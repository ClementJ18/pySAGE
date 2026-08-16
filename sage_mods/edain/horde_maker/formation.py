"""The horde formation block of a `HordeContain`, as data.

A horde's shape is written as a list of `RankInfo` lines: one rank per row of the formation,
each naming the unit it is made of and the position of every soldier in it, plus a `Leader`
back-reference tying a soldier to the one it follows in the rank ahead. Written by hand, that
is a page of coordinates nobody can picture; `Slot` is the same thing as a flat list of units at
positions, which an editor can draw.

The coordinate frame is the game's own: **X is depth**, growing towards the front of the
formation, and **Y is lateral**, growing to the left of the centre line. Both are in world
units, so a `RankInfo` block written here drops straight into an object's `HordeContain`.

How wide each unit *is* decides whether a formation's soldiers overlap, and the block itself
never says: geometry lives on the object, not in the horde. `render_formation` can therefore
carry the diameters it was drawn with in a leading `; HordeMaker DotSizes` comment, which
`parse_sizes` reads back - the one thing an editor needs that the ini does not record. It is a
comment, so the game never sees it and a block without one is read just the same.

`render_formation` and `parse_formation` are inverses over the block's positions - what a
position's coordinates lose is the one decimal `render_formation` writes them to. Nothing here
raises on malformed text: a line it does not understand is a line it skips (CONVENTIONS.md
rule 4).

Qt-free, so the window in `ui/` and any script share it.
"""

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

__all__ = [
    "SIZES_COMMENT",
    "Slot",
    "parse_formation",
    "parse_sizes",
    "render_formation",
]

# Opens the comment line the unit diameters are recorded on, as `<unit>=<diameter>` tokens.
SIZES_COMMENT = "; HordeMaker DotSizes"

# A position, in either spelling the block uses: `Position:X:1.0 Y:2.0` for a rank member and
# `Pos:X:1.0 Y:2.0` for the banner carrier. Only the coordinates themselves are captured, so
# both forms - and any `Leader n i` sitting between two of them - read the same way.
_COORDINATES = re.compile(r"X:(-?\d+(?:\.\d+)?)\s+Y:(-?\d+(?:\.\d+)?)")

# The object the line places. Anchored on the keyword, so the `X:`/`Y:` that follow cannot be
# mistaken for it.
_UNIT = re.compile(r"UnitType:(\S+)")


@dataclass(frozen=True)
class Slot:
    """One soldier of the horde: the object it is, and where it stands. `banner` marks the
    single banner carrier, which the block places on its own line rather than in a rank."""

    unit: str
    x: float
    y: float
    banner: bool = False


def render_formation(slots: Iterable[Slot], sizes: Mapping[str, float] | None = None) -> str:
    """The `HordeContain` formation block for `slots`: the slot count, an `InitialPayload` per
    unit, the banner carrier's own two lines, and the `RankInfo` lines themselves. `sizes`, if
    given, records each unit's diameter in a leading `SIZES_COMMENT` line, so a block reopened in
    an editor is drawn at the scale it was laid out at.

    Ranks are the rows of one unit, front (largest X) first, and are numbered in one run across
    the units so a rank number identifies a row of the whole horde. Within a rank, soldiers are
    ordered left to right, and each takes the soldier standing at its index in the rank ahead as
    its `Leader` - the tie the engine uses to keep a marching horde in shape. A rank longer than
    the one ahead leaves its extra soldiers leaderless, which is what the engine expects."""
    ranked: list[Slot] = []
    banner: Slot | None = None
    for slot in slots:
        if slot.banner and banner is None:
            banner = slot
        else:
            ranked.append(slot)

    by_unit = _by_unit(ranked)
    lines: list[str] = []
    if sizes:
        tokens = " ".join(f"{unit}={size:.1f}" for unit, size in sizes.items())
        lines += [f"{SIZES_COMMENT} {tokens}", ""]
    lines += [f"Slots = {len(ranked)}", ""]
    lines += [f"InitialPayload = {unit} {len(members)}" for unit, members in by_unit.items()]
    lines.append("")
    if banner is not None:
        lines += [
            f"BannerCarriersAllowed = {banner.unit}",
            f"BannerCarrierPosition = UnitType:{banner.unit} Pos:{_position(banner)}",
            "",
        ]
    lines += _rank_lines(by_unit)
    return "\n".join(lines).rstrip("\n") + "\n"


def parse_formation(text: str) -> list[Slot]:
    """The slots `text` places - its `RankInfo` lines and its `BannerCarrierPosition`, in the
    order they are written. Every other line (the payload, the slot count, comments, whatever
    else the object's block carries) is ignored, so a whole `HordeContain` can be pasted in as
    it stands."""
    slots: list[Slot] = []
    for raw in text.splitlines():
        line = _strip_comment(raw)
        banner = line.startswith("BannerCarrierPosition")
        if not banner and not line.startswith("RankInfo"):
            continue
        found = _UNIT.search(line)
        if found is None:
            continue
        unit = found.group(1)
        slots += [
            Slot(unit=unit, x=float(x), y=float(y), banner=banner)
            for x, y in _COORDINATES.findall(line)
        ]
    return slots


def parse_sizes(text: str) -> dict[str, float]:
    """The unit diameters `text` records on its `SIZES_COMMENT` line, if it carries one - a block
    written elsewhere simply has none, and an editor keeps whatever sizes it already had. A token
    that is not a `<unit>=<number>` pair is skipped rather than failing the read."""
    sizes: dict[str, float] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line.startswith(SIZES_COMMENT):
            continue
        for token in line[len(SIZES_COMMENT) :].split():
            unit, marker, written = token.partition("=")
            if not unit or not marker:
                continue
            try:
                sizes[unit] = float(written)
            except ValueError:
                continue
    return sizes


def _strip_comment(line: str) -> str:
    """`line` without its trailing comment, in either syntax the ini files use."""
    for marker in (";", "//"):
        cut = line.find(marker)
        if cut >= 0:
            line = line[:cut]
    return line.strip()


def _position(slot: Slot) -> str:
    return f"X:{slot.x:.1f} Y:{slot.y:.1f}"


def _by_unit(slots: Sequence[Slot]) -> dict[str, list[Slot]]:
    """The slots grouped by the object they are, in the order the units first appear - the order
    the payload and the ranks are then written in, so a re-render keeps the block's own layout."""
    grouped: dict[str, list[Slot]] = {}
    for slot in slots:
        grouped.setdefault(slot.unit, []).append(slot)
    return grouped


def _rank_lines(by_unit: Mapping[str, Sequence[Slot]]) -> list[str]:
    lines: list[str] = []
    rank = 0
    for unit, members in by_unit.items():
        ahead: list[Slot] = []
        ahead_rank = 0
        for depth in sorted({slot.x for slot in members}, reverse=True):
            row = sorted((s for s in members if s.x == depth), key=lambda s: -s.y)
            rank += 1
            parts = []
            for index, slot in enumerate(row):
                leader = f" Leader {ahead_rank} {index}" if index < len(ahead) else ""
                parts.append(f"Position:{_position(slot)}{leader}")
            lines.append(f"RankInfo = RankNumber:{rank} UnitType:{unit} {' '.join(parts)}")
            ahead, ahead_rank = row, rank
        lines.append("")
    return lines
