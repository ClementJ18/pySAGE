"""Rendering and frame pacing: draw modules, render scopes, the client frame rate."""

from __future__ import annotations

__all__ = [
    "ALPHA_RECOMPUTE",
    "ALPHA_RECOMPUTE_BODY",
    "ALPHA_RECOMPUTE_BODY_BYTES",
    "ALPHA_RECOMPUTE_ENTRY",
    "D3DPERF_MODULE_HANDLE",
    "D3DPERF_RESOLVE_ANCHOR",
    "D3DPERF_RESOLVE_ANCHOR_BYTES",
    "D3DPERF_SETOPTIONS_STORE",
    "D3DPERF_SETOPTIONS_STORE_ENTRY",
    "D3DPERF_SETOPTIONS_STORE_RESUME",
    "D3DPERF_SET_OPTIONS_PTR",
    "DIRECT3D_CREATE9_PTR",
    "DIRECT3D_CREATE9_RESOLVE",
    "DIRECT3D_CREATE9_RESOLVE_BYTES",
    "DIRECT3D_CREATE9_STORE",
    "DIRECT3D_CREATE9_STORE_ENTRY",
    "DIRECT3D_CREATE9_STORE_RESUME",
    "DISPLAY_DRAW_VTABLE_SLOT",
    "DRAWABLE_GET_SCALE",
    "DRAWABLE_GET_SCALE_BYTES",
    "DRAWABLE_GET_SCALE_OTHER_CALLS",
    "OBJECT_GET_RADAR_PRIORITY",
    "OBJECT_GET_RADAR_PRIORITY_BYTES",
    "PERF_BEGIN_EVENT",
    "PERF_BEGIN_EVENT_BYTES",
    "PERF_D3D_BEGIN_EVENT_PTR",
    "PERF_D3D_END_EVENT_PTR",
    "PERF_END_EVENT",
    "PERF_END_EVENT_BYTES",
    "PERF_SCOPE_CTOR",
    "PERF_SCOPE_CTOR_BYTES",
    "PERF_SCOPE_CTOR_ENTRY",
    "PERF_SCOPE_CTOR_OBJECT_SETUP",
    "PERF_SCOPE_CTOR_OBJECT_SETUP_BYTES",
    "PERF_SCOPE_CTOR_RESUME",
    "PERF_SCOPE_DTOR",
    "PERF_SCOPE_DTOR_ENTRY",
    "PERF_SCOPE_NULL_EXIT",
    "PERF_SCOPE_NULL_EXIT_BYTES",
    "PERF_SCOPE_NULL_GATE",
    "PERF_SCOPE_NULL_GATE_ENTRY",
    "PERF_SCOPE_NULL_GATE_RESUME",
    "PERF_SCOPE_NULL_GATE_RESUME_BYTES",
    "PERF_SCOPE_STAGE_SITE",
    "PERF_SCOPE_STAGE_SITE_BYTES",
    "PERF_SCOPE_STRNCPY_IAT",
    "RADAR_BLIP_COLOUR",
    "RADAR_BLIP_KINDOF_LOAD",
    "RADAR_BLIP_KINDOF_SEQUENCE",
    "RADAR_BLIP_KINDOF_SEQUENCE_BYTES",
    "RADAR_CIRCLE_MIN_RADIUS",
    "RADAR_CIRCLE_MIN_RADIUS_STOCK",
    "RADAR_CIRCLE_RADIUS",
    "RADAR_CIRCLE_RADIUS_BYTES",
    "RADAR_CIRCLE_SPAN_CALLS",
    "RADAR_CIRCLE_SPAN_LOOP",
    "RADAR_CIRCLE_SPAN_LOOP_BYTES",
    "RADAR_KINDOF_COMMANDCENTER",
    "RADAR_PIXEL_IN_BOUNDS",
    "RADAR_PIXEL_IN_BOUNDS_BYTES",
    "RADAR_PLOT_SPAN_ENDS",
    "RADAR_PLOT_SPAN_ENDS_BYTES",
    "RADAR_PRIORITY_STRUCTURE",
    "SURFACE_DRAW_PIXEL",
    "THE_DISPLAY",
    "W3D_HORDE_MODEL_DRAW_SET_MODEL_STATE_SCALE_CALLS",
    "W3D_HORDE_MODEL_DRAW_SET_MODEL_STATE_THIS",
    "W3D_MODEL_DRAW_BIRTH_FADE_ADDITIVE",
    "W3D_MODEL_DRAW_BIRTH_FADE_DEFAULT",
    "W3D_MODEL_DRAW_BIRTH_FADE_DEFAULT_BYTES",
    "W3D_MODEL_DRAW_BONE_UPDATE_SCALE_CALL",
    "W3D_MODEL_DRAW_BONE_UPDATE_THIS",
    "W3D_MODEL_DRAW_DERIVED_TABLE_REFS",
    "W3D_MODEL_DRAW_DO_DRAW",
    "W3D_MODEL_DRAW_FIELD_TABLE",
    "W3D_MODEL_DRAW_FIELD_TABLE_REF",
    "W3D_MODEL_DRAW_IFACE_SLOT3_SCALE_CALL",
    "W3D_MODEL_DRAW_IFACE_SLOT3_THIS",
    "W3D_MODEL_DRAW_IFACE_SLOT6_MODULE_DATA",
    "W3D_MODEL_DRAW_IFACE_SLOT6_SCALE_CALL",
    "W3D_MODEL_DRAW_MODULE_DATA_SIZE",
    "W3D_MODEL_DRAW_SET_MODEL_STATE_SCALE_CALLS",
    "W3D_MODEL_DRAW_SET_MODEL_STATE_THIS",
    "W3D_MODEL_DRAW_STATIC_SORT_LEVEL",
    "W3D_MODEL_DRAW_TRANSFORM_CALLS",
    "W3D_MODEL_DRAW_TRANSFORM_HELPER",
    "W3D_MODEL_DRAW_TRANSFORM_HELPER_BYTES",
]

# `TheDisplay` and the one call that draws a frame (`GameClient::update`'s `draw`, through vtable
# `+0x30`). Its 540 unchecked references are why headless mode suppresses drawing rather than the
# display.
THE_DISPLAY = 0x00DE4418
DISPLAY_DRAW_VTABLE_SLOT = 0x30
#: `GameEngine::recomputeAlpha` - `+0x3C = clamp(+0x34 / +0x38, 0, 1)`, called from `0x00632642`,
#: `0x006326BE`, `0x006326E4` and `0x00632AF0`, all inside the pacing loop. Nothing branches into
#: its body, so the five-byte `cvtsi2ss` at its head is a whole hook window.
ALPHA_RECOMPUTE = 0x0063256F
ALPHA_RECOMPUTE_ENTRY = bytes.fromhex("f30f2a4938")
#: The 44 bytes after the hook window: the second convert, the divide, and the two-sided clamp
#: that pins the result into `[0, 1]`. Anchored, never written - a build that computes the alpha
#: some other way is not the build this is a correction for.
ALPHA_RECOMPUTE_BODY = 0x00632574
ALPHA_RECOMPUTE_BODY_BYTES = bytes.fromhex(
    "f30f2a4134f30f5ec10f57c90f2fc8f30f11413c770df30f100d0819bd000f2fc176030f28c1f30f11413cc3"
)
# An object's `Scale` as the model draw modules read it, and the padding in their shared
# `ModuleData` a per-module factor fits in. Derived in `docs/draw-module-scale.md`.

#: `Drawable::getScale` - `__thiscall`, no arguments, `fld dword [ecx+0x200]` then `ret`. The
#: `Drawable` constructor copies `ThingTemplate+0x4F0` there once (`0x00679FE2`) and nothing
#: rewrites it. It has 22 callers: the 19 model draw calls below and
#: `DRAWABLE_GET_SCALE_OTHER_CALLS`.
DRAWABLE_GET_SCALE = 0x00478180
DRAWABLE_GET_SCALE_BYTES = bytes.fromhex("d98100020000c3")
#: The three `getScale` calls outside the model draw family: a draw class with vtable
#: `0x00BDF700`, an unrelated vtable slot at `0x00BE3258`, and a routine handed the drawable
#: directly. None of them holds a `W3DModelDrawModuleData`.
DRAWABLE_GET_SCALE_OTHER_CALLS = (0x004B1883, 0x004CE7ED, 0x004D137A)
#: The field table every model draw module parses - `W3DScriptedModelDraw`, `W3DHordeModelDraw`,
#: `W3DQuadrupedDraw`, `W3DSupplyDraw`, `W3DTruckDraw`, `W3DTankDraw`, `W3DSailModelDraw` - and
#: its one reference, the `push` in the shared `buildFieldParse` (`0x004C893A`).
W3D_MODEL_DRAW_FIELD_TABLE = 0x00BE1320
W3D_MODEL_DRAW_FIELD_TABLE_REF = 0x004C8940
#: The `push` of each derived module's own field table, which the reader searches alongside the
#: shared one: Horde, Quadruped, Supply, Truck, Tank, Sail.
W3D_MODEL_DRAW_DERIVED_TABLE_REFS = (
    0x00478C7A,
    0x004C97B1,
    0x004CA611,
    0x004CA92B,
    0x004CD79A,
    0x004CFF77,
)
#: `W3DModelDrawModuleData`'s `sizeof`, where every derived module's own fields start - which is
#: why it cannot grow. `BirthFadeAdditive` is a one-byte `Bool` and `StaticSortLevelWhileFading`
#: the next dword, so `+0x155..+0x157` is padding no row names.
W3D_MODEL_DRAW_MODULE_DATA_SIZE = 0x188
W3D_MODEL_DRAW_BIRTH_FADE_ADDITIVE = 0x154
W3D_MODEL_DRAW_STATIC_SORT_LEVEL = 0x158
#: The `BirthFadeAdditive` default in the `ModuleData` constructor (`0x004C85E9`, which all seven
#: model draw constructors run): `mov byte [esi+0x154], bl`, with `ebx` zero for the whole body.
W3D_MODEL_DRAW_BIRTH_FADE_DEFAULT = 0x004C8730
W3D_MODEL_DRAW_BIRTH_FADE_DEFAULT_BYTES = bytes.fromhex("889e54010000")
#: `W3DModelDraw::setModelState` (`0x004C451D`) and `W3DHordeModelDraw`'s own copy of it
#: (`0x0047A0AD`): the `mov esi, ecx` that keeps the module in `esi` for the whole body, and the
#: eight `getScale` calls in each.
W3D_MODEL_DRAW_SET_MODEL_STATE_THIS = 0x004C452E
W3D_MODEL_DRAW_SET_MODEL_STATE_SCALE_CALLS = (
    0x004C4661,
    0x004C482B,
    0x004C48E2,
    0x004C4AB7,
    0x004C4ADB,
    0x004C4B3D,
    0x004C4C9E,
    0x004C4DFF,
)
W3D_HORDE_MODEL_DRAW_SET_MODEL_STATE_THIS = 0x0047A0C4
W3D_HORDE_MODEL_DRAW_SET_MODEL_STATE_SCALE_CALLS = (
    0x0047A181,
    0x0047A30A,
    0x0047A3CA,
    0x0047A52A,
    0x0047A54E,
    0x0047A5AE,
    0x0047A68F,
    0x0047A77E,
)
#: `ObjectDrawInterface` slot 6 (`0x004C34A2`), entered on the module's `+0xC` sub-object: the
#: `mov edi, [esi-8]` that loads the `ModuleData`, and its `getScale` call.
W3D_MODEL_DRAW_IFACE_SLOT6_MODULE_DATA = 0x004C34DC
W3D_MODEL_DRAW_IFACE_SLOT6_SCALE_CALL = 0x004C34E4
#: `ObjectDrawInterface` slot 3 (`0x004C3731`): the `mov edi, ecx` that keeps the sub-object, and
#: its `getScale` call.
W3D_MODEL_DRAW_IFACE_SLOT3_THIS = 0x004C3746
W3D_MODEL_DRAW_IFACE_SLOT3_SCALE_CALL = 0x004C3789
#: The per-frame bone update (`0x004C6514`, called only from the model draw's slot 11 at
#: `0x004C7790`): the `mov ebx, ecx` that keeps the module, and its `getScale` call.
W3D_MODEL_DRAW_BONE_UPDATE_THIS = 0x004C6525
W3D_MODEL_DRAW_BONE_UPDATE_SCALE_CALL = 0x004C6909
#: The helper every model draw runs on the matrix immediately before handing it to its render
#: object's `Set_Transform` - `__thiscall(Matrix3D *)`, `ret 4`, which overrides the matrix when
#: the module is attached to another module's bone and otherwise leaves it as the caller filled
#: it. Its five call sites are every place a model draw positions what it draws; each is
#: `mov ecx, <the module>` then a five-byte `call`.
W3D_MODEL_DRAW_TRANSFORM_HELPER = 0x004B686D
W3D_MODEL_DRAW_TRANSFORM_HELPER_BYTES = bytes.fromhex("558bec83ec3453")
W3D_MODEL_DRAW_TRANSFORM_CALLS = (0x004B79AA, 0x004B7CD8, 0x004B8A14, 0x004B988A, 0x004C76D0)
#: The per-frame one of those five, in the draw the whole family shares (`0x004C72BE`: vtable slot
#: 11 of five model draw vtables, and called directly by `W3DTruckDraw` (`0x004CC008`) and
#: `W3DTankDraw` (`0x004CDECE`)).
W3D_MODEL_DRAW_DO_DRAW = 0x004C72BE
#: The engine's named render-scope class (thirty per frame). The name is only a `.rdata` pointer in
#: the constructor, which is why the hook is there. See `docs/perf-stage-readout.md`.
PERF_SCOPE_CTOR = 0x00517690
#: `mov eax, [esp+4]` / `test eax, eax` - the six displaced bytes. The `test` sets the flags the
#: `je` at `0x00517699` reads, so a cave must re-run both and jump back with them fresh.
PERF_SCOPE_CTOR_ENTRY = bytes.fromhex("8b44240485c0")
PERF_SCOPE_CTOR_RESUME = 0x00517696
#: The constructor's identity: `eax` is the name, `esi` becomes the object. **It stops one
#: instruction short of the `je` at `PERF_SCOPE_NULL_GATE` on purpose** - that is
#: `perf-scope-skip`'s hook site, and an anchor reaching into it would make the two patches
#: refuse each other depending on which was applied first.
PERF_SCOPE_CTOR_BYTES = bytes.fromhex("8b44240485c0568bf1")
#: `push esi` / `mov esi, ecx` - the constructor establishing the object, and the first bytes of
#: it that `perf-stage-readout`'s six-byte hook does **not** overwrite. `perf-scope-skip` anchors
#: here rather than at `PERF_SCOPE_CTOR` for exactly that reason: it has to hold whichever of the
#: two patches was applied first. It is also the instruction the skip path depends on - the exit it
#: jumps to ends `pop esi`, which only balances because the entry pushed it.
PERF_SCOPE_CTOR_OBJECT_SETUP = 0x00517696
PERF_SCOPE_CTOR_OBJECT_SETUP_BYTES = bytes.fromhex("568bf1")
#: `je PERF_SCOPE_NULL_EXIT` - the constructor's "this scope has no name, do nothing" branch, and
#: `perf-scope-skip`'s hook. Six bytes of near `jcc`, reached with the flags from the `test` at
#: `0x00517694` still live, `eax` the name and `esi` the object.
PERF_SCOPE_NULL_GATE = 0x00517699
PERF_SCOPE_NULL_GATE_ENTRY = bytes.fromhex("0f8492000000")
#: Where the stock body begins, i.e. where a cave jumps when it decides to let the scope run.
PERF_SCOPE_NULL_GATE_RESUME = 0x0051769F
PERF_SCOPE_NULL_GATE_RESUME_BYTES = bytes.fromhex("55578b3d2406")
#: The constructor's own do-nothing exit: `mov eax, esi` / `pop esi` / `ret 0xC`. It returns the
#: object and unwinds the one `push esi` the entry made, which is exactly the ABI a skipped scope
#: needs - so `perf-scope-skip` jumps here rather than assembling its own return.
PERF_SCOPE_NULL_EXIT = 0x00517731
PERF_SCOPE_NULL_EXIT_BYTES = bytes.fromhex("8bc65ec20c00")
#: `msvcr71!strncpy` in the IAT, which the scope constructor calls twice per scope. The first call
#: passes `n = 0x100` and `strncpy` **pads to `n`**, so it writes 256 bytes whatever the name's
#: length; the second passes `0x40 - len`. That is the cost `perf-scope-skip` removes.
PERF_SCOPE_STRNCPY_IAT = 0x00BD0624
#: Where the engine stores `D3DPERF_SetOptions`, the last of the four D3DPERF resolves, and
#: `perf-scope-skip`'s second hook: the first point at which `d3d9.dll` is loaded, its handle is in
#: `D3DPERF_MODULE_HANDLE` and nothing else is half-initialised. The patch re-runs the displaced
#: store and then asks `D3DPERF_GetStatus` whether anyone is actually listening.
D3DPERF_SETOPTIONS_STORE = 0x00525202
D3DPERF_SETOPTIONS_STORE_ENTRY = bytes.fromhex("a32836dd00")
D3DPERF_SETOPTIONS_STORE_RESUME = 0x00525207
#: Where the engine stores the `Direct3DCreate9` it has just resolved from `d3d9.dll`, and the
#: `accel-module` patch's hook: the one moment the renderer's entry point passes through a writable
#: slot before first use, on the game thread, with `d3d9.dll` already loaded. The cave re-runs the
#: store, then loads `bfme2_accel.dll`.
DIRECT3D_CREATE9_STORE = 0x00525199
DIRECT3D_CREATE9_STORE_ENTRY = bytes.fromhex("a31436dd00")
#: The `je` that tests the resolve's result. It reads the flags of the `cmp eax, ebx` *before* the
#: store, which is why the cave must hand them back untouched.
DIRECT3D_CREATE9_STORE_RESUME = 0x0052519E
#: The slot, called once at `0x00525209` as `Direct3DCreate9(D3D_SDK_VERSION)`.
DIRECT3D_CREATE9_PTR = 0x00DD3614
#: From the `"Direct3DCreate9"` push to the `je`: the resolve, the flag-setting compare the resume
#: depends on, the store, and the branch that reads those flags.
DIRECT3D_CREATE9_RESOLVE = 0x0052518F
DIRECT3D_CREATE9_RESOLVE_BYTES = bytes.fromhex("68f471be0050ffd63bc3a31436dd007478")
#: The whole resolve tail, from the module-handle load to the call past the hook.
D3DPERF_RESOLVE_ANCHOR = 0x005251F5
D3DPERF_RESOLVE_ANCHOR_BYTES = bytes.fromhex("a11036dd00689071be0050ffd6a32836dd006a20ff151436dd00")
#: The `d3d9.dll` module handle the four D3DPERF resolves are taken from, and the slot the last of
#: them lands in.
D3DPERF_MODULE_HANDLE = 0x00DD3610
D3DPERF_SET_OPTIONS_PTR = 0x00DD3628
#: `PerfScope::~PerfScope`, which is nothing but a five-byte tail jump to `PERF_END_EVENT`. Thirty
#: callers, pairing one-for-one with the constructor's thirty. Being exactly one jump makes it the
#: cleanest hook in the pair: there are no displaced instructions to re-run.
PERF_SCOPE_DTOR = 0x00517740
PERF_SCOPE_DTOR_ENTRY = bytes.fromhex("e91b760000")
#: The two D3DPERF wrappers the scope class drives. `PERF_BEGIN_EVENT` widens the ASCII name into
#: a `0x200`-byte stack buffer and calls through `PERF_D3D_BEGIN_EVENT_PTR`; `PERF_END_EVENT` is a
#: null test and a tail jump through `PERF_D3D_END_EVENT_PTR`. Both do nothing when the pointer is
#: null, which is what makes the stage events free to the engine and invisible without a consumer.
PERF_BEGIN_EVENT = 0x0051ECE0
PERF_BEGIN_EVENT_BYTES = bytes.fromhex("81ec00020000568b351c36dd00")
PERF_END_EVENT = 0x0051ED60
PERF_END_EVENT_BYTES = bytes.fromhex("a12036dd0085c07501c3ffe0")
#: `D3DPERF_BeginEvent` / `D3DPERF_EndEvent`, resolved out of `d3d9.dll` at `0x005251D7` and
#: `0x005251EA` and cleared again at `0x00525844` / `0x0052584A`. Zero in the file; non-null in a
#: running game, because `d3d9.dll` always exports them. `perf-stage-readout` does not touch
#: either - it measures the scope, not the event - but they are what the scope exists to drive.
PERF_D3D_BEGIN_EVENT_PTR = 0x00DD361C
PERF_D3D_END_EVENT_PTR = 0x00DD3620
#: `UpdateShadowMap`'s scope, planted whole as the proof of the calling convention: `push colour`
#: / `push "Frame"` / `push "UpdateShadowMap"` / `lea ecx, [ebp-0x158]` / `call PERF_SCOPE_CTOR`.
#: What entitles the cave to read the name off `[esp+4]` is this sequence, not the constructor's
#: own first instruction.
PERF_SCOPE_STAGE_SITE = 0x00449DCF
PERF_SCOPE_STAGE_SITE_BYTES = bytes.fromhex("5368fc9dbd0068ec9dbd008d8da8feffffe8abd80c00")

# The minimap blip painter: the per-object body of the radar draw loop, which walks the radar
# object list and paints each object onto the 128x128 radar surface. It picks one of three shapes
# from the template's KindOf: WALL_SEGMENT fills the geometry footprint, COMMANDCENTER draws a
# circle of radius `floor(boundingRadius * scale + 0.5)` (at least 2), and everything else is a
# fixed 2x2 dot. Derived in `docs/radar-structure-discs.md`.

#: `Object::getRadarPriority` - `__thiscall`, no arguments. Returns the template's `RadarPriority`
#: byte (`ThingTemplate+0x600`), and for `INVALID` (0) falls back to `STRUCTURE` (2) when the
#: template is `KindOf CAPTURABLE` or the object's contain module answers yes at vtable `+0x10`.
#: Preserves `esi`, `edi` and `ebx`.
OBJECT_GET_RADAR_PRIORITY = 0x0068EBE9
OBJECT_GET_RADAR_PRIORITY_BYTES = bytes.fromhex(
    "568bf18b4604570fbeb80006000085ff75258b8e5802000085c9740c8b01ff501084c074036a025f"
    "8b4604f6800e0100000274036a025f8bc75f5ec3"
)
#: `RadarPriorityType::STRUCTURE`, as `OBJECT_GET_RADAR_PRIORITY` returns it: index 2 of the name
#: table at `0x00DA3B24` (`INVALID`, `NOT_ON_RADAR`, `STRUCTURE`, `UNIT`, `LOCAL_UNIT_ONLY`).
RADAR_PRIORITY_STRUCTURE = 2
#: `KindOf COMMANDCENTER` is index 17, so it is bit 17 of the first KindOf dword.
RADAR_KINDOF_COMMANDCENTER = 17
#: The painter reading the first KindOf dword into `ebx` and keeping bit 17 in `bl`, which picks
#: the circle. `edi` is the `Object*` and `eax` its `ThingTemplate*`:
#: `mov edi,[esi+4]; mov eax,[edi+4]; mov ebx,[eax+0x108]; push [ebp-0x28]; shr ebx,0x11;
#: mov ecx,edi; and bl,1; call 0x0068D8F7`. `RADAR_BLIP_KINDOF_LOAD` is the six-byte `mov ebx`.
RADAR_BLIP_KINDOF_SEQUENCE = 0x0044FA73
RADAR_BLIP_KINDOF_SEQUENCE_BYTES = bytes.fromhex(
    "8b7e048b47048b9808010000ff75d8c1eb118bcf80e301e868de2300"
)
RADAR_BLIP_KINDOF_LOAD = 0x0044FA79
#: The circle's radius: `fld [edi+0xb8]` (the bounding radius), `push 2`, `fmul [ebp-0x20]`,
#: `pop ebx`, then `floor(r * scale + 0.5)` - and `ebx`, the popped 2, is the smallest radius the
#: painter lets through. `RADAR_CIRCLE_MIN_RADIUS` is that `push`'s imm8.
RADAR_CIRCLE_RADIUS = 0x0044FC51
RADAR_CIRCLE_RADIUS_BYTES = bytes.fromhex("d987b80000006a02d84de05b5151d8059c86bd00")
RADAR_CIRCLE_MIN_RADIUS = 0x0044FC58
RADAR_CIRCLE_MIN_RADIUS_STOCK = 2
#: The circle's first pass. `0x006E0AE4` has already rasterised the circle into 12-byte spans
#: `{row, a, b}`, and for each span this loop sets `esi` to the row, then to the row mirrored
#: about the centre, and calls `RADAR_PLOT_SPAN_ENDS` with `(a, b, &surface)` both times.
RADAR_CIRCLE_SPAN_LOOP = 0x0044FCB3
RADAR_CIRCLE_SPAN_LOOP_BYTES = bytes.fromhex(
    "8b378d45ec50ff7708ff7704e84de1ffff8b75dc2b378d45ec50ff7708ff7704e839e1ffff8b0383c418"
    "3b070f4cdf83c70c3b7dac75c9"
)
#: The two calls in `RADAR_CIRCLE_SPAN_LOOP`, and nothing else calls the routine they reach.
RADAR_CIRCLE_SPAN_CALLS = (0x0044FCBF, 0x0044FCD3)
#: Plots only the two ends of a span, `(a, row)` and `(b, row)`, with `row` in `esi`, which is
#: why a COMMANDCENTER circle comes out hollow. `cdecl`, `(a, b, surface)`.
RADAR_PLOT_SPAN_ENDS = 0x0044DE11
RADAR_PLOT_SPAN_ENDS_BYTES = bytes.fromhex(
    "558bec56ff7508e886ffffff84c059597412ff353877dc008b4d1056ff7508e8ab870c0056ff750ce865ffffff"
    "84c059597412ff353877dc008b4d1056ff750ce88a870c005dc3"
)
#: `cdecl (x, y) -> al`: true when both lie in `[0, 128)`. Touches only `eax`.
RADAR_PIXEL_IN_BOUNDS = 0x0044DDA3
RADAR_PIXEL_IN_BOUNDS_BYTES = bytes.fromhex(
    "837c2404007c1b837c2408007c14b880000000394424047d09394424087d03b001c332c0c3"
)
#: The colour of the blip being drawn, written by the painter just before the circle passes.
RADAR_BLIP_COLOUR = 0x00DC7738
#: `SurfaceClass::DrawPixel(x, y, colour)` - `__thiscall` on the surface, callee-cleaned.
SURFACE_DRAW_PIXEL = 0x005165E0
