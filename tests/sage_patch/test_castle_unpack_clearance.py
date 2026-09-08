"""Tests for `castle-unpack-clearance`, which stops a camp unpack dropping structures.

The cave is hand-assembled x86 that cannot be executed here, so the tests that matter disassemble
it back and assert it says what it was meant to say. Three things can go wrong and none of them
raises on its own.

The first is the **calling convention**. The cave takes the place of a `__stdcall` callee that
cleans five arguments with ``ret 0x14``, and it is entered by the engine's own `call`. A routine
that returns with a bare `ret`, or that forwards four arguments where the thunk reads five, leaves
the builder's stack short by a frame and crashes on the next unpack rather than at the patch site.

The second is **which ask is which**. The first ask has to be the stock question bit for bit and
the second has to differ in exactly one dword - the flags word. Swapping them, or retrying with the
stock flags, produces a patch that applies, verifies, and changes nothing.

The third is the **build fingerprint**. The patch rewrites five bytes and reads seven windows it
does not rewrite, including one dword of `.rdata`; every one of them has to fail loudly on anything
else.
"""

from __future__ import annotations

import struct

import pytest

from sage_patch.patches import foundation_rebind as fnd
from sage_patch.patches.castle_unpack_clearance import (
    ANCHORS,
    BUILD_ASSISTANT_OBJECT_GATE,
    BUILD_ASSISTANT_TERRAIN_GATE,
    CASTLE_BUILD_MEMBER_ARGS,
    CASTLE_BUILD_MEMBER_KEEP_TEST,
    CASTLE_BUILD_MEMBER_REJECT,
    CASTLE_LEGALITY_THUNK,
    HOOK_ORIGINAL,
    HOOK_VA,
    IS_LOCATION_LEGAL,
    IS_LOCATION_LEGAL_SLOT_VA,
    SECTION_NAME,
    STOCK_FLAGS,
    THUNK_CALL_TARGET,
    UNCONDITIONAL_FLAGS,
    CastleUnpackClearancePatch,
    build_code,
)
from sage_patch.registry import PATCHES
from sage_patch.utils import find_section, va_to_offset

from .synthetic import _sparse_image

BASE = 0x00F00000
IMAGE_BASE = 0x400000


@pytest.fixture
def image() -> bytearray:
    """A stand-in mapping only the pages this patch reads or rewrites.

    Its sites span `BuildAssistant` and `CastleBehavior`, ~8 KB of `.text` apart, plus one dword of
    `.rdata` four megabytes further on, so a sparse image is a handful of pages where a flat one
    would be that whole span. Everything not planted reads as zero, which is what makes the image
    useful negatively too: a hook aimed one instruction to either side finds nothing there."""
    return _sparse_image({HOOK_VA: HOOK_ORIGINAL, **ANCHORS})


def _patched(image: bytearray) -> bytearray:
    data = bytearray(image)
    CastleUnpackClearancePatch().apply(data)
    return data


def disassemble(base: int = BASE):
    capstone = pytest.importorskip("capstone")
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    md.detail = True
    return list(md.disasm(build_code(base), base))


class TestTheCave:
    def test_it_disassembles_cleanly_to_its_end(self):
        """Capstone stopping early means an invalid encoding, which would be a crash in-game."""
        insns = disassemble()
        assert sum(i.size for i in insns) == len(build_code(BASE))

    def test_it_is_a_callee_and_cleans_the_thunks_arguments(self):
        """The cave replaces the *target* of the engine's `call`, so it is entered the way the
        thunk was. A bare `ret`, or any other immediate, leaves five dwords on the builder's
        stack."""
        insns = disassemble()
        assert [(i.mnemonic, i.op_str) for i in insns[:2]] == [
            ("push", "ebp"),
            ("mov", "ebp, esp"),
        ]
        assert (insns[-2].mnemonic, insns[-2].op_str) == ("pop", "ebp")
        assert (insns[-1].mnemonic, insns[-1].op_str) == ("ret", "0x14")

    def test_it_asks_the_thunk_exactly_twice(self):
        calls = [i for i in disassemble() if i.mnemonic == "call"]
        assert [int(i.op_str, 16) for i in calls] == [CASTLE_LEGALITY_THUNK] * 2

    def test_the_first_ask_is_the_stock_question(self):
        """Bit for bit: the caller's own flags word is passed through, so a placement the engine
        would have allowed takes exactly the stock path and the second ask never runs."""
        pushes = self._pushes_before(0)
        assert pushes == [
            "dword ptr [ebp + 0x18]",
            "dword ptr [ebp + 0x14]",
            "dword ptr [ebp + 0x10]",
            "dword ptr [ebp + 0xc]",
            "dword ptr [ebp + 8]",
        ]

    def test_the_retry_differs_in_exactly_one_argument(self):
        """The flags word, and nothing else. Forwarding a different position or template would
        answer a question about a placement the builder never asked for."""
        first, second = self._pushes_before(0), self._pushes_before(1)
        assert len(first) == len(second) == 5
        differ = [i for i, (a, b) in enumerate(zip(first, second, strict=True)) if a != b]
        assert differ == [1], "the two asks must disagree only about the flags word"

    def test_the_retry_clears_the_flags_word(self):
        """`push 0`, not `push 5`: with the flags word clear, the terrain tests (bit 0x1) and the
        object-clearance test (bit 0x4) are both skipped and only the three unflagged tests -
        map extent, supply proximity, wall-hub proximity - can still refuse."""
        second = self._pushes_before(1)
        assert int(second[1], 16) == UNCONDITIONAL_FLAGS
        assert UNCONDITIONAL_FLAGS & (STOCK_FLAGS) == 0

    def test_the_retry_runs_only_when_the_stock_ask_refused(self):
        """`test eax, eax` then a `je` over the retry: zero is legal and is returned as-is.
        Inverting this would re-ask on success and never re-ask on failure."""
        insns = disassemble()
        first_call = next(i for i in insns if i.mnemonic == "call")
        test = next(i for i in insns if i.mnemonic == "test" and i.address > first_call.address)
        assert test.op_str == "eax, eax"
        skip = next(i for i in insns if i.mnemonic == "je" and i.address > test.address)
        second_call = [i for i in insns if i.mnemonic == "call"][1]
        target = int(skip.op_str, 16)
        assert second_call.address < target, "the je must jump over the retry, not into it"

    def test_the_answer_it_returns_is_the_last_one_it_asked(self):
        """`eax` is the thunk's own return and nothing touches it after the second call, so the
        retry's verdict is what the builder tests."""
        insns = disassemble()
        second_call = [i for i in insns if i.mnemonic == "call"][1]
        after = [i for i in insns if i.address > second_call.address]
        assert [(i.mnemonic, i.op_str) for i in after] == [("pop", "ebp"), ("ret", "0x14")]

    def test_every_conditional_branch_stays_inside_the_cave(self):
        """A displacement computed wrong would jump into arbitrary engine code."""
        code = build_code(BASE)
        lo, hi = BASE, BASE + len(code)
        for ins in disassemble():
            if not ins.mnemonic.startswith("j"):
                continue
            assert lo <= int(ins.op_str, 16) < hi, f"{ins.mnemonic} at {ins.address:#x} escapes"

    def test_it_never_jumps_out(self):
        """Unlike a displaced-`jmp` cave, this one has no resume point: it returns."""
        assert not [i for i in disassemble() if i.mnemonic == "jmp"]

    def test_it_relocates_with_its_section(self):
        a, b = build_code(BASE), build_code(BASE + 0x1000)
        assert a != b, "the two calls to the thunk must be recomputed for the cave's address"
        assert len(a) == len(b)

    @staticmethod
    def _pushes_before(index: int) -> list[str]:
        """The operands pushed for call number ``index``, in the order they are pushed."""
        insns = disassemble()
        calls = [i for i in insns if i.mnemonic == "call"]
        # for the first ask, start past the prologue so its `push ebp` is not counted as an argument
        start = calls[index - 1].address if index else insns[1].address
        return [
            i.op_str
            for i in insns
            if i.mnemonic == "push" and start < i.address < calls[index].address
        ]


class TestApply:
    def test_apply_then_verify(self, image):
        data = _patched(image)
        assert CastleUnpackClearancePatch().verify(data) == []

    def test_the_hook_is_a_call_to_the_cave(self, image):
        """Five bytes for five: the stock instruction is itself a `call rel32`, so the site is an
        exact fit and nothing is padded."""
        data = _patched(image)
        section_va, _off, _vsize = find_section(data, SECTION_NAME)
        off = va_to_offset(data, HOOK_VA)
        site = bytes(data[off : off + len(HOOK_ORIGINAL)])
        assert len(HOOK_ORIGINAL) == 5
        assert site[0] == 0xE8
        assert HOOK_VA + 5 + struct.unpack_from("<i", site, 1)[0] == section_va

    def test_the_cave_holds_the_expected_code(self, image):
        data = _patched(image)
        section_va, off, _vsize = find_section(data, SECTION_NAME)
        assert bytes(data[off : off + len(build_code(section_va))]) == build_code(section_va)

    def test_the_section_name_survives_the_eight_byte_pe_field(self, image):
        assert len(SECTION_NAME) <= 8, "a longer name is silently truncated in the header"
        assert find_section(_patched(image), SECTION_NAME) is not None

    def test_refuses_to_apply_twice(self, image):
        data = _patched(image)
        with pytest.raises(ValueError, match="expected"):
            CastleUnpackClearancePatch().apply(data)

    def test_the_hooked_call_really_names_the_thunk(self):
        """Why anchoring the site's own five bytes proves what the patch repoints: they *are* the
        displacement, so asserting them asserts the target."""
        assert THUNK_CALL_TARGET == CASTLE_LEGALITY_THUNK

    def test_the_vtable_slot_names_the_legality_function(self):
        """The thunk dispatches through `TheBuildAssistant`'s vtable, so the flag semantics the
        retry depends on are only this build's if that slot still holds this function."""
        assert ANCHORS[IS_LOCATION_LEGAL_SLOT_VA] == struct.pack("<I", IS_LOCATION_LEGAL)

    @pytest.mark.parametrize(
        "va",
        [
            CASTLE_BUILD_MEMBER_KEEP_TEST,
            CASTLE_BUILD_MEMBER_ARGS,
            CASTLE_BUILD_MEMBER_REJECT,
            CASTLE_LEGALITY_THUNK,
            IS_LOCATION_LEGAL_SLOT_VA,
            BUILD_ASSISTANT_OBJECT_GATE,
            BUILD_ASSISTANT_TERRAIN_GATE,
        ],
    )
    def test_a_moved_anchor_refuses_to_apply(self, image, va):
        off = va_to_offset(image, va)
        image[off : off + 4] = b"\x90\x90\x90\x90"
        with pytest.raises(ValueError, match="not this build's"):
            CastleUnpackClearancePatch().apply(image)

    def test_the_stock_flags_word_is_the_one_the_builder_pushes(self):
        """`STOCK_FLAGS` is not an independent claim: the anchored argument setup contains the
        `push 5` it names, so the two cannot drift apart."""
        assert bytes([0x6A, STOCK_FLAGS]) in ANCHORS[CASTLE_BUILD_MEMBER_ARGS]

    def test_it_does_not_touch_the_builder_beyond_the_five_hooked_bytes(self, image):
        """The keep exemption, the argument setup and the refusal edge all have to survive: the
        patch changes what the call answers, never what the builder does with the answer."""
        data = _patched(image)
        for va, planted in ANCHORS.items():
            off = va_to_offset(data, va)
            assert bytes(data[off : off + len(planted)]) == planted, f"{va:#010x} was rewritten"


class TestRegistration:
    def test_it_is_offered_on_the_cli(self):
        assert PATCHES[CastleUnpackClearancePatch.name] is CastleUnpackClearancePatch

    def test_it_composes_with_foundation_rebind(self):
        """The other patch in this corner of the binary. The composition claim in the module
        docstring, as an assertion: neither edits a byte the other edits, and neither reads a
        window the other rewrites."""
        mine = set(range(HOOK_VA, HOOK_VA + len(HOOK_ORIGINAL)))
        theirs = {
            va
            for hook in (fnd.HOOK_DESTROY_CALL_VA, fnd.HOOK_WALK_CALL_VA)
            for va in range(hook, hook + 5)
        }
        assert not mine & theirs
        assert not theirs & {
            va for base, blob in ANCHORS.items() for va in range(base, base + len(blob))
        }
        assert not mine & {
            va for base, blob in fnd.ANCHORS.items() for va in range(base, base + len(blob))
        }
