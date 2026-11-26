# Scenario scripts: map scripts in `sage_test` engine tests

Design, 2026-11-14. **Slices 2-4 are built and unit-tested** (`sage_test/script_compile.py`,
`sage_test/scripts.py`, Edain `tests/utils/scripts.py`); **slice 1, the first live run, has not
been done**, so "the engine clears a fired trigger's flag and the counter appears" is still the
spike's reading, not a test result. It adds map scripts to `sage_test` scenarios, so
an engine test can make the engine itself spawn, kill, transfer, reveal or check something,
whenever the test chooses.

## 1. What it is for

A test today can place objects before the match (`Scenario.place`) and give orders a player
could give (`Session`). Some of what tests need fits neither:

- **Mid-match world changes.** Spawn a wave at frame N, kill a unit, change an owner, give
  money, set the time of day, reveal the map, stop an AI.
- **Engine-side checks.** "Unit X is inside area A", "player has built Y", "unit is in model
  condition Z": WorldBuilder's conditions already evaluate these exactly as the game does.
- **Mission logic.** A cut-down copy of a mission script can run on the plain test map without
  loading the whole mission.

## 2. Constraints that decide the design

| fact | consequence |
|---|---|
| `bfme2_accel.dll` hooks `0x006325C4` (the frame-gate site), but only when `[Engine] LogicHz` is set. The engine-test launch sets it to 0, and since 2026-11-14 the gate chains onto the accelerator's hook anyway. | `FrameGate.command` ("run actions now") works in engine tests too. It still needs a code hook and a cave, so the byte-write trigger below stays the main path, with run-now as the extra (§7). |
| A scenario is compiled before launch (`compile.py`). | Scripts are declared and compiled the same way as placements, so the generated map still opens in WorldBuilder. |
| `Script+0x40` (`SCRIPT_ACTIVE`) is the live enabled flag the due check reads. A one-shot clears it when it fires (spike 1, `script-debugger.md` §6). | **Firing a script = writing one byte.** No hook or cave, so it works with the accelerator. |
| A counter or flag exists only once a script has touched it (`script-debugger.md` §4). | Every compiled script ends with an action that bumps its own counter. Reading that counter confirms the script ran and counts its runs. |
| A skirmish is not recorded, and engine tests run single-player. | The desync rules in `script-action-injection.md` §4 do not apply. `Match.scripts` still refuses a network game, using the same check as the gate. |
| `tests/data/test.map` (Edain) has 18 empty script lists: `''`, `PlyrCivilian`, `PlyrCreeps`, 12 `Skirmish*`, `Player_1`..`Player_4`. | Nothing is in the way. Scripts are added per scenario at compile time; test.map stays a plain map. |
| `sage_worldbuilder.scripting` / `.templates` hold the template catalogue and item builders, and import no Qt. | No new script model is needed. Scripts are authored by WorldBuilder internal names (`CREATE_OBJECT`, `NAMED_INSIDE_AREA`, ...). |

## 3. The shape

```
declare                      compile                         drive
Scenario.script(...)   ->    PlayerScriptsList entries  ->   match.scripts.fire("wave")
Scenario.probe(...)          (+ waypoints, trigger areas)    match.scripts.wait_fired("wave")
Scenario.waypoint/area(...)                                  match.scripts.count("entered")
scenario.py (data only)      compile.py (+ script_compile)   harness.py (+ scripts.py)
```

### 3.1 Declaring

```python
from sage_test.scenario import Scenario, Seat, act, cond

scenario = Scenario("wave", seats=(Seat.human(faction=3), Seat.easy_ai(faction=10)))
gate = scenario.place("GondorGate", at=(1700, 1700, 0), name="TestGate")
scenario.waypoint("WaveSpawn", at=(1400, 1700, 0))
scenario.area("GateYard", rect=((1650, 1650), (1750, 1750)))

# A trigger: compiled switched off; runs once each time the test fires it.
scenario.script(
    "wave",
    act("CREATE_OBJECT", "MordorOrcWarriorHorde", "Player_2/teamPlayer_2", (1400, 1700, 0), 0.0),
    act("CREATE_OBJECT", "MordorOrcWarriorHorde", "Player_2/teamPlayer_2", (1400, 1750, 0), 0.0),
)

# A probe: switched on, with conditions; its counter records each time they held.
scout = scenario.place("GondorRanger", at=(1300, 1300, 0), name="TestScout")
scenario.probe("scout_at_gate", cond("NAMED_INSIDE_AREA", "TestScout", "GateYard"), once=True)
```

- `act(name, *args)` / `cond(name, *args, inverted=False)` hold only the internal name and the
  raw Python values. `scenario.py` therefore still imports nothing beyond what it does today.
- An OR of conditions is written `any_of(cond(...), cond(...))`. Several `cond`s passed
  side by side are ANDed, which is how the map format stores them.
- Arguments are converted from the template's `ParameterType` at compile time:
  `str` -> name types, `int`/`float`/`bool`, a 3-tuple -> `POSITION_COORDINATE`, and
  `"=="`/`"<"`/... -> `COMPARISON`.
  A wrong count or type raises in `compile`, naming the script, the item and the argument,
  before any game starts.
- `side=` picks the script list: `None` (default) is the neutral list `''`; a seat index picks
  `Seat.map_side` (`Player_<start+1>`); a string names any list. Use a seat when an action needs
  `<This Player>`.

### 3.2 Compiling (`sage_test/script_compile.py`, new)

Each `script()` becomes one `Script` inside a group `sage_test`, built with
`sage_worldbuilder.scripting.new_script` / `new_item`:

| | trigger (`script`) | probe (`probe`) |
|---|---|---|
| active | **no** | yes |
| one-shot | yes | `once` (default yes) |
| conditions | `CONDITION_TRUE` | as declared |
| true actions | as declared, then `INCREMENT_COUNTER 1 sage_test.<name>` | `INCREMENT_COUNTER 1 sage_test.<name>` (+ any declared) |
| delay | 0 (every frame) | `every=` seconds, default 0 |

Names are prefixed (`sage_test.<name>`) so they cannot clash with a template map's own scripts.
A repeat name raises.

`waypoint()` writes a `*Waypoints/Waypoint` object (`waypointName`, `waypointID`) through the
existing placement path. `area()` appends a `PolygonTrigger`. Scripts already reach named units
through `Placement.name` (`objectName`).

`compile_into` calls the script compiler after the placements. A scenario with no scripts writes
exactly what it writes today.

**Dependency.** This makes `compile` import `sage_worldbuilder.scripting` and `.templates`.
Both are Qt-free (checked). If the editor package is too heavy to sit under `sage_test`, move the
catalogue (`script_templates.json`, `templates.py`) and the four `new_*` builders into
`sage_map.scripts`, and have `sage_worldbuilder` re-export them. Recommended, but not needed for
slice 2.

### 3.3 Driving (`sage_test/scripts.py`, new; `Match.scripts`)

```python
with scenario_runner(scenario, writable=True) as match:
    match.scripts.fire("wave")                  # SCRIPT_ACTIVE = 1 (re-arms a fired one-shot)
    match.scripts.wait_fired("wave", timeout=5) # counter sage_test.wave went up by 1
    match.wait_until(lambda m: len(m.find("MordorOrcWarriorHorde")) == 2)
    assert match.scripts.count("scout_at_gate") == 0
```

| call | how |
|---|---|
| `fire(name)` | finds the `LiveScript` (`read_script_tree`, cached per match: the tree's addresses do not move after load), notes the counter, writes `SCRIPT_ACTIVE = 1`. A one-shot that has fired is re-armed first by writing its next-evaluation frame (`+0x3C`) to 0, as `script-debugger.md` §4 describes. |
| `wait_fired(name, timeout)` | polls `read_script_variables` until the counter is above the value `fire` noted. Times out with the script's live state and, if available, its condition verdicts (`read_script_conditions`). |
| `count(name)` | the counter, 0 while it does not exist yet. |
| `enable` / `disable(name)` | write `SCRIPT_ACTIVE`, for probes. |
| `set_flag` / `set_counter(name, v)` | write an existing variable (the `set_script_variable.py` path). This is the way to pass values into a script at run time (§5). |
| `fired_frames(name)` | only with the optional trace (§7). |

`fire` makes no assumption about timing. Under fast-forward the script runs on the next logic
pass, and `wait_fired` is the only sync point a test needs.

## 4. Edain: the test map and a script library

`tests/data/test.map` itself is **not** edited. It stays a flat, empty map, with test-specific
scripts arriving per scenario like placements. What the Edain suite adds:

- `tests/utils/scripts.py`: reusable declarations, all calling `scenario.script` or
  `scenario.probe`:
  `reveal_map(scenario)`, `stop_ai(scenario, seat)`, `give_money(scenario, seat, n)`,
  `spawn(scenario, template, seat, at, angle=0)`, `kill_named(scenario, name)`,
  `inside_area(scenario, unit_name, area)`. Each is a few lines, and later tests reuse them.
- A data-free core test (`tests/general/test_scenario_scripts_compile.py`) that builds every
  scenario the suite declares and compiles it against test.map without launching. A wrong
  argument then fails in seconds, not after a 30-second launch.
- Placements stay far from the starts (a citadel unpacking shoves anything near it), and so do
  spawn coordinates.

For **shipped maps** (`map_runner`, which writes nothing), scripts are not available on purpose:
that path exists to test the map as shipped. `user_map_runner` (missions) already copies the map
(`mission.prepare_map`) and can take a script list the same way, a later slice.

## 5. Limits, and what to do about them

- **Arguments are fixed at compile time.** The test chooses which script runs and when, not what
  it runs with. When a value is only known at run time:
  1. declare one script per variant (spawn at A / B / C);
  2. pass a number in through a counter: `set_counter("sage_test.wave_size", 3)`, and the
     script's conditions/loops read it;
  3. for a truly dynamic call, use the `.livebrg` action injection (`script-action-injection.md`,
     not built), or the frame gate with the accelerator off (§7).
- **Scope.** Untested: whether a `Player_N` list runs in skirmish for a seated slot, and with
  which scope. Spike 1 on linhir saw 5 live sides, so lists do load. The neutral list is the
  default until slice 1 answers this.
- **The gate condition is the engine's.** Scripts are evaluated at the engine's own cadence, so
  a probe sees what the engine sees, which is also when it sees it.

## 6. Failure modes the API must report clearly

| symptom | cause | report |
|---|---|---|
| `fire` raises "not in the live tree" | name typo, or the map was not the compiled one | list the `sage_test.*` scripts that are live |
| `wait_fired` times out, script still active | condition never true (a trigger's is `TRUE`, so the action list faulted or the side has no player) | live active/one-shot state + condition verdicts |
| counter rose but no effect | the action ran with wrong arguments (e.g. an unknown team) | name the action; suggest opening the generated map (`--keep-maps`) in WorldBuilder |
| game exits on load | malformed chunk | the compile round-trip unit test (slice 2) catches this offline |

## 7. Optional extras

- **Run now** without the bump: `FrameGate.command(RUN_TRUE_ACTIONS, ...)`. The gate chains onto
  the accelerator's logic-rate hook when it finds one, so this works with or without the
  accelerator. Useful for a template map's own scripts, which carry no counter.
- **Trace** (`script_trace`, as `ScriptWatch` uses it): exact frames per firing. Check first that
  its hooks coexist with the accelerator; they are on `executeScript`'s logger calls, not on
  `0x006325C4`.

## 8. Slices

| slice | what | done when |
|---|---|---|
| **1. Spike** | hand-build one inactive one-shot (`CREATE_OBJECT` + counter) into a copy of test.map, launch through the toolbar CLI, write `SCRIPT_ACTIVE` from a live script, then re-arm and fire again. Also put the same script on `Player_1` to answer the scope question. | the object appears twice, the counter reads 2 |
| **2. Declare + compile** | `act`/`cond`/`any_of`, `Scenario.script/probe/waypoint/area`, `script_compile.py`; unit tests: argument conversion, errors, `write_map` -> `parse_map` round trip, unchanged output with no scripts | core suite green, no game |
| **3. Drive** | `sage_test/scripts.py`, `Match.scripts`, network refusal; unit tests against a fake reader | first Edain engine test using `fire` passes |
| **4. Edain library** | `tests/utils/scripts.py`, the compile-only test, docs in `tests/README.md` | two tests use the library |
| **5. Extras** | probes in anger, accelerator-off run-now, trace frames, scripts for `user_map_runner` | as needed |

Slices 2 and 4 can start before 1 lands, but 3 depends on what slice 1 finds out.
