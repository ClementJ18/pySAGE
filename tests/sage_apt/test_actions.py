"""Byte-level tests for the ActionScript reader/writer.

The Edain corpus exercises neither `EA_PUSHREGISTER` nor `EA_PUSHWORDCONSTANT`, so
these opcode tests are hand-crafted action buffers. `pushregister`, `pushbyte`,
`pushshort` and `pushwordconstant` all carry an inline operand with no 4-byte
alignment, so a buffer is just the opcode byte, its operand, and a trailing
`ACTION_END` (0x00) to stop the reader.

The definefunction tests cover Phase 3: the compiler recomputes each body's `size`
field from the bytes it emits rather than trusting the (advisory) XML attribute.
"""

import shutil
import struct
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from sage_apt.actions import ActionBytes, apt_process_actions, xml_process_actions
from sage_apt.aptfile import apt_to_xml, xml_to_apt

FIXTURES = Path(__file__).parent / "fixtures"


def _empty_const():
    return {"aptdataoffset": 0, "itemcount": 0, "items": []}


def _read(buf):
    """Decompile a raw action buffer to a flat list of (tag, attrib) pairs."""
    parent = ET.Element("action")
    apt_process_actions(parent, 0, bytes(buf), _empty_const())
    return [(c.tag, dict(c.attrib)) for c in parent]


def _compile(children_xml):
    """Compile an <action> element (given as inner XML) to an ActionBytes buffer."""
    action = ET.fromstring(f"<action>{children_xml}</action>")
    ab = ActionBytes()
    xml_process_actions(action, ab, _empty_const())
    return ab


# Phase 2 - pushregister (0xB9)


def test_pushregister_reads_operand_byte():
    # Buffer: opcode 0xB9, register 5, ACTION_END. The register byte must survive,
    # not be overwritten by the opcode value (185) as the old C++ port did.
    tags = _read(bytes([0xB9, 5, 0x00]))
    assert tags == [("pushregister", {"val": "5"}), ("end", {})]


def test_pushregister_does_not_consume_neighbour():
    tags = _read(bytes([0xB9, 5, 0xB5, 7, 0x00]))
    assert tags == [
        ("pushregister", {"val": "5"}),
        ("pushbyte", {"val": "7"}),
        ("end", {}),
    ]


def test_pushregister_round_trip_identity():
    ab = _compile('<pushregister val="5"/><pushbyte val="7"/><end/>')
    assert list(ab.buf) == [0xB9, 5, 0xB5, 7, 0x00]
    assert _read(ab.buf) == [
        ("pushregister", {"val": "5"}),
        ("pushbyte", {"val": "7"}),
        ("end", {}),
    ]


# Phase 2 - pushwordconstant (0xA3)


def test_pushwordconstant_reads_single_u16():
    # 0xA3, uint16 0x1234, ACTION_END. Exactly one uint16 operand: no phantom
    # pushshort, and the reader must land on the ACTION_END right after.
    tags = _read(bytes([0xA3, 0x34, 0x12, 0x00]))
    assert tags == [("pushwordconstant", {"val": "4660"}), ("end", {})]


def test_pushwordconstant_frames_neighbour():
    # pushwordconstant (2-byte operand) followed by pushshort (2-byte operand).
    tags = _read(bytes([0xA3, 0x34, 0x12, 0xB6, 0x02, 0x00, 0x00]))
    assert tags == [
        ("pushwordconstant", {"val": "4660"}),
        ("pushshort", {"val": "2"}),
        ("end", {}),
    ]


def test_pushwordconstant_round_trip_identity():
    ab = _compile('<pushwordconstant val="4660"/><pushshort val="2"/><end/>')
    assert list(ab.buf) == [0xA3, 0x34, 0x12, 0xB6, 0x02, 0x00, 0x00]
    assert _read(ab.buf) == [
        ("pushwordconstant", {"val": "4660"}),
        ("pushshort", {"val": "2"}),
        ("end", {}),
    ]


# Phase 3 - recomputed definefunction body sizes


def _def_size_field(buf, size_offset):
    return struct.unpack_from("<I", bytes(buf), size_offset)[0]


def test_definefunction_size_recomputed_from_body():
    # A body of pushbyte (2 bytes) + trace (1 byte) = 3 bytes, regardless of the
    # advisory XML size, which is deliberately wrong here.
    ab = _compile(
        '<definefunction name="f" size="999">'
        '<body><pushbyte val="2"/><trace/></body>'
        "</definefunction><end/>"
    )
    pd = ab.actiondefinefunctions[0]
    assert _def_size_field(ab.buf, pd["size_offset"]) == 3


def test_nested_definefunction_sizes_enclose_inner():
    # Outer body is exactly the inner function; the inner body is pushbyte + trace.
    # The inner function's on-disk footprint is its 28-byte header plus its 3-byte
    # body, so the outer size (31) must fully enclose the inner one (3).
    ab = _compile(
        '<definefunction name="outer" size="0"><body>'
        '<definefunction name="inner" size="0"><body>'
        '<pushbyte val="2"/><trace/>'
        "</body></definefunction>"
        "</body></definefunction><end/>"
    )
    parent = ET.Element("action")
    apt_process_actions(parent, 0, bytes(ab.buf), _empty_const())

    # The reader nests the inner function inside the outer body; both sizes match.
    outer = [e for e in parent if e.tag == "definefunction"]
    assert len(outer) == 1
    outer = outer[0]
    assert outer.get("size") == "31"
    outer_body = outer.find("body")
    inner = outer_body.find("definefunction")
    assert inner is not None
    assert inner.get("size") == "3"
    assert [c.tag for c in inner.find("body")] == ["pushbyte", "trace"]


# Phase 4 - label-based branches


def test_forward_and_backward_branches_resolve_to_labels():
    # A loop: branchiftrue jumps back to the leading trace (L1), branchalways jumps
    # forward to the trailing trace (L2). The offset attributes are placeholders;
    # the compiler resolves the targets from the anchors.
    ab = _compile(
        '<trace anchor="L1"/><pushbyte val="1"/>'
        '<branchiftrue offset="0" target="L1"/>'
        '<pushbyte val="2"/>'
        '<branchalways offset="0" target="L2"/>'
        '<pushbyte val="3"/><trace anchor="L2"/><end/>'
    )
    tags = _read(ab.buf)
    # Anchors land on the two traces; the branches point at them.
    assert tags[0] == ("trace", {"anchor": "L1"})
    assert tags[2] == ("branchiftrue", {"offset": "-8", "target": "L1"})
    assert tags[4] == ("branchalways", {"offset": "2", "target": "L2"})
    assert tags[6] == ("trace", {"anchor": "L2"})
    # Backward branch is negative, forward branch positive.
    assert int(dict(tags[2][1])["offset"]) < 0
    assert int(dict(tags[4][1])["offset"]) > 0
    # Recompiling the decompiled XML reproduces the exact original bytes.
    inner = "".join(ET.tostring(c, encoding="unicode") for c in _read_elements(ab.buf))
    assert list(_compile(inner).buf) == list(ab.buf)


def _read_elements(buf):
    parent = ET.Element("action")
    apt_process_actions(parent, 0, bytes(buf), _empty_const())
    return list(parent)


def test_insert_between_branch_and_target_grows_offset_by_exact_bytes():
    # A forward branch to an anchored trace. Inserting a one-byte trace between the
    # branch and its target must keep the target label and grow the raw offset by
    # exactly one byte.
    parent = ET.Element("action")
    apt_process_actions(
        parent,
        0,
        bytes(
            _compile(
                '<branchalways offset="0" target="L1"/><pushbyte val="1"/>'
                '<trace anchor="L1"/><end/>'
            ).buf
        ),
        _empty_const(),
    )
    branch = parent[0]
    old_offset = int(branch.get("offset"))
    assert branch.get("target") == "L1"

    # Insert a single-byte trace just before the anchored target.
    target_idx = next(i for i, c in enumerate(parent) if c.get("anchor") == "L1")
    parent.insert(target_idx, ET.Element("trace"))

    inner = "".join(ET.tostring(c, encoding="unicode") for c in parent)
    rebuilt = _read(_compile(inner).buf)
    branch2 = next(t for t in rebuilt if t[0] == "branchalways")
    assert branch2[1]["target"] == "L1"
    assert int(branch2[1]["offset"]) == old_offset + 1


def test_branch_to_gotolabel_keeps_string_operand():
    # gotolabel uses `label` for its frame-label string operand, so the branch
    # destination marker must live in a separate `anchor` attribute (the corpus has
    # branches landing on gotolabels in MpGameSetup and Palantir).
    # Layout: branchalways at 0 (operand at 4, dest = 8 + offset), gotolabel at 8
    # (aligned string pointer at 12 -> 20), end at 16, "goHere" at 20.
    buf = bytearray([0x99, 0, 0, 0, 0, 0, 0, 0, 0x8C, 0, 0, 0, 20, 0, 0, 0, 0x00, 0, 0, 0])
    buf += b"goHere\x00"
    tags = _read(buf)
    assert tags[0] == ("branchalways", {"offset": "0", "target": "L1"})
    assert tags[1] == ("gotolabel", {"label": "goHere", "anchor": "L1"})

    # Recompile: the goto's string operand survives, the branch delta is recomputed,
    # and the bytes match the original once the string relocation is patched in
    # (pointer patching happens at file write time, outside xml_process_actions).
    inner = "".join(ET.tostring(c, encoding="unicode") for c in _read_elements(buf))
    ab = _compile(inner)
    assert ab.actionstrings == [{"offset": 12, "string": "goHere"}]
    out = bytearray(ab.buf)
    struct.pack_into("<I", out, 12, 20)
    while len(out) % 4:
        out.append(0)
    out += b"goHere\x00"
    assert bytes(out) == bytes(buf)


def test_offset_only_branch_compiles_verbatim():
    # A pre-Phase-4 branch with no target: the raw offset is emitted unchanged, and
    # (pointing outside the block here) it stays offset-only on decompile.
    ab = _compile('<branchalways offset="12"/><end/>')
    assert struct.unpack_from("<i", bytes(ab.buf), 4)[0] == 12
    tags = _read(ab.buf)
    assert tags[0] == ("branchalways", {"offset": "12"})
    assert "target" not in tags[0][1]


def test_unknown_branch_target_raises():
    with pytest.raises(ValueError, match="branch target label"):
        _compile('<branchalways offset="0" target="Lnope"/><end/>')


@pytest.fixture
def spellstore_dir(tmp_path):
    shutil.copy(FIXTURES / "SpellStore.apt", tmp_path / "SpellStore.apt")
    shutil.copy(FIXTURES / "SpellStore.const", tmp_path / "SpellStore.const")
    return tmp_path


def _find_function(root, name):
    for e in root.iter("definefunction"):
        if e.get("name") == name:
            return e
    return None


def test_edited_function_body_recompiles_with_new_size(spellstore_dir):
    """Injecting a <trace/> into a real function body and recompiling must keep the
    edit inside the same body, preserve everything else, and grow the recomputed
    `size` by exactly one byte (trace is a single un-aligned opcode)."""
    apt = spellstore_dir / "SpellStore.apt"
    xml_path = apt_to_xml(apt)
    tree = ET.parse(xml_path)
    root = tree.getroot()

    fn = _find_function(root, "PlaySound")
    assert fn is not None
    old_size = int(fn.get("size"))
    old_body = [c.tag for c in fn.find("body")]
    names_before = [e.get("name") for e in root.iter("definefunction")]

    ET.SubElement(fn.find("body"), "trace")
    tree.write(xml_path, encoding="utf-8")

    xml_to_apt(xml_path)
    apt_to_xml(apt)
    root2 = ET.parse(xml_path).getroot()

    fn2 = _find_function(root2, "PlaySound")
    assert fn2 is not None
    new_body = [c.tag for c in fn2.find("body")]
    assert new_body == old_body + ["trace"]
    assert int(fn2.get("size")) == old_size + 1
    # Nothing after (or around) the function was lost.
    assert [e.get("name") for e in root2.iter("definefunction")] == names_before
