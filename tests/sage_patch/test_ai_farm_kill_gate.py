"""Tests for the AI farm raid fields.

The cave is hand-assembled x86 that cannot be executed here, so the tests that matter disassemble
it back and assert it says what it was meant to say. The properties `apply` and `verify` cannot
see are the ones a match would only show as an AI behaving oddly:

* **every wrapper hands the stock routine exactly what its caller passed.** Three of them stand
  in vtable slots and one in front of the recruiter's object test, so `ecx` and the stack
  arguments have to be the caller's when the stock code runs, and each wrapper has to clean the
  stack the way the routine it replaces does;
* **which verdict takes which exit.** A faction that declined is answered `false`; a candidate
  the army did not flag is answered `false`. Swapping either pair inverts the feature;
* **an army that sets nothing is stock.** Unset sizes and intervals skip the rewrite, and an army
  with no flagged member accepts whoever the stock test accepts;
* **only a farm squad's candidates are screened.** The recruiter's test is shared by every team
  the AI builds, so the mark has to be tested before anything else;
* **the rebuilt tables hold the real rows and nothing after them.** Neither stock table has a
  terminator, so a rebuild that copied to the first zero would carry stray pointers along as rows.
"""

from __future__ import annotations

import struct

import pytest

from sage_patch.addresses import (
    AI_DATA_ARMY_DEFINITION,
    AI_DATA_SET_VALUE,
    AI_FARM_KILL_SQUAD_BUILD,
    AI_FARM_KILL_SQUAD_BUILD_SLOT,
    AI_FARM_KILL_SQUAD_NEXT_RUN_KEY,
    AI_FARM_KILL_SQUAD_RESET,
    AI_FARM_KILL_SQUAD_RESET_SLOT,
    AI_FARM_KILL_SQUAD_RUN_GATE,
    AI_FARM_KILL_SQUAD_RUN_GATE_SLOT,
    AI_FARM_KILL_SQUAD_VTABLE,
    AI_TACTIC_PLAYER,
    AI_TEAM_BUILDER_PLAYER,
    AI_TEAM_PROTOTYPE_FORBIDDEN_KIND_OF,
    AI_TEAM_PROTOTYPE_MAX_SIZE,
    AI_TEAM_PROTOTYPE_MIN_SIZE,
    AI_TEAM_RECRUIT_ACCEPT,
    AI_TEAM_RECRUIT_ACCEPT_CALLS,
    AI_TEAM_RECRUIT_FORBIDDEN_KIND_OF,
    ARMY_DEFINITION_FIELD_TABLE,
    ARMY_DEFINITION_FIELD_TABLE_REFS,
    ARMY_DEFINITION_PHASE_DURATION_MID_GAME,
    ARMY_DEFINITION_PHASE_DURATION_RUSH,
    ARMY_MEMBER_DEFINITION_ALLOC,
    ARMY_MEMBER_DEFINITION_FIELD_TABLE,
    ARMY_MEMBER_DEFINITION_FIELD_TABLE_REFS,
    GAME_LOGIC_RANDOM_VALUE,
    INI_PARSE_BOOL,
    INI_PARSE_INT,
    LOGIC_FRAMES_PER_SECOND,
    NAME_KEY_FROM_STRING,
    OPERATOR_NEW,
    SKIRMISH_AI_MANAGER_PLAYER_DATA,
    THE_SKIRMISH_AI_MANAGER,
    THING_FACTORY_FIND_TEMPLATE,
    THING_TEMPLATE_IS_EQUIVALENT,
)
from sage_patch.patches.ai_farm_kill_gate import (
    ANCHORS,
    ARMY_KEYWORDS,
    FLAGS_OFFSET,
    MARKER_BIT,
    MARKER_BYTE,
    MEMBER_KEYWORDS,
    PATCHED_MEMBER_SIZE,
    SECTION_NAME,
    SLOT_SIZE,
    SLOTS,
    TABLE_BYTES,
    AiFarmKillGatePatch,
    build_code,
    layout,
    live_rows,
)
from sage_patch.patches.utils.field_tables import ROW_SIZE, read_field_table
from sage_patch.registry import PATCHES
from sage_patch.utils import find_section, read_cstring, va_to_offset

from .synthetic import (
    ARMY_DEFINITION_STAND_IN_ROWS,
    ARMY_MEMBER_DEFINITION_STAND_IN_ROWS,
    ai_farm_kill_gate_image,
)

BASE = 0x00F00000
CODE = BASE + TABLE_BYTES
PIECES = layout(BASE)
_STARTS = sorted(
    [
        PIECES.parse_bool,
        PIECES.parse_pair,
        PIECES.parse_member,
        PIECES.alloc,
        PIECES.gate,
        PIECES.reset,
        PIECES.build,
        PIECES.accept,
        CODE + len(build_code(BASE)),
    ]
)


def instructions():
    capstone = pytest.importorskip("capstone")
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    md.detail = True
    return {ins.address: ins for ins in md.disasm(build_code(BASE), CODE)}


def text(ins) -> str:
    return f"{ins.mnemonic} {ins.op_str}".strip()


def routine(start: int) -> list[str]:
    """The instructions from one named routine up to the next."""
    end = _STARTS[_STARTS.index(start) + 1]
    return [text(ins) for va, ins in instructions().items() if start <= va < end]


def patched() -> tuple[bytearray, int]:
    image = ai_farm_kill_gate_image()
    AiFarmKillGatePatch().apply(image)
    located = find_section(image, SECTION_NAME)
    assert located is not None
    return image, located[0]


def dword(image: bytes | bytearray, va: int) -> int:
    off = va_to_offset(image, va)
    assert off is not None
    return struct.unpack_from("<I", image, off)[0]


def read_bytes(image: bytes | bytearray, va: int, count: int) -> bytes:
    """Byte by byte, because one of the patched calls crosses a page of the stand-in."""
    out = bytearray()
    for index in range(count):
        off = va_to_offset(image, va + index)
        assert off is not None
        out.append(image[off])
    return bytes(out)


class TestTheCave:
    def test_it_disassembles_cleanly_to_its_end(self):
        decoded = instructions()
        last = max(decoded)
        assert last + decoded[last].size == CODE + len(build_code(BASE))

    def test_the_pieces_follow_each_other_without_overlapping(self):
        assert CODE < PIECES.parse_bool < PIECES.gate < PIECES.reset < PIECES.build < PIECES.accept
        first_keyword = min(PIECES.keywords.values())
        assert CODE + len(build_code(BASE)) <= first_keyword
        assert max(PIECES.keywords.values()) < PIECES.army_table
        assert PIECES.army_table % ROW_SIZE == 0

    def test_every_branch_and_internal_call_stays_inside_the_cave(self):
        end = CODE + len(build_code(BASE))
        for ins in instructions().values():
            if ins.mnemonic.startswith("j") and ins.mnemonic != "jmp":
                assert CODE <= int(ins.op_str, 16) < end, f"{text(ins)} leaves the cave"

    def test_the_only_ways_out_are_the_routines_it_means_to_reach(self):
        end = CODE + len(build_code(BASE))
        outward = {
            int(ins.op_str, 16)
            for ins in instructions().values()
            if ins.mnemonic in {"call", "jmp"}
            and ins.op_str.startswith("0x")
            and not CODE <= int(ins.op_str, 16) < end
        }
        assert outward == {
            NAME_KEY_FROM_STRING,
            INI_PARSE_BOOL,
            INI_PARSE_INT,
            OPERATOR_NEW,
            SKIRMISH_AI_MANAGER_PLAYER_DATA,
            AI_FARM_KILL_SQUAD_RUN_GATE,
            AI_FARM_KILL_SQUAD_RESET,
            AI_FARM_KILL_SQUAD_BUILD,
            GAME_LOGIC_RANDOM_VALUE,
            AI_DATA_SET_VALUE,
            AI_TEAM_RECRUIT_ACCEPT,
            THING_FACTORY_FIND_TEMPLATE,
            THING_TEMPLATE_IS_EQUIVALENT,
        }

    def test_the_stack_is_balanced_on_every_path_through_every_routine(self):
        """Walks each routine's control flow with a stack depth, taking both sides of every
        branch, and requires every `ret` to be reached at depth zero with the right cleanup."""
        decoded = instructions()
        callee_pops = {
            NAME_KEY_FROM_STRING: 4,
            SKIRMISH_AI_MANAGER_PLAYER_DATA: 4,
            THING_FACTORY_FIND_TEMPLATE: 4,
            THING_TEMPLATE_IS_EQUIVALENT: 4,
            AI_DATA_SET_VALUE: 8,
            AI_FARM_KILL_SQUAD_BUILD: 8,
        }
        internal = {
            int(ins.op_str, 16)
            for ins in decoded.values()
            if ins.mnemonic == "call" and CODE <= int(ins.op_str, 16)
        }
        eligible = max(internal)
        assert eligible > PIECES.accept
        seen: dict[int, int] = {}

        def walk(va: int, depth: int) -> None:
            while True:
                if va in seen:
                    assert seen[va] == depth, f"0x{va:08x} reached at two stack depths"
                    return
                seen[va] = depth
                ins = decoded[va]
                target = int(ins.op_str, 16) if ins.op_str.startswith("0x") else None
                if ins.mnemonic == "push":
                    depth += 4
                elif ins.mnemonic == "pop":
                    depth -= 4
                elif ins.mnemonic in {"add", "sub"} and ins.op_str.startswith("esp,"):
                    amount = int(ins.op_str.split(",")[1], 16)
                    depth += -amount if ins.mnemonic == "add" else amount
                elif ins.mnemonic == "leave":
                    depth = 0
                elif ins.mnemonic == "call":
                    assert target is not None
                    depth -= 8 if target == eligible else callee_pops.get(target, 0)
                elif ins.mnemonic == "ret":
                    assert depth == 0, f"ret at 0x{va:08x} with {depth} bytes still pushed"
                    return
                elif ins.mnemonic == "jmp":
                    assert target is not None
                    if not CODE <= target:
                        assert depth == 0, f"tail jump at 0x{va:08x} with {depth} bytes pushed"
                        return
                    va = target
                    continue
                elif ins.mnemonic.startswith("j"):
                    assert target is not None
                    walk(target, depth)
                va += ins.size

        for entry in [*_STARTS[:-1], *sorted(internal)]:
            walk(entry, 0)
        assert set(seen) == set(decoded), "some instruction is reachable from no entry"

    def test_only_the_faction_table_the_prototype_and_a_new_member_are_written(self):
        capstone = pytest.importorskip("capstone")
        for ins in instructions().values():
            if ins.mnemonic in {"push", "call"}:
                continue
            for op in ins.operands:
                if op.type == capstone.x86.X86_OP_MEM and op.access & capstone.CS_AC_WRITE:
                    base = ins.reg_name(op.mem.base)
                    assert base in {"ecx", "edx", "eax", "esi"}, f"{text(ins)} stores elsewhere"


class TestTheGate:
    def test_it_asks_the_ai_manager_about_the_tactics_own_player(self):
        stream = routine(PIECES.gate)
        call = stream.index(f"call 0x{SKIRMISH_AI_MANAGER_PLAYER_DATA:x}")
        assert stream[call - 2] == f"push dword ptr [ecx + 0x{AI_TACTIC_PLAYER:x}]"
        assert stream[call - 1] == f"mov ecx, dword ptr [0x{THE_SKIRMISH_AI_MANAGER:x}]"
        assert f"mov eax, dword ptr [eax + 0x{AI_DATA_ARMY_DEFINITION:x}]" in stream[call:]

    def test_the_stock_routine_gets_the_tactic_back_in_ecx(self):
        stream = routine(PIECES.gate)
        assert stream[0] == "push ecx"
        tail = stream.index(f"jmp 0x{AI_FARM_KILL_SQUAD_RUN_GATE:x}")
        assert stream[tail - 1] == "pop ecx"

    def test_a_refusal_is_false_with_the_stock_cleanup(self):
        assert routine(PIECES.gate)[-3:] == ["pop ecx", "xor al, al", "ret 4"]

    def gate_edges(self) -> tuple[list[str], int, int]:
        """The gate's instructions, and the indices its two exits start at."""
        decoded = instructions()
        order = [va for va in sorted(decoded) if PIECES.gate <= va < PIECES.reset]
        stream = [text(decoded[va]) for va in order]
        stock = stream.index(f"jmp 0x{AI_FARM_KILL_SQUAD_RUN_GATE:x}") - 1
        refusal = len(stream) - 3
        self.targets = {
            index: order.index(int(line.split()[1], 16))
            for index, line in enumerate(stream)
            if line.startswith("j") and not line.startswith("jmp")
        }
        return stream, stock, refusal

    def test_yes_runs_and_no_refuses(self):
        stream, stock, refusal = self.gate_edges()
        answer = stream.index("mov eax, dword ptr [eax + 4]")
        assert stream[answer + 1] == "cmp eax, 2"
        assert stream[answer + 2].startswith("je ") and self.targets[answer + 2] == stock
        assert stream[answer + 3] == "cmp eax, 1"
        assert stream[answer + 4].startswith("je ") and self.targets[answer + 4] == refusal

    def test_an_unwritten_answer_runs_only_for_an_army_that_flags_a_member(self):
        """Reached two ways - no slot at all, or a slot holding only a size or an interval - and
        both fall to the same question, asked of the army saved across the slot lookup."""
        stream, stock, refusal = self.gate_edges()
        lookup = next(i for i, line in enumerate(stream) if line.startswith("call 0xf"))
        assert stream[lookup - 1] == "push eax"
        assert stream[lookup + 1 : lookup + 3] == ["pop edx", "test eax, eax"]
        unwritten = self.targets[lookup + 3]
        assert stream[unwritten] == "mov eax, edx"
        assert stream[unwritten + 1].startswith("call 0xf")
        assert stream[unwritten + 2] == "test al, al"
        assert stream[unwritten + 3].startswith("je ") and self.targets[unwritten + 3] == refusal
        assert unwritten + 4 == stock
        assert stream[unwritten - 1].startswith("je "), "No falls through to the flag question"

    def test_a_player_with_no_army_definition_is_left_to_the_stock_routine(self):
        stream, stock, _refusal = self.gate_edges()
        lookup = next(i for i, line in enumerate(stream) if line.startswith("call 0xf"))
        early = [index for index in self.targets if index < lookup]
        assert len(early) == 2
        assert all(self.targets[index] == stock for index in early)


class TestTheReset:
    def test_it_runs_the_stock_routine_first_on_the_same_tactic(self):
        stream = routine(PIECES.reset)
        assert stream[:4] == [
            "push esi",
            "push edi",
            "mov esi, ecx",
            f"call 0x{AI_FARM_KILL_SQUAD_RESET:x}",
        ]

    def test_an_unset_interval_leaves_what_the_stock_routine_stored(self):
        stream = routine(PIECES.reset)
        test = stream.index("cmp ecx, 0")
        assert stream[test - 1] == "mov ecx, dword ptr [eax + 0x14]"
        assert stream[test + 1].startswith("jle ")
        assert stream[-3:] == ["pop edi", "pop esi", "ret"]

    def test_it_converts_seconds_with_the_logic_rate_read_at_run_time(self):
        stream = routine(PIECES.reset)
        assert f"imul ecx, dword ptr [0x{LOGIC_FRAMES_PER_SECOND:x}]" in stream
        assert f"imul edx, dword ptr [0x{LOGIC_FRAMES_PER_SECOND:x}]" in stream

    def test_it_stores_the_next_run_frame_on_the_players_record(self):
        stream = routine(PIECES.reset)
        call = stream.index(f"call 0x{AI_DATA_SET_VALUE:x}")
        assert stream[call - 3 : call] == [
            "push eax",
            f"push 0x{AI_FARM_KILL_SQUAD_NEXT_RUN_KEY:x}",
            "mov ecx, edi",
        ]
        assert stream[call - 4] == "add eax, dword ptr [ecx + 0x40]"

    def test_the_random_draw_is_low_then_high(self):
        stream = routine(PIECES.reset)
        call = stream.index(f"call 0x{GAME_LOGIC_RANDOM_VALUE:x}")
        assert stream[call - 2 : call] == ["push ecx", "push edx"]


class TestTheBuild:
    def test_it_passes_both_arguments_to_the_stock_routine(self):
        stream = routine(PIECES.build)
        call = stream.index(f"call 0x{AI_FARM_KILL_SQUAD_BUILD:x}")
        assert stream[:call] == [
            "push esi",
            "push edi",
            "mov esi, dword ptr [esp + 0xc]",
            "mov edi, ecx",
            "push dword ptr [esp + 0x10]",
            "push esi",
        ]

    def test_it_marks_the_prototype_whatever_else_happens(self):
        stream = routine(PIECES.build)
        mark = f"or byte ptr [esi + 0x{AI_TEAM_PROTOTYPE_FORBIDDEN_KIND_OF + MARKER_BYTE:x}], 4"
        call = stream.index(f"call 0x{AI_FARM_KILL_SQUAD_BUILD:x}")
        assert stream[call + 1] == mark
        assert MARKER_BIT == 4

    def test_archers_are_let_in_only_for_an_army_that_flags_members(self):
        stream = routine(PIECES.build)
        lift = f"and byte ptr [esi + 0x{AI_TEAM_PROTOTYPE_FORBIDDEN_KIND_OF + 0x10:x}], 0xdf"
        at = stream.index(lift)
        assert stream[at - 2] == "test al, al"
        assert stream[at - 1].startswith("je ")

    def test_an_unset_size_leaves_the_stock_numbers(self):
        stream = routine(PIECES.build)
        test = stream.index("cmp ecx, 0")
        assert stream[test - 1] == "mov ecx, dword ptr [eax + 0xc]"
        assert stream[test + 1].startswith("jle ")

    def test_the_minimum_is_at_least_one_and_the_maximum_at_least_the_minimum(self):
        stream = routine(PIECES.build)
        assert "mov edx, 1" in stream
        assert stream.index("cmp edx, 1") < stream.index("cmp ecx, edx")

    def test_it_writes_the_minimum_and_draws_the_maximum(self):
        stream = routine(PIECES.build)
        call = stream.index(f"call 0x{GAME_LOGIC_RANDOM_VALUE:x}")
        assert f"mov dword ptr [esi + 0x{AI_TEAM_PROTOTYPE_MIN_SIZE:x}], edx" in stream[:call]
        assert stream[call + 2] == f"mov dword ptr [esi + 0x{AI_TEAM_PROTOTYPE_MAX_SIZE:x}], eax"

    def test_it_returns_true_and_cleans_two_arguments(self):
        assert routine(PIECES.build)[-4:] == ["mov al, 1", "pop edi", "pop esi", "ret 8"]


class TestTheAccept:
    def test_a_team_without_the_mark_goes_straight_to_the_stock_test(self):
        stream = routine(PIECES.accept)
        mark = AI_TEAM_RECRUIT_FORBIDDEN_KIND_OF + MARKER_BYTE
        assert stream[:3] == [
            "mov eax, dword ptr [esp + 8]",
            f"test byte ptr [eax + 0x{mark:x}], 4",
            stream[2],
        ]
        assert stream[2].startswith("je ")
        decoded = instructions()
        target = int(stream[2].split()[1], 16)
        assert text(decoded[target]) == f"jmp 0x{AI_TEAM_RECRUIT_ACCEPT:x}"

    def test_the_mark_is_the_same_bit_the_build_sets(self):
        """`prototypePart` is the prototype `+0x12C`, so the two offsets name one byte."""
        assert AI_TEAM_PROTOTYPE_FORBIDDEN_KIND_OF - AI_TEAM_RECRUIT_FORBIDDEN_KIND_OF == 0x12C

    def test_the_builder_survives_the_question_and_a_refusal_cleans_three_arguments(self):
        stream = routine(PIECES.accept)
        ask = next(i for i, line in enumerate(stream) if line.startswith("call 0xf"))
        assert stream[ask - 3 : ask] == [
            "push ecx",
            "push eax",
            f"push dword ptr [ecx + 0x{AI_TEAM_BUILDER_PLAYER:x}]",
        ]
        assert stream[ask + 1 : ask + 6] == [
            "pop ecx",
            "test al, al",
            stream[ask + 3],
            "xor al, al",
            "ret 0xc",
        ]
        assert stream[ask + 3].startswith("jne ")

    def test_the_phase_comes_from_whole_seconds_against_the_two_phase_lengths(self):
        stream = routine(PIECES.accept)
        assert f"div dword ptr [0x{LOGIC_FRAMES_PER_SECOND:x}]" in stream
        rush = stream.index(
            f"cvttss2si ecx, dword ptr [ebp + 0x{ARMY_DEFINITION_PHASE_DURATION_RUSH:x}]"
        )
        mid = stream.index(
            f"cvttss2si edx, dword ptr [ebp + 0x{ARMY_DEFINITION_PHASE_DURATION_MID_GAME:x}]"
        )
        assert rush < mid
        assert stream[mid + 1] == "add ecx, edx"
        assert stream.count("inc edi") == 2

    def test_a_member_is_matched_by_template_equivalence_in_its_phase(self):
        stream = routine(PIECES.accept)
        phase = stream.index(f"cmp byte ptr [eax + edi + 0x{FLAGS_OFFSET:x}], 0")
        find = stream.index(f"call 0x{THING_FACTORY_FIND_TEMPLATE:x}")
        same = stream.index(f"call 0x{THING_TEMPLATE_IS_EQUIVALENT:x}")
        assert phase < find < same
        assert stream[same - 3 : same] == [
            "mov ecx, dword ptr [esp + 0x18]",
            "mov ecx, dword ptr [ecx + 4]",
            "push eax",
        ]

    def test_an_army_that_flags_nobody_accepts_whoever_the_stock_test_accepts(self):
        stream = routine(PIECES.accept)
        at = stream.index("test bl, bl")
        assert stream[at + 1].startswith("je ")
        assert stream[at + 2] == "xor al, al"
        assert stream[-6:] == ["mov al, 1", "pop ebp", "pop edi", "pop esi", "pop ebx", "ret 8"]


class TestTheParsers:
    def test_the_bool_goes_through_the_stock_parser_into_a_local(self):
        stream = routine(PIECES.parse_bool)
        call = stream.index(f"call 0x{INI_PARSE_BOOL:x}")
        assert stream[call - 5 : call] == [
            "lea eax, [ebp - 4]",
            "push 0",
            "push eax",
            "push dword ptr [ebp + 0xc]",
            "push dword ptr [ebp + 8]",
        ]
        assert stream[-2:] == ["leave", "ret"]

    def test_no_is_recorded_as_one_and_yes_as_two(self):
        """Zero stays free to mean the line was never written."""
        stream = routine(PIECES.parse_bool)
        at = stream.index("cmp byte ptr [ebp - 4], 0")
        assert stream[at - 1] == "xor ecx, ecx"
        assert stream[at + 1 : at + 4] == ["setne cl", "inc ecx", "mov dword ptr [eax + 4], ecx"]

    def test_a_pair_reads_two_integers_before_it_looks_for_the_slot(self):
        stream = routine(PIECES.parse_pair)
        calls = [i for i, line in enumerate(stream) if line == f"call 0x{INI_PARSE_INT:x}"]
        assert len(calls) == 2
        assert stream[calls[0] - 5] == "lea eax, [ebp - 8]"
        assert stream[calls[1] - 5] == "lea eax, [ebp - 4]"
        assert stream.index("add eax, dword ptr [ebp + 0x14]") > calls[1]
        assert stream[-2:] == ["leave", "ret"]

    def test_the_member_shorthand_copies_one_answer_to_all_three_phases(self):
        stream = routine(PIECES.parse_member)
        assert stream[:4] == ["push dword ptr [esp + 0x10]"] * 4
        assert stream[4:] == [
            f"call 0x{INI_PARSE_BOOL:x}",
            "add esp, 0x10",
            "mov eax, dword ptr [esp + 0xc]",
            "mov cl, byte ptr [eax]",
            "mov byte ptr [eax + 1], cl",
            "mov byte ptr [eax + 2], cl",
            "ret",
        ]

    def test_a_new_member_has_its_flags_cleared_and_the_size_left_for_the_caller(self):
        assert routine(PIECES.alloc) == [
            "push dword ptr [esp + 4]",
            f"call 0x{OPERATOR_NEW:x}",
            "pop ecx",
            "test eax, eax",
            routine(PIECES.alloc)[4],
            f"and dword ptr [eax + 0x{FLAGS_OFFSET:x}], 0",
            "ret",
        ]


class TestLiveRows:
    @pytest.mark.parametrize(
        ("table", "names"),
        [
            (ARMY_DEFINITION_FIELD_TABLE, ARMY_DEFINITION_STAND_IN_ROWS),
            (ARMY_MEMBER_DEFINITION_FIELD_TABLE, ARMY_MEMBER_DEFINITION_STAND_IN_ROWS),
        ],
    )
    def test_it_stops_at_the_first_row_that_names_no_keyword(self, table, names):
        image = ai_farm_kill_gate_image()
        assert [read_cstring(image, row[0]) for row in live_rows(image, table)] == list(names)
        assert len(read_field_table(image, table)) > len(names)


class TestApply:
    def test_apply_then_verify(self):
        image, _ = patched()
        assert AiFarmKillGatePatch().verify(image) == []

    def test_it_is_registered(self):
        assert PATCHES[AiFarmKillGatePatch.name] is AiFarmKillGatePatch

    def test_the_three_vtable_slots_hold_their_wrappers(self):
        image, section_va = patched()
        pieces = layout(section_va)
        vtable = AI_FARM_KILL_SQUAD_VTABLE
        assert dword(image, vtable + AI_FARM_KILL_SQUAD_RUN_GATE_SLOT) == pieces.gate
        assert dword(image, vtable + AI_FARM_KILL_SQUAD_RESET_SLOT) == pieces.reset
        assert dword(image, vtable + AI_FARM_KILL_SQUAD_BUILD_SLOT) == pieces.build

    def test_both_recruiter_calls_reach_the_accept_wrapper(self):
        image, section_va = patched()
        for site in AI_TEAM_RECRUIT_ACCEPT_CALLS:
            raw = read_bytes(image, site, 5)
            assert raw[0] == 0xE8
            assert site + 5 + struct.unpack("<i", raw[1:])[0] == layout(section_va).accept

    def test_a_member_is_allocated_four_bytes_larger_through_the_cave(self):
        image, section_va = patched()
        raw = read_bytes(image, ARMY_MEMBER_DEFINITION_ALLOC, 7)
        assert raw[:2] == bytes([0x6A, PATCHED_MEMBER_SIZE])
        call = ARMY_MEMBER_DEFINITION_ALLOC + 2
        assert call + 5 + struct.unpack("<i", raw[3:])[0] == layout(section_va).alloc

    def test_the_army_table_is_the_real_rows_then_the_three_keywords(self):
        image, section_va = patched()
        pieces = layout(section_va)
        for ref in ARMY_DEFINITION_FIELD_TABLE_REFS:
            assert dword(image, ref + 1) == pieces.army_table
        rows = read_field_table(image, pieces.army_table)
        stock = live_rows(ai_farm_kill_gate_image(), ARMY_DEFINITION_FIELD_TABLE)
        assert rows[: len(stock)] == stock
        assert [read_cstring(image, row[0]) for row in rows[len(stock) :]] == list(ARMY_KEYWORDS)
        assert rows[-3] == (pieces.keywords[ARMY_KEYWORDS[0]], pieces.parse_bool, 0, 0)
        assert rows[-2][1:] == (pieces.parse_pair, 0x08, 0)
        assert rows[-1][1:] == (pieces.parse_pair, 0x10, 0)

    def test_the_member_table_is_the_real_rows_then_the_four_keywords(self):
        image, section_va = patched()
        pieces = layout(section_va)
        tables = {dword(image, ref + 1) for ref in ARMY_MEMBER_DEFINITION_FIELD_TABLE_REFS}
        assert len(tables) == 1
        rows = read_field_table(image, tables.pop())
        stock = live_rows(ai_farm_kill_gate_image(), ARMY_MEMBER_DEFINITION_FIELD_TABLE)
        assert rows[: len(stock)] == stock
        assert [read_cstring(image, row[0]) for row in rows[len(stock) :]] == list(MEMBER_KEYWORDS)
        assert rows[-4][1:] == (pieces.parse_member, 0, FLAGS_OFFSET)
        assert [row[1:] for row in rows[-3:]] == [
            (INI_PARSE_BOOL, 0, FLAGS_OFFSET + phase) for phase in range(3)
        ]

    def test_the_two_tables_do_not_overlap(self):
        image, section_va = patched()
        pieces = layout(section_va)
        member = dword(image, ARMY_MEMBER_DEFINITION_FIELD_TABLE_REFS[0] + 1)
        army_rows = len(read_field_table(image, pieces.army_table))
        assert member == pieces.army_table + (army_rows + 1) * ROW_SIZE

    def test_the_faction_table_starts_empty_with_room_for_every_slot(self):
        image, section_va = patched()
        assert read_bytes(image, section_va, TABLE_BYTES) == bytes(SLOTS * SLOT_SIZE)

    def test_the_section_name_survives_the_eight_byte_pe_field(self):
        assert len(SECTION_NAME) <= 8

    def test_refuses_to_apply_twice(self):
        image, _ = patched()
        with pytest.raises(ValueError, match="already names"):
            AiFarmKillGatePatch().apply(image)

    @pytest.mark.parametrize("anchor", sorted(ANCHORS))
    def test_refuses_a_build_where_an_anchor_moved(self, anchor):
        image = ai_farm_kill_gate_image()
        image[va_to_offset(image, anchor)] ^= 0xFF
        with pytest.raises(ValueError, match="farm raid tactic is not this build's"):
            AiFarmKillGatePatch().apply(image)

    def test_refuses_a_vtable_slot_that_dispatches_elsewhere(self):
        image = ai_farm_kill_gate_image()
        off = va_to_offset(image, AI_FARM_KILL_SQUAD_VTABLE + AI_FARM_KILL_SQUAD_BUILD_SLOT)
        struct.pack_into("<I", image, off, AI_FARM_KILL_SQUAD_BUILD + 1)
        with pytest.raises(ValueError):
            AiFarmKillGatePatch().apply(image)

    def test_refuses_an_unmapped_build(self):
        with pytest.raises(ValueError, match="not mapped"):
            AiFarmKillGatePatch().apply(bytearray(b"MZ" + b"\x00" * 0x400))


class TestVerify:
    def test_rejects_an_unpatched_file(self):
        problems = AiFarmKillGatePatch().verify(ai_farm_kill_gate_image())
        assert problems == [f"no {SECTION_NAME} section: the file does not carry this patch"]

    def test_rejects_a_cave_whose_code_was_altered(self):
        image, section_va = patched()
        image[va_to_offset(image, section_va) + TABLE_BYTES] ^= 0xFF
        problems = AiFarmKillGatePatch().verify(image)
        assert problems == [f"the {SECTION_NAME} cave does not hold the expected code"]

    def test_rejects_a_slot_put_back_to_stock(self):
        image, _ = patched()
        off = va_to_offset(image, AI_FARM_KILL_SQUAD_VTABLE + AI_FARM_KILL_SQUAD_RESET_SLOT)
        struct.pack_into("<I", image, off, AI_FARM_KILL_SQUAD_RESET)
        assert any("reset" in problem for problem in AiFarmKillGatePatch().verify(image))

    def test_rejects_a_member_table_that_lost_a_row(self):
        image, _ = patched()
        table = dword(image, ARMY_MEMBER_DEFINITION_FIELD_TABLE_REFS[0] + 1)
        last = table + (len(read_field_table(image, table)) - 1) * ROW_SIZE
        struct.pack_into("<IIII", image, va_to_offset(image, last), 0, 0, 0, 0)
        problems = AiFarmKillGatePatch().verify(image)
        assert problems == [
            f"the live ArmyMemberDefinition table has no {MEMBER_KEYWORDS[-1]} row of this patch's"
        ]

    def test_accepts_a_file_whose_faction_table_has_been_written(self):
        """The table is filled while the engine reads its INI, so a binary that has been run
        holds whatever that run left there."""
        image, section_va = patched()
        struct.pack_into("<II", image, va_to_offset(image, section_va), 0x1234, 1)
        assert AiFarmKillGatePatch().verify(image) == []

    def test_accepts_a_row_another_patch_repointed(self):
        """Rows copied from the live table are not this patch's to check: `ai-hero-build-delay`
        repoints `HeroBuildOrder` in whatever table is live."""
        image, section_va = patched()
        table = layout(section_va).army_table
        row = ARMY_DEFINITION_STAND_IN_ROWS.index("HeroBuildOrder")
        struct.pack_into("<I", image, va_to_offset(image, table + row * ROW_SIZE + 4), 0xF00)
        assert AiFarmKillGatePatch().verify(image) == []
