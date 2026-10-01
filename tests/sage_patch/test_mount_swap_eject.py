"""Tests for the mount-swap-eject patch.

The hook is one 6-byte `jmp` over the retire's `mov ecx, [TheGameLogic]`. What could still be
wrong without raising is the walk: that it visits every module and stops at the NULL, that it
leaves alone what is not an ejecting non-horde `OpenContain`, that it calls the two slots stock
death calls in the same order with the same `this`, and that the retire's tail still gets the
registers it expects. So the cave is emulated over a fake object whose modules cover each case.
"""

from __future__ import annotations

import faulthandler
import struct
from pathlib import Path

import pytest

from sage_patch import MountSwapEjectPatch
from sage_patch.addresses import (
    BEHAVIOR_GET_CONTAIN_SLOT,
    BEHAVIOR_MODULE_INTERFACE,
    CONTAIN_GET_HORDE_IFACE_SLOT,
    CONTAIN_REMOVE_ALL_SLOT,
    MODULE_MODULE_DATA,
    OBJECT_MODULE_LIST,
    OPEN_CONTAIN_CONTAIN_INTERFACE,
    OPEN_CONTAIN_EJECT_PASSENGERS_ON_DEATH,
    OPEN_CONTAIN_GET_CONTAIN,
    OPEN_CONTAIN_KILL_RIDERS_NOT_FREE_TO_EXIT_SLOT,
    OPEN_CONTAIN_ON_DIE_EJECT_BYTES,
    THE_GAME_LOGIC,
    TOGGLE_MOUNTED_RETIRE,
    TOGGLE_MOUNTED_RETIRE_BYTES,
    TOGGLE_MOUNTED_RETIRE_DESTROY,
)
from sage_patch.patches.mount_swap_eject import (
    ANCHORS,
    HOOK_WIDTH,
    RESUME,
    SECTION_NAME,
    STOCK_HOOK,
    build_code,
)
from sage_patch.registry import PATCHES
from sage_patch.utils import find_section, jmp_rel32, va_to_offset
from tests.sage_patch.synthetic import mount_swap_eject_image


def _read(data: bytes | bytearray, va: int, n: int) -> bytes:
    off = va_to_offset(data, va)
    assert off is not None, f"0x{va:08x} is not mapped"
    return bytes(data[off : off + n])


def _cave_va(data: bytes | bytearray) -> int:
    located = find_section(data, SECTION_NAME)
    assert located is not None, f"no {SECTION_NAME} section"
    return located[0]


@pytest.fixture
def image() -> bytearray:
    return mount_swap_eject_image()


@pytest.fixture
def patched() -> bytearray:
    data = mount_swap_eject_image()
    MountSwapEjectPatch().apply(data)
    return data


class TestStructure:
    def test_the_hook_is_the_game_logic_load(self) -> None:
        assert STOCK_HOOK == bytes.fromhex("8b0d2c41de00")  # mov ecx, [0x00de412c]
        offset = TOGGLE_MOUNTED_RETIRE_DESTROY - TOGGLE_MOUNTED_RETIRE
        assert TOGGLE_MOUNTED_RETIRE_BYTES[offset : offset + HOOK_WIDTH] == STOCK_HOOK

    def test_the_retire_calls_the_cave(self, patched: bytearray) -> None:
        want = jmp_rel32(TOGGLE_MOUNTED_RETIRE_DESTROY, _cave_va(patched), HOOK_WIDTH)
        assert _read(patched, TOGGLE_MOUNTED_RETIRE_DESTROY, HOOK_WIDTH) == want

    def test_nothing_else_in_the_retire_moves(self, patched: bytearray) -> None:
        """The head the lifetime-fields patch anchors and the tail the cave rejoins both have to
        survive byte for byte."""
        got = _read(patched, TOGGLE_MOUNTED_RETIRE, len(TOGGLE_MOUNTED_RETIRE_BYTES))
        hook = TOGGLE_MOUNTED_RETIRE_DESTROY - TOGGLE_MOUNTED_RETIRE
        assert got[:hook] == TOGGLE_MOUNTED_RETIRE_BYTES[:hook]
        assert got[hook + HOOK_WIDTH :] == TOGGLE_MOUNTED_RETIRE_BYTES[hook + HOOK_WIDTH :]

    def test_the_slots_are_the_ones_stock_death_uses(self) -> None:
        """The flag offset and both slots are read out of `OpenContain::onDie`'s eject arm, which
        reaches the module as `esi-0x28` and the interface as `esi-8`."""
        arm = OPEN_CONTAIN_ON_DIE_EJECT_BYTES
        assert arm[:2] == b"\x80\xb8"  # cmp byte [eax+disp32], 0
        assert struct.unpack_from("<I", arm, 2)[0] == OPEN_CONTAIN_EJECT_PASSENGERS_ON_DEATH
        kill_slot = bytes([OPEN_CONTAIN_KILL_RIDERS_NOT_FREE_TO_EXIT_SLOT])
        remove_slot = struct.pack("<I", CONTAIN_REMOVE_ALL_SLOT)
        kill = b"\x8d\x4e\xd8\x8b\x01\xff\x50" + kill_slot  # lea ecx,[esi-0x28] / call [eax+x]
        remove = b"\x8d\x4e\xf8\x8b\x01\x6a\x00\xff\x90" + remove_slot  # lea ecx,[esi-8] / push 0
        assert arm.index(kill) < arm.index(remove)
        assert 0xF8 - 0xD8 == OPEN_CONTAIN_CONTAIN_INTERFACE

    def test_the_cave_decodes_as_written(self, patched: bytearray) -> None:
        capstone = pytest.importorskip("capstone")
        md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
        cave = _cave_va(patched)
        code = build_code(cave)
        listing = [f"{i.mnemonic} {i.op_str}".strip() for i in md.disasm(code, cave)]
        assert listing == [
            "push ebx",
            "push edi",
            "mov ebx, dword ptr [esi + 0x24c]",
            "mov eax, dword ptr [ebx]",
            "test eax, eax",
            f"je {cave + 0x4D:#x}",
            "add ebx, 4",
            "mov ecx, dword ptr [eax + 0xc]",
            "cmp dword ptr [ecx + 8], 0x8a18e0",
            f"jne {cave + 8:#x}",
            "mov ecx, dword ptr [eax + 4]",
            "cmp byte ptr [ecx + 0x82], 0",
            f"je {cave + 8:#x}",
            "lea edi, [eax + 0x20]",
            "mov ecx, edi",
            "mov eax, dword ptr [edi]",
            "call dword ptr [eax + 0x7c]",
            "test eax, eax",
            f"jne {cave + 8:#x}",
            "lea ecx, [edi - 0x20]",
            "mov eax, dword ptr [ecx]",
            "call dword ptr [eax + 0x64]",
            "push 0",
            "mov ecx, edi",
            "mov eax, dword ptr [edi]",
            "call dword ptr [eax + 0xa8]",
            f"jmp {cave + 8:#x}",
            "pop edi",
            "pop ebx",
            "mov ecx, dword ptr [0xde412c]",
            f"jmp {RESUME:#x}",
        ]
        assert _read(patched, cave, len(code)) == code


class TestLifecycle:
    def test_apply_verify_detect(self, patched: bytearray) -> None:
        assert MountSwapEjectPatch().verify(patched) == []
        assert isinstance(MountSwapEjectPatch.detect(patched), MountSwapEjectPatch)

    def test_an_unpatched_image_is_not_detected(self, image: bytearray) -> None:
        assert MountSwapEjectPatch().verify(image) != []
        assert MountSwapEjectPatch.detect(image) is None

    def test_a_second_apply_refuses(self, patched: bytearray) -> None:
        with pytest.raises(ValueError, match="already carries this patch"):
            MountSwapEjectPatch().apply(patched)

    @pytest.mark.parametrize("va", sorted(ANCHORS), ids=lambda va: f"{va:08x}")
    def test_any_anchor_differing_refuses_before_writing(self, image: bytearray, va: int) -> None:
        off = va_to_offset(image, va)
        assert off is not None
        image[off] ^= 0xFF
        before = bytes(image)
        with pytest.raises(ValueError, match="not the expected build"):
            MountSwapEjectPatch().apply(image)
        assert bytes(image) == before

    def test_registered_as_settled(self) -> None:
        assert PATCHES["mount-swap-eject"] is MountSwapEjectPatch
        assert not MountSwapEjectPatch.experimental


unicorn = pytest.importorskip("unicorn", reason="the emulator harness needs unicorn")

from unicorn import UC_ARCH_X86, UC_HOOK_CODE, UC_MODE_32, Uc  # noqa: E402
from unicorn.x86_const import (  # noqa: E402
    UC_X86_REG_EBP,
    UC_X86_REG_EBX,
    UC_X86_REG_ECX,
    UC_X86_REG_EDI,
    UC_X86_REG_ESI,
    UC_X86_REG_ESP,
)

_PAGE = 0x1000
_HEAP = 0x20000000
_STACK = 0x30000000
_STUBS = 0x40000000
_OBJECT = _HEAP
_MODULE_LIST = _HEAP + 0x800
_GAME_LOGIC = 0x51000000  # what `*THE_GAME_LOGIC` holds; never dereferenced here

#: Stub bodies, each only a return of the right width, plus the one answer the horde test needs.
_KILL, _REMOVE, _NOT_HORDE, _HORDE = _STUBS, _STUBS + 0x10, _STUBS + 0x20, _STUBS + 0x30
_STUB_CODE = {
    _KILL: b"\xc3",  # ret
    _REMOVE: b"\xc2\x04\x00",  # ret 4
    _NOT_HORDE: b"\x31\xc0\xc3",  # xor eax, eax / ret
    _HORDE: b"\xb8\x01\x00\x00\x00\xc3",  # mov eax, 1 / ret
}
#: A behaviour-interface `getContain` that is not `OpenContain`'s - its address is only compared.
_OTHER_GET_CONTAIN = _STUBS + 0x40

#: The cases: (name, interface's getContain, EjectPassengersOnDeath, is a horde).
_MODULES = {
    "rider": (OPEN_CONTAIN_GET_CONTAIN, 1, False),
    "flag_off": (OPEN_CONTAIN_GET_CONTAIN, 0, False),
    "horde": (OPEN_CONTAIN_GET_CONTAIN, 1, True),
    "not_open_contain": (_OTHER_GET_CONTAIN, 1, False),
    "second_rider": (OPEN_CONTAIN_GET_CONTAIN, 1, False),
}


def _module_va(index: int) -> int:
    return _HEAP + _PAGE * (1 + index)


def _plant_module(uc: Uc, module: int, get_contain: int, eject: int, horde: bool) -> None:
    """One module on its own page: primary vtable at `+0x100`, ModuleData at `+0x200`,
    behaviour-interface vtable at `+0x300`, contain-interface vtable at `+0x400`."""
    primary, data, behavior, contain = (module + k for k in (0x100, 0x200, 0x300, 0x400))
    uc.mem_write(module, struct.pack("<I", primary))
    uc.mem_write(module + MODULE_MODULE_DATA, struct.pack("<I", data))
    uc.mem_write(module + BEHAVIOR_MODULE_INTERFACE, struct.pack("<I", behavior))
    uc.mem_write(module + OPEN_CONTAIN_CONTAIN_INTERFACE, struct.pack("<I", contain))
    uc.mem_write(primary + OPEN_CONTAIN_KILL_RIDERS_NOT_FREE_TO_EXIT_SLOT, struct.pack("<I", _KILL))
    uc.mem_write(data + OPEN_CONTAIN_EJECT_PASSENGERS_ON_DEATH, bytes([eject]))
    uc.mem_write(behavior + BEHAVIOR_GET_CONTAIN_SLOT, struct.pack("<I", get_contain))
    uc.mem_write(
        contain + CONTAIN_GET_HORDE_IFACE_SLOT, struct.pack("<I", _HORDE if horde else _NOT_HORDE)
    )
    uc.mem_write(contain + CONTAIN_REMOVE_ALL_SLOT, struct.pack("<I", _REMOVE))


def _retire(data: bytes | bytearray, modules: list[str]):
    """Run the retire from the hooked instruction to the `push esi` in front of `destroyObject`
    over an object carrying `modules`, in that order.

    Returns the slot calls made, as `(slot, ecx, stack argument)` with `ecx` given as the module
    it belongs to, then `ecx` at the end and whether the saved registers and the stack came back."""
    uc = Uc(UC_ARCH_X86, UC_MODE_32)
    cave = find_section(data, SECTION_NAME)
    pages = {TOGGLE_MOUNTED_RETIRE & ~0xFFF, THE_GAME_LOGIC & ~0xFFF, _STACK, _STUBS, _HEAP}
    pages |= {_module_va(i) for i in range(len(modules))}
    if cave is not None:
        pages.add(cave[0] & ~0xFFF)
    # `mem_map` raises and catches an SEH access violation inside Unicorn on Windows; every map
    # still succeeds, but the fault handler would print a stack for each one.
    was_enabled = faulthandler.is_enabled()
    faulthandler.disable()
    try:
        for page in sorted(pages):
            uc.mem_map(page, _PAGE)
    finally:
        if was_enabled:
            faulthandler.enable()

    uc.mem_write(TOGGLE_MOUNTED_RETIRE, _read(data, TOGGLE_MOUNTED_RETIRE, 0x4D))
    if cave is not None:
        uc.mem_write(cave[0], _read(data, cave[0], len(build_code(cave[0]))))
    uc.mem_write(THE_GAME_LOGIC, struct.pack("<I", _GAME_LOGIC))
    for va, body in _STUB_CODE.items():
        uc.mem_write(va, body)
    uc.mem_write(_OBJECT + OBJECT_MODULE_LIST, struct.pack("<I", _MODULE_LIST))
    owners: dict[int, str] = {}
    for index, name in enumerate(modules):
        module = _module_va(index)
        _plant_module(uc, module, *_MODULES[name])
        uc.mem_write(_MODULE_LIST + 4 * index, struct.pack("<I", module))
        owners[module] = owners[module + OPEN_CONTAIN_CONTAIN_INTERFACE] = name
    uc.mem_write(_MODULE_LIST + 4 * len(modules), bytes(4))

    calls: list[tuple[str, str, int | None]] = []

    def on_stub(uc: Uc, address: int, _size: int, _data: object) -> None:
        ecx = uc.reg_read(UC_X86_REG_ECX)
        esp = uc.reg_read(UC_X86_REG_ESP)
        if address == _KILL:
            calls.append(("kill", owners[ecx], None))
            assert ecx == _module_va(modules.index(owners[ecx])), "kill wants the module"
        elif address == _REMOVE:
            (argument,) = struct.unpack("<I", bytes(uc.mem_read(esp + 4, 4)))
            calls.append(("remove", owners[ecx], argument))
            assert ecx == _module_va(modules.index(owners[ecx])) + OPEN_CONTAIN_CONTAIN_INTERFACE

    uc.hook_add(UC_HOOK_CODE, on_stub, begin=_KILL, end=_REMOVE)

    esp = _STACK + 0x800
    saved = {UC_X86_REG_EBX: 0x0B0B0B0B, UC_X86_REG_EDI: 0x0D0D0D0D, UC_X86_REG_EBP: esp + 0x40}
    uc.reg_write(UC_X86_REG_ESP, esp)
    uc.reg_write(UC_X86_REG_ESI, _OBJECT)
    for reg, value in saved.items():
        uc.reg_write(reg, value)
    uc.emu_start(TOGGLE_MOUNTED_RETIRE_DESTROY, RESUME, count=512)
    kept = uc.reg_read(UC_X86_REG_ESI) == _OBJECT and uc.reg_read(UC_X86_REG_ESP) == esp
    kept = kept and all(uc.reg_read(reg) == value for reg, value in saved.items())
    return calls, uc.reg_read(UC_X86_REG_ECX), kept


class TestTheRetireRuns:
    def test_stock_only_loads_game_logic(self, image: bytearray) -> None:
        calls, ecx, kept = _retire(image, ["rider"])
        assert (calls, ecx, kept) == ([], _GAME_LOGIC, True)

    def test_a_rider_is_ejected_as_death_would(self, patched: bytearray) -> None:
        calls, ecx, kept = _retire(patched, ["rider"])
        assert calls == [("kill", "rider", None), ("remove", "rider", 0)]
        assert (ecx, kept) == (_GAME_LOGIC, True)

    def test_only_ejecting_non_horde_open_contains_are_touched(self, patched: bytearray) -> None:
        """Every module is visited, and a hero carrying two contains - Edain's Gandalf, whose
        ring pickup sits at `OBJECT_CONTAIN` - still has the other one emptied."""
        calls, ecx, kept = _retire(patched, list(_MODULES))
        assert calls == [
            ("kill", "rider", None),
            ("remove", "rider", 0),
            ("kill", "second_rider", None),
            ("remove", "second_rider", 0),
        ]
        assert (ecx, kept) == (_GAME_LOGIC, True)

    def test_an_object_with_no_modules(self, patched: bytearray) -> None:
        assert _retire(patched, []) == ([], _GAME_LOGIC, True)


#: Both copies a checkout can hold; neither is committed, so each check skips when absent.
_BINARIES = {
    "repo": Path(__file__).resolve().parents[2] / "game.dat",
    "clean": Path(__file__).resolve().parents[2] / "sage_patch" / "engine" / "game.dat.backup",
}


@pytest.mark.parametrize("which", sorted(_BINARIES))
class TestStockBinaries:
    def _stock(self, which: str) -> bytes:
        path = _BINARIES[which]
        if not path.exists():
            pytest.skip(f"needs {path.name}")
        return path.read_bytes()

    def test_every_anchor_is_stock(self, which: str) -> None:
        stock = self._stock(which)
        for va, expected in ANCHORS.items():
            assert _read(stock, va, len(expected)) == expected

    def test_apply_verify_detect_round_trip(self, which: str) -> None:
        data = bytearray(self._stock(which))
        MountSwapEjectPatch().apply(data)
        assert MountSwapEjectPatch().verify(data) == []
        assert isinstance(MountSwapEjectPatch.detect(data), MountSwapEjectPatch)
