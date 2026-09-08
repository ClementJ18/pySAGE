"""Tests for the map-list-symbols patch.

The cave is hand-assembled x86 that cannot be executed here, so the tests that matter most
disassemble it back and assert it says what it was meant to say. Three things get particular
attention, because each is invisible in the bytes and none of them raises when it is wrong:

* **Stack discipline across the two calls the cave makes into the engine.** `MapMetaData::operator=`
  is ``ret 4`` and consumes the argument the *insert* left on the stack, so the store hook has to
  re-push it rather than tail-jump; `INI_PARSE_FIELDS` is ``ret 8`` and cleans both of its own, so
  the pre-fields hook has to tail-jump rather than call. Getting either backwards unbalances the
  parser's stack a `MapCache` block at a time.
* **The flags the save hook carries across itself.** It replaces the two instructions between a
  ``cmp`` and the ``je`` that reads it, so everything it adds sits inside a ``pushfd``/``popfd``.
  Without that, every non-multiplayer map takes the wrong arm of pass 1.
* **The three ways out of the pick stub**, which have to leave the stock ladder holding the key in
  ``eax`` and the flags of ``cmp eax, 0x8001`` - the ladder branches on them five bytes past the
  point it rejoins - and have to pop back to a balanced stack on each.

The other half of the suite is the build fingerprint. This patch reads five things it does not
rewrite - the `MapCache` field table it copies, the assignment operator its store hook wraps, the
insert whose ``ret 4`` that hook depends on, the comparator arm that turns the key into a sort
order, and the mapped-image lookup's convention - and each has to fail loudly on anything that is
not the expected build.
"""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

pytest.importorskip("capstone", reason="the [patch] extra (capstone) is not installed")
from capstone import CS_ARCH_X86, CS_MODE_32, Cs  # noqa: E402 - after the importorskip guard

from sage_patch import MapListSymbolsPatch, apply_patches  # noqa: E402
from sage_patch.addresses import (  # noqa: E402
    ASCII_STRING_CTOR,
    ASCII_STRING_DTOR,
    FIELD_PARSE_STRIDE,
    INI_PARSE_FIELDS,
    INI_PARSE_INT,
    MAP_CACHE_ASSIGN_CALL,
    MAP_CACHE_ASSIGN_CALL_BYTES,
    MAP_CACHE_FIELD_TABLE,
    MAP_CACHE_FIELD_TABLE_GETTER_REF,
    MAP_CACHE_FIELD_TABLE_PARSE_REF,
    MAP_CACHE_PARSE_FIELDS,
    MAP_CACHE_PARSE_FIELDS_BYTES,
    MAP_CACHE_STOCK_FIELDS,
    MAP_LIST_ANCHORS,
    MAP_LIST_COMPARE_KEY,
    MAP_LIST_COMPARE_KEY_BYTES,
    MAP_LIST_COMPARE_KEY_RESUME,
    MAP_LIST_ICON_LADDER,
    MAP_LIST_ICON_LADDER_BYTES,
    MAP_LIST_ICON_LADDER_RESUME,
    MAP_LIST_OFFICIAL_BIT,
    MAP_LIST_OFFICIAL_BIT_BYTES,
    MAP_LIST_OFFICIAL_BIT_RESUME,
    MAP_LIST_RESOLVE,
    MAP_LIST_RESOLVE_BYTES,
    MAP_LIST_RESOLVE_RESUME,
    MAP_LIST_ROW_ADD,
    MAP_LIST_SAVE_KEY,
    MAP_LIST_SAVE_KEY_BYTES,
    MAP_LIST_SAVE_KEY_RESUME,
    MAP_META_DATA_ASSIGN,
    MAP_META_DATA_IS_OFFICIAL,
    MAP_META_DATA_SORT_KEY,
    OBJECT_IMAGE_UPGRADE_FIND_IMAGE,
    OBJECT_IMAGE_UPGRADE_THE_IMAGES,
)
from sage_patch.patches.map_list_symbols import (  # noqa: E402
    DEFAULT_KEYWORD,
    DEFAULT_SYMBOLS,
    FLAG_SORT_BY_SYMBOL,
    IMAGE_STATES,
    MAX_SYMBOLS,
    SECTION_NAME,
    SYMBOL_MASK,
    SYMBOL_SHIFT,
    _layout,
    image_names,
)
from sage_patch.registry import PATCHES  # noqa: E402
from sage_patch.utils import find_section, va_to_offset  # noqa: E402
from tests.sage_patch.synthetic import map_list_symbols_image  # noqa: E402

#: Every site the patch rewrites, with the bytes it expects to find there. The two table
#: references are imm32s inside an instruction and are checked separately.
CODE_SITES = (
    (MAP_CACHE_PARSE_FIELDS, MAP_CACHE_PARSE_FIELDS_BYTES),
    (MAP_CACHE_ASSIGN_CALL, MAP_CACHE_ASSIGN_CALL_BYTES),
    (MAP_LIST_RESOLVE, MAP_LIST_RESOLVE_BYTES),
    (MAP_LIST_SAVE_KEY, MAP_LIST_SAVE_KEY_BYTES),
    (MAP_LIST_OFFICIAL_BIT, MAP_LIST_OFFICIAL_BIT_BYTES),
    (MAP_LIST_ICON_LADDER, MAP_LIST_ICON_LADDER_BYTES),
)


@pytest.fixture
def image() -> bytearray:
    return map_list_symbols_image()


def at(data: bytes | bytearray, va: int, count: int) -> bytes:
    off = va_to_offset(data, va)
    assert off is not None, f"0x{va:08x} is not mapped"
    return bytes(data[off : off + count])


def disassemble(data: bytes | bytearray, va: int, size: int) -> list[str]:
    md = Cs(CS_ARCH_X86, CS_MODE_32)
    return [f"{i.mnemonic} {i.op_str}".strip() for i in md.disasm(at(data, va, size), va)]


def patched(
    keyword: str = DEFAULT_KEYWORD,
    symbols: int = DEFAULT_SYMBOLS,
    sort_by_symbol: bool = False,
) -> bytearray:
    data = map_list_symbols_image()
    MapListSymbolsPatch(keyword, symbols, sort_by_symbol).apply(data)
    return data


def pieces(data: bytes | bytearray):  # noqa: ANN201 - the private layout record
    located = find_section(data, SECTION_NAME)
    assert located is not None
    return _layout(located[0], *MapListSymbolsPatch._installed_parameters(data, located[0]))


def imm(value: int) -> str:
    """An immediate the way capstone prints it: decimal below ten, hexadecimal from ten up."""
    return str(value) if value < 10 else f"{value:#x}"


def stub(data: bytes | bytearray, start: int, end: int) -> list[str]:
    return disassemble(data, start, end - start)


def compare(data: bytes | bytearray) -> list[str]:
    """The comparator stub, which is last in the cave when it is installed at all."""
    located = find_section(data, SECTION_NAME)
    assert located is not None
    section_va, _off, vsize = located
    compare_va = pieces(data).compare_va
    assert compare_va is not None
    text = stub(data, compare_va, section_va + vsize)
    return text[: next(i for i, line in enumerate(text) if line.startswith("jmp ")) + 1]


def pick(data: bytes | bytearray) -> list[str]:
    """The pick stub, which is last in the cave and so runs to the section's end."""
    located = find_section(data, SECTION_NAME)
    assert located is not None
    section_va, _off, vsize = located
    return stub(data, pieces(data).pick_va, section_va + vsize)


class TestRoundTrip:
    def test_apply_then_verify(self, image: bytearray) -> None:
        patch = MapListSymbolsPatch()
        patch.apply(image)
        assert patch.verify(bytes(image)) == []

    def test_a_stock_image_carries_nothing(self, image: bytearray) -> None:
        assert MapListSymbolsPatch.detect(bytes(image)) is None
        assert MapListSymbolsPatch().verify(bytes(image)) != []

    def test_detect_recovers_both_parameters(self) -> None:
        found = MapListSymbolsPatch.detect(bytes(patched("mapIcon", 3)))
        assert found is not None
        assert found.options() == {
            "keyword": "mapIcon",
            "symbols": 3,
            "sort_by_symbol": False,
        }

    def test_verify_names_the_parameters_rather_than_a_size(self) -> None:
        problems = MapListSymbolsPatch().verify(bytes(patched("mapIcon", 3)))
        assert len(problems) == 1
        assert "mapIcon" in problems[0]

    def test_verify_catches_a_reverted_site(self) -> None:
        data = patched()
        off = va_to_offset(data, MAP_LIST_ICON_LADDER)
        assert off is not None
        data[off : off + len(MAP_LIST_ICON_LADDER_BYTES)] = MAP_LIST_ICON_LADDER_BYTES
        assert MapListSymbolsPatch().verify(bytes(data)) != []

    def test_apply_writes_a_file_and_leaves_the_input_alone(self, tmp_path: Path) -> None:
        source = tmp_path / "game.dat"
        source.write_bytes(bytes(map_list_symbols_image()))
        before = source.read_bytes()
        out = apply_patches(source, [MapListSymbolsPatch()], tmp_path / "patched.dat")
        assert source.read_bytes() == before
        assert MapListSymbolsPatch().verify(out.read_bytes()) == []

    def test_it_is_registered(self) -> None:
        assert PATCHES[MapListSymbolsPatch.name] is MapListSymbolsPatch


class TestTheEdits:
    def test_every_code_hook_replaces_whole_instructions_with_a_jump_or_call(self) -> None:
        data = patched()
        for va, original in CODE_SITES:
            replacement = at(data, va, len(original))
            assert replacement[:1] in (b"\xe9", b"\xe8"), f"0x{va:08x} is not a branch"
            assert replacement[5:] == b"\x90" * (len(original) - 5), (
                f"0x{va:08x} does not pad the instructions it displaced"
            )

    def test_the_edits_keep_their_lengths(self, image: bytearray) -> None:
        patch = MapListSymbolsPatch()
        for _off, old, new, _note in patch._edits(image, pieces(patched())):
            assert len(old) == len(new)

    def test_both_table_references_are_repointed_into_the_cave(self) -> None:
        data = patched()
        table = pieces(data).table_va
        assert table != MAP_CACHE_FIELD_TABLE
        for va in (MAP_CACHE_FIELD_TABLE_GETTER_REF, MAP_CACHE_FIELD_TABLE_PARSE_REF):
            assert struct.unpack("<I", at(data, va, 4))[0] == table

    def test_the_reference_edits_leave_their_opcodes_alone(self) -> None:
        data = patched()
        assert at(data, MAP_CACHE_FIELD_TABLE_GETTER_REF - 1, 1) == b"\xb8"  # mov eax, imm32
        assert at(data, MAP_CACHE_FIELD_TABLE_PARSE_REF - 1, 1) == b"\x68"  # push imm32

    def test_the_two_parse_side_hooks_are_calls_and_the_three_ui_ones_are_jumps(self) -> None:
        data = patched()
        for va in (MAP_CACHE_PARSE_FIELDS, MAP_CACHE_ASSIGN_CALL):
            assert at(data, va, 1) == b"\xe8", f"0x{va:08x} must stay a call"
        jumps = (MAP_LIST_RESOLVE, MAP_LIST_SAVE_KEY, MAP_LIST_OFFICIAL_BIT, MAP_LIST_ICON_LADDER)
        for va in jumps:
            assert at(data, va, 1) == b"\xe9", f"0x{va:08x} must be a jump"


class TestTheTable:
    def test_the_stock_rows_are_copied_verbatim(self) -> None:
        data = patched()
        table = pieces(data).table_va
        size = len(MAP_CACHE_STOCK_FIELDS) * FIELD_PARSE_STRIDE
        assert at(data, table, size) == at(data, MAP_CACHE_FIELD_TABLE, size)

    def test_the_added_row_is_last_and_names_the_caves_own_parser(self) -> None:
        data = patched()
        layout = pieces(data)
        row = layout.table_va + len(MAP_CACHE_STOCK_FIELDS) * FIELD_PARSE_STRIDE
        name_va, parse_fn, user_data, offset = struct.unpack("<4I", at(data, row, 16))
        assert name_va == layout.keyword_va
        assert parse_fn == layout.parse_va
        assert (user_data, offset) == (0, 0)

    def test_the_table_is_terminated(self) -> None:
        data = patched()
        end = pieces(data).table_va + (len(MAP_CACHE_STOCK_FIELDS) + 1) * FIELD_PARSE_STRIDE
        assert at(data, end, FIELD_PARSE_STRIDE) == bytes(FIELD_PARSE_STRIDE)

    def test_the_keyword_string_is_where_the_row_points(self) -> None:
        data = patched("mapIcon", 2)
        assert at(data, pieces(data).keyword_va, 8) == b"mapIcon\x00"

    def test_a_keyword_the_block_already_parses_is_refused(self) -> None:
        for name, _offset in MAP_CACHE_STOCK_FIELDS:
            with pytest.raises(ValueError, match="already a MapCache field"):
                MapListSymbolsPatch(name.lower())

    def test_a_keyword_the_reader_could_never_match_is_refused(self) -> None:
        for bad in ("", "map symbol", "map-symbol", "2symbols", "map=symbol"):
            with pytest.raises(ValueError, match="not a valid INI keyword"):
                MapListSymbolsPatch(bad)

    def test_a_symbol_count_the_names_cannot_spell_is_refused(self) -> None:
        for bad in (0, -1, MAX_SYMBOLS + 1):
            with pytest.raises(ValueError, match="symbols must be between"):
                MapListSymbolsPatch(symbols=bad)

    def test_a_table_that_is_not_this_build_is_refused(self, image: bytearray) -> None:
        off = va_to_offset(image, MAP_CACHE_FIELD_TABLE)
        assert off is not None
        struct.pack_into("<I", image, off + 12, 0x99)  # isOfficial's offset into the temporary
        with pytest.raises(ValueError, match="expected offset 0x28"):
            MapListSymbolsPatch().apply(image)

    def test_a_table_that_is_not_terminated_is_refused(self, image: bytearray) -> None:
        off = va_to_offset(image, MAP_CACHE_FIELD_TABLE)
        assert off is not None
        end = off + len(MAP_CACHE_STOCK_FIELDS) * FIELD_PARSE_STRIDE
        struct.pack_into("<I", image, end, 0xDEADBEEF)
        with pytest.raises(ValueError, match="not NULL-terminated"):
            MapListSymbolsPatch().apply(image)


class TestTheImageNames:
    def test_the_seven_states_start_with_the_bare_name(self) -> None:
        assert IMAGE_STATES[0] == ""
        assert len(IMAGE_STATES) == 7

    def test_the_six_states_are_the_engines_own_spelling(self) -> None:
        assert IMAGE_STATES[1:] == (
            "NotConquered",
            "EasyConquered",
            "MedConquered",
            "HardConquered",
            "BrutalConquered",
            "MaxConquered",
        )

    def test_the_names_are_symbol_major_and_two_digits(self) -> None:
        names = image_names(2)
        assert len(names) == 14
        assert names[0] == "AptMapSymbol01"
        assert names[1] == "AptMapSymbol01NotConquered"
        assert names[7] == "AptMapSymbol02"
        assert names[13] == "AptMapSymbol02MaxConquered"

    def test_every_name_is_in_the_cave_where_its_pointer_says(self) -> None:
        data = patched("mapSymbol", 3)
        layout = pieces(data)
        names = image_names(3)
        pointers = struct.unpack(f"<{len(names)}I", at(data, layout.names_va, len(names) * 4))
        for name, pointer in zip(names, pointers, strict=True):
            assert at(data, pointer, len(name) + 1) == name.encode("ascii") + b"\x00"

    def test_the_image_array_is_scratch_and_starts_empty(self) -> None:
        data = patched("mapSymbol", 3)
        layout = pieces(data)
        span = layout.names_va - layout.images_va
        assert span == len(image_names(3)) * 4
        assert at(data, layout.images_va, span) == bytes(span)


class TestTheKeyPacking:
    def test_the_symbol_sits_above_the_official_bit_and_the_difficulty(self) -> None:
        """Bit 15 is `isOfficial` and bits 0-3 the conquered difficulty, both written by pass 1.

        The symbol has to clear them, and clearing them is also what makes it the *primary*
        grouping when the icon column is sorted: the comparator subtracts whole keys."""
        assert SYMBOL_SHIFT == 16

    def test_the_save_hook_keeps_exactly_the_symbols_half_of_the_key(self) -> None:
        data = patched()
        text = stub(data, pieces(data).save_va, pieces(data).key_va)
        assert "and eax, 0xffff0000" in text


class TestTheParseStub:
    def test_it_reads_an_int_the_way_numplayers_does(self) -> None:
        data = patched()
        layout = pieces(data)
        text = stub(data, layout.parse_va, layout.pre_fields_va)
        assert f"call 0x{INI_PARSE_INT:x}" in text

    def test_it_hands_the_parser_a_slot_of_its_own_rather_than_the_store_it_was_given(self) -> None:
        """``store`` points into the parse temporary, whose layout past the stock fields this
        patch deliberately makes no claim about."""
        data = patched()
        layout = pieces(data)
        text = stub(data, layout.parse_va, layout.pre_fields_va)
        assert text[0] == "sub esp, 4"
        assert "lea eax, [esp + 4]" in text

    def test_it_balances_the_stack_it_built_for_the_cdecl_call(self) -> None:
        data = patched()
        layout = pieces(data)
        text = stub(data, layout.parse_va, layout.pre_fields_va)
        assert text.count("push 0") == 2  # instance and userData
        assert "add esp, 0x10" in text
        assert text[-1] == "ret"

    def test_an_out_of_range_symbol_becomes_no_symbol(self) -> None:
        data = patched("mapSymbol", 4)
        layout = pieces(data)
        text = stub(data, layout.parse_va, layout.pre_fields_va)
        assert "cmp eax, 4" in text
        assert "xor eax, eax" in text

    def test_it_stores_the_symbol_already_shifted(self) -> None:
        data = patched()
        layout = pieces(data)
        text = stub(data, layout.parse_va, layout.pre_fields_va)
        assert f"shl eax, {SYMBOL_SHIFT:#x}" in text
        assert f"mov dword ptr [{layout.pending_va:#x}], eax" in text


class TestThePreFieldsStub:
    def test_it_clears_the_pending_symbol_before_a_blocks_fields_are_read(self) -> None:
        data = patched()
        layout = pieces(data)
        text = stub(data, layout.pre_fields_va, layout.store_va)
        assert text[0] == f"and dword ptr [{layout.pending_va:#x}], 0"

    def test_it_tail_jumps_so_the_parsers_own_cleanup_returns_to_the_caller(self) -> None:
        """`INI_PARSE_FIELDS` is ``__thiscall`` with two stack arguments and cleans them itself.
        Jumping into it leaves ``ecx``, both arguments and the return address exactly as the
        stock ``call`` did; calling it would strand a return address."""
        data = patched()
        layout = pieces(data)
        text = stub(data, layout.pre_fields_va, layout.store_va)
        assert text[-1] == f"jmp 0x{INI_PARSE_FIELDS:x}"


class TestTheStoreStub:
    def test_the_stock_copy_runs_first(self) -> None:
        """It is what fills the entry, and it copies ``+0xF4`` from a freshly constructed source -
        so a symbol written before it would be overwritten by a zero."""
        data = patched()
        layout = pieces(data)
        text = stub(data, layout.store_va, layout.resolve_va)
        layout = pieces(data)
        assert text.index(f"call 0x{MAP_META_DATA_ASSIGN:x}") < text.index(
            f"mov eax, dword ptr [{layout.pending_va:#x}]"
        )

    def test_it_re_pushes_the_argument_the_insert_left_behind(self) -> None:
        """`MapCache::insert` is ``ret 4`` and leaves the source pointer on the stack as this
        call's argument; the callee is ``ret 4`` too, so the cave has to push a second copy and
        return with ``ret 4`` of its own."""
        data = patched()
        layout = pieces(data)
        text = stub(data, layout.store_va, layout.resolve_va)
        assert text[0] == "push ecx"
        assert text[1] == "push dword ptr [esp + 8]"
        assert text[-1] == "ret 4"

    def test_it_writes_the_symbol_into_the_stored_entrys_key(self) -> None:
        data = patched()
        layout = pieces(data)
        text = stub(data, layout.store_va, layout.resolve_va)
        assert f"mov dword ptr [ecx + {MAP_META_DATA_SORT_KEY:#x}], eax" in text

    def test_it_clears_the_pending_symbol_on_the_way_out_too(self) -> None:
        data = patched()
        layout = pieces(data)
        text = stub(data, layout.store_va, layout.resolve_va)
        assert text.count(f"and dword ptr [{layout.pending_va:#x}], 0") == 1

    def test_it_returns_what_the_stock_call_returned(self) -> None:
        data = patched()
        layout = pieces(data)
        text = stub(data, layout.store_va, layout.resolve_va)
        assert "mov eax, ecx" in text


class TestTheResolveStub:
    def test_it_walks_every_name_once(self) -> None:
        data = patched("mapSymbol", 3)
        layout = pieces(data)
        text = stub(data, layout.resolve_va, layout.save_va)
        assert f"cmp ebx, {len(image_names(3)):#x}" in text
        assert "inc ebx" in text

    def test_it_builds_and_destroys_the_asciistring_the_lookup_wants(self) -> None:
        data = patched()
        layout = pieces(data)
        text = stub(data, layout.resolve_va, layout.save_va)
        assert f"call 0x{ASCII_STRING_CTOR:x}" in text
        assert f"call 0x{OBJECT_IMAGE_UPGRADE_FIND_IMAGE:x}" in text
        assert f"call 0x{ASCII_STRING_DTOR:x}" in text
        assert text.index(f"call 0x{ASCII_STRING_CTOR:x}") < text.index(
            f"call 0x{OBJECT_IMAGE_UPGRADE_FIND_IMAGE:x}"
        )
        assert text.index(f"call 0x{OBJECT_IMAGE_UPGRADE_FIND_IMAGE:x}") < text.index(
            f"call 0x{ASCII_STRING_DTOR:x}"
        )

    def test_it_asks_the_collection_the_stock_lookups_ask(self) -> None:
        data = patched()
        layout = pieces(data)
        text = stub(data, layout.resolve_va, layout.save_va)
        assert f"mov ecx, dword ptr [{OBJECT_IMAGE_UPGRADE_THE_IMAGES:#x}]" in text

    def test_a_name_with_no_pointer_leaves_a_null_image_rather_than_stale_one(self) -> None:
        data = patched()
        layout = pieces(data)
        text = stub(data, layout.resolve_va, layout.save_va)
        assert f"and dword ptr [ebx*4 + {layout.images_va:#x}], 0" in text

    def test_it_restores_every_register_and_the_displaced_push(self) -> None:
        data = patched()
        layout = pieces(data)
        text = stub(data, layout.resolve_va, layout.save_va)
        pushes = [line for line in text if line.startswith("push ") and "ptr" not in line]
        pops = [line for line in text if line.startswith("pop ")]
        assert pushes[:6] == [
            "push eax",
            "push ecx",
            "push edx",
            "push ebx",
            "push esi",
            "push edi",
        ]
        assert pops[-6:] == ["pop edi", "pop esi", "pop ebx", "pop edx", "pop ecx", "pop eax"]
        assert text[-2] == f"push {struct.unpack('<I', MAP_LIST_RESOLVE_BYTES[1:])[0]:#x}"
        assert text[-1] == f"jmp 0x{MAP_LIST_RESOLVE_RESUME:x}"

    def test_it_leaves_the_stack_it_borrowed_for_the_string(self) -> None:
        data = patched()
        layout = pieces(data)
        text = stub(data, layout.resolve_va, layout.save_va)
        assert text.count("sub esp, 4") == text.count("add esp, 4") == 1


class TestTheSaveStub:
    def test_both_displaced_instructions_come_first(self) -> None:
        data = patched()
        layout = pieces(data)
        text = stub(data, layout.save_va, layout.key_va)
        assert text[:2] == ["mov eax, dword ptr [ebp + 8]", "mov esi, dword ptr [eax]"]

    def test_everything_that_touches_the_flags_sits_inside_pushfd_popfd(self) -> None:
        """The `ZF` the resume point branches on was set three bytes before the hook, by the test
        for a null stats object; the two displaced ``mov``s do not disturb it and neither may
        anything the cave adds."""
        data = patched()
        layout = pieces(data)
        text = stub(data, layout.save_va, layout.key_va)
        assert text.index("pushfd") == 2
        assert text[-2] == "popfd"
        assert "and eax" in " ".join(text[3:-2])

    def test_it_reads_the_key_and_rejoins_where_it_left(self) -> None:
        data = patched()
        layout = pieces(data)
        text = stub(data, layout.save_va, layout.key_va)
        assert f"mov eax, dword ptr [esi + {MAP_META_DATA_SORT_KEY:#x}]" in text
        assert f"mov dword ptr [{layout.carry_va:#x}], eax" in text
        assert text[-1] == f"jmp 0x{MAP_LIST_SAVE_KEY_RESUME:x}"


class TestTheApplyKeyStub:
    def test_the_stock_official_bit_is_reproduced_byte_for_byte(self) -> None:
        """A map with no symbol has to come out of this hook holding exactly the key the stock
        engine would have given it, which is what makes `mapSymbol = 0` mean 'unpatched'."""
        data = patched()
        layout = pieces(data)
        stock = MAP_LIST_OFFICIAL_BIT_BYTES[:-2]
        assert at(data, layout.key_va, len(stock)) == stock

    def test_it_ors_the_carry_back_on_top(self) -> None:
        data = patched()
        layout = pieces(data)
        text = stub(data, layout.key_va, layout.pick_va)
        assert f"mov eax, dword ptr [{layout.carry_va:#x}]" in text
        assert f"or dword ptr [esi + {MAP_META_DATA_SORT_KEY:#x}], eax" in text

    def test_it_still_reads_the_official_byte_the_engine_reads(self) -> None:
        data = patched()
        layout = pieces(data)
        text = stub(data, layout.key_va, layout.pick_va)
        assert f"cmp byte ptr [esi + {MAP_META_DATA_IS_OFFICIAL:#x}], 0" in text

    def test_it_rejoins_past_the_thirteen_bytes_it_replaced(self) -> None:
        data = patched()
        layout = pieces(data)
        text = stub(data, layout.key_va, layout.pick_va)
        assert text[-1] == f"jmp 0x{MAP_LIST_OFFICIAL_BIT_RESUME:x}"
        replaced = len(MAP_LIST_OFFICIAL_BIT_BYTES)
        assert MAP_LIST_OFFICIAL_BIT_RESUME == MAP_LIST_OFFICIAL_BIT + replaced


class TestThePickStub:
    def test_a_row_with_no_symbol_is_handed_back_to_the_stock_ladder(self) -> None:
        data = patched()
        pieces(data)
        text = pick(data)
        assert text[0] == f"mov eax, dword ptr [esi + {MAP_META_DATA_SORT_KEY:#x}]"
        assert text[1] == "push eax"
        assert f"shr eax, {SYMBOL_SHIFT:#x}" in text

    def test_declining_restores_the_key_and_the_flags_the_ladder_branches_on(self) -> None:
        data = patched()
        pieces(data)
        text = pick(data)
        assert text[-3:] == ["pop eax", "cmp eax, 0x8001", f"jmp 0x{MAP_LIST_ICON_LADDER_RESUME:x}"]
        assert MAP_LIST_ICON_LADDER_RESUME == MAP_LIST_ICON_LADDER + len(MAP_LIST_ICON_LADDER_BYTES)

    def test_a_symbol_this_build_has_no_room_for_declines_rather_than_reads_past_the_array(
        self,
    ) -> None:
        data = patched("mapSymbol", 5)
        pieces(data)
        text = pick(data)
        assert "cmp eax, 5" in text

    def test_the_state_is_the_keys_low_nibble_clamped_to_the_six(self) -> None:
        data = patched()
        pieces(data)
        text = pick(data)
        assert "and ecx, 0xf" in text
        assert f"cmp ecx, {imm(len(IMAGE_STATES) - 1)}" in text

    def test_the_index_is_symbol_major_the_way_the_names_are(self) -> None:
        data = patched()
        pieces(data)
        text = pick(data)
        assert f"imul eax, eax, {imm(len(IMAGE_STATES))}" in text
        assert "add eax, ecx" in text

    def test_a_missing_state_falls_back_to_the_bare_name_and_then_to_stock(self) -> None:
        data = patched()
        layout = pieces(data)
        text = pick(data)
        want = f"mov eax, dword ptr [eax*4 + {layout.images_va:#x}]"
        lookups = [line for line in text if line == want]
        assert len(lookups) == 2, "one lookup for this state, one for the bare name"
        assert text.count("test eax, eax") == 2

    def test_a_symbol_writes_the_image_the_ladders_arms_write_and_skips_them(self) -> None:
        data = patched()
        pieces(data)
        text = pick(data)
        assert "mov dword ptr [ebp + 8], eax" in text
        assert f"jmp 0x{MAP_LIST_ROW_ADD:x}" in text

    def test_every_way_out_pops_what_it_pushed(self) -> None:
        data = patched()
        pieces(data)
        text = pick(data)
        # the key, then this symbol's base index; both exits that reach the second pop it first
        assert text.count("push eax") == 2
        assert text.count("pop ecx") == 2
        assert text.count("pop eax") == 2


class TestSortBySymbol:
    """``--sort-by-symbol``: the icon column orders on the symbol and nothing below it.

    Without it the comparator subtracts whole keys, so two maps sharing a symbol but differing in
    conquered state never tie and the sort orders them by that state. Masking makes them tie, and
    a tie is what sends the comparator on to its next key - the secondary sort column."""

    def test_a_default_build_leaves_the_comparator_alone(self) -> None:
        data = patched()
        assert at(data, MAP_LIST_COMPARE_KEY, len(MAP_LIST_COMPARE_KEY_BYTES)) == (
            MAP_LIST_COMPARE_KEY_BYTES
        )

    def test_it_hooks_the_comparator_and_pads_what_it_displaced(self) -> None:
        data = patched(sort_by_symbol=True)
        replacement = at(data, MAP_LIST_COMPARE_KEY, len(MAP_LIST_COMPARE_KEY_BYTES))
        assert replacement[:1] == bytes.fromhex("e9")
        assert replacement[5:] == bytes.fromhex("90") * (len(MAP_LIST_COMPARE_KEY_BYTES) - 5)

    def test_the_hook_rejoins_exactly_past_the_bytes_it_took(self) -> None:
        replaced = len(MAP_LIST_COMPARE_KEY_BYTES)
        assert MAP_LIST_COMPARE_KEY_RESUME == MAP_LIST_COMPARE_KEY + replaced

    def test_both_operands_are_masked_to_the_symbol(self) -> None:
        """One masked operand would order by the *difference* of two unmasked keys, which is not
        the same relation and is not even a consistent one."""
        data = patched(sort_by_symbol=True)
        text = compare(data)
        assert text.count(f"and eax, {SYMBOL_MASK:#x}") == 1
        assert text.count(f"and edx, {SYMBOL_MASK:#x}") == 1
        assert "sub eax, edx" in text

    def test_the_mask_keeps_the_symbol_and_drops_everything_under_it(self) -> None:
        assert SYMBOL_MASK == 0xFFFF0000
        assert SYMBOL_MASK >> SYMBOL_SHIFT == 0xFFFF  # every symbol the key can hold
        assert SYMBOL_MASK & 0x8000 == 0  # ... and neither isOfficial
        assert SYMBOL_MASK & 0xF == 0  # ... nor the conquered nibble survives it

    def test_it_reproduces_the_two_instructions_interleaved_with_the_delta(self) -> None:
        """The stock arm is `mov eax` / `mov ecx, [ebp-0x10]` / `sub eax` / `mov ecx, [ecx]` - the
        functor load sits *between* the two halves of the subtraction, so a hook that took the
        whole span owes the caller both."""
        data = patched(sort_by_symbol=True)
        text = compare(data)
        assert text[-3:-1] == ["mov ecx, dword ptr [ebp - 0x10]", "mov ecx, dword ptr [ecx]"]
        assert text[-1] == f"jmp 0x{MAP_LIST_COMPARE_KEY_RESUME:x}"

    def test_it_reads_the_two_entries_the_comparator_was_given(self) -> None:
        data = patched(sort_by_symbol=True)
        text = compare(data)
        assert f"mov eax, dword ptr [ebx + {MAP_META_DATA_SORT_KEY:#x}]" in text
        assert f"mov edx, dword ptr [edi + {MAP_META_DATA_SORT_KEY:#x}]" in text

    def test_the_option_round_trips(self) -> None:
        found = MapListSymbolsPatch.detect(bytes(patched("mapIcon", 3, sort_by_symbol=True)))
        assert found is not None
        assert found.options() == {
            "keyword": "mapIcon",
            "symbols": 3,
            "sort_by_symbol": True,
        }

    def test_the_two_builds_do_not_verify_as_each_other(self) -> None:
        assert MapListSymbolsPatch(sort_by_symbol=True).verify(bytes(patched())) != []
        assert MapListSymbolsPatch().verify(bytes(patched(sort_by_symbol=True))) != []

    def test_the_flag_is_recorded_in_the_cave_rather_than_inferred(self) -> None:
        """`detect` reads it, so it cannot be confused with a binary somebody hooked by hand."""
        for flag in (False, True):
            data = patched(sort_by_symbol=flag)
            layout = pieces(data)
            expected = FLAG_SORT_BY_SYMBOL if flag else 0
            assert struct.unpack("<I", at(data, layout.flags_va, 4))[0] == expected

    def test_a_cave_with_flags_this_build_does_not_know_is_refused(self) -> None:
        data = patched()
        layout = pieces(data)
        off = va_to_offset(data, layout.flags_va)
        assert off is not None
        struct.pack_into("<I", data, off, 0x40)
        assert MapListSymbolsPatch.detect(bytes(data)) is None

    def test_the_stub_is_absent_from_a_default_build(self) -> None:
        assert pieces(patched()).compare_va is None
        assert pieces(patched(sort_by_symbol=True)).compare_va is not None

    def test_the_icon_still_tracks_the_conquered_state(self) -> None:
        """The option changes the *comparator*, not the key and not the ladder, so a masked sort
        and a per-difficulty icon are independent."""
        plain, sorted_ = patched(), patched(sort_by_symbol=True)
        assert stub(plain, pieces(plain).pick_va, pieces(plain).pick_va + 0x40) == stub(
            sorted_, pieces(sorted_).pick_va, pieces(sorted_).pick_va + 0x40
        )


class TestTheBuildFingerprint:
    def test_every_anchor_is_checked_before_a_byte_is_written(self, image: bytearray) -> None:
        for va, expected in MAP_LIST_ANCHORS.items():
            broken = map_list_symbols_image()
            off = va_to_offset(broken, va)
            assert off is not None
            broken[off : off + len(expected)] = b"\xcc" * len(expected)
            with pytest.raises(ValueError, match="not the expected build"):
                MapListSymbolsPatch().apply(broken)

    def test_the_anchors_are_what_the_design_rests_on(self) -> None:
        """Named rather than merely listed: the assignment operator the store hook wraps, the
        insert whose ``ret 4`` leaves that hook its argument, the comparator arm that makes the
        key a sort key, and the lookup's NULL-on-a-miss."""
        assert MAP_META_DATA_ASSIGN in MAP_LIST_ANCHORS
        assert 0x00706636 in MAP_LIST_ANCHORS  # MapCache::insert's `ret 4`
        assert MAP_LIST_COMPARE_KEY_BYTES.endswith(bytes.fromhex("2b87f40000008b09"))
        assert OBJECT_IMAGE_UPGRADE_FIND_IMAGE in MAP_LIST_ANCHORS

    def test_a_patched_image_still_passes_its_own_fingerprint(self) -> None:
        assert MapListSymbolsPatch()._anchor_problems(bytes(patched())) == []
