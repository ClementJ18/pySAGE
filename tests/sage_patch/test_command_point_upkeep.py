"""Tests for the command-point-upkeep patch.

The patch is ~690 bytes of hand-encoded x86 in a cave plus four edits to engine bytes, and none
of that fails loudly when it is wrong: a mis-encoded displacement assembles, applies and
verifies, and then the game reads the wrong field or jumps into the middle of an instruction. So
the tests that matter here **disassemble the result back** and assert it says what it was meant
to say - the stance `test_unique_production_id` and `test_hero_mana` take for their bytes.

One encoding bug this file exists to have caught: `fild dword ptr [esp]` is `DB /0`, and `DF /0`
is the *16-bit* form. Both assemble, both apply, and the wrong one silently reads two bytes.

The rest hold the invariants the design rests on: a faction that declares nothing is untouched,
the tier arithmetic is stated once and asserted against, the patch refuses to apply twice, and
it composes with `hero-mana` - the other patch that rebuilds INI field tables, though never the
same one.
"""

from __future__ import annotations

import itertools
import struct

import pytest

from sage_patch import CommandPointUpkeepPatch, HeroManaPatch
from sage_patch.addresses import (
    AUTO_DEPOSIT_SCALE,
    AUTO_DEPOSIT_SCALE_BYTES,
    AUTO_DEPOSIT_SCALE_RESUME,
    INI_PARSE_INT,
    PALANTIR_COMMAND_POINTS,
    PALANTIR_COMMAND_POINTS_BYTES,
    PALANTIR_COMMAND_POINTS_DONE,
    PALANTIR_COMMAND_POINTS_RESUME,
    PLAYER_TEMPLATE_BLOCK_KEY,
    PLAYER_TEMPLATE_BLOCK_KEY_BYTES,
    PLAYER_TEMPLATE_BLOCK_KEY_RESUME,
    PLAYER_TEMPLATE_FIELD_TABLE,
    PLAYER_TEMPLATE_FIELD_TABLE_REF_OPCODES,
    PLAYER_TEMPLATE_FIELD_TABLE_REFS,
    PLAYER_TEMPLATE_RESOURCE_FILTER,
    PLAYER_TEMPLATE_RESOURCE_VALUES,
)
from sage_patch.patches import command_point_upkeep as cpu
from sage_patch.patches.hero_mana import read_field_table
from sage_patch.utils import find_section, va_to_offset
from tests.sage_patch import test_hero_mana as hm_test

IMAGE_BASE = 0x400000

#: Where this image parks the `PlayerTemplate` table's name strings - above the block
#: `test_hero_mana` uses, so one image can host both patches' sites.
STRINGS_VA = 0x00DAB000

#: The stock `PlayerTemplate` table, as the real build holds it: 61 entries, of which the last
#: three are what :meth:`CommandPointUpkeepPatch._check_build` fingerprints.
STOCK_FIELDS: tuple[tuple[str, int], ...] = (
    *((f"StockField{i}", 0x14 + i * 4) for i in range(58)),
    ("ResourceModifierObjectFilter", PLAYER_TEMPLATE_RESOURCE_FILTER),
    ("ResourceModifierValues", PLAYER_TEMPLATE_RESOURCE_VALUES),
    ("MultiSelectionPortrait", 0x1D8),
)


def _name_vas() -> tuple[list[int], bytes]:
    strings = bytearray()
    vas: list[int] = []
    for name, _offset in STOCK_FIELDS:
        vas.append(STRINGS_VA + len(strings))
        strings += name.encode("ascii") + b"\x00"
    return vas, bytes(strings)


def _hero_mana_name_vas() -> tuple[list[int], bytes]:
    strings = bytearray()
    vas: list[int] = []
    for name, _offset in (*hm_test.STOCK_FIELDS, *hm_test.STOCK_OBJECT_FIELDS):
        vas.append(hm_test.STRINGS_VA + len(strings))
        strings += name.encode("ascii") + b"\x00"
    return vas, bytes(strings)


def synthetic_image() -> bytearray:
    """A PE32 image mapping every address this patch touches - and every address `hero-mana`
    touches, so the composition test needs no second image - with the real original bytes
    planted, so the whole apply + verify path runs in CI without the copyrighted `game.dat`."""
    vas, strings = _name_vas()
    hm_vas, hm_strings = _hero_mana_name_vas()

    highest = max(STRINGS_VA + len(strings), hm_test.STRINGS_VA + len(hm_strings)) - IMAGE_BASE
    data = bytearray(((highest + 0x100 + 0x400) // 0x200 + 1) * 0x200)

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

    plant_sites(data, vas, strings)
    hm_test.plant_sites(data, hm_vas, hm_strings)
    return data


def plant_sites(data: bytearray, vas: list[int], strings: bytes) -> None:
    """The clean bytes the patch asserts before writing."""

    def at(va: int) -> int:
        return va - IMAGE_BASE

    data[at(STRINGS_VA) : at(STRINGS_VA) + len(strings)] = strings

    table = at(PLAYER_TEMPLATE_FIELD_TABLE)
    for index, (_name, offset) in enumerate(STOCK_FIELDS):
        struct.pack_into("<IIII", data, table + index * 16, vas[index], INI_PARSE_INT, 0, offset)
    struct.pack_into("<IIII", data, table + len(STOCK_FIELDS) * 16, 0, 0, 0, 0)
    for ref_va, opcode in zip(
        PLAYER_TEMPLATE_FIELD_TABLE_REFS, PLAYER_TEMPLATE_FIELD_TABLE_REF_OPCODES, strict=True
    ):
        data[at(ref_va)] = opcode
        struct.pack_into("<I", data, at(ref_va) + 1, PLAYER_TEMPLATE_FIELD_TABLE)

    for va, window in (
        (PLAYER_TEMPLATE_BLOCK_KEY, PLAYER_TEMPLATE_BLOCK_KEY_BYTES),
        (AUTO_DEPOSIT_SCALE, AUTO_DEPOSIT_SCALE_BYTES),
        (PALANTIR_COMMAND_POINTS, PALANTIR_COMMAND_POINTS_BYTES),
    ):
        data[at(va) : at(va) + len(window)] = window


@pytest.fixture(scope="module")
def image() -> bytearray:
    return synthetic_image()


@pytest.fixture(scope="module")
def patched(image: bytearray) -> bytes:
    data = bytearray(image)
    CommandPointUpkeepPatch().apply(data)
    return bytes(data)


def cave(data: bytes, *, hud: bool = True):
    """``(section VA, code VA, code bytes)`` for the emitted routines."""
    section_va, off, vsize = find_section(data, cpu.SECTION_NAME)
    all_entries = read_field_table(data, CommandPointUpkeepPatch._resolve(data))  # noqa: SLF001
    entries = all_entries[: len(all_entries) - len(cpu.FIELDS)]
    code_off = CommandPointUpkeepPatch(hud=hud)._code_offset(entries)  # noqa: SLF001
    return section_va, section_va + code_off, bytes(data[off + code_off : off + vsize])


def labels(data: bytes, *, hud: bool = True) -> dict[str, int]:
    section_va, _off, _vsize = find_section(data, cpu.SECTION_NAME)
    all_entries = read_field_table(data, CommandPointUpkeepPatch._resolve(data))  # noqa: SLF001
    entries = all_entries[: len(all_entries) - len(cpu.FIELDS)]
    asm = CommandPointUpkeepPatch(hud=hud)._assemble(section_va, entries)  # noqa: SLF001
    return {name: asm.label_va(name) for name in asm._labels}  # noqa: SLF001


def name_of(data: bytes, entry) -> str | None:
    off = va_to_offset(data, entry[0])
    return None if off is None else data[off : data.index(b"\x00", off)].decode("latin1")


class TestWhatTheMechanicMeans:
    """`kept_percent` is the rule in Python; the emitted code is asserted against it below.

    Stating it once is what makes "did I mean this?" a separate question from "did I encode it
    right?" - the two failure modes this patch has.
    """

    VALUES = (100, 90, 80, 70)

    @pytest.mark.parametrize(
        ("points", "expected"),
        [(0, 100), (499, 100), (500, 90), (999, 90), (1000, 80), (1500, 70)],
    )
    def test_each_step_moves_one_tier(self, points, expected):
        assert cpu.kept_percent(points, 500, self.VALUES) == expected

    def test_past_the_last_entry_the_last_value_is_held(self):
        """A flat floor, not an extrapolation to zero: the table bounds the *table*, not the
        army. `ResourceModifierValues` extends itself at -2% per object instead, and that is a
        curve nobody would want applied to command points, where the step is 500 wide."""
        assert cpu.kept_percent(10_000, 500, self.VALUES) == 70
        assert cpu.kept_percent(10**9, 500, self.VALUES) == 70

    def test_a_zero_step_is_upkeep_off(self):
        """The default, and what makes the patch opt-in per faction."""
        assert cpu.kept_percent(50_000, 0, self.VALUES) == 100

    def test_a_negative_step_is_upkeep_off_rather_than_a_divide_by_zero(self):
        assert cpu.kept_percent(50_000, -1, self.VALUES) == 100

    def test_no_values_is_upkeep_off(self):
        """A faction that sets a step but no curve gets no penalty, not a penalty of 0%."""
        assert cpu.kept_percent(50_000, 500, ()) == 100

    def test_negative_command_points_are_tier_zero(self):
        assert cpu.kept_percent(-5, 500, self.VALUES) == 100

    def test_percentages_are_clamped_into_zero_to_one_hundred(self):
        """Above 100 would be a bonus, which the `(-N%)` the HUD prints cannot describe
        honestly; below 0 would invert the deposit."""
        assert cpu.kept_percent(0, 500, (250,)) == 100
        assert cpu.kept_percent(0, 500, (-40,)) == 0


class TestTheCave:
    def test_it_disassembles_cleanly_to_its_end(self, patched):
        """Capstone stopping early means an invalid encoding, which would be a crash in-game."""
        capstone = pytest.importorskip("capstone")
        md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
        _section, code_va, code = cave(patched)
        assert sum(i.size for i in md.disasm(code, code_va)) == len(code)

    def test_the_percentage_is_loaded_as_a_full_dword(self, patched):
        """`fild dword ptr [esp]` is `DB /0`. `DF /0` is the 16-bit form, and it assembles,
        applies and verifies exactly as happily while reading half the value."""
        capstone = pytest.importorskip("capstone")
        md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
        _section, code_va, code = cave(patched)
        filds = [i for i in md.disasm(code, code_va) if i.mnemonic == "fild" and "esp" in i.op_str]
        assert [i.op_str for i in filds] == ["dword ptr [esp]"]

    def test_the_x87_pushes_and_pops_balance(self, patched):
        """The displaced `fild` is the next push after the hook returns, so a leaked stack slot
        would corrupt the deposit that follows - and every one after it."""
        capstone = pytest.importorskip("capstone")
        md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
        _section, code_va, code = cave(patched)
        insns = list(md.disasm(code, code_va))
        deposit = labels(patched)["deposit"]
        body = [i for i in insns if deposit <= i.address < deposit + 0x60]
        pushes = sum(i.mnemonic in {"fild", "fld"} for i in body)
        pops = sum(i.mnemonic in {"fstp", "fistp"} for i in body)
        # one balanced pair of our own, plus the displaced `fild` the resume point consumes
        assert (pushes, pops) == (2, 1)

    def test_the_format_string_carries_three_numbers(self):
        assert cpu.FORMAT.count("%d") == 3
        assert cpu.FORMAT == "%d/%d (-%d%%)"

    def test_the_format_string_is_utf16_and_terminated(self, patched):
        """Read the way the engine reads it - 16-bit units to the first null one - because a
        byte-wise search for `00 00` lands off-boundary inside perfectly good text."""
        _va, off, _vsize = find_section(patched, cpu.SECTION_NAME)
        raw = bytes(patched[off + cpu._FMT_OFF :])  # noqa: SLF001
        units = [raw[i : i + 2] for i in range(0, len(raw) - 1, 2)]
        assert b"".join(units[: units.index(b"\x00\x00")]).decode("utf-16-le") == cpu.FORMAT

    def test_the_row_table_and_the_block_key_start_zeroed(self, patched):
        """A zero key is the empty marker, so a dirty table would hand a faction another
        faction's curve."""
        _va, off, _vsize = find_section(patched, cpu.SECTION_NAME)
        rows = off + cpu._ROWS_OFF  # noqa: SLF001
        assert bytes(patched[off : off + 4]) == bytes(4)
        assert bytes(patched[rows : rows + cpu.ROWS * cpu.ROW_STRIDE]) == bytes(
            cpu.ROWS * cpu.ROW_STRIDE
        )

    def test_a_row_holds_every_tier_it_says_it_does(self):
        assert cpu.ROW_STRIDE == 12 + cpu.VALUES * 4

    def test_the_row_index_fold_is_a_mask(self):
        assert cpu.ROWS & (cpu.ROWS - 1) == 0, "a non-power-of-two would need a divide"

    def test_it_relocates_with_its_section(self, image):
        """Every routine address and every table pointer is recomputed for where the section
        lands, so the cave cannot be assembled once and reused at another base."""
        entries = read_field_table(image, PLAYER_TEMPLATE_FIELD_TABLE)
        patch = CommandPointUpkeepPatch()
        a = patch._assemble(0x00F00000, entries).finish()  # noqa: SLF001
        b = patch._assemble(0x00F01000, entries).finish()  # noqa: SLF001
        assert a != b
        assert len(a) == len(b)


class TestTheFieldTable:
    def test_both_fields_are_added(self, patched):
        table = read_field_table(patched, CommandPointUpkeepPatch._resolve(patched))  # noqa: SLF001
        names = [name_of(patched, e) for e in table]
        assert names[-2:] == ["UpkeepCommandPointStep", "UpkeepValues"]

    def test_they_use_the_cave_parser_and_are_told_apart_by_userdata(self, patched):
        table = read_field_table(patched, CommandPointUpkeepPatch._resolve(patched))  # noqa: SLF001
        parse = labels(patched)["parse"]
        assert [(e[1], e[2]) for e in table[-2:]] == [(parse, 0), (parse, 1)]

    def test_neither_writes_into_the_template(self, patched):
        """Offset 0 is the whole storage argument: `PlayerTemplate` is `0x1DC` bytes with no
        hole, and a parse-time `this` is a stack temporary anyway."""
        table = read_field_table(patched, CommandPointUpkeepPatch._resolve(patched))  # noqa: SLF001
        assert [e[3] for e in table[-2:]] == [0, 0]

    def test_the_stock_entries_pass_through_untouched(self, image, patched):
        before = read_field_table(image, PLAYER_TEMPLATE_FIELD_TABLE)
        after = read_field_table(patched, CommandPointUpkeepPatch._resolve(patched))  # noqa: SLF001
        assert after[: len(before)] == before

    def test_the_table_moved_out_of_read_only_memory(self, image, patched):
        assert CommandPointUpkeepPatch._resolve(patched) != PLAYER_TEMPLATE_FIELD_TABLE  # noqa: SLF001
        assert CommandPointUpkeepPatch._resolve(image) == PLAYER_TEMPLATE_FIELD_TABLE  # noqa: SLF001


class TestTheHooks:
    @pytest.mark.parametrize(
        ("site", "window", "resume", "label"),
        [
            (
                PLAYER_TEMPLATE_BLOCK_KEY,
                PLAYER_TEMPLATE_BLOCK_KEY_BYTES,
                PLAYER_TEMPLATE_BLOCK_KEY_RESUME,
                "block",
            ),
            (AUTO_DEPOSIT_SCALE, AUTO_DEPOSIT_SCALE_BYTES, AUTO_DEPOSIT_SCALE_RESUME, "deposit"),
            (
                PALANTIR_COMMAND_POINTS,
                PALANTIR_COMMAND_POINTS_BYTES,
                PALANTIR_COMMAND_POINTS_RESUME,
                "text",
            ),
        ],
    )
    def test_each_site_is_a_jump_to_its_routine_padded_with_nops(
        self, patched, site, window, resume, label
    ):
        off = va_to_offset(patched, site)
        target = struct.unpack_from("<i", patched, off + 1)[0] + site + 5
        assert patched[off] == 0xE9
        assert target == labels(patched)[label]
        assert bytes(patched[off + 5 : off + len(window)]) == b"\x90" * (len(window) - 5)
        assert resume == site + len(window), "the resume point must be the end of the window"

    def test_every_displaced_window_reappears_in_the_cave(self, patched):
        """The bytes a hook overwrites have to run somewhere, and this is the check that they
        were carried across rather than dropped."""
        _section, _code_va, code = cave(patched)
        for window in (
            PLAYER_TEMPLATE_BLOCK_KEY_BYTES[:2],  # the `mov edi, eax`; the call is re-emitted
            AUTO_DEPOSIT_SCALE_BYTES,
            PALANTIR_COMMAND_POINTS_BYTES,
        ):
            assert window in code

    def test_the_hooks_do_not_overlap_each_other(self):
        spans = [
            range(PLAYER_TEMPLATE_BLOCK_KEY, PLAYER_TEMPLATE_BLOCK_KEY_RESUME),
            range(AUTO_DEPOSIT_SCALE, AUTO_DEPOSIT_SCALE_RESUME),
            range(PALANTIR_COMMAND_POINTS, PALANTIR_COMMAND_POINTS_RESUME),
            range(PLAYER_TEMPLATE_FIELD_TABLE_REFS[0], PLAYER_TEMPLATE_FIELD_TABLE_REFS[0] + 5),
        ]
        for a, b in itertools.combinations(spans, 2):
            assert not set(a) & set(b)

    def test_the_text_hook_rejoins_after_the_stock_cleanup(self, patched):
        """The three-vararg path does its own `add esp, 20`, so it must not fall back into the
        stock `add esp, 16`."""
        capstone = pytest.importorskip("capstone")
        md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
        _section, code_va, code = cave(patched)
        text = labels(patched)["text"]
        body = [i for i in md.disasm(code, code_va) if text <= i.address < text + 0x50]
        cleanups = [i.op_str for i in body if i.mnemonic == "add" and i.op_str.startswith("esp")]
        assert cleanups == ["esp, 0x14"]
        assert any(
            i.mnemonic == "jmp" and int(i.op_str, 16) == PALANTIR_COMMAND_POINTS_DONE for i in body
        )


class TestTheHudIsOptional:
    def test_no_hud_leaves_the_palantir_bytes_alone(self, image):
        data = bytearray(image)
        CommandPointUpkeepPatch(hud=False).apply(data)
        off = va_to_offset(data, PALANTIR_COMMAND_POINTS)
        assert bytes(data[off : off + len(PALANTIR_COMMAND_POINTS_BYTES)]) == (
            PALANTIR_COMMAND_POINTS_BYTES
        )

    def test_no_hud_still_charges(self, image):
        data = bytearray(image)
        CommandPointUpkeepPatch(hud=False).apply(data)
        assert data[va_to_offset(data, AUTO_DEPOSIT_SCALE)] == 0xE9

    def test_no_hud_applies_and_verifies(self, image):
        data = bytearray(image)
        patch = CommandPointUpkeepPatch(hud=False)
        patch.apply(data)
        assert patch.verify(data) == []

    def test_a_hud_build_does_not_verify_as_a_no_hud_one(self, patched):
        """`_edits` only lists bytes a configuration writes, so without an explicit check the
        no-hud verifier would happily pass a build whose HUD half is installed."""
        problems = CommandPointUpkeepPatch(hud=False).verify(patched)
        assert any("HUD half off" in p for p in problems)


class TestApply:
    def test_apply_then_verify(self, patched):
        assert CommandPointUpkeepPatch().verify(patched) == []

    def test_it_writes_nothing_outside_its_sites(self, image, patched):
        edited: set[int] = set()
        for va, length in (
            (PLAYER_TEMPLATE_FIELD_TABLE_REFS[0], 5),
            (PLAYER_TEMPLATE_BLOCK_KEY, len(PLAYER_TEMPLATE_BLOCK_KEY_BYTES)),
            (AUTO_DEPOSIT_SCALE, len(AUTO_DEPOSIT_SCALE_BYTES)),
            (PALANTIR_COMMAND_POINTS, len(PALANTIR_COMMAND_POINTS_BYTES)),
        ):
            off = va_to_offset(image, va)
            edited |= set(range(off, off + length))
        headers = set(range(0, 0x400))
        differing = {i for i in range(len(image)) if image[i] != patched[i]}
        assert not differing - edited - headers

    def test_the_section_name_survives_the_eight_byte_pe_field(self, patched):
        assert len(cpu.SECTION_NAME) <= 8, "a longer name is silently truncated in the header"
        assert find_section(patched, cpu.SECTION_NAME) is not None

    def test_the_section_is_readable_writable_and_executable(self, patched):
        e = struct.unpack_from("<I", patched, 0x3C)[0]
        nsec = struct.unpack_from("<H", patched, e + 6)[0]
        sectab = e + 24 + struct.unpack_from("<H", patched, e + 20)[0]
        for i in range(nsec):
            hdr = sectab + i * 40
            if bytes(patched[hdr : hdr + 8]).rstrip(b"\x00").decode() != cpu.SECTION_NAME:
                continue
            chars = struct.unpack_from("<I", patched, hdr + 36)[0]
            assert chars & 0x20000000, "the cave holds code"
            assert chars & 0x40000000, "and a field table read at INI load"
            assert chars & 0x80000000, "and rows written at INI load"
            return
        pytest.fail(f"{cpu.SECTION_NAME} is absent")

    def test_refuses_to_apply_twice(self, image):
        data = bytearray(image)
        CommandPointUpkeepPatch().apply(data)
        with pytest.raises(ValueError, match="already names"):
            CommandPointUpkeepPatch().apply(data)

    def test_refuses_a_build_whose_table_moved_a_fingerprinted_field(self, image):
        data = bytearray(image)
        table = va_to_offset(data, PLAYER_TEMPLATE_FIELD_TABLE)
        struct.pack_into("<I", data, table + 58 * 16 + 12, 0x1C0)  # ResourceModifier...Filter
        with pytest.raises(ValueError, match="unexpected build"):
            CommandPointUpkeepPatch().apply(data)

    def test_refuses_a_build_whose_table_reference_is_not_a_push(self, image):
        data = bytearray(image)
        data[va_to_offset(data, PLAYER_TEMPLATE_FIELD_TABLE_REFS[0])] = 0xB8  # mov eax, imm32
        with pytest.raises(ValueError, match="expected 0x68"):
            CommandPointUpkeepPatch().apply(data)

    def test_refuses_a_build_whose_hook_site_is_not_the_stock_one(self, image):
        data = bytearray(image)
        data[va_to_offset(data, AUTO_DEPOSIT_SCALE)] ^= 0xFF
        with pytest.raises(ValueError, match="expected"):
            CommandPointUpkeepPatch().apply(data)


class TestVerify:
    def test_an_unpatched_image_does_not_verify(self, image):
        problems = CommandPointUpkeepPatch().verify(image)
        assert problems == [f"no {cpu.SECTION_NAME} section: the file does not carry this patch"]

    def test_a_dirty_row_table_does_not_verify(self, patched):
        data = bytearray(patched)
        _va, off, _vsize = find_section(data, cpu.SECTION_NAME)
        data[off + cpu._ROWS_OFF] = 7  # noqa: SLF001
        assert any("not zero-initialised" in p for p in CommandPointUpkeepPatch().verify(data))

    def test_a_rewritten_hook_does_not_verify(self, patched):
        data = bytearray(patched)
        data[va_to_offset(data, AUTO_DEPOSIT_SCALE) + 1] ^= 0xFF
        assert any("AutoDepositUpdate" in p for p in CommandPointUpkeepPatch().verify(data))


class TestComposesWithHeroMana:
    """The only other patch that rebuilds INI field-parse tables. It moves the `Object` and
    `SpecialPower` tables; this one moves `PlayerTemplate`. No table and no byte is shared, so
    either order has to work."""

    @pytest.mark.parametrize("order", [(0, 1), (1, 0)])
    def test_any_order_applies_and_verifies(self, order):
        data = synthetic_image()
        patches = (CommandPointUpkeepPatch(), HeroManaPatch())
        for i in order:
            patches[i].apply(data)
        for patch in (CommandPointUpkeepPatch(), HeroManaPatch()):
            assert patch.verify(data) == [], f"{patch} failed in order {order}"

    def test_they_edit_disjoint_bytes(self):
        before = synthetic_image()
        mine = bytearray(before)
        CommandPointUpkeepPatch().apply(mine)
        theirs = bytearray(before)
        HeroManaPatch().apply(theirs)
        headers = set(range(0, 0x400))
        a = {i for i in range(len(before)) if before[i] != mine[i]} - headers
        b = {i for i in range(len(before)) if before[i] != theirs[i]} - headers
        assert not a & b

    def test_both_caves_are_present_and_the_section_table_stays_sorted(self):
        data = synthetic_image()
        CommandPointUpkeepPatch().apply(data)
        HeroManaPatch().apply(data)
        assert find_section(data, cpu.SECTION_NAME) is not None
        assert find_section(data, ".heromna") is not None
        e = struct.unpack_from("<I", data, 0x3C)[0]
        nsec = struct.unpack_from("<H", data, e + 6)[0]
        sectab = e + 24 + struct.unpack_from("<H", data, e + 20)[0]
        rvas = [struct.unpack_from("<I", data, sectab + i * 40 + 12)[0] for i in range(nsec)]
        assert rvas == sorted(rvas)
