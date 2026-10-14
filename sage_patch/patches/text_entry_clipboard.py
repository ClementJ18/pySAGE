"""Clipboard hotkeys at RotWK's tested Ctrl-navigation fallback.

ABI evidence, ownership and in-game acceptance checklist: ../docs/text-entry-clipboard.md.
"""

from __future__ import annotations

import struct

from ..addresses import (
    GET_MODULE_HANDLE_A_IAT,
    GET_PROC_ADDRESS_IAT,
    TEXT_ENTRY_CLIPBOARD_ANCHORS,
    TEXT_ENTRY_CLIPBOARD_BYTES,
    TEXT_ENTRY_CLIPBOARD_HOOK,
    TEXT_ENTRY_CLIPBOARD_RESUME,
    TEXT_ENTRY_INPUT,
    TEXT_ENTRY_SET_CURSOR,
    UNICODE_STRING_DTOR,
)
from ..asm import JB, JBE, JE, JNE, Asm
from ..patcher import Patch
from ..utils import (
    allocate_section,
    apply_byte_patch,
    file_offset,
    find_section,
    jmp_rel32,
    read_bytes,
    u32,
)

__all__ = ["TextEntryClipboardPatch", "build_code", "SECTION_NAME", "CODE_OFFSET", "APIS"]

SECTION_NAME = ".txtclip"
CODE_OFFSET = 256
KEY_STATE_DOWN = 0x0002
KEY_STATE_CONTROL = 0x000C
KEY_STATE_ALT = 0x00C0
KEY_STATE_SHIFT = 0x0430
KEY_A, KEY_C, KEY_X, KEY_V = 0x1E, 0x2E, 0x2D, 0x2F
KEY_DEL = 0xD3
GWM_CHAR, GWM_IME_CHAR = 0x15, 0x19
APIS = (
    "OpenClipboard",
    "GetClipboardData",
    "SetClipboardData",
    "EmptyClipboard",
    "CloseClipboard",
    "GetForegroundWindow",
    "GlobalAlloc",
    "GlobalFree",
    "GlobalLock",
    "GlobalUnlock",
    "GlobalSize",
)


def build_code(base: int) -> bytes:
    """Emit a read-only cave; all API pointers and operation state live on the stack."""
    block = bytearray(b"TXTCLP01".ljust(16, b"\0"))
    strings: dict[str, int] = {}
    for name in ("user32.dll", "kernel32.dll", *APIS):
        strings[name] = base + len(block)
        block.extend(name.encode("ascii") + b"\0")
    assert len(block) <= CODE_OFFSET
    a = Asm(base + CODE_OFFSET)

    def emit(hexcode: str) -> None:
        a.emit(bytes.fromhex(hexcode))

    def api(name: str) -> None:
        a.emit(0xFF, 0x57, APIS.index(name) * 4)  # call [edi+slot], stdcall

    def fail(label: str) -> None:
        emit("85c0")
        a.jcc(JE, label)

    def input_message(message: int, state: int, key: int | None = None) -> None:
        a.emit(0x6A, state)
        if key is None:
            a.emit(0x50)
        else:
            a.emit(0x68, u32(key))
        a.emit(0x6A, message)
        emit("ff7508")
        a.call_absolute(TEXT_ENTRY_INPUT)
        emit("83c410")

    emit("9c60")  # no new EBP frame: retain engine parameters and save all registers/flags
    emit("8b4514")
    a.emit(0xA9, u32(KEY_STATE_DOWN))
    a.jcc(JE, "fallback")
    a.emit(0xA9, u32(KEY_STATE_CONTROL))
    a.jcc(JE, "fallback")
    a.emit(0xA9, u32(KEY_STATE_ALT))  # Alt and AltGr must fall through
    a.jcc(JNE, "fallback")
    emit("8b4510")
    for key in (KEY_A, KEY_C, KEY_X, KEY_V):
        a.emit(0x83, 0xF8, key)
        a.jcc(JE, "recognized")
    a.label("fallback")
    emit("619d89550c")
    a.jmp_absolute(TEXT_ENTRY_CLIPBOARD_RESUME)
    a.label("recognized")
    emit("c7450c0100000083ec5089e7")  # 80 private bytes; edi is stable across engine/API calls
    emit("c7472c00000000c7473000000000c7473400000000")  # temporary, owned handle, copy success
    emit("83f81e")
    a.jcc(JE, "select_all")
    # A module reference is borrowed rather than LoadLibrary'd on each key press.
    for dll, names in (("user32.dll", APIS[:6]), ("kernel32.dll", APIS[6:])):
        a.emit(0x68, u32(strings[dll]), 0xFF, 0x15, u32(GET_MODULE_HANDLE_A_IAT))
        fail("done")
        emit("89c3")
        for name in names:
            a.emit(0x68, u32(strings[name]), 0x53, 0xFF, 0x15, u32(GET_PROC_ADDRESS_IAT))
            fail("done")
            a.emit(0x89, 0x47, APIS.index(name) * 4)
    emit("837d102f")
    a.jcc(JE, "paste")

    # Copy and cut share this path. No mutation of EntryData is needed to copy.
    emit("807e1200")
    a.jcc(JNE, "done")
    emit("0fb7461c0fb74e1e39c8")
    a.jcc(JBE, "ordered")
    emit("91")  # xchg eax,ecx
    a.label("ordered")
    emit("894738894f3c8b0e8b01ff500c")  # start/end; DisplayString::getTextLength
    emit("394738")
    a.jcc(JB, "empty")
    emit("894738")
    a.label("empty")
    emit("39473c")
    a.jcc(JBE, "length_clamped")
    emit("89473c")
    a.label("length_clamped")
    emit("8b473c3b4738")
    a.jcc(JBE, "done")
    emit("8b0e8b018d572c52ff50088b472c")  # getText(&temporary), callee pops hidden argument
    fail("copy_cleanup")
    # Clamp again against the backing string, independent of the virtual length result.
    emit("0fb748048b573c39ca")
    a.jcc(JBE, "backing_clamped")
    emit("89ca")
    a.label("backing_clamped")
    emit("2b5738")
    a.jcc(JBE, "copy_cleanup")
    emit("8957408b4f388d4448088947448d441200")  # source = header+8+2*start; bytes = 2*count
    emit("83c002506a02")  # terminator; GMEM_MOVEABLE
    api("GlobalAlloc")
    fail("copy_cleanup")
    emit("89473050")
    api("GlobalLock")
    fail("copy_cleanup")
    emit("8b57448b4f40")  # source and count; preserve EntryData in esi
    a.label("copy_loop")
    emit("668b1a66891883c20283c00249")
    a.jcc(JNE, "copy_loop")
    emit("66c7000000ff7730")
    api("GlobalUnlock")
    api("GetForegroundWindow")
    fail("copy_cleanup")
    emit("50")
    api("OpenClipboard")
    fail("copy_cleanup")
    api("EmptyClipboard")
    fail("copy_close")
    emit("ff77306a0d")
    api("SetClipboardData")
    fail("copy_close")
    emit("c7473000000000c7473401000000")  # Windows owns handle now; cut is allowed
    a.label("copy_close")
    api("CloseClipboard")
    a.label("copy_cleanup")
    emit("837f3000")
    a.jcc(JE, "release_string")
    emit("ff7730")
    api("GlobalFree")
    a.label("release_string")
    emit("8d4f2c")
    a.call_absolute(UNICODE_STRING_DTOR)
    emit("837f3400")
    a.jcc(JE, "done")
    emit("837d102d")
    a.jcc(JNE, "done")
    input_message(GWM_CHAR, KEY_STATE_DOWN, KEY_DEL)
    a.jmp("done")

    a.label("paste")
    emit("6a00")
    api("OpenClipboard")
    fail("done")
    emit("6a0d")
    api("GetClipboardData")
    fail("paste_close")
    emit("89473050")
    api("GlobalSize")
    emit("d1e8")  # avoid reading past a malformed, unterminated clipboard allocation
    fail("paste_close")
    emit("3d00100000")
    a.jcc(JBE, "paste_bound")
    a.emit(0xB8, u32(4096))
    a.label("paste_bound")
    emit("894740ff7730")
    api("GlobalLock")
    fail("paste_close")
    emit("89c3")  # ebx = cursor, API/engine preserve it
    a.label("paste_loop")
    emit("0fb70383c302")
    fail("paste_unlock")
    for char in (9, 10, 13):
        a.emit(0x83, 0xF8, char)
        a.jcc(JE, "paste_next")
    a.emit(0x3D, u32(0xD800))
    a.jcc(JB, "insert")
    a.emit(0x3D, u32(0xDFFF))
    a.jcc(JBE, "paste_next")
    a.label("insert")
    input_message(GWM_IME_CHAR, 0)
    a.label("paste_next")
    emit("ff4f40")
    a.jcc(JNE, "paste_loop")
    a.label("paste_unlock")
    emit("ff7730")
    api("GlobalUnlock")
    a.label("paste_close")
    api("CloseClipboard")
    a.jmp("done")

    a.label("select_all")
    emit("8b0e8b01ff500c50ff7508")
    a.call_absolute(TEXT_ENTRY_SET_CURSOR)
    emit("83c40866c7461e0000")
    a.label("done")
    emit("83c450619d")
    a.jmp_absolute(TEXT_ENTRY_CLIPBOARD_RESUME)
    return bytes(block).ljust(CODE_OFFSET, b"\0") + a.finish()


def _check_contract(data: bytes | bytearray) -> None:
    """Check the fixed-address engine and both imported resolver thunks before any mutation."""
    try:
        e = struct.unpack_from("<I", data, 0x3C)[0]
        opt = e + 24
        if (
            data[:2] != b"MZ"
            or data[e : e + 4] != b"PE\0\0"
            or struct.unpack_from("<H", data, e + 4)[0] != 0x14C
            or struct.unpack_from("<H", data, opt)[0] != 0x10B
            or struct.unpack_from("<I", data, opt + 28)[0] != 0x400000
            or struct.unpack_from("<H", data, opt + 70)[0] & 0x40
        ):
            raise ValueError("requires fixed-base x86 RotWK 2.01 PE32 (ImageBase 0x400000)")
        for va, expected in TEXT_ENTRY_CLIPBOARD_ANCHORS.items():
            if read_bytes(data, va, len(expected)) != expected:
                raise ValueError(
                    f"TextEntry contract mismatch at {va:#010x}; wrong build or conflict"
                )
        import_rva, size = struct.unpack_from("<II", data, opt + 104)
        found: dict[str, int] = {}
        for pos in range(0, min(size, 4096), 20):
            desc = read_bytes(data, 0x400000 + import_rva + pos, 20)
            original, _, _, dll, first = struct.unpack("<5I", desc)
            if not dll:
                break
            dll_off = file_offset(data, 0x400000 + dll)
            dll_name = bytes(data[dll_off : dll_off + 64]).split(b"\0", 1)[0].lower()
            if dll_name != b"kernel32.dll":
                continue
            for index in range(4096):
                thunk = struct.unpack(
                    "<I", read_bytes(data, 0x400000 + (original or first) + 4 * index, 4)
                )[0]
                if not thunk:
                    break
                if thunk & 0x80000000:
                    continue
                off = file_offset(data, 0x400000 + thunk + 2)
                name = bytes(data[off : off + 64]).split(b"\0", 1)[0].decode("ascii")
                found[name] = 0x400000 + first + 4 * index
        if (
            found.get("GetModuleHandleA") != GET_MODULE_HANDLE_A_IAT
            or found.get("GetProcAddress") != GET_PROC_ADDRESS_IAT
        ):
            raise ValueError("TextEntry resolver import contract mismatch")
    except (struct.error, UnicodeError, IndexError) as exc:
        raise ValueError("invalid or truncated TextEntry PE contract") from exc


class TextEntryClipboardPatch(Patch):
    """Enable Ctrl+A/C/X/V in RotWK 2.01 text entries; no INI changes."""

    name = "text-entry-clipboard"
    author = "Ostkannit"
    description = (
        "Enable Ctrl+A/C/X/V in text entries using the Windows UTF-16 clipboard; no INI changes"
    )

    def apply(self, data: bytearray) -> None:
        _check_contract(data)
        off = file_offset(data, TEXT_ENTRY_CLIPBOARD_HOOK)
        if read_bytes(data, TEXT_ENTRY_CLIPBOARD_HOOK, 8) != TEXT_ENTRY_CLIPBOARD_BYTES:
            raise ValueError(
                "TextEntry hook mismatch; already patched, wrong build or conflicting patch"
            )
        if find_section(data, SECTION_NAME) is not None:
            raise ValueError("TextEntry clipboard section already exists")
        # Build on a copy so even a section-allocation failure leaves the caller's bytes intact.
        result = bytearray(data)
        base = allocate_section(result, SECTION_NAME, build_code, 0x60000060)
        apply_byte_patch(
            result,
            off,
            TEXT_ENTRY_CLIPBOARD_BYTES,
            jmp_rel32(TEXT_ENTRY_CLIPBOARD_HOOK, base + CODE_OFFSET, 8),
            self.name,
        )
        data[:] = result

    def verify(self, data: bytes | bytearray) -> list[str]:
        try:
            _check_contract(data)
            located = find_section(data, SECTION_NAME)
            if located is None:
                return [f"missing {SECTION_NAME} section"]
            base, off, size = located
            expected = build_code(base)
            if size != len(expected) or data[off : off + size] != expected:
                return ["TextEntry clipboard cave mismatch"]
            if read_bytes(data, TEXT_ENTRY_CLIPBOARD_HOOK, 8) != jmp_rel32(
                TEXT_ENTRY_CLIPBOARD_HOOK, base + CODE_OFFSET, 8
            ):
                return ["TextEntry clipboard hook mismatch"]
        except ValueError as exc:
            return [str(exc)]
        return []
