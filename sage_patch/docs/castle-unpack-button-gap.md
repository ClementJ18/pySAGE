# Castle unpack: the button window before `BASE_BUILD`

Engine build `2.01.2614.37001`. Addresses are VAs (ImageBase `0x400000`), recovered **statically**
2026-09-28.

**Status: implemented as `castle-unpack-buttons`**
([`../patches/castle_unpack_buttons.py`](../patches/castle_unpack_buttons.py)), option C of §4;
§5 is what was built. It applies and verifies against the real `game.dat`. **Not
runtime-verified.**

The symptom: when a castle flag unpacks, the new citadel's command buttons can be clicked for a
couple of seconds. Then the structure plays its build-up and the buttons disappear until it
finishes.

## TL;DR

- `CastleBehavior`'s update is a timed state machine. Unpacking puts every member into
  `JUST_BUILT` for **`FadeTime`** (default 2 s). Only after that does it swap `JUST_BUILT` for
  **`BASE_BUILD`**, which it holds for **`BuildTime`** (default 5 s).
- `ControlBar::evaluateContextUI` hides the command set (context 6) for `BASE_BUILD`, and for
  `UNDER_CONSTRUCTION` with an unfinished `GettingBuiltBehavior`. It never checks `JUST_BUILT`, so
  the buttons stay live for the whole fade. That is the window.
- Edain's castle flags (`gondor_castle` and the others) leave `FadeTime`, `BuildTime` and
  `InstantUnpack` at their defaults, so the window is 2 s.
- The engine sets `JUST_BUILT` at 8+ other sites (ordinary construction completion among them), so
  gating the bar on `JUST_BUILT` alone would be too broad.

## 1. The state machine

`CastleBehavior`'s update interface sits at module `+0x10` (vtable `0x00C30E08`), and
`update()` is **`0x0079CF2A`**. In that function `esi` is module `+0x10`, so the state is module
`+0x34` and the countdown (seconds, decremented by `1/LOGICFRAMES_PER_SECOND` per frame) is module
`+0x40`. The "expired" byte is set only when the countdown was `> 0` and drops to `<= 0`
(`0x0079CF4B`–`0x0079CF7E`).

| state | arm | what it does |
|---|---|---|
| 1 | `0x0079D09D` | state = 2, `CastleBehavior::unpack(0)` (`0x0079BE6A`), countdown = `FadeTime` (data `+0x1C`) |
| 2 | `0x0079D035` | on expiry: state = 3, `clearAndSetModelConditionFlags(clear = JUST_BUILT, set = BASE_BUILD)` on every member (`0x00799F0F`), countdown = `BuildTime` (data `+0x24`) |
| 3 | `0x0079CFE8` | on expiry: state = 4, `clearAndSet(clear = BASE_BUILD, set = none)`, then members `setStatus(NO_ATTACK, false)` (`0x0079A017`) |

The two flag masks are 0x4C-byte `ModelConditionFlags` on the stack. `or byte [ebp-9], 4` sets
byte `+0x1B` bit `0x04` of the mask at `ebp-0x24` (`JUST_BUILT`, index 218). `or byte [ebp+0x43], 8`
sets byte `+0x1B` bit `0x08` of the mask at `ebp+0x28` (`BASE_BUILD`, index 219). This is why no
`push 0xdb` for `BASE_BUILD` exists anywhere in `.text`: the flag is built as a mask here.
`0x00799F0F` applies the pair to the keep (module `+0x38`) and to each id in the member vector
(module `+0x5C`/`+0x60`) through `Object::clearAndSetModelConditionFlags` (`0x0068D607`), with
`[esp+4]` as the clear mask and `[esp+8]` as the set mask.

## 2. What a member looks like during the fade

`CastleBehavior::buildCastleMember` (`0x007987EE`; see
[`castle-unpack-clearance.md`](castle-unpack-clearance.md) §2) creates each structure. When the
unpack is not instant (`[ebp+0xC] == 0`), the block at `0x00798AEA`–`0x00798B33` does this:

```asm
00798aed  fld   [edi+0x1c]            ; FadeTime
00798af0  fild  [0xd9f60c]            ; * frames per second -> fade frames
00798b04  call  0x70e013 / 0x670aa2   ; drawable fade-in over that many frames
00798b11  push  0xda                  ; JUST_BUILT
00798b18  call  0x68b581              ; timed model condition, same frame count
00798b1f  push  5 / push 1
00798b23  call  0x62684d              ; setStatus(NO_ATTACK, true)
```

So during the fade a member carries `JUST_BUILT` and `NO_ATTACK`, and neither `BASE_BUILD` nor
`UNDER_CONSTRUCTION`. With `InstantUnpack = Yes` this block is skipped and `0x0068D252` runs
instead (it walks the modules and calls a completion hook on each). The state machine still runs,
though, so an instant unpack has the same `FadeTime` window, this time with no flags at all.

## 3. The control bar test

`ControlBar::evaluateContextUI` is **`0x0071EBDA`**: it clears the dirty byte at `+0x28` and
ends in `switchToContext(ctx, drawable)` at `0x0071D8BE`. For a single selected object:

```asm
0071ee67  push 0xdb                   ; BASE_BUILD
0071ee6e  call 0x46e918               ; testModelCondition
0071ee75  jne  0x71ef19               ; -> context 6 (under construction: no command set)
0071ee7b  push 2                      ; UNDER_CONSTRUCTION
0071ee7f  call 0x44ddec               ; testStatus
0071ee8a  call 0x68c3e6               ;   GettingBuiltBehavior, and its +0x38 / +0x2c queries
                                      ;   decide between context 6 and the normal bar
```

Nothing tests `JUST_BUILT`.

Leaving context 6 needs no event. Its per-frame update, `0x00944EBB` (case 6 of the context switch
in `ControlBar::update` at `0x0071FDFC`), tests `UNDER_CONSTRUCTION` and, while it is clear,
tail-jumps straight back into `evaluateContextUI`. So an object held in context 6 by `BASE_BUILD`
is re-asked every frame, and the bar returns the frame the answer changes. What marks the bar dirty
when `BASE_BUILD` first appears on an object that is *already* selected was not traced.

## 4. Fix options

| option | what | cost / risk |
|---|---|---|
| **A. INI only** | set `FadeTime` to one logic frame (e.g. `0.04`) on the castle flags' `CastleBehavior` | No binary change. **Do not use `0`**: the expiry byte needs a countdown `> 0`, so the machine would sit in state 2 forever (no `BASE_BUILD`, `NO_ATTACK` never cleared). This loses the opacity fade-in and changes the flag's own fade-out, but Edain's `BASE_BUILD` animation (the same `…_ABL` rise as `JUST_BUILT`) still plays. |
| **B. bar hook, cheap** | hook `0x0071EE67`: go to context 6 on `BASE_BUILD`, **or** on `JUST_BUILT` together with status `NO_ATTACK` | Only the non-instant fade sets that pair, but an object that carries `NO_ATTACK` permanently (for example from a `StatusBitsUpgrade`) would also lose its buttons for its short post-construction `JUST_BUILT` window. Does not cover `InstantUnpack = Yes`. |
| **C. bar hook, exact** | same site: if the object has `CastleMemberBehavior`, read its castle's flag id (`+0x18`), find that object, and test its `CastleBehavior` state `== 2` | Exact, and covers instant unpacks too. The cave is larger: it needs a module lookup by name key, the same way `onStructureBuilt` finds `CastleMemberBehavior` at `0x0079AC6E`. |
| D. logic side | set `BASE_BUILD` at unpack instead of after the fade | Changes which model state shows during the fade, and ties with `JUST_BUILT` in state matching. Not recommended. |

## 5. What was built

`castle-unpack-buttons` repoints the bar's `call testModelCondition` at `0x0071EE6E` to a cave with
the same contract (`__thiscall` on the object, the index on the stack, `ret 4`, the answer in `eax`):

1. `testModelCondition(index)`. If it holds, answer `1`: the stock behaviour, unchanged.
2. `findModule(nameKey("CastleMemberBehavior"))` on the object. None: answer `0`.
3. `findObjectByID(member+0x18)`, the flag that built it. `0` or gone: answer `0`.
4. `findModule(nameKey("CastleBehavior"))` on the flag. None: answer `0`.
5. Answer `1` exactly when that module's state (`+0x34`) is `2`, the fade.

Both name keys are looked up on every call rather than read from the engine's caches (`0x00DE8264`,
`0x00DE825C`), which are filled lazily and may still be empty. The call only runs when the bar
re-evaluates, so the two hash lookups cost nothing that matters.

Consequences:

- The citadel, and every other member the unpack built, shows the under-construction bar from its
  first frame. When the fade ends, members that get `BASE_BUILD` stay in context 6 through the
  build-up. Members that don't (the ones outside the keep and the `+0x5C` list) get their
  buttons back that frame, through the per-frame re-evaluation in §3.
- `InstantUnpack = Yes` castles are covered too, because the state machine runs the same way.
- Only the control bar changes. Nothing in the logic refuses a command from a fading member, so a
  message that reaches the logic some other way (a script, the AI) still runs, exactly as it does
  during `BASE_BUILD` today.

Runtime check still owed: unpack a castle flag, select the citadel on its first frame, and confirm
the bar shows the under-construction context immediately, holds it through the build-up, and
returns the buttons when `BASE_BUILD` clears. Also select a wall or gate of the same unpack and
confirm its buttons return when the fade ends.

## Addresses

| what | address |
|---|---|
| `CastleBehavior` update vtable / `update()` | `0x00C30E08` / `0x0079CF2A` |
| … state 1 (unpack) / state 2 (fade → `BASE_BUILD`) / state 3 (build-up done) | `0x0079D09D` / `0x0079D035` / `0x0079CFE8` |
| apply clear/set masks to keep + members | `0x00799F0F` |
| `Object::clearAndSetModelConditionFlags(clear, set)` | `0x0068D607` |
| members `setStatus(bit, Bool)` helper | `0x0079A017` |
| member fade block (`JUST_BUILT` + `NO_ATTACK`) | `0x00798AEA`–`0x00798B33` |
| instant-unpack completion walk | `0x0068D252` |
| `ControlBar::evaluateContextUI` / its `BASE_BUILD` test / `switchToContext` | `0x0071EBDA` / `0x0071EE67` / `0x0071D8BE` |
| the under-construction context's per-frame update | `0x00944EBB` |
| `Object::findModule(nameKey)` / `Object::testModelCondition(index)` | `0x0068BDA5` / `0x0046E918` |
| `CastleMemberBehavior+0x18` (the flag's id) stamped in `onStructureBuilt` | `0x0079AC81` |
| `ModelConditionFlags` `JUST_BUILT` / `BASE_BUILD` | index 218 / 219 (byte `+0x1B`, bits `0x04` / `0x08`) |
