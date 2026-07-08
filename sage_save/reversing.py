"""Reversing aids for the still-opaque chunks: a nested-`KOLB`-block tree and a cross-save differ.

Every step of the decoding plan leans on two questions about an undecoded chunk: *what is its
block structure* and *where do two saves diverge inside it*. `nested_block_tree` answers the
first by locating the BFME `KOLB` composite blocks in a payload (each `[ascii name] + "KOLB" +
uint32 absolute-end-offset`) and nesting them by containment — turning a wall of bytes into the
named tree the format actually is. `first_difference` / `format_divergence` answer the second by
aligning the same chunk from two saves and showing the first byte that differs, which is how the
single-sample ambiguities (the `GameState` fixed regions, the `GameLogic` preamble) get pinned
down as the corpus grows.

Block detection is deliberately a *heuristic scan* for the `KOLB` marker (validated by a
plausible in-range end offset), not a grammar-aware walk: it works on chunks no decoder
understands yet, at the cost of the occasional false marker in binary payloads. That trade is
right for a reversing tool — it never has to be told the layout first.
"""

from dataclasses import dataclass

from sage_save.save import BLOCK_MARKER

_NAME_MAX = 40  # longest plausible block name to look back for before a marker


@dataclass(frozen=True)
class NestedBlock:
    """One `KOLB` composite block found in a payload: the offset of its marker, the ascii name
    written just before it (if any), the range its body spans, and its nesting depth."""

    marker_offset: int  # payload offset of the "KOLB" marker
    name: str | None  # the length-prefixed ascii name immediately before the marker, if present
    payload_start: int  # first body byte (past the marker + end-offset field)
    end: int  # payload-relative end of the block
    depth: int  # 0 for a top-level block, +1 per enclosing block

    @property
    def size(self) -> int:
        """The block body's byte length."""
        return self.end - self.payload_start


def _read_name_before(payload: bytes, marker_offset: int) -> str | None:
    """The length-prefixed ascii block name ending right before `marker_offset`, or None. BFME
    writes named composites as `uint8 len + name + "KOLB"`, so the name (when present) sits
    immediately before the marker."""
    for length in range(1, _NAME_MAX + 1):
        length_pos = marker_offset - length - 1
        if length_pos < 0:
            break
        if payload[length_pos] != length:
            continue
        name = payload[length_pos + 1 : marker_offset]
        if all(32 <= byte < 127 for byte in name):
            return name.decode("ascii")
    return None


def nested_block_tree(payload: bytes, base_offset: int) -> list[NestedBlock]:
    """Every `KOLB` block in `payload`, in offset order, with nesting depth by containment.

    `base_offset` is the absolute file position of `payload[0]` (a chunk's `payload_offset`),
    needed because the stored end-offsets are absolute. A marker is accepted only when its end
    offset lands past the marker and within the payload — enough to reject most stray `KOLB`
    byte sequences in binary data."""
    found: list[tuple[int, str | None, int, int]] = []
    search = 0
    while True:
        marker_offset = payload.find(BLOCK_MARKER, search)
        if marker_offset < 0:
            break
        search = marker_offset + 1
        payload_start = marker_offset + len(BLOCK_MARKER) + 4
        if payload_start > len(payload):
            continue
        end_absolute = int.from_bytes(payload[marker_offset + 4 : payload_start], "little")
        end = end_absolute - base_offset
        if not (payload_start <= end <= len(payload)):
            continue  # end offset out of range → not a real block header
        found.append((marker_offset, _read_name_before(payload, marker_offset), payload_start, end))

    blocks: list[NestedBlock] = []
    for marker_offset, name, payload_start, end in found:
        # Depth = how many earlier blocks strictly enclose this one's body range.
        depth = sum(
            1
            for other_off, _n, other_start, other_end in found
            if other_start <= marker_offset and end <= other_end and other_off != marker_offset
        )
        blocks.append(NestedBlock(marker_offset, name, payload_start, end, depth))
    return blocks


def format_block_tree(blocks: list[NestedBlock], *, limit: int | None = None) -> list[str]:
    """Indented one-line-per-block rendering of `nested_block_tree`, capped at `limit` lines."""
    lines: list[str] = []
    shown = blocks if limit is None else blocks[:limit]
    for block in shown:
        indent = "  " * block.depth
        label = block.name if block.name is not None else "<unnamed>"
        lines.append(f"{indent}{label} @{block.marker_offset:,} size={block.size:,}")
    if limit is not None and len(blocks) > limit:
        lines.append(f"... {len(blocks) - limit:,} more block(s)")
    return lines


def first_difference(a: bytes, b: bytes) -> int | None:
    """The offset of the first byte at which `a` and `b` differ (or the shorter length when one
    is a prefix of the other), or None if they are identical."""
    if a == b:
        return None
    limit = min(len(a), len(b))
    for offset in range(limit):
        if a[offset] != b[offset]:
            return offset
    return limit  # identical up to the shorter one, which is then a prefix of the longer


def format_divergence(
    a: bytes, b: bytes, at: int, *, before: int = 8, width: int = 24
) -> list[str]:
    """A short aligned hexdump of both byte strings around their first divergence at `at`."""
    start = max(0, at - before)
    return [
        f"first difference at byte {at:,} (0x{at:x});  A is {len(a):,} bytes, B is {len(b):,}",
        f"  window from {start:,} (divergence at the offset above):",
        f"  A: {a[start : at + width].hex(' ')}",
        f"  B: {b[start : at + width].hex(' ')}",
    ]
