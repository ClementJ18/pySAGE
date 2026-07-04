"""Test GlobalLighting asset parsing."""

from sage_map.assets import GlobalLighting

from .conftest import create_context, create_writing_context, load_asset_bytes


def test_global_lighting():
    """Test GlobalLighting asset parsing."""
    asset_bytes = load_asset_bytes("GlobalLighting")

    context = create_context(asset_bytes, "GlobalLighting")
    result = GlobalLighting.parse(context)
    assert result is not None


def test_global_lighting_write():
    """Test GlobalLighting asset writing."""
    asset_bytes = load_asset_bytes("GlobalLighting")

    # Parse the asset
    parse_context = create_context(asset_bytes, "GlobalLighting")
    result = GlobalLighting.parse(parse_context)

    # Write the asset
    write_context = create_writing_context("GlobalLighting")
    result.write(write_context)
    written_bytes = write_context.stream.getvalue()

    # Compare
    assert written_bytes == asset_bytes
