"""Tests for the skirmish-replay patch.

Two hand-assembled routines that cannot be executed here, so the important tests disassemble
them back and assert they say what they were meant to say - a wrong byte in a hook does not
raise, it crashes the game.

The two routines have different failure modes and are checked for different things. The
whitelist routine is a jump target inside a live loop, so what matters is that it gives back
every register it borrows and lands on the recorder's own two exits. The naming routine
replaces a normal function, so what matters is that it is stack-balanced across three foreign
calling conventions (stdcall `GetLocalTime`, cdecl variadic `swprintf`, thiscall `ret 4`
constructor) and still returns the caller's argument.
"""

from __future__ import annotations

import argparse
import faulthandler
import struct

import pytest

pytest.importorskip("capstone", reason="the [patch] extra (capstone) is not installed")
from capstone import CS_ARCH_X86, CS_MODE_32, Cs  # noqa: E402 - after the importorskip guard

pytest.importorskip("unicorn", reason="the [patch] extra (unicorn) is not installed")
from unicorn import UC_ARCH_X86, UC_HOOK_CODE, UC_MODE_32, Uc  # noqa: E402
from unicorn.x86_const import (  # noqa: E402
    UC_X86_REG_EAX,
    UC_X86_REG_EBP,
    UC_X86_REG_EBX,
    UC_X86_REG_ECX,
    UC_X86_REG_EDI,
    UC_X86_REG_EDX,
    UC_X86_REG_EIP,
    UC_X86_REG_ESI,
    UC_X86_REG_ESP,
)

from sage_patch.addresses import (  # noqa: E402
    DELETE_FILE_W_IAT,
    FIND_CLOSE_IAT,
    FIND_FIRST_FILE_W_IAT,
    FIND_NEXT_FILE_W_IAT,
    GAME_INFO_MAP,
    GAME_MODE_SKIRMISH,
    IMPORT_GET_LOCAL_TIME,
    IMPORT_SWPRINTF,
    IMPORT_WCSCMP,
    RECORDER_END_WRITE_CALL,
    RECORDER_END_WRITE_CALL_BYTES,
    RECORDER_GAME_MODE,
    RECORDER_GAME_MODE_RESET,
    RECORDER_LAST_REPLAY_NAME,
    RECORDER_MODE_GATE,
    RECORDER_MODE_GATE_ACCEPT,
    RECORDER_MODE_GATE_BYTES,
    RECORDER_MODE_GATE_REJECT,
    RECORDER_NAME_CALL,
    RECORDER_NAME_CALL_BYTES,
    RECORDER_NAME_CALL_FINGERPRINT,
    RECORDER_NEW_GAME_BRANCH,
    RECORDER_NEW_GAME_BRANCH_BYTES,
    RECORDER_RECORDED_MODES,
    START_RECORDING_MODE_ARG,
    START_RECORDING_REPLAY_DIR,
    THE_GAME_INFO,
    THE_RECORDER,
    THE_SKIRMISH_GAME_INFO,
    UNICODE_STRING_FROM_WIDE,
)
from sage_patch.patches.multiplayer import skirmish_replay  # noqa: E402
from sage_patch.patches.multiplayer.skirmish_replay import (
    DEFAULT_KEEP,
    DEFAULT_MODES,
    DIR_MAX,
    FORMAT,
    GATE_CODE_OFF,
    ILLEGAL_CHARACTERS,
    KEEP_OFF,
    MAP_MAX,
    MAX_DELETES,
    MAX_MODES,
    MODE_COUNT_OFF,
    MODE_TABLE_OFF,
    NAME_CODE_OFF,
    PRUNE_CODE_OFF,
    RENAME_ADDED,
    RENAME_ALL,
    SECTION_NAME,
    SkirmishReplayPatch,
    build_section,
)
from sage_patch.pe import image_sections
from sage_patch.utils import append_section, find_section, next_section_rva, va_to_offset

IMAGE_BASE = 0x400000
BASE = 0x00F00000

_NAME_CALL_START = RECORDER_NAME_CALL - RECORDER_NAME_CALL_FINGERPRINT.index(
    RECORDER_NAME_CALL_BYTES
)


def synthetic_image() -> bytearray:
    """A PE32 image mapping the two patch sites and the fingerprints that identify them, with
    the real original bytes planted, so the whole apply + verify path runs without the
    copyrighted `game.dat`."""
    highest = max(RECORDER_MODE_GATE + 0x40, RECORDER_NAME_CALL + 0x40) - IMAGE_BASE
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
    struct.pack_into("<I", data, opt + 60, 0x400)  # SizeOfHeaders, room for a 2nd header
    header = bytearray(40)
    header[0:8] = b".text\x00\x00\x00"
    size = len(data) - 0x1000
    struct.pack_into("<IIII", header, 8, size, 0x1000, size, 0x1000)
    data[opt + 0xE0 : opt + 0xE0 + 40] = header

    def plant(va: int, raw: bytes) -> None:
        data[va - IMAGE_BASE : va - IMAGE_BASE + len(raw)] = raw

    plant(RECORDER_NEW_GAME_BRANCH, RECORDER_NEW_GAME_BRANCH_BYTES)
    plant(RECORDER_MODE_GATE, RECORDER_MODE_GATE_BYTES)
    plant(_NAME_CALL_START, RECORDER_NAME_CALL_FINGERPRINT)
    return data


def patched_image(patch: SkirmishReplayPatch | None = None) -> bytearray:
    data = synthetic_image()
    (patch or SkirmishReplayPatch()).apply(data)
    return data


def _disassemble(code: bytes, at: int) -> list:
    return list(Cs(CS_ARCH_X86, CS_MODE_32).disasm(code, at))


def gate_text(base: int = BASE, modes: tuple[int, ...] = DEFAULT_MODES) -> list[str]:
    body = build_section(base, modes)[GATE_CODE_OFF:NAME_CODE_OFF].rstrip(b"\xcc")
    return [f"{i.mnemonic} {i.op_str}" for i in _disassemble(body, base + GATE_CODE_OFF)]


def name_text(
    base: int = BASE,
    modes: tuple[int, ...] = DEFAULT_MODES,
    rename_all: bool = True,
    keep: int = 0,
) -> list[str]:
    """The naming routine alone. `keep` defaults to 0 here so the naming tests read the routine
    without the one `call` pruning puts in front of it; the pruning tests ask for it."""
    body = build_section(base, modes, rename_all, keep)[NAME_CODE_OFF:PRUNE_CODE_OFF]
    body = body.rstrip(b"\xcc")
    return [f"{i.mnemonic} {i.op_str}" for i in _disassemble(body, base + NAME_CODE_OFF)]


def test_apply_replaces_the_whitelist_tail_with_a_jump_into_the_cave():
    data = patched_image()
    section_va, _, _ = find_section(data, SECTION_NAME)
    off = va_to_offset(data, RECORDER_MODE_GATE)
    assert data[off] == 0xE9  # a jmp, not a call: this is a branch inside a function
    target = RECORDER_MODE_GATE + 5 + struct.unpack_from("<i", data, off + 1)[0]
    assert target == section_va + GATE_CODE_OFF


def test_the_bytes_the_jump_does_not_use_are_nop():
    """The whitelist tail is nine bytes and the jump is five. Nothing branches into the
    remainder - the only way in was the fall-through the jump replaced - but leaving the old
    `jne`'s displacement there would disassemble as garbage next to live code."""
    data = patched_image()
    off = va_to_offset(data, RECORDER_MODE_GATE)
    assert bytes(data[off + 5 : off + len(RECORDER_MODE_GATE_BYTES)]) == b"\x90" * 4


def test_apply_retargets_the_name_call_and_keeps_it_a_call():
    """`startRecording` cleans the argument itself (`pop ecx`), so the site has to stay a
    `call` - a `jmp` would leave the helper returning to `startRecording`'s caller."""
    data = patched_image()
    section_va, _, _ = find_section(data, SECTION_NAME)
    off = va_to_offset(data, RECORDER_NAME_CALL)
    assert data[off] == 0xE8
    target = RECORDER_NAME_CALL + 5 + struct.unpack_from("<i", data, off + 1)[0]
    assert target == section_va + NAME_CODE_OFF


def test_apply_then_verify_is_clean():
    assert SkirmishReplayPatch().verify(patched_image()) == []


def test_verify_rejects_an_unpatched_image():
    assert SkirmishReplayPatch().verify(synthetic_image()) == [f"{SECTION_NAME} section is absent"]


def test_verify_rejects_a_different_mode_set():
    """`verify` re-derives from the arguments it was given, so a binary built for skirmish does
    not verify as one built for something else."""
    problems = SkirmishReplayPatch(modes=(4,)).verify(patched_image())
    assert any("mode table" in problem for problem in problems)


def test_apply_is_not_repeatable():
    data = patched_image()
    with pytest.raises(ValueError, match="expected"):
        SkirmishReplayPatch().apply(data)


def test_apply_refuses_when_the_new_game_branch_moved():
    """A bare `cmp eax, 5` says nothing about which comparison it is; the 63 bytes above it -
    the message-type test, the argument fetch, the `TheGameLogic` gate - do."""
    data = synthetic_image()
    off = va_to_offset(data, RECORDER_NEW_GAME_BRANCH)
    data[off] = 0x90
    with pytest.raises(ValueError, match="game-mode whitelist"):
        SkirmishReplayPatch().apply(data)


def test_apply_refuses_when_the_name_call_context_moved():
    data = synthetic_image()
    off = va_to_offset(data, _NAME_CALL_START)
    data[off] = 0x90
    with pytest.raises(ValueError, match="getLastReplayFileName"):
        SkirmishReplayPatch().apply(data)


def test_the_guards_are_checked_before_anything_is_written():
    """A refused apply must leave the image untouched, not carrying an orphan cave or a gate
    hook with no naming hook."""
    data = synthetic_image()
    before = bytes(data)
    off = va_to_offset(data, _NAME_CALL_START)
    data[off] = 0x90
    with pytest.raises(ValueError):
        SkirmishReplayPatch().apply(data)
    data[off] = before[off]
    assert bytes(data) == before


@pytest.mark.parametrize("mode", RECORDER_RECORDED_MODES)
def test_a_mode_the_engine_already_records_is_refused(mode: int):
    """Adding one would not enable anything - it would only divert that mode's recordings to
    the new naming, which is the one thing this patch promises not to do."""
    with pytest.raises(ValueError, match="already recorded"):
        SkirmishReplayPatch(modes=(mode,))


@pytest.mark.parametrize("modes", [(), (0,), (256,), tuple(range(10, 10 + MAX_MODES + 1))])
def test_an_unusable_mode_set_is_refused(modes: tuple[int, ...]):
    with pytest.raises(ValueError):
        SkirmishReplayPatch(modes=modes)


def test_the_gate_still_accepts_the_mode_the_replaced_bytes_tested():
    """The nine bytes taken were `cmp eax, 5` / `jne`. Mode 5 has to survive the move, or the
    patch turns off recording for the network flavour that used it."""
    assert gate_text()[0] == f"cmp eax, {RECORDER_RECORDED_MODES[1]}"


def test_the_gate_lands_on_the_recorders_own_two_exits():
    body = gate_text()
    jumps = {line for line in body if line.startswith("jmp 0x")}
    assert f"jmp {RECORDER_MODE_GATE_ACCEPT:#x}" in jumps
    assert f"jmp {RECORDER_MODE_GATE_REJECT:#x}" in jumps


def test_the_gate_gives_back_every_register_it_borrows():
    """It is entered mid-function with the recorder's loop live in ebx/esi/edi/ebp and `ebx`
    already holding the default arg1, so only ecx and edx may be touched - and *both* exits
    have to restore them, since the table walk can leave by either."""
    body = gate_text()
    assert [line for line in body if line.startswith(("push ", "pop "))] == [
        "push ecx",
        "push edx",
        "pop edx",
        "pop ecx",  # the accept path
        "pop edx",
        "pop ecx",  # the reject path
    ]
    exits = {f"jmp {RECORDER_MODE_GATE_ACCEPT:#x}", f"jmp {RECORDER_MODE_GATE_REJECT:#x}"}
    assert exits <= set(body)
    for index, line in enumerate(body):
        if line in exits:
            assert body[index - 2 : index] == ["pop edx", "pop ecx"]


def test_the_gate_reads_the_mode_table_rather_than_unrolling_it():
    """The table is what `verify` reads back, so the code has to agree with it by construction
    rather than by both being generated from the same list."""
    section = build_section(BASE, (2, 6))
    count = struct.unpack_from("<I", section, MODE_COUNT_OFF)[0]
    table = struct.unpack_from("<2I", section, MODE_TABLE_OFF)
    assert (count, table) == (2, (2, 6))
    body = gate_text(modes=(2, 6))
    assert f"mov ecx, dword ptr [{BASE + MODE_COUNT_OFF:#x}]" in body
    assert f"mov edx, {BASE + MODE_TABLE_OFF:#x}" in body
    assert gate_text(modes=(2,)) == body  # the code does not vary with the mode count


def test_renaming_everything_is_the_default_and_asks_no_questions():
    """The whole point of the default is that no recording keeps the fixed name, so there is
    nothing to decide and the routine never consults the mode or the stock helper."""
    assert SkirmishReplayPatch().rename == RENAME_ALL
    body = name_text(rename_all=True)
    assert body[:3] == ["push ebx", "push esi", "push edi"]
    assert f"jmp {RECORDER_LAST_REPLAY_NAME:#x}" not in body


def test_renaming_only_the_added_modes_falls_back_to_the_stock_helper():
    """The conservative setting: a mode the engine already recorded keeps the stock name, so
    the replay menu's Save Replay button goes on working. The fall-back is a tail `jmp` - the
    argument is still on the stack and the helper's own `ret` is the answer."""
    body = name_text(rename_all=False)
    assert f"jmp {RECORDER_LAST_REPLAY_NAME:#x}" in body
    assert f"call {RECORDER_LAST_REPLAY_NAME:#x}" not in body


def test_the_mode_is_read_from_start_recordings_argument():
    """The first instruction, before anything can clobber the frame."""
    assert name_text(rename_all=False)[0] == (
        f"mov eax, dword ptr [ebp + {START_RECORDING_MODE_ARG:#x}]"
    )


@pytest.mark.parametrize("rename_all", [True, False])
def test_the_name_routine_never_reads_the_recorders_cached_mode(rename_all: bool):
    """`startRecording` calls `reset()` before it names the file, and that writes the sentinel
    9 over `m_gameMode` (`0x0077D7D2`). The first version of this patch read the field here and
    fell back to the stock name on every single skirmish - a regression test, not a style rule.
    """
    body = name_text(rename_all=rename_all)
    assert f"mov eax, dword ptr [{THE_RECORDER:#x}]" not in body
    assert not any(f"+ {RECORDER_GAME_MODE:#x}" in line for line in body)
    assert RECORDER_GAME_MODE_RESET == 9


def test_verify_rejects_the_other_rename_scope():
    """The scope changes what the binary does to *network* replays, so a build made one way
    must not verify as the other."""
    data = patched_image(SkirmishReplayPatch(rename=RENAME_ALL))
    problems = SkirmishReplayPatch(rename=RENAME_ADDED).verify(data)
    assert any("renames" in problem for problem in problems)
    assert SkirmishReplayPatch(rename=RENAME_ALL).verify(data) == []


def test_an_unknown_rename_scope_is_refused():
    with pytest.raises(ValueError, match="rename must be"):
        SkirmishReplayPatch(rename="sometimes")


def test_the_name_routine_takes_the_map_from_the_game_info():
    body = name_text()
    assert f"mov ecx, dword ptr [{THE_GAME_INFO:#x}]" in body
    assert f"mov ecx, dword ptr [{THE_SKIRMISH_GAME_INFO:#x}]" in body
    assert f"mov esi, dword ptr [ecx + {GAME_INFO_MAP:#x}]" in body
    assert "add esi, 8" in body  # an AsciiString's characters begin at +8


def test_the_name_routine_preserves_the_callee_saved_registers():
    body = name_text()
    for register in ("ebx", "esi", "edi"):
        assert body.count(f"push {register}") == 1
        assert body.count(f"pop {register}") == 1


def test_the_swprintf_call_is_cdecl_balanced():
    """Nine dwords - the buffer, the format and six date fields - cleaned by the caller. An
    unbalanced variadic call here would corrupt `startRecording`'s frame."""
    body = name_text()
    call = body.index(f"call dword ptr [{IMPORT_SWPRINTF:#x}]")
    assert body[call + 1] == "add esp, 0x24"
    assert len([line for line in body[:call] if line.startswith("push")]) >= 9


def test_get_local_time_is_called_without_cleaning_after_it():
    """`GetLocalTime` is stdcall and cleans its own argument; adding an `add esp, 4` would
    unbalance the frame just as surely as omitting one after `swprintf`."""
    body = name_text()
    call = body.index(f"call dword ptr [{IMPORT_GET_LOCAL_TIME:#x}]")
    assert body[call - 1].startswith("push 0x")
    assert not body[call + 1].startswith("add esp")


def test_the_string_is_built_with_the_engines_own_constructor():
    """`UnicodeString::UnicodeString(const WideChar *)` zeroes before it assigns, which is what
    makes it correct on the uninitialised storage `startRecording` hands out."""
    body = name_text()
    call = body.index(f"call {UNICODE_STRING_FROM_WIDE:#x}")
    assert body[call - 2] == "mov ecx, dword ptr [esp + 0x10]"  # this = the caller's storage
    assert body[call - 1].startswith("push 0x")  # the formatted name
    assert body[call + 1 : call + 4] == ["pop edi", "pop esi", "pop ebx"]


def test_the_routine_returns_the_storage_it_was_given():
    body = name_text()
    assert body[-2] == "mov eax, dword ptr [esp + 4]"
    assert body[-1] == "ret "


def test_the_map_copy_is_bounded_by_the_buffer():
    assert f"mov ecx, {MAP_MAX - 1:#x}" in name_text()  # room left for the terminator


def test_the_map_extension_is_stripped():
    """`GameInfo::m_map` is a full path with the file on the end - live, it reads
    `maps\\map wor forlindon\\map wor forlindon.map` - so the copy has to stop at the last `.`
    or the replay is called `... map wor forlindon.map.BfME2Replay`."""
    body = name_text()
    assert f"cmp eax, {ord('.'):#x}" in body
    assert "mov edi, ebx" in body  # truncate the destination at the remembered dot


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (r"maps\map wor forlindon\map wor forlindon.map", "map wor forlindon"),
        ("maps/map mp westfold/map mp westfold.map", "map mp westfold"),
        ("maps/map mp westfold", "map mp westfold"),  # the form the metadata `M=` carries
        ("", ""),
        (".map", ".map"),  # nothing but an extension: truncating would leave nothing
        ("a<b>c:d|e?f*g", "a_b_c_d_e_f_g"),
        ("x" * 200, "x" * (MAP_MAX - 1)),
    ],
)
def test_the_map_name_model(raw: str, expected: str):
    """A Python model of what the cave's copy loop does, so the intended output is written down
    somewhere executable. The asm is checked separately; this pins the *rules*."""
    basename = raw.replace("\\", "/").rsplit("/", 1)[-1]
    out = ""
    dot = None
    for character in basename[: MAP_MAX - 1]:
        if character == ".":
            dot = len(out)
        legal = 0x20 <= ord(character) <= 0x7E and character not in ILLEGAL_CHARACTERS
        out += character if legal else "_"
    if dot:  # a leading dot (index 0) is left alone, as is no dot at all
        out = out[:dot]
    assert out == expected


def test_every_illegal_file_name_character_is_substituted():
    body = name_text()
    for character in ILLEGAL_CHARACTERS:
        assert f"cmp eax, {ord(character):#x}" in body
    assert "cmp eax, 0x20" in body  # and everything below printable ASCII
    assert "cmp eax, 0x7e" in body  # and everything above it
    assert f"mov eax, {ord('_'):#x}" in body


def test_the_format_is_stored_as_a_wide_string():
    section = build_section(BASE)
    encoded = FORMAT.encode("utf-16-le") + b"\x00\x00"
    assert encoded in bytes(section)


def test_the_format_orders_the_name_so_it_sorts():
    assert FORMAT.startswith("%04d-%02d-%02d ")
    assert FORMAT.endswith("%s")  # the map last: it is what truncation should eat


def test_the_cave_is_position_independent_of_its_base():
    """Every absolute either routine holds is derived from the base it is built for, so the
    same body at a different base differs only in those - not in length or shape."""
    here, elsewhere = build_section(BASE), build_section(BASE + 0x10000)
    assert len(here) == len(elsewhere)
    for at in (GATE_CODE_OFF, NAME_CODE_OFF, PRUNE_CODE_OFF):
        mine = _disassemble(bytes(here[at:]), BASE + at)
        theirs = _disassemble(bytes(elsewhere[at:]), BASE + 0x10000 + at)
        assert [i.mnemonic for i in mine] == [i.mnemonic for i in theirs]


def test_the_whitelist_routine_fits_its_window():
    """`NAME_CODE_OFF` is a constant so both entry points can be named without deriving one
    from the other's length; that only holds while the first routine fits."""
    section = build_section(BASE, tuple(range(10, 10 + MAX_MODES)))
    assert section[NAME_CODE_OFF - 1] == 0xCC  # padded, not overrun


def test_the_default_is_the_skirmish_mode():
    assert DEFAULT_MODES == (GAME_MODE_SKIRMISH,)
    assert GAME_MODE_SKIRMISH not in RECORDER_RECORDED_MODES


def test_the_cave_lands_past_every_existing_section():
    data = patched_image()
    section_va, _, _ = find_section(data, SECTION_NAME)
    ours = section_va - IMAGE_BASE
    for section in image_sections(data):
        if section.name == SECTION_NAME:
            continue
        assert ours >= section.virtual_address - IMAGE_BASE + section.virtual_size


def test_it_still_applies_behind_another_patch_s_cave():
    clean = synthetic_image()
    SkirmishReplayPatch().apply(clean)
    alone_va, _, _ = find_section(clean, SECTION_NAME)

    stacked = synthetic_image()
    append_section(stacked, ".other", next_section_rva(stacked), b"\x90" * 0x40, 0x40000040)
    SkirmishReplayPatch().apply(stacked)
    behind_va, _, _ = find_section(stacked, SECTION_NAME)

    assert behind_va > alone_va
    assert SkirmishReplayPatch().verify(stacked) == []


def test_it_does_not_touch_the_bytes_replay_outcome_hooks():
    """Both patches edit `RecorderClass::updateRecord`; this one takes the `MSG_NEW_GAME`
    whitelist and `replay-outcome` takes the `writeToFile` call in the `MSG_CLEAR_GAME_DATA`
    branch, ~0x7B bytes apart. Rule 2 of composing patches, asserted rather than assumed."""
    ours = range(RECORDER_MODE_GATE, RECORDER_MODE_GATE + len(RECORDER_MODE_GATE_BYTES))
    theirs = range(
        RECORDER_END_WRITE_CALL, RECORDER_END_WRITE_CALL + len(RECORDER_END_WRITE_CALL_BYTES)
    )
    assert not set(ours) & set(theirs)
    # and neither reads what the other writes: our fingerprint stops before their site
    assert RECORDER_NEW_GAME_BRANCH + len(RECORDER_NEW_GAME_BRANCH_BYTES) <= RECORDER_END_WRITE_CALL


class TestDetect:
    """**The gate on parameter recovery.** `verify` only answers "does this file carry *this*
    configuration", so the default probe reports a binary recording any other mode set as
    unpatched - which is the case detection exists for."""

    def test_it_recovers_a_non_default_mode_set(self):
        patch = SkirmishReplayPatch(modes=(3, 4))
        data = patched_image(patch)
        found = SkirmishReplayPatch.detect(data)
        assert found is not None, "a patch recording other modes reports as absent"
        assert found.modes == (3, 4)

    @pytest.mark.parametrize("rename", [RENAME_ALL, RENAME_ADDED])
    def test_it_recovers_the_rename_scope(self, rename: str):
        data = patched_image(SkirmishReplayPatch(modes=(3,), rename=rename))
        found = SkirmishReplayPatch.detect(data)
        assert found is not None
        assert found.rename == rename

    def test_the_recovered_patch_verifies_against_the_binary_it_came_from(self):
        data = patched_image(SkirmishReplayPatch(modes=(3, 4), rename=RENAME_ADDED))
        assert SkirmishReplayPatch.detect(data).verify(data) == []

    def test_a_full_mode_table_round_trips(self):
        """The count is read from the cave and bounds the table read, so the largest legal table
        must come back whole rather than truncated."""
        modes = tuple(range(10, 10 + MAX_MODES))
        data = patched_image(SkirmishReplayPatch(modes=modes))
        assert SkirmishReplayPatch.detect(data).modes == modes

    def test_an_unpatched_image_carries_nothing(self):
        assert SkirmishReplayPatch.detect(synthetic_image()) is None

    def test_detection_never_raises_on_something_that_is_not_a_game_dat(self):
        assert SkirmishReplayPatch.detect(bytearray(b"MZ" + bytes(4096))) is None


# --- pruning -------------------------------------------------------------------------------
#
# The pruning routine is a loop over four Win32 calls and a `wcscmp`, which is too much logic to
# trust to a disassembly read. So it is *run*: Unicorn executes the real bytes, with each import
# slot pointing at a stub that answers from a Python model of the `Replays` folder.

_REPLAY_DIR = "C:\\Users\\me\\Replays\\"


def _own(day: int, second: int = 0, map_name: str = "map wor forlindon") -> str:
    return f"2026-11-{day:02d} 12-00-{second:02d} {map_name}.BfME2Replay"


class _FakeReplays:
    """Runs `_build_prune_code` on a fake replay folder and records what it did."""

    STUBS = 0x00100000
    STACK = 0x00200000
    STRING = 0x00300000
    SENTINEL = 0x00400000
    DIRECTORY = "<dir>"

    def __init__(
        self,
        files: list[str],
        keep: int = 10,
        directory: str | None = _REPLAY_DIR,
        delete_works: bool = True,
        delete_removes: bool = True,
    ) -> None:
        self.files = list(files)  # entries ending in DIRECTORY are folders
        self.directory = directory
        self.delete_works = delete_works
        self.delete_removes = delete_removes
        self.deleted: list[str] = []
        self.delete_calls = 0
        self.scans: list[str] = []
        self.open_handles = 0
        self._listing: list[str] = []

        self.section = build_section(BASE, keep=keep)
        uc = self.uc = Uc(UC_ARCH_X86, UC_MODE_32)
        size = (len(self.section) + 0xFFF) & ~0xFFF
        # `mem_map` raises and catches an SEH access violation inside Unicorn 2.1.4 on Windows;
        # every map succeeds, but the fault handler would print a stack for each one.
        was_enabled = faulthandler.is_enabled()
        faulthandler.disable()
        try:
            uc.mem_map(BASE, size)
            uc.mem_map(0x00BD0000, 0x1000)
            for region in (self.STUBS, self.STACK, self.STRING, self.SENTINEL):
                uc.mem_map(region, 0x10000)
        finally:
            if was_enabled:
                faulthandler.enable()
        uc.mem_write(BASE, self.section)
        uc.mem_write(self.SENTINEL, b"\xc3")

        stubs = {
            FIND_FIRST_FILE_W_IAT: (self._find_first, 2),
            FIND_NEXT_FILE_W_IAT: (self._find_next, 2),
            FIND_CLOSE_IAT: (self._find_close, 1),
            DELETE_FILE_W_IAT: (self._delete, 1),
            IMPORT_WCSCMP: (self._wcscmp, 0),  # cdecl: the caller cleans
        }
        self._by_address = {}
        for index, (slot, (handler, stdcall_args)) in enumerate(stubs.items()):
            address = self.STUBS + index * 0x10
            uc.mem_write(address, b"\xc3")
            uc.mem_write(slot, struct.pack("<I", address))
            self._by_address[address] = (handler, stdcall_args)

        def hook(uc, address, _size, _user):
            if address not in self._by_address:
                return
            handler, stdcall_args = self._by_address[address]
            esp = uc.reg_read(UC_X86_REG_ESP)
            ret, *args = struct.unpack("<5I", uc.mem_read(esp, 20))
            uc.reg_write(UC_X86_REG_EAX, handler(*args) & 0xFFFFFFFF)
            uc.reg_write(UC_X86_REG_ESP, esp + 4 + 4 * stdcall_args)
            uc.reg_write(UC_X86_REG_EIP, ret)

        uc.hook_add(UC_HOOK_CODE, hook, begin=self.STUBS, end=self.STUBS + 0x1000)

        # startRecording's frame: [ebp-0x2c] is the replay directory's UnicodeString.
        ebp = self.STACK + 0x8000
        if directory is None:
            uc.mem_write(ebp + START_RECORDING_REPLAY_DIR, struct.pack("<I", 0))
        else:
            uc.mem_write(self.STRING + 8, directory.encode("utf-16-le") + b"\x00\x00")
            uc.mem_write(ebp + START_RECORDING_REPLAY_DIR, struct.pack("<I", self.STRING))
        esp = ebp - 0x100
        uc.mem_write(esp, struct.pack("<I", self.SENTINEL))
        self.before = {
            UC_X86_REG_EAX: 0x11111111,
            UC_X86_REG_EBX: 0x22222222,
            UC_X86_REG_ECX: 0x33333333,
            UC_X86_REG_EDX: 0x44444444,
            UC_X86_REG_ESI: 0x55555555,
            UC_X86_REG_EDI: 0x66666666,
            UC_X86_REG_EBP: ebp,
        }
        for register, value in self.before.items():
            uc.reg_write(register, value)
        uc.reg_write(UC_X86_REG_ESP, esp)
        uc.emu_start(BASE + PRUNE_CODE_OFF, self.SENTINEL, count=50_000_000)
        self.after = {register: uc.reg_read(register) for register in self.before}
        self.esp_after = uc.reg_read(UC_X86_REG_ESP)
        self.esp_expected = esp + 4

    def _read_wide(self, address: int) -> str:
        raw = bytes(self.uc.mem_read(address, 2 * 600))
        return raw.decode("utf-16-le").split("\x00", 1)[0]

    def _fill(self, wfd: int) -> None:
        entry = self._listing.pop(0)
        folder = entry.endswith(self.DIRECTORY)
        name = entry.removesuffix(self.DIRECTORY)
        record = bytearray(0x250)
        struct.pack_into("<I", record, 0, 0x10 if folder else 0x80)
        encoded = name.encode("utf-16-le") + b"\x00\x00"
        record[0x2C : 0x2C + len(encoded)] = encoded
        self.uc.mem_write(wfd, bytes(record))

    def _find_first(self, path: int, wfd: int, *_rest: int) -> int:
        pattern = self._read_wide(path)
        self.scans.append(pattern)
        assert pattern == f"{self.directory}*.BfME2Replay"
        self._listing = [
            entry
            for entry in self.files
            if entry.lower().endswith(".bfme2replay") or entry.endswith(self.DIRECTORY)
        ]
        if not self._listing:
            return -1
        self.open_handles += 1
        self._fill(wfd)
        return 0x1234

    def _find_next(self, handle: int, wfd: int, *_rest: int) -> int:
        assert handle == 0x1234
        if not self._listing:
            return 0
        self._fill(wfd)
        return 1

    def _find_close(self, handle: int, *_rest: int) -> int:
        assert handle == 0x1234
        self.open_handles -= 1
        return 1

    def _delete(self, path: int, *_rest: int) -> int:
        self.delete_calls += 1
        full = self._read_wide(path)
        assert full.startswith(self.directory)
        name = full[len(self.directory) :]
        if not self.delete_works:
            return 0
        if self.delete_removes:
            self.files.remove(name)
        self.deleted.append(name)
        return 1

    def _wcscmp(self, left: int, right: int, *_rest: int) -> int:
        a, b = self._read_wide(left), self._read_wide(right)
        return (a > b) - (a < b)


class TestPruning:
    def test_the_oldest_go_until_keep_minus_one_remain(self):
        """Room for the recording about to start: ten kept means nine before it."""
        own = [_own(day) for day in range(1, 13)]  # 12 files
        run = _FakeReplays(own, keep=10)
        assert run.deleted == [_own(1), _own(2), _own(3)]
        assert sorted(run.files) == own[3:]

    def test_the_order_comes_from_the_name_not_the_listing(self):
        """NTFS lists alphabetically, but nothing may depend on it."""
        own = [_own(day) for day in range(1, 13)]
        shuffled = own[5:] + own[:5][::-1]
        assert _FakeReplays(shuffled, keep=10).deleted == own[:3]

    def test_the_timestamp_decides_not_the_map(self):
        names = [_own(2, map_name="aaa"), _own(1, map_name="zzz"), _own(3, map_name="mmm")]
        assert _FakeReplays(names, keep=2).deleted == [
            _own(1, map_name="zzz"),
            _own(2, map_name="aaa"),
        ]

    def test_nothing_goes_while_there_is_room(self):
        own = [_own(day) for day in range(1, 10)]  # 9: with the new one, exactly 10
        run = _FakeReplays(own, keep=10)
        assert run.deleted == []
        assert len(run.scans) == 1

    @pytest.mark.parametrize(
        "name",
        [
            "Last Replay.BfME2Replay",
            "my best game.BfME2Replay",
            "Game 4.BfME2Replay",
            "2026-11-01 12-00-00.BfME2Replay",  # no space before the extension: not ours
            "2026-11-01_12-00-00 map.BfME2Replay",
            "2026-1x-01 12-00-00 map.BfME2Replay",
            "x2026-11-01 12-00-00 map.BfME2Replay",  # the rename that keeps a replay
            "2026-11-01 12-00-0 map.BfME2Replay",
        ],
    )
    def test_names_the_patch_does_not_write_are_never_counted_or_deleted(self, name: str):
        own = [_own(day) for day in range(10, 20)]
        run = _FakeReplays([name, *own], keep=10)
        assert name in run.files
        assert run.deleted == [_own(10)]

    def test_a_map_less_name_is_still_ours(self):
        """The format with an empty map ends in the space, which the template includes."""
        names = ["2026-11-01 12-00-00 .BfME2Replay", _own(2)]
        assert _FakeReplays(names, keep=2).deleted == ["2026-11-01 12-00-00 .BfME2Replay"]

    def test_a_folder_named_like_a_replay_is_skipped(self):
        names = [_own(1) + _FakeReplays.DIRECTORY, _own(2), _own(3)]
        run = _FakeReplays(names, keep=2)
        assert run.deleted == [_own(2)]

    def test_keep_one_clears_every_old_recording(self):
        own = [_own(day) for day in range(1, 6)]
        assert _FakeReplays(own, keep=1).deleted == own

    def test_a_refused_delete_ends_the_pruning(self):
        """A file in use stays; the recording must still start, so no retry loop."""
        own = [_own(day) for day in range(1, 15)]
        run = _FakeReplays(own, keep=10, delete_works=False)
        assert run.delete_calls == 1
        assert run.files == own

    def test_a_delete_that_lies_is_bounded(self):
        """`DeleteFileW` succeeds on a file another process holds with FILE_SHARE_DELETE, and it
        goes on listing until that handle closes. The budget is what ends that loop."""
        own = [_own(day) for day in range(1, 15)]
        run = _FakeReplays(own, keep=10, delete_removes=False)
        assert run.delete_calls == MAX_DELETES

    def test_a_large_backlog_is_capped_per_recording(self):
        own = [
            f"2026-{1 + n // 28 % 12:02d}-{1 + n % 28:02d} {n // 336:02d}-00-00 m.BfME2Replay"
            for n in range(MAX_DELETES + 40)
        ]
        run = _FakeReplays(own, keep=10)
        assert len(run.deleted) == MAX_DELETES
        assert run.deleted == sorted(own)[:MAX_DELETES]

    def test_an_empty_folder_is_fine(self):
        run = _FakeReplays([], keep=10)
        assert run.deleted == []
        assert run.open_handles == 0

    def test_every_find_handle_is_closed(self):
        run = _FakeReplays([_own(day) for day in range(1, 15)], keep=10)
        assert run.open_handles == 0
        assert len(run.scans) == len(run.deleted) + 1

    def test_no_directory_means_no_scan(self):
        assert _FakeReplays([_own(1)], keep=1, directory=None).scans == []

    def test_an_over_long_directory_is_left_alone(self):
        long_dir = "C:\\" + "d" * DIR_MAX + "\\"
        assert _FakeReplays([_own(1)], keep=1, directory=long_dir).scans == []

    def test_a_directory_at_the_limit_still_works(self):
        at_limit = "C:\\" + "d" * (DIR_MAX - 4) + "\\"
        assert len(at_limit) == DIR_MAX
        assert _FakeReplays([_own(1), _own(2)], keep=2, directory=at_limit).deleted == [_own(1)]

    def test_every_register_comes_back_and_the_stack_balances(self):
        run = _FakeReplays([_own(day) for day in range(1, 15)], keep=10)
        assert run.after == run.before
        assert run.esp_after == run.esp_expected


def test_pruning_is_called_first_when_on():
    """Ahead of the rename decision, so it runs under both rename scopes."""
    for rename_all in (True, False):
        body = name_text(rename_all=rename_all, keep=DEFAULT_KEEP)
        assert body[0] == f"call {BASE + PRUNE_CODE_OFF:#x}"
        without = name_text(rename_all=rename_all, keep=0)
        # every branch target moves by the five-byte call; the instructions do not
        assert [line.split()[0] for line in body[1:]] == [line.split()[0] for line in without]


def test_keep_zero_leaves_the_naming_routine_as_it_was():
    assert f"call {BASE + PRUNE_CODE_OFF:#x}" not in name_text(keep=0)


def test_the_default_keeps_ten():
    assert DEFAULT_KEEP == 10
    assert SkirmishReplayPatch().keep == 10


@pytest.mark.parametrize("keep", [-1, 0x10000])
def test_an_unusable_keep_is_refused(keep: int):
    with pytest.raises(ValueError, match="keep"):
        SkirmishReplayPatch(keep=keep)


def test_verify_rejects_another_keep():
    data = patched_image(SkirmishReplayPatch(keep=10))
    assert SkirmishReplayPatch(keep=10).verify(data) == []
    assert SkirmishReplayPatch(keep=5).verify(data)
    assert SkirmishReplayPatch(keep=0).verify(data)


def test_verify_rejects_a_damaged_pruning_routine():
    data = patched_image()
    _, section_off, _ = find_section(data, SECTION_NAME)
    data[section_off + PRUNE_CODE_OFF + 1] ^= 0xFF
    assert any("pruning routine" in problem for problem in SkirmishReplayPatch().verify(data))


@pytest.mark.parametrize("keep", [0, 1, 10, 500])
def test_detect_recovers_keep(keep: int):
    data = patched_image(SkirmishReplayPatch(keep=keep))
    found = SkirmishReplayPatch.detect(data)
    assert found is not None
    assert found.keep == keep


def test_a_cave_from_before_pruning_reads_as_keep_zero():
    """Such a cave ended with the naming routine, so it is too short to hold a keep count."""
    assert skirmish_replay._stored_keep(bytes(KEEP_OFF), 0, KEEP_OFF) == 0


def test_the_keep_option_reaches_the_patch():
    parser = argparse.ArgumentParser()
    SkirmishReplayPatch.add_cli_arguments(parser)
    assert SkirmishReplayPatch.from_cli_args(parser.parse_args([])).keep == DEFAULT_KEEP
    assert SkirmishReplayPatch.from_cli_args(parser.parse_args(["--keep", "0"])).keep == 0
    assert SkirmishReplayPatch.from_cli_args(parser.parse_args(["--keep", "25"])).keep == 25
