"""Qt-level tests for the Script Debugger panel and the live state it lends the Scripts panel.
Headless via the Qt 'offscreen' platform; marked `full` like the other desktop suites. The game
is a fake session, so nothing here needs a running game or Windows."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")  # headless; must precede the Qt import

from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.full

pytest.importorskip("PyQt6", reason="the [worldbuilder] extra (PyQt6) is not installed")

from PyQt6.QtCore import QPoint  # noqa: E402
from PyQt6.QtWidgets import (  # noqa: E402
    QApplication,
    QInputDialog,
    QMenu,
    QTreeWidgetItemIterator,
)

from sage_live.backends.script_trace import BreakpointHit, EventKind, TraceEvent  # noqa: E402
from sage_live.backends.scripts import (  # noqa: E402
    LiveScript,
    ScriptTree,
    ScriptVariable,
    SideScripts,
)
from sage_map.assets.player_scripts import PlayerScriptsList, ScriptList  # noqa: E402
from sage_map.context import AssetPropertyType  # noqa: E402
from sage_map.map import Map  # noqa: E402
from sage_worldbuilder import MapDocument  # noqa: E402
from sage_worldbuilder.live import LiveAccessDenied, LiveAttachError, LiveSnapshot  # noqa: E402
from sage_worldbuilder.scripting import new_script  # noqa: E402
from sage_worldbuilder.ui.script_debugger import (  # noqa: E402
    ScriptDebuggerPanel,
    achieved_speed,
)
from sage_worldbuilder.ui.scripts import ScriptsPanel  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    yield QApplication.instance() or QApplication([])


ADDRESSES = {"Intro": 0x1000, "Idle": 0x2000}


def live_script(name: str, active: bool, one_shot: bool = False) -> LiveScript:
    return LiveScript(
        has_true_actions=name == "Intro",
        name_address=ADDRESSES[name] + 0x800,
        name=name,
        address=ADDRESSES[name],
        active=active,
        authored_active=True,
        one_shot=one_shot,
        subroutine=False,
        easy=True,
        normal=True,
        hard=True,
        delay_seconds=0,
        sequential=False,
        next_frame=0,
    )


class FakeSession:
    pid = 4242

    def __init__(self, map_path: str) -> None:
        self.map_path = map_path
        self.timer = 50
        self.running = True
        self.closed = False
        self.recording = False
        self.refuse_trace = False
        self.events: list[TraceEvent] = []
        self.waves = 3
        self.paused = False
        self.frame = 300
        self.table: dict[int, int] = {}
        self.hit: BreakpointHit | None = None
        self.steps: list[int] = []
        self.calls: list[tuple] = []
        self.speed = 1

    def set_recording(self, on: bool) -> list[str]:
        if on and self.refuse_trace:
            raise LiveAttachError("The game could not be hooked: a network game")
        self.recording = on
        return []

    def set_breakpoints(self, table: dict[int, int]) -> list[str]:
        self.table = dict(table)
        return []

    def pause(self) -> None:
        self.paused = True

    def resume(self) -> None:
        self.paused = False

    def step(self, frames: int) -> None:
        self.steps.append(frames)

    def set_speed(self, multiplier: int) -> None:
        self._refuse()
        self.speed = multiplier

    def _refuse(self) -> None:
        if self.refuse_trace:
            raise LiveAttachError("This is a network game; changing its scripts is refused.")

    def set_script_active(self, script: LiveScript, active: bool) -> None:
        self._refuse()
        self.calls.append(("active", script.name, active))

    def rearm(self, script: LiveScript) -> None:
        self.calls.append(("rearm", script.name))

    def set_group_active(self, group, active: bool) -> None:
        self.calls.append(("group", group.name, active))

    def set_variable(self, variable: ScriptVariable, value: int) -> None:
        self._refuse()
        self.calls.append(("variable", variable.key, value))

    def evaluate(self, script: LiveScript, side: int) -> bool:
        self.calls.append(("evaluate", script.name, side))
        return True

    def run_actions(self, script: LiveScript, side: int, false_actions: bool = False) -> bool:
        self.calls.append(("run", script.name, side, false_actions))
        return True

    def unhook(self) -> list[str]:
        self.recording = False
        self.table = {}
        self.paused = False
        self.speed = 1
        return []

    def poll(self) -> LiveSnapshot | None:
        if not self.running:
            return None
        self.timer -= 5
        side = SideScripts(
            index=0,
            scripts=(live_script("Intro", False, one_shot=True), live_script("Idle", False)),
            groups=(),
        )
        return LiveSnapshot(
            map_path=self.map_path,
            frame=self.frame,
            logic_rate=5,
            tree=ScriptTree(sides=(side,), difficulty=1),
            variables=(
                ScriptVariable("counter", "", "Waves", self.waves),
                ScriptVariable("timer", "Player_1", "Attack", self.timer, seconds=True),
                ScriptVariable("flag", "", "Started", 1),
            ),
            players={0: "Player_1"},
            trace=tuple(self._take()),
            paused=self.paused,
            hit=self.hit,
            speed=self.speed,
        )

    def _take(self) -> list[TraceEvent]:
        events, self.events = self.events, []
        return events

    def alive(self) -> bool:
        return self.running

    def close(self) -> list[str]:
        self.closed = True
        return self.unhook()


def scripted_document(tmp_path) -> MapDocument:
    map = Map()
    map.player_scripts_list = PlayerScriptsList(
        version=1,
        script_lists=[
            ScriptList(
                version=1,
                items=[new_script("Intro"), new_script("Idle"), new_script("Editor Only")],
                start_pos=0,
                end_pos=0,
            )
        ],
        start_pos=0,
        end_pos=0,
    )
    name = {"name": "playerName", "type": AssetPropertyType.AsciiString, "value": "Player_1"}
    map.sides_list = SimpleNamespace(players=[SimpleNamespace(properties={"playerName": name})])
    return MapDocument(map, path=tmp_path / "My Map" / "My Map.map")


class Host:
    def __init__(self, document: MapDocument) -> None:
        self.document = document
        self.game = None

    def execute(self, command) -> None:
        self.document.execute(command)


@pytest.fixture
def panels(qapp, tmp_path):
    host = Host(scripted_document(tmp_path))
    scripts = ScriptsPanel(host)
    session = FakeSession("c:\\users\\me\\maps\\my map\\my map.map")
    debugger = ScriptDebuggerPanel(host, attach=lambda: session)
    debugger.live_changed.connect(scripts.set_live)
    yield scripts, debugger, session
    debugger.shutdown()


def labels(panel: ScriptsPanel) -> dict[str, str]:
    found = {}
    iterator = QTreeWidgetItemIterator(panel.tree)
    while (node := iterator.value()) is not None:
        item = node.data(0, 256)
        if hasattr(item, "name"):
            found[item.name] = node.text(0)
        iterator += 1
    return found


def values(debugger: ScriptDebuggerPanel) -> list[tuple[str, ...]]:
    table = debugger.table
    return [
        tuple(table.item(row, column).text() for column in range(table.columnCount()))
        for row in range(table.rowCount())
    ]


def test_attaching_to_the_open_map_marks_the_scripts(panels):
    scripts, debugger, _ = panels
    assert debugger.attach()
    assert "Frame 300" in debugger.status.text()
    shown = labels(scripts)
    assert shown["Intro"] == "Intro  [fired]"
    assert shown["Idle"] == "Idle  [inactive in game]"
    assert shown["Editor Only"] == "Editor Only"
    scripts.select_script("Editor Only")
    assert "not loaded" in scripts.script_live.text()


def test_the_variables_table_reads_like_a_mapper_would(panels):
    _, debugger, _ = panels
    debugger.attach()
    assert values(debugger) == [
        ("counter", "", "Waves", "3"),
        ("timer", "Player_1", "Attack", "9.0 s (45 frames)"),
        ("flag", "", "Started", "true"),
    ]
    debugger.poll_now()
    assert debugger.table.item(1, 3).text() == "8.0 s (40 frames)"
    assert debugger.table.item(1, 3).font().bold()
    assert not debugger.table.item(0, 3).font().bold()
    debugger.filter.setText("attack")
    assert [debugger.table.isRowHidden(row) for row in range(3)] == [True, False, True]


def test_another_map_shows_no_live_state(panels):
    scripts, debugger, session = panels
    session.map_path = "maps/map mp westfold"
    debugger.attach()
    assert "not the open map" in debugger.status.text()
    assert labels(scripts)["Intro"] == "Intro"


def test_detaching_takes_the_live_state_away(panels):
    scripts, debugger, session = panels
    debugger.attach()
    debugger.toggle()
    assert session.closed and not debugger.attached
    assert labels(scripts)["Intro"] == "Intro"
    assert debugger.table.rowCount() == 0


def test_a_game_that_exits_detaches(panels):
    _, debugger, session = panels
    debugger.attach()
    session.running = False
    debugger.poll_now()
    assert not debugger.attached
    assert debugger.status.text() == "The game has exited."


def test_a_refused_attach_says_why(qapp, tmp_path):
    def refuse():
        raise LiveAttachError("No running game was found.")

    debugger = ScriptDebuggerPanel(Host(scripted_document(tmp_path)), attach=refuse)
    assert not debugger.attach()
    assert debugger.status.text() == "No running game was found."


def trace_rows(debugger: ScriptDebuggerPanel) -> list[tuple[str, ...]]:
    rows = []
    for index in range(debugger.trace.topLevelItemCount()):
        row = debugger.trace.topLevelItem(index)
        rows.append(tuple(row.text(column) for column in range(4)))
    return rows


def test_recording_starts_with_attach_and_stops_with_detach(panels):
    _, debugger, session = panels
    assert debugger.record_box.isChecked()
    debugger.attach()
    assert session.recording
    debugger.detach()
    assert not session.recording and debugger.record_box.isChecked()


def test_unticking_while_detached_is_kept_for_the_next_attach(panels):
    _, debugger, session = panels
    debugger.record_box.setChecked(False)
    debugger.attach()
    assert not session.recording
    debugger.record_box.setChecked(True)
    assert session.recording


def test_recording_lists_the_scripts_the_game_fires(panels):
    _, debugger, session = panels
    debugger.attach()
    assert session.recording
    session.events = [
        TraceEvent(301, EventKind.TRUE_ACTIONS, 0x1000, 0),
        TraceEvent(302, EventKind.FALSE_ACTIONS, 0x2000, 77),
        TraceEvent(303, EventKind.SEQUENTIAL, 0x9999, 0),
    ]
    debugger.poll_now()
    assert trace_rows(debugger)[-3:] == [
        ("301", "Player_1", "Intro", "ran its actions"),
        ("302", "Player_1", "Idle", "ran its false actions for object 77"),
        ("303", "", "0x00009999", "queued its actions (sequential)"),
    ]
    activated = []
    debugger.script_activated.connect(activated.append)
    last = debugger.trace.topLevelItemCount()
    debugger._activate(debugger.trace.topLevelItem(last - 3), 0)
    assert activated == ["Intro"]
    debugger.record_box.setChecked(False)
    assert not session.recording


def test_variable_changes_are_traced_but_a_running_timer_is_not(panels):
    _, debugger, session = panels
    debugger.attach()
    before = debugger.trace.topLevelItemCount()
    session.waves = 4
    debugger.poll_now()
    assert trace_rows(debugger)[before:] == [("≤300", "", "/Waves", "3 → 4")]


def test_a_refused_recording_unticks_itself(panels):
    _, debugger, session = panels
    session.refuse_trace = True
    debugger.attach()
    assert not session.recording and not debugger.record_box.isChecked()
    assert any("network game" in row[2] for row in trace_rows(debugger))


def test_reshowing_a_read_does_not_repeat_its_trace(panels):
    _, debugger, session = panels
    debugger.attach()
    session.events = [TraceEvent(301, EventKind.TRUE_ACTIONS, 0x1000, 0)]
    debugger.poll_now()
    count = debugger.trace.topLevelItemCount()
    debugger.document_changed()
    assert debugger.trace.topLevelItemCount() == count


def test_pause_continue_and_step(panels):
    _, debugger, session = panels
    debugger.attach()
    assert debugger.pause_button.text() == "Pause"
    debugger.toggle_pause()
    assert session.paused and debugger.pause_button.text() == "Continue"
    assert debugger.status.text().startswith("Paused at frame 300")
    debugger.step(1)
    debugger.step_second()
    assert session.steps == [1, 5]
    debugger.toggle_pause()
    assert not session.paused and debugger.pause_button.text() == "Pause"


def test_fast_forward_follows_the_game(panels):
    _, debugger, session = panels
    assert not debugger.fast_button.isEnabled()
    debugger.attach()
    debugger.fast_button.click()
    assert session.speed == 10 and debugger.fast_button.isChecked()
    assert ", fast ×10" in debugger.status.text()
    # The engine put its own cap back: the button says so at the next read.
    session.speed = 1
    debugger.poll_now()
    assert not debugger.fast_button.isChecked()
    debugger.fast_button.click()
    debugger.fast_button.click()
    assert session.speed == 1 and not debugger.fast_button.isChecked()


def test_a_refused_fast_forward_unchecks_itself(panels):
    _, debugger, session = panels
    debugger.attach()
    session.refuse_trace = True
    debugger.fast_button.click()
    assert session.speed == 1 and not debugger.fast_button.isChecked()
    assert "network game" in debugger.status.text()


def test_the_speed_reached_is_measured_against_the_wall_clock():
    assert achieved_speed([(0.0, 100)], 5) is None
    assert achieved_speed([(0.0, 100), (1.0, 150)], 5) is None
    assert achieved_speed([(0.0, 100), (2.0, 180)], 5) == 8.0


def test_a_breakpoint_watches_every_live_copy_and_marks_the_tree(panels):
    scripts, debugger, session = panels
    debugger.breakpoints_changed.connect(scripts.set_breakpoints)
    debugger.attach()
    debugger.toggle_breakpoint("intro")
    assert session.table == {0x1000: (1 << EventKind.TRUE_ACTIONS) | (1 << EventKind.SEQUENTIAL)}
    assert labels(scripts)["Intro"].startswith("● Intro")
    assert [debugger.breakpoint_list.item(0).text()] == ["intro"]
    debugger.toggle_breakpoint("Intro")
    assert session.table == {} and not labels(scripts)["Intro"].startswith("●")


def test_a_hit_is_announced_and_selects_the_script(panels):
    _, debugger, session = panels
    debugger.attach()
    debugger.toggle_breakpoint("Idle")
    activated = []
    debugger.script_activated.connect(activated.append)
    session.paused = True
    session.hit = BreakpointHit(1, 0x2000, 305, EventKind.TRUE_ACTIONS)
    debugger.poll_now()
    assert activated == ["Idle"]
    assert trace_rows(debugger)[-1] == ("305", "Player_1", "● Idle", "breakpoint - paused")
    debugger.poll_now()
    assert activated == ["Idle"]  # the same hit is not announced twice


def test_run_until_resumes_and_removes_itself_when_it_hits(panels):
    _, debugger, session = panels
    debugger.attach()
    debugger.toggle_pause()
    debugger.run_until("Idle")
    assert not session.paused and session.table
    session.hit = BreakpointHit(1, 0x2000, 310, EventKind.TRUE_ACTIONS)
    debugger.poll_now()
    assert debugger.breakpoints == {} and session.table == {}


def test_the_tree_menu_offers_breakpoints(panels, monkeypatch):
    scripts, debugger, _ = panels
    scripts.debugger = debugger
    intro = scripts.host.document.map.player_scripts_list.script_lists[0].items[0]
    offered = []

    def choose_first(menu, _at):
        offered.append([action.text() for action in menu.actions()])
        return menu.actions()[0]

    monkeypatch.setattr(QMenu, "exec", choose_first)
    scripts.open_tree_menu(intro, QPoint(0, 0))
    assert offered == [["Break When It Fires", "Run Until It Fires"]]
    assert debugger.has_breakpoint("Intro")


def starting_game(session, failures: list[Exception]):
    """An attach that fails with each of `failures` in turn, then reaches `session`."""

    def attach():
        if failures:
            raise failures.pop(0)
        return session

    return attach


def test_attach_when_ready_retries_until_the_game_can_be_read(qapp, tmp_path):
    session = FakeSession("maps/my map")
    not_yet = [LiveAttachError("No running game was found.")] * 2
    host = Host(scripted_document(tmp_path))
    debugger = ScriptDebuggerPanel(host, starting_game(session, not_yet))
    debugger.attach_when_ready()
    assert debugger.waiting and debugger.status.text() == "Waiting for the game to start…"
    debugger._try_attach()
    debugger._try_attach()
    assert debugger.waiting and not debugger.attached
    debugger._try_attach()
    assert debugger.attached and not debugger.waiting
    assert session.recording  # recording by default, as a manual attach does
    debugger.shutdown()


def test_attach_when_ready_stops_on_a_denied_read(qapp, tmp_path):
    denied = [LiveAccessDenied("The game runs as administrator, so the editor must be run as")]
    debugger = ScriptDebuggerPanel(Host(scripted_document(tmp_path)), starting_game(None, denied))
    debugger.attach_when_ready()
    debugger._try_attach()
    assert not debugger.waiting and "administrator" in debugger.status.text()


def test_a_denied_read_offers_to_restart_elevated(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr("sage_worldbuilder.ui.script_debugger.is_elevated", lambda: False)
    session = FakeSession("maps/my map")
    denied = [LiveAccessDenied("The game runs as administrator, so the editor must be run as")]
    debugger = ScriptDebuggerPanel(
        Host(scripted_document(tmp_path)), starting_game(session, denied)
    )
    requested = []
    debugger.elevation_requested.connect(lambda: requested.append(True))
    assert not debugger.attach()
    assert not debugger.elevate_button.isHidden()
    debugger.elevate_button.click()
    assert requested == [True]
    assert debugger.attach()
    assert debugger.elevate_button.isHidden()
    debugger.shutdown()


def test_an_elevated_editor_is_not_offered_a_restart(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr("sage_worldbuilder.ui.script_debugger.is_elevated", lambda: True)
    denied = [LiveAccessDenied("The game runs as administrator, so the editor must be run as")]
    debugger = ScriptDebuggerPanel(Host(scripted_document(tmp_path)), starting_game(None, denied))
    assert not debugger.attach()
    assert debugger.elevate_button.isHidden()


def test_attach_when_ready_gives_up_at_the_deadline(qapp, tmp_path):
    never = [LiveAttachError("No running game was found.")] * 5
    debugger = ScriptDebuggerPanel(Host(scripted_document(tmp_path)), starting_game(None, never))
    debugger.attach_when_ready(timeout=0)
    debugger._try_attach()
    assert not debugger.waiting
    assert debugger.status.text().startswith("The game did not come up to attach to")


def test_attach_when_ready_keeps_a_live_attach(panels):
    _, debugger, session = panels
    debugger.attach()
    debugger.attach_when_ready()
    assert debugger.attached and not debugger.waiting and not session.closed


def tree_node(panel: ScriptsPanel, name: str):
    iterator = QTreeWidgetItemIterator(panel.tree)
    while (node := iterator.value()) is not None:
        item = node.data(0, 256)
        if getattr(item, "name", None) == name:
            return node, item
        iterator += 1
    raise AssertionError(name)


def menu_for(scripts: ScriptsPanel, name: str, monkeypatch, pick: str | None = None):
    """The tree menu of `name` as `(text, enabled)` rows, choosing `pick` when given."""
    node, item = tree_node(scripts, name)
    shown = []

    def choose(menu, _at):
        rows = [(a.text(), a.isEnabled()) for a in menu.actions() if not a.isSeparator()]
        shown.append(rows)
        return next((a for a in menu.actions() if a.text() == pick), None)

    monkeypatch.setattr(QMenu, "exec", choose)
    scripts.open_tree_menu(item, QPoint(0, 0), scripts._live_state(node, item))
    return shown[0]


@pytest.fixture
def attached(panels):
    scripts, debugger, session = panels
    scripts.debugger = debugger
    debugger.attach()
    return scripts, debugger, session


def test_the_menu_offers_triggers_for_what_the_game_holds(attached, monkeypatch):
    scripts, _, _ = attached
    assert menu_for(scripts, "Intro", monkeypatch) == [
        ("Break When It Fires", True),
        ("Run Until It Fires", True),
        ("Enable in Game", True),
        ("Re-arm", True),  # a fired one-shot
        ("Evaluate Conditions Now", True),
        ("Run Actions Now", True),
        ("Run False Actions Now", False),  # it has none
    ]
    rows = dict(menu_for(scripts, "Idle", monkeypatch))
    assert rows["Re-arm"] is False and rows["Run Actions Now"] is False
    assert [text for text, _ in menu_for(scripts, "Editor Only", monkeypatch)] == [
        "Break When It Fires",
        "Run Until It Fires",
    ]


def test_triggers_reach_the_game_and_the_trace(attached, monkeypatch):
    scripts, debugger, session = attached
    menu_for(scripts, "Intro", monkeypatch, pick="Enable in Game")
    menu_for(scripts, "Intro", monkeypatch, pick="Re-arm")
    menu_for(scripts, "Intro", monkeypatch, pick="Evaluate Conditions Now")
    menu_for(scripts, "Intro", monkeypatch, pick="Run Actions Now")
    assert session.calls == [
        ("active", "Intro", True),
        ("rearm", "Intro"),
        ("evaluate", "Intro", 0),
        ("run", "Intro", 0, False),
    ]
    notes = [row[2] for row in trace_rows(debugger)]
    assert "— conditions of 'Intro' on Player_1 are true —" in notes
    assert "— ran the actions of 'Intro' on Player_1 —" in notes


def test_variables_are_edited_by_double_click(attached, monkeypatch):
    _, debugger, session = attached
    debugger.edit_variable(2)  # a flag flips without asking
    monkeypatch.setattr(QInputDialog, "getInt", lambda *args: (7, True))
    debugger.edit_variable(0)
    monkeypatch.setattr(QInputDialog, "getDouble", lambda *args: (12.5, True))
    debugger.edit_variable(1)  # a timer is given in seconds and set in frames
    assert session.calls == [
        ("variable", "/Started", 0),
        ("variable", "/Waves", 7),
        ("variable", "Player_1/Attack", 62),
    ]


def test_a_refused_trigger_is_reported_not_raised(attached, monkeypatch):
    scripts, debugger, session = attached
    session.refuse_trace = True
    menu_for(scripts, "Intro", monkeypatch, pick="Enable in Game")
    assert session.calls == []
    assert "network game" in debugger.status.text()
