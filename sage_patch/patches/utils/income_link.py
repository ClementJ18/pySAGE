"""The one thing `command-point-upkeep` and `inflation-readout` share: a function pointer.

Both patches scale the *same* income. `command-point-upkeep` multiplies `AutoDepositUpdate`'s
inflation multiplier by its own factor; `inflation-readout` draws that multiplier in the palantir.
So when both are installed the readout has to show the **product**, or the palantir and the
treasury disagree.

**Why this is a module and not a direct import.** The obvious implementation - have the readout
look for `.upkeep` and bake its address in - breaks
:class:`~sage_patch.patcher.Patch`'s composition contract in the one way the framework cannot
catch. Rule 3 is *do not derive your output from bytes another patch rewrites*: applied
readout-then-upkeep the lookup finds nothing and the readout silently drops the upkeep factor,
applied upkeep-then-readout it finds it. **Both orders succeed and disagree**, and no assertion
fires, because neither patch has touched a byte the other asserted.

So the link is a **null function pointer either patch can fill**, and whichever is applied
*second* completes it:

* `.upkeep + 0x04` exports `percent`. That offset is free at zero cost - the upkeep cave's block
  key is one dword at `+0x00` and its row table starts at `+0x10`, so `+0x04..+0x0F` is padding.
* `.inflrd + 0x00` imports it, and is zero in a file that carries no upkeep.
* Readout second: it reads the export and lays the value into its own section as it builds it -
  no cross-patch write at all. Upkeep second: it adds one entry to its edit list writing the
  import slot from four zero bytes, which `apply_byte_patch` guards like any other edit.

Neither patch's *code layout* depends on the other. Only these four bytes of data do, which is
what makes the pair order-independent rather than merely documented-as-ordered.

**The exported contract**, which `command-point-upkeep` may not now change without breaking a
linked readout::

    percent(ecx: Player*) -> eax: int    ; the percentage of income that player keeps, 0..100

`100` for every degenerate case (no player, no template, no row, a zero step, an empty value
list), so a caller never needs to special-case anything. Preserves every register but `eax`,
`ecx` and the flags, and reads no memory the simulation writes during a frame.
"""

from __future__ import annotations

import struct

from sage_patch.utils import find_section

__all__ = [
    "READOUT_IMPORT_OFF",
    "READOUT_SECTION",
    "UPKEEP_EXPORT_OFF",
    "UPKEEP_SECTION",
    "read_export",
    "read_import",
    "import_slot_offset",
]

#: `command-point-upkeep`'s cave, and the offset in it that publishes `percent`. `0x04` sits in
#: the padding between the block-key dword at `0x00` and the row table at `0x10`, so exporting
#: costs no bytes and moves no routine.
UPKEEP_SECTION = ".upkeep"
UPKEEP_EXPORT_OFF = 0x04

#: `inflation-readout`'s cave, and the slot its code calls through. Zero means "no upkeep in this
#: file", which the emitted code tests for on every refresh.
READOUT_SECTION = ".inflrd"
READOUT_IMPORT_OFF = 0x00


def read_export(data: bytes | bytearray) -> int | None:
    """The VA of `command-point-upkeep`'s `percent`, or None if the file carries no upkeep."""
    located = find_section(data, UPKEEP_SECTION)
    if located is None:
        return None
    _va, off, _vsize = located
    value: int = struct.unpack_from("<I", data, off + UPKEEP_EXPORT_OFF)[0]
    return value or None


def import_slot_offset(data: bytes | bytearray) -> int | None:
    """The file offset of `inflation-readout`'s import slot, or None if it carries no readout."""
    located = find_section(data, READOUT_SECTION)
    if located is None:
        return None
    _va, off, _vsize = located
    return off + READOUT_IMPORT_OFF


def read_import(data: bytes | bytearray) -> int | None:
    """What `inflation-readout` currently calls for the upkeep factor: a VA, or 0 for "nothing".

    None distinguishes "the file has no readout" from "the readout is unlinked", which
    :meth:`verify` on both sides needs to tell apart.
    """
    off = import_slot_offset(data)
    if off is None:
        return None
    value: int = struct.unpack_from("<I", data, off)[0]
    return value
