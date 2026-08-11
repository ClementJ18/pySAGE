"""Tests for the `HEROBAR` kindof patch.

Three kinds of thing are checked here, and only the first is ordinary code.

**The table move** is mechanical and testable directly: every stock kindof has to come through
the rebuild with both its index and its original string, all fourteen references have to point at
the copy, and all six counts have to agree with it.

**The cave** is hand-encoded x86 that cannot be executed in a test, so the tests that matter
disassemble it back and assert it says what it was meant to say. A wrong byte does not raise - it
crashes the game, or marks the wrong slot, or selects the wrong units.

**The invariants of the target build** the patch quietly depends on: that the kindof mask has room
for a 223rd bit at all, and that the byte-and-mask form this patch emits for a kindof test is
byte-identical to the one the engine already uses for `HERO` at the site being replaced. Neither
is visible from the code that relies on it, and both are the reason the patch is as small as it is.
"""

from __future__ import annotations

import struct

import pytest

from sage_patch.patches.herobar import (
    DEFAULT_KINDOF,
    GROUPED_HEROBAR,
    HERO_BIT,
    HOOKS,
    SECTION_NAME,
    STATE_SIZE,
    HeroBarPatch,
    build_cave,
)
from sage_patch.patches.production_condition import ProductionConditionPatch
from sage_patch.patches.utils import kind_of
from sage_patch.utils import find_section, va_to_offset
from tests.sage_patch.synthetic import stock_kindof_name, synthetic_image

BASE = 0x00F00000
BIT = kind_of.STOCK_KIND_COUNT


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


def _cave_start(data: bytes | bytearray) -> int:
    """Where the hook code begins: past the rebuilt table, the name and the scratch words."""
    located = find_section(data, SECTION_NAME)
    assert located is not None
    section_va = located[0]
    entries = kind_of.STOCK_KIND_COUNT + 1
    name = len(DEFAULT_KINDOF) + 1
    return section_va + (entries + 1) * 4 + name + (-name % 4) + STATE_SIZE


def _disassemble(data: bytes | bytearray, va: int, size: int) -> list:
    capstone = pytest.importorskip("capstone")
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    return list(md.disasm(_bytes_at(data, va, size), va))


# --- the build's own invariants ---------------------------------------------------------------


def test_the_mask_has_room_for_one_more_kindof() -> None:
    """The whole patch is affordable because of this. 222 names in a 224-bit mask means the new
    bit needs no `ThingTemplate` growth and no savegame length change."""
    assert kind_of.STOCK_KIND_COUNT < kind_of.MASK_DWORDS * 32
    assert kind_of.MASK_BYTES == 0x1C


def test_the_emitted_bit_test_matches_the_engines_own() -> None:
    """`bit_test` has to reproduce the engine's encoding exactly, because the classify hook
    re-executes the `HERO` test it displaced. If the two forms differed, the displaced original
    bytes asserted at the hook site would not be the ones the cave re-emits."""
    hook = next(h for h in HOOKS if h.label == "classify")
    assert kind_of.bit_test(HERO_BIT, 0, kind_of.THING_TEMPLATE_MASK_OFFSET) == hook.original


def test_bit_test_places_the_new_bit_in_the_last_dword() -> None:
    encoded = kind_of.bit_test(BIT, 0, kind_of.THING_TEMPLATE_MASK_OFFSET)
    displacement = struct.unpack_from("<I", encoded, 2)[0]
    assert displacement == kind_of.THING_TEMPLATE_MASK_OFFSET + BIT // 8
    assert encoded[-1] == 1 << (BIT % 8)
    # still inside the mask the engine memsets
    assert displacement < kind_of.THING_TEMPLATE_MASK_OFFSET + kind_of.MASK_BYTES


def test_a_third_kindof_does_not_fit(clean: bytearray) -> None:
    data = bytearray(clean)
    with pytest.raises(ValueError, match="overflows"):
        kind_of.extend(data, ".k3", ["ONE", "TWO", "THREE"])


# --- the table move ---------------------------------------------------------------------------


def test_every_stock_kindof_keeps_its_index_and_string(patched: bytearray) -> None:
    table = kind_of.read(patched)
    assert table.count == kind_of.STOCK_KIND_COUNT + 1
    for index in range(kind_of.STOCK_KIND_COUNT):
        assert kind_of.read_cstring(patched, table.pointers[index]) == stock_kindof_name(index)
    assert kind_of.read_cstring(patched, table.pointers[BIT]) == DEFAULT_KINDOF


def test_every_reference_points_at_the_copy(patched: bytearray) -> None:
    located = find_section(patched, SECTION_NAME)
    assert located is not None
    for va in kind_of.TABLE_REF_VAS:
        assert _u32(patched, va) == located[0], f"ref @0x{va:08x} was left behind"


def test_every_count_site_agrees_with_the_new_length(patched: bytearray) -> None:
    for va, prefix in kind_of.COUNT_SITES:
        assert _bytes_at(patched, va, len(prefix)) == prefix
        assert _u32(patched, va + len(prefix)) == kind_of.STOCK_KIND_COUNT + 1


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


# --- the hook sites ---------------------------------------------------------------------------


def test_every_hook_is_a_jmp_into_the_cave_padded_to_fit(patched: bytearray) -> None:
    located = find_section(patched, SECTION_NAME)
    assert located is not None
    section_va, _off, vsize = located
    cave = build_cave(_cave_start(patched) - STATE_SIZE, BIT)
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


# --- the cave -----------------------------------------------------------------------------------


def test_the_scratch_words_start_zeroed(patched: bytearray) -> None:
    """The per-pass template set is only correct if its length starts at zero; the draw hook
    clears it at the top of every pass, but the very first pass runs before that has happened
    for a freshly loaded image."""
    located = find_section(patched, SECTION_NAME)
    assert located is not None
    assert _bytes_at(patched, _cave_start(patched) - STATE_SIZE, STATE_SIZE) == bytes(STATE_SIZE)


def test_the_cave_section_is_writable(patched: bytearray) -> None:
    """The draw hook writes the scratch words at runtime, so a read-execute cave would fault."""
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


def test_the_classify_hook_tests_both_kindofs_then_rejoins_the_engine(patched: bytearray) -> None:
    """`HERO || HEROBAR` on the way to `addHero`, falling through to the stock `PORTER` test.
    Re-entering at the engine's own two arms is what keeps the `je` and both calls untouched."""
    instructions = _disassemble(
        patched, build_cave(_cave_start(patched) - STATE_SIZE, BIT).entries["classify"], 0x24
    )
    rendered = [(i.mnemonic, i.op_str) for i in instructions]
    assert rendered[0] == ("test", "byte ptr [eax + 0x113], 4")  # HERO
    assert rendered[2] == ("test", "byte ptr [eax + 0x123], 0x40")  # HEROBAR, bit 222
    assert rendered[4] == ("jmp", "0x92cd90")  # the stock PORTER test
    assert rendered[5] == ("jmp", "0x92cd88")  # push edx ; call addHero


@pytest.mark.parametrize(
    ("label", "resume"),
    [("remove_gate", "0x92c43f"), ("remove_list", "0x92c46d")],
)
def test_the_removal_hooks_leave_the_engines_own_branch_to_read_the_flags(
    patched: bytearray, label: str, resume: str
) -> None:
    """Both removal hooks rejoin *before* the engine's `jne`/`je`, so what they have to get right
    is the flags. Every path out therefore ends with a `test` and then the same jump - never a
    jump taken straight from the first test, which would leave stale flags behind."""
    entries = build_cave(_cave_start(patched) - STATE_SIZE, BIT).entries
    rendered = [(i.mnemonic, i.op_str) for i in _disassemble(patched, entries[label], 0x20)]
    assert rendered[0][0] == "test", "the displaced HERO test is gone"
    assert rendered[1][0] == "je"
    assert rendered[2] == ("jmp", resume)
    assert rendered[3][0] == "test"
    assert rendered[3][1].endswith("0x123], 0x40"), "the second test is not the new kindof"
    assert rendered[4] == ("jmp", resume)


def test_the_per_node_hook_skips_a_duplicate_without_consuming_a_slot(patched: bytearray) -> None:
    """The engine's own "ineligible" label is the skip target: it advances to the next node but
    leaves the slot cursor alone, which is exactly what a duplicate needs."""
    entries = build_cave(_cave_start(patched) - STATE_SIZE, BIT).entries
    rendered = [(i.mnemonic, i.op_str) for i in _disassemble(patched, entries["per_node"], 0x80)]
    assert ("jmp", "0x92d76f") in rendered, "the duplicate path does not reach the engine's skip"
    assert ("jmp", "0x92d425") in rendered, "the unchanged-slot path is gone"
    assert ("jmp", "0x92d3f3") in rendered, "the redraw path is gone"
    assert ("cmp", "ebx, dword ptr [edi - 4]") in rendered, "the displaced compare was dropped"


def test_the_per_node_hook_balances_the_registers_it_borrows(patched: bytearray) -> None:
    """Three pushes at the top, and both ways out pop all three. A path that missed one would
    return into the draw loop with a shifted stack."""
    entries = build_cave(_cave_start(patched) - STATE_SIZE, BIT).entries
    rendered = [(i.mnemonic, i.op_str) for i in _disassemble(patched, entries["per_node"], 0x80)]
    assert [op for m, op in rendered if m == "push"] == ["eax", "ecx", "edx"]
    assert [op for m, op in rendered if m == "pop"] == ["edx", "ecx", "eax"] * 2


def test_the_per_node_hook_marks_and_unmarks_the_slot(patched: bytearray) -> None:
    """Both arms write the group byte: a template that is not `HEROBAR` clears it, so a slot
    reused by an ordinary hero this pass stops dispatching to the group click."""
    entries = build_cave(_cave_start(patched) - STATE_SIZE, BIT).entries
    rendered = [(i.mnemonic, i.op_str) for i in _disassemble(patched, entries["per_node"], 0x80)]
    writes = [op for m, op in rendered if m == "mov" and op.startswith("byte ptr [edi + 0x12]")]
    assert writes == [f"byte ptr [edi + 0x12], {GROUPED_HEROBAR}", "byte ptr [edi + 0x12], 0"]


def test_the_click_hook_is_a_three_way(patched: bytearray) -> None:
    """`2` is this patch's group, `1` is the stock porter group and `0` is a plain hero. The two
    stock arms have to be reachable unchanged, or the patch would break porters."""
    entries = build_cave(_cave_start(patched) - STATE_SIZE, BIT).entries
    rendered = [(i.mnemonic, i.op_str) for i in _disassemble(patched, entries["click"], 0x20)]
    assert rendered[0] == ("cmp", f"byte ptr [ecx + esi + 0x5e], {GROUPED_HEROBAR}")
    assert rendered[2] == ("cmp", "byte ptr [ecx + esi + 0x5e], 0")
    assert rendered[4] == ("jmp", "0x92dbeb")  # the stock single-object select
    assert rendered[5] == ("jmp", "0x92dbdd")  # the stock porter cycle


def test_the_group_select_balances_every_call_it_makes(patched: bytearray) -> None:
    """Each of the three callee-cleaned calls in the member loop is wrapped in one push it pops
    itself. An unbalanced arm would corrupt the click handler's frame on the way out."""
    entries = build_cave(_cave_start(patched) - STATE_SIZE, BIT).entries
    start = entries["click"]
    rendered = [(i.mnemonic, i.op_str) for i in _disassemble(patched, start, 0x140)]
    pushes = sum(1 for m, op in rendered if m == "push" and op in {"eax", "ecx"})
    pops = sum(1 for m, op in rendered if m == "pop" and op == "ecx")
    assert pushes == 4, "the saves around the callee-cleaned calls changed"
    assert pops == 2, "a saved object is not being restored"


def test_the_group_select_validates_the_slot_before_dereferencing_it(patched: bytearray) -> None:
    """A slot's node pointer is only as fresh as the last draw pass, so the routine walks the
    live list to confirm the node is still on it. Without that, a stale mark would hand a freed
    pointer to `findObjectByID`."""
    entries = build_cave(_cave_start(patched) - STATE_SIZE, BIT).entries
    rendered = [(i.mnemonic, i.op_str) for i in _disassemble(patched, entries["click"], 0x140)]
    find_calls = [op for m, op in rendered if m == "call" and op == "0x449681"]
    assert len(find_calls) == 2, "the validation walk or the member walk is missing"
    assert rendered.index(("call", "0x449681")) > rendered.index(("mov", "edi, dword ptr [edi]"))


def test_the_group_select_ends_at_the_handlers_own_epilogue(patched: bytearray) -> None:
    """`0x0092DDE1` pops only edi and esi, so it is correct to jump to exactly as long as the
    routine has not pushed ebx - which it never does."""
    entries = build_cave(_cave_start(patched) - STATE_SIZE, BIT).entries
    rendered = [(i.mnemonic, i.op_str) for i in _disassemble(patched, entries["click"], 0x140)]
    assert ("jmp", "0x92dde1") in rendered
    assert not any(m == "push" and op == "ebx" for m, op in rendered)


# --- apply / verify / detect --------------------------------------------------------------------


def test_apply_then_verify_is_clean(patched: bytearray) -> None:
    assert HeroBarPatch().verify(patched) == []


def test_verify_rejects_an_unpatched_image(clean: bytearray) -> None:
    assert HeroBarPatch().verify(clean) == [
        f"no {SECTION_NAME} section: the file does not carry this patch"
    ]


def test_verify_rejects_a_different_name(patched: bytearray) -> None:
    problems = HeroBarPatch(kindof="SOMETHINGELSE").verify(patched)
    assert problems and "adds kindof 'HEROBAR'" in problems[0]


def test_verify_notices_a_reverted_hook(patched: bytearray) -> None:
    hook = HOOKS[0]
    off = va_to_offset(patched, hook.va)
    assert off is not None
    patched[off : off + hook.size] = hook.original
    problems = HeroBarPatch().verify(patched)
    assert any("is unpatched" in problem for problem in problems)


def test_verify_notices_a_flipped_cave_byte(patched: bytearray) -> None:
    off = va_to_offset(patched, _cave_start(patched))
    assert off is not None
    patched[off] ^= 0xFF
    problems = HeroBarPatch().verify(patched)
    assert any("hook code" in problem for problem in problems)


def test_detect_recovers_the_name(clean: bytearray) -> None:
    data = bytearray(clean)
    HeroBarPatch(kindof="SHAREDSLOT").apply(data)
    found = HeroBarPatch.detect(data)
    assert isinstance(found, HeroBarPatch)
    assert found.kindof == "SHAREDSLOT"


def test_detect_is_none_on_a_clean_image(clean: bytearray) -> None:
    assert HeroBarPatch.detect(clean) is None


def test_the_ini_surface_names_the_kindof() -> None:
    (member,) = HeroBarPatch(kindof="SHAREDSLOT").ini_surface().enum_members
    assert (member.enum, member.name, member.value) == ("KindOf", "SHAREDSLOT", None)


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
