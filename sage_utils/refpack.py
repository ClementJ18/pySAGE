"""Codec for EA's RefPack (LZSS) compression, used by the SAGE engine's binary
`.map`/`.bse` asset layer.

Decompression is always pure Python: it is fast (milliseconds) and cross-platform.

Compression prefers a native backend (the `reversebox` package) when it is importable and
passes a self-test, because the pure-Python compressor runs EA's exact O(n^2) hash-chain
search and can take tens of seconds on large, repetitive maps. reversebox's bundled DLL is
Windows-only, so it is a base dependency there and absent everywhere else; off Windows, and
whenever the DLL cannot load, compression falls back to the pure-Python compressor and emits
a one-time `RefpackPerformanceWarning`.

The pure-Python compressor is a faithful port of the reference C++ encoder (hash-chain
match finding, identical tie-breaks and command encoding), so it reproduces the reference
encoder's output byte-for-byte on real game data. That byte-exact parity - shared by the
native backend, which is the same algorithm at the same settings - is what lets `sage_map`
re-save a map identical to the original file on disk, whichever backend runs.
"""

import sys
import warnings
from array import array
from collections.abc import Callable

__all__ = ["compress", "decompress", "RefpackError", "RefpackPerformanceWarning"]

MAGIC_SECOND_BYTE = 0xFB
MAX_WINDOW = 131072  # sliding window: back-references reach at most this far
MAX_MATCH = 1028  # longest single back-reference the format can encode


class RefpackError(ValueError):
    """A RefPack stream is malformed or cannot be represented in this format."""


class RefpackPerformanceWarning(UserWarning):
    """The native RefPack accelerator is unavailable, so the slower pure-Python
    compressor is in use. Correctness is unaffected - only compression speed."""


def decompress(data: bytes) -> bytes:
    """Decode a full RefPack stream (header + command body) to raw bytes."""
    if len(data) < 6:
        raise RefpackError(f"RefPack stream too short to hold a header: {len(data)} bytes")
    first, second = data[0], data[1]
    if second != MAGIC_SECOND_BYTE:
        raise RefpackError(f"not a RefPack stream: bad magic {data[:2]!r}")
    flags = (first << 8) | second
    size_width = 4 if flags & 0x8000 else 3
    pos = 2
    if flags & 0x0100:
        pos += size_width  # a compressed-size field we don't need
    if pos + size_width > len(data):
        raise RefpackError("RefPack stream too short to hold its size field")
    unpacked_size = int.from_bytes(data[pos : pos + size_width], "big")
    pos += size_width
    return _decompress_body(data, pos, unpacked_size)


def _decompress_body(data: bytes, pos: int, unpacked_size: int) -> bytes:
    out = bytearray(unpacked_size)
    n = len(data)
    di = 0
    try:
        while True:
            if pos >= n:
                raise RefpackError("RefPack stream ends mid-command")
            first = data[pos]
            pos += 1
            if not (first & 0x80):  # short form: f=0..1023, n=3..10, d=0..3
                second = data[pos]
                pos += 1
                run = first & 3
                out[di : di + run] = data[pos : pos + run]
                di += run
                pos += run
                distance = ((first & 0x60) << 3) + second + 1
                length = ((first & 0x1C) >> 2) + 3
                di = _copy_ref(out, di, distance, length)
                continue
            if not (first & 0x40):  # long form: f=0..16384, n=4..67, d=0..3
                second = data[pos]
                third = data[pos + 1]
                pos += 2
                run = second >> 6
                out[di : di + run] = data[pos : pos + run]
                di += run
                pos += run
                distance = ((second & 0x3F) << 8) + third + 1
                length = (first & 0x3F) + 4
                di = _copy_ref(out, di, distance, length)
                continue
            if not (first & 0x20):  # very long form: f=0..131071, n=5..1028, d=0..3
                second = data[pos]
                third = data[pos + 1]
                fourth = data[pos + 2]
                pos += 3
                run = first & 3
                out[di : di + run] = data[pos : pos + run]
                di += run
                pos += run
                distance = (((first & 0x10) >> 4) << 16) + (second << 8) + third + 1
                length = (((first & 0x0C) >> 2) << 8) + fourth + 5
                di = _copy_ref(out, di, distance, length)
                continue
            run = ((first & 0x1F) << 2) + 4  # literal run, d=4..112, or eof, d=0..3
            if run <= 112:
                out[di : di + run] = data[pos : pos + run]
                di += run
                pos += run
                continue
            run = first & 3
            out[di : di + run] = data[pos : pos + run]
            di += run
            pos += run
            break
    except IndexError as exc:
        raise RefpackError("RefPack stream ends mid-command") from exc
    if di != unpacked_size or len(out) != unpacked_size:
        raise RefpackError(
            f"RefPack stream decoded to {di} bytes (buffer length {len(out)}), "
            f"expected the declared {unpacked_size}"
        )
    return bytes(out)


def _copy_ref(out: bytearray, di: int, distance: int, length: int) -> int:
    """Copy `length` bytes from `distance` back into `out` at `di`, LZ-style.

    The source and destination ranges can overlap (distance < length) - that overlap
    is how RefPack encodes runs, so each chunk must only pull from bytes already
    written, in chunks no larger than `distance` to keep every slice copy correct.
    """
    if distance > di:
        raise RefpackError(
            "RefPack back-reference reaches before the start of the output "
            f"(distance {distance} at output offset {di})"
        )
    ref = di - distance
    if distance >= length:
        out[di : di + length] = out[ref : ref + length]
        return di + length
    remaining = length
    while remaining > 0:
        chunk = min(distance, remaining)
        out[di : di + chunk] = out[ref : ref + chunk]
        di += chunk
        ref += chunk
        remaining -= chunk
    return di


def compress(data: bytes) -> bytes:
    """Encode raw bytes into a full RefPack stream (header + command body).

    Uses the native accelerator when it is available (see the module docstring),
    otherwise the pure-Python compressor, warning once. Both produce byte-identical
    output, so the choice never changes the bytes on disk - only the speed.
    """
    # Checked here, ahead of the native DLL, because the DLL writes a 3-byte size
    # field and would silently truncate an oversized input instead of rejecting it.
    if len(data) > 0xFFFFFF:
        raise RefpackError(f"input too large for a 3-byte RefPack size field: {len(data)} bytes")
    if data:
        native = _native_compressor()
        if native is not None:
            return native(data)
    return _compress_pure(data)


def _compress_pure(data: bytes) -> bytes:
    """The guaranteed, cross-platform RefPack compressor.

    Reproduces the reference RefPack compressor's match selection and command
    encoding exactly, so the output is byte-for-byte identical to a stream produced
    by EA's own tools for the same input.
    """
    size = len(data)
    if size > 0xFFFFFF:
        raise RefpackError(f"input too large for a 3-byte RefPack size field: {size} bytes")
    header = b"\x10\xfb" + size.to_bytes(3, "big")
    return header + _compress_body(data)


_native_probed: bool = False
_native_compress_fn: Callable[[bytes], bytes] | None = None


def _native_compressor() -> Callable[[bytes], bytes] | None:
    """Return a working native `compress_data` callable, or None (probed once).

    The `reversebox` package wraps EA's reference codec as a compiled DLL. We accept it
    only if a self-test shows it emits the same bytes as the pure-Python compressor for
    the same input - a round-trip alone isn't enough, since a backend that decompresses
    fine but encodes differently would break the byte-identical-output contract. A
    missing package, an unloadable DLL (the bundled build is Windows-only), or a failed
    parity check all degrade transparently to the pure-Python path.
    """
    global _native_probed, _native_compress_fn
    if _native_probed:
        return _native_compress_fn
    _native_probed = True
    try:
        from reversebox.compression.compression_refpack import (  # noqa: PLC0415 - lazy: Windows-only dep
            RefpackHandler,
        )
    except ImportError:
        _warn_fallback("the native accelerator is not installed")
        return None
    handler = RefpackHandler()
    probe = b"RefPack native backend self-test probe " * 4
    try:
        ok = handler.compress_data(probe) == _compress_pure(probe)
    except Exception as exc:  # noqa: BLE001 - any native failure must fall back safely
        _warn_fallback(f"the native accelerator is not usable ({exc})")
        return None
    if not ok:
        _warn_fallback("the native accelerator failed its self-test")
        return None
    _native_compress_fn = handler.compress_data
    return _native_compress_fn


def _warn_fallback(reason: str) -> None:
    # The remedy differs by platform: on Windows the accelerator is a base dependency, so its
    # absence means a broken install; elsewhere the pure-Python path is the only one there is.
    remedy = (
        "Reinstalling pysage-tools should restore it."
        if sys.platform == "win32"
        else "The native accelerator is Windows-only, so this is expected here."
    )
    warnings.warn(
        f"RefPack compression is using the pure-Python codec ({reason}); this can be slow "
        f"on large maps, though the output is byte-identical. {remedy}",
        RefpackPerformanceWarning,
        stacklevel=2,
    )


def _matchlen(data: bytes, s: int, d: int, maxmatch: int, lo: int = 0) -> int:
    """Length of the common prefix of `data[s:]` and `data[d:]`, capped at `maxmatch`.

    Binary search over slice comparisons: since a matching prefix of length L implies
    every shorter prefix also matches, the match/mismatch outcome is monotonic in the
    tried length, so bisecting finds the exact boundary in O(log maxmatch) memcmp-speed
    comparisons instead of a byte-at-a-time Python loop.

    `lo` seeds the search with a prefix length already known to match (e.g. from a
    cheaper probe by the caller), skipping the low end of the search; it's clamped to
    `maxmatch` so the result never exceeds the cap even when the known prefix is longer
    than `maxmatch` allows.
    """
    lo = min(lo, maxmatch)
    hi = maxmatch
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if data[s : s + mid] == data[d : d + mid]:
            lo = mid
        else:
            hi = mid - 1
    return lo


def _compress_body(data: bytes) -> bytes:
    n = len(data)
    out = bytearray()
    hashtbl = [-1] * 65536
    link = [-1] * MAX_WINDOW
    MASK = MAX_WINDOW - 1

    # Any pure function of 3 bytes is fine: hash collisions are filtered downstream
    # by the match-length check, so this need not be a "good" hash. Every position's
    # hash is precomputed once up front - a single array lookup per chain insertion -
    # rather than recomputed on each of the many times a position is touched; z1/z2
    # are data shifted left by one/two bytes with zero padding, reproducing the same
    # zero-past-the-end reads as looking up bytes i+1/i+2 near the tail of data.
    z1 = data[1:] + b"\x00"
    z2 = data[2:] + b"\x00\x00"
    # For inputs shorter than the 3-byte hash width the padding leaves z1/z2 longer
    # than data, so zip is deliberately not strict: it stops at data's length.
    hashes = array(
        "H", (((a << 8) ^ (b << 4) ^ c) & 0xFFFF for a, b, c in zip(data, z1, z2, strict=False))
    )

    run = 0
    cptr = 0
    rptr = 0
    remaining = n

    while remaining > 0:
        boffset = 0
        blen = 2
        bcost = 2
        # The EA encoder that produced the SAGE maps (and the reference DLL we match)
        # never lets a match consume the last 4 bytes of the input, reserving them for
        # the literal/EOF tail. Capping the match length at `remaining - 4` reproduces
        # that exact termination; without it the final match runs a few bytes longer
        # and the encoded tail diverges from EA's bytes (verified: the streams are
        # otherwise byte-identical up to the last command on every map fixture).
        mlen = min(remaining - 4, MAX_MATCH)

        hash_ = hashes[cptr]
        hoffset = hashtbl[hash_]
        minhoffset = max(cptr - (MAX_WINDOW - 1), 0)

        if hoffset >= minhoffset:
            ci = cptr + blen
            while True:
                tptr = hoffset
                # A candidate can only improve on blen if it matches the current best on
                # every byte through index blen, so it is probed in two stages, cheapest
                # first: a single-byte check at index blen (which rejects almost every
                # candidate at O(1)), then one slice compare over the rest of the prefix.
                # Only a candidate that passes both - guaranteed to beat blen - pays for
                # the binary search, seeded with the prefix already known to match.
                # Reading past the input can never satisfy the probe (matchlen is bounded
                # by mlen <= remaining), so it's treated as a miss, like a value mismatch.
                if (
                    ci < n
                    and data[ci] == data[tptr + blen]
                    and data[cptr:ci] == data[tptr : tptr + blen]
                ):
                    tlen = _matchlen(data, cptr, tptr, mlen, blen + 1)
                    if tlen > blen:
                        toffset = (cptr - 1) - tptr
                        if toffset < 1024 and tlen <= 10:
                            tcost = 2
                        elif toffset < 16384 and tlen <= 67:
                            tcost = 3
                        else:
                            tcost = 4
                        if tlen - tcost > blen - bcost:
                            blen, bcost, boffset = tlen, tcost, toffset
                            ci = cptr + blen
                            # Once the best match hits the per-position cap, every
                            # later candidate is measured against the same cap and so
                            # can never come back longer - further chain links can
                            # only tie or lose, so the walk stops here.
                            if blen >= mlen:
                                break
                hoffset = link[hoffset & MASK]
                if hoffset < minhoffset:
                    break

        if bcost >= blen:
            link[cptr & MASK] = hashtbl[hash_]
            hashtbl[hash_] = cptr
            run += 1
            cptr += 1
            remaining -= 1
            continue

        while run > 3:
            tlen = min(112, run & ~3)
            run -= tlen
            out.append(0xE0 + (tlen >> 2) - 1)
            out += data[rptr : rptr + tlen]
            rptr += tlen

        if bcost == 2:
            out.append(((boffset >> 8) << 5) + ((blen - 3) << 2) + run)
            out.append(boffset & 0xFF)
        elif bcost == 3:
            out.append(0x80 + (blen - 4))
            out.append(((run << 6) + (boffset >> 8)) & 0xFF)
            out.append(boffset & 0xFF)
        else:
            out.append(0xC0 + ((boffset >> 16) << 4) + (((blen - 5) >> 8) << 2) + run)
            out.append((boffset >> 8) & 0xFF)
            out.append(boffset & 0xFF)
            out.append((blen - 5) & 0xFF)

        if run:
            out += data[rptr : rptr + run]
            run = 0

        for i in range(cptr, cptr + blen):
            h = hashes[i]
            link[i & MASK] = hashtbl[h]
            hashtbl[h] = i
        cptr += blen

        rptr = cptr
        remaining -= blen

    while run > 3:
        tlen = min(112, run & ~3)
        run -= tlen
        out.append(0xE0 + (tlen >> 2) - 1)
        out += data[rptr : rptr + tlen]
        rptr += tlen

    out.append(0xFC + run)
    if run:
        out += data[rptr : rptr + run]

    return bytes(out)
