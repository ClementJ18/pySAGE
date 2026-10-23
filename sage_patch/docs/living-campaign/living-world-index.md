# The Living World investigation — an index

What was asked, what was found, and which document holds it. Engine build `2.01.2614.37001`;
BFME1 comparisons against `C:\BFME1\lotrbfme.exe`.

## Start here

[`living-world-parity.md`](living-world-parity.md) is the plan and the order of work. Everything
else is evidence feeding it.

## The documents

| document | what it establishes |
|---|---|
| [`living-world-campaign.md`](living-world-campaign.md) | **Working.** A scripted campaign runs its acts with no End Turn: `IsScriptedCampaign = Yes`, declare players, name it through `LivingWorldCampaignOverrride`. One four-byte patch. |
| [`living-world-parity.md`](living-world-parity.md) | The plan. Ordered work items and the BFME1/RotWK feature diff. |
| [`living-world-region-gating.md`](living-world-region-gating.md) | Why the player can waste an act wandering into owned territory: `DisableRegions` + `EnableRegion` are live and **unused**. INI-only fix. |
| [`hero-army-slot-overflow.md`](hero-army-slot-overflow.md) | **Scoped, static only, 2026-10-01.** The crash with a fifth leader in one territory: Edain authors exactly four `HeroArmySpot`s per region, `Region::reserveArmySlot` (`0x007F3D27`) fails on the fifth, and `spawnArmy` ignores that failure and positions the army from stack garbage. Proposed `hero-army-slot-overflow` patch: share the least-occupied spot instead of failing. The fault site is unconfirmed, and a one-line INI control test decides it. |
| [`ai-disabled-regions.md`](ai-disabled-regions.md) | **Read from crash dumps, 2026-09-13.** Any scenario with `DisableRegions` crashes on the AI's first turn: the AI region graph skips disabled regions and the planner looks them up unchecked. Fixed by [`ai-disabled-regions`](../../patches/ai_disabled_regions.py), runtime-verified 2026-09-22. |
| [`hide-selection-details.md`](hide-selection-details.md) | **Built, static only, 2026-09-13.** The selection-details tray is `StrategicDetailsTray.apt`, driven by one engine class whose `setHasContent` decides whether the HUD's refresh closes it. A `Scenario` `HideSelectionDetails` flag, read through the campaign manager's current campaign, keeps it shut: [`hide-selection-details`](../../patches/experimental/hide_selection_details.py). |
| [`force-battle.md`](force-battle.md) | **Built, static only, 2026-09-13.** `ForceBattle`'s battle form calls a bare `ret 0xC`; the engine's one live battle creator (`RegionStore::createBattle`, phase 1) and how `SpawnArmy` snaps a `Position` to a region slot. Both re-implemented in [`campaign-army-verbs`](../../patches/campaign_army_verbs.py): `ForceBattle` builds the battle the conflict pass would, `ExactPosition = Yes` keeps a spawned army on its point. |
| [`reinforcements.md`](reinforcements.md) | **Built, static and emulated, 2026-10-20.** How a battle's reinforcement armies work: a five-state roster machine at `roster+0x2C` (waiting, in battle, summoning, ready, called in), the banner's two clicks as `MSG_SUMMON_REINFORCEMENTS` / `MSG_CALL_IN_REINFORCEMENTS`, the AI's direct call-in, and a complete auto-summon step nothing calls. Stub action 543 revived as [`call-in-reinforcements`](../../patches/call_in_reinforcements.py): call an army in by its overworld `ScriptingName`. |
| [`bfme1-act-verbs.md`](bfme1-act-verbs.md) | RotWK has 15 campaign Act verbs to BFME1's 18. The four lost — `DespawnArmy`, `ModifyArmyEntry`, `MergePlayerArmy`, `RegionReinforcements` — with their exact INI field specs. |
| [`bfme1-vs-rotwk-actions.md`](bfme1-vs-rotwk-actions.md) | Name-based script-action diff: exactly **8** regressed, none improved, 52 added. Living-world army scripting never worked in *either* game. |
| [`dead-script-actions.md`](dead-script-actions.md) | 66 stub slots + 19 gutted bodies; 34 genuinely unimplemented after accounting for the two-stage dispatch. Includes a traced route to reviving the assimilate block. |
| [`merge-player-army.md`](merge-player-army.md) | **Built.** BFME1's `MergePlayerArmy` traced end to end — it moves `ArmyEntry` records, with `SplitArmyTemplate` as the manifest — and the RotWK re-implementation, shipped with `DespawnArmy` as [`campaign-army-verbs`](../../patches/campaign_army_verbs.py). Establishes that the Act struct is `0xB8` bytes with three spare, so no new verb can add a per-act list. |
| [`hero-permadeath.md`](hero-permadeath.md) | **Resolved, both games measured.** Both BFME1 and RotWK harvest a battle back into the living-world army. The single difference: BFME1 keeps a hero with no surviving object **in his army**; RotWK moves him **out**, to the fortress hero-spawn queue, re-buyable with his upgrades. Includes the BFME1 control experiment, why `Default`/`SurvivalThreshhold` cannot restore a hero, and the `hero-army-carryover` patch. |
| [`battle-sides.md`](battle-sides.md) | Who plays in a battle. `SidesList`'s two arrays, the `Player_1` = owner / `Player_2` = attacker convention, the `AddPlayer` trace, and the unresolved `m_sides` prune. |
| [`mp-battle-participation.md`](mp-battle-participation.md) | **Built, runtime-verified 2026-09-06.** Why a co-op War of the Ring battle auto-resolves: one gate at `0x006BEBE5` forces it whenever the battle has fewer participants than the session has humans. The gate exists because `buildSidesFromGameInfo` names sides by slot index and leaves a non-participant with no seat. Shipped as [`wotr-battle-observers`](../../patches/wotr_battle_observers.py), which seats them on the engine's own observer path instead. |
| [`wotr-lobby-slots.md`](wotr-lobby-slots.md) | **Built 2026-10-08, not played.** Why a multiplayer War of the Ring lobby seats six players and two humans: the gadget binder hides slots 7-8 (`0x00840A92`) and the slot-state combo offers `Open` only to the first open slot and to none once a second human sits (`0x0084178D`). Neither is `MaxPlayers`. Shipped as [`wotr-lobby-slots`](../../patches/wotr_lobby_slots.py), two one-byte branch edits. |
| [`wotr-save-failure.md`](wotr-save-failure.md) | **Static, matched against two broken Edain saves; patches built and emulated, not played, 2026-10-14.** Why a War of the Ring save stops half-written or will not load: the campaign-long `LivingWorldScoreKeeper` keeps battle `ThingTemplate *` keys after `ThingFactory::reset` has freed the battle map's `map.ini` templates, and every later save writes their names first thing. `GameState::saveGame` swallows the fault in a `catch (...)` and leaves the partial file. Fixed by [`score-keeper-dangling-keys`](../../patches/score_keeper_dangling_keys.py) (skip entries that fail when merging, saving and loading) and [`save-temp-file`](../../patches/save_temp_file.py) (save to `.tmp`, rename on success). |
| [`mission-objectives.md`](mission-objectives.md) | The objectives system is entirely intact and already authored — the only system in this investigation where nothing was removed. |
| [`objectives-in-any-map.md`](../objectives-in-any-map.md) | Why the objectives button opens the player list outside the linear campaign, and the shipped [`objectives-screen`](../../patches/objectives_screen.py) patch that fixes it. |
| [`living-world-menu-entry.md`](living-world-menu-entry.md) | `AptMainMenu::OnTutorial("Strategic")` is a menu-driven Living World launcher that **no shipped movie calls**. The route to a shippable menu entry. |
| [`act-advance-stall.md`](act-advance-stall.md) | **Scoped, not yet measured.** Why a scripted act sometimes stops until you zoom out and back in. An act advances only when the turn phase reaches 6, and the phase is braked in four places by the strategic message-box gate — a box marked showing whose dialog was never pushed to `TheAptPlayer` freezes the campaign, and the camera round trip runs the overlay re-show hook that releases it. Carries the live read that separates the candidates and the `living-world-box-watchdog` patch scope. |
| [`script-holder.md`](script-holder.md) | **Measured 2026-09-04.** `LivingWorldCampaign`'s `ScriptHolder` names a WorldBuilder layout the campaign loads as its strategic session, at `LivingWorldScripts\<name>\<name>.lws`, and game mode 8 is the living-world mode. The file loads; its scripts never run, because no player in a living-world session has a script list at all. Also: why the "Game crash" box localises nothing. |
| [`scenario-player-factions.md`](../scenario-player-factions.md) | Who may play what in a WotR scenario: `DisabledFactions` has no player in it, `StartingRestriction`'s faction filter is skipped for a `HistoricalScenario`, and the four readers a per-player rule has to reach. The [`scenario-player-factions`](../../patches/scenario_player_factions.py) patch. |

## The findings that changed the picture

**RotWK is not a cut-down BFME1.** It added 52 script actions, a whole carryover system, and
`IsScriptedCampaign`; it dropped 8 script actions and 4 Act verbs. The gap is specific, not general.

**Most of the complaints are authoring, not engine.** `EnableRegion`, `DisableRegions`,
`IsControllableByOwner = Yes` and the revival-entry actions are all live and unused
or near-unused in the mod. Two of them were written into the INI and commented out.
`ForceBattle` was on this list and is not live: its battle form calls an empty stub — see
[`force-battle.md`](force-battle.md).

**The strategic layer was never script-driven.** Every `LIVING_WORLD_*_ARMY` action is a stub or
gutted in *both* games. BFME1 moved armies through campaign-INI Act verbs, which is where the real
parity gap lives.

**Hero permadeath is one rule, and both games were measured.** Saves either side of a hero's death
in *both* games, 2026-08-28: **both** BFME1 and RotWK harvest a battle back into the living-world
army, survivors and their upgrades included. They differ in what happens to a hero record with no
surviving object — BFME1 **keeps him in his army**, RotWK **moves him out** into the faction's
fortress hero-spawn queue, re-buyable as a one-hero army with his upgrades intact. That is the
entire difference, and it is a one-rule patch target rather than a missing subsystem. BFME1's
binary contains no `Carryover` string; it writes battle results back anyway
([`hero-permadeath.md`](hero-permadeath.md)).

## What is shipped

One patch: [`objectives-screen`](../../patches/objectives_screen.py) — the Palantir button opens
`Objectives.apt` on any map that declares objectives, instead of only in the linear campaign. Twelve
tests, all disassembly-based, and **runtime-verified in a War of the Ring battle on 2026-08-14**.

A second, **runtime-verified on 2026-08-28**:
[`hero-army-carryover`](../../patches/experimental/hero_army_carryover.py) — `ArmyEntry` gains
`Persistent`, and a marked hero killed in a mission is back in his army afterwards carrying the
upgrades he earned in it. He is also still offered at his faction's fortress, which is intended:
the patch adds BFME1's army rule without removing ROTWK's own. See
[`hero-permadeath.md`](hero-permadeath.md).

Two more built but not played, both `experimental` and both static-only:
[`scenario-player-factions`](../../patches/scenario_player_factions.py) — `DisabledFactions`
gains a `:N` player qualifier, so a scenario can pin a faction to a lobby slot instead of only to the
scenario (fifty-eight tests) — and
[`campaign-army-verbs`](../../patches/campaign_army_verbs.py), which restores BFME1's
`MergePlayerArmy` and `DespawnArmy` Act verbs (forty-nine tests, see
[`merge-player-army.md`](merge-player-army.md)).

## What is still open

| | question | where |
|---|---|---|
| 1 | What prunes `m_sides` for a WotR battle? | **still open, sharpened 2026-08-14** — a 7-side map seats 3 unscripted and 1 scripted, so the reduction is upstream of `newGame` in both. [`battle-sides.md`](battle-sides.md) |
| 1b | How do the campaign's `AddPlayer` entries reach a **scripted** battle? | the blocking item: scripted battles have no faction players at all — [`battle-sides.md`](battle-sides.md) |
| 2 | How does a re-bought hero get *back into his old army* without `hero-army-carryover`? | `ArmyToSpawn` has no `ScriptingName`, so `MergePlayerArmy` cannot address one — [`hero-permadeath.md`](hero-permadeath.md) |
| 3 | Does `AptMainMenu::OnTutorial("Strategic")` work at all? | [`living-world-menu-entry.md`](living-world-menu-entry.md) |
| 4 | Is `tracker->[0x10]` reset between maps? | [`objectives-in-any-map.md`](../objectives-in-any-map.md) |
| 6 | Which candidate in [`act-advance-stall.md`](act-advance-stall.md) §5 is the real stall? | needs one live read while stuck — §6 lists it in order |
| 7 | What installs a map's script lists onto players, and why does no player in a living-world session get one? | the blocker for `ScriptHolder` - [`script-holder.md`](script-holder.md) §5 |
| 5 | What does `ArmyCarryoverPoints` do? | [`living-world-parity.md`](living-world-parity.md) §3 — lower priority, since the dead-hero question is resolved |

Claims carry their own provenance: everything not marked as measured is static analysis or map/INI
data.

## A note on method

Rules this investigation runs on:

- **Reading the binary is not observing behaviour.** Confirm an inferred behaviour by reading the
  running process.
- **Engine *capability* is not *usage*.** Count the shipped INI and map data before saying a
  feature is unused.
- **A name that sounds like the answer is not evidence that it is.** Ask the author what actually
  happens.
- **Ask how many callers a function has, and what they are, before believing what it is for.**
  `SurvivalThreshhold` and `Default` do exactly what their field table says, one layer below the
  world map — they govern an army arriving in a battle. And the absence of an obvious mechanism is
  not evidence for the alternative: the harvest *replaces* a roster with no clear call anywhere near
  it, because the records are consumed one at a time at deployment.

"No callers found" is not "never called": virtual dispatch defeats a direct-call scan. Check for a
vtable reference before concluding a function is dead.
