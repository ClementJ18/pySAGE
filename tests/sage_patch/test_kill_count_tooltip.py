"""Tests for the kill-count-tooltip patch.

The stock windows are disassembled to show the hook is the description's release and the anchors
are the record reads the cave relies on. The cave then runs under Unicorn from the hooked `call`
itself, so the line it adds, the battalion redirect, the silent paths and the tail call into the
displaced destructor are all checked against the stack and registers the builder expects back.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sage_patch.addresses import (
    GAME_TEXT_FORMAT_SLOT,
    KINDOF_HORDE_BIT,
    KINDOF_HORDE_BYTE,
    OBJECT_BATTLES_FOUGHT,
    OBJECT_CONTAINED_BY,
    OBJECT_KILLS,
    OBJECT_KILLS_MIRROR,
    OBJECT_SCORE_KILL_COUNT,
    OBJECT_SCORE_KILL_COUNT_BYTES,
    OBJECT_THING_TEMPLATE,
    OBJECT_TOOLTIP_APPEND_LINE,
    OBJECT_TOOLTIP_BATTLES_FOUGHT,
    OBJECT_TOOLTIP_BATTLES_FOUGHT_BYTES,
    OBJECT_TOOLTIP_DESCRIPTION_RELEASE,
    OBJECT_TOOLTIP_DESCRIPTION_RELEASE_BYTES,
    OBJECT_TOOLTIP_DESCRIPTION_RELEASE_RESUME,
    OBJECT_TOOLTIP_LINES_EBP,
    OBJECT_TOOLTIP_OBJECT_EBP,
    THE_GAME_TEXT,
    UNICODE_STRING_CONCAT,
    UNICODE_STRING_DTOR,
)
from sage_patch.patches.kill_count_tooltip import (
    ANCHORS,
    ENTRY_OFFSET,
    LABEL,
    KillCountTooltipPatch,
    build_section,
    replacement,
)
from sage_patch.registry import PATCHES
from sage_patch.utils import va_to_offset
from tests.sage_patch.synthetic import kill_count_tooltip_image

REAL_GAME_DAT = Path(__file__).resolve().parents[2] / "game.dat"
BASE = 0x00F00000


def ops(code: bytes, base: int) -> list[tuple[str, str]]:
    capstone = pytest.importorskip("capstone")
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    return [(i.mnemonic, i.op_str) for i in md.disasm(code, base)]


@pytest.fixture
def patched() -> bytearray:
    data = kill_count_tooltip_image()
    KillCountTooltipPatch().apply(data)
    return data


class TestTheStockWindows:
    def test_the_hook_is_the_description_release(self):
        stock = ops(OBJECT_TOOLTIP_DESCRIPTION_RELEASE_BYTES, OBJECT_TOOLTIP_DESCRIPTION_RELEASE)
        assert stock == [("call", hex(UNICODE_STRING_DTOR))]
        assert OBJECT_TOOLTIP_DESCRIPTION_RELEASE + 5 == OBJECT_TOOLTIP_DESCRIPTION_RELEASE_RESUME

    def test_the_scorer_counts_both_kill_fields_on_the_killer(self):
        assert ops(OBJECT_SCORE_KILL_COUNT_BYTES, OBJECT_SCORE_KILL_COUNT) == [
            ("inc", f"dword ptr [esi + {OBJECT_KILLS_MIRROR:#x}]"),
            ("mov", f"eax, dword ptr [esi + {OBJECT_CONTAINED_BY:#x}]"),
            ("inc", f"dword ptr [esi + {OBJECT_KILLS:#x}]"),
        ]

    def test_the_battles_line_reads_the_record_from_the_hovered_object(self):
        insns = ops(OBJECT_TOOLTIP_BATTLES_FOUGHT_BYTES, OBJECT_TOOLTIP_BATTLES_FOUGHT)
        assert insns[0] == ("mov", f"eax, dword ptr [esi + {OBJECT_BATTLES_FOUGHT:#x}]")
        assert ("jle", hex(0x008EC09C)) in insns  # nothing at zero
        assert ("mov", f"ecx, dword ptr [{THE_GAME_TEXT:#x}]") in insns
        # `OBJECT_KILLS` sits one dword past the battles in the same record.
        assert OBJECT_KILLS == OBJECT_BATTLES_FOUGHT + 4


class TestTheCave:
    def test_the_label_heads_the_section_and_the_code_follows(self):
        code = build_section(BASE)
        assert code[: len(LABEL) + 1] == LABEL + b"\x00"
        assert len(LABEL) < ENTRY_OFFSET

    def test_the_replacement_calls_the_entry(self):
        new = replacement(BASE)
        assert len(new) == len(OBJECT_TOOLTIP_DESCRIPTION_RELEASE_BYTES)
        assert ops(new, OBJECT_TOOLTIP_DESCRIPTION_RELEASE) == [("call", hex(BASE + ENTRY_OFFSET))]

    def test_it_reads_the_count_and_ends_in_the_displaced_call(self):
        insns = ops(build_section(BASE)[ENTRY_OFFSET:], BASE + ENTRY_OFFSET)
        assert insns[0] == ("pushal", "")
        assert insns[1] == ("mov", f"esi, dword ptr [ebp - {-OBJECT_TOOLTIP_OBJECT_EBP:#x}]")
        assert ("mov", f"eax, dword ptr [esi + {OBJECT_CONTAINED_BY:#x}]") in insns
        assert ("test", f"byte ptr [edx + {KINDOF_HORDE_BYTE:#x}], {KINDOF_HORDE_BIT:#x}") in insns
        assert ("mov", f"eax, dword ptr [esi + {OBJECT_KILLS:#x}]") in insns
        assert ("push", hex(BASE)) in insns  # the label
        assert ("call", f"dword ptr [edx + {GAME_TEXT_FORMAT_SLOT:#x}]") in insns
        assert ("call", hex(UNICODE_STRING_CONCAT)) in insns
        assert ("call", hex(OBJECT_TOOLTIP_APPEND_LINE)) in insns
        assert insns[-2:] == [("popal", ""), ("jmp", hex(UNICODE_STRING_DTOR))]


class TestApply:
    def test_apply_then_verify(self, patched: bytearray):
        assert KillCountTooltipPatch().verify(patched) == []

    def test_a_stock_image_does_not_verify(self):
        assert KillCountTooltipPatch().verify(kill_count_tooltip_image())

    def test_refuses_to_apply_twice(self, patched: bytearray):
        with pytest.raises(ValueError, match="already carries"):
            KillCountTooltipPatch().apply(patched)

    @pytest.mark.parametrize("va", [*sorted(ANCHORS), OBJECT_TOOLTIP_DESCRIPTION_RELEASE])
    def test_a_moved_site_refuses_to_apply(self, va: int):
        data = kill_count_tooltip_image()
        data[va_to_offset(data, va)] ^= 0xFF
        before = bytes(data)
        with pytest.raises(ValueError):
            KillCountTooltipPatch().apply(data)
        assert bytes(data) == before

    def test_it_is_registered_and_detected_once_applied(self, patched: bytearray):
        assert PATCHES[KillCountTooltipPatch.name] is KillCountTooltipPatch
        assert KillCountTooltipPatch.detect(kill_count_tooltip_image()) is None
        assert isinstance(KillCountTooltipPatch.detect(patched), KillCountTooltipPatch)

    @pytest.mark.skipif(not REAL_GAME_DAT.exists(), reason="needs the repo's game.dat")
    @pytest.mark.parametrize("kills_first", [True, False])
    def test_it_composes_with_herobar_in_either_order(self, kills_first: bool):
        """`herobar` owns the seven bytes in front of the hook and resumes into it."""
        herobar = PATCHES["herobar"]
        data = bytearray(REAL_GAME_DAT.read_bytes())
        order = [KillCountTooltipPatch(), herobar()]
        for patch in order if kills_first else reversed(order):
            patch.apply(data)
        assert KillCountTooltipPatch().verify(data) == []
        assert herobar().verify(data) == []


class TestExecuted:
    """The cave entered through the hooked `call`, with `ebp` a builder frame."""

    FORMAT = 0x7777
    LINE_BUFFER = 0xBEEF

    @pytest.fixture
    def machine(self):
        pytest.importorskip("unicorn")
        pytest.importorskip("pefile")
        from tests.sage_patch.save_machine import Machine  # noqa: PLC0415

        source = (
            bytearray(REAL_GAME_DAT.read_bytes())
            if REAL_GAME_DAT.exists()
            else kill_count_tooltip_image()
        )
        KillCountTooltipPatch().apply(source)
        m = Machine(bytes(source))
        self.exists = 1
        self.fetches: list[tuple[bytes, int]] = []
        self.formats: list[tuple[int, int, int]] = []
        self.appended: list[tuple[int, int]] = []
        self.destroyed: list[tuple[int, int]] = []

        def fetch(mm):
            label = bytes(mm.uc.mem_read(mm.arg(0), len(LABEL) + 1))
            self.fetches.append((label, mm.reg("ecx")))
            mm.write32(mm.arg(1), self.exists)
            mm.ret(8, self.FORMAT)

        def fmt(mm):
            self.formats.append((mm.read32(mm.arg(0)), mm.arg(1), mm.arg(2)))
            mm.write32(mm.arg(0), self.LINE_BUFFER)
            mm.ret(0)

        def append(mm):
            self.appended.append((mm.arg(0), mm.read32(mm.arg(1))))
            mm.ret(0)

        def destroy(mm):
            self.destroyed.append((mm.reg("ecx"), mm.read32(mm.reg("ecx"))))
            mm.ret(0)

        text_vt = m.alloc(0x100, bytes(0x100))
        m.write32(text_vt + GAME_TEXT_FORMAT_SLOT, m.stub(None, fetch))
        self.text = m.alloc(0x10, bytes(0x10))
        m.write32(self.text, text_vt)
        m.ensure(THE_GAME_TEXT)
        m.write32(THE_GAME_TEXT, self.text)
        m.stub(UNICODE_STRING_CONCAT, fmt)
        m.stub(OBJECT_TOOLTIP_APPEND_LINE, append)
        m.stub(UNICODE_STRING_DTOR, destroy)
        m.stop_at(OBJECT_TOOLTIP_DESCRIPTION_RELEASE_RESUME)
        self.ebp = m.frame()
        self.description = self.ebp - 0x28
        m.write32(self.description, 0xD35C)
        return m

    def unit(self, m, kills: int, template: int = 0) -> int:
        obj = m.alloc(0x500, bytes(0x500))
        m.write32(obj + OBJECT_THING_TEMPLATE, template)
        m.write32(obj + OBJECT_KILLS, kills)
        return obj

    def battalion(self, m, kills: int, horde: bool = True) -> int:
        template = m.alloc(0x200, bytes(0x200))
        if horde:
            m.uc.mem_write(template + KINDOF_HORDE_BYTE, bytes([KINDOF_HORDE_BIT]))
        return self.unit(m, kills, template)

    def hover(self, m, obj: int) -> None:
        """Run the hooked instruction with `obj` as the builder's object; check what it hands
        back."""
        from unicorn.x86_const import UC_X86_REG_ESP  # noqa: PLC0415

        from tests.sage_patch.save_machine import STACK, STACK_SIZE  # noqa: PLC0415

        m.write32(self.ebp + OBJECT_TOOLTIP_OBJECT_EBP, obj)
        regs = {"ebx": 0x1111, "esi": 0x2222, "edi": 0x3333, "edx": 0x4444}
        m.call(OBJECT_TOOLTIP_DESCRIPTION_RELEASE, ebp=self.ebp, ecx=self.description, **regs)
        assert m.stopped_at == OBJECT_TOOLTIP_DESCRIPTION_RELEASE_RESUME
        # The stock call's own effect, once and last, on the description temporary.
        assert self.destroyed[-1] == (self.description, 0xD35C)
        assert m.uc.reg_read(UC_X86_REG_ESP) == STACK + STACK_SIZE - 0x1000 - 4
        for name, value in regs.items():
            assert m.reg(name) == value
        assert m.reg("ebp") == self.ebp

    def test_a_unit_with_kills_gets_the_line(self, machine):
        self.hover(machine, self.unit(machine, 7))
        assert self.fetches == [(LABEL + b"\x00", self.text)]
        assert self.formats == [(0, self.FORMAT, 7)]  # into an empty local
        assert self.appended == [(self.ebp + OBJECT_TOOLTIP_LINES_EBP, self.LINE_BUFFER)]
        assert [buffer for _, buffer in self.destroyed] == [self.LINE_BUFFER, 0xD35C]

    def test_a_battalion_member_shows_the_battalion(self, machine):
        member = self.unit(machine, 1)
        machine.write32(member + OBJECT_CONTAINED_BY, self.battalion(machine, 12))
        self.hover(machine, member)
        assert [count for _, _, count in self.formats] == [12]

    def test_a_container_that_is_not_a_horde_is_ignored(self, machine):
        passenger = self.unit(machine, 3)
        machine.write32(passenger + OBJECT_CONTAINED_BY, self.battalion(machine, 40, horde=False))
        self.hover(machine, passenger)
        assert [count for _, _, count in self.formats] == [3]

    @pytest.mark.parametrize("kills", [0, -1])
    def test_no_kills_no_line(self, machine, kills: int):
        self.hover(machine, self.unit(machine, kills))
        assert self.fetches == []
        assert self.appended == []
        assert len(self.destroyed) == 1

    def test_no_object_no_line(self, machine):
        self.hover(machine, 0)
        assert self.fetches == []
        assert len(self.destroyed) == 1

    def test_a_missing_key_drops_the_line(self, machine):
        self.exists = 0
        self.hover(machine, self.unit(machine, 5))
        assert len(self.fetches) == 1
        assert self.formats == []
        assert self.appended == []
        assert len(self.destroyed) == 1  # the local owned nothing
