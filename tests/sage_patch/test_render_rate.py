"""Tests for `render-rate`, which draws at N frames per second without the simulation speeding up.

Almost everything this patch can get wrong is **silent**. It writes seven immediates and a dword,
and a wrong one does not crash: it makes the game run at a slightly different speed, which is the
one failure nobody notices and everybody blames on something else. Four kinds of silence are
checked separately.

**The arithmetic.** `ratio`, the timecode stride, the latch divisor and the four derived floats
are all functions of `fps`, and each is checked at the value where it stops being obvious rather
than only at 60 - the floats against the bytes the *compiler* emitted at 30, which is the one
place the patch's derivation can be checked against something it did not produce itself.

**The identity at 30.** Every site is written so that computing it for the stock rate reproduces
the stock bytes. That is not decoration: it is what makes the whole edit set checkable, and
`TestTheStockRateIsAnIdentity` is where it is actually checked, one site at a time.

**The cave's shape.** The two routines in `.fxrate` are the only assembly here, and every one of
their three exits is an address the patch does not own. A jump landing one byte off is a crash, so
the disassembly is read back and each target compared against the engine address it is meant to be.

**The Edain-only anchor.** The latch divisor this patch writes does not exist on stock SAGE, where
the same instruction divides by the logic rate. Writing a dword into whatever lives at
`0x00ECA400` on such a build is the worst thing here, so the refusal is checked directly.
"""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

from sage_patch import apply_patches
from sage_patch.patches.experimental.render_rate import (
    ANCHORS,
    CLIENT_RATE,
    DEFER_MS,
    GAME_CLIENT,
    GET_TICK_COUNT,
    GPU_CLOCK_STOCK,
    GPU_CLOCKS,
    IMM8,
    LATCH_DIVISOR,
    LOGIC_RATE,
    MAX_FPS,
    MIN_FPS,
    PARTICLE_GATE,
    PARTICLE_GATE_RESUME,
    PARTICLE_GATE_RUN,
    PARTICLE_GATE_STOCK,
    PREDICATE,
    RECOMPUTE_GATE,
    SECTION_NAME,
    STATE_RESET,
    STATE_RESET_RESUME,
    STATE_RESET_STOCK,
    STOCK_CLIENT_RATE,
    STOCK_LOGIC_RATE,
    STORE_STATES,
    STORE_STATES_END,
    STRIDES,
    UPDATE_LOOP,
    UPDATE_LOOP_DONE,
    UPDATE_LOOP_STOCK,
    UPDATE_LOOP_TOP,
    WRAP,
    RenderRatePatch,
    cave_code,
    defer_entry,
    derived_floats,
    gpu_clock_bytes,
    latch_divisor,
    state_reset_entry,
    tick_stamp,
)
from sage_patch.utils import find_section, va_to_offset

from .synthetic import render_rate_image

# The repo-root `game.dat`, not the install and not `game.dat.backup`. The install is whatever was
# last deployed to it - once a 60 fps build is in place it holds none of these anchors - and the
# backup is the *stock*-shaped binary, where the latch predicate divides by the logic rate and
# `0x00ECA400` does not exist at all. This patch targets the Edain shape (doc §0), and the
# repo-root copy is the unpatched one of those.
_GAME_DAT = Path(__file__).resolve().parents[2] / "game.dat"


def at(data: bytes | bytearray, va: int, length: int) -> bytes:
    off = va_to_offset(data, va)
    assert off is not None, f"0x{va:08x} is not mapped"
    return bytes(data[off : off + length])


def i32(data: bytes | bytearray, va: int) -> int:
    return int(struct.unpack("<i", at(data, va, 4))[0])


def _characteristics(data: bytes | bytearray, name: str) -> int:
    """The `Characteristics` dword of a named section, read straight out of the section table -
    `Section` does not carry it, and what a cave is allowed to do is worth asserting."""
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
    return render_rate_image()


def _patched(image: bytearray, fps: int = 60) -> bytearray:
    data = bytearray(image)
    RenderRatePatch(fps).apply(data)
    return data


class TestRoundTrip:
    def test_apply_then_verify(self, image: bytearray) -> None:
        assert RenderRatePatch(60).verify(_patched(image)) == []

    @pytest.mark.parametrize("fps", [35, 60, 120, 300, MAX_FPS])
    def test_every_supported_rate_applies_and_verifies(self, image: bytearray, fps: int) -> None:
        assert RenderRatePatch(fps).verify(_patched(image, fps)) == []

    def test_verify_rejects_an_unpatched_image(self, image: bytearray) -> None:
        problems = RenderRatePatch(60).verify(image)
        assert problems and SECTION_NAME in problems[0]

    def test_verify_rejects_the_wrong_rate(self, image: bytearray) -> None:
        """The failure this patch is most likely to meet in the wild: a binary that carries the
        patch, at a rate that is not the one being asked about."""
        problems = RenderRatePatch(120).verify(_patched(image, 60))
        assert problems and "rate" in problems[0]

    def test_detect_recovers_the_rate(self, image: bytearray) -> None:
        for fps in (35, 60, 300):
            found = RenderRatePatch.detect(_patched(image, fps))
            assert found is not None and found.fps == fps

    def test_detect_says_no_on_an_unpatched_image(self, image: bytearray) -> None:
        assert RenderRatePatch.detect(image) is None

    def test_apply_is_idempotent_only_in_the_sense_that_it_refuses(self, image: bytearray) -> None:
        """Applying twice must raise rather than write a second cave over a rate that has already
        moved - the stock bytes are gone, and `apply_byte_patch` is what notices."""
        data = _patched(image)
        with pytest.raises(ValueError):
            RenderRatePatch(60).apply(data)


class TestParameterValidation:
    @pytest.mark.parametrize("fps", [0, 30, MIN_FPS - 5, MAX_FPS + 5, 1000])
    def test_rejects_rates_outside_the_supported_range(self, fps: int) -> None:
        with pytest.raises(ValueError):
            RenderRatePatch(fps)

    @pytest.mark.parametrize("fps", [37, 61, 121])
    def test_rejects_rates_that_are_not_a_multiple_of_the_logic_rate(self, fps: int) -> None:
        """`ratio = fps / 5` is written as an integer immediate, so a rate that does not divide
        would silently round the wrap and drift the simulation against the frame counter."""
        with pytest.raises(ValueError):
            RenderRatePatch(fps)

    def test_the_default_is_60(self) -> None:
        assert RenderRatePatch().fps == 60

    def test_the_floor_is_where_the_stride_stops_being_stock(self) -> None:
        """`MIN_FPS` is 35 rather than 30 because at the stock ratio every site recomputes its own
        stock bytes - there would be nothing to write."""
        assert MIN_FPS == STOCK_CLIENT_RATE + STOCK_LOGIC_RATE

    def test_the_ceiling_is_the_imm8_bound(self) -> None:
        """The ratio and the stride are signed `imm8`s, so 127 is the largest either can hold -
        and the next supported rate up would need the sites re-encoded as imm32."""
        assert RenderRatePatch(MAX_FPS).ratio == 127
        with pytest.raises(ValueError):
            RenderRatePatch(MAX_FPS + STOCK_LOGIC_RATE)


class TestArithmetic:
    @pytest.mark.parametrize(
        ("fps", "expected"), [(30, 6), (35, 7), (60, 12), (120, 24), (MAX_FPS, 127)]
    )
    def test_the_ratio_is_the_client_rate_over_the_logic_rate(self, fps: int, expected: int):
        if fps == STOCK_CLIENT_RATE:
            assert ANCHORS[WRAP][IMM8] == expected  # the literal the patch replaces
        else:
            assert RenderRatePatch(fps).ratio == expected

    def test_the_derived_floats_reproduce_the_compiler_at_the_stock_rate(self) -> None:
        """The one check in this file against bytes the patch did not produce. Each constant is
        folded in **double** and narrowed to float32, which is what the compiler did; the setter's
        own `mulss` against `0.001f` would put `client/1000` one ulp away."""
        for va, expected in derived_floats(STOCK_CLIENT_RATE).items():
            assert expected == ANCHORS[va], f"0x{va:08X} does not rederive its stock bytes"

    def test_client_over_1000_is_the_folded_double_not_the_single(self) -> None:
        """The one ulp that says the derivation copies the **compiler** rather than the dead
        setter. `0x00D9F624` ships as `float(30 * 0.001)` folded in double; the setter's `mulss`
        against a `float` 0.001 lands one ulp higher, and would verify against nothing."""
        as_double = struct.pack("<f", STOCK_CLIENT_RATE * 0.001)
        one_ulp_up = struct.pack("<I", struct.unpack("<I", as_double)[0] + 1)
        assert derived_floats(STOCK_CLIENT_RATE)[0x00D9F624] == as_double
        assert ANCHORS[0x00D9F624] == as_double
        assert one_ulp_up != as_double  # the value the single-precision route would have given

    @pytest.mark.parametrize(("fps", "expected"), [(30, 8), (60, 20), (35, 11), (120, 40)])
    def test_the_latch_divisor_keeps_the_quotient_at_three(self, fps: int, expected: int) -> None:
        """The predicate answers ``subFrame == 6 / (clientRate / divisor)``, and the answer has to
        stay on sub-frame **2**: sub-frame 1 is never observable on this build, because the wrap
        sets the counter to 1 and the always-running catch-up loop bumps it to 2 inside the same
        logic step. Holding the quotient at 3 is what keeps the answer there."""
        assert latch_divisor(fps) == expected
        assert fps // latch_divisor(fps) == 3
        assert 6 // (fps // latch_divisor(fps)) == 2

    def test_the_stock_divisor_is_left_alone_at_the_stock_rate(self) -> None:
        assert latch_divisor(STOCK_CLIENT_RATE) == 8

    @pytest.mark.parametrize(("fps", "expected"), [(30, 10), (60, 12), (35, 10), (300, 60)])
    def test_the_stride_never_falls_below_its_stock_ten(self, fps: int, expected: int) -> None:
        assert max(10, fps // STOCK_LOGIC_RATE) == expected


class TestTheStockRateIsAnIdentity:
    """**Every site computes its own stock bytes at 30.**

    This is the property that makes the edit set checkable at all: each site is written as a
    function of the rate, and the function is confirmed against what the build already holds
    rather than against a second copy of the answer. A constant that only ever appears on the
    "new" side of an edit has nothing checking it.
    """

    def test_the_wrap_and_the_gate_hold_the_literal_six(self) -> None:
        assert ANCHORS[WRAP][IMM8] == STOCK_CLIENT_RATE // STOCK_LOGIC_RATE == 6
        assert ANCHORS[RECOMPUTE_GATE][IMM8] == 6

    def test_the_strides_hold_the_literal_ten(self) -> None:
        for va in STRIDES:
            assert ANCHORS[va][IMM8] == max(10, STOCK_CLIENT_RATE // STOCK_LOGIC_RATE)

    def test_the_rates_are_five_and_thirty(self) -> None:
        assert ANCHORS[LOGIC_RATE] == struct.pack("<i", STOCK_LOGIC_RATE)
        assert ANCHORS[CLIENT_RATE] == struct.pack("<i", STOCK_CLIENT_RATE)

    def test_the_cave_divides_the_authored_rate_by_the_live_one(self) -> None:
        """`clientFrame * 30 / clientRate` is an identity at 30, which is what makes the cave safe
        to lay over a binary whose rate has not moved - and what makes 0.500 the right answer at
        60 rather than a number chosen to match an observation."""
        for fps, expected in ((30, 1.0), (60, 0.5), (120, 0.25), (90, 1 / 3)):
            assert STOCK_CLIENT_RATE / fps == pytest.approx(expected)


class TestTheGateAndTheWrapAgree:
    """**The recompute gate must hold the same number as the wrap**, at every rate.

    `docs/render-rate.md` §9.10. The alpha is `subFrame / [TheGameEngine+0x38]`, and the recompute
    at `0x0063260F` is what puts `clientRate / logicRate` in that field. It fires only on the
    sub-frame index the gate names, so the gate has to name one that occurs - which means the
    sub-frame the wrap ends on, exactly as stock does with 6 and 6.

    The patch shipped this gate as a literal **1** for a while, on the reasoning that sub-frame 1
    always occurs. It never occurs: the catch-up loop at `0x00632A9B` steps past it inside the same
    logic step, which is the same thing §9.2 had already found out about the latch predicate. The
    recompute then never ran, `+0x38` was left to `0x006323D2`'s one-way `inc` - a site reachable
    only on a networked peer - and it ratcheted upward all match. Measured on both sides of one
    live match: 14 on the host and 31 on the off-host against a wrap of 12, which is a 4x and a 20x
    velocity spike at the logic-frame boundary where a correct build is 2x at any rate.

    Single-player cannot see any of this, which is why it survived §9.1 through §9.7. These tests
    are the cheap thing that would have.
    """

    @pytest.mark.parametrize("fps", [35, 60, 120, 300, MAX_FPS])
    def test_the_gate_holds_the_same_byte_as_the_wrap(self, image: bytearray, fps: int) -> None:
        data = _patched(image, fps)
        wrap = at(data, WRAP + IMM8, 1)[0]
        gate = at(data, RECOMPUTE_GATE + IMM8, 1)[0]
        assert gate == wrap, f"at {fps} fps the gate is {gate} and the wrap is {wrap}"

    @pytest.mark.parametrize("fps", [35, 60, 120, 300, MAX_FPS])
    def test_the_gate_holds_the_ratio(self, image: bytearray, fps: int) -> None:
        assert at(_patched(image, fps), RECOMPUTE_GATE + IMM8, 1)[0] == RenderRatePatch(fps).ratio

    def test_the_gate_is_never_one(self, image: bytearray) -> None:
        """The specific wrong answer, named so a regression says why it is wrong rather than only
        that a number changed. Sub-frame 1 is not observable on this binary."""
        for fps in (35, 60, 120, 300, MAX_FPS):
            assert at(_patched(image, fps), RECOMPUTE_GATE + IMM8, 1)[0] != 1

    def test_at_the_stock_rate_both_recompute_the_stock_byte(self, image: bytearray) -> None:
        """The identity `TestTheStockRateIsAnIdentity` documents, extended to the gate: 30 fps
        would write 6 into both, which is what the unpatched build already holds. A gate that did
        not have this property would be writing a constant rather than deriving one."""
        assert STOCK_CLIENT_RATE // STOCK_LOGIC_RATE == ANCHORS[RECOMPUTE_GATE][IMM8] == 6


class TestTheAnchorsAgreeWithTheEdits:
    """The stock constants are written down twice - in `ANCHORS`, which the stand-in is built
    from, and on the "old" side of every edit. Two copies that agreed with each other but not with
    the binary would pass every other test in this file, so they are compared here."""

    def test_every_edit_reads_its_old_side_out_of_the_anchor_table(self, image: bytearray) -> None:
        patch = RenderRatePatch(60)
        edits = patch._edits(image, 0x00F00000)
        assert edits, "no edits recovered"
        for file_off, old, _new, note in edits:
            found = bytes(image[file_off : file_off + len(old)])
            assert found == old, f"{note}: stand-in holds {found.hex()}, edit expects {old.hex()}"

    def test_the_anchor_table_covers_every_site_the_patch_writes(self, image: bytearray) -> None:
        """A site edited but not anchored would not exist in the stand-in, so every test here
        would be exercising zeroes."""
        written = {
            CLIENT_RATE,
            LATCH_DIVISOR,
            PARTICLE_GATE,
            WRAP,
            RECOMPUTE_GATE,
            *STRIDES,
            *GPU_CLOCKS,
            *derived_floats(60),
        }
        assert written <= set(ANCHORS), sorted(hex(va) for va in written - set(ANCHORS))


class TestTheParticleCave:
    """§9.4's fix, and §9.6's beside it: the only assembly in this patch, and the only place a
    wrong byte crashes rather than merely running at the wrong speed."""

    @staticmethod
    def _disassembled(data: bytes | bytearray) -> list:
        capstone = pytest.importorskip("capstone")
        md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
        located = find_section(data, SECTION_NAME)
        assert located is not None
        section_va, off, vsize = located
        return list(md.disasm(bytes(data[off : off + vsize]), section_va))

    def test_the_hook_is_a_near_jump_padded_to_the_whole_window(self, image: bytearray) -> None:
        data = _patched(image)
        located = find_section(data, SECTION_NAME)
        assert located is not None
        window = at(data, PARTICLE_GATE, len(PARTICLE_GATE_STOCK))
        assert window[0] == 0xE9
        target = PARTICLE_GATE + 5 + struct.unpack("<i", window[1:5])[0]
        assert target == located[0], "the hook does not land on the cave"
        assert set(window[5:]) == {0x90}, "the rest of the window is not nop"

    def test_both_exits_land_on_the_engine_addresses_they_name(self, image: bytearray) -> None:
        """The five jumps out. `PARTICLE_GATE_RESUME` is the engine's own compare-and-store,
        which the cave deliberately does not reimplement; `PARTICLE_GATE_RUN` is the update body,
        taken when there is no `TheGameClient` to ask; `STATE_RESET_RESUME` is the spell store
        handler's own `ret 4`."""
        jumps = [i for i in self._disassembled(_patched(image)) if i.mnemonic == "jmp"]
        assert [int(i.op_str, 16) for i in jumps] == [
            PARTICLE_GATE_RESUME,
            PARTICLE_GATE_RUN,
            STATE_RESET_RESUME,
            UPDATE_LOOP_TOP,
            UPDATE_LOOP_DONE,
        ]

    def test_the_cave_multiplies_by_the_authored_rate_and_divides_by_the_live_one(
        self, image: bytearray
    ) -> None:
        """The whole fix, as two instructions. The 30 is folded in because it is what the content
        was authored at; the divisor is *read* so that it cannot drift from the rate this patch
        writes four bytes away."""
        text = [f"{i.mnemonic} {i.op_str}" for i in self._disassembled(_patched(image))]
        assert f"imul eax, eax, 0x{STOCK_CLIENT_RATE:x}" in text
        assert f"div dword ptr [0x{CLIENT_RATE:x}]" in text
        assert "xor edx, edx" in text, "div without clearing edx divides by a garbage high word"

    def test_the_cave_asks_the_game_client_the_way_the_displaced_code_did(
        self, image: bytearray
    ) -> None:
        text = [f"{i.mnemonic} {i.op_str}" for i in self._disassembled(_patched(image))]
        assert f"mov ecx, dword ptr [0x{GAME_CLIENT:x}]" in text
        assert "call dword ptr [eax + 0x7c]" in text

    def test_the_cave_is_the_same_at_every_rate(self, image: bytearray) -> None:
        """It reads the rate rather than folding it in, so one cave serves every N - which is also
        why `verify` can recompute it from the section base alone."""
        caves = []
        for fps in (35, 60, 120):
            data = _patched(image, fps)
            located = find_section(data, SECTION_NAME)
            assert located is not None
            caves.append(bytes(data[located[1] : located[1] + located[2]]))
        assert caves[0] == caves[1] == caves[2]
        assert caves[0] == cave_code(
            find_section(_patched(image), SECTION_NAME)[0]  # type: ignore[index]
        )

    def test_the_section_is_executable_and_writable_for_the_stamp(self, image: bytearray) -> None:
        """The particle gate needs no writable storage, but §9.6's deferral does: it stamps the
        millisecond the spell store initialised at and reads it back every update. Four bytes of
        run-time state is the whole reason this section is writable, and the stamp ships zeroed."""
        data = _patched(image)
        flags = _characteristics(data, SECTION_NAME)
        assert flags & 0x20000000, "the cave is not executable"
        assert flags & 0x40000000, "the cave is not readable"
        assert flags & 0x80000000, "the tick stamp cannot be written"
        located = find_section(data, SECTION_NAME)
        assert located is not None
        assert at(data, tick_stamp(located[0]), 4) == bytes(4)


class TestTheStateResetCave:
    """§9.6's fix: re-send the spell store's button states once the movie is built.

    The engine sends a button's state only when it differs from the value cached at
    `this+0x2AC`, and writes that cache whether or not the movie took the message - so a state
    the movie refused is never repeated and the spellbook shows nothing purchasable. This cave
    hangs off `AptSpellStore::OnInitialized` and stamps every slot with a value no computed
    state can equal, which makes the next `update` re-send all twenty.
    """

    @staticmethod
    def _text(data: bytes | bytearray) -> list[str]:
        capstone = pytest.importorskip("capstone")
        md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
        located = find_section(data, SECTION_NAME)
        assert located is not None
        section_va, off, vsize = located
        return [
            f"{i.mnemonic} {i.op_str}"
            for i in md.disasm(bytes(data[off : off + vsize]), section_va)
        ]

    def test_the_hook_is_a_near_jump_padded_to_the_whole_window(self, image: bytearray) -> None:
        data = _patched(image)
        located = find_section(data, SECTION_NAME)
        assert located is not None
        window = at(data, STATE_RESET, len(STATE_RESET_STOCK))
        assert window[0] == 0xE9
        target = STATE_RESET + 5 + struct.unpack("<i", window[1:5])[0]
        assert target == state_reset_entry(located[0]), "the hook does not land on the routine"
        assert set(window[5:]) == {0x90}, "the rest of the window is not nop"

    def test_the_displaced_store_is_carried_into_the_cave(self, image: bytearray) -> None:
        """The window taken over is `mov byte [ecx+0x2A0], 1` - the flag that tells `update` the
        panel is open. Losing it would leave the store shut and `update` returning immediately,
        which looks exactly like the bug this is fixing."""
        data = _patched(image)
        located = find_section(data, SECTION_NAME)
        assert located is not None
        entry = state_reset_entry(located[0])
        assert at(data, entry, len(STATE_RESET_STOCK)) == STATE_RESET_STOCK

    def test_the_loop_covers_exactly_the_twenty_state_slots(self, image: bytearray) -> None:
        """The bounds are the two `lea`s, and the stride is the 8 that steps over each button
        pointer. Twenty is the count `update` itself iterates (`cmp [ebp-0x14], 0x14`), and a
        bound one pair too far would stamp `+0x34C`, a real field the handler resets to -1."""
        text = self._text(_patched(image))
        assert f"lea edx, [ecx + 0x{STORE_STATES:x}]" in text
        assert f"lea ecx, [ecx + 0x{STORE_STATES_END:x}]" in text
        assert "add edx, 8" in text
        assert (STORE_STATES_END - STORE_STATES) % 8 == 0
        assert (STORE_STATES_END - STORE_STATES) // 8 == 20

    def test_the_sentinel_is_a_value_no_computed_state_can_equal(self, image: bytearray) -> None:
        """`update` computes 0..5 (the six labels at `0x00C50BF8`). The cache is only ever
        compared against that, never used to index it, so -1 is safe to park there and is what
        guarantees a mismatch on the next pass."""
        assert "or eax, 0xffffffff" in self._text(_patched(image))

    def test_it_writes_the_slots_and_not_the_button_pointers(self, image: bytearray) -> None:
        """`+0x2AC` is the state; `+0x2A8` is the `CommandButton` beside it. Starting the walk
        four bytes early would null every button and take the panel out entirely."""
        assert STORE_STATES - 4 == 0x2A8
        assert "mov dword ptr [edx], eax" in self._text(_patched(image))


class TestTheDeferral:
    """§9.6's other half, and the half that does the work: `update` sends nothing at all for the
    first `DEFER_MS` after the panel initialises, so that when the twenty sends do go out the
    movie has built its button clips and can accept them.

    Invalidating the cache without this is a no-op - `OnInitialized` is what sets `+0x2A0`, so the
    first update after it is the pass the original send was already happening on.
    """

    @staticmethod
    def _text(data: bytes | bytearray) -> list[str]:
        capstone = pytest.importorskip("capstone")
        md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
        located = find_section(data, SECTION_NAME)
        assert located is not None
        section_va, off, vsize = located
        return [
            f"{i.mnemonic} {i.op_str}"
            for i in md.disasm(bytes(data[off : off + vsize]), section_va)
        ]

    def test_the_hook_is_a_near_jump_padded_to_the_whole_window(self, image: bytearray) -> None:
        data = _patched(image)
        located = find_section(data, SECTION_NAME)
        assert located is not None
        window = at(data, UPDATE_LOOP, len(UPDATE_LOOP_STOCK))
        assert window[0] == 0xE9
        target = UPDATE_LOOP + 5 + struct.unpack("<i", window[1:5])[0]
        assert target == defer_entry(located[0]), "the hook does not land on the deferral"
        assert set(window[5:]) == {0x90}, "the rest of the window is not nop"

    def test_the_displaced_loop_setup_is_carried_into_the_cave(self, image: bytearray) -> None:
        """The window taken over is the loop's index and cursor. Dropping either walks the wrong
        memory twenty times, which is a crash rather than a wrong colour."""
        assert UPDATE_LOOP_STOCK in bytes(_patched(image))

    def test_it_waits_on_a_clock_rather_than_on_a_count_of_passes(self, image: bytearray) -> None:
        """`update` runs off whatever pump is turning, and while the store is up that is the modal
        `Sleep(5)` spin rather than the client frame - so a pass count would mean a different
        wall-clock wait at every rate, which is the exact class of bug this patch is about."""
        text = self._text(_patched(image))
        assert f"call dword ptr [0x{GET_TICK_COUNT:x}]" in text
        assert f"cmp eax, 0x{DEFER_MS:x}" in text

    def test_the_wait_is_unsigned_so_it_survives_the_tick_wrap(self, image: bytearray) -> None:
        """`GetTickCount` wraps every 49 days. An unsigned subtract and an unsigned compare give
        the right answer across it; `jl` would defer for a further 24 days."""
        text = self._text(_patched(image))
        assert any(t.startswith("jb ") for t in text), "the compare is not unsigned"
        assert not any(t.startswith("jl ") for t in text)

    def test_both_exits_are_the_loop_the_engine_already_has(self, image: bytearray) -> None:
        """Neither exit is invented: one is the loop body, the other is the `jmp` the loop itself
        takes once all twenty iterations are done, which is exactly what "not this pass" means."""
        text = self._text(_patched(image))
        assert f"jmp 0x{UPDATE_LOOP_TOP:x}" in text
        assert f"jmp 0x{UPDATE_LOOP_DONE:x}" in text

    def test_the_stamp_is_written_by_the_reset_and_read_by_the_deferral(
        self, image: bytearray
    ) -> None:
        """One dword, one writer, one reader - and the reset is the writer because it is the only
        hook that runs exactly once per panel."""
        data = _patched(image)
        located = find_section(data, SECTION_NAME)
        assert located is not None
        stamp = tick_stamp(located[0])
        text = self._text(data)
        assert f"mov dword ptr [0x{stamp:x}], eax" in text, "the reset does not stamp the tick"
        assert f"sub eax, dword ptr [0x{stamp:x}]" in text, "the deferral does not read it"
        assert stamp >= located[0] + len(cave_code(located[0])) - 4, "the stamp is inside the code"


class TestItRefusesTheWrongBuild:
    """The patch writes a dword to `0x00ECA400`, which on stock SAGE is not the latch divisor and
    may not be anything at all. Refusing is the whole safety property."""

    def test_it_refuses_a_build_whose_predicate_divides_by_the_logic_rate(
        self, image: bytearray
    ) -> None:
        stock_shape = ANCHORS[PREDICATE][:6] + bytes.fromhex("f73d08f6d900")  # idiv [logicRate]
        off = va_to_offset(image, PREDICATE)
        assert off is not None
        image[off : off + len(stock_shape)] = stock_shape
        with pytest.raises(ValueError, match="not the Edain build"):
            RenderRatePatch(60).apply(image)

    def test_it_refuses_a_build_whose_logic_rate_is_not_five(self, image: bytearray) -> None:
        off = va_to_offset(image, LOGIC_RATE)
        assert off is not None
        image[off : off + 4] = struct.pack("<i", 6)
        with pytest.raises(ValueError, match="logic rate"):
            RenderRatePatch(60).apply(image)

    @pytest.mark.parametrize("va", [PARTICLE_GATE_RESUME, PARTICLE_GATE_RUN])
    def test_it_refuses_when_a_cave_landing_has_moved(self, image: bytearray, va: int) -> None:
        """Neither exit is inside the window this patch rewrites, so nothing else would notice -
        and a cave jumping into the middle of another patch's edit is a crash."""
        off = va_to_offset(image, va)
        assert off is not None
        image[off] ^= 0xFF
        with pytest.raises(ValueError, match="landing"):
            RenderRatePatch(60).apply(image)


class TestTheGpuParticleClocks:
    """§9.11: the second particle clock, and the only edit here that is **not** a function of `fps`.

    A `Type = GPU_PARTICLE` system is never aged by the walk `PARTICLE_GATE` sits in front of, so
    §9.4's cave never reached it. The GPU storage module converts the W3D millisecond clock into
    frames itself, with the *live* client rate, at four sites - which is why the fix is four
    identical byte edits and no cave, and why it does not move when `fps` does.
    """

    def test_the_stock_bytes_are_a_multiply_by_the_live_rate(self) -> None:
        """`0F AF 05 <disp32>` is `imul eax, dword [disp32]`, and the operand must be the same
        client rate the rest of this patch rewrites - otherwise the site is not the one §9.11
        found."""
        assert GPU_CLOCK_STOCK == bytes((0x0F, 0xAF, 0x05)) + struct.pack("<I", CLIENT_RATE)

    def test_the_replacement_multiplies_by_the_authored_rate(self) -> None:
        """`6B C0 ib` is `imul eax, eax, imm8`. The immediate is the rate the content was authored
        at, not the rate the binary runs at."""
        assert gpu_clock_bytes()[:3] == bytes((0x6B, 0xC0, STOCK_CLIENT_RATE))

    def test_the_replacement_fills_the_window_it_shortens(self) -> None:
        """Three bytes for seven, `nop`-padded rather than moving anything after it - each site is
        followed by `test eax, eax`, which is also why the flags the two forms set differently do
        not matter."""
        patched = gpu_clock_bytes()
        assert len(patched) == len(GPU_CLOCK_STOCK)
        assert patched[3:] == b"\x90" * (len(GPU_CLOCK_STOCK) - 3)

    def test_there_are_four_distinct_sites(self) -> None:
        assert len(set(GPU_CLOCKS)) == len(GPU_CLOCKS) == 4

    @pytest.mark.parametrize("fps", [MIN_FPS, 60, 90, 120, MAX_FPS])
    def test_the_edit_is_the_same_at_every_rate(self, image: bytearray, fps: int) -> None:
        """The whole point of the fix. Every other edit in this patch is a function of `fps`; this
        one must not be, because the number it writes is what the *content* was authored against.
        A version of this that scaled with the rate would reintroduce the defect it removes."""
        data = _patched(image, fps)
        for va in GPU_CLOCKS:
            assert at(data, va, len(GPU_CLOCK_STOCK)) == gpu_clock_bytes(), f"0x{va:08X}"

    @pytest.mark.parametrize("fps", [30, 60, 90, 120])
    def test_the_fixed_clock_lands_on_the_authored_rate(self, fps: int) -> None:
        """What the edit buys, as arithmetic rather than as bytes.

        The W3D clock gains `1000 // fps` ms per client frame (`0x00BC146C`, truncated), so it
        gains `(1000 // fps) * fps` ms per real second. Multiplied by the authored 30 and scaled by
        0.001, the tick lands within 4% of 30 Hz at every client rate - the residual being that
        truncation, which this patch does not remove.
        """
        per_second = (1000 // fps) * fps
        assert per_second * STOCK_CLIENT_RATE / 1000 == pytest.approx(STOCK_CLIENT_RATE, rel=0.04)

    @pytest.mark.parametrize("fps", [30, 60, 90, 120])
    def test_the_stock_clock_tracks_the_client_rate_instead(self, fps: int) -> None:
        """And the defect, stated the same way: stock multiplies by the live rate, so the tick
        lands on the *client* rate. At 30 that is indistinguishable from correct, which is why
        this survived to be found at 60."""
        per_second = (1000 // fps) * fps
        assert per_second * fps / 1000 == pytest.approx(fps, rel=0.04)


class TestTheRealBinary:
    """The stand-in proves the patch is self-consistent; only a real `game.dat` proves the
    addresses are right. Skipped where there is none, which is every machine but the author's.

    It reads the repo-root copy rather than the install on purpose: the install holds whatever was
    last deployed to it, so the moment a patched build ships there these assertions would start
    failing on the patch's own success."""

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
        out = apply_patches(src, [RenderRatePatch(60)], tmp_path / "out.dat")
        data = out.read_bytes()
        assert RenderRatePatch(60).verify(data) == []
        assert i32(data, CLIENT_RATE) == 60
        assert i32(data, LOGIC_RATE) == STOCK_LOGIC_RATE
        assert i32(data, LATCH_DIVISOR) == 20
        assert src.read_bytes() == game_dat, "the input was modified"
