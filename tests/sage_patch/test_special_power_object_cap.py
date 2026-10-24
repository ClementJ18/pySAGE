"""Tests for the special-power-object-cap patch: apply, verify, detect and refusal against a
stand-in carrying exactly the bytes the patch asserts. `..._emulated.py` runs the cave."""

from __future__ import annotations

import pytest

from sage_patch.patches.special_power_object_cap import (
    ANCHORS,
    HOOKS,
    SECTION_NAME,
    SpecialPowerObjectCapPatch,
)
from sage_patch.registry import PATCHES
from sage_patch.utils import file_offset, find_section
from tests.sage_patch.synthetic import special_power_object_cap_image


def test_registered() -> None:
    assert PATCHES[SpecialPowerObjectCapPatch.name] is SpecialPowerObjectCapPatch


def test_apply_verify_detect_round_trip() -> None:
    data = special_power_object_cap_image()
    original = bytes(data)
    patch = SpecialPowerObjectCapPatch()
    assert patch.detect(data) is None
    assert patch.verify(data)
    patch.apply(data)
    assert patch.verify(data) == []
    assert isinstance(SpecialPowerObjectCapPatch.detect(data), SpecialPowerObjectCapPatch)
    # Outside the headers and the new section, only the two hook windows changed.
    windows = [(file_offset(original, va), len(stock)) for va, (stock, _r) in HOOKS.items()]
    changed = [
        n
        for n in range(0x400, len(original))
        if original[n] != data[n] and not any(o <= n < o + w for o, w in windows)
    ]
    assert changed == []


def test_second_apply_is_refused_and_atomic() -> None:
    data = special_power_object_cap_image()
    SpecialPowerObjectCapPatch().apply(data)
    snapshot = bytes(data)
    with pytest.raises(ValueError, match="already carries"):
        SpecialPowerObjectCapPatch().apply(data)
    assert data == snapshot


@pytest.mark.parametrize("va", [*ANCHORS, *HOOKS])
def test_unexpected_bytes_are_refused_atomically(va: int) -> None:
    data = special_power_object_cap_image()
    data[file_offset(data, va)] ^= 0xFF
    snapshot = bytes(data)
    with pytest.raises(ValueError, match="expected build"):
        SpecialPowerObjectCapPatch().apply(data)
    assert data == snapshot


@pytest.mark.parametrize("va", [*HOOKS, 0])
def test_verify_reports_a_damaged_hook_or_cave(va: int) -> None:
    data = special_power_object_cap_image()
    SpecialPowerObjectCapPatch().apply(data)
    located = find_section(data, SECTION_NAME)
    assert located is not None
    data[file_offset(data, va) if va else located[1]] ^= 0xFF
    assert SpecialPowerObjectCapPatch().verify(data)
