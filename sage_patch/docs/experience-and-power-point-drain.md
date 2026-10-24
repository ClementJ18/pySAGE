# Removing experience, levels, and power points

Investigation dated 2026-10-09. Based on local OpenBfme/OpenBfme2 sources,
targeted reads of their matching entries, and direct disassembly of
`tools/BFME-FILES/game.dat.backup`. No patch has been implemented or tested in game.

RotWK file version: 2.01.2614.37001; ImageBase 0x00400000.
SHA-256: `5481de75b63e22483660ea8097478faef594f90b9ade7de893e092256ba68a26`.
All RotWK addresses below are virtual addresses (VAs), not file offsets.
BFME2 addresses in the source code are mostly RVAs; VA = RVA + ImageBase.
Recheck addresses and byte sequences against the actual target before patching.

## Findings

Four operations must be distinguished:

| Operation | Finding | Effort |
|---|---|---|
| Remove available power points | Existing negative-delta path with a zero floor and UI notification | Low |
| Remove player XP used to earn power points | Float accumulator accepts negative values; cap can block the call; no automatic demotion | Low to medium |
| Remove unit XP while retaining the level | Add/set path exists; requires an explicit lower bound | Low to medium |
| Lower unit level and reverse its effects | Named-level application path exists; reversal of all effects is unproven | Medium to high |

Purchasing a spell consumes SciencePurchasePoints. It lowers neither the player's
rank nor their SkillPoints. Player ranks come from RankInfo; unit levels come from
ExperienceLevels. Purchased Sciences are another, separate state.

## OpenBfme and OpenBfme2

OpenBfme's `game/GameEngine/Source/Common/RTS/Player_setRankLevel.cpp` contains
an explicit demotion path: a lower target rank calls `resetRank()`, then rebuilds
up to the target rank. `PlayerRankAndScience.cpp` shows the accompanying reset of
XP, purchase points, and Sciences. This is more than subtracting one rank and can
remove purchased spells.

OpenBfme2's `PlayerRva002AD826.cpp` shows the purchase path: obtain the cost,
call virtual slot 2 on the member at Player+8 with the NEGATIVE cost,
then add the Science. The store provides definitions and costs; point accounting
belongs to the Player member.

The BFME2 experience cascade in `ExperienceTrackerXfer.cpp`, RVA 0x0039AC23,
starts at the current level key and works forwards. The setter in
`ExperienceTrackerSetExperience.cpp`, RVA 0x0039B3D1, sets XP and calls
that same cascade. A lower XP value therefore does not automatically produce
a lower level.

`ExperienceTrackerRva0039B4EC.cpp` contains two other important paths.
The level-gain loop at RVA 0x0039B4EC rejects counts <= 0, so negative
level counts do not cause demotion. The routine at RVA 0x0039B438 instead
finds a level by name and applies it through RVA 0x0039B24F. The latter
calls the virtual level-application slot and sets XP to RequiredExperience.
This is a useful starting point for targeted demotion, but it does not prove
that previous upgrades or other level effects are removed.

Source caveat: `OpenBfme/.../ExperienceTracker.cpp` also contains
`present-unmatched` Generals code with four veterancy levels and a complete
recalculation from level zero. Do NOT use that code as evidence for BFME/RotWK
demotion. The native BFME2/RotWK cascade works differently. Likewise, comment
names and private class views in these RE repositories do not, by themselves,
establish a field's actual meaning.

## Entry points checked directly in RotWK

| VA | Function / structural meaning | Relevance |
|---|---|---|
| 0x006AA980 | Point-delta wrapper on Player+8; ret 4 | Negative deltas, statistics only for positive values, UI refresh on change |
| 0x00782764 | Purchase-point core; ret 4 | add [this+0x1C], delta; a negative result becomes zero |
| 0x006AA9C2 | Rank-change wrapper on Player+8; ret 4 | Notifications/EVA around the rank change |
| 0x00782865 | Rank-change core; ret 4 | Detects a lower target rank and calls virtual reset slot +0x0C |
| 0x006AEE11 | Player rank reset on Player+8 | Calls 0x00782774 and then 0x006AED4B on Player |
| 0x00782774 | Base rank reset | Sets rank to 1 and XP to 0; reconstructs starting purchase points |
| 0x006AED4B | Rebuild Sciences on Player | Processes Player+0x310, template Sciences, and rank Sciences; further call 0x006AD142 needs investigation |
| 0x00782AA4 | Add player SkillPoints; ret 8 | Float delta, multipliers, cap guard, promotion only |
| 0x0079D833 | Unit XP wrapper; ret 0x14 | ExperienceSink at +0x38, object tracker at Object+0x26C, multipliers |
| 0x0079D68D | Unit XP core; ret 0x18 | Checks Trainable/max level, adds float, calls cascade |
| 0x0079D8EF | Set absolute unit XP; ret 8 | Float value plus feedback; sink-aware; uses the same promotion cascade |
| 0x0079D141 | Unit level cascade; ret 4 | Truncates XP, checks subsequent entries, calls virtual slot +0x10 |
| 0x0079D956 | Apply unit level by name; ret 8 | Named-level lookup; calls 0x0079D76D |
| 0x0079D76D | Apply level record; ret 0x0C | Virtual slot +0x10; XP = RequiredExperience; updates rank/auxiliary state |
| 0x0068931C | Find the tracker's ExperienceLevel list | Unit-specific level chain |
| 0x00689E3C | Query level chain using the current level key | Forward-cascade path |
| 0x00DE4704 | TheExperienceLevelSystem, global pointer | Entry point for store/list lookup |
| 0x00DE3B2C | RankInfoStore, global pointer | Player rank thresholds |
| 0x005FF99F / 0x005FFA44 | RankInfo lookup / side-specific SkillPoints threshold | Derive player rank from XP |

Verified relative fields:

- Unit tracker: +0x0C level key, +0x10 XP FLOAT,
  +0x24 current rank, +0x28 maximum rank, +0x2C auxiliary object,
  +0x38 ExperienceSink. Here +0x04 is template-related information;
  do not use it as an Object pointer without checking.
- Player+8 member: +0x0C SkillPoints FLOAT, +0x14 rank INT,
  +0x1C purchase points INT, +0x20 next promotion threshold INT.
  Relative to Player itself: XP +0x14, rank +0x1C,
  purchase points +0x24, next threshold +0x28.
- ExperienceLevel: +0x18 RequiredExperience, +0xFC rank.
- RotWK RankInfo: +0x38 granted purchase points. BFME2 uses +0x34 instead.

The directly observed player XP at Player+0x14 contradicts the provisional
Player+0x20 derivation in [`live-object-model.md`](live-object-model.md) and
[`sage_live/backends/memory.py`](../../sage_live/backends/memory.py). Neither existing file was changed.
Use the native float access as the starting point for a patch and additionally
validate the offset in game.

## Recommended patch

Initially provide explicit operations, for example (draft names):
`RemoveSciencePurchasePoints`, `RemoveExperiencePoints`, `RemoveExperienceLevels`.
Globally enabling existing negative INI values would affect several different
filters, scaling rules, and cap checks.

1. **Purchase points:** use the existing wrapper at 0x006AA980 on Player+8 with -N.
   For a cost condition, first check that the balance is sufficient;
   for a drain, the existing zero floor is appropriate.
   No additional rank change or Science redistribution.
2. **XP without level loss:** new XP = max(0, old XP - amount). For units,
   use the existing absolute setter after identifying the actual sink recipient.
   For player XP, provide a dedicated setter/drain so the cap and multipliers
   cannot unexpectedly block or alter the subtraction.
   The current level is retained. Later gains must recover the lost XP before
   reaching the next promotion threshold.
3. **Unit level loss:** determine the target level from the actual applicable
   level chain instead of subtracting a fixed XP constant. An exact level drain
   needs a rule for whether progress within the old level is discarded or
   transferred proportionally. For XP-based demotion, select the highest valid
   level whose RequiredExperience <= new XP.
4. **Apply the level change:** first trace the actual virtual handler
   `[tracker-vtable+0x10]`. 0x0079D76D is the existing application path,
   but overwrites XP with the target threshold. For XP-based demotion,
   restore the desired XP value afterwards.
   This is useful only if the handler consistently supports lower levels;
   otherwise a separate reversible level-change routine is required.
5. **Player rank loss:** do not use the existing reset-and-rebuild path
   as a simple rank subtraction. It resets XP/purchase points and performs
   the Science rebuild. A targeted patch needs a rule for whether spent points
   and purchased Sciences are retained, lost, or treated as debt against
   later gains.

The simplest first version combines a purchase-point drain with an XP drain
that retains the level. Actual unit demotion would be a second phase.

## Further investigation required in game.dat

- **Virtual unit level handler +0x10:** new/old level names and
  rank values, AttributeModifier, Upgrades/RemoveUpgrade, ModelConditionState,
  SubObjects, current and maximum health, weapons, and level FX.
  A new level record alone does not guarantee reversal of permanently granted
  upgrades, unlocked powers, or objects that have already been created.
- **Named-level setter 0x0079D956 and its callers:** identify script actions for
  UNIT/TEAM_SET_EXPERIENCE_POINTS and TEAM_GIVE_EXPERIENCE_LEVEL;
  find action entries by name rather than borrowing BFME1 enum values.
- **Cap guards 0x0079D6A8 and 0x00782AC3:** when using a delta-based approach,
  bypass them for negative values while continuing to limit positive gains.
  The absolute unit setter does not contain this max-level guard.
- **Point-purchase callers:** trace the Spellstore purchase to virtual slot +8
  of the Player+8 member; confirm negative costs and 0x006AA980.
- **Science rebuild 0x006AED4B / 0x006AD142:** determine its exact removal effects,
  special-power/Spellbook refresh, and consequences for acquired Sciences.
- **Sink, hordes, and revival:** decide whether experience belongs to the horde,
  a member, or a sponsor; check retained XP and levels after death/revival.

Minimum game test: subtraction within a level; across one and several
thresholds; exactly at a threshold; more subtraction than the balance;
unit/player at the cap; horde with members; hero with level upgrades;
death/revival; save/load; subsequent level gain. Run any later multiplayer
patch on the synchronized simulation side; the Spellstore UI alone is not
a suitable place for the actual state change.
