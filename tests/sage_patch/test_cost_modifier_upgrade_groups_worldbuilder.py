"""Editor parser compatibility, native append ABI and preservation of existing module data."""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

from sage_ini.engine import STOCK
from sage_patch import (
    CostModifierUpgradeGroupsPatch,
    CostModifierUpgradeGroupsWorldbuilderPatch,
)
from sage_patch import addresses as ad
from sage_patch.__main__ import main
from sage_patch.patches import (
    GrantScienceUpgradeWorldbuilderPatch,
    ObjectImageUpgradeWorldbuilderPatch,
    SpecialPowerRefundUpgradeWorldbuilderPatch,
)
from sage_patch.patches.economy import cost_modifier_upgrade_groups as cmug
from sage_patch.patches.worldbuilder.worldbuilder_silent_errors import WorldbuilderSilentErrorsPatch
from sage_patch.registry import PATCHES
from sage_patch.utils import file_offset, find_section, read_cstring

from .synthetic import _sparse_image, cost_modifier_upgrade_groups_image

SITE = ad.WORLDBUILDER_COST_MODIFIER_UPGRADE_FIELD_APPEND_CALL
BUILD_FIELDS = ad.WORLDBUILDER_COST_MODIFIER_UPGRADE_BUILD_FIELDS
TABLE = ad.WORLDBUILDER_COST_MODIFIER_UPGRADE_FIELD_TABLE
ANCHORS = ad.WORLDBUILDER_COST_MODIFIER_UPGRADE_ANCHORS
PATCH = CostModifierUpgradeGroupsWorldbuilderPatch


def image() -> bytearray:
    return _sparse_image(
        {**ANCHORS, SITE: ad.WORLDBUILDER_COST_MODIFIER_UPGRADE_FIELD_APPEND_CALL_BYTES}
    )


@pytest.fixture(scope="module")
def reference() -> bytes:
    path = Path(__file__).resolve().parents[2] / "tools/BFME-FILES/Worldbuilder.exe.backup"
    if not path.exists():
        pytest.skip("RotWK editor reference backup unavailable")
    return path.read_bytes()


def test_registration_apply_verify_scope_and_second_application() -> None:
    assert PATCHES[PATCH.name] is PATCH
    assert PATCH().ini_surface() == STOCK
    data, patch = image(), PATCH()
    before = bytes(data)
    assert patch.detect(data) is None
    patch.apply(data)
    assert patch.verify(data) == []
    assert isinstance(patch.detect(data), PATCH)
    section = find_section(data, cmug.WORLDBUILDER_SECTION_NAME)
    assert section is not None
    base, off, _size = section
    name, parser, user, offset = struct.unpack_from("<4I", data, off)
    assert read_cstring(data, name) == "DiscountGroup"
    assert parser == patch._assemble(base).label_va("parse")
    assert (user, offset) == (0, 0)
    assert data[off + 16 : off + 32] == bytes(16)
    hook = file_offset(data, SITE)
    assert all(
        a == b or hook <= n < hook + 5
        for n, (a, b) in enumerate(
            zip(before[0x1000:], data[0x1000 : len(before)], strict=True), 0x1000
        )
    )
    saved = bytes(data)
    with pytest.raises(ValueError, match="already carries"):
        patch.apply(data)
    assert data == saved


@pytest.mark.parametrize("va", [*ANCHORS, SITE])
def test_bad_build_is_rejected_before_mutation(va: int) -> None:
    data = image()
    data[file_offset(data, va)] ^= 1
    before = bytes(data)
    with pytest.raises(ValueError, match="expected Worldbuilder build"):
        PATCH().apply(data)
    assert data == before


@pytest.mark.parametrize("va", [0, *ANCHORS, SITE])
def test_verify_checks_helpers_hook_and_dependencies(va: int) -> None:
    data, patch = image(), PATCH()
    patch.apply(data)
    section = find_section(data, cmug.WORLDBUILDER_SECTION_NAME)
    assert section is not None
    data[file_offset(data, va) if va else section[1] + section[2] - 1] ^= 1
    assert patch.verify(data)
    assert patch.detect(data) is None


def test_cli_and_game_binary_rejection(tmp_path: Path) -> None:
    source, dest = tmp_path / "editor.exe", tmp_path / "patched.exe"
    source.write_bytes(image())
    assert main(["apply", PATCH.name, "--in", str(source), "--out", str(dest)]) == 0
    assert main(["verify", PATCH.name, str(dest)]) == 0
    assert source.read_bytes() == image()
    game = cost_modifier_upgrade_groups_image()
    before = bytes(game)
    with pytest.raises(ValueError, match="expected Worldbuilder build"):
        PATCH().apply(game)
    assert game == before
    assert CostModifierUpgradeGroupsPatch.detect(dest.read_bytes()) is None


def test_append_wrapper_preserves_arguments_and_callee_saved_registers() -> None:
    pytest.importorskip("unicorn")
    pytest.importorskip("pefile")
    from .save_machine import Machine  # noqa: PLC0415

    data, patch = image(), PATCH()
    patch.apply(data)
    section = find_section(data, cmug.WORLDBUILDER_SECTION_NAME)
    assert section is not None
    m = Machine(bytes(data))
    tables = m.alloc(0x84)
    registers = dict(esi=0x12345678, edi=0x23456789, ebx=0x34567890, ebp=0x456789AB)
    m.call(patch._assemble(section[0]).label_va("append"), 0x123456, 0x28, ecx=tables, **registers)
    assert m.read32(tables + 0x80) == 2
    assert (m.read32(tables), m.read32(tables + 0x40)) == (0x123456, 0x28)
    assert (m.read32(tables + 4), m.read32(tables + 0x44)) == (section[0], 0)
    assert all(m.reg(name) == value for name, value in registers.items())
    assert not m.faults


@pytest.mark.parametrize("token", [0, 0x123456])
def test_discard_parser_uses_ini_and_never_dereferences_object_pointers(token: int) -> None:
    x86 = pytest.importorskip("unicorn.x86_const")
    pytest.importorskip("pefile")
    from .save_machine import STACK, STACK_SIZE, Machine  # noqa: PLC0415

    data, patch = image(), PATCH()
    patch.apply(data)
    section = find_section(data, cmug.WORLDBUILDER_SECTION_NAME)
    assert section is not None
    m, calls = Machine(bytes(data)), []

    def next_token(machine: Machine) -> None:
        calls.append((machine.reg("ecx"), machine.arg(0)))
        machine.ret(4, token)

    m.stub(ad.WORLDBUILDER_INI_GET_NEXT_TOKEN, next_token)
    m.call(patch._assemble(section[0]).label_va("parse"), 0xABCDEF, 0xDEADBEEF, 0xBADF00D, 0)
    assert calls == [(0xABCDEF, 0)]
    # A field callback is cdecl: all four original arguments are still on the stack.
    assert m.uc.reg_read(x86.UC_X86_REG_ESP) == STACK + STACK_SIZE - 0x1000 - 16
    assert not m.faults


@pytest.mark.parametrize("reverse", [False, True])
def test_reference_editor_composes_with_other_upgrade_parsers(
    reference: bytes, reverse: bool
) -> None:
    data = bytearray(reference)
    patches = [
        PATCH(),
        ObjectImageUpgradeWorldbuilderPatch(),
        GrantScienceUpgradeWorldbuilderPatch(),
        SpecialPowerRefundUpgradeWorldbuilderPatch(),
        WorldbuilderSilentErrorsPatch(),
    ]
    for patch in reversed(patches) if reverse else patches:
        patch.apply(data)
    assert all(not patch.verify(data) for patch in patches)


class EditorParser:
    """Native field building and dispatch; model input, CRT tokens and absent macro definitions."""

    def __init__(self, reference: bytes, *, patched: bool):
        pytest.importorskip("unicorn")
        pytest.importorskip("pefile")
        from .save_machine import RETURN, Machine  # noqa: PLC0415

        data = bytearray(reference)
        if patched:
            PATCH().apply(data)
            assert PATCH().verify(data) == []
        self.m = m = Machine(bytes(data))
        self.return_address = RETURN
        self.tables = m.alloc(0x84)
        m.call(BUILD_FIELDS, self.tables)
        self.ini, self.obj = m.alloc(0x880), m.alloc(0x15C, b"\xa5" * 0x15C)
        self.separators, self.end = m.alloc(8, b" \t\r\n=\0"), m.alloc(4, b"End\0")
        m.write32(self.ini + 0x418, self.separators)
        m.write32(self.ini + 0x428, self.end)
        self.cursor = 0
        self.values = []
        self.read = []
        m.stub(0x006D1070, self.read_line)
        # INI::lookupDefine: these cases have no macros, so return the literal token.
        m.stub(0x006D0580, lambda machine: machine.ret(value=machine.arg(0)))
        m.write32(0x022F5188, m.stub(None, self.strtok))
        m.write32(0x022F4FF8, m.stub(None, self.stricmp))
        m.stop_at(0x006D1510)  # the native unknown-keyword branch, before diagnostic services

    def string(self, address):
        result = bytearray()
        while value := self.m.uc.mem_read(address + len(result), 1)[0]:
            result.append(value)
        return bytes(result)

    def read_line(self, m):
        line = next(self.lines)
        self.read.append(line)
        m.uc.mem_write(self.ini + 0x14, line.encode() + b"\0")
        m.ret()

    def strtok(self, m):
        if m.arg(0):
            self.cursor = m.arg(0)
        separators = self.string(m.arg(1))
        while self.cursor and m.uc.mem_read(self.cursor, 1)[0] in separators:
            self.cursor += 1
        start = self.cursor
        while self.cursor and (value := m.uc.mem_read(self.cursor, 1)[0]):
            if value in separators:
                m.uc.mem_write(self.cursor, b"\0")
                self.cursor += 1
                break
            self.cursor += 1
        if not start or not m.uc.mem_read(start, 1)[0]:
            m.ret(value=0)
        else:
            self.values.append(self.string(start))
            m.ret(value=start)

    def stricmp(self, m):
        m.ret(value=int(self.string(m.arg(0)).lower() != self.string(m.arg(1)).lower()))

    def run(self, lines):
        self.lines = iter([*lines, "End"])
        self.m.call(0x006D1310, self.obj, self.tables, ecx=self.ini)


@pytest.mark.parametrize("group", ["BlacksmithForging", '"Shared Forge"', ""])
def test_native_parser_accepts_discount_group_without_moduledata_writes(
    reference: bytes, group: str
):
    w = EditorParser(reference, patched=True)
    m = w.m
    before = bytes(m.uc.mem_read(w.obj, 0x15C))
    assert m.read32(w.tables + 0x80) == 3
    assert (m.read32(w.tables), m.read32(w.tables + 0x40)) == (0x01E97D40, 8)
    assert (m.read32(w.tables + 4), m.read32(w.tables + 0x44)) == (TABLE, 0)
    w.run([f"DiscountGroup = {group}"])
    assert m.stopped_at == w.return_address
    assert w.read[-1] == "End"
    assert bytes(m.uc.mem_read(w.obj, 0x15C)) == before
    assert not m.faults


def test_native_parser_keeps_existing_fields_and_unknown_keyword_errors(reference: bytes):
    stock = EditorParser(reference, patched=False)
    stock.run(["DiscountGroup = Shared"])
    assert stock.m.stopped_at == 0x006D1510

    patched = EditorParser(reference, patched=True)
    patched.run(["DiscountGroup = Shared", "UpgradeDiscount = Yes", "StartsActive = No"])
    assert patched.m.stopped_at == patched.return_address
    assert bytes(patched.m.uc.mem_read(patched.obj + 0x148, 2)) == b"\x01\x00"
    assert not patched.m.faults

    unknown = EditorParser(reference, patched=True)
    unknown.run(["DiscountGroup = Shared", "UnknownDiscountField = Shared"])
    assert unknown.m.stopped_at == 0x006D1510
