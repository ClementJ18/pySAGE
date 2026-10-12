"""Execute the castle-prefab caves with optional Unicorn engine stand-ins."""

from __future__ import annotations

import struct

import pytest

from sage_patch import addresses as ad
from sage_patch.asm import Asm
from sage_patch.patches.experimental import castle_prefab as cp
from sage_patch.utils import u32

pytest.importorskip("unicorn", reason="the cave emulator requires the patch extra")
from unicorn import UC_ARCH_X86, UC_HOOK_CODE, UC_MODE_32, Uc  # noqa: E402
from unicorn.x86_const import (  # noqa: E402
    UC_X86_REG_EAX,
    UC_X86_REG_EBP,
    UC_X86_REG_EBX,
    UC_X86_REG_ECX,
    UC_X86_REG_EDI,
    UC_X86_REG_EIP,
    UC_X86_REG_ESI,
    UC_X86_REG_ESP,
)


class Engine:
    """Engine callees stand in for validation; the actual cave runs as x86."""

    BASE = 0x1000000
    OBJECT = 0x2001000
    BEHAVIOR = 0x2002000
    ACTION = 0x2003000
    STOP = 0x200F000
    STACK = 0x3008000

    def __init__(self) -> None:
        self.cpu = Uc(UC_ARCH_X86, UC_MODE_32)
        pages = {
            va & ~0xFFF
            for va in (
                *cp.HOOKS,
                *cp.ANCHORS,
                ad.SCRIPT_RESOLVE_UNIT_PARAMETER,
                ad.NAME_KEY_FROM_STRING,
                ad.SCRIPT_NAMED_BASE_UNPACK,
                ad.CASTLE_BEHAVIOR_START_UNPACK,
                ad.THE_SCRIPT_ENGINE,
                ad.THE_NAME_KEY_GENERATOR,
                ad.WORLDBUILDER_ASCIISTRING_SET,
                0x40618C,
            )
        }
        for page in pages:
            self.cpu.mem_map(page, 0x1000)
        self.cpu.mem_map(self.BASE, 0x10000)
        self.cpu.mem_map(0x2000000, 0x10000)
        self.cpu.mem_map(0x3000000, 0x10000)
        self.a = cp._emit(self.BASE)
        self.cpu.mem_write(self.BASE, self.a.finish())
        self.write(self.BEHAVIOR + 8, self.OBJECT)
        self.write(self.OBJECT + ad.OBJECT_ID, 42)
        self.write(self.ACTION + ad.SCRIPT_ACTION_PARAM_COUNT, 3)
        for i, kind in enumerate(cp.PARAMETER_TYPES):
            param = self.ACTION + 0x100 + i * 0x40
            self.write(self.ACTION + ad.SCRIPT_ACTION_PARAM_ARRAY + i * 4, param)
            self.write(param, kind)
            self.write(param + ad.SCRIPT_PARAMETER_STRING, self.ACTION + 0x400 + i * 0x40)
            self.cpu.mem_write(self.ACTION + 0x408 + i * 0x40, b"Prefab\0")
        self.accept = True
        self.match = True
        self.instant = False
        self.free_flags: list[int] = []
        self.started = 0
        self.names: list[int] = []
        self.key = 1234
        self.cpu.hook_add(UC_HOOK_CODE, self._hook)
        # Stock helper's frame and call setup are reproduced, including its Parameter* arg.
        a = Asm(ad.SCRIPT_NAMED_BASE_UNPACK)
        a.emit(b"\x55\x8b\xec\x6a\x00\xff\x75\x10")
        a.emit(0xB9, u32(self.BEHAVIOR), 0xBF, u32(self.OBJECT))
        a.call_absolute(self.a.label_va("start"))
        a.emit(b"\x5d\xc2\x0c\x00")
        self.cpu.mem_write(ad.SCRIPT_NAMED_BASE_UNPACK, a.finish())
        # The real prologue builds a SEH frame. Model its stack footprint and deliberately
        # destroy ESI to exercise the late stock paths that cannot supply cleanup identity.
        a = Asm(ad.CASTLE_BEHAVIOR_UNPACK + 5)
        a.emit(b"\x55\x8b\xec\x83\xec\x10\x53\x56\x33\xf6")
        a.jmp_absolute(self.a.label_va("complete"))
        self.cpu.mem_write(ad.CASTLE_BEHAVIOR_UNPACK + 5, a.finish())
        self.cpu.mem_write(ad.CASTLE_BEHAVIOR_UNPACK_EPILOGUE + 5, b"\xc9\xc2\x04\x00")
        # Instant unpack invokes the wrapped actual-unpack entry while the pending context
        # still exists. Completion must clear persistent state, then the action clears pending.
        a = Asm(ad.CASTLE_BEHAVIOR_START_UNPACK)
        a.emit(b"\x6a\x01")
        a.call_absolute(self.a.label_va("unpack"))
        a.emit(b"\xc2\x08\x00")
        self.cpu.mem_write(ad.CASTLE_BEHAVIOR_START_UNPACK, a.finish())

    def write(self, addr: int, value: int) -> None:
        self.cpu.mem_write(addr, u32(value))

    def read(self, addr: int) -> int:
        return struct.unpack("<I", self.cpu.mem_read(addr, 4))[0]

    def _return(self, cleanup: int, result: int = 0) -> None:
        sp = self.cpu.reg_read(UC_X86_REG_ESP)
        self.cpu.reg_write(UC_X86_REG_EIP, self.read(sp))
        self.cpu.reg_write(UC_X86_REG_ESP, sp + 4 + cleanup)
        self.cpu.reg_write(UC_X86_REG_EAX, result)

    def _hook(self, cpu: Uc, addr: int, size: int, user: object) -> None:
        if addr in (self.STOP, ad.SCRIPT_ACTION_EPILOGUE):
            cpu.emu_stop()
        elif addr == ad.SCRIPT_RESOLVE_UNIT_PARAMETER:
            self._return(4, self.OBJECT)
        elif addr == ad.NAME_KEY_FROM_STRING:
            self._return(4, self.key)
        elif addr == ad.SCRIPT_NAMED_BASE_UNPACK:
            if not self.accept:
                self._return(12)
            elif not self.match:
                self.write(self.BASE + cp.PENDING_OFF, self.OBJECT + 4)
        elif addr == ad.CASTLE_BEHAVIOR_START_UNPACK:
            self.started += 1
            self.free_flags.append(self.read(cpu.reg_read(UC_X86_REG_ESP) + 4))
            self.names.append(self.read(self.BASE + cp.TABLE_OFF + 4))
            if not self.instant:
                self._return(8)
        elif addr == ad.CASTLE_BEHAVIOR_PREFAB_RESOLVER + 5:
            self._return(0, 99)  # exact stock continuation, with owner already loaded into ECX
        elif addr == ad.CASTLE_BEHAVIOR_DESTRUCTOR + 5:
            cpu.emu_stop()

    def run(self, label: str, *, arg: int | None = None) -> int:
        self.cpu.reg_write(UC_X86_REG_ESP, self.STACK)
        self.cpu.reg_write(UC_X86_REG_ECX, self.BEHAVIOR)
        self.cpu.reg_write(UC_X86_REG_ESI, self.ACTION)
        self.cpu.reg_write(UC_X86_REG_EDI, 0x22222222)
        self.cpu.reg_write(UC_X86_REG_EBX, 0x33333333)
        self.write(self.STACK, self.STOP)
        if arg is not None:
            self.write(self.STACK + 4, arg)
        self.cpu.emu_start(self.a.label_va(label), self.STOP, count=20000)
        return self.cpu.reg_read(UC_X86_REG_EAX)


@pytest.mark.parametrize("label,free", [("normal", 0), ("free", 1)])
def test_pending_latches_and_both_resolver_uses_keep_it(label: str, free: int) -> None:
    e = Engine()
    e.run(label)
    assert e.free_flags == [free]
    assert e.names == [e.key]
    assert e.read(e.BASE) == e.read(e.BASE + 4) == e.read(e.BASE + 8) == 0
    assert e.run("resolve") == e.key
    assert e.run("resolve") == e.key
    assert e.cpu.reg_read(UC_X86_REG_ESP) == e.STACK + 4
    e.run("unpack", arg=1)
    assert e.cpu.reg_read(UC_X86_REG_ESP) == e.STACK + 8
    assert e.read(e.BASE + cp.TABLE_OFF) == 0
    assert e.run("resolve") == 99


def test_immediate_cleanup_runs_before_pending_clear() -> None:
    e = Engine()
    e.instant = True
    e.run("free")
    assert e.started == 1
    assert e.read(e.BASE + cp.TABLE_OFF) == 0
    assert e.read(e.BASE) == 0


@pytest.mark.parametrize("accept,match", [(False, True), (True, False)])
def test_failed_validation_or_wrong_target_never_latches(accept: bool, match: bool) -> None:
    e = Engine()
    e.accept, e.match = accept, match
    e.run("normal")
    assert e.read(e.BASE + cp.TABLE_OFF) == 0
    assert e.read(e.BASE) == 0


def test_destruction_and_object_identity() -> None:
    e = Engine()
    e.run("normal")
    e.write(e.OBJECT + ad.OBJECT_ID, 43)
    assert e.run("resolve") == 99
    e.run("destroy")
    assert e.read(e.BASE + cp.TABLE_OFF) == 0


def test_full_table_declines_and_malformed_action_is_noop() -> None:
    e = Engine()
    for i in range(cp.MAX_OVERRIDES):
        e.write(e.BASE + cp.TABLE_OFF + i * cp.SLOT_SIZE, 0x123000 + i)
    e.run("normal")
    assert e.started == 0
    assert e.read(e.BASE) == 0
    e = Engine()
    e.write(e.ACTION + ad.SCRIPT_ACTION_PARAM_COUNT, 2)
    e.run("normal")
    assert e.started == 0


@pytest.mark.parametrize("worldbuilder", [False, True])
def test_runtime_template_registration(worldbuilder: bool) -> None:
    e = Engine()
    a = cp._emit(e.BASE, worldbuilder=worldbuilder)
    e.cpu.mem_write(e.BASE, a.finish())
    owner = 0x2100000
    e.cpu.mem_map(owner, 0x20000)
    e.cpu.reg_write(UC_X86_REG_ESP, e.STACK)
    e.cpu.reg_write(UC_X86_REG_ESI, owner)
    e.cpu.reg_write(UC_X86_REG_EBP, e.STACK + 0x100)
    e.write(e.STACK + 0xF8, owner)
    e.write(e.STACK, e.STOP)
    e.write(e.STACK + 4, 0)
    setter = ad.WORLDBUILDER_ASCIISTRING_SET if worldbuilder else 0x40618C
    strings: dict[int, str] = {}

    def set_string(cpu: Uc, addr: int, size: int, user: object) -> None:
        if addr == setter:
            src = e.read(cpu.reg_read(UC_X86_REG_ESP) + 4)
            if src:
                text = bytes(cpu.mem_read(src, 100)).split(b"\0")[0].decode("ascii")
                strings[cpu.reg_read(UC_X86_REG_ECX)] = text
            e._return(4)

    e.cpu.hook_add(UC_HOOK_CODE, set_string)
    e.cpu.emu_start(a.label_va("register"), e.STOP, count=20000)
    for i, action_id in enumerate(cp.ACTION_IDS):
        record = owner + 0x20 + action_id * 0x80
        assert strings[record + 0xC] == cp.ACTION_NAMES[i]
        assert strings[record + 4].startswith("Base/")
        assert e.read(record + 0x48) == 3
        assert tuple(e.read(record + 0x4C + j * 4) for j in range(3)) == (14, 54, 10)
    assert e.cpu.reg_read(UC_X86_REG_ESP) == e.STACK + 8


def test_rejected_second_request_preserves_delayed_choice() -> None:
    e = Engine()
    e.run("normal")
    e.key = 5678
    e.accept = False
    e.run("normal")
    assert e.run("resolve") == 1234


def test_pending_context_is_restored_for_an_outer_action() -> None:
    e = Engine()
    for i, value in enumerate((7654, 6543, 5432)):
        e.write(e.BASE + i * 4, value)
    e.run("normal")
    assert tuple(e.read(e.BASE + i * 4) for i in range(3)) == (7654, 6543, 5432)
    assert e.cpu.reg_read(UC_X86_REG_ESI) == e.ACTION
    assert e.cpu.reg_read(UC_X86_REG_EDI) == 0x22222222
    assert e.cpu.reg_read(UC_X86_REG_EBX) == 0x33333333


def test_two_castles_retain_distinct_prefabs() -> None:
    e = Engine()
    e.run("normal")
    second_behavior, second_object = e.BEHAVIOR + 0x100, e.OBJECT + 0x100
    e.write(second_behavior + 8, second_object)
    e.write(second_object + ad.OBJECT_ID, 43)
    e.write(e.BASE, second_object)
    e.write(e.BASE + 4, 5678)
    parameter = e.read(e.ACTION + ad.SCRIPT_ACTION_PARAM_ARRAY)
    e.write(e.BASE + 8, parameter)
    frame = e.STACK + 0x100
    e.write(frame + 8, parameter)
    e.write(e.STACK, e.STOP)
    e.write(e.STACK + 4, 0)
    e.write(e.STACK + 8, 0)
    e.cpu.reg_write(UC_X86_REG_EBP, frame)
    e.cpu.reg_write(UC_X86_REG_ESP, e.STACK)
    e.cpu.reg_write(UC_X86_REG_ECX, second_behavior)
    e.cpu.reg_write(UC_X86_REG_EDI, second_object)
    e.cpu.emu_start(e.a.label_va("start"), e.STOP, count=20000)
    assert e.run("resolve") == 1234
    e.cpu.reg_write(UC_X86_REG_ESP, e.STACK)
    e.cpu.reg_write(UC_X86_REG_ECX, second_behavior)
    e.write(e.STACK, e.STOP)
    e.cpu.emu_start(e.a.label_va("resolve"), e.STOP, count=20000)
    assert e.cpu.reg_read(UC_X86_REG_EAX) == 5678


def test_resolver_default_replays_owner_lookup() -> None:
    e = Engine()
    assert e.run("resolve") == 99
    assert e.cpu.reg_read(UC_X86_REG_ECX) == e.OBJECT


@pytest.mark.parametrize("label", ["normal", "free"])
@pytest.mark.parametrize("parameter_type", [2, 10])
def test_map_editor_string_parameter_reaches_stock_helper(label: str, parameter_type: int) -> None:
    e = Engine()
    third_parameter = e.read(e.ACTION + ad.SCRIPT_ACTION_PARAM_ARRAY + 8)
    e.write(third_parameter + ad.SCRIPT_PARAMETER_TYPE, parameter_type)
    e.run(label)
    assert e.started == 1
    assert e.read(e.BASE) == 0
    assert e.run("resolve") == e.key


@pytest.mark.parametrize("parameter_type", [0, 1, 16])
def test_nonstring_prefab_parameters_are_rejected(parameter_type: int) -> None:
    e = Engine()
    third_parameter = e.read(e.ACTION + ad.SCRIPT_ACTION_PARAM_ARRAY + 8)
    e.write(third_parameter + ad.SCRIPT_PARAMETER_TYPE, parameter_type)
    e.run("normal")
    assert e.started == 0
    assert e.read(e.BASE + cp.TABLE_OFF) == 0
