"""Fast-forward: the frame cap is a whole multiple of `FramesPerSecondLimit`, and 1 puts it back."""

from __future__ import annotations

import pytest

from sage_live.backends.game_speed import base_rate, set_speed, speed
from sage_live.backends.live_patch import LivePatchError
from sage_patch.addresses import (
    GAME_ENGINE,
    GAME_ENGINE_MAX_FPS,
    GLOBAL_DATA,
    GLOBAL_DATA_FPS_LIMIT,
)
from tests.sage_live.fake_process import FakeProcess

ENGINE = 0x05000000
DATA = 0x06000000


def game(limit: int = 30, cap: int = 30) -> FakeProcess:
    process = FakeProcess()
    process.u32(GAME_ENGINE, ENGINE)
    process.u32(GLOBAL_DATA, DATA)
    process.u32(DATA + GLOBAL_DATA_FPS_LIMIT, limit)
    process.u32(ENGINE + GAME_ENGINE_MAX_FPS, cap)
    return process


def cap(process: FakeProcess) -> int:
    raw = process.read(ENGINE + GAME_ENGINE_MAX_FPS, 4)
    assert raw is not None
    return int.from_bytes(raw, "little")


def test_fast_multiplies_the_ini_limit_and_normal_restores_it() -> None:
    process = game()
    assert base_rate(process.read) == 30 and speed(process.read) == 1
    set_speed(process, 10)
    assert cap(process) == 300 and speed(process.read) == 10
    set_speed(process, 1)
    assert cap(process) == 30 and speed(process.read) == 1


def test_a_cap_the_engine_raised_on_its_own_is_not_read_as_fast() -> None:
    assert speed(game(cap=45).read) == 1


def test_a_game_that_is_not_up_or_not_capped_is_refused() -> None:
    with pytest.raises(LivePatchError, match="not up"):
        set_speed(FakeProcess(), 10)
    assert speed(FakeProcess().read) == 1
    with pytest.raises(LivePatchError, match="no frame cap"):
        set_speed(game(limit=0, cap=0), 10)
