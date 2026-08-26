"""The attack-requires-damage patch: a unit only auto-acquires / right-click-attacks a target one
of its weapon's nuggets can actually damage.

Targets the ROTWK SAGE-engine `game.dat` build ``2.01.2614.37001``. Every address below is derived
in ``../docs/attack-requires-damage.md``.

**The defect.** Whether object A can attack object B ends, for auto-acquire and for a right-click /
attack order, in ``WEAPON_ANY_NUGGET_VALID_VICTIM`` (`0x006CB779`): it walks the weapon's nugget
vector and answers yes if **any** nugget's per-victim test (`NUGGET_VTBL_VALID_VICTIM`) accepts the
target - with no regard for whether that nugget deals damage. So a weapon whose only matching nugget
is a knockback (`MetaImpactNugget`) or an `AttributeModifierNugget` reports itself able to attack a
target it cannot hurt, and the unit walks up and "attacks" for no damage. Players report this as a
bug.

**What this does.** Redirects the one ``call WEAPON_ANY_NUGGET_VALID_VICTIM`` at
``ATTACK_ELIGIBILITY_NUGGET_CALL`` (`0x006CDCD1`) - the final answer of the attack-eligibility
predicate `0x006CDBF3`, which every acquire / attack-move / right-click path reaches - into an
appended cave that repeats the same nugget walk but counts a nugget only when it both accepts the
victim **and** is one of the eight nugget kinds that are a reason to attack at all
(``ATTACK_NUGGET_VTABLES``): `DamageNugget`, `ProjectileNugget`, `DOTNugget`,
`DamageContainedNugget`, `DamageFieldNugget`, `GrabNugget`, `HordeAttackNugget` and
`SlaveAttackNugget`. The kind test is a vtable compare, not a call.

**Why an allowlist and not the engine's own damage getters.** The obvious implementation asks
``NUGGET_VTBL_DEALS_DAMAGE`` (`+0x1c`) or ``NUGGET_VTBL_SUBWEAPON`` (`+0x2c`), and it gets the
answer wrong in both directions. `AttributeModifierNugget`, `ParalyzeNugget`, `FireLogicNugget`
and `EmotionWeaponNugget` all return `mov al,1` from `+0x1c` while being no reason to walk up to
anything - so the very nugget this patch is named for was never actually excluded by it. And
`HordeAttackNugget`, `SlaveAttackNugget`, `DamageFieldNugget` and `GrabNugget` answer false to
`+0x1c` *and* NULL to `+0x2c` while being exactly how their weapon hurts the target. The worst
of those is `HordeAttackNugget`: a horde acquires with a rangefinder weapon that carries it as
its only nugget, so on the getters alone every horde in the game reports itself unable to attack
anything at all. Nothing in the vtable separates the two groups, so they are named.

**Firing is untouched.** The two other callers of `0x006CB779` (`0x0090F527`, `0x0090F97E`) are
sub-weapon nuggets' own valid-victim methods, used while the weapon is firing; they keep the stock
answer. So a knockback still knocks back once the weapon is engaged on a legitimately damageable
enemy - it just no longer causes the engagement on its own.

**Every peer must run the same patched binary.** This changes which targets a logic-side order
reaches, so a patched and an unpatched client diverge on the first acquire of a
damage-less-weapon's target, and replays do not cross - the same requirement `multi-execute-gate`
and `spawn-union` carry. There is **no INI change**: the filter is global and reads only data every
weapon already has.

**Composition.** Order-independent: the cave is allocated past every existing section and
:meth:`verify` finds it by name. The only engine bytes it edits are the five at
``ATTACK_ELIGIBILITY_NUGGET_CALL``, which no other bundled patch touches.

**Statically verified, not runtime-verified.**
"""

from __future__ import annotations

import struct

from ..addresses import (
    ATTACK_ELIGIBILITY_NUGGET_CALL,
    ATTACK_ELIGIBILITY_NUGGET_CALL_WINDOW,
    ATTACK_ELIGIBILITY_NUGGET_CALL_WINDOW_BYTES,
    ATTACK_NUGGET_VTABLE_STORES,
    ATTACK_NUGGET_VTABLES,
    NUGGET_VTBL_VALID_VICTIM,
    WEAPON_ANY_NUGGET_VALID_VICTIM,
    WEAPON_ANY_NUGGET_VALID_VICTIM_BYTES,
    WEAPONTEMPLATE_NUGGET_VECTOR_OFFSET,
)
from ..asm import JE, JNE, Asm
from ..patcher import Patch
from ..utils import allocate_section, apply_byte_patch, find_section, va_to_offset

__all__ = [
    "ANCHORS",
    "ATTACK_VTABLES",
    "CALL_VA",
    "SECTION_NAME",
    "AttackRequiresDamagePatch",
    "build_cave",
]

SECTION_NAME = ".ardmg"  # <= 8 chars: the PE name field is 8 bytes and truncates silently

# IMAGE_SCN_CNT_CODE | MEM_EXECUTE | MEM_READ - the cave is pure code and is never written.
_CHARACTERISTICS = 0x20 | 0x20000000 | 0x40000000

CALL_VA = ATTACK_ELIGIBILITY_NUGGET_CALL

#: Where inside the hook window the five ``call rel32`` bytes sit - masked out when the window is
#: checked against an already-patched image, since those are the bytes this patch rewrites.
_CALL_IN_WINDOW = CALL_VA - ATTACK_ELIGIBILITY_NUGGET_CALL_WINDOW

#: Everything the cave depends on and does not rewrite: the stock head of the routine it
#: replicates, and the constructor store that identifies each allowlisted nugget's vtable. A
#: build that laid any of them out differently fails here instead of on a wrong answer in game.
ANCHORS = {
    WEAPON_ANY_NUGGET_VALID_VICTIM: WEAPON_ANY_NUGGET_VALID_VICTIM_BYTES,
    **ATTACK_NUGGET_VTABLE_STORES,
}

#: The vtables the cave compares against, in the order it emits them.
ATTACK_VTABLES = tuple(ATTACK_NUGGET_VTABLES.values())


def _call_bytes(from_va: int, to_va: int) -> bytes:
    """The five bytes of ``call rel32`` sited at ``from_va``."""
    return b"\xe8" + struct.pack("<i", to_va - (from_va + 5))


def build_cave(base_va: int) -> bytes:
    """``bool cave(WeaponTemplate *this, Object *victim, Weapon *weapon)`` - ``__thiscall``,
    ``ret 8``, an allowlist-filtered replica of ``WEAPON_ANY_NUGGET_VALID_VICTIM``.

    Walks the nugget vector exactly as the stock routine does and returns TRUE on the first nugget
    that is one of ``ATTACK_VTABLES`` **and** accepts the victim (`NUGGET_VTBL_VALID_VICTIM`). The
    kind test is a vtable compare rather than a call, so the only engine code the cave reaches is
    the one valid-victim method the stock routine already called - and it is reached for a strict
    subset of the nuggets, so nothing is asked a question it was not already asked. That method is
    a ``__thiscall`` getter preserving ``ebx``/``esi``/``edi``/``ebp``, so the `WeaponTemplate`
    (``edi``) and the current list node (``esi``) live in registers across the walk; the victim and
    weapon are read from the frame.
    """
    disp = struct.pack("<I", WEAPONTEMPLATE_NUGGET_VECTOR_OFFSET)
    a = Asm(base_va)
    a.emit(0x55)  # push ebp
    a.emit(b"\x8b\xec")  # mov ebp, esp
    a.emit(0x56, 0x57)  # push esi / push edi
    a.emit(b"\x8b\xf9")  # mov edi, ecx            ; WeaponTemplate
    a.emit(b"\x8b\x45\x08")  # mov eax, [ebp+8]        ; victim
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc(JE, "ret0")  # je .ret0                ; no victim -> 0, as stock
    a.emit(b"\x8b\x87", disp)  # mov eax, [edi+0x17c]    ; &nugget list head (sentinel)
    a.emit(b"\x8b\x30")  # mov esi, [eax]          ; first node
    a.emit(b"\x3b\xf0")  # cmp esi, eax
    a.jcc(JE, "ret0")  # je .ret0                ; empty list -> 0

    a.label("loop")
    a.emit(b"\x8b\x4e\x08")  # mov ecx, [esi+8]        ; the nugget
    a.emit(b"\x8b\x01")  # mov eax, [ecx]          ; nugget vtable
    for vtable in ATTACK_VTABLES:
        a.emit(0x3D, struct.pack("<I", vtable))  # cmp eax, <nugget vtable>
        a.jcc(JE, "valid")  # je .valid
    a.jmp("next")  # jmp .next               ; not a kind of nugget worth attacking for

    # An allowlisted nugget: does it accept this victim? (the stock question, unchanged -
    # victim pushed first then weapon, so the callee sees them in the order the stock routine
    # handed them.)
    a.label("valid")
    a.emit(b"\xff\x75\x08")  # push dword [ebp+8]      ; victim
    a.emit(b"\x8b\x4e\x08")  # mov ecx, [esi+8]        ; nugget = this
    a.emit(b"\xff\x75\x0c")  # push dword [ebp+0xc]    ; weapon
    a.emit(b"\x8b\x01")  # mov eax, [ecx]
    a.emit(b"\xff\x50", NUGGET_VTBL_VALID_VICTIM)  # call [eax+0x04] ; valid victim? (ret 8)
    a.emit(b"\x84\xc0")  # test al, al
    a.jcc(JNE, "ret1")  # jne .ret1               ; allowlisted AND accepts -> 1

    a.label("next")
    a.emit(b"\x8b\x36")  # mov esi, [esi]          ; next node
    a.emit(b"\x3b\xb7", disp)  # cmp esi, [edi+0x17c]
    a.jcc(JNE, "loop")  # jne .loop

    a.label("ret0")
    a.emit(b"\x32\xc0")  # xor al, al
    a.jmp_short("done")

    a.label("ret1")
    a.emit(b"\xb0\x01")  # mov al, 1

    a.label("done")
    a.emit(0x5F, 0x5E, 0x5D)  # pop edi / pop esi / pop ebp
    a.emit(0xC2, struct.pack("<H", 8))  # ret 8
    return a.finish()


class AttackRequiresDamagePatch(Patch):
    name = "attack-requires-damage"
    author = "officialNecro"
    description = (
        "A unit only auto-acquires or right-click-attacks a target its weapon can actually "
        "do something to: one of its nuggets must be a damage, projectile, DOT, "
        "damage-contained, damage-field, grab, horde-attack or slave-attack nugget. A "
        "knockback-, attribute-modifier-, paralyze- or emotion-only weapon no longer picks "
        "victims it cannot hurt. Weapon firing and effects are unchanged. No INI change"
    )

    def apply(self, data: bytearray) -> None:
        call_off = va_to_offset(data, CALL_VA)
        if call_off is None:
            raise ValueError(f"{CALL_VA:#010x} is not mapped - not the expected build")
        self._check_anchors(data)
        section_va = allocate_section(data, SECTION_NAME, build_cave, _CHARACTERISTICS)
        apply_byte_patch(
            data,
            call_off,
            _call_bytes(CALL_VA, WEAPON_ANY_NUGGET_VALID_VICTIM),
            _call_bytes(CALL_VA, section_va),
            "attack-eligibility nugget check -> attack-requires-damage cave",
        )

    def verify(self, data: bytes | bytearray) -> list[str]:
        problems: list[str] = []
        located = find_section(data, SECTION_NAME)
        if located is None:
            return [f"{SECTION_NAME} section is absent"]
        section_va, section_off, _ = located

        off = va_to_offset(data, CALL_VA)
        if off is None:
            return [f"{CALL_VA:#010x} is not mapped by any section"]
        if data[off] != 0xE8:
            return [f"{CALL_VA:#010x} is not a call - the hook is not installed"]
        target = CALL_VA + 5 + struct.unpack_from("<i", data, off + 1)[0]
        if target != section_va:
            problems.append(f"hook calls {target:#010x}, expected the cave at {section_va:#010x}")

        cave = build_cave(section_va)
        if bytes(data[section_off : section_off + len(cave)]) != cave:
            problems.append(
                f"the {SECTION_NAME} cave does not hold the expected damage-filtered walk"
            )

        problems += self._anchor_problems(data)
        return problems

    # --- anchors -----------------------------------------------------------------------------

    def _anchor_problems(self, data: bytes | bytearray) -> list[str]:
        """Everything checked identically stock and patched: the framing of the hooked call (its
        five call bytes masked, since those are what the patch rewrites) and the fixed anchors."""
        problems: list[str] = []

        off = va_to_offset(data, ATTACK_ELIGIBILITY_NUGGET_CALL_WINDOW)
        if off is None:
            problems.append(f"{ATTACK_ELIGIBILITY_NUGGET_CALL_WINDOW:#010x} is not mapped")
        else:
            want = bytearray(ATTACK_ELIGIBILITY_NUGGET_CALL_WINDOW_BYTES)
            got = bytearray(data[off : off + len(want)])
            want[_CALL_IN_WINDOW : _CALL_IN_WINDOW + 5] = b"\x00" * 5
            got[_CALL_IN_WINDOW : _CALL_IN_WINDOW + 5] = b"\x00" * 5
            if bytes(got) != bytes(want):
                where = ATTACK_ELIGIBILITY_NUGGET_CALL_WINDOW
                problems.append(
                    f"the attack-eligibility call framing @0x{where:08x} is not this build's: "
                    f"expected {bytes(want).hex()}, got {bytes(got).hex()}"
                )

        for va, expected in ANCHORS.items():
            aoff = va_to_offset(data, va)
            if aoff is None:
                problems.append(f"{va:#010x} is not mapped")
                continue
            here = bytes(data[aoff : aoff + len(expected)])
            if here != expected:
                problems.append(f"{va:#010x} holds {here.hex()}, expected {expected.hex()}")
        return problems

    def _check_anchors(self, data: bytes | bytearray) -> None:
        problems = self._anchor_problems(data)
        if problems:
            raise ValueError(
                "this is not the expected build (the attack-eligibility nugget check moved): "
                + "; ".join(problems)
            )
