"""Test MissionObjectives asset parsing."""

from sage_map.assets import MissionObjectives

from .conftest import create_context, create_writing_context, require_asset


def test_mission_objectives():
    """Test MissionObjectives asset parsing."""
    asset_bytes = require_asset("MissionObjectives")

    context = create_context(asset_bytes, "MissionObjectives")
    result = MissionObjectives.parse(context)
    assert result is not None
    assert hasattr(result, "version")
    assert hasattr(result, "objectives")


def test_mission_objectives_write():
    """Test MissionObjectives asset writing."""
    asset_bytes = require_asset("MissionObjectives")

    # Parse the asset
    parse_context = create_context(asset_bytes, "MissionObjectives")
    result = MissionObjectives.parse(parse_context)

    # Write the asset
    write_context = create_writing_context("MissionObjectives")
    result.write(write_context)
    written_bytes = write_context.stream.getvalue()

    # Compare
    assert written_bytes == asset_bytes
