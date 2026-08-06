# Injecting script actions — a scope, and why this one is different

Static recovery from RotWK 2.01 `game.dat`, 2026-08-06, with `pefile` + `capstone` via
[`../scripts/pe.py`](../scripts/pe.py). **Nothing here is implemented.** This is the design and
the risk assessment for a third `.livebrg` command, next to the order buffer
([`message-stream.md`](message-stream.md)) and the camera slot
([`camera-control.md`](camera-control.md)).

**Verdict up front.** The dispatch is as reachable as the other two — one virtual call on one
global, `0x00DE87D8` slot `+0x38` — and the argument struct is a plain array of pointers the
cave can lay out itself. The *engineering* is a day's work. What makes this different from the
first two commands is that most of the 600 actions **change simulation state without telling
anyone**, which the order path exists specifically to avoid, and the camera path is exempt from
because the camera is not simulated. So the deliverable is not really "call this function"; it
is the classification and the gates around it. §4 is the point of this document.

## 1. The dispatch

```asm
007cafa5  mov  eax, 0xB977B3            ; ScriptActions::executeAction(ScriptAction *)
007cafb4  mov  esi, [ebp + 8]           ;   arg 1 = the action
007cafb7  mov  al,  [esi + 0x41]        ;   an enabled flag; zero skips the whole call
007cafc7  mov  eax, [esi + 4]           ;   the action type
007cafca  cmp  eax, 0x257               ;   600 cases
007cafd5  jmp  [eax*4 + 0x7CF857]
...
007cf854  ret  4
```

| fact | value | evidence |
|---|---|---|
| `ScriptActions::executeAction` | `0x007CAFA5`, `__thiscall`, one stack argument, `ret 4` | the function above |
| dispatched through | vtable `0x00C36098`, slot **`+0x38`** | the address appears in exactly one vtable slot in the image |
| the object | **`0x00DE87D8`** | stored at `0x00605695`, immediately after the constructor at `0x007BE076` writes that vtable |
| a live call site | `0x00735E62` | `mov ecx,[0xDE87D8]` / `mov eax,[ecx]` / `push <action>` / `call [eax+0x38]` |
| action ids | `0`–`0x257` (600) | the switch bound; the same number space as `ScriptAction.content_type`, which `sage_map` already parses |

**`ScriptAction`**, as much of it as the dispatcher and `getParameter` (`0x00602EFB`) establish:

```
+0x04  type            dword   the switch value == the map file's content_type
+0x08  parameter count dword
+0x0C  Parameter *     dword[] inline array, indexed directly: [this + 0xC + i*4]
+0x41  enabled         byte    cleared means executeAction returns immediately
```

`getParameter` is four instructions and bounds-checks against `+0x08`, so a synthesized action
with a truthful count cannot be walked off the end.

**`Parameter`'s own layout is not yet recovered**, and it is the one real unknown in the
mechanism (§5).

## 2. What the patch would add

A third command word in the `.livebrg` buffer, served by the same `GameLogic::update` hook, with
a small arena after it because unlike an order — which is copied into the engine's own message —
a `ScriptAction` is read *in place* through pointers:

```
script     dword    1 = an action is pending, cleared by the hook
action     0x48     the ScriptAction, with its Parameter* array written by the writer
params     N x ?    the Parameter records those pointers name
```

The cave is the same shape as the camera block:

```asm
mov  eax, [script]
test eax, eax
je   done
mov  ecx, [0x00DE87D8]
test ecx, ecx
je   done                    ; no ScriptActions object yet - leave it pending
mov  eax, [ecx]
push <action arena VA>
call [eax + 0x38]
mov  dword [script], 0
```

Two differences from the camera call worth planning for. `executeAction` **installs an SEH
frame** (the `mov fs:[0], ecx` in its epilogue), so it is a much heavier callee than
`setLocation` — fine on the logic thread, but it is not a leaf and a malformed action reaches
real engine code with a real chance of faulting. And the arena addresses are baked into the
action by the *writer*, which means the writer must know the section's runtime base — it already
does, from `find_section`.

## 3. Why the id space is nearly free

`sage_map` already parses `ScriptAction` out of every `.map` in the corpus: `content_type`, and
per-argument `ScriptArgumentType` with typed payload slots
([`sage_map/assets/player_scripts.py`](../../sage_map/assets/player_scripts.py),
[`sage_map/scripts.py`](../../sage_map/scripts.py)). So the argument shape of an action id does
not need deriving from the binary at all — it can be read off real maps that the engine
demonstrably executes, the same way the replay corpus grounds the order space. Any id the corpus
uses is an id whose parameter list has a worked example.

That is the strongest argument for doing this at all: the hard half is already done.

## 4. Desync — the part that decides whether this ships

### 4.1 Two different failures, and only one of them is called desync

**Peer divergence.** Every client in a network game simulates the same logic from the same
order stream. Script actions are *not* in that stream: each client runs the map's scripts itself
and arrives at the same result because it started from the same state. An action injected into
one client changes that client's state and nobody else's, and the engine notices — it emits
`MSG_LOGIC_CRC` (`0x44A`) every 100 frames as a checksum heartbeat
([`message-stream.md`](message-stream.md) §1). The result is a mismatch and a dropped game.

**Replay divergence.** A replay is the order stream, not the state; playback re-simulates from
it. An injected action leaves no trace in the file, so the recording no longer reproduces the
match it recorded — and this happens in a **solo skirmish, with no peer anywhere**. That is the
failure people forget, and it is the one that quietly invalidates a recorded run.

This is precisely the rule the order path was built to obey, stated in `live_bridge.py`'s own
docstring: orders go through `appendMessage` so they are network-ordered and check-summed like
human input, and "calling logic functions directly would bypass that and desync". Injecting a
script action *is* calling a logic function directly. The camera command is exempt only because
the camera is not simulated at all; there is no such exemption here in general.

### 4.2 Three tiers of action, and the tier is a property of the case body

Of the 600 cases, the risk is not uniform:

| tier | examples | peer divergence | replay divergence |
|---|---|---|---|
| **client-only** | camera moves and pans, letterbox, fades, sounds, UI messages, cinematic control | no | no |
| **script-engine state** | flags, counters, timers, enabling/disabling other scripts | yes | yes |
| **logic-mutating** | spawn, kill, damage, teleport, transfer ownership, grant money or sciences | yes | yes |

The middle tier is the trap: it touches no object, so it *looks* safe, but the script engine runs
inside the logic tick and its state feeds the same simulation, so a counter set on one client is
a divergence like any other.

**The tier is mechanically derivable, and that is the main piece of work here.** Each case body
is `mov ecx, edi; call <impl>` — a single implementation function per action. Walking each
implementation's call graph and asking which globals it reaches classifies it: `TheGameLogic`,
`ThePlayerList`, `TheThingFactory`, `ThePartitionManager` mean logic; `TheTacticalView`,
`TheInGameUI`, `TheAudio`, `TheDisplay` and nothing else mean client-only. That is the same scan
this document was written with, run 600 times, and it produces a table that is checked in rather
than a judgement made per call site.

### 4.3 The gates that follow from it

1. **Default deny.** The writer ships the derived allowlist and refuses everything else unless a
   caller passes an explicit unsafe flag — the `IllegitimateOrder` pattern `Session` already uses
   for hero recruits, where the engine will happily do something the interface never offered.
2. **Refuse outright in a network game.** Peer divergence is not a risk to be managed, it is a
   dropped match for everyone in it. `THE_GAME_INFO` (`0x00DE892C`) and `GAME_MODE_SKIRMISH` are
   already in [`../addresses.py`](../addresses.py), so the check is a read.
3. **Refuse, or at least mark, while recording.** `RecorderClass::m_mode == RECORD`
   (`THE_RECORDER + RECORDER_MODE`) says a replay is being written. An unsafe action injected
   then produces a file that does not replay, and nothing about the file says why.
4. **Make it visible in the session.** A session that has ever executed a logic-tier action
   should say so, so a run's results are not later read as if they came from an unmodified match.

### 4.4 Where the risk is worth taking

- **A training or test harness.** Scripted spawns, instant resources and forced kills make a
  reproducible scenario out of a game that otherwise takes ten minutes to reach the state under
  test. Nothing is being recorded, nobody is watching, and divergence costs nothing.
- **The client-only tier, permanently.** Cinematic camera work with the engine's own
  interpolation is the whole reason to want this, and it carries no risk at all — it is the same
  class of write as the camera command already shipped, done through a richer vocabulary.

And where it is not: **anything a real order can already express**. An order is delivered to
every peer, survives into the replay, and is subject to the game's own affordability and
legality checks. A script action that recruits a unit is strictly worse than
`MSG_QUEUE_UNIT_CREATE` in every one of those respects.

## 5. What has to be derived first

| # | unknown | how |
|---|---|---|
| 1 | **`Parameter`'s layout and size** | The one blocker in the mechanism. Find a case body that reads a numeric argument and follow the offsets off the `Parameter*` that `getParameter` returns; the map-side `ScriptArgument` (type tag, int, real, string, `Coord3D`) says which fields exist, so this is confirming offsets rather than discovering fields. |
| 2 | **Strings inside a parameter** | An `AsciiString` is one pointer to a refcounted block whose characters start at `+8` (already documented for `GameInfo::m_map`). Synthesizing one from outside the process means either building that block in the cave and getting the refcount right, or restricting the first version to actions whose parameters are **numeric and enumerated only** — which is the sane starting scope, and covers most of the camera tier. |
| 3 | **The id → name table** | `sage_map` has the ids; the names come from WorldBuilder's own tables. Needed for an allowlist anyone can audit, not for execution. |
| 4 | **The client/logic classification** | §4.2. The bulk of the work, and mechanical. |
| 5 | **Whether `+0x41` is really "enabled"** | The dispatcher refuses to run an action whose byte at `+0x41` is clear, so a synthesized action must set it. Worth confirming against a real `ScriptAction` in memory rather than trusting the branch. |

## 6. Acceptance test

The same discipline as the injection acceptance test the examples already carry
([`../../examples/sage_live/acceptance_verify.py`](../../examples/sage_live/acceptance_verify.py)),
turned to measure the thing this document is about:

1. Record a solo match, injecting one **client-only** action. Play the replay back. It must run
   to the end — proving the tier classification is real and not merely plausible.
2. Record a second, injecting one **logic-tier** action. Play it back. It must diverge, and
   visibly. A test that only demonstrates the safe case has not tested the claim.

That pair is what would justify shipping the allowlist as a safety boundary rather than as a
comment.

## 7. Effort

| piece | size |
|---|---|
| the cave: a third command, an arena, and the call | small — it is the camera block with a bigger payload |
| the writer: lay out a `ScriptAction` and its parameters at known addresses | small, once `Parameter` is known |
| `Parameter` layout (§5.1) | half a day of static work |
| the classification scan and its checked-in table (§4.2) | the bulk of it — one to two days including spot-checks |
| gates and the session surface | small |
| the acceptance pair (§6) | a session with the game running |

The mechanism is the cheap part and the safety table is the expensive part, which is the honest
summary of this whole change.
