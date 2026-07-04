"""Test EnvironmentData asset parsing."""

from sage_map.assets import EnvironmentData

from .conftest import create_context, create_writing_context, load_asset_bytes


def test_environment_data():
    """Test EnvironmentData asset parsing."""
    asset_bytes = load_asset_bytes("EnvironmentData")

    context = create_context(asset_bytes, "EnvironmentData")
    result = EnvironmentData.parse(context)
    assert result is not None


def test_environment_data_write():
    """Test EnvironmentData asset writing."""
    asset_bytes = load_asset_bytes("EnvironmentData")

    # Parse the asset
    parse_context = create_context(asset_bytes, "EnvironmentData")
    result = EnvironmentData.parse(parse_context)

    # Write the asset
    write_context = create_writing_context("EnvironmentData")
    result.write(write_context)
    written_bytes = write_context.stream.getvalue()

    # Compare
    assert written_bytes == asset_bytes
