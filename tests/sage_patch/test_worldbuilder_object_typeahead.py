"""Tests for the Worldbuilder object-picker type-ahead patch.

Two halves, and they fail differently. The **resource** half is checkable by reading: the patched
`IDD` 190 has to parse as a dialog template, hold the new edit control, and occupy exactly the
bytes the stock one did - a template that grew would need the resource directory repointed, which
this patch deliberately does not do, and a template that stopped parsing would take the dialog
down with it at `DoModal`.

The **behaviour** half is hand-assembled x86 that cannot be executed here, so the tests
disassemble it back and assert it says what it was meant to say. Its failure modes are all silent:
an `AFX_MSGMAP` whose base map is wrong severs the dialog from `CDialog`'s own handlers, an entry
with the wrong notification code never fires, and a handler that returns with `ret 4` unbalances
MFC's dispatcher - none of which raise at apply time.
"""

from __future__ import annotations

import struct
from typing import NamedTuple

import pytest

from sage_patch.patches.worldbuilder_object_typeahead import (
    _CODE_OFF,
    _ENTRIES_OFF,
    _GET_BASE_MAP,
    _MSGMAP_OFF,
    _SEND_DLG_ITEM_MESSAGE_A,
    _SEND_MESSAGE_A,
    _STOCK_ENTRIES,
    _STOCK_MESSAGE_MAP,
    ANCHORS,
    EDIT_ID,
    MESSAGE_MAP_SITES,
    PATCHED_TEMPLATE,
    SECTION_NAME,
    STOCK_TEMPLATE,
    TEMPLATE_VA,
    WorldbuilderObjectTypeaheadPatch,
    build_section,
)
from sage_patch.utils import find_section, va_to_offset

from .synthetic import worldbuilder_object_typeahead_image

TREE_ID = 1175


@pytest.fixture
def image() -> bytearray:
    return worldbuilder_object_typeahead_image()


def _patched(image: bytearray) -> tuple[bytearray, int]:
    WorldbuilderObjectTypeaheadPatch().apply(image)
    located = find_section(image, SECTION_NAME)
    assert located is not None
    return image, located[0]


def _read_sz(blob: bytes, offset: int) -> tuple[str | int, int]:
    """One `DLGTEMPLATEEX` variable-length field: an ordinal, or a NUL-terminated UTF-16 string."""
    if struct.unpack_from("<H", blob, offset)[0] == 0xFFFF:
        return struct.unpack_from("<H", blob, offset + 2)[0], offset + 4
    end = offset
    while struct.unpack_from("<H", blob, end)[0] != 0:
        end += 2
    return blob[offset:end].decode("utf-16-le"), end + 2


class _Control(NamedTuple):
    """One parsed `DLGITEMTEMPLATEEX`. `cls` is a class name, or an ordinal for the six built-in
    window classes - 0x80 is BUTTON, 0x81 is EDIT."""

    cls: str | int
    id: int
    rect: tuple[int, int, int, int]
    style: int


def _parse_dialog(blob: bytes) -> tuple[str, list[_Control]]:
    """The caption and controls of a `DLGTEMPLATEEX`, parsed the way the dialog manager does.

    Written out here rather than imported: the point of the resource tests is that the bytes the
    patch writes are a *template*, and a parser that shares code with the writer could not say so.
    """
    version, signature = struct.unpack_from("<HH", blob, 0)
    assert (version, signature) == (1, 0xFFFF), "not a DLGTEMPLATEEX"
    style, count = struct.unpack_from("<I", blob, 12)[0], struct.unpack_from("<H", blob, 16)[0]
    offset = 26
    _menu, offset = _read_sz(blob, offset)
    _class, offset = _read_sz(blob, offset)
    caption, offset = _read_sz(blob, offset)
    assert isinstance(caption, str)
    if style & 0x40:  # DS_SETFONT
        offset += 6
        _font, offset = _read_sz(blob, offset)

    controls: list[_Control] = []
    for _ in range(count):
        offset = (offset + 3) & ~3
        control_style = struct.unpack_from("<I", blob, offset + 8)[0]
        x, y, cx, cy = struct.unpack_from("<hhhh", blob, offset + 12)
        control_id = struct.unpack_from("<I", blob, offset + 20)[0]
        offset += 24
        class_name, offset = _read_sz(blob, offset)
        _title, offset = _read_sz(blob, offset)
        extra = struct.unpack_from("<H", blob, offset)[0]
        offset += 2 + extra
        controls.append(_Control(class_name, control_id, (x, y, cx, cy), control_style))
    assert offset == len(blob), "the template must end exactly where its last control does"
    return caption, controls


def test_applies_and_verifies_clean(image: bytearray) -> None:
    data, _ = _patched(image)
    assert WorldbuilderObjectTypeaheadPatch().verify(data) == []


def test_detect_recognises_only_a_patched_image(image: bytearray) -> None:
    assert WorldbuilderObjectTypeaheadPatch.detect(image) is None
    data, _ = _patched(image)
    detected = WorldbuilderObjectTypeaheadPatch.detect(data)
    assert detected is not None
    assert detected.name == "worldbuilder-object-typeahead"


def test_the_template_keeps_its_length(image: bytearray) -> None:
    """The resource is rewritten in place, so its `IMAGE_RESOURCE_DATA_ENTRY` needs no edit - and
    the patch does not make one. A longer template would run off the end of the resource."""
    assert len(PATCHED_TEMPLATE) == len(STOCK_TEMPLATE) == 292
    data, _ = _patched(image)
    off = va_to_offset(data, TEMPLATE_VA)
    assert off is not None
    assert bytes(data[off : off + len(PATCHED_TEMPLATE)]) == PATCHED_TEMPLATE


def test_the_patched_template_still_parses(image: bytearray) -> None:
    caption, controls = _parse_dialog(PATCHED_TEMPLATE)
    assert caption == "Object", "the caption pays for the new control and must have shrunk"
    assert len(controls) == 5


def test_the_edit_control_is_a_tabstop_ahead_of_the_tree(image: bytearray) -> None:
    """Focus lands on the first tabstop in template order, which is what lets the dialog be typed
    into the moment it opens - so the edit has to carry WS_TABSTOP *and* precede the tree."""
    _caption, controls = _parse_dialog(PATCHED_TEMPLATE)
    ids = [control.id for control in controls]
    assert ids.index(EDIT_ID) < ids.index(TREE_ID)

    edit = next(control for control in controls if control.id == EDIT_ID)
    assert edit.cls == 0x0081, "class ordinal 0x0081 is EDIT"
    assert edit.style & 0x00010000, "WS_TABSTOP"
    assert edit.style & 0x50000000 == 0x50000000, "WS_CHILD | WS_VISIBLE"
    assert edit.style & 0x0004 == 0, "ES_MULTILINE would swallow the Enter that accepts the dialog"

    tabstops = [control.id for control in controls if control.style & 0x00010000]
    assert tabstops[0] == EDIT_ID


def test_the_tree_moves_down_and_nothing_else_moves(image: bytearray) -> None:
    """The `DialogLayoutManager` anchors by control id, so every rect that does not have to change
    must not: only the tree gives up the space the edit takes."""
    _stock_caption, stock = _parse_dialog(STOCK_TEMPLATE)
    _caption, patched = _parse_dialog(PATCHED_TEMPLATE)
    stock_rects = {control.id: control.rect for control in stock}
    patched_rects = {control.id: control.rect for control in patched}

    assert stock_rects[TREE_ID] == (15, 20, 114, 126)
    assert patched_rects[TREE_ID] == (15, 35, 114, 111)
    edit_x, edit_y, edit_cx, edit_cy = patched_rects[EDIT_ID]
    tree_x, tree_y, tree_cx, _tree_cy = patched_rects[TREE_ID]
    assert (edit_x, edit_cx) == (tree_x, tree_cx), "the box lines up with the tree under it"
    assert edit_y + edit_cy <= tree_y, "the box must not overlap the tree"
    for control_id, rect in stock_rects.items():
        if control_id != TREE_ID:
            assert patched_rects[control_id] == rect


def test_both_get_message_map_bodies_point_at_the_cave(image: bytearray) -> None:
    """There are two - the static `GetThisMessageMap` and the virtual `GetMessageMap` - and MFC
    reaches the map through either, so leaving one behind would dispatch half the messages through
    the stock map and drop every `EN_CHANGE`."""
    data, section_va = _patched(image)
    wanted = b"\xb8" + struct.pack("<I", section_va + _MSGMAP_OFF)
    for va in MESSAGE_MAP_SITES:
        off = va_to_offset(data, va)
        assert off is not None
        assert bytes(data[off : off + 5]) == wanted


def test_the_cave_map_keeps_the_base_chain_and_the_stock_entries(image: bytearray) -> None:
    _data, section_va = _patched(image)
    content = build_section(section_va)
    base_map, entries = struct.unpack_from("<II", content, _MSGMAP_OFF)
    assert base_map == _GET_BASE_MAP, "severing the base chain loses CDialog's own handlers"
    assert entries == section_va + _ENTRIES_OFF
    assert content[_ENTRIES_OFF : _ENTRIES_OFF + len(_STOCK_ENTRIES)] == _STOCK_ENTRIES


def test_the_new_entry_is_an_en_change_for_the_edit_control(image: bytearray) -> None:
    _data, section_va = _patched(image)
    content = build_section(section_va)
    offset = _ENTRIES_OFF + len(_STOCK_ENTRIES)
    message, code, first, last, signature, handler = struct.unpack_from("<IIIIII", content, offset)
    assert message == 0x0111, "WM_COMMAND"
    assert code == 0x0300, "EN_CHANGE"
    assert (first, last) == (EDIT_ID, EDIT_ID)
    assert signature == 0x35, "AfxSig_vv - a void member taking nothing"
    assert handler == section_va + _CODE_OFF
    assert struct.unpack_from("<IIIIII", content, offset + 24) == (0,) * 6, "terminator"


def test_the_handler_obeys_the_member_calling_convention(image: bytearray) -> None:
    """MFC calls this as `void (CWnd::*)()`: `this` in ECX, nothing on the stack, and the
    dispatcher keeps going afterwards - so it has to preserve every register and clean nothing."""
    _data, section_va = _patched(image)
    content = build_section(section_va)
    code = content[_CODE_OFF:]
    assert code[0] == 0x60, "pushad"
    assert b"\x61\xc3" in code, "popad then a bare ret, never ret <n>"


def test_the_cave_calls_only_the_two_imports_it_names(image: bytearray) -> None:
    """No `GetProcAddress` dance and no new import: everything the handler needs is already in
    Worldbuilder's table, and a cave reaching anywhere else would be reaching into engine code it
    has no business calling from a dialog notification."""
    capstone = pytest.importorskip("capstone")
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    _data, section_va = _patched(image)
    content = build_section(section_va)
    code_va = section_va + _CODE_OFF

    indirect: set[int] = set()
    direct: set[int] = set()
    for insn in md.disasm(bytes(content[_CODE_OFF:]), code_va):
        if insn.mnemonic != "call":
            continue
        if insn.op_str.startswith("dword"):
            indirect.add(int(insn.op_str.split("[")[1].rstrip("]"), 16))
        else:
            direct.add(int(insn.op_str, 16))

    assert indirect == {_SEND_MESSAGE_A, _SEND_DLG_ITEM_MESSAGE_A}
    assert all(code_va <= target < section_va + len(content) for target in direct), (
        "the cave's direct calls are its own helpers and must stay inside it"
    )


def test_the_handler_reads_the_edit_and_steers_the_tree(image: bytearray) -> None:
    """The pushed message ids are the whole contract with the dialog: read the box, walk the tree,
    move the caret. Nothing here writes to the `Parameter` - `OnOK` still does that, unpatched."""
    capstone = pytest.importorskip("capstone")
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    _data, section_va = _patched(image)
    content = build_section(section_va)

    pushed = {
        int(insn.op_str, 16)
        for insn in md.disasm(bytes(content[_CODE_OFF:]), section_va + _CODE_OFF)
        if insn.mnemonic == "push" and insn.op_str.startswith("0x")
    }
    assert 0x0D in pushed, "WM_GETTEXT"
    assert 0x110A in pushed, "TVM_GETNEXTITEM"
    assert 0x110B in pushed, "TVM_SELECTITEM"
    assert 0x110C in pushed, "TVM_GETITEM"
    assert EDIT_ID in pushed


def test_the_handler_walks_the_whole_tree_not_just_what_is_visible(image: bytearray) -> None:
    """`TVGN_NEXTVISIBLE` would only ever reach expanded folders, and the dialog opens with every
    folder collapsed - which is the problem this patch exists to solve."""
    capstone = pytest.importorskip("capstone")
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    _data, section_va = _patched(image)
    content = build_section(section_va)

    insns = list(md.disasm(bytes(content[_CODE_OFF:]), section_va + _CODE_OFF))
    flags = {
        int(insns[index - 1].op_str, 16)
        for index, insn in enumerate(insns)
        if insn.mnemonic == "push" and insn.op_str == "0x110a" and index
    }
    assert flags == {0, 1, 3, 4}, "TVGN_ROOT, _NEXT, _PARENT, _CHILD - a full pre-order walk"


@pytest.mark.parametrize("anchor_va", sorted(ANCHORS))
def test_refuses_a_build_whose_anchors_moved(image: bytearray, anchor_va: int) -> None:
    off = va_to_offset(image, anchor_va)
    assert off is not None
    image[off] ^= 0xFF
    with pytest.raises(ValueError, match="not the one the handler was written against"):
        WorldbuilderObjectTypeaheadPatch().apply(image)


def test_refuses_a_build_whose_dialog_template_moved(image: bytearray) -> None:
    off = va_to_offset(image, TEMPLATE_VA)
    assert off is not None
    image[off + 16] ^= 0xFF  # cDlgItems: a dialog with a different control count
    with pytest.raises(ValueError):
        WorldbuilderObjectTypeaheadPatch().apply(image)


def test_refuses_a_build_whose_message_map_moved(image: bytearray) -> None:
    off = va_to_offset(image, MESSAGE_MAP_SITES[1])
    assert off is not None
    image[off + 1] ^= 0xFF
    with pytest.raises(ValueError):
        WorldbuilderObjectTypeaheadPatch().apply(image)


def test_refuses_an_aslr_image(image: bytearray) -> None:
    e_lfanew = struct.unpack_from("<I", image, 0x3C)[0]
    dll_characteristics_off = e_lfanew + 24 + 70
    (stock,) = struct.unpack_from("<H", image, dll_characteristics_off)
    struct.pack_into("<H", image, dll_characteristics_off, stock | 0x0040)
    with pytest.raises(ValueError, match="DYNAMIC_BASE"):
        WorldbuilderObjectTypeaheadPatch().apply(image)


def test_verify_reports_a_tampered_cave(image: bytearray) -> None:
    data, _section_va = _patched(image)
    located = find_section(data, SECTION_NAME)
    assert located is not None
    _va, section_off, _vsize = located
    data[section_off + _CODE_OFF] ^= 0xFF
    problems = WorldbuilderObjectTypeaheadPatch().verify(data)
    assert problems and "cave" in problems[0]


def test_verify_reports_a_stock_template(image: bytearray) -> None:
    """A binary whose cave and map survived a resource editor's round-trip still has no edit box,
    and the patch has to say so rather than report itself applied."""
    data, _section_va = _patched(image)
    off = va_to_offset(data, TEMPLATE_VA)
    assert off is not None
    data[off : off + len(STOCK_TEMPLATE)] = STOCK_TEMPLATE
    problems = WorldbuilderObjectTypeaheadPatch().verify(data)
    assert problems and "edit control is missing" in problems[0]


def test_verify_reports_a_missing_section(image: bytearray) -> None:
    assert WorldbuilderObjectTypeaheadPatch().verify(image) == [
        f"no {SECTION_NAME} section: the file does not carry this patch"
    ]


def test_the_stock_template_is_the_dialog_the_patch_thinks_it_is(image: bytearray) -> None:
    """The constants are pinned to `IDD` 190 in one build, and `_STOCK_MESSAGE_MAP` is what both
    `GetMessageMap` bodies return there. If either drifts, everything above is testing itself."""
    caption, controls = _parse_dialog(STOCK_TEMPLATE)
    assert caption == "Edit object parameter."
    assert [control.cls for control in controls] == [0x80, "SysTreeView32", 0x80, 0x80]
    assert [control.id for control in controls] == [1133, TREE_ID, 1, 2]
    assert _STOCK_MESSAGE_MAP == 0x01DF2050
