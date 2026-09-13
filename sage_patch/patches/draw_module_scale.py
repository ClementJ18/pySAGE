"""The draw-module-scale patch: `Scale`, `Offset` and `AngleOffset` on a model draw module, so one
`Draw` block is drawn bigger, smaller, somewhere else or turned from the object it belongs to.

Targets the ROTWK SAGE-engine `game.dat` build ``2.01.2614.37001``. Every address is derived in
``../../docs/draw-module-scale.md``.

**What the engine does today.** An object's `Scale` is copied into its drawable once and read back
through one getter, `Drawable::getScale` (`DRAWABLE_GET_SCALE`). The model draw modules never scale
a transform with it: they hand it to the asset manager when a render object is created, which
builds a scaled copy of the model, and to the bone cache, which records bone positions at that
scale. And every draw module on an object is drawn at the object's own transform - there is no
per-module displacement or turn anywhere in the family. So one scale, one position and one facing
govern every model an object draws.

**What this does.** Adds three keywords - `Scale`, `Offset` and `AngleOffset` unless named
otherwise - to the field table every model draw module parses: `W3DScriptedModelDraw`,
`W3DHordeModelDraw`, `W3DQuadrupedDraw`, `W3DSupplyDraw`, `W3DTruckDraw`, `W3DTankDraw` and
`W3DSailModelDraw` all build their `ModuleData` on `W3DModelDrawModuleData` and read its table.

- `Scale = 1.5` builds *that module's* model at the object's scale times 1.5, bones included,
  because the factor goes in where the object's scale is read.
- `Offset = X:0 Y:0 Z:20` moves what that module draws, in the object's own frame - so it turns
  with the unit - by adding the rotated offset to the matrix the module hands its render object.
- `AngleOffset = 45` turns what that module draws about the object's up axis by that many degrees,
  which is how a model whose animation faces the wrong way is lined up. One value, positive one
  way and negative the other; the object itself does not turn.

A module that declares none of them is untouched, and the object's footprint, selection and other
draw modules never move, resize or turn either way. The three are independent: the offset is
measured in the object's frame whatever the angle says, so changing one does not move the other.

**Why they arrive by different routes.** A scale can be baked into a model at creation; a position
and a facing cannot, because nothing in the creation path takes either. So the scale is multiplied
in at the **19** `getScale` calls the family makes (`SITES`), and the offset and the turn are
applied at the **five** calls to `W3D_MODEL_DRAW_TRANSFORM_HELPER` (`TRANSFORM_SITES`) - the helper
every model draw runs on the matrix immediately before `Set_Transform`, which is therefore every
place the family positions what it draws. All 24 are five-byte ``call rel32`` sites retargeted,
five bytes for five, at stubs that do what the engine did and then apply the module's own numbers.
`getScale`'s three callers outside the family (`DRAWABLE_GET_SCALE_OTHER_CALLS`) keep the stock
call.

**Where the numbers live.** `W3DModelDrawModuleData` cannot grow - every derived module's fields
start at its ``sizeof`` - and has no free dword, only three bytes of padding between
`BirthFadeAdditive` (a one-byte `Bool` at ``+0x154``) and `StaticSortLevelWhileFading` at
``+0x158``. A scale, an offset and an angle do not fit in three bytes, so the padding holds a
**24-bit index** into a table of records in the cave, and the three keywords share one record:
whichever parses first allocates it, the others find it. Index zero means "declared none of them",
which is what the constructor leaves behind - its one-byte `BirthFadeAdditive` default is widened
to a dword store from the same zero register (``0x88`` -> ``0x89``), clearing the padding
`operator new` leaves as heap garbage, for all seven modules at once. A fresh record starts at
scale one, offset zero and no turn, so declaring one keyword does not disturb the others.

**The angle costs no trigonometry per frame.** `AngleOffset`'s parser turns the degrees into
radians and runs `fsincos` **once**, leaving the sine and the cosine in the record. The per-frame
stub spends four multiplies a row turning the matrix's first two columns, which is all a turn about
the up axis touches.

**The rows.** The shared table has one reference and is rebuilt in the cave from whatever that
reference names **now**, so a patch that extended it first keeps its rows. All three keywords are
refused if the shared table or any of the six derived modules' own tables - which the reader
searches too - already parses them. `Scale` is read by the engine's own
`INI::parsePositiveNonZeroReal`, so ``Scale = 0`` or a negative value is the engine's own INI
error; `Offset` by `INI::parseCoord3D`; and `AngleOffset` by the plain `INI::parseReal`, because a
negative angle turns the other way and zero is a legitimate "no turn".

**Determinism.** Unestablished for `Scale`: in the Generals lineage the bone cache it scales is
where weapon launch offsets are read from, and if RotWK does the same then a scaled module's
projectiles leave from a scaled bone, exactly as under the object's `Scale`. `Offset` and
`AngleOffset` are applied to a client-side transform only and the bone cache never sees them. Treat
the three as simulation state anyway - every peer runs the same binary. The keywords are an INI
parse error on a stock build either way, and `ModuleData` is never `Xfer`'d, so savegames are
unaffected.

**Composition.** Order-independent: the cave is allocated past every existing section and
:meth:`DrawModuleScalePatch.verify` finds it by name. No other bundled patch touches the model draw
field table, its constructor, `Drawable::getScale`, the transform helper or any of their callers.
"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sage_ini.engine import Engine, FieldDelta

from ..addresses import (
    DRAWABLE_GET_SCALE,
    DRAWABLE_GET_SCALE_BYTES,
    INI_PARSE_BOOL,
    INI_PARSE_COORD3D,
    INI_PARSE_COORD3D_BYTES,
    INI_PARSE_POSITIVE_REAL,
    INI_PARSE_POSITIVE_REAL_BYTES,
    INI_PARSE_REAL,
    INI_PARSE_REAL_BYTES,
    MATRIX3D_ROW_STRIDE,
    MATRIX3D_TRANSLATION,
    W3D_HORDE_MODEL_DRAW_SET_MODEL_STATE_SCALE_CALLS,
    W3D_HORDE_MODEL_DRAW_SET_MODEL_STATE_THIS,
    W3D_MODEL_DRAW_BIRTH_FADE_ADDITIVE,
    W3D_MODEL_DRAW_BIRTH_FADE_DEFAULT,
    W3D_MODEL_DRAW_BIRTH_FADE_DEFAULT_BYTES,
    W3D_MODEL_DRAW_BONE_UPDATE_SCALE_CALL,
    W3D_MODEL_DRAW_BONE_UPDATE_THIS,
    W3D_MODEL_DRAW_DERIVED_TABLE_REFS,
    W3D_MODEL_DRAW_FIELD_TABLE_REF,
    W3D_MODEL_DRAW_IFACE_SLOT3_SCALE_CALL,
    W3D_MODEL_DRAW_IFACE_SLOT3_THIS,
    W3D_MODEL_DRAW_IFACE_SLOT6_MODULE_DATA,
    W3D_MODEL_DRAW_IFACE_SLOT6_SCALE_CALL,
    W3D_MODEL_DRAW_SET_MODEL_STATE_SCALE_CALLS,
    W3D_MODEL_DRAW_SET_MODEL_STATE_THIS,
    W3D_MODEL_DRAW_STATIC_SORT_LEVEL,
    W3D_MODEL_DRAW_TRANSFORM_CALLS,
    W3D_MODEL_DRAW_TRANSFORM_HELPER,
    W3D_MODEL_DRAW_TRANSFORM_HELPER_BYTES,
)
from ..asm import JAE, JE, JNE, Asm
from ..patcher import Patch
from ..utils import allocate_section, apply_byte_patch, find_section, va_to_offset
from .utils.field_tables import ROW_SIZE, Entry, entries_before, read_field_table, resolve_table
from .utils.name_tables import read_cstring

if TYPE_CHECKING:
    import argparse

__all__ = [
    "ANCHORS",
    "CONTEXT_ANCHORS",
    "DEFAULT_ANGLE_KEYWORD",
    "DEFAULT_KEYWORD",
    "DEFAULT_OFFSET_KEYWORD",
    "FAMILY_BLOCKS",
    "FIELD_OFFSET",
    "FIELD_WIDTH",
    "LOCATORS",
    "RECORD_ANGLE_FLAG",
    "RECORD_CAPACITY",
    "RECORD_COS",
    "RECORD_OFFSET",
    "RECORD_SCALE",
    "RECORD_SHIFT",
    "RECORD_SIN",
    "RECORD_SIZE",
    "ROUTINES",
    "SECTION_NAME",
    "SITES",
    "TRANSFORM_SITES",
    "DrawModuleScalePatch",
    "build_code",
    "build_table",
    "entry_points",
    "validate_keywords",
    "widened_default",
]

SECTION_NAME = ".drwscl"  # 7 chars: the PE name field is 8 bytes and truncates silently

# CNT_CODE | CNT_INITIALIZED_DATA | MEM_EXECUTE | MEM_READ | MEM_WRITE. The cave holds the keywords,
# the rebuilt table and the routines, and the records and their counter are written while the INI
# is read.
_CHARACTERISTICS = 0x20 | 0x40 | 0x20000000 | 0x40000000 | 0x80000000

#: The keywords the fields are installed under unless the caller names others.
DEFAULT_KEYWORD = "Scale"
DEFAULT_OFFSET_KEYWORD = "Offset"
DEFAULT_ANGLE_KEYWORD = "AngleOffset"

#: Where the record index is stored and how many bytes it has: the padding behind
#: `BirthFadeAdditive`.
FIELD_OFFSET = W3D_MODEL_DRAW_BIRTH_FADE_ADDITIVE + 1
FIELD_WIDTH = W3D_MODEL_DRAW_STATIC_SORT_LEVEL - FIELD_OFFSET

#: One record: the module's scale, its offset, whether it declared a turn, and that turn as the
#: sine and cosine `fsincos` produced while the INI was read. Indices are one-based, because zero
#: in the padding is what "this module declared nothing" looks like.
RECORD_SCALE = 0x00
RECORD_OFFSET = 0x04
RECORD_ANGLE_FLAG = 0x10
RECORD_COS = 0x14
RECORD_SIN = 0x18
RECORD_SIZE = 0x20
#: ``log2(RECORD_SIZE)``: an index becomes an address with a shift, which needs the size to be a
#: power of two - the x86 `lea` scale factors stop at eight.
RECORD_SHIFT = 5
#: How many modules may declare a keyword. The index has room for sixteen million; this is what the
#: cave pays for in the file, and it is two orders of magnitude past what a mod declares.
RECORD_CAPACITY = 1024

#: The `sage_ini` blocks the keywords are declared on. `W3DHordeModelDraw` inherits them from
#: `W3DScriptedModelDraw` there as it inherits the table here.
FAMILY_BLOCKS = (
    "W3DScriptedModelDraw",
    "W3DQuadrupedDraw",
    "W3DSupplyDraw",
    "W3DTruckDraw",
    "W3DTankDraw",
    "W3DSailModelDraw",
)

#: How each scale stub loads the calling module's `ModuleData` into ``eax``, keyed by the register
#: the calling function keeps it behind.
LOCATORS: dict[str, bytes] = {
    "esi": bytes.fromhex("8b4604"),  # mov eax, [esi+4]   ; esi is the module
    "edi": bytes.fromhex("8bc7"),  # mov eax, edi        ; edi is already the ModuleData
    "edi_iface": bytes.fromhex("8b47f8"),  # mov eax, [edi-8]  ; edi is the +0xC sub-object
    "ebx": bytes.fromhex("8b4304"),  # mov eax, [ebx+4]   ; ebx is the module
}

#: Every `getScale` call in the model draw family, and the locator its function needs.
SITES: dict[int, str] = {
    **dict.fromkeys(W3D_MODEL_DRAW_SET_MODEL_STATE_SCALE_CALLS, "esi"),
    **dict.fromkeys(W3D_HORDE_MODEL_DRAW_SET_MODEL_STATE_SCALE_CALLS, "esi"),
    W3D_MODEL_DRAW_IFACE_SLOT6_SCALE_CALL: "edi",
    W3D_MODEL_DRAW_IFACE_SLOT3_SCALE_CALL: "edi_iface",
    W3D_MODEL_DRAW_BONE_UPDATE_SCALE_CALL: "ebx",
}

#: Every call to the transform helper: one stub for all five, because each is reached with the
#: module in ``ecx`` and the matrix already pushed.
TRANSFORM_SITES = W3D_MODEL_DRAW_TRANSFORM_CALLS

#: What the patch relies on and never rewrites: the getter and the helper the stubs reproduce, the
#: three parsers the new rows wrap, and the instructions that put each locator's register in place.
#: A build where one of the last differs is a build where a stub would read the wrong structure.
CONTEXT_ANCHORS: dict[int, bytes] = {
    DRAWABLE_GET_SCALE: DRAWABLE_GET_SCALE_BYTES,
    W3D_MODEL_DRAW_TRANSFORM_HELPER: W3D_MODEL_DRAW_TRANSFORM_HELPER_BYTES,
    INI_PARSE_POSITIVE_REAL: INI_PARSE_POSITIVE_REAL_BYTES,
    INI_PARSE_COORD3D: INI_PARSE_COORD3D_BYTES,
    INI_PARSE_REAL: INI_PARSE_REAL_BYTES,
    W3D_MODEL_DRAW_SET_MODEL_STATE_THIS: bytes.fromhex("8bf1"),  # mov esi, ecx
    W3D_HORDE_MODEL_DRAW_SET_MODEL_STATE_THIS: bytes.fromhex("8bf1"),  # mov esi, ecx
    W3D_MODEL_DRAW_IFACE_SLOT6_MODULE_DATA: bytes.fromhex("8b7ef8"),  # mov edi, [esi-8]
    W3D_MODEL_DRAW_IFACE_SLOT3_THIS: bytes.fromhex("8bf9"),  # mov edi, ecx
    W3D_MODEL_DRAW_BONE_UPDATE_THIS: bytes.fromhex("8bd9"),  # mov ebx, ecx
}


def _call(site: int, target: int) -> bytes:
    """``call rel32`` from ``site`` to ``target``."""
    return b"\xe8" + struct.pack("<i", target - (site + 5))


def _u32(value: int) -> bytes:
    """A 32-bit immediate. Masked rather than range-checked, because the layout measures the code's
    length with placeholder addresses before it knows the real ones, and an immediate that comes
    out negative there is still four bytes wide."""
    return struct.pack("<I", value & 0xFFFFFFFF)


#: Every site the patch asserts before it writes anything, as ``VA -> stock bytes``.
ANCHORS: dict[int, bytes] = {
    **CONTEXT_ANCHORS,
    W3D_MODEL_DRAW_BIRTH_FADE_DEFAULT: W3D_MODEL_DRAW_BIRTH_FADE_DEFAULT_BYTES,
    **{site: _call(site, DRAWABLE_GET_SCALE) for site in SITES},
    **{site: _call(site, W3D_MODEL_DRAW_TRANSFORM_HELPER) for site in TRANSFORM_SITES},
}

#: The routines the cave holds, in the order it lays them out.
ROUTINES = ("record", "parse_scale", "parse_offset", "parse_angle", "transform", *LOCATORS)

# The stubs read the record index as the top three bytes of the dword at `BirthFadeAdditive`,
# which only works if the index starts on the very next byte and fills the rest of that dword.
assert FIELD_OFFSET - W3D_MODEL_DRAW_BIRTH_FADE_ADDITIVE == 1 and FIELD_WIDTH == 3
assert RECORD_SIZE == 1 << RECORD_SHIFT

# An INI keyword is matched by case-insensitive compare, so anything the parser could never match
# is a typo rather than a choice. The engine's own field names are CamelCase with digits.
_KEYWORD_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,62}$")


def validate_keywords(keyword: str, offset_keyword: str, angle_keyword: str) -> None:
    """Raise unless all three names are tokens the engine's INI reader could match, and they
    differ.

    A duplicate would parse - the reader takes the first match - so one field would exist and
    another would silently never be written."""
    names = (keyword, offset_keyword, angle_keyword)
    for name in names:
        if not _KEYWORD_PATTERN.match(name):
            raise ValueError(
                "an INI keyword must be letters, digits and underscores starting with a letter "
                f"(the reader matches it by name), got {name!r}"
            )
    folded = [name.lower() for name in names]
    if len(set(folded)) != len(folded):
        raise ValueError(f"the three keywords must differ, got {names!r}")


def widened_default() -> bytes:
    """The constructor's ``mov byte [esi+0x154], bl`` as a dword store from ``ebx``.

    Six bytes for six, one of them changed. ``ebx`` is zero for the whole constructor, so the store
    clears `BirthFadeAdditive` exactly as before and the record index behind it as well."""
    return bytes((0x89,)) + W3D_MODEL_DRAW_BIRTH_FADE_DEFAULT_BYTES[1:]


@dataclass(frozen=True)
class _Layout:
    """Where each piece of the cave sits, given its base address, the keywords and how many rows
    the table held before this patch's three.

    Pure arithmetic, so :meth:`DrawModuleScalePatch.apply` and :meth:`DrawModuleScalePatch.verify`
    compute the same addresses from opposite directions. The keywords come first, in declaration
    order, so :meth:`DrawModuleScalePatch.detect` reads them off the section base without knowing
    how long anything after them is."""

    keyword_va: int
    offset_keyword_va: int
    angle_keyword_va: int
    table_va: int
    code_va: int
    count_va: int
    records_va: int

    @property
    def size(self) -> int:
        return self.records_va + RECORD_SIZE * RECORD_CAPACITY - self.keyword_va


def _layout(base_va: int, keywords: tuple[str, str, str], row_count: int) -> _Layout:
    keyword, offset_keyword, _angle_keyword = keywords
    offset_keyword_va = base_va + len(keyword) + 1
    angle_keyword_va = offset_keyword_va + len(offset_keyword) + 1
    strings = sum(len(name) + 1 for name in keywords)
    table_va = base_va + strings + (-strings % 4)  # keep the table's dwords aligned
    code_va = table_va + (row_count + 4) * ROW_SIZE  # + this patch's three rows + the terminator
    # The code's length does not depend on the addresses it embeds, so measuring it with
    # placeholders is exact - and is the only way to place what comes after it.
    after_code = code_va + len(build_code(code_va, 0, 0))
    count_va = after_code + (-after_code % 4)
    return _Layout(
        base_va,
        offset_keyword_va,
        angle_keyword_va,
        table_va,
        code_va,
        count_va,
        count_va + 4,
    )


def build_table(
    rows: tuple[Entry, ...],
    keyword_vas: tuple[int, int, int],
    parse_vas: tuple[int, int, int],
) -> bytes:
    """The rebuilt field-parse table: the live rows verbatim, the three new ones, the terminator.

    The rows are copied rather than rewritten because every pointer in them is absolute - their
    keyword strings stay where they are and only the new rows point into the cave. All three new
    rows name the same `ModuleData` offset: what they write there is the record index, and which of
    them writes it is whichever the reader meets first."""
    blob = b"".join(struct.pack("<IIII", *row) for row in rows)
    for keyword_va, parse_va in zip(keyword_vas, parse_vas, strict=True):
        blob += struct.pack("<IIII", keyword_va, parse_va, 0, FIELD_OFFSET)
    return blob + bytes(ROW_SIZE)


def _emit_record_lookup(a: Asm, records_va: int) -> None:
    """``eax`` holds an index; leave it holding that record's address."""
    a.emit(b"\xc1\xe0", RECORD_SHIFT)  # shl eax, 5
    a.emit(0x05, _u32(records_va - RECORD_SIZE))  # add eax, <records - one record>


def _emit_parse_head(a: Asm, slot: int, parser: int) -> None:
    """The head every row parser shares: a stack slot for the value, the engine's own parser
    called on it, and the row's store pushed for the record lookup behind it.

    Each ``push [esp+N]`` names the next of the caller's arguments once the slot and the pushes
    before it are counted, which is what makes one offset serve all three."""
    outer = slot + 0x10
    a.emit(b"\x83\xec", slot)  # sub  esp, <the slot>
    a.emit(b"\x8b\xc4")  # mov  eax, esp
    a.emit(b"\xff\x74\x24", outer)  # push [esp+N]           ; userData
    a.emit(0x50)  # push eax               ; store: the slot
    a.emit(b"\xff\x74\x24", outer)  # push [esp+N]           ; instance
    a.emit(b"\xff\x74\x24", outer)  # push [esp+N]           ; the INI
    a.call_absolute(parser)
    a.emit(b"\x83\xc4\x10")  # add  esp, 0x10         ; cdecl
    a.emit(b"\xff\x74\x24", slot + 0xC)  # push [esp+N]           ; the row's store


def _emit_offset_row(a: Asm, row: int) -> None:
    """One row of ``translation += rotation . offset``, with ``esi`` the matrix and ``eax`` the
    record. The offset is read in the object's own frame, which is what makes it turn with the unit
    instead of pointing north - and what keeps it independent of the module's own turn."""
    base = row * MATRIX3D_ROW_STRIDE
    translation = base + MATRIX3D_TRANSLATION
    a.emit(b"\xd9\x40", RECORD_OFFSET)  # fld   dword [eax+4]     ; X
    a.emit(b"\xd8\x4e", base)  # fmul  dword [esi+row]
    a.emit(b"\xd9\x40", RECORD_OFFSET + 4)  # fld   dword [eax+8]     ; Y
    a.emit(b"\xd8\x4e", base + 4)  # fmul  dword [esi+row+4]
    a.emit(b"\xde\xc1")  # faddp st(1), st
    a.emit(b"\xd9\x40", RECORD_OFFSET + 8)  # fld   dword [eax+0xc]   ; Z
    a.emit(b"\xd8\x4e", base + 8)  # fmul  dword [esi+row+8]
    a.emit(b"\xde\xc1")  # faddp st(1), st
    a.emit(b"\xd8\x46", translation)  # fadd  dword [esi+row+0xc]
    a.emit(b"\xd9\x5e", translation)  # fstp  dword [esi+row+0xc]


def _emit_turn_row(a: Asm, row: int) -> None:
    """One row of the turn about the up axis: the row's first two entries become
    ``(x*cos + y*sin, y*cos - x*sin)`` and its third is left alone, which is the whole of what
    multiplying a matrix by a rotation about Z does.

    ``esi`` is the matrix, ``eax`` the record and ``[esp]``/``[esp+4]`` two scratch dwords the stub
    reserved - the row is copied there first because both answers read both of its originals."""
    base = row * MATRIX3D_ROW_STRIDE
    a.emit(b"\xd9\x46", base)  # fld   dword [esi+row]
    a.emit(b"\xd9\x1c\x24")  # fstp  dword [esp]        ; x
    a.emit(b"\xd9\x46", base + 4)  # fld   dword [esi+row+4]
    a.emit(b"\xd9\x5c\x24\x04")  # fstp  dword [esp+4]      ; y
    a.emit(b"\xd9\x04\x24")  # fld   dword [esp]
    a.emit(b"\xd8\x48", RECORD_COS)  # fmul  dword [eax+0x14]   ; x*cos
    a.emit(b"\xd9\x44\x24\x04")  # fld   dword [esp+4]
    a.emit(b"\xd8\x48", RECORD_SIN)  # fmul  dword [eax+0x18]   ; y*sin
    a.emit(b"\xde\xc1")  # faddp st(1), st
    a.emit(b"\xd9\x5e", base)  # fstp  dword [esi+row]
    a.emit(b"\xd9\x44\x24\x04")  # fld   dword [esp+4]
    a.emit(b"\xd8\x48", RECORD_COS)  # fmul  dword [eax+0x14]   ; y*cos
    a.emit(b"\xd9\x04\x24")  # fld   dword [esp]
    a.emit(b"\xd8\x48", RECORD_SIN)  # fmul  dword [eax+0x18]   ; x*sin
    a.emit(b"\xde\xe9")  # fsubp st(1), st          ; y*cos - x*sin
    a.emit(b"\xd9\x5e", base + 4)  # fstp  dword [esi+row+4]


def _assemble(base_va: int, count_va: int, records_va: int) -> Asm:
    """Every routine, laid out in one buffer so their addresses come from the layout itself."""
    a = Asm(base_va)

    # The record a `ModuleData` owns, allocated on first use. `__stdcall`-shaped: the argument is
    # the row's store - the index bytes themselves - and the answer is the record's address, or
    # zero when the table is full, which leaves the module stock.
    a.label("record")
    a.emit(b"\x8b\x54\x24\x04")  # mov  edx, [esp+4]      ; &the index
    a.emit(b"\x8b\x42\xff")  # mov  eax, [edx-1]      ; the dword at BirthFadeAdditive
    a.emit(b"\xc1\xe8\x08")  # shr  eax, 8
    a.jcc_short(JNE, "known")  # already has one
    a.emit(0xA1, _u32(count_va))  # mov  eax, [count]
    a.emit(0x3D, _u32(RECORD_CAPACITY))  # cmp  eax, <capacity>
    a.jcc_short(JAE, "full")
    a.emit(0x40)  # inc  eax               ; index 0 means "declared nothing"
    a.emit(0xA3, _u32(count_va))  # mov  [count], eax
    a.emit(b"\x66\x89\x02")  # mov  [edx], ax
    a.emit(b"\x8b\xc8")  # mov  ecx, eax
    a.emit(b"\xc1\xe9\x10")  # shr  ecx, 16
    a.emit(b"\x88\x4a\x02")  # mov  [edx+2], cl       ; three bytes, never the Bool before them
    _emit_record_lookup(a, records_va)
    # The section is zero-filled, so the offset starts at nothing and the turn's flag clear; the
    # scale has to be told that nothing means one, or declaring another keyword alone would
    # collapse the model.
    a.emit(b"\xc7\x00", _u32(0x3F800000))  # mov  dword [eax], 1.0f
    a.emit(b"\xc2\x04\x00")  # ret  4
    a.label("known")
    _emit_record_lookup(a, records_va)
    a.emit(b"\xc2\x04\x00")  # ret  4
    a.label("full")
    a.emit(b"\x33\xc0")  # xor  eax, eax
    a.emit(b"\xc2\x04\x00")  # ret  4

    # The scale row's parser, cdecl (INI *, instance, store, userData) with store = the index
    # bytes. The engine's positive-real parser reads the token and raises the INI error into a
    # stack slot, and only a value it accepted reaches the record.
    a.label("parse_scale")
    _emit_parse_head(a, 0x4, INI_PARSE_POSITIVE_REAL)  # throws unless the value is above zero
    a.call("record")
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc_short(JE, "scale_done")  # no record to be had -> the module stays stock
    a.emit(b"\x8b\x14\x24")  # mov  edx, [esp]
    a.emit(b"\x89\x50", RECORD_SCALE)  # mov  [eax+0], edx
    a.label("scale_done")
    a.emit(b"\x83\xc4\x04")  # add  esp, 4
    a.emit(0xC3)  # ret

    # The offset row's parser, the same shape around `INI::parseCoord3D` and its three floats.
    a.label("parse_offset")
    _emit_parse_head(a, 0xC, INI_PARSE_COORD3D)
    a.call("record")
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc_short(JE, "offset_done")
    for element in range(3):
        a.emit(b"\x8b\x54\x24", element * 4)  # mov edx, [esp+n]
        a.emit(b"\x89\x50", RECORD_OFFSET + element * 4)  # mov [eax+4+n], edx
    a.label("offset_done")
    a.emit(b"\x83\xc4\x0c")  # add  esp, 0xc
    a.emit(0xC3)  # ret

    # The angle row's parser: degrees in, a sine and a cosine out, computed here so that drawing
    # costs neither. The plain real parser, not the positive one - a negative angle turns the other
    # way and zero is a legitimate "no turn".
    a.label("parse_angle")
    _emit_parse_head(a, 0x4, INI_PARSE_REAL)
    a.call("record")
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc_short(JE, "angle_done")  # no record to be had -> the module stays stock
    a.emit(b"\xd9\x04\x24")  # fld   dword [esp]      ; the angle, in degrees
    a.emit(b"\xd9\xeb")  # fldpi
    a.emit(b"\xde\xc9")  # fmulp st(1), st
    a.emit(0x68, _u32(180))  # push  180
    a.emit(b"\xda\x34\x24")  # fidiv dword [esp]      ; ... and now in radians
    a.emit(0x59)  # pop   ecx
    a.emit(b"\xd9\xfb")  # fsincos                ; st0 = cos, st1 = sin
    a.emit(b"\xd9\x58", RECORD_COS)  # fstp  dword [eax+0x14]
    a.emit(b"\xd9\x58", RECORD_SIN)  # fstp  dword [eax+0x18]
    a.emit(b"\xc7\x40", RECORD_ANGLE_FLAG, _u32(1))  # mov dword [eax+0x10], 1
    a.label("angle_done")
    a.emit(b"\x83\xc4\x04")  # add  esp, 4
    a.emit(0xC3)  # ret

    # The transform stub, in place of the five `call`s to the helper. It runs the helper exactly as
    # the call site did - same `this`, same argument, and the callee still pops it - and then moves
    # and turns the matrix the helper settled. `esi` and `edi` are callee-saved, which is what lets
    # it keep the matrix and the module across that call; `eax`, `ecx` and `edx` are the helper's to
    # clobber either way, and no call site reads the flags afterwards.
    a.label("transform")
    a.emit(0x56)  # push esi
    a.emit(0x57)  # push edi
    a.emit(b"\x8b\x74\x24\x0c")  # mov  esi, [esp+0xc]    ; the matrix the caller pushed
    a.emit(b"\x8b\xf9")  # mov  edi, ecx          ; the module
    a.emit(0x56)  # push esi               ; the helper's own argument
    a.call_absolute(W3D_MODEL_DRAW_TRANSFORM_HELPER)  # ret 4: it pops that
    a.emit(b"\x8b\x47\x04")  # mov  eax, [edi+4]      ; the ModuleData
    a.emit(b"\x8b\x80", _u32(W3D_MODEL_DRAW_BIRTH_FADE_ADDITIVE))  # mov eax, [eax+0x154]
    a.emit(b"\xc1\xe8\x08")  # shr  eax, 8            ; the record index
    # Near, not short: the offset and the turn between here and the label are well past a rel8.
    a.jcc(JE, "transform_done")  # nothing declared -> the matrix as the engine left it
    _emit_record_lookup(a, records_va)
    for row in range(3):
        _emit_offset_row(a, row)
    # The turn goes on after the offset, so the offset stays in the object's frame rather than the
    # module's - two knobs that do not move each other.
    a.emit(b"\x83\x78", RECORD_ANGLE_FLAG, 0x00)  # cmp dword [eax+0x10], 0
    a.jcc(JE, "transform_done")  # near: three turn rows do not fit in a rel8 either
    a.emit(b"\x83\xec\x08")  # sub  esp, 8            ; the row, as it was
    for row in range(3):
        _emit_turn_row(a, row)
    a.emit(b"\x83\xc4\x08")  # add  esp, 8
    a.label("transform_done")
    a.emit(0x5F)  # pop  edi
    a.emit(0x5E)  # pop  esi
    a.emit(b"\xc2\x04\x00")  # ret  4                 ; as the helper does

    # The scale stubs, one per locator. Each is `Drawable::getScale` byte for byte, then the
    # module's factor if it declared one. `eax` is saved because the getter never touched it, and
    # `ecx` and `edx` are left alone for the same reason.
    for name, load in LOCATORS.items():
        a.label(name)
        a.emit(DRAWABLE_GET_SCALE_BYTES[:-1])  # fld  dword [ecx+0x200]  ; getScale
        a.emit(0x50)  # push eax
        a.emit(load)  # mov  eax, <the ModuleData>
        a.emit(b"\x8b\x80", _u32(W3D_MODEL_DRAW_BIRTH_FADE_ADDITIVE))  # mov eax, [eax+0x154]
        a.emit(b"\xc1\xe8\x08")  # shr  eax, 8            ; the record index
        a.jcc_short(JE, f"{name}_unset")  # nothing declared -> the object's scale alone
        a.emit(b"\xc1\xe0", RECORD_SHIFT)  # shl  eax, 5
        a.emit(b"\xd8\x88", _u32(records_va - RECORD_SIZE + RECORD_SCALE))  # fmul dword [eax+..]
        a.label(f"{name}_unset")
        a.emit(0x58)  # pop  eax
        a.emit(0xC3)  # ret
    return a


def build_code(base_va: int, count_va: int, records_va: int) -> bytes:
    """The cave's code, laid out at ``base_va`` and reaching the counter and records given."""
    return _assemble(base_va, count_va, records_va).finish()


def entry_points(base_va: int, count_va: int, records_va: int) -> dict[str, int]:
    """Where each routine starts, given the address the code is laid out at."""
    code = _assemble(base_va, count_va, records_va)
    code.finish()
    return {name: code.label_va(name) for name in ROUTINES}


def _offset(data: bytes | bytearray, va: int) -> int:
    off = va_to_offset(data, va)
    if off is None:
        raise ValueError(f"VA 0x{va:08x} is not mapped - not the expected build")
    return off


def _push(table_va: int) -> bytes:
    return b"\x68" + _u32(table_va)


def _live_table(data: bytes | bytearray, ref_va: int) -> int:
    return resolve_table(data, (ref_va,), (0x68,), "model draw")


def _read_keywords(data: bytes | bytearray, base_va: int) -> tuple[str, str, str] | None:
    """The three keyword strings the cave starts with, or None if they are not all there."""
    keywords: list[str] = []
    va = base_va
    for _ in range(3):
        name = read_cstring(data, va)
        if name is None:
            return None
        keywords.append(name)
        va += len(name) + 1
    return (keywords[0], keywords[1], keywords[2])


class DrawModuleScalePatch(Patch):
    """Add `Scale`, `Offset` and `AngleOffset` to the model draw modules, sizing, placing and
    turning one module's model without touching the object."""

    name = "draw-module-scale"
    author = "officialNecro"
    description = (
        "Add Scale, Offset and AngleOffset to W3DScriptedModelDraw and every model draw built on "
        "it (Horde, Quadruped, Supply, Truck, Tank, Sail). Scale = <factor> builds that Draw "
        "block's model at the object's Scale times the factor, bones included; Offset = X:<x> "
        "Y:<y> Z:<z> moves what the module draws, in the object's own frame; AngleOffset = "
        "<degrees> turns it about the object's up axis, which lines up a model whose animation "
        "faces the wrong way. Any of them absent is stock, and the object's footprint, selection "
        "and other draw modules never change; a mod that writes them will not load on an unpatched "
        "binary, since an unknown field is an INI parse error"
    )

    def __init__(
        self,
        keyword: str = DEFAULT_KEYWORD,
        offset_keyword: str = DEFAULT_OFFSET_KEYWORD,
        angle_keyword: str = DEFAULT_ANGLE_KEYWORD,
    ):
        self.keyword = keyword
        self.offset_keyword = offset_keyword
        self.angle_keyword = angle_keyword
        validate_keywords(keyword, offset_keyword, angle_keyword)

    def __str__(self) -> str:
        return f"{self.name} ({', '.join(self._keywords)})"

    @property
    def _keywords(self) -> tuple[str, str, str]:
        return (self.keyword, self.offset_keyword, self.angle_keyword)

    def apply(self, data: bytearray) -> None:
        self._check_anchors(data)
        table_va = _live_table(data, W3D_MODEL_DRAW_FIELD_TABLE_REF)
        rows = read_field_table(data, table_va)
        self._check_table(data, rows)
        self._check_keywords_free(data, rows)

        base_va = allocate_section(
            data, SECTION_NAME, lambda va: self._build(va, rows), _CHARACTERISTICS
        )
        pieces = self._pieces(base_va, len(rows))
        routines = self._routines(pieces)

        edits = [
            (
                W3D_MODEL_DRAW_FIELD_TABLE_REF,
                _push(table_va),
                _push(pieces.table_va),
                f"buildFieldParse -> the {SECTION_NAME} field table",
            ),
            (
                W3D_MODEL_DRAW_BIRTH_FADE_DEFAULT,
                W3D_MODEL_DRAW_BIRTH_FADE_DEFAULT_BYTES,
                widened_default(),
                "the ModuleData ctor -> a module declares no keyword by default",
            ),
        ]
        edits += [
            (site, ANCHORS[site], _call(site, routines[locator]), f"getScale -> the {locator} stub")
            for site, locator in SITES.items()
        ]
        edits += [
            (
                site,
                ANCHORS[site],
                _call(site, routines["transform"]),
                f"the transform helper -> the {self.offset_keyword}/{self.angle_keyword} stub",
            )
            for site in TRANSFORM_SITES
        ]
        for va, old, new, note in edits:
            apply_byte_patch(data, _offset(data, va), old, new, note)

    def _pieces(self, base_va: int, row_count: int) -> _Layout:
        return _layout(base_va, self._keywords, row_count)

    @staticmethod
    def _routines(pieces: _Layout) -> dict[str, int]:
        return entry_points(pieces.code_va, pieces.count_va, pieces.records_va)

    def _build(self, base_va: int, rows: tuple[Entry, ...]) -> bytes:
        """The cave: the keywords, the rebuilt table, the routines, the counter and the records."""
        pieces = self._pieces(base_va, len(rows))
        routines = self._routines(pieces)

        blob = bytearray()
        for name in self._keywords:
            blob += name.encode("ascii") + b"\x00"
        blob += bytes(pieces.table_va - (base_va + len(blob)))
        blob += build_table(
            rows,
            (pieces.keyword_va, pieces.offset_keyword_va, pieces.angle_keyword_va),
            (routines["parse_scale"], routines["parse_offset"], routines["parse_angle"]),
        )
        assert base_va + len(blob) == pieces.code_va, "the cave layout and its addresses disagree"
        blob += build_code(pieces.code_va, pieces.count_va, pieces.records_va)
        blob += bytes(pieces.count_va - (base_va + len(blob)))
        blob += bytes(4 + RECORD_SIZE * RECORD_CAPACITY)  # the counter, then the records
        assert len(blob) == pieces.size, "the cave is not the size its layout says"
        return bytes(blob)

    @staticmethod
    def _anchor_problems(data: bytes | bytearray, anchors: dict[int, bytes]) -> list[str]:
        problems: list[str] = []
        for va, stock in anchors.items():
            off = va_to_offset(data, va)
            if off is None:
                problems.append(f"@0x{va:08x} is not mapped - not the expected build")
                continue
            got = bytes(data[off : off + len(stock)])
            if got != stock:
                problems.append(f"@0x{va:08x}: expected {stock.hex()}, got {got.hex()}")
        return problems

    def _check_anchors(self, data: bytes | bytearray) -> None:
        problems = self._anchor_problems(data, ANCHORS)
        if problems:
            raise ValueError(
                f"{self.name}: not the expected build, or already carries this patch: "
                + "; ".join(problems)
            )

    @staticmethod
    def _check_table(data: bytes | bytearray, rows: tuple[Entry, ...]) -> None:
        """Raise unless the live table still has the layout the padding is inferred from.

        `BirthFadeAdditive` has to be the one-byte `Bool` right before the index, and no row may
        already store into the three bytes after it - a patch that took them first would have its
        field overwritten by this one's, silently."""
        birth_fade = [row for row in rows if read_cstring(data, row[0]) == "BirthFadeAdditive"]
        if [(row[1], row[3]) for row in birth_fade] != [
            (INI_PARSE_BOOL, W3D_MODEL_DRAW_BIRTH_FADE_ADDITIVE)
        ]:
            raise ValueError(
                "the model draw table's BirthFadeAdditive is not one Bool at "
                f"+0x{W3D_MODEL_DRAW_BIRTH_FADE_ADDITIVE:x} - not the expected build"
            )
        for name_va, _parse, _user, offset in rows:
            if FIELD_OFFSET <= offset < FIELD_OFFSET + FIELD_WIDTH:
                raise ValueError(
                    f"the model draw field {read_cstring(data, name_va)!r} already stores into "
                    f"+0x{offset:x}, the padding this patch needs"
                )

    def _check_keywords_free(self, data: bytes | bytearray, rows: tuple[Entry, ...]) -> None:
        """Raise if any table a model draw's reader searches already parses one of the keywords.

        The reader walks the derived module's table beside the shared one and takes the first
        match, so a duplicate would parse and the new field would silently never be written - for
        every module, or for one."""
        tables = [rows]
        tables += [
            read_field_table(data, _live_table(data, ref))
            for ref in W3D_MODEL_DRAW_DERIVED_TABLE_REFS
        ]
        wanted = {name.lower() for name in self._keywords}
        for table in tables:
            for name_va, *_ in table:
                name = read_cstring(data, name_va)
                if name is not None and name.lower() in wanted:
                    raise ValueError(
                        f"a model draw module already parses {name!r} - pick another keyword"
                    )

    @classmethod
    def detect(cls, data: bytes | bytearray) -> DrawModuleScalePatch | None:
        """Recognise this patch **and recover its keywords** from ``data``.

        All three strings are the first thing in the cave, in declaration order, so they read
        straight back out; `verify` then checks the whole cave against them."""
        located = find_section(data, SECTION_NAME)
        if located is None:
            return None
        keywords = _read_keywords(data, located[0])
        if keywords is None:
            return None
        try:
            patch = cls(*keywords)
        except ValueError:
            return None  # not a set of keywords this patch could have written
        return None if patch.verify(data) else patch

    def ini_surface(self) -> Engine:
        """The three fields this patch adds to every model draw block, under whatever keywords it
        was installed with: a factor that defaults to one, an offset that defaults to nothing and an
        angle that defaults to none - all three stock behaviour, which is what makes the fields
        opt-in."""
        fields: list[FieldDelta] = []
        for block in FAMILY_BLOCKS:
            fields.append(FieldDelta(block, self.keyword, "Float", 1.0, self.name))
            fields.append(FieldDelta(block, self.offset_keyword, "Coords", None, self.name))
            fields.append(FieldDelta(block, self.angle_keyword, "Float", 0.0, self.name))
        return Engine(fields=tuple(fields))

    def verify(self, data: bytes | bytearray) -> list[str]:
        """Return the structural problems that mean ``data`` does not carry this patch for exactly
        these keywords. Reads only via ``struct`` and the section table.

        The table's rows are read back out of the cave's own copy, located by this patch's own row
        rather than counted from the end, so the cave verifies against whatever the table held when
        it was built. The **live** table is checked by name rather than by address, so a patch that
        extended it again afterwards - moving it out of this cave - still verifies."""
        located = find_section(data, SECTION_NAME)
        if located is None:
            return [f"no {SECTION_NAME} section: the file does not carry this patch"]
        section_va, section_off, vsize = located

        installed = _read_keywords(data, section_va)
        if installed is None:
            return [f"{SECTION_NAME} does not start with three keywords"]
        if installed != self._keywords:
            return [f"the keywords in {SECTION_NAME} are {installed!r}, not {self._keywords!r}"]

        try:
            table_va = self._pieces(section_va, 0).table_va
            preceding = entries_before(data, read_field_table(data, table_va), self.keyword)
            if preceding is None:
                return [f"the table in {SECTION_NAME} has no {self.keyword!r} row"]
            pieces = self._pieces(section_va, len(preceding))
            content = self._build(section_va, preceding)
            live_rows = read_field_table(data, _live_table(data, W3D_MODEL_DRAW_FIELD_TABLE_REF))
        except (ValueError, struct.error) as exc:
            return [f"cannot read back the patch (wrong build?): {exc}"]

        if len(content) > vsize:
            return [f"{SECTION_NAME} holds {vsize} bytes, too few for this patch's cave"]
        problems: list[str] = []
        # The records are written while a game reads its INI, so only what this patch lays down is
        # compared: everything up to the counter.
        fixed = pieces.count_va - section_va
        if bytes(data[section_off : section_off + fixed]) != content[:fixed]:
            problems.append(f"{SECTION_NAME} is not the cave this patch builds for {installed!r}")

        routines = self._routines(pieces)
        rows_expected = (
            (self.keyword, "parse_scale"),
            (self.offset_keyword, "parse_offset"),
            (self.angle_keyword, "parse_angle"),
        )
        for keyword, routine in rows_expected:
            mine = [row for row in live_rows if read_cstring(data, row[0]) == keyword]
            if [row[1:] for row in mine] != [(routines[routine], 0, FIELD_OFFSET)]:
                problems.append(
                    f"the live model draw table does not parse {keyword!r} into "
                    f"+0x{FIELD_OFFSET:x} through the {SECTION_NAME} parser"
                )

        expected = {W3D_MODEL_DRAW_BIRTH_FADE_DEFAULT: widened_default()}
        expected.update({site: _call(site, routines[loc]) for site, loc in SITES.items()})
        expected.update({site: _call(site, routines["transform"]) for site in TRANSFORM_SITES})
        for site_va, want in expected.items():
            off = _offset(data, site_va)
            got = bytes(data[off : off + len(want)])
            if got != want:
                problems.append(f"@0x{site_va:08x}: expected {want.hex()}, got {got.hex()}")

        problems += self._anchor_problems(data, CONTEXT_ANCHORS)
        return problems

    @classmethod
    def add_cli_arguments(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--keyword",
            default=DEFAULT_KEYWORD,
            metavar="NAME",
            help=(
                f"name of the scale field to add (default {DEFAULT_KEYWORD}); letters, digits and "
                "underscores, and not already a field of any model draw module"
            ),
        )
        parser.add_argument(
            "--offset-keyword",
            default=DEFAULT_OFFSET_KEYWORD,
            metavar="NAME",
            help=(
                f"name of the offset field to add (default {DEFAULT_OFFSET_KEYWORD}); takes "
                "X:/Y:/Z: in the object's own frame, like the engine's other Coord3D fields"
            ),
        )
        parser.add_argument(
            "--angle-keyword",
            default=DEFAULT_ANGLE_KEYWORD,
            metavar="NAME",
            help=(
                f"name of the turn field to add (default {DEFAULT_ANGLE_KEYWORD}); one angle in "
                "degrees about the object's up axis, negative turning the other way"
            ),
        )

    @classmethod
    def from_cli_args(cls, args: argparse.Namespace) -> DrawModuleScalePatch:
        return cls(
            keyword=args.keyword,
            offset_keyword=args.offset_keyword,
            angle_keyword=args.angle_keyword,
        )
