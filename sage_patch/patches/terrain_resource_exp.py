"""The terrain-resource-exp patch: let a resource spot pay without levelling its own building.

Targets the ROTWK SAGE-engine `game.dat` build ``2.01.2614.37001``. Every address below is
derived in ``../docs/terrain-resource-exp.md``.

**The gap.** `TerrainResourceBehavior` is the module on a claimed resource spot. Once the spot is
activated it wakes every `IncomeInterval` frames, computes an income, deposits it into the owning
player's purse - and then hands the **same integer** to the building's `ExperienceTracker` as
experience points. A resource building therefore levels up purely by existing, at a rate set by
how much money it makes, and no INI field separates the two.

**What this does.** Adds one boolean field, `GiveNoXP`, to the module. Default `No`, which is
stock behaviour; `Yes` skips the experience grant and leaves everything else - the deposit, the
upgrade bonus, the handicap curve, the floating `+N` text, the sleep interval - exactly as it was.

**The engine already wrote this gate.** `AutoDepositUpdate`, the other "this structure pays you on
a timer" module, ships a stock `GiveNoXP` boolean at its own `ModuleData+0x20` and gates the
identical block on it::

    0089dd10  mov  edi, [eax+0x26c]     ; ExperienceTracker
    0089dd16  mov  eax, [esi-0xc]       ; ModuleData
    0089dd19  cmp  byte [eax+0x20], 0   ; GiveNoXP
    0089dd1d  jne  0x89dd4f             ; skip the grant, keep the money

So this is not a new mechanism, and not a new name either: it is the field the engine gave one of
its two income modules and not the other, reproduced on the second one with the first one's own
gate and the first one's own keyword.

Three edits, one cave
---------------------
1. **The default, in place, for no bytes.** The new `Bool` lands in `ModuleData+0x16`, which is
   alignment padding between the two stock `Bool`s at +0x14/+0x15 and the 4-byte `KindOfFilter`
   that has to start at +0x18 - so ``sizeof`` stays 0x24 and nothing the allocator sees changes.
   `operator new` does not zero the block, so the field still needs initialising; the
   constructor's two `Bool` stores rewrite into ``and dword [esi+0x14], 0`` plus the same
   `Visible` store, eight bytes for eight. That is the constructor's own idiom - ``and dword
   [esi+0x0c], 0`` sits three instructions earlier - and it clears +0x16 on the way past.

2. **The field table moves, and one reference is repointed.** The stock table at ``0x00C5FD78``
   is boxed in: its own keyword strings sit immediately before it and its NULL terminator
   immediately after. So it is rebuilt in the cave - the eight stock rows copied verbatim, since
   their name pointers are absolute and keep pointing at the stock strings, plus one appended row
   and the terminator. There is **exactly one reference to the table in the whole image**, the
   `push` immediate inside `buildFieldParse`, and the table is walked to its terminator rather
   than to a count, so no bound needs raising anywhere.

3. **A 6-byte hook on the experience block.** The stock window from ``0x0088573C`` to the first
   `push` is 21 bytes holding 21 bytes of code, so the gate's three instructions do not fit in
   place. Hooking the `ExperienceTracker` load displaces exactly one instruction, and the hook
   site is *itself* a jump target - the `jle` past the deposit lands on it when the income comes
   out <= 0 - so one edit gates both paths. `eax` is dead there on both of them.

**What it does not do.** The `[obj+0x26C]` -> `isTrainable` -> `addExperiencePoints` idiom has
fifteen call sites in the image; this gates one. `ProductionUpdate`, the special-ability updates,
the production-exit updates and `AutoDepositUpdate` keep granting experience as they do now, and a
building fed by an `ExperienceScalarUpgrade` or a `ShareExperienceBehavior` sponsor still levels -
this gates one producer, not the tracker.

**Determinism.** Experience feeds `ExperienceTracker`, veterancy is logic-side `Object` state, and
the engine CRCs it - so **every peer must run the same patched binary**, which is stricter than
the data-shape patches. And the keyword is fatal on a stock one: SAGE treats an unknown field in a
known block as a parse error, the same failure the `CommandSet` limit produces as ``"Error parsing
field '34'..."``. The field is usable only by a mod that ships the patched `game.dat`. Savegames
are unaffected either way - `ModuleData` is load-time configuration read from `.ini`, never
`Xfer`'d, and +0x16 is padding a save has never carried.

**Composition.** Order-independent: the cave is allocated past every existing section and
:meth:`verify` finds it by name. No bundled patch touches the three sites, reads the field table,
or derives anything from bytes this one rewrites; the nearest neighbours, `production-condition`
and `unique-production-id`, both live in `ProductionUpdate`.
"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sage_ini.engine import Engine, FieldDelta

from ..addresses import (
    FIELD_PARSE_STRIDE,
    INI_PARSE_BOOL,
    TERRAIN_RESOURCE_DEFAULT_STORES,
    TERRAIN_RESOURCE_DEFAULT_STORES_BYTES,
    TERRAIN_RESOURCE_EXP_BLOCK,
    TERRAIN_RESOURCE_EXP_BLOCK_BYTES,
    TERRAIN_RESOURCE_EXP_BLOCK_RESUME,
    TERRAIN_RESOURCE_EXP_BLOCK_SKIP,
    TERRAIN_RESOURCE_FIELD_TABLE,
    TERRAIN_RESOURCE_FIELD_TABLE_PUSH,
    TERRAIN_RESOURCE_FIELD_TABLE_PUSH_BYTES,
    TERRAIN_RESOURCE_FIELD_TABLE_STOCK,
    TERRAIN_RESOURCE_FREE_OFFSET,
    TERRAIN_RESOURCE_MODULE_DATA_EBP_SLOT,
    TERRAIN_RESOURCE_UPDATE,
    TERRAIN_RESOURCE_UPDATE_VTABLE,
    TERRAIN_RESOURCE_UPDATE_VTABLE_SLOT,
)
from ..asm import JNE, Asm
from ..patcher import Patch
from ..utils import allocate_section, apply_byte_patch, find_section, va_to_offset

if TYPE_CHECKING:
    import argparse

__all__ = [
    "DEFAULT_KEYWORD",
    "SECTION_NAME",
    "STOCK_FIELD_COUNT",
    "TerrainResourceExpPatch",
    "build_gate",
    "build_table",
    "rewritten_defaults",
    "validate_keyword",
]

SECTION_NAME = ".trexp"  # 6 chars: the PE name field is 8 bytes and truncates silently

#: The keyword the stock engine already uses for this exact field, on `AutoDepositUpdate`. One
#: name for one concept across both income modules is the point of the default.
DEFAULT_KEYWORD = "GiveNoXP"

#: Rows in the stock table, excluding its NULL terminator.
STOCK_FIELD_COUNT = len(TERRAIN_RESOURCE_FIELD_TABLE_STOCK) // FIELD_PARSE_STRIDE - 1

# IMAGE_SCN_CNT_INITIALIZED_DATA | MEM_EXECUTE | MEM_READ. The cave holds the rebuilt table and
# the gate, so it is both read as data and entered as code.
_CHARACTERISTICS = 0x40 | 0x20000000 | 0x40000000

# An INI keyword is matched by exact compare, so anything the parser could never match is a typo
# rather than a choice. The engine's own field names are CamelCase with digits and underscores.
_KEYWORD_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,62}$")


def validate_keyword(keyword: str) -> None:
    """Raise unless ``keyword`` is a token the engine's INI reader could ever match."""
    if not _KEYWORD_PATTERN.match(keyword):
        raise ValueError(
            "an INI keyword must be letters, digits and underscores starting with a letter "
            f"(the reader matches it by exact compare), got {keyword!r}"
        )


@dataclass(frozen=True)
class _Layout:
    """Where each piece of the cave sits, given its base address and the keyword.

    Pure arithmetic on the keyword's length, so :meth:`TerrainResourceExpPatch.apply` and
    :meth:`TerrainResourceExpPatch.verify` compute the same addresses from opposite directions."""

    keyword_va: int
    table_va: int
    code_va: int


def _layout(base_va: int, keyword: str) -> _Layout:
    string = len(keyword) + 1
    table_va = base_va + string + (-string % 4)  # keep the table's dwords aligned
    code_va = table_va + (STOCK_FIELD_COUNT + 2) * FIELD_PARSE_STRIDE  # + the row + the terminator
    return _Layout(base_va, table_va, code_va)


def rewritten_defaults() -> bytes:
    """The constructor's two `Bool` stores, rewritten to zero the new field as well.

    ``and dword [esi+0x14], 0`` clears `HighPriority`, `Visible`, the new field at +0x16 and the
    remaining pad byte in one go; the following store puts `Visible` back to `Yes`. Eight bytes
    for eight, so there is no hook and no displaced instruction - and the encoding is the
    constructor's own, byte-identical in form to the ``and dword [esi+0x0c], 0`` three
    instructions earlier."""
    new = bytes.fromhex("83661400") + TERRAIN_RESOURCE_DEFAULT_STORES_BYTES[4:]
    assert len(new) == len(TERRAIN_RESOURCE_DEFAULT_STORES_BYTES)
    return new


def build_table(keyword_va: int) -> bytes:
    """The rebuilt field-parse table: the stock rows verbatim, the new `Bool`, the terminator.

    The stock rows are copied rather than rewritten because every pointer in them is absolute -
    their keyword strings stay where they are, in `.rdata`, and only the new row points into the
    cave."""
    rows = TERRAIN_RESOURCE_FIELD_TABLE_STOCK[: STOCK_FIELD_COUNT * FIELD_PARSE_STRIDE]
    new_row = struct.pack("<IIII", keyword_va, INI_PARSE_BOOL, 0, TERRAIN_RESOURCE_FREE_OFFSET)
    return rows + new_row + bytes(FIELD_PARSE_STRIDE)


def build_gate(base_va: int) -> bytes:
    """The cave body, entered in place of `update`'s `ExperienceTracker` load.

    Reads the field off the `ModuleData` the function already cached in ``[ebp-0x18]`` - the same
    slot the very next stock instruction reads - and either runs the displaced load and rejoins,
    or jumps to the address both stock rejections already land on. `eax` is the only register it
    touches, and it is dead at the hook on both incoming paths.

    The conditional is emitted short deliberately, to match the stock `AutoDepositUpdate` gate
    (``75 30``) it reproduces; :meth:`Asm.finish` raises rather than truncating if the body ever
    grows past a rel8's reach."""
    a = Asm(base_va)
    slot = struct.pack("<b", TERRAIN_RESOURCE_MODULE_DATA_EBP_SLOT)
    a.emit(0x8B, 0x45, slot)  # mov eax, [ebp-0x18]           ; the ModuleData
    a.emit(0x80, 0x78, TERRAIN_RESOURCE_FREE_OFFSET, 0x00)  # cmp byte [eax+0x16], 0
    a.jcc_short(JNE, "skip")
    a.emit(TERRAIN_RESOURCE_EXP_BLOCK_BYTES)  # the displaced mov edi, [edi+0x26c]
    a.jmp_absolute(TERRAIN_RESOURCE_EXP_BLOCK_RESUME)
    a.label("skip")
    a.jmp_absolute(TERRAIN_RESOURCE_EXP_BLOCK_SKIP)
    return a.finish()


def _hook_bytes(code_va: int) -> bytes:
    """`jmp rel32` to the gate, padded to the 6 bytes of the instruction it displaces."""
    jump = b"\xe9" + struct.pack("<i", code_va - (TERRAIN_RESOURCE_EXP_BLOCK + 5))
    return jump + b"\x90" * (len(TERRAIN_RESOURCE_EXP_BLOCK_BYTES) - len(jump))


def _offset(data: bytes | bytearray, va: int) -> int:
    off = va_to_offset(data, va)
    if off is None:
        raise ValueError(f"VA 0x{va:08x} is not mapped - not the expected build")
    return off


def _cstring(data: bytes | bytearray, va: int, limit: int = 64) -> str | None:
    """The NUL-terminated ASCII string at ``va``, or None if it is unmapped or not one."""
    off = va_to_offset(data, va)
    if off is None:
        return None
    end = bytes(data).find(b"\x00", off, off + limit)
    if end < 0:
        return None
    try:
        return data[off:end].decode("ascii")
    except UnicodeDecodeError:
        return None


class TerrainResourceExpPatch(Patch):
    """Add a `GiveNoXP` boolean to `TerrainResourceBehavior`, gating its experience grant."""

    name = "terrain-resource-exp"
    author = "officialNecro"
    description = (
        "Add a GiveNoXP boolean to TerrainResourceBehavior, so a resource spot can pay its "
        "owner without levelling its own building"
    )

    def __init__(self, keyword: str = DEFAULT_KEYWORD):
        self.keyword = keyword
        validate_keyword(keyword)

    def __str__(self) -> str:
        return f"{self.name} ({self.keyword})"

    def apply(self, data: bytearray) -> None:
        self._check_dispatch(data)
        self._check_table(data)
        self._check_keyword_free(data)

        base_va = allocate_section(data, SECTION_NAME, self._build, _CHARACTERISTICS)
        pieces = _layout(base_va, self.keyword)

        for file_off, old, new, note in (
            (
                _offset(data, TERRAIN_RESOURCE_DEFAULT_STORES),
                TERRAIN_RESOURCE_DEFAULT_STORES_BYTES,
                rewritten_defaults(),
                f"TerrainResourceBehaviorModuleData ctor -> {self.keyword} defaults to No",
            ),
            (
                _offset(data, TERRAIN_RESOURCE_FIELD_TABLE_PUSH),
                TERRAIN_RESOURCE_FIELD_TABLE_PUSH_BYTES,
                b"\x68" + struct.pack("<I", pieces.table_va),
                f"buildFieldParse -> the {SECTION_NAME} field table",
            ),
            (
                _offset(data, TERRAIN_RESOURCE_EXP_BLOCK),
                TERRAIN_RESOURCE_EXP_BLOCK_BYTES,
                _hook_bytes(pieces.code_va),
                f"TerrainResourceBehavior::update -> the {self.keyword} gate",
            ),
        ):
            apply_byte_patch(data, file_off, old, new, note)

    def _build(self, base_va: int) -> bytes:
        """The cave: the keyword string, the rebuilt table, the gate."""
        pieces = _layout(base_va, self.keyword)
        blob = self.keyword.encode("ascii") + b"\x00"
        blob += bytes(pieces.table_va - (base_va + len(blob)))
        blob += build_table(pieces.keyword_va)
        assert base_va + len(blob) == pieces.code_va, "the cave layout and its addresses disagree"
        return blob + build_gate(pieces.code_va)

    @staticmethod
    def _check_dispatch(data: bytes | bytearray) -> None:
        """Raise unless the module's `UpdateModule` vtable still names the function being hooked.

        A hook installed 6 bytes into some other function assembles perfectly and never runs."""
        slot_va = TERRAIN_RESOURCE_UPDATE_VTABLE + TERRAIN_RESOURCE_UPDATE_VTABLE_SLOT
        target = struct.unpack_from("<I", data, _offset(data, slot_va))[0]
        if target != TERRAIN_RESOURCE_UPDATE:
            raise ValueError(
                f"vtable slot 0x{slot_va:08x} dispatches to 0x{target:08x}, not "
                f"0x{TERRAIN_RESOURCE_UPDATE:08x} - the update being hooked is not the live one"
            )

    @staticmethod
    def _check_table(data: bytes | bytearray) -> None:
        """Raise unless the stock field table is where and what it is expected to be.

        Checked before anything is written, because the table is copied into the cave rather than
        read row by row: a build whose table differs here would be rebuilt wrong and silently."""
        off = _offset(data, TERRAIN_RESOURCE_FIELD_TABLE)
        got = bytes(data[off : off + len(TERRAIN_RESOURCE_FIELD_TABLE_STOCK)])
        if got != TERRAIN_RESOURCE_FIELD_TABLE_STOCK:
            raise ValueError(
                f"the TerrainResourceBehavior field table at 0x{TERRAIN_RESOURCE_FIELD_TABLE:08x} "
                "is not the stock one - the file is not the expected build, or already carries "
                "this patch"
            )

    def _check_keyword_free(self, data: bytes | bytearray) -> None:
        """Raise if the module already parses this keyword.

        A duplicate row would parse - the reader takes the first match and the engine would never
        complain - so the field would exist and silently do nothing."""
        for index in range(STOCK_FIELD_COUNT):
            name_va = struct.unpack_from(
                "<I", TERRAIN_RESOURCE_FIELD_TABLE_STOCK, index * FIELD_PARSE_STRIDE
            )[0]
            if _cstring(data, name_va) == self.keyword:
                raise ValueError(
                    f"TerrainResourceBehavior already has a {self.keyword!r} field - pick "
                    "another keyword"
                )

    @classmethod
    def detect(cls, data: bytes | bytearray) -> TerrainResourceExpPatch | None:
        """Recognise this patch **and recover its keyword** from ``data``.

        The default probe would only ever recognise the default keyword. The keyword string is
        the first thing in the cave (`_layout` puts it at the section base), so it reads straight
        back out; `verify` then checks the whole cave against it."""
        located = find_section(data, SECTION_NAME)
        if located is None:
            return None
        keyword = _cstring(data, located[0])
        if keyword is None:
            return None
        try:
            patch = cls(keyword)
        except ValueError:
            return None  # not a keyword this patch could have written
        return None if patch.verify(data) else patch

    def ini_surface(self) -> Engine:
        """The one `Bool` this patch adds to `TerrainResourceBehavior`, under whatever keyword it
        was installed with. The constructor zeroes it, so the default is `No` - stock behaviour,
        which is what makes the field opt-in."""
        return Engine(
            fields=(FieldDelta("TerrainResourceBehavior", self.keyword, "Bool", False, self.name),)
        )

    def verify(self, data: bytes | bytearray) -> list[str]:
        """Structural check that ``data`` carries this patch for exactly this keyword. Reads only
        via ``struct`` and the section table, so it needs no disassembler.

        Every address is recovered from where the cave actually landed rather than from where it
        would land on a clean image, so a build carrying another patch's section too verifies the
        same."""
        located = find_section(data, SECTION_NAME)
        if located is None:
            return [f"no {SECTION_NAME} section: the file does not carry this patch"]
        section_va, _section_off, vsize = located
        pieces = _layout(section_va, self.keyword)

        problems: list[str] = []
        try:
            problems += self._verify_cave(data, pieces, section_va, vsize)
            problems += self._verify_sites(data, pieces)
        except (ValueError, struct.error) as exc:
            problems.append(f"cannot read back the patch (wrong build?): {exc}")
        return problems

    def _verify_cave(
        self, data: bytes | bytearray, pieces: _Layout, section_va: int, vsize: int
    ) -> list[str]:
        problems: list[str] = []
        if pieces.code_va + len(build_gate(pieces.code_va)) > section_va + vsize:
            problems.append(
                f"{SECTION_NAME} holds {vsize} bytes, too few for the table and the gate"
            )
            return problems
        got_keyword = _cstring(data, pieces.keyword_va)
        if got_keyword != self.keyword:
            problems.append(
                f"the keyword in {SECTION_NAME} is {got_keyword!r}, not {self.keyword!r}"
            )
        want_table = build_table(pieces.keyword_va)
        table_off = _offset(data, pieces.table_va)
        if bytes(data[table_off : table_off + len(want_table)]) != want_table:
            problems.append(
                f"the field table at 0x{pieces.table_va:08x} is not the stock "
                f"{STOCK_FIELD_COUNT} rows plus a Bool at ModuleData+0x"
                f"{TERRAIN_RESOURCE_FREE_OFFSET:02x}"
            )
        want_gate = build_gate(pieces.code_va)
        code_off = _offset(data, pieces.code_va)
        if bytes(data[code_off : code_off + len(want_gate)]) != want_gate:
            problems.append(f"the gate at 0x{pieces.code_va:08x} is not the one this patch builds")
        return problems

    def _verify_sites(self, data: bytes | bytearray, pieces: _Layout) -> list[str]:
        problems: list[str] = []
        checks = (
            (
                TERRAIN_RESOURCE_DEFAULT_STORES,
                rewritten_defaults(),
                f"the ctor does not default {self.keyword} to No",
            ),
            (
                TERRAIN_RESOURCE_FIELD_TABLE_PUSH,
                b"\x68" + struct.pack("<I", pieces.table_va),
                f"buildFieldParse does not push the {SECTION_NAME} field table",
            ),
            (
                TERRAIN_RESOURCE_EXP_BLOCK,
                _hook_bytes(pieces.code_va),
                f"the experience block is not hooked to the {SECTION_NAME} gate",
            ),
        )
        for va, want, complaint in checks:
            off = _offset(data, va)
            got = bytes(data[off : off + len(want)])
            if got != want:
                problems.append(f"@0x{va:08x}: {complaint} (holds {got.hex()})")
        return problems

    @classmethod
    def add_cli_arguments(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--keyword",
            default=DEFAULT_KEYWORD,
            metavar="NAME",
            help=(
                f"name of the INI field to add (default {DEFAULT_KEYWORD}, which is what the "
                "stock AutoDepositUpdate calls the same field); letters, digits and underscores, "
                "and must not already be a TerrainResourceBehavior field"
            ),
        )

    @classmethod
    def from_cli_args(cls, args: argparse.Namespace) -> TerrainResourceExpPatch:
        return cls(keyword=args.keyword)
