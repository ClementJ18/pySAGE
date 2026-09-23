"""Turn on the engine's own out-of-sync instrumentation, which ships unreachable.

The switches exist but only an orphaned command-line block (see `../docs/headless.md` section 5)
ever wrote them. The patch rewrites three initialisers - the checksum interval, the self-check flag
and the focus frame - with no cave or hook. The interval is the patch's identity for `detect`, so it
must be 1..99 (100 is stock; above it, the skirmish re-seed clamps at `0x0077ED63` while the
constructor does not, and 0 divides by zero). Every peer needs the same binary.

Derivation: `../docs/desync-debug.md` and `../docs/desync-detection.md`.
"""

from __future__ import annotations

import struct
from typing import TYPE_CHECKING

from ..addresses import (
    DESYNC_FOCUS_FRAME,
    DESYNC_FOCUS_FRAME_UNSET,
    DESYNC_VERIFY_CLIENT_CRC_FLAG,
    NET_CRC_INTERVAL,
    NET_CRC_INTERVAL_STOCK,
)
from ..patcher import Patch
from ..utils import apply_byte_patch, va_to_offset

if TYPE_CHECKING:
    import argparse

__all__ = [
    "MAX_FOCUS_FRAME",
    "MAX_INTERVAL",
    "MIN_FOCUS_FRAME",
    "MIN_INTERVAL",
    "DesyncDebugPatch",
]

#: 1 because the heartbeat gate's `div ecx` has no zero guard, and 99 because at 100 every site
#: this patch writes holds its stock value - a `verify` that passed there would make `detect`
#: report every unpatched binary as carrying the patch. Above 100 is refused for a third reason:
#: the skirmish re-seed clamps to `min(x, 100)` and the `GameInfo` constructor does not, so a
#: coarser interval would mean two paths disagreeing about the cadence.
MIN_INTERVAL = 1
MAX_INTERVAL = NET_CRC_INTERVAL_STOCK - 1

#: The engine's own focus-frame handler rejects a non-positive `atoi`, and `0xFFFFFFFF` is the
#: sentinel the gate compares against for "unset", so the usable range is the positive signed ints.
MIN_FOCUS_FRAME = 1
MAX_FOCUS_FRAME = 0x7FFFFFFF


class DesyncDebugPatch(Patch):
    """Turn on the engine's dead out-of-sync instrumentation: a finer CRC heartbeat, optionally
    the `CLIENT_DESYNC_*.txt` self-check and a focus frame."""

    name = "desync-debug"
    author = "officialNecro"
    description = (
        "Turn on the engine's own out-of-sync instrumentation, which ships unreachable: tighten "
        "the MSG_LOGIC_CRC heartbeat from every 100 frames to every N, so a desync is declared "
        "within N frames and every player's replay carries a CRC sample that often - two "
        "recordings of one match then diff to the frame they parted. Optionally arms the "
        "CLIENT_DESYNC_<name>.txt self-check and a focus frame. No INI surface, but EVERY PEER "
        "MUST RUN THE SAME BINARY - the heartbeat cadence is a protocol detail, not a preference"
    )

    def __init__(
        self,
        crc_interval: int = 1,
        verify_client_crc: bool = False,
        focus_frame: int | None = None,
    ):
        if not MIN_INTERVAL <= crc_interval <= MAX_INTERVAL:
            hint = ""
            if crc_interval < MIN_INTERVAL:
                hint = " (the heartbeat gate divides the frame by it, with no zero guard)"
            elif crc_interval >= NET_CRC_INTERVAL_STOCK:
                hint = f" ({NET_CRC_INTERVAL_STOCK} is what the engine ships; this tightens it)"
            raise ValueError(
                f"crc_interval must be in {MIN_INTERVAL}..{MAX_INTERVAL}, got {crc_interval}{hint}"
            )
        if focus_frame is not None and not MIN_FOCUS_FRAME <= focus_frame <= MAX_FOCUS_FRAME:
            raise ValueError(
                f"focus_frame must be in {MIN_FOCUS_FRAME}..{MAX_FOCUS_FRAME} or None, "
                f"got {focus_frame}"
            )
        self.crc_interval = crc_interval
        self.verify_client_crc = verify_client_crc
        self.focus_frame = focus_frame

    def __str__(self) -> str:
        extra = ", verifyClientCRC" if self.verify_client_crc else ""
        if self.focus_frame is not None:
            extra += f", focus frame {self.focus_frame}"
        return f"{self.name} (every {self.crc_interval} frames{extra})"

    def apply(self, data: bytearray) -> None:
        for file_off, old, new, note in self._edits(data):
            apply_byte_patch(data, file_off, old, new, note)

    def verify(self, data: bytes | bytearray) -> list[str]:
        """Structural check that `data` carries this patch with these options (an empty list ==
        verified). Recomputes all three sites and compares; reads only via the section table, so
        it needs no disassembler.

        The two optional sites are checked whether they are on or off: a binary whose
        `-verifyClientCRC` gate is set does not carry a patch built with it left alone."""
        problems: list[str] = []
        try:
            edits = self._edits(data)
        except ValueError as exc:
            return [str(exc)]
        for file_off, _old, new, note in edits:
            got = bytes(data[file_off : file_off + len(new)])
            if got != new:
                problems.append(f"{note} @0x{file_off:x}: expected {new.hex()}, got {got.hex()}")
        return problems

    @classmethod
    def detect(cls, data: bytes | bytearray) -> DesyncDebugPatch | None:
        """Recognise this patch **and recover its options** from `data`.

        The default probe cannot: it would ask `verify` about interval 1 with both extras off and
        call every other configuration absent. All three parameters are plain initialisers, so
        they read straight back out. A stock binary yields interval 100, which is outside this
        patch's range and so is reported - correctly - as not carrying it."""
        interval_off = va_to_offset(data, NET_CRC_INTERVAL)
        flag_off = va_to_offset(data, DESYNC_VERIFY_CLIENT_CRC_FLAG)
        frame_off = va_to_offset(data, DESYNC_FOCUS_FRAME)
        if interval_off is None or flag_off is None or frame_off is None:
            return None
        try:
            interval = struct.unpack_from("<I", data, interval_off)[0]
            focus = struct.unpack_from("<I", data, frame_off)[0]
        except struct.error:
            return None
        if not MIN_INTERVAL <= interval <= MAX_INTERVAL:
            return None
        flag = data[flag_off]
        if flag not in (0, 1):
            return None
        focus_frame = None if focus == DESYNC_FOCUS_FRAME_UNSET else focus
        try:
            patch = cls(interval, bool(flag), focus_frame)
        except ValueError:
            return None
        return None if patch.verify(data) else patch

    @classmethod
    def add_cli_arguments(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--crc-interval",
            type=int,
            default=1,
            metavar="N",
            help=(
                f"emit the frame checksum every N frames ({MIN_INTERVAL}..{MAX_INTERVAL}); "
                "default 1. The engine ships 100. Lower is finer and costs one CRC pass plus one "
                "message per client per frame, so 5 or 10 trades resolution for load"
            ),
        )
        parser.add_argument(
            "--verify-client-crc",
            action="store_true",
            help=(
                "arm the engine's per-frame self-check, which appends to CLIENT_DESYNC_<name>.txt "
                "next to the executable when its recomputed checksum disagrees"
            ),
        )
        parser.add_argument(
            "--focus-frame",
            type=int,
            default=None,
            metavar="F",
            help=(
                "override the interval near one frame: emit a checksum every frame across the "
                "window ending at F and none anywhere else. For a second pass, once a first has "
                "narrowed it down"
            ),
        )

    @classmethod
    def from_cli_args(cls, args: argparse.Namespace) -> DesyncDebugPatch:
        return cls(
            crc_interval=args.crc_interval,
            verify_client_crc=args.verify_client_crc,
            focus_frame=args.focus_frame,
        )

    def _edits(self, data: bytes | bytearray) -> list[tuple[int, bytes, bytes, str]]:
        """Every `(file offset, stock bytes, patched bytes, note)` this patch writes.

        One list serves `apply` and `verify`: `apply` asserts the stock bytes and writes the
        patched ones, `verify` compares the patched ones to what is on disk. Raises if a site is
        not mapped, which is how a binary that is not this build fails before anything is
        written."""
        focus = DESYNC_FOCUS_FRAME_UNSET if self.focus_frame is None else self.focus_frame
        return [
            (
                self._offset(data, NET_CRC_INTERVAL),
                struct.pack("<I", NET_CRC_INTERVAL_STOCK),
                struct.pack("<I", self.crc_interval),
                f"NetCRCInterval -> every {self.crc_interval} frames",
            ),
            (
                self._offset(data, DESYNC_VERIFY_CLIENT_CRC_FLAG),
                b"\x00",
                bytes([int(self.verify_client_crc)]),
                f"verifyClientCRC -> {'on' if self.verify_client_crc else 'off'}",
            ),
            (
                self._offset(data, DESYNC_FOCUS_FRAME),
                struct.pack("<I", DESYNC_FOCUS_FRAME_UNSET),
                struct.pack("<I", focus),
                f"desync focus frame -> {'unset' if self.focus_frame is None else focus}",
            ),
        ]

    @staticmethod
    def _offset(data: bytes | bytearray, va: int) -> int:
        off = va_to_offset(data, va)
        if off is None:
            raise ValueError(f"{va:#010x} is not mapped - not the expected build")
        return off
