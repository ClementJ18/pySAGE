"""Tests for the multi-select-group patch.

The structural checks are the usual ones - the cave's layout, the edits, the round trip through
`verify`. The rest hold the properties the patch's correctness actually rests on, none of which
"it applies cleanly" would catch:

* the new field lands in the *second* of `CommandButton`'s two alignment holes, so ``sizeof``
  never has to change and neither `queue-ignore-cp` nor `command-point-cost` loses its own byte;
* the widened constructor store really does zero those bytes and really does leave
  `TriggerWhenReady` at `No`, since `operator new` does not zero the block;
* the rebuilt table keeps the live rows *verbatim*, because their name pointers are absolute;
* the cave reproduces **both** stock tests it displaced, so an ungrouped pair still takes the path
  it always did and the `ATTACK_MOVE` exemption still exempts;
* `eax` is zeroed on the one path that re-enters the engine's install arm, because that arm hands
  `eax` to `winHide` and a non-zero one would hide the window it means to show; and
* the routine's bytes say what they were meant to say - a wrong displacement assembles, applies
  and verifies, and then jumps into the middle of an instruction in a running game.
"""

from __future__ import annotations

import struct

import pytest

from sage_patch import CommandPointCostPatch, MultiSelectGroupPatch, QueueIgnoreCpPatch
from sage_patch.addresses import (
    COMMAND_BUTTON_CTOR_TRIGGER_WHEN_READY,
    COMMAND_BUTTON_CTOR_TRIGGER_WHEN_READY_BYTES,
    COMMAND_BUTTON_FIELD_TABLE,
    COMMAND_BUTTON_FIELD_TABLE_REF_OPCODES,
    COMMAND_BUTTON_FIELD_TABLE_REFS,
    COMMAND_BUTTON_FREE_OFFSET,
    COMMAND_BUTTON_SIZE,
    COMMAND_BUTTON_TRIGGER_WHEN_READY,
    CONTROL_BAR_MERGE_HIDE,
    CONTROL_BAR_MERGE_INSTALL,
    CONTROL_BAR_MERGE_KEEP,
    CONTROL_BAR_MERGE_OBJECT_EBP,
    CONTROL_BAR_MERGE_SLOT,
    CONTROL_BAR_MERGE_SLOT_BYTES,
    FIELD_PARSE_STRIDE,
    INI_PARSE_BOOL,
    INI_PARSE_UNSIGNED_SHORT,
    OBJECT_HAS_UPGRADE,
)
from sage_patch.patches.command_point_cost import COMMAND_POINT_COST_OFFSET
from sage_patch.patches.multi_select_group import (
    ANCHORS,
    DEFAULT_KEYWORD,
    MULTI_SELECT_GROUP_OFFSET,
    SECTION_NAME,
    build_code,
    build_table,
    entry_points,
    rewritten_default,
)
from sage_patch.registry import PATCHES
from sage_patch.utils import find_section, va_to_offset
from tests.sage_patch.test_command_point_cost import plant_sites as plant_command_point_cost_sites
from tests.sage_patch.test_queue_ignore_cp import STOCK_FIELDS, _string_vas
from tests.sage_patch.test_queue_ignore_cp import plant_sites as plant_queue_ignore_cp_sites
from tests.sage_patch.test_terrain_resource_exp import _pe32

IMAGE_BASE = 0x400000

#: Where the shared `CommandButton` planting helper parks the field-name strings.
STRINGS_VA = 0x00C31000

#: Byte widths for the offsets `STOCK_FIELDS` names, so a test can prove the new field's two bytes
#: are claimed by none of them. Everything not listed is a dword or larger.
_WIDTHS = {0x100: 1, 0x101: 1, 0x102: 1, 0x104: 1, 0x105: 1, 0x106: 1, 0x107: 1, 0x10C: 1, 0x12C: 1}

#: `pushad` / `popad`, the guard the routine brackets its one engine call with. Asserted as part of
#: a whole sequence rather than as bare bytes, because either can turn up inside a `rel32`.
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


def _routine_va(data: bytes | bytearray) -> int:
    """Where the merge routine landed, taken from the jump the engine now takes to reach it."""
    hook = _read(data, CONTROL_BAR_MERGE_SLOT, 5)
    assert hook[0] == 0xE9
    return CONTROL_BAR_MERGE_SLOT + 5 + struct.unpack_from("<i", hook, 1)[0]


def _jmp(from_va: int, to_va: int) -> bytes:
    return b"\xe9" + struct.pack("<i", to_va - (from_va + 5))


def test_new_field_lands_in_alignment_padding() -> None:
    """The two bytes the patch uses are inside the struct and claimed by no stock field.

    This is what the whole patch rests on: if it did not hold, `sizeof(CommandButton)` and the
    `operator new(0x2E0)` that allocates it would both have to grow."""
    claimed: set[int] = set()
    for _name, offset in STOCK_FIELDS:
        claimed.update(range(offset, offset + _WIDTHS.get(offset, 4)))
    ours = set(range(MULTI_SELECT_GROUP_OFFSET, MULTI_SELECT_GROUP_OFFSET + 2))
    assert ours.isdisjoint(claimed)
    assert max(ours) < COMMAND_BUTTON_SIZE


def test_new_field_is_word_aligned() -> None:
    """`INI::parseUnsignedShort` does `mov word [store], ax`, so a misaligned home would be a split
    store across the `PresetRange` boundary rather than a slow one."""
    assert MULTI_SELECT_GROUP_OFFSET % 2 == 0


def test_new_field_sits_between_its_two_neighbours() -> None:
    """The hole is bounded below by the `Bool` the constructor's widened store defaults and above
    by the `Real` the next instruction writes. Both bounds have to hold for the widening to be
    six bytes for six."""
    fields = dict(STOCK_FIELDS)
    assert fields["TriggerWhenReady"] == COMMAND_BUTTON_TRIGGER_WHEN_READY
    assert COMMAND_BUTTON_TRIGGER_WHEN_READY < MULTI_SELECT_GROUP_OFFSET
    assert MULTI_SELECT_GROUP_OFFSET + 2 <= fields["PresetRange"]


def test_the_field_collides_with_neither_other_commandbutton_patch() -> None:
    """Three patches now add a `CommandButton` field. `queue-ignore-cp` takes the byte at +0x10D
    and `command-point-cost` the word at +0x10E, both in the first hole; this one takes the word in
    the second. All three have to be applicable together."""
    ours = set(range(MULTI_SELECT_GROUP_OFFSET, MULTI_SELECT_GROUP_OFFSET + 2))
    theirs = {COMMAND_BUTTON_FREE_OFFSET} | set(
        range(COMMAND_POINT_COST_OFFSET, COMMAND_POINT_COST_OFFSET + 2)
    )
    assert ours.isdisjoint(theirs)


def test_the_allocation_size_is_asserted_and_never_written(image: bytearray) -> None:
    """A field in the padding is only free while the allocation is the size it is, so the
    `push 0x2E0` is anchored - and it is still there afterwards."""
    alloc_va = 0x0071C446
    assert ANCHORS[alloc_va] == bytes([0x68]) + struct.pack("<I", COMMAND_BUTTON_SIZE)
    before = _read(image, alloc_va, 5)
    MultiSelectGroupPatch().apply(image)
    assert _read(image, alloc_va, 5) == before


def test_the_default_is_a_one_byte_widening(image: bytearray) -> None:
    """`0x88` is `mov r/m8, r8` and `0x89` is `mov r/m32, r32`; the ModRM and displacement are
    untouched. Six bytes for six is what lets the field be defaulted with no cave and no displaced
    instruction."""
    widened = rewritten_default()
    assert len(widened) == len(COMMAND_BUTTON_CTOR_TRIGGER_WHEN_READY_BYTES)
    assert COMMAND_BUTTON_CTOR_TRIGGER_WHEN_READY_BYTES[0] == 0x88
    assert widened[0] == 0x89
    assert widened[1:] == COMMAND_BUTTON_CTOR_TRIGGER_WHEN_READY_BYTES[1:]
    differing = [
        index
        for index, (new, old) in enumerate(
            zip(widened, COMMAND_BUTTON_CTOR_TRIGGER_WHEN_READY_BYTES, strict=True)
        )
        if new != old
    ]
    assert differing == [0]
    MultiSelectGroupPatch().apply(image)
    assert _read(image, COMMAND_BUTTON_CTOR_TRIGGER_WHEN_READY, len(widened)) == widened


def test_the_widened_store_covers_the_whole_field() -> None:
    """A dword written at `TriggerWhenReady` reaches the top of the hole, so both bytes of the
    field are zeroed and nothing past `PresetRange` is."""
    covered = set(range(COMMAND_BUTTON_TRIGGER_WHEN_READY, COMMAND_BUTTON_TRIGGER_WHEN_READY + 4))
    assert set(range(MULTI_SELECT_GROUP_OFFSET, MULTI_SELECT_GROUP_OFFSET + 2)) <= covered
    assert max(covered) < dict(STOCK_FIELDS)["PresetRange"]


def test_table_keeps_the_live_rows_verbatim() -> None:
    entries = _live_entries()
    table = build_table(entries, 0x00F00000)
    for index, entry in enumerate(entries):
        assert struct.unpack_from("<IIII", table, index * FIELD_PARSE_STRIDE) == entry


def test_table_appends_the_new_row_and_a_terminator() -> None:
    entries = _live_entries()
    keyword_va = 0x00F00000
    table = build_table(entries, keyword_va)
    assert len(table) == (len(entries) + 2) * FIELD_PARSE_STRIDE
    row = struct.unpack_from("<IIII", table, len(entries) * FIELD_PARSE_STRIDE)
    assert row == (keyword_va, INI_PARSE_UNSIGNED_SHORT, 0, MULTI_SELECT_GROUP_OFFSET)
    assert table[-FIELD_PARSE_STRIDE:] == bytes(FIELD_PARSE_STRIDE)


def test_every_table_reference_is_repointed(image: bytearray) -> None:
    MultiSelectGroupPatch().apply(image)
    base_va, _vsize = _cave(image)
    for ref_va, opcode in zip(
        COMMAND_BUTTON_FIELD_TABLE_REFS, COMMAND_BUTTON_FIELD_TABLE_REF_OPCODES, strict=True
    ):
        blob = _read(image, ref_va, 5)
        assert blob[0] == opcode
        assert struct.unpack_from("<I", blob, 1)[0] > base_va


def test_the_hook_is_a_padded_jump(image: bytearray) -> None:
    """The window is eight bytes and four whole instructions, so the jump takes three trailing
    `nop` - nothing partial is left behind for the loop to fall into."""
    assert len(CONTROL_BAR_MERGE_SLOT_BYTES) == 8
    MultiSelectGroupPatch().apply(image)
    blob = _read(image, CONTROL_BAR_MERGE_SLOT, len(CONTROL_BAR_MERGE_SLOT_BYTES))
    assert blob[0] == 0xE9
    assert blob[5:] == b"\x90" * 3
    assert _routine_va(image) == entry_points(_routine_va(image))["merge"]


def test_the_routine_reproduces_both_displaced_tests() -> None:
    """The identity compare and the `ATTACK_MOVE` flag test are the two things the hook displaced.
    If either were dropped, every slot in every mixed selection would go through the new code."""
    code = build_code(0x00F00000)
    assert code.startswith(b"\x3b\xf8")  # cmp edi, eax
    assert b"\x84\xc9" in code  # test cl, cl


def test_the_routine_reaches_all_three_continuations() -> None:
    """`KEEP`, `HIDE` and `INSTALL` are the loop's own arms; the routine adds no fourth."""
    code_va = 0x00F00000
    code = build_code(code_va)
    targets = set()
    for index in range(len(code) - 4):
        if code[index] == 0xE9:
            targets.add(code_va + index + 5 + struct.unpack_from("<i", code, index + 1)[0])
    outside = {va for va in targets if not code_va <= va < code_va + len(code)}
    assert outside == {CONTROL_BAR_MERGE_KEEP, CONTROL_BAR_MERGE_HIDE, CONTROL_BAR_MERGE_INSTALL}


def test_eax_is_zeroed_before_the_install_arm() -> None:
    """`0x00944704` stores `edi` into the slot and then calls `winHide(eax)`. Re-entering it with
    the installed button still in `eax` would hide the very window it means to show, so the two
    bytes before that jump are `xor eax, eax` - and this is the one property of the routine that a
    running game would punish and no structural check would notice."""
    code_va = 0x00F00000
    code = build_code(code_va)
    index = -1
    for candidate in range(len(code) - 4):
        if code[candidate] != 0xE9:
            continue
        target = code_va + candidate + 5 + struct.unpack_from("<i", code, candidate + 1)[0]
        if target == CONTROL_BAR_MERGE_INSTALL:
            index = candidate
            break
    assert index > 0, "the routine never reaches the install arm"
    assert code[index - 2 : index] == b"\x33\xc0"  # xor eax, eax


def test_the_upgrade_query_is_bracketed_by_pushad() -> None:
    """Every register in the merge loop is live across the call, and the callee's own clobbers are
    not this patch's to know. `popad` leaves EFLAGS alone, which is what carries the answer out."""
    code = build_code(0x00F00000)
    call = struct.pack("<B", 0xE8)
    index = code.find(bytes([PUSHAD, 0x52, 0x8B, 0x4D, CONTROL_BAR_MERGE_OBJECT_EBP & 0xFF]) + call)
    assert index >= 0, "the routine does not push the object and call through a guard"
    tail = code[index : index + 32]
    assert bytes([0x84, 0xC0, POPAD]) in tail  # test al, al ; popad


def test_the_upgrade_query_calls_the_engine_predicate() -> None:
    code_va = 0x00F00000
    code = build_code(code_va)
    calls = {
        code_va + i + 5 + struct.unpack_from("<i", code, i + 1)[0]
        for i in range(len(code) - 4)
        if code[i] == 0xE8
    }
    assert OBJECT_HAS_UPGRADE in calls


def test_apply_then_verify_round_trips(image: bytearray) -> None:
    patch = MultiSelectGroupPatch()
    patch.apply(image)
    assert patch.verify(image) == []


def test_verify_fails_on_an_unpatched_image(image: bytearray) -> None:
    assert MultiSelectGroupPatch().verify(image) != []


def test_detect_recovers_a_custom_keyword(image: bytearray) -> None:
    MultiSelectGroupPatch(keyword="SharedSlot").apply(image)
    found = MultiSelectGroupPatch.detect(image)
    assert found is not None
    assert found.keyword == "SharedSlot"


def test_the_default_keyword_is_the_documented_one() -> None:
    assert DEFAULT_KEYWORD == "MultiSelectGroup"


def test_verify_rejects_a_different_keyword(image: bytearray) -> None:
    MultiSelectGroupPatch(keyword="SharedSlot").apply(image)
    assert MultiSelectGroupPatch().verify(image) != []


def test_applying_twice_raises(image: bytearray) -> None:
    MultiSelectGroupPatch().apply(image)
    with pytest.raises(ValueError, match="expected"):
        MultiSelectGroupPatch().apply(image)


def test_a_bad_keyword_is_refused() -> None:
    with pytest.raises(ValueError, match="INI keyword"):
        MultiSelectGroupPatch(keyword="Multi Select Group")


def test_ini_surface_names_the_installed_keyword() -> None:
    surface = MultiSelectGroupPatch(keyword="SharedSlot").ini_surface()
    (field,) = surface.fields
    assert (field.block, field.name, field.type, field.default) == (
        "CommandButton",
        "SharedSlot",
        "Int",
        0,
    )


def test_the_patch_is_registered() -> None:
    assert PATCHES[MultiSelectGroupPatch.name] is MultiSelectGroupPatch


@pytest.mark.parametrize(
    "order",
    [
        (MultiSelectGroupPatch, CommandPointCostPatch, QueueIgnoreCpPatch),
        (CommandPointCostPatch, QueueIgnoreCpPatch, MultiSelectGroupPatch),
        (QueueIgnoreCpPatch, MultiSelectGroupPatch, CommandPointCostPatch),
    ],
)
def test_the_three_commandbutton_patches_compose_in_any_order(order: tuple[type, ...]) -> None:
    """All three rebuild the same field table and all three read it live, so each one's row
    survives the next one's rebuild whichever way round they are applied."""
    data = _pe32(
        max(
            STRINGS_VA + sum(len(name) + 1 for name, _ in STOCK_FIELDS),
            COMMAND_BUTTON_FIELD_TABLE + (len(STOCK_FIELDS) + 1) * FIELD_PARSE_STRIDE,
            max(va + len(blob) for va, blob in ANCHORS.items()),
            0x00C40000,
        )
    )
    plant_queue_ignore_cp_sites(data)
    plant_command_point_cost_sites(data)
    plant_sites(data)
    for cls in order:
        cls().apply(data)
    for cls in order:
        assert cls().verify(data) == [], cls.__name__
