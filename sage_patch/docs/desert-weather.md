# `DESERT` weather and the `SAND` model condition

Derivation for the `desert-weather` patch, against ROTWK `game.dat` build `2.01.2614.37001`
(ImageBase `0x400000`). Every address below was recovered statically from that binary with
`pefile` + `capstone`; the scripts in [`../scripts/`](../scripts/) reproduce it.

## 0. What the request was, and the one thing it assumed wrong

> add another weather type called `DESERT`… `SNOWY` is linked to the `SNOW` model condition, I
> would like `DESERT` to be linked to the `SAND` model condition

`SNOWY` → `SNOW` is real and is exactly one code block. **`SAND` is not a stock model condition**,
though — the 591-entry `ModelConditionFlags` name table at `0x00D9FAD8` has `SNOW` at bit 8 and no
`SAND` anywhere. The `SAND` you can find in the binary is at `0x00DA34F4`, in the *terrain surface*
name list (`SWISS_1`, `SNOW_1`, `ASPHALT`, `CONCRETE`, `TRANSITION`, `SAND`, `WOOD`, `BLEND_EDGE`,
`LOTR_NEW`) — a tile classification, nothing to do with model conditions.

So the patch has to create the condition as well as the weather. That is the same table extension
`production-condition` performs, which is why both go through
[`../patches/utils/model_conditions.py`](../patches/utils/model_conditions.py) rather than each owning a copy
of the 16 references and 10 count bounds.

## 1. The global weather is a two-member enum in `GlobalData`

| what | where |
|---|---|
| name table | `0x00DA3A84` = `{"NORMAL", "SNOWY", NULL}` |
| the field | `GameData`'s `Weather`, `GlobalData+0x138`, `Enum`, default `0` |
| the pointer | `TheWritableGlobalData` @ `0x00DE4364` |
| the gate | `GameData`'s `ForceModelsToFollowWeather`, `GlobalData+0x13F`, default `Yes` |

The table is resolved by `INI::scanIndexList` (`0x0042B914`), which walks it to the NULL with
`stricmp` and returns the index — **no length constant anywhere**, so a third member is a table
change and nothing else. The nearest thing to a bound is the error path
(`"Token '%s' is not a valid member of the index list"`, `0x00BD3B54`).

**But the INI field is not how a map sets it.** `GlobalData+0x138` has exactly one writer outside
the field parser, and it is the `WorldInfo` map-chunk reader at `0x004AB790`:

```
004ab7a4  call 0x70901f                ; read the WorldInfo Dict out of the chunk
004ab7b8  call 0x714caf                ; store it as the global map dict @0x00DE638C
004ab7c1  mov ecx, 0x00DA2FBC          ; StaticNameKey "weather"  { cached key; const char *name; }
004ab7ce  call 0x714a98                ; Dict::getInt(key, &exists)   -- type tag 1, no clamp
004ab7d3  cmp byte [ebp-0xd], 0        ; present?
004ab7e0  mov [TheWritableGlobalData+0x138], eax
```

So the weather a map ships with is a plain **`Integer` property named `weather` in the `WorldInfo`
chunk**, copied into `GlobalData` verbatim — no range check on either side. `sage_map` already
reads and writes it (`map.world_info.properties["weather"]`). A map carrying `weather = 2` selects
`DESERT` on a patched binary with nothing else needed; the INI field is the mod-wide default that
such a map then overrides.

It cannot be extended in place: `0x00DA3A88` is `SNOWY`, `0x00DA3A8C` is the terminator, and
`0x00DA3A90` is already the first entry of the `LivingWorldObjectType` table. The patch relocates
it into its cave and repoints all four references:

| ref | what it is |
|---|---|
| `0x004CF07B` | `push <table>` in a `WeatherTexture` field parser |
| `0x004CFECE` | the same, in the second draw module's parser |
| `0x00BF2C08` | `userData` of the `Sound` / `ViewShake` `Weather` field descriptor (offset `0x140`) |
| `0x00BFFA98` | `userData` of the `GameData` `Weather` field descriptor (offset `0x138`) |

The two stock string pointers are copied through as-is, so `NORMAL` and `SNOWY` keep both their
indices and their original strings.

## 2. Everywhere the engine reads `GlobalData+0x138`

Found by taking all 1293 `.text` references to `TheWritableGlobalData`, re-aligning each to a real
instruction boundary, and disassembling forward. Six real sites (the rest are misalignment
artefacts of the immediate appearing inside another instruction):

| site | what it does | patched? |
|---|---|---|
| `0x00690FC0` | `Drawable::bindToObject`: `set(SNOW, weather == SNOWY)` | **yes** — §3 |
| `0x0080590B` | timed-upgrade expiry: re-assert `SNOW` after clearing an upgrade's conditions | **yes** — §4 |
| `0x005DF6FB` | `Sound` / `ViewShake` condition matcher: does this weather match? | **yes** — §5 |
| `0x004CEA4C` | `WeatherTexture` lookup: linear scan of `(weather, texture)` pairs, stride 8 | no — index-agnostic |
| `0x004CFAE2` | the second `WeatherTexture` lookup, same shape | no — index-agnostic |
| `0x00491FB6` | builds a `NIGHT`/`SNOW` mask and asks each draw module which model it would use | **no** — §6 |

`WeatherTexture` therefore accepts `DESERT` for free: the parser resolves the token through the
table this patch grows, and the lookup compares the stored integer against `GlobalData+0x138` with
no bound on either side.

## 3. The primary site: `Drawable::bindToObject` (`0x00690F02`)

Called from `0x00625AB9`, `0x00625AE9`, `0x0064652B`; stores the `Object*` at `Drawable+0x84`,
builds a *clear* mask and a *set* mask from the object's status bits through the 0x68-entry map at
`0x00C16958`, applies the two globals, and hands both to
`Drawable::clearAndSetModelConditionFlags` (`0x0068D607`).

```
00690f95  cmp byte [esi+0x13e], 0      ; ForceModelsToFollowTimeOfDay
00690f9c  je  0x690fb5
00690fa0  cmp dword [esi+0x134], 4     ; TIME_OF_DAY_NIGHT
00690faa  sete al
00690fae  push 7                       ; MODELCONDITION_NIGHT
00690fb0  call 0x68cc09                ; ModelConditionFlags::set(bit, value)
00690fb5  cmp byte [esi+0x13f], 0      ; ForceModelsToFollowWeather
00690fbc  je  0x690fd5
00690fbe  <--- replaced: 23 bytes, through 0x00690FD5 --->
00690fc0  cmp dword [esi+0x138], 1     ; WEATHER_SNOWY
00690fca  sete al
00690fce  push 8                       ; MODELCONDITION_SNOW
00690fd0  call 0x68cc09
```

`ModelConditionFlags::set` (`0x0068CC09`) is a plain `thiscall` set-or-clear with **no bound
check** — `bit >> 5` indexes the dword, `1 << (bit & 31)` is the mask, and the `value` argument
selects set or clear branchlessly. The cave duplicates the block for the new pair, and going
through `set` rather than an `or` is what makes the negative case work: on a `SNOWY` map the
`SAND` call *clears* `SAND`, so art that names both conditions cannot end up wearing both.

Registers: `esi` is `TheWritableGlobalData` (already null-checked at `0x00690F91`) and `edi` the
`Drawable`; both are live past the join at `0x00690FD5`. The cave writes only `eax`/`ecx`/`edx`,
and `set` is `ret 8`, so it balances its own arguments.

Nothing jumps into the middle of the replaced range — the only branches that reach it are
`0x00690F93` and `0x00690FBC`, both to `0x00690FD5`.

## 4. The secondary site: the timed-upgrade expiry update (`0x0080585F`)

An `UpdateModule` (constructor `0x008057A6`, `0xA8` bytes, allocated at `0x0064C3C8`) walking a
list of `(upgrade key, deadline, …)` entries of stride `0x10` at `this+0x10..+0x14`. When one
expires it pulls the upgrade's model conditions back off the object
(`0x005E3B79` → `Drawable::clearAndSetModelConditionFlags`) and then re-asserts the two
environment conditions if it had just cleared them:

```
008058f9  <--- replaced: 52 bytes, through 0x0080592D --->
008058f9  mov eax, [ebp-0x94]          ; the mask just cleared
008058ff  shr eax, 8
00805902  test al, 1                   ; was SNOW in it?
00805906  mov eax, [TheWritableGlobalData]
0080590b  cmp dword [eax+0x138], 1     ; still snowy?
00805914  mov ecx, [esi-8]             ; Object*  (module+0x08, same idiom as ProductionUpdate)
00805917  lea eax, [ecx+0x10c]         ; ModelConditionFlags
0080591d  mov edx, 0x100               ; bit 8
00805922  test [eax], edx              ; read before write
00805926  or   [eax], edx
00805928  call 0x68b53c                ; Object::onModelConditionFlagsChanged
0080592d  ... the identical NIGHT block, left untouched ...
```

The replacement starts at the *test*, not at the weather compare, so the whole "was this bit in
the cleared set" question can be asked for `SAND` too. Without it, an upgrade whose
`ModelConditionState` names `SAND` would strip it permanently on expiry — the asymmetry with
`SNOW` that the request is explicitly asking not to have.

Again nothing branches into the replaced range: `0x00805904`, `0x00805912` and `0x00805924` all
target `0x0080592D`, and the loop's back edge is to `0x008058A5`.

## 5. The sentinel that fails silently: `Sound` / `ViewShake` `Weather`

`Sound` and `ViewShake` carry a `Weather` field at `+0x140`, and the condition matcher at
`0x005DF671` treats the **member count** as "matches any weather":

```
005df6eb  mov esi, [esi+0x140]         ; the block's Weather
005df6f1  cmp esi, 2                   ; == the stock member count -> "any"
005df6f4  je  match
005df6f6  mov eax, [TheWritableGlobalData]
005df6fb  cmp [eax+0x138], esi
```

and the constructor at `0x005DF5BE` stores that same `2` as the default:

```
005df616  mov dword [esi+0x140], 2
```

`DESERT` takes index 2. Left alone, `Weather = DESERT` on a sound would parse fine and mean
*always* — no error, no log line, just a sound that plays on every map. Both immediates move to 3,
which keeps the unset default meaning "any" and makes `DESERT` selectable. This is the only edit
in the patch whose omission would be invisible rather than loud.

## 6. Knowingly left alone: `0x00491F82`

Slot 34 of the vtable at `0x00BDDF90`. It zeroes a `0x4C`-byte `ModelConditionFlags` at
`[ebp-0x60]`, sets bit 8 if the weather is snowy and bit 7 if the time of day is night, then walks
a `ThingTemplate`'s draw-module list (`+0x2F0`/`+0x2F4`, stride `0x14`) calling each module's
`+0x38` virtual to collect model *names*. It feeds asset preloading, not what is drawn.

Unpatched, a `DESERT` map preloads the non-`SAND` variant of each model and then loads the right
one on demand — a first-appearance stutter, not a wrong picture. Fixing it costs a third cave (the
block is 26 bytes of `or byte [ebp-0x5f], 1` style immediates with no room for a fourth branch),
which is not worth a hitch; it is recorded here so it is a decision rather than an oversight.

## 7. The model condition

`SAND` is appended to the `ModelConditionFlags` name table by
[`../patches/utils/model_conditions.py`](../patches/utils/model_conditions.py) — 16 references repointed, 10
count bounds raised, all read live out of the image rather than assumed. On a stock binary it
lands on **bit 591**, the first unnamed slot and the last one the `xfer` packed blob already
covers; applied alongside `production-condition` one of the two lands on 592 and the helper widens
the blob's two `push 0x4a` length constants. The full derivation of the table, the count sites and
the blob is in [`production-model-condition.md`](production-model-condition.md) §2a.

Bit 591 puts the mask at `Object+0x154` with mask `0x8000` — the last dword of the 19-dword mask,
which ends exactly at `Object+0x158`.

## 8. Using it

Per map — the normal route, and what Worldbuilder's map-settings dialog writes:

```python
from sage_map import parse_map_from_path, write_map_to_path

m = parse_map_from_path("map mp foo.map")
m.world_info.properties["weather"]["value"] = 2  # DESERT
write_map_to_path(m, "map mp foo.map")
```

Mod-wide, as the default a map without that property inherits:

```ini
GameData
  Weather = DESERT
End
```

Either way, on any object's draw module:

```ini
ModelConditionState = SAND
  Model = EUFoo_DES
End
; and/or
WeatherTexture = DESERT EUFoo_DES.tga
```

`ForceModelsToFollowWeather` must stay `Yes` (it is by default) or the engine sets neither `SNOW`
nor `SAND`.

## 9. Worldbuilder needs its own patch — and will silently undo the setting until it gets one

`Worldbuilder.exe` links the same engine code and carries its own copy of everything above: the
weather table at `0x02231FB0` (`{NORMAL, SNOWY, NULL}`, with `0x02231FBC` already the next table,
so no slack there either), both `Weather` field descriptors at `+0x140`/`+0x138`, the `WorldInfo`
read (`0x0076E44D`) and the matching write on save (`Dict::setInt` at `0x0066ECE4`). Its
`TheWritableGlobalData` is `0x022CA7D8`. It is a clean PE with `.reloc` and no protection
sections, so the same `allocate_section` approach works on it.

The map-settings dialog is where it diverges. The `&Weather:` combo (control `0x4F5`) is filled by
a loop with a **hardcoded bound**, not by walking to the terminator:

```
0056b97e  mov dword [ebp-0x20], 0
0056b990  cmp dword [ebp-0x20], 2          ; <-- 83 7D E0 02, the member count, hardcoded
0056b994  jge done
0056b999  mov edx, [ecx*4 + 0x02231FB0]
0056b9af  push 0x143                       ; CB_ADDSTRING
0056b9c3  done:
0056b9c8  mov ecx, [TheWritableGlobalData+0x138]
0056b9dd  push 0x14e                       ; CB_SETCURSEL <- the map's current weather
```

and the OK handler stores the selection back **unvalidated**:

```
0056c63e  push 0x147                       ; CB_GETCURSEL
0056c650  mov [ebp-0x30], eax
0056c66b  mov [TheWritableGlobalData+0x138], eax
```

So on an unpatched Worldbuilder, a map carrying `weather = 2` opens with `CB_SETCURSEL(2)` on a
two-item combo. That returns `CB_ERR` and *clears the selection*, so `CB_GETCURSEL` answers `-1`
and clicking OK writes `-1` into `GlobalData+0x138`, which the save path then writes back into the
map. **Opening the map settings and pressing OK destroys the setting, with no warning** - the same
failure shape as the `Sound`/`ViewShake` sentinel in §5, and worth knowing before authoring a
`DESERT` map by hand.

Making the dropdown work is small, and is what the **`desert-weather-wb`** patch does: relocate the
table and repoint its five references (`0x0056B99C` the combo loop, `0x0090D2EC` and `0x0095DAFC`
the two `WeatherTexture` parsers, `0x01E70E20` and `0x01E86B88` the two field descriptors), then
raise the one immediate at `0x0056B990` from 2 to 3. The OK handler needs nothing — it already
stores whatever index the combo reports.

```
sage-patch apply desert-weather-wb --in Worldbuilder.exe.backup --out Worldbuilder.exe
```

Two things make that patch's checks worth more than usual. The immediate it raises is an ordinary
`cmp` against a small constant, so it is pinned by the two window messages that bracket the loop
(`push 0x143` = `CB_ADDSTRING` at `0x0056B9AF`, `push 0x14E` = `CB_SETCURSEL` at `0x0056B9DD`)
rather than by the `cmp` alone. And the relocated table holds absolute string addresses with no
entries in `.reloc` — Worldbuilder, unlike `game.dat`, is `RELOCS_STRIPPED=False` and ships a
base-relocation directory — so the patch asserts `DllCharacteristics` has `DYNAMIC_BASE` clear
instead of assuming the image is never rebased.

**Keep the two weathers named the same on both sides.** A map stores the weather as an *integer*;
the name only exists to look it up. `DESERT` is appended to a two-entry table in both binaries, so
both resolve it to 2 — but `--weather` on either patch without the other would author maps that
come out as some other weather, with nothing to report the mismatch.

Making the editor **viewport** show `SAND` models is a separate, larger job: Worldbuilder resolves
model conditions the same way the game does (`0x00CEBF4C` gates on `ForceModelsToFollowWeather`
then `cmp +0x138, 1` for bit 8; also `0x00928EC8`, `0x0092952B`, `0x0064F953`, the last bounded by
`0x24F` = 591), so it would need its own model-condition table extension as well. That is cosmetic
inside the editor only - the map data and the game are unaffected by it.

## 10. Constraints

- **Determinism.** `Object+0x10C` is the logic-side mask and part of what the engine CRCs, so
  every peer must run the same patched binary. A patched and an unpatched client desync as soon as
  a drawable binds on a `DESERT` map, and replays do not cross. Same constraint, same reason, as
  `production-condition`.
- **Savegames.** The `xfer` save/load path serialises condition **names**, not a bit layout, so a
  save carrying `SAND` cannot be loaded by an unpatched binary (the load aborts on a name it
  cannot resolve, `0x004BAFDC` → `int3` at `0x004BB022`) but nothing about the format changes.
- **`WeatherData` / `GlobalWeatherSystem` is a different system.** The `WeatherType` enum at
  `0x00DB0074` (`NONE`, `CLOUDY`, `RAINY`, `CLOUDYRAINY`, `SUNNY`) drives RotWK's weather
  *effects*, and `ChangeWeather` on a special power refers to that one. It is untouched and
  unrelated to `GlobalData+0x138`.
