"""Add `NoBattleHeroPool` to a `LivingWorldCampaign`'s `Scenario`: `Yes` keeps the world-map hero
pool out of that scenario's battles.

A War of the Ring player's off-map heroes - the level-1 heroes its world-map buildings offer, and
every hero who left an army or died without being revived - sit in a pool on its world-map player.
When a battle starts, the RTS player's hero seeding moves that whole pool into its revive ledger,
so a fortress's REVIVE buttons offer heroes the map never fielded, at the level the pool holds them.
With the flag set the seeding takes its own "no world-map player" exit instead: the pool is never
collected and stays on the world map as it was, and the battle's ledger holds only the heroes who
die in that battle. What the battle hands back when it ends is untouched.

Shares `Scenario`'s padding with `hide-selection-details` (`+0xC2`), taking the byte after it, and
composes with it in either order: the widened constructor store that zeroes both is written by
whichever patch comes first.

Derivation: `../docs/living-campaign/wotr-battle-hero-pool.md`.
"""

from __future__ import annotations

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
    PLAYER_WOTR_HERO_POOL_SEED,
    PLAYER_WOTR_HERO_POOL_SEED_BYTES,
    PLAYER_WOTR_HERO_POOL_SEED_RESUME,
    PLAYER_WOTR_HERO_POOL_SEED_RESUME_BYTES,
    PLAYER_WOTR_HERO_POOL_SEED_SKIP,
    PLAYER_WOTR_HERO_POOL_SEED_SKIP_BYTES,
    SCENARIO_ALLOC,
    SCENARIO_ALLOC_BYTES,
    SCENARIO_BATTLE_HERO_POOL_OFFSET,
    SCENARIO_CTOR_HISTORICAL,
    SCENARIO_CTOR_HISTORICAL_BYTES,
    SCENARIO_CTOR_USE_MP_RULES,
    SCENARIO_CTOR_USE_MP_RULES_BYTES,
    SCENARIO_CTOR_ZERO,
    SCENARIO_CTOR_ZERO_BYTES,
    SCENARIO_FIELD_TABLE_REF_OPCODES,
    SCENARIO_FIELD_TABLE_REFS,
    SCENARIO_HISTORICAL,
    SCENARIO_USE_MP_RULES,
    THE_LIVING_WORLD_CAMPAIGN_MANAGER,
)
from ...asm import JAE, JE, JL, JNE, Asm
from ...patcher import Patch
from ...utils import (
    allocate_section,
    apply_byte_patch,
    file_offset,
    find_section,
    jmp_rel32,
    read_cstring,
    u32,
)
from ..experimental.hide_selection_details import rewritten_default, validate_keyword
from ..utils.field_tables import Entry, entries_before, read_field_table, resolve_table

if TYPE_CHECKING:
    import argparse

__all__ = [
    "ANCHORS",
    "DEFAULT_KEYWORD",
    "SECTION_NAME",
    "WotrBattleHeroPoolPatch",
    "build_code",
    "build_table",
]

SECTION_NAME = ".wbhpl"

#: The INI keyword the new `Scenario` field is parsed under.
DEFAULT_KEYWORD = "NoBattleHeroPool"

#: IMAGE_SCN_CNT_CODE | CNT_INITIALIZED_DATA | MEM_EXECUTE | MEM_READ. The cave holds the keyword
#: and the rebuilt table (read) and two routines (executed); nothing in it is written.
_CHARACTERISTICS = 0x20 | 0x40 | 0x20000000 | 0x40000000

#: Bytes the patch reads rather than writes: the struct is big enough for the flag, the
#: constructor zeroes from `ebx` and re-sets `+0xC1` after the widened store, the manager and the
#: campaign keep the layout the flag is read through, and the seeding resumes and leaves where the
#: hook expects.
ANCHORS: dict[int, bytes] = {
    SCENARIO_ALLOC: SCENARIO_ALLOC_BYTES,
    SCENARIO_CTOR_ZERO: SCENARIO_CTOR_ZERO_BYTES,
    SCENARIO_CTOR_USE_MP_RULES: SCENARIO_CTOR_USE_MP_RULES_BYTES,
    LIVING_WORLD_CAMPAIGN_MANAGER_CURRENT_READ: LIVING_WORLD_CAMPAIGN_MANAGER_CURRENT_READ_BYTES,
    LIVING_WORLD_CAMPAIGN_SCENARIO_READ: LIVING_WORLD_CAMPAIGN_SCENARIO_READ_BYTES,
    PLAYER_WOTR_HERO_POOL_SEED_RESUME: PLAYER_WOTR_HERO_POOL_SEED_RESUME_BYTES,
    PLAYER_WOTR_HERO_POOL_SEED_SKIP: PLAYER_WOTR_HERO_POOL_SEED_SKIP_BYTES,
}

#: Fields the live table must still carry at these offsets, or this is not the build the layout was
#: derived against. Checked by name, so another patch having appended to the table first is fine.
FINGERPRINT = {
    "DisableRegions": 0x1C,
    "HistoricalScenario": SCENARIO_HISTORICAL,
    "UseMpRulesVictoryCondition": SCENARIO_USE_MP_RULES,
}


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


def build_table(entries: tuple[Entry, ...], keyword_va: int) -> bytes:
    """The rebuilt field-parse table: the live rows verbatim, the new `Bool`, the terminator."""
    table = bytearray()
    for entry in entries:
        table += struct.pack("<IIII", *entry)
    table += struct.pack("<IIII", keyword_va, INI_PARSE_BOOL, 0, SCENARIO_BATTLE_HERO_POOL_OFFSET)
    return bytes(table) + bytes(FIELD_PARSE_STRIDE)


def build_code(code_va: int) -> Asm:
    """The cave's two routines, laid out at the address they will occupy.

    `seed` replaces the seeding's load of the world-map player id and is reached by the hook's
    `jmp`, with `ebx` the RTS player and `esi`/`edi` pushed, which is the stack both the resume and
    the skip expect. `scenario_flag` keeps every register but `eax`."""
    a = Asm(code_va)

    a.label("seed")  # in place of `mov eax, [ebx+0x3CC]`
    a.call("scenario_flag")
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JNE, "skip")
    a.emit(PLAYER_WOTR_HERO_POOL_SEED_BYTES)  # mov eax, [ebx+0x3CC]   ; the world-map player id
    a.jmp_absolute(PLAYER_WOTR_HERO_POOL_SEED_RESUME)
    a.label("skip")  # the pool stays on the world map
    a.jmp_absolute(PLAYER_WOTR_HERO_POOL_SEED_SKIP)

    a.label("scenario_flag")  # eax = the current scenario's flag, 0 when there is none
    a.emit(0x51, 0x52)  # push ecx / push edx
    a.emit(0x33, 0xC0)  # xor eax, eax
    a.emit(0x8B, 0x0D, u32(THE_LIVING_WORLD_CAMPAIGN_MANAGER))  # mov ecx, [manager]
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
    a.emit(0x0F, 0xB6, 0x81, u32(SCENARIO_BATTLE_HERO_POOL_OFFSET))  # movzx eax, byte [ecx+0xC3]
    a.jmp_short("flag_out")
    a.label("flag_none")
    a.emit(0x33, 0xC0)  # xor eax, eax
    a.label("flag_out")
    a.emit(0x5A, 0x59, 0xC3)  # pop edx / pop ecx / ret
    return a


class WotrBattleHeroPoolPatch(Patch):
    """Add a `NoBattleHeroPool` boolean to `Scenario`, keeping the world-map hero pool out of
    the revive ledger of that scenario's battles."""

    name = "wotr-battle-hero-pool"
    author = "officialNecro"
    description = (
        "Add a NoBattleHeroPool boolean to a LivingWorldCampaign's Scenario block: Yes keeps the "
        "world-map hero pool (off-map and unrevived heroes) out of that scenario's battles, so a "
        "battle's REVIVE buttons offer only heroes who died in it. The pool stays on the world "
        "map. No, the default, is stock"
    )

    def __init__(self, keyword: str = DEFAULT_KEYWORD):
        self.keyword = keyword
        validate_keyword(keyword)

    def __str__(self) -> str:
        return f"{self.name} ({self.keyword})"

    def apply(self, data: bytearray) -> None:
        self._check_anchors(data)
        self._check_sites(data)
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
    def _hook(code: Asm) -> tuple[int, bytes, bytes, str]:
        return (
            PLAYER_WOTR_HERO_POOL_SEED,
            PLAYER_WOTR_HERO_POOL_SEED_BYTES,
            jmp_rel32(
                PLAYER_WOTR_HERO_POOL_SEED,
                code.label_va("seed"),
                len(PLAYER_WOTR_HERO_POOL_SEED_BYTES),
            ),
            "the player's world-map hero pool seeding",
        )

    def _edits(
        self, data: bytes | bytearray, pieces: _Layout, code: Asm
    ) -> list[tuple[int, bytes, bytes, str]]:
        """Every byte this patch writes outside its own cave, as
        `(file offset, expected, replacement, note)`. The constructor store is only widened when
        `hide-selection-details` has not already widened it."""
        sites = [self._hook(code)]
        ctor = file_offset(data, SCENARIO_CTOR_HISTORICAL)
        if bytes(data[ctor : ctor + len(SCENARIO_CTOR_HISTORICAL_BYTES)]) != rewritten_default():
            sites.append(
                (
                    SCENARIO_CTOR_HISTORICAL,
                    SCENARIO_CTOR_HISTORICAL_BYTES,
                    rewritten_default(),
                    "the Scenario ctor's HistoricalScenario store",
                )
            )
        edits = [
            (file_offset(data, va), old, new, f"{what} -> {SECTION_NAME}")
            for va, old, new, what in sites
        ]
        for ref_va, opcode in zip(
            SCENARIO_FIELD_TABLE_REFS, SCENARIO_FIELD_TABLE_REF_OPCODES, strict=True
        ):
            off = file_offset(data, ref_va)
            edits.append(
                (
                    off,
                    bytes(data[off : off + 5]),
                    bytes([opcode]) + u32(pieces.table_va),
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
            off = file_offset(data, va)
            got = bytes(data[off : off + len(want)])
            if got != want:
                problems.append(
                    f"0x{va:08x} holds {got.hex()}, expected {want.hex()} - not the build the "
                    "Scenario layout and the hero seeding were read from"
                )
        ctor = file_offset(data, SCENARIO_CTOR_HISTORICAL)
        store = bytes(data[ctor : ctor + len(SCENARIO_CTOR_HISTORICAL_BYTES)])
        if store not in (SCENARIO_CTOR_HISTORICAL_BYTES, rewritten_default()):
            problems.append(
                f"0x{SCENARIO_CTOR_HISTORICAL:08x} holds {store.hex()}, neither the stock "
                "HistoricalScenario store nor the widened one"
            )
        return problems

    @classmethod
    def _check_anchors(cls, data: bytes | bytearray) -> None:
        problems = cls._anchor_problems(data)
        if problems:
            raise ValueError(problems[0])

    @staticmethod
    def _check_sites(data: bytes | bytearray) -> None:
        off = file_offset(data, PLAYER_WOTR_HERO_POOL_SEED)
        got = bytes(data[off : off + len(PLAYER_WOTR_HERO_POOL_SEED_BYTES)])
        if got != PLAYER_WOTR_HERO_POOL_SEED_BYTES:
            raise ValueError(
                f"0x{PLAYER_WOTR_HERO_POOL_SEED:08x} holds {got.hex()}, expected "
                f"{PLAYER_WOTR_HERO_POOL_SEED_BYTES.hex()} - the file already carries this patch, "
                "or is not the expected build"
            )

    def _check_table(self, data: bytes | bytearray, table_va: int) -> tuple[Entry, ...]:
        """The live rows, once the table has been checked for the build, for this keyword and for
        the padding byte still being free."""
        entries = read_field_table(data, table_va)
        by_name = {read_cstring(data, name): offset for name, _fn, _ud, offset in entries}
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
        taken = [n for n, offset in by_name.items() if offset == SCENARIO_BATTLE_HERO_POOL_OFFSET]
        if taken:
            raise ValueError(
                f"Scenario+0x{SCENARIO_BATTLE_HERO_POOL_OFFSET:02x} is already the {taken[0]!r} "
                "field - another patch is using the padding this one stores into"
            )
        return entries

    @classmethod
    def detect(cls, data: bytes | bytearray) -> WotrBattleHeroPoolPatch | None:
        """Recognise this patch and recover its keyword, which opens the cave."""
        located = find_section(data, SECTION_NAME)
        if located is None:
            return None
        keyword = read_cstring(data, located[0])
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
        """Structural check that `data` carries this patch for exactly this keyword, with every
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
            code = build_code(pieces.code_va)
            problems += self._verify_cave(data, pieces, preceding, section_va, vsize)
            problems += self._verify_sites(data, pieces, live, code)
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
        got_keyword = read_cstring(data, pieces.keyword_va)
        if got_keyword != self.keyword:
            problems.append(
                f"the keyword in {SECTION_NAME} is {got_keyword!r}, not {self.keyword!r}"
            )
        want_table = build_table(preceding, pieces.keyword_va)
        table_off = file_offset(data, pieces.table_va)
        if bytes(data[table_off : table_off + len(want_table)]) != want_table:
            problems.append(
                f"the field table at 0x{pieces.table_va:08x} is not the live rows plus a Bool at "
                f"Scenario+0x{SCENARIO_BATTLE_HERO_POOL_OFFSET:02x}"
            )
        code_off = file_offset(data, pieces.code_va)
        if bytes(data[code_off : code_off + len(code)]) != code:
            problems.append(f"the code at 0x{pieces.code_va:08x} is not what this patch builds")
        return problems

    def _verify_sites(
        self, data: bytes | bytearray, pieces: _Layout, live: tuple[Entry, ...], code: Asm
    ) -> list[str]:
        """The hook, the widened store, and the row the engine will actually parse the field
        through - checked in the live table, since a later patch extending `Scenario` copies the
        row into its own."""
        problems: list[str] = []
        va, _old, want, what = self._hook(code)
        off = file_offset(data, va)
        got = bytes(data[off : off + len(want)])
        if got != want:
            problems.append(f"@0x{va:08x}: {what} is not patched (holds {got.hex()})")
        ctor = file_offset(data, SCENARIO_CTOR_HISTORICAL)
        if bytes(data[ctor : ctor + len(SCENARIO_CTOR_HISTORICAL_BYTES)]) != rewritten_default():
            problems.append("the Scenario constructor does not zero the flag")

        want_row = (pieces.keyword_va, INI_PARSE_BOOL, 0, SCENARIO_BATTLE_HERO_POOL_OFFSET)
        row = next((e for e in live if read_cstring(data, e[0]) == self.keyword), None)
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
    def from_cli_args(cls, args: argparse.Namespace) -> WotrBattleHeroPoolPatch:
        return cls(keyword=args.keyword)
