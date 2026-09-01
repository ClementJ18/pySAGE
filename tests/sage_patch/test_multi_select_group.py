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
  `eax` to `winHide` and a non-zero one would hide the window it means to show;
* the seed shim puts back the flags **and** the register the instruction after it reads, neither of
  which a jump would have disturbed;
* the member shim re-derives the message's upgrade from the argument slot rather than from `ebx`,
  which it is about to overwrite; and
* the routine's bytes say what they were meant to say - a wrong displacement assembles, applies
  and verifies, and then jumps into the middle of an instruction in a running game.
"""

from __future__ import annotations

import struct

import pytest

from sage_patch import CommandPointCostPatch, MultiSelectGroupPatch, QueueIgnoreCpPatch
from sage_patch.addresses import (
    AI_GROUP_MEMBER_OBJECT,
    AI_GROUP_UPGRADE_MEMBER,
    AI_GROUP_UPGRADE_MEMBER_BYTES,
    AI_GROUP_UPGRADE_MEMBER_RESUME,
    COMMAND_BUTTON_CTOR_TRIGGER_WHEN_READY,
    COMMAND_BUTTON_CTOR_TRIGGER_WHEN_READY_BYTES,
    COMMAND_BUTTON_FIELD_TABLE,
    COMMAND_BUTTON_FIELD_TABLE_REF_OPCODES,
    COMMAND_BUTTON_FIELD_TABLE_REFS,
    COMMAND_BUTTON_FREE_OFFSET,
    COMMAND_BUTTON_SIZE,
    COMMAND_BUTTON_TRIGGER_WHEN_READY,
    CONTROL_BAR_MERGE_CLEAR_SLOTS,
    CONTROL_BAR_MERGE_HIDE,
    CONTROL_BAR_MERGE_INSTALL,
    CONTROL_BAR_MERGE_INSTALL_FIRST,
    CONTROL_BAR_MERGE_INSTALL_FIRST_RESUME,
    CONTROL_BAR_MERGE_KEEP,
    CONTROL_BAR_MERGE_OBJECT_EBP,
    CONTROL_BAR_MERGE_RESET,
    CONTROL_BAR_MERGE_SLOT,
    FIELD_PARSE_STRIDE,
    INI_PARSE_BOOL,
    INI_PARSE_UNSIGNED_SHORT,
    OBJECT_HAS_UPGRADE,
)
from sage_patch.patches.command_point_cost import COMMAND_POINT_COST_OFFSET
from sage_patch.patches.multi_select_group import (
    ANCHORS,
    AVAILABILITY,
    DEFAULT_KEYWORD,
    HOOK_CALL,
    HOOK_JMP,
    MULTI_SELECT_GROUP_OFFSET,
    ROUTINES,
    SECTION_NAME,
    SLOTS,
    _layout,
    build_code,
    build_table,
    entry_points,
    rewritten_default,
)
from sage_patch.patches.utils.field_tables import entries_before, read_field_table
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

#: `nop`, the padding a short window takes, and `ret`, which the reset routine must not contain.
NOP, RET = 0x90, 0xC3


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


def _routine_va(data: bytes | bytearray, hook_va: int) -> int:
    """Where a routine landed, taken from the jump the engine now takes to reach it."""
    hook = _read(data, hook_va, 5)
    assert hook[0] in (HOOK_JMP, HOOK_CALL)
    return hook_va + 5 + struct.unpack_from("<i", hook, 1)[0]


#: The cave is laid out at a fixed pretend address in the pure-assembly tests, with the scratch
#: area at a second one; neither has to be where the patch really puts them, only distinct.
_CODE_VA, _FLAGS_VA = 0x00F00000, 0x00F10000


def _code() -> bytes:
    return build_code(_CODE_VA, _FLAGS_VA)


def _targets(code: bytes, opcode: int) -> set[int]:
    """Every address a `rel32` of ``opcode`` in ``code`` reaches."""
    return {
        _CODE_VA + i + 5 + struct.unpack_from("<i", code, i + 1)[0]
        for i in range(len(code) - 4)
        if code[i] == opcode
    }


def _entries(data: bytes | bytearray) -> dict[str, int]:
    """Where each routine actually landed in a patched image, recovered the way `verify` does."""
    base_va, _vsize = _cave(data)
    rebuilt = read_field_table(data, _table_va(data))
    preceding = entries_before(data, rebuilt, DEFAULT_KEYWORD)
    assert preceding is not None
    pieces = _layout(base_va, DEFAULT_KEYWORD, len(preceding))
    return entry_points(pieces.code_va, pieces.flags_va)


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


@pytest.mark.parametrize(
    ("hook_va", "routine", "pad", "opcode"),
    [
        (CONTROL_BAR_MERGE_SLOT, "merge", 3, HOOK_JMP),
        (CONTROL_BAR_MERGE_RESET, "reset", 0, HOOK_CALL),
        (CONTROL_BAR_MERGE_INSTALL_FIRST, "seed", 1, HOOK_JMP),
        (AI_GROUP_UPGRADE_MEMBER, "member", 1, HOOK_JMP),
    ],
)
def test_each_hook_is_a_padded_branch(
    image: bytearray, hook_va: int, routine: str, pad: int, opcode: int
) -> None:
    """Every window is a whole number of instructions, so the branch plus its `nop` leaves nothing
    partial for the surrounding code to fall into."""
    MultiSelectGroupPatch().apply(image)
    window = ANCHORS[hook_va]
    blob = _read(image, hook_va, len(window))
    assert blob[0] == opcode
    assert blob[5:] == bytes([NOP]) * pad
    assert _routine_va(image, hook_va) == _entries(image)[routine]


def test_a_hook_keeps_the_branch_kind_its_site_had() -> None:
    """**The bug this test exists for.** `0x00944853` is a `call`, and its routine ends by
    tail-calling the callee that `call` named - so that callee's `ret` is what returns to the
    instruction after the site. Patching it as a `jmp` leaves nothing for the `ret` to pop, and the
    engine returns into garbage the first time a player selects more than one unit. It applies
    cleanly, it verifies, and it crashes.

    So the rule is checked against the site's own stock bytes rather than against the table: a
    window whose stock instruction is `call rel32` must be patched with `call rel32`."""
    for hook_va, (stock, _routine, opcode) in MultiSelectGroupPatch._HOOKS.items():
        assert opcode == (HOOK_CALL if stock[0] == HOOK_CALL else HOOK_JMP), hex(hook_va)


def test_the_reset_routine_tail_calls_rather_than_returning() -> None:
    """The other half of the same rule: the routine the `call` site reaches must **not** `ret` -
    it hands off to the helper with a `jmp`, and the helper returns for it."""
    code = _code()
    reset = entry_points(_CODE_VA, _FLAGS_VA)["reset"] - _CODE_VA
    stores = (SLOTS + 3) // 4
    end = reset + stores * 10
    assert code[end] == HOOK_JMP
    assert code[reset:end].count(bytes([RET])) == 0  # no ret anywhere in the body


def test_every_routine_is_reachable_and_distinct() -> None:
    """`entry_points` is what `apply` and `verify` both site the hooks from, so a duplicate or a
    stale name there would point two hooks at one routine and neither would notice."""
    entries = entry_points(_CODE_VA, _FLAGS_VA)
    assert set(entries) == set(ROUTINES)
    assert len(set(entries.values())) == len(ROUTINES)
    assert all(_CODE_VA <= va < _CODE_VA + len(_code()) for va in entries.values())


def _branch_target(code: bytes, at: int) -> int:
    """Where the `jcc rel32` whose opcode pair starts at ``at`` lands, following one `jmp` hop.

    The cave's exits are labels that each hold a single `jmp` to the engine, so a `jcc` aimed at
    `keep` or `hide` reaches the engine one instruction later. Following that hop is what lets a
    test say "this branch means KEEP" rather than "this branch goes somewhere in the cave"."""
    assert code[at] == 0x0F and 0x80 <= code[at + 1] <= 0x8F
    landed = _CODE_VA + at + 6 + struct.unpack_from("<i", code, at + 2)[0]
    offset = landed - _CODE_VA
    if 0 <= offset < len(code) - 4 and code[offset] == HOOK_JMP:
        return _CODE_VA + offset + 5 + struct.unpack_from("<i", code, offset + 1)[0]
    return landed


def test_a_slot_only_one_set_fills_is_filled_rather_than_blanked() -> None:
    """The union half of the rule, and the one part not gated on the new field: a set that says
    nothing about a slot is not in conflict with one that does.

    `test edi, edi` (this set has no button) must reach `KEEP`, so the installed one stands, and
    `test eax, eax` (nothing installed) must reach the adopt arm rather than `HIDE`. Stock sends
    both to the clear-and-hide, which is what puts an empty socket under a button only half the
    selection owns."""
    code = _code()
    merge = entry_points(_CODE_VA, _FLAGS_VA)["merge"] - _CODE_VA
    no_button = code.index(bytes([0x85, 0xFF]), merge)  # test edi, edi
    nothing_installed = code.index(bytes([0x85, 0xC0]), no_button)  # test eax, eax
    assert _branch_target(code, no_button + 2) == CONTROL_BAR_MERGE_KEEP
    adopt = _branch_target(code, nothing_installed + 2)
    assert adopt not in (CONTROL_BAR_MERGE_HIDE, CONTROL_BAR_MERGE_KEEP)
    assert _CODE_VA <= adopt < _CODE_VA + len(code)


def test_the_adopt_arm_re_tests_ok_for_multi_select() -> None:
    """The first-object pass gates on `OK_FOR_MULTI_SELECT` at `0x009445DA` before it installs
    anything, and the adopt arm bypasses that pass entirely - so it has to ask again, or the union
    would put buttons in a group bar that are not meant to appear in one."""
    code = _code()
    merge = entry_points(_CODE_VA, _FLAGS_VA)["merge"] - _CODE_VA
    nothing_installed = code.index(bytes([0x85, 0xC0]), code.index(bytes([0x85, 0xFF]), merge))
    adopt = _branch_target(code, nothing_installed + 2) - _CODE_VA
    assert code[adopt : adopt + 4] == bytes([0xF6, 0x47, 0x1D, 0x01])  # test byte [edi+0x1d], 1
    assert _branch_target(code, adopt + 4) == CONTROL_BAR_MERGE_HIDE


def test_the_adopt_arm_zeroes_eax_after_asking_availability() -> None:
    """It arrives with `eax` already the NULL the install arm wants to hand to `winHide`, but
    `avail` returns its answer there - so the zero has to be re-established, not assumed."""
    code = _code()
    merge = entry_points(_CODE_VA, _FLAGS_VA)["merge"] - _CODE_VA
    nothing_installed = code.index(bytes([0x85, 0xC0]), code.index(bytes([0x85, 0xFF]), merge))
    adopt = _branch_target(code, nothing_installed + 2) - _CODE_VA
    body = code[adopt : adopt + 0x28]
    assert bytes([0x33, 0xC0]) in body  # xor eax, eax
    assert body.index(bytes([0x33, 0xC0])) < body.index(bytes([0xE9]))  # before the jmp to INSTALL


def test_the_merge_reproduces_both_displaced_tests() -> None:
    """The identity compare and the `ATTACK_MOVE` flag test are the two things the hook displaced.
    If either were dropped, every slot in every mixed selection would go through the new code."""
    code = _code()
    merge = entry_points(_CODE_VA, _FLAGS_VA)["merge"] - _CODE_VA
    assert code[merge : merge + 2] == b"\x3b\xf8"  # cmp edi, eax
    assert code[merge + 8 : merge + 10] == b"\x84\xc9"  # test cl, cl


def test_the_cave_jumps_only_where_the_engine_expects_it_back() -> None:
    """`KEEP`, `HIDE` and `INSTALL` are the arms the merge loop already has; the cave adds no
    fourth, and the other three are the resume points of the other three hooks.

    Like `explore.py xref`, the scan decodes a `rel32` at **every** byte rather than sweeping
    instruction by instruction, so it cannot miss a jump - at the cost of the occasional `0xE9`
    that is really some other instruction's displacement. Those decode to addresses nowhere near
    the image, which is why the assertion is over the plausible ones."""
    expected = {
        CONTROL_BAR_MERGE_KEEP,
        CONTROL_BAR_MERGE_HIDE,
        CONTROL_BAR_MERGE_INSTALL,
        CONTROL_BAR_MERGE_CLEAR_SLOTS,
        CONTROL_BAR_MERGE_INSTALL_FIRST_RESUME,
        AI_GROUP_UPGRADE_MEMBER_RESUME,
    }
    code = _code()
    outside = {va for va in _targets(code, 0xE9) if not _CODE_VA <= va < _CODE_VA + len(code)}
    assert expected <= outside
    assert {va for va in outside if IMAGE_BASE <= va < _CODE_VA} == expected


def test_eax_is_zeroed_before_the_install_arm() -> None:
    """`0x00944704` stores `edi` into the slot and then calls `winHide(eax)`. Re-entering it with
    the installed button still in `eax` would hide the very window it means to show, so the two
    bytes before that jump are `xor eax, eax` - and this is the one property of the routine that a
    running game would punish and no structural check would notice."""
    code = _code()
    index = next(
        i
        for i in range(len(code) - 4)
        if code[i] == 0xE9
        and _CODE_VA + i + 5 + struct.unpack_from("<i", code, i + 1)[0] == CONTROL_BAR_MERGE_INSTALL
    )
    assert code[index - 2 : index] == b"\x33\xc0"  # xor eax, eax


def test_the_seed_restores_the_flags_the_resume_point_branches_on(image: bytearray) -> None:
    """`cmp ecx, esi` two bytes before the seed hook is what the `je` at the resume point reads.
    `popad` puts `ecx` back and leaves EFLAGS alone, so the compare is re-issued - the last two
    instructions of the routine, in that order."""
    assert _read(image, CONTROL_BAR_MERGE_INSTALL_FIRST - 2, 2) == b"\x3b\xce"  # cmp ecx, esi
    code = _code()
    seed = entry_points(_CODE_VA, _FLAGS_VA)["seed"] - _CODE_VA
    tail = code[seed : seed + 0x40]
    assert bytes([POPAD, 0x3B, 0xCE, 0xE9]) in tail  # popad ; cmp ecx, esi ; jmp <resume>


def test_the_reset_clears_the_whole_record_then_tail_calls() -> None:
    """One `mov dword [flags+n], 0` per four slots, covering all 33, and then the helper the hook
    displaced - a `jmp`, not a `call`, so the helper returns to the engine's own caller."""
    code = _code()
    reset = entry_points(_CODE_VA, _FLAGS_VA)["reset"] - _CODE_VA
    stores = [_FLAGS_VA + n for n in range(0, (SLOTS + 3) & ~3, 4)]
    for index, flags_va in enumerate(stores):
        want = bytes([0xC7, 0x05]) + struct.pack("<II", flags_va, 0)
        assert code[reset + index * 10 : reset + (index + 1) * 10] == want
    end = reset + len(stores) * 10
    assert code[end] == 0xE9
    assert (
        _CODE_VA + end + 5 + struct.unpack_from("<i", code, end + 1)[0]
        == CONTROL_BAR_MERGE_CLEAR_SLOTS
    )


def test_the_member_hook_rewrites_ebx_from_the_untouched_argument() -> None:
    """The stock loop carries the message's upgrade in `ebx`. The shim re-derives it from
    `[ebp+8]` - which the function never writes - so each member is resolved from the message
    rather than from whatever the previous member was given."""
    code = _code()
    member = entry_points(_CODE_VA, _FLAGS_VA)["member"] - _CODE_VA
    body = code[member : member + 0x20]
    assert body.startswith(bytes([0x8B, 0x7E, AI_GROUP_MEMBER_OBJECT]))  # mov edi, [esi+8]
    assert bytes([0xFF, 0x75, 0x08]) in body  # push [ebp+8]
    assert bytes([0x8B, 0xD8]) in body  # mov ebx, eax
    assert bytes([0x6A, 0x00, 0x57]) in body  # the two displaced pushes, in order


def test_the_displaced_pushes_are_re_emitted_in_order() -> None:
    """`push 0` then `push edi` are two of the three instructions the member hook displaced, and
    the callee behind the resume point reads them as its arguments. Emitting them in the other
    order would pass the member as the flag and vice versa."""
    assert AI_GROUP_UPGRADE_MEMBER_BYTES.endswith(bytes([0x6A, 0x00, 0x57]))
    assert AI_GROUP_UPGRADE_MEMBER + len(AI_GROUP_UPGRADE_MEMBER_BYTES) == (
        AI_GROUP_UPGRADE_MEMBER_RESUME
    )


def test_availability_is_asked_with_a_null_window() -> None:
    """The click executor passes a NULL window at `0x009405B0`, so the cave does too rather than
    reaching for a window pointer that may not exist. `arg2` is the `push 0` between the object and
    the button."""
    code = _code()
    avail = entry_points(_CODE_VA, _FLAGS_VA)["avail"] - _CODE_VA
    body = code[avail : avail + 0x40]
    assert bytes([0xFF, 0x75, 0x0C, 0x6A, 0x00, 0xFF, 0x75, 0x08]) in body
    assert AVAILABILITY in _targets(code, 0xE8)


def test_the_upgrade_query_is_bracketed_by_pushad() -> None:
    """Every register in the merge loop is live across the call, and the callee's own clobbers are
    not this patch's to know. `popad` leaves EFLAGS alone, which is what carries the answer out."""
    code = _code()
    index = code.find(bytes([PUSHAD, 0x52, 0x8B, 0x4D, CONTROL_BAR_MERGE_OBJECT_EBP & 0xFF, 0xE8]))
    assert index >= 0, "the routine does not push the object and call through a guard"
    assert bytes([0x84, 0xC0, POPAD]) in code[index : index + 32]  # test al, al ; popad


def test_the_upgrade_query_calls_the_engine_predicate() -> None:
    assert OBJECT_HAS_UPGRADE in _targets(_code(), 0xE8)


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
