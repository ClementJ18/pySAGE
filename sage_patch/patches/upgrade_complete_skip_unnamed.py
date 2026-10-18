"""Skip the top-right "upgrade complete" notice for an upgrade without a `DisplayName`.

When the local player's upgrade finishes, the engine posts `UPGRADE:UpgradeComplete` formatted
with the upgrade's `DisplayName` to the in-game message area. An upgrade with no `DisplayName`
(typically an internal one: a trigger, a counter, a hidden unlock) fetches the empty label and
shows `MISSING: ""`. The patch skips that one message when the label is empty. The radar event,
the EVA "research complete" event and the upgrade's sounds are unchanged, as is every upgrade that
has a name. Client-side only. No INI change.

Derivation: `../docs/upgrade-complete-skip-unnamed.md`.
"""

from __future__ import annotations

from ..addresses import (
    ASCII_STRING_CHARS_OFFSET,
    IN_GAME_UI_MESSAGE_SLOT,
    THE_IN_GAME_UI,
    UNICODE_STRING_DTOR,
    UPGRADE_COMPLETE_FORMAT_KEY,
    UPGRADE_COMPLETE_FORMAT_KEY_BYTES,
    UPGRADE_COMPLETE_MESSAGE,
    UPGRADE_COMPLETE_MESSAGE_BYTES,
    UPGRADE_TEMPLATE_DISPLAY_NAME,
)
from ..asm import JE, Asm
from ..patcher import Patch
from ..utils import allocate_section, apply_byte_patch, call_rel32, file_offset, find_section

__all__ = [
    "ANCHORS",
    "SECTION_NAME",
    "UpgradeCompleteSkipUnnamedPatch",
    "build_section",
    "replacement",
]

SECTION_NAME = ".upgmsg"

#: Read, never rewritten: the format key push, which pins this block as the upgrade-complete
#: notice, and `UnicodeString`'s destructor, which the cave calls.
ANCHORS: dict[int, bytes] = {
    UPGRADE_COMPLETE_FORMAT_KEY: UPGRADE_COMPLETE_FORMAT_KEY_BYTES,
    UNICODE_STRING_DTOR: bytes.fromhex("6aff68f80eb700"),
}

# CNT_CODE | MEM_EXECUTE | MEM_READ
_CHARACTERISTICS = 0x20 | 0x20000000 | 0x40000000

#: The eleven stock bytes become a five-byte call and six one-byte `nop`s.
_NOPS = bytes([0x90]) * (len(UPGRADE_COMPLETE_MESSAGE_BYTES) - 5)


def build_section(base_va: int) -> bytes:
    """`message_or_skip`: entered by `call` with `[esp+4]` the by-value format string and `edi`
    the `UpgradeTemplate`. It leaves the stack as the stock `push eax` / `call [ecx+0x40]` pair
    leaves it, one dword above the string, which the caller's next `add esp, 4` pops."""
    a = Asm(base_va)
    a.emit(0x8B, 0x47, UPGRADE_TEMPLATE_DISPLAY_NAME)  # mov eax, [edi+0x28]   ; DisplayName
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "skip")
    a.emit(0x80, 0x78, ASCII_STRING_CHARS_OFFSET, 0x00)  # cmp byte [eax+8], 0
    a.jcc(JE, "skip")
    # Named: what the stock bytes did, as a tail call returning to the caller.
    a.emit(0xA1, THE_IN_GAME_UI.to_bytes(4, "little"))  # mov eax, [TheInGameUI]
    a.emit(0x8B, 0x08)  # mov ecx, [eax]
    a.emit(0x5A)  # pop edx                       ; the return address
    a.emit(0x50)  # push eax                      ; this
    a.emit(0x52)  # push edx
    a.emit(0xFF, 0x61, IN_GAME_UI_MESSAGE_SLOT)  # jmp [ecx+0x40]
    # Unnamed: destroy the string the callee would have, keep the stack shape.
    a.label("skip")
    a.emit(0x8D, 0x4C, 0x24, 0x04)  # lea ecx, [esp+4]
    a.call_absolute(UNICODE_STRING_DTOR)
    a.emit(0x5A)  # pop edx
    a.emit(0x50)  # push eax                      ; the dword the caller pops
    a.emit(0x52)  # push edx
    a.emit(0xC3)  # ret
    return a.finish()


def replacement(base_va: int) -> bytes:
    return call_rel32(UPGRADE_COMPLETE_MESSAGE, base_va) + _NOPS


class UpgradeCompleteSkipUnnamedPatch(Patch):
    name = "upgrade-complete-skip-unnamed"
    author = "officialNecro"
    description = (
        "Skip the top-right 'upgrade complete' message for an upgrade with no DisplayName, which "
        'stock shows as MISSING: "". The EVA event, radar event and sounds still play, and named '
        "upgrades are unchanged. Client-side only. No INI change"
    )

    def apply(self, data: bytearray) -> None:
        for va, expected in {
            **ANCHORS,
            UPGRADE_COMPLETE_MESSAGE: UPGRADE_COMPLETE_MESSAGE_BYTES,
        }.items():
            self._check_stock(data, va, expected)
        base_va = allocate_section(data, SECTION_NAME, build_section, _CHARACTERISTICS)
        apply_byte_patch(
            data,
            file_offset(data, UPGRADE_COMPLETE_MESSAGE),
            UPGRADE_COMPLETE_MESSAGE_BYTES,
            replacement(base_va),
            "upgrade-complete notice -> skip it when the upgrade has no DisplayName",
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
        off = file_offset(data, UPGRADE_COMPLETE_MESSAGE)
        here = bytes(data[off : off + len(UPGRADE_COMPLETE_MESSAGE_BYTES)])
        if here != replacement(base_va):
            problems.append(f"@{UPGRADE_COMPLETE_MESSAGE:#010x}: the hook is not installed")
        return problems
