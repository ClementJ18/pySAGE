"""Tests for the crash-dump patch.

The cave is hand-assembled x86 that cannot be executed here, and it runs exactly once per
process - inside a process that has already crashed - so nothing about it is observable by trying
it. The tests that matter therefore disassemble it back and assert it says what it was meant to
say, with two failure modes singled out because both are invisible to `apply` and `verify`:

* a **stack imbalance**. Both hooks are jumps that stand in for a run of `push`es in somebody
  else's frame, so pushing one dword too few or too many silently shifts every argument of the
  call that follows - `MiniDumpWriteDump` would read the file handle as its dump type.
  `TestStackBalance` counts the pushes on each path and compares them with the window each hook
  replaced;
* a **callback that answers the wrong question**. It is handed every module, every thread and
  every memory range in the process, and clearing a flag for the wrong one either drops
  `game.dat`'s own globals or keeps the 20 MB this patch exists to remove. Its type test, its
  base-address test and the single bit it clears are each asserted on their own.
"""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

from sage_patch.addresses import (
    DEBUG_CRASH_EXCEPTION_CODE,
    DEBUG_CRASH_MESSAGE_EBP,
    DEBUG_CRASH_MODE_EBP,
    DEBUG_CRASH_RAISE,
    DEBUG_CRASH_RAISE_BYTES,
    DEBUG_CRASH_RAISE_RESUME,
    DEBUG_CRASH_TAG_EBP,
    IMAGE_BASE,
    MINI_DUMP_ARGS,
    MINI_DUMP_ARGS_BYTES,
    MINI_DUMP_ARGS_RESUME,
    MINI_DUMP_EXCEPTION_INFO_EBP,
    MINI_DUMP_FULL_DUMP_EBP,
    WRITE_MINI_DUMP,
)
from sage_patch.patches.crash_dump import (
    ANCHORS,
    DEEP_PROFILE,
    MODULE_WRITE_DATA_SEG,
    NORMAL_PROFILE,
    RAISE_ARGUMENT_COUNT,
    SECTION_NAME,
    CrashDumpPatch,
    build_code,
    build_section,
    entry_points,
)
from sage_patch.registry import PATCHES
from sage_patch.utils import find_section, next_section_rva, va_to_offset

from .synthetic import crash_dump_image

BASE = 0x00F00000

_GAME_DAT = Path(__file__).resolve().parents[2] / "game.dat"

#: `writeMiniDump` runs from its prologue to the `int3` padding after its `ret`, and
#: `Debug::crash` from `WRITE_MINI_DUMP`'s neighbour at `0x0043A820` to the same. Both are where
#: the branch-target sweep has to stop: a jump from outside cannot reach one of their frame locals
#: anyway, so anything past the end is a different function's arithmetic.
_WRITE_MINI_DUMP_SIZE = 0x1D1
_DEBUG_CRASH = 0x0043A820
_DEBUG_CRASH_SIZE = 0x44D

#: `MiniDumpWithPrivateReadWriteMemory`, the bit that answers "what was this pointer pointing at"
#: and the one the constructor refuses a profile without.
_WITH_PRIVATE_READ_WRITE_MEMORY = 0x0200


def instructions(base: int = BASE):
    """The cave's code, decoded at the address it was laid out for. ``base`` is the **section**
    base, so the code starts past the data header - and the honest source for where that is is the
    first entry point, not a constant counted twice."""
    capstone = pytest.importorskip("capstone")
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    md.detail = True
    code_va = min(entry_points(base))
    return {ins.address: ins for ins in md.disasm(build_code(base), code_va)}


def text(ins) -> str:
    return f"{ins.mnemonic} {ins.op_str}".strip()


def body(start: int, end: int, base: int = BASE) -> list:
    """The decoded instructions of one routine, in address order."""
    decoded = instructions(base)
    return [decoded[a] for a in sorted(decoded) if start <= a < end]


def at(data: bytes | bytearray, va: int, count: int) -> bytes:
    off = va_to_offset(data, va)
    assert off is not None, f"0x{va:08x} is not mapped"
    return bytes(data[off : off + count])


def _find_callback_block(section: bytes) -> int:
    """Where the `MINIDUMP_CALLBACK_INFORMATION` sits in the cave's data header, found by looking
    for the routine's own address rather than by repeating the layout constant."""
    _args, _raise, callback = entry_points(BASE)
    for off in range(0, min(entry_points(BASE)) - BASE, 4):
        if struct.unpack_from("<II", section, off) == (callback, 0):
            return off
    raise AssertionError("the header carries no callback block")


def _characteristics(data: bytes | bytearray, name: str) -> int:
    """One appended section's `Characteristics` dword, which `sage_patch.pe.Section` does not
    carry - it answers where a section is, not what may be done to it."""
    e = struct.unpack_from("<I", data, 0x3C)[0]
    count = struct.unpack_from("<H", data, e + 6)[0]
    table = e + 24 + struct.unpack_from("<H", data, e + 20)[0]
    for index in range(count):
        header = table + index * 40
        if bytes(data[header : header + 8]) == name.encode("ascii").ljust(8, b"\x00"):
            return struct.unpack_from("<I", data, header + 36)[0]
    raise AssertionError(f"{name} is absent")


class TestTheProfiles:
    def test_the_default_carries_the_heap(self):
        """The whole point: without this bit the dump still holds every singleton pointer and
        nothing any of them points at."""
        assert NORMAL_PROFILE & _WITH_PRIVATE_READ_WRITE_MEMORY

    def test_the_deep_profile_only_ever_adds(self):
        assert DEEP_PROFILE & NORMAL_PROFILE == NORMAL_PROFILE
        assert DEEP_PROFILE != NORMAL_PROFILE

    def test_the_stock_type_is_refused(self):
        """`MiniDumpWithDataSegs` alone is what the engine already asks for, so accepting it would
        let somebody install this patch and change nothing."""
        with pytest.raises(ValueError, match="no heap"):
            CrashDumpPatch(normal=0x0001)

    def test_a_deep_profile_without_a_heap_is_refused(self):
        with pytest.raises(ValueError, match="no heap"):
            CrashDumpPatch(deep=0x0001)

    def test_full_memory_counts_as_a_heap(self):
        assert CrashDumpPatch(normal=0x0002).normal == 0x0002

    @pytest.mark.parametrize("value", [-1, 0x1_0000_0000])
    def test_a_type_that_is_not_a_dword_is_refused(self, value):
        with pytest.raises(ValueError):
            CrashDumpPatch(normal=value)

    def test_the_name_says_which_profiles_were_built(self):
        assert str(CrashDumpPatch(normal=0x0202, deep=0x0203)) == "crash-dump (0x0202/0x0203)"


class TestTheArgsHook:
    """It stands in for the eighteen bytes that push `MiniDumpWriteDump`'s last four arguments."""

    def _body(self):
        args, raise_, _callback = entry_points(BASE)
        return body(args, raise_)

    def test_it_starts_the_cave_code(self):
        args, raise_, callback = entry_points(BASE)
        assert args < raise_ < callback

    def test_it_pushes_the_callback_block_the_header_holds(self):
        """The stock `push edi` here is a literal null, which is the reason no callback runs."""
        section = build_section(BASE, NORMAL_PROFILE, DEEP_PROFILE)
        _args, _raise, callback = entry_points(BASE)
        block = _find_callback_block(section)
        routine, param = struct.unpack_from("<II", section, block)
        assert (routine, param) == (callback, 0), "the block must name the routine and no context"
        assert any(text(ins) == f"push 0x{BASE + block:x}" for ins in self._body())

    def test_the_user_stream_parameter_stays_null(self):
        assert [text(ins) for ins in self._body()].count("push 0") == 1

    def test_it_rebuilds_the_exception_information_pointer(self):
        offset = 0x100 - (MINI_DUMP_EXCEPTION_INFO_EBP & 0xFF)
        assert any(text(ins) == f"lea eax, [ebp - 0x{offset:x}]" for ins in self._body())

    def test_the_dump_type_comes_from_the_header_table(self):
        section = build_section(BASE, NORMAL_PROFILE, DEEP_PROFILE)
        assert struct.unpack_from("<II", section, 0) == (NORMAL_PROFILE, DEEP_PROFILE)
        assert any(text(ins) == f"push dword ptr [ecx*4 + 0x{BASE:x}]" for ins in self._body())

    def test_the_fulldump_flag_is_what_indexes_it(self):
        """The engine's own `fulldump` debug command keeps selecting between the two profiles,
        rather than the patch replacing the switch with a constant."""
        assert any(
            text(ins) == f"cmp byte ptr [ebp + 0x{MINI_DUMP_FULL_DUMP_EBP:x}], 0"
            for ins in self._body()
        )
        assert any(text(ins) == "inc ecx" for ins in self._body())

    def test_it_returns_by_jumping_to_the_file_handle_push(self):
        assert text(self._body()[-1]) == f"jmp 0x{MINI_DUMP_ARGS_RESUME:x}"

    def test_it_calls_nothing(self):
        """It runs in a process that has already faulted, so it is leaf code by construction."""
        assert not [ins for ins in self._body() if ins.mnemonic == "call"]


class TestTheRaiseHook:
    """It stands in for `RaiseException`'s four arguments in `Debug::crash`."""

    def _body(self):
        _args, raise_, callback = entry_points(BASE)
        return body(raise_, callback)

    def test_it_spills_the_three_values_the_exception_record_is_missing(self):
        reads = [text(ins) for ins in self._body() if ins.mnemonic == "mov" and "eax," in text(ins)]
        assert reads == [
            f"mov eax, dword ptr [ebp - {-DEBUG_CRASH_MESSAGE_EBP}]",
            f"mov eax, dword ptr [ebp - {-DEBUG_CRASH_TAG_EBP}]",
            f"mov eax, dword ptr [ebp + {DEBUG_CRASH_MODE_EBP}]",
        ]

    def test_it_spills_them_into_three_consecutive_slots(self):
        writes = [
            int(text(ins).removeprefix("mov dword ptr [").split("]")[0], 16)
            for ins in self._body()
            if text(ins).startswith("mov dword ptr [0x")
        ]
        assert len(writes) == RAISE_ARGUMENT_COUNT
        assert writes == [writes[0] + 4 * i for i in range(RAISE_ARGUMENT_COUNT)]

    def test_the_argument_block_it_passes_is_the_block_it_filled(self):
        writes = [
            int(text(ins).removeprefix("mov dword ptr [").split("]")[0], 16)
            for ins in self._body()
            if text(ins).startswith("mov dword ptr [0x")
        ]
        assert any(text(ins) == f"push 0x{writes[0]:x}" for ins in self._body())

    def test_it_declares_the_count_it_actually_filled(self):
        """A count larger than the block is how a well-meant exception record reads off the end of
        the cave and into whatever follows it."""
        assert any(text(ins) == f"push {RAISE_ARGUMENT_COUNT}" for ins in self._body())

    def test_the_exception_code_is_unchanged(self):
        """The filter at `0x0043D610` recognises this code and treats it as a crash rather than a
        fault, so changing it would route the engine's own asserts down the wrong arm."""
        assert any(text(ins) == f"push 0x{DEBUG_CRASH_EXCEPTION_CODE:x}" for ins in self._body())

    def test_it_returns_by_jumping_to_the_raise_itself(self):
        assert text(self._body()[-1]) == f"jmp 0x{DEBUG_CRASH_RAISE_RESUME:x}"

    def test_it_calls_nothing(self):
        assert not [ins for ins in self._body() if ins.mnemonic == "call"]


class TestTheCallback:
    def _body(self):
        _args, _raise, callback = entry_points(BASE)
        decoded = instructions()
        return [decoded[a] for a in sorted(decoded) if a >= callback]

    def test_it_answers_only_the_module_callback(self):
        """It is handed threads, memory ranges and cancellation requests too, and the only honest
        answer to those is the one dbghelp already had."""
        assert any(text(ins) == "cmp dword ptr [eax + 8], 0" for ins in self._body())

    def test_it_keeps_game_dats_own_data_segments(self):
        """`.rdata` and `.data` are where every engine singleton lives, so the one module whose
        globals must survive is the one being debugged."""
        assert any(
            text(ins) == f"cmp dword ptr [eax + 0x18], 0x{IMAGE_BASE:x}" for ins in self._body()
        )

    def test_it_tests_the_whole_64_bit_base_address(self):
        """`BaseOfImage` is a `ULONG64`; comparing only its low half would keep the data segments
        of a module that happened to load at 0x1_0040_0000."""
        assert any(text(ins) == "cmp dword ptr [eax + 0x1c], 0" for ins in self._body())

    def test_it_clears_the_data_segment_bit_and_nothing_else(self):
        """`ModuleWriteModule` has to survive, or a filtered module vanishes from the module list
        and a return address into it resolves to nothing."""
        mask = 0xFFFFFFFF & ~MODULE_WRITE_DATA_SEG
        ands = [text(ins) for ins in self._body() if ins.mnemonic == "and"]
        assert ands == [f"and dword ptr [ecx], 0x{mask:x}"]

    def test_it_null_tests_both_pointers_it_is_handed(self):
        tests = [text(ins) for ins in self._body() if ins.mnemonic == "test"]
        assert tests == ["test eax, eax", "test ecx, ecx"]

    def test_it_returns_true(self):
        assert any(text(ins) == "mov eax, 1" for ins in self._body())

    def test_it_cleans_its_three_stdcall_arguments(self):
        rets = [text(ins) for ins in self._body() if ins.mnemonic == "ret"]
        assert rets == ["ret 0xc"]

    def test_it_calls_nothing_and_loops_nowhere(self):
        """A callback that faults or spins costs the dump, which is the one thing the process has
        left, so it is straight-line code with forward branches only."""
        assert not [ins for ins in self._body() if ins.mnemonic == "call"]
        for ins in self._body():
            if ins.mnemonic.startswith("j"):
                assert int(ins.op_str, 16) > ins.address, f"{ins.address:#010x} branches backwards"


class TestStackBalance:
    """Each hook has to leave `esp` exactly where the bytes it replaced would have.

    Both are `jmp`s rather than `call`s, so there is no return address in play and the arithmetic
    is simply "how many dwords went on". The window each replaced is decoded for the same count,
    so the two cannot drift apart when either side is edited.
    """

    @staticmethod
    def _pushes(instructions_) -> int:
        return sum(1 for ins in instructions_ if ins.mnemonic == "push")

    @staticmethod
    def _window(window: bytes) -> list:
        capstone = pytest.importorskip("capstone")
        md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
        return list(md.disasm(window, 0))

    def test_the_args_hook_pushes_what_its_window_pushed(self):
        args, raise_, _callback = entry_points(BASE)
        assert self._pushes(body(args, raise_)) == self._pushes(self._window(MINI_DUMP_ARGS_BYTES))

    def test_the_raise_hook_pushes_what_its_window_pushed(self):
        _args, raise_, callback = entry_points(BASE)
        assert self._pushes(body(raise_, callback)) == self._pushes(
            self._window(DEBUG_CRASH_RAISE_BYTES)
        )

    @pytest.mark.parametrize("routine", ["args", "raise"])
    def test_neither_hook_pops(self, routine):
        args, raise_, callback = entry_points(BASE)
        start, end = (args, raise_) if routine == "args" else (raise_, callback)
        assert not [ins for ins in body(start, end) if ins.mnemonic in {"pop", "leave"}]


class TestApply:
    def test_it_applies_and_verifies(self):
        data = crash_dump_image()
        patch = CrashDumpPatch()
        patch.apply(data)
        assert patch.verify(data) == []

    def test_a_stock_image_does_not_verify(self):
        assert CrashDumpPatch().verify(crash_dump_image())

    def test_both_windows_become_jumps_into_the_cave(self):
        data = crash_dump_image()
        CrashDumpPatch().apply(data)
        section_va, _, _ = find_section(data, SECTION_NAME)
        args, raise_, _callback = entry_points(section_va)
        for hook_va, expected in ((MINI_DUMP_ARGS, args), (DEBUG_CRASH_RAISE, raise_)):
            off = va_to_offset(data, hook_va)
            assert data[off] == 0xE9
            assert hook_va + 5 + struct.unpack_from("<i", data, off + 1)[0] == expected

    @pytest.mark.parametrize(
        ("hook", "window"),
        [(MINI_DUMP_ARGS, MINI_DUMP_ARGS_BYTES), (DEBUG_CRASH_RAISE, DEBUG_CRASH_RAISE_BYTES)],
    )
    def test_each_window_is_filled_to_its_resume_point(self, hook, window):
        """A jump is five bytes and both windows are wider, so the rest has to be `nop` - a
        leftover byte would be decoded as an instruction on the way back in."""
        data = crash_dump_image()
        CrashDumpPatch().apply(data)
        off = va_to_offset(data, hook)
        assert bytes(data[off + 5 : off + len(window)]) == b"\x90" * (len(window) - 5)

    def test_the_windows_end_where_the_resume_points_start(self):
        assert MINI_DUMP_ARGS + len(MINI_DUMP_ARGS_BYTES) == MINI_DUMP_ARGS_RESUME
        assert DEBUG_CRASH_RAISE + len(DEBUG_CRASH_RAISE_BYTES) == DEBUG_CRASH_RAISE_RESUME

    def test_the_cave_lands_past_every_existing_section(self):
        data = crash_dump_image()
        expected = next_section_rva(data)
        CrashDumpPatch().apply(data)
        section_va, _, _ = find_section(data, SECTION_NAME)
        assert section_va - IMAGE_BASE == expected

    def test_the_cave_is_writable(self):
        """The raise hook spills into its own argument block, so a read-only cave would fault
        inside the crash path and cost the dump."""
        data = crash_dump_image()
        CrashDumpPatch().apply(data)
        assert _characteristics(data, SECTION_NAME) & 0x80000000  # IMAGE_SCN_MEM_WRITE

    def test_applying_twice_raises_rather_than_double_hooking(self):
        data = crash_dump_image()
        CrashDumpPatch().apply(data)
        with pytest.raises(ValueError):
            CrashDumpPatch().apply(data)

    @pytest.mark.parametrize("va", sorted(ANCHORS))
    def test_a_moved_anchor_is_refused(self, va):
        data = crash_dump_image()
        off = va_to_offset(data, va)
        data[off] ^= 0xFF
        with pytest.raises(ValueError):
            CrashDumpPatch().apply(data)

    @pytest.mark.parametrize("va", [MINI_DUMP_ARGS, DEBUG_CRASH_RAISE])
    def test_a_moved_window_is_refused(self, va):
        data = crash_dump_image()
        off = va_to_offset(data, va)
        data[off] ^= 0xFF
        with pytest.raises(ValueError):
            CrashDumpPatch().apply(data)

    def test_it_is_registered(self):
        assert PATCHES[CrashDumpPatch.name] is CrashDumpPatch


class TestDetect:
    def test_it_recovers_the_defaults(self):
        data = crash_dump_image()
        CrashDumpPatch().apply(data)
        found = CrashDumpPatch.detect(data)
        assert isinstance(found, CrashDumpPatch)
        assert (found.normal, found.deep) == (NORMAL_PROFILE, DEEP_PROFILE)

    def test_it_recovers_a_profile_nobody_could_have_guessed(self):
        data = crash_dump_image()
        CrashDumpPatch(normal=0x0205, deep=0x0207).apply(data)
        found = CrashDumpPatch.detect(data)
        assert (found.normal, found.deep) == (0x0205, 0x0207)
        assert found.verify(data) == []

    def test_the_default_probe_would_have_missed_it(self):
        """Which is why `detect` is overridden at all."""
        data = crash_dump_image()
        CrashDumpPatch(normal=0x0205, deep=0x0207).apply(data)
        assert CrashDumpPatch().verify(data)

    def test_an_unpatched_image_carries_nothing(self):
        assert CrashDumpPatch.detect(crash_dump_image()) is None

    def test_detection_never_raises_on_something_that_is_not_a_game_dat(self):
        assert CrashDumpPatch.detect(b"not a PE at all") is None

    def test_a_cave_holding_a_heapless_type_is_not_taken_for_this_patch(self):
        """The constructor refuses such a profile, and `detect` must answer "not this patch"
        rather than propagate that as an error out of a sweep."""
        data = crash_dump_image()
        CrashDumpPatch().apply(data)
        _va, off, _size = find_section(data, SECTION_NAME)
        struct.pack_into("<I", data, off, 0x0001)
        assert CrashDumpPatch.detect(data) is None

    def test_the_filled_argument_block_does_not_stop_it_verifying(self):
        """The raise hook writes those three slots at crash time, so a `game.dat` recovered from a
        machine that has crashed once carries values there. They are state, not the patch."""
        data = crash_dump_image()
        patch = CrashDumpPatch()
        patch.apply(data)
        _va, off, _size = find_section(data, SECTION_NAME)
        struct.pack_into("<III", data, off + 0x10, 0x0A3DE730, 0x00BD4BAC, 1)
        assert patch.verify(data) == []
        assert CrashDumpPatch.detect(data) is not None


@pytest.mark.skipif(not _GAME_DAT.exists(), reason="needs the real game.dat")
class TestInstalledBinary:
    """Against the real binary, which is the only thing that can say the addresses are right.

    The stand-in is built from this patch's own anchor table, so it round-trips whatever that
    table says. Only the shipped `game.dat` can confirm that `0x0043C001` is `MiniDumpWriteDump`'s
    argument push rather than the middle of some other sequence.
    """

    @pytest.fixture(scope="class")
    def stock(self) -> bytes:
        return _GAME_DAT.read_bytes()

    def test_every_site_holds_its_stock_bytes(self, stock):
        for va, expected in (
            (MINI_DUMP_ARGS, MINI_DUMP_ARGS_BYTES),
            (DEBUG_CRASH_RAISE, DEBUG_CRASH_RAISE_BYTES),
            *ANCHORS.items(),
        ):
            assert at(stock, va, len(expected)) == expected, f"0x{va:08x}"

    def test_apply_verify_detect_round_trip(self, stock):
        data = bytearray(stock)
        patch = CrashDumpPatch()
        patch.apply(data)
        assert patch.verify(data) == []
        assert CrashDumpPatch.detect(data) is not None

    def test_the_stock_binary_carries_nothing(self, stock):
        assert CrashDumpPatch.detect(stock) is None

    @pytest.mark.parametrize(
        ("function", "size", "hook", "window"),
        [
            (WRITE_MINI_DUMP, _WRITE_MINI_DUMP_SIZE, MINI_DUMP_ARGS, MINI_DUMP_ARGS_BYTES),
            (_DEBUG_CRASH, _DEBUG_CRASH_SIZE, DEBUG_CRASH_RAISE, DEBUG_CRASH_RAISE_BYTES),
        ],
    )
    def test_nothing_branches_into_a_window(self, stock, function, size, hook, window):
        """A window may be *landed on* - one jump targets the first byte of the args window - but
        nothing may branch into its interior, or the replacement `jmp` would be entered part-way
        through."""
        capstone = pytest.importorskip("capstone")
        md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
        start = va_to_offset(stock, function)
        interior = range(hook + 1, hook + len(window))
        for ins in md.disasm(stock[start : start + size], function):
            if ins.mnemonic.startswith("j") and ins.op_str.startswith("0x"):
                assert int(ins.op_str, 16) not in interior, (
                    f"{ins.address:#010x} branches into the window at {hook:#010x}"
                )

    def test_the_raise_site_reads_both_frame_slots_before_it(self, stock):
        """The hook passes `[ebp-4]` and `[ebp-8]` on, which is only sound because the engine's own
        code on the same path already reads them - so they are live rather than uninitialised."""
        capstone = pytest.importorskip("capstone")
        md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
        start = va_to_offset(stock, _DEBUG_CRASH)
        reads = {
            ins.op_str.split(", ")[1]
            for ins in md.disasm(stock[start : start + _DEBUG_CRASH_SIZE], _DEBUG_CRASH)
            if ins.mnemonic == "mov" and ", dword ptr [ebp - " in ins.op_str
        }
        assert "dword ptr [ebp - 4]" in reads
        assert "dword ptr [ebp - 8]" in reads
