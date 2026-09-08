"""Tests for the interpolation-alpha patch.

The cave is hand-assembled SSE that cannot be executed here, so the important tests disassemble it
back and assert it says what it was meant to say. The failure mode this patch exists to remove is
invisible to the engine - a doubled interpolation step is a perfectly legal alpha - so a wrong byte
here would not raise anywhere either; it would just move things wrong on screen.

:class:`TestTheSweepIsEven` is the behavioural claim, as arithmetic: the whole point of
``(subFrame - 1) / (ratio - 1)`` is that the step across the logic-frame boundary is the same size
as every other step, and that stock's formula is not.
"""

from __future__ import annotations

import struct

import pytest

from sage_ini.engine import STOCK
from sage_patch.addresses import (
    ALPHA_RECOMPUTE_BODY,
    CATCHUP_ESCAPE,
    FLOAT_ONE,
    GAME_ENGINE_ALPHA,
    GAME_ENGINE_SUB_FRAME,
    GAME_ENGINE_SUB_FRAME_RATIO,
)
from sage_patch.patches.experimental import render_rate as rr
from sage_patch.patches.experimental.interpolation_alpha import (
    ANCHORS,
    HOOK_ORIGINAL,
    HOOK_VA,
    SECTION_NAME,
    InterpolationAlphaPatch,
    build_code,
)
from sage_patch.registry import PATCHES
from sage_patch.utils import find_section, va_to_offset

from .synthetic import IMAGE_BASE, interpolation_alpha_image

BASE = 0x00F00000


def disassemble(base: int = BASE):
    capstone = pytest.importorskip("capstone")
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    md.detail = True
    return list(md.disasm(build_code(base), base))


class TestTheSweepIsEven:
    """Why the formula is what it is. The catch-up loop consumes sub-frame 1, so the client only
    ever observes ``2..ratio`` - and an alpha is only smooth if consecutive observations are
    equally spaced *including across the boundary*, where the matrices roll over and the next
    alpha is measured against a fresh segment."""

    @staticmethod
    def steps(alphas: list[float]) -> list[float]:
        """The motion between consecutive rendered frames, the boundary one included. At the
        boundary `previous = current`, so the next frame's motion is the alpha itself."""
        return [alphas[i + 1] - alphas[i] for i in range(len(alphas) - 1)] + [alphas[0]]

    @pytest.mark.parametrize("ratio", [6, 12, 5, 24])
    def test_the_boundary_step_matches_every_other_step(self, ratio: int):
        observed = range(2, ratio + 1)
        alphas = [(sub - 1) / (ratio - 1) for sub in observed]
        steps = self.steps(alphas)
        assert alphas[-1] == pytest.approx(1.0), "the sweep must still end on the current transform"
        assert steps == pytest.approx([steps[0]] * len(steps))

    @pytest.mark.parametrize("ratio", [6, 12])
    def test_the_stock_formula_doubles_the_boundary_step(self, ratio: int):
        """The defect, stated as a number: `subFrame / ratio` over the same observed range."""
        alphas = [sub / ratio for sub in range(2, ratio + 1)]
        steps = self.steps(alphas)
        assert steps[-1] == pytest.approx(2 * steps[0])

    def test_it_would_stall_the_boundary_on_a_stock_catch_up_loop(self):
        """Why `_check_anchors` refuses one. With sub-frame 1 observable the range is `1..ratio`,
        and this formula puts a zero-length step at the boundary - the same defect, sign flipped,
        which is what makes the anchor load-bearing rather than cautious."""
        ratio = 6
        alphas = [(sub - 1) / (ratio - 1) for sub in range(1, ratio + 1)]
        assert self.steps(alphas)[-1] == pytest.approx(0.0)


class TestTheCave:
    def test_it_disassembles_cleanly_to_its_end(self):
        """Capstone stopping early means an invalid encoding, which would be a crash in-game."""
        insns = disassemble()
        assert sum(i.size for i in insns) == len(build_code(BASE))

    def test_it_reproduces_the_instruction_the_hook_displaced(self):
        """The cave *is* the routine now, so the `cvtsi2ss` the five-byte jmp overwrote has to be
        the first thing it does - and byte-for-byte, since that is what the hook asserted."""
        assert build_code(BASE)[: len(HOOK_ORIGINAL)] == HOOK_ORIGINAL
        first = disassemble()[0]
        assert first.mnemonic == "cvtsi2ss"
        assert first.op_str == f"xmm1, dword ptr [ecx + {GAME_ENGINE_SUB_FRAME_RATIO:#x}]"

    def test_both_operands_lose_one_before_the_divide(self):
        """The correction, and the asymmetry that would be the bug: subtracting from only the
        numerator, or only the denominator, skews the sweep instead of evening it."""
        insns = disassemble()
        subs = [i for i in insns if i.mnemonic == "subss"]
        assert len(subs) == 2
        assert all(f"[{FLOAT_ONE:#x}]" in i.op_str for i in subs)
        assert {i.op_str.split(",")[0] for i in subs} == {"xmm1", "xmm0"}
        divide = next(i for i in insns if i.mnemonic == "divss")
        assert all(sub.address < divide.address for sub in subs)

    def test_it_divides_the_sub_frame_by_the_ratio_and_not_the_other_way(self):
        insns = disassemble()
        numerator = next(
            i
            for i in insns
            if i.mnemonic == "cvtsi2ss" and f"[ecx + {GAME_ENGINE_SUB_FRAME:#x}]" in i.op_str
        )
        assert numerator.op_str.startswith("xmm0")
        assert next(i for i in insns if i.mnemonic == "divss").op_str == "xmm0, xmm1"

    def test_a_ratio_of_one_takes_the_no_span_arm_and_writes_one(self):
        """`+0x38` is 1 from the constructor until the first recompute, so `ratio - 1` really is
        zero for the opening window of a match. `jbe` covers less-than, equal and unordered."""
        insns = disassemble()
        compare = next(i for i in insns if i.mnemonic == "comiss")
        assert compare.op_str == "xmm1, xmm0"  # (ratio - 1) against a zeroed xmm0
        taken = next(i for i in insns if i.mnemonic == "jbe")
        arm = next(i for i in insns if i.address == int(taken.op_str, 16))
        assert (arm.mnemonic, arm.op_str) == ("movss", f"xmm0, dword ptr [{FLOAT_ONE:#x}]")

    def test_every_exit_stores_to_the_alpha_field_and_returns(self):
        insns = disassemble()
        stores = [i for i in insns if i.mnemonic == "movss" and i.op_str.endswith("xmm0")]
        assert len(stores) == 2, "one store on each arm"
        for store in stores:
            assert store.op_str == f"dword ptr [ecx + {GAME_ENGINE_ALPHA:#x}], xmm0"
            after = next(i for i in insns if i.address == store.address + store.size)
            assert after.mnemonic == "ret"
        assert sum(1 for i in insns if i.mnemonic == "ret") == 2

    def test_it_keeps_the_two_sided_clamp(self):
        """The displaced routine clamps into [0, 1] and the ratchet at `0x006323D2` can still
        drive `+0x38` past the wrap on a networked peer, so dropping the clamp would let the alpha
        out of range where stock would not."""
        insns = disassemble()
        assert any(i.mnemonic == "maxss" for i in insns)
        assert any(i.mnemonic == "minss" for i in insns)

    def test_it_clobbers_no_more_registers_than_the_routine_it_replaces(self):
        """Callers are entitled to assume whatever the stock routine preserved. It touches xmm0
        and xmm1 and reads ecx; anything wider here would be a silent corruption at four call
        sites."""
        for ins in disassemble():
            for register in ("xmm2", "xmm3", "xmm4", "xmm5", "xmm6", "xmm7"):
                assert register not in ins.op_str, f"{ins.mnemonic} touches {register}"
            assert "esp" not in ins.op_str and "ebp" not in ins.op_str

    def test_every_conditional_branch_stays_inside_the_cave(self):
        code = build_code(BASE)
        lo, hi = BASE, BASE + len(code)
        for ins in disassemble():
            if not ins.mnemonic.startswith("j"):
                continue
            assert lo <= int(ins.op_str, 16) < hi, f"{ins.mnemonic} at {ins.address:#x} escapes"

    def test_it_never_branches_back_into_the_engine(self):
        """Unlike most caves here this one owns a whole function and returns, so a `jmp` or `call`
        out of it would be reaching into a routine it has replaced."""
        assert not [i for i in disassemble() if i.mnemonic == "call"]

    def test_it_relocates_with_its_section(self):
        a, b = build_code(BASE), build_code(BASE + 0x1000)
        assert len(a) == len(b)
        # only the rel32 of the internal `jbe` is position-relative, and it is not - the absolute
        # float references are, and they must not move
        assert a == b, "the cave holds no address that depends on where it lands"


class TestApply:
    def test_apply_then_verify(self):
        data = interpolation_alpha_image()
        InterpolationAlphaPatch().apply(data)
        assert InterpolationAlphaPatch().verify(data) == []

    def test_the_hook_is_a_five_byte_jmp_to_the_cave(self):
        data = interpolation_alpha_image()
        InterpolationAlphaPatch().apply(data)
        section_va, _off, _vsize = find_section(data, SECTION_NAME)
        off = va_to_offset(data, HOOK_VA)
        site = bytes(data[off : off + len(HOOK_ORIGINAL)])
        assert site[0] == 0xE9
        assert HOOK_VA + 5 + struct.unpack_from("<i", site, 1)[0] == section_va
        assert len(HOOK_ORIGINAL) == 5, "the displaced instruction is exactly a jmp rel32 wide"

    def test_the_cave_holds_the_expected_code(self):
        data = interpolation_alpha_image()
        InterpolationAlphaPatch().apply(data)
        section_va, off, _vsize = find_section(data, SECTION_NAME)
        assert bytes(data[off : off + len(build_code(section_va))]) == build_code(section_va)

    def test_detect_finds_it(self):
        data = interpolation_alpha_image()
        assert InterpolationAlphaPatch.detect(data) is None
        InterpolationAlphaPatch().apply(data)
        found = InterpolationAlphaPatch.detect(data)
        assert found is not None and found.name == InterpolationAlphaPatch.name

    def test_refuses_to_apply_twice(self):
        data = interpolation_alpha_image()
        InterpolationAlphaPatch().apply(data)
        with pytest.raises(ValueError, match="expected"):
            InterpolationAlphaPatch().apply(data)

    def test_it_refuses_a_stock_catch_up_loop(self):
        """The premise, enforced. On a binary whose escape still skips the loop, sub-frame 1 is
        observable and this correction would be wrong in the other direction."""
        data = interpolation_alpha_image()
        off = va_to_offset(data, CATCHUP_ESCAPE)
        data[off : off + 7] = bytes.fromhex("f73d08f6d9008bc8")[:7]  # idiv [logicRate] / mov ecx
        with pytest.raises(ValueError, match="catch-up loop always runs"):
            InterpolationAlphaPatch().apply(data)

    def test_it_refuses_a_build_that_computes_the_alpha_differently(self):
        data = interpolation_alpha_image()
        off = va_to_offset(data, ALPHA_RECOMPUTE_BODY)
        data[off : off + 4] = b"\x90\x90\x90\x90"
        with pytest.raises(ValueError, match="expected"):
            InterpolationAlphaPatch().apply(data)

    def test_it_refuses_a_build_whose_one_is_not_one(self):
        """The cave subtracts and clamps against that constant by address, so a build where it
        holds something else would silently compute a different curve."""
        data = interpolation_alpha_image()
        off = va_to_offset(data, FLOAT_ONE)
        struct.pack_into("<f", data, off, 2.0)
        with pytest.raises(ValueError, match="expected"):
            InterpolationAlphaPatch().apply(data)

    def test_it_leaves_the_catch_up_loop_alone(self):
        """The alternative fix, not taken: reverting the escape would remove the jitter by
        removing the delay fix with it."""
        before = interpolation_alpha_image()
        data = interpolation_alpha_image()
        InterpolationAlphaPatch().apply(data)
        off = va_to_offset(data, CATCHUP_ESCAPE)
        assert data[off : off + 7] == before[off : off + 7]


class TestRegistration:
    def test_it_is_offered_on_the_cli(self):
        assert PATCHES[InterpolationAlphaPatch.name] is InterpolationAlphaPatch

    def test_it_is_declared_experimental(self):
        assert InterpolationAlphaPatch.experimental is True

    def test_it_changes_no_ini(self):
        assert InterpolationAlphaPatch().ini_surface() is STOCK

    def test_it_composes_with_render_rate(self):
        """The composition claim in the module docstring, as an assertion. `render-rate` rewrites
        the wrap, the recompute gate and the latch divisor; this patch edits one routine neither
        of those is in, and reads `+0x38` at run time rather than any byte `render-rate` writes."""
        mine = set(range(HOOK_VA, HOOK_VA + len(HOOK_ORIGINAL)))
        theirs = set()
        for va, stock in rr.ANCHORS.items():
            theirs |= set(range(va, va + len(stock)))
        assert not mine & theirs
        for va, expected in ANCHORS.items():
            assert not set(range(va, va + len(expected))) & mine
        assert rr.LATCH_DIVISOR not in mine
        assert rr.WRAP not in mine and rr.RECOMPUTE_GATE not in mine


class TestTheSyntheticImage:
    def test_it_plants_the_routine_the_patch_replaces(self):
        data = interpolation_alpha_image()
        off = va_to_offset(data, HOOK_VA)
        assert bytes(data[off : off + len(HOOK_ORIGINAL)]) == HOOK_ORIGINAL

    def test_everything_not_planted_reads_as_zero(self):
        """What makes the image negative as well: a patch that looked one dword to either side of
        the float constant would find 0.0 there, not 1.0."""
        data = interpolation_alpha_image()
        off = va_to_offset(data, FLOAT_ONE)
        assert bytes(data[off : off + 4]) == struct.pack("<f", 1.0)
        assert bytes(data[off + 4 : off + 8]) == bytes(4)
        assert IMAGE_BASE == 0x400000
