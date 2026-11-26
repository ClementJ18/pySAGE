"""The engine half of a checkbox row on the shell Options screen, as cave emitters.

A row is three pieces of code that have nothing to do with what the option does: a ladder arm in
`AptOptions::InitGadgets` that claims the gadget by instance name and seeds it from `Options.ini`,
a store in `AptOptions::Save` that writes the box back as `yes`/`no` under the row's key, and a
reader that answers the key the way the engine's own boolean accessors do. Each patch that adds a
row owns its own hook sites and its own cave; only the bodies are shared.

The emitters take the addresses of the cave globals they use (the remembered gadget and its owning
`AptOptions`) and of the literals (gadget name, key, `yes`, `no`), because each cave lays those out
in its own data block. Labels are prefixed by the caller, so two rows could share one cave.

Derivation: `../../docs/options-menu-rows.md` §5-§6a.
"""

from __future__ import annotations

import struct

from ...addresses import (
    APT_INIT_GADGETS_EPILOGUE,
    APT_OPTIONS_SAVE_MAP_EBP,
    ASCII_STRING_CTOR,
    ASCII_STRING_DTOR,
    ASCII_STRING_SET,
    EMPTY_STRING,
    GET_CHECKBOX_STATE,
    OPTION_PREFERENCES_CTOR,
    OPTION_PREFERENCES_DTOR,
    PREFERENCES_MAP_FIND,
    PREFERENCES_MAP_INDEX,
    SET_CHECKBOX_STATE,
    STRICMP,
    YES_STRING,
)
from ...asm import JNE, JZ, Asm

__all__ = ["emit_arm_body", "emit_read", "emit_read_fresh", "emit_save_body"]


def emit_arm_body(
    a: Asm, prefix: str, gadget_name_va: int, owner_va: int, gadget_va: int, miss_va: int
) -> None:
    """A ladder arm: claim the gadget called `gadget_name_va`, or leave for `miss_va`.

    Entered with `AptOptions::InitGadgets`' frame live: `edi` the `AptOptions`, `esi` the gadget
    and `[ebp+8]` its instance name, exactly as every stock arm sees them. Needs `read_fresh` in
    the same cave.
    """
    a.label(f"{prefix}_mine")
    a.emit(0x68, struct.pack("<I", gadget_name_va))  # push <gadget name>
    a.emit(b"\xff\x75\x08")  # push dword [ebp+8]      ; the gadget's name
    a.call_absolute(STRICMP)  # call stricmp
    a.emit(b"\x83\xc4\x08")  # add esp, 8
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc(JNE, f"{prefix}_ladder")  # jne .ladder     ; someone else's row -> stock ladder

    # Ours. Remember the gadget and whose screen it belongs to, then show the saved value. Read
    # fresh, not from any cache: after a save-and-reopen a cache still holds the launch value.
    a.emit(0x89, 0x3D, struct.pack("<I", owner_va))  # mov [owner], edi
    a.emit(0x89, 0x35, struct.pack("<I", gadget_va))  # mov [gadget], esi
    a.call("read_fresh")  # call .read_fresh        ; eax = 0 or 1
    a.emit(0x50)  # push eax                        ; the state
    a.emit(0x56)  # push esi                        ; the gadget
    a.call_absolute(SET_CHECKBOX_STATE)  # call setCheckBoxState
    a.emit(b"\x83\xc4\x08")  # add esp, 8
    a.jmp_absolute(APT_INIT_GADGETS_EPILOGUE)

    a.label(f"{prefix}_ladder")
    a.jmp_absolute(miss_va)


def emit_save_body(
    a: Asm, prefix: str, owner_va: int, gadget_va: int, key_va: int, yes_va: int, no_va: int
) -> None:
    """The row's key, written into the map `AptOptions::Save` is about to flush.

    Entered inside `Save` with its frame live - the map at `[ebp-0x30]`, `edi` the `AptOptions` -
    and wrapped in `pushad`/`popad` by the caller's hook. Falls through to `{prefix}_done`, which
    the caller defines next, whether or not there was anything to write.
    """
    a.emit(0xA1, struct.pack("<I", owner_va))  # mov eax, [owner]
    a.emit(b"\x3b\xc7")  # cmp eax, edi
    a.jcc(JNE, f"{prefix}_done")  # jne .done        ; a screen our row never initialised
    a.emit(0xA1, struct.pack("<I", gadget_va))  # mov eax, [gadget]
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc(JZ, f"{prefix}_done")  # jz .done          ; the movie has no such gadget

    a.emit(0x50)  # push eax
    a.call_absolute(GET_CHECKBOX_STATE)  # call getCheckBoxState -> al
    a.emit(0x59)  # pop ecx
    a.emit(b"\x0f\xb6\xd8")  # movzx ebx, al      ; survives the calls below

    a.emit(0x6A, 0x00)  # push 0                  ; the scratch AsciiString
    a.emit(0x68, struct.pack("<I", key_va))  # push <key>
    a.emit(b"\x8d\x4c\x24\x04")  # lea ecx, [esp+4]
    a.call_absolute(ASCII_STRING_CTOR)  # call AsciiString::AsciiString   (ret 4)
    a.emit(b"\x8b\xc4")  # mov eax, esp           ; &key
    a.emit(0x50)  # push eax
    a.emit(b"\x8d\x8d", struct.pack("<i", APT_OPTIONS_SAVE_MAP_EBP))  # lea ecx, [ebp-0x30]
    a.call_absolute(PREFERENCES_MAP_INDEX)  # call map::operator[]  (ret 4) -> &value
    a.emit(b"\x85\xdb")  # test ebx, ebx
    a.jcc_short(JZ, f"{prefix}_no")  # jz .no
    a.emit(0x68, struct.pack("<I", yes_va))  # push <"yes">
    a.jmp_short(f"{prefix}_set")

    a.label(f"{prefix}_no")
    a.emit(0x68, struct.pack("<I", no_va))  # push <"no">

    a.label(f"{prefix}_set")
    a.emit(b"\x8b\xc8")  # mov ecx, eax           ; the map's value slot
    a.call_absolute(ASCII_STRING_SET)  # call AsciiString::operator=(const char *)  (ret 4)
    a.emit(b"\x8b\xcc")  # mov ecx, esp           ; &key
    a.call_absolute(ASCII_STRING_DTOR)  # call AsciiString::~AsciiString
    a.emit(b"\x83\xc4\x04")  # add esp, 4


def emit_read_fresh(a: Asm) -> None:
    """`bool read_fresh()` - construct an `OptionPreferences`, `read` the key, destroy it.

    0x80 bytes of stack is comfortably more than the object needs and costs nothing to
    over-reserve. `ebx`/`esi`/`edi` are preserved because callers hold live values in them.
    """
    a.label("read_fresh")
    a.emit(0x55)  # push ebp
    a.emit(b"\x8b\xec")  # mov ebp, esp
    a.emit(b"\x81\xec", struct.pack("<I", 0x80))  # sub esp, 0x80
    a.emit(0x53, 0x56, 0x57)  # push ebx / esi / edi
    a.emit(b"\x8d\x8d", struct.pack("<i", -0x80))  # lea ecx, [ebp-0x80]
    a.call_absolute(OPTION_PREFERENCES_CTOR)  # call OptionPreferences::ctor -> eax = this
    a.emit(b"\x8b\xc8")  # mov ecx, eax
    a.call("read")  # call .read                  ; al = the value
    a.emit(b"\x0f\xb6\xd8")  # movzx ebx, al      ; survive the dtor
    a.emit(b"\x8d\x8d", struct.pack("<i", -0x80))  # lea ecx, [ebp-0x80]
    a.call_absolute(OPTION_PREFERENCES_DTOR)  # call OptionPreferences::dtor
    a.emit(b"\x8b\xc3")  # mov eax, ebx
    a.emit(0x5F, 0x5E, 0x5B)  # pop edi / esi / ebx
    a.emit(0xC9)  # leave
    a.emit(0xC3)  # ret


def emit_read(a: Asm, key_va: int) -> None:
    """`bool read(OptionPreferences *this)` - `OPTION_PREFERENCES_GET_BOOL` with another key.

    Instruction for instruction the engine's own accessor: look the key up in the map at
    `this+4`, and answer true only if the stored value is `yes`. A key that is not in the file
    lands on the same `xor al, al` the stock routine uses, so an untouched `Options.ini` reads as
    off. Preserves `esi`/`edi`; clobbers `eax`, `ecx`, `edx`.
    """
    a.label("read")
    a.emit(0x55)  # push ebp
    a.emit(b"\x8b\xec")  # mov ebp, esp
    a.emit(0x51)  # push ecx                      ; reserve [ebp-4]
    a.emit(0x56, 0x57)  # push esi / push edi
    a.emit(b"\x8b\xf1")  # mov esi, ecx           ; this
    a.emit(0x68, struct.pack("<I", key_va))  # push <key>
    a.emit(b"\x8d\x4d\xfc")  # lea ecx, [ebp-4]
    a.call_absolute(ASCII_STRING_CTOR)  # call AsciiString::AsciiString
    a.emit(b"\x8d\x45\xfc")  # lea eax, [ebp-4]
    a.emit(b"\x83\xc6\x04")  # add esi, 4         ; -> the preference map
    a.emit(0x50)  # push eax
    a.emit(b"\x8b\xce")  # mov ecx, esi
    a.call_absolute(PREFERENCES_MAP_FIND)  # call map::find -> node, or the header
    a.emit(b"\x8d\x4d\xfc")  # lea ecx, [ebp-4]
    a.emit(b"\x8b\xf8")  # mov edi, eax
    a.call_absolute(ASCII_STRING_DTOR)  # call AsciiString::~AsciiString
    a.emit(b"\x3b\x3e")  # cmp edi, [esi]         ; end() is the header node
    a.jcc_short(JNE, "read_found")  # jne .found
    a.emit(b"\x32\xc0")  # xor al, al             ; absent -> off
    a.jmp_short("read_out")

    a.label("read_found")
    a.emit(b"\x8b\x7f\x14")  # mov edi, [edi+0x14]    ; the value AsciiString's buffer
    a.emit(b"\x85\xff")  # test edi, edi
    a.emit(b"\x8d\x47\x08")  # lea eax, [edi+8]       ; chars live at +8, not +4
    a.jcc_short(JNE, "read_compare")  # jne .compare
    a.emit(0xB8, struct.pack("<I", EMPTY_STRING))  # mov eax, <"">

    a.label("read_compare")
    a.emit(0x68, struct.pack("<I", YES_STRING))  # push <"yes">
    a.emit(0x50)  # push eax
    a.call_absolute(STRICMP)  # call stricmp
    a.emit(b"\xf7\xd8")  # neg eax                ; eax == 0  ->  al = 1
    a.emit(0x59)  # pop ecx
    a.emit(b"\x1a\xc0")  # sbb al, al
    a.emit(0x59)  # pop ecx
    a.emit(b"\xfe\xc0")  # inc al

    a.label("read_out")
    a.emit(0x5F, 0x5E)  # pop edi / pop esi
    a.emit(0xC9)  # leave
    a.emit(0xC3)  # ret
