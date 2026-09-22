"""Tests for the perf-stage-readout patch.

The patch is two hooks and an accumulator, and the accumulator is where the risk is: a profile that
is merely *wrong* looks exactly like a profile that is right, so nothing downstream would raise.
:class:`TestTheAccumulatorRuns` therefore **executes** the cave under Unicorn against a stubbed
`QueryPerformanceCounter` whose clock the test drives, and asserts the arithmetic it was written
for - inclusive, exclusive, nesting, and the three ways a scope can fail to be measurable.

:class:`TestTheHooksAreWhereTheNameIs` is the reverse-engineering claim: that the name is a
``.rdata`` pointer at the constructor and a stack address by the time the D3DPERF wrapper sees it.
That is the reason the hook is where it is, and it is checked against the real stage site's bytes
rather than restated.
"""

from __future__ import annotations

import struct

import pytest

from sage_ini.engine import STOCK
from sage_patch.addresses import (
    PERF_BEGIN_EVENT,
    PERF_END_EVENT,
    PERF_SCOPE_CTOR,
    PERF_SCOPE_CTOR_ENTRY,
    PERF_SCOPE_CTOR_RESUME,
    PERF_SCOPE_DTOR,
    PERF_SCOPE_DTOR_ENTRY,
    PERF_SCOPE_STAGE_SITE,
    PERF_SCOPE_STAGE_SITE_BYTES,
    QUERY_PERFORMANCE_COUNTER_IAT,
)
from sage_patch.patcher import apply_patches
from sage_patch.patches.perf_stage_readout import (
    ANCHORS,
    BLOCK_MAGIC,
    BLOCK_VERSION,
    CODE_OFFSET,
    OFF_DEPTH,
    OFF_OVERFLOW,
    OFF_SLOTS,
    OFF_SLOTS_USED,
    OFF_TABLE_FULL,
    OFF_UNBALANCED,
    SECTION_NAME,
    SLOT_CAPACITY,
    SLOT_SIZE,
    STACK_CAPACITY,
    STAGE_NAMES,
    PerfStageReadoutPatch,
    build_code,
    enter_va,
    leave_va,
)
from sage_patch.pe import image_sections
from sage_patch.registry import PATCHES
from sage_patch.utils import find_section, va_to_offset

from .synthetic import perf_stage_readout_image

#: Where the emulated section is mapped. Any page-aligned address works; the cave addresses its own
#: counters absolutely, so the value only has to match what `build_code` was given.
BASE = 0x00F00000

#: Two of the engine's real call sites, used as keys: the address each returns to, which is what
#: the cave reads off the stack. The cave never dereferences anything - it compares the return
#: address - so these need to be the right addresses and nothing more.
SITE_SHADOW = 0x00449DE5  # the `UpdateShadowMap` scope
SITE_VIEWS = 0x00449FBF  # the `RenderViews` scope

#: A name for the scope's own argument. Four of the thirty sites pass a stack pointer here rather
#: than a literal, which is exactly why it is not the key; the cave only ever re-runs the `test`
#: the constructor does on it.
NAME_LITERAL = 0x00BD9DEC


@pytest.fixture
def image() -> bytearray:
    return perf_stage_readout_image()


@pytest.fixture
def patched(image: bytearray) -> bytearray:
    PerfStageReadoutPatch().apply(image)
    return image


class TestRegistration:
    def test_registered_and_stable(self) -> None:
        assert PATCHES["perf-stage-readout"] is PerfStageReadoutPatch
        assert PerfStageReadoutPatch.author == "officialNecro"
        assert PerfStageReadoutPatch.experimental is False
        assert ".experimental." not in PerfStageReadoutPatch.__module__

    def test_changes_no_ini_surface(self) -> None:
        assert PerfStageReadoutPatch().ini_surface() is STOCK

    def test_takes_no_parameters(self) -> None:
        assert PerfStageReadoutPatch().options() == {}


class TestTheHooksAreWhereTheNameIs:
    """Why the constructor and not the wrapper.

    The stage site pushes the literal's address; the constructor's first instruction reads it off
    the stack. Everything after that point in the engine sees a copy, so a hook further in would be
    keying on `[ebp-0x158]` - one address shared by the three stages of the frame's draw.
    """

    def test_the_stage_site_pushes_the_rdata_literal(self) -> None:
        # push colour / push "Frame" / push "UpdateShadowMap" / lea ecx, [ebp-0x158] / call ctor
        assert PERF_SCOPE_STAGE_SITE_BYTES[0] == 0x53  # push ebx, the colour
        assert PERF_SCOPE_STAGE_SITE_BYTES[1] == 0x68  # push imm32, the category
        assert struct.unpack_from("<I", PERF_SCOPE_STAGE_SITE_BYTES, 2)[0] == 0x00BD9DFC
        assert PERF_SCOPE_STAGE_SITE_BYTES[6] == 0x68  # push imm32, the name
        assert struct.unpack_from("<I", PERF_SCOPE_STAGE_SITE_BYTES, 7)[0] == NAME_LITERAL
        # ... and the call really does land on the routine the patch hooks.
        assert PERF_SCOPE_STAGE_SITE_BYTES[17] == 0xE8
        displacement = struct.unpack_from("<i", PERF_SCOPE_STAGE_SITE_BYTES, 18)[0]
        assert PERF_SCOPE_STAGE_SITE + 22 + displacement == PERF_SCOPE_CTOR

    def test_the_constructor_reads_that_push(self) -> None:
        # mov eax, [esp+4] -- the name, one push deep past the return address.
        assert PERF_SCOPE_CTOR_ENTRY == bytes.fromhex("8b44240485c0")
        assert PERF_SCOPE_CTOR + len(PERF_SCOPE_CTOR_ENTRY) == PERF_SCOPE_CTOR_RESUME

    def test_the_destructor_is_nothing_but_the_jump_it_is_replaced_with(self) -> None:
        assert len(PERF_SCOPE_DTOR_ENTRY) == 5
        assert PERF_SCOPE_DTOR_ENTRY[0] == 0xE9
        displacement = struct.unpack_from("<i", PERF_SCOPE_DTOR_ENTRY, 1)[0]
        assert PERF_SCOPE_DTOR + 5 + displacement == PERF_END_EVENT

    def test_every_anchor_is_checked(self) -> None:
        assert set(ANCHORS) == {
            PERF_SCOPE_CTOR,
            PERF_SCOPE_DTOR,
            PERF_BEGIN_EVENT,
            PERF_END_EVENT,
            PERF_SCOPE_STAGE_SITE,
        }

    def test_the_engine_has_the_names_this_documents(self) -> None:
        assert len(STAGE_NAMES) == 28
        assert len(set(STAGE_NAMES)) == 28
        assert "UpdateShadowMap" in STAGE_NAMES
        assert "MeshDX8Render" in STAGE_NAMES
        assert SLOT_CAPACITY > 2 * len(STAGE_NAMES)  # the load factor the probe length rests on


class TestApply:
    def test_apply_and_verify(self, patched: bytearray) -> None:
        assert PerfStageReadoutPatch().verify(patched) == []
        assert PerfStageReadoutPatch.detect(patched) is not None

    def test_absent_from_a_stock_image(self, image: bytearray) -> None:
        assert PerfStageReadoutPatch().verify(image) != []
        assert PerfStageReadoutPatch.detect(image) is None

    def test_both_hooks_land_in_the_cave(self, patched: bytearray) -> None:
        located = find_section(patched, SECTION_NAME)
        assert located is not None
        section_va, _, _ = located
        for va, expected in (
            (PERF_SCOPE_CTOR, enter_va(section_va)),
            (PERF_SCOPE_DTOR, leave_va(section_va)),
        ):
            off = va_to_offset(patched, va)
            assert off is not None
            assert patched[off] == 0xE9
            assert va + 5 + struct.unpack_from("<i", patched, off + 1)[0] == expected

    def test_the_sixth_displaced_byte_is_a_nop(self, patched: bytearray) -> None:
        """Five bytes of jump replace six of instruction, so the odd byte has to be filled or the
        engine falls into the tail of `test eax, eax`."""
        off = va_to_offset(patched, PERF_SCOPE_CTOR)
        assert off is not None
        assert patched[off + 5] == 0x90

    def test_only_the_two_hooks_are_edited(self, image: bytearray) -> None:
        before = bytes(image)
        PerfStageReadoutPatch().apply(image)
        changed = {index for index in range(len(before)) if before[index] != image[index]}
        # Everything outside the two hook sites is either untouched or PE header bookkeeping.
        hooks = set()
        for va, length in ((PERF_SCOPE_CTOR, 6), (PERF_SCOPE_DTOR, 5)):
            off = va_to_offset(before, va)
            assert off is not None
            hooks |= set(range(off, off + length))
        # SizeOfHeaders rather than a fixed slab: this image maps a page per planted site, so how
        # far the section table reaches is a property of the image and not a constant.
        e_lfanew = struct.unpack_from("<I", before, 0x3C)[0]
        header_end = struct.unpack_from("<I", before, e_lfanew + 24 + 60)[0]
        assert changed <= hooks | set(range(0, header_end))

    def test_refuses_a_build_whose_scope_class_differs(self, image: bytearray) -> None:
        off = va_to_offset(image, PERF_SCOPE_STAGE_SITE)
        assert off is not None
        image[off + 7] = 0xFF  # a different name literal: not this build's draw
        with pytest.raises(ValueError, match="render-scope class"):
            PerfStageReadoutPatch().apply(image)

    def test_applying_twice_raises(self, patched: bytearray) -> None:
        with pytest.raises(ValueError):
            PerfStageReadoutPatch().apply(patched)

    def test_the_cave_is_appended_past_every_existing_section(self, image: bytearray) -> None:
        """Rule 1 of composing patches: a cave allocated past the highest section keeps the
        section table sorted whatever else has been added, so any subset applies in any order."""
        before = max(s.virtual_address + s.mapped_size for s in image_sections(image))
        PerfStageReadoutPatch().apply(image)
        located = find_section(image, SECTION_NAME)
        assert located is not None
        assert located[0] >= before

    def test_round_trips_through_the_file_pipeline(self, tmp_path, image: bytearray) -> None:
        source = tmp_path / "game.dat"
        source.write_bytes(bytes(image))
        out = apply_patches(source, [PerfStageReadoutPatch()], tmp_path / "out.dat")
        assert PerfStageReadoutPatch().verify(out.read_bytes()) == []


class TestTheBlockIsSelfDescribing:
    def test_header(self) -> None:
        block = build_code(BASE)
        magic, version, slots, stack = struct.unpack_from("<IIII", block, 0)
        assert magic == BLOCK_MAGIC
        assert struct.pack("<I", magic) == b"PSTG"
        assert version == BLOCK_VERSION
        assert slots == SLOT_CAPACITY
        assert stack == STACK_CAPACITY

    def test_the_counters_start_clear(self) -> None:
        block = build_code(BASE)
        for offset in (OFF_DEPTH, OFF_SLOTS_USED, OFF_OVERFLOW, OFF_UNBALANCED, OFF_TABLE_FULL):
            assert struct.unpack_from("<I", block, offset)[0] == 0
        assert block[OFF_SLOTS:CODE_OFFSET] == bytes(CODE_OFFSET - OFF_SLOTS)

    def test_the_code_starts_past_every_counter(self) -> None:
        assert CODE_OFFSET >= OFF_SLOTS + SLOT_CAPACITY * SLOT_SIZE + STACK_CAPACITY * 24
        assert enter_va(BASE) == BASE + CODE_OFFSET


# --------------------------------------------------------------------------------------------
# Executing the cave
# --------------------------------------------------------------------------------------------

_STUB = 0x00E00000  # where the QueryPerformanceCounter stand-in is mapped
_STACK = 0x00200000
_STACK_SIZE = 0x10000
_SENTINEL = 0x00DEAD00


class Machine:
    """The cave, running, with a clock the test turns by hand.

    `QueryPerformanceCounter` is stubbed in Python rather than assembled, so a scope's duration is
    whatever the test says it is - which is the only way to assert that 40 ticks of a 100-tick
    parent were the child's.
    """

    def __init__(self) -> None:
        unicorn = pytest.importorskip("unicorn")
        self.regs = pytest.importorskip("unicorn.x86_const")
        self.unicorn = unicorn
        self.uc = unicorn.Uc(unicorn.UC_ARCH_X86, unicorn.UC_MODE_32)
        self.clock = 0

        code = build_code(BASE)
        size = (len(code) + 0xFFF) & ~0xFFF
        self.uc.mem_map(BASE, size)
        self.uc.mem_write(BASE, code)

        self.uc.mem_map(_STACK, _STACK_SIZE)
        self.uc.mem_map(_STUB, 0x1000)
        self.uc.mem_write(_STUB, b"\xc3" * 0x10)

        iat_page = QUERY_PERFORMANCE_COUNTER_IAT & ~0xFFF
        self.uc.mem_map(iat_page, 0x1000)
        self.uc.mem_write(QUERY_PERFORMANCE_COUNTER_IAT, struct.pack("<I", _STUB))

        self.uc.hook_add(unicorn.UC_HOOK_CODE, self._qpc, begin=_STUB, end=_STUB + 0x10)

    def _qpc(self, uc, address, size, user_data) -> None:  # noqa: ANN001, ARG002
        """`BOOL __stdcall QueryPerformanceCounter(LARGE_INTEGER *out)` - writes the clock and
        pops its own argument, which is what the cave's `call [iat]` is written against."""
        esp = uc.reg_read(self.regs.UC_X86_REG_ESP)
        ret = struct.unpack("<I", uc.mem_read(esp, 4))[0]
        out = struct.unpack("<I", uc.mem_read(esp + 4, 4))[0]
        uc.mem_write(out, struct.pack("<Q", self.clock))
        uc.reg_write(self.regs.UC_X86_REG_ESP, esp + 8)  # return address + the stdcall argument
        uc.reg_write(self.regs.UC_X86_REG_EAX, 1)
        uc.reg_write(self.regs.UC_X86_REG_EIP, ret)

    def enter(self, site: int, name: int = NAME_LITERAL) -> None:
        """One `PerfScope` construction, with the stack the stage site leaves behind: the return
        address first, which is the key, then the three arguments."""
        esp = _STACK + _STACK_SIZE - 0x100
        self.uc.mem_write(esp, struct.pack("<IIII", site, name, 0x00BD9DFC, 0))
        self.uc.reg_write(self.regs.UC_X86_REG_ESP, esp)
        self.uc.emu_start(enter_va(BASE), PERF_SCOPE_CTOR_RESUME)
        assert self.uc.reg_read(self.regs.UC_X86_REG_ESP) == esp, "the entry moved the stack"

    def leave(self) -> None:
        """One `PerfScope` destruction: no arguments, just the return address."""
        esp = _STACK + _STACK_SIZE - 0x100
        self.uc.mem_write(esp, struct.pack("<I", _SENTINEL))
        self.uc.reg_write(self.regs.UC_X86_REG_ESP, esp)
        self.uc.emu_start(leave_va(BASE), PERF_END_EVENT)
        assert self.uc.reg_read(self.regs.UC_X86_REG_ESP) == esp, "the exit moved the stack"

    def scope(self, site: int, ticks: int, name: int = NAME_LITERAL) -> None:
        """A whole leaf scope that takes ``ticks``."""
        self.enter(site, name)
        self.clock += ticks
        self.leave()

    def counter(self, offset: int) -> int:
        return struct.unpack("<I", self.uc.mem_read(BASE + offset, 4))[0]

    def slot(self, site: int) -> tuple[int, int, int]:
        """``(calls, inclusive, exclusive)`` for a call site, or zeroes if it has no slot."""
        for index in range(SLOT_CAPACITY):
            at = BASE + OFF_SLOTS + index * SLOT_SIZE
            raw = bytes(self.uc.mem_read(at, SLOT_SIZE))
            if struct.unpack_from("<I", raw, 0)[0] == site:
                calls = struct.unpack_from("<I", raw, 4)[0]
                inclusive = struct.unpack_from("<Q", raw, 8)[0]
                return calls, inclusive, struct.unpack_from("<Q", raw, 16)[0]
        return 0, 0, 0


class TestTheAccumulatorRuns:
    def test_one_scope(self) -> None:
        m = Machine()
        m.scope(SITE_SHADOW, 100)
        assert m.slot(SITE_SHADOW) == (1, 100, 100)
        assert m.counter(OFF_DEPTH) == 0
        assert m.counter(OFF_SLOTS_USED) == 1

    def test_repeats_accumulate_into_one_slot(self) -> None:
        m = Machine()
        m.scope(SITE_SHADOW, 100)
        m.scope(SITE_SHADOW, 250)
        assert m.slot(SITE_SHADOW) == (2, 350, 350)
        assert m.counter(OFF_SLOTS_USED) == 1

    def test_two_names_take_two_slots(self) -> None:
        m = Machine()
        m.scope(SITE_SHADOW, 100)
        m.scope(SITE_VIEWS, 40)
        assert m.slot(SITE_SHADOW) == (1, 100, 100)
        assert m.slot(SITE_VIEWS) == (1, 40, 40)
        assert m.counter(OFF_SLOTS_USED) == 2

    def test_a_child_is_subtracted_from_its_parent(self) -> None:
        """The whole point of the exclusive column: a parent that spent 100 ticks with 40 of them
        inside a child did 60 ticks of work itself."""
        m = Machine()
        m.enter(SITE_SHADOW)
        m.clock += 30
        m.scope(SITE_VIEWS, 40)
        m.clock += 30
        m.leave()
        assert m.slot(SITE_SHADOW) == (1, 100, 60)
        assert m.slot(SITE_VIEWS) == (1, 40, 40)
        assert m.counter(OFF_DEPTH) == 0

    def test_two_children_are_both_subtracted(self) -> None:
        m = Machine()
        m.enter(SITE_SHADOW)
        m.scope(SITE_VIEWS, 40)
        m.clock += 10
        m.scope(SITE_VIEWS, 25)
        m.leave()
        assert m.slot(SITE_SHADOW) == (1, 75, 10)
        assert m.slot(SITE_VIEWS) == (2, 65, 65)

    def test_three_deep(self) -> None:
        third = 0x00BDC3F4  # "RenderParticles"
        m = Machine()
        m.enter(SITE_SHADOW)
        m.clock += 5
        m.enter(SITE_VIEWS)
        m.clock += 7
        m.scope(third, 20)
        m.clock += 3
        m.leave()
        m.clock += 5
        m.leave()
        assert m.slot(third) == (1, 20, 20)
        assert m.slot(SITE_VIEWS) == (1, 30, 10)
        assert m.slot(SITE_SHADOW) == (1, 40, 10)

    def test_a_null_name_is_measured_like_any_other_scope(self) -> None:
        """The constructor tolerates a null name and does nothing with it - but the scope still
        happened, still took time and still has a call site, so keying on the site measures it.

        This is what keying on the return address bought: with the name as the key there was
        nothing to key a nameless scope on, so it was timed by nobody."""
        m = Machine()
        m.enter(SITE_SHADOW)
        m.clock += 10
        m.scope(SITE_VIEWS, 40, name=0)  # a scope with no name, and a slot all the same
        m.clock += 10
        m.leave()
        assert m.counter(OFF_DEPTH) == 0
        assert m.counter(OFF_SLOTS_USED) == 2
        assert m.slot(SITE_VIEWS) == (1, 40, 40)
        assert m.slot(SITE_SHADOW) == (1, 60, 20)

    def test_an_unbalanced_exit_is_counted_not_crashed(self) -> None:
        m = Machine()
        m.leave()
        assert m.counter(OFF_UNBALANCED) == 1
        assert m.counter(OFF_DEPTH) == 0
        m.scope(SITE_SHADOW, 100)  # and the next scope still measures
        assert m.slot(SITE_SHADOW) == (1, 100, 100)

    def test_overflowing_the_nesting_stack_stays_paired(self) -> None:
        """The regression that matters: a scope too deep to record still occupies a level, so its
        own exit unwinds it rather than closing the frame below."""
        m = Machine()
        depth = STACK_CAPACITY + 4
        for _ in range(depth):
            m.enter(SITE_VIEWS)
            m.clock += 1
        assert m.counter(OFF_OVERFLOW) == 4
        for _ in range(depth):
            m.leave()
            m.clock += 1
        assert m.counter(OFF_DEPTH) == 0
        # The outermost scope is the one whose numbers must survive: it was recorded, and its
        # exclusive time must not have been corrupted by the four that were not.
        calls, inclusive, exclusive = m.slot(SITE_VIEWS)
        assert calls == STACK_CAPACITY
        assert inclusive > 0
        # And a fresh scope after the whole unwind measures cleanly.
        m.scope(SITE_SHADOW, 100)
        assert m.slot(SITE_SHADOW) == (1, 100, 100)

    def test_the_table_fills_gracefully(self) -> None:
        m = Machine()
        for index in range(SLOT_CAPACITY + 8):
            m.scope(0x00B00000 + index * 4, 1)
        assert m.counter(OFF_SLOTS_USED) == SLOT_CAPACITY
        assert m.counter(OFF_TABLE_FULL) >= 8
        assert m.counter(OFF_DEPTH) == 0
