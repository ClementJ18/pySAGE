"""The Script Debugger panel: attach to a running game, follow it, trace the scripts it fires and
list its counters, timers and flags. While the game runs the open map, the Scripts panel shows each
script's live state.

Attaching is read-only: it writes nothing to the game and needs no patch. **Record** is not - it
hooks the game so every script that fires is logged with its frame (`sage_live.backends.
script_trace`), and it takes the hooks out again when turned off or on detach. Variable changes
are traced without hooks, by comparing each read with the last, so they carry the frame of the
read that saw them rather than the frame they happened on.

**Pause, Step and breakpoints** hold the simulation with the engine's own frame gate while the
game keeps drawing (`sage_live.backends.script_debugger`). A breakpoint is a script name: it
breaks on every live copy of that script, when its actions run, and stops the game at the end of
that frame. "Run until" is a breakpoint that removes itself when it hits.

**Fast** runs the game ten times faster by raising the frame cap the engine paces its main loop to
(`sage_live.backends.game_speed`); no code is written, and detaching puts normal speed back. The
game still draws every frame, so the status line says how fast it actually got.

The game is read on a worker thread once a second, so a slow read never stalls the editor, and the
results are applied on the GUI thread by the same timer that starts the next read.
"""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable, Sequence
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Protocol

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from sage_live.backends.game_speed import FAST_FORWARD
from sage_live.backends.script_trace import BREAKPOINT_LIMIT, EventKind, kind_mask
from sage_live.backends.scripts import ScriptVariable
from sage_worldbuilder.document import MapDocument
from sage_worldbuilder.live import (
    LiveAccessDenied,
    LiveAttachError,
    LiveIndex,
    LiveSession,
    LiveSnapshot,
    LiveState,
    document_keys,
    map_key,
    side_label,
)

__all__ = ["ScriptDebuggerHost", "ScriptDebuggerPanel", "achieved_speed", "variable_value"]

_TICK_MS = 200
_POLL_SECONDS = 1.0
# How far back the measured speed looks, in seconds of wall clock.
_SPEED_WINDOW = 4.0
# After Jump To Game, how long to keep trying to attach while the game starts, and how often.
ATTACH_WAIT_SECONDS = 180.0
_ATTACH_RETRY_MS = 1000
_COLUMNS = ("Kind", "Scope", "Name", "Value")
_TRACE_COLUMNS = ("Frame", "Player", "Script or variable", "What")
# The trace keeps this many lines; it trims back to it once it is a fifth over.
TRACE_LIMIT = 5000
_ROLE = Qt.ItemDataRole.UserRole
_WHAT = {
    EventKind.TRUE_ACTIONS: "ran its actions",
    EventKind.FALSE_ACTIONS: "ran its false actions",
    EventKind.SEQUENTIAL: "queued its actions (sequential)",
}

_Key = tuple[str, str, str]
# What a breakpoint breaks on: the script firing, whichever way it runs its true actions.
_BREAK_ON = kind_mask([EventKind.TRUE_ACTIONS, EventKind.SEQUENTIAL])


class ScriptDebuggerHost(Protocol):
    @property
    def document(self) -> MapDocument | None: ...


def variable_value(variable: ScriptVariable, rate: int) -> str:
    """A variable's value as a mapper reads it: a timer in seconds left, a flag as true or false."""
    if variable.kind == "flag":
        return "true" if variable.value else "false"
    if variable.kind == "timer":
        if variable.value < 0:
            return "expired"
        return f"{variable.value / rate:.1f} s ({variable.value} frames)"
    return str(variable.value)


def achieved_speed(samples: Sequence[tuple[float, int]], rate: int) -> float | None:
    """How many times normal speed the game ran across `(monotonic seconds, logic frame)` reads,
    or None until they span enough time to say."""
    if len(samples) < 2 or rate <= 0:
        return None
    (start, first), (end, last) = samples[0], samples[-1]
    if end - start < 1.5:
        return None
    return (last - first) / (end - start) / rate


def _with(variable: ScriptVariable, value: int) -> ScriptVariable:
    return ScriptVariable(
        variable.kind, variable.scope, variable.name, value, variable.seconds, variable.address
    )


def _variable_change(old: ScriptVariable | None, new: ScriptVariable, rate: int) -> str | None:
    """What a trace line says about a variable between two reads, or None when nothing worth a
    line happened. A running timer changes on every read, so only a timer being set or running
    out is a change."""
    if old is None:
        return f"created, {variable_value(new, rate)}"
    if old.value == new.value and old.kind == new.kind:
        return None
    if new.kind == "timer":
        if new.value < 0 <= old.value:
            return "expired"
        if new.value <= old.value:
            return None
        return f"set to {variable_value(new, rate)}"
    return f"{variable_value(old, rate)} → {variable_value(new, rate)}"


class ScriptDebuggerPanel(QWidget):
    #: The running game's scripts when it runs the open map, None otherwise.
    live_changed = pyqtSignal(object)
    #: A trace line was double-clicked, or a breakpoint hit: the name of the script it is about.
    script_activated = pyqtSignal(str)
    #: The breakpoints changed: the set of script names, in case-folded form.
    breakpoints_changed = pyqtSignal(object)

    def __init__(
        self,
        host: ScriptDebuggerHost,
        attach: Callable[[], LiveSession] = LiveSession.attach,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.host = host
        self._attach = attach
        self.session: LiveSession | None = None
        self.snapshot: LiveSnapshot | None = None
        self._matched = False
        self._pool: ThreadPoolExecutor | None = None
        self._pending: Future[LiveSnapshot | None] | None = None
        self._last_poll = 0.0
        self._keys: list[_Key] = []
        self._values: dict[_Key, str] = {}
        self._variables: dict[tuple[str, str], ScriptVariable] | None = None
        self._dropped = 0
        # Breakpoints by case-folded script name: the name as given, and whether it is a "run
        # until" that removes itself when it hits. They outlive an attach.
        self.breakpoints: dict[str, tuple[str, bool]] = {}
        self._hits: int | None = None
        # Running reads while the game is fast, for the speed it really reaches.
        self._speed_samples: deque[tuple[float, int]] = deque()

        layout = QVBoxLayout(self)
        row = QHBoxLayout()
        self.attach_button = QPushButton("Attach")
        self.attach_button.setToolTip(
            "Read the running game's scripts. Nothing is written to the game; the editor must run "
            "as administrator, as the game does."
        )
        self.attach_button.clicked.connect(self.toggle)
        row.addWidget(self.attach_button)
        self.status = QLabel("Not attached.")
        self.status.setWordWrap(True)
        row.addWidget(self.status, 1)
        layout.addLayout(row)

        controls = QHBoxLayout()
        self.pause_button = QPushButton("Pause")
        self.pause_button.setToolTip(
            "Hold the game's simulation; it keeps drawing, and the camera still moves. This hooks "
            "the running game."
        )
        self.pause_button.clicked.connect(lambda _checked=False: self.toggle_pause())
        controls.addWidget(self.pause_button)
        self.step_button = QPushButton("Step")
        self.step_button.setToolTip("Run one logic frame, then hold again.")
        self.step_button.clicked.connect(lambda _checked=False: self.step(1))
        controls.addWidget(self.step_button)
        self.step_second_button = QPushButton("Step 1 s")
        self.step_second_button.setToolTip("Run one second of game time, then hold again.")
        self.step_second_button.clicked.connect(lambda _checked=False: self.step_second())
        controls.addWidget(self.step_second_button)
        self.fast_button = QPushButton(f"Fast ×{FAST_FORWARD}")
        self.fast_button.setCheckable(True)
        self.fast_button.setToolTip(
            f"Run the game {FAST_FORWARD} times faster by raising its frame cap; the simulation's "
            "own timing is unchanged. The game still draws every frame, so a machine that cannot "
            "draw that fast runs as fast as it can - the status line shows the speed reached."
        )
        self.fast_button.clicked.connect(self.set_fast)
        controls.addWidget(self.fast_button)
        controls.addStretch(1)
        layout.addLayout(controls)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_trace_page(), "Trace")
        self.tabs.addTab(self._build_variables_page(), "Variables")
        self.tabs.addTab(self._build_breakpoints_page(), "Breakpoints")
        layout.addWidget(self.tabs, 1)

        self.timer = QTimer(self)
        self.timer.setInterval(_TICK_MS)
        self.timer.timeout.connect(self._tick)
        # Retries an attach while a game Jump To Game started is still coming up.
        self._wait_timer = QTimer(self)
        self._wait_timer.setInterval(_ATTACH_RETRY_MS)
        self._wait_timer.timeout.connect(self._try_attach)
        self._wait_deadline = 0.0
        self._sync_controls()

    def _build_breakpoints_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        hint = QLabel(
            "Right-click a script in the Scripts panel to break when it fires. The game stops at "
            "the end of that frame."
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.breakpoint_list = QListWidget()
        self.breakpoint_list.itemDoubleClicked.connect(
            lambda item: self.script_activated.emit(item.data(_ROLE))
        )
        layout.addWidget(self.breakpoint_list, 1)
        row = QHBoxLayout()
        remove = QPushButton("Remove")
        remove.clicked.connect(lambda _checked=False: self._remove_selected_breakpoint())
        row.addWidget(remove)
        clear = QPushButton("Clear All")
        clear.clicked.connect(lambda _checked=False: self.clear_breakpoints())
        row.addWidget(clear)
        row.addStretch(1)
        layout.addLayout(row)
        return page

    def _build_trace_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        row = QHBoxLayout()
        self.record_box = QCheckBox("Record fired scripts")
        self.record_box.setToolTip(
            "Hook the game so every script whose actions run is logged with its frame. On by "
            "default: it starts with Attach. This writes code into the running game, and takes it "
            "out again when turned off or on Detach; a network game is refused."
        )
        self.record_box.setChecked(True)
        self.record_box.toggled.connect(self.set_recording)
        row.addWidget(self.record_box)
        self.follow_box = QCheckBox("Follow")
        self.follow_box.setChecked(True)
        row.addWidget(self.follow_box)
        clear = QPushButton("Clear")
        clear.clicked.connect(lambda _checked=False: self.trace.clear())
        row.addWidget(clear)
        row.addStretch(1)
        layout.addLayout(row)
        self.trace_filter = QLineEdit()
        self.trace_filter.setPlaceholderText("Filter the trace")
        self.trace_filter.textChanged.connect(lambda _text: self._filter_trace())
        layout.addWidget(self.trace_filter)
        self.trace = QTreeWidget()
        self.trace.setHeaderLabels(_TRACE_COLUMNS)
        self.trace.setRootIsDecorated(False)
        self.trace.setUniformRowHeights(True)
        self.trace.itemDoubleClicked.connect(self._activate)
        header = self.trace.header()
        if header is not None:
            header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.trace, 1)
        return page

    def _build_variables_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Filter counters, timers and flags")
        self.filter.textChanged.connect(lambda _text: self._apply_filter())
        layout.addWidget(self.filter)
        self.table = QTableWidget(0, len(_COLUMNS))
        self.table.setHorizontalHeaderLabels(_COLUMNS)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.verticalHeader().setVisible(False)  # type: ignore[union-attr]
        self.table.setToolTip("Double-click a value to change it in the game.")
        self.table.cellDoubleClicked.connect(lambda row, _column: self.edit_variable(row))
        header = self.table.horizontalHeader()
        if header is not None:
            header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table, 1)
        return page

    @property
    def attached(self) -> bool:
        return self.session is not None

    def toggle(self) -> None:
        if self.attached:
            self.detach()
        else:
            self.attach()

    @property
    def waiting(self) -> bool:
        """Whether an attach is being retried until a starting game can be read."""
        return self._wait_timer.isActive()

    def attach_when_ready(self, timeout: float = ATTACH_WAIT_SECONDS) -> None:
        """Attach to a game that is starting - Jump To Game's - as soon as it can be read.
        Already attached to a game that is still running, this does nothing."""
        session = self.session
        if session is not None:
            if session.alive():
                return
            self.detach("The game has exited.")
        self._wait_deadline = time.monotonic() + timeout
        self.status.setText("Waiting for the game to start…")
        self._wait_timer.start()

    def _try_attach(self) -> None:
        if self.session is not None:
            self._wait_timer.stop()
            return
        try:
            session = self._attach()
        except LiveAccessDenied as exc:
            self._wait_timer.stop()
            self.status.setText(str(exc))
            return
        except LiveAttachError as exc:
            # A game still starting cannot be read yet; that fixes itself, up to the deadline.
            if time.monotonic() >= self._wait_deadline:
                self._wait_timer.stop()
                self.status.setText(f"The game did not come up to attach to: {exc}")
            return
        self._wait_timer.stop()
        self._start(session)

    def attach(self) -> bool:
        self._wait_timer.stop()
        try:
            session = self._attach()
        except LiveAttachError as exc:
            self.status.setText(str(exc))
            return False
        self._start(session)
        return True

    def _start(self, session: LiveSession) -> None:
        self.session = session
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="script-debugger")
        self.attach_button.setText("Detach")
        self.status.setText(f"Attached to the game (process {self.session.pid}). Reading…")
        # The box is the mapper's choice either way; attached, it is also the hooks' state.
        if self.record_box.isChecked():
            self.set_recording(True)
        self._hits = None
        self.poll_now()
        self.timer.start()
        self._sync_controls()

    def detach(self, reason: str = "Not attached.") -> None:
        self._wait_timer.stop()
        self.timer.stop()
        self._settle()
        if self._pool is not None:
            self._pool.shutdown(wait=True, cancel_futures=True)
            self._pool = None
        if self.session is not None:
            self.session.close()
            self.session = None
        self.snapshot = None
        self._speed_samples.clear()
        self.attach_button.setText("Attach")
        self._sync_controls()
        self.status.setText(reason)
        self.table.setRowCount(0)
        self._keys, self._values = [], {}
        self._variables = None
        self._publish(None)

    def _settle(self) -> None:
        """Let a read in flight finish and show it, so nothing races a change to the session."""
        pending, self._pending = self._pending, None
        if pending is None:
            return
        try:
            snapshot = pending.result()
        except OSError:
            return
        self._show(snapshot)

    def set_recording(self, on: bool) -> None:
        """Start or stop the trace hooks. Detached, only the choice is kept, for the next Attach."""
        session = self.session
        if session is None or session.recording == on:
            return
        self._settle()
        if on:
            try:
                session.set_recording(True)
            except LiveAttachError as exc:
                # Also a trace line: the next read replaces the status, the trace keeps it.
                self.status.setText(str(exc))
                self._add_note(f"not recording: {exc}")
                self.record_box.blockSignals(True)
                self.record_box.setChecked(False)
                self.record_box.blockSignals(False)
                return
            self._dropped = 0
            self._add_note("recording started")
        else:
            notes = session.set_recording(False)
            self._add_note("recording stopped" + (f": {'; '.join(notes)}" if notes else ""))

    def _sync_controls(self) -> None:
        attached = self.session is not None
        paused = self.snapshot is not None and self.snapshot.paused
        self.pause_button.setText("Continue" if paused else "Pause")
        for button in (
            self.pause_button,
            self.step_button,
            self.step_second_button,
            self.fast_button,
        ):
            button.setEnabled(attached)
        # The game's pace, not the last click: the engine resets the cap itself at times.
        self.fast_button.setChecked(self.snapshot is not None and self.snapshot.speed > 1)

    def _debug(self, action: Callable[[LiveSession], None]) -> bool:
        """Run a pause or step on the session, reporting a refusal; True when it went through."""
        session = self.session
        if session is None:
            return False
        self._settle()
        try:
            action(session)
        except LiveAttachError as exc:
            self.status.setText(str(exc))
            self._add_note(str(exc))
            return False
        self.poll_now()
        return True

    def toggle_pause(self) -> None:
        if self.snapshot is not None and self.snapshot.paused:
            self._debug(lambda session: session.resume())
        else:
            self._debug(lambda session: session.pause())

    def step(self, frames: int) -> None:
        self._debug(lambda session: session.step(frames))

    def step_second(self) -> None:
        rate = self.snapshot.logic_rate if self.snapshot is not None else 5
        self.step(rate)

    def set_fast(self, on: bool) -> None:
        """Run the game `FAST_FORWARD` times faster, or at normal speed."""
        self._speed_samples.clear()
        if not self._debug(lambda session: session.set_speed(FAST_FORWARD if on else 1)):
            self._sync_controls()

    def _trigger(self, done: str, action: Callable[[LiveSession], object]) -> object:
        """Run one trigger on the session, and say what happened in the trace either way."""
        session = self.session
        if session is None:
            return None
        self._settle()
        try:
            result = action(session)
        except LiveAttachError as exc:
            self.status.setText(str(exc))
            self._add_note(str(exc))
            return None
        self._add_note(done)
        self.poll_now()
        return result

    def _describe(self, state: LiveState) -> str:
        name = state.script.name if state.script else state.group.name if state.group else "?"
        return f"'{name}' on {side_label(state.side, state.player)}"

    def set_active(self, state: LiveState, active: bool) -> None:
        """Switch a script or group on or off in the game."""
        what = "enabled" if active else "disabled"
        if state.script is not None:
            script = state.script
            self._trigger(
                f"{what} {self._describe(state)}",
                lambda session: session.set_script_active(script, active),
            )
        elif state.group is not None:
            group = state.group
            self._trigger(
                f"{what} {self._describe(state)}",
                lambda session: session.set_group_active(group, active),
            )

    def rearm(self, state: LiveState) -> None:
        script = state.script
        if script is not None:
            self._trigger(f"re-armed {self._describe(state)}", lambda s: s.rearm(script))

    def evaluate(self, state: LiveState) -> None:
        """Test a script's conditions now, and put the answer in the trace."""
        script = state.script
        session = self.session
        if script is None or session is None:
            return
        self._settle()
        try:
            passed = session.evaluate(script, state.side)
        except LiveAttachError as exc:
            self.status.setText(str(exc))
            self._add_note(str(exc))
            return
        verdict = "true" if passed else "false"
        self._add_note(f"conditions of {self._describe(state)} are {verdict}")

    def run_actions(self, state: LiveState, false_actions: bool) -> None:
        """Run a script's true or false actions now, whatever its conditions say."""
        script = state.script
        if script is None:
            return
        which = "false actions" if false_actions else "actions"
        self._trigger(
            f"ran the {which} of {self._describe(state)}",
            lambda session: session.run_actions(script, state.side, false_actions),
        )

    def edit_variable(self, row: int) -> None:
        """Change a counter, timer or flag in the game: a flag flips, the others ask."""
        snapshot = self.snapshot
        if snapshot is None or not 0 <= row < len(self._keys):
            return
        kind, scope, name = self._keys[row]
        variable = next(
            (v for v in snapshot.variables if (v.kind, v.scope, v.name) == (kind, scope, name)),
            None,
        )
        if variable is None:
            return
        rate = snapshot.logic_rate
        if variable.kind == "flag":
            value = 0 if variable.value else 1
        elif variable.kind == "timer":
            seconds, ok = QInputDialog.getDouble(
                self,
                "Set Timer",
                f"Seconds left on {variable.key}:",
                max(variable.value, 0) / rate,
                0.0,
                1_000_000.0,
                1,
            )
            if not ok:
                return
            value = round(seconds * rate)
        else:
            value, ok = QInputDialog.getInt(
                self, "Set Counter", f"{variable.key}:", variable.value, -(2**31), 2**31 - 1
            )
            if not ok:
                return
        self._trigger(
            f"set {variable.kind} {variable.key} to {variable_value(_with(variable, value), rate)}",
            lambda session: session.set_variable(variable, value),
        )

    def has_breakpoint(self, name: str) -> bool:
        return name.casefold() in self.breakpoints

    def toggle_breakpoint(self, name: str) -> None:
        """Break when `name` fires, or stop breaking on it."""
        key = name.casefold()
        if key in self.breakpoints:
            del self.breakpoints[key]
        else:
            self.breakpoints[key] = (name, False)
        self._breakpoints_changed()

    def run_until(self, name: str) -> None:
        """Let the game run until `name` fires, and hold it there."""
        key = name.casefold()
        if key not in self.breakpoints:
            self.breakpoints[key] = (name, True)
        self._breakpoints_changed()
        if self.snapshot is not None and self.snapshot.paused:
            self._debug(lambda session: session.resume())

    def clear_breakpoints(self) -> None:
        self.breakpoints.clear()
        self._breakpoints_changed()

    def _remove_selected_breakpoint(self) -> None:
        item = self.breakpoint_list.currentItem()
        if item is not None:
            self.breakpoints.pop(str(item.data(_ROLE)).casefold(), None)
            self._breakpoints_changed()

    def _breakpoints_changed(self) -> None:
        self.breakpoint_list.clear()
        for name, temporary in sorted(self.breakpoints.values(), key=lambda b: b[0].casefold()):
            label = f"{name}  (run until)" if temporary else name
            item = QListWidgetItem(label)
            item.setData(_ROLE, name)
            self.breakpoint_list.addItem(item)
        self.breakpoints_changed.emit(set(self.breakpoints))
        if self.snapshot is not None:
            # A read in flight must not race the hooks going in.
            self._settle()
            if self.snapshot is not None:
                self._sync_breakpoints(LiveIndex(self.snapshot))

    def _sync_breakpoints(self, index: LiveIndex) -> None:
        """Write the breakpoint table for this read's scripts. Names are resolved afresh each
        read, since a map reload moves every script."""
        session = self.session
        if session is None:
            return
        table = {address: _BREAK_ON for key in self.breakpoints for address in index.addresses(key)}
        if len(table) > BREAKPOINT_LIMIT:
            self.status.setText(
                f"Only the first {BREAKPOINT_LIMIT} live copies of the breakpoint scripts are "
                "watched."
            )
            table = dict(sorted(table.items())[:BREAKPOINT_LIMIT])
        try:
            session.set_breakpoints(table)
        except LiveAttachError as exc:
            self.status.setText(str(exc))

    def _check_hit(self, snapshot: LiveSnapshot, index: LiveIndex) -> None:
        """React to a breakpoint that hit since the last read: say which, and select it."""
        hit = snapshot.hit
        count = hit.count if hit is not None else 0
        if self._hits is None or hit is None or count <= self._hits:
            self._hits = count
            return
        self._hits = count
        found = index.at(hit.script)
        name = found[1].name if found is not None else f"0x{hit.script:08X}"
        player = found[0] if found is not None else ""
        self._append([self._line(str(hit.frame), player, f"● {name}", "breakpoint - paused")])
        entry = self.breakpoints.get(name.casefold())
        if entry is not None and entry[1]:
            del self.breakpoints[name.casefold()]
            self._breakpoints_changed()
        self.script_activated.emit(name)

    def poll_now(self) -> None:
        """Read the game on this thread and show it - Attach's first read, and the tests'."""
        if self.session is not None:
            self._show(self.session.poll())

    def _tick(self) -> None:
        pending = self._pending
        if pending is not None:
            if not pending.done():
                return
            self._pending = None
            try:
                snapshot = pending.result()
            except OSError as exc:
                self.detach(f"Reading the game failed: {exc}")
                return
            self._show(snapshot)
        session, pool = self.session, self._pool
        if session is None or pool is None:
            return
        if time.monotonic() - self._last_poll >= _POLL_SECONDS:
            self._last_poll = time.monotonic()
            self._pending = pool.submit(session.poll)

    def _show(self, snapshot: LiveSnapshot | None, fresh: bool = True) -> None:
        """Show a read. `fresh` is False when an old read is shown again, whose trace is already
        in the list."""
        session = self.session
        if session is None:
            return
        if snapshot is None:
            if not session.alive():
                self.detach("The game has exited.")
                return
            self.snapshot = None
            self._variables = None
            self.status.setText("Attached; no match is running.")
            self._publish(None)
            return
        self.snapshot = snapshot
        running = map_key(snapshot.map_path) if snapshot.map_path else ""
        document = self.host.document
        opened = document_keys(document) if document is not None else set()
        self._matched = bool(running) and running in opened
        where = f"running {running or 'an unknown map'}"
        if not self._matched:
            where += (
                " - not the open map, so the Scripts panel shows no live state"
                if opened
                else " - save or open that map to see live state in the Scripts panel"
            )
        state = (
            f"Paused at frame {snapshot.frame}" if snapshot.paused else f"Frame {snapshot.frame}"
        )
        if snapshot.speed > 1:
            state += f", fast ×{snapshot.speed}"
            reached = self._measure(snapshot) if fresh else None
            if reached is not None:
                state += f" (reaching ×{reached:.1f})"
        self.status.setText(
            f"{state}, {snapshot.script_count} scripts, "
            f"{len(snapshot.variables)} variables; {where}."
        )
        index = LiveIndex(snapshot)
        if fresh:
            self._trace_snapshot(snapshot, index)
            self._check_hit(snapshot, index)
            self._sync_breakpoints(index)
        self._fill(snapshot)
        self._sync_controls()
        self._publish(index if self._matched else None)

    def _measure(self, snapshot: LiveSnapshot) -> float | None:
        """The speed the game reaches, over the fast, running reads of the last few seconds."""
        samples = self._speed_samples
        if snapshot.paused or snapshot.speed <= 1:
            samples.clear()
            return None
        now = time.monotonic()
        samples.append((now, snapshot.frame))
        while samples and now - samples[0][0] > _SPEED_WINDOW:
            samples.popleft()
        return achieved_speed(samples, snapshot.logic_rate)

    def document_changed(self) -> None:
        """Re-check the running map against a newly opened document."""
        if self.snapshot is not None:
            self._show(self.snapshot, fresh=False)

    def _publish(self, live: LiveIndex | None) -> None:
        self.live_changed.emit(live)

    def _trace_snapshot(self, snapshot: LiveSnapshot, index: LiveIndex) -> None:
        """Append what one read saw: the scripts fired since the last, then the variables that
        moved."""
        rows: list[QTreeWidgetItem] = []
        if snapshot.dropped > self._dropped:
            lost = snapshot.dropped - self._dropped
            self._dropped = snapshot.dropped
            rows.append(self._line("", "", f"{lost} events were lost", "the ring overflowed"))
        for event in snapshot.trace:
            found = index.at(event.script)
            player, name = (found[0], found[1].name) if found else ("", f"0x{event.script:08X}")
            what = _WHAT[event.kind]
            if event.object_id:
                what += f" for object {event.object_id}"
            rows.append(self._line(str(event.frame), player, name, what, script=name))
        current = {(v.scope, v.name): v for v in snapshot.variables}
        if self._variables is not None:
            for key, variable in current.items():
                change = _variable_change(self._variables.get(key), variable, snapshot.logic_rate)
                if change is not None:
                    row = self._line(f"≤{snapshot.frame}", variable.scope, variable.key, change)
                    font = QFont(row.font(2))
                    font.setItalic(True)
                    row.setFont(2, font)
                    rows.append(row)
        self._variables = current
        self._append(rows)

    def _line(
        self, frame: str, player: str, subject: str, what: str, script: str | None = None
    ) -> QTreeWidgetItem:
        row = QTreeWidgetItem([frame, player, subject, what])
        row.setData(0, _ROLE, script)
        return row

    def _add_note(self, text: str) -> None:
        frame = str(self.snapshot.frame) if self.snapshot is not None else ""
        row = self._line(frame, "", f"— {text} —", "")
        self._append([row])

    def _append(self, rows: list[QTreeWidgetItem]) -> None:
        if not rows:
            return
        self.trace.addTopLevelItems(rows)
        count = self.trace.topLevelItemCount()
        if count > TRACE_LIMIT + TRACE_LIMIT // 5:
            root = self.trace.invisibleRootItem()
            if root is not None:
                kept = root.takeChildren()[count - TRACE_LIMIT :]
                self.trace.addTopLevelItems(kept)
        needle = self.trace_filter.text().strip()
        if needle:
            for row in rows:
                row.setHidden(not self._trace_matches(row, needle.casefold()))
        if self.follow_box.isChecked():
            self.trace.scrollToBottom()

    @staticmethod
    def _trace_matches(row: QTreeWidgetItem, needle: str) -> bool:
        return any(needle in row.text(column).casefold() for column in range(4))

    def _filter_trace(self) -> None:
        needle = self.trace_filter.text().strip().casefold()
        for index in range(self.trace.topLevelItemCount()):
            row = self.trace.topLevelItem(index)
            if row is not None:
                row.setHidden(bool(needle) and not self._trace_matches(row, needle))

    def _activate(self, row: QTreeWidgetItem, _column: int) -> None:
        script = row.data(0, _ROLE)
        if isinstance(script, str) and script:
            self.script_activated.emit(script)

    def _fill(self, snapshot: LiveSnapshot) -> None:
        rows = [
            ((v.kind, v.scope, v.name), variable_value(v, snapshot.logic_rate))
            for v in snapshot.variables
        ]
        keys = [key for key, _ in rows]
        if keys != self._keys:
            self.table.setRowCount(len(rows))
            for index, (key, value) in enumerate(rows):
                for column, text in enumerate((*key, value)):
                    self.table.setItem(index, column, QTableWidgetItem(text))
            self._keys = keys
        else:
            for index, (key, value) in enumerate(rows):
                cell = self.table.item(index, 3)
                if cell is None:
                    continue
                cell.setText(value)
                font = QFont(cell.font())
                # A value that moved since the last read is bold until the next one.
                font.setBold(self._values.get(key) != value)
                cell.setFont(font)
        self._values = dict(rows)
        self._apply_filter()

    def _apply_filter(self) -> None:
        needle = self.filter.text().strip().casefold()
        for index, (kind, scope, name) in enumerate(self._keys):
            text = f"{kind} {scope}/{name}".casefold()
            self.table.setRowHidden(index, bool(needle) and needle not in text)

    def shutdown(self) -> None:
        """Detach without touching the widgets - for the window closing. Waits for a read in
        flight, so the trace hooks are never taken out from under it."""
        self._wait_timer.stop()
        self.timer.stop()
        if self._pool is not None:
            self._pool.shutdown(wait=True, cancel_futures=True)
            self._pool = None
        self._pending = None
        if self.session is not None:
            self.session.close()
            self.session = None
