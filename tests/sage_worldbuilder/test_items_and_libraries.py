"""The Item List search, the Player List's library maps and faction edits, and the Multiplayer
Positions panel's no-team value. The Qt parts run headless via 'offscreen' and are `full`."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")  # headless; must precede the Qt import

from types import SimpleNamespace

import pytest

from sage_map.assets.library_map_lists import LibraryMapLists, LibraryMaps
from sage_map.assets.mp_positions import MPPosition, MPPositionList
from sage_map.assets.object_list import Object, ObjectsList
from sage_map.assets.player_scripts import PlayerScriptsList, ScriptList
from sage_map.assets.sides_list import BuildList, BuildLists, SidesList
from sage_map.assets.teams import Teams
from sage_map.context import AssetPropertyType
from sage_map.map import Map
from sage_worldbuilder import MapDocument
from sage_worldbuilder.items import ItemKind, map_items
from sage_worldbuilder.players import new_player
from sage_worldbuilder.teams import new_team


def text(name: str, value: str) -> dict:
    return {"name": name, "type": AssetPropertyType.AsciiString, "value": value}


def placed(type_name: str, x: float, y: float, **properties: str) -> Object:
    return Object(
        version=3,
        position=(x, y, 0.0),
        angle=0.0,
        road_type=0,
        type_name=type_name,
        properties={key: text(key, value) for key, value in properties.items()},
        start_pos=0,
        end_pos=0,
    )


def full_map() -> Map:
    map = Map()
    map.sides_list = SidesList(
        version=6,
        unknown1=False,
        players=[new_player(""), new_player("PlyrGood", "Good", "FactionMen", True)],
        start_pos=0,
        end_pos=0,
    )
    map.player_scripts_list = PlayerScriptsList(
        version=1,
        script_lists=[ScriptList(version=1, items=[], start_pos=0, end_pos=0) for _ in range(2)],
        start_pos=0,
        end_pos=0,
    )
    map.build_lists = BuildLists(
        version=1,
        build_lists=[
            BuildList(None, (AssetPropertyType.AsciiString, 0, owner), [])
            for owner in ("UNKNOWN", "Men")
        ],
        start_pos=0,
        end_pos=0,
    )
    map.library_map_lists = LibraryMapLists(
        version=1,
        lists=[LibraryMaps(version=1, values=[], start_pos=0, end_pos=0) for _ in range(2)],
        start_pos=0,
        end_pos=0,
    )
    map.teams = Teams(version=1, teams=[new_team("Riders", "PlyrGood")], start_pos=0, end_pos=0)
    map.objects_list = ObjectsList(
        version=3,
        object_list=[
            placed("GondorFighter", 10, 20, objectName="Boromir"),
            placed("GondorFighter", 30, 40),
            placed("*Waypoints/Waypoint", 50, 60, waypointName="Gate"),
        ],
        start_pos=0,
        end_pos=0,
    )
    map.polygon_triggers = SimpleNamespace(polygon_triggers=[SimpleNamespace(name="Keep")])
    return map


def test_map_items_lists_filters_and_searches():
    map = full_map()
    kinds = [(row.kind, row.name) for row in map_items(map)]
    assert kinds == [
        (ItemKind.OBJECT, "Boromir"),
        (ItemKind.OBJECT, ""),
        (ItemKind.WAYPOINT, "Gate"),
        (ItemKind.AREA, "Keep"),
        (ItemKind.TEAM, "PlyrGood/Riders"),
    ]
    assert [
        row.name for row in map_items(map, only_named=True, kinds=frozenset({ItemKind.OBJECT}))
    ] == ["Boromir"]
    assert [row.name for row in map_items(map, "gondorfighter")] == ["Boromir", ""]
    assert [row.name for row in map_items(map, "(50, 60)")] == ["Gate"]


qt = pytest.mark.full


@pytest.fixture(scope="module")
def qapp():
    pytest.importorskip("PyQt6", reason="the [worldbuilder] extra (PyQt6) is not installed")
    from PyQt6.QtWidgets import QApplication  # noqa: PLC0415

    yield QApplication.instance() or QApplication([])


class Host:
    def __init__(self, document: MapDocument, game=None) -> None:
        self.document = document
        self.game = game

    def execute(self, command) -> None:
        self.document.execute(command)


@qt
def test_player_libraries_and_faction(qapp):
    from sage_worldbuilder.ui.players import PlayersPanel  # noqa: PLC0415

    map = full_map()
    document = MapDocument(map)
    panel = PlayersPanel(Host(document), lambda: ["KI Kern", "lib_gollumspawn"])
    document.subscribe(lambda _change: panel.refresh())
    panel.list.setCurrentRow(1)

    assert [panel.library_choice.itemText(i) for i in range(panel.library_choice.count())] == [
        "KI Kern",
        "lib_gollumspawn",
    ]
    panel.add_library("KI Kern")
    panel.add_library("ki kern")  # already there
    assert map.library_map_lists.lists[1].values == ["Libraries\\KI Kern\\KI Kern.map"]
    panel.libraries.setCurrentRow(0)
    panel.remove_library()
    assert map.library_map_lists.lists[1].values == []

    faction = panel.form.fields["playerFaction"]
    faction.setCurrentText("FactionElves")
    faction.lineEdit().editingFinished.emit()
    assert map.build_lists.build_lists[1].faction_name_property[2] == "Elves"
    document.stack.undo()
    assert map.build_lists.build_lists[1].faction_name_property[2] == "Men"


@qt
def test_item_list_panel_opens_teams(qapp):
    from sage_worldbuilder.ui.item_list import ItemListPanel  # noqa: PLC0415

    opened = []
    panel = ItemListPanel(Host(MapDocument(full_map())), opened.append)
    assert panel.tree.topLevelItemCount() == 5
    panel.only_named.setChecked(True)
    assert panel.tree.topLevelItemCount() == 4
    panel.kind.setCurrentText("Team")
    panel._open(panel.tree.topLevelItem(0))
    assert opened == ["PlyrGood/Riders"]


@qt
def test_item_list_sorts_by_a_clicked_column_and_back_to_map_order(qapp):
    from PyQt6.QtCore import Qt  # noqa: PLC0415

    from sage_worldbuilder.ui.item_list import ItemListPanel, natural_key  # noqa: PLC0415

    assert natural_key("Tower2") < natural_key("tower10")
    assert natural_key("at (-50, 0)") < natural_key("at (20, 0)")

    panel = ItemListPanel(Host(MapDocument(full_map())))
    tree = panel.tree

    def column(index: int) -> list[str]:
        return [tree.topLevelItem(row).text(index) for row in range(tree.topLevelItemCount())]

    map_order = column(1)
    assert tree.header().sortIndicatorSection() == -1  # unsorted until a header is clicked

    tree.sortByColumn(1, Qt.SortOrder.AscendingOrder)
    names = sorted(map_order, key=natural_key)
    assert column(1) == names
    tree.sortByColumn(1, Qt.SortOrder.DescendingOrder)
    assert column(1) == names[::-1]

    panel.refresh()  # a rebuild keeps the chosen sort
    assert column(1) == names[::-1]

    tree.header().setSortIndicator(-1, Qt.SortOrder.AscendingOrder)
    assert column(1) == map_order


@qt
def test_no_team_positions_show_and_keep_their_value(qapp):
    from sage_worldbuilder.ui.map_settings import MultiplayerPositionsPanel  # noqa: PLC0415

    map = Map()
    position = MPPosition(1, True, True, True, 0xFFFFFFFF, [], 0, 0)
    map.mp_positions_list = MPPositionList(version=1, positions=[position], start_pos=0, end_pos=0)
    document = MapDocument(map)
    panel = MultiplayerPositionsPanel(Host(document))

    assert panel.team.value() == -1 and panel.team.text() == "none"
    panel.team.setValue(3)
    assert position.team == 3
    panel.team.setValue(-1)
    assert position.team == 0xFFFFFFFF
