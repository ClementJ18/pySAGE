"""Test MissionHotSpots asset parsing."""

from sage_map.assets import MissionHotSpots

from .conftest import create_context, create_writing_context, require_asset


def test_mission_hotspots():
    """Test MissionHotSpots asset parsing."""
    asset_bytes = require_asset("MissionHotSpots")

    context = create_context(asset_bytes, "MissionHotSpots")
    result = MissionHotSpots.parse(context)
    assert result is not None
    assert hasattr(result, "version")
    assert hasattr(result, "mission_hotspots")


def test_mission_hotspots_write():
    """Test MissionHotSpots asset writing."""
    asset_bytes = require_asset("MissionHotSpots")

    # Parse the asset
    parse_context = create_context(asset_bytes, "MissionHotSpots")
    result = MissionHotSpots.parse(parse_context)

    # Write the asset
    write_context = create_writing_context("MissionHotSpots")
    result.write(write_context)
    written_bytes = write_context.stream.getvalue()

    # Compare
    assert written_bytes == asset_bytes
