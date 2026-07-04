"""Script to blend a tile with its neighbour in a given direction.

Coordinates match the world editor visual (rows top-to-bottom, columns left-to-right).

Usage:
    python blend_tile.py <map_file_path> <row> <col> <direction> [output_map_path]

Directions:
    right  Blend towards the tile at col+1
    left   Blend towards the tile at col-1
    down   Blend towards the tile at row+1
    up     Blend towards the tile at row-1

Example:
    python blend_tile.py Mission.map 1 2 right
    python blend_tile.py Mission.map 1 2 right Mission_blended.map
"""

import string
import sys
from pathlib import Path

from sage_map import parse_map_from_path, write_map_to_path
from sage_map.assets.blend_tile_data import (
    BlendDescription,
    BlendDirection,
    BlendTileData,
)

# Editor (row, col) maps to internal [col][row] (transposed).
# Editor col+1 = internal row+1 = RIGHT_TO_LEFT
# Editor col-1 = internal row-1 = LEFT_TO_RIGHT
# Editor row+1 = internal col+1 = TOP_TO_BOTTOM
# Editor row-1 = internal col-1 = BOTTOM_TO_TOP
DIRECTION_MAP = {
    "right": BlendDirection.RIGHT_TO_LEFT,
    "left": BlendDirection.LEFT_TO_RIGHT,
    "down": BlendDirection.TOP_TO_BOTTOM,
    "up": BlendDirection.BOTTOM_TO_TOP,
}


def print_map(btd: BlendTileData) -> None:
    """Print a visual representation of the tile map with a texture key."""
    symbols = string.ascii_uppercase + string.ascii_lowercase + string.digits

    # Build ordered list of unique texture names as they appear in the textures list
    texture_names = [t.name for t in btd.textures]
    texture_symbol = {name: symbols[i % len(symbols)] for i, name in enumerate(texture_names)}

    def tile_to_texture(tile_idx: int) -> str:
        for tex in btd.textures:
            if tex.cell_start <= tile_idx < tex.cell_start + tex.cell_count:
                return texture_symbol[tex.name]
        return "?"

    # Internal layout is [internal_row][internal_col].
    # Editor view is transposed: editor_row = internal_col, editor_col = internal_row.
    editor_rows = len(btd.tiles[0])
    editor_cols = len(btd.tiles)

    col_header = "    " + " ".join(f"{c:2}" for c in range(editor_cols))
    print(col_header)
    print("    " + "--" * editor_cols + "-")
    for er in range(editor_rows):
        row_str = " ".join(tile_to_texture(btd.tiles[ec][er]) for ec in range(editor_cols))
        blend_str = " ".join(
            str(btd.blends[ec][er]) if btd.blends[ec][er] else "." for ec in range(editor_cols)
        )
        print(f"{er:2}| {row_str}   blends: {blend_str}")
    print()
    print("Key:")
    for name, sym in texture_symbol.items():
        print(f"  {sym} = {name}")


def blend_tile(btd: BlendTileData, row: int, col: int, direction: BlendDirection) -> None:
    dr, dc = {
        BlendDirection.RIGHT_TO_LEFT: (1, 0),
        BlendDirection.LEFT_TO_RIGHT: (-1, 0),
        BlendDirection.TOP_TO_BOTTOM: (0, 1),
        BlendDirection.BOTTOM_TO_TOP: (0, -1),
    }[direction]

    neighbour_row = row + dr
    neighbour_col = col + dc

    rows = len(btd.tiles)
    cols = len(btd.tiles[0])
    if not (0 <= neighbour_row < rows and 0 <= neighbour_col < cols):
        raise ValueError(f"Neighbour ({neighbour_row}, {neighbour_col}) is out of bounds")

    neighbour_tile = btd.tiles[neighbour_row][neighbour_col]
    if direction in (BlendDirection.LEFT_TO_RIGHT, BlendDirection.BOTTOM_TO_TOP):
        secondary_texture_tile = neighbour_tile + 1
    else:
        secondary_texture_tile = neighbour_tile - 1

    raw_blend_direction = bytes(
        [
            1 if direction in (BlendDirection.RIGHT_TO_LEFT, BlendDirection.LEFT_TO_RIGHT) else 0,
            1 if direction in (BlendDirection.TOP_TO_BOTTOM, BlendDirection.BOTTOM_TO_TOP) else 0,
            0,
            0,
        ]
    )
    flags = 1 if direction in (BlendDirection.LEFT_TO_RIGHT, BlendDirection.BOTTOM_TO_TOP) else 0

    desc = BlendDescription(
        secondary_texture_tile=secondary_texture_tile,
        raw_blend_direction=raw_blend_direction,
        flags=flags,
        two_sided=False,
        magic_value1=0xFFFFFFFF,
    )

    for i, existing in enumerate(btd.blend_descriptions):
        if existing == desc:
            btd.blends[row][col] = i + 1
            return

    btd.blend_descriptions.append(desc)
    btd.blends[row][col] = len(btd.blend_descriptions)


def main():
    if len(sys.argv) < 5:
        print(
            "Usage: python blend_tile.py <map_file_path> <row> <col> <direction> [output_map_path]"
        )
        print("\nDirections:", ", ".join(DIRECTION_MAP))
        sys.exit(1)

    map_path = sys.argv[1]
    output_path = sys.argv[5] if len(sys.argv) > 5 else map_path

    if not Path(map_path).exists():
        print(f"Error: Map file not found: {map_path}")
        sys.exit(1)

    try:
        row = int(sys.argv[2])
        col = int(sys.argv[3])
    except ValueError:
        print("Error: row and col must be integers")
        sys.exit(1)

    direction_str = sys.argv[4].lower()
    if direction_str not in DIRECTION_MAP:
        print(f"Error: Unknown direction '{direction_str}'. Valid: {', '.join(DIRECTION_MAP)}")
        sys.exit(1)
    direction = DIRECTION_MAP[direction_str]

    print(f"Loading map from: {map_path}")
    sage_map = parse_map_from_path(map_path)

    if not sage_map.blend_tile_data:
        print("Error: No BlendTileData found in map")
        sys.exit(1)

    print("\nBefore blend:")
    print_map(sage_map.blend_tile_data)
    print(sage_map.blend_tile_data)

    # Translate editor (row, col) to internal (col, row)
    internal_row, internal_col = col, row
    blend_tile(sage_map.blend_tile_data, internal_row, internal_col, direction)

    print("\nAfter blend:")
    print_map(sage_map.blend_tile_data)
    print(sage_map.blend_tile_data)

    print(f"Saving map to: {output_path}")
    write_map_to_path(sage_map, output_path, compress=True)
    print("Done.")


if __name__ == "__main__":
    main()
