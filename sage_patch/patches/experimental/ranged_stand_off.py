"""Let a ranged unit ordered to attack a target stop at weapon range instead of walking onto it.

Targets the ROTWK SAGE-engine `game.dat` build ``2.01.2614.37001``. Every address below is derived
in ``../../docs/ranged-approach-overshoot.md``.

**The premise.** `AIAttackApproachTargetState` has an exit that ends the approach because the
target is in weapon range (``0x00749F1A``), and a state byte at ``+0x6E`` that gates it. The state
derives that byte at the top of every update from `AIUpdateInterface`'s "the current move goal is
an object" flag at ``+0x3B2``::

    00749d83  cmp  byte ptr [edi+0x3b2], 0
    00749d8a  sete al                        ; only a *position* goal may stop at range
    00749d8d  cmp  byte ptr [esi+0x71], 0
    00749d91  mov  byte ptr [esi+0x6e], al

and its own `computePath` ends an ordinary attack order by calling `setGoalObject`
(``0x00749C8D`` -> ``0x00663802``), which stamps that flag with 1. So the state guarantees the
byte is zero, the range exit is unreachable, and the unit follows a path whose destination is the
target's body until the locomotor runs out of path.

**What this does.** Replaces the `sete al` with `mov al, 1`, so an object goal is allowed to stop
at range too. Three bytes, one site, and nothing else in the image changes - in particular the
``+0x3B2`` flag itself is untouched, so its only other reader (``0x00669049``) is unaffected.

**Melee is unchanged, by the engine's own hand.** Twelve bytes further on, the state clears the
same byte for a melee weapon::

    00749dbe  mov  ecx, dword ptr [eax+4]   ; the WeaponTemplate
    00749dc1  call 0x00441b59               ; template->[+0x125], i.e. MeleeWeapon
    00749dc8  je   0x00749dce
    00749dca  mov  byte ptr [esi+0x6e], 0

That runs after the patched instruction, so `MeleeWeapon = Yes` still closes to contact. The
engine already drew this distinction and then handed ranged weapons the melee behaviour anyway;
this makes the distinction reach the range exit.

**What a mod has to get right.** `MeleeWeapon` defaults to `No`, so a genuinely melee weapon that
leaves it unset now stops as soon as it is inside its own `AttackRange` rather than walking to
contact. For a melee weapon that range *is* roughly contact distance, so the visible change is
small, but it is real and it is data-dependent. Declaring `MeleeWeapon = Yes` on melee weapons is
the fix, and it is what the stock data already does in the large majority of cases.

**The second exit this reaches.** The byte also gates a range check in the state's no-victim-object
arm (``0x0074A231``), which tests the goal *position* against weapon range. That arm serves an
attack order on ground rather than on a unit, and it is dead today for the same reason. It comes
alive here, which is the same fix applied to the same mistake.

**Not covered.** `AIAttackPursueTargetState` (``0x0074AF91``, `computePath` at ``0x00746C69``) is a
separate state with its own logic; it sets a *position* goal and never reads ``+0x3B2``, so this
patch neither helps nor harms it. Whether pursuit overshoots for its own reasons has not been
looked at.
"""

from __future__ import annotations

from ...addresses import ATTACK_APPROACH_MAY_STOP_GATE
from ...patcher import Patch
from ...utils import apply_byte_patch, va_to_offset

__all__ = ["ANCHORS", "MAY_STOP_SETE_VA", "PATCHED_BYTES", "RangedStandOffPatch", "STOCK_BYTES"]

#: The `sete al` inside the gate at :data:`ATTACK_APPROACH_MAY_STOP_GATE` - the three bytes that
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


def _offset(data: bytes | bytearray, va: int) -> int:
    off = va_to_offset(data, va)
    if off is None:
        raise ValueError(f"VA 0x{va:08x} is not mapped - not the expected build")
    return off


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
            _offset(data, MAY_STOP_SETE_VA),
            STOCK_BYTES,
            PATCHED_BYTES,
            f"attack-approach may-stop gate @0x{MAY_STOP_SETE_VA:08x}",
        )

    def verify(self, data: bytes | bytearray) -> list[str]:
        try:
            off = _offset(data, MAY_STOP_SETE_VA)
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
            off = _offset(data, va)
            got = bytes(data[off : off + len(expected)])
            if got != expected:
                raise ValueError(
                    f"unexpected build: 0x{va:08x} is {got.hex()}, expected {expected.hex()} - "
                    "this is not the game.dat these addresses were read from"
                )
