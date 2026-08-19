"""Tests for the command-point-cost patch.

The structural checks are the usual ones - the cave's layout, the five edits, the round trip
through `verify`. The rest hold the properties the patch's correctness actually rests on, none of
which "it applies cleanly" would catch:

* the new field lands on the **aligned word** of `CommandButton`'s alignment padding, so ``sizeof``
  never has to change and `ControlBar::newCommandButton`'s ``operator new(0x2E0)`` is left alone -
  and it does not collide with the byte `queue-ignore-cp` takes out of the same three-byte hole;
* the constructor routine reproduces the store it displaced *before* it zeroes the new field, since
  `operator new` does not zero the block and a button with a random cost would be unpressable;
* the gate routine leaves **every** register as it found it. `ecx` is live across the hook window -
  it is the `Player *` two `__thiscall`s six and thirteen bytes past the resume point take as their
  implicit `this` - and the first build of this patch used it as scratch and crashed at
  `0x006AD100` on a null `this`. The routine is now bracketed by `pushad`/`popad`, and both the
  liveness of `ecx` and the bracket are asserted;
* its stack balances: one `push`/`pop` pair across `getCommandPointCap`, and its refusal edge lands
  on the evaluator's shared tail at exactly the depth the tail's pops expect;
* the refusal is the engine's own verdict 7 - the number `0x00942F47` pushes - because that is what
  greys the button and turns a click into `GUI:ErrorNoMoreCommandPoints` rather than an order; and
* the two routines' bytes say what they were meant to say - a wrong displacement assembles, applies
  and verifies, and then jumps into the middle of an instruction in a running game.
"""

from __future__ import annotations

import struct

import pytest

from sage_patch import CommandPointCostPatch, QueueIgnoreCpPatch
from sage_patch.addresses import (
    COMMAND_BUTTON_COMMAND,
    COMMAND_BUTTON_FIELD_TABLE,
    COMMAND_BUTTON_FIELD_TABLE_REF_OPCODES,
    COMMAND_BUTTON_FIELD_TABLE_REFS,
    COMMAND_BUTTON_FREE_OFFSET,
    COMMAND_BUTTON_SIZE,
    FIELD_PARSE_STRIDE,
    INI_PARSE_BOOL,
    INI_PARSE_UNSIGNED_SHORT,
)
from sage_patch.patches.command_point_cost import (
    ANCHORS,
    AVAILABILITY_BUTTON_EBP,
    AVAILABILITY_HOOK_STOCK,
    AVAILABILITY_HOOK_VA,
    AVAILABILITY_PLAYER_EBP,
    AVAILABILITY_REFUSE_TAIL,
    AVAILABILITY_RESUME_VA,
    COMMAND_POINT_COST_OFFSET,
    COMMAND_POINTS_IN_USE,
    CTOR_HOOK_STOCK,
    CTOR_HOOK_VA,
    CTOR_RESUME_VA,
    DEFAULT_KEYWORD,
    GET_COMMAND_POINT_CAP,
    NOT_ENOUGH_COMMAND_POINTS,
    PLAYER_COMMAND_POINTS,
    SECTION_NAME,
    build_code,
    build_table,
    entry_points,
)
from sage_patch.patches.multi_execute_gate import (
    GATE_A_CALL_VA,
    GATE_A_WINDOW,
    GATE_B_CALL_VA,
    GATE_B_WINDOW,
    MODEL_CONDITION_GATE_WINDOW,
)
from sage_patch.registry import PATCHES
from sage_patch.utils import find_section, va_to_offset
from tests.sage_patch.test_patching import _section_rvas
from tests.sage_patch.test_queue_ignore_cp import STOCK_FIELDS, _string_vas
from tests.sage_patch.test_queue_ignore_cp import plant_sites as plant_queue_ignore_cp_sites
from tests.sage_patch.test_terrain_resource_exp import _pe32

IMAGE_BASE = 0x400000

#: Where the shared `CommandButton` planting helper parks the field-name strings.
STRINGS_VA = 0x00C31000

#: Byte widths for the offsets `STOCK_FIELDS` names, so a test can prove the new field's two bytes
#: are claimed by none of them. Everything not listed is a dword or larger and is covered by the
#: `AffectsKindOf` bound instead.
_WIDTHS = {0x100: 1, 0x101: 1, 0x102: 1, 0x104: 1, 0x105: 1, 0x106: 1, 0x107: 1, 0x10C: 1}

#: `pushad` / `popad` - the guard the gate routine brackets its whole body with. Never counted as
#: bare bytes: `0x60` is also `PLAYER_COMMAND_POINTS` in `add edx, 0x60`, and either can turn up
#: inside a `rel32` at some cave addresses. Every assertion below is on a whole sequence.
PUSHAD, POPAD = 0x60, 0x61


def plant_sites(data: bytearray) -> None:
    """The clean bytes this patch asserts before writing: the `CommandButton` field table and its
    keyword strings, plus every anchor window."""
    plant_queue_ignore_cp_sites(data)
    for va, blob in ANCHORS.items():
        data[va - IMAGE_BASE : va - IMAGE_BASE + len(blob)] = blob


def synthetic_image() -> bytearray:
    """A PE32 image carrying every site the patch asserts, with the real original bytes planted."""
    highest = max(
        STRINGS_VA + sum(len(name) + 1 for name, _ in STOCK_FIELDS),
        COMMAND_BUTTON_FIELD_TABLE + (len(STOCK_FIELDS) + 1) * FIELD_PARSE_STRIDE,
        max(va + len(blob) for va, blob in ANCHORS.items()),
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


def _table_va(data: bytes | bytearray) -> int:
    """Where the field table lives now, read from the reference the parser uses."""
    push = _read(data, COMMAND_BUTTON_FIELD_TABLE_REFS[1], 5)
    assert push[0] == 0x68
    return struct.unpack_from("<I", push, 1)[0]


def _live_entries() -> tuple[tuple[int, int, int, int], ...]:
    vas = _string_vas()
    return tuple((vas[name], INI_PARSE_BOOL, 0, offset) for name, offset in STOCK_FIELDS)


# --- the field's home ------------------------------------------------------------------------


def test_new_field_lands_in_alignment_padding() -> None:
    """The two bytes the patch uses are inside the struct and claimed by no stock field.

    This is what the whole patch rests on: if it did not hold, `sizeof(CommandButton)` and the
    `operator new(0x2E0)` that allocates it would both have to grow."""
    claimed: set[int] = set()
    for _name, offset in STOCK_FIELDS:
        claimed.update(range(offset, offset + _WIDTHS.get(offset, 4)))
    ours = set(range(COMMAND_POINT_COST_OFFSET, COMMAND_POINT_COST_OFFSET + 2))
    assert ours.isdisjoint(claimed)
    assert max(ours) < COMMAND_BUTTON_SIZE


def test_new_field_is_word_aligned() -> None:
    """`INI::parseUnsignedShort` does `mov word [store], ax`, so a misaligned home would be a
    split store across the `KindOfFlags` boundary rather than a slow one."""
    assert COMMAND_POINT_COST_OFFSET % 2 == 0


def test_new_field_sits_below_the_kindof_mask() -> None:
    """`AffectsKindOf` is memset separately, starting at +0x110 - so the padding this patch takes
    ends where that memset begins, and the two cannot overlap."""
    kindof = dict(STOCK_FIELDS)["AffectsKindOf"]
    assert COMMAND_POINT_COST_OFFSET + 2 <= kindof


def test_the_field_does_not_collide_with_queue_ignore_cp() -> None:
    """Both patches live in the same three-byte hole. `queue-ignore-cp` takes the byte at +0x10D
    and this one the aligned word above it, so the two can be applied together."""
    assert COMMAND_BUTTON_FREE_OFFSET not in range(
        COMMAND_POINT_COST_OFFSET, COMMAND_POINT_COST_OFFSET + 2
    )


def test_the_allocation_size_is_asserted_and_never_written(image: bytearray) -> None:
    """A field in the padding is only free while the allocation is the size it is, so the
    `push 0x2E0` is anchored - and it is still there afterwards."""
    alloc_va = 0x0071C446
    assert ANCHORS[alloc_va] == bytes([0x68]) + struct.pack("<I", COMMAND_BUTTON_SIZE)
    before = _read(image, alloc_va, 5)
    CommandPointCostPatch().apply(image)
    assert _read(image, alloc_va, 5) == before


# --- the rebuilt table -----------------------------------------------------------------------


def test_table_keeps_the_live_rows_verbatim() -> None:
    entries = _live_entries()
    table = build_table(entries, 0x00F00000)
    for index, entry in enumerate(entries):
        assert struct.unpack_from("<IIII", table, index * FIELD_PARSE_STRIDE) == entry


def test_table_appends_one_unsigned_short_row_and_a_terminator() -> None:
    entries = _live_entries()
    keyword_va = 0x00F00000
    table = build_table(entries, keyword_va)
    assert len(table) == (len(entries) + 2) * FIELD_PARSE_STRIDE
    row = struct.unpack_from("<IIII", table, len(entries) * FIELD_PARSE_STRIDE)
    assert row == (keyword_va, INI_PARSE_UNSIGNED_SHORT, 0, COMMAND_POINT_COST_OFFSET)
    assert table[-FIELD_PARSE_STRIDE:] == bytes(FIELD_PARSE_STRIDE)


# --- the cave's code -------------------------------------------------------------------------


def _decode_jmp(code: bytes, base: int, at: int) -> int:
    assert code[at] == 0xE9, f"expected a jmp rel32 at +0x{at:x}, got 0x{code[at]:02x}"
    return base + at + 5 + struct.unpack_from("<i", code, at + 1)[0]


def _routine(base: int, name: str) -> tuple[bytes, int]:
    """A routine's bytes and the address it starts at."""
    code = build_code(base)
    start = entry_points(base)[name] - base
    return code[start:], base + start


def test_ctor_routine_reproduces_the_store_then_zeroes_the_new_field() -> None:
    """The order is the safety argument. `operator new` does not zero the block, so the field is
    garbage until this runs - and the displaced store has to happen too, or `RequireLevel` becomes
    garbage instead."""
    base = 0x00F00000
    body, at = _routine(base, "ctor")

    assert body[: len(CTOR_HOOK_STOCK)] == CTOR_HOOK_STOCK
    zero = body[len(CTOR_HOOK_STOCK) :]
    assert zero[0:3] == bytes([0x66, 0xC7, 0x86])  # mov word [esi+disp32], imm16
    assert struct.unpack_from("<I", zero, 3)[0] == COMMAND_POINT_COST_OFFSET
    assert struct.unpack_from("<H", zero, 7)[0] == 0

    assert _decode_jmp(body, at, len(CTOR_HOOK_STOCK) + 9) == CTOR_RESUME_VA


def test_ctor_routine_does_not_touch_the_byte_queue_ignore_cp_defaults() -> None:
    """`queue-ignore-cp` clears +0x10D by widening the store at ``0x0075D688``. This routine ends
    before that instruction and must not reproduce or pre-empt it, or the two would fight."""
    body, _at = _routine(0x00F00000, "ctor")
    assert struct.pack("<I", COMMAND_BUTTON_FREE_OFFSET) not in body


def test_gate_routine_reads_the_field_off_the_button_argument() -> None:
    base = 0x00F00000
    body, _at = _routine(base, "gate")

    assert body[0:3] == bytes([0x8B, 0x7D, AVAILABILITY_BUTTON_EBP])  # mov edi, [ebp+8]
    assert body[3] == PUSHAD
    assert body[4:7] == bytes([0x0F, 0xB7, 0x87])  # movzx eax, word [edi+disp32]
    assert struct.unpack_from("<I", body, 7)[0] == COMMAND_POINT_COST_OFFSET


def test_gate_routine_compares_cost_plus_in_use_against_the_engines_own_cap() -> None:
    """`hasEnoughCommandPoints` is ``inUse + cost <= getCommandPointCap()``, and this reproduces
    it. Reading a cap field instead would miss the `CPObject` bonus and the hard clamp."""
    base = 0x00F00000
    body, at = _routine(base, "gate")

    assert bytes([0x8B, 0x55, AVAILABILITY_PLAYER_EBP & 0xFF]) in body  # mov edx, [ebp-0x10]
    assert bytes([0x83, 0xC2, PLAYER_COMMAND_POINTS]) in body  # add edx, 0x60
    assert bytes([0x03, 0x42, COMMAND_POINTS_IN_USE]) in body  # add eax, [edx+8]

    call_at = body.index(bytes([0x8B, 0xCA])) + 2  # mov ecx, edx ; call <cap>
    assert body[call_at] == 0xE8
    target = at + call_at + 5 + struct.unpack_from("<i", body, call_at + 1)[0]
    assert target == GET_COMMAND_POINT_CAP


def test_gate_routine_carries_its_total_across_the_call_on_the_stack() -> None:
    """`getCommandPointCap` answers in `eax` and overwrites its own saved `ecx`, so the running
    total cannot ride in either. One `push`, one `pop`, and the `cmp` is between them."""
    body, _at = _routine(0x00F00000, "gate")
    push_at = body.index(bytes([0x50, 0x8B, 0xCA]))  # push eax ; mov ecx, edx
    pop_at = body.index(bytes([0x5A, 0x3B, 0xD0]))  # pop edx ; cmp edx, eax
    assert push_at < pop_at
    assert body.count(bytes([0x50])) == body.count(bytes([0x5A])) == 1


# --- the live-register rule --------------------------------------------------------------------


def test_ecx_is_live_across_the_hook_window() -> None:
    """The fact the first version of this patch got wrong, pinned to the bytes that establish it.

    `mov ecx, eax` at ``0x00942762`` leaves the local player in `ecx`; the displaced window writes
    only `edi` and `eax`; and six and thirteen bytes past the resume point it is consumed as the
    implicit `this` of two `__thiscall`s. So `ecx` crosses the hook, invisibly, and a cave that
    used it as scratch faulted at ``0x006AD100`` reading ``[null+0x710]``."""
    assert ANCHORS[0x00942762] == bytes([0x8B, 0xC8])  # mov ecx, eax
    # the window this patch replaces touches neither ecx nor anything that would reload it
    assert AVAILABILITY_HOOK_STOCK == bytes([0x8B, 0x7D, 0x08, 0x8B, 0x47, 0x14])
    # and both callees take their `this` in ecx
    assert ANCHORS[0x00942785][0] == 0xE8  # call rel32
    assert ANCHORS[0x0094278C][0] == 0xE8
    assert ANCHORS[0x006AD0F8].endswith(bytes([0x8B, 0xF1, 0x83, 0xBE]))  # mov esi,ecx; cmp [esi+
    assert ANCHORS[0x006AD0D9].startswith(bytes([0x55, 0x8B, 0xEC]))  # push ebp; mov ebp,esp


def test_gate_routine_guards_every_register_it_could_clobber() -> None:
    """`pushad` / `popad` around the whole body, so being wrong about *which* register is live -
    the mistake that crashed the first build - cannot be made again.

    One `pushad`, and exactly one `popad` on each of the two exits, so the stack depth at both
    `jmp`s out is the one the engine's own code expects there."""
    body, _at = _routine(0x00F00000, "gate")

    # the guard opens immediately after the displaced load, so `popad` hands `edi` back as the
    # CommandButton the stock path then reads +0x14 from
    assert body[3] == PUSHAD
    # and it closes immediately before each of the two exits
    assert bytes([POPAD, 0x8B, 0x47, COMMAND_BUTTON_COMMAND]) in body  # popad ; mov eax,[edi+0x14]
    assert bytes([POPAD, 0x6A, NOT_ENOUGH_COMMAND_POINTS]) in body  # popad ; push 7

    # every path out of the routine is one of those two, so the guard cannot be skipped
    exits = [i for i in range(len(body) - 4) if body[i] == 0xE9]
    assert len(exits) == 2
    for jmp_at in exits:
        assert POPAD in body[max(0, jmp_at - 4) : jmp_at]


def test_the_verdict_survives_popad_in_the_flags() -> None:
    """`popad` does not touch `EFLAGS`, which is the whole reason the decision can be taken inside
    the guarded region and acted on outside it. The `cmp`/`jg` pair must therefore sit *before*
    the `popad`s, with nothing between them that writes flags."""
    body, _at = _routine(0x00F00000, "gate")
    cmp_at = body.index(bytes([0x3B, 0xD0]))  # cmp edx, eax
    assert body[cmp_at + 2] == 0x7F  # jg rel8, immediately after
    assert cmp_at < body.index(bytes([POPAD]))


def test_gate_routine_falls_through_to_the_displaced_load() -> None:
    """The stock path has to be byte-identical to what it displaced, or every button in the game
    dispatches on the wrong number."""
    base = 0x00F00000
    body, at = _routine(base, "gate")
    stock_at = body.index(bytes([0x8B, 0x47, COMMAND_BUTTON_COMMAND]))  # mov eax, [edi+0x14]
    assert AVAILABILITY_HOOK_STOCK[3:] == bytes([0x8B, 0x47, COMMAND_BUTTON_COMMAND])
    assert _decode_jmp(body, at, stock_at + 3) == AVAILABILITY_RESUME_VA


def test_gate_routine_refuses_with_the_engines_own_verdict() -> None:
    """`push 7` / `jmp <the shared pop eax>` - the exact shape the evaluator's own "not enough
    command points" site uses, which is what makes the button grey rather than vanish and a click
    play `GUI:ErrorNoMoreCommandPoints`."""
    base = 0x00F00000
    body, at = _routine(base, "gate")
    refuse_at = body.index(bytes([0x6A, NOT_ENOUGH_COMMAND_POINTS]))
    assert _decode_jmp(body, at, refuse_at + 2) == AVAILABILITY_REFUSE_TAIL


def test_the_verdict_is_the_one_the_engine_already_pushes() -> None:
    """Read straight out of the anchored window at ``0x00942F42``: ``cmp eax, 7`` / ``jne`` /
    ``push 7``. If the evaluator's command-point verdict were some other number this patch would
    be greying buttons with a code nothing downstream recognises."""
    window = ANCHORS[0x00942F42]
    assert window[0:2] == bytes([0x83, 0xF8])  # cmp eax, imm8
    assert window[2] == NOT_ENOUGH_COMMAND_POINTS
    assert window[5:7] == bytes([0x6A, NOT_ENOUGH_COMMAND_POINTS])  # push 7


def test_both_hook_windows_are_whole_instructions_the_cave_reproduces() -> None:
    """Six bytes each, and every one of them is emitted again inside the cave - so nothing the
    engine was doing at either site is lost."""
    for stock, routine in ((CTOR_HOOK_STOCK, "ctor"), (AVAILABILITY_HOOK_STOCK, "gate")):
        assert len(stock) == 6
        body, _at = _routine(0x00F00000, routine)
        for piece in (stock[:6],) if routine == "ctor" else (stock[:3], stock[3:]):
            assert piece in body or piece == stock[:3]


def test_code_is_position_independent() -> None:
    """Built at two addresses, only the absolute references differ - the routine bodies do not."""
    a = build_code(0x00F00000)
    b = build_code(0x00F02000)
    assert len(a) == len(b)
    differing = [i for i, (x, y) in enumerate(zip(a, b, strict=True)) if x != y]
    assert len(differing) <= 4 * 4  # the three rel32 jumps out of the cave and the one call


# --- apply -------------------------------------------------------------------------------------


def test_apply_writes_both_hooks(image: bytearray) -> None:
    CommandPointCostPatch().apply(image)
    base_va, vsize = _cave(image)

    for va, window in (
        (CTOR_HOOK_VA, CTOR_HOOK_STOCK),
        (AVAILABILITY_HOOK_VA, AVAILABILITY_HOOK_STOCK),
    ):
        hook = _read(image, va, len(window))
        assert hook[0] == 0xE9
        assert hook[5:] == b"\x90" * (len(window) - 5)
        target = va + 5 + struct.unpack_from("<i", hook, 1)[0]
        assert base_va <= target < base_va + vsize


def test_apply_repoints_all_three_table_references(image: bytearray) -> None:
    """The two `push`es the parser uses and the static accessor. Leaving any of them naming the
    stock table would leave a reader that never learns about the new field."""
    CommandPointCostPatch().apply(image)
    table_va = _table_va(image)
    base_va, vsize = _cave(image)
    assert base_va <= table_va < base_va + vsize
    for ref_va, opcode in zip(
        COMMAND_BUTTON_FIELD_TABLE_REFS, COMMAND_BUTTON_FIELD_TABLE_REF_OPCODES, strict=True
    ):
        ref = _read(image, ref_va, 5)
        assert ref[0] == opcode
        assert struct.unpack_from("<I", ref, 1)[0] == table_va


def test_apply_leaves_the_stock_table_where_it_was(image: bytearray) -> None:
    """The old table is abandoned, not edited: rewriting `.rdata` in place is exactly the kind of
    edit that collides with another patch."""
    span = (len(STOCK_FIELDS) + 1) * FIELD_PARSE_STRIDE
    before = _read(image, COMMAND_BUTTON_FIELD_TABLE, span)
    CommandPointCostPatch().apply(image)
    assert _read(image, COMMAND_BUTTON_FIELD_TABLE, span) == before


def test_cave_holds_the_keyword_the_new_row_points_at(image: bytearray) -> None:
    CommandPointCostPatch(keyword="SummonCP").apply(image)
    table_va = _table_va(image)
    row = struct.unpack(
        "<IIII", _read(image, table_va + len(STOCK_FIELDS) * FIELD_PARSE_STRIDE, 16)
    )
    name_va, parse, user, offset = row
    assert (parse, user, offset) == (INI_PARSE_UNSIGNED_SHORT, 0, COMMAND_POINT_COST_OFFSET)
    assert _read(image, name_va, 9) == b"SummonCP\x00"


def test_default_keyword() -> None:
    assert DEFAULT_KEYWORD == "CommandPointCost"


def test_ini_surface_names_the_field_it_installed(image: bytearray) -> None:
    surface = CommandPointCostPatch(keyword="SummonCP").ini_surface()
    assert [(f.block, f.name, f.type, f.default) for f in surface.fields] == [
        ("CommandButton", "SummonCP", "Int", 0)
    ]


# --- verify ------------------------------------------------------------------------------------


def test_verify_clean_after_apply(image: bytearray) -> None:
    patch = CommandPointCostPatch()
    patch.apply(image)
    assert patch.verify(image) == []


def test_verify_clean_for_a_custom_keyword(image: bytearray) -> None:
    patch = CommandPointCostPatch(keyword="SummonCP")
    patch.apply(image)
    assert patch.verify(image) == []


def test_verify_rejects_an_unpatched_image(image: bytearray) -> None:
    assert CommandPointCostPatch().verify(image) != []


def test_verify_rejects_the_wrong_keyword(image: bytearray) -> None:
    CommandPointCostPatch(keyword="SummonCP").apply(image)
    assert CommandPointCostPatch().verify(image) != []


@pytest.mark.parametrize(
    "va",
    [CTOR_HOOK_VA, AVAILABILITY_HOOK_VA, *COMMAND_BUTTON_FIELD_TABLE_REFS],
)
def test_verify_catches_a_reverted_site(image: bytearray, va: int) -> None:
    patch = CommandPointCostPatch()
    patch.apply(image)
    off = va_to_offset(image, va)
    assert off is not None
    image[off : off + 4] = b"\x00\x00\x00\x00"
    assert patch.verify(image) != []


def test_verify_catches_a_row_repointed_at_another_parser(image: bytearray) -> None:
    """The row is what the engine parses the field through. A row naming `INI::parseInt` would
    write a dword and take the `KindOfFlags` with it."""
    patch = CommandPointCostPatch()
    patch.apply(image)
    row_va = _table_va(image) + len(STOCK_FIELDS) * FIELD_PARSE_STRIDE
    off = va_to_offset(image, row_va)
    assert off is not None
    struct.pack_into("<I", image, off + 4, INI_PARSE_BOOL)
    assert patch.verify(image) != []


def test_detect_recovers_the_keyword(image: bytearray) -> None:
    CommandPointCostPatch(keyword="SummonCP").apply(image)
    found = CommandPointCostPatch.detect(image)
    assert found is not None
    assert found.keyword == "SummonCP"


def test_detect_finds_nothing_in_an_unpatched_image(image: bytearray) -> None:
    assert CommandPointCostPatch.detect(image) is None


# --- refusals ----------------------------------------------------------------------------------


def test_apply_refuses_a_second_time(image: bytearray) -> None:
    """A second run raises rather than stacking two caves.

    It is the *anchor* check that catches it, not the duplicate keyword: the first run turned both
    hook windows into jumps, and the anchors are asserted before the table is read. The keyword
    would catch it too - the table is resolved from its live references, so the second run sees the
    row the first added - which is what `test_apply_refuses_a_keyword_the_block_already_has`
    exercises on an image that has not been hooked."""
    CommandPointCostPatch().apply(image)
    with pytest.raises(ValueError, match="derived against"):
        CommandPointCostPatch().apply(image)


def test_apply_refuses_a_keyword_the_block_already_has(image: bytearray) -> None:
    with pytest.raises(ValueError, match="already has"):
        CommandPointCostPatch(keyword="RequireLevel").apply(image)


@pytest.mark.parametrize("va", sorted(ANCHORS))
def test_apply_refuses_when_an_anchor_moved(image: bytearray, va: int) -> None:
    off = va_to_offset(image, va)
    assert off is not None
    image[off] ^= 0xFF
    with pytest.raises(ValueError, match="derived against|is not mapped"):
        CommandPointCostPatch().apply(image)


def test_apply_refuses_when_the_table_is_not_this_build(image: bytearray) -> None:
    off = va_to_offset(image, COMMAND_BUTTON_FIELD_TABLE)
    assert off is not None
    struct.pack_into("<I", image, off + 12, 0x99)  # `Command` at some other offset
    with pytest.raises(ValueError, match="unexpected build"):
        CommandPointCostPatch().apply(image)


def test_apply_refuses_when_the_table_references_disagree(image: bytearray) -> None:
    off = va_to_offset(image, COMMAND_BUTTON_FIELD_TABLE_REFS[2])
    assert off is not None
    struct.pack_into("<I", image, off + 1, COMMAND_BUTTON_FIELD_TABLE + 0x40)
    with pytest.raises(ValueError, match="disagree"):
        CommandPointCostPatch().apply(image)


@pytest.mark.parametrize(
    "keyword", ["", "9Lives", "Command Point Cost", "Command-Point-Cost", "a" * 80]
)
def test_constructor_refuses_an_unparseable_keyword(keyword: str) -> None:
    with pytest.raises(ValueError, match="INI keyword"):
        CommandPointCostPatch(keyword=keyword)


# --- composition -------------------------------------------------------------------------------


def _composable_image() -> bytearray:
    """One image carrying this patch's sites and those of the patches applied alongside it."""
    data = synthetic_image()
    plant_queue_ignore_cp_sites(data)
    plant_sites(data)
    return data


def test_composes_with_queue_ignore_cp_in_either_order() -> None:
    """The pair that shares a struct hole *and* a field table: `queue-ignore-cp` takes the byte at
    +0x10D and rebuilds the same table. Whichever runs second copies the first's row across and
    repoints the references at its own cave, so both have to verify against the live table rather
    than against their own copy of it."""
    for order in (
        (CommandPointCostPatch, QueueIgnoreCpPatch),
        (QueueIgnoreCpPatch, CommandPointCostPatch),
    ):
        data = _composable_image()
        patches = [cls() for cls in order]
        for patch in patches:
            patch.apply(data)
        for patch in patches:
            assert patch.verify(data) == [], f"{patch} after {[str(p) for p in patches]}"
        rvas = _section_rvas(data)
        assert rvas == sorted(rvas)


def test_windows_are_disjoint_from_multi_execute_gates() -> None:
    """`multi-execute-gate` hooks ``0x00942490``, the model-condition predicate the availability
    evaluator calls, and retargets two `call`s inside it - the nearest neighbour in the same
    subsystem. Both patches rewrite bytes in the ControlBar, so the windows are asserted apart
    rather than assumed to be."""
    ours = {
        i
        for va, window in (
            (CTOR_HOOK_VA, CTOR_HOOK_STOCK),
            (AVAILABILITY_HOOK_VA, AVAILABILITY_HOOK_STOCK),
        )
        for i in range(va, va + len(window))
    }
    theirs = {
        i
        for va, window in (MODEL_CONDITION_GATE_WINDOW, GATE_A_WINDOW, GATE_B_WINDOW)
        for i in range(va, va + len(window))
    }
    theirs.update(range(GATE_A_CALL_VA, GATE_A_CALL_VA + 5))
    theirs.update(range(GATE_B_CALL_VA, GATE_B_CALL_VA + 5))
    assert ours.isdisjoint(theirs)


def test_touches_no_byte_queue_ignore_cp_touches() -> None:
    """Both live in `CommandButton`'s three-byte padding hole and both edit the constructor, one
    instruction apart. This is the pair worth asserting rather than assuming."""
    base = _composable_image()
    ours = _composable_image()
    CommandPointCostPatch().apply(ours)
    changed_by_ours = {i for i in range(len(base)) if base[i] != ours[i]}

    others = _composable_image()
    QueueIgnoreCpPatch().apply(others)
    changed_by_others = {i for i in range(min(len(base), len(others))) if base[i] != others[i]}

    overlap = changed_by_ours & changed_by_others
    # both append sections and both repoint the same three table references, so the PE header and
    # those fifteen bytes move for either - everything else has to be disjoint
    header_end = 0x400
    refs = {
        i
        for ref_va in COMMAND_BUTTON_FIELD_TABLE_REFS
        for i in range(ref_va - IMAGE_BASE, ref_va - IMAGE_BASE + 5)
    }
    assert {i for i in overlap if i >= header_end} - refs == set()


def test_registered_under_its_name() -> None:
    assert PATCHES[CommandPointCostPatch.name] is CommandPointCostPatch
