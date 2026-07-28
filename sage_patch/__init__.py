"""Binary-patching framework for the ROTWK SAGE engine (`game.dat`).

`apply_patches(game_dat, [patches...], output)` runs an ordered list of :class:`Patch` over a
copy of the binary and writes the result. Both bundled patches are engine-level: they apply to
any ROTWK `game.dat` of the target build and benefit every mod built on it (Edain among them),
not one mod in particular.

* :class:`CommandSetLimitPatch` raises the `CommandSet` button limit from the stock 33 to any N
  in 34..127.
* :class:`CahFactionsPatch` adds mod sides and an `All` token to the nine-name Create-A-Hero
  faction enum, so a `SubClass` can name them in `UsableFactions`.

    from sage_patch import apply_patches, CahFactionsPatch, CommandSetLimitPatch
    apply_patches(
        "game.dat.backup",
        [CommandSetLimitPatch(count=64), CahFactionsPatch(sides=["Rohan", "Lothlorien"])],
        output="game.dat",
    )
"""

from sage_patch.patcher import Patch, apply_patches
from sage_patch.patches import CahFactionsPatch, CommandSetLimitPatch

__all__ = ["Patch", "apply_patches", "CahFactionsPatch", "CommandSetLimitPatch"]
