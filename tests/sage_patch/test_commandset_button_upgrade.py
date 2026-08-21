"""Tests for the command-button upgrade overlay.

The rebuild routine is what matters and it is *run* here rather than read. Its whole job is a
decision made from state a disassembly cannot show: which of an object's modules count as applied,
which of those carry buttons, what the resulting set is called, and which buttons end up in which
slots. The dozen engine calls it makes are intercepted by the interpreter, which is what turns
"it put `Command_Spear` in slot 5 of a set named after the base plus the tokens" into an assertion.

`AsciiString` is modelled with real buffers in the interpreter's memory rather than as Python
strings on the side, because the cave does pointer arithmetic on them - it hands
`AsciiString::concat` the field's own characters as `handle+8` - and a model that hid that would
not catch getting it wrong.

The parser is the shared one from `sage_patch.patches.utils.token_lists`, tested with
`trigger-recharge-list`; what is checked here is that the cave holds one copy and that the new row
points at it. The rest is the build fingerprint: one row of a one-row table, a `sizeof`, two calls
inside a constructor and a destructor, and two function entries.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from sage_patch.asm import Asm
from sage_patch.patches.commandset_button_upgrade import (
    ANCHORS,
    ASCII_STRING_ASSIGN,
    CLEAR_COMMAND_BUTTONS,
    CLEAR_CUSTOM_ANIM,
    COMMAND_BUTTONS_OFFSET,
    COMMAND_SET_OFFSET,
    COMMAND_SET_STORE_DIRTY_OFFSET,
    CTOR_ASSIGN_CALL_VA,
    DTOR_DTOR_CALL_VA,
    FIELD_TABLE_REF_VA,
    FIELD_TABLE_VA,
    FIND_COMMAND_BUTTON,
    FIND_COMMAND_SET,
    GET_COMMAND_BUTTON,
    KEYWORD,
    MAX_NAME,
    MODULE_DATA_PTR_OFFSET,
    MODULE_DATA_SIZE,
    MODULE_DATA_SIZE_VA,
    MODULE_LATCH_OFFSET,
    MODULE_OBJECT_PTR_OFFSET,
    MODULE_VTABLE,
    MUX_OFFSET,
    NEW_COMMAND_SET,
    OBJECT_MODULES_OFFSET,
    OBJECT_TEMPLATE_OFFSET,
    SECTION_NAME,
    SELECTION_UI,
    SET_BUTTON_BOUND_IMM8_VA,
    SET_COMMAND_BUTTON,
    SET_COMMAND_SET_STRING_OVERRIDE,
    TEMPLATE_COMMAND_SET_OFFSET,
    THE_COMMAND_SET_STORE,
    UI_DESELECT,
    UI_RESELECT,
    UNUPGRADE_EH_EAX,
    UNUPGRADE_IMPL_BYTES,
    UNUPGRADE_IMPL_RESUME,
    UNUPGRADE_IMPL_VA,
    UPGRADE_IMPL_BYTES,
    UPGRADE_IMPL_RESUME,
    UPGRADE_IMPL_VA,
    CommandSetButtonUpgradePatch,
    build_code,
)
from sage_patch.patches.utils.field_tables import ROW_SIZE
from sage_patch.patches.utils.token_lists import (
    ASCII_STRING_CONCAT_CHAR,
    ASCII_STRING_CONCAT_CSTR,
    ASCII_STRING_DTOR,
    ASCII_STRING_SET,
    STOCK_ASCII_STRING_PARSER,
    build_list_parser,
)
from sage_patch.utils import find_section, va_to_offset
from tests.sage_patch.synthetic import commandset_button_upgrade_image

_GAME_DAT = Path(__file__).resolve().parents[2] / "game.dat"


@pytest.fixture
def image() -> bytearray:
    return commandset_button_upgrade_image()


def _patched(image: bytearray) -> bytearray:
    data = bytearray(image)
    CommandSetButtonUpgradePatch().apply(data)
    return data


def at(data: bytes | bytearray, va: int, count: int) -> bytes:
    off = va_to_offset(data, va)
    assert off is not None, f"0x{va:08x} is not mapped"
    return bytes(data[off : off + count])


def _cave(data: bytes | bytearray) -> tuple[int, bytes]:
    located = find_section(data, SECTION_NAME)
    assert located is not None
    section_va, section_off, vsize = located
    return section_va, bytes(data[section_off : section_off + vsize])


def _row(data: bytes | bytearray, table_va: int, index: int) -> tuple[int, int, int, int]:
    return struct.unpack("<4I", at(data, table_va + index * ROW_SIZE, ROW_SIZE))


def _call_target(data: bytes | bytearray, va: int) -> int:
    assert at(data, va, 1) == b"\xe8"
    return va + 5 + struct.unpack("<i", at(data, va + 1, 4))[0]


def _jmp_target(data: bytes | bytearray, va: int) -> int:
    assert at(data, va, 1) == b"\xe9"
    return va + 5 + struct.unpack("<i", at(data, va + 1, 4))[0]


class TestApply:
    def test_apply_then_verify(self, image: bytearray) -> None:
        data = _patched(image)
        assert CommandSetButtonUpgradePatch().verify(data) == []

    def test_verify_rejects_an_unpatched_image(self, image: bytearray) -> None:
        problems = CommandSetButtonUpgradePatch().verify(image)
        assert problems and SECTION_NAME in problems[0]

    def test_detect(self, image: bytearray) -> None:
        assert CommandSetButtonUpgradePatch.detect(image) is None
        found = CommandSetButtonUpgradePatch.detect(_patched(image))
        assert found is not None and found.name == "commandset-button-upgrade"

    def test_applying_twice_fails_rather_than_double_patching(self, image: bytearray) -> None:
        data = _patched(image)
        with pytest.raises(ValueError, match="already patched"):
            CommandSetButtonUpgradePatch().apply(data)

    def test_the_new_row_names_the_keyword_and_the_new_field(self, image: bytearray) -> None:
        data = _patched(image)
        table_va = struct.unpack("<I", at(data, FIELD_TABLE_REF_VA + 1, 4))[0]
        name_va, parse_fn, userdata, offset = _row(data, table_va, 1)
        assert at(data, name_va, len(KEYWORD) + 1) == KEYWORD.encode() + b"\x00"
        assert parse_fn != STOCK_ASCII_STRING_PARSER
        assert userdata == 0
        assert offset == COMMAND_BUTTONS_OFFSET

    def test_the_stock_row_is_copied_verbatim(self, image: bytearray) -> None:
        """The rebuilt table has to carry `CommandSet` unchanged - same name pointer, same stock
        parser, same `ModuleData` offset - because the module's own code still reads that field."""
        data = _patched(image)
        table_va = struct.unpack("<I", at(data, FIELD_TABLE_REF_VA + 1, 4))[0]
        assert _row(data, table_va, 0) == _row(image, FIELD_TABLE_VA, 0)
        assert _row(data, table_va, 0)[1] == STOCK_ASCII_STRING_PARSER
        assert _row(data, table_va, 0)[3] == COMMAND_SET_OFFSET

    def test_the_table_is_terminated(self, image: bytearray) -> None:
        data = _patched(image)
        table_va = struct.unpack("<I", at(data, FIELD_TABLE_REF_VA + 1, 4))[0]
        assert _row(data, table_va, 2) == (0, 0, 0, 0)

    def test_the_keyword_parses_through_the_shared_list_parser(self, image: bytearray) -> None:
        data = _patched(image)
        table_va = struct.unpack("<I", at(data, FIELD_TABLE_REF_VA + 1, 4))[0]
        parser_va = _row(data, table_va, 1)[1]
        section_va, content = _cave(data)
        parser = build_list_parser(parser_va)
        start = parser_va - section_va
        assert content[start : start + len(parser)] == parser
        assert content.count(parser[:16]) == 1

    def test_sizeof_grows_by_one_pointer(self, image: bytearray) -> None:
        data = _patched(image)
        assert at(data, MODULE_DATA_SIZE_VA, 5) == b"\x68" + struct.pack("<I", MODULE_DATA_SIZE + 4)
        assert COMMAND_BUTTONS_OFFSET == MODULE_DATA_SIZE

    def test_the_constructor_and_destructor_route_through_the_shims(self, image: bytearray) -> None:
        data = _patched(image)
        section_va, content = _cave(data)
        shims = (
            (CTOR_ASSIGN_CALL_VA, ASCII_STRING_ASSIGN),
            (DTOR_DTOR_CALL_VA, ASCII_STRING_DTOR),
        )
        for va, stock in shims:
            target = _call_target(data, va)
            assert target != stock
            assert section_va <= target < section_va + len(content)

    def test_both_implementations_are_hooked_into_the_cave(self, image: bytearray) -> None:
        data = _patched(image)
        section_va, content = _cave(data)
        for va in (UPGRADE_IMPL_VA, UNUPGRADE_IMPL_VA):
            target = _jmp_target(data, va)
            assert section_va <= target < section_va + len(content)
        assert _jmp_target(data, UPGRADE_IMPL_VA) != _jmp_target(data, UNUPGRADE_IMPL_VA)

    def test_the_upgrade_hook_window_is_padded_not_overrun(self, image: bytearray) -> None:
        """Seven bytes are displaced because five would cut `lea ecx, [esi-0x10]` in half. The
        two spare bytes must be `nop`, and the instruction after the window must be untouched."""
        data = _patched(image)
        assert at(data, UPGRADE_IMPL_VA + 5, 2) == b"\x90\x90"
        assert at(data, UPGRADE_IMPL_RESUME, 5) == at(image, UPGRADE_IMPL_RESUME, 5)

    def test_a_relocated_table_is_followed_rather_than_bypassed(self, image: bytearray) -> None:
        """The base comes from the reference that names it. Point that reference somewhere else
        and the patch must read the rows there - the failure it prevents is silent, because the
        stale table still holds every byte the patch would assert."""
        moved = FIELD_TABLE_VA - 0x400  # still inside the page the stand-in maps
        rows = at(image, FIELD_TABLE_VA, 2 * ROW_SIZE)
        off = va_to_offset(image, moved)
        assert off is not None
        image[off : off + len(rows)] = rows
        ref_off = va_to_offset(image, FIELD_TABLE_REF_VA + 1)
        assert ref_off is not None
        struct.pack_into("<I", image, ref_off, moved)

        data = _patched(image)
        table_va = struct.unpack("<I", at(data, FIELD_TABLE_REF_VA + 1, 4))[0]
        assert table_va not in (FIELD_TABLE_VA, moved)
        assert _row(data, table_va, 0) == _row(image, moved, 0)
        # ... and the stale copy is left alone
        assert _row(data, FIELD_TABLE_VA, 0)[1] == STOCK_ASCII_STRING_PARSER

    def test_a_missing_command_set_row_is_refused(self, image: bytearray) -> None:
        name_va = struct.unpack("<I", at(image, FIELD_TABLE_VA, 4))[0]
        off = va_to_offset(image, name_va)
        assert off is not None
        image[off] = ord("X")
        with pytest.raises(ValueError, match="no 'CommandSet' row"):
            CommandSetButtonUpgradePatch().apply(image)

    @pytest.mark.parametrize("va", [va for va, _blob, _what in ANCHORS])
    def test_a_disturbed_anchor_is_refused(self, image: bytearray, va: int) -> None:
        off = va_to_offset(image, va)
        assert off is not None
        image[off] ^= 0xFF
        with pytest.raises(ValueError, match="not the expected build"):
            CommandSetButtonUpgradePatch().apply(image)

    def test_the_slot_guard_immediate_is_not_asserted(self, image: bytearray) -> None:
        """`commandset-limit` rewrites exactly that byte, and this patch reads it at run time. If
        it were part of an anchor the two would stop composing in one order."""
        off = va_to_offset(image, SET_BUTTON_BOUND_IMM8_VA)
        assert off is not None
        image[off] = 64
        CommandSetButtonUpgradePatch().apply(image)  # must not raise


class TestAgainstTheRealBinary:
    """The same sites, in the real `game.dat` - the check the synthetic image cannot make."""

    @pytest.mark.full
    def test_every_site_holds_its_stock_bytes(self) -> None:
        if not _GAME_DAT.exists():
            pytest.skip("no game.dat beside the repo")
        data = bytearray(_GAME_DAT.read_bytes())
        CommandSetButtonUpgradePatch().apply(data)
        assert CommandSetButtonUpgradePatch().verify(data) == []


_REGS = ("eax", "ecx", "edx", "ebx", "esp", "ebp", "esi", "edi")
_REG8 = ("al", "cl", "dl", "bl", "ah", "ch", "dh", "bh")
_MASK = 0xFFFFFFFF

_STACK_TOP = 0x00300000
_HEAP = 0x02000000
_RETURN_MAGIC = 0x0BADF00D


class Unsupported(Exception):
    """An instruction form the cave was not known to emit.

    Raising rather than skipping is the point: an instruction added to the cave without a test to
    match it fails here instead of being quietly ignored.
    """


@dataclass
class Machine:
    """An interpreter for the instruction forms `build_code` emits, and nothing else.

    Byte-addressed memory, the eight general registers, and the four flags the cave's five branch
    conditions need. The engine calls are **intercepted**, not executed: each is a Python method
    that reads the arguments off the modelled stack, does what the real one does to the modelled
    world, and returns `(eax, bytes to pop)` - which is how each one's `ret n` is honoured.

    `AsciiString`s are real: a handle is a pointer to `{refcount, length, allocated, chars...}` in
    this memory, so the cave's own `handle+8` arithmetic is exercised rather than modelled away.
    """

    mem: dict[int, int] = field(default_factory=dict)
    regs: dict[str, int] = field(default_factory=lambda: dict.fromkeys(_REGS, 0))
    zf: bool = False
    sf: bool = False
    of: bool = False
    cf: bool = False
    brk: int = _HEAP
    #: Every `CommandSet` the store knows, by name, each a `{slot: button}` dict.
    sets: dict[str, dict[int, int]] = field(default_factory=dict)
    #: `CommandSet *` -> its name, so an intercepted write can find the set back.
    set_names: dict[int, str] = field(default_factory=dict)
    #: Name -> the `CommandButton *` `findCommandButton` answers with.
    buttons: dict[str, int] = field(default_factory=dict)
    #: Every name handed to `findCommandSet` and to `findCommandButton`, in order.
    sets_looked_up: list[str] = field(default_factory=list)
    buttons_looked_up: list[str] = field(default_factory=list)
    #: Every set `newCommandSet` was asked to create, as `(name, mutable flag)`.
    created: list[tuple[str, int]] = field(default_factory=list)
    #: What `setCommandCommandSetStringOverride` was last given, and how often.
    override: str | None = None
    override_calls: int = 0
    #: Every module base `setCustomAnimAndDuration(false)` was called on.
    anim_cleared: list[int] = field(default_factory=list)
    deselected: list[int] = field(default_factory=list)
    reselected: list[int] = field(default_factory=list)
    dirty: bool = False

    def read8(self, va: int) -> int:
        return self.mem.get(va, 0)

    def write8(self, va: int, value: int) -> None:
        self.mem[va] = value & 0xFF

    def read32(self, va: int) -> int:
        return int.from_bytes(bytes(self.read8(va + i) for i in range(4)), "little")

    def write32(self, va: int, value: int) -> None:
        for i, byte in enumerate((value & _MASK).to_bytes(4, "little")):
            self.write8(va + i, byte)

    def write(self, va: int, blob: bytes) -> None:
        for i, byte in enumerate(blob):
            self.write8(va + i, byte)

    def cstring(self, va: int) -> str:
        out = bytearray()
        while self.read8(va) != 0:
            out.append(self.read8(va))
            va += 1
        return out.decode("latin1")

    def alloc(self, size: int) -> int:
        va, self.brk = self.brk, self.brk + ((size + 15) & ~15)
        return va

    def alloc_string(self, text: str) -> int:
        """An `AsciiString` buffer: the eight-byte header the engine uses, then the characters."""
        raw = text.encode("latin1") + b"\x00"
        handle = self.alloc(8 + len(raw))
        self.write32(handle, 1)  # refCount
        self.write32(handle + 4, len(text) | (len(raw) << 16))  # length, allocated
        self.write(handle + 8, raw)
        return handle

    def read_field(self, slot_va: int) -> str:
        handle = self.read32(slot_va)
        return "" if handle == 0 else self.cstring(handle + 8)

    def write_field(self, slot_va: int, text: str) -> None:
        self.write32(slot_va, 0 if text == "" else self.alloc_string(text))

    def push(self, value: int) -> None:
        self.regs["esp"] = (self.regs["esp"] - 4) & _MASK
        self.write32(self.regs["esp"], value)

    def pop(self) -> int:
        value = self.read32(self.regs["esp"])
        self.regs["esp"] = (self.regs["esp"] + 4) & _MASK
        return value

    def arg(self, index: int) -> int:
        """The ``index``-th stack argument of the call currently being intercepted."""
        return self.read32(self.regs["esp"] + 4 * index)

    def _logic_flags(self, result: int, bits: int = 32) -> None:
        self.zf = result == 0
        self.sf = bool(result >> (bits - 1) & 1)
        self.cf = self.of = False

    def _sub_flags(self, left: int, right: int, bits: int = 32) -> int:
        mask = (1 << bits) - 1
        result = (left - right) & mask
        self.zf = result == 0
        self.sf = bool(result >> (bits - 1) & 1)
        self.cf = left < right
        sign = 1 << (bits - 1)
        self.of = bool((left ^ right) & (left ^ result) & sign)
        return result

    def _add_flags(self, left: int, right: int, bits: int = 32) -> int:
        mask = (1 << bits) - 1
        raw = left + right
        result = raw & mask
        self.zf = result == 0
        self.sf = bool(result >> (bits - 1) & 1)
        self.cf = raw > mask
        sign = 1 << (bits - 1)
        self.of = bool(~(left ^ right) & (left ^ result) & sign)
        return result

    def get8(self, index: int) -> int:
        name = _REGS[index & 3]
        value = self.regs[name]
        return (value >> 8 & 0xFF) if index >= 4 else (value & 0xFF)

    def set8(self, index: int, value: int) -> None:
        name = _REGS[index & 3]
        current = self.regs[name]
        if index >= 4:
            self.regs[name] = (current & ~0xFF00) | ((value & 0xFF) << 8)
        else:
            self.regs[name] = (current & ~0xFF) | (value & 0xFF)


@dataclass
class Cpu:
    """The decode/execute loop, kept apart from the modelled world so the two read separately."""

    machine: Machine
    code: bytes
    code_va: int
    eip: int = 0

    def fetch(self, count: int) -> bytes:
        blob = self.machine_bytes(self.eip, count)
        self.eip += count
        return blob

    def machine_bytes(self, va: int, count: int) -> bytes:
        return bytes(self.machine.read8(va + i) for i in range(count))

    def imm8(self) -> int:
        return self.fetch(1)[0]

    def simm8(self) -> int:
        return struct.unpack("<b", self.fetch(1))[0]

    def imm32(self) -> int:
        return struct.unpack("<I", self.fetch(4))[0]

    def simm32(self) -> int:
        return struct.unpack("<i", self.fetch(4))[0]

    def modrm(self) -> tuple[int, tuple[str, int]]:
        """`(reg field, operand)`, where the operand is `('reg', index)` or `('mem', address)`."""
        byte = self.imm8()
        mod, reg, rm = byte >> 6, (byte >> 3) & 7, byte & 7
        if mod == 3:
            return reg, ("reg", rm)
        if rm == 4:
            raise Unsupported("SIB addressing")
        if mod == 0 and rm == 5:
            return reg, ("mem", self.imm32())
        base = self.machine.regs[_REGS[rm]]
        if mod == 0:
            return reg, ("mem", base & _MASK)
        offset = self.simm8() if mod == 1 else self.simm32()
        return reg, ("mem", (base + offset) & _MASK)

    def load(self, operand: tuple[str, int], bits: int = 32) -> int:
        kind, value = operand
        if kind == "reg":
            return self.machine.get8(value) if bits == 8 else self.machine.regs[_REGS[value]]
        return self.machine.read8(value) if bits == 8 else self.machine.read32(value)

    def store(self, operand: tuple[str, int], value: int, bits: int = 32) -> None:
        kind, where = operand
        if kind == "reg":
            if bits == 8:
                self.machine.set8(where, value)
            else:
                self.machine.regs[_REGS[where]] = value & _MASK
        elif bits == 8:
            self.machine.write8(where, value)
        else:
            self.machine.write32(where, value)

    def condition(self, code: int) -> bool:
        m = self.machine
        if code == 0x4:
            return m.zf
        if code == 0x5:
            return not m.zf
        if code == 0x7:
            return not m.cf and not m.zf
        if code == 0xC:
            return m.sf != m.of
        if code == 0xD:
            return m.sf == m.of
        raise Unsupported(f"jcc condition 0x{code:x}")

    def group1(self, operand: tuple[str, int], op: int, value: int, bits: int = 32) -> None:
        m = self.machine
        left = self.load(operand, bits)
        if op == 0:
            self.store(operand, m._add_flags(left, value, bits), bits)
        elif op == 1:
            result = (left | value) & ((1 << bits) - 1)
            m._logic_flags(result, bits)
            self.store(operand, result, bits)
        elif op == 4:
            result = left & value & ((1 << bits) - 1)
            m._logic_flags(result, bits)
            self.store(operand, result, bits)
        elif op == 5:
            self.store(operand, m._sub_flags(left, value, bits), bits)
        elif op == 7:
            m._sub_flags(left, value, bits)
        else:
            raise Unsupported(f"group1 /{op}")

    def run(self, limit: int = 200_000) -> None:
        for _ in range(limit):
            if self.eip == _RETURN_MAGIC:
                return
            self.step()
        raise AssertionError("the routine did not return")

    def step(self) -> None:  # noqa: PLR0911, PLR0912, PLR0915 - a decoder is a jump table
        m = self.machine
        op = self.imm8()
        if 0x50 <= op <= 0x57:
            m.push(m.regs[_REGS[op - 0x50]])
            return
        if 0x58 <= op <= 0x5F:
            m.regs[_REGS[op - 0x58]] = m.pop()
            return
        if 0x40 <= op <= 0x47:
            name = _REGS[op - 0x40]
            carry = m.cf
            m.regs[name] = m._add_flags(m.regs[name], 1)
            m.cf = carry
            return
        if 0x48 <= op <= 0x4F:
            name = _REGS[op - 0x48]
            carry = m.cf
            m.regs[name] = m._sub_flags(m.regs[name], 1)
            m.cf = carry
            return
        if 0xB8 <= op <= 0xBF:
            m.regs[_REGS[op - 0xB8]] = self.imm32()
            return
        if 0xB0 <= op <= 0xB7:
            m.set8(op - 0xB0, self.imm8())
            return
        if op == 0x6A:
            m.push(struct.unpack("<b", self.fetch(1))[0] & _MASK)
            return
        if op == 0x3C:
            m._sub_flags(m.regs["eax"] & 0xFF, self.imm8(), 8)
            return
        if op == 0xA1:
            m.regs["eax"] = m.read32(self.imm32())
            return
        if op in (0x03, 0x3B, 0x8B, 0x8D, 0x33):
            reg, operand = self.modrm()
            if op == 0x8D:
                kind, address = operand
                if kind != "mem":
                    raise Unsupported("lea on a register")
                m.regs[_REGS[reg]] = address
                return
            right = self.load(operand)
            left = m.regs[_REGS[reg]]
            if op == 0x03:
                m.regs[_REGS[reg]] = m._add_flags(left, right)
            elif op == 0x3B:
                m._sub_flags(left, right)
            elif op == 0x33:
                result = left ^ right
                m._logic_flags(result)
                m.regs[_REGS[reg]] = result
            else:
                m.regs[_REGS[reg]] = right
            return
        if op in (0x89, 0x85):
            reg, operand = self.modrm()
            if op == 0x89:
                self.store(operand, m.regs[_REGS[reg]])
            else:
                m._logic_flags(self.load(operand) & m.regs[_REGS[reg]])
            return
        if op in (0x88, 0x8A, 0x84, 0x32):
            reg, operand = self.modrm()
            if op == 0x88:
                self.store(operand, m.get8(reg), 8)
            elif op == 0x8A:
                m.set8(reg, self.load(operand, 8))
            elif op == 0x84:
                m._logic_flags(self.load(operand, 8) & m.get8(reg), 8)
            else:
                result = m.get8(reg) ^ self.load(operand, 8)
                m._logic_flags(result, 8)
                m.set8(reg, result)
            return
        if op == 0x6B:
            reg, operand = self.modrm()
            m.regs[_REGS[reg]] = (self.load(operand) * self.simm8()) & _MASK
            return
        if op == 0x83:
            reg, operand = self.modrm()
            self.group1(operand, reg, self.simm8() & _MASK)
            return
        if op == 0x81:
            reg, operand = self.modrm()
            self.group1(operand, reg, self.imm32())
            return
        if op == 0x80:
            reg, operand = self.modrm()
            self.group1(operand, reg, self.imm8(), 8)
            return
        if op == 0xC6:
            reg, operand = self.modrm()
            if reg != 0:
                raise Unsupported(f"0xc6 /{reg}")
            self.store(operand, self.imm8(), 8)
            return
        if op == 0xC7:
            reg, operand = self.modrm()
            if reg != 0:
                raise Unsupported(f"0xc7 /{reg}")
            self.store(operand, self.imm32())
            return
        if op == 0xFF:
            reg, operand = self.modrm()
            if reg != 6:
                raise Unsupported(f"0xff /{reg}")
            m.push(self.load(operand))
            return
        if op == 0x0F:
            second = self.imm8()
            if second in (0xB6, 0xBE):
                reg, operand = self.modrm()
                value = self.load(operand, 8)
                if second == 0xBE and value & 0x80:
                    value -= 0x100
                m.regs[_REGS[reg]] = value & _MASK
                return
            if 0x80 <= second <= 0x8F:
                displacement = self.simm32()
                if self.condition(second & 0xF):
                    self.eip = (self.eip + displacement) & _MASK
                return
            raise Unsupported(f"0f {second:02x}")
        if op == 0xE9:
            # The displacement is read into a local first: fetching it advances `eip` past it,
            # and a displacement is relative to *that* address, not to the one before the read.
            displacement = self.simm32()
            self.eip = (self.eip + displacement) & _MASK
            return
        if op == 0xE8:
            displacement = self.simm32()
            target = (self.eip + displacement) & _MASK
            if self.code_va <= target < self.code_va + len(self.code):
                m.push(self.eip)
                self.eip = target
            else:
                self.engine_call(target)
            return
        if op == 0xC3:
            self.eip = m.pop()
            return
        if op == 0xC9:
            m.regs["esp"] = m.regs["ebp"]
            m.regs["ebp"] = m.pop()
            return
        raise Unsupported(f"opcode 0x{op:02x} at 0x{self.eip - 1:08x}")

    def engine_call(self, target: int) -> None:
        """Intercept one engine call: run its model, drop its arguments, resume the caller."""
        m = self.machine
        handler = _STUBS.get(target)
        if handler is None:
            raise Unsupported(f"call to unmodelled 0x{target:08x}")
        eax, popped = handler(m)
        m.regs["eax"] = eax & _MASK
        m.regs["esp"] = (m.regs["esp"] + popped) & _MASK


def _stub_assign(m: Machine) -> tuple[int, int]:
    m.write_field(m.regs["ecx"], m.read_field(m.arg(0)))
    return m.regs["ecx"], 4


def _stub_set(m: Machine) -> tuple[int, int]:
    m.write_field(m.regs["ecx"], m.cstring(m.arg(0)))
    return m.regs["ecx"], 4


def _stub_concat_cstr(m: Machine) -> tuple[int, int]:
    m.write_field(m.regs["ecx"], m.read_field(m.regs["ecx"]) + m.cstring(m.arg(0)))
    return m.regs["ecx"], 4


def _stub_concat_char(m: Machine) -> tuple[int, int]:
    m.write_field(m.regs["ecx"], m.read_field(m.regs["ecx"]) + chr(m.arg(0) & 0xFF))
    return m.regs["ecx"], 4


def _stub_dtor(m: Machine) -> tuple[int, int]:
    m.write32(m.regs["ecx"], 0)
    return m.regs["ecx"], 0


def _stub_find_set(m: Machine) -> tuple[int, int]:
    name = m.read_field(m.arg(0))
    m.sets_looked_up.append(name)
    for pointer, known in m.set_names.items():
        if known == name:
            return pointer, 4
    return 0, 4


def _stub_new_set(m: Machine) -> tuple[int, int]:
    name = m.read_field(m.arg(0))
    m.created.append((name, m.arg(1)))
    pointer = m.alloc(16)
    m.sets[name] = {}
    m.set_names[pointer] = name
    return pointer, 8


def _stub_clear(m: Machine) -> tuple[int, int]:
    m.sets[m.set_names[m.regs["ecx"]]] = {}
    return m.regs["ecx"], 0


def _stub_get_button(m: Machine) -> tuple[int, int]:
    return m.sets[m.set_names[m.regs["ecx"]]].get(m.arg(0), 0), 4


def _stub_set_button(m: Machine) -> tuple[int, int]:
    button, slot = m.arg(0), m.arg(1)
    if 0 <= slot < m.read8(SET_BUTTON_BOUND_IMM8_VA):  # the engine's own guard
        m.sets[m.set_names[m.regs["ecx"]]][slot] = button
    return m.regs["ecx"], 8


def _stub_find_button(m: Machine) -> tuple[int, int]:
    name = m.read_field(m.arg(0))
    m.buttons_looked_up.append(name)
    return m.buttons.get(name, 0), 4


def _stub_override(m: Machine) -> tuple[int, int]:
    m.override = m.read_field(m.arg(0))
    m.override_calls += 1
    return m.regs["ecx"], 4


def _stub_clear_anim(m: Machine) -> tuple[int, int]:
    m.anim_cleared.append(m.regs["ecx"])
    return m.regs["ecx"], 0


def _stub_deselect(m: Machine) -> tuple[int, int]:
    m.deselected.append(m.arg(0))
    return m.regs["ecx"], 4


def _stub_reselect(m: Machine) -> tuple[int, int]:
    m.reselected.append(m.arg(0))
    return m.regs["ecx"], 4


_STUBS = {
    ASCII_STRING_ASSIGN: _stub_assign,
    ASCII_STRING_SET: _stub_set,
    ASCII_STRING_CONCAT_CSTR: _stub_concat_cstr,
    ASCII_STRING_CONCAT_CHAR: _stub_concat_char,
    ASCII_STRING_DTOR: _stub_dtor,
    FIND_COMMAND_SET: _stub_find_set,
    NEW_COMMAND_SET: _stub_new_set,
    CLEAR_COMMAND_BUTTONS: _stub_clear,
    CLEAR_CUSTOM_ANIM: _stub_clear_anim,
    GET_COMMAND_BUTTON: _stub_get_button,
    SET_COMMAND_BUTTON: _stub_set_button,
    FIND_COMMAND_BUTTON: _stub_find_button,
    SET_COMMAND_SET_STRING_OVERRIDE: _stub_override,
    UI_DESELECT: _stub_deselect,
    UI_RESELECT: _stub_reselect,
}


@dataclass
class World:
    """One object with its modules, laid out in a `Machine`'s memory the way the engine lays it
    out - so the cave finds each field where it looks for it and nowhere else."""

    machine: Machine
    cpu: Cpu
    #: The cave's routines, re-laid-out at the address the patched image put them, so a test can
    #: enter one by name instead of by counting bytes.
    code: Asm
    obj: int
    modules: list[int]

    def enter(self, label: str) -> None:
        """Point the CPU at one of the cave's routines, with a sentinel return address below it."""
        self.machine.push(_RETURN_MAGIC)
        self.cpu.eip = self.code.label_va(label)


def _cave_code(data: bytes | bytearray) -> Asm:
    """The cave's code, re-derived from where the patched image actually put its parser.

    Taken from the field-table row rather than from an assumed layout, so a test enters the same
    bytes the engine would call.
    """
    table_va = struct.unpack("<I", at(data, FIELD_TABLE_REF_VA + 1, 4))[0]
    parser_va = _row(data, table_va, 1)[1]
    return build_code(parser_va + len(build_list_parser(parser_va)))


def _world(
    modules: list[tuple[str | None, str | None, bool]],
    template_set: str = "BaseSet",
    bound: int = 33,
) -> World:
    """A `Machine` holding one object whose modules are ``(CommandSet, CommandButtons, applied)``.

    A `None` field is one the INI never wrote, which is a NULL handle - the state the cave tests
    for. `False` for applied leaves the `UpgradeMux` latch clear.
    """
    data = _patched(commandset_button_upgrade_image())
    section_va, content = _cave(data)

    m = Machine()
    m.write(section_va, content)
    m.write8(SET_BUTTON_BOUND_IMM8_VA, bound)
    m.write32(THE_COMMAND_SET_STORE, m.alloc(0x40))
    m.write32(SELECTION_UI, m.alloc(0x40))

    template = m.alloc(0x100)
    m.write_field(template + TEMPLATE_COMMAND_SET_OFFSET, template_set)
    obj = m.alloc(0x400)
    m.write32(obj + OBJECT_TEMPLATE_OFFSET, template)

    pointers: list[int] = []
    for command_set, command_buttons, applied in modules:
        module_data = m.alloc(0x200)
        if command_set is not None:
            m.write_field(module_data + COMMAND_SET_OFFSET, command_set)
        if command_buttons is not None:
            m.write_field(module_data + COMMAND_BUTTONS_OFFSET, command_buttons)
        module = m.alloc(0x20)
        m.write32(module, MODULE_VTABLE)
        m.write32(module + MODULE_DATA_PTR_OFFSET, module_data)
        m.write8(module + MODULE_LATCH_OFFSET, 1 if applied else 0)
        pointers.append(module)

    array = m.alloc(4 * (len(pointers) + 1))
    for index, module in enumerate(pointers):
        m.write32(array + 4 * index, module)
    m.write32(obj + OBJECT_MODULES_OFFSET, array)

    return World(m, Cpu(m, content, section_va), _cave_code(data), obj, pointers)


def _built(world: World) -> dict[int, int]:
    """The `CommandSet` the last rebuild pointed the object at, by the name it wrote."""
    name = world.machine.override
    assert name, "the rebuild left the override empty"
    return world.machine.sets[name]


def _rebuild(world: World, self_module: int = 0, self_applied: int = 0) -> None:
    """Call the cave's rebuild routine the way its two hooks do - `cdecl`, caller cleans."""
    m = world.machine
    m.regs["esp"] = _STACK_TOP
    m.push(self_applied)
    m.push(self_module)
    m.push(world.obj)
    world.enter("rebuild")
    world.cpu.run()
    m.regs["esp"] = (m.regs["esp"] + 12) & _MASK
    assert m.regs["esp"] == _STACK_TOP, "the routine did not balance the stack"


def _has_overlay(world: World) -> int:
    m = world.machine
    m.regs["esp"] = _STACK_TOP
    m.regs["ecx"] = world.obj
    world.enter("has_overlay")
    world.cpu.run()
    assert m.regs["esp"] == _STACK_TOP, "the scan did not balance the stack"
    return m.regs["eax"] & 0xFF


class TestHasOverlay:
    def test_no_modules_at_all(self) -> None:
        assert _has_overlay(_world([])) == 0

    def test_a_plain_module_alone_is_not_an_overlay(self) -> None:
        assert _has_overlay(_world([("Other", None, True)])) == 0

    def test_an_overlay_module_is_found_even_when_not_applied(self) -> None:
        """The scan asks whether the object *carries* one, not whether it is on: an object whose
        only overlay is currently off must still take the rebuild path, or removing the last
        upgrade would leave the synthetic set in place."""
        assert _has_overlay(_world([("Other", "Command_A", False)])) == 1

    def test_a_foreign_module_is_skipped(self) -> None:
        """Anything whose first dword is not `CommandSetUpgrade`'s vtable is another module type,
        and reading `+0x13c` of its `ModuleData` would be reading a stranger's field."""
        world = _world([(None, "Command_A", True)])
        world.machine.write32(world.modules[0], MODULE_VTABLE ^ 0xFF)
        assert _has_overlay(world) == 0


class TestRebuild:
    def test_one_applied_overlay_builds_and_names_a_set(self) -> None:
        world = _world([(None, "Command_A", True)])
        world.machine.buttons["Command_A"] = 0xAAAA
        _rebuild(world)

        assert world.machine.override == "BaseSet+Command_A"
        assert world.machine.created == [("BaseSet+Command_A", 1)]
        assert world.machine.sets["BaseSet+Command_A"] == {0: 0xAAAA}

    def test_the_synthetic_set_is_created_mutable(self) -> None:
        """`setCommandButton` and `clearCommandButtons` both no-op on a set whose flag is not 1,
        so a set created with 0 would come out empty and silent."""
        world = _world([(None, "Command_A", True)])
        world.machine.buttons["Command_A"] = 0xAAAA
        _rebuild(world)
        assert world.machine.created[0][1] == 1

    def test_the_base_set_is_copied_in_before_the_overlay(self) -> None:
        world = _world([(None, "Command_A", True)])
        world.machine.buttons["Command_A"] = 0xAAAA
        base = world.machine.alloc(16)
        world.machine.set_names[base] = "BaseSet"
        world.machine.sets["BaseSet"] = {0: 0x1111, 2: 0x2222}
        _rebuild(world)

        built = world.machine.sets["BaseSet+Command_A"]
        assert built[0] == 0x1111 and built[2] == 0x2222
        assert built[1] == 0xAAAA, "the bare name should take the lowest free slot, which is 1"

    def test_a_numbered_slot_is_honoured(self) -> None:
        world = _world([(None, "Command_A:5", True)])
        world.machine.buttons["Command_A"] = 0xAAAA
        _rebuild(world)
        assert world.machine.sets["BaseSet+Command_A:5"] == {5: 0xAAAA}

    def test_a_numbered_slot_overwrites_the_base(self) -> None:
        world = _world([(None, "Command_A:2", True)])
        world.machine.buttons["Command_A"] = 0xAAAA
        base = world.machine.alloc(16)
        world.machine.set_names[base] = "BaseSet"
        world.machine.sets["BaseSet"] = {2: 0x2222}
        _rebuild(world)
        assert world.machine.sets["BaseSet+Command_A:2"] == {2: 0xAAAA}

    def test_several_tokens_in_one_module(self) -> None:
        world = _world([(None, "Command_A:7 Command_B", True)])
        world.machine.buttons.update({"Command_A": 0xAAAA, "Command_B": 0xBBBB})
        _rebuild(world)
        assert world.machine.sets["BaseSet+Command_A:7 Command_B"] == {7: 0xAAAA, 0: 0xBBBB}

    def test_several_modules_accumulate(self) -> None:
        """The point of the patch: two upgrades, two modules, one set carrying both buttons."""
        world = _world([(None, "Command_A:3", True), (None, "Command_B:4", True)])
        world.machine.buttons.update({"Command_A": 0xAAAA, "Command_B": 0xBBBB})
        _rebuild(world)

        assert world.machine.override == "BaseSet+Command_A:3+Command_B:4"
        assert _built(world) == {3: 0xAAAA, 4: 0xBBBB}

    def test_an_unapplied_module_contributes_nothing(self) -> None:
        world = _world([(None, "Command_A:3", True), (None, "Command_B:4", False)])
        world.machine.buttons.update({"Command_A": 0xAAAA, "Command_B": 0xBBBB})
        _rebuild(world)
        assert world.machine.override == "BaseSet+Command_A:3"
        assert _built(world) == {3: 0xAAAA}

    def test_self_is_counted_as_the_caller_says_and_not_as_its_latch_says(self) -> None:
        """`giveSelfUpgrade` runs the implementation *before* it sets the latch and
        `unUpgradeImplementation` runs while the latch is still set, so neither hook can trust it
        for its own module. Both directions are exercised here."""
        world = _world([(None, "Command_A:3", False)])
        world.machine.buttons["Command_A"] = 0xAAAA
        _rebuild(world, self_module=world.modules[0], self_applied=1)
        assert world.machine.override == "BaseSet+Command_A:3"

        world = _world([(None, "Command_A:3", True)])
        world.machine.buttons["Command_A"] = 0xAAAA
        _rebuild(world, self_module=world.modules[0], self_applied=0)
        assert world.machine.override == ""

    def test_no_applied_overlay_clears_the_override(self) -> None:
        """An empty name is how `Object+0x43C` is reset, which is what lets
        `getCommandSetString` fall back through to the template."""
        world = _world([(None, "Command_A", False)])
        _rebuild(world)
        assert world.machine.override == ""
        assert world.machine.created == []

    def test_a_plain_module_supplies_the_base(self) -> None:
        world = _world([("SwappedSet", None, True), (None, "Command_A", True)])
        world.machine.buttons["Command_A"] = 0xAAAA
        base = world.machine.alloc(16)
        world.machine.set_names[base] = "SwappedSet"
        world.machine.sets["SwappedSet"] = {0: 0x9999}
        _rebuild(world)

        assert world.machine.override == "SwappedSet+Command_A"
        assert world.machine.sets["SwappedSet+Command_A"] == {0: 0x9999, 1: 0xAAAA}

    def test_the_last_applied_plain_module_wins_the_base(self) -> None:
        """Which is the stock last-writer rule: two `CommandSetUpgrade`s that both fire leave the
        object showing the later one's set."""
        world = _world([("First", None, True), ("Second", None, True), (None, "Command_A", True)])
        world.machine.buttons["Command_A"] = 0xAAAA
        _rebuild(world)
        assert world.machine.override == "Second+Command_A"

    def test_a_plain_module_alone_still_gets_its_set(self) -> None:
        """The hooks route a plain module through here whenever the object carries any overlay,
        so the plain behaviour has to come out of the rebuild unchanged."""
        world = _world([("SwappedSet", None, True), (None, "Command_A", False)])
        _rebuild(world)
        assert world.machine.override == "SwappedSet"
        assert world.machine.created == []

    def test_an_unresolved_button_is_skipped_rather_than_placed(self) -> None:
        world = _world([(None, "Command_Missing Command_A", True)])
        world.machine.buttons["Command_A"] = 0xAAAA
        _rebuild(world)
        assert world.machine.buttons_looked_up == ["Command_Missing", "Command_A"]
        assert _built(world) == {0: 0xAAAA}

    def test_a_second_rebuild_reuses_the_cached_set(self) -> None:
        """The name is the cache key; building the same combination twice must not allocate a
        second `CommandSet`, because `newCommandSet` always allocates and overwrites the map."""
        world = _world([(None, "Command_A", True)])
        world.machine.buttons["Command_A"] = 0xAAAA
        _rebuild(world)
        _rebuild(world)
        assert len(world.machine.created) == 1
        assert world.machine.override_calls == 2

    def test_the_store_is_marked_dirty_and_the_object_reselected(self) -> None:
        world = _world([(None, "Command_A", True)])
        world.machine.buttons["Command_A"] = 0xAAAA
        _rebuild(world)
        store = world.machine.read32(THE_COMMAND_SET_STORE)
        assert world.machine.read8(store + COMMAND_SET_STORE_DIRTY_OFFSET) == 1
        assert world.machine.deselected == [world.obj]
        assert world.machine.reselected == [world.obj]

    def test_the_bound_is_read_from_the_engine_at_run_time(self) -> None:
        """`commandset-limit` widens `setCommandButton`'s guard; the free-slot search has to see
        the same number, or a mod running both would never reach the slots the other opened."""
        world = _world([(None, "Command_A", True)], bound=64)
        world.machine.buttons["Command_A"] = 0xAAAA
        base = world.machine.alloc(16)
        world.machine.set_names[base] = "BaseSet"
        world.machine.sets["BaseSet"] = dict.fromkeys(range(40), 0x1111)
        _rebuild(world)
        assert _built(world)[40] == 0xAAAA

    def test_no_free_slot_drops_the_button_rather_than_the_set(self) -> None:
        world = _world([(None, "Command_A", True)], bound=4)
        world.machine.buttons["Command_A"] = 0xAAAA
        base = world.machine.alloc(16)
        world.machine.set_names[base] = "BaseSet"
        world.machine.sets["BaseSet"] = dict.fromkeys(range(4), 0x1111)
        _rebuild(world)
        assert _built(world) == dict.fromkeys(range(4), 0x1111)

    def test_a_bare_colon_is_not_slot_zero(self) -> None:
        """`Command_A:` with nothing after it is a typo, and reading it as slot 0 would silently
        overwrite the first button of the base set."""
        world = _world([(None, "Command_A:", True)])
        world.machine.buttons["Command_A"] = 0xAAAA
        base = world.machine.alloc(16)
        world.machine.set_names[base] = "BaseSet"
        world.machine.sets["BaseSet"] = {0: 0x1111}
        _rebuild(world)
        built = _built(world)
        assert built[0] == 0x1111 and built[1] == 0xAAAA

    def test_leading_and_repeated_separators_are_tolerated(self) -> None:
        world = _world([(None, "  Command_A   Command_B  ", True)])
        world.machine.buttons.update({"Command_A": 0xAAAA, "Command_B": 0xBBBB})
        _rebuild(world)
        assert world.machine.buttons_looked_up == ["Command_A", "Command_B"]

    def test_a_two_digit_slot(self) -> None:
        world = _world([(None, "Command_A:12", True)], bound=33)
        world.machine.buttons["Command_A"] = 0xAAAA
        _rebuild(world)
        assert _built(world) == {12: 0xAAAA}

    def test_an_over_long_name_is_truncated_rather_than_overrunning_the_frame(self) -> None:
        """The copy is bounded by `MAX_NAME`; what a longer token buys is a failed lookup, which
        is the same outcome as a misspelling."""
        long_name = "C" * (MAX_NAME + 20)
        world = _world([(None, long_name, True)])
        _rebuild(world)
        assert world.machine.buttons_looked_up == ["C" * MAX_NAME]

    def test_a_foreign_module_between_two_overlays_is_stepped_over(self) -> None:
        world = _world(
            [(None, "Command_A:1", True), (None, "Command_X:2", True), (None, "Command_B:3", True)]
        )
        world.machine.write32(world.modules[1], MODULE_VTABLE ^ 0xFF)
        world.machine.buttons.update({"Command_A": 0xAAAA, "Command_B": 0xBBBB})
        _rebuild(world)
        assert world.machine.override == "BaseSet+Command_A:1+Command_B:3"
        assert _built(world) == {1: 0xAAAA, 3: 0xBBBB}


def _run_until_it_leaves_the_cave(world: World, limit: int = 100_000) -> int:
    """Step until `eip` is outside the cave, and return where it went.

    A hook's passthrough ends in a `jmp` back into the stock function, which this image does not
    hold - so "where it jumped to" is the assertion, and stepping is what makes it available.
    """
    cpu = world.cpu
    for _ in range(limit):
        if not cpu.code_va <= cpu.eip < cpu.code_va + len(cpu.code):
            return cpu.eip
        cpu.step()
    raise AssertionError("the routine never left the cave")


def _enter_hook(world: World, label: str, module: int) -> Machine:
    """Set the machine up as the engine does at either implementation's first byte."""
    m = world.machine
    m.write32(module + MODULE_OBJECT_PTR_OFFSET, world.obj)
    m.regs["esp"] = _STACK_TOP
    m.regs["ecx"] = module + MUX_OFFSET
    m.regs["esi"], m.regs["edi"] = 0x11111111, 0x22222222  # to be seen saved, or not
    world.enter(label)
    return m


class TestPassthrough:
    """The arm that has to leave a mod that does not use the keyword exactly as it was."""

    def test_the_upgrade_hook_falls_back_into_the_stock_function(self) -> None:
        world = _world([("Other", None, True)])
        m = _enter_hook(world, "hook_upgrade", world.modules[0])
        assert _run_until_it_leaves_the_cave(world) == UPGRADE_IMPL_RESUME
        assert m.override is None, "the passthrough must not have rebuilt anything"

    def test_the_upgrade_passthrough_arrives_as_the_stock_prologue_left_it(self) -> None:
        """It resumes four instructions into the stock function, so it has to *be* those four:
        `esi` and `edi` saved in that order, `esi` the interface and `ecx` the module."""
        world = _world([("Other", None, True)])
        module = world.modules[0]
        m = _enter_hook(world, "hook_upgrade", module)
        _run_until_it_leaves_the_cave(world)

        assert m.regs["esi"] == module + MUX_OFFSET  # mov esi, ecx
        assert m.regs["ecx"] == module  # lea ecx, [esi-0x10]
        assert m.regs["esp"] == _STACK_TOP - 4 - 8  # the sentinel, then two pushes
        assert m.read32(m.regs["esp"]) == 0x22222222  # push edi, last
        assert m.read32(m.regs["esp"] + 4) == 0x11111111  # push esi, first

    def test_the_un_upgrade_passthrough_restores_eax_and_touches_nothing_else(self) -> None:
        """The five displaced bytes are the `mov eax, imm32` that hands `__EH_prolog` its handler
        table, and it resumes on the `call` itself - so `eax` must be back and `esp` untouched, or
        the stock function gets a garbage SEH frame."""
        world = _world([("Other", None, True)])
        m = _enter_hook(world, "hook_unupgrade", world.modules[0])
        assert _run_until_it_leaves_the_cave(world) == UNUPGRADE_IMPL_RESUME

        assert m.regs["eax"] == UNUPGRADE_EH_EAX
        assert m.regs["esp"] == _STACK_TOP - 4  # only the sentinel
        assert m.override is None

    def test_an_overlay_object_does_not_take_the_passthrough(self) -> None:
        world = _world([(None, "Command_A", True)])
        world.machine.buttons["Command_A"] = 0xAAAA
        m = _enter_hook(world, "hook_upgrade", world.modules[0])
        world.cpu.run()

        assert m.override == "BaseSet+Command_A"
        assert m.regs["esp"] == _STACK_TOP, "the hook did not balance the stack"


class TestUnUpgradeHook:
    """The half that runs on every `Object::updateUpgradeModules` pass, and makes removal work."""

    def test_it_does_nothing_when_the_module_is_not_applied(self) -> None:
        """Its first act is the stock latch guard: a module that never fired has nothing to undo,
        and rebuilding from here would fight whichever module *is* applied."""
        world = _world([(None, "Command_A", False)])
        m = _enter_hook(world, "hook_unupgrade", world.modules[0])
        world.cpu.run()
        assert m.override is None
        assert m.regs["esp"] == _STACK_TOP

    def test_it_rebuilds_without_itself_and_clears_the_latch(self) -> None:
        world = _world([(None, "Command_A:1", True), (None, "Command_B:2", True)])
        world.machine.buttons.update({"Command_A": 0xAAAA, "Command_B": 0xBBBB})
        m = _enter_hook(world, "hook_unupgrade", world.modules[0])
        world.cpu.run()

        assert m.override == "BaseSet+Command_B:2"
        assert m.sets[m.override] == {2: 0xBBBB}
        assert m.anim_cleared == [world.modules[0]], "on the module, not the interface"
        assert m.read8(world.modules[0] + MODULE_LATCH_OFFSET) == 0
        assert m.read8(world.modules[1] + MODULE_LATCH_OFFSET) == 1
        assert m.regs["esp"] == _STACK_TOP

    def test_undoing_the_only_overlay_restores_the_stock_chain(self) -> None:
        world = _world([(None, "Command_A", True)])
        world.machine.buttons["Command_A"] = 0xAAAA
        m = _enter_hook(world, "hook_unupgrade", world.modules[0])
        world.cpu.run()
        assert m.override == "", "an empty override is what falls back to the template"


class TestHookBytes:
    """What the two hook sites hold, which the interpreter cannot see because it starts inside."""

    def test_the_upgrade_hook_re_emits_the_displaced_bytes_then_jumps_back(self) -> None:
        data = _patched(commandset_button_upgrade_image())
        section_va, content = _cave(data)
        target = _jmp_target(data, UPGRADE_IMPL_VA)
        window = content[target - section_va : target - section_va + 64]
        assert UPGRADE_IMPL_BYTES in window
        start = window.index(UPGRADE_IMPL_BYTES) + len(UPGRADE_IMPL_BYTES)
        assert window[start] == 0xE9
        displacement = struct.unpack("<i", window[start + 1 : start + 5])[0]
        assert target + start + 5 + displacement == UPGRADE_IMPL_RESUME

    def test_the_un_upgrade_hook_re_emits_the_displaced_bytes_then_jumps_back(self) -> None:
        data = _patched(commandset_button_upgrade_image())
        section_va, content = _cave(data)
        target = _jmp_target(data, UNUPGRADE_IMPL_VA)
        window = content[target - section_va : target - section_va + 64]
        assert UNUPGRADE_IMPL_BYTES in window
        start = window.index(UNUPGRADE_IMPL_BYTES) + len(UNUPGRADE_IMPL_BYTES)
        assert window[start] == 0xE9
        displacement = struct.unpack("<i", window[start + 1 : start + 5])[0]
        assert target + start + 5 + displacement == UNUPGRADE_IMPL_RESUME


class TestShims:
    """The constructor and destructor shims, which run before there is a frame to inspect."""

    def test_the_constructor_shim_zeroes_the_new_field_then_assigns_the_old_one(self) -> None:
        world = _world([])
        m = world.machine
        module_data = m.alloc(0x200)
        m.write32(module_data + COMMAND_BUTTONS_OFFSET, 0xDEADBEEF)  # uninitialised heap
        source = m.alloc(4)
        m.write_field(source, "TheDefault")

        m.regs["esp"] = _STACK_TOP
        m.push(source)
        m.regs["ecx"] = module_data + COMMAND_SET_OFFSET
        world.enter("ctor_shim")
        landed = _run_until_it_leaves_the_cave(world)

        # The assign itself is the engine's and is left unrun here; what the shim owes is the
        # zeroed field, `ecx` still on the old one, and the argument still on the stack for it.
        assert landed == ASCII_STRING_ASSIGN, "the shim must tail-call the call it displaced"
        assert m.read32(module_data + COMMAND_BUTTONS_OFFSET) == 0
        assert m.regs["ecx"] == module_data + COMMAND_SET_OFFSET
        assert m.read32(m.regs["esp"] + 4) == source

    def test_the_destructor_shim_releases_both_strings(self) -> None:
        world = _world([])
        m = world.machine
        module_data = m.alloc(0x200)
        m.write_field(module_data + COMMAND_SET_OFFSET, "TheSet")
        m.write_field(module_data + COMMAND_BUTTONS_OFFSET, "Command_A")

        m.regs["esp"] = _STACK_TOP
        m.regs["ecx"] = module_data + COMMAND_SET_OFFSET
        world.enter("dtor_shim")
        landed = _run_until_it_leaves_the_cave(world)

        assert landed == ASCII_STRING_DTOR, "the shim must tail-call the call it displaced"
        assert m.read32(module_data + COMMAND_BUTTONS_OFFSET) == 0
        assert m.regs["ecx"] == module_data + COMMAND_SET_OFFSET, "the tail call's `this`"
