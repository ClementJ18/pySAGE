"""Qt-level tests for the script search, import/export and moves, the Validation panel and Jump
To Game. Headless via the Qt 'offscreen' platform; marked `full` like the other desktop suites."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")  # headless; must precede the Qt import

from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.full

pytest.importorskip("PyQt6", reason="the [worldbuilder] extra (PyQt6) is not installed")

from PyQt6.QtWidgets import (  # noqa: E402
    QApplication,
    QDialog,
    QMessageBox,
    QTreeWidgetItemIterator,
)

from sage_map.assets.player_scripts import PlayerScriptsList, ScriptList  # noqa: E402
from sage_map.context import AssetPropertyType  # noqa: E402
from sage_map.map import Map  # noqa: E402
from sage_worldbuilder import MapDocument  # noqa: E402
from sage_worldbuilder.jump import JumpMatch, JumpOptions, JumpSeat  # noqa: E402
from sage_worldbuilder.launch_patch import LaunchPatchError  # noqa: E402
from sage_worldbuilder.scripting import new_group, new_item, new_script  # noqa: E402
from sage_worldbuilder.settings import Settings  # noqa: E402
from sage_worldbuilder.templates import TemplateKind, template_named  # noqa: E402
from sage_worldbuilder.ui.jump_dialog import JumpSettingsDialog  # noqa: E402
from sage_worldbuilder.ui.scripts import ScriptsPanel  # noqa: E402
from sage_worldbuilder.ui.window import MainWindow  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    yield QApplication.instance() or QApplication([])


def entry(kind: TemplateKind, name: str):
    found = template_named(kind, name)
    assert found is not None
    return found


def player(name: str):
    return SimpleNamespace(
        properties={
            "playerName": {
                "name": "playerName",
                "type": AssetPropertyType.AsciiString,
                "value": name,
            }
        }
    )


def scripted_map() -> Map:
    map = Map()
    grant = new_script("Grant")
    science = new_item(entry(TemplateKind.ACTION, "PLAYER_GRANT_SCIENCE"))
    science.arguments[0].string_value = "PlyrGood"
    science.arguments[1].string_value = "SCIENCE_Missing"
    grant.actions_if_true.append(science)
    group = new_group("Rewards")
    group.items.append(grant)
    idle = new_script("Idle")
    map.player_scripts_list = PlayerScriptsList(
        version=1,
        script_lists=[ScriptList(version=1, items=[group, idle], start_pos=0, end_pos=0)],
        start_pos=0,
        end_pos=0,
    )
    map.sides_list = SimpleNamespace(players=[player("PlyrGood")], teams=[])
    return map


class Host:
    def __init__(self, document: MapDocument) -> None:
        self.document = document
        self.game = None

    def execute(self, command) -> None:
        self.document.execute(command)


@pytest.fixture
def panel(qapp):
    document = MapDocument(scripted_map())
    panel = ScriptsPanel(Host(document))
    document.subscribe(lambda _change: panel.refresh())
    return panel


def visible_names(panel: ScriptsPanel) -> list[str]:
    names = []
    iterator = QTreeWidgetItemIterator(panel.tree)
    while (node := iterator.value()) is not None:
        data = node.data(0, 256)
        if not node.isHidden() and hasattr(data, "name"):
            names.append(data.name)
        iterator += 1
    return names


def test_search_filters_the_tree(panel):
    assert visible_names(panel) == ["Rewards", "Grant", "Idle"]
    panel.search.setText("science_missing")
    assert visible_names(panel) == ["Rewards", "Grant"]
    panel.whole_value.setChecked(True)
    assert visible_names(panel) == ["Rewards", "Grant"]
    panel.search.setText("science")
    assert visible_names(panel) == []


def test_sequential_fields_edit_the_script(panel):
    idle = panel.host.document.map.player_scripts_list.script_lists[0].items[1]
    assert panel.select_script("IDLE")
    panel.sequential_box.setChecked(True)
    panel.loop_count.setValue(3)
    panel.sequential_target.setText("PlyrGood/teamPatrol")
    panel.sequential_target.editingFinished.emit()

    assert (idle.actions_fire_sequentially, idle.loop_count) == (True, 3)
    assert idle.sequential_target_name == "PlyrGood/teamPatrol"


def test_move_into_and_out_of_groups(panel):
    document = panel.host.document
    top = document.map.player_scripts_list.script_lists[0].items
    group, idle = top

    panel.move_to(idle, group.items, 0)
    assert [item.name for item in group.items] == ["Idle", "Grant"] and top == [group]
    panel.move_to(group, group.items, 0)  # a group never moves into itself
    assert top == [group]
    panel.move_to(idle, top, 1)
    assert [item.name for item in top] == ["Rewards", "Idle"]
    document.stack.undo()
    document.stack.undo()
    assert top == [group, idle] and [item.name for item in group.items] == ["Grant"]


def test_export_then_import_adds_only_the_scripts_the_map_lacks(panel, tmp_path):
    document = panel.host.document
    top = document.map.player_scripts_list.script_lists[0].items
    path = str(tmp_path / "scripts.scb")
    panel.export_scripts(path)
    idle = top[1]
    assert panel.select_script("Idle")
    panel.delete_selected()
    assert [item.name for item in top] == ["Rewards"]

    skipped = panel.import_scripts(path)

    assert skipped == []
    assert [item.name for item in top] == ["Rewards", "Idle"]
    assert top[1] is not idle and [item.name for item in top[0].items] == ["Grant"]
    document.stack.undo()
    assert [item.name for item in top] == ["Rewards"]


@pytest.fixture
def window(qapp, tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    install = tmp_path / "install"
    install.mkdir()
    user = tmp_path / "user"
    monkeypatch.setattr("sage_worldbuilder.gamedata.user_data_dir", lambda game: user)
    monkeypatch.setattr(
        "sage_worldbuilder.ui.window.patch_for_launch", lambda game_dat, extra=(): False
    )
    window = MainWindow(Settings(install=str(install)), load_game_data=False)
    window.ask_save_changes = lambda document: "discard"
    yield window
    window.close()


def test_report_lists_missing_references_and_opens_the_script(window):
    window._set_document(MapDocument(scripted_map()))
    window.context.game = SimpleNamespace(
        tables={"sciences": {"SCIENCE_Known": object()}},
        strings={},
        lookup=lambda table, name: (None, name),
    )

    window.generate_report()

    findings = window.validation_panel.findings
    assert len(findings) == 1 and "SCIENCE_Missing" in findings[0].message
    window.validation_panel._open(window.validation_panel.tree.topLevelItem(0))
    assert window.scripts_panel.selected.name == "Grant"


def test_report_without_game_data_says_so(window):
    window._set_document(MapDocument(scripted_map()))
    window.generate_report()
    assert window.validation_panel.findings == []
    assert "not loaded" in window.validation_panel.summary.text()


def test_jump_to_game_launches_on_a_user_map(window, tmp_path):
    user = tmp_path / "user"
    path = user / "Maps" / "Fords" / "Fords.map"
    path.parent.mkdir(parents=True)
    MapDocument(Map()).save(path, compress=False)
    window._set_document(MapDocument.open(path))
    launched = []
    window.launch_game = lambda arguments, cwd: launched.append((arguments, cwd))

    window.jump_to_game()

    ((arguments, cwd),) = launched
    assert arguments[1:3] == ["-file", str(user / "Maps" / "Fords.map").lower()]
    assert cwd == tmp_path / "install"
    # The Script Debugger waits for the game it just started, to attach to it.
    assert window.script_debugger_panel.waiting


def test_jump_to_game_copies_a_map_without_a_file(window, tmp_path):
    window._set_document(MapDocument(Map(), read_only=True, name="Packed"))
    launched = []
    window.launch_game = lambda arguments, cwd: launched.append(arguments)

    window.jump_to_game()

    copy = tmp_path / "user" / "Maps" / "Packed" / "Packed.map"
    assert copy.is_file() and launched


def test_jump_to_game_refuses_a_game_that_cannot_be_patched(window, tmp_path, monkeypatch):
    def cannot_patch(game_dat, extra=()):
        raise LaunchPatchError(f"{game_dat} lacks it")

    monkeypatch.setattr("sage_worldbuilder.ui.window.patch_for_launch", cannot_patch)
    warnings = []
    monkeypatch.setattr(
        "sage_worldbuilder.ui.window.QMessageBox.warning",
        lambda parent, title, text: warnings.append(text),
    )
    window._set_document(MapDocument(Map(), read_only=True, name="Packed"))
    launched = []
    window.launch_game = lambda arguments, cwd: launched.append(arguments)

    window.jump_to_game()

    assert warnings == [f"{tmp_path / 'install' / 'game.dat'} lacks it"]
    assert not launched and not (tmp_path / "user" / "Maps" / "Packed").exists()


def test_closing_puts_back_the_game_dat_jump_to_game_patched(window, tmp_path, monkeypatch):
    monkeypatch.setattr(
        "sage_worldbuilder.ui.window.patch_for_launch", lambda game_dat, extra=(): True
    )
    restored = []
    monkeypatch.setattr(
        "sage_worldbuilder.ui.window.restore_after_launch",
        lambda game_dat: restored.append(game_dat),
    )
    window._set_document(MapDocument(Map(), read_only=True, name="Packed"))
    window.launch_game = lambda arguments, cwd: None

    window.jump_to_game()
    assert restored == []
    window.close()

    assert restored == [tmp_path / "install" / "game.dat"]


def test_closing_while_the_game_holds_game_dat_can_stay_open(window, tmp_path, monkeypatch):
    game_dat = tmp_path / "install" / "game.dat"
    window._patched_game_dats.add(game_dat)
    monkeypatch.setattr("sage_worldbuilder.ui.window.restore_after_launch", lambda path: "in use")
    monkeypatch.setattr("sage_worldbuilder.ui.window.restore_pending", lambda path: True)
    answers = [QMessageBox.StandardButton.Retry, QMessageBox.StandardButton.Cancel]
    asked = []

    def warning(*args):
        asked.append(args[2])
        return answers.pop(0)

    monkeypatch.setattr("sage_worldbuilder.ui.window.QMessageBox.warning", warning)

    assert window.restore_game_dats() is False
    assert len(asked) == 2 and "in use" in asked[0]
    assert window._patched_game_dats == {game_dat}

    answers[:] = [QMessageBox.StandardButton.Ignore]
    assert window.restore_game_dats() is True
    assert window._patched_game_dats == set()


def jump_game():
    """Factions and colours in registration order, the first faction not playable."""
    template = lambda playable: SimpleNamespace(PlayableSide=playable, _fields={})  # noqa: E731
    return SimpleNamespace(
        tables={
            "factions": {
                "FactionCivilian": template(False),
                "FactionMen": template(True),
                "FactionMordor": template(True),
            },
            "multiplayercolors": {"ColorBlue": object(), "ColorRed": object()},
        }
    )


def test_jump_to_game_passes_the_chosen_match(window):
    window.settings.jump_match = JumpMatch(
        enabled=True,
        seats=(
            JumpSeat("human", "FactionMordor", 1, "ColorRed", 0),
            JumpSeat("brutal", "FactionMen", 0, "ColorBlue", 1),
        ),
        seed=42,
    )
    window._set_document(MapDocument(Map(), read_only=True, name="Packed"))
    window.context.game = jump_game()
    launched = []
    window.launch_game = lambda arguments, cwd: launched.append(arguments)

    window.jump_to_game()

    ((arguments),) = launched
    value = arguments[arguments.index("-gameInfo") + 1]
    assert "SD=42;" in value
    assert "S=HPlayer,0,0,TT,1,2,1,0," in value
    assert ":CB,0,1,0,1," in value


def test_jump_to_game_without_a_match_passes_none(window):
    window._set_document(MapDocument(Map(), read_only=True, name="Packed"))
    window.context.game = jump_game()
    launched = []
    window.launch_game = lambda arguments, cwd: launched.append(arguments)

    window.jump_to_game()

    assert launched and "-gameInfo" not in launched[0]


def test_jump_to_game_refuses_a_match_it_cannot_resolve(window, tmp_path, monkeypatch):
    warnings = []
    monkeypatch.setattr(
        "sage_worldbuilder.ui.window.QMessageBox.warning",
        lambda parent, title, text: warnings.append(text),
    )
    window.settings.jump_match = JumpMatch(enabled=True, seats=(JumpSeat("human", "FactionMen"),))
    window._set_document(MapDocument(Map(), read_only=True, name="Packed"))
    launched = []
    window.launch_game = lambda arguments, cwd: launched.append(arguments)

    window.jump_to_game()

    assert len(warnings) == 1 and "not loaded" in warnings[0]
    assert not launched and not (tmp_path / "user" / "Maps" / "Packed").exists()


def test_the_settings_dialog_starts_from_the_default_seats(qapp):
    dialog = JumpSettingsDialog(JumpMatch(), jump_game(), 4)

    assert dialog.table.rowCount() == 2
    assert not dialog.table.isEnabled()
    human, ai = dialog.seats
    assert (human.kind, human.faction, human.colour) == ("human", "FactionMen", "ColorBlue")
    assert (ai.kind, ai.faction, ai.start_position) == ("easy", "FactionMordor", 1)


def test_the_settings_dialog_edits_the_match(qapp):
    dialog = JumpSettingsDialog(JumpMatch(), jump_game(), 4)
    dialog.enabled_box.setChecked(True)
    dialog.add_seat()
    kind = dialog.table.cellWidget(2, 0)
    kind.setCurrentIndex(kind.findData("brutal"))
    team = dialog.table.cellWidget(2, 4)
    team.setCurrentIndex(team.findData(2))
    dialog.resources.setValue(9000)
    dialog.random_seed_box.setChecked(False)
    dialog.seed.setValue(17)

    match = dialog.match

    assert match.enabled
    assert [seat.start_position for seat in match.seats] == [0, 1, 2]
    assert (match.seats[2].kind, match.seats[2].team) == ("brutal", 2)
    assert (match.starting_resources, match.seed) == (9000, 17)
    assert dialog.problem() is None


def test_the_settings_dialog_edits_the_launch(qapp):
    saved = JumpOptions(windowed=True, script_debug=False, extra_arguments="-quick")
    dialog = JumpSettingsDialog(JumpMatch(), jump_game(), 4, options=saved)
    assert dialog.options == saved

    dialog.width_spin.setValue(1920)
    dialog.height_spin.setValue(1080)
    dialog.script_debug_box.setChecked(True)
    dialog.extra_edit.setText(" -noshellmap ")
    assert dialog.options == JumpOptions(True, True, "-noshellmap", (1920, 1080))

    dialog.windowed_box.setChecked(False)
    assert not dialog.width_spin.isEnabled() and not dialog.options.windowed


def test_the_settings_dialog_saves_the_launch_to_the_settings(qapp, monkeypatch, window):
    def choose(dialog):
        dialog.width_spin.setValue(1600)
        dialog.height_spin.setValue(900)
        dialog.script_debug_box.setChecked(True)
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(JumpSettingsDialog, "exec", choose)

    window.edit_jump_settings()

    assert window.settings.jump_resolution == (1600, 900)
    assert window.settings.jump_script_debug
    assert window.settings.jump_options().resolution == (1600, 900)


def test_the_settings_dialog_explains_a_match_the_game_would_refuse(qapp):
    dialog = JumpSettingsDialog(JumpMatch(enabled=True), jump_game(), 4)
    start = dialog.table.cellWidget(1, 2)
    start.setCurrentIndex(start.findData(0))

    assert "Seats 1 and 2 both start at Position 1" in dialog.note.text()


def test_the_settings_dialog_keeps_names_the_game_does_not_have(qapp):
    saved = JumpMatch(enabled=True, seats=(JumpSeat("human", "FactionElves", 0, "ColorRed"),))
    dialog = JumpSettingsDialog(saved, None, 0)

    assert dialog.seats == saved.seats
    assert "not loaded" in dialog.note.text()
