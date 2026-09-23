"""Turn on the engine's built-in per-asset load timer, so a match writes a CSV row for every
demand-loaded model and what it cost.

Models load synchronously on first use, inside the frame (`AssetHandle::EnsureLoaded`). The engine
already times each load, but the switch is a `GlobalData` byte no INI or command-line option can
set. Two byte stores in the `GlobalData` constructor are rewritten to default it on. A diagnostic:
client-local, but it writes to disk on every load.

Derivation: `../docs/asset-demand-load.md`.
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

#: The two adjacent byte stores in `GlobalData`'s constructor that zero `+0x123C` and
#: `+0x123D`. `bl` is zero across this entire run of field initialisers.
CTOR_STORE_PAIR = 0x00643A73
CTOR_STORE_PAIR_BYTES = bytes.fromhex("889e3c120000889e3d120000")

#: `mov word [esi+0x123C], 0x0100` plus three `nop`s. The immediate is little-endian, so the low
#: byte lands on `+0x123C` (zero, as stock) and the high byte on `+0x123D` (one).
PATCHED_STORE = bytes.fromhex("66c7863c1200000001") + b"\x90\x90\x90"

#: The literal the profiler names its output after, and where it lives. Read as an anchor, never
#: written: it is what proves the flag being defaulted is the asset profiler's own.
PROFILE_NAME_PREFIX_VA = 0x00BFE048
PROFILE_NAME_PREFIX = b"assetload \x00"

#: Byte windows the patch depends on but never writes, as `{va: expected bytes}`. Together they
#: pin the field offset from *both* ends: the gate at `0x0063160B` reads `+0x123D` and, five
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
