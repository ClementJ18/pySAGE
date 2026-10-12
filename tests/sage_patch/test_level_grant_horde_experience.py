"""Execute the native special-power, group aggregation and tracker paths together."""

from __future__ import annotations

import argparse
import struct

import pytest

from sage_patch import ExperienceLevelDownPatch
from sage_patch.addresses import (
    HORDE_EXPERIENCE_ADD,
    HORDE_EXPERIENCE_GROUP_LOOKUP_OR_INSERT,
    HORDE_FIND_INTERFACE,
    LEVEL_GRANT_SPECIAL_POWER_HORDE_ANCHORS,
)
from sage_patch.asm import JE, Asm
from sage_patch.patches import experience_level_down as xp
from sage_patch.patches import level_grant_special_power as power
from sage_patch.utils import find_section
from tests.sage_patch.test_experience_level_down import World, float_bits, image


class HordeWorld(World):
    """Model contain iteration/containers and services; execute actual XP and level code."""

    controller = 0x1060000
    module_data = 0x1061000
    vector = 0x1069000
    iterator = 0xF30000
    count_entry = 0xF30100
    cave = 0xF40000

    def __init__(
        self,
        *,
        capped: bool = True,
        rank: int = 5,
        experience: float = 300,
        extra: bool = False,
        hordes: int = 1,
        patched: bool = True,
    ) -> None:
        super().__init__(rank, experience, thresholds=(1, 100, 150, 200, 300))
        self.modifier_store = {self.object: self.modifiers}
        self.objects = {123: self.object}
        self.members: list[int] = []
        self.parents: list[int] = []
        self.interfaces: dict[int, int] = {}
        self.group_maps: dict[int, dict[int, int]] = {}
        self.group_values: list[dict[int, int]] = []
        self.wrapper_deltas: list[float] = []
        self.upward_horde_callbacks = 0
        self.w32(self.controller + 4, self.module_data)
        self.w32(self.vector, self.vector + 0x100)
        self.w32(self.vector + 4, self.vector + 0x100)
        self.wfloat(0xBD1908, 1)
        for va, blob in LEVEL_GRANT_SPECIAL_POWER_HORDE_ANCHORS.items():
            self.uc.mem_write(va, blob)
        if capped:
            base = 0xF20000
            self.uc.mem_write(
                base, xp._cap_assemble(base, xp._assemble(self.base).label_va("down")).finish()
            )
            for va, new in xp._cap_windows(base).items():
                self.uc.mem_write(va, new)
        self.uc.mem_write(self.cave, power.build_code(self.cave))
        for va, (_old, new) in power._windows(self.cave).items():
            # The baseline has the signed-XP gate but no horde extensions.
            if patched or va in power._WINDOWS:
                self.uc.mem_write(va, new)
        self.w32(0x1067000 + 0xC0, HORDE_EXPERIENCE_ADD)
        self.w32(0x1067000 + 0x180, self.count_entry)
        self.w32(0x1068000 + 0x110, self.iterator)
        a = Asm(self.iterator)
        a.emit(b"\x55\x8b\xec\x53\x56\x57\x8b\x59\x04\x8b\x79\x08\x8b\x75\x0c\x85\xff")
        a.jcc(JE, "end")
        a.label("loop")
        a.emit(b"\x56\xff\x33\xff\x55\x08\x83\xc4\x08\x83\xc3\x04\x4f")
        a.jcc(0x5, "loop")
        a.label("end")
        a.emit(b"\x5f\x5e\x5b\x5d\xc2\x0c\x00")
        self.uc.mem_write(self.iterator, a.finish())
        for h in range(hordes):
            obj = self.object if h == 0 else 0x1070000
            tracker = self.tracker if h == 0 else 0x1070800
            template = self.template if h == 0 else 0x1071000
            iface = 0x1018000 if h == 0 else 0x1073000
            contain = iface - 0xFC
            self.clone_tracker(obj, tracker, template, rank, experience, 123 + h)
            self.parents.append(obj)
            self.interfaces[obj] = iface
            self.uc.mem_write(template + 0x115, b"\x20")
            self.w32(obj + 0x258, contain)
            self.w32(iface, 0x1067000)
            self.w32(iface - 0x114, obj)
            self.w32(contain, 0x1068000)
            array = 0x1065000 + h * 0x10000
            self.w32(contain + 4, array)
            self.w32(contain + 8, 20 + int(extra))
            entries = {0x1A88: 0x1063000 + h * 0x11000}
            if extra:
                entries[0x1A50] = entries[0x1A88] + 0x20
            sentinel = entries[0x1A88] + 0x100
            self.w32(iface + 0x13C, sentinel)
            self.group_maps[iface + 0x13C] = entries
            self.group_values.append(entries)
            for key, node in entries.items():
                self.w32(node + 0x10, key)
                self.wfloat(node + 0x14, experience if key == 0x1A88 else 1)
            for n in range(20 + int(extra)):
                i = len(self.members)
                member = 0x1080000 + i * 0x1000
                self.clone_tracker(
                    member, member + 0x400, member + 0x600, rank, experience, 1000 + i
                )
                self.uc.mem_write(member + 0x600 + 0x115, b"\x00")
                self.w32(member + 0x78, 123 + h)
                self.w32(member + 0x600 + 0x5E8, 0x1A88 if n < 20 else 0x1A50)
                self.w32(array + n * 4, member)
                self.members.append(member)
        self.services.update(
            {
                HORDE_FIND_INTERFACE: (0, lambda args: self.interfaces.get(self.this(), 0)),
                self.count_entry: (1, lambda args: 20),
                power.HORDE_EXPERIENCE_GROUP_FIND: (1, self.find_group),
                HORDE_EXPERIENCE_GROUP_LOOKUP_OR_INSERT: (1, self.group_value),
                0x0044DDEC: (1, lambda args: 0),
                0x00449681: (1, lambda args: self.objects.get(args[0], 0)),
                0x005487BB: (1, self.append_id),
                0x008719E4: (1, self.horde_up),
            }
        )
        self.uc.hook_add(self.unicorn.UC_HOOK_CODE, self.record_wrapper)

    def clone_tracker(
        self, obj: int, tracker: int, template: int, rank: int, experience: float, object_id: int
    ) -> None:
        self.uc.mem_write(tracker, bytes(self.uc.mem_read(self.tracker, 0x40)))
        self.uc.mem_write(template, bytes(self.uc.mem_read(self.template, 0x600)))
        self.w32(tracker + 4, template)
        self.w32(tracker + 0x34, obj)
        self.wfloat(tracker + 0x10, experience)
        self.w32(obj + 4, template)
        self.w32(obj + 0x26C, tracker)
        self.w32(obj + 0x74, object_id)
        self.w32(obj + 0x28C, sum(1 << n for n in range(1, rank + 1)))
        self.objects[object_id] = obj
        self.modifier_store[obj] = list(range(1, rank + 1))

    def this(self) -> int:
        return self.uc.reg_read(self.regs.UC_X86_REG_ECX)

    def find_group(self, args: list[int]) -> int:
        key = self.r32(args[0]) & 0xFFFF
        return self.group_maps[self.this()].get(key, self.r32(self.this()))

    def group_value(self, args: list[int]) -> int:
        return self.find_group(args) + 0x14

    def append_id(self, args: list[int]) -> int:
        end = self.r32(self.vector + 4)
        self.w32(end, self.r32(args[0]))
        self.w32(self.vector + 4, end + 4)
        return 0

    def horde_up(self, args: list[int]) -> int:
        self.upward_horde_callbacks += 1
        return 0

    def remove_modifier(self, args: list[int]) -> int:
        value = self.r32(args[0])
        entries = self.modifier_store[self.this()]
        if value in entries:
            entries.remove(value)
        return 0

    def remove_upgrade(self, args: list[int]) -> int:
        obj = self.this()
        bit = self.r32(args[0] + 0x38)
        self.w32(obj + 0x28C, self.r32(obj + 0x28C) & ~(1 << bit))
        return 0

    def enqueue(self, args: list[int]) -> int:
        result = super().enqueue([args[0], self.object, args[2]])
        self.w32(self.queue_nodes[-1] + 8, self.r32(args[1] + 0x74))
        return result

    def grant(self, args: list[int]) -> int:
        rank = self.r32(args[0] + 0xFC)
        obj = args[1]
        self.modifier_store[obj].append(rank)
        self.w32(obj + 0x28C, self.r32(obj + 0x28C) | (1 << rank))
        return 0

    def record_wrapper(self, _uc: object, address: int, _size: int, _data: object) -> None:
        if address == power.EXPERIENCE_TRACKER_ADD_EXPERIENCE_POINTS:
            sp = self.uc.reg_read(self.regs.UC_X86_REG_ESP)
            self.wrapper_deltas.append(struct.unpack("<f", self.uc.mem_read(sp + 4, 4))[0])

    def run(self, entry: int, args: list[int], *, this: int | None = None) -> None:
        self.w32(self.stack, self.stop)
        for n, value in enumerate(args, 1):
            self.w32(self.stack + n * 4, value)
        preserved = {
            self.regs.UC_X86_REG_EBP: 0x12345678,
            self.regs.UC_X86_REG_ESI: 0x22345678,
            self.regs.UC_X86_REG_EDI: 0x32345678,
            self.regs.UC_X86_REG_EBX: 0x42345678,
        }
        for reg, value in preserved.items():
            self.uc.reg_write(reg, value)
        top = self.uc.reg_read(self.regs.UC_X86_REG_FPSW) & 0x3800
        self.uc.reg_write(self.regs.UC_X86_REG_ESP, self.stack)
        self.uc.reg_write(self.regs.UC_X86_REG_ECX, self.tracker if this is None else this)
        self.uc.emu_start(entry, self.stop, count=3000000)
        assert self.uc.reg_read(self.regs.UC_X86_REG_EIP) == self.stop
        assert self.uc.reg_read(self.regs.UC_X86_REG_ESP) == self.stack + 4 + len(args) * 4
        assert self.uc.reg_read(self.regs.UC_X86_REG_FPSW) & 0x3800 == top
        for reg, value in preserved.items():
            assert self.uc.reg_read(reg) == value

    def ability(self, delta: int, targets: list[int] | None = None) -> None:
        self.w32(self.module_data + 0xD0, delta)
        self.w32(self.vector + 4, self.vector + 0x100)
        for obj in self.members if targets is None else targets:
            self.run(0x8C6F32, [obj, self.vector], this=self.controller)

    def state(self, obj: int) -> tuple[int, float]:
        tracker = self.r32(obj + 0x26C)
        return self.r32(tracker + 0x24), struct.unpack("<f", self.uc.mem_read(tracker + 0x10, 4))[0]


@pytest.mark.parametrize("extra", [False, True])
def test_positive_power_matches_native_horde_aggregation(extra: bool) -> None:
    patched = HordeWorld(rank=1, experience=1, extra=extra)
    baseline = HordeWorld(rank=1, experience=1, extra=extra, patched=False)
    for world in [patched, baseline]:
        world.ability(500)
        assert world.wrapper_deltas == []
        assert world.state(world.object) == (5, 300)
    assert [patched.state(o) for o in patched.members] == [
        baseline.state(o) for o in baseline.members
    ]
    assert patched.upward_horde_callbacks == baseline.upward_horde_callbacks


@pytest.mark.parametrize("extra", [False, True])
@pytest.mark.parametrize("hordes", [1, 2])
def test_negative_power_drains_each_parent_once_and_recovers(extra: bool, hordes: int) -> None:
    world = HordeWorld(extra=extra, hordes=hordes)
    world.ability(-500)
    assert world.wrapper_deltas == [-500] * hordes
    assert all(world.state(obj) == (1, 1) for obj in [*world.parents, *world.members])
    assert all(
        world.r32(node + 0x14) == 0 for entries in world.group_values for node in entries.values()
    )
    assert world.upward_horde_callbacks == 0
    world.ability(500)
    assert all(world.state(obj) == (5, 300) for obj in world.parents)
    assert all(
        world.state(obj) == (5, 300)
        for obj in world.members
        if world.r32(obj + 0x600 + 0x5E8) == 0x1A88
    )


def test_unbounded_mode_keeps_native_negative_group_reserves() -> None:
    world = HordeWorld(capped=False)
    world.ability(-500)
    assert world.state(world.object) == (1, -200)
    assert world.state(world.members[0]) == (1, -200)
    assert (
        struct.unpack("<f", world.uc.mem_read(world.group_values[0][0x1A88] + 0x14, 4))[0] == -200
    )


def test_combat_xp_matches_native_even_with_mixed_member_types() -> None:
    patched, baseline = (
        HordeWorld(rank=1, experience=1, extra=True),
        HordeWorld(rank=1, experience=1, extra=True, patched=False),
    )
    for world in [patched, baseline]:
        iface = world.interfaces[world.object]
        for member in world.members:
            world.run(HORDE_EXPERIENCE_ADD, [member, float_bits(25)], this=iface)
        assert world.wrapper_deltas == []
    assert patched.state(patched.object) == baseline.state(baseline.object) == (5, 300)
    assert [patched.state(o) for o in patched.members] == [
        baseline.state(o) for o in baseline.members
    ]


@pytest.mark.parametrize("delta", [0, 500, -500])
def test_single_object_and_missing_tracker_keep_native_path(delta: int) -> None:
    world = HordeWorld()
    obj = world.members[0]
    world.w32(obj + 0x78, 0)
    world.ability(delta, [obj])
    assert len(world.wrapper_deltas) == int(delta != 0)
    assert world.state(world.object) == (5, 300)
    world.w32(obj + 0x26C, 0)
    world.ability(delta, [obj])
    assert len(world.wrapper_deltas) == int(delta != 0)


def test_default_xp_bounds_and_explicit_python_opt_out() -> None:
    assert ExperienceLevelDownPatch().options() == {"xp_cap": True}
    assert ExperienceLevelDownPatch(xp_cap=False).options() == {"xp_cap": False}
    for enabled in [False, True]:
        data = image()
        patch = ExperienceLevelDownPatch(xp_cap=enabled)
        patch.apply(data)
        detected = patch.detect(data)
        assert detected is not None and detected.xp_cap is enabled
        assert bool(find_section(data, xp._XP_CAP_SECTION)) is enabled


def test_cli_default_and_explicit_opt_out() -> None:
    # The parameter behavior itself is independent of binary output paths.
    parser = argparse.ArgumentParser()
    ExperienceLevelDownPatch.add_cli_arguments(parser)
    assert ExperienceLevelDownPatch.from_cli_args(parser.parse_args([])).xp_cap
    assert not ExperienceLevelDownPatch.from_cli_args(parser.parse_args(["--no-xp-cap"])).xp_cap


@pytest.mark.parametrize("delta", [-100, -2147483648])
def test_partial_and_extreme_drains_use_full_signed_ini_value(delta: int) -> None:
    world = HordeWorld(extra=True)
    world.ability(delta)
    assert world.wrapper_deltas == [delta]
    assert world.state(world.object) == ((4, 200) if delta == -100 else (1, 1))


def test_small_gain_after_floor_is_not_consumed_by_a_hidden_negative_account() -> None:
    world = HordeWorld()
    world.ability(-500)
    world.ability(100)
    assert world.state(world.object) == (2, 100)
    assert all(world.state(obj) == (2, 100) for obj in world.members)


@pytest.mark.parametrize("missing", ["zero", "empty", "interface"])
def test_zero_and_missing_horde_distribution_do_not_drain_parent(missing: str) -> None:
    world = HordeWorld()
    if missing == "empty":
        world.services[world.count_entry] = (1, lambda args: 0)
    elif missing == "interface":
        world.services[HORDE_FIND_INTERFACE] = (0, lambda args: 0)
    world.ability(0 if missing == "zero" else -500)
    assert world.wrapper_deltas == []
    assert world.state(world.object) == (5, 300)


def test_native_sink_forwarding_and_eligibility_are_respected() -> None:
    world = HordeWorld()
    world.w32(world.tracker + 0x38, 1000)  # existing member ObjectID is the configured sink
    world.wfloat(world.tracker + 0x1C, 0.5)
    world.ability(-100)
    assert world.state(world.object) == (5, 300)
    assert world.state(world.members[0]) == (3, 150)
    assert world.state(world.members[1]) == (4, 200)
    blocked = HordeWorld()
    blocked.services[0x44DDEC] = (1, lambda args: int(blocked.this() == blocked.object))
    blocked.ability(-100)
    assert blocked.wrapper_deltas == [] and blocked.state(blocked.object) == (5, 300)


def test_existing_object_tracker_guard_is_not_broadened() -> None:
    world = HordeWorld()
    assert world.r32(world.r32(world.tracker) + 0x10) == xp.EXPERIENCE_TRACKER_OBJECT_LEVEL_CHANGE
    other_vtable = 0x1076000
    world.uc.mem_write(other_vtable, bytes(world.uc.mem_read(world.vtable, 0x20)))
    world.w32(other_vtable + 0x10, 0x12345678)
    world.w32(world.tracker, other_vtable)
    world.ability(-100)
    assert world.state(world.object) == (5, 200)  # XP changes, but no unsupported rank rollback
    assert world.state(world.members[0]) == (4, 200)


def test_additional_parent_call_restores_registers_flags_and_float_state() -> None:
    world = HordeWorld()
    xmm = [getattr(world.regs, f"UC_X86_REG_XMM{n}") for n in range(8)]
    registers = [
        *xmm,
        world.regs.UC_X86_REG_FPSW,
        world.regs.UC_X86_REG_FPCW,
        world.regs.UC_X86_REG_MXCSR,
        world.regs.UC_X86_REG_EFLAGS,
        world.regs.UC_X86_REG_EAX,
        world.regs.UC_X86_REG_ECX,
        world.regs.UC_X86_REG_EDX,
        world.regs.UC_X86_REG_ESP,
    ]
    snapshots: list[list[int]] = []

    def observe(uc: object, address: int, size: int, data: object) -> None:
        if address in [world.cave + 6, power.LEVEL_GRANT_SPECIAL_POWER_DISTRIBUTE_RETURN]:
            snapshots.append([world.uc.reg_read(r) for r in registers])
        if address == power.EXPERIENCE_TRACKER_ADD_EXPERIENCE_POINTS:
            world.uc.reg_write(xmm[7], 0xDEADBEEF)
            world.uc.reg_write(
                world.regs.UC_X86_REG_MXCSR, world.uc.reg_read(world.regs.UC_X86_REG_MXCSR) ^ 0x2000
            )

    world.uc.hook_add(world.unicorn.UC_HOOK_CODE, observe)
    world.ability(-100, [world.members[0]])
    assert len(snapshots) == 2 and snapshots[0] == snapshots[1]
