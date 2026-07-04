"""Test NamedCameras asset parsing."""

from sage_map.assets import NamedCameras

from .conftest import create_context, create_writing_context, load_asset_bytes


def test_named_cameras():
    """Test NamedCameras asset parsing."""
    asset_bytes = load_asset_bytes("NamedCameras")

    context = create_context(asset_bytes, "NamedCameras")
    result = NamedCameras.parse(context)
    assert result is not None


def test_named_cameras_write():
    """Test NamedCameras asset writing."""
    asset_bytes = load_asset_bytes("NamedCameras")

    # Parse the asset
    parse_context = create_context(asset_bytes, "NamedCameras")
    result = NamedCameras.parse(parse_context)

    # Write the asset
    write_context = create_writing_context("NamedCameras")
    result.write(write_context)
    written_bytes = write_context.stream.getvalue()

    # Compare
    assert written_bytes == asset_bytes
