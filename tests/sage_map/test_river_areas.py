"""Test RiverAreas asset parsing."""

from sage_map.assets import RiverAreas

from .conftest import create_context, create_writing_context, load_asset_bytes


def test_river_areas():
    """Test RiverAreas asset parsing."""
    asset_bytes = load_asset_bytes("RiverAreas")

    context = create_context(asset_bytes, "RiverAreas")
    result = RiverAreas.parse(context)
    assert result is not None


def test_river_areas_write():
    """Test RiverAreas asset writing."""
    asset_bytes = load_asset_bytes("RiverAreas")

    # Parse the asset
    parse_context = create_context(asset_bytes, "RiverAreas")
    result = RiverAreas.parse(parse_context)

    # Write the asset
    write_context = create_writing_context("RiverAreas")
    result.write(write_context)
    written_bytes = write_context.stream.getvalue()

    # Compare
    assert written_bytes == asset_bytes
