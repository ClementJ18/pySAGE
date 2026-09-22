# The render profile the engine already produces

Engine build `2.01.2614.37001`. Addresses are VAs (ImageBase `0x400000`, no ASLR); the file offset
is `VA - 0x400000` for everything cited here. Read **statically** on 2026-09-20 with `capstone`
from the repo-root `game.dat` (11,346,944 bytes), and applied to that same file.

**The complaint.** Nobody has measured a frame on this build.
[`multicore.md`](multicore.md) §6 makes that the gate in front of every threading idea and then
proposes building the instrumentation from scratch — `QueryPerformanceCounter` detours on the
client and logic phases — on the premise that "this engine gives you almost nothing for free".

**That premise is wrong.** The engine instruments its own render in thirty named scopes, and has
since it shipped. What it lacks is not the instrumentation but a *consumer*: the scopes drive
`D3DPERF_BeginEvent` / `D3DPERF_EndEvent`, which do nothing unless a PIX-like profiler is attached.

- **Status: built, unit-tested against an executing cave, and run live on 2026-09-22 — which
  found a defect in it.** The first version keyed each slot on the scope's *name pointer*, and
  §2.1 is what that turned out to be worth: four of the thirty sites build their name on the
  stack, so the table filled with stack addresses within seconds and the two per-mesh stages never
  got a row. It now keys on the **call site**. It is the registered `perf-stage-readout` patch;
  `sage-patch apply perf-stage-readout` is the whole build.
- **Cost:** one six-byte hook, one five-byte hook, and a 2,646-byte `.perfstg` section — 2,352
  bytes of counter block and 303 of code. The patched file is 3,072 bytes larger.
- **Client-local.** No simulation state is read or written, no INI surface, no replay or network
  effect. One player can profile a match everyone else plays on stock binaries.

## TL;DR

- `PerfScope` (`0x00517690` / `0x00517740`) is a stack-allocated RAII object. **Thirty are
  constructed and destroyed per drawn frame**, each naming a stage. §1 lists all thirty.
- The name is `strncpy`'d into the object immediately, so **nothing downstream of the constructor
  can tell two scopes apart** — §2, and the reason the hook is where it is.
- **The key is the call site, not the name.** Twenty-six sites pass an `.rdata` literal; four build
  the name on the stack (§1.2), which filled the table on the first live run (§2.1).
- The patch hooks the constructor and the destructor, stamps `QueryPerformanceCounter` onto a
  nesting stack, and accumulates inclusive and exclusive ticks per call site (§3).
- The destructor is a five-byte `jmp` and nothing else, so that hook displaces no instructions at
  all. The constructor's six displaced bytes end in a `test` whose flags the next branch reads, so
  the cave re-runs them **last** (§3.1).
- A second, larger finding fell out of reading the constructor: the engine pays two `strncpy`s and
  a `strlen` per scope — thousands of times a frame — to build a name string nothing consumes.
  **That is now [`perf-scope-skip`](perf-scope-skip.md)**, and the two compose: §6.

## 1. Thirty named scopes

`PerfScope::PerfScope` at `0x00517690` has **30 callers**; `PerfScope::~PerfScope` at `0x00517740`
has **30**, pairing one for one. Twenty-six of the sites push a name literal, a category literal
and a colour — the other four are §1.2, and they are why this patch keys on the call site:

```asm
00449dcf  53              push ebx                  ; the colour (0)
00449dd0  68fc9dbd00      push 0x00bd9dfc           ; "Frame"      - the category
00449dd5  68ec9dbd00      push 0x00bd9dec           ; "UpdateShadowMap"
00449dda  8d8da8feffff    lea  ecx, [ebp-0x158]     ; the object, on the caller's frame
00449de0  e8abd80c00      call 0x00517690           ; PerfScope::PerfScope
              ...                                   ; the stage's work
00449e00  885dfc          mov  byte [ebp-4], bl     ; unwind state
00449e03  e838d90c00      call 0x00517740           ; PerfScope::~PerfScope
```

Twenty-eight distinct labels across the thirty sites, by where those sites sit — but see §1.2
before reading the last row as a name:

| where | names |
|---|---|
| the frame's draw, `0x00449D…`–`0x0044A0…` | `UpdateShadowMap`, `UpdateWaterReflection`, `RenderViews`, `RenderUI` |
| scene objects, `0x0046B0…`–`0x004717…` | `RenderTrees`, `RenderShrubs`, `RenderBuffs`, `RenderWater`, `RenderDecalShadows`, `RenderVolumeShadows`, `RenderStaticSortLists`, `RenderParticles`, `RenderSmudges` |
| terrain, `0x004E29…`–`0x004E32…` | `DoTerrainSystems`, `RenderTerrain`, `RenderRoads`, `RenderFloors`, `RenderScorches`, `RenderTreeShadows`, `RenderTerrainParticles`, `RenderTerrainTracks`, `RenderWaypoints`, `RenderOrders`, `RenderBibs`, `RenderProps` |
| meshes and shaders, `0x005431…`–`0x00573E…` | `MeshDX8Render` (2 sites), `MeshFXShader` (2 sites), `RenderFXShaderBatch` |

The first eleven pass the category `"Frame"`; the rest pass none. `MeshDX8Render` and
`MeshFXShader` are **per mesh**, not per frame — which is what makes them the interesting rows and
also the expensive ones (§5).

### 1.1 What the scopes drive

The constructor ends by calling `0x0051ECE0`, which widens the name into a `0x200`-byte stack
buffer and calls through `[0x00DD361C]`. The destructor is a tail jump to `0x0051ED60`:

```asm
0051ed60  a12036dd00      mov  eax, [0x00dd3620]
0051ed65  85c0            test eax, eax
0051ed67  7501            jne  0x0051ed6a
0051ed69  c3              ret                       ; no consumer -> nothing happens
0051ed6a  ffe0            jmp  eax
```

Those two pointers are `D3DPERF_BeginEvent` and `D3DPERF_EndEvent`, resolved by name out of
`d3d9.dll` at device init:

```asm
005251b8  a11036dd00      mov  eax, [0x00dd3610]    ; the d3d9 module handle
005251bd  68cc71be00      push 0x00be71cc           ; "D3DPERF_BeginEvent"
005251c4  ffd6            call esi                  ; GetProcAddress
005251d7  a31c36dd00      mov  [0x00dd361c], eax
              ...                                   ; "D3DPERF_EndEvent"   -> 0x00dd3620
              ...                                   ; "D3DPERF_SetMarker"  -> 0x00dd3624
              ...                                   ; "D3DPERF_SetOptions" -> 0x00dd3628
```

and cleared again at `0x00525820`. They are zero in the file and non-null in a running game, because
`d3d9.dll` always exports them — so the scopes always call out, and the call always returns
immediately with no profiler attached. **The instrumentation is complete and its output is
discarded.**

### 1.2 Four sites do not pass a name literal at all

The sentence "each call site pushes a name literal, a category literal and a colour" is true of
twenty-six sites and false of four, and the difference is load-bearing enough to have broken the
first version of this patch (§2.1). The two `MeshDX8Render` sites and the two `MeshFXShader` ones
look like this:

```asm
005431c6  f3a5            rep movsd                 ; concatenate, into a stack buffer
005431ca  6a00            push 0                    ; the colour
005431cc  83e103          and  ecx, 3
005431cf  68e894be00      push 0x00be94e8           ; "MeshDX8Render"  - the CATEGORY
005431d4  8d442414        lea  eax, [esp+0x14]      ; the buffer just built
005431d8  f3a4            rep movsb
005431da  50              push eax                  ; the NAME: a stack address
005431db  8d8c2418010000  lea  ecx, [esp+0x118]
005431e2  e8a944fdff      call 0x00517690
```

So on these sites the **name is the mesh's own name**, composed at runtime — which is what makes
them per-mesh in the first place — and the stage string arrives as the *category*. The fallback
literal `0x00BE94F8` (`"(unnamed)"`) at `0x00573D6D` is the same story from the other end: a mesh
with no name still gets one, from `.rdata`, at a site that would otherwise pass a buffer.

The four sites, and the label this document and the patch use for each:

| call | returns to | label | where the label comes from |
|---|---|---|---|
| `0x005431E2` | `0x005431E7` | `MeshDX8Render` | the category at `0x00BE94E8` |
| `0x00543321` | `0x00543326` | `MeshDX8Render` | the same literal |
| `0x00573D95` | `0x00573D9A` | `MeshFXShader` | the category at `0x00BEA764` |
| `0x00573E18` | `0x00573E1D` | `MeshFXShader` | the same literal |

## 2. Why the constructor, and not the wrapper

The obvious hook is `0x0051ECE0`, which already receives a name and a colour. It is the wrong one.

```asm
00517690  8b442404        mov  eax, [esp+4]         ; arg0: the .rdata literal
00517694  85c0            test eax, eax
00517696  56              push esi
00517697  8bf1            mov  esi, ecx             ; this
00517699  0f8492000000    je   0x00517731           ; a null name does nothing
005176a1  8b3d2406bd00    mov  edi, [0x00bd0624]    ; strncpy
005176a7  6800010000      push 0x100
005176ac  50              push eax
005176ad  56              push esi
005176ae  ffd7            call edi                  ; strncpy(this, name, 0x100)
```

The name is copied into the object on the constructor's fourth instruction. Everything downstream —
including the `push esi` at `0x00517726` that hands the wrapper its name — sees `this`, which is
the caller's `lea ecx, [ebp-0x158]`. **In the frame's draw, that is one address shared by
`UpdateShadowMap`, `UpdateWaterReflection`, `RenderViews` and `RenderUI`**, because they are four
scopes in one function at one stack slot. A profiler hooked on the wrapper would fold all four into
a single row and would have to `strcmp` to avoid it.

At the constructor, then, the arguments are still the caller's. What the patch keys on is one of
them — but not the one this section originally chose.

### 2.1 Why the call site, and not the name

**This is the correction the first live run produced, and it is the most useful thing on this
page.** The obvious key at the constructor is the name pointer: for twenty-six sites it is an
`.rdata` literal, stable and unique, one `cmp` to compare. §1.2 is the other four.

Keyed on the name, a run of the first build reported this after a few minutes at a skirmish:

```
slots_used  64          <- all of them
table_full  4335110     <- scopes that found no slot at all
  9 0x001a4020 ?     4747559   86409319   86409319  '\xff\xff\xff\xff\x84\xe1\x1a'
 55 0x001a3edc ?     3970911   65029028   65029028  ''
 36 0x00bea790 .rdata 2807322  330033463 117361681  'RenderFXShaderBatch'
```

Thirty-six of the sixty-four slots held **stack addresses**, not `.rdata` pointers. The two with
millions of calls are the per-mesh sites, keyed on whatever stack address that frame's buffer
happened to sit at; the rest are the same sites at other stack depths and on the load-screen
thread. `MeshDX8Render` and `MeshFXShader` — the two rows §5 calls the interesting ones — appear
nowhere, because by the time they were reached the table was full.

The fix is to key on **the return address at `[esp]`**, which at the constructor's first
instruction is the call site:

- it is in `.text`, so it is fixed for the life of the process and unique per site;
- there are thirty of them, into sixty-four slots, averaging 1.3 probes;
- it costs exactly what the name cost — one `mov`, one displacement lower;
- and it distinguishes a stage's two call sites, which the reader then sums.

The name is then never dereferenced at all. The label a row prints comes from `STAGE_SITES` in the
patch module, a static table of the thirty return addresses; `apply` refuses a binary in which any
of them is not the byte after a `call` to the constructor, so a build that moved one is rejected
rather than mislabelled.

This is also why `PERF_SCOPE_STAGE_SITE`'s whole push sequence is an anchor rather than just the
constructor's own first instruction: what entitles the cave to read the stack at all is the call
site, not the callee.

## 3. What the patch does

A `.perfstg` section holds a counter block and two routines. The block is fixed-size and comes
first, so the routines can address their own counters absolutely while they are still being
emitted:

| offset | field |
|---|---|
| `+0x00` | magic `'PSTG'`, version, slot capacity (64), stack capacity (32) |
| `+0x10` | depth, slots used, overflow, unbalanced, table-full |
| `+0x28` | the scratch `LARGE_INTEGER` the exit's `QueryPerformanceCounter` lands in |
| `+0x30` | 64 slots × 24 bytes: name, calls, inclusive (u64), exclusive (u64) |
| `+0x630` | 32 stack frames × 24 bytes: slot pointer, pad, start tick (u64), child ticks (u64) |
| `+0x930` | the code |

**Entry** (hooked at `0x00517690`) saves everything, raises the depth, claims a slot for **the
return address at `[esp]`** by open addressing on it (§2.1), zeroes the frame's child accumulator
and stamps the start tick.

A reader turns that key back into a name through `STAGE_SITES`, and sums the two sites that share
a label.

**Exit** (hooked at `0x00517740`) lowers the depth, takes a second tick, and:

- adds the whole span to the **parent** frame's child accumulator, if there is a parent;
- adds the span to the slot's **inclusive** total;
- subtracts this frame's own children from the span and adds the remainder to **exclusive**.

So `RenderViews` inclusive is everything the view pass cost, and `RenderViews` exclusive is what it
cost outside `RenderTerrain`, `MeshDX8Render` and the rest.

### 3.1 The two hooks are asymmetric, and that is the point

The destructor is *nothing but* a five-byte `jmp` to `0x0051ED60`. The hook replaces that jump with
a jump into the cave and the cave ends with the jump that was there. **No instruction is
displaced.**

The constructor's first six bytes are `mov eax, [esp+4]` / `test eax, eax`, and the `je` two
instructions later reads the flags that `test` set. The cave therefore re-runs both **at the end of
its routine**, immediately before jumping back to `0x00517696` — anything between would have to
preserve the flags across a `QueryPerformanceCounter` call, and re-running is cheaper than saving.
Five bytes of jump replace six bytes of instruction, so the sixth is a `nop`.

### 3.2 Three ways a scope declines to be measured, and one that used to be a bug

The counters exist because each of these happens, and each has a test that executes the cave:

- **A null name.** The constructor tolerates one and skips its whole body — and since the key is
  the call site, the scope is measured like any other. (Keyed on the name there was nothing to key
  it on, so it was timed by nobody; the frame still had to be pushed or the next exit would close
  somebody else's.)
- **An unbalanced exit** (depth already zero). Counted, and nothing is written.
- **The nesting stack full.** This is the one that was wrong first. The entry originally declined to
  raise the depth when it declined to push a frame — and then the matching exit lowered it anyway,
  closing the frame *below* and shifting every attribution by one level for the rest of the session.
  The entry now raises the depth unconditionally and the exit discards any level at or above the
  capacity. Observed nesting is 3 deep against a capacity of 32, so this should never fire; it is
  tested at 36 deep because "should never" is not a guarantee, and a silent one-level shift is
  indistinguishable from a real profile.

## 4. What it does not do

- **It does not touch the D3DPERF pointers.** A PIX capture still works and still says exactly what
  it said before. The patch measures the scope, not the event.
- **It does not reset.** The counters accumulate from process start. A reader takes two samples and
  subtracts, which is also how it gets a per-frame figure without the cave needing to know what a
  frame is.
- **It does not record a frequency.** `QueryPerformanceFrequency` is invariant system-wide, so the
  reader calls it rather than the cave storing it.
- **It is not interlocked.** The load screen draws on its own thread ([`multicore.md`](multicore.md)
  §1.1) and can enter these scopes while the main thread is in one. The counters are plain adds, so
  numbers gathered while a map is loading may be mixed. Every write is bounds-checked, so that is a
  wrong number and never a wrong address.

## 5. What it costs

Two `QueryPerformanceCounter` calls and about forty instructions per scope. Twenty-six of the
twenty-eight names are once-per-frame and cost nothing worth measuring. `MeshDX8Render` and
`MeshFXShader` are per mesh, so on a heavy frame this is a few thousand QPC pairs — on the order of
a few tenths of a millisecond.

That is the honest cost, and it is why this is a diagnostic rather than something to ship in a mod
release. It is also, as §6 explains, considerably **less** than what the stock engine already
spends on the same call path.

## 6. The thing this patch found and does not fix — now `perf-scope-skip`

**Resolved.** This section scoped a sibling patch and left two questions open. Both are answered
and the patch is built: [`perf-scope-skip.md`](perf-scope-skip.md).

What it found, in short. `PerfScope::PerfScope` does real work before it reaches the D3DPERF call,
on every scope:

```asm
005176ae  ffd7            call edi                  ; strncpy(this, name, 0x100)
005176c2  8b15b85bbe00    mov  edx, [0x00be5bb8]    ; "SceneAnalyst", 13 bytes, copied inline
005176f0  8a08            mov  cl, [eax]            ; strlen over the result
005176f7  75f7            jne  0x005176f0
0051770c  ffd7            call edi                  ; strncat(this+0x100+len, category, ...)
```

`0x00BD0624` is `msvcr71!strncpy`, and **`strncpy` pads to `n`** — so the first call writes 256
bytes whatever the name's length. About 313 bytes per scope, into a `0x140`-byte buffer on the
caller's stack, for an event that with no profiler attached is never read. **Per mesh**, for two of
the thirty.

The two open questions, closed in [`perf-scope-skip.md`](perf-scope-skip.md) §4:

1. **What the destructor does then.** Nothing different. The `mov byte [ebp-4], N` at each site is
   the *caller's* MSVC exception state; the constructor uses `ebp` as a saved scratch register
   rather than a frame pointer and the destructor is five bytes of `jmp`, so neither can reach it.
   The object stays "constructed" as far as the unwinder is concerned and the destructor still runs
   on both paths.
2. **Whether anything else reads the object.** Nothing does. All 64 memory references to a
   scope-object stack slot, across the eight functions that construct one, are `lea ecx` feeding
   the constructor or the destructor — no reads, and every call site discards the `this` the
   constructor returns.

The gate turned out not to be the one this section guessed at either. `D3DPERF_BeginEvent` is
exported by `d3d9.dll` whether or not anyone is listening, so the engine's own null test can never
fire and neither can a copy of it; the question that works is `D3DPERF_GetStatus`, which the engine
does not resolve and the patch resolves for itself.

**The two patches compose, and the pair is what to run.** `perf-scope-skip` hooks the
constructor's null-name branch at `0x00517699`; this patch hooks the six bytes at `0x00517690`,
*before* it. So the readout still times every scope while the scope no longer builds a name.

## 7. What to do with the numbers

This is [`multicore.md`](multicore.md) §6.1, answered. The reader is
[`../scripts/perf_stage_dump.py`](../scripts/perf_stage_dump.py):

```
python -m sage_patch.scripts.perf_stage_dump --seconds 20 --csv fight.csv
```

It attaches read-only through `sage_live`'s `ProcessMemory`, finds `.perfstg` by walking the mapped
section table (the magic `'PSTG'` confirms it), takes two samples and subtracts, labels each row
through `STAGE_SITES`, and derives the window's frame count from `RenderViews`' call count — so
`ms/frame` needs nothing from the engine, and `calls/frame` on the two mesh rows *is* the mesh
count. Elevation is needed only if the game is running elevated.

The question the numbers settle is the one §6 was gating: whether the render is where a heavy frame
goes, and if so which stage. `RenderViews` exclusive against `MeshDX8Render` inclusive is the split
between "the view pass is slow" and "there are too many meshes", and those have different answers —
the first is [`render-thread.md`](render-thread.md) §6's territory and the second is not a threading
problem at all.

## Address table

| VA | what |
|---|---|
| `0x00517690` | `PerfScope::PerfScope(name, category, colour)`, `__thiscall`, 30 callers — hooked |
| the 30 return addresses | `STAGE_SITES` in the patch module: the key the cave uses and the label a reader prints (§2.1) |
| `0x005431E2` / `0x00543321` / `0x00573D95` / `0x00573E18` | the four sites whose *name* is a stack buffer; the stage literal is their category (§1.2) |
| `0x00BE94E8` / `0x00BEA764` / `0x00BE94F8` | `"MeshDX8Render"`, `"MeshFXShader"`, `"(unnamed)"` |
| `0x00517696` | where the entry cave returns, past the displaced `mov`/`test` |
| `0x00517731` | the constructor's null-name exit |
| `0x00517740` | `PerfScope::~PerfScope` — five bytes of `jmp`, 30 callers — hooked |
| `0x0051ECE0` | the `D3DPERF_BeginEvent` wrapper: ASCII → UTF-16 into a `0x200` stack buffer |
| `0x0051ED60` | the `D3DPERF_EndEvent` wrapper: a null test and a tail jump. The exit cave's target |
| `0x00DD361C` / `0x00DD3620` | `D3DPERF_BeginEvent` / `D3DPERF_EndEvent`; `+0x24` `SetMarker`, `+0x28` `SetOptions` |
| `0x005251B8`..`0x00525202` | where all four are resolved; `0x00525820` clears them |
| `0x00449DCF` | `UpdateShadowMap`'s scope — the anchor that fixes the calling convention |
| `0x00BD9DEC` / `0x00BD9DC8` / `0x00BD9DBC` / `0x00BD9DFC` | `UpdateShadowMap`, `RenderViews`, `RenderUI`, `"Frame"` |
| `0x00BE5BB8` | `"SceneAnalyst"`, the prefix the constructor builds (§6) |
| `0x00BD0624` | `strncpy` in the IAT — the per-scope cost of §6 |
| `0x00BD02E8` | `QueryPerformanceCounter` in the IAT — what both cave routines call |
