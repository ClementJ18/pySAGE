"""Tests for `render-only-frames`: the round trip, every edit against its stock bytes, and the
shape of the routines. `test_render_only_frames_emulated.py` runs them."""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

from sage_patch import apply_patches
from sage_patch.patches.render.render_only_frames import (
    ANCHORS,
    CACHE,
    CACHE_CHECK_FIELD,
    CACHE_FRAME,
    CALC_CALL,
    CALC_PHYSICS_XFORM,
    CALC_RESULT_TEST,
    COUNTER_IDIVS,
    COUNTER_IMULS,
    COUNTER_STEPS,
    ELAPSED_PUSHES,
    FADE_LATCH_CALL,
    FRAME_LENGTH,
    LOCO_INFO_ALLOCS,
    LOCO_INFO_PATCHED_SIZE,
    LOCO_INFO_SIZE,
    LOGIC_LATCH,
    RUNTIME_BYTES,
    SECTION_NAME,
    RenderOnlyFramesPatch,
    cave_code,
    layout,
)
from sage_patch.utils import find_section, va_to_offset

from .synthetic import render_only_frames_image

_GAME_DAT = Path(__file__).resolve().parents[2] / "game.dat"


def at(data: bytes | bytearray, va: int, length: int) -> bytes:
    off = va_to_offset(data, va)
    assert off is not None, f"0x{va:08x} is not mapped"
    return bytes(data[off : off + length])


def rel32_target(data: bytes | bytearray, va: int) -> int:
    return va + 5 + struct.unpack("<i", at(data, va + 1, 4))[0]


@pytest.fixture
def image() -> bytearray:
    return render_only_frames_image()


def _patched(image: bytearray) -> bytearray:
    data = bytearray(image)
    RenderOnlyFramesPatch().apply(data)
    return data


def _cave(data: bytes | bytearray) -> int:
    located = find_section(data, SECTION_NAME)
    assert located is not None
    return located[0]


class TestRoundTrip:
    def test_apply_then_verify(self, image: bytearray) -> None:
        assert RenderOnlyFramesPatch().verify(_patched(image)) == []

    def test_verify_rejects_an_unpatched_image(self, image: bytearray) -> None:
        assert RenderOnlyFramesPatch().verify(image)

    def test_detect(self, image: bytearray) -> None:
        assert RenderOnlyFramesPatch.detect(_patched(image)) is not None
        assert RenderOnlyFramesPatch.detect(image) is None

    def test_a_second_apply_refuses(self, image: bytearray) -> None:
        data = _patched(image)
        with pytest.raises(ValueError):
            RenderOnlyFramesPatch().apply(data)

    def test_verify_ignores_the_run_time_dwords(self, image: bytearray) -> None:
        data = _patched(image)
        cave = _cave(data)
        lay = layout(cave)
        for va in (lay.fade_frame, lay.scratch, *lay.counter_clocks, *lay.push_clocks):
            off = va_to_offset(data, va)
            assert off is not None
            data[off : off + 4] = struct.pack("<I", 987654)
        assert RenderOnlyFramesPatch().verify(data) == []

    def test_the_run_time_dwords_are_the_tail(self, image: bytearray) -> None:
        cave = _cave(_patched(image))
        lay = layout(cave)
        end = cave + len(cave_code(cave))
        assert lay.one == end - RUNTIME_BYTES - 4
        runtime = [lay.fade_frame, lay.scratch, *lay.counter_clocks, *lay.push_clocks]
        assert runtime == list(range(end - RUNTIME_BYTES, end, 4))

    def test_it_refuses_when_the_answer_test_has_moved(self, image: bytearray) -> None:
        off = va_to_offset(image, CALC_RESULT_TEST)
        assert off is not None
        image[off] ^= 0xFF
        with pytest.raises(ValueError, match="anchor"):
            RenderOnlyFramesPatch().apply(image)


class TestThePhysicsCache:
    def test_the_call_now_reaches_the_wrapper(self, image: bytearray) -> None:
        data = _patched(image)
        assert at(data, CALC_CALL, 1) == b"\xe8"
        assert rel32_target(data, CALC_CALL) == _cave(data)

    def test_the_wrapper_still_calls_the_real_function(self, image: bytearray) -> None:
        capstone = pytest.importorskip("capstone")
        md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
        cave = 0x01000000
        calls = [i for i in md.disasm(cave_code(cave), cave) if i.mnemonic == "call"]
        assert f"0x{CALC_PHYSICS_XFORM:x}" in [c.op_str for c in calls]

    @pytest.mark.parametrize("va", LOCO_INFO_ALLOCS)
    def test_every_allocation_grows_by_the_cache(self, image: bytearray, va: int) -> None:
        assert at(image, va, 2) == bytes((0x6A, LOCO_INFO_SIZE))
        assert at(_patched(image), va, 2) == bytes((0x6A, LOCO_INFO_PATCHED_SIZE))

    def test_the_cache_sits_wholly_in_the_added_tail(self) -> None:
        """Below `LOCO_INFO_SIZE` is the engine's own state; the cache must not reach into it,
        and the block must be big enough for the last field."""
        assert CACHE >= LOCO_INFO_SIZE
        assert CACHE_FRAME == CACHE + 0x10
        assert CACHE_CHECK_FIELD + 4 <= LOCO_INFO_PATCHED_SIZE
        assert LOCO_INFO_PATCHED_SIZE < 0x80, "the push is a signed imm8"


class TestTheCameraMoves:
    @pytest.mark.parametrize("va", COUNTER_IDIVS)
    def test_each_division_reads_the_one(self, image: bytearray, va: int) -> None:
        data = _patched(image)
        assert at(data, va, 2) == bytes.fromhex("f73d"), "no longer an idiv [mem]"
        assert struct.unpack("<I", at(data, va + 2, 4))[0] == layout(_cave(data)).one

    @pytest.mark.parametrize("va", COUNTER_IMULS)
    def test_each_multiply_reads_the_one(self, image: bytearray, va: int) -> None:
        data = _patched(image)
        assert at(data, va, 3) == bytes.fromhex("0faf05"), "no longer an imul eax, [mem]"
        assert struct.unpack("<I", at(data, va + 3, 4))[0] == layout(_cave(data)).one

    def test_the_one_is_one(self, image: bytearray) -> None:
        data = _patched(image)
        assert at(data, layout(_cave(data)).one, 4) == struct.pack("<I", 1)

    @pytest.mark.parametrize("index", range(len(COUNTER_STEPS)))
    def test_each_counter_step_calls_its_own_routine(self, image: bytearray, index: int) -> None:
        data = _patched(image)
        va = COUNTER_STEPS[index][0]
        assert at(data, va, 1) == b"\xe8"
        assert rel32_target(data, va) == layout(_cave(data)).counter_steps[index]
        assert at(data, va + 5, 1) == b"\x90"

    @pytest.mark.parametrize("index", range(len(ELAPSED_PUSHES)))
    def test_each_path_push_calls_its_own_routine(self, image: bytearray, index: int) -> None:
        data = _patched(image)
        va = ELAPSED_PUSHES[index]
        assert at(data, va, 1) == b"\xe8"
        assert rel32_target(data, va) == layout(_cave(data)).elapsed_pushes[index]
        assert at(data, va + 5, 1) == b"\x90"

    def test_every_counter_and_push_has_its_own_clock(self) -> None:
        """Zoom, pitch and a rotation can run together; a shared clock would hand the second
        one the few microseconds since the first."""
        lay = layout(0x01000000)
        clocks = lay.counter_clocks + lay.push_clocks
        assert len(set(clocks)) == len(COUNTER_STEPS) + len(ELAPSED_PUSHES)

    def test_the_counters_are_distinct_fields(self) -> None:
        assert len({field for _va, field, _what in COUNTER_STEPS}) == len(COUNTER_STEPS)

    def test_the_frame_length_itself_is_not_written(self) -> None:
        """Everything else that reads it (start-up, the W3D animation clock) keeps reading 33."""
        assert FRAME_LENGTH not in ANCHORS


class TestTheFadeLatch:
    def test_the_call_now_reaches_the_wrapper(self, image: bytearray) -> None:
        data = _patched(image)
        assert at(data, FADE_LATCH_CALL, 1) == b"\xe8"
        assert rel32_target(data, FADE_LATCH_CALL) == layout(_cave(data)).fade_latch

    def test_the_wrapper_still_asks_the_real_latch(self) -> None:
        capstone = pytest.importorskip("capstone")
        md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
        cave = 0x01000000
        entry = layout(cave).fade_latch
        first = next(md.disasm(cave_code(cave)[entry - cave :], entry, 1))
        assert (first.mnemonic, int(first.op_str, 16)) == ("call", LOGIC_LATCH)

    def test_no_fade_has_stepped_when_the_game_starts(self, image: bytearray) -> None:
        data = _patched(image)
        assert at(data, layout(_cave(data)).fade_frame, 4) == b"\xff" * 4


class TestTheRealBinary:
    @pytest.fixture(scope="class")
    @staticmethod
    def game_dat() -> bytes:
        if not _GAME_DAT.exists():
            pytest.skip(f"no {_GAME_DAT}")
        return _GAME_DAT.read_bytes()

    def test_every_anchor_holds_what_the_patch_says_it_holds(self, game_dat: bytes) -> None:
        for va, expected in sorted(ANCHORS.items()):
            assert at(game_dat, va, len(expected)) == expected, f"0x{va:08X}"

    def test_the_frame_length_is_initialised_from_the_client_rate(self, game_dat: bytes) -> None:
        """`mov eax, 1000` / `cdq` / `idiv [clientRate]` / `mov [FRAME_LENGTH], eax`."""
        assert at(game_dat, 0x00BC146C, 17) == bytes.fromhex("b8e803000099f73d0cf6d900a38c7adc00")

    def test_apply_and_verify_on_the_real_thing(self, game_dat: bytes, tmp_path: Path) -> None:
        src = tmp_path / "game.dat"
        src.write_bytes(game_dat)
        out = apply_patches(src, [RenderOnlyFramesPatch()], tmp_path / "out.dat")
        assert RenderOnlyFramesPatch().verify(out.read_bytes()) == []
        assert src.read_bytes() == game_dat, "the input was modified"
