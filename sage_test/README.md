# sage_test

System tests for BFME2 / RotWK that run against the **real engine**: declare a match, start it,
and assert on what the game actually did.

```python
scenario = Scenario("edict", seats=(Seat.human(faction=12), Seat.easy_ai(faction=10)))
hero = scenario.place("AngmarMorgramir", at=(4180, 2500, 0), level=7,
                      upgrades=tuple(f"Upgrade_Level_{n}" for n in range(1, 8)))
hall = scenario.place("AngmarBarracks", at=(4300, 2500, 0))

with run_scenario(scenario, install, template, writable=True) as match:
    match.session.select([match.id_of(hero)])
    time.sleep(2.0)                       # a cast ordered sooner is discarded in silence
    match.session.cast("SpecialAbilitySchergendesGrossorks", form=CAST_LOCATION,
                       position=match[hall].position, source_id=match.id_of(hero))
    match.wait_until(lambda m: "Upgrade_RaiseShield" in m[hall].upgrades)
```

The pipeline is one direction, one module per stage:

```
Scenario  ->  a generated .map  ->  a launched game  ->  a bound Match
scenario.py   compile.py           runner.py            harness.py
```

## Why a scenario is static

`place()` does not create anything. Everything a scenario declares is compiled into a `.map`
**before the engine starts**, because that is how you get a level-7 hero standing next to a
finished building without asking the engine to do something a player could not:
`objectExperienceLevel`, `objectUpgradesList` and `originalOwner` are ordinary WorldBuilder
object properties. A scenario is legal map data, not an injected cheat — no script injection, no
desync risk, and the map opens in WorldBuilder if you want to look at it.

So declaration and execution are separate phases, and `place()` returns a `Handle` naming an
object that does not exist yet. `harness.bind_handles` ties each handle to a live `ObjectId` once
the match is up, by finding the object of that template nearest where the scenario put it.

## What each module needs

Dependencies point one way, and only the first module is free of everything:

| module | needs | what it does |
|---|---|---|
| `scenario` | nothing | the declaration — seats, placements, handles |
| `compile` | `sage_map` | appends the placements to a template map's object list |
| `runner` | a game install | writes the map where the engine looks, and launches |
| `harness` | `sage_live` + a running game | binds handles, and is a `Session` for everything else |
| `maps` | nothing | reads the engine's map cache: which maps can be started, and how to spell them |

`scenario` imports no game data, no `sage_map` and nothing Windows-only, so a test's declaration
can be built and checked anywhere — which is what keeps the core test suite data-free.

## Three engine rules this package exists to get right

Each of these is silent when you get it wrong, and each is written up in
[`sage_patch/docs/game-info.md`](../sage_patch/docs/game-info.md).

**A seat binds to `Player_<start_position + 1>`.** Not to its index in the seat list. That is the
map-side player a scenario's objects must be owned by for the seat to own them, and `Seat.map_team`
is the qualified name to write into `originalOwner`.

**Generated maps live in `My Rise of the Witch-king Files\Maps`** — the RotWK user folder, not the
BFME2 one sitting next to it — as `Maps\<name>\<name>.map`, and the engine keys them there by
**absolute lowercased path**, while maps inside the `.big` archives are keyed relatively.

**The `-file` argument names the parent, not the file.** The engine inserts the map's own stem as
a directory, so `…\Maps\<name>.map` is what resolves to `…\maps\<name>\<name>.map`. Passing the
path that actually exists produces the folder twice, the cache lookup misses, and the game dies
several seconds later somewhere unrelated. `runner.install_map` returns the argument to use.

## Requirements

A game install, and a `game.dat` carrying **`command-line-skirmish`**
([`sage_patch`](../sage_patch/README.md)). Without that patch `-file` starts a game with a random
faction, no opponent and no starting resources, and dies before frame 1 — `-file` alone skips the
menus but does not configure a match.

The binary must also be the install's own `game.dat`, **under that name**: a section-modified
image run under any other filename dies immediately inside `msvcr71.dll`, so a patched build
cannot be copied aside and tried out.

## Running scenarios from pytest

`sage_test.plugin` is a pytest plugin. Enable it from a `conftest.py`:

```python
pytest_plugins = ["sage_test.plugin"]
```

It adds `--install`, `--mod`, `--map-template` and `--keep-maps`, and three fixtures: `install`
(which **skips** when `--install` is absent, so a bare `pytest` never launches a game),
`scenario_runner`, and `map_runner` for starting a map the mod already ships.

Write a scenario as a **class- or module-scoped** fixture, never function-scoped:

```python
@pytest.fixture(scope="class")
def world(scenario_runner):
    with scenario_runner(build_scenario(), writable=True) as match:
        yield match
```

The scope is the whole design. There is no scripted reset, so a scenario costs a full launch —
about thirty seconds to frame 1. Function scope pays that per assertion; class scope pays it once
and still reports each failure by name. The runner hands back a context manager rather than a
`Match` precisely so the caller's scope decides when the process dies — which matters because the
engine refuses to start a second copy of itself, so a leaked game turns every later scenario into
a failure with an unrelated-looking cause.

`--mod <tree>` runs the game against an **uncompiled** mod tree (the folder holding `data/ini`)
instead of its built `.big` archives, so a test exercises the ini you just edited rather than the
last release. That is the difference between a suite that guards a release and one you run while
working. Loading uncompiled files is slower, which is why casts are confirmed by retry rather than
by a fixed wait — see `Match.cast_and_confirm`.

`sage_test.run.run_scenario` is the same thing without pytest, for a script or a notebook.

## Starting a map that already exists

A scenario always runs on a *generated* map, and one thing does not travel with it: the map's own
`map.ini`. The engine loads that from the map's folder, so the only way to put a shipped map's
per-map data in front of the ini parser is to start that map where it lives. `run_map` (and the
`map_runner` fixture) does exactly that — no compile, no map written, nothing removed afterwards:

```python
@pytest.mark.engine
def test_the_map_loads(map_entry, map_runner):
    with map_runner(map_entry.argument) as session:
        assert session.observe().in_match
```

**Which maps exist is not a question about folders.** `-file` starts a *cache entry*, and
`TheMapCache` is built from `maps\mapcache.ini` — shipped inside the archives, hand-maintained in
some mods. `sage_test.maps` reads it:

```python
from sage_test import load_map_cache

for entry in load_map_cache(install=r"C:\RotWK", mod="./_mod"):
    print(entry.name, entry.is_multiplayer, entry.argument)
```

Two rules it exists to keep:

- **A folder the cache does not name cannot be started at all**, by any command line or menu.
- **`isMultiplayer = no` is refused by the auto-start** — it takes the silent failure branch and
  dies in `TheTerrainVisual` seconds later, so a suite skips those rather than reporting the
  engine's own gate as a crash.

`MapEntry.argument` is the `-file` spelling, which is *not* the path: see §1 of
[`game-info.md`](../sage_patch/docs/game-info.md) and the module docstring.

Edain's `tests/test_map_load.py` is the suite this was built for: one launch per multiplayer map,
asking only whether the engine reached a running match. A fatal `map.ini` error does not exit the
process — the engine raises a message box and waits — so that failure arrives as the launch
timeout, not as an exit code.

## Status

Proven end to end, from both a script and pytest. Edain's own suite
(`Edain-Mod/tests/test_edict_of_carn_dum.py`) runs five assertions against one launch in 31
seconds: a level 7 Mornamarth and a Hall of the King's Men are placed, bound, owned by the right
seat; the Edict is cast; the power goes on recharge within 0.1 s and the hall gains
`Upgrade_RaiseShield` at +3.0 s. The run leaves no process and no map behind.

`run_map` is proven the same way, both directions: `map mp harlindon` off an Edain install reaches
a running match in 36 s, and the same map with a deliberately broken `map.ini` overlaid through
`-mod` fails — by hanging on the engine's error box until the launch timeout, which is what that
failure looks like.

What is **not** built yet is parallelism. One scenario is one process because there is no scripted
reset, and the engine refuses a second copy of itself without the `multi-instance` patch — so
`pytest-xdist` needs that patch applied and a worker-suffixed map name, which the plugin already
writes but nothing has yet exercised.
