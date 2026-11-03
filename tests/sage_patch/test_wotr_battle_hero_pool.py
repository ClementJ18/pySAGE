"""Tests for the wotr-battle-hero-pool patch.

Three claims hold the patch up:

* the hook replaces exactly the seeding's load of the world-map player id, and `seed` either
  replays that load and resumes on the compare after it, or leaves through the stock "no world-map
  player" exit - the two places whose stack is the hook's own;
* the flag is the byte after `hide-selection-details`' and the widened constructor store zeroes it,
  whichever of the two patches writes that store;
* `scenario_flag` reads the current scenario exactly as `hide-selection-details` does, at
  `+0xC3`.

The stand-in plants every anchor and site at its real address; against a real `game.dat` the same
bytes are read back from the binary.
"""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

from sage_patch import addresses as ad
from sage_patch.patches.campaign.wotr_battle_hero_pool import (
    ANCHORS,
    DEFAULT_KEYWORD,
    SECTION_NAME,
    WotrBattleHeroPoolPatch,
    build_code,
)
from sage_patch.patches.experimental import hide_selection_details as hsd
from sage_patch.patches.experimental.hide_selection_details import (
    HideSelectionDetailsPatch,
    rewritten_default,
)
from sage_patch.patches.utils.field_tables import ROW_SIZE, read_field_table
from sage_patch.registry import PATCHES
from sage_patch.utils import find_section, va_to_offset
from tests.sage_patch.synthetic import _sparse_image

_GAME_DAT = Path(__file__).resolve().parents[2] / "game.dat"

#: Where the stand-in keeps its field names: the start of the page the table sits on.
STRINGS_VA = ad.SCENARIO_FIELD_TABLE & ~0xFFF

STAND_IN_ROWS = (
    ("MaxPlayers", ad.INI_PARSE_INT, 0x10),
    ("DisableRegions", ad.INI_PARSE_STRING_LIST, 0x1C),
    ("HistoricalScenario", ad.INI_PARSE_BOOL, ad.SCENARIO_HISTORICAL),
    ("UseMpRulesVictoryCondition", ad.INI_PARSE_BOOL, ad.SCENARIO_USE_MP_RULES),
)

#: `hide-selection-details`' hooked windows, so the two patches can be applied to one stand-in.
HSD_SITES = {
    ad.SELECTION_DETAILS_TRAY_SET_HAS_CONTENT: ad.SELECTION_DETAILS_TRAY_SET_HAS_CONTENT_BYTES,
    ad.SELECTION_DETAILS_TRAY_OPEN: ad.SELECTION_DETAILS_TRAY_OPEN_BYTES,
}

CODE_BASE = 0x00F00000

Row = tuple[str, int, int]


def _table(rows: tuple[Row, ...]) -> tuple[bytes, bytes]:
    strings = bytearray()
    table = bytearray()
    for name, parse, offset in rows:
        table += struct.pack("<IIII", STRINGS_VA + len(strings), parse, 0, offset)
        strings += name.encode("ascii") + b"\x00"
    return bytes(strings), bytes(table) + bytes(ROW_SIZE)


def stand_in(rows: tuple[Row, ...] = STAND_IN_ROWS) -> bytearray:
    strings, table = _table(rows)
    ref = b"\x68" + struct.pack("<I", ad.SCENARIO_FIELD_TABLE)
    return _sparse_image(
        {
            **hsd.ANCHORS,
            **ANCHORS,
            STRINGS_VA: strings,
            ad.SCENARIO_FIELD_TABLE: table,
            **{va: ref for va in ad.SCENARIO_FIELD_TABLE_REFS},
            ad.SCENARIO_CTOR_HISTORICAL: ad.SCENARIO_CTOR_HISTORICAL_BYTES,
            ad.PLAYER_WOTR_HERO_POOL_SEED: ad.PLAYER_WOTR_HERO_POOL_SEED_BYTES,
            **HSD_SITES,
        }
    )


def applied(keyword: str = DEFAULT_KEYWORD) -> bytearray:
    data = stand_in()
    WotrBattleHeroPoolPatch(keyword).apply(data)
    return data


def _disasm(blob: bytes, va: int) -> list[tuple[str, str]]:
    capstone = pytest.importorskip("capstone")
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    return [(insn.mnemonic, insn.op_str) for insn in md.disasm(blob, va)]


def _routine(name: str, end: str | None = None) -> tuple[bytes, int]:
    """One routine's bytes out of the assembled cave, up to the next label."""
    code = build_code(CODE_BASE)
    blob = code.finish()
    start = code.label_va(name) - CODE_BASE
    stop = code.label_va(end) - CODE_BASE if end else len(blob)
    return blob[start:stop], CODE_BASE + start


def _row(data: bytearray, keyword: str) -> tuple[int, int, int, int] | None:
    ref = va_to_offset(data, ad.SCENARIO_FIELD_TABLE_REFS[0])
    assert ref is not None
    table_va = struct.unpack_from("<I", data, ref + 1)[0]
    for entry in read_field_table(data, table_va):
        name_off = va_to_offset(data, entry[0])
        assert name_off is not None
        if data[name_off : name_off + len(keyword) + 1] == keyword.encode() + b"\x00":
            return entry
    return None


class TestStockSites:
    def test_the_hook_is_the_world_map_player_id_load(self) -> None:
        listing = _disasm(ad.PLAYER_WOTR_HERO_POOL_SEED_BYTES, ad.PLAYER_WOTR_HERO_POOL_SEED)
        assert listing == [("mov", "eax, dword ptr [ebx + 0x3cc]")]

    def test_it_resumes_on_the_compare_after_it(self) -> None:
        end = ad.PLAYER_WOTR_HERO_POOL_SEED + len(ad.PLAYER_WOTR_HERO_POOL_SEED_BYTES)
        assert end == ad.PLAYER_WOTR_HERO_POOL_SEED_RESUME
        listing = _disasm(
            ad.PLAYER_WOTR_HERO_POOL_SEED_RESUME_BYTES, ad.PLAYER_WOTR_HERO_POOL_SEED_RESUME
        )
        assert listing == [("cmp", "eax, -1")]

    def test_the_skip_pops_what_the_function_pushed(self) -> None:
        listing = _disasm(
            ad.PLAYER_WOTR_HERO_POOL_SEED_SKIP_BYTES, ad.PLAYER_WOTR_HERO_POOL_SEED_SKIP
        )
        assert listing == [
            ("mov", "ecx, dword ptr [ebp - 0xc]"),
            ("pop", "edi"),
            ("pop", "esi"),
            ("pop", "ebx"),
        ]

    def test_the_flag_byte_is_inside_the_allocation_and_after_the_tray_flag(self) -> None:
        assert ad.SCENARIO_FREE_OFFSET < ad.SCENARIO_BATTLE_HERO_POOL_OFFSET < ad.SCENARIO_SIZE
        assert ad.SCENARIO_BATTLE_HERO_POOL_OFFSET - ad.SCENARIO_HISTORICAL < 4  # in the dword

    @pytest.mark.skipif(not _GAME_DAT.exists(), reason="needs the real game.dat")
    def test_the_real_binary_carries_the_stock_bytes(self) -> None:
        stock = _GAME_DAT.read_bytes()
        planted = {
            **ANCHORS,
            ad.SCENARIO_CTOR_HISTORICAL: ad.SCENARIO_CTOR_HISTORICAL_BYTES,
            ad.PLAYER_WOTR_HERO_POOL_SEED: ad.PLAYER_WOTR_HERO_POOL_SEED_BYTES,
        }
        for va, expected in planted.items():
            off = va_to_offset(stock, va)
            assert off is not None
            assert stock[off : off + len(expected)] == expected, hex(va)


class TestCode:
    def test_seed_replays_the_load_or_leaves_through_the_skip(self) -> None:
        blob, va = _routine("seed", "scenario_flag")
        listing = _disasm(blob, va)
        code = build_code(CODE_BASE)
        assert listing == [
            ("call", f"{code.label_va('scenario_flag'):#x}"),
            ("test", "eax, eax"),
            ("jne", f"{code.label_va('skip'):#x}"),
            ("mov", "eax, dword ptr [ebx + 0x3cc]"),
            ("jmp", f"{ad.PLAYER_WOTR_HERO_POOL_SEED_RESUME:#x}"),
            ("jmp", f"{ad.PLAYER_WOTR_HERO_POOL_SEED_SKIP:#x}"),
        ]

    def test_scenario_flag_reads_the_byte_after_the_tray_flag(self) -> None:
        blob, va = _routine("scenario_flag")
        body = [f"{mnemonic} {operands}" for mnemonic, operands in _disasm(blob, va)]
        assert f"movzx eax, byte ptr [ecx + {ad.SCENARIO_BATTLE_HERO_POOL_OFFSET:#x}]" in body
        theirs = hsd.build_code(CODE_BASE)
        start = theirs.label_va("scenario_flag") - CODE_BASE
        their_body = [f"{m} {o}" for m, o in _disasm(theirs.finish()[start:], CODE_BASE + start)]
        assert [line for line in body if "movzx" not in line and not line.startswith("j")] == [
            line for line in their_body if "movzx" not in line and not line.startswith("j")
        ], "the same walk of the campaign manager as hide-selection-details"


class TestApply:
    def test_applies_and_verifies(self) -> None:
        assert WotrBattleHeroPoolPatch().verify(applied()) == []

    def test_a_stock_image_does_not_carry_it(self) -> None:
        problems = WotrBattleHeroPoolPatch().verify(stand_in())
        assert problems == [f"no {SECTION_NAME} section: the file does not carry this patch"]

    def test_detect_recovers_the_keyword(self) -> None:
        assert WotrBattleHeroPoolPatch.detect(stand_in()) is None
        found = WotrBattleHeroPoolPatch.detect(applied("KeepPoolOnMap"))
        assert isinstance(found, WotrBattleHeroPoolPatch)
        assert found.keyword == "KeepPoolOnMap"

    def test_alone_it_widens_the_constructor_store(self) -> None:
        data = applied()
        off = va_to_offset(data, ad.SCENARIO_CTOR_HISTORICAL)
        assert off is not None
        assert data[off : off + 6] == rewritten_default()

    def test_the_hook_lands_on_seed(self) -> None:
        data = applied()
        located = find_section(data, SECTION_NAME)
        assert located is not None
        off = va_to_offset(data, ad.PLAYER_WOTR_HERO_POOL_SEED)
        assert off is not None
        assert data[off] == 0xE9
        target = ad.PLAYER_WOTR_HERO_POOL_SEED + 5 + struct.unpack_from("<i", data, off + 1)[0]
        assert located[0] <= target < located[0] + located[2]
        assert data[off + 5] == 0x90

    def test_after_hide_selection_details_both_fields_are_live(self) -> None:
        data = stand_in()
        HideSelectionDetailsPatch().apply(data)
        WotrBattleHeroPoolPatch().apply(data)
        assert HideSelectionDetailsPatch().verify(data) == []
        assert WotrBattleHeroPoolPatch().verify(data) == []
        assert _row(data, "HideSelectionDetails") is not None
        row = _row(data, DEFAULT_KEYWORD)
        assert row is not None
        assert row[1:] == (ad.INI_PARSE_BOOL, 0, ad.SCENARIO_BATTLE_HERO_POOL_OFFSET)

    def test_before_hide_selection_details_both_fields_are_live(self) -> None:
        """The registry lists this settled patch ahead of the experimental one, so a regenerated
        manifest applies them this way round. Both widen the same constructor store, and the
        second must leave it alone rather than refuse it."""
        data = stand_in()
        WotrBattleHeroPoolPatch().apply(data)
        HideSelectionDetailsPatch().apply(data)
        assert HideSelectionDetailsPatch().verify(data) == []
        assert WotrBattleHeroPoolPatch().verify(data) == []
        assert _row(data, "HideSelectionDetails") is not None
        assert _row(data, DEFAULT_KEYWORD) is not None
        off = va_to_offset(data, ad.SCENARIO_CTOR_HISTORICAL)
        assert off is not None
        widened = bytes(data[off : off + len(ad.SCENARIO_CTOR_HISTORICAL_BYTES)])
        assert widened == hsd.rewritten_default()

    def test_applying_twice_raises(self) -> None:
        data = applied()
        with pytest.raises(ValueError, match="already"):
            WotrBattleHeroPoolPatch().apply(data)

    def test_a_moved_anchor_is_refused(self) -> None:
        data = stand_in()
        off = va_to_offset(data, ad.PLAYER_WOTR_HERO_POOL_SEED_SKIP)
        assert off is not None
        data[off] ^= 0xFF
        with pytest.raises(ValueError, match="not the build"):
            WotrBattleHeroPoolPatch().apply(data)

    def test_a_table_already_using_the_byte_is_refused(self) -> None:
        squatter = ("Squatter", ad.INI_PARSE_BOOL, ad.SCENARIO_BATTLE_HERO_POOL_OFFSET)
        data = stand_in((*STAND_IN_ROWS, squatter))
        with pytest.raises(ValueError, match="padding"):
            WotrBattleHeroPoolPatch().apply(data)

    def test_the_ini_surface_is_one_scenario_bool(self) -> None:
        (field,) = WotrBattleHeroPoolPatch().ini_surface().fields
        assert (field.block, field.name, field.type, field.default) == (
            "Scenario",
            DEFAULT_KEYWORD,
            "Bool",
            False,
        )


class TestRegistration:
    def test_it_is_registered_and_not_experimental(self) -> None:
        assert PATCHES["wotr-battle-hero-pool"] is WotrBattleHeroPoolPatch
        assert WotrBattleHeroPoolPatch().experimental is False

    def test_the_description_names_the_field_and_the_block(self) -> None:
        assert DEFAULT_KEYWORD in WotrBattleHeroPoolPatch.description
        assert "Scenario" in WotrBattleHeroPoolPatch.description
        assert not WotrBattleHeroPoolPatch.description.endswith(".")
