"""Record a live process's memory and replay it later, as a `MemorySource`.

Two uses, and the first is the reason this exists.

**A regression test only a real game can supply.** Every offset in `EngineLayout` was confirmed
once, by hand, against a running match. The synthetic image in the test suite cannot catch a
*wrong belief*: it writes its fields at the offsets the layout declares, so a wrong layout and
a wrong fixture cancel out and the test passes. Bytes taken from a real process cannot do that
- they were laid out by the engine, not by us.

**Offline development.** A snapshot is a real match that needs no game, no Windows and no
elevation to read, so a policy can be debugged against a genuine 400-object world on any
machine. `LoopbackBackend` answers the same need with hand-written observations; this answers
it with a recorded one.

**Ranges, not reads.** The recorder keeps the *address span* of each read and merges the spans,
so a replay serves any read landing inside a captured range - including reads of a different
size than the ones recorded. Keying on exact `(address, size)` pairs would freeze one read
pattern into the fixture, and batching those reads is an obvious future change that alters
every size while altering no address.

A snapshot is sparse by construction: it holds exactly the bytes the decode touched, which is
why it is measured in hundreds of kilobytes rather than the process's hundreds of megabytes.
"""

from __future__ import annotations

import bisect
import gzip
import struct
from pathlib import Path
from typing import Protocol

__all__ = ["MAGIC", "RecordingSource", "SnapshotSource", "encode_spans", "decode_spans"]

# Versioned, so a snapshot from an older layout of this file refuses rather than mis-parses.
MAGIC = b"SAGELIVESNAP\x00\x01"


class _Readable(Protocol):
    def read(self, address: int, size: int) -> bytes | None: ...

    def close(self) -> None: ...


def encode_spans(spans: list[tuple[int, bytes]]) -> bytes:
    body = bytearray(MAGIC)
    body += struct.pack("<I", len(spans))
    for base, data in spans:
        body += struct.pack("<II", base, len(data))
        body += data
    return bytes(body)


def decode_spans(blob: bytes) -> list[tuple[int, bytes]]:
    if not blob.startswith(MAGIC):
        raise ValueError("not a sage_live snapshot, or one written by another version")
    pos = len(MAGIC)
    (count,) = struct.unpack_from("<I", blob, pos)
    pos += 4
    spans: list[tuple[int, bytes]] = []
    for _ in range(count):
        base, size = struct.unpack_from("<II", blob, pos)
        pos += 8
        spans.append((base, blob[pos : pos + size]))
        pos += size
    return spans


class RecordingSource:
    """Wraps a `MemorySource`, remembering every byte range it served.

    Read-only on purpose: a capture that could write to the game would be a capture that
    changes what it is recording, so `write` raises rather than forwarding.
    """

    def __init__(self, inner: _Readable) -> None:
        self.inner = inner
        self.spans: list[tuple[int, bytes]] = []
        self.reads = 0
        self.bytes = 0

    def read(self, address: int, size: int) -> bytes | None:
        data = self.inner.read(address, size)
        self.reads += 1
        if data is not None:
            self.bytes += len(data)
            self.spans.append((address, data))
        return data

    def write(self, address: int, data: bytes) -> bool:
        raise AssertionError("a recording source is read-only")

    def close(self) -> None:
        self.inner.close()

    def merged(self) -> list[tuple[int, bytes]]:
        """Overlapping and adjacent spans coalesced into the fewest contiguous ranges.

        Later reads win where two spans overlap, which is what a caller re-reading a field
        after it changed would expect.
        """
        out: list[tuple[int, bytearray]] = []
        for base, data in sorted(self.spans, key=lambda span: span[0]):
            if out and base <= out[-1][0] + len(out[-1][1]):
                head_base, head = out[-1]
                start = base - head_base
                end = start + len(data)
                if end > len(head):
                    head.extend(b"\x00" * (end - len(head)))
                head[start:end] = data
            else:
                out.append((base, bytearray(data)))
        return [(base, bytes(data)) for base, data in out]

    def save(self, path: str | Path) -> int:
        """Write the snapshot, gzipped. Returns the file size in bytes."""
        target = Path(path)
        target.write_bytes(gzip.compress(encode_spans(self.merged()), 9))
        return target.stat().st_size


class SnapshotSource:
    """A `MemorySource` that replays a recorded snapshot.

    A read fully inside a captured range is served from it; anything else answers None, which
    is exactly how a real source reports an unreadable address. So a decode that starts
    following a *different* pointer chain than the capture did degrades to "unreadable" rather
    than to silently wrong bytes.
    """

    def __init__(self, spans: list[tuple[int, bytes]]) -> None:
        ordered = sorted(spans, key=lambda span: span[0])
        self._bases = [base for base, _ in ordered]
        self._data = [data for _, data in ordered]
        self.closed = False
        self.misses = 0

    @classmethod
    def load(cls, path: str | Path) -> SnapshotSource:
        return cls(decode_spans(gzip.decompress(Path(path).read_bytes())))

    def read(self, address: int, size: int) -> bytes | None:
        if size <= 0:
            return None
        index = bisect.bisect_right(self._bases, address) - 1
        if index < 0:
            self.misses += 1
            return None
        base, data = self._bases[index], self._data[index]
        start = address - base
        if start + size > len(data):
            self.misses += 1
            return None
        return data[start : start + size]

    def close(self) -> None:
        self.closed = True
