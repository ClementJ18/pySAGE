"""Binary-patching framework for the ROTWK SAGE engine (`game.dat`).

`apply_patches(game_dat, [patches...], output)` runs an ordered list of :class:`Patch` over a
copy of the binary and writes the result. Every patch exported here is engine-level: it applies
to any ROTWK `game.dat` of the target build and benefits every mod built on it (Edain among
them), not one mod in particular.

* :class:`CommandSetLimitPatch` raises the `CommandSet` button limit from the stock 33 to any N
  in 34..127, and widens the AI's set-walk to match.
* :class:`CahFactionsPatch` adds mod sides and an `All` token to the nine-name Create-A-Hero
  faction enum, so a `SubClass` can name them in `UsableFactions`.
* :class:`AiReviveGatePatch` makes the AI evaluate a REVIVE command button's `NeededUpgrade`
  before recruiting or reviving through it, as the player's control bar already does.
* :class:`ProductionConditionPatch` adds a model condition that is active while a building's
  production queue is non-empty - training a unit or researching an upgrade.
* :class:`HeroManaPatch` gives special powers a regenerating per-object mana cost, which the
  stock `UnitCost` field cannot do for a hero - it is skipped outright on an object with no
  horde, so it costs a lone hero nothing at all.
* :class:`CommandPointUpkeepPatch` scales a faction's tick income down as its command-point
  usage crosses thresholds declared in `playertemplate.ini`, and shows the current loss
  beside the palantir's command-point numbers.
* :class:`UniqueProductionIdPatch` mints production ids game-wide instead of per building, so
  recruiting a hero from a second building no longer takes the money and starts nothing.
* :class:`ReplayOutcomePatch` writes every player's final victory/defeat state into the replay
  at the frame the recording ends, which the stock input-only stream never records.
* :class:`SecondResourcePatch` gives every player a second resource pool, granted per tick by
  `AutoDepositUpdate.DepositAmount2`, seeded per faction by `PlayerTemplate.StartMoney2`, shown
  in brackets after the palantir's own number, and spent through `Object.BuildCost2`.
* :class:`SkirmishReplayPatch` records single-player skirmish games, which the stock recorder
  refuses, and names each recording by timestamp and map instead of overwriting `Last Replay`.
* :class:`TerrainResourceExpPatch` adds a `GiveNoXP` boolean to `TerrainResourceBehavior` -
  the field `AutoDepositUpdate` already has - so a resource spot can pay its owner without
  levelling its own building.
* :class:`SciencePrereqPatch` lets `PrerequisiteSciences` name a science defined later in the
  file, so a mutually dependent pair no longer has to be closed from `map.ini` - and, by
  default, still reports any name that is missing once every science file has been read.
* :class:`MultiExecuteGatePatch` makes an `OK_FOR_MULTI_EXECUTE` button respect each selected
  unit's own `EnableOnModelCondition` / `DisableOnModelCondition`, instead of running the
  ability on the whole group as soon as one member qualifies.
* :class:`QueueIgnoreCpPatch` adds a `QueueIgnoreCP` boolean to `CommandButton`, so a button the
  engine presses on an object's behalf (a `DoCommandUpgrade`, say) can queue its unit while the
  player is at the command-point cap - the stock queue then holds it until the points free up.
* :class:`BannerFilterPatch` adds an `ObjectFilter` keyword to `BannerCarrierUpdate`, limiting
  which nearby hordes a banner carrier replenishes - by kind, template, or (unlike the engine's
  own ally-wide partition scan) to the banner owner's own hordes via `SAME_PLAYER`.
* :class:`SpawnUnionPatch` makes an object with several `SpawnBehavior`s use all of their spawns
  rather than the first module's alone - which is what a `SPAWNS_ARE_THE_WEAPONS` structure
  attacks with, and also what gets told that a slave died.

    from sage_patch import AiReviveGatePatch, apply_patches, CommandSetLimitPatch
    apply_patches(
        "game.dat.backup",
        [CommandSetLimitPatch(count=64), AiReviveGatePatch()],
        output="game.dat",
    )
"""

from sage_patch.patcher import Patch, apply_patches
from sage_patch.patches import (
    AiReviveGatePatch,
    BannerFilterPatch,
    CahFactionsPatch,
    CommandPointUpkeepPatch,
    CommandSetLimitPatch,
    HeroManaPatch,
    HordeOrphanTargetPatch,
    InflationReadoutPatch,
    MultiExecuteGatePatch,
    ProductionConditionPatch,
    QueueIgnoreCpPatch,
    ReplayOutcomePatch,
    SciencePrereqPatch,
    SecondResourcePatch,
    SkirmishReplayPatch,
    SpawnUnionPatch,
    TerrainResourceExpPatch,
    UniqueProductionIdPatch,
)
from sage_patch.sagepatch import generate

__all__ = [
    "AiReviveGatePatch",
    "BannerFilterPatch",
    "CahFactionsPatch",
    "CommandPointUpkeepPatch",
    "CommandSetLimitPatch",
    "HeroManaPatch",
    "HordeOrphanTargetPatch",
    "InflationReadoutPatch",
    "MultiExecuteGatePatch",
    "Patch",
    "ProductionConditionPatch",
    "QueueIgnoreCpPatch",
    "ReplayOutcomePatch",
    "SciencePrereqPatch",
    "SecondResourcePatch",
    "SkirmishReplayPatch",
    "SpawnUnionPatch",
    "TerrainResourceExpPatch",
    "UniqueProductionIdPatch",
    "apply_patches",
    "generate",
]
