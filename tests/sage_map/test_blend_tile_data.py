"""Test BlendTileData asset parsing."""

from sage_map.assets import BlendTileData, HeightMapData

from .conftest import create_context, create_writing_context, load_asset_bytes


def test_blend_tile_data():
    """Test BlendTileData asset parsing."""
    asset_bytes = load_asset_bytes("BlendTileData")
    heght_map_bytes = load_asset_bytes("HeightMapData")

    context = create_context(asset_bytes, "BlendTileData")
    height_map_context = create_context(heght_map_bytes, "HeightMapData")

    height_map = HeightMapData.parse(height_map_context)
    result = BlendTileData.parse(context, height_map)
    assert result is not None


def test_blend_tile_data_write():
    """Test BlendTileData asset writing."""
    asset_bytes = load_asset_bytes("BlendTileData")
    height_map_bytes = load_asset_bytes("HeightMapData")

    # Parse the assets
    parse_context = create_context(asset_bytes, "BlendTileData")
    height_map_context = create_context(height_map_bytes, "HeightMapData")
    height_map = HeightMapData.parse(height_map_context)
    result = BlendTileData.parse(parse_context, height_map)

    # Write the asset
    write_context = create_writing_context("BlendTileData")
    result.write(write_context)
    written_bytes = write_context.stream.getvalue()

    # Compare
    assert written_bytes == asset_bytes


def _parse_fixture() -> BlendTileData:
    height_map = HeightMapData.parse(
        create_context(load_asset_bytes("HeightMapData"), "HeightMapData")
    )
    return BlendTileData.parse(
        create_context(load_asset_bytes("BlendTileData"), "BlendTileData"), height_map
    )


def _write(data: BlendTileData) -> BlendTileData:
    write_context = create_writing_context("BlendTileData")
    data.write(write_context)
    height_map = HeightMapData.parse(
        create_context(load_asset_bytes("HeightMapData"), "HeightMapData")
    )
    return BlendTileData.parse(
        create_context(write_context.stream.getvalue(), "BlendTileData"), height_map
    )


def test_blend_tile_data_keeps_raw_zero_counts():
    """An empty list stored with a raw 0 count writes back as 0, not as the usual N+1."""
    data = _parse_fixture()
    data.blend_descriptions = []
    data.blends_count_raw = 0
    data.cliff_texture_mappings = []
    data.parsed_cliff_texture_mappings_count = 0

    reparsed = _write(data)

    assert reparsed.blends_count_raw == 0
    assert reparsed.parsed_cliff_texture_mappings_count == 0


def test_blend_tile_data_counts_follow_edited_lists():
    """Once a list is edited, the stored count follows its length, whatever the raw value was."""
    data = _parse_fixture()
    data.cliff_texture_mappings = []
    data.parsed_cliff_texture_mappings_count = 5

    reparsed = _write(data)

    assert reparsed.parsed_cliff_texture_mappings_count == 1
    assert reparsed.cliff_texture_mappings == []
