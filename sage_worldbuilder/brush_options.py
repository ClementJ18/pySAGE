"""The terrain brushes' settings, as WorldBuilder's Height Brush, Terrain Brush and Feather Brush
option panels hold them, and the Terrain Material panel's painting mode. Widths are in heightmap
cells and heights in feet.

Kept free of numpy so the settings file can be read before any terrain is loaded.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from enum import StrEnum
from typing import Any

__all__ = [
    "BrushOptions",
    "CopyTerrainOptions",
    "PaintMode",
    "PaintOptions",
    "Passability",
    "SelectMethod",
]


class SelectMethod(StrEnum):
    """Copy Terrain Options' selection options: drag a rectangle, or brush cells in."""

    DRAG = "Drag select"
    BRUSH = "Brush select"


@dataclass
class CopyTerrainOptions:
    """Copy Terrain Options (dialog 262). `copying` is Copy mode against Selection mode; `remove`
    is Remove from selection against Add to selection; `turns` is Rotate in quarter turns."""

    copying: bool = False
    method: SelectMethod = SelectMethod.DRAG
    brush_size: int = 5
    remove: bool = False
    flip_vertically: bool = False
    flip_horizontally: bool = False
    heights: bool = True
    texture: bool = True
    passability: bool = True
    turns: int = 0

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["method"] = self.method.value
        return data

    @classmethod
    def from_dict(cls, data: Any) -> CopyTerrainOptions:
        options = cls()
        if not isinstance(data, dict):
            return options
        for name in (
            "copying",
            "remove",
            "flip_vertically",
            "flip_horizontally",
            "heights",
            "texture",
            "passability",
        ):
            if isinstance(data.get(name), bool):
                setattr(options, name, data[name])
        if data.get("method") in {method.value for method in SelectMethod}:
            options.method = SelectMethod(data["method"])
        for name, low, high in (("brush_size", 1, 100), ("turns", 0, 3)):
            value = data.get(name)
            if isinstance(value, int) and not isinstance(value, bool) and low <= value <= high:
                setattr(options, name, value)
        return options


class PaintMode(StrEnum):
    """Terrain Material's Terrain Painting Mode: what Single Tile and Large Tile paint."""

    TEXTURE = "Texture"
    PASSABILITY = "Passability"
    PASSAGE_WIDTH = "Passage Width"
    TAINTABILITY = "Taintability"
    FLAMMABILITY = "Flammability"
    VISIBILITY = "Visibility"


class Passability(StrEnum):
    PASSABLE = "Passable"
    IMPASSABLE = "Impassable"
    IMPASSABLE_TO_PLAYERS = "Impassable to players"
    EXTRA_PASSABLE = '"Extra" passable'


@dataclass
class PaintOptions:
    """The value each painting mode paints. Flammability is the stored byte: 0 fire resistant,
    1 grass, 2 highly flammable, 3 undefined. `texture` is the Terrain.ini name Texture mode
    paints, '' for none chosen."""

    mode: PaintMode = PaintMode.PASSABILITY
    passability: Passability = Passability.IMPASSABLE
    narrow: bool = True
    taintable: bool = True
    flammability: int = 1
    visible: bool = False
    texture: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode.value,
            "passability": self.passability.value,
            "narrow": self.narrow,
            "taintable": self.taintable,
            "flammability": self.flammability,
            "visible": self.visible,
            "texture": self.texture,
        }

    @classmethod
    def from_dict(cls, data: Any) -> PaintOptions:
        options = cls()
        if not isinstance(data, dict):
            return options
        if data.get("mode") in {mode.value for mode in PaintMode}:
            options.mode = PaintMode(data["mode"])
        if data.get("passability") in {state.value for state in Passability}:
            options.passability = Passability(data["passability"])
        for name in ("narrow", "taintable", "visible"):
            if isinstance(data.get(name), bool):
                setattr(options, name, data[name])
        if isinstance(data.get("texture"), str):
            options.texture = data["texture"]
        flammability = data.get("flammability")
        if isinstance(flammability, int) and not isinstance(flammability, bool):
            if 0 <= flammability <= 3:
                options.flammability = flammability
        return options


@dataclass
class BrushOptions:
    # Brush Width: the samples at full strength, across.
    width: int = 5
    # Brush Feather Width: the ring beyond it where the strength falls off to nothing.
    feather: int = 2
    # Height Brush: the height it paints, in feet.
    height: float = 16.0
    # Mound and Dig: how far one step raises or lowers, in feet.
    amount: float = 1.0
    # Smooth Height: the Filter Radius, in cells, and the Feather Rate, 1 (scrub) to 10 (at once).
    radius: int = 1
    rate: int = 5

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Any) -> BrushOptions:
        options = cls()
        if not isinstance(data, dict):
            return options
        for field in fields(cls):
            value = data.get(field.name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                continue
            if field.type == "int" and isinstance(value, int):
                setattr(options, field.name, value)
            elif field.type == "float":
                setattr(options, field.name, float(value))
        options.clamp()
        return options

    def clamp(self) -> None:
        """Pull every value back into the range the option panels allow."""
        self.width = min(max(self.width, 1), 100)
        self.feather = min(max(self.feather, 0), 50)
        self.height = min(max(self.height, 0.0), 2559.0)
        self.amount = min(max(self.amount, 0.0), 500.0)
        self.radius = min(max(self.radius, 1), 10)
        self.rate = min(max(self.rate, 1), 10)
