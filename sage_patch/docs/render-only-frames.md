# Frames drawn without a client frame

Engine build `2.01.2614.37001`, Edain's binary. Addresses are VAs (ImageBase `0x400000`). Read
statically with `explore.py` and measured in a live Edain match on 2026-10-25 with
`sage_live`, running OH1A's accelerator at `FpsLimit = 60`, `LogicHz = 30`.

**The patch:** `render-only-frames`. Status: static-verified and emulated
(`tests/sage_patch/test_render_only_frames_emulated.py`), not yet played.

## 1. What a render-only frame is

The accelerator (`accel-module.md`) raises the frame rate by answering the engine's own
"render this frame without advancing the simulation?" predicate. Its note on the scheduler at
`0x006325A0`:

```
call this->vtbl[0x9C]        ; 0x00632409 - input, client, net: runs on both paths
if (renderOnly) { [[0x00DE4388]+0xC8] = 0; draw; return }
[[0x00DE4388]+0xC8] = 1; advance the sub-frame; GameLogic::update
```

So `GameClient::update` (`0x0064849E`, slot 4 of the `GameClient` vtable at `0x00C048B0`), and the
drawing inside it, runs on **every** drawn frame. The client frame counter
(`TheGameClient->vtbl[0x7C]`) does not. Measured with `examples/sage_live/render_rate_probe.py`:
client frames at **30.0/s** while the accelerator's log reports 60 rendered frames a second.

Engine code written against "one client update per client frame" then sees two updates per
client frame, and goes wrong in one of two ways depending on how it counts:

- **Stamped against the client frame:** the second call is skipped. *Locomotor rocking* (§2).
- **Counted per call:** it runs at twice its speed. *Scripted camera moves* (§3).
- **Keyed to the sub-frame:** it fires twice. *Script fades* (§4).

The engine's render-only flag is no help to a fix. `[[0x00DE4388]+0xC8]` is written *after*
`0x00632409` runs, so during the client update it still holds the previous frame's answer. The
fixes key on the client frame and on wall time instead, which is also what makes them identities on
a stock binary, where every draw is a new client frame.

## 2. Locomotor rocking flickers

**Symptom:** ships oscillate far too fast.

**The rocking itself runs at the right rate.** The wave phases at `[drawable+0x13C]+0x34` and
`+0x38` advance by `AeleronCorrectionRate` / `ElevatorCorrectionRate` per integration
(`0x00673847`–`0x006738AA`). Sampled live over two seconds across seven ships:
`EvilMenCorsairShip` 0.6263/s against a rate of 0.021, and 0.4773/s against 0.016, i.e. 29.8
integrations a second, the stock rate.

**What goes wrong is the second draw.** `Drawable::calcPhysicsXform` (`0x0067BDC0`):

```
0067BDF6  mov ecx, [0x00DE4388] / call [eax+0x7C]   ; client frame
0067BE04  cmp [esi+0xAC], ebx                       ; stamp on the current locomotor
0067BE0A  je  0x0067BE86                            ; same frame: return 0
...       switch Locomotor.Appearance (+0x74)       ; 9 = SHIP -> 0x006732DC
```

Its one caller, `Drawable::applyPhysicsXform` (`0x0067BE90`), zeroes a four-float info, calls it at
`0x0067BF39`, and on 0 (`0x0067BF3E test al, al / je`) applies nothing. So on a render-only frame
the hull is drawn level, and on the next frame it is tilted again: a 30 Hz flicker. Every
appearance with a physics transform does the same (cases 1–5, 8, 9). Ships show it most because
they tilt the most.

**The fix** wraps the call at `0x0067BF39`:

- On a produced transform, it copies the four floats into a tail added to `DrawableLocoInfo` and
  stamps the tail with the client frame (and that frame xor a check word).
- On a refusal, it re-applies the tail if the tail was computed *in this client frame*.

A refusal for any other reason (no locomotor, a non-physics appearance) is left alone, because the
cache cannot be from the current frame in that case. The check word matters because the heap does
not zero the block.

`DrawableLocoInfo` (vtable `0x00C10E48`, constructor `0x00670392`) is allocated `0x58` bytes at
five sites, `0x00670B28`, `0x006732F8`, `0x00677042`, `0x0067A8E0` and `0x0067B7C6`, each
`push 0x58 / call operator new (0x0042F6E0)` followed by the constructor, and the constructor has no
other caller. The patch makes all five `push 0x70`. The allocator is the sized heap call
`[0x00DC5E44](size, 1, 0)`, so the larger block frees normally.

## 3. Scripted camera moves run at double speed

**Symptoms:** the victory camera spin is too fast; in the Imladris shellmap the camera stops well before
the fade to white that should end its move.

The spin is a script camera action. Script case `0x007CB98A` calls `0x007BB979`, which calls
`TheTacticalView` (`0x00DE447C`) vtable `+0xCC`. `W3DView` (vtable `0x00BDD490`) keeps one
rotation:

| field | what |
|---|---|
| `+0x1AC` | `numFrames` |
| `+0x1B0` | `curFrame` |
| `+0x1BC` | `numHoldFrames` |
| `+0x1C0` | the ease curve, built from the raw milliseconds (`0x0070FCC0`) and fed `cur/num` |
| `+0x1DC` | rotating |

- **Setup** converts milliseconds to frames with `idiv [0x00DC7A8C]`, `TheW3DFrameLengthInMsec`.
  That is `1000 / clientRate` as an integer, stored at start-up by `0x00BC146C`, and live it reads
  **33**. The conversions are at:
  - `0x00485DD4` (`rotateCamera`, `+0xCC`)
  - `0x00485E7A` / `0x00485E9A` (toward object, `+0xD0`: hold and duration)
  - `0x004886B1` (toward position, `+0xD4`)
- **Two getters** convert back with `imul [0x00DC7A8C]`: `0x00485F62` (`+0x7C`) and `0x00486279`
  (`+0x88`), the rotation's remaining time.
- **The step** is `0x0048A417`. Its one caller is in the view update (`0x0048A9E0`, gated only on
  `+0x1DC`), and its first instruction is `inc dword [esi+0x1B0]` (`0x0048A420`). It reads the
  three counters only as ratios (`cur / num`, and `cur >= num + hold` to finish).

With a step per drawn frame, a rotation sized for 30 steps a second finishes in half its time.
`render-rate` does not have this problem, because it raises the client rate that `0x00DC7A8C` is
derived from.

**The other frame-counted moves have the same shape.** Each setup converts with
`idiv [0x00DC7A8C]`, and each step is an `inc` of its counter, read only as `cur / num`:

| move (view vtable) | setup `idiv` | count / counter | step |
|---|---|---|---|
| rotate (`+0xCC`, `+0xD0`, `+0xD4`) | as above | `+0x1AC` / `+0x1B0` | `0x0048A420` |
| zoom (`+0xEC`, `ZOOM_CAMERA`) | `0x004887F4` | `+0x208` / `+0x20C` | `0x00486615` |
| `+0xF0` | `0x0048887A` | `+0x22C` / `+0x230` | `0x004866AE` |
| pitch (`+0xF4`, `PITCH_CAMERA`) | `0x0048892E` | `+0x1E0` / `+0x1E4` | `0x0048675F` |
| `+0xF8` | `0x004889B2` | `+0x258` / `+0x25C` | `0x004867F8` |
| reset (`+0xC8`, `RESET_CAMERA`, mode 3 at `+0x2354`) | `0x0048D3C5` | `+0x19C` / `+0x1A0` | `0x004865E1` |

The script handlers reach them through `0x007BB5D6` (zoom), `0x007BB678` (pitch) and `0x007C58BF`
(reset). Apart from these readers and writers, the only accesses to the counters are the view's
save code (`0x0048B1C5`–`0x0048B22F`).

**The path moves keep milliseconds and are fed a frame.** `MOVE_CAMERA_TO` (`0x007BB540`, view
`+0x60`) and `MOVE_CAMERA_ALONG_SPLINE_PATH` with its locator twin (`0x007BBB23`, `+0x64`) are stepped
by `0x00489817(ms, locator)` and `0x0048688A(ms)`, which add `ms` to an elapsed total and compare it
with the duration. The view update calls them with `push [0x00DC7A8C]`, a fixed 33, at
`0x0048A9F2`, `0x0048AAE5` and `0x0048AB06`. So a 12 s spline ends after about 6 s under the
accelerator. The Imladris shellmap moves the camera along `ganzweg` for 12 s and starts its fade to
white from a 9 s logic timer, so the camera stands still for about 3 s first.

**The fix** puts every timed move on wall time:

- It points the nine `idiv` and two `imul` operands at a cave dword holding 1, so the counters
  become milliseconds. The instructions stay in place.
- It replaces each `inc` with a call that adds `timeGetTime` (`0x00BD0920`) minus that counter's
  previous step. Every counter has its own clock, because zoom, pitch and a rotation can run
  together. A counter's first step (its setup zeroes it) adds one stock frame, as the `inc` did,
  and any step is clamped to 200 ms, so a stall cannot jump the camera.
- It replaces each `push [0x00DC7A8C]` with a call that leaves the milliseconds since that site
  last ran on the stack, where the push would have put its value: the routine writes the value
  over its return address and returns by jumping to it. A gap over 200 ms (a new move, or a hitch)
  counts as one stock frame.

Progress is then the same at any frame rate and as smooth as the frames are. On a stock binary,
wall time and 30 steps a second agree to within a frame.

## 4. Script fades step in 200 ms jumps

**Symptom:** a fade to white or black is very choppy.

**The fade is stepped once per logic frame.** `CAMERA_FADE_ADD`/`SUBTRACT`/`SATURATE`/`MULTIPLY`
(template ids 124–127) are dead cases in the action switch (`0x007CAFD5`, table `0x007CF857`).
The script engine takes them itself in `setFade` (`0x006030C1`, `sub edx, 0x7C`), which writes
these fields on `TheScriptEngine` (`0x00DE3BAC`):

| field | what |
|---|---|
| `+0x1A238` | the fade type |
| `+0x1A23C` | just set |
| `+0x1A240` / `+0x1A244` | min / max |
| `+0x1A248` | the current value |
| `+0x1A24C` | the frame |
| `+0x1A250` / `+0x1A254` / `+0x1A258` | increase / hold / decrease, straight from the script |

`updateFades` (`0x00603016`, `inc` the frame, then a linear blend) is called from
`ScriptEngine::update` (`0x0060CC67`, vtable `0x00BF9ED0` `+0x28`, read live). `GameLogic::update`
calls that at `0x0062E6B7`, behind the once-per-logic-frame latch `[ebp-0xD]`. So the fade's
"frames" are logic frames, and its value changes five times a second, with or without the
accelerator.

**The view smooths it, once per logic frame.** In `W3DView::draw`, `0x0048E2D3` calls the latch
`0x0063252F` (true while `TheGameEngine+0x34`, the sub-frame, is 2; `render-rate.md` §9.2). On
true it takes the new step: previous `+0xCC` = current `+0xD0`, current = `TheScriptEngine+0x1A248`.
The draw then shows `previous·(1−α) + current·α` with `α = TheGameEngine+0x3C`
(`0x0048E3AD`–`0x0048E40E`), the same alpha units move by.

**A render-only frame makes the latch fire twice.** The scheduler runs the client update *before*
it advances the sub-frame, so a render-only frame and the frame after it see the same sub-frame,
and the same client frame (§1). On the second firing, previous becomes current, and the blend
shows the new step at once and holds it for the whole logic frame.

**The fix** wraps the call at `0x0048E2D3`. A true answer from the latch is passed on only when the
client frame differs from the one the fade last stepped on. On a stock binary every draw is a new
client frame, so the answer is the latch's own.

The latch has nine other callers (`0x00461EBD`, `0x004B51F4`, `0x004B6BE6`, `0x004ED6AB`,
`0x0064871C`, `0x006487F3`, `0x006759BB`, `0x0083BA12`, `0x008A036E`), and they fire twice per
logic frame under the accelerator too. None has been tied to a visible fault yet.

## 5. The accelerator's `SmoothAnimation` breaks weather snow

`TheSnowManager` (`0x00DE3B54`, vtable `0x00BDE06C`) runs its update (`0x004943E1`, slot `+0x28`,
called from `GameClient::update` at `0x00648591`). The update advances the snow's time `+0x10` and
fall/drift offsets `+0x94..+0x9C` by the W3D clock's delta, `[0x00DD1E0C] - [0x00DD1E10]` in ms.
A negative delta is read as unsigned, adding 2^32 (`0x00494408`, `fadd [0x00BD8698]`).
The time is then reduced modulo the snow period (`BoxHeight / SnowSpeed`), and the offsets move by
the reduced change. The two draw paths, point-sprite `0x00492F0F` and emulation `0x004936CB`, place
each flake from `+0x94`.

The engine's setter `0x00516E20` always moves the pair together: previous = current, current = new.
The accelerator's `SmoothAnimation` (`lrDecide` in `aotr_logicrate.inc`, on by default) moves
current forward on a render-only frame without touching previous. It puts current back on the next
logic frame. The snow update reads the pair before `W3DDisplay::draw` runs the setter. So it sees
about 49 ms on the render-only frame, and a small negative delta on the logic frame. The negative
delta reads as about 4.29e6 s, and the period reduction turns that into a quasi-random jump every
logic frame. The jump does not depend on `SnowSpeed`, so lowering the map's snow speed changed
nothing.

Measured live 2026-10-27 on `map kampa evil 06`:
- The snow time only ever held multiples of 0.5, which is what float32 keeps at a magnitude of 2^32.
- Lowering `SnowSpeed` to 5 (confirmed loaded in memory) left the visible speed unchanged.
- Snow falls at the authored speed with the accelerator off, and with `[Engine] SmoothAnimation = 0`
  in `bfme2_accel.ini`.

Every other reader of that delta that runs between `lrDecide` and the draw sees the same pair of
bad steps. The readers after the setter were wrong too: the setter copied the nudged value into
previous, so they saw 33 + 17 ms in each 33 ms logic interval.

**The fix** is in the accelerator fork (branch `edain-compat`, `lrClockSet` / `lrSetClock` in
`aotr_logicrate.inc`; built 2026-10-27, not yet played):
- Each frame the DLL writes both values. Current is the engine's own value, plus the elapsed share
  on a render-only frame. Previous is the value the readers saw the frame before, never ahead of
  current.
- The setter call at `0x0044B925` is redirected to a wrapper. It puts the engine's own value back,
  then calls `0x00516E20`.

A frame-by-frame model of the scheduler gives these deltas per frame:

| readers | old code | fixed |
|---|---|---|
| before the draw | +49, −16, … | +16, +17, … (33 per logic frame) |
| after the setter | 33, 17, … | 0, 33, … (stock exactly) |

## 6. Still open

- **The last two readers of the frame length**, `0x0044B8DD` (`add`) and `0x0044B911` (`mov`),
  are not camera code and are left as they are; what they time is not established.
- **The spellbook** opening with nothing purchasable is `render-rate.md` §9.6, now its own patch
  `spell-store-deferral`. Apply it beside this one.
- **Live confirmation** of all three fixes: ships hold their tilt, scripted camera moves (the
  victory spin, the shellmap) take their scripted time with the accelerator on and off, and a
  fade blends without steps.
