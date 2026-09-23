# How `bfme2_accel.dll` decides which thread may draw

Read 1 of [`accel-port.md`](accel-port.md) §4: *how does the recognised build keep the load-screen
thread out of the moved renderer?* Read 2026-09-22 from the DLL's machine code, with the author's
permission, using `pefile` + `capstone`. DLL addresses are `bfme2_accel.dll` at its ImageBase
`0x10000000`; engine addresses are ROTWK `game.dat` `2.01.2614.37001` at `0x400000`.

## TL;DR

- **The question contained a wrong assumption, mine.** There is no load-screen handling. The DLL
  never references `0x0065C19B`, `0x0065CE28` or `0x0065C1BB` — the whole load-screen thread that
  [`multicore.md`](multicore.md) §1.1 identifies is invisible to it. I checked all 197 engine
  addresses it references as instruction operands; the load screen is not among them.
- **What it has instead is one thread-identity rule and one critical section.** Every hooked call
  asks "am I the thread that owns the queue?" A thread that is not gets its call executed
  **directly, under a critical section (`0x10153D94`) that the owner also takes whenever it
  executes directly**. That is the entire protection, and it is generic — it would cover the load
  screen, a driver thread, or anything else, without naming any of them.
- **So the mechanism is portable in a way the inventory suggested it would not be.** It needs no
  engine addresses at all. What it needs is to know *which thread is the game thread*.
- **And that is exactly what the unrecognised build gets wrong.** With no engine hooks the DLL falls
  back to "the first thread to make 64 effect calls owns the queue" (`0x1003E1F0`, and `0x40` is
  literally the constant). Three seconds into startup the thread drawing is the load screen. The
  recognised build never runs that heuristic, because its render-stage hooks have already claimed
  the id from a site only the game thread executes.
- **For a port this is good news twice over.** The design is a lock discipline, not engine
  knowledge; and `sage_patch` can establish the identity *better* than the DLL can, because it can
  patch a known engine site to publish the thread id outright instead of guessing from call counts.

## 1. The install, and where the identity comes from

The render thread arms at load and goes live on the first `ID3DXEffect` call:

| DLL address | what |
|---|---|
| `0x100459F0` | the gate every `ID3DXEffect` wrapper calls. Caches `QueryPerformanceFrequency`, stores `GetCurrentThreadId()` into `0x100DE3C4`, and under the critical section `0x10153D7C` runs the one-time init (`0x10153D60` is the once-flag) before calling the installer |
| `0x100404B0` | the installer. Recovers the device from the effect through `[0x101A41B0]`, probes and hooks the vtables, starts the worker, and declares the thread |
| `0x1003FDA0` | the vtable-hook helper — called 14 times with slot counts `0x16, 0x11, 0xE, 0xE, 6, 0xA, 0x16, 0x16, 0xB, 8, 5, 5, 5, 0x77`. The last is `IDirect3DDevice9`'s 119 slots, wrappers at `0x1005BBF0`, originals saved at `0x101A3EC0` |
| `0x100408A2` | `CreateThread` on the worker proc `0x100448B0`; `SetThreadPriority(+1)` at `0x100408C3`; then `WaitForSingleObject(…, 5000)` at `0x100408D4` for the worker's ready signal |
| `0x10040C32` | `GetCurrentThreadId()` → **`0x10153D64`, the game-thread id**. The worker writes its own into `0x10153D68` at `0x100448CE` |

The last row is the whole answer to "which thread is the game thread": **whichever one happened to
make the effect call that went live.** There is no engine-derived check at that moment, on any
build. What differs between builds is which thread has already been *allowed to get there*.

## 2. The per-call gate

`Present` (`0x10008790`, device slot 17) is representative; the same shape recurs across the
wrapper family.

```
        cmp  [0x10155734], 0        ; live?
        ...
        call GetCurrentThreadId
        cmp  eax, [0x10153D64]      ; the game thread?
        jne  0x100089DB             ; -> the foreign path
        cmp  [0x10153D5C], 0        ; render thread enabled?
        je   0x10008A33             ; -> straight through
        cmp  [0x10153D74], 0        ; already inside a direct scope?
        jne  0x100089DB
        ...                         ; pDirtyRegion non-zero:
        EnterCriticalSection(0x10153D94)
        inc  [0x10153D74]
        call [0x101A3F04]           ; the saved original
        dec  [0x10153D74]
        LeaveCriticalSection(0x10153D94)
        ...                         ; otherwise: enqueue 5 dword args via 0x1003E240
```

and the foreign path, which is the one that matters here:

```
0x100089DB:
        cmp  [0x10153D5C], 0        ; render thread off -> direct
        je   0x10008A33
        cmp  eax, [0x10153D68]      ; I am the worker -> direct, I own the device
        je   0x10008A33
        cmp  eax, [0x10153D64]      ; I am the game thread -> direct
        je   0x10008A33
        EnterCriticalSection(0x10153D94)
        call [0x101A3F04]
        LeaveCriticalSection(0x10153D94)
        lock inc [0x10153DF0]       ; "off-queue from: other-thread" in the report
```

`0x10008A33` is a two-instruction tail jump to the saved original — the zero-cost pass-through when
the render thread is off.

**The worker takes the same lock, so the exclusion is real.** Its proc `0x100448B0` records its own
id, signals ready, then spins on a sequence counter (`0x10153E40` produced vs `0x10153E80`
consumed — `pause`, up to `0xFA0` iterations, then an event wait). When there is work it reaches
`0x100449D5`:

```
        push 0x10153D94
        call EnterCriticalSection      ; the same section the foreign path takes
        ...                            ; drain up to 0x100 commands, each via 0x1003F590
```

There is also a **hand-off flag, `0x10153EC0`**, and it is the nicest detail in the design. Before
the worker acquires, it spins while that flag is set (`0x100449AF`, up to `0x10000` pauses), and it
abandons a drain mid-batch when it goes up (`0x10044A07`). The game thread raises it immediately
before asking for the lock and clears it once it has it (`0x10008A6A` / `0x10008A88`). So the owner
never queues behind a 256-command batch: it asks, and the worker steps aside at the next command
boundary.

So there are exactly three dispositions for a hooked call: **queued** (the owner, common case),
**direct under `0x10153D94`** (the owner's own re-entrant cases, and every other thread), and
**straight through** (render thread off, or the worker itself). The load screen takes the second.
`0x10153D94` is the only thing standing between it and the worker, and it is enough, because the
worker takes the same lock around the work it drains.

**Globals worth having by name:**

| | |
|---|---|
| `0x10153D5C` | render thread enabled (Scroll Lock toggles it) |
| `0x10153D64` / `0x10153D68` | game-thread id / worker-thread id |
| `0x10153D74` | direct-scope depth, so a direct call that re-enters does not deadlock |
| `0x10153D94` | **the critical section every direct execution takes** |
| `0x10153DF0` | the off-queue-from-another-thread counter |
| `0x10155734` | live flag |
| `0x100DE3C4` | the render-thread id as the wrappers and timers see it |
| `0x100BBC8C` | **"this build's engine hooks are installed"** |

## 3. Why the unrecognised build crashed

`0x100BBC8C` selects between two ways of establishing `0x100DE3C4`, and that id is what decides who
reaches the installer first.

**Recognised.** The render-stage hooks are installed — `0x10044E20`, `0x10044EC0`, `0x10045030`,
one per stage, each opening with `QueryPerformanceCounter` and a phase marker (`[0x100DE42C] = 3`
in the first), and each carrying:

```
        cmp  [0x100DE3C4], 0
        jne  ...
        call GetCurrentThreadId     ; unset -> it is me
```

Those sites sit in the engine's own render sequence, so the only thread that can ever execute them
is the game thread. The identity is settled before any effect call matters.

**Unrecognised.** Those hooks do not exist, so `0x1003E1F0` runs instead — the function whose string
is *"this build has no engine hooks, so the drawing thread is identified by its own work"*:

```
0x1003E1F0:
        cmp  [0x100BBC8C], 0        ; engine hooks present -> do not guess
        jne  ...
        ; candidate in 0x10153D6C, streak in 0x10153D70
        ; same thread again? inc. different? reset to 0.
        cmp  eax, 0x40              ; 64 consecutive calls
        jl   ...
        mov  [0x100DE3C4], ecx      ; you are the drawing thread
```

Sixty-four consecutive effect calls from one thread, with no other qualification. **Three seconds
into startup, the thread drawing is the load screen**, and the user's log shows the heuristic firing
at `18:12:22.987` and the render thread going live on that same thread `6 ms` later, with
`D3DERR_INVALIDCALL` immediately after on a stack whose top frame is the load-screen thread's own
loop (`0x0065CE76`, the return of its `call [eax+0x124]` — [`multicore.md`](multicore.md) §1 names
that loop).

**What is established and what is not.** The two code paths above, the constant `0x40`, the gate on
`0x100BBC8C`, and the fact that the installer takes the calling thread's id are all read from the
instructions. That the winning thread in that log *was* the load screen is an inference — a strong
one, since both the heuristic's winner and the crash's faulting thread are "the thread drawing three
seconds into startup", but the log does not print the faulting thread id next to `15820` and a
static read cannot close it. The precise sequence from misidentification to `INVALIDCALL` is
likewise not established: with the load screen owning the queue, the real game thread becomes a
foreign thread and the queue's owner is a thread that exits when loading ends, and either is
sufficient to explain the failure without telling us which one did it.

## 4. What a port has to reproduce

Three things, none of which needs an engine address:

1. **One worker that owns the device**, and every other caller either enqueuing to it or
   executing under a shared lock.
2. **`0x10153D94`'s discipline** — a single critical section around *every* direct execution,
   including the owner's own re-entrant paths, with a depth counter (`0x10153D74`) so re-entry does
   not self-deadlock.
3. **A positive identity for the game thread**, established before the first hooked call can matter.

Item 3 is the one the DLL does worst and we can do best. Its two mechanisms are a guess (64 calls)
and a set of hooks that a whole-image checksum gates off ([`accel-port.md`](accel-port.md) §1.1).
`sage_patch` has a third option neither of those is: **patch a site only the game thread executes
and have it publish `GetCurrentThreadId()` into a known location.** `GameLogic::update`
(`sage_patch.addresses`'s `GAME_LOGIC_UPDATE`, already hooked by `live-bridge`) and the scene render at
`0x0047177E` are both candidates, both already carry cave machinery in this repo, and a site
signature composes with every other patch instead of excluding them.

That reframes the B1/B2 decision in [`accel-port.md`](accel-port.md) §6 slightly: **the identity
half is a cave, on either branch, and it is worth having before anything else is written.** It is
small, it is testable on its own (publish the id, read it back with `sage_live`), and it is the
precondition the DLL's own failure mode says is the load-bearing one.

## 5. Not established by this read

- ~~The queue itself.~~ **Read 3, 2026-09-24: [`accel-queue.md`](accel-queue.md).** The `5` passed
  to `0x1003E240` is `Present`'s dword-argument count, not an opcode. The lock mirrors and dedupe
  layers are located there by record kind but still not read.
- ~~Whether the worker takes `0x10153D94` around each drained call.~~ **Read, and it does** — §2.
  The drain is batched (256 commands) and yields to the owner through `0x10153EC0`.
- ~~What selects `Present`'s direct-under-lock path.~~ **`pDirtyRegion`** (the fifth argument,
  counting `this`): non-null flushes the queue and calls directly, because the queued form does not
  copy the region ([`accel-queue.md`](accel-queue.md) §2).
- The `ID3DXEffectStateManager` bail-out (`0x1001C3D0`) and the Scroll Lock toggle path
  (`0x1003A580` swaps `0x100DE3C4`).

## Address table

| DLL | what |
|---|---|
| `0x100404B0` / `0x1003FDA0` / `0x100448B0` | installer / vtable-hook helper / worker proc |
| `0x100459F0` | the go-live gate called from every effect wrapper |
| `0x1003E1F0` | the 64-call fallback identifier |
| `0x10044E20` `0x10044EC0` `0x10045030` | the render-stage hooks that claim the id on a recognised build |
| `0x10008790` / `0x100089DB` / `0x10008A33` | `Present`: wrapper / foreign-thread path / pass-through |
| `0x1005BBF0` / `0x101A3EC0` | device wrapper table (119) / saved originals |
| `0x1003E240` | the enqueue |

| engine | what |
|---|---|
| `0x0065CE28`..`0x0065D69C` | the load-screen thread proc ([`multicore.md`](multicore.md) §1) — **referenced nowhere in the DLL** |
| `0x0065CE76` | the return of its `call [eax+0x124]`, top of the crash stack |
| `0x0047177E` | scene render — a candidate identity site for our own version (§4) |
