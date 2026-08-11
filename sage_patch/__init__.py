"""Binary-patching framework for the ROTWK SAGE engine (`game.dat`).

`apply_patches(game_dat, [patches...], output)` runs an ordered list of :class:`Patch` over a
copy of the binary and writes the result. Every patch exported here is engine-level: it applies
to any ROTWK `game.dat` of the target build and benefits every mod built on it (Edain among
them), not one mod in particular.

What each patch does is on the patch itself - `Patch.description` for the one-liner `sage-patch
list` prints, the module docstring in `sage_patch.patches` for why it is built the way it is, and
`docs/<patch>.md` for the reverse engineering behind it. Nothing here restates them, because a
list in this file is a list that drifts.

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
    FoundationRebindPatch,
    HeroBarSlotsPatch,
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
    "FoundationRebindPatch",
    "HeroBarSlotsPatch",
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
