"""Tests for the perf-scope-skip patch.

Two routines, both executed here rather than only disassembled. The gate is four instructions and
all four are control flow, so :class:`TestTheGateRuns` checks *where it lands* for each of the
three cases the constructor can be in, and that it lands there without disturbing the two registers
the body is about to use. :class:`TestTheProbeRuns` drives `GetProcAddress` and
`D3DPERF_GetStatus` from Python so the "no profiler", "no such export" and "PIX is attached" paths
are all reachable.

:class:`TestComposition` is the invariant that made this patch's anchors move: the two render-scope
patches hook the same function nine bytes apart, and an anchor reaching into the other's hook makes
them refuse each other in one order and not the other. It is checked mechanically - by applying one
and asking whether the other's anchors still read what they claim - rather than by eye.
"""

from __future__ import annotations

import struct

import pytest

from sage_ini.engine import STOCK
from sage_patch.addresses import (
    D3DPERF_MODULE_HANDLE,
    D3DPERF_SET_OPTIONS_PTR,
    D3DPERF_SETOPTIONS_STORE,
    D3DPERF_SETOPTIONS_STORE_ENTRY,
    D3DPERF_SETOPTIONS_STORE_RESUME,
    GET_PROC_ADDRESS_IAT,
    PERF_SCOPE_CTOR,
    PERF_SCOPE_CTOR_ENTRY,
    PERF_SCOPE_DTOR,
    PERF_SCOPE_DTOR_ENTRY,
    PERF_SCOPE_NULL_EXIT,
    PERF_SCOPE_NULL_EXIT_BYTES,
    PERF_SCOPE_NULL_GATE,
    PERF_SCOPE_NULL_GATE_ENTRY,
    PERF_SCOPE_NULL_GATE_RESUME,
)
from sage_patch.patcher import apply_patches
from sage_patch.patches.perf_scope_skip import (
    ANCHORS,
    BLOCK_MAGIC,
    CODE_OFFSET,
    GETSTATUS_NAME,
    OFF_ENABLED,
    OFF_PROBED,
    SECTION_NAME,
    PerfScopeSkipPatch,
    build_code,
    gate_va,
    probe_va,
)
from sage_patch.patches.perf_stage_readout import ANCHORS as READOUT_ANCHORS
from sage_patch.patches.perf_stage_readout import PerfStageReadoutPatch
from sage_patch.registry import PATCHES
from sage_patch.utils import find_section, va_to_offset

from .synthetic import perf_scope_skip_image

BASE = 0x00F00000
_GETPROC = 0x00E10000  # the GetProcAddress stand-in
_GETSTATUS = 0x00E20000  # the D3DPERF_GetStatus stand-in
_STACK = 0x00200000
_STACK_SIZE = 0x10000
_SENTINEL = 0x00DEAD00
_D3D9_HANDLE = 0x6A000000


@pytest.fixture
def image() -> bytearray:
    return perf_scope_skip_image()


@pytest.fixture
def patched(image: bytearray) -> bytearray:
    PerfScopeSkipPatch().apply(image)
    return image


class TestRegistration:
    def test_registered_and_stable(self) -> None:
        assert PATCHES["perf-scope-skip"] is PerfScopeSkipPatch
        assert PerfScopeSkipPatch.author == "officialNecro"
        assert PerfScopeSkipPatch.experimental is False
        assert ".experimental." not in PerfScopeSkipPatch.__module__

    def test_changes_no_ini_surface(self) -> None:
        assert PerfScopeSkipPatch().ini_surface() is STOCK

    def test_takes_no_parameters(self) -> None:
        assert PerfScopeSkipPatch().options() == {}


class TestTheSiteIsWhatItClaims:
    def test_the_gate_is_the_engines_own_null_branch(self) -> None:
        """Six bytes of `je rel32`, and its target is the do-nothing exit the patch reuses."""
        assert PERF_SCOPE_NULL_GATE_ENTRY[:2] == b"\x0f\x84"
        displacement = struct.unpack_from("<i", PERF_SCOPE_NULL_GATE_ENTRY, 2)[0]
        assert PERF_SCOPE_NULL_GATE + 6 + displacement == PERF_SCOPE_NULL_EXIT
        assert PERF_SCOPE_NULL_GATE + 6 == PERF_SCOPE_NULL_GATE_RESUME

    def test_the_exit_returns_the_object_and_unwinds_the_push(self) -> None:
        # mov eax, esi / pop esi / ret 0xC -- the ABI a skipped scope needs, already written.
        assert PERF_SCOPE_NULL_EXIT_BYTES == bytes.fromhex("8bc65ec20c00")

    def test_the_probe_displaces_a_store_it_re_runs(self) -> None:
        assert D3DPERF_SETOPTIONS_STORE_ENTRY[0] == 0xA3  # mov [imm32], eax
        assert struct.unpack_from("<I", D3DPERF_SETOPTIONS_STORE_ENTRY, 1)[0] == (
            D3DPERF_SET_OPTIONS_PTR
        )
        assert D3DPERF_SETOPTIONS_STORE + 5 == D3DPERF_SETOPTIONS_STORE_RESUME

    def test_the_block_carries_the_export_the_engine_never_resolves(self) -> None:
        assert GETSTATUS_NAME == b"D3DPERF_GetStatus\x00"
        block = build_code(BASE)[:CODE_OFFSET]
        assert struct.pack("<I", BLOCK_MAGIC) == b"PSSK"
        assert GETSTATUS_NAME in block
        assert block[OFF_ENABLED] == 0, "the default must be 'nobody is listening'"
        assert block[OFF_PROBED] == 0


class TestApply:
    def test_apply_and_verify(self, patched: bytearray) -> None:
        assert PerfScopeSkipPatch().verify(patched) == []
        assert PerfScopeSkipPatch.detect(patched) is not None

    def test_absent_from_a_stock_image(self, image: bytearray) -> None:
        assert PerfScopeSkipPatch().verify(image) != []
        assert PerfScopeSkipPatch.detect(image) is None

    def test_both_hooks_land_in_the_cave(self, patched: bytearray) -> None:
        located = find_section(patched, SECTION_NAME)
        assert located is not None
        section_va, _, _ = located
        for va, expected in (
            (PERF_SCOPE_NULL_GATE, gate_va(section_va)),
            (D3DPERF_SETOPTIONS_STORE, probe_va(section_va)),
        ):
            off = va_to_offset(patched, va)
            assert off is not None
            assert patched[off] == 0xE9
            assert va + 5 + struct.unpack_from("<i", patched, off + 1)[0] == expected

    def test_the_sixth_gate_byte_is_a_nop(self, patched: bytearray) -> None:
        off = va_to_offset(patched, PERF_SCOPE_NULL_GATE)
        assert off is not None
        assert patched[off + 5] == 0x90

    def test_refuses_a_build_whose_resolve_differs(self, image: bytearray) -> None:
        off = va_to_offset(image, D3DPERF_SETOPTIONS_STORE)
        assert off is not None
        image[off + 1] = 0xFF
        with pytest.raises(ValueError, match="D3DPERF resolve"):
            PerfScopeSkipPatch().apply(image)

    def test_applying_twice_raises(self, patched: bytearray) -> None:
        with pytest.raises(ValueError):
            PerfScopeSkipPatch().apply(patched)

    def test_round_trips_through_the_file_pipeline(self, tmp_path, image: bytearray) -> None:
        source = tmp_path / "game.dat"
        source.write_bytes(bytes(image))
        out = apply_patches(source, [PerfScopeSkipPatch()], tmp_path / "out.dat")
        assert PerfScopeSkipPatch().verify(out.read_bytes()) == []


class TestComposition:
    """The two render-scope patches hook the same function nine bytes apart.

    `perf-stage-readout` takes `0x00517690`..`0x00517695` and the destructor; this one takes
    `0x00517699`..`0x0051769E` and a site in the D3D init. Neither may *read* a byte the other
    writes, or the pair applies in one order and refuses in the other - which is what the first
    build of this patch did.
    """

    #: Every hook either patch installs, as ``{va: the stock bytes it replaces}``. Taken from
    #: `addresses` rather than from a diff, because a diff under-reports: a replacement byte
    #: that happens to equal the byte it replaced is still a byte the site owns, and the whole
    #: question here is who owns which bytes.
    HOOKS = {
        PERF_SCOPE_CTOR: PERF_SCOPE_CTOR_ENTRY,
        PERF_SCOPE_DTOR: PERF_SCOPE_DTOR_ENTRY,
        PERF_SCOPE_NULL_GATE: PERF_SCOPE_NULL_GATE_ENTRY,
        D3DPERF_SETOPTIONS_STORE: D3DPERF_SETOPTIONS_STORE_ENTRY,
    }

    @classmethod
    def _written(cls, image: bytearray, patch) -> set[int]:
        """The virtual addresses ``patch`` overwrites in the existing image, not its new section.

        A site counts when the patch changed *any* byte of it, and then the whole declared site
        counts - see :attr:`HOOKS`.
        """
        before = bytes(image)
        working = bytearray(before)
        patch.apply(working)
        out: set[int] = set()
        for va, stock in cls.HOOKS.items():
            off = va_to_offset(before, va)
            if off is None:
                continue
            width = len(stock)
            assert bytes(before[off : off + width]) == stock, f"{va:#x} is not stock in the image"
            if bytes(working[off : off + width]) != stock:
                out |= {va + delta for delta in range(width)}
        return out

    @staticmethod
    def _anchor_range(anchors: dict[int, bytes]) -> set[int]:
        return {va + d for va, blob in anchors.items() for d in range(len(blob))}

    def test_neither_patch_anchors_on_what_the_other_writes(self, image: bytearray) -> None:
        skip_writes = self._written(image, PerfScopeSkipPatch())
        readout_writes = self._written(image, PerfStageReadoutPatch())
        assert skip_writes and readout_writes  # the check is vacuous if nothing was found
        assert not (skip_writes & self._anchor_range(READOUT_ANCHORS)), (
            "perf-scope-skip writes bytes perf-stage-readout anchors on"
        )
        assert not (readout_writes & self._anchor_range(ANCHORS)), (
            "perf-stage-readout writes bytes perf-scope-skip anchors on"
        )

    def test_neither_patch_writes_where_the_other_writes(self, image: bytearray) -> None:
        assert not (
            self._written(image, PerfScopeSkipPatch())
            & self._written(image, PerfStageReadoutPatch())
        )

    @pytest.mark.parametrize(
        "order",
        [
            (PerfScopeSkipPatch, PerfStageReadoutPatch),
            (PerfStageReadoutPatch, PerfScopeSkipPatch),
        ],
        ids=["skip-first", "readout-first"],
    )
    def test_applies_in_either_order(self, image: bytearray, order) -> None:
        for cls in order:
            cls().apply(image)
        for cls in order:
            assert cls().verify(image) == [], f"{cls.name} did not survive {order}"


# Executing the two routines


class Machine:
    """The cave, running, with `GetProcAddress` and `D3DPERF_GetStatus` driven from Python."""

    def __init__(self, *, resolves: bool = True, status: int = 0) -> None:
        unicorn = pytest.importorskip("unicorn")
        self.regs = pytest.importorskip("unicorn.x86_const")
        self.unicorn = unicorn
        self.uc = unicorn.Uc(unicorn.UC_ARCH_X86, unicorn.UC_MODE_32)
        self.resolves = resolves
        self.status = status
        self.landed: int | None = None

        code = build_code(BASE)
        self.uc.mem_map(BASE, (len(code) + 0xFFF) & ~0xFFF)
        self.uc.mem_write(BASE, code)
        self.uc.mem_map(_STACK, _STACK_SIZE)
        for page in (0x00517000, 0x00525000, _GETPROC, _GETSTATUS):
            self.uc.mem_map(page, 0x1000)
            self.uc.mem_write(page, b"\xc3" * 0x1000)
        for va in (D3DPERF_MODULE_HANDLE, GET_PROC_ADDRESS_IAT):
            page = va & ~0xFFF
            try:
                self.uc.mem_map(page, 0x1000)
            except unicorn.UcError:
                pass  # already mapped: the two live in different pages, but be order-independent
        self.uc.mem_write(D3DPERF_MODULE_HANDLE, struct.pack("<I", _D3D9_HANDLE))
        self.uc.mem_write(GET_PROC_ADDRESS_IAT, struct.pack("<I", _GETPROC))

        self.uc.hook_add(unicorn.UC_HOOK_CODE, self._getproc, begin=_GETPROC, end=_GETPROC + 4)
        self.uc.hook_add(
            unicorn.UC_HOOK_CODE, self._getstatus, begin=_GETSTATUS, end=_GETSTATUS + 4
        )
        for target in (
            PERF_SCOPE_NULL_EXIT,
            PERF_SCOPE_NULL_GATE_RESUME,
            D3DPERF_SETOPTIONS_STORE_RESUME,
        ):
            self.uc.hook_add(unicorn.UC_HOOK_CODE, self._land, begin=target, end=target)

    def _land(self, uc, address, size, user_data) -> None:  # noqa: ANN001, ARG002
        self.landed = address
        uc.emu_stop()

    def _getproc(self, uc, address, size, user_data) -> None:  # noqa: ANN001, ARG002
        esp = uc.reg_read(self.regs.UC_X86_REG_ESP)
        ret, handle, name_ptr = struct.unpack("<III", uc.mem_read(esp, 12))
        assert handle == _D3D9_HANDLE, "the probe asked the wrong module"
        name = bytes(uc.mem_read(name_ptr, len(GETSTATUS_NAME)))
        assert name == GETSTATUS_NAME, f"the probe asked for {name!r}"
        uc.reg_write(self.regs.UC_X86_REG_EAX, _GETSTATUS if self.resolves else 0)
        uc.reg_write(self.regs.UC_X86_REG_ESP, esp + 12)  # stdcall: 2 arguments
        uc.reg_write(self.regs.UC_X86_REG_EIP, ret)

    def _getstatus(self, uc, address, size, user_data) -> None:  # noqa: ANN001, ARG002
        esp = uc.reg_read(self.regs.UC_X86_REG_ESP)
        ret = struct.unpack("<I", uc.mem_read(esp, 4))[0]
        uc.reg_write(self.regs.UC_X86_REG_EAX, self.status)
        uc.reg_write(self.regs.UC_X86_REG_ESP, esp + 4)  # stdcall, no arguments
        uc.reg_write(self.regs.UC_X86_REG_EIP, ret)

    def byte(self, offset: int) -> int:
        return self.uc.mem_read(BASE + offset, 1)[0]

    def set_enabled(self, value: int) -> None:
        self.uc.mem_write(BASE + OFF_ENABLED, bytes([value]))

    def run_gate(self, *, zero_flag: bool, eax: int = 0x11111111, esi: int = 0x22222222) -> int:
        """The gate, entered as the constructor enters it. Returns where it jumped."""
        self.uc.reg_write(self.regs.UC_X86_REG_ESP, _STACK + _STACK_SIZE - 0x100)
        self.uc.reg_write(self.regs.UC_X86_REG_EAX, eax)
        self.uc.reg_write(self.regs.UC_X86_REG_ESI, esi)
        flags = self.uc.reg_read(self.regs.UC_X86_REG_EFLAGS)
        flags = (flags | 0x40) if zero_flag else (flags & ~0x40)
        self.uc.reg_write(self.regs.UC_X86_REG_EFLAGS, flags)
        self.landed = None
        self.uc.emu_start(gate_va(BASE), 0xFFFFFFFF, count=16)
        assert self.landed is not None, "the gate did not reach either exit"
        return self.landed

    def run_probe(self, eax: int = 0x33333333) -> int:
        self.uc.reg_write(self.regs.UC_X86_REG_ESP, _STACK + _STACK_SIZE - 0x100)
        self.uc.reg_write(self.regs.UC_X86_REG_EAX, eax)
        self.landed = None
        self.uc.emu_start(probe_va(BASE), 0xFFFFFFFF, count=64)
        assert self.landed is not None, "the probe did not reach its resume point"
        return self.landed


class TestTheGateRuns:
    def test_a_null_name_still_does_nothing(self) -> None:
        """The branch being replaced has to keep its own meaning."""
        for enabled in (0, 1):
            m = Machine()
            m.set_enabled(enabled)
            assert m.run_gate(zero_flag=True) == PERF_SCOPE_NULL_EXIT

    def test_nobody_listening_takes_the_exit(self) -> None:
        m = Machine()
        m.set_enabled(0)
        assert m.run_gate(zero_flag=False) == PERF_SCOPE_NULL_EXIT

    def test_a_profiler_listening_runs_the_body(self) -> None:
        m = Machine()
        m.set_enabled(1)
        assert m.run_gate(zero_flag=False) == PERF_SCOPE_NULL_GATE_RESUME

    def test_the_gate_preserves_the_registers_the_body_uses(self) -> None:
        """`eax` is the name and `esi` is the object; the body pushes both three instructions on."""
        for enabled, zero in ((0, False), (1, False), (0, True)):
            m = Machine()
            m.set_enabled(enabled)
            m.run_gate(zero_flag=zero, eax=0xABCDEF01, esi=0x0BADF00D)
            assert m.uc.reg_read(m.regs.UC_X86_REG_EAX) == 0xABCDEF01
            assert m.uc.reg_read(m.regs.UC_X86_REG_ESI) == 0x0BADF00D

    def test_the_gate_leaves_the_stack_alone(self) -> None:
        m = Machine()
        m.set_enabled(0)
        before = _STACK + _STACK_SIZE - 0x100
        m.run_gate(zero_flag=False)
        assert m.uc.reg_read(m.regs.UC_X86_REG_ESP) == before


class TestTheProbeRuns:
    def test_it_re_runs_the_displaced_store(self) -> None:
        m = Machine()
        m.run_probe(eax=0x44556677)
        stored = struct.unpack("<I", m.uc.mem_read(D3DPERF_SET_OPTIONS_PTR, 4))[0]
        assert stored == 0x44556677

    def test_a_profiler_answering_turns_the_names_back_on(self) -> None:
        m = Machine(resolves=True, status=1)
        assert m.run_probe() == D3DPERF_SETOPTIONS_STORE_RESUME
        assert m.byte(OFF_ENABLED) == 1
        assert m.byte(OFF_PROBED) == 1

    def test_no_profiler_leaves_them_off(self) -> None:
        m = Machine(resolves=True, status=0)
        m.set_enabled(1)  # prove the probe writes the answer rather than only ever setting it
        assert m.run_probe() == D3DPERF_SETOPTIONS_STORE_RESUME
        assert m.byte(OFF_ENABLED) == 0
        assert m.byte(OFF_PROBED) == 1

    def test_a_d3d9_without_the_export_takes_the_fast_path(self) -> None:
        """DXVK, or any replacement that omits it: the answer is 'not listening', not a crash."""
        m = Machine(resolves=False)
        m.set_enabled(1)
        assert m.run_probe() == D3DPERF_SETOPTIONS_STORE_RESUME
        assert m.byte(OFF_ENABLED) == 0
        assert m.byte(OFF_PROBED) == 1

    def test_the_probe_preserves_everything(self) -> None:
        m = Machine(resolves=True, status=1)
        regs = m.regs
        seeds = {
            regs.UC_X86_REG_EBX: 0x1234ABCD,
            regs.UC_X86_REG_ECX: 0x2345BCDE,
            regs.UC_X86_REG_EDX: 0x3456CDEF,
            regs.UC_X86_REG_ESI: 0x4567DEF0,
            regs.UC_X86_REG_EDI: 0x5678EF01,
            regs.UC_X86_REG_EBP: 0x6789F012,
        }
        for reg, value in seeds.items():
            m.uc.reg_write(reg, value)
        esp_before = _STACK + _STACK_SIZE - 0x100
        m.run_probe(eax=0x7890ABCD)
        for reg, value in seeds.items():
            assert m.uc.reg_read(reg) == value
        assert m.uc.reg_read(regs.UC_X86_REG_EAX) == 0x7890ABCD
        assert m.uc.reg_read(regs.UC_X86_REG_ESP) == esp_before

    def test_probing_twice_is_idempotent(self) -> None:
        """Device reset re-runs the resolve."""
        m = Machine(resolves=True, status=1)
        m.run_probe()
        m.run_probe()
        assert m.byte(OFF_ENABLED) == 1
