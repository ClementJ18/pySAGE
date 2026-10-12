"""Structural tests for GrantScienceUpgrade and its Worldbuilder parser twin."""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

from sage_ini.engine import parse_type
from sage_patch.addresses import (
    GAME_DATA_ASCIISTRING_PARSER,
    GRANT_SCIENCE_UPGRADE_REGISTER_CALL,
    OBJECT_GET_CONTROLLING_PLAYER,
    OBJECT_IMAGE_UPGRADE_REGISTER,
    OBJECT_IMAGE_UPGRADE_RUNTIME_FACTORY_STOCK,
    OBJECT_IMAGE_UPGRADE_UPGRADE_VTABLE,
    PLAYER_GRANT_SCIENCE,
    SCIENCE_STORE_FRIENDLY_NAME_TO_SCIENCE,
    THE_SCIENCE_STORE,
    WORLDBUILDER_GRANT_SCIENCE_UPGRADE_REGISTER_CALL,
    WORLDBUILDER_OBJECT_IMAGE_UPGRADE_ASCIISTRING_PARSER,
    WORLDBUILDER_OBJECT_IMAGE_UPGRADE_REGISTER,
    WORLDBUILDER_OBJECT_IMAGE_UPGRADE_RUNTIME_FACTORY_STOCK,
)
from sage_patch.patches import GrantScienceUpgradePatch as Exported
from sage_patch.patches import GrantScienceUpgradeWorldbuilderPatch as ExportedWorldbuilder
from sage_patch.patches.grant_science_upgrade import (
    BLOCK_NAME,
    FIELD,
    SECTION_NAME,
    WORLDBUILDER_SECTION_NAME,
    GrantScienceUpgradePatch,
    GrantScienceUpgradeWorldbuilderPatch,
)
from sage_patch.patches.object_image_upgrade import (
    ObjectImageUpgradePatch,
    ObjectImageUpgradeWorldbuilderPatch,
)
from sage_patch.registry import PATCHES
from sage_patch.utils import find_section, va_to_offset
from tests.sage_patch.synthetic import grant_science_upgrade_worldbuilder_image

_GAME_DAT = Path(__file__).resolve().parents[2] / "game.dat"


@pytest.fixture
def image() -> bytearray:
    if not _GAME_DAT.exists():
        pytest.skip("repository game.dat fixture is absent")
    return bytearray(_GAME_DAT.read_bytes())


@pytest.fixture
def wb_image() -> bytearray:
    return grant_science_upgrade_worldbuilder_image()


def _body(image: bytearray, section: str, patch, start: str, end: str | None) -> bytes:
    base, section_off, _size = find_section(image, section) or pytest.fail("missing section")
    code = patch._assemble(base)
    begin = section_off + code.label_va(start) - base
    finish = section_off + (
        code.label_va(end) - base if end else code.base_va - base + len(code.finish())
    )
    return bytes(image[begin:finish])


def _call_targets(body: bytes, va: int) -> list[int]:
    return [
        va + index + 5 + struct.unpack_from("<i", body, index + 1)[0]
        for index in range(len(body) - 4)
        if body[index] == 0xE8
    ]


def test_apply_verify_and_detect(image: bytearray) -> None:
    patch = GrantScienceUpgradePatch()
    assert patch.detect(image) is None
    patch.apply(image)
    assert patch.verify(image) == []
    assert patch.detect(image) is not None


def test_second_application_fails(image: bytearray) -> None:
    patch = GrantScienceUpgradePatch()
    patch.apply(image)
    with pytest.raises(ValueError, match="unexpected build|overlapping patch"):
        patch.apply(image)


@pytest.mark.parametrize("first_object_image", [True, False])
def test_composes_with_object_image_upgrade(image: bytearray, first_object_image: bool) -> None:
    order = [ObjectImageUpgradePatch(), GrantScienceUpgradePatch()]
    for patch in order if first_object_image else reversed(order):
        patch.apply(image)
    assert all(patch.verify(image) == [] for patch in order)


def test_hook_replaces_only_the_audio_loop_registration_call(image: bytearray) -> None:
    stock = bytes(image)
    GrantScienceUpgradePatch().apply(image)
    off = va_to_offset(image, GRANT_SCIENCE_UPGRADE_REGISTER_CALL)
    assert off is not None
    assert image[off] == 0xE8
    assert image[off - 16 : off] == stock[off - 16 : off]
    assert image[off + 5 : off + 32] == stock[off + 5 : off + 32]


def test_field_table_is_one_ascii_string_row(image: bytearray) -> None:
    patch = GrantScienceUpgradePatch()
    patch.apply(image)
    base, _off, _size = find_section(image, SECTION_NAME) or pytest.fail("missing section")
    row_off = va_to_offset(image, patch._layout(base)["table"])
    assert row_off is not None
    name_va, parser, userdata, offset = struct.unpack_from("<4I", image, row_off)
    name_off = va_to_offset(image, name_va)
    assert name_off is not None
    assert image[name_off : name_off + len(FIELD[0]) + 1] == FIELD[0].encode() + b"\0"
    assert (parser, userdata, offset) == (GAME_DATA_ASCIISTRING_PARSER, 0, 0x138)
    assert image[row_off + 16 : row_off + 32] == bytes(16)


def test_registration_replays_stock_then_adds_wrapped_runtime_factory(image: bytearray) -> None:
    patch = GrantScienceUpgradePatch()
    patch.apply(image)
    base, _off, _size = find_section(image, SECTION_NAME) or pytest.fail("missing section")
    code = patch._assemble(base)
    body = _body(image, SECTION_NAME, patch, "register", "runtime_factory")
    targets = _call_targets(body, code.label_va("register"))
    assert targets.count(OBJECT_IMAGE_UPGRADE_REGISTER) == 2
    # Our entry must register the wrapper that installs Apply, not Tooltip's stock factory.
    assert b"\x68" + struct.pack("<I", code.label_va("runtime_factory")) in body
    assert b"\x68" + struct.pack("<I", OBJECT_IMAGE_UPGRADE_RUNTIME_FACTORY_STOCK) not in body
    assert body.endswith(b"\xc2\x18\x00")


def test_upgrade_vtable_patches_apply_and_unapply_slots(image: bytearray) -> None:
    patch = GrantScienceUpgradePatch()
    patch.apply(image)
    base, _off, _size = find_section(image, SECTION_NAME) or pytest.fail("missing section")
    code = patch._assemble(base)
    table_off = va_to_offset(image, patch._layout(base)["upgrade"])
    stock_off = va_to_offset(image, OBJECT_IMAGE_UPGRADE_UPGRADE_VTABLE)
    assert table_off is not None and stock_off is not None
    assert struct.unpack_from("<I", image, table_off + 0x20)[0] == code.label_va("unapply")
    assert struct.unpack_from("<I", image, table_off + 0x28)[0] == code.label_va("apply")
    for slot in range(0, 0x48, 4):
        if slot not in (0x20, 0x28):
            assert (
                image[table_off + slot : table_off + slot + 4]
                == (image[stock_off + slot : stock_off + slot + 4])
            )


def test_apply_makes_the_script_action_calls_in_order(image: bytearray) -> None:
    patch = GrantScienceUpgradePatch()
    patch.apply(image)
    base, _off, _size = find_section(image, SECTION_NAME) or pytest.fail("missing section")
    code = patch._assemble(base)
    body = _body(image, SECTION_NAME, patch, "apply", "unapply")
    assert b"\x8b\x7e\xf8" in body  # Object* = [mux-8]
    assert b"\x8b\x46\xf4\x05\x38\x01\x00\x00" in body  # &ModuleData->GrantScience
    assert b"\x83\x38\x00" in body  # empty name skips the lookup
    assert b"\x8b\x0d" + struct.pack("<I", THE_SCIENCE_STORE) in body
    assert b"\x83\xf8\xff" in body  # unknown science
    assert _call_targets(body, code.label_va("apply")) == [
        SCIENCE_STORE_FRIENDLY_NAME_TO_SCIENCE,
        OBJECT_GET_CONTROLLING_PLAYER,
        PLAYER_GRANT_SCIENCE,
    ]
    assert body.endswith(b"\x5f\x5e\xc3")


def test_unapply_never_revokes(image: bytearray) -> None:
    patch = GrantScienceUpgradePatch()
    patch.apply(image)
    assert _body(image, SECTION_NAME, patch, "unapply", None) == b"\xc3"


def test_ini_surface_declares_the_new_behavior() -> None:
    surface = GrantScienceUpgradePatch().ini_surface()
    # UpgradeBehavior, not Behavior: the block must inherit TriggeredBy, ConflictsWith and the
    # other UpgradeModule fields, or every use of it lints as unknown-attribute.
    assert [(block.name, block.base) for block in surface.blocks] == [
        (BLOCK_NAME, "UpgradeBehavior")
    ]
    assert [(field.name, field.type) for field in surface.fields] == [
        ("GrantScience", "Ref:sciences")
    ]
    assert parse_type("Ref:sciences")[1] == ""


def test_registered_and_exported() -> None:
    assert Exported is GrantScienceUpgradePatch
    assert ExportedWorldbuilder is GrantScienceUpgradeWorldbuilderPatch
    assert PATCHES["grant-science-upgrade"] is GrantScienceUpgradePatch
    assert PATCHES["grant-science-upgrade-wb"] is GrantScienceUpgradeWorldbuilderPatch


def test_worldbuilder_apply_verify_detect(wb_image: bytearray) -> None:
    patch = GrantScienceUpgradeWorldbuilderPatch()
    assert patch.detect(wb_image) is None
    patch.apply(wb_image)
    assert patch.verify(wb_image) == []
    assert patch.detect(wb_image) is not None
    with pytest.raises(ValueError, match="unexpected Worldbuilder build|overlapping patch"):
        patch.apply(wb_image)


@pytest.mark.parametrize("first_object_image", [True, False])
def test_worldbuilder_composes_with_object_image_upgrade(
    wb_image: bytearray, first_object_image: bool
) -> None:
    order = [ObjectImageUpgradeWorldbuilderPatch(), GrantScienceUpgradeWorldbuilderPatch()]
    for patch in order if first_object_image else reversed(order):
        patch.apply(wb_image)
    assert all(patch.verify(wb_image) == [] for patch in order)


def test_worldbuilder_registers_with_stock_runtime_and_editor_parser(wb_image: bytearray) -> None:
    patch = GrantScienceUpgradeWorldbuilderPatch()
    patch.apply(wb_image)
    base, _off, _size = find_section(wb_image, WORLDBUILDER_SECTION_NAME) or pytest.fail(
        "missing section"
    )
    code = patch._assemble(base)
    body = _body(wb_image, WORLDBUILDER_SECTION_NAME, patch, "register", "moduledata_factory")
    targets = _call_targets(body, code.label_va("register"))
    assert targets.count(WORLDBUILDER_OBJECT_IMAGE_UPGRADE_REGISTER) == 2
    assert (
        b"\x68" + struct.pack("<I", WORLDBUILDER_OBJECT_IMAGE_UPGRADE_RUNTIME_FACTORY_STOCK) in body
    )

    row_off = va_to_offset(wb_image, patch._layout(base)["table"])
    assert row_off is not None
    _name, parser, _userdata, offset = struct.unpack_from("<4I", wb_image, row_off)
    assert (parser, offset) == (WORLDBUILDER_OBJECT_IMAGE_UPGRADE_ASCIISTRING_PARSER, 0x138)

    hook_off = va_to_offset(wb_image, WORLDBUILDER_GRANT_SCIENCE_UPGRADE_REGISTER_CALL)
    assert hook_off is not None
    assert _call_targets(
        bytes(wb_image[hook_off : hook_off + 5]), WORLDBUILDER_GRANT_SCIENCE_UPGRADE_REGISTER_CALL
    ) == [code.label_va("register")]
