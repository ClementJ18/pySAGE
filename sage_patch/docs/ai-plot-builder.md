# Making the skirmish AI build on settlement plots

Engine build `2.01.2614.37001`. Addresses are VAs (ImageBase `0x400000`), recovered statically
2026-08-31 against this repo's `game.dat`, with the BFME1 comparison read out of a retail
`C:\BFME1\lotrbfme.exe` and the mod data read from the Edain `_mod` ini tree.

**This is a scoping note, not a patch.** Nothing is built. It records what the engine does today,
what BFME1 did instead, and what a fix would cost.

## TL;DR

- **No stock skirmish-AI tactic builds on a plot flag.** The one that looks like it does,
  `AIFarmBuilderTactic` (`0x009B5594`), drops free-build structures at a random angle and radius
  around the base and never touches a plot. That is why Edain drives plot building from per-map
  scripts.
- `AIFlagCaptureSquad` (`0x009BC093`) *claims* plots and stops there — see
  [`ai-flag-capture-gate.md`](ai-flag-capture-gate.md). So the engine takes settlement flags and
  then leaves them empty.
- **BFME1 had the feature, in data, with no scripts at all.** `CastleBehavior` carried
  `SidesAllowed <side> FROM_PLAYER FROM_AI FROM_SCRIPT` — a per-side permission mask with the AI
  as a first-class unpack source — plus one canonical prefab per faction in
  `CastleToUnpackForFaction`.
- **RotWK deleted `SidesAllowed`.** It is not a keyword of any field-parse table in this build. The
  permission-and-source model went when the BFME2 `SkirmishAI` subsystem replaced the
  Generals-lineage `AIPlayer`, and nothing replaced it — the same shape of hole
  [`ai-construction-gate.md`](ai-construction-gate.md) describes in a different corner of that
  rewrite.
- **Edain builds through `CASTLE_UNPACK_EXPLICIT_OBJECT`,** so cost is the button object's own
  `BuildCost` and the palette is a runtime function of the owning player's upgrades. No static
  list in `skirmishaidata.ini` can mirror it.
- The fix is **one new targetless tactic**. A `PlotBuildDefinition` block on `ArmyDefinition` is a
  small, well-understood second half, and is optional for a first version.

## 1. What the AI does today

RotWK ships the BFME2 `SkirmishAI` subsystem, and the binary names its targetless tactics in the
pool strings under `AITacticsGenerator/TargetlessTactics/`. Three of them are candidates for
"builds on a plot". None is.

| tactic | ctor | vtable | what it actually does |
|---|---|---|---|
| `AIFarmBuilderTactic` | `0x009B5594` | `0x00C899D0` | free-builds `AIEconomyAssigment.TemplateName` near the base |
| `AIFlagCaptureSquad` | `0x009BC093` | `0x00C8A2FC` | walks a squad onto a capture flag; never builds |
| `AISimpleExpansionTactic` | `0x009B5190` | `0x00C898D4` | a *unit* tactic for the `EXPANSION` entry in `TacticalAITargets` |

`AILumberMillBuildTactic`, `AIRoamingDefenseTactic` and `AIStructureCreepTactic` share the same
base class and are unread.

### 1a. The farm builder is the consumer of `AIEconomyAssigment`

Its update (`0x009B5C53`) calls the order-issuing step at `0x009B5B59`, which opens with:

```asm
009b5b6a  push [esi+0x24]                ; the player
009b5b6d  mov  ecx, [0x00de4938]         ; TheSkirmishAIManager
009b5b73  call 0x006a950b                ; -> per-player record
009b5b78  mov  eax, [eax+0x160]          ; the ArmyDefinition
009b5b7e  add  eax, 0x24                 ; +0x24 = AIEconomyAssigment
```

`ArmyDefinition+0x24` is exactly where the `AIEconomyAssigment` sub-block parses to (§6a), and its
first field is `TemplateName`. So that block is live data and this is its only consumer.

### 1b. The placement is a random ring, not a search

`0x009B59A5`, paraphrased from the disassembly:

```c
anchor = player->getBasePosition();                     // 0x008F0284
for (attempt = 0; attempt < 5; ++attempt) {
    angle  = GameLogicRandomValueReal(...);             // consts 0x00C89A14 / 0x00C89AB0
    radius = GameLogicRandomValueReal(...);             // consts 0x00C899C8 / 0x00C899CC
    pos    = anchor + polar(angle, radius);
    pos.z  = TheTerrainLogic->getGroundHeight(pos);     // [0x00DE4690] vtable +0x18
    if (TheBuildAssistant->isLocationClear(tmpl, pos))  // [0x00DE8200] vtable +0x44
        return pos;
}
return false;
```

No `BASE_SITE`, no flag, no plot, anywhere in it. Every Edain `*EconomyVariants_AI` entry ends in
`FreeBuild` precisely because this is what consumes them, and `WildEconomyVariants_AI` weights its
picks by repeating entries — the only weighting mechanism the stock path has.

## 2. The order a plot builder would issue

Already solved elsewhere in the repo. A human clicking a plot button fires one of two messages,
both tabulated in [`order_space_map.md`](../../sage_replay/order_space_map.md):

| order | command | carries | content decided by |
|---|---|---|---|
| `0x43D` | `CASTLE_UNPACK` | nothing | the target's own `CastleToUnpackForFaction` row |
| `0x43F` | `CASTLE_UNPACK_EXPLICIT_OBJECT` | one thing-template id | the button's `Object` |

`sage_live` injected a `0x43D` at a live Isengard economy plot on 2026-07-31, so the message path is
proven before a byte of patch is written.

## 3. How BFME1 did it

BFME1 had this feature and **no skirmish scripts at all**. Enumerating every `.big` in a retail
install, `data\scripts` holds only `scripts.ini`, `scripts.lua` and `scriptevents.*` — the
RotWK-style `.scb` library does not exist there. The `SkirmishBuildList` in
`data/ini/default/aidata.ini` is a vestigial stub: one faction (Gondor), eight structures, every
one marked `AutomaticallyBuild = No`.

The mechanism was entirely on the plot object:

```ini
; BFME1 - Object EconomyPlotFlag
Behavior = CastleBehavior ModuleTag_castle
    SidesAllowed = Isengard FROM_PLAYER FROM_AI FROM_SCRIPT
    SidesAllowed = Mordor   FROM_PLAYER FROM_AI FROM_SCRIPT
    SidesAllowed = Rohan    FROM_PLAYER FROM_AI FROM_SCRIPT
    SidesAllowed = Gondor   FROM_PLAYER FROM_AI FROM_SCRIPT
    UseTheNewCastleSystemInsteadOfTheClunkyBuildList = Yes
    CastleToUnpackForFaction = Mordor   Lumbermill_Mordor MORDOR_FLAG_ECONOMY_UNPACK_COST
    CastleToUnpackForFaction = Isengard Lumbermill_Mordor ISENGARD_FLAG_ECONOMY_UNPACK_COST
    CastleToUnpackForFaction = Rohan    EconomyFarm_Rohan ROHAN_FLAG_ECONOMY_UNPACK_COST
    CastleToUnpackForFaction = Gondor   Farm_Gondor       GONDOR_FLAG_ECONOMY_UNPACK_COST
End
```

Two axes, both declared on the plot and neither on the AI:

**Permission, with a source axis.** `SidesAllowed` is a per-side three-bit mask.

| thing | address (BFME1 `lotrbfme.exe`) |
|---|---|
| `CastleBehavior` field-parse table | `0x010EA060` — 3 rows |
| `SidesAllowed` row | parse `0x00437817`, offset `0xC` |
| the parse function itself (thunk target) | `0x00777AF0` |
| flag name table | `0x012B4180` — `FROM_PLAYER`, `FROM_SCRIPT`, `FROM_AI` |

**Content.** One canonical prefab per faction with its cost macro.

No percentages, no phases, no per-faction AI list, no candidate search. The AI's whole decision
collapses to *is there a plot I may unpack, and can I afford it*. BFME1 could afford that because
each faction had exactly one economy building.

> **How far this is verified.** The field, its flag name table and its parse function were read out
> of `lotrbfme.exe`. The BFME1 **AI code** that consumes the `FROM_AI` bit was not traced. That the
> AI path is gated on that bit is inference from the flag's name plus the total absence of skirmish
> scripts — strong, but not disassembled.

## 4. What RotWK kept and what it deleted

| `CastleBehavior` field | BFME1 | RotWK |
|---|---|---|
| `SidesAllowed` (with `FROM_AI`) | yes | **absent** from every field-parse table of this build |
| `UseSecondaryBuildList` | yes | absent |
| `UseTheNewCastleSystemInsteadOfTheClunkyBuildList` | yes | absent |
| `CastleToUnpackForFaction` | yes | kept — module data `+0x68`, parse `0x0079BD2F` |

RotWK's `CastleBehavior` module data is 120 bytes with 25 fields (ctor `0x0079C543`);
`SidesAllowed` is not among them. `explore.py keyword SidesAllowed` finds no table.

## 5. Where Edain keeps the answer

Edain builds through `CASTLE_UNPACK_EXPLICIT_OBJECT`, not through the `CastleBehavior` default.
That settles both the cost question and the shape of any new INI block.

### 5a. Cost lives on the object, per tier

```ini
ChildObject GondorFarm_Extern  GondorFarm         BuildCost = EDAIN_ECONOMY_FLAG_UNPACK_COST_LEVEL1
ChildObject GondorFarm_Extern2 GondorFarm_Extern  BuildCost = EDAIN_ECONOMY_FLAG_UNPACK_COST_LEVEL2
ChildObject GondorFarm_Extern3 GondorFarm_Extern  BuildCost = EDAIN_ECONOMY_FLAG_UNPACK_COST_LEVEL3
```

The zeroed cost column in Edain's `CastleToUnpackForFaction` rows charges nothing because nothing
goes through it. An AI on the explicit path pays exactly what a player pays, with no extra work.

Those rows are still live for the neutral claim — `EconomyFlagCommandSet` holds a single
`Command_UnpackEconomyPlot` with `Command = CASTLE_UNPACK` — and their `.bse` prefabs
(`farm_gondor`, `farm_belfalas`, `entmoot_lorien`, …) are present and Edain-maintained in
`____edain_maps.big`. They are the *claim* path, not the *build* path.

### 5b. The palette is a function of live player state

Which buttons a plot offers is decided at runtime by `CommandSetUpgrade` modules on the flag, keyed
on the owning player's upgrades:

```ini
Behavior = CommandSetUpgrade ModuleTag_CommandSetEconomyLevel2_Men
    TriggeredBy         = Upgrade_MenFaction Upgrade_EdainEconomyProduktionserhohungExtern
    CommandSet          = GondorEconomyPlotCommandSet2
    RequiresAllTriggers = Yes
End
```

Faction, subfaction and economy tier all resolve through that one mechanism —
`GondorEconomyPlotCommandSet`, `…Set2`, `…Set3`, `…_DolAmroth`, `ArnorGondor…`.

**This is the constraint that shapes everything else.** A tactic must take its *candidates* from the
plot's live CommandSet. An INI block therefore cannot be a candidate list — it can only be a
**weight table**, and its keys must be stable across tiers. Keying a weight on
`GondorFarm_Extern2` means the tuning silently stops applying the moment a player researches
Siedlerwerkzeuge.

## 6. The proposed design

Decisions taken during scoping:

| question | decision |
|---|---|
| which plots | **outer settlement flags only** — the neutral flags a squad captures first |
| candidate source | **the plot's live CommandSet**; the INI block supplies weights only |
| percentage denominator | **of plot-built structures only** — the mix among what this tactic placed |
| the free-build farm dropper | **coexist** — `AIEconomyAssigment` keeps working unchanged |

The block is structurally a clone of `ArmyMemberDefinition`, reusing the `PhaseDuration_Rush` /
`PhaseDuration_MidGame` boundaries already on the army definition:

```ini
ArmyDefinition MenOfTheWestArmy
    Side = Men

    PlotBuildDefinition GondorFarm_Plot
        Unit                         = GondorFarm_Extern   ; tier-1 name = the family key
        PercentageOfStructuresPhase1 = 35.0
        PercentageOfStructuresPhase2 = 25.0
        PercentageOfStructuresPhase3 = 20.0
    End
End
```

`ExpansionPointDefinition` was the name this started as; it collides with the engine's own
`EXPANSION` tactical-target type and with `ExpansionPlotFlag`, while the content is economy plots.
`Unit` is kept for consistency with `ArmyMemberDefinition` even though it names a structure.

**The key-resolution rule** is what makes this survive tier changes: a weight entry matches a live
button when the button's `Object` is the named template *or a child of it*. `GondorFarm_Extern2`
and `GondorFarm_Extern3` are both `ChildObject`s of `GondorFarm_Extern`, so one entry covers all
three tiers. **Unverified** — see §8.

### 6a. What the INI surface costs

`ArmyDefinition` parses through table `0x00C52B40` into a struct from `operator new(0xEC)`.

| thing | address |
|---|---|
| field-parse table | `0x00C52B40` — 57 rows, `0x3A0` bytes, NULL-terminated |
| its two references (both imm32) | `0x00830103` (`mov eax`), `0x008302A0` (`push`) |
| the allocation | `0x00830281` — `push 0xEC` / `operator new` |
| the constructor | `0x0082FF49` |
| highest field offset in use | `0xE8` (a float) — the struct is packed, no spare bytes |
| `ArmyMemberDefinition` trampoline | `0x0082FEFE` — `new(0x10)`, sub-table `0x00C52538`, pushed onto the vector at `ArmyDefinition+4` via `0x0090BE00` |
| `AIEconomyAssigment` trampoline | `0x0082FD19` — sub-table `0x00C52588` (one field, `TemplateName`), parsed in place at `ArmyDefinition+0x24` |
| `AIWallNodeAssignment` trampoline | `0x0082FD30` |

So a new list field is four edits: a cloned trampoline and sub-table in a cave, one new row in a
**relocated** copy of the field table (it is full; both references are imm32 and trivial to
repoint), the allocation bumped `0xEC` → `0xF8` for one 12-byte vector, and the constructor zeroing
it. Table relocation is established practice here — see
[`production-model-condition.md`](production-model-condition.md) §11a.

### 6b. Staging

1. **Spike from `sage_live`** before patching: pick a captured flag, read its live CommandSet,
   issue `0x43F`, watch what the AI does with it. Answers whether this is worth having, and
   exercises the order path end to end. The `edain-bot-run` skill already drives a live match.
2. **The tactic** — a new targetless tactic in a cave on `AIFarmBuilderTactic`'s skeleton (the
   dictionary-backed `IsRunning` / `FrameNextRun` cooldown and the five-state update), enumerating
   owned plot flags, rejecting built ones, weighting the live `CASTLE_UNPACK_EXPLICIT_OBJECT`
   buttons and issuing the order. The bulk of the work.
3. **The INI surface** (§6a), plus `PlotBuildDefinition` in
   [`sage_ini/model/data_blocks.py`](../../sage_ini/model/data_blocks.py) beside
   `ArmyMemberDefinition` so `sage_lint` resolves the references.
4. **Retire the map scripts** — the scripts and the tactic would both fire, so the maps need
   cleaning in the same release. Map data, not engine; unscoped.

Steps 1–2 ship without 3: with no weight table the tactic picks uniformly from what the plot
offers, which almost certainly already beats the scripts. That makes the INI surface a tuning
refinement rather than a prerequisite.

## 7. Options considered and not taken

- **The INI list as the candidate set** — the original proposal. Every tier and subfaction variant
  would need enumerating and hand-syncing against data the CommandSet already encodes correctly.
  Rots on the first economy rebalance. §5b is the reason.
- **Revive the BFME1 contract** — issue `0x43D` and let `CastleToUnpackForFaction` decide. It
  resolves to a `.bse` prefab (the neutral-claim path, not the build path) and gives one answer per
  faction, so it cannot express a mix — the exact thing the feature is for.
- **Extend `AIEconomyAssigment` to plots** — weighting by repeating entries in `BuildVariations`
  works and is already idiomatic (`WildEconomyVariants_AI` repeats `WildPlundermineFreeBuild` three
  times), but there is no phase dimension.
- **Weights on the `CommandButton`** — correct in principle and needs no key-resolution rule at
  all, but scatters AI tuning across 166 unpack buttons instead of centralising it per faction.
  Worth reconsidering if the child-template rule in §6 does not hold.
- **Re-add `SidesAllowed` / `FROM_AI`** — the one BFME1 idea with no Edain equivalent: a per-plot
  AI opt-out, so a map or plot variant can be excluded without touching any army definition. One
  relocated module table. Not needed for a first version, but the cheapest good idea left on the
  table.

## 8. What remains unread

- **Tactic registration.** Everything above traces how the existing tactics *run*. How a new one is
  registered into `AITacticsGenerator`, and whether the generator's tactic list has room, has not
  been read. The piece most likely to move the estimate.
- **The child-template key rule.** Matching a weight entry to a button through the engine's template
  parent chain is what makes tier changes safe, and it is asserted rather than verified.
- **A reliable "claimed but empty" test.** [`ai-flag-capture-gate.md`](ai-flag-capture-gate.md) §5
  established that a claimed plot carries `ObjectStatus UNSELECTABLE`, correlated across 20 flags on
  one map — but the code that *sets* that bit was never located. That correlation is the current
  best candidate and inherits the same caveat.
- **Whether the capture squad feeds the builder.** Claiming and building would be separate tactics
  on independent cooldowns. Whether an AI reliably captures enough flags to keep a builder busy is
  unmeasured; the spike should count it.
- **The stock behaviour in a running game.** As with `ai-construction-gate`, the defect is
  established statically. Nobody has watched a skirmish AI capture a settlement flag and leave it
  empty.

## Status

**Scoped, not built.** No patch, no code, no tests. Every address above holds on this repo's
`game.dat` (and, where marked, on a retail BFME1 `lotrbfme.exe`); the Edain data is quoted from the
`_mod` ini tree. The design decisions in §6 are settled; §8 lists what must be answered before the
tactic can be written.
