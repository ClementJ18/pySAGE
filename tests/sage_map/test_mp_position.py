"""Test MPPositionList asset parsing."""

from sage_map.assets import MPPositionList

from .conftest import create_context, create_writing_context, load_asset_bytes


def test_mp_positions_list():
    """Test MPPositionList asset parsing."""
    asset_bytes = load_asset_bytes("MPPositionList")

    context = create_context(asset_bytes, "MPPositionList")
    result = MPPositionList.parse(context)
    assert result is not None


def test_mp_positions_list_write():
    """Test MPPositionList asset writing."""
    asset_bytes = load_asset_bytes("MPPositionList")

    # Parse the asset
    parse_context = create_context(asset_bytes, "MPPositionList")
    result = MPPositionList.parse(parse_context)

    # Write the asset
    write_context = create_writing_context("MPPositionList")
    result.write(write_context)
    written_bytes = write_context.stream.getvalue()

    # Compare
    assert written_bytes == asset_bytes
