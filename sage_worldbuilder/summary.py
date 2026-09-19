"""A plain-text summary of what a map holds, for the shell's Map panel."""

from __future__ import annotations

from sage_map.map import Map
from sage_map.model import build_symbols

__all__ = ["map_summary"]


def map_summary(map: Map) -> list[tuple[str, str]]:
    """`(label, value)` rows describing `map`; chunks the map does not carry are left out."""
    rows: list[tuple[str, str]] = []
    heights = map.height_map_data
    if heights is not None:
        rows.append(("Size", f"{heights.width} x {heights.height}, border {heights.border_width}"))
    if map.sides_list is not None:
        rows.append(("Players", str(len(map.sides_list.players))))
    if map.teams is not None:
        rows.append(("Teams", str(len(map.teams.teams))))
    elif map.sides_list is not None:
        rows.append(("Teams", str(len(map.sides_list.teams))))
    if map.objects_list is not None:
        rows.append(("Objects", str(len(map.objects_list.object_list))))
    symbols = build_symbols(map)
    rows.append(("Waypoints", str(len(symbols.waypoints))))
    rows.append(("Trigger areas", str(len(symbols.trigger_areas))))
    rows.append(("Scripts", str(len(symbols.scripts))))
    return rows
