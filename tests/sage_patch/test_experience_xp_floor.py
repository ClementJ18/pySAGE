"""Execute dynamic XP floors without changing the level-down cave or hook set."""

from __future__ import annotations

import math

import pytest

from sage_patch import ExperienceLevelDownPatch
from sage_patch.addresses import EXPERIENCE_XP_CAP_WINDOWS
from sage_patch.patches import experience_level_down as xp
from sage_patch.utils import file_offset, find_section
from tests.sage_patch.test_experience_follow_up import capped_world
from tests.sage_patch.test_experience_level_down import image


@pytest.mark.parametrize("floor", [0, 1, 15])
@pytest.mark.parametrize("setter", [False, True])
@pytest.mark.parametrize("old", [1, 35, 450])
def test_floor_preserves_loss_detection_and_lost_effect_removal(
    floor: int, setter: bool, old: float
) -> None:
    rank = 5 if old == 450 else 2
    world = capped_world(rank=rank, experience=old, thresholds=(floor, 100, 200, 300, 400))
    if setter:
        world.set(-100)
    else:
        world.add(-1000)
    assert world.experience == floor
    # Correction from below/equal floor must not demote an explicitly granted level.
    assert world.rank == (1 if old > floor else rank)
    if old > floor:
        assert world.modifiers == [1]
        assert world.r32(world.object + 0x28C) == (1 << 1)
        assert world.events.count(("remove-upgrade", rank)) == 1
    else:
        assert not world.events
    assert world.player_upgrades == {999}


def test_requested_examples_and_reascending_from_floor() -> None:
    world = capped_world(rank=1, experience=1, thresholds=(1, 100, 200, 300, 400))
    world.add(-100)
    assert (world.rank, world.experience) == (1, 1)
    world = capped_world(rank=2, experience=35, thresholds=(1, 100, 200, 300, 400))
    world.add(-100)
    assert (world.rank, world.experience) == (1, 1)
    world.add(100)
    world.drain_queue()
    assert (world.rank, world.experience) == (2, 101)
    world.add(10000)
    assert (world.rank, world.experience) == (5, 400)


@pytest.mark.parametrize("floor", [0, 1])
@pytest.mark.parametrize("old", [-1e20, -50, float("-inf")])
@pytest.mark.parametrize("setter", [False, True])
def test_negative_reserves_and_infinity_are_corrected_without_false_loss(
    floor: int, old: float, setter: bool
) -> None:
    world = capped_world(rank=2, experience=old, thresholds=(floor, 100, 200, 300, 400))
    if setter:
        world.set(float("-inf"))
    else:
        world.add(-1000)
    assert (world.rank, world.experience) == (2, floor)
    assert not world.events
    world.add(10)
    assert world.experience == floor + 10


@pytest.mark.parametrize("old", [16777216.0, 1e8, 1e9])
@pytest.mark.parametrize("floor", [0, 1, 15])
def test_float32_cancellation_hits_exact_floor_and_still_demotes(old: float, floor: int) -> None:
    world = capped_world(rank=3, experience=old, thresholds=(floor, 100, 2000000000))
    pattern = 0x112233445566778899AABBCCDDEEFF00
    world.uc.reg_write(world.regs.UC_X86_REG_XMM2, pattern)
    world.add(-2 * old)
    assert (world.rank, world.experience) == (1, floor)
    assert world.modifiers == [1]
    assert [value for event, value in world.events if event == "remove-upgrade"] == [3, 2]
    assert world.player_upgrades == {999}
    assert world.uc.reg_read(world.regs.UC_X86_REG_XMM2) == pattern


@pytest.mark.parametrize("multiplayer", [False, True])
def test_floor_uses_mode_filter_and_lowest_eligible_rank(multiplayer: bool) -> None:
    world = capped_world(multiplayer=multiplayer)
    world.uc.mem_write(world.levels[0] + (0x101 if multiplayer else 0x102), b"\x01")
    world.add(-1000)
    assert (world.rank, world.experience) == (2, 100)


@pytest.mark.parametrize("setter", [False, True])
def test_single_eligible_level_is_both_floor_and_ceiling(setter: bool) -> None:
    world = capped_world(rank=1, experience=1, thresholds=(1, 100, 200, 300, 400))
    world.w32(world.tracker + 0x28, 1)
    if setter:
        world.set(-100)
    else:
        world.add(-100)
    assert (world.rank, world.experience) == (1, 1)
    world.add(1000)
    assert (world.rank, world.experience) == (1, 1)


def test_floor_applies_after_sse_and_x87_effective_delta() -> None:
    world = capped_world(rank=5, experience=450, thresholds=(1, 100, 200, 300, 400))
    pattern = 0x112233445566778899AABBCCDDEEFF00
    world.uc.reg_write(world.regs.UC_X86_REG_XMM2, pattern)
    world.add(1000, scale=True, factor=-1)
    assert (world.rank, world.experience) == (1, 1)
    assert world.uc.reg_read(world.regs.UC_X86_REG_XMM2) == pattern
    world.add(1000)
    world.wfloat(0x100F000, -1)
    world.add(1000, adjust=True)
    assert (world.rank, world.experience) == (1, 1)


def test_nan_remains_unordered_and_is_not_a_floor_trigger() -> None:
    world = capped_world(rank=2, experience=150, thresholds=(1, 100, 200, 300, 400))
    world.add(float("nan"))
    assert math.isnan(world.experience)
    assert world.rank == 2 and not world.events


def test_floor_changes_only_existing_cap_windows_and_not_the_down_cave() -> None:
    data = image()
    down = ExperienceLevelDownPatch(xp_cap=False)
    down.apply(data)
    located = find_section(data, xp.SECTION_NAME)
    assert located is not None
    base, off, size = located
    original = bytes(data)
    cave = bytes(data[off : off + size])
    hooks = {
        va: bytes(data[file_offset(data, va) : file_offset(data, va) + len(old)])
        for va, old in xp._WINDOWS.items()
    }
    cap = ExperienceLevelDownPatch(xp_cap=True)
    data = image()
    cap.apply(data)
    assert bytes(data[off : off + size]) == cave == xp.build_code(base)
    assert all(
        bytes(data[file_offset(data, va) : file_offset(data, va) + len(blob)]) == blob
        for va, blob in hooks.items()
    )
    assert set(EXPERIENCE_XP_CAP_WINDOWS) == {0x79D6CD, 0x79D6E1, 0x79D921, 0x79D17B}
    assert down.verify(data) and cap.verify(data) == []
    changed = {
        file_offset(original, va) + n
        for va, old in EXPERIENCE_XP_CAP_WINDOWS.items()
        for n in range(len(old))
    }
    assert all(
        a == b or n in changed
        for n, (a, b) in enumerate(
            zip(original[0x200:], data[0x200 : len(original)], strict=True), 0x200
        )
    )
    cap_section = find_section(data, xp._XP_CAP_SECTION)
    assert cap_section is not None
    assert (
        bytes(data[cap_section[1] : cap_section[1] + cap_section[2]])
        == xp._cap_assemble(cap_section[0], xp._assemble(base).label_va("down")).finish()
    )


def test_old_upper_only_cave_is_not_silently_accepted_or_overwritten() -> None:
    data = image()
    cap = ExperienceLevelDownPatch(xp_cap=True)
    cap.apply(data)
    located = find_section(data, xp._XP_CAP_SECTION)
    assert located is not None
    # Stand in for any incompatible helper body, including an older upper-only build.
    data[located[1]] ^= 0xFF
    snapshot = bytes(data)
    assert cap.verify(data)
    with pytest.raises(ValueError, match="already carries"):
        cap.apply(data)
    assert data == snapshot
