"""Let a multi-execute special power stay usable while any selected unit has it ready.

With several units selected, the control bar shows a special power's cooldown from one unit: a
selection of one type is shown through a single representative drawable, and a mixed selection
keeps the clock of whichever member it painted last. The click is gated the same way, on the
representative alone or on every member. So one unit that has used the power greys it for the
whole group.

For a `SPECIAL_POWER` button with `OK_FOR_MULTI_EXECUTE`, the patch asks the rest of the selection
before accepting "recharging": the button is shown ready and clickable when any selected unit has
the power ready, and only shows a clock (the one closest to ready) when none does. The order is
unchanged: the group loop on the logic side already skips every member whose power is still
recharging, so only the ready units fire.

The mixed-selection bar also keeps a recharge clock on a slot that a ready member made usable: the
clock is a one-frame request, and a recharging member painted earlier in the frame leaves its
request standing. For a usable slot the patch drops that request and the recharge bit, except on
a special-power button without `OK_FOR_MULTI_EXECUTE`, whose click still needs every member ready
(so its clock is accurate). Client-side only; no INI change.

Derivation: `../docs/multi-execute-cooldown.md`.
"""

from __future__ import annotations

from ..addresses import (
    COMMAND_BUTTON_COMMAND,
    COMMAND_BUTTON_IS_READY,
    COMMAND_BUTTON_IS_READY_ENTRY,
    COMMAND_BUTTON_OPTION_MULTI_EXECUTE,
    COMMAND_BUTTON_OPTIONS,
    COMMAND_WINDOW_DATA_KIND,
    COMMAND_WINDOW_DATA_KIND_PROGRESS,
    CONTROL_BAR_AVAILABILITY_OK_HIGH,
    CONTROL_BAR_AVAILABILITY_OK_LOW,
    CONTROL_BAR_AVAILABILITY_RECHARGING,
    CONTROL_BAR_DO_COMMAND_MULTI_READY_CALL,
    CONTROL_BAR_DO_COMMAND_MULTI_READY_CALL_BYTES,
    CONTROL_BAR_DO_COMMAND_READY_CALL,
    CONTROL_BAR_DO_COMMAND_READY_CALL_BYTES,
    CONTROL_BAR_DO_COMMAND_SPECIAL_POWER_GATE,
    CONTROL_BAR_DO_COMMAND_SPECIAL_POWER_GATE_BYTES,
    CONTROL_BAR_GET_COMMAND_AVAILABILITY,
    CONTROL_BAR_GET_COMMAND_AVAILABILITY_ENTRY,
    CONTROL_BAR_MULTI_AVAILABILITY_CALL,
    CONTROL_BAR_MULTI_AVAILABILITY_CALL_BYTES,
    CONTROL_BAR_MULTI_USABLE_CLEAR_CALL,
    CONTROL_BAR_MULTI_USABLE_CLEAR_CALL_BYTES,
    CONTROL_BAR_MULTI_USABLE_PASS,
    CONTROL_BAR_MULTI_USABLE_PASS_BYTES,
    CONTROL_BAR_SLOT_AVAILABILITY_CALL_BYTES,
    CONTROL_BAR_UPDATE_AVAILABILITY_CALL,
    DRAWABLE_OBJECT,
    GAME_WINDOW_GET_COMMAND_BUTTON,
    GAME_WINDOW_GET_COMMAND_BUTTON_ENTRY,
    GAME_WINDOW_GET_DATA,
    GAME_WINDOW_GET_DATA_ENTRY,
    GUI_COMMAND_SPECIAL_POWER,
    GUI_COMMAND_SPECIAL_POWER_FROM_COMMAND_CENTER,
    IN_GAME_UI_GET_ALL_SELECTED_DRAWABLES_SLOT,
    SELECTION_LIST_DRAWABLE,
    THE_IN_GAME_UI,
    WINDOW_CLEAR_STATUS,
    WINDOW_CLEAR_STATUS_BYTES,
    WINDOW_STATUS_RECHARGING,
)
from ..asm import JBE, JE, JNE, Asm
from ..patcher import Patch
from ..utils import allocate_section, apply_byte_patch, call_rel32, file_offset, find_section, u32

__all__ = [
    "ANCHORS",
    "AVAILABILITY_SITES",
    "READY_SITES",
    "USABLE_SITES",
    "SECTION_NAME",
    "MultiExecuteCooldownPatch",
    "build_section",
    "layout",
]

SECTION_NAME = ".mxcool"  # 7 chars: the PE name field is 8 bytes and truncates silently

#: The two calls that paint the bar, as `{va: stock bytes}`; both go to `availability_any`.
AVAILABILITY_SITES: dict[int, bytes] = {
    CONTROL_BAR_UPDATE_AVAILABILITY_CALL: CONTROL_BAR_SLOT_AVAILABILITY_CALL_BYTES,
    CONTROL_BAR_MULTI_AVAILABILITY_CALL: CONTROL_BAR_MULTI_AVAILABILITY_CALL_BYTES,
}
#: The two calls that gate the click; both go to `ready_any`.
READY_SITES: dict[int, bytes] = {
    CONTROL_BAR_DO_COMMAND_READY_CALL: CONTROL_BAR_DO_COMMAND_READY_CALL_BYTES,
    CONTROL_BAR_DO_COMMAND_MULTI_READY_CALL: CONTROL_BAR_DO_COMMAND_MULTI_READY_CALL_BYTES,
}

#: The mixed-selection final pass's last status clear for a usable slot; goes to `usable_paint`.
USABLE_SITES: dict[int, bytes] = {
    CONTROL_BAR_MULTI_USABLE_CLEAR_CALL: CONTROL_BAR_MULTI_USABLE_CLEAR_CALL_BYTES,
}

#: Read, never rewritten: the routines the caves call (so their entry is the one relied on), the
#: click gate both ready sites sit in, and the usable branch the usable site sits in.
ANCHORS: dict[int, bytes] = {
    CONTROL_BAR_GET_COMMAND_AVAILABILITY: CONTROL_BAR_GET_COMMAND_AVAILABILITY_ENTRY,
    COMMAND_BUTTON_IS_READY: COMMAND_BUTTON_IS_READY_ENTRY,
    CONTROL_BAR_DO_COMMAND_SPECIAL_POWER_GATE: CONTROL_BAR_DO_COMMAND_SPECIAL_POWER_GATE_BYTES,
    CONTROL_BAR_MULTI_USABLE_PASS: CONTROL_BAR_MULTI_USABLE_PASS_BYTES,
    WINDOW_CLEAR_STATUS: WINDOW_CLEAR_STATUS_BYTES,
    GAME_WINDOW_GET_DATA: GAME_WINDOW_GET_DATA_ENTRY,
    GAME_WINDOW_GET_COMMAND_BUTTON: GAME_WINDOW_GET_COMMAND_BUTTON_ENTRY,
}

# CNT_CODE | MEM_EXECUTE | MEM_READ.
_CHARACTERISTICS = 0x20 | 0x20000000 | 0x40000000

#: `1.0f`, the ready fraction a usable answer leaves in the progress argument (no clock).
_ONE = 0x3F800000


def _multi_execute_power(a: Asm, button: int, fail: str) -> None:
    """Jump to `fail` unless the button in register `button` (`modrm` reg number, `[reg]`
    addressing) is a `SPECIAL_POWER` with `OK_FOR_MULTI_EXECUTE`."""
    a.emit(0x83, 0x78 | button, COMMAND_BUTTON_COMMAND, GUI_COMMAND_SPECIAL_POWER)  # cmp [r+0x14]
    a.jcc(JNE, fail)
    a.emit(0xF7, 0x40 | button, COMMAND_BUTTON_OPTIONS, u32(COMMAND_BUTTON_OPTION_MULTI_EXECUTE))
    a.jcc(JE, fail)  # test [r+0x1c], OK_FOR_MULTI_EXECUTE


def _selection(a: Asm, empty: str) -> None:
    """`eax` = the selected-drawable list's sentinel node, or jump to `empty`."""
    a.emit(0x8B, 0x0D, u32(THE_IN_GAME_UI))  # mov ecx, [TheInGameUI]
    a.emit(0x85, 0xC9)  # test ecx, ecx
    a.jcc(JE, empty)
    a.emit(0x8B, 0x01)  # mov eax, [ecx]
    a.emit(0xFF, 0x90, u32(IN_GAME_UI_GET_ALL_SELECTED_DRAWABLES_SLOT))  # call [eax+0x124]
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, empty)
    a.emit(0x8B, 0x00)  # mov eax, [eax]                ; the sentinel


def _member_object(a: Asm, node: int, skip: str) -> None:
    """`eax` = the `Object *` of the selection node in register `node`, or jump to `skip`."""
    a.emit(0x8B, 0x40 | node, SELECTION_LIST_DRAWABLE)  # mov eax, [node+8]   ; the Drawable
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, skip)
    a.emit(0x8B, 0x80, u32(DRAWABLE_OBJECT))  # mov eax, [eax+0xfc]
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, skip)


_EAX, _ECX, _EDX, _EBX, _ESP, _EBP, _ESI, _EDI = range(8)


def _assemble(base_va: int) -> Asm:
    a = Asm(base_va)

    # availability_any: in place of `getCommandAvailability`. `__thiscall` on the ControlBar,
    # (button, window, obj, progress, flag), `ret 0x14`. Frame: [ebp+8..0x18] the arguments,
    # [ebp-0x10] a member's progress, [ebp-0x14] the best progress, [ebp-0x18] the sentinel.
    a.label("availability_any")
    a.emit(0x55)  # push ebp
    a.emit(0x8B, 0xEC)  # mov ebp, esp
    a.emit(0x53, 0x56, 0x57)  # push ebx / esi / edi
    a.emit(0x83, 0xEC, 0x0C)  # sub esp, 0xc
    a.emit(0x8B, 0xD9)  # mov ebx, ecx                    ; the ControlBar
    for disp in (0x18, 0x14, 0x10, 0x0C, 0x08):
        a.emit(0xFF, 0x75, disp)  # push [ebp+disp]           ; the caller's arguments
    a.call_absolute(CONTROL_BAR_GET_COMMAND_AVAILABILITY)  # ecx is still the ControlBar
    a.emit(0x83, 0xF8, CONTROL_BAR_AVAILABILITY_RECHARGING)  # cmp eax, 5
    a.jcc(JNE, "av_out")
    a.emit(0x8B, 0x55, 0x08)  # mov edx, [ebp+8]          ; the button
    a.emit(0x85, 0xD2)  # test edx, edx
    a.jcc(JE, "av_out")
    _multi_execute_power(a, _EDX, "av_out")
    a.emit(0x8B, 0xF8)  # mov edi, eax                    ; the answer so far: recharging
    a.emit(0x8B, 0x4D, 0x14)  # mov ecx, [ebp+0x14]
    a.emit(0x8B, 0x01)  # mov eax, [ecx]
    a.emit(0x89, 0x45, 0xEC)  # mov [ebp-0x14], eax       ; best = this unit's progress
    _selection(a, "av_keep")
    a.emit(0x89, 0x45, 0xE8)  # mov [ebp-0x18], eax       ; the sentinel
    a.emit(0x8B, 0x30)  # mov esi, [eax]                  ; the first node
    a.label("av_walk")
    a.emit(0x3B, 0x75, 0xE8)  # cmp esi, [ebp-0x18]
    a.jcc(JE, "av_best")
    _member_object(a, _ESI, "av_next")
    a.emit(0x3B, 0x45, 0x10)  # cmp eax, [ebp+0x10]       ; the unit already asked
    a.jcc(JE, "av_next")
    a.emit(0x8D, 0x4D, 0xF0)  # lea ecx, [ebp-0x10]
    a.emit(0x6A, 0x00)  # push 0
    a.emit(0x51)  # push ecx                              ; this member's progress
    a.emit(0x50)  # push eax                              ; this member
    a.emit(0xFF, 0x75, 0x0C)  # push [ebp+0xc]            ; the window
    a.emit(0xFF, 0x75, 0x08)  # push [ebp+8]              ; the button
    a.emit(0x8B, 0xCB)  # mov ecx, ebx
    a.call_absolute(CONTROL_BAR_GET_COMMAND_AVAILABILITY)
    a.emit(0x83, 0xF8, CONTROL_BAR_AVAILABILITY_OK_LOW)  # cmp eax, 1
    a.jcc(JE, "av_ready")
    a.emit(0x83, 0xF8, CONTROL_BAR_AVAILABILITY_OK_HIGH)  # cmp eax, 2
    a.jcc(JE, "av_ready")
    a.emit(0x83, 0xF8, CONTROL_BAR_AVAILABILITY_RECHARGING)  # cmp eax, 5
    a.jcc(JNE, "av_next")
    a.emit(0xF3, 0x0F, 0x10, 0x45, 0xF0)  # movss xmm0, [ebp-0x10]
    a.emit(0x0F, 0x2F, 0x45, 0xEC)  # comiss xmm0, [ebp-0x14]
    a.jcc(JBE, "av_next")
    a.emit(0xF3, 0x0F, 0x11, 0x45, 0xEC)  # movss [ebp-0x14], xmm0   ; closer to ready
    a.label("av_next")
    a.emit(0x8B, 0x36)  # mov esi, [esi]                  ; next node
    a.jmp("av_walk")
    a.label("av_ready")
    a.emit(0x8B, 0xF8)  # mov edi, eax                    ; usable, as that member answered
    a.emit(0x8B, 0x4D, 0x14)  # mov ecx, [ebp+0x14]
    a.emit(0xC7, 0x01, u32(_ONE))  # mov dword [ecx], 1.0   ; no clock
    a.jmp("av_keep")
    a.label("av_best")
    a.emit(0x8B, 0x4D, 0x14)  # mov ecx, [ebp+0x14]
    a.emit(0x8B, 0x45, 0xEC)  # mov eax, [ebp-0x14]
    a.emit(0x89, 0x01)  # mov [ecx], eax                  ; the clock closest to ready
    a.label("av_keep")
    a.emit(0x8B, 0xC7)  # mov eax, edi
    a.label("av_out")
    a.emit(0x8D, 0x65, 0xF4)  # lea esp, [ebp-0xc]
    a.emit(0x5F, 0x5E, 0x5B)  # pop edi / esi / ebx
    a.emit(0x5D)  # pop ebp
    a.emit(0xC2, 0x14, 0x00)  # ret 0x14

    # ready_any: in place of `CommandButton::isReady`. `__thiscall` on the button, (obj), `ret 4`.
    a.label("ready_any")
    a.emit(0x55)  # push ebp
    a.emit(0x8B, 0xEC)  # mov ebp, esp
    a.emit(0x53, 0x56, 0x57)  # push ebx / esi / edi
    a.emit(0x8B, 0xD9)  # mov ebx, ecx                    ; the button
    a.emit(0xFF, 0x75, 0x08)  # push [ebp+8]
    a.call_absolute(COMMAND_BUTTON_IS_READY)  # ecx is still the button
    a.emit(0x84, 0xC0)  # test al, al
    a.jcc(JNE, "rd_yes")
    _multi_execute_power(a, _EBX, "rd_no")
    _selection(a, "rd_no")
    a.emit(0x8B, 0xF8)  # mov edi, eax                    ; the sentinel
    a.emit(0x8B, 0x37)  # mov esi, [edi]                  ; the first node
    a.label("rd_walk")
    a.emit(0x3B, 0xF7)  # cmp esi, edi
    a.jcc(JE, "rd_no")
    _member_object(a, _ESI, "rd_next")
    a.emit(0x50)  # push eax
    a.emit(0x8B, 0xCB)  # mov ecx, ebx
    a.call_absolute(COMMAND_BUTTON_IS_READY)
    a.emit(0x84, 0xC0)  # test al, al
    a.jcc(JNE, "rd_yes")
    a.label("rd_next")
    a.emit(0x8B, 0x36)  # mov esi, [esi]
    a.jmp("rd_walk")
    a.label("rd_yes")
    a.emit(0xB0, 0x01)  # mov al, 1
    a.jmp("rd_out")
    a.label("rd_no")
    a.emit(0x32, 0xC0)  # xor al, al
    a.label("rd_out")
    a.emit(0x5F, 0x5E, 0x5B)  # pop edi / esi / ebx
    a.emit(0x5D)  # pop ebp
    a.emit(0xC2, 0x04, 0x00)  # ret 4

    # usable_paint: in place of the final pass's last `clearStatus` for a usable slot.
    # `__thiscall` on the window, (mask), `ret 4`.
    a.label("usable_paint")
    a.emit(0x56)  # push esi
    a.emit(0x8B, 0xF1)  # mov esi, ecx                    ; the window
    a.emit(0xFF, 0x74, 0x24, 0x08)  # push [esp+8]          ; the stock mask
    a.call_absolute(WINDOW_CLEAR_STATUS)  # ecx is still the window
    a.emit(0x56)  # push esi
    a.call_absolute(GAME_WINDOW_GET_COMMAND_BUTTON)
    a.emit(0x59)  # pop ecx
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "up_out")
    a.emit(0x83, 0x78, COMMAND_BUTTON_COMMAND, GUI_COMMAND_SPECIAL_POWER_FROM_COMMAND_CENTER)
    a.jcc(JE, "up_out")  # cmp [eax+0x14], 0x17 - its click needs every member: keep the clock
    a.emit(0x83, 0x78, COMMAND_BUTTON_COMMAND, GUI_COMMAND_SPECIAL_POWER)
    a.jcc(JNE, "up_clear")  # cmp [eax+0x14], 0x18 - any other command: the click needs one
    a.emit(0xF7, 0x40, COMMAND_BUTTON_OPTIONS, u32(COMMAND_BUTTON_OPTION_MULTI_EXECUTE))
    a.jcc(JE, "up_out")  # a special power without OK_FOR_MULTI_EXECUTE: keep the clock
    a.label("up_clear")
    a.emit(0x68, u32(WINDOW_STATUS_RECHARGING))  # push 0x400000
    a.emit(0x8B, 0xCE)  # mov ecx, esi
    a.call_absolute(WINDOW_CLEAR_STATUS)
    a.emit(0x8B, 0xCE)  # mov ecx, esi
    a.call_absolute(GAME_WINDOW_GET_DATA)
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "up_out")
    a.emit(0x80, 0x78, COMMAND_WINDOW_DATA_KIND, COMMAND_WINDOW_DATA_KIND_PROGRESS)
    a.jcc(JNE, "up_out")  # cmp byte [eax], 2 - a clock request, and only that
    a.emit(0xC6, 0x40, COMMAND_WINDOW_DATA_KIND, 0x00)  # mov byte [eax], 0
    a.label("up_out")
    a.emit(0x5E)  # pop esi
    a.emit(0xC2, 0x04, 0x00)  # ret 4
    return a


def build_section(base_va: int) -> bytes:
    return _assemble(base_va).finish()


def layout(base_va: int) -> dict[str, int]:
    a = _assemble(base_va)
    return {name: a.label_va(name) for name in ("availability_any", "ready_any", "usable_paint")}


def _edits(base_va: int) -> list[tuple[int, bytes, bytes, str]]:
    at = layout(base_va)
    edits = [
        (
            va,
            stock,
            call_rel32(va, at["availability_any"]),
            "ControlBar slot paint -> recharging only if no selected unit has the power ready",
        )
        for va, stock in AVAILABILITY_SITES.items()
    ]
    edits += [
        (
            va,
            stock,
            call_rel32(va, at["ready_any"]),
            "ControlBar::doCommand special-power gate -> ready if any selected unit is",
        )
        for va, stock in READY_SITES.items()
    ]
    edits += [
        (
            va,
            stock,
            call_rel32(va, at["usable_paint"]),
            "ControlBar mixed-selection usable slot -> drop a stale recharge clock",
        )
        for va, stock in USABLE_SITES.items()
    ]
    return edits


class MultiExecuteCooldownPatch(Patch):
    name = "multi-execute-cooldown"
    author = "officialNecro"
    description = (
        "With several units selected, show a SPECIAL_POWER button with OK_FOR_MULTI_EXECUTE as "
        "ready and let it be clicked while any selected unit has the power off cooldown; the "
        "order then fires only on the units that are ready (as stock). Stock shows one unit's "
        "cooldown for the whole group. A mixed selection also no longer keeps a stale cooldown "
        "clock on a button some member can use. Client-side only. No INI change"
    )

    def apply(self, data: bytearray) -> None:
        for va, expected in ANCHORS.items():
            self._check_stock(data, va, expected)
        for va, stock, _new, _note in _edits(0):  # the stock half does not depend on the base
            self._check_stock(data, va, stock)
        base_va = allocate_section(data, SECTION_NAME, build_section, _CHARACTERISTICS)
        for va, stock, new, note in _edits(base_va):
            apply_byte_patch(data, file_offset(data, va), stock, new, note)

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
        got = bytes(data[section_off : section_off + len(expected)])
        if vsize < len(expected) or got != expected:
            problems.append(f"the {SECTION_NAME} cave is not the one this patch builds")
        for va, _stock, new, note in _edits(base_va):
            off = file_offset(data, va)
            here = bytes(data[off : off + len(new)])
            if here != new:
                problems.append(f"@{va:#010x}: {note} is not installed (holds {here.hex()})")
        return problems
