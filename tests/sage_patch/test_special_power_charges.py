"""Tests for the special-power-charges patch.

The structural checks are the usual ones - the cave's layout, the eleven edits, the round trip
through `verify`. The rest hold the properties the patch's correctness actually rests on, none of
which "it applies cleanly" would catch:

* the three new `SpecialPower` fields land **past** every stock field and the struct grows by
  exactly enough to hold them, at all three of its `operator new` sites - the one move in this
  patch that is not locally reversible if a fourth allocation existed;
* the two module fields land in padding that neither the base constructor nor the module's `Xfer`
  claims, which is what lets them exist at all;
* both constructor widenings are one opcode bit and the **same length**, so nothing is displaced;
* the rebuilt table keeps the live rows *verbatim*, because their name pointers are absolute;
* the recharge hook's declining arm replays the displaced instruction **before** resuming, so a
  power without `ChargeNumber` takes the stock path byte for byte; and
* the routines' bytes say what they were meant to say - a wrong displacement assembles, applies
  and verifies, and then jumps into the middle of an instruction in a running game.
"""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

from sage_patch.addresses import (
    DESCRIPTION_SPECIAL_POWER_CASE,
    DESCRIPTION_SPECIAL_POWER_CASE_BYTES,
    DESCRIPTION_UNIT_COST_BODY,
    FIELD_PARSE_STRIDE,
    INI_PARSE_BOOL,
    INI_PARSE_INT,
    SPECIAL_POWER_FIELD_TABLE,
    SPECIAL_POWER_FIELD_TABLE_REF_OPCODES,
    SPECIAL_POWER_FIELD_TABLE_REFS,
    SPECIAL_POWER_TEMPLATE_COPY_TAIL,
    SPECIAL_POWER_TEMPLATE_COPY_TAIL_BYTES,
    SPECIAL_POWER_TEMPLATE_NEW_SITES,
    SPECIAL_POWER_TEMPLATE_SIZE,
)
from sage_patch.patches.experimental.cooldown_through_death import CooldownThroughDeathPatch
from sage_patch.patches.experimental.special_power_charges import (
    ANCHORS,
    DESCRIPTION_CASE_NOT_TAKEN,
    INI_PARSE_DURATION,
    KEY_CHARGES,
    KEY_CHARGES_RECHARGING,
    KEYWORD_CHARGE_NUMBER,
    KEYWORD_RELOAD_BETWEEN,
    KEYWORD_REPLENISH_ALL,
    MODULE_CTOR_CALL,
    MODULE_CTOR_CALL_BYTES,
    MODULE_CTOR_FLAG,
    MODULE_CTOR_FLAG_BYTES,
    MODULE_CTOR_HELD,
    MODULE_CTOR_HELD_BYTES,
    MODULE_CTOR_RETURN,
    NEW_TEMPLATE_SIZE,
    RECHARGE_DONE,
    RECHARGE_FORMULA_ANCHORS,
    RECHARGE_HOOK,
    RECHARGE_HOOK_BYTES,
    RECHARGE_STOCK_RESUME,
    SECTION_NAME,
    SPI_DEADLINE_SHIFT,
    SPI_FLAG,
    SPI_SPENT,
    SPI_VTABLE,
    SPI_VTABLE_RECHARGE_SLOT,
    START_POWER_RECHARGE,
    TEMPLATE_CHARGE_NUMBER,
    TEMPLATE_CTOR_TAIL,
    TEMPLATE_CTOR_TAIL_BYTES,
    TEMPLATE_CTOR_TAIL_RESUME,
    TEMPLATE_RELOAD_BETWEEN,
    TEMPLATE_REPLENISH_ALL,
    TRIGGER_WALK_CALL,
    TRIGGER_WALK_CALL_BYTES,
    TRIGGER_WALK_RETURN,
    SpecialPowerChargesPatch,
    build_table,
    rewritten_module_ctor_flag,
    rewritten_module_ctor_held,
)
from sage_patch.patches.utils.field_tables import entries_before, read_field_table
from sage_patch.registry import PATCHES
from sage_patch.utils import find_section, va_to_offset
from tests.sage_patch.test_terrain_resource_exp import _pe32

IMAGE_BASE = 0x400000

#: Where the synthetic image parks the field-name strings, past every site the patch touches.
STRINGS_VA = 0x00DB0000

#: A spare keyword the fingerprint does not name, for the test that stands in for another patch
#: having already grown the struct.
INTRUDER_VA = 0x00DB1000
INTRUDER_KEYWORD = "SomeOtherPatchesField"


#: The stock `SpecialPower` field table, as ``(keyword, SpecialPowerTemplate offset)``, in the
#: order the real build holds them. The parse functions are not reproduced because the patch copies
#: every row through by value and never looks at them.
STOCK_FIELDS: tuple[tuple[str, int], ...] = (
    ("Flags", 0x18),
    ("ReloadTime", 0x20),
    ("RequiredSciences", 0x24),
    ("LightPointCost", 0x30),
    ("InitiateSound", 0x34),
    ("InitiateAtLocationSound", 0x38),
    ("UnitSpecificSoundToUseAsInitiateIntendToDoVoice", 0x3C),
    ("UnitSpecificSoundToUseAsEnterStateInitiateIntendToDoVoice", 0x40),
    ("EvaEventToPlayOnSuccess", 0x44),
    ("PublicTimer", 0x58),
    ("Enum", 0x1C),
    ("DetectionTime", 0x48),
    ("SharedSyncedTimer", 0x59),
    ("ViewObjectDuration", 0x4C),
    ("ViewObjectRange", 0x50),
    ("RadiusCursorRadius", 0x54),
    ("PalantirMovie", 0x5C),
    ("ObjectFilter", 0x60),
    ("PreventActivationConditions", 0x64),
    ("MaxCastRange", 0x74),
    ("ForbiddenObjectFilter", 0x78),
    ("ForbiddenObjectRange", 0x7C),
    ("UnitCost", 0x80),
    ("UnitCostDeathType", 0x84),
)

#: The engine bytes the patch replaces, as ``(va, original)``.
WINDOWS: tuple[tuple[int, bytes], ...] = (
    (MODULE_CTOR_FLAG, MODULE_CTOR_FLAG_BYTES),
    (MODULE_CTOR_HELD, MODULE_CTOR_HELD_BYTES),
    (TEMPLATE_CTOR_TAIL, TEMPLATE_CTOR_TAIL_BYTES),
    (SPECIAL_POWER_TEMPLATE_COPY_TAIL, SPECIAL_POWER_TEMPLATE_COPY_TAIL_BYTES),
    (RECHARGE_HOOK, RECHARGE_HOOK_BYTES),
    (DESCRIPTION_SPECIAL_POWER_CASE, DESCRIPTION_SPECIAL_POWER_CASE_BYTES),
)

_PUSH_STOCK_SIZE = b"\x68" + struct.pack("<I", SPECIAL_POWER_TEMPLATE_SIZE)


def _string_vas() -> dict[str, int]:
    vas, cursor = {}, STRINGS_VA
    for name, _offset in STOCK_FIELDS:
        vas[name] = cursor
        cursor += len(name) + 1
    return vas


def plant_sites(data: bytearray) -> None:
    """The clean bytes this patch asserts before writing, plus the stock keyword strings.

    Every window in `ANCHORS` is planted, not just the six the patch rewrites: the anchors are what
    `apply` refuses on, so a synthetic image that omitted one would test the refusal rather than
    the patch."""

    def at(va: int) -> int:
        return va - IMAGE_BASE

    for va, window in {**ANCHORS, **RECHARGE_FORMULA_ANCHORS}.items():
        data[at(va) : at(va) + len(window)] = window
    for va, window in WINDOWS:
        data[at(va) : at(va) + len(window)] = window
    for push_va, _call_va in SPECIAL_POWER_TEMPLATE_NEW_SITES:
        data[at(push_va) : at(push_va) + 5] = _PUSH_STOCK_SIZE

    struct.pack_into("<I", data, at(SPI_VTABLE + SPI_VTABLE_RECHARGE_SLOT), START_POWER_RECHARGE)

    blob = INTRUDER_KEYWORD.encode("ascii") + b"\x00"
    data[at(INTRUDER_VA) : at(INTRUDER_VA) + len(blob)] = blob

    vas = _string_vas()
    for name, va in vas.items():
        blob = name.encode("ascii") + b"\x00"
        data[at(va) : at(va) + len(blob)] = blob

    table = at(SPECIAL_POWER_FIELD_TABLE)
    for index, (name, offset) in enumerate(STOCK_FIELDS):
        # `ReloadTime`'s own parse function, because one of this patch's rows has to match it.
        parse_fn = INI_PARSE_DURATION if name == "ReloadTime" else INI_PARSE_INT
        struct.pack_into(
            "<IIII", data, table + index * FIELD_PARSE_STRIDE, vas[name], parse_fn, 0, offset
        )
    struct.pack_into("<IIII", data, table + len(STOCK_FIELDS) * FIELD_PARSE_STRIDE, 0, 0, 0, 0)

    for ref_va, opcode in zip(
        SPECIAL_POWER_FIELD_TABLE_REFS, SPECIAL_POWER_FIELD_TABLE_REF_OPCODES, strict=True
    ):
        data[at(ref_va)] = opcode
        struct.pack_into("<I", data, at(ref_va) + 1, SPECIAL_POWER_FIELD_TABLE)


def synthetic_image() -> bytearray:
    """A PE32 image carrying every site the patch asserts, with the real original bytes planted."""
    highest = max(
        max(va + len(w) for va, w in {**ANCHORS, **RECHARGE_FORMULA_ANCHORS}.items()),
        max(va + len(w) for va, w in WINDOWS),
        SPI_VTABLE + SPI_VTABLE_RECHARGE_SLOT + 4,
        STRINGS_VA + sum(len(name) + 1 for name, _ in STOCK_FIELDS),
        INTRUDER_VA + len(INTRUDER_KEYWORD) + 1,
        SPECIAL_POWER_FIELD_TABLE + (len(STOCK_FIELDS) + 1) * FIELD_PARSE_STRIDE,
    )
    data = _pe32(highest)
    plant_sites(data)
    return data


@pytest.fixture
def image() -> bytearray:
    return synthetic_image()


@pytest.fixture
def patched(image: bytearray) -> bytearray:
    SpecialPowerChargesPatch().apply(image)
    return image


def _read(data: bytes | bytearray, va: int, n: int) -> bytes:
    off = va_to_offset(data, va)
    assert off is not None, f"0x{va:08x} is not mapped"
    return bytes(data[off : off + n])


def _cave(data: bytes | bytearray) -> tuple[int, int]:
    located = find_section(data, SECTION_NAME)
    assert located is not None, f"no {SECTION_NAME} section"
    base_va, _off, vsize = located
    return base_va, vsize


def _table_va(data: bytes | bytearray) -> int:
    """Where the field table lives now, read from the reference the parser uses."""
    push = _read(data, SPECIAL_POWER_FIELD_TABLE_REFS[1], 5)
    assert push[0] == 0x68
    return struct.unpack_from("<I", push, 1)[0]


def _rows(data: bytes | bytearray, table_va: int) -> list[tuple[int, int, int, int]]:
    rows, index = [], 0
    while True:
        row = struct.unpack(
            "<IIII", _read(data, table_va + index * FIELD_PARSE_STRIDE, FIELD_PARSE_STRIDE)
        )
        if row[0] == 0 and row[1] == 0:
            return rows
        rows.append(row)
        index += 1


def _jump_target(data: bytes | bytearray, va: int) -> int:
    window = _read(data, va, 5)
    assert window[0] == 0xE9, f"0x{va:08x} does not hold a jmp rel32"
    return va + 5 + struct.unpack_from("<i", window, 1)[0]


def _labels(data: bytes | bytearray) -> dict[str, int]:
    """Where each routine landed, re-derived the way `verify` does."""
    base_va, _vsize = _cave(data)
    live = read_field_table(data, _table_va(data))
    preceding = entries_before(data, live, KEYWORD_CHARGE_NUMBER)
    assert preceding is not None
    asm = SpecialPowerChargesPatch._assemble(base_va, preceding)
    return {name: asm.label_va(name) for name in asm._labels}


# --- where the three template fields live -----------------------------------------------------


def test_the_new_fields_land_past_every_stock_field() -> None:
    """The struct is packed solid: its last field is a dword at `+0x84` and `sizeof` is `0x88`, so
    the three new ones have to come from the end. Anything overlapping a stock field would be a
    silent corruption of it."""
    claimed: set[int] = set()
    for _name, offset in STOCK_FIELDS:
        claimed.update(range(offset, offset + 4))
    for offset in (TEMPLATE_CHARGE_NUMBER, TEMPLATE_RELOAD_BETWEEN, TEMPLATE_REPLENISH_ALL):
        assert offset >= SPECIAL_POWER_TEMPLATE_SIZE
        assert not claimed & set(range(offset, offset + 4))


def test_the_struct_grows_by_exactly_the_three_fields() -> None:
    assert NEW_TEMPLATE_SIZE == SPECIAL_POWER_TEMPLATE_SIZE + 12
    assert TEMPLATE_REPLENISH_ALL + 4 == NEW_TEMPLATE_SIZE


def test_every_allocation_site_is_grown(patched: bytearray) -> None:
    """All three, or a template allocated at the odd one out is nine bytes short of the fields the
    parser will write into it."""
    want = b"\x68" + struct.pack("<I", NEW_TEMPLATE_SIZE)
    for push_va, _call_va in SPECIAL_POWER_TEMPLATE_NEW_SITES:
        assert _read(patched, push_va, 5) == want, f"0x{push_va:08x}"


def test_growing_the_allocation_is_the_same_length(patched: bytearray) -> None:
    """`push imm32` either way, so nothing after the site moves and no instruction is displaced."""
    assert len(_PUSH_STOCK_SIZE) == 5
    for push_va, _call_va in SPECIAL_POWER_TEMPLATE_NEW_SITES:
        assert _read(patched, push_va, 1) == b"\x68"


# --- where the two module fields live ---------------------------------------------------------


def test_the_module_fields_are_in_padding_the_base_leaves(patched: bytearray) -> None:
    """`+0x19..+0x1B` is the gap behind the recharge flag at `+0x18`, and `+0x21..+0x23` the tail
    behind the held latch at `+0x20`. The interface's `sizeof` is `0x24`, so both are interior."""
    assert SPI_DEADLINE_SHIFT == 8, "the deadline is the top three bytes of the dword at +0x18"
    assert SPI_FLAG == 0x18
    assert 0x19 <= SPI_FLAG + 1 <= 0x1B
    assert 0x21 <= SPI_SPENT <= 0x23


def test_both_ctor_widenings_are_one_opcode_bit_and_the_same_length() -> None:
    """`mov byte` -> `mov dword`, `88` -> `89`. Same length is what makes them in-place edits with
    no hook, no displaced instruction and nothing to resume to."""
    for stock, widened in (
        (MODULE_CTOR_FLAG_BYTES, rewritten_module_ctor_flag()),
        (MODULE_CTOR_HELD_BYTES, rewritten_module_ctor_held()),
    ):
        assert len(widened) == len(stock)
        assert widened[1:] == stock[1:]
        assert stock[0] == 0x88 and widened[0] == 0x89


def test_the_ctor_widenings_are_written(patched: bytearray) -> None:
    assert _read(patched, MODULE_CTOR_FLAG, 3) == rewritten_module_ctor_flag()
    assert _read(patched, MODULE_CTOR_HELD, 3) == rewritten_module_ctor_held()


# --- the rebuilt field table --------------------------------------------------------------------


def test_apply_repoints_both_table_references(patched: bytearray) -> None:
    base_va, _vsize = _cave(patched)
    seen = set()
    for ref_va, opcode in zip(
        SPECIAL_POWER_FIELD_TABLE_REFS, SPECIAL_POWER_FIELD_TABLE_REF_OPCODES, strict=True
    ):
        window = _read(patched, ref_va, 5)
        assert window[0] == opcode
        seen.add(struct.unpack_from("<I", window, 1)[0])
    assert len(seen) == 1
    assert base_va <= seen.pop() < base_va + _cave(patched)[1]


def test_apply_leaves_the_stock_table_where_it_was(patched: bytearray) -> None:
    """The rebuilt table is a copy in the cave; nothing overwrites the original, which is what
    keeps the edit reversible by repointing the two references back."""
    assert _table_va(patched) != SPECIAL_POWER_FIELD_TABLE
    first = struct.unpack("<IIII", _read(patched, SPECIAL_POWER_FIELD_TABLE, FIELD_PARSE_STRIDE))
    assert first[3] == STOCK_FIELDS[0][1]


def test_rebuilt_table_keeps_the_live_rows_verbatim(patched: bytearray) -> None:
    """Every pointer in a row is absolute - the keyword strings stay where they are - so a copy is
    the only correct transformation."""
    rows = _rows(patched, _table_va(patched))
    stock = _rows(synthetic_image(), SPECIAL_POWER_FIELD_TABLE)
    assert rows[: len(stock)] == stock


def test_rebuilt_table_appends_the_three_fields(patched: bytearray) -> None:
    rows = _rows(patched, _table_va(patched))
    added = rows[len(STOCK_FIELDS) :]
    assert len(added) == 3
    wanted = (
        (KEYWORD_CHARGE_NUMBER, INI_PARSE_INT, TEMPLATE_CHARGE_NUMBER),
        (KEYWORD_RELOAD_BETWEEN, INI_PARSE_DURATION, TEMPLATE_RELOAD_BETWEEN),
        (KEYWORD_REPLENISH_ALL, INI_PARSE_BOOL, TEMPLATE_REPLENISH_ALL),
    )
    for row, (keyword, parse_fn, offset) in zip(added, wanted, strict=True):
        name_va, fn, userdata, at = row
        assert _read(patched, name_va, len(keyword) + 1) == keyword.encode() + b"\x00"
        assert (fn, userdata, at) == (parse_fn, 0, offset)


def test_reload_between_reuses_the_reload_time_parser(patched: bytearray) -> None:
    """The whole point of the keyword: milliseconds in, frames in the struct, by the same function
    `ReloadTime` goes through - so the cave's arithmetic is a copy rather than a conversion."""
    rows = {
        _read(patched, name, 64).split(b"\x00")[0].decode(): fn
        for name, fn, _u, _o in _rows(patched, _table_va(patched))
    }
    assert rows[KEYWORD_RELOAD_BETWEEN] == rows["ReloadTime"]


def test_build_table_is_terminated() -> None:
    blob = build_table((), 0x1000, 0x2000, 0x3000)
    assert len(blob) == 4 * FIELD_PARSE_STRIDE
    assert blob[-FIELD_PARSE_STRIDE:] == bytes(FIELD_PARSE_STRIDE)


# --- the hooks ----------------------------------------------------------------------------------


def test_every_window_is_hooked(patched: bytearray) -> None:
    labels = _labels(patched)
    for va, label in (
        (TEMPLATE_CTOR_TAIL, "ctor"),
        (SPECIAL_POWER_TEMPLATE_COPY_TAIL, "copy"),
        (RECHARGE_HOOK, "cast"),
        (DESCRIPTION_SPECIAL_POWER_CASE, "description"),
    ):
        assert _jump_target(patched, va) == labels[label], f"0x{va:08x}"


def test_hooks_that_displace_more_than_five_bytes_are_padded(patched: bytearray) -> None:
    """A `jmp rel32` is five bytes; the rest of a longer window has to become `nop`, or the tail of
    the displaced instruction is executed as code."""
    for va, window in WINDOWS:
        if len(window) > 5 and window not in (MODULE_CTOR_FLAG_BYTES, MODULE_CTOR_HELD_BYTES):
            tail = _read(patched, va + 5, len(window) - 5)
            assert tail == b"\x90" * (len(window) - 5), f"0x{va:08x}"


def test_the_cast_hook_excludes_the_two_arms_that_are_not_a_use(patched: bytearray) -> None:
    """**The test this patch exists in its current shape because of.** `startPowerRecharge` arms a
    cooldown from fourteen sites and only some of them are somebody using the power. Two are
    provably not, and the cave has to recognise them by return address before it does anything
    else - a charge spent in the module constructor puts every charge power one short at spawn.

    Asserted as bytes rather than through `verify`, because the constants being right and the
    comparison being *emitted* are different claims."""
    labels = _labels(patched)
    body = _read(patched, labels["cast"], 0x18)
    assert body[0:3] == bytes([0x8B, 0x45, 0x04]), "the return address is not read first"
    assert struct.unpack_from("<I", body, 4)[0] == MODULE_CTOR_RETURN
    assert struct.unpack_from("<I", body, 15)[0] == TRIGGER_WALK_RETURN


def test_the_two_excluded_return_addresses_are_the_calls_they_claim(patched: bytearray) -> None:
    """A return address is only meaningful next to the call it returns from. Both are checked
    against the live bytes, so a build that moved either call fails here rather than charging the
    constructor again."""
    assert _read(patched, MODULE_CTOR_CALL, len(MODULE_CTOR_CALL_BYTES)) == MODULE_CTOR_CALL_BYTES
    assert MODULE_CTOR_CALL + len(MODULE_CTOR_CALL_BYTES) == MODULE_CTOR_RETURN
    assert _read(patched, TRIGGER_WALK_CALL, len(TRIGGER_WALK_CALL_BYTES)) == (
        TRIGGER_WALK_CALL_BYTES
    )
    assert TRIGGER_WALK_CALL + len(TRIGGER_WALK_CALL_BYTES) == TRIGGER_WALK_RETURN


def test_the_module_constructor_call_is_left_alone(patched: bytearray) -> None:
    """It is excluded by return address, not by being rewritten - so the engine goes on arming a
    power that declares itself to start on cooldown, exactly as it does today."""
    window = _read(patched, MODULE_CTOR_CALL, 5)
    assert window[0] == 0xE8
    assert MODULE_CTOR_CALL + 5 + struct.unpack_from("<i", window, 1)[0] == START_POWER_RECHARGE


def test_the_arm_that_declines_replays_the_displaced_instruction(patched: bytearray) -> None:
    """Every way out that is not a charge power - the two excluded callers, a missing template, a
    zero `ChargeNumber` - takes the stock path **byte for byte**, which means the five bytes the
    hook took are re-executed before the resume rather than skipped."""
    labels = _labels(patched)
    stock = labels["c_stock"]
    assert _read(patched, stock, len(RECHARGE_HOOK_BYTES)) == RECHARGE_HOOK_BYTES
    assert _jump_target(patched, stock + len(RECHARGE_HOOK_BYTES)) == RECHARGE_STOCK_RESUME


def test_every_arm_leaves_the_cave_where_it_should(patched: bytearray) -> None:
    """Four `jmp rel32` back into the engine, one per hook. A cave that fell off its own end would
    execute whatever the section allocator zero-padded it with."""
    cave_va, vsize = _cave(patched)
    body = _read(patched, cave_va, vsize)
    targets = {
        cave_va + index + 5 + struct.unpack_from("<i", body, index + 1)[0]
        for index in range(len(body) - 5)
        if body[index] == 0xE9
    }
    assert RECHARGE_STOCK_RESUME in targets
    assert RECHARGE_DONE in targets
    assert TEMPLATE_CTOR_TAIL_RESUME in targets
    assert DESCRIPTION_UNIT_COST_BODY in targets
    assert DESCRIPTION_CASE_NOT_TAKEN in targets


def test_the_template_ctor_hook_runs_the_displaced_store_first(patched: bytearray) -> None:
    """The three new fields are zeroed *after* the store the hook took, so `UnitCostDeathType`
    still gets its zero however the cave then behaves."""
    labels = _labels(patched)
    assert _read(patched, labels["ctor"], len(TEMPLATE_CTOR_TAIL_BYTES)) == TEMPLATE_CTOR_TAIL_BYTES


def test_the_copy_hook_runs_the_field_copies_before_the_displaced_epilogue(
    patched: bytearray,
) -> None:
    """The displaced epilogue ends in `ret 4`, so anything emitted after it would never run - the
    three copies have to come first."""
    labels = _labels(patched)
    body = _read(patched, labels["copy"], 0x40)
    at = body.find(SPECIAL_POWER_TEMPLATE_COPY_TAIL_BYTES)
    assert at > 0, "the epilogue is not in the copy routine, or it is the first thing in it"
    assert at == 3 * 12, "three six-byte load/store pairs, then the epilogue"


def test_the_description_hook_preserves_the_case_it_displaced(patched: bytearray) -> None:
    """The window is `cmp ecx, 0x18` / `jne <done>`; both have to still happen, or every other
    button's description falls into the special-power body."""
    labels = _labels(patched)
    assert _read(patched, labels["description"], 3) == DESCRIPTION_SPECIAL_POWER_CASE_BYTES[:3]


# --- the cave ------------------------------------------------------------------------------------


def test_the_cave_opens_with_both_localization_keys(patched: bytearray) -> None:
    base_va, _vsize = _cave(patched)
    blob = _read(patched, base_va, 128)
    assert blob.startswith(KEY_CHARGES.encode() + b"\x00")
    assert KEY_CHARGES_RECHARGING.encode() + b"\x00" in blob


def test_the_cave_is_executable(patched: bytearray) -> None:
    """The cave holds code the engine jumps into, so the section it lands in has to be executable -
    which `Section` does not model, so the header is read directly."""
    e_lfanew = struct.unpack_from("<I", patched, 0x3C)[0]
    count = struct.unpack_from("<H", patched, e_lfanew + 6)[0]
    opt_size = struct.unpack_from("<H", patched, e_lfanew + 20)[0]
    table = e_lfanew + 24 + opt_size
    for index in range(count):
        header = table + index * 40
        if bytes(patched[header : header + 8]).rstrip(b"\x00") == SECTION_NAME.encode():
            characteristics = struct.unpack_from("<I", patched, header + 36)[0]
            assert characteristics & 0x20000000, "MEM_EXECUTE"
            return
    pytest.fail(f"no {SECTION_NAME} section header")


def test_the_fold_routine_is_shared_by_both_callers(patched: bytearray) -> None:
    """The readout and the cast must not be able to disagree about what the bank is, which is only
    guaranteed by their calling the same code - so `fold` has exactly two callers."""
    labels = _labels(patched)
    base_va, vsize = _cave(patched)
    body = _read(patched, base_va, vsize)
    callers = [
        base_va + index
        for index in range(len(body) - 5)
        if body[index] == 0xE8
        and base_va + index + 5 + struct.unpack_from("<i", body, index + 1)[0] == labels["fold"]
    ]
    assert len(callers) == 2
    assert labels["cast"] < callers[0] < labels["description"]
    assert labels["description"] < callers[1] < labels["interval"]


# --- verify / detect ------------------------------------------------------------------------------


def test_verify_clean_after_apply(patched: bytearray) -> None:
    assert SpecialPowerChargesPatch().verify(patched) == []


def test_verify_rejects_an_unpatched_image(image: bytearray) -> None:
    assert SpecialPowerChargesPatch().verify(image) != []


def test_verify_rejects_a_table_that_dropped_the_fields(patched: bytearray) -> None:
    """A later patch that rebuilt the table without carrying these rows forward leaves a binary
    whose cave is intact and whose engine parses nothing."""
    table_va = _table_va(patched)
    off = va_to_offset(patched, table_va + len(STOCK_FIELDS) * FIELD_PARSE_STRIDE)
    assert off is not None
    struct.pack_into("<IIII", patched, off, 0, 0, 0, 0)
    assert SpecialPowerChargesPatch().verify(patched) != []


def test_detect_finds_it(patched: bytearray) -> None:
    assert isinstance(SpecialPowerChargesPatch.detect(patched), SpecialPowerChargesPatch)


def test_detect_finds_nothing_in_a_clean_image(image: bytearray) -> None:
    assert SpecialPowerChargesPatch.detect(image) is None


# --- what applying refuses --------------------------------------------------------------------


def test_applying_twice_raises(patched: bytearray) -> None:
    with pytest.raises(ValueError, match="already"):
        SpecialPowerChargesPatch().apply(patched)


def test_apply_refuses_a_moved_anchor(image: bytearray) -> None:
    va = next(iter(ANCHORS))
    off = va_to_offset(image, va)
    assert off is not None
    image[off] ^= 0xFF
    with pytest.raises(ValueError, match="not the build"):
        SpecialPowerChargesPatch().apply(image)


def test_apply_refuses_when_the_flavour_slot_moved(image: bytearray) -> None:
    off = va_to_offset(image, SPI_VTABLE + SPI_VTABLE_RECHARGE_SLOT)
    assert off is not None
    struct.pack_into("<I", image, off, START_POWER_RECHARGE + 0x10)
    with pytest.raises(ValueError, match="dispatches to"):
        SpecialPowerChargesPatch().apply(image)


def test_apply_refuses_a_table_whose_fields_moved(image: bytearray) -> None:
    off = va_to_offset(image, SPECIAL_POWER_FIELD_TABLE + FIELD_PARSE_STRIDE)
    assert off is not None
    struct.pack_into("<I", image, off + 12, 0x2C)  # ReloadTime somewhere else
    with pytest.raises(ValueError, match="ReloadTime"):
        SpecialPowerChargesPatch().apply(image)


def test_apply_refuses_a_struct_another_patch_already_grew(image: bytearray) -> None:
    """`hero-mana` takes `+0x88` for its own field. Sharing an offset would make one of the two
    fields silently write the other's, so this has to be a refusal rather than a race."""
    terminator = SPECIAL_POWER_FIELD_TABLE + len(STOCK_FIELDS) * FIELD_PARSE_STRIDE
    off = va_to_offset(image, terminator)
    assert off is not None
    struct.pack_into("<IIII", image, off, INTRUDER_VA, INI_PARSE_INT, 0, TEMPLATE_CHARGE_NUMBER)
    struct.pack_into("<IIII", image, off + FIELD_PARSE_STRIDE, 0, 0, 0, 0)
    with pytest.raises(ValueError, match="already uses offset"):
        SpecialPowerChargesPatch().apply(image)


def test_apply_refuses_an_allocation_that_is_already_grown(image: bytearray) -> None:
    push_va = SPECIAL_POWER_TEMPLATE_NEW_SITES[0][0]
    off = va_to_offset(image, push_va)
    assert off is not None
    struct.pack_into("<I", image, off + 1, NEW_TEMPLATE_SIZE)
    with pytest.raises(ValueError, match="already been grown"):
        SpecialPowerChargesPatch().apply(image)


# --- the INI surface ------------------------------------------------------------------------------


def test_ini_surface_names_all_three_fields() -> None:
    surface = SpecialPowerChargesPatch().ini_surface()
    by_name = {delta.name: delta for delta in surface.fields}
    assert set(by_name) == {
        KEYWORD_CHARGE_NUMBER,
        KEYWORD_RELOAD_BETWEEN,
        KEYWORD_REPLENISH_ALL,
    }
    assert all(delta.block == "SpecialPower" for delta in surface.fields)
    assert by_name[KEYWORD_CHARGE_NUMBER].default == 0, "off unless the mod asks for it"
    assert by_name[KEYWORD_REPLENISH_ALL].default is False


def test_registered() -> None:
    assert PATCHES[SpecialPowerChargesPatch.name] is SpecialPowerChargesPatch


def test_declared_experimental() -> None:
    """It lives in `patches/experimental/`, so the attribute has to agree - `apply` prints the
    warning off the attribute and a reader finds out from the module, and the two disagreeing is
    the failure `TestExperimentalPatchesAreDeclared` exists for."""
    assert SpecialPowerChargesPatch.experimental is True


# --- against the real binaries ------------------------------------------------------------------

#: The repo-root `game.dat` carries eleven modifications and `sage_patch/engine/game.dat.backup`
#: is the clean reference, so a site is only safe to describe as stock when both agree - and none
#: of this patch's does anything else. Neither binary is committed, so each check skips when its
#: file is absent.
_BINARIES = {
    "repo": Path(__file__).resolve().parents[2] / "game.dat",
    "clean": Path(__file__).resolve().parents[2] / "sage_patch" / "engine" / "game.dat.backup",
}


@pytest.mark.parametrize("which", sorted(_BINARIES))
class TestStockBinaries:
    """Against the real binaries, which are the only things that can say the addresses are right.

    The synthetic image is built from this patch's own tables, so it round-trips whatever those
    tables say. Only a shipped `game.dat` can confirm that `0x00896F75` is `startPowerRecharge`'s
    full-recharge arm rather than the middle of something else."""

    def _stock(self, which: str) -> bytes:
        path = _BINARIES[which]
        if not path.exists():
            pytest.skip(f"needs {path.name}")
        return path.read_bytes()

    def test_every_site_holds_its_stock_bytes(self, which: str) -> None:
        stock = self._stock(which)
        for va, expected in (
            *WINDOWS,
            *ANCHORS.items(),
            *RECHARGE_FORMULA_ANCHORS.items(),
        ):
            off = va_to_offset(stock, va)
            assert off is not None, f"{va:#010x} is not mapped"
            assert bytes(stock[off : off + len(expected)]) == expected, f"{va:#010x}"

    def test_every_allocation_asks_for_the_stock_size(self, which: str) -> None:
        stock = self._stock(which)
        for push_va, _call_va in SPECIAL_POWER_TEMPLATE_NEW_SITES:
            off = va_to_offset(stock, push_va)
            assert off is not None
            assert bytes(stock[off : off + 5]) == _PUSH_STOCK_SIZE, f"{push_va:#010x}"

    def test_the_flavour_slot_names_start_power_recharge(self, which: str) -> None:
        stock = self._stock(which)
        off = va_to_offset(stock, SPI_VTABLE + SPI_VTABLE_RECHARGE_SLOT)
        assert off is not None
        assert struct.unpack_from("<I", stock, off)[0] == START_POWER_RECHARGE

    def test_the_stock_table_holds_the_fields_this_patch_fingerprints(self, which: str) -> None:
        stock = self._stock(which)
        rows = _rows(stock, SPECIAL_POWER_FIELD_TABLE)
        by_name = {
            bytes(stock[va_to_offset(stock, name) :]).split(b"\x00")[0].decode(): offset
            for name, _fn, _ud, offset in rows
        }
        assert by_name["ReloadTime"] == 0x20
        assert by_name["UnitCostDeathType"] == 0x84
        assert max(by_name.values()) < TEMPLATE_CHARGE_NUMBER

    def test_apply_verify_detect_round_trip(self, which: str) -> None:
        data = bytearray(self._stock(which))
        patch = SpecialPowerChargesPatch()
        patch.apply(data)
        assert patch.verify(data) == []
        assert isinstance(SpecialPowerChargesPatch.detect(data), SpecialPowerChargesPatch)

    def test_it_composes_with_cooldown_through_death(self, which: str) -> None:
        """Both extend the `SpecialPower` field table and both read it live, so the second appends
        to the first's. `cooldown-through-death` spends the interior padding at `+0x5A`/`+0x5B`;
        this one grows the tail. They share no byte - but see the ordering test below."""
        data = bytearray(self._stock(which))
        order = (CooldownThroughDeathPatch(), SpecialPowerChargesPatch())
        for patch in order:
            patch.apply(data)
        for patch in order:
            assert patch.verify(data) == [], str(patch)

    def test_cooldown_through_death_has_to_be_applied_first(self, which: str) -> None:
        """The pair is **ordered**, and loudly so. `cooldown-through-death` anchors a 29-byte
        window over `startPowerRecharge`'s full arm - the five bytes this patch's hook takes - so
        it refuses to apply afterwards rather than writing over a live jump. Recorded as a test
        because the constraint is a consequence of *where the hook has to be*, not a preference:
        the caller discrimination needs `[ebp+4]`, which needs to be inside that function."""
        data = bytearray(self._stock(which))
        SpecialPowerChargesPatch().apply(data)
        with pytest.raises(ValueError, match="not the build"):
            CooldownThroughDeathPatch().apply(data)

    def test_the_two_excluded_calls_are_where_the_patch_says(self, which: str) -> None:
        """The whole discrimination rests on two return addresses, and a return address is a fact
        about the *stock* binary. Only a real `game.dat` can say these two calls are the module
        constructor's and the `OnTriggerRecharge` walk's."""
        stock = self._stock(which)
        for call_va, call_bytes, return_va in (
            (MODULE_CTOR_CALL, MODULE_CTOR_CALL_BYTES, MODULE_CTOR_RETURN),
            (TRIGGER_WALK_CALL, TRIGGER_WALK_CALL_BYTES, TRIGGER_WALK_RETURN),
        ):
            assert _read(stock, call_va, len(call_bytes)) == call_bytes, f"{call_va:#010x}"
            assert call_va + len(call_bytes) == return_va

    def test_the_constructors_call_really_reaches_start_power_recharge(self, which: str) -> None:
        """The direct one is checkable outright, and it is the arm that mattered: without the
        exclusion every charge power spawns one charge short."""
        stock = self._stock(which)
        window = _read(stock, MODULE_CTOR_CALL, 5)
        assert window[0] == 0xE8
        target = MODULE_CTOR_CALL + 5 + struct.unpack_from("<i", window, 1)[0]
        assert target == START_POWER_RECHARGE
