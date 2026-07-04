"""Test WaypointsList asset parsing."""

from sage_map.assets import WaypointsList

from .conftest import create_context, create_writing_context, load_asset_bytes


def test_waypoints_list():
    """Test WaypointsList asset parsing."""
    asset_bytes = load_asset_bytes("WaypointsList")

    context = create_context(asset_bytes, "WaypointsList")
    result = WaypointsList.parse(context)
    assert result is not None


def test_waypoints_list_write():
    """Test WaypointsList asset writing."""
    asset_bytes = load_asset_bytes("WaypointsList")

    # Parse the asset
    parse_context = create_context(asset_bytes, "WaypointsList")
    result = WaypointsList.parse(parse_context)

    # Write the asset
    write_context = create_writing_context("WaypointsList")
    result.write(write_context)
    written_bytes = write_context.stream.getvalue()

    # Compare
    assert written_bytes == asset_bytes
