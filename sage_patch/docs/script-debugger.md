# A live script debugger — scope and engine findings

Static reading of RotWK 2.01 `game.dat` (ImageBase `0x400000`), 2026-09-18, with the
`sage-engine-re` skill's `explore.py`. **Nothing here is implemented.** This is the scope for a
script debugger in `sage_worldbuilder`, backed by `sage_live`, and the engine facts it rests on.

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
| `0x00603491` | `CanAppContinue`, then `RunAppFast` | **the frame gate**: 4 callers (`0x0044B897`, `0x0060503A`, `0x0060CEE0`, `0x0063A012`); latch byte `0x00DE3BA8` |
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
  the `0x00603491` hook. "Run until S" is decided inside the game: the `executeScript` hook
  compares the `Script *` against a breakpoint table and flips the gate to pause itself, so a
  breakpoint stops on the same frame even when the editor polls slowly.

## 2. How a script runs

| address | what | notes |
|---|---|---|
| `0x0060A377` | walks a script **scheduling list** | nodes linked at `[node]`, per-node index at `+4`; data at `[list+0x38] + index*0x14 + 8`. Not the player/group tree — BFME2 schedules evaluation. **Open**, see §6 |
| `0x0060A15C` | `ScriptEngine::runScript(Script *, int)` | `__thiscall`, `ret 8`: if due, sets next-evaluation frame, then `0x00609C3A` (when `Script+0x10` is set) or `executeScript` |
| `0x00603878` | "is this script due" | false when inactive `+0x40`, not enabled for the current difficulty (`+0x2B` easy, `+0x2C` normal, `+0x2D` hard; difficulty at `ScriptEngine+0x1A5C4`), or before the frame at `+0x3C` |
| `0x006099DC` | `ScriptEngine::executeScript(Script *, int)` | `__thiscall`, `ret 8`. Scripts with a team name run once per team member (`+0x334` list, `ScriptEngine+0x1A218` = current object) |
| `0x0060930F` | **evaluate conditions** `(Script *, 0, 0)` | returns bool; 4 callers. This is "evaluate now" |
| `0x0060C1C9` | **run an action list** `(ScriptAction *list, Script *, int)` | `__thiscall`. This is "run actions now" — the true list or the false list — without synthesising a single action |

`Script` fields read so far:

| offset | field |
|---|---|
| `+0x10` | byte, selects the `0x00609C3A` path (to identify) |
| `+0x20` | evaluation delay, seconds |
| `+0x29` | one-shot: executing clears `+0x40` |
| `+0x2B` / `+0x2C` / `+0x2D` | enabled on easy / normal / hard |
| `+0x34` | true action list (`ScriptAction *`, linked) |
| `+0x38` | false action list |
| `+0x3C` | next frame the script may evaluate |
| `+0x40` | **active** |
| `+0x4C` | float, profiling (cleared every evaluation) |

These match what `sage_map` parses from the file (active, one-shot, per-difficulty flags,
evaluation delay), which is the cross-check the spike should make first.

`ScriptEngine` fields: scope string `+0x1A20C` (the player being evaluated), current object
`+0x1A218`, difficulty `+0x1A5C4`; counters+timers map `+0x191A0`, flags map `+0x191AC`, with
lookup-or-create `0x0060817A` / `0x006082CF` ([`map-transition.md`](map-transition.md) §6.1).

## 3. `Parameter`, partly

`ScriptAction::getParameter` (`0x00602EFB`) returns `[action + 0xC + i*4]`, bounds-checked
against `+0x08`. `Parameter::getUiText` (`0x007B5670`) switches on the type at **`+0x00`** over 78
cases (`0x007B56C2`), reads the **string** `AsciiString` at **`+0x10`** and a **real** at
**`+0x0C`**. The int and the coordinate are still to be read (most likely `+0x08` and
`+0x14`). This is the blocker [`script-action-injection.md`](script-action-injection.md) §5.1
names, now mostly closed. The debugger does not need to build a `Parameter` from scratch for
"run actions now" — `0x0060C1C9` runs the script's own, already-built list — so the layout matters
only for **showing** live argument values, and for a later "run this one action" feature.

## 4. What each trigger costs

| trigger | how | new engine work |
|---|---|---|
| enable / disable | write `Script+0x40` | none |
| re-arm a one-shot | write `+0x40 = 1`, `+0x3C = 0` | none |
| set counter / flag / timer | the lookup-or-create functions, called from the bridge hook with a `<scope>/<name>` key | a bridge command; the call is already documented |
| evaluate now | `0x0060930F(script, 0, 0)` from the bridge hook, result written back | a bridge command; must set the scope `+0x1A20C` to the script's player first |
| run actions now | `0x0060C1C9(script+0x34 list, script, 0)` from the bridge hook | a bridge command; same scope rule. Team scripts: run once, no per-member loop, in v1 |

All four calls run **inside the logic tick**, from the live-bridge hook in `GameLogic::update`,
never from another thread.

**Desync.** Every trigger except enable/disable is logic-tier
([`script-action-injection.md`](script-action-injection.md) §4). A debugger session is a test
session, so it is allowed, but with the §4.3 gates: refuse in a network game (`THE_GAME_INFO`
game mode), and mark the session when a replay is being recorded. Since the user wants to attach
to any running game, the network refusal is the one that actually protects someone.

## 5. Finding scripts in memory

The editor knows scripts by name, from the `.map`; the game knows them as `Script *`. The debugger
needs the map both ways:

- **map name**: `GameInfo::m_map` at `THE_GAME_INFO` (already read by `sage_live`) says which map
  is running, so an attached session can open it in the editor.
- **script objects**: walk the sides list's per-player `ScriptList` → groups → scripts once
  after the map loads and index by name. The walk is not read yet (§6).

## 6. Open, in spike order

1. **Walk the per-player script tree** in memory and match every script against the `.map`'s
   (name, active, one-shot, difficulty flags, delay). Confirms the `Script` table above on a
   real game.
2. **The scheduling list** at `0x0060A377` — whether every script passes through
   `runScript`, or some are only evaluated through `0x0060BEDA` / `0x0060C0F2` (the other two
   callers). A breakpoint that misses a path is a breakpoint that lies.
3. **`Script+0x10` and `0x00609C3A`** — likely the "evaluate in sequence" or subroutine path.
4. **Which of the 87 `AppendMessage` sites carry what** — condition results would give a trace
   of *why* a script did not fire, not only that it did.
5. **Where the frame gate sits in the main loop** (`0x0044B897`): confirm that holding it
   freezes logic but keeps rendering, audio and input alive, and that the camera still moves.
6. **Patch in memory, not on disk.** Attaching to any running game means the hooks cannot be
   baked into `game.dat` beforehand. `examples/sage_live/set_render_rate.py` already writes code
   bytes with `VirtualProtectEx` + `WriteProcessMemory`; the debugger needs the same for caves,
   plus `VirtualAllocEx` for their home. A patch applied to a live process must write each hook's
   5-byte jump in one write and be removable on detach. Jump To Game can keep using the on-disk
   route.

## 7. Slices

| slice | what | depends on |
|---|---|---|
| **A. Spike** | §6 items 1, 2, 5, 6 against a running game; the go/no-go | the user running the game |
| **B. Read-only attach** | `sage_live` reads the script tree, counters, flags, timers; the editor's Scripts tree shows live active/fired state; a Script Debugger dock lists variables | A |
| **C. Trace** | event-ring hooks; per-frame trace in the dock, each line linking to its script | A (in-memory patching) |
| **D. Pause / step / breakpoints** | control block on the frame gate; breakpoints on scripts from the Scripts tree | C |
| **E. Triggers** | enable/disable/re-arm (B's writes), then set variable, evaluate now, run actions now (bridge commands) | B, D |
| **F. Why not** | condition-level trace (§6.4): which condition failed | C |

Each slice after A is usable on its own. B is useful before any code is patched.
