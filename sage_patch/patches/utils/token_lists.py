"""Turning a single-token INI keyword into a **list** of them, without growing anything.

Several stock keywords name exactly one thing where a mod wants several -
`OnTriggerRechargeSpecialPower` names one special power, `ObjectCreationUpgrade`'s `GrantUpgrade`
and `RemoveUpgrade` name one upgrade each. All of them are stored as an `AsciiString` and parsed
by `INI::parseAsciiString`, which reads the **first** token on the line and returns, leaving the
rest unread: `Keyword = A B` therefore loads on a stock build and silently means `A`.

That shape is what makes the plural cheap. An `AsciiString` field is **one pointer** to a
refcounted buffer, so a list of names is simply a longer string - no `sizeof(ModuleData)` literal
to raise, no field-parse table to relocate for a wider row, no constructor shim to
default-construct a new member and no destructor to release it. A patch of this kind is therefore
two moves: repoint the entry's parse function at :func:`build_list_parser`, and replace whatever
reads the field with something that walks tokens.

**This module owns the first move only.** The second is each patch's own business, because what
"walks tokens" means differs entirely - `trigger-recharge-list` compares each token against a
template name, `upgrade-grant-lists` looks each one up in `TheUpgradeCenter` and applies it. What
they share is the string the two halves agree about, which is this one:

* tokens joined by **single spaces**, which is also what the engine's own multi-token fields look
  like, and a separator the value cannot contain (`INI::getNextAsciiString` tokenizes on
  whitespace, so an unquoted token never has one in it);
* **replaced, not appended**, on every line that writes the keyword, so an override block keeps
  the stock last-line-wins meaning;
* a **single token stored byte-for-byte as stock stored it**, which is what lets each patch leave
  its own single-name behaviour provably unchanged.
"""

from __future__ import annotations

from ...addresses import ASCII_STRING_SET
from ...asm import JNE, Asm

__all__ = [
    "ASCII_STRING_ASSIGN",
    "ASCII_STRING_CHARS",
    "ASCII_STRING_CONCAT_CHAR",
    "ASCII_STRING_CONCAT_CSTR",
    "ASCII_STRING_DTOR",
    "ASCII_STRING_IS_EMPTY",
    "ASCII_STRING_SET",
    "INI_NEXT_ASCII_STRING",
    "SEPARATOR",
    "STOCK_ASCII_STRING_PARSER",
    "build_list_parser",
]

#: `INI::parseAsciiString` - cdecl ``(INI *, void *instance, void *store, const void *userData)``.
#: The parse function every one-token keyword names, and the one a list patch replaces.
#: :data:`~...addresses.GAME_DATA_ASCIISTRING_PARSER` is the same function under the name its
#: `GlobalData` caller knows it by.
STOCK_ASCII_STRING_PARSER = 0x0042EE5E

#: `INI::getNextAsciiString(AsciiString *out)` - ``__thiscall`` on the `INI`, ``ret 4``, returns
#: ``out``. Sets ``out`` to the next token on the current line, handling quotes, and leaves it
#: **empty** at end of line: it reads the tokenizer state on the `INI`'s own line buffer
#: (`INI+0x86C`, through `INI::getNextTokenOrNull` at `0x0042DBF5`) and never advances to the next
#: line, which is what makes it safe to loop on.
INI_NEXT_ASCII_STRING = 0x0042E757

#: `AsciiString::isEmpty()` - ``__thiscall``, no arguments, ``al`` set when the string holds no
#: characters. A zeroed `AsciiString` answers "empty" without being dereferenced.
ASCII_STRING_IS_EMPTY = 0x00401E64

#: `AsciiString::operator=(const AsciiString &)` - ``__thiscall``, ``ret 4``. The assignment the
#: stock parser finishes with: it releases whatever the field held and takes a reference on the
#: source buffer.
ASCII_STRING_ASSIGN = 0x00436030

#: `AsciiString::concat(const char *)` and `AsciiString::concat(char)` - both ``__thiscall``,
#: ``ret 4``, both ending in the same worker at `0x004362E0`. Concatenating onto a
#: never-constructed (zeroed) `AsciiString` is safe: the worker sees a null buffer and assigns
#: instead (`0x0043634A`).
ASCII_STRING_CONCAT_CSTR = 0x0040511A
ASCII_STRING_CONCAT_CHAR = 0x0040513F

#: `AsciiString::~AsciiString()` - ``__thiscall``, no arguments, plain ``ret``. It drops the
#: buffer's reference and writes NULL back over ``m_data``, so calling it twice is harmless.
ASCII_STRING_DTOR = 0x00435D50

#: Where an `AsciiString`'s characters start, relative to the buffer its one pointer holds. The
#: buffer's header is ``{ UnsignedInt refCount; UInt16 length; UInt16 allocated; }``.
ASCII_STRING_CHARS = 8

#: What the parser joins tokens with, and what every consumer of one of these strings splits on.
SEPARATOR = 0x20


def build_list_parser(base_va: int) -> bytes:
    """A field parser that stores **every** token on the line, joined by single spaces.

    ``cdecl(INI *ini, void *instance, void *store, const void *userData)``, the shape every entry
    in a field-parse table has, so it is installed by writing its address into the entry and
    nothing else. Position-independent apart from its own ``call`` displacements, so a patch can
    lay it anywhere in its cave.

    Two `AsciiString` locals: the accumulator at ``[ebp-4]`` and the token at ``[ebp-8]``, both
    zeroed, which is a validly constructed empty string for every routine called here. The result
    is assigned into the field with the same `AsciiString::operator=` the stock parser used, so a
    field written twice in one block is *replaced* rather than appended to.

    No SEH frame is set up. The engine's INI errors throw, and a throw crossing this frame leaks
    the two locals' buffers rather than corrupting anything; an INI parse error already ends the
    load.
    """
    a = Asm(base_va)
    a.emit(0x55)  # push ebp
    a.emit(b"\x8b\xec")  # mov ebp, esp
    a.emit(b"\x83\xec\x08")  # sub esp, 8
    a.emit(b"\x83\x65\xfc\x00")  # and dword [ebp-4], 0   ; accumulator
    a.emit(b"\x83\x65\xf8\x00")  # and dword [ebp-8], 0   ; token

    a.label("next")
    a.emit(b"\x8d\x45\xf8")  # lea eax, [ebp-8]
    a.emit(0x50)  # push eax
    a.emit(b"\x8b\x4d\x08")  # mov ecx, [ebp+8]       ; the INI
    a.call_absolute(INI_NEXT_ASCII_STRING)  # call <getNextAsciiString>
    a.emit(b"\x8d\x4d\xf8")  # lea ecx, [ebp-8]
    a.call_absolute(ASCII_STRING_IS_EMPTY)  # call <isEmpty>
    a.emit(b"\x84\xc0")  # test al, al
    a.jcc(JNE, "done")  # jne .done              ; end of line

    a.emit(b"\x8d\x4d\xfc")  # lea ecx, [ebp-4]
    a.call_absolute(ASCII_STRING_IS_EMPTY)  # call <isEmpty>
    a.emit(b"\x84\xc0")  # test al, al
    a.jcc(JNE, "append")  # jne .append           ; first token: no separator
    a.emit(0x6A, SEPARATOR)  # push ' '
    a.emit(b"\x8d\x4d\xfc")  # lea ecx, [ebp-4]
    a.call_absolute(ASCII_STRING_CONCAT_CHAR)  # call <concat(char)>

    a.label("append")
    a.emit(b"\x8b\x45\xf8")  # mov eax, [ebp-8]       ; the token's buffer
    a.emit(b"\x83\xc0", bytes([ASCII_STRING_CHARS]))  # add eax, 8   ; its characters
    a.emit(0x50)  # push eax
    a.emit(b"\x8d\x4d\xfc")  # lea ecx, [ebp-4]
    a.call_absolute(ASCII_STRING_CONCAT_CSTR)  # call <concat(const char *)>
    a.jmp("next")  # jmp .next

    a.label("done")
    a.emit(b"\x8d\x45\xfc")  # lea eax, [ebp-4]
    a.emit(0x50)  # push eax
    a.emit(b"\x8b\x4d\x10")  # mov ecx, [ebp+0x10]    ; the field
    a.call_absolute(ASCII_STRING_ASSIGN)  # call <operator=>
    a.emit(b"\x8d\x4d\xf8")  # lea ecx, [ebp-8]
    a.call_absolute(ASCII_STRING_DTOR)  # call <~AsciiString>
    a.emit(b"\x8d\x4d\xfc")  # lea ecx, [ebp-4]
    a.call_absolute(ASCII_STRING_DTOR)  # call <~AsciiString>
    a.emit(0xC9)  # leave
    a.emit(0xC3)  # ret                    ; cdecl: the caller cleans
    return a.finish()
