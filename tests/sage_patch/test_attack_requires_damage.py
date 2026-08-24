"""Tests for the attack-requires-damage patch.

The cave is hand-assembled x86 that cannot be executed here, so the tests that matter disassemble it
back and assert it says what it was meant to say: it walks the weapon's nugget vector, and counts a
nugget only when it both accepts the victim (`+0x04`) and deals damage (`+0x1c`, or a sub-weapon at
`+0x2c`). Getting the damage gate wrong does not raise - it would either leave the bug in place or
stop units attacking anything at all.
"""

from __future__ import annotations

import struct

import pytest

from sage_patch.addresses import (
    ATTACK_ELIGIBILITY_NUGGET_CALL_WINDOW,
    ATTACK_ELIGIBILITY_NUGGET_CALL_WINDOW_BYTES,
    NUGGET_VTBL_DEALS_DAMAGE,
    NUGGET_VTBL_SUBWEAPON,
    NUGGET_VTBL_VALID_VICTIM,
    WEAPON_ANY_NUGGET_VALID_VICTIM,
    WEAPON_ANY_NUGGET_VALID_VICTIM_BYTES,
    WEAPONTEMPLATE_NUGGET_VECTOR_OFFSET,
)
from sage_patch.patches.attack_requires_damage import (
    ANCHORS,
    CALL_VA,
    SECTION_NAME,
    AttackRequiresDamagePatch,
    build_cave,
)
from sage_patch.registry import PATCHES
from sage_patch.utils import find_section, va_to_offset

BASE = 0x00F00000
IMAGE_BASE = 0x400000


def synthetic_image() -> bytearray:
    """A PE32 image big enough to map the hook window and every anchor, with the real stock bytes
    planted, so apply + verify run without the copyrighted `game.dat`."""
    vas = [
        ATTACK_ELIGIBILITY_NUGGET_CALL_WINDOW + len(ATTACK_ELIGIBILITY_NUGGET_CALL_WINDOW_BYTES),
        *(va + len(b) for va, b in ANCHORS.items()),
    ]
    highest = max(vas) - IMAGE_BASE + 0x100
    data = bytearray(((highest + 0x400) // 0x200 + 1) * 0x200)

    data[0:2] = b"MZ"
    e = 0x80
    struct.pack_into("<I", data, 0x3C, e)
    data[e : e + 4] = b"PE\x00\x00"
    struct.pack_into("<H", data, e + 4, 0x14C)  # Machine (i386)
    struct.pack_into("<H", data, e + 6, 1)  # NumberOfSections
    struct.pack_into("<H", data, e + 20, 0xE0)  # SizeOfOptionalHeader
    opt = e + 24
    struct.pack_into("<H", data, opt, 0x10B)  # PE32 magic
    struct.pack_into("<I", data, opt + 28, IMAGE_BASE)
    struct.pack_into("<I", data, opt + 32, 0x1000)  # SectionAlignment
    struct.pack_into("<I", data, opt + 36, 0x200)  # FileAlignment
    struct.pack_into("<I", data, opt + 56, 0x2000000)  # SizeOfImage
    struct.pack_into("<I", data, opt + 60, 0x400)  # SizeOfHeaders, room for a 2nd header
    header = bytearray(40)
    header[0:8] = b".text\x00\x00\x00"
    size = len(data) - 0x1000
    struct.pack_into("<IIII", header, 8, size, 0x1000, size, 0x1000)
    data[opt + 0xE0 : opt + 0xE0 + 40] = header

    def plant(va: int, b: bytes) -> None:
        data[va - IMAGE_BASE : va - IMAGE_BASE + len(b)] = b

    plant(ATTACK_ELIGIBILITY_NUGGET_CALL_WINDOW, ATTACK_ELIGIBILITY_NUGGET_CALL_WINDOW_BYTES)
    for va, expected in ANCHORS.items():
        plant(va, expected)
    return data


def disassemble(base: int = BASE):
    capstone = pytest.importorskip("capstone")
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    md.detail = True
    return list(md.disasm(build_cave(base), base))


class TestTheHookSite:
    def test_the_stock_call_targets_the_nugget_check(self):
        """Decoded from the planted window rather than written down: the call this patch rewrites
        really does reach `WEAPON_ANY_NUGGET_VALID_VICTIM`."""
        window = ATTACK_ELIGIBILITY_NUGGET_CALL_WINDOW_BYTES
        at = CALL_VA - ATTACK_ELIGIBILITY_NUGGET_CALL_WINDOW
        assert window[at] == 0xE8
        target = CALL_VA + 5 + struct.unpack_from("<i", window, at + 1)[0]
        assert target == WEAPON_ANY_NUGGET_VALID_VICTIM

    def test_the_replicated_routine_head_is_planted(self):
        assert ANCHORS[WEAPON_ANY_NUGGET_VALID_VICTIM] == WEAPON_ANY_NUGGET_VALID_VICTIM_BYTES


class TestTheCave:
    def test_it_disassembles_cleanly_to_its_end(self):
        """Capstone stopping early means an invalid encoding, which would be a crash in-game."""
        insns = disassemble()
        assert sum(i.size for i in insns) == len(build_cave(BASE))

    def test_it_walks_the_nugget_vector(self):
        """The same vector offset the stock routine walks, so the filtered walk visits every
        nugget the unfiltered one did."""
        insns = disassemble()
        want = f"esi, dword ptr [edi + {WEAPONTEMPLATE_NUGGET_VECTOR_OFFSET:#x}]"
        assert any(i.mnemonic == "cmp" and i.op_str == want for i in insns)

    def test_it_asks_the_damage_discriminator_before_accepting(self):
        """Both damage questions the engine itself uses: direct damage (`+0x1c`) and a damaging
        sub-weapon (`+0x2c`). Dropping either would exclude a whole class of real weapons."""
        calls = [i.op_str for i in disassemble() if i.mnemonic == "call"]
        assert f"dword ptr [eax + {NUGGET_VTBL_DEALS_DAMAGE:#x}]" in calls
        assert f"dword ptr [eax + {NUGGET_VTBL_SUBWEAPON:#x}]" in calls

    def test_it_still_asks_the_stock_valid_victim_question(self):
        """The damage gate is added to the acceptance test, not a replacement for it."""
        calls = [i.op_str for i in disassemble() if i.mnemonic == "call"]
        assert f"dword ptr [eax + {NUGGET_VTBL_VALID_VICTIM:d}]" in calls

    def test_it_calls_no_engine_address(self):
        """Every call is an indirect vtable call; the cave hardcodes no engine VA, so it is immune
        to anything another patch relocates."""
        assert all("[" in i.op_str for i in disassemble() if i.mnemonic == "call")

    def test_it_returns_stdcall_with_two_args(self):
        """`ret 8` - the same frame `WEAPON_ANY_NUGGET_VALID_VICTIM` cleans, so the redirected call
        site is balanced."""
        last = disassemble()[-1]
        assert (last.mnemonic, last.op_str) == ("ret", "8")


class TestApply:
    def test_apply_then_verify(self):
        data = synthetic_image()
        AttackRequiresDamagePatch().apply(data)
        assert AttackRequiresDamagePatch().verify(data) == []

    def test_a_stock_image_does_not_verify(self):
        assert AttackRequiresDamagePatch().verify(synthetic_image())

    def test_the_call_is_redirected_to_the_cave(self):
        data = synthetic_image()
        AttackRequiresDamagePatch().apply(data)
        located = find_section(data, SECTION_NAME)
        assert located is not None
        off = va_to_offset(data, CALL_VA)
        assert data[off] == 0xE8
        assert CALL_VA + 5 + struct.unpack_from("<i", data, off + 1)[0] == located[0]

    def test_it_touches_nothing_but_the_call(self):
        before = synthetic_image()
        data = synthetic_image()
        AttackRequiresDamagePatch().apply(data)
        call = va_to_offset(before, CALL_VA)
        changed = [
            i for i in range(len(before)) if before[i] != data[i] and not call <= i < call + 5
        ]
        located = find_section(data, SECTION_NAME)
        assert located is not None
        # only the PE header (a new section) and the appended cave itself
        assert all(i < 0x400 or i >= located[1] for i in changed)

    def test_refuses_to_apply_twice(self):
        data = synthetic_image()
        AttackRequiresDamagePatch().apply(data)
        with pytest.raises(ValueError):
            AttackRequiresDamagePatch().apply(data)


class TestTheAnchors:
    @pytest.mark.parametrize("va", sorted(ANCHORS))
    def test_a_moved_anchor_refuses_to_apply(self, va: int):
        data = synthetic_image()
        off = va_to_offset(data, va)
        assert off is not None
        data[off] ^= 0xFF
        with pytest.raises(ValueError):
            AttackRequiresDamagePatch().apply(data)

    def test_a_moved_anchor_leaves_the_call_alone(self):
        data = synthetic_image()
        off = va_to_offset(data, WEAPON_ANY_NUGGET_VALID_VICTIM)
        assert off is not None
        data[off] ^= 0xFF
        with pytest.raises(ValueError):
            AttackRequiresDamagePatch().apply(data)
        call = va_to_offset(data, CALL_VA)
        assert data[call] == 0xE8  # the stock call is untouched

    def test_a_changed_call_framing_refuses_to_apply(self):
        """A byte of the window outside the call itself moving means the hook is not the predicate's
        tail on this build."""
        data = synthetic_image()
        off = va_to_offset(data, ATTACK_ELIGIBILITY_NUGGET_CALL_WINDOW)
        assert off is not None
        data[off] ^= 0xFF  # the `mov ecx,[ebx+4]` ahead of the call
        with pytest.raises(ValueError):
            AttackRequiresDamagePatch().apply(data)


class TestRegistration:
    def test_it_is_offered_on_the_cli(self):
        assert PATCHES[AttackRequiresDamagePatch.name] is AttackRequiresDamagePatch

    def test_detect_finds_it_only_once_applied(self):
        data = synthetic_image()
        assert AttackRequiresDamagePatch.detect(data) is None
        AttackRequiresDamagePatch().apply(data)
        assert AttackRequiresDamagePatch.detect(data) is not None

    def test_the_description_promises_firing_is_unchanged(self):
        assert "firing and effects are unchanged" in AttackRequiresDamagePatch.description
