# `bfme2_accel.dll` on a patched `game.dat`

What OH1A's BFME2 Accelerator does when it is injected into a `game.dat` that `sage_patch` has
edited, and what the DLL is made of. [`accel-module.md`](accel-module.md) is the patch that loads it
and the fixes it needs; [`accel-thread-identity.md`](accel-thread-identity.md) and
[`accel-queue.md`](accel-queue.md) read its render thread.

## TL;DR

- **The stock DLL and `sage_patch` are mutually exclusive, and they fail by crashing rather than by
  declining.** The DLL identifies a build by a checksum over the whole of `.text`, so *any*
  `sage_patch` edit makes it an "unrecognised build" — and an unrecognised build still gets the
  render thread, installed by generic vtable discovery, without the engine-specific handling that
  makes it safe. The crash lands on the **load-screen thread**, which [`multicore.md`](multicore.md)
  §1.1 names as the only other thread that enters the render layer (§1).
- **The DLL is 1,435 functions, 359 KB of dense, stripped MSVC x86** (§2). Its diagnostic strings
  name its engine addresses, so it is read a feature at a time, never decompiled whole.
- **The author has given full permission to use his work to recreate a pySAGE patch of it**
  (2026-09-22, §3).

## 1. What happens on a patched binary

Run 2026-09-22, the stock DLL injected into Edain on a `sage_patch`-patched `game.dat`; the DLL's own log, abridged:

```
game module base 00400000, size 00AD3000, checksum 00ADC2F6, timestamp 460DA09E
init: an unrecognised build of this engine (.text 4404F3C6, stamp 460DA09E size 00AD3000
      sum 00ADC2F6 entry 0063D082). Only the parts that do not depend on a build's addresses
      are installed; the rest is left alone.
alloc:     rpmalloc installed on malloc/calloc/realloc/free (froze 16 threads). Live.
preshader: cache LIVE (noop=0).
fastcrt:   16 import slots now use the exact fast versions, out of 16 that matched.
rt:        armed - ID3DXEffect vtable hooked (79 slots), 14 D3DX device functions scoped.
rt:        this build has no engine hooks, so the drawing thread is identified by its own work -
           thread 15820 made 64 effect calls and is treated as the render thread.
rt:        RENDER THREAD LIVE - device 3B881180, game thread 15820, worker thread 24984.
```

then `Direct3D error 0x8876086C (D3DERR_INVALIDCALL)`, with these `game.dat` return addresses on
the stack (the dialog prints them as decimal offsets from the module base; the symbol names beside
them are nearest-export guesses over a handful of exports and mean nothing):

| dialog | VA | what is there |
|---|---|---|
| `game.dat+2477686` | `0x0065CE76` | the instruction after `call [eax+0x124]` — **the load-screen thread's loop body** |
| `game.dat+2477380` | `0x0065CD44` | the instruction after `call [eax+0x18]`, same object, same region |
| `game.dat+1175111` | `0x0051EE47` | a `ret` after `call [edx+0x4c]`, inside the W3D device neighbourhood (`WW3D::Lock` is `0x0051EEC0`) |
| `game.dat+593082` | `0x00490CBA` | a vtable call chain, `call [eax+0xc]` → `[esi+0x2c]` → `call [eax]` |
| `game.dat+239838` | `0x0043A8DE` | does not disassemble as an instruction boundary; ignore it |

[`multicore.md`](multicore.md) §1 names the load-screen thread proc `0x0065CE28`..`0x0065D69C` and
describes its loop as *"wait `+0x40`, call vtable `+0x118` ("keep going?"), then vtable `+0x124`,
`Sleep(0x64)`, poll `+0x44`"*, and §1.1 establishes that it takes the W3D lock at `0x0065C1BB` and
so **genuinely enters the render layer while the main thread is loading a map**. `0x0065CE76` is the
return address of that `+0x124` call. The stack is the load screen, drawing, into a device the
accelerator had moved onto its own worker.

Three conclusions:

**1.1 The build gate is a `.text` checksum, so it is incompatible with `sage_patch` by
construction.** Every other field in the log matches record 0 of the table in
[`render-thread.md`](render-thread.md) §2 — stamp `460DA09E`, sum `00ADC2F6`, entry `0063D082` — and
only `.text 4404F3C6` differs from its `5ED63115`. Stock 2.02 is recognised and works; one patched
byte anywhere in `.text` is not. Note also that the table's `size` field (`00AD4000`) does **not**
match the real `00AD3000` on a build that is otherwise recognised, so that section's caution about that column
was right and the identity really does rest on the checksum.

This is a design difference worth naming rather than working around. `sage_patch` identifies a site
by **the bytes at that site** and verifies each edit's expected originals before writing, so two
patches that touch different functions compose. A whole-image checksum cannot compose with anything,
including itself: it admits exactly one binary in the world.

**1.2 An unrecognised build does not fail safe.** The banner says "only the parts that do not depend
on a build's addresses are installed", and the parts that do not so depend turn out to include
`rpmalloc`, the fast CRT, the preshader cache **and the render thread**, which falls back to
identifying the drawing thread by counting effect calls. What turns *off* is the engine-specific
half — the shroud (`0x0047308C`/`0x00473EB3`), the per-pixel writes (`0x005165E0`/`0x005166C0`), the
radar `SurfaceClass` locks — which is to say precisely the set of engine-side paths that write to
the device without going through it. The design is "move the renderer and special-case everything
that bypasses it"; with the special cases off, what is left is not a degraded accelerator, it is the
dangerous half on its own.

**1.3 The second drawing thread is the whole correctness condition.** The DLL has no load-screen
handling at all ([`accel-thread-identity.md`](accel-thread-identity.md)): it has a thread-identity
rule and one critical section. A recognised build hooks a site only the game thread executes; an
unrecognised one guesses the game thread by counting effect calls, and the load screen draws first,
so it picks the wrong thread. [`render-thread.md`](render-thread.md) §4.1's *"the worker is the only
thread that ever calls D3D and the lock is uncontended"* is therefore true only when that guess is
right.

## 2. What is actually being disassembled

Measured 2026-09-22 with `pefile` + `capstone` against the repo-root `bfme2_accel.dll`
(811,520 bytes, PE32, ImageBase `0x10000000`, 5 sections).

| | |
|---|---|
| `.text` | 359,439 bytes of code in **1,435** `int3`-delimited functions |
| sizes | 210 fns ≤32 b (0.9% of bytes) · 392 fns 33–128 b (9.1%) · **678 fns 129–512 b (53.9%)** · 151 fns 513–2048 b (32.9%) · 4 fns >2048 b (3.2%) |
| symbols | **none.** RTTI carries three types, all `std::` (`exception`, `bad_exception`, `type_info`) |
| names available | 15 `AotrRtTest*` exports; ~1,200 diagnostic strings |
| imports | `KERNEL32` (121), `USER32` (5), `ADVAPI32` (3) — nothing else |
| entry | `0x10048D1F`, a stock CRT shim: `fdwReason == DLL_PROCESS_ATTACH` → `call 0x100490A9` (the install), then CRT init at `0x10048BE6` |

Two things follow.

**It is dense, not a veneer.** Over half the code sits in mid-size functions. A D3D9 marshaller over
thirteen interface types could have been mostly one-line thunks; this is not that shape, so the
`≥129 b` mass is where the logic lives and there is a great deal of it.

**The strings are the map, and a good one.** Each feature prints an install banner naming its own
engine addresses, and [`render-thread.md`](render-thread.md) §2 confirmed thirteen of those land on
clean prologues in our `game.dat`. A targeted read therefore never starts cold: the banner names the
feature, the engine addresses give one end, and the string's `.rdata` address gives the other by
xref. That is what makes per-feature reads cheap and a wholesale decompile pointless.

**What is never worth reading:** `rpmalloc`, the SSE/SSE4.1 CRT, the formatter and log writer, the
100 Hz sampler and stack walker, and the per-interface D3D wrapper thunks. None of it is engine
knowledge.

## 3. Permission and attribution

The author has given **full permission to use his work to recreate a pySAGE patch of it**
(2026-09-22). That is a derivation licence, not a warrant to redistribute his binary; the source is
in any case published under the MIT licence. Every patch derived from the DLL names him beside its
`author` — [`../README.md`](../README.md)'s author convention exists because an author is who gets
asked for a fix, and on derived work he knows why the code is shaped the way it is.
