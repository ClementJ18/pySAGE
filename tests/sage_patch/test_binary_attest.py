"""Tests for the binary-attest patch.

The cave is hand-assembled x86 that cannot be executed here, so the important tests disassemble
it back and assert it says what it was meant to say - a wrong byte in a hook does not raise, it
crashes the game mid-match.

The other half is the arithmetic. :func:`expected_hash` and the stub's `hash_image` are two
independent implementations of the same walk, and the whole value of the patch rests on them
agreeing: if the Python side cannot predict what the running game will publish, nobody can
compare two binaries without playing a game against each other.
"""

from __future__ import annotations

import struct

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
    THE_RECORDER,
)
from sage_patch.patcher import application_order  # noqa: E402
from sage_patch.patches.multiplayer.binary_attest import (  # noqa: E402
    CODE_OFF,
    FNV_OFFSET_BASIS,
    FNV_PRIME,
    HASH_OFF,
    HOOK_OFF,
    ORIGINAL_ENTRY_OFF,
    READY_OFF,
    SECTION_LEN,
    SECTION_NAME,
    BinaryAttestPatch,
    build_section,
    entry_stub_va,
    expected_hash,
    hash_routine_va,
    loader_written_ranges,
)
from sage_patch.patches.multiplayer.replay_outcome import ReplayOutcomePatch  # noqa: E402
from sage_patch.patches.platform.dll_load import DllLoadPatch  # noqa: E402
from sage_patch.registry import PATCHES  # noqa: E402
from sage_patch.utils import find_section, va_to_offset  # noqa: E402

from ..binaries import STOCK_GAME_DAT  # noqa: E402
from .synthetic import (  # noqa: E402
    ATTEST_COOKIE_VA,
    ATTEST_ENTRY_VA,
    ATTEST_IAT_VA,
    IMAGE_BASE,
    binary_attest_image,
)

BASE = 0x00F00000
EXCLUSIONS = [(0x00BD0000, 0x00BD0BFC), (0x00DBDB40, 0x00DBDB44)]


def _disasm(code: bytes, base: int) -> list[tuple[int, str, str]]:
    md = Cs(CS_ARCH_X86, CS_MODE_32)
    return [(i.address, i.mnemonic, i.op_str) for i in md.disasm(code, base)]


def _entry_va(data: bytes | bytearray) -> int:
    e_lfanew = struct.unpack_from("<I", data, 0x3C)[0]
    return IMAGE_BASE + struct.unpack_from("<I", data, e_lfanew + 24 + 16)[0]


@pytest.fixture
def image() -> bytearray:
    return binary_attest_image()


@pytest.fixture
def patched(image: bytearray) -> bytearray:
    BinaryAttestPatch().apply(image)
    return image


def _section_off(data: bytes | bytearray) -> int:
    located = find_section(data, SECTION_NAME)
    assert located is not None
    return located[1]


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

    def test_the_entry_point_becomes_the_stub_and_the_old_one_is_kept(
        self, patched: bytearray
    ) -> None:
        section_va, section_off, _ = find_section(patched, SECTION_NAME)
        assert _entry_va(patched) == entry_stub_va(section_va)
        kept = struct.unpack_from("<I", patched, section_off + ORIGINAL_ENTRY_OFF)[0]
        assert kept == ATTEST_ENTRY_VA

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

    def test_a_tampered_cave_fails_verification(self, patched: bytearray) -> None:
        """Editing the routine is the one attack the patch has to notice about itself."""
        patched[_section_off(patched) + CODE_OFF] ^= 0xFF
        assert any("expected routine" in p for p in BinaryAttestPatch().verify(patched))

    def test_moving_the_entry_point_afterwards_fails_verification(self, patched: bytearray) -> None:
        """A loader stub ahead of the hash would let its DLL change memory before it is read."""
        DllLoadPatch().apply(patched)
        assert any("entry point" in p for p in BinaryAttestPatch().verify(patched))

    def test_moving_the_entry_point_first_composes(self, image: bytearray) -> None:
        DllLoadPatch().apply(image)
        BinaryAttestPatch().apply(image)
        assert BinaryAttestPatch().verify(image) == []
        # Its stub is now second in line, behind the hash, and it still recognises itself.
        assert DllLoadPatch().verify(image) == []
        assert DllLoadPatch.detect(image) is not None

    def test_a_new_import_afterwards_fails_verification(self, patched: bytearray) -> None:
        """The loader would write a table the hash folds, and each machine would differ."""
        terminator = va_to_offset(patched, ATTEST_IAT_VA + 0x10)
        struct.pack_into("<I", patched, terminator, 0x400)
        assert any("loader-written" in p for p in BinaryAttestPatch().verify(patched))


class TestLoaderWrittenRanges:
    def test_back_to_back_tables_merge_and_the_cookie_is_its_own(self, image: bytearray) -> None:
        assert loader_written_ranges(image) == [
            (ATTEST_IAT_VA, ATTEST_IAT_VA + 0x14),
            (ATTEST_COOKIE_VA, ATTEST_COOKIE_VA + 4),
        ]

    def test_an_image_with_neither_has_none(self, image: bytearray) -> None:
        e_lfanew = struct.unpack_from("<I", image, 0x3C)[0]
        for directory in (1, 10):
            struct.pack_into("<II", image, e_lfanew + 24 + 96 + 8 * directory, 0, 0)
        assert loader_written_ranges(image) == []


class TestCave:
    """The hand-assembled routines, disassembled back."""

    @pytest.fixture
    def code(self) -> list[tuple[int, str, str]]:
        section = build_section(BASE, IMAGE_BASE, ATTEST_ENTRY_VA, EXCLUSIONS)
        return _disasm(section[CODE_OFF:], BASE + CODE_OFF)

    @pytest.fixture
    def text(self, code: list[tuple[int, str, str]]) -> list[str]:
        return [f"{m} {op}".strip() for _, m, op in code]

    def test_it_fits_the_section(self) -> None:
        assert len(build_section(BASE, IMAGE_BASE, ATTEST_ENTRY_VA, EXCLUSIONS)) == SECTION_LEN

    def test_the_exclusion_table_is_laid_out_for_the_walk(self) -> None:
        section = build_section(BASE, IMAGE_BASE, ATTEST_ENTRY_VA, EXCLUSIONS, hook=0x1234)
        assert struct.unpack_from("<IIII", section, HOOK_OFF) == (
            0x1234,
            ATTEST_ENTRY_VA,
            2,
            EXCLUSIONS[0][0],
        )

    def test_the_heartbeat_preserves_every_register_but_edi(
        self, code: list[tuple[int, str, str]], text: list[str]
    ) -> None:
        """`edi` carries the checksum and is the one register meant to change. Everything else
        belongs to the emitter, which is mid-way through building a message."""
        assert [op for _, m, op in code[:4]] == ["eax", "ecx", "edx", "esi"]
        assert code[4][1] == "pushfd"
        assert "push edi" not in text

    def test_it_exempts_replay_playback(self, text: list[str]) -> None:
        assert f"mov eax, dword ptr [0x{THE_RECORDER:x}]" in text
        assert f"cmp dword ptr [eax + 0x{RECORDER_MODE:x}], {RECORDER_MODE_PLAYBACK}" in text

    def test_it_mixes_the_stored_hash_into_the_checksum_register(self, text: list[str]) -> None:
        assert f"mov eax, dword ptr [0x{BASE + HASH_OFF:x}]" in text
        assert "xor edi, eax" in text

    def test_it_calls_a_hooked_routine_with_every_register_saved(self, text: list[str]) -> None:
        at = text.index(f"mov eax, dword ptr [0x{BASE + HOOK_OFF:x}]")
        assert text[at + 1] == "test eax, eax"
        assert text[at + 2].startswith("je ")
        assert text[at + 3 : at + 6] == ["pushal", "call eax", "popal"]

    def test_it_reemits_the_displaced_instruction_and_returns(self, text: list[str]) -> None:
        """The tail has to restore what the six stolen bytes did, or the emitter calls
        `appendMessage` on whatever `ecx` happened to hold."""
        assert f"mov ecx, dword ptr [0x{0xDE6398:x}]" in text
        assert f"jmp 0x{LOGIC_CRC_EMIT_RESUME:x}" in text
        assert LOGIC_CRC_EMIT_BYTES in build_section(BASE, IMAGE_BASE, ATTEST_ENTRY_VA, [])

    def test_the_entry_stub_hashes_stores_and_goes_on_to_the_original_entry(self) -> None:
        stub = entry_stub_va(BASE)
        section = build_section(BASE, IMAGE_BASE, ATTEST_ENTRY_VA, EXCLUSIONS)
        code = _disasm(section[stub - BASE :], stub)
        text = [f"{m} {op}".strip() for _, m, op in code[:8]]
        assert text == [
            "pushfd",
            "pushal",
            f"call 0x{hash_routine_va(BASE):x}",
            f"mov dword ptr [0x{BASE + HASH_OFF:x}], eax",
            f"mov dword ptr [0x{BASE + READY_OFF:x}], 1",
            "popal",
            "popfd",
            f"jmp 0x{ATTEST_ENTRY_VA:x}",
        ]

    def test_the_walk_reads_the_section_table_and_folds_with_the_python_constants(
        self, text: list[str]
    ) -> None:
        assert f"mov eax, 0x{FNV_OFFSET_BASIS:x}" in text
        assert f"mov ebx, dword ptr [0x{IMAGE_BASE + 0x3C:x}]" in text
        assert "movzx ecx, word ptr [ebx + 6]" in text
        assert "test dword ptr [ebx + 0x24], 0x40000000" in text
        assert "xor eax, dword ptr [esi]" in text
        assert f"imul eax, eax, 0x{FNV_PRIME:x}" in text
        assert "add ebx, 0x28" in text


class TestExpectedHash:
    def test_it_refuses_an_unpatched_image(self, image: bytearray) -> None:
        with pytest.raises(ValueError, match="does not carry binary-attest"):
            expected_hash(image)

    def test_it_is_stable_across_recomputation(self, patched: bytearray) -> None:
        assert expected_hash(patched) == expected_hash(patched)

    def test_it_changes_when_a_single_byte_anywhere_changes(self, patched: bytearray) -> None:
        """The property the whole patch sells: one byte anywhere in the image - code, data or
        another patch's cave - has to move the published checksum."""
        before = expected_hash(patched)
        off = va_to_offset(patched, LOGIC_CRC_SHROUD_XFER)
        patched[off] ^= 0x01
        assert expected_hash(patched) != before

    def test_it_covers_the_caves_own_code_and_the_hook_slot(self, patched: bytearray) -> None:
        before = expected_hash(patched)
        off = _section_off(patched)
        patched[off + CODE_OFF + 4] ^= 0x01
        assert expected_hash(patched) != before
        patched[off + CODE_OFF + 4] ^= 0x01
        struct.pack_into("<I", patched, off + HOOK_OFF, 0x1234)
        assert expected_hash(patched) != before

    def test_what_the_loader_writes_is_not_hashed(self, patched: bytearray) -> None:
        """Each machine's DLL addresses and a random cookie, so folding them would make every
        player attest to a different value."""
        before = expected_hash(patched)
        struct.pack_into("<I", patched, va_to_offset(patched, ATTEST_IAT_VA), 0x76543210)
        struct.pack_into("<I", patched, va_to_offset(patched, ATTEST_COOKIE_VA), 0x12345678)
        assert expected_hash(patched) == before


@pytest.mark.skipif(not STOCK_GAME_DAT.is_file(), reason="the ROTWK game.dat is not here")
class TestInstalledBinary:
    """Against the real thing, which is what says the addresses are right."""

    @pytest.fixture
    def stock(self) -> bytes:
        return STOCK_GAME_DAT.read_bytes()

    def test_the_emitter_holds_the_expected_bytes(self, stock: bytes) -> None:
        off = va_to_offset(stock, LOGIC_CRC_EMIT)
        assert bytes(stock[off : off + len(LOGIC_CRC_EMIT_BYTES)]) == LOGIC_CRC_EMIT_BYTES

    def test_the_crc_producer_still_folds_the_shroud_manager(self, stock: bytes) -> None:
        """The finding the patch is scoped by, asserted against the shipped binary: the shroud
        manager is xfer'd into the frame checksum, so shroud *state* is already attested."""
        off = va_to_offset(stock, LOGIC_CRC_SHROUD_XFER)
        got = bytes(stock[off : off + len(LOGIC_CRC_SHROUD_XFER_BYTES)])
        assert got == LOGIC_CRC_SHROUD_XFER_BYTES

    def test_the_loader_writes_the_import_tables_and_the_cookie(self, stock: bytes) -> None:
        """`game.dat` leaves its IAT directory empty; the 23 tables sit back to back."""
        assert loader_written_ranges(stock) == EXCLUSIONS

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
        for data in (forward, backward):
            assert BinaryAttestPatch().verify(data) == []
            assert ReplayOutcomePatch().verify(data) == []
        assert expected_hash(forward) != expected_hash(backward)

    def test_the_installed_binary_is_not_already_patched(self, stock: bytes) -> None:
        assert BinaryAttestPatch.detect(stock) is None


class TestApplicationOrder:
    def test_it_goes_after_the_patches_that_move_the_entry_point(self, image: bytearray) -> None:
        """A build listed alphabetically - as the registry and a generated `.sagepatch` list it -
        still applies binary-attest after dll-load."""
        ordered = application_order([BinaryAttestPatch(), DllLoadPatch(), ReplayOutcomePatch()])
        assert [patch.name for patch in ordered] == ["dll-load", "binary-attest", "replay-outcome"]
        for patch in ordered[:2]:
            patch.apply(image)
        assert BinaryAttestPatch().verify(image) == []
        assert DllLoadPatch().verify(image) == []

    def test_an_unconstrained_list_keeps_its_order(self) -> None:
        patches = [ReplayOutcomePatch(), DllLoadPatch()]
        assert application_order(patches) == patches
