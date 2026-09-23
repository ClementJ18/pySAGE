"""The Edit menu's selection helpers: which objects Select Similar, Select Duplicate Objects,
Select Objects w/bad teams, Select Deprecated Objects, Select Missing Objects and Select Base
Object(s) pick, and the command Replace Selected issues."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import TYPE_CHECKING

from sage_map.assets.object_list import Object
from sage_map.map import Map
from sage_worldbuilder.anchors import RotationAnchors, shown_position
from sage_worldbuilder.changes import Change, ChangeKind
from sage_worldbuilder.commands.base import CompositeCommand, SetAttribute
from sage_worldbuilder.teams import qualified_team_name, team_list

if TYPE_CHECKING:
    from sage_ini.model.game import Game

__all__ = [
    "TemplateIndex",
    "base_parents",
    "base_siblings",
    "deprecated_objects",
    "duplicate_objects",
    "missing_objects",
    "objects_with_bad_teams",
    "replace_objects",
    "similar_objects",
]

OBJECTS = Change(ChangeKind.OBJECTS)
# Editor-only types (waypoints, generic AI objects) have no template in the game data.
_EDITOR_PREFIX = "*"


def _objects(map: Map) -> list[Object]:
    return list(map.objects_list.object_list) if map.objects_list is not None else []


class TemplateIndex:
    """The game's object templates by name, ignoring case as the engine does."""

    def __init__(self, game: Game) -> None:
        self._by_name = {name.lower(): template for name, template in game.objects.items()}

    def get(self, name: str) -> object | None:
        return self._by_name.get(name.lower())


def _flag(obj: Object, key: str) -> bool:
    stored = obj.properties.get(key)
    return bool(stored["value"]) if stored is not None else False


def _text(obj: Object, key: str) -> str:
    stored = obj.properties.get(key)
    value = stored["value"] if stored is not None else ""
    return value if isinstance(value, str) else ""


def _base_names(selected: Iterable[Object]) -> set[str]:
    return {name.lower() for obj in selected if (name := _text(obj, "objectBaseName"))}


def base_siblings(map: Map, selected: Iterable[Object]) -> list[Object]:
    """Select Base Object(s) > all siblings of current: every object of the same base as one of
    `selected`. The objects of a base share an `objectBaseName`, the base the game builds them
    as (the name a `.bse` file's castle templates are written under)."""
    names = _base_names(selected)
    return [obj for obj in _objects(map) if _text(obj, "objectBaseName").lower() in names]


def base_parents(map: Map, selected: Iterable[Object]) -> list[Object]:
    """Select Base Object(s) > parent of current: the object each of `selected` belongs to, the
    one flagged `objectIsABase` whose name is their base's."""
    names = _base_names(selected)
    return [
        obj
        for obj in _objects(map)
        if _flag(obj, "objectIsABase") and _text(obj, "objectName").lower() in names
    ]


def similar_objects(map: Map, selected: Iterable[Object]) -> list[Object]:
    """Every object of the same type as one of `selected`."""
    types = {obj.type_name.lower() for obj in selected}
    return [obj for obj in _objects(map) if obj.type_name.lower() in types]


def duplicate_objects(
    map: Map, tolerance: float = 1.0, anchors: RotationAnchors | None = None
) -> list[Object]:
    """Objects of the same type standing within `tolerance` world units of an earlier one; the
    first of each group is left out, so deleting the result keeps one of each. Where an object
    stands follows `anchors` (`shown_position`): castle walls share one stored pivot but not a
    place."""
    seen: dict[tuple[str, int, int], list[tuple[float, float]]] = {}
    duplicates: list[Object] = []
    for obj in _objects(map):
        x, y, _ = shown_position(obj, anchors)
        cell = (obj.type_name.lower(), round(x / tolerance), round(y / tolerance))
        nearby = [
            (ox, oy)
            for dx in (-1, 0, 1)
            for dy in (-1, 0, 1)
            for ox, oy in seen.get((cell[0], cell[1] + dx, cell[2] + dy), [])
            if abs(ox - x) <= tolerance and abs(oy - y) <= tolerance
        ]
        if nearby:
            duplicates.append(obj)
        seen.setdefault(cell, []).append((x, y))
    return duplicates


def objects_with_bad_teams(map: Map) -> list[Object]:
    """Objects whose `originalOwner` names a team the map does not have."""
    teams = {qualified_team_name(team).lower() for team in team_list(map) or []}
    bad = []
    for obj in _objects(map):
        stored = obj.properties.get("originalOwner")
        owner = str(stored["value"]) if stored is not None else ""
        if owner and owner.lower() not in teams:
            bad.append(obj)
    return bad


def deprecated_objects(map: Map, templates: TemplateIndex) -> list[Object]:
    """Objects whose template is sorted as OBSOLETE."""
    found = []
    for obj in _objects(map):
        template = templates.get(obj.type_name)
        sortings = getattr(template, "EditorSorting", None) or []
        if any(
            getattr(sorting, "name", str(sorting)).upper() == "OBSOLETE" for sorting in sortings
        ):
            found.append(obj)
    return found


def missing_objects(map: Map, templates: TemplateIndex) -> list[Object]:
    """Objects whose type the game data does not define (the ones WorldBuilder offers to replace
    when it loads a map)."""
    return [
        obj
        for obj in _objects(map)
        if not obj.type_name.startswith(_EDITOR_PREFIX) and templates.get(obj.type_name) is None
    ]


def replace_objects(objects: Sequence[Object], type_name: str) -> CompositeCommand:
    """Replace Selected: the objects become `type_name`, keeping everything else they store."""
    return CompositeCommand(
        "Replace Selected",
        [
            SetAttribute(obj, "type_name", type_name, OBJECTS, "Replace Selected")
            for obj in objects
            if obj.type_name != type_name
        ],
    )
