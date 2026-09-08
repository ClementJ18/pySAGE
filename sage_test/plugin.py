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

**One game at a time.** The engine refuses to start a second copy of itself unless `multi-instance`
is applied, so scenarios are serial by nature: each fixture's `with` block ends - killing the
process - before the next class begins. Under `pytest-xdist` each worker needs both that patch and
its own map name, which the runner handles by suffixing the worker id.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager
from pathlib import Path

import pytest

from sage_test.run import (
    DEFAULT_TIMEOUT,
    EngineUnavailable,
    run_map,
    run_scenario,
    run_user_map,
)
from sage_test.scenario import Scenario

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


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "engine: needs a real game; skipped unless --install names an install",
    )


def _worker_id() -> str:
    """This xdist worker, or `master` when running single-process.

    Read from the environment rather than the `worker_id` fixture so the plugin does not require
    `pytest-xdist` to be installed at all.
    """
    return os.environ.get("PYTEST_XDIST_WORKER", "master")


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
    worker = _worker_id()

    def run(
        scenario: Scenario,
        *,
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
            writable=writable,
            timeout=timeout,
            keep_map=keep_map,
            windowed=windowed,
            mod=mod or mod_tree,
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

    Takes the `-file` argument, which is not a path; `sage_test.maps.MapEntry.argument` is what
    produces it. `--mod` applies here exactly as it does to scenarios, and is what makes the run
    exercise the map.ini in the working tree rather than the last release's.
    """
    mod_tree = request.config.getoption("--mod")

    def run(
        argument: str,
        *,
        writable: bool = False,
        timeout: float = DEFAULT_TIMEOUT,
        windowed: bool = True,
        mod: str | None = None,
    ) -> AbstractContextManager:
        return run_map(
            argument,
            install,
            writable=writable,
            timeout=timeout,
            windowed=windowed,
            mod=mod or mod_tree,
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
    """
    keep_map = bool(request.config.getoption("--keep-maps"))
    mod_tree = request.config.getoption("--mod")

    def run(
        source: str | Path,
        *,
        name: str | None = None,
        extras: tuple[str | Path, ...] = (),
        writable: bool = False,
        timeout: float = DEFAULT_TIMEOUT,
        windowed: bool = True,
        mod: str | None = None,
    ) -> AbstractContextManager:
        return run_user_map(
            source,
            install,
            name=name,
            extras=extras,
            keep_map=keep_map,
            writable=writable,
            timeout=timeout,
            windowed=windowed,
            mod=mod or mod_tree,
        )

    yield run


@pytest.fixture
def engine_unavailable() -> type[EngineUnavailable]:
    """The exception a scenario raises when the game could not be brought up, for tests that
    want to assert on the failure rather than suffer it."""
    return EngineUnavailable
