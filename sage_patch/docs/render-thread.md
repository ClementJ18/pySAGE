# Moving the Direct3D work off the game thread — scoping notes

What OH1A's BFME2 Accelerator, `bfme2_accel.dll`, does, and which of it is a static `sage_patch`
patch. ROTWK `game.dat` build `2.01.2614.37001`, ImageBase `0x400000`, no ASLR; the file offset is
`VA - 0x400000` for every site cited here.

The DLL ships a render thread **against this exact binary** — the design
[`multicore.md`](multicore.md) §3.2 describes as the one that works. §2 establishes the "exact
binary" claim, because everything else rests on it. [`accel-module.md`](accel-module.md) is the
patch that loads the DLL from `game.dat`.

## 0. How this was read, and what is therefore not established

`bfme2_accel.dll` (811,520 bytes, PE32, ImageBase `0x10000000`, 5 sections) was read on
2026-09-20 from:

- its **section table, import directory and export directory**, parsed with `sage_patch.pe`;
- its **build-recognition table** at file offset `0xAD0D8`, four 28-byte records, decoded in §2;
- its **diagnostic string table**, ~1,200 printable strings, which is where the entire feature
  inventory in §3 comes from;
- and, for every engine address those strings cite, the **bytes at that address in our own
  `game.dat`**, which is the cross-check in §2.

**This read did not disassemble its machine code.** Every claim in §3 about *how* a feature works is
the DLL's own diagnostic text, quoted, not a reading of its instructions — except the render
thread's thread identity and queue, which are read from instructions in
[`accel-thread-identity.md`](accel-thread-identity.md) and [`accel-queue.md`](accel-queue.md). The
README's warning applies in the other direction here: a wrong reading of somebody else's log
messages passes no test at all. Treat the rest of §3 as an inventory of intent and §5's Tier 1 as
the only part costed against real bytes.

**What the import table does establish**, and it is worth stating because the companion
`bfme2_accel_loader.exe` was quarantined by Defender on contact (a generic trojan heuristic —
the ordinary outcome for a `CreateRemoteThread` injector, and not by itself evidence of anything):
the DLL imports **`KERNEL32` (121), `USER32` (5), `ADVAPI32` (3)** and nothing else. No `d3d9`, no
`d3dx9_27` — both are resolved from the game's already-loaded modules, which is why it hooks
vtables rather than an IAT. No winsock, no WinINet, no registry. The three `ADVAPI32` imports are
`OpenProcessToken` / `LookupPrivilegeValueA` / `AdjustTokenPrivileges`, and the DLL carries the
string `SeLockMemoryPrivilege`, which is large-page backing for its allocator. It exports fifteen
`AotrRtTest*` entry points, so the author drives it from a test harness.

None of that is an audit. It is the shape of the thing.

## TL;DR

- **It targets our binary.** Not a cousin of it — the same build, confirmed four ways in §2. Every
  engine address in its diagnostics is directly usable by us, today, with no porting.
- **The W3D global mutex does not block it.** It serializes a render thread that *shares* the
  renderer. This DLL **moves** it, so the worker is the only thread that ever calls D3D and the
  lock is uncontended — provided the load screen's thread is kept out (§4.1). Then it converts the
  lock to a user-mode one so that uncontended case is cheap.
- **The engine already profiles its own render.** It instruments the render in **thirty named
  scopes** — a `PerfScope` RAII class at `0x00517690` / `0x00517740` — each opening a PIX event
  through `D3DPERF_BeginEvent`, resolved into `0x00DD361C` at device init and inert with no profiler
  attached. [`perf-stage-readout`](perf-stage-readout.md) is the consumer (§5.1).
- **Almost none of the DLL is portable to a `sage_patch` patch, and that is the real finding.**
  A D3D9 command-queue marshaller, an `rpmalloc`, an SSE CRT and a worker pool are not cave
  assembly. §5 splits the inventory into six things that are genuinely static patches and
  everything else, which is Tier 2.
- **Tier 2 stays OH1A's.** `sage_patch` ships no module of its own: [`accel-module`](accel-module.md)
  loads his DLL from `game.dat`, and the fixes it needs on a patched binary go to his repository
  (§6). Tier 1 is the whole of what this repository builds.

## 1. What the DLL is

`BFME2 Accelerator v47 PRODUCTION build`, by its own banner. Its environment variables and marker
files are prefixed `AOTR_`, so it comes from the Age of the Ring side of the community; the build
table in §2 lists Edain and stock 2.02 as supported alongside it.

It installs at load time, identifies the host binary, and then turns on a set of largely
independent features — each of which **self-checks against the stock code path and disables itself
on any mismatch**. That discipline is worth naming up front, because it is the reason a thing this
invasive is shippable at all, and it is the part of the design most worth copying regardless of
what else is done:

```
rlsort:  SELF-CHECK MISMATCH on a list of %u (comparator %08X) - stock sort for the rest of the session.
pick:    a repeated query in one frame returned a different result - memo OFF for this session (after %d checks).
drawgen: a recipe did not reproduce the payload - ... that mesh is left to the engine.
preshader: cache LIVE (noop=%d). Self-checking, auto-reverts on any mismatch.
```

Every feature also has an off switch (`AOTR_RT=0`, `SLICER_OFF`, `AOTR_POSEWARM2=0`, …), and two
are toggleable **live from the keyboard** — Scroll Lock for the render thread, Pause/Break for the
logic spreader. A/B measurement in one session, without a restart.

## 2. It targets our binary

The table at file offset `0xAD0D8` is four 28-byte records of
`(textSum, timeStamp, size, headerSum, entryRVA, namePtr, flag)`:

| # | textSum | stamp | size | headerSum | entry RVA | name | flag |
|---|---|---|---|---|---|---|---|
| 0 | `5ED63115` | `460DA09E` | `00AD4000` | `00ADC2F6` | `0063D082` | `RotWK 2.02 (Age of the Ring, Edain, stock 2.02)` | 1 |
| 1 | `DE0F8163` | `460DA09E` | `00AD4000` | `00ADC2F6` | `0063D082` | `RotWK 2.02 delayfix` | 0 |
| 2 | `8C81C601` | `460DA09E` | `00ACA000` | `00BAF85F` | `0063D082` | `RotWK 2.02 build 820` | 0 |
| 3 | `32667B9B` | `00564544` | `00ADA000` | `00BC0776` | `00629306` | `BFME2` | 0 |

Our `game.dat` (11,346,944 bytes) carries `TimeDateStamp 460DA09E`, header checksum `00ADC2F6`
and entry RVA `0063D082` — **record 0 on three fields of three**, and record 0 is the only one
with the flag set. (`size` reads `00AD4000` against our `SizeOfImage` of `00AD3000`; that is the
one field that does not match exactly and it is not worth chasing, because the fourth check below
is stronger than all of them.)

The decisive check is the addresses. Thirteen engine addresses appear in the DLL's diagnostic
strings. Every one of them lands where the string says it should, in **our** file:

| DLL string | VA | bytes at that VA in our `game.dat` | reads as |
|---|---|---|---|
| `pose fn ... (expected 005A4A70)` | `0x005A4A70` | `56 8b f1 83 be 00 01 00 00 02` | prologue |
| `ThingTemplate::isEquivalentTo 0x73D5C2` | `0x0073D5C2` | `55 8b ec 83 ec 0c 53 56 8b f1` | prologue |
| `object filter 0x763543` | `0x00763543` | `b8 5a 26 b9 00 e8 a3 99 2d 00` | prologue (`__chkstk`) |
| `brute-force mesh cast 0x56C600` | `0x0056C600` | `83 ec 18 53 55 8b e9` | prologue |
| `view scene pick 0x48AB28` | `0x0048AB28` | `b8 dd 3d b7 00 e8 be 23 5b 00` | prologue (`__chkstk`) |
| `MAPPER installed at ... (expected 00470176)` | `0x00470176` | `55 8b ec b8 44 a1 00 00` | prologue |
| `scene render 0x47177E hooked` | `0x0047177E` | `55 8b ec 83 ec 28 53 56` | prologue |
| `DrawPixel 0x5165E0` | `0x005165E0` | `83 ec 24 56 8b f1 83 3e 00` | prologue |
| `alpha 0x5166C0` | `0x005166C0` | `83 ec 24 56 8b f1 83 3e 00` | prologue |
| `HLod transform update 0x59CD70` | `0x0059CD70` | `83 ec 4c 53 55 56 57 8b d9` | prologue |
| `tree update 0x5A5050` | `0x005A5050` | `83 ec 30 56 8b f1` | prologue |
| `logic module updates (0x62EA97)` | `0x0062EA97` | `8d 4b 10 8b 01 ff 10 83 f8 01` | mid-function call site |
| `0x456D8B list walk replaced` | `0x00456D8B` | `55 8b ec 83 ec 18 53 57 8b 7d 08` | prologue |

Eleven clean function prologues and two mid-function sites that the strings describe *as* call
sites. That is not a coincidence across thirteen addresses, and the shroud (`0x0047308C`,
`0x00473EB3`) and perf-event (`0x00DD361C`, `0x00DD3620`) sites check out the same way.

**So: no porting. Every address the DLL names is an address we can use.**

## 3. The inventory

From the diagnostic strings, and subject to §0's caveat. Grouped by what it would take a static
patch to have the same thing.

### 3.1 The render thread — the headline

`rt:`. Hooks the `ID3DXEffect` vtable (79 slots) and the `IDirect3DDevice9` vtable, plus wrapper
classes for `Texture`, `Surface`, `SwapChain`, `CubeTexture`, `VolumeTexture`, `VertexBuffer`,
`IndexBuffer`, `StateBlock`, `VertexShader`, `PixelShader`, `VertexDeclaration` and `Query`.
Every D3D9 and D3DX-effect call is then marshalled onto a worker thread through a command queue;
the game thread enqueues and moves on.

```
rt: RENDER THREAD LIVE - device %p, game thread %u, worker thread %u.
    All D3D9 and D3DX effect work now runs on the worker (per-call object refs %s).
```

The hard parts are all visible in its counters and its sub-features, and they are the parts any
reimplementation would spend its time on, not the queue:

- **Lock mirroring.** `LockRect` / `Lock` must return a pointer *now*, on the game thread, for a
  call that has not executed yet. It keeps shadow copies — `tex mirrors adopted %d locks %d
  dropped %d failed %d`, same for buffers — and queues the real upload.
- **Engine-side write paths that bypass the device.** Three of them are special-cased by address:
  the shroud updates (`0x0047308C` / `0x00473EB3`), the per-pixel surface writes
  (`DrawPixel 0x005165E0`, `alpha 0x005166C0`), and the radar's `SurfaceClass` locks. Each is
  version-checked and each falls back to synchronous on a mismatch.
- **Redundancy elimination**, which is where much of the win probably is: `AOTR_FXDEDUPE`
  (effect-parameter sets that repeat the last value), `AOTR_DEVDEDUPE` (vertex inputs),
  `AOTR_FXBATCH` (parameter batching), and a `redundant %s%%` column in the report.
- **A bail-out.** `the game installed an ID3DXEffectStateManager - render thread switched OFF`.

**Not portable.** This is thousands of lines of C++ with per-interface knowledge of D3D9.

### 3.2 The rest

| feature | what it is | portable as a static patch? |
|---|---|---|
| `alloc` | `rpmalloc` swapped onto `msvcr71`'s `malloc`/`calloc`/`realloc`/`free` by IAT patch, freezing threads to do it | **No** — the allocator is the payload |
| `fastcrt` | SSE/SSE4.1 replacements for 16 `msvcr71` imports (`memcpy`, `memset`, `strlen`, `fabs`, `floor`, …) by IAT patch | **No** — same reason |
| `preshader` | caches the `d3dx9_27` preshader interpreter's results | **No** — hooks a Microsoft DLL, not `game.dat` |
| `pose-warm2` | skeleton tree updates for the objects a pass will draw, run on worker threads; hooked at scene render `0x0047177E`, self-checked per object | **No** — needs a pool |
| `rlsort` | replacement render-list sort / push / clear, validated against the stock comparator at startup | **No** — a sort routine, not a gate |
| `drawgen` | learns a per-mesh "recipe" that rebuilds the three per-draw effect parameters from the mesh transform and its skeleton pivots, instead of walking the parameter bindings; a recipe must reproduce the engine four times before it is used, and 1 draw in 32 is still checked | **No** |
| `equiv-memo` | memoizes `ThingTemplate::isEquivalentTo` (`0x0073D5C2`) per template pair, cleared each new game | **Conceivably** — but a cave-sized hash map is a poor trade |
| `filter-memo` | memoizes the object filter's template checks (`0x00763543`) per (filter, template) | same |
| `pick` | memoizes repeated view picks in a frame (`0x0048AB28`), and skips brute-force mesh casts whose bounding box the ray misses (`0x0056C600`) | **The box pre-test, yes** — that is a gate, and gates are what caves do well |
| `audiolimit` | replaces the sound-request-limit list walk at `0x00456D8B` with an index, proving itself against the walk first | **No** — needs the index |
| `logicspread` | leaves the engine's six logical update calls **unchanged and in order** and places render frames *inside* that sequence by measured time, at 9 sites. Pause/Break toggles it | **Possibly** — see §4.3 |
| `devlock` | replaces the engine's device kernel mutex with a user-mode recursive lock, 4 call sites | **Yes** — §5.2 |
| `mutexcs` | same for the engine's generic `MutexClass`; unnamed mutexes become user-mode recursive locks | **Yes** — §5.3 |
| Present / device loss | v47's banner: *"Present now reports device loss to the engine - the alt-tab crash"* | **Doubtful** — §5.5 |
| `stages`, `phases`, `fx-timers`, `clienttime`, `subsys`, `modtime`, `flushtime`, `gs` sampler, `crashlog`, scene capture | the diagnostic half: a 100 Hz game-thread sampler, per-stage and per-call timers, a 30-second report | **The engine's own half, yes** — §5.1 |

## 4. What the design means for the engine's render lock

### 4.1 The render thread is not blocked by the W3D lock

`WW3D::Lock` (`0x0051EEC0`, 123 callers) serializes any two threads that both enter the renderer
([`multicore.md`](multicore.md) §3.2). The DLL's design does not let them: **every** D3D call moves
to the worker; the game thread enqueues a command and returns. There is one thread in the renderer,
as before — a different one. The lock is then uncontended, and §5.2 makes the uncontended path
cheap.

**Conditional on the second drawing thread.** The load screen ([`multicore.md`](multicore.md) §1.1)
enters the render layer on its own thread while a map loads, so "the worker is the only thread that
ever calls D3D" is something the DLL must arrange, not something the design gives it. It arranges it
with one thread-identity rule and one critical section
([`accel-thread-identity.md`](accel-thread-identity.md)); on an unrecognised build it guesses the
game thread wrong and crashes with `D3DERR_INVALIDCALL` on the load-screen thread's own loop at
`0x0065CE76` ([`accel-port.md`](accel-port.md) §1).

### 4.2 The `D3DCREATE_MULTITHREADED` byte

[`multicore.md`](multicore.md) §3.3: `0x005240E1` (`83 C0 40` → `83 C0 44`) is strictly a loss on
its own. It belongs only with a design that moves the renderer, never alone.

Verified unchanged in our file:

```
005240d2  81 bc 24 cc 00 00 00  01 01 fe ff   cmp [esp+0xCC], 0xFFFE0101
005240dd  1b c0                                sbb eax, eax
005240df  24 e0                                and al, 0xE0
005240e1  83 c0 40                             add eax, 0x40      <- the byte
005240e4  a8 40                                test al, 0x40
005240e6  a3 5c 34 dd 00                       mov [0x00DD345C], eax
```

### 4.3 `logicspread` is not "update at 30, draw at 60"

[`multicore.md`](multicore.md) §3.4 and [`render-rate.md`](render-rate.md) §8 rule out "update at
30, draw at 60" because client content is counted in *client frames* — particle lifetimes, W3D
animation cursors, APT playback, and the drawable interpolation cache.

`logicspread` does not do that. Its own description is careful about exactly this:

```
logicspread: v26 - the engine's six logical update calls run unchanged and in order;
             render frames are placed inside that sequence by measured time (9 sites).
```

The count of client frames is untouched; only *when* they occur within the logic step moves. That
is a different proposition, and the negative result does not refute it. It is also the one item in
§3.2's table that might be expressible as a set of caves, and it interacts with
[`interpolation-alpha.md`](interpolation-alpha.md) — both are about where a rendered frame sits
between two logic frames. **Do not cost this before §5.1 has measured a frame**; it is the item
most likely to be a mirage.

## 5. Tier 1 — what is a `sage_patch` patch today

Six items, all static, all inside what `sage_patch` already does. In the order they should be done.

### 5.1 `perf-stage-readout` — turn on the profile the engine already produces

**Built, and run live.** It is the registered `perf-stage-readout` patch, and
[`perf-stage-readout.md`](perf-stage-readout.md) is its write-up.

**Thirty stages.** The engine does not scatter `D3DPERF_BeginEvent` calls through the render; it has
a class. `PerfScope` (`0x00517690` / `0x00517740`) is a stack-allocated RAII object with **thirty
constructor callers and thirty matching destructor callers**, each naming one stage — twenty-eight
distinct names, from `UpdateShadowMap` and `RenderViews` down to `RenderTerrainTracks`,
`MeshDX8Render` and `MeshFXShader`.

**The hook is on the constructor, not the D3DPERF pointers.** The constructor `strncpy`s the name
into the object on its fourth instruction, so by the time the wrapper at `0x0051ECE0` sees a name,
the pointer is `[ebp-0x158]` — **one address shared by the four scopes of the frame's draw**.
Installing a begin/end into `0x00DD361C` / `0x00DD3620` and keying on that pointer would fold
`UpdateShadowMap`, `UpdateWaterReflection`, `RenderViews` and `RenderUI` into a single row. The
patch hooks the constructor and keys on the call site.

The two pointers are resolved from `d3d9.dll` at `0x005251D7` / `0x005251EA` and do nothing with no
profiler attached, so the instrumentation is complete and its output discarded. The patch adds a
`.perfstg` section that stamps `QueryPerformanceCounter` (IAT `0x00BD02E8`) onto a nesting stack and
accumulates inclusive and exclusive ticks per stage. It leaves the D3DPERF pointers alone, so a PIX
capture still works unchanged.

**This answers `multicore.md` §6.1 and most of §6.2.** It is what says whether the render is where
a heavy frame goes and which stage owns it. Client-local, no INI change, no replay or network
effect.

**And it found a better patch than itself, also built.** The scope constructor spends
two `strncpy`s, a 13-byte inline copy and a `strlen` per scope — *per mesh*, for `MeshDX8Render` —
building a name string that is then widened into a second buffer and handed to a function that
returns without reading it. `strncpy` pads to `n` and the first call passes `0x100`, so it writes
**256 bytes whatever the name is**. That is `perf-scope-skip`
([`perf-scope-skip.md`](perf-scope-skip.md)): it asks `D3DPERF_GetStatus` — the one D3DPERF export
the engine never resolves, and the only test that works, since `D3DPERF_BeginEvent` is exported
whether or not anyone is listening — and when the answer is no, sends the scope down the engine's
own do-nothing exit. The two patches hook the same function nine bytes apart and are
order-independent, so the pair is what to run: the profile, without the measurement paying for a
string.

### 5.2 `device-lock` — the W3D mutex as a user-mode lock

`multicore.md` §7.1 proposes *skipping* the W3D lock when no second thread is drawing. The DLL does
something strictly safer and gets most of the same win: it keeps the mutual exclusion and changes
the primitive.

```
devlock: engine device mutex replaced by a user-mode recursive lock (4 call sites).
```

Today, one guarded scope costs two kernel-object operations plus two critical-section pairs.
`WW3D::Lock` at `0x0051EEC0`, verified unchanged in our file:

```
0051eec0  a1 d8 1f dd 00      mov  eax, [0x00DD1FD8]       ; the mutex
0051eec5  68 20 4e 00 00      push 0x4E20                  ; 20 000 ms
0051eecb  ff 15 34 02 bd 00   call [WaitForSingleObject]
0051eed1  3d 02 01 00 00      cmp  eax, 0x102
```

with the handle created at `0x0052506B` (`ff 15 1c 02 bd 00` / `a3 d8 1f dd 00`) and released in
`WW3D::Unlock` at `0x005208D0`.

**The patch:** replace the `CreateMutexA` result with a handle-shaped token and redirect the
wait/release pair onto an owned `CRITICAL_SECTION` in the cave — or, more simply, detour
`0x0051EEC0` / `0x005208D0` onto cave bodies that take a recursive critical section and keep
`0x00DD34C8` (owner id) and `0x00DD34CC` (recursion count) written exactly as the stock bodies
write them, since other code reads them. **`0x0051EEA0`, the "this thread owns the device"
predicate, must keep answering identically** — that is the correctness condition and where the
review time goes.

Unlike §7.1 this is safe with the load screen up, because exclusion is preserved. It is worth doing
**without the DLL too**, and §5.1 sizes it first.

### 5.3 `mutex-critical-section` — the same, for `MutexClass`

The DLL's `mutexcs` extends §5.2 to the engine's generic wrapper: *"unnamed mutexes created from
now on use a user-mode recursive lock"*, plus a mention of render-object `Set_Transform`. Same
argument, wider blast radius, and it needs the `MutexClass` constructor located first —
**not established here.** Cost it after §5.2 has shipped and §5.1 says the lock traffic is real.

### 5.4 `pace-sleep` — the frame limiter stops burning a core

`multicore.md` §7.2, unchanged, and worth restating because **the DLL does not do this** — it is
additive to everything above. The main loop paces on `Sleep(0)`:

```
0063a1dc  ff 15 b4 03 bd 00   call [Sleep]
0063a1e2  ff 15 20 09 bd 00   call [timeGetTime]
...
0063a1f3  72 e7               jb   0x0063A1DC
```

At 30 fps that is a thread at 100% for most of every frame. Sleep the whole-millisecond part and
spin only the remainder. A few bytes. Read `render-rate.md` §8 before touching the `ftol` at
`0x0063A1AD`.

### 5.5 `present-device-loss` — probably not an engine defect

v47's headline: *"Present now reports device loss to the engine - the alt-tab crash"*. Read from
the DLL's machine code, that describes **a regression its own queue introduced, repaired**: the
DLL's `Present` wrapper (`0x10008790`) enqueues the call and returns the global `0x10153DE4` — the
result of a *previous* `Present`, with the game thread throttled to at most one outstanding
(`0x10042940` blocks while `0x10153DE0 > 1`), so the engine sees a result at most one frame stale
([`accel-queue.md`](accel-queue.md)).

And the engine is not naive here. It consumes device loss at five sites — `0x00516C5A`,
`0x00517B5C`, `0x005221F7`, `0x00522675`, `0x00522837` — each calling `[ecx+0xC]`
(`TestCooperativeLevel`) on the device at `0x00DD3474` and branching on `D3DERR_DEVICELOST`
(`0x88760868`) and `D3DERR_DEVICENOTRESET` (`0x88760869`). There is a complete device-lost path in
stock.

**Not established:** whether the engine also checks `Present`'s own `HRESULT`. That is the one
reading under which a stock-engine patch here exists; the place to look is near the `CreateDevice`
calls at `0x005241B6` / `0x00524222` and the device-lost path around `TestCooperativeLevel`.

### 5.6 `pick-box-pretest` — the one memo shaped like a gate

Of the DLL's four memoization features, exactly one is expressible as a cave: skipping a
brute-force mesh ray cast (`0x0056C600`) whose bounding box the ray misses. That is a test and an
early return, which is what caves are for. The DLL proves it 3,000 times before trusting it and
still samples 1 in 16 afterwards; a static patch cannot self-check like that, so the proving has to
happen once, offline, and be written into the document instead. Low value alone — **do it only if
§5.1 says picking is on the profile.**

## 6. Tier 2 — the DLL's own territory

Everything else in §3 needs a companion module. There is no honest way to write a D3D9 command
queue, an `rpmalloc` and a worker pool as cave assembly.

**That module is OH1A's.** He has given full permission to use his work to recreate a pySAGE patch
of it, and publishes its source under the MIT licence, but `sage_patch` ships no module of its own:
[`accel-module`](accel-module.md) makes `game.dat` load `bfme2_accel.dll` itself, and the fixes the
DLL needs on a patched binary — its build gate is a checksum over the whole of `.text`
([`accel-port.md`](accel-port.md) §1.1) — live on a fork of his repository, to be offered upstream
([`accel-module.md`](accel-module.md) §3). As of 2026-10-15, Accelerator 2.0 does not yet run Edain
with or without those fixes ([`accel-module.md`](accel-module.md) §4). The technical points that
shape that arrangement:

- **A cave, not an import descriptor, loads the DLL.** With an import descriptor Windows refuses to
  start a `game.dat` whose DLL is absent; with the cave the patched binary runs unchanged without
  it. Either way there is no injector, no `CreateRemoteThread` and no second process — the thing
  Defender quarantines.
- **The engine's own module-load site is a poor hijack.** `0x006056E5` `LoadLibraryA`s
  `DebugWindowLite.dll` into `0x00DE3B98` — but only behind `-scriptDebug2` / `-scriptDebugLite`
  (see [`script-debug-window.md`](script-debug-window.md) §1), so it is not an unconditional load
  site.
- **The engine's allocator is already thread-safe** ([`multicore.md`](multicore.md) §3.5:
  `GeneralAllocator::Init` installs a critical section at `+0x4E4`), so a worker may allocate
  through the game's own heap with no patch.

## 7. Order of work

1. **Measure.** A late-game Edain match with a large army: the twenty-eight named stages out of
   the `.perfstg` block ([`perf-stage-readout.md`](perf-stage-readout.md), with
   [`perf-scope-skip.md`](perf-scope-skip.md) beside it), and the lock traffic from §5.2 while you
   are there. Everything below is waiting on it.
2. **§5.2 `device-lock`** if the lock traffic is real; **§5.4 `pace-sleep`** regardless, it is a
   few bytes.
3. **§5.5's open question** — whether the engine checks `Present`'s `HRESULT` — as an independent
   RE task.
4. **§4.3's `logicspread`**, costed against a real profile rather than a description of one.

## Address table

Everything below was read from our `game.dat` on 2026-09-20, not from the DLL.

| VA | what |
|---|---|
| `0x005251B0`..`0x005251EA` | the `D3DPERF_*` resolve; `0x005251D7` stores `BeginEvent`, `0x005251EA` stores `EndEvent` |
| `0x00525820`..`0x0052584A` | the mirror teardown — clears all four pointers |
| `0x00DD361C` / `0x00DD3620` | `D3DPERF_BeginEvent` / `D3DPERF_EndEvent`; `0x00DD3624` `SetMarker`, `0x00DD3628` `SetOptions` |
| `0x0051ECE0` / `0x0051ED61` | the engine's begin / end wrappers (§5.1) |
| `0x00BD9DBC` / `0x00BD9DC8` / `0x00BD9DEC` / `0x00BDC3F4` / `0x00BEA790` | `RenderUI`, `RenderViews`, `UpdateShadowMap`, `RenderParticles`, `RenderFXShaderBatch` |
| `0x0051EEC0` / `0x005208D0` | `WW3D::Lock` / `Unlock` (§5.2) |
| `0x0052506B` | `CreateMutexA`, storing to `0x00DD1FD8` |
| `0x00DD1FD8` / `0x00DD1F80` | the W3D mutex handle and its critical section |
| `0x00DD34C8` / `0x00DD34CC` | owning thread id and recursion count — must stay consistent (§5.2) |
| `0x0051EEA0` | "this thread owns the device" predicate — the correctness condition for §5.2 |
| `0x005240E1` | the `D3DCREATE_MULTITHREADED` byte, `83 C0 40` → `83 C0 44` (§4.2) |
| `0x005241B6` / `0x00524222` | the two `IDirect3D9::CreateDevice` calls (§5.5) |
| `0x0063A1DC` | the `Sleep(0)` pace spin; `0x0063A1AD` the `ftol` (§5.4) |
| `0x006056E5` | `LoadLibraryA("DebugWindowLite.dll")`, handle to `0x00DE3B98` (§6) |
| `0x0056C600` | the brute-force mesh cast (§5.6) |
| `0x0048AB28` | the view scene pick |
| `0x0047177E` | the scene render the DLL hooks for parallel skeleton updates |
| `0x0047308C` / `0x00473EB3` | the shroud texture updates |
| `0x005165E0` / `0x005166C0` | the engine's per-pixel surface writes |
| `0x0073D5C2` / `0x00763543` | `ThingTemplate::isEquivalentTo` / the object filter |
| `0x00456D8B` | the sound-request-limit list walk |
| `0x0062EA97` | the logic module update call site |
| `0x005A4A70` / `0x0059CD70` / `0x005A5050` | `Single_Anim_Progress`, HLod transform update, tree update |
