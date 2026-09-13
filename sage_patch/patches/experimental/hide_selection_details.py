"""The hide-selection-details patch: a War of the Ring scenario that does without the details tray.

Targets the ROTWK SAGE-engine `game.dat` build ``2.01.2614.37001``. The reverse engineering is in
``../../docs/living-campaign/hide-selection-details.md``.

**The panel.** On the War of the Ring map `StrategicHUD.apt` loads `StrategicDetailsTray.swf` into
its `selectionDetails` clip: the tray showing the selected territory's armies, structures and build
queue, behind the `ToggleSelectionDetailsButton` of `strategichud.ini`. No INI field hides it -
`StrategicHUD` only names the button's image and tooltip. The movie opens and closes when the
engine says so: a small class (vtable
:data:`~sage_patch.addresses.SELECTION_DETAILS_TRAY_VTABLE`) calls the movie's `Open` and `Close`
and keeps the state.

**What this does.** Adds one boolean field, `HideSelectionDetails`, to a `LivingWorldCampaign`'s
`Scenario`. Default `No`, which is stock; `Yes` keeps the tray shut for that scenario.

1. **The field, in the struct's own padding.** `Scenario` is ``0xC4`` bytes and its last field is
   `UseMpRulesVictoryCondition` at ``+0xC1``, so ``+0xC2`` is alignment no row names. The
   constructor's ``mov byte [esi+0xC0], bl`` becomes ``mov dword [esi+0xC0], ebx`` - ``0x88`` to
   ``0x89``, six bytes for six - which clears ``+0xC0..+0xC3``; the ``mov byte [esi+0xC1], 1``
   straight after it puts `UseMpRulesVictoryCondition` back at `Yes`.
2. **The field table moves.** It is rebuilt in the cave with one `Bool` row appended, and its one
   reference, the block parser's `push`, is repointed.
3. **`setHasContent` stores zero.** It is the tray's only writer of "the selection has something to
   show" (``+0x2C``). With that clear, the HUD's per-frame refresh closes an open tray and sets the
   toggle button `_disabled` - the stock path for an empty selection.
4. **`open` returns.** So the toggle button, or anything else that asks, cannot open it regardless.

Both hooks ask one routine, which reads the flag through the campaign manager's current campaign
(``+0x10`` indexing ``+0x14..+0x18``, bounds-checked as the manager itself does) and that
campaign's `Scenario` (``+0x1C``). A null anywhere on the way answers `No`, so outside a campaign
the tray is stock.

**What it does not do.** The tray is where a player reads a territory's armies and structures and
queues construction; a scenario that hides it takes that interface away and has to give the player
another. The movie's own frame-0 script also opens the tray whenever `_global.InGame` is unset,
which no engine hook can reach. The engine registers `InGame` with the movie player
(``0x00815EF3``), so that branch reads as the movie's standalone preview - not confirmed in game.

**Determinism.** Interface only: nothing here reaches the logic or the CRC, so a peer without the
patch stays in sync. The keyword itself is fatal on a stock build - an unknown field in a known
block is a parse error - so a mod that writes it ships the patched `game.dat`.

**Composition.** Order-independent: the cave is allocated past every section and the field table is
located from its live reference, so it appends to whatever is there. No other bundled patch touches
`Scenario`'s table, its constructor or the tray class.
"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sage_ini.engine import Engine, FieldDelta

from ...addresses import (
    FIELD_PARSE_STRIDE,
    INI_PARSE_BOOL,
    LIVING_WORLD_CAMPAIGN_MANAGER_CAMPAIGNS_BEGIN,
    LIVING_WORLD_CAMPAIGN_MANAGER_CAMPAIGNS_END,
    LIVING_WORLD_CAMPAIGN_MANAGER_CURRENT,
    LIVING_WORLD_CAMPAIGN_MANAGER_CURRENT_READ,
    LIVING_WORLD_CAMPAIGN_MANAGER_CURRENT_READ_BYTES,
    LIVING_WORLD_CAMPAIGN_SCENARIO,
    LIVING_WORLD_CAMPAIGN_SCENARIO_READ,
    LIVING_WORLD_CAMPAIGN_SCENARIO_READ_BYTES,
    SCENARIO_ALLOC,
    SCENARIO_ALLOC_BYTES,
    SCENARIO_CTOR_HISTORICAL,
    SCENARIO_CTOR_HISTORICAL_BYTES,
    SCENARIO_CTOR_USE_MP_RULES,
    SCENARIO_CTOR_USE_MP_RULES_BYTES,
    SCENARIO_CTOR_ZERO,
    SCENARIO_CTOR_ZERO_BYTES,
    SCENARIO_FIELD_TABLE_REF_OPCODES,
    SCENARIO_FIELD_TABLE_REFS,
    SCENARIO_FREE_OFFSET,
    SCENARIO_HISTORICAL,
    SCENARIO_USE_MP_RULES,
    SELECTION_DETAILS_TRAY_HAS_CONTENT,
    SELECTION_DETAILS_TRAY_OPEN,
    SELECTION_DETAILS_TRAY_OPEN_BYTES,
    SELECTION_DETAILS_TRAY_OPEN_RESUME,
    SELECTION_DETAILS_TRAY_OPEN_SLOT,
    SELECTION_DETAILS_TRAY_OPEN_THUNK,
    SELECTION_DETAILS_TRAY_OPEN_THUNK_BYTES,
    SELECTION_DETAILS_TRAY_REFRESH_TEST,
    SELECTION_DETAILS_TRAY_REFRESH_TEST_BYTES,
    SELECTION_DETAILS_TRAY_SET_HAS_CONTENT,
    SELECTION_DETAILS_TRAY_SET_HAS_CONTENT_BYTES,
    SELECTION_DETAILS_TRAY_SET_HAS_CONTENT_RESUME,
    SELECTION_DETAILS_TRAY_SET_HAS_CONTENT_SLOT,
    SELECTION_DETAILS_TRAY_VTABLE,
    THE_LIVING_WORLD_CAMPAIGN_MANAGER,
)
from ...asm import JAE, JE, JL, Asm
from ...patcher import Patch
from ...utils import allocate_section, apply_byte_patch, find_section, va_to_offset
from ..utils.field_tables import Entry, entries_before, read_field_table, resolve_table

if TYPE_CHECKING:
    import argparse

__all__ = [
    "ANCHORS",
    "DEFAULT_KEYWORD",
    "SECTION_NAME",
    "HideSelectionDetailsPatch",
    "build_code",
    "build_table",
    "rewritten_default",
    "validate_keyword",
]

SECTION_NAME = ".hsd"

#: The INI keyword the new `Scenario` field is parsed under.
DEFAULT_KEYWORD = "HideSelectionDetails"

#: IMAGE_SCN_CNT_CODE | CNT_INITIALIZED_DATA | MEM_EXECUTE | MEM_READ. The cave holds the keyword
#: and the rebuilt table (read) and three routines (executed); nothing in it is written.
_CHARACTERISTICS = 0x20 | 0x40 | 0x20000000 | 0x40000000


def _u32(value: int) -> bytes:
    return struct.pack("<I", value)


#: Bytes the patch reads rather than writes, each one a fact the cave relies on: the struct is big
#: enough to hold the field, the constructor zeroes from `ebx` and re-sets `+0xC1` after the widened
#: store, the manager and the campaign keep the layout the flag is read through, and the vtable,
#: the thunk and the refresh are the tray class whose methods are hooked.
ANCHORS: dict[int, bytes] = {
    SCENARIO_ALLOC: SCENARIO_ALLOC_BYTES,
    SCENARIO_CTOR_ZERO: SCENARIO_CTOR_ZERO_BYTES,
    SCENARIO_CTOR_USE_MP_RULES: SCENARIO_CTOR_USE_MP_RULES_BYTES,
    LIVING_WORLD_CAMPAIGN_MANAGER_CURRENT_READ: LIVING_WORLD_CAMPAIGN_MANAGER_CURRENT_READ_BYTES,
    LIVING_WORLD_CAMPAIGN_SCENARIO_READ: LIVING_WORLD_CAMPAIGN_SCENARIO_READ_BYTES,
    SELECTION_DETAILS_TRAY_VTABLE + SELECTION_DETAILS_TRAY_SET_HAS_CONTENT_SLOT: _u32(
        SELECTION_DETAILS_TRAY_SET_HAS_CONTENT
    ),
    SELECTION_DETAILS_TRAY_VTABLE + SELECTION_DETAILS_TRAY_OPEN_SLOT: _u32(
        SELECTION_DETAILS_TRAY_OPEN_THUNK
    ),
    SELECTION_DETAILS_TRAY_OPEN_THUNK: SELECTION_DETAILS_TRAY_OPEN_THUNK_BYTES,
    SELECTION_DETAILS_TRAY_REFRESH_TEST: SELECTION_DETAILS_TRAY_REFRESH_TEST_BYTES,
}

#: Fields the live table must still carry at these offsets, or this is not the build the layout was
#: derived against. Checked by name, so another patch having appended to the table first is fine.
FINGERPRINT = {
    "DisableRegions": 0x1C,
    "HistoricalScenario": SCENARIO_HISTORICAL,
    "UseMpRulesVictoryCondition": SCENARIO_USE_MP_RULES,
}

# An INI keyword is matched by exact compare, so anything the parser could never match is a typo
# rather than a choice.
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
    """Where each piece of the cave sits, given its base, the keyword and the live table's row
    count - pure arithmetic, so `apply` and `verify` reach the same addresses."""

    keyword_va: int
    table_va: int
    code_va: int


def _layout(base_va: int, keyword: str, rows: int) -> _Layout:
    # The keyword opens the cave, which is what lets `detect` read it back without knowing it.
    string = len(keyword) + 1
    table_va = base_va + string + (-string % 4)
    code_va = table_va + (rows + 2) * FIELD_PARSE_STRIDE  # + the new row + the terminator
    return _Layout(base_va, table_va, code_va)


def rewritten_default() -> bytes:
    """The constructor's `HistoricalScenario` store, widened to zero the new field as well.

    ``mov byte [esi+0xC0], bl`` becomes ``mov dword [esi+0xC0], ebx``. `ebx` is the constructor's
    zero throughout, so `HistoricalScenario` keeps its `No`; ``+0xC1`` is cleared on the way past
    and set back to 1 by the very next instruction."""
    new = bytes([0x89]) + SCENARIO_CTOR_HISTORICAL_BYTES[1:]
    assert len(new) == len(SCENARIO_CTOR_HISTORICAL_BYTES)
    return new


def build_table(entries: tuple[Entry, ...], keyword_va: int) -> bytes:
    """The rebuilt field-parse table: the live rows verbatim, the new `Bool`, the terminator."""
    table = bytearray()
    for entry in entries:
        table += struct.pack("<IIII", *entry)
    table += struct.pack("<IIII", keyword_va, INI_PARSE_BOOL, 0, SCENARIO_FREE_OFFSET)
    return bytes(table) + bytes(FIELD_PARSE_STRIDE)


def build_code(code_va: int) -> Asm:
    """The cave's three routines, laid out at the address they will occupy.

    `has_content` and `open` replace the first instructions of the two tray methods and are reached
    by the `jmp` the hooks install, so the stack is the method's own on entry: `[esp]` is the
    caller's return address and `[esp+4]` the argument. `scenario_flag` is the one question both
    ask, and keeps every register but `eax`."""
    a = Asm(code_va)

    a.label("has_content")  # in place of setHasContent's first two instructions
    a.call("scenario_flag")
    a.emit(0x85, 0xC0)  # test eax, eax
    a.emit(0x8A, 0x44, 0x24, 0x04)  # mov al, [esp+4]      ; the argument; flags kept
    a.jcc_short(JE, "store")
    a.emit(0x32, 0xC0)  # xor al, al                          ; hidden: nothing to show
    a.label("store")
    a.emit(0x3A, 0x41, SELECTION_DETAILS_TRAY_HAS_CONTENT)  # cmp al, [ecx+0x2C]
    a.jmp_absolute(SELECTION_DETAILS_TRAY_SET_HAS_CONTENT_RESUME)

    a.label("open")  # in place of open's first three instructions
    a.call("scenario_flag")
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc_short(JE, "open_stock")
    a.emit(0xC3)  # ret                                       ; hidden: the tray stays shut
    a.label("open_stock")
    a.emit(SELECTION_DETAILS_TRAY_OPEN_BYTES)  # push esi / mov esi, ecx / mov eax, [esi+0x18]
    a.jmp_absolute(SELECTION_DETAILS_TRAY_OPEN_RESUME)

    a.label("scenario_flag")  # eax = the current scenario's flag, 0 when there is none
    a.emit(0x51, 0x52)  # push ecx / push edx
    a.emit(0x33, 0xC0)  # xor eax, eax
    a.emit(0x8B, 0x0D, _u32(THE_LIVING_WORLD_CAMPAIGN_MANAGER))  # mov ecx, [manager]
    a.emit(0x85, 0xC9)  # test ecx, ecx
    a.jcc_short(JE, "flag_out")
    a.emit(0x8B, 0x51, LIVING_WORLD_CAMPAIGN_MANAGER_CURRENT)  # mov edx, [ecx+0x10]
    a.emit(0x85, 0xD2)  # test edx, edx
    a.jcc_short(JL, "flag_out")
    a.emit(0x8B, 0x41, LIVING_WORLD_CAMPAIGN_MANAGER_CAMPAIGNS_END)  # mov eax, [ecx+0x18]
    a.emit(0x2B, 0x41, LIVING_WORLD_CAMPAIGN_MANAGER_CAMPAIGNS_BEGIN)  # sub eax, [ecx+0x14]
    a.emit(0xC1, 0xF8, 0x02)  # sar eax, 2
    a.emit(0x3B, 0xD0)  # cmp edx, eax
    a.jcc_short(JAE, "flag_none")
    a.emit(0x8B, 0x49, LIVING_WORLD_CAMPAIGN_MANAGER_CAMPAIGNS_BEGIN)  # mov ecx, [ecx+0x14]
    a.emit(0x8B, 0x0C, 0x91)  # mov ecx, [ecx+edx*4]            ; the campaign
    a.emit(0x85, 0xC9)  # test ecx, ecx
    a.jcc_short(JE, "flag_none")
    a.emit(0x8B, 0x49, LIVING_WORLD_CAMPAIGN_SCENARIO)  # mov ecx, [ecx+0x1C]  ; its Scenario
    a.emit(0x85, 0xC9)  # test ecx, ecx
    a.jcc_short(JE, "flag_none")
    a.emit(0x0F, 0xB6, 0x81, _u32(SCENARIO_FREE_OFFSET))  # movzx eax, byte [ecx+0xC2]
    a.jmp_short("flag_out")
    a.label("flag_none")
    a.emit(0x33, 0xC0)  # xor eax, eax
    a.label("flag_out")
    a.emit(0x5A, 0x59, 0xC3)  # pop edx / pop ecx / ret
    return a


def _hook(site_va: int, window: bytes, target_va: int) -> bytes:
    """`jmp rel32` to ``target_va``, padded with `nop` to the width of ``window``."""
    jump = b"\xe9" + struct.pack("<i", target_va - (site_va + 5))
    if len(window) < len(jump):
        raise ValueError(f"the window at 0x{site_va:08x} is too small for a jmp rel32")
    return jump + b"\x90" * (len(window) - len(jump))


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


class HideSelectionDetailsPatch(Patch):
    """Add a `HideSelectionDetails` boolean to `Scenario`, keeping the War of the Ring
    selection-details tray shut for a scenario that sets it."""

    name = "hide-selection-details"
    author = "officialNecro"
    experimental = True
    description = (
        "Add a HideSelectionDetails boolean to a LivingWorldCampaign's Scenario block: Yes keeps "
        "the War of the Ring selection-details tray shut for that scenario and disables its "
        "toggle button. No, the default, is stock"
    )

    def __init__(self, keyword: str = DEFAULT_KEYWORD):
        self.keyword = keyword
        validate_keyword(keyword)

    def __str__(self) -> str:
        return f"{self.name} ({self.keyword})"

    def apply(self, data: bytearray) -> None:
        self._check_anchors(data)
        entries = self._check_table(data, self._resolve(data))

        base_va = allocate_section(
            data, SECTION_NAME, lambda base: self._build(base, entries), _CHARACTERISTICS
        )
        pieces = _layout(base_va, self.keyword, len(entries))
        code = build_code(pieces.code_va)
        for file_off, old, new, note in self._edits(data, pieces, code):
            apply_byte_patch(data, file_off, old, new, note)

    def _build(self, base_va: int, entries: tuple[Entry, ...]) -> bytes:
        """The cave: the keyword string, the rebuilt table, the code."""
        pieces = _layout(base_va, self.keyword, len(entries))
        blob = bytearray(self.keyword.encode("ascii") + b"\x00")
        blob += bytes(pieces.table_va - (base_va + len(blob)))
        blob += build_table(entries, pieces.keyword_va)
        assert base_va + len(blob) == pieces.code_va, "the cave layout and its addresses disagree"
        return bytes(blob) + build_code(pieces.code_va).finish()

    @staticmethod
    def _hooks(code: Asm) -> list[tuple[int, bytes, bytes, str]]:
        """``(site, stock bytes, replacement, what)`` for the constructor store and both hooks."""
        return [
            (
                SCENARIO_CTOR_HISTORICAL,
                SCENARIO_CTOR_HISTORICAL_BYTES,
                rewritten_default(),
                "the Scenario ctor's HistoricalScenario store",
            ),
            (
                SELECTION_DETAILS_TRAY_SET_HAS_CONTENT,
                SELECTION_DETAILS_TRAY_SET_HAS_CONTENT_BYTES,
                _hook(
                    SELECTION_DETAILS_TRAY_SET_HAS_CONTENT,
                    SELECTION_DETAILS_TRAY_SET_HAS_CONTENT_BYTES,
                    code.label_va("has_content"),
                ),
                "the tray's setHasContent",
            ),
            (
                SELECTION_DETAILS_TRAY_OPEN,
                SELECTION_DETAILS_TRAY_OPEN_BYTES,
                _hook(
                    SELECTION_DETAILS_TRAY_OPEN,
                    SELECTION_DETAILS_TRAY_OPEN_BYTES,
                    code.label_va("open"),
                ),
                "the tray's open",
            ),
        ]

    def _edits(
        self, data: bytes | bytearray, pieces: _Layout, code: Asm
    ) -> list[tuple[int, bytes, bytes, str]]:
        """Every byte this patch writes outside its own cave, as
        ``(file offset, expected, replacement, note)``."""
        edits = [
            (_offset(data, va), old, new, f"{what} -> {SECTION_NAME}")
            for va, old, new, what in self._hooks(code)
        ]
        for ref_va, opcode in zip(
            SCENARIO_FIELD_TABLE_REFS, SCENARIO_FIELD_TABLE_REF_OPCODES, strict=True
        ):
            off = _offset(data, ref_va)
            edits.append(
                (
                    off,
                    bytes(data[off : off + 5]),
                    bytes([opcode]) + _u32(pieces.table_va),
                    f"Scenario field table reference 0x{ref_va:08x} -> {SECTION_NAME}",
                )
            )
        return edits

    @staticmethod
    def _resolve(data: bytes | bytearray) -> int:
        """`Scenario`'s field table as the image currently holds it, read from its reference so the
        patch appends to whatever is live and applying it twice fails cleanly."""
        return resolve_table(
            data, SCENARIO_FIELD_TABLE_REFS, SCENARIO_FIELD_TABLE_REF_OPCODES, "Scenario"
        )

    @staticmethod
    def _anchor_problems(data: bytes | bytearray) -> list[str]:
        problems = []
        for va, want in ANCHORS.items():
            off = _offset(data, va)
            got = bytes(data[off : off + len(want)])
            if got != want:
                problems.append(
                    f"0x{va:08x} holds {got.hex()}, expected {want.hex()} - not the build the "
                    "Scenario layout and the selection-details tray were read from"
                )
        return problems

    @classmethod
    def _check_anchors(cls, data: bytes | bytearray) -> None:
        problems = cls._anchor_problems(data)
        if problems:
            raise ValueError(problems[0])

    def _check_table(self, data: bytes | bytearray, table_va: int) -> tuple[Entry, ...]:
        """The live rows, once the table has been checked for the build, for this keyword and for
        the padding still being free."""
        entries = read_field_table(data, table_va)
        by_name = {_cstring(data, name): offset for name, _fn, _ud, offset in entries}
        for field, want in FINGERPRINT.items():
            got = by_name.get(field)
            if got != want:
                raise ValueError(
                    f"unexpected build: Scenario.{field} is at "
                    f"{'absent' if got is None else hex(got)}, expected {want:#x}"
                )
        if self.keyword in by_name:
            raise ValueError(
                f"Scenario already has a {self.keyword!r} field - this patch is already applied, "
                "or another patch has added the same field"
            )
        taken = [name for name, offset in by_name.items() if offset == SCENARIO_FREE_OFFSET]
        if taken:
            raise ValueError(
                f"Scenario+0x{SCENARIO_FREE_OFFSET:02x} is already the {taken[0]!r} field - "
                "another patch is using the padding this one stores into"
            )
        return entries

    @classmethod
    def detect(cls, data: bytes | bytearray) -> HideSelectionDetailsPatch | None:
        """Recognise this patch and recover its keyword, which opens the cave."""
        located = find_section(data, SECTION_NAME)
        if located is None:
            return None
        keyword = _cstring(data, located[0])
        if keyword is None:
            return None
        try:
            patch = cls(keyword)
        except ValueError:
            return None
        return None if patch.verify(data) else patch

    def ini_surface(self) -> Engine:
        """The one `Bool` this patch adds to `Scenario`. The constructor zeroes it, so the default
        is `No` - stock behaviour."""
        return Engine(fields=(FieldDelta("Scenario", self.keyword, "Bool", False, self.name),))

    def verify(self, data: bytes | bytearray) -> list[str]:
        """Structural check that ``data`` carries this patch for exactly this keyword, with every
        address recovered from where the cave actually landed."""
        located = find_section(data, SECTION_NAME)
        if located is None:
            return [f"no {SECTION_NAME} section: the file does not carry this patch"]
        section_va, _section_off, vsize = located

        try:
            problems = self._anchor_problems(data)
            live = read_field_table(data, self._resolve(data))
            preceding = entries_before(data, live, self.keyword)
            if preceding is None:
                return [*problems, f"the live Scenario table does not name {self.keyword!r}"]
            pieces = _layout(section_va, self.keyword, len(preceding))
            problems += self._verify_cave(data, pieces, preceding, section_va, vsize)
            problems += self._verify_sites(data, pieces, live)
        except (ValueError, struct.error) as exc:
            return [f"cannot read back the patch (wrong build?): {exc}"]
        return problems

    def _verify_cave(
        self,
        data: bytes | bytearray,
        pieces: _Layout,
        preceding: tuple[Entry, ...],
        section_va: int,
        vsize: int,
    ) -> list[str]:
        code = build_code(pieces.code_va).finish()
        if pieces.code_va + len(code) > section_va + vsize:
            return [f"{SECTION_NAME} holds {vsize} bytes, too few for the table and the code"]
        problems: list[str] = []
        got_keyword = _cstring(data, pieces.keyword_va)
        if got_keyword != self.keyword:
            problems.append(
                f"the keyword in {SECTION_NAME} is {got_keyword!r}, not {self.keyword!r}"
            )
        want_table = build_table(preceding, pieces.keyword_va)
        table_off = _offset(data, pieces.table_va)
        if bytes(data[table_off : table_off + len(want_table)]) != want_table:
            problems.append(
                f"the field table at 0x{pieces.table_va:08x} is not the live rows plus a Bool at "
                f"Scenario+0x{SCENARIO_FREE_OFFSET:02x}"
            )
        code_off = _offset(data, pieces.code_va)
        if bytes(data[code_off : code_off + len(code)]) != code:
            problems.append(f"the code at 0x{pieces.code_va:08x} is not what this patch builds")
        return problems

    def _verify_sites(
        self, data: bytes | bytearray, pieces: _Layout, live: tuple[Entry, ...]
    ) -> list[str]:
        """The three edits, and the row the engine will actually parse the field through - checked
        in the live table, since a later patch extending `Scenario` copies the row into its own."""
        problems: list[str] = []
        for va, _old, want, what in self._hooks(build_code(pieces.code_va)):
            off = _offset(data, va)
            got = bytes(data[off : off + len(want)])
            if got != want:
                problems.append(f"@0x{va:08x}: {what} is not patched (holds {got.hex()})")

        want_row = (pieces.keyword_va, INI_PARSE_BOOL, 0, SCENARIO_FREE_OFFSET)
        row = next((e for e in live if _cstring(data, e[0]) == self.keyword), None)
        if row != want_row:
            problems.append(
                f"the live Scenario table's {self.keyword!r} row is "
                f"{'absent' if row is None else tuple(hex(v) for v in row)}, expected "
                f"{tuple(hex(v) for v in want_row)}"
            )
        return problems

    @classmethod
    def add_cli_arguments(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--keyword",
            default=DEFAULT_KEYWORD,
            metavar="NAME",
            help=(
                f"name of the INI field to add to Scenario (default {DEFAULT_KEYWORD}); letters, "
                "digits and underscores, and must not already be a Scenario field"
            ),
        )

    @classmethod
    def from_cli_args(cls, args: argparse.Namespace) -> HideSelectionDetailsPatch:
        return cls(keyword=args.keyword)
