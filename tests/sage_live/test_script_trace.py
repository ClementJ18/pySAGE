"""The script trace: the cave executed under unicorn, and the ring read back through a fake process.

The cave is run for both entry points - the logger replacement, which must record and then reach
the logger with the stack untouched, and the sequential wrapper, which must make the engine's own
condition call, record only a "yes", and return with the stack balanced for `ret 0xc`.
"""

from __future__ import annotations

import faulthandler
import struct

import pytest

from sage_live.backends.live_patch import call_target
from sage_live.backends.script_trace import (
    CAPACITY,
    TRACE_MAGIC,
    BreakpointHit,
    EventKind,
    ScriptTrace,
    TraceEvent,
    build_trace_cave,
    kind_mask,
)
from sage_patch.addresses import (
    GAME_LOGIC_FRAME,
    GAME_LOGIC_GAME_MODE,
    OBJECT_ID,
    SCRIPT_DEBUG_RUN_SCRIPT_LOG,
    SCRIPT_ENGINE_CURRENT_OBJECT,
    SCRIPT_ENGINE_EVALUATE,
    SCRIPT_EXECUTE_LOG_CALLS,
    SCRIPT_SEQUENTIAL_EVALUATE_CALL,
    SCRIPT_SEQUENTIAL_EVALUATE_CALL_BYTES,
    THE_GAME_LOGIC,
)
from tests.sage_live.fake_process import FakeProcess

CAVE = 0x20000000
LOGIC = 0x10000000
ENGINE = 0x11000000
OBJECT = 0x12000000
SCRIPT = 0x13000000
RING = 0x400
GATE_MODE = 0x14000000


def ring_entry(read, base: int, index: int) -> tuple[int, int, int, int]:
    return struct.unpack("<IIII", read(base + RING + index * 16, 16))


class TestCave:
    unicorn = pytest.importorskip("unicorn", reason="executing the cave needs unicorn")

    def emulator(self, evaluate_answer: int = 1):
        from unicorn import UC_ARCH_X86, UC_MODE_32, Uc  # noqa: PLC0415

        uc = Uc(UC_ARCH_X86, UC_MODE_32)
        image, log, sequential = build_trace_cave(CAVE)
        # `mem_map` raises and catches an SEH access violation inside Unicorn 2.1.4 on Windows;
        # every map succeeds, but the fault handler would print a stack for each one.
        was_enabled = faulthandler.is_enabled()
        faulthandler.disable()
        try:
            uc.mem_map(CAVE, (len(image) + 0xFFF) & ~0xFFF)
            for page in (THE_GAME_LOGIC, LOGIC, OBJECT, SCRIPT, GATE_MODE, 0x00200000, 0x00300000):
                uc.mem_map(page & ~0xFFF, 0x1000)
            uc.mem_map(ENGINE, 0x20000)
            uc.mem_map(SCRIPT_DEBUG_RUN_SCRIPT_LOG & ~0xFFF, 0x1000)
            if SCRIPT_ENGINE_EVALUATE & ~0xFFF != SCRIPT_DEBUG_RUN_SCRIPT_LOG & ~0xFFF:
                uc.mem_map(SCRIPT_ENGINE_EVALUATE & ~0xFFF, 0x1000)
        finally:
            if was_enabled:
                faulthandler.enable()
        uc.mem_write(CAVE, image)
        uc.mem_write(THE_GAME_LOGIC, struct.pack("<I", LOGIC))
        uc.mem_write(LOGIC + GAME_LOGIC_FRAME, struct.pack("<I", 777))
        uc.mem_write(OBJECT + OBJECT_ID, struct.pack("<I", 4242))
        # The engine's evaluator, stubbed: answer in al, pop the three arguments.
        uc.mem_write(SCRIPT_ENGINE_EVALUATE, bytes([0xB0, evaluate_answer, 0xC2, 0x0C, 0x00]))
        return uc, log, sequential

    def break_on(self, uc, script: int, mask: int) -> None:
        uc.mem_write(CAVE + 0x14, struct.pack("<II", GATE_MODE, 1))  # gate, one breakpoint
        uc.mem_write(CAVE + 0x200, struct.pack("<II", script, mask))

    def fire_logger(self, uc, log: int, is_true: int) -> None:
        from unicorn.x86_const import UC_X86_REG_EDI, UC_X86_REG_ESI  # noqa: PLC0415

        uc.reg_write(UC_X86_REG_ESI, SCRIPT)
        uc.reg_write(UC_X86_REG_EDI, ENGINE)
        self.run(uc, log, [0x00300000, 0xAAAA, is_true, 0], SCRIPT_DEBUG_RUN_SCRIPT_LOG)

    def test_a_breakpoint_holds_the_gate_and_says_what_hit(self) -> None:
        uc, log, _ = self.emulator()
        self.break_on(uc, SCRIPT, kind_mask([EventKind.TRUE_ACTIONS]))
        self.fire_logger(uc, log, is_true=1)
        assert struct.unpack("<I", bytes(uc.mem_read(GATE_MODE, 4)))[0] == 1
        hits, script, frame, kind = struct.unpack("<IIII", bytes(uc.mem_read(CAVE + 0x1C, 16)))
        assert (hits, script, frame, kind) == (1, SCRIPT, 777, EventKind.TRUE_ACTIONS)

    def test_a_breakpoint_ignores_kinds_outside_its_mask(self) -> None:
        uc, log, _ = self.emulator()
        self.break_on(uc, SCRIPT, kind_mask([EventKind.TRUE_ACTIONS]))
        self.fire_logger(uc, log, is_true=0)
        assert struct.unpack("<I", bytes(uc.mem_read(GATE_MODE, 4)))[0] == 0
        assert struct.unpack("<I", bytes(uc.mem_read(CAVE + 0x1C, 4)))[0] == 0

    def test_a_breakpoint_hits_with_recording_off(self) -> None:
        uc, log, _ = self.emulator()
        uc.mem_write(CAVE + 0x10, struct.pack("<I", 0))
        self.break_on(uc, SCRIPT, kind_mask(EventKind))
        self.fire_logger(uc, log, is_true=1)
        assert struct.unpack("<I", bytes(uc.mem_read(GATE_MODE, 4)))[0] == 1
        assert struct.unpack("<I", bytes(uc.mem_read(CAVE + 8, 4)))[0] == 0  # nothing recorded

    def run(self, uc, entry: int, stack: list[int], stop: int) -> int:
        from unicorn.x86_const import UC_X86_REG_EIP, UC_X86_REG_ESP  # noqa: PLC0415

        esp = 0x00200800
        uc.mem_write(esp, b"".join(struct.pack("<I", v) for v in stack))
        uc.reg_write(UC_X86_REG_ESP, esp)
        uc.emu_start(entry, stop, count=500)
        assert uc.reg_read(UC_X86_REG_EIP) == stop
        return uc.reg_read(UC_X86_REG_ESP) - esp

    def test_the_logger_hook_records_then_reaches_the_logger(self) -> None:
        from unicorn.x86_const import UC_X86_REG_EDI, UC_X86_REG_ESI  # noqa: PLC0415

        uc, log, _ = self.emulator()
        uc.reg_write(UC_X86_REG_ESI, SCRIPT)
        uc.reg_write(UC_X86_REG_EDI, ENGINE)
        uc.mem_write(ENGINE + SCRIPT_ENGINE_CURRENT_OBJECT, struct.pack("<I", OBJECT))
        moved = self.run(uc, log, [0x00300000, 0xAAAA, 0, 0], stop=SCRIPT_DEBUG_RUN_SCRIPT_LOG)
        assert moved == 0  # the logger sees executeScript's own stack
        read = lambda address, size: bytes(uc.mem_read(address, size))  # noqa: E731
        assert ring_entry(read, CAVE, 0) == (777, EventKind.FALSE_ACTIONS, SCRIPT, 4242)
        assert struct.unpack("<I", read(CAVE + 8, 4))[0] == 1

    def test_the_sequential_hook_records_a_yes_and_balances_the_stack(self) -> None:
        from unicorn.x86_const import UC_X86_REG_EAX, UC_X86_REG_EDI  # noqa: PLC0415

        uc, _, sequential = self.emulator(evaluate_answer=1)
        uc.reg_write(UC_X86_REG_EDI, SCRIPT)
        moved = self.run(uc, sequential, [0x00300000, SCRIPT, 0, 0], stop=0x00300000)
        assert moved == 16  # the return address and `ret 0xc`'s three arguments
        assert uc.reg_read(UC_X86_REG_EAX) & 0xFF == 1
        read = lambda address, size: bytes(uc.mem_read(address, size))  # noqa: E731
        assert ring_entry(read, CAVE, 0) == (777, EventKind.SEQUENTIAL, SCRIPT, 0)

    def test_the_sequential_hook_records_nothing_on_a_no(self) -> None:
        from unicorn.x86_const import UC_X86_REG_EAX, UC_X86_REG_EDI  # noqa: PLC0415

        uc, _, sequential = self.emulator(evaluate_answer=0)
        uc.reg_write(UC_X86_REG_EDI, SCRIPT)
        self.run(uc, sequential, [0x00300000, SCRIPT, 0, 0], stop=0x00300000)
        assert uc.reg_read(UC_X86_REG_EAX) & 0xFF == 0
        assert struct.unpack("<I", bytes(uc.mem_read(CAVE + 8, 4)))[0] == 0


def running_game() -> FakeProcess:
    process = FakeProcess()
    process.u32(THE_GAME_LOGIC, LOGIC)
    process.u32(LOGIC + GAME_LOGIC_GAME_MODE, 2)
    for site, stock in SCRIPT_EXECUTE_LOG_CALLS.items():
        process.write(site, stock)
    process.write(SCRIPT_SEQUENTIAL_EVALUATE_CALL, SCRIPT_SEQUENTIAL_EVALUATE_CALL_BYTES)
    return process


def emit(process: FakeProcess, cave: int, events: list[tuple[int, int, int, int]]) -> None:
    """What the cave does, done from outside: fill slots, then move the count."""
    written = struct.unpack("<I", process.read(cave + 8, 4) or b"")[0]
    for event in events:
        slot = written % CAPACITY
        process.write(cave + RING + slot * 16, struct.pack("<IIII", *event))
        written += 1
    process.u32(cave + 8, written)


def test_attach_hooks_every_site_and_close_restores_them() -> None:
    process = running_game()
    trace = ScriptTrace(process)
    trace.attach()
    assert trace.cave is not None and process.read(trace.cave, 4) == TRACE_MAGIC
    _, log, sequential = build_trace_cave(trace.cave)
    for site in SCRIPT_EXECUTE_LOG_CALLS:
        assert call_target(site, process.read(site, 5) or b"") == log
    seq = process.read(SCRIPT_SEQUENTIAL_EVALUATE_CALL, 5) or b""
    assert call_target(SCRIPT_SEQUENTIAL_EVALUATE_CALL, seq) == sequential
    assert trace.close() == []
    for site, stock in SCRIPT_EXECUTE_LOG_CALLS.items():
        assert process.read(site, 5) == stock
    assert process.code_writes_while_running == 0


def test_read_returns_new_events_across_the_wrap() -> None:
    process = running_game()
    trace = ScriptTrace(process)
    trace.attach()
    assert trace.cave is not None
    process.u32(trace.cave + 8, CAPACITY - 2)  # nearly a full lap already written
    trace._read = CAPACITY - 2
    emit(process, trace.cave, [(10, 1, 0x100, 0), (11, 2, 0x200, 0), (12, 3, 0x300, 0)])
    assert trace.read() == [
        TraceEvent(10, EventKind.TRUE_ACTIONS, 0x100, 0),
        TraceEvent(11, EventKind.FALSE_ACTIONS, 0x200, 0),
        TraceEvent(12, EventKind.SEQUENTIAL, 0x300, 0),
    ]
    assert trace.read() == []
    trace.close()


def test_a_reader_a_lap_behind_is_told_what_it_lost() -> None:
    process = running_game()
    trace = ScriptTrace(process)
    trace.attach()
    assert trace.cave is not None
    emit(process, trace.cave, [(frame, 1, 0x100, 0) for frame in range(CAPACITY + 5)])
    events = trace.read()
    assert len(events) == CAPACITY and trace.dropped == 5
    assert events[0].frame == 5
    trace.close()


def test_a_second_trace_adopts_the_cave_left_behind() -> None:
    process = running_game()
    first = ScriptTrace(process)
    first.attach()
    second = ScriptTrace(process)
    second.attach()
    assert second.adopted and second.cave == first.cave
    second.close()
    for site, stock in SCRIPT_EXECUTE_LOG_CALLS.items():
        assert process.read(site, 5) == stock


def test_a_network_game_is_refused() -> None:
    process = running_game()
    process.u32(LOGIC + GAME_LOGIC_GAME_MODE, 5)
    with pytest.raises(Exception, match="network game"):
        ScriptTrace(process).attach()


def test_closing_after_the_game_exited_is_quiet() -> None:
    process = running_game()
    trace = ScriptTrace(process)
    trace.attach()
    process.gone = True
    assert trace.close() == []
    assert process.freed == []


def test_breakpoints_are_written_and_hits_read_back() -> None:
    process = running_game()
    trace = ScriptTrace(process)
    trace.attach()
    assert trace.cave is not None
    trace.set_gate(0x5000)
    trace.set_breakpoints({0x300: 2, 0x100: 6})
    assert struct.unpack("<IIII", process.read(trace.cave + 0x14, 16) or b"") == (0x5000, 2, 0, 0)
    table = struct.unpack("<IIII", process.read(trace.cave + 0x200, 16) or b"")
    assert table == (0x100, 6, 0x300, 2)
    assert trace.hit() is None
    process.write(trace.cave + 0x1C, struct.pack("<IIII", 3, 0x100, 90, 1))
    assert trace.hit() == BreakpointHit(3, 0x100, 90, EventKind.TRUE_ACTIONS)
    trace.close()


def test_an_older_cave_is_replaced() -> None:
    process = running_game()
    first = ScriptTrace(process)
    first.attach()
    assert first.cave is not None
    process.u32(first.cave + 4, 1)  # as a version-1 session would have left it
    second = ScriptTrace(process)
    second.attach()
    assert not second.adopted and second.cave != first.cave
    assert first.cave in process.freed
    second.close()
    for site, stock in SCRIPT_EXECUTE_LOG_CALLS.items():
        assert process.read(site, 5) == stock
