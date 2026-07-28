"""The patch framework: a :class:`Patch` mutates an in-memory `game.dat` image, and
:func:`apply_patches` runs a sequence of them over a copy and writes the result.

A concrete patch subclasses :class:`Patch` and implements :meth:`Patch.apply`, mutating the
``bytearray`` in place and raising on any verification failure (e.g. unexpected original bytes).
Because every patch verifies before it writes, an ordered list either applies cleanly in full or
raises without leaving a half-patched file on disk (the buffer is only written out once all
patches succeed)."""

from __future__ import annotations

import logging
from collections.abc import Iterable
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import argparse

log = logging.getLogger("sage_patch")


class Patch:
    """One binary modification of a `game.dat` image.

    Subclasses set :attr:`name`/:attr:`description` and implement :meth:`apply`. To be reachable
    from the ``sage-patch`` CLI, a patch is registered in :mod:`sage_patch.registry`; it may
    override :meth:`add_cli_arguments`/:meth:`from_cli_args` to accept parameters and
    :meth:`verify` to make its result independently checkable.

    Composing patches
    -----------------
    The bundled patches are order-independent: any subset applies in any order. A new patch keeps
    that property by observing three rules, in decreasing order of how mechanically they hold.

    1. **Allocate caves with** :func:`~sage_patch.utils.allocate_section`, never at a fixed RVA,
       and have :meth:`verify` locate the cave with :func:`~sage_patch.utils.find_section` rather
       than recomputing where it "should" be. Appending past the highest existing section keeps
       the section table sorted by RVA no matter what else has been added; a hardcoded RVA
       composes only when its patch happens to be applied first. Appending never moves an existing
       section, so file offsets stay stable for everyone.
    2. **Do not edit bytes another patch edits.** This is not enforced, but it does fail loudly:
       :func:`~sage_patch.utils.apply_byte_patch` asserts the original bytes before writing, so
       the second patch to reach a shared site raises instead of silently corrupting it.
    3. **Do not derive your output from bytes another patch rewrites.** This is the one the
       framework cannot catch — both orders would "succeed" and disagree. If a patch must read a
       structure another patch rebuilds, say so in its docstring and treat the pair as ordered."""

    name: str = ""
    description: str = ""

    def apply(self, data: bytearray) -> None:
        """Mutate ``data`` in place. Raise (typically ``ValueError``) if the image is not the
        expected build or a patch site does not match."""
        raise NotImplementedError

    def verify(self, data: bytes | bytearray) -> list[str]:
        """Return the structural problems that mean ``data`` does not carry this patch (an empty
        list == verified). Default: nothing checkable. Overrides should not disassemble, so that
        verification stays dependency-light."""
        return []

    @classmethod
    def add_cli_arguments(cls, parser: argparse.ArgumentParser) -> None:
        """Register this patch's parameters as CLI options on ``parser``. Default: none."""

    @classmethod
    def from_cli_args(cls, args: argparse.Namespace) -> Patch:
        """Build an instance from parsed CLI ``args``. Default: the no-argument constructor."""
        return cls()

    def __str__(self) -> str:
        return self.name or type(self).__name__


def apply_patches(
    game_dat: str | Path,
    patches: Iterable[Patch],
    output: str | Path | None = None,
) -> Path:
    """Apply ``patches`` (in order) to a copy of ``game_dat`` and write the result.

    Parameters
    ----------
    game_dat:
        Path to the input binary. It is read but never modified.
    patches:
        The :class:`Patch` instances to apply, in order.
    output:
        Where to write the patched binary. Defaults to ``game_dat`` (in-place overwrite);
        pass an explicit path to keep the original.

    Returns the path written. Raises before writing anything if any patch fails to verify.
    """
    src = Path(game_dat)
    data = bytearray(src.read_bytes())
    orig_len = len(data)

    patches = list(patches)
    for patch in patches:
        log.info("applying patch: %s", patch)
        patch.apply(data)

    dest = Path(output) if output is not None else src
    dest.write_bytes(data)
    log.info("wrote %s  (%d -> %d bytes, %d patch(es))", dest, orig_len, len(data), len(patches))
    return dest
