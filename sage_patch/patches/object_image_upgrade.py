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
``Object *`` and source module. UI resolution scans matching rows for a non-null image. Image names
are resolved once on every successful apply. The result is deliberately sticky: later upgrade loss
or a newly conflicting upgrade does not roll it back, while another successful apply can overwrite
it.

The sidecar contains presentation pointers only.  It is neither transferred nor CRC'd and uses
no clock, RNG or simulation mutation, so identical binaries/data cannot introduce a simulation
desync. The Apply/UI path, multiple behaviors, repeated triggers and the sticky semantics are
live-tested.
"""

from __future__ import annotations

import struct

from sage_ini.engine import BlockDelta, Engine, FieldDelta

from ..asm import JB, JE, JNE, Asm
from ..patcher import Patch
from ..utils import allocate_section, apply_byte_patch, find_section, va_to_offset

__all__ = ["ObjectImageUpgradePatch", "SECTION_NAME"]

SECTION_NAME = ".objimg"
BLOCK_NAME = "ObjectImageUpgrade"
FIELDS = (("SelectPortrait", 0x138), ("ButtonImage", 0x13C))

# TooltipUpgrade is the proven layout twin: ModuleData 0x140, runtime 0x1C, UpgradeMux at +0x10.
_REGISTER_CALL = 0x0065A7F2
_REGISTER = 0x006570FE
_REGISTER_BYTES = bytes.fromhex("e807c9ffff")
_RUNTIME_FACTORY_STOCK = 0x006504C2
_MODULEDATA_CTOR = 0x0065563C
_OPERATOR_NEW = 0x0042F6E0
_ASCII_SET_CSTR = 0x0040611E
_ASCII_DTOR = 0x00435D50
_REGISTER_CLEANUP = 0x0042DBBD
_BUILD_UPGRADE_FIELDS = 0x008D26E0
_APPEND_FIELD_TABLE = 0x0042B8D7

_UPGRADE_VTABLE = 0x00C6F820
_UPGRADE_VTABLE_SIZE = 0x48
_MODULEDATA_VTABLE = 0x00C09AD0
_MODULEDATA_VTABLE_SIZE = 0x80

_STOCK_FIELD_TABLE = 0x00C6F898
_PARSE_ASCII_STRING = 0x0042EE5E

_FIND_IMAGE = 0x006DA34C
_THE_IMAGES = 0x00DE4AC0
_THE_CONTROL_BAR = 0x00DE7744

_SELECT_HOOK = 0x00694F06
_SELECT_BYTES = bytes.fromhex("568bf1e8eafcffff")
_SELECT_RESUME = 0x00694F0E
_SELECT_DISPLACED_CALL = 0x00694BF8
_BUTTON_HOOK = 0x0073D0BA
_BUTTON_BYTES = bytes.fromhex("837c240400")
_BUTTON_RESUME = 0x0073D0BF
_ROWS = 2048
_ROW_SIZE = 16  # Object *, source, select Image *, button Image *
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
        "add ObjectImageUpgrade with TriggeredBy, SelectPortrait and ButtonImage fields for "
        "per-object presentation-only image changes"
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
        a.call_absolute(_REGISTER)
        a.emit(b"\x83\xec\x04", b"\x83\x24\x24\x00", b"\x8b\xcc")
        a.emit(b"\x68", _u32(layout["block_name"]))
        a.call_absolute(_ASCII_SET_CSTR)
        a.emit(b"\x68\x84\x00\x00\x00", 0x50, b"\x6a\x00\x6a\x00")
        a.emit(0x68)
        a.label("moduledata_factory_imm")
        a.emit(bytes(4), 0x68)
        a.label("runtime_factory_imm")
        a.emit(bytes(4), b"\x8b\xce")
        a.call_absolute(_REGISTER)
        a.emit(b"\x8b\xcc")
        a.call_absolute(_ASCII_DTOR)
        a.emit(b"\x83\xc4\x04", 0x5E, 0x5D, b"\xc2\x18\x00")

        a.label("runtime_factory")
        # Delegate allocation and construction to TooltipUpgrade's exact factory.  The callback
        # is cdecl (plain RET), while its thiscall constructor consumes its own two arguments.
        a.emit(0x55, b"\x8b\xec", 0x56, b"\xff\x75\x0c", b"\xff\x75\x08")
        a.call_absolute(_RUNTIME_FACTORY_STOCK)
        a.emit(b"\x83\xc4\x08", b"\x8b\xf0", b"\x85\xf6")
        a.jcc(JE, "runtime_factory_done")
        # Preserve the constructor-set primary/behavior/aux vtables. Only UpgradeMux differs.
        a.emit(b"\xc7\x46\x10", _u32(layout["upgrade"]))
        a.label("runtime_factory_done")
        a.emit(b"\x8b\xc6", 0x5E, 0x5D, 0xC3)

        a.label("moduledata_factory")
        a.emit(0x55, b"\x8b\xec", 0x56, b"\x68", _u32(_MODULEDATA_SIZE))
        a.call_absolute(_OPERATOR_NEW)
        a.emit(0x59, b"\x8b\xf0", b"\x85\xf6")
        a.jcc(JE, "moduledata_factory_done")

        a.emit(b"\x8b\xce")
        a.call_absolute(_MODULEDATA_CTOR)

        a.emit(b"\xc7\x06", _u32(layout["moduledata"]))

        a.emit(b"\x8b\x4d\x08", b"\x85\xc9")
        a.jcc(JE, "moduledata_factory_done")

        a.emit(0x68)
        a.label("build_fields_imm")
        a.emit(bytes(4), 0x56)
        a.call_absolute(_REGISTER_CLEANUP)

        a.label("moduledata_factory_done")
        a.emit(b"\x8b\xc6", 0x5E, 0x5D, 0xC3)

        a.label("build_fields")

        a.emit(b"\x6a\x08")
        a.call_absolute(_BUILD_UPGRADE_FIELDS)

        a.emit(b"\x8b\x4c\x24\x08", 0x50)
        a.call_absolute(_APPEND_FIELD_TABLE)

        a.emit(
            b"\x8b\x4c\x24\x04",
            b"\x6a\x00",
            b"\x68", _u32(layout["table"]),
        )
        a.call_absolute(_APPEND_FIELD_TABLE)

        a.emit(0xC3)

        a.label("apply")

        a.emit(
            0x53,                         # push ebx
            0x55,                         # push ebp
            0x56,                         # push esi
            0x57,                         # push edi

            b"\x8b\xf1",                  # mov esi,ecx       ; UpgradeMux*
            b"\x8b\x7e\xf8",              # mov edi,[esi-08]  ; Object*
            b"\x85\xff",                  # test edi,edi
        )
        a.jcc(JE, "apply_done")

        a.emit(
            b"\xbb", _u32(layout["sidecar"]),
            b"\x31\xc0",
        )
        a.label("apply_scan")
        a.emit(b"\x83\x3b\x00")         # cmp dword ptr [ebx],0
        a.jcc(JE, "apply_slot")
        a.emit(b"\x83\xc3", bytes([_ROW_SIZE]), 0x40, b"\x3d", _u32(_ROWS))
        a.jcc(JB, "apply_scan")
        a.jmp("apply_done")

        a.label("apply_slot")
        a.emit(
            b"\x8b\x6e\xf4",            # mov ebp,[esi-0C] ; ModuleData*
            b"\x89\x3b",                # mov [ebx],edi    ; Object*
            b"\x8d\x46\xf0",            # lea eax,[esi-10] ; source runtime
            b"\x89\x43\x04",            # source runtime

            b"\xc7\x43\x08\x00\x00\x00\x00",
            b"\xc7\x43\x0c\x00\x00\x00\x00",
        )

        # SelectPortrait
        a.emit(
            b"\x8b\x0d", _u32(_THE_IMAGES),
            b"\x85\xc9",
        )
        a.jcc(JE, "apply_button_image")

        a.emit(
            b"\x8d\x85\x38\x01\x00\x00",  # lea eax,[ebp+138]
            0x50,                          # push eax
        )
        a.call_absolute(_FIND_IMAGE)

        a.emit(
            b"\x89\x43\x08",               # row.selectPortrait = eax
        )

        # ButtonImage
        a.label("apply_button_image")
        a.emit(
            b"\x8b\x0d", _u32(_THE_IMAGES),
            b"\x85\xc9",
        )
        a.jcc(JE, "apply_dirty")

        a.emit(
            b"\x8d\x85\x3c\x01\x00\x00",  # lea eax,[ebp+13C]
            0x50,                          # push eax
        )
        a.call_absolute(_FIND_IMAGE)

        a.emit(
            b"\x89\x43\x0c",               # row.buttonImage = eax
        )

        a.label("apply_dirty")
        a.emit(
            b"\xa1", _u32(_THE_CONTROL_BAR),
            b"\x85\xc0",
        )
        a.jcc(JE, "apply_done")
        a.emit(b"\xc6\x40\x28\x01")

        a.label("apply_done")
        a.emit(0x5F, 0x5E, 0x5D, 0x5B, 0xC3)


        a.label("unapply")
        a.emit(0xC3)
        
        # Select portrait hook. ECX = Object*.
        # Sidecar row:
        #   +00 Object*, +04 source runtime*, +08 SelectPortrait Image*
        #   +0C ButtonImage Image*
        a.label("select_hook")
        a.emit(
            0x53,                         # push ebx
            0x55,                         # push ebp
            0x56,                         # push esi
            0x57,                         # push edi

            b"\x8b\xf9",                  # mov edi,ecx       ; Object*
            b"\x31\xed",                  # xor ebp,ebp       ; result = nullptr
            b"\xb9", _u32(layout["sidecar"]),
            b"\x31\xc0",                  # xor eax,eax       ; row index
        )

        a.label("select_scan")

        # row.object == current Object* ?
        a.emit(b"\x39\x39")              # cmp [ecx],edi
        a.jcc(JNE, "select_next")

        a.emit(
            b"\x8b\x59\x08",              # mov ebx,[ecx+08]  ; SelectPortrait Image*
            b"\x85\xdb",                  # test ebx,ebx
        )
        a.jcc(JE, "select_next")
        a.emit(b"\x8b\xeb")

        a.label("select_next")
        a.emit(
            b"\x83\xc1", bytes([_ROW_SIZE]),
            0x40,
            b"\x3d", _u32(_ROWS),
        )
        a.jcc(JB, "select_scan")

        a.emit(b"\x85\xed")
        a.jcc(JE, "select_fallback")

        a.emit(
            b"\x8b\xc5",                  # mov eax,ebp
            0x5F,                         # pop edi
            0x5E,                         # pop esi
            0x5D,                         # pop ebp
            0x5B,                         # pop ebx
            0xC3,
        )

        a.label("select_fallback")
        a.emit(
            b"\x8b\xcf",                  # mov ecx,edi ; restore Object*
            0x5F,
            0x5E,
            0x5D,
            0x5B,

            # displaced vanilla:
            0x56,                         # push esi
            b"\x8b\xf1",                  # mov esi,ecx
        )
        a.call_absolute(_SELECT_DISPLACED_CALL)
        a.jmp_absolute(_SELECT_RESUME)

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
            b"\x8b\x7c\x24\x18",         # mov edi,[esp+18] ; Object*
            b"\x85\xff",
        )
        a.jcc(JE, "button_fallback")

        a.emit(
            b"\x31\xed",                  # xor ebp,ebp
            b"\xb9", _u32(layout["sidecar"]),
            b"\x31\xc0",
        )

        a.label("button_scan")

        a.emit(b"\x39\x39")              # cmp [ecx],edi
        a.jcc(JNE, "button_next")

        a.emit(
            b"\x8b\x59\x0c",              # mov ebx,[ecx+0C]
            b"\x85\xdb",
        )
        a.jcc(JE, "button_next")
        a.emit(b"\x8b\xeb")

        a.label("button_next")
        a.emit(
            b"\x83\xc1", bytes([_ROW_SIZE]),
            0x40,
            b"\x3d", _u32(_ROWS),
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
            b"\x83\x7c\x24\x04\x00",     # displaced vanilla CMP
        )
        a.jmp_absolute(_BUTTON_RESUME)

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

        upgrade = bytearray(
            _at(data, _UPGRADE_VTABLE, _UPGRADE_VTABLE_SIZE)
        )

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

        for index, (name, offset) in enumerate(FIELDS):
            name_va = layout[
                "select_name" if index == 0 else "button_name"
            ]

            table += struct.pack(
                "<4I",
                name_va,
                _PARSE_ASCII_STRING,
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
            _MODULEDATA_VTABLE,
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
            (_REGISTER_CALL, _REGISTER_BYTES),
            (_SELECT_HOOK, _SELECT_BYTES),
            (_BUTTON_HOOK, _BUTTON_BYTES),
        ):
            if _at(data, va, len(expected)) != expected:
                raise ValueError(f"unexpected build or overlapping patch at {va:#010x}")
        base = allocate_section(
            data, SECTION_NAME, lambda va: self._build(data, va), _CHARACTERISTICS
        )
        code = self._assemble(base)

        edits = (
            (
                _REGISTER_CALL,
                _REGISTER_BYTES,
                _call(_REGISTER_CALL, code.label_va("register")),
                "register ObjectImageUpgrade",
            ),
            (
                _SELECT_HOOK,
                _SELECT_BYTES,
                _jmp(_SELECT_HOOK, code.label_va("select_hook")) + b"\x90" * 3,
                "instance select portrait",
            ),
            (
                _BUTTON_HOOK,
                _BUTTON_BYTES,
                _jmp(_BUTTON_HOOK, code.label_va("button_hook")),
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
            (_REGISTER_CALL, _call(_REGISTER_CALL, code.label_va("register"))),
            (_SELECT_HOOK, _jmp(_SELECT_HOOK, code.label_va("select_hook")) + b"\x90" * 3),
            (_BUTTON_HOOK, _jmp(_BUTTON_HOOK, code.label_va("button_hook"))),
        ):
            if _at(data, va, len(want)) != want:
                problems.append(f"hook at {va:#010x} does not point into {SECTION_NAME}")
        return problems

    def ini_surface(self) -> Engine:
        return Engine(
            blocks=(BlockDelta(BLOCK_NAME, base="Behavior", patch=self.name),),
            fields=tuple(
                FieldDelta(BLOCK_NAME, name, "AsciiString", patch=self.name)
                for name, _offset in FIELDS
            ),
        )
