"""Test HeightMapData asset parsing."""

from sage_map.assets import HeightMapData

from .conftest import create_context, create_writing_context, load_asset_bytes


def test_height_map_data():
    """Test HeightMapData asset parsing."""
    asset_bytes = load_asset_bytes("HeightMapData")

    context = create_context(asset_bytes, "HeightMapData")
    result = HeightMapData.parse(context)
    assert result is not None


def test_height_map_data_write():
    """Test HeightMapData asset writing."""
    asset_bytes = load_asset_bytes("HeightMapData")

    # Parse the asset
    parse_context = create_context(asset_bytes, "HeightMapData")
    result = HeightMapData.parse(parse_context)

    # Write the asset
    write_context = create_writing_context("HeightMapData")
    result.write(write_context)
    written_bytes = write_context.stream.getvalue()

    # Compare
    assert written_bytes == asset_bytes
