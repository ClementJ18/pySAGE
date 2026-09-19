# A live script debugger — scope and engine findings

Static reading of RotWK 2.01 `game.dat` (ImageBase `0x400000`), 2026-09-18, with the
`sage-engine-re` skill's `explore.py`. This is the scope for a script debugger in
`sage_worldbuilder`, backed by `sage_live`, and the engine facts it rests on. **Built so far:** the
read-only tree and variable reader (`sage_live/backends/scripts.py`, spike
`examples/sage_live/script_tree.py`), the in-memory patcher (`sage_live/backends/live_patch.py`)
and the frame gate on it (`sage_live/backends/script_debugger.py`, spike
`examples/sage_live/frame_gate.py`). Slice A is done and confirmed on a running game. Slice B is
built (`sage_worldbuilder/live.py`, the Script Debugger dock in `sage_worldbuilder/ui/script_debugger.py`,
live rows in the Scripts panel) and confirmed by the user on a live game. Slice C is built
(`sage_live/backends/script_trace.py`, spike `examples/sage_live/script_trace.py`, the dock's Trace
tab) and executed under unicorn; not yet run against a live game. Slice D is built: breakpoints
live in the trace cave (layout v2, §2.2), pause and step drive the frame gate, and the dock and the
Scripts panel's right-click menu drive both; spike `script_trace.py --break NAME`, not yet run live. Slice E is
built (§4): triggers from the Scripts panel's right-click menu and the Variables tab; not yet run
live.

Surface agreed with the user:

- **Stepping:** pause, step one logic frame, run until a chosen script fires (breakpoints stop on
  the frame boundary, not between two actions).
- **Triggering:** enable / disable / re-arm a script; set counters, flags and timers; run a
  script's actions now; evaluate a script's conditions now without running it.
- **Sessions:** attach to any running game, not only one Jump To Game started.

## 1. The engine already has a debugger protocol

With `-scriptDebug2` or `-scriptDebugLite` the engine loads `DebugWindowLite.dll`
([`script-debug-window.md`](script-debug-window.md) §1) and talks to it through ten exports. The
engine-side wrappers are the natural hook points, because they are what every script event
already funnels through:

| wrapper | export | what reaches it |
|---|---|---|
| `0x00604D85` | `AppendMessage` | 87 call sites across the script engine; `(AsciiString *, bool)` |
| `0x00604F1C` | `AppendMessage` / `AppendMessageAndPause` | "`Run script - `*name*" and "`Run script false - `*name*" from `executeScript`, 4 sites (`0x00609AE7`, `0x00609B37`, `0x00609BB5`, `0x00609BF4`); skips names listed in `TheWritableGlobalData+0x10F4..+0x10F8` |
| `0x00605021` | `AdjustVariable` / `AdjustVariableAndPause` | counter and flag changes |
| `0x00604189`, `0x00604152` | `CanAppContinue` | polled once per frame into `0x00DE3B9C` / `0x00DE3B9D`; 1 when no DLL is loaded |
| `0x00603452` | - | **the frame gate** (§1.1): true when the DLL is loaded and `CanAppContinue` said no |
| `0x00603491` | `RunAppFast` | *not* a pause: the main loop (`0x0044B897`) uses it to skip rendering and fast-forward. The `CanAppContinue` lookup inside it is dead - its result is discarded. Latch byte `0x00DE3BA8` |
| `0x006034FB` | `ForceAppContinue` | tail-jumps into the DLL |
| `0x00603A1E`, `0x00603A71` | `SetFrameNumber` | once per frame |

Every wrapper first checks the module handle `[0x00DE3B98]` and most check the Lite byte
`0x00DE87B8`. **The pause and step machinery is the engine's own**: a gate that says "not yet"
holds the logic frame, and the game window keeps running. The debugger replaces the DLL's
answers, not the mechanism.

**Design consequence:** hook these wrappers directly (so no DLL, no MFC window and no
`-scriptDebug` flag are needed) and route them into a buffer the editor reads:

- an **event ring** — frame number, event kind (script ran true / false, message, variable),
  and the script's `Script *` plus its name — written by the `0x00604F1C` / `0x00604D85` /
  `0x00605021` hooks;
- a **control block** — `run` / `pause` / `step N frames` / `run until script S fires` — read by
  the frame-gate cave (§1.1). "Run until S" is decided inside the game: a `runScript` hook
  compares the `Script *` against a breakpoint table and flips the gate to pause itself, so a
  breakpoint stops on the same frame even when the editor polls slowly.

### 1.1 The frame gate

The frame dispatcher `0x006325A0` (called first thing in `GameEngine::update`) runs in this order:

```
006325b9  call 0x00604189        ; poll CanAppContinue into 0x00DE3B9C
006325c4  call 0x00603452        ; the gate: al = "held"
006325c9  mov  bl, al
006325cf  call [eax+0x9c]        ; the CLIENT phase - render, camera, input - runs regardless
006325d5  test bl, bl
006325dc  je   0x006325f8        ; not held: sub-frame advance, and every 6th call the LOGIC phase
006325de  mov  byte [TheGameClient+0xc8], 0
006325f3  jmp  0x00632705        ; held: skip both
```

`0x00603452` is `ScriptEngine::isPausedByDebugger`: false unless the DLL handle `[0x00DE3B98]` is
set, `ScriptEngine+0x1A5D9` is clear and `0x00DE3B9C` is zero. Without the DLL it can never be true,
so the debugger **redirects the call at `0x006325C4`** (stock `e8 89 0e fd ff`) to a cave that
answers from its control block and defers to `0x00603452` when not driving - so a real
`DebugWindowLite.dll` session still works. `0x00441E23` is the engine's own "either predicate is
true" query for the rest of the game.

The cave's modes are run / held / run-until-frame; run-until compares `GameLogic::m_frame` against
the target and switches itself to held inside the same dispatcher call, so stepping is exact. A
**lease** counts down one per held client frame and drops the cave back to run at zero; the
controller renews it every second, so a controller that dies leaves a game that resumes by itself.

**Confirmed live**, 2026-09-18, Edain skirmish (`examples/sage_live/frame_gate.py --check`): held,
the logic frame stayed at 4011 for 2 s while the dispatcher was called 60 times (the client at
30 fps); `step 1` went 4011 → 4012 and `step 10` 4012 → 4022, exactly; resume advanced it again;
detach left the site stock. A controller killed while holding (lease 60) let the game go within
about 2 s, and the next attach adopted the orphaned cave by its `SDBG` tag and removed it.

## 2. How a script runs

### The tree in memory

Recovered from the chunk writer (`0x007B63E8` for a script, `0x007B7350` for a group,
`0x007B7DA0` for a list) and the chunk reader (`0x007B83CC`), then cross-checked against the
per-frame walk below. Every offset is in `sage_patch/addresses.py`.

```
SidesList   +0x3c numSides   +0x40 SidesInfo[20], stride 0x60
SidesInfo   +0x08 ScriptList, embedded (not a pointer)
ScriptList  +0x04 group node chain     +0x18 group pool entries
            +0x08 script node chain    +0x38 script pool entries
node        +0x00 next   +0x04 entry index   +0x08 generation
entry       (0x14 bytes) +0x08 name AsciiString   +0x0e int16 generation   +0x10 object chain
ScriptGroup +0x04 child group chain   +0x08 script chain   +0x0c active   +0x0d subroutine
```

A script's **name is not in the `Script`**: it lives in the pool entry, and the object is
`[entry+0x10] + 4` (`0x007B53D8`; `0x007B5379` for groups). A node is live when its generation
equals its entry's (`0x007B53EF` / `0x007B5390`); the walk skips a stale one. **Groups nest** -
a group has its own child-group chain - which is what `sage_map`'s recursive `ScriptGroup.items`
already models. Side `i` is player `i`: the driver walks `SidesList` and `ThePlayerList` with one
index.

### The call chain

| address | what | notes |
|---|---|---|
| `0x0060CD88`.. | per-frame driver | for each side: current player (`+0x1A230`) = player *i*, scope `+0x1A20C` = its name, then the top-level script chain, then the groups |
| `0x0060A377` | `runScriptNodes(ScriptList *, node *, Bool validate)` | `__thiscall`, `ret 0xC`. Skips stale nodes and subroutines (`Script+0x2A`), passes the entry's name to `runScript` |
| `0x0060BCE5` | `runGroupNodes(ScriptList *, node *)` | recursive; an inactive **or** subroutine group skips its scripts *and* its children |
| `0x0060BD42` | call subroutine by name | 5 callers in the action dispatcher (`0x007A2xxx`); finds a group (`0x006049DD`) or a script (`0x00604A5D`) that must be a subroutine, sets the scope to the caller's, runs it |
| `0x0060BFBD` | the parameter-driven twin of the above | reads the name from the `Parameter` string (`+0x10`); one caller, `0x0060C298` |
| `0x0060A15C` | `ScriptEngine::runScript(Script *, AsciiString *name)` | `__thiscall`, `ret 8`: if due, sets `+0x3C`, then `0x00609C3A` when `Script+0x10` is set, else `executeScript` |
| `0x00603878` | "is this script due" | false when inactive `+0x40`, not enabled for the difficulty (`+0x2B/+0x2C/+0x2D`; the **current player's AI** difficulty when it has one, `ScriptEngine+0x1A5C4` otherwise), or before frame `+0x3C`. In Living World mode the frame test reads another clock (`[0x00DE4950]+0xFC`) and a turn-phase mask at `Script+0x24` |
| `0x006099DC` | `ScriptEngine::executeScript(Script *, AsciiString *)` | `__thiscall`, `ret 8`. Scripts with a team name run once per team member (`+0x334` list, `ScriptEngine+0x1A218` = current object) |
| `0x00609C3A` | the fire-actions-sequentially path | `Script+0x10` is the first byte of the sequential block (sequential, loop, loop count, target type, target name - `sage_map`'s field order) |
| `0x0060930F` | **evaluate conditions** `(Script *, 0, 0)` | returns bool; 4 callers. This is "evaluate now" |
| `0x0060C1C9` | **run an action list** `(ScriptAction *list, Script *, int)` | `__thiscall`. This is "run actions now" - the true list or the false list - without synthesising a single action |

**Every execution reaches `runScript`**: the per-frame walk through `0x0060A377`, and both
call-subroutine paths, through either `0x0060A377` (a group) or a direct call (`0x0060BEDA`,
`0x0060C0F2`). A breakpoint there misses nothing. Its second argument is the entry's **name**,
which the event ring can log without a lookup.

### 2.1 What a trace can hook

`executeScript` reports to the debug DLL's run-script logger `0x00604F1C` - `cdecl (AsciiString
*key, Bool isTrue, Bool pause)`, where `key` is the scope and name composed by `0x0072CDAB` - at
four sites, each **immediately before** it runs an action list and **only when that list is not
empty**:

| site | list | path |
|---|---|---|
| `0x00609AE7` | true | once per team member (`ScriptEngine+0x1A218` set) |
| `0x00609B37` | false | once per team member |
| `0x00609BB5` | true | a script without a team |
| `0x00609BF4` | false | a script without a team |

At all four `esi` is the `Script *` and `edi` is `TheScriptEngine`, and the logger reads nothing
but its stack, so a cave in place of the call can record and then jump on. A script whose
conditions pass but has no actions is **not** reported - it is visible only as an evaluation.

The fire-actions-sequentially path (`0x00609C3A`) never reaches the logger. It evaluates at
`0x00609C55` (`call 0x0060930F`, `thiscall (Script *, 0, 0)`, `ret 0xC`; `edi` the script) and
queues the true actions on a yes, so the trace wraps that call and records a yes.

**Variables have no change hook.** The fourth caller family of the adjust-variable wrapper
(`0x0060CF5B`, `0x0060CF89`, `0x0060D018`, inside `ScriptEngine::update`) is a dump of *every*
counter and flag to the DLL on every frame; the DLL diffs. The editor diffs its once-a-second reads
instead, which puts a change on the read that saw it rather than the frame it happened.

### 2.2 Breakpoints

A breakpoint is checked where a trace event is made (§2.1), so it sees exactly what the trace
sees: a script whose true actions run, whose false actions run, or whose sequential actions are
queued - each a bit of the entry's kind mask. The check runs whether or not recording is on. A hit
stores the script, frame and kind, counts itself, and writes "held" into the frame gate's mode
(§1.1). The gate is only asked at the start of the next dispatcher call, so the rest of that
frame's scripts run and the game holds on the **frame boundary**, never between two actions.

The table holds `Script *`s, not names: the editor resolves each breakpoint name to every live
copy of that script on every read, since a reload moves every script, and rewrites the table only
when that changes (count to zero first, entries, count last). A cave laid out by another version is
retired by its hooks and replaced; a cave's head is found by the 64 KB allocation granularity, not
by an entry point's offset, so this works whatever version laid it out.

`Script` fields:

| offset | field |
|---|---|
| `+0x04` / `+0x08` / `+0x0C` | comment, condition comment, action comment (`AsciiString`) |
| `+0x10` | sequential-actions block; its first byte selects `0x00609C3A` |
| `+0x20` | evaluation delay, seconds; each run sets `+0x3C = frame + delay * 5` |
| `+0x24` | Living World evaluation mask (chunk version 4 and later) |
| `+0x28` | active, **as authored** |
| `+0x29` | one-shot: executing clears `+0x40` |
| `+0x2A` | subroutine |
| `+0x2B` / `+0x2C` / `+0x2D` | enabled on easy / normal / hard |
| `+0x30` | `OrCondition *` |
| `+0x34` | true action list (`ScriptAction *`, linked) |
| `+0x38` | false action list |
| `+0x3C` | next frame the script may evaluate |
| `+0x40` | **active, live** - what the due check reads; the reader seeds it from `+0x28` |
| `+0x4C` | float, profiling (cleared every evaluation) |

`+0x28` against `+0x40` is the "has it fired" signal the editor needs: a one-shot that ran reads
authored-active, live-inactive.

`ScriptEngine` fields: scope string `+0x1A20C` (the player being evaluated), current object
`+0x1A218`, current player `+0x1A230`, difficulty `+0x1A5C4`; counters+timers map `+0x191A0`,
flags map `+0x191AC`, with lookup-or-create `0x0060817A` / `0x006082CF`
([`map-transition.md`](map-transition.md) §6.1). The maps are STLport red-black trees (node
`+0x04` parent, `+0x08` left, `+0x0C` right, null leaves; header `+0x08` leftmost), keyed
`(scope, name)` at `+0x10` / `+0x14`.

## 3. `Parameter`, partly

`ScriptAction::getParameter` (`0x00602EFB`) returns `[action + 0xC + i*4]`, bounds-checked
against `+0x08`. `Parameter::getUiText` (`0x007B5670`) switches on the type at **`+0x00`** over 78
cases (`0x007B56C2`), reads the **string** `AsciiString` at **`+0x10`** and a **real** at
**`+0x0C`**. The int and the coordinate are still to be read (most likely `+0x08` and
`+0x14`). This is the blocker [`script-action-injection.md`](script-action-injection.md) §5.1
names, now mostly closed. The debugger does not need to build a `Parameter` from scratch for
"run actions now" — `0x0060C1C9` runs the script's own, already-built list — so the layout matters
only for **showing** live argument values, and for a later "run this one action" feature.

## 4. Triggers, as built

| trigger | how |
|---|---|
| enable / disable | write `Script+0x40` (a group: `ScriptGroup+0x0C`) |
| re-arm a one-shot | write `+0x3C = 0`, then `+0x40 = 1` |
| set counter / flag / timer | write the record the reader already found (`ScriptVariable.address`): a dword value, a flag's byte. A timer is set in logic frames (seconds x the logic rate). A variable no script has created yet cannot be made - the record does not exist |
| evaluate now | `0x0060930F(script, 0, 0)`, from the gate's command mailbox; the answer comes back in the control block |
| run actions now | `0x0060C1C9(script+0x34 or +0x38, script, name)`, from the mailbox. `name` is the pool entry's `AsciiString *` (`LiveScript.name_address`), which is what `executeScript` passes. Team scripts run once, with no current object |

**Where the calls run.** Not inside `GameLogic::update` as first planned: the gate cave (§1.1) is
called by the frame dispatcher on the game's main thread once a client frame, *between* two logic
ticks, paused or not - so the command mailbox lives there and needs no hook of its own. Before a
command the cave does what the per-frame driver (`0x0060CDAA`..) does around each player's
scripts: the side's `Player *` (`PLAYER_LIST_GET_NTH`) into `ScriptEngine+0x1A230`, no current
object, and the scope string `+0x1A20C` set to the player's name through the engine's own
scope guard (`0x00604243` / `0x0060428D`); all three are put back afterwards. Executed under
unicorn with every helper stubbed; not yet confirmed on a live game that an action run between
ticks behaves as one run inside one.

**Desync.** Every trigger changes what the simulation does, so every one is refused in a network
game (`GameLogic::m_gameMode` 1 or 5). A skirmish is not recorded (`RECORDER_RECORDED_MODES`), so
the replay mark §4.3 of [`script-action-injection.md`](script-action-injection.md) asks for does
not arise in the games the debugger attaches to today.

## 5. Finding scripts in memory

The editor knows scripts by name, from the `.map`; the game knows them as `Script *`. The debugger
needs the map both ways:

- **map name**: `GameInfo::m_map` at `THE_GAME_INFO` (already read by `sage_live`) says which map
  is running, so an attached session can open it in the editor.
- **script objects**: walk each side's `ScriptList` (§2) and index by name. `read_script_tree`
  does this, and is cheap enough to re-read every poll - which is how the editor sees a one-shot
  fire without any hook.

## 6. Open, in spike order

1. ~~**Walk the tree against a real game**~~ - confirmed 2026-09-18 on an Edain skirmish of
   `map edain linhir` (5 sides, 883 scripts, groups nested four deep): all 34 of the map's own
   scripts matched on every flag and the delay, none missing; the other 837 are AI-library and
   music scripts. A fired one-shot (`KI Brutal`) read authored-active, live-inactive. Counters,
   timers and flags read with their scopes. `--watch` confirmed `+0x3C = frame + delay * 5` (1 s
   rescheduled 5 frames on, 30 s 150). A moving `+0x3C` means *evaluated*, not *fired*: it is
   set before the conditions run.
2. ~~**The scheduling list**~~ - answered statically: it is the `ScriptList` node chain, and every
   path reaches `runScript` (§2).
3. ~~**`Script+0x10` and `0x00609C3A`**~~ - the fire-actions-sequentially path (§2).
4. **Which of the 87 `AppendMessage` sites carry what** - condition results would give a trace
   of *why* a script did not fire, not only that it did.
5. ~~**Where the frame gate sits**~~ - `0x006325C4`, not `0x0044B897` (§1.1). Held, the logic
   frame freezes while the client keeps being called; confirmed live. Still to eyeball: that
   the camera moves and the screen animates while held (the numbers say the client runs; a person
   should confirm what it draws).
6. ~~**Patch in memory, not on disk**~~ - `LivePatcher`: `VirtualAllocEx` caves, every code write
   done with the process suspended (`NtSuspendProcess`) after checking the site holds its stock
   bytes, and undone on detach only where the site still holds ours. Confirmed live with the gate.

## 7. Slices

| slice | what | depends on |
|---|---|---|
| **A. Spike** | §6 items 1, 2, 5, 6 against a running game; the go/no-go | the user running the game |
| **B. Read-only attach** (built) | `sage_live` reads the script tree, counters, flags, timers; the editor's Scripts tree shows live active/fired state; a Script Debugger dock lists variables | A |
| **C. Trace** (built) | event-ring hooks; per-frame trace in the dock, each line linking to its script | A (in-memory patching) |
| **D. Pause / step / breakpoints** (built) | control block on the frame gate; breakpoints on scripts from the Scripts tree | C |
| **E. Triggers** (built) | enable/disable/re-arm (B's writes), then set variable, evaluate now, run actions now (bridge commands) | B, D |
| **F. Why not** | condition-level trace (§6.4): which condition failed | C |

Each slice after A is usable on its own. B is useful before any code is patched.
