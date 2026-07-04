"""Test CastleTemplates asset parsing."""

from sage_map.assets import CastleTemplates

from .conftest import create_context, create_writing_context, load_asset_bytes


def test_castle_templates():
    """Test CastleTemplates asset parsing."""
    asset_bytes = load_asset_bytes("CastleTemplates")

    context = create_context(asset_bytes, "CastleTemplates")
    result = CastleTemplates.parse(context)
    assert result is not None
    assert hasattr(result, "templates")
    assert hasattr(result, "version")


def test_castle_templates_write():
    """Test CastleTemplates asset writing."""
    asset_bytes = load_asset_bytes("CastleTemplates")

    # Parse the asset
    parse_context = create_context(asset_bytes, "CastleTemplates")
    result = CastleTemplates.parse(parse_context)

    # Write the asset
    write_context = create_writing_context("CastleTemplates")
    result.write(write_context)
    written_bytes = write_context.stream.getvalue()

    # Compare
    assert written_bytes == asset_bytes
