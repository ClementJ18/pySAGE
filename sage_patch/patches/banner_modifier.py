"""Add `BannerCarrierInflictsModifierOnDeath` to `HordeContain`: a `ModifierList` the horde's
survivors take when its banner carrier dies, lifted when it is re-bannered.

The stock death handler (`BANNER_DIED_VA`) can only destroy the horde or do nothing. The patch adds
the field to `HordeContain`'s module data and hooks that handler to apply the modifier to every
member, and the banner-installed path to remove it. Logic-side: every peer needs the same binary.

Derivation: `../docs/banner-carrier-modifier.md`.
"""

from __future__ import annotations

import struct
from typing import TYPE_CHECKING

from sage_ini.engine import Engine, FieldDelta

from ..asm import JE, Asm
from ..patcher import Patch
from ..utils import (
    allocate_section,
    apply_byte_patch,
    call_rel32,
    find_section,
    read_cstring,
    u32,
    va_to_offset,
)

if TYPE_CHECKING:
    import argparse

__all__ = [
    "DEFAULT_KEYWORD",
    "KEYWORD_OFFSET",
    "MODIFIER_OFFSET",
    "PATCHED_MODULEDATA_SIZE",
    "SECTION_NAME",
    "SIZE_SITES",
    "STOCK_FIELDS",
    "BannerModifierPatch",
]

# HordeContain, as this build lays it out (VA, ImageBase 0x400000)

#: The three `newModuleData` allocations of a `HordeContainModuleData`, as
#: `(VA of the push, stock size, which class)`. All three are `push imm32`, and all three grow
#: to the same `PATCHED_MODULEDATA_SIZE` so one field offset is right in every class.
#: `HorseHordeContain` has a second, out-of-line constructor at `0x0064B69F` with **no callers**,
#: which is why it is not here.
SIZE_SITES = (
    (0x0064B61C, 0x284, "HordeContain"),
    (0x00653317, 0x284, "HorseHordeContain"),
    (0x0064B851, 0x2CC, "AODHordeContain"),
)

#: `AODHordeContainModuleData`'s size, and therefore the first offset free in every class of the
#: family. `HordeContainModuleData` ends at `0x284` and `AODHordeContainModuleData` fills
#: `0x284`..`0x2CC` with its own thirteen fields.
MODIFIER_OFFSET = 0x2CC
PATCHED_MODULEDATA_SIZE = MODIFIER_OFFSET + 4

#: The last store in `HordeContainModuleData::HordeContainModuleData` - `mov [esi+0x280], ebx`
#: with `ebx` the constructor's zero register, zeroing the `LivingWorldOverloadTemplate`
#: `AsciiString`. The shim reproduces it and zeroes the new field the same way.
CTOR_TAIL_VA = 0x008790D7
CTOR_TAIL_BYTES = b"\x89\x9e\x80\x02\x00\x00"

#: Where the destructor destroys that same string: `lea ecx, [esi+0x280]` followed by the
#: unwind-state store the compiler pairs with it. Ten bytes, which is room for the `call`.
DTOR_STRING_VA = 0x00878D3B
DTOR_STRING_BYTES = b"\x8d\x8e\x80\x02\x00\x00\xc6\x45\xfc\x0c"

#: `AsciiString::~AsciiString` - `__thiscall`, no arguments. Identified as what the destructor
#: calls on `AlternateFormation` (`0x1B0`), `MachineType` (`0x244`) and
#: `LivingWorldOverloadTemplate` (`0x280`), the module's three `AsciiString` fields.
ASCII_STRING_DTOR = 0x00435D50

#: The 16-byte-stride field-parse table `HordeContain`'s `buildFieldParse` contributes, and the
#: single imm32 that loads it (inside `push 0xc5bb50` at `0x00878B73`, so the operand starts
#: one byte later). The table ends where the `ModuleData` vtable begins, so it cannot grow.
FIELD_TABLE_VA = 0x00C5BB50
FIELD_TABLE_REF_VA = 0x00878B74

#: `HordeContain::applyAttributeModifierToMembers` - `__thiscall(name, filter, duration)`,
#: `ret 0xc`. Walks the contained list and the module's own id list, applying the named
#: `ModifierList` to each object that passes the filter, and finally to the container object
#: itself. This is the routine behind the stock `AttributeModifiers` keyword.
APPLY_TO_MEMBERS = 0x00870E50
#: Its exact inverse - `__thiscall(name, filter)`, `ret 8`.
REMOVE_FROM_MEMBERS = 0x00870F75

#: What the two routines above take as `this`: the contain sub-object, which is the module base
#: plus this. The banner sites hold the module base, so both call sites `lea` across it.
CONTAIN_SUBOBJECT_OFFSET = 0x11C

#: `Module::m_moduleData`.
MODULEDATA_OFFSET = 0x04

#: The head of the "our banner carrier died and the horde is *not* being destroyed" arm:
#: `and dword [esi+0x26c], 0`, clearing the banner slot. Reached by both arms of the
#: `BannerCarrierDestroyHordeOnDeath` test - the `No` answer and a null `ModuleData` - which is
#: why the shim re-tests `edi` rather than assuming it.
BANNER_DIED_VA = 0x008719B5
BANNER_DIED_BYTES = b"\x83\xa6\x6c\x02\x00\x00\x00"

#: The `call` that installs a banner carrier's `ObjectID` into the module. The callee writes it
#: through the out-parameter the caller points at `module+0x26c`; the *other* caller of the same
#: callee points it at `module+0x264`, the leader slot, and is deliberately left alone.
BANNER_INSTALLED_VA = 0x00876431
BANNER_INSTALLER = 0x00876394

FIELD_ENTRY_SIZE = 16

#: The engine's `AsciiString` field parser, which the new table entry names. A `ModifierList` is
#: referenced by name everywhere in this engine - `AttributeModifierUpgrade.AttributeModifier`,
#: `HordeContain.AttributeModifiers`, `LargeGroupAudioUpdate.AttributeModifier` - and resolved
#: through `TheAttributeModifierStore` at the moment it is applied, which is what lets a block
#: defined later in the load order be named here.
ASCII_STRING_PARSE_VA = 0x0042EE5E

#: The stock table, in table order, as `(name, ModuleData offset)`. Used as a fingerprint: all
#: 43 names *and* offsets must match before anything is written.
STOCK_FIELDS = (
    ("ThisFormationIsTheMainFormation", 0x1D8),
    ("RankInfo", 0x18C),
    ("RanksThatStopAdvance", 0x1B4),
    ("RanksToReleaseWhenAttacking", 0x1B8),
    ("RanksToJustFreeWhenAttacking", 0x1C4),
    ("ComboHorde", 0x198),
    ("AlternateFormation", 0x1B0),
    ("RandomOffset", 0x1D0),
    ("LeaderPosition", 0x200),
    ("LeadersAllowed", 0x1F4),
    ("BannerCarrierPosition", 0x20C),
    ("BannerCarriersAllowed", 0x218),
    ("BannerCarrierDestroyHordeOnDeath", 0x224),
    ("BannerCarrierHordeDeathType", 0x228),
    ("LeaderRank", 0x208),
    ("BackUpMinDelayTime", 0x1DC),
    ("BackUpMaxDelayTime", 0x1E0),
    ("BackUpMinDistance", 0x1E4),
    ("BackUpMaxDistance", 0x1E8),
    ("BackupPercentage", 0x1EC),
    ("CowerRadius", 0x1F0),
    ("AttributeModifiers", 0x22C),
    ("IsPorcupineFormation", 0x238),
    ("ForcedLocomotorSet", 0x23C),
    ("MachineAllowed", 0x240),
    ("MachineType", 0x244),
    ("UseSlowHordeMovement", 0x248),
    ("SplitHorde", 0x1A4),
    ("MeleeAttackLeashDistance", 0x24C),
    ("EvaEventLastMemberDeath", 0x250),
    ("RankSplit", 0x254),
    ("SplitHordeNumber", 0x258),
    ("NotComboFormation", 0x25C),
    ("UseMarchingAnims", 0x25D),
    ("FrontAngle", 0x264),
    ("FlankedDelay", 0x268),
    ("FlankedDuration", 0x26C),
    ("MeleeBehavior", 0x260),
    ("MinimumHordeSize", 0x270),
    ("VisionRearOverride", 0x274),
    ("VisionSideOverride", 0x278),
    ("BannerCarrierMinLevel", 0x27C),
    ("LivingWorldOverloadTemplate", 0x280),
)

#: Where the keyword string lands in the cave: immediately past the relocated table, whose entry
#: count is fixed by the build (the 43 stock fields, the new one, and the NULL terminator).
#: `BannerModifierPatch.detect` reads the keyword back from here.
KEYWORD_OFFSET = (len(STOCK_FIELDS) + 2) * FIELD_ENTRY_SIZE

DEFAULT_KEYWORD = "BannerCarrierInflictsModifierOnDeath"

SECTION_NAME = ".bnrmod"
# CNT_CODE | CNT_INITIALIZED_DATA | MEM_EXECUTE | MEM_READ - the cave holds the relocated table,
# the keyword string and four code stubs, so it must be executable as well as readable.
SECTION_CHARACTERISTICS = 0x60000060


# The cave's four stubs


def build_ctor(base_va: int) -> bytes:
    """Zero `LivingWorldOverloadTemplate` and the new field, then return.

    Replaces the constructor's last store. `ebx` is the constructor's zero register - the
    displaced instruction is itself `mov [esi+0x280], ebx` into an `AsciiString`, so the stock
    code is only correct if it holds zero there - and `esi` is `this`."""
    a = Asm(base_va)
    a.emit(CTOR_TAIL_BYTES)  # mov [esi+0x280], ebx   ; the displaced store
    a.emit(b"\x89\x9e", u32(MODIFIER_OFFSET))  # mov [esi+0x2cc], ebx
    a.emit(0xC3)  # ret
    return a.finish()


def build_dtor(base_va: int) -> bytes:
    """Release the new `AsciiString`, then do what the displaced pair did.

    The destructor destroys its three `AsciiString` fields in reverse declaration order, each
    preceded by the unwind-state store the compiler pairs with it. The new field is released
    first, before that state moves on, and the pair is then reproduced verbatim so the stock
    `call` following the hook still destroys `0x280`. `ecx` is scratch; the callee is
    `__thiscall` with no arguments and preserves `esi` and `ebp`."""
    a = Asm(base_va)
    a.emit(b"\x8d\x8e", u32(MODIFIER_OFFSET))  # lea ecx, [esi+0x2cc]
    a.call_absolute(ASCII_STRING_DTOR)  # call <AsciiString::~AsciiString>
    a.emit(DTOR_STRING_BYTES)  # lea ecx,[esi+0x280] / mov [ebp-4], 0xc
    a.emit(0xC3)  # ret
    return a.finish()


def build_apply(base_va: int) -> bytes:
    """Clear the banner slot, then inflict the field's `ModifierList` on what is left of the horde.

    On entry `esi` is the `HordeContain` module, `edi` its `ModuleData` **or NULL** (this arm
    is reached both from the `BannerCarrierDestroyHordeOnDeath` = `No` answer and from the null
    check above it), and `edx` holds the dying `Object *` that the caller's very next
    instruction pushes - so `edx` is live across a hook the stock code never made a call from,
    and is saved.

    An unwritten field is a NULL `AsciiString` pointer, which is the opt-out: the store lookup is
    not even attempted."""
    a = Asm(base_va)
    a.emit(BANNER_DIED_BYTES)  # and dword [esi+0x26c], 0   ; displaced
    a.emit(b"\x85\xff")  # test edi, edi
    a.jcc(JE, "done")  # je .done            ; no ModuleData
    a.emit(b"\x8b\x87", u32(MODIFIER_OFFSET))  # mov eax, [edi+0x2cc]
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc(JE, "done")  # je .done            ; keyword unwritten

    a.emit(0x52)  # push edx            ; the dying object
    a.emit(b"\x6a\xff")  # push -1             ; the block's own Duration
    a.emit(b"\x6a\x00")  # push 0              ; no ObjectFilter
    a.emit(b"\x8d\x87", u32(MODIFIER_OFFSET))  # lea eax, [edi+0x2cc]
    a.emit(0x50)  # push eax            ; the ModifierList name
    a.emit(b"\x8d\x8e", u32(CONTAIN_SUBOBJECT_OFFSET))  # lea ecx, [esi+0x11c]
    a.call_absolute(APPLY_TO_MEMBERS)  # call <apply to members>   ; ret 0xc
    a.emit(0x5A)  # pop edx

    a.label("done")
    a.emit(0xC3)  # ret
    return a.finish()


def build_restore(base_va: int) -> bytes:
    """Take the field's `ModifierList` back off the horde, then install the banner carrier.

    Replaces the `call` that hands the new carrier's `ObjectID` to the module, so on entry
    `ecx` is the module and the callee's three arguments are already pushed above this stub's
    return address. The removal runs first and the installer is then **tail-jumped** to, so its
    `ret 0xc` returns to the original caller and cleans the original frame.

    `eax`/`ecx`/`edx` are all clobbered by the installer anyway, so only `ecx` - which is
    its `this` - has to survive this stub."""
    a = Asm(base_va)
    a.emit(0x51)  # push ecx
    a.emit(b"\x8b\x41", MODULEDATA_OFFSET)  # mov eax, [ecx+4]     ; the ModuleData
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc(JE, "done")  # je .done
    a.emit(b"\x8b\x90", u32(MODIFIER_OFFSET))  # mov edx, [eax+0x2cc]
    a.emit(b"\x85\xd2")  # test edx, edx
    a.jcc(JE, "done")  # je .done            ; keyword unwritten

    a.emit(b"\x6a\x00")  # push 0              ; no ObjectFilter
    a.emit(b"\x05", u32(MODIFIER_OFFSET))  # add eax, 0x2cc
    a.emit(0x50)  # push eax            ; the ModifierList name
    a.emit(b"\x81\xc1", u32(CONTAIN_SUBOBJECT_OFFSET))  # add ecx, 0x11c
    a.call_absolute(REMOVE_FROM_MEMBERS)  # call <remove from members> ; ret 8

    a.label("done")
    a.emit(0x59)  # pop ecx
    a.jmp_absolute(BANNER_INSTALLER)  # jmp <install banner carrier>
    return a.finish()


class BannerModifierPatch(Patch):
    """Add a `ModifierList` keyword to `HordeContain`, applied when the banner carrier dies."""

    name = "banner-modifier"
    author = "officialNecro"
    description = (
        "Add a ModifierList to HordeContain that a horde takes when its banner carrier dies: "
        "BannerCarrierInflictsModifierOnDeath = <ModifierList> beside "
        "BannerCarrierDestroyHordeOnDeath, applied to every surviving member and lifted again "
        "when the horde is re-bannered. The block's own Duration governs how long it lasts, and "
        "an undeclared keyword leaves the module stock"
    )

    def __init__(self, keyword: str = DEFAULT_KEYWORD, restore: bool = True):
        self.keyword = keyword
        self.restore = restore
        self._validate()

    def __str__(self) -> str:
        scope = "lifted on re-banner" if self.restore else "permanent"
        return f"{self.name} ({self.keyword}, {scope})"

    def _validate(self) -> None:
        keyword = self.keyword
        if not keyword or keyword != keyword.strip():
            raise ValueError(f"keyword must be non-empty and unpadded, got {keyword!r}")
        if not keyword.isascii() or not keyword.isprintable() or any(c.isspace() for c in keyword):
            raise ValueError(f"keyword must be printable ASCII with no spaces: {keyword!r}")
        if any(keyword.lower() == name.lower() for name, _off in STOCK_FIELDS):
            raise ValueError(f"{keyword!r} is already a HordeContain field")

    # Apply / verify

    def apply(self, data: bytearray) -> None:
        section_va = allocate_section(
            data,
            SECTION_NAME,
            lambda va: self._compute_section(data, va)[0],
            SECTION_CHARACTERISTICS,
        )
        # The layout is a pure function of the base VA, so re-deriving it costs nothing and keeps
        # `build` above a plain bytes-returning callable.
        _content, stubs = self._compute_section(data, section_va)
        for file_off, old, new, note in self._edits(data, section_va, stubs):
            apply_byte_patch(data, file_off, old, new, note)

    def verify(self, data: bytes | bytearray) -> list[str]:
        """Structural check that `data` carries this patch with exactly this keyword and restore
        setting (an empty list == verified). Locates the cave, recomputes the table, string and
        stubs the settings imply, and compares them and every repointed site to what is on disk.
        Reads only via `struct` + the section table, so verification needs no disassembler."""
        located = find_section(data, SECTION_NAME)
        if located is None:
            return [f"no {SECTION_NAME} section: the file does not carry this patch"]
        section_va, section_off, _vsize = located

        problems: list[str] = []
        try:
            content, stubs = self._compute_section(data, section_va)
            edits = self._edits(data, section_va, stubs)
        except (ValueError, struct.error) as exc:
            return [f"cannot recompute the expected cave (wrong build?): {exc}"]

        got = bytes(data[section_off : section_off + len(content)])
        if got != content:
            problems.append(
                f"{SECTION_NAME} does not match keyword {self.keyword!r} "
                f"(table, string or stubs differ)"
            )

        for file_off, _old, new, note in edits:
            got = bytes(data[file_off : file_off + len(new)])
            if got != new:
                problems.append(f"{note} @0x{file_off:x}: expected {new.hex()}, got {got.hex()}")
        return problems

    @classmethod
    def detect(cls, data: bytes | bytearray) -> BannerModifierPatch | None:
        """Recognise this patch **and recover its keyword and restore setting**.

        The default probe only ever recognises the default settings, so a binary patched under any
        other keyword reads as unpatched. The keyword sits at a fixed offset into the cave - past
        the relocated table, whose entry count is fixed by the build - so it can be read back
        rather than guessed. `restore` adds a stub and an edit rather than changing one, so it is
        probed: on first, since that is the default."""
        located = find_section(data, SECTION_NAME)
        if located is None:
            return None
        keyword = read_cstring(data, located[0] + KEYWORD_OFFSET)
        if keyword is None:
            return None
        for restore in (True, False):
            try:
                patch = cls(keyword, restore=restore)
                problems = patch.verify(data)
            except (ValueError, KeyError, IndexError, TypeError, struct.error):
                return None  # not a keyword this patch could have written
            if not problems:
                return patch
        return None

    def ini_surface(self) -> Engine:
        """The one `ModifierList` name this patch adds to `HordeContain`, under whatever keyword
        it was installed with - a cross-reference into the `modifiers` table, which is what the
        model already makes of the stock `AttributeModifiers`. The constructor leaves it empty, so
        the default is "no modifier" - stock behaviour, which is what makes the field opt-in.
        `HorseHordeContain` and `AODHordeContain` inherit it, in the model as in the engine."""
        field = FieldDelta("HordeContain", self.keyword, "Ref:modifiers", None, self.name)
        return Engine(fields=(field,))

    # CLI integration

    @classmethod
    def add_cli_arguments(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--keyword",
            default=DEFAULT_KEYWORD,
            metavar="NAME",
            help=f"the INI keyword to add to HordeContain (default: {DEFAULT_KEYWORD})",
        )
        parser.add_argument(
            "--no-restore",
            action="store_true",
            help=(
                "leave the modifier on the horde when it gets a banner carrier back. Off by "
                "default: without the removal a respawned banner never undoes the loss, and a "
                "malus meant for a banner-less horde outlives being re-bannered"
            ),
        )

    @classmethod
    def from_cli_args(cls, args: argparse.Namespace) -> BannerModifierPatch:
        return cls(keyword=args.keyword, restore=not args.no_restore)

    # The cave

    def _compute_section(
        self, data: bytes | bytearray, section_va: int
    ) -> tuple[bytes, tuple[int, int, int, int]]:
        """Return `(section content, (ctor VA, dtor VA, apply VA, restore VA))` for a cave based
        at `section_va`.

        Layout: the relocated field-parse table, the keyword string it points at, then the stubs.
        The 43 stock entries are copied verbatim - including their name pointers, which keep
        pointing into `.rdata` - so their order and their strings are untouched. The restore stub
        is emitted last and only when it is wanted, so `--no-restore` shortens the cave rather
        than leaving dead code in it."""
        stock = self._read_stock_table(data)

        table_size = KEYWORD_OFFSET  # the stock entries + the new one + the NULL terminator
        keyword_va = section_va + table_size

        blob = bytearray(self.keyword.encode("ascii") + b"\x00")
        while len(blob) % 4:  # keep the stubs dword-aligned
            blob += b"\x00"

        new_entry = u32(keyword_va) + u32(ASCII_STRING_PARSE_VA) + u32(0) + u32(MODIFIER_OFFSET)
        table = stock + new_entry + bytes(FIELD_ENTRY_SIZE)  # NULL-terminate
        assert len(table) == table_size

        ctor_va = keyword_va + len(blob)
        ctor = build_ctor(ctor_va)
        dtor_va = ctor_va + len(ctor)
        dtor = build_dtor(dtor_va)
        apply_va = dtor_va + len(dtor)
        apply_code = build_apply(apply_va)
        restore_va = apply_va + len(apply_code)
        restore = build_restore(restore_va) if self.restore else b""

        content = bytes(table) + bytes(blob) + ctor + dtor + apply_code + restore
        return content, (ctor_va, dtor_va, apply_va, restore_va)

    def _read_stock_table(self, data: bytes | bytearray) -> bytes:
        """The 43 stock entries verbatim, after checking they really are this build's
        `HordeContain` table: every name and every `ModuleData` offset must match, and the
        forty-fourth entry must be the NULL terminator."""
        off = va_to_offset(data, FIELD_TABLE_VA)
        if off is None:
            raise ValueError(f"the field table VA 0x{FIELD_TABLE_VA:08x} is not mapped")

        size = len(STOCK_FIELDS) * FIELD_ENTRY_SIZE
        entries = bytes(data[off : off + size])
        if len(entries) != size:
            raise ValueError("the field table runs past the end of the image")

        for index, (name, offset) in enumerate(STOCK_FIELDS):
            name_va, _parse, _userdata, field_off = struct.unpack_from(
                "<4I", entries, index * FIELD_ENTRY_SIZE
            )
            got = read_cstring(data, name_va)
            if got != name:
                raise ValueError(f"field table entry {index}: expected {name!r}, found {got!r}")
            if field_off != offset:
                raise ValueError(
                    f"field table entry {name!r}: expected offset 0x{offset:x}, "
                    f"found 0x{field_off:x}"
                )

        terminator = bytes(data[off + size : off + size + FIELD_ENTRY_SIZE])
        if terminator != bytes(FIELD_ENTRY_SIZE):
            raise ValueError(
                f"the field table is not NULL-terminated after {len(STOCK_FIELDS)} entries "
                f"(found {terminator.hex()})"
            )
        return entries

    # The edits

    def _edits(
        self,
        data: bytes | bytearray,
        section_va: int,
        stubs: tuple[int, int, int, int],
    ) -> list[tuple[int, bytes, bytes, str]]:
        """Every byte range this patch rewrites, as `(file offset, old, new, note)`."""
        ctor_va, dtor_va, apply_va, restore_va = stubs
        edits: list[tuple[int, bytes, bytes, str]] = []

        def at(va: int, old: bytes, new: bytes, note: str) -> None:
            off = va_to_offset(data, va)
            if off is None:
                raise ValueError(f"{note}: VA 0x{va:08x} is not mapped")
            edits.append((off, old, new, note))

        for va, stock_size, owner in SIZE_SITES:
            at(
                va,
                b"\x68" + u32(stock_size),
                b"\x68" + u32(PATCHED_MODULEDATA_SIZE),
                f"sizeof({owner}ModuleData)",
            )
        at(
            CTOR_TAIL_VA,
            CTOR_TAIL_BYTES,
            call_rel32(CTOR_TAIL_VA, ctor_va) + b"\x90",
            "ModuleData ctor tail -> cave",
        )
        at(
            DTOR_STRING_VA,
            DTOR_STRING_BYTES,
            call_rel32(DTOR_STRING_VA, dtor_va) + b"\x90" * 5,
            "ModuleData dtor -> cave",
        )
        at(
            FIELD_TABLE_REF_VA,
            u32(FIELD_TABLE_VA),
            u32(section_va),
            "field-parse table -> cave",
        )
        at(
            BANNER_DIED_VA,
            BANNER_DIED_BYTES,
            call_rel32(BANNER_DIED_VA, apply_va) + b"\x90" * 2,
            "banner-carrier death -> cave",
        )
        if self.restore:
            at(
                BANNER_INSTALLED_VA,
                call_rel32(BANNER_INSTALLED_VA, BANNER_INSTALLER),
                call_rel32(BANNER_INSTALLED_VA, restore_va),
                "banner-carrier install -> cave",
            )
        return edits
