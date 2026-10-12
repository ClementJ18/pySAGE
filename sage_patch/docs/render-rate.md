# Raising the frame rate without speeding the game up

Engine build `2.01.2614.37001`, Edain's binary. Addresses are VAs (ImageBase `0x400000`, no ASLR);
the file offset is `VA - 0x400000` for everything cited here. Read **statically** with `pefile` +
`capstone` and measured in live matches with `sage_live` (§9). [§0](#0-which-game-dat) explains why
the binary the game runs differs from stock in exactly the code this patch is about.

**The complaint.** The game draws at 30 fps, and raising `FramesPerSecondLimit` to get more makes
everything run faster instead.

**What the engine actually does: frame rate and simulation rate are not the same clock, and the
two are already decoupled.** SAGE here simulates at **5 logic frames per second** and draws at
**30 client frames per second**, keeps a sub-frame counter on `TheGameEngine`, and hands the render
path an **interpolation alpha** at `TheGameEngine+0x3C` that the drawable and animation code
already lerps with. What welds them together is one comparison: the wrap that ends a logic frame is
written against a **literal 6** instead of against the ratio the engine derives from the two rates.

**Where that leads.** Moving the client rate and that literal together holds the simulation near
its rate at any frame rate, and genuinely buys smoothness — §9.1 measures a rendered drawable taking
**11 distinct interpolated positions per logic frame at 60 fps against 5 at stock**. Some client
content is **authored in client frames** and advanced one unit per client frame (§8); the patch
decouples each such subsystem that was measured to matter.

- **Status: registered as `render-rate`, played, including network matches between peers at
  different frame rates with no desync** (§9.9). `sage-patch apply render-rate --fps 60` is the
  whole build.
- **What it writes:** the client rate and four derived floats, the wrap, the recompute gate, three
  timecode strides, Edain's latch divisor, four GPU-particle clock multiplies, and three jumps into
  a `.fxrate` cave — the particle rate gate and the two halves of the spell-store fix (§4).
- **What is still open:** a 4–11% simulation slowdown (§9.5), a handful of unrescaled constants
  (§9.7), the two flipbook sites (§9.11), and the rendered-frame clock (§9.9), which is real
  arithmetic but not a barrier to network play. §10 is the list.
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
- **The recompute gate must equal the wrap.** `+0x38` is re-derived only on the sub-frame index the
  gate names; stock has gate 6 and wrap 6, and the patch keeps the two equal (§3.2). On a networked
  client anything else lets the alpha's denominator ratchet upward all match (§9.10).
- **Edain's binary is not stock in the pacing code.** Its latch predicate divides by a global at
  `0x00ECA400`, and its catch-up loop always runs (§0, §3.3, §3.4). The patch rescales the divisor so
  the latch keeps firing (§9.2) and refuses any binary without that predicate.
- **The simulation is untouched.** The logic rate does not move, `GameLogic::update` still advances
  its frame counter five times a second, and no simulation state depends on the sub-frame index.
- **There is no "uncapped".** The wrap counts frames, not milliseconds. [§6](#6-what-uncapped-would-cost)
  scopes what a wall-clock wrap would take and why it is a different patch.

## 0. Which `game.dat`

**Edain's `game.dat` is not stock**, and two of its differences are inside the pacing code this
patch is about. The repo-root `game.dat` and the installed `C:\RotWK\game.dat` are byte-identical
to each other; diffed against the stock `sage_patch/engine/game.dat.backup` they have eleven
differing runs, including:

| VA | stock | Edain |
|---|---|---|
| `0x00632537` | `idiv dword [0x00D9F608]` (the logic rate) | `idiv dword [0x00ECA400]` |
| `0x00ECA400` | `0` | `8` |
| `0x00632A9B` | `idiv [0x00D9F608]` / `mov ecx, eax` | `mov eax, 2` / `jmp 0x00632ABB` |
| `0x0084B43D`+ | — | ~60 bytes rewritten in the LAN transport |

The first two turn the sub-frame predicate of §3.3 from "fire on sub-frame 1" into "fire on
sub-frame 2"; the third hardcodes the catch-up bound of §3.4 so the loop always runs, and leaves two
instructions before it dead.

**The patch targets the Edain binary.** It asserts the predicate's `idiv dword [0x00ECA400]` as an
anchor and writes the divisor (§9.2), so it refuses the stock build. No other site it writes is in a
differing run — `0x00822890` (§9.6) included. Anything that edits this area should assert against
every `game.dat` in the tree rather than against one of them.

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
00632604  cmp  ecx, 6                  ; <-- the recompute gate  (patched: the ratio)
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
several feeding the lerp at `0x00B27C80` — `0x00671755` lerps a drawable transform (the dormant
path; the live one is `0x006765C4`, §9.1), `0x00676688` and `0x00676739` two vector pairs each, `0x004B523C`/`0x004B6C1C`/`0x004B6F81` W3D animation, and
`0x008A037D` a counter readout. Nine more sites read `+0x38` itself to turn a per-logic-frame rate
into a per-client-frame increment. **All sixteen follow the ratio for free**, which is why this
patch re-parameterises rather than builds.

### 3.2 The recompute gate takes the ratio

`+0x38` is initialised to **1** by the constructor (`0x0063A4DE`), not to 6 — the ratio only
becomes real when the recompute at `0x0063260F` fires, and it fires only when the rates-changed
latch at `+0x40` is set **and** the sub-frame counter equals the imm8 at `0x00632606`. Stock has
that gate at 6 and the wrap at 6: the recompute runs on the sub-frame that ends each logic frame.

The patch keeps that relationship and moves both to the ratio. **The gate must name a sub-frame that
client code actually reaches, and 1 is not one**: on Edain's binary the catch-up loop (§3.4) steps
the counter from 1 to 2 inside the same logic step that wraps it, so a gate of 1 never fires (§9.2
measures the counter). With the recompute dead, `+0x38` is left to `0x006323D2`'s one-way `inc`,
which runs only on a networked peer, and the alpha's denominator ratchets upward all match —
§9.10 measures it and what it does to motion. Keyed to the ratio, the gate fires once per logic
frame and re-derives `+0x38`, clearing whatever the network inflated.

A gate keyed to the ratio would stop working below rate 30, where the ratio is smaller than the
first reachable sub-frame. The patch floors `fps` at 35 (§4), so no rate it permits is affected.

### 3.3 The sub-frame predicate

`0x0063252F`, called from eleven client sites. On stock:

```asm
0063252f  mov  eax, [0x00d9f60c] / cdq / idiv dword [0x00d9f608]   ; ratio
0063253c  push 6 / ... / cmp esi, eax
00632543  jge  0x632554                ; ratio >= 6 -> return subFrame == 1
00632546  idiv esi                     ; ratio <  6 -> return subFrame == (6 / ratio)
```

At any ratio of 6 or more it answers `subFrame == 1` — once per logic frame. The `6` at
`0x0063253C` is a floor for *slow* clients, not the ratio.

**Edain's binary divides by `[0x00ECA400]` = 8 instead of by the logic rate** (§0). At rate 30 the
quotient is 3 and the predicate answers `subFrame == 2`, which is reachable; at rate 60 it is 7 and
the predicate answers `subFrame == 1`, which never occurs where client code can see it. Every
caller is a `previous = current` latch (`if (predicate) previous = current;` then
`previous + alpha * rate`), so a predicate that never fires freezes animations. The patch rescales
the divisor so the quotient stays 3 at any rate (§9.2).

### 3.4 The catch-up loop

`0x00632A95` exists to run *extra* logic steps for a client slower than 6× the logic rate. On stock,
`0x00632AA3`'s `cmp ecx, 6 / jge 0x632B03` skips it at every ratio of 6 or more.

**Edain's binary replaces that escape with `mov eax, 2 / jmp`** (§0), so the loop **always runs**
one extra `GameLogic::update(2)` per logic frame and bumps the sub-frame counter from 1 to 2 before
any client code reads it. That makes the effective ratio 5-of-6 at rate 30 and 11-of-12 at 60,
which is where §9.5's simulation slowdown comes from, and it is why sub-frame 1 is unobservable
(§3.2, §3.3). `0x00632ACF`, one of the three strides this patch edits, lives inside it.

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
| `0x00D9F620`/`24`/`28`/`2C` | derived from 30 | derived from `fps` | animation, audio and UI timing read them (§1) |
| `0x0063264A` | `cmp eax, 6` | `cmp eax, ratio` | **the wrap** |
| `0x00632604` | `cmp ecx, 6` | `cmp ecx, ratio` | the recompute gate, kept equal to the wrap (§3.2) |
| `0x0062ECC6`, `0x00632631`, `0x00632ACF` | `imul …, 10` | `imul …, max(10, ratio)` | §3.5 |
| `0x00ECA400` | `8` | `8` if `fps // 8 == 3`, else `fps // 3` | keeps the latch predicate on sub-frame 2 (§9.2) |
| `0x005F515F` | the cinematics-flag test | `jmp` to the `.fxrate` particle gate | CPU particles step at the authored 30 (§9.4) |
| `0x007B1102`, `0x007B1160`, `0x007B12FE`, `0x007B140B` | `imul eax, [clientRate]` | `imul eax, eax, 30` + `nop`s | GPU particles age at the authored 30 (§9.11) |
| `0x00822890` | `mov byte [ecx+0x2A0], 1` | `jmp` to the spell-store state reset | invalidates the button cache and stamps the time (§9.6) |
| `0x008231CA` | the button loop's head | `jmp` to the spell-store deferral | holds the sends for 500 ms (§9.6) |
| `0x00D9F608` | `5` | `5` | **asserted, never written** |

`ratio = fps / 5`, and `fps` must be a multiple of 5 so a whole number of client frames fits in a
logic frame. The floor is **35** (ratio 7): at the stock ratio every site computes its stock bytes,
so allowing 30 would make `detect` report every unpatched binary as carrying the patch. The ceiling
is **635** (ratio 127), because the ratio and the stride are *signed* imm8s — at 128 the wrap's
constant decodes as −128 and the simulation never advances at all.

The logic rate is asserted rather than written, so a build that does not simulate at 5 Hz fails
before the client rate is raised against a denominator this patch guessed at. The latch predicate's
bytes at `0x0063252F` and the four places the cave rejoins engine code are asserted the same way.

**`FramesPerSecondLimit` must match `fps`.** The patch owns the client rate; INI owns the pace, for
the reason in §2. If they disagree the game runs at the wrong speed — `verify` reports the rate the
binary was built for, and that is the number to put in `GameData` (§9.3).

## 5. Proving it rather than believing it

Some of the rate numbers, left behind while the others move, produce a game that is subtly the wrong
speed rather than one that crashes. So the acceptance test is a **measurement**, not an impression:

1. **The logic rate.** Run a known map for a wall-clock minute and read `[[TheGameLogic]+0x40]`
   (`sage_live` already reaches it). It must advance by **300** whatever the frame rate is. At 60
   fps with the wrap left at 6 it advances by 600 — which is the bug, and is the thing this
   measurement exists to catch.
2. **The replay corpus.** Record on the patched build and parse with `sage_replay`. Timecodes must
   still be **0.20 s** apart. 0.10 means the simulation moved.
3. **Smoothness.** Compare a panning camera and a marching horde at 30 and at 60. §3.1's sixteen
   sites are what make the difference visible; anything that steps a visual quantity per client
   frame with a *hardcoded* increment rather than by reading `+0x38` runs at double speed instead.
   `sage_patch/scripts/census_client_rate.py` classifies the readers of the client frame (§9).
4. **Determinism.** Two peers on the same build and the same `fps`, compared with
   `sage-live desync-watch`. All ten `0x0063252F` callers are client-side latches (§9.2), so the
   predicate does not reach simulation state; §9.5 and §9.9 are what can.

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
lockstep. It would also remove §9.9's rendered-frame term outright.

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
| `0x006325A0` | the sub-frame advance; owns the recompute gate `0x00632604` and the wrap `0x0063264A` |
| `0x0063252F` | the sub-frame predicate (§3.3) |
| `0x0063256F` | the alpha computation |
| `0x006329B0` | vtable `+0x98` — the logic step and the catch-up loop (§3.4) |
| `0x0062E4E8` | `GameLogic::update`; `0x0062E577` increments the frame counter |
| `0x0062EC4B` / `0x0062EC55` | the `n == 1` gate and the object sweep behind it |
| `0x0062ECC6` / `0x00632631` / `0x00632ACF` | the timecode stride (§3.5) |
| `0x00B27C80` | the lerp the alpha is handed to |
| `0x00ECA400` | Edain's latch-predicate divisor — one reader, `0x00632535` (§9.2) |
| `0x006765C4` | the Drawable interpolation that runs (§9.1); `0x0067171D` is the dormant twin |
| `0x00822890` / `0x008231CA` | the spell store's `OnInitialized` tail and button-loop head - the two §9.6 hooks |
| `0x00632606` | the recompute gate's imm8 - the ratio, like the wrap (§3.2, §9.10) |
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

## 8. Frame-counted client content

**Some client-side content is authored in client frames, and the engine advances it one unit per
client frame.** Particle lifetimes and burst delays, W3D animation cursors, and APT movie playback
are counted that way. Doubling the client frame rate therefore halves the wall-clock duration of
each one that is not decoupled — FX at twice speed, animations off their intended timing, and
one-shot APT messages racing the movie that should receive them (§9.6).

**No constant fixes this.** §1's derived floats rescale the conversions that go *seconds → client
frames*; they do nothing for content whose duration is already a frame count in the mod's INI and
in its `.apt`/`.w3d` assets. Those numbers live outside the binary.

**And a "client content at 30, render at 60" split would buy nothing.** The live drawable
interpolation (`0x006765C4`, §9.1) is recomputed once per client frame and cached against the
client frame at `+0x244`. Gate the client update to every second iteration and the stamp does not
change between the two draws, the cached `+0x208` is returned unchanged, and the second draw is a
duplicate frame. The extra client frames are what produce new interpolated positions, so they have
to stay.

So the split runs the other way: **the client frame advances on every drawn iteration, and each
frame-counted subsystem is decoupled from it individually**, with its own divider or a fractional
step. The CPU particle rate (§9.4), the GPU particle clock (§9.11) and the spell store's state
delivery (§9.6) are the subsystems this patch decouples; §9.7 lists the constants that are not yet
rescaled.

## 9. What live matches measured

First run in a real skirmish on **2026-08-20**, on the installed `game.dat` — which is
byte-identical to the repo-root one (§0), so everything here is about the binary the game *runs*.
Two instruments:

- `examples/sage_live/render_rate_probe.py` — read-only, needs no patch.
- `examples/sage_live/set_render_rate.py` — flips a running process between rates, so one match
  can be measured at both. Its limits are in §9.3, and they matter.

`sage_patch/scripts/census_client_rate.py` is the census: 77 readers of `GameClient::getFrame()`,
classified by what they do with the value. Most of §9 below started as a census row.

### 9.1 The interpolation that runs

`Drawable::getInterpolatedTransform` (`0x0067171D`) looks like the interpolation and is not: it
has **one** caller on this binary, behind `cmp byte [edi+0x43F], 0`, and its cache stamp `+0x204`
reads `0xFFFFFFFF` on all 615 drawables in a live match. Its matrices are identity. It never runs.

The live path is **`0x006765C4`**, structurally identical and at different offsets:

| field | meaning |
|---|---|
| `+0x3AC` / `+0x3DC` | previous / current matrix (row-major 3x4; translation at `+0x0C`, `+0x1C`, `+0x2C`) |
| `+0x208` | the interpolated output the renderer uses |
| `+0x244` | the client frame it was last computed on — **the cache stamp** |
| `+0x3A4` | last logic frame moved; two frames stale and it snaps instead of interpolating |
| `+0x40C` `+0x418` `+0x424` `+0x430` | four Vec3s fed to a spline (`0xA3ED38`) that overwrites the output's translation |

**The feature's premise holds.** Recompute counts per logic frame, same drawable addresses,
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
that change alone keeps them running at 60, with nothing else altered.

`[0x00ECA400]` has exactly one reader in the whole image (`idiv` at `0x00632535`), so the edit
cannot affect anything else. All ten predicate callers were read; every one is a
`previous = current` latch.

### 9.3 The render clock, and the frame limiter

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

A file-patched build computes it from 60 and is correct; a live toggle shows double-speed animations
the patch does not cause. **This is the general hazard of the live toggle**: the census counted
**436** CRT initialisers reading the client rate, and only the shapes one goes looking for get
found. `set_render_rate.py` carries `[0x00DC7A8C]` explicitly, but treat it as good-for-logic,
not-proof-for-timing. Anything timed wants a file build and a cold start.

**And the file build has the mirror-image trap.** Edain's `GameData` sets
`FramesPerSecondLimit = 30`, inside the `.big` archives where no patch reaches it, and that number
lands in `TheGameEngine+0x0C` — the limiter the `Sleep(0)` pace targets (§2). So a cold start on a
60 fps binary paces the loop at 30 while every constant says 60, and **the whole game runs at half
speed**: measured 2026-08-20 at 30.33 client fps and **2.67 Hz logic**, against 5.67 Hz once the
limiter was raised. Nothing looks broken; it just runs slow, which is the failure mode hardest to
notice and easiest to blame on the patch.

The live toggle writes `+0x0C` itself, so only a cold start on a file build shows this.

**So the binary is half the deliverable.** `FramesPerSecondLimit` in the mod's `GameData` has to
be set to the same number the build was made with — the patch's description says so for exactly
this reason. Going without is not a warning, an error or a crash but a game quietly running at half
speed. Ship the two together.

Two escape hatches, for when the `.big` is not being rebuilt. `examples/sage_live/set_limiter.py`
raises the field in a running process. And a build could carry it by sourcing `+0x0C` from the client rate rather than from `GlobalData+0x28` at
`0x00779DCF` — **not** by patching the folded accessor at `0x0066F0FD`, which §2 rules out.

### 9.4 The particle rate: the mechanism, and the fix

FX running fast on an otherwise-correct build is §8's problem in its plainest form, and for CPU
particles it is **one site**. `ParticleSystemManager::update` has a per-client-frame gate, but it
is *conditional*, and on a normal launch the condition is false:

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
burning siege works looks right, where without the cave the same scene runs at double speed. Sampled with
`examples/sage_live/fx_step.py`, which reads the same two counters against each other and needs
no patch of its own to say which side of the fix a binary is on.

### 9.5 The simulation runs slow

| client rate | measured logic rate |
|---|---|
| 30 | 6.00 Hz |
| 60 | 5.75 Hz, 5.60 Hz, 5.33 Hz across runs |

Two causes, both outside §4's arithmetic. §3.4's always-running catch-up loop bumps the sub-frame
counter an extra time per logic frame, making the effective ratio **5-of-6** at rate 30 and
**11-of-12** at 60 — which is also why Edain's logic rate is 6 Hz at rate 30 rather than 5. And
the frame limiter truncates `1000/60` to 16 ms (`ftol` at `0x0063A1AD`),
costing a further 4%.

Against Edain's own 6 Hz at rate 30, rate 60 runs 4–11% slow, varying with the frame rate the
machine actually achieves (§9.9). It shifts replay timing and is a real defect. Fixing it means
making the wrap account for the catch-up loop's extra increment, which is a different edit from
§4's.

### 9.6 The spell store: the engine caches an intention it never confirms

Without the fix, the spellbook at 60 fps can open with nothing purchasable however many points the
player has. **It is a genuine engine defect, and not this patch's** — it reproduces on a stock
binary using Edain's debug `x2 speed` button, which moves no rate constant at all. A faster client
only makes it likely. The mechanism was proved by intervention in a live 60 fps match on 2026-08-20.

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
which is §8's "APT movie playback is authored in client frames" arriving as a dropped one-shot
message rather than as something playing at double speed.

**Proved by intervention.** In a live match at rate 60 with the book showing nothing purchasable,
writing a sentinel over the twenty cache dwords at `this+0x2AC` forced `update` to re-send every
state. The book lit immediately; the previously dead Rebuild button then took a click, staged
`SCIENCE_RebuildMen` for 1 point, and moved to `_already_purchased` while its neighbour dropped to
`_disabled` as the basket spent the point. Nothing else was touched.

**Nothing in the purchase logic was ever wrong.** Across both the broken and repaired states the
engine held the correct answer: `0x005FED5B` passed for the two affordable powers, prerequisites
and points were right, `AptSpellStore::InputEnabled` (`0x00822974`) read `"1"`, and the closing
latch at `this+0x2A2` was clear. The failure is entirely in delivery.

**The fix ships in this patch.** Two hooks, because one is not enough.

- `AptSpellStore::OnInitialized` (`0x0082285B`) already resets `+0x2A2`, `+0x348`, `+0x34C`,
  `+0x350` and `+0x354` and simply omits the button array. The patch takes over the seven-byte
  tail of that handler (`mov byte [ecx+0x2A0], 1`, with `ret 4` behind it) and jumps to a cave that
  carries the displaced store, stamps all twenty slots at `this+0x2AC` with `-1`, records
  `GetTickCount`, and rejoins the handler's own `ret`.
- `update`'s button loop head (`0x008231CA`, ten bytes; the one branch that reaches it targets its
  first byte, so it lands on the hook too) jumps to a second routine that compares the tick against
  that stamp and, until **500 ms** have passed, takes the loop's own "all twenty done" exit. Only
  the button states wait; the layout, help text and description still run every pass.

**Invalidating the cache on its own is a no-op.** `OnInitialized` is what sets `+0x2A0`, the flag
`update` checks before it does anything — so the first update after it is the same pass the
original send was already happening on, and stamping the cache there moves nothing; measured at
60, it changes nothing. The deferral is the half that does the work, and the invalidation is what
makes the deferred pass send all twenty rather than only those whose computed state happens to
differ from constructor garbage.

**Why a clock and not a count of passes.** `update` runs off whatever pump is turning, and while
the panel is up that is the modal `Sleep(5)` spin rather than the client frame — so a pass count
would mean a different wall-clock wait at every rate, which is the exact class of bug this document
is about. The subtract and the compare are unsigned, which is what makes them right across
`GetTickCount`'s 49-day wrap.

**The visible cost is a blank spellbook for the first half-second after it opens.** The delay is
not derived from a measurement: what is actually needed is however long the movie takes to build
its clips and run each one's ten-frame `_fade_in`. If the book comes up blank and stays blank, the
number is the first thing to raise, and `DEFER_MS` is where it lives.

**This fix is not rate-specific**, and folding it into `render-rate` is a deliberate choice rather
than a technical one: the same race can tip on a stock 30 fps build, where nothing installs this.
Reaching those installs means giving it a patch of its own.

**Three behaviours that look like the bug, and are not.** All three are real, all three were
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

### 9.8 The pacing core

Read out of the live process with `sage_live`'s `ProcessMemory`, mid-match at `--fps 60` with
`FramesPerSecondLimit = 60`:

```
[0x00D9F608] logic rate  = 5          [0x00D9F60C] client rate = 60
TheGameEngine+0x0C maxFPS = 60        +0x38 ratio = 12
client frame advancing 62/s           logic frame advancing ~5.2/s
```

Every number the patch is responsible for is what §3 and §4 intend: the wrap holds the simulation
near its rate, and the interpolation alpha sweeps each logic frame in twelfths instead of sixths.

(The overshoot in the client rate — 62.5 rather than 60 — is the frame limiter's `ftol` at
`0x0063A1AD` truncating `1000/60 = 16.67` to 16 ms. Stock has the same rounding at `1000/30 → 33`,
where it costs 1%. §9.5 is what the logic rate does with it.)

### 9.9 The simulation rate is a function of each machine's frame rate — and it does not end multiplayer

The identity below is real arithmetic. A match between peers at different achieved frame rates
played clean ([below](#mixed-frame-rates-played-clean--2026-08-26)), so it is not a barrier to
network play — lockstep absorbs it.

**§9.5's three runs vary by 8% on one machine** — 5.75, 5.60 and 5.33 Hz at client rate 60. The
catch-up loop and the `ftol` truncation are fixed costs and cannot vary; what varies is the frame
rate that machine was actually achieving.

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

**Consequences.**

- **Every peer wants a different speed, set by its graphics performance.** Lockstep holds them
  together by stalling whoever is ahead: a peer that renders 60 and wants 5.5 Hz waits for one that
  can only supply 4.1.
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

The divergence is bounded and the game absorbs it (below). The wall-clock wrap
[§6](#6-what-uncapped-would-cost) scopes — logic frames ending on elapsed milliseconds rather than
on a count of draws — would remove the term entirely, but it is not a prerequisite for playing a
match.

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

`logic rate = achieved fps / ratio` still follows from the wrap counting draws, and a client that
cannot hold 60 still runs slow. But **a machine that holds 60 paces exactly** — so this mechanism
is not, on its own, an explanation for a stuttering or desyncing match on hardware that keeps up.
Check that the peer in question is actually dropping frames before reaching for it.

That match ran 18.5 minutes with `TheGameLogic+0x1BC` (the desync latch) clear throughout, and
ended in a **client crash** rather than a mismatch, unexplained by anything here (§10).

#### Mixed frame rates played clean — 2026-08-26

Online play on the 60 fps build **between peers that were not sustaining the same frame rate** —
the exact condition the identity above predicts should diverge. It played clean: no desync, and no
stutter.

That is the discriminating case. Two peers both holding 60 would not have exercised the mechanism
at all; peers at different achieved rates do, and the divergence did not surface as anything a
player or the lockstep layer objected to.

**What this settles, and what it does not.** **The rendered-frame clock is not a barrier to network
play**; the multiplayer stutter is §9.10's, not this. The arithmetic stands — a peer that drops
frames still simulates slower than one that does not — and lockstep absorbs that difference the way
it absorbs ordinary network jitter, rather than compounding it.

**Evidentiary status: field observation, not instrumented.** Per-peer achieved frame rates were
not recorded, and `desync-watch` was not run on both sides. Two things would upgrade it — logging
`TheGameLogic+0x1BC` on both peers across a match, and sampling each peer's achieved rate to put
numbers on how far apart they actually were. Both would be needed before anyone quotes a bound on
how far apart peers can drift.

### 9.10 The alpha's denominator ratchets on a networked client, and never resets

**Why the recompute gate takes the ratio (§3.2).** With the gate keyed to a sub-frame client code
never reaches, a networked client's motion stutters while its logic rate holds a flat 5.000 Hz. The
logic rate is not the problem; the **interpolation alpha's denominator** is.

Measured 2026-08-24 in a multiplayer match on a 60 fps build with the gate at 1, and the symptom
split is the whole clue:

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

**Two sites write it. With the gate at 1, one is dead and the other only runs on a networked peer.**

- **`0x0063260F`, the recompute**, sets `+0x38 = clientRate / logicRate`. It needs the
  rates-changed latch at `+0x40` **and** the sub-frame index named by the imm8 at `0x00632606`.
  Sub-frame 1 never occurs where that gate can see it: the hardcoded catch-up at `0x00632A9B` runs
  `inc dword [ebp+0x34]` (`0x00632AC0`) inside the same logic step, so the counter is 2 before any
  other code sees it — measured over 373 frames ([§9.2](#92-the-stuck-animations-were-one-dword)).
  **Gated on 1, the recompute never runs.**

- **`0x006323D2`, `inc dword [esi+0x38]`**, inside `0x0063239D` (sole caller `0x00632450`). It
  grows the ratio when the sub-frame has outrun it and the peer-lag readout at net vtable `+0x58`
  is low, and stamps a float high-water mark beside it at `+0x44`. It returns early at
  `0x006323A6` — `mov ecx, [0x00DE4468] / test ecx, ecx / je` — so **it cannot run without a
  network object**: never in single-player, never in a replay. Only on a networked peer.

One writer is disabled and the other only counts up. `+0x38` is a ratchet.

**That is why no single-player measurement shows it.** In single-player `0x0063239D` early-outs
and `+0x38` sits where it was. And §9.1's headline — recomputes
doubling from 5 to 11 — counts `0x006765C4`'s cache stamp, which advances once per client frame no
matter what the alpha evaluates to. Eleven recomputes with a wrong alpha and eleven with a right
one are the same number.

**Measured 2026-08-24**, live, on the *host* of that networked match, with the `measure_network`
measurement of `examples/sage_live/render_rate_probe.py`. The host is the milder half; the off-host
reading is in the two-machine table below:

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

**The host looks fine for the same reason it is a ratchet.** Both peers hold a network object, so
`0x0063239D` is reachable on both — but its `inc` is gated on the peer-lag readout, and the peer
that spends the match waiting on frames is the one that trips it. Single-player and replays never
trip it at all, which is why
single-player motion at 60 looks smooth.

**The patch sets the imm8 at `0x00632606` to the ratio**, the same byte as the wrap (§3.2, §4).
`TestTheGateAndTheWrapAgree` asserts the two hold the same byte at 35, 60, 120, 300 and 635 fps.
That restores the stock relationship — stock's gate of 6 equals stock's wrap of 6 — so the
recompute fires on the sub-frame that ends the logic frame and re-derives `+0x38` every logic frame,
clearing whatever the network inflated. Networked matches on the patched build have played clean
(§9.9). The reading that confirms it on a given match is the one above: `+0x38` should sit at 12 and
stay there, and `boundary_spike` should read 2.0x on both peers.

**What this does not fix.** [§9.9](#99-the-simulation-rate-is-a-function-of-each-machines-frame-rate--and-it-does-not-end-multiplayer)
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

**Read the last row, not the one above it.** The raw gap overstates things, because Edain's binary
has a gap even with the gate right: the catch-up loop eats sub-frame 1, so the alpha starts at
`2/ratio` and the boundary frame always moves double. Measured against the frames either side of
it:

| build | ratio | normal step | boundary jump | spike |
|---|---|---|---|---|
| Edain 30 | 6 | 0.167 | 0.333 | **2.0x** |
| 60, gate = ratio | 12 | 0.083 | 0.167 | **2.0x** |
| host, gate = 1 | 14 | 0.071 | 0.286 | 4.0x |
| off-host, gate = 1 | 31 | 0.032 | 0.645 | **20.0x** |

With the ratio and the wrap agreeing, Edain's binary spikes exactly 2.0x at *any* rate — the same
as it does at 30 without this patch. True stock, whose catch-up loop is dormant, spikes 1.0x; the
residual 2.0x is its own defect, fixed by [`interpolation-alpha`](interpolation-alpha.md). The off-host is spiking
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

**Read statically and confirmed in a live paused match on 2026-08-27** — the measurement is at the
end of this section. The sites below are byte-identical in the repo's
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

**The fix, confirmed in play.** `imul eax, [0x00D9F60C]` (seven bytes)
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

**The two `0x007FB2xx` sites are left alone, and no symptom has been reported.** They take the same
multiply in the flipbook path, so the prediction is a sprite sheet running at the wrong speed; with
the four-site fix the effects are reported correct. That is the absence of a reported symptom rather
than a measurement — nobody has put a number on what the flipbook does at 60.

**The engine's numbering differs from `sage_ini`'s.** The engine's
`ParticleSystemType` name table is at `0x00C31A84`, and the indices are
`NONE=0, PARTICLE=1, DRAWABLE=2, STREAK=3, VOLUME_PARTICLE=4, SMUDGE=5, TERRAIN_PARTICLE=6,
GPU_PARTICLE=7, GPU_TERRAINFIRE=8` — the default is `PARTICLE`, which is why `0x005FACCB` skips
writing `Type` when the field at template `+0xC` reads 1. `sage_ini`'s `ParticleSystemType` was
surveyed from the corpus rather than from the binary and numbers its members differently.

#### Measured in a paused match on 2026-08-27

Read live, in a 60 fps build without the four-site fix, with `BarrageExplosion` on screen and the
game paused. Every
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

## 10. Status and open items

The patch is registered and played, including network matches between peers at different achieved
frame rates with no desync (§9.9). The pacing core (§9.8), the latch predicate (§9.2), the recompute
gate (§9.10), both particle clocks (§9.4, §9.11) and the spell store (§9.6) are in it.

Open:

1. **§9.5's 4–11% slowdown.** It shifts replay timing, so every peer and every recording is
   affected; in a network game it is a per-peer offset, which makes it a determinism concern rather
   than only a timing one. The fix is a wrap that accounts for the catch-up loop's extra increment.
2. **§9.7's constants.** Bounded, listed, and none observed to cause anything.
3. **§9.11's flipbook sites** (`0x007FB2CE`, `0x007FB334`), unmeasured at 60.
4. **§9.9's rendered-frame clock.** Real arithmetic, absorbed by lockstep; the wall-clock wrap of §6
   would remove it. The mixed-rate observation is uninstrumented, and §9.9 records what would
   upgrade it.
5. **§9.3's limiter.** Not a defect but a deployment requirement: `FramesPerSecondLimit` has to move
   with the build, and going without is silent.
6. **The 18.5-minute match's client crash** (§9.9) is unexplained by anything in §9.
