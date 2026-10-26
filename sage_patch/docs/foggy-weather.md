# Native FOGGY weather with hardware fog

Author: **Ostkannit**. Registry names: `foggy-weather` and `foggy-weather-wb`.
Python API: `sage_patch.patches.FoggyWeatherPatch` and
`sage_patch.patches.FoggyWeatherWorldbuilderPatch`; implementation in
`sage_patch/patches/experimental/foggy_weather.py`. Both are registered experimental patches.
The package-level imports remain available as a convenience; the full implementations
live in the experimental package; the hardware-fog renderer is part of FOGGY itself.

Target: RotWK **2.01.2614.37001**, PE32/x86, ImageBase `0x00400000`.
Verified reference executable SHA-256:
`5481de75b63e22483660ea8097478faef594f90b9ade7de893e092256ba68a26`.

## Runtime evidence

**User-confirmed on 2026-10-23:** triggering FOGGY produces the intended visual change;
saving and loading work, including restoration of the effect's remaining duration.
The game patch records `runtime_verified = "yes"` and remains experimental. This is a user report,
separate from the automated static and x86-emulation checks described below.
It does not establish multiplayer, replay, CRC, every graphics option or every shader.
Worldbuilder's parser extension is byte-verified and emulated; its editor runtime has
not separately been confirmed.

## Behavior and INI

| Native ID | Weather | Behavior |
| --- | --- | --- |
| 0 | NONE | Native behavior; any remaining hardware fog fades out |
| 1 | CLOUDY | Original dimming and cloud rendering; does not activate hardware fog |
| 2 | RAINY | Native behavior |
| 3 | CLOUDYRAINY | Native behavior |
| 4 | SUNNY | Native behavior |
| 5 | Reserved sentinel | Existing MOUNTED parser token retained; runtime skips the weather setter |
| 6 | FOGGY | Native CLOUDY dimming and cloud texture selection, plus smooth hardware fog |

In an existing weather-changing **SpecialPower behavior**, write:

```ini
ChangeWeather = FOGGY
```

This field belongs to the shared **SpecialPowerModuleData** used by behaviors such as
`DarknessSpecialPower` and `FreezingRainSpecialPower`. The FieldParse descriptor at
`0x00C64F80` names callback `0x008966F9` and offset `+0x64`; runtime `0x00897987`
loads that ModuleData through `[Behavior+4]`. It is not a new field in the top-level
`SpecialPower` template. Existing `WeatherDuration` settings retain their meaning.
**Do not add a `WeatherData FOGGY` block.**

The actual value at `GlobalWeatherSystem+0x10` remains **6**. Only two local graphics
comparisons interpret it as CLOUDY. On a FOGGY-to-CLOUDY transition the remaining fog
fades out; CLOUDY itself never starts a new hardware-fog effect.

## Optional parameters

All five settings are optional constructor arguments and CLI options. They are embedded
when building the patch, recovered from the binary by `detect`, recorded by `.sagepatch`,
and restored by manifest rebuilds. Changing a profile requires rebuilding from clean input.

| Default constant | Python argument | CLI option | Current default |
| --- | --- | --- | --- |
| `BLEND_IN_MS` | `blend_in_ms` | `--blend-in-ms` | `10000` simulation ms |
| `BLEND_OUT_MS` | `blend_out_ms` | `--blend-out-ms` | `10000` simulation ms |
| `FOG_RGB` | `fog_rgb` | `--fog-rgb R G B` | `(0.70, 0.76, 0.80)` |
| `FOG_START` | `fog_start` | `--fog-start` | `725.0` world units |
| `FOG_END` | `fog_end` | `--fog-end` | `2000.0` world units |

The constants can be imported from `sage_patch.patches.experimental.foggy_weather`; callers normally
pass lowercase keyword arguments. Each setting can be overridden independently:

```python
from sage_patch.patches import FoggyWeatherPatch, FoggyWeatherWorldbuilderPatch

patch = FoggyWeatherPatch()  # All defaults.
custom = FoggyWeatherPatch(
    blend_in_ms=3000,
    blend_out_ms=4500,
    fog_rgb=(0.65, 0.72, 0.80),
    fog_start=500.0,
    fog_end=1800.0,
)
editor = FoggyWeatherWorldbuilderPatch()  # Parser only; no render profile.
```

Durations must be integers in **1..600000** milliseconds. RGB needs exactly three finite
components in **0..1**. Distances must be finite and satisfy
**0 <= start < end <= 10000000**, including after float32 conversion. Invalid profiles
are rejected before patch application. Float values are stored canonically as float32.
The archived first test build used three-second fades; its stored profile is not changed
by the current ten-second constructor defaults.

## Apply, inspect and verify

Use clean input and a separate output:

```sh
python -m sage_patch apply foggy-weather --in original.dat --out game-foggy.dat
python -m sage_patch verify foggy-weather game-foggy.dat
python -m sage_patch info foggy-weather --file game-foggy.dat
```

The same optional settings are accepted by `apply` and `verify`:

```sh
python -m sage_patch apply foggy-weather --in original.dat --out game-foggy.dat --blend-in-ms 3000 --blend-out-ms 4500 --fog-rgb 0.65 0.72 0.80 --fog-start 500 --fog-end 1800
python -m sage_patch verify foggy-weather game-foggy.dat --blend-in-ms 3000 --blend-out-ms 4500 --fog-rgb 0.65 0.72 0.80 --fog-start 500 --fog-end 1800
```

Verification checks the requested profile; for a custom build, supply its settings or use
`info --file` to recover them. Add `FoggyWeatherPatch(...)` to a Python game-patch
list and `FoggyWeatherWorldbuilderPatch()` to the editor list. The standalone CLOUDY
fog patch has been removed; CLOUDY itself retains its native behavior. Rebuild from
clean input when migrating an older fog installation. Incompatible caves and occupied
hooks are rejected without changing input.

## Cause of native CLOUDY dimming

The following chain is supported by RotWK disassembly and execution of native partial
paths in Unicorn, rather than by matching a virtual slot number alone:

1. The cloud singleton is **`0x00DE3C24`**, registered as **TheCloudEffectManager**.
   GameClient's factory slot `+0xBC` calls `0x0044BEC3`, allocates `0x108` bytes and
   runs `0x00494C65`, producing VTable **`0x00BDE130`**. The registration/store is
   at `0x00647052`. The concrete C++ subclass name is not independently established.
   The separate `0x00DCA2C0` object is not the source of these lighting values.
2. GameClient dispatches update slot `+0x28` at `0x006485A0` to **`0x00497D00`**.
   Its early-return gate compares cached `+0x100` with the client frame. The real
   W3DGameClient VTable `0x00BDA6E0`, slot `+0x7C`, points to **`0x009F9F1A`**:
   `mov eax,[ecx+0x10]; ret`. A weather change is processed on the next new client frame.
3. On entering CLOUDY, slot `+0x38`, **`0x00614C71`**, copies the global RGB triples
   at `0x00DE3CE0` / `0x00DE3CEC` into cloud object `+0x30` / `+0x3C`. The native
   field table names them **DarkeningFactor** / **DarkeningFactorRain**. These are
   CloudEffect settings, separate from the five sound/lightning WeatherData records.
4. Visual cache `+0xBC`, effect state `+0xC0` and counter `+0xC4` drive native fades.
   Under graphics mode `0x00D9989C == 2`, the counter falls from 255 to 0 on entry
   and rises on exit. That native client-frame timing is preserved, independently
   of the configurable simulation-time hardware-fog blend.
5. **`0x00494DBA`**, particularly **`0x00495197`**, writes
   `DarkeningFactor * (1 - counter/255)` to **`+0xD4/+0xD8/+0xDC`**.
   Getter **`0x00494D4A`**, slot `+0x48`, returns that RGB triple; slot `+0x3C`
   (`0x00494794`) reports whether the effect is active.
6. Concrete consumers are Scene::Flush **`0x004713C0..0x0047141C`**, terrain lighting
   near **`0x00469108`**, props near **`0x004EDE98`** and drawable color near
   **`0x00670A06`**. Lighting is multiplied by **`1 - CloudEffectRGB`**. A test
   executes the real update, client-frame getter, RGB getter and scene consumer:
   input `(0.15, 0.20, 0.25)` produces light factors `(0.85, 0.80, 0.75)`, equally
   for original CLOUDY and patched FOGGY.

The additional texture comparison at `0x00496F4D` is in the running cloud renderer,
`0x00495228`. EBX is set to 1 at `0x0049525D/5F` and stays unchanged through this
comparison. FOGGY selects the same cloud texture, in addition to the proven lighting path.

## Native hooks, ABI and audio bounds

Central fingerprints live in `sage_patch/addresses/weather.py`. Application stages the
entire change before committing the bytearray; unknown bytes, conflicts or failed
verification leave the caller's input unchanged.

| VA | Original bytes | Replacement / continuation |
| --- | --- | --- |
| `0x00896701` | `68 74 00 DB 00` | PUSH a new NULL-terminated weather name table |
| `0x0089671F` | `83 F8 05` | `cmp eax,6`; native validation branches retained |
| `0x00497D2F` | `8B 48 10 3B CB` | Locally map ECX 6 to 1, native CMP, return `0x00497D34` |
| `0x00719E0F` | `8B 46 10 8D 44 C6 30` | Bound only the sound index, return `0x00719E16` |
| `0x00496F4D` | `39 58 10 75 03` | Local CLOUDY texture choice, targets `0x00496F52` / `0x00496F55` |

The dynamically allocated **`.foggy`** cave is RX, size `0x248`. Its three trampolines
precede the `FOGGY1` marker, names at `+0x220` and `FOGGY\0` at `+0x240`. Entries 0–5
retain their original pointers, entry 6 names FOGGY, and entry 7 is NULL. Original tables
and neighboring names are untouched. The five original names run directly into MOUNTED,
WEAPON_TOGGLE and MOVING; the original post-lookup upper bound already rejected 6 and 7.
The sentinel comparison at **`0x00897B2F`** stays `cmp eax,5`.

Audio **`0x00719DEE`** removes the previous handle before reaching the new hook. Its
local unsigned index becomes 0 when outside 0..4, so FOGGY uses NONE's record; a configured
NONE sound is honored, otherwise it remains silent. Native handle initialization, event
construction/destruction and Add/Remove calls remain in place. The hook preserves flags;
only the EAX result already produced by the displaced instructions changes. Negative IDs
are bounded too. Texture selection saves ECX and recreates native comparison flags.
The visual hook changes only the comparison's local ECX. None writes the weather ID,
adds calls or uses FPU arithmetic. GPRs, flags, SSE, x87, MXCSR and stack are tested.

The five records stay at **`+0x30..+0x57`**, stride 8; fields at `+0x58` and later are
not repurposed. **`0x00719BE4`** already bounds HasLightning to 0..4, so FOGGY returns
false without a patch. The independent WeatherData parser **`0x00719D60`** retains its
five-entry search. Other native enums, including NORMAL/SNOWY/DESERT, remain unchanged.
The INI schema declares FOGGY in the existing `WeatherFlag` union for ChangeWeather
behaviors; that schema's old Python enum numbers are not the native weather table.

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
`0x004E5F64`. `RenderShrubs` at `0x0046B3BF` reaches `0x004E837E`. These batch paths
bypass mesh TextureCategories. Compiled batch shaders were not decoded.
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
conversion, wrap/reset, reversals, custom profiles, conflicts,
parameter detection and manifest round trips. Native cloud lighting, parser, duration,
sound and snapshot tests are covered by the FOGGY suite.

Dedicated tree/shrub batches, special FX, all graphics options, exceptional/nested
rendering, live multiplayer/CRC and replays remain outside the confirmed coverage.
Native weather durations, modifiers, RNG and save-format fields are not changed by this renderer.

## Worldbuilder

The editor owns a separate ChangeWeather parser: PUSH **`0x011FA12C`** originally
`68 AC A2 23 02`, bound **`0x011FA154`** originally `83 38 05`. The editor twin redirects
that pointer and raises the bound to 6. Its **`.wbfoggy`** table is read-only and
non-executable, retaining entries 0–5 and appending FOGGY/NULL. FieldParse descriptor
`0x01F426F0` confirms behavior offset `+0x64`. No editor render hooks or WeatherData
expansion are added; editor viewport simulation of FOGGY is not promised.
Verified Worldbuilder reference SHA-256:
`005971beb68d0485846ff5f62d6f043e9c9b89d6576525ee25b56e9d305ec65d`.

## Duration, save/load and synchronization

Native setter **`0x0071A024`** stores ID `+0x10` and duration `+0x28`; logic update
**`0x0071A09E`** decrements the duration and invokes the same setter with NONE/0/0
on expiry. Reapplying the same weather ID does not refresh its timer: the native
same-value early return is preserved.

`CHUNK_WeatherSystem`, registered at `0x006DFAE0`, uses Snapshot subobject **+0x0C**.
VTable `0x00C22D9C`, slot `+0x0C`, invokes **`0x0071A2E3`** with unchanged versions
**minimum 1/current 4**. The ID is Snapshot `+4`, transferred by `0x0070777F` as a
four-byte `GlobalWeatherType`. Generic enum transfer **`0x00A1F8B5`** validates width
1..4, without an enum-value bound, then transfers `enu4`. Weather and modifier timers
`+0x28/+0x2C` are included from version 3. Postload **`0x0071A0D6`** adjusts This by
`-0x0C` and calls audio, which is protected by the same sound hook.

Automated tests execute native snapshot/enum/postload code for versions 1–4 and IDs
0–4/6 with external I/O and audio stubs. **The user additionally confirms real saving,
loading and remaining-duration restoration.** Private fog blend phase/RGB is not saved;
loading can restart the visual fade while preserving the native remaining weather time.

Existing IDs 0–4 retain meaning and layout. A save containing active FOGGY requires the
patch when loaded: the unpatched engine still has the unsafe sound index for 6.
Multiplayer/replay participants need matching engine patches and INIs. No live multiplayer,
CRC or replay validation is claimed, and the actual ID is never rewritten for serialization.

## Verification and remaining limits

The data-free tests cover profile defaults and individual overrides, public imports,
CLI apply/verify/info, validation before writes, detection and serialized manifest rebuilds,
original-byte rejection, atomicity, idempotence and cave conflicts. Native x86 execution
covers all 36 direct transitions between IDs 0/1/2/3/4/6, CLOUDY/FOGGY state-machine
entry/exit, unchanged-frame gating, real lighting getters/consumers, audio lifecycle,
expiry, snapshots and ABI. Shared-renderer tests cover logical timing and object routing.

Static inspection found **19 direct singleton references** in the reviewed consumer inventory.
Known WeatherData entry-addressing sites are HasLightning `0x00719BF0`, bounded parser
`0x00719DDD` and the now-bounded
audio `0x00719E12`. This is not a formal proof excluding every computed pointer alias
in the executable. Specialized tree/shrub shaders and special FX retain the shared
renderer's limits; private output state assumes serial scene rendering.

Initial compatibility checks applied the patch alongside 64 selected game patches in
three application positions and ten editor patches. Only eleven owned game-hook ranges
(95 reserved bytes, 89 changed bytes), PE headers and caves changed. The editor changed
four of eight owned hook bytes, and the ordered manifest rebuilt byte-identically.
Preserve patch order when combining production-split/healing-received ModifierType
extensions. The unrelated CastlePrefab empty-default serialization difference may still
appear in generic manifest checks.
