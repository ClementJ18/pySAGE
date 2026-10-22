"""HeroBar classifier detours must not invalidate the independent horde death hook."""

from __future__ import annotations

import itertools
import runpy
from pathlib import Path

import pytest

from sage_patch.patches.experimental import hero_horde_death as death
from sage_patch.patches.herobar import HeroBarPatch
from sage_patch.patches.horde_herobar import ANCHORS, HOOK, ORIGINAL, HordeHerobarPatch
from sage_patch.utils import file_offset

from .synthetic import synthetic_image


@pytest.mark.parametrize("order", list(itertools.permutations(range(3))))
def test_hero_bar_death_and_health_compose_in_any_order(order):
    data = synthetic_image()
    planted = {**ANCHORS, **death.ANCHORS, HOOK: ORIGINAL, death.HOOK: death.ORIGINAL}
    for va, blob in planted.items():
        off = file_offset(data, va)
        data[off : off + len(blob)] = blob
    patches = [HeroBarPatch(), death.HeroHordeDeathPatch(), HordeHerobarPatch()]
    for index in order:
        patches[index].apply(data)
    for patch in patches:
        assert not patch.verify(data), patch.name


def test_local_applymypatches_order_without_installing():
    root = Path(__file__).resolve().parents[2]
    script = root / "applymypatches.py"
    backup = root / "tools/BFME-FILES/game.dat.backup"
    if not script.exists() or not backup.exists():
        pytest.skip("local patch selection / game binary are not distributed")
    # run_path does not execute the script's guarded __main__: no mod-starter output is touched.
    patches = runpy.run_path(str(script), run_name="patch_order_test")["patches"]
    original = backup.read_bytes()
    data = bytearray(original)
    for patch in patches:
        patch.apply(data)
    for patch in patches:
        assert not patch.verify(data), patch.name
    assert backup.read_bytes() == original
