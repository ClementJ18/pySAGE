# Loading tips in place of the map description

Engine build `2.01.2614.37001`. Addresses are VAs (ImageBase `0x400000`, no ASLR), read from the
repo's `game.dat`, which carries only `cah-factions` (nowhere near these sites).

- **Goal:** during a skirmish/multiplayer map load, the box under the map preview shows tips from
  the string table instead of the map's description, picked at random and changing every few seconds.
  The local player's faction gets its own tips, alongside the general ones.
- **Cost:** one vtable dword and a cave with a single routine. No code bytes are rewritten, no
  structure grows, and no INI keyword is added. The tips are CSF labels, so a mod adds or edits
  them without rebuilding `game.dat`.
- **Risk:** low. The patch only changes UI, it never touches logic state, and it draws its
  randomness from the wall clock, so it cannot desync.
- **Status:** scoped, not built. The engine side below is static-verified. Nothing has been seen
  in a running game.

## What the engine does today

### The box is the `MapInfo` list box, and it holds the description

`LoadScreen.apt` (Edain ships its own; the stock `.const` is unchanged) places a sprite named
`MapInfo` whose clip action registers a gadget:

```
_type = ListBox
_Init = AptMapPreview::MapGadgetInit
_Load = Apt/ListBox.wnd           ; SCROLLLISTBOX, 1 column, Albertus MT 10
```

`AptMapPreview::MapGadgetInit` is bound at `0x009779C1` to `0x009777AB`, a name dispatch on the
gadget it is handed (`stricmp` against the strings at `0x00C85050..`):

| gadget name | stored at `AptMapPreview+` |
|---|---|
| `MapInfo` | `+0x28` |
| `MapDescription` | `+0x2C` (lobby only; the load screen has no such gadget) |
| `MapPicture` | `+0x24` |
| `CurrentMap` | `+0x20`, children `+0x30..+0x4C` (start-position markers) |

Every branch ends in the refresh `0x0097759F`, which calls `0x00976497` to fill `MapInfo` from
the selected `MapMetaData`. Outside Living World (`AptMapPreview+0x1C != 1`), that fill:

```
00976676  mov  ecx, [ebp+8]          ; MapMetaData
00976684  call 0x7022bf              ; display name  -> APT:CurrentMapName (the $MapTitle field)
...
009766bb  mov  ecx, [ebp+8]
009766c4  call 0x7021a2              ; description
009766c9  push [esi+0x28]            ; the MapInfo list box
009766cc  call 0x728632              ; GadgetListBoxAddEntryText(win, text, -1, -1, -1, 1)
```

`0x007021A2` resolves the `MapMetaData+0x4` label (MapCache `description`) through
`TheGameText` (`0x00DE4B04`, vtable `+0x38` = `fetch(UnicodeString *out, const AsciiString &label,
bool *exists)`), loading the map's `map.str` first via vtable `+0x4C`. It caches the result at
`+0xFC`. `0x007022BF` does the same for the display name (`+0x0`, cache `+0xF8`).

On the Living World branch (`+0x1C == 1`) the row comes from `0x0097606B` instead, the territory
text.

The fill opens with a dedup check (`0x009764B9..0x00976535`): if row 0 already equals the
description it returns. Otherwise it resets the box (`0x00726231`, `GadgetListBoxReset(win)`) and
refills it. Any re-run of the refresh therefore puts the description back over a tip, which
matters below.

### The load screen owns that `AptMapPreview`, and ticks on every progress report

The multiplayer/skirmish load screen has vtable `0x00C5091C`, written by its constructor
(`0x0081C8BD`) and destructor (`0x0081D37A`) and by nothing else:

| slot | VA | |
|---|---|---|
| 0 | `0x0081D33A` | destructor |
| 1 | `0x0081C5D3` | `update(Int percent)`, `thiscall`, `ret 4` |
| 2 | `0x0081CB08` | `init(GameInfo *)` |
| 3 | `0x0081C5C4` | clears the progress window `+0x88` |
| 4 | `0x0081C66F` | per-player progress |

Its `AptMapPreview` is embedded at `LoadScreen+0x18`: `update` passes `lea edi, [esi+0x18]` as
`this` to `0x00977542`, an `AptMapPreview` method. So the `MapInfo` box is `[LoadScreen+0x40]`,
and it is null until the APT runs the gadget's clip action.

### The local player's faction is already final when the screen exists

`init(GameInfo *)` stores its argument at `LoadScreen+0x88` (`0x0081CB2D`). `update` already asks
that `GameInfo` for the local seat:

```
0081c64a  mov  ecx, [esi+0x88]       ; GameInfo
0081c652  push edi                   ; percent, pushed early for the report
0081c653  call [eax+0x34]            ; GameInfo::getLocalSlotNum()
0081c656  mov  ecx, [0xde412c]
0081c65c  push eax
0081c65d  call 0x62648e              ; report(localSlot, percent), ret 8
```

The same vtable `+0x34` result feeds `GAME_INFO_GET_SLOT` (`0x00800B55`) at 16 other sites, and
`0x006DE6FC` treats a negative value as "no seat". From the slot onward, everything is already in
`sage_patch/addresses`:

- `slot+0x18` (`GAME_SLOT_PLAYER_TEMPLATE`): an index into `ThePlayerTemplateStore`, negative
  for an observer (`-2`).
- `PLAYER_TEMPLATE_FIND_BY_INDEX` (`0x005FCAD9`, thiscall on `[0x00DE3B10]`, `ret 4`): turns the
  index into a template, or null.
- `PlayerTemplate+0x10` (`PLAYER_TEMPLATE_NAME_KEY`): the block name's key.
- `NAME_KEY_TO_NAME` (`0x00548700`, thiscall on `[0x00DD90E4]`, `ret 4`): returns a
  `const AsciiString *` for that key, whose chars are at `[ret]+8` (`FactionMen`, `FactionMordor`, …).

Random is resolved before the screen exists. `startNewGame` gives a Random seat its drawn
template at `0x0062D71C` (`GAME_START_RANDOM_ASSIGN`), and only later in the same function creates
the load screen (`0x00626A87`, stored at `TheGameLogic+0x120`) and calls `init` (`0x0062DCBE`).
A Random player therefore gets the faction's tips, not a "Random" pool.

`update` ends in `0x00757B3C`, the base load-screen update, which pumps `TheAptPlayer`
(`0x00DE3F0C`, vtable `+0x28`) and draws a frame. The load screen redraws only when a progress
report arrives. Nothing animates between reports.

## The patch

### Hook: swap vtable slot 1

Point `[0x00C50920]` at a cave routine `update_hook(this, percent)`:

```
update_hook:                         ; thiscall, ret 4
    push ecx                         ; keep this
    push [esp+8]                     ; percent
    call 0x0081C5D3                  ; stock update (renders this tick)
    pop  ecx
    call rotate_tips                 ; ecx = LoadScreen
    ret  4
```

Swapping the slot avoids `LOADING_SCREEN_PROGRESS_RESUME` (`0x0081C662`), whose stock bytes the
experimental `command-line-skirmish` patch asserts and jumps to. The slot is only referenced
through the vtable, so no other patch reads it. The cost of running after the stock update is that
a new tip shows on the following tick, a few milliseconds later.

### `rotate_tips(LoadScreen *ls)`

```
box = [ls+0x40];  if box == 0: return          ; gadget not registered yet
now = timeGetTime()                             ; SPM_TIME_GET_TIME_IAT, 0x00BD0920
if first call for this ls  (cached ls != ls):
    cache ls; seed = now; due = 0
    faction = local_faction_name(ls)            ; below; null for an observer or no seat
    nf = faction ? count("LOADTIP:<faction>:%d") : 0
    ng = count("LOADTIP:%d")
    fill the bag with nf faction entries and ng general ones
    if bag is empty: leave the description alone
if now < due: return
GadgetListBoxReset(box)                         ; 0x00726231, cdecl
repeat TIPS_PER_SCREEN times:
    e = next entry from the bag                 ; reshuffled when empty, no repeat within a pass
    label = e.faction ? "LOADTIP:<faction>:%d" % e.i : "LOADTIP:%d" % e.i
    GadgetListBoxAddEntryText(box, fetch(label), -1, -1, -1, 1)   ; 0x00728632, cdecl
due = now + ROTATE_MS

local_faction_name(ls):
    gi   = [ls+0x88];                 if 0: return null
    slot = GAME_INFO_GET_SLOT(gi, gi->vtbl[0x34]())   ; getSlot returns null outside 0..7
    if slot == 0 or [slot+0x18] < 0: return null
    tmpl = PLAYER_TEMPLATE_FIND_BY_INDEX([0x00DE3B10], [slot+0x18]);  if 0: return null
    return [NAME_KEY_TO_NAME([0x00DD90E4], [tmpl+0x10])] + 8          ; "FactionMen"
```

- **Counting:** probe `<prefix>1`, `<prefix>2`, … through `TheGameText` fetch until `exists`
  comes back false (cap each pool at 127 so a bag entry fits in a byte: bit 7 marks faction,
  bits 0–6 hold the index). This is what makes the tip lists data-driven. Both counts are taken
  once per load.
- **Faction weighting:** one bag over both pools means a faction with 10 tips and 30 general ones
  shows its own a quarter of the time. `faction_weight` (below) repeats each faction entry
  in the bag `k` times; `general_tips=False` drops the general pool whenever the faction has any tips.
- **Label building:** `ASCII_STRING_FORMAT` (`0x00437A90`) with a `"%s%s:%d"` / `"%s%d"` format
  in the cave, into a stack `AsciiString` that gets destroyed afterwards. The faction name pointer is
  the interned key's storage, which lives for the whole session, so the cave can cache the `char *`
  rather than copying it.
- **Randomness:** a xorshift seeded from `timeGetTime`. Never `GameLogicRandomValue`: load
  timing differs per machine, so drawing from the logic stream here would desync the match.
- **Strings:** `fetch` returns a `UnicodeString` by out-pointer. `AddEntryText` takes it **by
  value** (one pointer slot that the callee does not destroy, matching the stock call at
  `0x009766B5`, which builds the slot with `0x00436990` and cleans up with `add esp, 0x18`). The cave
  needs the copy-construct and destructor pair (`0x00436990` / `UNICODE_STRING_DTOR` `0x004367B0`).
- **State:** a small `.data` block in the cave holding the cached `ls`, the count, the RNG state,
  `due` and the bag. Keying the first-call reset on `ls` handles a second load in the same session
  (a new `LoadScreen` object).

### Parameters

| constructor arg | default | |
|---|---|---|
| `label_prefix` | `"LOADTIP:"` | general labels `<prefix><n>`, faction labels `<prefix><PlayerTemplate>:<n>`, `n` from 1 |
| `faction_tips` | `True` | look up the local player's faction pool at all |
| `faction_weight` | `1` | how many times each faction tip appears in the bag (1–4) |
| `general_tips` | `True` | when False, a faction with its own tips shows only those; general tips stay the fallback |
| `rotate_ms` | `6000` | time between changes |
| `tips_per_screen` | `1` | rows shown at once, i.e. the size of the random set |
| `living_world` | `False` | when False, skip if `[ls+0x18+0x1C] == 1` and keep the territory text |

### Data side (Edain)

```
LOADTIP:1
"Heroes regain their abilities faster near a well."
END

LOADTIP:FactionMen:1
"Gondor's soldiers fight harder near a banner carrier."
END

LOADTIP:FactionMordor:1
"Orcs are cheap: spend them freely and keep your Uruks for the fight that matters."
END
```

The faction key is the `PlayerTemplate` block name from `playertemplate.ini`, the same name
`sage_ini` and the lobby use, so it follows whatever factions a mod defines. Numbering is
contiguous per pool: a gap ends that pool. The list of names to write tips for can come straight
from `sage_ini`'s `factions` table.

These are ordinary `lotr.csf` / `.str` entries. Since `TheGameText` has loaded `map.str` by the
time the box fills, a map can also ship its own `LOADTIP:n` entries (see "Not covered").

## Open questions for the runtime check

1. **Does the refresh re-run during the load?** The other callers of `0x0097759F`
   (`0x00841C78`, `0x00846B9B`, `0x00846BEF`) look like lobby paths. If one does fire mid-load, its
   dedup check restores the description, and the tip comes back only at the next rotation. If that
   happens, also rotate whenever row 0 equals `MapMetaData` `+0xFC`.
2. **Tick cadence.** Rotation is bounded by progress reports. A long single step (terrain, a big
   W3D batch) freezes the screen and the tip with it. That is acceptable, but it is worth timing
   the longest gap on a large Edain map.
3. **Wrapping.** `ListBox.wnd` has one column, `COLUMNSWIDTH: 100`. Map descriptions already wrap
   there. Confirm a tip does too, and whether a `\n` in a tip needs splitting into rows the way
   the lobby's `0x00702D09` splits on `0x0A`.
4. **First fill vs first tick.** If the gadget registers after the last progress report of a fast
   load, no tip ever shows. Check this on a small map.
5. **Local slot on every path.** Check that a skirmish, a LAN host, a LAN client and an observer
   each resolve to their own seat. `getLocalSlotNum` is virtual, so each `GameInfo` subclass
   answers it its own way. Seeing a Mordor tip as the Gondor client of a Gondor-vs-Mordor LAN game is
   the test that matters. Also confirm a Random seat shows its drawn faction.

## Tests (when built)

- Stock bytes: `[0x00C50920] == 0x0081C5D3`, plus the call shapes used (`0x009766B5..0x009766CC`,
  the `fetch` vtable offset at `0x0070225E`).
- Apply/verify/detect round-trip.
- Emulated (Unicorn, like `test_special_power_object_cap_emulated.py`): run `rotate_tips` against
  stubbed `TheGameText` / list-box calls. Check that it does nothing on a null box or a count of 0,
  holds the text until `due`, never repeats inside one pass of the bag, and resets on a new `ls`.
  For factions: the faction pool is used when the local slot's template resolves, only the general
  pool is used for an observer (`-2`), a null `GameInfo` or a null template, `faction_weight`
  scales the share, and `general_tips=False` falls back to the general pool when the faction has
  no tips.

## Not covered

- **Per-map tips** (`MAP:<name>/Tip%d`, from the map's own `map.str`). It would be a third pool
  in the same bag. Deferred until the faction version has run.
- **Opponents' factions** ("you face Mordor: …"). The same walk over the other occupied slots
  would give it, but it is a separate design question how many pools to mix.
- **Campaign and Living World load screens** that are not this class (other vtables, other
  `.apt`). This patch only reaches the multiplayer/skirmish load screen.
- **Animation between ticks.** Not possible without a timer that renders outside the progress
  callback. The engine draws the load screen only on a progress report.
