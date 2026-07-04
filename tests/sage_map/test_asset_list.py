"""Test AssetList asset parsing."""

import pytest

from sage_map.assets import AssetList

from .conftest import create_context, create_writing_context, load_asset_bytes


@pytest.mark.skip(reason="No test data available for AssetList yet")
def test_asset_list():
    """Test AssetList asset parsing."""
    asset_bytes = load_asset_bytes("AssetList")

    context = create_context(asset_bytes, "AssetList")
    result = AssetList.parse(context)
    assert result is not None


@pytest.mark.skip(reason="No test data available for AssetList yet")
def test_asset_list_write():
    """Test AssetList asset writing."""
    asset_bytes = load_asset_bytes("AssetList")

    # Parse the asset
    parse_context = create_context(asset_bytes, "AssetList")
    result = AssetList.parse(parse_context)

    # Write the asset
    write_context = create_writing_context("AssetList")
    result.write(write_context)
    written_bytes = write_context.stream.getvalue()

    # Compare
    assert written_bytes == asset_bytes
