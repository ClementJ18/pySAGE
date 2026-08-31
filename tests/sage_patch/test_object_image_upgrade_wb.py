"""Structural tests for the Worldbuilder half of ObjectImageUpgrade.

The editor needs the Behavior registration and ModuleData parser, but none of the game-side
presentation runtime. These tests keep that boundary explicit: the Worldbuilder entry reuses
TooltipUpgrade's runtime factory and owns only a small ModuleData factory and field table.
"""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

from sage_patch.addresses import (
    WORLDBUILDER_OBJECT_IMAGE_UPGRADE_APPEND_FIELD_TABLE,
    WORLDBUILDER_OBJECT_IMAGE_UPGRADE_ASCIISTRING_CTOR,
    WORLDBUILDER_OBJECT_IMAGE_UPGRADE_ASCIISTRING_DTOR,
    WORLDBUILDER_OBJECT_IMAGE_UPGRADE_ASCIISTRING_PARSER,
    WORLDBUILDER_OBJECT_IMAGE_UPGRADE_BUILD_UPGRADE_FIELDS,
    WORLDBUILDER_OBJECT_IMAGE_UPGRADE_MODULEDATA_CTOR,
    WORLDBUILDER_OBJECT_IMAGE_UPGRADE_OPERATOR_NEW,
    WORLDBUILDER_OBJECT_IMAGE_UPGRADE_REGISTER,
    WORLDBUILDER_OBJECT_IMAGE_UPGRADE_REGISTER_CALL,
    WORLDBUILDER_OBJECT_IMAGE_UPGRADE_REGISTER_CLEANUP,
    WORLDBUILDER_OBJECT_IMAGE_UPGRADE_RUNTIME_FACTORY_STOCK,
)
from sage_patch.patches import ObjectImageUpgradeWorldbuilderPatch as Exported
from sage_patch.patches.object_image_upgrade import (
    _WORLDBUILDER_INTERFACE_MASK,
    _WORLDBUILDER_REGISTER_BYTES,
    _WORLDBUILDER_REGISTER_PREFIX,
    BLOCK_NAME,
    FIELDS,
    WORLDBUILDER_SECTION_NAME,
    ObjectImageUpgradeWorldbuilderPatch,
)
from sage_patch.registry import PATCHES
from sage_patch.utils import find_section, va_to_offset
from tests.sage_patch.synthetic import object_image_upgrade_worldbuilder_image

_WORLDBUILDER = Path(__file__).resolve().parents[2] / "sage_patch" / "Worldbuilder.exe.backup"


@pytest.fixture
def image() -> bytearray:
    return object_image_upgrade_worldbuilder_image()


@pytest.fixture(scope="module")
def original_worldbuilder() -> bytes:
    return _WORLDBUILDER.read_bytes()


def _call_targets(body: bytes, base: int) -> list[int]:
    return [
        base + index + 5 + struct.unpack_from("<i", body, index + 1)[0]
        for index in range(len(body) - 4)
        if body[index] == 0xE8
    ]


def test_apply_verify_detect_round_trip(image: bytearray) -> None:
    patch = ObjectImageUpgradeWorldbuilderPatch()
    assert patch.detect(image) is None
    patch.apply(image)
    assert patch.verify(image) == []
    assert patch.detect(image) is not None


def test_patch_is_exported_and_registered() -> None:
    assert Exported is ObjectImageUpgradeWorldbuilderPatch
    assert PATCHES["object-image-upgrade-wb"] is ObjectImageUpgradeWorldbuilderPatch


def test_second_application_fails_without_corrupting_the_first(image: bytearray) -> None:
    patch = ObjectImageUpgradeWorldbuilderPatch()
    patch.apply(image)
    before = bytes(image)
    with pytest.raises(ValueError, match="unexpected Worldbuilder build|overlapping patch"):
        patch.apply(image)
    assert bytes(image) == before


def test_private_field_table_uses_worldbuilder_parser_and_shared_offsets(
    image: bytearray,
) -> None:
    patch = ObjectImageUpgradeWorldbuilderPatch()
    patch.apply(image)
    base, _section_off, _size = find_section(image, WORLDBUILDER_SECTION_NAME) or pytest.fail(
        "missing Worldbuilder section"
    )
    layout = patch._layout(base)
    table_off = va_to_offset(image, layout["table"])
    assert table_off is not None

    for index, (name, offset) in enumerate(FIELDS):
        name_va, parser, userdata, got_offset = struct.unpack_from(
            "<4I", image, table_off + index * 16
        )
        name_off = va_to_offset(image, name_va)
        assert name_off is not None
        assert image[name_off : name_off + len(name) + 1] == name.encode() + b"\0"
        assert parser == WORLDBUILDER_OBJECT_IMAGE_UPGRADE_ASCIISTRING_PARSER
        assert userdata == 0
        assert got_offset == offset

    assert image[table_off + 32 : table_off + 48] == bytes(16)


def test_registration_replays_tooltip_then_adds_the_new_name(image: bytearray) -> None:
    patch = ObjectImageUpgradeWorldbuilderPatch()
    patch.apply(image)
    base, section_off, _size = find_section(image, WORLDBUILDER_SECTION_NAME) or pytest.fail(
        "missing Worldbuilder section"
    )
    code = patch._assemble(base)
    begin = section_off + code.label_va("register") - base
    end = section_off + code.label_va("moduledata_factory") - base
    body = bytes(image[begin:end])
    targets = _call_targets(body, code.label_va("register"))

    assert targets == [
        WORLDBUILDER_OBJECT_IMAGE_UPGRADE_REGISTER,
        WORLDBUILDER_OBJECT_IMAGE_UPGRADE_ASCIISTRING_CTOR,
        WORLDBUILDER_OBJECT_IMAGE_UPGRADE_REGISTER,
        WORLDBUILDER_OBJECT_IMAGE_UPGRADE_ASCIISTRING_DTOR,
    ]
    assert body.startswith(bytes.fromhex("558bec56578bf1"))
    assert body.endswith(bytes.fromhex("83c4045f5e5dc21800"))
    assert b"\x68" + struct.pack("<I", _WORLDBUILDER_INTERFACE_MASK) in body
    assert (
        b"\x68" + struct.pack("<I", WORLDBUILDER_OBJECT_IMAGE_UPGRADE_RUNTIME_FACTORY_STOCK) in body
    )


def test_moduledata_factory_is_parser_only_and_keeps_tooltip_layout(image: bytearray) -> None:
    patch = ObjectImageUpgradeWorldbuilderPatch()
    patch.apply(image)
    base, section_off, _size = find_section(image, WORLDBUILDER_SECTION_NAME) or pytest.fail(
        "missing Worldbuilder section"
    )
    code = patch._assemble(base)
    begin = section_off + code.label_va("moduledata_factory") - base
    end = section_off + code.label_va("build_fields") - base
    body = bytes(image[begin:end])
    targets = _call_targets(body, code.label_va("moduledata_factory"))

    assert b"\x68\x40\x01\x00\x00" in body  # allocate TooltipUpgrade's 0x140 bytes
    assert targets == [
        WORLDBUILDER_OBJECT_IMAGE_UPGRADE_OPERATOR_NEW,
        WORLDBUILDER_OBJECT_IMAGE_UPGRADE_MODULEDATA_CTOR,
        WORLDBUILDER_OBJECT_IMAGE_UPGRADE_REGISTER_CLEANUP,
    ]
    # No custom Runtime/UpgradeMux vtable and no game-side sidecar occur in this twin.
    assert b"\xc7\x46\x10" not in body


def test_build_fields_mirrors_upgrade_base_then_appends_private_table(image: bytearray) -> None:
    patch = ObjectImageUpgradeWorldbuilderPatch()
    patch.apply(image)
    base, section_off, _size = find_section(image, WORLDBUILDER_SECTION_NAME) or pytest.fail(
        "missing Worldbuilder section"
    )
    code = patch._assemble(base)
    begin = section_off + code.label_va("build_fields") - base
    body = bytes(image[begin : section_off + len(patch._build(base))])
    targets = _call_targets(body, code.label_va("build_fields"))
    assert targets == [
        WORLDBUILDER_OBJECT_IMAGE_UPGRADE_BUILD_UPGRADE_FIELDS,
        WORLDBUILDER_OBJECT_IMAGE_UPGRADE_APPEND_FIELD_TABLE,
        WORLDBUILDER_OBJECT_IMAGE_UPGRADE_APPEND_FIELD_TABLE,
    ]
    # Worldbuilder's buildUpgradeFields leaves `push 8` on the stack until append consumes it.
    # Both parser-context loads must therefore be EBP-relative exactly like stock TooltipUpgrade;
    # an ESP-relative load after the first call reads the callback's return address and crashes.
    assert body.startswith(bytes.fromhex("558bec6a08"))
    assert body.count(bytes.fromhex("8b4d08")) == 2
    assert bytes.fromhex("8b4c2408") not in body
    assert bytes.fromhex("8b4c240c") not in body
    assert body.endswith(bytes.fromhex("5dc3"))


def test_worldbuilder_cave_is_executable_but_not_writable(image: bytearray) -> None:
    ObjectImageUpgradeWorldbuilderPatch().apply(image)
    e_lfanew = struct.unpack_from("<I", image, 0x3C)[0]
    section_count = struct.unpack_from("<H", image, e_lfanew + 6)[0]
    section_table = e_lfanew + 24 + struct.unpack_from("<H", image, e_lfanew + 20)[0]
    for index in range(section_count):
        header = section_table + index * 40
        name = bytes(image[header : header + 8]).rstrip(b"\0").decode()
        if name == WORLDBUILDER_SECTION_NAME:
            characteristics = struct.unpack_from("<I", image, header + 36)[0]
            assert characteristics & 0x20000000  # MEM_EXECUTE
            assert characteristics & 0x40000000  # MEM_READ
            assert not characteristics & 0x80000000  # MEM_WRITE
            return
    pytest.fail(f"missing {WORLDBUILDER_SECTION_NAME} section header")


def test_wrong_tooltip_factory_arguments_are_rejected(image: bytearray) -> None:
    prefix_va = WORLDBUILDER_OBJECT_IMAGE_UPGRADE_REGISTER_CALL - len(_WORLDBUILDER_REGISTER_PREFIX)
    off = va_to_offset(image, prefix_va)
    assert off is not None
    image[off + 1] ^= 0x01
    with pytest.raises(ValueError, match="factory arguments"):
        ObjectImageUpgradeWorldbuilderPatch().apply(image)


def test_wrong_registration_call_is_rejected(image: bytearray) -> None:
    off = va_to_offset(image, WORLDBUILDER_OBJECT_IMAGE_UPGRADE_REGISTER_CALL)
    assert off is not None
    image[off : off + len(_WORLDBUILDER_REGISTER_BYTES)] = bytes(len(_WORLDBUILDER_REGISTER_BYTES))
    with pytest.raises(ValueError, match="overlapping patch"):
        ObjectImageUpgradeWorldbuilderPatch().apply(image)


def test_aslr_image_is_rejected(image: bytearray) -> None:
    e_lfanew = struct.unpack_from("<I", image, 0x3C)[0]
    struct.pack_into("<H", image, e_lfanew + 24 + 70, 0x0040)
    with pytest.raises(ValueError, match="ASLR"):
        ObjectImageUpgradeWorldbuilderPatch().apply(image)


@pytest.mark.skipif(not _WORLDBUILDER.exists(), reason="needs the original Worldbuilder.exe")
class TestOriginalWorldbuilder:
    def test_registration_window_matches_the_original(self, original_worldbuilder: bytes) -> None:
        prefix_va = WORLDBUILDER_OBJECT_IMAGE_UPGRADE_REGISTER_CALL - len(
            _WORLDBUILDER_REGISTER_PREFIX
        )
        prefix_off = va_to_offset(original_worldbuilder, prefix_va)
        call_off = va_to_offset(
            original_worldbuilder, WORLDBUILDER_OBJECT_IMAGE_UPGRADE_REGISTER_CALL
        )
        assert prefix_off is not None and call_off is not None
        assert original_worldbuilder[prefix_off:call_off] == _WORLDBUILDER_REGISTER_PREFIX
        assert original_worldbuilder[call_off : call_off + 5] == _WORLDBUILDER_REGISTER_BYTES

    def test_apply_verify_detect_round_trip(self, original_worldbuilder: bytes) -> None:
        data = bytearray(original_worldbuilder)
        patch = ObjectImageUpgradeWorldbuilderPatch()
        patch.apply(data)
        assert patch.verify(data) == []
        assert patch.detect(data) is not None

    def test_cave_contains_the_expected_names(self, original_worldbuilder: bytes) -> None:
        data = bytearray(original_worldbuilder)
        patch = ObjectImageUpgradeWorldbuilderPatch()
        patch.apply(data)
        base, off, _size = find_section(data, WORLDBUILDER_SECTION_NAME) or pytest.fail(
            "missing Worldbuilder section"
        )
        cave = bytes(data[off : off + len(patch._build(base))])
        for name in (BLOCK_NAME, *(name for name, _offset in FIELDS)):
            assert name.encode() + b"\0" in cave
