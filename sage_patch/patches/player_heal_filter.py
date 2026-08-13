"""The player-heal filter: an `ObjectFilter` on `PlayerHealSpecialPower`.

Adds one INI keyword - `HealFilter` by default - to `PlayerHealSpecialPower`, narrowing which
objects the heal actually touches. Targets the ROTWK SAGE-engine `game.dat` build
``2.01.2614.37001``. Every address below is derived in ``../docs/player-heal-filter.md``.

**What the engine does today.** `PlayerHealSpecialPower::doSpecialPower` asks
`ThePartitionManager` for everything within `HealRadius` and hands each candidate to the
per-object routine at `HEAL_ONE_VA`. That routine screens the candidate three ways: a template
flag, `HealAffects` (a `KindOfFlags` bitmask, tested at `HEAL_KINDOF_CALL_VA`), and a
relationship test that accepts the caster's own player outright and otherwise requires
relationship ``2``. So the only thing a modder can say about *who* gets healed is a `KINDOF`
mask, and the relationship half is hardcoded: a heal that reaches allied hordes cannot be told
not to, and one that should only touch a named unit has no way to say so.

**Why this is cheap.** An `ObjectFilter` field in a `ModuleData` is **four bytes** - an index into
one global interned store (stride ``0x94``, refcounted at ``+0x8C``, "was specified" flag at
``+0x88``). The `ModuleData` this patch grows already carries three of them, inherited from
`SpecialAbilityUpdateModuleData`: `AttributeModifierAffects` at ``+0x24``, and
`RequirementsFilterMPSkirmish`/`RequirementsFilterStrategic` four bytes apart at ``+0x38`` and
``+0x3C``. So the whole feature is four bytes of allocation size, two repointed branches, one
relocated field-parse table and a small cave.

**Composition.** Order-independent: the cave is allocated with
:func:`~..utils.allocate_section` past every existing section and :meth:`verify` finds it by name,
no edited byte is shared with another bundled patch, and the only structures read - the stock
`PlayerHealSpecialPower` field-parse table and the inherited `SpecialAbilityUpdate` one - are
tables nothing else rewrites. See the composition contract on :class:`~..patcher.Patch`.

The patch has four parts:

* **The allocation.** ``push 0xAC`` at `MODULEDATA_SIZE_VA` becomes ``push 0xB0``. The field lands
  at ``0xAC`` in a structure that was otherwise fully packed with no slack, and nothing
  ``memcpy``s it.
* **The constructor.** The ``call`` to the stock ctor is redirected through a cave shim that runs
  it and then default-constructs the new handle. Skipping this would leave the field holding
  whatever ``operator new`` returned, and the parse function treats any value other than ``-1`` as
  a live store index to release.
* **The keyword.** The field-parse table cannot grow in place: it ends at ``0x00C74F30`` where a
  vtable begins. It is loaded by a single instruction, so the patch copies it into the cave with
  one appended entry and repoints that one imm32. Lookup is a linear name scan, so appending needs
  no re-sort.
* **The test.** The ``call`` that applies `HealAffects` is redirected into a cave that evaluates
  the filter first. On a reject it returns ``al = 0``, reusing the caller's existing
  ``test al,al / je`` to skip the candidate before it is healed, before the `HealFX` plays and
  before the OCL fires.

The two tests are an **AND**: a candidate has to satisfy `HealAffects` *and* the filter, because
the accepting path tail-calls the `KindOfFlags` test the stub replaced. A `ModuleData` that never
writes the keyword takes the stock path bit-for-bit.

Why the evaluator and not the wrapper
-------------------------------------
`0x007640C1` is a convenience wrapper around the real evaluator `OBJECT_FILTER_TEST_VA`, which
takes **three** arguments: the candidate's `ThingTemplate`, the candidate's `Player`, and the
**source** `Player` the filter is written from. The wrapper passes its own second parameter
through as that source, and every stock call site passes ``0``. With a null source the evaluator
rejects unconditionally at `0x007635F6` whenever the relationship mask is non-zero - so
relationship tokens routed through the wrapper do not fall back to permissive, they *always*
return false.

Calling the evaluator directly, with the caster's own controlling player as the third argument,
makes the mask work: ``ALLIES`` (bit ``0x1``, accepted outright for relationship 2, so it means
*self and allies*), ``ENEMIES`` (``0x2``), ``NEUTRAL`` (``0x4``) and ``SAME_PLAYER`` (``0x8``,
relationship 2 *and* matching ``Player+0x54`` - see :data:`~..addresses.PLAYER_INDEX`).
``SAME_PLAYER`` is the distinction the stock relationship test cannot make, and the one this
keyword mainly exists for.

The source player is not read out of a frame slot: the per-object routine keeps the module in
``ebx``, so the cave recomputes it with ``getControllingPlayer([ebx+8])``. That costs five bytes
more than reading a stack slot and removes the patch's only dependency on a stack frame. What it
does depend on is the routine's register allocation, so :data:`REGISTER_ANCHORS` pins every
instruction that establishes it and is asserted before anything is written.

Note that ``ENEMIES`` and ``NEUTRAL`` can only ever narrow to nothing here: the stock relationship
test runs after this one and rejects everything that is neither the caster's own nor an ally.
Rejecting them at INI-parse time would mean patching the shared `ObjectFilter` parser, which every
other filter keyword in the game routes through - so they are documented as useless rather than
blocked.

``ALLIES`` and ``SAME_PLAYER`` also nest rather than partition: bit ``0x1`` accepts relationship 2
outright, *before* the player-index comparison. So ``ALLIES`` means "self and allies" and
``SAME_PLAYER`` means "self only"; "allies but not me" is not expressible with these tokens.

No destructor
-------------
Unlike the banner-carrier filter, this patch does not release the handle's store refcount when the
`ModuleData` dies. `PlayerHealSpecialPowerModuleData`'s vtable at ``0x00C75268`` is shared - the
linker folded it with seven other identical ones - so hooking its destructor would mean giving the
class a private vtable copy, and the cost is out of proportion to what is leaked: `ModuleData`
objects are built once per INI object definition, and re-parsing the same field releases the
previous value inside the parse function, so what stays interned is one store entry (148 bytes)
per definition that writes the keyword, for the life of the process.
"""

from __future__ import annotations

import struct
from typing import TYPE_CHECKING

from sage_ini.engine import Engine, FieldDelta

from ..asm import JE, JNE, Asm
from ..patcher import Patch
from ..utils import allocate_section, apply_byte_patch, find_section, va_to_offset

if TYPE_CHECKING:
    import argparse

__all__ = [
    "DEFAULT_KEYWORD",
    "FILTER_OFFSET",
    "INHERITED_FIELD_TABLE_VA",
    "PATCHED_MODULEDATA_SIZE",
    "REGISTER_ANCHORS",
    "SECTION_NAME",
    "STOCK_FIELDS",
    "STOCK_MODULEDATA_SIZE",
    "PlayerHealFilterPatch",
]

#: `newModuleData`'s ``push 0xAC`` - the sole `sizeof(ModuleData)` literal for this class.
MODULEDATA_SIZE_VA = 0x00652370
#: The ``call`` to the ModuleData constructor, inside `newModuleData`.
MODULEDATA_CTOR_CALL_VA = 0x00652388
MODULEDATA_CTOR_VA = 0x008CC459

#: The 16-byte-stride field-parse table, and the single imm32 that loads it (inside
#: ``push 0xc74ec0`` at ``0x008CC292``, so the operand starts one byte later).
FIELD_TABLE_VA = 0x00C74EC0
FIELD_TABLE_REF_VA = 0x008CC293

#: `SpecialAbilityUpdate`'s table, added to the same `MultiIniFieldParse` *before* this module's
#: own, and how many fields it contributes. Read only to reject a keyword it would shadow; the
#: count bounds that scan and is asserted NULL-terminated when the table is read.
INHERITED_FIELD_TABLE_VA = 0x00C64DB0
INHERITED_FIELD_COUNT = 35

#: The per-candidate heal routine, and the ``call`` inside it that applies `HealAffects`.
HEAL_ONE_VA = 0x008CC37B
HEAL_KINDOF_CALL_VA = 0x008CC3A2
#: __thiscall(ecx=Object*, KindOfFlags*) -> bool, ``ret 4``.
KIND_OF_MATCHES_VA = 0x0070C548

#: The instructions in `HEAL_ONE_VA`'s preamble that give the cave its registers: the candidate in
#: ``esi``/``ecx``, the module in ``ebx`` and the `ModuleData` in ``edi``. The cave reads all three,
#: and nothing it writes would catch a build that allocated them differently - it would simply
#: dereference the wrong pointers - so each is asserted before anything is written.
REGISTER_ANCHORS = (
    (0x008CC380, b"\x8b\x75\x08", "mov esi, [ebp+8] (the candidate)"),
    (0x008CC38D, b"\x8b\xd9", "mov ebx, ecx (the module)"),
    (0x008CC390, b"\x8b\x7b\x04", "mov edi, [ebx+4] (the ModuleData)"),
    (0x008CC39F, b"\x50\x8b\xce", "push eax / mov ecx, esi (the HealAffects call)"),
)

OBJECT_FILTER_PARSE_VA = 0x0076392F  # the INI parse fn that goes in the field table
OBJECT_FILTER_CTOR_VA = 0x0076406F  # __thiscall(ecx=&field) -> writes -1, interns the default
OBJECT_FILTER_IS_DEFINED_VA = 0x00762977  # __thiscall(ecx=&field) -> bool, reads the +0x88 flag
OBJECT_FILTER_TEST_VA = 0x00763543  # __thiscall(ecx=&field, template, player, source), ret 0xc

GET_CONTROLLING_PLAYER_VA = 0x0068B678  # __thiscall(ecx=Object*) -> Player*

STOCK_MODULEDATA_SIZE = 0xAC
#: Where the new four-byte handle lands: the end of the stock structure, which is fully packed.
FILTER_OFFSET = STOCK_MODULEDATA_SIZE
PATCHED_MODULEDATA_SIZE = STOCK_MODULEDATA_SIZE + 4

FIELD_ENTRY_SIZE = 16

#: The stock table, in table order, as ``(name, ModuleData offset)``. Used as a fingerprint: all
#: six names *and* offsets must match before anything is written, which is a far stronger build
#: check than the size literal alone. Note the order is declaration order, not offset order.
STOCK_FIELDS = (
    ("HealAmount", 0x7C),
    ("HealAsPercent", 0x80),
    ("HealAffects", 0x88),
    ("HealRadius", 0x84),
    ("HealFX", 0xA4),
    ("HealOCL", 0xA8),
)

#: How far into the cave the keyword string sits, past the relocated table (the six stock entries,
#: the new one and the terminator). `detect` reads it there to recover the keyword a binary was
#: patched with.
KEYWORD_OFFSET = (len(STOCK_FIELDS) + 2) * FIELD_ENTRY_SIZE

DEFAULT_KEYWORD = "HealFilter"

SECTION_NAME = ".hlflt"
# CNT_CODE | CNT_INITIALIZED_DATA | MEM_EXECUTE | MEM_READ - the cave holds the relocated table,
# the keyword string and two code stubs, so it must be executable as well as readable.
SECTION_CHARACTERISTICS = 0x60000060


def _u32(value: int) -> bytes:
    return struct.pack("<I", value)


def _call_bytes(from_va: int, to_va: int) -> bytes:
    """The five bytes of ``call rel32`` sited at ``from_va``."""
    return b"\xe8" + struct.pack("<i", to_va - (from_va + 5))


def _read_cstring(data: bytes | bytearray, va: int, limit: int = 64) -> str | None:
    off = va_to_offset(data, va)
    if off is None:
        return None
    end = bytes(data[off : off + limit]).find(b"\x00")
    return None if end < 0 else bytes(data[off : off + end]).decode("latin1")


def build_ctor(base_va: int) -> bytes:
    """Run the stock ModuleData constructor, then default-construct the new handle.

    The stock ctor is ``__thiscall`` with no arguments and returns ``this`` in ``eax``, so the
    shim needs no frame of its own - which also keeps it transparent to the unwinder, since the
    call site it replaces sits inside `newModuleData`'s protected region. ``eax`` is saved across
    the handle ctor because that one is a full SEH frame and does not preserve it."""
    a = Asm(base_va)
    a.call_absolute(MODULEDATA_CTOR_VA)  # call <stock ctor>    ; eax = this
    a.emit(0x50)  # push eax
    a.emit(b"\x8d\x88", _u32(FILTER_OFFSET))  # lea ecx, [eax+0xac]
    a.call_absolute(OBJECT_FILTER_CTOR_VA)  # call <handle ctor>
    a.emit(0x58)  # pop eax
    a.emit(0xC3)  # ret
    return a.finish()


def build_filter(base_va: int) -> bytes:
    """Test the filter against the candidate, then fall through to the ``HealAffects`` test this
    stub replaced.

    On entry ``[esp]`` is the return address into the per-object routine, ``[esp+4]`` is the
    ``&HealAffects`` argument the caller already pushed, ``ecx`` and ``esi`` are the candidate
    `Object*`, ``ebx`` is the module and ``edi`` is the `ModuleData`.

    A rejected candidate returns ``al = 0`` and ``ret 4`` - reproducing the callee cleanup of the
    routine it stands in for while telling the caller "does not match", which its existing
    ``test al,al / je`` turns into a skip. Everything else tail-calls the stock test so its
    ``ret 4`` lands at the original return address.

    ``ecx`` cannot be held across the calls (`isDefined` opens with ``mov ecx, [ecx]``), so the
    candidate lives on the stack; ``ebx`` and ``edi`` are safe, since every callee is
    ``__thiscall`` and preserves them."""
    a = Asm(base_va)
    a.emit(0x51)  # push ecx            ; save the candidate
    a.emit(b"\x8d\x8f", _u32(FILTER_OFFSET))  # lea ecx, [edi+0xac]
    a.call_absolute(OBJECT_FILTER_IS_DEFINED_VA)  # call <isDefined>
    a.emit(b"\x84\xc0")  # test al, al
    a.jcc(JE, "stock_pop")  # je .stock_pop      ; unwritten -> stock

    a.emit(b"\x8b\x4b\x08")  # mov ecx, [ebx+8]    ; the caster
    a.call_absolute(GET_CONTROLLING_PLAYER_VA)  # call <getControllingPlayer>
    a.emit(0x50)  # push eax            ; arg3 = source player
    a.emit(b"\x8b\x4c\x24\x04")  # mov ecx, [esp+4]    ; the candidate
    a.call_absolute(GET_CONTROLLING_PLAYER_VA)  # call <getControllingPlayer>
    a.emit(0x50)  # push eax            ; arg2 = candidate's player
    a.emit(b"\x8b\x4c\x24\x08")  # mov ecx, [esp+8]    ; the candidate
    a.emit(b"\xff\x71\x04")  # push dword [ecx+4]  ; arg1 = ThingTemplate*
    a.emit(b"\x8d\x8f", _u32(FILTER_OFFSET))  # lea ecx, [edi+0xac]
    a.call_absolute(OBJECT_FILTER_TEST_VA)  # call <evaluator>    ; ret 0xc
    a.emit(b"\x84\xc0")  # test al, al
    a.jcc(JNE, "stock_pop")  # jne .stock_pop     ; passes -> stock

    a.emit(0x59)  # pop ecx             ; drop the candidate
    a.emit(b"\x32\xc0")  # xor al, al          ; reject: report "no match"
    a.emit(b"\xc2\x04\x00")  # ret 4

    a.label("stock_pop")
    a.emit(0x59)  # pop ecx             ; ecx = the candidate
    a.jmp_absolute(KIND_OF_MATCHES_VA)  # jmp <HealAffects test>
    return a.finish()


class PlayerHealFilterPatch(Patch):
    """Add an `ObjectFilter` keyword to `PlayerHealSpecialPower`'s per-candidate screen."""

    name = "player-heal-filter"
    author = "officialNecro"
    description = "Add an ObjectFilter to PlayerHealSpecialPower's heal scan"

    def __init__(self, keyword: str = DEFAULT_KEYWORD):
        self.keyword = keyword
        self._validate()

    def __str__(self) -> str:
        return f"{self.name} ({self.keyword})"

    def _validate(self) -> None:
        keyword = self.keyword
        if not keyword or keyword != keyword.strip():
            raise ValueError(f"keyword must be non-empty and unpadded, got {keyword!r}")
        if not keyword.isascii() or not keyword.isprintable() or any(c.isspace() for c in keyword):
            raise ValueError(f"keyword must be printable ASCII with no spaces: {keyword!r}")
        if any(keyword.lower() == name.lower() for name, _off in STOCK_FIELDS):
            raise ValueError(f"{keyword!r} is already a PlayerHealSpecialPower field")

    def apply(self, data: bytearray) -> None:
        self._check_anchors(data)
        self._check_keyword_is_free(data)
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
        """Structural check that ``data`` carries this patch with exactly this keyword (an empty
        list == verified). Locates the cave, recomputes the table, string and stubs the keyword
        implies, and compares them and every repointed site to what is on disk. Reads only via
        ``struct`` + the section table, so verification needs no disassembler."""
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

        for va, expected, what in REGISTER_ANCHORS:
            off = va_to_offset(data, va)
            if off is None or bytes(data[off : off + len(expected)]) != expected:
                problems.append(
                    f"{what} at 0x{va:08x} is not {expected.hex()}: the cave would read the "
                    f"wrong registers"
                )
        return problems

    @classmethod
    def detect(cls, data: bytes | bytearray) -> PlayerHealFilterPatch | None:
        """The instance this binary carries, keyword and all. The keyword sits at a fixed offset
        into the cave - past a relocated table whose entry count is fixed by the build - so it can
        be read back rather than guessed."""
        located = find_section(data, SECTION_NAME)
        if located is None:
            return None
        keyword = _read_cstring(data, located[0] + KEYWORD_OFFSET)
        if keyword is None:
            return None
        try:
            patch = cls(keyword)
        except ValueError:
            return None  # not a keyword this patch could have written
        return None if patch.verify(data) else patch

    def ini_surface(self) -> Engine:
        """The one `ObjectFilter` this patch adds to `PlayerHealSpecialPower`, under whatever
        keyword it was installed with. The constructor leaves it unspecified, so the default is
        "no filter" - stock behaviour, which is what makes the field opt-in."""
        field = FieldDelta("PlayerHealSpecialPower", self.keyword, "ObjectFilter", None, self.name)
        return Engine(fields=(field,))

    @classmethod
    def add_cli_arguments(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--keyword",
            default=DEFAULT_KEYWORD,
            metavar="NAME",
            help=(f"the INI keyword to add to PlayerHealSpecialPower (default: {DEFAULT_KEYWORD})"),
        )

    @classmethod
    def from_cli_args(cls, args: argparse.Namespace) -> PlayerHealFilterPatch:
        return cls(keyword=args.keyword)

    def _compute_section(
        self, data: bytes | bytearray, section_va: int
    ) -> tuple[bytes, tuple[int, int]]:
        """Return ``(section content, (ctor VA, filter VA))`` for a cave based at ``section_va``.

        Layout: the relocated field-parse table, the keyword string it points at, then the two
        stubs. The six stock entries are copied verbatim - including their name pointers, which
        keep pointing into ``.rdata`` - so their order and their strings are untouched."""
        stock = self._read_stock_table(data)

        table_size = (len(STOCK_FIELDS) + 2) * FIELD_ENTRY_SIZE  # + the new entry + terminator
        keyword_va = section_va + table_size

        blob = bytearray(self.keyword.encode("ascii") + b"\x00")
        while len(blob) % 4:  # keep the stubs dword-aligned
            blob += b"\x00"

        new_entry = _u32(keyword_va) + _u32(OBJECT_FILTER_PARSE_VA) + _u32(0) + _u32(FILTER_OFFSET)
        table = stock + new_entry + bytes(FIELD_ENTRY_SIZE)  # NULL-terminate
        assert len(table) == table_size

        ctor_va = keyword_va + len(blob)
        ctor = build_ctor(ctor_va)
        filter_va = ctor_va + len(ctor)
        filter_code = build_filter(filter_va)

        content = bytes(table) + bytes(blob) + ctor + filter_code
        return content, (ctor_va, filter_va)

    def _read_stock_table(self, data: bytes | bytearray) -> bytes:
        """The six stock entries verbatim, after checking they really are this build's
        `PlayerHealSpecialPower` table: every name and every `ModuleData` offset must match, and
        the seventh entry must be the NULL terminator."""
        entries = self._read_table(data, FIELD_TABLE_VA, len(STOCK_FIELDS))

        for index, (name, offset) in enumerate(STOCK_FIELDS):
            name_va, _parse, _userdata, field_off = struct.unpack_from(
                "<4I", entries, index * FIELD_ENTRY_SIZE
            )
            got = _read_cstring(data, name_va)
            if got != name:
                raise ValueError(f"field table entry {index}: expected {name!r}, found {got!r}")
            if field_off != offset:
                raise ValueError(
                    f"field table entry {name!r}: expected offset 0x{offset:x}, "
                    f"found 0x{field_off:x}"
                )
        return entries

    def _read_table(self, data: bytes | bytearray, table_va: int, count: int) -> bytes:
        """``count`` entries at ``table_va``, checked to be NULL-terminated straight after."""
        off = va_to_offset(data, table_va)
        if off is None:
            raise ValueError(f"the field table VA 0x{table_va:08x} is not mapped")

        size = count * FIELD_ENTRY_SIZE
        entries = bytes(data[off : off + size])
        if len(entries) != size:
            raise ValueError("the field table runs past the end of the image")

        terminator = bytes(data[off + size : off + size + FIELD_ENTRY_SIZE])
        if terminator != bytes(FIELD_ENTRY_SIZE):
            raise ValueError(
                f"the field table at 0x{table_va:08x} is not NULL-terminated after {count} "
                f"entries (found {terminator.hex()})"
            )
        return entries

    def _check_keyword_is_free(self, data: bytes | bytearray) -> None:
        """Reject a keyword `SpecialAbilityUpdate` already defines.

        Both tables hang off the same `MultiIniFieldParse`, and the inherited one is added first,
        so a duplicate name would be found there and parsed into the wrong field instead of being
        reported. The constructor cannot make this check - it has no image to read - so it runs
        here, before anything is written."""
        entries = self._read_table(data, INHERITED_FIELD_TABLE_VA, INHERITED_FIELD_COUNT)
        for index in range(INHERITED_FIELD_COUNT):
            name_va = struct.unpack_from("<I", entries, index * FIELD_ENTRY_SIZE)[0]
            name = _read_cstring(data, name_va)
            if name is not None and name.lower() == self.keyword.lower():
                raise ValueError(
                    f"{self.keyword!r} is already a SpecialAbilityUpdate field, which "
                    f"PlayerHealSpecialPower inherits - the inherited table is searched first"
                )

    def _check_anchors(self, data: bytes | bytearray) -> None:
        """Assert the per-object routine still keeps the module, the `ModuleData` and the
        candidate in the registers the cave reads them from.

        These are sites the patch depends on but does not itself rewrite, so nothing else would
        catch a mismatch: the cave would simply dereference whatever the registers happened to
        hold."""
        for va, expected, what in REGISTER_ANCHORS:
            off = va_to_offset(data, va)
            if off is None:
                raise ValueError(f"{what}: VA 0x{va:08x} is not mapped")
            got = bytes(data[off : off + len(expected)])
            if got != expected:
                raise ValueError(
                    f"{what} @0x{va:08x}: expected {expected.hex()}, got {got.hex()} - this is "
                    f"not the expected build"
                )

    def _edits(
        self,
        data: bytes | bytearray,
        section_va: int,
        stubs: tuple[int, int],
    ) -> list[tuple[int, bytes, bytes, str]]:
        """Every byte range this patch rewrites, as ``(file offset, old, new, note)``."""
        ctor_va, filter_va = stubs
        edits: list[tuple[int, bytes, bytes, str]] = []

        def at(va: int, old: bytes, new: bytes, note: str) -> None:
            off = va_to_offset(data, va)
            if off is None:
                raise ValueError(f"{note}: VA 0x{va:08x} is not mapped")
            edits.append((off, old, new, note))

        at(
            MODULEDATA_SIZE_VA,
            b"\x68" + _u32(STOCK_MODULEDATA_SIZE),
            b"\x68" + _u32(PATCHED_MODULEDATA_SIZE),
            "sizeof(PlayerHealSpecialPowerModuleData)",
        )
        at(
            MODULEDATA_CTOR_CALL_VA,
            _call_bytes(MODULEDATA_CTOR_CALL_VA, MODULEDATA_CTOR_VA),
            _call_bytes(MODULEDATA_CTOR_CALL_VA, ctor_va),
            "ModuleData ctor -> cave",
        )
        at(
            FIELD_TABLE_REF_VA,
            _u32(FIELD_TABLE_VA),
            _u32(section_va),
            "field-parse table -> cave",
        )
        at(
            HEAL_KINDOF_CALL_VA,
            _call_bytes(HEAL_KINDOF_CALL_VA, KIND_OF_MATCHES_VA),
            _call_bytes(HEAL_KINDOF_CALL_VA, filter_va),
            "HealAffects test -> cave",
        )
        return edits
