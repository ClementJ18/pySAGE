"""Tests for the AI hero build delay.

The cave is hand-assembled x86 that cannot be executed here, so the tests that matter disassemble
it back and assert it says what it was meant to say. Four of its properties are invisible to
`apply` and `verify` and would each be wrong in a way nobody would notice until a match went
strange, so each gets its own check:

* **`eax` survives the gate.** It holds the chosen hero's index, and the stock code stores it one
  instruction *after* the site the hook takes. A cave that clobbered it would push the wrong index
  onto the AI's retry list - a hero it never asked for, requested forever;
* **which of the two exits each verdict takes.** Both are stock edges of the same function and
  both are plain `jmp`s, so swapping them turns the patch into its own opposite: delayed heroes
  recruited and undelayed ones refused;
* **the comparison's direction.** `frame < seconds * rate` and its inverse are one condition code
  apart, and the inverse is a patch that blocks a hero *after* its delay instead of before;
* **which routine each of the two edits points at.** The parser and the gate live in one section
  and are both reached by address; a hook aimed at the parser or a table row aimed at the gate
  would be caught by nothing else here.

`TestTheParser` covers the half with no hook at all - the field-table row - because "the keyword
still parses a plain name" is the property that keeps every unsuffixed `HeroBuildOrder` in every
existing mod behaving exactly as it does today.
"""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

from sage_ini.model.objects import REGISTRY
from sage_patch.addresses import (
    AI_HERO_NAME_RESOLVED_RESUME,
    AI_HERO_REJECT,
    ARMY_DEFINITION_FIELD_TABLE,
    ARMY_DEFINITION_FIELD_TABLE_REF_OPCODES,
    ARMY_DEFINITION_FIELD_TABLE_REFS,
    ASCII_STRING_SET,
    GAME_LOGIC_FRAME,
    INI_PARSE_STRING_LIST,
    LOGIC_FRAMES_PER_SECOND,
    NAME_KEY_FROM_STRING,
    THE_GAME_LOGIC,
    THE_NAME_KEY_GENERATOR,
    THE_THING_FACTORY,
)
from sage_patch.patches.ai_hero_build_delay import (
    ANCHORS,
    HOOK_ORIGINAL,
    HOOK_VA,
    KEYWORD,
    MAX_SECONDS,
    SECTION_NAME,
    SLOTS,
    TABLE_BYTES,
    AiHeroBuildDelayPatch,
    build_code,
    build_section,
    layout,
)
from sage_patch.patches.utils.field_tables import (
    ROW_SIZE,
    entries_before,
    read_field_table,
    resolve_table,
)
from sage_patch.registry import PATCHES
from sage_patch.utils import find_section, va_to_offset

from .synthetic import ai_hero_build_delay_image

BASE = 0x00F00000

_GAME_DAT = Path(__file__).resolve().parents[2] / "game.dat"

#: The `ArmyDefinition` row the patch repoints, in the real table.
_HERO_ROW_VA = ARMY_DEFINITION_FIELD_TABLE + 29 * ROW_SIZE


def instructions(base: int = BASE):
    capstone = pytest.importorskip("capstone")
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    md.detail = True
    return {ins.address: ins for ins in md.disasm(build_code(base), base + TABLE_BYTES)}


def text(ins) -> str:
    return f"{ins.mnemonic} {ins.op_str}".strip()


def gate_instructions(base: int = BASE):
    """Only the gate's half of the cave - the parser shares several of its idioms."""
    gate = layout(base)[1]
    return {va: ins for va, ins in instructions(base).items() if va >= gate}


def parser_instructions(base: int = BASE):
    gate = layout(base)[1]
    return {va: ins for va, ins in instructions(base).items() if va < gate}


def at(data: bytes | bytearray, va: int, count: int) -> bytes:
    off = va_to_offset(data, va)
    assert off is not None, f"0x{va:08x} is not mapped"
    return bytes(data[off : off + count])


class TestTheCave:
    def test_it_disassembles_cleanly_to_its_end(self):
        decoded = instructions()
        assert decoded, "nothing decoded"
        last = max(decoded)
        assert last + decoded[last].size == BASE + TABLE_BYTES + len(build_code(BASE))

    def test_the_table_precedes_the_code_and_is_zeroed(self):
        """The section's own base is the table, so the code lands at a fixed offset from it and
        `verify` can compare the code without knowing what a run has since written."""
        section = build_section(BASE)
        assert section[:TABLE_BYTES] == bytes(TABLE_BYTES)
        assert section[TABLE_BYTES:] == build_code(BASE)
        assert layout(BASE)[0] == BASE + TABLE_BYTES

    def test_the_two_routines_do_not_overlap(self):
        parse_va, gate_va = layout(BASE)
        assert parse_va < gate_va < BASE + TABLE_BYTES + len(build_code(BASE))

    def test_it_relocates_with_its_section(self):
        assert build_code(BASE) != build_code(BASE + 0x1000)

    def test_every_conditional_branch_stays_inside_the_cave(self):
        decoded = instructions()
        start = BASE + TABLE_BYTES
        end = start + len(build_code(BASE))
        for ins in decoded.values():
            if ins.mnemonic.startswith("j") and ins.mnemonic != "jmp":
                target = int(ins.op_str, 16)
                assert start <= target < end, f"{text(ins)} leaves the cave"

    def test_only_the_delay_table_is_written(self):
        """Both routines are otherwise filters. The one place either stores through a pointer that
        is not the table or the parser's own frame would be state the engine still owns."""
        capstone = pytest.importorskip("capstone")
        for ins in instructions().values():
            for op in ins.operands:
                if op.type != capstone.x86.X86_OP_MEM or not op.access & capstone.CS_AC_WRITE:
                    continue
                base = ins.reg_name(op.mem.base) if op.mem.base else None
                assert base in {"ecx", "eax", "ebp"}, f"{text(ins)} stores somewhere unexpected"


class TestTheGate:
    def test_it_preserves_the_hero_index(self):
        """`eax` is the index `pickHeroIndex` just returned, and the stock code stores it to
        `[ebp-0x20]` one instruction after the hook. Every path through the gate must hand it
        back untouched, or the AI's retry list fills with heroes it never chose."""
        decoded = gate_instructions()
        stream = [text(ins) for ins in decoded.values()]
        assert stream[0] == "push eax"
        # One `pop eax` on the miss path and one on the hit path, and no path reaching an exit
        # without having taken one.
        assert stream.count("pop eax") == 2
        for va, ins in decoded.items():
            if ins.mnemonic == "jmp" and int(ins.op_str, 16) not in decoded:
                before = [text(i) for a, i in decoded.items() if a < va]
                assert "pop eax" in before, f"{text(ins)} leaves with the index still pushed"

    def test_it_interns_the_name_the_way_the_engine_does(self):
        decoded = gate_instructions()
        stream = [text(ins) for ins in decoded.values()]
        assert f"mov ecx, dword ptr [0x{THE_NAME_KEY_GENERATOR:x}]" in stream
        assert "push edi" in stream, "the name is the AsciiString the stock code just resolved"
        assert f"call 0x{NAME_KEY_FROM_STRING:x}" in stream

    def test_it_converts_seconds_with_the_logic_rate_read_at_run_time(self):
        """Five logic frames a second is the engine's, not this patch's. Reading the global keeps
        it that way, and keeps `render-rate`'s client rate out of it."""
        stream = [text(ins) for ins in gate_instructions().values()]
        assert f"imul eax, dword ptr [0x{LOGIC_FRAMES_PER_SECOND:x}]" in stream

    def test_it_compares_against_the_logic_frame(self):
        stream = [text(ins) for ins in gate_instructions().values()]
        assert f"mov ecx, dword ptr [0x{THE_GAME_LOGIC:x}]" in stream
        assert f"cmp dword ptr [ecx + 0x{GAME_LOGIC_FRAME:x}], eax" in stream

    def test_a_hero_still_on_the_clock_takes_the_rejection_edge(self):
        """`jb` on `frame < seconds * rate`. `jae` would be a patch that blocks a hero once its
        delay has *elapsed*, which assembles and verifies identically."""
        decoded = gate_instructions()
        compare = next(
            va
            for va, i in decoded.items()
            if i.op_str.startswith(f"dword ptr [ecx + 0x{GAME_LOGIC_FRAME:x}]")
        )
        branch = min(va for va in decoded if va > compare and decoded[va].mnemonic.startswith("j"))
        assert decoded[branch].mnemonic == "jb"
        landing = int(decoded[branch].op_str, 16)
        assert text(decoded[landing]) == f"jmp 0x{AI_HERO_REJECT:x}"

    def test_the_pop_between_the_compare_and_the_branch_keeps_the_flags(self):
        """`pop` is the one way to restore `eax` there without disturbing the comparison it sits
        between - the reason the sequence reads oddly."""
        decoded = gate_instructions()
        compare = next(
            va
            for va, i in decoded.items()
            if i.op_str.startswith(f"dword ptr [ecx + 0x{GAME_LOGIC_FRAME:x}]")
        )
        following = min(va for va in decoded if va > compare)
        assert text(decoded[following]) == "pop eax"

    def test_a_hero_with_no_delay_resumes_the_stock_instruction(self):
        """The miss path must replay the six bytes the hook displaced and give the function back,
        or the ThingFactory lookup that follows reads a stale `ecx`."""
        decoded = gate_instructions()
        stream = [text(ins) for ins in decoded.values()]
        displaced = f"mov ecx, dword ptr [0x{THE_THING_FACTORY:x}]"
        assert stream.count(displaced) == 1
        resume = next(va for va, i in decoded.items() if text(i) == displaced)
        following = min(va for va in decoded if va > resume)
        assert text(decoded[following]) == f"jmp 0x{AI_HERO_NAME_RESOLVED_RESUME:x}"

    def test_it_has_exactly_two_outward_exits_and_both_are_stock_edges(self):
        decoded = gate_instructions()
        outward = {
            int(ins.op_str, 16)
            for ins in decoded.values()
            if ins.mnemonic == "jmp" and int(ins.op_str, 16) not in decoded
        }
        assert outward == {AI_HERO_NAME_RESOLVED_RESUME, AI_HERO_REJECT}

    def test_it_scans_the_whole_table_and_no_further(self):
        stream = [text(ins) for ins in gate_instructions().values()]
        assert f"cmp ecx, 0x{BASE + TABLE_BYTES:x}" in stream
        assert f"mov ecx, 0x{BASE:x}" in stream


class TestTheParser:
    def test_it_runs_the_stock_parser_first(self):
        """Token splitting, macro expansion and the vector's housekeeping stay the engine's; this
        only post-processes what they produced."""
        stream = [text(ins) for ins in parser_instructions().values()]
        assert f"call 0x{INI_PARSE_STRING_LIST:x}" in stream
        pushes = stream[: stream.index(f"call 0x{INI_PARSE_STRING_LIST:x}")]
        for slot in ("0x14", "0x10", "0xc", "8"):
            assert f"push dword ptr [ebp + {slot}]" in pushes, slot

    def test_it_is_cdecl_like_every_other_row(self):
        decoded = parser_instructions()
        last = max(decoded)
        assert text(decoded[last]) == "ret", "a row that cleaned its own arguments would unbalance"
        assert text(decoded[max(va for va in decoded if va < last)]) == "leave"

    def test_it_writes_the_stripped_name_back_through_the_engine(self):
        """`AsciiString::set` rather than a poke into the buffer: the string is refcounted, and
        the engine owns how a shorter one is stored."""
        assert f"call 0x{ASCII_STRING_SET:x}" in [
            text(ins) for ins in parser_instructions().values()
        ]

    def test_it_looks_for_a_colon(self):
        assert "cmp cl, 0x3a" in [text(ins) for ins in parser_instructions().values()]

    def test_the_digit_scan_saturates_rather_than_wrapping(self):
        stream = [text(ins) for ins in parser_instructions().values()]
        assert f"cmp eax, 0x{MAX_SECONDS:x}" in stream
        assert f"mov eax, 0x{MAX_SECONDS:x}" in stream

    def test_the_clamp_keeps_the_frame_conversion_inside_an_int32(self):
        """The gate multiplies the stored seconds by the logic rate. Five is the rate today; the
        margin here is what makes the clamp a bound rather than a coincidence."""
        assert MAX_SECONDS * 30 < 2**31

    def test_it_erases_before_it_records(self):
        """A re-parse is authoritative: a name that lost its suffix has to lose its delay, not
        keep the one an earlier parse left standing."""
        decoded = parser_instructions()
        erase = next(va for va, i in decoded.items() if text(i) == "and dword ptr [ecx], 0")
        claim = next(va for va, i in decoded.items() if text(i) == "mov dword ptr [ecx], eax")
        assert erase < claim

    def test_a_freed_slot_loses_its_seconds_too(self):
        """A free slot has to read as zero seconds, because the gate's lookup treats a matched
        slot's second dword as the delay without asking whether the slot is live."""
        stream = [text(ins) for ins in parser_instructions().values()]
        assert "and dword ptr [ecx], 0" in stream
        assert "and dword ptr [ecx + 4], 0" in stream

    def test_the_name_buffer_leaves_room_for_a_terminator(self):
        """The copy stops one byte short of the buffer's end, and the terminator goes there."""
        decoded = parser_instructions()
        stream = [text(ins) for ins in decoded.values()]
        assert "lea ecx, [ebp - 5]" in stream
        assert "lea eax, [ebp - 0x104]" in stream
        assert "mov byte ptr [eax], 0" in stream


class TestApply:
    @pytest.fixture
    def image(self) -> bytearray:
        return ai_hero_build_delay_image()

    def test_apply_then_verify(self, image):
        patch = AiHeroBuildDelayPatch()
        patch.apply(image)
        assert patch.verify(image) == []

    def test_apply_then_detect(self, image):
        AiHeroBuildDelayPatch().apply(image)
        assert AiHeroBuildDelayPatch.detect(image) is not None

    def test_the_hook_is_a_jmp_to_the_gate_padded_to_six_bytes(self, image):
        """The displaced instruction is six bytes and `jmp rel32` is five, so the sixth is a
        `nop` - without it a disassembler walks into the tail of the instruction that was there."""
        AiHeroBuildDelayPatch().apply(image)
        located = find_section(image, SECTION_NAME)
        assert located is not None
        section_va, _, _ = located
        _parse_va, gate_va = layout(section_va)
        hook = at(image, HOOK_VA, len(HOOK_ORIGINAL))
        assert len(hook) == 6
        assert hook[0] == 0xE9
        assert hook[5] == 0x90
        assert HOOK_VA + 5 + struct.unpack("<i", hook[1:5])[0] == gate_va

    def test_the_field_table_row_points_at_the_parser_not_the_gate(self, image):
        """The two routines share a section and are both reached by address, so aiming either
        edit at the other's entry point is the mistake nothing else here would catch."""
        AiHeroBuildDelayPatch().apply(image)
        located = find_section(image, SECTION_NAME)
        assert located is not None
        section_va, _, _ = located
        parse_va, gate_va = layout(section_va)
        table = read_field_table(image, ARMY_DEFINITION_FIELD_TABLE)
        preceding = entries_before(image, table, KEYWORD)
        assert preceding is not None
        assert table[len(preceding)][1] == parse_va
        assert parse_va != gate_va

    def test_it_leaves_the_other_rows_of_the_table_alone(self, image):
        """`OffensiveBuildings` and `ScavangedResourceBuildings` name the same stock parser, and
        neither wants a colon to mean anything."""
        before = read_field_table(image, ARMY_DEFINITION_FIELD_TABLE)
        AiHeroBuildDelayPatch().apply(image)
        after = read_field_table(image, ARMY_DEFINITION_FIELD_TABLE)
        assert len(before) == len(after)
        changed = [i for i, (b, a) in enumerate(zip(before, after, strict=True)) if b != a]
        assert len(changed) == 1

    def test_the_delay_table_starts_empty(self, image):
        AiHeroBuildDelayPatch().apply(image)
        located = find_section(image, SECTION_NAME)
        assert located is not None
        _, section_off, _ = located
        assert bytes(image[section_off : section_off + TABLE_BYTES]) == bytes(TABLE_BYTES)

    def test_the_section_holds_room_for_every_slot(self, image):
        AiHeroBuildDelayPatch().apply(image)
        located = find_section(image, SECTION_NAME)
        assert located is not None
        _, _, vsize = located
        assert vsize == TABLE_BYTES + len(build_code(located[0]))
        assert TABLE_BYTES == SLOTS * 8

    def test_the_section_name_survives_the_eight_byte_pe_field(self):
        assert len(SECTION_NAME) <= 8

    def test_refuses_to_apply_twice(self, image):
        AiHeroBuildDelayPatch().apply(image)
        with pytest.raises(ValueError):
            AiHeroBuildDelayPatch().apply(image)

    @pytest.mark.parametrize("anchor", sorted(ANCHORS))
    def test_refuses_a_build_where_an_anchor_moved(self, image, anchor):
        off = va_to_offset(image, anchor)
        image[off] ^= 0xFF
        with pytest.raises(ValueError, match="hero builder is not this build's"):
            AiHeroBuildDelayPatch().apply(image)

    def test_refuses_a_table_that_does_not_name_the_keyword(self, image):
        """Located by name, so a table that has been rebuilt without the row - or a build where
        the keyword is spelled differently - fails rather than repointing whatever sits at 29."""
        off = va_to_offset(image, ARMY_DEFINITION_FIELD_TABLE + 29 * ROW_SIZE)
        struct.pack_into("<I", image, off, 0xDEAD0000)
        with pytest.raises(ValueError, match="does not name"):
            AiHeroBuildDelayPatch().apply(image)

    def test_refuses_a_build_whose_table_references_disagree(self, image):
        off = va_to_offset(image, ARMY_DEFINITION_FIELD_TABLE_REFS[0])
        struct.pack_into("<I", image, off + 1, ARMY_DEFINITION_FIELD_TABLE + 0x10)
        with pytest.raises(ValueError, match="disagree"):
            AiHeroBuildDelayPatch().apply(image)

    def test_refuses_an_unmapped_build(self):
        with pytest.raises(ValueError, match="not mapped"):
            AiHeroBuildDelayPatch().apply(bytearray(b"MZ" + b"\x00" * 0x400))


class TestVerify:
    def test_rejects_an_unpatched_file(self):
        problems = AiHeroBuildDelayPatch().verify(ai_hero_build_delay_image())
        assert problems == [f"no {SECTION_NAME} section: the file does not carry this patch"]

    def test_rejects_a_cave_whose_code_was_altered(self):
        image = ai_hero_build_delay_image()
        patch = AiHeroBuildDelayPatch()
        patch.apply(image)
        located = find_section(image, SECTION_NAME)
        assert located is not None
        _, section_off, _ = located
        image[section_off + TABLE_BYTES] ^= 0xFF
        assert patch.verify(image) == [f"the {SECTION_NAME} cave does not hold the expected code"]

    def test_accepts_a_file_whose_delay_table_has_been_written(self):
        """The table is filled while the engine reads its INI, so a binary that has been run holds
        whatever that run left there. Verifying it would fail on every real install."""
        image = ai_hero_build_delay_image()
        patch = AiHeroBuildDelayPatch()
        patch.apply(image)
        located = find_section(image, SECTION_NAME)
        assert located is not None
        _, section_off, _ = located
        struct.pack_into("<II", image, section_off, 0x1234, 300)
        assert patch.verify(image) == []

    def test_rejects_a_hook_pointing_somewhere_else(self):
        image = ai_hero_build_delay_image()
        patch = AiHeroBuildDelayPatch()
        patch.apply(image)
        off = va_to_offset(image, HOOK_VA)
        struct.pack_into("<i", image, off + 1, 0x20)
        assert any("hook jumps to" in problem for problem in patch.verify(image))

    def test_rejects_a_table_row_pointing_somewhere_else(self):
        image = ai_hero_build_delay_image()
        patch = AiHeroBuildDelayPatch()
        patch.apply(image)
        off = va_to_offset(image, ARMY_DEFINITION_FIELD_TABLE + 29 * ROW_SIZE + 4)
        struct.pack_into("<I", image, off, INI_PARSE_STRING_LIST)
        assert any("row parses through" in problem for problem in patch.verify(image))


class TestRegistration:
    def test_it_is_registered_under_its_name(self):
        assert PATCHES[AiHeroBuildDelayPatch.name] is AiHeroBuildDelayPatch

    def test_it_is_not_experimental(self):
        assert not AiHeroBuildDelayPatch.experimental

    def test_it_declares_the_keyword_it_widens(self):
        """`Opaque[]`, not a list of object references: `Name:Seconds` is not a name anything
        could be looked up by, which is exactly what `commandset-button-upgrade` says about its
        own `Name:Slot` tokens."""
        (field,) = AiHeroBuildDelayPatch().ini_surface().fields
        assert (field.block, field.name, field.type) == ("ArmyDefinition", KEYWORD, "Opaque[]")

    def test_the_surface_applies_and_reverts_against_the_live_schema(self):
        """A misspelled block or type name reaches `sage_ini` as a reported problem rather than an
        exception, so nothing else here would notice one."""
        cls = REGISTRY["ArmyDefinition"]
        stock = cls._fieldspec[KEYWORD]
        with AiHeroBuildDelayPatch().ini_surface().activate() as problems:
            assert problems == []
            assert cls._fieldspec[KEYWORD] is not stock
        assert cls._fieldspec[KEYWORD] is stock


@pytest.mark.skipif(not _GAME_DAT.exists(), reason="needs the real game.dat")
class TestInstalledBinary:
    """Against the real binary, which is the only thing that can say the addresses are right.

    The stand-in is built from this patch's own anchor table and its own idea of where the field
    table's rows sit, so it round-trips whatever those say. Only the shipped `game.dat` can
    confirm that `0x009A09E3` is between the hero name and its template lookup rather than the
    middle of some other load, and that row 29 of the real `ArmyDefinition` table is the keyword
    this patch is named for.
    """

    @pytest.fixture(scope="class")
    def stock(self) -> bytes:
        return _GAME_DAT.read_bytes()

    def test_every_site_holds_its_stock_bytes(self, stock):
        for va, expected in ((HOOK_VA, HOOK_ORIGINAL), *ANCHORS.items()):
            assert at(stock, va, len(expected)) == expected, f"0x{va:08x}"

    def test_the_row_the_patch_repoints_is_the_keyword(self, stock):
        table = read_field_table(stock, ARMY_DEFINITION_FIELD_TABLE)
        preceding = entries_before(stock, table, KEYWORD)
        assert preceding is not None
        assert ARMY_DEFINITION_FIELD_TABLE + len(preceding) * ROW_SIZE == _HERO_ROW_VA

    def test_the_row_parses_through_the_shared_string_list_parser(self, stock):
        assert struct.unpack("<I", at(stock, _HERO_ROW_VA + 4, 4))[0] == INI_PARSE_STRING_LIST

    def test_the_shared_parser_is_shared(self, stock):
        """The reason the row is repointed and the function is not: two other keywords name it,
        and a colon means nothing in either."""
        table = read_field_table(stock, ARMY_DEFINITION_FIELD_TABLE)
        sharers = [entry for entry in table if entry[1] == INI_PARSE_STRING_LIST]
        assert len(sharers) > 1

    def test_both_table_references_name_the_same_table(self, stock):
        found = resolve_table(
            stock,
            ARMY_DEFINITION_FIELD_TABLE_REFS,
            ARMY_DEFINITION_FIELD_TABLE_REF_OPCODES,
            "ArmyDefinition",
        )
        assert found == ARMY_DEFINITION_FIELD_TABLE

    def test_the_logic_rate_is_five_frames_a_second(self, stock):
        """Five, not the thirty four bytes above it - that one is the client rate. A delay
        converted with the wrong global would be six times too long."""
        assert struct.unpack("<I", at(stock, LOGIC_FRAMES_PER_SECOND, 4))[0] == 5

    def test_apply_verify_detect_round_trip(self, stock):
        data = bytearray(stock)
        patch = AiHeroBuildDelayPatch()
        patch.apply(data)
        assert patch.verify(data) == []
        assert AiHeroBuildDelayPatch.detect(data) is not None

    def test_the_stock_binary_carries_no_delay(self, stock):
        assert AiHeroBuildDelayPatch.detect(stock) is None

    @pytest.mark.parametrize(
        "other",
        ["ai-construction-gate", "ai-flag-capture-gate", "ai-revive-gate", "hero-recruit-parallel"],
    )
    def test_it_composes_with_the_other_ai_patches_in_either_order(self, stock, other):
        for order in ((AiHeroBuildDelayPatch.name, other), (other, AiHeroBuildDelayPatch.name)):
            data = bytearray(stock)
            for name in order:
                PATCHES[name]().apply(data)
            for name in order:
                assert PATCHES[name]().verify(data) == [], f"{order} broke {name}"
