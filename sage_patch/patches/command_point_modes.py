"""Add entries to the lobby's command-point option, the list Edain uses as its game-mode picker.

The skirmish/LAN/online rules combo for `RULE:CommandPointFactor` is built from a static descriptor
whose option list is seven `{label, value}` pairs in `.rdata` (33, 50, 100, 200, 400, 800, 10000).
The combo is populated from that list, a choice is stored and sent as the value, and a received
value is shown by matching it against the list, so the list is the only place the choices exist.

This patch writes a longer list into a section of its own - the stock seven, by pointer, then the
caller's `{label, value}` pairs and their label strings - and repoints the descriptor's list and
count at it, and optionally its default. Nothing in `.text` changes.

A label is a string-table key (`VALUE:...` by convention), fetched with the value as its format
argument; the mod adds the text. The value is the percentage the command-point hard cap is scaled
by - the only thing the simulation does with it - so a game mode that should not change command
points has to undo it from a map script with `OVERRIDE_PLAYER_COMMAND_POINTS`, and
`command-point-override` is what keeps that through a defeat.

Derivation: `../docs/command-point-override.md` §4.
"""

from __future__ import annotations

import argparse
import struct
from collections.abc import Sequence

from ..addresses import (
    GAME_RULES_COMBOS_MP,
    GAME_RULES_COMMAND_POINT_FACTOR,
    GAME_RULES_COMMAND_POINT_FACTOR_BYTES,
    GAME_RULES_COMMAND_POINT_FACTOR_COUNT,
    GAME_RULES_COMMAND_POINT_FACTOR_OPTIONS,
    GAME_RULES_COMMAND_POINT_FACTOR_OPTIONS_BYTES,
)
from ..patcher import Patch
from ..utils import allocate_section, apply_byte_patch, find_section, read_cstring, va_to_offset

__all__ = [
    "MAX_LABEL",
    "MAX_MODES",
    "MAX_VALUE",
    "SECTION_NAME",
    "STOCK_DEFAULT",
    "STOCK_VALUES",
    "CommandPointModesPatch",
    "parse_modes",
]

SECTION_NAME = ".cpmodes"

# IMAGE_SCN_CNT_INITIALIZED_DATA | MEM_READ - the engine only reads the list.
_CHARACTERISTICS = 0x40 | 0x40000000

#: The stock values, in list order, read from `GAME_RULES_COMMAND_POINT_FACTOR_OPTIONS_BYTES` so
#: they cannot drift from the bytes the patch checks.
STOCK_VALUES: tuple[int, ...] = tuple(
    struct.unpack_from("<I", GAME_RULES_COMMAND_POINT_FACTOR_OPTIONS_BYTES, 8 * i + 4)[0]
    for i in range(GAME_RULES_COMMAND_POINT_FACTOR_COUNT)
)
STOCK_DEFAULT = STOCK_VALUES[struct.unpack_from("<I", GAME_RULES_COMMAND_POINT_FACTOR_BYTES, 12)[0]]

#: Extra entries a combo may take. The lobby has never shown more than eleven in one combo, and
#: whether a long list scrolls is unconfirmed; this only bounds a typo.
MAX_MODES = 32
#: The hard cap is scaled as `cap * value / 100` in 32-bit signed arithmetic, so a value this size
#: leaves room for a hard cap past 20000.
MAX_VALUE = 100_000
#: A label is a string-table key, not display text.
MAX_LABEL = 63

_PAIR = 8


def parse_modes(text: str) -> tuple[tuple[int, ...], tuple[str, ...]]:
    """`"300=VALUE:Siege, 150=VALUE:Ranked"` -> `((300, 150), ("VALUE:Siege", "VALUE:Ranked"))`."""
    values: list[int] = []
    labels: list[str] = []
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        value, sep, label = part.partition("=")
        if not sep:
            raise ValueError(f"{part!r} is not VALUE=LABEL")
        try:
            values.append(int(value.strip(), 0))
        except ValueError:
            raise ValueError(f"{value.strip()!r} in {part!r} is not an integer") from None
        labels.append(label.strip())
    return tuple(values), tuple(labels)


class CommandPointModesPatch(Patch):
    name = "command-point-modes"
    author = "officialNecro"
    description = (
        "Add entries to the lobby's command-point option (RULE:CommandPointFactor, which Edain "
        "labels Game Mode) after the stock seven: --modes takes VALUE=LABEL pairs, the value "
        "being the percentage the command-point hard cap is scaled by and the label a string-"
        "table key the mod's .str/.csf must define; --default picks the preselected value. Every "
        "peer needs the same list, which the same game.dat gives. No INI change"
    )

    def __init__(
        self,
        values: Sequence[int] = (),
        labels: Sequence[str] = (),
        default: int | None = None,
    ):
        self.values = tuple(int(v) for v in values)
        self.labels = tuple(labels)
        self.default = None if default == STOCK_DEFAULT else default
        self._validate()

    def _validate(self) -> None:
        if len(self.values) != len(self.labels):
            raise ValueError(f"{len(self.values)} values but {len(self.labels)} labels")
        if len(self.values) > MAX_MODES:
            raise ValueError(f"{len(self.values)} modes, at most {MAX_MODES}")
        seen = set(STOCK_VALUES)
        for value in self.values:
            if not 1 <= value <= MAX_VALUE:
                raise ValueError(f"value {value} is outside 1..{MAX_VALUE}")
            if value in seen:
                # The lobby selects by value, so a repeat could never be shown as chosen.
                raise ValueError(f"value {value} is already in the list")
            seen.add(value)
        for label in self.labels:
            if not label or len(label) > MAX_LABEL or not label.isascii():
                raise ValueError(f"label {label!r} must be 1..{MAX_LABEL} ASCII characters")
            if not label.isprintable() or " " in label:
                raise ValueError(f"label {label!r} is not a string-table key")
        if self.default is not None and self.default not in seen:
            raise ValueError(f"default {self.default} is not one of the values")

    def __str__(self) -> str:
        listed = ", ".join(
            f"{v}={label}" for v, label in zip(self.values, self.labels, strict=True)
        )
        return f"{self.name} ({listed or 'no modes'})"

    @property
    def all_values(self) -> tuple[int, ...]:
        return STOCK_VALUES + self.values

    @property
    def default_index(self) -> int:
        return self.all_values.index(STOCK_DEFAULT if self.default is None else self.default)

    def _section(self, section_va: int) -> bytes:
        """The new list, then the label strings it points at. The stock seven are copied through
        by pointer, so their labels stay the `.rdata` strings."""
        count = len(self.all_values)
        strings_va = section_va + count * _PAIR
        table = bytearray(GAME_RULES_COMMAND_POINT_FACTOR_OPTIONS_BYTES)
        strings = bytearray()
        for value, label in zip(self.values, self.labels, strict=True):
            table += struct.pack("<II", strings_va + len(strings), value)
            strings += label.encode("ascii") + b"\x00"
        return bytes(table + strings)

    def _descriptor(self, options_va: int) -> bytes:
        return struct.pack(
            "<IIII",
            struct.unpack_from("<I", GAME_RULES_COMMAND_POINT_FACTOR_BYTES)[0],
            options_va,
            len(self.all_values),
            self.default_index,
        )

    def apply(self, data: bytearray) -> None:
        if not self.values:
            raise ValueError("no modes to add: pass --modes VALUE=LABEL[,VALUE=LABEL...]")
        self._check_anchors(data)
        section_va = allocate_section(data, SECTION_NAME, self._section, _CHARACTERISTICS)
        apply_byte_patch(
            data,
            _offset(data, GAME_RULES_COMMAND_POINT_FACTOR),
            GAME_RULES_COMMAND_POINT_FACTOR_BYTES,
            self._descriptor(section_va),
            f"lobby command-point option: {len(self.all_values)} entries in {SECTION_NAME}",
        )

    @staticmethod
    def _check_anchors(data: bytes | bytearray) -> None:
        """Raise unless the stock list is intact and the descriptor is the one the lobby reads.

        The stock pairs are copied by value into the new list, so they must be the stock pairs;
        and the descriptor must be rule set 0's second combo, or the repointed list would belong
        to some other combo."""
        for va, expected, what in (
            (
                GAME_RULES_COMMAND_POINT_FACTOR_OPTIONS,
                GAME_RULES_COMMAND_POINT_FACTOR_OPTIONS_BYTES,
                "stock command-point option list",
            ),
            (
                GAME_RULES_COMBOS_MP + 4,
                struct.pack("<I", GAME_RULES_COMMAND_POINT_FACTOR),
                "pointer from the lobby's rule-combo array to the command-point descriptor",
            ),
        ):
            off = _offset(data, va)
            got = bytes(data[off : off + len(expected)])
            if got != expected:
                raise ValueError(
                    f"{va:#010x} holds {got.hex()}, not the {what} - this is not the expected build"
                )

    def verify(self, data: bytes | bytearray) -> list[str]:
        try:
            self._check_anchors(data)
        except ValueError as exc:
            return [str(exc)]
        located = find_section(data, SECTION_NAME)
        if located is None:
            return [f"{SECTION_NAME} section is absent"]
        section_va, section_off, _ = located
        problems: list[str] = []
        off = _offset(data, GAME_RULES_COMMAND_POINT_FACTOR)
        expected = self._descriptor(section_va)
        if bytes(data[off : off + len(expected)]) != expected:
            problems.append(
                f"{GAME_RULES_COMMAND_POINT_FACTOR:#010x} does not point the command-point option "
                f"at this list"
            )
        content = self._section(section_va)
        if bytes(data[section_off : section_off + len(content)]) != content:
            problems.append(f"the {SECTION_NAME} section does not hold this list")
        return problems

    @classmethod
    def detect(cls, data: bytes | bytearray) -> CommandPointModesPatch | None:
        """Recognise this patch **and recover its list** from `data`.

        The default probe would build the patch with no modes, which matches nothing. The
        descriptor holds the count and default and points at the section, and the section's pairs
        past the stock seven are the caller's; `verify` then re-checks them all."""
        located = find_section(data, SECTION_NAME)
        if located is None:
            return None
        section_va, section_off, vsize = located
        try:
            off = _offset(data, GAME_RULES_COMMAND_POINT_FACTOR)
            _rule, options_va, count, default_index = struct.unpack_from("<IIII", data, off)
            stock = GAME_RULES_COMMAND_POINT_FACTOR_COUNT
            if options_va != section_va or not stock < count <= stock + MAX_MODES:
                return None
            if count * _PAIR > vsize or not 0 <= default_index < count:
                return None
            values: list[int] = []
            labels: list[str] = []
            for i in range(stock, count):
                label_va, value = struct.unpack_from("<II", data, section_off + i * _PAIR)
                label = read_cstring(data, label_va, MAX_LABEL + 1)
                if label is None:
                    return None
                values.append(value)
                labels.append(label)
            all_values = STOCK_VALUES + tuple(values)
            patch = cls(values, labels, default=all_values[default_index])
        except (ValueError, KeyError, IndexError, TypeError, struct.error):
            return None
        return None if patch.verify(data) else patch

    @classmethod
    def add_cli_arguments(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--modes",
            default="",
            metavar="VALUE=LABEL[,VALUE=LABEL...]",
            help=(
                "entries to add after the stock seven: the percentage the command-point hard cap "
                f"is scaled by (1..{MAX_VALUE}, not one of {', '.join(map(str, STOCK_VALUES))}) "
                "and the string-table key shown for it, e.g. 300=VALUE:Siege"
            ),
        )
        parser.add_argument(
            "--default",
            type=int,
            default=None,
            metavar="VALUE",
            help=f"the value preselected in a new lobby (default {STOCK_DEFAULT}, as stock)",
        )

    @classmethod
    def from_cli_args(cls, args: argparse.Namespace) -> CommandPointModesPatch:
        values, labels = parse_modes(args.modes)
        return cls(values, labels, default=args.default)


def _offset(data: bytes | bytearray, va: int) -> int:
    off = va_to_offset(data, va)
    if off is None:
        raise ValueError(f"{va:#010x} is not mapped - not the expected build")
    return off
