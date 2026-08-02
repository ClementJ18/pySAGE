"""Tests for the hero-mana patch.

The patch is ~770 bytes of hand-encoded x86 in a cave plus fourteen edits to engine bytes, and
almost none of that fails loudly when it is wrong: a mis-encoded displacement assembles, applies
and verifies, and then the game reads the wrong field or jumps into the middle of an instruction.
So the tests that matter here **disassemble the result back** and assert it says what it was meant
to say - the same stance ``test_unique_production_id`` takes for its ten bytes.

The rest hold the invariants the design rests on: the arithmetic cannot overflow, a power that
declares no `ManaCost` is untouched, the patch refuses to apply twice, and it composes with the
one other patch that hooks a per-frame path.
"""

from __future__ import annotations

import struct

import pytest

from sage_patch import HeroManaPatch, apply_patches
from sage_patch.addresses import (
    ABILITY_TRIGGER,
    ABILITY_TRIGGER_PAY,
    ABILITY_TRIGGER_PAY_BYTES,
    ABILITY_TRIGGER_PAY_RESUME,
    ABILITY_TRIGGER_VTABLE,
    CAN_USE_SPECIAL_POWER,
    CAN_USE_SPECIAL_POWER_ENTRY,
    CONTROL_BAR_UNAVAILABLE,
    CONTROL_BAR_UNIT_COST_CALL,
    CONTROL_BAR_UNIT_COST_CALL_BYTES,
    DESCRIPTION_DONE,
    DESCRIPTION_RANK_APPEND,
    DESCRIPTION_RANK_APPEND_BYTES,
    DESCRIPTION_RANK_RESUME,
    DESCRIPTION_SPECIAL_POWER_CASE,
    DESCRIPTION_SPECIAL_POWER_CASE_BYTES,
    DESCRIPTION_UNIT_COST_BODY,
    DO_SPECIAL_POWER_SITES,
    GAME_LOGIC_FRAME,
    GAME_LOGIC_UPDATE,
    GAME_LOGIC_UPDATE_ENTRY,
    GAME_LOGIC_UPDATE_VTABLE_SLOT,
    GET_FINAL_OVERRIDE,
    INI_PARSE_INT,
    OBJECT_FIELD_TABLE,
    OBJECT_FIELD_TABLE_REF_OPCODES,
    OBJECT_FIELD_TABLE_REFS,
    OBJECT_ID,
    OPERATOR_NEW,
    SPECIAL_POWER_FIELD_TABLE,
    SPECIAL_POWER_FIELD_TABLE_REF_OPCODES,
    SPECIAL_POWER_FIELD_TABLE_REFS,
    SPECIAL_POWER_TEMPLATE_COPY_TAIL,
    SPECIAL_POWER_TEMPLATE_COPY_TAIL_BYTES,
    SPECIAL_POWER_TEMPLATE_NEW_SITES,
    SPECIAL_POWER_TEMPLATE_SIZE,
    THE_GAME_LOGIC,
    THING_TEMPLATE_COPY_CALL,
    THING_TEMPLATE_COPY_CALL_BYTES,
    THING_TEMPLATE_COPY_FROM,
    UNICODE_STRING_APPEND,
    UNICODE_STRING_CONCAT,
)
from sage_patch.patches import LiveBridgePatch
from sage_patch.patches import hero_mana as hm
from sage_patch.utils import find_section, va_to_offset

IMAGE_BASE = 0x400000

#: Where the synthetic image parks the stock table's name strings.
STRINGS_VA = 0x00DA7000

#: The stock `SpecialPower` table, as the real build holds it: 24 entries, of which these two are
#: what :meth:`HeroManaPatch._check_build` fingerprints.
STOCK_FIELDS: tuple[tuple[str, int], ...] = (
    *((f"StockField{i}", 0x18 + i * 4) for i in range(22)),
    ("UnitCost", 0x80),
    ("UnitCostDeathType", 0x84),
)

#: The stock `Object` table. The real one has 191 entries; the three named here are the ones the
#: build fingerprint checks, and the rest only have to exist and pass through untouched.
STOCK_OBJECT_FIELDS: tuple[tuple[str, int], ...] = (
    *((f"ObjField{i}", 0x100 + i * 4) for i in range(188)),
    ("CampnessValue", 0x5E4),
    ("BuildCost", 0x5EA),
    ("RefundValue", 0x5EC),
)


def _rel32(at_va: int, target_va: int) -> bytes:
    return struct.pack("<i", target_va - (at_va + 5))


def synthetic_image() -> bytearray:
    """A PE32 image mapping every address this patch touches, with the real original bytes
    planted, so the whole apply + verify path runs in CI without the copyrighted `game.dat`."""
    strings = bytearray()
    name_vas: list[int] = []
    for name, _offset in (*STOCK_FIELDS, *STOCK_OBJECT_FIELDS):
        name_vas.append(STRINGS_VA + len(strings))
        strings += name.encode("ascii") + b"\x00"

    highest = STRINGS_VA + len(strings) - IMAGE_BASE + 0x100
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
    struct.pack_into("<I", data, opt + 60, 0x400)  # SizeOfHeaders, room for more headers
    header = bytearray(40)
    header[0:8] = b".text\x00\x00\x00"
    mapped = len(data) - 0x1000
    struct.pack_into("<IIII", header, 8, mapped, 0x1000, mapped, 0x1000)
    data[opt + 0xE0 : opt + 0xE0 + 40] = header

    plant_sites(data, name_vas, strings)
    return data


def plant_sites(data: bytearray, name_vas: list[int], strings: bytes) -> None:
    """The clean bytes the patch asserts before writing. Separate from the image so a composition
    test can host this patch and another in one image."""

    def at(va: int) -> int:
        return va - IMAGE_BASE

    data[at(STRINGS_VA) : at(STRINGS_VA) + len(strings)] = strings

    cursor = 0
    for fields, base, refs, opcodes in (
        (
            STOCK_FIELDS,
            SPECIAL_POWER_FIELD_TABLE,
            SPECIAL_POWER_FIELD_TABLE_REFS,
            SPECIAL_POWER_FIELD_TABLE_REF_OPCODES,
        ),
        (
            STOCK_OBJECT_FIELDS,
            OBJECT_FIELD_TABLE,
            OBJECT_FIELD_TABLE_REFS,
            OBJECT_FIELD_TABLE_REF_OPCODES,
        ),
    ):
        table = at(base)
        for index, (_name, offset) in enumerate(fields):
            struct.pack_into(
                "<IIII",
                data,
                table + index * 16,
                name_vas[cursor + index],
                INI_PARSE_INT,
                0,
                offset,
            )
        struct.pack_into("<IIII", data, table + len(fields) * 16, 0, 0, 0, 0)
        cursor += len(fields)
        for ref_va, opcode in zip(refs, opcodes, strict=True):
            data[at(ref_va)] = opcode
            struct.pack_into("<I", data, at(ref_va) + 1, base)

    for push_va, call_va in SPECIAL_POWER_TEMPLATE_NEW_SITES:
        data[at(push_va)] = 0x68
        struct.pack_into("<I", data, at(push_va) + 1, SPECIAL_POWER_TEMPLATE_SIZE)
        data[at(call_va)] = 0xE8
        data[at(call_va) + 1 : at(call_va) + 5] = _rel32(call_va, OPERATOR_NEW)

    tail = at(SPECIAL_POWER_TEMPLATE_COPY_TAIL)
    data[tail : tail + len(SPECIAL_POWER_TEMPLATE_COPY_TAIL_BYTES)] = (
        SPECIAL_POWER_TEMPLATE_COPY_TAIL_BYTES
    )

    entry = at(CAN_USE_SPECIAL_POWER)
    data[entry : entry + len(CAN_USE_SPECIAL_POWER_ENTRY)] = CAN_USE_SPECIAL_POWER_ENTRY

    for va, window, _resume in DO_SPECIAL_POWER_SITES:
        data[at(va) : at(va) + len(window)] = window

    cbar = at(CONTROL_BAR_UNIT_COST_CALL)
    data[cbar : cbar + len(CONTROL_BAR_UNIT_COST_CALL_BYTES)] = CONTROL_BAR_UNIT_COST_CALL_BYTES

    copy = at(THING_TEMPLATE_COPY_CALL)
    data[copy : copy + len(THING_TEMPLATE_COPY_CALL_BYTES)] = THING_TEMPLATE_COPY_CALL_BYTES

    struct.pack_into("<I", data, at(ABILITY_TRIGGER_VTABLE), ABILITY_TRIGGER)
    pay = at(ABILITY_TRIGGER_PAY)
    data[pay : pay + len(ABILITY_TRIGGER_PAY_BYTES)] = ABILITY_TRIGGER_PAY_BYTES

    rank = at(DESCRIPTION_RANK_APPEND)
    data[rank : rank + len(DESCRIPTION_RANK_APPEND_BYTES)] = DESCRIPTION_RANK_APPEND_BYTES

    case = at(DESCRIPTION_SPECIAL_POWER_CASE)
    data[case : case + len(DESCRIPTION_SPECIAL_POWER_CASE_BYTES)] = (
        DESCRIPTION_SPECIAL_POWER_CASE_BYTES
    )


@pytest.fixture(scope="module")
def image() -> bytearray:
    return synthetic_image()


@pytest.fixture(scope="module")
def patched(image: bytearray) -> bytes:
    data = bytearray(image)
    HeroManaPatch().apply(data)
    return bytes(data)


def resolved(data: bytes) -> tuple[int, int]:
    """``(SpecialPower table VA, Object table VA)`` as the image currently holds them."""
    return HeroManaPatch._resolve(data)  # noqa: SLF001


def name_of(data: bytes, entry) -> str | None:
    off = va_to_offset(data, entry[0])
    return None if off is None else data[off : data.index(b"\x00", off)].decode("latin1")


def entry_named(data: bytes, field: str):
    """The field-parse entry called ``field``, from whichever of the two tables holds it."""
    for base in resolved(data):
        for entry in hm.read_field_table(data, base):
            if name_of(data, entry) == field:
                return entry
    raise AssertionError(f"no field-parse entry named {field}")


def cave(data: bytes) -> tuple[int, int]:
    """``(base VA, file offset)`` of the patch's section."""
    located = find_section(data, hm.SECTION_NAME)
    assert located is not None
    base_va, off, _vsize = located
    return base_va, off


#: Stand-in entry tuples: only the *count* matters for the layout arithmetic.
_POWER_STOCK = tuple([(1, 1, 1, 1)] * len(STOCK_FIELDS))
_OBJECT_STOCK = tuple([(1, 1, 1, 1)] * len(STOCK_OBJECT_FIELDS))


def assembled(base_va: int):
    return HeroManaPatch()._assemble(base_va, _POWER_STOCK, _OBJECT_STOCK)  # noqa: SLF001


def code_of(data: bytes) -> tuple[int, bytes]:
    """``(VA, bytes)`` of just the cave's code, past the rows, the tables and the strings."""
    base_va, off = cave(data)
    code_off = HeroManaPatch._code_offset(_POWER_STOCK, _OBJECT_STOCK)  # noqa: SLF001
    end = len(assembled(base_va).finish())
    return base_va + code_off, data[off + code_off : off + code_off + end]


class TestApply:
    def test_verify_passes_after_apply(self, patched: bytes):
        assert HeroManaPatch().verify(patched) == []

    def test_verify_fails_on_a_clean_image(self, image: bytearray):
        assert HeroManaPatch().verify(bytes(image)) != []

    def test_mana_cost_lands_on_special_power_with_the_int_parser(self, patched: bytes):
        """The *cost* is per ability, so it is a real `SpecialPowerTemplate` field and can use
        the engine's own `Int` parser."""
        entry = entry_named(patched, "ManaCost")
        assert entry[1] == INI_PARSE_INT
        assert entry[2] == 0
        assert entry[3] == hm.MANA_COST_OFF

    def test_pool_and_regen_land_on_object_with_the_patch_parser(self, patched: bytes):
        """The *pool* is per caster, so it is declared on `Object` and stored beside the
        `ThingTemplate` rather than inside it - which is why these two need a parse function of
        their own and carry a template offset of 0."""
        base_va, _off = cave(patched)
        parse_fn = assembled(base_va).label_va("tparse")
        for field, user_data in hm.OBJECT_FIELDS:
            entry = entry_named(patched, field)
            assert entry[1] == parse_fn, f"{field} does not use the patch's parser"
            assert entry[2] == user_data
            assert entry[3] == 0, f"{field} must not write into the template"

    def test_the_pool_is_not_declared_on_special_power(self, patched: bytes):
        """The earlier revision put all three on `SpecialPower`, which let a hero's abilities
        disagree about the cap. Only the cost belongs there."""
        power = hm.read_field_table(patched, resolved(patched)[0])
        names = {name_of(patched, e) for e in power}
        assert "ManaPool" not in names
        assert "ManaRegen" not in names

    @pytest.mark.parametrize(
        ("stock", "old_base"),
        [(STOCK_FIELDS, SPECIAL_POWER_FIELD_TABLE), (STOCK_OBJECT_FIELDS, OBJECT_FIELD_TABLE)],
    )
    def test_stock_entries_pass_through_by_pointer(
        self, image: bytearray, patched: bytes, stock, old_base: int
    ):
        """Every field already in a table keeps its index, its parser and its own name string -
        the rule that lets this compose with a patch that extended one first."""
        new_base = (
            resolved(patched)[0] if old_base == SPECIAL_POWER_FIELD_TABLE else resolved(patched)[1]
        )
        old = va_to_offset(image, old_base)
        want = bytes(image[old : old + len(stock) * 16])
        got_off = va_to_offset(patched, new_base)
        assert patched[got_off : got_off + len(want)] == want

    @pytest.mark.parametrize("index", [0, 1])
    def test_tables_are_terminated(self, patched: bytes, index: int):
        added = (hm.POWER_FIELDS, hm.OBJECT_FIELDS)[index]
        stock = (STOCK_FIELDS, STOCK_OBJECT_FIELDS)[index]
        base = resolved(patched)[index]
        term = va_to_offset(patched, base) + (len(stock) + len(added)) * 16
        assert struct.unpack_from("<IIII", patched, term) == (0, 0, 0, 0)

    def test_all_seven_references_repointed(self, patched: bytes):
        base_va, _off = cave(patched)
        power_va, object_va = resolved(patched)
        for refs, want in (
            (SPECIAL_POWER_FIELD_TABLE_REFS, power_va),
            (OBJECT_FIELD_TABLE_REFS, object_va),
        ):
            for ref_va in refs:
                got = struct.unpack_from("<I", patched, va_to_offset(patched, ref_va) + 1)[0]
                assert got == want
                assert got > base_va, "a table must point into the cave, not at the stock base"

    def test_every_allocation_grows_and_zeroes(self, patched: bytes):
        for push_va, call_va in SPECIAL_POWER_TEMPLATE_NEW_SITES:
            size = struct.unpack_from("<I", patched, va_to_offset(patched, push_va) + 1)[0]
            assert size == hm.NEW_TEMPLATE_SIZE
            off = va_to_offset(patched, call_va)
            assert patched[off] == 0xE8
            target = call_va + 5 + struct.unpack_from("<i", patched, off + 1)[0]
            assert target != OPERATOR_NEW, "the raw allocator would leave the new fields garbage"

    def test_config_defaults_written(self, image: bytearray):
        data = bytearray(image)
        HeroManaPatch(pool=250, regen=7).apply(data)
        _base_va, off = cave(bytes(data))
        assert struct.unpack_from("<I", data, off + hm._CFG_POOL_OFF)[0] == 250  # noqa: SLF001
        assert struct.unpack_from("<I", data, off + hm._CFG_REGEN_OFF)[0] == 7  # noqa: SLF001
        assert HeroManaPatch(pool=250, regen=7).verify(bytes(data)) == []

    def test_verify_is_specific_to_the_configured_defaults(self, patched: bytes):
        assert any("default pool" in problem for problem in HeroManaPatch(pool=7).verify(patched))


class TestRefusals:
    def test_applying_twice_is_refused(self, image: bytearray):
        data = bytearray(image)
        HeroManaPatch().apply(data)
        with pytest.raises(ValueError, match="already"):
            HeroManaPatch().apply(data)

    @pytest.mark.parametrize(
        ("base", "index", "was"),
        [(SPECIAL_POWER_FIELD_TABLE, 22, 0x80), (OBJECT_FIELD_TABLE, 189, 0x5EA)],
    )
    def test_a_moved_field_is_refused(self, image: bytearray, base: int, index: int, was: int):
        """The fingerprints are what stop this being written to a build whose structs have a
        different shape - where `+0x88` might be a live member rather than past the end, or where
        the Object table is not the one these offsets were read from."""
        data = bytearray(image)
        table = va_to_offset(data, base)
        assert struct.unpack_from("<I", data, table + index * 16 + 12)[0] == was
        struct.pack_into("<I", data, table + index * 16 + 12, was - 4)
        with pytest.raises(ValueError, match="unexpected build"):
            HeroManaPatch().apply(data)

    def test_a_changed_hook_site_is_refused(self, image: bytearray):
        data = bytearray(image)
        at = va_to_offset(data, CAN_USE_SPECIAL_POWER)
        data[at] = 0x90
        with pytest.raises(ValueError, match="canUseSpecialPower"):
            HeroManaPatch().apply(data)

    @pytest.mark.parametrize(("pool", "regen"), [(0, 30), (100, 0), (0x10000, 30), (100, -1)])
    def test_out_of_range_configuration_is_refused(self, pool: int, regen: int):
        with pytest.raises(ValueError, match="must be in"):
            HeroManaPatch(pool=pool, regen=regen)

    def test_verify_catches_a_reverted_edit(self, patched: bytes):
        data = bytearray(patched)
        at = va_to_offset(data, CONTROL_BAR_UNIT_COST_CALL)
        data[at : at + len(CONTROL_BAR_UNIT_COST_CALL_BYTES)] = CONTROL_BAR_UNIT_COST_CALL_BYTES
        assert any("ControlBar" in problem for problem in HeroManaPatch().verify(bytes(data)))


class TestArithmetic:
    """The cave does no division and no 64-bit maths, so every product has to be provably inside
    32 bits. These are the bounds the emitted clamps enforce."""

    def test_gain_cannot_overflow(self):
        assert hm._CLAMP * hm._CLAMP < 2**32  # noqa: SLF001  elapsed * regen

    def test_the_sum_cannot_overflow(self):
        """`gain` is clamped to the cap *before* being added to the stored value, and the stored
        value is itself capped - so the sum is at worst twice the cap."""
        cap = hm._CLAMP * hm.HUNDREDTHS  # noqa: SLF001
        assert cap + cap < 2**32

    def test_cost_cannot_overflow(self):
        assert hm._CLAMP * hm.HUNDREDTHS < 2**32  # noqa: SLF001

    @pytest.mark.parametrize("rows", [hm.POOL_ROWS, hm.TEMPLATE_ROWS])
    def test_rows_are_a_power_of_two(self, rows: int):
        """Both index folds are an `and`, so both counts have to be."""
        assert rows & (rows - 1) == 0


def disassemble(data: bytes):
    """``(instructions, VA, bytes)`` of the cave's code."""
    capstone = pytest.importorskip("capstone")
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    va, code = code_of(data)
    return list(md.disasm(code, va)), va, code


class TestEmittedCode:
    """Disassemble the cave back and assert it says what it was meant to say."""

    _disassemble = staticmethod(disassemble)

    def test_every_byte_decodes(self, patched: bytes):
        """A cave that stops decoding part-way is a cave with a bad instruction in it, and the
        engine would run straight into it."""
        instructions, va, code = self._disassemble(patched)
        assert instructions, "nothing decoded"
        last = instructions[-1]
        assert last.address + last.size == va + len(code)

    def test_no_branch_leaves_the_cave_except_where_intended(self, patched: bytes):
        """Every outbound edge is either a documented engine address or inside the cave. A stray
        one means a displacement was computed against the wrong base."""
        instructions, va, code = self._disassemble(patched)
        allowed = {
            GET_FINAL_OVERRIDE,
            OPERATOR_NEW,
            CONTROL_BAR_UNAVAILABLE,
            INI_PARSE_INT,
            THING_TEMPLATE_COPY_FROM,
            UNICODE_STRING_CONCAT,
            UNICODE_STRING_APPEND,
            DESCRIPTION_DONE,
            DESCRIPTION_RANK_RESUME,
            ABILITY_TRIGGER_PAY_RESUME,
            DESCRIPTION_UNIT_COST_BODY,
            CAN_USE_SPECIAL_POWER + len(CAN_USE_SPECIAL_POWER_ENTRY),
            *(resume for _va, _window, resume in DO_SPECIAL_POWER_SITES),
        }
        for ins in instructions:
            if ins.mnemonic.startswith(("j", "call")) and ins.op_str.startswith("0x"):
                target = int(ins.op_str, 16)
                inside = va <= target < va + len(code)
                assert inside or target in allowed, f"{ins.address:#x} -> {target:#x}"

    def test_the_pool_row_index_is_folded_and_strided(self, patched: bytes):
        instructions, _va, _code = self._disassemble(patched)
        text = [f"{i.mnemonic} {i.op_str}" for i in instructions]
        assert text.count(f"and ecx, {hm.POOL_ROWS - 1:#x}") == 2, "read and spend must agree"
        assert text.count(f"imul ecx, ecx, {hm.ROW_STRIDE:#x}") == 2

    def test_the_template_table_is_probed_the_same_way_twice(self, patched: bytes):
        """`tlookup` and `tinsert` share a probe body; if they folded differently, an insert and
        the lookup that follows it would land on different rows."""
        instructions, _va, _code = self._disassemble(patched)
        text = [f"{i.mnemonic} {i.op_str}" for i in instructions]
        assert text.count(f"and eax, {hm.TEMPLATE_ROWS - 1:#x}") == 4  # twice each: hash + step
        assert text.count(f"imul edx, edx, {hm.ROW_STRIDE:#x}") == 2

    def test_the_object_id_is_read_from_the_measured_offset(self, patched: bytes):
        instructions, _va, _code = self._disassemble(patched)
        text = [f"{i.mnemonic} {i.op_str}" for i in instructions]
        assert text.count(f"mov edx, dword ptr [ebx + {OBJECT_ID:#x}]") == 2

    def test_the_frame_comes_from_the_game_logic_singleton(self, patched: bytes):
        instructions, _va, _code = self._disassemble(patched)
        text = [f"{i.mnemonic} {i.op_str}" for i in instructions]
        assert f"mov eax, dword ptr [{THE_GAME_LOGIC:#x}]" in text
        assert f"mov eax, dword ptr [eax + {GAME_LOGIC_FRAME:#x}]" in text

    def test_the_cost_is_read_from_the_power_template(self, patched: bytes):
        instructions, _va, _code = self._disassemble(patched)
        text = [f"{i.mnemonic} {i.op_str}" for i in instructions]
        assert f"mov eax, dword ptr [esi + {hm.MANA_COST_OFF:#x}]" in text

    def test_the_pool_is_read_from_the_objects_own_template(self, patched: bytes):
        """The cap and the regen come from `Object+0x04`, the caster's `ThingTemplate` - not from
        the power. That is what gives a hero one pool across all of its abilities."""
        instructions, _va, _code = self._disassemble(patched)
        text = [f"{i.mnemonic} {i.op_str}" for i in instructions]
        assert "mov ecx, dword ptr [ebx + 4]" in text
        # ...and then out of the side-table row it resolves to, not out of the template itself.
        assert "mov ecx, dword ptr [eax + 4]" in text  # ManaPool
        assert "mov edx, dword ptr [eax + 8]" in text  # ManaRegen

    def test_the_gate_returns_the_engines_own_calling_convention(self, patched: bytes):
        """`canUseSpecialPower` is `__thiscall` with two stack arguments; a refusal that does not
        `ret 8` corrupts its caller's stack."""
        instructions, _va, _code = self._disassemble(patched)
        assert any(i.mnemonic == "ret" and i.op_str == "8" for i in instructions)

    def test_the_copy_constructor_tail_is_reproduced(self, patched: bytes):
        """The displaced epilogue has to be re-emitted verbatim, or the constructor returns to
        nowhere."""
        _va, code = code_of(patched)
        assert code.count(SPECIAL_POWER_TEMPLATE_COPY_TAIL_BYTES) == 1

    def test_the_shipping_build_does_not_touch_the_dispatch_sites(self, patched: bytes):
        """The charge moved to the ability trigger, so these are pure observation and exist only
        in a `--trace` build. Charging here as well double-took the cost - measured on
        `SpecialAbilityLightningSword`, 50 at the click and 50 again 17 frames later at the fire."""
        for va, window, _resume in DO_SPECIAL_POWER_SITES:
            off = va_to_offset(patched, va)
            assert patched[off : off + len(window)] == window, (
                f"{va:#x} should be untouched in a non-trace build"
            )

    def test_the_pool_is_never_written_on_the_read_path(self, patched: bytes):
        """The ControlBar calls `check` on the local client only. If `check` (or the `value` it
        calls) ever wrote a row, two clients would diverge - so the only stores into the row array
        must be in `spend`."""
        capstone = pytest.importorskip("capstone")
        md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
        va, code = code_of(patched)
        asm = assembled(cave(patched)[0])
        # `tinsert` also stores through a pointer, but only ever at INI load; the window checked
        # here is the play-time one, from `value` (the read) to the end of `spend` (the write).
        start, spend, new = asm.label_va("value"), asm.label_va("spend"), asm.label_va("new")
        for ins in md.disasm(code, va):
            through_pointer = ins.op_str.startswith(("dword ptr [ecx", "dword ptr [eax"))
            if ins.mnemonic == "mov" and through_pointer and start <= ins.address < new:
                assert spend <= ins.address, (
                    f"{ins.address:#x} writes through a pointer outside `spend`: {ins.op_str}"
                )


class TestHookSites:
    def test_the_gate_is_a_jump_into_the_cave(self, patched: bytes):
        base_va, _off = cave(patched)
        off = va_to_offset(patched, CAN_USE_SPECIAL_POWER)
        assert patched[off] == 0xE9
        target = CAN_USE_SPECIAL_POWER + 5 + struct.unpack_from("<i", patched, off + 1)[0]
        assert target > base_va

    def test_the_description_case_is_hooked(self, patched: bytes):
        base_va, _off = cave(patched)
        off = va_to_offset(patched, DESCRIPTION_SPECIAL_POWER_CASE)
        assert patched[off] == 0xE9
        target = DESCRIPTION_SPECIAL_POWER_CASE + 5 + struct.unpack_from("<i", patched, off + 1)[0]
        assert target > base_va

    def test_the_description_line_re_tests_the_displaced_case(self, patched: bytes):
        """The five bytes taken are the case's own `cmp`/`jne`, so the cave has to make the same
        decision before doing anything - otherwise every other button type falls into it."""
        instructions, _va, _code = disassemble(patched)
        text = [f"{i.mnemonic} {i.op_str}" for i in instructions]
        assert f"cmp ecx, {hm.GUI_COMMAND_SPECIAL_POWER:#x}" in text

    def test_the_description_line_reads_the_casters_current_pool(self, patched: bytes):
        """The line carries cost *and* what the caster has, so it needs the builder's own Object
        (`ebp-0x1c`) and the pool converted from hundredths to whole points."""
        instructions, _va, _code = disassemble(patched)
        text = [f"{i.mnemonic} {i.op_str}" for i in instructions]
        assert "mov ebx, dword ptr [ebp - 0x1c]" in text
        assert f"mov ecx, {hm.HUNDREDTHS:#x}" in text
        assert "div ecx" in text

    def test_the_description_line_cleans_two_varargs(self, patched: bytes):
        """`fetch(label, exists)` cleans its own two arguments, so the trailing `add esp` has to
        drop the varargs plus the concat's two. One vararg is `0xc` (the stock UnitCost line);
        two is `0x10`. Getting this wrong corrupts the builder's frame rather than failing."""
        instructions, _va, _code = disassemble(patched)
        text = [f"{i.mnemonic} {i.op_str}" for i in instructions]
        assert "add esp, 0x10" in text, "the two-value line must clean four dwords"
        assert "add esp, 0xc" in text, "the one-value ManaPool line must still clean three"

    def test_the_description_line_falls_into_the_stock_unit_cost_line(self, patched: bytes):
        """A ManaCost line must not replace the UnitCost one - both should appear."""
        instructions, _va, _code = disassemble(patched)
        targets = {
            int(i.op_str, 16)
            for i in instructions
            if i.mnemonic == "jmp" and i.op_str.startswith("0x")
        }
        assert DESCRIPTION_UNIT_COST_BODY in targets
        assert DESCRIPTION_DONE in targets

    def test_both_tooltip_labels_are_in_the_cave(self, patched: bytes):
        _base_va, off = cave(patched)
        for label in hm.TOOLTIP_LABELS:
            assert label.encode() + b"\x00" in patched[off : off + 0x40000]

    def test_the_ability_trigger_is_hooked(self, patched: bytes):
        """The charge that matters: hero abilities never reach `Object::doSpecialPower*` when the
        starter has `UpdateModuleStartsAttack`, so this is the one that actually fires."""
        base_va, _off = cave(patched)
        off = va_to_offset(patched, ABILITY_TRIGGER_PAY)
        assert patched[off] == 0xE9
        target = ABILITY_TRIGGER_PAY + 5 + struct.unpack_from("<i", patched, off + 1)[0]
        assert target > base_va
        pad = len(ABILITY_TRIGGER_PAY_BYTES) - 5
        assert patched[off + 5 : off + 5 + pad] == b"\x90" * pad

    def test_the_ability_trigger_reproduces_its_displaced_pair(self, patched: bytes):
        _va, code = code_of(patched)
        assert code.count(ABILITY_TRIGGER_PAY_BYTES) == 1

    def test_a_moved_ability_trigger_is_refused(self, image: bytearray):
        """The charge is installed *inside* that function, so a build where the vtable names
        something else must stop rather than hook a routine nothing dispatches to."""
        data = bytearray(image)
        struct.pack_into("<I", data, ABILITY_TRIGGER_VTABLE - IMAGE_BASE, 0xDEAD)
        with pytest.raises(ValueError, match="not the live one"):
            HeroManaPatch().apply(data)

    def test_the_revive_description_is_hooked_and_padded(self, patched: bytes):
        base_va, _off = cave(patched)
        off = va_to_offset(patched, DESCRIPTION_RANK_APPEND)
        assert patched[off] == 0xE9
        target = DESCRIPTION_RANK_APPEND + 5 + struct.unpack_from("<i", patched, off + 1)[0]
        assert target > base_va
        pad = len(DESCRIPTION_RANK_APPEND_BYTES) - 5
        assert patched[off + 5 : off + 5 + pad] == b"\x90" * pad

    def test_the_revive_line_reproduces_the_displaced_fold(self, patched: bytes):
        """The bytes taken are the engine's own `lea ecx, [ebp-0x18]` / `call concat`, which is
        what actually hands the rank line to the description. Drop it and the level vanishes."""
        instructions, _va, _code = disassemble(patched)
        text = [f"{i.mnemonic} {i.op_str}" for i in instructions]
        assert "lea ecx, [ebp - 0x18]" in text
        assert f"call {UNICODE_STRING_APPEND:#x}" in text

    def test_the_revive_line_keys_off_the_hero_template(self, patched: bytes):
        """`esi` is the hero's ThingTemplate in that branch, and it is the side-table key."""
        instructions, _va, _code = disassemble(patched)
        text = [f"{i.mnemonic} {i.op_str}" for i in instructions]
        assert "mov ecx, esi" in text

    def test_the_control_bar_site_stays_a_call(self, patched: bytes):
        """It is installed over a `call getFinalOverride` whose result the caller uses, so it has
        to return a value - a `jmp` there would lose the override."""
        off = va_to_offset(patched, CONTROL_BAR_UNIT_COST_CALL)
        assert patched[off] == 0xE8


class TestComposition:
    """`live-bridge` is the patch this one had to be designed around: a ticked pool would have
    wanted `GameLogic::update`'s five bytes, which `live-bridge` already owns. Computing the pool
    on read instead is what makes both installable, so the pair is worth a test."""

    @staticmethod
    def _image_with_live_bridge() -> bytearray:
        data = synthetic_image()
        at = GAME_LOGIC_UPDATE - IMAGE_BASE
        data[at : at + len(GAME_LOGIC_UPDATE_ENTRY)] = GAME_LOGIC_UPDATE_ENTRY
        struct.pack_into("<I", data, GAME_LOGIC_UPDATE_VTABLE_SLOT - IMAGE_BASE, GAME_LOGIC_UPDATE)
        return data

    @pytest.mark.parametrize("reverse", [False, True])
    def test_applies_in_either_order(self, tmp_path, reverse: bool):
        source = tmp_path / "game.dat"
        source.write_bytes(self._image_with_live_bridge())
        patches = [HeroManaPatch(), LiveBridgePatch()]
        if reverse:
            patches.reverse()
        out = apply_patches(source, patches, output=tmp_path / f"out{reverse}.dat")
        data = out.read_bytes()
        assert HeroManaPatch().verify(data) == []
        assert LiveBridgePatch().verify(data) == []

    def test_the_two_caves_do_not_overlap(self, tmp_path):
        source = tmp_path / "game.dat"
        source.write_bytes(self._image_with_live_bridge())
        out = apply_patches(
            source, [HeroManaPatch(), LiveBridgePatch()], output=tmp_path / "out.dat"
        )
        data = out.read_bytes()
        mana = find_section(data, hm.SECTION_NAME)
        bridge = find_section(data, ".livebrg")
        assert mana is not None and bridge is not None
        assert mana[0] + mana[2] <= bridge[0] or bridge[0] + bridge[2] <= mana[0]
