"""Test WorldInfo asset parsing."""

from sage_map.assets import WorldInfo

from .conftest import create_context, create_writing_context, load_asset_bytes


def test_world_info():
    """Test WorldInfo asset parsing."""
    asset_bytes = load_asset_bytes("WorldInfo")

    context = create_context(asset_bytes, "WorldInfo")
    result = WorldInfo.parse(context)
    assert result is not None


def test_world_info_write():
    """Test WorldInfo asset writing."""
    asset_bytes = load_asset_bytes("WorldInfo")

    # Parse the asset
    parse_context = create_context(asset_bytes, "WorldInfo")
    result = WorldInfo.parse(parse_context)

    # Write the asset
    write_context = create_writing_context("WorldInfo")
    result.write(write_context)
    written_bytes = write_context.stream.getvalue()

    # Compare
    assert written_bytes == asset_bytes
