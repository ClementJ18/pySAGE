"""Give a faction a working AI on a skirmish map that has no `Skirmish<Faction>` side for it.

A map holds at most twenty sides, many lack one per faction, and a faction without one becomes a
human player nobody drives. A `.skfall` section redirects two windows in `Player::initFromDict`:
when no side matches, the player falls back to its faction's `DefaultPlayerAIType` and runs that
type's library scripts. Skirmish only (the scan runs only for `playerIsSkirmish` players); never
overrides a side the map has.

Derivation: `../docs/skirmish-ai-fallback.md`.
"""

from __future__ import annotations

import struct

from ..addresses import (
    DICT_SET_ASCII_STRING,
    DICT_SET_ASCII_STRING_BYTES,
    KEY_PLAYER_AI_TYPE,
    KEY_PLAYER_AI_TYPE_BYTES,
    PLAYER_INDEX,
    PLAYER_INIT_FROM_DICT,
    PLAYER_INIT_FROM_DICT_BYTES,
    PLAYER_SET_TYPE,
    PLAYER_SET_TYPE_BYTES,
    PLAYER_SKIRMISH_FOUND_EBP,
    PLAYER_SKIRMISH_IMPORT,
    PLAYER_SKIRMISH_IMPORT_BYTES,
    PLAYER_SKIRMISH_IMPORT_SKIP,
    PLAYER_SKIRMISH_IMPORT_SKIP_BYTES,
    PLAYER_SKIRMISH_MISSING_EBP,
    PLAYER_SKIRMISH_ROUTE,
    PLAYER_SKIRMISH_ROUTE_BYTES,
    PLAYER_TEMPLATE_DEFAULT_AI_TYPE,
    PLAYER_TEMPLATE_FIELD_DEFAULT_AI_TYPE,
    PLAYER_TEMPLATE_FIELD_DEFAULT_AI_TYPE_BYTES,
    PLAYER_TEMPLATE_PTR,
    SIDES_INFO_DICT,
    SIDES_LIST_GET_SIDE_INFO,
    SIDES_LIST_GET_SIDE_INFO_BYTES,
    SIDES_LIST_LOAD_AI_LIBRARY_FOR_SIDE,
    SIDES_LIST_LOAD_AI_LIBRARY_FOR_SIDE_BYTES,
    STATIC_NAME_KEY_KEY,
    STATIC_NAME_KEY_KEY_BYTES,
    THE_SIDES_LIST,
    THE_SIDES_LIST_LOAD,
    THE_SIDES_LIST_LOAD_BYTES,
)
from ..asm import JE, JNE, Asm
from ..patcher import Patch
from ..utils import allocate_section, apply_byte_patch, find_section, va_to_offset

__all__ = [
    "ANCHORS",
    "SECTION_NAME",
    "SYNTHESISED",
    "SkirmishAiFallbackPatch",
    "build_code",
    "entry_points",
]

SECTION_NAME = ".skfall"  # 7 chars: the PE name field is 8 bytes and truncates silently

#: What the first hook writes into the found flag, and the second recognises. Any non-zero value
#: makes `setPlayerType` allocate an `AISkirmishPlayer`; a value other than 1 is what distinguishes
#: "no side, synthesised" from "a side genuinely matched" at the second hook, whose stock edges for
#: 0 and 1 must both survive untouched.
SYNTHESISED = 2

# IMAGE_SCN_CNT_CODE | MEM_EXECUTE | MEM_READ - the cave is pure code and is never written.
_CHARACTERISTICS = 0x20 | 0x20000000 | 0x40000000

#: The first bytes at each address the cave calls, jumps to or reads through, as a `{va: bytes}`
#: map. The two hook windows are asserted by `apply_byte_patch`; these are everything else the
#: assembly assumes about this build - the four engine routines, the resume point, the name-key
#: object, one load of `TheSidesList` inside the hooked function, and the field-table entry that
#: says where `DefaultPlayerAIType` lands in a `PlayerTemplate`. A build whose layout moved fails
#: here rather than on a wild call or a write into the middle of some other field.
ANCHORS = {
    PLAYER_INIT_FROM_DICT: PLAYER_INIT_FROM_DICT_BYTES,
    PLAYER_SKIRMISH_IMPORT_SKIP: PLAYER_SKIRMISH_IMPORT_SKIP_BYTES,
    PLAYER_SET_TYPE: PLAYER_SET_TYPE_BYTES,
    THE_SIDES_LIST_LOAD: THE_SIDES_LIST_LOAD_BYTES,
    SIDES_LIST_GET_SIDE_INFO: SIDES_LIST_GET_SIDE_INFO_BYTES,
    SIDES_LIST_LOAD_AI_LIBRARY_FOR_SIDE: SIDES_LIST_LOAD_AI_LIBRARY_FOR_SIDE_BYTES,
    DICT_SET_ASCII_STRING: DICT_SET_ASCII_STRING_BYTES,
    STATIC_NAME_KEY_KEY: STATIC_NAME_KEY_KEY_BYTES,
    KEY_PLAYER_AI_TYPE: KEY_PLAYER_AI_TYPE_BYTES,
    PLAYER_TEMPLATE_FIELD_DEFAULT_AI_TYPE: PLAYER_TEMPLATE_FIELD_DEFAULT_AI_TYPE_BYTES,
}

_FOUND = PLAYER_SKIRMISH_FOUND_EBP & 0xFF  # disp8, as encoded
_MISSING = PLAYER_SKIRMISH_MISSING_EBP & 0xFF


def _assemble(base_va: int) -> Asm:
    """Both routines, laid out in one cave. `route` is first, so it starts at `base_va`."""
    a = Asm(base_va)

    # Called in place of `cmp byte [ebp-0x25], al` / `jne 0x006B0A20`, and returns into the stock
    # fall-through. `ebp` is the hooked function's frame, so both flags are addressable here.
    #
    # Falling through rather than taking the stock branch is the whole point: the branch leads to
    # the arm that types the player 0 (human) and leaves it with no AI, while the fall-through is
    # the arm a player *with* a matching side takes. Returning unchanged when the flag is clear
    # preserves every other case - a matched AI, an observer, and every player in a game where the
    # scan never ran because the dict carries no `playerIsSkirmish`.
    a.label("route")
    a.emit(0x80, 0x7D, _MISSING, 0x00)  # cmp byte [ebp-0x25], 0
    a.jcc_short(JE, "route_out")
    a.emit(0xC6, 0x45, _MISSING, 0x00)  # mov byte [ebp-0x25], 0
    a.emit(0xC6, 0x45, _FOUND, SYNTHESISED)  # mov byte [ebp-0x20], 2
    a.label("route_out")
    a.emit(0xC3)  # ret

    # Called in place of `cmp byte [ebp-0x20], 0` / `je 0x006B102E`. Three cases: 0 keeps the stock
    # jump, 1 keeps the stock fall-through into the matched-side import, and 2 is ours.
    a.label("import")
    a.emit(0x8A, 0x45, _FOUND)  # mov al, [ebp-0x20]
    a.emit(0x84, 0xC0)  # test al, al
    a.jcc_short(JE, "skip")  # 0: nothing matched, nothing to import
    a.emit(0x3C, SYNTHESISED)  # cmp al, 2
    a.jcc_short(JNE, "matched")  # 1: the stock import, untouched

    # Synthesised. `esi` is the `Player` throughout the hooked function; `ebx`/`esi`/`edi` are all
    # live across the resume points (`edi` is the zero the continuation compares against), so the
    # body saves the three registers the engine keeps values in and clobbers only eax/ecx/edx,
    # which every call here already does.
    a.emit(0x53, 0x56, 0x57)  # push ebx / push esi / push edi
    a.emit(0x8B, 0x46, PLAYER_TEMPLATE_PTR)  # mov eax, [esi+0x34]   ; m_playerTemplate
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc_short(JE, "done")
    a.emit(0x05, struct.pack("<I", PLAYER_TEMPLATE_DEFAULT_AI_TYPE))  # add eax, 0x1b0
    a.emit(0x50)  # push eax              ; &value, arg 2
    a.emit(0xB9, struct.pack("<I", KEY_PLAYER_AI_TYPE))  # mov ecx, &TheKey_playerAIType
    a.call_absolute(STATIC_NAME_KEY_KEY)  # StaticNameKey::key()  -> eax, stack-neutral
    a.emit(0x50)  # push eax              ; key, arg 1
    a.emit(0xFF, 0x76, PLAYER_INDEX)  # push [esi+0x54]       ; m_playerIndex
    a.emit(0x8B, 0x0D, struct.pack("<I", THE_SIDES_LIST))  # mov ecx, [TheSidesList]
    a.call_absolute(SIDES_LIST_GET_SIDE_INFO)  # -> SidesInfo* (ret 4)
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc_short(JE, "unwind")  # out of range: drop the two args
    a.emit(0x8D, 0x48, SIDES_INFO_DICT)  # lea ecx, [eax+4]      ; &sideInfo->m_dict
    a.call_absolute(DICT_SET_ASCII_STRING)  # Dict::setAsciiString (ret 8)
    a.emit(0xFF, 0x76, PLAYER_INDEX)  # push [esi+0x54]
    a.emit(0x8B, 0x0D, struct.pack("<I", THE_SIDES_LIST))  # mov ecx, [TheSidesList]
    a.call_absolute(SIDES_LIST_LOAD_AI_LIBRARY_FOR_SIDE)  # merge our own library (ret 4)
    a.jmp_short("done")

    a.label("unwind")
    a.emit(0x83, 0xC4, 0x08)  # add esp, 8
    a.label("done")
    a.emit(0x5F, 0x5E, 0x5B)  # pop edi / pop esi / pop ebx

    # Both the stock 0-edge and the synthesised path continue where the engine's own "nothing to
    # import" jump went, so the cave discards its return address rather than coming back.
    a.label("skip")
    a.emit(0x83, 0xC4, 0x04)  # add esp, 4
    a.jmp_absolute(PLAYER_SKIRMISH_IMPORT_SKIP)

    a.label("matched")
    a.emit(0xC3)  # ret
    return a


def build_code(base_va: int) -> bytes:
    """The cave, laid out at `base_va`."""
    return _assemble(base_va).finish()


def entry_points(base_va: int) -> tuple[int, int]:
    """`(route, import)` - the virtual address each hook calls, read off the emitted layout
    rather than counted by hand."""
    a = _assemble(base_va)
    a.finish()
    return a.label_va("route"), a.label_va("import")


class SkirmishAiFallbackPatch(Patch):
    name = "skirmish-ai-fallback"
    author = "officialNecro"
    description = (
        "Give a faction a working AI on maps that carry no Skirmish<Faction> side for it. The "
        "faction's own PlayerTemplate must name a DefaultPlayerAIType, and that AIPlayerType's "
        "LibraryMap scripts are what the AI then runs - no map edit and no new INI field"
    )

    def apply(self, data: bytearray) -> None:
        self._check_anchors(data)
        section_va = allocate_section(data, SECTION_NAME, build_code, _CHARACTERISTICS)
        route_va, import_va = entry_points(section_va)
        for hook_va, original, target, padding, note in (
            (
                PLAYER_SKIRMISH_ROUTE,
                PLAYER_SKIRMISH_ROUTE_BYTES,
                route_va,
                0,
                "initFromDict skirmish-side fork -> skirmish-ai-fallback cave",
            ),
            (
                PLAYER_SKIRMISH_IMPORT,
                PLAYER_SKIRMISH_IMPORT_BYTES,
                import_va,
                len(PLAYER_SKIRMISH_IMPORT_BYTES) - 5,
                "initFromDict skirmish-side import fork -> skirmish-ai-fallback cave",
            ),
        ):
            off = va_to_offset(data, hook_va)
            if off is None:
                raise ValueError(f"{hook_va:#010x} is not mapped - not the expected build")
            call = b"\xe8" + struct.pack("<i", target - (hook_va + 5)) + b"\x90" * padding
            apply_byte_patch(data, off, original, call, note)

    @staticmethod
    def _check_anchors(data: bytes | bytearray) -> None:
        for va, expected in ANCHORS.items():
            off = va_to_offset(data, va)
            if off is None:
                raise ValueError(f"{va:#010x} is not mapped - not the expected build")
            got = bytes(data[off : off + len(expected)])
            if got != expected:
                raise ValueError(
                    f"{va:#010x} holds {got.hex()}, expected {expected.hex()} - this build's "
                    "player setup is not the one the cave was written against, so it would call "
                    "the wrong routine or write into the wrong field"
                )

    def verify(self, data: bytes | bytearray) -> list[str]:
        problems: list[str] = []
        located = find_section(data, SECTION_NAME)
        if located is None:
            return [f"{SECTION_NAME} section is absent"]
        section_va, section_off, _ = located
        route_va, import_va = entry_points(section_va)
        for hook_va, expected_target, name in (
            (PLAYER_SKIRMISH_ROUTE, route_va, "skirmish-side fork"),
            (PLAYER_SKIRMISH_IMPORT, import_va, "skirmish-side import fork"),
        ):
            off = va_to_offset(data, hook_va)
            if off is None:
                return [f"{hook_va:#010x} is not mapped by any section"]
            if data[off] != 0xE8:
                problems.append(f"{name} at {hook_va:#010x} is not a call - the hook is absent")
                continue
            target = hook_va + 5 + struct.unpack_from("<i", data, off + 1)[0]
            if target != expected_target:
                problems.append(f"{name} calls {target:#010x}, expected {expected_target:#010x}")
        code = build_code(section_va)
        if bytes(data[section_off : section_off + len(code)]) != code:
            problems.append(f"the {SECTION_NAME} cave does not hold the expected routines")
        return problems
