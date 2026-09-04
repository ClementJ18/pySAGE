# `GameInfo` — the structure a command-line game is set up through

Engine build `2.01.2614.37001`. Addresses are VAs (ImageBase `0x400000`, no ASLR); the file offset
is `VA - 0x400000`. Read **statically** with the skill's `explore.py` and **confirmed live** on
2026-09-01 by reading a running `game.dat` with `sage_live`'s `ProcessMemory` — the layout below is
observed memory, not inferred offsets, except where a row says otherwise.

**The question.** A test or training harness wants to start a specific match from the command line:
this map, these seats, these factions, no menus. `-file <map>` is the stock entry point for that
([`headless.md`](headless.md) §1), and it builds a `GameInfo` from defaults nobody had inspected.
This is that inspection.

**Status.** Solved, and shipped as a patch. A `-file` start runs a real skirmish — map loaded,
both seats created with the right factions, bases unpacked, income flowing, frames advancing — and
`command-line-skirmish` (`patches/experimental/command_line_skirmish.py`) does it in the binary.
§6 records the procedure the patch implements, which is also how it was worked out: by writing the
five things into a running process with `ProcessMemory(writable=True)` before any byte was patched.

**A section-modified `game.dat` only runs under that name.** The same bytes renamed die instantly
with an access violation inside `msvcr71.dll`, while an *unpatched* copy runs under any name — so a
patched build has to be installed as `game.dat` to be tested at all, and "try the copy" proves
nothing. This cost an hour of bisecting a patch that turned out to be fine; `live-bridge` and an
appended **empty** section fail the same way under a new name.

## 1. The argument form is the first gate, and it is not the obvious one

`-file`'s handler (`0x007BACA4`) stores its argument into `GlobalData+0xABC` and then hands that
string to a path builder at `0x007BAADF`:

```asm
007bacb8  push [ecx+4]                ; the argument
007bacbb  lea  ecx, [eax+0xabc]
007bacc1  call ASCII_STRING_SET       ; GlobalData+0xABC = argument
007bacd2  add  eax, 0xabc
007bacd8  call 0x7baadf               ; builder(&+0xABC, &+0xAB8)
```

The builder requires the name to end in `.map` (`0x00BFE9BC`), then looks for a `\` (`0x5C`) or `/`
(`0x2F`); a name with no separator takes a different branch (`0x007BAC73`) and is left alone. When
there **is** a separator it rewrites `+0xABC` in place, **inserting the file's own stem as a
directory** before the basename. Measured live, by reading `GlobalData+0xABC` five seconds into a
run:

| `-file` argument | `GlobalData+0xABC` afterwards | matches a cache key |
|---|---|---|
| `maps\map mp harlindon\map mp harlindon.map` | `maps\map mp harlindon\map mp harlindon\map mp harlindon.map` | no — the folder is inserted a second time |
| `map mp harlindon.map` | `map mp harlindon.map` (no separator, untouched) | no — the key needs the `maps\` prefix |
| **`maps\map mp harlindon.map`** | **`maps\map mp harlindon\map mp harlindon.map`** | **yes** |

So the form the engine wants is the one that looks wrong: **the containing folder is supplied by
the builder, not by the caller.** An absolute path fails for the same reason.

`+0xAB8`, the builder's second output, is not a path at all — it is the auto-generated recording
name, observed as `_map mp harlindon_20260901-155729`.

## 2. The lookup, and what it gates

`GameEngine::init` creates `TheMapCache` (`0x00DE4B74`, `new(0x24)` at `0x0063C920`, ctor
`0x0063ACF6`) and populates it at `0x00706F1E`, then:

```asm
0063c9eb  cmp  [0xde4b74], ebx        ; no cache -> esi stays 0
0063c9f1  je   0x63ca11
0063ca0a  call 0x703c91               ; esi = TheMapCache->find(GlobalData+0xABC)
...
0063ca1e  cmp  esi, ebx
0063ca20  je   0x63cb95               ; not found      -> failure branch
0063ca28  cmp  byte [esi+0x24], bl
0063ca2b  je   0x63cb95               ; not multiplayer -> failure branch
```

`0x00703C91` is a `std::map` lookup (`PREFERENCES_MAP_FIND`, `0x00456726`) returning `node+0x14` or
NULL.

**The failure branch is silent and lethal.** `0x0063CB95` skips the whole `GameInfo` construction
and appends game mode **0** where the success path appends **2** (`GAME_MODE_SKIRMISH`), through
`GameMessage::appendIntegerArgument` (`0x007111E5`) on the `MSG_NEW_GAME` message. The engine then
runs with no seats and no terrain, and dies in `TheTerrainVisual` — see [§5](#5-the-failure-mode).

### `TheMapCache` and `MapMetaData`, as read live

431 entries in the Edain install. The tree nodes are not the usual MSVC order — established by
walking all 431 and checking `root->parent == head` and `head->parent == root`:

| offset | node field |
|---|---|
| `+0x00` | colour / `_Isnil` flags |
| `+0x04` | `_Parent` |
| `+0x08` | `_Left` |
| `+0x0C` | `_Right` |
| `+0x10` | key, an `AsciiString` — the lowercased map path |
| `+0x14` | `MapMetaData` |

| offset | `MapMetaData` field | evidence |
|---|---|---|
| `+0x24` | `isMultiplayer` (byte) | 1 for every `map mp …`, 0 for every `map edain wor …`; it is the gate at `0x0063CA28` |
| `+0x28` | file size | 487138 for `map mp harlindon`, and lands in `GameInfo+0x48` |
| `+0x2C` | CRC | lands in `GameInfo+0x44` |

Keys are lowercase. Maps inside the `.big` archives are keyed relative (`maps\…`); maps in the
user folder are keyed by **absolute** path under `My Rise of the Witch-king Files` — not the BFME2
user folder, which is a separate directory and is not what RotWK scans.

## 3. What the auto-start actually sets

`0x0063CA31`–`0x0063CB7B`, in order:

| site | call | meaning |
|---|---|---|
| `0x0063CA3B` | `operator new(0xE9C)`, ctor `0x00628B3A` | `sizeof(GameInfo) == 0xE9C`; stored to `0x00DE8930` |
| `0x0063CA74` | `getSlot(0)`, then two dword copies | `GameInfo+0x38`/`+0x3C` = `slot[0]+0x38`/`+0x3C` |
| `0x0063CAB6` | `0x00955CAB(GameInfo, time(0))` | the seed |
| `0x0063CAD7` | `0x00801C46(GameInfo, AsciiString)` | the map, from `GlobalData+0xABC` |
| `0x0063CAE5` | `0x0080298E(GameInfo, [esi+0x2C])` | the map CRC |
| `0x0063CAF3` | `0x00802A49(GameInfo, [esi+0x28])` | the map file size |
| `0x0063CB4B` | `0x008014F1(slot, 6)` | one `GameSlot`, state 6, named `"Test"` (`0x00BFE9B0`, wide) |
| `0x0063CB76` | `0x008016C3(GameInfo, 0)` | that slot becomes slot 0 |
| `0x0063CB7B` | `appendIntegerArgument(2)` | game mode 2 = skirmish |

**Only slot 0 is ever touched.** Nothing sets a side, a team, a colour, or an AI for any seat.

## 4. The structure

### `GameInfo` — `0xE9C` bytes

`0x00DE8930` is the skirmish instance (`THE_SKIRMISH_GAME_INFO`); `0x00DE892C` is `THE_GAME_INFO`.

| offset | field | evidence |
|---|---|---|
| `+0x00` | vtable | |
| `+0x18` … `+0x34` | `GameSlot *m_slot[8]` | `getSlot` is `mov eax, [ecx+eax*4+0x18]` under `cmp eax, 8`; live, each points at `+0xDC + i*0x1B8` |
| `+0x38`, `+0x3C` | two dwords seeded from `slot[0]` | `0x0063CA79`–`0x0063CA8E`; live `0` and `0x800000` |
| `+0x40` | map path (`AsciiString`) | live: `maps\map mp harlindon\map mp harlindon.map` |
| `+0x44` | map CRC | live value equals `MapMetaData+0x2C` |
| `+0x48` | map file size | live value equals `MapMetaData+0x28` |
| `+0x5C` … `+0x70` | the **skirmish options block** — see below | `-1` throughout in an auto-start, filled in a menu game |
| `+0xA0` … `+0xB8` | build identity, seven `AsciiString`s | live: `LOTRBFME2`, `BUILDER`, `builduser`, `FC32172E-8F97-4139-B810-342D63CDC43E`, `19:47:21`, `2007-03-30`, `Release` |
| `+0xDC` | `GameSlot m_slotData[8]`, stride `0x1B8` | live slot pointers |

#### The options block

Six consecutive dwords that a menu game fills and the auto-start leaves at `-1`:

| offset | menu game | what |
|---|---|---|
| `+0x5C`, `+0x60`, `+0x64` | 0 | unidentified |
| `+0x68` | 1 | unidentified |
| `+0x6C` | 100 | unidentified |
| `+0x70` | 1000 | **starting resources** — writing 1000 into an auto-start gave both players exactly 1000 |

`+0x70` is the field, and it is literal rather than scaled. Left at `-1` the engine falls back to
a path that ends at **4999** per player, one short of the 5000 an Edain fortress costs — so the
human cannot unpack a base, owns no buildings, and the match ends in defeat within thirty frames.
That single resource was the whole visible symptom of an unconfigured game. Which code produces
4999 from `-1` is not identified; setting the field explicitly makes it moot.

`0xDC + 8 * 0x1B8 = 0xE9C` exactly, so the slot array runs to the end of the object and the header
is `+0x00`–`+0xDB` with nothing unaccounted for. `+0x4C`–`+0x9F` and `+0xBC`–`+0xDB` are mapped but
not yet named.

### Two slot classes, and which global carries which

The menus and the auto-start do **not** populate the same object, and the two globals are never
both live:

| | global | slot vtable | slot stride |
|---|---|---|---|
| `-file` auto-start | `THE_SKIRMISH_GAME_INFO` `0x00DE8930` | `0x00BFE4F8` | `0x1B8` |
| the skirmish menus | `THE_GAME_INFO` `0x00DE892C` | `0x00C54B5C` | `0x1DC` |

Both put the array at `+0xDC` and share the first `0x1B8` of fields; the menu path's class adds
`0x24` bytes. The field table below is the base class, read from a menu game and confirmed against
an auto-start one.

### `GameSlot` — `0x1B8` bytes

The semantics come from a differential read on 2026-09-01: two configured skirmishes on
`map mp druadan forest`, differing in one seat's colour and start position, against the
auto-start's slots. Index orderings are from `__edain_data.big`, so the values below are
confirmations rather than inferences.

| offset | field | evidence |
|---|---|---|
| `+0x00` | vtable | `0x00BFE4F8` for the base class |
| `+0x04` | **state** | see the enum below |
| `+0x08`, `+0x09` | two bytes `setSlot` forces to 1 when slot 0 has state 6 | `0x008016E9`–`0x008016F3` |
| `+0x0C` | **colour**, an index into `multiplayer.ini`'s `MultiplayerColor` order | red → 1 and blue → 0 (`[0] ColorBlue`, `[1] ColorRed`); changing one seat to white moved it to **9** (`[9] ColorWhite`) and nothing else to 9 |
| `+0x10` | **start position**, 0-based | 1 → 2 when that seat was moved one position; the AI at the first position reads 0 |
| `+0x14` | start position again — tracks `+0x10` exactly | changed 1 → 2 in lockstep; which of the two is "requested" and which "granted" is undetermined (see Open 2) |
| `+0x18` | **playerTemplate** (faction), an index into `playertemplate.ini` order | Gondor → **3** = `FactionMen`, Mordor → **10** = `FactionMordor` |
| `+0x1C` | **team**, 0-based | team 1 → 0, team 2 → 1 |
| `+0x24`, `+0x28`, `+0x2C` | colour, start position, playerTemplate again | each equals its counterpart above in every sample — the requested/actual pair |
| `+0x30` | display name (`UnicodeString`) | the profile name for a human, `"Easy"` for an easy AI, `"Closed"` for a closed seat |
| `+0x34` | **the map-side player this seat binds to** (`AsciiString`) | `Player_<startPos + 1>`: the seat at start position 1 read `Player_2`, and reading `Player_3` after it moved to position 2; the AI at position 0 read `Player_1` |

`+0x34` is the answer to "which map player owns a seat's pre-placed objects", and it is derived
from the start position, not from the slot index.

#### `state` (`+0x04`)

| value | meaning | evidence |
|---|---|---|
| 1 | closed | `+0x30` reads `"Closed"`; the auto-start writes 1 into slots 1–7 |
| 2 | easy AI | `+0x30` reads `"Easy"` on a seat configured as an easy AI |
| 6 | local human | the auto-start's `push 6`, and `setSlot`'s special case for slot 0 |

0, 3, 4 and 5 are unobserved; the medium/brutal AI values and "open" are the obvious candidates.

### What the auto-start leaves unset

Against the table above, an auto-start slot 0 reads: colour `-1`, start position `-1`, **faction
`-2`**, team `-1`, no `+0x34`. Slots 1–7 are all state 1, closed. So the auto-start produces one
human with a random faction, no team, no colour and no start position, against seven closed seats
— which is the concrete shape of "not playable", and the list of fields a harness has to fill.

### Accessors

| address | what |
|---|---|
| `0x00800B55` | `GameInfo::getSlot(int)`, bounds-checked `0 <= i < 8` |
| `0x008016C3` | `GameInfo::setSlot(int, GameSlot)` — the slot arrives by value |
| `0x00801C46` | `setMap(AsciiString)` |
| `0x0080298E` | `setMapCRC(int)` |
| `0x00802A49` | `setMapSize(int)` |
| `0x00955CAB` | `setSeed(int)` |
| `0x00801415` | `GameSlot` constructor |
| `0x008014F1` | `GameSlot` setup — takes the state and the names |
| `0x006DCBFF` | `GameSlot::operator=` |
| `0x00635BD4` | `GameSlot` copy, for the by-value push into `setSlot` |

## 5. The failure mode

When the lookup fails, the engine does not stop. It runs on with no seats, never loads a map, and
faults in `TheTerrainVisual`:

```
0xc0000005  ACCESS_VIOLATION: read at 0x8    EIP = 0x004E09C6

004e09b8  mov eax, [esi + 0x37c0]    ; the heightmap - NULL
004e09c6  mov ecx, [eax + 8]         ; its width
004e09cc  mov eax, [eax + 0xc]       ; its height
```

Reached through `0x0063123A: call [eax+0x14]` on the global `0x00DE4AC8`, which is registered as
**`TheTerrainVisual`** (`0x00646EAD` stores it; the name at `0x00C04798` is registered against it at
`0x00646EC1`). `+0x37C0` is a refcounted member with two setters, `0x0046CF3A` and `0x0046D107`,
both releasing the old value and addref'ing the new.

That makes `TheTerrainVisual+0x37C0` a useful canary for a harness: **non-null means a map actually
loaded**, which is a far better check than "did it crash". Observed from outside, the same failure
reads as a player list holding only `ReplayObserver`, `frame` stuck at 0, and exit code 666 about
13 seconds in.

## 6. Making a `-file` start playable — the recipe

Verified on 2026-09-01 by writing into a running process with
`ProcessMemory(writable=True)`; the game reached a real match, the fortress unpacked, and play
continued. **Nothing here is a patch yet** — it is the list of what a patch would have to do.

Wait for `THE_SKIRMISH_GAME_INFO` to become non-null (about 8 seconds into a run; the pointer is
published at `0x0063CA62`, before the engine finishes configuring the object), then:

1. **Fill the slots.** Slot 0: state 6, faction, colour, team, start position, and their
   `+0x24`/`+0x28`/`+0x2C` counterparts. Slot 1: state 2 for an easy AI, likewise. Slots left at
   state 1 stay closed, which is fine.
2. **Give each slot its map-player binding at `+0x34`.** This is an `AsciiString`, so it needs a
   block rather than an integer: `VirtualAllocEx` a page and write

   ```
   +0x00  dword  refcount        (a large value, so nothing can free it)
   +0x04  word   length
   +0x06  word   allocated
   +0x08  chars  "Player_<startPos + 1>\0"
   ```

   confirmed against the engine's own strings — the map path at `GameInfo+0x40` reads
   `refcount=4 len=42 alloc=60` with its characters at `+8`.
3. **Set the options block**, at least `+0x70` (starting resources). Without it the players get
   4999 and cannot afford a fortress.
4. **Point `TheGameInfo` at it**: `[0x00DE892C] = [0x00DE8930]`. `GameLogic::update` reads the
   *former* and the auto-start fills the *latter*, so frame 1 faults without this:

   ```asm
   0062e714  mov eax, [0xde892c]     ; TheGameInfo, null on a -file start
   0062e719  mov ecx, [eax + 0xc]    ; faults
   0062e721  div ecx                 ; frame % [GameInfo+0xC], which is 100
   ```

5. **Get past the loading screen.** `0x0081C64A` dereferences a window that a menu-less start
   never creates (§5's sibling problem). Skipping the 24 bytes from `0x0081C64A` to `0x0081C662`
   — the whole progress-bar update — is enough. A real patch wants a null check instead, which
   does not fit in place: the guard plus the original tail is 28 bytes in a 24-byte block, so it
   needs a cave.

With all five, the engine loads the map, creates the players with the right factions and names,
honours the start positions (Edain's own scripts spawn the starting troops and give the AI its
base), and runs. Observed as: 5 players, ~370 objects, frames advancing normally.

**Edain's map scripts unpack a base for an AI but not for a human.** The script log shows
`Player_2/Start entpacken` and `Player_2/Festung__1` firing under the AI's `KI leicht` branch,
with no counterpart under `Player_1` — a human is expected to buy the fortress from the plot at
their start position, which is why the starting-resource field is load-bearing rather than
cosmetic.

## Open

1. **More play.** `command-line-skirmish` has had exactly one session: one map, one mod, two
   factions, 131 frames. It is `experimental` for that reason and not because anything is known to
   be wrong with it. The things most likely to break first are a map whose start positions are not
   0 and 1, a faction index that is not a playable side, and more than two seats — none of which
   has been tried.
2. **Where does 4999 come from?** With `GameInfo+0x70` at `-1` both players start on 4999.
   Setting the field makes it literal, so the fallback path is unexamined — but it is the sort of
   thing that will resurface as a surprise somewhere else.
3. **What are `+0x5C`, `+0x60`, `+0x64`, `+0x68`, `+0x6C`?** A menu game holds 0, 0, 0, 1, 100.
   Only `+0x70` has been identified. Changing one option at a time in the lobby and re-dumping is
   the same differential method that solved the slot fields.
4. **Are `+0x10` and `+0x14` requested vs granted start position?** They hold the same value in
   every sample taken. Separating them needs a case where the two disagree — two seats asking for
   the same start position is the obvious way to force it.
5. **The rest of the `state` enum.** 1, 2 and 6 are known. The medium and brutal AI values and
   "open" are unobserved; a lobby with one seat of each would settle all of them in one read.
6. **What are `GameInfo+0x38`/`+0x3C`?** Seeded from slot 0 before the slot is configured, so they
   are read from a default-constructed slot. Live values `0` and `0x800000`.
7. **Is `MapMetaData+0x24` really `isMultiplayer`?** It partitions the 431 cached maps exactly
   along the `map mp …` / `map edain wor …` naming split, which is strong but circumstantial; the
   field has not been traced to whatever writes it during the cache scan.
8. **What does the menu slot class add in its extra `0x24` bytes?** Unexamined — it is not on the
   auto-start path, so nothing needs it yet.

## Method and provenance

Static reading with the skill's `explore.py` over `game.dat`; byte scans for struct displacements
(`c0 37 00 00`, `c4 0a 00 00`) with `re.finditer` over the raw image.

The image is **stock**: `sage-patch sagepatch` reports "no known patch found", and the repo's
`game.dat`, the install's `game.dat` and its `game_original.dat` are byte-identical
(sha256 `5481de75…`, 11,346,944 bytes), so every site cited here is untouched engine code and the
live reads came from the same bytes.

Live confirmation used `sage_live.backends.memory.ProcessMemory` against a running `game.dat`
started as `game.dat -file <map>` from its own directory, read from a **non-elevated** shell.

The slot semantics come from a differential read rather than from the disassembly, because every
`GameSlot` accessor is inlined in this build — the class's vtable holds seven entries and none of
them is a getter (the string `"GameSlot"` sits immediately after it at `0x00BFE514`). Three
observations were compared: the `-file` auto-start, and two menu skirmishes on
`map mp druadan forest` that differed only in one seat's colour and start position. The colour and
faction orderings were read out of `__edain_data.big`'s `multiplayer.ini` and `playertemplate.ini`,
so each field was checked against a predicted index instead of being guessed from context.
