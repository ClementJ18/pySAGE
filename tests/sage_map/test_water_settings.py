"""Test WaterSettings asset parsing."""

import pytest

from sage_map.assets import WaterSettings

from .conftest import create_context, create_writing_context, load_asset_bytes


@pytest.mark.skip(reason="No test data available for AssetList yet")
def test_water_settings():
    """Test WaterSettings asset parsing."""
    asset_bytes = load_asset_bytes("WaterSettings")

    context = create_context(asset_bytes, "WaterSettings")
    result = WaterSettings.parse(context)
    assert result is not None


@pytest.mark.skip(reason="No test data available for AssetList yet")
def test_water_settings_write():
    """Test WaterSettings asset writing."""
    asset_bytes = load_asset_bytes("WaterSettings")

    # Parse the asset
    parse_context = create_context(asset_bytes, "WaterSettings")
    result = WaterSettings.parse(parse_context)

    # Write the asset
    write_context = create_writing_context("WaterSettings")
    result.write(write_context)
    written_bytes = write_context.stream.getvalue()

    # Compare
    assert written_bytes == asset_bytes
