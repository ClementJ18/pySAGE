"""Where a placed object stands: its stored position moved out along its template's rotation anchor.

A template with `GeometryRotationAnchorOffset` is stored at a pivot, not where it stands: the game
stands it at that offset turned by the object's angle. Castle walls are stored at the castle's
centre, each turned its own way, and so stand on a ring around it. The stored position stays the
pivot, which moving and rotating edit; drawing, picking and finding duplicates use where the
object stands.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sage_ini.model.game import Game
    from sage_map.assets.object_list import Object

__all__ = ["RotationAnchors", "shown_position"]

_NO_OFFSET = (0.0, 0.0)


class RotationAnchors:
    """Rotation anchor offsets by object name, read from the game data on first use and kept."""

    def __init__(self, game: Game) -> None:
        self.game = game
        self._cache: dict[str, tuple[float, float]] = {}
        self._names: dict[str, str] | None = None

    def get(self, type_name: str) -> tuple[float, float]:
        """The `(x, y)` offset along an object's facing, `(0, 0)` for a template without one or
        a name the game data does not know. A template repeats the key once per geometry block;
        the first is used."""
        if type_name not in self._cache:
            self._cache[type_name] = self._read(type_name)
        return self._cache[type_name]

    def _read(self, type_name: str) -> tuple[float, float]:
        objects = self.game.objects
        template = objects.get(type_name)
        if template is None:
            if self._names is None:
                self._names = {name.lower(): name for name in objects}
            name = self._names.get(type_name.lower())
            template = objects.get(name) if name is not None else None
        offsets = getattr(template, "GeometryRotationAnchorOffset", None) or []
        if not offsets:
            return _NO_OFFSET
        first = offsets[0]
        try:
            x = float(first[0]) if len(first) > 0 else 0.0
            y = float(first[1]) if len(first) > 1 else 0.0
        except (TypeError, ValueError):
            return _NO_OFFSET
        return x, y


def shown_position(obj: Object, anchors: RotationAnchors | None) -> tuple[float, float, float]:
    """Where an object stands: its stored position, moved by its rotation anchor offset turned by
    its angle (radians, counter-clockwise from +x). Without `anchors`, the stored position."""
    x, y, z = obj.position
    ox, oy = anchors.get(obj.type_name) if anchors is not None else _NO_OFFSET
    if ox or oy:
        cos, sin = math.cos(obj.angle), math.sin(obj.angle)
        x, y = x + ox * cos - oy * sin, y + ox * sin + oy * cos
    return x, y, z
