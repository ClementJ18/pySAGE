"""Tests for the mount-health-ratio patch.

The hook is two 5-byte `call`s, so the structural checks are short. What could still be wrong
without raising is the arithmetic and the register contract: that `[ebp-0x14]` really is the new
body when the cave runs, that the ratio survives the second call, and that the stock `fstp` /
`setHealth` after the hook stores what the cave left in `st(0)`. So the hand-over is emulated,
before and after the patch, against the engine's own getter and setter bytes.
"""

from __future__ import annotations

import faulthandler
import struct
from pathlib import Path

import pytest

from sage_patch import MountHealthRatioPatch
from sage_patch.addresses import (
    BODY_GET_HEALTH_RATIO_SLOT,
    BODY_GET_HEALTH_SLOT,
    BODY_GET_MAX_HEALTH_SLOT,
    OBJECT_BODY_MODULE,
    TOGGLE_MOUNTED_DISMOUNT_HEALTH_COPY,
    TOGGLE_MOUNTED_HEALTH_COPY_SEQUENCE,
    TOGGLE_MOUNTED_MOUNT_HEALTH_COPY,
)
from sage_patch.patches.mount_health_ratio import (
    HOOK_SITES,
    SECTION_NAME,
    STOCK_HOOK,
    build_code,
)
from sage_patch.registry import PATCHES
from sage_patch.utils import call_rel32, find_section, va_to_offset
from tests.sage_patch.synthetic import mount_health_ratio_image

SEQUENCES = (TOGGLE_MOUNTED_MOUNT_HEALTH_COPY, TOGGLE_MOUNTED_DISMOUNT_HEALTH_COPY)

#: The `ActiveBody` getters and setter the hand-over reaches, as the engine has them: the vtable
#: every ordinary unit body uses, and each slot's function with its stock bytes. The ratio getter
#: compares against the zero at `0x00C1B594`.
ACTIVE_BODY_VTABLE = 0x00C71ED0
BODY_SET_HEALTH_SLOT = 0xAC
BODY_ZERO = 0x00C1B594
GETTERS = {
    BODY_GET_HEALTH_SLOT: (0x005F2D41, bytes.fromhex("d94108c3")),
    BODY_GET_HEALTH_RATIO_SLOT: (
        0x008C1D75,
        bytes.fromhex("f30f1041100f2f0594b5c1007607d94108d87110c3d90594b5c100c3"),
    ),
    BODY_GET_MAX_HEALTH_SLOT: (0x006AA274, bytes.fromhex("d94110c3")),
    BODY_SET_HEALTH_SLOT: (0x005015C6, bytes.fromhex("f30f10442404f30f114108c20400")),
}


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
    return mount_health_ratio_image()


@pytest.fixture
def patched() -> bytearray:
    data = mount_health_ratio_image()
    MountHealthRatioPatch().apply(data)
    return data


class TestStructure:
    def test_the_hook_is_the_get_health_call(self) -> None:
        assert STOCK_HOOK == bytes.fromhex("8b01ff5010")  # mov eax, [ecx]; call [eax+0x10]

    def test_both_sites_call_the_cave(self, patched: bytearray) -> None:
        cave = _cave_va(patched)
        for site in HOOK_SITES:
            assert _read(patched, site, 5) == call_rel32(site, cave)

    def test_nothing_else_in_either_sequence_moves(self, patched: bytearray) -> None:
        """The stock code on either side of the hook is what stores the answer, so it has to
        survive byte for byte."""
        for seq, site in zip(SEQUENCES, HOOK_SITES, strict=True):
            got = _read(patched, seq, len(TOGGLE_MOUNTED_HEALTH_COPY_SEQUENCE))
            hook = site - seq
            assert got[:hook] == TOGGLE_MOUNTED_HEALTH_COPY_SEQUENCE[:hook]
            assert got[hook + 5 :] == TOGGLE_MOUNTED_HEALTH_COPY_SEQUENCE[hook + 5 :]

    def test_the_cave_decodes_as_written(self, patched: bytearray) -> None:
        capstone = pytest.importorskip("capstone")
        md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
        code = build_code()
        listing = [f"{i.mnemonic} {i.op_str}".strip() for i in md.disasm(code, _cave_va(patched))]
        assert listing == [
            "mov eax, dword ptr [ecx]",
            "call dword ptr [eax + 0x14]",
            "push ecx",
            "fstp dword ptr [esp]",
            "mov ecx, dword ptr [ebp - 0x14]",
            "mov eax, dword ptr [ecx]",
            "call dword ptr [eax + 0x1c]",
            "fmul dword ptr [esp]",
            "pop ecx",
            "ret",
        ]
        assert _read(patched, _cave_va(patched), len(code)) == code


class TestLifecycle:
    def test_apply_verify_detect(self, patched: bytearray) -> None:
        assert MountHealthRatioPatch().verify(patched) == []
        assert isinstance(MountHealthRatioPatch.detect(patched), MountHealthRatioPatch)

    def test_an_unpatched_image_is_not_detected(self, image: bytearray) -> None:
        assert MountHealthRatioPatch().verify(image) != []
        assert MountHealthRatioPatch.detect(image) is None

    def test_a_second_apply_refuses(self, patched: bytearray) -> None:
        with pytest.raises(ValueError, match="already carries this patch"):
            MountHealthRatioPatch().apply(patched)

    def test_either_sequence_differing_refuses_before_writing(self, image: bytearray) -> None:
        """A drifted byte outside the hook still breaks the register contract, so it refuses."""
        off = va_to_offset(image, TOGGLE_MOUNTED_DISMOUNT_HEALTH_COPY)
        assert off is not None
        image[off + 0x10] ^= 0xFF  # the displacement of `mov [ebp-0x14], eax`
        before = bytes(image)
        with pytest.raises(ValueError, match="expected the stock mount-swap health hand-over"):
            MountHealthRatioPatch().apply(image)
        assert bytes(image) == before

    def test_registered_as_settled(self) -> None:
        assert PATCHES["mount-health-ratio"] is MountHealthRatioPatch
        assert not MountHealthRatioPatch.experimental


unicorn = pytest.importorskip("unicorn", reason="the emulator harness needs unicorn")

from unicorn import UC_ARCH_X86, UC_MODE_32, Uc  # noqa: E402
from unicorn.x86_const import (  # noqa: E402
    UC_X86_REG_EBP,
    UC_X86_REG_EBX,
    UC_X86_REG_EDI,
    UC_X86_REG_ESI,
    UC_X86_REG_ESP,
)

_PAGE = 0x1000
_HEAP = 0x20000000
_STACK = 0x30000000
_OLD, _NEW = _HEAP, _HEAP + _PAGE
_OLD_BODY, _NEW_BODY = _HEAP + 2 * _PAGE, _HEAP + 3 * _PAGE
_VTABLE = _HEAP + 4 * _PAGE


def _swap(data: bytes | bytearray, sequence: int, old: tuple[float, float], new_max: float):
    """Run one health hand-over out of `data` and return the new body's current health, plus
    `ebx` and `esp` as the sequence left them.

    `old` is the old body's `(current, max)`; the new body starts at `new_max` of `new_max`, as a
    freshly built object does."""
    uc = Uc(UC_ARCH_X86, UC_MODE_32)
    length = len(TOGGLE_MOUNTED_HEALTH_COPY_SEQUENCE)
    cave = find_section(data, SECTION_NAME)
    pages = {sequence & ~0xFFF, BODY_ZERO & ~0xFFF, _STACK}
    pages |= {va & ~0xFFF for va, _ in GETTERS.values()}
    pages |= {_OLD, _NEW, _OLD_BODY, _NEW_BODY, _VTABLE}
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

    uc.mem_write(sequence, _read(data, sequence, length))
    if cave is not None:
        uc.mem_write(cave[0], _read(data, cave[0], len(build_code())))
    for slot, (va, body) in GETTERS.items():
        uc.mem_write(va, body)
        uc.mem_write(_VTABLE + slot, struct.pack("<I", va))
    for obj, body, (current, maximum) in (
        (_OLD, _OLD_BODY, old),
        (_NEW, _NEW_BODY, (new_max, new_max)),
    ):
        uc.mem_write(obj + OBJECT_BODY_MODULE, struct.pack("<I", body))
        uc.mem_write(body, struct.pack("<I", _VTABLE))
        uc.mem_write(body + 0x08, struct.pack("<f", current))
        uc.mem_write(body + 0x10, struct.pack("<f", maximum))

    esp = _STACK + 0x800
    uc.reg_write(UC_X86_REG_ESP, esp)
    uc.reg_write(UC_X86_REG_EBP, esp + 0x40)
    uc.reg_write(UC_X86_REG_ESI, _NEW)
    uc.reg_write(UC_X86_REG_EDI, _OLD)
    uc.emu_start(sequence, sequence + length, count=64)
    (health,) = struct.unpack("<f", bytes(uc.mem_read(_NEW_BODY + 0x08, 4)))
    return health, uc.reg_read(UC_X86_REG_EBX), uc.reg_read(UC_X86_REG_ESP) - esp


@pytest.mark.parametrize("sequence", SEQUENCES, ids=("mount", "dismount"))
class TestTheHandOverRuns:
    """The WildZuchtdracheOld pair: 5600 on the ground, 5000 in the air."""

    def test_stock_copies_hit_points(self, image: bytearray, sequence: int) -> None:
        health, _ebx, _esp = _swap(image, sequence, old=(5600.0, 5600.0), new_max=5000.0)
        assert health == 5600.0  # above the flying form's maximum

    def test_patched_keeps_full_health_full(self, patched: bytearray, sequence: int) -> None:
        health, _ebx, _esp = _swap(patched, sequence, old=(5600.0, 5600.0), new_max=5000.0)
        assert health == pytest.approx(5000.0)

    def test_patched_keeps_the_fraction_both_ways(self, patched: bytearray, sequence: int) -> None:
        up, _ebx, _esp = _swap(patched, sequence, old=(2800.0, 5600.0), new_max=5000.0)
        assert up == pytest.approx(2500.0)
        down, _ebx, _esp = _swap(patched, sequence, old=(up, 5000.0), new_max=5600.0)
        assert down == pytest.approx(2800.0)

    def test_a_zero_maximum_stores_zero(self, patched: bytearray, sequence: int) -> None:
        """The ratio getter answers 0 for a body with no maximum, rather than dividing by it."""
        health, _ebx, _esp = _swap(patched, sequence, old=(10.0, 0.0), new_max=5000.0)
        assert health == 0.0

    def test_the_swap_keeps_its_registers(self, patched: bytearray, sequence: int) -> None:
        """`ebx` is the new body's vtable before the hook and must be after it; the stack has to
        come back where the stock sequence leaves it."""
        _health, stock_ebx, stock_esp = _swap(
            mount_health_ratio_image(), sequence, old=(1.0, 2.0), new_max=4.0
        )
        _health, ebx, esp = _swap(patched, sequence, old=(1.0, 2.0), new_max=4.0)
        assert (ebx, esp) == (stock_ebx, stock_esp) == (_VTABLE, 0)


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

    def test_both_sequences_are_stock(self, which: str) -> None:
        stock = self._stock(which)
        for va in SEQUENCES:
            assert _read(stock, va, len(TOGGLE_MOUNTED_HEALTH_COPY_SEQUENCE)) == (
                TOGGLE_MOUNTED_HEALTH_COPY_SEQUENCE
            )

    def test_the_emulated_getters_are_the_engines(self, which: str) -> None:
        """The emulation plants these bytes behind these slots; this is what entitles it to."""
        stock = self._stock(which)
        for slot, (va, body) in GETTERS.items():
            assert struct.unpack("<I", _read(stock, ACTIVE_BODY_VTABLE + slot, 4))[0] == va
            assert _read(stock, va, len(body)) == body
        assert _read(stock, BODY_ZERO, 4) == bytes(4)

    def test_apply_verify_detect_round_trip(self, which: str) -> None:
        data = bytearray(self._stock(which))
        MountHealthRatioPatch().apply(data)
        assert MountHealthRatioPatch().verify(data) == []
        assert isinstance(MountHealthRatioPatch.detect(data), MountHealthRatioPatch)
