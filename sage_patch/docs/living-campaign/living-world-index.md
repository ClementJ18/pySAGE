# The Living World investigation — an index

What was asked, what was found, and which document holds it. Engine build `2.01.2614.37001`;
BFME1 comparisons against `C:\BFME1\lotrbfme.exe`.

## Start here

[`living-world-parity.md`](living-world-parity.md) is the plan and the order of work. Everything
else is evidence feeding it.

## The documents

| document | what it establishes |
|---|---|
| [`living-world-campaign.md`](../living-world-campaign.md) | **Working.** A scripted campaign runs its acts with no End Turn: `IsScriptedCampaign = Yes`, declare players, name it through `LivingWorldCampaignOverrride`. One four-byte patch. |
| [`living-world-parity.md`](living-world-parity.md) | The plan. Ordered work items, the BFME1/RotWK feature diff, and five recorded corrections. |
| [`living-world-region-gating.md`](living-world-region-gating.md) | Why the player can waste an act wandering into owned territory: `DisableRegions` + `EnableRegion` are live and **unused**. INI-only fix. |
| [`bfme1-act-verbs.md`](bfme1-act-verbs.md) | RotWK has 15 campaign Act verbs to BFME1's 18. The four lost — `DespawnArmy`, `ModifyArmyEntry`, `MergePlayerArmy`, `RegionReinforcements` — with their exact INI field specs. |
| [`bfme1-vs-rotwk-actions.md`](bfme1-vs-rotwk-actions.md) | Name-based script-action diff: exactly **8** regressed, none improved, 52 added. Living-world army scripting never worked in *either* game. |
| [`dead-script-actions.md`](dead-script-actions.md) | 66 stub slots + 19 gutted bodies; 34 genuinely unimplemented after accounting for the two-stage dispatch. Includes a traced route to reviving the assimilate block. |
| [`battle-sides.md`](battle-sides.md) | Who plays in a battle. `SidesList`'s two arrays, the `Player_1` = owner / `Player_2` = attacker convention, the `AddPlayer` trace, and the unresolved `m_sides` prune. |
| [`mission-objectives.md`](mission-objectives.md) | The objectives system is entirely intact and already authored — the only system in this investigation where nothing was removed. |
| [`objectives-in-any-map.md`](../objectives-in-any-map.md) | Why the objectives button opens the player list outside the linear campaign, and the shipped [`objectives-screen`](../../patches/objectives_screen.py) patch that fixes it. |
| [`living-world-menu-entry.md`](living-world-menu-entry.md) | `AptMainMenu::OnTutorial("Strategic")` is a menu-driven Living World launcher that **no shipped movie calls**. The route to a shippable menu entry. |

## The findings that changed the picture

**RotWK is not a cut-down BFME1.** It added 52 script actions, a whole carryover system, and
`IsScriptedCampaign`; it dropped 8 script actions and 4 Act verbs. The gap is specific, not general.

**Most of the complaints are authoring, not engine.** `EnableRegion`, `DisableRegions`,
`ForceBattle`, `IsControllableByOwner = Yes` and the revival-entry actions are all live and unused
or near-unused in the mod. Two of them were written into the INI and commented out.

**The strategic layer was never script-driven.** Every `LIVING_WORLD_*_ARMY` action is a stub or
gutted in *both* games. BFME1 moved armies through campaign-INI Act verbs, which is where the real
parity gap lives.

**Hero permadeath is an inversion, not a regression of a feature.** BFME1 has zero carryover
machinery; heroes came back because death was never recorded. RotWK added persistence, and
persistence of death is the problem.

## What is shipped

One patch: [`objectives-screen`](../../patches/objectives_screen.py) — the Palantir button opens
`Objectives.apt` on any map that declares objectives, instead of only in the linear campaign. Twelve
tests, all disassembly-based, and **runtime-verified in a War of the Ring battle on 2026-08-14**.

## What is still open

| | question | where |
|---|---|---|
| 1 | What prunes `m_sides` for a WotR battle? | **still open, sharpened 2026-08-14** — a 7-side map seats 3 unscripted and 1 scripted, so the reduction is upstream of `newGame` in both. [`battle-sides.md`](battle-sides.md) |
| 1b | How do the campaign's `AddPlayer` entries reach a **scripted** battle? | the blocking item: scripted battles have no faction players at all — [`battle-sides.md`](battle-sides.md) |
| 2 | Does a revival entry survive the mission boundary? | [`living-world-parity.md`](living-world-parity.md) §3 |
| 3 | Does `AptMainMenu::OnTutorial("Strategic")` work at all? | [`living-world-menu-entry.md`](living-world-menu-entry.md) |
| 4 | Is `tracker->[0x10]` reset between maps? | [`objectives-in-any-map.md`](../objectives-in-any-map.md) |
| 5 | What does `ArmyCarryoverPoints` do? | [`living-world-parity.md`](living-world-parity.md) §3 |

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

"No callers found" is not "never called": virtual dispatch defeats a direct-call scan, and that trap
produced one of the wrong claims. Check for a vtable reference before concluding a function is dead.
