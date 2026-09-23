# Mission testing playbook

How to put a **single-player mission map** under an automated test: launch it in the real engine,
drive it from Python, and assert that the scripts you care about actually ran.

This is the campaign counterpart to [`sage_test`](../sage_test/README.md)'s scenario tests. A
scenario builds a synthetic map and asks *does this ability work*; a mission test starts a map
somebody authored and asks *does the mission still play*. The difference is that a mission's
behaviour lives in its **map scripts**, so the assertions are about scripts firing, not about
objects changing — which is what [`sage_live`](../sage_live/README.md)'s script debugger reads.

> **Status: designed, not yet run.** The pieces it composes are each proven — `run_user_map`
> starts a shipped map, the trace hooks record every script a game fires — but nothing has yet
> run them together against a mission, and §2 names one module that still has to be written.
> Treat every numbered step as a claim to be confirmed on the first run, and record what it
> actually did here.

## Contents

- [0. What the engine will and will not let you do](#0-what-the-engine-will-and-will-not-let-you-do)
- [1. Prerequisites](#1-prerequisites)
- [2. The missing piece: a name-keyed script watch](#2-the-missing-piece-a-name-keyed-script-watch)
- [3. Stage 1 — the static gate, no engine](#3-stage-1--the-static-gate-no-engine)
- [4. Stage 2 — launch the mission](#4-stage-2--launch-the-mission)
- [5. Stage 3 — attach and watch the scripts](#5-stage-3--attach-and-watch-the-scripts)
- [6. Stage 4 — drive the mission](#6-stage-4--drive-the-mission)
- [7. Stage 5 — the assertions worth writing](#7-stage-5--the-assertions-worth-writing)
- [8. Making a run cheap](#8-making-a-run-cheap)
- [9. Fidelity: what a test like this does not prove](#9-fidelity-what-a-test-like-this-does-not-prove)
- [10. Worked example](#10-worked-example)

## 0. What the engine will and will not let you do

Four engine facts shape the whole approach. Each one is silent when you get it wrong.

**A mission map cannot be auto-started from its own mod.** `-file` starts a *map cache entry*, and
for a map inside a mod's archives that entry comes from the mod's hand-written
`maps\mapcache.ini`. A campaign map is usually not in that file at all, and where it is it says
`isMultiplayer = no`, which the auto-start refuses — it takes the silent failure branch and dies
in `TheTerrainVisual` seconds later. The way round it is
[`run_user_map`](../sage_test/run.py): the engine caches maps in the **user files** folder itself
and derives the multiplayer flag from the map, and for these same maps it derives *yes*. So the
test copies the map folder to `My Rise of the Witch-king Files\Maps` and starts it there.

**A `map.ini`'s relative includes do not travel with the copy.** `map.ini` is read from the map's
own folder, and `#include "..\_inis\general\generic.ini"` resolves against that folder. Once the
folder sits in the user Maps directory with no `_inis` beside it the load stops on an error box
that reads exactly like a broken ini. `install_map_folder(extras=...)` copies the sibling folders
next to the map; pass every folder the ini reaches for.

**A `-file` start is a skirmish, not a campaign.** It goes through `TheSkirmishGameInfo`, so the
engine rebuilds the sides the way a skirmish does — one per occupied slot, plus the civilian and
creep sides — and merges each AI's library scripts into its side. The mission's own scripts are
still there and still run, but the **player they are scoped to** is whatever seat the lobby string
gives that slot, and nothing that only a `LinearCampaign` does happens at all: no carryover units,
no intro movie, no campaign save. §9 says what that costs.

This is sharpest on a **scenario** map, which is what a mission usually is: its sides are *named*
(`PlyrDwarves`, `PlyrMordor`, `PlyrCivilian`) rather than `Player_1..8`, and it may carry no player
start waypoints at all. A skirmish start has no slot to bind those names to. Check a map's sides
before assuming a launch will work, and treat the first launch as the experiment that answers it.

**A fatal ini error does not exit the process.** The engine raises a message box and waits. That
failure arrives as the launch timeout, not as an exit code, so a test that fails at 120 s with
"never reached frame 1" usually means a bad `map.ini`, not a slow machine.

## 1. Prerequisites

| what | why | check |
| --- | --- | --- |
| a game install | the engine and its archives | `<install>\game.dat` exists |
| `command-line-skirmish` in that `game.dat` | without it `-file` starts a random faction, no opponent, no resources, and dies before frame 1 | `sage-patch verify command-line-skirmish <install>\game.dat` |
| the install's **own** `game.dat`, under that name | a section-modified image run under any other filename dies inside `msvcr71.dll` | patch in place, don't copy aside |
| the map folder | `<name>\<name>.map` plus its `map.ini` | — |
| the sibling include folders | `extras` for `install_map_folder` | whatever the `map.ini` `#include`s |
| a non-elevated shell for the game, an elevated one for the write hooks | reading needs a read handle; recording, breakpoints and pause write code into the process | — |

Optional, and each one makes a run cheaper or quieter: `quiet-exit`, `render-rate`, `headless`,
`multi-instance` (the engine refuses a second copy of itself, so without it a leaked game turns
every later test into a failure with an unrelated-looking cause).

## 2. The missing piece: a name-keyed script watch

Everything below is available today **except one join**. The trace ring records
`(frame, kind, Script *, object id)` — addresses, not names — because a `Script` does not hold its
own name; the name lives in the `ScriptList`'s name-keyed pool entry that leads to it. The editor
closes that gap with `sage_worldbuilder.live.LiveIndex`, which needs an open `MapDocument`.

A test has no document, so it needs the same join without Qt or the editor:

```
sage_test/scripts.py        # to be written

class ScriptWatch:
    """Every script a running game fires, by name."""

    def __init__(self, session, *, kinds=...): ...

    def refresh(self) -> None            # drain the ring, resolve addresses to names
    def fired(self, name) -> bool
    def frames(self, name) -> list[int]  # every frame it fired on
    def order(self, *names) -> bool      # fired in this order
    def wait_for(self, name, timeout)    # poll until it fires, or fail
    def timeline(self) -> list[tuple[int, str]]
```

It is a thin thing — `read_script_tree(memory.read)` gives `ScriptTree`, whose `find(name)`
already returns `[(side, LiveScript)]` and whose `LiveScript.address` is what the ring records, so
the watch is a dict inverted once per attach plus a re-read when the tree changes. It belongs in
`sage_test` rather than `sage_live` because it is test ergonomics over the live API, not a new live
capability; it imports `sage_live.backends.script_trace` and `.scripts` and nothing from the
editor.

Two things it has to get right:

- **A name can exist on more than one side.** `find` returns every match. A mission's own scripts
  are unique in practice, but an AI library script name is not, so a watch keyed by name alone
  has to say which side it means, or report the collision rather than pick.
- **The tree is re-read, not cached forever.** Addresses are stable while a match runs, but a
  watch that outlives a match must notice and stop resolving into freed memory.

## 3. Stage 1 — the static gate, no engine

Run this before ever launching. It is seconds, it needs no install, and it catches the failure
mode that dominates a map recovered from an older version: a reference to something that no longer
exists.

```
sage-lint lint-maps "<map>.map" --game <install> --game <mod-tree>
python -m sage_edain.map_checks "<map>.map"      # or your mod's own rule set
```

`lint-maps` resolves the map's script arguments and placed objects against the assembled game and
reports `map-dangling-reference`, `map-dangling-object`, `map-dangling-property`. Base game first,
mod after, or base content is reported as missing.

**What a finding here means for a mission.** A dangling *object* is 100 placed props that silently
do not appear. A dangling *reference* in a script argument is worse: the action runs and does
nothing, so a mission stalls at an objective with no error anywhere. Neither is caught by the
engine and neither shows up as a crash, which is why the static gate comes first — a test that
launches a map with 12 dangling references is measuring the wrong thing.

Use `--baseline` to hold a known backlog and report only what is new.

## 4. Stage 2 — launch the mission

**By hand first.** Before writing a test, put the map where the engine will cache it and start it
from the game's own map list. That separates "the mission loads" from "the harness works":

```
sage-test install-map "<mod>\maps\<mission>" --extras "<mod>\maps\_inis"
sage-test uninstall-map "<mission>"
```

`install-map` prints the installed path, the name the map list will show, and the `-file` argument
for a scripted start. It needs no patch, no archive rebuild and no `mapcache.ini` edit — the engine
scans the user Maps folder itself. `sage-test maps` lists the cache the engine would build instead,
for the archive side.

**Then from a test.**

```python
from sage_test import Seat
from sage_live.launch.game_info import LobbySettings
from sage_test.run import run_user_map

MAP = r"C:\...\_mod\maps\<mission>"
INIS = r"C:\...\_mod\maps\_inis"

with run_user_map(
    MAP,
    install=r"C:\RotWK",
    name="sagetest_<mission>",        # a folder the harness owns, not the player's copy
    extras=(INIS,),
    seats=(Seat.human(faction=..., start_position=0),
           Seat.computer(faction=..., difficulty="hard", start_position=1)),
    settings=LobbySettings(starting_resources=0, seed=42),
    writable=True,                    # ordering needs the live bridge
    timeout=180,
) as session:
    session.wait_for_match()
    ...
```

Three choices in there that matter:

- **`name=`** installs the copy under a name of your own. `install_map_folder` *replaces* any
  folder of that name, so naming it after the map would overwrite a copy the player installed.
- **`seats=`** is the match. The mission's scripts are written against map players — `Player_1`,
  `Player_2` — and a seat binds to `Player_<start_position + 1>`, not to its index in the list. Get
  this wrong and the mission's scripts run for the wrong side, or for a side with no player, and
  fail in ways that look like script bugs.
- **`settings=LobbySettings(seed=...)`** fixes the seed. A mission with random spawn picks is not
  reproducible without it.

`_await_session` polls until the game reports a running match; a timeout here is §0's message box.

## 5. Stage 3 — attach and watch the scripts

Reading the script tree needs nothing: it follows pointers in a read handle, so it is safe against
any running game and needs no patch. Recording writes a cave and redirects four calls; it writes
nothing the game reads, so a controller that dies leaves a game running exactly as before.

```python
from sage_live.backends.memory import ProcessMemory, MemoryBackend
from sage_live.backends.script_trace import ScriptTrace, EventKind

trace = ScriptTrace(process)          # process = a writable handle on the game
trace.attach(recording=True)
...
events = trace.read()                 # (frame, kind, Script *, object id)
```

With §2's watch on top this becomes `watch.fired("Smaug_in_pos")`.

**Read the ring often enough.** It is a fixed-size ring; a reader that falls more than a ring
behind loses the oldest events and is told how many. A mission that fires hundreds of scripts a
second while fast-forwarded needs a poll in the loop, not one read at the end.

**A moving `Script+0x3C` means *evaluated*, not *fired*.** If you are tempted to infer firing from
the script tree instead of the trace, don't: `next_frame` is set before the conditions run. The
trace's `EventKind` is the thing that distinguishes a condition that passed from one that was
merely asked. **Why** a script did not fire is one level down: the condition watch (slice F in
[`sage_patch/docs/script-debugger.md`](../sage_patch/docs/script-debugger.md) §2.3) records the
engine's verdict on each condition of a watched script, and `sage_worldbuilder.why_not.explain`
turns that into "which condition failed, which were never reached". `ScriptTrace.set_watches`
and `condition_results` work without the editor.

## 6. Stage 4 — drive the mission

A mission advances because the player does something. Three levers, in order of fidelity:

**Play it.** `session.select`, `move`, `attack_move`, `attack`, `cast`, `recruit`, `build`. This is
the only lever that tests the mission as authored — a trigger on "heroes reach the exodus area"
is only really tested by walking the heroes there. It is also the slowest to write and the most
brittle: pathing takes as long as it takes, so wait on a condition, never on a sleep.

**Set the state the trigger reads.** `LiveSession.set_variable` writes a counter, flag or timer the
game already has. A mission gated on `Civilians_saved >= 5` can be advanced by setting the counter
instead of escorting five civilians. This tests everything downstream of the trigger and nothing
upstream of it, which is often exactly the trade you want when the thing under test is mission
stage 6.

**Run the script.** `LiveSession.run_actions(script, side)` runs a script's true or false actions
on demand, in that script's player scope, exactly as the engine's per-frame driver would;
`evaluate(script, side)` asks its conditions without running anything. This is a jump, not a test —
use it to get *to* the part under test, and assert on what happens after.

`set_script_active` and `rearm` complete the set: switch a script off to isolate a stage, or make a
fired one-shot able to fire again.

> Every lever but the first changes what the simulation does, and `LiveSession` **refuses all of
> them in a network game** — a peer that did not see the change would drop out of the match. Single
> player, which is what a mission test is, is fine.

## 7. Stage 5 — the assertions worth writing

In rough order of how much they are worth per line:

1. **It reached frame 1.** `session.observe().in_match`. For a map recovered from an older version
   this alone is most of the value: it proves the `map.ini` parses, the terrain loads, and the
   objects resolve.
2. **The opening scripts fired.** The settings group, the camera animation, the intro. If these do
   not fire, nothing downstream will, and the failure is unambiguous.
3. **Each objective's `Done_*` script fires after its `Show_*`.** `watch.order(...)`. This is the
   mission's spine; a stage that shows an objective it can never complete is the classic
   version-drift bug.
4. **A script fires exactly once.** A one-shot that fires twice is a re-arm bug; `watch.frames(name)`
   has the count.
5. **A script does *not* fire.** The failure branches — `Hero_*_killed`, `Loose` — asserted absent
   over a bounded window. Note this is only ever evidence over the window you watched.
6. **The variables the scripts keep.** `read_script_variables` gives counters, flags and timers
   with their scopes; a timer holds logic ticks *remaining*.

Assert on **frames, not seconds**. The logic rate is a fixed engine global, the wall clock is not,
and a fast-forwarded run has no relationship between the two.

## 8. Making a run cheap

A launch is about thirty seconds to frame 1, and more against an uncompiled mod tree. There is no
scripted reset, so **one mission is one process**.

- **Class- or module-scoped fixtures, never function-scoped.** Pay the launch once and still report
  each assertion by name. `sage_test.plugin` is built for this; enable it from a `conftest.py` and
  the `install` fixture *skips* when `--install` is absent, so a bare `pytest` never launches a
  game.
- **Fast-forward.** `LiveSession.set_speed(n)` raises the frame cap; it writes no code and is put
  back on `unhook`. A mission with a 4-minute attack timer does not need 4 minutes.
- **Pause and step for determinism.** `FrameGate` holds the logic frame while the client keeps
  drawing. `step(frames)` advances an exact number. Use it when an assertion is about *which
  frame*, and when you need to read state without it moving underneath you.
- **Breakpoints to synchronise.** A breakpoint on a script holds the game on the frame boundary
  after it fires — never between two actions — so the controller can read the world at exactly that
  point. The gate is only asked at the start of the next dispatcher call, so the rest of the
  frame's scripts still run.
- **The lease is why this is safe in a shared install.** Every client frame spent paused or stepping
  spends one; at zero the gate drops back to running by itself. A killed Python process leaves a
  game that resumes a few seconds later, not one frozen until it is closed.
- **Parallelism is not built.** `pytest-xdist` needs the `multi-instance` patch and a
  worker-suffixed map name; the plugin already writes the name, nothing has exercised it.

## 9. Fidelity: what a test like this does not prove

Be explicit about this in the test's own docstring, because the gap is easy to forget:

- **It is a skirmish.** No carryover units, no `LinearCampaign` entry, no intro movie, no campaign
  save. If the mission depends on a hero arriving from the previous mission, that hero is not there
  and the scripts that use it will not fire. Starting the real campaign from the shell is a
  different mechanism (`sage_patch/docs/campaign-select.md`) and not scriptable today.
- **It is the copy in the user folder**, not whatever the engine would otherwise have loaded. When
  the source tree and the shipped archives disagree, this tests the tree.
- **Sides are rebuilt.** The live script tree is keyed by player and name, never by position, and
  the AI libraries are merged in. A script looked up by name alone may not be the one you meant.
- **A passing run is evidence over the window you watched**, at the seed you fixed, at one
  difficulty. Easy, normal and hard are per-script flags (`LiveScript.easy` / `.normal` / `.hard`):
  a mission can have stages that only exist on one difficulty, and one run tests one of them.
- **The static gate and the live run catch different things.** Neither is a substitute; a mission
  with zero dangling references can still stall, and a mission full of them can still reach frame 1.

## 10. Worked example

The shape a mission test should end up as. `ScriptWatch` is §2, still to be written.

```python
import pytest

pytest_plugins = ["sage_test.plugin"]


@pytest.fixture(scope="class")
def mission(install, ...):
    with run_user_map(MAP, install, name="sagetest_erebor", extras=(INIS,),
                      seats=SEATS, settings=LobbySettings(seed=42),
                      writable=True) as session:
        session.wait_for_match()
        watch = ScriptWatch(session)
        yield session, watch


@pytest.mark.engine
class TestErebor:
    def test_reaches_a_match(self, mission):
        session, _ = mission
        assert session.observe().in_match

    def test_the_opening_runs(self, mission):
        session, watch = mission
        watch.wait_for("Position_start_camera", timeout=30)
        assert watch.fired("Set_Parameter")
        assert watch.fired("Give_upgrades")

    def test_objective_one_completes(self, mission):
        session, watch = mission
        # walk the heroes to the exodus area, then:
        watch.wait_for("Thror_reached_exodus", timeout=120)
        assert watch.order("Show_objective_1", "Done_objective_1")

    def test_nobody_died(self, mission):
        _, watch = mission
        assert not watch.fired("Hero_thror_killed")
        assert not watch.fired("Loose")
```

## Log

Record what each first run actually did, so the next person does not re-derive it.

| date | what was run | result |
| --- | --- | --- |
| 2026-09-22 | `sage-patch verify command-line-skirmish C:\RotWK\game.dat` | **fails** — `.clskir` section absent, so `run_map` / `run_user_map` cannot start anything off that install until the patch is in its `game.dat` |
| 2026-09-22 | `sage-test install-map` on Edain's `MAP ANG Erebor`, `--extras _inis` | installed; `_inis/general` and `_inis/gondor` landed beside the map as siblings, so the `map.ini`'s `..\_inis\general\generic.ini` resolves |
| 2026-09-22 | `sage-lint lint-maps` on that map, RotWK + `_mod` | 21 warnings, 0 errors; useful before a launch, and none of it is anything the engine would report |
| 2026-09-22 | reading the map's own player setup | it is a **scenario** map: named sides (`PlyrDwarves` human, `PlyrMordor`, `PlyrCivilian`, `PlyrNeutral`), no `Player_N_Start` waypoints. Whether a `-file` skirmish start honours named sides or strands the mission's scripts on a side with no player is **the open question** for §0's fourth fact, and the first thing a launch settles |
