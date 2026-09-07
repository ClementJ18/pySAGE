"""The script debug window's log, appended instead of rebuilt.

**Targets `DebugWindowLite.dll`, not `game.dat`** - the 172,032-byte MFC 7.1 dialog that ships
beside the game and that both `-scriptDebug2` and `-scriptDebugLite` load. Every address below is
derived in ``../../docs/script-debug-window.md``.

**The defect.** The dialog keeps every message of the session in a `std::vector<std::string>` at
`+0xEC` and rebuilds the whole window text from it on **every** appended line: `0x10002680` walks
the vector from the first message ever logged, concatenates each entry plus ``"\\r\\n"`` into one
string, hands the result to `SetWindowTextA`, and drives the caret to the end. So the cost of
message *N* is proportional to *N*, and a session's total is quadratic - the game thread blocking
in USER32 for all of it, inside the logic frame that produced the message. With a script-heavy map
the window's own redraw is what makes the game stutter.

Nothing trims the vector either. Its only clear (`0x10003440`) is referenced from one dword in the
dialog's MFC message map, so the log is emptied by a human clicking Clear and by nothing else.

**What this does.** Appends a `.dbgwnd` PE section and redirects the five bytes at `0x100034C5` -
the ``call updateDisplay`` inside the dialog's append method - into it. The cave appends the new
line to the edit control with `EM_REPLACESEL` and never rebuilds anything, so the per-line cost
stops depending on how much has already been logged. Both exports funnel through the hooked
method (`AppendMessage` at `0x1000165E`, `AppendMessageAndPause` at `0x100016CE`), so one hook
covers both.

**The pane next door already does it right**, which is why this reads as an oversight rather than
a design: `AdjustVariable` sets a dirty byte at `+0xDA` and lets `SetFrameNumber` rebuild the
variables list at most once a frame. The message pane has no such flag.

**The `push_back` is left standing**, so the vector still records every line and the Clear button
still works - it empties the vector and calls the stock rebuild, which now writes an empty buffer
over the control. The log's *memory* therefore still grows without bound. That is a second defect
and it is not fixed here.

**No INI change, and no `game.dat` change.** This patch is applied to the DLL:
``sage-patch apply script-debug-window --in DebugWindowLite.dll.backup --out DebugWindowLite.dll``.

**Reloc-free.** The DLL carries a `.reloc` section and can therefore be rebased, and this patch
writes no relocation entries, so the cave contains no absolute operand. The two imports it needs
are reached by recovering the load address from a ``call``/``pop`` pair, and the ``"\\r\\n"`` it
appends is built on the stack rather than pointed at in `.rdata`.

**Composition.** Nothing else in this package touches this binary, so the question is close to
moot - but the cave is allocated with :func:`~...utils.allocate_section` and located by name in
:meth:`verify` all the same, so a second DLL patch would compose with it.
"""

from __future__ import annotations

import struct

from ...asm import JB, JE, Asm
from ...patcher import Patch
from ...utils import allocate_section, apply_byte_patch, find_section, va_to_offset

__all__ = [
    "ANCHORS",
    "DIALOG_APPEND_MESSAGE",
    "HOOK_ORIGINAL",
    "HOOK_VA",
    "SECTION_NAME",
    "ScriptDebugWindowPatch",
    "UPDATE_DISPLAY",
    "build_code",
]

SECTION_NAME = ".dbgwnd"  # 7 chars: the PE name field is 8 bytes and truncates silently

#: `CDebugWindowDialog::appendMessage` - `push_back` into the message vector, then rebuild.
DIALOG_APPEND_MESSAGE = 0x100034B0
#: The rebuild the hook replaces. Not called by the cave; asserted so that a build whose layout
#: moved fails here rather than redirecting some other five bytes.
UPDATE_DISPLAY = 0x10002680

#: The ``call updateDisplay`` at the end of `DIALOG_APPEND_MESSAGE`, and its stock encoding.
HOOK_VA = 0x100034C5
HOOK_ORIGINAL = bytes.fromhex("e8b6f1ffff")

#: Where `HOOK_ORIGINAL` actually goes, decoded from its own bytes rather than written down, so
#: that "the redirected call is the rebuild" is a derived fact the anchor check enforces.
HOOK_TARGET = HOOK_VA + 5 + struct.unpack("<i", HOOK_ORIGINAL[1:5])[0]

#: The import address table slots the cave calls through. Each is anchored below to an instruction
#: in the stock image that provably uses it as that function.
IAT_GET_DLG_ITEM = 0x100192F0
IAT_SEND_MESSAGE = 0x10019340

#: `CWnd::m_hWnd`. Stated by the stock code at `0x100106FF` and again at `0x10002734`.
CWND_HWND = 0x1C
#: The message pane's edit control, in the dialog template.
MESSAGE_EDIT_CONTROL = 0x3EC

#: MSVC 7.1 `std::string`: a 16-byte union at `+4` holding the characters inline, or a `char *`
#: when the capacity at `+0x18` has reached `SSO_LIMIT`. The DLL states this at `0x100026CE`.
STRING_BUFFER = 0x04
STRING_CAPACITY = 0x18
SSO_LIMIT = 0x10

WM_GETTEXTLENGTH = 0x000E
EM_SETSEL = 0x00B1
EM_SCROLLCARET = 0x00B7
EM_REPLACESEL = 0x00C2

#: ``"\r\n"`` with its terminator, as the immediate of a ``push`` - the cave builds the separator
#: on the stack so that it needs no address, and therefore no relocation entry.
CRLF_IMMEDIATE = 0x00000A0D

# IMAGE_SCN_CNT_CODE | MEM_EXECUTE | MEM_READ - the cave is pure code and is never written.
_CHARACTERISTICS = 0x20 | 0x20000000 | 0x40000000

#: The first bytes at each address the patch depends on but does not write, as a `{va: bytes}`
#: map. The hook's own five bytes are asserted by `apply_byte_patch`; these are the append method
#: it sits in, the rebuild it replaces, the two exports that reach it, and the two instructions
#: that identify the import slots the cave calls through.
ANCHORS = {
    DIALOG_APPEND_MESSAGE: bytes.fromhex("8b44240456"),  # mov eax,[esp+4]; push esi
    UPDATE_DISPLAY: bytes.fromhex("5356578bf1"),  # push ebx/esi/edi; mov esi,ecx
    0x1000165E: bytes.fromhex("e84d1e0000"),  # AppendMessage         -> appendMessage
    0x100016CE: bytes.fromhex("e8dd1d0000"),  # AppendMessageAndPause -> appendMessage
    0x10010702: bytes.fromhex("ff15f0920110"),  # call [GetDlgItem], inside CWnd::GetDlgItem
    0x1000272C: bytes.fromhex("8b3d40930110"),  # mov edi,[SendMessageA], inside the rebuild
}

#: ``push 0`` / ``push eax`` / ``push ebx``, as the argument forms `_send_message` takes.
_PUSH_ZERO = bytes((0x6A, 0x00))
_PUSH_EAX = bytes((0x50,))
_PUSH_EBX = bytes((0x53,))


def _send_message(a: Asm, message: int, wparam: bytes, lparam: bytes) -> None:
    """``SendMessageA(esi, message, wparam, lparam)``, through the IAT slot `edi` points at.

    Arguments go on in reverse, so `lparam` is emitted first. `esi` holds the edit control's
    `HWND` throughout the cave and the callee cleans the stack, so nothing here disturbs it."""
    a.emit(lparam, wparam)
    a.emit(0x68, struct.pack("<I", message))  # push message
    a.emit(0x56)  # push esi
    a.emit(0xFF, 0x17)  # call dword [edi]


def build_code(base_va: int) -> bytes:
    """The replacement for the rebuild: append this one line to the edit control.

    Entered by `call` from `HOOK_VA` with `ecx` still holding the dialog (the stock
    ``mov ecx, esi`` one instruction earlier) and the `std::string *` argument of the append
    method five slots up the stack. Returns to `HOOK_VA + 5`, where the stock epilogue pops `esi`
    and returns, so the cave preserves `ebx`, `esi` and `edi` and clobbers only `eax`."""
    a = Asm(base_va)
    a.emit(0x53, 0x56, 0x57)  # push ebx; push esi; push edi
    a.emit(0x8B, 0x71, CWND_HWND)  # mov esi, [ecx+0x1c]  ; the dialog's own HWND
    a.emit(0x85, 0xF6)  # test esi, esi
    a.jcc(JE, "done")  # no window yet: the vector still took the line

    # The message. Three pushes deep, the append method's argument is at [esp+0x18].
    a.emit(0x8B, 0x44, 0x24, 0x18)  # mov eax, [esp+0x18]   ; const std::string *
    a.emit(0x83, 0x78, STRING_CAPACITY, SSO_LIMIT)  # cmp dword [eax+0x18], 0x10
    a.jcc(JB, "text_is_inline")
    a.emit(0x8B, 0x58, STRING_BUFFER)  # mov ebx, [eax+4]      ; the heap buffer
    a.jmp("have_text")
    a.label("text_is_inline")
    a.emit(0x8D, 0x58, STRING_BUFFER)  # lea ebx, [eax+4]      ; the characters themselves
    a.label("have_text")

    # Where the imports live, without an absolute operand: the return address a zero-displacement
    # `call` pushes is this instruction's *runtime* address, so subtracting its build-time offset
    # from the IAT slot yields the slot wherever the DLL was loaded.
    a.emit(0xE8, b"\x00\x00\x00\x00")  # call the next instruction
    a.label("load_base")
    a.emit(0x5F)  # pop edi
    delta = (a.label_va("load_base") - IAT_GET_DLG_ITEM) & 0xFFFFFFFF
    a.emit(0x81, 0xEF, struct.pack("<I", delta))  # sub edi, delta  ; edi = &__imp_GetDlgItem

    a.emit(0x68, struct.pack("<I", MESSAGE_EDIT_CONTROL))  # push 0x3ec
    a.emit(0x56)  # push esi           ; the dialog's HWND
    a.emit(0xFF, 0x17)  # call dword [edi]   ; GetDlgItem
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "done")
    a.emit(0x8B, 0xF0)  # mov esi, eax       ; the edit control from here on
    a.emit(0x83, 0xC7, IAT_SEND_MESSAGE - IAT_GET_DLG_ITEM)  # add edi, 0x50

    # Put the caret at the end, then replace the (empty) selection with the new line. This is what
    # the rebuild bought with a whole-buffer SetWindowTextA: the control appends and re-lays out
    # only what was added.
    _send_message(a, WM_GETTEXTLENGTH, _PUSH_ZERO, _PUSH_ZERO)
    _send_message(a, EM_SETSEL, _PUSH_EAX, _PUSH_EAX)  # eax = the length just returned
    _send_message(a, EM_REPLACESEL, _PUSH_ZERO, _PUSH_EBX)  # wParam 0: no undo record
    a.emit(0x68, struct.pack("<I", CRLF_IMMEDIATE))  # push "\r\n\0"
    a.emit(0x8B, 0xC4)  # mov eax, esp
    _send_message(a, EM_REPLACESEL, _PUSH_ZERO, _PUSH_EAX)
    a.emit(0x83, 0xC4, 0x04)  # add esp, 4         ; drop the separator
    _send_message(a, EM_SCROLLCARET, _PUSH_ZERO, _PUSH_ZERO)

    a.label("done")
    a.emit(0x5F, 0x5E, 0x5B)  # pop edi; pop esi; pop ebx
    a.emit(0xC3)  # ret
    return a.finish()


class ScriptDebugWindowPatch(Patch):
    name = "script-debug-window"
    author = "officialNecro"
    experimental = True
    description = (
        "Stop the script debug window rebuilding its whole log on every line, which makes the "
        "game stutter worse the longer it runs. Applied to DebugWindowLite.dll, not game.dat. No "
        "INI change"
    )

    def apply(self, data: bytearray) -> None:
        hook_off = va_to_offset(data, HOOK_VA)
        if hook_off is None:
            raise ValueError(f"{HOOK_VA:#010x} is not mapped - not DebugWindowLite.dll")
        self._check_anchors(data)
        section_va = allocate_section(data, SECTION_NAME, build_code, _CHARACTERISTICS)
        call = b"\xe8" + struct.pack("<i", section_va - (HOOK_VA + 5))
        apply_byte_patch(
            data,
            hook_off,
            HOOK_ORIGINAL,
            call,
            "debug dialog appendMessage rebuild -> script-debug-window cave",
        )

    @staticmethod
    def _check_anchors(data: bytes | bytearray) -> None:
        if HOOK_TARGET != UPDATE_DISPLAY:
            raise ValueError(
                f"the hooked call goes to {HOOK_TARGET:#010x}, not the rebuild at "
                f"{UPDATE_DISPLAY:#010x}"
            )
        for va, expected in ANCHORS.items():
            off = va_to_offset(data, va)
            if off is None:
                raise ValueError(f"{va:#010x} is not mapped - not DebugWindowLite.dll")
            got = bytes(data[off : off + len(expected)])
            if got != expected:
                raise ValueError(
                    f"{va:#010x} holds {got.hex()}, expected {expected.hex()} - this is not the "
                    "DebugWindowLite.dll this patch was written against, so the cave would append "
                    "to the wrong control or read the wrong string"
                )

    def verify(self, data: bytes | bytearray) -> list[str]:
        problems: list[str] = []
        located = find_section(data, SECTION_NAME)
        if located is None:
            return [f"{SECTION_NAME} section is absent"]
        section_va, section_off, _ = located
        off = va_to_offset(data, HOOK_VA)
        if off is None:
            return [f"{HOOK_VA:#010x} is not mapped by any section"]
        if data[off] != 0xE8:
            return [f"{HOOK_VA:#010x} is not a call - the hook is not installed"]
        target = HOOK_VA + 5 + struct.unpack_from("<i", data, off + 1)[0]
        if target != section_va:
            problems.append(f"hook calls {target:#010x}, expected {section_va:#010x}")
        code = build_code(section_va)
        if bytes(data[section_off : section_off + len(code)]) != code:
            problems.append(f"the {SECTION_NAME} cave does not hold the expected append routine")
        return problems
