"""Compile, launch, bind: one scenario from declaration to a live `Match`.

The four stages each have their own module; this is the one call that walks them, and it is a
context manager because the thing it produces owns a **process**. A scenario that leaks its game
does not merely waste memory - the engine refuses to start a second copy of itself, so one leaked
process turns every later scenario into a failure with an unrelated-looking cause.

Deliberately free of `pytest`, so a scenario can be run from a script, a notebook or a `__main__`
exactly as a test runs it; `sage_test.plugin` is the thin fixture wrapper over this.

Not re-exported from `sage_test`, for the reason `sage_live` keeps `resolve` and `statics` out of
its root: importing this pulls in `sage_map` and `sage_live`, and the declaration layer is worth
keeping importable without either.
"""

from __future__ import annotations

import io
import shutil
import time
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path

import sage_live
from sage_live.api.session import Session
from sage_live.launch.game_info import LobbySettings, game_info_string
from sage_live.launch.maps import read_archive_file
from sage_live.launch.runner import GameProcess, install_map, install_map_folder, launch
from sage_map import parse_map, write_map
from sage_test.compile import compile_into
from sage_test.harness import DEFAULT_TOLERANCE, Match, bind_handles
from sage_test.scenario import Scenario, Seat

__all__ = [
    "DEFAULT_TIMEOUT",
    "EngineUnavailable",
    "MapIniError",
    "check_map_ini",
    "read_template",
    "run_map",
    "run_scenario",
    "run_user_map",
    "write_map_ini",
]

#: How long to wait for a launched game to reach frame 1. Measured at roughly 25 s on a shipped
#: multiplayer map; the rest is headroom for a cold disk cache.
DEFAULT_TIMEOUT = 120.0


class EngineUnavailable(RuntimeError):
    """The game could not be brought up far enough to run a scenario against it."""


class MapIniError(ValueError):
    """A scenario's `map.ini` would not load, found before the game is launched.

    Checked up front because the engine's own answer to a broken override is an error box that
    waits for a click, which a test only sees as the launch timing out two minutes later.
    """


def write_map_ini(scenario: Scenario, folder: Path) -> Path | None:
    """Write `scenario`'s `map.ini` into the generated map's `folder`, includes and all.

    Returns the file written, or None when the scenario has no override. Written with CRLF and
    a final line ending, as the mod's own map inis are: the engine is known to drop an
    unterminated last line in other text files it reads.
    """
    path = folder / "map.ini"
    if not scenario.map_ini.strip():
        # A folder left by `--keep-maps` may still hold an earlier run's override.
        path.unlink(missing_ok=True)
        return None
    for include in scenario.map_ini_includes:
        source = Path(include)
        target = folder / source.name
        if source.is_dir():
            shutil.copytree(source, target, dirs_exist_ok=True)
        elif source.is_file():
            shutil.copy2(source, target)
        else:
            raise MapIniError(f"map.ini include {source} does not exist")
    text = scenario.map_ini.replace("\r\n", "\n").rstrip("\n") + "\n"
    path.write_bytes(text.replace("\n", "\r\n").encode("cp1252"))
    return path


def check_map_ini(path: Path) -> list[str]:
    """What would stop the `map.ini` at `path` loading: parse errors and bare modules.

    Each entry is one line, `file:line: [code] message`. Parse errors are what an `End` too few
    or too many produces; a bare module is what the engine crashes on ("You must use AddModule
    to add modules in override INI files"). References to definitions elsewhere in the mod are
    not checked - one file on its own cannot resolve them - so those are left to the engine.
    """
    # Imported here: the ini model is a large import, and a scenario without a map.ini never
    # needs it.
    from sage_ini.model.game import Game  # noqa: PLC0415
    from sage_ini.parser.blockparser import parse_file  # noqa: PLC0415
    from sage_ini.parser.diagnostics import Severity  # noqa: PLC0415
    from sage_lint.rules.map_ini import MapBareModuleRule  # noqa: PLC0415

    result = parse_file(path, resolve_includes=True, include_layers=(path.parent,))
    found = [d for d in result.diagnostics.items if d.severity is Severity.ERROR]
    game = Game()
    try:
        game.load_document(result.document)
    except (ValueError, KeyError, TypeError, IndexError) as exc:
        return [f"{path}: [load-error] {exc}"]
    found += list(MapBareModuleRule().check(game))
    return [f"{d.span.file}:{d.span.line_start}: [{d.code}] {d.message}" for d in found]


def read_template(install: Path, name: str) -> bytes:
    """A shipped map, straight out of the install's `.big` archives - or, when `name` is a `.map`
    file that exists, that file.

    Scenarios are compiled onto a map that already plays rather than generated from nothing - see
    `sage_test.compile` - and this is where that map comes from. A file lets a mod keep a template
    of its own beside its tests (a flat, empty map that leaves only the scenario on it) without
    shipping it in an archive. An archive name is relative, so it never names a file by accident.
    """
    path = Path(name)
    if path.suffix.lower() == ".map" and path.is_file():
        return path.read_bytes()
    try:
        return read_archive_file(install, name)
    except ImportError as exc:  # pragma: no cover - depends on the install extra
        raise EngineUnavailable(f"{exc}; install the package's archive extra") from exc
    except FileNotFoundError as exc:
        raise EngineUnavailable(str(exc)) from exc


def _game_info(seats: Sequence[Seat], settings: LobbySettings | None) -> str | None:
    """The `-gameInfo` value for `seats`, or None to let the patch start its default match.

    Settings without seats are refused rather than dropped: the lobby string carries both or
    neither, and silently starting the default match would run a test against rules it did not
    ask for.
    """
    if not seats:
        if settings is not None:
            raise ValueError("lobby settings need seats to travel with - declare the seats too")
        return None
    return game_info_string(seats, settings)


def _await_session(process: GameProcess, timeout: float, writable: bool) -> Session:
    """Attach to a launching game once it is simulating, or say why it never got there.

    Frame 1 is the gate because everything that can go wrong on the way to it - the map missing
    from the cache, a mod file the ini parser refuses, no `command-line-skirmish` to configure a
    match - ends with a process that either exits or never advances, and both are failures. The
    retry loop is what tolerates the several seconds of loading before the bridge is readable.
    """
    deadline = time.monotonic() + timeout
    while True:
        if process.returncode is not None:
            raise EngineUnavailable(
                f"the game exited (rc 0x{process.returncode & 0xFFFFFFFF:08X}) before the "
                "match started - is command-line-skirmish applied to this game.dat?"
            )
        if time.monotonic() > deadline:
            raise EngineUnavailable(f"no match after {timeout}s")
        try:
            attached = sage_live.attach(process.pid, writable=writable)
        except Exception:  # noqa: BLE001 - still loading, or the bridge is not there yet
            time.sleep(1.0)
            continue
        if attached.observe().frame >= 1:
            return attached
        attached.close()
        time.sleep(1.0)


@contextmanager
def run_map(
    argument: str,
    install: str | Path,
    *,
    seats: Sequence[Seat] = (),
    settings: LobbySettings | None = None,
    writable: bool = False,
    timeout: float = DEFAULT_TIMEOUT,
    windowed: bool = True,
    mod: str | Path | Sequence[str | Path] | None = None,
    engine_args: Sequence[str] = (),
) -> Iterator[Session]:
    """Start a map that already exists, and yield the running game.

    The counterpart to `run_scenario`: nothing is compiled and nothing is written, because
    the map under test is the one the mod ships - **including its `map.ini`**, which is loaded
    from the map's own folder and so cannot come along with a copy of the map installed
    elsewhere. That makes this the only way to put a shipped map's per-map data in front of the
    real ini parser.

    `argument` is the `-file` form, not a path: `sage_live.launch.maps.MapEntry.argument` produces
    it, and the rules it follows are in that module.

    `seats` and `settings` choose the match through `-gameInfo`; leave both out for the patch's
    default two-seat game.

    Reaching frame 1 is the whole result. A caller wanting more - that the match is a real one,
    that it keeps running - asserts it on the yielded `Session`.
    """
    install = Path(install)
    game_dat = install / "game.dat"
    if not game_dat.is_file():
        raise EngineUnavailable(f"no game.dat in {install}")

    game_info = _game_info(seats, settings)
    process = launch(
        argument,
        game_dat,
        game_info=game_info,
        mod=mod,
        windowed=windowed,
        extra=tuple(engine_args),
    )
    session = None
    try:
        session = _await_session(process, timeout, writable)
        yield session
    finally:
        if session is not None:
            session.close()
        process.kill()


@contextmanager
def run_user_map(
    source: str | Path,
    install: str | Path,
    *,
    name: str | None = None,
    extras: tuple[str | Path, ...] = (),
    seats: Sequence[Seat] = (),
    settings: LobbySettings | None = None,
    keep_map: bool = False,
    writable: bool = False,
    timeout: float = DEFAULT_TIMEOUT,
    windowed: bool = True,
    mod: str | Path | Sequence[str | Path] | None = None,
    engine_args: Sequence[str] = (),
) -> Iterator[Session]:
    """Install a map folder into the user files, start it there, and clean up afterwards.

    **This is the only way to start a map its own mod refuses to list as multiplayer.** The
    `-file` gate reads that flag out of the map cache, and for a mod's own maps the cache is the
    mod's hand-written `maps\\mapcache.ini` - where every War of the Ring map says `no`. The
    engine caches maps in the user folder itself, deriving the flag from the map, and for those
    same maps it derives yes. `sage_live.launch.runner.install_map_folder` has the rest, `extras`
    included - a `map.ini`'s relative includes have to be copied along with it or the load stops
    on an error box that reads exactly like a broken ini.

    What this costs in fidelity: the map under test is the copy, so it is whatever is in `source`
    rather than whatever the engine would otherwise have loaded. That is a real difference when
    the tree and the archives disagree, and the caller chooses `source` knowing which it wants.
    """
    install = Path(install)
    game_dat = install / "game.dat"
    if not game_dat.is_file():
        raise EngineUnavailable(f"no game.dat in {install}")

    game_info = _game_info(seats, settings)
    installed = install_map_folder(source, name=name, extras=extras)
    process = launch(
        installed.argument,
        game_dat,
        game_info=game_info,
        mod=mod,
        windowed=windowed,
        extra=tuple(engine_args),
    )
    session = None
    try:
        session = _await_session(process, timeout, writable)
        yield session
    finally:
        if session is not None:
            session.close()
        process.kill()
        if not keep_map:
            for path in installed.created:
                shutil.rmtree(path, ignore_errors=True)


@contextmanager
def run_scenario(
    scenario: Scenario,
    install: str | Path,
    template: str,
    *,
    settings: LobbySettings | None = None,
    writable: bool = False,
    timeout: float = DEFAULT_TIMEOUT,
    keep_map: bool = False,
    tolerance: float = DEFAULT_TOLERANCE,
    windowed: bool = True,
    mod: str | Path | Sequence[str | Path] | None = None,
    engine_args: Sequence[str] = (),
) -> Iterator[Match]:
    """Bring `scenario` up as a running match, and take it down again afterwards.

    `writable` asks for an ordering session, which needs the `live-bridge` patch; leave it False
    for a scenario that only observes.

    **The scenario's seats are the match.** They travel as `-gameInfo`, so a scenario that places
    objects for `Player_3` also seats someone at start position 2. `settings` carries the rest of
    the lobby - starting resources, the rules list, the seed.

    `mod` runs the game against an uncompiled mod tree (`-mod`), so a test exercises the ini as
    it is on disk rather than as it was last built into `.big` archives. That is the difference
    between a suite that guards a release and one you can run against the edit you just made.

    `engine_args` go on the end of the command line as they are - `("-renderEvery", "0")` for a
    run that does not draw, which needs the `headless` patch.

    **The teardown is the point.** Whatever happens in the body - a failed assertion, a timeout,
    a keyboard interrupt - the process is killed and the generated map removed, because the next
    scenario cannot start while this one is still holding the engine's single-instance guard.
    """
    install = Path(install)
    game_dat = install / "game.dat"
    if not game_dat.is_file():
        raise EngineUnavailable(f"no game.dat in {install}")

    # Before anything is written, so a scenario the lobby parser would reject fails here with the
    # seat named, rather than leaving a generated map behind.
    game_info = _game_info(scenario.seats, settings)
    parsed = parse_map(io.BytesIO(read_template(install, template)))
    compile_into(scenario, parsed)
    # Uncompressed: the engine reads either, and compressing a five-megabyte map in pure Python
    # costs far more than the launch it would be shortening.
    map_path, file_argument = install_map(scenario.name, write_map(parsed, compress=False))
    try:
        map_ini = write_map_ini(scenario, map_path.parent)
        problems = check_map_ini(map_ini) if map_ini is not None else []
        if problems:
            raise MapIniError(f"{scenario.name}'s map.ini would not load:\n" + "\n".join(problems))
    except BaseException:
        if not keep_map:
            shutil.rmtree(map_path.parent, ignore_errors=True)
        raise

    process = launch(
        file_argument,
        game_dat,
        game_info=game_info,
        mod=mod,
        windowed=windowed,
        extra=tuple(engine_args),
    )
    session = None
    match = None
    try:
        session = _await_session(process, timeout, writable)
        match = Match(
            scenario, session, bind_handles(scenario, session.observe(), tolerance), process.pid
        )
        yield match
    finally:
        if match is not None:
            match.close()
        if session is not None:
            session.close()
        process.kill()
        if not keep_map:
            shutil.rmtree(map_path.parent, ignore_errors=True)
