"""The asset-load-profile patch: turn on the engine's own per-asset load timer.

Targets the ROTWK SAGE-engine `game.dat` build ``2.01.2614.37001``. Every address below is
derived in ``../docs/asset-demand-load.md``.

**What this measures, and why it needs a patch.** The engine loads a model the first time
something needs it, on the main thread, inside the frame - `AssetHandle::EnsureLoaded`
(``0x00A32AD0``) falls through to a synchronous load at ``0x00A37320`` whenever the handle is not
already in state ``0x30000``. That is where a mid-match hitch on a high-vertex model comes from,
and the engine has always been able to say so: ``0x00A37320`` timestamps itself with ``rdtsc``,
and a writer at the tail emits one CSV row per load with the columns

.. code-block:: none

    frame,type,asset,tInit,tPreload,tLoad,tPostload,tTotal,recursion

The whole instrumentation is gated on **one byte**, `GlobalData` ``+0x123D``. It is not in the
457-row `GameData` field table, so no INI can reach it; the retail command-line table
(``0x00C35DA8``) has sixteen entries and none of them writes it; and its only writer is
`GlobalData`'s constructor, storing zero. So the switch exists, nothing can flip it, and this
patch flips it.

**What this does.** Rewrites two adjacent byte stores in `GlobalData`'s constructor as one
16-bit store:

.. code-block:: none

    stock    mov byte [esi+0x123C], bl        ; bl is 0 for this whole run of stores
             mov byte [esi+0x123D], bl
    patched  mov word [esi+0x123C], 0x0100    ; +0x123C stays 0, +0x123D becomes 1
             nop / nop / nop

Twelve bytes replacing twelve, so there is no hook, no cave and no displaced instruction. The
low half of the immediate keeps ``+0x123C`` at the zero the stock pair wrote, and the two padding
bytes at ``+0x123E``/``+0x123F`` - which the constructor never touches - stay untouched, which is
why this is a `word` store and not the shorter dword one.

**Why the constructor and not the three readers.** The readers (``0x0062ECD4``, ``0x006314E2``,
``0x0063160B``) would each need their `je` blinded, which is three sites instead of one and
leaves the flag itself reading false - so anything that later asks "is profiling on" gets the
wrong answer. Defaulting the field instead leaves it a *field*: it is still one writable byte at
`TheWritableGlobalData` ``+0x123D``, so a live session can turn it back off through
:class:`sage_live.ProcessMemory` without unpatching the binary. The engine builds override
instances of `GlobalData` through the same constructor, so the default survives them too.

**Where the file goes.** ``0x00631617`` writes ``'assetload '`` (the literal at ``0x00BFE048``)
plus the map's base name into the buffer at ``0x00DEF658``, and that buffer is both the
"profiling is on" test and the **filename**: the writer calls ``fopen`` on it directly
(``0x00A37B8B``), ``"wt"`` the first time the name changes and ``"at"`` after. So a match on
`map mp fords of isen` writes CSV content to a file called ``assetload map mp fords of isen.map``
in the process's working directory - no ``.csv`` extension, because nothing appends one. Rename it
to read it in a spreadsheet.

**The numbers are milliseconds.** The four ``t*`` columns divide an ``rdtsc`` delta by the
calibration at ``0x00DEF760`` scaled by ``0.001`` (``0x00A37D7D``), and print through ``%.3lf``.
``recursion`` is the depth of the in-progress load stack at ``0x00DEF770`` - nested loads, where
one asset drags its sub-assets in behind it - not a count of loads.

**Cost, and the observer effect.** Every demand load now does an ``fopen``/``fprintf``/``fclose``
round trip. That lands *after* the timestamps, so the ``t*`` figures stay honest, but the frame
that stalls will stall harder than it does on a stock binary. Read the columns, not the felt
hitch. Nothing else changes: the flag reaches only the profiler, and its third reader
(``0x0062ECD4``) does nothing but publish the current logic frame to ``0x00DEF550`` for the
`frame` column.

**Client-local.** No simulation state, checksum, order stream or replay format is touched, and
peers need not agree on it - one player can profile a match everyone else plays on stock binaries.

**This is a diagnostic.** It writes a file to disk on every asset load for the life of the
process, which is a thing to do while measuring and not a thing to ship in a mod release.

**Composition.** Order-independent, and it allocates nothing. No other bundled patch writes the
twelve bytes at ``0x00643A73`` or reads `GlobalData` ``+0x123C``/``+0x123D``.
"""

from __future__ import annotations

import struct

from ..addresses import GLOBAL_DATA_ASSET_PROFILE
from ..patcher import Patch
from ..utils import apply_byte_patch, va_to_offset

__all__ = [
    "ANCHORS",
    "CTOR_STORE_PAIR",
    "CTOR_STORE_PAIR_BYTES",
    "PATCHED_STORE",
    "PROFILE_NAME_PREFIX",
    "PROFILE_NAME_PREFIX_VA",
    "AssetLoadProfilePatch",
]

#: The two adjacent byte stores in `GlobalData`'s constructor that zero ``+0x123C`` and
#: ``+0x123D``. ``bl`` is zero across this entire run of field initialisers.
CTOR_STORE_PAIR = 0x00643A73
CTOR_STORE_PAIR_BYTES = bytes.fromhex("889e3c120000889e3d120000")

#: `mov word [esi+0x123C], 0x0100` plus three `nop`s. The immediate is little-endian, so the low
#: byte lands on ``+0x123C`` (zero, as stock) and the high byte on ``+0x123D`` (one).
PATCHED_STORE = bytes.fromhex("66c7863c1200000001") + b"\x90\x90\x90"

#: The literal the profiler names its output after, and where it lives. Read as an anchor, never
#: written: it is what proves the flag being defaulted is the asset profiler's own.
PROFILE_NAME_PREFIX_VA = 0x00BFE048
PROFILE_NAME_PREFIX = b"assetload \x00"

#: Byte windows the patch depends on but never writes, as ``{va: expected bytes}``. Together they
#: pin the field offset from *both* ends: the gate at ``0x0063160B`` reads ``+0x123D`` and, five
#: bytes past its jump, hands the profiler its name.
ANCHORS: dict[int, bytes] = {
    # `cmp byte [eax+0x123D], bl` - the gate that arms the profile for a new map
    0x0063160B: bytes.fromhex("38983d120000"),
    # the `je` over it, and `push 0x00BFE048` on the arm it guards
    0x00631611: bytes.fromhex("0f84950000006848e0bf00"),
    # `cmp byte [eax+0x123D], 0` - the frame publisher in the logic update
    0x0062ECD4: bytes.fromhex("80b83d12000000"),
    PROFILE_NAME_PREFIX_VA: PROFILE_NAME_PREFIX,
}


class AssetLoadProfilePatch(Patch):
    name = "asset-load-profile"
    author = "officialNecro"
    description = (
        "Default the engine's own per-asset load timer on, so a match writes a CSV of every "
        "demand-loaded model and what it cost. Diagnostic. No INI change"
    )

    def apply(self, data: bytearray) -> None:
        self._check_anchors(data)
        off = va_to_offset(data, CTOR_STORE_PAIR)
        if off is None:
            raise ValueError(f"{CTOR_STORE_PAIR:#010x} is not mapped - not the expected build")
        apply_byte_patch(
            data,
            off,
            CTOR_STORE_PAIR_BYTES,
            PATCHED_STORE,
            f"GlobalData+{GLOBAL_DATA_ASSET_PROFILE:#x} defaults to 1",
        )

    @staticmethod
    def _check_anchors(data: bytes | bytearray) -> None:
        """Raise unless the profiler's own gates and its name literal are where they should be.

        The store being rewritten is generic - a dozen fields around it are initialised the same
        way - so on its own it proves nothing about *which* field it writes. These four windows
        are what make a wrong address fail loudly rather than quietly zeroing something else.
        """
        for va, expected in ANCHORS.items():
            off = va_to_offset(data, va)
            if off is None:
                raise ValueError(f"{va:#010x} is not mapped - not the expected build")
            got = bytes(data[off : off + len(expected)])
            if got != expected:
                raise ValueError(
                    f"anchor {va:#010x} holds {got.hex()}, expected {expected.hex()} - "
                    "the asset-load profiler is not where this patch expects it"
                )

    def verify(self, data: bytes | bytearray) -> list[str]:
        off = va_to_offset(data, CTOR_STORE_PAIR)
        if off is None:
            return [f"{CTOR_STORE_PAIR:#010x} is not mapped by any section"]
        got = bytes(data[off : off + len(PATCHED_STORE)])
        if got != PATCHED_STORE:
            return [
                f"the GlobalData constructor holds {got.hex()}, expected {PATCHED_STORE.hex()} - "
                "does not carry this patch"
            ]
        # The immediate is what decides whether the flag comes up set; read it back rather than
        # trusting the byte compare above to have been written with the right one.
        immediate = struct.unpack_from("<H", got, len(got) - 5)[0]
        if immediate >> 8 != 1:
            return [f"the constructor store writes {immediate:#06x} - the profiler stays off"]
        return []
