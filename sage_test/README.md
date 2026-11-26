# sage_test

System tests for BFME2 / RotWK that run against the **real engine**: declare a match, start it,
and assert on what the game actually did.

```python
scenario = Scenario("edict", seats=(Seat.human(faction=12), Seat.easy_ai(faction=10)))
hero = scenario.place(
    "AngmarMorgramir",
    at=(4180, 2500, 0),
    level=7,
    upgrades=tuple(f"Upgrade_Level_{n}" for n in range(1, 8)),
)
hall = scenario.place("AngmarBarracks", at=(4300, 2500, 0))

with run_scenario(scenario, install, template, writable=True) as match:
    match.session.select([match.id_of(hero)])
    time.sleep(2.0)  # a cast ordered sooner is discarded in silence
    match.session.cast(
        "SpecialAbilitySchergendesGrossorks",
        form=CAST_LOCATION,
        position=match[hall].position,
        source_id=match.id_of(hero),
    )
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
| `script_compile` | `sage_map` + `sage_worldbuilder` | writes a scenario's scripts, waypoints and trigger areas into the map |
| `scripts` | a running game | `Match.scripts`: fires a scenario's scripts and reads their counts |
| `runner` | a game install | writes the map where the engine looks, and launches |
| `harness` | `sage_live` + a running game | binds handles; a `Session` for everything else |
| `maps` | nothing | reads the engine's map cache: which maps can be started, and their names |
| `mission` | `sage_worldbuilder.live` + a running game | campaign missions: carryover, the script watch, objectives, the skirmish defeat hold |
| `mission_record` | the same | records a mission's opening frame by frame, and diffs two recordings |
| `perf` | nothing | army layouts, the median centre a camera follows, a JSON-lines log |
| `pace`, `camera` | a running game | frame-rate sampling; a camera that follows a moving army |
| `accelerator`, `options` | an install | settings for one launch, put back afterwards |
| `window`, `process` | Windows | the game's window (focus, Alt+Tab, capture); its address space |

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

A test of something a `sage_patch` patch adds says so with `@pytest.mark.needs_patch("name")`,
and is skipped - before any game launches - when the install's `game.dat` lacks it.

It adds `--install`, `--mod`, `--map-template`, `--keep-maps`, `--headless` and `--shard`, and the fixtures `install` (skips
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

`--headless` launches every game with `-renderEvery 0` (the `headless` patch): it simulates at the
usual capped rate and draws nothing. Not `-headless`, which also uncaps the loop and can step a
match past a state the suite is polling for.

`--shard K/N` runs the K-th of N slices of the suite, dealt round-robin by test class (or module,
for a test outside a class), so N pytest processes run N games at once without launching any
scenario twice. It needs the `multi-instance` patch; generated and user-installed maps carry the
shard in their names so the processes do not share files. `pytest-xdist -n N --dist loadscope`
slices the same way and also works; sharding exists because a frozen app cannot start xdist's
`python -c` workers.

```sh
for k in 1 2 3; do pytest tests --install "$ROTWK" --mod _mod --headless --shard $k/3 & done; wait
```

## Choosing the match

A scenario's seats are the match. `run_scenario` turns them into a `-gameInfo` lobby string, which
`command-line-skirmish` hands to the engine's own lobby parser: factions, AI difficulty, teams,
colours, start positions, starting resources and seed.

```python
from sage_live.launch.game_info import LobbySettings

scenario = Scenario(
    "siege",
    seats=(
        Seat.human(faction=3, start_position=0, team=0),
        Seat.computer(faction=10, difficulty="brutal", start_position=1, team=1),
        Seat.computer(faction=12, difficulty="hard", start_position=2, team=1),
    ),
)
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

## Per-test ini overrides

A scenario can bring its own `map.ini`. It is written beside the generated map, and the engine loads
it on top of the mod's ini, so a test can change an Object without touching the mod:

```python
scenario.override("""
    Object EntEntling
        AddModule ModuleTag_WallMelee
            Behavior = WeaponSetUpgrade ModuleTag_WallMelee
                TriggeredBy = Upgrade_Test
            End
        End
    End
""", shared_inis_folder)  # optional: files or folders the override #includes
```

- The engine reads the file once, when the map loads. Changing it means another launch.
- It is an override file, so a new module on an existing Object must be wrapped in `AddModule`.
- Before launch, `check_map_ini` parses the file and runs `sage_lint`'s `map-bare-module` rule. A
  problem raises `MapIniError` with the file and line, instead of an engine error box that a test
  would only see as a timeout. References to definitions elsewhere in the mod are not checked.
- An `#include` resolves from the user-maps folder, not from the mod tree, so pass what it names
  as an include to have it copied there.
- `--keep-maps` keeps the `map.ini` with the map.

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

## Map scripts

A scenario can add map scripts, so the engine itself spawns, kills or transfers something at the
moment a test chooses, or reports a condition only it can judge. Actions and conditions are
named the way WorldBuilder names them internally; the arguments are checked against the template
when the map is compiled, before anything launches.

```python
from sage_test import act, cond

scenario.place("GondorRanger", at=(1500, 1500, 0), name="TestScout")
scenario.area("Yard", rect=((1650, 1650), (1750, 1750)))
scenario.script("wave", act("CREATE_OBJECT", "MordorOrc", "Player_2/teamPlayer_2", (1400, 1700), 0))
scenario.probe("scout_in_yard", cond("NAMED_INSIDE_AREA", "TestScout", "Yard"))

with run_scenario(scenario, install, template, writable=True) as match:
    match.scripts.run("wave")                       # fire it, and wait until it has run
    assert match.scripts.count("scout_in_yard") == 0
```

- **`script`** declares a trigger: written switched off, it runs once each time the test fires
  it (and its `when=` conditions hold, if it has any).
- **`probe`** declares a script that is switched on from the start and counts each time its
  conditions held. `any_of(a, (b, c))` ORs clauses.
- Every script ends by raising the counter `sage_test.<name>`. That counter is how `run` and
  `wait_fired` know the actions ran, and its value is `count`.
- Scripts go into a `sage_test` group on the neutral side, or `side=` a seat index or side name.
  `waypoint` and `area` declare the names scripts refer to.

Firing writes the script's active flag and next-evaluation frame. No code is patched, so it
works with the accelerator loaded. A network game is refused. The arguments are fixed when the
map is compiled: declare one script per variant, or hand a number in through
`match.scripts.set_counter`. The design is in [`docs/scenario-scripts.md`](../docs/scenario-scripts.md).

## Status

Proven end to end from both a script and pytest: Edain's suite runs five assertions against one
31-second launch and leaves no process or map behind, and `run_map` reaches a running match on
`map mp harlindon` (and times out, as expected, with a broken `map.ini`).

Parallel runs (`--shard`, `--headless`) are built and unit-tested, but have not yet been run against
the real engine with several games at once.
