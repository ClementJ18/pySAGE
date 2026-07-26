"""Binary-patching framework for the ROTWK SAGE engine (`game.dat`).

`apply_patches(game_dat, [patches...], output)` runs an ordered list of :class:`Patch` over a
copy of the binary and writes the result. The bundled patch is :class:`CommandSetLimitPatch`,
which raises the `CommandSet` button limit from the stock 33 to any N in 34..127. The patch is
engine-level: it applies to any ROTWK `game.dat` of the target build and benefits every mod
built on it (Edain among them), not one mod in particular.

    from sage_patch import apply_patches, CommandSetLimitPatch
    apply_patches("game.dat.backup", [CommandSetLimitPatch(count=64)], output="game.dat")
"""

from sage_patch.patcher import Patch, apply_patches
from sage_patch.patches import CommandSetLimitPatch

__all__ = ["Patch", "apply_patches", "CommandSetLimitPatch"]
