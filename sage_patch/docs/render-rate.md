# Raising the frame rate without speeding the game up

> ⚠ **Tried and withdrawn.** The patch this document designed was built, run in a game, and
> **removed** — it paces correctly and still breaks the client, for a reason that is a property of
> the engine rather than of the implementation. [§8](#8-why-this-approach-does-not-work-and-what-would)
> is the measurement and the verdict, and is the part of this document worth reading first.

Engine build `2.01.2614.37001`. Addresses are VAs (ImageBase `0x400000`, no ASLR); the file offset
is `VA - 0x400000` for everything cited here. Read **statically** on 2026-08-18 with `pefile` +
`capstone` from `sage_mods/edain/patching/engine/game.dat.backup` (11,346,432 bytes) — see
[§0](#0-which-game-dat) for why that file and not the one in the repo root — and confirmed against
the running process with `sage_live`.

**The complaint.** The game draws at 30 fps, and raising `FramesPerSecondLimit` to get more makes
everything run faster instead.

**What the engine actually does: frame rate and simulation rate are not the same clock, and the
two are already decoupled.** SAGE here simulates at **5 logic frames per second** and draws at
**30 client frames per second**, keeps a sub-frame counter on `TheGameEngine`, and hands the render
path an **interpolation alpha** at `TheGameEngine+0x3C` that seven sites already lerp transforms
with. What welds them together is one comparison: the wrap that ends a logic frame is written
against a **literal 6** instead of against the ratio the engine derives from the two rates.

**Where that leads, and where it stops.** Moving the client rate and that literal together does
hold the simulation at 5 Hz at any frame rate — §8 measures it doing exactly that in a live match.
It is still not enough, because the client rate is not only a draw rate: a great deal of client
content is **authored in client frames** and advanced one unit per client frame, so doubling the
rate halves its wall-clock duration. Particle FX run at double speed, animations stick, the spell
store stops taking clicks.

- **Status: designed, built, run, and withdrawn.** §1–§4 are the reverse engineering and are
  sound; §8 is why the patch was removed and what shape the successor has to have. The
  three-rate design it names — logic / client content / render — is the open work.
- **Cost, had it worked:** four immediate bytes, one dword and four floats. No cave, no assembly.
- **Value that survives:** the rate block and its dead setter (§1), the main loop and its pace
  (§2), the sub-frame architecture and the interpolation alpha (§3), and the live read-out in §8
  are all reusable by anything that touches pacing.

## TL;DR

- **The logic rate is 5 and the client rate is 30**, statically initialised in `.data` at
  `0x00D9F608`/`0x00D9F60C` with ten derived floats. The setter that would fill that block,
  `0x00644F11`, has **zero callers in the image** — these are compile-time constants in writable
  memory. This corroborates [`description-timers.md`](description-timers.md) §1.4 from the other
  end.
- **`TheGameEngine` (`0x00DE4324`) carries the sub-frame state.** `+0x34` is the client frame
  within the current logic frame, `+0x38` the ratio `clientRate / logicRate`, `+0x3C` the alpha.
- **One loop iteration = one client frame; the wrap ends a logic frame.** The main loop paces
  itself to `GameEngine+0x0C` (`FramesPerSecondLimit`) and calls `GameEngine::update` once per
  iteration; `0x0063264A` compares the sub-frame counter against **6** and, when it passes, runs
  the simulation. That is the whole coupling.
- **Almost everything else already derives the ratio properly.** The sub-frame predicate at
  `0x0063252F` and the catch-up loop at `0x00632A95` both compute `clientRate / logicRate` at
  runtime and behave correctly at any ratio of 6 or more — **neither needs an edit**. Only two
  literals and the timecode stride do.
- **The simulation is untouched.** The logic rate does not move, `GameLogic::update` still advances
  its frame counter five times a second, and no simulation state depends on the sub-frame index.
- **There is no "uncapped".** The wrap counts frames, not milliseconds. [§6](#6-what-uncapped-would-cost)
  scopes what a wall-clock wrap would take and why it is a different patch.

## 0. Which `game.dat`

**The `game.dat` in the repo root is not stock**, and two of its differences are inside the pacing
code this patch is about. Diffed against `sage_mods/edain/patching/engine/game.dat.backup` it has
eleven differing runs, including:

| VA | backup | repo root |
|---|---|---|
| `0x00632537` | `idiv dword [0x00D9F608]` (the logic rate) | `idiv dword [0x00ECA400]` |
| `0x00ECA400` | `0` | `8` |
| `0x00632A9B` | `idiv [0x00D9F608]` / `mov ecx, eax` | `mov eax, 2` / `jmp 0x00632ABB` |
| `0x0084B43D`+ | — | ~60 bytes rewritten in the LAN transport |

The first two turn the sub-frame predicate of §3.3 from "fire on sub-frame 1" into "fire on
sub-frame 2"; the third hardcodes the catch-up bound of §3.4 and leaves two instructions before it
dead. Anything derived from that file about *this* area has to be re-derived, and was.

**None of this patch's five sites is in a differing run**, so it applies identically to both files
— which is worth asserting against every `game.dat` in the tree rather than against one of them,
for anything that edits this area next.

## 1. The two rates

`0x00644F11` takes `(logicRate, clientRate)`, clamps both to at least 1, forces
`clientRate >= logicRate`, **caps their ratio at 6**, and fills a twelve-dword block. **It is never
called** — no `call rel32` targets it and its address is in no vtable or table. The block is a
static initialiser:

| VA | value | what it is |
|---|---|---|
| `0x00D9F608` | `5` | **logic rate** — frames per second |
| `0x00D9F60C` | `30` | **client rate** — frames per second |
| `0x00D9F610` | `0.005` | `logic/1000` |
| `0x00D9F614` | `200.0` | `1000/logic` — ms per logic frame |
| `0x00D9F618` | `5.0` | `(float)logic` |
| `0x00D9F61C` | `0.2` | `1/logic` — seconds per logic frame |
| `0x00D9F620` | `33.333` | `1000/client` — ms per client frame |
| `0x00D9F624` | `0.03` | `client/1000` |
| `0x00D9F628` | `30.0` | `(float)client` |
| `0x00D9F62C` | `0.0333` | `1/client` |

Corroborated from outside the binary: `sage_replay`'s finalized BFME2 corpus clusters at 0.20
seconds per timecode, and an `Upgrade`'s `BuildTime` in seconds becomes frames by
`BuildTime * [0x00D9F608]` at `0x0066F1A8`.

**The static block and the dead setter disagree by one ulp.** `client/1000` ships as `0x3CF5C28F`,
which is `float(30 * 0.001)` folded in **double** by the compiler; the setter's
`mulss` against `0.001f` would produce `0x3CF5C290`. The patch reproduces the compiler, because the
compiler's bytes are the ones the engine runs on — and reproducing all four floats exactly at 30 is
the test that says so.

## 2. The main loop

At `0x00639EC6`, with `esi = TheGameEngine`:

```asm
00639ec6  cmp  byte [esi+0x10], bl     ; m_quitting
00639ee1  call [eax+0x28]              ; GameEngine::update (vtable 0x00BD84E0 +0x28 = 0x0044181F)
...
0063a01b  mov  al, [GlobalData+0x26]   ; UseFPSLimit -> the loop's flag at 0x00DE4320
0063a196  call [timeGetTime]
0063a19c  fild dword [esi+0xc]         ; m_maxFPS
0063a1a1  fmul dword [0x00d9f498]      ;   * the network slowdown scalar
0063a1a7  fdivr dword [0xbd4388]       ;   1000.0 / that = target ms per iteration
0063a1dc  push ebx / call [Sleep]      ; Sleep(0), spin until the iteration has cost enough
```

`+0x0C` is the *only* thing the pace is derived from. Its live source is
`GlobalData+0x28` = `GameData FramesPerSecondLimit`, pushed through
`TheGameEngine`'s vtable `+0x48` at `0x00779DCF`; the constructor at `0x0063A49C` leaves it 0 and
both fields default to 0, so the shipped INI is what sets them.

**Why the patch does not force that field.** vtable `+0x48` resolves to `0x0066F0FD` — `mov [ecx+0xc], eax ; ret 4` —
which the linker has **COMDAT-folded** across many unrelated classes; one of its ten callers
(`0x0062171A`) passes a *stack local* as `this`. Writing a constant into it would corrupt every
other user of that accessor. So the field stays INI's, and the patch says so loudly.

## 3. Where a loop iteration becomes a logic frame

`GameEngine::update` (`0x0044181F`) opens by calling `0x006325A0`, which owns the counter:

```asm
00632601  mov  ecx, [esi+0x34]         ; the sub-frame counter
00632604  cmp  ecx, 6                  ; <-- literal  (patched: 1)
00632607  jne  0x632622
00632609  cmp  byte [esi+0x40], 0      ;   the "rates changed" latch
0063260f  mov  eax, [0x00d9f60c]       ;   client rate
00632615  idiv dword [0x00d9f608]      ;     / logic rate
0063261f  mov  [esi+0x38], eax         ;   +0x38 = the ratio
00632622  lea  eax, [ecx+1]
00632625  mov  [esi+0x34], eax         ; advance the sub-frame
00632631  imul ecx, ecx, 0xa           ; logicFrame * 10           <-- stride
00632634  lea  eax, [ecx+eax-1]        ;   + subFrame - 1 = a client timecode
00632642  call 0x63256f                ; recompute the alpha
00632647  mov  eax, [esi+0x34]
0063264a  cmp  eax, 6                  ; <-- THE WRAP  (patched: the ratio)
0063264d  jle  0x6326eb                ;   no wrap -> vtable +0x98 (subFrame)
006326bb  mov  [esi+0x34], ebx         ;   wrap: subFrame = 1
006326c6  call [eax+0x98]              ;   -> 0x006329B0 with 1
```

and `0x006329B0` reaches the simulation at `0x00632A82` (`GameLogic::update`, `0x0062E4E8`), whose
frame counter increments at `0x0062E577`.

`GameLogic::update(n)` is called on **every** client frame with the sub-frame index, but the sim
work is gated on `n == 1`: `0x0062E606` latches that into `ebp-0xd`, and the object sweep over
`TheGameLogic+0xAC` at `0x0062EC55` sits behind `0x0062EC4B`'s test of it. So:

> one loop iteration = one client frame; every sixth client frame = one logic frame.

Run the loop at 60 and the counter passes 6 ten times a second. **That is the bug, and
`0x0063264A` is where it lives.**

### 3.1 The alpha

`0x0063256F`, on every sub-frame: `+0x3C = clamp(+0x34 / +0x38, 0, 1)`. Seven sites read it,
several feeding the lerp at `0x00B27C80` — `0x00671755` lerps a drawable transform, `0x00676688`
and `0x00676739` two vector pairs each, `0x004B523C`/`0x004B6C1C`/`0x004B6F81` W3D animation, and
`0x008A037D` a counter readout. Nine more sites read `+0x38` itself to turn a per-logic-frame rate
into a per-client-frame increment. **All sixteen follow the ratio for free**, which is why this
patch re-parameterises rather than builds.

### 3.2 Why the recompute gate becomes 1, not the ratio

`+0x38` is initialised to **1** by the constructor (`0x0063A4DE`), not to 6 — the ratio only
becomes real when the recompute at `0x0063260F` fires, which stock gates on the sub-frame index
reaching 6. Keyed to the ratio that gate would work at every rate of 30 and above and silently stop
working below it. Keyed to **1** it fires once per logic frame at every rate, because sub-frame 1
is the only index that always occurs. One byte, strictly more robust than what it replaces.

### 3.3 The sub-frame predicate needs no edit

`0x0063252F`, called from eleven client sites:

```asm
0063252f  mov  eax, [0x00d9f60c] / cdq / idiv dword [0x00d9f608]   ; ratio
0063253c  push 6 / ... / cmp esi, eax
00632543  jge  0x632554                ; ratio >= 6 -> return subFrame == 1
00632546  idiv esi                     ; ratio <  6 -> return subFrame == (6 / ratio)
```

At any ratio of 6 or more it answers `subFrame == 1` — once per logic frame, at every rate this
patch allows. The `6` at `0x0063253C` is a floor for *slow* clients, not the ratio. Four of the
eleven callers were read (`0x004B51F4`, `0x004ED6AB`, `0x0083BA12`, `0x008A0368`) and all four are
the client-side latch of §3.1: `if (predicate) previous = current;` then `previous + alpha * rate`.

### 3.4 The catch-up loop needs no edit either

`0x00632A95` computes the ratio the same way and `0x00632AA3`'s `cmp ecx, 6 / jge 0x632B03` skips
the whole loop when it is 6 or more. It exists to run *extra* logic steps for a client slower than
6× the logic rate, and stays dormant at every rate this patch allows.

### 3.5 The timecode stride

Three sites pack `logicFrame * 10 + subFrame - 1` and hand it to `0x006251A3`, which forwards it to
`[0x00DC62C0]`'s vtable `+0x90`: `0x0062ECC6`, `0x00632631`, `0x00632ACF`. The stride is the room
the sub-frame index has inside one logic frame's slot, so at a ratio above 10 sub-frames 10 and 11
collide with the next logic frame's 0 and 1. The patch raises all three to `max(10, ratio)` — a
one-byte immediate each, and `max` so that a modest rate still writes the stock bytes.

## 4. The patch

| site | stock | patched | why |
|---|---|---|---|
| `0x00D9F60C` | `30` | `fps` | the client rate |
| `0x00D9F620`/`24`/`28`/`2C` | derived from 30 | derived from `fps` | animation, audio and UI timing read them |
| `0x0063264A` | `cmp eax, 6` | `cmp eax, ratio` | **the wrap** |
| `0x00632604` | `cmp ecx, 6` | `cmp ecx, 1` | recompute the ratio every logic frame (§3.2) |
| `0x0062ECC6`, `0x00632631`, `0x00632ACF` | `imul …, 10` | `imul …, max(10, ratio)` | §3.5 |
| `0x00D9F608` | `5` | `5` | **asserted, never written** |

`ratio = fps / 5`, and `fps` must be a multiple of 5 so a whole number of client frames fits in a
logic frame. The floor is **35** (ratio 7): at the stock ratio every site computes its stock bytes,
so allowing 30 would make `detect` report every unpatched binary as carrying the patch. The ceiling
is **635** (ratio 127), because the ratio and the stride are *signed* imm8s — at 128 the wrap's
constant decodes as −128 and the simulation never advances at all.

The logic-rate row is an assertion written as an edit whose "new" bytes equal its "old" ones, so a
build that does not simulate at 5 Hz fails before the client rate is raised against a denominator
this patch guessed at.

**`FramesPerSecondLimit` must match `fps`.** The patch owns the client rate; INI owns the pace, for
the reason in §2. If they disagree the game runs at the wrong speed — `verify` reports the rate the
binary was built for, and that is the number to put in `GameData`.

## 5. Proving it rather than believing it

Five of the six numbers, left behind while the others move, produce a game that is subtly the wrong
speed rather than one that crashes. So the acceptance test is a **measurement**, not an impression:

1. **The logic rate.** Run a known map for a wall-clock minute and read `[[TheGameLogic]+0x40]`
   (`sage_live` already reaches it). It must advance by **300** whatever the frame rate is. At 60
   fps with the wrap left at 6 it advances by 600 — which is the bug, and is the thing this
   measurement exists to catch.
2. **The replay corpus.** Record on the patched build and parse with `sage_replay`. Timecodes must
   still be **0.20 s** apart. 0.10 means the simulation moved.
3. **Smoothness.** Compare a panning camera and a marching horde at 30 and at 60. §3.1's sixteen
   sites are what should make the difference visible; anything that steps a visual quantity per
   client frame with a *hardcoded* increment rather than by reading `+0x38` will run at double
   speed instead. None was found among the sites examined, and no exhaustive sweep for that pattern
   was done.
4. **Determinism.** Two peers, one patched and one stock, same seed — or a stock replay played back
   on a patched build. §3.3 is the reason to expect this to hold; the seven unread `0x0063252F`
   callers (`0x00461EBD`, `0x0048E2D3`, `0x004B6BE6`, `0x0064871C`, `0x006487F3`, `0x006759BB`,
   `0x0083BA12`) are the reason to check rather than assume.

## 6. What "uncapped" would cost

The wrap counts **frames**, so the simulation rate is always the frame rate over the ratio and
there is nothing to uncap: `UseFPSLimit = No` removes the pace and the simulation goes with it. A
genuinely uncapped build needs the wrap driven by the wall clock, and that is a different patch:

- **A cave at `0x0063264A`.** Nine bytes are available (`cmp` + a near `jle`), enough for a
  `jmp rel32` into a cave that compares `timeGetTime() - lastLogicMs` against 200 and jumps to
  `0x00632653` or `0x006326EB`.
- **The alpha has to move with it.** `+0x3C = subFrame / +0x38` saturates at 1.0 once the sub-frame
  index passes the ratio, so at 120 fps objects would interpolate for the first 50 ms of every
  logic frame and freeze for the remaining 150. `0x0063256F` is a standalone 0x31-byte function
  with four callers, all inside the two functions this patch already touches, so redirecting it to
  compute `(now - lastLogicMs) / 200` is tractable.
- **`+0x38` becomes a measurement.** With a variable frame rate "client frames per logic frame" is
  no longer a constant; the nine consumers want the count the *last* logic frame actually took.
- **The timecode loses its guarantee.** An unbounded sub-frame index cannot be packed into a
  fixed stride at all. It feeds a profiler, so collisions are cosmetic — but that has to be
  established rather than assumed.

Two caves, roughly 150 bytes, new state, and a wall clock introduced into a path adjacent to
lockstep — against a patch that is currently four immediate bytes and a constant. It is worth
doing only after §5 has been run on this one.

## 7. What this does not buy

At 60 fps the alpha advances in twelfths and the simulation still takes a decision every 200 ms.
Rendering gets smoother; **responsiveness does not change at all** — a click still waits up to
200 ms to be seen. Raising the *logic* rate is the fix for that, and it is a far worse project:
every duration in every INI is counted in logic frames, so it rescales the entire game's data and
invalidates every replay. [`headless.md`](headless.md) §1 says the same, and
[`recharge-rescale.md`](recharge-rescale.md) is a worked example of how much arithmetic hangs off
that constant.

## Address table

| VA | what |
|---|---|
| `0x00639EC6` | the main loop's top; `+0x10` is `m_quitting` |
| `0x00639EE1` | `call [eax+0x28]` — `GameEngine::update`, once per iteration |
| `0x0063A196`..`0x0063A1F5` | the `Sleep(0)` pace: `1000 / (m_maxFPS * [0x00D9F498])` ms |
| `0x0066F0FD` | the folded accessor that writes `+0x0C` — **do not patch** (§2) |
| `0x00779DCF` | its caller for `TheGameEngine`, from `GlobalData+0x28` |
| `0x00644F11` | the rate setter — **no callers**; `0x00644F31` caps the ratio at 6 |
| `0x00D9F608` / `0x00D9F60C` | logic rate (**5**) and client rate (**30**), static in `.data` |
| `0x00D9F610`..`0x00D9F62C` | the eight derived floats |
| `0x00DE4324` | `TheGameEngine`; `+0x0C` maxFPS, `+0x34` sub-frame, `+0x38` ratio, `+0x3C` alpha |
| `0x0063A49C` | its constructor — `+0x0C = 0`, `+0x38 = 1` (§3.2) |
| `0x00BD84E0` | the `GameEngine` vtable (`+0x28` update, `+0x48` setFPS, `+0x98` logic step) |
| `0x006325A0` | the sub-frame advance; owns `0x00632604` and `0x0063264A` |
| `0x0063252F` | the sub-frame predicate — needs no edit (§3.3) |
| `0x0063256F` | the alpha computation |
| `0x006329B0` | vtable `+0x98` — the logic step and the dormant catch-up loop (§3.4) |
| `0x0062E4E8` | `GameLogic::update`; `0x0062E577` increments the frame counter |
| `0x0062EC4B` / `0x0062EC55` | the `n == 1` gate and the object sweep behind it |
| `0x0062ECC6` / `0x00632631` / `0x00632ACF` | the timecode stride (§3.5) |
| `0x00B27C80` | the lerp the alpha is handed to |

## 8. Why this approach does not work, and what would

**Run in game at `--fps 60` with `FramesPerSecondLimit = 60`. Three symptoms, one cause.**

- Particle **FX play at exactly twice speed**.
- Unit **animations stick** — some frozen in idle, some frozen mid-walk, attack animations
  unaffected.
- The **spell store is dead**: no power can be clicked to purchase.

### What is provably right

Read out of the live process with `sage_live`'s `ProcessMemory`, mid-match:

```
[0x00D9F608] logic rate  = 5          [0x00D9F60C] client rate = 60
TheGameEngine+0x0C maxFPS = 60        +0x38 ratio = 12
+0x34 sub-frame cycles 1..12          +0x3C alpha sweeps 0.083 .. 1.000 in twelfths
client frame advancing 62/s           logic frame advancing ~5.2/s
```

Every number the patch is responsible for is exactly what §3 and §4 intend. The wrap holds the
simulation near 5 Hz; the interpolation alpha, which is the mechanism the whole design rests on,
sweeps smoothly across twelve sub-frames instead of six. **The pacing core is correct and is not
the defect.**

(The ~4% overshoot — 5.2 Hz rather than 5.0 — is the frame limiter's `ftol` at `0x0063A1AD`
truncating `1000/60 = 16.67` to 16 ms, so the loop runs at 62.5 fps rather than 60. Stock has the
same rounding at `1000/30 → 33`, where it costs 1%. It is not this patch's doing beyond making the
truncation proportionally larger.)

### The cause

**A large amount of client-side content is authored in client frames, and the engine advances it
one unit per client frame.** Particle lifetimes and burst delays, W3D animation cursors, and APT
movie playback are all counted that way. Doubling the client frame rate therefore halves the
wall-clock duration of every one of them — which is exactly "FX at twice speed", and the same
mechanism running animations and UI movies off their intended timing.

**No constant can fix this.** §1's derived floats rescale the conversions that go *seconds → client
frames*; they do nothing for content whose duration is already a frame count in the mod's INI and
in its `.apt`/`.w3d` assets. Those numbers live outside the binary.

That is the fatal objection to the design. The client frame rate is not a free parameter here: in
this engine one loop iteration is one client frame is one draw, so raising the draw rate
necessarily raises the rate at which frame-counted client content advances.

### What would work — and what would not

**First, the mechanism that decides this, because it is easy to get backwards.**
`Drawable::getInterpolatedTransform` at `0x0067171D` is where the alpha becomes a position:

```asm
0067171d  push esi                     ; esi = the Drawable
00671720  mov  ecx, [0x00de4388]       ; TheGameClient
00671728  call [eax+0x7c]              ;   -> the CLIENT frame
0067172b  cmp  [esi+0x378], eax
00671733  lea  eax, [esi+0x1a0]        ;   not interpolating -> the current matrix
00671746  cmp  [esi+0x204], eax        ; already computed this CLIENT frame?
0067174c  je   0x671788                ;   -> return the cache
0067175a  fld  dword [0x00de4324+0x3c] ; the alpha
0067176f  call 0xb27c80                ; lerp(+0x170 previous, +0x1a0 current) -> +0x1d0
00671782  mov  [esi+0x204], eax        ; stamp it with the client frame
00671788  lea  eax, [esi+0x1d0]
```

| Drawable | field |
|---|---|
| `+0x170` | the previous logic frame's matrix |
| `+0x1A0` | the current logic frame's matrix |
| `+0x1D0` | the interpolated matrix the render path uses |
| `+0x204` | the **client frame** the interpolation was last computed on |
| `+0x378` | the frame past which this drawable interpolates at all |

**So interpolation is recomputed once per client frame and cached against the client frame.**
Two consequences, and the second is the one that matters:

1. **Raising the client rate really does buy smoothness.** More client frames means more distinct
   values of `+0x1D0` between two logic frames — the extra frames are new positions, not duplicate
   ones. The withdrawn patch was not merely drawing more often; it was genuinely interpolating
   finer, which is why the motion it produced was correct even while everything else broke.
2. **A "client content at 30, render at 60" split would buy nothing at all.** Gate the client
   update to every second iteration and `+0x204` does not change between the two draws, the cache
   at `+0x1D0` is returned unchanged, and the second draw is a duplicate frame. The three-rate
   design this section previously proposed is therefore **wrong**, and would have cost a cave and
   a week to discover that.

The split has to run the other way:

- **The client frame must advance on every drawn iteration**, so `+0x204` changes and the
  interpolation refreshes. That is the thing producing the smoothness and it cannot be slowed down.
- **Frame-counted content must be decoupled from it** — particle lifetimes and burst delays, W3D
  animation cursors, APT movie playback — so that each still advances at its authored 30 Hz while
  the client frame runs at 60.

That is per-subsystem work: every consumer that treats "one client frame" as its unit of time needs
either its own divider or a fractional step, and each is its own piece of reverse engineering. It is
the honest price of this feature on this engine, and it is a great deal more than the four
immediates this document started with.

The patch was unregistered and its module and tests deleted; this document is what remains of it,
and is deliberately kept, because the reverse engineering above is correct and the negative results
— both the fatal one in this section and the corrected design that follows it — are the expensive
part to rediscover.
