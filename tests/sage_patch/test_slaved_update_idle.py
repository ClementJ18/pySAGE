"""Data-free PE checks and execution of generated x86 with synthetic engine objects."""

from __future__ import annotations

import argparse
import struct
from pathlib import Path

import pytest

from sage_patch import SlavedUpdateIdlePatch
from sage_patch.addresses import (
    GAME_LOGIC_FRAME,
    SLAVED_IDLE_ANCHORS,
    SLAVED_IDLE_CTOR,
    SLAVED_IDLE_DTOR,
    SLAVED_IDLE_FALLTHROUGH,
    SLAVED_IDLE_GUARD,
    SLAVED_IDLE_HOOK,
    SLAVED_IDLE_HOOKS,
    SLAVED_IDLE_XFER,
    THE_GAME_LOGIC,
)
from sage_patch.patches.slaved_update_idle import (
    CODE_OFFSET,
    SECTION_NAME,
    TABLE_OFFSET,
    build_code,
    milliseconds_to_logic_frames,
)
from sage_patch.registry import PATCHES
from sage_patch.utils import file_offset, find_section
from tests.sage_patch.test_patching import _tiny_pe


def image() -> bytearray:
    b = _tiny_pe()
    size = 0xAD0000
    b.extend(bytes(size))
    struct.pack_into("<IIII", b, 0x178 + 8, size, 0x1000, size, 0x200)
    struct.pack_into("<I", b, 0x98 + 56, size + 0x1000)
    for va, old in (SLAVED_IDLE_ANCHORS | SLAVED_IDLE_HOOKS).items():
        off = file_offset(b, va)
        b[off : off + len(old)] = old
    return b


def test_apply_detection_options_cli_and_conflicts() -> None:
    b = image()
    p = SlavedUpdateIdlePatch(10000, 25000, 2500, 9000)
    parser = argparse.ArgumentParser()
    p.add_cli_arguments(parser)
    assert (
        p.from_cli_args(
            parser.parse_args(
                [
                    "--idle-min-ms",
                    "2500",
                    "--idle-max-ms",
                    "9000",
                    "--wander-min-ms",
                    "10000",
                    "--wander-max-ms",
                    "25000",
                ]
            )
        ).options()
        == p.options()
    )
    assert PATCHES[p.name] is type(p)
    assert p.detect(b) is None
    p.apply(b)
    assert p.verify(b) == []
    detected = p.detect(b)
    assert detected is not None and detected.options() == p.options()
    assert SlavedUpdateIdlePatch().verify(b)
    before = bytes(b)
    with pytest.raises(ValueError):
        p.apply(b)
    assert b == before
    section = find_section(b, SECTION_NAME)
    assert section is not None
    b[section[1] + CODE_OFFSET + 20] ^= 1
    assert p.verify(b) and p.detect(b) is None


@pytest.mark.parametrize("va", [*SLAVED_IDLE_ANCHORS, *SLAVED_IDLE_HOOKS])
def test_contract_failure_is_atomic(va: int) -> None:
    b = image()
    b[file_offset(b, va)] ^= 1
    before = bytes(b)
    with pytest.raises(ValueError, match="contract mismatch"):
        SlavedUpdateIdlePatch().apply(b)
    assert b == before


@pytest.mark.parametrize("value", [0, -1, True, 1.5, "10", 86400001, 2**31, 2**32])
@pytest.mark.parametrize("name", ["wander_min_ms", "wander_max_ms", "idle_min_ms", "idle_max_ms"])
def test_bad_intervals(name: str, value: object) -> None:
    with pytest.raises(ValueError):
        SlavedUpdateIdlePatch(**{name: value})


def test_reversed_intervals() -> None:
    with pytest.raises(ValueError):
        SlavedUpdateIdlePatch(idle_min_ms=20, idle_max_ms=10)
    with pytest.raises(ValueError):
        SlavedUpdateIdlePatch(wander_min_ms=20, wander_max_ms=10)


@pytest.mark.parametrize("base", [0xF00000, 0x1800000])
def test_disassembly_targets(base: int) -> None:
    cs = pytest.importorskip("capstone")
    code, hooks = build_code(base, (6000, 14191, 3000, 7095))
    insns = list(cs.Cs(cs.CS_ARCH_X86, cs.CS_MODE_32).disasm(code, base + CODE_OFFSET))
    assert sum(i.size for i in insns) == len(code)
    starts = {i.address for i in insns}
    targets = {
        int(i.op_str, 16)
        for i in insns
        if i.mnemonic.startswith(("j", "call")) and i.op_str.startswith("0x")
    }
    assert targets - starts == {
        SLAVED_IDLE_GUARD,
        SLAVED_IDLE_FALLTHROUGH,
        *(
            va + len(SLAVED_IDLE_HOOKS[va])
            for va in (SLAVED_IDLE_CTOR, SLAVED_IDLE_DTOR, SLAVED_IDLE_XFER)
        ),
    }
    assert set(hooks.values()) <= starts


class World:
    def __init__(
        self,
        intervals: tuple[int, int, int, int] = (2000, 2000, 1000, 1000),
        shift: int = 0,
        cave_base: int = 0xF00000,
    ) -> None:
        uc = pytest.importorskip("unicorn")
        self.r = pytest.importorskip("unicorn.x86_const")
        self.u = uc.Uc(uc.UC_ARCH_X86, uc.UC_MODE_32)
        self.base = cave_base
        self.shift = shift
        self.logic = 0x101E0000 + shift
        code, self.hooks = build_code(self.base, intervals)
        for address, size in [
            (0x400000, 0x1000),
            (0x5E3000, 0x1000),
            (0x8A4000, 0x3000),
            (THE_GAME_LOGIC & ~0xFFF, 0x1000),
            (self.base, 0x22000),
            (0x10000000, 0x200000),
            (0x20000000, 0x10000),
        ]:
            self.u.mem_map(address, size)
        self.u.mem_write(self.base + CODE_OFFSET, code)
        self.write(THE_GAME_LOGIC, self.logic)
        self.u.mem_write(0x400100, b"\xc3")
        self.now = 0
        self.frame_reads = 0
        self.loading = False
        self.exit = 0
        self.stops = {
            SLAVED_IDLE_GUARD,
            SLAVED_IDLE_FALLTHROUGH,
            *(
                v + len(SLAVED_IDLE_HOOKS[v])
                for v in (SLAVED_IDLE_CTOR, SLAVED_IDLE_DTOR, SLAVED_IDLE_XFER)
            ),
        }
        self.u.hook_add(uc.UC_HOOK_CODE, self.on_code)
        self.u.hook_add(uc.UC_HOOK_MEM_READ, self.on_read)

    @property
    def now(self) -> int:
        return self.read(self.logic + GAME_LOGIC_FRAME)

    @now.setter
    def now(self, frame: int) -> None:
        self.write(self.logic + GAME_LOGIC_FRAME, frame)

    def on_read(
        self, u: object, access: int, address: int, size: int, value: int, user: object
    ) -> None:
        if address == self.logic + GAME_LOGIC_FRAME:
            self.frame_reads += 1

    def write(self, address: int, value: int) -> None:
        self.u.mem_write(address, struct.pack("<I", value & 0xFFFFFFFF))

    def read(self, address: int) -> int:
        return struct.unpack("<I", self.u.mem_read(address, 4))[0]

    def on_code(self, u: object, address: int, size: int, user: object) -> None:
        if address in self.stops:
            self.exit = address
            self.u.emu_stop()
        elif address == 0x400100:
            self.u.reg_write(self.r.UC_X86_REG_EAX, int(self.loading))
            self.u.reg_write(self.r.UC_X86_REG_ECX, 0xDEAD)
            self.u.reg_write(self.r.UC_X86_REG_EDX, 0xBEEF)
            self.u.reg_write(self.r.UC_X86_REG_XMM0, 0)

    def run(
        self,
        instance: int = 0x10000000,
        oid: int = 5,
        flags: int = 0x202,
        wander: int = 90,
        site: int = SLAVED_IDLE_HOOK,
    ) -> int:
        r = self.r
        ebp = 0x20008000 + (self.shift & 0x1000)
        esp = ebp - 0x100
        data = 0x101F0000 + self.shift
        owner = 0x101F1000 + self.shift
        self.write(ebp - 12, data)
        self.write(ebp - 4, owner)
        self.write(ebp - 8, instance + 16)
        self.write(data + 16, wander)
        self.write(owner + 0x74, oid)
        self.write(esp + 4, 0x101F2000)
        self.write(0x101F2000, 0x101F2100)
        self.write(0x101F2104, 0x400100)
        regs = {
            r.UC_X86_REG_EAX: 0x1234,
            r.UC_X86_REG_EBX: 0x5678,
            r.UC_X86_REG_ECX: instance,
            r.UC_X86_REG_EDX: 0xABCD,
            r.UC_X86_REG_ESI: 0x4567,
            r.UC_X86_REG_EDI: 0x9876,
            r.UC_X86_REG_EBP: ebp,
            r.UC_X86_REG_ESP: esp,
            r.UC_X86_REG_EFLAGS: flags,
            r.UC_X86_REG_XMM0: 0x123456789ABCDEF,
        }
        for reg, value in regs.items():
            self.u.reg_write(reg, value)
        self.exit = 0
        self.u.emu_start(self.hooks[site], 0, count=100000)
        assert self.exit
        if site == SLAVED_IDLE_HOOK:
            if self.exit == SLAVED_IDLE_FALLTHROUGH:
                regs[r.UC_X86_REG_EAX] = data
        elif site == SLAVED_IDLE_CTOR:
            regs[r.UC_X86_REG_ESP] -= 8
        elif site == SLAVED_IDLE_XFER:
            regs[r.UC_X86_REG_EBP] = esp - 4
            regs[r.UC_X86_REG_ESP] -= 8
            regs[r.UC_X86_REG_ESI] = 0x101F2000
        for reg, value in regs.items():
            assert self.u.reg_read(reg) == value, reg
        return self.exit

    def slot(self, instance: int) -> int:
        for i in range(4096):
            address = self.base + TABLE_OFFSET + i * 32
            if self.read(address) == instance:
                return address
        raise AssertionError("missing instance")


def test_phases_equal_bounds_and_flags_registers() -> None:
    w = World()
    assert w.run() == SLAVED_IDLE_FALLTHROUGH
    w.now = 4
    assert w.run() == SLAVED_IDLE_FALLTHROUGH
    w.now = 5
    assert w.run() == SLAVED_IDLE_GUARD
    w.now = 14
    assert w.run() == SLAVED_IDLE_GUARD
    w.now = 15
    assert w.run() == SLAVED_IDLE_FALLTHROUGH
    w.now = 1000
    assert w.run() == SLAVED_IDLE_GUARD
    assert w.read(w.slot(0x10000000) + 8) == 1010


@pytest.mark.parametrize("flags", [0x203, 0x242, 0x243])
def test_original_not_above_never_reads_objects_or_clock(flags: int) -> None:
    w = World()
    assert w.run(flags=flags) == SLAVED_IDLE_FALLTHROUGH
    assert w.frame_reads == 0


@pytest.mark.parametrize("wander", [0, -1])
def test_disabled_wandering_is_stock(wander: int) -> None:
    w = World()
    assert w.run(wander=wander) == SLAVED_IDLE_GUARD
    assert w.frame_reads == 0


def test_collision_deletion_tombstone_and_address_id_reuse() -> None:
    w = World()
    a, b = 0x10000000, 0x10010000
    w.run(a, 1)
    w.now = 3
    w.run(b, 1)  # deliberately identical hash and ObjectID, separate instance
    assert w.slot(a) != w.slot(b)
    w.now = 5
    assert w.run(a, 1) == SLAVED_IDLE_GUARD
    assert w.run(b, 1) == SLAVED_IDLE_FALLTHROUGH
    w.run(a, 1, site=SLAVED_IDLE_DTOR)
    assert w.run(b, 1) == SLAVED_IDLE_FALLTHROUGH  # lookup passes tombstone
    assert w.run(a, 1) == SLAVED_IDLE_FALLTHROUGH  # address AND id reused
    assert w.read(w.slot(a) + 8) == 10
    w.now = 10
    assert w.run(a, 1) == SLAVED_IDLE_GUARD
    assert w.run(a, 2) == SLAVED_IDLE_FALLTHROUGH  # ID changed without destructor
    w.now = 15
    assert w.run(a, 2) == SLAVED_IDLE_GUARD
    w.run(a, 2, site=SLAVED_IDLE_CTOR)
    assert w.run(a, 2) == SLAVED_IDLE_FALLTHROUGH


def test_save_preserves_load_resets_in_place() -> None:
    w = World()
    w.run()
    w.now = 5
    assert w.run() == SLAVED_IDLE_GUARD
    w.run(site=SLAVED_IDLE_XFER)
    assert w.run() == SLAVED_IDLE_GUARD
    w.loading = True
    w.run(site=SLAVED_IDLE_XFER)
    assert w.run() == SLAVED_IDLE_FALLTHROUGH


def test_wraparound() -> None:
    w = World()
    w.now = 0xFFFFFFFD
    assert w.run() == SLAVED_IDLE_FALLTHROUGH
    w.now = 1
    assert w.run() == SLAVED_IDLE_FALLTHROUGH
    w.now = 2
    assert w.run() == SLAVED_IDLE_GUARD


def test_full_table_does_not_evict_and_reuses_tombstone() -> None:
    w = World()
    for i in range(4096):
        w.write(w.base + TABLE_OFFSET + i * 32, 0x11000000 + i * 16)
    before = bytes(w.u.mem_read(w.base + TABLE_OFFSET, 4096 * 32))
    assert w.run() == SLAVED_IDLE_GUARD
    assert bytes(w.u.mem_read(w.base + TABLE_OFFSET, 4096 * 32)) == before and w.frame_reads == 0
    w.write(w.base + TABLE_OFFSET + 32, 1)
    assert w.run() == SLAVED_IDLE_FALLTHROUGH
    assert w.slot(0x10000000) == w.base + TABLE_OFFSET + 32


def test_arbitrary_inclusive_intervals_and_independence() -> None:
    w = World((1400, 3800, 600, 2200))
    for i in range(100):
        w.run(0x10000000 + i * 16, i)
    deadlines = {w.read(w.slot(0x10000000 + i * 16) + 8) for i in range(100)}
    assert deadlines == set(range(3, 12))
    a = 0x10000000
    durations = {0: set(), 1: set()}
    for _ in range(200):
        slot = w.slot(a)
        w.now = w.read(slot + 8)
        w.run(a, 0)
        phase = w.read(slot + 12)
        durations[phase].add((w.read(slot + 8) - w.now) & 0xFFFFFFFF)
    assert durations == {0: set(range(3, 12)), 1: set(range(7, 20))}


@pytest.mark.full
def test_stock_binary() -> None:
    path = Path("tools/BFME-FILES/game.dat.backup")
    if not path.exists():
        pytest.skip("stock RotWK not installed")
    b = bytearray(path.read_bytes())
    p = SlavedUpdateIdlePatch()
    p.apply(b)
    assert p.verify(b) == []


@pytest.mark.parametrize("distance, target", [(10000.0, 0x8A61D6), (160000.0, SLAVED_IDLE_GUARD)])
def test_idle_fallthrough_still_requires_guard_range_return(distance: float, target: int) -> None:
    w = World()
    w.u.mem_write(SLAVED_IDLE_FALLTHROUGH, SLAVED_IDLE_ANCHORS[SLAVED_IDLE_FALLTHROUGH])
    assert w.run() == SLAVED_IDLE_FALLTHROUGH
    w.write(0x101F0000 + 12, 350)
    w.u.mem_write(0x101F3000, struct.pack("<f", distance))
    # Stock squared-distance helper: thiscall, one argument, x87 result.
    w.u.mem_write(0x5E3BE4, b"\xdb\xe3\xd9\x05" + struct.pack("<I", 0x101F3000) + b"\xc2\x04\x00")
    w.stops.remove(SLAVED_IDLE_FALLTHROUGH)
    w.stops.add(0x8A61D6)
    w.exit = 0
    w.u.emu_start(SLAVED_IDLE_FALLTHROUGH, 0, count=1000)
    assert w.exit == target


def test_x87_sse_state_survives_snapshot_predicate() -> None:
    w = World()
    w.u.mem_write(0x400200, bytes.fromhex("dbe3d9e8d9eb"))  # fninit; fld1; fldpi
    w.u.emu_start(0x400200, 0x400206)
    w.u.mem_write(0x400100, bytes.fromhex("dbe3d9eec3"))  # destructive Xfer predicate
    regs = [
        w.r.UC_X86_REG_FPCW,
        w.r.UC_X86_REG_FPSW,
        w.r.UC_X86_REG_FPTAG,
        w.r.UC_X86_REG_MXCSR,
        *(getattr(w.r, f"UC_X86_REG_FP{i}") for i in range(8)),
    ]
    before = {reg: w.u.reg_read(reg) for reg in regs}
    w.run(site=SLAVED_IDLE_XFER)
    assert {reg: w.u.reg_read(reg) for reg in regs} == before


@pytest.mark.parametrize(
    "ms, frames",
    [
        (1, 1),
        (199, 1),
        (200, 1),
        (201, 2),
        (1000, 5),
        (3000, 15),
        (6000, 30),
        (7095, 36),
        (14191, 71),
        (86400000, 432000),
    ],
)
def test_simulation_grid_rounds_up(ms: int, frames: int) -> None:
    assert milliseconds_to_logic_frames(ms) == frames


def test_default_frame_intervals_and_subframe_parameters() -> None:
    for intervals, limits in [
        ((6000, 14191, 3000, 7095), ((15, 36), (30, 71))),
        ((1, 199, 1, 200), ((1, 1), (1, 1))),
    ]:
        w = World(intervals)
        w.run()
        slot = w.slot(0x10000000)
        for _ in range(500):
            phase = w.read(slot + 12)
            duration = (w.read(slot + 8) - w.now) & 0xFFFFFFFF
            assert limits[phase][0] <= duration <= limits[phase][1]
            w.now = w.read(slot + 8)
            w.run()


def test_two_clients_different_pointers_caves_and_collision_patterns() -> None:
    config = (6000, 14191, 3000, 7095)
    a = World(config)
    b = World(config, shift=-0x81000, cave_base=0x1200000)
    # Client A has separate buckets; B's sixteen instances all hash to the same bucket.
    ap = [0x10000000 + i * 16 for i in range(16)]
    bp = [0x10000000 + i * 0x10000 for i in range(16)]
    ids = [3 + i * 4096 for i in range(16)]  # also exercise colliding ObjectID low bits
    a.now = b.now = 12345
    for i in range(16):
        assert a.run(ap[i], ids[i]) == b.run(bp[i], ids[i])
    sa = [a.slot(p) for p in ap]
    sb = [b.slot(p) for p in bp]
    sequences = [set() for _ in range(16)]
    for step in range(1000):
        frame = 12345 + step * 7 + (step % 3)
        a.now = b.now = frame
        # Reversed per-object iteration order cannot change another instance's sequence.
        decisions_a = [a.run(ap[i], ids[i]) for i in range(16)]
        decisions_b = {i: b.run(bp[i], ids[i]) for i in reversed(range(16))}
        assert decisions_a == [decisions_b[i] for i in range(16)]
        for i in range(16):
            assert a.u.mem_read(sa[i] + 4, 24) == b.u.mem_read(sb[i] + 4, 24)
            sequences[i].add(a.read(sa[i] + 16))
    assert all(len(sequence) > 100 for sequence in sequences)
    assert len({frozenset(sequence) for sequence in sequences}) == 16


def test_repeated_calls_do_not_advance_time_and_sparse_updates_use_frame() -> None:
    w = World()
    w.now = 100
    w.run()
    slot = w.slot(0x10000000)
    before = bytes(w.u.mem_read(slot, 32))
    for _ in range(50):
        assert w.run() == SLAVED_IDLE_FALLTHROUGH
    assert bytes(w.u.mem_read(slot, 32)) == before
    w.now = 104
    assert w.run() == SLAVED_IDLE_FALLTHROUGH
    w.now = 4000
    assert w.run() == SLAVED_IDLE_GUARD
    assert w.read(slot + 8) == 4010  # schedule from real simulation frame, not invocation count


def test_two_clients_reinitialize_on_load_despite_different_previous_history() -> None:
    config = (6000, 14191, 3000, 7095)
    a, b = World(config), World(config, shift=-0x81000, cave_base=0x1200000)
    pa, pb = 0x10000000, 0x10070000
    a.now, b.now = 100, 900
    a.run(pa, 51)
    b.run(pb, 51)
    a.now = 200
    a.run(pa, 51)
    assert a.u.mem_read(a.slot(pa) + 4, 24) != b.u.mem_read(b.slot(pb) + 4, 24)
    a.loading = b.loading = True
    a.run(pa, 51, site=SLAVED_IDLE_XFER)
    b.run(pb, 51, site=SLAVED_IDLE_XFER)
    for frame in range(1234, 6000, 17):
        a.now = b.now = frame
        assert a.run(pa, 51) == b.run(pb, 51)
        assert a.u.mem_read(a.slot(pa) + 4, 24) == b.u.mem_read(b.slot(pb) + 4, 24)


def test_full_table_selection_does_not_depend_on_pointer_hash() -> None:
    a, b = World(), World(shift=-0x81000, cave_base=0x1200000)
    # Same logical occupancy in different slots/layouts; no wall-clock/time-budgeted probing.
    for i in range(4096):
        a.write(a.base + TABLE_OFFSET + i * 32, 0x11000000 + i * 16)
        b.write(b.base + TABLE_OFFSET + ((i * 17) & 4095) * 32, 0x12000000 + i * 16)
    assert a.run(0x10000000, 71) == b.run(0x10070000, 71) == SLAVED_IDLE_GUARD
    a.write(a.base + TABLE_OFFSET + 32, 1)
    b.write(b.base + TABLE_OFFSET + 777 * 32, 1)
    assert a.run(0x10000000, 71) == b.run(0x10070000, 71) == SLAVED_IDLE_FALLTHROUGH
    assert a.u.mem_read(a.slot(0x10000000) + 4, 24) == b.u.mem_read(b.slot(0x10070000) + 4, 24)


def test_null_game_logic_leaves_table_and_cpu_intact() -> None:
    w = World()
    w.write(THE_GAME_LOGIC, 0)
    assert w.run() == SLAVED_IDLE_GUARD
    assert not any(w.u.mem_read(w.base + TABLE_OFFSET, 4096 * 32))
    assert w.frame_reads == 0


def test_main_hook_has_no_external_rng_timer_or_floating_point_calls() -> None:
    cs = pytest.importorskip("capstone")
    code, hooks = build_code(0xF00000, (6000, 14191, 3000, 7095))
    end = hooks[SLAVED_IDLE_CTOR] - hooks[SLAVED_IDLE_HOOK]
    insns = list(cs.Cs(cs.CS_ARCH_X86, cs.CS_MODE_32).disasm(code[:end], hooks[SLAVED_IDLE_HOOK]))
    calls = [i for i in insns if i.mnemonic == "call"]
    assert len(calls) == 1 and calls[0].op_str.startswith("0x")
    assert int(calls[0].op_str, 16) > hooks[SLAVED_IDLE_XFER]  # private table lookup only
    assert not any(i.mnemonic.startswith(("f", "rdtsc", "rdtscp", "rdrand")) for i in insns)
