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

import struct

import pytest
from capstone import CS_ARCH_X86, CS_MODE_32, Cs

from sage_patch.addresses import (
    GAME_INFO_MAP,
    GAME_MODE_SKIRMISH,
    IMPORT_GET_LOCAL_TIME,
    IMPORT_SWPRINTF,
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
    THE_GAME_INFO,
    THE_RECORDER,
    THE_SKIRMISH_GAME_INFO,
    UNICODE_STRING_FROM_WIDE,
)
from sage_patch.patches.skirmish_replay import (
    DEFAULT_MODES,
    FORMAT,
    GATE_CODE_OFF,
    ILLEGAL_CHARACTERS,
    MAP_MAX,
    MAX_MODES,
    MODE_COUNT_OFF,
    MODE_TABLE_OFF,
    NAME_CODE_OFF,
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
    base: int = BASE, modes: tuple[int, ...] = DEFAULT_MODES, rename_all: bool = True
) -> list[str]:
    body = build_section(base, modes, rename_all)[NAME_CODE_OFF:]
    return [f"{i.mnemonic} {i.op_str}" for i in _disassemble(body, base + NAME_CODE_OFF)]


# --- the two hooks --------------------------------------------------------------------------


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


# --- the structural guards ------------------------------------------------------------------


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


# --- the whitelist routine ------------------------------------------------------------------


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


# --- the naming routine ---------------------------------------------------------------------


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


# --- both routines --------------------------------------------------------------------------


def test_the_cave_is_position_independent_of_its_base():
    """Every absolute either routine holds is derived from the base it is built for, so the
    same body at a different base differs only in those - not in length or shape."""
    here, elsewhere = build_section(BASE), build_section(BASE + 0x10000)
    assert len(here) == len(elsewhere)
    for at in (GATE_CODE_OFF, NAME_CODE_OFF):
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


# --- composition ----------------------------------------------------------------------------


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
