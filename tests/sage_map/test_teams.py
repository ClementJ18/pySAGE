"""Test Teams asset parsing."""

from sage_map.assets import Teams

from .conftest import create_context, create_writing_context, load_asset_bytes


def test_teams():
    """Test Teams asset parsing."""
    asset_bytes = load_asset_bytes("Teams")

    context = create_context(asset_bytes, "Teams")
    result = Teams.parse(context)
    assert result is not None
    assert hasattr(result, "teams")
    assert hasattr(result, "version")


def test_teams_write():
    """Test Teams asset writing."""
    asset_bytes = load_asset_bytes("Teams")

    # Parse the asset
    parse_context = create_context(asset_bytes, "Teams")
    result = Teams.parse(parse_context)

    # Write the asset
    write_context = create_writing_context("Teams")
    result.write(write_context)
    written_bytes = write_context.stream.getvalue()

    # Compare
    assert written_bytes == asset_bytes
