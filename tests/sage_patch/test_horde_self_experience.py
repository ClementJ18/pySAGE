"""Tests for the horde-self-experience patch.

One six-byte hook and one cave. What could be wrong without raising is the reading behind the
hook, so the scorer around it is disassembled: the hooked call is the horde interface's
`HORDE_EXPERIENCE_ADD` slot, reached with the interface in `ecx` and `(killer, xp)` pushed.
`..._emulated.py` runs the cave.
"""

from __future__ import annotations

import pytest

from sage_patch.addresses import (
    HORDE_EXPERIENCE_ADD,
    HORDE_IFACE_EXPERIENCE_ADD_SLOT,
    HORDE_IFACE_VTABLE,
    KILL_SCORE_HORDE_EXPERIENCE_CALL,
    KILL_SCORE_HORDE_EXPERIENCE_CALL_BYTES,
)
from sage_patch.patches.horde_self_experience import (
    ANCHORS,
    SECTION_NAME,
    HordeSelfExperiencePatch,
    build_section,
    hook_bytes,
    layout,
)
from sage_patch.registry import PATCHES
from sage_patch.utils import call_rel32, find_section, va_to_offset
from tests.sage_patch.synthetic import horde_self_experience_image

BASE = 0x00F00000


def disassemble(code: bytes, base: int):
    capstone = pytest.importorskip("capstone")
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    return list(md.disasm(code, base))


def ops(code: bytes, base: int) -> list[tuple[str, str]]:
    return [(i.mnemonic, i.op_str) for i in disassemble(code, base)]


def _read(data: bytes | bytearray, va: int, n: int) -> bytes:
    off = va_to_offset(data, va)
    return bytes(data[off : off + n])


@pytest.fixture
def patched() -> bytearray:
    data = horde_self_experience_image()
    HordeSelfExperiencePatch().apply(data)
    return data


class TestTheStockWindows:
    def test_the_hooked_call_is_the_experience_slot(self):
        assert ops(KILL_SCORE_HORDE_EXPERIENCE_CALL_BYTES, KILL_SCORE_HORDE_EXPERIENCE_CALL) == [
            ("call", f"dword ptr [eax + {HORDE_IFACE_EXPERIENCE_ADD_SLOT:#x}]")
        ]

    def test_the_slot_is_horde_experience_add(self):
        """The interface vtable's `+0xC0` entry, as `explore.py ptrs` reads it."""
        assert HORDE_IFACE_VTABLE + HORDE_IFACE_EXPERIENCE_ADD_SLOT == 0x00C5B2B8
        assert HORDE_EXPERIENCE_ADD == 0x00873A02

    def test_the_call_takes_the_interface_and_killer_xp(self):
        """`edi` is the interface found from the killer `esi`; `push ecx / fstp [esp]` passes the
        xp and `push esi` the killer; `ecx = edi` for the call."""
        assert ops(ANCHORS[0x00695504], 0x00695504)[:3] == [
            ("mov", "ecx, esi"),
            ("call", "0x694bf8"),
            ("mov", "edi, eax"),
        ]
        assert ops(ANCHORS[0x0069553F], 0x0069553F) == [
            ("fld", "dword ptr [ebp + 0x10]"),
            ("mov", "eax, dword ptr [edi]"),
            ("push", "ecx"),
            ("fstp", "dword ptr [esp]"),
            ("push", "esi"),
            ("mov", "ecx, edi"),
        ]


class TestTheCave:
    def test_it_disassembles_cleanly_to_its_end(self):
        section = build_section(BASE)
        insns = disassemble(section, BASE)
        assert sum(i.size for i in insns) == len(section)
        assert (insns[-1].mnemonic, insns[-1].op_str) == ("ret", "8")

    def test_a_member_killer_tail_jumps_to_the_slot(self):
        insns = ops(build_section(BASE), BASE)
        assert insns[:5] == [
            ("mov", "eax, dword ptr [esp + 4]"),
            ("cmp", "eax, dword ptr [ecx - 0x114]"),
            ("je", hex(BASE + 0x18)),
            ("mov", "eax, dword ptr [ecx]"),
            ("jmp", f"dword ptr [eax + {HORDE_IFACE_EXPERIENCE_ADD_SLOT:#x}]"),
        ]

    def test_the_hook_calls_the_cave_and_fills_the_window(self):
        hook = hook_bytes(BASE)
        assert len(hook) == len(KILL_SCORE_HORDE_EXPERIENCE_CALL_BYTES)
        assert hook == call_rel32(KILL_SCORE_HORDE_EXPERIENCE_CALL, BASE) + b"\x90"


class TestApply:
    def test_apply_then_verify(self, patched: bytearray):
        assert HordeSelfExperiencePatch().verify(patched) == []

    def test_a_stock_image_does_not_verify(self):
        assert HordeSelfExperiencePatch().verify(horde_self_experience_image())

    def test_the_site_calls_the_cave(self, patched: bytearray):
        at = layout(find_section(patched, SECTION_NAME)[0])
        assert _read(patched, KILL_SCORE_HORDE_EXPERIENCE_CALL, 6) == (
            call_rel32(KILL_SCORE_HORDE_EXPERIENCE_CALL, at["distribute"]) + b"\x90"
        )

    def test_refuses_to_apply_twice(self, patched: bytearray):
        with pytest.raises(ValueError, match="already carries"):
            HordeSelfExperiencePatch().apply(patched)

    @pytest.mark.parametrize("va", [*sorted(ANCHORS), KILL_SCORE_HORDE_EXPERIENCE_CALL])
    def test_a_moved_site_refuses_to_apply(self, va: int):
        data = horde_self_experience_image()
        data[va_to_offset(data, va)] ^= 0xFF
        before = bytes(data)
        with pytest.raises(ValueError):
            HordeSelfExperiencePatch().apply(data)
        assert bytes(data) == before


class TestRegistration:
    def test_it_is_offered_on_the_cli(self):
        assert PATCHES[HordeSelfExperiencePatch.name] is HordeSelfExperiencePatch

    def test_detect_finds_it_only_once_applied(self, patched: bytearray):
        assert HordeSelfExperiencePatch.detect(horde_self_experience_image()) is None
        assert isinstance(HordeSelfExperiencePatch.detect(patched), HordeSelfExperiencePatch)
