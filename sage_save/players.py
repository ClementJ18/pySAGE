"""Signature harvest of the *fatal* ini-name classes in `CHUNK_Players` (and object bodies).

`sage_save.chunks.decode_players` now walks each player record structurally down to the team
vector — the upgrade masks it decodes are these same structures — but each record's *tail*
(the acquired-science vector, hero roster, build lists) is still opaque bytes, so this scan
remains the harvest that reaches them. It extracts the two name-bearing structures by their
exact on-wire signature: the **upgrade mask** (`xferUpgradeMask`: `u8 version=1 + u16 count +
ascii names`) and **science vector** (`u8 version=1 + u32 count + ascii names`). A candidate
is accepted only when its version byte is 1, its count is in a small range, every entry is a
well-formed definition name, and at least one entry carries the class's conventional prefix
(`Upgrade_` / `SCIENCE_`). The structured mask decode doubles as this scan's oracle (and vice
versa): a divergence between the two is a test failure, not a silent drift.

Names in these lists are **fatal** cross-references: unlike the skip-tolerated object templates,
a dangling upgrade or science is `XFER_UNKNOWN_STRING` and aborts the load. Limitation: a list
whose entries all lack the conventional prefix is not recognised — walking the record tail
(the remaining Task 5 slice) would retire the heuristic entirely. See sav_format.md.
"""

import struct
from dataclasses import dataclass

from sage_save.save import Chunk

_NAME_CHARS = frozenset(b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_")
_MAX_COUNT = 128
_MAX_NAME = 64

# (kind, count-field width in bytes, conventional prefix) for each harvested name list.
_LIST_KINDS = (
    ("upgrade", 2, "Upgrade_"),
    ("science", 4, "SCIENCE_"),
)


@dataclass(frozen=True)
class NameList:
    """One recognised name list in `CHUNK_Players`: a player's upgrade mask or science vector."""

    kind: str  # "upgrade" | "science"
    names: list[str]
    offset: int  # where the version byte sits in the payload (for reporting/debugging)


def _read_names(payload: bytes, offset: int, count: int) -> tuple[list[str], int] | None:
    """Read `count` uint8-length ASCII names from `offset`, or None if any is malformed."""
    names: list[str] = []
    pos = offset
    for _ in range(count):
        if pos >= len(payload):
            return None
        length = payload[pos]
        if not (1 <= length <= _MAX_NAME) or pos + 1 + length > len(payload):
            return None
        raw = payload[pos + 1 : pos + 1 + length]
        if not all(byte in _NAME_CHARS for byte in raw):
            return None
        names.append(raw.decode("ascii"))
        pos += 1 + length
    return names, pos


def _scan(payload: bytes, kind: str, width: int, prefix: str) -> list[NameList]:
    fmt = "<H" if width == 2 else "<I"
    found: list[NameList] = []
    for offset in range(len(payload) - (1 + width)):
        if payload[offset] != 1:  # version byte
            continue
        count = struct.unpack_from(fmt, payload, offset + 1)[0]
        if not (1 <= count <= _MAX_COUNT):
            continue
        result = _read_names(payload, offset + 1 + width, count)
        if result is None:
            continue
        names, _ = result
        if any(name.startswith(prefix) for name in names):
            found.append(NameList(kind, names, offset))
    return found


def harvest_name_lists(chunk: Chunk) -> list[NameList]:
    """Every upgrade mask and science vector recognised in a `CHUNK_Players` payload."""
    return [
        name_list
        for kind, width, prefix in _LIST_KINDS
        for name_list in _scan(chunk.payload, kind, width, prefix)
    ]
