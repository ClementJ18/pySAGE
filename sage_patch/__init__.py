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
* :class:`UniqueProductionIdPatch` mints production ids game-wide instead of per building, so
  recruiting a hero from a second building no longer takes the money and starts nothing.
* :class:`ReplayOutcomePatch` writes every player's final victory/defeat state into the replay
  at the frame the recording ends, which the stock input-only stream never records.
* :class:`SkirmishReplayPatch` records single-player skirmish games, which the stock recorder
  refuses, and names each recording by timestamp and map instead of overwriting `Last Replay`.

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
    CahFactionsPatch,
    CommandSetLimitPatch,
    ProductionConditionPatch,
    ReplayOutcomePatch,
    SkirmishReplayPatch,
    UniqueProductionIdPatch,
)

__all__ = [
    "AiReviveGatePatch",
    "CahFactionsPatch",
    "CommandSetLimitPatch",
    "Patch",
    "ProductionConditionPatch",
    "ReplayOutcomePatch",
    "SkirmishReplayPatch",
    "UniqueProductionIdPatch",
    "apply_patches",
]
