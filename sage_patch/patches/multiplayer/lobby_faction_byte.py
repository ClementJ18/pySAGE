"""Send each lobby seat's faction and colour as a byte each, not a nibble each.

The LAN lobby's binary `GameInfo` - the host's options broadcast and its game announce - packs a
seat's colour and `PlayerTemplate` index into one byte, so only templates -2..13 survive the wire;
a later faction carries into the colour nibble and every client sees a different seat than the
host does. A `.lobfac` section replaces the packed byte with two, at the packer's two seat arms
(human, AI) and the parser's two. The parser's own range checks are left to judge both values.

A seat on a **faction-variants** Random pool, whose template no byte can hold, goes out as
`LAN_POOL_ESCAPE` followed by the pool's three mask bytes, and each parser arm puts the pool back
together where it hands the seat its template. Without faction-variants no seat holds a pool and
the parser refuses the escape byte, so the extra code never runs.

Derivation: `../docs/lobby-faction-byte.md`.
"""

from __future__ import annotations

from ...addresses import (
    GAME_SLOT_COLOR,
    GAME_SLOT_PLAYER_TEMPLATE,
    GAME_SLOT_SET_PLAYER_TEMPLATE,
    LAN_FACTION_READ_AI,
    LAN_FACTION_READ_AI_BYTES,
    LAN_FACTION_READ_HUMAN,
    LAN_FACTION_READ_HUMAN_BYTES,
    LAN_FACTION_READ_NEXT_AI,
    LAN_FACTION_READ_NEXT_AI_BYTES,
    LAN_FACTION_READ_NEXT_HUMAN,
    LAN_FACTION_READ_NEXT_HUMAN_BYTES,
    LAN_FACTION_SET_TEMPLATE_AI,
    LAN_FACTION_SET_TEMPLATE_AI_BYTES,
    LAN_FACTION_SET_TEMPLATE_HUMAN,
    LAN_FACTION_SET_TEMPLATE_HUMAN_BYTES,
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
from ...asm import JA, JAE, JE, JL, JNE, Asm
from ...patcher import Patch
from ...utils import allocate_section, apply_byte_patch, call_rel32, file_offset, find_section, u32
from .faction_variants import LAN_POOL_ESCAPE, RANDOM_POOL, RANDOM_POOL_BITS

__all__ = [
    "ANCHORS",
    "MISSING_TEMPLATE",
    "READ_SITES",
    "SECTION_NAME",
    "SET_TEMPLATE_SITES",
    "WRITE_SITES",
    "LobbyFactionBytePatch",
    "build_code",
    "entry_points",
]

SECTION_NAME = ".lobfac"  # 7 chars: the PE name field is 8 bytes and truncates silently

#: What the reader leaves as the template when the payload ends before the template, or before a
#: pool's mask: 127, which the parser's own `template < template count` check refuses - whatever
#: lower bound another patch has given it.
MISSING_TEMPLATE = 0x7F

# CNT_CODE | CNT_INITIALIZED_DATA | MEM_EXECUTE | MEM_READ | MEM_WRITE: code, and the pool the
# reader has just taken off the wire.
_CHARACTERISTICS = 0x20 | 0x40 | 0x20000000 | 0x40000000 | 0x80000000

#: Ahead of the code: the pool the last escape byte carried, until the arm hands it to the seat.
_PENDING_OFF = 0
_CODE_OFF = 4
_ESCAPE = LAN_POOL_ESCAPE & 0xFF
_MASK_BITS = (1 << RANDOM_POOL_BITS) - 1
_TAG_BITS = 0xFFFFFFFF & ~_MASK_BITS

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
#: Each parser arm's `push edi / mov ecx, esi / call GAME_SLOT_SET_PLAYER_TEMPLATE`.
SET_TEMPLATE_SITES = (
    (LAN_FACTION_SET_TEMPLATE_HUMAN, LAN_FACTION_SET_TEMPLATE_HUMAN_BYTES),
    (LAN_FACTION_SET_TEMPLATE_AI, LAN_FACTION_SET_TEMPLATE_AI_BYTES),
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
    pending = base_va + _PENDING_OFF
    a = Asm(base_va + _CODE_OFF)

    # Called in place of the arm's `call LAN_WRITE_BYTE`, with the same cdecl arguments - cursor,
    # packed byte, end - which the caller pops. The packed byte is ignored; the seat is still in
    # `esi`, so the colour and the template are written from it, each as its own signed byte. A
    # Random pool is the escape byte and its mask's three bytes, low first. A pool there is no
    # room left for becomes plain Random on the host too, so every peer draws alike.
    a.label("write")
    a.emit(0x8B, 0x44, 0x24, 0x04)  # mov eax, [esp+4]          ; cursor
    a.emit(0xFF, 0x74, 0x24, 0x0C)  # push dword [esp+0xc]      ; end
    a.emit(0xFF, 0x76, GAME_SLOT_COLOR)  # push dword [esi+0xc]
    a.emit(0x50)  # push eax
    a.call_absolute(LAN_WRITE_BYTE)
    a.emit(0x83, 0xC4, 0x0C)  # add esp, 0xc
    a.emit(0x8B, 0x4E, GAME_SLOT_PLAYER_TEMPLATE)  # mov ecx, [esi+0x18]
    a.emit(0x8B, 0xD1)  # mov edx, ecx
    a.emit(0x81, 0xE2, u32(_TAG_BITS))  # and edx, 0xff000000
    a.emit(0x81, 0xFA, u32(RANDOM_POOL & 0xFFFFFFFF))  # cmp edx, 0x80000000
    a.jcc(JNE, "write_template")
    a.emit(0xF7, 0xC1, u32(_MASK_BITS))  # test ecx, 0xffffff
    a.jcc(JE, "write_dropped")  # the tag alone: Random as it draws, not template 0
    a.emit(0x8B, 0x54, 0x24, 0x0C)  # mov edx, [esp+0xc]       ; end
    a.emit(0x2B, 0xD0)  # sub edx, eax
    a.emit(0x83, 0xFA, 0x04)  # cmp edx, 4
    a.jcc(JL, "write_dropped")
    a.emit(0x53)  # push ebx
    a.emit(0x8B, 0xD9)  # mov ebx, ecx                 ; the pool
    a.emit(0x6A, _ESCAPE)  # push 0x80                      ; the escape byte,
    a.emit(0x59)  # pop ecx
    for _ in range(4):
        a.emit(0xFF, 0x74, 0x24, 0x10)  # push dword [esp+0x10]     ; end
        a.emit(0x51)  # push ecx
        a.emit(0x50)  # push eax
        a.call_absolute(LAN_WRITE_BYTE)
        a.emit(0x83, 0xC4, 0x0C)  # add esp, 0xc
        a.emit(0x0F, 0xB6, 0xCB)  # movzx ecx, bl                ; then the mask, low first
        a.emit(0xC1, 0xEB, 0x08)  # shr ebx, 8
    a.emit(0x5B)  # pop ebx
    a.emit(0xC3)  # ret                       ; eax = the cursor past it all
    a.label("write_dropped")
    a.emit(0x83, 0x4E, GAME_SLOT_PLAYER_TEMPLATE, 0xFF)  # or dword [esi+0x18], -1
    a.emit(0x83, 0xC9, 0xFF)  # or ecx, -1
    a.label("write_template")
    a.emit(0xFF, 0x74, 0x24, 0x0C)  # push dword [esp+0xc]      ; end
    a.emit(0x51)  # push ecx
    a.emit(0x50)  # push eax
    a.call_absolute(LAN_WRITE_BYTE)
    a.emit(0x83, 0xC4, 0x0C)  # add esp, 0xc
    a.emit(0xC3)  # ret                       ; eax = the cursor past both

    # Called in place of the arm's `call LAN_UNPACK_NIBBLES`, with its cdecl arguments - the byte
    # already read, -1, -2, &colour, &template - which the caller pops. That byte is the colour.
    # The template is the next one, taken from `ebx` when the payload still holds it; the cursor
    # and its checked copy both move past it, so the arm's next read starts after it. The escape
    # byte takes its three mask bytes with it, and leaves the pool for `set_template`. When the
    # payload ends first the template is left at `MISSING_TEMPLATE` and the parser rejects the
    # message itself.
    a.label("read")
    a.emit(0x8B, 0x44, 0x24, 0x04)  # mov eax, [esp+4]
    a.emit(0x8B, 0x4C, 0x24, 0x10)  # mov ecx, [esp+0x10]       ; &colour
    a.emit(0x88, 0x01)  # mov [ecx], al
    a.emit(0x8B, 0x4C, 0x24, 0x14)  # mov ecx, [esp+0x14]       ; &template
    a.emit(0xC6, 0x01, MISSING_TEMPLATE)  # mov byte [ecx], 0x7f
    a.emit(0x83, 0x25, u32(pending), 0x00)  # and dword [pending], 0
    a.emit(0x3B, 0x5D, _END)  # cmp ebx, [ebp-0x10]
    a.jcc_short(JAE, "read_out")
    a.emit(0x8A, 0x03)  # mov al, [ebx]
    a.emit(0x3C, _ESCAPE)  # cmp al, 0x80
    a.jcc_short(JNE, "read_template")
    a.emit(0x8D, 0x53, 0x04)  # lea edx, [ebx+4]
    a.emit(0x3B, 0x55, _END)  # cmp edx, [ebp-0x10]
    a.jcc_short(JA, "read_out")  # the mask is cut off
    a.emit(0x0F, 0xB6, 0x53, 0x03)  # movzx edx, byte [ebx+3]
    a.emit(0xC1, 0xE2, 0x10)  # shl edx, 16
    a.emit(0x66, 0x8B, 0x53, 0x01)  # mov dx, [ebx+1]
    a.emit(0x81, 0xCA, u32(RANDOM_POOL & 0xFFFFFFFF))  # or edx, 0x80000000
    a.emit(0x89, 0x15, u32(pending))  # mov [pending], edx
    a.emit(0x88, 0x01)  # mov [ecx], al
    a.emit(0x83, 0xC3, 0x04)  # add ebx, 4
    a.emit(0x89, 0x5D, _CURSOR)  # mov [ebp-0x14], ebx
    a.emit(0xC3)  # ret
    a.label("read_template")
    a.emit(0x88, 0x01)  # mov [ecx], al
    a.emit(0x43)  # inc ebx
    a.emit(0x89, 0x5D, _CURSOR)  # mov [ebp-0x14], ebx
    a.label("read_out")
    a.emit(0xC3)  # ret

    # Called in place of each parser arm's `call GAME_SLOT_SET_PLAYER_TEMPLATE` - `thiscall`, the
    # template at `[esp+4]`, `ret 4`, which it jumps on to. The escape byte becomes the pool
    # `read` took off the wire; an escape with none is plain Random.
    a.label("set_template")
    a.emit(0x83, 0x7C, 0x24, 0x04, _ESCAPE)  # cmp dword [esp+4], -128
    a.jcc_short(JNE, "set_template_go")
    a.emit(0xA1, u32(pending))  # mov eax, [pending]
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc_short(JNE, "set_template_pool")
    a.emit(0x83, 0xC8, 0xFF)  # or eax, -1
    a.label("set_template_pool")
    a.emit(0x89, 0x44, 0x24, 0x04)  # mov [esp+4], eax
    a.label("set_template_go")
    a.emit(0x83, 0x25, u32(pending), 0x00)  # and dword [pending], 0
    a.jmp_absolute(GAME_SLOT_SET_PLAYER_TEMPLATE)
    return a


def build_code(base_va: int) -> bytes:
    """The cave, laid out at `base_va`: the zeroed pending pool, then the code."""
    return bytes(_CODE_OFF) + _assemble(base_va).finish()


def entry_points(base_va: int) -> tuple[int, int, int]:
    """`(write, read, set_template)` - the virtual address each kind of hook calls."""
    a = _assemble(base_va)
    a.finish()
    return a.label_va("write"), a.label_va("read"), a.label_va("set_template")


def _hooks(base_va: int) -> list[tuple[int, bytes, int, str]]:
    """`(call va, stock call, cave target, what)` for all six calls."""
    write_va, read_va, set_va = entry_points(base_va)
    arms = (
        (WRITE_SITES[0], LAN_WRITE_BYTE, write_va, "packer's human arm"),
        (WRITE_SITES[1], LAN_WRITE_BYTE, write_va, "packer's AI arm"),
        (READ_SITES[0], LAN_UNPACK_NIBBLES, read_va, "parser's human arm"),
        (READ_SITES[1], LAN_UNPACK_NIBBLES, read_va, "parser's AI arm"),
        (SET_TEMPLATE_SITES[0], GAME_SLOT_SET_PLAYER_TEMPLATE, set_va, "human arm's template"),
        (SET_TEMPLATE_SITES[1], GAME_SLOT_SET_PLAYER_TEMPLATE, set_va, "AI arm's template"),
    )
    return [
        (_call_va(window), call_rel32(_call_va(window), helper), target, what)
        for window, helper, target, what in arms
    ]


class LobbyFactionBytePatch(Patch):
    name = "lobby-faction-byte"
    author = "officialNecro"
    runtime_verified = "yes"
    description = (
        "Send each LAN lobby seat's faction and colour as a byte each instead of a nibble each, "
        "so a seat playing a PlayerTemplate at index 14 or later reaches the clients as the "
        "host set it, rather than overflowing into the seat's colour. A faction-variants Random "
        "pool travels as an escape byte and three mask bytes, and becomes plain Random when the "
        "packet has no room left for it. Every peer in the lobby needs the same binary. No INI "
        "change"
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
        for va, expected in (*WRITE_SITES, *READ_SITES, *SET_TEMPLATE_SITES, *ANCHORS.items()):
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
