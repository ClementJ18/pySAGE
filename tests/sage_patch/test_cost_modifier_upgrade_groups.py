"""Structure, ABI and grouping semantics for ``cost-modifier-upgrade-groups``."""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

from sage_patch import addresses as ad
from sage_patch.patches.economy import cost_modifier_upgrade_groups as cmug
from sage_patch.patches.economy import player_upgrade_discount as pud
from sage_patch.patches.economy.cost_modifier_upgrade_groups import CostModifierUpgradeGroupsPatch
from sage_patch.patches.economy.player_upgrade_discount import PlayerUpgradeDiscountPatch
from sage_patch.registry import PATCHES
from sage_patch.utils import call_rel32, file_offset, find_section, read_cstring, u32

from .synthetic import cost_modifier_upgrade_groups_image


@pytest.fixture
def image() -> bytearray:
    return cost_modifier_upgrade_groups_image()


def test_registration_ini_surface_and_relocated_table(image: bytearray) -> None:
    patch = CostModifierUpgradeGroupsPatch()
    assert PATCHES[patch.name] is CostModifierUpgradeGroupsPatch
    (field,) = patch.ini_surface().fields
    assert (field.block, field.name, field.type, field.default) == (
        "CostModifierUpgrade",
        cmug.KEYWORD,
        "String",
        "",
    )

    patch.apply(image)
    assert patch.verify(image) == []
    located = find_section(image, cmug.SECTION_NAME)
    assert located is not None
    base, off, _size = located
    stock_size = len(cmug.COST_MODIFIER_UPGRADE_STOCK_FIELDS) * cmug.FIELD_ENTRY_SIZE
    name_va, parser, userdata, field_off = struct.unpack_from("<4I", image, off + stock_size)
    assert read_cstring(image, name_va) == cmug.KEYWORD
    assert (parser, userdata, field_off) == (
        ad.GAME_DATA_ASCIISTRING_PARSER,
        0,
        cmug.DISCOUNT_GROUP_OFFSET,
    )
    assert bytes(image[off + stock_size + 16 : off + stock_size + 32]) == bytes(16)
    assert bytes(
        image[
            file_offset(image, ad.COST_MODIFIER_UPGRADE_FIELD_TABLE_REF) : file_offset(
                image, ad.COST_MODIFIER_UPGRADE_FIELD_TABLE_REF
            )
            + 5
        ]
    ) == b"\x68" + u32(base)
    assert bytes(
        image[
            file_offset(image, ad.COST_MODIFIER_UPGRADE_MODULEDATA_SIZE_SITE) : file_offset(
                image, ad.COST_MODIFIER_UPGRADE_MODULEDATA_SIZE_SITE
            )
            + 5
        ]
    ) == b"\x68" + u32(cmug.PATCHED_MODULEDATA_SIZE)


@pytest.mark.parametrize(
    "va",
    [
        ad.COST_MODIFIER_UPGRADE_MODULEDATA_SIZE_SITE,
        ad.COST_MODIFIER_UPGRADE_MODULEDATA_CTOR_CALL,
        ad.COST_MODIFIER_UPGRADE_MODULEDATA_DTOR,
        ad.COST_MODIFIER_UPGRADE_FIELD_TABLE_REF,
        ad.PLAYER_ADD_UPGRADE_DISCOUNT_RECORD,
        ad.PLAYER_REMOVE_UPGRADE_DISCOUNT_RECORD,
        ad.COST_MODIFIER_PALANTIR_UPGRADE_QUERY,
        *[va for va, _blob, _what in cmug._ANCHORS],
    ],
)
def test_wrong_build_is_rejected_before_mutation(image: bytearray, va: int) -> None:
    off = file_offset(image, va)
    image[off] ^= 1
    before = bytes(image)
    with pytest.raises(ValueError, match="expected build"):
        CostModifierUpgradeGroupsPatch().apply(image)
    assert image == before


@pytest.mark.parametrize("damage", ["cave", "size", "add", "remove", "ui", "anchor"])
def test_verify_detects_corruption(image: bytearray, damage: str) -> None:
    patch = CostModifierUpgradeGroupsPatch()
    patch.apply(image)
    located = find_section(image, cmug.SECTION_NAME)
    assert located is not None
    off = {
        "cave": located[1],
        "size": file_offset(image, ad.COST_MODIFIER_UPGRADE_MODULEDATA_SIZE_SITE),
        "add": file_offset(image, ad.PLAYER_ADD_UPGRADE_DISCOUNT_RECORD),
        "remove": file_offset(image, ad.PLAYER_REMOVE_UPGRADE_DISCOUNT_RECORD),
        "ui": file_offset(image, ad.COST_MODIFIER_PALANTIR_UPGRADE_QUERY),
        "anchor": file_offset(image, ad.ASCII_STRING_COMPARE),
    }[damage]
    image[off] ^= 1
    assert patch.verify(image)
    assert CostModifierUpgradeGroupsPatch.detect(image) is None


@pytest.mark.parametrize("grouped", [False, True])
def test_add_and_remove_use_the_same_optional_group_key(image: bytearray, grouped: bool) -> None:
    x86 = pytest.importorskip("unicorn.x86_const")
    pytest.importorskip("pefile")
    from .save_machine import Machine  # noqa: PLC0415

    patch = CostModifierUpgradeGroupsPatch()
    patch.apply(image)
    located = find_section(image, cmug.SECTION_NAME)
    assert located is not None
    _content, labels = patch._section(image, located[0])
    m = Machine(bytes(image))
    module_data = m.alloc(cmug.PATCHED_MODULEDATA_SIZE, bytes(cmug.PATCHED_MODULEDATA_SIZE))
    carrier_key = m.alloc(4)
    if grouped:
        m.write32(module_data + cmug.DISCOUNT_GROUP_OFFSET, 0x12345678)
    expected = module_data + cmug.DISCOUNT_GROUP_OFFSET if grouped else carrier_key
    seen_add: list[int] = []
    seen_remove: list[int] = []

    def add_resume(machine: Machine) -> None:
        seen_add.append(machine.arg(1))
        machine.ret(8)

    def remove_resume(machine: Machine) -> None:
        ebp = machine.reg("ebp")
        seen_remove.append(machine.read32(ebp + 0x0C))
        return_address = machine.read32(ebp + 4)
        old_ebp = machine.read32(ebp)
        machine.uc.reg_write(x86.UC_X86_REG_EIP, return_address)
        machine.uc.reg_write(x86.UC_X86_REG_ESP, ebp + 16)
        machine.uc.reg_write(x86.UC_X86_REG_EBP, old_ebp)

    m.stub(cmug._ADD_RESUME, add_resume)
    m.stub(cmug._REMOVE_RESUME, remove_resume)
    m.call(labels["add"], module_data, carrier_key, ecx=0x11111111)
    m.call(labels["remove"], module_data, carrier_key, ecx=0x11111111, ebp=0x22222222)
    assert not m.faults
    assert seen_add == [expected]
    assert seen_remove == [expected]


def test_constructor_and_destructor_own_the_appended_string(image: bytearray) -> None:
    pytest.importorskip("unicorn.x86_const")
    pytest.importorskip("pefile")
    from .save_machine import Machine  # noqa: PLC0415

    patch = CostModifierUpgradeGroupsPatch()
    patch.apply(image)
    located = find_section(image, cmug.SECTION_NAME)
    assert located is not None
    _content, labels = patch._section(image, located[0])
    m = Machine(bytes(image))
    module_data = m.alloc(cmug.PATCHED_MODULEDATA_SIZE, b"\xaa" * cmug.PATCHED_MODULEDATA_SIZE)
    destroyed: list[int] = []
    resumed: list[int] = []

    m.stub(
        ad.COST_MODIFIER_UPGRADE_MODULEDATA_CTOR,
        lambda machine: machine.ret(value=machine.reg("ecx")),
    )
    m.stub(
        ad.ASCII_STRING_DTOR,
        lambda machine: (destroyed.append(machine.reg("ecx")), machine.ret()),
    )
    m.stub(
        cmug._MODULEDATA_DTOR_RESUME,
        lambda machine: (resumed.append(machine.reg("ecx")), machine.ret()),
    )

    assert m.call(labels["ctor"], ecx=module_data) == module_data
    assert m.read32(module_data + cmug.DISCOUNT_GROUP_OFFSET) == 0
    m.write32(module_data + cmug.DISCOUNT_GROUP_OFFSET, 0x12345678)
    m.call(labels["dtor"], ecx=module_data)
    assert not m.faults
    assert destroyed == [module_data + cmug.DISCOUNT_GROUP_OFFSET]
    assert resumed == [module_data]


def _ui_result(machine, ui: int, module: int, player: int) -> float:
    scratch = machine.alloc(4, bytes(4))
    wrapper = machine.alloc(32)
    body = b"\xff\x74\x24\x04" + call_rel32(wrapper + 4, ui)
    body += b"\xd9\x1d" + u32(scratch) + b"\xc2\x04\x00"
    machine.uc.mem_write(wrapper, body)
    machine.call(wrapper, player, ecx=module)
    return struct.unpack("<f", machine.uc.mem_read(scratch, 4))[0]


def test_grouped_palantir_returns_only_the_exact_record(image: bytearray) -> None:
    pytest.importorskip("unicorn.x86_const")
    pytest.importorskip("pefile")
    from .save_machine import Machine  # noqa: PLC0415

    patch = CostModifierUpgradeGroupsPatch()
    patch.apply(image)
    located = find_section(image, cmug.SECTION_NAME)
    assert located is not None
    _content, labels = patch._section(image, located[0])
    m = Machine(bytes(image))
    module = m.alloc(8, bytes(8))
    module_data = m.alloc(cmug.PATCHED_MODULEDATA_SIZE, bytes(cmug.PATCHED_MODULEDATA_SIZE))
    player = m.alloc(0x400, bytes(0x400))
    records = m.alloc(
        2 * ad.UPGRADE_DISCOUNT_RECORD_SIZE, bytes(2 * ad.UPGRADE_DISCOUNT_RECORD_SIZE)
    )
    m.write32(module + 4, module_data)
    m.write32(player + ad.PLAYER_UPGRADE_DISCOUNTS, records)
    m.write32(
        player + ad.PLAYER_UPGRADE_DISCOUNTS_END, records + 2 * ad.UPGRADE_DISCOUNT_RECORD_SIZE
    )
    m.write32(module_data + cmug.DISCOUNT_GROUP_OFFSET, 0xAABBCCDD)
    m.write32(module_data + 0x13C, 0x11110000)
    m.write32(module_data + 0x150, 0x22220000)
    # An unrelated record comes first; the exact group/vector key is the second record.
    m.write32(records, 0xDEADBEEF)
    exact = records + ad.UPGRADE_DISCOUNT_RECORD_SIZE
    m.write32(exact, 0xAABBCCDD)
    m.write32(exact + ad.UPGRADE_DISCOUNT_RECORD_PERCENTAGES, 0x11110000)
    m.write32(exact + ad.UPGRADE_DISCOUNT_RECORD_TARGETS, 0x22220000)
    m.uc.mem_write(exact + ad.UPGRADE_DISCOUNT_RECORD_VALUE, struct.pack("<f", -0.25))

    def compare(machine: Machine) -> None:
        machine.ret(4, int(machine.read32(machine.reg("ecx")) != machine.read32(machine.arg(0))))

    def vector_equal(machine: Machine) -> None:
        machine.ret(value=int(machine.read32(machine.arg(0)) == machine.read32(machine.arg(1))))

    m.stub(ad.ASCII_STRING_COMPARE, compare)
    m.stub(ad.FLOAT_VECTOR_EQUAL, vector_equal)
    m.stub(ad.ASCII_STRING_VECTOR_EQUAL, vector_equal)
    assert _ui_result(m, labels["ui"], module, player) == pytest.approx(-0.25)
    m.write32(module_data + cmug.DISCOUNT_GROUP_OFFSET, 0x33330000)
    assert _ui_result(m, labels["ui"], module, player) == 0.0
    assert not m.faults


def test_empty_group_palantir_delegates_to_stock_sum(image: bytearray) -> None:
    pytest.importorskip("unicorn.x86_const")
    pytest.importorskip("pefile")
    from .save_machine import Machine  # noqa: PLC0415

    patch = CostModifierUpgradeGroupsPatch()
    patch.apply(image)
    located = find_section(image, cmug.SECTION_NAME)
    assert located is not None
    _content, labels = patch._section(image, located[0])
    m = Machine(bytes(image))
    module = m.alloc(8, bytes(8))
    module_data = m.alloc(cmug.PATCHED_MODULEDATA_SIZE, bytes(cmug.PATCHED_MODULEDATA_SIZE))
    player = m.alloc(0x400, bytes(0x400))
    value = m.alloc(4, struct.pack("<f", -0.4))
    m.write32(module + 4, module_data)
    copied: list[int] = []

    def copy_empty(machine: Machine) -> None:
        copied.append(machine.arg(0))
        machine.write32(machine.reg("ecx"), 0)
        machine.ret(4, machine.reg("ecx"))

    m.stub(ad.ASCII_STRING_COPY_CTOR, copy_empty)
    m.ensure(ad.PLAYER_GET_UPGRADE_DISCOUNT)
    m.uc.mem_write(ad.PLAYER_GET_UPGRADE_DISCOUNT, b"\xd9\x05" + u32(value) + b"\xc2\x04\x00")
    assert _ui_result(m, labels["ui"], module, player) == pytest.approx(-0.4)
    assert copied == [ad.EMPTY_ASCII_STRING]
    assert not m.faults


@pytest.mark.parametrize("groups_first", [False, True])
def test_composes_with_player_upgrade_discount(groups_first: bool) -> None:
    data = cost_modifier_upgrade_groups_image(dict(pud.ANCHORS))
    groups = CostModifierUpgradeGroupsPatch()
    player = PlayerUpgradeDiscountPatch()
    patches = [groups, player] if groups_first else [player, groups]
    for patch in patches:
        patch.apply(data)
    assert groups.verify(data) == []
    assert player.verify(data) == []


@pytest.mark.full
def test_real_binary() -> None:
    path = Path(__file__).resolve().parents[2] / "game.dat"
    if not path.exists():
        pytest.skip("repository game.dat fixture is absent")
    data = bytearray(path.read_bytes())
    patch = CostModifierUpgradeGroupsPatch()
    patch.apply(data)
    assert patch.verify(data) == []
