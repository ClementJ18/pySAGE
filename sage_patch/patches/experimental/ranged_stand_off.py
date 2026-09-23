"""Let a ranged unit ordered to attack a target stop at weapon range instead of walking onto it.

The attack-approach state may end on range only when its move goal is a position; for an object goal
it walks to contact. Three bytes: the `sete al` becomes `mov al, 1`. Melee stays melee through the
engine's own `MeleeWeapon` test, so a melee weapon that leaves `MeleeWeapon` unset now stops at its
`AttackRange`.

Derivation: `../../docs/ranged-approach-overshoot.md`.
"""

from __future__ import annotations

from ...addresses import ATTACK_APPROACH_MAY_STOP_GATE
from ...patcher import Patch
from ...utils import apply_byte_patch, file_offset

__all__ = ["ANCHORS", "MAY_STOP_SETE_VA", "PATCHED_BYTES", "RangedStandOffPatch", "STOCK_BYTES"]

#: The `sete al` inside the gate at `ATTACK_APPROACH_MAY_STOP_GATE` - the three bytes that
#: turn "the goal is a position" into "this state may end because the target is in range".
MAY_STOP_SETE_VA = ATTACK_APPROACH_MAY_STOP_GATE + 7

STOCK_BYTES = bytes.fromhex("0f94c0")  # sete al
PATCHED_BYTES = bytes.fromhex("b00190")  # mov al, 1 ; nop

#: Sites asserted but not rewritten, so a build that happens to carry a `sete al` here cannot be
#: mistaken for this one. In order: the `cmp` the `sete` reads, which fixes the offset the gate
#: consults; the blocked-wait override and the store into the state byte; the `MeleeWeapon` clear
#: that keeps melee closing; the in-range exit this unblocks; the no-victim arm's copy of the same
#: read; and the `setGoalObject` stamp that makes the flag one in the first place.
ANCHORS = {
    ATTACK_APPROACH_MAY_STOP_GATE: bytes.fromhex("80bfb203000000"),
    0x00749D8D: bytes.fromhex("807e710088466e7404c6466e01"),
    0x00749DBE: bytes.fromhex("8b4804e8937dcfff84c07404c6466e00"),
    0x00749F1A: bytes.fromhex("807e6e00742b837df8007425807dfe00"),
    0x0074A231: bytes.fromhex("807e6e00744d8b4df885c9"),
    0x00749C8D: bytes.fromhex("e8709bf1ff"),
    0x00663872: bytes.fromhex("c683b203000001"),
}


class RangedStandOffPatch(Patch):
    """End the attack approach when the target is in weapon range, not when the unit reaches it."""

    name = "ranged-stand-off"
    author = "officialNecro"
    experimental = True
    description = (
        "Ranged units given a direct attack order stop as soon as the target is in weapon range "
        "instead of closing to contact first, by letting the attack-approach state end on range "
        "when its move goal is an object. Needs no INI change, but melee stays melee only through "
        "the engine's existing MeleeWeapon test, so a melee Weapon that leaves MeleeWeapon unset "
        "(it defaults to No) will now stop at its own AttackRange instead of walking to contact"
    )

    def apply(self, data: bytearray) -> None:
        self._check_anchors(data)
        apply_byte_patch(
            data,
            file_offset(data, MAY_STOP_SETE_VA),
            STOCK_BYTES,
            PATCHED_BYTES,
            f"attack-approach may-stop gate @0x{MAY_STOP_SETE_VA:08x}",
        )

    def verify(self, data: bytes | bytearray) -> list[str]:
        try:
            off = file_offset(data, MAY_STOP_SETE_VA)
        except ValueError as exc:
            return [str(exc)]
        got = bytes(data[off : off + len(PATCHED_BYTES)])
        if got == PATCHED_BYTES:
            return []
        if got == STOCK_BYTES:
            return [f"the may-stop gate @0x{MAY_STOP_SETE_VA:08x} is unpatched"]
        return [
            f"the may-stop gate @0x{MAY_STOP_SETE_VA:08x} is {got.hex()}, expected "
            f"{PATCHED_BYTES.hex()} (patched) or {STOCK_BYTES.hex()} (stock)"
        ]

    @staticmethod
    def _check_anchors(data: bytes | bytearray) -> None:
        for va, expected in ANCHORS.items():
            off = file_offset(data, va)
            got = bytes(data[off : off + len(expected)])
            if got != expected:
                raise ValueError(
                    f"unexpected build: 0x{va:08x} is {got.hex()}, expected {expected.hex()} - "
                    "this is not the game.dat these addresses were read from"
                )
