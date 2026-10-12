"""Installation, signatures and composable parser rows for CastlePrefab buttons."""

from __future__ import annotations

import struct

import pytest

from sage_patch import addresses as ad
from sage_patch.patches import command_point_cost as cost
from sage_patch.patches.experimental import castle_prefab as cp
from sage_patch.registry import PATCHES
from sage_patch.utils import file_offset, u32

from .synthetic import _sparse_image
from .test_queue_ignore_cp import STOCK_FIELDS, _string_vas


def _image() -> bytearray:
    names = _string_vas()
    rows = b"".join(
        struct.pack("<IIII", names[name], ad.INI_PARSE_BOOL, 0, offset)
        for name, offset in STOCK_FIELDS
    ) + bytes(16)
    return _sparse_image(
        {
            **cost.ANCHORS,
            **{v: e[0] for v, e in cost.CommandPointCostPatch._HOOKS.items()},
            **cp.ANCHORS,
            **{va: e[0] for va, e in cp.HOOKS.items()},
            **{cp._slot_va(i): u32(ad.SCRIPT_ACTION_EPILOGUE) for i in cp.ACTION_IDS},
            **ad.CASTLE_COMMAND_ANCHORS,
            **{va: e[0] for va, e in cp.COMMAND_HOOKS.items()},
            ad.COMMAND_BUTTON_CTOR: ad.COMMAND_BUTTON_CTOR_BYTES,
            ad.COMMAND_BUTTON_FIELD_TABLE: rows,
            **{va: name.encode("ascii") + b"\0" for name, va in names.items()},
            **{
                va: bytes([opcode]) + u32(ad.COMMAND_BUTTON_FIELD_TABLE)
                for va, opcode in zip(
                    ad.COMMAND_BUTTON_FIELD_TABLE_REFS,
                    ad.COMMAND_BUTTON_FIELD_TABLE_REF_OPCODES,
                    strict=True,
                )
            },
        }
    )


def test_dependency_install_verify_and_retail_guards() -> None:
    data = _image()
    patch = cp.CastlePrefabCommandButtonPatch()
    before = bytes(data)
    with pytest.raises(ValueError, match="apply castle-prefab first"):
        patch.apply(data)
    assert bytes(data) == before
    cp.CastlePrefabPatch().apply(data)
    stock_rows = cp._command_table(data)
    untouched = {
        va: bytes(data[file_offset(data, va) :][: len(blob)])
        for va, blob in ad.CASTLE_COMMAND_ANCHORS.items()
    }
    patch.apply(data)
    assert patch.verify(data) == []
    assert cp.CastlePrefabPatch().verify(data) == []
    assert cp._command_table(data)[: len(stock_rows)] == stock_rows
    assert cp._command_table(data)[-1][2:] == (0, 0)  # parser never receives a struct field
    for va, expected in untouched.items():
        assert bytes(data[file_offset(data, va) :][: len(expected)]) == expected
    before = bytes(data)
    with pytest.raises(ValueError, match="conflict"):
        patch.apply(data)
    assert bytes(data) == before
    assert PATCHES[patch.name] is type(patch)
    assert patch.ini_surface().fields[0].name == cp.COMMAND_FIELD


@pytest.mark.parametrize("va", list(cp.COMMAND_HOOKS) + list(ad.CASTLE_COMMAND_ANCHORS))
def test_bad_signature_rejected_before_writes(va: int) -> None:
    data = _image()
    cp.CastlePrefabPatch().apply(data)
    data[file_offset(data, va)] ^= 1
    before = bytes(data)
    with pytest.raises(ValueError):
        cp.CastlePrefabCommandButtonPatch().apply(data)
    assert bytes(data) == before


def test_deterministic_ids_and_real_collision() -> None:
    assert cp._prefab_id(" RohanCastleLarge\t") == cp._prefab_id("RohanCastleLarge")
    assert cp._prefab_id("rohanCastleLarge") != cp._prefab_id("RohanCastleLarge")
    assert cp._prefab_id("Castle_12443256909038804325") == 0x677D4D74
    assert cp._prefab_id("Castle_9189280535366551549") == 0x677D4D74


@pytest.mark.parametrize("name", ["", "a b", "x" * 256, "ä", "\x00"])
def test_invalid_names(name: str) -> None:
    with pytest.raises(ValueError):
        cp._prefab_id(name)


@pytest.mark.parametrize("reverse", [False, True])
def test_composes_with_command_point_cost_in_both_orders(reverse: bool) -> None:
    data = _image()
    cp.CastlePrefabPatch().apply(data)
    patches = [cp.CastlePrefabCommandButtonPatch(), cost.CommandPointCostPatch()]
    if reverse:
        patches.reverse()
    for patch in patches:
        patch.apply(data)
    for patch in patches:
        assert patch.verify(data) == []
    assert cp.CastlePrefabPatch().verify(data) == []
    names = {cp.read_cstring(data, row[0]) for row in cp._command_table(data)}
    assert {"CastlePrefab", "CommandPointCost"} <= names
