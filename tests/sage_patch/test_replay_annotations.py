"""Tests for the replay-annotations patch.

The cave is hand-assembled x86 that cannot be executed here, so the important test
disassembles it back and asserts it says what it was meant to say. A wrong byte in a hook
does not raise - it crashes the game - so encoding errors have to be caught statically.

The chunks are checked from the other end too: both templates go through `sage_replay`'s own
parser and its reader, so the format the patch emits is the format the reader expects rather
than two independent readings of the same notes.
"""

from __future__ import annotations

import struct
from io import BytesIO
from pathlib import Path

import pytest

pytest.importorskip("capstone", reason="the [patch] extra (capstone) is not installed")
from capstone import CS_ARCH_X86, CS_MODE_32, Cs  # noqa: E402 - after the importorskip guard

from sage_patch.addresses import (  # noqa: E402
    IMPORT_FFLUSH,
    IMPORT_FWRITE,
    MAX_PLAYER_COUNT,
    PLAYER_DEFEAT_FRAME,
    PLAYER_SCORE_KEEPER,
    RECORDER_END_BRANCH,
    RECORDER_END_BRANCH_BYTES,
    RECORDER_END_STOP_CALL,
    RECORDER_END_STOP_CALL_BYTES,
    RECORDER_END_STOP_SETUP,
    RECORDER_END_STOP_SETUP_BYTES,
    RECORDER_END_WRITE_CALL,
    RECORDER_END_WRITE_CALL_BYTES,
    RECORDER_STOP_RECORDING,
    SCORE_KEEPER_COUNTER_BLOCK,
    SCORE_KEEPER_COUNTER_BLOCK_DWORDS,
    SCORE_KEEPER_END_FRAME,
    SCORE_KEEPER_LAYOUT_SITES,
    SCORE_KEEPER_PLAYER_REF,
    SCORE_KEEPER_PLAYER_REF_BYTES,
    SCORE_KEEPER_STRUCTURES_DESTROYED,
    SCORE_KEEPER_STRUCTURES_LOST,
    SCORE_KEEPER_UNITS_BUILT,
    SCORE_KEEPER_UNITS_DESTROYED,
    SCORE_KEEPER_UNITS_LOST,
    THE_GAME_LOGIC,
    THE_PLAYER_LIST,
    THE_RECORDER,
    THE_VICTORY_CONDITIONS,
    VICTORY_CONDITIONS_HAS_ACHIEVED_VICTORY,
    VICTORY_CONDITIONS_HAS_ACHIEVED_VICTORY_SLOT,
    VICTORY_CONDITIONS_HAS_BEEN_DEFEATED,
    VICTORY_CONDITIONS_HAS_BEEN_DEFEATED_SLOT,
    VICTORY_CONDITIONS_VTABLE,
)
from sage_patch.patches.replay_annotations import (  # noqa: E402
    CODE_OFF,
    KIND_PLAYER_SCORE,
    MANIFEST_LEN,
    MANIFEST_OFF,
    MANIFEST_TYPE,
    MANIFEST_VALUES,
    SCHEMA_VERSION,
    SCORE_FIELDS,
    SCORE_LEN,
    SCORE_OFF,
    SCORE_TYPE,
    SCORE_VALUES,
    SECTION_NAME,
    WRITER_ID,
    ReplayAnnotationsPatch,
    build_section,
    manifest_template,
    score_template,
)
from sage_patch.patches.replay_outcome import ReplayOutcomePatch  # noqa: E402
from sage_patch.pe import image_sections  # noqa: E402
from sage_patch.utils import (  # noqa: E402
    append_section,
    find_section,
    next_section_rva,
    va_to_offset,
)
from sage_replay import annotations  # noqa: E402
from sage_replay.replay import Bfme2OrderType, OrderArgumentType, ReplayChunk  # noqa: E402
from sage_utils.stream import BinaryStream  # noqa: E402

IMAGE_BASE = 0x400000
BASE = 0x00F00000


def synthetic_image() -> bytearray:
    """A PE32 image big enough to map both hook sites and the ScoreKeeper fingerprints, with
    the real original bytes planted, so the whole apply + verify path runs without the
    copyrighted `game.dat`."""
    highest = (
        max(
            RECORDER_END_BRANCH,
            SCORE_KEEPER_LAYOUT_SITES[-1][0],
            VICTORY_CONDITIONS_VTABLE + 0x80,
        )
        + 0x40
        - IMAGE_BASE
    )
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

    plant(RECORDER_END_BRANCH, RECORDER_END_BRANCH_BYTES)
    plant(RECORDER_END_WRITE_CALL, RECORDER_END_WRITE_CALL_BYTES)
    plant(RECORDER_END_STOP_SETUP, RECORDER_END_STOP_SETUP_BYTES)
    plant(RECORDER_END_STOP_CALL, RECORDER_END_STOP_CALL_BYTES)
    plant(SCORE_KEEPER_PLAYER_REF, SCORE_KEEPER_PLAYER_REF_BYTES)
    for va, raw in SCORE_KEEPER_LAYOUT_SITES:
        plant(va, raw)
    # `replay-outcome`'s own guards, so the composition test can apply it here too.
    for slot, target in (
        (VICTORY_CONDITIONS_HAS_ACHIEVED_VICTORY_SLOT, VICTORY_CONDITIONS_HAS_ACHIEVED_VICTORY),
        (VICTORY_CONDITIONS_HAS_BEEN_DEFEATED_SLOT, VICTORY_CONDITIONS_HAS_BEEN_DEFEATED),
    ):
        plant(VICTORY_CONDITIONS_VTABLE + slot, struct.pack("<I", target))
    return data


def patched_image() -> bytearray:
    data = synthetic_image()
    ReplayAnnotationsPatch().apply(data)
    return data


def code_bytes(base: int = BASE) -> bytes:
    return build_section(base)[CODE_OFF:]


def disassembled(base: int = BASE):
    md = Cs(CS_ARCH_X86, CS_MODE_32)
    return list(md.disasm(code_bytes(base), base + CODE_OFF))


def text_of(base: int = BASE) -> list[str]:
    return [f"{i.mnemonic} {i.op_str}" for i in disassembled(base)]


def test_apply_repoints_the_stop_recording_call_into_the_cave():
    data = patched_image()
    section_va, _, _ = find_section(data, SECTION_NAME)
    off = va_to_offset(data, RECORDER_END_STOP_CALL)
    assert data[off] == 0xE8  # still a call, not a jmp: the return address must survive
    target = RECORDER_END_STOP_CALL + 5 + struct.unpack_from("<i", data, off + 1)[0]
    assert target == section_va + CODE_OFF


def test_the_cave_tail_jumps_to_the_displaced_call_target():
    """The hook replaced a `call`, so the cave must `jmp` (never `call`) to the original
    target: `stopRecording`'s own `ret` is what returns to `updateRecord`."""
    last = disassembled()[-1]
    assert last.mnemonic == "jmp"
    assert int(last.op_str, 16) == RECORDER_STOP_RECORDING


def test_apply_then_verify_is_clean():
    assert ReplayAnnotationsPatch().verify(patched_image()) == []


def test_verify_rejects_an_unpatched_image():
    assert ReplayAnnotationsPatch().verify(synthetic_image()) == [
        f"{SECTION_NAME} section is absent"
    ]


def test_apply_is_not_repeatable():
    data = patched_image()
    with pytest.raises(ValueError, match="expected"):
        ReplayAnnotationsPatch().apply(data)


def test_apply_refuses_when_the_end_branch_fingerprint_moved():
    data = synthetic_image()
    off = va_to_offset(data, RECORDER_END_BRANCH)
    data[off] = 0x90
    with pytest.raises(ValueError, match="the end-of-recording branch"):
        ReplayAnnotationsPatch().apply(data)


def test_apply_refuses_when_the_call_setup_moved():
    """`mov ecx, edi` is what says the recorder is the `this` the tail-jump will hand to
    `stopRecording` - without it the cave would jump into it with the wrong object."""
    data = synthetic_image()
    off = va_to_offset(data, RECORDER_END_STOP_SETUP)
    data[off] = 0x90
    with pytest.raises(ValueError, match="its stopRecording setup"):
        ReplayAnnotationsPatch().apply(data)


def test_apply_refuses_when_the_score_keeper_moved_on_player():
    data = synthetic_image()
    off = va_to_offset(data, SCORE_KEEPER_PLAYER_REF)
    data[off + 2] = 0xE0  # a different displacement: lea ecx, [edi+0x3e0]
    with pytest.raises(ValueError, match="the ScoreKeeper is not at"):
        ReplayAnnotationsPatch().apply(data)


@pytest.mark.parametrize(("va", "raw"), SCORE_KEEPER_LAYOUT_SITES)
def test_apply_refuses_when_a_counter_offset_moved(va: int, raw: bytes):
    """The failure mode this guard exists for: a moved counter would ship a chunk that parses
    perfectly and means something else."""
    data = synthetic_image()
    off = va_to_offset(data, va)
    data[off + len(raw) - 1] ^= 0x04
    with pytest.raises(ValueError, match="the layout moved"):
        ReplayAnnotationsPatch().apply(data)


def test_the_guards_are_checked_before_the_section_is_added():
    """A refused apply must leave the image untouched, not carrying an orphan cave."""
    data = synthetic_image()
    before = bytes(data)
    off = va_to_offset(data, RECORDER_END_BRANCH)
    data[off] = 0x90
    with pytest.raises(ValueError):
        ReplayAnnotationsPatch().apply(data)
    data[off] = before[off]
    assert bytes(data) == before


def test_the_cave_preserves_every_register_it_borrows():
    body = text_of()
    assert body[0] == "pushfd "
    assert body[1] == "pushal "
    assert body[-3] == "popal "
    assert body[-2] == "popfd "


def test_the_cave_clears_the_direction_flag_before_its_block_copy():
    """`rep movsd` copies downward with DF set, which would write the counters backwards over
    the section. `popfd` puts back whatever the engine had."""
    body = text_of()
    assert "cld " in body
    assert body.index("cld ") < body.index("rep movsd dword ptr es:[edi], dword ptr [esi]")


def test_the_cave_reads_the_globals_it_needs():
    body = text_of()
    assert f"mov esi, dword ptr [{THE_RECORDER:#x}]" in body
    assert f"mov esi, dword ptr [{THE_VICTORY_CONDITIONS:#x}]" in body
    assert f"mov eax, dword ptr [{THE_GAME_LOGIC:#x}]" in body
    assert f"mov ecx, dword ptr [{THE_PLAYER_LIST:#x}]" in body


def test_the_cave_calls_fwrite_and_fflush_through_the_iat():
    body = text_of()
    assert body.count(f"call dword ptr [{IMPORT_FWRITE:#x}]") == 2  # manifest, then per player
    assert f"call dword ptr [{IMPORT_FFLUSH:#x}]" in body


@pytest.mark.parametrize("length", [MANIFEST_LEN, SCORE_LEN])
def test_each_fwrite_call_is_cdecl_balanced(length: int):
    """Four pushed arguments, cleaned by the caller. An unbalanced call here would corrupt
    `updateRecord`'s frame in a way nothing else would catch."""
    body = text_of()
    call = f"call dword ptr [{IMPORT_FWRITE:#x}]"
    at = next(
        i for i, line in enumerate(body) if line == call and f"push {length:#x}" in body[i - 4 : i]
    )
    assert len([line for line in body[at - 4 : at] if line.startswith("push")]) == 4
    assert body[at + 1] == "add esp, 0x10"


def test_the_loop_walks_every_player_slot():
    body = text_of()
    assert f"cmp ebx, {MAX_PLAYER_COUNT:#x}" in body
    assert any(line.startswith("jl ") for line in body)


def test_the_cave_reads_every_score_field_from_the_keeper():
    """The five scalars by displacement off the player, and the six contiguous counters as one
    `rep movsd` of the right length from the right place."""
    body = text_of()
    for offset in (
        annotations_offset
        for annotations_offset in (0x04, 0x08, 0x108, 0x10C, SCORE_KEEPER_END_FRAME)
    ):
        assert f"mov eax, dword ptr [edi + {PLAYER_SCORE_KEEPER + offset:#x}]" in body
    assert f"lea esi, [edi + {PLAYER_SCORE_KEEPER + SCORE_KEEPER_COUNTER_BLOCK:#x}]" in body
    assert f"mov ecx, {SCORE_KEEPER_COUNTER_BLOCK_DWORDS:#x}" in body


def test_the_end_frame_read_is_the_defeat_frame_replay_outcome_already_uses():
    """The cross-check that pins the keeper's base: the two patches reach the same field from
    two different descriptions of the layout."""
    assert PLAYER_SCORE_KEEPER + SCORE_KEEPER_END_FRAME == PLAYER_DEFEAT_FRAME
    assert f"mov eax, dword ptr [edi + {PLAYER_DEFEAT_FRAME:#x}]" in text_of()


def test_the_counter_block_covers_exactly_the_six_counters():
    """The single `rep movsd` is only correct while the counters stay contiguous, in this
    order - so the arithmetic that says so is asserted, not assumed."""
    assert SCORE_KEEPER_UNITS_DESTROYED + 4 * MAX_PLAYER_COUNT == SCORE_KEEPER_UNITS_BUILT
    assert SCORE_KEEPER_UNITS_BUILT + 4 == SCORE_KEEPER_UNITS_LOST
    assert SCORE_KEEPER_UNITS_LOST + 4 == SCORE_KEEPER_STRUCTURES_DESTROYED
    assert (
        SCORE_KEEPER_STRUCTURES_DESTROYED + 4 * MAX_PLAYER_COUNT == SCORE_KEEPER_STRUCTURES_LOST - 4
    )
    assert SCORE_KEEPER_COUNTER_BLOCK_DWORDS == 2 * MAX_PLAYER_COUNT + 4


def test_the_cave_is_position_independent_of_its_base():
    here, elsewhere = disassembled(BASE), disassembled(BASE + 0x10000)
    assert len(code_bytes(BASE)) == len(code_bytes(BASE + 0x10000))
    assert [i.mnemonic for i in here] == [i.mnemonic for i in elsewhere]


def test_the_templates_parse_as_replay_chunks():
    """The other end of the contract: what the cave lays down is what `sage_replay` reads."""
    for template, order_type, count in (
        (manifest_template(), MANIFEST_TYPE, len(MANIFEST_VALUES)),
        (score_template(), SCORE_TYPE, SCORE_VALUES),
    ):
        chunk = ReplayChunk.parse(BinaryStream(BytesIO(template)))
        assert chunk.order_type == order_type
        assert [a.argument_type for a in chunk.order.arguments] == (
            [OrderArgumentType.Integer] * count
        )


def test_the_order_types_are_the_ones_sage_replay_names():
    assert MANIFEST_TYPE == Bfme2OrderType.AnnotationManifest
    assert SCORE_TYPE == Bfme2OrderType.PlayerScore


def test_the_manifest_declares_the_score_records_this_build_writes():
    chunk = ReplayChunk.parse(BinaryStream(BytesIO(manifest_template())))
    version, kinds, writer = (a.value for a in chunk.order.arguments)
    assert version == SCHEMA_VERSION
    assert kinds & KIND_PLAYER_SCORE
    assert writer == WRITER_ID


def test_the_score_layout_matches_the_reader():
    """`sage_replay.annotations` restates the record layout rather than importing it (the
    packages are independent); the two must not drift."""
    assert SCORE_FIELDS == annotations.SCORE_FIELDS
    assert MAX_PLAYER_COUNT == annotations.MAX_PLAYER_COUNT


def test_a_score_record_fits_the_chunk_format():
    """Each `(type, count)` pair carries a single count byte, so a record may not exceed 255
    values - and both templates must fit the section slots they were given."""
    assert SCORE_VALUES <= 255
    assert MANIFEST_OFF + MANIFEST_LEN <= SCORE_OFF
    assert SCORE_OFF + SCORE_LEN <= CODE_OFF


def test_the_order_types_cannot_collide_with_an_engine_order():
    """The recorder copies `0x3E8 < type < 0x7CF` off the command list and the
    `GameMessage::Type` enum ends at `0x47B`, so the reserved block is unreachable."""
    assert MANIFEST_TYPE > 0x7CF
    assert SCORE_TYPE > 0x7CF


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
    ReplayAnnotationsPatch().apply(clean)
    alone_va, _, _ = find_section(clean, SECTION_NAME)

    stacked = synthetic_image()
    append_section(stacked, ".other", next_section_rva(stacked), b"\x90" * 0x40, 0x40000040)
    ReplayAnnotationsPatch().apply(stacked)
    behind_va, _, _ = find_section(stacked, SECTION_NAME)

    assert behind_va > alone_va
    assert ReplayAnnotationsPatch().verify(stacked) == []


@pytest.mark.parametrize("order", [("annotations", "outcome"), ("outcome", "annotations")])
def test_it_composes_with_replay_outcome_in_either_order(order: tuple[str, str]):
    """The two patches hook the two calls of one branch. Neither reads a byte the other
    rewrites, so both apply and both verify whichever went first."""
    data = synthetic_image()
    patches = {"annotations": ReplayAnnotationsPatch(), "outcome": ReplayOutcomePatch()}
    for name in order:
        patches[name].apply(data)
    assert ReplayAnnotationsPatch().verify(data) == []
    assert ReplayOutcomePatch().verify(data) == []


#: The repo's own clean build, for the address checks the synthetic image cannot make.
_GAME_DAT = Path(__file__).resolve().parents[2] / "game.dat"


@pytest.mark.full
@pytest.mark.skipif(
    not _GAME_DAT.exists(), reason="requires a local game.dat (gitignored, absent in CI)"
)
class TestInstalledBinary:
    """The addresses, against the real thing. Everything above is self-consistent by
    construction; only this says the sites are where the patch claims they are."""

    @pytest.fixture(scope="class")
    @classmethod
    def real(cls) -> bytearray:
        return bytearray(_GAME_DAT.read_bytes())

    def test_the_hook_site_holds_its_stock_bytes(self, real: bytearray) -> None:
        for va, stock in (
            (RECORDER_END_BRANCH, RECORDER_END_BRANCH_BYTES),
            (RECORDER_END_STOP_SETUP, RECORDER_END_STOP_SETUP_BYTES),
            (RECORDER_END_STOP_CALL, RECORDER_END_STOP_CALL_BYTES),
        ):
            off = va_to_offset(real, va)
            assert off is not None, f"{va:#010x} is not mapped"
            assert bytes(real[off : off + len(stock)]) == stock

    def test_the_displaced_call_really_targets_stop_recording(self, real: bytearray) -> None:
        """What makes the tail-jump correct: the five bytes taken are a call to exactly the
        address the cave jumps to."""
        off = va_to_offset(real, RECORDER_END_STOP_CALL)
        rel = struct.unpack_from("<i", real, off + 1)[0]
        assert real[off] == 0xE8
        assert RECORDER_END_STOP_CALL + 5 + rel == RECORDER_STOP_RECORDING

    def test_the_two_calls_of_the_branch_do_not_overlap(self, real: bytearray) -> None:
        """The composition claim, measured: `replay-outcome` takes the `writeToFile` call and
        this patch the `stopRecording` one, and the five bytes of each are disjoint."""
        ours = range(RECORDER_END_STOP_CALL, RECORDER_END_STOP_CALL + 5)
        theirs = range(RECORDER_END_WRITE_CALL, RECORDER_END_WRITE_CALL + 5)
        assert not set(ours) & set(theirs)
        # ...and neither lands inside the 20-byte fingerprint the other verifies.
        guarded = range(RECORDER_END_BRANCH, RECORDER_END_BRANCH + len(RECORDER_END_BRANCH_BYTES))
        assert not set(ours) & set(guarded)

    @pytest.mark.parametrize(("va", "raw"), SCORE_KEEPER_LAYOUT_SITES)
    def test_every_score_keeper_site_holds_its_stock_bytes(
        self, real: bytearray, va: int, raw: bytes
    ) -> None:
        off = va_to_offset(real, va)
        assert off is not None, f"{va:#010x} is not mapped"
        assert bytes(real[off : off + len(raw)]) == raw

    def test_the_score_keeper_base_is_where_the_player_code_says(self, real: bytearray) -> None:
        off = va_to_offset(real, SCORE_KEEPER_PLAYER_REF)
        assert bytes(real[off : off + len(SCORE_KEEPER_PLAYER_REF_BYTES)]) == (
            SCORE_KEEPER_PLAYER_REF_BYTES
        )

    def test_it_applies_verifies_and_is_detected_on_the_real_binary(self, real: bytearray) -> None:
        data = bytearray(real)
        ReplayAnnotationsPatch().apply(data)
        assert ReplayAnnotationsPatch().verify(data) == []
        assert isinstance(ReplayAnnotationsPatch.detect(data), ReplayAnnotationsPatch)
        assert ReplayAnnotationsPatch.detect(real) is None

    def test_it_composes_with_replay_outcome_on_the_real_binary(self, real: bytearray) -> None:
        for order in (
            (ReplayAnnotationsPatch(), ReplayOutcomePatch()),
            (ReplayOutcomePatch(), ReplayAnnotationsPatch()),
        ):
            data = bytearray(real)
            for patch in order:
                patch.apply(data)
            assert ReplayAnnotationsPatch().verify(data) == []
            assert ReplayOutcomePatch().verify(data) == []
