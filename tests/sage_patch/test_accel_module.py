"""Tests for the accel-module patch.

The hook is executed here, not only disassembled. :class:`Machine` runs it with `LoadLibraryA`
answered from Python, so both outcomes are reachable, and each one is checked for what the engine
sees afterwards: the pointer it will call, the registers and the flags. The `je` at the resume reads
flags the engine set *before* the hook, so flags coming back unchanged is the property that matters
most.

:class:`TestComposition` covers the neighbour: `perf-scope-skip` hooks the same function ninety
bytes further on.
"""

from __future__ import annotations

import struct

import pytest

from sage_ini.engine import STOCK
from sage_patch.addresses import (
    DIRECT3D_CREATE9_PTR,
    DIRECT3D_CREATE9_RESOLVE,
    DIRECT3D_CREATE9_RESOLVE_BYTES,
    DIRECT3D_CREATE9_STORE,
    DIRECT3D_CREATE9_STORE_ENTRY,
    DIRECT3D_CREATE9_STORE_RESUME,
    GET_PROC_ADDRESS_IAT,
    LOAD_LIBRARY_A_IAT,
)
from sage_patch.patcher import apply_patches
from sage_patch.patches.experimental.accel_module import (
    ANCHORS,
    BLOCK_MAGIC,
    CODE_OFFSET,
    DLL_NAME,
    INIT_NAME,
    OFF_MODULE,
    OFF_STATE,
    SECTION_NAME,
    STATE_INCOMPATIBLE,
    STATE_INIT_FAILED,
    STATE_LOADED,
    STATE_NO_MODULE,
    STATE_NOT_REACHED,
    AccelModulePatch,
    build_code,
    hook_va,
)
from sage_patch.patches.perf_scope_skip import PerfScopeSkipPatch
from sage_patch.patches.perf_stage_readout import PerfStageReadoutPatch
from sage_patch.registry import PATCHES
from sage_patch.utils import find_section, va_to_offset

from .synthetic import accel_module_image

BASE = 0x00F00000
_LOADLIB = 0x00E10000
_GETPROC = 0x00E10100
_INITIALIZE = 0x00E10200
_STACK = 0x00200000
_STACK_SIZE = 0x10000
_MODULE = 0x6B000000
_REAL = 0x6A012340  # the engine's own Direct3DCreate9


@pytest.fixture
def image() -> bytearray:
    return accel_module_image()


@pytest.fixture
def patched(image: bytearray) -> bytearray:
    AccelModulePatch().apply(image)
    return image


class TestRegistration:
    def test_registered_as_experimental(self) -> None:
        assert PATCHES["accel-module"] is AccelModulePatch
        assert AccelModulePatch.experimental is True
        assert ".experimental." in AccelModulePatch.__module__

    def test_credits_both_authors(self) -> None:
        assert AccelModulePatch.author == "officialNecro"
        credit = AccelModulePatch().credit
        assert "officialNecro" in credit
        assert "OH1A" in credit

    def test_changes_no_ini_surface(self) -> None:
        assert AccelModulePatch().ini_surface() is STOCK

    def test_takes_no_parameters(self) -> None:
        assert AccelModulePatch().options() == {}

    def test_loads_the_accelerators_own_dll(self) -> None:
        assert DLL_NAME == b"pysage_accel.dll\x00"


class TestTheSiteIsWhatItClaims:
    def test_the_hook_displaces_the_store_of_the_resolved_pointer(self) -> None:
        assert DIRECT3D_CREATE9_STORE_ENTRY[0] == 0xA3  # mov [imm32], eax
        assert struct.unpack_from("<I", DIRECT3D_CREATE9_STORE_ENTRY, 1)[0] == (
            DIRECT3D_CREATE9_PTR
        )
        assert DIRECT3D_CREATE9_STORE + 5 == DIRECT3D_CREATE9_STORE_RESUME

    def test_the_anchor_covers_the_compare_the_store_and_the_branch(self) -> None:
        """`push name / push eax / call esi / cmp eax, ebx / <store> / je` - the `je` reads the
        compare's flags across the store, which is the whole reason the cave saves flags."""
        start = DIRECT3D_CREATE9_STORE - DIRECT3D_CREATE9_RESOLVE
        assert DIRECT3D_CREATE9_RESOLVE_BYTES[start - 2 : start] == bytes.fromhex("3bc3")
        assert DIRECT3D_CREATE9_RESOLVE_BYTES[start : start + 5] == DIRECT3D_CREATE9_STORE_ENTRY
        assert DIRECT3D_CREATE9_RESOLVE_BYTES[start + 5] == 0x74  # je rel8
        assert ANCHORS == {DIRECT3D_CREATE9_RESOLVE: DIRECT3D_CREATE9_RESOLVE_BYTES}

    def test_the_block(self) -> None:
        block = build_code(BASE)[:CODE_OFFSET]
        assert struct.pack("<I", BLOCK_MAGIC) == b"SACL"
        assert DLL_NAME in block
        assert block[OFF_STATE] == STATE_NOT_REACHED


class TestApply:
    def test_apply_and_verify(self, patched: bytearray) -> None:
        assert AccelModulePatch().verify(patched) == []
        assert AccelModulePatch.detect(patched) is not None

    def test_absent_from_a_stock_image(self, image: bytearray) -> None:
        assert AccelModulePatch().verify(image) != []
        assert AccelModulePatch.detect(image) is None

    def test_the_hook_lands_in_the_cave(self, patched: bytearray) -> None:
        located = find_section(patched, SECTION_NAME)
        assert located is not None
        off = va_to_offset(patched, DIRECT3D_CREATE9_STORE)
        assert off is not None
        assert patched[off] == 0xE9
        target = DIRECT3D_CREATE9_STORE + 5 + struct.unpack_from("<i", patched, off + 1)[0]
        assert target == hook_va(located[0])

    def test_refuses_a_build_whose_resolve_differs(self, image: bytearray) -> None:
        off = va_to_offset(image, DIRECT3D_CREATE9_RESOLVE)
        assert off is not None
        image[off + 8] = 0x90  # the `cmp eax, ebx` the resume depends on
        with pytest.raises(ValueError, match="Direct3DCreate9 resolve"):
            AccelModulePatch().apply(image)

    def test_applying_twice_raises(self, patched: bytearray) -> None:
        with pytest.raises(ValueError):
            AccelModulePatch().apply(patched)

    def test_round_trips_through_the_file_pipeline(self, tmp_path, image: bytearray) -> None:
        source = tmp_path / "game.dat"
        source.write_bytes(bytes(image))
        out = apply_patches(source, [AccelModulePatch()], tmp_path / "out.dat")
        assert AccelModulePatch().verify(out.read_bytes()) == []


class TestComposition:
    ORDERS = [
        (AccelModulePatch, PerfScopeSkipPatch, PerfStageReadoutPatch),
        (PerfScopeSkipPatch, PerfStageReadoutPatch, AccelModulePatch),
        (PerfStageReadoutPatch, AccelModulePatch, PerfScopeSkipPatch),
    ]

    @pytest.mark.parametrize("order", ORDERS, ids=["accel-first", "accel-last", "accel-middle"])
    def test_applies_with_the_render_scope_patches_in_any_order(
        self, image: bytearray, order
    ) -> None:
        for cls in order:
            cls().apply(image)
        for cls in order:
            assert cls().verify(image) == [], f"{cls.name} did not survive {order}"


# Executing the hook


class Machine:
    """The hook, running, with `LoadLibraryA` answered from Python."""

    def __init__(self, *, loads: bool = True, compatible: bool = True, init_result: int = 1):
        unicorn = pytest.importorskip("unicorn")
        self.regs = pytest.importorskip("unicorn.x86_const")
        self.uc = unicorn.Uc(unicorn.UC_ARCH_X86, unicorn.UC_MODE_32)
        self.loads = loads
        self.compatible = compatible
        self.init_result = init_result
        self.initialized = 0
        self.loaded: list[bytes] = []
        self.landed: int | None = None

        code = build_code(BASE)
        self.uc.mem_map(BASE, (len(code) + 0xFFF) & ~0xFFF)
        self.uc.mem_write(BASE, code)
        self.uc.mem_map(_STACK, _STACK_SIZE)
        for page in (0x00525000, _LOADLIB):
            self.uc.mem_map(page, 0x1000)
            self.uc.mem_write(page, b"\xc3" * 0x1000)
        for page in {LOAD_LIBRARY_A_IAT & ~0xFFF, DIRECT3D_CREATE9_PTR & ~0xFFF}:
            self.uc.mem_map(page, 0x1000)
        self.uc.mem_write(LOAD_LIBRARY_A_IAT, struct.pack("<I", _LOADLIB))

        self.uc.mem_write(GET_PROC_ADDRESS_IAT, struct.pack("<I", _GETPROC))
        self.uc.hook_add(unicorn.UC_HOOK_CODE, self._getproc, begin=_GETPROC, end=_GETPROC)
        self.uc.hook_add(unicorn.UC_HOOK_CODE, self._initialize, begin=_INITIALIZE, end=_INITIALIZE)
        self.uc.hook_add(unicorn.UC_HOOK_CODE, self._loadlib, begin=_LOADLIB, end=_LOADLIB)
        resume = DIRECT3D_CREATE9_STORE_RESUME
        self.uc.hook_add(unicorn.UC_HOOK_CODE, self._land, begin=resume, end=resume)

    def _land(self, uc, address, size, user_data) -> None:  # noqa: ANN001, ARG002
        self.landed = address
        uc.emu_stop()

    def _loadlib(self, uc, address, size, user_data) -> None:  # noqa: ANN001, ARG002
        r = self.regs
        esp = uc.reg_read(r.UC_X86_REG_ESP)
        ret, name_va = struct.unpack("<II", uc.mem_read(esp, 8))
        raw = bytes(uc.mem_read(name_va, 64))
        self.loaded.append(raw[: raw.index(b"\x00") + 1])
        uc.reg_write(r.UC_X86_REG_EAX, _MODULE if self.loads else 0)
        uc.reg_write(r.UC_X86_REG_ESP, esp + 8)  # stdcall, one argument
        uc.reg_write(r.UC_X86_REG_EIP, ret)

    def _getproc(self, uc, address, size, user_data) -> None:  # noqa: ANN001, ARG002
        r = self.regs
        esp = uc.reg_read(r.UC_X86_REG_ESP)
        ret, module, name_va = struct.unpack("<III", uc.mem_read(esp, 12))
        assert module == _MODULE
        assert bytes(uc.mem_read(name_va, len(INIT_NAME))) == INIT_NAME
        uc.reg_write(r.UC_X86_REG_EAX, _INITIALIZE if self.compatible else 0)
        uc.reg_write(r.UC_X86_REG_ESP, esp + 12)
        uc.reg_write(r.UC_X86_REG_EIP, ret)

    def _initialize(self, uc, address, size, user_data) -> None:  # noqa: ANN001, ARG002
        self.initialized += 1
        r = self.regs
        esp = uc.reg_read(r.UC_X86_REG_ESP)
        ret = struct.unpack("<I", uc.mem_read(esp, 4))[0]
        # Simulate volatile registers clobbered by a real native initialization.
        uc.reg_write(r.UC_X86_REG_EAX, self.init_result)
        uc.reg_write(r.UC_X86_REG_ECX, 0xDEADBEEF)
        uc.reg_write(r.UC_X86_REG_EDX, 0xBADF00D)
        uc.reg_write(r.UC_X86_REG_ESP, esp + 4)
        uc.reg_write(r.UC_X86_REG_EIP, ret)

    def run(self, *, zero_flag: bool = False) -> dict[str, int]:
        """Enter the hook as the engine does: the real pointer in eax, ebx = 0, the flags of
        `cmp eax, ebx`. Returns the registers at the resume."""
        r = self.regs
        esp = _STACK + _STACK_SIZE - 0x100
        entry = {
            "eax": 0 if zero_flag else _REAL,
            "ebx": 0,
            "ecx": 0x11111111,
            "edx": 0x22222222,
            "esi": 0x33333333,
            "edi": 0x44444444,
            "ebp": 0x55555555,
        }
        for name, value in entry.items():
            self.uc.reg_write(getattr(r, f"UC_X86_REG_{name.upper()}"), value)
        self.uc.reg_write(r.UC_X86_REG_ESP, esp)
        flags = self.uc.reg_read(r.UC_X86_REG_EFLAGS)
        flags = (flags | 0x40) if zero_flag else (flags & ~0x40)
        self.uc.reg_write(r.UC_X86_REG_EFLAGS, flags)
        self.entry = dict(entry, esp=esp, eflags=flags)

        self.uc.emu_start(hook_va(BASE), 0xFFFFFFFF, count=200)
        assert self.landed == DIRECT3D_CREATE9_STORE_RESUME, "the hook did not reach the resume"
        return {n: self.uc.reg_read(getattr(r, f"UC_X86_REG_{n.upper()}")) for n in self.entry}

    def pointer(self) -> int:
        return struct.unpack("<I", self.uc.mem_read(DIRECT3D_CREATE9_PTR, 4))[0]

    def byte(self, offset: int) -> int:
        return self.uc.mem_read(BASE + offset, 1)[0]

    def dword(self, offset: int) -> int:
        return struct.unpack("<I", self.uc.mem_read(BASE + offset, 4))[0]


class TestTheHookRuns:
    def test_the_dll_is_loaded_and_the_engine_keeps_its_pointer(self) -> None:
        m = Machine()
        m.run()
        assert m.loaded == [DLL_NAME]
        assert m.initialized == 1
        assert m.pointer() == _REAL
        assert m.byte(OFF_STATE) == STATE_LOADED
        assert m.dword(OFF_MODULE) == _MODULE

    def test_a_missing_dll_is_recorded(self) -> None:
        m = Machine(loads=False)
        m.run()
        assert m.pointer() == _REAL
        assert m.byte(OFF_STATE) == STATE_NO_MODULE
        assert m.dword(OFF_MODULE) == 0

    @pytest.mark.parametrize("loads", [True, False], ids=["loaded", "missing"])
    def test_registers_and_flags_come_back_untouched(self, loads: bool) -> None:
        m = Machine(loads=loads)
        out = m.run()
        assert out == m.entry

    def test_a_failed_resolve_still_takes_the_engines_branch(self) -> None:
        """The engine resolved nothing: eax = 0 and ZF set. The store is re-run (writing 0), and
        the `je` must still see ZF."""
        m = Machine()
        out = m.run(zero_flag=True)
        assert out["eflags"] & 0x40
        assert m.pointer() == 0


@pytest.mark.parametrize(
    ("compatible", "result", "state"),
    [(False, 1, STATE_INCOMPATIBLE), (True, 0, STATE_INIT_FAILED), (True, 2, STATE_INIT_FAILED)],
)
def test_initialization_failure_preserves_engine(compatible, result, state) -> None:
    m = Machine(compatible=compatible, init_result=result)
    out = m.run()
    assert out == m.entry
    assert m.byte(OFF_STATE) == state
    assert m.initialized == int(compatible)
    assert m.pointer() == _REAL
