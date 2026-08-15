# Who plays in a battle — participants, sides, and the third-party problem

Engine build `2.01.2614.37001`, ImageBase `0x400000`. Static analysis 2026-08-12, with map data
parsed by `sage_map` across BFME1's `maps.big` and the Edain corpus.

**Partly unresolved, and marked as such.** The question is why a War of the Ring battle supports only
two players when a linear mission supports many. The structures are recovered; the exact substitution
is not. **Sharpened live on 2026-08-14** (see *Measured live*, below): `IsScriptedCampaign` decides
whether even those two appear, and third-party sides are dropped either way — so there are two
reductions here, not one, and only the first is characterised.

## The symptom

In Edain's War of the Ring battles only `Player_1` and `Player_2` exist. Other sides authored into
the map do not load — objects belonging to them disappear or sit inert regardless of allegiance. The
same authoring works in the **linear** campaign, where a mission can carry many dud players.

BFME1's campaign maps rely on that: `map good helms deep` declares **9** sides, including `Elves`,
`Eored`, `StupidHorses` and `IsengardCampers` — three sharing `FactionRohan` with the human player
but as separate players.

## The War of the Ring convention: owner is 1, attacker is 2

Confirmed across the Angmar missions. The tell is the team-count asymmetry:

| mission | `Player_1` faction | teams | `Player_2` faction | teams |
|---|---|---|---|---|
| angmar 01 | Angmar | **19** | Angmar | 5 |
| angmar 02 | Men | **15** | Angmar | 4 |
| angmar 03 | Men | **25** | Angmar | 3 |
| angmar 04 | Men | **21** | Angmar | 6 |
| angmar 05 | Arnor | **25** | Angmar | 8 |
| angmar 06 | Arnor | **31** | Angmar | 12 |
| angmar 08 | Arnor | **11** | Angmar | 4 |
| angmar 09 | Men | **64** | Angmar | 3 |
| angmar 11 | **Angmar** | **34** | **Men** | 2 |

`Player_1` is the region owner and its defending garrison — hand-authored, hence the bulk of the
teams. `Player_2` is the attacker, with almost nothing authored **because its army arrives from the
strategic layer**.

`angmar 11` is the proof: the roles follow the situation, not the human. There the defender is Angmar
(`Player_1`, 34 teams) and the attacker is Men (`Player_2`, 2 teams).

Mission 01's ownership reads the same way — `Player_1` owns `Plateau Camp`, `East Village`,
`Den Attackers`, `East/West/South Defenders`; `Player_2` owns `Finale Heroes` and `Rogash`, the
handful of things that join you.

### The conversion, and its leftovers

The Angmar campaign was converted to this two-player form by **moving every team under `Player_1` or
`Player_2` and rewriting the scripts**. Two maps escaped it:

- **`map kampa angmar 10`** is an unconverted linear mission, no longer connected to anything. It has
  **no `Player_N` sides at all** — everything is `Plyr*`-named (`PlyrDwarves_City_Left`,
  `PlyrAngmar`, `PlyrMen`, …), and it is the only Angmar map shipping a `map.str`. It is the
  surviving record of the pre-conversion arrangement.
- **`map kampa angmar 07`** has no `Player_2`; it runs `Player_3` (Angmar, **65** teams) against
  `Player_1` (Imladris, 7).

And **`map kampa angmar 03` already declares `Player_1` through `Player_8`** — Men, Angmar, Isengard,
Dwarves, Elves and three more Angmar. The attempt at third parties has already been made in this
corpus, and those extras are inert.

> **Correction.** An earlier revision of this document quoted `playerIsHuman` as meaningful. It is
> not: across these maps it is set on `PlyrMordor`, `PlyrElves`, `PlyrWild`, `PlyrCreep` and others.
> It is a WorldBuilder artifact, not something the engine acts on.

## `SidesList` holds two arrays

`TheSidesList` is at `0x00DE77A0`, allocated `0x11B0` bytes at `0x0063B407`, constructed by
`0x007307D0`.

| | count | array | stride | accessors |
|---|---|---|---|---|
| `m_sides` | `+0x3C` | `+0x40` | `0x60` | `getSide` `0x00602F20` |
| `m_skirmishSides` | `+0x7C0` | `+0x7C4` | `0x60` | count `0x006AA317`, get `0x006AA31E` |

`20 × 0x60 = 0x780`, so `m_sides` occupies `+0x40`–`+0x7C0` and `m_skirmishSides` follows — matching
`MAX_PLAYER_COUNT = 20` ([`max-player-count.md`](../max-player-count.md)). Both are copied together by
the assignment paths at `0x00730340`/`0x00730360` and `0x007309EC`/`0x00730A08`, which is how the
pair was found. A `removeSide`-shaped method sits at `0x0072F20A`, shifting entries down and clearing
the tail.

The map's list loads through the chunk parser registered at `0x004AEE84` (chunk `"SidesList"`,
version 6); the serialiser at `0x0072FF16` writes the `+0x3C` count.

## Players are made from `m_sides` only

`PlayerList::newGame` (`0x006A8A2D`):

```asm
006a8a51  edx = [0x00DE77A0]        ; TheSidesList
006a8a57  eax = edx->[0x3C]         ; m_sides count  <-- not the skirmish array
006a8a6a  loop: getSide(i)          ; 0x00602F20
006a8a89  look up "playerName" (NameKey 0x00DA2F2C)
006a8a98  empty -> skip             ; the neutral side
006a8aa8  m_players[m_playerCount++]
```

No lobby check, no faction filter, no start-position matching, no bound — **every side in `m_sides`
with a non-empty name becomes a player.** That is why a mission-style load gives as many duds as the
map declares, in BFME1 and RotWK's linear campaign alike.

`m_skirmishSides` is not the roster: its accessor's ten callers are all in `0x006ACF40`–`0x006B0E89`,
`Player` initialisation code supplying per-player skirmish attributes.

## How BFME1 gets a strategic army into a battle map

`map good lothlorien` places **zero** hero objects, and of its 41 army/hero-ish script actions every
one is `CREATE_NAMED_ON_TEAM_AT_WAYPOINT` spawning goblins, trolls and spotlight markers. Nothing
creates Gandalf or Aragorn.

What it declares instead is an **empty container team**:

```
team "Fellowship"   owner=PlyrGondor    teamUnitType1..3 = <none>
team "Fellowship"   owner=PlyrCivilian  teamUnitType1..3 = <none>
```

And the campaign declares an army of the same name:

```
SpawnArmy
    Name        = Fellowship             ; <-- matches the map team
    PlayerArmy  = FellowshipPlayerArmy
    PlayerOwned = Yes
    Position    = X:-360 Y:1430          ; a world-map coordinate
End

LivingWorldPlayerArmy
    Name = FellowshipPlayerArmy
    ArmyEntry { ThingTemplate = GondorAragorn;     Quantity = 1 }
    ArmyEntry { ThingTemplate = GondorBoromir;     Quantity = 1 }
    ArmyEntry { ThingTemplate = GondorGandalfGrey; Quantity = 1 }
    ...
```

**The army's `Name` against a same-named empty team in the map is the join**, and the engine fills
that team from the `ArmyEntry` roster on battle load. It is the exact inverse of the
`*_ASSIMILATE_WITH_*_ARMY` actions, which push map units *into* an army.

Stated as inference, not proof: there are no heroes placed, no script creating them, and an empty
team carrying precisely the army's name. The engine code performing the match was not found.

**Edain does not use this convention.** Its `CampaignTeam_1` / `CampaignTeam_2` containers are a mod
naming choice — the string `CampaignTeam` appears in **neither** binary.

## `AddPlayer` — what it does and does not do

`AddPlayer` populates the **living-world** player vector, not `TheSidesList`.

```
field table   0x00C1AE70   PlayerTemplate, AITemplate, BaseRegion,
                           MP_SlotColorIndex, TeamNumber, LWHandicap, IsDumb
parser        0x006E309A   validates the templates, then appends
append        0x00933D18   campaign+0x30, 0x28-byte entries, deduped by name (entry+8)
scripted loop 0x00933109   walks the whole vector, no clamp:
                             compare entry name against LocalPlayer (campaign+0x3C)
                             call 0x006BB3B5(entry, isLocal)   ; create the player
creator       0x006BB3B5   dedupes again via findPlayerByName, resolves PlayerTemplate
                           (0x00DE4AF8) and, unless IsDumb, AITemplate (0x00DE8BFC)
```

So the count is **uncapped** — a twentieth `AddPlayer` is instantiated like the first. Three ways an
entry vanishes with no message:

1. **Unknown `PlayerTemplate`** — dropped at parse (`0x006E3124`) and again at creation.
2. **Unknown `AITemplate`** — dropped unless `IsDumb = Yes`, which skips the lookup.
3. **A duplicate name** — discarded, not merged.

Only a missing name reports: `ParseLivingWorldPlayer::No name specified.`

These become `LivingWorldPlayer`s on `TheLivingWorldManager` — strategic-layer participants that own
regions and armies. **Nothing in that path writes `TheSidesList`**, so whether they reach a battle
depends on the substitution below. Untested either way.

Two things that may bind first: `MPPositionList` is **8** in all 585 shipped maps, and Edain's Angmar
`Scenario` sets `MinPlayers = 2` / `MaxPlayers = 2`.

## The live army's layout

Copied from the `SpawnArmy` parse record by the constructor at `0x0071BC70`:

| live army | from `SpawnArmy` | field |
|---|---|---|
| `+0x18` | `+0x50` | `HeroTemplateName` |
| `+0x1C` | `+0x18` | `ScriptingName` |
| `+0x24` | `+0x04` | `Icon` |
| `+0x28` | `+0x08` | `Banner` |
| `+0x58` | — | controllable-by-owner flag (see [`living-world-parity.md`](living-world-parity.md) §2) |
| `+0x78` | — | the battle-side record (see [`dead-script-actions.md`](dead-script-actions.md)) |

Armies live in a vector at `manager+0x8C`…`+0x90` (`TheLivingWorldManager` = `0x00DE4950`), with
`findArmyByScriptingName` at `0x006B53A4` and `findArmyById` at `0x006B5351`.

**Nothing in `0x006B0000`–`0x006C0000` writes `manager+0x90`.** Of the ten sites that shrink such a
vector, none is in the living-world manager — consistent with `DespawnArmy` being absent as both INI
verb and working script action. Armies do not appear to be removed.

## Measured live: `IsScriptedCampaign` decides whether the battle gets faction players

Measured 2026-08-14 against a running process with `sage_live`, same map, same INI, `IsScriptedCampaign`
the only difference between the two columns:

| | scripted `Yes` | scripted commented out |
|---|---|---|
| `ThePlayerList` slots | 3 | 4 |
| | *(nameless neutral)*, `PlyrCivilian`, `ReplayObserver` | + `Player_1` (Men), `Player_2` (Angmar) |
| local seat | **`ReplayObserver`** | `Player_2`, a real faction |
| hero objects on the map | **0** | `AngmarWitchking_mod`, `AngmarDurmarth`, `AngmarRogash_New`, all owned by the local player |
| objects | 265 | 926 |
| fog | whole map revealed | normal |

`map kampa angmar 01` declares **seven** sides — `Player_1` and `Player_2` (both `FactionAngmar`),
`PlyrCivilian`, `PlyrCreep`, `PlyrImladris`, `PlayerMordor` and the nameless neutral. Under
scripted mode five of the seven get no player, and the two that survive are the system sides every
map gets regardless. The `ReplayObserver` is not in the map at all: with no slot to seat the client,
the engine falls back to an observer, which is also why the map reads as fully revealed.

**The prune is real, and the flag makes it worse rather than causing it.** Note the third-party
sides: `PlyrCreep`, `PlyrImladris` and `PlayerMordor` get no player in **either** column. That is
the original symptom this document opens with, unchanged. What the flag adds is the loss of
`Player_1` and `Player_2` on top of it. So scripted mode is not the cause of the two-player limit;
it is a second, more severe reduction stacked on it.

**The mechanism is not established.** Recorded as a hypothesis, explicitly not a finding:

The branch at `0x00932EDA` reads `IsScriptedCampaign` and chooses between two builders. Both were
disassembled, and **both build `LivingWorldPlayer`s on `TheLivingWorldManager` (`0x00DE4950`)** —
the *strategic* participants — differing only in where they read from:

```asm
00932ee0  mov  esi, [0x00DE412C]      ; TheGameLogic          <- flag CLEAR
00932ee8  call 0x00610A21             ; multiplayer?
00932ef1  mov  eax, [0x00DE892C]      ;   yes -> TheGameInfo
00932ef8  cmp  [esi+0x114], 3         ;   no, and type 3 -> the scripted label too
00932f05  mov  eax, [0x00DE8930]      ;   else -> TheSkirmishGameInfo
00932f21  call [eax+0x34]             ; slot count, then walk the slots

00933109  eax = ([edi+0x34]-[edi+0x30]) / 0x28   ; the AddPlayer vector  <- flag SET
0093311e  lea  ebx, [edi+0x3c]        ; LocalPlayer, for the isLocal compare
0093312e  mov  ecx, [0x00DE4950]      ; TheLivingWorldManager
0093314f  call 0x006BB3B5             ; create the LivingWorldPlayer
```

So **neither branch writes `ThePlayerList`**, and neither can be the direct cause of the battle's
empty seat list. The plausible story is that the unscripted path leaves the lobby `GameInfo`
populated on the way in and the scripted path never populates it, with the battle built from that
downstream — but *the code that turns a `GameInfo` into battle players was not traced*, and until it
is, this is a guess with a correct prediction, not an explanation.

Two consequences worth stating plainly:

- **Progression and playable battles are currently mutually exclusive.** That is the central
  constraint on the living-world work, not a bug to be repaired in passing.
- **Renaming `AddPlayer` blocks cannot fix it.** Tried live: renaming them to `Player_1`/`Player_2`,
  matching the map's own side names exactly, changed nothing. An `AddPlayer` name reaches only the
  dedupe at `entry+8` and the `LocalPlayer` comparison at `campaign+0x3C`. The two namespaces never
  meet.

The engine work this defines is a **handoff**: when scripted mode skips the lobby init, fill the
participant list from the campaign's own `AddPlayer` vector at `campaign+0x30` instead. Everything
it needs is already parsed and verified live at the right offsets — template, AI template, region,
colour, team, `LWHandicap`, `IsDumb`.

One observation for whoever writes it: with scripted mode off, the live factions come out **crossed**
relative to the INI — `Player_1` is `PlayerAngmar` in `AddPlayer` but reads as **Men** in the battle,
and `Player_2` the reverse. Expected there, since the unscripted path takes factions from the lobby
rather than from the blocks; but it is exactly the mapping a handoff would have to get right.

## Where the trace stopped

**Still open, and the live run narrowed rather than answered it.** `PlayerList::newGame` gives every
non-neutral side a slot (see [`max-player-count.md`](../max-player-count.md)), so a 7-side map should
seat six. It seated three unscripted and one scripted. Whatever reduces `m_sides` is therefore
upstream of `newGame` in both modes, and `map kampa angmar 03` already declares `Player_1` through
`Player_8` with the extras inert.

If `newGame` walks `m_sides`, and `m_sides` is what the map loaded, a WotR battle should produce a
player for every declared side — and it demonstrably does not. Something prunes or replaces `m_sides`
between the map load and `newGame`. **That code was not found.**

Dead ends, recorded so they are not repeated:

- `newGame` is **virtual**; scanning `.text` for direct callers returns nothing. The same trap
  produced a wrong conclusion about `setObjectivesButtonEnabled` — "no callers found" is never
  "never called".
- `+0x3C` and `+0x18` are far too common as offsets to brute-force; both scans returned dozens of
  unrelated hits.

### `PlayerList::newGame` is exonerated (2026-08-14)

Located at `0x006A8A30` and decoded. It is not the reducer, and the pseudo-code this document
carried is confirmed against the disassembly:

```asm
006a8a51  mov  edx, [0x00DE77A0]        ; TheSidesList
006a8a57  mov  eax, [edx+0x3c]          ; m_sides count  <- the loop bound
006a8a6f  call 0x00602F20               ; getSide(i)
006a8a7f  call 0x00548930               ; StaticNameKey 0x00DA2F2C = "playerName"
006a8a8b  call 0x00714E6D               ; side.dict lookup
006a8a98  je   0x006A8B3E               ; absent      -> skip this side
006a8aa2  je   0x006A8B3E               ; empty       -> skip this side
006a8aa8  mov  eax, [edi+0x14]          ; m_playerCount
006a8aab  mov  ecx, [edi+eax*4+0x18]    ; m_players[count]
006a8ab4  mov  [edi+0x14], eax          ; m_playerCount++   <- no clamp, as documented
006a8ab7  call 0x006B07EF               ; player init from the side
```

The local seat is chosen just below, from `"multiplayerIsLocal"` (`0x00DA2F94`) and then
`"playerIsHuman"` (`0x00DA2F34`) gated on `[0x00DE4468] == 0`.

**So every side carrying a non-empty `playerName` gets a player, and only the nameless neutral is
skipped.** A 7-side map would yield six. It yielded three. Therefore `m_sides` is **already reduced
before `newGame` runs** — the reduction is upstream, in whatever prepares the sides list for a War
of the Ring battle, and the loop bound `TheSidesList+0x3C` is the value to watch.

Note in passing that `playerIsHuman` *is* read by the engine here, for the local-seat fallback only.
The correction above stands for its original claim — it does not decide which sides become players —
but "the engine does not act on it" was too strong.

Next anchors, unattempted: `SidesList`'s vtable (from the constructor at `0x007307D0`) will name its
reset/prepare methods. `removeSide` at `0x0072F20A` has **zero direct callers**, which by this
document's own rule is not the same as never called — check the vtable before concluding anything
from it.

### The measurement, taken (2026-08-14)

Read live in a **scripted** War of the Ring battle on `map kampa angmar 01`, a map declaring seven
sides (one nameless neutral + six named):

```
TheSidesList -> 0x04F921F8
  m_sides         count (+0x3C)  = 3
  m_skirmishSides count (+0x7C0) = 6
ThePlayerList
  m_playerCount         (+0x14)  = 3
```

**`m_sides` holds three entries where the map declared seven, and `newGame` turned those three into
exactly three players.** So the loop is faithful and the list it walks is already wrong: this is a
**replacement of `m_sides`**, before `newGame`, not a filter inside it. That is the substitution this
document has been looking for, now pinned to a specific field and a specific window — between map
load and `newGame`.

The three surviving entries correspond to the three player slots observed (`(nameless neutral)`,
`PlyrCivilian`, `ReplayObserver`).

**And the two arrays hold different things — read, not inferred.** With the `Dict` layout below,
every entry names itself:

| | `m_sides` (3) | `m_skirmishSides` (6) |
|---|---|---|
| 0 | *(no `playerName`)* — the neutral | `Player_2` — `FactionAngmar`, `AngmarSkirmishAI`, enemies `Player_1` |
| 1 | `PlyrCivilian` — `FactionCivilian` | `Player_1` — `FactionAngmar`, `AngmarSkirmishAI`, enemies `Player_2` |
| 2 | `ReplayObserver` — `FactionObserver` | `PlyrCreep` — `FactionTutorial`, `MenSkirmishAI` |
| | | `PlyrImladris` — `FactionImladris`, `ImladrisSkirmishAI` |
| | | `PlayerMordor` — `FactionMordor`, `MordorSkirmishAI` |
| | | `SkirmishHuman` — `FactionCivilian`, `Multiplayer_Human` |

So `m_sides` is the **battle's participant list** — system sides plus whoever was seated — and
`m_skirmishSides` is the **map's authored candidate sides**, intact, carrying their factions, their
`SkirmishAI` templates and their enemy lists. Five of the map's six named sides are there; the sixth,
`PlyrCivilian`, moved to `m_sides` as a system side, and `SkirmishHuman`/`Multiplayer_Human` is a
template the lobby fills rather than anything the map declared.

That is the best available outcome for a fix: **nothing is destroyed.** At battle time, in a
campaign with no players at all, `Player_1`, `Player_2`, `PlyrImladris`, `PlayerMordor` and
`PlyrCreep` are all sitting at `+0x7C4` fully described and simply unused. A patch that seats them
into `m_sides` before `newGame` needs to *move* data, not fabricate it - and third parties are
reachable by the same move, since `PlyrImladris` and `PlayerMordor` arrive with AI templates
already attached.

**Still inferred, not traced:** that the seating step matches lobby participants against
`m_skirmishSides`, and that its finding nothing is what leaves `m_sides` with three system entries.
It fits every measurement here and explains the unscripted case too (where `Player_1`/`Player_2` *do*
become players), but the code doing it has not been read.

### The reset path, located (2026-08-14)

The vtable is at `0x00C240E8` (installed at `0x00730807`), 14 slots. Scanning `0x00720000`-`0x00740000`
for stores to `[reg+0x3C]` gives 19, of which three matter:

| site | what |
|---|---|
| `0x00730831` | `and [esi+0x3c], 0` — the constructor's init |
| `0x0072F261` | `dec [esi+0x3c]` — inside `removeSide` (`0x0072F20A`) |
| **`0x0072F1CC`** | **`SidesList::clear`** — a function entry, and the interesting one |

`clear` zeroes **both** counts and **both** arrays:

```asm
0072f1cc  and  [ecx+0x3c], 0          ; m_sides count
0072f1d0  and  [ecx+0x7c0], 0         ; m_skirmishSides count
0072f1d9  push 0x14                   ; MAX_PLAYER_COUNT
0072f1e4  lea  ecx, [esi-0x784]       ; m_sides array
0072f1ea  call 0x0072E75B             ; clear 20 entries
0072f1f1  mov  ecx, esi               ; m_skirmishSides array
0072f1f3  call 0x0072E75B             ; clear 20 entries
```

So it is a **wholesale reset, not a selective prune** — which fits the measurement: nothing filters
sides one at a time, the list is emptied and rebuilt.

`clear` has exactly **two** callers: `0x004AEE48`, and `0x0072F790` — the latter inside `0x0072F78D`,
which is the target of **vtable slot 9** (`0x0072FF07` is a one-instruction `jmp` thunk to it). That
slot is the reset/prepare method this document predicted the vtable would name.

### `0x0073193D` builds `m_skirmishSides` — and only that

`clear`'s other caller, `0x004AEE48`, turned out to be the **map loader** and not the culprit — it
clears the list and then registers the `SidesList` and `Teams` chunk parsers (`0x00730A56` handles
`SidesList`, building a stack-temporary `SidesList` and assigning it in). After map load, `m_sides`
legitimately holds the map's sides.

The substitution is later, and it was found through the one name in the live dump that the map does
**not** declare: `SkirmishHuman`. That literal (`0x00C24154`) is referenced from `0x00731BA6`, inside
a function entered at **`0x0073193D`**, which has exactly one caller:

```asm
0073193d  <SEH prologue>
00731947  mov  eax, 0x11c8              ; a stack temporary SidesList
0073195c  call 0x007307D0               ; construct it
00731973  call 0x0072F762
00731978  cmp  [ebx+0x3c], esi          ; loop over the CURRENT m_sides
00731988  mov  ecx, 0x00DA2F2C          ; StaticNameKey "playerName"
00731b8a  add  [ebp-0x18], 0x60         ; stride 0x60 - SidesInfo
00731ba5  mov  esi, 0x00C24154          ; then append "SkirmishHuman"
00731c6a  ...  0x00C24130               ;   with "Multiplayer_Human"

; the only caller, gated:
0062fb51  mov  ecx, [0x00DE4324]
0062fb59  call [eax+0x58]               ; a virtual predicate - game type?
0062fb65  mov  ecx, [0x00DE77A0]        ; TheSidesList
0062fb6b  call 0x0073193D
```

The `SkirmishHuman` entry it appends is fully described in place, which is how the live dump's last
row was produced:

```
playerName        = "SkirmishHuman"      (0x00DA2F2C)
playerIsHuman     = 1                    (0x00DA2F34)
playerDisplayName = ""                   (0x00DA2F44)
playerFaction     = "FactionCivilian"    (0x00C24144)
playerEnemies     = ""                   (0x00DA2F54)
```

each written into a `Dict` and added to the temporary through `SidesList::addSide` at
`0x0072EA27` (whose own count store is the `0x0072EA3A` that looked like a loose end earlier).

**But the tail settles it the other way, and the identification above was too eager.** The function
ends:

```asm
00731d78  mov  [ebx+0x7c0], eax         ; m_skirmishSides COUNT
00731d84  lea  edi, [ebx+0x7c4]         ; m_skirmishSides ARRAY
00731deb  ret
```

`ebx` is `TheSidesList` throughout, and across the whole function `m_sides` (`+0x3C` / `+0x40`) is
**only ever read** — at `0x00731978` and `0x00731A39`, as the loop bound. So `0x0073193D` is
`prepareForSkirmish`-shaped: it *derives* the skirmish pool from the map's sides and writes the
second array. **It does not reduce `m_sides`.**

So this explains where `m_skirmishSides` and its `SkirmishHuman` row come from, and it confirms the
map's sides are read intact at that point — but the 7 → 3 reduction of `m_sides` is still unfound.

**Remaining candidates**, from the same `[reg+0x3C]` store scan, now that `0x0072EA3A` is accounted
for: `0x0073095E` (`mov [esi+0x3c], eax`, sitting near the constructor and so most likely
`SidesList::operator=` copying a count) is the strongest, because a wholesale *assignment* of a
3-entry list into `TheSidesList` matches the measurement better than any incremental edit. The
assignment paths at `0x00730340` / `0x00730360` / `0x007309EC` / `0x00730A08` that this document
already identified are the ones to read. The gate at `0x0062FB59` (`[0x00DE4324]`, virtual `+0x58`)
still wants identifying — it decides whether the skirmish pool is built at all.

### Reading a side's name

Needed for any further work here, and got wrong once. `SidesInfo+4` is a `Dict`, which is **one
pointer**; the layout, recovered from the pair finder at `0x00714A09`:

```
DictPairData  +0x00  refcount
              +0x04  UInt16 numPairsUsed        ; movzx esi, word [edi+4]
              +0x06  DictPair pairs[]           ; lea eax, [edi+ecx*8+6], sorted by key
DictPair (8)  +0x00  dword: low byte = type, high 24 bits = NameKey   ; shr edx, 8
              +0x04  value
type          0 = Bool, 1 = Int, 3 = AsciiString, 4 = UnicodeString
```

from `0x00714A66` (Bool), `0x00714E6D` (AsciiString) and `0x00714EB4` (UnicodeString), each of which
checks the type byte before returning `pair+4`. The runtime `NameKey` for a name lives in the
`StaticNameKey`'s first dword — `0x00DA2F2C` for `playerName` — filled on first use, so it must be
read from the **running process**, not the file, where it is 0.

**`map kampa angmar 10` is the controlled comparison** — same mod, same map format, one path each.
Isolating how it is reached versus how mission 01 is reached should bracket the substitution.

## Method

`SidesList` layout from `getSide`'s indexing (`imul eax, eax, 0x60` / `lea eax, [eax + ecx + 0x40]`),
the second array found by searching that exact `6B C0 60` encoding image-wide — eleven occurrences,
two indexing `+0x7C4`. Object size from the `push 0x11B0` before its constructor. `AddPlayer` path
from the `LivingWorldCampaign` field table (`0x00C7F898`). Map claims from `sage_map`, reading sides,
teams and every script action by `internal_name` rather than by id.
