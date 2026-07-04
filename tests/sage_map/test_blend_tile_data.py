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
