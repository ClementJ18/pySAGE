"""Running more than one copy of the game at once.

Two patches, because the limit is enforced in **two binaries**: :class:`MultiInstancePatch`
targets `game.dat` (build ``2.01.2614.37001``) and :class:`MultiInstanceLauncherPatch` targets
`lotrbfme2ep1.exe`, the launcher shim every shortcut actually starts. Both are needed — patching
either one alone leaves the other refusing. See ``../docs/multi-instance.md`` for the derivation.

**Three gates, all built the same way.** Each names a mutex, calls `CreateMutex`, and reads
`GetLastError` for ``ERROR_ALREADY_EXISTS`` (``0xB7``). The result is consumed by a conditional
branch whose *fall-through* is the normal startup path, so flipping that one opcode byte to
``jmp`` makes the "already exists" arm unreachable and leaves everything else — including the
`CreateMutex` call itself and the `CloseHandle` that balances it — exactly as it was.

1. **The launcher's message.** `lotrbfme2ep1.exe` at ``0x004092E3`` creates a mutex named by the
   ``G1`` GUID it parses out of `gi.dat`, and on ``0xB7`` puts up the CSF string
   ``Launcher:GameRunning`` — "The game is already running" — then closes the handle and exits.
   This is the only one of the three that says anything.

2. **`game.dat`'s silent abort.** `WinMain` at ``0x00402AED`` creates
   ``L"E99E8455-CC9B-488a-BA22-0E8A8F74F9FA"``, and on ``0xB7`` passes that same GUID to
   `FindWindowW` as a *window class* name, raises the window it finds, and returns 0 from `WinMain`
   with no diagnostic at all. A launcher-only patch gets you as far as this and no further.

3. **`game.dat`'s wait loop, which shuts the first instance down.** ``0x0063F68D`` is a bool
   probe — create the mutex, `sete` on ``0xB7``, close it again — called once, at ``0x00402C6E``.
   A true answer runs ``0x0063F6BF``, which spins for 60 seconds (``0xEA60`` ms) polling
   `OpenEventA` for a named event and, the moment it finds one, calls `SetEvent` on it. That event
   is how a copy of the game asks the copy already running to quit. So this gate is not merely a
   stall: left in place it makes starting a second instance terminate the first. The probe call and
   its `test al, al` are left standing (the probe closes its own handle and has no other effect);
   only the branch that acts on the answer is neutralised.

**What the patches do not do.** Both processes still share one user-data directory, so
`Options.ini` and `Last Replay.BfME2Replay` are written by both and kept by whichever exits last.
Nothing here separates them.

**Composition.** Neither patch allocates a cave, and no byte either one edits is touched by
anything else in this package, so both are order-independent with everything bundled. See the
composition contract on :class:`~..patcher.Patch`.
"""

from __future__ import annotations

from typing import NamedTuple

from ..patcher import Patch
from ..utils import apply_byte_patch, va_to_offset

__all__ = [
    "GAME_FINGERPRINT",
    "GAME_GUARDS",
    "LAUNCHER_FINGERPRINT",
    "LAUNCHER_GUARDS",
    "Guard",
    "MultiInstanceLauncherPatch",
    "MultiInstancePatch",
]

#: The one-byte encoding of ``jmp rel8``, which every guard's conditional jump becomes.
JMP_SHORT = 0xEB


class Guard(NamedTuple):
    """One conditional branch to defuse.

    ``va`` addresses ``run_up``, not the jump: asserting the instructions that compute the
    condition alongside the jump is what stops a two-byte ``75 xx`` somewhere else in a different
    build from being mistaken for this site. ``opcode`` and ``displacement`` are the stock ``jcc
    rel8``; only ``opcode`` is rewritten, so the branch keeps its target and its length.
    """

    va: int
    run_up: bytes
    opcode: int
    displacement: int
    note: str

    @property
    def stock(self) -> bytes:
        return self.run_up + bytes((self.opcode, self.displacement))

    @property
    def patched(self) -> bytes:
        return self.run_up + bytes((JMP_SHORT, self.displacement))


#: ``cmp eax, 0xB7`` — the ``GetLastError`` test all three gates share, and the run-up asserted
#: ahead of the two guards that follow it directly.
_CMP_ALREADY_EXISTS = bytes.fromhex("3db7000000")

GAME_GUARDS = (
    Guard(
        va=0x00402AFB,
        run_up=_CMP_ALREADY_EXISTS,
        opcode=0x75,  # jne 0x00402B5C -> carry on into normal startup
        displacement=0x5A,
        note="WinMain single-instance abort",
    ),
    Guard(
        va=0x00402C6E,
        # call 0x0063F68D (the probe) / test al, al
        run_up=bytes.fromhex("e81aca230084c0"),
        opcode=0x74,  # je 0x00402CA4 -> carry on, skipping the wait loop
        displacement=0x2D,
        note="WinMain wait-for-other-instance loop",
    ),
)

#: Calls that pin :data:`GAME_GUARDS` to the code that really is the instance check, asserted
#: before anything is written. The first guard is two `cmp`-able bytes and the second is a `rel32`
#: call, neither of which is distinctive on its own.
GAME_FINGERPRINT = {
    0x00402AED: bytes.fromhex("ff157c01bd00"),  # call CreateMutexW
    0x00402AF5: bytes.fromhex("ff150802bd00"),  # call GetLastError
    0x00402B0B: bytes.fromhex("ff150409bd00"),  # call FindWindowW, in the arm being cut off
    0x0063F699: bytes.fromhex("ff151c02bd00"),  # call CreateMutexA, inside the probe
    0x00402C77: bytes.fromhex("e843ca2300"),  # call 0x0063F6BF, the wait loop itself
}

LAUNCHER_GUARDS = (
    Guard(
        va=0x004092F5,
        run_up=_CMP_ALREADY_EXISTS,
        opcode=0x75,  # jne 0x0040933E -> carry on and launch game.dat
        displacement=0x42,
        note="launcher GameRunning message",
    ),
)

LAUNCHER_FINGERPRINT = {
    0x004092E3: bytes.fromhex("ff15c0f04500"),  # call CreateMutexA
    0x004092EF: bytes.fromhex("ff15d8f14500"),  # call GetLastError
    # The two CSF labels the arm being cut off puts on screen. These are what make the site
    # unmistakable: they are the message the patch exists to remove.
    0x00409305: bytes.fromhex("68b80b4600"),  # push "Launcher:LauncherErrorCaption"
    0x00409314: bytes.fromhex("68a00b4600"),  # push "Launcher:GameRunning"
}


def _offset(data: bytes | bytearray, va: int) -> int:
    off = va_to_offset(data, va)
    if off is None:
        raise ValueError(f"VA 0x{va:08x} is not mapped")
    return off


class _MutexGuardPatch(Patch):
    """Turn each of :attr:`guards`' conditional jumps into ``jmp``, once :attr:`fingerprint`
    confirms the image is the build those addresses were derived from.

    Subclasses supply the two tables and the usual :attr:`~..patcher.Patch.name` /
    :attr:`~..patcher.Patch.description`. There is nothing to parameterise, so the inherited
    :meth:`~..patcher.Patch.detect` — probe with the default constructor, ask :meth:`verify` —
    is already correct for both.
    """

    guards: tuple[Guard, ...] = ()
    fingerprint: dict[int, bytes] = {}
    binary: str = ""

    def apply(self, data: bytearray) -> None:
        self._check_fingerprint(data)
        for guard in self.guards:
            apply_byte_patch(data, _offset(data, guard.va), guard.stock, guard.patched, guard.note)

    def verify(self, data: bytes | bytearray) -> list[str]:
        """Structural check that ``data`` carries this patch (an empty list == verified): every
        fingerprint site still reads what it should, and every guard now reads ``jmp``."""
        problems: list[str] = []
        for va, expected in self.fingerprint.items():
            off = va_to_offset(data, va)
            got = None if off is None else bytes(data[off : off + len(expected)])
            if got != expected:
                hexed = "unmapped" if got is None else got.hex()
                problems.append(
                    f"0x{va:08x} is {hexed}, expected {expected.hex()}: this is not a "
                    f"{self.binary} of the build this patch was derived from"
                )
        if problems:
            return problems

        for guard in self.guards:
            off = _offset(data, guard.va)
            got = bytes(data[off : off + len(guard.patched)])
            if got != guard.patched:
                problems.append(
                    f"{guard.note} @0x{guard.va:08x}: expected {guard.patched.hex()}, "
                    f"got {got.hex()}"
                )
        return problems

    def _check_fingerprint(self, data: bytes | bytearray) -> None:
        """Raise unless every pinning site holds its stock bytes, so a patch aimed at the wrong
        binary or the wrong build fails before it writes rather than flipping an unrelated
        branch."""
        for va, expected in self.fingerprint.items():
            off = va_to_offset(data, va)
            got = None if off is None else bytes(data[off : off + len(expected)])
            if got != expected:
                hexed = "unmapped" if got is None else got.hex()
                raise ValueError(
                    f"unexpected build: 0x{va:08x} is {hexed}, expected {expected.hex()} — "
                    f"this does not look like the {self.binary} this patch targets"
                )


class MultiInstancePatch(_MutexGuardPatch):
    """Let `game.dat` start while another copy of it is already running."""

    name = "multi-instance"
    author = "officialNecro"
    description = (
        "Remove game.dat's one-instance-at-a-time limit: the silent WinMain abort and the wait "
        "loop that asks the running copy to quit. Needs multi-instance-launcher as well"
    )

    binary = "game.dat"
    guards = GAME_GUARDS
    fingerprint = GAME_FINGERPRINT


class MultiInstanceLauncherPatch(_MutexGuardPatch):
    """Stop the launcher shim refusing with `Launcher:GameRunning`."""

    name = "multi-instance-launcher"
    author = "officialNecro"
    description = (
        "lotrbfme2ep1.exe (not game.dat): remove the 'game is already running' refusal, so the "
        "shim launches game.dat instead. Pair with multi-instance"
    )

    binary = "lotrbfme2ep1.exe"
    guards = LAUNCHER_GUARDS
    fingerprint = LAUNCHER_FINGERPRINT
