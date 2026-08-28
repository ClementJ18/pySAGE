"""`hero-army-carryover`: the `Persistent` keyword, and the ledger walk that acts on it.

Static tests. They can establish that all four sites are what the patch thinks they are, that the
relocated `ArmyEntry` sub-table is the stock one plus exactly one row read by the engine's own
parser, that the record byte the keyword borrows really is free, that each hook makes the call it
displaced with the stack the callee expects, and that the cave decodes and branches only where it
is allowed to. What they cannot establish is that a hero rebuilt from a ledger entry behaves in the
running game - that is what `experimental` is for.
"""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

from sage_ini.model.objects import REGISTRY
from sage_ini.parser import parse
from sage_patch import addresses as ad
from sage_patch.patches.experimental import hero_army_carryover as hac
from sage_patch.patches.experimental.hero_army_carryover import (
    HELD_CAPACITY,
    KEYWORD,
    NAME_CAPACITY,
    PERSISTENT_CAPACITY,
    RECORD_SIZE,
    SECTION_NAME,
    HeroArmyCarryoverPatch,
    build_cave,
    cave_layout,
)
from sage_patch.registry import PATCHES
from sage_patch.sagepatch import generate_from_patches
from sage_patch.utils import (
    append_section,
    find_section,
    next_section_rva,
    va_to_offset,
)

from .synthetic import hero_army_carryover_image

FAKE_BASE = 0x0C000000
_GAME_DAT = Path(__file__).resolve().parents[2] / "game.dat"
_ROW = 0x10


def patched() -> bytearray:
    data = hero_army_carryover_image()
    HeroArmyCarryoverPatch().apply(data)
    return data


def cave_of(data: bytes | bytearray) -> tuple[int, int]:
    located = find_section(data, SECTION_NAME)
    assert located is not None
    section_va, section_off, _ = located
    return section_va, section_off


def listing(base: int = FAKE_BASE):
    capstone = pytest.importorskip("capstone")
    layout = cave_layout()
    code = build_cave(base)[layout["code"] :]
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    md.detail = True
    return capstone, list(md.disasm(code, base + layout["code"])), code


def rows(table: bytes) -> list[tuple[int, int, int, int]]:
    return [struct.unpack_from("<IIII", table, i * _ROW) for i in range(len(table) // _ROW)]


class TestStockSites:
    def test_every_site_holds_the_build_bytes(self) -> None:
        data = hero_army_carryover_image()
        for site, (original, _) in hac.ANCHORS.items():
            off = va_to_offset(data, site)
            assert off is not None
            assert bytes(data[off : off + len(original)]) == original
        off = va_to_offset(data, ad.ARMY_ENTRY_DEFAULT_TABLE_PUSH)
        assert off is not None
        assert bytes(data[off : off + 5]) == ad.ARMY_ENTRY_DEFAULT_TABLE_PUSH_BYTES

    def test_each_call_reaches_what_it_should(self) -> None:
        for site, (original, callee) in hac.ANCHORS.items():
            assert original[0] == 0xE8
            assert site + 5 + struct.unpack_from("<i", original, 1)[0] == callee

    def test_the_push_names_the_army_entry_sub_table(self) -> None:
        assert ad.ARMY_ENTRY_DEFAULT_TABLE_PUSH_BYTES[0] == 0x68
        named = struct.unpack_from("<I", ad.ARMY_ENTRY_DEFAULT_TABLE_PUSH_BYTES, 1)[0]
        assert named == ad.ARMY_ENTRY_DEFAULT_TABLE

    def test_the_stock_sub_table_is_one_row_and_a_terminator(self) -> None:
        decoded = rows(ad.ARMY_ENTRY_DEFAULT_TABLE_BYTES)
        assert len(decoded) == 2
        assert decoded[-1] == (0, 0, 0, 0)
        assert decoded[0][1] == ad.GAME_DATA_BOOL_PARSER  # `Default`, a Bool
        assert decoded[0][3] == ad.ARMY_ENTRY_DEFAULT_OFFSET

    @pytest.mark.parametrize("site", list(hac.ANCHORS))
    def test_a_changed_call_is_refused(self, site: int) -> None:
        data = hero_army_carryover_image()
        off = va_to_offset(data, site)
        assert off is not None
        data[off] ^= 0xFF
        with pytest.raises(ValueError, match="not the build"):
            HeroArmyCarryoverPatch().apply(data)

    def test_a_changed_sub_table_is_refused(self) -> None:
        data = hero_army_carryover_image()
        off = va_to_offset(data, ad.ARMY_ENTRY_DEFAULT_TABLE)
        assert off is not None
        data[off + 4] ^= 0xFF
        with pytest.raises(ValueError, match="refusing to relocate"):
            HeroArmyCarryoverPatch().apply(data)

    def test_a_call_that_reaches_elsewhere_is_refused(self, monkeypatch) -> None:
        """On a real image the anchor is the whole `call`, so bytes that match imply a target that
        matches. This guards the case they cannot: a `_BYTES` constant refreshed for a new build
        without the address beside it."""
        site = ad.LIVING_WORLD_BATTLE_HARVEST_CALL
        wrong = dict(hac.ANCHORS)
        wrong[site] = (hac.ANCHORS[site][0], ad.LIVING_WORLD_BATTLE_SETUP)
        monkeypatch.setattr(hac, "ANCHORS", wrong)
        with pytest.raises(ValueError, match="displace the wrong function"):
            HeroArmyCarryoverPatch().apply(hero_army_carryover_image())


class TestTheBorrowedByte:
    """`Persistent` parses into a record byte the patch borrows for the length of one block."""

    def test_it_is_past_every_field_the_record_declares(self) -> None:
        assert ad.ARMY_ENTRY_SCRATCH_OFFSET > ad.ARMY_ENTRY_DEFAULT_OFFSET
        assert ad.ARMY_ENTRY_SCRATCH_OFFSET < RECORD_SIZE

    @pytest.mark.skipif(not _GAME_DAT.exists(), reason="needs the real game.dat")
    def test_the_copy_constructor_does_not_carry_it(self) -> None:
        """The reason the flag has to be consumed inside the parser: a record copied from the
        `LivingWorldPlayerArmy` template into a live army would lose it. The copy-constructor's
        last byte copy is `+0xD6`, so `+0xD7` is not carried - and this is what would notice if a
        future build carried one byte further."""
        capstone = pytest.importorskip("capstone")
        stock = _GAME_DAT.read_bytes()
        off = va_to_offset(stock, 0x008101F5)
        assert off is not None
        md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
        md.detail = True
        copied = set()
        for insn in md.disasm(stock[off : off + 0x28], 0x008101F5):
            if insn.mnemonic != "mov":
                continue
            for operand in insn.operands:
                if operand.type == capstone.x86.X86_OP_MEM:
                    copied.add(operand.mem.disp)
        assert ad.ARMY_ENTRY_DEFAULT_OFFSET in copied, "the copy loop was not found"
        assert ad.ARMY_ENTRY_SCRATCH_OFFSET not in copied


class TestApply:
    def test_verify_is_clean_and_detect_finds_it(self) -> None:
        data = patched()
        assert HeroArmyCarryoverPatch().verify(data) == []
        found = HeroArmyCarryoverPatch.detect(data)
        assert found is not None and found.name == "hero-army-carryover"

    def test_detect_ignores_a_stock_image(self) -> None:
        assert HeroArmyCarryoverPatch.detect(hero_army_carryover_image()) is None

    def test_every_call_reaches_its_hook(self) -> None:
        data = patched()
        section_va, _ = cave_of(data)
        for site, expected in hac._hook_targets(section_va).items():
            off = va_to_offset(data, site)
            assert off is not None
            assert data[off] == 0xE8
            assert site + 5 + struct.unpack_from("<i", data, off + 1)[0] == expected

    def test_the_push_names_the_relocated_table(self) -> None:
        data = patched()
        section_va, _ = cave_of(data)
        off = va_to_offset(data, ad.ARMY_ENTRY_DEFAULT_TABLE_PUSH)
        assert off is not None
        assert data[off] == 0x68
        pushed = struct.unpack_from("<I", data, off + 1)[0]
        assert pushed == section_va + cave_layout()["field_table"]

    def test_the_stock_sub_table_is_left_alone(self) -> None:
        data = patched()
        off = va_to_offset(data, ad.ARMY_ENTRY_DEFAULT_TABLE)
        assert off is not None
        length = len(ad.ARMY_ENTRY_DEFAULT_TABLE_BYTES)
        assert bytes(data[off : off + length]) == ad.ARMY_ENTRY_DEFAULT_TABLE_BYTES


class TestTheRelocatedTable:
    def table(self) -> tuple[bytearray, int, list[tuple[int, int, int, int]]]:
        data = patched()
        section_va, section_off = cave_of(data)
        start = section_off + cave_layout()["field_table"]
        return data, section_va, rows(bytes(data[start : start + 3 * _ROW]))

    def test_the_stock_row_survives_and_a_second_appears(self) -> None:
        _data, _va, decoded = self.table()
        assert len(decoded) == 3
        assert decoded[-1] == (0, 0, 0, 0)
        assert decoded[0] == rows(ad.ARMY_ENTRY_DEFAULT_TABLE_BYTES)[0]

    def test_the_new_row_is_the_keyword_the_engine_will_read(self) -> None:
        data, section_va, decoded = self.table()
        name, parser, user_data, offset = decoded[1]
        assert name == section_va + cave_layout()["keyword"]
        off = va_to_offset(data, name)
        assert off is not None
        assert bytes(data[off : off + len(KEYWORD)]).decode() == KEYWORD
        assert data[off + len(KEYWORD)] == 0
        # Read by the engine's own Bool parser, into the borrowed byte, with no userData.
        assert parser == ad.GAME_DATA_BOOL_PARSER
        assert user_data == 0
        assert offset == ad.ARMY_ENTRY_SCRATCH_OFFSET


class TestTheHooks:
    def test_the_entry_hook_zeroes_the_byte_before_it_parses(self) -> None:
        """Order is the whole point: the record constructor leaves that byte uninitialised, so
        reading it after a parse that never saw the keyword would be reading heap noise."""
        _capstone, insns, _ = listing()
        start = hac._hook_targets(FAKE_BASE)[ad.ARMY_ENTRY_PARSE_FIELDS_CALL]
        body = [i for i in insns if i.address >= start][:8]
        zeroing = next(i for i in body if i.mnemonic == "mov" and i.op_str.endswith("0xd7], 0"))
        parsing = next(
            i
            for i in body
            if i.mnemonic == "call" and int(i.op_str, 16) == ad.ARMY_ENTRY_PARSE_FIELDS
        )
        assert zeroing.address < parsing.address

    def test_the_entry_hook_repushes_and_cleans(self) -> None:
        _capstone, insns, _ = listing()
        start = hac._hook_targets(FAKE_BASE)[ad.ARMY_ENTRY_PARSE_FIELDS_CALL]
        body = [i for i in insns if i.address >= start]
        pushes = [i for i in body[:8] if i.mnemonic == "push" and "esp" in i.op_str]
        assert pushes, "the wrapped parse takes a stack argument that has to be pushed again"
        end = next(i for i in body if i.mnemonic == "ret")
        assert end.op_str == "4"

    def test_the_setup_hook_calls_then_captures_and_cleans_nothing(self) -> None:
        _capstone, insns, _ = listing()
        start = hac._hook_targets(FAKE_BASE)[ad.LIVING_WORLD_BATTLE_SETUP_CALL]
        body = [i for i in insns if i.address >= start][:3]
        assert body[0].mnemonic == "call"
        assert int(body[0].op_str, 16) == ad.LIVING_WORLD_BATTLE_SETUP
        assert body[1].mnemonic == "call"
        assert (body[2].mnemonic, body[2].op_str) == ("ret", "")

    def test_the_harvest_hook_repushes_the_argument_and_cleans_it(self) -> None:
        _capstone, insns, _ = listing()
        start = hac._hook_targets(FAKE_BASE)[ad.LIVING_WORLD_BATTLE_HARVEST_CALL]
        body = [i for i in insns if i.address >= start][:4]
        assert (body[0].mnemonic, body[0].op_str) == ("push", "dword ptr [esp + 4]")
        assert body[1].mnemonic == "call"
        assert int(body[1].op_str, 16) == ad.LIVING_WORLD_BATTLE_HARVEST
        assert body[2].mnemonic == "call"
        assert (body[3].mnemonic, body[3].op_str) == ("ret", "4")


class TestTheCave:
    def test_it_decodes_to_the_last_byte(self) -> None:
        _capstone, insns, code = listing()
        assert sum(i.size for i in insns) == len(code)

    def test_every_absolute_branch_is_declared(self) -> None:
        capstone, insns, code = listing()
        engine = {
            ad.ARMY_ENTRY_PARSE_FIELDS,
            ad.ARMY_ENTRY_RECORD_CTOR,
            ad.HERO_LEDGER_FIND_TEMPLATE,
            ad.HERO_LEDGER_TO_RECORD,
            ad.LIVING_WORLD_ARMY_ADD_RECORD,
            ad.LIVING_WORLD_ARMY_GET_RECORD,
            ad.LIVING_WORLD_BATTLE_HARVEST,
            ad.LIVING_WORLD_BATTLE_SETUP,
            ad.LIVING_WORLD_FIND_ARMY_BY_ID,
            ad.OPERATOR_NEW,
            ad.PLAYER_LIST_GET_NTH,
            ad.REF_COUNT_RELEASE,
        }
        low = FAKE_BASE + cave_layout()["code"]
        high = low + len(code)
        seen = set()
        for insn in insns:
            if not insn.mnemonic.startswith("j") and insn.mnemonic != "call":
                continue
            operand = insn.operands[0]
            if operand.type != capstone.x86.X86_OP_IMM:
                continue
            target = operand.imm
            inside = low <= target < high
            assert inside or target in engine, (
                f"{insn.address:#010x} {insn.mnemonic} reaches {target:#010x}, "
                "which is neither the cave nor an address this patch declares"
            )
            if not inside:
                seen.add(target)
        missing = sorted(hex(a) for a in engine - seen)
        assert not missing, f"engine addresses the cave never reaches: {missing}"

    def test_the_rebuilt_record_is_referenced_once_and_released_once(self) -> None:
        """The only allocation the cave makes. The append takes its own reference, so one addref
        and one release leaves the record alive in the roster and owned by nobody else."""
        capstone, insns, _ = listing()
        addrefs = [
            i
            for i in insns
            if i.mnemonic == "inc" and i.op_str.endswith(f"+ {ad.ARMY_ENTRY_REFCOUNT_COUNT:#x}]")
        ]
        releases = [
            i
            for i in insns
            if i.mnemonic == "call"
            and i.operands[0].type == capstone.x86.X86_OP_IMM
            and i.operands[0].imm == ad.REF_COUNT_RELEASE
        ]
        assert len(addrefs) == 1
        assert len(releases) == 1

    def test_the_ledger_builder_runs_before_the_append(self) -> None:
        """A record appended before it is filled would join the army nameless."""
        capstone, insns, _ = listing()

        def site(address: int):
            return next(
                i
                for i in insns
                if i.mnemonic == "call"
                and i.operands[0].type == capstone.x86.X86_OP_IMM
                and i.operands[0].imm == address
            )

        assert (
            site(ad.HERO_LEDGER_TO_RECORD).address < site(ad.LIVING_WORLD_ARMY_ADD_RECORD).address
        )

    def test_the_allocation_is_the_record_size_the_engine_uses(self) -> None:
        capstone, insns, _ = listing()
        allocate = next(
            i
            for i in insns
            if i.mnemonic == "call"
            and i.operands[0].type == capstone.x86.X86_OP_IMM
            and i.operands[0].imm == ad.OPERATOR_NEW
        )
        pushed = [i for i in insns if i.address < allocate.address and i.mnemonic == "push"][-1]
        assert int(pushed.op_str, 16) == RECORD_SIZE

    def test_both_tables_start_empty_and_do_not_overlap(self) -> None:
        layout = cave_layout()
        cave = build_cave(FAKE_BASE)
        assert struct.unpack_from("<I", cave, layout["persist_count"])[0] == 0
        assert struct.unpack_from("<I", cave, layout["held_count"])[0] == 0
        names = layout["persist_names"]
        assert names + PERSISTENT_CAPACITY * NAME_CAPACITY <= layout["held_count"]
        assert layout["held"] + HELD_CAPACITY * hac._HELD_SIZE <= layout["field_table"]
        assert set(cave[names : names + PERSISTENT_CAPACITY * NAME_CAPACITY]) == {0}

    def test_it_relocates_with_its_base(self) -> None:
        assert build_cave(FAKE_BASE) != build_cave(FAKE_BASE + 0x30000)


class TestComposition:
    def test_the_cave_follows_whatever_section_is_already_there(self) -> None:
        plain = patched()
        crowded = hero_army_carryover_image()
        append_section(
            crowded, ".fill", next_section_rva(crowded), bytes([0x90]) * 0x2000, 0x40000000
        )
        HeroArmyCarryoverPatch().apply(crowded)
        assert HeroArmyCarryoverPatch().verify(crowded) == []
        assert cave_of(plain)[0] != cave_of(crowded)[0]

    @pytest.mark.skipif(not _GAME_DAT.exists(), reason="needs the real game.dat")
    @pytest.mark.parametrize("other", ["campaign-army-verbs", "objectives-screen"])
    def test_it_composes_on_the_real_binary(self, other: str) -> None:
        stock = _GAME_DAT.read_bytes()
        mine, theirs = PATCHES["hero-army-carryover"], PATCHES[other]
        forward = bytearray(stock)
        mine().apply(forward)
        theirs().apply(forward)
        backward = bytearray(stock)
        theirs().apply(backward)
        mine().apply(backward)
        for image in (forward, backward):
            assert mine().verify(image) == []
            assert theirs().verify(image) == []

    @pytest.mark.skipif(not _GAME_DAT.exists(), reason="needs the real game.dat")
    def test_the_real_binary_carries_every_stock_site(self) -> None:
        stock = _GAME_DAT.read_bytes()
        for site, (original, _) in hac.ANCHORS.items():
            off = va_to_offset(stock, site)
            assert off is not None
            assert bytes(stock[off : off + len(original)]) == original
        off = va_to_offset(stock, ad.ARMY_ENTRY_DEFAULT_TABLE)
        assert off is not None
        length = len(ad.ARMY_ENTRY_DEFAULT_TABLE_BYTES)
        assert bytes(stock[off : off + length]) == ad.ARMY_ENTRY_DEFAULT_TABLE_BYTES


class TestIniSurface:
    def test_it_declares_the_keyword_on_army_entry(self) -> None:
        surface = HeroArmyCarryoverPatch().ini_surface()
        assert [(d.block, d.name, d.type) for d in surface.fields] == [
            ("ArmyEntry", KEYWORD, "Bool")
        ]
        assert surface.fields[0].default is False

    def test_the_keyword_reads_as_a_field_of_the_block(self) -> None:
        text = (
            "LivingWorldPlayerArmy\n"
            "    Name = WitchKingKampaArmy\n"
            "    ArmyEntry\n"
            "        ThingTemplate = AngmarDurmarth\n"
            "        Quantity      = 1\n"
            f"        {KEYWORD} = Yes\n"
            "    End\n"
            "End\n"
        )
        with HeroArmyCarryoverPatch().ini_surface().activate() as problems:
            assert problems == []
            assert KEYWORD in REGISTRY["ArmyEntry"]._fieldspec
            result = parse(text, "campaign.ini")
            assert [d for d in result.diagnostics if d.severity.name == "ERROR"] == []

    def test_it_leaves_the_model_stock_afterwards(self) -> None:
        with HeroArmyCarryoverPatch().ini_surface().activate():
            pass
        assert KEYWORD not in REGISTRY["ArmyEntry"]._fieldspec

    def test_the_document_carries_the_keyword(self) -> None:
        described, unknown = generate_from_patches(["hero-army-carryover"])
        assert unknown == []
        assert [(d.block, d.name) for d in described.engine.fields] == [("ArmyEntry", KEYWORD)]


class TestTheFortressStillOffersHim:
    """A hero who died is back in his army *and* still recruitable at his faction's fortress.

    That is intended, not an oversight: the patch adds BFME1's army rule without taking ROTWK's
    own away, and it is confirmed in play. These tests are what stops it being silently "fixed" by
    somebody who reads the duplicate as a bug - and what would fail if a future change started
    suppressing the engine's own copy without saying so.
    """

    def test_the_engines_own_ledger_copy_is_left_alone(self) -> None:
        """`0x0078100E` is what files a dead hero on the `LivingWorldPlayer`, which is what puts
        his build button back in the fortress. Nothing in the cave calls it, hooks it or names it.
        """
        capstone, insns, _ = listing()
        reached = {
            insn.operands[0].imm
            for insn in insns
            if insn.mnemonic in ("call", "jmp") and insn.operands[0].type == capstone.x86.X86_OP_IMM
        }
        assert ad.LIVING_WORLD_LEDGER_TO_PLAYER not in reached

    def test_no_site_the_patch_edits_belongs_to_that_copy(self) -> None:
        edited = {*hac.ANCHORS, ad.ARMY_ENTRY_DEFAULT_TABLE_PUSH}
        assert ad.LIVING_WORLD_LEDGER_TO_PLAYER not in edited

    def test_the_description_says_so(self) -> None:
        """A mod author choosing this patch has to know the hero stays buyable."""
        description = HeroArmyCarryoverPatch.description
        assert "fortress" in description
        assert "intended" in description


class TestRegistration:
    def test_it_is_registered_and_experimental(self) -> None:
        assert PATCHES["hero-army-carryover"] is HeroArmyCarryoverPatch
        assert HeroArmyCarryoverPatch().experimental is True

    def test_the_description_names_the_keyword_and_the_state_it_keeps(self) -> None:
        description = HeroArmyCarryoverPatch.description
        assert KEYWORD in description
        assert "upgrades" in description
        assert not description.endswith(".")
