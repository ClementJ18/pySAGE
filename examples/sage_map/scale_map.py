"""Script to scale a map by a numeric factor (integer or float).

Usage:
    python scale_map.py <map_file_path> <scale> [output_map_path] [--scale-objects]

Example:
    python scale_map.py Mission.map 3
    python scale_map.py Mission.map 0.5 Mission_half.map
    python scale_map.py Mission.map 3 Mission_3x.map --scale-objects
"""

import math
from argparse import ArgumentParser
from pathlib import Path

from sage_map import parse_map_from_path, write_map_to_path
from sage_map.assets.blend_tile_data import BlendDescription, BlendDirection
from sage_map.assets.height_map import HeightMapBorder
from sage_map.context import AssetPropertyType


def find_texture_for_tile(tile_val, textures):
    """Return the BlendTileTexture that owns this tile value."""
    global_cell = tile_val // 4
    for tex in textures:
        if tex.cell_start <= global_cell < tex.cell_start + tex.cell_count:
            return tex
    raise ValueError(f"No texture owns tile value {tile_val} (global_cell={global_cell})")


def retile_tiles(tiles, textures, scale):
    """Scale tiles by factor, re-encoding each value using the destination position.

    Destination tiles are processed in 2×2 blocks (the smallest addressable cell
    unit). The entire block's combined source footprint is used for majority vote,
    so all 4 sub-tiles always get the same texture - preventing sub-cell
    fragmentation and checkerboard artefacts at texture boundaries.
    """
    src_rows = len(tiles)
    src_cols = len(tiles[0])
    dst_rows = round(src_rows * scale)
    dst_cols = round(src_cols * scale)
    result = [[0] * dst_cols for _ in range(dst_rows)]

    for block_r in range(math.ceil(dst_rows / 2)):
        for block_c in range(math.ceil(dst_cols / 2)):
            # Source region covered by this 2×2 destination block
            r_start = int(block_r * 2 / scale)
            r_end = min(math.ceil((block_r * 2 + 2) / scale), src_rows)
            c_start = int(block_c * 2 / scale)
            c_end = min(math.ceil((block_c * 2 + 2) / scale), src_cols)
            # Majority vote over the combined source footprint
            counts = {}
            id_to_tex = {}
            for sr in range(r_start, r_end):
                for sc in range(c_start, c_end):
                    tex = find_texture_for_tile(tiles[sr][sc], textures)
                    tid = id(tex)
                    counts[tid] = counts.get(tid, 0) + 1
                    id_to_tex[tid] = tex
            tex = id_to_tex[max(counts, key=counts.get)]
            # All 4 sub-tiles share the same cell, so compute global_cell once.
            # block_r == dst_r // 2 and block_c == dst_c // 2 for every sub-tile.
            cr = block_r % tex.cell_size
            cc = block_c % tex.cell_size
            global_cell = tex.cell_start + cc * tex.cell_size + cr
            for sub_r in range(2):
                for sub_c in range(2):
                    dst_r = block_r * 2 + sub_r
                    dst_c = block_c * 2 + sub_c
                    if dst_r < dst_rows and dst_c < dst_cols:
                        result[dst_r][dst_c] = global_cell * 4 + sub_c * 2 + sub_r
    return result


def rebuild_blend_descriptions(blends, three_way_blends, old_descriptions, retiled_tiles):
    """Rebuild blend descriptions after retiling.

    Each blend description's secondary_texture_tile references a specific tile
    value from the neighbour cell. After retiling those values change with position,
    so descriptions are recomputed from the new tile data and deduplicated.

    Returns (new_blends, new_three_way_blends, new_blend_descriptions).
    """
    _DIR_DELTAS = {
        BlendDirection.RIGHT_TO_LEFT: (1, 0),
        BlendDirection.LEFT_TO_RIGHT: (-1, 0),
        BlendDirection.TOP_TO_BOTTOM: (0, 1),
        BlendDirection.BOTTOM_TO_TOP: (0, -1),
    }
    rows = len(retiled_tiles)
    cols = len(retiled_tiles[0])
    new_descriptions = []
    key_to_idx = {}
    new_blends = [[0] * cols for _ in range(rows)]
    new_three_way = [[0] * cols for _ in range(rows)]

    for src_grid, dst_grid in [(blends, new_blends), (three_way_blends, new_three_way)]:
        for r in range(rows):
            for c in range(cols):
                old_idx = src_grid[r][c]
                if old_idx == 0:
                    continue
                old_desc = old_descriptions[old_idx - 1]
                direction = old_desc.blend_direction
                dr, dc = _DIR_DELTAS[direction]
                nr, nc = r + dr, c + dc
                if 0 <= nr < rows and 0 <= nc < cols:
                    # Use the neighbour tile directly as the secondary reference.
                    # secondary_texture_tile identifies the texture to blend to via
                    # global_cell = value // 4; the exact inner offset does not affect
                    # which texture is chosen, and using the tile itself avoids the
                    # underflow that ±1 can produce when the neighbour is at tile 0.
                    secondary = retiled_tiles[nr][nc]
                else:
                    secondary = old_desc.secondary_texture_tile
                key = (
                    secondary,
                    bytes(old_desc.raw_blend_direction),
                    old_desc.flags,
                    old_desc.two_sided,
                    old_desc.magic_value1,
                )
                if key not in key_to_idx:
                    key_to_idx[key] = len(new_descriptions) + 1
                    new_descriptions.append(
                        BlendDescription(
                            secondary_texture_tile=secondary,
                            raw_blend_direction=old_desc.raw_blend_direction,
                            flags=old_desc.flags,
                            two_sided=old_desc.two_sided,
                            magic_value1=old_desc.magic_value1,
                        )
                    )
                dst_grid[r][c] = key_to_idx[key]

    return new_blends, new_three_way, new_descriptions


def scale_2d_nearest(data, scale):
    if data is None:
        return None
    src_rows = len(data)
    src_cols = len(data[0])
    dst_rows = round(src_rows * scale)
    dst_cols = round(src_cols * scale)
    return [
        [
            data[min(int(r / scale), src_rows - 1)][min(int(c / scale), src_cols - 1)]
            for c in range(dst_cols)
        ]
        for r in range(dst_rows)
    ]


def clear_interior_blends(scaled_tiles, scaled_blend, textures=None):
    """Clear blend values on cells that have no adjacent tile boundary.

    A blend describes a directional texture transition. If all 8 neighbours of
    a cell share the same texture there is no actual boundary and the blend
    overlay would appear floating in the middle of a uniform texture.

    When textures is provided, boundary detection uses texture identity rather
    than raw tile values (required after retiling, where same-texture tiles differ
    in value due to position-dependent encoding).
    """
    if scaled_blend is None:
        return None
    rows = len(scaled_tiles)
    cols = len(scaled_tiles[0])
    result = [row[:] for row in scaled_blend]
    for r in range(rows):
        for c in range(cols):
            if result[r][c] == 0:
                continue
            tile = scaled_tiles[r][c]
            if textures is not None:
                ref = find_texture_for_tile(tile, textures)
                all_same = all(
                    find_texture_for_tile(scaled_tiles[r + dr][c + dc], textures) is ref
                    for dr in (-1, 0, 1)
                    for dc in (-1, 0, 1)
                    if (dr != 0 or dc != 0) and 0 <= r + dr < rows and 0 <= c + dc < cols
                )
            else:
                all_same = all(
                    scaled_tiles[r + dr][c + dc] == tile
                    for dr in (-1, 0, 1)
                    for dc in (-1, 0, 1)
                    if (dr != 0 or dc != 0) and 0 <= r + dr < rows and 0 <= c + dc < cols
                )
            if all_same:
                result[r][c] = 0
    return result


def scale_elevations(elevations: list[list[int]], scale: float) -> list[list[int]]:
    src_rows = len(elevations)
    src_cols = len(elevations[0])
    dst_rows = round(src_rows * scale)
    dst_cols = round(src_cols * scale)

    result = []
    for dst_r in range(dst_rows):
        row = []
        for dst_c in range(dst_cols):
            src_r = dst_r / scale
            src_c = dst_c / scale

            r0 = int(src_r)
            c0 = int(src_c)
            r1 = min(r0 + 1, src_rows - 1)
            c1 = min(c0 + 1, src_cols - 1)

            fr = src_r - r0
            fc = src_c - c0

            v = (
                elevations[r0][c0] * (1 - fr) * (1 - fc)
                + elevations[r0][c1] * (1 - fr) * fc
                + elevations[r1][c0] * fr * (1 - fc)
                + elevations[r1][c1] * fr * fc
            )
            row.append(round(v))
        result.append(row)
    return result


def scale_map(map_path: str, scale: float, output_path: str = None, scale_objects: bool = False):
    print(f"Loading map from: {map_path}")
    sage_map = parse_map_from_path(map_path)

    print(f"Scaling by {scale}x...")

    hmd = sage_map.height_map_data
    hmd.width = round(hmd.width * scale)
    hmd.height = round(hmd.height * scale)
    hmd.borders = [
        HeightMapBorder(
            corner1=(round(b.corner1[0] * scale), round(b.corner1[1] * scale)),
            position=(round(b.position[0] * scale), round(b.position[1] * scale)),
        )
        for b in hmd.borders
    ]
    hmd.area = hmd.width * hmd.height
    hmd.elevations = scale_elevations(hmd.elevations, scale)

    btd = sage_map.blend_tile_data
    old_blend_descriptions = btd.blend_descriptions[:]
    btd.tiles = retile_tiles(btd.tiles, btd.textures, scale)

    scaled_blends = scale_2d_nearest(btd.blends, scale)
    scaled_three_way = scale_2d_nearest(btd.three_way_blends, scale)
    scaled_cliff = scale_2d_nearest(btd.cliff_textures, scale)

    cleared_blends = clear_interior_blends(btd.tiles, scaled_blends, btd.textures)
    cleared_three_way = clear_interior_blends(btd.tiles, scaled_three_way, btd.textures)
    btd.cliff_textures = clear_interior_blends(btd.tiles, scaled_cliff, btd.textures)

    btd.blends, btd.three_way_blends, btd.blend_descriptions = rebuild_blend_descriptions(
        cleared_blends, cleared_three_way, old_blend_descriptions, btd.tiles
    )
    btd.impassability = scale_2d_nearest(btd.impassability, scale)
    btd.impassability_to_players = scale_2d_nearest(btd.impassability_to_players, scale)
    btd.passage_widths = scale_2d_nearest(btd.passage_widths, scale)
    btd.taintability = scale_2d_nearest(btd.taintability, scale)
    btd.extra_passability = scale_2d_nearest(btd.extra_passability, scale)
    btd.flammability = scale_2d_nearest(btd.flammability, scale)
    btd.visibility = scale_2d_nearest(btd.visibility, scale)
    btd.buildability = scale_2d_nearest(btd.buildability, scale)
    btd.impassability_to_air_units = scale_2d_nearest(btd.impassability_to_air_units, scale)
    btd.tiberium_growability = scale_2d_nearest(btd.tiberium_growability, scale)
    btd.dynamic_shrubbery_density = scale_2d_nearest(btd.dynamic_shrubbery_density, scale)

    for obj in sage_map.objects_list.object_list:
        obj.position = (obj.position[0] * scale, obj.position[1] * scale, obj.position[2])

        if scale_objects:
            obj.properties["objectPrototypeScale"] = {
                "name": "objectPrototypeScale",
                "type": AssetPropertyType.RealNumber,
                "value": scale,
            }

    for area in sage_map.trigger_areas.trigger_areas:
        area.points = [(x * scale, y * scale) for x, y in area.points]

    for area in sage_map.standing_water_areas.areas:
        area.points = [(x * scale, y * scale) for x, y in area.points]

    for area in sage_map.standing_wave_areas.areas:
        area.points = [(x * scale, y * scale) for x, y in area.points]

    for area in sage_map.river_areas.areas:
        area.lines = [
            ((x1 * scale, y1 * scale), (x2 * scale, y2 * scale))
            for (x1, y1), (x2, y2) in area.lines
        ]

    if output_path is None:
        output_path = map_path

    print(f"Saving scaled map to: {output_path}")
    write_map_to_path(sage_map, output_path, compress=True)
    print("Done.")


def main():
    parser = ArgumentParser(description="Scale a BFME map by a numeric factor.")
    parser.add_argument("map_path", help="Path to the .map file")
    parser.add_argument("scale", type=float, help="Scale factor (e.g. 2, 0.5)")
    parser.add_argument(
        "output_path",
        nargs="?",
        default=None,
        help="Output .map file path (default: overwrite input)",
    )
    parser.add_argument(
        "--scale-objects",
        action="store_true",
        help="Also scale object prototype sizes via objectPrototypeScale",
    )
    args = parser.parse_args()

    if args.scale <= 0:
        parser.error(f"Scale must be a positive number, got: {args.scale}")

    if not Path(args.map_path).exists():
        parser.error(f"Map file not found: {args.map_path}")

    scale_map(args.map_path, args.scale, args.output_path, scale_objects=args.scale_objects)


if __name__ == "__main__":
    main()
