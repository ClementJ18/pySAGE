# The lobby map list: `MapCache` attributes, the star/hammer icon, and adding symbols

Recovered against RotWK 2.01 `game.dat` build `2.01.2614.37001`, 2026-09-08, by static analysis
only. **Nothing here has been confirmed against a running game**; §7 is the test that would.

**The finding in one sentence.** The icon beside a map name is not a star-or-hammer boolean but the
low end of a **32-bit sort key** the lobby writes into `MapMetaData+0xF4` before it sorts the list -
`isOfficial` only contributes bit 15 - so "more symbols" means widening that key and the twelve-image
ladder that reads it, and the sorting then follows for free.

## 1. `MapCache` as the INI sees it

`maps\mapcache.ini` is not parsed through the global block-type table - there is no `MapCache`
string in the image. `MapCache::loadCacheINI` (`0x00701EE0`-ish) calls `INI::load` (`0x0042D753`)
with **one** block-parse callback, `parseMapCacheDefinition` (`0x0093B9F0`), and that callback takes
the block's second token as the map key, then runs `INI_PARSE_FIELDS` (`0x0042DB80`) over the field
table at **`0x00C7FAE8`** - 24 rows plus a NULL terminator, `0x190` bytes.

The table is referenced from exactly two places, which is what makes it relocatable:

| site | bytes | what |
|---|---|---|
| `0x0093B446` | `b8 e8 fa c7 00` | `mov eax, 0xc7fae8` / `ret` - the table getter |
| `0x0093BA80` | `68 e8 fa c7 00` | `push 0xc7fae8` into `INI_PARSE_FIELDS` |

`offset` below is into the **parse-time temporary** (`[ebp-0x26c]`, `0x26c` bytes), not into the
cache entry. `parseMapCacheDefinition` copies the temporary field by field into a real
`MapMetaData` and only then inserts it, so the two layouts differ - see §2.

| row | keyword | parse fn | type | temp offset |
|---|---|---|---|---|
| 0 | `isOfficial` | `0x0042E558` | `Bool` | `+0x28` |
| 1 | `isMultiplayer` | `0x0042E558` | `Bool` | `+0x1C` |
| 2 | `isScenarioMP` | `0x0042E558` | `Bool` | `+0x1D` |
| 3 | `extentMin` | `0x0042F247` | `Coord3D` (`X: Y: Z:`) | `+0x00` |
| 4 | `extentMax` | `0x0042F247` | `Coord3D` | `+0x0C` |
| 5 | `numPlayers` | `0x0042EC5E` | `Int` | `+0x18` |
| 6 | `fileSize` | `0x0042ECB2` | `UnsignedInt` | `+0x34` |
| 7 | `fileCRC` | `0x0042ECB2` | `UnsignedInt` | `+0x38` |
| 8 | `timestampLo` | `0x0042EC5E` | `Int` | `+0x2C` |
| 9 | `timestampHi` | `0x0042EC5E` | `Int` | `+0x30` |
| 10 | `displayName` | `0x0042EE5E` | `AsciiString` | `+0x20` |
| 11 | `description` | `0x0042EE5E` | `AsciiString` | `+0x24` |
| 12 | `supplyPosition` | `0x0093B4E5` | `Coord3D`, appended to a list | - |
| 13 | `techPosition` | `0x0093B512` | `Coord3D`, appended to a list | - |
| 14-21 | `Player_1_Start` .. `Player_8_Start` | `0x0042F247` | `Coord3D` | `+0x3C` + `0xC`*n |
| 22 | `InitialCameraPosition` | `0x0042F247` | `Coord3D` | `+0x9C` |
| 23 | `PlayerPosition` | `0x0093B9BD` | sub-block (`Computer`, `Human`, `AllowedFactions`, `ForcePlayerTeam`, `LoadAIScripts`; table `0x00C7FD78`) | - |

`displayName` and `description` are parsed as `AsciiString` and converted to `UnicodeString` on the
way into the cache entry (`0x0093BB4B` / `0x0093BB84`, then `0x00436A90`).

**Unknown keywords are fatal.** A `mapcache.ini` carrying a field this table does not name will not
load on a stock binary - so shipping a new field and shipping the patch that adds its row are the
same decision.

### The writer

`MapCache::writeCacheINI` (entry ~`0x00704C50`, opens the file at `0x00704CAA` with mode `"w"`, name
built from `MapCache.ini` at `0x00C1D944`) emits every field with its own `fprintf` format string;
the block header is `MapCache %s` at `0x00C1DBF4` and the field formats live in
`0x00C1D9D4`-`0x00C1DBF0` (`isOfficial = %s` at `0x00C1DB94`, `numPlayers = %d` at `0x00C1DB50`, and
so on). A field the writer does not emit is lost the next time the engine regenerates the cache.

## 2. `MapMetaData`, as the cache holds it

Constructor `0x007049A8`, assignment operator `0x00704AD0` - which is what pins the layout, because
it copies every member in order and its last one is `+0xFC`. The entry sits **inline** in the
`TheMapCache` (`0x00DE4B74`) tree node at `node+0x14`, keyed by the lowercased map path at
`node+0x10`.

| offset | field | evidence |
|---|---|---|
| `+0x00` | `UnicodeString m_displayName` | assigned at `0x0093BB53` |
| `+0x04` | `UnicodeString m_description` | assigned at `0x0093BB8C` |
| `+0x08` | `Coord3D extentMin` | `rep movsd` of 6 dwords from the temp, `0x0093BAAF` |
| `+0x14` | `Coord3D extentMax` | same copy |
| `+0x20` | `Int numPlayers` | `0x0093BACC`; read by the lobby at `0x008466C9` |
| `+0x24` | `Bool isMultiplayer` | `0x0093BAB7`; the auto-start gate at `0x0063CA28` |
| `+0x25` | `Bool isScenarioMP` | `0x0093BAC0` |
| `+0x26` | `Bool isOfficial` | `0x0093BAB1`; the filter at `0x007017FF`, the icon at `0x00846590` |
| `+0x28` | `UnsignedInt fileSize` | `0x0093BAD8` |
| `+0x2C` | `UnsignedInt CRC` | `0x0093BAE4` |
| `+0x30` | `Int timestampLo` | `0x0093BAF0` |
| `+0x34` | `Int timestampHi` | `0x0093BAFC` |
| `+0x38` | `std::map` of waypoints | `0x0093BBDB`, keys formatted `Player_%d_Start` (`0x00BFDA18`) |
| `+0x48`, `+0x4C` | two containers built by `0x0082147E` | ctor only |
| `+0x50` | `AsciiString` map file name | the stats key at `0x00846461`, appended to the screen's parallel name vector at `0x0084670A` |
| `+0x54` | container copied by `0x0070448C` | ctor `0x00704456` |
| `+0xF4` | `Int` - **the lobby's sort/icon key**, see §3 | written only by the fill at `0x008464xx`, copied at `0x00704AF5` |
| `+0xF8`, `+0xFC` | two `UnicodeString`s | `0x00704B0E`, `0x00704B20` |

`sizeof(MapMetaData)` is `0x100`. **There is no spare slot**, and because the entry is inline in the
map node it cannot be widened without patching the node allocator - which is what shapes §4.

`MapCache::getMapList(flags, out)` (`0x00703C2E`) walks the tree and pushes each `node+0x14` into a
`std::vector<MapMetaData*>`, keeping whatever the predicate at `0x007017F4` accepts:

| bit | meaning |
|---|---|
| `0x01` | accept official maps |
| `0x02` | accept user maps |
| `0x04` | reject multiplayer maps |
| `0x08` | reject single-player maps |
| `0x10` | reject `isScenarioMP` maps |
| `0x20` | reject non-`isScenarioMP` maps |
| `0x40` | do not clear `out` first |

The lobby asks for `0x1B` (`0x0084678D`): both official and user, multiplayer, not a scenario. Bits
`0x80` and up are free.

## 3. The list, the icon and the sort

One function fills the list - `0x008460B5`, called only from `0x00846791`, on the game-setup screen
whose `MapList` listbox lives at `this+0x394` (bound by name in the gadget dispatcher at
`0x0084091B`). The listbox is given **five columns** at `0x00840959` through
`GadgetListBoxSetColumns` (`0x00726D36`), widths `{8, 2, 70, 10, 10}`; the fill writes the icon into
column `0`, the name into column `numColumns-3` (= 2) and the player count into column
`numColumns-1` (= 4). **Columns 1 and 3 are never written.**

`0x008460B5` resolves twelve images up front through the mapped-image lookup (`0x006DA34C` on
`TheMappedImageCollection`, `[0x00DE4AC0]`):

| `isOfficial` | not conquered | Easy | Medium | Hard | Brutal | Max |
|---|---|---|---|---|---|---|
| yes | `AptDifficultyNotConquered` | `AptDifficultyEasyConquered` | `AptDifficultyMedConquered` | `AptDifficultyHardConquered` | `AptDifficultyBrutalConquered` | `AptDifficultyMaxConquered` |
| no | `AptUserMapNotConquered` | `AptUserMapEasyConquered` | `AptDifficultyMedConquered` | `AptUserMapHardConquered` | `AptUserMapBrutalConquered` | `AptUserMapMaxConquered` |

The medium user-map cell is not a mistake in this table: `0x00846273` loads
`AptDifficultyMedConquered` a second time, because no `AptUserMapMedConquered` string exists in the
image.

### Pass 1 - the key (`0x0084643F` .. `0x008465A7`)

For every `MapMetaData *esi` in the vector:

* not multiplayer (`byte [esi+0x24]` zero) - `[esi+0xF4] = 0`;
* otherwise the player's stats object is asked, difficulty 6 down to 2, for a win on this map name
  (`[esi+0x50]`), and `[esi+0xF4]` becomes the highest that answers - `6`..`2`, or `1` for none;
* then the only thing `isOfficial` does:

```asm
00846590  80 7e 26 00            cmp  byte [esi+0x26], 0
00846594  75 07                  jne  0x84659d
00846596  80 8e f5 00 00 00 80   or   byte [esi+0xf5], 0x80   ; +0xF4 |= 0x8000
```

So the key is `1..6` for an official map and `0x8001..0x8006` for a user map, and **bit 15 is the
whole star/hammer distinction**. Thirteen bytes, one branch.

### The sort (`0x0084606C`)

An introsort over the vector with a two-dword functor read from `this+0x3AC` (primary) and
`this+0x3B0` (secondary). The comparator is `0x0084246C`; it computes three deltas once -
`a->numPlayers - b->numPlayers`, a `UnicodeString` compare of the display names, and
`a->key(+0xF4) - b->key(+0xF4)` - then walks up to two column codes:

| code | field | direction |
|---|---|---|
| 0 / 1 | display name | ascending / descending |
| 2 / 3 | `numPlayers` | ascending / descending |
| 4 / 5 | the `+0xF4` key | ascending / descending |

A tie falls through to the next code, then to name, players, key and finally pointer identity. The
defaults are set at `0x008451A9`: primary `2`, secondary `0`. The three column headers call
`setSortColumn` (`0x0084010E`) through thunks at `0x00840143`, `0x0084014D` and `0x00840157`,
pushing `0`, `2` and `4`; clicking the active column flips it to `col+1`, otherwise the old primary
becomes the secondary.

**The icon column is already a sort key.** Whatever goes into `+0xF4` is what the icon header sorts
by, and codes `4`/`5` need no change.

### Pass 2 - the row (`0x008465E5` .. `0x0084672C`)

`eax = [esi+0xF4]`, then a ladder: `<= 1` keeps the default `AptDifficultyNotConquered`, `2..6` pick
the official medals, `0x8000..0x8001` picks `AptUserMapNotConquered`, `0x8002..0x8006` pick the
user-map medals, anything else draws nothing. The row is then added (`0x00726DD4`, with the key as
item data), the image goes into column 0 (`0x00725DCC`), the display name into column 2 and
`numPlayers` into column 4 (both `0x00728632`), and `[esi+0x50]` is appended to the screen's
parallel file-name vector at `this+0x398`.

The ladder's entry bytes:

```asm
008465e5  8b 45 e8              mov  eax, [ebp-0x18]
008465e8  8b 30                 mov  esi, [eax]
008465ea  8b 86 f4 00 00 00     mov  eax, [esi+0xf4]
008465f0  3d 01 80 00 00        cmp  eax, 0x8001
```

## 4. What "more symbols" costs, and where the value lives

Three things have to change, and only three: a per-map value the INI can say, carried from
`parseMapCacheDefinition` to the cache entry; that value folded into `+0xF4` so the sort follows;
and pass 2's ladder extended to pick an image for it. Nothing about the comparator, the header
buttons, the listbox or the `.wnd` has to move.

The obstacle is storage. `MapMetaData` is full (§2) and sits inline in a `std::map` node, so it
cannot be widened without patching the node allocator. A side table keyed beside it would need a
key that outlives a cache rebuild - which rules out the entry pointer, since a rescan destroys and
re-creates entries (`0x007065D6`, `0x00706691`), and leaves copying every map's file name into the
cave.

**Bits 16-31 of `+0xF4` are the storage**, and they are better than a side table on every axis
that matters here: the structure's own copy constructor (`0x00705274`) and assignment operator
(`0x00704AF5`) carry them, and the comparator reads them as part of the sort key, which is the
behaviour wanted anyway. Nothing else in the image writes `MapMetaData+0xF4` - a scan of every
`disp32` form over `.text` finds the constructor's zero, those two copies, the lobby's pass 1, and
the comparator's two reads, and nothing else.

The one thing those bits are not is durable across a fill: **pass 1 rewrites `+0xF4` from scratch**
for every entry it looks at, on both of its paths. So the patch brackets the pass - it saves the
symbol half of the key as pass 1 picks an entry up, and ORs it back thirteen bytes from the end of
the same iteration.

## 5. The patch

`map-list-symbols`, in [`../patches/map_list_symbols.py`](../patches/map_list_symbols.py). One
`.mapsym` cave, eight rewritten sites - nine with either sort option - no `.wnd` and no `.apt`
change.

Every address below is named in [`../addresses.py`](../addresses.py) under `MAP_CACHE_*`,
`MAP_META_DATA_*` and `MAP_LIST_*`, which is where facts about this build live; the patch module
holds only what is its own choice - the keyword, the section, the packing and the image names.

### 5.1 The INI surface

`mapSymbol = <Int>`, `0` (the default) meaning "behave exactly as today". The field table is
copied into the cave with a 25th row appended and both references repointed; the row's parse
function is the cave's own, which reads an `Int` through `INI_PARSE_INT` exactly as `numPlayers`
does and then **ignores the `store` it was handed**, writing a cave global instead. That is what
spares the patch from having to prove anything about the parse temporary's layout past `+0xA8`.
An out-of-range or negative value reads as 0 rather than as an error.

`mapcache.ini` is not part of the INI surface `sage_ini` models - it is parsed through a callback
of its own rather than through the engine's block-type table, and there is no `MapCache` block in
the schema - so the patch declares no `ini_surface`.

### 5.2 The sites

| site | stock bytes | what the detour does |
|---|---|---|
| `0x0093B447` | the getter's imm32 | the field table lives in the cave |
| `0x0093BA81` | the parse call's imm32 | the same |
| `0x0093BA8C` | `call INI_PARSE_FIELDS` | clear the pending symbol, then tail-jump into the parser, so a block that declares nothing starts from zero |
| `0x0093BCE4` | `call MapMetaData::operator=` | run the stock copy, then write `symbol << 16` into the **stored** entry's key |
| `0x008460E7` | `push <"AptDifficultyNotConquered">` | resolve this patch's images, once per fill, beside the stock twelve |
| `0x00846443` | pass 1's per-entry preamble | save the entry's symbol bits before the difficulty stores land |
| `0x00846590` | pass 1's `isOfficial` bit, 13 bytes | the stock bit, then the symbol back on top |
| `0x008465EA` | pass 2's ladder entry, 11 bytes | draw the symbol's image, or hand the row back to the ladder |
| `0x008424E2` | the comparator's key delta, 17 bytes | **the sort options only** - `--sort-by-symbol` masks both operands so nothing below the symbol orders the list; `--sort-by-icon` ranks both so the difficulty outranks the `isOfficial` bit |

Three of those are load-bearing in a way the bytes do not show.

**The comparator hook takes seventeen bytes, not twelve**, and both sort options pay it. The stock
arm is
`mov eax, [ebx+0xF4]` / `mov ecx, [ebp-0x10]` / `sub eax, [edi+0xF4]` / `mov ecx, [ecx]` - the sort
functor's load sits *between* the two halves of the subtraction, so a hook over the delta owes the
caller both. `edx` is free scratch: the stock code zeroes it four bytes past the resume point.

**The store hook cannot tail-jump.** `MapCache::insert` (`0x0070659C`) is `ret 4` and returns the
stored entry in `eax`; the `push` that supplied its second argument survives as the argument to
`MapMetaData::operator=`, which is `ret 4` in turn. So the cave pushes a second copy, calls, pops
its saved `this`, writes the key and returns `ret 4` itself. It also has to run the stock copy
**first**: that copy takes `+0xF4` from a freshly constructed source, so anything written before it
is overwritten with zero.

**The save hook sits between a `cmp` and its `je`.** `0x0084643F` tests the player's stats object
for NULL and `0x00846448` branches on it; the two instructions between are what the hook replaces.
Everything the cave adds is therefore bracketed by `pushfd`/`popfd`. Without that, every
non-multiplayer map takes the wrong arm.

**The pick stub has three ways out**, and the two that decline have to leave the ladder exactly
what it expects - the key in `eax` and the flags of `cmp eax, 0x8001`, which is branched on five
bytes past the point it rejoins. The way out that *does* draw a symbol writes the image into
`[ebp+8]`, the same local the ladder's arms write, and jumps to `0x00846674` where they converge.

### 5.3 The key, packed

```
bits 0-3    the conquered difficulty, 1..6, written by pass 1 (0 = not multiplayer)
bit  15     isOfficial == No, written by pass 1
bits 16-31  mapSymbol, written at parse time and carried across pass 1 by the bracket
```

Putting the symbol above bit 15 is what makes it the **primary** grouping when the icon column is
sorted, with official-versus-user the tiebreak inside a symbol and difficulty the tiebreak inside
that. The comparator subtracts whole keys, and the largest key a 99-symbol build can produce is
`0x00638006`, so nothing overflows into the sign.

That tiebreak is what the two sort options rework. Maps sharing a symbol are contiguous under all
three - the symbol is the high half of the key - but by default the order *within* a group is
official-then-difficulty, and that middle field is the problem: it splits a symbol's easy-conquered
maps in two, one run of official ones and one of user ones, with every other official difficulty in
between. Both options hook the same seventeen bytes, the comparator's key delta at `0x008424E2`, so
**at most one can be installed**.

**`--sort-by-symbol`** masks both operands to `0xFFFF0000`, so two maps carrying the same symbol
**tie**. A tie is what sends the comparator on to its next key, which is the secondary sort column -
the display name unless another header has been clicked. The cost is that untagged maps tie with
each other too: with it installed, sorting by the icon column no longer separates official from user
maps, because that distinction lives in a bit the comparator has stopped looking at.

**`--sort-by-icon`** keeps every field and reorders two of them. It ranks each operand as

```
symbol | difficulty << 1 | isOfficial-is-No
```

and subtracts the ranks, which is the stock key with its low two fields swapped: symbol, then the
conquered medal, then the star or hammer. Every map carrying one symbol and beaten on one difficulty
is then contiguous, which is the ordering the icon column looks like it should have - it groups by
the picture it is drawing. Nothing is masked away, so untagged maps still order by medal and then by
star-before-hammer rather than tying.

The rank cannot carry into the symbol. The difficulty is `0`..`6` and the official bit is one bit,
so the two low fields together reach `13`, and bits 4-15 stay clear. The ranking is a local
subroutine in the cave because it runs on both operands; it spends `eax`, `ecx` and `edx`, which are
exactly the three this arm owns - `ecx` because the displaced functor load rewrites it on the way
out, `edx` because the stock code zeroes it four bytes past the resume point.

Neither option changes anything else. The key still carries the difficulty and the `isOfficial` bit,
and pass 2 still reads the key itself, so the icon tracks the conquered state exactly as before
under all three modes.

### 5.4 The images

Symbol `NN` draws `AptMapSymbolNN<state>`, `<state>` being the engine's own six - `NotConquered`,
`EasyConquered`, `MedConquered`, `HardConquered`, `BrutalConquered`, `MaxConquered` - so **the
conquered medal survives**: the symbol replaces the family of twelve, not the key that chooses
within it. A seventh name per symbol, the bare `AptMapSymbolNN`, is the fallback for a mod that
does not care about difficulty, and a symbol with no images at all falls back to the stock medal.
That last fallback is what makes a half-installed image set degrade one row at a time rather than
blanking the column.

They are resolved by name through the same lookup the stock twelve use (`0x006DA34C` on
`TheMappedImageCollection`, `[0x00DE4AC0]`), **once per fill** - not per row, and not cached across
fills, so a reloaded `MappedImage` set is picked up the next time the screen opens. The
`AsciiString` that lookup wants is built and destroyed with the engine's own constructor and
destructor rather than by handing it a static string object it might retain.

## 6. What this does not do

* **`MapCache::writeCacheINI` is not patched**, so it does not emit `mapSymbol`. That costs nothing
  for maps a mod ships in its archives - the engine cannot write into a `.big` and never rewrites
  that file - but a `mapSymbol` hand-written into the **user** maps folder's own cache is dropped
  the next time the engine regenerates it. Adding the emitter is one more hook in the writer's
  field block (`~0x00704C50`, formats in `0x00C1D9D4`-`0x00C1DBF0`) if that gap ever bites.
* **Column 3 stays empty.** The listbox has five columns and the fill writes 0, 2 and 4, so a
  *second* icon could be added without a `.wnd` change - but it would be unsortable until a fourth
  header button, a fourth `setSortColumn` thunk (`0x0084010E`) and comparator codes `6`/`7` exist.
  The symbol replaces the medal instead, which needs none of that.
* **`isOfficial` keeps every other meaning it has** - the `0x01`/`0x02` filter bits behind the
  system-maps/user-maps radio buttons (`0x007017FF`), and the check at `0x00849E1F`.
* **No filter by symbol.** `MapCache::getMapList`'s flag byte has bits `0x80` and up free if that
  is ever wanted.

## 7. What has and has not been established

**Static only.** Every claim above carries its site, the patch applies and verifies against a
stock `game.dat` and against the stand-in in
[`../../tests/sage_patch/synthetic.py`](../../tests/sage_patch/synthetic.py), and the suite
disassembles the cave back and asserts what it says. None of that is play: a patch is a reading of
the machine code and its tests are written from the same reading, so a wrong reading passes both.

The in-game check is a mod that defines two symbols, gives two maps different `mapSymbol` values,
and:

1. opens the skirmish lobby and confirms both rows draw their own icon and the rest draw the stock
   star or hammer;
2. clicks the icon column header and confirms the symbols group, with official and user maps
   separating inside each group - and, on a `--sort-by-icon` build, that the medal separates first
   instead, so one symbol's easy-conquered maps are a single run;
3. beats one of them on a difficulty and confirms the row's icon follows the medal;
4. defines only a bare `AptMapSymbolNN` for the second symbol and confirms it draws at every
   difficulty;
5. deletes one symbol's images entirely and confirms that row falls back to the stock medal rather
   than blanking.

One assumption is worth confirming while doing that: the skirmish lobby and the multiplayer lobby
being the same instance of this screen is *inferred*, from there being exactly one caller of
`0x008460B5` and one user of the twelve stock image names.
