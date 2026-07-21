"""Test FogSettings asset parsing."""

from sage_map.assets import FogSettings

from .conftest import create_context, create_writing_context, require_asset


def test_fog_settings():
    """Test FogSettings asset parsing."""
    asset_bytes = require_asset("FogSettings")

    context = create_context(asset_bytes, "FogSettings")
    result = FogSettings.parse(context)
    assert result is not None
    assert hasattr(result, "version")


def test_fog_settings_write():
    """Test FogSettings asset writing."""
    asset_bytes = require_asset("FogSettings")

    # Parse the asset
    parse_context = create_context(asset_bytes, "FogSettings")
    result = FogSettings.parse(parse_context)

    # Write the asset
    write_context = create_writing_context("FogSettings")
    result.write(write_context)
    written_bytes = write_context.stream.getvalue()

    # Compare
    assert written_bytes == asset_bytes
