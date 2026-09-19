"""Build lists: the structures each player's skirmish AI builds, where, and how.

A map keeps one build list per player, in player order: in the `BuildLists` chunk (filed under the
player's faction) when the map has an asset list, otherwise on each `SidesList` player. An entry
is a `BuildListInfo`; its `unknown` flag, stored only by version 6+ lists in maps with an asset
list, is what WorldBuilder's export calls AutomaticallyBuild.

Export and Import use WorldBuilder's text format (the strings beside `BuildList::OnExport`):

    ;Skirmish AI Build List
    SkirmishBuildList <side>
      Structure <template>
        Name = <name>
        Location = X:<x> Y:<y>
        Rebuilds = <count>
        Angle = <angle>
        InitiallyBuilt = Yes|No
        AutomaticallyBuild = Yes|No
      END ;Structure <template>
    END ;SkirmishBuildList <side>
"""

from __future__ import annotations

import math
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sage_map.assets.sides_list import BuildListInfo
from sage_map.map import Map
from sage_worldbuilder.changes import Change, ChangeKind
from sage_worldbuilder.commands.base import Command, CompositeCommand
from sage_worldbuilder.commands.edits import InsertItem, MoveItem, RemoveItem
from sage_worldbuilder.players import player_name

if TYPE_CHECKING:
    from sage_worldbuilder.document import MapDocument

__all__ = [
    "ImportedStructure",
    "MoveBuilding",
    "add_entry",
    "build_list_entries",
    "export_build_list",
    "import_entries",
    "move_entry",
    "new_entry",
    "parse_build_list",
    "remove_entry",
    "side_label",
    "side_names",
    "stores_automatic_build",
]

SIDES = Change(ChangeKind.SIDES)

# What a new entry starts with. Not read from WorldBuilder: these are the values a structure the
# AI simply builds needs (full health, not yet built, no rebuilds, sellable and repairable).
DEFAULT_HEALTH = 100
DEFAULT_REBUILDS = 0
DEFAULT_INITIALLY_BUILT = False
DEFAULT_AUTOMATICALLY_BUILD = True
DEFAULT_WHINER = True
DEFAULT_UNSELLABLE = False
DEFAULT_REPAIRABLE = True


def side_names(map: Map) -> list[str]:
    """The player each build list belongs to, in build list order."""
    players = map.sides_list.players if map.sides_list is not None else []
    count = len(map.build_lists.build_lists) if map.build_lists is not None else len(players)
    return [player_name(players[index]) if index < len(players) else "" for index in range(count)]


def side_label(map: Map, side: int) -> str:
    """A player name with the faction its build list is filed under, for pickers."""
    name = side_names(map)[side] or "(neutral)"
    if map.build_lists is not None and side < len(map.build_lists.build_lists):
        build_list = map.build_lists.build_lists[side]
        faction = build_list.faction_name
        if faction is None and build_list.faction_name_property is not None:
            faction = build_list.faction_name_property[2]
        if faction:
            return f"{name} ({faction})"
    return name


def _faction(map: Map, side: int) -> str:
    if map.build_lists is not None and side < len(map.build_lists.build_lists):
        build_list = map.build_lists.build_lists[side]
        if build_list.faction_name is not None:
            return build_list.faction_name
        if build_list.faction_name_property is not None:
            return build_list.faction_name_property[2] or ""
    return side_names(map)[side] if side < len(side_names(map)) else ""


def build_list_entries(map: Map, side: int) -> list[BuildListInfo] | None:
    """The entries of player `side`'s build list, the list itself so edits reach the map."""
    if map.build_lists is not None:
        lists = map.build_lists.build_lists
        return lists[side].build_list if 0 <= side < len(lists) else None
    players = map.sides_list.players if map.sides_list is not None else []
    return getattr(players[side], "build_list_items", None) if 0 <= side < len(players) else None


def stores_automatic_build(map: Map) -> bool:
    """Whether entries carry the AutomaticallyBuild flag (`BuildListInfo.unknown`)."""
    if map.asset_list is None:
        return False
    if map.build_lists is not None:
        return map.build_lists.version >= 6
    return map.sides_list is not None and map.sides_list.version >= 6


def new_entry(
    map: Map, template: str, location: tuple[float, float, float], angle: float = 0.0
) -> BuildListInfo:
    return BuildListInfo(
        build_name=template,
        template_name=template,
        location=location,
        angle=angle,
        is_initially_built=DEFAULT_INITIALLY_BUILT,
        num_rebuilds=DEFAULT_REBUILDS,
        script="",
        health=DEFAULT_HEALTH,
        whiner=DEFAULT_WHINER,
        unsellable=DEFAULT_UNSELLABLE,
        repairable=DEFAULT_REPAIRABLE,
        unknown=DEFAULT_AUTOMATICALLY_BUILD if stores_automatic_build(map) else None,
    )


def _entries_or_raise(map: Map, side: int) -> list[BuildListInfo]:
    entries = build_list_entries(map, side)
    if entries is None:
        raise ValueError(f"the map has no build list for player {side}")
    return entries


def add_entry(map: Map, side: int, entry: BuildListInfo, label: str = "Add Building") -> Command:
    entries = _entries_or_raise(map, side)
    return InsertItem(entries, len(entries), entry, SIDES, label)


def remove_entry(map: Map, side: int, index: int) -> Command:
    return RemoveItem(_entries_or_raise(map, side), index, SIDES, "Delete Building")


def move_entry(map: Map, side: int, index: int, step: int) -> Command | None:
    """Move an entry up (`step` -1) or down (+1) the build order; None at either end."""
    entries = _entries_or_raise(map, side)
    target = index + step
    if not (0 <= index < len(entries) and 0 <= target < len(entries)):
        return None
    return MoveItem(entries, index, entries, target, SIDES, "Reorder Building")


class MoveBuilding(Command):
    """Move a build list entry. A run of moves of the same entry merges until closed."""

    def __init__(self, entry: BuildListInfo, location: tuple[float, float, float]) -> None:
        self.entry = entry
        self.location = location
        self.label = "Move Building"
        self.closed = False
        self._before: tuple[float, float, float] | None = None

    def do(self, document: MapDocument) -> None:
        if self._before is None:
            self._before = self.entry.location
        self.entry.location = self.location

    def undo(self, document: MapDocument) -> None:
        assert self._before is not None
        self.entry.location = self._before

    def changes(self) -> tuple[Change, ...]:
        return (SIDES,)

    def merge(self, following: Command) -> bool:
        if self.closed or not (
            isinstance(following, MoveBuilding) and following.entry is self.entry
        ):
            return False
        self.location = following.location
        return True


def _yes(value: bool) -> str:
    return "Yes" if value else "No"


def export_build_list(map: Map, side: int) -> str:
    """Player `side`'s build list in WorldBuilder's export format. The angle is in degrees."""
    entries = _entries_or_raise(map, side)
    owner = _faction(map, side)
    lines = [";Skirmish AI Build List", f"SkirmishBuildList {owner}"]
    for entry in entries:
        x, y, _ = entry.location
        automatic = entry.unknown if entry.unknown is not None else DEFAULT_AUTOMATICALLY_BUILD
        lines += [
            f"  Structure {entry.template_name}",
            f"    Name = {entry.build_name}",
            f"    Location = X:{x:.2f} Y:{y:.2f}",
            f"    Rebuilds = {entry.num_rebuilds}",
            f"    Angle = {math.degrees(entry.angle):.2f}",
            f"    InitiallyBuilt = {_yes(entry.is_initially_built)}",
            f"    AutomaticallyBuild = {_yes(automatic)}",
            f"  END ;Structure {entry.template_name}",
        ]
    lines.append(f"END ;SkirmishBuildList {owner}")
    return "\n".join(lines) + "\n"


@dataclass(frozen=True)
class ImportedStructure:
    template: str
    name: str
    x: float
    y: float
    rebuilds: int
    angle_degrees: float
    initially_built: bool
    automatically_build: bool


_FIELD = re.compile(r"^\s*(\w+)\s*=\s*(.*?)\s*$")
_LOCATION = re.compile(r"X:\s*(-?[\d.]+)\s+Y:\s*(-?[\d.]+)")


def parse_build_list(text: str) -> list[ImportedStructure]:
    """The structures in an exported build list. Unreadable fields keep their defaults."""
    structures: list[ImportedStructure] = []
    fields: dict[str, str] | None = None
    template = ""
    for raw in text.splitlines():
        line = raw.split(";", 1)[0].strip()
        if not line:
            continue
        if line.startswith("Structure "):
            template, fields = line[len("Structure ") :].strip(), {}
            continue
        if line == "END" and fields is not None:
            structures.append(_structure(template, fields))
            fields = None
            continue
        match = _FIELD.match(line)
        if match and fields is not None:
            fields[match.group(1).lower()] = match.group(2)
    return structures


def _structure(template: str, fields: dict[str, str]) -> ImportedStructure:
    location = _LOCATION.search(fields.get("location", ""))
    x, y = (float(location.group(1)), float(location.group(2))) if location else (0.0, 0.0)

    def number(key: str, default: float) -> float:
        try:
            return float(fields.get(key, default))
        except ValueError:
            return default

    def flag(key: str, default: bool) -> bool:
        value = fields.get(key)
        return default if value is None else value.strip().lower() == "yes"

    return ImportedStructure(
        template=template,
        name=fields.get("name", template) or template,
        x=x,
        y=y,
        rebuilds=int(number("rebuilds", DEFAULT_REBUILDS)),
        angle_degrees=number("angle", 0.0),
        initially_built=flag("initiallybuilt", DEFAULT_INITIALLY_BUILT),
        automatically_build=flag("automaticallybuild", DEFAULT_AUTOMATICALLY_BUILD),
    )


def import_entries(map: Map, side: int, structures: Sequence[ImportedStructure]) -> Command:
    """Append imported structures to player `side`'s build list, as one edit."""
    entries = _entries_or_raise(map, side)
    commands: list[Command] = []
    for offset, structure in enumerate(structures):
        entry = new_entry(
            map,
            structure.template,
            (structure.x, structure.y, 0.0),
            math.radians(structure.angle_degrees),
        )
        entry.build_name = structure.name
        entry.num_rebuilds = structure.rebuilds
        entry.is_initially_built = structure.initially_built
        if entry.unknown is not None:
            entry.unknown = structure.automatically_build
        commands.append(InsertItem(entries, len(entries) + offset, entry, SIDES, "Import"))
    return CompositeCommand("Import Build List", commands)
