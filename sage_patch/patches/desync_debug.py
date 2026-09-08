"""`desync-debug` - turn on the engine's own out-of-sync instrumentation, which ships unreachable.

Targets the ROTWK SAGE-engine `game.dat` build ``2.01.2614.37001``. Every address below is derived
in ``../docs/desync-debug.md``; the detection side it builds on is ``../docs/desync-detection.md``.

**The defect.** A match desyncs and the engine tells you almost nothing about when. The
`MSG_LOGIC_CRC` (`0x44A`) heartbeat that peers compare goes out every ``NetCRCInterval`` frames and
that interval is **100**, so a declaration at frame 102 means "you parted somewhere in frames
1..100" and the message box is the whole report. The engine was built with better than that - a
tunable interval, a focus frame, a per-frame self-check that writes a file - and shipped with every
switch stranded behind the orphaned command-line region ``../docs/headless.md`` section 5
documents, a block of handlers with no dispatch-table row, no call site and no pointer anywhere in
the image. So the switches are `.data` with initialisers and no live writer, and nothing on a
retail build can flip one.

**What this does.** Writes three of them. No cave, no hook, no assembly: three initialisers, one
dword and one byte and one dword, asserted against their stock values before anything is written.

* ``crc_interval`` (1..99, default **1**) rewrites ``NetCRCInterval`` at ``NET_CRC_INTERVAL``.
  Three live readers pick it up and between them they cover both halves of an investigation. The
  `GameInfo` constructor seeds `+0xC` from it unclamped and `GameLogic::update` divides the frame
  by that field, so the **declaration** narrows from a 100-frame upper bound to an N-frame one; and
  the recorder copies the same global into the replay header, so **every peer's own recording gains
  a CRC sample every N frames** and two players' `.rep` files of one match become diffable to the
  frame - `sage_replay.replay.OrderType.ChecksumHeartbeat`. That second half is the one that
  actually finds things: the latch says *this client disagrees*, the diff says *from here on*.
* ``verify_client_crc`` (default off) sets the ``-verifyClientCRC`` gate at
  ``DESYNC_VERIFY_CLIENT_CRC_FLAG``, which unlocks the per-client-frame self-check at
  ``DESYNC_FILE_WRITER``: it recomputes this client's CRC, compares it against a caller-supplied
  value and appends ``"Desync detected on frame %d on %u-%u-%u %u:%u:%u"`` to
  ``CLIENT_DESYNC_<name>.txt``. The code is complete and reached; ``../docs/desync-detection.md``
  section 3 records that no retail build can arm it, which is exactly what this flips.
* ``focus_frame`` (default unset) sets ``DESYNC_FOCUS_FRAME``, which **overrides the interval**:
  per-frame heartbeats across the window ending on that frame and silence everywhere else. The
  second pass, once a first has said roughly where. It does not arm
  ``DESYNC_FOCUS_FRAME_FILTER_FLAG``, so the message box and the latch keep behaving normally.

**Why the interval is the patch's identity.** It is the parameter `detect` recovers, and its range
stops at 99 on purpose: at 100 every site holds its stock bytes, so a `verify` that passed there
would make `detect` report every unpatched `game.dat` as carrying this patch. Raising it is not
offered either way - the skirmish re-seed clamps to ``min(x, 100)`` (``0x0077ED63``) while the
constructor does not, so above 100 the two paths disagree, and coarser than stock is not what this
is for. **Zero is refused by the constructor**: the gate's `div ecx` has no guard, and a zero
interval is an integer divide-by-zero on the logic thread on the first frame of the first match.

**What it costs.** At interval 1 the CRC producer at ``0x00625886`` runs every logic frame instead
of every hundredth, walking the object list, the partition and collision managers, the shroud, the
players and the AI, and one extra `0x44A` message per frame per client goes on the wire and into
every replay. That is a real per-frame cost on a large late-game match and the reason the interval
is a parameter rather than a constant - 5 or 10 keeps most of the resolution for a tenth of the
work. Nothing here is free, and a build carrying this is a debugging build.

**Blast radius: every peer must match.** The heartbeat cadence is a network protocol detail, not a
client-local preference. A client emitting `0x44A` every frame against a peer emitting one every
hundred is not a configuration this engine was built to survive, so **all players in a match, and
anyone playing back a recording of it, must run the byte-identical binary**. Replays made on a
patched build carry the patched cadence in their header and should be played back on the same
build. That is the opposite of the `crash-dump` / `quiet-exit` rule and the same one
``binary-attest`` enforces on purpose.

**What is deliberately not exposed.** ``-deepCRC`` (``DESYNC_DEEP_CRC_FLAG``) logs the checksum's
constituents into a growable heap buffer that no shipping config drains - a per-frame allocation
and no file - and the nine ``-x<Subsystem>CRC`` exclusion flags are consulted only when
``CRC_LITE_FLAG`` is clear, which the plain emitter path sets for the duration of every call. So on
the route a retail build takes they change nothing. ``-debugCRCFromFrame`` and
``-debugCRCUntilFrame`` have no reader outside the flag-reporting function at all.
``../docs/desync-debug.md`` sections 4 to 6 have the disassembly for all three findings, so the
next reader does not spend the afternoon on them.

**Composition.** Order-independent: it allocates no section, edits three `.data` initialisers no
other bundled patch touches, and reads nothing another patch rewrites. It has no INI surface.
``binary-attest`` is the one to think about beside it - that patch mixes a `.text` hash into this
same checksum, and since this patch changes `.text` not at all but does change how often the
checksum is taken, the two compose, with the usual caveat that both of them require every peer to
run the identical file.

**Static-verified.** The addresses, the readers and the clamp are read out of the binary and the
patch applies, verifies and round-trips; what has not been done is play a patched match and watch a
desync land on a known frame.
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
        """Structural check that ``data`` carries this patch with these options (an empty list ==
        verified). Recomputes all three sites and compares; reads only via the section table, so
        it needs no disassembler.

        The two optional sites are checked whether they are on or off: a binary whose
        ``-verifyClientCRC`` gate is set does not carry a patch built with it left alone."""
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
        """Recognise this patch **and recover its options** from ``data``.

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
