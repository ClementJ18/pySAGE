"""Tests for the lobby-faction-byte patch.

The caves are small, but each depends on registers and frame slots that only the stock code
around its call site gives meaning to: the seat in `esi` on the way out, and on the way in the
cursor in `ebx`, its checked copy at `[ebp-0x14]` and the payload end at `[ebp-0x10]`. So beyond
reading the caves back, the real arms run under unicorn - the packer's from the colour load to its
byte write and the parser's from the cursor check to its unpack - on the stock image and the
patched one, and what one writes is what the other reads.
"""

from __future__ import annotations

import faulthandler
import struct

import pytest

from sage_patch.addresses import (
    LAN_FACTION_READ_AI,
    LAN_FACTION_READ_HUMAN,
    LAN_PACK_NIBBLES,
    LAN_UNPACK_NIBBLES,
    LAN_WRITE_BYTE,
)
from sage_patch.patches.lobby_faction_byte import (
    ANCHORS,
    MISSING_TEMPLATE,
    READ_SITES,
    SECTION_NAME,
    WRITE_SITES,
    LobbyFactionBytePatch,
    build_code,
    entry_points,
)
from sage_patch.registry import PATCHES
from sage_patch.utils import call_rel32, find_section, va_to_offset
from tests.sage_patch.synthetic import lobby_faction_byte_image


def _read(data: bytes | bytearray, va: int, n: int) -> bytes:
    off = va_to_offset(data, va)
    assert off is not None, f"0x{va:08x} is not mapped"
    return bytes(data[off : off + n])


def _cave_va(data: bytes | bytearray) -> int:
    located = find_section(data, SECTION_NAME)
    assert located is not None, f"no {SECTION_NAME} section"
    return located[0]


def _call_va(window: tuple[int, bytes]) -> int:
    return window[0] + len(window[1]) - 5


@pytest.fixture
def image() -> bytearray:
    return lobby_faction_byte_image()


@pytest.fixture
def patched() -> bytearray:
    data = lobby_faction_byte_image()
    LobbyFactionBytePatch().apply(data)
    return data


class TestStructure:
    def test_each_window_ends_in_the_call_it_replaces(self) -> None:
        for window in WRITE_SITES:
            assert window[1][-5:] == call_rel32(_call_va(window), LAN_WRITE_BYTE)
        for window in READ_SITES:
            assert window[1][-5:] == call_rel32(_call_va(window), LAN_UNPACK_NIBBLES)

    def test_each_packer_arm_packs_colour_and_template(self) -> None:
        # mov ecx, [esi+0xc] / push -2 / mov [ebp+0xc], eax / mov eax, [esi+0x18] / push -1 /
        # push eax / push ecx / call LAN_PACK_NIBBLES
        for va, stock in WRITE_SITES:
            assert stock[:15] == bytes.fromhex("8b4e0c6afe89450c8b46186aff5051")
            assert stock[15:20] == call_rel32(va + 15, LAN_PACK_NIBBLES)

    def test_only_the_four_calls_change(self, image: bytearray, patched: bytearray) -> None:
        cave = _cave_va(patched)
        write_va, read_va = entry_points(cave)
        for window, target in (
            *((w, write_va) for w in WRITE_SITES),
            *((r, read_va) for r in READ_SITES),
        ):
            va, stock = window
            got = _read(patched, va, len(stock))
            assert got[:-5] == stock[:-5]
            assert got[-5:] == call_rel32(_call_va(window), target)
        for va, stock in ANCHORS.items():
            assert _read(patched, va, len(stock)) == stock

    def test_the_caves_decode_as_written(self, patched: bytearray) -> None:
        capstone = pytest.importorskip("capstone")
        md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
        cave = _cave_va(patched)
        code = build_code(cave)
        assert _read(patched, cave, len(code)) == code
        write_va, read_va = entry_points(cave)
        listing = [f"{i.mnemonic} {i.op_str}" for i in md.disasm(code, cave)]
        assert listing == [
            "mov eax, dword ptr [esp + 4]",
            "push dword ptr [esp + 0xc]",
            "push dword ptr [esi + 0xc]",
            "push eax",
            f"call {LAN_WRITE_BYTE:#x}",
            "add esp, 0xc",
            "push dword ptr [esp + 0xc]",
            "push dword ptr [esi + 0x18]",
            "push eax",
            f"call {LAN_WRITE_BYTE:#x}",
            "add esp, 0xc",
            "ret ",
            "mov eax, dword ptr [esp + 4]",
            "mov ecx, dword ptr [esp + 0x10]",
            "mov byte ptr [ecx], al",
            "mov ecx, dword ptr [esp + 0x14]",
            "mov byte ptr [ecx], 0x80",
            "cmp ebx, dword ptr [ebp - 0x10]",
            f"jae {cave + len(code) - 1:#x}",  # the read cave's closing `ret`
            "mov al, byte ptr [ebx]",
            "mov byte ptr [ecx], al",
            "inc ebx",
            "mov dword ptr [ebp - 0x14], ebx",
            "ret ",
        ]
        assert write_va == cave


class TestLifecycle:
    def test_apply_verify_detect(self, patched: bytearray) -> None:
        assert LobbyFactionBytePatch().verify(patched) == []
        assert isinstance(LobbyFactionBytePatch.detect(patched), LobbyFactionBytePatch)

    def test_an_unpatched_image_is_not_detected(self, image: bytearray) -> None:
        assert LobbyFactionBytePatch().verify(image) != []
        assert LobbyFactionBytePatch.detect(image) is None

    def test_a_second_apply_refuses(self, patched: bytearray) -> None:
        with pytest.raises(ValueError, match="already carries this patch"):
            LobbyFactionBytePatch().apply(patched)

    def test_a_drifted_arm_refuses_before_writing(self, image: bytearray) -> None:
        """The read cave relies on the arm's `mov [ebp-0x14], ebx`; a build where that moved
        fails even though the hooked call is intact."""
        va, stock = READ_SITES[1]
        off = va_to_offset(image, va + stock.index(bytes.fromhex("895dec")) + 2)
        assert off is not None
        image[off] ^= 0xFF
        before = bytes(image)
        with pytest.raises(ValueError, match=f"@0x{va:08x}"):
            LobbyFactionBytePatch().apply(image)
        assert bytes(image) == before

    def test_a_missing_helper_refuses(self, image: bytearray) -> None:
        off = va_to_offset(image, LAN_WRITE_BYTE)
        assert off is not None
        image[off] = 0xCC
        with pytest.raises(ValueError, match=f"@0x{LAN_WRITE_BYTE:08x}"):
            LobbyFactionBytePatch().apply(image)

    def test_an_unhooked_arm_fails_verify(self, patched: bytearray) -> None:
        va = _call_va(READ_SITES[0])
        off = va_to_offset(patched, va)
        assert off is not None
        patched[off : off + 5] = call_rel32(va, LAN_UNPACK_NIBBLES)
        assert any("parser's human arm" in p for p in LobbyFactionBytePatch().verify(patched))

    def test_registered_as_settled(self) -> None:
        assert PATCHES["lobby-faction-byte"] is LobbyFactionBytePatch
        assert not LobbyFactionBytePatch.experimental


unicorn = pytest.importorskip("unicorn", reason="the emulator harness needs unicorn")

from unicorn import UC_ARCH_X86, UC_HOOK_CODE, UC_MODE_32, Uc  # noqa: E402
from unicorn.x86_const import (  # noqa: E402
    UC_X86_REG_EAX,
    UC_X86_REG_EBP,
    UC_X86_REG_EBX,
    UC_X86_REG_EDI,
    UC_X86_REG_EIP,
    UC_X86_REG_ESI,
    UC_X86_REG_ESP,
)

_PAGE = 0x1000
_HEAP = 0x20000000
_STACK = 0x30000000
_STUBS = 0x40000000

#: The block copy `LAN_WRITE_BYTE` delegates to - `(dst, src, n, end) -> dst + n`, or `dst` when
#: it would not fit - and the CRT `memcpy` thunk it calls. Not hooked or anchored by the patch, so
#: not in the stand-in image; the harness plants them so the writer runs as the engine's own.
_WRITE_BLOCK = 0x0084A4B5
_WRITE_BLOCK_BYTES = bytes.fromhex(
    "558bec837d1400568b7508578b7d1074113b751477088d043e3b451476048bc6eb10"
    "57ff750c56e8412a1f0083c40c8d043e5f5e5dc3"
)
_MEMCPY_THUNK = 0x00A3CF22
_MEMCPY_IAT = 0x00BD06C8
#: push esi / push edi / mov edi, [esp+0xc] / mov esi, [esp+0x10] / mov ecx, [esp+0x14] /
#: mov eax, edi / rep movsb / pop edi / pop esi / ret
_MEMCPY = bytes.fromhex("56578b7c240c8b7424108b4c241489f8f3a45f5ec3")

#: Where each parser arm bails out on a bad cursor or value.
_REJECT = 0x0084B9B5
#: The frame slots each parser arm keeps the packed byte, the colour and the template in.
_PARSER_LOCALS = {
    LAN_FACTION_READ_HUMAN: (-0x68, -0x1C, -0x1A),
    LAN_FACTION_READ_AI: (-0x64, -0x1D, -0x1B),
}


def _emulator(data: bytes | bytearray) -> Uc:
    uc = Uc(UC_ARCH_X86, UC_MODE_32)
    pages = {va & ~0xFFF for va, _ in (*WRITE_SITES, *READ_SITES)}
    pages |= {va & ~0xFFF for va in ANCHORS}
    pages |= {_WRITE_BLOCK & ~0xFFF, _MEMCPY_THUNK & ~0xFFF, _MEMCPY_IAT & ~0xFFF, _REJECT & ~0xFFF}
    pages |= {_HEAP, _STACK, _STUBS}
    cave = find_section(data, SECTION_NAME)
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
    for va, stock in (*WRITE_SITES, *READ_SITES, *ANCHORS.items()):
        uc.mem_write(va, _read(data, va, len(stock)))
    if cave is not None:
        uc.mem_write(cave[0], _read(data, cave[0], len(build_code(cave[0]))))
    uc.mem_write(_WRITE_BLOCK, _WRITE_BLOCK_BYTES)
    uc.mem_write(_MEMCPY_THUNK, b"\xff\x25" + struct.pack("<I", _MEMCPY_IAT))
    uc.mem_write(_MEMCPY_IAT, struct.pack("<I", _STUBS))
    uc.mem_write(_STUBS, _MEMCPY)
    return uc


def _write_seat(
    data: bytes | bytearray, arm: tuple[int, bytes], colour: int, template: int
) -> bytes:
    """Run one packer arm for a seat and return the bytes it put on the wire."""
    uc = _emulator(data)
    seat, buf = _HEAP, _HEAP + 0x400
    uc.mem_write(seat + 0x0C, struct.pack("<i", colour))
    uc.mem_write(seat + 0x18, struct.pack("<i", template))
    esp = _STACK + 0x800
    uc.reg_write(UC_X86_REG_ESP, esp)
    uc.reg_write(UC_X86_REG_EBP, esp + 0x100)
    uc.reg_write(UC_X86_REG_ESI, seat)
    uc.reg_write(UC_X86_REG_EAX, buf)  # the cursor, as the arm before it leaves it
    uc.reg_write(UC_X86_REG_EDI, buf + 0x40)  # the end
    va, stock = arm
    uc.emu_start(va, va + len(stock), count=200)
    # The arm leaves its 7 arguments for the function's later `add esp`.
    assert uc.reg_read(UC_X86_REG_ESP) == esp - 0x1C
    end = uc.reg_read(UC_X86_REG_EAX)
    return bytes(uc.mem_read(buf, end - buf))


def _read_seat(
    data: bytes | bytearray, arm: tuple[int, bytes], wire: bytes
) -> tuple[int, int, int] | None:
    """Run one parser arm over `wire`, as the stock read of its first byte leaves it, and return
    `(colour, template, bytes consumed)` - or None if the arm rejected the message."""
    uc = _emulator(data)
    buf = _HEAP + 0x400
    uc.mem_write(buf, wire)
    esp = _STACK + 0x800
    ebp = esp + 0x100
    packed_slot, colour_slot, template_slot = _PARSER_LOCALS[arm[0]]
    uc.mem_write(ebp + packed_slot, struct.pack("<I", wire[0]))
    uc.mem_write(ebp - 0x14, struct.pack("<I", buf))  # the checked cursor, before that read
    uc.mem_write(ebp - 0x10, struct.pack("<I", buf + len(wire)))  # the end
    uc.reg_write(UC_X86_REG_ESP, esp - 0xC)  # the read call's three arguments, popped first
    uc.reg_write(UC_X86_REG_EBP, ebp)
    uc.reg_write(UC_X86_REG_EAX, buf + 1)  # the cursor past the first byte
    uc.hook_add(UC_HOOK_CODE, lambda emu, *_: emu.emu_stop(), begin=_REJECT, end=_REJECT)
    va, stock = arm
    stop = va + len(stock)
    uc.emu_start(va, stop, count=200)
    if uc.reg_read(UC_X86_REG_EIP) != stop:
        return None
    assert uc.reg_read(UC_X86_REG_ESP) == esp - 0x14  # the unpack's five, for the `add esp`
    cursor = uc.reg_read(UC_X86_REG_EBX)
    assert struct.unpack("<I", bytes(uc.mem_read(ebp - 0x14, 4)))[0] == cursor
    colour = struct.unpack("<b", bytes(uc.mem_read(ebp + colour_slot, 1)))[0]
    template = struct.unpack("<b", bytes(uc.mem_read(ebp + template_slot, 1)))[0]
    return colour, template, cursor - buf


#: `(colour, template)` seats: random and observer, the last template a nibble holds, and three
#: past it - the Edain factions this was found with sit at those indices.
SEATS = [(-1, -1), (0, -2), (9, 3), (14, 13), (0, 14), (1, 15), (4, 21)]
ARMS = [
    pytest.param(WRITE_SITES[0], READ_SITES[0], id="human"),
    pytest.param(WRITE_SITES[1], READ_SITES[1], id="ai"),
]


class TestTheWire:
    @pytest.mark.parametrize(("writer", "reader"), ARMS)
    @pytest.mark.parametrize(("colour", "template"), SEATS)
    def test_patched_round_trip(
        self,
        patched: bytearray,
        writer: tuple[int, bytes],
        reader: tuple[int, bytes],
        colour: int,
        template: int,
    ) -> None:
        wire = _write_seat(patched, writer, colour, template)
        assert wire == struct.pack("<bb", colour, template)
        assert _read_seat(patched, reader, wire + b"\x07") == (colour, template, 2)

    @pytest.mark.parametrize(("writer", "reader"), ARMS)
    def test_stock_overflows_template_14_into_the_colour(
        self, image: bytearray, writer: tuple[int, bytes], reader: tuple[int, bytes]
    ) -> None:
        """The bug: blue (0) playing template 14 reaches a client as red (1) observing (-2)."""
        wire = _write_seat(image, writer, 0, 14)
        assert wire == b"\x20"
        assert _read_seat(image, reader, wire + b"\x07") == (1, -2, 1)

    @pytest.mark.parametrize(("writer", "reader"), ARMS)
    def test_stock_round_trips_below_14(
        self, image: bytearray, writer: tuple[int, bytes], reader: tuple[int, bytes]
    ) -> None:
        wire = _write_seat(image, writer, 9, 13)
        assert _read_seat(image, reader, wire + b"\x07") == (9, 13, 1)

    @pytest.mark.parametrize("reader", [READ_SITES[0], READ_SITES[1]], ids=["human", "ai"])
    def test_a_payload_ending_after_the_colour_leaves_a_rejected_template(
        self, patched: bytearray, reader: tuple[int, bytes]
    ) -> None:
        """No byte is read past the end: the template stays at the sentinel, which the arm's own
        `cmp byte [template], -2 / jl` turns away, and the cursor does not move."""
        assert _read_seat(patched, reader, b"\x03") == (3, MISSING_TEMPLATE - 0x100, 1)
