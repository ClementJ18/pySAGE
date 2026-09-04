# Bringing War of the Ring closer to the BFME1 campaign

A plan, written after scripted campaigns were made to work
([`living-world-campaign.md`](living-world-campaign.md)). Engine build `2.01.2614.37001`;
BFME1 comparisons against `C:\BFME1\lotrbfme.exe`.

Every item carries a **confidence** marker, because inferences in this investigation keep turning
out wrong — two static reads of the binary, caught by reading the running process, and then four
claims in this plan's own first draft, caught by reading the shipped INI data (see *Corrections* at
the end). Treat *verified* as fact, *likely* as a hypothesis with evidence, and *unknown* as a
question with an address attached.

**Revised 2026-08-11** after a pass over the campaign data in both games. The revision changed which
item to do first.

## Where things stand

**Done.** A campaign marked `IsScriptedCampaign = Yes`, declaring its own players, and named
through `LivingWorldCampaignOverrride` (needs the four-byte `living-world-override` patch) runs its
acts in sequence with no End Turn. Confirmed: Edain's twelve-act Angmar campaign advanced 0 → 10
under observation.

**The shape of the remaining gap.** RotWK is not a cut-down BFME1 — the two diverged in both
directions:

| | BFME1 | RotWK |
|---|---|---|
| split / merge armies | **present** — one `MergePlayerArmy` block, `SplitArmy = Yes` to split | **absent — zero occurrences** |
| `DespawnArmy` | present | **absent** |
| hand an army to the player | `ToggleArmyControl` + `PlayerControl` | `SetPlayerControlOfArmy` + `IsControllableByOwner` |
| army ownership on spawn | `PlayerOwned` (bool) | `SpawnForTemplates` (player template list) |
| `PathFindRule` (a `RegionReinforcements` field, **not** `MoveArmy` — see [`bfme1-act-verbs.md`](bfme1-act-verbs.md)) | present (`PlayerOwned`/`EnabledOrPlayerOwned`/`AllRegions`) | **absent** |
| Act verbs | **18** | **15** — missing `DespawnArmy`, `MergePlayerArmy`, `RegionReinforcements`, `ModifyArmyEntry` |
| `IsScriptedCampaign` | absent | present |
| `SecondsPerReinforcement`, `ForceAdvanceTurnPhase` | absent | present |
| `ScriptHolder` + the `LivingWorldScripts\` asset root | absent | present, and unused by any shipped campaign - see [`script-holder.md`](script-holder.md) |
| `AutoResolve*` stores | absent | 71 occurrences, six INI stores |
| `ArmyCarryoverPoints`, `DelayCarryoverSpawningOf` | absent | present |
| `SpawnArmy` fields | 9 used: `Name`, `PlayerArmy`, `Faction`, `Banner`, `Icon`, `IconSize`, `PalantirMovie`, `PlayerOwned`, `Position` | **18** (field table `0xC78380`): `ScriptingName`, `PlayerArmy`, `Banner`, `Icon`, `IconSize`, `PalantirMovie`, `Position`, `InitialRegion`, `SpawnForTemplates`, `HeroTemplateName`, `IsCity`, `MoveSpeed`, `BuildTime`, `SpawnAtActStart`, `TooltipStringTag`, three `ConstructButton*` |
| campaign shape | acts only, **no `Scenario` block** | `Scenario` + acts |

The two `SpawnArmy` lists overlap less than a "superset" reading suggests. RotWK **drops** `PlayerOwned`
and `Faction` and renames `Name` to `ScriptingName`; the ownership question BFME1 answered with a bool
is answered in RotWK by `SpawnForTemplates`.

So army *authoring* in RotWK is ahead of BFME1. Army *manipulation* is behind. That asymmetry is
what the plan is organised around: most of the parity gap is reachable through data and small
patches, and the removed engine features are confined to §6.

For scale, counting live (uncommented) lines:

| | BFME1 `GondorCampaign` | Edain `WOTRScenarioAngmar` |
|---|---|---|
| acts | 46 | 12 |
| `SpawnArmy` | 44 | 14 |
| `MoveArmy` | **132** | 23 |
| `MergePlayerArmy` | 14 | 0 (2 present, commented) |
| `DespawnArmy` | 20 | 0 (1 present, commented) |
| `ForceBattle` | 9 | 0 |
| `Scenario` block | none | 1 |

The `MoveArmy` row is the one to sit with: nearly three moves per act in BFME1 against two in
Angmar. Whatever else differs, BFME1's campaign was authored at a much higher density of scripted
movement — which is the texture the complaint is about, and it is authoring, not engine.

## 1. A menu entry instead of a global override — *high confidence, do before shipping*

**Why.** `LivingWorldCampaignOverrride` forces one campaign for every War of the Ring start. That
is fine for authoring and unacceptable for shipping, and it is the only thing standing between the
current state and something a mod could release.

**What is known.** Setting `IsScriptedCampaign` removes a campaign from the scenario list by design
(predicate `0x007B9551`). The engine's own way of launching a scripted campaign is `AptMainMenu`
holding the literal `"WOTRTutorial"` (`0x00C35D34`, built at `0x007B9983`, called from
`0x0091B867`) and resolving it through `findIndexByName`.

**The work.** Scoped in full: [`living-world-menu-entry.md`](living-world-menu-entry.md). The short
version is better than this section assumed — the engine already carries a menu-driven Living World
launcher, `AptMainMenu::OnTutorial` with `params = "Strategic"`, which bypasses the War of the Ring
picker entirely and names its campaign through a magic static of exactly the shape
[`campaign-select`](../campaign-select.md) exploits. It is **orphaned**: no shipped shell movie calls
it, in any of the 119 install archives.

**Settles it.** One thing, and it is not implementation: that path has **never run in a shipped
build**, so it must be proven before a cave is written for it. The scope doc's Option A — fill the
static, add a throwaway button — is the cheap proof.

## 2. Hand armies to and from the player — *wired end to end; one direction never used*

**Your complaint.** No way to intertwine forced movement with free movement.

**What is known.** `SetPlayerControlOfArmy` is an Act verb in RotWK, and BFME1 has the same mechanic
under a different name — `ToggleArmyControl` with a `PlayerControl` bool. Neither engine is missing it.

What is asymmetric is **use**:

| | `Yes` (give control) | `No` (take control away) |
|---|---|---|
| BFME1 `ToggleArmyControl` (gondor + mordor) | **14** | 9 |
| Edain scenarios, all five (`SetPlayerControlOfArmy`) | **0** | 65 |

Sixty-five live uses across `wotrscenarioangmar`, `evil`, `moria`, `test` and `test2`, and every
one of them takes control *away*. `IsControllableByOwner = Yes` appears nowhere — not in Edain, not
in stock RotWK.

**The mechanism, traced statically.** It is not a stub:

```
field table 0xC78544   ArmyScriptingName -> +0x4 (AsciiString)
                       IsControllableByOwner -> +0x8 (Bool)
parse 0x008E6185    -> appends a 16-byte record to the act's list at act+0xA8 (append 0x0096DF5D)
execute 0x0096C4AB  -> pass 9 of the 10 the act runner makes:
                         army = lookupByScriptingName(rec+0x4)      ; 0x006B53A4
                         army->setControllableByOwner(rec+0x8)      ; 0x0071A64E -> army+0x58
read 0x006B6657     -> a player-interaction predicate that returns false when army+0x58 is 0
                       (checked twice, at 0x006B669B and 0x006B66B6)
```

And the engine sets that same flag itself when it builds an army — `0x006B7285` pushes **1**,
`0x006B9316` pushes **0**. So `Yes` is the engine's own normal state for a player-owned army, not an
unexercised path.

**The hypothesis, restated.** The intertwining is not a missing verb and not an unused verb — it is
an unused *direction*. Edain uses the verb solely as a lock, which is the same thing as the hero
workaround in §3.

**Settles it.** Flip one existing line. In `wotrscenarioangmar.inc`, the Angmar act-one spawns are
each followed by a `SetPlayerControlOfArmy … IsControllableByOwner = No`; change one to `Yes` and
see whether that army becomes selectable and movable. No new INI, no patch, one character. **Still
the first thing to do** — it is now a cheaper test than when this plan was written, and the static
trace above says it should work.

**Caveat.** Static evidence only. Per the working rule at the bottom, `army+0x58` should be read
live through `live-bridge` to confirm the value lands before concluding anything from in-game
behaviour.

## 3. Heroes across the battle boundary — *every tool is live; two of them are used once between them*

> **Superseded in part, 2026-08-27.** Problem (2) below — the dead hero — is answered in
> [`hero-permadeath.md`](hero-permadeath.md): the mechanism is the post-battle harvest at
> `0x00811E1F`, which records only the survivors, and the lever is `ArmyEntry`'s `Default` plus
> `LivingWorldPlayerArmy`'s `SurvivalThreshhold`. The carryover/revival reading in this section is
> a different system and was not the one that loses the hero. Problem (1), the per-hero ownership
> transfer, still stands as written.

**Your complaint, in your words.** Two separate problems, both at the **tactical** boundary rather
than on the strategic map:

1. *Loading into a mission:* the heroes all spawn and every one of them has to be moved to a neutral
   player by hand.
2. *Leaving a mission:* a hero that dies is permanently dead. It can be revived **during** that
   mission, but if it is not, nothing carries the loss — or the hero — forward.

**An earlier revision of this section guessed wrong about (1).** It read "stripped from the player as
they spawn" as the strategic-map verb `SetPlayerControlOfArmy = No`, and built an argument on that.
That verb operates on living-world armies on the campaign map; your problem is unit ownership inside
the battle. The guess is withdrawn — it is recorded in *Corrections* below rather than quietly
deleted, because it is the third time in this investigation that a plausible reading of a name
substituted for evidence.

### What the mod actually does, counted

Parsing all 32 `map kampa *` campaign maps and reading every action by `internal_name`:

| action | uses | status |
|---|---|---|
| `NAMED_TRANSFER_OWNERSHIP_PLAYER` | **243** | live |
| `CREATE_DELAYED_CARRYOVER_UNIT_AT_WAYPOINT` | **22** | live |
| `CREATE_UNIT_REVIVAL_ENTRY_AT_LEVEL` | **1** | live |
| `CREATE_UNIT_REVIVAL_ENTRY_FROM_DELAYED_CARRYOVER_HERO` | **1** | live |
| `PLAYER_TRANSFER_OWNERSHIP_PLAYER` | 1 | live |
| any `*_ASSIMILATE_WITH_ARMY_BY_NAME` | **0** | dead anyway |

**`NAMED_TRANSFER_OWNERSHIP_PLAYER` is the hero workaround** — 243 uses, none of them optional.
`map kampa angmar 01` carries a script named *"Return my sons to me"* that transfers Rogash, Gulzar,
Helegwen, Hwaldar, Karsh, Mornamarth and Zaphragor to `Player_2` one call at a time. That is the
per-hero hand-moving, and it exists because a converted WotR battle has only `Player_1` and
`Player_2` to work with.

**Heroes arrive by delayed carryover**, not by any army mechanism:

```
CREATE_DELAYED_CARRYOVER_UNIT_AT_WAYPOINT( ThingTemplate, owner, waypoint, scriptingName )
    ['ImladrisArwen',   '<Local Player>', 'Event Tracker 03 Spawn', 'Event Tracker 03']
    ['DwarvenGloin_mod','<Local Player>', 'Gloin SPawn',            'Gloin']
    ['WildGoblinKing_mod','Player_2',     'Player_2_Start',         'Goblin King']
```

**And the revival half is used twice in the entire corpus**, both in `map kampa evil 08`, in a script
named *"Shelob and Drogoth made buildable"*:

```
CREATE_UNIT_REVIVAL_ENTRY_AT_LEVEL( 'Drogoth', 'Player_2', 7 )
CREATE_UNIT_REVIVAL_ENTRY_FROM_DELAYED_CARRYOVER_HERO( 'WildShelob', '<Local Player>' )
```

So the tool that makes a dead hero come back is live, understood well enough by the author to have
been used once, and then not used anywhere else. **On this evidence permadeath looks like an
authoring gap rather than an engine one** — with the open question being whether a revival entry
survives the mission boundary, which the single in-mission use ("made buildable") does not prove.

**What is actually there.** Both problems have named script actions, and the decisive fact is which
of them the engine implements. From [`dead-script-actions.md`](dead-script-actions.md):

| id | action | status | bears on |
|---|---|---|---|
| 540 | `PLAYER_ASSIMILATE_WITH_ARMY_BY_NAME` | **DEAD** | (1) |
| 541 | `TEAM_ASSIMILATE_WITH_ARMY_BY_NAME` | **DEAD** | (1) |
| 542 | `UNIT_ASSIMILATE_WITH_ARMY_BY_NAME` | **DEAD** | (1) |
| 514 | `TEAM_ASSIMILATE_WITH_FIRST_WALK_ON_ARMY` | live | (1) |
| 515 | `UNIT_ASSIMILATE_WITH_FIRST_WALK_ON_ARMY` | live | (1) |
| 579 | `CREATE_DELAYED_CARRYOVER_UNIT_AT_WAYPOINT` | live | (2) |
| 595 | `CREATE_UNIT_REVIVAL_ENTRY` | live | (2) |
| 596 | `CREATE_UNIT_REVIVAL_ENTRY_FROM_DELAYED_CARRYOVER_HERO` | live | (2) |
| 597 | `CREATE_UNIT_REVIVAL_ENTRY_AT_LEVEL` | live | (2) |

For **(1)**, the intended tool is dead at **all three scopes** — player, team and unit. Attaching
units to a *named* living-world army is simply not implemented, which is why the heroes have to be
moved by hand: that is not a workaround you chose over a better option, it is the only option left.
The one lever is the `*_WITH_FIRST_WALK_ON_ARMY` pair, which is live and picks the army implicitly
instead of by name. Cheapest experiment in this section.

For **(2)**, the persistence machinery is *entirely live*, and one action names your exact case:
`CREATE_UNIT_REVIVAL_ENTRY_FROM_DELAYED_CARRYOVER_HERO`. Read together with the INI fields
`DelayCarryoverSpawningOf` and `ArmyCarryoverPoints`, the shape it implies is: a hero that dies
becomes a *delayed carryover* record, and a later mission turns that record into a revival entry.
Nothing in that chain is stubbed.

**The catch, confirmed.** The suspicion that carryover is *linear*-campaign state is now established
by where the fields live:

| field | owning block | note |
|---|---|---|
| `CarryoverUnit` | the linear **`Campaign`** block, beside `CampaignDisplayNameLabel` and `Mission` | its neighbouring string is `CurrentCampaign…`, and its class's name getter is `0x0078010E` — a save-game snapshot block |
| `DelayCarryoverSpawningOf` | the linear **`Mission`** block, beside `Map`, `IntroMovie`, `LoadScreenImage` | same system |
| `ArmyCarryoverPoints` | **campaign-level**, in the same field table (`0x00BFA2C0`) as `ArmyRetreatRounds` | **set nowhere in the mod** |

So the carryover *store* belongs to the linear campaign, not the living world — which is consistent
with heroes persisting correctly through a linear campaign and being lost in a WotR one.

`ArmyCarryoverPoints` is the one unused knob aimed at this problem: it sits directly alongside
`ArmyRetreatRounds`, which Edain does set (`= 8`), and its name suggests it governs what an army
carries between battles. Semantics unknown; one INI line to find out.

**A correction to an earlier revision of this section**, which listed `ArmyCarryoverPoints` loosely
among *region* carryover fields. It is campaign-level. `DelayCarryoverSpawningOf` was likewise
described as a mission field without noting that the `Mission` block in question is the **linear**
campaign's.

### BFME1 did not solve this — it never had the problem

BFME1 contains **zero** carryover machinery. Counting strings across both binaries:

| string | RotWK | BFME1 |
|---|---|---|
| `Carryover` / `carryover` (any casing) | 9 | **0** |
| `CREATE_DELAYED_CARRYOVER_UNIT_AT_WAYPOINT` | 1 | **0** |
| `CREATE_UNIT_REVIVAL_ENTRY` | 3 | **0** |
| `ArmyCarryoverPoints`, `DelayCarryoverSpawningOf` | 1 each | **0** |
| `MSG_REVIVE` | 1 | 1 |

The only shared string is in-mission revive.

> **Wrong, and measured wrong on 2026-08-28.** The string counts above are accurate; the paragraph
> that used to follow them was not. It read: *"BFME1's strategic armies are defined by
> `LivingWorldPlayerArmy` `ArmyEntry` rows, each battle instantiates from that roster afresh, and
> nothing ever writes back — so a hero killed in a battle is still on the roster afterwards…
> Heroes come back in BFME1 because their death was never recorded, not because anything revives
> them. RotWK added persistence, and persistence of death is the regression."*
>
> **BFME1 writes back.** Read out of two BFME1 saves either side of Saruman's death in evil mission
> 1: `Evil_SarumanPlayerArmy` went in holding one `ArmyEntry` and came out holding six — five
> surviving Isengard hordes it never had, plus Saruman carrying an `Upgrade_SarumanFireBall` he
> never had. Both games harvest a battle into their living-world armies. They differ in **one
> rule**: BFME1 keeps a hero with no surviving object in his army, RotWK moves him out of it into
> the faction's fortress hero-spawn queue. See [`hero-permadeath.md`](hero-permadeath.md).
>
> The absence of a `Carryover` string in BFME1 says BFME1 has no *carryover subsystem*. It does not
> say BFME1 has no persistence, and reading it that way is what produced the wrong framing.

That also explains why BFME1 needed [`ModifyArmyEntry`](bfme1-act-verbs.md) — swapping
`CurUnitTemplate` for `NewUnitTemplate` was the *only* way to change an army's membership, precisely
because combat could not.

### What to do about it, in confidence order

1. **Author the revival entry.** No patch, and `map kampa evil 08` is a working example in the mod
   already. Every other mission spawns heroes by delayed carryover and creates no revival entry, so
   applying that pattern is the cheapest available fix. Proven *within* a mission; cross-mission
   persistence untested.
2. **Prevent the death.** `UNIT_AFFECT_OBJECT_PANEL_FLAGS(<hero>, 'Indestructible', …)` — already
   used on Rogash in `map kampa angmar 01`. Blunt but reliable.
3. **Try `ArmyCarryoverPoints`.** One INI line, unknown semantics, aimed squarely at this.
4. **Patch the write-back** — not located. The living army holds its hero at `+0x18`
   ([`battle-sides.md`](battle-sides.md)), and nothing in the living-world manager's range shrinks
   its army vector, so the hero is being emptied or flagged rather than deleted. Finding that flag is
   the next anchor.

**Settles it.** Two steps: author a `SpawnArmy` with `HeroTemplateName` and see what it produces
(that alone may replace the brittle workaround); then find the readers of `ArmyCarryoverPoints` and
`DelayCarryoverSpawningOf` and establish whether the living-world battle-exit path writes carryover
state at all. `sage_save` decodes the save structures and is the right instrument for the second
half.

## 4. Reinforcement timers — *unknown, cheap to settle*

**What is known.** `SecondsPerReinforcement` is parsed into `campaign+0x44`. No shipped campaign
sets it; Angmar reads **1** live, which is the constructor default. Whether anything consumes it is
**unproven** — a scan for readers found only comparisons against 0/1/2, which look like a phase
enum on a different object, not a seconds count.

**Settles it.** Set it to something distinctive (say 600), read `campaign+0x44` live to confirm the
value lands, and watch whether reinforcement behaviour changes. If the field lands but nothing
changes, it is parsed-and-dropped and the feature needs the engine work, not the INI line.

## 5. `ForceAdvanceTurnPhase` — *unknown, now low priority*

**Update 2026-08-14:** the Angmar scenario now sets it, and it reads **1** live at `campaign+0x5A` —
so the field lands. Whether anything *consumes* it is still unproven, and the paragraph below stands
otherwise.

Parsed into `campaign+0x5A`, set by **no shipped campaign anywhere**, reads 0 live. It was the
obvious candidate for "forced to press End Turn" — but scripted mode already removed that
requirement, so it may be redundant. Byte reads at `+0x5A` exist at `0x006B2F20` and `0x006BE27E`
in `LivingWorldLogic`, but the register was never proven to hold a campaign. One INI line to test;
worth doing only if turn pacing is still wrong after §2.

## 6. Splitting and merging armies — *verified absent, the real engine work*

**Your complaint, and the one that is genuinely a removal.** This section previously described two
blocks, `SplitArmy` and `MergeArmy`. That was the wrong shape. **BFME1 has one verb doing both
directions**, read out of `gondorcampaign.ini`:

```
MergePlayerArmy
    SourceArmy        = FellowshipPlayerArmy
    DestArmy          = MerryAndPippinPlayerArmy
    SplitArmyTemplate = MerryAndPippinSplitArmy
    SplitArmy         = Yes          ; omit to merge instead
End
```

`SplitArmyTemplate` names *which sub-army moves*; `SplitArmy = Yes` moves it out of `SourceArmy`
into `DestArmy`, and without the flag the block merges. Gondor uses 15 blocks, 11 of them splits,
and the content is exactly the Fellowship narrative — Merry and Pippin splitting off, Sam and Frodo
splitting off, Gandalf joining Éomer. That is what the mechanic was *for*.

**The removal is wider than stated.** Absent from RotWK, present in BFME1:

```
MergePlayerArmy  SplitArmy  SplitArmyTemplate  SourceArmy  DestArmy
DespawnArmy      PlayerOwned  PathFindRule
```

Zero occurrences of any of them in `game.dat`. `DespawnArmy` (20 uses in gondor, 7 in mordor) is the
one this plan previously missed, and taking an army *off* the map is arguably as load-bearing as
splitting it.

**Edain already tried.** `wotrscenarioangmar.inc` carries two `MergePlayerArmy` blocks and a
`DespawnArmy`, written out in full and **commented out** (lines 493–506). Somebody reached for this
and found it inert. That is corroboration, not new information — but it does mean the authoring
intent is already in the file, waiting for a runtime.

**Scoped in full: [`bfme1-act-verbs.md`](bfme1-act-verbs.md).** Dumping both games' Act verb tables
turned this from a vague "the blocks are gone" into an exact inventory. RotWK has **15** Act verbs,
BFME1 **18**; thirteen are shared, one was renamed (`ToggleArmyControl` → `SetPlayerControlOfArmy`),
RotWK added `SpawnBuilding`, and **four were removed**:

| verb | shape | note |
|---|---|---|
| `DespawnArmy` | a single `AsciiString` field on the Act, not a block | smallest of the four |
| `ModifyArmyEntry` | `PlayerArmy`, `CurUnitTemplate`, `NewUnitTemplate` | **composition mutation, as substitution** |
| `MergePlayerArmy` | `SourceArmy`, `DestArmy`, `SplitArmyTemplate`, `SplitArmy` | the Fellowship mechanic |
| `RegionReinforcements` | 7 fields, distance-scaled timers, `PathFindRule`, `AutoSummon` | an entire subsystem |

**`ModifyArmyEntry` answers this section's open question.** "Can RotWK's army model express a change
of composition?" was the cost gate, and BFME1 shows the operation it actually needs to support is
narrower than feared: *substitute one unit template for another inside a named army*. Not arbitrary
add/remove — replace.

**And the scaffolding turned out cheap.** RotWK's Act verb table at `0x00C84030` cannot grow in
place (a zero terminator then string data), but it has **exactly one reference in the image**, at
`0x0096E7F3`. Relocating it to a cave is a one-dword change. So for all four verbs the parser side
is nearly free and the runtime is the entire cost.

**Settles the cost question.** Read BFME1's `MergePlayerArmy` and `ModifyArmyEntry` runtimes past
their parsers (`0x007B8500`, `0x007B88F0`) and look for the equivalent army fields in RotWK.

## Order of work

| | item | shape | confidence |
|---|---|---|---|
| 1 | `DisableRegions` + `EnableRegion` per act ([`region gating`](living-world-region-gating.md)) | **INI only** | both live and unused; fixes the wasted-act problem by construction |
| 2 | Author revival entries for spawned heroes (§3) | **INI/script only** | a working example already exists in `map kampa evil 08` |
| 3 | Flip one `IsControllableByOwner` to `Yes` (§2) | **one character** | traced end to end; only the live check is missing |
| 4 | `objectives-screen` patch, now shipped ([`scope`](../objectives-in-any-map.md)) | applied, widened to three call sites after a failed live run | **runtime-verified 2026-08-14** in a WotR battle; mission *two*, the hotkey and the no-objectives fallback are still open |
| 5 | `SecondsPerReinforcement` (§4), `ArmyCarryoverPoints` (§3) | INI only | unknown, cheap, one line each |
| 6 | Menu entry for scripted campaigns (§1) | patch, precedent exists | that code path has never run in a shipped build |
| 7 | **Give a scripted battle its players** ([`battle-sides`](battle-sides.md)) | RE, then patch | **now the blocking item, measured 2026-08-14**: with `IsScriptedCampaign` set a battle has *no* faction players and the client is seated as an observer. The mechanism is not yet traced, and the older third-party prune is a second, separate reduction |
| 8 | Split/merge/despawn armies (§6, [`act verbs`](bfme1-act-verbs.md)) | large patch | scaffolding is a one-dword relocation; the runtime is the cost |

The top three are authoring, cost nothing, and between them address the wasted act, hero permadeath
and the movement complaint. Items 1 and 2 are the cheapest findings in the whole investigation and
both are things the mod already half-wrote and stopped.

The old item "`HeroTemplateName`" is gone from this table because it turned out to be in use
everywhere (§3), and "is a spawned army's composition mutable?" is gone because
[`bfme1-act-verbs.md`](bfme1-act-verbs.md) settled it — `LivingWorldPlayerArmy`/`ArmyEntry` parses
today and `ModifyArmyEntry` only ever substituted one template for another.

**Before any live test:** ~~the mod tree is currently pristine~~ — **no longer true as of
2026-08-14.** The recipe from [`living-world-campaign.md`](living-world-campaign.md) is applied:
`wotrscenarioangmar.inc` carries `IsScriptedCampaign`, `LocalPlayer` and its `AddPlayer` blocks, and
`gamedata.ini` sets `LivingWorldCampaignOverrride = WOTRScenarioAngmar`. What still needs checking
before a run is the **binary** — see [`verify`](../README.md#cli), and note that the mod's INI
reaches the game only through a Mod Command repack, since the install has no loose `data/ini/`.

**And the flag is now a switch, not a setting:** with `IsScriptedCampaign = Yes` the battles have no
players (item 7). Turn it off to test anything *inside* a battle; turn it on to test act
progression. They cannot currently both be true.

## Corrections to this plan

Recorded in the manner of [`living-world-campaign.md`](living-world-campaign.md), because the
pattern matters more than the individual slips. All four came from reading the shipped INI data
rather than the binary — the opposite failure mode from the two recorded there.

1. **"`SetPlayerControlOfArmy` … looks like a verb nobody has used" was wrong.** It is used **65
   live times across five Edain scenarios** (67 occurrences, two commented), 15 of them in the very
   campaign that was run to prove scripted mode works. The real finding is narrower and sharper:
   every use is `No`.
2. **"`SetPlayerControlOfArmy` does not exist in BFME1 at all" was wrong** in substance. The
   *string* is absent; the *mechanic* is `ToggleArmyControl`, and BFME1 uses both directions.
3. **`HeroTemplateName` was presented as an untried lever.** It is on 185 lines across the mod and
   95 in stock RotWK.
4. **The `SpawnArmy` comparison implied RotWK's 18 fields were a superset of BFME1's 9.** They are
   not: RotWK has no `PlayerOwned` and no `Faction` (field table `0xC78380`, dumped).
5. **The hero workaround was placed on the wrong side of the battle boundary.** §3 identified it as
   the strategic-map verb `SetPlayerControlOfArmy = No`. It is not: the actual complaint is that
   heroes spawning **into a tactical mission** must each be moved to a neutral player, which is unit
   ownership inside the battle. Corrected from the author's description, not from evidence — the
   original claim had none, which is the point.

The common cause of 1–4: the first pass compared *engine capability* by scanning binaries, and
inferred *usage* from that. Capability and usage are different questions, and for a plan about what
to author next, usage was the one that mattered.

The cause of 5 is worse and worth naming separately: a name that sounded like the complaint was
treated as the referent of the complaint. `SetPlayerControlOfArmy … = No` really does mean "take
this away from the player", and it really is used 65 times — but wanting it to be the answer is not
evidence that it is. Two of the five corrections here now come from reading a name and inferring a
mechanism.

## Working rule

**Verify live, not statically.** Two claims in this investigation were wrong — `LiveCampaignMode`'s
default, and a commented-out line read as live — and static reading produced both. The install now
carries `live-bridge`, and the campaign object's layout is written down in
[`living-world-campaign.md`](living-world-campaign.md), so any of these questions can be answered
by attaching and reading a field rather than by inferring one.
