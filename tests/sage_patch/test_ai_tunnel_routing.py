"""Tests for the AI tunnel routing patch.

The cave is three hand-assembled routines sharing a table, so it is checked three ways: read back
as text, run under unicorn against a stand-in engine (objects, players, tunnels and every engine
routine it calls modelled in Python), and - when a `game.dat` sits at the repo root - applied to
the real binary.
"""

from __future__ import annotations

import faulthandler
import struct
from pathlib import Path

import pytest

from sage_patch.addresses import (
    AI_ATTACK_MOVE_TO_POSITION,
    AI_CURRENT_STATE_ID,
    AI_DO_COMMAND_DISPATCH,
    AI_DO_COMMAND_OWNER_EBP,
    AI_DO_COMMAND_SWITCH,
    AI_DO_COMMAND_TAIL,
    AI_DO_COMMAND_THIS_EBP,
    AI_ENTER,
    AI_EXIT,
    AI_MOVE_TO_POSITION,
    CONTAIN_GET_HORDE_IFACE_SLOT,
    CONTAIN_IS_VALID_CONTAINER_FOR_SLOT,
    GAME_LOGIC_FIND_OBJECT_BY_ID,
    GAME_LOGIC_FRAME,
    GAME_LOGIC_RESET,
    GAME_LOGIC_RESET_VTABLE_SLOTS,
    HORDE_IFACE_EXIT_SLOT,
    LOGIC_FRAMES_PER_SECOND,
    OBJECT_AI_UPDATE,
    OBJECT_CONTAIN,
    OBJECT_CONTAINED_BY,
    OBJECT_GET_CONTROLLING_PLAYER,
    OBJECT_ID,
    OBJECT_POSITION,
    PLAYER_NEAREST_TUNNEL,
    PLAYER_TUNNEL_TRACKER,
    PLAYER_TYPE,
    THE_GAME_LOGIC,
    TUNNEL_CONTAIN_INTERFACE_VTABLE,
    TUNNEL_CONTAIN_UPDATE,
    TUNNEL_CONTAIN_UPDATE_VTABLE_SLOT,
)
from sage_patch.patcher import apply_patches
from sage_patch.patches.ai_tunnel_routing import (
    ANCHORS,
    ENTER_SECONDS,
    ENTRY_SIZE,
    EXIT_RETRY_SECONDS,
    FALLBACK_ATTEMPT,
    HOOK_ORIGINAL,
    HOOK_VA,
    PHASE_ENTERING,
    PHASE_EXITING,
    PHASE_INSIDE,
    SECTION_NAME,
    SLOTS,
    VTABLE_SLOTS,
    AiTunnelRoutingPatch,
    Layout,
    build_section,
)
from sage_patch.registry import PATCHES
from sage_patch.utils import find_section, va_to_offset

from .synthetic import ai_tunnel_routing_image

try:
    from unicorn import UC_ARCH_X86, UC_HOOK_CODE, UC_MODE_32, Uc
    from unicorn.x86_const import (
        UC_X86_REG_EAX,
        UC_X86_REG_EBP,
        UC_X86_REG_EBX,
        UC_X86_REG_ECX,
        UC_X86_REG_EDI,
        UC_X86_REG_ESI,
        UC_X86_REG_ESP,
    )
except ImportError:  # the emulator tests skip; the static and real-binary ones still run
    Uc = None

_GAME_DAT = Path(__file__).resolve().parents[2] / "game.dat"

SECTION = 0x00F00000
#: Where the per-frame pass sits in the section: past the three data words and the table.
_TABLE = SECTION + 0x10

MOVE, ATTACK_MOVE, IDLE, ATTACK_OBJECT = 0x00, 0x0F, 0x05, 0x0B
FROM_PLAYER, FROM_SCRIPT, FROM_AI = 0, 1, 2
HUMAN, COMPUTER = 0, 1
RATE = 5


def disassemble(base: int = SECTION):
    capstone = pytest.importorskip("capstone")
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    layout = Layout(base)
    return list(md.disasm(layout.code, layout.dispatch))


class TestTheCave:
    def test_it_disassembles_cleanly_to_its_end(self):
        """Capstone stopping early means an invalid encoding, which would be a crash in-game."""
        insns = disassemble()
        assert sum(i.size for i in insns) == len(Layout(SECTION).code)

    def test_every_branch_stays_inside_the_cave_or_lands_on_a_known_routine(self):
        layout = Layout(SECTION)
        end = layout.dispatch + len(layout.code)
        engine = {
            AI_DO_COMMAND_SWITCH,
            AI_DO_COMMAND_TAIL,
            AI_ENTER,
            AI_EXIT,
            AI_MOVE_TO_POSITION,
            AI_ATTACK_MOVE_TO_POSITION,
            AI_CURRENT_STATE_ID,
            GAME_LOGIC_FIND_OBJECT_BY_ID,
            GAME_LOGIC_RESET,
            OBJECT_GET_CONTROLLING_PLAYER,
            PLAYER_NEAREST_TUNNEL,
            TUNNEL_CONTAIN_UPDATE,
        }
        for insn in disassemble():
            if (
                insn.mnemonic.startswith("j") or insn.mnemonic == "call"
            ) and insn.op_str.startswith("0x"):
                target = int(insn.op_str, 16)
                assert layout.dispatch <= target < end or target in engine, insn

    def test_the_dispatch_starts_with_the_displaced_instructions(self):
        layout = Layout(SECTION)
        assert layout.code.startswith(HOOK_ORIGINAL)

    def test_the_data_words_and_table_lead_the_section(self):
        section = build_section(SECTION, 250)
        assert struct.unpack_from("<f", section, 0)[0] == 250.0
        assert struct.unpack_from("<I", section, 8)[0] == 0xFFFFFFFF
        assert section[0x10 : 0x10 + SLOTS * ENTRY_SIZE] == bytes(SLOTS * ENTRY_SIZE)

    def test_it_relocates_with_its_section(self):
        assert Layout(SECTION).code != Layout(SECTION + 0x10000).code


class _Engine:
    """Just enough of the engine for the three routines to run.

    Objects, players and tunnels live in emulated memory with the layout the cave reads; the engine
    routines it calls are `ret`s whose effect is performed in Python by a code hook on their first
    byte. Every order the cave gives is logged with the `busy` word as it stood.
    """

    HEAP = 0x10000000
    STACK = 0x20000000
    STUBS = 0x30000000
    RETURN = 0x3F000000

    def __init__(self) -> None:
        self.uc = Uc(UC_ARCH_X86, UC_MODE_32)
        self.layout = Layout(SECTION)
        section = build_section(SECTION)
        self._heap = self.HEAP

        rets = {
            PLAYER_NEAREST_TUNNEL: b"\xc3",
            OBJECT_GET_CONTROLLING_PLAYER: b"\xc3",
            GAME_LOGIC_FIND_OBJECT_BY_ID: b"\xc2\x04\x00",
            AI_ENTER: b"\xc2\x08\x00",
            AI_EXIT: b"\xc2\x08\x00",
            AI_MOVE_TO_POSITION: b"\xc2\x08\x00",
            AI_ATTACK_MOVE_TO_POSITION: b"\xc2\x0c\x00",
            AI_CURRENT_STATE_ID: b"\xc3",
            TUNNEL_CONTAIN_UPDATE: b"\xc3",
            GAME_LOGIC_RESET: b"\xc3",
            AI_DO_COMMAND_SWITCH: b"\xf4",
            AI_DO_COMMAND_TAIL: b"\xf4",
        }
        regions = {
            SECTION: (len(section) + 0xFFF) & ~0xFFF,
            self.HEAP: 0x100000,
            self.STACK: 0x10000,
            self.STUBS: 0x1000,
            self.RETURN: 0x1000,
        }
        engine_pages = {va & ~0xFFF for va in rets} | {
            THE_GAME_LOGIC & ~0xFFF,
            LOGIC_FRAMES_PER_SECOND & ~0xFFF,
            TUNNEL_CONTAIN_INTERFACE_VTABLE & ~0xFFF,
        }
        regions.update(dict.fromkeys(engine_pages, 0x1000))
        # unicorn's first mapping takes an access violation it handles itself, which faulthandler
        # would print as a fatal one
        was_enabled = faulthandler.is_enabled()
        faulthandler.disable()
        try:
            for base, size in regions.items():
                self.uc.mem_map(base, size)
        finally:
            if was_enabled:
                faulthandler.enable()
        self.uc.mem_write(SECTION, section)
        for va, code in rets.items():
            self.uc.mem_write(va, code)

        # Synthetic routines the cave reaches through vtables: valid-container, get-horde-iface,
        # horde exit. Each is a ret of the right size at its own address.
        self.valid_va = self.STUBS
        self.horde_iface_va = self.STUBS + 0x10
        self.horde_exit_va = self.STUBS + 0x20
        self.no_horde_va = self.STUBS + 0x30
        self.uc.mem_write(self.valid_va, b"\xc2\x0c\x00")
        self.uc.mem_write(self.horde_iface_va, b"\xc3")
        self.uc.mem_write(self.horde_exit_va, b"\xc2\x08\x00")
        self.uc.mem_write(self.no_horde_va, b"\x33\xc0\xc3")  # xor eax, eax / ret
        self._write(
            TUNNEL_CONTAIN_INTERFACE_VTABLE + CONTAIN_IS_VALID_CONTAINER_FOR_SLOT, self.valid_va
        )
        self._write(
            TUNNEL_CONTAIN_INTERFACE_VTABLE + CONTAIN_GET_HORDE_IFACE_SLOT, self.no_horde_va
        )

        self.game_logic = self._alloc(0x100)
        self._write(THE_GAME_LOGIC, self.game_logic)
        self._write(LOGIC_FRAMES_PER_SECOND, RATE)
        self.frame = 1

        self.objects: dict[int, int] = {}
        self.owner: dict[int, int] = {}  # object -> player
        self.tunnels: dict[int, list[int]] = {}  # player -> tunnel objects
        self.states: dict[int, int] = {}  # AIUpdate -> current state id
        self.accepts = True
        self.orders: list[tuple] = []
        self.horde_ifaces: dict[int, int] = {}  # a horde's contain -> its horde interface
        self.exit: int | None = None
        self._next_id = 1
        self.uc.hook_add(UC_HOOK_CODE, self._on_code)

    @property
    def frame(self) -> int:
        return self._read(self.game_logic + GAME_LOGIC_FRAME)

    @frame.setter
    def frame(self, value: int) -> None:
        self._write(self.game_logic + GAME_LOGIC_FRAME, value)

    def _alloc(self, size: int) -> int:
        va = self._heap
        self._heap += (size + 15) & ~15
        return va

    def _read(self, va: int) -> int:
        return struct.unpack("<I", self.uc.mem_read(va, 4))[0]

    def _write(self, va: int, value: int) -> None:
        self.uc.mem_write(va, struct.pack("<I", value & 0xFFFFFFFF))

    def _pos(self, obj: int) -> tuple[float, float]:
        return struct.unpack("<2f", self.uc.mem_read(obj + OBJECT_POSITION, 8))

    def player(self, kind: int = COMPUTER, network: bool = True) -> int:
        player = self._alloc(0x400)
        self._write(player + PLAYER_TYPE, kind)
        self._write(player + PLAYER_TUNNEL_TRACKER, self._alloc(0x10) if network else 0)
        self.tunnels[player] = []
        return player

    def unit(self, player: int, x: float, y: float = 0.0, *, horde: bool = False) -> int:
        obj = self._alloc(0x300)
        self.objects[self._next_id] = obj
        self._write(obj + OBJECT_ID, self._next_id)
        self._next_id += 1
        self.uc.mem_write(obj + OBJECT_POSITION, struct.pack("<3f", x, y, 0.0))
        ai = self._alloc(0x100)
        self._write(obj + OBJECT_AI_UPDATE, ai)
        self.states[ai] = 0
        self.owner[obj] = player
        if horde:
            contain, vtable = self._alloc(0x10), self._alloc(0x100)
            iface, iface_vtable = self._alloc(0x10), self._alloc(0x100)
            self._write(contain, vtable)
            self._write(vtable + CONTAIN_GET_HORDE_IFACE_SLOT, self.horde_iface_va)
            self._write(iface, iface_vtable)
            self._write(iface_vtable + HORDE_IFACE_EXIT_SLOT, self.horde_exit_va)
            self._write(obj + OBJECT_CONTAIN, contain)
            self.horde_ifaces[contain] = iface
        return obj

    def tunnel(self, player: int, x: float, y: float = 0.0) -> int:
        obj = self.unit(player, x, y)
        contain = self._alloc(0x10)
        self._write(contain, TUNNEL_CONTAIN_INTERFACE_VTABLE)
        self._write(obj + OBJECT_CONTAIN, contain)
        self.tunnels[player].append(obj)
        return obj

    def put_inside(self, unit: int, tunnel: int | None) -> None:
        self._write(unit + OBJECT_CONTAINED_BY, tunnel or 0)

    def kill(self, obj: int) -> None:
        del self.objects[self._read(obj + OBJECT_ID)]

    def _on_code(self, uc, address: int, _size: int, _user) -> None:
        esp = uc.reg_read(UC_X86_REG_ESP)
        ecx = uc.reg_read(UC_X86_REG_ECX)

        def arg(n: int) -> int:
            return self._read(esp + 4 + 4 * n)

        busy = self._read(self.layout.busy)
        if address == PLAYER_NEAREST_TUNNEL:
            player = uc.reg_read(UC_X86_REG_EAX)
            gx, gy = struct.unpack("<2f", uc.mem_read(uc.reg_read(UC_X86_REG_EBX), 8))
            best = None
            for tunnel in self.tunnels.get(player, []):
                tx, ty = self._pos(tunnel)
                d = (tx - gx) ** 2 + (ty - gy) ** 2
                if best is None or d < best[0]:
                    best = (d, tunnel)
            uc.reg_write(UC_X86_REG_EAX, best[1] if best else 0)
        elif address == OBJECT_GET_CONTROLLING_PLAYER:
            uc.reg_write(UC_X86_REG_EAX, self.owner.get(ecx, 0))
        elif address == GAME_LOGIC_FIND_OBJECT_BY_ID:
            uc.reg_write(UC_X86_REG_EAX, self.objects.get(arg(0), 0))
        elif address == AI_CURRENT_STATE_ID:
            uc.reg_write(UC_X86_REG_EAX, self.states[ecx])
        elif address == TUNNEL_CONTAIN_UPDATE:
            uc.reg_write(UC_X86_REG_EAX, 1)
        elif address == self.valid_va:
            uc.reg_write(UC_X86_REG_EAX, int(self.accepts))
        elif address == self.horde_iface_va:
            uc.reg_write(UC_X86_REG_EAX, self.horde_ifaces[ecx])
        elif address == AI_ENTER:
            self.orders.append(("enter", ecx, arg(0), arg(1), busy))
        elif address == AI_EXIT:
            self.orders.append(("exit", ecx, arg(0), arg(1), busy))
        elif address == self.horde_exit_va:
            self.orders.append(("horde_exit", ecx, arg(0), arg(1), busy))
        elif address == AI_MOVE_TO_POSITION:
            pos = struct.unpack("<3f", uc.mem_read(arg(0), 12))
            self.orders.append(("move", ecx, pos, arg(1), busy))
        elif address == AI_ATTACK_MOVE_TO_POSITION:
            pos = struct.unpack("<3f", uc.mem_read(arg(0), 12))
            self.orders.append(("attack_move", ecx, pos, arg(1), arg(2), busy))
        elif address in (AI_DO_COMMAND_SWITCH, AI_DO_COMMAND_TAIL, self.RETURN):
            self.exit = address
            uc.emu_stop()

    def order(self, unit: int, cmd: int, x: float, y: float = 0.0, *, source=FROM_AI, shots=0):
        """Run the dispatch as `aiDoCommand` reaches it with this order. Returns where it left by
        and the registers it left with."""
        parms = self._alloc(0xC0)
        self._write(parms, cmd)
        self._write(parms + 4, source)
        self.uc.mem_write(parms + 8, struct.pack("<3f", x, y, 0.0))
        self._write(parms + 0x34, shots)
        ai = self._read(unit + OBJECT_AI_UPDATE)
        ebp = self.STACK + 0x8000
        self._write(ebp + AI_DO_COMMAND_OWNER_EBP, unit)
        self._write(ebp + AI_DO_COMMAND_THIS_EBP, ai + 0x20)
        self._write(ebp + 8, 0x1234)
        registers = {
            UC_X86_REG_ESI: parms,
            UC_X86_REG_EBX: source,
            UC_X86_REG_EDI: ai,
            UC_X86_REG_EBP: ebp,
            UC_X86_REG_ESP: ebp - 0x100,
            UC_X86_REG_EAX: 0xDEAD,
        }
        for reg, value in registers.items():
            self.uc.reg_write(reg, value)
        self.uc.emu_start(self.layout.dispatch, 0, count=20000)
        after = {reg: self.uc.reg_read(reg) for reg in registers}
        assert self._read(ebp + 8) == 0xFFFFFFFF  # the displaced `or [ebp+8], -1` ran
        return self.exit, after, registers

    def call(self, va: int) -> None:
        esp = self.STACK + 0x4000
        self._write(esp, self.RETURN)
        self.uc.reg_write(UC_X86_REG_ESP, esp)
        self.uc.reg_write(UC_X86_REG_ECX, 0x5555)
        self.uc.emu_start(va, 0, count=200000)
        assert self.exit == self.RETURN

    def tick(self) -> None:
        self.call(self.layout.tick)

    def entry(self, unit: int) -> dict | None:
        uid = self._read(unit + OBJECT_ID)
        for n in range(SLOTS):
            va = _TABLE + n * ENTRY_SIZE
            if self._read(va) == uid:
                raw = bytes(self.uc.mem_read(va, ENTRY_SIZE))
                return {
                    "cmd": struct.unpack_from("<I", raw, 4)[0],
                    "goal": struct.unpack_from("<3f", raw, 8),
                    "shots": struct.unpack_from("<I", raw, 0x14)[0],
                    "phase": raw[0x18],
                    "attempts": raw[0x19],
                    "deadline": struct.unpack_from("<I", raw, 0x1C)[0],
                }
        return None


@pytest.fixture
def engine():
    if Uc is None:
        pytest.skip("the emulator harness needs unicorn")
    return _Engine()


@pytest.fixture
def world(engine):
    """A computer player with a tunnel at each end of a long walk, and a unit by the near one."""
    player = engine.player()
    near = engine.tunnel(player, 50.0)
    far = engine.tunnel(player, 1950.0)
    unit = engine.unit(player, 0.0)
    return engine, player, near, far, unit


def _iface(engine, unit: int) -> int:
    return engine._read(unit + OBJECT_AI_UPDATE) + 0x20


class TestRoutingAnOrder:
    def test_a_long_walk_goes_into_the_near_tunnel(self, world):
        engine, _player, near, _far, unit = world
        left, _after, _before = engine.order(unit, MOVE, 2000.0)
        assert left == AI_DO_COMMAND_TAIL
        assert engine.orders == [("enter", _iface(engine, unit), near, FROM_AI, 1)]
        entry = engine.entry(unit)
        assert entry["phase"] == PHASE_ENTERING
        assert entry["cmd"] == MOVE
        assert entry["goal"] == (2000.0, 0.0, 0.0)
        assert entry["deadline"] == engine.frame + ENTER_SECONDS * RATE

    def test_an_attack_move_keeps_its_shots(self, world):
        engine, *_, unit = world
        engine.order(unit, ATTACK_MOVE, 2000.0, shots=7)
        assert engine.entry(unit)["cmd"] == ATTACK_MOVE
        assert engine.entry(unit)["shots"] == 7

    def test_the_busy_word_is_clear_again_afterwards(self, world):
        engine, *_, unit = world
        engine.order(unit, MOVE, 2000.0)
        assert engine._read(engine.layout.busy) == 0

    @pytest.mark.parametrize(
        ("goal", "routed"),
        [
            (2000.0, True),  # direct 2000, via 50 + 50 + 200 = 300
            (300.0, False),  # the goal's nearest tunnel is the unit's: nothing to gain
        ],
    )
    def test_it_routes_only_when_the_tunnel_is_shorter(self, world, goal, routed):
        engine, *_, unit = world
        left, *_ = engine.order(unit, MOVE, goal)
        assert (left == AI_DO_COMMAND_TAIL) is routed
        assert bool(engine.orders) is routed

    def test_a_tie_walks(self, world):
        engine, *_, unit = world
        # direct 1100; via 50 + |1100 - 1950| + 200 = 1100
        left, *_ = engine.order(unit, MOVE, 1100.0)
        assert left == AI_DO_COMMAND_SWITCH
        assert engine.orders == []

    def test_a_large_transit_cost_keeps_units_walking(self, world):
        engine, *_, unit = world
        engine.uc.mem_write(engine.layout.transit, struct.pack("<f", 5000.0))
        left, *_ = engine.order(unit, MOVE, 2000.0)
        assert left == AI_DO_COMMAND_SWITCH
        assert engine.orders == []

    def test_a_human_players_units_walk(self, engine):
        player = engine.player(HUMAN)
        engine.tunnel(player, 50.0)
        engine.tunnel(player, 1950.0)
        unit = engine.unit(player, 0.0)
        left, *_ = engine.order(unit, MOVE, 2000.0)
        assert left == AI_DO_COMMAND_SWITCH
        assert engine.orders == []

    def test_a_player_without_a_network_walks(self, engine):
        player = engine.player(network=False)
        unit = engine.unit(player, 0.0)
        left, *_ = engine.order(unit, MOVE, 2000.0)
        assert left == AI_DO_COMMAND_SWITCH

    def test_an_order_from_a_script_walks(self, world):
        engine, *_, unit = world
        left, *_ = engine.order(unit, MOVE, 2000.0, source=FROM_SCRIPT)
        assert left == AI_DO_COMMAND_SWITCH
        assert engine.orders == []

    def test_the_skirmish_ais_own_army_order_is_routed(self, world):
        """The skirmish AI gives its army orders as its player: an attack-move from `FROM_PLAYER`
        on each horde, read live. Those are the orders worth routing."""
        engine, _player, near, _far, unit = world
        left, *_ = engine.order(unit, ATTACK_MOVE, 2000.0, source=FROM_PLAYER)
        assert left == AI_DO_COMMAND_TAIL
        assert engine.orders == [("enter", _iface(engine, unit), near, FROM_AI, 1)]

    def test_a_human_players_own_order_walks(self, engine):
        player = engine.player(HUMAN)
        engine.tunnel(player, 50.0)
        engine.tunnel(player, 1950.0)
        unit = engine.unit(player, 0.0)
        left, *_ = engine.order(unit, MOVE, 2000.0, source=FROM_PLAYER)
        assert left == AI_DO_COMMAND_SWITCH
        assert engine.orders == []

    def test_a_unit_the_tunnel_refuses_walks(self, world):
        engine, *_, unit = world
        engine.accepts = False
        left, *_ = engine.order(unit, MOVE, 2000.0)
        assert left == AI_DO_COMMAND_SWITCH
        assert engine.orders == []
        assert engine.entry(unit) is None

    def test_other_orders_are_left_alone(self, world):
        engine, *_, unit = world
        left, *_ = engine.order(unit, ATTACK_OBJECT, 2000.0)
        assert left == AI_DO_COMMAND_SWITCH
        assert engine.orders == []

    def test_a_horde_member_is_left_to_its_horde(self, world):
        engine, player, *_, unit = world
        horde = engine.unit(player, 0.0, horde=True)
        engine.put_inside(unit, horde)
        left, *_ = engine.order(unit, MOVE, 2000.0)
        assert left == AI_DO_COMMAND_SWITCH
        assert engine.entry(unit) is None

    def test_the_switch_gets_the_registers_it_would_have_had(self, world):
        engine, *_, unit = world
        engine.accepts = False
        _left, after, before = engine.order(unit, MOVE, 2000.0)
        expected = dict(before)
        expected[UC_X86_REG_EAX] = MOVE  # the displaced `mov eax, [esi]`
        assert after == expected

    def test_the_tail_gets_the_registers_it_would_have_had(self, world):
        engine, *_, unit = world
        _left, after, before = engine.order(unit, MOVE, 2000.0)
        expected = dict(before)
        expected[UC_X86_REG_EAX] = MOVE
        assert after == expected

    def test_an_order_given_while_busy_goes_straight_to_the_switch(self, world):
        engine, *_, unit = world
        engine._write(engine.layout.busy, 1)
        left, *_ = engine.order(unit, MOVE, 2000.0)
        assert left == AI_DO_COMMAND_SWITCH
        assert engine.entry(unit) is None


class TestRepeatedOrders:
    def test_the_same_order_again_does_not_restart_the_enter(self, world):
        engine, *_, unit = world
        engine.order(unit, MOVE, 2000.0)
        left, *_ = engine.order(unit, MOVE, 2000.0)
        assert left == AI_DO_COMMAND_TAIL
        assert [o[0] for o in engine.orders] == ["enter"]

    def test_a_new_goal_routes_afresh(self, world):
        engine, *_, unit = world
        engine.order(unit, MOVE, 2000.0)
        engine.order(unit, MOVE, 2100.0)
        assert [o[0] for o in engine.orders] == ["enter", "enter"]
        assert engine.entry(unit)["goal"][0] == 2100.0

    def test_a_short_new_order_cancels_the_route(self, world):
        engine, *_, unit = world
        engine.order(unit, MOVE, 2000.0)
        left, *_ = engine.order(unit, MOVE, 30.0)
        assert left == AI_DO_COMMAND_SWITCH
        assert engine.entry(unit) is None

    def test_a_different_kind_of_order_cancels_the_route(self, world):
        engine, *_, unit = world
        engine.order(unit, MOVE, 2000.0)
        engine.order(unit, ATTACK_OBJECT, 0.0)
        assert engine.entry(unit) is None

    def test_an_idle_order_does_not(self, world):
        engine, *_, unit = world
        engine.order(unit, MOVE, 2000.0)
        engine.order(unit, IDLE, 0.0)
        assert engine.entry(unit) is not None


class TestInside:
    def test_an_order_to_a_unit_inside_is_recorded_and_taken_over(self, world):
        engine, _player, near, _far, unit = world
        engine.put_inside(unit, near)
        left, *_ = engine.order(unit, ATTACK_MOVE, 2000.0, shots=3)
        assert left == AI_DO_COMMAND_TAIL
        assert engine.orders == []
        entry = engine.entry(unit)
        assert (entry["phase"], entry["cmd"], entry["shots"]) == (PHASE_INSIDE, ATTACK_MOVE, 3)

    def test_the_pass_brings_it_out_at_the_tunnel_nearest_the_goal(self, world):
        engine, _player, near, far, unit = world
        engine.order(unit, MOVE, 2000.0)
        engine.put_inside(unit, near)
        engine.orders.clear()
        engine.tick()
        assert engine.orders == [("exit", _iface(engine, unit), far, FROM_AI, 1)]
        assert engine.entry(unit)["phase"] == PHASE_EXITING
        assert engine.entry(unit)["deadline"] == engine.frame + EXIT_RETRY_SECONDS * RATE

    def test_a_horde_comes_out_through_its_own_exit(self, engine):
        player = engine.player()
        near = engine.tunnel(player, 50.0)
        far = engine.tunnel(player, 1950.0)
        horde = engine.unit(player, 0.0, horde=True)
        engine.order(horde, MOVE, 2000.0)
        engine.put_inside(horde, near)
        engine.orders.clear()
        engine.tick()
        iface = engine.horde_ifaces[engine._read(horde + OBJECT_CONTAIN)]
        assert engine.orders == [("horde_exit", iface, far, FROM_AI, 1)]

    def test_a_repeated_order_inside_does_not_restart_the_exit(self, world):
        engine, _player, near, _far, unit = world
        engine.order(unit, MOVE, 2000.0)
        engine.put_inside(unit, near)
        engine.tick()
        engine.order(unit, MOVE, 2000.0)
        engine.frame += 1
        engine.orders.clear()
        engine.tick()
        assert engine.orders == []
        assert engine.entry(unit)["phase"] == PHASE_EXITING

    def test_the_pass_runs_once_a_frame(self, world):
        engine, _player, near, _far, unit = world
        engine.order(unit, MOVE, 2000.0)
        engine.put_inside(unit, near)
        engine.tick()
        engine._write(_TABLE + 0x18, PHASE_INSIDE)  # would exit again if the pass ran
        engine.orders.clear()
        engine.tick()
        assert engine.orders == []


class TestFallbacks:
    def _inside_and_exiting(self, world):
        engine, _player, near, _far, unit = world
        engine.order(unit, MOVE, 2000.0)
        engine.put_inside(unit, near)
        engine.tick()
        engine.orders.clear()
        return engine, near, unit

    def test_an_exit_is_not_repeated_before_its_time(self, world):
        engine, _near, unit = self._inside_and_exiting(world)
        engine.frame += EXIT_RETRY_SECONDS * RATE - 1
        engine.tick()
        assert engine.orders == []

    def test_a_stalled_exit_is_ordered_again(self, world):
        engine, _near, unit = self._inside_and_exiting(world)
        far = world[3]
        engine.frame += EXIT_RETRY_SECONDS * RATE
        engine.tick()
        assert [(o[0], o[2]) for o in engine.orders] == [("exit", far)]
        assert engine.entry(unit)["attempts"] == 1

    def test_after_two_retries_it_leaves_by_the_tunnel_it_is_in(self, world):
        engine, near, unit = self._inside_and_exiting(world)
        for _ in range(FALLBACK_ATTEMPT):
            engine.frame += EXIT_RETRY_SECONDS * RATE
            engine.tick()
        assert engine.orders[-1][2] == near
        assert engine.entry(unit)["attempts"] == FALLBACK_ATTEMPT

    def test_a_destroyed_goal_tunnel_gives_the_next_nearest(self, world):
        engine, player, near, far, unit = world
        engine.order(unit, MOVE, 2000.0)
        engine.put_inside(unit, near)
        engine.tunnels[player].remove(far)
        engine.orders.clear()
        engine.tick()
        assert engine.orders[-1][2] == near

    def test_a_unit_out_of_the_network_gets_its_order_back(self, world):
        engine, _near, unit = self._inside_and_exiting(world)
        engine.put_inside(unit, None)
        engine.frame += 1
        engine.tick()
        assert engine.orders == [("move", _iface(engine, unit), (2000.0, 0.0, 0.0), FROM_AI, 1)]
        assert engine.entry(unit) is None

    def test_an_attack_move_comes_back_as_one(self, world):
        engine, _player, near, _far, unit = world
        engine.order(unit, ATTACK_MOVE, 2000.0, shots=4)
        engine.put_inside(unit, near)
        engine.tick()
        engine.put_inside(unit, None)
        engine.frame += 1
        engine.orders.clear()
        engine.tick()
        assert engine.orders == [
            ("attack_move", _iface(engine, unit), (2000.0, 0.0, 0.0), 4, FROM_AI, 1)
        ]

    def test_a_unit_still_walking_in_is_left_alone(self, world):
        engine, *_, unit = world
        engine.order(unit, MOVE, 2000.0)
        engine.states[engine._read(unit + OBJECT_AI_UPDATE)] = 0x26
        engine.frame += 1
        engine.orders.clear()
        engine.tick()
        assert engine.orders == []
        assert engine.entry(unit)["phase"] == PHASE_ENTERING

    def test_a_failed_enter_falls_back_to_walking(self, world):
        engine, *_, unit = world
        engine.order(unit, MOVE, 2000.0)
        engine.frame += 1
        engine.orders.clear()
        engine.tick()  # idle outside: the enter has ended without it
        assert [o[0] for o in engine.orders] == ["move"]
        assert engine.entry(unit) is None

    def test_an_enter_that_takes_too_long_falls_back_to_walking(self, world):
        engine, *_, unit = world
        engine.order(unit, MOVE, 2000.0)
        engine.states[engine._read(unit + OBJECT_AI_UPDATE)] = 0x26
        engine.frame += ENTER_SECONDS * RATE
        engine.orders.clear()
        engine.tick()
        assert [o[0] for o in engine.orders] == ["move"]

    def test_a_dead_unit_loses_its_entry(self, world):
        engine, *_, unit = world
        engine.order(unit, MOVE, 2000.0)
        engine.kill(unit)
        engine.frame += 1
        engine.orders.clear()
        engine.tick()
        assert engine.orders == []
        assert engine._read(_TABLE) == 0

    def test_a_reset_forgets_everything(self, world):
        engine, *_, unit = world
        engine.order(unit, MOVE, 2000.0)
        engine.tick()
        engine._write(engine.layout.busy, 1)
        engine.call(engine.layout.reset)
        assert engine.uc.mem_read(_TABLE, SLOTS * ENTRY_SIZE) == bytes(SLOTS * ENTRY_SIZE)
        assert engine._read(engine.layout.last_tick) == 0xFFFFFFFF
        assert engine._read(engine.layout.busy) == 0

    def test_a_full_table_leaves_the_order_alone(self, world):
        engine, player, *_ = world
        units = [engine.unit(player, 0.0) for _ in range(SLOTS + 1)]
        for unit in units:
            engine.order(unit, MOVE, 2000.0)
        assert engine.entry(units[-1]) is None
        assert len(engine.orders) == SLOTS


class TestApplying:
    def test_apply_then_verify(self):
        data = ai_tunnel_routing_image()
        AiTunnelRoutingPatch().apply(data)
        assert AiTunnelRoutingPatch().verify(data) == []

    def test_the_hook_jumps_to_the_dispatch(self):
        data = ai_tunnel_routing_image()
        AiTunnelRoutingPatch().apply(data)
        base = find_section(data, SECTION_NAME)[0]
        off = va_to_offset(data, HOOK_VA)
        assert data[off] == 0xE9
        assert HOOK_VA + 5 + struct.unpack_from("<i", data, off + 1)[0] == Layout(base).dispatch
        assert data[off + 5] == 0x90

    def test_the_vtable_slots_point_into_the_cave(self):
        data = ai_tunnel_routing_image()
        AiTunnelRoutingPatch().apply(data)
        layout = Layout(find_section(data, SECTION_NAME)[0])

        def slot(va: int) -> int:
            return struct.unpack_from("<I", data, va_to_offset(data, va))[0]

        assert slot(TUNNEL_CONTAIN_UPDATE_VTABLE_SLOT) == layout.tick
        assert all(slot(va) == layout.reset for va in GAME_LOGIC_RESET_VTABLE_SLOTS)

    def test_detect_reads_the_transit_cost_back(self):
        data = ai_tunnel_routing_image()
        AiTunnelRoutingPatch(transit_cost=350).apply(data)
        found = AiTunnelRoutingPatch.detect(data)
        assert found is not None
        assert found.options() == {"transit_cost": 350}
        assert AiTunnelRoutingPatch(transit_cost=200).verify(data) != []

    def test_it_is_not_detected_unpatched(self):
        assert AiTunnelRoutingPatch.detect(ai_tunnel_routing_image()) is None

    def test_refuses_to_apply_twice(self):
        data = ai_tunnel_routing_image()
        AiTunnelRoutingPatch().apply(data)
        with pytest.raises(ValueError):
            AiTunnelRoutingPatch().apply(data)

    @pytest.mark.parametrize("va", sorted(ANCHORS))
    def test_a_moved_anchor_refuses_to_apply(self, va: int):
        data = ai_tunnel_routing_image()
        data[va_to_offset(data, va)] ^= 0xFF
        with pytest.raises(ValueError):
            AiTunnelRoutingPatch().apply(data)

    @pytest.mark.parametrize("va", sorted(VTABLE_SLOTS))
    def test_a_taken_vtable_slot_refuses_to_apply(self, va: int):
        data = ai_tunnel_routing_image()
        data[va_to_offset(data, va)] ^= 0xFF
        with pytest.raises(ValueError):
            AiTunnelRoutingPatch().apply(data)

    def test_a_transit_cost_out_of_range_is_refused(self):
        with pytest.raises(ValueError):
            AiTunnelRoutingPatch(transit_cost=-1)

    def test_the_section_name_survives_the_eight_byte_pe_field(self):
        assert len(SECTION_NAME) <= 8


class TestRegistration:
    def test_it_is_offered_on_the_cli(self):
        assert PATCHES["ai-tunnel-routing"] is AiTunnelRoutingPatch

    def test_it_is_settled(self):
        assert not AiTunnelRoutingPatch.experimental

    def test_it_records_its_parameter(self):
        assert AiTunnelRoutingPatch().options() == {"transit_cost": 200}


class TestTheRealBinary:
    """The synthetic image proves the patch is self-consistent; only a real `game.dat` proves the
    addresses are right. Skipped where there is none."""

    @staticmethod
    @pytest.fixture(scope="class")
    def game_dat() -> bytes:
        if not _GAME_DAT.exists():
            pytest.skip(f"no {_GAME_DAT}")
        return _GAME_DAT.read_bytes()

    @staticmethod
    def _at(data: bytes, va: int, size: int) -> bytes:
        off = va_to_offset(data, va)
        return bytes(data[off : off + size])

    def test_every_anchor_holds_what_the_patch_says_it_holds(self, game_dat: bytes) -> None:
        for va, expected in ANCHORS.items():
            assert self._at(game_dat, va, len(expected)) == expected, hex(va)

    def test_every_vtable_slot_holds_its_stock_routine(self, game_dat: bytes) -> None:
        for va, stock in VTABLE_SLOTS.items():
            assert self._at(game_dat, va, 4) == struct.pack("<I", stock), hex(va)

    def test_the_hook_holds_the_dispatch(self, game_dat: bytes) -> None:
        assert self._at(game_dat, AI_DO_COMMAND_DISPATCH, len(HOOK_ORIGINAL)) == HOOK_ORIGINAL

    def test_apply_and_verify_on_the_real_thing(self, game_dat: bytes, tmp_path: Path) -> None:
        source = tmp_path / "game.dat"
        source.write_bytes(game_dat)
        out = tmp_path / "patched.dat"
        apply_patches(source, [AiTunnelRoutingPatch()], output=out)
        assert AiTunnelRoutingPatch().verify(out.read_bytes()) == []

    def test_it_is_not_detected_in_the_unpatched_binary(self, game_dat: bytes) -> None:
        assert AiTunnelRoutingPatch.detect(game_dat) is None
