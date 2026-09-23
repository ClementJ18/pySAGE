# A native accelerator module of our own — scope

[`accel-port.md`](accel-port.md) §6 was decided **2026-09-24: B2**, our own native companion module,
derived from OH1A's `bfme2_accel.dll` with his permission (2026-09-22). That file's §5 says B2 is a
separate project with its own scoping document; this is that document, and the write-up of the
`accel-module` patch that loads the module.

**Status 2026-09-24: M0 ran in Edain; M1 is built and harness-tested, not yet played.**

- **M0 in the game.** It was applied to the shipped Edain build and played. The log showed the
  module arming on the game thread and `Direct3DCreate9(0x20)` passing through the wrapper on that
  same thread:

  ```
  09:27:10.279 [28240] armed by the engine's Direct3DCreate9 resolve; game thread 28240, real 62B10DA0
  09:27:10.337 [28240] Direct3DCreate9(0x20) = 20BC7180
  ```

  The stock fallback (no DLL) was not reported on.
- **M1 is §9.** It is tested by `tests/sage_accel/harness.c`, a 32-bit program that runs the census
  code against fake Direct3D objects.

## TL;DR

- **The arming problem that sank the original on a patched binary goes away.** The engine resolves
  `Direct3DCreate9` itself (§2), so a three-instruction cave can hand it our export instead. We then
  wrap the device *as it is created, on the thread that creates it*. There's no whole-image checksum,
  no guessing from 64 effect calls, and no waiting for the first effect call to go live. The game
  thread's identity is simply the thread that called `CreateDevice`.
- **It composes with Edain and every other patch** for the reason [`accel-port.md`](accel-port.md)
  §1.1 gives: each `game.dat` edit is a site signature with verified originals, and the module itself
  touches no engine address in its first three milestones.
- **The first deliverable is a measurement, not an accelerator.** M1, a pass-through device wrapper
  that counts calls, answers the question read 3 raised
  ([`accel-queue.md`](accel-queue.md) §5): *how many queue drains would an Edain frame cost?* If the
  answer is "hundreds", the render thread is a loss on this content and we stop there, cheaply.
- **Toolchain: `ziglang` from PyPI** (the `accel` extra, installed 2026-09-24). It is a
  pip-installable clang targeting `x86-windows-gnu`, and zig 0.16's bundled mingw-w64 carries
  `d3d9.h` and every `d3dx9*.h`. It lives in the venv, needs no system install, and CI gets it with
  `pip install`.

## 1. Shape

| | |
|---|---|
| package | `sage_accel/` at the repo root, beside the other `sage_*` projects ([pySAGE layout](../../README.md)) |
| source | `sage_accel/src/*.c` — C, not C++. The D3D9 interfaces are called through their C vtable macros, which is also exactly the shape a vtable wrapper needs |
| generated | `sage_accel/gen.py` emits the wrapper thunks from a Python method table (§4). Generated C is committed so a reader never has to run Python to read the module |
| build | `sage-accel build` → `zig cc -target x86-windows-gnu -shared -O2 -Werror` → `sage_accel.dll`. **Shipped as CI's `sage_accel` artifact** (the `accel-module` job in `ci.yml`); players never need the toolchain |
| install | `sage-patch apply accel-module` on `game.dat`, and `sage-accel install <game dir>` to copy the DLL beside it. Either can happen first |
| tests | `tests/sage_accel/`: the generator's table against the D3D9 headers, and the queue's ring logic compiled into a test DLL and driven through `ctypes`. Nothing under test needs a GPU |

**Loading — changed while building M0.** This section first planned an `IMAGE_IMPORT_DESCRIPTOR`.
The cave in §2 calls `LoadLibraryA("sage_accel.dll")` itself instead, and that is better on every
count that matters here:

- **A missing DLL means stock, not a failed start.** With an import descriptor, Windows refuses to
  start a `game.dat` whose DLL is absent. With the cave, the patched binary runs unchanged without
  the DLL. It also runs unchanged on a system that cannot load it, such as one without the UCRT.
- **No import-directory surgery**, so there is nothing new in `sage_patch.utils`.
- **It loads at exactly the moment it arms**: `d3d9.dll` is loaded, and the call is on the game
  thread.

What it gives up: the module is not in the process from the first instruction. That matters only to
the later features that replace `msvcr71`'s allocator (`rpmalloc`), and only for memory allocated
before the device exists. The original swapped its allocator into a running process too, so this
is the situation it was already designed for. Revisit then.

**`sage-patch verify`** checks `game.dat` only. Since the DLL is optional at runtime, that is honest
for M0. Whether `verify` should also check the DLL beside `game.dat` against a recorded hash is
deferred to the milestone where the DLL's version starts to matter.

## 2. Arming — the one engine site

Read 2026-09-24 in `C:\RotWK\game.dat`:

```
00525171  68 04 72 be 00      push 0xBE7204            ; "D3D9.DLL"
00525176  ff 15 88 01 bd 00   call [LoadLibraryA]
0052517e  a3 10 36 dd 00      mov  [0x00DD3610], eax   ; the d3d9 module
00525189  8b 35 8c 01 bd 00   mov  esi, [GetProcAddress]
0052518f  68 f4 71 be 00      push 0xBE71F4            ; "Direct3DCreate9"
00525195  ff d6               call esi
00525199  a3 14 36 dd 00      mov  [0x00DD3614], eax   ; <- the pointer
...
00525209  ff 15 14 36 dd 00   call [0x00DD3614]        ; Direct3DCreate9(0x20)
```

The cave replaces the store at `0x00525199`. It re-runs the store, then calls
`LoadLibraryA("sage_accel.dll")` → `GetProcAddress("sage_accel_arm")` → `sage_accel_arm(real)`, and
stores any non-null result. It preserves every register and **the flags**, because the `je` after
the store reads the `cmp eax, ebx` from before it. It records what it found in a state byte in the
`.accel` block (magic `SACL`): 1 no DLL, 2 no export, 3 declined, 4 armed. From M1 on, the wrapper
`Direct3DCreate9` calls the real function and wraps the returned
`IDirect3D9`, and its `CreateDevice` wraps the device. Two consequences:

- **The game thread is identified positively.** Whoever calls `CreateDevice` is the thread that owns
  the queue. [`accel-thread-identity.md`](accel-thread-identity.md) §4's identity cave becomes
  unnecessary, because the wrapper sees the right thread by construction.
- **The load screen is handled by the discipline, not by name.** It is simply a thread other than
  the game thread, and it takes the direct-under-lock path (read 1 §2). Reproducing that path
  exactly is a correctness requirement from M2 on.

The effect side arms the same way, through the static import slots of `D3DXCreateEffect` and
`D3DXCreateEffectFromFileA` in `d3dx9_27.dll`. Those are IAT entries, so redirecting them is a data
edit, not a code cave.

Also relevant, and unchanged from [`render-thread.md`](render-thread.md) §4.2: the device is created
without `D3DCREATE_MULTITHREADED`. The queue design does not need it, because only one thread ever
executes. Leave it off unless M2 proves otherwise.

## 3. Milestones

Each one is shippable on its own and stops the project cheaply if its result says so.

| | what | done when | derived from |
|---|---|---|---|
| **M0** | toolchain, an empty module, the arming cave, a pass-through `Direct3DCreate9`, and `sage_accel.log` | **done 2026-09-24**, in Edain. Done when Edain starts and plays with the module loaded, and the log shows `Direct3DCreate9` intercepted on the game thread | §1, §2 |
| **M1** | pass-through wrappers for the device and effect vtables, counting calls per method per frame, **and getters per frame**, written to the log every 30 s | **built 2026-09-24** (§9). Done when a real Edain match produces the counts. **This is the measurement [`accel-port.md`](accel-port.md) deferred**, now answering the question that matters for B2 | read 3 §5 |
| **M2** | the queue: ring, commit, worker, flush, `Present` throttle, release mask, per-thread dispositions. **All `Lock`/`LockRect` calls drain** (no mirrors yet), and so do effect lookups | Edain plays correctly with the render thread on; the frame-time delta against M1 is measured | reads 1 and 3 |
| **M3** | effect wrappers onto the queue, with synthetic handles | as M2, with the effect half asynchronous | read 3 §3.1 |
| **M4** | lock mirrors (kinds `3`, `7`, `9`) and the engine's device-bypassing write paths | **needs read 4 first** — see §5 | unread |
| **M5** | dedupe and batching | needs read 5 | unread |
| later | `rpmalloc` (public domain), the fast CRT, the preshader cache | independent of the render thread; each is its own feature with its own on/off switch | [`render-thread.md`](render-thread.md) §3.2 |

**M2's all-locks-drain rule is deliberate.** It makes the first working render thread correct by
construction and slow exactly where M4 will make it fast. M1's counts say beforehand how slow.

## 4. The wrapper table

Read 3 found the queue-or-drain choice to be mechanical: a method that returns nothing the caller
reads is queued, and anything else drains and calls directly. So one Python table drives everything:

```python
Method("SetTexture", slot=65, args=("DWORD Stage", "IDirect3DBaseTexture9* pTexture"),
       queue=True, addref=("pTexture",))
Method("SetTransform", slot=44, args=("D3DTRANSFORMSTATETYPE", "const D3DMATRIX*"),
       queue=True, copy={"const D3DMATRIX*": "sizeof(D3DMATRIX)"})
Method("GetRenderState", slot=58, args=(...), queue=False)
```

`queue=False` generates "flush, then lock, then call". `queue=True` generates enqueue, inline copies,
`AddRef` plus the release mask, and commit. The per-thread gate is shared. The DLL's own split (47
queued and 72 draining on the device; [`accel-queue.md`](accel-queue.md) §TL;DR) is the reference the
table is tested against. Variable-size copies (`DrawPrimitiveUP`, the shader constant setters) take a
size expression in the same table.

## 5. Reads still owed

Two reads are needed before M4, and each lands in its own `docs/accel-*.md` as reads 1 and 3 did:

- **Read 4, lock mirrors.** Look at how the texture, surface and buffer wrappers build kinds `3`, `7`
  and `9`: shadow allocation, "adopted" and "dropped", `D3DLOCK_READONLY` and `D3DLOCK_DISCARD`.
  Then look at the engine write paths the DLL special-cases by address: the shroud at
  `0x0047308C`/`0x00473EB3`, the pixel writes at `0x005165E0`/`0x005166C0`, and the radar surface
  locks. Only that last part is engine knowledge, and it is what M4 costs.
- **Read 5, dedupe.** Read `0x1003FB80`, `0x10044B70` and `0x100438C0`, and how the effect-side
  batch records are opened and closed.

Neither blocks M0 through M3.

## 6. Risks

- **Two drains a frame could cost more than the queue saves.** M1 exists to find this out before
  anything is built on top of it.
- **Behaviour differences visible to the engine.** The DLL returns `D3DERR_INVALIDCALL` for a
  synthetic handle whose lookup has not run (read 3 §3.1), and it reports the *previous* frame's
  `Present` result (read 2). Our module should drain in the first case, which is correct and costs
  little, and should keep the second, because it is bounded at one frame.
- **Network and replays.** Everything here is client-local rendering. The logic step and the frame
  CRC ([`binary-attest.md`](binary-attest.md) §1) are untouched. `logicspread` stays out of scope for
  this project.
- **Defender.** An import-table load is the ordinary way a program gets a DLL, and there is no
  injector. The original's loader was quarantined for being an injector
  ([`render-thread.md`](render-thread.md) §0), which does not apply here.
- **Attribution, decided 2026-09-24.** `author = "officialNecro"`, who did this port and is the one to
  ask for fixes to it. OH1A is credited for the DLL work it is derived from: in the patch's credit
  line (`accel-module (by officialNecro), derived from OH1A's bfme2_accel.dll`), in its description,
  and in every `sage_accel` source file.

## 7. Decisions

1. **Toolchain: `ziglang`**, installed 2026-09-24.
2. **Ship the CI build** (2026-09-24). The DLL is a CI artifact and is never committed.
3. **Credit** as in §6 (2026-09-24).

## 8. Playing M0 (done)

1. `sage-patch apply accel-module` on a copy of the `game.dat` you play, and put it in place.
2. `sage-accel build` (or take CI's `sage_accel` artifact), then `sage-accel install C:\RotWK`.
3. Start Edain and play a skirmish. `sage_accel.log` beside `game.dat` should have the banner, the
   arming line with a thread id, and one `Direct3DCreate9(0x20)` line with no "NOT on the arming
   thread".
4. Delete the DLL, or create `sage_accel.off`, and check the game still starts. That is the stock
   fallback, and it must work.

## 9. M1 — the census

`sage_accel/src/census.c`. Nothing it hooks changes behaviour: every hook counts, then calls the
original with the same arguments and returns its result.

**What is hooked.**

- **`IDirect3D9::CreateDevice`**, from the `Direct3DCreate9` wrapper. The thread that calls it
  becomes the game thread.
- **All 119 `IDirect3DDevice9` slots.** `Present` is C, because it ends a frame. The other 118 are
  thunks the module writes at runtime: 50 bytes that read the thread id from `fs:[0x24]`, bump a
  counter and tail-jump to the original. They touch only `eax` and the flags, and never the stack.
- **The `ID3DXEffect` vtable** (79 slots), on the first effect the engine creates. It is reached by
  swapping game.dat's two `d3dx9_27` imports, `D3DXCreateEffect` and `D3DXCreateEffectFromFileA`.
  Both signatures were checked against the engine's only call sites: 9 arguments at `0x00551356`
  and 8 at `0x005513A3`. The count of 79 is the original's own (`push 0x4F` at `0x10040371`) and
  also mingw's.
- **`LockRect` on textures and surfaces, and `Lock` on vertex and index buffers.** Their vtables are
  found by making one throwaway resource per pool right after `CreateDevice`, before the device is
  hooked, so that making them is not counted.

**`game.dat` has no import name table.** Every import descriptor's `OriginalFirstThunk` is 0, so
once the game is loaded its IAT holds only resolved addresses. The first M1 build looked imports up
by name through that table and crashed at startup: a read access violation in the system string
compare, with the `d3dx9_27` IAT (`0x00BD09B4`) on the stack. The import hook now finds a slot by
the address `GetProcAddress` gives for it, and the harness covers it. Any future import hook into
`game.dat` must do the same.

Every vtable is checked before it is hooked: hooking stops at the first slot that does not point at
executable memory. The effect's vtable and the lock vtables must also stay inside the module that
owns slot 0, because their length depends on the DLL's version. **The device's table belongs to the Windows compatibility shim, and M1 has to live with it.**
Four runs on the Edain machine (2026-09-24) established how:

1. The device's vtable sits at a heap address, and its `QueryInterface` is in `apphelp.dll`: the
   shim has copied d3d9's table and hooked entries in it. The same-module rule stopped hooking at
   slot 1.
2. Patched entry by entry, all 119 slots were hooked, and within 10 s every entry had been put back
   (`Present slot is D3D9.DLL+0xE05D0 - REPLACED`). Device calls froze at 317 while effect calls
   kept rising. The engine calls `Reset` during startup (`0x0052220F`), and that is when the shim
   rewrites its table.
3. Giving the device a table of our own crashed inside that `Reset`, calling address 0 from
   `apphelp.dll+0x80D6C`. The shim's `Reset` hook finds its saved original by the device's vtable
   pointer, and the pointer was ours.
4. **So the device is hooked in place, and the hooks are put back whenever they are undone.** Its
   vtable pointer never changes. Every thunk jumps through `g_device_orig`, which each repair
   refreshes from the table, so the functions the shim installs are the ones our hooks call.
   `Reset` itself is a C hook that calls through and then repairs. The watchdog repairs anything
   else it finds rewritten, and follows the device if it is ever moved to another table.

`status:` lines report how many slots were still ours and how many repairs have happened; `census:
N device slots hooked again after Reset` should appear once per `Reset`.

**What is counted.** The queued/draining split per device method is the original's
([`accel-queue.md`](accel-queue.md)). It is generated into `src/vtables.h` by `sage_accel/gen.py`,
with slot names from the mingw headers. A **stall** is a draining call or a lock made while
something is queued. That is exactly when M2's game thread would have to wait for the worker.
Consecutive getters therefore cost one stall, not one each. Calls from other threads, such as the
load screen, are counted apart.

**The report**, every 30 s of game-thread `Present`s, in `sage_accel.log`:

```
report: 30.0 s, 1790 frames, 59.6 fps, frame avg 16.759 ms, max 45.210 ms
  device calls/frame: ... (queued ..., draining ...); STALLS/frame ..., worst frame ...
  stalls/frame by device method: ...
  texture|surface|vb|ib locks/frame: ... (discard, nooverwrite, readonly, other), stalls/frame ...
  draining methods/frame: ...      queued methods/frame: ...      effect methods/frame: ...
  other threads, whole window: ... device calls, ... effect calls, ... locks
```

**How to read it for M2.** Every stall costs one round trip to the worker. So stalls per frame,
multiplied by a round trip of a few tens of microseconds, is what M2 adds back to each frame. The
by-method line says which calls to remove first. If most stalls are effect-internal getters or
`GetRenderState`, a state shadow like the original's dedupe removes them. If most are locks, M4's
mirrors are required before M2 can win.

**Known blind spots.** Cube and volume texture locks are not hooked. Swap-chain `Present` is not
hooked either: if the engine presents that way, no report appears, and that absence is itself the
answer. An effect that d3dx9_27 creates through another entry point would not be counted.

### First results, 2026-09-24

One short Edain session: loading, then about a minute of play. The second report is the gameplay
window:

```
report: 30.0 s, 905 frames, 30.2 fps, frame avg 33.150 ms, max 74.576 ms
  device calls/frame: 4463.7 (queued 4043.9, draining 419.8); STALLS/frame 146.5, worst frame 159
  stalls/frame by device method: AddRef 87.2, GetDepthStencilSurface 3.0, GetBackBuffer 1.0, ...
  vb locks/frame: 81.3 (discard 3.1, nooverwrite 77.3, ...), stalls/frame 52.3
  ib locks/frame: 29.3 (discard 2.0, nooverwrite 26.3, ...), stalls/frame 2.0
  draining methods/frame: AddRef 205.8, Release 205.7, TestCooperativeLevel 4.0, ...
  queued methods/frame: SetTextureStageState 881.0, SetSamplerState 815.0, SetRenderState 641.0, ...
  effect methods/frame: SetVector 282.8, SetTexture 185.6, ... CommitChanges 76.3, Begin 17.5
```

- **The hooks hold.** All 119 device slots held for the whole session: one repair after the startup
  `Reset`, and two by the watchdog.
- **The load screen was seen.** 11 `Present`s and 1,584 device calls came from another thread during
  loading, which is [`multicore.md`](multicore.md) §1.1's second drawing thread measured.
- **About 146 stalls per frame** under the original's rules, from three sources:
  - **~87: the device's `AddRef`/`Release` pairs**, 206 of each per frame. The build that produced
    this log counted every non-queued method as draining, so the stalls were pinned on `AddRef`. The
    original treats `AddRef` as direct but drains on the device's `Release`, so the same stalls
    belong to `Release`. The census now uses the original's three-way split exactly: `DIRECT` in
    `gen.py`, 22 methods including `AddRef` and every `Create*`. **This one is avoidable:** only the
    last `Release` of the device needs the queue drained, and that happens at shutdown.
  - **~54: dynamic vertex and index buffer locks**, nearly all `D3DLOCK_NOOVERWRITE`. The original
    mirrors these (record kind `3`, [`accel-queue.md`](accel-queue.md) §3), so **M2 needs M4's
    buffer mirror before it can win**, or at least that part of M4.
  - **~5: real getters** (`GetDepthStencilSurface`, `GetBackBuffer`, `TestCooperativeLevel`).
- **This window says nothing about frame time yet.** It ran at the 30 fps cap, with a 33 ms average
  frame, so the game was not render-bound. The measurement that decides M2 needs a late-game scene
  that falls below the cap.

### Late game, 2026-09-24

Nine minutes of an Edain skirmish, with the corrected three-way split. The frame rate fell from the
30 fps cap to 13.5 fps. The heaviest reports:

| fps | frame | device calls | effect calls | stalls | `Release` | VB locks (`NOOVERWRITE`) | VB lock stalls |
|---|---|---|---|---|---|---|---|
| 17.6 | 56.7 ms | 38,122 | ~55,000 | 599 | 382 | 934 (923) | 213 |
| 13.5 | 74.0 ms | 29,843 | ~41,000 | 499 | 320 | 757 (742) | 175 |
| 16.8 | 59.7 ms | 21,285 | ~26,000 | 375 | 220 | 591 (583) | 150 |

All per frame. Getters stay at about 3 per frame (`GetDepthStencilSurface`), and index-buffer
locks almost never stall.

**What it settles.** Under the original's rules M2 would stall 400 to 600 times a frame. Two changes
take that to about 3:

1. **Device `Release` is direct** unless it is the last one.
2. **`NOOVERWRITE` buffer locks are mirrored**, which is M4's buffer half. In practice that part of
   M4 comes before M2.

It also shows the volume a render thread would move: 30,000 to 40,000 device calls per frame. More
effect calls than that stay on the game thread until M3.

**What it does not settle** is how much time that volume costs the game thread. The census now
samples the game thread's instruction pointer every 4 ms (after resuming it, so no lock matters)
and files each sample by module. It also times `Present` itself. The report's `game thread time by
module` line says how much of the frame is spent in `d3d9`, `d3dx9` and the driver. That share is
the ceiling on what a render thread can save; time inside `Present` is GPU wait, which it cannot
save.

### Playing M1

1. Rebuild: `sage-patch apply accel-module` is unchanged, so only the DLL needs replacing. Run
   `sage-accel build`, then `sage-accel install <game dir>`.
2. Play one skirmish of several minutes that reaches a large late-game army, and also sit on the
   loading screen once.
3. Send back `sage_accel.log`. The reports from the heaviest part of the match are what M2 is
   costed from.
