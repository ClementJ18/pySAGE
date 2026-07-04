"""Test CameraAnimationList asset parsing."""

from sage_map.assets import CameraAnimationList

from .conftest import create_context, create_writing_context, load_asset_bytes


def test_camera_animation_list():
    """Test CameraAnimationList asset parsing."""
    asset_bytes = load_asset_bytes("CameraAnimationList")

    context = create_context(asset_bytes, "CameraAnimationList")
    result = CameraAnimationList.parse(context)
    assert result is not None


def test_camera_animation_list_write():
    """Test CameraAnimationList asset writing."""
    asset_bytes = load_asset_bytes("CameraAnimationList")

    # Parse the asset
    parse_context = create_context(asset_bytes, "CameraAnimationList")
    result = CameraAnimationList.parse(parse_context)

    # Write the asset
    write_context = create_writing_context("CameraAnimationList")
    result.write(write_context)
    written_bytes = write_context.stream.getvalue()

    # Compare
    assert written_bytes == asset_bytes
