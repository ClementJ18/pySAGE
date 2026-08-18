"""Binary-patching framework for the ROTWK SAGE engine (`game.dat`).

`apply_patches(game_dat, [patches...], output)` runs an ordered list of :class:`Patch` over a
copy of the binary and writes the result. Every patch exported here is engine-level: it applies
to any ROTWK `game.dat` of the target build and benefits every mod built on it (Edain among
them), not one mod in particular.

What each patch does is on the patch itself - `Patch.description` for the one-liner `sage-patch
list` prints, the module docstring in `sage_patch.patches` for why it is built the way it is, and
`docs/<patch>.md` for the reverse engineering behind it. Nothing here restates them, because a
list in this file is a list that drifts.

**Some of what this module exports is experimental** - unstable and largely untested, see
:data:`~sage_patch.patcher.EXPERIMENTAL_WARNING` and :mod:`sage_patch.patches.experimental`. The
names are flat here, so the import that reaches one reads exactly like the import that reaches a
settled patch; :attr:`Patch.experimental` is the thing to ask, and `apply_patches` logs a warning
per experimental patch it is handed. That warning is a `WARNING` rather than a print precisely so
that it reaches a caller who never configured logging - Python's last-resort handler puts it on
stderr with no setup at all.

    from sage_patch import AiReviveGatePatch, apply_patches, CommandSetLimitPatch
    apply_patches(
        "game.dat.backup",
        [CommandSetLimitPatch(count=64), AiReviveGatePatch()],
        output="game.dat",
    )
"""

from sage_patch.patcher import EXPERIMENTAL_WARNING, Patch, apply_patches
from sage_patch.patches import (
    AiReviveGatePatch,
    BannerFilterPatch,
    CahFactionsPatch,
    CommandPointUpkeepPatch,
    CommandSetLimitPatch,
    FoundationRebindPatch,
    HeadlessPatch,
    HeroBarSlotsPatch,
    HeroManaPatch,
    HordeOrphanTargetPatch,
    InflationReadoutPatch,
    LargeGroupBonusFilterPatch,
    LifetimeExtendUpgradePatch,
    MultiExecuteGatePatch,
    PlayerHealFilterPatch,
    ProductionConditionPatch,
    ProductionSplitPatch,
    QueueIgnoreCpPatch,
    ReplayOutcomePatch,
    SciencePrereqPatch,
    SecondResourcePatch,
    SkirmishReplayPatch,
    SpawnUnionPatch,
    TerrainResourceExpPatch,
    TriggerRechargeListPatch,
    UniqueProductionIdPatch,
    UpgradeDescriptionPatch,
    UpgradeGrantListsPatch,
)
from sage_patch.sagepatch import generate

__all__ = [
    "EXPERIMENTAL_WARNING",
    "AiReviveGatePatch",
    "BannerFilterPatch",
    "CahFactionsPatch",
    "CommandPointUpkeepPatch",
    "CommandSetLimitPatch",
    "FoundationRebindPatch",
    "HeadlessPatch",
    "HeroBarSlotsPatch",
    "HeroManaPatch",
    "HordeOrphanTargetPatch",
    "InflationReadoutPatch",
    "LargeGroupBonusFilterPatch",
    "LifetimeExtendUpgradePatch",
    "MultiExecuteGatePatch",
    "Patch",
    "PlayerHealFilterPatch",
    "ProductionConditionPatch",
    "ProductionSplitPatch",
    "QueueIgnoreCpPatch",
    "ReplayOutcomePatch",
    "SciencePrereqPatch",
    "SecondResourcePatch",
    "SkirmishReplayPatch",
    "SpawnUnionPatch",
    "TerrainResourceExpPatch",
    "TriggerRechargeListPatch",
    "UniqueProductionIdPatch",
    "UpgradeDescriptionPatch",
    "UpgradeGrantListsPatch",
    "apply_patches",
    "generate",
]
