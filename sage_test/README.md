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

One module per stage:

```
Scenario  ->  a generated .map  ->  a launched game  ->  a bound Match
scenario.py   compile.py           runner.py            harness.py
```

## Why a scenario is static

`place()` creates nothing. A scenario is compiled into a `.map` before the engine starts, using
ordinary WorldBuilder object properties (`objectExperienceLevel`, `objectUpgradesList`,
`originalOwner`). So it is legal map data, not an injected cheat: no desync risk, and the map opens
in WorldBuilder. `place()` returns a `Handle`; once the match is up, `harness.bind_handles` ties it to
the live object of that template nearest where it was placed.

| module | needs | what it does |
|---|---|---|
| `scenario` | nothing | the declaration: seats, placements, handles |
| `compile` | `sage_map` | appends the placements to a template map's object list |
| `runner` | a game install | writes the map where the engine looks, and launches |
| `harness` | `sage_live` + a running game | binds handles; a `Session` for everything else |
| `maps` | nothing | reads the engine's map cache: which maps can be started, and their names |

`scenario` imports no game data, `sage_map` or Windows-only code, so declarations can be checked
anywhere, including the data-free core suite.

## Three engine rules it gets right

Each fails silently when wrong; see [`sage_patch/docs/game-info.md`](../sage_patch/docs/game-info.md).

- **A seat binds to `Player_<start_position + 1>`**, not its index in the seat list;
  `Seat.map_team` is the name to write into `originalOwner`.
- **Generated maps live in `My Rise of the Witch-king Files\Maps`** as `Maps\<name>\<name>.map`, keyed
  by absolute lowercased path (maps inside `.big` archives are keyed relatively).
- **`-file` names the parent, not the file**: the engine inserts the map's stem as a folder, so
  `...\Maps\<name>.map` resolves to `...\maps\<name>\<name>.map`. `runner.install_map` returns the
  right argument.

## Requirements

A game install whose `game.dat` carries **`command-line-skirmish`** ([`sage_patch`](../sage_patch)).
Without it, `-file` skips the menus but configures no match and dies before frame 1. The patched
binary must be the install's own `game.dat` under that name: under any other name it dies inside
`msvcr71.dll`.

## Running scenarios from pytest

Enable the plugin from a `conftest.py`:

```python
pytest_plugins = ["sage_test.plugin"]
```

It adds `--install`, `--mod`, `--map-template` and `--keep-maps`, and the fixtures `install` (skips
without `--install`, so a bare `pytest` never launches a game), `scenario_runner` and `map_runner`.

Make a scenario **class- or module-scoped**, never function-scoped:

```python
@pytest.fixture(scope="class")
def world(scenario_runner):
    with scenario_runner(build_scenario(), writable=True) as match:
        yield match
```

A launch takes about thirty seconds and there is no scripted reset, so function scope pays that per
assertion. The runner returns a context manager so the fixture's scope decides when the game exits;
the engine refuses to start a second copy, so a leaked game breaks every later scenario.

`--mod <tree>` runs against an uncompiled mod tree (the folder holding `data/ini`), so a test
exercises the ini being edited rather than the last release. Loading is slower, which is why casts
are confirmed by retry (`Match.cast_and_confirm`). Outside pytest, use
`sage_test.run.run_scenario`.

## Choosing the match

A scenario's seats are the match. `run_scenario` turns them into a `-gameInfo` lobby string, which
`command-line-skirmish` hands to the engine's own lobby parser: factions, AI difficulty, teams,
colours, start positions, starting resources and seed.

```python
from sage_live.launch.game_info import LobbySettings

scenario = Scenario("siege", seats=(
    Seat.human(faction=3, start_position=0, team=0),
    Seat.computer(faction=10, difficulty="brutal", start_position=1, team=1),
    Seat.computer(faction=12, difficulty="hard", start_position=2, team=1),
))
with run_scenario(scenario, install, template, settings=LobbySettings(seed=42)) as match:
    ...
```

`run_map` and `run_user_map` take `seats=` and `settings=` too; without them the patch starts a
default two-seat match. `sage_live.launch.game_info.game_info_string` builds the string for other
launchers.

The engine's parser is all or nothing and silently falls back to the default match on a refusal, so
`game_info_string` rejects up front what it would refuse: anything but exactly one human, a shared or
out-of-range start position, a random faction or colour, or a team outside -1..3. Not yet run in a
game: the parser's contract is read from the disassembly and tested under an emulator
(`game-info.md` section 7).

## Starting a map that already exists

A generated map never carries a shipped map's own `map.ini`, so to test that data, start the map
where it lives with `run_map` (or the `map_runner` fixture): no compile, nothing written.

```python
@pytest.mark.engine
def test_the_map_loads(map_entry, map_runner):
    with map_runner(map_entry.argument) as session:
        assert session.observe().in_match
```

`-file` starts a map-cache entry, not a folder, and the cache comes from `maps\mapcache.ini`.
`sage_live.launch.maps` reads it:

```python
from sage_test import load_map_cache

for entry in load_map_cache(install=r"C:\RotWK", mod="./_mod"):
    print(entry.name, entry.is_multiplayer, entry.argument)
```

A folder the cache does not name cannot be started, and an `isMultiplayer = no` entry crashes the
auto-start, so suites skip those. `MapEntry.argument` is the `-file` spelling, which is not the
path. A fatal `map.ini` error shows a message box rather than exiting, so it surfaces as the launch
timeout.

## Status

Proven end to end from both a script and pytest: Edain's suite runs five assertions against one
31-second launch and leaves no process or map behind, and `run_map` reaches a running match on
`map mp harlindon` (and times out, as expected, with a broken `map.ini`).

Not built yet: parallel runs. They need the `multi-instance` patch and worker-suffixed map names,
which the plugin writes but nothing has exercised.
