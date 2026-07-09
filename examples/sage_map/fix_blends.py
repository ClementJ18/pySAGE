"""Script to detect and fix unblended tile connections.

For every adjacent pair of tiles with different textures that lacks a blend,
the smaller texture group blends over the larger one.  A blend is added on
the small-group tile, pointing toward the large-group tile.

Coordinates match the world editor visual (rows top-to-bottom, columns
left-to-right).  Internally the tile array is transposed, but that detail
is handled transparently.

Usage:
    python fix_blends.py <map_file_path> [output_map_path] [--dry-run]

Options:
    --dry-run   Scan and report without writing any changes.

Example:
    python fix_blends.py Mission.map
    python fix_blends.py Mission.map Mission_fixed.map
    python fix_blends.py Mission.map --dry-run
"""

import sys
from argparse import ArgumentParser
from collections import Counter
from pathlib import Path

from sage_map import parse_map_from_path, write_map_to_path
from sage_map.assets.blend_tile_data import (
    BlendDescription,
    BlendDirection,
    BlendTileData,
)

# ---------------------------------------------------------------------------
# Direction constants (all in internal tile-array coordinates)
# Internal (r, c) is transposed vs. the editor view:
#   internal r = editor col,  internal c = editor row
# ---------------------------------------------------------------------------

_DIR_DELTAS = {
    BlendDirection.RIGHT_TO_LEFT: (1, 0),
    BlendDirection.LEFT_TO_RIGHT: (-1, 0),
    BlendDirection.TOP_TO_BOTTOM: (0, 1),
    BlendDirection.BOTTOM_TO_TOP: (0, -1),
}

_OPPOSITE = {
    BlendDirection.RIGHT_TO_LEFT: BlendDirection.LEFT_TO_RIGHT,
    BlendDirection.LEFT_TO_RIGHT: BlendDirection.RIGHT_TO_LEFT,
    BlendDirection.TOP_TO_BOTTOM: BlendDirection.BOTTOM_TO_TOP,
    BlendDirection.BOTTOM_TO_TOP: BlendDirection.TOP_TO_BOTTOM,
}

# Only the two "forward" directions are needed to visit every boundary once.
_FORWARD_DIRS = [
    (BlendDirection.RIGHT_TO_LEFT, 1, 0),
    (BlendDirection.TOP_TO_BOTTOM, 0, 1),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _find_texture(tile_val, textures):
    gc = tile_val // 4
    for t in textures:
        if t.cell_start <= gc < t.cell_start + t.cell_count:
            return t
    return None


def _count_tiles_per_texture(tiles, textures):
    counts = Counter()
    for row in tiles:
        for val in row:
            t = _find_texture(val, textures)
            if t:
                counts[t.name] += 1
    return counts


def _make_desc(direction, neighbour_tile):
    """Build a BlendDescription for *direction* blending toward *neighbour_tile*."""
    raw = bytes(
        [
            1 if direction in (BlendDirection.RIGHT_TO_LEFT, BlendDirection.LEFT_TO_RIGHT) else 0,
            1 if direction in (BlendDirection.TOP_TO_BOTTOM, BlendDirection.BOTTOM_TO_TOP) else 0,
            0,
            0,
        ]
    )
    flags = 1 if direction in (BlendDirection.LEFT_TO_RIGHT, BlendDirection.BOTTOM_TO_TOP) else 0
    return BlendDescription(
        secondary_texture_tile=neighbour_tile,
        raw_blend_direction=raw,
        flags=flags,
        two_sided=False,
        magic_value1=0xFFFFFFFF,
    )


def _get_or_add_desc(desc, desc_list):
    """Return a 1-based index for *desc*, appending it if not already present."""
    for i, d in enumerate(desc_list):
        if d == desc:
            return i + 1
    desc_list.append(desc)
    return len(desc_list)


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------


def fix_blends(btd: BlendTileData, dry_run: bool = False) -> tuple[int, int]:
    """Add missing blends at every unblended texture boundary.

    The smaller texture group (by tile count) blends over the larger one.
    Each tile supports two blend slots: ``blends`` and ``three_way_blends``.
    Boundaries whose small-group tile already has both slots occupied are
    counted as skipped.

    Returns (added, skipped).
    """
    tiles = btd.tiles
    rows = len(tiles)
    cols = len(tiles[0])
    textures = btd.textures

    tile_counts = _count_tiles_per_texture(tiles, textures)

    # Pre-compute which blend directions are already occupied on each tile.
    # This covers both blend slots.
    used_dir: list[list[set]] = [[set() for _ in range(cols)] for _ in range(rows)]
    for grid in (btd.blends, btd.three_way_blends):
        for r in range(rows):
            for c in range(cols):
                idx = grid[r][c]
                if idx:
                    used_dir[r][c].add(btd.blend_descriptions[idx - 1].blend_direction)

    added = 0
    skipped = 0  # both blend slots already occupied on the small-group tile

    for r in range(rows):
        for c in range(cols):
            tex_a = _find_texture(tiles[r][c], textures)
            if tex_a is None:
                continue

            for fwd_dir, dr, dc in _FORWARD_DIRS:
                nr, nc = r + dr, c + dc
                if not (0 <= nr < rows and 0 <= nc < cols):
                    continue

                tex_b = _find_texture(tiles[nr][nc], textures)
                if tex_b is None or tex_a is tex_b:
                    continue

                # Determine which tile belongs to the smaller group.
                count_a = tile_counts[tex_a.name]
                count_b = tile_counts[tex_b.name]

                if count_a <= count_b:
                    sr, sc = r, c  # small-group tile receives the blend
                    lr, lc = nr, nc  # large-group tile (secondary texture)
                    blend_dir = fwd_dir
                else:
                    sr, sc = nr, nc
                    lr, lc = r, c
                    blend_dir = _OPPOSITE[fwd_dir]

                # Already handled in this direction - skip.
                if blend_dir in used_dir[sr][sc]:
                    continue

                desc = _make_desc(blend_dir, tiles[lr][lc])

                if btd.blends[sr][sc] == 0:
                    if not dry_run:
                        btd.blends[sr][sc] = _get_or_add_desc(desc, btd.blend_descriptions)
                    used_dir[sr][sc].add(blend_dir)
                    added += 1
                elif btd.three_way_blends[sr][sc] == 0:
                    if not dry_run:
                        btd.three_way_blends[sr][sc] = _get_or_add_desc(
                            desc, btd.blend_descriptions
                        )
                    used_dir[sr][sc].add(blend_dir)
                    added += 1
                else:
                    skipped += 1

    return added, skipped


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():
    parser = ArgumentParser(
        description="Detect and fix unblended tile connections. "
        "The smaller texture group always blends over the larger one."
    )
    parser.add_argument("map_path", help="Path to the .map file")
    parser.add_argument(
        "output_path",
        nargs="?",
        default=None,
        help="Output .map file path (default: overwrite input)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Scan and report without writing any changes",
    )
    args = parser.parse_args()

    if not Path(args.map_path).exists():
        parser.error(f"Map file not found: {args.map_path}")

    output_path = args.output_path or args.map_path

    print(f"Loading map from: {args.map_path}")
    sage_map = parse_map_from_path(args.map_path)

    if not sage_map.blend_tile_data:
        print("Error: No BlendTileData found in map")
        sys.exit(1)

    btd = sage_map.blend_tile_data
    tile_counts = _count_tiles_per_texture(btd.tiles, btd.textures)

    print(f"Map size: {len(btd.tiles)} × {len(btd.tiles[0])} tiles")
    print(f"Textures ({len(btd.textures)}):")
    for tex in btd.textures:
        print(f"  {tex.name}: {tile_counts[tex.name]} tiles  (cell_size={tex.cell_size})")

    if args.dry_run:
        print("\n[DRY RUN] Scanning for unblended connections...")
    else:
        print("\nScanning and fixing unblended connections...")

    added, skipped = fix_blends(btd, dry_run=args.dry_run)

    action = "Would add" if args.dry_run else "Added"
    print(f"{action} {added} blend(s).", end="")
    if skipped:
        print(f"  {skipped} boundary tile(s) skipped (both blend slots already occupied).")
    else:
        print()

    if not args.dry_run:
        if added > 0:
            print(f"Saving to: {output_path}")
            write_map_to_path(sage_map, output_path, compress=True)
            print("Done.")
        else:
            print("No changes needed.")


if __name__ == "__main__":
    main()
