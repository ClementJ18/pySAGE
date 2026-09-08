"""Tests for the detachable-rider-heal patch.

Four things can go wrong here without raising, so all four are checked by reading bytes back.

The **struct grows**, which no other check would catch: the factory's allocation and the offset
the new row names have to agree, and the constructor stub has to zero a dword `operator new`
leaves as heap garbage. A field that is one dword past the allocation is a field written off the
end of the block.

The **cave's code** is hand-assembled, and a wrong displacement assembles, applies and verifies
before it jumps into the middle of an instruction in a running game. Both routines are decoded
here instruction by instruction against the engine addresses they are supposed to reach.

The **stack contract** matters twice over: the detach routine reproduces two engine calls the
stock tail made for it (`ret` and `ret 4`) and issues a third through a vtable slot (`ret 8`), so
the argument bytes each one cleans are asserted rather than assumed.

And the **table** is rebuilt rather than edited, so the three stock rows have to come through
verbatim - their name pointers are absolute, and repointing one would break a stock keyword.
"""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

from sage_patch import TerrainResourceExpPatch, apply_patches
from sage_patch.addresses import FIELD_PARSE_STRIDE, INI_PARSE_REAL
from sage_patch.patches.detachable_rider_heal import (
    ANCHORS,
    BASE_ATTEMPT_DAMAGE,
    DEFAULT_KEYWORD,
    DETACH_RIDER,
    DETACH_TAIL_RESUME,
    DETACH_TAIL_STOCK,
    DETACH_TAIL_VA,
    FIELD_OFFSET,
    FIELD_TABLE,
    FIELD_TABLE_PUSH_VA,
    FIELD_TABLE_STOCK,
    INHERITED_KEYWORDS,
    INTERNAL_CHANGE_HEALTH_SLOT,
    MODULE_DATA_CTOR,
    MODULE_DATA_CTOR_CALL_VA,
    MODULE_DATA_SIZE_PATCHED,
    MODULE_DATA_SIZE_VA,
    PATCHED_MODULE_DATA_SIZE,
    SECTION_NAME,
    STOCK_FIELD_COUNT,
    STOCK_MODULE_DATA_SIZE,
    DetachableRiderHealPatch,
    build_code,
    build_table,
    entry_points,
    validate_keyword,
)
from sage_patch.utils import find_section, va_to_offset
from tests.sage_patch.test_terrain_resource_exp import (
    plant_sites as plant_terrain_resource_sites,
)

IMAGE_BASE = 0x400000

#: The keywords the stock rows point at, in table order.
STOCK_KEYWORDS = ("HealthPercentageWhenRiderDies", "StartsActive", "RiderlessDeathChance")


def _stock_rows() -> list[tuple[int, int, int, int]]:
    """The stock table as ``(name VA, parse fn, userData, ModuleData offset)`` rows."""
    return [
        struct.unpack_from("<IIII", FIELD_TABLE_STOCK, i * FIELD_PARSE_STRIDE)
        for i in range(STOCK_FIELD_COUNT)
    ]


def _pe32(highest_va: int) -> bytearray:
    """A PE32 image mapping one `.text` from VA 0x401000 up to ``highest_va``.

    Raw offset equals RVA throughout, as it does in the real binary, so a sibling patch's
    site-planting helper - which writes at file offsets - lands where it means to."""
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
    walks the same pointers it would walk on a real `game.dat`."""

    def write(va: int, blob: bytes) -> None:
        data[va - IMAGE_BASE : va - IMAGE_BASE + len(blob)] = blob

    for va, stock in ANCHORS.items():
        write(va, stock)
    for (name_va, *_), keyword in zip(_stock_rows(), STOCK_KEYWORDS, strict=True):
        write(name_va, keyword.encode("ascii") + b"\x00")


def synthetic_image() -> bytearray:
    """A PE32 image carrying every site the patch asserts, with the real original bytes planted."""
    highest = max(
        *(va + len(stock) for va, stock in ANCHORS.items()),
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


def _rel32(code: bytes, at: int, base_va: int) -> int:
    """The absolute target of the `rel32` whose displacement starts at ``at``."""
    return base_va + at + 4 + struct.unpack_from("<i", code, at)[0]


def test_the_new_field_sits_past_every_stock_one() -> None:
    """The offset the new row names is the old end of the struct, and the allocation grows by
    exactly the dword that puts it inside the block."""
    assert FIELD_OFFSET == STOCK_MODULE_DATA_SIZE
    assert PATCHED_MODULE_DATA_SIZE == STOCK_MODULE_DATA_SIZE + 4
    assert FIELD_OFFSET % 4 == 0, "INI::parseReal stores a dword through the pointer"
    for _name_va, _parse, _user, offset in _stock_rows():
        assert offset + 4 <= FIELD_OFFSET


def test_table_keeps_the_stock_rows_verbatim() -> None:
    table = build_table(0x00F00000)
    stock = FIELD_TABLE_STOCK[: STOCK_FIELD_COUNT * FIELD_PARSE_STRIDE]
    assert table[: len(stock)] == stock


def test_table_appends_one_real_row_and_a_terminator() -> None:
    keyword_va = 0x00F00000
    table = build_table(keyword_va)
    assert len(table) == (STOCK_FIELD_COUNT + 2) * FIELD_PARSE_STRIDE
    row = struct.unpack_from("<IIII", table, STOCK_FIELD_COUNT * FIELD_PARSE_STRIDE)
    assert row == (keyword_va, INI_PARSE_REAL, 0, FIELD_OFFSET)
    assert table[-FIELD_PARSE_STRIDE:] == bytes(FIELD_PARSE_STRIDE)


def test_ctor_stub_runs_the_stock_constructor_and_zeroes_the_field() -> None:
    """`operator new` does not zero the block, so the field is heap garbage until this runs -
    and the stub has to leave `eax` alone, because the factory reads `this` back out of it."""
    base = 0x00F00000
    code = build_code(base)
    entries = entry_points(base)
    at = entries["ctor"] - base

    assert code[at] == 0xE8
    assert _rel32(code, at + 1, base) == MODULE_DATA_CTOR
    # and dword [eax+FIELD_OFFSET], 0 - `eax` untouched, the dword cleared
    assert code[at + 5 : at + 7] == bytes((0x83, 0xA0))
    assert struct.unpack_from("<I", code, at + 7)[0] == FIELD_OFFSET
    assert code[at + 11] == 0x00
    assert code[at + 12] == 0xC3


def test_detach_routine_heals_after_the_damage_it_reproduces() -> None:
    """Decode the grant by hand. The order is the whole point: the displaced detach call, then
    the base `attemptDamage` the stock tail would have made, and only then the heal - a heal
    before the damage would be spent against the clamp at maximum health."""
    base = 0x00F00000
    code = build_code(base)
    entries = entry_points(base)
    at = entries["detach"] - base

    assert code[at : at + 2] == DETACH_TAIL_STOCK[:2]  # mov ecx, eax  (displaced)
    assert code[at + 2] == 0xE8
    assert _rel32(code, at + 3, base) == DETACH_RIDER

    assert code[at + 7] == 0x57  # push edi          the DamageInfo
    assert code[at + 8 : at + 10] == bytes((0x8B, 0xCE))  # mov ecx, esi
    assert code[at + 10] == 0xE8
    assert _rel32(code, at + 11, base) == BASE_ATTEMPT_DAMAGE

    assert code[at + 15 : at + 18] == bytes((0x8B, 0x46, 0xF4))  # mov eax, [esi-0xc]
    assert code[at + 18 : at + 22] == bytes((0xF3, 0x0F, 0x10, 0x80))  # movss xmm0, [eax+off]
    assert struct.unpack_from("<I", code, at + 22)[0] == FIELD_OFFSET

    assert code[at + 26 : at + 29] == bytes((0x0F, 0x57, 0xC9))  # xorps xmm1, xmm1
    assert code[at + 29 : at + 32] == bytes((0x0F, 0x2F, 0xC1))  # comiss xmm0, xmm1
    assert code[at + 32] == 0x76  # jbe rel8 - nothing to grant
    nothing_to_grant = at + 34 + code[at + 33]

    assert code[at + 34 : at + 38] == bytes((0x0F, 0x2F, 0x4E, 0x08))  # comiss xmm1, [esi+8]
    assert code[at + 38] == 0x73  # jae rel8 - it died anyway
    died = at + 40 + code[at + 39]
    assert nothing_to_grant == died, "both guards skip the same call"

    assert code[at + 40] == 0x57  # push edi           the DamageInfo, as the engine passes it
    assert code[at + 41] == 0x51  # push ecx           the float's slot
    assert code[at + 42 : at + 47] == bytes((0xF3, 0x0F, 0x11, 0x04, 0x24))  # movss [esp], xmm0
    assert code[at + 47 : at + 49] == bytes((0x8B, 0x06))  # mov eax, [esi]
    assert code[at + 49 : at + 51] == bytes((0x8B, 0xCE))  # mov ecx, esi
    assert code[at + 51 : at + 53] == bytes((0xFF, 0x90))  # call [eax+slot]
    assert struct.unpack_from("<I", code, at + 53)[0] == INTERNAL_CHANGE_HEALTH_SLOT

    assert died == at + 57
    assert code[died] == 0xE9
    assert _rel32(code, died + 1, base) == DETACH_TAIL_RESUME
    assert len(code) == died + 5


def test_the_routines_clean_no_argument_bytes_of_their_own() -> None:
    """Every call the cave makes is one the callee cleans - the two engine routines it reproduces
    and the vtable slot it adds - so the two `push`es it issues are argument bytes it must *not*
    take back. A stray `add esp, N` here would unbalance the frame it returns into."""
    code = build_code(0x00F00000)
    assert bytes((0x83, 0xC4)) not in code  # add esp, imm8
    assert bytes((0x81, 0xC4)) not in code  # add esp, imm32


def test_code_is_position_independent() -> None:
    """Built at two addresses, only the rel32s differ - nothing else in it is absolute."""
    a, b = build_code(0x00F00000), build_code(0x00F01000)
    assert len(a) == len(b)
    differing = [i for i, (x, y) in enumerate(zip(a, b, strict=True)) if x != y]
    assert len(differing) <= 4 * 4  # the four rel32s


def test_apply_writes_the_four_sites(image: bytearray) -> None:
    DetachableRiderHealPatch().apply(image)
    base_va, vsize = _cave(image)

    assert _read(image, MODULE_DATA_SIZE_VA, 5) == MODULE_DATA_SIZE_PATCHED

    push = _read(image, FIELD_TABLE_PUSH_VA, 5)
    assert push[0] == 0x68
    table_va = struct.unpack_from("<I", push, 1)[0]
    assert table_va != FIELD_TABLE
    assert base_va <= table_va < base_va + vsize

    hook = _read(image, DETACH_TAIL_VA, len(DETACH_TAIL_STOCK))
    assert hook[0] == 0xE9
    assert hook[5:] == b"\x90\x90"  # the two displaced instructions, padded
    detach_va = DETACH_TAIL_VA + 5 + struct.unpack_from("<i", hook, 1)[0]

    ctor_call = _read(image, MODULE_DATA_CTOR_CALL_VA, 5)
    assert ctor_call[0] == 0xE8
    ctor_va = MODULE_DATA_CTOR_CALL_VA + 5 + struct.unpack_from("<i", ctor_call, 1)[0]

    # both hooks reach the same cave, at the two entry points its own layout puts them at
    assert base_va <= ctor_va < detach_va < base_va + vsize
    assert entry_points(ctor_va) == {"ctor": ctor_va, "detach": detach_va}
    assert _read(image, ctor_va, len(build_code(ctor_va))) == build_code(ctor_va)


def test_apply_leaves_the_stock_table_where_it_was(image: bytearray) -> None:
    """The old table is abandoned, not edited: nothing else may be pointing into it, and
    rewriting `.rdata` in place is exactly the kind of edit that collides with another patch."""
    DetachableRiderHealPatch().apply(image)
    assert _read(image, FIELD_TABLE, len(FIELD_TABLE_STOCK)) == FIELD_TABLE_STOCK


def test_cave_holds_the_keyword_the_new_row_points_at(image: bytearray) -> None:
    DetachableRiderHealPatch(keyword="RiderlessBonusHealth").apply(image)
    push = _read(image, FIELD_TABLE_PUSH_VA, 5)
    table_va = struct.unpack_from("<I", push, 1)[0]
    row = struct.unpack("<IIII", _read(image, table_va + STOCK_FIELD_COUNT * 16, 16))
    name_va, parse, user, offset = row
    assert (parse, user, offset) == (INI_PARSE_REAL, 0, FIELD_OFFSET)
    assert _read(image, name_va, 21) == b"RiderlessBonusHealth\x00"


def test_default_keyword() -> None:
    assert DEFAULT_KEYWORD == "HealOnDetach"


def test_verify_clean_after_apply(image: bytearray) -> None:
    patch = DetachableRiderHealPatch()
    patch.apply(image)
    assert patch.verify(image) == []


def test_verify_clean_for_a_custom_keyword(image: bytearray) -> None:
    patch = DetachableRiderHealPatch(keyword="DetachHeal")
    patch.apply(image)
    assert patch.verify(image) == []


def test_verify_rejects_an_unpatched_image(image: bytearray) -> None:
    assert DetachableRiderHealPatch().verify(image) != []


def test_verify_rejects_the_wrong_keyword(image: bytearray) -> None:
    DetachableRiderHealPatch(keyword="DetachHeal").apply(image)
    assert DetachableRiderHealPatch().verify(image) != []


@pytest.mark.parametrize(
    "va",
    [MODULE_DATA_SIZE_VA, MODULE_DATA_CTOR_CALL_VA, FIELD_TABLE_PUSH_VA, DETACH_TAIL_VA],
)
def test_verify_catches_a_reverted_site(image: bytearray, va: int) -> None:
    patch = DetachableRiderHealPatch()
    patch.apply(image)
    off = va_to_offset(image, va)
    assert off is not None
    image[off : off + 4] = b"\x00\x00\x00\x00"
    assert patch.verify(image) != []


def test_detect_recovers_the_keyword(image: bytearray) -> None:
    DetachableRiderHealPatch(keyword="DetachHeal").apply(image)
    found = DetachableRiderHealPatch.detect(image)
    assert found is not None
    assert found.keyword == "DetachHeal"


def test_detect_finds_nothing_in_a_clean_image(image: bytearray) -> None:
    assert DetachableRiderHealPatch.detect(image) is None


@pytest.mark.parametrize("va", list(ANCHORS))
def test_apply_refuses_a_build_whose_site_differs(image: bytearray, va: int) -> None:
    off = va_to_offset(image, va)
    assert off is not None
    image[off : off + 4] = b"\xcc\xcc\xcc\xcc"
    with pytest.raises(ValueError):
        DetachableRiderHealPatch().apply(image)


def test_apply_refuses_to_run_twice(image: bytearray) -> None:
    DetachableRiderHealPatch().apply(image)
    with pytest.raises(ValueError):
        DetachableRiderHealPatch().apply(image)


@pytest.mark.parametrize("keyword", ["", "1Heal", "Heal Me", "Heal-Me"])
def test_validate_keyword_rejects_what_the_reader_could_never_match(keyword: str) -> None:
    with pytest.raises(ValueError):
        validate_keyword(keyword)


def test_validate_keyword_rejects_an_inherited_field() -> None:
    """`MaxHealth` and friends are added to the reader *before* this module's own table, so a
    duplicate would be matched there and the new field would never be written."""
    assert "MaxHealth" in INHERITED_KEYWORDS
    with pytest.raises(ValueError):
        validate_keyword("MaxHealth")


def test_apply_refuses_a_keyword_the_module_already_parses(image: bytearray) -> None:
    with pytest.raises(ValueError):
        DetachableRiderHealPatch(keyword="StartsActive").apply(image)


def test_ini_surface_reports_the_new_field() -> None:
    surface = DetachableRiderHealPatch(keyword="DetachHeal").ini_surface()
    assert [(f.block, f.name, f.type, f.default) for f in surface.fields] == [
        ("DetachableRiderBody", "DetachHeal", "Float", 0.0)
    ]


def test_the_ini_surface_actually_applies_to_the_model() -> None:
    """A field the model cannot take is a declaration that silently does nothing - the surface
    has to land on `DetachableRiderBody` itself, not just parse."""
    with DetachableRiderHealPatch().ini_surface().activate() as problems:
        assert problems == []


def test_it_composes_with_the_other_field_adder(tmp_path: Path) -> None:
    """`terrain-resource-exp` rebuilds a field table the same way for a different module. The two
    share no byte, so either order applies and both verify."""
    highest = max(
        *(va + len(stock) for va, stock in ANCHORS.items()),
        *(name_va + 64 for name_va, *_ in _stock_rows()),
    )
    image = _pe32(highest)
    plant_sites(image)
    plant_terrain_resource_sites(image)

    source = tmp_path / "game.dat"
    source.write_bytes(bytes(image))
    for order in ((0, 1), (1, 0)):
        patches = [DetachableRiderHealPatch(), TerrainResourceExpPatch()]
        out = tmp_path / f"out{order[0]}.dat"
        apply_patches(source, [patches[i] for i in order], output=out)
        result = bytearray(out.read_bytes())
        for patch in patches:
            assert patch.verify(result) == []


#: Both copies a checkout can hold. The repo-root `game.dat` carries eleven modifications and is
#: **not** stock, so a site is only safe to describe as stock when it agrees with the clean
#: `sage_patch/engine/game.dat.backup` - and none of this patch's does anything else. Neither
#: binary is committed (both are gitignored), so each check skips when its file is absent.
_BINARIES = {
    "repo": Path(__file__).resolve().parents[2] / "game.dat",
    "clean": Path(__file__).resolve().parents[2] / "sage_patch" / "engine" / "game.dat.backup",
}


@pytest.mark.parametrize("which", sorted(_BINARIES))
class TestStockBinaries:
    """Against the real binaries, which are the only things that can say the addresses are right."""

    def _stock(self, which: str) -> bytes:
        path = _BINARIES[which]
        if not path.exists():
            pytest.skip(f"needs {path.name}")
        return path.read_bytes()

    def test_every_anchor_holds_its_stock_bytes(self, which: str) -> None:
        stock = self._stock(which)
        for va, expected in ANCHORS.items():
            off = va_to_offset(stock, va)
            assert off is not None, f"{va:#010x} is not mapped"
            assert bytes(stock[off : off + len(expected)]) == expected, f"{va:#010x}"

    def test_the_keyword_strings_are_where_the_table_says(self, which: str) -> None:
        """The rows are copied into the cave pointer-for-pointer, so a build whose strings moved
        would keep three rows pointing at whatever now lives there."""
        stock = self._stock(which)
        for (name_va, *_), keyword in zip(_stock_rows(), STOCK_KEYWORDS, strict=True):
            off = va_to_offset(stock, name_va)
            assert off is not None
            assert bytes(stock[off : off + len(keyword) + 1]) == keyword.encode() + b"\x00"

    def test_apply_verify_detect_round_trip(self, which: str) -> None:
        data = bytearray(self._stock(which))
        patch = DetachableRiderHealPatch()
        patch.apply(data)
        assert patch.verify(data) == []
        found = DetachableRiderHealPatch.detect(data)
        assert isinstance(found, DetachableRiderHealPatch)
        assert found.keyword == DEFAULT_KEYWORD

    def test_it_composes_with_the_other_field_adder(self, which: str) -> None:
        data = bytearray(self._stock(which))
        patches = [DetachableRiderHealPatch(), TerrainResourceExpPatch()]
        for order in (patches, list(reversed(patches))):
            image = bytearray(data)
            for patch in order:
                patch.apply(image)
            for patch in order:
                assert patch.verify(image) == [], f"{patch} failed in {[str(p) for p in order]}"
