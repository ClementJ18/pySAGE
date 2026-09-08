# Giving a faction a working AI on a map that has no `Skirmish<Faction>` side

Engine build `2.01.2614.37001`. Addresses are VAs (ImageBase `0x400000`), verified against the
installed stock `game.dat` (`md5 daed3668006cd90f01c34e5a7da1901f`).

This is the patch behind alternative 2 of [`max-player-count.md`](max-player-count.md) — *"if two
factions can be driven from one AI side selected at runtime, the per-faction side cost drops"* —
and it ends up somewhere better than that. The engine already selects the AI's map side at runtime,
so the question is not how to *share* a side but why a faction needs one at all. It needs one for
two things, and both can be supplied without it.

**Verdict:** two five-byte hook sites and one cave. `MAX_PLAYER_COUNT` stays 20, no map is edited,
and every faction gets an AI that runs **its own** script library on every map — including the 63
shipped maps already at the 20-side cap and the 106 with no skirmish sides at all.

## 1. What a `Skirmish<Faction>` side is for

As authored in the `.map` it is a stub: six dict keys (`playerName`, `playerIsHuman`,
`playerDisplayName`, `playerFaction`, `playerAllies`, `playerEnemies`), an **empty** BuildList, an
**empty** script list, and one singleton team `teamSkirmish<Faction>`. That holds on stock
`map mp amon sul fortress` and on Edain's `map edain linhir` alike.

The engine fills the stub in. By the time a player is created, that side carries the faction's whole
AI script library, and the player inherits it — which is why deleting the side breaks the faction,
and why a shared side would hand one faction another's AI.

## 2. The chain, end to end

`TheSidesList` is `[0x00de77a0]`. All of this runs inside `GameLogic::startNewGame` (`0x0062f91a`).

```
SidesList  +0x3c  m_numSides           +0x40  m_sides[20]          (SidesInfo, stride 0x60)
           +0x7c0 m_numSkirmishSides   +0x7c4 m_skirmishSides[20]  (0x7c4 + 20*0x60 = 0xf44)
           +0xf44 team list            +0xf60 skirmish team list (+0xf6c its array)
SidesInfo  +0x04  Dict   +0x08  ScriptList   +0x54  LibraryMapLists
PlayerTemplate +0x18 Side   +0x150 IsObserver   +0x1b0 DefaultPlayerAIType
Player         +0x34 m_playerTemplate  +0x4c m_playerName  +0x54 m_playerIndex
               +0x58 m_side            +0x5c m_playerType  +0x2fc m_ai
```

1. **`SidesList::prepareForMP`** (`0x0073193d`) removes every side whose name is not empty and not
   `PlyrCivilian` / `PlyrCreeps` — the `Skirmish*` sides, `PlyrNeutral`, `PlyrWild`, and any
   map-authored `Player_N` — into `m_skirmishSides`, with their teams. Each one that has no
   `playerAIType` string gets one stamped from **its own faction's**
   `PlayerTemplate::DefaultPlayerAIType` (loop `0x00731af7`–`0x00731b94`). A synthetic
   `SkirmishHuman` / `FactionCivilian` side is appended.
2. **`SidesList::loadAILibraryMaps`** (`0x007318a1`, per side `0x0073161c`) reads that
   `playerAIType` off each side's dict, finds it in `TheAIPlayerTypeStore` (`[0x00de3d5c]`, lookup
   `0x006151d6`), and hands the record's `LibraryMap` to `0x007313b3`. That loads the library
   `.map`, recurses through its side-1 `LibraryMapLists` (`SidesInfo+0x54` — how `KI Kern` and
   `ki <faction> spellbook` arrive) and **merges** the library's side-1 script list into the side
   (`0x0072fe23`, which appends rather than replaces).
3. **The lobby-side builder** (`0x00627c1f`) synthesises one live side per occupied `GameInfo`
   slot — `playerName` = `Player_%d`, `playerFaction` from the slot's template — and adds it with
   `SidesList::addSide` (`0x00628148`). *The map is not consulted for this.* A map-authored
   `Player_N` side is a name-matched script donor for the slot, nothing more; the shipped maps carry
   3 to 8 of them on 8-position maps, with no functional pattern.
4. **`PlayerList::newGame`** (`0x006a8a2d`) creates one `Player` per non-empty-named side, passing
   `&sideInfo->m_dict` to **`Player::initFromDict`** (`0x006b07ef`), which:
   - resolves `playerFaction` to a `PlayerTemplate` and copies `template->Side` into `Player+0x58`
     (`0x006b0521`);
   - **loop A** (`0x006b090b`–`0x006b0997`), skipped for `IsObserver` templates and for dicts
     without `playerIsSkirmish`: for each skirmish side, resolve *its* `playerFaction` to a template
     and compare **its `Side`** with `Player+0x58` (`0x006b096a`). A match sets the found flag
     `[ebp-0x20] = 1`; running out sets `[ebp-0x25] = 1`;
   - calls `Player::setPlayerType` (`0x006aa450`) — which allocates `AISkirmishPlayer`
     (`0xa4` bytes, ctor `0x008f3df3`) or legacy `AIPlayer` (`0x7c`, ctor `0x008f7f2b`) or neither;
   - and finally imports the matched side's script list onto the player's own `SidesInfo`
     (`0x006b0dbe`–`0x006b0df7`) plus its teams.

### The failure mode, exactly

The two flags meet at `0x006b09f5`:

```
006b09e4  getBool(playerIsHuman)
006b09f3  jne 0x6b0a20             ; human
006b09f5  cmp byte [ebp-0x25], al  ; al == 0
006b09f8  jne 0x6b0a20             ; NO SKIRMISH SIDE MATCHED
006b09fa  push [ebp-0x20] / push 1 / call setPlayerType   ; type 1 = COMPUTER
006b0a06  jmp 0x6b0d4e
```

`0x006b0a20` — where both a human and a *side-less* AI land — calls `setPlayerType` with
`push edi`, and `edi` is zero throughout the function. **Type 0 is `PLAYER_HUMAN`.** So a faction
with no `Skirmish<Faction>` side on the map does not get a worse AI; it gets typed as a human and
no AI object is created at all. Nobody drives it. That is "the faction is not controllable by the
AI", precisely, and it is a data condition, not memory corruption — `SidesList::addSide`
(`0x0072ea27`) opens `cmp edi, 0x14 / jge` and refuses side 21 with `-1`.

## 3. What the patch does

Two hooks, both inside `initFromDict`, and one `.skfall` cave.

| site | stock bytes | what it was |
|---|---|---|
| `0x006b09f5` | `38 45 db 75 26` | `cmp byte [ebp-0x25], al` / `jne 0x6b0a20` |
| `0x006b0d4e` | `80 7d e0 00 0f 84 d6 02 00 00` | `cmp byte [ebp-0x20], 0` / `je 0x6b102e` |

**Hook 1 — route a side-less AI the way a matched AI is routed.** When `[ebp-0x25]` says loop A
found nothing, the cave clears it and writes `[ebp-0x20] = 2`, then returns into the stock
fall-through. `setPlayerType(1, 2)` therefore runs: type `PLAYER_COMPUTER`, `isSkirmish` non-zero,
so the player gets an `AISkirmishPlayer`. Only the low byte of `[ebp-0x20]` is ever read (as
`setPlayerType`'s second argument, tested `cmp byte`), so `2` is both a working truth value and a
marker hook 2 can recognise. When `[ebp-0x25]` is zero the cave returns unchanged, which is the
stock path for a matched AI, for an observer, and for every player in a non-skirmish game — loop A
never runs there, so the flag is never set and the patch never fires.

**Hook 2 — give that player its own library instead of a borrowed one.** `[ebp-0x20]` is `0`
(→ jump to `0x006b102e`, stock), `1` (→ return, stock faction-based import), or `2` (synthesised).
For `2` the cave:

1. reads `Player+0x34` → `PlayerTemplate`, and takes `&template->DefaultPlayerAIType` (`+0x1b0`);
2. `Dict::setAsciiString` (`0x00715028`) writes it as `playerAIType` into the player's **own** side
   dict, reached through `SidesList::getSideInfo(Player+0x54)` (`0x00602f20`) — the NameKey comes
   from the `playerAIType` `StaticNameKey` at `0x00da2fa4` via `StaticNameKey::key`
   (`0x00548930`);
3. calls `SidesList::loadAILibraryForSide(m_playerIndex)` — **`0x007318f4`**, the single-side
   variant of step 2 above, which builds the loader's temporaries itself and has **zero callers in
   the stock image**;
4. discards its return address and jumps to `0x006b102e`, the same continuation the stock
   "no side" edge uses, because there is no side to import from.

`0x0072fe23` merges into the side's script list rather than replacing it, so driving the loader
against a live player side is additive. The result is that a Rohan player on a map with no
`SkirmishRohan` side runs `ki rohan` + `KI Kern` + `ki rohan spellbook` — its own library, resolved
through its own `DefaultPlayerAIType`, with nothing borrowed from another faction.

### What it deliberately does not do

- **It does not touch the matched path.** Where a `Skirmish<Faction>` side exists it wins, exactly
  as today, and hook 2 returns without doing anything. The patch is a fallback, never an override.
- **It does not raise any limit.** `MAX_PLAYER_COUNT`, `m_sides[20]`, `m_skirmishSides[20]` and the
  32-bit `PlayerMaskType` are untouched.
- **It does not clone teams.** The matched path copies `teamSkirmish<X>`; the synthesised player
  gets only the team `initFromDict` already builds for every player at `0x006b0cb9`. That team is
  the player's own, which is what the skirmish clone was providing a renamed copy of.
- **It does not read or write map data.** Nothing in the `.map` changes, and nothing has to.

## 4. What it buys

Census over every shipped map (`Maps.big`, `_patch201maps.big`, `____edain_maps.big`) — 617 maps,
0 parse errors:

| skirmish sides on the map | maps |
|---|---|
| 0 | 106 |
| 1–7 | 20 |
| 8 | 62 |
| 9 | 17 |
| 10 | 198 |
| 11 | 214 |

and by total side count: **63 maps are at the 20 cap**, 237 at 19. Under the patch none of that
decides whether a faction's AI works. A faction added to the mod tomorrow plays on all 617 maps the
day it ships, with no map re-release; a map at the cap needs no room it does not have; and the 106
maps with no skirmish sides at all become AI-playable for every faction at once.

Two sides in the shipped set are already dead and stay dead — `SkirmishArnor` (270 maps) and
`SkirmishGondor` (11) name `FactionArnor` / `FactionGondor`, which Edain's `playertemplate.ini`
does not define, so both resolve to a null template and are skipped by loop A. Under the patch
those factions' would-be players fall into the synthesised path instead of failing.

## 5. Risks and open questions

- **Every peer must run the same binary.** The patch changes which AI class a player gets and what
  scripts it runs, from frame 0. Patched and unpatched peers desync, and replays do not cross the
  boundary — the same rule as `production-condition`.
- **The `0x006b0db5` either/or is not fully pinned.** A player whose own dict carries `playerAIType`
  as a string takes the name-based import (`0x006add80`) and skips the faction path entirely. The
  lobby stamps that at `0x006280a9` under a `TheMapCache` (`[0x00de4b74]`) byte at
  `+0x54 + slot*0x14 + 2` that has not been identified — it does not reconcile with the map-cache
  INI field table, where `Player_N_Start` sits at `0x3c` with stride 12. On maps that take that
  path, hook 1 still fires (loop A ran and found nothing) but the player was already getting its
  scripts from the map's own donor side.
- **`0x007318f4` has never been executed.** It is stock code and its shape is unambiguous, but the
  stock image never calls it, so "the engine's own loader, reused" is a reading of the disassembly
  and not an observation.
- **Not yet observed in game.** Everything below "the file still loads and verifies" is a claim.

## 6. How to test it

1. **Static** — both sites hold their stock bytes; apply, disassemble the cave, `verify`, `detect`,
   round-trip. This is what `tests/sage_patch/test_skirmish_ai_fallback.py` does.
2. **Data** — pick a map at 20 sides carrying no side for some faction (or delete one from a copy),
   and confirm `sage_map` still round-trips it.
3. **In game** — skirmish on that map with the AI set to that faction. Unpatched it sits inert (it
   is typed human and has no AI object); patched it should build and attack, using its own faction's
   units. The Edain overlay's bot harness (`sage_edain.bot`, in the separate pySAGE-edain
   repository) drives the lobby and the match.
4. **Negative** — a faction that *does* have a side on the map must behave byte-identically. Hook 2
   returns immediately on `[ebp-0x20] == 1`, so this is a check rather than a hope.

## Verification notes

Verified directly against the stock `game.dat`: the `SidesList` and `SidesInfo` layouts;
`prepareForMP` at `0x0073193d` including the `DefaultPlayerAIType` stamp and the 20-slot copy;
`loadAILibraryMaps` at `0x007318a1`, the per-side loader at `0x0073161c`, the library merge at
`0x007313b3` and its install at `0x0072fe23`; `0x007318f4`'s signature and its zero callers;
`addSide`'s `cmp edi, 0x14`; loop A and both flags; `setPlayerType`'s two AI classes and its type-0
edge; `Player+0x58 = template->Side` at `0x006b0521`; the `PlayerTemplate` field table at
`0x00bf81a8` (`Side = 0x18`, `IsObserver = 0x150`, `DefaultPlayerAIType = 0x1b0`); the calling
conventions of `0x00602f20` (`ret 4`), `0x00715028` (`ret 8`), `0x00548930` (`ret`) and
`0x007318f4` (`ret 4`); and that nothing in `initFromDict` branches into either hook site's
interior.

Verified against shipped game data: the side / build-list / script / team inventory of the two maps
named above; the 617-map census; Edain's 14 `PlayerTemplate`s, their `Side` and
`DefaultPlayerAIType` values; the 21 `PlayerAIType` blocks in `playeraitypes.ini` and the libraries
they name; and the script counts of those libraries (`ki rohan` 133, `ki angmar` 172, `KI Kern`
238, `spieler` 203).

Not confirmed: the map-cache byte at `0x006280a9`, and anything about the patch in a running game.
