"""Show how many kills an object has at the bottom of its hover tooltip.

The engine already counts every object's kills (`OBJECT_KILLS`, bumped by the kill scorer on the
killer and on its battalion) and saves them, but no screen shows the number. This adds one line,
`TOOLTIP:Kills` formatted with the count, at the bottom of the tooltip an object shows when hovered
in the world. A battalion member shows its battalion's total, so the number does not reset when the
member dies and is replaced. Nothing is shown below one kill, and nothing when the string table has
no `TOOLTIP:Kills`, so a mod opts in by adding the string, e.g. `"Kills: %d"`. Client-side and
read-only. No INI change.

Derivation: `../docs/kill-count-tooltip.md`.
"""

from __future__ import annotations

from ..addresses import (
    GAME_TEXT_FORMAT_SLOT,
    KINDOF_HORDE_BIT,
    KINDOF_HORDE_BYTE,
    OBJECT_CONTAINED_BY,
    OBJECT_KILLS,
    OBJECT_SCORE_KILL_COUNT,
    OBJECT_SCORE_KILL_COUNT_BYTES,
    OBJECT_THING_TEMPLATE,
    OBJECT_TOOLTIP_APPEND_LINE,
    OBJECT_TOOLTIP_APPEND_LINE_BYTES,
    OBJECT_TOOLTIP_BATTLES_FOUGHT,
    OBJECT_TOOLTIP_BATTLES_FOUGHT_BYTES,
    OBJECT_TOOLTIP_DESCRIPTION_RELEASE,
    OBJECT_TOOLTIP_DESCRIPTION_RELEASE_BYTES,
    OBJECT_TOOLTIP_LINES_EBP,
    OBJECT_TOOLTIP_OBJECT_EBP,
    THE_GAME_TEXT,
    UNICODE_STRING_CONCAT,
    UNICODE_STRING_DTOR,
)
from ..asm import JE, JLE, JZ, Asm
from ..patcher import Patch
from ..utils import (
    allocate_section,
    apply_byte_patch,
    call_rel32,
    file_offset,
    find_section,
    i8,
    u32,
)

__all__ = [
    "ANCHORS",
    "ENTRY_OFFSET",
    "LABEL",
    "SECTION_NAME",
    "KillCountTooltipPatch",
    "build_section",
    "replacement",
]

SECTION_NAME = ".kills"

#: The string-table key the line is formatted from, with the count as its one `%d`. It heads the
#: section, and the code starts at `ENTRY_OFFSET` past it.
LABEL = b"TOOLTIP:Kills"
ENTRY_OFFSET = 0x10

#: Read, never rewritten. The kill scorer's increments pin `OBJECT_KILLS` and the horde mirror the
#: cave follows; the battles-fought line pins the record, the frame slots and the line idiom the
#: cave copies; the append helper and the destructor are called.
ANCHORS: dict[int, bytes] = {
    OBJECT_SCORE_KILL_COUNT: OBJECT_SCORE_KILL_COUNT_BYTES,
    OBJECT_TOOLTIP_BATTLES_FOUGHT: OBJECT_TOOLTIP_BATTLES_FOUGHT_BYTES,
    OBJECT_TOOLTIP_APPEND_LINE: OBJECT_TOOLTIP_APPEND_LINE_BYTES,
    UNICODE_STRING_DTOR: bytes.fromhex("6aff68f80eb700"),
}

# CNT_CODE | MEM_EXECUTE | MEM_READ
_CHARACTERISTICS = 0x20 | 0x20000000 | 0x40000000


def build_section(base_va: int) -> bytes:
    """`kills_line`: entered by the `call` that replaced the description's release, with `ecx` the
    description temporary and `ebp` the builder's frame. It adds the line and then makes the
    displaced call as a tail call, so `ecx` and every other register reach the destructor as the
    stock bytes left them."""
    a = Asm(base_va)
    a.emit(LABEL.ljust(ENTRY_OFFSET, b"\x00"))
    a.emit(0x60)  # pushad
    a.emit(0x8B, 0x75, i8(OBJECT_TOOLTIP_OBJECT_EBP))  # mov esi, [ebp-0x18]   ; hovered Object
    a.emit(0x85, 0xF6)  # test esi, esi
    a.jcc(JZ, "done")

    # A battalion member reports its battalion, whose count is the sum of its members' kills.
    a.emit(0x8B, 0x86, u32(OBJECT_CONTAINED_BY))  # mov eax, [esi+0x27c]
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JZ, "own")
    a.emit(0x8B, 0x50, OBJECT_THING_TEMPLATE)  # mov edx, [eax+4]
    a.emit(0xF6, 0x82, u32(KINDOF_HORDE_BYTE), KINDOF_HORDE_BIT)  # test byte [edx+0x115], 0x20
    a.jcc(JZ, "own")
    a.emit(0x8B, 0xF0)  # mov esi, eax

    a.label("own")
    a.emit(0x8B, 0x86, u32(OBJECT_KILLS))  # mov eax, [esi+0x48c]
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JLE, "done")

    # [ebx] = the fetch's `exists`, [ebx+4] = the line, an empty `UnicodeString`.
    a.emit(0x83, 0xEC, 0x08)  # sub esp, 8
    a.emit(0x83, 0x24, 0x24, 0x00)  # and dword [esp], 0
    a.emit(0x83, 0x64, 0x24, 0x04, 0x00)  # and dword [esp+4], 0
    a.emit(0x8B, 0xDC)  # mov ebx, esp

    # The battles-fought idiom: the count is pushed ahead of the fetch and survives it as the
    # format's vararg. `fetch(key, &exists)` is `__thiscall`, `ret 8`, and the caller does not own
    # the string it returns.
    a.emit(0x50)  # push eax                       ; the count
    a.emit(0x53)  # push ebx                       ; &exists
    a.emit(0x68, u32(base_va))  # push "TOOLTIP:Kills"
    a.emit(0x8B, 0x0D, u32(THE_GAME_TEXT))  # mov ecx, [TheGameText]
    a.emit(0x8B, 0x11)  # mov edx, [ecx]
    a.emit(0xFF, 0x52, GAME_TEXT_FORMAT_SLOT)  # call [edx+0x44]
    a.emit(0x83, 0x3B, 0x00)  # cmp dword [ebx], 0
    a.jcc(JE, "drop")

    # `0x00ADF7E0` replaces its destination, so it formats into the empty local, not the list.
    a.emit(0x50)  # push eax                       ; the format
    a.emit(0x8D, 0x43, 0x04)  # lea eax, [ebx+4]
    a.emit(0x50)  # push eax                       ; the line
    a.call_absolute(UNICODE_STRING_CONCAT)
    a.emit(0x83, 0xC4, 0x0C)  # add esp, 0xc     ; line, format, count
    a.emit(0x8D, 0x43, 0x04)  # lea eax, [ebx+4]
    a.emit(0x50)  # push eax
    a.emit(0x8D, 0x45, i8(OBJECT_TOOLTIP_LINES_EBP))  # lea eax, [ebp-0x1c]
    a.emit(0x50)  # push eax
    a.call_absolute(OBJECT_TOOLTIP_APPEND_LINE)
    a.emit(0x83, 0xC4, 0x08)  # add esp, 8
    a.emit(0x8D, 0x4B, 0x04)  # lea ecx, [ebx+4]
    a.call_absolute(UNICODE_STRING_DTOR)
    a.jmp("free")

    # No such key: the local was never formatted into and owns nothing, so only the count goes.
    a.label("drop")
    a.emit(0x58)  # pop eax

    a.label("free")
    a.emit(0x83, 0xC4, 0x08)  # add esp, 8

    a.label("done")
    a.emit(0x61)  # popad
    a.jmp_absolute(UNICODE_STRING_DTOR)  # the displaced call, returning to its own caller
    return a.finish()


def replacement(base_va: int) -> bytes:
    return call_rel32(OBJECT_TOOLTIP_DESCRIPTION_RELEASE, base_va + ENTRY_OFFSET)


class KillCountTooltipPatch(Patch):
    name = "kill-count-tooltip"
    author = "officialNecro"
    description = (
        "Add a kill count at the bottom of an object's hover tooltip, from the count the engine "
        "already keeps and saves. A battalion member shows its battalion's total. Formatted from "
        "TOOLTIP:Kills (one %d), so nothing shows until the string table has that key, and nothing "
        "below one kill. Client-side only. No INI change"
    )

    def apply(self, data: bytearray) -> None:
        for va, expected in {
            **ANCHORS,
            OBJECT_TOOLTIP_DESCRIPTION_RELEASE: OBJECT_TOOLTIP_DESCRIPTION_RELEASE_BYTES,
        }.items():
            self._check_stock(data, va, expected)
        base_va = allocate_section(data, SECTION_NAME, build_section, _CHARACTERISTICS)
        apply_byte_patch(
            data,
            file_offset(data, OBJECT_TOOLTIP_DESCRIPTION_RELEASE),
            OBJECT_TOOLTIP_DESCRIPTION_RELEASE_BYTES,
            replacement(base_va),
            "object tooltip, description release -> add the kills line first",
        )

    @staticmethod
    def _check_stock(data: bytes | bytearray, va: int, expected: bytes) -> None:
        off = file_offset(data, va)
        got = bytes(data[off : off + len(expected)])
        if got != expected:
            raise ValueError(
                f"{va:#010x} holds {got.hex()}, expected {expected.hex()} - the file is not "
                "the expected build, or already carries this patch"
            )

    def verify(self, data: bytes | bytearray) -> list[str]:
        located = find_section(data, SECTION_NAME)
        if located is None:
            return [f"no {SECTION_NAME} section: the file does not carry this patch"]
        base_va, section_off, vsize = located
        problems: list[str] = []
        expected = build_section(base_va)
        if (
            vsize < len(expected)
            or bytes(data[section_off : section_off + len(expected)]) != expected
        ):
            problems.append(f"the {SECTION_NAME} cave is not the one this patch builds")
        off = file_offset(data, OBJECT_TOOLTIP_DESCRIPTION_RELEASE)
        here = bytes(data[off : off + len(OBJECT_TOOLTIP_DESCRIPTION_RELEASE_BYTES)])
        if here != replacement(base_va):
            site = OBJECT_TOOLTIP_DESCRIPTION_RELEASE
            problems.append(f"@{site:#010x}: the hook is not installed")
        return problems
