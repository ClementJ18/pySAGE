"""Primitives shared by every patch that appends a name to one of the engine's global tables.

The SAGE INI parser resolves a token to a number by walking a NULL-terminated ``const char*[]``
with `stricmp` (`INI::scanIndexList`, ``0x0042B914``). Three of those tables are interesting to a
mod - `ModelConditionFlags`, `WeaponSetFlags`, `LocomotorSetType` - and adding a name to any of
them is the same three moves:

1. **read the live table**, wherever the image's references currently point and however many
   entries it currently has, rather than assuming the stock base and count;
2. **rebuild it into a cave**, copying the existing entries through *by pointer* so every name
   already there keeps both its index and its original string;
3. **repoint every reference** - they are bare imm32/disp32 operands, so a table cannot grow in
   place and each site has to be found and rewritten.

Doing it from the live image rather than from stock constants is what makes two such patches
compose in either order: applied second, a patch appends to whatever the first one left behind
instead of dropping its name. :mod:`.model_conditions`, :mod:`.weapon_set_flags` and
:mod:`.locomotor_sets` are the three tables' owners; everything generic to all three is here.

What is *not* here is the per-table question of whether a **count** has to move with the table.
`ModelConditionFlags` bakes its count into ten loop bounds and needs all ten; the other two are
read only through the terminator and need none. That difference is the whole reason each table
keeps its own module.
"""

from __future__ import annotations

import re
import struct
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from ...utils import va_to_offset

__all__ = [
    "SECTION_CHARACTERISTICS",
    "NameTable",
    "check_fingerprint",
    "layout",
    "offset",
    "read_cstring",
    "read_terminated",
    "ref_edits",
    "resolve_base",
    "validate_name",
]

# CNT_CODE | CNT_INITIALIZED_DATA | MEM_EXECUTE | MEM_READ - a cave holds a table, the name
# strings and (usually) hook code, so it must be executable as well as readable.
SECTION_CHARACTERISTICS = 0x60000060

#: The engine's own names are uppercase with underscores and digits; the INI parser resolves the
#: token by exact compare, so anything else would simply never match a real INI file.
_NAME_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]*$")


def _u32(value: int) -> bytes:
    return struct.pack("<I", value)


def offset(data: bytes | bytearray, va: int) -> int:
    off = va_to_offset(data, va)
    if off is None:
        raise ValueError(f"VA 0x{va:08x} is not mapped")
    return off


def read_cstring(data: bytes | bytearray, va: int, limit: int = 64) -> str | None:
    off = va_to_offset(data, va)
    if off is None:
        return None
    end = bytes(data[off : off + limit]).find(b"\x00")
    return None if end < 0 else bytes(data[off : off + end]).decode("latin1")


def validate_name(name: str, what: str = "condition name") -> None:
    """Raise unless ``name`` is a token the engine's INI parser could ever match."""
    if not _NAME_PATTERN.match(name):
        raise ValueError(
            f"{what} must be uppercase letters, digits and underscores starting with "
            f"a letter (the INI parser matches it by exact compare), got {name!r}"
        )


@dataclass(frozen=True)
class NameTable:
    """One of the engine's name tables as the image currently holds it."""

    base_va: int
    #: One name pointer per named entry, in index order. The NULL terminator is not included.
    pointers: tuple[int, ...]

    @property
    def count(self) -> int:
        return len(self.pointers)

    def index_of(self, data: bytes | bytearray, name: str) -> int | None:
        """The index ``name`` is, or None if the table does not name it."""
        for index, pointer in enumerate(self.pointers):
            if read_cstring(data, pointer) == name:
                return index
        return None


def resolve_base(data: bytes | bytearray, ref_vas: Sequence[int], what: str) -> int:
    """The base VA every reference in ``ref_vas`` holds, or raise if they disagree.

    Disagreement means either a build these addresses were not derived against or a half-applied
    patch, and both should stop a patch rather than let it write."""
    bases = {va: struct.unpack_from("<I", data, offset(data, va))[0] for va in ref_vas}
    if len(set(bases.values())) != 1:
        disagreement = ", ".join(f"0x{va:08x}->0x{base:08x}" for va, base in bases.items())
        raise ValueError(f"the {len(ref_vas)} {what} refs disagree: {disagreement}")
    return next(iter(bases.values()))


def read_terminated(
    data: bytes | bytearray, base_va: int, what: str, limit: int = 1024
) -> tuple[int, ...]:
    """The name pointers of the NULL-terminated table at ``base_va``, terminator excluded."""
    off = offset(data, base_va)
    pointers: list[int] = []
    for index in range(limit):
        pointer = struct.unpack_from("<I", data, off + index * 4)[0]
        if pointer == 0:
            return tuple(pointers)
        pointers.append(pointer)
    raise ValueError(f"the {what} at 0x{base_va:08x} is not NULL-terminated within {limit} entries")


def check_fingerprint(
    data: bytes | bytearray,
    pointers: Sequence[int],
    fingerprint: Mapping[int, str],
    what: str,
) -> None:
    """Raise unless the table names what it should at the fingerprint indices.

    Names at a handful of known indices identify a build far more tightly than a count does, and
    every index is below the stock count, so the check keeps working once the table has grown."""
    for index, want in fingerprint.items():
        got = read_cstring(data, pointers[index]) if index < len(pointers) else None
        if got != want:
            raise ValueError(f"unexpected build: {what} {index} is {got!r}, expected {want!r}")


def layout(
    pointers: Sequence[int], new_names: Sequence[str], base_va: int
) -> tuple[bytes, tuple[int, ...], int]:
    """A rebuilt table at ``base_va``: ``(bytes, the new names' VAs, the VA just past it)``.

    Order is the pointer array (existing, then new, then the terminator), then the new name
    strings, padded so that whatever a caller places after them stays dword-aligned."""
    table_size = (len(pointers) + len(new_names) + 1) * 4

    strings = bytearray()
    name_vas: list[int] = []
    for name in new_names:
        name_vas.append(base_va + table_size + len(strings))
        strings += name.encode("ascii") + b"\x00"
    strings += b"\x00" * (-len(strings) % 4)

    array = b"".join(_u32(p) for p in (*pointers, *name_vas)) + _u32(0)
    assert len(array) == table_size
    return array + bytes(strings), tuple(name_vas), base_va + table_size + len(strings)


def ref_edits(
    data: bytes | bytearray,
    ref_vas: Sequence[int],
    old_base_va: int,
    new_base_va: int,
    what: str,
) -> list[tuple[int, bytes, bytes, str]]:
    """The ``(file offset, original bytes, patched bytes, note)`` edits repointing every
    reference from ``old_base_va`` to the rebuilt table at ``new_base_va``."""
    return [
        (offset(data, va), _u32(old_base_va), _u32(new_base_va), f"{what} ref @0x{va:08x}")
        for va in ref_vas
    ]
