"""Test StandingWaterAreas asset parsing."""

from sage_map.assets import StandingWaterAreas

from .conftest import create_context, create_writing_context, load_asset_bytes


def test_standing_water_areas():
    """Test StandingWaterAreas asset parsing."""
    asset_bytes = load_asset_bytes("StandingWaterAreas")

    context = create_context(asset_bytes, "StandingWaterAreas")
    result = StandingWaterAreas.parse(context)
    assert result is not None


def test_standing_water_areas_write():
    """Test StandingWaterAreas asset writing."""
    asset_bytes = load_asset_bytes("StandingWaterAreas")

    # Parse the asset
    parse_context = create_context(asset_bytes, "StandingWaterAreas")
    result = StandingWaterAreas.parse(parse_context)

    # Write the asset
    write_context = create_writing_context("StandingWaterAreas")
    result.write(write_context)
    written_bytes = write_context.stream.getvalue()

    # Compare
    assert written_bytes == asset_bytes
