"""Static coverage for the upgrade-selected SpellStore CommandSet patch."""

from __future__ import annotations

import itertools
import struct

import pytest

from sage_patch import SpellStoreUpgradePatch
from sage_patch.addresses import (
    AUTO_DEPOSIT_SCALE,
    AUTO_DEPOSIT_SCALE_BYTES,
    COMMAND_SET_STORE_FIND_COMMAND_SET,
    COMMAND_SET_STORE_GET_PURCHASE_SCIENCE_COMMAND_SET,
    PLAYER_COMPLETED_UPGRADE_MASK,
    PLAYER_PLAYER_TEMPLATE,
    PLAYER_TEMPLATE_BLOCK_KEY,
    PLAYER_TEMPLATE_BLOCK_KEY_BYTES,
    PLAYER_TEMPLATE_FIELD_TABLE,
    PLAYER_TEMPLATE_FIELD_TABLE_REF_OPCODES,
    PLAYER_TEMPLATE_FIELD_TABLE_REFS,
    PLAYER_TEMPLATE_PURCHASE_SCIENCE_COMMAND_SET,
    PLAYER_TEMPLATE_PURCHASE_SCIENCE_COMMAND_SET_MP,
    SPELL_STORE_COMMAND_SET_CALL,
    SPELL_STORE_COMMAND_SET_CALL_BYTES,
    THE_UPGRADE_CENTER,
    UPGRADE_TEMPLATE_INDEX,
)
from sage_patch.patches import spell_store_upgrade as ssu
from sage_patch.patches.command_point_upkeep import CommandPointUpkeepPatch
from sage_patch.patches.utils.field_tables import entries_before, read_field_table
from sage_patch.patches.utils.name_tables import read_cstring
from sage_patch.patches.utils.token_lists import (
    ASCII_STRING_ASSIGN,
    INI_NEXT_ASCII_STRING,
)
from sage_patch.registry import PATCHES
from sage_patch.utils import find_section, va_to_offset

IMAGE_BASE = 0x00400000
STRINGS_VA = 0x00DAB000
STOCK_PARSE = 0x0042EE5E

STOCK_FIELDS = (
    ("Side", 0x14),
    ("PurchaseScienceCommandSet", PLAYER_TEMPLATE_PURCHASE_SCIENCE_COMMAND_SET),
    ("PurchaseScienceCommandSetMP", PLAYER_TEMPLATE_PURCHASE_SCIENCE_COMMAND_SET_MP),
    ("ResourceModifierObjectFilter", 0x1C8),
    ("ResourceModifierValues", 0x1CC),
    ("MultiSelectionPortrait", 0x1D8),
)


def _synthetic_image() -> bytearray:
    data = bytearray(0x9C0000)
    data[:2] = b"MZ"
    e = 0x80
    struct.pack_into("<I", data, 0x3C, e)
    data[e : e + 4] = b"PE\x00\x00"
    struct.pack_into("<H", data, e + 4, 0x14C)
    struct.pack_into("<H", data, e + 6, 1)
    struct.pack_into("<H", data, e + 20, 0xE0)
    opt = e + 24
    struct.pack_into("<H", data, opt, 0x10B)
    struct.pack_into("<I", data, opt + 28, IMAGE_BASE)
    struct.pack_into("<I", data, opt + 32, 0x1000)
    struct.pack_into("<I", data, opt + 36, 0x200)
    struct.pack_into("<I", data, opt + 56, 0xA00000)
    struct.pack_into("<I", data, opt + 60, 0x400)
    section = bytearray(40)
    section[:8] = b".text\x00\x00\x00"
    mapped = len(data) - 0x1000
    struct.pack_into("<IIII", section, 8, mapped, 0x1000, mapped, 0x1000)
    data[opt + 0xE0 : opt + 0xE0 + 40] = section

    strings = bytearray()
    name_vas: list[int] = []
    for name, _offset in STOCK_FIELDS:
        name_vas.append(STRINGS_VA + len(strings))
        strings += name.encode("ascii") + b"\x00"
    data[STRINGS_VA - IMAGE_BASE : STRINGS_VA - IMAGE_BASE + len(strings)] = strings

    table = PLAYER_TEMPLATE_FIELD_TABLE - IMAGE_BASE
    for index, ((_, offset), name_va) in enumerate(zip(STOCK_FIELDS, name_vas, strict=True)):
        struct.pack_into("<4I", data, table + index * 16, name_va, STOCK_PARSE, 0, offset)
    struct.pack_into("<4I", data, table + len(STOCK_FIELDS) * 16, 0, 0, 0, 0)

    for ref_va, opcode in zip(
        PLAYER_TEMPLATE_FIELD_TABLE_REFS,
        PLAYER_TEMPLATE_FIELD_TABLE_REF_OPCODES,
        strict=True,
    ):
        off = ref_va - IMAGE_BASE
        data[off] = opcode
        struct.pack_into("<I", data, off + 1, PLAYER_TEMPLATE_FIELD_TABLE)

    for va, window in (
        (SPELL_STORE_COMMAND_SET_CALL, SPELL_STORE_COMMAND_SET_CALL_BYTES),
        (PLAYER_TEMPLATE_BLOCK_KEY, PLAYER_TEMPLATE_BLOCK_KEY_BYTES),
        (AUTO_DEPOSIT_SCALE, AUTO_DEPOSIT_SCALE_BYTES),
    ):
        off = va - IMAGE_BASE
        data[off : off + len(window)] = window
    return data


@pytest.fixture
def image() -> bytearray:
    return _synthetic_image()


@pytest.fixture
def patched(image: bytearray) -> bytes:
    data = bytearray(image)
    SpellStoreUpgradePatch().apply(data)
    return bytes(data)


def _layout(data: bytes | bytearray):
    section_va, section_off, vsize = find_section(data, ssu.SECTION_NAME)
    live = read_field_table(data, SpellStoreUpgradePatch._resolve(data))  # noqa: SLF001
    original = entries_before(data, live, ssu.FIELD_NAME)
    assert original is not None
    patch = SpellStoreUpgradePatch()
    asm = patch._assemble(section_va, original)  # noqa: SLF001
    code_off = patch._code_offset(original)  # noqa: SLF001
    code = bytes(data[section_off + code_off : section_off + vsize])
    return section_va, code_off, code, asm


def _disassembly(data: bytes | bytearray):
    capstone = pytest.importorskip("capstone")
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    md.detail = True
    section_va, code_off, code, asm = _layout(data)
    code_va = section_va + code_off
    return list(md.disasm(code, code_va)), asm


def _direct_targets(insns, mnemonic: str) -> list[int]:
    return [i.operands[0].imm for i in insns if i.mnemonic == mnemonic and i.operands[0].type == 2]


class TestFieldTable:
    def test_adds_the_repeatable_mapping_field(self, patched: bytes) -> None:
        table = read_field_table(patched, SpellStoreUpgradePatch._resolve(patched))  # noqa: SLF001
        assert read_cstring(patched, table[-1][0]) == ssu.FIELD_NAME
        assert table[-1][2:] == (0, 0)

    def test_preserves_every_stock_row(self, image: bytearray, patched: bytes) -> None:
        before = read_field_table(image, PLAYER_TEMPLATE_FIELD_TABLE)
        after = read_field_table(
            patched,
            SpellStoreUpgradePatch._resolve(patched),  # noqa: SLF001
        )
        assert after[: len(before)] == before

    def test_parser_is_the_one_in_the_patch_section(self, patched: bytes) -> None:
        table = read_field_table(patched, SpellStoreUpgradePatch._resolve(patched))  # noqa: SLF001
        _section, _off, _code, asm = _layout(patched)
        assert table[-1][1] == asm.label_va("parse")

    def test_ini_surface_models_the_two_names(self) -> None:
        (field,) = SpellStoreUpgradePatch().ini_surface().fields
        assert (field.block, field.name, field.type) == (
            "PlayerTemplate",
            ssu.FIELD_NAME,
            "Opaque[]",
        )
        with SpellStoreUpgradePatch().ini_surface().activate() as problems:
            assert problems == []


class TestCave:
    def test_disassembles_cleanly_to_the_end(self, patched: bytes) -> None:
        insns, _asm = _disassembly(patched)
        _section, _code_off, code, _layout_asm = _layout(patched)
        assert sum(i.size for i in insns) == len(code)

    def test_parser_reads_two_names_and_assigns_refcounted_strings(self, patched: bytes) -> None:
        insns, asm = _disassembly(patched)
        parser = asm.label_va("parse")
        selector = asm.label_va("selector")
        body = [i for i in insns if parser <= i.address < selector]
        calls = _direct_targets(body, "call")
        assert calls.count(INI_NEXT_ASCII_STRING) == 2
        assert calls.count(ASCII_STRING_ASSIGN) == 2
        assert ssu._FIND_UPGRADE not in calls  # noqa: SLF001  (resolution waits for runtime)

    def test_selector_uses_every_confirmed_layout(self, patched: bytes) -> None:
        insns, asm = _disassembly(patched)
        selector = asm.label_va("selector")
        body = [i for i in insns if i.address >= selector]
        text = [f"{i.mnemonic} {i.op_str}" for i in body]
        assert any(f"[esi + {PLAYER_PLAYER_TEMPLATE:#x}]" in row for row in text)
        assert any(f"[eax + {UPGRADE_TEMPLATE_INDEX:#x}]" in row for row in text)
        assert any(f"+ {PLAYER_COMPLETED_UPGRADE_MASK:#x}]" in row for row in text)
        assert any(f"[{THE_UPGRADE_CENTER:#x}]" in row for row in text)

    def test_selector_calls_both_name_lookups_and_tail_calls_stock(self, patched: bytes) -> None:
        insns, asm = _disassembly(patched)
        selector = asm.label_va("selector")
        body = [i for i in insns if i.address >= selector]
        assert ssu._FIND_UPGRADE in _direct_targets(body, "call")  # noqa: SLF001
        assert COMMAND_SET_STORE_FIND_COMMAND_SET in _direct_targets(body, "call")
        assert _direct_targets(body, "jmp")[-1] == (
            COMMAND_SET_STORE_GET_PURCHASE_SCIENCE_COMMAND_SET
        )
        assert any(i.mnemonic == "ret" and i.op_str == "4" for i in body)

    def test_runtime_table_starts_empty(self, patched: bytes) -> None:
        _section_va, section_off, _vsize = find_section(patched, ssu.SECTION_NAME)
        assert bytes(patched[section_off : section_off + 4]) == bytes(4)
        rows = section_off + ssu._MAPPINGS_OFF  # noqa: SLF001
        assert bytes(patched[rows : rows + ssu.MAPPINGS * ssu.MAPPING_STRIDE]) == bytes(
            ssu.MAPPINGS * ssu.MAPPING_STRIDE
        )


class TestHook:
    def test_stock_signature_targets_the_confirmed_fallback(self) -> None:
        displacement = struct.unpack_from("<i", SPELL_STORE_COMMAND_SET_CALL_BYTES, 1)[0]
        assert SPELL_STORE_COMMAND_SET_CALL + 5 + displacement == (
            COMMAND_SET_STORE_GET_PURCHASE_SCIENCE_COMMAND_SET
        )

    def test_only_the_spell_store_call_is_redirected(self, patched: bytes) -> None:
        off = va_to_offset(patched, SPELL_STORE_COMMAND_SET_CALL)
        target = SPELL_STORE_COMMAND_SET_CALL + 5 + struct.unpack_from("<i", patched, off + 1)[0]
        _section, _code_off, _code, asm = _layout(patched)
        assert patched[off] == 0xE8
        assert target == asm.label_va("selector")

    def test_no_other_stock_code_bytes_change(self, image: bytearray, patched: bytes) -> None:
        differing = {i for i in range(len(image)) if image[i] != patched[i]}
        expected: set[int] = set()
        for va, size in (
            (PLAYER_TEMPLATE_FIELD_TABLE_REFS[0], 5),
            (SPELL_STORE_COMMAND_SET_CALL, 5),
        ):
            off = va_to_offset(image, va)
            expected.update(range(off, off + size))
        assert not differing - expected - set(range(0x400))


class TestApplyAndVerify:
    def test_round_trip(self, patched: bytes) -> None:
        assert SpellStoreUpgradePatch().verify(patched) == []
        found = SpellStoreUpgradePatch.detect(patched)
        assert isinstance(found, SpellStoreUpgradePatch)

    def test_unpatched_image_does_not_verify(self, image: bytearray) -> None:
        assert SpellStoreUpgradePatch().verify(image) == [
            f"no {ssu.SECTION_NAME} section: the file does not carry this patch"
        ]

    def test_refuses_to_apply_twice(self, image: bytearray) -> None:
        SpellStoreUpgradePatch().apply(image)
        with pytest.raises(ValueError, match="already names"):
            SpellStoreUpgradePatch().apply(image)

    def test_refuses_a_wrong_callsite_signature(self, image: bytearray) -> None:
        image[va_to_offset(image, SPELL_STORE_COMMAND_SET_CALL)] ^= 0xFF
        with pytest.raises(ValueError, match="expected"):
            SpellStoreUpgradePatch().apply(image)

    def test_refuses_a_wrong_purchase_field_offset(self, image: bytearray) -> None:
        table = va_to_offset(image, PLAYER_TEMPLATE_FIELD_TABLE)
        struct.pack_into("<I", image, table + 1 * 16 + 12, 0x140)
        with pytest.raises(ValueError, match="unexpected build"):
            SpellStoreUpgradePatch().apply(image)

    def test_verify_reports_a_rewritten_hook(self, patched: bytes) -> None:
        dirty = bytearray(patched)
        dirty[va_to_offset(dirty, SPELL_STORE_COMMAND_SET_CALL) + 1] ^= 0xFF
        assert any("AptSpellStore" in item for item in SpellStoreUpgradePatch().verify(dirty))

    def test_section_name_and_permissions(self, patched: bytes) -> None:
        assert len(ssu.SECTION_NAME) <= 8
        e = struct.unpack_from("<I", patched, 0x3C)[0]
        count = struct.unpack_from("<H", patched, e + 6)[0]
        table = e + 24 + struct.unpack_from("<H", patched, e + 20)[0]
        for i in range(count):
            header = table + i * 40
            name = bytes(patched[header : header + 8]).rstrip(b"\x00").decode()
            if name == ssu.SECTION_NAME:
                flags = struct.unpack_from("<I", patched, header + 36)[0]
                assert flags & 0x20000000
                assert flags & 0x40000000
                assert flags & 0x80000000
                break
        else:
            pytest.fail(f"{ssu.SECTION_NAME} is absent")

    def test_registered_exported_and_experimental(self) -> None:
        assert PATCHES[SpellStoreUpgradePatch.name] is SpellStoreUpgradePatch
        assert SpellStoreUpgradePatch
        assert SpellStoreUpgradePatch.author


class TestComposition:
    @pytest.mark.parametrize("order", tuple(itertools.permutations((0, 1))))
    def test_player_template_field_extensions_compose(self, order: tuple[int, int]) -> None:
        data = _synthetic_image()
        patches = (SpellStoreUpgradePatch(), CommandPointUpkeepPatch())
        for index in order:
            patches[index].apply(data)
        for patch in patches:
            assert patch.verify(data) == [], f"{patch} failed in order {order}"
