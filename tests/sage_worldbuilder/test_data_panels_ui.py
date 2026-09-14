"""Qt-level tests for the property form and the Player List, Teams, Map Settings and
Multiplayer Positions panels. Headless via the Qt 'offscreen' platform; marked `full`."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")  # headless; must precede the Qt import

from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.full

pytest.importorskip("PyQt6", reason="the [worldbuilder] extra (PyQt6) is not installed")

from PyQt6.QtWidgets import QApplication  # noqa: E402

from sage_ini.engine import Engine, EnumDelta  # noqa: E402
from sage_map.assets.global_lighting import TimeOfTheDay  # noqa: E402
from sage_map.assets.mp_positions import MPPosition, MPPositionList  # noqa: E402
from sage_map.assets.player_scripts import PlayerScriptsList, ScriptList  # noqa: E402
from sage_map.assets.sides_list import SidesList  # noqa: E402
from sage_map.assets.teams import Teams  # noqa: E402
from sage_map.assets.world_info import WorldInfo  # noqa: E402
from sage_map.map import Map  # noqa: E402
from sage_worldbuilder import Change, ChangeKind, MapDocument  # noqa: E402
from sage_worldbuilder.players import new_player, player_name  # noqa: E402
from sage_worldbuilder.properties import WORLD_INFO_SPECS  # noqa: E402
from sage_worldbuilder.teams import new_team, team_name, team_owner  # noqa: E402
from sage_worldbuilder.ui.map_settings import (  # noqa: E402
    MapSettingsPanel,
    MultiplayerPositionsPanel,
)
from sage_worldbuilder.ui.players import PlayersPanel  # noqa: E402
from sage_worldbuilder.ui.property_form import PropertyForm  # noqa: E402
from sage_worldbuilder.ui.teams import TeamsPanel  # noqa: E402

SETTINGS = Change(ChangeKind.SETTINGS)


@pytest.fixture(scope="module")
def qapp():
    yield QApplication.instance() or QApplication([])


class Host:
    def __init__(self, document: MapDocument, game=None) -> None:
        self.document = document
        self.game = game

    def execute(self, command) -> None:
        self.document.execute(command)


def map_with_players() -> Map:
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
    map.teams = Teams(
        version=1,
        teams=[new_team("teamPlyrGood", "PlyrGood"), new_team("Raiders", "PlyrEvil")],
        start_pos=0,
        end_pos=0,
    )
    return map


def items(combo) -> list[str]:
    return [combo.itemText(index) for index in range(combo.count())]


def connected(panel, document: MapDocument):
    document.subscribe(lambda _change: panel.refresh())
    return panel


def test_property_form_writes_typed_values_only_when_changed(qapp):
    document = MapDocument(Map())
    properties: dict = {}
    form = PropertyForm(WORLD_INFO_SPECS, document.execute, SETTINGS)
    form.set_properties(properties)

    form.fields["cameraPitchAngle"].setValue(40.0)
    assert properties["cameraPitchAngle"]["value"] == 40.0
    form.fields["isScenarioMultiplayer"].setChecked(False)  # already the default, and absent
    assert "isScenarioMultiplayer" not in properties
    compression = form.fields["compression"]
    assert items(compression) == ["No compression", "RefPack"]
    assert compression.currentIndex() == 1

    document.stack.undo()
    assert properties == {}


def test_weather_drop_down_follows_a_patched_engine(qapp):
    """The form is built long before a `.sagepatch` is applied, so a weather the patched engine
    adds has to reach an existing drop-down on the next reload."""
    document = MapDocument(Map())
    properties: dict = {}
    form = PropertyForm(WORLD_INFO_SPECS, document.execute, SETTINGS)
    form.set_properties(properties)
    assert items(form.fields["weather"]) == ["Normal", "Snowy"]

    engine = Engine(enum_members=(EnumDelta("MapWeatherType", "DESERT", 2, "desert-weather"),))
    with engine.activate():
        form.reload()
        weather = form.fields["weather"]
        assert items(weather) == ["Normal", "Snowy", "Desert"]
        weather.setCurrentIndex(2)
        assert properties["weather"]["value"] == 2

    form.reload()
    assert items(form.fields["weather"]) == ["Normal", "Snowy"]
    # The map keeps the index it was authored with; the stock engine simply cannot name it.
    assert properties["weather"]["value"] == 2
    assert form.fields["weather"].currentIndex() == -1


def test_players_panel_adds_edits_and_removes(qapp):
    map = map_with_players()
    document = MapDocument(map)
    game = SimpleNamespace(tables={"factions": {"FactionMen": 1, "FactionElves": 1}})
    panel = connected(PlayersPanel(Host(document, game)), document)

    assert panel.list.count() == 2 and "(neutral)" in panel.list.item(0).text()
    assert "PlyrEvil/Raiders" in panel.orphans.text()
    panel.list.setCurrentRow(0)
    assert not panel.remove_button.isEnabled()

    panel.add()
    assert panel.list.count() == 3 and panel.list.currentRow() == 2
    faction = panel.form.fields["playerFaction"]
    assert items(faction) == ["FactionElves", "FactionMen"]
    faction.setCurrentText("FactionElves")
    faction.lineEdit().editingFinished.emit()
    assert map.sides_list.players[2].properties["playerFaction"]["value"] == "FactionElves"

    panel.remove_selected()
    assert [player_name(p) for p in map.sides_list.players] == ["", "PlyrGood"]
    assert len(map.player_scripts_list.script_lists) == 2


def tree_labels(tree) -> list[str]:
    labels = []
    for index in range(tree.topLevelItemCount()):
        group = tree.topLevelItem(index)
        labels.append(group.text(0))
        labels += [f"  {group.child(child).text(0)}" for child in range(group.childCount())]
    return labels


def test_teams_panel_groups_teams_by_player(qapp):
    map = map_with_players()
    document = MapDocument(map)
    game = SimpleNamespace(tables={"objects": {"GondorArcherHorde": 1}})
    panel = connected(TeamsPanel(Host(document, game)), document)
    teams = map.teams.teams

    assert tree_labels(panel.tree) == [
        "(neutral) (0)",
        "PlyrGood (1)",
        "  teamPlyrGood",
        "(no owner) (1)",
        "  Raiders",
    ]

    assert panel.select_team("PlyrEvil/Raiders")
    owner = panel.forms[0].fields["teamOwner"]
    assert items(owner) == ["", "PlyrGood"]
    owner.setCurrentText("PlyrGood")
    owner.lineEdit().editingFinished.emit()
    assert team_owner(teams[1]) == "PlyrGood"
    assert tree_labels(panel.tree) == [
        "(neutral) (0)",
        "PlyrGood (2)",
        "  teamPlyrGood",
        "  Raiders",
    ]
    assert panel.selected_team is teams[1]
    assert items(panel.forms[1].fields["teamUnitType1"]) == ["GondorArcherHorde"]


def test_teams_panel_adds_copies_and_deletes_within_groups(qapp):
    map = map_with_players()
    document = MapDocument(map)
    panel = connected(TeamsPanel(Host(document)), document)
    teams = map.teams.teams

    panel.select_team("PlyrEvil/Raiders")
    panel.copy_selected()
    assert [team_name(team) for team in teams] == ["teamPlyrGood", "Raiders", "Raiders2"]
    assert panel.selected_team is teams[2]
    panel.delete_selected()
    assert [team_name(team) for team in teams] == ["teamPlyrGood", "Raiders"]
    assert panel.selected_team is None

    assert panel.select_player("plyrgood")
    panel.add()
    assert (team_name(teams[2]), team_owner(teams[2])) == ("Team", "PlyrGood")
    assert panel.selected_team is teams[2]
    assert "  Team" in tree_labels(panel.tree)

    assert panel.select_player("")
    panel.add()
    assert team_owner(teams[3]) == ""
    assert tree_labels(panel.tree)[:2] == ["(neutral) (1)", "  Team2"]


def test_map_settings_panel_sets_time_and_restores_camera(qapp):
    map = Map()
    map.world_info = WorldInfo(version=1, properties={}, start_pos=0, end_pos=0)
    map.global_lighting = SimpleNamespace(time_of_the_day=TimeOfTheDay.Morning)
    document = MapDocument(map)
    panel = connected(MapSettingsPanel(Host(document)), document)

    panel.time_of_day.setCurrentIndex(3)
    assert map.global_lighting.time_of_the_day is TimeOfTheDay.Night
    panel.form.fields["cameraPitchAngle"].setValue(50.0)
    panel.restore_camera_defaults()
    assert map.world_info.properties["cameraPitchAngle"]["value"] == 37.5
    assert panel.form.fields["cameraPitchAngle"].value() == 37.5

    document.stack.undo()
    assert map.world_info.properties["cameraPitchAngle"]["value"] == 50.0


def test_multiplayer_positions_panel_edits_a_position(qapp):
    map = Map()
    position = MPPosition(
        version=1,
        is_human=True,
        is_computer=True,
        load_ai_script=True,
        team=0,
        side_restrictions=[],
        start_pos=0,
        end_pos=0,
    )
    map.mp_positions_list = MPPositionList(version=1, positions=[position], start_pos=0, end_pos=0)
    document = MapDocument(map)
    panel = connected(MultiplayerPositionsPanel(Host(document)), document)

    panel.computer.setChecked(False)
    panel.team.setValue(2)
    panel.restrictions.setText("Mordor Isengard")
    panel.restrictions.editingFinished.emit()

    assert (position.is_computer, position.team) == (False, 2)
    assert position.side_restrictions == ["Mordor", "Isengard"]
    document.stack.undo()
    assert position.side_restrictions == []
