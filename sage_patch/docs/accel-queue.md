# How `bfme2_accel.dll` queues Direct3D work

Read 3 of [`accel-port.md`](accel-port.md) §6: the enqueue (`0x1003E240`), the worker
(`0x100448B0`) and the dispatch (`0x1003F590`) that [`accel-thread-identity.md`](accel-thread-identity.md)
§5 left unread. Read 2026-09-24 from the DLL's machine code, with the author's permission, using
`pefile` + `capstone`. DLL addresses are `bfme2_accel.dll` at its ImageBase `0x10000000`.

## TL;DR

- **The queue is one single-producer ring, 32 MB, with no allocation per call.** A command is a
  24-byte header, its stack arguments copied verbatim, and any pointed-to data (rects, matrices,
  constants) copied inline behind them. The game thread writes; the worker reads; two sequence
  counters and one event connect them. It is about as simple as a D3D9 command queue can be.
- **The split is by return value, not by method, and it is mechanical.** Of `IDirect3DDevice9`'s 119
  methods, the **47 that return nothing the caller reads** — every `Set*`, every `Draw*`, `Clear`,
  `BeginScene`/`EndScene`, `Present`, `Reset`, `UpdateSurface`/`UpdateTexture`, `StretchRect`,
  `ColorFill` — are queued. The **72 that return something** — every `Get*`, every `Create*`,
  `TestCooperativeLevel`, `QueryInterface` — **drain the whole queue and then run directly under the
  lock.** No method is special-cased in the choice.
- **So a getter is a full pipeline stall, and the design works only because the engine rarely asks.**
  This is the correctness-for-free half of the design and its performance risk in one line. A port
  inherits both; the thing to measure is how many drains a frame costs (§5).
- **Two tricks turn "returns something" into "queueable" where it matters:**
  `Present` returns the *previous* frame's `HRESULT` (read 2), and effect-parameter lookups return a
  **synthetic `D3DXHANDLE`** (`0xFFFF0003 | idx << 2`) that the worker resolves into a table when the
  lookup actually runs. The second is the more interesting: it is what lets the effect half of the
  frame stay asynchronous at all.
- **Nothing here needs an engine address.** Like read 1, this is D3D9 knowledge, not SAGE knowledge.
  That is good for a port (it is specifiable from the D3D9 headers alone) and it confirms that the
  engine-specific parts of the DLL are the lock mirrors and the special-cased write paths, which are
  still unread.

## 1. The ring

| global | what |
|---|---|
| `0x10153DDC` | ring base (32 MB, `0x2000000`) |
| `0x10153E00` | producer write offset — private to the game thread |
| `0x10153E40` | **published** write offset — what the worker may read up to |
| `0x10153E80` | consumer read offset — written by the worker |
| `0x10153E04` | the producer's cached copy of the consumer offset |
| `0x10153E08` / `0x10153E84` | commands produced / consumed (sequence numbers) |
| `0x10153E0C` | commands written since the last publish |
| `0x10153DAC` | the "work published" event; `0x10153DBC` is 1 while the worker sleeps on it |
| `0x10153DB0` | the "drained" event, for §4's flush |

**Enqueue** (`0x1003E240`, `cdecl (argc, extra_bytes)`) reserves
`align16(argc*4 + 0x27) + align16(extra_bytes + 15) + 0x60` bytes and returns a pointer to a
zero-initialised header. It never writes arguments; the caller does. Two limits:

- **Outstanding bytes are capped at 16 MB.** Past that the producer calls the flush (§4) and waits.
  That is the game thread's only backpressure in the steady state.
- **Wrap.** If the record would cross the end of the ring it writes a kind-`2` marker at the current
  offset, resets both offsets to zero, and wakes the worker; the worker sees kind `2` and jumps its
  read offset to zero (`0x10044A18`).

**Commit** is inlined in every wrapper (read in `Present` at `0x10008958`..`0x100089C7`): fill the
header's size, stamp the next sequence number, advance the private write offset, and **publish only
every 32 commands** (`0x20`) — or immediately if the header's flag bit 0 is set, which `Present`
sets. Publishing is a plain store to `0x10153E40` plus `SetEvent` if the worker is asleep. On x86 the
ordering is sound without a fence: the record's bytes are stored before the publish store, and x86
does not reorder stores with stores.

## 2. The record

```
+0x00  u16  kind         1 = call, 2 = wrap, 3..9 = special forms (§3)
+0x02  u8   argc         dword arguments at +0x18, including `this`
+0x03  u8   flags        bit 0: publish now, and route the HRESULT to 0x10153DE4 (Present)
+0x04  u32  size         whole record, 16-aligned
+0x08  ptr  target       the saved original method (e.g. [0x101A3F04] for Present)
+0x0C  u32  sequence
+0x10  u16  release mask bit i set -> Release() argument i after the call
+0x12  u16  method id    the vtable slot, for diagnostics (0x11 = Present)
+0x14  u32  (batched count, kind 8)
+0x18  u32  args[argc]
        ... inline copies of pointed-to data, 16-aligned, after align16(argc*4 + 0x27)
```

`Present` shows the inline-copy rule clearly: `pSourceRect` and `pDestRect` are copied behind the
arguments and the argument slots are rewritten to point at the copies (`0x100088EA`..`0x1000890E`);
`pDirtyRegion` is **not copied** — its slot is set to zero (`0x10008918`). That is safe only because
a non-null `pDirtyRegion` never reaches the queue: it takes the synchronous path. **That answers read
1's open question (§5 there): the "fifth stack argument" is `pDirtyRegion`.**

**The release mask is how the queue keeps objects alive.** A queued `SetTexture(stage, tex)` must
not let the game `Release` `tex` to zero before the worker binds it. The enqueuer `AddRef`s the COM
argument and sets its bit — `SetTexture` does `call [vtbl+4]` then `or word [rec+0x10], 4` for
argument 2 (`0x1000D4F5`..`0x1000D4FA`) — and the worker `Release`s each masked argument after the
call (`0x1003FADE`..`0x1003FB15`). **It is switchable**: the `AddRef` is gated on the byte at
`0x100BB044`, which is the log's "per-call object refs %s". With it off, the design relies on the
engine not freeing a bound resource within one frame — plausible for SAGE, and a port should start
with it on.

## 3. The dispatch

`0x1003F590` switches on `kind`. Kind `1` is the general case: a jump table on `argc` (1..10, at
`0x1003FB4C`) pushes the arguments and calls `target`. The others are the forms that need more than
a call, and they are the first concrete sight of the features [`render-thread.md`](render-thread.md)
§3.1 only knew from strings:

| kind | shape | what it is |
|---|---|---|
| `3` | `Lock(off, size, &p, flags)` → `memcpy(p, shadow, size)` → `Unlock()`, optional `Release` | **buffer lock mirror**: the game wrote into a shadow copy; the worker replays it into the real buffer |
| `4` | `LockRect` a 1×1 rect → write 1, 2 or 4 bytes (or byte 3 only, for kind `0x100`) → `UnlockRect` | **single-pixel writes** — the `DrawPixel` / alpha special case (`0x005165E0` / `0x005166C0` in the engine) |
| `5` | call; store the result in `[0x10186B80 + idx*4]` | **deferred effect lookup** — resolves a synthetic `D3DXHANDLE` (§3.1) |
| `6` | call with a handle resolved through that table; optionally clear the slot | use / free of a synthetic handle |
| `7` | `LockRect` → row-by-row `memcpy` from a shadow → `UnlockRect` | **texture lock mirror**, 2D |
| `8` | walk `count` packed sub-records, each `(vtable slot, size)`, calling `[vtbl + slot*4]` | **effect parameter batch** (`AOTR_FXBATCH`) — several `SetMatrix`/`SetVector`/`SetValue`s in one record; slot `0x4E` takes five arguments, `0x22`/`0x26`/`0x2C` take a nullable inline pointer |
| `9` | `LockBox`/`LockRect` → row copy → unlock, then a follow-up call with optional rects | volume/cube mirror, or a lock-then-`UpdateSurface` pair |

### 3.1 Synthetic effect handles

A `D3DXHANDLE` returned by `GetParameterByName` and friends is an opaque pointer the caller hands
back later. The DLL exploits that. When the lookup is queued, the caller gets
`0xFFFF0003 | (idx << 2)` — low bits `11` so it can never collide with a real, aligned handle — and
the worker writes the real one into slot `idx` when it runs (kind `5`). Every effect wrapper that
takes a handle tests for the pattern (`and eax, 0xFFFF0003; cmp eax, 0xFFFF0003` at `0x1001CE8B`)
and substitutes the table entry, or rejects the call with `D3DERR_INVALIDCALL` if the lookup has not
run yet (`0x1001CEEA`..`0x1001CEF2`, guarded by a per-slot ready byte at `[0x101A9CA8 + idx]`).

That rejection is a real behaviour difference from stock, visible to the caller, and a port must
decide whether to reproduce it or drain instead.

### 3.2 Coalescing

`0x1003FC50` commits an **open record** held at `0x100BB0C0`, called at the top of the enqueue and
the flush. It lets a wrapper leave a record open and append compatible calls to it (the kind-`8`
batch is built this way), counting each towards the publish threshold. Nine device wrappers also
call `0x1003FB80` and `0x10044B70` on the queued path, which is where `AOTR_DEVDEDUPE`'s redundant-set
elimination should live. **Not read.**

## 4. The worker, and the flush

**Worker** (`0x100448B0`): records its thread id (`0x10153D68`), loads the game thread's `MXCSR`
(`0x10155730` — so SSE rounding and denormal behaviour match the thread whose calls it replays; a
detail a port must not drop), signals ready, then loops:

1. **Idle:** spin up to `0xFA0` `pause`s on the published offset; then set `0x10153DBC` and
   `WaitForSingleObject(0x10153DAC, 2 ms)`. The 2 ms timeout means a missed wake costs at most 2 ms.
2. **Yield to the owner:** spin while the hand-off flag `0x10153EC0` is up (read 1 §2).
3. **Drain:** `EnterCriticalSection(0x10153D94)`, run up to 256 records through the dispatch, stopping
   early if the hand-off flag rises; store the consumer offset and sequence; `LeaveCriticalSection`.
4. If a flush is waiting (`0x10153DC0`) and the consumer sequence has reached its target
   (`0x10153DD8`), `SetEvent(0x10153DB0)`.

**Flush** (`0x1003F350`), called by every synchronous wrapper: publish everything, set the target to
the current producer sequence, wake the worker, then wait — `0x2000` `pause`s, then an event wait
through `0x10044810` — until the consumer sequence reaches the target. After five seconds it logs
*"game thread waited > 5 s for the worker (exec seq %u, target %u, next op %s)"* and keeps waiting.
Time spent here is accumulated per method id (`0x10153F10`, indexed by `0x100BB07C`), which is what
the 30-second report's per-call stall column is.

**Present throttle** (`0x10042940`): after queueing a `Present`, the game thread waits while more than
one `Present` is outstanding (`0x10153DE0 > 1`), in `MsgWaitForMultipleObjects` so the message pump
keeps running. The worker decrements the count and signals `0x10153DB4` when a `Present` completes
(`0x1003FB1D`). **So the game thread can be at most one frame ahead of the GPU submission.** That is
the whole latency cost of the design, and it is bounded.

## 5. What this means for the port

[`accel-port.md`](accel-port.md) §6 chose B2, a native module of our own. This read is the core of it,
and it sizes the core smaller than feared:

- **The queue itself is a weekend, not a quarter.** Ring, header, commit, worker, flush, throttle:
  perhaps 400 lines of C. It is specifiable from the D3D9 headers — the kind-`1` rule needs only each
  method's argument count and which arguments are pointers to copy or objects to `AddRef`.
- **The wrapper table is generated, not written.** 119 device methods, 79 effect methods, and the
  resource interfaces, each either "queue" or "drain then call" by return type. A table in Python that
  emits the C thunks is the obvious shape, and it is where `sage_patch`'s habits carry over.
- **The cost lives where it lived before this read**: the lock mirrors (kinds `3`, `7`, `9`), the
  synthetic handles, and the dedupe. Those need the engine's lock patterns, which is why the DLL's
  engine-address list is mostly about writes that bypass the device.
- **The measurement a port needs is drains per frame.** Every getter or creator the engine calls
  mid-frame costs a full stall. The DLL counts these (`0x10153F10` per method id); ours should too
  from day one, because that number decides whether the render thread is a win on Edain's content at
  all.

## 6. Not established by this read

- `0x1003FB80` / `0x10044B70` / `0x100438C0` — the dedupe and state-shadow calls on the queued path.
- The texture and buffer wrappers that build kinds `3`, `7` and `9`: how the shadow is allocated, when
  the mirror is "adopted" or "dropped" (the report's words), and what happens to `D3DLOCK_READONLY`.
- The effect-side wrappers beyond the handle test: which of the 79 are queued, and how kind `8`
  batches are opened and closed.
- The per-thread dispositions for the synchronous path are as read 1 describes; this read did not
  re-verify them per method.

## Address table

| DLL | what |
|---|---|
| `0x1003E240` | enqueue: `(argc, extra_bytes)` → header pointer |
| `0x1003FC50` | commit the open (coalescing) record |
| `0x1003F350` | flush: publish, wait until the worker's sequence reaches ours |
| `0x1003F590` | dispatch, by record kind; kind-1 jump table at `0x1003FB4C` |
| `0x100448B0` | worker proc |
| `0x10042940` | `Present` throttle (at most one outstanding) |
| `0x1003E3D0` | Scroll Lock state change: resets the handle table (`0x10186B88`, `0x4000` bytes) and flips `0x10153D5C` |
| `0x1005BBF0` | device wrapper table, 119 entries |
| `0x10153DDC` / `0x10153E00` / `0x10153E40` / `0x10153E80` | ring base / private write / published write / read |
| `0x10153E08` / `0x10153E84` | produced / consumed sequence |
| `0x10153DE0` / `0x10153DE4` | outstanding `Present`s / last `Present` result |
| `0x10186B80` / `0x101A9CA8` | synthetic-handle table / per-slot ready bytes |
| `0x10155730` | the game thread's `MXCSR`, loaded by the worker |
