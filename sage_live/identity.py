"""Which build is actually running - measured from the mapped image, never assumed.

Every address in `EngineLayout` is specific to one `game.dat`. Point those offsets at a
different build and nothing announces the mistake: the reads succeed, the pointers look
plausible, and the observation comes back full of confident nonsense. That is the worst
failure mode this package has, because a wrong number is much harder to notice than an
exception.

So the handshake is a **gate, not a greeting** - the rule `sage_patch` already applies when it
asserts expected bytes before writing. Before a session reads anything, the running image is
identified and refused if it is not the build the layout describes.

**The identity is the PE header's `TimeDateStamp`.** It is the linker's stamp, unique per
build, and - unlike the file size - it survives patching: appending a cave bumps
`NumberOfSections` and `SizeOfImage` and leaves the COFF header alone, and a byte patch
rewrites `.text` without touching any header at all. So one number identifies a build whether
or not it carries `live-bridge`, `commandset-limit` or anything else, which matters because
the writable path *requires* a patched binary.

Reading it needs no game files: the headers are mapped at `IMAGE_BASE` in the running process,
which is the same walk `sage_patch.pe` already does to find a cave.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from sage_patch.addresses import IMAGE_BASE
from sage_patch.pe import Reader, Section, mapped_sections, read_headers

__all__ = ["ROTWK_201_TIMESTAMP", "BuildIdentity", "read_identity"]

# The COFF `TimeDateStamp` of RotWK 2.01's `game.dat`, read off the installed file that
# `LAYOUT_ROTWK_201` was confirmed against (2026-07-31). Every offset in that layout is only
# meaningful for an image carrying this stamp.
#
# Note that this identifies the **engine build**, not the mod: Edain is ini and `.big` data, so
# a different Edain release runs the same `game.dat` and answers with the same stamp. It is the
# id spaces, not the layout, that a mod release moves - see `naming.LiveNames`.
ROTWK_201_TIMESTAMP = 0x460DA09E

# `TimeDateStamp` is the second field of the COFF header, which itself sits four bytes past
# `e_lfanew` (the "PE\0\0" signature comes first).
_COFF_TIMESTAMP = 4 + 4


@dataclass(frozen=True)
class BuildIdentity:
    """What the running image says about itself."""

    timestamp: int
    image_base: int
    sections: tuple[Section, ...] = ()

    @property
    def fingerprint(self) -> str:
        """A short stable string for `Handshake.data_checksum`.

        Formatted rather than raw so a pinned value is recognisable in a config file as
        something this package produced.
        """
        return f"pe-{self.timestamp:08x}"

    @property
    def section_names(self) -> tuple[str, ...]:
        return tuple(s.name for s in self.sections)

    def carries(self, name: str) -> bool:
        """Whether the image carries a named section - how a patch announces itself."""
        return any(s.name == name for s in self.sections)

    def maps(self, address: int) -> bool:
        """Whether `address` falls inside one of the image's own sections.

        A subsystem global that lands outside every section is not a static this binary
        declares, whatever it happens to read.
        """
        return any(s.contains(address) for s in self.sections)


def read_identity(read: Reader, image_base: int = IMAGE_BASE) -> BuildIdentity | None:
    """Identify the image mapped at `image_base`, or None if there is not one there.

    None is the answer for three different problems and they are worth distinguishing at the
    call site rather than here: the process is not `game.dat`, the handle cannot read (an
    unelevated shell), or the image was relocated away from its preferred base - which would
    invalidate every hardcoded address in the layout, so it is a refusal either way.
    """
    headers = read_headers(read, image_base)
    if headers is None:
        return None
    raw = read(image_base + headers.e_lfanew + _COFF_TIMESTAMP, 4)
    if raw is None or len(raw) < 4:
        return None
    return BuildIdentity(
        timestamp=struct.unpack("<I", raw)[0],
        image_base=image_base,
        sections=tuple(mapped_sections(read, image_base)),
    )
