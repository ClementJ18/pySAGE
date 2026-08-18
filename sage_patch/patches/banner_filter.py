"""The banner-carrier replenish filter: an `ObjectFilter` on `BannerCarrierUpdate`.

Adds one INI keyword — `ReplenishFilter` by default — to `BannerCarrierUpdate`, limiting which
nearby hordes a banner carrier will top up. Targets the ROTWK SAGE-engine `game.dat` build
``2.01.2614.37001``. Every address below is derived in ``../docs/banner-carrier-filter.md``.

**What the engine does today.** `ReplenishNearbyHorde` is the master gate: when it is set,
`BannerCarrierUpdate::update` calls the nearby-horde scan at `SCAN_VA` *instead of* the normal
own-horde spawn path. The scan asks `ThePartitionManager` for objects within `ScanHordeDistance`,
filtered by a stack-built `PartitionFilterRelationship` whose mask is ``2`` — **allies only, with
no same-player narrowing**. `ReplenishAllNearbyHordes` is not a mode switch on that scan; it is a
loop-break checked at `0x0089AC98` *after* an object has already been replenished.

Two consequences follow, and they are why this patch exists. There is no way to say "replenish
pikemen but not archers", and no way to say "replenish my own hordes but not my ally's" — in a
2v2 a banner carrier tops up its ally's hordes and nothing in INI can stop it.

**Why this is cheap.** An `ObjectFilter` field in a `ModuleData` is **four bytes**: an index into
one global interned store (stride ``0x94``, refcounted at ``+0x8C``, "was specified" flag at
``+0x88``). 56 of the 59 such fields in the engine occupy exactly four bytes. So the whole feature
is one byte of allocation size, three repointed branches, one relocated field-parse table and a
small cave.

**Composition.** Order-independent: the cave is allocated with
:func:`~..utils.allocate_section` past every existing section and :meth:`verify` finds it by name,
no edited byte is shared with another bundled patch, and the only structure read — the stock
`BannerCarrierUpdate` field-parse table — is one nothing else rewrites. See the composition
contract on :class:`~..patcher.Patch`.

The patch has five parts:

* **The allocation.** ``push 0x44`` at `MODULEDATA_SIZE_VA` becomes ``push 0x48``. This literal
  appears exactly once and nothing ``memcpy``s the structure, so the field lands at ``0x44`` in a
  structure that was otherwise fully packed with no slack.
* **The constructor.** The ``call`` to the stock ctor is redirected through a cave shim that runs
  it and then default-constructs the new handle. Skipping this would leave the field holding
  whatever ``operator new`` returned, and the parse function treats any value other than ``-1`` as
  a live store index to release.
* **The destructor.** Likewise redirected, to release the handle's store refcount. Strictly
  optional — `ModuleData` objects are built once per INI object definition — but fifteen bytes.
* **The keyword.** The field-parse table cannot grow in place: it ends at ``0x00C66160`` where
  unrelated ``.rdata`` begins. It is loaded by a single instruction, so the patch copies it into
  the cave with one appended entry and repoints that one imm32. Lookup is a linear name scan (the
  stock table is ordered by declaration, not alphabetically), so appending needs no re-sort.
* **The test.** The ``call Object::isKindOf`` that opens the scan's loop body is redirected into a
  cave that evaluates the filter first. On a reject it returns ``al = 1``, reusing the caller's
  existing ``test al,al / jne`` to skip the object — which also means a rejected candidate never
  reaches the `ReplenishAllNearbyHordes` break, so in single-horde mode the scan keeps looking
  instead of burning its one replenish.

Why the evaluator and not the wrapper
-------------------------------------
`0x007640C1` is a convenience wrapper around the real evaluator `OBJECT_FILTER_TEST_VA`, which
takes **three** arguments: the candidate's `ThingTemplate`, the candidate's `Player`, and the
**source** `Player` the filter is written from. The wrapper passes its own second parameter
through as that source, and every stock call site passes ``0``. With a null source the evaluator
rejects unconditionally at `0x007635F6` whenever the relationship mask is non-zero — so
relationship tokens routed through the wrapper do not fall back to permissive, they *always*
return false.

Calling the evaluator directly, with the banner's own controlling player as the third argument,
costs sixteen bytes and makes the mask work: ``ALLIES`` (bit ``0x1``, accepted outright for
relationship 2, so it means *self and allies*), ``ENEMIES`` (``0x2``), ``NEUTRAL`` (``0x4``) and
``SAME_PLAYER`` (``0x8``, relationship 2 *and* matching ``Player+0x54`` — see
:data:`~..addresses.PLAYER_INDEX`). ``SAME_PLAYER`` is precisely the distinction the partition
scan cannot make.

The source player is already in the scan's frame: `0x0089ABA3` computes it and stores it at
``[ebp-0x20]``, and no other instruction in the function writes that slot. This is the one part of
the patch coupled to a stack frame rather than a symbol, so :data:`SOURCE_PLAYER_ANCHOR` is
asserted before anything is written — a reordered frame fails loudly instead of reading a stale
slot.

Note that ``ENEMIES`` and ``NEUTRAL`` can only ever narrow to nothing here: the partition scan has
already rejected everything that is not an ally before the filter runs. Rejecting them at INI-parse
time would mean patching the shared `ObjectFilter` parser, which every other filter keyword in the
game routes through — so they are documented as useless rather than blocked.

``ALLIES`` and ``SAME_PLAYER`` also nest rather than partition: bit ``0x1`` accepts relationship 2
outright, *before* the player-index comparison. So ``ALLIES`` means "self and allies" and
``SAME_PLAYER`` means "self only"; "allies but not me" is not expressible with these tokens.
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
    "KEYWORD_OFFSET",
    "PATCHED_MODULEDATA_SIZE",
    "SECTION_NAME",
    "SOURCE_PLAYER_ANCHOR",
    "STOCK_FIELDS",
    "STOCK_MODULEDATA_SIZE",
    "BannerFilterPatch",
]

# --- BannerCarrierUpdate, as this build lays it out (VA, ImageBase 0x400000) ---

#: `newModuleData`'s ``push 0x44`` — the sole `sizeof(ModuleData)` literal.
MODULEDATA_SIZE_VA = 0x0064DE90
#: The ``call`` to the ModuleData constructor, inside `newModuleData`.
MODULEDATA_CTOR_CALL_VA = 0x0064DEA5
MODULEDATA_CTOR_VA = 0x0089A765
#: The ``call`` to the ModuleData destructor, inside the vector-deleting destructor.
MODULEDATA_DTOR_CALL_VA = 0x0089AE71
MODULEDATA_DTOR_VA = 0x0089A816

#: The 16-byte-stride field-parse table, and the single imm32 that loads it (inside
#: ``push 0xc66090`` at ``0x0089AE90``, so the operand starts one byte later).
FIELD_TABLE_VA = 0x00C66090
FIELD_TABLE_REF_VA = 0x0089AE91

#: The nearby-horde replenish scan, and the ``call Object::isKindOf`` opening its loop body.
SCAN_VA = 0x0089AB8F
SCAN_KINDOF_CALL_VA = 0x0089AC38
IS_KIND_OF_VA = 0x0044DDEC

#: ``mov [ebp-0x20], eax`` — the scan storing the banner's controlling player. The cave reads that
#: slot, so this exact encoding at this exact address is a precondition of the patch.
SOURCE_PLAYER_ANCHOR = (0x0089ABC0, b"\x89\x45\xe0")
#: The frame displacement the anchor establishes, as it appears in ``push dword [ebp-0x20]``.
SOURCE_PLAYER_DISP8 = -0x20

# --- the ObjectFilter handle ABI ---

OBJECT_FILTER_PARSE_VA = 0x0076392F  # the INI parse fn that goes in the field table
OBJECT_FILTER_CTOR_VA = 0x0076406F  # __thiscall(ecx=&field) -> writes -1, interns the default
OBJECT_FILTER_DTOR_VA = 0x007629B0  # __thiscall(ecx=&field) -> releases the store refcount
OBJECT_FILTER_IS_DEFINED_VA = 0x00762977  # __thiscall(ecx=&field) -> bool, reads the +0x88 flag
OBJECT_FILTER_TEST_VA = 0x00763543  # __thiscall(ecx=&field, template, player, source), ret 0xc

GET_CONTROLLING_PLAYER_VA = 0x0068B678  # __thiscall(ecx=Object*) -> Player*

# --- layout ---

STOCK_MODULEDATA_SIZE = 0x44
#: Where the new four-byte handle lands: the end of the stock structure, which is fully packed.
FILTER_OFFSET = STOCK_MODULEDATA_SIZE
PATCHED_MODULEDATA_SIZE = STOCK_MODULEDATA_SIZE + 4

FIELD_ENTRY_SIZE = 16

#: The stock table, in table order, as ``(name, ModuleData offset)``. Used as a fingerprint: all
#: twelve names *and* offsets must match before anything is written, which is a far stronger
#: build check than the size literal alone.
STOCK_FIELDS = (
    ("IdleSpawnRate", 0x08),
    ("MeleeFreeUnitSpawnTime", 0x0C),
    ("DiedRespawnTime", 0x10),
    ("MeleeFreeBannerReSpawnTime", 0x14),
    ("MorphCondition", 0x18),
    ("ExpLevelDraw", 0x24),
    ("BannerMorphFX", 0x30),
    ("UnitSpawnFX", 0x34),
    ("ReplenishNearbyHorde", 0x38),
    ("ReplenishAllNearbyHordes", 0x39),
    ("ScanHordeDistance", 0x3C),
    ("UpgradeRequired", 0x40),
)

#: Where the keyword string lands in the cave: immediately past the relocated table, whose entry
#: count is fixed by the build (the twelve stock fields, the new one, and the NULL terminator).
#: :meth:`BannerFilterPatch.detect` reads the keyword back from here, so this is the one place the
#: offset is written down and :meth:`BannerFilterPatch._compute_section` lays the cave out by it.
KEYWORD_OFFSET = (len(STOCK_FIELDS) + 2) * FIELD_ENTRY_SIZE

#: `ReplenishAllNearbyHordes`, for the ``--only-when-all`` gate.
REPLENISH_ALL_OFFSET = 0x39

DEFAULT_KEYWORD = "ReplenishFilter"

SECTION_NAME = ".bnrflt"
# CNT_CODE | CNT_INITIALIZED_DATA | MEM_EXECUTE | MEM_READ — the cave holds the relocated table,
# the keyword string and three code stubs, so it must be executable as well as readable.
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


# --- the cave's three stubs ------------------------------------------------------------------


def build_ctor(base_va: int) -> bytes:
    """Run the stock ModuleData constructor, then default-construct the new handle.

    The stock ctor is ``__thiscall`` with no arguments and returns ``this`` in ``eax``, so the
    shim needs no frame of its own — which also keeps it transparent to the unwinder, since the
    call site it replaces sits inside `newModuleData`'s protected region."""
    a = Asm(base_va)
    a.call_absolute(MODULEDATA_CTOR_VA)  # call <stock ctor>      ; eax = this
    a.emit(0x50)  # push eax
    a.emit(b"\x8d\x48", FILTER_OFFSET)  # lea ecx, [eax+0x44]
    a.call_absolute(OBJECT_FILTER_CTOR_VA)  # call <handle ctor>
    a.emit(0x58)  # pop eax
    a.emit(0xC3)  # ret
    return a.finish()


def build_dtor(base_va: int) -> bytes:
    """Run the stock ModuleData destructor, then release the handle's store refcount.

    The handle dtor is tail-called, so its ``ret`` returns straight to the vector-deleting
    destructor that called this shim."""
    a = Asm(base_va)
    a.emit(0x51)  # push ecx
    a.call_absolute(MODULEDATA_DTOR_VA)  # call <stock dtor>
    a.emit(0x59)  # pop ecx
    a.emit(b"\x83\xc1", FILTER_OFFSET)  # add ecx, 0x44
    a.jmp_absolute(OBJECT_FILTER_DTOR_VA)  # jmp <handle dtor>
    return a.finish()


def build_filter(base_va: int, only_when_all: bool = False) -> bytes:
    """Test the filter against the scan's current candidate, then fall through to the stock
    ``Object::isKindOf`` call this stub replaced.

    On entry ``[esp]`` is the return address into the loop body, ``[esp+4]`` is the ``KINDOF_``
    argument the caller already pushed, ``ecx`` is the candidate `Object*`, ``edi`` is the
    `ModuleData` and ``ebp`` is the scan's own frame.

    A rejected candidate returns ``al = 1`` and ``ret 4`` — reproducing `isKindOf`'s callee
    cleanup while telling the caller "immobile", which its existing ``test al,al / jne`` turns
    into a skip. Everything else tail-calls the stock `isKindOf` so its ``ret 4`` lands at the
    original return address.

    ``ecx`` cannot be held across the calls (`isDefined` opens with ``mov ecx, [ecx]``), so the
    candidate lives on the stack; ``edi`` is safe, since all three callees are ``__thiscall`` and
    preserve it."""
    a = Asm(base_va)
    if only_when_all:
        a.emit(b"\x80\x7f", REPLENISH_ALL_OFFSET, 0x00)  # cmp byte [edi+0x39], 0
        a.jcc(JE, "stock")  # je .stock          ; not "all" -> stock

    a.emit(0x51)  # push ecx            ; save the candidate
    a.emit(b"\x8d\x4f", FILTER_OFFSET)  # lea ecx, [edi+0x44]
    a.call_absolute(OBJECT_FILTER_IS_DEFINED_VA)  # call <isDefined>
    a.emit(b"\x84\xc0")  # test al, al
    a.jcc(JE, "stock_pop")  # je .stock_pop      ; unwritten -> stock

    a.emit(b"\xff\x75", SOURCE_PLAYER_DISP8 & 0xFF)  # push dword [ebp-0x20] ; arg3 = source
    a.emit(b"\x8b\x4c\x24\x04")  # mov ecx, [esp+4]    ; the candidate
    a.call_absolute(GET_CONTROLLING_PLAYER_VA)  # call <getControllingPlayer>
    a.emit(0x50)  # push eax            ; arg2 = candidate's player
    a.emit(b"\x8b\x4c\x24\x08")  # mov ecx, [esp+8]    ; the candidate
    a.emit(b"\xff\x71\x04")  # push dword [ecx+4]  ; arg1 = ThingTemplate*
    a.emit(b"\x8d\x4f", FILTER_OFFSET)  # lea ecx, [edi+0x44]
    a.call_absolute(OBJECT_FILTER_TEST_VA)  # call <evaluator>    ; ret 0xc
    a.emit(b"\x84\xc0")  # test al, al
    a.jcc(JNE, "stock_pop")  # jne .stock_pop     ; passes -> stock

    a.emit(0x59)  # pop ecx             ; drop the candidate
    a.emit(b"\xb0\x01")  # mov al, 1           ; reject: report "immobile"
    a.emit(b"\xc2\x04\x00")  # ret 4

    a.label("stock_pop")
    a.emit(0x59)  # pop ecx             ; ecx = the candidate
    a.label("stock")
    a.jmp_absolute(IS_KIND_OF_VA)  # jmp <Object::isKindOf>
    return a.finish()


class BannerFilterPatch(Patch):
    """Add an `ObjectFilter` keyword to `BannerCarrierUpdate`'s nearby-horde replenish scan."""

    name = "banner-filter"
    author = "officialNecro"
    description = (
        "Add an ObjectFilter to BannerCarrierUpdate's nearby-horde replenish: ReplenishFilter = "
        "<ObjectFilter> beside the ReplenishNearbyHorde that turns the scan on, to say which "
        "nearby hordes - and, with a relationship term, whose - get topped up. An undeclared "
        "filter leaves the module stock"
    )

    def __init__(self, keyword: str = DEFAULT_KEYWORD, only_when_all: bool = False):
        self.keyword = keyword
        self.only_when_all = only_when_all
        self._validate()

    def __str__(self) -> str:
        scope = "ReplenishAllNearbyHordes only" if self.only_when_all else "both replenish modes"
        return f"{self.name} ({self.keyword}, {scope})"

    def _validate(self) -> None:
        keyword = self.keyword
        if not keyword or keyword != keyword.strip():
            raise ValueError(f"keyword must be non-empty and unpadded, got {keyword!r}")
        if not keyword.isascii() or not keyword.isprintable() or any(c.isspace() for c in keyword):
            raise ValueError(f"keyword must be printable ASCII with no spaces: {keyword!r}")
        if any(keyword.lower() == name.lower() for name, _off in STOCK_FIELDS):
            raise ValueError(f"{keyword!r} is already a BannerCarrierUpdate field")

    # --- apply / verify ----------------------------------------------------------------------

    def apply(self, data: bytearray) -> None:
        self._check_anchor(data)
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
        """Structural check that ``data`` carries this patch with exactly this keyword and scope
        (an empty list == verified). Locates the cave, recomputes the table, string and stubs the
        settings imply, and compares them and every repointed site to what is on disk. Reads only
        via ``struct`` + the section table, so verification needs no disassembler."""
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

        anchor_va, anchor_bytes = SOURCE_PLAYER_ANCHOR
        off = va_to_offset(data, anchor_va)
        if off is None or bytes(data[off : off + len(anchor_bytes)]) != anchor_bytes:
            problems.append(
                f"the scan's source-player store at 0x{anchor_va:08x} is not "
                f"{anchor_bytes.hex()}: the cave would read the wrong frame slot"
            )
        return problems

    @classmethod
    def detect(cls, data: bytes | bytearray) -> BannerFilterPatch | None:
        """Recognise this patch **and recover its keyword and scope**.

        The default probe only ever recognises the default settings, so a binary patched under any
        other keyword reads as unpatched. The keyword sits at a fixed offset into the cave - past
        the relocated table, whose entry count is fixed by the build - so it can be read back
        rather than guessed. ``only_when_all`` changes only the filter stub's opening test and is
        recorded nowhere else, so it is probed: off first, since that is the default."""
        located = find_section(data, SECTION_NAME)
        if located is None:
            return None
        keyword = _read_cstring(data, located[0] + KEYWORD_OFFSET)
        if keyword is None:
            return None
        for only_when_all in (False, True):
            try:
                patch = cls(keyword, only_when_all=only_when_all)
                problems = patch.verify(data)
            except (ValueError, KeyError, IndexError, TypeError, struct.error):
                return None  # not a keyword this patch could have written
            if not problems:
                return patch
        return None

    def ini_surface(self) -> Engine:
        """The one `ObjectFilter` this patch adds to `BannerCarrierUpdate`, under whatever keyword
        it was installed with. The constructor leaves it unspecified, so the default is "no
        filter" - stock behaviour, which is what makes the field opt-in. `only_when_all` is not
        part of the surface: it decides when the scan consults the filter, not whether the
        keyword parses."""
        field = FieldDelta("BannerCarrierUpdate", self.keyword, "ObjectFilter", None, self.name)
        return Engine(fields=(field,))

    # --- CLI integration ---------------------------------------------------------------------

    @classmethod
    def add_cli_arguments(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--keyword",
            default=DEFAULT_KEYWORD,
            metavar="NAME",
            help=f"the INI keyword to add to BannerCarrierUpdate (default: {DEFAULT_KEYWORD})",
        )
        parser.add_argument(
            "--only-when-all",
            action="store_true",
            help=(
                "apply the filter only when ReplenishAllNearbyHordes is Yes. Off by default: the "
                "scan runs whenever ReplenishNearbyHorde is Yes, and a keyword whose effect "
                "depends on a different keyword is hard to document"
            ),
        )

    @classmethod
    def from_cli_args(cls, args: argparse.Namespace) -> BannerFilterPatch:
        return cls(keyword=args.keyword, only_when_all=args.only_when_all)

    # --- the cave ------------------------------------------------------------------------------

    def _compute_section(
        self, data: bytes | bytearray, section_va: int
    ) -> tuple[bytes, tuple[int, int, int]]:
        """Return ``(section content, (ctor VA, dtor VA, filter VA))`` for a cave based at
        ``section_va``.

        Layout: the relocated field-parse table, the keyword string it points at, then the three
        stubs. The twelve stock entries are copied verbatim — including their name pointers, which
        keep pointing into ``.rdata`` — so their order and their strings are untouched."""
        stock = self._read_stock_table(data)

        table_size = KEYWORD_OFFSET  # the stock entries + the new one + the NULL terminator
        keyword_va = section_va + table_size

        blob = bytearray(self.keyword.encode("ascii") + b"\x00")
        while len(blob) % 4:  # keep the stubs dword-aligned
            blob += b"\x00"

        new_entry = _u32(keyword_va) + _u32(OBJECT_FILTER_PARSE_VA) + _u32(0) + _u32(FILTER_OFFSET)
        table = stock + new_entry + bytes(FIELD_ENTRY_SIZE)  # NULL-terminate
        assert len(table) == table_size

        ctor_va = keyword_va + len(blob)
        ctor = build_ctor(ctor_va)
        dtor_va = ctor_va + len(ctor)
        dtor = build_dtor(dtor_va)
        filter_va = dtor_va + len(dtor)
        filter_code = build_filter(filter_va, self.only_when_all)

        content = bytes(table) + bytes(blob) + ctor + dtor + filter_code
        return content, (ctor_va, dtor_va, filter_va)

    def _read_stock_table(self, data: bytes | bytearray) -> bytes:
        """The twelve stock entries verbatim, after checking they really are this build's
        `BannerCarrierUpdate` table: every name and every `ModuleData` offset must match, and the
        thirteenth entry must be the NULL terminator."""
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
            got = _read_cstring(data, name_va)
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

    def _check_anchor(self, data: bytes | bytearray) -> None:
        """Assert the scan still stores the banner's controlling player where the cave reads it.

        This is the one site the patch depends on that it does not itself rewrite, so nothing else
        would catch a mismatch: the cave would simply read whatever the frame slot happens to hold
        and hand it to the evaluator as the source player."""
        va, expected = SOURCE_PLAYER_ANCHOR
        off = va_to_offset(data, va)
        if off is None:
            raise ValueError(f"the scan's source-player store 0x{va:08x} is not mapped")
        got = bytes(data[off : off + len(expected)])
        if got != expected:
            raise ValueError(
                f"the scan's source-player store @0x{va:08x}: expected {expected.hex()}, "
                f"got {got.hex()} — this is not the expected build"
            )

    # --- the edits -----------------------------------------------------------------------------

    def _edits(
        self,
        data: bytes | bytearray,
        section_va: int,
        stubs: tuple[int, int, int],
    ) -> list[tuple[int, bytes, bytes, str]]:
        """Every byte range this patch rewrites, as ``(file offset, old, new, note)``."""
        ctor_va, dtor_va, filter_va = stubs
        edits: list[tuple[int, bytes, bytes, str]] = []

        def at(va: int, old: bytes, new: bytes, note: str) -> None:
            off = va_to_offset(data, va)
            if off is None:
                raise ValueError(f"{note}: VA 0x{va:08x} is not mapped")
            edits.append((off, old, new, note))

        at(
            MODULEDATA_SIZE_VA,
            bytes((0x6A, STOCK_MODULEDATA_SIZE)),
            bytes((0x6A, PATCHED_MODULEDATA_SIZE)),
            "sizeof(BannerCarrierUpdateModuleData)",
        )
        at(
            MODULEDATA_CTOR_CALL_VA,
            _call_bytes(MODULEDATA_CTOR_CALL_VA, MODULEDATA_CTOR_VA),
            _call_bytes(MODULEDATA_CTOR_CALL_VA, ctor_va),
            "ModuleData ctor -> cave",
        )
        at(
            MODULEDATA_DTOR_CALL_VA,
            _call_bytes(MODULEDATA_DTOR_CALL_VA, MODULEDATA_DTOR_VA),
            _call_bytes(MODULEDATA_DTOR_CALL_VA, dtor_va),
            "ModuleData dtor -> cave",
        )
        at(
            FIELD_TABLE_REF_VA,
            _u32(FIELD_TABLE_VA),
            _u32(section_va),
            "field-parse table -> cave",
        )
        at(
            SCAN_KINDOF_CALL_VA,
            _call_bytes(SCAN_KINDOF_CALL_VA, IS_KIND_OF_VA),
            _call_bytes(SCAN_KINDOF_CALL_VA, filter_va),
            "replenish scan isKindOf -> cave",
        )
        return edits
