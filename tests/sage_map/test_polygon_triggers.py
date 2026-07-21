"""Test PolygonTriggers asset parsing."""

from sage_map.assets import PolygonTriggers

from .conftest import create_context, create_writing_context, require_asset


def test_polygon_triggers():
    """Test PolygonTriggers asset parsing."""
    asset_bytes = require_asset("PolygonTriggers")

    context = create_context(asset_bytes, "PolygonTriggers")
    result = PolygonTriggers.parse(context)
    assert result is not None


def test_polygon_triggers_write():
    """Test PolygonTriggers asset writing."""
    asset_bytes = require_asset("PolygonTriggers")

    # Parse the asset
    parse_context = create_context(asset_bytes, "PolygonTriggers")
    result = PolygonTriggers.parse(parse_context)

    # Write the asset
    write_context = create_writing_context("PolygonTriggers")
    result.write(write_context)
    written_bytes = write_context.stream.getvalue()

    # Compare
    assert written_bytes == asset_bytes
