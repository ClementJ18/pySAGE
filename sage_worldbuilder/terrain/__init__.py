"""Terrain math for the editor: heightmap arrays and coordinate conversion (numpy)."""

from sage_worldbuilder.terrain.grid import (
    FEET_PER_HEIGHT_UNIT,
    MAX_HEIGHT,
    WORLD_UNITS_PER_CELL,
    TerrainGrid,
)

__all__ = ["FEET_PER_HEIGHT_UNIT", "MAX_HEIGHT", "WORLD_UNITS_PER_CELL", "TerrainGrid"]
