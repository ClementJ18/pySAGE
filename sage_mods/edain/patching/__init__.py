"""Binary-patching framework for ROTWK/Edain `game.dat`.

`apply_patches(game_dat, [patches...], output)` runs an ordered list of :class:`Patch` over a
copy of the binary and writes the result. The bundled patch is :class:`CommandSetLimitPatch`,
which raises the `CommandSet` button limit from the stock 33 to any N in 34..127.

    from sage_mods.edain.patching import apply_patches, CommandSetLimitPatch
    apply_patches("game.dat.backup", [CommandSetLimitPatch(count=64)], output="game.dat")
"""

from sage_mods.edain.patching.patcher import Patch, apply_patches
from sage_mods.edain.patching.patches import CommandSetLimitPatch

__all__ = ["Patch", "apply_patches", "CommandSetLimitPatch"]
