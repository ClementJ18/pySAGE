"""Tests for the hide-modifier-fx patch.

The structural half is the usual one: the four hooks and the five table references land where
they should, `verify`/`detect` round-trip, and a second application refuses. The emulated half
runs the cave's routines under unicorn against a stand-in engine, because what the patch rests on
is behaviour the bytes cannot show:

* the gate plays the FX for an unflagged template and swallows it for a flagged one, keeping the
  cdecl contract so the caller's own `add esp, 0xC` still balances;
* the parse function files the value against the *template's id*, not inside the template;
* the identity-keeping copy hands the source's flag to the destination's own id; and
* the id swap leaves the displaced template its flag and the newcomer a clean slot.
"""

from __future__ import annotations

import struct

import pytest

from sage_patch import HideModifierFxPatch
from sage_patch.addresses import (
    FIELD_PARSE_STRIDE,
    FX_LIST_PLAY_AT_OBJECT,
    INI_PARSE_BOOL,
    MODIFIER_HOLDER_APPLY_FX_CALLS,
    OBJECT_FIELD_TABLE,
    OBJECT_FIELD_TABLE_REF_OPCODES,
    OBJECT_FIELD_TABLE_REFS,
    THING_FACTORY_ID_SWAP,
    THING_FACTORY_ID_SWAP_BYTES,
    THING_FACTORY_ID_SWAP_RESUME,
    THING_TEMPLATE_COPY_KEEP_ID,
    THING_TEMPLATE_COPY_KEEP_ID_BYTES,
    THING_TEMPLATE_COPY_KEEP_ID_RESUME,
    THING_TEMPLATE_ID,
    THING_TEMPLATE_ID_COUNTER,
)
from sage_patch.patches.hide_modifier_fx import (
    DEFAULT_KEYWORD,
    FINGERPRINT,
    ID_TABLE_SIZE,
    SECTION_NAME,
    build_code,
    build_table,
)
from sage_patch.registry import PATCHES
from sage_patch.utils import call_rel32, find_section, va_to_offset
from tests.sage_patch.test_terrain_resource_exp import _pe32

IMAGE_BASE = 0x400000

#: Where the synthetic image parks the field names, past every site the patch touches.
STRINGS_VA = 0x00DB0000

#: A stand-in `Object` table: the fingerprint rows plus a couple of ordinary ones.
STOCK_FIELDS: tuple[tuple[str, int], ...] = (
    ("DisplayName", 0x78),
    *FINGERPRINT.items(),
    ("EditorSorting", 0x2A8),
)


def _string_vas() -> dict[str, int]:
    vas, cursor = {}, STRINGS_VA
    for name, _offset in STOCK_FIELDS:
        vas[name] = cursor
        cursor += len(name) + 1
    return vas


def plant_sites(data: bytearray) -> None:
    """The clean bytes this patch asserts before writing, plus the stock keyword strings."""

    def at(va: int) -> int:
        return va - IMAGE_BASE

    vas = _string_vas()
    for name, va in vas.items():
        blob = name.encode("ascii") + b"\x00"
        data[at(va) : at(va) + len(blob)] = blob

    table = at(OBJECT_FIELD_TABLE)
    for index, (name, offset) in enumerate(STOCK_FIELDS):
        struct.pack_into(
            "<IIII", data, table + index * FIELD_PARSE_STRIDE, vas[name], INI_PARSE_BOOL, 0, offset
        )
    struct.pack_into("<IIII", data, table + len(STOCK_FIELDS) * FIELD_PARSE_STRIDE, 0, 0, 0, 0)

    for ref_va, opcode in zip(OBJECT_FIELD_TABLE_REFS, OBJECT_FIELD_TABLE_REF_OPCODES, strict=True):
        data[at(ref_va)] = opcode
        struct.pack_into("<I", data, at(ref_va) + 1, OBJECT_FIELD_TABLE)

    for site in MODIFIER_HOLDER_APPLY_FX_CALLS:
        data[at(site) : at(site) + 5] = call_rel32(site, FX_LIST_PLAY_AT_OBJECT)
    for va, window in (
        (THING_TEMPLATE_COPY_KEEP_ID, THING_TEMPLATE_COPY_KEEP_ID_BYTES),
        (THING_FACTORY_ID_SWAP, THING_FACTORY_ID_SWAP_BYTES),
    ):
        data[at(va) : at(va) + len(window)] = window


def synthetic_image() -> bytearray:
    highest = max(
        STRINGS_VA + sum(len(name) + 1 for name, _ in STOCK_FIELDS),
        OBJECT_FIELD_TABLE + (len(STOCK_FIELDS) + 1) * FIELD_PARSE_STRIDE,
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


def _table_va(data: bytes | bytearray) -> int:
    push = _read(data, OBJECT_FIELD_TABLE_REFS[1], 5)
    assert push[0] == 0x68
    return struct.unpack_from("<I", push, 1)[0]


# The rebuilt table


def test_table_keeps_the_live_rows_and_appends_one_row_with_its_own_parser() -> None:
    vas = _string_vas()
    entries = tuple((vas[name], INI_PARSE_BOOL, 0, offset) for name, offset in STOCK_FIELDS)
    table = build_table(entries, 0x00F00000, 0x00F00100)
    for index, entry in enumerate(entries):
        assert struct.unpack_from("<IIII", table, index * FIELD_PARSE_STRIDE) == entry
    row = struct.unpack_from("<IIII", table, len(entries) * FIELD_PARSE_STRIDE)
    assert row == (0x00F00000, 0x00F00100, 0, 0)  # offset 0: nothing lands in the template
    assert table[-FIELD_PARSE_STRIDE:] == bytes(FIELD_PARSE_STRIDE)


# Apply / verify / detect


def test_apply_hooks_all_four_sites(image: bytearray) -> None:
    HideModifierFxPatch().apply(image)
    base_va = find_section(image, SECTION_NAME)[0]
    for site in MODIFIER_HOLDER_APPLY_FX_CALLS:
        got = _read(image, site, 5)
        assert got[0] == 0xE8
        assert site + 5 + struct.unpack_from("<i", got, 1)[0] > base_va  # into the cave
    for site, width in (
        (THING_TEMPLATE_COPY_KEEP_ID, len(THING_TEMPLATE_COPY_KEEP_ID_BYTES)),
        (THING_FACTORY_ID_SWAP, len(THING_FACTORY_ID_SWAP_BYTES)),
    ):
        got = _read(image, site, width)
        assert got[0] == 0xE9
        assert got[5:] == b"\x90" * (width - 5)


def test_apply_repoints_every_table_reference_and_leaves_the_stock_table(
    image: bytearray,
) -> None:
    stock = _read(image, OBJECT_FIELD_TABLE, (len(STOCK_FIELDS) + 1) * FIELD_PARSE_STRIDE)
    HideModifierFxPatch().apply(image)
    table_va = _table_va(image)
    assert table_va != OBJECT_FIELD_TABLE
    for ref_va, opcode in zip(OBJECT_FIELD_TABLE_REFS, OBJECT_FIELD_TABLE_REF_OPCODES, strict=True):
        assert _read(image, ref_va, 5) == bytes([opcode]) + struct.pack("<I", table_va)
    assert _read(image, OBJECT_FIELD_TABLE, len(stock)) == stock


def test_the_id_table_starts_clear_and_the_keyword_follows_it(image: bytearray) -> None:
    HideModifierFxPatch().apply(image)
    base_va = find_section(image, SECTION_NAME)[0]
    assert _read(image, base_va, ID_TABLE_SIZE) == bytes(ID_TABLE_SIZE)
    keyword = DEFAULT_KEYWORD.encode() + b"\x00"
    assert _read(image, base_va + ID_TABLE_SIZE, len(keyword)) == keyword


def test_verify_and_detect_round_trip(image: bytearray) -> None:
    patch = HideModifierFxPatch("NoLeadershipGlow")
    assert patch.verify(image) != []
    assert HideModifierFxPatch.detect(image) is None
    patch.apply(image)
    assert patch.verify(image) == []
    found = HideModifierFxPatch.detect(image)
    assert found is not None and found.keyword == "NoLeadershipGlow"
    assert HideModifierFxPatch().verify(image) != []  # the wrong keyword


@pytest.mark.parametrize(
    "va", [*MODIFIER_HOLDER_APPLY_FX_CALLS, THING_TEMPLATE_COPY_KEEP_ID, THING_FACTORY_ID_SWAP]
)
def test_verify_catches_a_reverted_site(image: bytearray, va: int) -> None:
    clean = synthetic_image()
    HideModifierFxPatch().apply(image)
    off = va - IMAGE_BASE
    image[off : off + 5] = clean[off : off + 5]
    assert HideModifierFxPatch().verify(image) != []


def test_apply_refuses_a_second_time(image: bytearray) -> None:
    HideModifierFxPatch().apply(image)
    with pytest.raises(ValueError):
        HideModifierFxPatch().apply(image)


def test_apply_refuses_when_the_table_is_not_this_build(image: bytearray) -> None:
    row = OBJECT_FIELD_TABLE - IMAGE_BASE + FIELD_PARSE_STRIDE  # BuildCost
    struct.pack_into("<I", image, row + 12, 0x5EE)
    with pytest.raises(ValueError, match="unexpected build"):
        HideModifierFxPatch().apply(image)


def test_ini_surface_is_one_object_bool(image: bytearray) -> None:
    (field,) = HideModifierFxPatch().ini_surface().fields
    assert (field.block, field.name, field.type) == ("Object", DEFAULT_KEYWORD, "Bool")


def test_registered_under_its_name() -> None:
    assert PATCHES[HideModifierFxPatch.name] is HideModifierFxPatch


# The routines, executed

unicorn = pytest.importorskip("unicorn", reason="the emulator harness needs unicorn")

from unicorn import UC_ARCH_X86, UC_MODE_32, Uc  # noqa: E402
from unicorn.x86_const import (  # noqa: E402
    UC_X86_REG_EAX,
    UC_X86_REG_EBX,
    UC_X86_REG_ESI,
    UC_X86_REG_ESP,
)

CODE = 0x00F00000
IDS = 0x00F10000
HEAP = 0x10000000
STACK = 0x20000000
RETURN = 0x30000000
PAGE = 0x1000

#: Where the stubs record what the engine would have seen.
FX_PLAYED = HEAP + 0x800
BOOL_TOKEN = HEAP + 0x804


class Engine:
    """The cave's code, an id table, and stubs for the two engine functions it calls."""

    def __init__(self) -> None:
        self.uc = Uc(UC_ARCH_X86, UC_MODE_32)
        self.asm = build_code(CODE, IDS)
        code = self.asm.finish()
        self.uc.mem_map(CODE, 0x1000)
        self.uc.mem_write(CODE, code)
        self.uc.mem_map(IDS, ID_TABLE_SIZE)
        self.uc.mem_map(HEAP, 0x10000)
        self.uc.mem_map(STACK, 0x10000)
        self.uc.mem_map(RETURN, PAGE)
        self.uc.mem_map(THING_TEMPLATE_ID_COUNTER & ~0xFFF, PAGE)
        for va in {
            FX_LIST_PLAY_AT_OBJECT,
            INI_PARSE_BOOL,
            THING_TEMPLATE_COPY_KEEP_ID_RESUME,
            THING_FACTORY_ID_SWAP_RESUME,
        }:
            try:
                self.uc.mem_map(va & ~0xFFF, PAGE)
            except unicorn.UcError:
                pass  # two sites share a page
        # FX: count the play, return. Bool: store the token cell through `store`, return.
        self.uc.mem_write(
            FX_LIST_PLAY_AT_OBJECT, b"\xff\x05" + struct.pack("<I", FX_PLAYED) + b"\xc3"
        )
        self.uc.mem_write(
            INI_PARSE_BOOL,
            b"\xa0"
            + struct.pack("<I", BOOL_TOKEN)  # mov al, [token]
            + b"\x8b\x4c\x24\x0c"  # mov ecx, [esp+0xc]
            + b"\x88\x01"  # mov [ecx], al
            + b"\xc3",
        )

    def template(self, slot: int, template_id: int) -> int:
        va = HEAP + 0x1000 + slot * 0x800
        self.uc.mem_write(va + THING_TEMPLATE_ID, struct.pack("<H", template_id))
        return va

    def obj(self, slot: int, template_va: int) -> int:
        va = HEAP + 0x100 + slot * 0x20
        self.uc.mem_write(va + 4, struct.pack("<I", template_va))
        return va

    def flag(self, template_id: int) -> int:
        return self.uc.mem_read(IDS + template_id, 1)[0]

    def set_flag(self, template_id: int, value: int) -> None:
        self.uc.mem_write(IDS + template_id, bytes([value]))

    def call(self, label: str, *args: int) -> int:
        """Run a cdecl routine; return `esp` after it returns, to check the stack balances."""
        esp = STACK + 0x8000
        frame = struct.pack(f"<I{len(args)}I", RETURN, *args)
        self.uc.mem_write(esp, frame)
        self.uc.reg_write(UC_X86_REG_ESP, esp)
        self.uc.emu_start(self.asm.label_va(label), RETURN)
        return self.uc.reg_read(UC_X86_REG_ESP) - esp

    def run_to(self, label: str, until: int, **regs: int) -> None:
        self.uc.reg_write(UC_X86_REG_ESP, STACK + 0x8000)
        for name, value in regs.items():
            self.uc.reg_write(
                {"eax": UC_X86_REG_EAX, "ebx": UC_X86_REG_EBX, "esi": UC_X86_REG_ESI}[name], value
            )
        self.uc.emu_start(self.asm.label_va(label), until)

    @property
    def fx_played(self) -> int:
        return struct.unpack("<I", self.uc.mem_read(FX_PLAYED, 4))[0]


@pytest.fixture
def engine() -> Engine:
    return Engine()


def test_gate_plays_the_fx_on_an_unflagged_object(engine: Engine) -> None:
    obj = engine.obj(0, engine.template(0, 0x1234))
    assert engine.call("fx_gate", 0xF00D, obj, 0) == 4  # only the return address popped
    assert engine.fx_played == 1


def test_gate_swallows_the_fx_on_a_flagged_object(engine: Engine) -> None:
    obj = engine.obj(0, engine.template(0, 0x1234))
    engine.set_flag(0x1234, 1)
    assert engine.call("fx_gate", 0xF00D, obj, 0) == 4
    assert engine.fx_played == 0


def test_gate_flags_are_per_template(engine: Engine) -> None:
    hidden = engine.obj(0, engine.template(0, 7))
    shown = engine.obj(1, engine.template(1, 8))
    engine.set_flag(7, 1)
    engine.call("fx_gate", 0xF00D, hidden, 0)
    engine.call("fx_gate", 0xF00D, shown, 0)
    assert engine.fx_played == 1


def test_gate_passes_a_null_object_through_to_the_engine(engine: Engine) -> None:
    engine.call("fx_gate", 0xF00D, 0, 0)
    assert engine.fx_played == 1


@pytest.mark.parametrize("token", [0, 1])
def test_parse_files_the_value_under_the_templates_id(engine: Engine, token: int) -> None:
    tmpl = engine.template(0, 0xBEEF)
    engine.set_flag(0xBEEF, 1 - token)
    engine.uc.mem_write(BOOL_TOKEN, bytes([token]))
    assert engine.call("parse", 0x1111, tmpl, tmpl, 0) == 4
    assert engine.flag(0xBEEF) == token
    assert engine.uc.mem_read(tmpl, 0x5E8) == bytes(0x5E8)  # nothing written into the template


def test_identity_keeping_copy_hands_the_flag_to_the_destinations_own_id(engine: Engine) -> None:
    dest = engine.template(0, 0x0042)  # holds the source's id, as copyFrom just left it
    engine.set_flag(0x0042, 1)
    engine.run_to(
        "keep_id", THING_TEMPLATE_COPY_KEEP_ID_RESUME, esi=dest, ebx=0x0077, eax=0xAAAA5555
    )
    assert engine.flag(0x0077) == 1
    assert engine.flag(0x0042) == 1  # the source keeps its own
    assert struct.unpack("<H", engine.uc.mem_read(dest + THING_TEMPLATE_ID, 2))[0] == 0x0077
    assert engine.uc.reg_read(UC_X86_REG_EAX) == 0xAAAA5555


def test_id_swap_keeps_the_displaced_templates_flag_and_clears_the_newcomers(
    engine: Engine,
) -> None:
    newcomer = engine.template(0, 0x0010)  # has just taken the old template's id
    old = engine.template(1, 0x0010)
    engine.set_flag(0x0010, 1)
    engine.uc.mem_write(THING_TEMPLATE_ID_COUNTER, struct.pack("<I", 0xFFF0))
    engine.run_to(
        "id_swap", THING_FACTORY_ID_SWAP_RESUME, esi=newcomer, eax=old + THING_TEMPLATE_ID
    )
    assert struct.unpack("<H", engine.uc.mem_read(old + THING_TEMPLATE_ID, 2))[0] == 0xFFF0
    assert engine.flag(0xFFF0) == 1
    assert engine.flag(0x0010) == 0
    assert engine.uc.reg_read(UC_X86_REG_EAX) == old + THING_TEMPLATE_ID
    counter = struct.unpack("<H", engine.uc.mem_read(THING_TEMPLATE_ID_COUNTER, 2))[0]
    assert counter == 0xFFEF


def test_the_resume_windows_are_reproduced_verbatim() -> None:
    code = build_code(CODE, IDS)
    body = code.finish()
    assert THING_FACTORY_ID_SWAP_BYTES in body
    assert THING_TEMPLATE_COPY_KEEP_ID_BYTES in body
