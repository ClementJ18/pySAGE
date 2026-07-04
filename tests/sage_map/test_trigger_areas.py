"""Test TriggerAreas asset parsing."""

from sage_map.assets import TriggerAreas

from .conftest import create_context, create_writing_context, load_asset_bytes


def test_trigger_areas():
    """Test TriggerAreas asset parsing."""
    asset_bytes = load_asset_bytes("TriggerAreas")

    context = create_context(asset_bytes, "TriggerAreas")
    result = TriggerAreas.parse(context)
    assert result is not None


def test_trigger_areas_write():
    """Test TriggerAreas asset writing."""
    asset_bytes = load_asset_bytes("TriggerAreas")

    # Parse the asset
    parse_context = create_context(asset_bytes, "TriggerAreas")
    result = TriggerAreas.parse(parse_context)

    # Write the asset
    write_context = create_writing_context("TriggerAreas")
    result.write(write_context)
    written_bytes = write_context.stream.getvalue()

    # Compare
    assert written_bytes == asset_bytes
