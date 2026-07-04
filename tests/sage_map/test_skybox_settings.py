"""Test SkyboxSettings asset parsing."""

import pytest

from sage_map.assets import SkyboxSettings

from .conftest import create_context, create_writing_context, load_asset_bytes


@pytest.mark.skip(reason="No test data available")
def test_skybox_settings():
    """Test SkyboxSettings asset parsing."""
    asset_bytes = load_asset_bytes("SkyboxSettings")

    context = create_context(asset_bytes, "SkyboxSettings")
    result = SkyboxSettings.parse(context)
    assert result is not None
    assert hasattr(result, "version")
    assert hasattr(result, "position")


@pytest.mark.skip(reason="No test data available")
def test_skybox_settings_write():
    """Test SkyboxSettings asset writing."""
    asset_bytes = load_asset_bytes("SkyboxSettings")

    # Parse the asset
    parse_context = create_context(asset_bytes, "SkyboxSettings")
    result = SkyboxSettings.parse(parse_context)

    # Write the asset
    write_context = create_writing_context("SkyboxSettings")
    result.write(write_context)
    written_bytes = write_context.stream.getvalue()

    # Compare
    assert written_bytes == asset_bytes
