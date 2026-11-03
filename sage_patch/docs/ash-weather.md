# `ASH_RAIN` weather and the `ASHEN` model condition

Registry names: `ash-weather` (`game.dat`) and `ash-weather-wb` (`Worldbuilder.exe`). Target: ROTWK
`game.dat` build `2.01.2614.37001` and the Worldbuilder that ships with it.

The mechanism is the one [`desert-weather`](desert-weather.md) derives - read that page for every
address. This page covers what is different: a fixed weather slot, and composing with
`desert-weather` at the sites both patches take over. Both patches go through
[`../patches/utils/map_weather.py`](../patches/utils/map_weather.py), which owns those sites.

## Using it

A map sets the `Integer` property `weather = 3` in its `WorldInfo` chunk. Worldbuilder's
map-settings dropdown writes it once `ash-weather-wb` is applied. `GameData Weather = ASH_RAIN`
sets the mod-wide default. Either way, on an object's draw module:

```ini
ModelConditionState = ASHEN
  Model = EUFoo_ASH
End
; and/or
WeatherTexture = ASH_RAIN EUFoo_ASH.tga
```

`ForceModelsToFollowWeather` must stay `Yes` (the default). `Sound` / `ViewShake` accept
`Weather = ASH_RAIN`.

The patch does not make ash fall. Falling particles come from the global `Weather` block in
`weather.ini` (`IsSnowing`, `SnowTexture`), one texture for the whole game, and nothing ties that
block to the map weather.

## 1. Fixed slots

A map stores its weather as an integer, so a token's index has to be the same on every stack of
patches. If `ASH_RAIN` took the next free slot, it would be 2 alone and 3 beside `desert-weather`,
and a map authored on one stack would silently come out as some other weather on the other. The
registry also sorts `ash-weather` before `desert-weather`, which would move `DESERT` to 3 and break
every map already carrying `weather = 2`.

So each patch owns its slot: `DESERT` is 2 and `ASH_RAIN` is 3. A patch whose slot lies past the
end of the live table fills the gap with a placeholder, `RESERVED_WEATHER_<n>`. The patch owning
that slot replaces it later. A placeholder parses, selects nothing and drives no condition. Alone,
`ash-weather` gives `{NORMAL, SNOWY, RESERVED_WEATHER_2, ASH_RAIN}`. `sage-patch sagepatch` leaves
placeholders out of the generated `MapWeatherType` tokens.

The `Sound`/`ViewShake` "matches any weather" value (§5 of the desert page) and Worldbuilder's
dropdown bound (§9) are both the member count. Each patch moves them from the live table length to
the new one, so alone or together they end at 4.

## 2. Chained hooks

Both patches take over the same two blocks: `Drawable::bindToObject`'s weather arm (`0x00690FBE`)
and the timed-upgrade expiry re-assert (`0x008058F9`). The first patch to arrive finds the engine's
bytes and writes a **head** cave: the displaced `SNOW` code, its own condition, and a `jmp` back to
the engine. This is byte for byte what `desert-weather` always wrote, so a `game.dat` built before
the helper existed still detects and verifies. A later patch finds a `jmp` at the site and writes
a **link** cave: its own condition, then a `jmp` to wherever the site pointed. It then repoints
the site's `jmp` at the link. The rest of the replaced range stays `nop`.

```
site -> [ash link: ASHEN] -> [desert head: SNOW, SAND] -> engine
```

Every cave writes only eax/ecx/edx, so the order they run in does not matter. Each pair still goes
through `ModelConditionFlags::set`, so a condition is cleared on every other weather.

`verify` walks the chain from the site to find its own cave. A head is told from a link by the
weather its first block compares against: a head starts with the `SNOWY` compare (`1`), and a
link's weather is its own slot, never 1. Walking needs no knowledge of the other patch.

## 3. Constraints

The same as `desert-weather`. Every peer needs the same binary, since `Object+0x10C` is part of
the CRC. A save carrying `ASHEN` does not load on an unpatched binary. The asset-preload site
`0x00491F82` is left alone (a first-appearance stutter, not a wrong picture). The Worldbuilder
viewport keeps drawing the non-`ASHEN` variant.

Neither patch has been run in a game yet. The chained caves are executed under Unicorn in
`tests/sage_patch/test_ash_weather_emulated.py`, from both hook sites, for all four weathers and
both apply orders. The real `game.dat` takes both patches in either order and verifies.
