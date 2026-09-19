"""A base's castle templates: the `CastleTemplates` chunk WorldBuilder rebuilds from the objects.

Whenever WorldBuilder saves a `.bse` it writes the chunk anew (`SidesList::
writeCastleTemplateDataChunk`, `0x00A8C560`): the game builds a castle from it, not from the base's
objects. A piece is an object with a non-empty `objectBaseName` that is not flagged
`objectIsABase` and whose template is not a `CASTLE_CENTER`; it is stored with its offset from the
castle's centre, its angle, and its `objectBasePriority` / `objectBasePhase` (40 when absent). The
centre is the mean position of the `CASTLE_CENTER` objects, or of the pieces when there are none.
Each trigger area of the base is a perimeter, its points relative to the centre.

A position is where the object stands (its rotation anchor applied): castle walls are stored at
the castle's pivot. The arithmetic is single precision, summed in object order. Checked against all
1,035 corpus bases: every base comes within 0.01 of its stored chunk, every perimeter exactly, and
every piece without a rotation anchor exactly; some anchored pieces differ in the last float bit,
which is why a base is only rebuilt once its objects change.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from sage_map.assets.castle_templates import (
    CastlePerimeter,
    CastleTemplate,
    CastleTemplates,
    PerimeterPoint,
)
from sage_map.context import AssetPropertyType
from sage_worldbuilder.anchors import RotationAnchors

if TYPE_CHECKING:
    from sage_ini.model.game import Game
    from sage_map.assets.object_list import Object
    from sage_map.map import Map

__all__ = [
    "BASE_SUFFIX",
    "CastleKinds",
    "castle_templates",
    "is_base_path",
    "refresh_castle_templates",
]

BASE_SUFFIX = ".bse"
CASTLE_TEMPLATES_VERSION = 5
DEFAULT_ORDER = 40
_CASTLE_CENTER = "CASTLE_CENTER"

_F = np.float32


def is_base_path(path: str | Path | None) -> bool:
    return path is not None and Path(path).suffix.lower() == BASE_SUFFIX


class CastleKinds:
    """Which templates are castle centres, and each template's own spelling, read from the game
    data on first use and kept."""

    def __init__(self, game: Game) -> None:
        self.game = game
        self._cache: dict[str, tuple[str, bool] | None] = {}
        self._names: dict[str, str] | None = None

    def lookup(self, type_name: str) -> tuple[str, bool] | None:
        """The template's name and whether it is a castle centre; `None` when the game data does
        not know the object."""
        if type_name not in self._cache:
            self._cache[type_name] = self._read(type_name)
        return self._cache[type_name]

    def _read(self, type_name: str) -> tuple[str, bool] | None:
        objects = self.game.objects
        name = type_name if type_name in objects else None
        if name is None:
            if self._names is None:
                self._names = {known.lower(): known for known in objects}
            name = self._names.get(type_name.lower())
        if name is None:
            return None
        kinds = getattr(objects[name], "KindOf", None) or []
        return name, any(
            str(getattr(kind, "name", kind)).upper() == _CASTLE_CENTER for kind in kinds
        )


def _value(obj: Object, key: str) -> object:
    stored = obj.properties.get(key)
    return None if stored is None else stored["value"]


def _order(obj: Object, key: str) -> int:
    value = _value(obj, key)
    return value if isinstance(value, int) and not isinstance(value, bool) else DEFAULT_ORDER


def _standing(obj: Object, anchors: RotationAnchors | None) -> np.ndarray:
    """Where the object stands, in single precision over a double-precision cosine and sine: of
    the forms tried, the one that reproduces the most stored bases exactly."""
    x, y, z = (_F(value) for value in obj.position)
    ox, oy = anchors.get(obj.type_name) if anchors is not None else (0.0, 0.0)
    if ox or oy:
        cos, sin = _F(math.cos(obj.angle)), _F(math.sin(obj.angle))
        x, y = x + _F(ox) * cos - _F(oy) * sin, y + _F(ox) * sin + _F(oy) * cos
    return np.array([x, y, z], dtype=_F)


def _mean(points: list[np.ndarray]) -> np.ndarray:
    total = np.zeros(3, dtype=_F)
    for point in points:
        total = total + point
    return total / _F(len(points))


def castle_templates(
    map: Map,
    base_name: str,
    kinds: CastleKinds | None,
    anchors: RotationAnchors | None,
) -> CastleTemplates:
    """The chunk WorldBuilder writes for `map` saved as the base `base_name`.

    Without `kinds` no object counts as a castle centre; without `anchors` objects stand where
    they are stored. An object the game data does not know keeps its own name as its template
    name (WorldBuilder writes an empty one, which the game cannot build)."""
    objects = map.objects_list.object_list if map.objects_list is not None else []
    centres: list[np.ndarray] = []
    pieces: list[tuple[Object, str, np.ndarray]] = []
    for obj in objects:
        known = kinds.lookup(obj.type_name) if kinds is not None else None
        position = _standing(obj, anchors)
        if known is not None and known[1]:
            centres.append(position)
            continue
        if _value(obj, "objectIsABase") is True or not _value(obj, "objectBaseName"):
            continue
        pieces.append((obj, known[0] if known is not None else obj.type_name, position))

    group = centres or [position for _, _, position in pieces]
    centre = _mean(group) if group else np.zeros(3, dtype=_F)
    templates = []
    for obj, template_name, position in pieces:
        offset = position - centre
        name = _value(obj, "objectName")
        templates.append(
            CastleTemplate(
                name=name if isinstance(name, str) else "",
                template_name=template_name,
                offset=(float(offset[0]), float(offset[1]), float(offset[2])),
                angle=float(_F(obj.angle)),
                priority=_order(obj, "objectBasePriority"),
                phase=_order(obj, "objectBasePhase"),
            )
        )

    areas = map.trigger_areas.trigger_areas if map.trigger_areas is not None else []
    perimeters = [
        CastlePerimeter(
            name=area.name,
            points=[
                PerimeterPoint(float(_F(x) - centre[0]), float(_F(y) - centre[1]), 0.0)
                for x, y in area.points
            ],
        )
        for area in areas
    ]
    return CastleTemplates(
        version=CASTLE_TEMPLATES_VERSION,
        property_key=(AssetPropertyType.AsciiString, 0, base_name),
        templates=templates,
        perimeters=perimeters,
        start_pos=0,
        end_pos=0,
    )


def base_name(path: str | Path) -> str:
    """The name a base is saved under: its file name up to the first dot, as WorldBuilder has it."""
    return Path(path).name.split(".", 1)[0]


def refresh_castle_templates(
    map: Map,
    path: str | Path,
    game: Game | None,
    anchors: RotationAnchors | None = None,
    kinds: Callable[[Game], CastleKinds] = CastleKinds,
) -> bool:
    """Replace `map`'s castle templates with the ones its objects make, for a base saved to `path`.

    Returns whether the chunk was replaced: never for a file that is not a `.bse`, nor without game
    data, which decides the castle centres and where walls stand."""
    if not is_base_path(path) or game is None:
        return False
    map.castle_templates = castle_templates(
        map,
        base_name(path),
        kinds(game),
        anchors if anchors is not None else RotationAnchors(game),
    )
    return True
