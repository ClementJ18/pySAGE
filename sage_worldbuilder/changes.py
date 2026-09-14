"""What an edit changed, so each view refreshes only what it shows."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

__all__ = ["Change", "ChangeKind", "Region"]


class ChangeKind(StrEnum):
    """The part of the map an edit touched. `WHOLE` means anything may have changed."""

    TERRAIN = "terrain"
    OBJECTS = "objects"
    WAYPOINTS = "waypoints"
    AREAS = "areas"
    SIDES = "sides"
    SCRIPTS = "scripts"
    SETTINGS = "settings"
    WATER = "water"
    CAMERAS = "cameras"
    WHOLE = "whole"


@dataclass(frozen=True)
class Region:
    """A half-open rectangle of heightmap cells: `x0 <= x < x1`, `y0 <= y < y1`."""

    x0: int
    y0: int
    x1: int
    y1: int

    def union(self, other: Region) -> Region:
        return Region(
            min(self.x0, other.x0),
            min(self.y0, other.y0),
            max(self.x1, other.x1),
            max(self.y1, other.y1),
        )


@dataclass(frozen=True)
class Change:
    """One notification: the kind of data touched and, for spatial data, where."""

    kind: ChangeKind
    region: Region | None = None
