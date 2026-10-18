"""A pytest plugin for running scenarios against the real engine.

Enable it from a `conftest.py` with::

    pytest_plugins = ["sage_test.plugin"]

and write a scenario as a **class- or module-scoped fixture**, not a function-scoped one::

    @pytest.fixture(scope="class")
    def edict(scenario_runner):
        with scenario_runner(build_scenario(), writable=True) as match:
            yield match

**The scope is the whole design.** There is no scripted reset in this engine, so a scenario costs
a full launch - about thirty seconds to frame 1. A function-scoped fixture pays that per assertion
and a five-assertion file takes three minutes; a class-scoped one pays it once and still reports
five named failures. Grouping by *scenario* rather than by *assertion* is what makes engine tests
affordable, and it is why this plugin offers a runner rather than a `match` fixture.

**Nothing runs without `--install`.** A bare `pytest` in a mod's repository must never open a game
window on somebody, so the `install` fixture skips when the option is absent and every scenario
fixture depends on it.

**`--mod` runs against the files you are editing.** Without it the engine loads a mod from its
built `.big` archives, so a suite would be testing the last release rather than the working tree.
Point it at the folder holding `data/ini` and the ini on disk is what the test exercises.

**One game at a time, per process.** The engine refuses to start a second copy of itself unless
`multi-instance` is applied, so scenarios are serial by nature: each fixture's `with` block ends -
killing the process - before the next class begins. With that patch, `--shard K/N` runs the K-th
of N slices of the suite, and N pytest processes with one slice each run N games side by side.
Each needs its own map names, which the runners handle by suffixing the shard (or, under
`pytest-xdist`, the worker id). The suite is sliced by **test class, or module for a test outside
a class** - the scope a scenario fixture lives at - so one scenario is never launched in two
processes. `pytest-xdist` with `--dist loadscope` groups the same way, and works too.

**`--headless` stops the games drawing.** Each launch gets `-renderEvery 0`, which needs the
`headless` patch: the window still opens and the match simulates exactly as before, at the same
capped rate, but no frame is drawn - which is most of what several copies at once would cost.
`-headless` itself is not used because it also uncaps the loop, and a match running faster than
the suite polls it can step over a state a test is waiting to see.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager
from pathlib import Path

import pytest

from sage_live.launch.game_info import LobbySettings
from sage_test.run import (
    DEFAULT_TIMEOUT,
    EngineUnavailable,
    run_map,
    run_scenario,
    run_user_map,
)
from sage_test.scenario import Scenario, Seat

__all__ = [
    "MapRunner",
    "ScenarioRunner",
    "install",
    "map_runner",
    "scenario_runner",
    "user_map_runner",
]

#: The shipped multiplayer map scenarios are compiled onto unless a test says otherwise. It
#: brings terrain, eight start positions and the castle plots; a scenario only adds objects.
DEFAULT_TEMPLATE = "maps\\map mp harlindon\\map mp harlindon.map"

ScenarioRunner = Callable[..., AbstractContextManager]
MapRunner = Callable[..., AbstractContextManager]


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("sage_test", "system tests against a running BFME2/RotWK engine")
    group.addoption(
        "--install",
        action="store",
        default=None,
        metavar="DIR",
        help="RotWK install holding a game.dat patched with command-line-skirmish. Without it, "
        "every engine test is skipped and no game is ever launched",
    )
    group.addoption(
        "--map-template",
        action="store",
        default=DEFAULT_TEMPLATE,
        metavar="NAME",
        help=f"the shipped map scenarios are compiled onto (default: {DEFAULT_TEMPLATE})",
    )
    group.addoption(
        "--mod",
        action="store",
        default=None,
        metavar="DIR",
        help="run against an uncompiled mod tree (the folder holding data/ini) instead of its "
        "built .big archives, so tests exercise the files you are editing",
    )
    group.addoption(
        "--keep-maps",
        action="store_true",
        help="leave generated maps in the game's map folder instead of removing them, so a "
        "failing scenario can be opened in WorldBuilder",
    )

    group.addoption(
        "--headless",
        action="store_true",
        help="launch every game with -renderEvery 0, so it simulates without drawing. Needs the "
        "headless patch on game.dat",
    )
    group.addoption(
        "--shard",
        action="store",
        default=None,
        metavar="K/N",
        help="run only the K-th of N slices of the suite (1-based), sliced by test class, so N "
        "processes run N games at once. Needs the multi-instance patch on game.dat",
    )


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "engine: needs a real game; skipped unless --install names an install",
    )
    _shard(config)  # a malformed --shard fails here, before anything is collected


def _shard(config: pytest.Config) -> tuple[int, int] | None:
    """`--shard` as (K, N), 1 <= K <= N, or None when the whole suite runs in this process."""
    given = config.getoption("--shard")
    if given is None:
        return None
    try:
        index, count = (int(part) for part in given.split("/"))
    except ValueError:
        raise pytest.UsageError(f"--shard takes K/N, as in 2/4 - not {given!r}") from None
    if not 1 <= index <= count:
        raise pytest.UsageError(f"--shard {given}: K has to be between 1 and N")
    return index, count


#: Fixture scopes wide enough that every test sharing one of their parameter values shares one
#: game: a shard must keep them together, or the scenario is launched in two processes.
_SHARED_SCOPES = frozenset({"class", "module", "package", "session"})


def _scope(item: pytest.Item) -> str:
    """The unit a shard takes whole: the scenario fixture's node - the item's class, else its
    module - and, when a class- or module-scoped fixture is parametrized, which of its values
    the item runs with.

    Without the parameter a class that runs one scenario per unit (`params=UNITS` on its scenario
    fixture) is a single unit of work, and the whole parametrized class lands in one shard however
    many there are. Function-scoped parameters are left out: every value of those runs in the same
    game, so splitting on them would launch it twice."""
    node = item.getparent(pytest.Class) or item.getparent(pytest.Module)
    key = node.nodeid if node is not None else item.nodeid
    callspec = getattr(item, "callspec", None)
    if callspec is None:
        return key
    definitions = item._fixtureinfo.name2fixturedefs  # noqa: SLF001 - pytest's own record of scopes
    shared = sorted(
        f"{name}={callspec.indices[name]}"
        for name in callspec.params
        if name in definitions and definitions[name][-1].scope in _SHARED_SCOPES
    )
    return f"{key}[{','.join(shared)}]" if shared else key


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Under `--shard`, keep only this shard's scopes, dealt round-robin in collection order.

    Collection order is the same in every process given the same arguments, so the N shards
    partition the suite between them without having to talk to each other.
    """
    shard = _shard(config)
    if shard is None:
        return
    index, count = shard
    scopes = list(dict.fromkeys(_scope(item) for item in items))
    mine = set(scopes[index - 1 :: count])
    deselected = [item for item in items if _scope(item) not in mine]
    if deselected:
        config.hook.pytest_deselected(items=deselected)
        items[:] = [item for item in items if _scope(item) in mine]


def _worker_id(config: pytest.Config) -> str:
    """This process's name among several, or `master` when it is the only one.

    `--shard K/N` makes it `shardK`; under xdist it is the worker id, read from the environment
    rather than the `worker_id` fixture so the plugin does not require `pytest-xdist` at all.
    """
    shard = _shard(config)
    if shard is not None and shard[1] > 1:
        return f"shard{shard[0]}"
    return os.environ.get("PYTEST_XDIST_WORKER", "master")


def _engine_args(config: pytest.Config) -> tuple[str, ...]:
    """What every launch adds to the command line for the options this run was given."""
    return ("-renderEvery", "0") if config.getoption("--headless") else ()


@pytest.fixture(scope="session")
def install(request: pytest.FixtureRequest) -> Path:
    """The game install to run against, or skip the test."""
    given = request.config.getoption("--install")
    if not given:
        pytest.skip("engine tests need --install <RotWK folder>")
    path = Path(given)
    if not (path / "game.dat").is_file():
        pytest.skip(f"no game.dat in {path}")
    return path


@pytest.fixture(scope="session")
def scenario_runner(install: Path, request: pytest.FixtureRequest) -> Iterator[ScenarioRunner]:
    """A callable that brings a scenario up as a running match.

    Returns the context manager rather than a `Match`, so the *caller's* fixture scope decides
    when the game dies::

        with scenario_runner(build_scenario(), writable=True) as match:
            yield match

    `writable=True` asks for an ordering session, which needs the `live-bridge` patch on top of
    `command-line-skirmish`; leave it off for a scenario that only observes.
    """
    template = request.config.getoption("--map-template")
    keep_map = bool(request.config.getoption("--keep-maps"))
    mod_tree = request.config.getoption("--mod")
    engine_args = _engine_args(request.config)
    worker = _worker_id(request.config)

    def run(
        scenario: Scenario,
        *,
        settings: LobbySettings | None = None,
        writable: bool = False,
        timeout: float = DEFAULT_TIMEOUT,
        template_name: str | None = None,
        windowed: bool = True,
        mod: str | None = None,
    ) -> AbstractContextManager:
        # Generated maps share one folder across workers, so the name carries the worker id.
        named = scenario if worker == "master" else scenario.with_name(f"{scenario.name}_{worker}")
        return run_scenario(
            named,
            install,
            template_name or template,
            settings=settings,
            writable=writable,
            timeout=timeout,
            keep_map=keep_map,
            windowed=windowed,
            mod=mod or mod_tree,
            engine_args=engine_args,
        )

    yield run


@pytest.fixture(scope="session")
def map_runner(install: Path, request: pytest.FixtureRequest) -> Iterator[MapRunner]:
    """A callable that starts a map the mod already ships, and yields the running game.

    The counterpart to `scenario_runner` for the one thing a scenario cannot reach: a shipped
    map's own `map.ini`, which the engine loads from the map's folder and which therefore never
    travels with a generated copy. Nothing is compiled and nothing is written - the map under
    test is the one on disk::

        with map_runner(entry.argument) as session:
            assert session.observe().in_match

    Takes the `-file` argument, which is not a path; `sage_live.launch.maps.MapEntry.argument` is
    what produces it. `--mod` applies here exactly as it does to scenarios, and is what makes the
    run exercise the map.ini in the working tree rather than the last release's.
    """
    mod_tree = request.config.getoption("--mod")
    engine_args = _engine_args(request.config)

    def run(
        argument: str,
        *,
        seats: tuple[Seat, ...] = (),
        settings: LobbySettings | None = None,
        writable: bool = False,
        timeout: float = DEFAULT_TIMEOUT,
        windowed: bool = True,
        mod: str | None = None,
    ) -> AbstractContextManager:
        return run_map(
            argument,
            install,
            seats=seats,
            settings=settings,
            writable=writable,
            timeout=timeout,
            windowed=windowed,
            mod=mod or mod_tree,
            engine_args=engine_args,
        )

    yield run


@pytest.fixture(scope="session")
def user_map_runner(install: Path, request: pytest.FixtureRequest) -> Iterator[MapRunner]:
    """A callable that installs a map folder into the user files and starts it there.

    For the maps `map_runner` cannot reach: the `-file` gate refuses any cache entry a mod flags
    `isMultiplayer = no`, and the engine caches maps in the user folder itself rather than from
    that list. `sage_test.run.run_user_map` says what that costs and what `extras` is for::

        with user_map_runner(tree / "maps" / name, extras=(tree / "maps" / "_inis",)) as session:
            assert session.observe().in_match

    `--keep-maps` leaves the installed copy behind, exactly as it does for a scenario's map.
    Under `--shard` the copy's name carries the shard, as a scenario's does, so two processes
    installing the same map do not write over and then delete each other's.
    """
    keep_map = bool(request.config.getoption("--keep-maps"))
    mod_tree = request.config.getoption("--mod")
    engine_args = _engine_args(request.config)
    worker = _worker_id(request.config)

    def run(
        source: str | Path,
        *,
        name: str | None = None,
        extras: tuple[str | Path, ...] = (),
        seats: tuple[Seat, ...] = (),
        settings: LobbySettings | None = None,
        writable: bool = False,
        timeout: float = DEFAULT_TIMEOUT,
        windowed: bool = True,
        mod: str | None = None,
    ) -> AbstractContextManager:
        if worker != "master":
            name = f"{name or Path(source).name}_{worker}"
        return run_user_map(
            source,
            install,
            name=name,
            extras=extras,
            seats=seats,
            settings=settings,
            keep_map=keep_map,
            writable=writable,
            timeout=timeout,
            windowed=windowed,
            mod=mod or mod_tree,
            engine_args=engine_args,
        )

    yield run


@pytest.fixture
def engine_unavailable() -> type[EngineUnavailable]:
    """The exception a scenario raises when the game could not be brought up, for tests that
    want to assert on the failure rather than suffer it."""
    return EngineUnavailable
