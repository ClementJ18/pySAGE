"""Tests for the gate-close repath patch.

The cave is hand-assembled x86 with a float geometry test inside a double loop, so it is checked
three ways: disassembled back and read, run under an emulator against a stand-in object table, and
- when a `game.dat` sits at the repo root - applied to the real binary.
"""

from __future__ import annotations

import faulthandler
import struct
from pathlib import Path

import pytest

from sage_patch.addresses import (
    AI_CURRENT_STATE_ID,
    AI_DESTROY_PATH,
    AI_PATH_OFFSET,
    AI_STATE_NO_PATH_UNSAFE,
    AI_WAITING_FOR_PATH_OFFSET,
    GAME_LOGIC_OBJECT_BUCKETS_BEGIN,
    GAME_LOGIC_OBJECT_BUCKETS_END,
    GATE_CLOSE_EPILOGUE,
    GATE_CLOSE_FOR_PATHING,
    OBJECT_AI_UPDATE,
    OBJECT_BOUNDING_CIRCLE_RADIUS,
    OBJECT_HASH_ENTRY_NEXT,
    OBJECT_HASH_ENTRY_OBJECT,
    OBJECT_POSITION,
    PATH_HEAD_OFFSET,
    PATH_NODE_NEXT_OFFSET,
    PATH_NODE_POS_OFFSET,
    PATHFINDER_ADD_OBJECT,
    THE_GAME_LOGIC,
)
from sage_patch.patcher import apply_patches
from sage_patch.patches.gate_close_repath import (
    ANCHORS,
    HOOK_ORIGINAL,
    HOOK_VA,
    SECTION_NAME,
    GateCloseRepathPatch,
    build_code,
)
from sage_patch.registry import PATCHES
from sage_patch.utils import find_section, va_to_offset

from .synthetic import gate_close_repath_image

try:
    from unicorn import UC_ARCH_X86, UC_HOOK_CODE, UC_MODE_32, Uc, x86_const
except ImportError:  # the emulator tests skip; the static and real-binary ones still run
    Uc = None

BASE = 0x00F00000

_GAME_DAT = Path(__file__).resolve().parents[2] / "game.dat"

#: `GATE_CLOSE_FOR_PATHING` runs to the `ret 4` at 0x0089CA81.
_CLOSE_SIZE = 0x0089CA84 - GATE_CLOSE_FOR_PATHING


def disassemble(base: int = BASE):
    capstone = pytest.importorskip("capstone")
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    return list(md.disasm(build_code(base), base))


def _target(insn) -> int:
    return int(insn.op_str, 16)


class TestTheCave:
    def test_it_disassembles_cleanly_to_its_end(self):
        """Capstone stopping early means an invalid encoding, which would be a crash in-game."""
        insns = disassemble()
        assert sum(i.size for i in insns) == len(build_code(BASE))

    def test_it_makes_the_displaced_call_first_with_the_gate(self):
        """The gate has to be back in the pathfind map before anything else happens - it is the
        call the hook replaced, and it is what the re-planned paths are planned against."""
        push, call = disassemble()[:2]
        assert (push.mnemonic, push.op_str) == ("push", "dword ptr [esp + 4]")
        assert call.mnemonic == "call" and _target(call) == PATHFINDER_ADD_OBJECT

    def test_it_calls_only_the_three_engine_functions(self):
        calls = [_target(i) for i in disassemble() if i.mnemonic == "call"]
        assert calls == [PATHFINDER_ADD_OBJECT, AI_CURRENT_STATE_ID, AI_DESTROY_PATH]

    def test_the_state_exclusion_guards_the_destroy(self):
        insns = disassemble()
        destroy = next(
            n for n, i in enumerate(insns) if i.mnemonic == "call" and _target(i) == AI_DESTROY_PATH
        )
        cmp, je = insns[destroy - 2], insns[destroy - 1]
        assert (cmp.mnemonic, cmp.op_str) == ("cmp", f"eax, {AI_STATE_NO_PATH_UNSAFE:#x}")
        assert je.mnemonic == "je"

    def test_it_saves_and_restores_the_callee_saved_registers(self):
        insns = disassemble()
        pushes = [i.op_str for i in insns[2:6]]
        pops = [i.op_str for i in insns[-5:-1]]
        assert pushes == ["ebx", "esi", "edi", "ebp"]
        assert pops == list(reversed(pushes))

    def test_it_reads_the_gate_from_past_the_saves(self):
        """Four pushes on top of the return address put the caller's argument at `esp+0x14`."""
        load = disassemble()[6]
        assert (load.mnemonic, load.op_str) == ("mov", "ebp, dword ptr [esp + 0x14]")

    def test_it_returns_as_the_replaced_callee_did(self):
        last = disassemble()[-1]
        assert (last.mnemonic, last.op_str) == ("ret", "4")

    def test_every_branch_stays_inside_the_cave(self):
        end = BASE + len(build_code(BASE))
        for insn in disassemble():
            if insn.mnemonic.startswith("j"):
                assert BASE <= _target(insn) < end, insn

    def test_it_relocates_with_its_section(self):
        assert build_code(BASE) != build_code(BASE + 0x1000)


# --- the emulator -------------------------------------------------------------------------------

_PAGE = 0x1000
_HEAP = 0x20000000
_STACK = 0x30000000
_GAME_LOGIC = _HEAP
_BUCKETS = _HEAP + 0x100
_BUCKET_COUNT = 8
_PATHFINDER = 0x50415448
_SENTINEL = 0x0DEAD000
_SAVED = {"ebx": 0xBBBBBBBB, "esi": 0x51515151, "edi": 0xD1D1D1D1, "ebp": 0xEBEBEBEB}

_GATE_POS = (100.0, 100.0)
_GATE_RADIUS = 40.0
_UNIT_RADIUS = 5.0
_REACH = _GATE_RADIUS + _UNIT_RADIUS


class _Unit:
    def __init__(
        self,
        name: str,
        path: list[tuple[float, float]] | None,
        *,
        bucket: int,
        waiting: bool = False,
        state: int = 0,
        has_ai: bool = True,
        empty_path: bool = False,
    ):
        self.name = name
        self.path = path
        self.bucket = bucket
        self.waiting = waiting
        self.state = state
        self.has_ai = has_ai
        self.empty_path = empty_path


class _World:
    """One emulated close: the hook site runs with the world below in memory, and the three engine
    functions are stubs that record what they were handed."""

    def __init__(self, units: list[_Unit], *, gate_in_table: bool = True):
        if Uc is None:
            pytest.skip("the emulator harness needs unicorn")
        self.r = x86_const
        data = gate_close_repath_image()
        GateCloseRepathPatch().apply(data)
        cave, cave_off, cave_size = find_section(data, SECTION_NAME)

        self.uc = uc = Uc(UC_ARCH_X86, UC_MODE_32)
        pages = {cave & ~0xFFF, HOOK_VA & ~0xFFF, THE_GAME_LOGIC & ~0xFFF, _SENTINEL}
        pages |= {
            va & ~0xFFF for va in (PATHFINDER_ADD_OBJECT, AI_CURRENT_STATE_ID, AI_DESTROY_PATH)
        }
        pages |= set(range(cave & ~0xFFF, cave + cave_size, _PAGE))
        pages |= set(range(_HEAP, _HEAP + 0x10000, _PAGE))
        pages |= set(range(_STACK, _STACK + 0x2000, _PAGE))
        was_enabled = faulthandler.is_enabled()
        faulthandler.disable()
        try:
            for page in sorted(pages):
                uc.mem_map(page, _PAGE)
        finally:
            if was_enabled:
                faulthandler.enable()

        uc.mem_write(cave, bytes(data[cave_off : cave_off + cave_size]))
        site = HOOK_VA & ~0xFFF
        site_off = va_to_offset(data, site)
        uc.mem_write(site, bytes(data[site_off : site_off + _PAGE]))

        self.added: list[tuple[int, int]] = []
        self.destroyed: list[int] = []
        self.state_queries: list[int] = []
        self.epilogue_regs: dict[str, int] = {}
        stubs = {
            PATHFINDER_ADD_OBJECT: b"\xc2\x04\x00",
            AI_CURRENT_STATE_ID: b"\xc3",
            AI_DESTROY_PATH: b"\xc3",
        }
        for va, stub in stubs.items():
            uc.mem_write(va, stub)
            uc.hook_add(UC_HOOK_CODE, self._stub, begin=va, end=va)
        uc.hook_add(
            UC_HOOK_CODE, self._epilogue, begin=GATE_CLOSE_EPILOGUE, end=GATE_CLOSE_EPILOGUE
        )

        self._cursor = _HEAP + 0x1000
        self.gate = self._alloc(0x300)
        self._put(self.gate + OBJECT_POSITION, *_GATE_POS, fmt="f")
        self._put(self.gate + OBJECT_BOUNDING_CIRCLE_RADIUS, _GATE_RADIUS, fmt="f")
        self._put(THE_GAME_LOGIC, _GAME_LOGIC)
        self._put(_GAME_LOGIC + GAME_LOGIC_OBJECT_BUCKETS_BEGIN, _BUCKETS)
        self._put(_GAME_LOGIC + GAME_LOGIC_OBJECT_BUCKETS_END, _BUCKETS + 4 * _BUCKET_COUNT)

        self.ai_of: dict[str, int] = {}
        self._state_of_ai: dict[int, int] = {}
        chains: dict[int, list[int]] = {}
        if gate_in_table:
            gate_ai = self._ai([(0.0, 100.0), (200.0, 100.0)], waiting=False)
            self._put(self.gate + OBJECT_AI_UPDATE, gate_ai)
            self.ai_of["gate"] = gate_ai
            chains.setdefault(0, []).append(self.gate)
        for unit in units:
            obj = self._alloc(0x300)
            self._put(obj + OBJECT_BOUNDING_CIRCLE_RADIUS, _UNIT_RADIUS, fmt="f")
            if unit.has_ai:
                ai = self._ai(unit.path, waiting=unit.waiting, empty=unit.empty_path)
                self._put(obj + OBJECT_AI_UPDATE, ai)
                self.ai_of[unit.name] = ai
                self._state_of_ai[ai] = unit.state
            chains.setdefault(unit.bucket, []).append(obj)
        for bucket, objects in chains.items():
            following = 0
            for obj in reversed(objects):
                entry = self._alloc(12)
                self._put(entry + OBJECT_HASH_ENTRY_NEXT, following)
                self._put(entry + OBJECT_HASH_ENTRY_OBJECT, obj)
                following = entry
            self._put(_BUCKETS + 4 * bucket, following)

    def _alloc(self, size: int) -> int:
        va = self._cursor
        self._cursor += (size + 0xF) & ~0xF
        return va

    def _put(self, va: int, *values, fmt: str = "I") -> None:
        self.uc.mem_write(va, struct.pack(f"<{len(values)}{fmt}", *values))

    def _ai(
        self, path: list[tuple[float, float]] | None, *, waiting: bool, empty: bool = False
    ) -> int:
        ai = self._alloc(0x400)
        self.uc.mem_write(ai + AI_WAITING_FOR_PATH_OFFSET, bytes([waiting]))
        if path is None:
            return ai
        header = self._alloc(0x28)
        self._put(ai + AI_PATH_OFFSET, header)
        if empty:
            return ai
        following = 0
        for x, y in reversed(path):
            node = self._alloc(0x24)
            self._put(node + PATH_NODE_NEXT_OFFSET, following)
            self._put(node + PATH_NODE_POS_OFFSET, x, y, 0.0, fmt="f")
            following = node
        self._put(header + PATH_HEAD_OFFSET, following)
        return ai

    def _reg(self, name: str) -> int:
        return self.uc.reg_read(getattr(self.r, f"UC_X86_REG_{name.upper()}"))

    def _stub(self, uc, address, _size, _user) -> None:
        ecx = self._reg("ecx")
        esp = self._reg("esp")
        if address == PATHFINDER_ADD_OBJECT:
            (arg,) = struct.unpack("<I", uc.mem_read(esp + 4, 4))
            self.added.append((ecx, arg))
        elif address == AI_CURRENT_STATE_ID:
            self.state_queries.append(ecx)
            uc.reg_write(self.r.UC_X86_REG_EAX, self._state_of_ai[ecx])
        elif address == AI_DESTROY_PATH:
            self.destroyed.append(ecx)
            # destroyPath's contract: eax, ecx and edx are the caller's to lose.
            for reg in ("EAX", "ECX", "EDX"):
                uc.reg_write(getattr(self.r, f"UC_X86_REG_{reg}"), 0xCCCCCCCC)

    def _epilogue(self, _uc, _address, _size, _user) -> None:
        self.epilogue_regs = {name: self._reg(name) for name in ("ebx", "esi", "edi", "ebp", "esp")}

    def close(self) -> _World:
        """Run from the hook site to close-for-pathing's return, as the real function would."""
        r = self.r
        esp = _STACK + 0x1000
        # What close-for-pathing's frame holds at the hook: the gate pushed for the call, the four
        # registers the epilogue pops, the return address and the function's own argument.
        frame = [
            self.gate,
            _SAVED["ebp"],
            _SAVED["ebx"],
            _SAVED["edi"],
            _SAVED["esi"],
            _SENTINEL,
            1,
        ]
        self._put(esp, *frame)
        self.uc.reg_write(r.UC_X86_REG_ESP, esp)
        self.uc.reg_write(r.UC_X86_REG_ECX, _PATHFINDER)
        # At the hook `ebx` is the gate, as close-for-pathing loaded it; the others are live values
        # the cave must hand back unchanged.
        self.uc.reg_write(r.UC_X86_REG_EBX, self.gate)
        self.uc.reg_write(r.UC_X86_REG_ESI, 0x5E5E5E5E)
        self.uc.reg_write(r.UC_X86_REG_EDI, 0xD0D0D0D0)
        self.uc.reg_write(r.UC_X86_REG_EBP, 0xB0B0B0B0)
        self.uc.emu_start(HOOK_VA, _SENTINEL, count=200_000)
        self.final_esp = self._reg("esp")
        self.final_regs = {name: self._reg(name) for name in ("ebx", "esi", "edi", "ebp")}
        self.frame_esp = esp
        return self

    def dropped(self) -> set[str]:
        names = {ai: name for name, ai in self.ai_of.items()}
        return {names[ai] for ai in self.destroyed}


def _run(*units: _Unit, **kwargs) -> _World:
    return _World(list(units), **kwargs).close()


class TestUnderEmulation:
    def test_the_gate_goes_back_into_the_map_first(self):
        world = _run(_Unit("through", [(0.0, 100.0), (200.0, 100.0)], bucket=1))
        assert world.added == [(_PATHFINDER, world.gate)]

    def test_the_stack_and_registers_come_back_as_the_function_left_them(self):
        world = _run(_Unit("through", [(0.0, 100.0), (200.0, 100.0)], bucket=1))
        assert world.epilogue_regs["esp"] == world.frame_esp + 4  # `ret 4` took the gate
        assert world.epilogue_regs["ebx"] == world.gate
        assert (
            world.epilogue_regs["esi"],
            world.epilogue_regs["edi"],
            world.epilogue_regs["ebp"],
        ) == (
            0x5E5E5E5E,
            0xD0D0D0D0,
            0xB0B0B0B0,
        )
        assert world.final_esp == world.frame_esp + 4 * 7
        assert world.final_regs == _SAVED

    def test_a_path_through_the_gate_is_dropped(self):
        assert _run(_Unit("through", [(0.0, 100.0), (200.0, 100.0)], bucket=1)).dropped() == {
            "through"
        }

    def test_a_path_that_stays_clear_is_kept(self):
        assert _run(_Unit("clear", [(0.0, 0.0), (0.0, 200.0)], bucket=1)).dropped() == set()

    @pytest.mark.parametrize(("offset", "dropped"), [(_REACH - 1.0, True), (_REACH + 1.0, False)])
    def test_the_reach_is_both_radii(self, offset: float, dropped: bool):
        """A segment passing the gate at exactly the two radii apart is the boundary."""
        y = _GATE_POS[1] + offset
        world = _run(_Unit("edge", [(0.0, y), (200.0, y)], bucket=1))
        assert world.dropped() == ({"edge"} if dropped else set())

    def test_a_path_ending_in_the_gate_is_dropped(self):
        """The closest point is the segment's far end: the `wd >= dd` arm."""
        world = _run(_Unit("ends", [(300.0, 300.0), (160.0, 100.0), (130.0, 100.0)], bucket=1))
        assert world.dropped() == {"ends"}

    def test_a_path_starting_past_the_gate_is_kept(self):
        """The closest point is the segment's near end and it is out of reach: the `wd <= 0` arm."""
        world = _run(_Unit("away", [(200.0, 100.0), (400.0, 100.0)], bucket=1))
        assert world.dropped() == set()

    def test_a_one_node_path_is_tested_as_a_point(self):
        near = _Unit("near", [(110.0, 105.0)], bucket=1)
        far = _Unit("far", [(300.0, 105.0)], bucket=2)
        assert _run(near, far).dropped() == {"near"}

    def test_a_later_segment_is_found(self):
        world = _run(_Unit("turns", [(0.0, 0.0), (0.0, 100.0), (200.0, 100.0)], bucket=1))
        assert world.dropped() == {"turns"}

    def test_a_unit_waiting_for_the_pathfinder_is_left_alone(self):
        world = _run(_Unit("waiting", [(0.0, 100.0), (200.0, 100.0)], bucket=1, waiting=True))
        assert world.dropped() == set()

    def test_the_unsafe_state_is_left_alone(self):
        unsafe = _Unit(
            "unsafe", [(0.0, 100.0), (200.0, 100.0)], bucket=1, state=AI_STATE_NO_PATH_UNSAFE
        )
        world = _run(unsafe)
        assert world.dropped() == set()
        assert world.state_queries == [world.ai_of["unsafe"]]

    def test_objects_without_ai_or_path_are_skipped(self):
        world = _run(
            _Unit("no_ai", None, bucket=1, has_ai=False),
            _Unit("no_path", None, bucket=2),
            _Unit("no_nodes", [], bucket=3, empty_path=True),
        )
        assert world.dropped() == set()
        assert world.state_queries == []

    def test_the_gate_is_not_its_own_victim(self):
        assert "gate" not in _run(gate_in_table=True).dropped()

    def test_every_bucket_and_every_chain_entry_is_visited(self):
        through = [(0.0, 100.0), (200.0, 100.0)]
        units = [
            _Unit("head", through, bucket=0),
            _Unit("chained", through, bucket=0),
            _Unit("third", through, bucket=0),
            _Unit("last_bucket", through, bucket=_BUCKET_COUNT - 1),
            _Unit("clear", [(0.0, 0.0), (0.0, 200.0)], bucket=4),
        ]
        world = _run(*units)
        assert world.dropped() == {"head", "chained", "third", "last_bucket"}
        assert len(world.destroyed) == 4


# --- applying it --------------------------------------------------------------------------------


class TestApply:
    def test_apply_then_verify(self):
        data = gate_close_repath_image()
        GateCloseRepathPatch().apply(data)
        assert GateCloseRepathPatch().verify(data) == []

    def test_the_hook_is_one_call_into_the_cave(self):
        data = gate_close_repath_image()
        GateCloseRepathPatch().apply(data)
        section_va, _, _ = find_section(data, SECTION_NAME)
        off = va_to_offset(data, HOOK_VA)
        assert data[off] == 0xE8
        assert HOOK_VA + 5 + struct.unpack_from("<i", data, off + 1)[0] == section_va

    def test_nothing_but_the_hooked_call_changes_in_the_image(self):
        data = gate_close_repath_image()
        GateCloseRepathPatch().apply(data)
        for va, expected in ANCHORS.items():
            off = va_to_offset(data, va)
            assert bytes(data[off : off + len(expected)]) == expected

    def test_the_cave_holds_the_expected_code(self):
        data = gate_close_repath_image()
        GateCloseRepathPatch().apply(data)
        section_va, section_off, _ = find_section(data, SECTION_NAME)
        code = build_code(section_va)
        assert bytes(data[section_off : section_off + len(code)]) == code

    def test_the_section_name_survives_the_eight_byte_pe_field(self):
        assert len(SECTION_NAME) <= 8

    def test_refuses_to_apply_twice(self):
        data = gate_close_repath_image()
        GateCloseRepathPatch().apply(data)
        with pytest.raises(ValueError):
            GateCloseRepathPatch().apply(data)

    @pytest.mark.parametrize("va", sorted(ANCHORS))
    def test_a_moved_anchor_refuses_to_apply(self, va: int):
        data = gate_close_repath_image()
        off = va_to_offset(data, va)
        data[off] ^= 0xFF
        with pytest.raises(ValueError):
            GateCloseRepathPatch().apply(data)

    def test_an_unpatched_image_does_not_verify(self):
        assert GateCloseRepathPatch().verify(gate_close_repath_image()) != []


class TestRegistration:
    def test_it_is_offered_on_the_cli(self):
        assert PATCHES["gate-close-repath"] is GateCloseRepathPatch

    def test_it_is_settled(self):
        assert not GateCloseRepathPatch.experimental

    def test_it_declares_no_parameters(self):
        assert GateCloseRepathPatch().options() == {}


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

    def test_the_hook_holds_the_re_add_call(self, game_dat: bytes) -> None:
        assert self._at(game_dat, HOOK_VA, len(HOOK_ORIGINAL)) == HOOK_ORIGINAL
        rel = struct.unpack("<i", HOOK_ORIGINAL[1:])[0]
        assert HOOK_VA + 5 + rel == PATHFINDER_ADD_OBJECT

    def test_the_hook_is_inside_close_for_pathing(self) -> None:
        assert GATE_CLOSE_FOR_PATHING < HOOK_VA < GATE_CLOSE_FOR_PATHING + _CLOSE_SIZE

    def test_nothing_branches_into_the_hooked_call(self, game_dat: bytes) -> None:
        capstone = pytest.importorskip("capstone")
        md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
        body = self._at(game_dat, GATE_CLOSE_FOR_PATHING, _CLOSE_SIZE)
        for insn in md.disasm(body, GATE_CLOSE_FOR_PATHING):
            if insn.mnemonic.startswith("j") and insn.op_str.startswith("0x"):
                target = int(insn.op_str, 16)
                assert not HOOK_VA < target < HOOK_VA + len(HOOK_ORIGINAL), insn

    def test_apply_and_verify_on_the_real_thing(self, game_dat: bytes, tmp_path: Path) -> None:
        source = tmp_path / "game.dat"
        source.write_bytes(game_dat)
        out = tmp_path / "patched.dat"
        apply_patches(source, [GateCloseRepathPatch()], output=out)
        assert GateCloseRepathPatch().verify(out.read_bytes()) == []

    def test_it_is_not_detected_in_the_unpatched_binary(self, game_dat: bytes) -> None:
        assert GateCloseRepathPatch.detect(game_dat) is None
