"""Per-object select-portrait and button-image overrides driven by an upgrade.

Targets ROTWK ``game.dat`` build ``2.01.2614.37001``.  The patch registers a new
``ObjectImageUpgrade`` behaviour by cloning TooltipUpgrade's layout, not its registration::

    Behavior = ObjectImageUpgrade ModuleTag_Level5Image
      TriggeredBy    = Upgrade_Level_5
      SelectPortrait = HP_Hero_Level5
      ButtonImage    = HI_Hero_Level5
    End

Only the two instance-aware UI image resolvers are intercepted. Recruitment buttons use the
separate CommandButton path and remain stock. Applied modules live in a fixed sidecar keyed by
``Object *``, ObjectID and source module. UI resolution scans matching rows for a non-null image.
Image names are resolved once on every successful apply. The result is deliberately sticky: later
upgrade loss or a newly conflicting upgrade does not roll it back, while another successful apply
can overwrite it.

The sidecar contains presentation pointers only.  It is neither transferred nor CRC'd and uses
no clock, RNG or simulation mutation, so identical binaries/data cannot introduce a simulation
desync. The Apply/UI path, multiple behaviors, repeated triggers and the sticky semantics are
live-tested.
"""

from __future__ import annotations

import struct

from sage_ini.engine import BlockDelta, Engine, FieldDelta

from ..addresses import (
    ASCII_STRING_DTOR,
    GAME_DATA_ASCIISTRING_PARSER,
    OBJECT_IMAGE_UPGRADE_APPEND_FIELD_TABLE,
    OBJECT_IMAGE_UPGRADE_BUILD_UPGRADE_FIELDS,
    OBJECT_IMAGE_UPGRADE_BUTTON_HOOK,
    OBJECT_IMAGE_UPGRADE_BUTTON_RESUME,
    OBJECT_IMAGE_UPGRADE_FIND_IMAGE,
    OBJECT_IMAGE_UPGRADE_MODULEDATA_CTOR,
    OBJECT_IMAGE_UPGRADE_MODULEDATA_VTABLE,
    OBJECT_IMAGE_UPGRADE_REGISTER,
    OBJECT_IMAGE_UPGRADE_REGISTER_CALL,
    OBJECT_IMAGE_UPGRADE_REGISTER_CLEANUP,
    OBJECT_IMAGE_UPGRADE_RUNTIME_FACTORY_STOCK,
    OBJECT_IMAGE_UPGRADE_SELECT_DISPLACED_CALL,
    OBJECT_IMAGE_UPGRADE_SELECT_HOOK,
    OBJECT_IMAGE_UPGRADE_SELECT_RESUME,
    OBJECT_IMAGE_UPGRADE_SET_ASCII_CSTR,
    OBJECT_IMAGE_UPGRADE_THE_CONTROL_BAR,
    OBJECT_IMAGE_UPGRADE_THE_IMAGES,
    OBJECT_IMAGE_UPGRADE_UPGRADE_VTABLE,
    OPERATOR_NEW,
    WORLDBUILDER_OBJECT_IMAGE_UPGRADE_APPEND_FIELD_TABLE,
    WORLDBUILDER_OBJECT_IMAGE_UPGRADE_ASCIISTRING_CTOR,
    WORLDBUILDER_OBJECT_IMAGE_UPGRADE_ASCIISTRING_DTOR,
    WORLDBUILDER_OBJECT_IMAGE_UPGRADE_ASCIISTRING_PARSER,
    WORLDBUILDER_OBJECT_IMAGE_UPGRADE_BUILD_UPGRADE_FIELDS,
    WORLDBUILDER_OBJECT_IMAGE_UPGRADE_MODULEDATA_CTOR,
    WORLDBUILDER_OBJECT_IMAGE_UPGRADE_OPERATOR_NEW,
    WORLDBUILDER_OBJECT_IMAGE_UPGRADE_REGISTER,
    WORLDBUILDER_OBJECT_IMAGE_UPGRADE_REGISTER_CALL,
    WORLDBUILDER_OBJECT_IMAGE_UPGRADE_REGISTER_CLEANUP,
    WORLDBUILDER_OBJECT_IMAGE_UPGRADE_RUNTIME_FACTORY_STOCK,
)
from ..asm import JB, JE, JNE, Asm
from ..patcher import Patch
from ..utils import allocate_section, apply_byte_patch, find_section, va_to_offset
from .utils import name_tables

__all__ = [
    "ObjectImageUpgradePatch",
    "ObjectImageUpgradeWorldbuilderPatch",
    "SECTION_NAME",
    "WORLDBUILDER_SECTION_NAME",
]

SECTION_NAME = ".objimg"
BLOCK_NAME = "ObjectImageUpgrade"
FIELDS = (("SelectPortrait", 0x138), ("ButtonImage", 0x13C))

# TooltipUpgrade is the proven layout twin: ModuleData 0x140, runtime 0x1C, UpgradeMux at +0x10.
_REGISTER_BYTES = bytes.fromhex("e807c9ffff")
_UPGRADE_VTABLE_SIZE = 0x48
_MODULEDATA_VTABLE_SIZE = 0x80
_SELECT_BYTES = bytes.fromhex("568bf1e8eafcffff")
_BUTTON_BYTES = bytes.fromhex("837c240400")
_ROWS = 2048
_ROW_SIZE = 0x14  # Object *, ObjectID, source, select Image *, button Image *
_SIDECAR_SIZE = _ROWS * _ROW_SIZE
_MODULEDATA_SIZE = 0x140
_RUNTIME_SIZE = 0x1C

_CHARACTERISTICS = 0x20 | 0x40 | 0x20000000 | 0x40000000 | 0x80000000


def _u32(value: int) -> bytes:
    return struct.pack("<I", value)


def _at(data: bytes | bytearray, va: int, count: int) -> bytes:
    off = va_to_offset(data, va)
    if off is None:
        raise ValueError(f"{va:#010x} is not mapped - not the expected build")
    return bytes(data[off : off + count])


def _jmp(at_va: int, target_va: int) -> bytes:
    return b"\xe9" + struct.pack("<i", target_va - at_va - 5)


def _call(at_va: int, target_va: int) -> bytes:
    return b"\xe8" + struct.pack("<i", target_va - at_va - 5)


class ObjectImageUpgradePatch(Patch):
    """Install the ObjectImageUpgrade parser, module and presentation-only sidecar."""

    name = "object-image-upgrade"
    author = "Ostkannit"
    description = (
        "Adds a new Behavior ObjectImageUpgrade, which allows for per-object "
        "select-portrait and button-image overrides driven by an upgrade. "
        "The Behavior should be triggered less than 2048 times in total per active game-session, "
        "as the patch uses a fixed-size sidecar to store the overrides"
    )

    def _layout(self, base: int) -> dict[str, int]:
        cursor = base + _SIDECAR_SIZE
        out: dict[str, int] = {"sidecar": base}

        for name, size in (
            ("upgrade", _UPGRADE_VTABLE_SIZE),
            ("moduledata", _MODULEDATA_VTABLE_SIZE),
        ):
            out[name] = cursor
            cursor += size

        out["table"] = cursor
        cursor += 3 * 16

        for name, raw in (
            ("block_name", BLOCK_NAME),
            ("select_name", FIELDS[0][0]),
            ("button_name", FIELDS[1][0]),
        ):
            out[name] = cursor
            cursor += len(raw) + 1

        cursor = (cursor + 3) & ~3
        out["code"] = cursor

        return out

    def _assemble(self, base: int) -> Asm:
        layout = self._layout(base)
        a = Asm(layout["code"])

        # Register stock TooltipUpgrade first, then append our independent factory entry.
        a.label("register")
        a.emit(0x55, b"\x8b\xec", 0x56, b"\x8b\xf1")
        for disp in (0x1C, 0x18, 0x14, 0x10, 0x0C, 0x08):
            a.emit(b"\xff\x75", bytes([disp]))
        a.emit(b"\x8b\xce")
        a.call_absolute(OBJECT_IMAGE_UPGRADE_REGISTER)
        a.emit(b"\x83\xec\x04", b"\x83\x24\x24\x00", b"\x8b\xcc")
        a.emit(b"\x68", _u32(layout["block_name"]))
        a.call_absolute(OBJECT_IMAGE_UPGRADE_SET_ASCII_CSTR)
        a.emit(b"\x68\x84\x00\x00\x00", 0x50, b"\x6a\x00\x6a\x00")
        a.emit(0x68)
        a.label("moduledata_factory_imm")
        a.emit(bytes(4), 0x68)
        a.label("runtime_factory_imm")
        a.emit(bytes(4), b"\x8b\xce")
        a.call_absolute(OBJECT_IMAGE_UPGRADE_REGISTER)
        a.emit(b"\x8b\xcc")
        a.call_absolute(ASCII_STRING_DTOR)
        a.emit(b"\x83\xc4\x04", 0x5E, 0x5D, b"\xc2\x18\x00")

        a.label("runtime_factory")
        # Delegate allocation and construction to TooltipUpgrade's exact factory.  The callback
        # is cdecl (plain RET), while its thiscall constructor consumes its own two arguments.
        a.emit(0x55, b"\x8b\xec", 0x56, b"\xff\x75\x0c", b"\xff\x75\x08")
        a.call_absolute(OBJECT_IMAGE_UPGRADE_RUNTIME_FACTORY_STOCK)
        a.emit(b"\x83\xc4\x08", b"\x8b\xf0", b"\x85\xf6")
        a.jcc(JE, "runtime_factory_done")
        # Preserve the constructor-set primary/behavior/aux vtables. Only UpgradeMux differs.
        a.emit(b"\xc7\x46\x10", _u32(layout["upgrade"]))
        a.label("runtime_factory_done")
        a.emit(b"\x8b\xc6", 0x5E, 0x5D, 0xC3)

        a.label("moduledata_factory")
        a.emit(0x55, b"\x8b\xec", 0x56, b"\x68", _u32(_MODULEDATA_SIZE))
        a.call_absolute(OPERATOR_NEW)
        a.emit(0x59, b"\x8b\xf0", b"\x85\xf6")
        a.jcc(JE, "moduledata_factory_done")

        a.emit(b"\x8b\xce")
        a.call_absolute(OBJECT_IMAGE_UPGRADE_MODULEDATA_CTOR)

        a.emit(b"\xc7\x06", _u32(layout["moduledata"]))

        a.emit(b"\x8b\x4d\x08", b"\x85\xc9")
        a.jcc(JE, "moduledata_factory_done")

        a.emit(0x68)
        a.label("build_fields_imm")
        a.emit(bytes(4), 0x56)
        a.call_absolute(OBJECT_IMAGE_UPGRADE_REGISTER_CLEANUP)

        a.label("moduledata_factory_done")
        a.emit(b"\x8b\xc6", 0x5E, 0x5D, 0xC3)

        a.label("build_fields")

        a.emit(b"\x6a\x08")
        a.call_absolute(OBJECT_IMAGE_UPGRADE_BUILD_UPGRADE_FIELDS)

        a.emit(b"\x8b\x4c\x24\x08", 0x50)
        a.call_absolute(OBJECT_IMAGE_UPGRADE_APPEND_FIELD_TABLE)

        a.emit(
            b"\x8b\x4c\x24\x04",
            b"\x6a\x00",
            b"\x68",
            _u32(layout["table"]),
        )
        a.call_absolute(OBJECT_IMAGE_UPGRADE_APPEND_FIELD_TABLE)

        a.emit(0xC3)

        a.label("apply")

        a.emit(
            0x53,  # push ebx
            0x55,  # push ebp
            0x56,  # push esi
            0x57,  # push edi
            b"\x8b\xf1",  # mov esi,ecx       ; UpgradeMux*
            b"\x8b\x7e\xf8",  # mov edi,[esi-08]  ; Object*
            b"\x85\xff",  # test edi,edi
        )
        a.jcc(JE, "apply_done")

        # Keep an existing instance/source row, or a conclusively stale same-pointer row, in a
        # stack local. On reuse, close the old gap and rewrite the row at the occupied tail; this
        # avoids duplicates while preserving the resolvers' "last matching row wins" ordering.
        a.emit(
            b"\x8d\x6e\xf0",  # lea ebp,[esi-10] ; source runtime
            b"\x6a\x00",  # existing-row local
            b"\xbb",
            _u32(layout["sidecar"]),
            b"\x31\xc0",
            b"\x8b\x57\x74",  # mov edx,[edi+74] ; ObjectID
        )
        a.label("apply_scan")
        a.emit(b"\x83\x3b\x00")  # cmp dword ptr [ebx],0
        a.jcc(JE, "apply_scan_done")
        a.emit(b"\x39\x3b")  # cmp [ebx],edi ; same Object*?
        a.jcc(JNE, "apply_next")
        a.emit(b"\x39\x53\x04")  # cmp [ebx+04],edx ; same ObjectID?
        a.jcc(JE, "apply_same_instance")
        a.emit(b"\x83\x3c\x24\x00")  # no better reusable row remembered yet?
        a.jcc(JNE, "apply_next")
        a.emit(b"\x89\x1c\x24")  # remember stale same-pointer row
        a.jmp("apply_next")
        a.label("apply_same_instance")
        a.emit(b"\x39\x6b\x08")  # cmp [ebx+08],ebp ; same source runtime?
        a.jcc(JNE, "apply_next")
        a.emit(b"\x89\x1c\x24")  # exact match supersedes stale candidate
        a.label("apply_next")
        a.emit(b"\x83\xc3", bytes([_ROW_SIZE]), 0x40, b"\x3d", _u32(_ROWS))
        a.jcc(JB, "apply_scan")

        a.label("apply_scan_done")
        a.emit(b"\x8b\x14\x24", b"\x85\xd2")  # edx = existing
        a.jcc(JE, "apply_new_slot")

        # Stable removal. EBX is the first free row (or one-past-table when full); EDX finishes at
        # the vacated occupied-tail row, which is then rewritten by the normal resolution path.
        a.label("apply_shift")
        a.emit(b"\x8d\x4a\x14", b"\x3b\xcb")
        a.jcc(JE, "apply_reused_slot")
        a.emit(
            b"\x8b\x01",
            b"\x89\x02",
            b"\x8b\x41\x04",
            b"\x89\x42\x04",
            b"\x8b\x41\x08",
            b"\x89\x42\x08",
            b"\x8b\x41\x0c",
            b"\x89\x42\x0c",
            b"\x8b\x41\x10",
            b"\x89\x42\x10",
            b"\x8b\xd1",
        )
        a.jmp("apply_shift")

        a.label("apply_reused_slot")
        a.emit(b"\x8b\xda")  # ebx = vacated occupied-tail row
        a.jmp("apply_slot")

        a.label("apply_new_slot")
        a.emit(b"\x3d", _u32(_ROWS))
        a.jcc(JE, "apply_done_local")  # full and no reusable row

        a.label("apply_slot")
        a.emit(
            b"\x89\x3b",  # mov [ebx],edi    ; Object*
            b"\x8b\x47\x74",  # mov eax,[edi+74] ; ObjectID
            b"\x89\x43\x04",  # store ObjectID
            b"\x89\x6b\x08",  # source runtime
            b"\x8b\x6e\xf4",  # mov ebp,[esi-0C] ; ModuleData*
            b"\xc7\x43\x0c\x00\x00\x00\x00",
            b"\xc7\x43\x10\x00\x00\x00\x00",
        )

        # SelectPortrait
        a.emit(
            b"\x8b\x0d",
            _u32(OBJECT_IMAGE_UPGRADE_THE_IMAGES),
            b"\x85\xc9",
        )
        a.jcc(JE, "apply_button_image")

        a.emit(
            b"\x8d\x85\x38\x01\x00\x00",  # lea eax,[ebp+138]
            0x50,  # push eax
        )
        a.call_absolute(OBJECT_IMAGE_UPGRADE_FIND_IMAGE)

        a.emit(
            b"\x89\x43\x0c",  # row.selectPortrait = eax
        )

        # ButtonImage
        a.label("apply_button_image")
        a.emit(
            b"\x8b\x0d",
            _u32(OBJECT_IMAGE_UPGRADE_THE_IMAGES),
            b"\x85\xc9",
        )
        a.jcc(JE, "apply_dirty")

        a.emit(
            b"\x8d\x85\x3c\x01\x00\x00",  # lea eax,[ebp+13C]
            0x50,  # push eax
        )
        a.call_absolute(OBJECT_IMAGE_UPGRADE_FIND_IMAGE)

        a.emit(
            b"\x89\x43\x10",  # row.buttonImage = eax
        )

        a.label("apply_dirty")
        a.emit(
            b"\xa1",
            _u32(OBJECT_IMAGE_UPGRADE_THE_CONTROL_BAR),
            b"\x85\xc0",
        )
        a.jcc(JE, "apply_done_local")
        a.emit(b"\xc6\x40\x28\x01")

        a.label("apply_done_local")
        a.emit(b"\x83\xc4\x04")  # discard existing-row local
        a.label("apply_done")
        a.emit(0x5F, 0x5E, 0x5D, 0x5B, 0xC3)

        a.label("unapply")
        a.emit(0xC3)

        # Select portrait hook. ECX = Object*.
        # Sidecar row:
        #   +00 Object*, +04 ObjectID, +08 source runtime*
        #   +0C SelectPortrait Image*, +10 ButtonImage Image*
        a.label("select_hook")
        a.emit(
            0x53,  # push ebx
            0x55,  # push ebp
            0x56,  # push esi
            0x57,  # push edi
            b"\x8b\xf9",  # mov edi,ecx       ; Object*
            b"\x8b\x77\x74",  # mov esi,[edi+74]  ; ObjectID
            b"\x31\xed",  # xor ebp,ebp       ; result = nullptr
            b"\xb9",
            _u32(layout["sidecar"]),
            b"\x31\xc0",  # xor eax,eax       ; row index
        )

        a.label("select_scan")

        # row.object == current Object* ?
        a.emit(b"\x39\x39")  # cmp [ecx],edi
        a.jcc(JNE, "select_next")
        a.emit(b"\x39\x71\x04")  # cmp [ecx+04],esi
        a.jcc(JNE, "select_next")

        a.emit(
            b"\x8b\x59\x0c",  # mov ebx,[ecx+0C]  ; SelectPortrait Image*
            b"\x85\xdb",  # test ebx,ebx
        )
        a.jcc(JE, "select_next")
        a.emit(b"\x8b\xeb")

        a.label("select_next")
        a.emit(
            b"\x83\xc1",
            bytes([_ROW_SIZE]),
            0x40,
            b"\x3d",
            _u32(_ROWS),
        )
        a.jcc(JB, "select_scan")

        a.emit(b"\x85\xed")
        a.jcc(JE, "select_fallback")

        a.emit(
            b"\x8b\xc5",  # mov eax,ebp
            0x5F,  # pop edi
            0x5E,  # pop esi
            0x5D,  # pop ebp
            0x5B,  # pop ebx
            0xC3,
        )

        a.label("select_fallback")
        a.emit(
            b"\x8b\xcf",  # mov ecx,edi ; restore Object*
            0x5F,
            0x5E,
            0x5D,
            0x5B,
            # displaced vanilla:
            0x56,  # push esi
            b"\x8b\xf1",  # mov esi,ecx
        )
        a.call_absolute(OBJECT_IMAGE_UPGRADE_SELECT_DISPLACED_CALL)
        a.jmp_absolute(OBJECT_IMAGE_UPGRADE_SELECT_RESUME)

        # Button hook:
        # Image* __cdecl GetEffectiveObjectButtonImage(
        #     ObjectTemplate* displayTemplate,
        #     Object* object);
        #
        # Only the initial five-byte CMP is displaced.
        a.label("button_hook")
        a.emit(
            0x53,
            0x55,
            0x56,
            0x57,
            # Four pushes => original arg2 Object* is at ESP+18.
            b"\x8b\x7c\x24\x18",  # mov edi,[esp+18] ; Object*
            b"\x85\xff",
        )
        a.jcc(JE, "button_fallback")

        a.emit(
            b"\x8b\x77\x74",  # mov esi,[edi+74] ; ObjectID
            b"\x31\xed",  # xor ebp,ebp
            b"\xb9",
            _u32(layout["sidecar"]),
            b"\x31\xc0",
        )

        a.label("button_scan")

        a.emit(b"\x39\x39")  # cmp [ecx],edi
        a.jcc(JNE, "button_next")
        a.emit(b"\x39\x71\x04")  # cmp [ecx+04],esi
        a.jcc(JNE, "button_next")

        a.emit(
            b"\x8b\x59\x10",  # mov ebx,[ecx+10]
            b"\x85\xdb",
        )
        a.jcc(JE, "button_next")
        a.emit(b"\x8b\xeb")

        a.label("button_next")
        a.emit(
            b"\x83\xc1",
            bytes([_ROW_SIZE]),
            0x40,
            b"\x3d",
            _u32(_ROWS),
        )
        a.jcc(JB, "button_scan")

        a.emit(b"\x85\xed")
        a.jcc(JE, "button_fallback")

        a.emit(
            b"\x8b\xc5",
            0x5F,
            0x5E,
            0x5D,
            0x5B,
            0xC3,
        )

        a.label("button_fallback")
        a.emit(
            0x5F,
            0x5E,
            0x5D,
            0x5B,
            b"\x83\x7c\x24\x04\x00",  # displaced vanilla CMP
        )
        a.jmp_absolute(OBJECT_IMAGE_UPGRADE_BUTTON_RESUME)

        a.finish()
        return a

    def _code_bytes(self, base: int) -> bytes:
        code = self._assemble(base)
        out = bytearray(code.finish())
        for immediate, target in (
            (
                "moduledata_factory_imm",
                code.label_va("moduledata_factory"),
            ),
            (
                "runtime_factory_imm",
                code.label_va("runtime_factory"),
            ),
            ("build_fields_imm", code.label_va("build_fields")),
        ):
            offset = code.label_va(immediate) - code.base_va
            struct.pack_into("<I", out, offset, target)
        return bytes(out)

    def _build(self, data: bytes | bytearray, base: int) -> bytes:
        layout = self._layout(base)

        upgrade = bytearray(_at(data, OBJECT_IMAGE_UPGRADE_UPGRADE_VTABLE, _UPGRADE_VTABLE_SIZE))

        code = self._assemble(base)

        struct.pack_into(
            "<I",
            upgrade,
            0x20,
            code.label_va("unapply"),
        )
        struct.pack_into(
            "<I",
            upgrade,
            0x28,
            code.label_va("apply"),
        )

        table = bytearray()

        for index, (_name, offset) in enumerate(FIELDS):
            name_va = layout["select_name" if index == 0 else "button_name"]

            table += struct.pack(
                "<4I",
                name_va,
                GAME_DATA_ASCIISTRING_PARSER,
                0,
                offset,
            )

        # Field-table terminator.
        table += bytes(16)

        out = bytearray(_SIDECAR_SIZE)

        # These correspond 1:1 to the entries reserved by _layout(). Runtime construction keeps
        # TooltipUpgrade's primary/behavior/aux vtables and replaces only UpgradeMux at +0x10.
        out += upgrade
        out += _at(
            data,
            OBJECT_IMAGE_UPGRADE_MODULEDATA_VTABLE,
            _MODULEDATA_VTABLE_SIZE,
        )

        out += table

        out += BLOCK_NAME.encode() + b"\0"
        out += FIELDS[0][0].encode() + b"\0"
        out += FIELDS[1][0].encode() + b"\0"

        # Align start of generated code to 4 bytes.
        out += b"\0" * (-len(out) % 4)

        assert base + len(out) == layout["code"]

        out += self._code_bytes(base)

        return bytes(out)

    def apply(self, data: bytearray) -> None:
        for va, expected in (
            (OBJECT_IMAGE_UPGRADE_REGISTER_CALL, _REGISTER_BYTES),
            (OBJECT_IMAGE_UPGRADE_SELECT_HOOK, _SELECT_BYTES),
            (OBJECT_IMAGE_UPGRADE_BUTTON_HOOK, _BUTTON_BYTES),
        ):
            if _at(data, va, len(expected)) != expected:
                raise ValueError(f"unexpected build or overlapping patch at {va:#010x}")
        base = allocate_section(
            data, SECTION_NAME, lambda va: self._build(data, va), _CHARACTERISTICS
        )
        code = self._assemble(base)

        edits = (
            (
                OBJECT_IMAGE_UPGRADE_REGISTER_CALL,
                _REGISTER_BYTES,
                _call(OBJECT_IMAGE_UPGRADE_REGISTER_CALL, code.label_va("register")),
                "register ObjectImageUpgrade",
            ),
            (
                OBJECT_IMAGE_UPGRADE_SELECT_HOOK,
                _SELECT_BYTES,
                _jmp(OBJECT_IMAGE_UPGRADE_SELECT_HOOK, code.label_va("select_hook")) + b"\x90" * 3,
                "instance select portrait",
            ),
            (
                OBJECT_IMAGE_UPGRADE_BUTTON_HOOK,
                _BUTTON_BYTES,
                _jmp(OBJECT_IMAGE_UPGRADE_BUTTON_HOOK, code.label_va("button_hook")),
                "instance button image",
            ),
        )
        for va, old, new, note in edits:
            apply_byte_patch(data, va_to_offset(data, va) or 0, old, new, note)

    def verify(self, data: bytes | bytearray) -> list[str]:
        located = find_section(data, SECTION_NAME)
        if located is None:
            return [f"no {SECTION_NAME} section: the file does not carry this patch"]
        base, section_off, _size = located
        code = self._assemble(base)
        expected = self._build(data, base)
        problems: list[str] = []
        got = bytes(data[section_off : section_off + len(expected)])
        if got != expected:
            problems.append(f"{SECTION_NAME} does not hold the expected sidecar, tables and code")
        for va, want in (
            (
                OBJECT_IMAGE_UPGRADE_REGISTER_CALL,
                _call(OBJECT_IMAGE_UPGRADE_REGISTER_CALL, code.label_va("register")),
            ),
            (
                OBJECT_IMAGE_UPGRADE_SELECT_HOOK,
                _jmp(OBJECT_IMAGE_UPGRADE_SELECT_HOOK, code.label_va("select_hook")) + b"\x90" * 3,
            ),
            (
                OBJECT_IMAGE_UPGRADE_BUTTON_HOOK,
                _jmp(OBJECT_IMAGE_UPGRADE_BUTTON_HOOK, code.label_va("button_hook")),
            ),
        ):
            if _at(data, va, len(want)) != want:
                problems.append(f"hook at {va:#010x} does not point into {SECTION_NAME}")
        return problems

    def ini_surface(self) -> Engine:
        return Engine(
            blocks=(BlockDelta(BLOCK_NAME, base="Behavior", patch=self.name),),
            fields=tuple(
                FieldDelta(BLOCK_NAME, name, "Ref:mappedimages", patch=self.name)
                for name, _offset in FIELDS
            ),
        )


# The Worldbuilder half. The editor links an independent debug build of the engine and constructs
# its own ModuleFactory. Registering a behavior in `game.dat` therefore does not teach the editor
# its block name or fields. Unlike the game half, this twin is parser-only: TooltipUpgrade's stock
# runtime is sufficient because Worldbuilder never needs the presentation sidecar or the UI hooks.

# Eight bytes exactly: PE section names are not NUL-terminated when every byte is used.
WORLDBUILDER_SECTION_NAME = ".wbobjim"

_WORLDBUILDER_INTERFACE_MASK = 0x84
_WORLDBUILDER_REGISTER_BYTES = bytes.fromhex("e8fce00100")
_WORLDBUILDER_REGISTER_PREFIX = bytes.fromhex(
    # push Tooltip ModuleData factory; push Tooltip runtime factory; mov ecx, ModuleFactory*
    "6810b5c80068a0b4c8008b8d18fbffff"
)
# CNT_CODE | CNT_INITIALIZED_DATA | MEM_EXECUTE | MEM_READ. The editor cave has immutable tables
# and code only; unlike the game-side section, it contains no writable sidecar.
_WORLDBUILDER_CHARACTERISTICS = 0x60000060


class ObjectImageUpgradeWorldbuilderPatch(Patch):
    """Teach **Worldbuilder** to parse the ObjectImageUpgrade behavior.

    **This patch targets `Worldbuilder.exe`, not `game.dat`.** It is the authoring half of
    :class:`ObjectImageUpgradePatch`: the editor gains the block name and its two image fields,
    while all live image resolution remains in the game-side patch.
    """

    name = "object-image-upgrade-wb"
    author = "Ostkannit"
    description = (
        "Worldbuilder.exe (not game.dat): register the ObjectImageUpgrade Behavior and its "
        "SelectPortrait and ButtonImage mapped-image fields, so the editor can load object "
        "templates written for a game.dat carrying object-image-upgrade; parser-only, with no "
        "editor-side image override runtime"
    )

    @staticmethod
    def _layout(base: int) -> dict[str, int]:
        cursor = base
        out: dict[str, int] = {"table": cursor}
        cursor += 3 * 16

        for name, raw in (
            ("block_name", BLOCK_NAME),
            ("select_name", FIELDS[0][0]),
            ("button_name", FIELDS[1][0]),
        ):
            out[name] = cursor
            cursor += len(raw) + 1

        cursor = (cursor + 3) & ~3
        out["code"] = cursor
        return out

    def _assemble(self, base: int) -> Asm:
        layout = self._layout(base)
        a = Asm(layout["code"])

        # Entered in place of TooltipUpgrade's addModule call. Its six original arguments remain
        # on our stack. Copy them for the stock call because addModule returns with `ret 0x18`,
        # then consume the originals ourselves after registering the second name.
        a.label("register")
        a.emit(0x55, b"\x8b\xec", 0x56, 0x57, b"\x8b\xf1")
        for disp in (0x1C, 0x18, 0x14, 0x10, 0x0C, 0x08):
            a.emit(b"\xff\x75", bytes([disp]))
        a.emit(b"\x8b\xce")
        a.call_absolute(WORLDBUILDER_OBJECT_IMAGE_UPGRADE_REGISTER)

        # A real AsciiString object must outlive addModule: the factory keys its map from the
        # string value during the call, and the stock initializer destroys every temporary after
        # registration. Use the same constructor/destructor thunks as that initializer.
        a.emit(b"\x83\xec\x04", b"\xc7\x04\x24\x00\x00\x00\x00", b"\x8b\xfc")
        a.emit(0x68, _u32(layout["block_name"]), b"\x8b\xcf")
        a.call_absolute(WORLDBUILDER_OBJECT_IMAGE_UPGRADE_ASCIISTRING_CTOR)

        a.emit(b"\x68", _u32(_WORLDBUILDER_INTERFACE_MASK), 0x57, b"\x6a\x00\x6a\x00", 0x68)
        a.label("moduledata_factory_imm")
        a.emit(bytes(4), 0x68, _u32(WORLDBUILDER_OBJECT_IMAGE_UPGRADE_RUNTIME_FACTORY_STOCK))
        a.emit(b"\x8b\xce")
        a.call_absolute(WORLDBUILDER_OBJECT_IMAGE_UPGRADE_REGISTER)

        a.emit(b"\x8b\xcf")
        a.call_absolute(WORLDBUILDER_OBJECT_IMAGE_UPGRADE_ASCIISTRING_DTOR)
        a.emit(b"\x83\xc4\x04", 0x5F, 0x5E, 0x5D, b"\xc2\x18\x00")

        # TooltipUpgrade is the confirmed Worldbuilder layout twin too: its ModuleData factory
        # allocates 0x140 and calls this constructor. Only the parse-table callback differs.
        a.label("moduledata_factory")
        a.emit(0x55, b"\x8b\xec", 0x56, b"\x68", _u32(_MODULEDATA_SIZE))
        a.call_absolute(WORLDBUILDER_OBJECT_IMAGE_UPGRADE_OPERATOR_NEW)
        a.emit(b"\x83\xc4\x04", b"\x8b\xf0", b"\x85\xf6")
        a.jcc(JE, "moduledata_factory_done")
        a.emit(b"\x8b\xce")
        a.call_absolute(WORLDBUILDER_OBJECT_IMAGE_UPGRADE_MODULEDATA_CTOR)
        a.emit(b"\x8b\x4d\x08", b"\x85\xc9")
        a.jcc(JE, "moduledata_factory_done")
        a.emit(0x68)
        a.label("build_fields_imm")
        a.emit(bytes(4), 0x56, b"\x8b\x4d\x08")
        a.call_absolute(WORLDBUILDER_OBJECT_IMAGE_UPGRADE_REGISTER_CLEANUP)
        a.label("moduledata_factory_done")
        a.emit(b"\x8b\xc6", 0x5E, 0x5D, 0xC3)

        # Mirror TooltipUpgrade's stock callback: inherited UpgradeModule fields first, then this
        # behavior's private two-row table. Keep the stock EBP frame: buildUpgradeFields returns
        # without popping the leading `8`; the first append consumes that value together with the
        # returned table pointer, so an ESP-relative load here would read the return address as
        # the parser context and crash as soon as the editor parsed the new block.
        a.label("build_fields")
        a.emit(0x55, b"\x8b\xec", b"\x6a\x08")
        a.call_absolute(WORLDBUILDER_OBJECT_IMAGE_UPGRADE_BUILD_UPGRADE_FIELDS)
        a.emit(0x50, b"\x8b\x4d\x08")
        a.call_absolute(WORLDBUILDER_OBJECT_IMAGE_UPGRADE_APPEND_FIELD_TABLE)
        a.emit(b"\x6a\x00", b"\x68", _u32(layout["table"]), b"\x8b\x4d\x08")
        a.call_absolute(WORLDBUILDER_OBJECT_IMAGE_UPGRADE_APPEND_FIELD_TABLE)
        a.emit(0x5D, 0xC3)

        a.finish()
        return a

    def _code_bytes(self, base: int) -> bytes:
        code = self._assemble(base)
        out = bytearray(code.finish())
        for immediate, target in (
            ("moduledata_factory_imm", code.label_va("moduledata_factory")),
            ("build_fields_imm", code.label_va("build_fields")),
        ):
            struct.pack_into("<I", out, code.label_va(immediate) - code.base_va, target)
        return bytes(out)

    def _build(self, base: int) -> bytes:
        layout = self._layout(base)
        table = bytearray()
        for index, (_name, offset) in enumerate(FIELDS):
            name_va = layout["select_name" if index == 0 else "button_name"]
            table += struct.pack(
                "<4I",
                name_va,
                WORLDBUILDER_OBJECT_IMAGE_UPGRADE_ASCIISTRING_PARSER,
                0,
                offset,
            )
        table += bytes(16)

        out = table
        out += BLOCK_NAME.encode() + b"\0"
        out += FIELDS[0][0].encode() + b"\0"
        out += FIELDS[1][0].encode() + b"\0"
        out += b"\0" * (-len(out) % 4)
        assert base + len(out) == layout["code"]
        out += self._code_bytes(base)
        return bytes(out)

    @staticmethod
    def _check_registration(data: bytes | bytearray) -> None:
        prefix_va = WORLDBUILDER_OBJECT_IMAGE_UPGRADE_REGISTER_CALL - len(
            _WORLDBUILDER_REGISTER_PREFIX
        )
        got_prefix = _at(data, prefix_va, len(_WORLDBUILDER_REGISTER_PREFIX))
        if got_prefix != _WORLDBUILDER_REGISTER_PREFIX:
            raise ValueError(
                "unexpected Worldbuilder build: TooltipUpgrade factory arguments do not match"
            )
        got_call = _at(
            data,
            WORLDBUILDER_OBJECT_IMAGE_UPGRADE_REGISTER_CALL,
            len(_WORLDBUILDER_REGISTER_BYTES),
        )
        if got_call != _WORLDBUILDER_REGISTER_BYTES:
            raise ValueError(
                "unexpected Worldbuilder build or overlapping patch at "
                f"{WORLDBUILDER_OBJECT_IMAGE_UPGRADE_REGISTER_CALL:#010x}"
            )

    def apply(self, data: bytearray) -> None:
        name_tables.check_not_rebased(data)
        self._check_registration(data)
        base = allocate_section(
            data,
            WORLDBUILDER_SECTION_NAME,
            self._build,
            _WORLDBUILDER_CHARACTERISTICS,
        )
        code = self._assemble(base)
        apply_byte_patch(
            data,
            va_to_offset(data, WORLDBUILDER_OBJECT_IMAGE_UPGRADE_REGISTER_CALL) or 0,
            _WORLDBUILDER_REGISTER_BYTES,
            _call(
                WORLDBUILDER_OBJECT_IMAGE_UPGRADE_REGISTER_CALL,
                code.label_va("register"),
            ),
            "register ObjectImageUpgrade in Worldbuilder",
        )

    def verify(self, data: bytes | bytearray) -> list[str]:
        located = find_section(data, WORLDBUILDER_SECTION_NAME)
        if located is None:
            return [f"no {WORLDBUILDER_SECTION_NAME} section: the file does not carry this patch"]
        base, section_off, _size = located
        code = self._assemble(base)
        expected = self._build(base)
        problems: list[str] = []
        if bytes(data[section_off : section_off + len(expected)]) != expected:
            problems.append(
                f"{WORLDBUILDER_SECTION_NAME} does not hold the expected field table and code"
            )
        want = _call(
            WORLDBUILDER_OBJECT_IMAGE_UPGRADE_REGISTER_CALL,
            code.label_va("register"),
        )
        if _at(data, WORLDBUILDER_OBJECT_IMAGE_UPGRADE_REGISTER_CALL, len(want)) != want:
            problems.append(
                "Worldbuilder TooltipUpgrade registration does not point into "
                f"{WORLDBUILDER_SECTION_NAME}"
            )
        return problems
