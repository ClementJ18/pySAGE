"""Tests for the evacuate-contained-heroes patch.

The hook is one `jmp` and a two-armed cave, so the structural checks are short. What could still be
wrong without raising is the register contract with the loop it jumps back into: that `eax` holds
the passenger when the `aiExit` arm reads it, that the displaced `push` lands before the horde arm
resumes, and that the stack comes back level. So the real loop body is run, before and after the
patch, over a passenger list holding one of each kind.
"""

from __future__ import annotations

import faulthandler
import struct
from pathlib import Path

import pytest

from sage_patch.addresses import (
    CONTAIN_EXIT_ALL_HORDE_TEST,
    CONTAIN_EXIT_ALL_LOOP,
    CONTAIN_EXIT_ALL_LOOP_BYTES,
    CONTAIN_EXIT_ALL_ORDER_EXIT,
    CONTAIN_EXIT_ALL_PASSENGERS,
    CONTAIN_EXIT_ALL_WRAPPER_CALLS,
    OBJECT_AI_UPDATE,
    OBJECT_CONTAIN,
)
from sage_patch.patches.evacuate_contained_heroes import (
    HOOK_WIDTH,
    SECTION_NAME,
    STOCK_HOOK,
    EvacuateContainedHeroesPatch,
    build_code,
)
from sage_patch.registry import PATCHES
from sage_patch.utils import call_rel32, find_section, jmp_rel32, va_to_offset
from tests.sage_patch.synthetic import evacuate_contained_heroes_image

#: `AIUpdateInterface::aiExit`-style helper the `aiExit` arm calls, on the `AIUpdate`'s `+0x20`.
AI_EXIT = 0x007716C1
#: Contain-interface slot that answers the horde interface, and the horde interface's exit slot.
GET_HORDE_IFACE_SLOT = 0x7C
HORDE_EXIT_SLOT = 0x84
LOOP_END = CONTAIN_EXIT_ALL_LOOP + len(CONTAIN_EXIT_ALL_LOOP_BYTES)


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
    return evacuate_contained_heroes_image()


@pytest.fixture
def patched() -> bytearray:
    data = evacuate_contained_heroes_image()
    EvacuateContainedHeroesPatch().apply(data)
    return data


class TestStructure:
    def test_the_hook_is_the_horde_test(self) -> None:
        # test eax, eax; je +0x2a; push [ebp+0x10]
        assert STOCK_HOOK == bytes.fromhex("85c0742aff7510")

    def test_the_hook_jumps_to_the_cave(self, patched: bytearray) -> None:
        want = jmp_rel32(CONTAIN_EXIT_ALL_HORDE_TEST, _cave_va(patched), HOOK_WIDTH)
        assert _read(patched, CONTAIN_EXIT_ALL_HORDE_TEST, HOOK_WIDTH) == want

    def test_nothing_else_in_the_loop_moves(self, patched: bytearray) -> None:
        got = _read(patched, CONTAIN_EXIT_ALL_LOOP, len(CONTAIN_EXIT_ALL_LOOP_BYTES))
        hook = CONTAIN_EXIT_ALL_HORDE_TEST - CONTAIN_EXIT_ALL_LOOP
        assert got[:hook] == CONTAIN_EXIT_ALL_LOOP_BYTES[:hook]
        assert got[hook + HOOK_WIDTH :] == CONTAIN_EXIT_ALL_LOOP_BYTES[hook + HOOK_WIDTH :]

    def test_the_cave_decodes_as_written(self, patched: bytearray) -> None:
        capstone = pytest.importorskip("capstone")
        md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
        cave = _cave_va(patched)
        code = build_code(cave)
        listing = [f"{i.mnemonic} {i.op_str}" for i in md.disasm(code, cave)]
        assert listing == [
            "test eax, eax",
            f"je {cave + 12:#x}",
            "push dword ptr [ebp + 0x10]",
            f"jmp {CONTAIN_EXIT_ALL_HORDE_TEST + HOOK_WIDTH:#x}",
            "mov eax, dword ptr [esi + 8]",
            f"jmp {CONTAIN_EXIT_ALL_ORDER_EXIT:#x}",
        ]
        assert _read(patched, cave, len(code)) == code


class TestLifecycle:
    def test_apply_verify_detect(self, patched: bytearray) -> None:
        assert EvacuateContainedHeroesPatch().verify(patched) == []
        assert isinstance(
            EvacuateContainedHeroesPatch.detect(patched), EvacuateContainedHeroesPatch
        )

    def test_an_unpatched_image_is_not_detected(self, image: bytearray) -> None:
        assert EvacuateContainedHeroesPatch().verify(image) != []
        assert EvacuateContainedHeroesPatch.detect(image) is None

    def test_a_second_apply_refuses(self, patched: bytearray) -> None:
        with pytest.raises(ValueError, match="already carries this patch"):
            EvacuateContainedHeroesPatch().apply(patched)

    def test_a_drifted_loop_refuses_before_writing(self, image: bytearray) -> None:
        """The cave jumps back to the `aiExit` arm, so a change there breaks it even though the
        hooked bytes are intact."""
        off = va_to_offset(image, CONTAIN_EXIT_ALL_ORDER_EXIT)
        assert off is not None
        image[off + 2] ^= 0xFF  # the 0x260 displacement
        before = bytes(image)
        with pytest.raises(ValueError, match="expected the stock exit-all loop"):
            EvacuateContainedHeroesPatch().apply(image)
        assert bytes(image) == before

    def test_a_missing_wrapper_call_refuses(self, image: bytearray) -> None:
        off = va_to_offset(image, CONTAIN_EXIT_ALL_WRAPPER_CALLS[0])
        assert off is not None
        image[off : off + 5] = bytes(5)
        with pytest.raises(ValueError, match="expected a call to the exit-all loop"):
            EvacuateContainedHeroesPatch().apply(image)

    def test_registered_as_settled(self) -> None:
        assert PATCHES["evacuate-contained-heroes"] is EvacuateContainedHeroesPatch
        assert not EvacuateContainedHeroesPatch.experimental


unicorn = pytest.importorskip("unicorn", reason="the emulator harness needs unicorn")

from unicorn import UC_ARCH_X86, UC_HOOK_CODE, UC_MODE_32, Uc  # noqa: E402
from unicorn.x86_const import (  # noqa: E402
    UC_X86_REG_EAX,
    UC_X86_REG_EBP,
    UC_X86_REG_ECX,
    UC_X86_REG_ESI,
    UC_X86_REG_ESP,
)

_PAGE = 0x1000
_HEAP = 0x20000000
_STACK = 0x30000000
_STUBS = 0x40000000
_GET_HORDE, _NO_HORDE, _HORDE_EXIT = _STUBS, _STUBS + 0x10, _STUBS + 0x20
_CONTAINER, _CMD_SOURCE = 0x12345678, 2

#: The four passengers, as `(contain kind, has an AIUpdate)`: a plain unit, a battalion, a ring
#: hero, and a contain-carrier without AI, which neither arm can move.
PASSENGERS = {
    "unit": (None, True),
    "battalion": ("horde", True),
    "ring hero": ("other", True),
    "no ai": ("other", False),
}


def _evacuate(data: bytes | bytearray) -> tuple[list[tuple[str, str]], int]:
    """Run the exit-all loop out of `data` over `PASSENGERS` and return who was sent out, and by
    which arm, plus the stack drift."""
    uc = Uc(UC_ARCH_X86, UC_MODE_32)
    cave = find_section(data, SECTION_NAME)
    pages = {CONTAIN_EXIT_ALL_LOOP & ~0xFFF, AI_EXIT & ~0xFFF, _STACK, _STUBS}
    pages |= {_HEAP + i * _PAGE for i in range(4)}
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

    uc.mem_write(
        CONTAIN_EXIT_ALL_LOOP, _read(data, CONTAIN_EXIT_ALL_LOOP, len(CONTAIN_EXIT_ALL_LOOP_BYTES))
    )
    if cave is not None:
        code = build_code(cave[0])
        uc.mem_write(cave[0], _read(data, cave[0], len(code)))
    uc.mem_write(AI_EXIT, b"\xc2\x08\x00")  # ret 8
    uc.mem_write(_NO_HORDE, b"\x31\xc0\xc3")  # xor eax, eax; ret
    uc.mem_write(_HORDE_EXIT, b"\xc2\x08\x00")  # ret 8

    # One heap page per role: list nodes, objects, modules, vtables.
    nodes, objects, modules, vtables = (_HEAP + i * _PAGE for i in range(4))
    contain_vt, horde_contain_vt, horde_vt = vtables, vtables + 0x200, vtables + 0x400
    uc.mem_write(contain_vt + GET_HORDE_IFACE_SLOT, struct.pack("<I", _NO_HORDE))
    uc.mem_write(horde_contain_vt + GET_HORDE_IFACE_SLOT, struct.pack("<I", _GET_HORDE))
    uc.mem_write(horde_vt + HORDE_EXIT_SLOT, struct.pack("<I", _HORDE_EXIT))
    horde_iface = modules + 0x800
    uc.mem_write(horde_iface, struct.pack("<I", horde_vt))
    uc.mem_write(_GET_HORDE, b"\xb8" + struct.pack("<I", horde_iface) + b"\xc3")

    who: dict[int, str] = {}
    sentinel = nodes
    previous = sentinel
    for i, (name, (contain, has_ai)) in enumerate(PASSENGERS.items(), start=1):
        node, obj, module = nodes + 0x20 * i, objects + 0x300 * i, modules + 0x40 * i
        uc.mem_write(node + 8, struct.pack("<I", obj))
        uc.mem_write(previous, struct.pack("<I", node))
        previous = node
        if contain is not None:
            vt = horde_contain_vt if contain == "horde" else contain_vt
            uc.mem_write(module, struct.pack("<I", vt))
            uc.mem_write(obj + OBJECT_CONTAIN, struct.pack("<I", module))
            if contain == "horde":
                who[horde_iface] = name
        if has_ai:
            ai = module + 0x20
            uc.mem_write(obj + OBJECT_AI_UPDATE, struct.pack("<I", ai))
            who[ai + 0x20] = name
    uc.mem_write(previous, struct.pack("<I", sentinel))

    exits: list[tuple[str, str]] = []

    def on_code(emu: Uc, address: int, _size: int, _user: object) -> None:
        arm = {AI_EXIT: "aiExit", _HORDE_EXIT: "horde"}.get(address)
        if arm is None:
            return
        esp = emu.reg_read(UC_X86_REG_ESP)
        args = struct.unpack("<II", bytes(emu.mem_read(esp + 4, 8)))
        assert args == (_CONTAINER, _CMD_SOURCE), f"{arm} called with {args}"
        exits.append((who[emu.reg_read(UC_X86_REG_ECX)], arm))

    uc.hook_add(UC_HOOK_CODE, on_code)

    esp = _STACK + 0x800
    ebp = esp + 0x40
    uc.mem_write(ebp + 0x08, struct.pack("<III", sentinel, _CONTAINER, _CMD_SOURCE))
    uc.reg_write(UC_X86_REG_ESP, esp)
    uc.reg_write(UC_X86_REG_EBP, ebp)
    first = struct.unpack("<I", bytes(uc.mem_read(sentinel, 4)))[0]
    uc.reg_write(UC_X86_REG_ESI, first)
    uc.reg_write(UC_X86_REG_EAX, 0)
    uc.emu_start(CONTAIN_EXIT_ALL_LOOP, LOOP_END, count=400)
    return exits, uc.reg_read(UC_X86_REG_ESP) - esp


class TestTheLoopRuns:
    def test_stock_leaves_the_ring_hero_inside(self, image: bytearray) -> None:
        exits, drift = _evacuate(image)
        assert exits == [("unit", "aiExit"), ("battalion", "horde")]
        assert drift == 0

    def test_patched_sends_the_ring_hero_out(self, patched: bytearray) -> None:
        exits, drift = _evacuate(patched)
        assert exits == [("unit", "aiExit"), ("battalion", "horde"), ("ring hero", "aiExit")]
        assert drift == 0


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

    def test_the_loop_and_its_callers_are_stock(self, which: str) -> None:
        stock = self._stock(which)
        assert _read(stock, CONTAIN_EXIT_ALL_LOOP, len(CONTAIN_EXIT_ALL_LOOP_BYTES)) == (
            CONTAIN_EXIT_ALL_LOOP_BYTES
        )
        for site in CONTAIN_EXIT_ALL_WRAPPER_CALLS:
            assert _read(stock, site, 5) == call_rel32(site, CONTAIN_EXIT_ALL_PASSENGERS)

    def test_the_ai_exit_arm_calls_the_helper(self, which: str) -> None:
        """The `call` at the end of the `aiExit` arm, which the emulation stubs out."""
        stock = self._stock(which)
        site = CONTAIN_EXIT_ALL_ORDER_EXIT + 0x13
        assert _read(stock, site, 5) == call_rel32(site, AI_EXIT)

    def test_apply_verify_detect_round_trip(self, which: str) -> None:
        data = bytearray(self._stock(which))
        EvacuateContainedHeroesPatch().apply(data)
        assert EvacuateContainedHeroesPatch().verify(data) == []
        assert isinstance(EvacuateContainedHeroesPatch.detect(data), EvacuateContainedHeroesPatch)
