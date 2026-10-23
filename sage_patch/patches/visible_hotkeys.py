"""Make a command-button shortcut act on a visible button that has the letter, not on whichever
button registered the letter first.

A shortcut is the character after the first `&` in a button's label, registered per control-bar
slot as the set is bound (`ControlBar::setControlCommand`). The hotkey map holds one handler per
key string and tries the letter lowercase then uppercase, so the first two slots that share a
letter get it and every later one is dropped. Hidden slots register too. A command set that lists
three alternatives under one letter and shows only one of them (Edain's dwarven foundation:
three subfaction barracks, each `HIDE_WHILE_DISABLED`) leaves the third alternative with no
shortcut at all.

The patch records each bound slot's letter, and makes the slot handler resolve, at the moment the
key is pressed, the first **visible and enabled** slot with that letter (else the first visible
one), then run the engine's own hidden / enabled / click methods on it. A hidden slot is never
chosen, and a letter nothing visible carries does nothing, as in stock.

Derivation: `../docs/visible-hotkeys.md`.
"""

from __future__ import annotations

import struct

from ..addresses import GAME_WINDOW_GET_COMMAND_BUTTON, GAME_WINDOW_GET_DATA, THE_COMMAND_SET_STORE
from ..asm import JA, JE, JL, JNE, JNZ, JZ, Asm
from ..patcher import Patch
from ..utils import allocate_section, apply_byte_patch, find_section, u32, va_to_offset

__all__ = [
    "ANCHORS",
    "CTOR_VTABLE_IMM_VA",
    "HANDLER_VTABLE",
    "HOOK_ORIGINAL",
    "HOOK_RESUME",
    "HOOK_VA",
    "SECTION_NAME",
    "SLOT_COUNT",
    "STOCK_CLICK",
    "STOCK_IS_ENABLED",
    "STOCK_IS_HIDDEN",
    "VisibleHotkeysPatch",
    "build_section",
    "layout",
]

SECTION_NAME = ".vishkey"  # the PE name field is 8 bytes and truncates silently

# CNT_CODE | CNT_INITIALIZED_DATA | MEM_EXECUTE | MEM_READ | MEM_WRITE - the cave holds the
# per-slot letter table the registration hook writes at runtime, beside the code that reads it.
_CHARACTERISTICS = 0xE0000060

#: The control bar's slot widgets: `ControlBar+0xDC`, 33 `GameWindow *`, slot order. The bind loop
#: (`0x009445C0`) walks them with `cmp [ebp+8], 0x21`, and `commandset-limit` keeps the widget
#: count at 33 whatever the set size.
SLOT_ARRAY_OFFSET = 0xDC
SLOT_COUNT = 33

#: `GameWindow` status (`winGetStatus` is `mov eax, [ecx+8]`): the bits the stock handler tests.
_WINDOW_STATUS = 0x08
_STATUS_ENABLED = 0x08
_STATUS_HIDDEN = 0x10

#: In `ControlBar::setControlCommand`, after the letter is known to be non-empty: `push 0xC; call
#: operator new` - the allocation of the slot's hotkey handler. `eax` is the letter's AsciiString
#: data (chars at `+8`), `esi` the CommandButton, `edi` the slot window, `[ebp-0x14]` the
#: ControlBar.
HOOK_VA = 0x0071D0F9
HOOK_ORIGINAL = bytes.fromhex("6a0ce8e025d1ff")
HOOK_RESUME = 0x0071D100  # pop ecx - the cdecl cleanup of that call
OPERATOR_NEW = 0x0042F6E0
_CONTROL_BAR_EBP = -0x14

#: The slot hotkey handler: `{vtable, refcount, GameWindow *}`, 12 bytes, built only here. Its
#: constructor is called once (`0x0071D10F`) and is the only reference to its vtable.
HANDLER_CTOR = 0x009444F3
CTOR_VTABLE_IMM_VA = 0x009444FF  # the imm32 of `mov dword [eax], 0xC80310`
HANDLER_VTABLE = 0x00C80310
#: Its methods, each `__thiscall` with one argument, reading only `[this+8]`: `+4` the window's
#: HIDDEN bit, `+8` its ENABLED bit, `+0xC` the click (`processCommandUI` on the window).
STOCK_DELETING_DTOR = 0x00A087F2
STOCK_IS_HIDDEN = 0x00944476
STOCK_IS_ENABLED = 0x00944487
STOCK_CLICK = 0x00944498

#: Everything the patch relies on and does not rewrite, as `{va: stock bytes}`.
ANCHORS: dict[int, bytes] = {
    HANDLER_CTOR: bytes.fromhex("8bc18b4c240483600400c7001003c800894808c20400"),
    HANDLER_VTABLE: struct.pack(
        "<4I", STOCK_DELETING_DTOR, STOCK_IS_HIDDEN, STOCK_IS_ENABLED, STOCK_CLICK
    ),
    STOCK_IS_HIDDEN: bytes.fromhex("8b4908e8985a0b00c1e80483e001c20400"),
    STOCK_IS_ENABLED: bytes.fromhex("8b4908e8875a0b00c1e80383e001c20400"),
    STOCK_CLICK: bytes.fromhex("568bf18b4e08e87114ddff"),
    0x009F9F16: bytes.fromhex("8b4108c3"),  # winGetStatus: mov eax, [ecx+8]
    GAME_WINDOW_GET_COMMAND_BUTTON: bytes.fromhex(
        "8b4c240485c97409e85fc6270085c0750333c0c38b4014c3"
    ),
    GAME_WINDOW_GET_DATA: bytes.fromhex("8b412cc3"),
    OPERATOR_NEW: bytes.fromhex("8b442404"),
    # mov eax, [TheControlBar]; mov ebx, [eax+ebx*4+0xDC] - the slot array, off the global.
    0x0092FF8F: bytes.fromhex("a14477de008b9c98dc000000"),
}


def layout(base_va: int) -> dict[str, int]:
    """Where each part of the cave sits: the two 33-entry tables, the vtable, then code."""
    buttons = base_va
    letters = buttons + SLOT_COUNT * 4
    vtable = letters + SLOT_COUNT * 4
    return {"buttons": buttons, "letters": letters, "vtable": vtable, "code": vtable + 16}


def build_section(base_va: int) -> bytes:
    """The whole cave. The tables start zeroed; a zero letter matches nothing."""
    at = layout(base_va)
    a = Asm(at["code"])

    # Registration: remember which button, and which letter, this slot was bound with.
    a.label("record")
    a.emit(0x60)  # pushad
    a.emit(0x8B, 0x55, _CONTROL_BAR_EBP & 0xFF)  # mov edx, [ebp-0x14]     the ControlBar
    a.emit(0x0F, 0xB6, 0x40, 0x08)  # movzx eax, byte [eax+8]             the letter
    a.emit(0x8D, 0x48, 0xBF)  # lea ecx, [eax-'A']
    a.emit(0x83, 0xF9, 0x19)  # cmp ecx, 25
    a.jcc_short(JA, "r_lower")
    a.emit(0x83, 0xC8, 0x20)  # or eax, 0x20                              ASCII lowercase
    a.label("r_lower")
    a.emit(0x31, 0xC9)  # xor ecx, ecx
    a.label("r_find")
    a.emit(0x39, 0xBC, 0x8A, u32(SLOT_ARRAY_OFFSET))  # cmp [edx+ecx*4+0xDC], edi
    a.jcc_short(JE, "r_found")
    a.emit(0x41)  # inc ecx
    a.emit(0x83, 0xF9, SLOT_COUNT)  # cmp ecx, 33
    a.jcc_short(JL, "r_find")
    a.jmp_short("r_done")  # not a slot widget: leave it to stock
    a.label("r_found")
    a.emit(0x89, 0x34, 0x8D, u32(at["buttons"]))  # mov [ecx*4+buttons], esi
    a.emit(0x89, 0x04, 0x8D, u32(at["letters"]))  # mov [ecx*4+letters], eax
    a.label("r_done")
    a.emit(0x61)  # popad
    a.emit(HOOK_ORIGINAL[:2])  # push 0xC
    a.call_absolute(OPERATOR_NEW)
    a.jmp_absolute(HOOK_RESUME)

    # resolve(ecx = handler) -> eax = the handler to act through: either a stand-in whose `+8` is
    # the chosen slot's window (`&slots[i] - 8`, which is all the stock methods read), or the
    # handler itself when its slot is not in the table. Preserves ebx/esi/edi/ebp.
    a.label("resolve")
    a.emit(0x53, 0x56, 0x57, 0x55)  # push ebx; push esi; push edi; push ebp
    a.emit(0x8B, 0xE9)  # mov ebp, ecx
    a.emit(0x8B, 0x1D, u32(THE_COMMAND_SET_STORE))  # mov ebx, [TheControlBar]
    a.emit(0x85, 0xDB)  # test ebx, ebx
    a.jcc(JZ, "self")
    a.emit(0x81, 0xC3, u32(SLOT_ARRAY_OFFSET))  # add ebx, 0xDC              the slot widgets
    a.emit(0x8B, 0x45, 0x08)  # mov eax, [ebp+8]                         this handler's window
    a.emit(0x31, 0xF6)  # xor esi, esi
    a.label("own")
    a.emit(0x39, 0x04, 0xB3)  # cmp [ebx+esi*4], eax
    a.jcc_short(JE, "own_found")
    a.emit(0x46)  # inc esi
    a.emit(0x83, 0xFE, SLOT_COUNT)  # cmp esi, 33
    a.jcc_short(JL, "own")
    a.jmp("self")
    a.label("own_found")
    a.emit(0x50)  # push eax
    a.call_absolute(GAME_WINDOW_GET_COMMAND_BUTTON)
    a.emit(0x83, 0xC4, 0x04)  # add esp, 4
    a.emit(0x3B, 0x04, 0xB5, u32(at["buttons"]))  # cmp eax, [esi*4+buttons]   still that button?
    a.jcc(JNE, "self")
    a.emit(0x8B, 0x3C, 0xB5, u32(at["letters"]))  # mov edi, [esi*4+letters]   the letter
    a.emit(0x31, 0xF6)  # xor esi, esi
    a.emit(0x6A, 0x00)  # push 0                       [esp] = first visible-but-disabled match
    a.label("scan")
    a.emit(0x8B, 0x04, 0xB3)  # mov eax, [ebx+esi*4]
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc_short(JZ, "next")
    a.emit(0xF6, 0x40, _WINDOW_STATUS, _STATUS_HIDDEN)  # test byte [eax+8], HIDDEN
    a.jcc_short(JNZ, "next")
    a.emit(0x3B, 0x3C, 0xB5, u32(at["letters"]))  # cmp edi, [esi*4+letters]
    a.jcc_short(JNE, "next")
    a.emit(0x50)  # push eax
    a.call_absolute(GAME_WINDOW_GET_COMMAND_BUTTON)
    a.emit(0x83, 0xC4, 0x04)  # add esp, 4
    a.emit(0x3B, 0x04, 0xB5, u32(at["buttons"]))  # cmp eax, [esi*4+buttons]   rebound since?
    a.jcc_short(JNE, "next")
    a.emit(0x8D, 0x44, 0xB3, 0xF8)  # lea eax, [ebx+esi*4-8]              the stand-in
    a.emit(0x8B, 0x0C, 0xB3)  # mov ecx, [ebx+esi*4]
    a.emit(0xF6, 0x41, _WINDOW_STATUS, _STATUS_ENABLED)  # test byte [ecx+8], ENABLED
    a.jcc_short(JNZ, "enabled")
    a.emit(0x83, 0x3C, 0x24, 0x00)  # cmp dword [esp], 0
    a.jcc_short(JNE, "next")
    a.emit(0x89, 0x04, 0x24)  # mov [esp], eax
    a.label("next")
    a.emit(0x46)  # inc esi
    a.emit(0x83, 0xFE, SLOT_COUNT)  # cmp esi, 33
    a.jcc_short(JL, "scan")
    a.emit(0x58)  # pop eax                        the visible-but-disabled match, if any
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc_short(JNZ, "out")
    a.jmp_short("self")
    a.label("enabled")
    a.emit(0x83, 0xC4, 0x04)  # add esp, 4
    a.jmp_short("out")
    a.label("self")
    a.emit(0x8B, 0xC5)  # mov eax, ebp
    a.label("out")
    a.emit(0x5D, 0x5F, 0x5E, 0x5B)  # pop ebp; pop edi; pop esi; pop ebx
    a.emit(0xC3)  # ret

    # The three methods: resolve, then the stock method on whatever it chose.
    for label, stock in (
        ("is_hidden", STOCK_IS_HIDDEN),
        ("is_enabled", STOCK_IS_ENABLED),
        ("click", STOCK_CLICK),
    ):
        a.label(label)
        a.emit(0xFF, 0x74, 0x24, 0x04)  # push dword [esp+4]        the argument, for the stock call
        a.call("resolve")
        a.emit(0x8B, 0xC8)  # mov ecx, eax
        a.call_absolute(stock)  # ret 4 - consumes the copy
        a.emit(0xC2, 0x04, 0x00)  # ret 4

    code = a.finish()
    vtable = struct.pack(
        "<4I",
        STOCK_DELETING_DTOR,
        a.label_va("is_hidden"),
        a.label_va("is_enabled"),
        a.label_va("click"),
    )
    return bytes(SLOT_COUNT * 8) + vtable + code


def _record_va(base_va: int) -> int:
    return layout(base_va)["code"]


def _edits(section_va: int) -> list[tuple[int, bytes, bytes, str]]:
    """`(va, stock bytes, patched bytes, note)` for the two sites the patch rewrites."""
    jump = b"\xe9" + struct.pack("<i", _record_va(section_va) - (HOOK_VA + 5)) + b"\x90\x90"
    return [
        (HOOK_VA, HOOK_ORIGINAL, jump, "setControlCommand handler allocation -> letter record"),
        (
            CTOR_VTABLE_IMM_VA,
            u32(HANDLER_VTABLE),
            u32(layout(section_va)["vtable"]),
            "slot hotkey handler vtable -> visible-slot resolving vtable",
        ),
    ]


class VisibleHotkeysPatch(Patch):
    name = "visible-hotkeys"
    author = "officialNecro"
    description = (
        "Make a command button's shortcut letter act on the first visible button that carries "
        "it (preferring an enabled one), not on whichever slot registered the letter first. "
        "Stock keeps only two slots per letter, hidden ones included, so a set listing three "
        "HIDE_WHILE_DISABLED alternatives under one letter leaves the third with no shortcut. "
        "Hidden buttons still never fire. No INI change"
    )

    def apply(self, data: bytearray) -> None:
        for va, expected in ANCHORS.items():
            off = va_to_offset(data, va)
            if off is None:
                raise ValueError(f"{va:#010x} is not mapped - not the expected build")
            got = bytes(data[off : off + len(expected)])
            if got != expected:
                raise ValueError(
                    f"{va:#010x} holds {got.hex()}, expected {expected.hex()} - the control "
                    "bar's hotkey handler is not where this patch expects it"
                )
        section_va = allocate_section(data, SECTION_NAME, build_section, _CHARACTERISTICS)
        for va, old, new, note in _edits(section_va):
            off = va_to_offset(data, va)
            if off is None:
                raise ValueError(f"{va:#010x} is not mapped - not the expected build")
            apply_byte_patch(data, off, old, new, note)

    def verify(self, data: bytes | bytearray) -> list[str]:
        located = find_section(data, SECTION_NAME)
        if located is None:
            return [f"no {SECTION_NAME} section: the file does not carry this patch"]
        section_va, section_off, _ = located
        problems: list[str] = []
        # The tables are written at runtime, so only the vtable and code are compared.
        want = build_section(section_va)[SLOT_COUNT * 8 :]
        start = section_off + SLOT_COUNT * 8
        if bytes(data[start : start + len(want)]) != want:
            problems.append(f"the {SECTION_NAME} cave does not hold the expected vtable and code")
        for va, _old, new, note in _edits(section_va):
            off = va_to_offset(data, va)
            if off is None or bytes(data[off : off + len(new)]) != new:
                problems.append(f"{note}: {va:#010x} is not patched")
        return problems
