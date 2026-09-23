"""Run more than one copy of the game at once.

Three single-instance gates (WinMain's silent abort, the loop asking the running copy to quit, and
the LAN host's same-serial refusal) each test `CreateMutex` for `ERROR_ALREADY_EXISTS`. Each
conditional branch becomes a `jmp`, leaving the mutex calls themselves in place. The third removes a
licence check, so this belongs in a development build. `MultiInstanceLauncherPatch` removes the
launcher's own refusal and is needed as well.

Derivation: `../docs/multi-instance.md`.
"""

from __future__ import annotations

from typing import NamedTuple

from ..patcher import Patch
from ..utils import apply_byte_patch, file_offset, va_to_offset

__all__ = [
    "GAME_FINGERPRINT",
    "GAME_GUARDS",
    "LAUNCHER_FINGERPRINT",
    "LAUNCHER_GUARDS",
    "Guard",
    "MultiInstanceLauncherPatch",
    "MultiInstancePatch",
]

#: The one-byte encoding of `jmp rel8`, which an always-taken guard's conditional jump becomes.
JMP_SHORT = 0xEB
#: What a never-taken guard's conditional jump becomes instead, both bytes of it.
NOP = 0x90


class Guard(NamedTuple):
    """One conditional branch to defuse.

    `va` addresses `run_up`, not the jump: asserting the instructions that compute the
    condition alongside the jump is what stops a two-byte `75 xx` somewhere else in a different
    build from being mistaken for this site. `opcode` and `displacement` are the stock ``jcc
    rel8``.

    Two shapes, because the gates are not all the same shape. Where the branch **skips** a refusal,
    `always_taken` leaves the displacement alone and rewrites only the opcode, so the branch keeps
    its target and its length and the patched path is one the stock binary already takes. Where the
    branch **is** the refusal, there is no such path to force: the jump is replaced by two `nop`
    and control falls into the instruction after it, which is where the non-refusing case already
    went.
    """

    va: int
    run_up: bytes
    opcode: int
    displacement: int
    note: str
    always_taken: bool = True

    @property
    def stock(self) -> bytes:
        return self.run_up + bytes((self.opcode, self.displacement))

    @property
    def patched(self) -> bytes:
        if self.always_taken:
            return self.run_up + bytes((JMP_SHORT, self.displacement))
        return self.run_up + bytes((NOP, NOP))


#: `cmp eax, 0xB7` - the `GetLastError` test all three gates share, and the run-up asserted
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
    Guard(
        va=0x0098AA8C,
        # The host's MSG_REQUEST_JOIN handler comparing one slot's serial with the joiner's:
        # mov ecx, [ebp+8] / push 0x17 / add ecx, 0x3a / add eax, 8 / push ecx / push eax /
        # call [msvcr71!strncmp] / add esp, 0xc / test eax, eax
        run_up=bytes.fromhex("8b4d086a1783c13a83c0085150ff156c05bd0083c40c85c0"),
        opcode=0x74,  # je 0x0098AAAE -> deny the join
        displacement=0x08,
        note="LAN duplicate-serial join deny",
        always_taken=False,
    ),
)

#: Calls that pin `GAME_GUARDS` to the code that really is the instance check, asserted
#: before anything is written. The first guard is two `cmp`-able bytes and the second is a `rel32`
#: call, neither of which is distinctive on its own.
GAME_FINGERPRINT = {
    0x00402AED: bytes.fromhex("ff157c01bd00"),  # call CreateMutexW
    0x00402AF5: bytes.fromhex("ff150802bd00"),  # call GetLastError
    0x00402B0B: bytes.fromhex("ff150409bd00"),  # call FindWindowW, in the arm being cut off
    0x0063F699: bytes.fromhex("ff151c02bd00"),  # call CreateMutexA, inside the probe
    0x00402C77: bytes.fromhex("e843ca2300"),  # call 0x0063F6BF, the wait loop itself
    # The arm the fourth guard stops reaching, and what makes that site unmistakable: `push 5`
    # into both the outgoing message type (MSG_JOIN_DENY) and the deny reason the joiner renders
    # as `WOL:ChatErrorSerialDup`.
    0x0098AAAE: bytes.fromhex("6a05588985f8fdffff898544feffff"),
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


class _MutexGuardPatch(Patch):
    """Turn each of `guards`' conditional jumps into `jmp`, once `fingerprint`
    confirms the image is the build those addresses were derived from.

    Subclasses supply the two tables and the usual `name` /
    `description`. There is nothing to parameterise, so the inherited
    `detect` - probe with the default constructor, ask `verify` -
    is already correct for both.
    """

    guards: tuple[Guard, ...] = ()
    fingerprint: dict[int, bytes] = {}
    binary: str = ""

    def apply(self, data: bytearray) -> None:
        self._check_fingerprint(data)
        for guard in self.guards:
            apply_byte_patch(
                data, file_offset(data, guard.va), guard.stock, guard.patched, guard.note
            )

    def verify(self, data: bytes | bytearray) -> list[str]:
        """Structural check that `data` carries this patch (an empty list == verified): every
        fingerprint site still reads what it should, and every guard now reads `jmp`."""
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
            off = file_offset(data, guard.va)
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
        "Remove game.dat's one-instance-at-a-time limit: the silent WinMain abort, the wait loop "
        "that asks the running copy to quit, and the LAN host's refusal to let a second client "
        "with the same serial join. That last one removes a licence check, so this belongs in a "
        "development build. Needs multi-instance-launcher as well. No INI change"
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
        "shim launches game.dat instead. Pair with multi-instance. No INI change"
    )

    binary = "lotrbfme2ep1.exe"
    guards = LAUNCHER_GUARDS
    fingerprint = LAUNCHER_FINGERPRINT
