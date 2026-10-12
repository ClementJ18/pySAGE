"""The registration skeleton of an upgrade module built as `TooltipUpgrade`'s layout twin.

A new upgrade behaviour needs four routines that have nothing to do with what it does: a stub that
adds its name to the `ModuleFactory`, a runtime factory, a `ModuleData` factory and the callback
that builds its field-parse tables. Cloning `TooltipUpgrade` gives all four for the price of two
copied vtables, because the stock `UpgradeMux` then evaluates `TriggeredBy`, `ConflictsWith` and
the rest, and only Apply (`+0x28`) and Unapply (`+0x20`) are the new module's own.

The stub is entered in place of some stock module's `addModule` call. It replays the six arguments
it displaces, so which module it wraps does not matter - only that no other patch wraps the same
call. Each patch names its own site and asserts the bytes in front of it.

`Worldbuilder.exe` links its own engine copy, so the editor half is a second skeleton against the
editor's addresses. It is parser-only: the editor never fires an upgrade, so it keeps Tooltip's
stock runtime factory and vtables.

Derivation: `../../docs/object-image-upgrade.md` (the twin) and
`../../docs/grant-science-upgrade.md` (the skeleton on its own).
"""

from __future__ import annotations

import struct
from collections.abc import Iterable, Sequence

from ...addresses import (
    ASCII_STRING_DTOR,
    OBJECT_IMAGE_UPGRADE_APPEND_FIELD_TABLE,
    OBJECT_IMAGE_UPGRADE_BUILD_UPGRADE_FIELDS,
    OBJECT_IMAGE_UPGRADE_MODULEDATA_CTOR,
    OBJECT_IMAGE_UPGRADE_MODULEDATA_VTABLE,
    OBJECT_IMAGE_UPGRADE_REGISTER,
    OBJECT_IMAGE_UPGRADE_REGISTER_CLEANUP,
    OBJECT_IMAGE_UPGRADE_RUNTIME_FACTORY_STOCK,
    OBJECT_IMAGE_UPGRADE_SET_ASCII_CSTR,
    OBJECT_IMAGE_UPGRADE_UPGRADE_VTABLE,
    OPERATOR_NEW,
    WORLDBUILDER_OBJECT_IMAGE_UPGRADE_APPEND_FIELD_TABLE,
    WORLDBUILDER_OBJECT_IMAGE_UPGRADE_ASCIISTRING_CTOR,
    WORLDBUILDER_OBJECT_IMAGE_UPGRADE_ASCIISTRING_DTOR,
    WORLDBUILDER_OBJECT_IMAGE_UPGRADE_BUILD_UPGRADE_FIELDS,
    WORLDBUILDER_OBJECT_IMAGE_UPGRADE_MODULEDATA_CTOR,
    WORLDBUILDER_OBJECT_IMAGE_UPGRADE_OPERATOR_NEW,
    WORLDBUILDER_OBJECT_IMAGE_UPGRADE_REGISTER,
    WORLDBUILDER_OBJECT_IMAGE_UPGRADE_REGISTER_CLEANUP,
    WORLDBUILDER_OBJECT_IMAGE_UPGRADE_RUNTIME_FACTORY_STOCK,
)
from ...asm import JE, Asm
from ...utils import read_bytes, u32

__all__ = [
    "CHARACTERISTICS",
    "FIELD_ROW_SIZE",
    "GAME_IMMEDIATES",
    "INTERFACE_MASK",
    "MODULEDATA_SIZE",
    "MODULEDATA_VTABLE_SIZE",
    "MUX_MODULE_DATA",
    "MUX_OBJECT",
    "UPGRADE_VTABLE_SIZE",
    "WORLDBUILDER_IMMEDIATES",
    "check_registration",
    "copied_vtables",
    "emit_game_skeleton",
    "emit_worldbuilder_skeleton",
    "field_table",
    "resolve_immediates",
]

#: The interface mask TooltipUpgrade registers with.
INTERFACE_MASK = 0x84
UPGRADE_VTABLE_SIZE = 0x48
MODULEDATA_VTABLE_SIZE = 0x80
#: Tooltip's `ModuleData`: two engine `AsciiString`s, at `+0x138` and `+0x13C`, end it. Both have
#: stock destructors, so neither slot can hold anything but a string.
MODULEDATA_SIZE = 0x140
#: UpgradeMux sits at runtime `+0x10`; the ModuleData and Object pointers are at `+0x04` and
#: `+0x08`, so Apply reaches them at these displacements from its `this`.
MUX_MODULE_DATA = -0x0C
MUX_OBJECT = -0x08
#: CNT_CODE | CNT_INITIALIZED_DATA | MEM_EXECUTE | MEM_READ: tables and code only, nothing written.
CHARACTERISTICS = 0x60000060
FIELD_ROW_SIZE = 16

#: The `push imm32` operands that name a routine emitted later in the same skeleton, as
#: `(label of the immediate, label of its target)`. `resolve_immediates` fills them in.
GAME_IMMEDIATES = (
    ("moduledata_factory_imm", "moduledata_factory"),
    ("runtime_factory_imm", "runtime_factory"),
    ("build_fields_imm", "build_fields"),
)
WORLDBUILDER_IMMEDIATES = (
    ("moduledata_factory_imm", "moduledata_factory"),
    ("build_fields_imm", "build_fields"),
)


def field_table(rows: Iterable[tuple[int, int, int]]) -> bytes:
    """A private field-parse table: one `(name VA, parser, ModuleData offset)` row per keyword,
    then the zero row that ends it."""
    out = bytearray()
    for name_va, parser, offset in rows:
        out += struct.pack("<4I", name_va, parser, 0, offset)
    return bytes(out) + bytes(FIELD_ROW_SIZE)


def check_registration(
    data: bytes | bytearray, call_va: int, prefix: bytes, call_bytes: bytes, build: str
) -> None:
    """Raise unless `call_va` still holds the stock `addModule` call, with the stock factory pushes
    in front of it. `build` names the binary and the wrapped module for the message."""
    if read_bytes(data, call_va - len(prefix), len(prefix)) != prefix:
        raise ValueError(f"unexpected {build}: factory arguments do not match")
    if read_bytes(data, call_va, len(call_bytes)) != call_bytes:
        raise ValueError(f"unexpected {build} or overlapping patch at {call_va:#010x}")


def resolve_immediates(code: Asm, immediates: Sequence[tuple[str, str]]) -> bytes:
    """The assembled bytes of `code`, with each forward `push imm32` pointed at its routine."""
    out = bytearray(code.finish())
    for immediate, target in immediates:
        struct.pack_into("<I", out, code.label_va(immediate) - code.base_va, code.label_va(target))
    return bytes(out)


def copied_vtables(data: bytes | bytearray, apply_va: int, unapply_va: int) -> bytes:
    """Tooltip's `UpgradeMux` vtable with Apply and Unapply replaced, then its ModuleData vtable
    verbatim: `UPGRADE_VTABLE_SIZE + MODULEDATA_VTABLE_SIZE` bytes."""
    upgrade = bytearray(read_bytes(data, OBJECT_IMAGE_UPGRADE_UPGRADE_VTABLE, UPGRADE_VTABLE_SIZE))
    struct.pack_into("<I", upgrade, 0x20, unapply_va)
    struct.pack_into("<I", upgrade, 0x28, apply_va)
    return bytes(upgrade) + read_bytes(
        data, OBJECT_IMAGE_UPGRADE_MODULEDATA_VTABLE, MODULEDATA_VTABLE_SIZE
    )


def emit_game_skeleton(
    a: Asm,
    *,
    block_name: int,
    upgrade_vtable: int,
    moduledata_vtable: int,
    table: int,
    moduledata_size: int = MODULEDATA_SIZE,
    after_ctor: bytes = b"",
) -> None:
    """Emit `register`, `runtime_factory`, `moduledata_factory` and `build_fields` for `game.dat`.

    `block_name` is the VA of the behaviour's name, the two vtables are the copies
    `copied_vtables` lays out, and `table` is the private `field_table`. A module that needs more
    than Tooltip's two strings passes a larger `moduledata_size` and, in `after_ctor`, the bytes
    that initialise the extra space with `esi` holding the new `ModuleData`.
    """
    # Entered in place of the wrapped addModule call: register it with its own six arguments, then
    # add our entry, and consume the originals with addModule's `ret 0x18`.
    a.label("register")
    a.emit(0x55, b"\x8b\xec", 0x56, b"\x8b\xf1")
    for disp in (0x1C, 0x18, 0x14, 0x10, 0x0C, 0x08):
        a.emit(b"\xff\x75", bytes([disp]))
    a.emit(b"\x8b\xce")
    a.call_absolute(OBJECT_IMAGE_UPGRADE_REGISTER)
    # A zeroed AsciiString slot on the stack, which ECX must address before the C-string is
    # pushed: `set` pops its argument, so the order is what keeps the name alive.
    a.emit(b"\x83\xec\x04", b"\x83\x24\x24\x00", b"\x8b\xcc")
    a.emit(b"\x68", u32(block_name))
    a.call_absolute(OBJECT_IMAGE_UPGRADE_SET_ASCII_CSTR)
    a.emit(b"\x68", u32(INTERFACE_MASK), 0x50, b"\x6a\x00\x6a\x00")
    a.emit(0x68)
    a.label("moduledata_factory_imm")
    a.emit(bytes(4), 0x68)
    a.label("runtime_factory_imm")
    a.emit(bytes(4), b"\x8b\xce")
    a.call_absolute(OBJECT_IMAGE_UPGRADE_REGISTER)
    a.emit(b"\x8b\xcc")
    a.call_absolute(ASCII_STRING_DTOR)
    a.emit(b"\x83\xc4\x04", 0x5E, 0x5D, b"\xc2\x18\x00")

    # TooltipUpgrade's runtime factory, then UpgradeMux (+0x10) repointed at our vtable copy so
    # Apply and Unapply are ours. The other vtables stay Tooltip's. The callback is cdecl.
    a.label("runtime_factory")
    a.emit(0x55, b"\x8b\xec", 0x56, b"\xff\x75\x0c", b"\xff\x75\x08")
    a.call_absolute(OBJECT_IMAGE_UPGRADE_RUNTIME_FACTORY_STOCK)
    a.emit(b"\x83\xc4\x08", b"\x8b\xf0", b"\x85\xf6")
    a.jcc(JE, "runtime_factory_done")
    a.emit(b"\xc7\x46\x10", u32(upgrade_vtable))
    a.label("runtime_factory_done")
    a.emit(b"\x8b\xc6", 0x5E, 0x5D, 0xC3)

    a.label("moduledata_factory")
    a.emit(0x55, b"\x8b\xec", 0x56, b"\x68", u32(moduledata_size))
    a.call_absolute(OPERATOR_NEW)
    a.emit(0x59, b"\x8b\xf0", b"\x85\xf6")
    a.jcc(JE, "moduledata_factory_done")
    a.emit(b"\x8b\xce")
    a.call_absolute(OBJECT_IMAGE_UPGRADE_MODULEDATA_CTOR)
    a.emit(after_ctor)
    a.emit(b"\xc7\x06", u32(moduledata_vtable))
    a.emit(b"\x8b\x4d\x08", b"\x85\xc9")
    a.jcc(JE, "moduledata_factory_done")
    a.emit(0x68)
    a.label("build_fields_imm")
    a.emit(bytes(4), 0x56)
    a.call_absolute(OBJECT_IMAGE_UPGRADE_REGISTER_CLEANUP)
    a.label("moduledata_factory_done")
    a.emit(b"\x8b\xc6", 0x5E, 0x5D, 0xC3)

    # The inherited UpgradeModule fields, then the private table.
    a.label("build_fields")
    a.emit(b"\x6a\x08")
    a.call_absolute(OBJECT_IMAGE_UPGRADE_BUILD_UPGRADE_FIELDS)
    a.emit(b"\x8b\x4c\x24\x08", 0x50)
    a.call_absolute(OBJECT_IMAGE_UPGRADE_APPEND_FIELD_TABLE)
    a.emit(b"\x8b\x4c\x24\x04", b"\x6a\x00", b"\x68", u32(table))
    a.call_absolute(OBJECT_IMAGE_UPGRADE_APPEND_FIELD_TABLE)
    a.emit(0xC3)


def emit_worldbuilder_skeleton(
    a: Asm,
    *,
    block_name: int,
    table: int,
    moduledata_size: int = MODULEDATA_SIZE,
    after_ctor: bytes = b"",
) -> None:
    """Emit `register`, `moduledata_factory` and `build_fields` for `Worldbuilder.exe`.

    The arguments are `emit_game_skeleton`'s, without the vtables the editor does not need.
    """
    # Entered in place of the wrapped addModule call, with its six arguments on our stack: copy
    # them for the stock call (`ret 0x18`), register the second name, then consume the originals
    # ourselves.
    a.label("register")
    a.emit(0x55, b"\x8b\xec", 0x56, 0x57, b"\x8b\xf1")
    for disp in (0x1C, 0x18, 0x14, 0x10, 0x0C, 0x08):
        a.emit(b"\xff\x75", bytes([disp]))
    a.emit(b"\x8b\xce")
    a.call_absolute(WORLDBUILDER_OBJECT_IMAGE_UPGRADE_REGISTER)

    # A real AsciiString that outlives addModule, built and destroyed with the same thunks the
    # stock initializer uses.
    a.emit(b"\x83\xec\x04", b"\xc7\x04\x24\x00\x00\x00\x00", b"\x8b\xfc")
    a.emit(0x68, u32(block_name), b"\x8b\xcf")
    a.call_absolute(WORLDBUILDER_OBJECT_IMAGE_UPGRADE_ASCIISTRING_CTOR)

    a.emit(b"\x68", u32(INTERFACE_MASK), 0x57, b"\x6a\x00\x6a\x00", 0x68)
    a.label("moduledata_factory_imm")
    a.emit(bytes(4), 0x68, u32(WORLDBUILDER_OBJECT_IMAGE_UPGRADE_RUNTIME_FACTORY_STOCK))
    a.emit(b"\x8b\xce")
    a.call_absolute(WORLDBUILDER_OBJECT_IMAGE_UPGRADE_REGISTER)

    a.emit(b"\x8b\xcf")
    a.call_absolute(WORLDBUILDER_OBJECT_IMAGE_UPGRADE_ASCIISTRING_DTOR)
    a.emit(b"\x83\xc4\x04", 0x5F, 0x5E, 0x5D, b"\xc2\x18\x00")

    # TooltipUpgrade's ModuleData, with only the parse-table callback replaced.
    a.label("moduledata_factory")
    a.emit(0x55, b"\x8b\xec", 0x56, b"\x68", u32(moduledata_size))
    a.call_absolute(WORLDBUILDER_OBJECT_IMAGE_UPGRADE_OPERATOR_NEW)
    a.emit(b"\x83\xc4\x04", b"\x8b\xf0", b"\x85\xf6")
    a.jcc(JE, "moduledata_factory_done")
    a.emit(b"\x8b\xce")
    a.call_absolute(WORLDBUILDER_OBJECT_IMAGE_UPGRADE_MODULEDATA_CTOR)
    a.emit(after_ctor)
    a.emit(b"\x8b\x4d\x08", b"\x85\xc9")
    a.jcc(JE, "moduledata_factory_done")
    a.emit(0x68)
    a.label("build_fields_imm")
    a.emit(bytes(4), 0x56, b"\x8b\x4d\x08")
    a.call_absolute(WORLDBUILDER_OBJECT_IMAGE_UPGRADE_REGISTER_CLEANUP)
    a.label("moduledata_factory_done")
    a.emit(b"\x8b\xc6", 0x5E, 0x5D, 0xC3)

    # Inherited UpgradeModule fields, then the private table. The EBP frame is load-bearing:
    # this debug build's buildUpgradeFields leaves its `8` argument for the first append to
    # consume, so the parser context must come from [ebp+8], not from ESP.
    a.label("build_fields")
    a.emit(0x55, b"\x8b\xec", b"\x6a\x08")
    a.call_absolute(WORLDBUILDER_OBJECT_IMAGE_UPGRADE_BUILD_UPGRADE_FIELDS)
    a.emit(0x50, b"\x8b\x4d\x08")
    a.call_absolute(WORLDBUILDER_OBJECT_IMAGE_UPGRADE_APPEND_FIELD_TABLE)
    a.emit(b"\x6a\x00", b"\x68", u32(table), b"\x8b\x4d\x08")
    a.call_absolute(WORLDBUILDER_OBJECT_IMAGE_UPGRADE_APPEND_FIELD_TABLE)
    a.emit(0x5D, 0xC3)
