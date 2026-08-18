"""Tests for the `HEROBAR` / `HEROBAR_GROUP` kindof patch.

Three kinds of thing are checked here, and only the first is ordinary code.

**The table move** is mechanical and testable directly: every stock kindof has to come through
the rebuild with both its index and its original string, all fourteen references have to point at
the copy, and all six counts have to agree with it.

**The cave** is hand-encoded x86 that cannot be executed in a test, so the tests that matter
disassemble it back and assert it says what it was meant to say. A wrong byte does not raise - it
crashes the game, or marks the wrong slot, or selects the wrong units.

**The invariants of the target build** the patch quietly depends on: that the kindof mask has room
for two more bits at all, and that the byte-and-mask form this patch emits for a kindof test is
byte-identical to the one the engine already uses for `HERO` at the site being replaced. Neither
is visible from the code that relies on it, and both are the reason the patch is as small as it is.

The patch adds **two kindofs in one application**, and which of the two an object carries is a
runtime question rather than a build-time one. So what the tests have to separate is not two
binaries but two bits: every hook reads *either* kindof for membership, and only the draw loop
narrows to the grouping one.
"""

from __future__ import annotations

import struct

import pytest

from sage_patch.patches.herobar import (
    DEFAULT_GROUP_KINDOF,
    DEFAULT_JUMP_WINDOW,
    DEFAULT_KINDOF,
    GROUPED_HEROBAR,
    HERO_BIT,
    HOOKS,
    MAX_JUMP_WINDOW,
    SECTION_NAME,
    STATE_SIZE,
    TOOLTIP_EDIT,
    Cave,
    HeroBarPatch,
    build_cave,
)
from sage_patch.patches.production_condition import ProductionConditionPatch
from sage_patch.patches.utils import kind_of
from sage_patch.utils import find_section, va_to_offset
from tests.sage_patch.synthetic import stock_kindof_name, synthetic_image

BASE = 0x00F00000
BIT = kind_of.STOCK_KIND_COUNT
GROUP_BIT = kind_of.STOCK_KIND_COUNT + 1

#: How capstone renders the two bit tests the cave emits, one per added kindof. Bits 222 and 223
#: share a byte - `0x108 + 222/8` - and differ only in the mask.
IS_HEROBAR = "byte ptr [eax + 0x123], 0x40"
IS_GROUP = "byte ptr [eax + 0x123], 0x80"

#: `appendObjectIDArgument` and `findObjectByID`, as capstone renders their call targets.
APPEND_OBJECT_ID = "0x71111a"
FIND_OBJECT_BY_ID = "0x449681"


@pytest.fixture(scope="module")
def clean() -> bytearray:
    """Built once - the image is a few MB and every test only reads or copies it."""
    return synthetic_image()


@pytest.fixture
def patched(clean: bytearray) -> bytearray:
    data = bytearray(clean)
    HeroBarPatch().apply(data)
    return data


def _u32(data: bytes | bytearray, va: int) -> int:
    off = va_to_offset(data, va)
    assert off is not None
    return struct.unpack_from("<I", data, off)[0]


def _bytes_at(data: bytes | bytearray, va: int, size: int) -> bytes:
    off = va_to_offset(data, va)
    assert off is not None
    return bytes(data[off : off + size])


def _cave_base(data: bytes | bytearray) -> int:
    """Where the cave's own content begins: past the rebuilt table and the two new names.

    The names are padded once, as a run, which is what the patch's own `_padded` is called with
    the summed length for."""
    located = find_section(data, SECTION_NAME)
    assert located is not None
    entries = kind_of.STOCK_KIND_COUNT + 2
    names = len(DEFAULT_KINDOF) + 1 + len(DEFAULT_GROUP_KINDOF) + 1
    return located[0] + (entries + 1) * 4 + names + (-names % 4)


def _cave(data: bytes | bytearray) -> tuple[int, Cave]:
    """The cave this image carries, and the VA it was built at."""
    base = _cave_base(data)
    return base, build_cave(base, BIT, GROUP_BIT)


def _disassemble(data: bytes | bytearray, va: int, size: int) -> list:
    capstone = pytest.importorskip("capstone")
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    return list(md.disasm(_bytes_at(data, va, size), va))


def _routine_ins(data: bytes | bytearray, label: str) -> list:
    """One cave routine, disassembled from its entry to the next one (or the end of the cave)."""
    base, cave = _cave(data)
    start = cave.entries[label]
    after = [va for va in cave.entries.values() if va > start]
    end = min(after) if after else base + len(cave.content)
    return _disassemble(data, start, end - start)


def _routine(data: bytes | bytearray, label: str) -> list[tuple[str, str]]:
    return [(i.mnemonic, i.op_str) for i in _routine_ins(data, label)]


def test_the_mask_has_room_for_both_kindofs() -> None:
    """The whole patch is affordable because of this. 222 names in a 224-bit mask means the two
    new bits need no `ThingTemplate` growth and no savegame length change - and they are the last
    two, which is why one patch adds both rather than leaving a bit for a second application."""
    assert kind_of.STOCK_KIND_COUNT + 2 == kind_of.MASK_DWORDS * 32
    assert kind_of.MASK_BYTES == 0x1C


def test_the_emitted_bit_test_matches_the_engines_own() -> None:
    """`bit_test` has to reproduce the engine's encoding exactly, because the classify hook
    re-executes the `HERO` test it displaced. If the two forms differed, the displaced original
    bytes asserted at the hook site would not be the ones the cave re-emits."""
    hook = next(h for h in HOOKS if h.label == "classify")
    assert kind_of.bit_test(HERO_BIT, 0, kind_of.THING_TEMPLATE_MASK_OFFSET) == hook.original


def test_both_bit_tests_land_in_the_last_dword_of_the_mask() -> None:
    for bit, mask in ((BIT, 0x40), (GROUP_BIT, 0x80)):
        encoded = kind_of.bit_test(bit, 0, kind_of.THING_TEMPLATE_MASK_OFFSET)
        displacement = struct.unpack_from("<I", encoded, 2)[0]
        assert displacement == kind_of.THING_TEMPLATE_MASK_OFFSET + bit // 8
        assert encoded[-1] == mask
        # still inside the mask the engine memsets
        assert displacement < kind_of.THING_TEMPLATE_MASK_OFFSET + kind_of.MASK_BYTES


def test_a_third_kindof_does_not_fit(clean: bytearray) -> None:
    data = bytearray(clean)
    with pytest.raises(ValueError, match="overflows"):
        kind_of.extend(data, ".k3", ["ONE", "TWO", "THREE"])


def test_the_patch_spends_the_last_two_bits(patched: bytearray) -> None:
    """Stated as a test because it is the cost of the pair: nothing else can add a kindof to a
    binary that already carries this one."""
    with pytest.raises(ValueError, match="overflows"):
        kind_of.extend(patched, ".k1", ["ONEMORE"])


def test_every_stock_kindof_keeps_its_index_and_string(patched: bytearray) -> None:
    table = kind_of.read(patched)
    assert table.count == kind_of.STOCK_KIND_COUNT + 2
    for index in range(kind_of.STOCK_KIND_COUNT):
        assert kind_of.read_cstring(patched, table.pointers[index]) == stock_kindof_name(index)
    assert kind_of.read_cstring(patched, table.pointers[BIT]) == DEFAULT_KINDOF
    assert kind_of.read_cstring(patched, table.pointers[GROUP_BIT]) == DEFAULT_GROUP_KINDOF


def test_every_reference_points_at_the_copy(patched: bytearray) -> None:
    located = find_section(patched, SECTION_NAME)
    assert located is not None
    for va in kind_of.TABLE_REF_VAS:
        assert _u32(patched, va) == located[0], f"ref @0x{va:08x} was left behind"


def test_every_count_site_agrees_with_the_new_length(patched: bytearray) -> None:
    for va, prefix in kind_of.COUNT_SITES:
        assert _bytes_at(patched, va, len(prefix)) == prefix
        assert _u32(patched, va + len(prefix)) == kind_of.STOCK_KIND_COUNT + 2


def test_the_table_could_not_have_grown_in_place(clean: bytearray) -> None:
    """The dword after the stock terminator already belongs to the next table, which is why the
    patch relocates rather than appends."""
    after = _u32(clean, kind_of.NAME_TABLE_VA + (kind_of.STOCK_KIND_COUNT + 1) * 4)
    assert after != 0


def test_a_name_the_ini_parser_could_never_match_is_refused(clean: bytearray) -> None:
    data = bytearray(clean)
    with pytest.raises(ValueError, match="uppercase"):
        HeroBarPatch(kindof="Hero Bar").apply(data)


def test_an_existing_kindof_name_is_refused(clean: bytearray) -> None:
    data = bytearray(clean)
    with pytest.raises(ValueError, match="already kindof 143"):
        HeroBarPatch(kindof="PORTER").apply(data)


def test_the_two_names_may_not_be_the_same(clean: bytearray) -> None:
    data = bytearray(clean)
    with pytest.raises(ValueError, match="duplicate"):
        HeroBarPatch(kindof="SLOT", group_kindof="SLOT").apply(data)


def test_every_hook_is_a_jmp_into_the_cave_padded_to_fit(patched: bytearray) -> None:
    located = find_section(patched, SECTION_NAME)
    assert located is not None
    section_va, _off, vsize = located
    _base, cave = _cave(patched)
    for hook in HOOKS:
        here = _bytes_at(patched, hook.va, hook.size)
        assert here[0] == 0xE9, f"{hook.label} is not a jmp"
        assert here[5:] == b"\x90" * (hook.size - 5), f"{hook.label} is not nop-padded"
        target = hook.va + 5 + struct.unpack_from("<i", here, 1)[0]
        assert section_va <= target < section_va + vsize
        assert target == cave.entries[hook.label]


def test_the_hook_sites_hold_the_expected_original_bytes(clean: bytearray) -> None:
    """The whole patch is aimed at these six addresses. If a site does not hold what it should,
    `apply_byte_patch` refuses - this asserts the same thing up front, so a build mismatch reads
    as a build mismatch rather than as a patch bug."""
    for hook in HOOKS:
        assert _bytes_at(clean, hook.va, hook.size) == hook.original


def test_a_hook_site_is_wide_enough_for_the_detour() -> None:
    for hook in HOOKS:
        assert hook.size >= 5, f"{hook.label} cannot hold a jmp rel32"


def test_the_scratch_words_start_zeroed(patched: bytearray) -> None:
    """The per-pass template set is only correct if its length starts at zero; the draw hook
    clears it at the top of every pass, but the very first pass runs before that has happened
    for a freshly loaded image. The cursor table wants the same: zero means "no member picked
    from this slot yet", which is what sends the first click to the first member.

    The jump window at `+0xB8` is the one word here the patcher fills in and the game only reads,
    so it is the one exception."""
    state = _bytes_at(patched, _cave_base(patched), STATE_SIZE)
    assert state[:0xB8] == bytes(0xB8)
    assert state[0xBC:] == bytes(STATE_SIZE - 0xBC)
    assert struct.unpack_from("<I", state, 0xB8)[0] == DEFAULT_JUMP_WINDOW


def test_the_patch_narrows_the_hover_handlers_tooltip_test(
    clean: bytearray, patched: bytearray
) -> None:
    """The hover handler reads `slot+0x16` as a flag, so every non-zero value would take the
    porter's "select nearest unit" tooltip. Narrowing it to `== 1` leaves `2` on the arm that
    builds the tooltip from the slot's own node."""
    size = len(TOOLTIP_EDIT.patched)
    assert _bytes_at(clean, TOOLTIP_EDIT.va, size) == TOOLTIP_EDIT.original
    assert _bytes_at(patched, TOOLTIP_EDIT.va, size) == TOOLTIP_EDIT.patched


def test_the_narrowed_tooltip_test_still_reads_the_same_byte_and_jumps_the_same_way(
    patched: bytearray,
) -> None:
    """Two bytes change: the immediate and the branch sense. The operand and the target have to
    survive, or the handler would dispatch on something else or land somewhere else."""
    rendered = [
        (i.mnemonic, i.op_str)
        for i in _disassemble(patched, TOOLTIP_EDIT.va, len(TOOLTIP_EDIT.patched))
    ]
    assert rendered[0] == ("cmp", "byte ptr [eax + 0x16], 1")
    assert rendered[1] == ("jne", "0x92bfaa")


def test_verify_notices_a_reverted_tooltip_edit(patched: bytearray) -> None:
    off = va_to_offset(patched, TOOLTIP_EDIT.va)
    assert off is not None
    patched[off : off + len(TOOLTIP_EDIT.original)] = TOOLTIP_EDIT.original
    problems = HeroBarPatch().verify(patched)
    assert any("select nearest unit" in problem for problem in problems)


def test_the_cave_is_writable_and_executable(patched: bytearray) -> None:
    """The draw and click hooks write the scratch words at runtime, so a read-execute cave would
    fault."""
    e = struct.unpack_from("<I", patched, 0x3C)[0]
    nsec = struct.unpack_from("<H", patched, e + 6)[0]
    szopt = struct.unpack_from("<H", patched, e + 20)[0]
    for index in range(nsec):
        off = e + 24 + szopt + index * 40
        if bytes(patched[off : off + 8]).rstrip(b"\x00") == SECTION_NAME.encode():
            characteristics = struct.unpack_from("<I", patched, off + 36)[0]
            assert characteristics & 0x80000000, "the cave is not MEM_WRITE"
            assert characteristics & 0x20000000, "the cave is not MEM_EXECUTE"
            return
    pytest.fail(f"no {SECTION_NAME} section")


def test_the_classify_hook_tests_all_three_kindofs_then_rejoins_the_engine(
    patched: bytearray,
) -> None:
    """`HERO || HEROBAR || HEROBAR_GROUP` on the way to `addHero`, falling through to the stock
    `PORTER` test. Re-entering at the engine's own two arms is what keeps the `je` and both calls
    untouched. Membership does not care which of the two kindofs an object carries."""
    rendered = _routine(patched, "classify")
    assert rendered[0] == ("test", "byte ptr [eax + 0x113], 4")  # HERO
    assert rendered[2] == ("test", IS_HEROBAR)
    assert rendered[4] == ("test", IS_GROUP)
    assert rendered[6] == ("jmp", "0x92cd90")  # the stock PORTER test
    assert rendered[7] == ("jmp", "0x92cd88")  # push edx ; call addHero


@pytest.mark.parametrize(
    ("label", "register", "resume"),
    [("remove_gate", "eax", "0x92c43f"), ("remove_list", "esi", "0x92c46d")],
)
def test_the_removal_hooks_leave_the_engines_own_branch_to_read_the_flags(
    patched: bytearray, label: str, register: str, resume: str
) -> None:
    """Both removal hooks rejoin *before* the engine's `jne`/`je`, so what they have to get right
    is the flags. The three tests run in turn and the first one that is set jumps out - and since
    neither `jcc` nor `jmp` disturbs the flags, whichever `test` ran last is the one the engine
    reads. A path that jumped without having tested anything would leave stale flags behind."""
    rendered = _routine(patched, label)
    assert rendered[0][0] == "test", "the displaced HERO test is gone"
    assert rendered[1][0] == "jne"
    assert rendered[2] == ("test", IS_HEROBAR.replace("eax", register))
    assert rendered[3][0] == "jne"
    assert rendered[4] == ("test", IS_GROUP.replace("eax", register))
    assert rendered[5] == ("jmp", resume)
    # both early exits land on that last jump, not on an arm of their own
    target = _routine_ins(patched, label)[5].address
    assert int(rendered[1][1], 16) == int(rendered[3][1], 16) == target


@pytest.mark.parametrize(
    ("label", "resume", "skip"),
    [
        ("select_all_scan", "0x92c918", "0x92c94e"),
        ("select_all_pick", "0x92c9a0", "0x92ca5f"),
    ],
)
def test_select_all_heroes_passes_over_both_kindofs(
    patched: bytearray, label: str, resume: str, skip: str
) -> None:
    """`_OnBttnSelectAllHeroes` walks the slot array and never asks `HERO`, so without this every
    slot the patch put on the bar came back selected. `HERO` is tested first, so a template that
    is a hero *and* on the bar still counts as a hero; a rejected object leaves through the loop's
    own "next slot" label, and the displaced selectable test is re-issued on the way back."""
    rendered = _routine(patched, label)
    assert rendered[0] == ("mov", "eax, dword ptr [esi + 4]")
    assert rendered[1] == ("test", "byte ptr [eax + 0x113], 4")  # HERO, and it wins
    assert rendered[3] == ("test", IS_HEROBAR)
    assert rendered[5] == ("test", IS_GROUP)
    assert rendered[7] == ("mov", "ecx, esi")
    assert rendered[8] == ("call", "0x68de58")
    assert rendered[9] == ("jmp", resume)
    assert rendered[10] == ("jmp", skip)
    rejected = _routine_ins(patched, label)[10].address
    assert int(rendered[4][1], 16) == rejected, "HEROBAR does not reach the skip"
    assert int(rendered[6][1], 16) == rejected, "HEROBAR_GROUP does not reach the skip"


def test_both_select_all_passes_apply_the_same_test(patched: bytearray) -> None:
    """The button counts the eligible slots in one pass and appends them in another, and the two
    have to agree: a filter on only one of them would either drop the last selection or size the
    message wrongly."""
    scan = [step for step in _routine(patched, "select_all_scan") if step[0] == "test"]
    pick = [step for step in _routine(patched, "select_all_pick") if step[0] == "test"]
    assert scan == pick != []


def test_the_draw_loop_keys_on_the_grouping_kindof_only(patched: bytearray) -> None:
    """The split between the two kindofs lives here and nowhere else: membership reads either
    bit, and the slot-sharing decision reads only `HEROBAR_GROUP`. A plain `HEROBAR` object
    therefore falls to the arm that clears the group byte and gets a slot of its own."""
    rendered = _routine(patched, "per_node")
    tests = [op for m, op in rendered if m == "test" and "0x123" in op]
    assert tests == [IS_GROUP.replace("eax", "ecx")], "the draw loop reads the wrong bit"


def test_the_per_node_hook_skips_a_duplicate_without_consuming_a_slot(patched: bytearray) -> None:
    """The engine's own "ineligible" label is the skip target: it advances to the next node but
    leaves the slot cursor alone, which is exactly what a duplicate needs."""
    rendered = _routine(patched, "per_node")
    assert ("jmp", "0x92d76f") in rendered, "the duplicate path does not reach the engine's skip"
    assert ("jmp", "0x92d425") in rendered, "the unchanged-slot path is gone"
    assert ("jmp", "0x92d3f3") in rendered, "the redraw path is gone"
    assert ("cmp", "ebx, dword ptr [edi - 4]") in rendered, "the displaced compare was dropped"


def test_the_per_node_hook_balances_the_registers_it_borrows(patched: bytearray) -> None:
    """Three pushes at the top, and both ways out pop all three. A path that missed one would
    return into the draw loop with a shifted stack."""
    rendered = _routine(patched, "per_node")
    assert rendered[:3] == [("push", "eax"), ("push", "ecx"), ("push", "edx")]
    exits = [
        index
        for index in range(len(rendered) - 2)
        if [m for m, _ in rendered[index : index + 3]] == ["pop"] * 3
    ]
    assert len(exits) == 2, "the hook does not have exactly two ways out"
    for index in exits:
        assert [op for _, op in rendered[index : index + 3]] == ["edx", "ecx", "eax"]


def test_the_badge_count_restores_its_walker_around_the_calls_it_makes(
    patched: bytearray,
) -> None:
    """The count loop borrows `edx` for the node it is on and has to get it back after each of
    the two calls, which clobber it. Two `push edx` (the hook's own save, then the walker's) and
    three `pop edx` (the walker's, then one per way out of the hook)."""
    rendered = _routine(patched, "per_node")
    assert [op for m, op in rendered if m == "push" and op == "edx"] == ["edx"] * 2
    assert [op for m, op in rendered if m == "pop" and op == "edx"] == ["edx"] * 3


def test_the_per_node_hook_marks_and_unmarks_the_slot(patched: bytearray) -> None:
    """Both arms write the group byte: a template that is not `HEROBAR_GROUP` clears it, so a
    slot reused by an ordinary hero - or by a plain `HEROBAR` object - this pass stops dispatching
    to the group click."""
    rendered = _routine(patched, "per_node")
    writes = [op for m, op in rendered if m == "mov" and op.startswith("byte ptr [edi + 0x12]")]
    assert writes == [f"byte ptr [edi + 0x12], {GROUPED_HEROBAR}", "byte ptr [edi + 0x12], 0"]


def test_a_group_slot_draws_a_member_count_where_a_hero_draws_its_rank(
    patched: bytearray,
) -> None:
    """`[ebp-0x18]` is the number the engine is about to draw, and every read of it that draws or
    caches it happens after this hook. Writing the count there is the whole badge - no APT call,
    no string, no second hook site."""
    base, _cave_ = _cave(patched)
    count = base + 0xA8
    rendered = _routine(patched, "per_node")
    write = rendered.index(("mov", "dword ptr [ebp - 0x18], eax"))
    assert rendered[write - 1] == ("mov", f"eax, dword ptr [0x{count:x}]"), "not the counted value"


def test_the_badge_count_applies_the_draw_loops_own_two_tests(patched: bytearray) -> None:
    """A member is counted only if it is still findable and the bar would accept it - the same
    pair the draw loop applies before giving a node a slot. Counting anything else would put a
    number on the slot that does not match what a click can reach."""
    rendered = _routine(patched, "per_node")
    assert ("call", FIND_OBJECT_BY_ID) in rendered, "the count does not resolve its nodes"
    assert ("call", "0x92bbef") in rendered, "the count does not filter on eligibility"


def test_a_template_past_the_sixteenth_keeps_its_rank(patched: bytearray) -> None:
    """The per-pass set clamps at 16, and that path has to skip the count as well as the
    recording: those slots are drawn ungrouped, so a count would contradict the bar."""
    instructions = _routine_ins(patched, "per_node")
    rendered = [(i.mnemonic, i.op_str) for i in instructions]
    clamp = rendered.index(("cmp", "eax, 0x10"))
    assert rendered[clamp + 1][0] == "jae"
    target = int(rendered[clamp + 1][1], 16)
    mark = next(
        i.address for i in instructions if i.op_str == f"byte ptr [edi + 0x12], {GROUPED_HEROBAR}"
    )
    assert target == mark, "the clamp does not jump straight to the mark, skipping the count"


def test_the_click_hook_is_a_three_way(patched: bytearray) -> None:
    """`2` is this patch's group, `1` is the stock porter group and `0` is a plain hero - or a
    plain `HEROBAR` object, which is the same click. The two stock arms have to be reachable
    unchanged, or the patch would break porters."""
    rendered = _routine(patched, "click")
    assert rendered[0] == ("cmp", f"byte ptr [ecx + esi + 0x5e], {GROUPED_HEROBAR}")
    assert rendered[2] == ("cmp", "byte ptr [ecx + esi + 0x5e], 0")
    assert rendered[4] == ("jmp", "0x92dbeb")  # the stock single-object select
    assert rendered[5] == ("jmp", "0x92dbdd")  # the stock porter cycle


def test_a_click_selects_one_member_not_the_group(patched: bytearray) -> None:
    """The point of the whole routine: one `ObjectID` reaches the message, so the click behaves
    like clicking a hero's slot rather than like a select-all."""
    rendered = _routine(patched, "click")
    appends = [op for m, op in rendered if m == "call" and op == APPEND_OBJECT_ID]
    assert len(appends) == 1, "a stepped click appends exactly one member"


def test_a_click_reads_the_slots_cursor_and_writes_the_member_it_picked(
    patched: bytearray,
) -> None:
    """The cursor table is what makes the next click pick the next member: indexed by slot on the
    way in through `eax`, and on the way out through `edx`, both scaled by four."""
    base, _cave_ = _cave(patched)
    cursor = base + 0x68
    rendered = _routine(patched, "click")
    assert ("mov", f"eax, dword ptr [eax*4 + 0x{cursor:x}]") in rendered, "the cursor is not read"
    assert ("mov", f"dword ptr [edx*4 + 0x{cursor:x}], eax") in rendered, "it is never written"


def test_a_click_clamps_the_cursor_table_to_its_sixteen_slots(patched: bytearray) -> None:
    """`hero-bar-slots` can make the bar wider than the table. Both the read and the write are
    bounded, so a slot past the sixteenth simply never steps - it does not walk off the array."""
    rendered = _routine(patched, "click")
    assert ("cmp", "eax, 0x10") in rendered, "the cursor read is unbounded"
    assert ("cmp", "edx, 0x10") in rendered, "the cursor write is unbounded"


def test_a_click_falls_back_to_the_first_member(patched: bytearray) -> None:
    """A cursor that names nobody on the list is the ordinary case - a fresh slot, a dead unit,
    the end of a round - so the pick reads the "after the cursor" word, then the first member,
    and only gives up if both are null."""
    base, _cave_ = _cave(patched)
    first, chosen = base + 0x5C, base + 0x60
    rendered = _routine(patched, "click")
    loads = [op for m, op in rendered if m == "mov" and op.startswith("ecx, dword ptr [0x")]
    pick = loads.index(f"ecx, dword ptr [0x{chosen:x}]")
    assert loads[pick + 1] == f"ecx, dword ptr [0x{first:x}]", "the wrap-around read is gone"


def test_a_repeat_click_centres_the_camera_instead_of_stepping(patched: bytearray) -> None:
    """The second click on a slot means "take me there", not "next one": it asks the client for
    the frame, checks the window has not closed, and drives the camera through the same pair of
    calls the porter cycle uses - the drawable's position into `TheTacticalView::lookAt`."""
    base, _cave_ = _cave(patched)
    deadline = base + 0xB4
    rendered = _routine(patched, "click")
    assert ("call", "dword ptr [eax + 0x7c]") in rendered, "nothing reads the current frame"
    assert ("cmp", f"eax, dword ptr [0x{deadline:x}]") in rendered, "the window is not checked"
    assert ("call", "0x676711") in rendered, "the drawable's position is not resolved"
    assert ("call", "dword ptr [edx + 0x54]") in rendered, "lookAt is never called"


def test_a_repeat_click_only_counts_on_the_slot_that_was_clicked_last(
    patched: bytearray,
) -> None:
    """Clicking a different slot has to step, not jump, so the remembered slot is compared before
    anything else. It is stored biased by one, which is what makes a zeroed cave mean "no slot
    clicked yet" rather than "slot 0"."""
    base, _cave_ = _cave(patched)
    slot, click_slot = base + 0x54, base + 0xB0
    rendered = _routine(patched, "click")
    # the slot is read for the cursor too, so anchor on the read that biases it
    reads = [
        index
        for index, step in enumerate(rendered)
        if step == ("mov", f"eax, dword ptr [0x{slot:x}]") and rendered[index + 1] == ("inc", "eax")
    ]
    assert len(reads) == 2, "the bias is written in one place and read in the other"
    assert rendered[reads[0] + 2] == ("cmp", f"eax, dword ptr [0x{click_slot:x}]")
    assert rendered[reads[0] + 3][0] == "jne", "a different slot does not fall through to the step"
    assert rendered[reads[1] + 2] == ("mov", f"dword ptr [0x{click_slot:x}], eax")


def test_the_repeat_window_is_the_patchs_own_millisecond_constant(patched: bytearray) -> None:
    """The window is `--jump-window` milliseconds, held as a word in the cave and scaled to logic
    frames at runtime with the engine's own `.data` float and `_ftol` - the arithmetic
    `0x0092BA91` does, without the engine value (3500ms, a porter *round*) or its store into
    `bar+0x1DC` (a field `hero-bar-slots` moves)."""
    base, _cave_ = _cave(patched)
    window_ms, deadline = base + 0xB8, base + 0xB4
    rendered = _routine(patched, "click")
    window = rendered.index(("fild", f"dword ptr [0x{window_ms:x}]"))
    assert rendered[window + 1 : window + 3] == [
        ("fmul", "dword ptr [0xd9f624]"),
        ("call", "0xa3cfa4"),
    ]
    added = ("add", f"eax, dword ptr [0x{deadline:x}]")
    assert added in rendered[window:], "the current frame is never added to the window"


@pytest.mark.parametrize("ms", [0, 1, 250, DEFAULT_JUMP_WINDOW, MAX_JUMP_WINDOW])
def test_the_jump_window_is_the_only_thing_the_setting_changes(ms: int) -> None:
    """`--jump-window` is data, not code: it lands in one word of the state block and the routines
    around it are byte-identical, which is why `detect` can read it back rather than guess."""
    default = build_cave(BASE, BIT, GROUP_BIT, DEFAULT_JUMP_WINDOW).content
    tuned = build_cave(BASE, BIT, GROUP_BIT, ms).content
    assert len(tuned) == len(default)
    differing = {index for index in range(len(tuned)) if tuned[index] != default[index]}
    assert differing <= {0xB8, 0xB9, 0xBA, 0xBB}, "the window leaked out of its word"
    assert struct.unpack_from("<I", tuned, 0xB8)[0] == ms


def test_the_jump_window_round_trips_through_detect(clean: bytearray) -> None:
    """A window recovered wrong would fail `verify` with nothing to say which of the two settings
    the binary disagreed about, so `detect` reads the word instead of trying values."""
    data = bytearray(clean)
    HeroBarPatch(jump_window=250).apply(data)
    found = HeroBarPatch.detect(data)
    assert found == HeroBarPatch(jump_window=250)
    assert not found.verify(data)


@pytest.mark.parametrize("ms", [-1, MAX_JUMP_WINDOW + 1])
def test_an_out_of_range_jump_window_is_refused(ms: int) -> None:
    """The word is `fild`ed as a signed dword and the gesture is a gesture; a value outside the
    range is a mistake worth a message rather than a cave that quietly never fires."""
    with pytest.raises(ValueError, match="jump-window"):
        HeroBarPatch(jump_window=ms)


def test_the_repeat_window_reads_nothing_past_the_bars_slot_array(patched: bytearray) -> None:
    """`hero-bar-slots` grows the array in place and slides everything after it up, so
    `bar+0x1C8`.. is not a fixed address on a patched build. The engine's own deadline routine
    stores into `bar+0x1DC`; calling it and reading that back would take a slot's cached bytes for
    a deadline on a widened bar, and stomp the porter's real field on the way past."""
    rendered = _routine(patched, "click")
    assert ("call", "0x92ba91") not in rendered, "the deadline routine is called again"
    # Slot addressing is scaled by the index and stays inside the array, which does not move; a
    # bare `[esi + disp]` is the shape that would break, and the model pointer is the only one.
    bare = [op for _m, op in rendered if "[esi + 0x" in op]
    assert bare == ["ecx, dword ptr [esi + 0x10]"], f"the bar is read past its array: {bare}"


def test_the_group_step_balances_every_call_it_makes(patched: bytearray) -> None:
    """Every call here is callee-cleaned, so a push is either an argument the callee takes away
    or a save this routine pops back itself. An unbalanced arm would corrupt the click handler's
    frame on the way out."""
    rendered = _routine(patched, "click")
    pushes = sum(1 for m, op in rendered if m == "push" and op in {"eax", "ecx"})
    pops = sum(1 for m, op in rendered if m == "pop" and op == "ecx")
    # Six pushes: the object saved across the eligibility test and the argument to it, the object
    # saved across the message calls and again across `appendObjectIDArgument`, the drawable handed
    # to `selectDrawable`, and the position handed to `lookAt`. Three are saves - the three pops.
    assert (pushes, pops) == (6, 3)


def test_the_group_step_validates_the_slot_before_dereferencing_it(patched: bytearray) -> None:
    """A slot's node pointer is only as fresh as the last draw pass, so the routine walks the
    live list to confirm the node is still on it. Without that, a stale mark would hand a freed
    pointer to `findObjectByID`."""
    rendered = _routine(patched, "click")
    find_calls = [op for m, op in rendered if m == "call" and op == FIND_OBJECT_BY_ID]
    # three lookups: the validation walk, the repeat click's remembered member, the member walk
    assert len(find_calls) == 3, "a lookup the routine depends on is missing"
    assert rendered.index(("call", FIND_OBJECT_BY_ID)) > rendered.index(
        ("mov", "edi, dword ptr [edi]")
    )


def test_the_group_step_ends_at_the_handlers_own_epilogue(patched: bytearray) -> None:
    """`0x0092DDE1` pops only edi and esi, so it is correct to jump to exactly as long as the
    routine has not pushed ebx - which it never does."""
    rendered = _routine(patched, "click")
    assert ("jmp", "0x92dde1") in rendered
    assert not any(m == "push" and op == "ebx" for m, op in rendered)


def test_apply_then_verify_is_clean(clean: bytearray) -> None:
    data = bytearray(clean)
    patch = HeroBarPatch()
    patch.apply(data)
    assert patch.verify(data) == []


def test_verify_rejects_an_unpatched_image(clean: bytearray) -> None:
    assert HeroBarPatch().verify(clean) == [
        f"no {SECTION_NAME} section: the file does not carry this patch"
    ]


def test_verify_rejects_a_different_name(patched: bytearray) -> None:
    problems = HeroBarPatch(kindof="SOMETHINGELSE").verify(patched)
    assert problems and "adds kindofs 'HEROBAR' and 'HEROBAR_GROUP'" in problems[0]


def test_verify_rejects_the_two_names_the_wrong_way_round(patched: bytearray) -> None:
    """Which bit is which is the whole difference between the two kindofs, so a swapped pair is
    not a naming quibble - it would make every `HEROBAR` object group and every `HEROBAR_GROUP`
    object take a slot of its own."""
    problems = HeroBarPatch(kindof=DEFAULT_GROUP_KINDOF, group_kindof=DEFAULT_KINDOF).verify(
        patched
    )
    assert problems and "adds kindofs" in problems[0]


def test_verify_notices_a_reverted_hook(patched: bytearray) -> None:
    hook = HOOKS[0]
    off = va_to_offset(patched, hook.va)
    assert off is not None
    patched[off : off + hook.size] = hook.original
    problems = HeroBarPatch().verify(patched)
    assert any("is unpatched" in problem for problem in problems)


def test_verify_notices_a_flipped_cave_byte(patched: bytearray) -> None:
    off = va_to_offset(patched, _cave_base(patched) + STATE_SIZE)
    assert off is not None
    patched[off] ^= 0xFF
    assert any("hook code" in problem for problem in HeroBarPatch().verify(patched))


def test_detect_recovers_both_names(clean: bytearray) -> None:
    data = bytearray(clean)
    HeroBarPatch(kindof="SOLOSLOT", group_kindof="SHAREDSLOT").apply(data)
    found = HeroBarPatch.detect(data)
    assert isinstance(found, HeroBarPatch)
    assert (found.kindof, found.group_kindof) == ("SOLOSLOT", "SHAREDSLOT")


def test_detect_is_none_on_a_clean_image(clean: bytearray) -> None:
    assert HeroBarPatch.detect(clean) is None


def test_the_ini_surface_names_both_kindofs() -> None:
    members = HeroBarPatch(kindof="SOLOSLOT", group_kindof="SHAREDSLOT").ini_surface().enum_members
    assert [(m.enum, m.name, m.value) for m in members] == [
        ("KindOf", "SOLOSLOT", None),
        ("KindOf", "SHAREDSLOT", None),
    ]


@pytest.mark.parametrize("herobar_first", [True, False])
def test_it_composes_with_the_other_table_growing_patch(
    clean: bytearray, herobar_first: bool
) -> None:
    """Both patches append a section and rebuild a name table, so the two orders exercise
    different `next_section_rva` outcomes. Neither table is the other's."""
    data = bytearray(clean)
    patches = [HeroBarPatch(), ProductionConditionPatch(condition="PRODUCING")]
    for patch in patches if herobar_first else reversed(patches):
        patch.apply(data)
    for patch in patches:
        assert patch.verify(data) == [], f"{patch} broke when applied {herobar_first=}"
