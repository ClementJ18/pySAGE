"""Tests for the passive-aura-revive patch.

Neither half assembles anything hard, so what needs proving is not that the bytes decode but that
each dead arm returns the **right** value.

For `PassiveAreaEffectBehavior` that is a displacement: `[esp+0x10]` has to be the same slot the
update's normal return reads, or the dead arm hands the scheduler a sleep made of whatever the
frame happens to hold. For `AttributeModifierAuraUpdate` it is a set of addresses: the cave has to
send `RunWhileDead = Yes` to the byte the stock gate fell through to, `No` to the computation every
other path returns, and a structure that is still going up to the same place - and it has to leave
the sentinel alone, because the module's other reader of it is an aura correctly waiting on its
`TriggeredBy` upgrade. The construction gate is transcribed from the passive module rather than
invented, so it is checked against that module's own stock bytes.

Both are checked against instructions decoded out of the stand-in rather than against numbers
written down here.
"""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

from sage_ini.engine import STOCK
from sage_patch.addresses import (
    ATTRIBUTE_MODIFIER_AURA_ANCHORS,
    ATTRIBUTE_MODIFIER_AURA_DEAD_SLEEP,
    ATTRIBUTE_MODIFIER_AURA_DEAD_SLEEP_BYTES,
    ATTRIBUTE_MODIFIER_AURA_GATES,
    ATTRIBUTE_MODIFIER_AURA_GATES_BYTES,
    ATTRIBUTE_MODIFIER_AURA_MODULE_NAME_STRING,
    ATTRIBUTE_MODIFIER_AURA_NORMAL_SLEEP,
    ATTRIBUTE_MODIFIER_AURA_RUN_WHILE_DEAD_OFFSET,
    ATTRIBUTE_MODIFIER_AURA_SCAN,
    ATTRIBUTE_MODIFIER_AURA_THIS_EBP_OFFSET,
    ATTRIBUTE_MODIFIER_AURA_UPDATE,
    ATTRIBUTE_MODIFIER_AURA_UPDATE_VTABLE,
    OBJECT_GET_GETTING_BUILT_BEHAVIOR,
    OBJECT_TEST_STATUS,
    PASSIVE_AREA_EFFECT_ANCHORS,
    PASSIVE_AREA_EFFECT_CONSTRUCTION_FALLBACK,
    PASSIVE_AREA_EFFECT_CONSTRUCTION_GATE,
    PASSIVE_AREA_EFFECT_DEAD_SLEEP,
    PASSIVE_AREA_EFFECT_DEAD_SLEEP_BYTES,
    PASSIVE_AREA_EFFECT_MODULE_NAME_STRING,
    PASSIVE_AREA_EFFECT_PING_SLOT_OFFSET,
    PASSIVE_AREA_EFFECT_UPDATE,
    PASSIVE_AREA_EFFECT_UPDATE_VTABLE,
)
from sage_patch.patches.passive_aura_revive import (
    GATE_JUMP_PADDING,
    PATCHED_BYTES,
    SECTION_NAME,
    PassiveAuraRevivePatch,
    build_code,
)
from sage_patch.registry import PATCHES
from sage_patch.utils import find_section, va_to_offset

from .synthetic import passive_aura_revive_image

#: The sleep-forever sentinel an `UpdateModule` returns to be scheduled never again.
SLEEP_FOREVER = 0x3FFFFFFF

#: The normal return at `0x00887EBE`, whose first instruction is the one the patch copies.
NORMAL_RETURN = 0x00887EBE

#: Where the cave lands in the stand-in, for the disassembly tests. `apply` allocates the real one
#: past the last section, and `verify` finds it by name.
CAVE_BASE = 0x00F00000

_GAME_DAT = Path(__file__).resolve().parents[2] / "game.dat"


def at(data: bytes | bytearray, va: int, count: int) -> bytes:
    off = va_to_offset(data, va)
    assert off is not None, f"0x{va:08x} is not mapped"
    return bytes(data[off : off + count])


def cstring(data: bytes | bytearray, va: int) -> str:
    off = va_to_offset(data, va)
    assert off is not None, f"0x{va:08x} is not mapped"
    return bytes(data[off : data.index(b"\x00", off)]).decode("ascii")


def disassemble(code: bytes, base: int):
    capstone = pytest.importorskip("capstone")
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    return list(md.disasm(code, base))


def applied() -> bytearray:
    data = passive_aura_revive_image()
    PassiveAuraRevivePatch().apply(data)
    return data


class TestThePassiveSiteItRewrites:
    def test_the_stock_bytes_are_the_sentinel(self):
        """Decoded rather than asserted as hex: the five bytes replaced really do load
        `UPDATE_SLEEP_FOREVER`, which is the whole reason the module is never scheduled again."""
        insn = disassemble(PASSIVE_AREA_EFFECT_DEAD_SLEEP_BYTES, PASSIVE_AREA_EFFECT_DEAD_SLEEP)[0]
        assert (insn.mnemonic, insn.op_str) == ("mov", f"eax, {SLEEP_FOREVER:#x}")

    def test_the_dead_test_falls_into_it(self):
        """The site is the dead arm and not some other return: the `test`/`je` pair anchored at
        `0x00887E5B` ends exactly where the rewritten instruction begins, and the `je` skips it."""
        test_va = 0x00887E5B
        code = PASSIVE_AREA_EFFECT_ANCHORS[test_va]
        assert test_va + len(code) == PASSIVE_AREA_EFFECT_DEAD_SLEEP
        dead_test, branch = disassemble(code, test_va)
        assert (dead_test.mnemonic, dead_test.op_str) == ("test", "byte ptr [ebx + 0x458], 1")
        assert branch.mnemonic == "je"
        assert int(branch.op_str, 16) > PASSIVE_AREA_EFFECT_DEAD_SLEEP

    def test_the_replacement_is_the_same_length(self):
        """A byte longer would eat the `jmp` that carries the value to the epilogue."""
        assert len(PATCHED_BYTES) == len(PASSIVE_AREA_EFFECT_DEAD_SLEEP_BYTES)


class TestThePassiveArmReturnsTheSleepTheOtherPathsDo:
    def test_the_replacement_reads_the_ping_slot(self):
        insn = disassemble(PATCHED_BYTES, PASSIVE_AREA_EFFECT_DEAD_SLEEP)[0]
        want = f"eax, dword ptr [esp + {PASSIVE_AREA_EFFECT_PING_SLOT_OFFSET:#x}]"
        assert (insn.mnemonic, insn.op_str) == ("mov", want)

    def test_it_is_the_slot_the_normal_return_reads(self):
        """**The assertion this half stands on.** The displacement is not written down twice: it is
        decoded out of the stock normal-return anchor, so a build where the update keeps its sleep
        somewhere else fails here rather than shipping a sleep made of stack garbage."""
        stock = disassemble(PASSIVE_AREA_EFFECT_ANCHORS[NORMAL_RETURN], NORMAL_RETURN)[0]
        patched = disassemble(PATCHED_BYTES, PASSIVE_AREA_EFFECT_DEAD_SLEEP)[0]
        assert (stock.mnemonic, stock.op_str) == (patched.mnemonic, patched.op_str)

    def test_the_slot_is_written_from_the_ping_delay(self):
        """The other end of the same slot: the store at the top of the update, from
        `ModuleData+0x10`, which is `PingDelay`."""
        read, _test, store = disassemble(PASSIVE_AREA_EFFECT_ANCHORS[0x00887E04], 0x00887E04)
        assert (read.mnemonic, read.op_str) == ("mov", "eax, dword ptr [edi + 0x10]")
        want = f"dword ptr [esp + {PASSIVE_AREA_EFFECT_PING_SLOT_OFFSET:#x}], eax"
        assert (store.mnemonic, store.op_str) == ("mov", want)

    def test_the_normal_return_pops_the_five_pushes(self):
        """What makes `[esp+0x10]` name the same slot at both sites: `esp` is where the prologue
        left it, so the epilogue's pops have to match the prologue's pushes."""
        insns = disassemble(PASSIVE_AREA_EFFECT_ANCHORS[NORMAL_RETURN], NORMAL_RETURN)
        assert [i.mnemonic for i in insns] == ["mov", "pop", "pop", "pop", "pop", "pop", "ret"]
        assert insns[-1].op_str == ""  # `ret`, not `ret n` - a __fastcall with no stack args

    def test_the_tail_is_a_nop_not_a_branch(self):
        """The five bytes are one instruction plus padding; the `jmp` behind them is stock and
        keeps its address."""
        assert [i.mnemonic for i in disassemble(PATCHED_BYTES, PASSIVE_AREA_EFFECT_DEAD_SLEEP)] == [
            "mov",
            "nop",
        ]


class TestTheAuraSiteItRewrites:
    def test_the_stock_block_is_the_dead_test_and_the_gate(self):
        """Decoded rather than asserted as hex. The twenty-four bytes are the dead test, the three
        instructions the cave has to re-emit before it can test anything, and the `RunWhileDead`
        compare - in that order."""
        insns = disassemble(ATTRIBUTE_MODIFIER_AURA_GATES_BYTES, ATTRIBUTE_MODIFIER_AURA_GATES)
        assert [i.mnemonic for i in insns] == ["test", "push", "mov", "mov", "je", "cmp", "je"]
        assert insns[0].op_str == "byte ptr [esi + 0x458], 1"
        assert insns[1].op_str == "edi"
        assert insns[2].op_str == "edi, dword ptr [ecx - 0xc]"
        assert insns[3].op_str == "dword ptr [ebp - 0x14], ecx"
        want = f"byte ptr [edi + {ATTRIBUTE_MODIFIER_AURA_RUN_WHILE_DEAD_OFFSET:#x}], bl"
        assert insns[5].op_str == want

    def test_the_gate_branches_to_the_sentinel(self):
        """What makes this the dead arm and not another compare: `RunWhileDead = No` goes to the
        `mov eax, 0x3fffffff` the patch is here to stop reaching."""
        insns = disassemble(ATTRIBUTE_MODIFIER_AURA_GATES_BYTES, ATTRIBUTE_MODIFIER_AURA_GATES)
        assert int(insns[-1].op_str, 16) == ATTRIBUTE_MODIFIER_AURA_DEAD_SLEEP
        sentinel = disassemble(
            ATTRIBUTE_MODIFIER_AURA_DEAD_SLEEP_BYTES, ATTRIBUTE_MODIFIER_AURA_DEAD_SLEEP
        )[0]
        assert (sentinel.mnemonic, sentinel.op_str) == ("mov", f"eax, {SLEEP_FOREVER:#x}")

    def test_the_live_arm_branches_to_the_scan(self):
        """The other stock exit the cave has to reproduce: not dead goes straight on to the scan."""
        insns = disassemble(ATTRIBUTE_MODIFIER_AURA_GATES_BYTES, ATTRIBUTE_MODIFIER_AURA_GATES)
        assert int(insns[4].op_str, 16) == ATTRIBUTE_MODIFIER_AURA_SCAN

    def test_the_scan_is_the_byte_after_the_block(self):
        """`RunWhileDead = Yes` falls through in the stock block, so the address the cave jumps to
        for that arm is derived, not chosen: it is the end of the bytes being replaced."""
        end = ATTRIBUTE_MODIFIER_AURA_GATES + len(ATTRIBUTE_MODIFIER_AURA_GATES_BYTES)
        assert end == ATTRIBUTE_MODIFIER_AURA_SCAN

    def test_the_hook_fits_the_block_exactly(self):
        """Five bytes of `jmp` and the rest padding: a byte more would cut into the next gate, a
        byte less would leave the tail of the `je` behind."""
        assert len(GATE_JUMP_PADDING) + 5 == len(ATTRIBUTE_MODIFIER_AURA_GATES_BYTES)
        assert set(GATE_JUMP_PADDING) == {0x90}

    def test_the_module_has_no_construction_gate_of_its_own(self):
        """Why the cave adds one. The stock block goes dead test -> `RunWhileDead` -> scan, with
        nothing between it and the scan that could ask whether the structure is finished."""
        insns = disassemble(ATTRIBUTE_MODIFIER_AURA_GATES_BYTES, ATTRIBUTE_MODIFIER_AURA_GATES)
        assert not [i for i in insns if i.mnemonic == "call"]


class TestTheAuraCave:
    def test_it_re_emits_the_displaced_instructions_first(self):
        """`edi` and `[ebp-0x14]` are set from `ecx` before anything is allowed to clobber it, and
        they are the same three instructions the stock block ran."""
        stock = disassemble(ATTRIBUTE_MODIFIER_AURA_GATES_BYTES, ATTRIBUTE_MODIFIER_AURA_GATES)
        cave = disassemble(build_code(CAVE_BASE), CAVE_BASE)
        assert [(i.mnemonic, i.op_str) for i in cave[:3]] == [
            (i.mnemonic, i.op_str) for i in stock[1:4]
        ]

    def test_it_tests_the_field_the_stock_gate_tests(self):
        """The offset is not written down twice: the cave's compare and the stock gate's compare
        are decoded and their memory operands matched, so a build with a different `ModuleData`
        layout fails here rather than gating on the wrong byte."""
        stock = disassemble(ATTRIBUTE_MODIFIER_AURA_GATES_BYTES, ATTRIBUTE_MODIFIER_AURA_GATES)[5]
        cave = next(i for i in disassemble(build_code(CAVE_BASE), CAVE_BASE) if i.mnemonic == "cmp")
        assert cave.op_str.split(",")[0] == stock.op_str.split(",")[0]
        assert cave.op_str.endswith(", 0")  # the immediate stands in for the stock zeroed `bl`

    def test_it_re_emits_the_dead_test(self):
        stock = disassemble(ATTRIBUTE_MODIFIER_AURA_GATES_BYTES, ATTRIBUTE_MODIFIER_AURA_GATES)[0]
        cave = [
            i
            for i in disassemble(build_code(CAVE_BASE), CAVE_BASE)
            if i.mnemonic == "test" and i.op_str.startswith("byte ptr")
        ]
        assert [(i.mnemonic, i.op_str) for i in cave] == [(stock.mnemonic, stock.op_str)]

    def test_it_calls_the_two_routines_the_passive_module_calls(self):
        """The construction gate is a transcription, so the addresses it calls are the ones the
        stock passive gate calls - decoded out of that module's own bytes, not written down here."""
        gate = disassemble(
            PASSIVE_AREA_EFFECT_ANCHORS[PASSIVE_AREA_EFFECT_CONSTRUCTION_GATE],
            PASSIVE_AREA_EFFECT_CONSTRUCTION_GATE,
        )
        fallback = disassemble(
            PASSIVE_AREA_EFFECT_ANCHORS[PASSIVE_AREA_EFFECT_CONSTRUCTION_FALLBACK],
            PASSIVE_AREA_EFFECT_CONSTRUCTION_FALLBACK,
        )
        stock_calls = {
            int(i.op_str, 16)
            for i in gate + fallback
            if i.mnemonic == "call" and "[" not in i.op_str
        }
        assert stock_calls == {OBJECT_GET_GETTING_BUILT_BEHAVIOR, OBJECT_TEST_STATUS}
        cave = disassemble(build_code(CAVE_BASE), CAVE_BASE)
        cave_calls = {
            int(i.op_str, 16) for i in cave if i.mnemonic == "call" and "[" not in i.op_str
        }
        assert cave_calls == stock_calls

    def test_it_calls_the_interface_slot_the_passive_module_calls(self):
        """The virtual call too: `isStillBuilding` is slot `+0x2c` of whatever
        `getGettingBuiltBehavior` hands back, in both."""
        gate = disassemble(
            PASSIVE_AREA_EFFECT_ANCHORS[PASSIVE_AREA_EFFECT_CONSTRUCTION_GATE],
            PASSIVE_AREA_EFFECT_CONSTRUCTION_GATE,
        )
        stock = next(i for i in gate if i.mnemonic == "call" and "[" in i.op_str)
        cave = next(
            i
            for i in disassemble(build_code(CAVE_BASE), CAVE_BASE)
            if i.mnemonic == "call" and "[" in i.op_str
        )
        assert cave.op_str == stock.op_str

    def test_a_structure_still_going_up_gets_the_ordinary_sleep(self):
        """The answer to the construction gate routes to the same place the dead arm does, so an
        aura resumes when the rebuild finishes rather than when it starts."""
        insns = disassemble(build_code(CAVE_BASE), CAVE_BASE)
        answer = next(i for i in insns if i.mnemonic == "test" and i.op_str == "al, al")
        branch = next(i for i in insns if i.address > answer.address and i.mnemonic == "jne")
        landing = next(i for i in insns if i.address == int(branch.op_str, 16))
        assert (landing.mnemonic, int(landing.op_str, 16)) == (
            "jmp",
            ATTRIBUTE_MODIFIER_AURA_NORMAL_SLEEP,
        )

    def test_run_while_dead_yes_goes_to_the_stock_scan(self):
        """The arm the patch must not change: an aura with `RunWhileDead = Yes` keeps being applied
        through the death, exactly as it is today."""
        insns = disassemble(build_code(CAVE_BASE), CAVE_BASE)
        compare = next(i for i in insns if i.mnemonic == "cmp")
        branch = next(i for i in insns if i.address > compare.address and i.mnemonic == "jne")
        landing = [i for i in insns if i.address >= int(branch.op_str, 16)][:2]
        assert (landing[-1].mnemonic, int(landing[-1].op_str, 16)) == (
            "jmp",
            ATTRIBUTE_MODIFIER_AURA_SCAN,
        )

    def test_the_scan_arm_puts_this_back_in_ecx(self):
        """**The crash this patch shipped with.** `0x0089F469` does `add ecx, 0x10` /
        `mov eax, [ecx]` / `call [eax]` off the `ecx` the `__thiscall` prologue left, because stock
        nothing between the gate and there touches it. The cave calls out twice before jumping
        there, and a `__thiscall` callee leaves *its own* `this` in `ecx` - so without this reload
        the update calls through `[GettingBuiltBehavior+0x10]`, which is zero, and the game dies on
        the first finished structure carrying an aura.

        The slot is the update's own, written by the displaced `mov` at the top of the cave and read
        back by stock code at `0x0089F4A0`.
        """
        insns = disassemble(build_code(CAVE_BASE), CAVE_BASE)
        jump = next(
            i
            for i in insns
            if i.mnemonic == "jmp"
            and i.op_str.startswith("0x")
            and int(i.op_str, 16) == ATTRIBUTE_MODIFIER_AURA_SCAN
        )
        before = [i for i in insns if i.address < jump.address][-1]
        assert before.mnemonic == "mov"
        assert (
            before.op_str
            == f"ecx, dword ptr [ebp - {hex(-ATTRIBUTE_MODIFIER_AURA_THIS_EBP_OFFSET)}]"
        )
        # And it is the same slot the displaced store writes, not a second scratch dword.
        store = next(
            i
            for i in insns
            if i.mnemonic == "mov" and i.op_str.endswith(", ecx") and i.op_str.startswith("dword")
        )
        assert store.address < jump.address
        assert (
            store.op_str.split(",")[0].strip()
            == f"dword ptr [ebp - {hex(-ATTRIBUTE_MODIFIER_AURA_THIS_EBP_OFFSET)}]"
        )

    def test_only_the_scan_arm_reloads_it(self):
        """The sleep exit reloads `ecx` itself on the way into the epilogue, so a second reload in
        front of it would be dead weight a later reader would have to explain away."""
        insns = disassemble(build_code(CAVE_BASE), CAVE_BASE)
        reloads = [
            i for i in insns if i.mnemonic == "mov" and i.op_str.startswith("ecx, dword ptr")
        ]
        assert len(reloads) == 1

    def test_run_while_dead_no_goes_to_the_ordinary_sleep(self):
        """**The assertion this half stands on.** The arm that today parks at the sentinel returns
        the sleep every other path returns, by falling through the `RunWhileDead` compare."""
        insns = disassemble(build_code(CAVE_BASE), CAVE_BASE)
        compare = next(i for i in insns if i.mnemonic == "cmp")
        after = [i for i in insns if i.address > compare.address]
        fallthrough = after[1]  # the jne, then the arm the compare falls into
        assert fallthrough.mnemonic == "jmp"
        assert int(fallthrough.op_str, 16) == ATTRIBUTE_MODIFIER_AURA_NORMAL_SLEEP

    def test_the_sleep_it_jumps_to_is_refresh_delay_plus_a_stagger(self):
        """What that address holds, decoded: the object's id modulo five plus
        `ModuleData+0x18`. A build whose exit computed something else - or kept its sleep in a slot
        the way the passive module does - fails here rather than returning a wrong frame count."""
        insns = disassemble(
            ATTRIBUTE_MODIFIER_AURA_ANCHORS[ATTRIBUTE_MODIFIER_AURA_NORMAL_SLEEP],
            ATTRIBUTE_MODIFIER_AURA_NORMAL_SLEEP,
        )
        assert [i.mnemonic for i in insns] == [
            "mov",
            "cdq",
            "push",
            "pop",
            "idiv",
            "mov",
            "add",
        ]
        assert insns[0].op_str == "eax, dword ptr [esi + 0x74]"
        assert insns[-1].op_str == "eax, dword ptr [edi + 0x18]"

    def test_it_never_falls_off_the_end(self):
        """Every arm is a jump, so the cave cannot run into whatever the next patch appends."""
        insns = disassemble(build_code(CAVE_BASE), CAVE_BASE)
        assert insns[-1].mnemonic == "jmp"
        assert sum(len(i.bytes) for i in insns) == len(build_code(CAVE_BASE))

    def test_it_relocates_with_its_section(self):
        a, b = build_code(CAVE_BASE), build_code(CAVE_BASE + 0x1000)
        assert a != b, "the absolute jumps and calls must be recomputed for the cave's address"
        assert len(a) == len(b)


class TestApply:
    def test_apply_then_verify(self):
        assert PassiveAuraRevivePatch().verify(applied()) == []

    def test_a_stock_image_does_not_verify(self):
        assert PassiveAuraRevivePatch().verify(passive_aura_revive_image())

    def test_it_writes_the_patched_bytes_at_the_passive_site(self):
        data = applied()
        off = va_to_offset(data, PASSIVE_AREA_EFFECT_DEAD_SLEEP)
        assert off is not None
        assert bytes(data[off : off + len(PATCHED_BYTES)]) == PATCHED_BYTES

    def test_the_gate_becomes_a_jmp_to_the_cave_then_padding(self):
        data = applied()
        located = find_section(data, SECTION_NAME)
        assert located is not None
        section_va, _off, _vsize = located
        off = va_to_offset(data, ATTRIBUTE_MODIFIER_AURA_GATES)
        assert off is not None
        site = bytes(data[off : off + len(ATTRIBUTE_MODIFIER_AURA_GATES_BYTES)])
        assert site[0] == 0xE9
        target = ATTRIBUTE_MODIFIER_AURA_GATES + 5 + struct.unpack_from("<i", site, 1)[0]
        assert target == section_va
        assert site[5:] == GATE_JUMP_PADDING

    def test_the_cave_holds_the_gate(self):
        data = applied()
        located = find_section(data, SECTION_NAME)
        assert located is not None
        section_va, section_off, _vsize = located
        code = build_code(section_va)
        assert bytes(data[section_off : section_off + len(code)]) == code

    def test_the_sentinel_is_left_stock(self):
        """The un-triggered arm still needs it: an aura waiting on its `TriggeredBy` upgrade is
        supposed to sleep forever, and is woken by `giveSelfUpgrade` rather than by a poll."""
        data = applied()
        off = va_to_offset(data, ATTRIBUTE_MODIFIER_AURA_DEAD_SLEEP)
        assert off is not None
        got = bytes(data[off : off + len(ATTRIBUTE_MODIFIER_AURA_DEAD_SLEEP_BYTES)])
        assert got == ATTRIBUTE_MODIFIER_AURA_DEAD_SLEEP_BYTES

    def test_it_touches_no_engine_bytes_but_the_two_sites(self):
        """Two windows and a new section - nothing else in any section that already existed."""
        before = passive_aura_revive_image()
        data = applied()
        windows = []
        for va, length in (
            (PASSIVE_AREA_EFFECT_DEAD_SLEEP, len(PATCHED_BYTES)),
            (ATTRIBUTE_MODIFIER_AURA_GATES, len(ATTRIBUTE_MODIFIER_AURA_GATES_BYTES)),
        ):
            off = va_to_offset(before, va)
            assert off is not None
            windows += list(range(off, off + length))
        headers = struct.unpack_from("<I", before, 0x3C)[0] + 0x400
        changed = {i for i in range(len(before)) if before[i] != data[i] and i >= headers}
        # A subset rather than an equality: a `jmp` displacement byte that happens to match the
        # stock byte under it does not show up as changed, and that is not a defect.
        assert changed <= set(windows)
        assert changed, "neither site was written"

    def test_refuses_to_apply_twice(self):
        data = applied()
        with pytest.raises(ValueError):
            PassiveAuraRevivePatch().apply(data)

    def test_an_unmapped_site_verifies_as_a_problem_rather_than_raising(self):
        """`detect` sweeps arbitrary binaries, so `verify` answers rather than throws."""
        assert PassiveAuraRevivePatch().verify(bytearray(0x400))

    def test_the_section_name_survives_the_eight_byte_pe_field(self):
        assert len(SECTION_NAME) <= 8, "a longer name is silently truncated in the header"
        assert find_section(applied(), SECTION_NAME) is not None


class TestTheFunctionsAreTheRightOnes:
    @pytest.mark.parametrize(
        ("vtable", "update", "name_string", "module"),
        [
            (
                PASSIVE_AREA_EFFECT_UPDATE_VTABLE,
                PASSIVE_AREA_EFFECT_UPDATE,
                PASSIVE_AREA_EFFECT_MODULE_NAME_STRING,
                b"PassiveAreaEffectBehavior\x00",
            ),
            (
                ATTRIBUTE_MODIFIER_AURA_UPDATE_VTABLE,
                ATTRIBUTE_MODIFIER_AURA_UPDATE,
                ATTRIBUTE_MODIFIER_AURA_MODULE_NAME_STRING,
                b"AttributeModifierAuraUpdate\x00",
            ),
        ],
        ids=["passive", "aura"],
    )
    def test_the_vtable_slot_and_the_name_string_agree(self, vtable, update, name_string, module):
        anchors = {**PASSIVE_AREA_EFFECT_ANCHORS, **ATTRIBUTE_MODIFIER_AURA_ANCHORS}
        assert int.from_bytes(anchors[vtable], "little") == update
        assert anchors[name_string] == module

    @pytest.mark.parametrize(
        ("get_module_name", "name_string"),
        [
            (0x00887D63, PASSIVE_AREA_EFFECT_MODULE_NAME_STRING),
            (0x0089EDD2, ATTRIBUTE_MODIFIER_AURA_MODULE_NAME_STRING),
        ],
        ids=["passive", "aura"],
    )
    def test_get_module_name_returns_that_string(self, get_module_name, name_string):
        """`mov eax, <the string> ; ret` - what ties each vtable to its module by name."""
        anchors = {**PASSIVE_AREA_EFFECT_ANCHORS, **ATTRIBUTE_MODIFIER_AURA_ANCHORS}
        load, ret = disassemble(anchors[get_module_name], get_module_name)
        assert (load.mnemonic, load.op_str) == ("mov", f"eax, {name_string:#x}")
        assert ret.mnemonic == "ret"

    @pytest.mark.parametrize(
        ("ctor_site", "vtable"),
        [
            (0x00887D2E, PASSIVE_AREA_EFFECT_UPDATE_VTABLE),
            (0x0089ED9B, ATTRIBUTE_MODIFIER_AURA_UPDATE_VTABLE),
        ],
        ids=["passive", "aura"],
    )
    def test_the_constructor_installs_that_vtable(self, ctor_site, vtable):
        """`mov dword [esi+0x10], <the update vtable>` - the sub-object whose slot 0 is patched
        belongs to this module and not to whatever else shares the page."""
        anchors = {**PASSIVE_AREA_EFFECT_ANCHORS, **ATTRIBUTE_MODIFIER_AURA_ANCHORS}
        insn = disassemble(anchors[ctor_site], ctor_site)[0]
        assert (insn.mnemonic, insn.op_str) == ("mov", f"dword ptr [esi + 0x10], {vtable:#x}")


class TestTheAnchors:
    ALL = {**PASSIVE_AREA_EFFECT_ANCHORS, **ATTRIBUTE_MODIFIER_AURA_ANCHORS}

    @pytest.mark.parametrize("va", sorted(ALL), ids=lambda va: f"{va:#x}")
    def test_a_moved_anchor_refuses_to_apply(self, va: int):
        data = passive_aura_revive_image()
        off = va_to_offset(data, va)
        assert off is not None
        data[off] ^= 0xFF
        with pytest.raises(ValueError):
            PassiveAuraRevivePatch().apply(data)

    @pytest.mark.parametrize(
        ("site", "stock"),
        [
            (PASSIVE_AREA_EFFECT_DEAD_SLEEP, PASSIVE_AREA_EFFECT_DEAD_SLEEP_BYTES),
            (ATTRIBUTE_MODIFIER_AURA_GATES, ATTRIBUTE_MODIFIER_AURA_GATES_BYTES),
        ],
        ids=["passive", "aura"],
    )
    def test_a_moved_anchor_leaves_both_sites_stock(self, site: int, stock: bytes):
        """The check runs before any write, so a refused build is not half-patched - which matters
        more now that the patch has two sites and a section to add."""
        data = passive_aura_revive_image()
        off = va_to_offset(data, PASSIVE_AREA_EFFECT_MODULE_NAME_STRING)
        assert off is not None
        data[off] ^= 0xFF
        with pytest.raises(ValueError):
            PassiveAuraRevivePatch().apply(data)
        assert find_section(data, SECTION_NAME) is None
        at = va_to_offset(data, site)
        assert at is not None
        assert bytes(data[at : at + len(stock)]) == stock


class TestRegistration:
    def test_it_is_offered_on_the_cli(self):
        assert PATCHES[PassiveAuraRevivePatch.name] is PassiveAuraRevivePatch

    def test_detect_finds_it_only_once_applied(self):
        assert PassiveAuraRevivePatch.detect(passive_aura_revive_image()) is None
        assert PassiveAuraRevivePatch.detect(applied()) is not None

    def test_it_takes_no_parameters(self):
        assert PassiveAuraRevivePatch().options() == {}

    def test_it_declares_no_ini_surface(self):
        """The promise the description makes: a mod writes exactly what it already writes."""
        assert PassiveAuraRevivePatch().ini_surface() == STOCK

    def test_the_description_promises_the_aura_stays_off_while_dead(self):
        """The half a reader has to be told, because the patch's name says only the other half."""
        assert "still inactive while the object is dead" in PassiveAuraRevivePatch.description


@pytest.mark.skipif(not _GAME_DAT.exists(), reason="needs the real game.dat")
class TestInstalledBinary:
    """Against the real binary, which is the only thing that can say the addresses are right.

    The stand-in is built from this patch's own anchor tables, so it round-trips whatever those
    tables say. Only the shipped `game.dat` can confirm that `0x0089F451` is
    `AttributeModifierAuraUpdate`'s `RunWhileDead` gate rather than the middle of some other
    compare, and that the two addresses the cave jumps to are the instructions they claim to be.
    """

    @pytest.fixture(scope="class")
    def stock(self) -> bytes:
        return _GAME_DAT.read_bytes()

    def test_every_site_holds_its_stock_bytes(self, stock):
        sites = {
            PASSIVE_AREA_EFFECT_DEAD_SLEEP: PASSIVE_AREA_EFFECT_DEAD_SLEEP_BYTES,
            ATTRIBUTE_MODIFIER_AURA_GATES: ATTRIBUTE_MODIFIER_AURA_GATES_BYTES,
            **PASSIVE_AREA_EFFECT_ANCHORS,
            **ATTRIBUTE_MODIFIER_AURA_ANCHORS,
        }
        for va, expected in sites.items():
            assert at(stock, va, len(expected)) == expected, f"0x{va:08x}"

    @pytest.mark.parametrize(
        ("vtable", "update", "name_string", "module"),
        [
            (
                PASSIVE_AREA_EFFECT_UPDATE_VTABLE,
                PASSIVE_AREA_EFFECT_UPDATE,
                PASSIVE_AREA_EFFECT_MODULE_NAME_STRING,
                "PassiveAreaEffectBehavior",
            ),
            (
                ATTRIBUTE_MODIFIER_AURA_UPDATE_VTABLE,
                ATTRIBUTE_MODIFIER_AURA_UPDATE,
                ATTRIBUTE_MODIFIER_AURA_MODULE_NAME_STRING,
                "AttributeModifierAuraUpdate",
            ),
        ],
        ids=["passive", "aura"],
    )
    def test_the_vtable_dispatches_to_the_patched_update(
        self, stock, vtable, update, name_string, module
    ):
        """The claim the whole patch rests on, read out of the shipped image rather than out of its
        own tables: slot 0 of that vtable is that function, and the module it belongs to has that
        name."""
        assert struct.unpack("<I", at(stock, vtable, 4))[0] == update
        assert cstring(stock, name_string) == module

    def test_the_aura_gate_branches_to_the_sentinel_in_the_real_image(self, stock):
        """Decoded from the binary: the block really does end in a compare and a branch, and the
        branch really does land on the `mov eax, 0x3fffffff` this patch routes around."""
        insns = disassemble(
            at(stock, ATTRIBUTE_MODIFIER_AURA_GATES, len(ATTRIBUTE_MODIFIER_AURA_GATES_BYTES)),
            ATTRIBUTE_MODIFIER_AURA_GATES,
        )
        assert insns[5].mnemonic == "cmp"
        assert int(insns[6].op_str, 16) == ATTRIBUTE_MODIFIER_AURA_DEAD_SLEEP
        sentinel = disassemble(
            at(stock, ATTRIBUTE_MODIFIER_AURA_DEAD_SLEEP, 5), ATTRIBUTE_MODIFIER_AURA_DEAD_SLEEP
        )[0]
        assert (sentinel.mnemonic, sentinel.op_str) == ("mov", f"eax, {SLEEP_FOREVER:#x}")

    def test_the_normal_sleep_falls_into_the_epilogue(self, stock):
        """What makes the cave's jump safe: the computation it lands on runs straight into the
        function's own epilogue, so the patched arm returns and unwinds like every other one."""
        sleep = ATTRIBUTE_MODIFIER_AURA_ANCHORS[ATTRIBUTE_MODIFIER_AURA_NORMAL_SLEEP]
        insns = disassemble(
            at(stock, ATTRIBUTE_MODIFIER_AURA_NORMAL_SLEEP, len(sleep) + 15),
            ATTRIBUTE_MODIFIER_AURA_NORMAL_SLEEP,
        )
        epilogue = [
            i for i in insns if i.address >= ATTRIBUTE_MODIFIER_AURA_NORMAL_SLEEP + len(sleep)
        ]
        # `mov ecx, [ebp-0xc]`, the three pops matching the pushes above the patched gate, the
        # SEH-chain restore, and the return.
        assert [i.mnemonic for i in epilogue] == ["mov", "pop", "pop", "pop", "mov", "leave", "ret"]
        assert [i.op_str for i in epilogue[1:4]] == ["edi", "esi", "ebx"]
        assert epilogue[4].op_str.startswith("dword ptr fs:")

    def test_apply_and_verify_on_the_real_thing(self, stock):
        data = bytearray(stock)
        PassiveAuraRevivePatch().apply(data)
        assert PassiveAuraRevivePatch().verify(data) == []
        assert PassiveAuraRevivePatch.detect(data) is not None
