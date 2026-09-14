"""The Item List: the map's placed objects, waypoints, trigger areas and teams, searchable."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from sage_map.map import Map
from sage_worldbuilder.teams import qualified_team_name, team_list

__all__ = ["ItemKind", "ItemRow", "item_position", "map_items"]


class ItemKind(StrEnum):
    OBJECT = "Object"
    WAYPOINT = "Waypoint"
    AREA = "Area"
    TEAM = "Team"


@dataclass(frozen=True)
class ItemRow:
    kind: ItemKind
    name: str
    detail: str
    # The map object behind the row (a placed object, an area or a team).
    source: object


def _text(properties: dict, key: str) -> str:
    stored = properties.get(key)
    return str(stored["value"]) if stored is not None and stored["value"] else ""


def item_position(row: ItemRow) -> tuple[float, float] | None:
    """Where an item is in world units: an object's position, the centre of an area's points,
    or None for a team or an area without points."""
    source = row.source
    if row.kind in (ItemKind.OBJECT, ItemKind.WAYPOINT):
        x, y, _ = source.position  # type: ignore[attr-defined]
        return float(x), float(y)
    if row.kind is ItemKind.AREA:
        points = getattr(source, "points", [])
        if not points:
            return None
        return (
            sum(point[0] for point in points) / len(points),
            sum(point[1] for point in points) / len(points),
        )
    return None


def map_items(
    map: Map,
    needle: str = "",
    only_named: bool = False,
    kinds: frozenset[ItemKind] | None = None,
) -> list[ItemRow]:
    """Every item matching `needle` (in its name or detail, ignoring case), optionally only the
    named ones and only some kinds, in the order the map stores them."""
    rows: list[ItemRow] = []
    if map.objects_list is not None:
        for placed in map.objects_list.object_list:
            x, y, _ = placed.position
            where = f"at ({x:.0f}, {y:.0f})"
            waypoint = _text(placed.properties, "waypointName")
            if waypoint:
                rows.append(ItemRow(ItemKind.WAYPOINT, waypoint, where, placed))
                continue
            name = _text(placed.properties, "objectName")
            team = _text(placed.properties, "originalOwner")
            detail = f"{placed.type_name} {where}" + (f", team {team}" if team else "")
            rows.append(ItemRow(ItemKind.OBJECT, name, detail, placed))
    areas: list[tuple[str, object]] = []
    if map.polygon_triggers is not None:
        areas += [(area.name, area) for area in map.polygon_triggers.polygon_triggers]
    if map.trigger_areas is not None:
        areas += [(area.name, area) for area in map.trigger_areas.trigger_areas]
    rows += [ItemRow(ItemKind.AREA, name, "trigger area", area) for name, area in areas]
    rows += [
        ItemRow(ItemKind.TEAM, qualified_team_name(team), "team", team)
        for team in team_list(map) or []
    ]

    folded = needle.strip().casefold()
    return [
        row
        for row in rows
        if (kinds is None or row.kind in kinds)
        and (not only_named or row.name)
        and (not folded or folded in row.name.casefold() or folded in row.detail.casefold())
    ]
