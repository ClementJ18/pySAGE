"""Tests for `mod-load-order`, which mounts `-mod` before the first INI file is read.

The cave is hand-assembled x86 that cannot be executed here, so the tests that matter disassemble
it back and assert it says what it was meant to say. Four things can go wrong and none of them
raises on its own.

The first is **order inside the cave**. It has to publish `TheWritableGlobalData` before it parses,
because the `-mod` handler is a silent no-op while that global is null, and it has to parse before
it mounts, because the parse is what fills the two path fields the mount reads. Either inversion
produces a patch that applies, verifies, and mounts nothing.

The second is the **registers**. `GameEngine::init` carries `ebx = 0` as its zero register and
`edi = 1` as the load type it hands to every `INI::load` from this point on. A cave that returns
either one changed corrupts the loads it exists to fix.

The third is **the transcription**. The mount is copied out of
`COMMAND_LINE_PARSE_AND_MOUNT_MODS`, so it is checked against that function's own bytes rather than
against a second reading of them - instruction for instruction, with branch targets compared as
positions so the widened jumps cannot hide a dropped one.

The fourth is the **build fingerprint**. The patch rewrites two sites and reads ten windows it does
not rewrite, including one dword of `.rdata`; every one of them has to fail loudly on anything else.

`MOD_CALL` is checked here as something the patch must *not* touch: repointing it would strand the
extended switch table `headless` installs, and leaving it alone is what keeps the two composable.
"""

from __future__ import annotations

import struct

import pytest

from sage_patch.addresses import (
    ARCHIVE_FILE_SYSTEM,
    ASCII_STRING_IS_EMPTY,
    COMMAND_LINE_PARSE,
    COMMAND_LINE_STARTUP_TABLE,
    COMMAND_LINE_STARTUP_TABLE_COUNT,
    GLOBAL_DATA,
    MOD_MOUNT_DIRECTORY,
)
from sage_patch.patches.mod_load_order import (
    ANCHORS,
    EMPTY_STRING,
    GLOBAL_DATA_CALL,
    GLOBAL_DATA_CALL_ORIGINAL,
    GLOBAL_DATA_CALL_TARGET,
    MOD_CALL,
    MOD_CALL_ORIGINAL,
    MOD_CALL_TARGET,
    MOD_MOUNT_BLOCK,
    MOD_MOUNT_BLOCK_END,
    MOD_MOUNT_BLOCK_ORIGINAL,
    MOD_MOUNT_SKIP,
    SECTION_NAME,
    SITES,
    ModLoadOrderPatch,
    build_code,
)
from sage_patch.registry import PATCHES
from sage_patch.utils import find_section, va_to_offset

from .synthetic import mod_load_order_image

BASE = 0x00F00000

#: The two instructions the compiler scheduled into the middle of the stock mount that the cave
#: emits somewhere else: the *parse's* stack cleanup, which the cave emits with the parse, and the
#: empty-string register, which it sets up front. Both are asserted separately.
_HOISTED = (("add", "esp, 0xc"), ("mov", f"edi, {EMPTY_STRING:#x}"))


@pytest.fixture
def image() -> bytearray:
    return mod_load_order_image()


def _patched(image: bytearray) -> bytearray:
    data = bytearray(image)
    ModLoadOrderPatch().apply(data)
    return data


def disassemble(code: bytes, base: int):
    capstone = pytest.importorskip("capstone")
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    return list(md.disasm(code, base))


def cave(base: int = BASE):
    return disassemble(build_code(base), base)


def calls_to(insns, target: int):
    """The direct `call rel32` instructions in ``insns`` that reach ``target``.

    Filtered on the operand being an immediate, because the cave also dispatches through
    `TheArchiveFileSystem`'s vtable and an indirect operand is not an address."""
    return [
        i
        for i in insns
        if i.mnemonic == "call" and i.op_str.startswith("0x") and int(i.op_str, 16) == target
    ]


def shape(insns, end_va: int, drop=()):
    """``(mnemonic, operand)`` per instruction, with a branch's operand as its target's position.

    Comparing positions rather than addresses is what lets the cave's near jumps be checked against
    the stock block's short ones: the encodings differ and the displacements differ with them, but
    a jump that lands on a different instruction still shows up. ``end_va`` is one past the last
    instruction, so a branch that leaves the block reads as the position after it rather than
    raising."""
    keep = [i for i in insns if (i.mnemonic, i.op_str) not in drop]
    index = {i.address: n for n, i in enumerate(keep)}
    index[end_va] = len(keep)
    return [
        (i.mnemonic, index[int(i.op_str, 16)] if i.mnemonic.startswith("j") else i.op_str)
        for i in keep
    ]


def mount_region(base: int = BASE):
    """The cave's mount, from the empty-string register to the `pop ecx` that ends it."""
    insns = cave(base)
    start = next(n for n, i in enumerate(insns) if (i.mnemonic, i.op_str) == _HOISTED[1])
    end = next(n for n, i in enumerate(insns) if (i.mnemonic, i.op_str) == ("pop", "ecx"))
    return insns[start : end + 1]


class TestTheCave:
    def test_it_disassembles_cleanly_to_its_end(self):
        """Capstone stopping early means an invalid encoding, which would be a crash in-game."""
        assert sum(i.size for i in cave()) == len(build_code(BASE))

    def test_it_preserves_the_registers_game_engine_init_holds_live(self):
        """`ebx` is that function's zero register and `edi` is the INI load type it passes to
        every `INI::load` after this point, so a cave that returns either one changed corrupts the
        loads this patch exists to fix."""
        insns = cave()
        assert [(i.mnemonic, i.op_str) for i in insns[:3]] == [
            ("push", "ebx"),
            ("push", "esi"),
            ("push", "edi"),
        ]
        assert [(i.mnemonic, i.op_str) for i in insns[-4:-1]] == [
            ("pop", "edi"),
            ("pop", "esi"),
            ("pop", "ebx"),
        ]

    def test_it_reads_the_object_from_the_registrations_third_argument(self):
        """Three saved registers plus the return address put the call's third argument - the
        `GlobalData` the registration is about to install - at ``[esp+0x18]``."""
        insns = cave()
        assert (insns[3].mnemonic, insns[3].op_str) == ("mov", "eax, dword ptr [esp + 0x18]")

    def test_it_publishes_the_global_before_it_parses(self):
        """The `-mod` handler bails silently while `TheWritableGlobalData` is null, so a cave that
        parsed first would apply, verify and mount nothing at all."""
        insns = cave()
        publish = next(
            i
            for i in insns
            if i.mnemonic == "mov" and i.op_str == f"dword ptr [{GLOBAL_DATA:#x}], eax"
        )
        assert publish.address < calls_to(insns, COMMAND_LINE_PARSE)[0].address

    def test_it_parses_the_stock_table_before_it_mounts(self):
        """The parse is what fills the two `GlobalData` path fields the mount reads, and the table
        and its entry count are the stock ones - see the module docstring on `headless`."""
        insns = cave()
        table = next(i for i in insns if i.mnemonic == "mov" and i.op_str.startswith("ebx,"))
        assert int(table.op_str.split(", ")[1], 16) == COMMAND_LINE_STARTUP_TABLE
        parse = calls_to(insns, COMMAND_LINE_PARSE)[0]
        count = [i for i in insns if i.mnemonic == "push" and i.address < parse.address][-1]
        assert int(count.op_str, 16) == COMMAND_LINE_STARTUP_TABLE_COUNT
        assert parse.address < calls_to(insns, MOD_MOUNT_DIRECTORY)[0].address

    def test_it_takes_argc_and_argv_from_game_engine_inits_frame(self):
        """`ebp` still points at that frame inside the cave, and the stock call site fourteen bytes
        later reads the pair from the same two slots."""
        insns = cave()
        parse = calls_to(insns, COMMAND_LINE_PARSE)[0]
        pushes = [i.op_str for i in insns if i.mnemonic == "push" and i.address < parse.address]
        assert pushes[-3:] == ["dword ptr [ebp + 0xc]", "dword ptr [ebp + 8]", "0x10"]

    def test_it_skips_everything_when_the_object_is_null(self):
        """`test eax, eax` then a `je` past the parse and the mount, to the register restore - the
        same answer the stock path gives when the allocation failed."""
        insns = cave()
        test = next(i for i in insns if i.mnemonic == "test" and i.op_str == "eax, eax")
        skip = next(i for i in insns if i.mnemonic == "je" and i.address > test.address)
        target = int(skip.op_str, 16)
        assert calls_to(insns, MOD_MOUNT_DIRECTORY)[0].address < target, (
            "the je must jump over the mount, not into it"
        )
        assert target == insns[-4].address, "and land on the register restore"

    def test_it_ends_by_falling_into_the_registration(self):
        """A tail-jump, not a call: the return address and all seven arguments are still on the
        stack exactly as the `call` this replaced left them, so the registration returns to
        `GameEngine::init` on its own."""
        insns = cave()
        assert (insns[-1].mnemonic, int(insns[-1].op_str, 16)) == ("jmp", GLOBAL_DATA_CALL_TARGET)
        assert not [i for i in insns if i.mnemonic == "ret"]

    def test_every_other_branch_stays_inside_the_cave(self):
        """A displacement computed wrong would jump into arbitrary engine code. The tail-jump is
        the one deliberate exit."""
        code = build_code(BASE)
        lo, hi = BASE, BASE + len(code)
        for ins in cave():
            if not ins.mnemonic.startswith("j"):
                continue
            target = int(ins.op_str, 16)
            if target == GLOBAL_DATA_CALL_TARGET:
                continue
            assert lo <= target < hi, f"{ins.mnemonic} at {ins.address:#x} escapes"

    def test_it_relocates_with_its_section(self):
        a, b = build_code(BASE), build_code(BASE + 0x1000)
        assert a != b, "the calls out of the cave must be recomputed for its address"
        assert len(a) == len(b)


class TestTheMountIsATranscription:
    def test_it_matches_the_stock_block_instruction_for_instruction(self):
        """The mount is copied out of `COMMAND_LINE_PARSE_AND_MOUNT_MODS`, so it is checked against
        that function's own bytes. Two instructions are compared separately because the compiler
        scheduled them into the middle of the block and the cave emits them elsewhere: the parse's
        stack cleanup, and the empty-string register."""
        stock = disassemble(MOD_MOUNT_BLOCK_ORIGINAL, MOD_MOUNT_BLOCK)
        assert sum(i.size for i in stock) == len(MOD_MOUNT_BLOCK_ORIGINAL)
        region = mount_region()
        end = region[-1].address + region[-1].size
        assert shape(stock, MOD_MOUNT_BLOCK_END, _HOISTED) == shape(region, end, _HOISTED[1:])

    def test_the_hoisted_instructions_are_still_emitted(self):
        emitted = {(i.mnemonic, i.op_str) for i in cave()}
        for instruction in _HOISTED:
            assert instruction in emitted

    def test_it_asks_is_empty_once_per_path_field(self):
        """Both fields are guarded, the way the stock block guards them - an unguarded mount would
        hand the archive loader or the directory mount an empty string."""
        assert len(calls_to(mount_region(), ASCII_STRING_IS_EMPTY)) == 2

    def test_it_mounts_the_archive_and_the_directory_once_each(self):
        insns = mount_region()
        assert [i for i in insns if i.mnemonic == "call" and i.op_str == "dword ptr [edx + 0x14]"]
        assert [i for i in insns if i.op_str == f"ecx, dword ptr [{ARCHIVE_FILE_SYSTEM:#x}]"]
        assert len(calls_to(insns, MOD_MOUNT_DIRECTORY)) == 1


class TestApply:
    def test_apply_then_verify(self, image):
        data = _patched(image)
        assert ModLoadOrderPatch().verify(data) == []

    def test_an_unpatched_image_does_not_verify(self, image):
        assert ModLoadOrderPatch().verify(image)

    def test_detect_recognises_its_own_work(self, image):
        assert ModLoadOrderPatch.detect(_patched(image)) is not None
        assert ModLoadOrderPatch.detect(image) is None

    def test_the_hook_is_a_call_to_the_cave(self, image):
        """Five bytes for five: the stock instruction is itself a `call rel32`, so the site is an
        exact fit and nothing is padded."""
        data = _patched(image)
        section_va, _off, _vsize = find_section(data, SECTION_NAME)
        off = va_to_offset(data, GLOBAL_DATA_CALL)
        site = bytes(data[off : off + len(GLOBAL_DATA_CALL_ORIGINAL)])
        assert len(GLOBAL_DATA_CALL_ORIGINAL) == 5
        assert site[0] == 0xE8
        assert GLOBAL_DATA_CALL + 5 + struct.unpack_from("<i", site, 1)[0] == section_va

    def test_the_stock_mount_is_jumped_over(self, image):
        """To the instruction after the block, so the stock function still runs its own tail."""
        data = _patched(image)
        off = va_to_offset(data, MOD_MOUNT_BLOCK)
        site = bytes(data[off : off + len(MOD_MOUNT_SKIP)])
        assert site == MOD_MOUNT_SKIP
        assert site[3] == 0xE9
        assert MOD_MOUNT_BLOCK + 8 + struct.unpack_from("<i", site, 4)[0] == MOD_MOUNT_BLOCK_END

    def test_the_skip_keeps_the_parse_cleanup_the_block_carried(self, image):
        """The block's `add esp, 0x0c` is the *parse's*, scheduled into the middle of the mount.
        Jumping straight past it leaves `COMMAND_LINE_PARSE_AND_MOUNT_MODS` twelve bytes out of
        balance, so its epilogue pops the parse arguments as its saved registers and returns to
        `edi` - which `GameEngine::init` holds at 1. That is an access violation at `EIP = 1`
        seconds into startup, which is why the skip opens by performing the cleanup itself."""
        cleanup = bytes.fromhex("83c40c")
        # Where the stock block carries it: twelve bytes in, and nowhere else.
        assert MOD_MOUNT_BLOCK_ORIGINAL.index(cleanup) == 0x0C
        assert MOD_MOUNT_BLOCK_ORIGINAL.count(cleanup) == 1
        # And the skip performs it before jumping over the block that held it.
        assert MOD_MOUNT_SKIP.startswith(cleanup)

        data = _patched(image)
        off = va_to_offset(data, MOD_MOUNT_BLOCK)
        assert bytes(data[off : off + 3]) == cleanup

    def test_the_stock_command_line_call_is_left_alone(self, image):
        """Repointing it would strand the extended switch table `headless` installs. The switches
        are still parsed after `GameData.ini` by the stock function, which by then has nothing left
        to mount."""
        data = _patched(image)
        off = va_to_offset(data, MOD_CALL)
        assert bytes(data[off : off + len(MOD_CALL_ORIGINAL)]) == MOD_CALL_ORIGINAL

    def test_the_cave_holds_the_expected_code(self, image):
        data = _patched(image)
        section_va, off, _vsize = find_section(data, SECTION_NAME)
        code = build_code(section_va)
        assert bytes(data[off : off + len(code)]) == code

    def test_applying_twice_raises(self, image):
        data = _patched(image)
        with pytest.raises(ValueError):
            ModLoadOrderPatch().apply(data)


class TestTheBuildFingerprint:
    def test_the_two_calls_it_reasons_from_go_where_the_patch_says(self):
        """Derived from the stock displacements rather than written down, so this asserts the
        premise rather than restating it."""
        assert GLOBAL_DATA_CALL + 5 + struct.unpack("<i", GLOBAL_DATA_CALL_ORIGINAL[1:5])[0] == (
            GLOBAL_DATA_CALL_TARGET
        )
        assert MOD_CALL + 5 + struct.unpack("<i", MOD_CALL_ORIGINAL[1:5])[0] == MOD_CALL_TARGET

    @pytest.mark.parametrize("va", sorted({**SITES, **ANCHORS}), ids=lambda va: f"{va:#010x}")
    def test_one_wrong_byte_refuses_the_build(self, image, va):
        off = va_to_offset(image, va)
        image[off] ^= 0xFF
        with pytest.raises(ValueError):
            ModLoadOrderPatch().apply(image)

    def test_the_mount_block_ends_where_the_jump_lands(self):
        assert MOD_MOUNT_BLOCK + len(MOD_MOUNT_BLOCK_ORIGINAL) == MOD_MOUNT_BLOCK_END


class TestTheRegistry:
    def test_it_is_registered_and_is_not_experimental(self):
        """The module lives outside `experimental/`, so the attribute has to agree - the two are
        the same fact, and `TestExperimentalPatchesAreDeclared` fails on either mismatch."""
        assert PATCHES["mod-load-order"] is ModLoadOrderPatch
        assert not ModLoadOrderPatch.experimental

    def test_it_takes_no_parameters(self):
        assert ModLoadOrderPatch().options() == {}
