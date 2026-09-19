"""The Create-A-Hero faction patch, as a :class:`~..patcher.Patch`.

Teaches the engine's nine-name side enum a caller-supplied list of mod sides plus an ``All``
token, so a `CreateAHeroClass` `SubClass` can name them in `UsableFactions` and `DefaultFaction`.
Targets the ROTWK SAGE-engine `game.dat` build ``2.01.2614.37001``. See
``../docs/cah-faction-limit.md`` for the derivation of every site.

Stock, `UsableFactions` is a 32-bit mask on each `SubClass` with one bit per entry of a
NULL-terminated name table (``Men Elves Dwarves Isengard Mordor Wild Angmar Arnor Neutral``). A
side reaches that mask through `PlayerTemplate::getSideIndex`, which resolves its `Side` string
against the same table by exact compare and answers ``9`` — one past the end — for anything it
does not recognise. Since the INI parser rejects any token outside the table, bit 9 can never be
set, so a mod side is silently offered no CAH subclasses at all.

**Composition.** Order-independent: it allocates its cave past every existing section and
:meth:`verify` finds it by name, it shares no edited byte with any other bundled patch, and the
only structure it reads — the stock side table — is one nothing else rewrites (it is repointed
away from, never modified). See the composition contract on :class:`~..patcher.Patch`.

The patch has three parts:

* **The table.** A superset table — the nine stock entries in their original order, then ``All``,
  then the caller's sides — is built in an appended ``.cahfac`` PE section, and all 28 references
  are repointed to it. Consumers that scan to the NULL terminator pick up the longer list;
  consumers bounded by a hard-coded count or end address keep their present behaviour exactly,
  which is why the stock nine must not move.
* **The resolver.** `getSideIndex`'s scan bound ``cmp esi, 9`` becomes the new entry count. Its
  not-found answer is deliberately *left* at ``9``, which the new table makes mean ``All`` — so an
  unrecognised side gets the subclasses that opted into ``All``, and nothing else.
* **The ``All`` token.** Rather than teach three separate gates about a magic bit, the
  `UsableFactions` field parser is wrapped: the stock parser still runs (and still rejects typos),
  then the wrapper expands a set ``All`` bit to a mask of all ones. Every existing test of the
  mask — the `isFactionUsable` leaf at ``0x00619477`` and the two inlined copies at ``0x00842E96``
  and ``0x00843C0F`` — passes without being touched, and so would any the engine adds elsewhere.

Why the ceiling is 22 sides
---------------------------
A side index is used as a **bit position in two independent 32-bit masks** — `UsableFactions` at
``SubClass+0x68``, and a stack-local at ``0x00932745``. Both are a single dword, so an index of 32
would make ``shr …, 5`` yield 1 and read the dword *past* the mask (`ViewInfo`, in the first case).
With indices 0..8 stock and 9 reserved for ``All``, the highest usable index is 31: 22 sides.
"""

from __future__ import annotations

import struct
from typing import TYPE_CHECKING

from sage_ini.engine import Engine, EnumDelta

from ..asm import JZ, Asm
from ..patcher import Patch
from ..utils import (
    allocate_section,
    apply_byte_patch,
    find_section,
    va_to_offset,
)
from .utils.name_tables import check_not_rebased, layout, read_terminated

if TYPE_CHECKING:
    import argparse

# --- fixed facts about the target build (VA, ImageBase 0x400000) ---
_SIDE_TABLE_VA = 0x00DA3AC0  # the stock 9-entry side name table (code copy)
_INI_TABLE_VA = 0x00D9EDD0  # the identical copy used as DefaultFaction's userData
_STOCK_PARSER_VA = 0x0061C0A5  # the stock UsableFactions field parser (cdecl thunk)
_DEFAULT_FACTION_USERDATA_VA = 0x00D9F160  # field table: DefaultFaction userData
_USABLE_FACTIONS_PARSER_VA = 0x00D9F16C  # field table: UsableFactions parse fn
_SCAN_BOUND_VA = 0x0073BDD1  # getSideIndex's `cmp esi, 9` scan bound

#: The nine stock entries, in the order the engine indexes them. They must keep these indices:
#: `Goblins` is hard-coded as an alias for `Wild` (5), and several loops are bounded by a count or
#: by the address of entry 8 rather than by the NULL terminator.
STOCK_SIDES = (
    "Men",
    "Elves",
    "Dwarves",
    "Isengard",
    "Mordor",
    "Wild",
    "Angmar",
    "Arnor",
    "Neutral",
)

#: Index of the `All` entry. Chosen as 9 because that is already the engine's answer for an
#: unrecognised side (and the literal it uses at 0x0062D4BD for "this slot has no player
#: template"), so folding the two together needs no extra patch site.
ALL_INDEX = len(STOCK_SIDES)

#: The `All` token itself.
ALL_NAME = "All"

#: Names a caller may not use: the stock nine, `All`, the parser's mask-clearing token `None`, and
#: `Goblins` (checked before the table scan, so it could never reach a new entry anyway).
RESERVED_NAMES = frozenset(name.lower() for name in (*STOCK_SIDES, ALL_NAME, "None", "Goblins"))

#: Most sides this patch can install. Bounded by the 32-bit masks the side index is used as a bit
#: position in (see the module docstring), not by the table or the section.
MAX_SIDES = 31 - ALL_INDEX

# Every reference to the table *base*: the file holds a bare imm32/disp32 at each of these VAs.
_TABLE_REF_VAS = (
    0x0061A8B6,  # UsableFactions parser, `+Name` branch
    0x0061A8F6,  # UsableFactions parser, `-Name` branch
    0x0061A961,  # UsableFactions parser, bare-name branch
    0x0073BD9E,  # the table getter
    0x0073BDBF,  # getSideIndex's scan
    0x007BE047,  # the second name->index resolver
    0x0093C590,
    0x0093DCFF,
    0x0093DEBC,
    0x0093DF78,
    0x0093E031,
    0x0093E115,
    0x00960642,
    0x009A9ABF,
    0x009D0F2B,
    0x009D1043,
    0x009D1A60,
    0x009E571F,
    0x009F02FF,
)

# Loops in the stats/leaderboard screens bounded by the *address* of entry 8 rather than a count.
# They move with the table so they keep iterating exactly the stock eight sides.
_TABLE_END_REF_VAS = (
    0x0093C5B0,
    0x0093DD1F,
    0x0093DF00,
    0x0093DFBC,
    0x0093E08E,
    0x0093E09B,
    0x0093E172,
    0x0093E17F,
)
_TABLE_END_DELTA = 0x20  # the bound is &table[8], i.e. base + 8*4

_SECTION_NAME = ".cahfac"
# CNT_CODE | CNT_INITIALIZED_DATA | MEM_EXECUTE | MEM_READ - the cave holds the table, the name
# strings and the parser wrapper, so it must be executable as well as readable.
_SECTION_CHARACTERISTICS = 0x60000060


def _u32(value: int) -> bytes:
    return struct.pack("<I", value)


def _read_cstring(data: bytes | bytearray, va: int, limit: int = 64) -> str | None:
    off = va_to_offset(data, va)
    if off is None:
        return None
    end = bytes(data[off : off + limit]).find(b"\x00")
    return None if end < 0 else bytes(data[off : off + end]).decode("latin1")


def validate_sides(sides: tuple[str, ...]) -> None:
    """Raise unless ``sides`` is a list both halves of this patch can install.

    Shared by the two halves, so a list the game accepts cannot be one the editor rejects - which
    would be a build with the table grown in only one of the two binaries."""
    if len(sides) > MAX_SIDES:
        raise ValueError(
            f"at most {MAX_SIDES} sides fit (the side index is a bit position in a 32-bit "
            f"mask, and indices 0..{ALL_INDEX} are taken), got {len(sides)}"
        )
    seen: set[str] = set()
    for side in sides:
        if not side or side != side.strip():
            raise ValueError(f"side name must be non-empty and unpadded, got {side!r}")
        if not side.isascii() or not side.isprintable() or any(c.isspace() for c in side):
            raise ValueError(f"side name must be printable ASCII with no spaces: {side!r}")
        if side[0] in "+-":
            raise ValueError(
                f"side name may not start with '+' or '-' (they prefix UsableFactions "
                f"tokens): {side!r}"
            )
        if side.lower() in RESERVED_NAMES:
            raise ValueError(f"{side!r} is reserved by the engine")
        if side.lower() in seen:
            raise ValueError(f"duplicate side name {side!r}")
        seen.add(side.lower())


def _wrapper_code(wrapper_va: int) -> bytes:
    """The 43-byte `UsableFactions` parser wrapper that lives in the cave.

    A cdecl ``(ini, instance, store, userData)`` shim: forward all four arguments to the stock
    parser, then expand a set `All` bit in the mask it wrote to all ones. ``store`` is the address
    of the mask itself, which is what the stock thunk uses it as."""
    a = Asm(wrapper_va)
    a.emit(b"\xff\x74\x24\x10" * 4)  # push [esp+0x10] x4 -> ini, instance, store, userData
    a.call_absolute(_STOCK_PARSER_VA)  # call <stock parser>
    a.emit(b"\x83\xc4\x10")  # add esp, 0x10
    a.emit(b"\x8b\x44\x24\x0c")  # mov eax, [esp+0xc]      ; store = &mask
    a.emit(b"\xf7\x00", _u32(1 << ALL_INDEX))  # test dword [eax], <All bit>
    a.jcc_short(JZ, "done")  # jz .done
    a.emit(b"\xc7\x00\xff\xff\xff\xff")  # mov dword [eax], 0xffffffff
    a.label("done")
    a.emit(0xC3)  # ret
    return a.finish()


class CahFactionsPatch(Patch):
    """Add mod sides and an ``All`` token to the Create-A-Hero faction enum."""

    name = "cah-factions"
    author = "officialNecro"
    description = (
        "Add mod sides + an 'All' token to the Create-A-Hero faction enum, so a "
        "CreateAHeroClass SubClass can name them in UsableFactions and DefaultFaction. Give "
        "--sides each side name exactly as its PlayerTemplate Side string spells it; a side the "
        "list omits gets only the subclasses that named All"
    )

    def __init__(self, sides: list[str] | tuple[str, ...] = ()):
        self.sides = tuple(sides)
        validate_sides(self.sides)

    def __str__(self) -> str:
        listed = ", ".join(self.sides) if self.sides else "no extra sides"
        return f"{self.name} ({listed})"

    @property
    def entry_count(self) -> int:
        """Table entries the patch installs, excluding the NULL terminator: the stock nine, `All`
        and the caller's sides. This is `getSideIndex`'s new scan bound."""
        return len(STOCK_SIDES) + 1 + len(self.sides)

    def apply(self, data: bytearray) -> None:
        section_va = allocate_section(
            data,
            _SECTION_NAME,
            lambda va: self._compute_section(data, va)[0],
            _SECTION_CHARACTERISTICS,
        )
        # The layout is a pure function of the base VA, so re-deriving it costs nothing and keeps
        # `build` above a plain bytes-returning callable.
        _content, wrapper_va = self._compute_section(data, section_va)
        for file_off, old, new, note in self._edits(data, section_va, wrapper_va):
            apply_byte_patch(data, file_off, old, new, note)

    def ini_surface(self) -> Engine:
        """The tokens this patch adds to the Create-A-Hero side table: ``All``, then the caller's
        sides in the order they were installed.

        `CreateAHeroClass`'s `DefaultFaction` is typed as that enum in the model, so a subclass
        written for a patched binary reads as an unknown token without these - which is the whole
        point of the patch, said in the one place a tool that never opens the binary can see it.

        The indices are the engine's own and are fixed by the table's layout: the stock nine keep
        0..8 (they must - see `STOCK_SIDES`), `All` takes `ALL_INDEX`, and each side follows.

        Declaring them here is also what obliges the editor half to exist: Worldbuilder holds its
        own copies of this table and parses `CreateAHeroClass`, so apply
        :class:`CahFactionsWorldbuilderPatch` to `Worldbuilder.exe` with the same sides in the
        same order."""
        return Engine(
            enum_members=tuple(
                EnumDelta("CreateAHeroFaction", name, ALL_INDEX + offset, self.name)
                for offset, name in enumerate((ALL_NAME, *self.sides))
            )
        )

    def verify(self, data: bytes | bytearray) -> list[str]:
        """Structural check that ``data`` already carries this patch for exactly these sides (an
        empty list == verified). Locates the ``.cahfac`` cave, recomputes the table, strings and
        wrapper that these sides imply, and compares them and every repointed site to what is on
        disk. Reads only via ``struct`` + the section table, so it needs no disassembler."""
        located = find_section(data, _SECTION_NAME)
        if located is None:
            return [f"no {_SECTION_NAME} section: the file does not carry this patch"]
        section_va, section_off, _vsize = located

        problems: list[str] = []
        try:
            content, wrapper_va = self._compute_section(data, section_va)
            edits = self._edits(data, section_va, wrapper_va)
        except (ValueError, struct.error) as exc:
            return [f"cannot recompute the expected cave (wrong build?): {exc}"]

        got = bytes(data[section_off : section_off + len(content)])
        if got != content:
            problems.append(
                f"{_SECTION_NAME} does not match these {len(self.sides)} side(s) "
                f"(table, names or wrapper differ)"
            )

        for file_off, _old, new, note in edits:
            got = bytes(data[file_off : file_off + len(new)])
            if got != new:
                problems.append(f"{note} @0x{file_off:x}: expected {new.hex()}, got {got.hex()}")
        return problems

    @classmethod
    def detect(cls, data: bytes | bytearray) -> CahFactionsPatch | None:
        """Recognise this patch **and recover its sides** from ``data``.

        The default probe cannot: it builds the patch with no sides and asks :meth:`verify`, which
        answers "does this file carry *this* side list" - so a binary patched with any sides at all
        reports the patch as absent, which is the one case worth detecting. `getSideIndex`'s
        rewritten scan bound holds the entry count, and the cave opens with one name pointer per
        entry, so the names read straight back out: everything past the stock nine and ``All``,
        which the constructor re-adds. :meth:`verify` then re-checks all 30 sites against them."""
        located = find_section(data, _SECTION_NAME)
        if located is None:
            return None
        _section_va, section_off, _vsize = located
        try:
            bound_off = va_to_offset(data, _SCAN_BOUND_VA)
            if bound_off is None:
                return None
            # `cmp esi, <entry count>` - the bound this patch rewrote. A `.cahfac` section with a
            # stock bound still here reads as 9, which is one short of the `All` entry alone and
            # so falls outside the range below rather than being taken for a zero-side patch.
            entry_count = data[bound_off + 2]
            if not 0 <= entry_count - ALL_INDEX - 1 <= MAX_SIDES:
                return None
            pointers = struct.unpack_from(f"<{entry_count}I", data, section_off)
            sides: list[str] = []
            for pointer in pointers[ALL_INDEX + 1 :]:
                name = _read_cstring(data, pointer)
                if name is None:
                    return None
                sides.append(name)
            patch = cls(sides=sides)
        except (ValueError, IndexError, struct.error):
            return None
        return None if patch.verify(data) else patch

    @classmethod
    def add_cli_arguments(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--sides",
            default="",
            metavar="NAME[,NAME...]",
            help=(
                f"comma-separated mod side names to add (at most {MAX_SIDES}); each must match a "
                f"PlayerTemplate's Side string exactly. 'All' is always added."
            ),
        )

    @classmethod
    def from_cli_args(cls, args: argparse.Namespace) -> CahFactionsPatch:
        sides = [part.strip() for part in args.sides.split(",") if part.strip()]
        return cls(sides=sides)

    def _compute_section(self, data: bytes | bytearray, section_va: int) -> tuple[bytes, int]:
        """Return ``(section content, wrapper VA)`` for a cave based at ``section_va``.

        Layout: the superset pointer table, then the `All` and side name strings it points at,
        then the parser wrapper. The stock nine entries are copied through by pointer so they keep
        both their order and their original strings."""
        stock = self._read_stock_table(data)

        table_size = (self.entry_count + 1) * 4  # + NULL terminator
        strings_va = section_va + table_size

        blob = bytearray()
        new_ptrs: list[int] = []
        for name in (ALL_NAME, *self.sides):
            new_ptrs.append(strings_va + len(blob))
            blob += name.encode("ascii") + b"\x00"
        while len(blob) % 4:  # keep the wrapper dword-aligned
            blob += b"\x00"

        table = b"".join(_u32(p) for p in (*stock, *new_ptrs)) + _u32(0)
        assert len(table) == table_size

        wrapper_va = strings_va + len(blob)
        return bytes(table) + bytes(blob) + _wrapper_code(wrapper_va), wrapper_va

    def _read_stock_table(self, data: bytes | bytearray) -> tuple[int, ...]:
        """The nine stock name pointers, after checking they really are this build's side table
        (nine known names followed by a NULL terminator)."""
        off = va_to_offset(data, _SIDE_TABLE_VA)
        if off is None:
            raise ValueError(f"the side table VA 0x{_SIDE_TABLE_VA:08x} is not mapped")
        ptrs = struct.unpack_from(f"<{len(STOCK_SIDES) + 1}I", data, off)
        if ptrs[-1] != 0:
            raise ValueError(
                f"the side table is not NULL-terminated after {len(STOCK_SIDES)} entries "
                f"(found 0x{ptrs[-1]:08x})"
            )
        for ptr, expected in zip(ptrs, STOCK_SIDES, strict=False):
            got = _read_cstring(data, ptr)
            if got != expected:
                raise ValueError(f"unexpected build: side table has {got!r}, expected {expected!r}")
        return ptrs[:-1]

    def _edits(
        self, data: bytes | bytearray, section_va: int, wrapper_va: int
    ) -> list[tuple[int, bytes, bytes, str]]:
        """The 30 ``(file_offset, original bytes, patched bytes, note)`` edits that point the
        engine at the new table and wrapper. Shared by :meth:`apply` (writes ``patched`` if
        ``original`` matches) and :meth:`verify` (asserts ``patched`` is present); both derive
        every value from the constants above, so neither needs to read the sites first."""

        def offset(va: int) -> int:
            off = va_to_offset(data, va)
            if off is None:
                raise ValueError(f"VA 0x{va:08x} is not mapped")
            return off

        edits: list[tuple[int, bytes, bytes, str]] = []
        for va in _TABLE_REF_VAS:
            edits.append(
                (offset(va), _u32(_SIDE_TABLE_VA), _u32(section_va), f"table ref @0x{va:08x}")
            )
        for va in _TABLE_END_REF_VAS:
            edits.append(
                (
                    offset(va),
                    _u32(_SIDE_TABLE_VA + _TABLE_END_DELTA),
                    _u32(section_va + _TABLE_END_DELTA),
                    f"stock-eight loop bound @0x{va:08x}",
                )
            )
        edits.append(
            (
                offset(_DEFAULT_FACTION_USERDATA_VA),
                _u32(_INI_TABLE_VA),
                _u32(section_va),
                "DefaultFaction userData",
            )
        )
        edits.append(
            (
                offset(_USABLE_FACTIONS_PARSER_VA),
                _u32(_STOCK_PARSER_VA),
                _u32(wrapper_va),
                "UsableFactions parser -> wrapper",
            )
        )
        edits.append(
            (
                offset(_SCAN_BOUND_VA),
                b"\x83\xfe" + bytes([len(STOCK_SIDES)]),
                b"\x83\xfe" + bytes([self.entry_count]),
                "getSideIndex scan bound",
            )
        )
        return edits


# The Worldbuilder half.
#
# `Worldbuilder.exe` is an assert-enabled build of the same engine and it parses the same
# `CreateAHeroClass` blocks, out of its own copies of the side name table. Both copies are there,
# the same pair `game.dat` has: `0x02231FEC` is the code copy, and `0x0222F470` is the one the
# `DefaultFaction` field descriptor carries as `userData`.
#
# What the editor calls the enum is written in its own assert strings - `BitFlags<9,enum
# FactionType>`, `Source\Common/BitFlags.h` - and that `9` is baked into ten `cmp`s, so growing
# the table without raising them is worse than not growing it at all:
#
#     00b8a6d7  call 0x006cd120           ; INI::scanIndexListFromString -> index
#     00b8a6e2  cmp  dword [ebp-8], 9     ; BitFlags<9,FactionType>::SetBit's `bit < NUMBITS`
#     00b8a6e6  jb   0x00b8a743           ; >= 9 falls into the assert path
#
# The four that a parse reaches are `SetBit` (twice - the `+Name` and bare-name branches),
# `ClearBit` (the `-Name` branch) and `testNameArray`, which asserts the list holds **exactly**
# nine non-NULL names followed by a NULL - through a baked `cmp dword [0x02232010], 0`, so the
# terminator's address has to move with the table. The remaining five are
# `BitFlags<9,FactionType>::test`, the editor's readers of the mask, and they bound an index that
# only becomes reachable once the table is longer.
#
# Left alone, the failure is quiet rather than loud, which is the worse of the two.
# `INI::scanIndexListFromString` answers **0** for a name it cannot find, so `UsableFactions =
# Rohan` reads as `Men` and the editor carries on.
#
# The `All` bit needs no wrapper here. The game half wraps the field parser so that a set `All`
# bit expands to all ones; that is what the *gates* read, and the editor has none - it parses
# `UsableFactions` into a mask nothing in the editor tests against a side. So this cave is a
# pointer table and its strings, and no code.
#
# Scope: parsing only. The editor gains no Create-A-Hero behaviour and needs none.

#: The PE section name field is 8 bytes and truncates silently.
WORLDBUILDER_SECTION_NAME = ".cahfwb"

# CNT_INITIALIZED_DATA | MEM_READ - the cave is a pointer table and the name strings, and no code.
_WORLDBUILDER_CHARACTERISTICS = 0x40000040

#: Worldbuilder's code copy of the side name table, the one every site below reads.
WORLDBUILDER_TABLE_VA = 0x02231FEC

#: Its NULL terminator, `&table[9]`, which `testNameArray` checks through a baked absolute address
#: rather than by indexing the table it was just handed.
WORLDBUILDER_TERMINATOR_VA = WORLDBUILDER_TABLE_VA + len(STOCK_SIDES) * 4

#: The editor's second copy, and the `DefaultFaction` field descriptor's `userData` slot that is
#: its only reference - row 13 of the `SubClass` field-parse table at `0x0222F718`, so the slot is
#: in `.data` rather than `.text`. It is repointed at the same rebuilt table the code copy's
#: references get, exactly as the `game.dat` half folds its own two copies into one.
WORLDBUILDER_INI_TABLE_VA = 0x0222F470
WORLDBUILDER_DEFAULT_FACTION_USERDATA_VA = 0x0222F7F0

#: Every reference to the code copy, as ``(instruction VA, the bytes before its imm32/disp32)``.
#: Asserting the encoding as well as the address means a coincidental copy of the value elsewhere
#: cannot be mistaken for one of these.
#:
#: The first four are the `UsableFactions` parse path: the `+Name`, `-Name` and bare-name branches
#: push the table at `INI::scanIndexListFromString`, and `testNameArray` walks it. `0x00BF308C` is
#: the editor's `PlayerTemplate::getSideIndex`, `0x01006E53` its second name->index resolver. The
#: six in `0x0116…` are stats loops bounded by a hard-coded **8** and go on listing the same eight
#: sides; the rest read `table[i]` for a caller-supplied `i`. All of them see the same first nine
#: entries after the move, which is why only the parse path needs anything else done to it.
WORLDBUILDER_TABLE_REF_SITES = (
    (0x00B8A6CB, bytes.fromhex("68")),  # SetBit, `+Name`: push <table>
    (0x00B8A7B3, bytes.fromhex("68")),  # ClearBit, `-Name`: push <table>
    (0x00B8A8A7, bytes.fromhex("68")),  # SetBit, bare name: push <table>
    (0x00B8AA24, bytes.fromhex("833c8d")),  # testNameArray: cmp dword [ecx*4 + <table>], 0
    (0x00BF308C, bytes.fromhex("c745fc")),  # getSideIndex: mov [ebp-4], <table>
    (0x01006E53, bytes.fromhex("c745fc")),  # the second name->index resolver
    (0x01163793, bytes.fromhex("c745e8")),
    (0x01163853, bytes.fromhex("c745ec")),
    (0x01164DD9, bytes.fromhex("c745e8")),
    (0x01164F29, bytes.fromhex("c745ec")),
    (0x01165080, bytes.fromhex("c745e4")),
    (0x01165230, bytes.fromhex("c745e8")),
    (0x01414FF6, bytes.fromhex("c745ec")),
    (0x01415163, bytes.fromhex("8b0c85")),  # mov ecx, [eax*4 + <table>]
    (0x0151A9B1, bytes.fromhex("c74588")),
    (0x015C2C9E, bytes.fromhex("c745f0")),
    (0x015C2D47, bytes.fromhex("c745dc")),
    (0x015C4320, bytes.fromhex("c745e4")),
    (0x0160607E, bytes.fromhex("c745a0")),
    (0x016144BA, bytes.fromhex("c745e8")),
)

#: Every site holding `BitFlags<9,FactionType>`'s bit count, as ``(instruction VA, the bytes
#: before its imm8)``. All ten are `cmp <slot>, 9` and all ten become `cmp <slot>, <entry count>`;
#: the immediate stays one byte because `MAX_SIDES` caps the count at 32.
#:
#: `0x00BF30A5` is the editor's `getSideIndex` scan bound - the twin of `game.dat`'s `cmp esi, 9`
#: at `0x0073BDD1`, and like it the not-found answer just past it (`mov eax, 9`) is deliberately
#: left alone, so an unrecognised side still lands on `All`.
WORLDBUILDER_BOUND_SITES = (
    (0x00B820E9, bytes.fromhex("837d08")),  # BitFlags<9,FactionType>::test
    (0x00B8A6E2, bytes.fromhex("837df8")),  # SetBit, `+Name`
    (0x00B8A7CA, bytes.fromhex("837df4")),  # ClearBit, `-Name`
    (0x00B8A8BB, bytes.fromhex("837df0")),  # SetBit, bare name
    (0x00B8AA1B, bytes.fromhex("837dfc")),  # testNameArray's walk
    (0x00BF30A5, bytes.fromhex("837df8")),  # getSideIndex's scan bound
    (0x00D10C37, bytes.fromhex("83bda0f0ffff")),  # ::test
    (0x01356EAB, bytes.fromhex("837dd8")),  # ::test
    (0x014CAE69, bytes.fromhex("837df0")),  # ::test
    (0x014CE9EB, bytes.fromhex("837db4")),  # ::test
)

#: `testNameArray`'s terminator check, `cmp dword [<&table[9]>], 0`, and the bytes before its
#: disp32. It is the one site holding an address *into* the table rather than the table's base.
WORLDBUILDER_TERMINATOR_SITE = (0x00B8AA9C, bytes.fromhex("833d"))


class CahFactionsWorldbuilderPatch(Patch):
    """Teach **Worldbuilder** the same side names, so the editor can parse a mod that uses them.

    **This patch targets `Worldbuilder.exe`, not `game.dat`.** It is the authoring half of
    `cah-factions`: the game half adds the sides and the `All` semantics, this one only stops the
    editor mis-resolving and asserting on the names. Give both binaries the **same** `--sides`
    list in the **same order**, since what a resolved token becomes is an index.
    """

    name = "cah-factions-wb"
    author = "officialNecro"
    description = (
        "Worldbuilder.exe (not game.dat): add the same mod sides and 'All' token to the editor's "
        "own copies of the Create-A-Hero faction name table, so a SubClass naming them parses "
        "instead of resolving to Men and tripping BitFlags<9,FactionType>'s bit-count asserts. "
        "Pass the same --sides given to game.dat's cah-factions, in the same order"
    )

    def __init__(self, sides: list[str] | tuple[str, ...] = ()):
        self.sides = tuple(sides)
        validate_sides(self.sides)

    def __str__(self) -> str:
        listed = ", ".join(self.sides) if self.sides else "no extra sides"
        return f"{self.name} ({listed})"

    @property
    def entry_count(self) -> int:
        """Table entries the patch installs, excluding the NULL terminator, and the editor's new
        `BitFlags<9,FactionType>` bit count. The same number the game half writes into
        `getSideIndex`'s scan bound, because it is the same table."""
        return len(STOCK_SIDES) + 1 + len(self.sides)

    def apply(self, data: bytearray) -> None:
        check_not_rebased(data)
        stock = self._read_stock_table(data)
        section_va = allocate_section(
            data,
            WORLDBUILDER_SECTION_NAME,
            lambda base_va: self._content(base_va, stock),
            _WORLDBUILDER_CHARACTERISTICS,
        )
        for file_off, old, new, note in self._edits(data, section_va):
            apply_byte_patch(data, file_off, old, new, note)

    def verify(self, data: bytes | bytearray) -> list[str]:
        """Structural check that ``data`` already carries this patch for exactly these sides (an
        empty list == verified). Recomputes the cave these sides imply and compares it, and every
        repointed or rewritten site, against what is on disk."""
        located = find_section(data, WORLDBUILDER_SECTION_NAME)
        if located is None:
            return [f"no {WORLDBUILDER_SECTION_NAME} section: the file does not carry this patch"]
        section_va, section_off, _vsize = located

        problems: list[str] = []
        try:
            content = self._content(section_va, self._read_stock_table(data))
            edits = self._edits(data, section_va)
        except (ValueError, struct.error) as exc:
            return [f"cannot recompute the expected cave (wrong build?): {exc}"]

        got = bytes(data[section_off : section_off + len(content)])
        if got != content:
            problems.append(
                f"{WORLDBUILDER_SECTION_NAME} does not match these {len(self.sides)} side(s) "
                f"(table or names differ)"
            )
        for file_off, _old, new, note in edits:
            got = bytes(data[file_off : file_off + len(new)])
            if got != new:
                problems.append(f"{note} @0x{file_off:x}: expected {new.hex()}, got {got.hex()}")
        return problems

    @classmethod
    def detect(cls, data: bytes | bytearray) -> CahFactionsWorldbuilderPatch | None:
        """Recognise this patch **and recover its sides** from ``data``.

        The default probe builds the patch with no sides and asks :meth:`verify`, so an editor
        patched with any sides at all would read as unpatched - the one case worth detecting. The
        cave *is* the rebuilt table, so its entries past the stock nine and ``All`` are the names
        this patch added, and the constructor re-adds ``All``."""
        located = find_section(data, WORLDBUILDER_SECTION_NAME)
        if located is None:
            return None
        section_va, _section_off, _vsize = located
        try:
            pointers = read_terminated(
                data, section_va, "Worldbuilder side name table", limit=ALL_INDEX + MAX_SIDES + 2
            )
            if not ALL_INDEX + 1 <= len(pointers) <= ALL_INDEX + 1 + MAX_SIDES:
                return None
            sides: list[str] = []
            for pointer in pointers[ALL_INDEX + 1 :]:
                name = _read_cstring(data, pointer)
                if name is None:
                    return None
                sides.append(name)
            patch = cls(sides=sides)
        except (ValueError, IndexError, struct.error):
            return None
        return None if patch.verify(data) else patch

    @classmethod
    def add_cli_arguments(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--sides",
            default="",
            metavar="NAME[,NAME...]",
            help=(
                f"comma-separated mod side names to add (at most {MAX_SIDES}); pass the same list "
                "in the same order as game.dat's cah-factions, since a token resolves to an "
                "index. 'All' is always added."
            ),
        )

    @classmethod
    def from_cli_args(cls, args: argparse.Namespace) -> CahFactionsWorldbuilderPatch:
        sides = [part.strip() for part in args.sides.split(",") if part.strip()]
        return cls(sides=sides)

    def _read_stock_table(self, data: bytes | bytearray) -> tuple[int, ...]:
        """The editor's nine stock name pointers, after checking that **both** copies really are
        this build's side table. Both are read because one rebuilt table replaces both: a build
        where they had drifted apart needs more than one cave, and finding that out here is better
        than silently handing `DefaultFaction` the code copy's strings."""
        stock: tuple[int, ...] = ()
        for base_va, what in (
            (WORLDBUILDER_TABLE_VA, "code copy"),
            (WORLDBUILDER_INI_TABLE_VA, "DefaultFaction userData copy"),
        ):
            pointers = read_terminated(data, base_va, f"Worldbuilder side table ({what})")
            if len(pointers) != len(STOCK_SIDES):
                raise ValueError(
                    f"the Worldbuilder side table ({what}) at 0x{base_va:08x} holds "
                    f"{len(pointers)} names, expected the stock {len(STOCK_SIDES)}"
                )
            for index, expected in enumerate(STOCK_SIDES):
                got = _read_cstring(data, pointers[index])
                if got != expected:
                    raise ValueError(
                        f"unexpected build: the Worldbuilder side table ({what}) has {got!r} at "
                        f"index {index}, expected {expected!r}"
                    )
            if base_va == WORLDBUILDER_TABLE_VA:
                stock = pointers
        return stock

    def _content(self, base_va: int, stock: tuple[int, ...]) -> bytes:
        """The cave: the superset pointer table, then the `All` and side name strings it points
        at. The stock nine are copied through **by pointer**, so they keep both their indices and
        their original strings, and `All` lands at `ALL_INDEX` exactly as it does in `game.dat`."""
        content, _name_vas, _end_va = layout(stock, (ALL_NAME, *self.sides), base_va)
        return content

    def _edits(
        self, data: bytes | bytearray, section_va: int
    ) -> list[tuple[int, bytes, bytes, str]]:
        """The 32 ``(file offset, original bytes, patched bytes, note)`` edits: twenty-one
        references to the two stock tables, ten bit-count bounds, and `testNameArray`'s terminator
        address. Shared by :meth:`apply` (writes ``patched`` when ``original`` matches) and
        :meth:`verify` (asserts ``patched`` is present); both derive every value from the
        constants above, so neither has to read the sites first."""

        def offset(va: int) -> int:
            off = va_to_offset(data, va)
            if off is None:
                raise ValueError(f"VA 0x{va:08x} is not mapped")
            return off

        edits: list[tuple[int, bytes, bytes, str]] = []
        for va, prefix in WORLDBUILDER_TABLE_REF_SITES:
            edits.append(
                (
                    offset(va),
                    prefix + _u32(WORLDBUILDER_TABLE_VA),
                    prefix + _u32(section_va),
                    f"Worldbuilder side table ref @0x{va:08x}",
                )
            )
        edits.append(
            (
                offset(WORLDBUILDER_DEFAULT_FACTION_USERDATA_VA),
                _u32(WORLDBUILDER_INI_TABLE_VA),
                _u32(section_va),
                "Worldbuilder DefaultFaction userData",
            )
        )
        for va, prefix in WORLDBUILDER_BOUND_SITES:
            edits.append(
                (
                    offset(va),
                    prefix + bytes([len(STOCK_SIDES)]),
                    prefix + bytes([self.entry_count]),
                    f"Worldbuilder FactionType bit count @0x{va:08x}",
                )
            )
        terminator_va, terminator_prefix = WORLDBUILDER_TERMINATOR_SITE
        edits.append(
            (
                offset(terminator_va),
                terminator_prefix + _u32(WORLDBUILDER_TERMINATOR_VA),
                terminator_prefix + _u32(section_va + self.entry_count * 4),
                "Worldbuilder testNameArray terminator",
            )
        )
        return edits
