from __future__ import annotations

import struct
from pathlib import Path

import pytest

from sage_ini.engine import parse_type
from sage_patch.addresses import (
    OBJECT_IMAGE_UPGRADE_REGISTER,
    OBJECT_IMAGE_UPGRADE_UPGRADE_VTABLE,
)
from sage_patch.patches import ObjectImageUpgradePatch as Exported
from sage_patch.patches import object_image_upgrade as object_image_module
from sage_patch.patches.object_image_upgrade import (
    BLOCK_NAME,
    FIELDS,
    SECTION_NAME,
    ObjectImageUpgradePatch,
)
from sage_patch.registry import PATCHES
from sage_patch.utils import find_section, va_to_offset

"""Structural tests for the presentation-only ObjectImageUpgrade module."""

_GAME_DAT = Path(__file__).resolve().parents[2] / "game.dat"


@pytest.fixture
def image() -> bytearray:
    if not _GAME_DAT.exists():
        pytest.skip("repository game.dat fixture is absent")
    return bytearray(_GAME_DAT.read_bytes())


def test_apply_verify_and_detect(image: bytearray) -> None:
    patch = ObjectImageUpgradePatch()
    assert patch.detect(image) is None
    patch.apply(image)
    assert patch.verify(image) == []
    assert patch.detect(image) is not None


def test_second_application_fails(image: bytearray) -> None:
    patch = ObjectImageUpgradePatch()
    patch.apply(image)
    with pytest.raises(ValueError, match="unexpected build|overlapping patch"):
        patch.apply(image)


def test_cave_contains_the_private_field_table(image: bytearray) -> None:
    patch = ObjectImageUpgradePatch()
    patch.apply(image)
    located = find_section(image, SECTION_NAME)
    assert located is not None
    base, _off, _size = located
    layout = patch._layout(base)
    for index, (name, offset) in enumerate(FIELDS):
        row_off = va_to_offset(image, layout["table"] + index * 16)
        assert row_off is not None
        name_va, parser, userdata, got_offset = struct.unpack_from("<4I", image, row_off)
        name_off = va_to_offset(image, name_va)
        assert name_off is not None
        assert image[name_off : name_off + len(name) + 1] == name.encode() + b"\0"
        assert parser != 0
        assert userdata == 0
        assert got_offset == offset


def test_registration_constructs_name_in_reserved_ascii_string(image: bytearray) -> None:
    patch = ObjectImageUpgradePatch()
    patch.apply(image)
    located = find_section(image, SECTION_NAME)
    assert located is not None
    base, section_off, _size = located
    code = patch._assemble(base)
    register_off = section_off + code.label_va("register") - base
    register = bytes(image[register_off : register_off + 96])

    # ECX must capture the reserved four-byte AsciiString before the C-string argument is pushed.
    # Reversing these two instructions makes ECX point at the argument slot, which is popped by
    # AsciiString::set and leaves ModuleFactory::addModule with a dangling name pointer.
    expected = b"\x83\xec\x04\x83\x24\x24\x00\x8b\xcc\x68" + struct.pack(
        "<I", patch._layout(base)["block_name"]
    )
    assert expected in register


def test_registration_calls_stock_wrapper_before_custom_registration(image: bytearray) -> None:
    patch = ObjectImageUpgradePatch()
    patch.apply(image)
    base, section_off, _size = find_section(image, SECTION_NAME) or pytest.fail("missing section")
    code = patch._assemble(base)
    begin = section_off + code.label_va("register") - base
    end = section_off + code.label_va("runtime_factory") - base
    body = bytes(image[begin:end])
    calls = [index for index in range(len(body) - 4) if body[index] == 0xE8]
    targets = [code.label_va("register") + i + 5 + struct.unpack_from("<i", body, i + 1)[0] 
               for i in calls
               ]
    assert targets.count(OBJECT_IMAGE_UPGRADE_REGISTER) == 2
    assert targets.index(OBJECT_IMAGE_UPGRADE_REGISTER) < len(targets) - 1


def test_factories_delegate_to_stock_and_only_replace_upgrade_mux(image: bytearray) -> None:
    patch = ObjectImageUpgradePatch()
    patch.apply(image)
    located = find_section(image, SECTION_NAME)
    assert located is not None
    base, section_off, _size = located
    code = patch._assemble(base)

    runtime_off = section_off + code.label_va("runtime_factory") - base
    runtime_done = section_off + code.label_va("runtime_factory_done") - base
    runtime = bytes(image[runtime_off:runtime_done])
    # push arg2; push arg1; call stock factory; add esp,8
    stock_call = b"\xff\x75\x0c\xff\x75\x08\xe8"
    assert stock_call in runtime
    assert b"\x83\xc4\x08" in runtime
    # The sole post-factory write is [runtime+0x10], the UpgradeMux subobject.
    expected_upgrade_write = b"\xc7\x46\x10" + struct.pack(
        "<I", patch._layout(base)["upgrade"]
    )
    assert runtime.count(expected_upgrade_write) == 1
    assert b"\xc7\x06" not in runtime
    assert b"\xc7\x46\x0c" not in runtime
    assert b"\xc7\x46\x18" not in runtime


def test_ui_hooks_never_read_unconfirmed_object_module_array(image: bytearray) -> None:
    patch = ObjectImageUpgradePatch()
    patch.apply(image)
    located = find_section(image, SECTION_NAME)
    assert located is not None
    base, section_off, _size = located
    code = patch._assemble(base)

    for start, end in (("select_hook", "button_hook"), ("button_hook", None)):
        begin = section_off + code.label_va(start) - base
        finish = section_off + (
            code.label_va(end) - base
            if end
            else code.base_va - base + len(code.finish())
        )
        hook = bytes(image[begin:finish])
        assert b"\x8b\x9f\x4c\x02\x00\x00" not in hook
        assert b"\x39\x39" in hook


def test_sidecar_uses_20_byte_rows_and_expected_capacity() -> None:
    assert object_image_module._ROW_SIZE == 0x14
    assert object_image_module._SIDECAR_SIZE == 0xA000


def test_ui_hooks_match_object_and_object_id_in_20_byte_rows(image: bytearray) -> None:
    patch = ObjectImageUpgradePatch()
    patch.apply(image)
    located = find_section(image, SECTION_NAME)
    assert located is not None
    base, section_off, _size = located
    code = patch._assemble(base)

    for start, end, image_offset in (
        ("select_hook", "button_hook", 0x0C),
        ("button_hook", None, 0x10),
    ):
        begin = section_off + code.label_va(start) - base
        finish = section_off + (
            code.label_va(end) - base
            if end
            else code.base_va - base + len(code.finish())
        )
        hook = bytes(image[begin:finish])
        assert b"\x8b\x77\x74" in hook  # current ObjectID = [Object+74]
        object_match = hook.index(b"\x39\x39")
        id_match = hook.index(b"\x39\x71\x04", object_match)
        image_load = hook.index(b"\x8b\x59" + bytes([image_offset]), id_match)
        assert b"\x8b\x59" + bytes([image_offset]) + b"\x85\xdb" in hook
        assert b"\x8b\xeb" in hook
        assert b"\x83\xc1\x14" in hook
        assert object_match < id_match < image_load


def test_apply_uses_object_key_and_ascii_string_addresses(image: bytearray) -> None:
    patch = ObjectImageUpgradePatch()
    patch.apply(image)
    base, section_off, _size = find_section(image, SECTION_NAME) or pytest.fail("missing section")
    code = patch._assemble(base)
    begin = section_off + code.label_va("apply") - base
    end = section_off + code.label_va("unapply") - base
    body = bytes(image[begin:end])
    assert b"\x8b\x7e\xf8" in body  # [UpgradeMux-8] = Object*
    assert b"\x8b\x57\x74" in body  # ObjectID = [Object+74]
    assert b"\x8b\x47\x74\x89\x43\x04" in body  # store row.ObjectID
    assert b"\x89\x6b\x08" in body  # store row.source
    assert b"\x8d\x85\x38\x01\x00\x00\x50" in body
    assert b"\x8d\x85\x3c\x01\x00\x00\x50" in body
    assert b"\x8b\x77\x84" not in body


def test_apply_reuses_exact_or_same_pointer_stale_row_at_tail(image: bytearray) -> None:
    patch = ObjectImageUpgradePatch()
    patch.apply(image)
    base, section_off, _size = find_section(image, SECTION_NAME) or pytest.fail("missing section")
    code = patch._assemble(base)
    begin = section_off + code.label_va("apply") - base
    end = section_off + code.label_va("unapply") - base
    body = bytes(image[begin:end])

    # A stale same-pointer/different-ID row is a candidate; an exact Object/ID/source row takes
    # precedence. Then copy every later 20-byte row left. The
    # vacated tail becomes apply_slot, so A -> B -> A has physical order B,A and A wins again.
    object_match = body.index(b"\x39\x3b")
    id_match = body.index(b"\x39\x53\x04", object_match)
    stale_free_check = body.index(b"\x83\x3c\x24\x00", id_match)
    stale_remember = body.index(b"\x89\x1c\x24", stale_free_check)
    source_match = body.index(b"\x39\x6b\x08", stale_remember)
    exact_remember = body.index(b"\x89\x1c\x24", source_match)
    shift = body.index(b"\x8d\x4a\x14", exact_remember)
    five_dword_copy = bytes.fromhex(
        "8b0189028b41048942048b41088942088b410c89420c8b41108942108bd1"
    )
    copied = body.index(five_dword_copy, shift)
    reuse_tail = body.index(b"\x8b\xda", copied)
    assert (
        object_match
        < id_match
        < stale_free_check
        < stale_remember
        < source_match
        < exact_remember
        < shift
        < copied
        < reuse_tail
    )


def test_reused_row_is_cleared_before_images_are_resolved_again(image: bytearray) -> None:
    patch = ObjectImageUpgradePatch()
    patch.apply(image)
    base, section_off, _size = find_section(image, SECTION_NAME) or pytest.fail("missing section")
    code = patch._assemble(base)
    begin = section_off + code.label_va("apply_slot") - base
    end = section_off + code.label_va("unapply") - base
    body = bytes(image[begin:end])
    clear = b"\xc7\x43\x0c\x00\x00\x00\x00\xc7\x43\x10\x00\x00\x00\x00"
    select_lookup = b"\x8d\x85\x38\x01\x00\x00\x50"
    button_lookup = b"\x8d\x85\x3c\x01\x00\x00\x50"
    assert body.index(clear) < body.index(select_lookup) < body.index(button_lookup)


def test_upgrade_vtable_patches_apply_and_unapply_slots(image: bytearray) -> None:
    patch = ObjectImageUpgradePatch()
    patch.apply(image)
    base, _section_off, _size = find_section(image, SECTION_NAME) or pytest.fail("missing section")
    layout = patch._layout(base)
    code = patch._assemble(base)
    table_off = va_to_offset(image, layout["upgrade"])
    stock_off = va_to_offset(image, OBJECT_IMAGE_UPGRADE_UPGRADE_VTABLE)
    assert table_off is not None
    assert stock_off is not None
    assert image[table_off + 0x04 : table_off + 0x0C] == image[
        stock_off + 0x04 : stock_off + 0x0C
    ]
    assert struct.unpack_from("<I", image, table_off + 0x20)[0] == code.label_va("unapply")
    assert struct.unpack_from("<I", image, table_off + 0x28)[0] == code.label_va("apply")


def test_unapply_is_the_intentional_sticky_noop(image: bytearray) -> None:
    patch = ObjectImageUpgradePatch()
    patch.apply(image)
    base, section_off, _size = find_section(image, SECTION_NAME) or pytest.fail("missing section")
    code = patch._assemble(base)
    begin = section_off + code.label_va("unapply") - base
    end = section_off + code.label_va("select_hook") - base
    body = bytes(image[begin:end])
    assert body == b"\xc3"


def test_resolvers_scan_all_rows_and_keep_later_non_null_matches(image: bytearray) -> None:
    patch = ObjectImageUpgradePatch()
    patch.apply(image)
    base, section_off, _size = find_section(image, SECTION_NAME) or pytest.fail("missing section")
    code = patch._assemble(base)

    for start, end, field in (
        ("select_hook", "button_hook", b"\x8b\x59\x0c"),
        ("button_hook", None, b"\x8b\x59\x10"),
    ):
        begin = section_off + code.label_va(start) - base
        finish = section_off + (
            code.label_va(end) - base if end else code.base_va - base + len(code.finish())
        )
        body = bytes(image[begin:finish])
        found = body.index(field)
        replace = body.index(b"\x8b\xeb", found)
        advance = body.index(b"\x83\xc1\x14", replace)
        bound = body.index(b"\x3d" + struct.pack("<I", 2048), advance)
        assert found < replace < advance < bound


def test_registered_exported_and_not_experimental() -> None:

    assert Exported is ObjectImageUpgradePatch
    assert PATCHES[ObjectImageUpgradePatch.name] is ObjectImageUpgradePatch
    assert ObjectImageUpgradePatch.experimental is False


def test_hook_fallbacks_replay_displaced_instructions(image: bytearray) -> None:
    patch = ObjectImageUpgradePatch()
    patch.apply(image)
    located = find_section(image, SECTION_NAME)
    assert located is not None
    base, section_off, _size = located
    code = patch._assemble(base)
    select_begin = section_off + code.label_va("select_fallback") - base
    button_begin = section_off + code.label_va("button_fallback") - base

    # Four saved registers are restored before the original entry bytes execute.
    assert bytes(image[select_begin : select_begin + 10]) == bytes.fromhex("8bcf5f5e5d5b568bf1e8")
    assert bytes(image[button_begin : button_begin + 9]) == bytes.fromhex("5f5e5d5b837c240400")


def test_ini_surface_declares_the_new_behavior() -> None:
    surface = ObjectImageUpgradePatch().ini_surface()
    assert surface.blocks[0].name == BLOCK_NAME
    assert {field.name for field in surface.fields} == {"SelectPortrait", "ButtonImage"}
    assert {field.type for field in surface.fields} == {"Ref:mappedimages"}
    assert all(parse_type(field.type)[1] == "" for field in surface.fields)
