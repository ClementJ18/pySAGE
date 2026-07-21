"""Test GlobalVersion asset parsing."""

from sage_map.assets import GlobalVersion

from .conftest import create_context, create_writing_context, require_asset


def test_global_version():
    """Test GlobalVersion asset parsing."""
    asset_bytes = require_asset("GlobalVersion")

    context = create_context(asset_bytes, "GlobalVersion")
    result = GlobalVersion.parse(context)
    assert result is not None
    assert hasattr(result, "version")


def test_global_version_write():
    """Test GlobalVersion asset writing."""
    asset_bytes = require_asset("GlobalVersion")

    # Parse the asset
    parse_context = create_context(asset_bytes, "GlobalVersion")
    result = GlobalVersion.parse(parse_context)

    # Write the asset
    write_context = create_writing_context("GlobalVersion")
    result.write(write_context)
    written_bytes = write_context.stream.getvalue()

    # Compare
    assert written_bytes == asset_bytes
