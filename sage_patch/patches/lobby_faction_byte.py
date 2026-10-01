"""Send each lobby seat's faction and colour as a byte each, not a nibble each.

The LAN lobby's binary `GameInfo` - the host's options broadcast and its game announce - packs a
seat's colour and `PlayerTemplate` index into one byte, so only templates -2..13 survive the wire;
a later faction carries into the colour nibble and every client sees a different seat than the
host does. A `.lobfac` section replaces the packed byte with two, at the packer's two seat arms
(human, AI) and the parser's two. The parser's own range checks are left to judge both values.

Derivation: `../docs/lobby-faction-byte.md`.
"""

from __future__ import annotations

from ..addresses import (
    GAME_SLOT_COLOR,
    GAME_SLOT_PLAYER_TEMPLATE,
    LAN_FACTION_READ_AI,
    LAN_FACTION_READ_AI_BYTES,
    LAN_FACTION_READ_HUMAN,
    LAN_FACTION_READ_HUMAN_BYTES,
    LAN_FACTION_READ_NEXT_AI,
    LAN_FACTION_READ_NEXT_AI_BYTES,
    LAN_FACTION_READ_NEXT_HUMAN,
    LAN_FACTION_READ_NEXT_HUMAN_BYTES,
    LAN_FACTION_WRITE_AI,
    LAN_FACTION_WRITE_AI_BYTES,
    LAN_FACTION_WRITE_HUMAN,
    LAN_FACTION_WRITE_HUMAN_BYTES,
    LAN_PACK_NIBBLES,
    LAN_PACK_NIBBLES_BYTES,
    LAN_PARSE_CURSOR_EBP,
    LAN_PARSE_END_EBP,
    LAN_UNPACK_NIBBLES,
    LAN_UNPACK_NIBBLES_BYTES,
    LAN_WRITE_BYTE,
    LAN_WRITE_BYTE_BYTES,
)
from ..asm import JAE, Asm
from ..patcher import Patch
from ..utils import allocate_section, apply_byte_patch, call_rel32, file_offset, find_section

__all__ = [
    "ANCHORS",
    "MISSING_TEMPLATE",
    "READ_SITES",
    "SECTION_NAME",
    "WRITE_SITES",
    "LobbyFactionBytePatch",
    "build_code",
    "entry_points",
]

SECTION_NAME = ".lobfac"  # 7 chars: the PE name field is 8 bytes and truncates silently

#: What the reader leaves as the template when the payload ends before the second byte: -128,
#: which the parser's own `cmp byte [template], -2 / jl <reject>` refuses.
MISSING_TEMPLATE = 0x80

# IMAGE_SCN_CNT_CODE | MEM_EXECUTE | MEM_READ.
_CHARACTERISTICS = 0x20 | 0x20000000 | 0x40000000

#: `(window va, stock window)` for each arm. The hooked `call` is the window's last five bytes; the
#: rest is the register contract the cave relies on, so it is asserted along with it.
WRITE_SITES = (
    (LAN_FACTION_WRITE_HUMAN, LAN_FACTION_WRITE_HUMAN_BYTES),
    (LAN_FACTION_WRITE_AI, LAN_FACTION_WRITE_AI_BYTES),
)
READ_SITES = (
    (LAN_FACTION_READ_HUMAN, LAN_FACTION_READ_HUMAN_BYTES),
    (LAN_FACTION_READ_AI, LAN_FACTION_READ_AI_BYTES),
)

#: Everything else the patch assumes about this build: the byte writer the cave calls, the two
#: nibble helpers whose call sites it takes over, and each parser arm's next read, which has to
#: continue from `ebx` for advancing the cursor there to be enough.
ANCHORS = {
    LAN_WRITE_BYTE: LAN_WRITE_BYTE_BYTES,
    LAN_PACK_NIBBLES: LAN_PACK_NIBBLES_BYTES,
    LAN_UNPACK_NIBBLES: LAN_UNPACK_NIBBLES_BYTES,
    LAN_FACTION_READ_NEXT_HUMAN: LAN_FACTION_READ_NEXT_HUMAN_BYTES,
    LAN_FACTION_READ_NEXT_AI: LAN_FACTION_READ_NEXT_AI_BYTES,
}

_CURSOR = LAN_PARSE_CURSOR_EBP & 0xFF  # disp8, as encoded
_END = LAN_PARSE_END_EBP & 0xFF


def _call_va(window: tuple[int, bytes]) -> int:
    va, stock = window
    return va + len(stock) - 5


def _assemble(base_va: int) -> Asm:
    a = Asm(base_va)

    # Called in place of the arm's `call LAN_WRITE_BYTE`, with the same cdecl arguments - cursor,
    # packed byte, end - which the caller pops. The packed byte is ignored; the seat is still in
    # `esi`, so the colour and the template are written from it, each as its own signed byte.
    a.label("write")
    a.emit(0x8B, 0x44, 0x24, 0x04)  # mov eax, [esp+4]          ; cursor
    a.emit(0xFF, 0x74, 0x24, 0x0C)  # push dword [esp+0xc]      ; end
    a.emit(0xFF, 0x76, GAME_SLOT_COLOR)  # push dword [esi+0xc]
    a.emit(0x50)  # push eax
    a.call_absolute(LAN_WRITE_BYTE)
    a.emit(0x83, 0xC4, 0x0C)  # add esp, 0xc
    a.emit(0xFF, 0x74, 0x24, 0x0C)  # push dword [esp+0xc]      ; end
    a.emit(0xFF, 0x76, GAME_SLOT_PLAYER_TEMPLATE)  # push dword [esi+0x18]
    a.emit(0x50)  # push eax
    a.call_absolute(LAN_WRITE_BYTE)
    a.emit(0x83, 0xC4, 0x0C)  # add esp, 0xc
    a.emit(0xC3)  # ret                       ; eax = the cursor past both

    # Called in place of the arm's `call LAN_UNPACK_NIBBLES`, with its cdecl arguments - the byte
    # already read, -1, -2, &colour, &template - which the caller pops. That byte is the colour.
    # The template is the next one, taken from `ebx` when the payload still holds it; the cursor
    # and its checked copy both move past it, so the arm's next read starts after it. When the
    # payload has ended the template is left at -128 and the parser rejects the message itself.
    a.label("read")
    a.emit(0x8B, 0x44, 0x24, 0x04)  # mov eax, [esp+4]
    a.emit(0x8B, 0x4C, 0x24, 0x10)  # mov ecx, [esp+0x10]       ; &colour
    a.emit(0x88, 0x01)  # mov [ecx], al
    a.emit(0x8B, 0x4C, 0x24, 0x14)  # mov ecx, [esp+0x14]       ; &template
    a.emit(0xC6, 0x01, MISSING_TEMPLATE)  # mov byte [ecx], 0x80
    a.emit(0x3B, 0x5D, _END)  # cmp ebx, [ebp-0x10]
    a.jcc_short(JAE, "read_out")
    a.emit(0x8A, 0x03)  # mov al, [ebx]
    a.emit(0x88, 0x01)  # mov [ecx], al
    a.emit(0x43)  # inc ebx
    a.emit(0x89, 0x5D, _CURSOR)  # mov [ebp-0x14], ebx
    a.label("read_out")
    a.emit(0xC3)  # ret
    return a


def build_code(base_va: int) -> bytes:
    """The cave, laid out at `base_va`."""
    return _assemble(base_va).finish()


def entry_points(base_va: int) -> tuple[int, int]:
    """`(write, read)` - the virtual address each kind of hook calls."""
    a = _assemble(base_va)
    a.finish()
    return a.label_va("write"), a.label_va("read")


def _hooks(base_va: int) -> list[tuple[int, bytes, int, str]]:
    """`(call va, stock call, cave target, what)` for all four arms."""
    write_va, read_va = entry_points(base_va)
    arms = (
        (WRITE_SITES[0], LAN_WRITE_BYTE, write_va, "packer's human arm"),
        (WRITE_SITES[1], LAN_WRITE_BYTE, write_va, "packer's AI arm"),
        (READ_SITES[0], LAN_UNPACK_NIBBLES, read_va, "parser's human arm"),
        (READ_SITES[1], LAN_UNPACK_NIBBLES, read_va, "parser's AI arm"),
    )
    return [
        (_call_va(window), call_rel32(_call_va(window), helper), target, what)
        for window, helper, target, what in arms
    ]


class LobbyFactionBytePatch(Patch):
    name = "lobby-faction-byte"
    author = "officialNecro"
    description = (
        "Send each LAN lobby seat's faction and colour as a byte each instead of a nibble each, "
        "so a seat playing a PlayerTemplate at index 14 or later reaches the clients as the "
        "host set it, rather than overflowing into the seat's colour. Every peer in the lobby "
        "needs the same binary. No INI change"
    )

    def apply(self, data: bytearray) -> None:
        self._check_sites(data)
        section_va = allocate_section(data, SECTION_NAME, build_code, _CHARACTERISTICS)
        for va, stock, target, what in _hooks(section_va):
            note = f"LAN lobby {what} -> {SECTION_NAME}"
            apply_byte_patch(data, file_offset(data, va), stock, call_rel32(va, target), note)

    @staticmethod
    def _check_sites(data: bytes | bytearray) -> None:
        """Raise unless every arm is stock across its whole window - the caves read `esi`, `ebx`
        and two frame slots that only the code around the call gives a meaning - and unless the
        routines they call or replace are the ones read."""
        for va, expected in (*WRITE_SITES, *READ_SITES, *ANCHORS.items()):
            off = file_offset(data, va)
            got = bytes(data[off : off + len(expected)])
            if got != expected:
                raise ValueError(
                    f"@0x{va:08x}: expected {expected.hex()}, got {got.hex()} - the file is not "
                    "the expected build, or already carries this patch"
                )

    def verify(self, data: bytes | bytearray) -> list[str]:
        located = find_section(data, SECTION_NAME)
        if located is None:
            return [f"no {SECTION_NAME} section: the file does not carry this patch"]
        section_va, section_off, vsize = located
        problems: list[str] = []
        code = build_code(section_va)
        if vsize < len(code) or bytes(data[section_off : section_off + len(code)]) != code:
            problems.append(f"the routines in {SECTION_NAME} are not the ones this patch builds")
        for va, _stock, target, what in _hooks(section_va):
            want = call_rel32(va, target)
            off = file_offset(data, va)
            got = bytes(data[off : off + len(want)])
            if got != want:
                problems.append(f"@0x{va:08x}: the {what} is not hooked (holds {got.hex()})")
        return problems
