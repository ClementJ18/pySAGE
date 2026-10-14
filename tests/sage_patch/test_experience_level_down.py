"""Execute the patch and anchored stock XP paths against a data-free object/queue world."""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

from sage_ini.engine import STOCK
from sage_patch import ExperienceLevelDownPatch, LevelGrantSpecialPowerPatch
from sage_patch.__main__ import main
from sage_patch.addresses import EXPERIENCE_LEVEL_DOWN_ANCHORS
from sage_patch.asm import Asm
from sage_patch.patches import experience_level_down as xp
from sage_patch.registry import PATCHES
from sage_patch.utils import file_offset, find_section
from tests.sage_patch.test_patching import _tiny_pe


def image() -> bytearray:
    data = _tiny_pe()
    data.extend(bytes(0xA00000 - len(data)))
    # Keep distinct raw and virtual offsets, covering all stock code and vtable anchors.
    size = len(data) - 0x200
    struct.pack_into("<IIII", data, 0x178 + 8, size, 0x1000, size, 0x200)
    for va, old in {**EXPERIENCE_LEVEL_DOWN_ANCHORS, **xp._WINDOWS}.items():
        off = file_offset(data, va)
        data[off : off + len(old)] = old
    return data


def test_apply_verify_detect_and_registration() -> None:
    data = image()
    patch = ExperienceLevelDownPatch(xp_cap=False)
    assert PATCHES[patch.name] is type(patch)
    assert not patch.experimental and not patch.runtime_verified
    assert patch.detect(data) is None
    before = bytes(data)
    patch.apply(data)
    assert patch.verify(data) == []
    assert isinstance(patch.detect(data), type(patch))
    # Existing section contents only change inside the four fingerprinted windows.
    changed = {
        file_offset(before, va) + n for va, old in xp._WINDOWS.items() for n in range(len(old))
    }
    assert all(
        a == b or n in changed
        for n, (a, b) in enumerate(
            zip(before[0x200:], data[0x200 : len(before)], strict=True), 0x200
        )
    )
    located = find_section(data, xp.SECTION_NAME)
    assert located is not None
    va, off, size = located
    assert bytes(data[off : off + size]) == xp.build_code(va)
    assert patch.ini_surface() is STOCK
    snapshot = bytes(data)
    with pytest.raises(ValueError, match="already carries"):
        patch.apply(data)
    assert bytes(data) == snapshot


@pytest.mark.parametrize("va", [*EXPERIENCE_LEVEL_DOWN_ANCHORS, *xp._WINDOWS])
def test_wrong_build_fails_before_allocating_or_writing(va: int) -> None:
    data = image()
    data[file_offset(data, va)] ^= 0xFF
    before = bytes(data)
    with pytest.raises(ValueError, match="unexpected build"):
        ExperienceLevelDownPatch(xp_cap=False).apply(data)
    assert bytes(data) == before


def test_disassembly_and_jump_windows() -> None:
    capstone = pytest.importorskip("capstone")
    decoder = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    base = 0xF00000
    code = xp.build_code(base)
    instructions = list(decoder.disasm(code, base))
    assert sum(i.size for i in instructions) == len(code)
    assert not any(i.mnemonic.startswith(("fld", "fst")) for i in instructions)
    calls = {
        int(i.op_str, 16)
        for i in instructions
        if i.mnemonic == "call" and i.op_str.startswith("0x")
    }
    assert xp.OBJECT_REMOVE_LEVEL_MODIFIER in calls
    assert xp.OBJECT_REMOVE_LEVEL_UPGRADE in calls
    assert 0x006AE60C not in calls and 0x0079D76D not in calls
    for va, old, new in xp._windows(base):
        assert sum(i.size for i in decoder.disasm(old, va)) == len(old)
        assert len(old) == len(new)
        if va != xp._CAP:
            target = va + 5 + struct.unpack_from("<i", new, 1)[0]
            assert target in {i.address for i in instructions}


def test_cli_application_and_verification(tmp_path: Path) -> None:
    source, output = tmp_path / "stock.dat", tmp_path / "patched.dat"
    original = image()
    source.write_bytes(original)
    assert main(["apply", "experience-level-down", "--in", str(source), "--out", str(output)]) == 0
    assert main(["verify", "experience-level-down", str(output)]) == 0
    assert source.read_bytes() == original


@pytest.mark.parametrize("site", [*xp._WINDOWS, 0])
def test_verify_rejects_a_modified_hook_or_cave(site: int) -> None:
    data = image()
    patch = ExperienceLevelDownPatch(xp_cap=False)
    patch.apply(data)
    if site:
        off = file_offset(data, site)
    else:
        located = find_section(data, xp.SECTION_NAME)
        assert located is not None
        off = located[1]
    data[off] ^= 0xFF
    assert patch.verify(data)
    assert patch.detect(data) is None


class World:
    """Run real stock machine code; model only engine services, effect storage and allocation."""

    tracker = 0x1000000
    object = 0x1001000
    template = 0x1002000
    vtable = 0x1003000
    collection = 0x1004000
    sentinel = 0x1004100
    queue_system = 0x1005000
    queue_head = 0x1005100
    stack = 0x1108000
    stop = 0xF10000
    base = 0xF00000

    def __init__(
        self,
        rank: int = 5,
        experience: float = 450,
        *,
        thresholds: tuple[int, ...] = (0, 100, 200, 300, 400),
        multiplayer: bool = False,
    ) -> None:
        self.unicorn = pytest.importorskip("unicorn")
        self.regs = pytest.importorskip("unicorn.x86_const")
        self.uc = self.unicorn.Uc(self.unicorn.UC_ARCH_X86, self.unicorn.UC_MODE_32)
        self.uc.mem_map(0x400000, 0xD00000)
        self.uc.mem_map(0x1100000, 0x10000)
        self.events: list[tuple[str, int]] = []
        self.modifiers: list[int] = list(range(1, rank + 1))
        self.player_upgrades = {999}
        self.levels = [0x1006000 + n * 0x200 for n in range(len(thresholds))]
        self.queue_nodes: list[int] = []
        self.multiplayer = multiplayer
        for va, blob in EXPERIENCE_LEVEL_DOWN_ANCHORS.items():
            self.uc.mem_write(va, blob)
        self.uc.mem_write(
            0x79D76D,
            bytes.fromhex(
                "5657ff7424108b7c24108bf18b0657ff5010f30f2a4718f30f11461081c7fc000000ff378bcee892ffffff807c2414007409ff378bcee89dffffff5f5ec20c00"
            ),
        )
        # Core and setter epilogues sit just outside their edited windows.
        self.uc.mem_write(0x79D6FC, bytes.fromhex("c9c21800"))
        self.uc.mem_write(self.base, xp.build_code(self.base))
        for va, _old, new in xp._windows(self.base):
            self.uc.mem_write(va, new)
        self.w32(xp.THE_EXPERIENCE_LEVEL_SYSTEM, 0x1009000)
        self.w32(xp.THE_DELAYED_EXPERIENCE_LEVEL_GRANT_SYSTEM, self.queue_system)
        self.w32(self.tracker, self.vtable)
        self.w32(self.vtable + 0x10, xp.EXPERIENCE_TRACKER_OBJECT_LEVEL_CHANGE)
        self.w32(self.tracker + 4, self.template)
        self.w32(self.tracker + 0xC, rank)
        self.wfloat(self.tracker + 0x10, experience)
        self.wfloat(self.tracker + 0x1C, 1)
        self.uc.mem_write(self.tracker + 0x20, b"\x01")
        self.w32(self.tracker + 0x24, rank)
        self.w32(self.tracker + 0x28, len(thresholds))
        self.w32(self.tracker + 0x2C, 0x100A000)
        self.w32(self.tracker + 0x34, self.object)
        self.w32(self.object + 0x26C, self.tracker)
        self.w32(self.object + 0x74, 123)
        self.uc.mem_write(self.template + 0x5F7, b"\x01")
        self.w32(self.collection, self.sentinel)
        self.w32(self.sentinel, 0x100B000 if thresholds else self.sentinel)
        for n, (level, threshold) in enumerate(zip(self.levels, thresholds, strict=True), 1):
            node = 0x100B000 + (n - 1) * 0x20
            self.w32(node, node + 0x20 if n < len(thresholds) else self.sentinel)
            self.w32(node + 0xC, level)
            self.w32(level + 0x10, n)
            self.w32(level + 0x18, threshold)
            self.w32(level + 0xFC, n)
            modifier = 0x100C000 + n * 0x20
            self.w32(modifier, n)
            self.w32(level + 0x30, modifier)
            self.w32(level + 0x34, modifier + 4)
            upgrade = 0x100D000 + n * 0x40
            player_upgrade = upgrade + 0x20
            self.w32(upgrade + 4, 1)
            self.w32(upgrade + 0x38, n)
            self.w32(player_upgrade + 4, 0)
            self.w32(player_upgrade + 0x38, 999)
            vector = 0x100E000 + n * 0x10
            self.w32(vector, upgrade)
            self.w32(vector + 4, player_upgrade)
            self.w32(level + 0x4C, vector)
            self.w32(level + 0x50, vector + 8)
        self.w32(self.object + 0x28C, sum(1 << n for n in range(1, rank + 1)))
        self.w32(self.queue_system + 0x10, self.queue_head)
        self.w32(self.queue_head, self.queue_head)
        self.w32(self.queue_head + 4, self.queue_head)
        # Model the XP-adjustment float return with a genuine x87 call/ret contract.
        self.wfloat(0x100F000, 1)
        self.uc.mem_write(0x79D4B9, bytes.fromhex("d9442404d80d00f00001c20400"))
        self.services = {
            xp.EXPERIENCE_LEVEL_COLLECTION: (1, lambda args: self.collection),
            xp.EXPERIENCE_LEVEL_FIND_BY_KEY: (
                1,
                lambda args: self.levels[args[0] - 1] if 0 < args[0] <= len(self.levels) else 0,
            ),
            0x625456: (0, lambda args: int(self.multiplayer)),
            xp.OBJECT_REMOVE_LEVEL_MODIFIER: (1, self.remove_modifier),
            xp.OBJECT_REMOVE_LEVEL_UPGRADE: (1, self.remove_upgrade),
            0x436030: (1, lambda args: 0),
            0x49F474: (1, lambda args: self.r32(args[0])),
            0x79D717: (0, lambda args: 0),
            0x70E013: (0, lambda args: 0),
            0x8215C2: (3, self.enqueue),
            0x449681: (1, lambda args: self.object if args[0] == 123 else 0),
            0x821319: (3, self.grant),
            0x862535: (0, self.clear_queue),
        }
        self.uc.hook_add(self.unicorn.UC_HOOK_CODE, self.callback)

    def w32(self, address: int, value: int) -> None:
        self.uc.mem_write(address, struct.pack("<I", value & 0xFFFFFFFF))

    def r32(self, address: int) -> int:
        return struct.unpack("<I", self.uc.mem_read(address, 4))[0]

    def wfloat(self, address: int, value: float) -> None:
        self.uc.mem_write(address, struct.pack("<f", value))

    @property
    def experience(self) -> float:
        return struct.unpack("<f", self.uc.mem_read(self.tracker + 0x10, 4))[0]

    @property
    def rank(self) -> int:
        return self.r32(self.tracker + 0x24)

    def callback(self, _machine: object, address: int, _size: int, _data: object) -> None:
        if address not in self.services:
            return
        count, service = self.services[address]
        sp = self.uc.reg_read(self.regs.UC_X86_REG_ESP)
        args = [self.r32(sp + 4 + n * 4) for n in range(count)]
        result = service(args)
        self.uc.reg_write(self.regs.UC_X86_REG_EAX, result)
        self.uc.reg_write(self.regs.UC_X86_REG_EDX, 0xDEADBEEF)
        self.uc.reg_write(self.regs.UC_X86_REG_ECX, 0xDEADBEEF)
        self.uc.reg_write(self.regs.UC_X86_REG_EIP, self.r32(sp))
        self.uc.reg_write(self.regs.UC_X86_REG_ESP, sp + 4 + count * 4)

    def remove_modifier(self, args: list[int]) -> int:
        assert self.uc.reg_read(self.regs.UC_X86_REG_ECX) == self.object
        value = self.r32(args[0])
        self.events.append(("remove-modifier", value))
        if value in self.modifiers:
            self.modifiers.remove(value)
        return 0

    def remove_upgrade(self, args: list[int]) -> int:
        assert self.uc.reg_read(self.regs.UC_X86_REG_ECX) == self.object
        assert self.r32(args[0] + 4) != 0
        bit = self.r32(args[0] + 0x38)
        self.events.append(("remove-upgrade", bit))
        self.w32(self.object + 0x28C, self.r32(self.object + 0x28C) & ~(1 << bit))
        return 0

    def enqueue(self, args: list[int]) -> int:
        level, obj, flag = args
        assert obj == self.object
        node = 0x100F100 + len(self.queue_nodes) * 0x20
        last = self.r32(self.queue_head + 4)
        self.w32(last, node)
        self.w32(node, self.queue_head)
        self.w32(node + 4, last)
        self.w32(node + 8, 123)
        self.w32(node + 0xC, level)
        self.w32(node + 0x10, flag)
        self.w32(self.queue_head + 4, node)
        self.queue_nodes.append(node)
        return 0

    def grant(self, args: list[int]) -> int:
        level, obj, _flag = args
        assert obj == self.object and level
        rank = self.r32(level + 0xFC)
        self.events.append(("grant", rank))
        self.modifiers.append(rank)
        self.w32(self.object + 0x28C, self.r32(self.object + 0x28C) | (1 << rank))
        return 0

    def clear_queue(self, _args: list[int]) -> int:
        self.w32(self.queue_head, self.queue_head)
        self.w32(self.queue_head + 4, self.queue_head)
        return 0

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
        self.uc.reg_write(self.regs.UC_X86_REG_ESP, self.stack)
        self.uc.reg_write(self.regs.UC_X86_REG_ECX, self.tracker if this is None else this)
        self.uc.emu_start(entry, self.stop, count=50000)
        assert self.uc.reg_read(self.regs.UC_X86_REG_EIP) == self.stop
        assert self.uc.reg_read(self.regs.UC_X86_REG_ESP) == self.stack + 4 + len(args) * 4
        for reg, value in preserved.items():
            assert self.uc.reg_read(reg) == value
        assert (self.uc.reg_read(self.regs.UC_X86_REG_FPSW) >> 11) & 7 == 0

    def add(
        self, delta: float, *, scale: bool = False, adjust: bool = False, factor: float = 1
    ) -> None:
        self.run(0x79D68D, [float_bits(delta), int(adjust), int(scale), 0, 0, float_bits(factor)])

    def set(self, value: float) -> None:
        self.run(0x79D8EF, [float_bits(value), 0])

    def drain_queue(self) -> None:
        # The real queue body runs, skipping only our explicitly cancelled nodes.
        self.run(0x821567, [], this=self.queue_system)


def float_bits(value: float) -> int:
    return struct.unpack("<I", struct.pack("<f", value))[0]


@pytest.mark.parametrize("setter", [False, True])
@pytest.mark.parametrize(
    "loss,rank,remaining", [(10, 5, 440), (75, 4, 375), (300, 2, 150), (600, 1, -150)]
)
def test_loss_preserves_xp_and_removes_only_lost_effects(
    setter: bool, loss: float, rank: int, remaining: float
) -> None:
    world = World()
    if setter:
        world.set(remaining)
    else:
        world.add(-loss)
    assert (world.rank, world.experience) == (rank, remaining)
    assert world.modifiers == list(range(1, rank + 1))
    assert world.player_upgrades == {999}
    assert world.r32(world.object + 0x28C) == sum(1 << n for n in range(1, rank + 1))
    assert [n for kind, n in world.events if kind == "remove-modifier"] == list(range(5, rank, -1))
    assert not world.queue_nodes  # state update must not enqueue the lower level again


@pytest.mark.parametrize(
    "delta,factor,new_rank,new_xp",
    [(100, 1, 5, 450), (-100, -1, 5, 450), (100, -1, 4, 350), (-100, 0, 5, 450)],
)
def test_maximum_rank_uses_effective_change(
    delta: float, factor: float, new_rank: int, new_xp: float
) -> None:
    world = World()
    world.add(delta, scale=True, factor=factor)
    assert (world.rank, world.experience) == (new_rank, new_xp)


def test_x87_adjustment_and_rounding_determine_actual_loss() -> None:
    world = World()
    world.wfloat(0x100F000, -1)
    world.add(100, adjust=True)
    assert (world.rank, world.experience) == (4, 350)
    world = World(experience=2**30)
    world.add(-1)  # rounded addition is unchanged: no automatic rollback of an explicit rank
    assert (world.rank, world.experience) == (5, 2**30)


def test_ascend_again_regrants_only_lost_levels() -> None:
    world = World()
    world.add(-300)
    world.add(300)
    assert (world.rank, world.experience) == (5, 450)
    world.drain_queue()
    assert world.modifiers == [1, 2, 3, 4, 5]
    assert [n for kind, n in world.events if kind == "grant"] == [3, 4, 5]


def test_pending_lost_grants_cancelled_without_losing_valid_intermediate_levels() -> None:
    world = World()
    world.modifiers.clear()
    world.w32(world.object + 0x28C, 0)
    for level in world.levels:
        world.enqueue([level, world.object, 0])
    world.add(-300)
    assert [world.r32(node + 0xC) for node in world.queue_nodes] == [*world.levels[:2], 0, 0, 0]
    world.add(200)  # re-ascend before the pending queue is drained
    world.drain_queue()
    assert world.modifiers == [1, 2, 3, 4]
    assert [n for kind, n in world.events if kind == "grant"] == [1, 2, 3, 4]


def test_positive_multilevel_cascade_is_unchanged() -> None:
    world = World(rank=1, experience=0)
    world.add(450)
    assert (world.rank, world.experience) == (5, 450)
    world.drain_queue()
    assert world.modifiers == [1, 2, 3, 4, 5]
    assert not any(kind.startswith("remove") for kind, _n in world.events)


def test_explicit_level_and_xp_discrepancy_are_not_rolled_back() -> None:
    world = World(rank=5, experience=0)
    world.add(0)
    world.set(0)
    assert world.rank == 5 and not world.events
    # Explicit level assignment still calls the untouched native XP-resetting setter.
    world.run(0x79D76D, [world.levels[1], 0, 0])
    assert (world.rank, world.experience) == (2, 100)
    assert not any(kind.startswith("remove") for kind, _n in world.events)


@pytest.mark.parametrize("multiplayer", [False, True])
def test_mode_ineligible_levels_are_skipped(multiplayer: bool) -> None:
    world = World(multiplayer=multiplayer)
    world.uc.mem_write(world.levels[3] + (0x101 if multiplayer else 0x102), b"\x01")
    world.add(-75)
    assert world.rank == 3


def test_equal_thresholds_choose_highest_rank_deterministically() -> None:
    world = World(thresholds=(0, 100, 100, 300, 400))
    world.add(-300)
    assert (world.rank, world.experience) == (3, 150)


def test_no_eligible_records_preserve_level_and_remaining_xp() -> None:
    world = World()
    for level in world.levels:
        world.uc.mem_write(level + 0x102, b"\x01")
    world.add(-300)
    assert (world.rank, world.experience) == (5, 150)
    assert not world.events


def test_duplicate_object_upgrades_use_native_remove_once() -> None:
    world = World()
    world.w32(world.levels[3] + 0x4C, world.r32(world.levels[4] + 0x4C))
    world.w32(world.levels[3] + 0x50, world.r32(world.levels[4] + 0x50))
    world.add(-300)
    assert [n for kind, n in world.events if kind == "remove-upgrade"] == [5, 3]


def test_positive_float_overflow_is_not_misread_as_negative_xp() -> None:
    world = World(experience=2**32)
    world.add(-1024)
    assert (world.rank, world.experience) == (5, 2**32 - 1024)
    assert not world.events


def test_other_objects_pending_grants_are_untouched() -> None:
    world = World()
    world.enqueue([world.levels[4], world.object, 0])
    world.w32(world.queue_nodes[0] + 8, 456)
    world.add(-300)
    assert world.r32(world.queue_nodes[0] + 0xC) == world.levels[4]


def test_native_remove_upgrade_clears_bits_and_visits_module_remove_path() -> None:
    world = World()
    del world.services[xp.OBJECT_REMOVE_LEVEL_UPGRADE]
    modules, module, interface_table, implementation, implementation_table = (
        0x1009100,
        0x1009200,
        0x1009300,
        0x1009400,
        0x1009500,
    )
    world.w32(world.object + 0x24C, modules)
    world.w32(modules, module)
    world.w32(module + 0xC, interface_table)
    world.w32(interface_table + 0x28, 0xF11000)
    world.w32(implementation, implementation_table)
    world.w32(implementation_table + 0xC, 0xF11010)
    world.w32(implementation_table + 0x1C, 0xF11020)
    world.w32(implementation_table + 0x20, 0xF11030)
    world.w32(implementation_table + 0x24, 0xF11040)
    notified: list[int] = []

    def unapply(_args: list[int]) -> int:
        assert world.uc.reg_read(world.regs.UC_X86_REG_ECX) == implementation
        notified.append(world.r32(world.object + 0x28C))
        return 0

    world.services.update(
        {
            0xF11000: (0, lambda args: implementation),
            0x68FD31: (2, lambda args: 0),
            0xF11010: (1, lambda args: 1),
            0xF11020: (0, lambda args: 0),
            0xF11030: (0, unapply),
            0xF11040: (1, lambda args: 0),
        }
    )
    world.add(-75)
    assert world.rank == 4
    assert notified == [sum(1 << n for n in range(1, 5))]


def test_missing_collection_is_safe() -> None:
    world = World()
    world.services[xp.EXPERIENCE_LEVEL_COLLECTION] = (1, lambda args: 0)
    world.add(-300)
    assert (world.rank, world.experience) == (5, 150)
    assert not world.events


@pytest.mark.parametrize("during_upgrade", [False, True])
def test_reentrant_xp_loss_aborts_an_already_executing_native_grant(during_upgrade: bool) -> None:
    world = World()
    world.modifiers = [1, 2, 3, 4]
    world.w32(world.object + 0x28C, sum(1 << n for n in range(1, 5)))
    world.enqueue([world.levels[4], world.object, 0])

    def add_modifier(args: list[int]) -> int:
        world.modifiers.append(world.r32(args[0]))
        return 0

    def add_upgrade(args: list[int]) -> int:
        bit = world.r32(args[0] + 0x38)
        world.w32(world.object + 0x28C, world.r32(world.object + 0x28C) | (1 << bit))
        return 0

    entry = 0x69388B if during_upgrade else 0x68F1A8
    world.services[0xF12000] = (1, add_upgrade if during_upgrade else add_modifier)
    if during_upgrade:
        world.services[0x68F1A8] = (2, add_modifier)
    # A native-shaped effect callback grants its effect and then issues a real nested XP loss.
    a = Asm(entry)
    a.emit(b"\x55\x8b\xec\x56\x8b\xf1\xff\x75\x08")
    a.call_absolute(0xF12000)
    a.emit(b"\x68", struct.pack("<f", 1))
    a.emit(b"\x6a\x00\x6a\x00\x6a\x00\x6a\x00\x68", struct.pack("<f", -300))
    a.emit(b"\x8b\x8e\x6c\x02\x00\x00")
    a.call_absolute(0x79D68D)
    a.emit(b"\x5e\xc9\xc2", struct.pack("<H", 4 if during_upgrade else 8))
    world.uc.mem_write(entry, a.finish())
    # Enter after the native grant's SEH prologue with its verified frame/implicit registers.
    frame, sp = 0x1107000, 0x1106F00
    world.w32(frame + 0x14, world.queue_nodes[0])
    world.uc.reg_write(world.regs.UC_X86_REG_EBP, frame)
    world.uc.reg_write(world.regs.UC_X86_REG_ESP, sp)
    world.uc.reg_write(world.regs.UC_X86_REG_ESI, world.levels[4])
    world.uc.reg_write(world.regs.UC_X86_REG_EBX, world.object)
    world.uc.reg_write(world.regs.UC_X86_REG_EDI, 0)
    world.uc.emu_start(0x82133D, 0x82146D, count=50000)
    assert world.uc.reg_read(world.regs.UC_X86_REG_EIP) == 0x82146D
    assert world.uc.reg_read(world.regs.UC_X86_REG_ESP) == sp
    assert world.uc.reg_read(world.regs.UC_X86_REG_EBP) == frame
    assert (world.rank, world.experience) == (2, 150)
    assert world.modifiers == [1, 2]
    assert world.r32(world.queue_nodes[0] + 0xC) == 0


_BINARY = Path(__file__).resolve().parents[2] / "tools" / "BFME-FILES" / "game.dat.backup"


@pytest.mark.full
@pytest.mark.skipif(not _BINARY.is_file(), reason="requires the local supported RotWK binary")
def test_supported_binary_and_negative_power_patch_compose(tmp_path: Path) -> None:
    original = _BINARY.read_bytes()
    first = bytearray(original)
    second = bytearray(original)
    down, power = ExperienceLevelDownPatch(xp_cap=False), LevelGrantSpecialPowerPatch()
    down.apply(first)
    power.apply(first)
    power.apply(second)
    down.apply(second)
    assert all(patch.verify(data) == [] for data in [first, second] for patch in [down, power])
    assert _BINARY.read_bytes() == original
