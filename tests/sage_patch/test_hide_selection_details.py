"""Tests for the hide-selection-details patch.

Four claims hold the patch up, and "it applies and verifies" checks none of them:

* the field fits in `Scenario`'s padding and the widened constructor store zeroes it without
  losing `UseMpRulesVictoryCondition`'s `Yes`;
* each hook replaces whole instructions, none of them a `call`, and resumes on the instruction
  after them - a hook that splits one assembles, applies and verifies, then faults in game;
* `has_content` keeps the argument when the flag is clear and stores zero when it is set, and
  leaves the flags of the compare the stock `je` reads; `open` returns before touching the tray;
* `scenario_flag` walks the manager the way the manager itself does and keeps `ecx` and `edx`.

The stand-in plants every anchor and site at its real address; against a real `game.dat` the same
bytes are read back from the binary.
"""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

from sage_patch import addresses as ad
from sage_patch.patches.experimental.hide_selection_details import (
    ANCHORS,
    DEFAULT_KEYWORD,
    SECTION_NAME,
    HideSelectionDetailsPatch,
    build_code,
    rewritten_default,
    validate_keyword,
)
from sage_patch.patches.utils.field_tables import ROW_SIZE, read_field_table
from sage_patch.registry import PATCHES
from sage_patch.utils import find_section, va_to_offset
from tests.sage_patch.synthetic import _sparse_image

_GAME_DAT = Path(__file__).resolve().parents[2] / "game.dat"

#: Where the stand-in keeps its field names: the start of the page the table sits on.
STRINGS_VA = ad.SCENARIO_FIELD_TABLE & ~0xFFF

#: Enough of the stock table to carry the rows the patch checks.
STAND_IN_ROWS = (
    ("MaxPlayers", ad.INI_PARSE_INT, 0x10),
    ("DisableRegions", ad.INI_PARSE_STRING_LIST, 0x1C),
    ("HistoricalScenario", ad.INI_PARSE_BOOL, ad.SCENARIO_HISTORICAL),
    ("UseMpRulesVictoryCondition", ad.INI_PARSE_BOOL, ad.SCENARIO_USE_MP_RULES),
)

#: The two hooked windows, as the stock binary holds them.
SITES = {
    ad.SELECTION_DETAILS_TRAY_SET_HAS_CONTENT: ad.SELECTION_DETAILS_TRAY_SET_HAS_CONTENT_BYTES,
    ad.SELECTION_DETAILS_TRAY_OPEN: ad.SELECTION_DETAILS_TRAY_OPEN_BYTES,
}

#: An address to assemble at when only the shape of the code is under test.
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
            **ANCHORS,
            STRINGS_VA: strings,
            ad.SCENARIO_FIELD_TABLE: table,
            **{va: ref for va in ad.SCENARIO_FIELD_TABLE_REFS},
            ad.SCENARIO_CTOR_HISTORICAL: ad.SCENARIO_CTOR_HISTORICAL_BYTES,
            **SITES,
        }
    )


def applied(keyword: str = DEFAULT_KEYWORD) -> bytearray:
    data = stand_in()
    HideSelectionDetailsPatch(keyword).apply(data)
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


class TestStockSites:
    def test_set_has_content_is_the_load_and_the_compare(self) -> None:
        va = ad.SELECTION_DETAILS_TRAY_SET_HAS_CONTENT
        listing = _disasm(ad.SELECTION_DETAILS_TRAY_SET_HAS_CONTENT_BYTES, va)
        assert listing == [
            ("mov", "al, byte ptr [esp + 4]"),
            ("cmp", f"al, byte ptr [ecx + {ad.SELECTION_DETAILS_TRAY_HAS_CONTENT:#x}]"),
        ]
        assert va + len(ad.SELECTION_DETAILS_TRAY_SET_HAS_CONTENT_BYTES) == (
            ad.SELECTION_DETAILS_TRAY_SET_HAS_CONTENT_RESUME
        )

    def test_open_is_three_whole_instructions(self) -> None:
        va = ad.SELECTION_DETAILS_TRAY_OPEN
        assert _disasm(ad.SELECTION_DETAILS_TRAY_OPEN_BYTES, va) == [
            ("push", "esi"),
            ("mov", "esi, ecx"),
            ("mov", "eax, dword ptr [esi + 0x18]"),
        ]
        assert (
            va + len(ad.SELECTION_DETAILS_TRAY_OPEN_BYTES) == ad.SELECTION_DETAILS_TRAY_OPEN_RESUME
        )

    def test_neither_hook_displaces_a_call(self) -> None:
        for window in (
            ad.SELECTION_DETAILS_TRAY_SET_HAS_CONTENT_BYTES,
            ad.SELECTION_DETAILS_TRAY_OPEN_BYTES,
        ):
            assert window[0] not in (0xE8, 0xE9)

    def test_the_vtable_thunk_jumps_to_open(self) -> None:
        va = ad.SELECTION_DETAILS_TRAY_OPEN_THUNK
        mnemonic, target = _disasm(ad.SELECTION_DETAILS_TRAY_OPEN_THUNK_BYTES, va)[0]
        assert mnemonic == "jmp"
        assert int(target, 16) == ad.SELECTION_DETAILS_TRAY_OPEN

    def test_the_padding_is_inside_the_allocation(self) -> None:
        (mnemonic, operand), *_ = _disasm(ad.SCENARIO_ALLOC_BYTES, ad.SCENARIO_ALLOC)
        assert (mnemonic, int(operand, 16)) == ("push", ad.SCENARIO_SIZE)
        assert ad.SCENARIO_USE_MP_RULES < ad.SCENARIO_FREE_OFFSET < ad.SCENARIO_SIZE

    @pytest.mark.skipif(not _GAME_DAT.exists(), reason="needs the real game.dat")
    def test_the_real_binary_carries_the_stock_bytes(self) -> None:
        stock = _GAME_DAT.read_bytes()
        planted = {
            **ANCHORS,
            ad.SCENARIO_CTOR_HISTORICAL: ad.SCENARIO_CTOR_HISTORICAL_BYTES,
            **SITES,
        }
        for va, expected in planted.items():
            off = va_to_offset(stock, va)
            assert off is not None
            assert stock[off : off + len(expected)] == expected, hex(va)

    @pytest.mark.skipif(not _GAME_DAT.exists(), reason="needs the real game.dat")
    def test_the_real_table_leaves_the_padding_unnamed(self) -> None:
        stock = _GAME_DAT.read_bytes()
        rows = read_field_table(stock, ad.SCENARIO_FIELD_TABLE)
        offsets = {row[3] for row in rows}
        assert {ad.SCENARIO_HISTORICAL, ad.SCENARIO_USE_MP_RULES} <= offsets
        assert not any(ad.SCENARIO_USE_MP_RULES < offset < ad.SCENARIO_SIZE for offset in offsets)


class TestDefault:
    def test_the_widened_store_zeroes_the_whole_dword(self) -> None:
        listing = _disasm(rewritten_default(), ad.SCENARIO_CTOR_HISTORICAL)
        assert listing == [("mov", f"dword ptr [esi + {ad.SCENARIO_HISTORICAL:#x}], ebx")]
        assert len(rewritten_default()) == len(ad.SCENARIO_CTOR_HISTORICAL_BYTES)

    def test_use_mp_rules_is_set_again_straight_after(self) -> None:
        end = ad.SCENARIO_CTOR_HISTORICAL + len(ad.SCENARIO_CTOR_HISTORICAL_BYTES)
        assert end == ad.SCENARIO_CTOR_USE_MP_RULES
        listing = _disasm(ad.SCENARIO_CTOR_USE_MP_RULES_BYTES, ad.SCENARIO_CTOR_USE_MP_RULES)
        assert listing == [("mov", f"byte ptr [esi + {ad.SCENARIO_USE_MP_RULES:#x}], 1")]

    def test_ebx_is_the_constructors_zero(self) -> None:
        assert _disasm(ad.SCENARIO_CTOR_ZERO_BYTES, ad.SCENARIO_CTOR_ZERO) == [("xor", "ebx, ebx")]


class TestCode:
    def test_has_content_stores_zero_only_when_the_flag_is_set(self) -> None:
        blob, va = _routine("has_content", "open")
        listing = _disasm(blob, va)
        code = build_code(CODE_BASE)
        assert listing[0] == ("call", hex(code.label_va("scenario_flag")))
        assert listing[1] == ("test", "eax, eax")
        # the load sits between the test and the branch, and a mov leaves the flags alone
        assert listing[2] == ("mov", "al, byte ptr [esp + 4]")
        assert listing[3][0] == "je"
        assert listing[4] == ("xor", "al, al")
        assert int(listing[3][1], 16) == code.label_va("store")
        assert listing[5] == (
            "cmp",
            f"al, byte ptr [ecx + {ad.SELECTION_DETAILS_TRAY_HAS_CONTENT:#x}]",
        )
        assert listing[6] == ("jmp", hex(ad.SELECTION_DETAILS_TRAY_SET_HAS_CONTENT_RESUME))
        assert len(listing) == 7

    def test_open_returns_before_the_stock_body(self) -> None:
        blob, va = _routine("open", "scenario_flag")
        listing = _disasm(blob, va)
        code = build_code(CODE_BASE)
        assert listing[:2] == [("call", hex(code.label_va("scenario_flag"))), ("test", "eax, eax")]
        assert listing[2] == ("je", hex(code.label_va("open_stock")))
        assert listing[3] == ("ret", "")
        assert listing[4:7] == _disasm(
            ad.SELECTION_DETAILS_TRAY_OPEN_BYTES, code.label_va("open_stock")
        )
        assert listing[7] == ("jmp", hex(ad.SELECTION_DETAILS_TRAY_OPEN_RESUME))

    def test_scenario_flag_walks_the_manager_as_the_manager_does(self) -> None:
        blob, va = _routine("scenario_flag")
        listing = _disasm(blob, va)
        assert listing[:3] == [("push", "ecx"), ("push", "edx"), ("xor", "eax, eax")]
        assert listing[-3:] == [("pop", "edx"), ("pop", "ecx"), ("ret", "")]
        body = [f"{mnemonic} {operands}" for mnemonic, operands in listing]
        manager = ad.THE_LIVING_WORLD_CAMPAIGN_MANAGER
        for expected in (
            f"mov ecx, dword ptr [{manager:#x}]",
            f"mov edx, dword ptr [ecx + {ad.LIVING_WORLD_CAMPAIGN_MANAGER_CURRENT:#x}]",
            f"mov eax, dword ptr [ecx + {ad.LIVING_WORLD_CAMPAIGN_MANAGER_CAMPAIGNS_END:#x}]",
            f"sub eax, dword ptr [ecx + {ad.LIVING_WORLD_CAMPAIGN_MANAGER_CAMPAIGNS_BEGIN:#x}]",
            "mov ecx, dword ptr [ecx + edx*4]",
            f"mov ecx, dword ptr [ecx + {ad.LIVING_WORLD_CAMPAIGN_SCENARIO:#x}]",
            f"movzx eax, byte ptr [ecx + {ad.SCENARIO_FREE_OFFSET:#x}]",
        ):
            assert expected in body, expected
        # the manager's own reader bounds the index the same way
        stock = _disasm(
            ad.LIVING_WORLD_CAMPAIGN_MANAGER_CURRENT_READ_BYTES,
            ad.LIVING_WORLD_CAMPAIGN_MANAGER_CURRENT_READ,
        )
        assert ("jl", "0x7b9764") in stock and ("jae", "0x7b9764") in stock
        assert any(mnemonic == "jl" for mnemonic, _ in listing)
        assert any(mnemonic == "jae" for mnemonic, _ in listing)


class TestApply:
    def test_applies_and_verifies(self) -> None:
        assert HideSelectionDetailsPatch().verify(applied()) == []

    def test_a_stock_image_does_not_carry_it(self) -> None:
        problems = HideSelectionDetailsPatch().verify(stand_in())
        assert problems == [f"no {SECTION_NAME} section: the file does not carry this patch"]

    def test_detect_recovers_the_keyword(self) -> None:
        assert HideSelectionDetailsPatch.detect(stand_in()) is None
        found = HideSelectionDetailsPatch.detect(applied("NoTray"))
        assert isinstance(found, HideSelectionDetailsPatch)
        assert found.keyword == "NoTray"

    def test_the_row_is_appended_to_the_live_rows(self) -> None:
        data = applied()
        ref = va_to_offset(data, ad.SCENARIO_FIELD_TABLE_REFS[0])
        assert ref is not None
        assert data[ref] == 0x68
        table_va = struct.unpack_from("<I", data, ref + 1)[0]
        located = find_section(data, SECTION_NAME)
        assert located is not None
        assert located[0] <= table_va < located[0] + located[2]
        rows = read_field_table(data, table_va)
        stock = read_field_table(stand_in(), ad.SCENARIO_FIELD_TABLE)
        assert rows[:-1] == stock
        name, parse, user_data, offset = rows[-1]
        assert (parse, user_data, offset) == (ad.INI_PARSE_BOOL, 0, ad.SCENARIO_FREE_OFFSET)
        assert name == located[0]  # the keyword opens the cave

    def test_the_constructor_and_both_hooks_are_rewritten(self) -> None:
        data = applied()
        for va, before in (
            (ad.SCENARIO_CTOR_HISTORICAL, ad.SCENARIO_CTOR_HISTORICAL_BYTES),
            (
                ad.SELECTION_DETAILS_TRAY_SET_HAS_CONTENT,
                ad.SELECTION_DETAILS_TRAY_SET_HAS_CONTENT_BYTES,
            ),
            (ad.SELECTION_DETAILS_TRAY_OPEN, ad.SELECTION_DETAILS_TRAY_OPEN_BYTES),
        ):
            off = va_to_offset(data, va)
            assert off is not None
            assert data[off : off + len(before)] != before
        off = va_to_offset(data, ad.SCENARIO_CTOR_HISTORICAL)
        assert off is not None
        assert data[off : off + 6] == rewritten_default()

    def test_the_hooks_land_on_their_routines(self) -> None:
        data = applied()
        located = find_section(data, SECTION_NAME)
        assert located is not None
        for va, window in (
            (
                ad.SELECTION_DETAILS_TRAY_SET_HAS_CONTENT,
                ad.SELECTION_DETAILS_TRAY_SET_HAS_CONTENT_BYTES,
            ),
            (ad.SELECTION_DETAILS_TRAY_OPEN, ad.SELECTION_DETAILS_TRAY_OPEN_BYTES),
        ):
            off = va_to_offset(data, va)
            assert off is not None
            assert data[off] == 0xE9
            target = va + 5 + struct.unpack_from("<i", data, off + 1)[0]
            assert located[0] <= target < located[0] + located[2]
            assert set(data[off + 5 : off + len(window)]) <= {0x90}

    def test_applying_twice_raises(self) -> None:
        data = applied()
        with pytest.raises(ValueError, match="already"):
            HideSelectionDetailsPatch().apply(data)

    def test_a_moved_anchor_is_refused(self) -> None:
        data = stand_in()
        off = va_to_offset(data, ad.SCENARIO_ALLOC)
        assert off is not None
        data[off + 1] = 0xC2  # a Scenario too small to hold the field
        with pytest.raises(ValueError, match="not the build"):
            HideSelectionDetailsPatch().apply(data)

    def test_a_table_already_using_the_padding_is_refused(self) -> None:
        data = stand_in((*STAND_IN_ROWS, ("Squatter", ad.INI_PARSE_BOOL, ad.SCENARIO_FREE_OFFSET)))
        with pytest.raises(ValueError, match="padding"):
            HideSelectionDetailsPatch().apply(data)

    def test_a_different_build_is_refused(self) -> None:
        data = stand_in(STAND_IN_ROWS[:2])
        with pytest.raises(ValueError, match="HistoricalScenario"):
            HideSelectionDetailsPatch().apply(data)

    @pytest.mark.parametrize("keyword", ["", "1Tray", "Hide Tray", "Hide-Tray"])
    def test_a_keyword_the_reader_cannot_match_is_refused(self, keyword: str) -> None:
        with pytest.raises(ValueError):
            validate_keyword(keyword)

    def test_the_ini_surface_is_one_scenario_bool(self) -> None:
        (field,) = HideSelectionDetailsPatch("NoTray").ini_surface().fields
        assert (field.block, field.name, field.type, field.default) == (
            "Scenario",
            "NoTray",
            "Bool",
            False,
        )


class TestRegistration:
    def test_it_is_registered_and_experimental(self) -> None:
        assert PATCHES["hide-selection-details"] is HideSelectionDetailsPatch
        assert HideSelectionDetailsPatch().experimental is True

    def test_the_description_names_the_field_and_the_block(self) -> None:
        assert "HideSelectionDetails" in HideSelectionDetailsPatch.description
        assert "Scenario" in HideSelectionDetailsPatch.description
        assert not HideSelectionDetailsPatch.description.endswith(".")
