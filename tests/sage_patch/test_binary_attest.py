"""Tests for the binary-attest patch.

The cave is hand-assembled x86 that cannot be executed here, so the important tests disassemble
it back and assert it says what it was meant to say - a wrong byte in a hook does not raise, it
crashes the game mid-match.

The other half is the arithmetic. :func:`expected_hash` and the cave's `fold` loop are two
independent implementations of the same FNV-1a walk, and the whole value of the patch rests on
them agreeing: if the Python side cannot predict what the running game will publish, nobody can
compare two binaries without playing a game against each other. So the loop is disassembled
instruction by instruction and its constants checked against the ones Python folds with.
"""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

pytest.importorskip("capstone", reason="the [patch] extra (capstone) is not installed")
from capstone import CS_ARCH_X86, CS_MODE_32, Cs  # noqa: E402 - after the importorskip guard

from sage_patch.addresses import (  # noqa: E402
    LOGIC_CRC_EMIT,
    LOGIC_CRC_EMIT_BYTES,
    LOGIC_CRC_EMIT_RESUME,
    LOGIC_CRC_SHROUD_XFER,
    LOGIC_CRC_SHROUD_XFER_BYTES,
    RECORDER_MODE,
    RECORDER_MODE_PLAYBACK,
    TEXT_SECTION_LEN,
    TEXT_SECTION_VA,
    THE_RECORDER,
)
from sage_patch.patches.binary_attest import (  # noqa: E402
    CODE_OFF,
    FNV_OFFSET_BASIS,
    FNV_PRIME,
    HASH_OFF,
    READY_OFF,
    SECTION_LEN,
    SECTION_NAME,
    BinaryAttestPatch,
    build_section,
    expected_hash,
)
from sage_patch.patches.replay_outcome import ReplayOutcomePatch  # noqa: E402
from sage_patch.registry import PATCHES  # noqa: E402
from sage_patch.utils import find_section, va_to_offset  # noqa: E402

from .synthetic import binary_attest_image  # noqa: E402

_GAME_DAT = Path(r"C:\Program Files (x86)\Games\bfme\rotwk\game.dat")

BASE = 0x00F00000


def _disasm(code: bytes, base: int) -> list[tuple[int, str, str]]:
    md = Cs(CS_ARCH_X86, CS_MODE_32)
    return [(i.address, i.mnemonic, i.op_str) for i in md.disasm(code, base)]


@pytest.fixture
def image() -> bytearray:
    return binary_attest_image()


@pytest.fixture
def patched(image: bytearray) -> bytearray:
    BinaryAttestPatch().apply(image)
    return image


class TestApply:
    def test_it_registers_on_the_cli(self) -> None:
        assert PATCHES["binary-attest"] is BinaryAttestPatch

    def test_the_hook_becomes_a_jump_into_the_cave(self, patched: bytearray) -> None:
        section_va, _, _ = find_section(patched, SECTION_NAME)
        off = va_to_offset(patched, LOGIC_CRC_EMIT)
        assert patched[off] == 0xE9
        target = LOGIC_CRC_EMIT + 5 + struct.unpack_from("<i", patched, off + 1)[0]
        assert target == section_va + CODE_OFF

    def test_the_sixth_displaced_byte_is_a_nop(self, patched: bytearray) -> None:
        """The displaced instruction is six bytes and the jump is five. The spare byte has to be
        a nop rather than left as-is, because `0x0062E7E2` jumps to the emitter and execution
        must reach `LOGIC_CRC_EMIT_RESUME` on an instruction boundary."""
        off = va_to_offset(patched, LOGIC_CRC_EMIT)
        assert patched[off + 5] == 0x90
        assert LOGIC_CRC_EMIT + 6 == LOGIC_CRC_EMIT_RESUME

    def test_it_verifies_and_detects_after_applying(self, patched: bytearray) -> None:
        assert BinaryAttestPatch().verify(patched) == []
        assert BinaryAttestPatch.detect(patched) is not None

    def test_an_unpatched_image_neither_verifies_nor_detects(self, image: bytearray) -> None:
        assert BinaryAttestPatch().verify(image) != []
        assert BinaryAttestPatch.detect(image) is None

    def test_it_refuses_an_image_whose_emitter_is_not_the_expected_bytes(
        self, image: bytearray
    ) -> None:
        off = va_to_offset(image, LOGIC_CRC_EMIT)
        image[off] = 0x33
        with pytest.raises(ValueError, match="MSG_LOGIC_CRC emitter"):
            BinaryAttestPatch().apply(image)

    def test_it_refuses_a_build_that_does_not_fold_the_shroud_into_the_crc(
        self, image: bytearray
    ) -> None:
        """The premise check. This patch attests *code* precisely because the engine already
        hashes shroud state; a build that stopped doing so needs a different patch, and should
        fail here rather than ship covering half of what its documentation claims."""
        off = va_to_offset(image, LOGIC_CRC_SHROUD_XFER)
        image[off : off + len(LOGIC_CRC_SHROUD_XFER_BYTES)] = b"\x90" * len(
            LOGIC_CRC_SHROUD_XFER_BYTES
        )
        with pytest.raises(ValueError, match="shroud is not being folded"):
            BinaryAttestPatch().apply(image)

    def test_it_refuses_an_image_whose_text_section_moved(self, image: bytearray) -> None:
        """The hashed range is an immediate with no runtime bound check behind it, so a build
        whose `.text` started elsewhere would have the cave fold whatever sat at that address."""
        assert va_to_offset(image, TEXT_SECTION_VA) is not None
        moved = binary_attest_image(text_va=TEXT_SECTION_VA + 0x1000)
        with pytest.raises(ValueError, match=r"\.text is"):
            BinaryAttestPatch().apply(moved)

    def test_a_tampered_cave_fails_verification(self, patched: bytearray) -> None:
        """Editing the routine is the one attack the patch has to notice about itself."""
        _, section_off, _ = find_section(patched, SECTION_NAME)
        patched[section_off + CODE_OFF] ^= 0xFF
        assert any("expected routine" in p for p in BinaryAttestPatch().verify(patched))


class TestCave:
    """The hand-assembled routine, disassembled back."""

    @pytest.fixture
    def code(self) -> list[tuple[int, str, str]]:
        section = build_section(BASE)
        return _disasm(section[CODE_OFF:], BASE + CODE_OFF)

    def test_it_fits_the_section_with_room_for_the_hashed_tail(self) -> None:
        section = build_section(BASE)
        assert len(section) == SECTION_LEN

    def test_it_preserves_every_register_but_edi(self, code: list[tuple[int, str, str]]) -> None:
        """`edi` carries the checksum and is the one register meant to change. Everything else
        belongs to the emitter, which is mid-way through building a message."""
        pushes = [op for _, m, op in code[:5] if m == "push"]
        assert pushes == ["eax", "ecx", "edx", "esi"]
        assert code[4][1] == "pushfd"
        text = [(m, op) for _, m, op in code]
        assert ("popfd", "") in text
        for register in ("eax", "ecx", "edx", "esi"):
            assert ("pop", register) in text
        assert ("push", "edi") not in text

    def test_it_exempts_replay_playback(self, code: list[tuple[int, str, str]]) -> None:
        text = [f"{m} {op}" for _, m, op in code]
        assert f"mov eax, dword ptr [0x{THE_RECORDER:x}]" in text
        assert f"cmp dword ptr [eax + 0x{RECORDER_MODE:x}], {RECORDER_MODE_PLAYBACK}" in text

    def test_it_mixes_the_hash_into_the_checksum_register(
        self, code: list[tuple[int, str, str]]
    ) -> None:
        text = [f"{m} {op}" for _, m, op in code]
        assert f"mov eax, dword ptr [0x{BASE + HASH_OFF:x}]" in text
        assert "xor edi, eax" in text

    def test_it_caches_behind_a_flag_separate_from_the_value(
        self, code: list[tuple[int, str, str]]
    ) -> None:
        """Nonzero-means-computed would rehash forever on the one image whose code folds to 0."""
        text = [f"{m} {op}" for _, m, op in code]
        assert f"mov eax, dword ptr [0x{BASE + READY_OFF:x}]" in text
        assert f"mov dword ptr [0x{BASE + READY_OFF:x}], 1" in text

    def test_it_reemits_the_displaced_instruction_and_returns(
        self, code: list[tuple[int, str, str]]
    ) -> None:
        """The tail has to restore what the six stolen bytes did, or the emitter calls
        `appendMessage` on whatever `ecx` happened to hold."""
        tail = [f"{m} {op}" for _, m, op in code]
        assert f"mov ecx, dword ptr [0x{0xDE6398:x}]" in tail
        assert f"jmp 0x{LOGIC_CRC_EMIT_RESUME:x}" in tail

    def test_the_displaced_instruction_is_reemitted_verbatim(self) -> None:
        section = build_section(BASE)
        assert LOGIC_CRC_EMIT_BYTES in section

    def test_the_fold_loop_walks_both_ranges_with_the_python_constants(
        self, code: list[tuple[int, str, str]]
    ) -> None:
        text = [f"{m} {op}" for _, m, op in code]
        assert f"mov eax, 0x{FNV_OFFSET_BASIS:x}" in text
        assert f"mov esi, 0x{TEXT_SECTION_VA:x}" in text
        assert f"mov ecx, 0x{TEXT_SECTION_LEN // 4:x}" in text
        assert f"mov esi, 0x{BASE + CODE_OFF:x}" in text
        assert f"mov ecx, 0x{(SECTION_LEN - CODE_OFF) // 4:x}" in text
        assert "xor eax, dword ptr [esi]" in text
        assert f"imul eax, eax, 0x{FNV_PRIME:x}" in text
        assert "add esi, 4" in text
        assert "dec ecx" in text


class TestExpectedHash:
    def test_it_refuses_an_unpatched_image(self, image: bytearray) -> None:
        with pytest.raises(ValueError, match="does not carry binary-attest"):
            expected_hash(image)

    def test_it_is_stable_across_recomputation(self, patched: bytearray) -> None:
        assert expected_hash(patched) == expected_hash(patched)

    def test_it_changes_when_a_single_byte_of_text_changes(self, patched: bytearray) -> None:
        """The property the whole patch sells. One byte anywhere in the code the game executes
        has to move the published checksum, or a fog-branch edit slips through."""
        before = expected_hash(patched)
        off = va_to_offset(patched, TEXT_SECTION_VA + 0x40)
        patched[off] ^= 0x01
        assert expected_hash(patched) != before

    def test_it_covers_the_caves_own_code(self, patched: bytearray) -> None:
        """Editing the attest routine itself is the cheapest way to defeat the patch, and it must
        at least perturb the value rather than being free."""
        before = expected_hash(patched)
        _, section_off, _ = find_section(patched, SECTION_NAME)
        patched[section_off + CODE_OFF + 4] ^= 0x01
        assert expected_hash(patched) != before

    def test_the_hash_slot_itself_is_not_hashed(self, patched: bytearray) -> None:
        """It is written at runtime, so folding it in would make the value depend on itself."""
        before = expected_hash(patched)
        _, section_off, _ = find_section(patched, SECTION_NAME)
        struct.pack_into("<II", patched, section_off + READY_OFF, 1, 0xDEADBEEF)
        assert expected_hash(patched) == before

    def test_it_matches_a_reference_fold(self, patched: bytearray) -> None:
        """An independent walk of the two ranges, written the naive way."""
        _, section_off, _ = find_section(patched, SECTION_NAME)
        text_off = va_to_offset(patched, TEXT_SECTION_VA)
        blob = bytes(patched[text_off : text_off + TEXT_SECTION_LEN]) + bytes(
            patched[section_off + CODE_OFF : section_off + SECTION_LEN]
        )
        digest = FNV_OFFSET_BASIS
        for (word,) in struct.iter_unpack("<I", blob):
            digest = ((digest ^ word) * FNV_PRIME) & 0xFFFFFFFF
        assert expected_hash(patched) == digest


@pytest.mark.skipif(not _GAME_DAT.exists(), reason="the ROTWK game.dat is not installed here")
class TestInstalledBinary:
    """Against the real thing, which is what says the addresses are right."""

    @pytest.fixture
    def stock(self) -> bytes:
        return _GAME_DAT.read_bytes()

    def test_the_emitter_holds_the_expected_bytes(self, stock: bytes) -> None:
        off = va_to_offset(stock, LOGIC_CRC_EMIT)
        assert bytes(stock[off : off + len(LOGIC_CRC_EMIT_BYTES)]) == LOGIC_CRC_EMIT_BYTES

    def test_the_crc_producer_still_folds_the_shroud_manager(self, stock: bytes) -> None:
        """The finding the patch is scoped by, asserted against the shipped binary: the shroud
        manager is xfer'd into the frame checksum, so shroud *state* is already attested."""
        off = va_to_offset(stock, LOGIC_CRC_SHROUD_XFER)
        got = bytes(stock[off : off + len(LOGIC_CRC_SHROUD_XFER_BYTES)])
        assert got == LOGIC_CRC_SHROUD_XFER_BYTES

    def test_it_applies_verifies_and_hashes(self, stock: bytes) -> None:
        data = bytearray(stock)
        patch = BinaryAttestPatch()
        patch.apply(data)
        assert patch.verify(data) == []
        assert expected_hash(data) != 0

    def test_it_composes_with_another_section_adding_patch(self, stock: bytes) -> None:
        """Order-independent in the framework's sense - both apply and both verify either way.
        The *values* differ between the two orders, and deliberately: the cave lands at a
        different address, so the attested image is a different image."""
        forward = bytearray(stock)
        for patch in (BinaryAttestPatch(), ReplayOutcomePatch()):
            patch.apply(forward)
        backward = bytearray(stock)
        for patch in (ReplayOutcomePatch(), BinaryAttestPatch()):
            patch.apply(backward)
        assert BinaryAttestPatch().verify(forward) == []
        assert BinaryAttestPatch().verify(backward) == []
        assert ReplayOutcomePatch().verify(forward) == []
        assert ReplayOutcomePatch().verify(backward) == []
        assert expected_hash(forward) != expected_hash(backward)

    def test_the_installed_binary_is_not_already_patched(self, stock: bytes) -> None:
        assert BinaryAttestPatch.detect(stock) is None
