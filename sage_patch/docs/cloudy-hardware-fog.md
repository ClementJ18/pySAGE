# Hardware fog renderer: timing, object colors and native mesh policy

Author: **Ostkannit**. RotWK **2.01.2614.37001**, ImageBase `0x00400000`.
The shared implementation is `sage_patch/patches/experimental/cloudy_hardware_fog.py`.
The experimental [FOGGY patch](foggy-weather.md) applies it to native FOGGY=6.
The experimental `cloudy-hardware-fog` patch applies it to CLOUDY=1 and remains
available through `sage_patch.patches.experimental.cloudy_hardware_fog`.
These patches own the same hooks and cannot be combined.

The user has confirmed the FOGGY visual effect and real save/load with remaining
weather duration restored. That report covers the shared renderer in the tested
configuration; it does not establish every shader, vegetation batch or graphics option.
Standalone CLOUDY retains its experimental status. The native renderer code and cave
format are shared so Python/CLI integration does not alter its instruction stream.

## Configuration

The profile is optional and embedded when the patch is built. Current defaults are
**10000 simulation milliseconds** each for blend-in/out, RGB **0.70/0.76/0.80**, start
**725**, end **2000**. The archived first test binaries used explicit three-second
fades; they remain recognizable at those parameters.

```python
from sage_patch.patches import FoggyWeatherPatch

patch = FoggyWeatherPatch(
    blend_in_ms=3000,
    blend_out_ms=4500,
    fog_rgb=(0.70, 0.76, 0.80),
    fog_start=725.0,
    fog_end=2000.0,
)
```

`CloudyHardwareFogPatch` accepts the same arguments. Durations must be integer values
in **1..600000**. RGB has exactly three finite components in **0..1**. Finite distances
must satisfy **0 <= start < end <= 10000000** even after float32 conversion. Detection
reads the stored profile; manifests and rebuilds retain every parameter. The public
FOGGY API/CLI examples are in [Native FOGGY weather](foggy-weather.md).

## Object-rendering findings

Replacing the main scene fog cache alone does not cover the native object path:

1. `Customized_Render` and `renderOneObject` copy **Scene+0x20/24/28** to
   **RenderInfo+8/0C/10**. Mesh rendering carries this color to **Mesh+0x314**.
   Native FX preparation at `0x0054A0C9` then overwrites the FogColor cache with that
   original scene color. Terrain and FX objects can therefore receive different colors.
   Tests execute the native chain and reproduce the difference before the color hooks.
2. `DX8TextureCategoryClass::Render` checks **Mesh+0xBD (HardwareFog)**. False clears
   shader fog bits, and `ShaderClass::Apply` turns those bits into
   `D3DRS_FOGENABLE = false`. Prop setup at `0x004EE244` explicitly clears this flag
   under an option. This is a concrete independent NoFog path; it does not identify
   every visible model without runtime tracing.

While the blend weight is positive, three object-color hooks substitute the computed
RGB triple. The shroud-ghost path still applies native ClearAlpha/FogAlpha scaling.
Scene colors and mesh flags are not mutated, so subsequent frames retain original inputs.

The classic mesh path takes its existing HardwareFog=true branch during the same
interval. Native **`Enable_Fog("HardwareFog")`**, **`0x00537CE0`**, chooses normal fog
for opaque/alpha materials, black fog for additive/screen passes and white fog for
multiplicative passes. Already-selected fog modes and unsupported blends retain native
policy. Alpha test, blending, textures and techniques are not globally rewritten.

The preceding global-enable gate and `ShaderClass::Apply` capability checks remain.
Tests execute the native FogEnable (state 28) and FogColor (34) output paths. Start/end
(states 36/37) use the scene values. FX bindings at `0x0058B5C8`, `0x0058B5DF`,
`0x0058B65C`, `0x0058B675` read the same caches. A shader must actually consume those
fog inputs; the patch does not invent a new shader technique.

| Render path | Coverage | Limit |
| --- | --- | --- |
| Standard W3D meshes, buildings, props, mesh vegetation | Shared object color and native mesh fog policy | Not every model has been tested in game |
| FX and skinned meshes using this path | RenderInfo reaches Mesh+0x314 and FX FogColor | Existing shader must calculate fog |
| Alpha-tested, aligned and oriented meshes | Same TextureCategory decision; alpha test retained | Special billboards/shaders need separate checks |
| Shroud ghosts | Computed color with native shroud scaling | Brightness is intentionally not forced equal |
| Dedicated tree/shrub batches | Global profile remains available | No dedicated batch shader hook |
| Particles, water, special FX, UI | No universal fog enforcement | Targeted rendering tests remain necessary |

The separate `RenderTrees` path at `0x0046B20A` calls `0x004EC387` then batch pass
`0x004E5F64`. `RenderShrubs` at `0x0046B3BF` reaches `0x004E837E`. The Open-BFME-2
reference `Rva000E663BRenderPasses.cpp` describes their separate rendering-method/FX
pass stack, bypassing mesh TextureCategories. Compiled batch shaders were not decoded.
Setting FOGENABLE alone does not supply a fog factor in programmable vertex shaders;
see [Microsoft: Vertex Fog](https://learn.microsoft.com/en-us/windows/win32/direct3d9/vertex-fog).

## Simulation time and interpolation

The scheduler addresses identify the simulation clock; they are not millisecond getters
to call from rendering:

| Source | Meaning |
| --- | --- |
| `*0x00DE412C` (`THE_GAME_LOGIC`) | GameLogic singleton |
| `GameLogic+0x40` | Logical frame counter |
| `0x00850C32` / `0x0062B921` | Scheduler evidence for the same frame counter |
| `GameLogic+0x124` | Pause byte; getter `0x0090F92C`, caller `0x006329D4` |
| `*0x00DE4324`, then `+0x3C` | GameEngine render interpolation fraction |
| `0x00D9F608` | Live logical frames/second, 5 in the examined build |

Progress uses integer-frame deltas plus render-fraction deltas:
`deltaFrames / (logicRate * fadeMs / 1000)`. Ten simulation seconds at rate 5 equal
50 logic frames, independently of a 60-Hz client render rate. The fraction is clamped
into 0..1; without GameEngine interpolation, only whole logic ticks are used.
Absolute large frame numbers are never converted to float: modular integer subtraction
comes first, preserving precision in long games and across 32-bit wrap.

Repeated draws at the same logical time do not advance the blend. A fraction reset
within one tick cannot spend that tick twice. Pause freezes progress, and the first
draw after resume only resets the observation point. Game speed changes elapsed wall
time, while the requested simulation duration remains unchanged. Existing engine
interpolation is read, not replaced. No OS timer or new native call is introduced.

Phase `p` is clamped to 0..1; visible weight is smoothstep `p*p*(3-2*p)`. The selected
weather increases phase and other weather decreases it. Reversals retain phase and the
visible profile; a partial path takes proportionally less time to reach its endpoint.
Compensated float summation limits drift at high frame rates and long durations.
Endpoints within 1e-6 are completed, where smoothstep is already effectively saturated.

New singleton/GameLogic pointers, missing singletons or a backward time epoch reset
private state. The phase is not serialized. Loading may restart the visual blend while
the native weather timer is correctly restored. With identical pointers and the same
frame, this render hook alone cannot distinguish load from pause.

## Original fog enabled or disabled

With valid original fog enabled, RGB/start/end interpolate between the current original
values and the target. Native setup runs before every hook, so the last blended output
never becomes the next frame's original endpoint. Scene object values remain untouched.
An invalid or non-increasing original range takes the neutral path.

When original fog is disabled, its distances are not meaningful. For positive weight `a`:

```text
start(a) = targetStart
end(a)   = targetStart + min((targetEnd - targetStart) / a, 1e30)
```

At zero weight, original values and disabled enable-flag pass through unchanged. At
small positive weight, the end lies far away and approaches the target continuously;
full weight copies the exact target. A finite cap avoids infinite render parameters.
RGB still blends from the original scene color.

This follows the [linear Direct3D fog formula](https://learn.microsoft.com/en-us/windows/win32/direct3d9/fog-formulas):
the clamped contribution is `(distance-start)/(end-start)`. In the unsaturated region,
the chosen ramp scales the target slope by `a`. It is a range adjustment, not a universal
fog-alpha control: distant geometry can saturate earlier than with a separate alpha knob.

No assumed camera height is used as fog depth. Native clip getter `0x005337F0` reads
Camera `+0xEC/+0xF0`; view-plane getter `0x00533B40` reads `+0xD8..+0xE4`. A mod's
camera-height range does not prove its far clip. No speculative camera-layout pointers
are dereferenced; finite visible distances approach zero contribution as weight tends
to zero. Runtime camera/frustum values have not been measured by these tests.

## Hooks, state and ABI

| Hook VA | Original bytes | Purpose |
| --- | --- | --- |
| `0x00471913` | `A2 61 34 DD 00` | Scene fog cache submission; resume `0x00471918` |
| `0x0046FEC3` | `8B 4F 20 89 48 08 8B 4F 24 89 48 0C 8B 4F 28 89 48 10` | Scene object RGB |
| `0x0046F557` | `8B 4E 20 89 48 08 8B 4E 24 89 48 0C 8B 4E 28 89 48 10` | Single-object RGB |
| `0x0046FA6D` | `F3 0F 10 46 28 F3 0F 10 4E 24 F3 0F 10 56 20` | Shroud-ghost RGB |
| `0x00546C33` | `80 BD BD 00 00 00 00` | Native mesh fog gate |
| `0x00471A40` | `5F 5E 5B C9 C2 04 00` | Scene-exit marker cleanup |

The primary JMP targets a dynamically allocated **`.cldfog`** cave, size **`0x8C0`**,
with code/read/write permissions for the immutable code/config and private mutable
render state. Object code starts at `+0x600`; config at `+0x800`, state at `+0x880`
(size `0x40`), RGB at state `+0x20`, scene marker at state `+0x3C`. The embedded magic
is `CLDFOG3`. No fixed cave RVA is assumed; normal sections and shared sub-caves use
`allocate_section`/`find_section` and are covered by tests.

At primary entry AL is enable, XMM1 low float is start, XMM0 low float is end. The
verified frame locals are start **`[EBP-0x14]`**, end **`[EBP-0x18]`**, RGB pointer
**`[EBP-0x10]`**. The live scene at **`[EBP-0x1C]`** is preserved; the initial analysis
had the first three locals shifted by four bytes. The hook updates both SSE values
and matching locals before native continuation.

Flags and GPRs are saved; an aligned FXSAVE/FXRSTOR area preserves SSE, x87 and MXCSR.
Only the documented fog outputs change. Temporary work does not call native functions.
The original global enable store runs, followed by the jump to `0x00471918`. Projection
`0x00DD3445` and static-LOD `0x00D9B058` gates retain native behavior.

The scene-active marker is reset on primary entry and the normal scene epilogue,
limiting mesh substitutions to a positive blend in this scene. Object fog calls outside
that interval follow original paths. Scene fields and mesh HardwareFog flags are never
persistently patched. An exceptional exit before the epilogue is cleared on next entry;
private phase, RGB and marker assume serial, non-nested scene rendering.

## Compatibility and evidence

Every original-byte fingerprint is checked. Unknown/occupied hooks, foreign cave content,
old V1/V2 layouts and differing V3 profiles are rejected. Identical application is
idempotent. Rebuild from clean input when changing profile, rather than layering another
fog patch over existing hooks. Parameter detection verifies immutable code/config while
allowing the mutable runtime state to change.

Data-free tests execute original x86 continuations and object/material chains, verify
registers/flags/SSE/x87/MXCSR/stack, logical timing at several rates, pause, speed/rate
conversion, wrap/reset, reversals, custom profiles, protected builder outputs, conflicts,
parameter detection and manifest round trips. Native cloud lighting, parser, duration,
sound and snapshot tests are covered by the FOGGY suite.

Archived V3 and initial FOGGY artifacts are under `tools/BFME-FILES/`; they retain their
original profiles, hashes and evidence logs. Dedicated tree/shrub batches, special FX,
all graphics options, exceptional/nested rendering, live multiplayer/CRC and replays
remain outside the confirmed coverage. Native weather durations, modifiers, RNG and
save-format fields are not changed by this renderer.
