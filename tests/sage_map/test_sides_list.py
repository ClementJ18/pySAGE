"""Test SidesList and BuildLists asset parsing."""

from sage_map.assets import SidesList
from sage_map.assets.sides_list import BuildListInfo, Player

from .conftest import create_context, create_writing_context, load_asset_bytes


def _building(name: str, template: str) -> BuildListInfo:
    return BuildListInfo(name, template, (1.0, 2.0, 0.0), 0.5, True, 0, "", 100, False, False, True)


def test_player_build_list_keeps_order_and_repeated_names():
    player = Player(
        properties={},
        build_list_items=[
            _building("Farm", "GondorFarm"),
            _building("Barracks", "GondorBarracks"),
            _building("Farm", "GondorFarm"),
        ],
    )
    write_context = create_writing_context("SidesList")
    player.write(write_context, False)

    parsed = Player.parse(create_context(write_context.stream.getvalue(), "SidesList"), 6, False)
    assert [item.build_name for item in parsed.build_list_items] == ["Farm", "Barracks", "Farm"]
    assert parsed == player


def test_sides_list():
    """Test SidesList asset parsing."""
    asset_bytes = load_asset_bytes("SidesList")

    context = create_context(asset_bytes, "SidesList")
    result = SidesList.parse(context, False)
    assert result is not None


def test_sides_list_write():
    """Test SidesList asset writing."""
    asset_bytes = load_asset_bytes("SidesList")

    # Parse the asset
    parse_context = create_context(asset_bytes, "SidesList")
    result = SidesList.parse(parse_context, False)

    # Write the asset
    write_context = create_writing_context("SidesList")
    result.write(write_context, False)
    written_bytes = write_context.stream.getvalue()

    # Compare
    assert written_bytes == asset_bytes
