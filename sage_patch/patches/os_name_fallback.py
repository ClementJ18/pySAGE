"""Let `game.dat` start on Windows 10 and 11 without the Windows XP compatibility mode.

The startup hardware report names the Windows version through a builder (`OS_NAME_BUILDER`) that
knows NT major versions 4 and 5 only. For any other major it returns without writing the name
pointer, and the report prints that uninitialised pointer with `%s` - a crash in `msvcr71.dll`
before the first frame. The XP compatibility mode hides it by reporting version 5.1, and in doing so
wraps the Direct3D device in the compatibility shim. Six bytes: the branch for an unknown major goes
to the major-5 arm's last case instead, which writes "WINXX" and returns through the same epilogue.

Derivation: `../docs/os-name-fallback.md`.
"""

from __future__ import annotations

import struct

from ..addresses import (
    OS_NAME_NT_FALLBACK,
    OS_NAME_NT_FALLBACK_BYTES,
    OS_NAME_NT_MAJOR_FIVE_TEST,
    OS_NAME_NT_MAJOR_FIVE_TEST_BYTES,
    OS_NAME_NT_UNKNOWN_BRANCH,
    OS_NAME_NT_UNKNOWN_BRANCH_BYTES,
)
from ..patcher import Patch
from ..utils import apply_byte_patch, va_to_offset

__all__ = ["ANCHORS", "FALLBACK_BRANCH", "OsNameFallbackPatch"]

#: The unknown-major branch as it becomes: the same `jne`, to the "WINXX" case.
FALLBACK_BRANCH = b"\x0f\x85" + struct.pack(
    "<i", OS_NAME_NT_FALLBACK - (OS_NAME_NT_UNKNOWN_BRANCH + len(OS_NAME_NT_UNKNOWN_BRANCH_BYTES))
)

#: Byte windows the patch depends on and does not write: the test the branch belongs to, and the
#: case it is sent to.
ANCHORS: dict[int, bytes] = {
    OS_NAME_NT_MAJOR_FIVE_TEST: OS_NAME_NT_MAJOR_FIVE_TEST_BYTES,
    OS_NAME_NT_FALLBACK: OS_NAME_NT_FALLBACK_BYTES,
}


class OsNameFallbackPatch(Patch):
    name = "os-name-fallback"
    author = "officialNecro"
    # The game starts without compatibility mode on Windows 11 (2026-10-15); no full match yet
    runtime_verified = "partly"
    description = (
        "Name an unknown Windows version in the startup hardware report instead of printing an "
        "uninitialised pointer, so game.dat starts on Windows 10 and 11 without the Windows XP "
        "compatibility mode (which also wraps the Direct3D device in a compatibility shim). "
        "Client-local. No INI change"
    )

    def apply(self, data: bytearray) -> None:
        self._check_anchors(data)
        apply_byte_patch(
            data,
            self._offset(data, OS_NAME_NT_UNKNOWN_BRANCH),
            OS_NAME_NT_UNKNOWN_BRANCH_BYTES,
            FALLBACK_BRANCH,
            "Windows name: unknown NT major -> WINXX",
        )

    @staticmethod
    def _offset(data: bytes | bytearray, va: int) -> int:
        off = va_to_offset(data, va)
        if off is None:
            raise ValueError(f"{va:#010x} is not mapped - not the expected build")
        return off

    @classmethod
    def _check_anchors(cls, data: bytes | bytearray) -> None:
        """Raise unless the branch sits after the major-5 test and the "WINXX" case is intact.

        The branch is only this patch's to redirect when it is the one taken on that test, and its
        new target only returns cleanly while it is the epilogue the bare return shares."""
        for va, expected in ANCHORS.items():
            off = cls._offset(data, va)
            got = bytes(data[off : off + len(expected)])
            if got != expected:
                raise ValueError(
                    f"{va:#010x} holds {got.hex()}, expected {expected.hex()} - this is not the "
                    "Windows-name builder of the expected build"
                )

    def verify(self, data: bytes | bytearray) -> list[str]:
        try:
            self._check_anchors(data)
        except ValueError as exc:
            return [str(exc)]
        off = self._offset(data, OS_NAME_NT_UNKNOWN_BRANCH)
        got = bytes(data[off : off + len(FALLBACK_BRANCH)])
        if got == FALLBACK_BRANCH:
            return []
        which = "the stock branch" if got == OS_NAME_NT_UNKNOWN_BRANCH_BYTES else "something else"
        return [
            f"{OS_NAME_NT_UNKNOWN_BRANCH:#010x} holds {got.hex()} ({which}): the file does not "
            "carry this patch"
        ]
