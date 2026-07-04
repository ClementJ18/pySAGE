"""Test MissionObjectives asset parsing."""

import pytest

from sage_map.assets import MissionObjectives

from .conftest import create_context, create_writing_context, load_asset_bytes


@pytest.mark.skip(reason="No test data available")
def test_mission_objectives():
    """Test MissionObjectives asset parsing."""
    asset_bytes = load_asset_bytes("MissionObjectives")

    context = create_context(asset_bytes, "MissionObjectives")
    result = MissionObjectives.parse(context)
    assert result is not None
    assert hasattr(result, "version")
    assert hasattr(result, "objectives")


@pytest.mark.skip(reason="No test data available")
def test_mission_objectives_write():
    """Test MissionObjectives asset writing."""
    asset_bytes = load_asset_bytes("MissionObjectives")

    # Parse the asset
    parse_context = create_context(asset_bytes, "MissionObjectives")
    result = MissionObjectives.parse(parse_context)

    # Write the asset
    write_context = create_writing_context("MissionObjectives")
    result.write(write_context)
    written_bytes = write_context.stream.getvalue()

    # Compare
    assert written_bytes == asset_bytes
