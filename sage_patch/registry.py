"""Registry of installable patches, keyed by :attr:`Patch.name`, that the ``sage-patch`` CLI
lists, applies and verifies. Add a patch here to expose it on the command line."""

from sage_patch.patcher import Patch
from sage_patch.patches.commandset import CommandSetLimitPatch

PATCHES: dict[str, type[Patch]] = {
    CommandSetLimitPatch.name: CommandSetLimitPatch,
}

__all__ = ["PATCHES"]
