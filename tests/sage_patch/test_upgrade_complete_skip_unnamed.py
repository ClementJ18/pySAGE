"""Tests for the upgrade-complete-skip-unnamed patch.

The stock window is disassembled to show it is the `TheInGameUI->message` call and nothing else,
and the cave runs under Unicorn on both paths: a named upgrade reaches `message` with the same
arguments the stock bytes passed, an unnamed one destroys the format string instead, and both
leave the stack the shape the caller's `add esp, 4` expects.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sage_patch.addresses import (
    ASCII_STRING_CHARS_OFFSET,
    IN_GAME_UI_MESSAGE_SLOT,
    THE_IN_GAME_UI,
    UNICODE_STRING_DTOR,
    UPGRADE_COMPLETE_MESSAGE,
    UPGRADE_COMPLETE_MESSAGE_BYTES,
    UPGRADE_COMPLETE_MESSAGE_RESUME,
    UPGRADE_TEMPLATE_DISPLAY_NAME,
)
from sage_patch.patches.upgrade_complete_skip_unnamed import (
    ANCHORS,
    SECTION_NAME,
    UpgradeCompleteSkipUnnamedPatch,
    build_section,
    replacement,
)
from sage_patch.registry import PATCHES
from sage_patch.utils import find_section, va_to_offset
from tests.sage_patch.synthetic import upgrade_complete_skip_unnamed_image

REAL_GAME_DAT = Path(__file__).resolve().parents[2] / "game.dat"
BASE = 0x00F00000


def ops(code: bytes, base: int) -> list[tuple[str, str]]:
    capstone = pytest.importorskip("capstone")
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    return [(i.mnemonic, i.op_str) for i in md.disasm(code, base)]


@pytest.fixture
def patched() -> bytearray:
    data = upgrade_complete_skip_unnamed_image()
    UpgradeCompleteSkipUnnamedPatch().apply(data)
    return data


class TestTheStockWindow:
    def test_it_is_the_message_call_and_nothing_else(self):
        assert ops(UPGRADE_COMPLETE_MESSAGE_BYTES, UPGRADE_COMPLETE_MESSAGE) == [
            ("mov", f"eax, dword ptr [{THE_IN_GAME_UI:#x}]"),
            ("mov", "ecx, dword ptr [eax]"),
            ("push", "eax"),
            ("call", f"dword ptr [ecx + {IN_GAME_UI_MESSAGE_SLOT:#x}]"),
        ]
        assert UPGRADE_COMPLETE_MESSAGE + len(UPGRADE_COMPLETE_MESSAGE_BYTES) == (
            UPGRADE_COMPLETE_MESSAGE_RESUME
        )

    def test_the_replacement_is_a_call_then_nops_of_the_same_length(self):
        new = replacement(BASE)
        assert len(new) == len(UPGRADE_COMPLETE_MESSAGE_BYTES)
        insns = ops(new, UPGRADE_COMPLETE_MESSAGE)
        assert insns[0] == ("call", hex(BASE))
        assert {m for m, _ in insns[1:]} == {"nop"}

    def test_the_cave_reads_the_display_name_and_disassembles_cleanly(self):
        insns = ops(build_section(BASE), BASE)
        assert insns[0] == ("mov", f"eax, dword ptr [edi + {UPGRADE_TEMPLATE_DISPLAY_NAME:#x}]")
        assert ("cmp", f"byte ptr [eax + {ASCII_STRING_CHARS_OFFSET}], 0") in insns
        assert ("jmp", f"dword ptr [ecx + {IN_GAME_UI_MESSAGE_SLOT:#x}]") in insns
        assert ("call", hex(UNICODE_STRING_DTOR)) in insns


class TestApply:
    def test_apply_then_verify(self, patched: bytearray):
        assert UpgradeCompleteSkipUnnamedPatch().verify(patched) == []

    def test_a_stock_image_does_not_verify(self):
        assert UpgradeCompleteSkipUnnamedPatch().verify(upgrade_complete_skip_unnamed_image())

    def test_refuses_to_apply_twice(self, patched: bytearray):
        with pytest.raises(ValueError, match="already carries"):
            UpgradeCompleteSkipUnnamedPatch().apply(patched)

    @pytest.mark.parametrize("va", [*sorted(ANCHORS), UPGRADE_COMPLETE_MESSAGE])
    def test_a_moved_site_refuses_to_apply(self, va: int):
        data = upgrade_complete_skip_unnamed_image()
        data[va_to_offset(data, va)] ^= 0xFF
        before = bytes(data)
        with pytest.raises(ValueError):
            UpgradeCompleteSkipUnnamedPatch().apply(data)
        assert bytes(data) == before

    def test_it_is_registered_and_detected_once_applied(self, patched: bytearray):
        assert PATCHES[UpgradeCompleteSkipUnnamedPatch.name] is UpgradeCompleteSkipUnnamedPatch
        assert UpgradeCompleteSkipUnnamedPatch.detect(upgrade_complete_skip_unnamed_image()) is None
        assert isinstance(
            UpgradeCompleteSkipUnnamedPatch.detect(patched), UpgradeCompleteSkipUnnamedPatch
        )


class TestExecuted:
    """The cave entered as the hook's `call` enters it: `[esp+4]` the format string slot."""

    @pytest.fixture
    def machine(self):
        pytest.importorskip("unicorn")
        pytest.importorskip("pefile")
        from tests.sage_patch.save_machine import Machine  # noqa: PLC0415

        source = (
            bytearray(REAL_GAME_DAT.read_bytes())
            if REAL_GAME_DAT.exists()
            else upgrade_complete_skip_unnamed_image()
        )
        UpgradeCompleteSkipUnnamedPatch().apply(source)
        m = Machine(bytes(source))
        self.cave = find_section(m.image, SECTION_NAME)[0]
        self.messages: list[tuple[int, int]] = []
        self.destroyed: list[int] = []
        ui_vt = m.alloc(0x100, bytes(0x100))
        m.write32(
            ui_vt + IN_GAME_UI_MESSAGE_SLOT,
            m.stub(None, lambda mm: (self.messages.append((mm.arg(0), mm.arg(1))), mm.ret(0))),
        )
        self.ui = m.alloc(0x10, bytes(0x10))
        m.write32(self.ui, ui_vt)
        m.ensure(THE_IN_GAME_UI)
        m.write32(THE_IN_GAME_UI, self.ui)
        m.stub(UNICODE_STRING_DTOR, lambda mm: (self.destroyed.append(mm.reg("ecx")), mm.ret(0)))
        return m

    def template(self, m, name: bytes | None) -> int:
        template = m.alloc(0x80, bytes(0x80))
        if name is not None:
            text = m.alloc(0x40, bytes(8) + name + b"\x00")
            m.write32(template + UPGRADE_TEMPLATE_DISPLAY_NAME, text)
        return template

    def run(self, m, template: int) -> int:
        """Call the cave with one argument (the string slot); return the slot's address."""
        from unicorn.x86_const import UC_X86_REG_ESP  # noqa: PLC0415

        string = 0x5151
        m.call(self.cave, string, edi=template)
        return m.uc.reg_read(UC_X86_REG_ESP)

    def test_a_named_upgrade_gets_the_stock_message(self, machine):
        self.run(machine, self.template(machine, b"UPGRADE:Forge"))
        assert self.messages == [(self.ui, 0x5151)]
        assert self.destroyed == []

    @pytest.mark.parametrize("name", [None, b""])
    def test_an_unnamed_upgrade_destroys_the_string_instead(self, machine, name):
        self.run(machine, self.template(machine, name))
        assert self.messages == []
        assert len(self.destroyed) == 1
        assert machine.read32(self.destroyed[0]) == 0x5151  # the slot holding the string

    @pytest.mark.parametrize("name", [None, b"", b"UPGRADE:Forge"])
    def test_both_paths_leave_the_same_stack(self, machine, name):
        """One dword above the string slot, as `push this` / the call leave it."""
        esp = self.run(machine, self.template(machine, name))
        assert machine.read32(esp + 4) == 0x5151
