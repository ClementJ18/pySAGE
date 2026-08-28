"""Tests for the fire-at-attacker patch.

The structural checks are the usual ones - the cave's layout, the four edits, the round trip
through `verify`. The rest hold the properties the patch's correctness actually rests on, none of
which "it applies cleanly" would catch:

* the new field lands **exactly** at the stock ``sizeof(ModuleData)``, which is only free because
  the block is grown by four bytes in the same patch - unlike `queue-ignore-cp`, which finds
  alignment padding and leaves the allocation alone;
* the constructor shim really does zero that dword, since `operator new` does not;
* the rebuilt table keeps the live rows *verbatim*, because their name pointers are absolute;
* the `No` path reproduces the three displaced instructions and returns to the **stock call**,
  while the `Yes` path makes its own call and resumes **past** it - swap those two resume
  addresses and the weapon fires twice, or not at all;
* the chosen `WeaponTemplate` in `ecx` is saved across the object lookup, which is the one
  register the cave could silently destroy; and
* the routines' bytes say what they were meant to say - a wrong displacement assembles, applies
  and verifies, and then jumps into the middle of an instruction in a running game.

:class:`TestInstalledBinary` is the only thing here that can say the addresses are the right ones;
``sage_patch/docs/fire-at-attacker.md`` records the derivation.
"""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

from sage_ini.engine import STOCK
from sage_patch.addresses import (
    CREATE_AND_FIRE_TEMP_WEAPON_AT_VICTIM,
    DAMAGE_INFO_SOURCE_ID,
    FIELD_PARSE_STRIDE,
    FWWD_FIELD_TABLE,
    FWWD_FIELD_TABLE_REF_OPCODES,
    FWWD_FIELD_TABLE_REFS,
    FWWD_IFACE_MODULE_DATA_DISP,
    FWWD_MODULEDATA_CTOR,
    FWWD_MODULEDATA_CTOR_CALL,
    FWWD_MODULEDATA_CTOR_CALL_BYTES,
    FWWD_MODULEDATA_SIZE,
    FWWD_MODULEDATA_SIZE_BYTES,
    FWWD_MODULEDATA_SIZE_VA,
    FWWD_REACTION_AIM,
    FWWD_REACTION_AIM_BYTES,
    FWWD_REACTION_FIRE_CALL,
    FWWD_REACTION_FIRE_RESUME,
    GAME_LOGIC_FIND_OBJECT_BY_ID,
    INI_PARSE_BOOL,
    THE_GAME_LOGIC,
)
from sage_patch.patches.fire_at_attacker import (
    ANCHORS,
    DEFAULT_KEYWORD,
    FINGERPRINT,
    FLAG_OFFSET,
    GROWN_MODULEDATA_SIZE,
    SECTION_NAME,
    FireAtAttackerPatch,
    build_code,
    build_table,
    grown_size_bytes,
)
from sage_patch.registry import PATCHES
from sage_patch.utils import find_section, va_to_offset
from tests.sage_patch.test_terrain_resource_exp import _pe32

IMAGE_BASE = 0x400000

_GAME_DAT = Path(__file__).resolve().parents[2] / "game.dat"

#: Where the synthetic image parks the field names, past every site the patch touches.
STRINGS_VA = 0x00C31000

#: The stock `FireWeaponWhenDamagedBehavior` field table, as ``(keyword, ModuleData offset)``, in
#: the order the real build holds it. The parse functions are not reproduced because the patch
#: copies every row through by value and never looks at them.
STOCK_FIELDS: tuple[tuple[str, int], ...] = (
    ("StartsActive", 0x138),
    ("ReactionWeaponPristine", 0x144),
    ("ReactionWeaponDamaged", 0x148),
    ("ReactionWeaponReallyDamaged", 0x14C),
    ("ReactionWeaponRubble", 0x150),
    ("ContinuousWeaponPristine", 0x154),
    ("ContinuousWeaponDamaged", 0x158),
    ("ContinuousWeaponReallyDamaged", 0x15C),
    ("ContinuousWeaponRubble", 0x160),
    ("DamageTypes", 0x13C),
    ("DamageAmount", 0x140),
)


def _string_vas() -> dict[str, int]:
    vas, cursor = {}, STRINGS_VA
    for name, _offset in STOCK_FIELDS:
        vas[name] = cursor
        cursor += len(name) + 1
    return vas


def plant_sites(data: bytearray) -> None:
    """The clean bytes this patch asserts before writing, plus the stock keyword strings.

    Separate from the image builder so a composition test can host this patch and others in one
    image."""

    def at(va: int) -> int:
        return va - IMAGE_BASE

    vas = _string_vas()
    for name, va in vas.items():
        blob = name.encode("ascii") + b"\x00"
        data[at(va) : at(va) + len(blob)] = blob

    table = at(FWWD_FIELD_TABLE)
    for index, (name, offset) in enumerate(STOCK_FIELDS):
        struct.pack_into(
            "<IIII", data, table + index * FIELD_PARSE_STRIDE, vas[name], INI_PARSE_BOOL, 0, offset
        )
    struct.pack_into("<IIII", data, table + len(STOCK_FIELDS) * FIELD_PARSE_STRIDE, 0, 0, 0, 0)

    for ref_va, opcode in zip(FWWD_FIELD_TABLE_REFS, FWWD_FIELD_TABLE_REF_OPCODES, strict=True):
        data[at(ref_va)] = opcode
        struct.pack_into("<I", data, at(ref_va) + 1, FWWD_FIELD_TABLE)

    for va, window in (
        (FWWD_MODULEDATA_SIZE_VA, FWWD_MODULEDATA_SIZE_BYTES),
        (FWWD_MODULEDATA_CTOR_CALL, FWWD_MODULEDATA_CTOR_CALL_BYTES),
        (FWWD_REACTION_AIM, FWWD_REACTION_AIM_BYTES),
    ):
        data[at(va) : at(va) + len(window)] = window

    for va, window in ANCHORS.items():
        data[at(va) : at(va) + len(window)] = window


def _image() -> bytearray:
    data = _pe32(STRINGS_VA + sum(len(name) + 1 for name, _ in STOCK_FIELDS) + 0x100)
    plant_sites(data)
    return data


def at(data: bytes | bytearray, va: int, count: int) -> bytes:
    off = va_to_offset(data, va)
    assert off is not None, f"0x{va:08x} is not mapped"
    return bytes(data[off : off + count])


def _cave(data: bytes | bytearray) -> tuple[int, int]:
    """The cave's base VA and virtual size."""
    located = find_section(data, SECTION_NAME)
    assert located is not None
    return located[0], located[2]


def _code_va(data: bytes | bytearray, keyword: str = DEFAULT_KEYWORD) -> int:
    """Where the cave's code starts: past the keyword string and the rebuilt table."""
    base, _vsize = _cave(data)
    string = len(keyword) + 1
    table_va = base + string + (-string % 4)
    return table_va + (len(STOCK_FIELDS) + 2) * FIELD_PARSE_STRIDE


@pytest.fixture
def image() -> bytearray:
    return _image()


@pytest.fixture
def patched(image: bytearray) -> bytearray:
    FireAtAttackerPatch().apply(image)
    return image


class TestRegistration:
    def test_the_registry_holds_it(self):
        assert PATCHES[FireAtAttackerPatch.name] is FireAtAttackerPatch

    def test_it_is_not_marked_experimental(self):
        """It lives in `patches/`, not `patches/experimental/`, and the two must agree."""
        assert FireAtAttackerPatch.experimental is False

    def test_str_names_the_keyword(self):
        assert str(FireAtAttackerPatch("Reflect")) == "fire-at-attacker (Reflect)"

    @pytest.mark.parametrize("keyword", ["", "9Lives", "Fire At Attacker", "Fire-At-Attacker"])
    def test_a_keyword_the_reader_could_never_match_is_refused(self, keyword):
        with pytest.raises(ValueError, match="INI keyword"):
            FireAtAttackerPatch(keyword)


class TestFieldPlacement:
    """Where the new `Bool` goes, and why that spot is free."""

    def test_the_field_sits_at_the_stock_sizeof(self):
        assert FLAG_OFFSET == FWWD_MODULEDATA_SIZE == 0x164

    def test_the_block_is_grown_by_exactly_the_dword_the_field_needs(self):
        assert GROWN_MODULEDATA_SIZE == FWWD_MODULEDATA_SIZE + 4

    def test_no_stock_field_reaches_the_new_one(self):
        """Every stock field is a dword or narrower, and the widest ends flush at `0x164`. If a
        future reading found a field past that, the grown block would land on top of it."""
        assert max(offset for _name, offset in STOCK_FIELDS) + 4 == FLAG_OFFSET

    def test_growing_the_allocation_is_five_bytes_for_five(self):
        grown = grown_size_bytes()
        assert len(grown) == len(FWWD_MODULEDATA_SIZE_BYTES)
        assert grown[:1] == FWWD_MODULEDATA_SIZE_BYTES[:1]  # still `push imm32`
        assert struct.unpack_from("<I", grown, 1)[0] == GROWN_MODULEDATA_SIZE

    def test_the_fingerprint_names_fields_the_stock_table_carries(self):
        stock = dict(STOCK_FIELDS)
        assert all(stock[name] == offset for name, offset in FINGERPRINT.items())


class TestTable:
    def test_the_live_rows_are_copied_verbatim(self):
        """Their name pointers are absolute - the strings stay in `.rdata` - so a rewritten row
        would point the reader at whatever now sits at that address."""
        rows = ((0x11111111, 0x22222222, 0x33333333, 0x44444444),)
        assert build_table(rows, 0xDEAD)[:FIELD_PARSE_STRIDE] == struct.pack("<IIII", *rows[0])

    def test_the_new_row_is_a_bool_at_the_new_offset(self):
        table = build_table((), 0xCAFE)
        assert struct.unpack_from("<IIII", table, 0) == (0xCAFE, INI_PARSE_BOOL, 0, FLAG_OFFSET)

    def test_it_is_terminated(self):
        table = build_table((), 0xCAFE)
        assert table[FIELD_PARSE_STRIDE:] == bytes(FIELD_PARSE_STRIDE)

    def test_the_patched_table_is_the_stock_rows_plus_one(self, patched):
        base, _vsize = _cave(patched)
        string = len(DEFAULT_KEYWORD) + 1
        table_va = base + string + (-string % 4)
        rows = at(patched, table_va, (len(STOCK_FIELDS) + 2) * FIELD_PARSE_STRIDE)
        stock = rows[: len(STOCK_FIELDS) * FIELD_PARSE_STRIDE]
        assert stock == at(patched, FWWD_FIELD_TABLE, len(stock))
        new = struct.unpack_from("<IIII", rows, len(STOCK_FIELDS) * FIELD_PARSE_STRIDE)
        assert new == (base, INI_PARSE_BOOL, 0, FLAG_OFFSET)

    def test_the_keyword_string_is_at_the_base_of_the_cave(self, patched):
        base, _vsize = _cave(patched)
        assert at(patched, base, len(DEFAULT_KEYWORD) + 1) == DEFAULT_KEYWORD.encode() + b"\x00"


class TestCode:
    """What the two routines actually say."""

    @pytest.fixture
    def code(self) -> bytes:
        return build_code(0x00F00000).finish()

    def test_the_ctor_shim_runs_the_stock_ctor_then_zeroes_the_field(self, code):
        call = struct.unpack_from("<i", code, 1)[0]
        assert code[0] == 0xE8
        assert 0x00F00000 + 5 + call == FWWD_MODULEDATA_CTOR
        # `mov dword [eax+0x164], 0`, then `ret` - no frame, so `newModuleData` still gets `this`
        assert code[5:15] == b"\xc7\x80" + struct.pack("<I", FLAG_OFFSET) + struct.pack("<I", 0)
        assert code[15] == 0xC3

    def test_the_aim_reads_the_moduledata_the_way_the_stock_code_does(self, code):
        """`mov eax, [esi-0x24]` - the same displacement `onDamage`'s own filters use, which is
        what ties the cave to `esi` still being the damage-interface sub-object."""
        aim = code[16:]
        assert aim[:3] == b"\x8b\x46" + bytes((FWWD_IFACE_MODULE_DATA_DISP & 0xFF,))
        assert ANCHORS[0x00885CEE] == aim[:3]

    def test_it_tests_the_new_field_and_falls_through_to_stock_on_no(self, code):
        aim = code[16:]
        assert aim[3:10] == b"\x80\xb8" + struct.pack("<I", FLAG_OFFSET) + b"\x00"
        assert aim[10] == 0x74  # je rel8, to the at-self tail

    def test_the_weapon_template_is_saved_across_the_lookup(self, code):
        """`ecx` carries the chosen `WeaponTemplate` into the fire call and is destroyed by
        `findObjectByID`. `push ecx` ... `pop ecx` is the only thing keeping it."""
        aim = code[16:]
        push = aim.index(b"\x51")
        pop = aim.index(b"\x59")
        lookup = aim.index(b"\x8b\x0d" + struct.pack("<I", THE_GAME_LOGIC))
        assert push < lookup < pop

    def test_it_resolves_the_damage_source_from_the_damage_info(self, code):
        aim = code[16:]
        # `mov eax,[esp+0x10]` - the DamageInfo, one push deeper than onDamage's own `[esp+0xc]`
        assert b"\x8b\x44\x24\x10" in aim
        # `push dword [eax+8]` - the attacker's ObjectID
        assert b"\xff\x70" + bytes((DAMAGE_INFO_SOURCE_ID,)) in aim

    def test_a_null_lookup_takes_the_same_path_as_no(self, code):
        """Two `je`s, both to the at-self tail: the field being off, and the source being gone."""
        aim = code[16:]
        assert aim.count(b"\x85\xc0\x74") == 1  # test eax,eax / je

    def test_the_yes_path_calls_the_victim_overload_and_skips_the_stock_call(self, code):
        base = 0x00F00000
        aim = code[16:]
        call_at = aim.index(b"\x50\x57\xe8") + 2  # push eax / push edi / call
        target = base + 16 + call_at + 5 + struct.unpack_from("<i", aim, call_at + 1)[0]
        assert target == CREATE_AND_FIRE_TEMP_WEAPON_AT_VICTIM
        jmp_at = call_at + 5
        assert aim[jmp_at] == 0xE9
        resume = base + 16 + jmp_at + 5 + struct.unpack_from("<i", aim, jmp_at + 1)[0]
        assert resume == FWWD_REACTION_FIRE_RESUME, "the Yes path must land past the stock call"

    def test_the_no_path_reproduces_the_displaced_bytes_and_returns_to_the_stock_call(self, code):
        base = 0x00F00000
        tail = code.index(FWWD_REACTION_AIM_BYTES, 16)
        assert code[tail : tail + len(FWWD_REACTION_AIM_BYTES)] == FWWD_REACTION_AIM_BYTES
        jmp_at = tail + len(FWWD_REACTION_AIM_BYTES)
        assert code[jmp_at] == 0xE9
        resume = base + jmp_at + 5 + struct.unpack_from("<i", code, jmp_at + 1)[0]
        assert resume == FWWD_REACTION_FIRE_CALL, "the No path must run the stock call"

    def test_the_lookup_targets_the_engines_own_resolver(self, code):
        base = 0x00F00000
        at_ = code.index(b"\x8b\x0d" + struct.pack("<I", THE_GAME_LOGIC)) + 6
        assert code[at_] == 0xE8
        assert base + at_ + 5 + struct.unpack_from("<i", code, at_ + 1)[0] == (
            GAME_LOGIC_FIND_OBJECT_BY_ID
        )

    def test_the_two_routines_move_together(self):
        """Laid out at a different base, every branch shifts with it - which is what says the
        addresses come from the layout rather than from a hardcoded guess."""
        assert build_code(0x00F00000).finish() != build_code(0x00F01000).finish()


class TestApply:
    def test_the_hook_is_a_bare_jump_with_nothing_to_pad(self, patched):
        """The displaced block is exactly five bytes, so a correct hook has no `nop` in it. A
        sixth byte here would mean the window was measured wrong."""
        window = at(patched, FWWD_REACTION_AIM, len(FWWD_REACTION_AIM_BYTES))
        assert len(window) == 5
        assert window[0] == 0xE9
        target = FWWD_REACTION_AIM + 5 + struct.unpack_from("<i", window, 1)[0]
        assert target == _code_va(patched) + 16  # the `aim` label, past the ctor shim

    def test_the_allocation_is_grown(self, patched):
        assert at(patched, FWWD_MODULEDATA_SIZE_VA, 5) == grown_size_bytes()

    def test_the_ctor_call_is_redirected_into_the_cave(self, patched):
        window = at(patched, FWWD_MODULEDATA_CTOR_CALL, 5)
        assert window[0] == 0xE8
        target = FWWD_MODULEDATA_CTOR_CALL + 5 + struct.unpack_from("<i", window, 1)[0]
        assert target == _code_va(patched)

    def test_the_parse_callback_names_the_rebuilt_table(self, patched):
        base, _vsize = _cave(patched)
        ref = FWWD_FIELD_TABLE_REFS[0]
        assert at(patched, ref, 1)[0] == FWWD_FIELD_TABLE_REF_OPCODES[0]
        string = len(DEFAULT_KEYWORD) + 1
        assert struct.unpack_from("<I", at(patched, ref + 1, 4))[0] == (
            base + string + (-string % 4)
        )

    def test_the_stock_table_is_left_where_it_was(self, patched):
        """It is `.rdata` nobody reaches any more, but rewriting it would break a second patch
        that read the live table before this one ran."""
        assert struct.unpack_from("<I", at(patched, FWWD_FIELD_TABLE + 12, 4))[0] == 0x138

    def test_apply_then_verify(self, patched):
        assert FireAtAttackerPatch().verify(patched) == []

    def test_a_clean_image_does_not_verify(self, image):
        problems = FireAtAttackerPatch().verify(image)
        assert problems and SECTION_NAME in problems[0]

    def test_applying_twice_is_refused(self, patched):
        with pytest.raises(ValueError, match="already has a 'FireAtAttacker' field"):
            FireAtAttackerPatch().apply(patched)

    def test_a_wrong_build_is_refused_before_a_byte_is_written(self, image):
        off = va_to_offset(image, FWWD_REACTION_FIRE_CALL)
        assert off is not None
        image[off] = 0x90  # the stock call is not where the derivation says
        with pytest.raises(ValueError, match="unexpected build"):
            FireAtAttackerPatch().apply(image)

    def test_a_table_that_does_not_look_like_this_build_is_refused(self, image):
        off = va_to_offset(image, FWWD_FIELD_TABLE)
        assert off is not None
        struct.pack_into("<I", image, off + 12, 0x999)  # StartsActive is not at 0x138
        with pytest.raises(ValueError, match="unexpected build"):
            FireAtAttackerPatch().apply(image)


class TestKeyword:
    def test_a_custom_keyword_round_trips(self):
        image = _image()
        FireAtAttackerPatch("ReflectAtSource").apply(image)
        found = FireAtAttackerPatch.detect(image)
        assert found is not None
        assert found.keyword == "ReflectAtSource"
        assert found.options() == {"keyword": "ReflectAtSource"}

    def test_detect_finds_nothing_in_a_clean_image(self, image):
        assert FireAtAttackerPatch.detect(image) is None

    def test_verify_rejects_the_wrong_keyword(self):
        image = _image()
        FireAtAttackerPatch("ReflectAtSource").apply(image)
        assert FireAtAttackerPatch(DEFAULT_KEYWORD).verify(image) != []


class TestIniSurface:
    def test_it_declares_the_one_bool_it_adds(self):
        (field,) = FireAtAttackerPatch().ini_surface().fields
        assert (field.block, field.name, field.type, field.default) == (
            "FireWeaponWhenDamagedBehavior",
            DEFAULT_KEYWORD,
            "Bool",
            False,
        )
        assert field.patch == FireAtAttackerPatch.name

    def test_it_reports_the_keyword_it_was_built_with(self):
        (field,) = FireAtAttackerPatch("ReflectAtSource").ini_surface().fields
        assert field.name == "ReflectAtSource"

    def test_the_stock_engine_does_not_already_have_it(self):
        assert not [
            field
            for field in STOCK.fields
            if (field.block, field.name) == ("FireWeaponWhenDamagedBehavior", DEFAULT_KEYWORD)
        ]


@pytest.mark.skipif(not _GAME_DAT.exists(), reason="requires a local ROTWK install")
class TestInstalledBinary:
    """The addresses, against the real thing. Everything above is self-consistent by construction;
    only this says the sites are where the patch claims."""

    @pytest.fixture
    def installed(self) -> bytearray:
        return bytearray(_GAME_DAT.read_bytes())

    def test_every_anchor_is_present(self, installed):
        for va, expected in ANCHORS.items():
            assert at(installed, va, len(expected)) == expected, f"0x{va:08x}"

    def test_the_three_edited_windows_are_stock(self, installed):
        for va, expected in (
            (FWWD_MODULEDATA_SIZE_VA, FWWD_MODULEDATA_SIZE_BYTES),
            (FWWD_MODULEDATA_CTOR_CALL, FWWD_MODULEDATA_CTOR_CALL_BYTES),
            (FWWD_REACTION_AIM, FWWD_REACTION_AIM_BYTES),
        ):
            assert at(installed, va, len(expected)) == expected, f"0x{va:08x}"

    def test_the_field_table_is_the_one_the_stock_fields_describe(self, installed):
        ref = FWWD_FIELD_TABLE_REFS[0]
        assert at(installed, ref, 1)[0] == FWWD_FIELD_TABLE_REF_OPCODES[0]
        assert struct.unpack_from("<I", at(installed, ref + 1, 4))[0] == FWWD_FIELD_TABLE
        rows = at(installed, FWWD_FIELD_TABLE, (len(STOCK_FIELDS) + 1) * FIELD_PARSE_STRIDE)
        offsets = [
            struct.unpack_from("<IIII", rows, index * FIELD_PARSE_STRIDE)[3]
            for index in range(len(STOCK_FIELDS))
        ]
        assert offsets == [offset for _name, offset in STOCK_FIELDS]
        assert rows[len(STOCK_FIELDS) * FIELD_PARSE_STRIDE :] == bytes(FIELD_PARSE_STRIDE)

    def test_apply_then_verify(self, installed):
        patch = FireAtAttackerPatch()
        assert patch.verify(installed) != []
        patch.apply(installed)
        assert patch.verify(installed) == []
