"""Execute native upgrade callbacks/readiness and capped XP using existing x86 fixtures."""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

from sage_ini.engine import Engine, dump_engine, parse_engine
from sage_patch import (
    ExperienceLevelDownPatch,
    LevelGrantSpecialPowerPatch,
    UpgradeModuleRemovalPatch,
)
from sage_patch.__main__ import main
from sage_patch.addresses import (
    EXPERIENCE_XP_CAP_WINDOWS,
    UPGRADE_MODULE_REMOVAL_ANCHORS,
    UPGRADE_MODULE_REMOVAL_WINDOWS,
)
from sage_patch.asm import Asm
from sage_patch.patches import experience_level_down as xp
from sage_patch.patches import upgrade_module_removal as upgrades
from sage_patch.registry import PATCHES
from sage_patch.sagepatch import detect_patches, manifest, rebuild
from sage_patch.utils import file_offset, find_section
from tests.sage_patch.test_experience_level_down import World, image


def upgrade_image() -> bytearray:
    data = image()
    for va, old in UPGRADE_MODULE_REMOVAL_ANCHORS.items():
        off = file_offset(data, va)
        data[off : off + len(old)] = old
    return data


@pytest.mark.parametrize("enabled", [False, True])
def test_xp_cap_option_detection_and_manifest_rebuild(enabled: bool) -> None:
    data = image()
    patch = ExperienceLevelDownPatch(xp_cap=enabled)
    patch.apply(data)
    detected = ExperienceLevelDownPatch.detect(data)
    assert detected is not None and detected.options() == {"xp_cap": enabled}
    assert ExperienceLevelDownPatch(xp_cap=not enabled).verify(data)
    found = [p for p in detect_patches(data) if p.name == patch.name]
    entries, problems = manifest(found)
    assert problems == [] and len(entries) == 1
    engine = parse_engine(dump_engine(Engine(patches=entries)))
    rebuilt, problems = rebuild(engine)
    assert problems == [] and len(rebuilt) == 1
    fresh = image()
    rebuilt[0].apply(fresh)
    assert fresh == data
    assert "experience-xp-cap" not in PATCHES


def test_xp_cap_detection_requires_verified_helper_and_hooks() -> None:
    data = image()
    patch = ExperienceLevelDownPatch(xp_cap=True)
    patch.apply(data)
    located = find_section(data, xp._XP_CAP_SECTION)
    assert located is not None
    for off in [located[1], *(file_offset(data, va) for va in EXPERIENCE_XP_CAP_WINDOWS)]:
        damaged = bytearray(data)
        damaged[off] ^= 0xFF
        assert patch.verify(damaged)
        assert ExperienceLevelDownPatch.detect(damaged) is None


@pytest.mark.parametrize("cap", [False, True])
def test_registration_application_and_idempotence(cap: bool, tmp_path: Path) -> None:
    patch = ExperienceLevelDownPatch(xp_cap=True) if cap else UpgradeModuleRemovalPatch()
    data = upgrade_image()
    assert PATCHES[patch.name] is type(patch)
    assert not patch.experimental and not patch.runtime_verified
    assert patch.detect(data) is None
    source, output = tmp_path / "source.dat", tmp_path / "patched.dat"
    source.write_bytes(data)
    flags = ["--xp-cap"] if cap else []
    assert main(["apply", patch.name, *flags, "--in", str(source), "--out", str(output)]) == 0
    assert main(["verify", patch.name, *flags, str(output)]) == 0
    patch.apply(data)
    assert output.read_bytes() == data and patch.verify(data) == []
    assert isinstance(patch.detect(data), type(patch))
    before = bytes(data)
    with pytest.raises(ValueError, match="already carries"):
        patch.apply(data)
    assert data == before


@pytest.mark.parametrize("va", list(UPGRADE_MODULE_REMOVAL_ANCHORS))
def test_upgrade_originals_checked_before_any_write(va: int) -> None:
    data = upgrade_image()
    data[file_offset(data, va)] ^= 0xFF
    snapshot = bytes(data)
    with pytest.raises(ValueError, match="unexpected build"):
        UpgradeModuleRemovalPatch().apply(data)
    assert data == snapshot


@pytest.mark.parametrize("va", list(EXPERIENCE_XP_CAP_WINDOWS))
def test_cap_originals_checked_before_any_write(va: int) -> None:
    data = image()
    data[file_offset(data, va)] ^= 0xFF
    snapshot = bytes(data)
    with pytest.raises(ValueError):
        ExperienceLevelDownPatch(xp_cap=True).apply(data)
    assert data == snapshot


@pytest.mark.parametrize("cap", [False, True])
def test_only_fingerprinted_windows_change_and_detours_decode(cap: bool) -> None:
    capstone = pytest.importorskip("capstone")
    decoder = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    data = upgrade_image()
    before = bytes(data)
    patch = ExperienceLevelDownPatch(xp_cap=True) if cap else UpgradeModuleRemovalPatch()
    patch.apply(data)
    windows = EXPERIENCE_XP_CAP_WINDOWS if cap else UPGRADE_MODULE_REMOVAL_WINDOWS
    all_windows = {**xp._WINDOWS, **windows} if cap else windows
    changed = {
        file_offset(before, va) + n for va, old in all_windows.items() for n in range(len(old))
    }
    assert all(
        a == b or n in changed
        for n, (a, b) in enumerate(
            zip(before[0x200:], data[0x200 : len(before)], strict=True), 0x200
        )
    )
    located = find_section(data, xp._XP_CAP_SECTION if cap else upgrades.SECTION_NAME)
    assert located is not None
    base, off, size = located
    instructions = list(decoder.disasm(bytes(data[off : off + size]), base))
    assert sum(i.size for i in instructions) == size
    for va, old in windows.items():
        assert sum(i.size for i in decoder.disasm(old, va)) == len(old)
        new = bytes(data[file_offset(data, va) : file_offset(data, va) + len(old)])
        assert sum(i.size for i in decoder.disasm(new, va)) == len(old)
        if new[0] == 0xE9:
            target = va + 5 + struct.unpack_from("<i", new, 1)[0]
            assert target in {i.address for i in instructions}
        damaged = bytearray(data)
        damaged[file_offset(data, va)] ^= 0xFF
        assert patch.verify(damaged)
    data[off] ^= 0xFF
    assert patch.verify(data)


def capped_world(**kwargs: object) -> World:
    world = World(**kwargs)
    base = 0xF20000
    world.uc.mem_write(
        base, xp._cap_assemble(base, xp._assemble(world.base).label_va("down")).finish()
    )
    for va, new in xp._cap_windows(base).items():
        world.uc.mem_write(va, new)
    return world


@pytest.mark.parametrize(
    "rank,old,delta,new_rank,new_xp",
    [
        (2, 150, 25, 2, 175),
        (4, 350, 50, 5, 400),
        (4, 350, 500, 5, 400),
        (5, 400, 500, 5, 400),
        (5, 400, -75, 4, 325),
        (5, 400, -300, 2, 100),
        (5, 650, -100, 4, 300),
        (5, 650, 100, 5, 400),
        (5, 650, 0, 5, 400),
        (1, -1e20, 2e20, 5, 400),
        (2, 150, float("inf"), 5, 400),
    ],
)
def test_relative_cap_and_loss(
    rank: int, old: float, delta: float, new_rank: int, new_xp: float
) -> None:
    world = capped_world(rank=rank, experience=old)
    world.add(delta)
    assert (world.rank, world.experience) == (new_rank, new_xp)


@pytest.mark.parametrize("setter", [False, True])
@pytest.mark.parametrize("max_rank", [2, 3, 5, 0, -1])
def test_configured_maximum_and_absolute_setter(setter: bool, max_rank: int) -> None:
    world = capped_world(rank=1, experience=0)
    world.w32(world.tracker + 0x28, max_rank)
    expected = max_rank if max_rank > 0 else 5
    if setter:
        world.set(10000)
    else:
        world.add(10000)
    assert (world.rank, world.experience) == (expected, (expected - 1) * 100)
    world.drain_queue()
    world.add(-100)
    world.drain_queue()
    assert world.rank == max(1, expected - 1)
    world.add(10000)
    world.drain_queue()
    assert (world.rank, world.experience) == (expected, (expected - 1) * 100)
    assert world.player_upgrades == {999}


@pytest.mark.parametrize("multiplayer", [False, True])
def test_ceiling_uses_native_mode_filter(multiplayer: bool) -> None:
    world = capped_world(rank=1, experience=0, multiplayer=multiplayer)
    world.uc.mem_write(world.levels[4] + (0x101 if multiplayer else 0x102), b"\x01")
    world.add(1000)
    assert (world.rank, world.experience) == (4, 300)


def test_effective_scaling_negative_absolute_and_lazy_loaded_reserve() -> None:
    world = capped_world(experience=1500)
    world.add(100, scale=True, factor=-1)
    assert (world.rank, world.experience) == (4, 300)
    world.set(10000)
    assert (world.rank, world.experience) == (5, 400)
    world.set(75)
    assert (world.rank, world.experience) == (1, 75)
    # A restored tracker is normalized on its next XP operation, not during deserialization.
    world.wfloat(world.tracker + 0x10, 1500)
    world.w32(world.tracker + 0x24, 5)
    world.w32(world.tracker + 0xC, 5)
    world.add(-100)
    assert (world.rank, world.experience) == (4, 300)


def test_cap_preserves_explicit_rank_grants_without_an_actual_xp_loss() -> None:
    world = capped_world(rank=2, experience=150)
    world.run(0x79D76D, [world.levels[4], 0, 0])
    world.w32(world.tracker + 0x28, 3)
    world.add(0)
    assert (world.rank, world.experience) == (5, 200)
    world.set(10000)
    assert (world.rank, world.experience) == (5, 200)


def test_cap_retains_x87_adjustment_and_full_sse_registers() -> None:
    world = capped_world(experience=400)
    pattern = 0x112233445566778899AABBCCDDEEFF00
    world.uc.reg_write(world.regs.UC_X86_REG_XMM2, pattern)
    world.wfloat(0x100F000, -0.5)
    world.add(200, adjust=True)
    assert (world.rank, world.experience) == (4, 300)
    assert world.uc.reg_read(world.regs.UC_X86_REG_XMM2) == pattern
    world.set(10000)
    assert (world.rank, world.experience) == (5, 400)
    assert world.uc.reg_read(world.regs.UC_X86_REG_XMM2) == pattern


def test_configured_maximum_rejects_equal_threshold_higher_ranks() -> None:
    world = capped_world(rank=1, experience=0, thresholds=(0, 100, 200, 200, 200))
    world.w32(world.tracker + 0x28, 3)
    world.add(1000)
    assert (world.rank, world.experience) == (3, 200)


@pytest.mark.parametrize("setter", [False, True])
def test_other_tracker_subclass_keeps_stock_behavior(setter: bool) -> None:
    world = capped_world(rank=2, experience=150)
    world.w32(world.vtable + 0x10, 0xF17000)
    world.uc.mem_write(0xF17000, bytes.fromhex("c20800"))
    # No level-changing callback is needed when the increase stays below the next threshold.
    if setter:
        world.set(175)
    else:
        world.add(25)
    assert (world.rank, world.experience) == (2, 175)


def test_missing_or_empty_eligible_collection_does_not_invent_a_ceiling() -> None:
    for missing in [False, True]:
        world = capped_world(rank=2, experience=150)
        if missing:
            world.services[xp.EXPERIENCE_LEVEL_COLLECTION] = (1, lambda args: 0)
        else:
            for level in world.levels:
                world.uc.mem_write(level + 0x102, b"\x01")
        world.add(500)
        assert (world.rank, world.experience) == (2, 650)


class UpgradeWorld(World):
    """Native mux/event/removal/pause/readiness; model object services and allocation."""

    modules = 0x1020000
    module = 0x1020100
    mux = module + 0x10
    module_data = 0x1021000
    power_module = 0x1022000
    power = power_module + 0x10
    power_data = 0x1023000
    power_template = 0x1024000
    now = 0x1025000

    def __init__(
        self, *, permanent: bool | None = None, shared: bool = False, patched: bool = True
    ) -> None:
        super().__init__()
        for va, blob in UPGRADE_MODULE_REMOVAL_ANCHORS.items():
            self.uc.mem_write(va, blob)
        if patched:
            base = 0xF30000
            self.uc.mem_write(base, upgrades.build_code(base))
            for va, new in upgrades._windows(base).items():
                self.uc.mem_write(va, new)
        del self.services[xp.OBJECT_REMOVE_LEVEL_UPGRADE]
        self.w32(self.object + 0x24C, self.modules)
        self.w32(self.modules, self.module)
        self.w32(self.modules + 4, self.power_module)
        self.w32(self.module + 4, self.module_data)
        self.w32(self.module + 8, self.object)
        self.w32(self.module + 0xC, 0x1026000)
        self.w32(0x1026000 + 0x28, 0xF14000)
        self.w32(0x1026000 + 0x20, 0xF14010)
        self.w32(self.mux, 0xC6EA50)
        self.w32(self.module_data + 0x138, self.power_template)
        # Constructor/default evidence is exercised separately; omitted means its zero byte.
        if permanent is not None:
            self.uc.mem_write(self.module_data + 0x136, bytes([permanent]))
        self.uc.mem_write(self.module_data + 0x13C, b"\x01")  # preserve recharge on unpause
        self.w32(self.module_data + 8, 1 << 5)  # TriggeredBy the rank-five OBJECT upgrade
        self.w32(self.power_module + 4, self.power_data)
        self.w32(self.power_module + 8, self.object)
        self.w32(self.power_module + 0xC, 0x1026100)
        self.w32(0x1026100 + 0x28, 0xF14010)
        self.w32(0x1026100 + 0x20, 0xF14020)
        self.w32(self.power, 0x1026200)
        self.w32(0x1026200 + 0x18, 0xF14030)
        self.w32(0x1026200 + 0x24, 0x896756)
        self.w32(0x1026200 + 8, 0xF15000)
        self.uc.mem_write(0xF15000, bytes.fromhex("d9eec3"))  # x87 percentage return
        self.w32(self.power_data + 8, 0x1027000)
        self.w32(0x1027000 + 4, self.power_template)
        self.uc.mem_write(self.power_template + 0x59, bytes([shared]))
        self.w32(0xDE412C, self.now)
        self.w32(self.now + 0x40, 100)
        self.w32(self.power + 8, 100)
        self.w32(self.power + 0xC, 1)  # StartsPaused
        self.w32(self.power + 0x10, 100)
        self.services.update(
            {
                0xF14000: (0, lambda args: self.mux),
                0xF14010: (0, lambda args: 0),
                0xF14020: (0, lambda args: self.power),
                0xF14030: (0, lambda args: self.power_template),
                0x5EA666: (0, self.zero_bits),
                0x9F3A3C: (1, lambda args: 0),
                0x68FD31: (2, self.event_bits),
                0x44DDEC: (1, lambda args: 0),
                0x68B678: (0, lambda args: 0x1028000),
                0x6AD26F: (1, lambda args: self.r32(self.power + 8)),
                0xA3CF28: (0, self.memset),
                0x62684D: (2, self.status_change),
                0x68B53C: (0, lambda args: 0),
            }
        )

    def zero_bits(self, _args: list[int]) -> int:
        self.uc.mem_write(self.uc.reg_read(self.regs.UC_X86_REG_ECX), bytes(0x90))
        return 0

    def event_bits(self, args: list[int]) -> int:
        assert args[0] == 0  # native removal event
        dest = self.uc.reg_read(self.regs.UC_X86_REG_ECX)
        self.uc.mem_write(dest, bytes(0x90))
        self.w32(dest + (args[1] // 32) * 4, 1 << (args[1] % 32))
        return 0

    def memset(self, _args: list[int]) -> int:
        # Cdecl leaves all three arguments for the native caller to clean up.
        sp = self.uc.reg_read(self.regs.UC_X86_REG_ESP)
        args = [self.r32(sp + n * 4) for n in (1, 2, 3)]
        self.uc.mem_write(args[0], bytes([args[1]]) * args[2])
        return args[0]

    def status_change(self, args: list[int]) -> int:
        assert self.uc.reg_read(self.regs.UC_X86_REG_ECX) == self.object
        self.events.append(("status", args[1]))
        assert args[0] == 0x12
        return 0

    def ready(self) -> bool:
        self.run(0x896C72, [], this=self.power)
        return bool(self.uc.reg_read(self.regs.UC_X86_REG_EAX) & 0xFF)

    def unlock(self) -> None:
        self.w32(self.object + 0x28C, self.r32(self.object + 0x28C) | (1 << 5))
        self.run(0x8D26BF, [self.object + 0x28C], this=self.mux)

    def remove(self) -> None:
        self.run(0x691438, [0x100D000 + 5 * 0x40], this=self.object)


@pytest.mark.parametrize("permanent", [None, False, True])
@pytest.mark.parametrize("shared", [False, True])
def test_native_unlock_remove_regrant_and_actual_readiness(
    permanent: bool | None, shared: bool
) -> None:
    world = UpgradeWorld(permanent=permanent, shared=shared)
    assert not world.ready()
    world.unlock()
    assert world.ready()
    world.remove()
    assert world.ready() is bool(permanent)
    assert world.uc.mem_read(world.mux + 4, 1) == b"\x00"
    world.unlock()
    assert world.ready()
    assert world.r32(world.power + 0xC) == 0


def test_stock_bug_is_reproduced_and_shared_pause_bypass_is_reproduced() -> None:
    world = UpgradeWorld(patched=False)
    world.unlock()
    world.remove()
    assert world.ready()  # original getter skipped the entire removal implementation
    world = UpgradeWorld(shared=True, patched=False)
    assert world.ready()  # the native shared timer branch ignored StartsPaused


def test_native_constructor_keeps_permanent_default_false() -> None:
    world = UpgradeWorld()
    world.uc.mem_write(world.module_data + 0x136, b"\xff")
    world.run(0x6531CE, [], this=world.module_data)
    assert world.uc.mem_read(world.module_data + 0x136, 1) == b"\x00"


def test_native_trigger_conflict_and_model_condition_event_semantics() -> None:
    world = UpgradeWorld()
    world.run(0x8D26BF, [world.object + 0x28C], this=world.mux)
    # The initial level fixture owns rank-five upgrade, so reset its bit for this check.
    world.w32(world.object + 0x28C, 0)
    world.uc.mem_write(world.mux + 4, b"\x00")
    world.run(0x8D26BF, [world.object + 0x28C], this=world.mux)
    assert world.uc.mem_read(world.mux + 4, 1) == b"\x00"
    world.w32(world.module_data + 8 + 0x90, 1 << 5)  # conflicting upgrade blocks grant
    world.unlock()
    assert world.uc.mem_read(world.mux + 4, 1) == b"\x00"
    world.w32(world.module_data + 8 + 0x90, 0)
    world.unlock()
    assert world.ready()
    world.w32(world.module_data + 0x128, 3)
    world.w32(world.object + 0x10C, 1 << 3)
    world.remove()
    assert world.r32(world.object + 0x10C) == 0
    assert not world.ready()


@pytest.mark.parametrize("shared", [False, True])
@pytest.mark.parametrize("ready_frame", [100, 500])
def test_pause_resume_preserves_native_cooldown(shared: bool, ready_frame: int) -> None:
    world = UpgradeWorld(shared=shared)
    world.unlock()
    world.w32(world.power + 8, ready_frame)
    world.w32(world.power + 4, 400)
    world.remove()
    assert not world.ready()
    assert world.r32(world.power + 8) == ready_frame
    world.w32(world.now + 0x40, 160)
    world.unlock()
    assert world.r32(world.power + 8) == ready_frame + 60
    assert world.r32(world.power + 4) == 400
    assert world.ready() is (ready_frame == 100)


@pytest.mark.parametrize("active", [False, True])
@pytest.mark.parametrize("permanent", [False, True])
def test_general_reset_keeps_native_active_and_permanent_semantics(
    active: bool, permanent: bool
) -> None:
    world = UpgradeWorld(permanent=permanent)
    if active:
        world.unlock()
    count = world.r32(world.power + 0xC)
    world.run(0x68E083, [], this=world.object)
    assert world.r32(world.object + 0x28C) == 0
    assert world.r32(world.power + 0xC) == count + int(active and not permanent)


def test_second_native_module_removal_and_multilevel_loss() -> None:
    world = UpgradeWorld()
    world.unlock()
    world.w32(world.mux, 0xC6E9D8)  # another real vtable, removal calls status-bit clearing
    world.add(-300)
    assert (world.rank, world.experience) == (2, 150)
    assert ("status", 0) in world.events
    assert world.player_upgrades == {999}
    assert world.uc.mem_read(world.mux + 4, 1) == b"\x00"


def test_cap_and_multilevel_loss_use_the_real_special_power_removal() -> None:
    world = UpgradeWorld()
    base = 0xF20000
    world.uc.mem_write(
        base, xp._cap_assemble(base, xp._assemble(world.base).label_va("down")).finish()
    )
    for va, new in xp._cap_windows(base).items():
        world.uc.mem_write(va, new)
    world.unlock()
    assert world.ready()
    world.add(-300)  # 450 old XP is normalized to 400 before the drain
    assert (world.rank, world.experience) == (2, 100)
    assert not world.ready()
    world.add(1000)
    world.drain_queue()
    assert (world.rank, world.experience) == (5, 400)
    # The fixture models effect storage during delayed grants; run the actual native
    # upgrade event once those bits are present to test the power's regrant callback.
    world.unlock()
    assert world.ready()


def test_nested_removal_and_reset_do_not_repeat_the_active_callback() -> None:
    world = UpgradeWorld()
    world.unlock()
    callback = 0xF16000
    table = 0x1029000
    world.uc.mem_write(table, bytes(world.uc.mem_read(0xC6EA50, 64)))
    world.w32(table + 0x20, callback)
    world.w32(world.mux, table)
    # A native-shaped removal callback repeats this upgrade's removal and invokes reset.
    a = Asm(callback)
    a.emit(b"\x56\x8b\xf1\xff\x05", struct.pack("<I", 0x102A000))
    a.emit(b"\x68", struct.pack("<I", 0x100D000 + 5 * 0x40))
    a.emit(b"\x8b\x4e\xf8")
    a.call_absolute(0x691438)
    a.emit(b"\x8b\x4e\xf8")
    a.call_absolute(0x68E083)
    a.emit(b"\x8b\xce")
    a.call_absolute(0x8B9701)
    a.emit(b"\x5e\xc3")
    world.uc.mem_write(callback, a.finish())
    world.remove()
    assert world.r32(0x102A000) == 1
    assert world.r32(world.power + 0xC) == 1
    assert world.uc.mem_read(world.mux + 4, 1) == b"\x00"


_BINARY = Path(__file__).resolve().parents[2] / "tools" / "BFME-FILES" / "game.dat.backup"


@pytest.mark.full
@pytest.mark.skipif(not _BINARY.is_file(), reason="requires the local supported RotWK binary")
@pytest.mark.parametrize("upgrade_first", [False, True])
def test_real_binary_composition_and_original_preservation(upgrade_first: bool) -> None:
    original = _BINARY.read_bytes()
    data = bytearray(original)
    patches = [
        LevelGrantSpecialPowerPatch(),
        ExperienceLevelDownPatch(xp_cap=True),
    ]
    if upgrade_first:
        patches.insert(0, UpgradeModuleRemovalPatch())
    else:
        patches.append(UpgradeModuleRemovalPatch())
    for patch in patches:
        patch.apply(data)
    assert all(patch.verify(data) == [] for patch in patches)
    assert _BINARY.read_bytes() == original
