"""Script to replace textures in a map file.

Usage:
1. Run the script with a map file path
2. It will generate texture_mapping.json with all unique textures
3. Edit the JSON file to specify replacements
4. Press Enter to apply the changes

Mapping file format (per texture entry):
  "OldName": {"name": "NewName", "cell_size": N}

Leave "name" empty to keep the texture.  "cell_size" must match the new texture's
actual cell grid size (2, 4, or 16).  When cell_size changes, all tile values on
the map are re-encoded and blend descriptions are rebuilt.
"""

import json
import sys
from pathlib import Path

from sage_map import parse_map_from_path, write_map_to_path
from sage_map.assets.blend_tile_data import BlendDescription, BlendDirection

# ---------------------------------------------------------------------------
# Internal helpers – tile re-encoding and blend rebuilding
# ---------------------------------------------------------------------------


def _find_texture_for_tile(tile_val, textures):
    global_cell = tile_val // 4
    for tex in textures:
        if tex.cell_start <= global_cell < tex.cell_start + tex.cell_count:
            return tex
    return None


def _retile_after_resize(tiles, old_ranges, new_textures):
    """Re-encode every tile using the updated cell_size / cell_start values.

    old_ranges is a list of (old_cell_start, old_cell_count, index) tuples
    captured *before* any texture metadata was modified.
    """
    rows = len(tiles)
    cols = len(tiles[0])
    result = [[0] * cols for _ in range(rows)]
    for r in range(rows):
        for c in range(cols):
            old_val = tiles[r][c]
            old_global_cell = old_val // 4
            tex_idx = None
            for i, (start, count, _) in enumerate(old_ranges):
                if start <= old_global_cell < start + count:
                    tex_idx = i
                    break
            if tex_idx is None:
                result[r][c] = old_val
                continue
            new_tex = new_textures[tex_idx]
            cr = (r // 2) % new_tex.cell_size
            cc = (c // 2) % new_tex.cell_size
            global_cell = new_tex.cell_start + cc * new_tex.cell_size + cr
            result[r][c] = global_cell * 4 + (c % 2) * 2 + (r % 2)
    return result


def _clear_interior_blends(tiles, blend_grid, textures):
    """Zero blend entries where all 8 neighbours share the same texture."""
    if blend_grid is None:
        return None
    rows = len(tiles)
    cols = len(tiles[0])
    result = [row[:] for row in blend_grid]
    for r in range(rows):
        for c in range(cols):
            if result[r][c] == 0:
                continue
            ref = _find_texture_for_tile(tiles[r][c], textures)
            all_same = all(
                _find_texture_for_tile(tiles[r + dr][c + dc], textures) is ref
                for dr in (-1, 0, 1)
                for dc in (-1, 0, 1)
                if (dr != 0 or dc != 0) and 0 <= r + dr < rows and 0 <= c + dc < cols
            )
            if all_same:
                result[r][c] = 0
    return result


def _rebuild_blends(blends, three_way_blends, old_descriptions, retiled_tiles):
    """Recompute secondary_texture_tile from the updated tile grid and deduplicate."""
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


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def extract_textures(map_path: str) -> dict:
    """Extract all unique texture names from a map file."""
    print(f"Loading map from: {map_path}")
    sage_map = parse_map_from_path(map_path)

    if not sage_map.blend_tile_data:
        print("Warning: No BlendTileData found in map")
        return {}

    textures = {}
    for texture in sage_map.blend_tile_data.textures:
        textures[texture.name] = {"name": "", "cell_size": texture.cell_size}

    print(f"Found {len(textures)} unique textures:")
    for texture_name in sorted(textures.keys()):
        print(f"  - {texture_name}  (cell_size={textures[texture_name]['cell_size']})")

    return textures


def create_mapping_file(textures: dict, output_path: str = "texture_mapping.json"):
    """Create a JSON file with texture mappings."""
    with open(output_path, "w") as f:
        json.dump(textures, f, indent=2)
    print(f"\nCreated {output_path}")
    print('Edit "name" to specify the replacement texture name (leave empty to keep).')
    print('Edit "cell_size" only if the new texture uses a different cell grid size.')


def load_mapping_file(mapping_path: str = "texture_mapping.json") -> dict:
    """Load texture mappings from JSON file."""
    with open(mapping_path) as f:
        return json.load(f)


def apply_replacements(map_path: str, mapping: dict, output_path: str = None):
    """Apply texture replacements to a map file, re-tiling and re-blending as needed."""
    print(f"\nApplying replacements to: {map_path}")
    sage_map = parse_map_from_path(map_path)

    if not sage_map.blend_tile_data:
        print("Error: No BlendTileData found in map")
        return

    # Normalise mapping entries: accept plain strings (legacy) or dicts.
    active = {}
    for old_name, value in mapping.items():
        if not value:
            continue
        if isinstance(value, str) and value.strip():
            active[old_name] = {"name": value.strip(), "cell_size": None}
        elif isinstance(value, dict):
            new_name = value.get("name", "").strip()
            if new_name:
                active[old_name] = {"name": new_name, "cell_size": value.get("cell_size")}

    if not active:
        print("No replacements specified. Aborting.")
        return

    btd = sage_map.blend_tile_data

    # Snapshot old ranges before touching anything.
    old_ranges = [(tex.cell_start, tex.cell_count, i) for i, tex in enumerate(btd.textures)]

    print(f"\nApplying {len(active)} replacement(s):")
    replaced_count = 0
    needs_retile = False

    for tex in btd.textures:
        if tex.name not in active:
            continue
        rep = active[tex.name]
        old_name = tex.name
        tex.name = rep["name"]
        new_cs = rep["cell_size"]
        if new_cs is not None and new_cs != tex.cell_size:
            old_cs = tex.cell_size
            tex.cell_size = new_cs
            tex.cell_count = new_cs * new_cs
            needs_retile = True
            print(f"  {old_name} -> {tex.name}  (cell_size {old_cs} -> {new_cs})")
        else:
            print(f"  {old_name} -> {tex.name}")
        replaced_count += 1

    if replaced_count == 0:
        print("Warning: No textures were replaced (mapping names may not match)")
        return

    if needs_retile:
        print("\nCell sizes changed - rebuilding cell_starts, re-tiling, and re-blending...")

        # Rebuild cell_start for every texture sequentially.
        cursor = 0
        for tex in btd.textures:
            tex.cell_start = cursor
            cursor += tex.cell_count
        btd.texture_cell_count = cursor

        # Re-encode all tile values for new cell layout.
        old_descs = btd.blend_descriptions[:]
        btd.tiles = _retile_after_resize(btd.tiles, old_ranges, btd.textures)

        # Clear blends that are now interior (same texture on all sides).
        cleared_blends = _clear_interior_blends(btd.tiles, btd.blends, btd.textures)
        cleared_three_way = _clear_interior_blends(btd.tiles, btd.three_way_blends, btd.textures)
        btd.cliff_textures = _clear_interior_blends(btd.tiles, btd.cliff_textures, btd.textures)

        # Rebuild blend descriptions with updated secondary_texture_tile values.
        btd.blends, btd.three_way_blends, btd.blend_descriptions = _rebuild_blends(
            cleared_blends, cleared_three_way, old_descs, btd.tiles
        )
        print(
            f"  Re-tiling done. blend_descriptions: "
            f"{len(old_descs)} -> {len(btd.blend_descriptions)}"
        )

    if output_path is None:
        output_path = map_path

    print(f"\nSaving modified map to: {output_path}")
    write_map_to_path(sage_map, output_path, compress=True)
    print(f"Successfully replaced {replaced_count} texture(s)")


def main():
    if len(sys.argv) < 2:
        print("Usage: python texture_replacer.py <map_file_path> [output_map_path]")
        print("\nExample:")
        print("  python texture_replacer.py Mission.json")
        print("  python texture_replacer.py Mission.json Mission_Modified.json")
        sys.exit(1)

    map_path = sys.argv[1]
    output_path = sys.argv[2] if len(sys.argv) > 2 else None

    if not Path(map_path).exists():
        print(f"Error: Map file not found: {map_path}")
        sys.exit(1)

    # Step 1: Extract textures
    textures = extract_textures(map_path)
    if not textures:
        print("No textures found to replace")
        sys.exit(0)

    # Step 2: Create mapping file
    mapping_file = "texture_mapping.json"
    create_mapping_file(textures, mapping_file)

    # Step 3: Wait for user to edit
    print("\n" + "=" * 60)
    print("Please edit texture_mapping.json with your replacements.")
    print("Press Enter when ready to apply changes...")
    print("=" * 60)
    input()

    # Step 4: Load mappings
    try:
        mapping = load_mapping_file(mapping_file)
    except FileNotFoundError:
        print(f"Error: {mapping_file} not found")
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON in {mapping_file}: {e}")
        sys.exit(1)

    # Step 5: Apply replacements
    apply_replacements(map_path, mapping, output_path)


if __name__ == "__main__":
    main()
