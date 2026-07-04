"""Test SidesList and BuildLists asset parsing."""

from sage_map.assets import SidesList

from .conftest import create_context, create_writing_context, load_asset_bytes


def test_sides_list():
    """Test SidesList asset parsing."""
    asset_bytes = load_asset_bytes("SidesList")

    context = create_context(asset_bytes, "SidesList")
    result = SidesList.parse(context, False)
    assert result is not None


def test_sides_list_write():
    """Test SidesList asset writing."""
    asset_bytes = load_asset_bytes("SidesList")

    # Parse the asset
    parse_context = create_context(asset_bytes, "SidesList")
    result = SidesList.parse(parse_context, False)

    # Write the asset
    write_context = create_writing_context("SidesList")
    result.write(write_context, False)
    written_bytes = write_context.stream.getvalue()

    # Compare
    assert written_bytes == asset_bytes
