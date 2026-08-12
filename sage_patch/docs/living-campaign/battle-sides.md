# Who plays in a battle — participants, sides, and the third-party problem

Engine build `2.01.2614.37001`, ImageBase `0x400000`. Static analysis 2026-08-12, with map data
parsed by `sage_map` across BFME1's `maps.big` and the Edain corpus.

**Partly unresolved, and marked as such.** The question is why a War of the Ring battle supports only
two players when a linear mission supports many. The structures are recovered; the exact substitution
is not.

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

## Where the trace stopped

If `newGame` walks `m_sides`, and `m_sides` is what the map loaded, a WotR battle should produce a
player for every declared side — and it demonstrably does not. Something prunes or replaces `m_sides`
between the map load and `newGame`. **That code was not found.**

Dead ends, recorded so they are not repeated:

- `newGame` is **virtual**; scanning `.text` for direct callers returns nothing. The same trap
  produced a wrong conclusion about `setObjectivesButtonEnabled` — "no callers found" is never
  "never called".
- `+0x3C` and `+0x18` are far too common as offsets to brute-force; both scans returned dozens of
  unrelated hits.

Next anchors, unattempted: `SidesList`'s vtable (from the constructor at `0x007307D0`) will name its
reset/prepare methods, and `removeSide` at `0x0072F20A` has callers worth enumerating.

**`map kampa angmar 10` is the controlled comparison** — same mod, same map format, one path each.
Isolating how it is reached versus how mission 01 is reached should bracket the substitution.

## Method

`SidesList` layout from `getSide`'s indexing (`imul eax, eax, 0x60` / `lea eax, [eax + ecx + 0x40]`),
the second array found by searching that exact `6B C0 60` encoding image-wide — eleven occurrences,
two indexing `+0x7C4`. Object size from the `push 0x11B0` before its constructor. `AddPlayer` path
from the `LivingWorldCampaign` field table (`0x00C7F898`). Map claims from `sage_map`, reading sides,
teams and every script action by `internal_name` rather than by id.
