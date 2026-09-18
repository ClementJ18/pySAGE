"""The frame gate and the in-memory patcher under it.

The cave is executed, not just read: unicorn runs it against a scratch `TheGameLogic` for every
mode, which is the only way to know the bytes do what the comments beside them say. The patcher
and the gate's attach/detach run against a fake process that records whether each code write
happened while the process was suspended.
"""

from __future__ import annotations

import faulthandler
import struct

import pytest

from sage_live.backends.live_patch import (
    LivePatcher,
    LivePatchError,
    call_bytes,
    call_target,
)
from sage_live.backends.script_debugger import (
    CAVE_SIZE,
    CODE_OFFSET,
    MAGIC,
    Command,
    FrameGate,
    Mode,
    NetworkGameRefused,
    build_gate_cave,
)
from sage_patch.addresses import (
    FRAME_DISPATCHER_PAUSE_CALL,
    FRAME_DISPATCHER_PAUSE_CALL_BYTES,
    GAME_LOGIC_FRAME,
    GAME_LOGIC_GAME_MODE,
    NAME_KEY_TO_NAME,
    PLAYER_LIST_GET_NTH,
    SCRIPT_DEBUG_PAUSED,
    SCRIPT_ENGINE_CURRENT_OBJECT,
    SCRIPT_ENGINE_CURRENT_PLAYER,
    SCRIPT_ENGINE_EVALUATE,
    SCRIPT_ENGINE_RUN_ACTIONS,
    SCRIPT_ENGINE_SCOPE,
    SCRIPT_SCOPE_ENTER,
    SCRIPT_SCOPE_LEAVE,
    THE_GAME_LOGIC,
    THE_NAME_KEY_GENERATOR,
    THE_PLAYER_LIST,
)
from tests.sage_live.fake_process import FakeProcess

CAVE = 0x20000000
LOGIC = 0x10000000


def running_game(game_mode: int = 2, frame: int = 100) -> FakeProcess:
    process = FakeProcess()
    process.u32(THE_GAME_LOGIC, LOGIC)
    process.u32(LOGIC + GAME_LOGIC_FRAME, frame)
    process.u32(LOGIC + GAME_LOGIC_GAME_MODE, game_mode)
    process.write(FRAME_DISPATCHER_PAUSE_CALL, FRAME_DISPATCHER_PAUSE_CALL_BYTES)
    return process


class TestCave:
    """The predicate replacement, run in an emulator for each mode."""

    unicorn = pytest.importorskip("unicorn", reason="executing the cave needs unicorn")

    def run(
        self, mode: int, lease: int, frame: int, target: int = 0
    ) -> tuple[str, int, dict[str, int]]:
        from unicorn import UC_ARCH_X86, UC_HOOK_CODE, UC_MODE_32, Uc  # noqa: PLC0415
        from unicorn.x86_const import (  # noqa: PLC0415
            UC_X86_REG_EAX,
            UC_X86_REG_EIP,
            UC_X86_REG_ESP,
        )

        uc = Uc(UC_ARCH_X86, UC_MODE_32)
        stack, ret = 0x00200000, 0x00300000
        # `mem_map` raises and catches an SEH access violation inside Unicorn 2.1.4 on Windows;
        # every map succeeds, but the fault handler would print a stack for each one.
        was_enabled = faulthandler.is_enabled()
        faulthandler.disable()
        try:
            uc.mem_map(CAVE, 0x1000)
            uc.mem_map(THE_GAME_LOGIC & ~0xFFF, 0x1000)
            uc.mem_map(LOGIC, 0x1000)
            uc.mem_map(stack - 0x1000, 0x2000)
            uc.mem_map(ret, 0x1000)
            uc.mem_map(SCRIPT_DEBUG_PAUSED & ~0xFFF, 0x1000)
        finally:
            if was_enabled:
                faulthandler.enable()
        cave = bytearray(build_gate_cave(CAVE))
        struct.pack_into("<III", cave, 0x08, mode, target, lease)
        uc.mem_write(CAVE, bytes(cave))
        uc.mem_write(THE_GAME_LOGIC, struct.pack("<I", LOGIC))
        uc.mem_write(LOGIC + GAME_LOGIC_FRAME, struct.pack("<I", frame))
        uc.mem_write(stack, struct.pack("<I", ret))
        uc.reg_write(UC_X86_REG_ESP, stack)
        uc.reg_write(UC_X86_REG_EAX, 0xDEADBEEF)
        outcome = {"where": "?"}

        def on_code(emu: Uc, address: int, size: int, _: object) -> None:
            if address == SCRIPT_DEBUG_PAUSED:
                outcome["where"] = "engine"
                emu.emu_stop()
            elif address == ret:
                outcome["where"] = "returned"
                emu.emu_stop()

        uc.hook_add(UC_HOOK_CODE, on_code)
        uc.emu_start(CAVE + CODE_OFFSET, 0xFFFFFFFF, count=200)
        assert uc.reg_read(UC_X86_REG_EIP) in (SCRIPT_DEBUG_PAUSED, ret)
        block = struct.unpack("<IIII", uc.mem_read(CAVE + 0x08, 0x10))
        fields = dict(zip(("mode", "target", "lease", "hits"), block, strict=True))
        return outcome["where"], uc.reg_read(UC_X86_REG_EAX) & 0xFF, fields

    def test_run_defers_to_the_engine(self) -> None:
        where, _, fields = self.run(Mode.RUN, lease=0, frame=100)
        assert where == "engine"
        assert fields["hits"] == 1

    def test_paused_holds_and_spends_the_lease(self) -> None:
        where, al, fields = self.run(Mode.PAUSED, lease=5, frame=100)
        assert (where, al) == ("returned", 1)
        assert fields["lease"] == 4

    def test_an_expired_lease_lets_the_game_go(self) -> None:
        where, _, fields = self.run(Mode.PAUSED, lease=0, frame=100)
        assert where == "engine"
        assert fields["mode"] == Mode.RUN

    def test_run_until_runs_short_of_the_target(self) -> None:
        where, al, fields = self.run(Mode.RUN_UNTIL, lease=5, frame=100, target=101)
        assert (where, al) == ("returned", 0)
        assert fields["mode"] == Mode.RUN_UNTIL

    def test_run_until_holds_at_the_target(self) -> None:
        where, al, fields = self.run(Mode.RUN_UNTIL, lease=5, frame=101, target=101)
        assert (where, al) == ("returned", 1)
        assert fields["mode"] == Mode.PAUSED

    def test_the_cave_fits(self) -> None:
        assert len(build_gate_cave(CAVE)) <= CAVE_SIZE
        assert build_gate_cave(CAVE).startswith(MAGIC)


def test_call_bytes_round_trip() -> None:
    site = FRAME_DISPATCHER_PAUSE_CALL
    assert call_bytes(site, SCRIPT_DEBUG_PAUSED) == FRAME_DISPATCHER_PAUSE_CALL_BYTES
    assert call_target(site, FRAME_DISPATCHER_PAUSE_CALL_BYTES) == SCRIPT_DEBUG_PAUSED
    assert call_target(site, call_bytes(site, 0x7FFE0000)) == 0x7FFE0000


def test_the_patcher_refuses_a_site_it_does_not_recognise() -> None:
    process = FakeProcess()
    process.write(0x401000, b"\x90" * 5)
    with pytest.raises(LivePatchError, match="expected the stock"):
        LivePatcher(process).hook(0x401000, b"\xe8\x00\x00\x00\x00", b"\xe8\x01\x00\x00\x00")
    assert process.suspended == 0


def test_the_patcher_leaves_a_site_someone_else_changed() -> None:
    process = FakeProcess()
    process.write(0x401000, b"\xe8\x00\x00\x00\x00")
    patcher = LivePatcher(process)
    patcher.hook(0x401000, b"\xe8\x00\x00\x00\x00", b"\xe8\x01\x00\x00\x00")
    process.write(0x401000, b"\xcc" * 5)
    notes = patcher.close()
    assert notes and "left as is" in notes[0]
    assert process.read(0x401000, 5) == b"\xcc" * 5


def test_attach_hooks_under_suspension_and_close_restores() -> None:
    process = running_game()
    gate = FrameGate(process)
    gate.attach()
    try:
        assert gate.cave is not None
        hooked = process.read(FRAME_DISPATCHER_PAUSE_CALL, 5)
        assert hooked is not None
        assert call_target(FRAME_DISPATCHER_PAUSE_CALL, hooked) == gate.cave + CODE_OFFSET
        assert process.read(gate.cave, 4) == MAGIC
        gate.pause()
        assert gate.state().mode == Mode.PAUSED
        gate.run_until(105)
        assert (gate.state().mode, gate.state().target) == (Mode.RUN_UNTIL, 105)
    finally:
        cave = gate.cave
        assert gate.close() == []
    assert process.read(FRAME_DISPATCHER_PAUSE_CALL, 5) == FRAME_DISPATCHER_PAUSE_CALL_BYTES
    assert process.freed == [cave]
    assert process.code_writes_while_running == 0


def test_a_second_attach_adopts_the_cave_left_behind() -> None:
    process = running_game()
    first = FrameGate(process)
    first.attach()
    first._stop.set()  # a controller that died without detaching
    left = first.cave
    second = FrameGate(process)
    second.attach()
    try:
        assert second.adopted and second.cave == left
    finally:
        second.close()
    assert process.read(FRAME_DISPATCHER_PAUSE_CALL, 5) == FRAME_DISPATCHER_PAUSE_CALL_BYTES


def test_a_network_game_is_refused() -> None:
    process = running_game(game_mode=1)
    with pytest.raises(NetworkGameRefused):
        FrameGate(process).attach()
    assert process.read(FRAME_DISPATCHER_PAUSE_CALL, 5) == FRAME_DISPATCHER_PAUSE_CALL_BYTES


def test_closing_after_the_game_exited_is_quiet() -> None:
    process = running_game()
    gate = FrameGate(process)
    gate.attach()
    gate.pause()
    process.gone = True
    assert gate.close() == []
    assert process.freed == []


def _u32(value: int) -> bytes:
    return struct.pack("<I", value)


class TestCommand:
    """The command mailbox, run in an emulator with the engine's helpers stubbed to record."""

    unicorn = pytest.importorskip("unicorn", reason="executing the cave needs unicorn")

    ENGINE = 0x11000000
    PLAYER = 0x12000000
    NAME = 0x12000100  # the script's name AsciiString *
    PLAYER_NAME = 0x12000200  # what the name-key lookup hands back
    SCRIPT = 0x13000000
    RECORD = 0x14000000
    EARLIER_PLAYER = 0x12345678
    STACK = 0x00200000
    RETURN = 0x00300000

    def stubs(self, player: int) -> dict[int, bytes]:
        """Each engine helper as a few bytes that record what they were given."""

        def slot(index: int) -> bytes:
            return _u32(self.RECORD + index * 4)

        arg1, arg2, arg3 = b"\x8b\x44\x24\x04", b"\x8b\x44\x24\x08", b"\x8b\x44\x24\x0c"
        store, store_ecx = b"\xa3", b"\x89\x0d"
        return {
            # player = GetNth(side): records the side and the list, answers `player`
            PLAYER_LIST_GET_NTH: arg1
            + store
            + slot(0)
            + store_ecx
            + slot(1)
            + b"\xb8"
            + _u32(player)
            + b"\xc2\x04\x00",
            NAME_KEY_TO_NAME: b"\xb8" + _u32(self.PLAYER_NAME) + b"\xc2\x04\x00",
            # enter(target, value): records both, and the guard
            SCRIPT_SCOPE_ENTER: arg1
            + store
            + slot(2)
            + arg2
            + store
            + slot(3)
            + store_ecx
            + slot(4)
            + b"\xc2\x08\x00",
            SCRIPT_SCOPE_LEAVE: store_ecx + slot(5) + b"\xc3",
            # evaluate(script, 0, 0): records the script and the current player, answers yes
            SCRIPT_ENGINE_EVALUATE: arg1
            + store
            + slot(6)
            + b"\x8b\x81"
            + _u32(SCRIPT_ENGINE_CURRENT_PLAYER)
            + store
            + slot(7)
            + b"\xb0\x01\xc2\x0c\x00",
            # run(list, script, name): records all three
            SCRIPT_ENGINE_RUN_ACTIONS: arg1
            + store
            + slot(8)
            + arg2
            + store
            + slot(9)
            + arg3
            + store
            + slot(10)
            + b"\xc2\x0c\x00",
        }

    def run(self, command: int, side: int = 2, player: int = PLAYER) -> dict[str, object]:
        from unicorn import UC_ARCH_X86, UC_HOOK_CODE, UC_MODE_32, Uc  # noqa: PLC0415
        from unicorn.x86_const import (  # noqa: PLC0415
            UC_X86_REG_EBP,
            UC_X86_REG_EBX,
            UC_X86_REG_ECX,
            UC_X86_REG_EDI,
            UC_X86_REG_ESI,
            UC_X86_REG_ESP,
        )

        uc = Uc(UC_ARCH_X86, UC_MODE_32)
        stubs = self.stubs(player)
        wanted = {CAVE, THE_GAME_LOGIC, THE_PLAYER_LIST, THE_NAME_KEY_GENERATOR, LOGIC}
        wanted |= {self.PLAYER, self.SCRIPT, self.RECORD, self.RETURN, SCRIPT_DEBUG_PAUSED}
        wanted |= set(stubs)
        was_enabled = faulthandler.is_enabled()
        faulthandler.disable()
        try:
            for page in sorted({address & ~0xFFF for address in wanted}):
                uc.mem_map(page, 0x1000)
            uc.mem_map(self.STACK - 0x1000, 0x2000)
            uc.mem_map(self.ENGINE, 0x20000)
        finally:
            if was_enabled:
                faulthandler.enable()
        for address, code in stubs.items():
            uc.mem_write(address, code)
        uc.mem_write(THE_PLAYER_LIST, _u32(0x0BADF00D))
        uc.mem_write(self.SCRIPT + 0x34, _u32(0xA1A1A1A1))  # true actions
        uc.mem_write(self.SCRIPT + 0x38, _u32(0xB2B2B2B2))  # false actions
        uc.mem_write(self.ENGINE + SCRIPT_ENGINE_CURRENT_PLAYER, _u32(self.EARLIER_PLAYER))
        uc.mem_write(self.ENGINE + SCRIPT_ENGINE_CURRENT_OBJECT, _u32(0x0B1EC7))
        cave = bytearray(build_gate_cave(CAVE))
        struct.pack_into("<IIIIIII", cave, 0x18, 1, 0, command, self.SCRIPT, side, self.NAME, 7)
        uc.mem_write(CAVE, bytes(cave))
        uc.mem_write(self.STACK, _u32(self.RETURN))
        uc.reg_write(UC_X86_REG_ESP, self.STACK)
        uc.reg_write(UC_X86_REG_ECX, self.ENGINE)
        saved = (UC_X86_REG_EBX, UC_X86_REG_ESI, UC_X86_REG_EDI, UC_X86_REG_EBP)
        for register, value in zip(saved, (0xB0B0, 0x5151, 0xD1D1, 0xBEBE), strict=True):
            uc.reg_write(register, value)

        def stop_at_engine(emu: Uc, address: int, size: int, _: object) -> None:
            if address == SCRIPT_DEBUG_PAUSED:
                emu.emu_stop()

        uc.hook_add(UC_HOOK_CODE, stop_at_engine)
        uc.emu_start(CAVE + CODE_OFFSET, 0xFFFFFFFF, count=2000)

        def engine(offset: int) -> int:
            return struct.unpack("<I", bytes(uc.mem_read(self.ENGINE + offset, 4)))[0]

        recorded = struct.unpack("<11I", bytes(uc.mem_read(self.RECORD, 44)))
        done = struct.unpack("<I", bytes(uc.mem_read(CAVE + 0x1C, 4)))[0]
        result = struct.unpack("<I", bytes(uc.mem_read(CAVE + 0x30, 4)))[0]
        names = "side player_list scope_target scope_value guard left evaluated player_seen"
        names += " list script name"
        seen: dict[str, object] = dict(zip(names.split(), recorded, strict=True))
        seen.update(
            done=done,
            result=result,
            player_after=engine(SCRIPT_ENGINE_CURRENT_PLAYER),
            object_after=engine(SCRIPT_ENGINE_CURRENT_OBJECT),
            registers=tuple(uc.reg_read(register) for register in saved),
            esp=uc.reg_read(UC_X86_REG_ESP) - self.STACK,
        )
        return seen

    def test_evaluate_runs_in_the_players_scope_and_reports(self) -> None:
        seen = self.run(Command.EVALUATE)
        assert (seen["side"], seen["player_list"]) == (2, 0x0BADF00D)
        scope = self.ENGINE + SCRIPT_ENGINE_SCOPE
        assert (seen["scope_target"], seen["scope_value"]) == (scope, self.PLAYER_NAME)
        assert seen["guard"] == seen["left"] == CAVE + 0x40
        assert (seen["evaluated"], seen["player_seen"]) == (self.SCRIPT, self.PLAYER)
        assert (seen["done"], seen["result"]) == (1, 1)

    def test_the_engine_state_and_registers_come_back(self) -> None:
        seen = self.run(Command.EVALUATE)
        assert (seen["player_after"], seen["object_after"]) == (self.EARLIER_PLAYER, 0x0B1EC7)
        assert seen["registers"] == (0xB0B0, 0x5151, 0xD1D1, 0xBEBE)
        assert seen["esp"] == 0  # stopped on the jump to the engine's predicate, nothing left over

    def test_run_false_actions_passes_the_list_the_script_and_its_name(self) -> None:
        seen = self.run(Command.RUN_FALSE_ACTIONS)
        assert (seen["list"], seen["script"], seen["name"]) == (0xB2B2B2B2, self.SCRIPT, self.NAME)
        assert seen["evaluated"] == 0 and (seen["done"], seen["result"]) == (1, 1)

    def test_a_side_without_a_player_runs_nothing(self) -> None:
        seen = self.run(Command.RUN_TRUE_ACTIONS, player=0)
        assert seen["result"] == 0xFFFFFFFF and seen["done"] == 1
        assert seen["guard"] == 0 and seen["list"] == 0


def test_a_command_waits_for_the_game_and_reads_the_result() -> None:
    process = running_game()
    gate = FrameGate(process)
    gate.attach()
    assert gate.cave is not None
    cave = gate.cave
    original = process.write

    def game_answers(address: int, data: bytes) -> bool:
        ok = original(address, data)
        if address == cave + 0x18:  # the request: the "game" runs it at once
            original(cave + 0x30, struct.pack("<I", 1))
            original(cave + 0x1C, data)
        return ok

    process.write = game_answers  # type: ignore[method-assign]
    assert gate.command(Command.EVALUATE, 0x5000, 3, 0x6000) == 1
    fields = struct.unpack("<IIII", process.read(cave + 0x20, 16) or b"")
    assert fields == (Command.EVALUATE, 0x5000, 3, 0x6000)
    gate.close()


def test_a_command_the_game_never_runs_times_out() -> None:
    process = running_game()
    gate = FrameGate(process)
    gate.attach()
    with pytest.raises(LivePatchError, match="did not run the command"):
        gate.command(Command.EVALUATE, 0x5000, 3, 0x6000, timeout=0.05)
    gate.close()
