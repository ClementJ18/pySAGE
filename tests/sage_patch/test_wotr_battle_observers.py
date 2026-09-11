"""Tests for the War of the Ring co-op observer patch.

The cave is hand-assembled x86 that cannot be executed here, so the tests that matter most
disassemble it back and assert it says what it was meant to say. A wrong byte does not raise: it
makes every co-op battle seat somebody on the wrong army, which is the kind of error only a static
check catches.

Two properties get their own tests because getting them wrong is silent. The first hook is a
``call`` whose *last* instruction has to be the comparison the caller's ``jl`` reads, so anything
that sets flags after it breaks the seat assignment; and the observer arms have to leave the sign
flag set, which is the whole mechanism.

The other half is the build fingerprint. This patch reads eight things it never rewrites - the
branches its forced comparisons feed, the two instructions that say which arm of the button mask
is which, and the prologues of the four routines its cave calls - and each has to fail loudly on
anything that is not the expected build.
"""

from __future__ import annotations

import struct

import pytest

pytest.importorskip("capstone", reason="the [patch] extra (capstone) is not installed")
from capstone import CS_ARCH_X86, CS_MODE_32, Cs  # noqa: E402 - after the importorskip guard

from sage_patch import WotrBattleObserversPatch, apply_patches  # noqa: E402
from sage_patch.addresses import (  # noqa: E402
    GAME_INFO_GET_SLOT,
    GAME_SLOT_IS_OCCUPIED,
    LIVING_WORLD_CURRENT_REGION,
    LIVING_WORLD_FIND_PLAYER_BY_ID,
)
from sage_patch.patches.wotr_battle_observers import (  # noqa: E402
    ANCHORS,
    ASCII_STRING_ASSIGN,
    ASSIGN_NAME_BYTES,
    ASSIGN_NAME_VA,
    CODE_OFFSET,
    DATA_SIZE,
    FACTION_TEST_BYTES,
    FACTION_TEST_VA,
    NAME_OFFSET,
    NUMBER_BYTES,
    NUMBER_VA,
    OBSERVER_SIDE_NAME,
    PREPARE_BYTES,
    PREPARE_VA,
    QUORUM_BRANCH_BYTES,
    QUORUM_BRANCH_PATCHED,
    QUORUM_BRANCH_VA,
    RESOLUTION_MASK_BYTES,
    RESOLUTION_MASK_PATCHED,
    RESOLUTION_MASK_VA,
    REVEAL_CALL_BYTES,
    REVEAL_CALL_VA,
    SEATED_OFFSET,
    SECTION_NAME,
    SHROUD_REVEAL_ALL,
    SLOT_KIND_TEST_BYTES,
    SLOT_KIND_TEST_VA,
    START_POSITION_BYTES,
    START_POSITION_VA,
    build_cave,
)
from sage_patch.utils import find_section, va_to_offset  # noqa: E402

IMAGE_BASE = 0x400000


def synthetic_image() -> bytearray:
    """A PE32 image mapping every site this patch asserts or replaces, holding exactly what the
    real ``2.01.2614.37001`` build holds there - so the whole apply + verify path runs in CI
    without the copyrighted `game.dat`, and a patch aimed at a wrong address fails here too."""
    highest = 0x00B4E000 - IMAGE_BASE  # room for the shroud reveal, the furthest site
    data = bytearray(((highest + 0x400) // 0x200 + 1) * 0x200)

    data[0:2] = b"MZ"
    e = 0x80
    struct.pack_into("<I", data, 0x3C, e)
    data[e : e + 4] = b"PE\x00\x00"
    struct.pack_into("<H", data, e + 4, 0x14C)  # Machine (i386)
    struct.pack_into("<H", data, e + 6, 1)  # NumberOfSections
    struct.pack_into("<H", data, e + 20, 0xE0)  # SizeOfOptionalHeader
    opt = e + 24
    struct.pack_into("<H", data, opt, 0x10B)  # PE32 magic
    struct.pack_into("<I", data, opt + 28, IMAGE_BASE)
    struct.pack_into("<I", data, opt + 32, 0x1000)  # SectionAlignment
    struct.pack_into("<I", data, opt + 36, 0x200)  # FileAlignment
    struct.pack_into("<I", data, opt + 56, 0x2000000)  # SizeOfImage
    struct.pack_into("<I", data, opt + 60, 0x400)  # SizeOfHeaders, room for more headers
    header = bytearray(40)
    header[0:8] = b".text\x00\x00\x00"
    size = len(data) - 0x1000
    struct.pack_into("<IIII", header, 8, size, 0x1000, size, 0x1000)
    data[opt + 0xE0 : opt + 0xE0 + 40] = header

    def write(va: int, blob: bytes) -> None:
        data[va - IMAGE_BASE : va - IMAGE_BASE + len(blob)] = blob

    write(PREPARE_VA, PREPARE_BYTES)
    write(QUORUM_BRANCH_VA, QUORUM_BRANCH_BYTES)
    write(RESOLUTION_MASK_VA, RESOLUTION_MASK_BYTES)
    write(SLOT_KIND_TEST_VA, SLOT_KIND_TEST_BYTES)
    write(NUMBER_VA, NUMBER_BYTES)
    write(FACTION_TEST_VA, FACTION_TEST_BYTES)
    write(ASSIGN_NAME_VA, ASSIGN_NAME_BYTES)
    write(REVEAL_CALL_VA, REVEAL_CALL_BYTES)
    write(START_POSITION_VA, START_POSITION_BYTES)
    for va, blob, _what in ANCHORS:
        write(va, blob)
    return data


@pytest.fixture
def image() -> bytearray:
    return synthetic_image()


def _patched(image: bytearray) -> bytearray:
    data = bytearray(image)
    WotrBattleObserversPatch().apply(data)
    return data


def _cave_va(data: bytes | bytearray) -> int:
    located = find_section(data, SECTION_NAME)
    assert located is not None
    return located[0]


def _disasm(data: bytes | bytearray, va: int, length: int) -> list[tuple[str, str]]:
    off = va_to_offset(data, va)
    assert off is not None
    md = Cs(CS_ARCH_X86, CS_MODE_32)
    return [(i.mnemonic, i.op_str) for i in md.disasm(bytes(data[off : off + length]), va)]


#: How each hook ends: the two that force a comparison return from either arm, and the two that
#: produce a value have a single exit every early failure falls through to.
_ROUTINE_END = {
    "hook_prepare": ("ret", 1),
    "hook_name": ("ret", 2),
    "hook_faction": ("ret", 2),
    "hook_assign": ("ret", 1),
    "hook_reveal": ("ret", 1),
    "hook_number": ("ret", 1),
}


def _routine(data: bytes | bytearray, name: str) -> list[tuple[str, str]]:
    """One hook, disassembled from its entry point to the instruction that ends it."""
    terminator, wanted = _ROUTINE_END[name]
    entry = build_cave(_cave_va(data))[1][name]
    body: list[tuple[str, str]] = []
    seen = 0
    for instruction in _disasm(data, entry, 0x200):
        body.append(instruction)
        if instruction[0] == terminator:
            seen += 1
            if seen == wanted:
                return body
    raise AssertionError(f"{name} does not end in {wanted} x {terminator}")


def test_apply_then_verify(image):
    data = _patched(image)
    assert WotrBattleObserversPatch().verify(data) == []


def test_an_unpatched_image_does_not_verify(image):
    problems = WotrBattleObserversPatch().verify(image)
    assert problems and SECTION_NAME in problems[0]


def test_detect_finds_it_only_once_applied(image):
    assert WotrBattleObserversPatch.detect(image) is None
    assert WotrBattleObserversPatch.detect(_patched(image)) is not None


def test_applying_twice_fails_rather_than_double_patching(image):
    data = _patched(image)
    with pytest.raises(ValueError, match=SECTION_NAME):
        WotrBattleObserversPatch().apply(data)


def test_it_writes_a_file(tmp_path, image):
    src = tmp_path / "game.dat"
    src.write_bytes(bytes(image))
    out = apply_patches(src, [WotrBattleObserversPatch()], output=tmp_path / "patched.dat")
    assert WotrBattleObserversPatch().verify(out.read_bytes()) == []


def test_the_gate_becomes_an_unconditional_skip(image):
    """The `jge` that honours the vote when the battle has enough participants becomes a `jmp`,
    so the forced auto-resolve below it is never reached. Same length, same target."""
    data = _patched(image)
    stock = _disasm(image, QUORUM_BRANCH_VA, len(QUORUM_BRANCH_BYTES))
    patched = _disasm(data, QUORUM_BRANCH_VA, len(QUORUM_BRANCH_PATCHED))
    assert stock[0][0] == "jge"
    assert patched[0][0] == "jmp"
    assert patched[0][1] == stock[0][1], "the branch has to land where the stock one did"


def test_the_button_mask_gains_the_real_time_bit_without_losing_auto_resolve(image):
    """The prompt shifts this mask into its three buttons, bit 3 being Real Time. Stock, the arm
    reached when the battle has fewer participants than the session has humans sets only bit 1, so
    the button greys out and the vote the logic gate would now honour can never be cast. Widening
    the constant offers both, which is what leaves auto-resolve available as it always was."""
    data = _patched(image)
    stock = _disasm(image, RESOLUTION_MASK_VA, len(RESOLUTION_MASK_BYTES))
    patched = _disasm(data, RESOLUTION_MASK_VA, len(RESOLUTION_MASK_PATCHED))
    assert stock == [("or", "dword ptr [ebp - 8], 2")]
    assert patched == [("or", "dword ptr [ebp - 8], 0xa")]
    assert len(RESOLUTION_MASK_PATCHED) == len(RESOLUTION_MASK_BYTES)


def test_both_copies_of_the_participant_rule_are_cleared(image):
    """The count is compared in two places and the client's runs first. A build carrying only one
    of the two edits still greys the button, which is the failure this pair exists to prevent."""
    data = _patched(image)
    edits = WotrBattleObserversPatch()._edits(_cave_va(data))
    assert {QUORUM_BRANCH_VA, RESOLUTION_MASK_VA} <= {site for site, _s, _n, _note in edits}


@pytest.mark.parametrize(
    ("site", "stock", "entry", "pad"),
    [
        (PREPARE_VA, PREPARE_BYTES, "hook_prepare", "nop"),
        (SLOT_KIND_TEST_VA, SLOT_KIND_TEST_BYTES, "hook_name", "nop"),
        (NUMBER_VA, NUMBER_BYTES, "hook_number", "nop"),
        (FACTION_TEST_VA, FACTION_TEST_BYTES, "hook_faction", None),
        (ASSIGN_NAME_VA, ASSIGN_NAME_BYTES, "hook_assign", "nop"),
        (REVEAL_CALL_VA, REVEAL_CALL_BYTES, "hook_reveal", None),
    ],
)
def test_each_site_detours_to_its_own_entry_point(image, site, stock, entry, pad):
    """A `call` detour's pad is executed on the way back, so it is a `nop`; the `jmp` detour's is
    unreachable, so it is an `int3` that faults rather than running half an instruction."""
    data = _patched(image)
    expected = build_cave(_cave_va(data))[1][entry]
    body = _disasm(data, site, len(stock))
    verb = "call"
    assert body[0] == (verb, hex(expected))
    assert {mnemonic for mnemonic, _ops in body[1:]} == ({pad} if pad else set())


def test_the_prepare_hook_puts_a_skipped_seat_back_into_both_loops(image):
    """`buildSidesFromGameInfo` skips a slot whose `isOccupied` is false, and the engine leaves
    `m_isOccupied` clear on a seat that is not in this battle - so without this pre-pass none of
    the other hooks are reached for it at all, and the client lands on `PlyrCivilian`. Measured
    live 2026-09-06: 1 on the two seats fighting, 0 on the third human."""
    data = _patched(image)
    body = _routine(data, "hook_prepare")
    assert body[0] == ("mov", "dword ptr [ebp - 0x20], eax"), "the displaced GameInfo store"
    assert body[1] == ("mov", "dword ptr [ebp - 0x18], ebx"), "the displaced counter zeroing"
    assert body[2] == ("pushal", ""), "everything after this is the cave's own"
    assert ("mov", f"byte ptr [esi + {hex(GAME_SLOT_IS_OCCUPIED)}], 1") in body
    assert ("call", hex(GAME_INFO_GET_SLOT)) in body
    assert body[-1] == ("ret", "") and body[-2] == ("popal", "")


def test_the_reveal_hook_keeps_the_full_map_for_a_replay(image):
    """The map-wide reveal is right for a replay, where the observer is the audience and there is
    nobody to watch through. It is skipped only when the pre-pass actually seated somebody, so the
    flag is read and the stock routine stays reachable."""
    data = _patched(image)
    body = _routine(data, "hook_reveal")
    assert body[0][0] == "cmp" and hex(_cave_va(data) + SEATED_OFFSET) in body[0][1]
    assert ("jmp", hex(SHROUD_REVEAL_ALL)) in body, "the reveal arm tail-jumps to the stock one"


def test_the_reveal_hook_agrees_with_the_stock_callee_about_the_stack(image):
    """The stock routine takes one stack argument and cleans it (`ret 4`). The skip arm has to do
    the same, or `startNewGame` returns into a corrupted frame."""
    data = _patched(image)
    body = _routine(data, "hook_reveal")
    assert body[-1] == ("ret", "4")


def test_the_prepare_hook_records_that_it_seated_somebody(image):
    """The flag the reveal hook reads: cleared at the top of every pre-pass so a later game cannot
    inherit an earlier one's answer, and set beside the occupied byte."""
    data = _patched(image)
    body = _routine(data, "hook_prepare")
    flag = hex(_cave_va(data) + SEATED_OFFSET)
    assert any(m == "and" and flag in o for m, o in body), "cleared each run"
    assert any(m == "mov" and flag in o and o.endswith(", 1") for m, o in body), "set when marking"


def test_the_prepare_hook_only_marks_seats_the_predicate_picks(image):
    """It is the same predicate the naming hooks ask, so a seat that *is* fighting, an AI seat and
    a lobby observer are all left exactly as the engine set them."""
    data = _patched(image)
    entries = build_cave(_cave_va(data))[1]
    body = _routine(data, "hook_prepare")
    calls = [ops for mnemonic, ops in body if mnemonic == "call"]
    assert hex(entries["hook_prepare"]) not in calls, "no recursion"
    assert any(int(c, 16) > _cave_va(data) for c in calls), "it calls the shared predicate"


def test_the_name_hook_ends_on_the_comparison_the_caller_branches_on(image):
    """The caller's next instruction is a `jl`, so the last thing either arm does before `ret`
    has to be the comparison that sets its flags. The displaced `mov` goes first precisely
    because it sets none."""
    data = _patched(image)
    body = _routine(data, "hook_name")
    assert body[0] == ("mov", "dword ptr [ebp - 4], ebx"), "the displaced store, flag-free"
    rets = [i for i, (mnemonic, _ops) in enumerate(body) if mnemonic == "ret"]
    assert len(rets) == 2
    for index in rets:
        assert body[index - 1][0] == "cmp"


def test_the_observer_arms_force_a_negative_comparison(image):
    """`Observer_%d` and `FactionObserver` are both chosen by a `jl` on the slot's player
    template, so making a seat an observer is exactly making that comparison negative."""
    data = _patched(image)
    for name, verb in (("hook_name", "cmp"), ("hook_faction", "test")):
        body = _routine(data, name)
        tail = body[-3:]
        assert tail[0] == ("mov", "eax, 0xffffffff")
        assert tail[1][0] == verb
        assert tail[2][0] == "ret"


def test_the_name_hook_reproduces_the_stock_comparison_on_the_other_arm(image):
    """A seat that is fighting has to reach the stock `jl` with the stock flags, or every normal
    battle changes too."""
    data = _patched(image)
    body = _routine(data, "hook_name")
    assert ("cmp", "dword ptr [esi + 0x18], ebx") in body


def test_the_faction_hook_still_returns_the_template_index(image):
    """The arm that is not an observer falls into `ThePlayerTemplateStore` indexed by `eax`, so
    the hook has to hand the index back as well as the flags."""
    data = _patched(image)
    body = _routine(data, "hook_faction")
    assert ("mov", "eax, dword ptr [esi + 0x18]") in body


def test_the_assign_hook_renames_the_seat_to_the_side_that_always_exists(image):
    """`Observer_%d` names a side no War of the Ring map declares, so a seat given that name gets
    no side, nothing marks it local, and the client is seated on `PlyrCivilian`. The one side
    every game carries is `ReplayObserver`, so that is the literal the hook assigns - and it
    assigns it through the engine's own `AsciiString::operator=`, the helper the `Player_1` arm
    just above the hook site already uses."""
    data = _patched(image)
    section_va = _cave_va(data)
    blob, _entries = build_cave(section_va)
    body = _routine(data, "hook_assign")
    assert body[0] == ("cmp", f"byte ptr [{hex(section_va)}], 0"), "the flag hook_name left"
    assert ("push", hex(section_va + NAME_OFFSET)) in body
    assert ("call", hex(ASCII_STRING_ASSIGN)) in body
    name = bytes(blob[NAME_OFFSET : NAME_OFFSET + len(OBSERVER_SIDE_NAME) + 1])
    assert name == OBSERVER_SIDE_NAME + b"\x00", "the literal is NUL-terminated in the cave"


def test_the_assign_hook_leaves_the_displaced_leas_last(image):
    """The caller's next instruction is `push eax` into `AsciiString::operator=`, so both
    displaced `lea`s have to survive the hook - which means they come *after* the `popad`, not
    before it."""
    data = _patched(image)
    body = _routine(data, "hook_assign")
    assert body[-3:] == [
        ("lea", "eax, [ebp - 0x1c]"),
        ("lea", "ecx, [esi + 0x34]"),
        ("ret", ""),
    ]
    mnemonics = [mnemonic for mnemonic, _ops in body]
    assert mnemonics.index("popal") < mnemonics.index("ret")


def test_every_predicate_call_is_wrapped_in_pushad(image):
    """The seating hooks run inside functions that are carrying live registers - the slot,
    the zero constant, the player just looked up - and the predicate clobbers most of them."""
    data = _patched(image)
    for name in ("hook_name", "hook_faction"):
        body = _routine(data, name)
        mnemonics = [mnemonic for mnemonic, _ops in body]
        assert mnemonics.count("pushal") == 1
        assert mnemonics.count("popal") == 1
        assert mnemonics.index("pushal") < mnemonics.index("popal")


def test_the_number_hook_writes_the_stock_answer_before_anything_can_fail(image):
    """Every early exit lands on the same `popad` / load / `ret`, so the fallback has to already
    be in place by then: the stock number is written second, before the first test."""
    data = _patched(image)
    body = _routine(data, "hook_number")
    assert body[0] == ("pushal", "")
    assert body[1] == ("mov", "eax, dword ptr [ebp - 0x18]")
    assert ("add", "eax, 2") in body[:6]
    assert body[-1] == ("ret", "")
    assert body[-2][0] == "mov" and body[-2][1].startswith("eax, dword ptr [")
    assert body[-3] == ("popal", "")


def test_the_cave_calls_only_the_three_routines_it_fingerprints(image):
    """A call the anchors do not cover is a call this patch cannot promise is the right function
    on any other build."""
    data = _patched(image)
    section_va = _cave_va(data)
    blob, _entries = build_cave(section_va)
    body = _disasm(data, section_va + CODE_OFFSET, len(blob) - CODE_OFFSET)
    external = {ops for mnemonic, ops in body if mnemonic == "call" and int(ops, 16) < section_va}
    assert external == {
        hex(ASCII_STRING_ASSIGN),
        hex(GAME_INFO_GET_SLOT),
        hex(LIVING_WORLD_CURRENT_REGION),
        hex(LIVING_WORLD_FIND_PLAYER_BY_ID),
    }


def test_the_scratch_area_starts_zeroed(image):
    """`hook_number`'s fallback and the predicate's answer both live there, and the section's raw
    data is what says so - an uninitialised cave would carry whatever the file had."""
    data = _patched(image)
    located = find_section(data, SECTION_NAME)
    assert located is not None
    _va, off, _vsize = located
    assert bytes(data[off : off + DATA_SIZE]) == bytes(DATA_SIZE)


@pytest.mark.parametrize("index", range(len(ANCHORS)))
def test_a_build_missing_any_anchor_refuses(image, index):
    va, blob, _what = ANCHORS[index]
    off = va_to_offset(image, va)
    assert off is not None
    image[off : off + len(blob)] = b"\x90" * len(blob)
    with pytest.raises(ValueError, match=f"0x{va:08x}"):
        WotrBattleObserversPatch().apply(image)


@pytest.mark.parametrize(
    ("site", "stock"),
    [
        (PREPARE_VA, PREPARE_BYTES),
        (QUORUM_BRANCH_VA, QUORUM_BRANCH_BYTES),
        (RESOLUTION_MASK_VA, RESOLUTION_MASK_BYTES),
        (SLOT_KIND_TEST_VA, SLOT_KIND_TEST_BYTES),
        (NUMBER_VA, NUMBER_BYTES),
        (FACTION_TEST_VA, FACTION_TEST_BYTES),
        (ASSIGN_NAME_VA, ASSIGN_NAME_BYTES),
        (REVEAL_CALL_VA, REVEAL_CALL_BYTES),
    ],
)
def test_a_build_whose_site_reads_differently_refuses(image, site, stock):
    off = va_to_offset(image, site)
    assert off is not None
    image[off : off + len(stock)] = b"\x90" * len(stock)
    with pytest.raises(ValueError):
        WotrBattleObserversPatch().apply(image)
