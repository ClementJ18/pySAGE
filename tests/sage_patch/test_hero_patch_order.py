"""HeroBar classifier detours must not invalidate the independent horde death hook."""

from __future__ import annotations

import itertools

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
