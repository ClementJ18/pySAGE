"""Test PlayerScriptsList asset parsing."""

from sage_map.assets import PlayerScriptsList

from .conftest import create_context, create_writing_context, load_asset_bytes


def test_player_scripts_list():
    """Test PlayerScriptsList asset parsing."""
    asset_bytes = load_asset_bytes("PlayerScriptsList")

    context = create_context(asset_bytes, "PlayerScriptsList")
    result = PlayerScriptsList.parse(context)
    assert result is not None


def test_player_scripts_list_write():
    """Test PlayerScriptsList asset writing."""
    asset_bytes = load_asset_bytes("PlayerScriptsList")

    parse_context = create_context(asset_bytes, "PlayerScriptsList")
    result = PlayerScriptsList.parse(parse_context)

    write_context = create_writing_context("PlayerScriptsList")
    result.write(write_context)
    written_bytes = write_context.stream.getvalue()

    assert written_bytes == asset_bytes
