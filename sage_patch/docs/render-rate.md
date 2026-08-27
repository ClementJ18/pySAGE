# Raising the frame rate without speeding the game up

> ⚠ **§8's verdict was wrong, and §3.3/§3.4 are false on the binary the game runs.**
> The patch was withdrawn on three symptoms. Measured in a live match on 2026-08-20: one was a
> one-dword bug, one was an artifact of how the test was applied, and one is a real engine defect
> this patch does not cause — the spell store's state messages are dropped by the movie and never
> repeated (§9.6), diagnosed and proved by intervention at 60 fps, and now fixed by a second cave.
> **[§9](#9-what-a-live-match-actually-measured) is the
> measurement and the current verdict, and is the part of this document to read first** —
> it corrects §3.2, §3.3, §3.4 and §8 in specific places, and those sections are left standing only
> so the corrections have something to point at.
>
> ⚠ **The multiplayer stutter had a cause and a one-byte fix, applied 2026-08-24.** §3.2's recompute
> gate repeats §9.2's mistake, so the interpolation alpha's denominator ratchets upward all match
> on a networked client. Measured on both peers of one live match: the ratio reads **14 on the host
> and 31 on the off-host** against a wrap of 12, and the off-host's boundary frame moves **20x** a
> normal frame's motion where a correct build moves 2.0x.
> **[§9.10](#910-the-alphas-denominator-ratchets-on-a-networked-client-and-never-resets) is the
> measurement**, and it is what §9.9's flat-5.000-Hz match was missing. §9.9 remains separately
> true and is the other half of "multiplayer must work".

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

**Where that leads.** Moving the client rate and that literal together holds the simulation near
its rate at any frame rate, and genuinely buys smoothness — §9 measures a rendered drawable taking
**11 distinct interpolated positions per logic frame at 60 fps against 5 at stock**. Some client
content really is **authored in client frames** and advanced one unit per client frame, which is
the residual cost; §9 narrows that from "a great deal of client content" to one measured
subsystem.

- **Status: designed, built, run, withdrawn — and the withdrawal was mostly wrong.** §1–§4 are
  the reverse engineering and are sound apart from §3.2, whose edit is a live defect (§9.10).
  §3.3 and §3.4 are sound *about stock* and false about the binary the game runs (§0 explains why;
  §9 measures it). §8's diagnosis does not survive §9's measurements.
- **Cost, as built:** four immediate bytes, two dwords, four floats and two 0x28-byte caves — the
  first since §9.4, the second since §9.6. It is the registered `render-rate` patch; `sage-patch
  apply render-rate --fps 60` is the whole build.
- **What is actually still broken:** a 7–11% simulation slowdown (§9.5), a handful of unrescaled
  constants (§9.7), and §9.9's rendered-frame clock, which is what still stands between this and
  network play. §9.10's recompute gate — the multiplayer stutter — is fixed. The particle rate is fixed on both of its clocks - the CPU one (§9.4, measured live) and the GPU one (§9.11, built and confirmed in play). Everything
  else §8 blamed has been accounted for.
- **A 60 fps build must also raise the frame limiter** (§9.3): Edain's `GameData` sets
  `FramesPerSecondLimit = 30` where no patch reaches it, and a cold start on a 60 fps binary
  otherwise runs the whole game at half speed.

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

**No site this patch writes is in a differing run**, so it applies identically to both files —
checked again for §9.6's `0x00822890`, which is byte-identical in both. Worth asserting against
every `game.dat` in the tree rather than against one of them, for anything that edits this area
next.

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

> ⚠ **False on the binary the game runs, and the reason multiplayer stutters.** Sub-frame 1 is
> **not** "the only index that always occurs" — it is an index that never occurs, for exactly the
> reason §9.2 gives about the predicate. Gated on it, the recompute never runs, `+0x38` is left to
> `0x006323D2`'s one-way `inc`, and the interpolation alpha divides by a number that climbs all
> match on a networked client. See [§9.10](#910-the-alphas-denominator-ratchets-on-a-networked-client-and-never-resets),
> which measures it. The gate wants the ratio after all; the paragraph below is the mistake.

`+0x38` is initialised to **1** by the constructor (`0x0063A4DE`), not to 6 — the ratio only
becomes real when the recompute at `0x0063260F` fires, which stock gates on the sub-frame index
reaching 6. Keyed to the ratio that gate would work at every rate of 30 and above and silently stop
working below it. Keyed to **1** it fires once per logic frame at every rate, because sub-frame 1
is the only index that always occurs. One byte, strictly more robust than what it replaces.

### 3.3 The sub-frame predicate needs no edit

> ⚠ **False on the binary the game runs.** True of `game.dat.backup` only. The installed
> binary divides by `[0x00ECA400]` = 8 rather than by the logic rate (§0), so the answer is
> `subFrame == 2` at rate 30 and `subFrame == 1` at rate 60 — and **sub-frame 1 never occurs**
> where client code can see it. This is what froze every animation and is why the patch was
> withdrawn. See [§9.2](#92-the-stuck-animations-were-one-dword).

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

> ⚠ **False on the binary the game runs.** The installed binary replaces the `cmp ecx, 6 /
> jge` escape with `mov eax, 2 / jmp`, so the loop **always runs** one extra
> `GameLogic::update(2)` per logic frame. That makes the effective ratio 5-of-6 at rate 30 and
> 11-of-12 at 60, which is where §9.5's simulation slowdown comes from — and `0x00632ACF`, one
> of the three strides this patch edits, lives inside it.

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
| `0x00ECA400` | Edain's latch-predicate divisor — one reader, `0x00632535` (§9.2) |
| `0x006765C4` | the Drawable interpolation that actually runs (§9.1) |
| `0x00632606` | the recompute gate's imm8 - the multiplayer stutter, 1 -> ratio (§9.10) |
| `0x0063239D` | the network ratio stretch; `0x006323A6` its null-net early-out (§9.10) |
| `0x006323D2` | `inc dword [esi+0x38]` - the one-way writer of the alpha's denominator |
| `0x00632450` | its sole caller |
| `0x00DE4468` | the network singleton - null in single-player and in replays |
| `TheGameEngine+0x40` / `+0x44` | the rates-changed latch, and `0x006323D2`'s float high-water |
| `0x00DE3744` | `TheParticleSystemManager`; `+0x74` the step stamp the cave rewrites (§9.4) |
| `0x005F5123` | `ParticleSystemManager::update`; `0x005F515F` the rate gate, `0x00449D48` its one caller |
| `0x007B1102` / `0x007B1160` / `0x007B12FE` / `0x007B140B` | the GPU particle module's own clock: `ms * clientRate * 0.001` (§9.11) |
| `0x007FB2CE` / `0x007FB334` | the `GpuDraw` flipbook step, `1.0f / ((n + 4) * clientRate)` (§9.11) |
| `0x00DD1E0C` / `0x00DD1E10` | the W3D millisecond clock and its previous value; sole writer `0x00516E20` |
| `0x00DC7580` / `0x00DC7A8C` | its accumulator, and the per-client-frame step `1000 / clientRate` set at `0x00BC146C` |
| `0x0044B8B8`..`0x0044B929` | the two arms that advance it, selected by §9.7's `frame % 30` at `0x0044B8C2` |
| `0x00C31A84` | the `ParticleSystemType` name table; `GPU_PARTICLE` is **7**, template `+0xC` (§9.11) |
| `0x00C82D10` | the `GpuDraw` field table - `FramesPerRow` `+0xC`, `TotalFrames` `+0x10`, `DetailTexture` `+0x14`, `SpeedMultiplier` `+0x18` |

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

> ⚠ **Wrong function.** `0x0067171D` has exactly one caller on the running binary, behind a
> per-drawable flag, and its stamp reads `0xFFFFFFFF` on every live drawable — it never runs.
> The live path is `0x006765C4` and its fields are different; see [§9.1](#91-the-interpolation-this-document-documents-is-dead-code).
> The *reasoning* below survives; only the addresses are wrong.

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

## 9. What a live match actually measured

Run in a real skirmish on **2026-08-20**, on the installed `game.dat` — which is byte-identical to
the repo-root one (§0), so everything here is about the binary the game *runs*, not the backup the
rest of this document was read from. Two instruments, both committed:

- `examples/sage_live/render_rate_probe.py` — read-only, needs no patch.
- `examples/sage_live/set_render_rate.py` — flips a running process between rates, so one match
  can be measured at both. Its limits are in §9.3, and they matter.

The census that §5.3 promised and never ran is `sage_patch/scripts/census_client_rate.py`: 77
readers of `GameClient::getFrame()`, classified by what they do with the value. Most of §9 below
started as a census row.

### 9.1 The interpolation this document documents is dead code

`Drawable::getInterpolatedTransform` (`0x0067171D`, §8) has **one** caller on this binary, behind
`cmp byte [edi+0x43F], 0`, and its stamp `+0x204` reads `0xFFFFFFFF` on all 615 drawables in a live
match. Its matrices are identity. It never runs.

The live path is **`0x006765C4`**, structurally identical and at different offsets:

| field | meaning |
|---|---|
| `+0x3AC` / `+0x3DC` | previous / current matrix (row-major 3x4; translation at `+0x0C`, `+0x1C`, `+0x2C`) |
| `+0x208` | the interpolated output the renderer uses |
| `+0x244` | the client frame it was last computed on — **the cache stamp** |
| `+0x3A4` | last logic frame moved; two frames stale and it snaps instead of interpolating |
| `+0x40C` `+0x418` `+0x424` `+0x430` | four Vec3s fed to a spline (`0xA3ED38`) that overwrites the output's translation |

So §8's *reasoning* survives intact, including its correction that a "client content at 30, render
at 60" split would return duplicate frames. Only its addresses were wrong.

**The feature's premise is confirmed.** Recompute counts per logic frame, same drawable addresses,
both rates:

| drawable | at 60 | at 30 |
|---|---|---|
| `0x0AFE9520` | 11 | 5 |
| `0x0A3F8B20` | 11 | 5 |
| `0x0A3F8FF0` | 11 | 5 |
| `0x0A098F68` | 10 | 5 |
| `0x0A08F910` | 4 | 2 |

Every drawable being rendered exactly doubled. 5 and 11 are the full effective ratio at each rate
(§9.5), so the interpolation is recomputed once per client frame and tracks the rate precisely.
Across all 618 drawables at 60: 511 at 1, 102 at 2, one at 4, one at 10, three at 11 — the 1s and
2s are drawables not being drawn, and they are unaffected either way. Confirmed by eye: motion at
60 looks smooth, not merely faster.

### 9.2 The stuck animations were one dword

The latch that froze is `0x004B6BEF`, `[edi+0x26C] = [ebx+0x288]` — an animation's
`previous = current` — gated on the §3.3 predicate. On this binary that predicate answers
`subFrame == 6 / (clientRate / [0x00ECA400])`, or `subFrame == 1` once the quotient reaches 6:

| client rate | quotient | answers |
|---|---|---|
| 30 | `30/8` = 3 | sub-frame **2** |
| 60 | `60/8` = 7 | sub-frame **1** |

And **sub-frame 1 is never observable by client code**: the wrap sets the counter to 1 and §3.4's
always-running catch-up loop bumps it to 2 inside the same logic step, before `GameClient::update`
next runs. Measured by sampling `TheGameEngine+0x34` every client frame for 373 frames — the values
were 2..6 at rate 30 and 2..12 at rate 60, **never 1**.

So at 60 the predicate names a sub-frame that never occurs, every latch behind it stops firing, and
animations freeze. Holding the quotient at 3 keeps the answer on sub-frame 2 at any rate:
`[0x00ECA400] = 8 if fps//8 == 3 else fps//3` — 20 at 60 fps. **One dword.** Confirmed in game:
that change alone unfroze them, with nothing else altered.

`[0x00ECA400]` has exactly one reader in the whole image (`idiv` at `0x00632535`), so the edit
cannot affect anything else. All ten predicate callers were read; every one is a
`previous = current` latch, which also retires §5.4's "seven unread callers" determinism worry.

### 9.3 The double-speed animations were the measurement, not the patch

```asm
00BC146C  mov  eax, 0x3E8              ; 1000
00BC1472  idiv dword ptr [0x00D9F60C]  ; / clientRate
00BC1478  mov  [0x00DC7A8C], eax       ; ms per client frame
```

A **CRT static initialiser**. `W3DDisplay::draw` advances a render clock by
`[0x00DC7A8C] * clientFrameDelta` (`0x0044B911`), and that clock drives animation and effect
timing. Because it runs at startup, a live poke of the client rate cannot reach it:

| | live poke | file build |
|---|---|---|
| `[0x00DC7A8C]` | 33 (stale) | **16** |
| render clock | **2.06x** real time | **1.00x** |

A file-patched build computes it from 60 and is correct. **This is the general hazard of the live
toggle**: the census counted **436** CRT initialisers reading the client rate, and only the shapes
one goes looking for get found. The toggle now carries `[0x00DC7A8C]` explicitly, but treat it as
good-for-logic, not-proof-for-timing. Anything timed wants a file build and a cold start.

**And the file build has the mirror-image trap.** Edain's `GameData` sets
`FramesPerSecondLimit = 30`, inside the `.big` archives where no patch reaches it, and that number
lands in `TheGameEngine+0x0C` — the limiter the `Sleep(0)` pace targets (§2). So a cold start on a
60 fps binary paces the loop at 30 while every constant says 60, and **the whole game runs at half
speed**: measured 2026-08-20 at 30.33 client fps and **2.67 Hz logic**, against 5.67 Hz once the
limiter was raised. Nothing looks broken; it just runs slow, which is the failure mode hardest to
notice and easiest to blame on the patch.

The live toggle writes `+0x0C` itself, which is why this never surfaced in §9.1–§9.4's first
runs and surfaced immediately the first time a build was tested cold.

**So the binary is half the deliverable.** `FramesPerSecondLimit` in the mod's `GameData` has to
be set to the same number the build was made with — the patch's description says so for exactly
this reason, and §4 has said so from the start; what §9 adds is what going without actually looks
like, which is not a warning, an error or a crash but a game quietly running at half speed. Ship
the two together.

Two escape hatches, for when the `.big` is not being rebuilt. `examples/sage_live/set_limiter.py`
raises the field in a running process, which is what §9.4's measurements used. And the build
could carry it by sourcing `+0x0C` from the client rate rather than from `GlobalData+0x28` at
`0x00779DCF` — **not** by patching the folded accessor at `0x0066F0FD`, which §2 rules out.

### 9.4 The particle rate: the mechanism, and the fix

FX running fast on an otherwise-correct build is §8's objection, and it is genuine. It is also
**one site**, not the open-ended per-subsystem project §8 feared.

> ⚠ **An earlier draft of this section had the mechanism half wrong.** It read
> `ParticleSystemManager::update`'s frame gate as always-on. The gate is real, but it is
> *conditional*, and on a normal launch the condition is false — so the gate never runs and the
> rate comes from somewhere else. What follows is the corrected reading.

```asm
005F515F  mov  eax, [0x00DE4364]    ; TheGlobalData
005F5164  cmp  eax, ebx             ;   null?
005F5166  je   0x005F518F           ;     -> update, ungated
005F5168  cmp  byte [eax+0xD45], bl
005F516E  je   0x005F518F           ;     -> update, ungated
005F5170  ...                       ; else fetch the client frame
005F5183  cmp  eax, [edi+0x74]      ;   already stepped on this client frame?
005F5186  je   <return>
005F518C  mov  [edi+0x74], eax
005F518F  <the update>
```

`[TheGlobalData+0xD45]` is a **mode flag**: written by one command-line handler (`0x007BA880`, the
one that also repoints the mod path at `Mods\cinematics`), read in six other places, and copied
into the game header at `0x0091A725`. It is 0 on a normal launch, so both `je`s are taken, the
whole per-client-frame gate is jumped over, and the manager steps every system on every call.

**Which is once per client frame anyway.** `TheParticleSystemManager` is `0x00DE3744`; its
`update` (vtable `+0x28` → `0x005F5123`) has exactly **one** call site in the image, `0x00449D48`,
inside the per-view routine `0x00449CF8` that `W3DDisplay::draw` enters at `0x0044BB00` and
`0x0044BBF5`. So the step rate *is* the client rate, and doubling one doubles the other. The gate
exists for the **multi-pass** branch — `[0x00DC7568] > 0` draws a client frame more than once —
which is what the cinematics flag switches on.

**The fix.** `[manager+0x74]` is a private stamp. One read (`0x005F5183`), one write from that
compare, and zero written in the constructor (`0x005F5115`) and in `reset` (`0x005F9ED7`); across
all 173 references to `TheParticleSystemManager` in the image, nothing else touches `+0x74`. So
the tick stored there need not be the client frame — it only has to advance at the rate the
content was authored for.

The patch displaces the 17 bytes of the flag test at `0x005F515F` with a jump to a
cave that computes that tick and rejoins at the engine's own compare:

```asm
mov  ecx, [0x00DE4388]     ; TheGameClient
test ecx, ecx
je   run                   ;   nothing to ask -> update, as stock does
mov  eax, [ecx]
call [eax+0x7C]            ; GameClient::getFrame
imul eax, eax, 30          ;   * the authored rate
xor  edx, edx
div  dword [0x00D9F60C]    ;   / the live client rate
jmp  0x005F5183            ; the stock cmp / je-return / store
run:
jmp  0x005F518F
```

`clientFrame * 30 / clientRate` advances 30 times a second at any client rate, so lifetimes and
burst delays — counted in *updates*, which is why no constant could ever have fixed this — keep
their authored duration while the world renders at 60. The divisor is read from `.data` rather
than folded into the cave, so there is one source of truth for the rate rather than two that can
drift — and the arithmetic is an identity at 30 (`frame * 30 / 30`), which is what makes the cave
safe to apply to an unmodified binary. (The only writer of that global is `0x00644FB0`, inside
the rate setter the address table records as having no callers; it holds the static constant for
the life of the process.)

The window is safe to take over: `0x005F515F` is entered only by the `je` at `0x005F5149`, and no
branch anywhere in the image targets `0x005F5164`..`0x005F518E`. The displaced `getFrame` fetch at
`0x005F5170`..`0x005F5182` is left byte-identical and simply becomes unreachable — the cave does
the same three instructions itself.

Three consequences worth naming. The gate is now **unconditional**, so the multi-pass branch steps
particles once per client frame rather than once per pass — a behaviour change at 30 fps, in the
one mode the cinematics flag was added to correct. The first update after a reset is skipped,
because frame 0 matches the zeroed stamp. And a null `TheGameClient` updates rather than gating,
which is what stock does with the flag off.

**Measured in a match on 2026-08-20**, reading `[TheParticleSystemManager+0x74]` — the stamp the
cave writes — against `TheGameClient+0x10`:

| | over 4.00 s |
|---|---|
| client frames | +250 (62.5 Hz) |
| particle steps | +125 (31.2 Hz) |
| **steps per client frame** | **0.500** |

`1.000` is the defect; `0.500` at rate 60 is the cave. Confirmed by eye at the same time — a
burning siege works looked right, where the same scene ran at double speed before. Sampled with
`examples/sage_live/fx_step.py`, which reads the same two counters against each other and needs
no patch of its own to say which side of the fix a binary is on.

### 9.5 The simulation runs slow, and §4 does not account for it

| client rate | measured logic rate |
|---|---|
| 30 | 6.00 Hz |
| 60 | 5.75 Hz, 5.60 Hz, 5.33 Hz across runs |

Two causes, both outside §4's arithmetic. §3.4's always-running catch-up loop bumps the sub-frame
counter an extra time per logic frame, making the effective ratio **5-of-6** at rate 30 and
**11-of-12** at 60 — which is also why the logic rate is 6 Hz rather than the 5 this document
assumes throughout. And the frame limiter truncates `1000/60` to 16 ms (`ftol` at `0x0063A1AD`),
costing a further 4%.

A 7-11% speed change shifts replay timing and is a real defect. Fixing it means making the wrap
account for the catch-up loop's extra increment, which is a different edit from §4's.

### 9.6 The dead spell store: the engine caches an intention it never confirms

§8's third symptom is **real, is a genuine defect, and is not this patch's** — it reproduces on a
stock binary using Edain's debug `x2 speed` button, which moves no rate constant at all. It was
recorded here as "a pre-existing engine bug triggered by a faster client, mechanism unknown".
The mechanism was found on 2026-08-20 and proved by intervention in a live 60 fps match.

**The two halves, and the gap between them.**

- **The engine sends each button's state once.** `AptSpellStore::update` (`0x00822E43`) computes a
  state per button and calls `SetSpellButtonState` (`0x008229B5`) **only when it differs from its
  own cache** at `this+0x2AC` (`0x00823237`), then writes that cache unconditionally at
  `0x00823246`. The cache records what the engine *intended to send*, not what arrived.
- **The movie is entitled to refuse, and never says so.** `SetSpellButtonState(index, state)` in
  `SpellStore.apt` — identical in `apt/` and `apt_widescreen/` — is:

  ```js
  var btn = SpellStore.Buttons["Spell" + index];
  if (btn == undefined) return;          // the clip does not exist yet
  btn.targetState = state;
  if (btn.open) { btn.gotoAndPlay(state); }   // the clip is not ready yet
  ```

  `open` is `false` at frame 0 (`_unused`) and becomes `true` only at frame 19, the last frame of
  `_fade_in`; frame 19 also carries a `gotoAndPlay(targetState)` catch-up for a state that arrived
  early. Both refusal paths are silent.

**So one refused message is permanent**, because the engine's cache now says there is nothing left
to say. The button clip falls through from `_fade_in` into `_disabled` at frame 20 and stops at 35,
which is what a spellbook with nothing lit actually is.

**Why the client rate decides it.** The losing side of the race is measured in *movie* frames — the
clip's construction and its ten-frame intro both advance one frame per client frame — while the
engine's first `update` pass is not. Doubling the client rate moves the two relative to each other,
which is precisely §8's "APT movie playback is authored in client frames" arriving as a dropped
one-shot message rather than as something playing at double speed.

**Proved by intervention.** In a live match at rate 60 with the book showing nothing purchasable,
writing a sentinel over the twenty cache dwords at `this+0x2AC` forced `update` to re-send every
state. The book lit immediately; the previously dead Rebuild button then took a click, staged
`SCIENCE_RebuildMen` for 1 point, and moved to `_already_purchased` while its neighbour dropped to
`_disabled` as the basket spent the point. Nothing else was touched.

**Nothing in the purchase logic was ever wrong.** Across both the broken and repaired states the
engine held the correct answer: `0x005FED5B` passed for the two affordable powers, prerequisites
and points were right, `AptSpellStore::InputEnabled` (`0x00822974`) read `"1"`, and the closing
latch at `this+0x2A2` was clear. The failure is entirely in delivery.

**The fix, and it ships in this patch.** Two hooks, because one is not enough.

- `AptSpellStore::OnInitialized` (`0x0082285B`) already resets `+0x2A2`, `+0x348`, `+0x34C`,
  `+0x350` and `+0x354` and simply omits the button array. The patch takes over the seven-byte
  tail of that handler (`mov byte [ecx+0x2A0], 1`, with `ret 4` behind it) and jumps to a cave that
  carries the displaced store, stamps all twenty slots at `this+0x2AC` with `-1`, records
  `GetTickCount`, and rejoins the handler's own `ret`.
- `update`'s button loop head (`0x008231CA`, ten bytes; the one branch that reaches it targets its
  first byte, so it lands on the hook too) jumps to a second routine that compares the tick against
  that stamp and, until **1000 ms** have passed, takes the loop's own "all twenty done" exit. Only
  the button states wait; the layout, help text and description still run every pass.

**Invalidating the cache on its own is a no-op, and was tried first.** `OnInitialized` is what sets
`+0x2A0`, the flag `update` checks before it does anything — so the first update after it is the
same pass the original send was already happening on, and stamping the cache there moves nothing.
Built, installed and measured at 60: no change. The deferral is the half that does the work, and
the invalidation is what makes the deferred pass send all twenty rather than only those whose
computed state happens to differ from constructor garbage.

**Why a clock and not a count of passes.** `update` runs off whatever pump is turning, and while
the panel is up that is the modal `Sleep(5)` spin rather than the client frame — so a pass count
would mean a different wall-clock wait at every rate, which is the exact class of bug this document
is about. The subtract and the compare are unsigned, which is what makes them right across
`GetTickCount`'s 49-day wrap.

**The visible cost is a blank spellbook for the first second after it opens.** One second is a
guess, not a measurement: what is actually needed is however long the movie takes to build its
clips and run each one's ten-frame `_fade_in`, and nobody has measured that. If the book comes up
correct it is long enough; if it comes up blank and stays blank, the number is the first thing to
raise, and `DEFER_MS` is where it lives.

**This fix is not rate-specific**, and folding it into `render-rate` is a deliberate choice rather
than a technical one: the same race can tip on a stock 30 fps build, where nothing installs this.
Reaching those installs means giving it a patch of its own.

**Three behaviours that were misread as the bug, and are not.** All three are real, all three were
measured, and none of them is rate-dependent:

- **Opening the panel stops the game.** `GameEngine::update` (`0x0044181F`) tail-calls the normal
  path only while the modal pointer `[0x00DC3C64]` is null; once set it spins on `Sleep(5)` + pump
  at `0x0044184C` and never reaches the client or logic update. Both frame counters stand still
  while the window stays responsive, and the APT keeps repainting off the modal pump. It leaves
  that spin for `TheGameLogic+0x110` of 1 or 5 only, so a skirmish (mode 2) stays modal until the
  panel closes. **This is what "the game freezes when the spellbook opens" is.** Whether the store
  is *meant* to take the modal path in a skirmish has not been established.
- **A click buys nothing by itself.** `OnBttnSpell` (`0x008235A5`) ends in `0x0082355F`, which
  stages the science in a basket at `this+0x290`, adds its cost to `this+0x29C`, and stages the
  `CommandButton` at `this+0x27C`. `OnBttnReset` (`0x00823484`) clears exactly those.
- **The commit is the destructor.** Neither `OnBttnClose` (`0x0082289A`) nor `OnClosed`
  (`0x00822A80`) purchases anything. The teardown at `0x008233FC`–`0x0082342E` replays each staged
  button through `[0x00DE7744]`, and the purchase resolves on the first logic frame after the modal
  spin ends. Confirmed at rate 30: open, click, close, and `SCIENCE_RebuildMen` went from unheld to
  held on the local player.

`examples/sage_live/spell_store_probe.py` reads all of the above out of a running match, and
distinguishes a modal reading from a stale one — a probe that cannot tell those apart reports the
last live frame as though it were a diagnosis.

### 9.7 The unrescaled constants the census found

- **`0x00BDFC6C` = `1/30`** — outside the §1 block, four readers (`0x004B6B63`, `0x005033E5`,
  `0x00765E07`, `0x0080B088`), none rescaled by §4. `0x004B6B63` is an animation blend weight that
  advances per client frame and clamps at 1.0, so transitions complete in half the intended
  wall-clock time.
- **`0x00BE560C` = `33.333`** — one reader (`0x00500186`), also missed.
- **`0x0083AD72`** — a click detector's window, `clientFrame - mouseDownFrame < 5`: 167 ms at 30 fps
  and 83 ms at 60. A real defect; it is *not* the spell-store symptom (§9.6), and it has not been
  observed to cause anything. Rescale it as `5 * fps / 30`.
- Nine moduli keyed to the client frame, including a **second copy of the ratio** (`frame % 6` at
  `0x00450119`) and a once-per-second gate (`frame % 30` at `0x0044B8C2`). Only `0x006A2451`
  derives its cadence correctly. Full table from the census script.

### 9.9 The simulation rate is a function of each machine's frame rate — and it does not end multiplayer

**Superseded in its conclusion, kept for its arithmetic.** The identity below is real and still
governs the design. What this section originally concluded from it — that mixed hardware cannot
play together — was tested directly on 2026-08-26 and did not hold; see
[the mixed-rate match](#mixed-frame-rates-played-clean--2026-08-26) at the end. The 2026-08-23
failure that motivated it is accounted for by §9.10, which was found and fixed afterwards. Read
the rest of this section as the mechanism, not as the ceiling.

Observed on 2026-08-23 in a real online match between two Edain installs carrying the 60 fps build,
after a control match on the 30 fps build (the same patch set minus `render-rate`) ran clean:

| machine | rendered | reported |
|---|---|---|
| host | 60 fps | "everything badly stutters" |
| off-host (weaker) | above 30, not 60 — in single player too | smooth, but the match feels 30 |

Then a desync, with animation glitches before it.

**§9.5 measured this and read it as a constant.** Its three runs at client rate 60 came back
**5.75, 5.60 and 5.33 Hz** — and attributed the gap to the catch-up loop plus `ftol` truncation,
which are both fixed costs. Fixed costs do not vary by 8% across three runs on one machine. What
varies is the frame rate that machine was actually achieving.

**The wrap counts client frames, not milliseconds** ([§3.2](#3-where-a-loop-iteration-becomes-a-logic-frame)),
and the limiter is a *ceiling* the loop reaches only if the machine can render that fast
([§2](#2-the-main-loop)). So the logic rate is not `clientRate / ratio`. It is:

```
logic rate = (frames this machine actually renders per second) / ratio
```

At stock that identity is invisible, because the ceiling is 30 and every machine that runs this
game at all renders 30. Raise the ceiling to 60 and it becomes the dominant term: a client
sustaining 45 fps simulates at `45/11 ≈ 4.1 Hz` while a client sustaining 60 simulates at
`≈ 5.5 Hz`. Back-solving §9.5's own numbers through the 11-of-12 effective ratio gives 63, 62 and
59 rendered fps — a machine hovering around its 60 cap, which is exactly what that test box was.

**Consequences, in order of how bad they are.**

- **Every peer simulates at a different speed, set by its graphics performance.** Lockstep holds
  them together by stalling whoever is ahead, which is what the host reported: it renders 60,
  wants 5.5 Hz, and spends the match waiting for a peer that can only supply 4.1. The stutter is
  not a rendering problem, it is the network layer throttling a client that is running too fast.
- **The sub-frame counter now advances a machine-dependent number of times per logic frame.**
  §3.4's catch-up loop runs to make up the difference, so how many sub-frames elapse inside one
  logic frame depends on how many frames got dropped. Any simulation value derived from that
  counter is then not the same on two peers — which is a desync rather than a lag, and §9.7's
  unrescaled client-frame constants are where to look for one. **Not established**: no specific
  value has been traced from the sub-frame counter into logic state on this build. The
  rate divergence is measured; this is the mechanism most likely to convert it into a mismatch.
- **It cannot be tuned away.** There is no `FramesPerSecondLimit` that fixes it, because the
  problem is not the number — it is that the logic clock is denominated in rendered frames. Two
  machines with different GPUs disagree by construction.

**That was read, at the time, as putting the ceiling at single-player and replays.** The
measurement below and the mixed-rate match at the end of this section both say otherwise: the
divergence is real arithmetic, but it is bounded and the game absorbs it. The wall-clock wrap
[§6](#6-what-uncapped-would-cost) scopes — logic frames ending on elapsed milliseconds rather than
on a count of draws — would remove the term entirely and is still the right shape for this
eventually. It is no longer a prerequisite for playing a match.

#### What a machine that *does* hold 60 measures — and what it does not explain

Measured 2026-08-24 with `sage-live desync-watch` on the 60 fps build, one client, sampled every
logic frame for an entire match:

| window (frames) | logic rate | objects | intervals > 400 ms |
|---|---|---|---|
| 1..556 | 5.003 Hz | 463 | 4 |
| 557..1112 | 4.999 Hz | 463 | 0 |
| 1113..1669 | 5.000 Hz | 450 | 0 |
| … six more windows … | 4.999–5.001 Hz | 441 | 0 |
| 5008..5564 | 4.999 Hz | 441 | 0 |

**18.5 minutes, 5.000 Hz overall, flat, with no stalls after the opening.** So the mechanism above
is conditional and its condition matters: a client that sustains its target rate paces *exactly*
right, for a long match, at a realistic object count. The four early stalls are the map settling.

This is counter-evidence to the strength of the claim, not to the claim. `logic rate = achieved
fps / ratio` still follows from the wrap counting draws, and a client that cannot hold 60 must
still run slow. But **the machine this was measured on holds 60, and nothing degraded** — so
§9.9's mechanism is not, on its own, an explanation for a stuttering or desyncing match on
hardware that keeps up. Do not reach for it before checking that the peer in question is actually
dropping frames.

**And it did not reproduce the desync.** That match ran 18.5 minutes with `TheGameLogic+0x1BC`
clear throughout, and ended in a **client crash** rather than a mismatch — one of five that
evening, two of which wrote no minidump at all. Whatever ends these sessions, this measurement
does not show it being the pacing.

#### Mixed frame rates played clean — 2026-08-26

The test this section's conclusion asked for, and the one §9.8 item 1 said to run once §9.10 was
in: online play on the 60 fps build **between peers that were not sustaining the same frame
rate** — the exact condition the identity above predicts should diverge. It played clean. No
desync, and none of the 2026-08-23 stutter.

That is the discriminating case. Two peers both holding 60 would not have exercised the mechanism
at all; peers at different achieved rates do, and the divergence did not surface as anything a
player or the lockstep layer objected to.

**What this settles, and what it does not.** It settles the conclusion: **the rendered-frame clock
is not a barrier to network play**, and §9.10's recompute gate was indeed "the whole of what was
reported" on 2026-08-23, as §9.8 item 1 guessed it might be. It does not overturn the arithmetic —
`logic rate = achieved fps / ratio` still follows from the wrap counting draws, and a peer that
drops frames still simulates slower than one that does not. What is now known is that lockstep
absorbs that difference the way it absorbs ordinary network jitter, rather than compounding it.

**Evidentiary status: field observation, not instrumented.** Per-peer achieved frame rates were
not recorded, and `desync-watch` was not run on both sides. Two things would upgrade it — logging
`TheGameLogic+0x1BC` on both peers across a match, and sampling each peer's achieved rate to put
numbers on how far apart they actually were. Neither is needed to retire the "single-player only"
framing; both would be needed before anyone quotes a bound on how far apart peers can drift.

### 9.10 The alpha's denominator ratchets on a networked client, and never resets

**This is the mechanism §9.9's last subsection went looking for and did not find.** That match held
a flat 5.000 Hz for 18.5 minutes and still played badly, which rules out the logic rate as the
cause. The logic rate was never the problem. The **interpolation alpha's denominator** was.

Reported 2026-08-24 from a multiplayer test on the 60 fps build, and the symptom split is the
whole clue:

| what | off-host | host |
|---|---|---|
| client frame rate | 60, confirmed in `sage_patch` and by eye | 60 |
| `FramesPerSecondLimit` in the `.big` | 60, confirmed in FinalBIG | 60 |
| idle animations | smooth | smooth |
| **movement animations** | **stutter** | fine |
| **attack animations** | **render wrong** | fine |

Idle animations and movement rendering ride different clocks, which is why only one of them broke.
Idle is advanced by the render clock — `[0x00DC7A8C]` ms-per-client-frame,
[§9.3](#93-the-double-speed-animations-were-the-measurement-not-the-patch) — which is client-side,
correct on a file build, and cannot see the network. Movement and attack rendering go through the
interpolation alpha, and `0x0063256F` computes that as

```asm
0063256f  cvtsi2ss xmm1, [ecx+0x38]    ; the ratio
00632574  cvtsi2ss xmm0, [ecx+0x34]    ;   sub-frame
00632579  divss    xmm0, xmm1          ;     subFrame / ratio
0063257d  ...                          ;       clamped to [0, 1] -> +0x3C
```

So `+0x38` is not a reporting field. It is the divisor that scales every interpolated transform
(`0x006765C4`) and all three W3D animation lerps (`0x004B523C`, `0x004B6C1C`, `0x004B6F81`).
"Idle fine, movement and attack broken" says the alpha is wrong, which says `+0x38` is wrong.

**Two sites write it. On this build one is dead and the other only runs off-host.**

- **`0x0063260F`, the recompute**, sets `+0x38 = clientRate / logicRate`. It needs the
  rates-changed latch at `+0x40` **and** the sub-frame index named by the imm8 at `0x00632606` —
  the byte [§3.2](#32-why-the-recompute-gate-becomes-1-not-the-ratio) moved from 6 to **1**.
  §3.2's argument for 1 was "sub-frame 1 is the only index that always occurs", and
  [§9.2](#92-the-stuck-animations-were-one-dword) **already disproved exactly that premise**: the
  hardcoded catch-up at `0x00632A9B` runs `inc dword [ebp+0x34]` (`0x00632AC0`) inside the same
  logic step, so the counter is 2 before any other code sees it — measured over 373 frames. §9.2
  repaired the *predicate* through `[0x00ECA400]` and left the identical false premise standing
  here. **The recompute has never run on a 60 fps build.**

- **`0x006323D2`, `inc dword [esi+0x38]`**, inside `0x0063239D` (sole caller `0x00632450`). It
  grows the ratio when the sub-frame has outrun it and the peer-lag readout at net vtable `+0x58`
  is low, and stamps a float high-water mark beside it at `+0x44`. It returns early at
  `0x006323A6` — `mov ecx, [0x00DE4468] / test ecx, ecx / je` — so **it cannot run without a
  network object**: never in single-player, never in a replay. Only on a networked peer.

One writer is disabled and the other only counts up. `+0x38` is a ratchet.

**That is why every measurement in §9 missed it.** §9.1 through §9.7 were taken in single-player,
where `0x0063239D` early-outs and `+0x38` sits where it was. And §9.1's headline — recomputes
doubling from 5 to 11 — counts `0x006765C4`'s cache stamp, which advances once per client frame no
matter what the alpha evaluates to. Eleven recomputes with a wrong alpha and eleven with a right
one are the same number.

**Measured 2026-08-24**, live, in a networked match on the 60 fps build, with the `measure_network`
phase of `examples/sage_live/render_rate_probe.py`. This first capture turned out to be the *host* -
the milder half; the off-host reading is in the two-machine table below and is four times worse:

```
rates
  client [0x00D9F60C] = 60      TheGameEngine+0x0C maxFPS = 60      +0x38 ratio = 14
pace
  client 55.0 fps over 3.0s
  logic  5.0 Hz    observed ratio 11.0
  sub-frames seen: [2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]
  alpha 0.1429 .. 0.8571 in 11 distinct values
  alpha pinned at 1.0 on 0% of client frames
network pacing
  [0x00DE4468] network object : 0x149CCA50
  [0x00D9F498] slowdown scalar: 1.0
  +0x38 ratio = 14    wrap at 0x0063264A = 12
  recompute gate fires on sub-frame 1    +0x40 latch = 1
  +0x44 sub-frame high-water = 14.0
```

Read it in order.

- **`+0x38` is 14. The wrap is 12.** The logic frame spans sub-frames 2..12; the alpha divides by
  14. The ratio has been inflated two past the wrap by `0x006323D2`, and `+0x44`'s high-water mark
  reads 14.0 — the same number, written by the same site, which is what identifies the writer.
- **The alpha sweeps 0.1429 to 0.8571 and reaches neither end.** `2/14` to `12/14`. A drawable
  starts each logic frame already 14% into the segment, stops 14% short of the end, and then the
  matrices roll over. The discontinuity is `(1 − 0.857) + 0.143` = **29% of a step, skipped five
  times a second.** That is the stutter, as a number.
- **It is not the "no interpolation" failure it looks like from the symptom.** Alpha is pinned at
  1.0 on 0% of frames and takes 11 distinct values — the interpolation is running, at full
  client-rate resolution. It is running against the wrong denominator, so motion is smooth for 71%
  of each step and then jumps. Truncated interpolation, not absent interpolation: the same thing
  to look at, the opposite sign to reason about.
- **The latch at `+0x40` reads 1.** The recompute is *armed*, and has been all match. The only
  thing holding it off is the sub-frame index in the gate. Correct that byte and `+0x38` returns to
  `60 / 5` = 12 on the next logic frame.

The ratchet is monotonic — nothing anywhere decrements `+0x38` — so the longer the match runs the
further the denominator drifts and the worse the skip gets. A reading of 14 is a snapshot of a
number that only goes up, and the off-host was at **31** in the same match. **This is a defect that grows with match length, which is what
distinguishes it from anything §9 measured in a three-second window.**

**The host is fine for the same reason it is a ratchet.** Both peers hold a network object, so
`0x0063239D` is reachable on both — but its `inc` is gated on the peer-lag readout, and the peer
that spends the match waiting on frames is the one that trips it. Single-player and replays never
trip it at all, which is why
[§9.1](#91-the-interpolation-this-document-documents-is-dead-code)'s "confirmed by eye: motion at
60 looks smooth" was honestly reported and locally true.

**The fix is the imm8 at `0x00632606`: 1 → the ratio. Applied 2026-08-24**, in `render_rate.py`'s
`_edits`, one changed expression — the gate now takes `ratio` alongside the wrap instead of a
literal 1. `TestTheGateAndTheWrapAgree` asserts the two hold the same byte at 35, 60, 120, 300 and
635 fps, that the gate equals the ratio, and that it is never 1 again. **Built and unit-tested; not
yet played.** The reading to take after a match is the same one above: `+0x38` should sit at 12 and
stay there, and `boundary_spike` should read 2.0x on both peers. That restores the stock relationship —
stock's gate of 6 equals stock's wrap of 6 — so the recompute fires on the sub-frame that ends the
logic frame and re-derives `+0x38` every logic frame, clearing whatever the network inflated. §3.2
rejected keying the gate to the ratio because it "would silently stop working below rate 30";
`render_rate.py` already floors the patch at 35 fps, so that objection does not reach any rate this
patch permits. **§3.2's reasoning should be struck rather than amended**: it was wrong on this
binary for the same reason §9.2 was, and the two are the same mistake made twice.

**What this does not fix.** [§9.9](#99-the-simulation-rate-is-a-function-of-each-machines-frame-rate-and-that-ends-multiplayer)
is untouched. The logic clock is still counted in rendered frames, so a peer that cannot hold its
target rate still simulates slow — the run above shows it, 55 rendered fps against a 60 cap. §9.10
is the *stutter*; §9.9 is the *divergence*, and it needs the wall-clock wrap
[§6](#6-what-uncapped-would-cost) scopes. Fixing the gate makes a client render its motion
correctly at whatever rate it is simulating. It does not make two peers simulate at the same rate.

#### Both peers, same match, same minute

Taken 2026-08-24 with `render_rate_probe.exe --seconds 5` on each machine of a live two-machine
match. This is the reading that turns the section above from a diagnosis into a measurement.

| | host | off-host |
|---|---|---|
| client rate constant | 60 | 60 |
| `TheGameEngine+0x0C` maxFPS | 60 | 60 |
| rendered | 55.0 fps | 52.6 fps |
| logic | **5.0 Hz** | **4.8 Hz** |
| wrap at `0x0063264A` | 12 | 12 |
| **`+0x38` ratio** | **14** | **31** |
| `+0x44` high-water | 14.0 | 2.0 |
| recompute gate | sub-frame 1 | sub-frame 1 |
| `+0x40` latch | 1 (armed, never fired) | 1 (armed, never fired) |
| `[0x00D9F498]` slowdown | 1.0 | 1.0 |
| sub-frames seen | 2..12 | 1..12 |
| alpha sweep | 0.143 .. 0.857 | **0.032 .. 0.387** |
| skipped per logic frame | 28.6% | **64.5%** |
| **boundary spike** | **4.0x** | **20.0x** |

**The ratio is 31 on the off-host.** Against a wrap of 12, the alpha divides by 31 while the logic
frame spans 12 sub-frames, so a drawable covers 39% of each step and then jumps the remaining 65%
in a single client frame. The host's 14 is the same defect at a quarter of the severity, which is
why it was reported as fine rather than as broken — it *is* wrong, just not visibly so.

**Read the last row, not the one above it.** The raw gap overstates things, because a healthy build
has a gap too: the catch-up loop eats sub-frame 1, so the alpha starts at `2/ratio` and the boundary
frame always moves double. Measured against the frames either side of it:

| build | ratio | normal step | boundary jump | spike |
|---|---|---|---|---|
| stock 30 | 6 | 0.167 | 0.333 | **2.0x** |
| 60 with the gate fixed | 12 | 0.083 | 0.167 | **2.0x** |
| host, as shipped | 14 | 0.071 | 0.286 | 4.0x |
| off-host, as shipped | 31 | 0.032 | 0.645 | **20.0x** |

A correct build spikes exactly 2.0x at *any* rate — that is what "the ratio and the wrap agree"
means, and it is why stock's 33% gap has never been visible to anyone. The off-host is spiking
**twenty times** a normal frame's motion, 4.8 times a second. That is not a subtle artifact.

**`+0x44` corroborates the mechanism rather than contradicting it.** The host's high-water reads
14.0, exactly its ratio, which is `0x006323D2`'s signature: that path raises `+0x44` to match every
time it bumps `+0x38`. The off-host reads 2.0 against a ratio of 31, which looks wrong until the
other branch of `0x0063239D` is read — the `subFrame <= ratio` path at `0x006323E9` *lowers* `+0x44`
toward the current sub-frame. Once the ratio has ratcheted past the highest sub-frame the wrap ever
produces, that branch is the only one that can run, and it drags the high-water back down. So the
off-host is the same story further along: it climbed to 31, outran the sub-frame range permanently,
and has been in the second branch ever since. Nothing needs a third writer to explain it.

**§9.9 is in this capture too, and it is the smaller of the two.** The off-host renders 52.6 against
a 60 cap and simulates at 4.8 Hz against the host's 5.0 — a 4% divergence, real, and exactly what
§9.9 describes. It is not what anyone was looking at. A 4% rate difference is a lockstep stall; a
20x velocity spike five times a second is the thing on screen.

**How to take this reading yourself.** `dist/render_rate_probe.exe`, built from
`examples/sage_live/render-rate-probe.spec`, is the probe frozen into a standalone binary so it can
be run on a machine with the game but no Python and no checkout — which is what the off-host box in
a two-machine test usually is. Run it elevated on **both** peers during the same match and diff the
JSON:

```
render_rate_probe.exe --seconds 5 --json host.json
render_rate_probe.exe --seconds 5 --json offhost.json
```

`ratio_moved`, `ratio_matches_wrap` and `snap_per_logic_frame` are the three fields that carry this
section's finding.

### 9.11 GPU particles keep a second clock, and §9.4's cave does not reach it

**Read statically on 2026-08-26 and confirmed in a live paused match on 2026-08-27** — the
measurement is at the end of this section. The sites below are byte-identical in the repo's
`game.dat` and in `C:\RotWK\game.dat`, so the reading applies to both.

§9.4 fixed the particle rate by gating `ParticleSystemManager::update`, which walks the system list
at `TheParticleSystemManager+0x4C` and calls each system's vtable `+0x10`. **A `Type = GPU_PARTICLE`
system does not get its age from that walk.** The GPU particle storage module derives its own
elapsed time from the W3D millisecond clock, and converts it to frames with the *live* client rate:

```asm
007b12f9  mov  eax, [0x00DD1E0C]     ; W3D accumulated milliseconds
007b12fe  imul eax, [0x00D9F60C]     ;   * the client rate      <-- 30 authored, 60 patched
007b1305  test eax, eax
007b130e  fild dword [ebp-8]
007b1319  fmul dword [0x00BD88A0]    ;   * 0.001  ->  elapsed CLIENT FRAMES
```

The same five-instruction idiom appears **four times**. Three are provably the module's own —
`0x007B1102` and `0x007B1160` sit in its vtable slot 0 (`0x007B1098`) and `0x007B12FE` in slot
`+0x28` (`0x007B12F4`, the pass that retires expired entries); the fourth, `0x007B140B`, is in the
adjacent function at `0x007B13xx`..`0x007B17CB`, which reads `TheGameClient` and was not tied back
to the vtable. The multiply is the whole defect. `ms * clientRate / 1000`
recovers the client frame count correctly at *any* rate, which is exactly what is wrong with it:
the content is authored in **30 Hz** particle updates, so at rate 60 a GPU particle is handed twice
the age per wall-clock second.

**Why that reads as "too large" rather than "too fast".** `BarrageExplosion` is
`Size = 15 30`, `SizeRate = 1 1`, `SizeRateDamping = 1 1`, `Lifetime = 30 30` — size is
`Size0 + SizeRate * age`, so doubling the age doubles the growth term. At the moment the eye
catches it the particle is roughly twice the size it should be, and it should *also* be finishing
its 30-frame life in half a second rather than a whole one. That prediction was checked and holds: the
live particles die 30 client frames after birth, which is 0.50 s at rate 60.

**The W3D clock itself is rate-derived and truncating.** `0x00DD1E0C` is written only by the
two-line setter at `0x00516E20` (which also keeps the previous value at `0x00DD1E10`), from an
accumulator `0x00DC7580` advanced once per client frame at `0x0044B8D8`/`0x0044B911` by
`0x00DC7A8C` ms. That step is set at `0x00BC146C`:

```asm
00bc146c  mov  eax, 1000
00bc1472  idiv dword [0x00D9F60C]    ; 1000 / clientRate, truncated
00bc1478  mov  [0x00DC7A8C], eax     ; 33 at rate 30, 16 at rate 60
```

so the W3D clock runs 1% slow at 30 and **4% slow at 60** — the same `ftol`-class truncation §9.5
found in the frame limiter, on a different clock. It does not cause the size defect (the multiply
cancels it back out) but it is the reason nothing here is exactly 2.000.

**`0x0044B8C2`'s `frame % 30` is in this same routine**, and §9.7 already listed it. It selects
between two ways of advancing `0x00DC7580`; at rate 60 the "once per second" arm fires twice a
second.

**Two more sites take the same multiply, in the sprite-sheet path** — `0x007FB2CE` and
`0x007FB334`, both `1.0f / ((n + 4) * clientRate)` stored to `[this+0x64]` and `[this+0x6C]`. That
is the `GpuDraw` block's own business (`FramesPerRow` `+0xC`, `TotalFrames` `+0x10`,
`DetailTexture` `+0x14`, `SpeedMultiplier` `+0x18`), and it is a *separate* symptom from size —
expect the flipbook to run at the wrong speed, not to change the particle's dimensions.

**The fix, built and confirmed in play on 2026-08-27.** `imul eax, [0x00D9F60C]` (seven bytes)
becomes `imul eax, eax, 30` (three bytes plus four `nop`) at each of the four GPU-particle sites —
a byte edit rather than a cave, an identity at rate 30, and the one edit in this patch that is
deliberately *not* a function of `fps`, because the number it writes is what the content was
authored against. It ships in `render-rate`; `gpu_clock_bytes` is the definition and
`TestTheGpuParticleClocks` the coverage.

**It does not make the clock exact, and cannot.** The W3D millisecond clock it reads is itself
rate-derived and truncating, so the tick lands on 29.7 Hz at rate 30 and 28.8 Hz at rate 60
against the authored 30. Removing that residual means changing how the W3D clock is represented,
which every other consumer of that clock would feel — a different patch, and not obviously one
worth having.

**The two `0x007FB2xx` sites were left alone and no symptom followed.** They take the same
multiply in the flipbook path, so the prediction was a sprite sheet running at the wrong speed;
after the four-site fix the effects were reported correct with those two untouched. That is the
absence of a reported symptom rather than a measurement — nobody has put a number on what the
flipbook does at 60 — so it stays an open thread rather than a closed one.

**One correction that falls out of this and belongs elsewhere.** The engine's
`ParticleSystemType` name table is at `0x00C31A84`, and the indices are
`NONE=0, PARTICLE=1, DRAWABLE=2, STREAK=3, VOLUME_PARTICLE=4, SMUDGE=5, TERRAIN_PARTICLE=6,
GPU_PARTICLE=7, GPU_TERRAINFIRE=8` — the default is `PARTICLE`, which is why `0x005FACCB` skips
writing `Type` when the field at template `+0xC` reads 1. `sage_ini`'s `ParticleSystemType` was
surveyed from the corpus rather than from the binary and numbers its members differently.

#### Measured in a paused match on 2026-08-27

Confirmed live, in a 60 fps build with `BarrageExplosion` on screen and the game paused. Every
number below is an absolute counter, which is why a paused game reads them as well as a running
one — and better, because nothing moves between reads.

| | |
|---|---|
| client rate `0x00D9F60C` | **60** |
| ms per client frame `0x00DC7A8C` | **16** — `1000/60` truncated, the 4% of §9.11 |
| W3D millis `0x00DD1E0C` | 73,648 (= 4,603 × 16 exactly) |
| client frame | 4,603 |
| §9.4 stamp `+0x74` | **2,301** = `4603 * 30 / 60` — **the §9.4 cave is working** |
| GPU clock `ms * rate * 0.001` | **4,418.88** |
| **GPU ticks per §9.4 tick** | **1.920** |
| **GPU ticks per client frame** | **0.960** |

`1.920` is `2.000 × 0.96`, which is the prediction and the truncation, to three figures. **The two
particle clocks in one process disagree by a factor of two**: CPU-side systems step at the authored
30 while GPU particles age at the client rate.

**The live object layout**, recovered from the same read. `FXParticleSystem` (vtable `0x00BF7B48`)
carries its parsed `System` block inline — `+0xC` `Type`, `+0x10` `ParticleName`, `+0x18`/`+0x1C`
`Lifetime`, `+0x2C`/`+0x30` `Size` — and embeds the GPU storage module at **`+0x1E0`** (vtable
`0x00C33B48`) **when it has one**: only two of the six live `GPU_PARTICLE` systems in this sample
carried a store, and the other four held garbage at that offset, so anything reading it must guard
on the vtable rather than on the type. The module's `+0x24`/`+0x28` are a vector of 12-byte entries
`{float deadline, id, object *}` with the count at `+0x10`. Each particle (vtable `0x00BF7858`)
holds `+0x10`..`+0x18` emission velocity, `+0x1C`..`+0x24` position, `+0x28`..`+0x30` the emitter
origin, `+0x34` and `+0x54` its lifetime, and **`+0x58` its birth client frame**.

Six live particles of that one system, against `Lifetime = 30 30`, `Size = 15 30`, `SizeRate = 1 1`:

| # | birth frame | age | should be | life used | size now | size it should be |
|---|---|---|---|---|---|---|
| 0–2 | 4,596 | 7 | 3.5 | 23.3% | 22.0–37.0 | 18.5–33.5 |
| 3–4 | 4,598 | 5 | 2.5 | 16.7% | 20.0–35.0 | 17.5–32.5 |
| 5 | 4,600 | 3 | 1.5 | 10.0% | 18.0–33.0 | 16.5–31.5 |

**The mismatch is visible inside that table, not only against it.** The three bursts are two client
frames apart — one burst per §9.4 tick, so emission is correctly on the 30 Hz clock — while each
particle's age is counted in client frames. `deadline - born` is exactly `30.00` GPU ticks and
`born / 0.96` is exactly the birth client frame, so the deadline is the authored lifetime
denominated in client frames: **the particle dies 30 client frames after birth, 0.50 s at rate 60
where the author wrote 1.00 s.**

**And that is the "too large".** The peak size is unchanged — `Size0 + SizeRate * 30` either way —
but it is reached in half the time, so at every instant of the visible effect the particle is up to
**twice as far along its growth curve as it should be**. The size columns above are that gap
measured at one paused instant, 7 frames into an effect that has 23 to go.

### 9.8 Verdict

**The directive is "multiplayer must work", so this section is now a list of what stands between
here and that, rather than a list of reasons the patch stays in single-player.**

The design works. What killed it was one dword, one artifact of how it was tested, and one real
engine defect that this patch does not cause but now fixes (§9.6: the spell store's state
messages are dropped by the movie and never repeated; the second cave re-sends them from
`AptSpellStore::OnInitialized`). The particle rate (§9.4) — the one defect that was really the feature's
own — is a 0x28-byte cave, and it measures 0.500 steps per client frame in a running match, which
is exactly right.

The list below is a real but bounded one, and still not the "per-subsystem work, the honest price
of this feature" §8 concluded with — §9.10 adds an item to it, but the item is one byte.

**Nothing on this list now blocks network play.** Both things that did have been answered: §9.10
was the stutter and it is fixed, and §9.9's divergence was tested on 2026-08-26 between peers at
different frame rates and played clean. Items 1 and 2 record how each was closed; the rest are
open but none of them is a barrier to a match.

1. **§9.10's recompute gate — the multiplayer stutter. Fixed 2026-08-24; confirmed 2026-08-26.**
   `0x00632606` goes from 1 to the ratio. The alpha's denominator was left to a one-way
   `inc` that only runs on a networked peer, so it ratchets past the wrap and the boundary frame
   moves many times a normal frame's motion, five times a second, getting worse the longer the
   match runs. Measured on both peers of one live match: ratio **14 on the host** and **31 on the
   off-host** against a wrap of 12, a **4.0x** and a **20.0x** boundary spike where a correct build
   at any rate is 2.0x. The edit is in, the suite covers it, and the 2026-08-26 match played
   clean — so the fix holds in the case that produced the report. This explains the reported
   symptom exactly, including why idle animations were unaffected and why the host was fine, and
   it is the reason §9.9's flat-5.000-Hz match still played badly. Still outstanding, and now only
   for completeness: the probe run on both sides of a match to put numbers on the fixed build.
2. **§9.9's rendered-frame clock — the divergence. Real arithmetic, not a barrier. Closed
   2026-08-26.** The logic clock is counted in draws, so a peer that cannot hold its target rate
   simulates slower than one that can. Two measurements bound it: a machine that *does* hold 60
   paced flat for 18.5 minutes, and a match between peers at *different* achieved rates — the
   condition the identity predicts should diverge — played clean. Lockstep absorbs the difference
   the way it absorbs ordinary jitter. The wall-clock wrap §6 scopes would remove the term
   outright and is still the better design, but it is no longer a prerequisite. The field
   observation is uninstrumented; §9.9 records what would upgrade it.
3. **§9.3's limiter.** The build is only half the deliverable; `FramesPerSecondLimit` has to move
   with it. That is an INI change rather than a patch, but it is a thing a registered patch would
   have to say out loud, because going without is silent.
4. **§9.5's 7–11%.** It shifts replay timing, so every peer and every recording is affected — and
   in a network game it is a per-peer offset, which makes it a determinism concern rather than only
   a timing one.
5. **§9.7's constants.** Bounded, listed, and none observed to cause anything yet.
6. **§9.11's GPU particle clock.** `Type = GPU_PARTICLE` systems never went through §9.4's cave;
   they read the W3D millisecond clock and multiply it by the live client rate at four sites, so
   they age at the client rate rather than at the authored 30. **Measured live on 2026-08-27:
   1.920 GPU ticks per §9.4 tick** at rate 60, and `BarrageExplosion`'s particles die 30 client
   frames after birth - 0.50 s where the author wrote 1.00 s. **Fixed 2026-08-27** by a seven-byte
   edit at each of the four sites, rebuilt into the mod's `game.dat`, and confirmed correct in
   play.
7. **A match end to end.** Now partly answered: §9.9's 18.5-minute run is a real match, and it
   ended in a client crash that this measurement does not explain. That crash is still open and is
   not accounted for by anything in §9.

It stays unregistered until at least 1 and 3 are done and a two-machine match has been played and
probed on both sides.
