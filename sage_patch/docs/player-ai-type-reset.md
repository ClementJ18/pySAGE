# A map's `PlayerAIType` blocks outlive the map

Engine build `2.01.2614.37001`. Addresses are VAs (ImageBase `0x400000`), read from the stock
`game.dat` (`md5 daed3668006cd90f01c34e5a7da1901f`).

**Symptom.** After a campaign mission whose `map.ini` sets `PlayerAIType ElvesAI` /
`ElvesSkirmishAI` to `LibraryMap = NONE`, Lothlórien AIs in later skirmish matches ran no
library scripts, until the game was restarted. The same mechanism applies to any `PlayerAIType`
a map redefines. Edain's fortress maps point all 21 of them at the `... festung` libraries
(`maps/_inis/general/festungaidata.ini`), so after one fortress match every ordinary skirmish in
the session runs the fortress libraries.

**Patch:** `player-ai-type-reset`. Before each map's `map.ini` is read, it reads
`Data\INI\PlayerAITypes.ini` again, which puts every type back to its global value.

## 1. Why the value stays

`ThePlayerAITypeSet` (`[0x00DE3D5C]`) is registered at `0x0063B511` without INI paths. The
global `Data\INI` directory load fills it once. It is not an `Overridable` store:

| what | where |
|---|---|
| block table entry `PlayerAIType` | `0x00D9EC30`, parse function `0x00615995` |
| parse | `0x00615871`: parse a fresh 16-byte record (`0x00615487`, field table `0x00BFBA64`, `LibraryMap` at `+4`), find the name (`0x006151D6`, returns the index or -1), append when it is missing, then **swap the parsed record over the stored one** (`0x006151B9`) and destroy the old value |
| `SubsystemInterface::reset` | vtable `0x00BFE8D0` slot 9 (`+0x24`, where `ThingFactory`'s vtable `0x00BDA800` holds `ThingFactory::reset` `0x006D120A`), the bare `ret` at `0x0063F3BF` |

So a `map.ini` block takes the same path as the global file, and the global record is gone once
it is swapped out. Compare `ThingTemplate`, whose `map.ini` blocks are flagged overrides that
`ThingFactory::reset` deletes when the map ends
([`living-campaign/wotr-save-failure.md`](living-campaign/wotr-save-failure.md)).

The parser ignores the INI load type, so loading a file as a `map.ini` pass
(`INI_LOAD_CREATE_OVERRIDES`, 2) or as the global pass makes no difference to this store.

## 2. Where it is read

`SidesList::loadAILibraryMaps` (`0x007318A1`, per side `0x0073161C`) looks the side's
`playerAIType` up in the set and loads that record's `LibraryMap`
([`skirmish-ai-fallback.md`](skirmish-ai-fallback.md)). This runs inside `startNewGame`, after
the map-INI loader, so the order on each map start is:

1. `0x0062FA07` calls the map-INI loader `0x0062710D` (`__thiscall`, the map path as an
   `AsciiString` by value). It loads `%s\map.ini` (`0x00BFD4D0`) and `%s\solo.ini` (`0x00BFD4C4`)
   with load type 2.
2. The AI libraries are resolved from the set as it now stands.

## 3. What the patch does

One five-byte hook and one cave (`.aitypes`).

| site | stock bytes | becomes |
|---|---|---|
| `0x0062710D` | `b8 a3 3b b8 00` (`mov eax, <SEH table>`) | `jmp` into the cave |

`0x0062710D` has one caller (`0x0062FA07`) and nothing branches into its first five bytes. The
cave:

1. `pushad`, then reserves `0x880` bytes for an `INI` object. The stock loader's object is
   `0x87C` bytes: `[ebp-0xA98]` up to the path buffer at `[ebp-0x21C]`.
2. `TheFileSystem->doesFileExist("Data\INI\PlayerAITypes.ini")` (`[0x00DEC598]`, `0x00A14AEB`,
   `ret 4`). If the file is missing, it skips to step 5, so a mod that keeps its AI types elsewhere
   gets stock behaviour.
3. `INI::INI` (`0x0042CAB8`), then `INI::load(AsciiString(path), 2, NULL)` (`0x0042D97D`,
   `ret 0xC`; the string built in place by `0x004374E0`), then `INI::~INI` (`0x0042CB63`). This is
   the stock loader's `map.ini` call sequence (`0x0062724A`..`0x0062727D`).
4. Every type in the file is parsed and swapped back to its global value.
5. Frees the reservation, `popad`, runs the displaced `mov eax, 0x00B83BA3`, and jumps to
   `0x00627112`. The new map's `map.ini` then applies over the restored set as before.

A type defined only by some `map.ini` (for example `NoAI` in Edain's `Moria`) stays in the set. It
is harmless, since only a map that names it can use it, and such a map defines it again.

Reloading the file costs one small INI parse per map load, the shell map included.

**Every peer needs the same binary.** The AI's libraries are game logic. Without the patch, two
peers whose sessions had played different maps could already disagree about an AI's library.

## 4. Limits

- Only `Data\INI\PlayerAITypes.ini` is reloaded. A mod that splits its `PlayerAIType` blocks
  across other files gets only that file's types reset.
- An `INI::load` that throws (a parse error in the global file) unwinds through the cave. The
  same file has already parsed cleanly at startup, so this cannot happen unless the file changes
  on disk while the game runs.

## 5. Verifying it in a game

1. Play a map whose `map.ini` sets a faction's `PlayerAIType` to `LibraryMap = NONE` (Edain:
   any evil campaign mission against Lothlórien), quit to the menu, and start a skirmish against
   that faction. The AI builds and attacks: its library scripts run.
2. Play a fortress map, then an ordinary skirmish map in the same session. The AI runs the
   ordinary library. In Edain, the Misty Mountains AI receives
   `Upgrade_AngmarStructureVasallenhausBuild` on its timer, which only `ki nebel` grants.
3. The campaign map itself still runs without the Elven library: the map's own block still
   applies after the reset.
