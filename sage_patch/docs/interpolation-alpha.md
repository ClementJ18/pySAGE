# The interpolation alpha skips a step at every logic-frame boundary

Engine build `2.01.2614.37001`. Addresses are VAs (ImageBase `0x400000`, no ASLR); the file offset
is `VA - 0x400000` for everything cited here. Read **statically** with `capstone` against the
AotR and Edain shapes of the binary; `docs/render-rate.md` §3 derives the surrounding pacing loop
and §9.2 supplies the live measurement this rests on.

**The complaint.** Resource readouts and offset animations jitter — a regular hitch, five times a
second, on a binary that is otherwise smooth. It is present on Edain and on AotR's `delayfix`
build, and absent on stock.

**What it is.** The interpolation alpha is taken over a range one wider than the one the client
can actually observe, so every interpolated thing on screen moves a normal step N−1 times and then
a **double** step, once per logic frame.

- **Status: built, unit-tested, not played.** It is the registered experimental
  `interpolation-alpha` patch; `sage-patch apply interpolation-alpha` is the whole build.
- **Cost:** one five-byte hook and an 81-byte cave.
- **Precondition:** the binary's catch-up loop must always run (§4). Stock is not affected by this
  defect and the patch refuses it.

## 1. The two clocks and the alpha between them

SAGE simulates at 5 logic frames per second and draws at 30. `TheGameEngine` (`0x00DE4324`) carries
the sub-frame state that bridges them:

| field | meaning |
|---|---|
| `+0x34` | the sub-frame counter — one rendered frame each, reset by the wrap |
| `+0x38` | the ratio, `clientRate / logicRate`, set by the recompute at `0x0063260F` |
| `+0x3C` | the interpolation alpha |

`GameEngine::recomputeAlpha` (`0x0063256F`) is called on every sub-frame, from `0x00632642`,
`0x006326BE`, `0x006326E4` and `0x00632AF0`:

```asm
0063256f  cvtsi2ss xmm1, [ecx+0x38]    ; the ratio
00632574  cvtsi2ss xmm0, [ecx+0x34]    ;   the sub-frame
00632579  divss    xmm0, xmm1          ;     subFrame / ratio
0063257d  ...                          ;       clamped into [0, 1] -> +0x3C
```

Seven sites read `+0x3C`: the live drawable interpolation at `0x006765C4`, three W3D animation
lerps (`0x004B523C`, `0x004B6C1C`, `0x004B6F81`), and the counter readout at `0x008A037D` — which
is what puts this on a resource display.

## 2. What "smooth" requires

Within one logic frame the renderer lerps between a `previous` and a `current` transform. At the
boundary the matrices roll over: `previous` becomes `current`, and the next frame's alpha is
measured against a fresh segment. So the motion the eye sees on the boundary frame is **the alpha
itself**, not the difference from the last one.

Smooth therefore needs one thing: consecutive observed alphas evenly spaced, *and* the first alpha
of a segment equal to that same spacing.

Stock satisfies it. The counter takes 1..6, `+0x38` is 6, the alpha sweeps `1/6 … 6/6` in six
steps of `1/6`, and the boundary frame moves `1/6` — the same as every other frame.

## 3. Why this build does not

`docs/render-rate.md` §3.4 records the edit. The catch-up loop's escape at `0x00632A9B` — stock
`idiv [0x00D9F608]` / `mov ecx, eax`, then `cmp ecx, 6` / `jge 0x00632B03`, which on a 30 fps
client always skips the loop — is replaced with:

```asm
00632a9b  b8 02 00 00 00    mov  eax, 2
00632aa0  eb 19             jmp  0x00632abb      ; esi = 2, esi++ -> one iteration
```

so the loop runs exactly one iteration every logic frame, and its body opens with
`inc dword [ebp+0x34]` at `0x00632AC0`. The wrap sets the counter to 1; the catch-up loop steps it
to 2 **inside the same logic step**, before `GameClient::update` next runs.

**Sub-frame 1 is therefore never observable.** Measured live over 373 client frames
(`render-rate.md` §9.2): the counter took 2..6 at rate 30 and 2..12 at rate 60, never 1.

The denominator did not move with it. `+0x38` is still `clientRate / logicRate`, because the
recompute gate at `0x00632604` tests the counter against 6 and 6 still occurs. So:

| | observed sub-frames | `+0x38` | alpha sweep | interior step | boundary step | spike |
|---|---|---|---|---|---|---|
| stock, 30 fps | 1..6 | 6 | `1/6 … 1` | `1/6` | `1/6` | **1.0x** |
| this build, 30 fps | 2..6 | 6 | `2/6 … 1` | `1/6` | `2/6` | **2.0x** |
| this build, 60 fps | 2..12 | 12 | `2/12 … 1` | `1/12` | `2/12` | **2.0x** |

**The spike is 2.0x at every rate**, which is why it reads as a regular hitch rather than as
roughness: N−1 correct frames, then one frame that moves twice as far, five times a second.

> ⚠ `render-rate.md`'s §9.10 table lists `stock 30 | 2.0x` and concludes "a correct build spikes
> exactly 2.0x at *any* rate". That row was measured on the repo's own `game.dat`, which carries
> the catch-up edit — §0 of that document warns about exactly this. True stock spikes **1.0x**, and
> 2.0x is the defect, not the baseline.

## 4. The correction

The observed range is `2..N`, which is N−1 values. Mapping it onto an even sweep that still ends at
1.0 — the phase stock has, and the one the seven readers are written against — is:

```
alpha = (subFrame - 1) / (ratio - 1)
```

At ratio 6 that is `1/5, 2/5, 3/5, 4/5, 1` — four interior steps of `1/5` and a boundary step of
`1/5`. Spike 1.0x, at any ratio.

**This is correct only where sub-frame 1 is unobservable.** On stock the range is `1..N` and the
same formula yields `0, 1/5, … 1`, putting a *zero-length* step at the boundary — the same defect
with the sign flipped. So the patch anchors `0x00632A9B` to the always-runs bytes and refuses a
binary that does not carry them.

### Why not revert the catch-up loop instead

Restoring the stock escape would also even the sweep, in seven bytes. It would also undo the delay
fix: the stolen sub-frame is what makes a logic frame complete in N−1 rendered frames instead of N,
raising the logic clock from 5 Hz to 6 Hz on a 30 fps client. A network run-ahead is counted in
*logic frames* and felt in *seconds*, so that same 1/6 is what shortens the off-host's input delay.
Reverting the loop buys the jitter fix by giving the latency fix up. Correcting the denominator
keeps both.

### The cave

The routine is 49 bytes and nothing branches into its body, so the five-byte `cvtsi2ss` at its head
is a whole hook window and the replacement owns the function. It touches only `xmm0` and `xmm1` —
exactly what the routine it replaces clobbers.

```asm
  cvtsi2ss xmm1, [ecx+0x38]      ; the ratio
  subss    xmm1, [0x00BD1908]    ;   - 1  = the sub-frames the client observes
  xorps    xmm0, xmm0
  comiss   xmm1, xmm0
  jbe      no_span               ; +0x38 is 1 until the first recompute: do not divide
  cvtsi2ss xmm0, [ecx+0x34]      ; the sub-frame
  subss    xmm0, [0x00BD1908]    ;   - 1
  divss    xmm0, xmm1
  xorps    xmm1, xmm1
  maxss    xmm0, xmm1            ; the same two-sided clamp the stock routine ends with
  movss    xmm1, [0x00BD1908]
  minss    xmm0, xmm1
  movss    [ecx+0x3c], xmm0
  ret
no_span:
  movss    xmm0, [0x00BD1908]    ; no span yet - show the current transform
  movss    [ecx+0x3c], xmm0
  ret
```

`0x00BD1908` is the engine's own `1.0f`, already read by the routine being replaced for its high
clamp, and already named `FLOAT_ONE` in `addresses.py`.

**The degenerate arm is load-bearing.** `+0x38` is 1 from the constructor (`0x0063A4DE`) until the
first recompute fires, so `ratio - 1` is genuinely zero for the opening window of a match.

**The clamp is kept** because `0x006323D2` can still ratchet `+0x38` past the wrap on a networked
peer (`render-rate.md` §9.10), which is the one case that drives the alpha out of range.

## 5. Composition with `render-rate`

`render-rate` rewrites the wrap (`0x0063264A`), the recompute gate (`0x00632604`) and the latch
divisor (`0x00ECA400`). This patch reads none of them: it edits one routine none of them is in, and
takes `+0x38` at run time rather than deriving anything from the bytes that set it. Whatever ratio
`render-rate` establishes, the alpha is taken over it. `TestItComposesWithRenderRate` asserts the
two write-sets are disjoint.

Note that both patches assert the same build shape from opposite ends — `render-rate` anchors the
latch divisor at 8 and the predicate's `idiv [0x00ECA400]`, this one anchors the catch-up escape —
so neither will run against a stock binary, and for the same underlying reason.

## 6. What this does not fix

- **`render-rate.md` §9.9**, the rendered-frame clock: the logic rate is still each machine's
  achieved frame rate divided by the ratio, so two peers at different frame rates still simulate at
  different speeds. This makes each machine render *its own* simulation correctly; it does not make
  two machines agree.
- **The 20x off-host spike of §9.10** is a different defect with a different fix (the recompute
  gate), already applied in `render_rate.py`. This patch corrects the 2.0x that remains underneath
  it, which §9.10 mistook for the floor.

## Address table

| VA | what |
|---|---|
| `0x0063256F` | `GameEngine::recomputeAlpha` — the hooked routine, 49 bytes |
| `0x00632574` | its body, anchored and never written |
| `0x00632A9B` | the catch-up escape — anchored to the always-runs bytes |
| `0x00632AC0` | `inc dword [ebp+0x34]`, the increment that consumes sub-frame 1 |
| `0x00632604` / `0x0063264A` | the recompute gate and the wrap — read by neither this patch nor its cave |
| `0x00BD1908` | `1.0f` (`FLOAT_ONE`) |
| `0x00DE4324` | `TheGameEngine`; `+0x34` sub-frame, `+0x38` ratio, `+0x3C` alpha |
| `0x0063A4DE` | the constructor that leaves `+0x38` at 1 |
| `0x006323D2` | `inc dword [esi+0x38]`, the networked ratchet the clamp still covers |
