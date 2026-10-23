"""Add `DamageSubType` names, for `DamageFilteredCreateObjectDie` to trigger on.

A damage nugget's `DamageSubType` tags the victim, and a `DamageFilteredCreateObjectDie` runs its
OCL when the object dies tagged with the subtype its `DamageTypeTriggersInstantly` (or, within
`PostFilterTriggeredDuration`, its `DamageTypeTriggersForDuration`) names. Stock has four
subtypes and every one already means something, so a mod-defined effect-on-death has nothing free
to use. The patch relocates the name table into a cave with new names appended; the subtype is an
`int` everywhere it travels, so nothing else has to move. `DamageSubtypesWorldbuilderPatch`
teaches the editor the same tokens.

**Index 4 is reserved.** The module's data constructor (`0x008891DD`) defaults both trigger
fields to `4`, one past the last stock name, meaning "no trigger". A name at 4 would make every
module that leaves a trigger unset fire on it, so slot 4 holds a string no INI token can equal and
the new names start at 5.

Derivation: `../docs/damage-subtypes.md`.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sage_ini.engine import Engine, EnumDelta

from ..patcher import Patch
from ..utils import allocate_section, apply_byte_patch, file_offset, find_section, u32
from .utils import name_tables

if TYPE_CHECKING:
    import argparse

__all__ = [
    "DEFAULT_NAMES",
    "FIRST_NEW_INDEX",
    "GAME",
    "RESERVED_NAME",
    "SECTION_NAME",
    "STOCK_NAMES",
    "WORLDBUILDER",
    "WORLDBUILDER_SECTION_NAME",
    "DamageSubtypesPatch",
    "DamageSubtypesWorldbuilderPatch",
]


#: The stock subtype names, in index order. `SELF` is set by the engine itself on self and
#: lifetime kills, and `BECOME_UNDEAD_ONCE` carries a hard-coded 5-frame throttle per source
#: (`0x00889141`); new indices have neither.
STOCK_NAMES = ("NORMAL", "BECOME_UNDEAD", "SELF", "BECOME_UNDEAD_ONCE")

#: What slot 4 points at. It contains a space, and the INI tokenizer splits on whitespace, so no
#: token can ever equal it: the slot is held without being nameable.
RESERVED_NAME = "(no trigger)"

#: The index the first new name takes: past the stock names and the reserved slot.
FIRST_NEW_INDEX = len(STOCK_NAMES) + 1

DEFAULT_NAMES = tuple(f"CUSTOM_{n}" for n in range(1, 9))

#: The PE section name field is 8 bytes and truncates silently.
SECTION_NAME = ".dmgsub"
WORLDBUILDER_SECTION_NAME = ".wbdmgsb"

# CNT_INITIALIZED_DATA | MEM_READ - a pointer table and its strings, no code.
_CHARACTERISTICS = 0x40000040


@dataclass(frozen=True)
class _Target:
    """Where one binary keeps the subtype name table and what reads it.

    The header declaring the table is compiled into many units, so each binary holds a dozen
    identical copies; only the ones below are read, each through the `userData` slot of an INI
    field descriptor (`{name, parseFn, userData, offset}`, parsed by the index-list parser). No
    code references any copy."""

    binary: str
    #: `(userData slot VA, the stock table it points at)`.
    refs: tuple[tuple[int, int], ...]


GAME = _Target(
    "game.dat",
    (
        (0x00C7B088, 0x00DB5D9C),  # DamageNugget DamageSubType, nugget +0x184
        (0x00C613F0, 0x00DAF5CC),  # DamageFilteredCreateObjectDie ...TriggersInstantly, +0x3C
        (0x00C61400, 0x00DAF5CC),  # ... DamageTypeTriggersForDuration, +0x40
    ),
)

WORLDBUILDER = _Target(
    "Worldbuilder.exe",
    (
        (0x01F1D768, 0x02236B8C),  # DamageNugget DamageSubType, nugget +0x184
        (0x01F3B500, 0x02239784),  # DamageFilteredCreateObjectDie DamageTypeTriggersInstantly
        (0x01F3B510, 0x02239784),  # ... DamageTypeTriggersForDuration
    ),
)


def _validate(names: tuple[str, ...]) -> None:
    if not names:
        raise ValueError("damage-subtypes needs at least one name to add")
    for name in names:
        name_tables.validate_name(name, "damage subtype name")
    taken = set(STOCK_NAMES)
    for name in names:
        if name in taken:
            raise ValueError(f"{name!r} is already a damage subtype name, or repeated")
        taken.add(name)


def _stock_pointers(data: bytes | bytearray, target: _Target) -> tuple[int, ...]:
    """The stock name pointers, after checking every slot still points at a stock table that
    names exactly the four stock subtypes."""
    pointers: tuple[int, ...] | None = None
    for slot_va, table_va in target.refs:
        got = struct.unpack_from("<I", data, name_tables.offset(data, slot_va))[0]
        if got != table_va:
            raise ValueError(
                f"the DamageSubType userData slot @0x{slot_va:08x} holds 0x{got:08x}, not the "
                f"stock table 0x{table_va:08x} - not the expected {target.binary}, or already "
                "patched"
            )
        table = name_tables.read_terminated(data, table_va, "DamageSubType table")
        names = tuple(name_tables.read_cstring(data, p) for p in table)
        if names != STOCK_NAMES:
            raise ValueError(
                f"unexpected build: the DamageSubType table at 0x{table_va:08x} reads "
                f"{list(names)}, expected {list(STOCK_NAMES)}"
            )
        pointers = pointers or table
    assert pointers is not None
    return pointers


def _table(stock: tuple[int, ...], names: tuple[str, ...], base_va: int) -> bytes:
    """The relocated table: the stock pointers reused as-is, so every stock name keeps its index
    and its original string; the reserved slot; the new names; the NULL; then the strings."""
    blob, _name_vas, _end = name_tables.layout(stock, (RESERVED_NAME, *names), base_va)
    return blob


def _read_names(data: bytes | bytearray, base_va: int) -> list[str | None]:
    pointers = name_tables.read_terminated(data, base_va, "DamageSubType table", limit=256)
    return [name_tables.read_cstring(data, p) for p in pointers]


def _apply(data: bytearray, target: _Target, section: str, names: tuple[str, ...]) -> None:
    name_tables.check_not_rebased(data)
    stock = _stock_pointers(data, target)
    section_va = allocate_section(
        data, section, lambda base_va: _table(stock, names, base_va), _CHARACTERISTICS
    )
    for slot_va, table_va in target.refs:
        apply_byte_patch(
            data,
            file_offset(data, slot_va),
            u32(table_va),
            u32(section_va),
            f"DamageSubType userData slot @0x{slot_va:08x} -> {section}",
        )


def _verify(
    data: bytes | bytearray, target: _Target, section: str, names: tuple[str, ...]
) -> list[str]:
    located = find_section(data, section)
    if located is None:
        return [f"no {section} section: the file does not carry this patch"]
    section_va = located[0]
    try:
        got = _read_names(data, section_va)
    except (ValueError, struct.error) as exc:
        return [f"cannot read back the {section} table (wrong build?): {exc}"]

    problems: list[str] = []
    want = [*STOCK_NAMES, RESERVED_NAME, *names]
    if got != want:
        problems.append(f"the DamageSubType table in {section} reads {got}, expected {want}")
    for slot_va, _table_va in target.refs:
        slot = struct.unpack_from("<I", data, file_offset(data, slot_va))[0]
        if slot != section_va:
            problems.append(
                f"DamageSubType userData slot @0x{slot_va:08x} points at 0x{slot:08x}, not the "
                f"patched table at 0x{section_va:08x}"
            )
    return problems


def _detect_names(data: bytes | bytearray, section: str) -> tuple[str, ...] | None:
    """The names a cave was built with, read from the table itself: whatever follows the stock
    names and the reserved slot."""
    located = find_section(data, section)
    if located is None:
        return None
    try:
        got = _read_names(data, located[0])
    except (ValueError, struct.error):
        return None
    head = [*STOCK_NAMES, RESERVED_NAME]
    if got[: len(head)] != head or len(got) == len(head) or None in got:
        return None
    return tuple(name for name in got[len(head) :] if name is not None)


def _add_names_argument(parser: argparse.ArgumentParser, other: str) -> None:
    parser.add_argument(
        "--names",
        default=",".join(DEFAULT_NAMES),
        metavar="NAME[,NAME...]",
        help=(
            f"comma-separated DamageSubType names to add, taking indices {FIRST_NEW_INDEX} "
            f"upward in order (default {','.join(DEFAULT_NAMES)}). Uppercase letters, digits and "
            f"underscores. Give {other} the same list in the same order: parsed data stores the "
            "index a name resolved to"
        ),
    )


def _names_from(args: argparse.Namespace) -> tuple[str, ...]:
    return tuple(part.strip() for part in args.names.split(",") if part.strip())


class DamageSubtypesPatch(Patch):
    """Append `DamageSubType` names for nuggets to tag with and the filtered die module to match."""

    name = "damage-subtypes"
    author = "officialNecro"
    description = (
        "Add DamageSubType names (default CUSTOM_1..CUSTOM_8, indices 5..12) for a damage "
        "nugget's DamageSubType and DamageFilteredCreateObjectDie's DamageTypeTriggersInstantly "
        "/ DamageTypeTriggersForDuration, so a mod can define its own effects-on-death. New "
        "subtypes carry none of the engine's special cases (SELF, BECOME_UNDEAD_ONCE's throttle)"
    )

    def __init__(self, names: tuple[str, ...] = DEFAULT_NAMES):
        self.names = tuple(names)
        _validate(self.names)

    def __str__(self) -> str:
        return f"{self.name} ({', '.join(self.names)})"

    def apply(self, data: bytearray) -> None:
        _apply(data, GAME, SECTION_NAME, self.names)

    def verify(self, data: bytes | bytearray) -> list[str]:
        return _verify(data, GAME, SECTION_NAME, self.names)

    @classmethod
    def detect(cls, data: bytes | bytearray) -> DamageSubtypesPatch | None:
        """Recognise this patch **and recover the names it was applied with** from its table."""
        names = _detect_names(data, SECTION_NAME)
        if names is None:
            return None
        try:
            patch = cls(names)
        except ValueError:
            return None
        return None if patch.verify(data) else patch

    def ini_surface(self) -> Engine:
        """The names, at the indices the relocated table gives them."""
        return Engine(
            enum_members=tuple(
                EnumDelta("DamageSubType", name, FIRST_NEW_INDEX + i, self.name)
                for i, name in enumerate(self.names)
            )
        )

    @classmethod
    def add_cli_arguments(cls, parser: argparse.ArgumentParser) -> None:
        _add_names_argument(parser, "Worldbuilder's damage-subtypes-wb")

    @classmethod
    def from_cli_args(cls, args: argparse.Namespace) -> DamageSubtypesPatch:
        return cls(_names_from(args))


class DamageSubtypesWorldbuilderPatch(Patch):
    """Teach Worldbuilder's INI parser the same `DamageSubType` names.

    **This patch targets `Worldbuilder.exe`, not `game.dat`.** The editor loads the same objects
    and weapons and throws on a token its own copy of the table does not hold.
    """

    name = "damage-subtypes-wb"
    author = "officialNecro"
    description = (
        "Worldbuilder.exe (not game.dat): add the DamageSubType names damage-subtypes adds, so "
        "the editor still loads INI that uses them. Pass the same --names list, in the same order"
    )

    def __init__(self, names: tuple[str, ...] = DEFAULT_NAMES):
        self.names = tuple(names)
        _validate(self.names)

    def __str__(self) -> str:
        return f"{self.name} ({', '.join(self.names)})"

    def apply(self, data: bytearray) -> None:
        _apply(data, WORLDBUILDER, WORLDBUILDER_SECTION_NAME, self.names)

    def verify(self, data: bytes | bytearray) -> list[str]:
        return _verify(data, WORLDBUILDER, WORLDBUILDER_SECTION_NAME, self.names)

    @classmethod
    def detect(cls, data: bytes | bytearray) -> DamageSubtypesWorldbuilderPatch | None:
        names = _detect_names(data, WORLDBUILDER_SECTION_NAME)
        if names is None:
            return None
        try:
            patch = cls(names)
        except ValueError:
            return None
        return None if patch.verify(data) else patch

    @classmethod
    def add_cli_arguments(cls, parser: argparse.ArgumentParser) -> None:
        _add_names_argument(parser, "game.dat's damage-subtypes")

    @classmethod
    def from_cli_args(cls, args: argparse.Namespace) -> DamageSubtypesWorldbuilderPatch:
        return cls(_names_from(args))
