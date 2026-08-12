# The four campaign Act verbs RotWK lost, with their BFME1 INI specs

BFME1 `C:\BFME1\lotrbfme.exe` against RotWK `game.dat` build `2.01.2614.37001`. Recovered
statically on 2026-08-12 by dumping both games' Act verb tables and the field tables behind them.

**Nothing here has been run.** Static analysis of two binaries plus the shipped INI corpus.

## Why this is the important comparison

[`bfme1-vs-rotwk-actions.md`](bfme1-vs-rotwk-actions.md) establishes that **mission scripts never
drove the strategic map** — the `LIVING_WORLD_*` script actions are vestigial in *both* games. So
whatever BFME1's campaign did on the world map, it did through campaign-INI **Act verbs**. That
makes the Act verb table the real inventory of the Living World feature set, and the diff between
the two tables the real scope of "reimplement BFME1's campaign".

## The two tables

Act verb tables: RotWK `0x00C84030` (15 verbs), BFME1 `0x010EC9D8` (18 verbs). Rows are 16 bytes,
`(name, parse fn, 0, offset)`.

| verb | BFME1 | RotWK |
|---|---|---|
| `EnableRegion` | ✓ | ✓ |
| `ForceBattle` | ✓ | ✓ |
| `SpawnArmy` | ✓ | ✓ |
| `MoveArmy` | ✓ | ✓ |
| `CallActSubroutine` | ✓ | ✓ |
| `JumpToAct` | ✓ | ✓ |
| `MoveCamera` | ✓ | ✓ |
| `SplineCamera` | ✓ | ✓ |
| `WorldText` | ✓ | ✓ |
| `AudioEvent` | ✓ | ✓ |
| `EndAct` | ✓ | ✓ |
| `UpdateAnimObject` | ✓ | ✓ |
| `EyeTowerPoints` | ✓ | ✓ |
| hand an army to the player | `ToggleArmyControl` | `SetPlayerControlOfArmy` *(renamed)* |
| `SpawnBuilding` | — | **✓ RotWK only** |
| **`DespawnArmy`** | **✓** | — |
| **`MergePlayerArmy`** | **✓** | — |
| **`RegionReinforcements`** | **✓** | — |
| **`ModifyArmyEntry`** | **✓** | — |

Thirteen verbs are shared outright, one was renamed, RotWK added one, and **four were removed**.
That is the whole gap, and it is smaller and far better defined than "the Living World was stripped
out".

## The four, with their exact INI syntax

Field tables read directly from BFME1's parsers.

### `DespawnArmy` — not a block, a single field

```
Act Something
    DespawnArmy = Zaphragor_Army
End
```

Parser `0x00C541E0` (the `AsciiString` parser), act offset `0x38`. It is a plain named field on the
Act, not a nested block — which is why Edain's commented-out line reads `; DespawnArmy = Zaphragor_Army`
rather than a `DespawnArmy … End` block.

### `MergePlayerArmy` — one verb, both directions

```
MergePlayerArmy
    SourceArmy        = FellowshipPlayerArmy
    DestArmy          = MerryAndPippinPlayerArmy
    SplitArmyTemplate = MerryAndPippinSplitArmy
    SplitArmy         = Yes            ; omit to merge instead
End
```

| field | offset | type |
|---|---|---|
| `SourceArmy` | `+0x04` | AsciiString |
| `SplitArmyTemplate` | `+0x08` | AsciiString |
| `DestArmy` | `+0x0C` | AsciiString |
| `SplitArmy` | `+0x10` | Bool |

Parser `0x007B8500`. Gondor's campaign uses 14 of these, 11 of them splits — the Fellowship breaking
apart. Edain's `wotrscenarioangmar.inc` already contains two, written correctly and commented out.

### `ModifyArmyEntry` — composition mutation

```
ModifyArmyEntry
    PlayerArmy      = SomeArmy
    CurUnitTemplate = OldUnit
    NewUnitTemplate = NewUnit
End
```

| field | offset | type |
|---|---|---|
| `PlayerArmy` | `+0x00` | AsciiString |
| `CurUnitTemplate` | `+0x04` | AsciiString |
| `NewUnitTemplate` | `+0x08` | AsciiString |

Parser `0x007B88F0`. **This is the answer to the open question in
[`living-world-parity.md`](living-world-parity.md) §6** — "can RotWK's army model even express a
change of composition?" BFME1 expressed it as a *substitution*: swap one unit template for another
inside a named army. Not add or remove — replace. That is a much narrower operation than a general
composition editor, and it is the shape any reimplementation should follow.

**Why BFME1 needed this verb at all** is worth stating, because it explains the whole design. BFME1
contains **zero** carryover machinery — no `Carryover` string in any casing, no revival-entry
actions ([`living-world-parity.md`](living-world-parity.md) §3). Its strategic armies are
`LivingWorldPlayerArmy` rosters, each battle instantiates from the roster afresh, and combat never
writes back. So an army's membership could only ever change because an act *said* it changed —
which is exactly what `ModifyArmyEntry`, `MergePlayerArmy` and `DespawnArmy` are for. RotWK dropped
all three and added persistence instead.

**And RotWK still has the target structure, intact.** `PlayerArmy` here does not name a spawned
army; it names a `LivingWorldPlayerArmy` INI block — the composition definition that
`SpawnArmy … PlayerArmy = X` refers to. RotWK parses those blocks today:

```
LivingWorldPlayerArmy                      ; block table 0x00C4FB58
    Name           = GondorFighterArmy     ; +0x18
    DisplayNameTag = LWA:MenOfTheWest      ; +0x64
    ArmyEntry                              ; sub-parser 0x00811CF9, 0xD8-byte entries
        ThingTemplate = GondorFighterHorde ; +0x04   (tables 0x00C4FA94 + 0x00C2F470)
        Quantity      = 1                  ; +0xA0
    End
End
```

Edain's `livingworldbuildableunits.inc` is full of them. So `ModifyArmyEntry` reduces to: resolve
the `LivingWorldPlayerArmy` by `Name`, walk its `ArmyEntry` list, find the entry whose
`ThingTemplate` matches `CurUnitTemplate`, and write `NewUnitTemplate` into that `AsciiString` at
`+0x04`.

**Every structure it needs already exists and is already populated.** That makes this the
best-understood of the four by a distance — the remaining work is the act-record plumbing, not the
data model.

### `RegionReinforcements` — an entire subsystem RotWK has no trace of

```
RegionReinforcements
    RegionName           = Rohan
    AddReinforcementArmy = SomeArmy
    CloseDistanceTime    = 30
    MediumDistanceTime   = 60
    FarDistanceTime      = 120
    PathFindRule         = PlayerOwned     ; or EnabledOrPlayerOwned / AllRegions
    AutoSummon           = Yes
End
```

| field | offset | type |
|---|---|---|
| `PathFindRule` | `+0x00` | enum (`0x00416478`) |
| `RegionName` | `+0x04` | AsciiString |
| `AddReinforcementArmy` | `+0x08` | AsciiString list |
| `CloseDistanceTime` | `+0x14` | number |
| `MediumDistanceTime` | `+0x18` | number |
| `FarDistanceTime` | `+0x1C` | number |
| `AutoSummon` | `+0x22` | Bool |

Parser `0x007BABE0`. This is the biggest of the four by some margin: reinforcements attached to a
region, arriving on a timer that scales with distance, pathfinding constrained by ownership, with an
auto-summon option. It also explains `PathFindRule` — which
[`living-world-parity.md`](living-world-parity.md) lists as a missing `MoveArmy` field. It is not a
`MoveArmy` field at all; it belongs to `RegionReinforcements`, and BFME1's `gondorcampaign.ini` uses
`PathFindRule = PlayerOwned` 19 times.

**That is a correction to the parity doc** and it matters, because it moves `PathFindRule` from "a
small missing field" to "part of a subsystem that is wholly absent".

## What reimplementation actually costs

Ordered by value-per-effort, given everything now known:

1. **`DespawnArmy`** — one `AsciiString` field on the Act, one parser row, and a runtime that
   removes an army. The smallest of the four by a wide margin, and the one Edain already wrote a
   line for. Also the one the mission-script route can never provide, since
   `LIVING_WORLD_DESPAWN_ARMY` is a stub in both games.
2. **`ModifyArmyEntry`** — three strings and a template substitution inside a named army. Narrow,
   well-defined, and it unlocks the "armies change over the campaign" texture without needing
   general composition editing.
3. **`MergePlayerArmy`** — four fields, but the runtime is the real work: moving a sub-army between
   two armies. This is the Fellowship mechanic and the most *visible* of the four.
4. **`RegionReinforcements`** — seven fields and a timed, distance-aware, pathfinding-constrained
   subsystem. Scope this last; it is plausibly larger than the other three combined.

All four need the same scaffolding, which is now well understood from the RotWK side: a row in the
Act verb table at `0x00C84030`, a field table, a `push_back` into a per-verb list on the Act, and a
pass in the act runner at `0x0096E362` (see [`living-world-parity.md`](living-world-parity.md) §2,
which traces `SetPlayerControlOfArmy` end to end — field table → `act+0xA8` → executor pass 9 of 10).

### Adding a verb is a one-dword repoint

The table **cannot grow in place** — it is followed by a single 16-byte zero terminator at
`0x00C84120` and then string data (`"ParseLivingWorldCampaign:Act::No act name specified."` at
`0x00C84130`). A sixteenth row would consume the terminator; a seventeenth would eat the string.

But it does not need to grow in place, because **the table has exactly one reference in the whole
image**:

```asm
0096e7f2  push 0x00C84030          ; <-- the only mention
0096e7f7  lea  eax, [ebp - 0xd8]
0096e802  call 0x0042DB80          ; the shared field/block parse routine
```

So relocation is: copy the 15 rows plus terminator into a cave, append new rows, and change one
immediate at `0x0096E7F3`. No relocation table, no scattered references, no jump-table arithmetic —
materially simpler than the `campaign-select` or `hero-bar-slots` patches already in this repo.

That makes **the scaffolding cheap and the runtime the entire cost** for all four verbs.

## Unknowns

| | question | how to settle |
|---|---|---|
| ~~1~~ | ~~Can the Act verb table grow in place?~~ | **settled** — no, but relocation is one dword at `0x0096E7F3` |
| ~~2~~ | ~~Does RotWK still have the structure `ModifyArmyEntry` mutates?~~ | **settled** — yes, `LivingWorldPlayerArmy`/`ArmyEntry` parse today, offsets above |
| 3 | Does anything in RotWK survive of the reinforcement-army list `RegionReinforcements` fed? | RotWK still has live `CREATE_REINFORCEMENT_TEAM`; check whether it shares a backing list |
| 4 | What does BFME1's `MergePlayerArmy` runtime actually move — templates, or a sub-army object? | disassemble past `0x007B8500`'s parse into its executor |

With 1 and 2 settled, **`ModifyArmyEntry` is the obvious first verb to build**: the parser
scaffolding is a one-dword relocation, the data model is intact and populated, and the runtime is a
string compare and a string write. Question 4 gates the most *visible* verb, and question 3 the
largest.

## Method

Act verb tables located by finding the `SpawnArmy` string, taking the data reference whose next
dword is a code pointer, walking backwards to the table start, and enumerating 16-byte rows until a
non-string name. Field tables are the second value pushed before each parser's call to the shared
field-parse routine (`0x00C520A0` in BFME1). BFME1 was built with incremental linking, so parse-fn
pointers in the verb table land on `jmp` thunks around `0x0041E800`–`0x0044B000`; resolve one hop.
