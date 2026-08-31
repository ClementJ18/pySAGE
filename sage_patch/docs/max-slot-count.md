# `MAX_SLOTS` — more than 8 players in one game

Engine build `2.01.2614.37001`. Addresses are VAs (ImageBase `0x400000`), verified against the
clean `sage_patch/engine/game.dat.backup`
(`md5 08b9e9c3c79ad70af3dcc973bdcdd66a`).

**Verdict up front:** this one is tractable, and it is *not* the wall that
[`max-player-count.md`](max-player-count.md) describes. Two different constants get confused with
each other, and only the other one is a recompile-scale change:

| | `MAX_PLAYER_COUNT` | `MAX_SLOTS` (this doc) |
|---|---|---|
| value | 20 | **8** |
| what it counts | sides on a map / live `Player` objects | **lobby slots, i.e. players in a game** |
| array shape | `[N]` embedded **mid-struct** in ~12 classes, one of them per grid cell | a pointer array in **one** class, plus one concrete array per `GameInfo` subclass |
| access | inlined everywhere | through **three accessors**, `getSlot` / `getConstSlot` / `setSlotPointer` |
| bound sites | 80+ in the Generals source, more after inlining | **171**, every one of them an `imm8` |
| verdict | needs relocated structures or a recompile | **a cave, four constructors, and 171 one-byte edits** |

The player count everyone actually means when they say "8 players" is `MAX_SLOTS`. Raising it to
**16** needs no change to `MAX_PLAYER_COUNT` at all — the side budget already has room (§6).

The cost is not in the engine. It is in the **maps** (§5) and the **lobby UI** (§7), and the UI
half needs `sage_apt` to be able to write `.apt`, which it cannot yet.

## 1. The constant, and where it lives

`GameInfo` holds an array of *pointers* to slots; the slot objects themselves are embedded in each
subclass. Three accessors are the whole public surface, and all three carry the same bound:

```
00800b55  GameInfo::getSlot(Int)
  8d 41 18        lea  eax, [ecx + 0x18]        ; &m_slot[0], never null - dead test
  85 c0           test eax, eax
  74 13           je   0x800b6f
  8b 44 24 04     mov  eax, [esp + 4]
  85 c0           test eax, eax
  7c 0b           jl   0x800b6f                 ; i < 0 -> NULL
  83 f8 08        cmp  eax, 8                   ; <-- MAX_SLOTS
  7d 06           jge  0x800b6f
  8b 44 81 18     mov  eax, [ecx + eax*4 + 0x18]
  eb 02           jmp  0x800b71
  33 c0           xor  eax, eax
  c2 04 00        ret  4
```

| symbol | VA | callers |
|---|---|---|
| `GameInfo::getSlot(Int)` | `0x00800b55` | **228** |
| `GameInfo::getConstSlot(Int) const` | `0x00800b74` | **77** |
| `GameInfo::setSlotPointer(Int, GameSlot *)` | `0x00800bde` | 4 (the subclass constructors) |

```
GameInfo  +0x18  GameSlot *m_slot[8]      0x18 .. 0x37
          ...    base members continue to 0xdc
          +0xdc  <subclass> concrete slot array
```

Exactly **six** instructions in the whole image index that pointer array directly, and all six sit
in the `GameInfo` module itself — the three accessors above plus three inlined uses, each with its
own bound test:

| VA | instruction | bound |
|---|---|---|
| `0x00800b69` | `mov eax, [ecx + eax*4 + 0x18]` | `0x00800b64  cmp eax, 8` |
| `0x00800b81` | `mov eax, [ecx + eax*4 + 0x18]` | `0x00800b7c  cmp eax, 8` |
| `0x00800bef` | `mov [ecx + eax*4 + 0x18], edx` | `0x00800be6  cmp eax, 8` |
| `0x00800d56` | `mov ecx, [ecx + eax*4 + 0x18]` | `0x00800d49  cmp word [esp+4], 8` |
| `0x00800e33` | `mov ecx, [edi + eax*4 + 0x18]` | loop bound in `ebx` |
| `0x008016dd` | `mov ecx, [ecx + eax*4 + 0x18]` | `0x008016d8  cmp eax, 8` |

That containment is the whole reason this is cheap. `MAX_PLAYER_COUNT`'s arrays are inlined across
the engine; `m_slot`'s are not.

## 2. The four `GameInfo` subclasses

Each one embeds its own concrete slot array at `+0xdc` and arms the base pointer array from its
constructor — a vector-construct with a `push 8` count, then a `setSlotPointer` loop bounded 8.

| constructor | vtable | stride | array occupies | `sizeof` | allocated at |
|---|---|---|---|---|---|
| `0x00628b60` skirmish | `0x00bfd668` | `0x1b8` | `0xdc .. 0xe9b` | **`0xe9c`** — array is the **last member** | `0x0063097f`, `0x0063ca3b`, `0x0082be68`, `0x009288ee` |
| `0x0077dfa0` | `0x00c2ef18` | `0x1b8` | `0xdc .. 0xe9b` | `0xedc` (0x40 of members after) | `0x0077e16a` |
| `0x0084aea1` LAN | `0x00c54b78` | `0x1dc` | `0xdc .. 0xfbb` | `0xfcc` (members at `+0xfbc`, `+0xfc0`, `+0xfc4`, `+0xfc8`) | `0x00989a72`, `0x00989ba8` |
| `0x00903179` GameSpy | — | `0x1ec` | `0xdc .. 0x103b` | not heap-allocated in `.text` (statically placed; members past `+0x103c`, e.g. `+0x107c`) | — |

Only the skirmish subclass could be grown in place. The other three carry members after the array,
and one is not heap-allocated at all — so growing in place is out, and the design below never tries.

## 3. The bound sites

Scanning every `cmp <x>, 8` within ±0x80 of one of the 305 `getSlot` call sites, and separating
backward-branch loops whose body contains a `getSlot` call from everything else:

| | count |
|---|---|
| slot iteration loops (`cmp` + backward `jl`/`jb`, `getSlot` inside the body) | **104** |
| other `cmp …, 8` beside a `getSlot` call — index guards, range validations, `slot < 8` tests | **67** |
| **total** | **171** |
| …of which encode the 8 as an **`imm8`** | **171 / 171** |

Every single one is `83 /7 ib` or `66 83 /7 ib` or equivalent. **Changing 8 to any N ≤ 127 is a
one-byte edit that does not move a single instruction.** No `disp8` grows to `disp32`, no branch
distance changes, nothing shifts. That is the opposite of the `MAX_PLAYER_COUNT` situation and it
is what makes the whole thing a patch rather than a port.

Where they are:

| region | loops | guards | what lives there |
|---|---|---|---|
| `0x83f000`–`0x851fff` | 29 | 17 | `MpGameSetup::InitGadgets` — the lobby glue — and the LAN layer |
| `0x7f0000`–`0x80ffff` | 17 | 7 | `GameInfo` itself, including the ascii serializer |
| `0x9a0000`–`0x9effff` | 14 | 3 | online lobby (`AptOnlineCustomMatch::InitGadgets`), CAH UI |
| `0x619000`–`0x66efff` | 13 | 11 | game start, `GameLogic`, score screen |
| `0x900000`–`0x92ffff` | 11 | 2 | GameSpy game info, options |
| `0x970000`–`0x98ffff` | 6 | 5 | WOTR / strategic mode |
| `0x750000`–`0x78ffff` | 6 | 6 | save/load, the `0x0077dfa0` subclass |
| `0x6b0000`–`0x70ffff` | 4 | 2 | `Player`, `SidesList`, `MapCache` |
| `0x8d0000`–`0x8effff` | 3 | 10 | AI |
| `0x815000`–`0x82ffff` | 1 | 4 | misc |

The 104 loops are mechanical. The 67 guards each need reading before they are touched: some are
`MAX_SLOTS` bounds, some are genuinely "is this slot index one of the first eight", and a handful
in the `0x8d0000` band are probably unrelated comparisons that the ±0x80 window swept up.

## 4. The design: extend, don't grow

Because the pointer array sits mid-struct in `GameInfo` and the concrete arrays sit mid-struct in
three of four subclasses, nothing gets grown in place. Instead:

**Slots 0..7 stay exactly where they are.** Slots 8..N−1 live in a heap block allocated per
`GameInfo` instance, reached through a small side table keyed on `this` — at most four live
instances exist (skirmish, `0x0077dfa0`, LAN, GameSpy), so a four-entry table is enough and needs
no allocator.

1. **One cave, three entry points.** `getSlot`, `getConstSlot` and `setSlotPointer` are 0x1f, 0x18
   and 0x18 bytes; each is rewritten to `jmp` into a `.slotext` cave that answers `i < 8` from the
   stock array and `i >= 8` from the extension. `getSlot`'s own dead `lea/test/je` prologue
   (`0x00800b55`, seven bytes that can never branch) is free space for the hook.
2. **The three inlined uses** (`0x00800d56`, `0x00800e33`, `0x008016dd`) call the same helper
   instead of indexing.
3. **Four constructors, four strides.** Each already builds its concrete array with a counted
   vector-construct and then loops `setSlotPointer`. Each gets a second construct for the (N−8)
   extension slots at its own stride (`0x1b8`, `0x1b8`, `0x1dc`, `0x1ec`) and registers the block.
   The destructors mirror it.
4. **171 one-byte bound edits**, per §3.

Nothing in the object layout moves. Every offset in every disassembly stays valid, which also means
`sage_live`, `sage_verify` and the other patches keep working against the same offsets.

## 5. The maps — this is the real cost

An engine that can seat 16 players is useless on maps that describe 8 start positions. Three
places fix the map side at 8, and all three are cheap in the binary and expensive in the data.

| site | what |
|---|---|
| `0x0070216d` | `MPPositionList` chunk **writer**: `push 8 / pop ebx`, then a loop over 8 entries of stride `0x14` |
| `0x00704456` | the matching 8-element array construct (`push 8` count, `push 0x14` element size) |
| `0x00701b17` | `cmp dword [ebp-4], 8` — a consumer loop over the same 8 positions |
| `0x00704423` | `cmp eax, 8` — `MapCache`'s scan for the `Player_1_Start` … `Player_8_Start` waypoints, which is also what sets the map's `numPlayers` |
| `.rdata 0x00c7fbc8` | the `MapMetaData` INI field table: 8 rows, stride 16, `Player_1_Start`…`Player_8_Start`, writing `MapMetaData+0x3c` .. `+0x90` (a `Coord3D[8]`, stride `0xc`), immediately followed by `InitialCameraPosition` at `+0x9c` |

Two things make this less bad than it looks:

- **The waypoint lookup is by name, not by index.** Fifteen code sites format the string
  `Player_%d_Start` (`0x00bfda18`) and look the waypoint up by that name. Once the loop bound moves
  and a map carries a `Player_9_Start` waypoint, every one of those fifteen finds it for free.
- **The INI field table is data.** Extra `Player_9_Start` … `Player_N_Start` rows can be appended
  in a relocated table with their own `extra` offsets, exactly the technique `commandset-limit`
  uses for `.cmdext`. `MapMetaData` then grows only at its tail if the new positions are placed
  after the existing members rather than inside the `Coord3D[8]`.

What is *not* cheap: **every map that wants more than 8 players has to be re-authored**, and
Worldbuilder needs the same treatment the editor needed for `desert-weather-wb` before it will
place a ninth start position. Stock and Edain ship **zero** maps above 8 (`MPPositionList` is 8 in
all 585 maps surveyed in [`max-player-count.md`](max-player-count.md)).

## 6. The side budget — why 16, and why no `MAX_PLAYER_COUNT` change

`SidesList::addSide` (`0x0072ea27`) refuses side 21 outright:

```
0072ea2b  8b 7e 3c    mov  edi, [esi + 0x3c]     ; m_numSides
0072ea2e  83 ff 14    cmp  edi, 0x14             ; MAX_PLAYER_COUNT
0072ea31  7d 2b       jge  0x72ea5e              ; -> return -1
```

`SidesList::prepareForMP` (`0x0073193d`) runs first and keeps in `m_sides` only the sides whose
`playerName` is empty (the neutral side) or equals `PlyrCivilian` (`0x00c24164`) or `PlyrCreeps`
(`0x00bfd514`); everything else — `Skirmish<Faction>`, `PlyrNeutral`, `PlyrWild`, map-authored
`Player_N` — moves into `m_skirmishSides`, and a synthetic `SkirmishHuman` side is appended (see
[`skirmish-ai-fallback.md`](skirmish-ai-fallback.md) §2). The lobby side builder (`0x00627c1f`)
then adds one `Player_%d` / `Observer_%d` side per occupied slot.

So the live side count is roughly **4 + N**, and `addSide`'s cap of 20 puts the ceiling at

> **N ≤ 16 players, with `MAX_PLAYER_COUNT` left at 20.**

`PlayerMaskType` needs no change either: it is already 32-bit with `PLAYERMASK_ALL = 0x000FFFFF`
(20 bits), indexed by `Player`, not by slot.

Above 16 you are back in [`max-player-count.md`](max-player-count.md) territory and the price jumps
by two orders of magnitude. Don't.

## 7. The lobby UI

The skirmish and online lobbies are **APT movies**, not `.wnd` layouts: `pMpGameSetup.apt` in
`__edain_apt.big`, driven from `MpGameSetup::InitGadgets` (`0x84xxxx`) and
`AptOnlineCustomMatch::InitGadgets` (`0x9axxxx`). Only the LAN lobby is a window layout
(`Menus/LanGameOptionsMenu.wnd`, with `StaticTextPlayer%d` controls) and that one is editable text.

The good news is that the C++ side addresses lobby rows **by formatted path**, not through a
hardcoded eight-widget table — `APT:ConnectingPlayer%dName`, `APT:ConnectingPlayer%dStatus`,
`APT:ConnectionPlayerNum_%d`, `APT:Player_%d_Name_String`, `ConnectionIcon~%d`. Once the loop
bounds move, the glue asks the movie for rows 9..N without further code changes.

The bad news is that somebody has to put those rows in the movie, and
[`sage_apt`](../../sage_apt/README.md) is explicitly work in progress and cannot yet write `.apt`.
**This is the long pole**, and it is a tooling problem rather than a reverse-engineering one.

Player colours are not a problem: `MultiplayerColor` is a data-driven list and both stock `ini.big`
and Edain already define **10** of them.

## 8. Compatibility

- **Every peer needs the same binary.** Slot count changes the game-start data and the side list,
  so a patched client and a stock client cannot play together. Same rule as `commandset-limit`.
- **The lobby wire format scales on its own.** `GameInfo` serialises to
  `M=%3.3x%s;MC=%X;MS=%d;SD=%d;GSID=%X;GT=%d;SI=%d;` (`0x00c4e6b8`) followed by one
  `H<name>,<ip>,…:` / `C<ai>,…:` / `O:` token per slot (`0x00c4e68c`, `0x00c4e674`, `0x00c4e670`),
  appended to an `AsciiString` in a loop bounded at `0x008026a5`. It is variable-length with no
  fixed buffer at the build site — a ninth slot just makes a longer string. The LAN broadcast
  packet's own field width has **not** been checked and is the one place a fixed buffer could bite.
- **Replays.** The same slot string goes in the replay header, and
  [`sage_replay`](../../sage_replay/README.md) already parses it as a `:`-separated list of any
  length. One thing there does assume a small game: the Create-A-Hero block's
  `custom_hero_tail` is read as `24 - len(players)` bytes
  ([`replay.py:669`](../../sage_replay/replay.py#L669)), a relation validated only on the small-game
  corpus. That needs re-deriving before replays of >8-player games parse.
- **Saves** written by a patched binary will not load on a stock one.

## 9. What a patch would actually contain

| tier | work | risk |
|---|---|---|
| 1 | `.slotext` cave + three accessor hooks + three inlined uses + four ctor/dtor pairs | moderate — new allocation on four paths |
| 2 | 104 loop bounds, one byte each | low, mechanical |
| 3 | 67 guard sites, read individually | moderate — this is where a misread costs a crash |
| 4 | map format: 4 code sites + a relocated `MapMetaData` field table | low in the binary |
| 5 | Worldbuilder, so a ninth start position can be authored | separate binary, cf. `desert-weather-wb` |
| 6 | `pMpGameSetup.apt` rows 9..N | **blocked on `sage_apt` gaining a writer** |

Tiers 1–3 are a normal `sage_patch` job, comparable in size to `commandset-limit` and smaller than
`commandset-button-upgrade`. Tiers 4–6 are what turn it into something playable, and tier 6 is a
different project.

A sensible shipping shape mirrors `commandset-limit`: **N configurable in 9..16**, the bound read
from the patch's own guard byte at run time so composing patches can see it, and a default chosen
to match whatever maps exist.

## 10. Verification notes

Verified directly against `game.dat.backup`: the three accessors and their bounds; the six direct
`m_slot` accesses; the 228 + 77 caller counts; the four constructors with their strides, `push 8`
counts and `setSlotPointer` loops; `sizeof` for three of the four subclasses and their allocation
sites; the 104 / 67 / 171 bound-site census and the fact that all 171 encode the 8 as an `imm8`;
the `MPPositionList` writer and array construct; the `MapCache` waypoint scan bound; the
`MapMetaData` INI field table and its offsets; `addSide`'s `cmp edi, 0x14`; `prepareForMP`'s
keep-test; the serializer format strings and slot loop; the APT path formats; and the ten
`MultiplayerColor` blocks in `ini.big` and `__edain_data.big`.

Not confirmed, and each needs its own address before patch work starts: the LAN broadcast packet's
game-info field width; whether the `0x8d0000`-band guard sites are slot bounds at all; how the
lobby decides how many rows to show (assumed `min(map numPlayers, MAX_SLOTS)`, not read); the team
dropdown's own range; and the identity of the `0x0077dfa0` subclass.
