"""Tests for `multi-mod`, which honours every `-mod` rather than only the last.

The cave is hand-assembled x86 that cannot be executed here, so the tests that matter disassemble
it back and assert it says what it was meant to say. Five things can go wrong and none of them
raises on its own.

The first is the **calling convention of the recording stand-in**. It takes the place of
`AsciiString::operator=` at the end of the `-mod` handler, which is `__thiscall` returning `this`
and cleaning one argument with ``ret 4``. A stand-in that returns with a bare `ret`, or that
forgets to forward the assignment, leaves the handler's stack short or the `GlobalData` fields
empty - and an empty `m_modDir` is a game that mounts nothing at all.

The second is **which registers each block replacement may touch**. The four file-system blocks
are entered by a `call` from the middle of four different functions, each of which holds live
values the code after the block still uses: `sprintf` in `esi` or `edi`, the file name, the access
flags, the empty string. Each routine has to leave the answer in the register the continuation
reads and give back everything else, and none of that fails loudly.

The third is **the direction of the search**. Archives already stack last-mounted-first, so the
table has to be walked backwards or a file shipped loosely in one mod and packed in another
resolves differently depending on how it was shipped. Mounting runs forwards for the same reason.

The fourth is the **padding**. Each block is longer than the `call` that replaces it, and the
remainder is nop-padded out to exactly the block's length. Padding one byte short leaves a
truncated instruction; one byte long overwrites the continuation - which is why the byte *after*
each block is asserted not to be a `nop`.

The fifth is the **build fingerprint**. The patch rewrites five windows and reads nineteen it does
not, including a vtable dword, three CRT thunks and a format string in `.rdata`; every one of them
has to fail loudly on anything else.

`TestItComposesWithModLoadOrder` is the one class here that needs a second patch. The two are the
only ones that reach into the mod pipeline, and each one's own stand-in maps only its own sites -
so a collision between them would read as unmapped rather than as a conflict. It is checked on an
image that maps both.
"""

from __future__ import annotations

import itertools
import struct

import pytest

from sage_patch.addresses import (
    ARCHIVE_FILE_SYSTEM,
    ARCHIVE_FILE_SYSTEM_LOAD_ARCHIVE_SLOT,
    ASCII_STRING_ASSIGN,
    ASCII_STRING_SET,
    GLOBAL_DATA,
    GLOBAL_DATA_MOD_BIG,
    LOCAL_FILE_SYSTEM,
    LOCAL_FILE_SYSTEM_DOES_FILE_EXIST_SLOT,
    LOCAL_FILE_SYSTEM_GET_FILE_INFO_SLOT,
    LOCAL_FILE_SYSTEM_GET_FILE_LIST_SLOT,
    LOCAL_FILE_SYSTEM_OPEN_FILE_SLOT,
    MOD_DIRECTORY,
    MOD_MOUNT_DIRECTORY,
    MOD_PATH_FORMAT,
    SPRINTF_SLOT,
    STRCMPI,
    STRCPY,
    STRLEN,
)
from sage_patch.patches.experimental import mod_load_order as mlo
from sage_patch.patches.experimental import multi_mod as mm
from sage_patch.patches.experimental.mod_load_order import (
    MOD_MOUNT_BLOCK,
    MOD_MOUNT_BLOCK_ORIGINAL,
    ModLoadOrderPatch,
)
from sage_patch.patches.experimental.multi_mod import (
    ANCHORS,
    BLOCKS,
    COUNT_OFFSET,
    ENTRIES_OFFSET,
    ENTRY_STRIDE,
    KIND_ARCHIVE,
    MAX_MODS,
    MOD_HANDLER_STORE,
    MOD_HANDLER_STORE_ORIGINAL,
    MOD_HANDLER_STORE_TARGET,
    PATH_SIZE,
    SECTION_NAME,
    SITES,
    TABLE_SIZE,
    MultiModPatch,
    build_code,
    entry_points,
    table_va,
)
from sage_patch.registry import PATCHES
from sage_patch.utils import find_section, va_to_offset

from .synthetic import multi_mod_and_mod_load_order_image, multi_mod_image

BASE = 0x00F00000

#: Every routine in the cave, hooked or internal, so that one can be sliced out of the whole by
#: address. `entry_points` deliberately reports only the five the engine is pointed at - that is
#: the surface `apply` installs - so the rest are found through the layout's own labels.
_ROUTINES = (
    "record",
    "add_mod",
    "mod_directory",
    "open_file",
    "does_file_exist",
    "get_file_info",
    "get_file_list",
    "list_directory_chars",
)

#: Each block replacement, with the registers the code after its block still uses. Read off the
#: four containing functions' prologues and continuations, not off the routines themselves - the
#: point is to check the cave against the engine rather than against a second reading of itself.
_PRESERVED = {
    "open_file": ("ebx", "edi"),
    "does_file_exist": ("esi", "edi"),
    "get_file_info": ("ebx", "esi", "edi"),
    "get_file_list": ("esi", "edi"),
}


@pytest.fixture
def image() -> bytearray:
    return multi_mod_image()


def _patched(image: bytearray) -> bytearray:
    data = bytearray(image)
    MultiModPatch().apply(data)
    return data


def disassemble(code: bytes, base: int):
    capstone = pytest.importorskip("capstone")
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    return list(md.disasm(code, base))


def cave(base: int = BASE):
    """The section's code half, disassembled. The table leads the section and is not code."""
    return disassemble(build_code(base)[TABLE_SIZE:], base + TABLE_SIZE)


def address_of(name: str, base: int = BASE) -> int:
    return mm._layout(base).label_va(name)


def routine(name: str, base: int = BASE):
    """One cave routine: from its label to the next routine's, or to the end of the cave.

    Sliced by address rather than by counting instructions, so a routine that grows does not
    silently take the next one's assertions with it."""
    start = address_of(name, base)
    later = [va for va in (address_of(other, base) for other in _ROUTINES) if va > start]
    end = min(later) if later else base + len(build_code(base))
    return [i for i in cave(base) if start <= i.address < end]


def text(name: str, base: int = BASE):
    return [(i.mnemonic, i.op_str) for i in routine(name, base)]


def calls_to(insns, target: int):
    """The direct `call rel32` instructions in ``insns`` that reach ``target``.

    Filtered on the operand being an immediate, because the cave also dispatches through two
    vtables and an import slot, and an indirect operand is not an address."""
    return [
        i
        for i in insns
        if i.mnemonic == "call" and i.op_str.startswith("0x") and int(i.op_str, 16) == target
    ]


def writes(insns, register: str) -> bool:
    """Whether any instruction has ``register`` as its destination operand.

    Crude on purpose - it reads the first operand and nothing else - which makes it conservative:
    a routine that passes has not written the register anywhere obvious, and the push/pop pairing
    is asserted separately."""
    return any(i.op_str.split(",")[0].strip() == register for i in insns if i.mnemonic != "push")


class TestTheCave:
    def test_it_disassembles_cleanly_to_its_end(self):
        """Capstone stopping early means an invalid encoding, which would be a crash in-game."""
        assert sum(i.size for i in cave()) == len(build_code(BASE)) - TABLE_SIZE

    def test_the_table_leads_the_section_and_starts_zeroed(self):
        """The routines address the table absolutely, so its address has to be known before the
        code is laid out - which is what putting it first buys. It starts empty because the count
        is what every loop reads first."""
        assert table_va(BASE) == BASE
        assert build_code(BASE)[:TABLE_SIZE] == bytes(TABLE_SIZE)
        assert TABLE_SIZE == ENTRIES_OFFSET + MAX_MODS * ENTRY_STRIDE
        assert ENTRY_STRIDE == 4 + PATH_SIZE

    def test_every_branch_stays_inside_the_cave(self):
        """A displacement computed against the wrong base lands in engine code that happens to be
        mapped, which is a crash somewhere else entirely."""
        span = range(BASE + TABLE_SIZE, BASE + len(build_code(BASE)))
        strayed = [
            i for i in cave() if i.mnemonic.startswith("j") and int(i.op_str, 16) not in span
        ]
        assert strayed == []

    def test_no_routine_falls_through_into_the_next(self):
        """Each is entered by its own `call` and has to end on one, so a routine whose last
        instruction is not a return has run off into its neighbour."""
        for name in _ROUTINES:
            assert routine(name)[-1].mnemonic == "ret", name

    def test_it_relocates_with_its_section(self):
        """The cave is allocated past whatever sections are already there, so its own address is
        not knowable until apply time and every reference to itself has to move with it."""
        assert build_code(BASE) != build_code(BASE + 0x1000)
        assert len(build_code(BASE)) == len(build_code(BASE + 0x1000))


class TestTheRecordingStandIn:
    def test_it_forwards_the_assignment_before_it_records(self):
        """The `GlobalData` fields have to end up holding exactly what they held before, because
        the stock mount is left alone and still reads them - and the recording reads them too."""
        insns = routine("record")
        assert len(calls_to(insns, ASCII_STRING_ASSIGN)) == 1
        assigned = next(n for n, i in enumerate(insns) if calls_to([i], ASCII_STRING_ASSIGN))
        recorded = next(n for n, i in enumerate(insns) if i.mnemonic == "call" and n > assigned)
        assert assigned < recorded

    def test_it_forwards_the_source_string(self):
        """`[esp+8]` after one `push`, which is the caller's `[esp+4]` - the one argument."""
        assert ("push", "dword ptr [esp + 8]") in text("record")

    def test_it_returns_this_and_cleans_one_argument(self):
        """What `AsciiString::operator=` does, and so what the handler is written to call."""
        insns = routine("record")
        assert (insns[-1].mnemonic, insns[-1].op_str) == ("ret", "4")
        assert ("mov", "eax, ebx") in text("record")[-4:]

    def test_it_reads_the_path_out_of_the_destination_field(self):
        """Not the source: the destination is where the handler's finished absolute path lands,
        trailing separator and all, and it is also what says which kind of mod this was."""
        assert ("mov", "ebx, ecx") in text("record"), "the destination field is not captured"
        assert ("mov", "eax, dword ptr [ebx]") in text("record")

    def test_it_tags_the_archive_field_and_nothing_else(self):
        """`m_modBIG` is the only one of the two fields that means an archive, so the comparison
        has to be against that address and the tag has to be the flag the comparison sets."""
        assert ("mov", f"ecx, dword ptr [{GLOBAL_DATA:#x}]") in text("record")
        assert ("add", f"ecx, {GLOBAL_DATA_MOD_BIG:#x}") in text("record")
        assert ("cmp", "ebx, ecx") in text("record")
        assert ("sete", "dl") in text("record")
        assert KIND_ARCHIVE == 1, "sete produces 1, so the archive tag has to be 1"

    def test_it_records_nothing_for_an_empty_string(self):
        """Both halves of empty: no data block, and a data block whose first char is the
        terminator. The stock mount tests the same two things through `AsciiString::isEmpty`."""
        assert ("test", "eax, eax") in text("record")
        assert ("cmp", "byte ptr [eax], 0") in text("record")


class TestRecordingIsIdempotent:
    """`mod-load-order` makes the whole startup table parse twice, so the stand-in runs twice per
    switch. Appending or mounting on the second pass would double the table and remount every
    archive - and would do it silently, since both operations succeed."""

    def test_it_compares_case_insensitively_before_appending(self):
        assert len(calls_to(routine("add_mod"), STRCMPI)) == 1

    def test_it_mounts_only_on_the_append_path(self):
        """One directory mount, after the count has been advanced - so a path already found in the
        table has returned before either mount can run."""
        insns = routine("add_mod")
        mounts = [n for n, i in enumerate(insns) if calls_to([i], MOD_MOUNT_DIRECTORY)]
        appended = next(
            n for n, i in enumerate(insns) if i.mnemonic == "inc" and i.op_str.startswith("dword")
        )
        assert len(mounts) == 1
        assert mounts[0] > appended

    def test_it_bounds_both_the_table_and_the_path(self):
        """A seventeenth mod or an over-long path is dropped, not truncated: a truncated path
        names a directory that does not exist, which fails silently on every lookup after it."""
        assert ("cmp", f"eax, {PATH_SIZE:#x}") in text("add_mod")
        assert ("cmp", f"ecx, {MAX_MODS:#x}") in text("add_mod")
        assert len(calls_to(routine("add_mod"), STRLEN)) == 1
        assert len(calls_to(routine("add_mod"), STRCPY)) == 1

    def test_it_mounts_an_archive_through_the_load_slot_with_overwrite_set(self):
        """The flag is what makes several archives stack instead of the first one winning."""
        assert ("mov", f"ecx, dword ptr [{ARCHIVE_FILE_SYSTEM:#x}]") in text("add_mod")
        assert ("push", "1") in text("add_mod")
        slot = f"dword ptr [eax + {ARCHIVE_FILE_SYSTEM_LOAD_ARCHIVE_SLOT:#x}]"
        assert ("call", slot) in text("add_mod")


class TestTheSearchOrder:
    def test_it_walks_the_table_backwards(self):
        """Last `-mod` first, which is the order the archive file system already imposes. A
        forwards walk would make a file shipped loosely resolve to a different mod than the same
        file shipped packed."""
        assert ("dec", "ecx") in text("mod_directory")
        assert ("inc", "ecx") not in text("mod_directory")

    def test_it_skips_archive_entries(self):
        """They are in the table only so that mounting happens in command-line order; there is no
        loose tree to search under a `.big`."""
        assert ("cmp", "dword ptr [eax], 0") in text("mod_directory")

    def test_an_empty_table_falls_back_to_the_stock_global(self):
        """What makes a path this patch declined to record still get searched: with no directory
        recorded, index 0 answers `MOD_DIRECTORY` and every loop runs exactly one stock pass."""
        assert ("mov", f"eax, {MOD_DIRECTORY:#x}") in text("mod_directory")

    def test_it_reads_the_count_out_of_the_table(self):
        assert ("mov", f"ecx, dword ptr [{BASE + COUNT_OFFSET:#x}]") in text("mod_directory")

    def test_it_indexes_entries_by_the_declared_stride(self):
        assert ("imul", f"eax, ecx, {ENTRY_STRIDE:#x}") in text("mod_directory")
        assert ("add", f"eax, {BASE + ENTRIES_OFFSET:#x}") in text("mod_directory")


class TestTheBlockReplacements:
    """Each replacement stands between a guard and a continuation that were written for the block
    it replaces, so what it may clobber and where it leaves its answer are both fixed."""

    @pytest.mark.parametrize("name", sorted(_PRESERVED))
    def test_it_loops_over_the_table(self, name):
        """One `mod_directory` call, and a backward branch to retry - which is the whole
        difference from the block being replaced."""
        insns = routine(name)
        assert len(calls_to(insns, address_of("mod_directory"))) == 1
        backward = [
            i for i in insns if i.mnemonic.startswith("j") and int(i.op_str, 16) < i.address
        ]
        assert backward, f"{name} never retries - it is not a loop"

    @pytest.mark.parametrize("name", sorted(_PRESERVED))
    def test_its_prologue_and_epilogue_pair_up(self, name):
        insns = routine(name)
        prologue = list(itertools.takewhile(lambda i: i.mnemonic == "push", insns))
        epilogue = list(itertools.takewhile(lambda i: i.mnemonic == "pop", reversed(insns[:-1])))
        assert [i.op_str for i in epilogue] == [i.op_str for i in prologue]
        assert prologue, f"{name} saves nothing, yet it uses a register for its index"

    @pytest.mark.parametrize("name", sorted(_PRESERVED))
    def test_it_gives_back_the_registers_its_continuation_still_uses(self, name):
        """Everything the code after the block reads is either saved and restored or never
        written. `sprintf` is the one that bites: three of the four blocks are followed by a
        language lookup that calls it out of a register the block itself loaded."""
        insns = routine(name)
        saved = {i.op_str for i in insns if i.mnemonic == "push" and i.op_str.isalpha()}
        for register in _PRESERVED[name]:
            assert register in saved or not writes(insns, register), (
                f"{name} clobbers {register}, which its continuation still uses"
            )

    @pytest.mark.parametrize("name", sorted(_PRESERVED))
    def test_it_never_touches_ebp(self, name):
        """The buffer and every argument are the *calling* function's frame locals, reachable only
        because the routine is entered by a `call` and leaves the frame pointer alone."""
        assert not writes(routine(name), "ebp")

    @pytest.mark.parametrize("name", sorted(_PRESERVED))
    def test_it_formats_the_path_the_way_the_block_did(self, name):
        """The same format string and the same `sprintf`, so a mod path is built byte for byte the
        way it was - double separator included, since a recorded directory carries a trailing
        one."""
        assert ("push", f"{MOD_PATH_FORMAT:#x}") in text(name)
        assert ("call", f"dword ptr [{SPRINTF_SLOT:#x}]") in text(name)
        assert ("add", "esp, 0x10") in text(name)

    @pytest.mark.parametrize(
        ("name", "slot", "buffer"),
        [
            ("open_file", LOCAL_FILE_SYSTEM_OPEN_FILE_SLOT, "0x200"),
            ("does_file_exist", LOCAL_FILE_SYSTEM_DOES_FILE_EXIST_SLOT, "0x200"),
            ("get_file_info", LOCAL_FILE_SYSTEM_GET_FILE_INFO_SLOT, "0x104"),
            ("get_file_list", LOCAL_FILE_SYSTEM_GET_FILE_LIST_SLOT, "0x124"),
        ],
    )
    def test_it_calls_the_slot_its_block_called_with_its_block_s_buffer(self, name, slot, buffer):
        """The buffer differs per function, so getting it wrong writes past somebody's locals -
        and the slot is what the whole replacement is for."""
        insns = routine(name)
        assert ("mov", f"ecx, dword ptr [{LOCAL_FILE_SYSTEM:#x}]") in text(name)
        assert any(i.mnemonic == "lea" and i.op_str.endswith(f"[ebp - {buffer}]") for i in insns)
        assert any(i.mnemonic == "call" and i.op_str.endswith(f"+ {slot:#x}]") for i in insns)

    def test_open_file_resets_the_name_on_a_hit(self):
        """The `File` is opened under the mod's path and has to answer to the logical one, or a
        caller that reads the name back gets a path naming a particular mod."""
        assert len(calls_to(routine("open_file"), ASCII_STRING_SET)) == 1
        assert ("lea", "ecx, [esi + 4]") in text("open_file")

    def test_open_file_leaves_the_result_in_esi(self):
        assert ("mov", "esi, eax") in text("open_file")

    @pytest.mark.parametrize("name", ["does_file_exist", "get_file_info"])
    def test_the_predicates_answer_in_al(self, name):
        assert ("xor", "al, al") in text(name)
        assert ("mov", "al, 1") in text(name)

    def test_the_listing_never_stops_early(self):
        """It merges names into a set under their logical directory, so running it once per mod is
        what unions the trees. A success test would make them shadow one another instead - and the
        block it replaces has no such test either."""
        insns = routine("get_file_list")
        merged = next(
            n
            for n, i in enumerate(insns)
            if i.mnemonic == "call"
            and i.op_str.endswith(f"+ {LOCAL_FILE_SYSTEM_GET_FILE_LIST_SLOT:#x}]")
        )
        after = [(i.mnemonic, i.op_str) for i in insns[merged + 1 :]]
        assert after[:2] == [("inc", "edi"), ("jmp", f"{address_of('get_file_list') + 4:#x}")]

    def test_the_listing_substitutes_the_empty_string_for_a_missing_block(self):
        """Both `AsciiString` arguments may have no data block, and the block it replaces
        substitutes the engine's empty string for each. Passing a null would crash the merge."""
        assert text("get_file_list").count(("mov", f"eax, {mm.EMPTY_STRING:#x}")) == 1
        assert ("mov", f"eax, {mm.EMPTY_STRING:#x}") in text("list_directory_chars")
        assert ("push", f"{mm.EMPTY_STRING:#x}") in text("get_file_list")


class TestApply:
    def test_apply_then_verify(self, image):
        assert MultiModPatch().verify(_patched(image)) == []

    def test_an_unpatched_image_does_not_verify(self, image):
        assert MultiModPatch().verify(image)

    def test_detect_recognises_its_own_work(self, image):
        assert MultiModPatch.detect(_patched(image)) is not None
        assert MultiModPatch.detect(image) is None

    def test_the_store_hook_is_a_call_and_fits_exactly(self, image):
        """Five bytes for five: the stock instruction is itself a `call rel32`, so nothing pads."""
        data = _patched(image)
        routines = entry_points(find_section(data, SECTION_NAME)[0])
        off = va_to_offset(data, MOD_HANDLER_STORE)
        site = bytes(data[off : off + len(MOD_HANDLER_STORE_ORIGINAL)])
        assert len(MOD_HANDLER_STORE_ORIGINAL) == 5
        assert site[0] == 0xE8
        assert MOD_HANDLER_STORE + 5 + struct.unpack_from("<i", site, 1)[0] == routines["record"]

    @pytest.mark.parametrize("block", sorted(BLOCKS), ids=lambda va: f"{va:#010x}")
    def test_each_block_is_a_call_padded_to_its_own_length(self, image, block):
        """Short and the remainder of the stock block is left as a truncated instruction; long and
        the continuation is overwritten - which is what the last assertion is for, the byte after
        each block being the first of a continuation this patch must not have reached."""
        data = _patched(image)
        name, original = BLOCKS[block]
        routines = entry_points(find_section(data, SECTION_NAME)[0])
        off = va_to_offset(data, block)
        site = bytes(data[off : off + len(original)])
        assert site[0] == 0xE8
        assert block + 5 + struct.unpack_from("<i", site, 1)[0] == routines[name]
        assert site[5:] == b"\x90" * (len(original) - 5)
        assert data[off + len(original)] != 0x90

    def test_the_cave_holds_the_expected_code(self, image):
        data = _patched(image)
        section_va, off, _vsize = find_section(data, SECTION_NAME)
        code = build_code(section_va)
        assert bytes(data[off : off + len(code)]) == code

    def test_the_table_is_appended_zeroed(self, image):
        data = _patched(image)
        _va, off, _vsize = find_section(data, SECTION_NAME)
        assert bytes(data[off : off + TABLE_SIZE]) == bytes(TABLE_SIZE)

    def test_applying_twice_raises(self, image):
        data = _patched(image)
        with pytest.raises(ValueError):
            MultiModPatch().apply(data)


class TestItComposesWithModLoadOrder:
    """The two patches that reach into the same pipeline. This one records and mounts from inside
    the `-mod` handler; that one replaces the mount block and makes the whole table parse twice.
    Neither may touch a byte the other touches, in either direction."""

    @pytest.fixture
    def shared(self) -> bytearray:
        return multi_mod_and_mod_load_order_image()

    @pytest.mark.parametrize("first", ["multi-mod", "mod-load-order"])
    def test_both_apply_and_both_verify_in_either_order(self, shared, first):
        order = [MultiModPatch, ModLoadOrderPatch]
        if first == "mod-load-order":
            order.reverse()
        for cls in order:
            cls().apply(shared)
        assert MultiModPatch().verify(shared) == []
        assert ModLoadOrderPatch().verify(shared) == []

    def test_this_patch_leaves_the_stock_mount_alone(self, shared):
        """Rewriting it is `mod-load-order`'s business. Leaving it is also what keeps the stock
        rule that a `-mod` directory outranks a `-mod` archive, since the stock block re-mounts
        the last of each in that order on top of whatever the table already mounted."""
        data = _patched(shared)
        off = va_to_offset(data, MOD_MOUNT_BLOCK)
        assert bytes(data[off : off + len(MOD_MOUNT_BLOCK_ORIGINAL)]) == MOD_MOUNT_BLOCK_ORIGINAL

    def test_neither_rewrites_a_byte_the_other_rewrites(self):
        """Asserted on the declared sites rather than on a diff of two patched images, so it holds
        for a build where one of the two happens to be unmapped as well.

        `mod-load-order` rewrites only the first six bytes of the mount block - the rest is left
        standing behind the jump - so the span compared against is the jump's, not the block's."""
        theirs = dict(mlo.SITES)
        theirs[mlo.MOD_MOUNT_BLOCK] = mlo.MOD_MOUNT_SKIP
        assert _spans(SITES).isdisjoint(_spans(theirs))


class TestTheBuildFingerprint:
    def test_the_call_it_reasons_from_goes_where_the_patch_says(self):
        """Derived from the stock displacement rather than written down, so this asserts the
        premise - that the handler ends on an assignment - rather than restating it."""
        assert MOD_HANDLER_STORE_TARGET == ASCII_STRING_ASSIGN

    @pytest.mark.parametrize("va", sorted({**SITES, **ANCHORS}), ids=lambda va: f"{va:#010x}")
    def test_one_wrong_byte_refuses_the_build(self, image, va):
        off = va_to_offset(image, va)
        image[off] ^= 0xFF
        with pytest.raises(ValueError):
            MultiModPatch().apply(image)

    @pytest.mark.parametrize("block", sorted(BLOCKS), ids=lambda va: f"{va:#010x}")
    def test_each_block_is_long_enough_for_the_call_that_replaces_it(self, block):
        assert len(BLOCKS[block][1]) >= 5


class TestTheRegistry:
    def test_it_is_registered_and_marked_experimental(self):
        assert PATCHES["multi-mod"] is MultiModPatch
        assert MultiModPatch.experimental

    def test_it_takes_no_parameters(self):
        assert MultiModPatch().options() == {}

    def test_it_declares_no_ini_surface(self):
        """It changes which copy of a file the engine reads, not what the engine accepts."""
        assert MultiModPatch().ini_surface().enum_members == ()


def _spans(sites: dict[int, bytes]) -> set[int]:
    """Every byte address a ``{va: bytes}`` map of rewritten windows covers."""
    return {va + n for va, window in sites.items() for n in range(len(window))}
