"""Tests for the replay-outcome patch.

The cave is hand-assembled x86 that cannot be executed here, so the important test
disassembles it back and asserts it says what it was meant to say. A wrong byte in a hook
does not raise - it crashes the game - so encoding errors have to be caught statically.

The chunk the cave writes is checked from the other end too: the template is fed through
`sage_replay`'s own parser, so the format the patch emits is the format the reader expects
rather than two independent readings of the same notes.
"""

from __future__ import annotations

import struct
from io import BytesIO

import pytest

pytest.importorskip("capstone", reason="the [patch] extra (capstone) is not installed")
from capstone import CS_ARCH_X86, CS_MODE_32, Cs  # noqa: E402 - after the importorskip guard

from sage_patch.addresses import (  # noqa: E402
    IMPORT_FFLUSH,
    IMPORT_FWRITE,
    MAX_PLAYER_COUNT,
    RECORDER_END_BRANCH,
    RECORDER_END_BRANCH_BYTES,
    RECORDER_END_WRITE_CALL,
    RECORDER_END_WRITE_CALL_BYTES,
    RECORDER_WRITE_TO_FILE,
    THE_GAME_LOGIC,
    THE_RECORDER,
    THE_VICTORY_CONDITIONS,
    VICTORY_CONDITIONS_HAS_ACHIEVED_VICTORY,
    VICTORY_CONDITIONS_HAS_ACHIEVED_VICTORY_SLOT,
    VICTORY_CONDITIONS_HAS_BEEN_DEFEATED,
    VICTORY_CONDITIONS_HAS_BEEN_DEFEATED_SLOT,
    VICTORY_CONDITIONS_VTABLE,
)
from sage_patch.patches.replay_outcome import (
    CHUNK_LEN,
    CODE_OFF,
    ORDER_TYPE,
    OUTCOME_DEFEATED,
    OUTCOME_UNDETERMINED,
    OUTCOME_VICTORIOUS,
    SECTION_NAME,
    ReplayOutcomePatch,
    build_section,
    chunk_template,
)
from sage_patch.pe import image_sections
from sage_patch.utils import append_section, find_section, next_section_rva, va_to_offset
from sage_replay.replay import Bfme2OrderType, OrderArgumentType, ReplayChunk
from sage_utils.stream import BinaryStream

IMAGE_BASE = 0x400000
BASE = 0x00F00000

_VTABLE_SLOTS = (
    (VICTORY_CONDITIONS_HAS_ACHIEVED_VICTORY_SLOT, VICTORY_CONDITIONS_HAS_ACHIEVED_VICTORY),
    (VICTORY_CONDITIONS_HAS_BEEN_DEFEATED_SLOT, VICTORY_CONDITIONS_HAS_BEEN_DEFEATED),
)


def synthetic_image() -> bytearray:
    """A PE32 image big enough to map the hook site, the end-of-recording fingerprint and the
    `VictoryConditions` vtable, with the real original bytes planted, so the whole apply +
    verify path runs without the copyrighted `game.dat`."""
    highest = max(VICTORY_CONDITIONS_VTABLE + 0x80, RECORDER_END_BRANCH + 0x40) - IMAGE_BASE
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

    plant(RECORDER_END_WRITE_CALL, RECORDER_END_WRITE_CALL_BYTES)
    plant(RECORDER_END_BRANCH, RECORDER_END_BRANCH_BYTES)
    for slot, target in _VTABLE_SLOTS:
        plant(VICTORY_CONDITIONS_VTABLE + slot, struct.pack("<I", target))
    return data


def patched_image() -> bytearray:
    data = synthetic_image()
    ReplayOutcomePatch().apply(data)
    return data


def code_bytes(base: int = BASE) -> bytes:
    return build_section(base)[CODE_OFF:]


def disassembled(base: int = BASE):
    md = Cs(CS_ARCH_X86, CS_MODE_32)
    return list(md.disasm(code_bytes(base), base + CODE_OFF))


def text_of(base: int = BASE) -> list[str]:
    return [f"{i.mnemonic} {i.op_str}" for i in disassembled(base)]


def test_apply_repoints_the_write_to_file_call_into_the_cave():
    data = patched_image()
    section_va, _, _ = find_section(data, SECTION_NAME)
    off = va_to_offset(data, RECORDER_END_WRITE_CALL)
    assert data[off] == 0xE8  # still a call, not a jmp: the return address must survive
    target = RECORDER_END_WRITE_CALL + 5 + struct.unpack_from("<i", data, off + 1)[0]
    assert target == section_va + CODE_OFF


def test_the_cave_tail_jumps_to_the_displaced_call_target():
    """The hook replaced a `call`, so the cave must `jmp` (never `call`) to the original
    target: `writeToFile`'s own `ret 4` is what returns to `updateRecord` and pops the
    `GameMessage *` the recorder pushed."""
    last = disassembled()[-1]
    assert last.mnemonic == "jmp"
    assert int(last.op_str, 16) == RECORDER_WRITE_TO_FILE


def test_apply_then_verify_is_clean():
    assert ReplayOutcomePatch().verify(patched_image()) == []


def test_verify_rejects_an_unpatched_image():
    assert ReplayOutcomePatch().verify(synthetic_image()) == [f"{SECTION_NAME} section is absent"]


def test_apply_is_not_repeatable():
    """The site is a call to the cave the second time round, not the original call, so
    `apply_byte_patch` refuses rather than nesting a second hook."""
    data = patched_image()
    with pytest.raises(ValueError, match="expected"):
        ReplayOutcomePatch().apply(data)


def test_apply_refuses_when_the_end_branch_fingerprint_moved():
    """The hook site is a bare `call`; what proves it is the end-of-recording one is the
    `cmp eax, MSG_CLEAR_GAME_DATA` + `m_file` test just above it."""
    data = synthetic_image()
    off = va_to_offset(data, RECORDER_END_BRANCH)
    data[off] = 0x90
    with pytest.raises(ValueError, match="end-of-recording branch"):
        ReplayOutcomePatch().apply(data)


@pytest.mark.parametrize(("slot", "expected"), _VTABLE_SLOTS)
def test_apply_refuses_when_a_vtable_slot_moved(slot: int, expected: int):
    data = synthetic_image()
    off = va_to_offset(data, VICTORY_CONDITIONS_VTABLE + slot)
    struct.pack_into("<I", data, off, expected + 0x10)
    with pytest.raises(ValueError, match="the cave would call the wrong function"):
        ReplayOutcomePatch().apply(data)


def test_the_guards_are_checked_before_the_section_is_added():
    """A refused apply must leave the image untouched, not carrying an orphan cave."""
    data = synthetic_image()
    before = bytes(data)
    off = va_to_offset(data, RECORDER_END_BRANCH)
    data[off] = 0x90
    with pytest.raises(ValueError):
        ReplayOutcomePatch().apply(data)
    data[off] = before[off]
    assert bytes(data) == before


def test_the_cave_preserves_every_register_it_borrows():
    body = text_of()
    assert body[0] == "pushfd "
    assert body[1] == "pushal "
    assert body[-3] == "popal "
    assert body[-2] == "popfd "


def test_the_cave_reads_the_three_globals_it_needs():
    body = text_of()
    assert f"mov esi, dword ptr [{THE_RECORDER:#x}]" in body
    assert f"mov esi, dword ptr [{THE_VICTORY_CONDITIONS:#x}]" in body
    assert f"mov eax, dword ptr [{THE_GAME_LOGIC:#x}]" in body


def test_the_cave_dispatches_has_achieved_victory_through_the_vtable():
    slot = VICTORY_CONDITIONS_HAS_ACHIEVED_VICTORY_SLOT
    assert f"call dword ptr [eax + {slot:#x}]" in text_of()


def test_the_cave_calls_fwrite_and_fflush_through_the_iat():
    body = text_of()
    assert f"call dword ptr [{IMPORT_FWRITE:#x}]" in body
    assert f"call dword ptr [{IMPORT_FFLUSH:#x}]" in body


def test_the_fwrite_call_is_cdecl_balanced():
    """Four pushed arguments, cleaned by the caller. An unbalanced call here would corrupt
    `clearGameData`'s frame in a way nothing else would catch."""
    body = text_of()
    call = body.index(f"call dword ptr [{IMPORT_FWRITE:#x}]")
    pushes = [line for line in body[call - 4 : call] if line.startswith("push")]
    assert len(pushes) == 4
    assert body[call + 1] == "add esp, 0x10"
    assert f"push {CHUNK_LEN:#x}" in pushes  # size 1, count CHUNK_LEN


def test_the_loop_walks_every_player_slot():
    body = text_of()
    assert f"cmp ebx, {MAX_PLAYER_COUNT:#x}" in body
    assert any(line.startswith("jl ") for line in body)


def test_the_cave_writes_all_three_outcome_values():
    """`undetermined` is not written by a `mov` - it is the `xor edx, edx` the victory test
    falls through from - so the two explicit ones plus that xor cover the enum."""
    body = text_of()
    assert f"mov edx, {OUTCOME_VICTORIOUS}" in body
    assert f"mov edx, {OUTCOME_DEFEATED}" in body
    assert "xor edx, edx" in body
    assert OUTCOME_UNDETERMINED == 0


def test_the_cave_is_position_independent_of_its_base():
    """Every absolute the cave holds is derived from the base it is built for, so the same
    body at a different base differs only in those - not in length or instruction count."""
    here, elsewhere = disassembled(BASE), disassembled(BASE + 0x10000)
    assert len(code_bytes(BASE)) == len(code_bytes(BASE + 0x10000))
    assert [i.mnemonic for i in here] == [i.mnemonic for i in elsewhere]


def test_the_chunk_template_parses_as_a_replay_chunk():
    """The other end of the contract: what the cave lays down is what `sage_replay` reads."""
    chunk = ReplayChunk.parse(BinaryStream(BytesIO(chunk_template())))
    assert chunk.order_type == ORDER_TYPE == Bfme2OrderType.GameOutcome
    assert [a.argument_type for a in chunk.order.arguments] == [OrderArgumentType.Integer] * 2


def test_the_chunk_template_is_exactly_chunk_len():
    assert len(chunk_template()) == CHUNK_LEN


def test_the_order_type_cannot_collide_with_an_engine_order():
    """The recorder copies `0x3E8 < type < 0x7CF` off the command list and the
    `GameMessage::Type` enum ends at `0x47B`, so 0x7D0 is unreachable for the engine."""
    assert ORDER_TYPE > 0x7CF


def test_the_cave_lands_past_every_existing_section():
    """Rule 1 of composing patches: appending past the highest section is what keeps the
    section table sorted whatever else has already been added."""
    data = patched_image()
    section_va, _, _ = find_section(data, SECTION_NAME)
    ours = section_va - IMAGE_BASE
    for section in image_sections(data):
        if section.name == SECTION_NAME:
            continue
        assert ours >= section.virtual_address - IMAGE_BASE + section.virtual_size


def test_it_still_applies_behind_another_patch_s_cave():
    """The cave's placement is computed, not hardcoded, so an image that already carries
    someone else's appended section gets this one after it - and `verify` finds it by name
    rather than by the RVA it would have had on a clean image."""
    clean = synthetic_image()
    ReplayOutcomePatch().apply(clean)
    alone_va, _, _ = find_section(clean, SECTION_NAME)

    stacked = synthetic_image()
    append_section(stacked, ".other", next_section_rva(stacked), b"\x90" * 0x40, 0x40000040)
    ReplayOutcomePatch().apply(stacked)
    behind_va, _, _ = find_section(stacked, SECTION_NAME)

    assert behind_va > alone_va
    assert ReplayOutcomePatch().verify(stacked) == []
