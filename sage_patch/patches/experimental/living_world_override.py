"""Make `GameData`'s `LivingWorldCampaignOverrride` settable from INI.

The override starts a `LivingWorldCampaign` by name, the only data-driven way to reach a scripted
campaign (the engine's other route is the hardcoded `"WOTRTutorial"` at `0x007B9983`). Its field row
names the `Bool` parser while every reader treats the field as a string, so it can never be set. One
dword: the row's parser becomes the `AsciiString` parser. The override is global, so it suits
testing rather than shipping; `campaign-select` is the shipping shape.

Derivation: `../../docs/living-campaign/living-world-campaign.md`.
"""

from __future__ import annotations

import struct

from sage_ini.engine import Engine, FieldDelta

from ...addresses import (
    GAME_DATA_ASCIISTRING_PARSER,
    GAME_DATA_BOOL_PARSER,
    GAME_DATA_SHELL_MAP_NAME_ROW,
    LIVING_WORLD_OVERRIDE_OFFSET,
    LIVING_WORLD_OVERRIDE_ROW,
)
from ...patcher import Patch
from ...utils import apply_byte_patch, read_cstring, u32, va_to_offset

__all__ = ["FIELD_NAME", "LivingWorldOverridePatch", "ROW_NAME_OFFSET", "ROW_PARSE_OFFSET"]

#: A `GameData` field-table row is `{const char *name, parse_fn, user_data, offset}`.
ROW_NAME_OFFSET = 0x00
ROW_PARSE_OFFSET = 0x04
ROW_OFFSET_OFFSET = 0x0C

FIELD_NAME = "LivingWorldCampaignOverrride"  # the engine's own spelling, triple 'r' included


def _read_u32(data: bytes | bytearray, va: int, what: str) -> int:
    off = va_to_offset(data, va)
    if off is None:
        raise ValueError(f"{what} @{va:#010x} is not mapped - not the expected build")
    return struct.unpack_from("<I", data, off)[0]


class LivingWorldOverridePatch(Patch):
    name = "living-world-override"
    author = "officialNecro"
    experimental = True
    description = (
        "Parse GameData's LivingWorldCampaignOverrride as the AsciiString it is, not as a Bool, "
        "so it can name a LivingWorldCampaign - including an IsScriptedCampaign one, which the "
        "War of the Ring picker hides. On a stock binary the same line corrupts a string "
        "pointer and crashes"
    )

    def apply(self, data: bytearray) -> None:
        self._check_row(data)
        off = va_to_offset(data, LIVING_WORLD_OVERRIDE_ROW + ROW_PARSE_OFFSET)
        assert off is not None  # _check_row already proved the row is mapped
        apply_byte_patch(
            data,
            off,
            u32(GAME_DATA_BOOL_PARSER),
            u32(GAME_DATA_ASCIISTRING_PARSER),
            f"{FIELD_NAME} parser: Bool -> AsciiString",
        )

    @staticmethod
    def _check_row(data: bytes | bytearray) -> None:
        """Raise unless the row being edited is the one this patch means, and unless the parser it
        is being pointed at is this build's `AsciiString` parser.

        The row is identified by its **name and target offset**, not by its address alone: a build
        whose table moved or reordered fails here rather than having some other field's parser
        silently swapped. The replacement parser is proved by the `ShellMapName` row, which is an
        `AsciiString` field in every build - so the address is read from the image rather than
        trusted from this module.
        """
        named = read_cstring(data, _read_u32(data, LIVING_WORLD_OVERRIDE_ROW, "the override row"))
        if named != FIELD_NAME:
            raise ValueError(
                f"the row at {LIVING_WORLD_OVERRIDE_ROW:#010x} names {named!r}, not {FIELD_NAME!r} "
                "- this is not the GameData field table of the expected build"
            )
        target = _read_u32(
            data, LIVING_WORLD_OVERRIDE_ROW + ROW_OFFSET_OFFSET, "the override row's offset"
        )
        if target != LIVING_WORLD_OVERRIDE_OFFSET:
            raise ValueError(
                f"{FIELD_NAME} targets GlobalData+{target:#x}, expected "
                f"+{LIVING_WORLD_OVERRIDE_OFFSET:#x} - the GlobalData layout is not this build's"
            )
        anchor = _read_u32(
            data, GAME_DATA_SHELL_MAP_NAME_ROW + ROW_PARSE_OFFSET, "the ShellMapName row"
        )
        if anchor != GAME_DATA_ASCIISTRING_PARSER:
            raise ValueError(
                f"ShellMapName parses with {anchor:#010x}, not {GAME_DATA_ASCIISTRING_PARSER:#010x}"
                " - the AsciiString parser is not where this patch thinks, so the override would be"
                " pointed at the wrong code"
            )

    def verify(self, data: bytes | bytearray) -> list[str]:
        try:
            self._check_row(data)
        except ValueError as exc:
            return [str(exc)]
        parser = _read_u32(
            data, LIVING_WORLD_OVERRIDE_ROW + ROW_PARSE_OFFSET, "the override row's parser"
        )
        if parser == GAME_DATA_ASCIISTRING_PARSER:
            return []
        which = "the stock Bool parser" if parser == GAME_DATA_BOOL_PARSER else "something else"
        return [
            f"{FIELD_NAME} parses with {parser:#010x} ({which}), not "
            f"{GAME_DATA_ASCIISTRING_PARSER:#010x}: the file does not carry this patch"
        ]

    def ini_surface(self) -> Engine:
        """The field the patched engine now accepts as a string.

        `sage_ini` models neither this field nor its neighbours today, so this is additive rather
        than a correction - but it is what makes `sage_lint` accept
        `LivingWorldCampaignOverrride = WOTRScenarioAngmar` instead of reporting an unknown
        attribute, and it records the type the patched engine actually parses - the same `String`
        the sibling `ShellMapName` already carries.
        """
        return Engine(fields=(FieldDelta("GameData", FIELD_NAME, "String", "", self.name),))
