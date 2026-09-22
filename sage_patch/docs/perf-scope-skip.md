# The render pays megabytes a frame to label events nobody reads

Engine build `2.01.2614.37001`. Addresses are VAs (ImageBase `0x400000`, no ASLR); the file offset
is `VA - 0x400000` for everything cited here. Read **statically** on 2026-09-20 with `capstone`
from the repo-root `game.dat` (11,346,944 bytes).

This is [`perf-stage-readout.md`](perf-stage-readout.md) §6, promoted to a patch. That document
derives the render-scope class; this one derives what the class **costs** and closes the two
questions §6 left open. Read §1 of that document first — the thirty scopes and where they are — or
this one starts in the middle.

- **Status: built, unit-tested against both routines executing, not yet played.** It is the
  registered `perf-scope-skip` patch; `sage-patch apply perf-scope-skip` is the whole build.
- **Cost:** one six-byte hook, one five-byte hook, and a 136-byte `.pscope` section — 32 bytes of
  flag block and 104 of code. The patched file is 512 bytes larger.
- **Client-local.** No simulation state, no INI surface, no replay or network effect.

## TL;DR

- The scope constructor spends **two `strncpy` calls, a 13-byte inline copy and a `strlen`** — about
  **313 bytes written** — building a name string, per scope. §1.
- `strncpy` **pads to `n`**. The first call passes `n = 0x100`, so it writes 256 bytes whether the
  name is `RenderUI` or `RenderTerrainParticles`. That is most of the cost and it is invisible in
  the source. §1.1.
- Two of the thirty scopes are **per mesh**. A frame drawing three thousand meshes does this about
  six thousand times: **on the order of two megabytes of string traffic per frame**, in the render
  path, in the shipping build. §2.
- It is built for `D3DPERF_BeginEvent`, which with no profiler attached **returns without reading
  it**. §2.1.
- The patch asks `D3DPERF_GetStatus` — which the engine never resolves — once at device init, and
  when the answer is no it sends the scope down **the engine's own do-nothing exit**. §3.
- §4 closes `perf-stage-readout.md` §6's two open questions: **nothing reads the buffer** (64 of 64
  references are `lea ecx` feeding the constructor or destructor) and **the unwind state is the
  caller's**, untouchable by either routine.

## 1. What a scope costs to open

`PerfScope::PerfScope` (`0x00517690`), after the null-name test:

```asm
005176a1  8b3d2406bd00    mov  edi, [0x00bd0624]    ; msvcr71!strncpy
005176a7  6800010000      push 0x100
005176ac  50              push eax                  ; the name
005176ad  56              push esi                  ; this
005176ae  ffd7            call edi                  ; strncpy(this, name, 0x100)

005176c2  8b15b85bbe00    mov  edx, [0x00be5bb8]    ; "SceneAnalyst", 13 bytes,
005176d0  8911            mov  [ecx], edx           ;   copied as 3 dwords and a byte
005176e4  8a15c45bbe00    mov  dl, [0x00be5bc4]
005176ea  88510c          mov  [ecx+0xc], dl

005176f0  8a08            mov  cl, [eax]            ; strlen(this + 0x100)
005176f2  83c001          add  eax, 1
005176f7  75f7            jne  0x005176f0
005176fb  b940000000      mov  ecx, 0x40
00517700  2bc8            sub  ecx, eax             ; 0x40 - len
0051770c  ffd7            call edi                  ; strncpy(this+0x100+len, category, 0x40-len)

00517727  e8b4750000      call 0x0051ece0           ; -> D3DPERF_BeginEvent
```

`0x00BD0624` is `msvcr71.dll!strncpy`, confirmed from the import directory.

### 1.1 `strncpy` pads, which is where the bytes go

`strncpy(dest, src, n)` copies `src` and then **fills the remainder of `n` with zeros**. It is the
standard C function's standard surprise, and here it means the first call writes **256 bytes every
time**, regardless of the name. The second writes `0x40 - len`, so another ~44.

Per scope, then: 256 + 13 + ~44 ≈ **313 bytes written**, plus a `strlen` over the prefix and two
CRT calls. Call it 333 with the widening in §2.1.

The object is `0x140` bytes on the **caller's** stack — `lea ecx, [ebp-0x158]` at every site — so
none of this is a heap allocation. It is just writes, to a buffer that is about to be abandoned.

## 2. Times thirty, and two of the thirty are per mesh

[`perf-stage-readout.md`](perf-stage-readout.md) §1 has the full list. Twenty-six of the twenty-eight
names are once per frame and cost nothing worth counting. The exceptions:

| name | sites | when |
|---|---|---|
| `MeshDX8Render` | `0x005431E2`, `0x00543321` | per mesh drawn |
| `MeshFXShader` | `0x00573D95`, `0x00573E18` | per shader-driven mesh |

A late-game frame drawing three thousand meshes therefore opens roughly six thousand scopes, at
~333 bytes each: **about two megabytes written per frame**, all of it into stack buffers that are
never read. At 30 fps that is sixty megabytes a second of memory traffic whose only purpose is to
label events.

The measured figure is what [`perf-stage-readout`](perf-stage-readout.md) exists to produce, and
this document deliberately does **not** claim one — §7 says what to measure.

**What this patch does not remove, at exactly those four sites.** Each of them *composes* the
scope's name before the call: a `strlen` and a `rep movsd`/`rep movsb` concatenation into a stack
buffer, because on these sites the name is the mesh's own name and the stage string is the category
([`perf-stage-readout.md`](perf-stage-readout.md) §1.2). The gate here is inside the constructor,
so the ~313 bytes and two CRT calls it removes are removed per mesh as claimed — but the caller's
concatenation still runs, and it is still building a string for a reader that is not there. Gating
*that* means editing four call sites rather than one branch, and it should be costed against a
profile rather than assumed.

### 2.1 And the reader is not there

`0x0051ECE0` widens the finished ASCII string into a `0x200`-byte stack buffer as UTF-16 (a loop
that stops at the terminator, so this part really is proportional to the name) and calls through
`0x00DD361C`. That pointer is `D3DPERF_BeginEvent`, resolved from `d3d9.dll` at device init.

With no profiler attached, `D3DPERF_BeginEvent` returns immediately and never dereferences the
string. Everything in §1 is built for nobody.

## 3. What the patch does

Two hooks and a byte.

### 3.1 The gate reuses the engine's own do-nothing exit

The constructor already knows how to do nothing. Its second instruction tests the name and its
fourth branches on it:

```asm
00517690  8b442404        mov  eax, [esp+4]         ; the name
00517694  85c0            test eax, eax
00517696  56              push esi
00517697  8bf1            mov  esi, ecx             ; this
00517699  0f8492000000    je   0x00517731           ; <- the hook
0051769f  55              push ebp                  ; <- the body
...
00517731  8bc6            mov  eax, esi             ; the do-nothing exit:
00517733  5e              pop  esi                  ;   return this,
00517734  c20c00          ret  0xc                  ;   unwind the push, clean the args
```

`0x00517731` already returns the object in `eax` and unwinds the one `push esi` the entry made.
**That is exactly the ABI a skipped scope needs**, so the patch does not assemble a return sequence;
it borrows this one.

The six bytes at `0x00517699` become a jump into a four-instruction gate:

```asm
je   take_exit                  ; the branch being replaced, unchanged: a null name does nothing
cmp  byte [enabled], 0
jne  run_body                   ; somebody is listening -> build the name exactly as stock
take_exit:
jmp  0x00517731
run_body:
jmp  0x0051769F
```

Two things make that safe. The flags reaching `0x00517699` are still the ones `test eax, eax` set —
`push` and `mov` do not touch flags, and neither does the `jmp` that replaces the branch — so the
first instruction of the gate *is* the branch it replaced. And `cmp` against memory plus two jumps
disturbs neither `eax` (the name) nor `esi` (the object), which the body pushes three instructions
later.

### 3.2 The probe asks the question the engine never asks

The obvious gate is "is `0x00DD361C` null", and it is useless: `d3d9.dll` exports
`D3DPERF_BeginEvent` whether or not anyone is listening, so the pointer is **never** null in a
running game and the engine's own null test can never fire.

`D3DPERF_GetStatus` is the documented question. The engine resolves four D3DPERF entry points and
this is not one of them, so the patch resolves it itself, at the tail of the engine's own resolve
where `d3d9.dll` is loaded and its handle is in `0x00DD3610`:

```asm
005251f5  a11036dd00      mov  eax, [0x00dd3610]    ; the d3d9 module handle
005251fa  689071be00      push 0x00be7190           ; "D3DPERF_SetOptions"
005251ff  50              push eax
00525200  ffd6            call esi                  ; GetProcAddress
00525202  a32836dd00      mov  [0x00dd3628], eax    ; <- the hook, five bytes
00525207  6a20            push 0x20                 ; <- the resume
```

The cave re-runs the displaced store, saves everything, resolves `D3DPERF_GetStatus` through
`GetProcAddress` (IAT `0x00BD018C`), calls it, and records the answer in one byte. **The byte
defaults to zero**, which is both "nobody is listening" and the right answer for the window before
a device exists, and for a run that never creates one.

If `GetProcAddress` fails — a `d3d9.dll` replacement that omits the export, DXVK — the answer is
zero. That is the fast path, and it is the correct answer for a runtime with no PIX in it.

### 3.3 What is left behind

The destructor still calls `D3DPERF_EndEvent` for a scope whose `BeginEvent` never happened.

An unbalanced `End` matters only to a profiler's nesting counter — and **when a profiler is
attached, this gate does not fire**. The only runs that produce the imbalance are the ones with
nothing there to mind it, where `D3DPERF_EndEvent` reads `0x00DD3620`, tail-jumps into `d3d9.dll`
and returns immediately.

It is worth being exact about what is *not* being claimed here. The constructor is written to
tolerate a null name and the destructor is unconditional, so the engine's own code anticipates this
pairing — but **no call site passes null**, so that arm is dead in a stock build. "The engine
already does this" would be a statement about code that never runs, and it is not the argument. The
argument is the previous paragraph.

> **Correction (2026-09-22).** This paragraph used to say "all thirty call sites push an `.rdata`
> literal". Twenty-six do. The two `MeshDX8Render` sites and the two `MeshFXShader` ones build the
> name on the caller's stack and pass the stage string as the *category* instead — see
> [`perf-stage-readout.md`](perf-stage-readout.md) §1.2, which is where it cost something. It costs
> nothing here: this gate never looks at the name, only at whether anyone is listening.

What is left is one predictable indirect call against the ~313 bytes and two CRT calls this
removes. Gating it as well would mean editing the five bytes at `0x00517740` that
[`perf-stage-readout`](perf-stage-readout.md) owns — see §5.

## 4. The two questions §6 left open, closed

### 4.1 Nothing reads the buffer

The object is `0x140` bytes on the caller's frame. If any caller read it back, skipping the
constructor would hand it garbage.

None does. Across the **eight functions** that construct a scope, every memory reference to a
scope-object stack slot — 64 of them — is a `lea ecx` feeding the constructor or the destructor.
There is not one read, not one write outside the constructor, and no address of the slot is taken
for anything else.

The method matters, because a naive answer here is easy to get wrong: a linear disassembly of
`.text` desynchronises and finds nothing at all. The count above comes from disassembling each
enclosing function from a **known function start** — the set of `call` targets in `.text` — and
classifying every operand that names one of the slots the ctor/dtor calls are fed from.

The one thing this does not rule out is a reader reached indirectly, by a pointer copied out of
`ecx` inside the constructor. The constructor keeps `this` in `esi`, passes it to `strncpy` and to
`0x0051ECE0`, and returns it in `eax` — and every call site discards the return value.

### 4.2 The unwind state is the caller's, and neither routine can touch it

Each site brackets its scope with `mov byte [ebp-4], N`, which is MSVC's exception-state variable —
the thing that tells the unwinder which objects are live.

It belongs to the **caller**. The constructor never establishes a frame pointer: it uses `ebp` as
an ordinary saved register holding its second argument (`push ebp` at `0x0051769F`, `mov ebp,
[esp+0x20]` at `0x005176B0`, `pop ebp` at `0x00517730`), so the `[ebp-4]` it could write is not the
caller's. The destructor is five bytes of `jmp` and touches nothing at all.

So short-circuiting the body cannot affect unwinding. The caller still sets the state, the object
is still "constructed" as far as the unwinder is concerned, and the destructor still runs — on the
normal path and on the exceptional one.

## 5. Composition with `perf-stage-readout`

The two patches hook the same function nine bytes apart:

| patch | sites |
|---|---|
| `perf-stage-readout` | `0x00517690`..`0x00517695` (six bytes), `0x00517740` (five) |
| `perf-scope-skip` | `0x00517699`..`0x0051769E` (six bytes), `0x00525202` (five) |

They are order-independent, and **that took a fix**. This patch's first build anchored on
`PERF_SCOPE_CTOR`'s first twelve bytes, which span both its own hook and the readout's; the pair
then applied in one order and refused in the other. Both anchors were narrowed — the readout's to
nine bytes, ending before the gate, and this one's moved to `0x00517696`'s `push esi` / `mov esi,
ecx`, which is the first part of the constructor the readout leaves alone.

The invariant is now checked mechanically rather than by eye:
`TestComposition::test_neither_patch_anchors_on_what_the_other_writes` applies each patch, collects
the sites it overwrites from the declared hook widths, and asserts the other's anchor ranges do not
intersect them. Reinstating the old anchor makes it fail with the exact six-byte overlap.

**Applied together they are complementary**, and that is the combination worth running: the readout
still times every scope, because it hooks the constructor's entry *before* the gate, and the scope
no longer builds a name. You get the render profile without the measurement paying for a string.

## 6. What this is not

- **Not a fix for the D3DPERF call itself.** The events still fire when a profiler is attached, and
  a PIX capture comes out labelled exactly as before.
- **Not a removal of the scopes.** The objects are still constructed and destroyed; only the string
  building is skipped. Removing them would mean editing thirty call sites.
- **Not measured.** §2's arithmetic is arithmetic. The frame it is arithmetic *about* has not been
  profiled on this build — that is [`perf-stage-readout`](perf-stage-readout.md)'s job and it has
  not been run in a game either.
- **Not a live toggle.** The byte at `.pscope+4` can be flipped through `sage_live` to turn the
  names back on without unpatching, but nothing in the engine writes it after the probe.

## 7. What to measure, when either of these is finally played

Both patches are static-verified and unplayed, so the first run is a correctness run, not a
benchmark: the game starts, a skirmish renders, nothing is missing from the screen.

After that, the number this patch is *for* comes from the other one. Apply
`perf-stage-readout` alone and record `MeshDX8Render` inclusive over a late-game frame; apply both
and record it again. The difference is what the labels were costing, and it is the first real
figure anyone will have had for it.

If it is small, this patch is a curiosity and [`render-thread.md`](render-thread.md) §5.2 is where
to go next. If it is not, it is the cheapest frame time in the engine.

## Address table

| VA | what |
|---|---|
| `0x00517690` | `PerfScope::PerfScope`; `0x00517694` the `test` whose flags the gate inherits |
| `0x00517696` | `push esi` / `mov esi, ecx` — this patch's anchor, clear of the readout's hook |
| `0x00517699` | the null-name `je` — **hooked**, six bytes |
| `0x0051769F` | the body, where a live scope falls through to |
| `0x005176A1`..`0x0051770C` | the two `strncpy` calls, the inline prefix copy and the `strlen` |
| `0x00517731` | the do-nothing exit the gate reuses: `mov eax, esi` / `pop esi` / `ret 0xC` |
| `0x00517740` | `PerfScope::~PerfScope` — untouched here, owned by `perf-stage-readout` |
| `0x0051ECE0` | the `D3DPERF_BeginEvent` wrapper and its UTF-16 widening loop |
| `0x005251F5` | the resolve tail the probe anchors on |
| `0x00525202` | `mov [0x00DD3628], eax` — **hooked**, five bytes; resume `0x00525207` |
| `0x00DD3610` | the `d3d9.dll` module handle the probe borrows |
| `0x00DD361C` | `D3DPERF_BeginEvent` — never null in a running game, which is why it cannot be the gate |
| `0x00BD0624` | `msvcr71!strncpy` — the cost |
| `0x00BD018C` | `kernel32!GetProcAddress` — how the probe reaches `D3DPERF_GetStatus` |
| `0x00BE5BB8` | `"SceneAnalyst"`, the 13-byte prefix |
| `0x005431E2` / `0x00543321` / `0x00573D95` / `0x00573E18` | the four per-mesh scope sites |
