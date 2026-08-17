# The camera — `TheTacticalView`, and driving it from outside the process

Recovered from RotWK 2.01 `game.dat` (ImageBase `0x400000`), 2026-08-06, statically with
`pefile` + `capstone` via [`../scripts/pe.py`](../scripts/pe.py). Shipped as the camera half of
[`../patches/experimental/live_bridge.py`](../patches/experimental/live_bridge.py) and `sage_live`'s
`Session.look_at` / `Session.camera`.

**Verdict up front.** A camera *move* is **a twelve-byte write to one field** — no call, no
command slot, no acknowledgement — and it is by far the cheapest thing in this repository to
write into a running game: nothing in the simulation reads the camera, so unlike an order it
cannot desync a match, cannot be discarded by logic, and needs no place in the message stream at
all. Reading the camera, and restoring a whole saved placement, do go through the virtual pair
below. **Re-aiming must not** — §6 has the measurements for why.

## 1. Do not look for a camera message

`MSG_SET_REPLAY_CAMERA` (`0x447`) exists and is emitted every frame from `0x0083BA86`:

```asm
0083ba7a  push edx                       ; a ViewLocation on the stack
0083ba7e  mov  eax, [ecx]
0083ba80  call [eax + 0x170]             ; view->getLocation(&loc)
0083ba86  mov  ecx, [0x00DE6398]         ; TheMessageStream
0083ba8e  push 0x447                     ; MSG_SET_REPLAY_CAMERA
0083ba93  call [eax + 0x48]              ; appendMessage
0083ba9e  call 0x71115c                  ;   the position
0083baac  call 0x7110ea                  ;   then four floats
```

That is telemetry **out** — the emit is gated on `TheWritableGlobalData+0xB70` and on
`TheRecorder`'s mode, and it is what puts a camera track in a replay. It is not a way in, and
routing a camera move through the order path would be the wrong shape anyway: the message
stream is the *logic* thread's input queue, and the camera is not logic.

## 2. `TheTacticalView` is at `0x00DE447C`

Absent from [`engine-globals.md`](engine-globals.md) because it is not a registered subsystem —
`TheGameClient` builds it:

```asm
0069ef61  mov  eax, [esi]
0069ef65  call [eax + 0x1d8]             ; TheGameClient->createView()
0069ef6b  mov  [0x00DE447C], eax
0069ef70  mov  edx, [eax]
0069ef74  call [edx + 0x10]              ; view->init()
```

It has **423 xrefs**, and every one of them is in client code. That absence is the useful fact:
no logic path reads this object, which is why writing it is desync-safe where writing anything
the simulation touches would not be.

## 3. `getLocation` / `setLocation`, at vtable `+0x170` and `+0x174`

The pair is pinned by the camera-bookmark hotkeys, which save and restore numbered slots out
of one array with a **32-byte stride**:

| site | what it does |
|---|---|
| `0x0083B294` | `lea edx,[edx + esi + 0x28]` with `shl edx, 5`, then `call [eax + 0x170]` — save slot *n* |
| `0x0083B420` | the same address arithmetic, then `call [edx + 0x174]` — restore slot *n* |

Both are `__thiscall` taking one pointer and **cleaning their own argument** (`ret 4`): the
engine's own call sites push and never adjust `esp`, which is what lets the cave call them from
inside a `pushad` without touching the stack itself.

The implementations are shared by two vtables (`0x00BDD490` and `0x00C0C330` — the base `View`
and the concrete `W3DView`), at `0x0065E90A` and `0x0065E980`.

## 4. `ViewLocation` — 32 bytes, and what each field is

Read straight out of `View::getLocation`, which fills the caller's struct from four virtual
accessors and the view's own position field:

```
+0x00  valid    dword   set to 1 by getLocation; setLocation returns immediately when clear
+0x04  pos      3 x float   copied to/from view+0x0C..0x14 by three MOVSDs
+0x10  angle    float   get [+0x100]  set [+0xFC]
+0x14  pitch    float   get [+0x108]  set [+0x104]
+0x18  zoom     float   get [+0x124]  set [+0x128]
+0x1C  ?        float   get [+0x110]  set [+0x10C]
```

**Each field is read from one accessor and written to another, and they are not the same
quantity** — so a captured location *cannot* be handed straight back. This was assumed for a
while and it is false; §7 has the measurements. The names rest on this:

- **`angle`.** The keyboard rotate keys read `+0x100`, add `TheWritableGlobalData+0xC2C`, and
  write `+0xFC` (`0x0083B9AB`–`0x0083B9C6`; the subtract path is at `0x0083B979`). That field is
  `KeyboardCameraRotateSpeed`, named from the `GlobalData` field-parse table entry at
  `0x00C00860`. This one is ground truth.
- **`pitch`.** Driven by the vertical axis of the same mouse drag whose horizontal axis drives
  `angle`: `0x0083B1A6` takes an integer delta, scales it by `0.01` (`0x00BE5600`), adds it to
  `+0x108` and writes `+0x104`.
- **`zoom`.** A camera reset writes `1.0` into `+0x128` (`fld1` at `0x0062C367`), and a scripted
  pull-back writes `2.2` (`0x00BFDB48`). A multiplier reset to one, not a distance.
- **The fourth is unnamed on purpose.** Its accessor pair `+0x10C`/`+0x110` is called from
  **nowhere else in the image** — only from inside `getLocation` and `setLocation` — so nothing
  in the binary says what it means. `sage_live.ViewLocation` carries it as `extra` and never
  alters it.

`setLocation` finishes with `call [eax+0x50]`, so the view does whatever recomputation it needs
itself; nothing here has to know how the camera matrix is built.

## 5. What the patch adds

A second command slot in the `.livebrg` buffer, served by the same `GameLogic::update` hook the
orders use:

```
tag       dword   BUFFER_TAG - the layout this cave was built to
camera    dword   1 = apply the location, 2 = fill it from the view; cleared when served
location  32 bytes ViewLocation
```

Three things about it are deliberate.

**It rides in the existing hook rather than getting its own.** The engine ticks logic and
client from one loop on one thread, so the view is reachable from where `GameLogic::update`
runs. If that ever stops being true, the natural second site is the client camera update at
`~0x0083B9A0` — the function above, which already calls the view's accessors every frame.

**Both directions, not just the write.** Capture is what makes "look over there" a
read-modify-write: the zoom, facing and tilt in a location belong to whoever is at the
keyboard, and a re-aim that also resets them would fight them and look nothing like the game
it is filming. It is also the only way to see what the view did with a placement, since the
map's own camera limits clamp it.

**No view means the flag stays set.** A camera command issued at a loading screen is left
pending rather than dropped, because unlike an order it is not stale a frame later. The writer
times out and says so.

**The tag** is the one thing the "import the offsets from the patch module" rule cannot cover:
it keeps a writer and a cave consistent within one process, but says nothing about a `game.dat`
patched by an older version. `BridgeBackend.connect` refuses a tag it does not know, because
every offset it would write at points somewhere else in that older cave — and the nearest thing
to the camera block there is the appender table the hook calls through.

## 6. Confirmed live

Run against a live RotWK match, 2026-08-07 (`m_pos` at `view+0x0C`, `TheTacticalView` resolving
to `0x069D1200`). The headline is that *capture, replace the position, hand it back* does not
work at all.

**A round-trip is not a no-op.** Handing `setLocation` the location `getLocation` had just
produced changed the zoom:

```
capture           zoom 1.281116
echo it back      zoom 1.234136      <- moved by -0.047
echo again x17    zoom 1.234136      no further change
```

It is a clamp, not a drift: the first write moves it and the next seventeen are exact no-ops.
Asking for the captured value back is refused every time. A sweep over fourteen zooms shows the
setter saturating at `1.234136` for anything ≥ 1.0, and **all of them relaxing back to
`1.281116` within 0.6 s** — the client restoring its own resting value:

```
asked      immediate   after 0.6s
0.250000    1.033789    1.281034
1.000000    1.234136    1.281116
1.281116    1.234136    1.281116     <- the reported value, refused
3.000000    1.234136    1.281116
```

That is the whole of the "camera zooms in and snaps back" symptom, and it is unavoidable
through this call: §4's accessor pairs are read-here/write-there, so there is no value that
makes `setLocation` a no-op.

**Writing `m_pos` alone moves the camera, with no call and no patch.** The three floats at
`view+0x0C` are the same ones `getLocation` reports, and writing them directly moves the view —
confirmed on screen — while `zoom` stays at `1.281116` throughout. The recompute at `[eax+0x50]`
that `setLocation` makes afterwards is **not** required; the client picks the position up on its
own. `sage_live`'s `BridgeBackend.move_camera` is this, and `Session.look_at` uses it whenever
no scalar is being overridden.

**And it is fast enough to pan with.** A raw write is twelve bytes with no command slot, no hook
and no acknowledgement, so it is not bounded by the logic frame rate. A clock-driven loop
achieved **162 writes/second** with a p95 gap of 7 ms and rendered as a smooth pan. Two things
were needed for that: driving the interpolation off elapsed wall time rather than a step counter
(so a late tick lands where the camera should be *now*), and asking for a 1 ms timer period.
Coarser steps do not read as motion — a 250 ms step was described as snapping between locations,
and one step per two-second policy cycle is a jump every two seconds however small the step.

**`position` is the look-at point on the terrain**, not the camera's eye. A camera reporting
`z=150.00` sat over 137 objects whose median `z` was `150.00`. The camera's own altitude is
derived from this point plus the zoom and pitch, and does not appear in `ViewLocation` at all.

**The zoom is derived, which is why it cannot be written.** Panning the camera 700 units
north-east and back, writing only `m_pos`, moved the reported zoom to `1.258015` and then
returned it to `1.281113` — the engine maintaining its own value as a function of where the
camera now is. Nothing wrote it in either direction. A value captured at one position is
therefore not even meaningful at another, and the relaxation measured above is this same
mechanism reasserting itself after a write.

## 7. What is still open

- **The fourth scalar is unnamed** (§4).
- **The engine's own interpolated move is still unidentified** — the `CAMERA_MOVE_TO_LOCATION`
  script action drives some other View slot. It matters little: easing from outside at 160 Hz
  looks right, bar occasional stutters.
- **What restores the zoom over 0.6 s has not been traced.** The behaviour is pinned by
  measurement and routed around; the field doing the restoring is not identified. Likely the
  client's per-frame camera update at `~0x0083B9A0`.
- **Whether `[eax+0x50]` is ever needed.** Skipping it works for position; a patch-side
  position-only command that also calls it remains the fallback if some map or camera mode
  turns out to render from a cached matrix.
