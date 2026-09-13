"""Tests for the draw-module-scale patch.

Four things here can go wrong without raising, so each is read back.

The **stubs** are hand-assembled and stand in for two engine routines: a getter 19 callers rely on
and the transform helper five more do. A stub that leaves a register, the stack or the x87 stack
different from what it replaced breaks a caller while assembling, applying and verifying cleanly,
so each is decoded against the routine it reproduces.

The **storage** is three bytes of padding beside a live `Bool`, holding an index rather than a
value. The allocator has to write exactly those three bytes, hand back the same record the second
time it is asked, and start a record at scale one - otherwise declaring another keyword alone would
collapse the model to nothing.

The **turn** is a sine and a cosine computed while the INI is read, and three rows of four
multiplies while drawing. Both halves are decoded here, because a swapped sine and cosine or a
sign the wrong way round is a rotation that still runs.

And the **site maps** are the claim the patch rests on: every model draw call reaches the stub its
function's registers suit, and none is missed. Against a real binary both maps are pinned to a scan
of the image.
"""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

from sage_ini.model.draw import W3DHordeModelDraw
from sage_patch.addresses import (
    DRAWABLE_GET_SCALE,
    DRAWABLE_GET_SCALE_BYTES,
    DRAWABLE_GET_SCALE_OTHER_CALLS,
    INI_PARSE_BOOL,
    INI_PARSE_COORD3D,
    INI_PARSE_INT,
    INI_PARSE_POSITIVE_REAL,
    INI_PARSE_REAL,
    MATRIX3D_ROW_STRIDE,
    MATRIX3D_TRANSLATION,
    W3D_MODEL_DRAW_BIRTH_FADE_ADDITIVE,
    W3D_MODEL_DRAW_BIRTH_FADE_DEFAULT,
    W3D_MODEL_DRAW_BIRTH_FADE_DEFAULT_BYTES,
    W3D_MODEL_DRAW_DERIVED_TABLE_REFS,
    W3D_MODEL_DRAW_FIELD_TABLE,
    W3D_MODEL_DRAW_FIELD_TABLE_REF,
    W3D_MODEL_DRAW_STATIC_SORT_LEVEL,
    W3D_MODEL_DRAW_TRANSFORM_HELPER,
)
from sage_patch.patches.draw_module_scale import (
    ANCHORS,
    DEFAULT_ANGLE_KEYWORD,
    DEFAULT_KEYWORD,
    DEFAULT_OFFSET_KEYWORD,
    FAMILY_BLOCKS,
    FIELD_OFFSET,
    FIELD_WIDTH,
    LOCATORS,
    RECORD_ANGLE_FLAG,
    RECORD_CAPACITY,
    RECORD_COS,
    RECORD_OFFSET,
    RECORD_SCALE,
    RECORD_SHIFT,
    RECORD_SIN,
    RECORD_SIZE,
    SECTION_NAME,
    SITES,
    TRANSFORM_SITES,
    DrawModuleScalePatch,
    build_code,
    entry_points,
    validate_keywords,
    widened_default,
)
from sage_patch.patches.utils.field_tables import ROW_SIZE, read_field_table
from sage_patch.patches.utils.name_tables import read_cstring
from sage_patch.pe import image_sections
from sage_patch.registry import PATCHES
from sage_patch.utils import find_section, va_to_offset
from tests.sage_patch.synthetic import _sparse_image

#: Where the stand-in keeps its keyword strings: the page the shared table already maps.
STRINGS_VA = 0x00BE1000

#: The stand-in's shared table: enough rows to carry the neighbourhood the patch checks.
STAND_IN_ROWS = (
    ("OkToChangeModelColor", INI_PARSE_BOOL, 0x68),
    ("BirthFadeAdditive", INI_PARSE_BOOL, W3D_MODEL_DRAW_BIRTH_FADE_ADDITIVE),
    ("StaticSortLevelWhileFading", INI_PARSE_INT, W3D_MODEL_DRAW_STATIC_SORT_LEVEL),
)

#: The one table every derived module's `push` names in the stand-in.
DERIVED_TABLE_VA = 0x00BE1C00

#: Addresses to assemble at when only the shape of the code is under test.
CODE_BASE, COUNT_VA, RECORDS_VA = 0x00F00000, 0x00F08000, 0x00F08004

Row = tuple[str, int, int]


def _table(rows: tuple[Row, ...], strings_va: int) -> tuple[bytes, bytes]:
    """``(strings, table)`` for ``rows``, the table's name pointers aimed into ``strings_va``."""
    strings = bytearray()
    table = bytearray()
    for name, parse, offset in rows:
        table += struct.pack("<IIII", strings_va + len(strings), parse, 0, offset)
        strings += name.encode("ascii") + b"\x00"
    return bytes(strings), bytes(table) + bytes(ROW_SIZE)


def stand_in(
    rows: tuple[Row, ...] = STAND_IN_ROWS,
    derived_rows: tuple[Row, ...] = (),
    table_va: int = W3D_MODEL_DRAW_FIELD_TABLE,
) -> bytearray:
    """A sparse image carrying every site the patch asserts, the shared table the reference names
    and one derived table the six derived references share."""
    strings, table = _table(rows, STRINGS_VA)
    derived_strings, derived = _table(derived_rows, STRINGS_VA + len(strings))
    return _sparse_image(
        {
            **ANCHORS,
            STRINGS_VA: strings + derived_strings,
            table_va: table,
            DERIVED_TABLE_VA: derived,
            W3D_MODEL_DRAW_FIELD_TABLE_REF: b"\x68" + struct.pack("<I", table_va),
            **{
                ref: b"\x68" + struct.pack("<I", DERIVED_TABLE_VA)
                for ref in W3D_MODEL_DRAW_DERIVED_TABLE_REFS
            },
        }
    )


@pytest.fixture
def image() -> bytearray:
    return stand_in()


def _read(data: bytes | bytearray, va: int, n: int) -> bytes:
    off = va_to_offset(data, va)
    assert off is not None, f"0x{va:08x} is not mapped"
    return bytes(data[off : off + n])


def _pushed(data: bytes | bytearray, va: int) -> int:
    raw = _read(data, va, 5)
    assert raw[0] == 0x68
    return int(struct.unpack_from("<I", raw, 1)[0])


def _call_target(data: bytes | bytearray, va: int) -> int:
    raw = _read(data, va, 5)
    assert raw[0] == 0xE8, f"0x{va:08x} is not a call"
    return va + 5 + int(struct.unpack_from("<i", raw, 1)[0])


def _cave(data: bytes | bytearray) -> tuple[int, int, int]:
    """``(code, counter, records)`` in a patched image, from the table its reference names."""
    table_va = _pushed(data, W3D_MODEL_DRAW_FIELD_TABLE_REF)
    code_va = table_va + (len(read_field_table(data, table_va)) + 1) * ROW_SIZE
    after = code_va + len(build_code(code_va, 0, 0))
    count_va = after + (-after % 4)
    return code_va, count_va, count_va + 4


def _routines(data: bytes | bytearray) -> dict[str, int]:
    return entry_points(*_cave(data))


def _shape() -> tuple[bytes, dict[str, int]]:
    """The code and its entry points at the addresses shape tests assemble at."""
    where = (CODE_BASE, COUNT_VA, RECORDS_VA)
    return build_code(*where), entry_points(*where)


def test_the_index_is_exactly_the_padding() -> None:
    assert FIELD_OFFSET == W3D_MODEL_DRAW_BIRTH_FADE_ADDITIVE + 1
    assert FIELD_OFFSET + FIELD_WIDTH == W3D_MODEL_DRAW_STATIC_SORT_LEVEL
    assert FIELD_WIDTH == 3
    assert RECORD_CAPACITY < (1 << (8 * FIELD_WIDTH))  # the index has to be able to name them all


def test_the_record_holds_all_three_fields_without_overlapping() -> None:
    assert RECORD_SIZE == 1 << RECORD_SHIFT  # an index becomes an address with a shift
    spans = [
        (RECORD_SCALE, 4),
        (RECORD_OFFSET, 12),
        (RECORD_ANGLE_FLAG, 4),
        (RECORD_COS, 4),
        (RECORD_SIN, 4),
    ]
    ends = [start + size for start, size in spans]
    starts = [start for start, _size in spans]
    assert starts == sorted(starts)
    assert all(end <= nxt for end, nxt in zip(ends, starts[1:], strict=False))
    assert max(ends) <= RECORD_SIZE


def test_the_site_maps_cover_the_family_and_nothing_else() -> None:
    assert len(SITES) == 19
    assert set(SITES.values()) == set(LOCATORS)
    assert not set(SITES) & set(DRAWABLE_GET_SCALE_OTHER_CALLS)
    assert len(TRANSFORM_SITES) == 5
    assert not set(TRANSFORM_SITES) & set(SITES)


def test_the_default_store_only_widens() -> None:
    stock = W3D_MODEL_DRAW_BIRTH_FADE_DEFAULT_BYTES
    assert stock[0] == 0x88 and widened_default() == b"\x89" + stock[1:]


@pytest.mark.parametrize("locator", list(LOCATORS))
def test_a_scale_stub_is_the_getter_then_the_factor(locator: str) -> None:
    """Decode a stub by hand: the getter's own `fld`, a save, the load, the test, and on the
    declared path one `fmul` straight out of the record."""
    code, entries = _shape()
    at = entries[locator] - CODE_BASE

    fld = DRAWABLE_GET_SCALE_BYTES[:-1]
    assert code[at : at + len(fld)] == fld
    at += len(fld)
    assert code[at] == 0x50  # push eax
    at += 1
    load = LOCATORS[locator]
    assert code[at : at + len(load)] == load
    at += len(load)
    assert code[at : at + 2] == bytes((0x8B, 0x80))  # mov eax, [eax+disp32]
    assert struct.unpack_from("<I", code, at + 2)[0] == W3D_MODEL_DRAW_BIRTH_FADE_ADDITIVE
    at += 6
    assert code[at : at + 3] == bytes((0xC1, 0xE8, 8))  # shr eax, 8
    at += 3
    assert code[at] == 0x74  # je rel8
    unset = at + 2 + code[at + 1]
    at += 2

    assert code[at : at + 3] == bytes((0xC1, 0xE0, RECORD_SHIFT))  # shl eax, 5
    assert code[at + 3 : at + 5] == bytes((0xD8, 0x88))  # fmul dword [eax+disp32]
    assert struct.unpack_from("<I", code, at + 5)[0] == RECORDS_VA - RECORD_SIZE + RECORD_SCALE
    assert at + 9 == unset
    assert code[unset : unset + 2] == b"\x58\xc3"  # pop eax; ret


def test_the_transform_stub_runs_the_helper_then_moves_and_turns_the_matrix() -> None:
    """The helper is `__thiscall(Matrix3D *)` with `ret 4`, so the stub has to hand it the same
    argument the call site pushed, keep `ecx`, and clean those four bytes itself on the way out."""
    code, entries = _shape()
    at = entries["transform"] - CODE_BASE

    assert code[at : at + 2] == b"\x56\x57"  # push esi; push edi - callee-saved, so they survive
    assert code[at + 2 : at + 6] == bytes.fromhex("8b74240c")  # mov esi, [esp+0xc]  the matrix
    assert code[at + 6 : at + 8] == bytes.fromhex("8bf9")  # mov edi, ecx        the module
    assert code[at + 8] == 0x56  # push esi            the helper's argument
    assert code[at + 9] == 0xE8
    assert CODE_BASE + at + 14 + struct.unpack_from("<i", code, at + 10)[0] == (
        W3D_MODEL_DRAW_TRANSFORM_HELPER
    )
    assert code[at + 14 : at + 17] == bytes.fromhex("8b4704")  # mov eax, [edi+4]

    # the turn is asked for after the offset, skipped unless the record says it is there, and the
    # two scratch dwords it borrows are given back before the stub returns
    gate = bytes((0x83, 0x78, RECORD_ANGLE_FLAG, 0x00))  # cmp dword [eax+0x10], 0
    assert gate in code
    end = entries[next(iter(LOCATORS))] - CODE_BASE
    assert code[code.index(gate) : end].count(bytes.fromhex("83ec08")) == 1  # sub esp, 8
    assert code[code.index(gate) : end].count(bytes.fromhex("83c408")) == 1  # add esp, 8
    assert code[end - 3 : end] == bytes.fromhex("c20400")  # ret 4, as the helper does


def test_the_transform_stub_adds_the_rotated_offset_to_every_row() -> None:
    """Each row multiplies the offset by that row of the rotation and adds it to that row's
    translation - which is what makes the offset turn with the object instead of pointing north."""
    code, _entries = _shape()
    for row in range(3):
        rot = row * MATRIX3D_ROW_STRIDE
        translation = rot + MATRIX3D_TRANSLATION
        expected = (
            bytes((0xD9, 0x40, RECORD_OFFSET))  # fld dword [eax+4]
            + bytes((0xD8, 0x4E, rot))  # fmul dword [esi+rot]
            + bytes((0xD9, 0x40, RECORD_OFFSET + 4))  # fld dword [eax+8]
            + bytes((0xD8, 0x4E, rot + 4))  # fmul dword [esi+rot+4]
            + bytes((0xDE, 0xC1))  # faddp st(1), st
            + bytes((0xD9, 0x40, RECORD_OFFSET + 8))  # fld dword [eax+0xc]
            + bytes((0xD8, 0x4E, rot + 8))  # fmul dword [esi+rot+8]
            + bytes((0xDE, 0xC1))  # faddp st(1), st
            + bytes((0xD8, 0x46, translation))  # fadd dword [esi+t]
            + bytes((0xD9, 0x5E, translation))  # fstp dword [esi+t]
        )
        assert expected in code, f"row {row}"


def test_the_turn_rewrites_two_columns_and_leaves_the_third() -> None:
    """`(x, y) -> (x*cos + y*sin, y*cos - x*sin)` per row, out of scratch copies because both
    answers read both originals - and the row's third entry, the one a turn about the up axis does
    not touch, is never written."""
    code, _entries = _shape()
    for row in range(3):
        base = row * MATRIX3D_ROW_STRIDE
        expected = (
            bytes((0xD9, 0x46, base))  # fld dword [esi+row]
            + b"\xd9\x1c\x24"  # fstp dword [esp]      x
            + bytes((0xD9, 0x46, base + 4))  # fld dword [esi+row+4]
            + b"\xd9\x5c\x24\x04"  # fstp dword [esp+4]    y
            + b"\xd9\x04\x24"  # fld dword [esp]
            + bytes((0xD8, 0x48, RECORD_COS))  # fmul dword [eax+cos]
            + b"\xd9\x44\x24\x04"  # fld dword [esp+4]
            + bytes((0xD8, 0x48, RECORD_SIN))  # fmul dword [eax+sin]
            + b"\xde\xc1"  # faddp st(1), st
            + bytes((0xD9, 0x5E, base))  # fstp dword [esi+row]
            + b"\xd9\x44\x24\x04"  # fld dword [esp+4]
            + bytes((0xD8, 0x48, RECORD_COS))  # fmul dword [eax+cos]
            + b"\xd9\x04\x24"  # fld dword [esp]
            + bytes((0xD8, 0x48, RECORD_SIN))  # fmul dword [eax+sin]
            + b"\xde\xe9"  # fsubp st(1), st
            + bytes((0xD9, 0x5E, base + 4))  # fstp dword [esi+row+4]
        )
        assert expected in code, f"row {row}"
        assert bytes((0xD9, 0x5E, base + 8)) not in code  # the third entry is never stored


@pytest.mark.parametrize(
    ("routine", "parser", "slot"),
    [
        ("parse_scale", INI_PARSE_POSITIVE_REAL, 4),
        ("parse_offset", INI_PARSE_COORD3D, 0xC),
        ("parse_angle", INI_PARSE_REAL, 4),
    ],
)
def test_a_parser_hands_the_engine_parser_the_callers_arguments(
    routine: str, parser: int, slot: int
) -> None:
    """After the slot is reserved the caller's four arguments sit one slot further out, and each
    push moves them four further again - which is what makes the same `push [esp+N]` name userData,
    then (after the slot) instance, then the INI."""
    code, entries = _shape()
    at = entries[routine] - CODE_BASE
    outer = slot + 0x10  # the caller's first argument, once the slot and four pushes are counted

    assert code[at : at + 3] == bytes((0x83, 0xEC, slot))  # sub esp, slot
    assert code[at + 3 : at + 5] == bytes.fromhex("8bc4")  # mov eax, esp
    push_outer = bytes((0xFF, 0x74, 0x24, outer))
    assert code[at + 5 : at + 9] == push_outer  # userData
    assert code[at + 9] == 0x50  # the slot, as store
    assert code[at + 10 : at + 18] == push_outer * 2  # instance, then the INI
    assert code[at + 18] == 0xE8
    assert CODE_BASE + at + 23 + struct.unpack_from("<i", code, at + 19)[0] == parser
    assert code[at + 23 : at + 26] == bytes.fromhex("83c410")  # add esp, 0x10


def test_the_angle_is_the_plain_real_parser_not_the_positive_one() -> None:
    """A negative angle turns the other way and zero is a legitimate "no turn", so the parser that
    throws on anything but a positive value would be the wrong one."""
    code, entries = _shape()
    at = entries["parse_angle"] - CODE_BASE
    window = code[at : entries["transform"] - CODE_BASE]
    targets = set()
    found = window.find(b"\xe8")
    while found >= 0:
        targets.add(CODE_BASE + at + found + 5 + struct.unpack_from("<i", window, found + 1)[0])
        found = window.find(b"\xe8", found + 1)
    assert INI_PARSE_REAL in targets
    assert INI_PARSE_POSITIVE_REAL not in targets


@pytest.mark.parametrize("routine", ["parse_scale", "parse_offset", "parse_angle"])
def test_the_parsers_reach_the_record_through_the_allocator(routine: str) -> None:
    """No parser may write anywhere but a record: the index is the only thing in the `ModuleData`,
    and whichever keyword parses first is what allocates."""
    code, entries = _shape()
    at = entries[routine] - CODE_BASE
    window = code[at : at + 0x60]
    store = window.index(bytes.fromhex("83c410")) + 3  # right after the cdecl clean-up
    assert window[store : store + 3] == bytes.fromhex("ff7424")  # push [esp+N] - the row's store
    call = store + 4
    assert window[call] == 0xE8
    target = CODE_BASE + at + call + 5 + struct.unpack_from("<i", window, call + 1)[0]
    assert target == entries["record"]


def test_the_angle_parser_computes_its_sine_and_cosine_once() -> None:
    """Degrees to radians, one `fsincos`, and the two results into the record - so drawing costs no
    trigonometry. `fsincos` leaves cos above sin, which is the order the stores come out in."""
    code, entries = _shape()
    at = entries["parse_angle"] - CODE_BASE
    window = code[at : entries["transform"] - CODE_BASE]

    convert = (
        b"\xd9\x04\x24"  # fld dword [esp]    the angle, in degrees
        + b"\xd9\xeb"  # fldpi
        + b"\xde\xc9"  # fmulp st(1), st
        + bytes((0x68, *struct.pack("<I", 180)))  # push 180
        + b"\xda\x34\x24"  # fidiv dword [esp]
        + b"\x59"  # pop ecx
        + b"\xd9\xfb"  # fsincos
        + bytes((0xD9, 0x58, RECORD_COS))  # fstp dword [eax+0x14]  cos
        + bytes((0xD9, 0x58, RECORD_SIN))  # fstp dword [eax+0x18]  sin
    )
    assert convert in window
    flag = bytes((0xC7, 0x40, RECORD_ANGLE_FLAG, *struct.pack("<I", 1)))
    assert flag in window  # mov dword [eax+0x10], 1
    assert window.index(flag) > window.index(convert)
    assert window.count(b"\xd9\xfb") == 1  # one fsincos, not one per frame


def test_code_is_position_independent() -> None:
    """Built at two addresses with the same data behind it, only the `call rel32`s differ."""
    a = build_code(CODE_BASE, COUNT_VA, RECORDS_VA)
    b = build_code(CODE_BASE + 0x1000, COUNT_VA, RECORDS_VA)
    assert len(a) == len(b)
    assert sum(x != y for x, y in zip(a, b, strict=True)) <= 4 * 4  # the four absolute calls


def test_apply_sends_every_site_to_its_stub(image: bytearray) -> None:
    DrawModuleScalePatch().apply(image)
    located = find_section(image, SECTION_NAME)
    assert located is not None
    base_va, _off, vsize = located
    code_va, count_va, records_va = _cave(image)
    routines = entry_points(code_va, count_va, records_va)

    for site, locator in SITES.items():
        assert _call_target(image, site) == routines[locator], f"0x{site:08x}"
    for site in TRANSFORM_SITES:
        assert _call_target(image, site) == routines["transform"], f"0x{site:08x}"

    want = build_code(code_va, count_va, records_va)
    assert _read(image, code_va, len(want)) == want
    assert base_va <= code_va < records_va + RECORD_SIZE * RECORD_CAPACITY <= base_va + vsize


def test_apply_widens_the_default_store(image: bytearray) -> None:
    DrawModuleScalePatch().apply(image)
    assert _read(image, W3D_MODEL_DRAW_BIRTH_FADE_DEFAULT, 6) == widened_default()


def test_apply_rebuilds_the_table_with_three_rows(image: bytearray) -> None:
    patch = DrawModuleScalePatch(
        keyword="ModelScale", offset_keyword="ModelOffset", angle_keyword="ModelAngle"
    )
    patch.apply(image)
    table_va = _pushed(image, W3D_MODEL_DRAW_FIELD_TABLE_REF)
    assert table_va != W3D_MODEL_DRAW_FIELD_TABLE

    rows = read_field_table(image, table_va)
    assert rows[:-3] == read_field_table(image, W3D_MODEL_DRAW_FIELD_TABLE)
    routines = _routines(image)
    expected = (
        ("ModelScale", "parse_scale"),
        ("ModelOffset", "parse_offset"),
        ("ModelAngle", "parse_angle"),
    )
    for row, (keyword, routine) in zip(rows[-3:], expected, strict=True):
        name_va, parse, user, offset = row
        assert read_cstring(image, name_va) == keyword
        assert (parse, user, offset) == (routines[routine], 0, FIELD_OFFSET)


def test_apply_leaves_the_counter_and_records_zeroed(image: bytearray) -> None:
    """They are runtime state: a patched file on disk has allocated nothing."""
    DrawModuleScalePatch().apply(image)
    _code_va, count_va, records_va = _cave(image)
    assert _read(image, count_va, 4) == bytes(4)
    assert _read(image, records_va, RECORD_SIZE * RECORD_CAPACITY) == bytes(
        RECORD_SIZE * RECORD_CAPACITY
    )


def test_apply_keeps_the_rows_of_a_table_moved_before_it() -> None:
    """A patch that extended the table first left the reference pointing somewhere else, with a
    row of its own. Appending to what is live keeps that row; the stock address would drop it."""
    rows = (*STAND_IN_ROWS, ("SomeoneElsesField", INI_PARSE_BOOL, 0x190))
    moved = stand_in(rows=rows, table_va=0x00BE1800)
    patch = DrawModuleScalePatch()
    patch.apply(moved)
    live = read_field_table(moved, _pushed(moved, W3D_MODEL_DRAW_FIELD_TABLE_REF))
    names = [read_cstring(moved, row[0]) for row in live]
    assert names == [
        *(name for name, *_ in rows),
        DEFAULT_KEYWORD,
        DEFAULT_OFFSET_KEYWORD,
        DEFAULT_ANGLE_KEYWORD,
    ]
    assert patch.verify(moved) == []


@pytest.mark.parametrize("keyword", ["BirthFadeAdditive", "birthfadeadditive"])
def test_apply_refuses_a_keyword_the_shared_table_parses(keyword: str) -> None:
    with pytest.raises(ValueError, match="already parses"):
        DrawModuleScalePatch(keyword=keyword).apply(stand_in())


@pytest.mark.parametrize("keyword", [DEFAULT_OFFSET_KEYWORD, DEFAULT_ANGLE_KEYWORD])
def test_apply_refuses_a_keyword_a_derived_table_parses(keyword: str) -> None:
    image = stand_in(derived_rows=((keyword, INI_PARSE_BOOL, 0x190),))
    with pytest.raises(ValueError, match="already parses"):
        DrawModuleScalePatch().apply(image)


def test_apply_refuses_a_table_without_the_bool_the_padding_follows() -> None:
    rows = tuple(row for row in STAND_IN_ROWS if row[0] != "BirthFadeAdditive")
    with pytest.raises(ValueError, match="BirthFadeAdditive"):
        DrawModuleScalePatch().apply(stand_in(rows=rows))


def test_apply_refuses_a_table_that_already_stores_into_the_padding() -> None:
    rows = (*STAND_IN_ROWS, ("Squatter", INI_PARSE_BOOL, FIELD_OFFSET + 1))
    with pytest.raises(ValueError, match="padding"):
        DrawModuleScalePatch().apply(stand_in(rows=rows))


@pytest.mark.parametrize("va", list(ANCHORS))
def test_apply_refuses_a_build_whose_site_differs(image: bytearray, va: int) -> None:
    off = va_to_offset(image, va)
    assert off is not None
    image[off] ^= 0xFF
    with pytest.raises(ValueError):
        DrawModuleScalePatch().apply(image)


def test_apply_refuses_to_run_twice(image: bytearray) -> None:
    DrawModuleScalePatch().apply(image)
    with pytest.raises(ValueError):
        DrawModuleScalePatch().apply(image)


def test_verify_clean_after_apply(image: bytearray) -> None:
    patch = DrawModuleScalePatch()
    patch.apply(image)
    assert patch.verify(image) == []


def test_verify_clean_for_custom_keywords(image: bytearray) -> None:
    patch = DrawModuleScalePatch(
        keyword="ModelScale", offset_keyword="ModelOffset", angle_keyword="ModelAngle"
    )
    patch.apply(image)
    assert patch.verify(image) == []


def test_verify_survives_records_a_game_has_written(image: bytearray) -> None:
    """The records and their counter are written while a game reads its INI, so a binary that has
    been run still verifies - only what the patch lays down is compared."""
    patch = DrawModuleScalePatch()
    patch.apply(image)
    _code_va, count_va, records_va = _cave(image)
    off = va_to_offset(image, count_va)
    assert off is not None
    image[off : off + 4] = struct.pack("<I", 7)
    off = va_to_offset(image, records_va)
    assert off is not None
    image[off : off + 4] = struct.pack("<f", 2.5)
    assert patch.verify(image) == []


def test_verify_rejects_an_unpatched_image(image: bytearray) -> None:
    assert DrawModuleScalePatch().verify(image) != []


def test_verify_rejects_the_wrong_keywords(image: bytearray) -> None:
    DrawModuleScalePatch(angle_keyword="ModelAngle").apply(image)
    assert DrawModuleScalePatch().verify(image) != []


@pytest.mark.parametrize(
    "va",
    [
        W3D_MODEL_DRAW_BIRTH_FADE_DEFAULT,
        W3D_MODEL_DRAW_FIELD_TABLE_REF,
        *SITES,
        *TRANSFORM_SITES,
    ],
)
def test_verify_catches_a_reverted_site(image: bytearray, va: int) -> None:
    patch = DrawModuleScalePatch()
    patch.apply(image)
    stock = ANCHORS.get(va) or b"\x68" + struct.pack("<I", W3D_MODEL_DRAW_FIELD_TABLE)
    off = va_to_offset(image, va)
    assert off is not None
    image[off : off + len(stock)] = stock
    assert patch.verify(image) != []


def test_detect_recovers_all_three_keywords(image: bytearray) -> None:
    DrawModuleScalePatch(
        keyword="ModelScale", offset_keyword="ModelOffset", angle_keyword="ModelAngle"
    ).apply(image)
    found = DrawModuleScalePatch.detect(image)
    assert found is not None
    assert (found.keyword, found.offset_keyword, found.angle_keyword) == (
        "ModelScale",
        "ModelOffset",
        "ModelAngle",
    )


def test_detect_finds_nothing_in_a_clean_image(image: bytearray) -> None:
    assert DrawModuleScalePatch.detect(image) is None


@pytest.mark.parametrize("keyword", ["", "1Scale", "Model Scale", "Model-Scale"])
def test_validate_keywords_rejects_what_the_reader_could_never_match(keyword: str) -> None:
    with pytest.raises(ValueError):
        validate_keywords(keyword, DEFAULT_OFFSET_KEYWORD, DEFAULT_ANGLE_KEYWORD)


def test_validate_keywords_rejects_one_name_used_twice() -> None:
    with pytest.raises(ValueError, match="must differ"):
        validate_keywords("Scale", "scale", DEFAULT_ANGLE_KEYWORD)


def test_ini_surface_lands_on_every_model_draw_block() -> None:
    surface = DrawModuleScalePatch(
        keyword="ModelScale", offset_keyword="ModelOffset", angle_keyword="ModelAngle"
    ).ini_surface()
    assert {field.block for field in surface.fields} == set(FAMILY_BLOCKS)
    assert {(f.name, f.type, f.default) for f in surface.fields} == {
        ("ModelScale", "Float", 1.0),
        ("ModelOffset", "Coords", None),
        ("ModelAngle", "Float", 0.0),
    }
    with surface.activate() as problems:
        assert problems == []
        # the horde block has no delta of its own: it inherits the scripted one's, as in the engine
        for name in ("ModelScale", "ModelOffset", "ModelAngle"):
            assert name in W3DHordeModelDraw._fieldspec


def test_it_is_registered_and_not_experimental() -> None:
    assert PATCHES[DrawModuleScalePatch.name] is DrawModuleScalePatch
    assert DrawModuleScalePatch.experimental is False


#: Both copies a checkout can hold; neither is committed, so each check skips when its file is
#: absent. Only the clean backup says a site is stock rather than merely unpatched by this package.
_BINARIES = {
    "repo": Path(__file__).resolve().parents[2] / "game.dat",
    "clean": Path(__file__).resolve().parents[2] / "sage_patch" / "engine" / "game.dat.backup",
}


def _calls_to(data: bytes, target: int) -> set[int]:
    """Every `call rel32` in `.text` that lands on ``target``. A byte scan over-reports rather than
    under-reports, so equality with a known set means none is missing."""
    text = next(section for section in image_sections(data) if section.name == ".text")
    code = data[text.raw_offset : text.raw_offset + text.raw_size]
    found = set()
    at = code.find(b"\xe8")
    while 0 <= at <= len(code) - 5:
        va = text.virtual_address + at
        if va + 5 + struct.unpack_from("<i", code, at + 1)[0] == target:
            found.add(va)
        at = code.find(b"\xe8", at + 1)
    return found


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
            assert _read(stock, va, len(expected)) == expected, f"0x{va:08x}"

    def test_every_get_scale_call_is_a_site_or_a_known_outsider(self, which: str) -> None:
        found = _calls_to(self._stock(which), DRAWABLE_GET_SCALE)
        assert found == set(SITES) | set(DRAWABLE_GET_SCALE_OTHER_CALLS)

    def test_every_transform_helper_call_is_hooked(self, which: str) -> None:
        """The offset and the turn reach every place the family positions what it draws only if the
        helper has no caller this patch leaves alone."""
        found = _calls_to(self._stock(which), W3D_MODEL_DRAW_TRANSFORM_HELPER)
        assert found == set(TRANSFORM_SITES)

    def test_the_table_has_the_neighbourhood_the_padding_depends_on(self, which: str) -> None:
        stock = self._stock(which)
        rows = read_field_table(stock, W3D_MODEL_DRAW_FIELD_TABLE)
        assert len(rows) == 57
        by_name = {read_cstring(stock, row[0]): row for row in rows}
        assert by_name["BirthFadeAdditive"][1:] == (
            INI_PARSE_BOOL,
            0,
            W3D_MODEL_DRAW_BIRTH_FADE_ADDITIVE,
        )
        assert by_name["StaticSortLevelWhileFading"][3] == W3D_MODEL_DRAW_STATIC_SORT_LEVEL
        assert not any(FIELD_OFFSET <= row[3] < FIELD_OFFSET + FIELD_WIDTH for row in rows)

    def test_no_keyword_is_already_a_model_draw_field(self, which: str) -> None:
        """`Scale`, `Offset` and `AngleOffset` are ordinary words: the point is that no table a
        model draw's reader searches spells any of them today."""
        stock = self._stock(which)
        names = set()
        for ref in (W3D_MODEL_DRAW_FIELD_TABLE_REF, *W3D_MODEL_DRAW_DERIVED_TABLE_REFS):
            table_va = struct.unpack_from("<I", _read(stock, ref, 5), 1)[0]
            names |= {
                (read_cstring(stock, row[0]) or "").lower()
                for row in read_field_table(stock, table_va)
            }
        for keyword in (DEFAULT_KEYWORD, DEFAULT_OFFSET_KEYWORD, DEFAULT_ANGLE_KEYWORD):
            assert keyword.lower() not in names

    def test_apply_verify_detect_round_trip(self, which: str) -> None:
        data = bytearray(self._stock(which))
        patch = DrawModuleScalePatch()
        patch.apply(data)
        assert patch.verify(data) == []
        found = DrawModuleScalePatch.detect(data)
        assert isinstance(found, DrawModuleScalePatch)
        assert (found.keyword, found.offset_keyword, found.angle_keyword) == (
            DEFAULT_KEYWORD,
            DEFAULT_OFFSET_KEYWORD,
            DEFAULT_ANGLE_KEYWORD,
        )
