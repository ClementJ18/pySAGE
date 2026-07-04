"""Test ObjectsList asset parsing."""

from sage_map.assets import ObjectsList

from .conftest import create_context, create_writing_context, load_asset_bytes


def test_objects_list():
    """Test ObjectsList asset parsing."""
    asset_bytes = load_asset_bytes("ObjectsList")

    context = create_context(asset_bytes, "ObjectsList")
    result = ObjectsList.parse(context)
    assert result is not None


def test_objects_list_write():
    """Test ObjectsList asset writing."""
    asset_bytes = load_asset_bytes("ObjectsList")

    # Parse the asset
    parse_context = create_context(asset_bytes, "ObjectsList")
    result = ObjectsList.parse(parse_context)

    # Write the asset
    write_context = create_writing_context("ObjectsList")
    result.write(write_context)
    written_bytes = write_context.stream.getvalue()

    # Compare
    assert written_bytes == asset_bytes
