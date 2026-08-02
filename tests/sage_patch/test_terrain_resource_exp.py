"""Tests for the terrain-resource-exp patch.

Three of the checks here are structural - the cave's layout, the three edits, the round trip
through `verify` - and the rest hold the properties the patch's correctness actually rests on and
which no amount of "it applies cleanly" would catch:

* the new field lands in the two padding bytes, so ``sizeof(ModuleData)`` never has to change;
* the rewritten constructor really does zero that byte, since `operator new` does not;
* the rebuilt table keeps the eight stock rows *verbatim*, because their name pointers are
  absolute and repointing them would break every stock keyword; and
* the gate's own bytes say what they were meant to say - a wrong displacement assembles, applies
  and verifies, and then jumps into the middle of an instruction in a running game.
"""

from __future__ import annotations

import struct

import pytest

from sage_patch import (
    AiReviveGatePatch,
    CommandSetLimitPatch,
    TerrainResourceExpPatch,
    UniqueProductionIdPatch,
)
from sage_patch.addresses import (
    FIELD_PARSE_STRIDE,
    INI_PARSE_BOOL,
    TERRAIN_RESOURCE_DEFAULT_STORES,
    TERRAIN_RESOURCE_DEFAULT_STORES_BYTES,
    TERRAIN_RESOURCE_EXP_BLOCK,
    TERRAIN_RESOURCE_EXP_BLOCK_BYTES,
    TERRAIN_RESOURCE_EXP_BLOCK_RESUME,
    TERRAIN_RESOURCE_EXP_BLOCK_SKIP,
    TERRAIN_RESOURCE_FIELD_TABLE,
    TERRAIN_RESOURCE_FIELD_TABLE_PUSH,
    TERRAIN_RESOURCE_FIELD_TABLE_PUSH_BYTES,
    TERRAIN_RESOURCE_FIELD_TABLE_STOCK,
    TERRAIN_RESOURCE_FREE_OFFSET,
    TERRAIN_RESOURCE_MODULE_DATA_SIZE,
    TERRAIN_RESOURCE_UPDATE,
    TERRAIN_RESOURCE_UPDATE_VTABLE,
    TERRAIN_RESOURCE_UPDATE_VTABLE_SLOT,
)
from sage_patch.patches.terrain_resource_exp import (
    DEFAULT_KEYWORD,
    SECTION_NAME,
    STOCK_FIELD_COUNT,
    build_gate,
    build_table,
    rewritten_defaults,
)
from sage_patch.utils import find_section, va_to_offset
from tests.sage_patch.test_ai_revive_gate import plant_sites as plant_ai_revive_gate_sites
from tests.sage_patch.test_patching import _plant_commandset_sites, _section_rvas
from tests.sage_patch.test_unique_production_id import (
    plant_sites as plant_unique_production_id_sites,
)

IMAGE_BASE = 0x400000

#: The vtable entry that proves the function being hooked is the module's live `update`.
VTABLE_SLOT = TERRAIN_RESOURCE_UPDATE_VTABLE + TERRAIN_RESOURCE_UPDATE_VTABLE_SLOT

STOCK_KEYWORDS = (
    "Radius",
    "MaxIncome",
    "IncomeInterval",
    "HighPriority",
    "Visible",
    "Upgrade",
    "UpgradeBonusPercent",
    "UpgradeMustBePresent",
)


def _stock_rows() -> list[tuple[int, int, int, int]]:
    """The stock table as ``(name VA, parse fn, userData, ModuleData offset)`` rows."""
    return [
        struct.unpack_from("<IIII", TERRAIN_RESOURCE_FIELD_TABLE_STOCK, i * FIELD_PARSE_STRIDE)
        for i in range(STOCK_FIELD_COUNT)
    ]


def _pe32(highest_va: int) -> bytearray:
    """A PE32 image mapping one `.text` from VA 0x401000 up to ``highest_va``.

    Raw offset equals RVA throughout, as it does in the real binary, so the other patches'
    site-planting helpers - which write at file offsets - land where they mean to."""
    data = bytearray(((highest_va - IMAGE_BASE + 0x800) // 0x200 + 1) * 0x200)

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
    struct.pack_into("<I", data, opt + 60, 0x400)  # SizeOfHeaders, room for more headers
    header = bytearray(40)
    header[0:8] = b".text\x00\x00\x00"
    mapped = len(data) - 0x1000
    struct.pack_into("<IIII", header, 8, mapped, 0x1000, mapped, 0x1000)
    data[opt + 0xE0 : opt + 0xE0 + 40] = header
    return data


def plant_sites(data: bytearray) -> None:
    """The clean bytes this patch asserts before writing, plus the stock keyword strings.

    The strings live at the addresses the *real* table's rows point at, so the duplicate check
    walks the same pointers it would walk on a real `game.dat`. Separate from :func:`_pe32` so a
    composition test can host this patch and the others in one image."""

    def write(va: int, blob: bytes) -> None:
        data[va - IMAGE_BASE : va - IMAGE_BASE + len(blob)] = blob

    write(TERRAIN_RESOURCE_FIELD_TABLE, TERRAIN_RESOURCE_FIELD_TABLE_STOCK)
    write(TERRAIN_RESOURCE_DEFAULT_STORES, TERRAIN_RESOURCE_DEFAULT_STORES_BYTES)
    write(TERRAIN_RESOURCE_FIELD_TABLE_PUSH, TERRAIN_RESOURCE_FIELD_TABLE_PUSH_BYTES)
    write(TERRAIN_RESOURCE_EXP_BLOCK, TERRAIN_RESOURCE_EXP_BLOCK_BYTES)
    write(VTABLE_SLOT, struct.pack("<I", TERRAIN_RESOURCE_UPDATE))
    for (name_va, *_), keyword in zip(_stock_rows(), STOCK_KEYWORDS, strict=True):
        write(name_va, keyword.encode("ascii") + b"\x00")


def synthetic_image() -> bytearray:
    """A PE32 image carrying every site the patch asserts, with the real original bytes planted."""
    highest = max(
        TERRAIN_RESOURCE_FIELD_TABLE + len(TERRAIN_RESOURCE_FIELD_TABLE_STOCK),
        VTABLE_SLOT + 4,
        *(name_va + 64 for name_va, *_ in _stock_rows()),
    )
    data = _pe32(highest)
    plant_sites(data)
    return data


@pytest.fixture
def image() -> bytearray:
    return synthetic_image()


def _read(data: bytes | bytearray, va: int, n: int) -> bytes:
    off = va_to_offset(data, va)
    assert off is not None, f"0x{va:08x} is not mapped"
    return bytes(data[off : off + n])


def _cave(data: bytes | bytearray) -> tuple[int, int]:
    located = find_section(data, SECTION_NAME)
    assert located is not None, f"no {SECTION_NAME} section"
    base_va, _off, vsize = located
    return base_va, vsize


def test_new_field_lands_in_existing_padding() -> None:
    """The offset the patch uses is inside the struct and claimed by no stock field.

    This is the property the whole patch rests on: if it did not hold, `sizeof(ModuleData)` and
    every allocation of it would have to grow."""
    claimed: set[int] = set()
    widths = {0x08: 4, 0x0C: 4, 0x10: 4, 0x14: 1, 0x15: 1, 0x18: 4, 0x1C: 4, 0x20: 4}
    for _name_va, _parse, _user, offset in _stock_rows():
        claimed.update(range(offset, offset + widths[offset]))
    assert TERRAIN_RESOURCE_FREE_OFFSET not in claimed
    assert TERRAIN_RESOURCE_FREE_OFFSET < TERRAIN_RESOURCE_MODULE_DATA_SIZE


def test_rewritten_ctor_zeroes_the_new_byte_and_keeps_visible() -> None:
    """`and dword [esi+0x14], 0` then `mov byte [esi+0x15], 1` - same length, and the two stock
    defaults are unchanged."""
    new = rewritten_defaults()
    assert len(new) == len(TERRAIN_RESOURCE_DEFAULT_STORES_BYTES)
    assert new[:4] == bytes.fromhex("83661400")  # and dword [esi+0x14], 0
    assert new[4:] == TERRAIN_RESOURCE_DEFAULT_STORES_BYTES[4:]  # mov byte [esi+0x15], 1
    # the dword store covers +0x14..+0x17, so it reaches the new field
    assert 0x14 <= TERRAIN_RESOURCE_FREE_OFFSET < 0x18


def test_table_keeps_the_stock_rows_verbatim() -> None:
    keyword_va = 0x00F00000
    table = build_table(keyword_va)
    stock = TERRAIN_RESOURCE_FIELD_TABLE_STOCK[: STOCK_FIELD_COUNT * FIELD_PARSE_STRIDE]
    assert table[: len(stock)] == stock


def test_table_appends_one_bool_row_and_a_terminator() -> None:
    keyword_va = 0x00F00000
    table = build_table(keyword_va)
    assert len(table) == (STOCK_FIELD_COUNT + 2) * FIELD_PARSE_STRIDE
    row = struct.unpack_from("<IIII", table, STOCK_FIELD_COUNT * FIELD_PARSE_STRIDE)
    assert row == (keyword_va, INI_PARSE_BOOL, 0, TERRAIN_RESOURCE_FREE_OFFSET)
    assert table[-FIELD_PARSE_STRIDE:] == bytes(FIELD_PARSE_STRIDE)


def test_gate_reads_the_field_and_branches_to_the_engine_edges() -> None:
    """Decode the gate by hand. A wrong displacement assembles and verifies, so the only thing
    that catches it is reading the bytes back."""
    base = 0x00F00000
    code = build_gate(base)

    assert code[0:3] == bytes.fromhex("8b45e8")  # mov eax, [ebp-0x18]   (the ModuleData)
    assert code[3:6] == bytes([0x80, 0x78, TERRAIN_RESOURCE_FREE_OFFSET])  # cmp byte [eax+off],
    assert code[6] == 0x00  # ... 0
    assert code[7] == 0x75  # jne rel8
    skip_at = 9 + code[8]

    displaced_at = 9
    assert code[displaced_at : displaced_at + len(TERRAIN_RESOURCE_EXP_BLOCK_BYTES)] == (
        TERRAIN_RESOURCE_EXP_BLOCK_BYTES
    )
    resume_at = displaced_at + len(TERRAIN_RESOURCE_EXP_BLOCK_BYTES)
    assert code[resume_at] == 0xE9
    resume = base + resume_at + 5 + struct.unpack_from("<i", code, resume_at + 1)[0]
    assert resume == TERRAIN_RESOURCE_EXP_BLOCK_RESUME

    assert skip_at == resume_at + 5, "the short branch must land on the skip jump"
    assert code[skip_at] == 0xE9
    skip = base + skip_at + 5 + struct.unpack_from("<i", code, skip_at + 1)[0]
    assert skip == TERRAIN_RESOURCE_EXP_BLOCK_SKIP
    assert len(code) == skip_at + 5


def test_gate_is_position_independent() -> None:
    """Built at two addresses, only the two rel32s differ - nothing else in it is absolute."""
    a, b = build_gate(0x00F00000), build_gate(0x00F01000)
    assert len(a) == len(b)
    differing = [i for i, (x, y) in enumerate(zip(a, b, strict=True)) if x != y]
    assert len(differing) <= 8  # the two displacements, 4 bytes each


def test_apply_writes_the_three_sites(image: bytearray) -> None:
    TerrainResourceExpPatch().apply(image)
    base_va, _vsize = _cave(image)

    assert _read(image, TERRAIN_RESOURCE_DEFAULT_STORES, 8) == rewritten_defaults()

    push = _read(image, TERRAIN_RESOURCE_FIELD_TABLE_PUSH, 5)
    assert push[0] == 0x68
    table_va = struct.unpack_from("<I", push, 1)[0]
    assert table_va != TERRAIN_RESOURCE_FIELD_TABLE
    assert base_va <= table_va < base_va + _cave(image)[1]

    hook = _read(image, TERRAIN_RESOURCE_EXP_BLOCK, len(TERRAIN_RESOURCE_EXP_BLOCK_BYTES))
    assert hook[0] == 0xE9
    assert hook[5:] == b"\x90"  # the 6-byte instruction, padded
    code_va = TERRAIN_RESOURCE_EXP_BLOCK + 5 + struct.unpack_from("<i", hook, 1)[0]
    assert _read(image, code_va, len(build_gate(code_va))) == build_gate(code_va)


def test_apply_leaves_the_stock_table_where_it_was(image: bytearray) -> None:
    """The old table is abandoned, not edited: nothing else may be pointing into it, and
    rewriting `.rdata` in place is exactly the kind of edit that collides with another patch."""
    TerrainResourceExpPatch().apply(image)
    assert (
        _read(image, TERRAIN_RESOURCE_FIELD_TABLE, len(TERRAIN_RESOURCE_FIELD_TABLE_STOCK))
        == TERRAIN_RESOURCE_FIELD_TABLE_STOCK
    )


def test_cave_holds_the_keyword_the_new_row_points_at(image: bytearray) -> None:
    TerrainResourceExpPatch(keyword="NoLevelPlease").apply(image)
    push = _read(image, TERRAIN_RESOURCE_FIELD_TABLE_PUSH, 5)
    table_va = struct.unpack_from("<I", push, 1)[0]
    row = struct.unpack("<IIII", _read(image, table_va + STOCK_FIELD_COUNT * 16, 16))
    name_va, parse, user, offset = row
    assert (parse, user, offset) == (INI_PARSE_BOOL, 0, TERRAIN_RESOURCE_FREE_OFFSET)
    assert _read(image, name_va, 14) == b"NoLevelPlease\x00"


def test_default_keyword_matches_the_stock_sibling() -> None:
    assert DEFAULT_KEYWORD == "GiveNoXP"


def test_verify_clean_after_apply(image: bytearray) -> None:
    patch = TerrainResourceExpPatch()
    patch.apply(image)
    assert patch.verify(image) == []


def test_verify_clean_for_a_custom_keyword(image: bytearray) -> None:
    patch = TerrainResourceExpPatch(keyword="GiveNoExp")
    patch.apply(image)
    assert patch.verify(image) == []


def test_verify_rejects_an_unpatched_image(image: bytearray) -> None:
    assert TerrainResourceExpPatch().verify(image) != []


def test_verify_rejects_the_wrong_keyword(image: bytearray) -> None:
    TerrainResourceExpPatch(keyword="GiveNoExp").apply(image)
    assert TerrainResourceExpPatch(keyword="GiveNoXP").verify(image) != []


@pytest.mark.parametrize(
    "va",
    [
        TERRAIN_RESOURCE_DEFAULT_STORES,
        TERRAIN_RESOURCE_FIELD_TABLE_PUSH,
        TERRAIN_RESOURCE_EXP_BLOCK,
    ],
)
def test_verify_catches_a_reverted_site(image: bytearray, va: int) -> None:
    patch = TerrainResourceExpPatch()
    patch.apply(image)
    off = va_to_offset(image, va)
    assert off is not None
    image[off : off + 4] = b"\x00\x00\x00\x00"
    assert patch.verify(image) != []


def test_apply_refuses_a_second_time(image: bytearray) -> None:
    """The stock table is checked before anything is written, and it no longer looks stock once
    the first application has repointed the `push` - so a double apply raises rather than
    stacking two caves."""
    TerrainResourceExpPatch().apply(image)
    with pytest.raises(ValueError):
        TerrainResourceExpPatch().apply(image)


def test_apply_refuses_a_keyword_the_module_already_has(image: bytearray) -> None:
    with pytest.raises(ValueError, match="already has"):
        TerrainResourceExpPatch(keyword="MaxIncome").apply(image)


def test_apply_refuses_when_the_vtable_names_another_update(image: bytearray) -> None:
    off = va_to_offset(image, VTABLE_SLOT)
    assert off is not None
    struct.pack_into("<I", image, off, TERRAIN_RESOURCE_UPDATE + 0x10)
    with pytest.raises(ValueError, match="not the live one"):
        TerrainResourceExpPatch().apply(image)


def test_apply_refuses_when_the_table_is_not_the_stock_one(image: bytearray) -> None:
    off = va_to_offset(image, TERRAIN_RESOURCE_FIELD_TABLE)
    assert off is not None
    struct.pack_into("<I", image, off + 12, 0x99)  # a different offset in row 0
    with pytest.raises(ValueError, match="not the stock one"):
        TerrainResourceExpPatch().apply(image)


@pytest.mark.parametrize("keyword", ["", "9Lives", "Give No XP", "Give-No-XP", "a" * 80])
def test_constructor_refuses_an_unparseable_keyword(keyword: str) -> None:
    with pytest.raises(ValueError, match="INI keyword"):
        TerrainResourceExpPatch(keyword=keyword)


#: Comfortably past the highest site any of the four patches below touches (the production
#: interface vtable at 0x00C67DB0 is the last of them).
_COMPOSABLE_TOP = 0x00C80000


def _composable_image() -> bytearray:
    """One image carrying this patch's sites and those of the three it is applied alongside."""
    data = _pe32(_COMPOSABLE_TOP)
    plant_sites(data)
    _plant_commandset_sites(data)
    plant_ai_revive_gate_sites(data)
    plant_unique_production_id_sites(data)
    return data


def test_composes_with_the_other_patches_in_either_order() -> None:
    """Any order produces a binary every patch still verifies, and the section table stays
    sorted by RVA - the property `allocate_section` exists to hold."""
    ours, other = TerrainResourceExpPatch(), UniqueProductionIdPatch()
    first, second = _composable_image(), _composable_image()

    ours.apply(first)
    other.apply(first)
    other.apply(second)
    ours.apply(second)

    for data in (first, second):
        assert ours.verify(data) == []
        assert other.verify(data) == []
        rvas = _section_rvas(data)
        assert rvas == sorted(rvas)


def test_composes_with_the_patches_that_share_no_bytes() -> None:
    data = _composable_image()
    for patch in (CommandSetLimitPatch(count=64), AiReviveGatePatch(), TerrainResourceExpPatch()):
        patch.apply(data)
    assert TerrainResourceExpPatch().verify(data) == []
    assert AiReviveGatePatch().verify(data) == []


def test_touches_no_byte_another_patch_touches() -> None:
    """The three sites are disjoint from every other bundled patch's, which is what makes the
    order-independence above hold rather than merely happen to."""
    base = _composable_image()
    ours = _composable_image()
    TerrainResourceExpPatch().apply(ours)
    changed_by_ours = {i for i in range(len(base)) if base[i] != ours[i]}

    others = _composable_image()
    for patch in (CommandSetLimitPatch(count=64), AiReviveGatePatch(), UniqueProductionIdPatch()):
        patch.apply(others)
    changed_by_others = {i for i in range(min(len(base), len(others))) if base[i] != others[i]}

    overlap = changed_by_ours & changed_by_others
    # both append sections, so the PE header's section count and SizeOfImage move for either
    header_end = 0x400
    assert {i for i in overlap if i >= header_end} == set()
