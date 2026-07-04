"""Test StandingWaveAreas asset parsing."""

from sage_map.assets import StandingWaveAreas

from .conftest import create_context, create_writing_context, load_asset_bytes


def test_standing_wave_areas():
    """Test StandingWaveAreas asset parsing."""
    asset_bytes = load_asset_bytes("StandingWaveAreas")

    context = create_context(asset_bytes, "StandingWaveAreas")
    result = StandingWaveAreas.parse(context)
    assert result is not None


def test_standing_wave_areas_write():
    """Test StandingWaveAreas asset writing."""
    asset_bytes = load_asset_bytes("StandingWaveAreas")

    # Parse the asset
    parse_context = create_context(asset_bytes, "StandingWaveAreas")
    result = StandingWaveAreas.parse(parse_context)

    # Write the asset
    write_context = create_writing_context("StandingWaveAreas")
    result.write(write_context)
    written_bytes = write_context.stream.getvalue()

    # Compare
    assert written_bytes == asset_bytes
