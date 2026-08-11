"""The `DESERT` weather in Worldbuilder's map-settings dropdown.

**This patch targets `Worldbuilder.exe`, not `game.dat`** - the only one in this package that does.
It is the authoring half of `desert-weather`; see ``../docs/desert-weather.md`` §9 for the
derivation. Build `2.01.2614.37001`'s Worldbuilder, ImageBase ``0x400000``.

**Why a second binary needs patching at all.** A map does not carry its weather as INI. The
`WorldInfo` chunk holds an `Integer` property named ``weather``, and both binaries copy it straight
into `GlobalData+0x138` with no range check (`game.dat` at ``0x004AB7E0``, Worldbuilder at
``0x0076E44D``); Worldbuilder writes it back out on save through `Dict::setInt` at ``0x0066ECE4``.
So the *data* path already accepts a third weather, and a map edited by any other means works on a
patched `game.dat` with nothing done here.

What does not accept it is the map-settings dialog. Its ``&Weather:`` combo (control ``0x4F5``) is
filled by a loop with a **hardcoded bound** rather than by walking the table's NULL terminator:

```
0056b97e  mov dword [ebp-0x20], 0
0056b990  cmp dword [ebp-0x20], 2      ; the stock member count, baked in
0056b994  jge done
0056b999  mov edx, [ecx*4 + 0x02231FB0]
0056b9af  push 0x143                   ; CB_ADDSTRING
0056b9c3  done:
0056b9dd  push 0x14e                   ; CB_SETCURSEL <- GlobalData+0x138
```

**And leaving it alone is not neutral - it is destructive.** `CB_SETCURSEL(2)` on a two-item combo
returns `CB_ERR` *and clears the selection*, so `CB_GETCURSEL` answers ``-1`` and the OK handler
stores that unvalidated:

```
0056c63e  push 0x147                   ; CB_GETCURSEL
0056c66b  mov [TheWritableGlobalData+0x138], eax
```

which the save path then writes back into the map. Opening the map settings on a `DESERT` map and
pressing OK silently reverts it. Raising the one immediate is what stops that, and the OK handler
needs no change at all - it already stores whatever index the combo reports.

**Scope.** The dropdown only. Worldbuilder resolves model conditions the way the game does
(``0x00CEBF4C`` gates on `ForceModelsToFollowWeather`, then ``cmp +0x138, 1`` for bit 8; also
``0x00928EC8``, ``0x0092952B``, ``0x0064F953``), so the editor **viewport** keeps drawing the
non-`SAND` variant until Worldbuilder's own model-condition table is extended too. That is
cosmetic inside the editor: the map data and the game are unaffected.

**Absolute pointers in the cave.** The relocated table holds absolute string addresses with no
entries in `.reloc`, which is only safe because the image is not rebased. Worldbuilder is
``RELOCS_STRIPPED=False`` and *does* ship a base-relocation directory, unlike `game.dat`, so
:meth:`apply` asserts `DYNAMIC_BASE` is clear rather than assuming it.

**Composition.** Nothing else in this package touches Worldbuilder, so ordering is moot; the cave
is still allocated with :func:`~sage_patch.utils.allocate_section` and found by name, so a future
Worldbuilder patch composes with it.
"""

from __future__ import annotations

import struct
from typing import TYPE_CHECKING

from ..patcher import Patch
from ..utils import allocate_section, apply_byte_patch, find_section, va_to_offset
from .utils.model_conditions import read_cstring, validate_name

if TYPE_CHECKING:
    import argparse

__all__ = ["DEFAULT_WEATHER", "STOCK_WEATHER_NAMES", "DesertWeatherWorldbuilderPatch"]


#: Worldbuilder's copy of the global weather name table: ``{"NORMAL", "SNOWY", NULL}``. The NULL
#: is at ``0x02231FB8`` and ``0x02231FBC`` is already `ARMY`, the first entry of the
#: `LivingWorldObjectType` table - so there is no room to grow it in place, exactly as in
#: `game.dat`.
WEATHER_TABLE_VA = 0x02231FB0
STOCK_WEATHER_NAMES = ("NORMAL", "SNOWY")

#: Every reference to it, as ``(instruction VA, the bytes before its imm32)``. Asserting the
#: encoding as well as the value means a coincidental copy of the address in a different build
#: cannot be mistaken for one of these. The two zero-length prefixes are `userData` slots in INI
#: field descriptors, which are data rather than code.
WEATHER_TABLE_REF_SITES = (
    (0x0056B999, bytes.fromhex("8b148d")),  # the combo loop: mov edx, [ecx*4 + <table>]
    (0x0090D2EB, bytes.fromhex("68")),  # a WeatherTexture field parser: push <table>
    (0x0095DAFB, bytes.fromhex("68")),  # the second WeatherTexture field parser
    (0x01E70E20, b""),  # field descriptor: FX nugget `Weather`, offset 0x140
    (0x01E86B88, b""),  # field descriptor: `GameData` `Weather`, offset 0x138
)

#: The combo-population loop's bound: ``cmp dword [ebp-0x20], 2``, an `imm8`.
COMBO_BOUND_VA = 0x0056B990
_COMBO_BOUND_PREFIX = bytes.fromhex("837de0")

#: Two window messages that pin the loop to the combo box it fills, so the `cmp` above cannot be
#: some other comparison that happens to encode the same way. ``0x143`` is `CB_ADDSTRING` (inside
#: the loop) and ``0x14E`` is `CB_SETCURSEL` (just past it, preselecting the map's weather).
_DIALOG_FINGERPRINT = {
    0x0056B9AF: bytes.fromhex("6843010000"),  # push 0x143
    0x0056B9DD: bytes.fromhex("684e010000"),  # push 0x14e
}

#: PE `DllCharacteristics` bit that would let the loader rebase the image out from under the
#: absolute pointers the cave's table holds.
_DYNAMIC_BASE = 0x0040

_SECTION_NAME = ".wbdsrt"
# CNT_INITIALIZED_DATA | MEM_READ - the cave is a pointer table and a string, and no code, so it
# does not need to be executable.
_SECTION_CHARACTERISTICS = 0x40000040

DEFAULT_WEATHER = "DESERT"


def _u32(value: int) -> bytes:
    return struct.pack("<I", value)


def _offset(data: bytes | bytearray, va: int) -> int:
    off = va_to_offset(data, va)
    if off is None:
        raise ValueError(f"VA 0x{va:08x} is not mapped")
    return off


class DesertWeatherWorldbuilderPatch(Patch):
    """Teach Worldbuilder's map-settings weather dropdown a third member."""

    name = "desert-weather-wb"
    author = "officialNecro"
    description = (
        "Worldbuilder.exe (not game.dat): add DESERT to the map-settings weather dropdown, so a "
        "map can be authored with it and the dialog stops reverting it"
    )

    def __init__(self, weather: str = DEFAULT_WEATHER):
        self.weather = weather
        validate_name(self.weather)

    def __str__(self) -> str:
        return f"{self.name} ({self.weather})"

    def apply(self, data: bytearray) -> None:
        self._check_not_rebased(data)
        self._check_dialog(data)
        stock = self._check_weather_table(data)

        section_va = allocate_section(
            data,
            _SECTION_NAME,
            lambda base_va: self._table(base_va, stock),
            _SECTION_CHARACTERISTICS,
        )
        for file_off, old, new, note in self._edits(data, section_va):
            apply_byte_patch(data, file_off, old, new, note)

    def verify(self, data: bytes | bytearray) -> list[str]:
        located = find_section(data, _SECTION_NAME)
        if located is None:
            return [f"no {_SECTION_NAME} section: the file does not carry this patch"]
        section_va, _section_off, _vsize = located

        problems: list[str] = []
        try:
            names = self._read_weather_table(data, section_va)
            edits = self._edits(data, section_va)
        except (ValueError, struct.error) as exc:
            return [f"cannot read back the {_SECTION_NAME} cave (wrong build?): {exc}"]

        if names != [*STOCK_WEATHER_NAMES, self.weather]:
            problems.append(
                f"the weather table in {_SECTION_NAME} reads {names}, expected "
                f"{[*STOCK_WEATHER_NAMES, self.weather]}"
            )
        for file_off, _old, new, note in edits:
            got = bytes(data[file_off : file_off + len(new)])
            if got != new:
                problems.append(f"{note} @0x{file_off:x}: expected {new.hex()}, got {got.hex()}")
        return problems

    @classmethod
    def add_cli_arguments(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--weather",
            default=DEFAULT_WEATHER,
            metavar="NAME",
            help=(
                f"name of the weather token to add (default {DEFAULT_WEATHER}); must match the "
                "one given to the game.dat `desert-weather` patch, since the map stores the index"
            ),
        )

    @classmethod
    def from_cli_args(cls, args: argparse.Namespace) -> DesertWeatherWorldbuilderPatch:
        return cls(weather=args.weather)

    def _table(self, base_va: int, stock: tuple[int, ...]) -> bytes:
        """The relocated table: the stock name pointers reused as-is - so ``NORMAL`` and ``SNOWY``
        keep both their indices and their original strings - then the new name, then the NULL.
        The dropdown's order is the table's order, and the *index* is what a map stores, so
        appending rather than inserting is what keeps existing maps meaning what they meant."""
        name = self.weather.encode("ascii") + b"\x00"
        name += b"\x00" * (-len(name) % 4)
        name_va = base_va + (len(stock) + 2) * 4
        return b"".join(_u32(p) for p in (*stock, name_va)) + _u32(0) + name

    def _edits(
        self, data: bytes | bytearray, section_va: int
    ) -> list[tuple[int, bytes, bytes, str]]:
        """The six ``(file offset, original bytes, patched bytes, note)`` edits: five references
        to the table, and the loop bound that decides how many of its entries reach the dropdown.
        Shared by :meth:`apply` (writes ``patched`` when ``original`` matches) and :meth:`verify`
        (asserts ``patched`` is present)."""
        edits: list[tuple[int, bytes, bytes, str]] = []
        for va, prefix in WEATHER_TABLE_REF_SITES:
            edits.append(
                (
                    _offset(data, va),
                    prefix + _u32(WEATHER_TABLE_VA),
                    prefix + _u32(section_va),
                    f"weather name table ref @0x{va:08x}",
                )
            )
        stock, patched = len(STOCK_WEATHER_NAMES), len(STOCK_WEATHER_NAMES) + 1
        edits.append(
            (
                _offset(data, COMBO_BOUND_VA),
                _COMBO_BOUND_PREFIX + bytes([stock]),
                _COMBO_BOUND_PREFIX + bytes([patched]),
                f"map-settings weather combo bound @0x{COMBO_BOUND_VA:08x}",
            )
        )
        return edits

    @staticmethod
    def _check_not_rebased(data: bytes | bytearray) -> None:
        """Raise if the loader could move the image. The cave's table holds absolute pointers with
        no base-relocation entries covering them, so a rebased image would index strings that are
        no longer there."""
        e_lfanew = struct.unpack_from("<I", data, 0x3C)[0]
        opt = e_lfanew + 24
        dll_characteristics = struct.unpack_from("<H", data, opt + 70)[0]
        if dll_characteristics & _DYNAMIC_BASE:
            raise ValueError(
                "the image opts in to ASLR (DllCharacteristics DYNAMIC_BASE), so the absolute "
                "pointers this patch writes into its cave would need base-relocation entries - "
                "refusing rather than writing a table that breaks when the image is rebased"
            )

    @staticmethod
    def _check_dialog(data: bytes | bytearray) -> None:
        """Raise unless the two window messages that bracket the combo-population loop are still
        where they should be. The bound being patched is an ordinary `cmp` against a small
        constant; without this, the same encoding somewhere else in a different build would be
        indistinguishable from it."""
        for va, expected in _DIALOG_FINGERPRINT.items():
            off = _offset(data, va)
            got = bytes(data[off : off + len(expected)])
            if got != expected:
                raise ValueError(
                    f"unexpected build: 0x{va:08x} is {got.hex()}, expected {expected.hex()} - "
                    "the weather combo box is not where this patch expects it"
                )

    def _check_weather_table(self, data: bytes | bytearray) -> tuple[int, ...]:
        """The stock name pointers, after checking the table is what it should be and that every
        reference to it still holds its address with its expected encoding."""
        names = self._read_weather_table(data, WEATHER_TABLE_VA)
        if names != list(STOCK_WEATHER_NAMES):
            raise ValueError(
                f"unexpected build: the weather name table at 0x{WEATHER_TABLE_VA:08x} reads "
                f"{names}, expected {list(STOCK_WEATHER_NAMES)}"
            )
        if self.weather in names:
            raise ValueError(f"{self.weather!r} is already weather {names.index(self.weather)}")
        for va, prefix in WEATHER_TABLE_REF_SITES:
            off = _offset(data, va)
            got = bytes(data[off : off + len(prefix) + 4])
            want = prefix + _u32(WEATHER_TABLE_VA)
            if got != want:
                raise ValueError(
                    f"weather name table ref @0x{va:08x} is {got.hex()}, expected {want.hex()} - "
                    "not the expected build, or already patched"
                )
        return struct.unpack_from(
            f"<{len(STOCK_WEATHER_NAMES)}I", data, _offset(data, WEATHER_TABLE_VA)
        )

    @staticmethod
    def _read_weather_table(data: bytes | bytearray, base_va: int, limit: int = 8) -> list[str]:
        """The NULL-terminated table at ``base_va``, as names."""
        names: list[str] = []
        off = _offset(data, base_va)
        for index in range(limit):
            pointer = struct.unpack_from("<I", data, off + index * 4)[0]
            if pointer == 0:
                return names
            name = read_cstring(data, pointer)
            if name is None:
                raise ValueError(f"weather entry {index} points at unmapped 0x{pointer:08x}")
            names.append(name)
        raise ValueError(f"the weather table at 0x{base_va:08x} is not NULL-terminated")
