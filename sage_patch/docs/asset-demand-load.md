# The mid-match model-load hitch — scoping notes

Scope for a hypothetical `asset-preload` patch: stop the frame from stalling the first time a
high-vertex model is needed. ROTWK `game.dat` build `2.01.2614.37001`, ImageBase `0x400000`, no
ASLR; the file offset is `VA - 0x400000` for every site cited here. Read **statically** on
2026-08-21 with `pefile` + `capstone` from
`sage_patch/engine/game.dat.backup`
(11,346,432 bytes). **Every site cited below was re-checked byte-for-byte against three other
copies** — the repo-root `game.dat`, the Edain-built `game.dat`, and the installed
`C:\Program Files (x86)\Games\bfme\rotwk\game.dat` — and is identical in all four.

## TL;DR

- **The engine already has the streaming asset system you would otherwise write.** There is an
  asset manager singleton (`0x00DEF75C`), a state machine over asset handles, per-stage work
  queues, a main-thread pump called once per client frame, and a **dedicated background loader
  thread** named `asst` (`0x00A361A0`, started from the manager's constructor at `0x00A38D2D`).
- **It is parked for the whole match.** Starting a game calls the manager's `SetAsyncEnabled(0,
  false)` (`0x00631542`, and again at `0x006261F3`), which clears the worker's run flag at
  `manager+0x1F4` and then spins on a heartbeat until the thread has parked. Nothing re-enables it
  once play begins: the only re-enable (`0x0065D5A9`) sits in the load-screen path and is itself
  gated on a flag that is false in retail.
- **So every asset first needed mid-match is loaded synchronously, inline, on the main thread.**
  That path is `0x00A32AD0` (`EnsureLoaded`, a virtual on the asset-handle base class, present in
  17 vtables) → `0x00A37320`, which takes the manager's critical section and does init/preload/
  load/postload right there. The engine even has a log line for it: `'[info] Demand load: '` at
  `0x00C95150`. **This is the shape of the stutter**, and it is by construction, not by accident.
- **A master switch exists and is unreachable.** `GlobalData+0x11C8` gates the whole async mode
  (readers at `0x004467C4`, `0x0062B456`, `0x00757947`, `0x00757973`, `0x00758508`). It is set to
  `false` in `GlobalData`'s constructor (`0x0064396E`), it is **not** in the 457-entry `GlobalData`
  INI field table, and the one function that sets it to 1 (`0x007BA7C8`) has **no callers and no
  data references anywhere in the image** — a dead command-line handler whose table entry was
  stripped from the 16-option retail table at `0x00C35DA8`.
- **The engine also ships a per-asset load profiler, and it is the measurement gate.** Turn on one
  byte (`GlobalData+0x123D`) and the engine writes a CSV with the columns
  `frame,type,asset,tInit,tPreload,tLoad,tPostload,tTotal,recursion` (`0x00C95108`) — exactly which
  asset demand-loaded on which frame, and how many milliseconds each phase cost. **Do not write a
  line of this patch before that file exists for a real match.** §4, and §4.1 for
  `asset-load-profile`, the twelve bytes that flip it.
- The `KindOf` idea does not fit the machine. §5.4.

## 1. What happens when a model is first needed

`0x00A32AD0` is the whole story, and it is nine instructions:

```asm
00a32ad0  mov  eax, ecx                     ; this = the asset handle
00a32ad2  mov  ecx, [eax+0x4]               ; the handle's state word
00a32ad5  and  ecx, 0xFF0000                ; state lives in bits 16..23
00a32adb  cmp  ecx, 0x30000                 ; 0x30000 == fully loaded
00a32ae1  je   0xa32af3                     ; ... then nothing to do
00a32ae3  mov  ecx, [0x00DEF75C]            ; the asset manager
00a32ae9  test ecx, ecx
00a32aeb  je   0xa32af3
00a32aed  push eax
00a32aee  call 0x00A37320                   ; <- load it. now. on this thread.
```

`0x00A37320` timestamps with `rdtsc` if profiling is on (`0x00A3736B`), takes
`EnterCriticalSection` on `manager+0x68` (`0x00A373A0`), logs `'[info] Demand load: <name>'` for
anything not prefixed `apt_` or `sfe_` (`0x00A3747D`), and runs the asset through its load stages
before returning. Whatever that costs — file read out of the `.big`, W3D chunk parse, vertex and
index buffer creation, texture upload — the client frame is holding still for all of it.

The manager is real in retail: it is constructed at `0x00446765` and its holder is stored to
`0x00DEF548`. That global is the one [`multicore.md`](multicore.md) §2 sees as the **first call in
the frame dispatcher** — `0x006325B0`, `[0x00DEF548]` vtable `+0x28`. Slot `+0x28` of vtable
`0x00C95090` is `0x00A32C30` (`mov ecx,[ecx+0xC]; jmp 0x00A37E50`), so the pump below runs before
anything else in the client frame.

## 2. The pipeline that is running, and the thread that is not

### 2.1 Handle states

The state word at `handle+0x4` bits 16..23 is a stage index. Observed values: `0x30000` (loaded,
the early-out above), `0x60000` and `0x70000` (set in sequence around the synchronous load at
`0x00A32A8C`..`0x00A32AB0`), `0x80000` (claimed by the worker, `0x00A36254`). The pump and the
worker both index per-stage queue blocks at `manager + 0x80 + stage*0x28`.

### 2.2 The main-thread pump — `0x00A37E50`

Once per client frame. It walks the stages in order and, for each one with a non-empty queue, does
a slice of work. Two details matter:

- `0x00A37E9B` reads `manager+0x1F4` — the worker's run flag — and **skips stages 1 and 5 only if
  the worker is running**. With the worker parked, the pump does those stages itself, on the main
  thread, inside the frame.
- `0x00A37F2E` compares a computed queue depth against `0x64` and bails out above it
  (`jae 0x00A38278`). That is the pump's per-frame backlog cap, and it is the one number in this
  system that is trivially patchable.

### 2.3 The worker thread — `0x00A361A0`, named `asst`

Started by the manager's constructor: `push 0x00A36390` (the thread proc, a one-line thunk into
`0x00A361A0`), `mov [0x00DEF75C], esi`, `call _beginthread` at `0x00A38D2D`, then `Sleep(1)`. The
thread names itself `'asst'` (`0x00A361C5`, `push 0x61737374`), then loops:

```asm
00a361f0  mov  al, [esi+0x1F4]              ; run flag
00a361f8  mov  byte [0x00DEF759], 1         ; heartbeat, every iteration
00a361ff  jne  0xa36208                     ; enabled -> drain the queues
00a36201  push 0x64
00a36203  jmp  <Sleep>                      ; disabled -> sleep 100ms and loop
```

So it costs nothing while parked, and it drains stages 1 and 5 (the two the pump skips) while
running. It takes the same `manager+0x68` critical section the demand path takes.

### 2.4 Who turns it off

`0x00A33BB0` is `Enable(which)` and `0x00A33BE0` is `Disable(which)`, `which` selecting between the
flags at `+0x1F4` (the worker), `+0x1F5` and `+0x1F6`. `Disable(0)` is a **synchronous quiesce**:
it clears the heartbeat at `0x00DEF759`, clears the run flag, and then `Sleep(1)`-spins
(`0x00A33C20`..`0x00A33C2A`) until the worker has ticked once and observed it.

| site | call | context |
|---|---|---|
| `0x004467CD` | `Disable(0)` if `GlobalData+0x11C8` | immediately after the manager is constructed |
| `0x006261F3` | `Disable(0)` unconditionally | first instruction of the body at `0x006261E2` |
| `0x0062A148` | `Disable(2)` | `0x0062A11A`, reached from the new-game path below |
| `0x00631542` | `Disable(0)` unconditionally (`ebx` is zeroed at `0x006314E0`) | the new-game routine |
| `0x0065D443` | `IsEnabled(0)` → saved to `[ebp-0x10]` | load-screen entry |
| `0x0065D5A9` | `Enable(0)` **if** `GlobalData+0x11C8` **and** the saved state | load-screen exit |

The routine at `0x006314CD` is the one to read: it clears the asset profile name at `0x006314ED`,
parks the worker at `0x00631542`, and then re-arms the profile as `assetload <mapname>` at
`0x00631617` — a start-a-new-game sequence. The worker is parked there and, because the only
re-enable is `0x11C8`-gated, stays parked for the match.

## 3. The master switch, and why nothing can reach it

`GlobalData+0x11C8` is a single byte with six readers (`0x004467C4`, `0x0062B456`, `0x00757947`,
`0x00757973`, `0x00758508`, `0x0065D59B`) that route several subsystems between an async path and a
blocking one — `0x00758508` picks between calling `[0x00DE4418]` vtable `+0x120` and a
`push -1` fallback, `0x00757947` and `0x00757973` conditionally call vtable `+0x124`.

Two writers. `0x0064396E` is `GlobalData`'s constructor, storing `bl` (zero) alongside its
neighbours `+0x11C9`..`+0x11CC`. `0x007BA7C8` is:

```asm
007ba7c8  mov  ecx, [0x00DE4364]            ; TheWritableGlobalData
007ba7ce  xor  eax, eax
007ba7d0  inc  eax
007ba7d1  mov  byte [ecx+0x11C8], al        ; = 1
007ba7d7  ret
```

`0x007BA7C8` has **no `call`/`jmp` targeting it and no 4-byte occurrence of its address anywhere in
the image.** It sits in a bank of identically shaped command-line handlers (`0x007BA795` is
`-randomSeed`; the table at `0x00C35DA8` holds sixteen entries and no more). EA stripped the option
and left the handler. There is no INI route either: `+0x11C8` does not appear in the 457-row
`GlobalData` field table (`0x00BFF580`..`0x00C01210`); `+0x11C4` is `ClampedLOSHeightForCastleStructures`
and `+0x11CA` is `PlanningModeEnabled`, and the bytes between them are unnamed.

**Read that as a warning as much as an opportunity.** This code path never shipped enabled, which
means it never shipped tested.

## 4. The measurement, which comes first

The engine profiles its own asset loads and the readout is one byte away.

- `GlobalData+0x123D` is the switch. Written only by `GlobalData`'s constructor (`0x00643A79`,
  zero); read at `0x0062ECD4`, `0x006314E2` and `0x0063160B`. Not in the INI field table, not on the
  command line.
- When set, `0x00631617` writes `'assetload '` (`0x00BFE048`) plus the map name into the buffer at
  `0x00DEF658`, and a non-empty first byte there **is** the "profiling on" test (`0x00A3736B`,
  `0x00A374ED`, and a dozen siblings).
- **That buffer is also the filename.** The writer calls `fopen` on `0x00DEF658` directly
  (`0x00A37B8B`) — `"wt"` (`0x00C9514C`) the first time the name differs from the copy kept at
  `0x00DEF558`, `"at"` (`0x00C95100`) every time after — and writes the header at `0x00C95108`:
  `frame,type,asset,tInit,tPreload,tLoad,tPostload,tTotal,recursion`. Rows go through `'%d,%s,"'`
  (`0x00C950F8`) and `',%.3lf'` / `',%.3lf,%i'` (`0x00C950F0`, `0x00C950E4`), and the file is
  closed again (`0x00A37D91`) after each one. Nothing appends an extension, so the file a match on
  `map mp fords of isen` leaves in the working directory is called
  `assetload map mp fords of isen.map` and holds CSV.
- **The times are milliseconds.** Each `t*` is an `rdtsc` delta over the calibration at
  `0x00DEF760` scaled by `0.001` (`0x00A37D7D`, the constant at `0x00BDCD88`), printed `%.3lf`.
- **`recursion` is a depth, not a count.** `0x00DEF770` is a stack of loads in progress: the demand
  path pushes the handle and bumps `0x00DEF900` on entry (`0x00A3738A`..`0x00A37397`), and the
  writer decrements it after emitting the row (`0x00A37D97`..`0x00A37DA4`). It holds a hundred
  entries with no bound check, which is a depth no tree of sub-assets will reach.
- **The third reader does nothing else.** `0x0062ECD4`, in the logic update, publishes the current
  frame to `0x00DEF550` for the `frame` column and that is all. The flag reaches the profiler and
  nothing but the profiler.

**The gate.** Set `GlobalData+0x123D` to 1, play the match that stutters, and read the CSV. It
answers, with no guessing, the three questions this whole page depends on:

1. **Is the hitch a demand load at all?** If the frame the user sees stutter on has no row, the
   cost is somewhere else — D3D resource creation on first *draw*, a texture upload, or per-model
   condition-state work — and none of §5 applies.
2. **Which assets, and how expensive?** `tTotal` per asset, and `recursion` says whether one model
   is dragging a tree of sub-assets in behind it.
3. **How early could it have been known?** The `frame` column against when the object was created.

Everything in §5 is a guess until that file exists.

### 4.1 The patch that flips it — `asset-load-profile`

Twelve bytes, in `GlobalData`'s constructor. The two adjacent byte stores that zero `+0x123C` and
`+0x123D` become one 16-bit store and three `nop`s:

```asm
        ; stock                                    ; patched
00643a73  mov byte [esi+0x123C], bl                mov word [esi+0x123C], 0x0100
00643a79  mov byte [esi+0x123D], bl                nop / nop / nop
```

`bl` is zero across that whole run of field initialisers, so the low half of the immediate keeps
`+0x123C` exactly as stock and the high half raises the flag. It is a **word** store rather than
the equally short dword one because `+0x123E`/`+0x123F` are padding the constructor never touches,
and a diagnostic patch has no business initialising them.

Why the constructor and not the three readers: blinding each reader's `je` is three sites instead
of one and leaves the flag itself reading false, so anything that later asks "is profiling on" gets
the wrong answer. Defaulting the field leaves it a *field* — one writable byte at
`TheWritableGlobalData+0x123D` — so a live session can turn it back off through `sage_live` without
unpatching, and the override instances the engine builds through the same constructor inherit the
default too.

The patch also reads four windows it never writes, because the store it rewrites is generic and on
its own proves nothing about which field it lands in: the two gates at `0x0063160B` and
`0x0062ECD4`, the `je` and `push 0x00BFE048` pair at `0x00631611`, and the `'assetload '` literal
itself. A build where any of those says something else is refused rather than silently zeroing some
other field.

**What it costs.** An `fopen`/`fprintf`/`fclose` per demand load. That lands after the timestamps,
so the columns stay honest, but the frame that stalls stalls harder than on a stock binary — read
the numbers, not the felt hitch. Client-local: no simulation state, checksum, order stream or
replay format is touched, and peers need not agree on it, so one player can profile a match
everyone else plays on stock binaries.

## 5. The three patch shapes

Ordered by risk. None of them should be written before §4 has run.

### 5.1 Preload during the load screen — the safe one

The load screen is already a load screen; work moved into it costs nothing anyone will feel, and it
is exactly where EA's own `Enable(0)` at `0x0065D5A9` puts the worker. The shape: at map start, walk
the set of models the match can possibly need and call `EnsureLoaded` (`0x00A32AD0`) on each, or
push them into the pump's stage-0 queue via the register path (`0x00A35430`, the function every W3D
asset-construction site at `0x0057F649`, `0x0057F9CC`, `0x0057FDFE`, `0x0058000B`, `0x0058031D`,
`0x005805A2` already calls).

The hard part is not the loading, it is the **set**. "Everything" is far too much: the installed
Edain tree is 6.5 GB of `.big` archives and `__edain_w3d.big` is the largest single one of them, so
a preload pass with no bound will exhaust a 32-bit address space long before it finishes. A
workable set is: every
`ThingTemplate` the map places, plus every template reachable from the participating factions'
`CommandSet`s, and for each, every `ConditionState` model rather than just the default. That last
clause is the one that matters for buildings — a structure's damaged and rubble states are separate
models, and they are first needed exactly when the player is least able to absorb a stall.

This is the patch that answers the question as asked, and it needs no thread and no `0x11C8`.

### 5.2 Give the pump more per frame — the cheap one

`0x00A37F2E` caps the pump's per-frame work at `0x64`. Raising that constant is a one-byte change
(a `cmp edx, 0x64` with an 8-bit immediate) and makes the already-running main-thread pipeline drain
faster, at the cost of a bigger, but bounded and *spread*, per-frame slice. It does not remove the
stall for an asset that was never queued; it shortens the window in which a queued asset can still
be caught unloaded. Worth trying immediately after §4 because it costs one byte and one match.

### 5.3 Wake the worker during play — the risky one

Two five-byte NOPs over `0x006261F3` and `0x00631542` leave the `asst` thread running for the whole
match, and stages 1 and 5 leave the frame. It is the smallest patch on this page and the most
dangerous one, for reasons that are properties of the engine and not of the change:

- **The D3D9 device is not created `D3DCREATE_MULTITHREADED`.** [`multicore.md`](multicore.md) §3.2:
  bit `0x4` is never set in the behaviour flags at `0x005240D2`. Whatever of the load path creates
  device resources cannot legally run on a second thread. The `WW3D::Lock`/`Unlock` discipline
  (`0x0051EEC0`/`0x005208D0`) exists to serialize the load-screen thread against the renderer and
  would have to cover the loader thread too — which is a claim about EA's code that must be checked
  stage by stage, not assumed because a mutex exists next door.
- **Lockstep.** If anything the loader produces is read by the simulation — bone positions feeding a
  fire point, a geometry-derived extent — then *when* it finishes changes what the logic computes,
  and the per-frame CRC at `0x00625886` will say so on the next multiplayer match. The `assetload`
  CSV's `type` column, cross-read against which subsystems consume each type, is how that gets
  ruled in or out.
- **It never shipped on.** §3.

### 5.4 The `KindOf` idea

A `KindOf` bit is the wrong axis, for three reasons, and the third is the fatal one:

1. `KindOf` is per-`ThingTemplate`; the stall is per-**model**, per-**condition-state**. Two
   buildings that share a `KindOf` may share no models, and one building's five condition states are
   five separate loads with one `KindOf` between them.
2. A new `KindOf` needs engine code to read it, so it is a binary patch either way — it buys no
   INI-only route, just a slower one.
3. By the time you can read the flag you already hold the `ThingTemplate`, and the template already
   names its models. If you can enumerate the templates, you can enumerate the models directly and
   skip the flag entirely — which is §5.1.

The honest version of the idea — "let the modder mark which things are worth paying for up front" —
is better served by a plain INI list in `GameData.ini` consumed by the §5.1 preload pass, if the
map-derived set turns out to be too coarse or too large. Decide that from the CSV, not now.

## 6. What is not known

- **Whether the stutter is in this system at all.** §4, question 1. The candidates this page does
  not cover are first-draw D3D buffer creation and texture upload, both of which happen on the main
  thread regardless of who parsed the `.w3d`.
- **Which stages of the pipeline touch the device.** Needed before §5.3 is even a proposal.
- **What the working set costs.** A preload pass that exhausts the 32-bit address space trades a
  stutter for a crash, and Edain HD assets are exactly the ones large enough to make that real.
- **Whether the pump's `0x64` cap is a count or a weighted budget.** The computation at
  `0x00A37EF5`..`0x00A37F2C` sums three queue depths with a `shl 5` on one of them; read it properly
  before touching the constant.

## Address table

| VA | what |
|---|---|
| `0x00A32AD0` | `EnsureLoaded` — the demand-load trigger, in 17 vtables |
| `0x00A37320` | the synchronous demand load; `0x00A3747D` logs `'[info] Demand load: '` |
| `0x00A37E50` | the main-thread pump; `0x00A37E9B` reads the worker flag, `0x00A37F2E` the `0x64` cap |
| `0x00A361A0` | the `asst` worker thread proc (`0x00A36390` is its thunk); `0x00A361F0` the run-flag test |
| `0x00A38AD0` | the asset manager constructor; `0x00A38D22`/`0x00A38D2D` start the thread |
| `0x00A38CAE`..`0x00A38CBC` | the three flags at `+0x1F4`/`+0x1F5`/`+0x1F6`, all initialised to 1/1/0 |
| `0x00A33BB0` / `0x00A33BE0` | `Enable(which)` / `Disable(which)`; `0x00A33C20` the quiesce spin |
| `0x00A32DE0` / `0x00A32E00` / `0x00A32E20` | their null-checked wrappers (cdecl, one arg) |
| `0x00A35430` | register an asset handle with the manager — every W3D construction site calls it |
| `0x00DEF75C` | the manager singleton; `0x00DEF548` its holder, pumped at `0x006325B0` |
| `0x00DEF759` | the worker heartbeat; `0x00DEF658` the profile-name buffer and the on/off test |
| `0x00DEF770` / `0x00DEF900` | the per-frame profiled-asset array and its count |
| `0x00446765` | where the manager is constructed; `0x004467CD` the first `Disable(0)` |
| `0x006261F3` / `0x00631542` | the two unconditional `Disable(0)` calls on the new-game path |
| `0x0065D443` / `0x0065D5A9` | the load screen's `IsEnabled(0)` / conditional `Enable(0)` |
| `GlobalData+0x11C8` | async master switch; `0x0064396E` zeroes it, `0x007BA7C8` sets it (unreferenced) |
| `GlobalData+0x123D` | asset-load profiler switch; `0x00643A79` zeroes it, read at `0x0063160B` |
| `0x00C95108` | the CSV header; `0x00A37B8B` the `fopen`, `0x00A37D91` the `fclose` after each row |
| `0x00643A73` | the two constructor stores `asset-load-profile` rewrites (§4.1) |
| `0x00C35DA8` | the 16-entry retail command-line table |
| `0x00BFF580`..`0x00C01210` | the 457-entry `GlobalData` INI field table |
| `0x00536E49` / `0x00536310` | create-render-obj-by-name, the classic path into the asset manager |
| `0x004BDACB` | `'ASSET ERROR: Model %s not found!'` — the failure arm of that call |
