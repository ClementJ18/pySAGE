"""Tests for the construction-initial-health patch.

The cave is hand-assembled x87/SSE that cannot be executed here, so the tests come in two halves.
:class:`TestTheCurve` is the behavioural claim written as arithmetic - what the three edits
together are supposed to make the health-to-progress relation be, and what each one alone would
get wrong. :class:`TestTheCave` disassembles the emitted bytes back and asserts they say that.

The failure mode this patch could introduce is quiet in exactly the way the interpolation-alpha
one is: a structure that finishes at 95% health, or a progress bar that reads ten points high,
is a legal number everywhere in the engine. Nothing would raise; it would just be wrong.
"""

from __future__ import annotations

import struct

import pytest

from sage_ini.engine import STOCK
from sage_patch.addresses import (
    ACTIVE_BODY_INTERNAL_CHANGE_HEALTH_SLOT,
    BODY_GET_HEALTH_RATIO_SLOT,
    BODY_GET_MAX_HEALTH_SLOT,
    CONSTRUCTION_INITIAL_HEALTH_CALLS,
    CONSTRUCTION_PERCENT_FROM_RATIO,
    CONSTRUCTION_RAMP_HEALTH_STEP,
    SELF_BUILD_HEAL_STEP,
)
from sage_patch.patches import production_split as ps
from sage_patch.patches.construction_initial_health import (
    _HOOKS,
    _ROUTINES,
    ANCHORS,
    DEFAULT_PERCENT,
    MAX_PERCENT,
    SECTION_NAME,
    ConstructionInitialHealthPatch,
    _routine_addresses,
    build_code,
)
from sage_patch.registry import PATCHES
from sage_patch.utils import find_section, va_to_offset

from .synthetic import construction_initial_health_image

BASE = 0x00F00000


def disassemble(base: int = BASE, percent: float = DEFAULT_PERCENT):
    """The cave's code, without the five constants it opens with."""
    capstone = pytest.importorskip("capstone")
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    md.detail = True
    code = build_code(base, percent)
    first = min(_routine_addresses(base, percent).values())
    return list(md.disasm(code[first - base :], first))


def routine(name: str, base: int = BASE, percent: float = DEFAULT_PERCENT):
    """One routine's instructions: from its entry label to the next one (or the cave's end)."""
    entries = sorted(_routine_addresses(base, percent).items(), key=lambda pair: pair[1])
    starts = dict(entries)
    order = [name for name, _ in entries]
    end = (
        starts[order[order.index(name) + 1]]
        if order.index(name) + 1 < len(order)
        else base + len(build_code(base, percent))
    )
    return [i for i in disassemble(base, percent) if starts[name] <= i.address < end]


def constants(base: int = BASE, percent: float = DEFAULT_PERCENT) -> list[float]:
    return list(struct.unpack_from("<5f", build_code(base, percent)))


class TestTheCurve:
    """What the patch is for, as numbers. ``health(p)`` is the health ratio at build progress
    ``p`` in ``[0, 1]``, and ``progress(r)`` is what the engine's two derivations recover from a
    health ratio - so the pair has to be each other's inverse or the progress bar lies."""

    @staticmethod
    def health(progress: float, fraction: float) -> float:
        """Start at `fraction`, add `(1 - fraction) / frames` per frame for `frames` frames."""
        return fraction + (1.0 - fraction) * progress

    @staticmethod
    def progress(ratio: float, fraction: float) -> float:
        return max(0.0, (ratio - fraction) / (1.0 - fraction))

    @pytest.mark.parametrize("percent", [0.0, 10.0, 25.0, MAX_PERCENT])
    def test_it_starts_at_the_percentage_and_ends_at_full_health(self, percent: float):
        fraction = percent / 100.0
        assert self.health(0.0, fraction) == pytest.approx(fraction)
        assert self.health(1.0, fraction) == pytest.approx(1.0)

    @pytest.mark.parametrize("percent", [0.0, 10.0, 25.0, MAX_PERCENT])
    @pytest.mark.parametrize("progress", [0.0, 0.25, 0.5, 0.9, 1.0])
    def test_the_derivation_inverts_the_ramp(self, percent: float, progress: float):
        """The reason the two derivation sites are in this patch at all. Leave them stock and a
        self-building structure reads `fraction` complete the frame it is placed."""
        fraction = percent / 100.0
        assert self.progress(self.health(progress, fraction), fraction) == pytest.approx(progress)

    def test_leaving_the_ramp_stock_would_reach_full_health_early(self):
        """The other half of "three things move together": the unscaled step adds a full
        `1 / frames` per frame on top of a 10% start, so health caps out at 90% built."""
        fraction = 0.1
        unscaled = [fraction + progress for progress in (0.85, 0.9, 0.95)]
        assert unscaled[0] < 1.0
        assert all(value >= 1.0 for value in unscaled[1:])

    def test_a_structure_damaged_below_its_start_reads_zero_rather_than_negative(self):
        """Why the low clamp is not defensive. Stock could never produce a negative percent
        because its floor was one hit point; with a floor of 10% of maximum, it can."""
        assert self.progress(0.02, 0.1) == 0.0

    def test_zero_percent_is_the_stock_relation(self):
        for progress in (0.0, 0.3, 1.0):
            assert self.health(progress, 0.0) == pytest.approx(progress)
            assert self.progress(progress, 0.0) == pytest.approx(progress)


class TestTheCave:
    def test_it_disassembles_cleanly_to_its_end(self):
        """Capstone stopping early means an invalid encoding, which would be a crash in-game."""
        code = build_code(BASE, DEFAULT_PERCENT)
        first = min(_routine_addresses(BASE, DEFAULT_PERCENT).values())
        assert sum(i.size for i in disassemble()) == len(code) - (first - BASE)

    def test_the_constants_are_the_parameter_and_what_derives_from_it(self):
        fraction, one, span, inverse, hundred = constants(percent=25.0)
        assert (fraction, one, hundred) == (pytest.approx(0.25), 1.0, 100.0)
        assert span == pytest.approx(0.75)
        assert inverse == pytest.approx(1.0 / 0.75)

    def test_no_routine_starts_inside_the_constant_block(self):
        """Nothing ever enters the cave at its base; the floats would decode as instructions."""
        entries = _routine_addresses(BASE, DEFAULT_PERCENT)
        assert set(entries) == set(_ROUTINES)
        assert min(entries.values()) >= BASE + 20
        assert len(set(entries.values())) == len(_ROUTINES)

    def test_initial_rewrites_the_delta_and_tails_into_the_call_it_displaced(self):
        """The whole trick of the `initial` routine: it does not call `internalChangeHealth`
        itself, it edits the argument the caller already pushed and jumps to the real slot, so
        the site's `ret 8` still cleans the stack and the hook's `call` returns normally."""
        insns = routine("initial")
        store = next(
            i for i in insns if i.mnemonic == "movss" and i.op_str == "dword ptr [esp + 0xc], xmm0"
        )
        load = next(
            i for i in insns if i.mnemonic == "addss" and i.op_str == "xmm0, dword ptr [esp + 0xc]"
        )
        assert load.address < store.address, "read the stock delta before overwriting it"
        tail = insns[-1]
        assert tail.mnemonic == "jmp"
        assert tail.op_str == f"dword ptr [eax + {ACTIVE_BODY_INTERNAL_CHANGE_HEALTH_SLOT:#x}]"
        assert not any(i.mnemonic == "ret" for i in insns)

    def test_initial_floors_the_target_at_one_point_before_subtracting_it(self):
        """`max(1.0, fraction * maxHealth)`, and then `- 1.0` because the delta the caller
        computed aimed at 1.0. Getting those two the wrong way round would cancel the floor."""
        insns = routine("initial")
        fraction_va = BASE
        one_va = BASE + 4
        assert [i.op_str for i in insns if i.mnemonic == "mulss"] == [
            f"xmm0, dword ptr [{fraction_va:#x}]"
        ]
        clamp = next(i for i in insns if i.mnemonic == "maxss")
        undo = next(i for i in insns if i.mnemonic == "subss")
        assert clamp.op_str == undo.op_str == "xmm0, xmm1"
        assert clamp.address < undo.address
        assert (
            next(i for i in insns if i.mnemonic == "movss" and i.op_str.startswith("xmm1")).op_str
            == f"xmm1, dword ptr [{one_va:#x}]"
        )

    def test_both_ramps_scale_by_the_same_span_constant(self):
        """The dozer ramp and the self-build heal cover the same remaining span, so a patch that
        scaled one and not the other would make builder-built and self-built structures differ."""
        span_va = BASE + 8
        for name in ("ramp", "selfbuild"):
            scales = [i for i in routine(name) if i.mnemonic == "fmul"]
            assert [i.op_str for i in scales] == [f"dword ptr [{span_va:#x}]"], name

    def test_ramp_reproduces_the_divide_it_displaced_against_the_callers_frame(self):
        """`[ebp-0x1c]` is the caller's local holding the frame count `calcTimeToBuild` produced.
        The cave never sets up a frame of its own, which is what keeps that read valid."""
        insns = routine("ramp")
        assert [i.op_str for i in insns if i.mnemonic == "fdiv"] == ["dword ptr [ebp - 0x1c]"]
        assert insns[-1].mnemonic == "ret"

    def test_selfbuild_leaves_the_x87_stack_the_way_the_caller_expects_it(self):
        """The caller divides two instructions later with `fdivp st(1)`, which wants the frame
        count on top and the scaled maximum beneath - so the `fild` has to come last."""
        insns = routine("selfbuild")
        fild = next(i for i in insns if i.mnemonic == "fild")
        scale = next(i for i in insns if i.mnemonic == "fmul")
        assert fild.op_str == "dword ptr [esi + 0x1c]"
        assert scale.address < fild.address
        assert insns[-1].mnemonic == "ret"

    def test_percent_returns_its_result_on_the_x87_stack(self):
        """The site's next instruction is `fstp [Object+0x288]`, so the routine has to hand back
        an st(0) even though it did the arithmetic in SSE."""
        insns = routine("percent")
        assert insns[-2].mnemonic == "pop"
        assert insns[-1].mnemonic == "ret"
        assert next(i for i in insns if i.mnemonic == "fld").op_str == "dword ptr [esp]"

    def test_percent_subtracts_before_it_divides_and_clamps_before_it_scales(self):
        """`max(0, (ratio - f) / (1 - f)) * 100`. Clamping after the `* 100` would be the same
        answer; clamping before the divide would not, because the divide is by a positive."""
        insns = routine("percent")
        scaling = [i for i in insns if i.mnemonic in ("subss", "mulss", "maxss")]
        assert [i.mnemonic for i in scaling] == ["subss", "mulss", "maxss", "mulss"]
        assert scaling[-1].op_str == f"xmm0, dword ptr [{BASE + 16:#x}]", "the last scale is by 100"

    def test_each_routine_asks_the_body_for_the_value_it_needs(self):
        slots = {
            "initial": BODY_GET_MAX_HEALTH_SLOT,
            "ramp": BODY_GET_MAX_HEALTH_SLOT,
            "selfbuild": BODY_GET_MAX_HEALTH_SLOT,
            "percent": BODY_GET_HEALTH_RATIO_SLOT,
        }
        for name, slot in slots.items():
            insns = routine(name)
            calls = [i for i in insns if i.mnemonic == "call"]
            assert [i.op_str for i in calls] == [f"dword ptr [eax + {slot:#x}]"], name
            fetch = next(
                i for i in insns if i.mnemonic == "mov" and i.op_str == "eax, dword ptr [ecx]"
            )
            assert fetch.address < calls[0].address, f"{name} loads the vtable from ecx first"

    def test_the_routines_that_call_out_preserve_ecx_across_the_call(self):
        """`ecx` is the body and the `this` pointer; a thiscall callee may clobber it, and three
        of the four sites still need it afterwards."""
        for name in ("initial", "percent"):
            insns = routine(name)
            call = next(i for i in insns if i.mnemonic == "call")
            assert insns[0].mnemonic == "push" and insns[0].op_str == "ecx", name
            assert any(
                i.mnemonic == "pop" and i.op_str == "ecx" and i.address > call.address
                for i in insns
            ), name

    @pytest.mark.parametrize("name", _ROUTINES)
    def test_every_routine_balances_its_own_stack(self, name: str):
        """A leaked or over-popped dword here corrupts the caller's frame, which is a crash a
        long way from the cave."""
        depth = 0
        for ins in routine(name):
            if ins.mnemonic == "push":
                depth += 4
            elif ins.mnemonic == "pop":
                depth -= 4
            elif ins.mnemonic == "sub" and ins.op_str.startswith("esp,"):
                depth += int(ins.op_str.split(",")[1], 0)
            elif ins.mnemonic == "add" and ins.op_str.startswith("esp,"):
                depth -= int(ins.op_str.split(",")[1], 0)
            assert depth >= 0, f"{name} pops past its own frame"
        assert depth == 0, f"{name} leaves {depth} bytes on the stack"

    def test_it_clobbers_no_callee_saved_register(self):
        """Every site returns into the middle of a function that is entitled to its ebx/esi/edi -
        the dozer ramp's caller is still holding the structure in edi when the cave returns."""
        for ins in disassemble():
            if ins.mnemonic in ("push", "pop"):
                continue
            written = ins.op_str.split(",")[0].strip()
            assert written not in ("ebx", "esi", "edi", "ebp"), f"{ins.mnemonic} writes {written}"

    def test_it_never_branches(self):
        """The arithmetic is branch-free by construction - both clamps are `maxss`. A branch here
        would mean a path the disassembly tests above do not cover."""
        assert not [i for i in disassemble() if i.mnemonic.startswith("j") and i.mnemonic != "jmp"]

    def test_the_only_jmp_is_the_tail_call_out_of_initial(self):
        jumps = [i for i in disassemble() if i.mnemonic == "jmp"]
        assert len(jumps) == 1
        assert jumps[0].address == routine("initial")[-1].address

    def test_it_relocates_with_its_section(self):
        """Every reference in the cave is either absolute-into-itself or register-relative, so the
        code differs between two bases only in the five float operands - which must all move."""
        low = build_code(BASE, DEFAULT_PERCENT)
        high = build_code(BASE + 0x1000, DEFAULT_PERCENT)
        assert len(low) == len(high)
        assert low[:20] == high[:20], "the constants themselves do not depend on where they land"
        assert low[20:] != high[20:], "but every reference to them does"


class TestApply:
    def test_apply_then_verify(self):
        data = construction_initial_health_image()
        ConstructionInitialHealthPatch().apply(data)
        assert ConstructionInitialHealthPatch().verify(data) == []

    def test_every_hook_is_a_call_to_its_routine_padded_with_nops(self):
        data = construction_initial_health_image()
        ConstructionInitialHealthPatch().apply(data)
        section_va, _off, _vsize = find_section(data, SECTION_NAME)
        entries = _routine_addresses(section_va, DEFAULT_PERCENT)
        for va, (original, label) in _HOOKS.items():
            off = va_to_offset(data, va)
            site = bytes(data[off : off + len(original)])
            assert site[0] == 0xE8, f"{va:#010x} is not a call"
            assert va + 5 + struct.unpack_from("<i", site, 1)[0] == entries[label]
            assert site[5:] == b"\x90" * (len(original) - 5), f"{va:#010x} is not nop-padded"

    def test_the_hooks_cover_every_site_the_addresses_name(self):
        expected = {
            *CONSTRUCTION_INITIAL_HEALTH_CALLS,
            CONSTRUCTION_RAMP_HEALTH_STEP,
            SELF_BUILD_HEAL_STEP,
            *CONSTRUCTION_PERCENT_FROM_RATIO,
        }
        assert set(_HOOKS) == expected
        assert len(expected) == 8

    def test_it_refuses_an_image_whose_construction_arithmetic_is_not_this_build(self):
        """Each anchor is load-bearing: the caves read `ecx`, the caller's stack and the caller's
        frame, none of which is true of some other build's bytes at the same address."""
        for va in ANCHORS:
            data = construction_initial_health_image()
            off = va_to_offset(data, va)
            data[off] ^= 0xFF
            with pytest.raises(ValueError, match=f"{va:#010x}"):
                ConstructionInitialHealthPatch().apply(data)

    def test_applying_twice_raises_rather_than_stacking(self):
        data = construction_initial_health_image()
        ConstructionInitialHealthPatch().apply(data)
        with pytest.raises(ValueError):
            ConstructionInitialHealthPatch().apply(data)

    def test_verify_fails_against_a_different_percentage(self):
        data = construction_initial_health_image()
        ConstructionInitialHealthPatch(percent=25.0).apply(data)
        assert ConstructionInitialHealthPatch(percent=25.0).verify(data) == []
        assert ConstructionInitialHealthPatch(percent=10.0).verify(data) != []

    def test_verify_reports_an_unpatched_image(self):
        problems = ConstructionInitialHealthPatch().verify(construction_initial_health_image())
        assert problems == [f"{SECTION_NAME} section is absent"]

    def test_it_adds_no_ini_surface(self):
        assert ConstructionInitialHealthPatch().ini_surface() is STOCK


class TestDetect:
    @pytest.mark.parametrize("percent", [0.0, 10.0, 25.0, MAX_PERCENT])
    def test_it_recovers_the_percentage_it_was_applied_with(self, percent: float):
        data = construction_initial_health_image()
        ConstructionInitialHealthPatch(percent=percent).apply(data)
        found = ConstructionInitialHealthPatch.detect(data)
        assert found is not None
        assert found.options() == {"percent": pytest.approx(percent)}

    def test_it_answers_none_for_an_unpatched_image(self):
        assert ConstructionInitialHealthPatch.detect(construction_initial_health_image()) is None


class TestParameter:
    @pytest.mark.parametrize("percent", [-1.0, MAX_PERCENT + 0.1, 100.0])
    def test_it_refuses_a_percentage_outside_the_range(self, percent: float):
        with pytest.raises(ValueError, match="percent must be between"):
            ConstructionInitialHealthPatch(percent=percent)

    def test_zero_is_allowed_and_is_the_identity(self):
        """The claim the docstring makes about `--percent 0`, as constants: a fraction of zero, a
        span of one and an inverse span of one make every routine reproduce stock's number."""
        fraction, one, span, inverse, hundred = constants(percent=0.0)
        assert (fraction, one, span, inverse, hundred) == (0.0, 1.0, 1.0, 1.0, 100.0)


class TestComposition:
    def test_it_is_registered_and_not_experimental(self):
        assert PATCHES[ConstructionInitialHealthPatch.name] is ConstructionInitialHealthPatch
        assert not ConstructionInitialHealthPatch.experimental
        assert ConstructionInitialHealthPatch.author

    def test_it_does_not_edit_any_byte_production_split_anchors(self):
        """`production-split` hooks the same `DozerAIUpdate` advance. Its anchor over that
        function is split around the six bytes this patch owns; the two must not intersect, or
        whichever applied second would raise."""
        theirs = {va + index for va, blob in ps.ANCHORS.items() for index in range(len(blob))}
        ours = {va + index for va, (blob, _) in _HOOKS.items() for index in range(len(blob))}
        assert not theirs & ours

    def test_it_does_not_anchor_any_byte_production_split_rewrites(self):
        """The mirror. `production-split` repoints five bytes at `0x0088DE6D`, and this patch's
        ramp anchor sits below them - so the anchors here must stop short of that call."""
        theirs = {va + index for va, *_ in ps.HOOKS for index in range(5)}
        ours = {va + index for va, blob in ANCHORS.items() for index in range(len(blob))}
        assert not theirs & ours
