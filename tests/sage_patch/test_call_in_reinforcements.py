"""Tests for `call-in-reinforcements`, which gives stub script action 543 a body.

The patch rewrites one dword - the action's jump-table slot - and reads three engine routines it
does not rewrite, so the structural tests are about the fingerprint: every one of those sites has
to fail loudly on anything else, and the slot in particular has to still be a stub rather than an
action the engine implements. The sibling file runs the cave.
"""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

from sage_patch import addresses as ad
from sage_patch.patches.call_in_reinforcements import (
    ACTION_ID,
    ANCHORS,
    SECTION_NAME,
    TABLE_SLOT_STOCK,
    TABLE_SLOT_VA,
    CallInReinforcementsPatch,
    build_code,
)
from sage_patch.registry import PATCHES
from sage_patch.utils import file_offset, find_section

from .synthetic import call_in_reinforcements_image

REAL_GAME_DAT = Path(__file__).resolve().parents[2] / "game.dat"


def _applied() -> bytearray:
    data = call_in_reinforcements_image()
    CallInReinforcementsPatch().apply(data)
    return data


def test_it_is_registered_and_settled() -> None:
    assert PATCHES["call-in-reinforcements"] is CallInReinforcementsPatch
    assert not CallInReinforcementsPatch.experimental


def test_the_slot_is_action_543s() -> None:
    assert ACTION_ID == 543
    assert TABLE_SLOT_VA == ad.SCRIPT_ACTION_JUMP_TABLE + 543 * 4
    assert TABLE_SLOT_STOCK == struct.pack("<I", ad.SCRIPT_ACTION_EPILOGUE)


@pytest.mark.skipif(not REAL_GAME_DAT.exists(), reason="needs the checkout's game.dat")
def test_the_real_binary_holds_every_stock_site() -> None:
    data = REAL_GAME_DAT.read_bytes()
    for va, expected in {**ANCHORS, TABLE_SLOT_VA: TABLE_SLOT_STOCK}.items():
        off = file_offset(data, va)
        assert data[off : off + len(expected)] == expected, f"{va:#010x}"


def test_apply_verify_detect_round_trip() -> None:
    data = _applied()
    assert CallInReinforcementsPatch().verify(data) == []
    assert CallInReinforcementsPatch.detect(data) is not None
    base = find_section(data, SECTION_NAME)[0]
    assert struct.unpack_from("<I", data, file_offset(data, TABLE_SLOT_VA))[0] == base


def test_an_unpatched_image_is_not_detected() -> None:
    data = call_in_reinforcements_image()
    assert CallInReinforcementsPatch().verify(data)
    assert CallInReinforcementsPatch.detect(data) is None


def test_it_refuses_a_second_application() -> None:
    data = _applied()
    with pytest.raises(ValueError):
        CallInReinforcementsPatch().apply(data)


def test_it_refuses_an_action_the_engine_implements() -> None:
    """A slot that no longer holds the epilogue is a live action, and repointing it would replace
    whatever the engine does there."""
    data = call_in_reinforcements_image()
    struct.pack_into("<I", data, file_offset(data, TABLE_SLOT_VA), 0x007CE925)
    with pytest.raises(ValueError, match="unexpected build"):
        CallInReinforcementsPatch().apply(data)


@pytest.mark.parametrize("va", sorted(ANCHORS), ids=lambda va: f"{va:#010x}")
def test_it_refuses_a_moved_routine(va: int) -> None:
    data = call_in_reinforcements_image()
    data[file_offset(data, va)] ^= 0xFF
    with pytest.raises(ValueError, match="unexpected build"):
        CallInReinforcementsPatch().apply(data)


def test_verify_notices_a_repointed_slot() -> None:
    data = _applied()
    struct.pack_into("<I", data, file_offset(data, TABLE_SLOT_VA), ad.SCRIPT_ACTION_EPILOGUE)
    assert any("dispatches to" in problem for problem in CallInReinforcementsPatch().verify(data))


def test_the_body_does_not_depend_on_where_it_lands() -> None:
    """Every engine reference is rel32 or absolute, so two bases give two bodies of one length."""
    assert len(build_code(0x00ED3000)) == len(build_code(0x01200000))
