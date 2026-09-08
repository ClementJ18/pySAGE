# Making the engine use more than one core — scoping notes

Scope for a hypothetical `multicore` patch. ROTWK `game.dat` build `2.01.2614.37001`, ImageBase
`0x400000`, no ASLR; the file offset is `VA - 0x400000` for every site cited here. Read
**statically** on 2026-08-18 with `pefile` + `capstone` from
`sage_patch/engine/game.dat.backup`
(11,346,432 bytes). **Every site cited below was re-checked byte-for-byte against three other
copies** — the repo-root `game.dat`, the Edain-built `game.dat`, and the installed
`C:\Program Files (x86)\Games\bfme\rotwk\game.dat` — and is identical in all four. That matters
here more than usual, because the repo-root file *does* differ from stock inside the pacing code
next door (see [`render-rate.md`](render-rate.md) §0).

## TL;DR

- **There is no "multicore patch."** The frame is one thread by construction, and the two offloads
  everyone reaches for first are each blocked by a property of the engine rather than of an
  implementation. What follows is a program of work with a measurement gate in front of it.
- **The engine is already multi-threaded** — four engine threads plus library threads — and it is
  already *paying* for that. Two of the four are audio (`0x0045E97D`, `0x004A7F55`), one is the
  crash handler (`0x0043D120`), and one is the **load screen** (`0x0065CE28`), which draws.
- **Because the load screen draws, every W3D operation takes a global mutex.** `WW3D::Lock`
  (`0x0051EEC0`) is a `WaitForSingleObject` on a kernel mutex with a 20-second timeout plus a
  critical-section pair; `WW3D::Unlock` (`0x005208D0`) is the mirror plus a `ReleaseMutex`. There
  are **123 direct calls to the acquire, 130 to the release, and 102 more to a release thunk**
  at `0x004428A6`. This is unconditional and always on.
- **The D3D9 device is not created `D3DCREATE_MULTITHREADED`.** The behaviour flags are computed at
  `0x005240D2`..`0x0052410D` into the global `0x00DD345C` and consumed by both `CreateDevice` calls
  (`0x005241B6`, `0x00524222`): hardware or software vertex processing, optionally `PUREDEVICE`,
  optionally `FPU_PRESERVE`. Bit `0x4` is never set. **So the renderer's answer to a second thread
  is serialization, not concurrency** — and any render-thread design inherits that, not the parallel
  version of it.
- **The allocator is already thread-safe, and this is the one green light.** `GeneralAllocator::Init`
  installs a critical section at `+0x4E4` (`0x00433063` tests it, `0x0043307D` stores it) and every
  allocate/free path takes it (`0x004349EA` and eight siblings). A worker thread may allocate and
  free through the game's own heap without a patch.
- **The simulation is CRC'd every logic frame** — the `'crc'` timing scope at `0x0062E7B3` wraps the
  call at `0x0062E7C8` — and runs lockstep. Any logic-side parallelism must be bit-identical to the
  serial order, and must be on every peer.
- **Where the time actually goes is not known.** Nobody has measured a frame on this build. §6 is
  the measurement, and it is the gate: **do not write a line of this patch before it has run.**
- Two adjacent wins that are *not* multicore but are what people usually mean when they ask for it
  are in §7, and they are far cheaper than anything in §5.

## 1. What already runs on which thread

Four `CreateThread` sites live in engine code (the remaining eight, and the three
`_beginthread`/`_beginthreadex` sites, are in the statically linked libraries above `0x009C0000` —
Bink, GameSpy, Miles).

| thread proc | created at | what it is | evidence |
|---|---|---|---|
| `0x0043D120` | `0x0043D295` | **crash handler.** Resolves `OpenThread` out of `kernel32`, then walks and formats the faulting thread's registers | `'EAX:'`/`'EIP:'`/`'Exception in exception handler'` at `0x00BD5B40`.. |
| `0x0045E97D` | `0x00461291` | **audio device servicing.** A stub that forwards its parameter to `0x0045E6FF`; the owner holds an array of `0x48`-byte entries at `+0xBD4` with the count at `+0xBD8`, swept by `0x0045E98F` | `'Miles Fast 2D Positional Audio'`, `'Creative Labs EAX 3 (TM)'`, `'Dolby Surround'` in the same module |
| `0x004A7F55` | `0x004A8098` | **audio request queue.** The `AR_*` command pump | `'AR_Play'`, `'AR_StopMusic'`, `'AR_ActivateMusicSystem'` at `0x00BDF2EC`.. |
| `0x0065CE28` | `0x0065D69C` | **the load screen.** Two-mutex loop: wait `+0x40`, call vtable `+0x118` ("keep going?"), then vtable `+0x124`, `Sleep(0x64)`, poll `+0x44` | `'FadeInGameMovie'`, `'FadeScreenToWhite'` in the same module |

Miles additionally installs its own mixer callback (`AIL_set_sample_processor` at `0x0045B1C1`) and
runs its own threads inside `mss32.dll`.

**Nothing pins itself.** There is no `SetThreadAffinityMask` import and no `GetSystemInfo` call in
engine code, so the engine neither counts cores nor asks for any. `SetThreadPriority` is used eight
times, all inside the library range and the audio layer.

### 1.1 The load screen is the reason the renderer is locked

`0x0065CE28` calls `0x0065C19B` at `0x0065CE4F`, and `0x0065C19B` takes the W3D lock at
`0x0065C1BB` after first checking its own two mutex handles at `+0x40`/`+0x44`. So the fourth
thread genuinely enters the render layer while the main thread is loading a map — which is what the
whole locking discipline in §3.2 exists for, and the only thing that consumes it today.

## 2. The frame, and why it is one thread

[`render-rate.md`](render-rate.md) §2–§3 has the pacing; the shape is what matters here:

```
0x00639EC6   main loop, one iteration = one client frame, paced to FramesPerSecondLimit
  0x00441827   GameEngine::update (vtable 0x00BD84E0 +0x28)
    0x006325A0   the dispatcher, and it owns everything below
      0x006325B0     [0x00DEF548] vtable +0x28
      0x006325B9     [0x00DE3BAC] -> 0x00604189, then 0x00603452 = "should this frame run"
      0x006325CF     this vtable +0x9C = 0x00632409     <- the CLIENT phase
      0x00632622     sub-frame advance, timecode, interpolation alpha
      0x0063264A     the wrap: every 6th client frame ...
      0x006326F0       ... this vtable +0x98 = 0x006329B0   <- the LOGIC phase
```

The client phase at `0x00632409` reaches `TheGameClient` (`0x00DE4388`) vtable `+0x28` at
`0x00632498`, and a dozen other singletons around it. The logic phase at `0x006329B0` opens a
`'logic'` timing scope (`0x006329B3`, name at `0x00BFE350`) and reaches `GameLogic::update`
(`0x0062E4E8`) through `0x00632A82`.

Both phases run on the main thread, in order, inside one call. There is no job system, no fence and
no producer/consumer anywhere in that path. **Multicore here means introducing all of that**, not
enabling something dormant.

The engine does keep a small named-timer registry (`0x00AD9AB0` opens a scope by name, `0x00AD98F0`
closes it) with seven call sites; the four names recoverable statically are `'logic'`, `'crc'`,
`'pathfind'` and `'collision'`. It is not a profiler — there is no per-scope readout in a shipping
build — but it does say which four things EA thought were worth naming.

## 3. The four constraints, in the order they kill designs

### 3.1 Lockstep and the per-frame CRC — kills logic-side parallelism

`GameLogic::update` computes a CRC of simulation state every logic frame:

```asm
0062e7ae  call 0x00A1611E              ; the state to hash
0062e7b3  mov  ebx, 0x00BFDC38         ; 'crc'
0062e7b8  push ebx / call 0x00AD9AB0   ; open the timing scope
0062e7c3  push [ebp-0x14]
0062e7c8  call 0x00625886              ; <- the CRC
0062e7cd  push ebx / call 0x00AD98F0   ; close it
```

Peers compare that number. Anything that changes the *order* in which simulation state is written —
or the floating-point rounding it is written with — desyncs the match and invalidates every replay
across the change. The engine ships EA's own scar tissue from this fight: eighteen
`'CritterDesync: doPathfind…'` format strings at `0x00C10078`.., and a further run of
`'CritterDesync: Pathfinder::SnapClosestGoalPosition()…'` at `0x00C1B900`..

This does not make logic-side parallelism impossible. It makes it **bit-exact or nothing**, on every
peer, with no partial rollout — which is a different and much larger project than "run two things
at once."

The engine carries **227** `'CritterDesync: …'` format strings, fourteen of them
`'CritterDesync: doPathfind<n>'` at `0x00C10078`.. and a further run on
`Pathfinder::SnapClosestGoalPosition` at `0x00C1B900`.. That is EA's own scar tissue from this
fight, in the area §5.3 proposes to go back into.

Note what §3.3 implies for it: `D3DCREATE_FPU_PRESERVE` is set only conditionally (`0x0052410B`,
gated on `0x00DD343C`), so the x87 control word is already a live variable in this build. A thread
created with `CreateThread` starts with the CRT default, **not** with whatever the main thread is
running under. Any worker that touches simulation floats has to set it explicitly.

### 3.2 The W3D global lock — kills the render thread

`WW3D::Lock` at `0x0051EEC0`:

```asm
0051eec0  mov  eax, [0x00DD1FD8]       ; the mutex, CreateMutexA at 0x0052506B
0051eec5  push 0x4E20 / push eax
0051eecb  call [WaitForSingleObject]   ; 20 000 ms
0051eed1  cmp  eax, 0x102 / jne 0x0051EF1C
                                       ; on timeout: "A thread held onto DirectX for more
                                       ;   than 20000ms" (0x00BE6D0C)
0051ef1c  push 0x00DD1F80 / call [EnterCriticalSection]
0051ef27  call 0x00A242C0              ; GetCurrentThreadId
0051ef2c  mov  [0x00DD34C8], eax       ; owning thread
0051ef31  inc  [0x00DD34CC]            ; recursion count
0051ef43  call [LeaveCriticalSection]
```

and `WW3D::Unlock` at `0x005208D0` mirrors it, ending in `ReleaseMutex`. So one guarded scope costs
**two kernel-object operations and two critical-section pairs**, and the scope is the W3D wrapper
layer's own RAII guard — `0x004428A6` is its destructor thunk, with 102 callers, spread across
`0x00442…`–`0x0055A…`, which is the whole DX8/9 wrapper.

Two consequences:

1. **A render thread would not run in parallel with anything.** It would take the same mutex the
   main thread takes, on the same operations, and serialize against it. The parallel fraction would
   be whatever CPU work sits *between* the guarded scopes, which is the part nobody has measured.
2. **This lock is a standing single-thread tax** paid on every frame of every game, for the benefit
   of one thread that only exists during loading. See §7.1.

### 3.3 The device is not multithreaded — so there is no way around §3.2

```asm
005240d2  cmp  [esp+0xCC], 0xFFFE0101  ; vertex shader version
005240dd  sbb  eax, eax / and al, 0xE0
005240e1  add  eax, 0x40               ; 0x40 HARDWARE_VP, or 0x20 SOFTWARE_VP
005240e4  test al, 0x40
005240e6  mov  [0x00DD345C], eax
005240f4  or   al, 0x10                ;   | PUREDEVICE, conditionally
0052410b  or   al, 2                   ;   | FPU_PRESERVE, if [0x00DD343C]
0052410d  mov  [0x00DD345C], eax
...
005241af  push [esp+0x1C] … push [0x00DD345C] … call [edx+0x40]   ; IDirect3D9::CreateDevice
```

`D3DCREATE_MULTITHREADED` is `0x00000004` and is never set. Setting it is genuinely a one-byte edit
— `83 C0 40` at `0x005240E1` becomes `83 C0 44`, and the `test al, 0x40` two bytes later is
undisturbed — but **setting it alone is strictly a loss**: it makes the D3D runtime take its own
internal lock on every call, buying nothing while W3D still serializes everything itself. It is a
prerequisite for a design that does not exist yet, not a patch.

D3D9 is loaded dynamically (`LoadLibrary("D3D9.DLL")` at `0x00525176`, `Direct3DCreate9` resolved at
`0x00525195`), so the device object is reachable but there is no import to hook.

### 3.4 Client content is counted in client frames — kills the "update at 30, draw at 60" split

This one is already settled and paid for: [`render-rate.md`](render-rate.md) §8 built that patch,
ran it in a game, and withdrew it. Particle lifetimes, W3D animation cursors and APT playback all
advance one unit per client frame, and the interpolation cache at `Drawable+0x204` is stamped with
the client frame, so gating the client update to every second iteration returns a duplicate frame.
Read §8 before proposing any variant of this; the negative result is the expensive part.

### 3.5 The allocator — the one thing that does not block you

`GeneralAllocator::Init` (`0x00433050`):

```asm
00433063  cmp  [esi+0x4E4], ebx        ; mutex pointer null?
0043306e  lea  eax, [esi+0x4E8]        ;   -> the embedded CRITICAL_SECTION
00433075  call 0x004306D0              ;   InitializeCriticalSection
0043307d  mov  [esi+0x4E4], eax
```

and the allocate path (`0x004349D0`, reached from the exported
`?_Allocate@MemoryPool@@YAPAXIW4AllocType@1@I@Z` at `0x0042FE60`):

```asm
004349ea  mov  esi, [edi+0x4E4]
004349f6  je   0x00434A06              ; null -> no lock
004349f9  call [EnterCriticalSection]
004349ff  inc  [esi+0x18]              ; recursion count
```

Eight more sites in the same family (`0x0043227D`, `0x004345FA`, `0x0043467D`, `0x00434A6A`,
`0x00434AFA`, `0x00434B7A`, `0x00434BFA`, `0x00434C8A`) take the same lock. There is also a runtime
toggle at `0x0043116E` that installs or removes the mutex — EA's `kOptionEnableThreadSafety` — but
the default path through `Init` installs it, and nothing in the image calls the toggle with zero.

**So a worker thread may allocate and free through the game's own heap with no patch at all.** That
is not a small thing: it removes the constraint that would otherwise force every offloaded routine
to be rewritten allocation-free.

`game.dat` exports 503 mangled C++ symbols, thirteen of them the `MemoryPool` free functions. Any
further work in this area should start from that export table rather than from a disassembler.

## 4. What is not worth trying

| idea | verdict | why |
|---|---|---|
| A render/submission thread | **no** | §3.2 — it serializes on the same mutex; §3.3 — no multithreaded device |
| Client update at 30 while drawing at 60 | **no** | §3.4 — already built and withdrawn |
| Parallel object update sweep (`0x0062EC55`) | **no** | §3.1 — order-dependent writes straight into CRC'd state |
| Threading the audio | **no** | §1 — done, twice, by EA |
| Raising the logic rate to "use the spare cores" | **no** | [`headless.md`](headless.md) §1 and [`recharge-rescale.md`](recharge-rescale.md): every duration in every INI is a logic-frame count |
| `D3DCREATE_MULTITHREADED` on its own | **no** | §3.3 — a cost with no consumer |

## 5. What is worth scoping, in the order it should be attempted

Each of these is a separate patch. None of them is "multicore" on its own; the point of the ordering
is that the second and third are only reachable after the first has proved the machinery.

### 5.1 Stage 1 — a worker pool and one join, with a trivial payload

Before offloading anything that matters, prove the mechanism: a cave that spawns *N* worker threads
at engine init, a job queue, a fork/join, and one payload chosen because it is easy to verify rather
than because it is slow. The deliverable is a thing that runs a live match for an hour without
crashing, not a frame-rate number.

- **Cost:** a `.mtcore` PE section on the pattern `commandset-limit` already uses (see
  [`commandset-button-limit.md`](commandset-button-limit.md) and
  [`../engine/README.md`](../engine/README.md)); roughly 400–800 bytes of hand-written assembly for
  the pool, the queue and the join; one five-byte detour at init and one at the join point.
- **Green lights:** the allocator (§3.5), and the fact that `CreateThread` is already imported at
  IAT `0x00BD0260`, so no import-table surgery is needed.
- **The hard part is not the threading.** It is proving the payload's body writes nothing shared.
  Budget most of the time for that audit, and note that a body which takes the W3D lock (§3.2) is
  disqualified before it starts.

### 5.2 Stage 2 — asset decode off the main thread

The highest-value target that is *not* blocked by anything in §3: image and model decode is CPU work
on private buffers, and only the final upload needs the device. The engine already loads D3DX
(`D3DXCreateTextureFromFileInMemoryEx`, `D3DXCreateVolumeTextureFromFileInMemoryEx`,
`D3DXLoadSurfaceFromFileInMemory` at IAT `0x00BD0A18`, `0x00BD0A04`, `0x00BD0A14`), which is the
split point: decode on the worker, upload on the main thread under the existing lock.

- **What it buys:** shorter map loads and fewer mid-match hitches. **Not** frame rate.
- **What it does not touch:** the simulation, the CRC, the replay format, the network. Client-local,
  so it does not have to be on every peer.
- **Open work before it can be costed:** which of those D3DX entry points the streaming path
  actually uses, and whether the `.big` reader underneath is re-entrant. Neither was established
  here.

### 5.3 Stage 3 — the pathfinder queue

The only candidate that attacks the thing players actually complain about, and the only one that
crosses §3.1.

The pathfinder is **already a deferred, budgeted, queued service**, which is why it is even
conceivable. At `0x006F2463`:

```asm
006f2463  mov  eax, [0x00DE4364]       ; TheWritableGlobalData
006f2468  mov  esi, [eax+0x11E8]       ; MaxPathfindCellsPerFrame  (field table 0x00C010E0)
006f246e  mov  eax, [0x00D9F608]       ; the logic rate
006f2476  imul eax, eax, 5             ;   * 5 = frame 25
006f247f  cmp  [TheGameLogic+0x40], eax
006f2484  imul esi, esi, 0x64          ;   first five seconds: budget * 100
006f2498  lea  edi, [ebx+0x1C9E8]      ; queue A: head +0x800, tail +0x804
006f24ec  lea  ecx, [ebx+0x1C1E0]      ; queue B, under the 'pathfind' scope (0x006F24E7)
006f24d9  cmp  [ebx+0x3C], eax         ; cells consumed this frame, against the budget
```

So there is a queue of independent requests and a global cell budget, drained until the budget runs
out. That is the *shape* of an embarrassingly parallel workload.

What stands between that shape and a patch:

1. **The search scratch.** A* over a shared node grid writes parent/cost/visited marks into the
   cells. If those live on the grid rather than per-search, two concurrent searches corrupt each
   other, and giving each worker its own copy of a map-sized grid is a real memory decision. **This
   was not established here and is the first thing to check.**
2. **The budget is a shared counter.** `[ebx+0x3C]` accumulates cells across requests, and *which*
   requests get served this frame depends on the running total. Parallel execution changes the
   partition unless the accounting is done serially after the fact.
3. **Determinism.** Results must be applied in queue order, and every worker must run under the same
   x87 control word (§3.1). This is testable cheaply and early: run the same replay on the patched
   build and compare the per-frame CRC at `0x00625886` against the serial run. **Build that test
   before the parallel path.**
4. **Every peer needs the binary.** Logic state, so it does not cross to unpatched clients and
   replays do not cross the change.

Cost, honestly: this is not a weekend. It is also the one on this list that could be worth it
anyway.

## 6. The measurement, which comes first

Every number in §5 is a guess until a frame has been broken down, and this engine gives you almost
nothing for free — the named-timer registry of §2 has no shipping readout. The gate:

1. **Where the client frame goes.** Detour the client phase (`0x00632409`) and the logic phase
   (`0x006329B0`) with `QueryPerformanceCounter` — already imported at IAT `0x00BD02E8` and called
   from seventeen sites, so the pattern is in the image to copy — and write the pair to a fixed
   global. Read it live with `sage_live`'s `ProcessMemory`, the same way
   [`render-rate.md`](render-rate.md) §8 read the pacing block. **If the logic phase is not a large
   share of a heavy late-game frame, §5.3 is not worth its risk** and the answer is Stage 2 alone.
2. **What the W3D lock costs.** Count acquisitions per frame by incrementing a counter in a detour
   on `0x0051EEC0`, and time the wait. This directly sizes §7.1, and it also says whether §3.2 is a
   wall or merely a fence.
3. **What the pathfinder costs.** `[ebx+0x3C]` at `0x006F24D9` is cells-consumed-this-frame and
   `GlobalData+0x11E8` is the budget. Read both live in a late-game match with a large army. If the
   budget is being hit every frame, pathfinding is deferring work and §5.3 is real; if it is not,
   the stall is elsewhere.
4. **Establish the CRC baseline.** Record a replay, play it back, log `0x00625886`'s result per
   frame. Nothing in §5.3 can be evaluated without this, and it costs nothing to build now.

All four are read-only instrumentation. None needs a cave larger than a few dozen bytes, and all
four are throwaway.

## 7. Two things that are not multicore, and are probably what was wanted

### 7.1 Stop paying for the W3D lock when nothing else is drawing

§3.2 measures a standing cost: two kernel-object operations and two critical-section pairs on every
guarded W3D scope, on every frame, forever — to make a load screen safe. The load screen is not up
during a match.

The shape: a global "a second thread may be in the renderer" flag, set while `0x0065CE28` is alive
and cleared when it exits, tested at the top of `0x0051EEC0` and `0x005208D0` to skip straight to
the return. Two five-byte detours and a byte of state; no cave.

The risks are real and must be written into the patch rather than discovered: the recursion count at
`0x00DD34CC` and the owner id at `0x00DD34C8` have to stay consistent across the transition, so the
flag must be raised *before* the thread starts and lowered *after* it is joined, never while a scope
is open. Measure it first (§6.2) — if the lock is taken only a few hundred times a frame this is
noise and not worth the risk.

### 7.2 The frame limiter burns a core doing nothing

The main loop paces itself by spinning on `Sleep(0)` (`0x0063A1DC`, with the target computed at
`0x0063A196`..`0x0063A1F5`; see [`render-rate.md`](render-rate.md) §2). At 30 fps that is a thread
at 100% for the great majority of every frame, achieving nothing. On the multicore machine that
prompts this question, that is one core pinned by design. Sleeping the whole-millisecond part and
spinning only the remainder is a few bytes, and is the cheapest thing on this page.

Note the same code truncates `1000/fps` with `ftol` at `0x0063A1AD` — 33 ms rather than 33.3 — so
the stock build already runs about 1% fast. Do not "fix" that without reading §8 of the render-rate
document first.

## Address table

| VA | what |
|---|---|
| `0x00639EC6` | main loop top; `0x0063A1DC` the `Sleep(0)` pace spin (§7.2) |
| `0x0044181F` | `GameEngine::update`, vtable `0x00BD84E0` `+0x28` |
| `0x006325A0` | the frame dispatcher; `0x0063264A` the logic-frame wrap |
| `0x00632409` | the client phase (vtable `+0x9C`); `0x00632498` reaches `TheGameClient` |
| `0x006329B0` | the logic phase (vtable `+0x98`); `0x006329B3` opens `'logic'` |
| `0x0062E4E8` | `GameLogic::update`; `0x0062E7B3` `'crc'`, `0x0062E7C8` the CRC call `0x00625886` |
| `0x00AD9AB0` / `0x00AD98F0` | named-timer scope open / close; names `'logic'`, `'crc'`, `'pathfind'`, `'collision'` |
| `0x0043D120` / `0x0045E97D` / `0x004A7F55` / `0x0065CE28` | the four engine thread procs (§1) |
| `0x0043D295` / `0x00461291` / `0x004A8098` / `0x0065D69C` | their `CreateThread` sites |
| `0x0065C19B` / `0x0065C1BB` | the load screen's draw, and where it takes the W3D lock |
| `0x0051EEC0` | `WW3D::Lock` — 123 callers |
| `0x005208D0` | `WW3D::Unlock` — 130 callers, plus 102 on the thunk at `0x004428A6` |
| `0x00DD1FD8` / `0x00DD1F80` | the W3D mutex handle and its critical section |
| `0x00DD34C8` / `0x00DD34CC` | the lock's owning thread id and recursion count |
| `0x0051EEA0` | "this thread owns the device, or nobody does" predicate |
| `0x005240D2`..`0x0052410D` | the `D3DCREATE_*` behaviour flags; `0x005240E1` is the one-byte site |
| `0x00DD345C` / `0x00DD343C` | the flags global, and the `FPU_PRESERVE` condition |
| `0x005241B6` / `0x00524222` | the two `IDirect3D9::CreateDevice` calls |
| `0x00525176` / `0x00525195` | `LoadLibrary("D3D9.DLL")` and `Direct3DCreate9` |
| `0x00433050` | `GeneralAllocator::Init`; `0x00433063`/`0x0043307D` install the mutex at `+0x4E4` |
| `0x004349D0` | the allocate path; `0x004349EA`/`0x004349F9` take the lock |
| `0x0042FE60` | exported `MemoryPool::_Allocate` (503 exports total, 13 in this family) |
| `0x006F2463` | the pathfinder's per-frame budget read, `GlobalData+0x11E8` |
| `0x006F2498` / `0x006F24EC` | its two request queues; `0x006F24E7` opens `'pathfind'` |
| `0x00BD0260` / `0x00BD02E8` | `CreateThread` and `QueryPerformanceCounter` in the IAT |
