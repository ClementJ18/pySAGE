"""Qt-level tests for the Scripts panel and the condition/action dialog. Headless via the Qt
'offscreen' platform; marked `full` like the other desktop suites."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")  # headless; must precede the Qt import

import pytest

pytestmark = pytest.mark.full

pytest.importorskip("PyQt6", reason="the [worldbuilder] extra (PyQt6) is not installed")

from PyQt6.QtCore import QPoint, QPointF, QRect, Qt  # noqa: E402
from PyQt6.QtGui import QColor, QPalette  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import (  # noqa: E402
    QApplication,
    QComboBox,
    QDialog,
    QMenu,
    QStyle,
    QStyleOptionViewItem,
)

from sage_map.assets.library_map_lists import LibraryMapLists  # noqa: E402
from sage_map.assets.library_map_lists import LibraryMaps as LibraryMapValues  # noqa: E402
from sage_map.assets.object_list import ObjectsList  # noqa: E402
from sage_map.assets.player_scripts import (  # noqa: E402
    PlayerScriptsList,
    Script,
    ScriptArgumentType,
    ScriptList,
)
from sage_map.map import Map  # noqa: E402
from sage_worldbuilder import MapDocument  # noqa: E402
from sage_worldbuilder.objects import new_object  # noqa: E402
from sage_worldbuilder.players import library_map_path  # noqa: E402
from sage_worldbuilder.script_targets import argument_target  # noqa: E402
from sage_worldbuilder.scripting import new_group, new_item, new_script  # noqa: E402
from sage_worldbuilder.templates import TemplateKind, template_named  # noqa: E402
from sage_worldbuilder.ui.script_items import ScriptItemDialog  # noqa: E402
from sage_worldbuilder.ui.scripts import ScriptsPanel  # noqa: E402
from sage_worldbuilder.ui.sentences import HTML_ROLE, link_color  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    yield QApplication.instance() or QApplication([])


class Host:
    def __init__(self, document: MapDocument) -> None:
        self.document = document
        self.game = None
        self.panel: ScriptsPanel | None = None

    def execute(self, command) -> None:
        self.document.execute(command)


def entry(kind: TemplateKind, name: str):
    found = template_named(kind, name)
    assert found is not None
    return found


def scripted_document() -> MapDocument:
    map = Map()
    script = new_script("Intro")
    script.or_conditions[0].conditions.append(
        new_item(entry(TemplateKind.CONDITION, "CONDITION_TRUE"))
    )
    script.actions_if_true.append(new_item(entry(TemplateKind.ACTION, "NO_OP")))
    group = new_group("Act One")
    group.items.append(script)
    map.player_scripts_list = PlayerScriptsList(
        version=1,
        script_lists=[
            ScriptList(version=1, items=[group], start_pos=0, end_pos=0),
            ScriptList(version=1, items=[], start_pos=0, end_pos=0),
        ],
        start_pos=0,
        end_pos=0,
    )
    return MapDocument(map)


@pytest.fixture
def panel(qapp):
    document = scripted_document()
    host = Host(document)
    panel = ScriptsPanel(host)
    host.panel = panel
    document.subscribe(lambda _change: panel.refresh())
    document.stack.subscribe(panel.refresh)
    return panel


def tree_labels(panel: ScriptsPanel) -> list[str]:
    labels = []

    def walk(node, depth):
        labels.append("  " * depth + node.text(0))
        for index in range(node.childCount()):
            walk(node.child(index), depth + 1)

    for index in range(panel.tree.topLevelItemCount()):
        walk(panel.tree.topLevelItem(index), 0)
    return labels


def select(panel: ScriptsPanel, target) -> None:
    def walk(node):
        if node.data(0, 256) is target:
            return node
        for index in range(node.childCount()):
            if (found := walk(node.child(index))) is not None:
                return found
        return None

    for index in range(panel.tree.topLevelItemCount()):
        if (found := walk(panel.tree.topLevelItem(index))) is not None:
            panel.tree.setCurrentItem(found)
            return
    raise AssertionError("not in the tree")


def test_tree_shows_players_groups_and_scripts(panel):
    assert tree_labels(panel) == ["Player 1", "  Act One", "    Intro", "Player 2"]
    group = panel.tree.topLevelItem(0).child(0)
    style = panel.style()
    folder = style.standardIcon(QStyle.StandardPixmap.SP_DirIcon).pixmap(16).toImage()
    file = style.standardIcon(QStyle.StandardPixmap.SP_FileIcon).pixmap(16).toImage()
    assert group.icon(0).pixmap(16).toImage() == folder
    assert group.child(0).icon(0).pixmap(16).toImage() == file
    assert folder != file


def test_script_editor_lists_sentences(panel):
    script = panel.host.document.map.player_scripts_list.script_lists[0].items[0].items[0]
    select(panel, script)

    assert panel.pages.currentIndex() == 2
    assert panel.script_name.text() == "Intro"
    rows = [panel.conditions.list.item(i).text() for i in range(panel.conditions.list.count())]
    assert rows[0] == "IF" and rows[1].strip().startswith("True")
    assert panel.actions_true.list.item(0).text().startswith("Null operation")


def test_new_script_goes_after_the_selection_and_undoes(panel):
    document = panel.host.document
    group = document.map.player_scripts_list.script_lists[0].items[0]
    select(panel, group.items[0])

    panel.new_script()

    assert [item.name for item in group.items] == ["Intro", "New Script"]
    assert panel.selected is group.items[1]
    document.stack.undo()
    assert [item.name for item in group.items] == ["Intro"]


def test_rename_flags_copy_move_delete(panel):
    document = panel.host.document
    group = document.map.player_scripts_list.script_lists[0].items[0]
    script = group.items[0]
    select(panel, script)

    panel.script_name.setText("Opening")
    panel.script_name.editingFinished.emit()
    panel.script_flags["is_subroutine"].setChecked(True)
    assert (script.name, script.is_subroutine) == ("Opening", True)

    panel.copy_selected()
    assert [item.name for item in group.items] == ["Opening", "Opening (2)"]
    panel.move_selected(-1)
    assert [item.name for item in group.items] == ["Opening (2)", "Opening"]
    panel.delete_selected()
    assert [item.name for item in group.items] == ["Opening"]

    while document.stack.undo():
        pass
    assert [item.name for item in group.items] == ["Intro"] and not script.is_subroutine


class StubDialog:
    """Stands in for the modal dialog: accepts with a prepared item."""

    def __init__(self, item):
        self.item = item
        self.focus_argument = None

    def __call__(self, kind, item, symbols, game, parent, focus_argument=None, **passed):
        self.focus_argument = focus_argument
        self.passed = passed
        return self

    def exec(self):
        return QDialog.DialogCode.Accepted


def test_new_and_edited_items_go_through_commands(panel):
    document = panel.host.document
    script: Script = document.map.player_scripts_list.script_lists[0].items[0].items[0]
    select(panel, script)

    move = new_item(entry(TemplateKind.ACTION, "MOVE_NAMED_UNIT_TO"))
    move.arguments[0].string_value = "Gandalf"
    panel.item_dialog = StubDialog(move)
    panel.actions_true.list.setCurrentRow(0)
    panel.new_action("actions_if_true")
    assert [a.internal_name[2] for a in script.actions_if_true] == ["NO_OP", "MOVE_NAMED_UNIT_TO"]

    panel.actions_true.list.setCurrentRow(1)
    panel.toggle_item(panel.actions_true)
    assert script.actions_if_true[1].is_enabled is False
    assert panel.actions_true.list.item(1).text().endswith("[disabled]")

    alive = new_item(entry(TemplateKind.CONDITION, "NAMED_NOT_DESTROYED"))
    panel.item_dialog = StubDialog(alive)
    panel.new_or_clause()
    assert len(script.or_conditions) == 2
    panel.conditions.list.setCurrentRow(2)  # the new OR header
    panel.new_condition()
    assert script.or_conditions[1].conditions == [alive]

    panel.conditions.list.setCurrentRow(1)
    panel.edit_item(panel.conditions)
    assert script.or_conditions[0].conditions[0] is alive

    while document.stack.undo():
        pass
    assert [a.internal_name[2] for a in script.actions_if_true] == ["NO_OP"]
    assert len(script.or_conditions) == 1


def test_arguments_are_links_that_open_the_dialog_on_them(panel):
    document = panel.host.document
    script: Script = document.map.player_scripts_list.script_lists[0].items[0].items[0]
    select(panel, script)
    move = new_item(entry(TemplateKind.ACTION, "MOVE_NAMED_UNIT_TO"))
    move.arguments[0].string_value = "Gandalf"
    move.arguments[1].string_value = "Gate <3>"
    panel.item_dialog = StubDialog(move)
    panel.actions_true.list.setCurrentRow(0)
    panel.new_action("actions_if_true")

    markup = panel.actions_true.list.item(1).data(HTML_ROLE)
    assert '<a href="argument:0">Gandalf</a>' in markup
    assert '<a href="argument:1">Gate &lt;3&gt;</a>' in markup
    assert panel.actions_true.list.item(1).text() == "Move Gandalf to Gate <3>."

    delegate = panel.actions_true.delegate
    option = QStyleOptionViewItem()
    option.rect = QRect(0, 0, 800, 30)
    option.font = panel.font()
    option.palette = panel.palette()
    index = panel.actions_true.list.model().index(1, 0)
    anchors = {delegate.anchor_at(option, index, QPointF(x, 10)) for x in range(0, 500, 2)}
    assert {"argument:0", "argument:1"} <= anchors

    stub = StubDialog(move)
    panel.item_dialog = stub
    clicked = []
    delegate.argument_clicked.connect(lambda row, argument: clicked.append((row, argument)))
    panel.edit_argument(panel.actions_true, 1, 1)
    assert stub.focus_argument == 1
    assert panel.actions_true.list.currentRow() == 1

    condition_markup = panel.conditions.list.item(0).data(HTML_ROLE)
    assert condition_markup == "<b>IF</b>"


def test_item_dialog_preview_links_focus_their_fields(qapp):
    dialog = ScriptItemDialog(TemplateKind.ACTION, None, {"units": ["Gandalf"]}, None)
    dialog.select_template(entry(TemplateKind.ACTION, "MOVE_NAMED_UNIT_TO"))
    assert 'href="argument:1"' in dialog.preview.text()

    dialog.preview.linkActivated.emit("argument:1")
    assert dialog.focused_argument == 1
    dialog.preview.linkActivated.emit("https://example.com")
    assert dialog.focused_argument == 1

    item = new_item(entry(TemplateKind.ACTION, "MOVE_NAMED_UNIT_TO"))
    opened = ScriptItemDialog(TemplateKind.ACTION, item, {}, None, focus_argument=0)
    qapp.processEvents()
    assert opened.focused_argument == 0
    assert opened.argument_editor(0) is not None and opened.argument_editor(5) is None


def test_item_dialog_builds_an_item_from_a_template(qapp):
    symbols = {"units": ["Gandalf", "Frodo"], "waypoints": ["Gate"]}
    dialog = ScriptItemDialog(TemplateKind.ACTION, None, symbols, None)
    assert dialog.ok_button is not None and not dialog.ok_button.isEnabled()

    dialog.select_template(entry(TemplateKind.ACTION, "MOVE_NAMED_UNIT_TO"))
    unit_box = dialog.form.itemAt(0, dialog.form.ItemRole.FieldRole).widget()
    assert isinstance(unit_box, QComboBox)
    assert [unit_box.itemText(i) for i in range(unit_box.count())] == ["Gandalf", "Frodo"]
    unit_box.setCurrentText("Frodo")
    dialog.accept()

    assert dialog.item is not None
    assert dialog.item.arguments[0].string_value == "Frodo"
    assert dialog.preview.text().startswith('Move <a href="argument:0">Frodo</a> to')


def test_item_dialog_edits_a_copy_and_keeps_fitting_arguments(qapp):
    original = new_item(entry(TemplateKind.CONDITION, "COUNTER"))
    original.arguments[0].string_value = "Waves"
    dialog = ScriptItemDialog(TemplateKind.CONDITION, original, {}, None)

    comparison = dialog.form.itemAt(1, dialog.form.ItemRole.FieldRole).widget()
    assert isinstance(comparison, QComboBox) and comparison.itemText(0) == "Less Than"
    comparison.setCurrentIndex(4)
    dialog.inverted_box.setChecked(True)
    dialog.accept()

    assert original.arguments[1].int_value == 0  # the original is untouched
    edited = dialog.item
    assert edited is not None and edited.arguments[1].int_value == 4
    assert edited.arguments[1].type is ScriptArgumentType.COMPARISON
    assert edited.is_inverted is True

    dialog.search.setText("threat level")
    leaves = [leaf for leaf in dialog._leaves.values() if not leaf.isHidden()]
    names = {leaf.data(0, 256).internal_name for leaf in leaves}
    assert {"UNIT_THREAT_LEVEL", "TEAM_THREAT_LEVEL"} <= names
    assert all("threat level" in leaf.data(0, 256).ui_name.casefold() for leaf in leaves)


def test_link_rows_paint_and_a_real_click_opens_the_argument(panel, qapp):
    document = panel.host.document
    script: Script = document.map.player_scripts_list.script_lists[0].items[0].items[0]
    select(panel, script)
    move = new_item(entry(TemplateKind.ACTION, "MOVE_NAMED_UNIT_TO"))
    move.arguments[0].string_value = "Gandalf"
    move.arguments[1].string_value = "Gate"
    panel.item_dialog = StubDialog(move)
    panel.actions_true.list.setCurrentRow(0)
    panel.new_action("actions_if_true")

    view = panel.actions_true.list
    view.resize(700, 200)
    assert not view.grab().isNull()  # draws every row through the delegate

    rect = view.visualItemRect(view.item(1))
    option = QStyleOptionViewItem()
    option.rect = rect
    option.font = view.font()
    option.palette = view.palette()
    index = view.model().index(1, 0)
    delegate = panel.actions_true.delegate
    y = rect.height() // 2
    x = next(
        x
        for x in range(rect.width())
        if delegate.anchor_at(option, index, QPointF(x, y)) == "argument:1"
    )

    stub = StubDialog(move)
    panel.item_dialog = stub
    QTest.mouseClick(
        view.viewport(), Qt.MouseButton.LeftButton, pos=QPoint(rect.left() + x, rect.top() + y)
    )
    assert stub.focus_argument == 1


def test_links_lighten_on_a_dark_background():
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Link, QColor("#0000ff"))
    on_light = link_color(palette, QColor("#ffffff"))
    on_dark = link_color(palette, QColor("#1e1e1e"))
    assert on_light.name() == "#0000ff"
    assert on_dark.lightness() > on_light.lightness()
    assert on_dark.hue() == on_light.hue()
    already_light = QPalette()
    already_light.setColor(QPalette.ColorRole.Link, QColor("#8ab4ff"))
    assert link_color(already_light, QColor("#1e1e1e")).name() == "#8ab4ff"


def library_document():
    """A map whose one player draws scripts from two library maps, one of which the game does not
    have, and a loader that reads them."""
    map = Map()
    map.player_scripts_list = PlayerScriptsList(
        version=1,
        script_lists=[ScriptList(version=1, items=[new_group("Own")], start_pos=0, end_pos=0)],
        start_pos=0,
        end_pos=0,
    )
    map.library_map_lists = LibraryMapLists(
        version=1,
        lists=[
            LibraryMapValues(
                version=1,
                values=[library_map_path("Core"), library_map_path("Gone")],
                start_pos=0,
                end_pos=0,
            )
        ],
        start_pos=0,
        end_pos=0,
    )
    group = new_group("Build")
    group.items.append(new_script("Farm"))
    core = Map()
    core.player_scripts_list = PlayerScriptsList(
        version=1,
        script_lists=[
            ScriptList(version=1, items=[], start_pos=0, end_pos=0),
            ScriptList(version=1, items=[group], start_pos=0, end_pos=0),
        ],
        start_pos=0,
        end_pos=0,
    )

    def load(path: str):
        return core if path.casefold() == library_map_path("Core").casefold() else None

    return MapDocument(map), load


def test_imported_library_scripts_are_shown_read_only(qapp):
    document, load = library_document()
    host = Host(document)
    panel = ScriptsPanel(host, load)
    host.panel = panel
    panel.refresh()

    assert tree_labels(panel) == [
        "Player 1",
        "  Own",
        "  Build  (imported)",
        "    Farm  (imported)",
        "  Gone  (library map not found)",
    ]
    imported = panel.tree.topLevelItem(0).child(1)
    assert "Core" in imported.toolTip(0)

    select(panel, imported.data(0, 256))
    assert panel.locked()
    assert not panel.group_name.isEnabled()
    for text in ("Copy", "Delete", "Up", "Down"):
        assert not panel.tree_buttons[text].isEnabled()

    # Nothing an imported row is asked to change reaches the library map.
    panel.group_name.setText("Renamed")
    panel._set_selected("name", "Renamed", "Rename Group")
    panel.delete_selected()
    assert document.map.player_scripts_list.script_lists[0].items[0].name == "Own"
    assert imported.data(0, 256).name == "Build"
    assert not document.stack.can_undo


def test_a_new_script_beside_an_imported_one_goes_to_the_player(qapp):
    document, load = library_document()
    host = Host(document)
    panel = ScriptsPanel(host, load)
    host.panel = panel
    panel.refresh()
    select(panel, panel.tree.topLevelItem(0).child(1).data(0, 256))

    panel.new_script()

    items = document.map.player_scripts_list.script_lists[0].items
    assert [item.name for item in items] == ["Own", "New Script"]


def navigable_document() -> MapDocument:
    """A map whose one action names an object that is on it, so the argument can be gone to."""
    document = scripted_document()
    map = document.map
    map.objects_list = ObjectsList(version=3, object_list=[], start_pos=0, end_pos=0)
    gandalf = new_object(map, "GondorGandalf", (30.0, 40.0, 0.0), 0.0, "/team")
    gandalf.properties["objectName"] = {
        "name": "objectName",
        "type": gandalf.properties["originalOwner"]["type"],
        "value": "Gandalf",
    }
    map.objects_list.object_list.append(gandalf)
    script = map.player_scripts_list.script_lists[0].items[0].items[0]
    action = new_item(entry(TemplateKind.ACTION, "NAMED_SET_HELD"))
    action.arguments[0].string_value = "Gandalf"
    script.actions_if_true[:] = [action]
    return document


def navigable_panel(load_library=None):
    document = navigable_document()
    host = Host(document)
    gone_to = []
    panel = ScriptsPanel(host, load_library, gone_to.append)
    host.panel = panel
    panel.refresh()
    return panel, gone_to


def test_item_dialog_go_to_button_follows_the_value(qapp):
    """Only the arguments naming something in the map get a button, and it is live: it enables
    as the value comes to name something the map has, and disables again when it does not."""
    document = navigable_document()
    map = document.map
    item = new_item(entry(TemplateKind.ACTION, "MOVE_NAMED_UNIT_TO"))
    item.arguments[0].string_value = "Gandalf"
    gone_to = []
    dialog = ScriptItemDialog(
        TemplateKind.ACTION,
        item,
        {"units": ["Gandalf"]},
        None,
        find_target=lambda argument: argument_target(argument, map),
        go_to=gone_to.append,
    )

    unit_button = dialog.go_to_button(0)
    assert unit_button is not None and unit_button.isEnabled()
    assert unit_button.toolTip() == "Go to object 'Gandalf'"
    # The field still edits the argument: the row around it is not what focusing hands back.
    assert isinstance(dialog.argument_editor(0), QComboBox)
    # The third parameter is a coordinate, which names nothing to go to.
    assert dialog.go_to_button(2) is None

    unit_button.click()
    assert [target.name for target in gone_to] == ["Gandalf"]

    dialog.argument_editor(0).setCurrentText("Saruman")
    assert not unit_button.isEnabled() and "Nothing in this map" in unit_button.toolTip()
    unit_button.click()
    assert len(gone_to) == 1


def test_item_dialog_has_no_go_to_buttons_without_a_window(qapp):
    item = new_item(entry(TemplateKind.ACTION, "MOVE_NAMED_UNIT_TO"))
    dialog = ScriptItemDialog(TemplateKind.ACTION, item, {}, None)
    assert dialog.go_to_button(0) is None
    assert isinstance(dialog.argument_editor(0), QComboBox)


def test_panel_hands_the_dialog_the_navigator(qapp):
    panel, gone_to = navigable_panel()
    stub = StubDialog(None)
    panel.item_dialog = stub
    select(panel, panel.host.document.map.player_scripts_list.script_lists[0].items[0].items[0])
    panel.actions_true.list.setCurrentRow(0)

    panel.edit_item(panel.actions_true)

    assert stub.passed["go_to"] is not None
    argument = panel.host.document.map.objects_list.object_list[0]
    found = stub.passed["find_target"](panel.selected.actions_if_true[0].arguments[0])
    assert found is not None and found.sources == (argument,)


def test_right_click_a_row_offers_what_its_arguments_name(qapp, monkeypatch):
    panel, gone_to = navigable_panel()
    select(panel, panel.host.document.map.player_scripts_list.script_lists[0].items[0].items[0])
    listed: list[str] = []

    def choose(menu, _at):
        listed[:] = [action.text() for action in menu.actions() if action.text()]
        return next(action for action in menu.actions() if action.text().startswith("Go to"))

    monkeypatch.setattr(QMenu, "exec", choose)
    panel.open_item_menu(panel.actions_true, 0, QPoint())

    assert listed == ["Edit…", "Go to object 'Gandalf'"]
    assert [target.name for target in gone_to] == ["Gandalf"]

    # An IF/OR header stands for no item, so only the (disabled) Edit entry is offered.
    listed.clear()
    monkeypatch.setattr(QMenu, "exec", lambda menu, _at: choose_nothing(menu, listed))
    panel.open_item_menu(panel.conditions, 0, QPoint())
    assert listed == ["Edit…"]


def choose_nothing(menu, listed: list[str]):
    listed[:] = [action.text() for action in menu.actions() if action.text()]
    return None


def test_override_button_gives_the_map_its_own_copy(qapp):
    document, load = library_document()
    host = Host(document)
    panel = ScriptsPanel(host, load)
    host.panel = panel
    panel.refresh()
    imported = panel.tree.topLevelItem(0).child(1).child(0)
    assert imported.text(0) == "Farm  (imported)"
    select(panel, imported.data(0, 256))
    assert panel.tree_buttons["Override"].isEnabled()

    panel.override_selected()
    panel.refresh()  # the window refreshes the panel on the document's change signal

    assert tree_labels(panel) == [
        "Player 1",
        "  Own",
        "  Build",
        "    Farm",
        "  Build  (overridden)",
        "    Farm  (overridden)",
        "  Gone  (library map not found)",
    ]
    items = document.map.player_scripts_list.script_lists[0].items
    assert [item.name for item in items] == ["Own", "Build"]
    assert [item.name for item in items[1].items] == ["Farm"]
    # The copy is what is selected, and it is the map's, so it can be edited.
    assert panel.selected is items[1].items[0]
    assert not panel.locked()
    assert panel.script_name.isEnabled()
    assert not panel.tree_buttons["Override"].isEnabled()

    document.stack.undo()
    panel.refresh()
    assert document.map.player_scripts_list.script_lists[0].items[0].name == "Own"
    assert len(document.map.player_scripts_list.script_lists[0].items) == 1
