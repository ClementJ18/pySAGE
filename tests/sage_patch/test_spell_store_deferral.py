"""Tests for `spell-store-deferral`, which re-sends the spellbook's button states once its movie
can accept them (`render-rate.md` §9.6).

Two routines in `.spstore` and three exits, every one an address the patch does not own, so the
disassembly is read back and each target compared against the engine address it is meant to be.
"""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

from sage_patch import apply_patches
from sage_patch.patches.commandbar.spell_store_deferral import (
    ANCHORS,
    DEFER_MS,
    GET_TICK_COUNT,
    SECTION_NAME,
    STATE_RESET,
    STATE_RESET_RESUME,
    STATE_RESET_STOCK,
    STORE_STATES,
    STORE_STATES_END,
    UPDATE_LOOP,
    UPDATE_LOOP_DONE,
    UPDATE_LOOP_STOCK,
    UPDATE_LOOP_TOP,
    SpellStoreDeferralPatch,
    cave_code,
    defer_entry,
    tick_stamp,
)
from sage_patch.patches.render import render_rate as rrate
from sage_patch.patches.render.render_rate import RenderRatePatch
from sage_patch.utils import find_section, va_to_offset

from .synthetic import _sparse_image, spell_store_deferral_image

_GAME_DAT = Path(__file__).resolve().parents[2] / "game.dat"


def at(data: bytes | bytearray, va: int, length: int) -> bytes:
    off = va_to_offset(data, va)
    assert off is not None, f"0x{va:08x} is not mapped"
    return bytes(data[off : off + length])


def _characteristics(data: bytes | bytearray, name: str) -> int:
    lfanew = struct.unpack_from("<I", data, 0x3C)[0]
    count = struct.unpack_from("<H", data, lfanew + 6)[0]
    table = lfanew + 24 + struct.unpack_from("<H", data, lfanew + 20)[0]
    for index in range(count):
        header = table + index * 40
        if bytes(data[header : header + 8]).rstrip(bytes(1)).decode("ascii") == name:
            return int(struct.unpack_from("<I", data, header + 36)[0])
    raise AssertionError(f"no {name} section")


@pytest.fixture
def image() -> bytearray:
    return spell_store_deferral_image()


def _patched(image: bytearray) -> bytearray:
    data = bytearray(image)
    SpellStoreDeferralPatch().apply(data)
    return data


def _cave(data: bytes | bytearray) -> int:
    located = find_section(data, SECTION_NAME)
    assert located is not None
    return located[0]


def _text(data: bytes | bytearray) -> list[str]:
    capstone = pytest.importorskip("capstone")
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    located = find_section(data, SECTION_NAME)
    assert located is not None
    section_va, off, vsize = located
    return [
        f"{i.mnemonic} {i.op_str}" for i in md.disasm(bytes(data[off : off + vsize]), section_va)
    ]


class TestRoundTrip:
    def test_apply_then_verify(self, image: bytearray) -> None:
        assert SpellStoreDeferralPatch().verify(_patched(image)) == []

    def test_verify_rejects_an_unpatched_image(self, image: bytearray) -> None:
        assert SpellStoreDeferralPatch().verify(image)

    def test_detect(self, image: bytearray) -> None:
        assert SpellStoreDeferralPatch.detect(_patched(image)) is not None
        assert SpellStoreDeferralPatch.detect(image) is None

    def test_a_second_apply_refuses(self, image: bytearray) -> None:
        data = _patched(image)
        with pytest.raises(ValueError):
            SpellStoreDeferralPatch().apply(data)

    def test_verify_ignores_the_stamp_the_game_writes(self, image: bytearray) -> None:
        """The stamp is written at run time; a file is never saved with one, but a memory image
        read back from a running game would carry it, and that is still the patch."""
        data = _patched(image)
        off = va_to_offset(data, tick_stamp(_cave(data)))
        assert off is not None
        data[off : off + 4] = struct.pack("<I", 123456)
        assert SpellStoreDeferralPatch().verify(data) == []

    @pytest.mark.parametrize("va", [STATE_RESET_RESUME, UPDATE_LOOP_TOP, UPDATE_LOOP_DONE])
    def test_it_refuses_when_a_landing_has_moved(self, image: bytearray, va: int) -> None:
        off = va_to_offset(image, va)
        assert off is not None
        image[off] ^= 0xFF
        with pytest.raises(ValueError, match="landing"):
            SpellStoreDeferralPatch().apply(image)


class TestTheSection:
    def test_it_is_executable_and_writable_for_the_stamp(self, image: bytearray) -> None:
        data = _patched(image)
        flags = _characteristics(data, SECTION_NAME)
        assert flags & 0x20000000, "the cave is not executable"
        assert flags & 0x40000000, "the cave is not readable"
        assert flags & 0x80000000, "the tick stamp cannot be written"
        assert at(data, tick_stamp(_cave(data)), 4) == bytes(4)

    def test_the_stamp_is_behind_the_code(self, image: bytearray) -> None:
        data = _patched(image)
        cave = _cave(data)
        assert tick_stamp(cave) == cave + len(cave_code(cave)) - 4

    def test_every_exit_is_an_engine_address(self, image: bytearray) -> None:
        jumps = [t for t in _text(_patched(image)) if t.startswith("jmp ")]
        assert [int(t.split()[1], 16) for t in jumps] == [
            STATE_RESET_RESUME,
            UPDATE_LOOP_TOP,
            UPDATE_LOOP_DONE,
        ]


class TestTheStateReset:
    """Invalidate the cache when the panel initialises, and start the clock.

    The engine sends a button's state only when it differs from the value cached at
    `this+0x2AC`, and writes that cache whether or not the movie took the message - so a state
    the movie refused is never repeated. This routine stamps every slot with a value no computed
    state can equal, which makes the first send after the deferral cover all twenty.
    """

    def test_the_hook_is_a_near_jump_padded_to_the_whole_window(self, image: bytearray) -> None:
        data = _patched(image)
        window = at(data, STATE_RESET, len(STATE_RESET_STOCK))
        assert window[0] == 0xE9
        target = STATE_RESET + 5 + struct.unpack("<i", window[1:5])[0]
        assert target == _cave(data), "the hook does not land on the routine"
        assert set(window[5:]) == {0x90}, "the rest of the window is not nop"

    def test_the_displaced_store_is_carried_into_the_cave(self, image: bytearray) -> None:
        """The window taken over is `mov byte [ecx+0x2A0], 1` - the flag that tells `update` the
        panel is open. Losing it would leave the store shut and `update` returning immediately,
        which looks exactly like the bug this is fixing."""
        data = _patched(image)
        assert at(data, _cave(data), len(STATE_RESET_STOCK)) == STATE_RESET_STOCK

    def test_the_loop_covers_exactly_the_twenty_state_slots(self, image: bytearray) -> None:
        """The bounds are the two `lea`s, and the stride is the 8 that steps over each button
        pointer. Twenty is the count `update` itself iterates (`cmp [ebp-0x14], 0x14`), and a
        bound one pair too far would stamp `+0x34C`, a real field the handler resets to -1."""
        text = _text(_patched(image))
        assert f"lea edx, [ecx + 0x{STORE_STATES:x}]" in text
        assert f"lea ecx, [ecx + 0x{STORE_STATES_END:x}]" in text
        assert "add edx, 8" in text
        assert (STORE_STATES_END - STORE_STATES) // 8 == 20

    def test_the_sentinel_is_a_value_no_computed_state_can_equal(self, image: bytearray) -> None:
        """`update` computes 0..5 (the six labels at `0x00C50BF8`), and only ever compares the
        cache against that, so -1 is safe to park there and guarantees a mismatch."""
        assert "or eax, 0xffffffff" in _text(_patched(image))

    def test_it_writes_the_slots_and_not_the_button_pointers(self, image: bytearray) -> None:
        """`+0x2AC` is the state; `+0x2A8` is the `CommandButton` beside it. Starting the walk
        four bytes early would null every button and take the panel out entirely."""
        assert STORE_STATES - 4 == 0x2A8
        assert "mov dword ptr [edx], eax" in _text(_patched(image))


class TestTheDeferral:
    """The half that does the work: `update` sends nothing for the first `DEFER_MS` after the
    panel initialises, so that when the twenty sends go out the movie has built its button clips.

    Invalidating the cache without this is a no-op - `OnInitialized` is what sets `+0x2A0`, so the
    first update after it is the pass the original send was already happening on.
    """

    def test_the_hook_is_a_near_jump_padded_to_the_whole_window(self, image: bytearray) -> None:
        data = _patched(image)
        window = at(data, UPDATE_LOOP, len(UPDATE_LOOP_STOCK))
        assert window[0] == 0xE9
        target = UPDATE_LOOP + 5 + struct.unpack("<i", window[1:5])[0]
        assert target == defer_entry(_cave(data)), "the hook does not land on the deferral"
        assert set(window[5:]) == {0x90}, "the rest of the window is not nop"

    def test_the_displaced_loop_setup_is_carried_into_the_cave(self, image: bytearray) -> None:
        """The window taken over is the loop's index and cursor. Dropping either walks the wrong
        memory twenty times, which is a crash rather than a wrong colour."""
        data = _patched(image)
        located = find_section(data, SECTION_NAME)
        assert located is not None
        _va, off, vsize = located
        assert UPDATE_LOOP_STOCK in bytes(data[off : off + vsize])

    def test_it_waits_on_a_clock_rather_than_on_a_count_of_passes(self, image: bytearray) -> None:
        """`update` runs off whatever pump is turning, and while the store is up that is the modal
        `Sleep(5)` spin rather than the client frame - so a pass count would mean a different
        wall-clock wait at every frame rate."""
        text = _text(_patched(image))
        assert f"call dword ptr [0x{GET_TICK_COUNT:x}]" in text
        assert f"cmp eax, 0x{DEFER_MS:x}" in text

    def test_the_wait_is_unsigned_so_it_survives_the_tick_wrap(self, image: bytearray) -> None:
        """`GetTickCount` wraps every 49 days. An unsigned subtract and an unsigned compare give
        the right answer across it; `jl` would defer for a further 24 days."""
        text = _text(_patched(image))
        assert any(t.startswith("jb ") for t in text), "the compare is not unsigned"
        assert not any(t.startswith("jl ") for t in text)

    def test_the_stamp_is_written_by_the_reset_and_read_by_the_deferral(
        self, image: bytearray
    ) -> None:
        """One dword, one writer, one reader - and the reset is the writer because it is the only
        hook that runs exactly once per panel."""
        data = _patched(image)
        stamp = tick_stamp(_cave(data))
        text = _text(data)
        assert f"mov dword ptr [0x{stamp:x}], eax" in text, "the reset does not stamp the tick"
        assert f"sub eax, dword ptr [0x{stamp:x}]" in text, "the deferral does not read it"


class TestItComposesWithRenderRate:
    """The two used to be one patch; they now touch disjoint sites and must apply together."""

    def test_both_apply_and_verify(self) -> None:
        data = _sparse_image({**rrate.ANCHORS, **ANCHORS})
        RenderRatePatch(60).apply(data)
        SpellStoreDeferralPatch().apply(data)
        assert RenderRatePatch(60).verify(data) == []
        assert SpellStoreDeferralPatch().verify(data) == []

    def test_the_sites_are_disjoint(self) -> None:
        assert not set(rrate.ANCHORS) & set(ANCHORS)


class TestTheRealBinary:
    @staticmethod
    @pytest.fixture(scope="class")
    def game_dat() -> bytes:
        if not _GAME_DAT.exists():
            pytest.skip(f"no {_GAME_DAT}")
        return _GAME_DAT.read_bytes()

    def test_every_anchor_holds_what_the_patch_says_it_holds(self, game_dat: bytes) -> None:
        for va, expected in sorted(ANCHORS.items()):
            assert at(game_dat, va, len(expected)) == expected, f"0x{va:08X}"

    def test_apply_and_verify_on_the_real_thing(self, game_dat: bytes, tmp_path: Path) -> None:
        src = tmp_path / "game.dat"
        src.write_bytes(game_dat)
        out = apply_patches(src, [SpellStoreDeferralPatch()], tmp_path / "out.dat")
        assert SpellStoreDeferralPatch().verify(out.read_bytes()) == []
        assert src.read_bytes() == game_dat, "the input was modified"
