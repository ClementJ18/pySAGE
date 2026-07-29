"""Record and replay the menu navigation that gets from the launcher into a live skirmish.

Everything in `sage_live` needs a running match, and the menus are the one part of the game
this project cannot drive: order injection reaches `TheMessageStream`, which does not exist
until a game is loaded. So the menus get driven the only way they can be - as input.

    python tools/game_macro.py record skirmish.json     # then navigate the menus yourself
    python tools/game_macro.py play skirmish.json       # replays it
    python tools/game_macro.py play skirmish.json --launch

**Reproducible matches** come from pairing this with `skirmish_config`: the clicks get into a
match, and the lobby file decides *which* match. `start` takes the lobby fields directly and
applies them before launching, so one command produces the same game every time:

    python tools/game_macro.py start cold-start.json --launch "..." --faction 10 --seed 1234

**Why this is not just a macro recorder.** A blind timed replay desynchronises the first time a
loading screen runs long. This one can see the game: `sage_live` reads the process, so recording
*stops by itself* when a match actually starts, and playback *waits on that same condition*
rather than on a stopwatch. The fragile part is reduced to the menu clicks between two states we
can actually observe.

**The menu is a running game.** BFME2 draws its main menu over a *shell map* - a real map,
simulated by the same `GameLogic`, with a looping camera script. The frame counter advances and
objects exist while nobody is playing, so "is a game running?" is the wrong question and this
tool asks `Observation.in_match` instead: whether the local player is a faction rather than the
observer seat. The first version of this file got that wrong and stopped recording instantly.

Coordinates are stored in the game window's **client** space, so the window may sit anywhere on
screen at replay time. A different client *size* is refused rather than scaled - menu hit boxes
do not move linearly with resolution, and a near-miss click is worse than an honest failure.

Windows only, like everything that touches the running game. Uses `ctypes` against user32
directly; no input library is required.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import sys
import time
from ctypes import wintypes
from dataclasses import asdict, dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))  # sibling tools, when imported not run

from skirmish_config import SkirmishConfig  # noqa: E402

from sage_live.connect import AttachError, open_backend  # noqa: E402
from sage_live.memory import MemoryBackend, find_game_processes  # noqa: E402
from sage_replay.replay import ReplaySlotType  # noqa: E402

__all__ = [
    "BLIND_MENU_WAIT",
    "SAGE_WINDOW_CLASS",
    "Recording",
    "Script",
    "Step",
    "await_menu",
    "play",
    "record",
    "run_script",
    "wait_for_shell_map",
    "windows_of",
]

user32 = ctypes.WinDLL("user32", use_last_error=True)

# Mouse buttons we care about, as (name, virtual-key, down-flag, up-flag).
_BUTTONS = (
    ("left", 0x01, 0x0002, 0x0004),
    ("right", 0x02, 0x0008, 0x0010),
    ("middle", 0x04, 0x0020, 0x0040),
)
_MOUSEEVENTF_MOVE = 0x0001
_MOUSEEVENTF_ABSOLUTE = 0x8000
_MOUSEEVENTF_VIRTUALDESK = 0x4000
_KEYEVENTF_KEYUP = 0x0002
_INPUT_MOUSE, _INPUT_KEYBOARD = 0, 1
_VK_F12 = 0x7B

# Keys worth recording: enough to type a profile or game name, plus the navigation keys.
_KEYS = tuple(range(0x30, 0x5B)) + (0x08, 0x0D, 0x1B, 0x20, 0x09, 0x2E, 0xBD, 0xBE)

_MOVE_HZ = 20.0  # movement samples per second; button transitions are caught by the poll loop
_POLL_HZ = 200.0

# The engine registers its 3D window under a GUID class name. Stable across runs, and unlike
# the title it is neither localized nor shared with the `-scriptdebug2` debug dialog.
SAGE_WINDOW_CLASS = "E99E8455-CC9B-488a-BA22-0E8A8F74F9FA"

# How long to give the main menu when the shell map cannot be watched (an unelevated shell).
# The window settles to its final size long before the menu accepts input; measured on this
# machine, the menu needs about 13s from launch, so this is the floor and not an estimate.
BLIND_MENU_WAIT = 15.0


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", _MOUSEINPUT), ("ki", _KEYBDINPUT)]


class _INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


@dataclass(frozen=True)
class Event:
    """One input event, in client coordinates of the game window."""

    at: float  # seconds since the recording started
    kind: str  # "move" | "down" | "up" | "keydown" | "keyup"
    x: int = 0
    y: int = 0
    button: str = ""
    vk: int = 0


@dataclass(frozen=True)
class Recording:
    client_width: int
    client_height: int
    events: list[Event]

    def to_json(self) -> str:
        return json.dumps(
            {
                "client_width": self.client_width,
                "client_height": self.client_height,
                "events": [asdict(e) for e in self.events],
            },
            indent=1,
        )

    @classmethod
    def from_json(cls, text: str) -> Recording:
        raw = json.loads(text)
        return cls(
            client_width=int(raw["client_width"]),
            client_height=int(raw["client_height"]),
            events=[Event(**e) for e in raw["events"]],
        )


def _class_name(hwnd: int) -> str:
    buffer = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buffer, 256)
    return buffer.value


def windows_of(pid: int) -> list[tuple[int, str, int, int]]:
    """Every visible top-level window the process owns, as `(hwnd, class, width, height)`."""
    found: list[tuple[int, str, int, int]] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def callback(hwnd: int, _: int) -> bool:
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == pid and user32.IsWindowVisible(hwnd):
            rect = wintypes.RECT()
            user32.GetClientRect(hwnd, ctypes.byref(rect))
            found.append((hwnd, _class_name(hwnd), rect.right, rect.bottom))
        return True

    user32.EnumWindows(callback, 0)
    return found


@dataclass(frozen=True)
class Step:
    """One click at a named UI element, in client coordinates."""

    label: str
    x: int
    y: int
    wait: float = 2.0


@dataclass(frozen=True)
class Script:
    """A menu path written as named steps rather than captured as timed input.

    Preferred over a `Recording` for anything reusable. A recording is a stream of coordinates
    with no idea what it is clicking, so when it desynchronises it fails silently and can press
    something destructive - an early cold-start attempt clicked QUIT, because the coordinate that
    is empty space in the skirmish lobby is the quit button on the main menu. A script names each
    target, so a failure says which button it could not reach.
    """

    client_width: int
    client_height: int
    steps: list[Step]

    @classmethod
    def from_json(cls, text: str) -> Script:
        raw = json.loads(text)
        return cls(
            client_width=int(raw["client_width"]),
            client_height=int(raw["client_height"]),
            steps=[
                Step(
                    label=str(s["label"]),
                    x=int(s["x"]),
                    y=int(s["y"]),
                    wait=float(s.get("wait", 2.0)),
                )
                for s in raw["steps"]
            ],
        )


def game_window(pid: int) -> int | None:
    """The 3D game window, matched on the engine's own window class.

    **Not the biggest visible window, and not the first.** Launched with `-scriptdebug2` the
    process also owns `DebugWindowLite` (class `#32770`, a plain dialog), which is visible,
    comfortably larger than any size threshold, and enumerates *before* the game. Targeting it
    silently produces a recording whose coordinates are relative to the wrong window - clicks
    land nowhere near where they were made.

    That debug window is worth keeping, though: it is how the game's speed is controlled during
    a test. So this identifies the real one positively rather than trying to exclude the others.
    """
    for hwnd, class_name, width, height in windows_of(pid):
        if class_name == SAGE_WINDOW_CLASS:
            return hwnd
        if class_name.count("-") == 4 and width > 200 and height > 200:
            return hwnd  # another SAGE build: the class is a GUID, but a different one
    return None


def client_size(hwnd: int) -> tuple[int, int]:
    rect = wintypes.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(rect))
    return rect.right, rect.bottom


def _to_client(hwnd: int, x: int, y: int) -> tuple[int, int]:
    point = wintypes.POINT(x, y)
    user32.ScreenToClient(hwnd, ctypes.byref(point))
    return point.x, point.y


def _to_screen(hwnd: int, x: int, y: int) -> tuple[int, int]:
    point = wintypes.POINT(x, y)
    user32.ClientToScreen(hwnd, ctypes.byref(point))
    return point.x, point.y


def _cursor() -> tuple[int, int]:
    point = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(point))
    return point.x, point.y


def _down(vk: int) -> bool:
    return bool(user32.GetAsyncKeyState(vk) & 0x8000)


def _send(*inputs: _INPUT) -> None:
    array = (_INPUT * len(inputs))(*inputs)
    user32.SendInput(len(inputs), array, ctypes.sizeof(_INPUT))


def _mouse_event(flags: int, x: int = 0, y: int = 0) -> _INPUT:
    event = _INPUT(type=_INPUT_MOUSE)
    event.u.mi = _MOUSEINPUT(dx=x, dy=y, mouseData=0, dwFlags=flags, time=0, dwExtraInfo=None)
    return event


def _move_to(screen_x: int, screen_y: int) -> None:
    """Absolute move over the whole virtual desktop, in the 0..65535 space SendInput wants."""
    left = user32.GetSystemMetrics(76)  # SM_XVIRTUALSCREEN
    top = user32.GetSystemMetrics(77)
    width = user32.GetSystemMetrics(78) or 1
    height = user32.GetSystemMetrics(79) or 1
    nx = int((screen_x - left) * 65535 / width)
    ny = int((screen_y - top) * 65535 / height)
    _send(
        _mouse_event(_MOUSEEVENTF_MOVE | _MOUSEEVENTF_ABSOLUTE | _MOUSEEVENTF_VIRTUALDESK, nx, ny)
    )


def _key_event(vk: int, up: bool) -> _INPUT:
    event = _INPUT(type=_INPUT_KEYBOARD)
    event.u.ki = _KEYBDINPUT(
        wVk=vk, wScan=0, dwFlags=_KEYEVENTF_KEYUP if up else 0, time=0, dwExtraInfo=None
    )
    return event


def wait_for_process(timeout: float = 120.0) -> int:
    """The game's pid, once it exists."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        found = find_game_processes()
        if found:
            return found[0]
        time.sleep(0.5)
    raise SystemExit("game.dat never appeared")


def wait_for_window(pid: int, timeout: float = 120.0, stable_for: float = 4.0) -> int:
    """The game's window handle, once it exists **and has stopped resizing**.

    Two separate waits, both needed. The process is created well before its window is, so
    finding the pid is not enough. And the window is created before the renderer has applied
    the configured resolution: it appears at 800x600 and only then becomes the real size. A
    caller that measured immediately would record coordinates against a client area that is
    about to change, or refuse to replay a recording that is in fact fine.

    `stable_for` is 4s because the 800x600 phase measured over 1.5s long: a shorter settle
    returned the transient size and made a valid recording look like a resolution mismatch.
    """
    deadline = time.monotonic() + timeout
    settled_since: float | None = None
    last: tuple[int, int] | None = None
    while time.monotonic() < deadline:
        hwnd = game_window(pid)
        if hwnd is not None:
            size = client_size(hwnd)
            if size == last and size > (0, 0):
                if settled_since is None:
                    settled_since = time.monotonic()
                elif time.monotonic() - settled_since >= stable_for:
                    return hwnd
            else:
                settled_since = None
            last = size
        time.sleep(0.25)
    raise SystemExit("game.dat is running but its window never settled to a stable size")


def wait_for_client_size(hwnd: int, want: tuple[int, int], timeout: float = 90.0) -> bool:
    """Wait for the window to actually be the size a recording or script needs.

    Better than settling for "unchanged for N seconds": the caller knows the size it requires,
    and the startup transient at 800x600 has outlasted every fixed settle tried so far. Refusing
    only after this waits means a slow start is tolerated while a genuine resolution mismatch is
    still caught.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if client_size(hwnd) == want:
            return True
        time.sleep(0.5)
    return False


def _connect(pid: int) -> MemoryBackend | None:
    """A connected read-only backend, or None when the game cannot be read yet.

    None covers both "this shell is not elevated" and "the engine has not built `TheGameLogic`
    yet", because a caller polling for readiness has to keep trying in either case - which is
    also why this swallows `AttachError` rather than reporting it. `sage_live.attach` is for a
    game that is already up; this tool is watching one come up.
    """
    try:
        return open_backend(pid)
    except AttachError:
        return None


def in_match(pid: int) -> bool:
    """Whether a real match is running, as opposed to the menu's shell map.

    This is the whole reason the tool is not blind. It cannot be a frame-counter test: BFME2's
    main menu is drawn over a **shell map**, a real map simulated by the same `GameLogic`, so
    the frame counter advances and objects exist while the player is still in the menu. The
    honest question is whether the local player is a faction rather than the observer seat,
    which is what `Observation.in_match` asks.
    """
    backend = _connect(pid)
    if backend is None:
        return False
    try:
        return backend.observe().in_match
    finally:
        backend.close()


def wait_for_match(pid: int, timeout: float = 180.0) -> bool:
    """Block until a real match is running."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if in_match(pid):
            return True
        time.sleep(0.5)
    return False


def wait_for_shell_map(pid: int, timeout: float = 120.0, advance: int = 60) -> bool:
    """Block until the menu's shell map is simulating - the honest "the menu is up" signal.

    The window reaches its final size several seconds before the main menu will take input, so
    a click scheduled off `wait_for_window` alone lands on a still-loading screen and is
    swallowed silently. What marks the menu as live is the **shell map**: the main menu is drawn
    over a real map, and `TheGameLogic` starts ticking once it loads. A frame counter that is
    not merely non-null but *advancing* therefore says the engine is simulating, which is as
    close to "the menu is ready" as anything observable from outside.

    This is the mirror of `in_match`, not a substitute. The shell map ticking at the menu is
    exactly why a frame test cannot answer "is a match running?" - and exactly why it can answer
    "has the menu finished loading?".

    False means the shell map could not be observed within `timeout` (typically an unelevated
    shell, where nothing here can read the process at all), so the caller should fall back to
    waiting a fixed period rather than clicking immediately.
    """
    deadline = time.monotonic() + timeout
    first: int | None = None
    while time.monotonic() < deadline:
        backend = _connect(pid)
        if backend is not None:
            try:
                frame = backend.frame()
            finally:
                backend.close()
            if first is None:
                first = frame
            elif frame >= first + advance:
                return True
        time.sleep(0.25)
    return False


def await_menu(pid: int) -> None:
    """Wait for the main menu to be clickable, however that can be established.

    Prefers watching the shell map; falls back to a fixed wait when the process cannot be read.
    Never raises: a wrong guess here costs one missed click, and the script reports which step
    failed anyway.
    """
    if wait_for_shell_map(pid):
        return
    print(f"  (shell map not observable; waiting {BLIND_MENU_WAIT:.0f}s for the menu instead)")
    time.sleep(BLIND_MENU_WAIT)


def record(path: Path, pid: int | None = None) -> int:
    """Capture input until a match starts (or F12 is pressed).

    A recording has to begin at the menu, so if a match is already up this waits for it to end
    rather than stopping on its own start condition the moment it is asked to record.
    """
    pid = pid or wait_for_process()
    hwnd = wait_for_window(pid)
    width, height = client_size(hwnd)
    print(f"recording against pid {pid}, game window {hwnd}, client {width}x{height}")

    if in_match(pid):
        print("a match is already running - quit to the main menu to start recording")
        while in_match(pid):
            time.sleep(0.5)
        time.sleep(2.0)  # let the menu settle before the first sample

    print("navigate the menus into a skirmish. Recording stops when the match starts (or F12).")

    events: list[Event] = []
    started = time.monotonic()
    held = {name: False for name, *_ in _BUTTONS}
    keys_held: dict[int, bool] = {}
    last_move = 0.0
    last_position = (-1, -1)
    next_match_check = started + 2.0

    while True:
        now = time.monotonic()
        elapsed = now - started

        if _down(_VK_F12):
            print("\nF12 - stopping")
            break
        if now >= next_match_check:
            next_match_check = now + 1.0
            if in_match(pid):
                print("\na match is running - stopping")
                break

        x, y = _to_client(hwnd, *_cursor())
        for name, vk, _, _ in _BUTTONS:
            pressed = _down(vk)
            if pressed != held[name]:
                held[name] = pressed
                events.append(Event(elapsed, "down" if pressed else "up", x, y, name))
                action = "press" if pressed else "release"
                print(f"  {elapsed:7.2f}s  {action:<8}{name:<7}({x},{y})")
        for vk in _KEYS:
            pressed = _down(vk)
            if pressed != keys_held.get(vk, False):
                keys_held[vk] = pressed
                events.append(Event(elapsed, "keydown" if pressed else "keyup", vk=vk))

        if (x, y) != last_position and now - last_move >= 1.0 / _MOVE_HZ:
            last_move, last_position = now, (x, y)
            events.append(Event(elapsed, "move", x, y))

        time.sleep(1.0 / _POLL_HZ)

    recording = Recording(width, height, events)
    path.write_text(recording.to_json(), encoding="utf-8")
    clicks = sum(1 for e in events if e.kind == "down")
    print(f"\nwrote {path}: {len(events)} events, {clicks} clicks, {events[-1].at:.1f}s")
    return 0


def play(
    path: Path,
    pid: int | None = None,
    speed: float = 1.0,
    settle: float = 2.0,
    wait_menu: bool = True,
) -> int:
    """Replay a recording into the game, then wait for the match to actually start.

    A menu recording only means anything from the menu, so by default this waits for any
    running match to end rather than replaying clicks into a live game, where they would land
    on the battlefield as real orders.
    """
    recording = Recording.from_json(path.read_text(encoding="utf-8"))
    pid = pid or wait_for_process()
    hwnd = wait_for_window(pid)
    await_menu(pid)

    if wait_menu and in_match(pid):
        print("a match is running - waiting for it to end before replaying menu input")
        while in_match(pid):
            time.sleep(0.5)
        time.sleep(settle)

    want = (recording.client_width, recording.client_height)
    if not wait_for_client_size(hwnd, want):
        raise SystemExit(
            f"window is {client_size(hwnd)} but the recording was made at {want}. Menu hit boxes "
            "do not scale linearly, so replaying this would click the wrong things."
        )

    user32.SetForegroundWindow(hwnd)
    time.sleep(settle)
    print(f"replaying {len(recording.events)} events at {speed}x")

    started = time.monotonic()
    for event in recording.events:
        due = started + event.at / speed
        while True:
            remaining = due - time.monotonic()
            if remaining <= 0:
                break
            time.sleep(min(remaining, 0.05))

        if event.kind in ("move", "down", "up"):
            _move_to(*_to_screen(hwnd, event.x, event.y))
        if event.kind in ("down", "up"):
            flags = next(
                (d if event.kind == "down" else u)
                for name, _, d, u in _BUTTONS
                if name == event.button
            )
            _send(_mouse_event(flags))
        elif event.kind in ("keydown", "keyup"):
            _send(_key_event(event.vk, event.kind == "keyup"))

    print("replay finished; waiting for the match to start")
    if wait_for_match(pid):
        print("match is running")
        return 0
    print("no match started - the menus probably desynchronised from the recording")
    return 1


def click(hwnd: int, x: int, y: int) -> None:
    """A press and release at one client coordinate of `hwnd`."""
    _move_to(*_to_screen(hwnd, x, y))
    time.sleep(0.2)
    _send(_mouse_event(0x0002))
    time.sleep(0.08)
    _send(_mouse_event(0x0004))


def run_script(
    path: Path, pid: int | None = None, settle: float = 2.0, wait_menu: bool = True
) -> int:
    """Click through a named-step script, then wait for the match to start."""
    script = Script.from_json(path.read_text(encoding="utf-8"))
    pid = pid or wait_for_process()
    hwnd = wait_for_window(pid)
    await_menu(pid)

    if wait_menu and in_match(pid):
        print("a match is running - waiting for it to end")
        while in_match(pid):
            time.sleep(0.5)
        time.sleep(settle)

    want = (script.client_width, script.client_height)
    if not wait_for_client_size(hwnd, want):
        raise SystemExit(
            f"window is {client_size(hwnd)} but the script was written for {want}; "
            "menu hit boxes do not scale"
        )

    user32.SetForegroundWindow(hwnd)
    time.sleep(settle)
    for step in script.steps:
        print(f"  click {step.label!r} at ({step.x},{step.y})")
        click(hwnd, step.x, step.y)
        time.sleep(step.wait)

    print("waiting for the match to start")
    if wait_for_match(pid):
        print("match is running")
        return 0
    print("no match started - a step probably missed its button")
    return 1


def launch(shortcut: str) -> None:
    import os  # noqa: PLC0415 - only needed on the launch path

    print(f"launching {shortcut}")
    os.startfile(shortcut)  # noqa: S606 - a user-supplied shortcut is the point


def configure(entry: int, faction: int | None, seed: int | None, start: int | None) -> None:
    """Apply lobby settings before launching, so the match is decided rather than inherited.

    Must happen with the game closed: the engine reads `Skirmish.ini` when the lobby opens and
    rewrites it when a match starts, so `SkirmishConfig.save` refuses under a running game
    rather than writing something that will be silently lost.
    """
    config = SkirmishConfig.load()
    saved = config.entry(entry)
    if saved is None or saved.metadata is None:
        raise SystemExit(f"no lobby entry [{entry}] with a GameInfo - run skirmish_config show")
    humans = [s for s in saved.metadata.slots if s.slot_type is ReplaySlotType.Human]
    if len(humans) != 1:
        raise SystemExit(f"entry [{entry}] has {len(humans)} human slots; edit it directly")
    for name, value in (("faction", faction), ("start_position", start)):
        if value is not None:
            print(f"  lobby slot: {name} {getattr(humans[0], name)} -> {value}")
            setattr(humans[0], name, value)
    if seed is not None:
        print(f"  lobby seed: {saved.metadata.seed} -> {seed}")
        saved.metadata.seed = seed
    try:
        config.save()
    except RuntimeError as exc:
        raise SystemExit(f"{exc}") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    rec = sub.add_parser("record", help="capture menu navigation until a match starts")
    rec.add_argument("path", type=Path)

    run = sub.add_parser("play", help="replay a recording and wait for the match")
    run.add_argument("path", type=Path)
    run.add_argument("--speed", type=float, default=1.0, help="replay rate multiplier")
    run.add_argument("--launch", metavar="SHORTCUT", help="start the game first")
    run.add_argument("--settle", type=float, default=2.0, help="pause before the first event")
    run.add_argument(
        "--now",
        action="store_true",
        help="replay immediately instead of waiting for any running match to end",
    )

    start = sub.add_parser("start", help="click through a named-step script into a match")
    start.add_argument("path", type=Path)
    start.add_argument("--launch", metavar="SHORTCUT", help="start the game first")
    start.add_argument("--settle", type=float, default=2.0)
    start.add_argument("--entry", type=int, default=0, help="which saved lobby configuration")
    start.add_argument("--faction", type=int, help="PlayerTemplate index for the human slot")
    start.add_argument("--seed", type=int, help="match seed - what makes two runs comparable")
    start.add_argument("--start-position", type=int, help="the slot's start-position field")

    args = parser.parse_args(argv)
    if args.command == "start":
        if args.faction is not None or args.seed is not None or args.start_position is not None:
            configure(args.entry, args.faction, args.seed, args.start_position)
        if args.launch:
            launch(args.launch)
        return run_script(args.path, settle=args.settle)
    if args.command == "record":
        return record(args.path)
    if args.launch:
        launch(args.launch)
    return play(args.path, speed=args.speed, settle=args.settle, wait_menu=not args.now)


if __name__ == "__main__":
    raise SystemExit(main())
