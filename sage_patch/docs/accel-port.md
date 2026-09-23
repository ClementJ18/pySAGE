# Porting `bfme2_accel.dll` — scope

It is a **plan, not a reading**. [`render-thread.md`](render-thread.md) §0 says the DLL's machine
code was not disassembled, and that §3's feature inventory is the DLL's own diagnostic text quoted
back rather than mechanism. **That is still true as of this document.** Nothing here promotes any
claim in §3; §3 below scopes the work that would.

## TL;DR

- **All three things blocking [`render-thread.md`](render-thread.md) are unblocked.** §0's caveat
  can be retired a feature at a time by reading instructions; §6's "talk to the author" has
  happened; and the author has since given **full permission to use his work to recreate a pySAGE
  patch of it** (2026-09-22).
- **Read 1 is done** ([`accel-thread-identity.md`](accel-thread-identity.md)) and it moved the
  estimate in a good direction. The DLL has no load-screen handling and, for this part, no engine
  knowledge at all: one worker owning the device, one critical section around every direct
  execution, and a rule for which thread owns the queue. The rule is the weak part — a guess on an
  unrecognised build, which is what crashed — and it is the part `sage_patch` can do **better** than
  the original, by patching a site only the game thread executes instead of counting calls.
- **That permission picks the branch.** *Recreate* is §3B — we write the payload, crediting him.
  §3A (shipping his binary) is **dropped**: it was never what was asked for, and §1.1 would have
  broken it anyway. The remaining fork is narrower and is the one open decision in this file: **may
  a native companion module live in this repo?** See §6.
- **New, and it outranks everything else here: the DLL and `sage_patch` are mutually exclusive
  today, and they fail by crashing rather than by declining.** §1 has the run. The DLL identifies a
  build by a checksum over the whole of `.text`, so *any* `sage_patch` edit makes it an
  "unrecognised build" — and an unrecognised build still gets the render thread, installed by
  generic vtable discovery, without the engine-specific handling that makes it safe. The crash lands
  on the **load-screen thread**, which [`multicore.md`](multicore.md) §1.1 already named as the only
  other thread that enters the render layer.
- **That failure is also the best lead in the whole file.** It says the recognised path does
  something specific about the load screen, and whatever that is, is the part a port would have to
  reproduce. It is now RE task #1.
- **The measurement is deferred by decision** (2026-09-22). `perf-stage-readout` was built for it on
  2026-09-20 and has still not been run in a game. That is a defensible call here — the Stage 1
  reads are about *mechanism*, which a profile would not tell us — but it costs us the ability to
  say which features are worth the port, so **every priority claim below is a guess until it runs**,
  and the profile becomes the thing that validates a port rather than the thing that chooses one.
- **Wholesale translation is not on the table.** §2 sizes the binary: 1,435 functions, 359 KB of
  dense, stripped MSVC x86. Budget targeted reads, not a decompile.

## 1. What the first run against a patched binary established

Run 2026-09-22, Edain on a `sage_patch`-patched `game.dat`; the DLL's own log, abridged:

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

Three conclusions, in order of how much they cost us:

**1.1 The build gate is a `.text` checksum, so it is incompatible with `sage_patch` by
construction.** Every other field in the log matches record 0 of the table in
[`render-thread.md`](render-thread.md) §2 — stamp `460DA09E`, sum `00ADC2F6`, entry `0063D082` — and
only `.text 4404F3C6` differs from its `5ED63115`. Stock 2.02 is recognised and works; one patched
byte anywhere in `.text` is not. Note also that the table's `size` field (`00AD4000`) does **not**
match the real `00AD3000` on a build that is otherwise recognised, so §2's caution about that column
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

**1.3 `render-thread.md` §4.1 needs a footnote.** *(Answered by read 1 —
[`accel-thread-identity.md`](accel-thread-identity.md). The DLL has no load-screen handling at all;
it has a thread-identity rule and one critical section, and the unrecognised build picks the wrong
thread. What follows is the question as it stood.)* It answers [`multicore.md`](multicore.md) §3.2
with *"the worker is the only thread that ever calls D3D and the lock is uncontended"*. On a
recognised build that is presumably arranged deliberately; on this run it was false, and the load
screen is why. §4.1's correction of §3.2 still stands — the DLL does ship a working render thread —
but the claim is conditional on handling the second drawing thread, and **how it does that is not
established**. It is the first thing to read.

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
knowledge; we would neither copy nor ship it. Exclude it from any budget.

## 3. The end state

**Decided 2026-09-22: B.** A is dropped; C is the part of B that happens to fit in a cave and is
therefore where B starts.

### A. Ship the author's DLL, loaded from `game.dat`'s import table — *dropped*

Recorded because the reasoning is reusable, not because it is live. `sage_patch` would write an
`IMAGE_IMPORT_DESCRIPTOR` so the Windows loader maps the module before the engine runs, and the
injector would disappear. The static work is small and in-competence — `sage_patch.utils.add_section`
already appends a section and keeps `SizeOfImage` consistent, and an import descriptor plus its
INT/IAT/name blob is the same class of surgery.

It dies on §1.1 regardless of permission: the moment that patch is applied `.text` changes, and the
DLL it just installed will not recognise the binary that installed it. The import-descriptor writer
is still the right mechanism if a module ever needs loading — keep it in mind for B, where the
module is ours and its gate composes.

One unknown goes unanswered with A, and B has to answer it from scratch anyway: **when to arm.**
The DLL's install runs from `DllMain` on `DLL_PROCESS_ATTACH`, which under an import-table load
fires before `d3d9.dll` and `d3dx9_27.dll` exist in the process — and many of its features test
exactly that (`d3d9.dll not loaded - OFF`). It was built for an injector entering a *running*
process; `froze 16 threads` in §1's log is a thing you only write when other threads already exist.
Reading `0x100490A9` tells us which moment it actually wants, and that answer is ours to reuse.

### B. Derive our own — *chosen*

Use the disassembly as reference; write the payload ourselves; name the author on every patch it
produces (§7).

- **What it buys:** licence-clean by construction, our conventions, and — the thing §1.1 makes
  concrete — a build gate that *composes*. `sage_patch` identifies a site by the bytes at that site
  and verifies each edit's originals before writing, so our version of this work survives being
  patched alongside eighty other patches, which the original cannot.
- **It is still the largest thing in this file**, and the headline features do not fit in a cave.
  [`render-thread.md`](render-thread.md) §6 is unchanged on this point and it is not a matter of
  effort: a D3D9 command queue, an `rpmalloc`, an SSE CRT and a worker pool are not cave assembly.
  So B forks once more, and that fork is §6's open decision.
- **B1 — caves only.** Everything expressible as a static edit, which is §3C plus whatever the
  Stage 1 reads promote into it. No new toolchain, no new package, every patch shaped like the
  ninety-two already here. It cannot contain the render thread.
- **B2 — a native companion module of our own.** Adds a C/C++ toolchain to a repo that is pure
  Python today, and changes packaging, CI and CONVENTIONS.md §8's four-gate green build. Say that
  out loud before starting, not after. It is the only route to §3.1 of
  [`render-thread.md`](render-thread.md).
- **Order, under either:** not the render thread. The two features a module makes nearly free are
  `device-lock` and `mutex-critical-section` ([`render-thread.md`](render-thread.md) §5.2/§5.3) —
  both are "replace a kernel primitive with a user-mode one", trivial in C and awkward but possible
  in a cave, so they are the pair that tells us what B2 would actually buy over B1.

### C. Tier 1 static patches, with the disassembly as a shortcut

[`render-thread.md`](render-thread.md) §5's six items; two are built. Permission buys four narrow,
real things:

| target | what reading the DLL gives | value |
|---|---|---|
| ~~§5.5 `present-device-loss`~~ | **Read 2, partial, 2026-09-22: the premise did not survive.** The DLL's `Present` (`0x10008790`) returns a *carried-forward* `HRESULT` from `0x10153DE4`, not the call's own, because the call is queued — and the engine already has a complete device-lost path on `TestCooperativeLevel` at five sites. v47's banner repairs its own queue, not an engine defect. [`render-thread.md`](render-thread.md) §5.5 has the detail | **demoted from highest to doubtful.** Only survives if the engine also checks `Present`'s return — unestablished |
| §5.2 `device-lock` | which 4 call sites it replaces, and how it keeps `0x00DD34C8`/`0x00DD34CC` written as the stock bodies write them — the exact correctness condition §5.2 states it cannot currently specify | high |
| §4.3 `logicspread` | its **9 sites**. Reading them settles the one genuinely open question in §4 | medium, and cheap |
| §5.6 `pick-box-pretest` | the box test and the thresholds its self-check proves against, which a static patch must instead prove once offline | low — gated on the profile saying picking is on it |

Plus, from §1 and outside the original six: **how the recognised build keeps the load-screen thread
out of the moved renderer.** That is not a Tier 1 patch, it is the correctness condition for every
branch, and it is now the first read.

## 4. Staged plan

**Stage 0 — unblock, no code.**
1. ~~Licence terms.~~ **Done, 2026-09-22:** full permission to use the author's work to recreate a
   pySAGE patch of it. That is a derivation licence, which is §3B; it is not a warrant to
   redistribute his binary, and §3A is dropped for independent reasons anyway.
2. ~~Run `perf-stage-readout` in a real Edain match.~~ **Deferred, 2026-09-22.** Still built, still
   unrun. The consequence is recorded in the TL;DR: the Stage 1 reads proceed without it because
   they establish mechanism, but nothing below can claim a feature is *worth* porting until it runs,
   and it is the natural acceptance test for anything Stage 3 ships.
3. Tell the author about §1. A build gate that excludes every patched binary is worth knowing about
   whether or not we ever port a line, and the crash is a real one on his side too.

**Stage 1 — targeted reads, each landing one `docs/*.md`.** In order:
1. ~~**the load screen / second-drawing-thread handling** (§1.3) — the correctness condition;~~
   **Done 2026-09-22:** [`accel-thread-identity.md`](accel-thread-identity.md), including the
   follow-up it raised (the worker does take the same critical section, batched 256 commands deep,
   yielding to the owner through a hand-off flag). Its §4 adds a new Stage 3 candidate that did not
   exist before: a **game-thread-identity cave**, which is where a port should start under either
   branch.
2. **the `Present` hook** (§3C) — converts straight into a patch;
3. **the build-recognition and install path** (`0x100490A9`, §3A) — decides branch A;
4. `devlock`, then the `logicspread` sites, then the `pick` box, by appetite.

Each is a day-ish given §2's map, and each retires a piece of
[`render-thread.md`](render-thread.md) §0's caveat by name. All are useful even if every branch in
§3 is abandoned.

**Stage 2 — choose B1 or B2 (§6), with the first two reads in hand.** Read 1 is the one that
decides it: if keeping the load screen out of a moved renderer turns out to be a handful of gates,
a great deal more of this fits in caves than §3 currently assumes.

**Stage 3 — build.** `present-device-loss` first in any case.

## 5. The changes, concretely

**Always (Stage 1):** this file; amendments to [`render-thread.md`](render-thread.md) §0 (the
caveat), §4.1 (the load-screen footnote) and §6 (the decision), and to
[`multicore.md`](multicore.md)'s banner; one `docs/<feature>.md` per read.

**Branch C, per patch:** `patches/<name>.py`, `tests/sage_patch/test_<name>.py`, `docs/<name>.md`, a
`README.md` entry, and the new constants in `sage_patch.addresses`. `perf_stage_readout` is the size
precedent: 560 lines of patch, 372 of write-up, three test modules.

**Branch B1:** nothing beyond the above. That is the point of it.

**Branch B2, additionally:** a new top-level package, a C/C++ toolchain in CI, an import-descriptor
writer beside `add_section` in `utils.py` to get the module loaded, and a decision about what
`sage-patch verify` means for a patch whose payload is a separate file. Treat as a separate project
with its own scoping document; do not let it arrive as a subdirectory of this one.

**Branch A:** dropped — see §3A.

## 6. What is decided, and the one thing that is not

**Decided.** Branch B: recreate, crediting the author. Branch A dropped. The measurement deferred.

**Decided 2026-09-24: B2 — a native companion module of our own.** The user's call, made with read 3
([`accel-queue.md`](accel-queue.md)) in progress. The scoping document for it is
[`accel-module.md`](accel-module.md); §5's "separate project" rule applies. What follows is the
question as it stood, kept for the reasoning:

- **B1 (caves only)** keeps every patch shaped like the ninety-two already in `patches/`, adds no
  toolchain, and is unarguably `sage_patch`. It cannot contain the render thread — the headline
  feature — and probably cannot contain `rlsort`, `drawgen`, `audiolimit` or `pose-warm2` either.
- **B2 (our own module)** can contain all of it and turns a pure-Python repository into one that
  ships native code, with everything that implies for CI, packaging and the green-build gate.

**It does not block anything yet.** Stage 1's reads are the same under both, and read 1 is what
should inform the answer rather than the other way round — so the recommendation is: **start
reading, decide at Stage 2.**

Order, **revised by the first two reads**. Read 1 is done and read 2 cost the plan its best item
rather than paying for one — which is the normal yield of reading before building, and cheap at a
few hours. What replaces them:

1. **A game-thread-identity cave** ([`accel-thread-identity.md`](accel-thread-identity.md) §4).
   Small, testable on its own through `sage_live`, useful under B1 and B2 alike, and the thing the
   DLL does worst. This is now the first thing to *build*.
2. ~~**The queue and the lock-mirror**~~ — **the queue is read, 2026-09-24:
   [`accel-queue.md`](accel-queue.md).** A single-producer ring with a mechanical queue-or-drain
   split by return type; smaller than feared. The lock mirrors are located (record kinds `3`, `7`,
   `9`) but not read, and they are now where the render thread's real difficulty lives.
3. `devlock`, the `logicspread` sites, the `pick` box — unchanged, by appetite.

**In the meantime: do not run the author's DLL on a patched `game.dat`.** Stock 2.02 is the only
binary it recognises, and §1.2 is why the unrecognised path is worse than no DLL at all.

## 7. Non-goals and risks

- **Attribution, and it is now load-bearing rather than polite.** Every patch derived from this
  work names the author beside ours. [`../README.md`](../README.md)'s author convention exists
  because an author is who gets asked for a fix, and on derived work that is both of us — he knows
  why the code is shaped the way it is and we will not, for a long time. Two chores follow: ask him
  which name he wants on the `author` field, and keep the permission recorded where a reader of the
  patches can find it (this file, §4 Stage 0, dated).
- **Network and replays.** Everything in §3C is client-local. `logicspread` moves only *when* a
  client frame happens inside the logic step and must not move the logic order — the frame CRC
  ([`binary-attest.md`](binary-attest.md) §1) is what it would break if it did.
- **The injector is not the model.** Branch A's point is dropping `CreateRemoteThread`; a
  `sage_patch` that shells out to an injector is not a patch, and would earn the Defender heuristic
  the loader already earned.
- **Nothing here ships experimental.** The README's warning about unplayed patches applies with full
  force to anything derived from a binary we have read but not run.
