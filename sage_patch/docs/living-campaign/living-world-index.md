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
| [`living-world-parity.md`](living-world-parity.md) | The plan. Ordered work items, the BFME1/RotWK feature diff, and five recorded corrections. |
| [`living-world-region-gating.md`](living-world-region-gating.md) | Why the player can waste an act wandering into owned territory: `DisableRegions` + `EnableRegion` are live and **unused**. INI-only fix. |
| [`bfme1-act-verbs.md`](bfme1-act-verbs.md) | RotWK has 15 campaign Act verbs to BFME1's 18. The four lost — `DespawnArmy`, `ModifyArmyEntry`, `MergePlayerArmy`, `RegionReinforcements` — with their exact INI field specs. |
| [`bfme1-vs-rotwk-actions.md`](bfme1-vs-rotwk-actions.md) | Name-based script-action diff: exactly **8** regressed, none improved, 52 added. Living-world army scripting never worked in *either* game. |
| [`dead-script-actions.md`](dead-script-actions.md) | 66 stub slots + 19 gutted bodies; 34 genuinely unimplemented after accounting for the two-stage dispatch. Includes a traced route to reviving the assimilate block. |
| [`merge-player-army.md`](merge-player-army.md) | **Built.** BFME1's `MergePlayerArmy` traced end to end — it moves `ArmyEntry` records, with `SplitArmyTemplate` as the manifest — and the RotWK re-implementation, shipped with `DespawnArmy` as [`campaign-army-verbs`](../../patches/experimental/campaign_army_verbs.py). Establishes that the Act struct is `0xB8` bytes with three spare, so no new verb can add a per-act list. |
| [`hero-permadeath.md`](hero-permadeath.md) | **Resolved, both games measured.** Both BFME1 and RotWK harvest a battle back into the living-world army. The single difference: BFME1 keeps a hero with no surviving object **in his army**; RotWK moves him **out**, to the fortress hero-spawn queue, re-buyable with his upgrades. Includes the BFME1 control experiment, the failed `Default`/`SurvivalThreshhold` fix, and the four wrong readings on the way. |
| [`battle-sides.md`](battle-sides.md) | Who plays in a battle. `SidesList`'s two arrays, the `Player_1` = owner / `Player_2` = attacker convention, the `AddPlayer` trace, and the unresolved `m_sides` prune. |
| [`mission-objectives.md`](mission-objectives.md) | The objectives system is entirely intact and already authored — the only system in this investigation where nothing was removed. |
| [`objectives-in-any-map.md`](../objectives-in-any-map.md) | Why the objectives button opens the player list outside the linear campaign, and the shipped [`objectives-screen`](../../patches/objectives_screen.py) patch that fixes it. |
| [`living-world-menu-entry.md`](living-world-menu-entry.md) | `AptMainMenu::OnTutorial("Strategic")` is a menu-driven Living World launcher that **no shipped movie calls**. The route to a shippable menu entry. |
| [`act-advance-stall.md`](act-advance-stall.md) | **Scoped, not yet measured.** Why a scripted act sometimes stops until you zoom out and back in. An act advances only when the turn phase reaches 6, and the phase is braked in four places by the strategic message-box gate — a box marked showing whose dialog was never pushed to `TheAptPlayer` freezes the campaign, and the camera round trip runs the overlay re-show hook that releases it. Carries the live read that separates the candidates and the `living-world-box-watchdog` patch scope. |
| [`scenario-player-factions.md`](../scenario-player-factions.md) | Who may play what in a WotR scenario: `DisabledFactions` has no player in it, `StartingRestriction`'s faction filter is skipped for a `HistoricalScenario`, and the four readers a per-player rule has to reach. The [`scenario-player-factions`](../../patches/experimental/scenario_player_factions.py) patch. |

## The findings that changed the picture

**RotWK is not a cut-down BFME1.** It added 52 script actions, a whole carryover system, and
`IsScriptedCampaign`; it dropped 8 script actions and 4 Act verbs. The gap is specific, not general.

**Most of the complaints are authoring, not engine.** `EnableRegion`, `DisableRegions`,
`ForceBattle`, `IsControllableByOwner = Yes` and the revival-entry actions are all live and unused
or near-unused in the mod. Two of them were written into the INI and commented out.

**The strategic layer was never script-driven.** Every `LIVING_WORLD_*_ARMY` action is a stub or
gutted in *both* games. BFME1 moved armies through campaign-INI Act verbs, which is where the real
parity gap lives.

**Hero permadeath is one rule, and both games were measured.** Saves either side of a hero's death
in *both* games, 2026-08-28: **both** BFME1 and RotWK harvest a battle back into the living-world
army, survivors and their upgrades included. They differ in what happens to a hero record with no
surviving object — BFME1 **keeps him in his army**, RotWK **moves him out** into the faction's
fortress hero-spawn queue, re-buyable as a one-hero army with his upgrades intact. That is the
entire difference, and it is a one-rule patch target rather than a missing subsystem.

This replaces the framing the investigation ran on for weeks — *"BFME1 has zero carryover
machinery; heroes came back because death was never recorded; RotWK added persistence and
persistence of death is the problem"* — which was inferred from BFME1's string counts and is wrong.
BFME1's binary really does contain no `Carryover` string; it writes battle results back anyway.
The correction is in [`living-world-parity.md`](living-world-parity.md) §3 and the evidence in
[`hero-permadeath.md`](hero-permadeath.md), which also carries the INI fix that was tried in play
and failed.

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
[`scenario-player-factions`](../../patches/experimental/scenario_player_factions.py) — `DisabledFactions`
gains a `:N` player qualifier, so a scenario can pin a faction to a lobby slot instead of only to the
scenario (fifty-eight tests) — and
[`campaign-army-verbs`](../../patches/experimental/campaign_army_verbs.py), which restores BFME1's
`MergePlayerArmy` and `DespawnArmy` Act verbs (forty-nine tests, see
[`merge-player-army.md`](merge-player-army.md)).

## What is still open

| | question | where |
|---|---|---|
| 1 | What prunes `m_sides` for a WotR battle? | **still open, sharpened 2026-08-14** — a 7-side map seats 3 unscripted and 1 scripted, so the reduction is upstream of `newGame` in both. [`battle-sides.md`](battle-sides.md) |
| 1b | How do the campaign's `AddPlayer` entries reach a **scripted** battle? | the blocking item: scripted battles have no faction players at all — [`battle-sides.md`](battle-sides.md) |
| ~~2~~ | ~~Where is a hero's death recorded?~~ | **closed 2026-08-28: nowhere — he is not dead.** He returns to the fortress hero-spawn queue. What remains open is how to put a re-bought hero *back into his old army*: `ArmyToSpawn` has no `ScriptingName`, so `MergePlayerArmy` cannot address one — [`hero-permadeath.md`](hero-permadeath.md) |
| 2b | ~~Does the post-battle harvest replace the army's records or append to them?~~ | **settled 2026-08-28 by measurement: replaced** — [`hero-permadeath.md`](hero-permadeath.md) |
| 3 | Does `AptMainMenu::OnTutorial("Strategic")` work at all? | [`living-world-menu-entry.md`](living-world-menu-entry.md) |
| 4 | Is `tracker->[0x10]` reset between maps? | [`objectives-in-any-map.md`](../objectives-in-any-map.md) |
| 6 | Which candidate in [`act-advance-stall.md`](act-advance-stall.md) §5 is the real stall? | needs one live read while stuck — §6 lists it in order |
| 5 | What does `ArmyCarryoverPoints` do? | [`living-world-parity.md`](living-world-parity.md) §3 — lower priority now that `SurvivalThreshhold` is the identified knob |

~~**Nothing in this investigation has been run against the game.**~~ **Out of date as of
2026-08-14.** A live session that day settled question 1, runtime-verified the `objectives-screen`
patch in a War of the Ring battle, and read `ForceAdvanceTurnPhase` set for the first time. Claims
still carry their own provenance: everything not marked as measured is static analysis or map/INI
data. The earlier live result was `living-world-campaign.md`'s scripted campaign, confirmed in game
on 2026-08-11.

## A note on method

Six claims in this investigation turned out wrong and are recorded in the documents that carried
them rather than quietly deleted. The pattern is worth internalising:

- **Two** came from reading the binary and inferring behaviour — caught by reading the running
  process.
- **Two** came from comparing engine *capability* and inferring *usage* — caught by counting the
  shipped INI and map data.
- **Two** came from a name that sounded like the answer — the hero workaround (twice), caught by the
  author saying what actually happens.
- **Two** came from the hero-permadeath pass on 2026-08-27/28, and they are the sharpest examples
  in the list because they were made a day apart on the same structure. The first read a field
  table correctly and then read the *function consuming it* too broadly — `SurvivalThreshhold` and
  `Default` do exactly what the disassembly said, one layer below where the fix needed them; caught
  by playing the mission. The second concluded that the post-battle harvest **appends** to an
  army's roster because no *clear* call could be found near it; caught the next morning by counting
  the entries in two saves, which showed a replace. The absence of the obvious mechanism is not
  evidence for the alternative: the records were being consumed one at a time somewhere else
  entirely. Both would have been caught earlier by asking "how many callers does this have, and
  what are they" before believing what a function is for.

"No callers found" is not "never called": virtual dispatch defeats a direct-call scan, and that trap
produced one of the wrong claims. Check for a vtable reference before concluding a function is dead.
