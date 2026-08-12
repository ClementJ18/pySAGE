"""The living-world-override patch: make `LivingWorldCampaignOverrride` settable from INI.

Targets the ROTWK SAGE-engine `game.dat` build ``2.01.2614.37001``. The reverse engineering is in
``../docs/living-world-campaign.md``.

**The gap.** `GameData`'s ``LivingWorldCampaignOverrride`` names a `LivingWorldCampaign` to start
by name instead of by the index the War of the Ring menu passes. It is the only data-driven way to
reach a **scripted** campaign, because a campaign with ``IsScriptedCampaign = Yes`` is deliberately
excluded from the scenario list: the list predicate at ``0x007B9551`` answers "not listable" the
moment that flag is set, so a scripted campaign disappears from the picker and the override is the
way back in. (The engine's only other route is `AptMainMenu`'s hardcoded ``"WOTRTutorial"`` at
``0x007B9983``.)

**The defect.** The field is declared with the **wrong parser**. Its row in the `GameData`
field-parse table names ``0x0042E558`` - the `Bool` parser, the one ``Windowed`` and ``AudioOn``
use, which ends in ``mov byte ptr [ecx], al`` - while every code path treats
``GlobalData+0x8C`` as an `AsciiString`:

- the constructor initialises it as a pointer (``0x00642AA3``, ``mov dword [esi+0x8c], ebx``),
- the campaign selector calls ``AsciiString::isEmpty`` on it (``0x007B96E4``),
- and the orphaned command-line handler at ``0x007BAA28`` sets it with ``AsciiString::set``.

So ``LivingWorldCampaignOverrride = Yes`` writes ``1`` over the low byte of the string pointer and
the next ``isEmpty`` dereferences it. The field is unusable, and the crash is latent in any mod
that writes the line - Edain already carries it in a ``;///`` comment block.

**What this does.** One dword: the row's parse pointer becomes ``0x0042EE5E``, the `AsciiString`
parser the neighbouring ``ShellMapName`` row already uses for a field of exactly the same shape.
Nothing else moves - the row keeps its name, its user data and its ``+0x8C`` offset, the table does
not grow, and no other row is touched.

**What it does not do.** It does not make a scripted campaign *good* - see the doc's §7 for the
feature gaps (`SplitArmy`/`MergeArmy` are absent from this engine entirely). And the override is
**global**: it forces one campaign for every War of the Ring start, which is right for testing a
scripted campaign and wrong as a shipping mechanism. The shipping shape is a menu entry that names
a campaign, in the manner of :mod:`~.campaign_select`.

**Composition.** Order-independent and cave-free. The only byte it edits is one pointer in the
`GameData` field table, which no other bundled patch rebuilds or reads.
"""

from __future__ import annotations

import struct

from sage_ini.engine import Engine, FieldDelta

from ..addresses import (
    GAME_DATA_ASCIISTRING_PARSER,
    GAME_DATA_BOOL_PARSER,
    GAME_DATA_SHELL_MAP_NAME_ROW,
    LIVING_WORLD_OVERRIDE_OFFSET,
    LIVING_WORLD_OVERRIDE_ROW,
)
from ..patcher import Patch
from ..utils import apply_byte_patch, va_to_offset

__all__ = ["FIELD_NAME", "LivingWorldOverridePatch", "ROW_NAME_OFFSET", "ROW_PARSE_OFFSET"]

#: A `GameData` field-table row is ``{const char *name, parse_fn, user_data, offset}``.
ROW_NAME_OFFSET = 0x00
ROW_PARSE_OFFSET = 0x04
ROW_OFFSET_OFFSET = 0x0C

FIELD_NAME = "LivingWorldCampaignOverrride"  # the engine's own spelling, triple 'r' included


def _u32(value: int) -> bytes:
    return struct.pack("<I", value)


def _read_u32(data: bytes | bytearray, va: int, what: str) -> int:
    off = va_to_offset(data, va)
    if off is None:
        raise ValueError(f"{what} @{va:#010x} is not mapped - not the expected build")
    return struct.unpack_from("<I", data, off)[0]


def _read_cstring(data: bytes | bytearray, va: int, limit: int = 64) -> str | None:
    off = va_to_offset(data, va)
    if off is None:
        return None
    blob = bytes(data[off : off + limit])
    end = blob.find(b"\x00")
    return None if end < 0 else blob[:end].decode("ascii", "replace")


class LivingWorldOverridePatch(Patch):
    name = "living-world-override"
    author = "officialNecro"
    description = (
        "Parse GameData's LivingWorldCampaignOverrride as the AsciiString it is, not as a Bool"
    )

    def apply(self, data: bytearray) -> None:
        self._check_row(data)
        off = va_to_offset(data, LIVING_WORLD_OVERRIDE_ROW + ROW_PARSE_OFFSET)
        assert off is not None  # _check_row already proved the row is mapped
        apply_byte_patch(
            data,
            off,
            _u32(GAME_DATA_BOOL_PARSER),
            _u32(GAME_DATA_ASCIISTRING_PARSER),
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
        named = _read_cstring(data, _read_u32(data, LIVING_WORLD_OVERRIDE_ROW, "the override row"))
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
        ``LivingWorldCampaignOverrride = WOTRScenarioAngmar`` instead of reporting an unknown
        attribute, and it records the type the patched engine actually parses - the same `String`
        the sibling ``ShellMapName`` already carries.
        """
        return Engine(fields=(FieldDelta("GameData", FIELD_NAME, "String", "", self.name),))
