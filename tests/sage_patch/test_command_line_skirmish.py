"""Tests for the command-line-skirmish patch.

The cave is hand-assembled x86 that cannot be executed here: it runs once, inside
`GameEngine::init`, against a `GameInfo` that only exists in a started game. So the tests that
matter disassemble it back and assert it says what it was meant to say, and single out the two
failure modes `apply` and `verify` cannot see.

The first is the **displaced tail**. The setup hook takes nine bytes that end in a relative
`call`, so the cave has to re-emit that call against its own address and then return to the
instruction after the nine - and a wrong displacement there assembles, applies and verifies
exactly like a right one.

The second is the **guard's stock arm**. The point of relocating the loading screen's progress
update is that a non-null window still gets the identical sequence of instructions; a guard that
quietly dropped one of them would look correct in every other test here.
"""

from __future__ import annotations

import struct
from pathlib import Path

import capstone
import pytest

from sage_patch.addresses import (
    COMMAND_LINE_SKIRMISH_SETUP,
    COMMAND_LINE_SKIRMISH_SETUP_BYTES,
    COMMAND_LINE_SKIRMISH_SETUP_RESUME,
    GAME_MESSAGE_APPEND_INTEGER,
    LOADING_SCREEN_PROGRESS,
    LOADING_SCREEN_PROGRESS_BYTES,
    LOADING_SCREEN_PROGRESS_RESUME,
    THE_GAME_INFO,
    THE_SKIRMISH_GAME_INFO,
)
from sage_patch.patches.experimental.command_line_skirmish import (
    MAGIC,
    SECTION_NAME,
    CommandLineSkirmishPatch,
)
from sage_patch.registry import PATCHES
from sage_patch.utils import find_section, va_to_offset

from .synthetic import command_line_skirmish_image

_GAME_DAT = Path(__file__).resolve().parents[2] / "game.dat"


def _patched(**kwargs) -> tuple[bytearray, CommandLineSkirmishPatch]:
    data = command_line_skirmish_image()
    patch = CommandLineSkirmishPatch(**kwargs)
    patch.apply(data)
    return data, patch


def _jump_target(data: bytes | bytearray, va: int) -> int:
    """Where the five-byte jump planted at `va` goes."""
    offset = va_to_offset(data, va)
    assert offset is not None
    assert data[offset] == 0xE9, "not a near jump"
    return va + 5 + struct.unpack_from("<i", bytes(data), offset + 1)[0]


def _disasm(data: bytes | bytearray, start_va: int, count: int) -> list:
    base_va, file_off, size = find_section(data, SECTION_NAME)
    blob = bytes(data)[file_off : file_off + size]
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    md.detail = False
    return list(md.disasm(blob[start_va - base_va :], start_va))[:count]


class TestStockBytes:
    """Both sites hold what the patch asserts before it writes, in the real build."""

    @pytest.mark.skipif(not _GAME_DAT.exists(), reason="needs the real game.dat")
    @pytest.mark.parametrize(
        ("va", "expected"),
        [
            (COMMAND_LINE_SKIRMISH_SETUP, COMMAND_LINE_SKIRMISH_SETUP_BYTES),
            (LOADING_SCREEN_PROGRESS, LOADING_SCREEN_PROGRESS_BYTES),
        ],
        ids=["skirmish-setup", "loading-screen-progress"],
    )
    def test_the_site_holds_the_bytes_the_patch_expects(self, va, expected):
        data = _GAME_DAT.read_bytes()
        offset = va_to_offset(data, va)
        assert data[offset : offset + len(expected)] == expected

    @pytest.mark.skipif(not _GAME_DAT.exists(), reason="needs the real game.dat")
    def test_the_displaced_tail_really_calls_append_integer(self):
        """The nine displaced bytes end in `call appendIntegerArgument`, decoded rather than
        assumed - that is what makes re-emitting it in the cave the right thing to do."""
        rel = struct.unpack("<i", COMMAND_LINE_SKIRMISH_SETUP_BYTES[5:9])[0]
        assert COMMAND_LINE_SKIRMISH_SETUP + 9 + rel == GAME_MESSAGE_APPEND_INTEGER

    @pytest.mark.skipif(not _GAME_DAT.exists(), reason="needs the real game.dat")
    def test_it_applies_to_the_real_binary(self):
        data = bytearray(_GAME_DAT.read_bytes())
        patch = CommandLineSkirmishPatch()
        patch.apply(data)
        assert patch.verify(data) == []


class TestRoundTrip:
    def test_apply_then_verify(self):
        data, patch = _patched()
        assert patch.verify(data) == []

    def test_detect_recovers_the_parameters(self):
        data, _ = _patched(human_faction=8, ai_faction=12, resources=12345)
        found = CommandLineSkirmishPatch.detect(data)
        assert found is not None
        assert found.options() == {
            "human_faction": 8,
            "ai_faction": 12,
            "resources": 12345,
        }

    def test_a_default_probe_does_not_claim_a_custom_build(self):
        """`verify` answers "does this carry *this* configuration", so the defaults must not
        report a build made with other parameters as present."""
        data, _ = _patched(human_faction=8, ai_faction=12, resources=12345)
        assert CommandLineSkirmishPatch().verify(data) != []

    def test_an_unpatched_image_carries_nothing(self):
        assert CommandLineSkirmishPatch.detect(command_line_skirmish_image()) is None

    def test_detection_never_raises_on_something_that_is_not_a_game_dat(self):
        assert CommandLineSkirmishPatch.detect(bytearray(b"MZ" + bytes(4096))) is None

    def test_applying_twice_fails_loudly(self):
        """The second apply meets its own jump where it asserts stock bytes."""
        data, patch = _patched()
        with pytest.raises(ValueError):
            patch.apply(data)


class TestTheSetupRoutine:
    def test_the_hook_jumps_into_the_cave(self):
        data, _ = _patched()
        base_va, _off, size = find_section(data, SECTION_NAME)
        target = _jump_target(data, COMMAND_LINE_SKIRMISH_SETUP)
        assert base_va <= target < base_va + size

    def test_the_nine_bytes_are_fully_consumed(self):
        """Five for the jump and four `nop`s - a shorter fill would leave a fragment of the
        original call to be executed as an instruction."""
        data, _ = _patched()
        offset = va_to_offset(data, COMMAND_LINE_SKIRMISH_SETUP)
        planted = bytes(data[offset : offset + len(COMMAND_LINE_SKIRMISH_SETUP_BYTES)])
        assert planted[0] == 0xE9
        assert planted[5:] == b"\x90" * (len(COMMAND_LINE_SKIRMISH_SETUP_BYTES) - 5)

    def test_it_reads_the_skirmish_game_info_and_writes_the_live_one(self):
        data, _ = _patched()
        setup = _jump_target(data, COMMAND_LINE_SKIRMISH_SETUP)
        text = [f"{i.mnemonic} {i.op_str}" for i in _disasm(data, setup, 120)]
        assert f"mov esi, dword ptr [0x{THE_SKIRMISH_GAME_INFO:x}]" in text
        assert f"mov dword ptr [0x{THE_GAME_INFO:x}], esi" in text

    def test_it_preserves_every_register_it_borrows(self):
        """`edi` carries the `GameMessage` the displaced tail passes in `ecx`, and the cave
        clobbers `eax` and `esi`. A `pushad`/`popad` pair around the body is what keeps the
        re-emitted tail seeing the frame the stock code would have."""
        data, _ = _patched()
        setup = _jump_target(data, COMMAND_LINE_SKIRMISH_SETUP)
        body = _disasm(data, setup, 120)
        text = [i.mnemonic for i in body]
        assert text[0] == "pushal"
        assert text[1] == "pushfd"
        assert text.index("popfd") < text.index("popal")
        assert text.count("pushal") == text.count("popal") == 1

    def test_it_re_emits_the_displaced_tail_and_returns(self):
        """The failure this exists for: the displaced `call` is relative, so re-emitting it in
        the cave needs a recomputed displacement, and the routine must resume at the instruction
        after the nine bytes it replaced."""
        data, _ = _patched()
        setup = _jump_target(data, COMMAND_LINE_SKIRMISH_SETUP)
        body = _disasm(data, setup, 200)
        tail = [f"{i.mnemonic} {i.op_str}" for i in body]
        assert "push 2" in tail
        assert "mov ecx, edi" in tail
        assert f"call 0x{GAME_MESSAGE_APPEND_INTEGER:x}" in tail
        assert f"jmp 0x{COMMAND_LINE_SKIRMISH_SETUP_RESUME:x}" in tail
        # ...and in that order, immediately before the return jump
        window = tail[tail.index("push 2") :]
        assert window[:4] == [
            "push 2",
            "mov ecx, edi",
            f"call 0x{GAME_MESSAGE_APPEND_INTEGER:x}",
            f"jmp 0x{COMMAND_LINE_SKIRMISH_SETUP_RESUME:x}",
        ]

    def test_the_map_player_strings_are_aligned_and_saturated(self):
        """`GAME_SLOT_MAP_PLAYER` is an `AsciiString`, so the cave carries real refcounted blocks.
        The refcount must be large enough that a release the engine makes on its own schedule can
        never free a page it did not allocate, and each block starts dword-aligned because that
        refcount is a dword the engine may write."""
        data, _ = _patched()
        base_va, file_off, size = find_section(data, SECTION_NAME)
        blob = bytes(data)[file_off : file_off + size]
        found = {}
        for text in (b"Player_1\x00", b"Player_2\x00"):
            at = blob.index(text)
            block = at - 8
            assert block % 4 == 0, f"{text!r} block is not dword-aligned"
            refcount, length, allocated = struct.unpack_from("<IHH", blob, block)
            assert refcount == 0x7FFFFFFF
            assert length == len(text) - 1
            assert allocated == len(text)
            found[text] = base_va + block
        assert len(found) == 2


class TestTheGuard:
    def test_the_hook_jumps_into_the_cave(self):
        data, _ = _patched()
        base_va, _off, size = find_section(data, SECTION_NAME)
        target = _jump_target(data, LOADING_SCREEN_PROGRESS)
        assert base_va <= target < base_va + size

    def test_the_twenty_four_bytes_are_fully_consumed(self):
        data, _ = _patched()
        offset = va_to_offset(data, LOADING_SCREEN_PROGRESS)
        planted = bytes(data[offset : offset + len(LOADING_SCREEN_PROGRESS_BYTES)])
        assert planted[0] == 0xE9
        assert planted[5:] == b"\x90" * (len(LOADING_SCREEN_PROGRESS_BYTES) - 5)

    def test_the_stock_arm_reproduces_the_original_instructions(self):
        """The relocated block must be instruction-for-instruction what it replaced, apart from
        the recomputed displacement on its one relative call. Anything dropped here is a silent
        behaviour change on the path that used to work."""
        md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
        original = [
            (i.mnemonic, i.op_str)
            for i in md.disasm(LOADING_SCREEN_PROGRESS_BYTES, LOADING_SCREEN_PROGRESS)
        ]
        data, _ = _patched()
        guard = _jump_target(data, LOADING_SCREEN_PROGRESS)
        body = [(i.mnemonic, i.op_str) for i in _disasm(data, guard, 12)]
        # the guard's own test and branch come first, then the stock sequence
        assert body[0] == original[0], "the window load must come first, unchanged"
        assert body[1][0] == "test"
        assert body[2][0] == "je"
        stock = [op for op in original[1:] if op[0] != "call" or not op[1].startswith("0x")]
        assert [op for op in body[3:] if op in stock] == stock

    def test_both_arms_converge_on_the_resume_point(self):
        data, _ = _patched()
        guard = _jump_target(data, LOADING_SCREEN_PROGRESS)
        body = _disasm(data, guard, 12)
        text = [f"{i.mnemonic} {i.op_str}" for i in body]
        assert f"jmp 0x{LOADING_SCREEN_PROGRESS_RESUME:x}" in text
        skip = next(i for i in body if i.mnemonic == "je")
        landing = next(i for i in body if i.address == int(skip.op_str, 16))
        assert landing.mnemonic == "jmp"
        assert landing.op_str == f"0x{LOADING_SCREEN_PROGRESS_RESUME:x}"


class TestComposition:
    def test_the_cave_lands_past_every_existing_section(self):
        data, _ = _patched()
        base_va, _off, _size = find_section(data, SECTION_NAME)
        e = struct.unpack_from("<I", bytes(data), 0x3C)[0]
        count = struct.unpack_from("<H", bytes(data), e + 6)[0]
        table = e + 24 + struct.unpack_from("<H", bytes(data), e + 20)[0]
        rvas = [struct.unpack_from("<I", bytes(data), table + i * 40 + 12)[0] for i in range(count)]
        assert rvas == sorted(rvas)
        assert base_va == max(rvas) + 0x400000

    def test_verify_finds_the_cave_by_name(self):
        data, patch = _patched()
        assert find_section(data, SECTION_NAME) is not None
        assert patch.verify(data) == []

    def test_the_section_starts_with_its_magic(self):
        data, _ = _patched()
        _base, file_off, _size = find_section(data, SECTION_NAME)
        assert bytes(data)[file_off : file_off + len(MAGIC)] == MAGIC


class TestRegistration:
    def test_it_is_reachable_from_the_cli(self):
        assert PATCHES[CommandLineSkirmishPatch.name] is CommandLineSkirmishPatch

    def test_it_declares_itself_experimental(self):
        assert CommandLineSkirmishPatch().experimental is True
        assert "experimental" in CommandLineSkirmishPatch.__module__
