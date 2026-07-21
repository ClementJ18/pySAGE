"""Test AssetList asset parsing."""

from sage_map.assets import AssetList

from .conftest import create_context, create_writing_context, require_asset


def test_asset_list():
    """Test AssetList asset parsing."""
    asset_bytes = require_asset("AssetList")

    context = create_context(asset_bytes, "AssetList")
    result = AssetList.parse(context)
    assert result is not None


def test_asset_list_write():
    """Test AssetList asset writing."""
    asset_bytes = require_asset("AssetList")

    # Parse the asset
    parse_context = create_context(asset_bytes, "AssetList")
    result = AssetList.parse(parse_context)

    # Write the asset
    write_context = create_writing_context("AssetList")
    result.write(write_context)
    written_bytes = write_context.stream.getvalue()

    # Compare
    assert written_bytes == asset_bytes
