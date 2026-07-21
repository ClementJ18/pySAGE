"""Test WaterSettings asset parsing."""

from sage_map.assets import WaterSettings

from .conftest import create_context, create_writing_context, require_asset


def test_water_settings():
    """Test WaterSettings asset parsing."""
    asset_bytes = require_asset("WaterSettings")

    context = create_context(asset_bytes, "WaterSettings")
    result = WaterSettings.parse(context)
    assert result is not None


def test_water_settings_write():
    """Test WaterSettings asset writing."""
    asset_bytes = require_asset("WaterSettings")

    # Parse the asset
    parse_context = create_context(asset_bytes, "WaterSettings")
    result = WaterSettings.parse(parse_context)

    # Write the asset
    write_context = create_writing_context("WaterSettings")
    result.write(write_context)
    written_bytes = write_context.stream.getvalue()

    # Compare
    assert written_bytes == asset_bytes
