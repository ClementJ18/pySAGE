"""Test LibraryMapLists asset parsing."""

from sage_map.assets import LibraryMapLists

from .conftest import create_context, create_writing_context, load_asset_bytes


def test_library_map_lists():
    """Test LibraryMapLists asset parsing."""
    asset_bytes = load_asset_bytes("LibraryMapLists")

    context = create_context(asset_bytes, "LibraryMapLists")
    result = LibraryMapLists.parse(context)
    assert result is not None


def test_library_map_lists_write():
    """Test LibraryMapLists asset writing."""
    asset_bytes = load_asset_bytes("LibraryMapLists")

    # Parse the asset
    parse_context = create_context(asset_bytes, "LibraryMapLists")
    result = LibraryMapLists.parse(parse_context)

    # Write the asset
    write_context = create_writing_context("LibraryMapLists")
    result.write(write_context)
    written_bytes = write_context.stream.getvalue()

    # Compare
    assert written_bytes == asset_bytes
