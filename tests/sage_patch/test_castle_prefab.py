"""Execute the emitted state machine and check patch composition without game data."""

from __future__ import annotations

import struct

import pytest

from sage_patch import addresses as ad
from sage_patch.patches import castle_unpack_buttons as cb
from sage_patch.patches import castle_unpack_clearance as cc
from sage_patch.patches.castle_unpack_buttons import CastleUnpackButtonsPatch
from sage_patch.patches.castle_unpack_clearance import CastleUnpackClearancePatch
from sage_patch.patches.experimental import castle_prefab as cp
from sage_patch.patches.experimental import map_transition as mt
from sage_patch.patches.experimental.map_transition import MapTransitionPatch
from sage_patch.utils import file_offset, u32

from .synthetic import _sparse_image


def _image() -> bytearray:
    return _sparse_image(
        {
            **cp.ANCHORS,
            **{va: entry[0] for va, entry in cp.HOOKS.items()},
            **{cp._slot_va(i): u32(ad.SCRIPT_ACTION_EPILOGUE) for i in cp.ACTION_IDS},
        }
    )


def test_install_verify_and_reject_taken_slot() -> None:
    data = _image()
    patch = cp.CastlePrefabPatch()
    patch.apply(data)
    assert patch.verify(data) == []
    for action_id, target in [(381, 0x7CE925), (493, 0x7CE928)]:
        assert data[file_offset(data, cp._slot_va(action_id)) :][:4] == u32(target)
    data = _image()
    struct.pack_into("<I", data, file_offset(data, cp._slot_va(cp.ACTION_IDS[0])), 0x12345678)
    before = bytes(data)
    with pytest.raises(ValueError, match="conflict"):
        patch.apply(data)
    assert bytes(data) == before


def test_worldbuilder_registration_and_verify() -> None:
    data = _sparse_image({**cp.WB_ANCHORS, cp.WB_HOOK: cp.WB_STOCK})
    patch = cp.CastlePrefabWorldbuilderPatch()
    patch.apply(data)
    assert patch.verify(data) == []


@pytest.mark.parametrize("reverse", [False, True])
def test_castle_and_map_transition_composition(reverse: bool) -> None:
    # The helper gathers the existing patches' anchors, rather than granting either permission
    # to overwrite the other's code. Both application orders must retain both caves.

    planted = {**cp.ANCHORS, **{va: entry[0] for va, entry in cp.HOOKS.items()}}
    planted.update({cp._slot_va(i): u32(ad.SCRIPT_ACTION_EPILOGUE) for i in cp.ACTION_IDS})
    planted.update(mt.ANCHORS)
    planted[ad.SCRIPT_ACTION_EPILOGUE] = cp.ANCHORS[ad.SCRIPT_ACTION_EPILOGUE]
    planted[mt.HOOK_VA] = mt.HOOK_ORIGINAL
    planted[mt.TABLE_SLOT_VA] = mt.TABLE_SLOT_STOCK
    planted[ad.GAME_LOGIC_UPDATE_VTABLE_SLOT] = u32(mt.HOOK_VA)

    for module in (cb, cc):
        planted.update(module.ANCHORS)
        planted[module.HOOK_VA] = module.HOOK_ORIGINAL
    data = _sparse_image(planted)
    patches = [
        cp.CastlePrefabPatch(),
        CastleUnpackButtonsPatch(),
        CastleUnpackClearancePatch(),
        MapTransitionPatch(),
    ]
    if reverse:
        patches.reverse()
    for patch in patches:
        patch.apply(data)
    for patch in patches:
        assert patch.verify(data) == []
