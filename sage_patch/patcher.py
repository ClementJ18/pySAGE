"""The patch framework: a `Patch` mutates an in-memory `game.dat` image, and `apply_patches` runs a
sequence of them over a copy and writes the result.

Every patch checks the original bytes before it writes, so a list either applies in full or raises
before anything reaches disk.
"""

from __future__ import annotations

import inspect
import logging
import struct
from collections.abc import Iterable
from pathlib import Path
from typing import TYPE_CHECKING

from sage_ini.engine import STOCK, Engine

__all__ = [
    "apply_patches",
    "EXPERIMENTAL_WARNING",
    "log",
    "Patch",
]

if TYPE_CHECKING:
    import argparse

log = logging.getLogger("sage_patch")

#: What `Patch.experimental` means, in one sentence, shared by everything that says it so the
#: CLI and the log cannot drift into two different promises.
EXPERIMENTAL_WARNING = (
    "unstable and largely untested - it applies and verifies, but it has not been established in "
    "play. Expect crashes, desyncs and save/replay incompatibility, and keep the unpatched binary."
)


class Patch:
    """One binary modification of a `game.dat` image.

    Subclasses set `name`, `description` and `author` and implement `apply`. Register the patch in
    `sage_patch.registry` to reach it from the CLI. Optional overrides: `add_cli_arguments` /
    `from_cli_args` for parameters, `verify` to make the result checkable, `detect` to recognise it
    (with its parameters) in someone else's binary, and `ini_surface` to declare the INI it adds.

    Patches compose in any order and subset as long as each new one keeps three rules:

    1. **Allocate caves with `sage_patch.utils.allocate_section`**, never at a fixed RVA, and have
       `verify` find the cave with `find_section`. Appending never moves an existing section.
    2. **Do not edit bytes another patch edits.** Not enforced, but `apply_byte_patch` checks the
       original bytes, so the second patch to reach a site raises.
    3. **Do not derive output from bytes another patch rewrites.** The framework cannot catch this;
       if a patch must, say so in its docstring and treat the pair as ordered.
    """

    name: str = ""

    #: One line: what the patch does and what a mod has to write to use it (INI keywords, tokens,
    #: string keys, `.apt` clips - or that it needs none). Shown by `list`, `apply --help` and the
    #: README table. No trailing full stop.
    description: str = ""
    #: Who did the reverse engineering, for the credit line `apply_patches` prints. Empty by
    #: default so a new patch must state its own rather than inherit someone's name.
    author: str = ""

    #: Whether the patch is experimental (see `EXPERIMENTAL_WARNING`). Must agree with living in
    #: `sage_patch.patches.experimental`; a test checks both directions.
    experimental: bool = False
    #: Whether the patch has been observed working in a running game: `"yes"`, `"partly"` (some of
    #: it has), or `""` (not yet). The patch's write-up has the details.
    runtime_verified: str = ""

    @property
    def credit(self) -> str:
        """This patch and who to credit for it, as one line: `name (by author)`. Separate from
        `__str__`, which callers use as an identifier.
        """
        return f"{self} (by {self.author})" if self.author else f"{self} (author unrecorded)"

    def apply(self, data: bytearray) -> None:
        """Mutate `data` in place. Raise (typically `ValueError`) if the image is not the
        expected build or a patch site does not match."""
        raise NotImplementedError

    def verify(self, data: bytes | bytearray) -> list[str]:
        """Return the structural problems that mean `data` does not carry this patch (an empty
        list == verified). Default: nothing checkable. Overrides should not disassemble, so that
        verification stays dependency-light."""
        return []

    @classmethod
    def detect(cls, data: bytes | bytearray) -> Patch | None:
        """The instance of this patch that `data` carries, or None.

        The default probes with the patch's defaults through `verify`, so **a patch with parameters
        must override this** and recover them from the image. Never raises: failing on an unfamiliar
        build means "not this patch".
        """
        try:
            patch = cls()
            problems = patch.verify(data)
        except (ValueError, KeyError, IndexError, TypeError, struct.error):
            return None
        return None if problems else patch

    def options(self) -> dict[str, object]:
        """The parameters this instance was built with, as constructor keyword arguments: `{"count":
        64}` for `commandset-limit` at 64, `{}` for a patch with none.

        `sagepatch` records these in the `.sagepatch` manifest and `rebuild` passes them back. The
        default reads each constructor parameter off the attribute of the same name, skipping None;
        a patch that stores its parameters differently overrides this.
        """
        found: dict[str, object] = {}
        for name, parameter in inspect.signature(type(self).__init__).parameters.items():
            variadic = (parameter.VAR_POSITIONAL, parameter.VAR_KEYWORD)
            if name == "self" or parameter.kind in variadic:
                continue
            value = getattr(self, name, None)
            if value is None:
                continue
            found[name] = tuple(value) if isinstance(value, list | tuple) else value
        return found

    def ini_surface(self) -> Engine:
        """What this patch changes about the INI the engine accepts, as a `sage_ini.engine.Engine`
        (fields, name-table tokens, raised limits, retired fields). Default: nothing.

        Read by `sage-patch sagepatch` to write the `.sagepatch` that teaches `sage_ini` and
        `sage_lint` about the patched engine. Describes this instance, so parameters are reflected.
        """
        return STOCK

    @classmethod
    def add_cli_arguments(cls, parser: argparse.ArgumentParser) -> None:
        """Register this patch's parameters as CLI options on `parser`. Default: none."""

    @classmethod
    def from_cli_args(cls, args: argparse.Namespace) -> Patch:
        """Build an instance from parsed CLI `args`. Default: the no-argument constructor."""
        return cls()

    def __str__(self) -> str:
        return self.name or type(self).__name__


def apply_patches(
    game_dat: str | Path,
    patches: Iterable[Patch],
    output: str | Path | None = None,
) -> Path:
    """Apply `patches`, in order, to a copy of `game_dat` and write the result.

    `output` defaults to `game_dat` itself (overwriting it); pass a path to keep the original.
    Returns the path written. Raises before writing anything if any patch fails.
    """
    src = Path(game_dat)
    data = bytearray(src.read_bytes())
    orig_len = len(data)

    patches = list(patches)
    for patch in patches:
        # Warn *before* the applying line, not after and not in a summary at the end, because a
        # patch that raises halfway has still been warned about - and because the last thing on
        # screen when this succeeds should be "wrote ...", not a caveat scrolled off the top.
        if patch.experimental:
            log.warning("WARNING: %s is %s", patch, EXPERIMENTAL_WARNING)
        # The author goes in the applying line rather than in a summary at the end, so that a run
        # that fails halfway has still named everyone whose work went into the bytes it wrote.
        log.info("applying patch: %s", patch.credit)
        patch.apply(data)

    dest = Path(output) if output is not None else src
    dest.write_bytes(data)
    log.info("wrote %s  (%d -> %d bytes, %d patch(es))", dest, orig_len, len(data), len(patches))
    return dest
