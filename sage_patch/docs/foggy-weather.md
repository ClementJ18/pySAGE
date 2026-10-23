# Native FOGGY weather with hardware fog

Author: **Ostkannit**. Registry names: `foggy-weather` and `foggy-weather-wb`.
Python API: `sage_patch.patches.FoggyWeatherPatch` and
`sage_patch.patches.FoggyWeatherWorldbuilderPatch`; implementation in
`sage_patch/patches/experimental/foggy_weather.py`. Both are registered experimental patches.
The package-level imports remain available as a convenience; the full implementations
live in the experimental package, including the shared CLOUDY renderer.

Target: RotWK **2.01.2614.37001**, PE32/x86, ImageBase `0x00400000`.
Verified original `game.dat.backup` SHA256:
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
python -m sage_patch apply foggy-weather --in game.dat.backup --out game-foggy.dat
python -m sage_patch verify foggy-weather game-foggy.dat
python -m sage_patch info foggy-weather --file game-foggy.dat
```

The same optional settings are accepted by `apply` and `verify`:

```sh
python -m sage_patch apply foggy-weather --in game.dat.backup --out game-foggy.dat --blend-in-ms 3000 --blend-out-ms 4500 --fog-rgb 0.65 0.72 0.80 --fog-start 500 --fog-end 1800
python -m sage_patch verify foggy-weather game-foggy.dat --blend-in-ms 3000 --blend-out-ms 4500 --fog-rgb 0.65 0.72 0.80 --fog-start 500 --fog-end 1800
```

Verification checks the requested profile; for a custom build, supply its settings or use
`info --file` to recover them. In a Python patch list replace `CloudyHardwareFogPatch()`
with `FoggyWeatherPatch(...)`, and add the editor twin to the Worldbuilder list.
**Do not apply both weather-fog patches together:** they own the same renderer hooks.
Existing incompatible fog caves and occupied hooks are rejected without changing input.
The personal `applymypatches.py` uses the experimental import; its installer is not needed
for verification and is not run by the helper builders.

For the configured patch selection, the guarded helper also accepts all five options:

```sh
python tools/build_foggy_weather_patch.py --out /tmp/game-foggy.dat --blend-in-ms 3000
python tools/build_foggy_weather_patch.py --target worldbuilder --out /tmp/Worldbuilder-foggy.exe
```

Omitted helper options retain the selected patch's configured values. The helper verifies
all selected patches, checks original source hashes, protects backups and configured
installation paths, and refuses to overwrite differing outputs. `--mode standalone`
builds only FOGGY; the default `listed` mode includes the other configured game patches.

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

Read-only Open-BFME-2 references include
`Code/GameEngineDevice/Source/W3DDevice/GameClient/RTS3DSceneFlush.cpp`,
`W3DPropBufferDrawProps.cpp`, `BaseHeightMapDoTheLight.cpp`, and
`Code/GameEngine/Source/Common/INI/INIBfmeSettingsParsers.cpp` plus
`Code/GameEngine/Source/GameLogic/System/GlobalWeatherSystemAudio.cpp`.
Their BFME2 addresses are not reused as RotWK addresses. Edain's
`_mod/data/ini/weather.ini` supplies the existing 725/2000 range and five WeatherData
entries; behavior examples include `_mod/data/ini/object/system/includes/systemgood.inc`.
No mod or reference-source changes are required.

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

The six shared renderer hooks and their ABI are documented in
[Hardware fog renderer](cloudy-hardware-fog.md). `.cldfog` remains the existing
`CLDFOG3` layout, including embedded parameters and private writable render state.

## Worldbuilder

The editor owns a separate ChangeWeather parser: PUSH **`0x011FA12C`** originally
`68 AC A2 23 02`, bound **`0x011FA154`** originally `83 38 05`. The editor twin redirects
that pointer and raises the bound to 6. Its **`.wbfoggy`** table is read-only and
non-executable, retaining entries 0–5 and appending FOGGY/NULL. FieldParse descriptor
`0x01F426F0` confirms behavior offset `+0x64`. No editor render hooks or WeatherData
expansion are added; editor viewport simulation of FOGGY is not promised.
Verified `Worldbuilder.exe.backup` SHA256:
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

The data-free tests cover profile defaults and individual overrides, public/legacy imports,
CLI apply/verify/info, validation before writes, detection and serialized manifest rebuilds,
original-byte rejection, atomicity, idempotence and cave conflicts. Native x86 execution
covers all 36 direct transitions between IDs 0/1/2/3/4/6, CLOUDY/FOGGY state-machine
entry/exit, unchanged-frame gating, real lighting getters/consumers, audio lifecycle,
expiry, snapshots and ABI. Shared-renderer tests cover logical timing and object routing.

The read-only `tools/analyse_foggy_weather.py` reproduces all **19 direct singleton
references** and the reviewed consumer inventory. Known WeatherData entry-addressing
sites are HasLightning `0x00719BF0`, bounded parser `0x00719DDD` and the now-bounded
audio `0x00719E12`. This is not a formal proof excluding every computed pointer alias
in the executable. Specialized tree/shrub shaders and special FX retain the shared
renderer's limits; private output state assumes serial scene rendering.

The archived initial test artifacts are under `tools/BFME-FILES/foggy-weather-v1/`.
That build verified all 64 selected game patches in three application positions and
all ten editor patches. It changed only eleven owned game-hook ranges (95 bytes,
89 actually changed), plus PE headers/caves; the editor changed four of eight owned
hook bytes. Its ordered manifest rebuilt byte-identically. Preserve actual patch order
when combining existing production-split/healing-received ModifierType extensions;
the unrelated CastlePrefab empty-default serialization difference may still appear in
generic manifest checks. Historical artifacts and installed files are not overwritten
by API/documentation integration.
