"""Tests for the accel-module patch.

The hook is executed here, not only disassembled. :class:`Machine` runs it with `LoadLibraryA`,
`GetProcAddress` and `sage_accel_arm` driven from Python, so every way the module can be absent is
reachable, and each one is checked for what the engine sees afterwards: the pointer it will call,
the registers and the flags. The `je` at the resume reads flags the engine set *before* the hook,
so flags coming back unchanged is the property that matters most.

:class:`TestComposition` covers the neighbour: `perf-scope-skip` hooks the same function ninety
bytes further on.
"""

from __future__ import annotations

import struct

import pytest

from sage_accel.build import DLL_NAME as BUILT_DLL_NAME
from sage_accel.build import EXPORT_NAME as BUILT_EXPORT_NAME
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
    EXPORT_NAME,
    OFF_MODULE,
    OFF_STATE,
    SECTION_NAME,
    STATE_ARMED,
    STATE_DECLINED,
    STATE_NO_EXPORT,
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
_GETPROC = 0x00E20000
_ARM = 0x00E30000
_STACK = 0x00200000
_STACK_SIZE = 0x10000
_MODULE = 0x6B000000
_REAL = 0x6A012340  # the engine's own Direct3DCreate9
_WRAPPER = 0x6B001000  # what the module hands back


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

    def test_names_agree_with_the_builder(self) -> None:
        """The cave asks for what `python -m sage_accel build` produces, by the same names."""
        assert DLL_NAME == BUILT_DLL_NAME.encode() + b"\x00"
        assert EXPORT_NAME == BUILT_EXPORT_NAME.encode() + b"\x00"


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
        assert EXPORT_NAME in block
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
    """The hook, running, with the three calls it makes answered from Python."""

    def __init__(self, *, loads: bool = True, resolves: bool = True, answer: int = _WRAPPER):
        unicorn = pytest.importorskip("unicorn")
        self.regs = pytest.importorskip("unicorn.x86_const")
        self.uc = unicorn.Uc(unicorn.UC_ARCH_X86, unicorn.UC_MODE_32)
        self.loads, self.resolves, self.answer = loads, resolves, answer
        self.arm_calls: list[int] = []
        self.landed: int | None = None

        code = build_code(BASE)
        self.uc.mem_map(BASE, (len(code) + 0xFFF) & ~0xFFF)
        self.uc.mem_write(BASE, code)
        self.uc.mem_map(_STACK, _STACK_SIZE)
        for page in (0x00525000, _LOADLIB, _GETPROC, _ARM):
            self.uc.mem_map(page, 0x1000)
            self.uc.mem_write(page, b"\xc3" * 0x1000)
        for page in {LOAD_LIBRARY_A_IAT & ~0xFFF, DIRECT3D_CREATE9_PTR & ~0xFFF}:
            self.uc.mem_map(page, 0x1000)
        self.uc.mem_write(LOAD_LIBRARY_A_IAT, struct.pack("<I", _LOADLIB))
        self.uc.mem_write(GET_PROC_ADDRESS_IAT, struct.pack("<I", _GETPROC))

        self.uc.hook_add(unicorn.UC_HOOK_CODE, self._loadlib, begin=_LOADLIB, end=_LOADLIB)
        self.uc.hook_add(unicorn.UC_HOOK_CODE, self._getproc, begin=_GETPROC, end=_GETPROC)
        self.uc.hook_add(unicorn.UC_HOOK_CODE, self._arm, begin=_ARM, end=_ARM)
        resume = DIRECT3D_CREATE9_STORE_RESUME
        self.uc.hook_add(unicorn.UC_HOOK_CODE, self._land, begin=resume, end=resume)

    def _land(self, uc, address, size, user_data) -> None:  # noqa: ANN001, ARG002
        self.landed = address
        uc.emu_stop()

    def _return(self, value: int, pop: int) -> None:
        esp = self.uc.reg_read(self.regs.UC_X86_REG_ESP)
        ret = struct.unpack("<I", self.uc.mem_read(esp, 4))[0]
        self.uc.reg_write(self.regs.UC_X86_REG_EAX, value)
        self.uc.reg_write(self.regs.UC_X86_REG_ESP, esp + 4 + pop)
        self.uc.reg_write(self.regs.UC_X86_REG_EIP, ret)

    def _cstring(self, va: int) -> bytes:
        raw = bytes(self.uc.mem_read(va, 64))
        return raw[: raw.index(b"\x00") + 1]

    def _loadlib(self, uc, address, size, user_data) -> None:  # noqa: ANN001, ARG002
        esp = uc.reg_read(self.regs.UC_X86_REG_ESP)
        assert self._cstring(struct.unpack("<I", uc.mem_read(esp + 4, 4))[0]) == DLL_NAME
        self._return(_MODULE if self.loads else 0, 4)  # stdcall, one argument

    def _getproc(self, uc, address, size, user_data) -> None:  # noqa: ANN001, ARG002
        esp = uc.reg_read(self.regs.UC_X86_REG_ESP)
        module, name = struct.unpack("<II", uc.mem_read(esp + 4, 8))
        assert module == _MODULE, "resolved from the wrong module"
        assert self._cstring(name) == EXPORT_NAME
        self._return(_ARM if self.resolves else 0, 8)  # stdcall, two arguments

    def _arm(self, uc, address, size, user_data) -> None:  # noqa: ANN001, ARG002
        esp = uc.reg_read(self.regs.UC_X86_REG_ESP)
        self.arm_calls.append(struct.unpack("<I", uc.mem_read(esp + 4, 4))[0])
        self._return(self.answer, 0)  # cdecl: the caller pops

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
        out = {n: self.uc.reg_read(getattr(r, f"UC_X86_REG_{n.upper()}")) for n in self.entry}
        return out

    def pointer(self) -> int:
        return struct.unpack("<I", self.uc.mem_read(DIRECT3D_CREATE9_PTR, 4))[0]

    def byte(self, offset: int) -> int:
        return self.uc.mem_read(BASE + offset, 1)[0]

    def dword(self, offset: int) -> int:
        return struct.unpack("<I", self.uc.mem_read(BASE + offset, 4))[0]


class TestTheHookRuns:
    def test_armed_the_engine_calls_the_module(self) -> None:
        m = Machine()
        m.run()
        assert m.arm_calls == [_REAL], "the module must be handed the engine's own pointer"
        assert m.pointer() == _WRAPPER
        assert m.byte(OFF_STATE) == STATE_ARMED
        assert m.dword(OFF_MODULE) == _MODULE

    @pytest.mark.parametrize(
        ("machine", "state"),
        [
            ({"loads": False}, STATE_NO_MODULE),
            ({"resolves": False}, STATE_NO_EXPORT),
            ({"answer": 0}, STATE_DECLINED),
        ],
        ids=["no-dll", "no-export", "declined"],
    )
    def test_every_absence_leaves_the_stock_pointer(self, machine, state: int) -> None:
        m = Machine(**machine)
        m.run()
        assert m.pointer() == _REAL
        assert m.byte(OFF_STATE) == state

    @pytest.mark.parametrize("machine", [{}, {"loads": False}, {"resolves": False}, {"answer": 0}])
    def test_registers_and_flags_come_back_untouched(self, machine) -> None:
        m = Machine(**machine)
        out = m.run()
        assert out == m.entry

    def test_a_failed_resolve_still_takes_the_engines_branch(self) -> None:
        """The engine resolved nothing: eax = 0 and ZF set. The store is re-run (writing 0), the
        module is still asked, and the `je` must still see ZF."""
        m = Machine(answer=0)
        out = m.run(zero_flag=True)
        assert out["eflags"] & 0x40
        assert m.pointer() == 0
        assert m.arm_calls == [0]
