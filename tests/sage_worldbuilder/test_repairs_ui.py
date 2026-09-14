"""Qt-level tests for Add Skirmish Players, the AI type, faction icon and regard lists in the
Player List, Fix Teams in the Validation panel, and Reset Active in the Scripts panel. Headless
via the Qt 'offscreen' platform; marked `full`."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")  # headless; must precede the Qt import

from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.full

pytest.importorskip("PyQt6", reason="the [worldbuilder] extra (PyQt6) is not installed")

from PyQt6.QtWidgets import QApplication, QStyle  # noqa: E402

from sage_ini.model.game import Game  # noqa: E402
from sage_ini.parser.diagnostics import Diagnostic  # noqa: E402
from sage_ini.parser.location import Span  # noqa: E402
from sage_map.assets.player_scripts import PlayerScriptsList, ScriptList  # noqa: E402
from sage_map.assets.sides_list import SidesList  # noqa: E402
from sage_map.assets.teams import Teams  # noqa: E402
from sage_map.context import AssetPropertyType  # noqa: E402
from sage_map.map import Map  # noqa: E402
from sage_worldbuilder import Change, ChangeKind, MapDocument  # noqa: E402
from sage_worldbuilder.commands import SetAttribute  # noqa: E402
from sage_worldbuilder.fix_teams import NO_PROBLEMS  # noqa: E402
from sage_worldbuilder.players import new_player, player_name  # noqa: E402
from sage_worldbuilder.scripting import new_script  # noqa: E402
from sage_worldbuilder.teams import new_team, team_name  # noqa: E402
from sage_worldbuilder.ui.players import DEFAULT_ICON, PlayersPanel  # noqa: E402
from sage_worldbuilder.ui.scripts import ScriptsPanel  # noqa: E402
from sage_worldbuilder.ui.validation import ValidationPanel  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    yield QApplication.instance() or QApplication([])


class Host:
    def __init__(self, document: MapDocument, game=None) -> None:
        self.document = document
        self.game = game

    def execute(self, command) -> None:
        self.document.execute(command)


def players_map() -> Map:
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


def game_with_factions() -> SimpleNamespace:
    men = SimpleNamespace(_fields={"Side": "Men"}, PlayableSide=True)
    observer = SimpleNamespace(_fields={"Side": "Observer"}, PlayableSide=False)
    return SimpleNamespace(
        tables={
            "factions": {"FactionMen": men, "FactionObserver": observer},
            "playeraitypes": {"MordorAI": 1, "MenSkirmishAI": 1},
        }
    )


def items(combo) -> list[str]:
    return [combo.itemText(index) for index in range(combo.count())]


def connected(panel, document: MapDocument):
    document.subscribe(lambda _change: panel.refresh())
    return panel


def test_players_panel_adds_skirmish_players_and_edits_optional_keys(qapp):
    map = players_map()
    document = MapDocument(map)
    panel = connected(PlayersPanel(Host(document, game_with_factions())), document)

    panel.add_skirmish()
    listed = [player_name(player) for player in map.sides_list.players]
    assert "SkirmishMen" in listed and "SkirmishObserver" not in listed
    assert panel.list.count() == len(listed)

    panel.list.setCurrentRow(1)
    good = map.sides_list.players[1].properties
    icon = panel.form.fields["playerFactionIcon"]
    assert items(icon) == [DEFAULT_ICON, "Men", "Fellowship"]
    icon.setCurrentText("Men")
    icon.lineEdit().editingFinished.emit()
    assert good["playerFactionIcon"]["value"] == "Men"
    icon.setCurrentText(DEFAULT_ICON)
    icon.lineEdit().editingFinished.emit()
    assert "playerFactionIcon" not in good
    assert items(panel.form.fields["playerAIType"]) == ["MenSkirmishAI", "MordorAI"]

    good["playerEnemies"]["value"] = "SkirmishMen"
    panel.refresh()
    assert "SkirmishMen: Enemy" in panel.regards_others.text()
    panel.list.setCurrentRow(listed.index("SkirmishMen"))
    assert "PlyrGood: Enemy" in panel.regarded_by.text()
    assert "PlyrGood: Neutral" in panel.regards_others.text()


def test_validation_panel_fixes_teams(qapp):
    map = players_map()
    document = MapDocument(map)
    panel = ValidationPanel(Host(document), lambda _name: None)

    panel.run_fix_teams()
    assert [team_name(team) for team in map.teams.teams] == ["teamPlyrGood"]
    assert (
        panel.tree.topLevelItem(0)
        .text(1)
        .startswith('Team "Raiders" was on non-existent player "PlyrEvil".')
    )

    panel.run_fix_teams()
    assert panel.summary.text() == NO_PROBLEMS
    assert panel.tree.topLevelItem(0).text(1) == NO_PROBLEMS


def test_scripts_panel_resets_active_flags(qapp):
    map = players_map()
    script = new_script("Intro")
    map.player_scripts_list.script_lists[1].items.append(script)
    document = MapDocument(map)
    panel = connected(ScriptsPanel(Host(document)), document)
    button = panel.tree_buttons["Reset Active"]
    assert not button.isEnabled()

    document.execute(SetAttribute(script, "is_active", False, Change(ChangeKind.SCRIPTS)))
    assert button.isEnabled()
    panel.reset_active_flags()
    assert script.is_active
    assert not button.isEnabled()


def test_scripts_panel_marks_scripts_with_live_warnings(qapp):
    map = players_map()
    map.player_scripts_list.script_lists[1].items += [new_script("Intro"), new_script("Outro")]
    document = MapDocument(map)
    host = Host(document)
    panel = connected(ScriptsPanel(host), document)
    message = "Unknown science SCIENCE_Missing"
    panel.lint = lambda _map, _game: {"intro": [message]}

    panel.update_warnings()
    assert panel.warnings == {}  # nothing to check against until the game is loaded

    host.game = object()
    panel.update_warnings()
    player = panel.tree.topLevelItem(1)
    intro, outro = player.child(0), player.child(1)
    warning = panel.style().standardIcon(QStyle.StandardPixmap.SP_MessageBoxWarning)
    assert intro.toolTip(0) == message
    assert intro.icon(0).pixmap(16).toImage() == warning.pixmap(16).toImage()
    assert outro.toolTip(0) == ""

    panel.refresh()  # a rebuild keeps the marks
    assert panel.tree.topLevelItem(1).child(0).toolTip(0) == message


def test_validation_panel_adds_overlay_checks_and_clears_execute_actions(qapp):
    map = players_map()
    raiders = map.teams.teams[1]
    raiders.properties["teamExecutesActionsOnCreate"] = {
        "name": "teamExecutesActionsOnCreate",
        "type": AssetPropertyType.Boolean,
        "value": True,
    }
    document = MapDocument(map)
    opened: list[str] = []

    def overlay(checked, path):
        assert checked is map
        return [
            Diagnostic(
                "overlay-rule",
                "Intro needs a camera",
                Span(str(path), 1, 1),
                extra={"script": "Intro"},
            )
        ]

    panel = ValidationPanel(Host(document, Game()), opened.append, extra_checks=overlay)
    panel.run()
    rows = [panel.tree.topLevelItem(index) for index in range(panel.tree.topLevelItemCount())]
    found = next(row for row in rows if row.text(1) == "Intro needs a camera")
    panel._open(found)
    assert opened == ["Intro"]

    panel.run_clear_execute_actions()
    assert raiders.properties["teamExecutesActionsOnCreate"]["value"] is False
    assert panel.tree.topLevelItem(0).text(1) == (
        'Team "Raiders" no longer executes its associated actions.'
    )
