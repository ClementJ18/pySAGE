"""The patch framework: a :class:`Patch` mutates an in-memory `game.dat` image, and
:func:`apply_patches` runs a sequence of them over a copy and writes the result.

A concrete patch subclasses :class:`Patch` and implements :meth:`Patch.apply`, mutating the
``bytearray`` in place and raising on any verification failure (e.g. unexpected original bytes).
Because every patch verifies before it writes, an ordered list either applies cleanly in full or
raises without leaving a half-patched file on disk (the buffer is only written out once all
patches succeed)."""

from __future__ import annotations

import inspect
import logging
import struct
from collections.abc import Iterable
from pathlib import Path
from typing import TYPE_CHECKING

from sage_ini.engine import STOCK, Engine

if TYPE_CHECKING:
    import argparse

log = logging.getLogger("sage_patch")

#: What :attr:`Patch.experimental` means, in one sentence, shared by everything that says it so the
#: CLI and the log cannot drift into two different promises.
EXPERIMENTAL_WARNING = (
    "unstable and largely untested - it applies and verifies, but it has not been established in "
    "play. Expect crashes, desyncs and save/replay incompatibility, and keep the unpatched binary."
)


class Patch:
    """One binary modification of a `game.dat` image.

    Subclasses set :attr:`name`/:attr:`description` and implement :meth:`apply`. To be reachable
    from the ``sage-patch`` CLI, a patch is registered in :mod:`sage_patch.registry`; it may
    override :meth:`add_cli_arguments`/:meth:`from_cli_args` to accept parameters,
    :meth:`verify` to make its result independently checkable, :meth:`detect` to be recognised
    (with its parameters) in a binary someone else patched, and :meth:`ini_surface` to say what
    it changes about the INI the engine accepts.

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

    #: What the patch does and **what a mod has to write to use it**, as one unbroken line -
    #: `sage-patch list` prints it in a table and `apply <name> --help` puts it at the top, and
    #: both are read by somebody deciding whether to apply this. So the description names the
    #: concrete surface: the INI keywords and enum tokens it adds, the `.str`/`.csf` keys a new
    #: tooltip line stays silent without, the `.apt` clips a widened UI needs, the map data that
    #: opts in - and, where a patch needs none of that, says so, because "is there something I
    #: am supposed to declare" is the same question either way.
    #:
    #: No trailing full stop: `apply <name> --help` appends one for an experimental patch.
    description: str = ""
    #: Who worked out this patch, for the credit line :func:`apply_patches` prints. A patch is
    #: somebody's reverse engineering before it is anybody's code - the addresses, the call
    #: convention and the reason the original bytes are what they are - and that work is invisible
    #: in the diff once the assembly is written down. Naming the author here is how a mod that
    #: ships the patched binary can say whose it was; see the README's "Credit" section.
    #:
    #: **Empty by default, deliberately.** A default naming a person attributes every future
    #: patch to them silently, which is exactly the failure this attribute exists to prevent, so
    #: an unattributed patch says so and a new one has to state its own.
    author: str = ""

    #: Whether this patch is **experimental**, in the sense of :data:`EXPERIMENTAL_WARNING`: the
    #: assembly is written and the binary comes out verifying, but the result has not been
    #: established in a real game - so what the patch does past "the file still loads" is a claim
    #: rather than an observation.
    #:
    #: This is not a quality grade and it is not about the RE being shakier. It marks the patches
    #: that live in :mod:`sage_patch.patches.experimental`, and the two must agree: the module a
    #: patch lives in is how a reader finds out, and this attribute is how ``apply`` says it out
    #: loud to somebody who never opens the source. ``TestExperimentalPatchesAreDeclared`` fails
    #: when they disagree in either direction.
    #:
    #: **False by default**, deliberately, for the mirror of the reason :attr:`author` is empty by
    #: default: defaulting to True would put a warning in front of settled patches until each one
    #: opted out, and a warning everything prints is a warning nobody reads.
    experimental: bool = False

    @property
    def credit(self) -> str:
        """This patch and who to credit for it, as one line - `name (by author)`.

        Kept apart from :meth:`__str__`, which several callers use as an identifier: `verify`
        prints it into an OK/FAIL line and `sagepatch` lists it as what was found in a binary,
        and neither is asking who wrote it.
        """
        return f"{self} (by {self.author})" if self.author else f"{self} (author unrecorded)"

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
    def detect(cls, data: bytes | bytearray) -> Patch | None:
        """The instance of this patch that ``data`` carries, or None if it does not carry one.

        The default probes with the patch's own defaults and asks :meth:`verify`. **A patch with
        parameters must override this** and recover them from the image: `verify` only answers
        "does this file carry *this* configuration", so a default-built probe reports a patch
        applied with any other parameters as absent.

        Never raises. A `verify` (or a constructor) that trips over an unrecognised build is
        answering "not this patch", which is exactly what a detection sweep over an arbitrary
        `game.dat` needs."""
        try:
            patch = cls()
            problems = patch.verify(data)
        except (ValueError, KeyError, IndexError, TypeError, struct.error):
            return None
        return None if problems else patch

    def options(self) -> dict[str, object]:
        """The parameters this instance was built with, as the keyword arguments that rebuild it
        - `{"count": 64}` for a `commandset-limit` at 64, `{}` for a patch that takes none.

        This is what makes a detected patch writable down and replayable: `sagepatch` records it
        in the `.sagepatch` manifest and `rebuild` passes it straight back to the constructor, so
        a build reproduces at the counts and keywords it was actually made with rather than at
        this version's defaults.

        The default reads the constructor's own named parameters off the instance, which is the
        convention every bundled patch already follows (`__init__(self, count=64)` storing
        `self.count`). A patch that keeps its parameters under other names overrides this; a
        parameter with no matching attribute is skipped, and so is one that is None, which is how
        an optional parameter says "left at the default" in a format that has no null.
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
        """What this patch changes about the **INI** the engine accepts, as an
        :class:`~sage_ini.engine.Engine`: fields it adds to a block, tokens it adds to a name
        table, ceilings it raises, fields it retires. Default: nothing.

        Declared here, beside the assembly that implements it, so the two cannot drift - and read
        by ``sage-patch sagepatch`` to write the `.sagepatch` that teaches `sage_ini` and
        `sage_lint` about this engine. It describes *this instance*, so a parameterized patch
        reports the names and counts it was actually built with."""
        return STOCK

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
