"""`campaign-army-verbs`: the relocated Act verb table, the two new rows, and the cave behind them.

Static tests only, and that is the whole point of being explicit about it: the patch is a reading
of the disassembly and these are written from the same reading, so they cannot tell a wrong reading
from a right one. What they *can* tell is that the bytes at every site are the build's own, that
the relocated table is the stock one plus exactly two rows, that every branch the cave takes lands
somewhere it is supposed to, and that the INI surface the patch declares is the INI the new verbs
are actually written in.
"""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

from sage_ini.engine import Engine, dump_engine, parse_engine
from sage_ini.model.objects import REGISTRY
from sage_ini.parser import parse
from sage_patch import addresses as ad
from sage_patch.patches.experimental import campaign_army_verbs as cav
from sage_patch.patches.experimental.campaign_army_verbs import (
    FIELD_ROWS,
    NAME_CAPACITY,
    RECORD_CAPACITY,
    RECORD_SIZE,
    SECTION_NAME,
    CampaignArmyVerbsPatch,
    build_cave,
    cave_layout,
)
from sage_patch.registry import PATCHES
from sage_patch.sagepatch import differences, generate_from_patches
from sage_patch.utils import (
    append_section,
    find_section,
    next_section_rva,
    va_to_offset,
)

from .synthetic import campaign_army_verbs_image

# A base that is nothing like a real section address, so a cave that accidentally used the image
# base or a hardcoded RVA would not pass by coincidence.
FAKE_BASE = 0x0AB00000

_GAME_DAT = Path(__file__).resolve().parents[2] / "game.dat"


def patched() -> bytearray:
    data = campaign_army_verbs_image()
    CampaignArmyVerbsPatch().apply(data)
    return data


def cave_of(data: bytes | bytearray) -> tuple[int, int]:
    located = find_section(data, SECTION_NAME)
    assert located is not None
    section_va, section_off, _ = located
    return section_va, section_off


def rows(table: bytes) -> list[tuple[int, int, int, int]]:
    """A verb/field table as `(name, parse, userData, offset)` tuples, terminator included."""
    return [
        struct.unpack_from("<IIII", table, index * ad.ACT_VERB_ROW_SIZE)
        for index in range(len(table) // ad.ACT_VERB_ROW_SIZE)
    ]


def read_cstring(data: bytes | bytearray, va: int) -> str:
    off = va_to_offset(data, va)
    assert off is not None
    end = data.index(0, off)
    return bytes(data[off:end]).decode("ascii")


class TestLayout:
    """The cave's regions, before any of them holds anything."""

    def test_regions_do_not_overlap(self) -> None:
        layout = cave_layout()
        bounds = [
            ("count", layout["count"], 4),
            ("records", layout["records"], RECORD_CAPACITY * RECORD_SIZE),
            ("verb_table", layout["verb_table"], (ad.ACT_VERB_ROW_COUNT + 3) * 16),
            ("field_table", layout["field_table"], (len(FIELD_ROWS) + 1) * 16),
        ]
        for (_, start, size), (_, next_start, _) in zip(bounds, bounds[1:], strict=False):
            assert start + size <= next_start

    def test_strings_sit_between_the_field_table_and_the_code(self) -> None:
        layout = cave_layout()
        starts = [value for key, value in layout.items() if key.startswith("str:")]
        assert starts, "the cave declares no strings"
        field_end = layout["field_table"] + (len(FIELD_ROWS) + 1) * 16
        assert min(starts) >= field_end
        assert max(starts) < layout["code"]

    def test_record_fields_fit_the_record(self) -> None:
        # Four names and three flag bytes, and nothing overlapping anything.
        assert cav._REC_ACT + NAME_CAPACITY <= cav._REC_SOURCE
        assert cav._REC_SOURCE + NAME_CAPACITY <= cav._REC_DEST
        assert cav._REC_DEST + NAME_CAPACITY <= cav._REC_TEMPLATE
        assert cav._REC_TEMPLATE + NAME_CAPACITY <= cav._REC_KIND
        assert cav._REC_DESPAWN < RECORD_SIZE

    def test_scratch_fields_fit_the_scratch(self) -> None:
        for _, _, offset in FIELD_ROWS:
            assert 0 <= offset < cav._SCRATCH_SIZE


class TestStockSites:
    """What the patch asserts before it changes anything."""

    def test_the_three_sites_hold_the_build_bytes(self) -> None:
        data = campaign_army_verbs_image()
        for va, expected in (
            (ad.ACT_VERB_TABLE, ad.ACT_VERB_TABLE_BYTES),
            (ad.ACT_VERB_TABLE_PUSH_SITE, ad.ACT_VERB_TABLE_PUSH_SITE_BYTES),
            (ad.ACT_RUN_PASS9_CALL, ad.ACT_RUN_PASS9_CALL_BYTES),
        ):
            off = va_to_offset(data, va)
            assert off is not None
            assert bytes(data[off : off + len(expected)]) == expected

    def test_the_push_names_the_table(self) -> None:
        # The immediate the patch repoints has to be the table it relocates, or it is repointing
        # something else.
        assert ad.ACT_VERB_TABLE_PUSH_SITE_BYTES[0] == 0x68
        named = struct.unpack_from("<I", ad.ACT_VERB_TABLE_PUSH_SITE_BYTES, 1)[0]
        assert named == ad.ACT_VERB_TABLE
        assert ad.ACT_VERB_TABLE_PUSH == ad.ACT_VERB_TABLE_PUSH_SITE + 1

    def test_the_displaced_call_is_pass_nine(self) -> None:
        assert ad.ACT_RUN_PASS9_CALL_BYTES[0] == 0xE8
        displacement = struct.unpack_from("<i", ad.ACT_RUN_PASS9_CALL_BYTES, 1)[0]
        target = ad.ACT_RUN_PASS9_CALL + 5 + displacement
        assert target == ad.ACT_SET_PLAYER_CONTROL_EXEC

    def test_the_stock_table_is_fifteen_rows_and_a_terminator(self) -> None:
        decoded = rows(ad.ACT_VERB_TABLE_BYTES)
        assert len(decoded) == ad.ACT_VERB_ROW_COUNT + 1
        assert decoded[-1] == (0, 0, 0, 0)
        assert all(name and parse for name, parse, _, _ in decoded[:-1])

    def test_a_changed_verb_table_refuses_to_relocate(self) -> None:
        data = campaign_army_verbs_image()
        off = va_to_offset(data, ad.ACT_VERB_TABLE)
        assert off is not None
        data[off + 4] ^= 0xFF  # a different parse function in row 0
        with pytest.raises(ValueError, match="not this build's"):
            CampaignArmyVerbsPatch().apply(data)

    @pytest.mark.parametrize("va", [ad.ACT_VERB_TABLE_PUSH_SITE, ad.ACT_RUN_PASS9_CALL])
    def test_a_changed_hook_site_refuses(self, va: int) -> None:
        data = campaign_army_verbs_image()
        off = va_to_offset(data, va)
        assert off is not None
        data[off] ^= 0xFF
        with pytest.raises(ValueError, match="expected"):
            CampaignArmyVerbsPatch().apply(data)


class TestApply:
    """The two edits, and the section they point at."""

    def test_verify_is_clean_and_detect_finds_it(self) -> None:
        data = patched()
        assert CampaignArmyVerbsPatch().verify(data) == []
        found = CampaignArmyVerbsPatch.detect(data)
        assert found is not None
        assert found.name == "campaign-army-verbs"

    def test_detect_ignores_a_stock_image(self) -> None:
        assert CampaignArmyVerbsPatch.detect(campaign_army_verbs_image()) is None

    def test_the_push_names_the_relocated_table(self) -> None:
        data = patched()
        section_va, _ = cave_of(data)
        off = va_to_offset(data, ad.ACT_VERB_TABLE_PUSH_SITE)
        assert off is not None
        assert data[off] == 0x68
        pushed = struct.unpack_from("<I", data, off + 1)[0]
        assert pushed == section_va + cave_layout()["verb_table"]

    def test_pass_nine_calls_the_cave(self) -> None:
        data = patched()
        section_va, _ = cave_of(data)
        off = va_to_offset(data, ad.ACT_RUN_PASS9_CALL)
        assert off is not None
        assert data[off] == 0xE8
        target = ad.ACT_RUN_PASS9_CALL + 5 + struct.unpack_from("<i", data, off + 1)[0]
        assert target == cav._hook_targets(section_va)[1]

    def test_the_stock_table_bytes_survive_relocation(self) -> None:
        data = patched()
        section_va, section_off = cave_of(data)
        start = section_off + cave_layout()["verb_table"]
        stock_size = ad.ACT_VERB_ROW_COUNT * ad.ACT_VERB_ROW_SIZE
        assert bytes(data[start : start + stock_size]) == ad.ACT_VERB_TABLE_BYTES[:stock_size]

    def test_the_stock_table_is_left_alone(self) -> None:
        # Relocation copies; it does not edit. A build that still pushed the old address would
        # still find fifteen working verbs there.
        data = patched()
        off = va_to_offset(data, ad.ACT_VERB_TABLE)
        assert off is not None
        assert bytes(data[off : off + len(ad.ACT_VERB_TABLE_BYTES)]) == ad.ACT_VERB_TABLE_BYTES


class TestRelocatedTable:
    """What the parser is handed once the push is repointed."""

    def test_seventeen_rows_and_a_terminator(self) -> None:
        data = patched()
        section_va, section_off = cave_of(data)
        start = section_off + cave_layout()["verb_table"]
        size = (ad.ACT_VERB_ROW_COUNT + 3) * ad.ACT_VERB_ROW_SIZE
        decoded = rows(bytes(data[start : start + size]))
        assert len(decoded) == ad.ACT_VERB_ROW_COUNT + 3
        assert decoded[-1] == (0, 0, 0, 0)
        assert all(row != (0, 0, 0, 0) for row in decoded[:-1])

    def test_the_two_new_rows_name_the_two_verbs(self) -> None:
        data = patched()
        section_va, section_off = cave_of(data)
        start = section_off + cave_layout()["verb_table"]
        size = (ad.ACT_VERB_ROW_COUNT + 3) * ad.ACT_VERB_ROW_SIZE
        decoded = rows(bytes(data[start : start + size]))
        merge, despawn = decoded[ad.ACT_VERB_ROW_COUNT : ad.ACT_VERB_ROW_COUNT + 2]
        assert read_cstring(data, merge[0]) == "MergePlayerArmy"
        assert read_cstring(data, despawn[0]) == "DespawnArmy"
        # Both are block-shaped as far as the driver is concerned: no userData, no act offset.
        assert merge[2] == merge[3] == 0
        assert despawn[2] == despawn[3] == 0

    def test_the_new_parsers_are_the_caves(self) -> None:
        data = patched()
        section_va, section_off = cave_of(data)
        _, _, size = find_section(data, SECTION_NAME)  # type: ignore[misc]
        start = section_off + cave_layout()["verb_table"]
        decoded = rows(
            bytes(data[start : start + (ad.ACT_VERB_ROW_COUNT + 3) * ad.ACT_VERB_ROW_SIZE])
        )
        code_start = section_va + cave_layout()["code"]
        for row in decoded[ad.ACT_VERB_ROW_COUNT : ad.ACT_VERB_ROW_COUNT + 2]:
            assert code_start <= row[1] < section_va + size

    def test_the_field_table_uses_the_engines_own_parsers(self) -> None:
        data = patched()
        section_va, section_off = cave_of(data)
        start = section_off + cave_layout()["field_table"]
        decoded = rows(bytes(data[start : start + (len(FIELD_ROWS) + 1) * 16]))
        assert decoded[-1] == (0, 0, 0, 0)
        for (name, parser, offset), row in zip(FIELD_ROWS, decoded, strict=False):
            assert read_cstring(data, row[0]) == name
            assert row[1] == parser
            assert row[2] == 0
            assert row[3] == offset
        # Not a cave address anywhere in the field table: every field is read by the engine.
        assert {row[1] for row in decoded[:-1]} <= {
            ad.GAME_DATA_ASCIISTRING_PARSER,
            ad.GAME_DATA_BOOL_PARSER,
        }


class TestCave:
    """The routines themselves."""

    def test_the_code_decodes_to_the_last_byte(self) -> None:
        capstone = pytest.importorskip("capstone")
        layout = cave_layout()
        code = build_cave(FAKE_BASE)[layout["code"] :]
        md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
        decoded = sum(insn.size for insn in md.disasm(code, FAKE_BASE + layout["code"]))
        assert decoded == len(code), "the cave holds a byte no instruction covers"

    def test_every_absolute_branch_leaves_for_a_known_address(self) -> None:
        capstone = pytest.importorskip("capstone")
        layout = cave_layout()
        cave = build_cave(FAKE_BASE)
        code = cave[layout["code"] :]
        code_start = FAKE_BASE + layout["code"]
        engine = {
            ad.ASCII_STRING_COMPARE,
            ad.ASCII_STRING_CTOR,
            ad.ASCII_STRING_DTOR,
            ad.ACT_SET_PLAYER_CONTROL_EXEC,
            ad.GAME_DATA_ASCIISTRING_PARSER,
            ad.INI_PARSE_FIELDS,
            ad.LIVING_WORLD_ARMY_ADD_RECORD,
            ad.LIVING_WORLD_ARMY_DESTROY,
            ad.LIVING_WORLD_ARMY_ERASE_RECORD,
            ad.LIVING_WORLD_ARMY_GET_RECORD,
            ad.LIVING_WORLD_FIND_ARMY_BY_NAME,
            ad.LIVING_WORLD_FIND_PLAYER_ARMY_BY_NAME,
            ad.REF_COUNT_RELEASE,
        }
        md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
        md.detail = True
        seen = set()
        for insn in md.disasm(code, code_start):
            if insn.mnemonic not in ("call", "jmp") and not insn.mnemonic.startswith("j"):
                continue
            operand = insn.operands[0]
            if operand.type != capstone.x86.X86_OP_IMM:
                continue
            target = operand.imm
            inside = code_start <= target < code_start + len(code)
            assert inside or target in engine, (
                f"{insn.address:#010x} {insn.mnemonic} reaches {target:#010x}, "
                "which is neither the cave nor an address this patch declares"
            )
            if not inside:
                seen.add(target)
        missing = sorted(hex(address) for address in engine - seen)
        assert not missing, f"engine addresses the cave never reaches: {missing}"

    def test_the_pass_hook_still_makes_the_call_it_displaced(self) -> None:
        capstone = pytest.importorskip("capstone")
        cave = build_cave(FAKE_BASE)
        hook = cav._hook_targets(FAKE_BASE)[1]
        md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
        window = cave[hook - FAKE_BASE : hook - FAKE_BASE + 8]
        listing = list(md.disasm(window, hook))
        assert listing[0].mnemonic == "push" and listing[0].op_str == "ecx"
        assert listing[1].mnemonic == "call"
        assert int(listing[1].op_str, 16) == ad.ACT_SET_PLAYER_CONTROL_EXEC
        assert listing[2].mnemonic == "pop" and listing[2].op_str == "ecx"

    def test_the_record_table_starts_empty(self) -> None:
        layout = cave_layout()
        cave = build_cave(FAKE_BASE)
        assert struct.unpack_from("<I", cave, layout["count"])[0] == 0
        records = cave[layout["records"] : layout["records"] + RECORD_CAPACITY * RECORD_SIZE]
        assert set(records) == {0}

    def test_the_cave_relocates_with_its_base(self) -> None:
        # Nothing in it may be position-dependent by accident: two bases give two different
        # images, and the second is not the first.
        assert build_cave(FAKE_BASE) != build_cave(FAKE_BASE + 0x10000)

    def test_the_strings_are_the_keywords(self) -> None:
        layout = cave_layout()
        cave = build_cave(FAKE_BASE)
        for text in ("MergePlayerArmy", "DespawnArmy", *(name for name, _, _ in FIELD_ROWS)):
            start = layout[f"str:{text}"]
            assert cave[start : start + len(text) + 1] == text.encode("ascii") + b"\x00"


class TestVerify:
    """What `verify` refuses to call installed."""

    def test_a_missing_section_is_reported(self) -> None:
        assert CampaignArmyVerbsPatch().verify(campaign_army_verbs_image()) == [
            f"{SECTION_NAME} section is absent"
        ]

    def test_a_reverted_push_is_reported(self) -> None:
        data = patched()
        off = va_to_offset(data, ad.ACT_VERB_TABLE_PUSH_SITE)
        assert off is not None
        data[off : off + 5] = ad.ACT_VERB_TABLE_PUSH_SITE_BYTES
        assert any("pushes" in problem for problem in CampaignArmyVerbsPatch().verify(data))

    def test_a_reverted_call_is_reported(self) -> None:
        data = patched()
        off = va_to_offset(data, ad.ACT_RUN_PASS9_CALL)
        assert off is not None
        data[off : off + 5] = ad.ACT_RUN_PASS9_CALL_BYTES
        assert any("calls" in problem for problem in CampaignArmyVerbsPatch().verify(data))

    def test_a_corrupted_cave_is_reported(self) -> None:
        data = patched()
        _, section_off = cave_of(data)
        data[section_off + cave_layout()["code"]] ^= 0xFF
        assert any("does not hold" in problem for problem in CampaignArmyVerbsPatch().verify(data))

    def test_writing_a_record_does_not_fail_verify(self) -> None:
        # The record table is what the parse functions fill in at run time, so a binary that has
        # been run must still verify.
        data = patched()
        _, section_off = cave_of(data)
        layout = cave_layout()
        struct.pack_into("<I", data, section_off + layout["count"], 1)
        data[section_off + layout["records"]] = ord("A")
        assert CampaignArmyVerbsPatch().verify(data) == []


class TestComposition:
    """Order independence, in the framework's sense: both patches apply and both verify whichever
    order they are applied in, and neither writes a byte the other does."""

    def test_the_cave_follows_whatever_section_is_already_there(self) -> None:
        # `allocate_section` puts the cave past the highest section, so a patch applied first
        # moves mine. Nothing in it may assume where it landed.
        plain = patched()
        crowded = campaign_army_verbs_image()
        filler = bytes([0x90]) * 0x2000
        append_section(crowded, ".fill", next_section_rva(crowded), filler, 0x40000000)
        CampaignArmyVerbsPatch().apply(crowded)

        assert CampaignArmyVerbsPatch().verify(crowded) == []
        assert cave_of(plain)[0] != cave_of(crowded)[0]

    @pytest.mark.skipif(not _GAME_DAT.exists(), reason="needs the real game.dat")
    @pytest.mark.parametrize("other", ["objectives-screen", "scenario-player-factions"])
    def test_it_composes_on_the_real_binary(self, other: str) -> None:
        """Only the shipped binary carries both patches' sites, so this is the one place the
        claim that they share no byte can actually be made."""
        stock = _GAME_DAT.read_bytes()
        mine, theirs = PATCHES["campaign-army-verbs"], PATCHES[other]

        forward = bytearray(stock)
        mine().apply(forward)
        theirs().apply(forward)

        backward = bytearray(stock)
        theirs().apply(backward)
        mine().apply(backward)

        assert mine().verify(forward) == []
        assert mine().verify(backward) == []
        assert theirs().verify(forward) == []
        assert theirs().verify(backward) == []

    @pytest.mark.skipif(not _GAME_DAT.exists(), reason="needs the real game.dat")
    def test_the_real_binary_carries_the_stock_sites(self) -> None:
        stock = _GAME_DAT.read_bytes()
        for va, expected in (
            (ad.ACT_VERB_TABLE, ad.ACT_VERB_TABLE_BYTES),
            (ad.ACT_VERB_TABLE_PUSH_SITE, ad.ACT_VERB_TABLE_PUSH_SITE_BYTES),
            (ad.ACT_RUN_PASS9_CALL, ad.ACT_RUN_PASS9_CALL_BYTES),
        ):
            off = va_to_offset(stock, va)
            assert off is not None
            assert bytes(stock[off : off + len(expected)]) == expected


class TestIniSurface:
    """The INI the patched engine accepts, and that the surface actually describes it."""

    def test_it_declares_the_block_its_nesting_and_its_fields(self) -> None:
        surface = CampaignArmyVerbsPatch().ini_surface()
        assert [delta.name for delta in surface.blocks] == ["MergePlayerArmy"]
        assert [(d.block, d.name) for d in surface.nested] == [("Act", "MergePlayerArmy")]
        assert ("Act", "DespawnArmy") in [(d.block, d.name) for d in surface.fields]
        merge_fields = {d.name for d in surface.fields if d.block == "MergePlayerArmy"}
        assert merge_fields == {name for name, _, _ in FIELD_ROWS}

    def test_every_declared_field_is_one_the_cave_parses(self) -> None:
        surface = CampaignArmyVerbsPatch().ini_surface()
        declared = {d.name for d in surface.fields if d.block == "MergePlayerArmy"}
        assert declared == {name for name, _, _ in FIELD_ROWS}

    def test_the_surface_applies_without_complaint(self) -> None:
        with CampaignArmyVerbsPatch().ini_surface().activate() as problems:
            assert problems == []
            assert "MergePlayerArmy" in REGISTRY["Act"]._nested
            assert "DespawnArmy" in REGISTRY["Act"]._fieldspec

    def test_the_new_verbs_read_as_the_verbs_they_are(self) -> None:
        text = (
            "LivingWorldCampaign TestCampaign\n"
            "    Act TestAct\n"
            "        DespawnArmy = Zaphragor_Army\n"
            "        MergePlayerArmy\n"
            "            SourceArmy = Zaphragor_Army\n"
            "            DestArmy = WitchKing_Army\n"
            "            SplitArmyTemplate = ZaphragorSplitArmy\n"
            "            SplitArmy = Yes\n"
            "        End\n"
            "    End\n"
            "End\n"
        )
        with CampaignArmyVerbsPatch().ini_surface().activate() as problems:
            assert problems == []
            result = parse(text, "campaign.ini")
            assert [d for d in result.diagnostics if d.severity.name == "ERROR"] == []
            act_cls = REGISTRY["Act"]
            assert act_cls._nested["MergePlayerArmy"] == ["MergePlayerArmy"]
            merge_cls = REGISTRY["MergePlayerArmy"]
            assert set(merge_cls._fieldspec) >= {name for name, _, _ in FIELD_ROWS}

    def test_the_surface_leaves_the_model_stock_afterwards(self) -> None:
        before = sorted(REGISTRY["Act"]._nested)
        with CampaignArmyVerbsPatch().ini_surface().activate():
            pass
        assert sorted(REGISTRY["Act"]._nested) == before
        assert "MergePlayerArmy" not in REGISTRY

    def test_a_sibling_block_does_not_gain_the_verb(self) -> None:
        # `Act` and `Scenario` share one `nested_attributes` dict in the stock model, so a delta
        # that mutated it in place would hand `MergePlayerArmy` to both.
        with CampaignArmyVerbsPatch().ini_surface().activate():
            assert "MergePlayerArmy" not in REGISTRY["Scenario"]._nested


class TestSagepatchDocument:
    """The path a mod actually takes: the binary describes itself, the file is committed, and
    `sage_ini` reads the file. A surface that only exists when `ini_surface()` is called directly
    is a surface no mod ever sees."""

    def generated(self) -> Engine:
        described, unknown = generate_from_patches(["campaign-army-verbs"])
        assert unknown == []
        return described.engine

    def test_the_document_carries_the_nesting(self) -> None:
        engine = self.generated()
        assert [(d.block, d.name) for d in engine.nested] == [("Act", "MergePlayerArmy")]

    def test_it_round_trips_through_the_file(self) -> None:
        engine = self.generated()
        back = parse_engine(dump_engine(engine))
        assert back.warnings == ()
        assert back.nested == engine.nested
        assert back.blocks == engine.blocks
        assert back.fields == engine.fields

    def test_a_file_missing_the_nesting_reads_as_drift(self) -> None:
        """`differences` is what `sagepatch --check` fails on, so a delta it does not compare is a
        delta that can silently go stale in a committed file."""
        engine = self.generated()
        stale = parse_engine(dump_engine(Engine(patches=engine.patches, blocks=engine.blocks)))
        assert any("nested block" in problem for problem in differences(stale, engine))

    def test_the_committed_file_applies_and_the_verbs_parse(self) -> None:
        engine = parse_engine(dump_engine(self.generated()))
        with engine.activate() as problems:
            assert problems == []
            assert "MergePlayerArmy" in REGISTRY["Act"]._nested
            assert "DespawnArmy" in REGISTRY["Act"]._fieldspec


class TestRegistration:
    def test_it_is_registered_and_experimental(self) -> None:
        assert PATCHES["campaign-army-verbs"] is CampaignArmyVerbsPatch
        assert CampaignArmyVerbsPatch().experimental is True

    def test_the_description_names_both_verbs(self) -> None:
        description = CampaignArmyVerbsPatch.description
        assert "MergePlayerArmy" in description
        assert "DespawnArmy" in description
        assert not description.endswith(".")

    def test_the_surface_is_not_stock(self) -> None:
        assert CampaignArmyVerbsPatch().ini_surface() != Engine()
