"""Converter between the APT binary pair (`.apt` + `.const`) and an editable XML form.
Port of the C++ AptConverter by Stephan Vedder; the size constants mirror the game's
32-bit packed structs, so pointers inside the files are plain buffer offsets."""

import struct
from pathlib import Path
from xml.dom import minidom
from xml.etree import ElementTree as ET

from sage_apt.actions import ActionBytes, apt_process_actions, xml_process_actions
from sage_apt.flags import (
    get_but_action_flags_int,
    get_but_action_flags_str,
    get_but_flags_int,
    get_but_flags_str,
    get_po_flags_int,
    get_po_flags_str,
)


class AptError(Exception):
    """Raised when converting an APT pair fails. Carries the offending path and a
    human-readable reason so callers (CLI, editor API) can report the cause."""

    def __init__(self, path, reason):
        self.path = Path(path)
        self.reason = reason
        super().__init__(f"{self.path.name}: {reason}")


# Character types
SHAPE = 1
EDITTEXT = 2
FONT = 3
BUTTON = 4
SPRITE = 5
IMAGE = 7
MORPH = 8
MOVIE = 9
TEXT = 10

# Frame item types
ACTION_ITEM = 1
FRAMELABEL = 2
PLACEOBJECT = 3
REMOVEOBJECT = 4
BACKGROUNDCOLOR = 5
INITACTION = 8

# Const item types
TYPE_UNDEF = 0
TYPE_STRING = 1
TYPE_NUMBER = 4

CHAR_SIG = 0x09876543

# Struct sizes (32-bit packed layout)
SZ_IMPORT = 16
SZ_EXPORT = 8
SZ_SHAPE = 28
SZ_EDITTEXT = 60
SZ_OUTPUTFONT = 20
SZ_OUTPUTSPRITE = 20
SZ_IMAGE = 12
SZ_MORPH = 16
SZ_OUTPUTMOVIE = 60
SZ_OUTPUTTEXT = 56
SZ_OUTPUTTEXTRECORD = 56
SZ_GLYPH = 8
SZ_VECTOR2 = 8
SZ_TRIANGLE = 6
SZ_BUTTONRECORD = 68
SZ_OUTPUTBUTTONACTION = 8
SZ_OUTPUTBUTTON = 64
SZ_OUTPUTACTION = 8
SZ_FRAMELABEL = 16
SZ_PLACEOBJECT = 64
SZ_REMOVEOBJECT = 8
SZ_BACKGROUNDCOLOR = 8
SZ_OUTPUTINITACTION = 12
SZ_OUTPUTFRAME = 8
SZ_PLACEOBJECTACTION = 12
SZ_OUTPUTPLACEOBJECTACTIONS = 8


# Low-level binary helpers


def _ru(buf, off):  # read uint32
    return struct.unpack_from("<I", buf, off)[0], off + 4


def _ri(buf, off):  # read int32
    return struct.unpack_from("<i", buf, off)[0], off + 4


def _rf(buf, off):  # read float32
    return struct.unpack_from("<f", buf, off)[0], off + 4


def _rcs(buf, off):  # read c-string at absolute offset
    end = off
    while end < len(buf) and buf[end] != 0:
        end += 1
    return buf[off:end].decode("latin-1", errors="replace")


def _getalign(x):
    return (4 * ((x + 3) // 4)) - x


def _strlength(s):
    if not s:
        return 4
    b = s.encode("latin-1") if isinstance(s, str) else s
    return 4 * (((len(b) + 1) + 3) // 4)


def _fmt_float(v):
    """Format float for XML attribute, stripping unnecessary trailing zeros."""
    s = f"{v:.8g}"
    return s


# APT → XML


def apt_to_xml(filename):
    """Decompile the `.apt`/`.const` pair at `filename` to XML. Returns the written
    `.xml` path; raises `AptError` if either input file is missing."""
    apt_path = Path(filename)
    const_path = apt_path.with_suffix(".const")
    xml_path = apt_path.with_suffix(".xml")

    if not apt_path.exists():
        raise AptError(apt_path, "file is missing")
    if not const_path.exists():
        raise AptError(const_path, "companion .const file is missing")

    constbuf = const_path.read_bytes()
    aptbuf = apt_path.read_bytes()

    # Parse .const
    off = 0x14  # skip header
    aptdataoffset, off = _ru(constbuf, off)
    itemcount, off = _ru(constbuf, off)
    off += 4  # skip items-block pointer

    const_data = {"aptdataoffset": aptdataoffset, "itemcount": itemcount, "items": []}
    item_base = off
    for i in range(itemcount):
        (itype,) = struct.unpack_from("<I", constbuf, item_base + i * 8)
        (ival,) = struct.unpack_from("<I", constbuf, item_base + i * 8 + 4)
        if itype == TYPE_STRING:
            const_data["items"].append({"type": TYPE_STRING, "value": _rcs(constbuf, ival)})
        else:
            const_data["items"].append({"type": itype, "value": ival})

    # Parse .apt
    root = ET.Element("aptdata")
    _parse_movie(aptbuf, aptdataoffset, root, const_data)

    # Write XML
    _write_xml(root, xml_path)
    return xml_path


def _write_xml(root, path):
    raw = ET.tostring(root, encoding="unicode")
    pretty = minidom.parseString(raw).toprettyxml(indent="  ", encoding="utf-8")
    # minidom adds an XML declaration; write as bytes
    path.write_bytes(pretty)


def _parse_movie(aptbuf, movie_off, root_elem, const_data):
    """Read OutputMovie at movie_off and build the full XML tree."""
    o = movie_off
    _type, o = _ru(aptbuf, o)
    _sig, o = _ru(aptbuf, o)
    framecount, o = _ru(aptbuf, o)
    frames_ptr, o = _ru(aptbuf, o)
    _pointer, o = _ru(aptbuf, o)
    charactercount, o = _ru(aptbuf, o)
    characters_ptr, o = _ru(aptbuf, o)
    _scrx, o = _ru(aptbuf, o)
    _scry, o = _ru(aptbuf, o)
    _unk, o = _ru(aptbuf, o)
    importcount, o = _ru(aptbuf, o)
    imports_ptr, o = _ru(aptbuf, o)
    exportcount, o = _ru(aptbuf, o)
    exports_ptr, o = _ru(aptbuf, o)

    movie_elem = ET.SubElement(root_elem, "movieclip")

    # imports
    imports_elem = ET.SubElement(movie_elem, "imports")
    for i in range(importcount):
        base = imports_ptr + i * SZ_IMPORT
        (movie_ptr,) = struct.unpack_from("<I", aptbuf, base)
        (name_ptr,) = struct.unpack_from("<I", aptbuf, base + 4)
        (character,) = struct.unpack_from("<I", aptbuf, base + 8)
        imp = ET.SubElement(imports_elem, "import")
        imp.set("name", _rcs(aptbuf, name_ptr))
        imp.set("movie", _rcs(aptbuf, movie_ptr))
        imp.set("character", str(character))

    # exports
    exports_elem = ET.SubElement(movie_elem, "exports")
    for i in range(exportcount):
        base = exports_ptr + i * SZ_EXPORT
        (name_ptr,) = struct.unpack_from("<I", aptbuf, base)
        (character,) = struct.unpack_from("<I", aptbuf, base + 4)
        exp = ET.SubElement(exports_elem, "export")
        exp.set("name", _rcs(aptbuf, name_ptr))
        exp.set("character", str(character))

    # frames
    frames_elem = ET.SubElement(movie_elem, "frames")
    _parse_frames(aptbuf, frames_ptr, framecount, frames_elem, const_data)

    # characters (index 0 is the movie itself – skip it)
    for ch in range(charactercount):
        (char_ptr,) = struct.unpack_from("<I", aptbuf, characters_ptr + ch * 4)
        if char_ptr == 0:
            e = ET.SubElement(root_elem, "empty")
            e.set("id", str(ch))
        else:
            _parse_character(aptbuf, char_ptr, ch, root_elem, const_data)


def _parse_frames(aptbuf, frames_ptr, framecount, parent_elem, const_data):
    for i in range(framecount):
        frame_off = frames_ptr + i * SZ_OUTPUTFRAME
        (item_count,) = struct.unpack_from("<I", aptbuf, frame_off)
        (items_ptr,) = struct.unpack_from("<I", aptbuf, frame_off + 4)
        frame_elem = ET.SubElement(parent_elem, "frame")
        frame_elem.set("id", str(i))
        for j in range(item_count):
            (fi_ptr,) = struct.unpack_from("<I", aptbuf, items_ptr + j * 4)
            (fi_type,) = struct.unpack_from("<I", aptbuf, fi_ptr)
            _parse_frame_item(aptbuf, fi_ptr, fi_type, frame_elem, const_data)


def _parse_frame_item(aptbuf, fi_ptr, fi_type, parent_elem, const_data):
    if fi_type == ACTION_ITEM:
        (ab_ptr,) = struct.unpack_from("<I", aptbuf, fi_ptr + 4)
        n = ET.SubElement(parent_elem, "action")
        apt_process_actions(n, ab_ptr, aptbuf, const_data)

    elif fi_type == FRAMELABEL:
        (label_ptr,) = struct.unpack_from("<I", aptbuf, fi_ptr + 4)
        (frame,) = struct.unpack_from("<I", aptbuf, fi_ptr + 12)
        n = ET.SubElement(parent_elem, "framelabel")
        n.set("label", _rcs(aptbuf, label_ptr))
        n.set("frame", str(frame))

    elif fi_type == PLACEOBJECT:
        _parse_placeobject(aptbuf, fi_ptr, parent_elem, const_data)

    elif fi_type == REMOVEOBJECT:
        (depth,) = struct.unpack_from("<i", aptbuf, fi_ptr + 4)
        n = ET.SubElement(parent_elem, "removeobject")
        n.set("depth", str(depth))

    elif fi_type == BACKGROUNDCOLOR:
        (color,) = struct.unpack_from("<I", aptbuf, fi_ptr + 4)
        n = ET.SubElement(parent_elem, "background")
        n.set("color", str(color))

    elif fi_type == INITACTION:
        (sprite,) = struct.unpack_from("<I", aptbuf, fi_ptr + 4)
        (ab_ptr,) = struct.unpack_from("<I", aptbuf, fi_ptr + 8)
        n = ET.SubElement(parent_elem, "initaction")
        n.set("sprite", str(sprite))
        apt_process_actions(n, ab_ptr, aptbuf, const_data)


def _parse_placeobject(aptbuf, fi_ptr, parent_elem, const_data):
    o = fi_ptr
    _type, o = _ru(aptbuf, o)
    flags, o = _ru(aptbuf, o)
    depth, o = _ri(aptbuf, o)
    character, o = _ri(aptbuf, o)
    m00, o = _rf(aptbuf, o)
    m01, o = _rf(aptbuf, o)
    m10, o = _rf(aptbuf, o)
    m11, o = _rf(aptbuf, o)
    tx, o = _rf(aptbuf, o)
    ty, o = _rf(aptbuf, o)
    colortransform, o = _ru(aptbuf, o)
    unknown, o = _ru(aptbuf, o)
    ratio, o = _rf(aptbuf, o)
    name_ptr, o = _ru(aptbuf, o)
    clipdepth, o = _ri(aptbuf, o)
    poa_ptr, o = _ru(aptbuf, o)

    red = colortransform & 0xFF
    green = (colortransform >> 8) & 0xFF
    blue = (colortransform >> 16) & 0xFF
    alpha = (colortransform >> 24) & 0xFF

    n = ET.SubElement(parent_elem, "placeobject")
    n.set("depth", str(depth))
    n.set("character", str(character))
    n.set("rotm00", _fmt_float(m00))
    n.set("rotm01", _fmt_float(m01))
    n.set("rotm10", _fmt_float(m10))
    n.set("rotm11", _fmt_float(m11))
    n.set("tx", _fmt_float(tx))
    n.set("ty", _fmt_float(ty))
    n.set("red", str(red))
    n.set("green", str(green))
    n.set("blue", str(blue))
    n.set("alpha", str(alpha))
    n.set("ratio", _fmt_float(ratio))
    n.set("clipdepth", str(clipdepth))
    n.set("unknown", str(unknown))

    flagstr = get_po_flags_str(flags)
    if flagstr:
        pf = ET.SubElement(n, "poflags")
        pf.set("value", flagstr)

    if name_ptr:
        pname = ET.SubElement(n, "poname")
        pname.set("name", _rcs(aptbuf, name_ptr))

    if poa_ptr:
        (clip_count,) = struct.unpack_from("<I", aptbuf, poa_ptr)
        (actions_ptr,) = struct.unpack_from("<I", aptbuf, poa_ptr + 4)
        ca_elem = ET.SubElement(n, "clipactions")
        for k in range(clip_count):
            base = actions_ptr + k * SZ_PLACEOBJECTACTION
            (f1,) = struct.unpack_from("<I", aptbuf, base)
            (f2,) = struct.unpack_from("<I", aptbuf, base + 4)
            (ad_ptr,) = struct.unpack_from("<I", aptbuf, base + 8)
            ca = ET.SubElement(ca_elem, "clipaction")
            ca.set("flags", str(f1))
            ca.set("flags2", str(f2))
            apt_process_actions(ca, ad_ptr, aptbuf, const_data)


def _parse_character(aptbuf, char_ptr, ch_id, parent_elem, const_data):
    (char_type,) = struct.unpack_from("<I", aptbuf, char_ptr)

    if char_type == SHAPE:
        o = char_ptr + 8  # skip type+sig
        left, o = _rf(aptbuf, o)
        top, o = _rf(aptbuf, o)
        right, o = _rf(aptbuf, o)
        bottom, o = _rf(aptbuf, o)
        geometry, o = _ru(aptbuf, o)
        n = ET.SubElement(parent_elem, "shape")
        n.set("id", str(ch_id))
        n.set("top", _fmt_float(top))
        n.set("left", _fmt_float(left))
        n.set("bottom", _fmt_float(bottom))
        n.set("right", _fmt_float(right))
        n.set("geometry", str(geometry))

    elif char_type == EDITTEXT:
        o = char_ptr + 8
        left, o = _rf(aptbuf, o)
        top, o = _rf(aptbuf, o)
        right, o = _rf(aptbuf, o)
        bottom, o = _rf(aptbuf, o)
        font, o = _ru(aptbuf, o)
        alignment, o = _ru(aptbuf, o)
        color, o = _ru(aptbuf, o)
        height, o = _rf(aptbuf, o)
        readonly, o = _ru(aptbuf, o)
        multiline, o = _ru(aptbuf, o)
        wordwrap, o = _ru(aptbuf, o)
        text_ptr, o = _ru(aptbuf, o)
        var_ptr, o = _ru(aptbuf, o)
        # Color byte order for EditText differs from PlaceObject:
        alpha = color & 0xFF
        blue = (color >> 8) & 0xFF
        green = (color >> 16) & 0xFF
        red = (color >> 24) & 0xFF
        n = ET.SubElement(parent_elem, "edittext")
        n.set("id", str(ch_id))
        n.set("top", _fmt_float(top))
        n.set("left", _fmt_float(left))
        n.set("bottom", _fmt_float(bottom))
        n.set("right", _fmt_float(right))
        n.set("font", str(font))
        n.set("alignment", str(alignment))
        n.set("red", str(red))
        n.set("green", str(green))
        n.set("blue", str(blue))
        n.set("alpha", str(alpha))
        n.set("height", _fmt_float(height))
        n.set("readonly", str(readonly))
        n.set("multiline", str(multiline))
        n.set("wordwrap", str(wordwrap))
        if text_ptr:
            et_txt = ET.SubElement(n, "ettext")
            et_txt.set("text", _rcs(aptbuf, text_ptr))
        if var_ptr:
            et_var = ET.SubElement(n, "etvar")
            et_var.set("variable", _rcs(aptbuf, var_ptr))

    elif char_type == FONT:
        o = char_ptr + 8
        name_ptr, o = _ru(aptbuf, o)
        glyphcount, o = _ru(aptbuf, o)
        glyphs_ptr, o = _ru(aptbuf, o)
        n = ET.SubElement(parent_elem, "font")
        n.set("id", str(ch_id))
        n.set("name", _rcs(aptbuf, name_ptr))
        if glyphcount and glyphs_ptr:
            g_elem = ET.SubElement(n, "glyphs")
            for gi in range(glyphcount):
                (gval,) = struct.unpack_from("<I", aptbuf, glyphs_ptr + gi * 4)
                g = ET.SubElement(g_elem, "glyph")
                g.set("id", str(gval))

    elif char_type == BUTTON:
        _parse_button(aptbuf, char_ptr, ch_id, parent_elem, const_data)

    elif char_type == SPRITE:
        o = char_ptr + 8
        framecount, o = _ru(aptbuf, o)
        frames_ptr, o = _ru(aptbuf, o)
        n = ET.SubElement(parent_elem, "sprite")
        n.set("id", str(ch_id))
        if framecount and frames_ptr:
            f_elem = ET.SubElement(n, "frames")
            _parse_frames(aptbuf, frames_ptr, framecount, f_elem, const_data)

    elif char_type == IMAGE:
        (texture,) = struct.unpack_from("<I", aptbuf, char_ptr + 8)
        n = ET.SubElement(parent_elem, "image")
        n.set("id", str(ch_id))
        n.set("image", str(texture))

    elif char_type == MORPH:
        o = char_ptr + 8
        startshape, o = _ru(aptbuf, o)
        endshape, o = _ru(aptbuf, o)
        n = ET.SubElement(parent_elem, "morph")
        n.set("id", str(ch_id))
        n.set("start", str(startshape))
        n.set("end", str(endshape))

    elif char_type == TEXT:
        _parse_text(aptbuf, char_ptr, ch_id, parent_elem)

    elif char_type == MOVIE:
        # Nested movie – treated as empty for now (same as C++ which doesn't recurse)
        n = ET.SubElement(parent_elem, "empty")
        n.set("id", str(ch_id))


def _parse_button(aptbuf, char_ptr, ch_id, parent_elem, const_data):
    o = char_ptr + 8  # skip type+sig
    unknown, o = _ru(aptbuf, o)
    left, o = _rf(aptbuf, o)
    top, o = _rf(aptbuf, o)
    right, o = _rf(aptbuf, o)
    bottom, o = _rf(aptbuf, o)
    tricount, o = _ru(aptbuf, o)
    vertcount, o = _ru(aptbuf, o)
    vert_ptr, o = _ru(aptbuf, o)
    tri_ptr, o = _ru(aptbuf, o)
    reccount, o = _ru(aptbuf, o)
    rec_ptr, o = _ru(aptbuf, o)
    bacount, o = _ru(aptbuf, o)
    ba_ptr, o = _ru(aptbuf, o)

    n = ET.SubElement(parent_elem, "button")
    n.set("id", str(ch_id))
    n.set("top", _fmt_float(top))
    n.set("left", _fmt_float(left))
    n.set("bottom", _fmt_float(bottom))
    n.set("right", _fmt_float(right))

    if tricount and vert_ptr:
        verts_elem = ET.SubElement(n, "vertexes")
        for i in range(vertcount):
            base = vert_ptr + i * SZ_VECTOR2
            (x,) = struct.unpack_from("<f", aptbuf, base)
            (y,) = struct.unpack_from("<f", aptbuf, base + 4)
            v = ET.SubElement(verts_elem, "vertex")
            v.set("x", _fmt_float(x))
            v.set("y", _fmt_float(y))
        tris_elem = ET.SubElement(n, "triangles")
        for i in range(tricount):
            base = tri_ptr + i * SZ_TRIANGLE
            v1, v2, v3 = struct.unpack_from("<HHH", aptbuf, base)
            t = ET.SubElement(tris_elem, "triangle")
            t.set("v1", str(v1))
            t.set("v2", str(v2))
            t.set("v3", str(v3))

    if reccount and rec_ptr:
        recs_elem = ET.SubElement(n, "buttonrecords")
        for i in range(reccount):
            base = rec_ptr + i * SZ_BUTTONRECORD
            (brflags,) = struct.unpack_from("<I", aptbuf, base)
            (character,) = struct.unpack_from("<I", aptbuf, base + 4)
            (depth,) = struct.unpack_from("<i", aptbuf, base + 8)
            m00, m01, m10, m11 = struct.unpack_from("<ffff", aptbuf, base + 12)
            tx, ty = struct.unpack_from("<ff", aptbuf, base + 28)
            br = ET.SubElement(recs_elem, "buttonrecord")
            br.set("character", str(character))
            br.set("depth", str(depth))
            br.set("rotm00", _fmt_float(m00))
            br.set("rotm01", _fmt_float(m01))
            br.set("rotm10", _fmt_float(m10))
            br.set("rotm11", _fmt_float(m11))
            br.set("tx", _fmt_float(tx))
            br.set("ty", _fmt_float(ty))
            bf_elem = ET.SubElement(br, "buttonflags")
            bf_elem.set("value", get_but_flags_str(brflags))

    if bacount and ba_ptr:
        bas_elem = ET.SubElement(n, "buttonactions")
        for i in range(bacount):
            base = ba_ptr + i * SZ_OUTPUTBUTTONACTION
            (baflags,) = struct.unpack_from("<I", aptbuf, base)
            (ad_ptr,) = struct.unpack_from("<I", aptbuf, base + 4)
            ba = ET.SubElement(bas_elem, "buttonaction")
            ba.set("flags", get_but_action_flags_str(baflags))
            apt_process_actions(ba, ad_ptr, aptbuf, const_data)


def _parse_text(aptbuf, char_ptr, ch_id, parent_elem):
    o = char_ptr + 8
    left, o = _rf(aptbuf, o)
    top, o = _rf(aptbuf, o)
    right, o = _rf(aptbuf, o)
    bottom, o = _rf(aptbuf, o)
    m00, o = _rf(aptbuf, o)
    m01, o = _rf(aptbuf, o)
    m10, o = _rf(aptbuf, o)
    m11, o = _rf(aptbuf, o)
    tx, o = _rf(aptbuf, o)
    ty, o = _rf(aptbuf, o)
    reccount, o = _ru(aptbuf, o)
    recs_ptr, o = _ru(aptbuf, o)

    n = ET.SubElement(parent_elem, "text")
    n.set("id", str(ch_id))
    n.set("top", _fmt_float(top))
    n.set("left", _fmt_float(left))
    n.set("bottom", _fmt_float(bottom))
    n.set("right", _fmt_float(right))
    n.set("rotm00", _fmt_float(m00))
    n.set("rotm01", _fmt_float(m01))
    n.set("rotm10", _fmt_float(m10))
    n.set("rotm11", _fmt_float(m11))
    n.set("tx", _fmt_float(tx))
    n.set("ty", _fmt_float(ty))

    if reccount and recs_ptr:
        recs_elem = ET.SubElement(n, "records")
        for i in range(reccount):
            base = recs_ptr + i * SZ_OUTPUTTEXTRECORD
            (font,) = struct.unpack_from("<I", aptbuf, base)
            cr, cg, cb, ca = struct.unpack_from("<ffff", aptbuf, base + 4)
            u1, u2, u3, u4 = struct.unpack_from("<ffff", aptbuf, base + 20)
            otx, oty = struct.unpack_from("<ff", aptbuf, base + 36)
            (texth,) = struct.unpack_from("<f", aptbuf, base + 44)
            (gcount,) = struct.unpack_from("<I", aptbuf, base + 48)
            (gptr,) = struct.unpack_from("<I", aptbuf, base + 52)
            rec = ET.SubElement(recs_elem, "record")
            rec.set("font", str(font))
            rec.set("red", _fmt_float(cr))
            rec.set("green", _fmt_float(cg))
            rec.set("blue", _fmt_float(cb))
            rec.set("alpha", _fmt_float(ca))
            rec.set("u1", _fmt_float(u1))
            rec.set("u2", _fmt_float(u2))
            rec.set("u3", _fmt_float(u3))
            rec.set("u4", _fmt_float(u4))
            rec.set("tx", _fmt_float(otx))
            rec.set("ty", _fmt_float(oty))
            rec.set("height", _fmt_float(texth))
            if gcount and gptr:
                g_elem = ET.SubElement(rec, "glyphs")
                for gi in range(gcount):
                    gbase = gptr + gi * SZ_GLYPH
                    (gidx,) = struct.unpack_from("<I", aptbuf, gbase)
                    (gadv,) = struct.unpack_from("<i", aptbuf, gbase + 4)
                    g = ET.SubElement(g_elem, "glyph")
                    g.set("index", str(gidx))
                    g.set("advance", str(gadv))


# XML → APT


def xml_to_apt(filename):
    """Compile the XML at `filename` back into its `.apt`/`.const` pair. Returns the
    written `(apt_path, const_path)` tuple; raises `AptError` on a missing/misnamed
    input or malformed XML. Both output buffers are built in memory before either
    file is written, so a failure never leaves a partial `.apt` beside a stale
    `.const`."""
    xml_path = Path(filename)
    const_path = xml_path.with_suffix(".const")
    apt_path = xml_path.with_suffix(".apt")

    if xml_path.suffix != ".xml":
        raise AptError(xml_path, "not an .xml file")
    if not xml_path.exists():
        raise AptError(xml_path, "file is missing")

    try:
        tree = ET.parse(str(xml_path))
    except ET.ParseError as exc:
        raise AptError(xml_path, f"malformed XML: {exc}") from exc

    root = tree.getroot()
    data = {"aptdataoffset": 0, "itemcount": 0, "items": []}
    m = _build_movie(root, data)

    apt_bytes, apt_offset = _generate_apt_file(m)
    data["aptdataoffset"] = apt_offset
    const_bytes = _generate_const_file(data)

    # Write only after both buffers exist, so a build failure leaves no output.
    apt_path.write_bytes(apt_bytes)
    const_path.write_bytes(const_bytes)
    return apt_path, const_path


# Build in-memory Movie from XML


def _new_ab():
    ab = ActionBytes()
    return ab


def _build_movie(root, data):
    m = {
        "type": MOVIE,
        "signature": CHAR_SIG,
        "pointer": 0,
        "screensizex": 1024,
        "screensizey": 768,
        "unknown": 33,
        "count": 0,
        "framecount": 0,
        "frames": [],
        "charactercount": 1,
        "characters": [],  # index 0 = self (filled at write)
        "importcount": 0,
        "imports": [],
        "exportcount": 0,
        "exports": [],
    }
    m["characters"].append(m)  # characters[0] = self

    for child in root:
        tag = child.tag
        if tag == "movieclip":
            _parse_movieclip_elem(child, m, data)
        elif tag == "shape":
            m["charactercount"] += 1
            m["characters"].append(_build_shape(child))
        elif tag == "edittext":
            m["charactercount"] += 1
            m["characters"].append(_build_edittext(child))
        elif tag == "font":
            m["charactercount"] += 1
            m["characters"].append(_build_font(child))
        elif tag == "button":
            m["charactercount"] += 1
            m["characters"].append(_build_button(child, data))
        elif tag == "sprite":
            m["charactercount"] += 1
            m["characters"].append(_build_sprite(child, data))
        elif tag == "image":
            m["charactercount"] += 1
            m["characters"].append(
                {"type": IMAGE, "signature": CHAR_SIG, "texture": int(child.get("image", 0))}
            )
        elif tag == "morph":
            m["charactercount"] += 1
            m["characters"].append(
                {
                    "type": MORPH,
                    "signature": CHAR_SIG,
                    "startshape": int(child.get("start", 0)),
                    "endshape": int(child.get("end", 0)),
                }
            )
        elif tag == "text":
            m["charactercount"] += 1
            m["characters"].append(_build_text(child))
        elif tag == "empty":
            # Character 0 is the movie's own slot (characters[0] = self); the
            # <empty id="0"/> the decompiler emits for it must not add a slot.
            if int(child.get("id", -1)) != 0:
                m["charactercount"] += 1
                m["characters"].append(None)
    return m


def _parse_movieclip_elem(mc_elem, m, data):
    children = list(mc_elem)
    if len(children) < 1:
        return
    # imports
    imports_elem = children[0]
    for imp in imports_elem:
        m["importcount"] += 1
        m["imports"].append(
            {
                "movie": imp.get("movie", ""),
                "name": imp.get("name", ""),
                "character": int(imp.get("character", 0)),
                "pointer": 0,
            }
        )
    if len(children) < 2:
        return
    # exports
    exports_elem = children[1]
    for exp in exports_elem:
        m["exportcount"] += 1
        m["exports"].append(
            {"name": exp.get("name", ""), "character": int(exp.get("character", 0))}
        )
    if len(children) < 3:
        return
    # frames
    frames_elem = children[2]
    for frame_elem in frames_elem:
        f = {"frameitemcount": 0, "frameitems": []}
        m["frames"].append(f)
        m["framecount"] += 1
        for fi_elem in frame_elem:
            _parse_frame_item_elem(fi_elem, f, data)


def _parse_frame_item_elem(elem, frame, data):
    tag = elem.tag.lower()
    if tag == "action":
        ab = _new_ab()
        xml_process_actions(elem, ab, data)
        frame["frameitems"].append({"type": ACTION_ITEM, "ab": ab})
        frame["frameitemcount"] += 1
    elif tag == "framelabel":
        frame["frameitems"].append(
            {
                "type": FRAMELABEL,
                "label": elem.get("label", ""),
                "frame": int(elem.get("frame", 0)),
                "flags": 0x70000,
            }
        )
        frame["frameitemcount"] += 1
    elif tag == "placeobject":
        po = _build_placeobject(elem, data)
        frame["frameitems"].append(po)
        frame["frameitemcount"] += 1
    elif tag == "removeobject":
        frame["frameitems"].append({"type": REMOVEOBJECT, "depth": int(elem.get("depth", 0))})
        frame["frameitemcount"] += 1
    elif tag == "background":
        frame["frameitems"].append({"type": BACKGROUNDCOLOR, "color": int(elem.get("color", 0))})
        frame["frameitemcount"] += 1
    elif tag == "initaction":
        ab = _new_ab()
        xml_process_actions(elem, ab, data)
        frame["frameitems"].append(
            {"type": INITACTION, "sprite": int(elem.get("sprite", 0)), "ab": ab}
        )
        frame["frameitemcount"] += 1


def _build_placeobject(elem, data):
    red = int(elem.get("red", 0))
    green = int(elem.get("green", 0))
    blue = int(elem.get("blue", 0))
    alpha = int(elem.get("alpha", 0))
    ct = red | (green << 8) | (blue << 16) | (alpha << 24)

    poa = None
    clip_elem = elem.find("clipactions")
    if clip_elem is not None:
        poa = {"clipactioncount": 0, "actions": []}
        for ca in clip_elem:
            ab = _new_ab()
            xml_process_actions(ca, ab, data)
            poa["actions"].append(
                {"flags": int(ca.get("flags", 0)), "flags2": int(ca.get("flags2", 0)), "ab": ab}
            )
            poa["clipactioncount"] += 1

    poflags = 0
    pf_elem = elem.find("poflags")
    if pf_elem is not None:
        poflags = get_po_flags_int(pf_elem.get("value", ""))

    name = None
    pn_elem = elem.find("poname")
    if pn_elem is not None:
        name = pn_elem.get("name", "")

    return {
        "type": PLACEOBJECT,
        "flags": poflags,
        "depth": int(elem.get("depth", 0)),
        "character": int(elem.get("character", 0)),
        "rotm00": float(elem.get("rotm00", 0)),
        "rotm01": float(elem.get("rotm01", 0)),
        "rotm10": float(elem.get("rotm10", 0)),
        "rotm11": float(elem.get("rotm11", 0)),
        "tx": float(elem.get("tx", 0)),
        "ty": float(elem.get("ty", 0)),
        "colortransform": ct,
        "unknown": int(elem.get("unknown", 0)),
        "ratio": float(elem.get("ratio", 0)),
        "name": name,
        "clipdepth": int(elem.get("clipdepth", 0)),
        "poa": poa,
    }


def _build_shape(elem):
    return {
        "type": SHAPE,
        "signature": CHAR_SIG,
        "bounds": (
            float(elem.get("top", 0)),
            float(elem.get("left", 0)),
            float(elem.get("right", 0)),
            float(elem.get("bottom", 0)),
        ),
        "geometry": int(elem.get("geometry", 0)),
    }


def _build_edittext(elem):
    red = int(elem.get("red", 0))
    green = int(elem.get("green", 0))
    blue = int(elem.get("blue", 0))
    alpha = int(elem.get("alpha", 0))
    color = alpha | (blue << 8) | (green << 16) | (red << 24)
    text = None
    ettext = elem.find("ettext")
    if ettext is not None:
        raw = ettext.get("text", "")
        text = raw.replace("\n", "\r")
    var = None
    etvar = elem.find("etvar")
    if etvar is not None:
        var = etvar.get("variable", "")
    return {
        "type": EDITTEXT,
        "signature": CHAR_SIG,
        "bounds": (
            float(elem.get("top", 0)),
            float(elem.get("left", 0)),
            float(elem.get("right", 0)),
            float(elem.get("bottom", 0)),
        ),
        "font": int(elem.get("font", 0)),
        "alignment": int(elem.get("alignment", 0)),
        "color": color,
        "fontheight": float(elem.get("height", 0)),
        "readonly": int(elem.get("readonly", 0)),
        "multiline": int(elem.get("multiline", 0)),
        "wordwrap": int(elem.get("wordwrap", 0)),
        "text": text,
        "variable": var,
    }


def _build_font(elem):
    glyphs = []
    g_elem = elem.find("glyphs")
    if g_elem is not None:
        for g in g_elem:
            glyphs.append(int(g.get("glyph", g.get("id", 0))))
    return {
        "type": FONT,
        "signature": CHAR_SIG,
        "name": elem.get("name", ""),
        "glyphcount": len(glyphs),
        "glyphs": glyphs,
    }


def _build_button(elem, data):
    vertexes = []
    ve = elem.find("vertexes")
    if ve is not None:
        for v in ve:
            vertexes.append((float(v.get("x", 0)), float(v.get("y", 0))))

    triangles = []
    te = elem.find("triangles")
    if te is not None:
        for t in te:
            triangles.append((int(t.get("v1", 0)), int(t.get("v2", 0)), int(t.get("v3", 0))))

    records = []
    re = elem.find("buttonrecords")
    if re is not None:
        for r in re:
            brflags = 0
            bf = r.find("buttonflags")
            if bf is not None:
                brflags = get_but_flags_int(bf.get("value", ""))
            records.append(
                {
                    "flags": brflags,
                    "character": int(r.get("character", 0)),
                    "depth": int(r.get("depth", 0)),
                    "rotm00": float(r.get("rotm00", 0)),
                    "rotm01": float(r.get("rotm01", 0)),
                    "rotm10": float(r.get("rotm10", 0)),
                    "rotm11": float(r.get("rotm11", 0)),
                    "tx": float(r.get("tx", 0)),
                    "ty": float(r.get("ty", 0)),
                    "color": (1.0, 1.0, 1.0, 1.0),
                    "unknown": (0.0, 0.0, 0.0, 0.0),
                }
            )

    bas = []
    bae = elem.find("buttonactions")
    if bae is not None:
        for ba in bae:
            ab = _new_ab()
            xml_process_actions(ba, ab, data)
            bas.append({"flags": get_but_action_flags_int(ba.get("flags", "")), "ab": ab})

    return {
        "type": BUTTON,
        "signature": CHAR_SIG,
        "unknown": 0,
        "unknown2": 0,
        "bounds": (
            float(elem.get("top", 0)),
            float(elem.get("left", 0)),
            float(elem.get("right", 0)),
            float(elem.get("bottom", 0)),
        ),
        "vertexcount": len(vertexes),
        "vertexes": vertexes,
        "trianglecount": len(triangles),
        "triangles": triangles,
        "recordcount": len(records),
        "buttonrecords": records,
        "buttonactioncount": len(bas),
        "buttonactions": bas,
    }


def _build_sprite(elem, data):
    frames = []
    fe = elem.find("frames")
    if fe is not None:
        for frame_elem in fe:
            f = {"frameitemcount": 0, "frameitems": []}
            frames.append(f)
            for fi_elem in frame_elem:
                _parse_frame_item_elem(fi_elem, f, data)
    return {
        "type": SPRITE,
        "signature": CHAR_SIG,
        "framecount": len(frames),
        "frames": frames,
        "pointer": 0,
    }


def _build_text(elem):
    records = []
    re = elem.find("records")
    if re is not None:
        for r in re:
            glyphs = []
            ge = r.find("glyphs")
            if ge is not None:
                for g in ge:
                    glyphs.append(
                        {"index": int(g.get("index", 0)), "advance": int(g.get("advance", 0))}
                    )
            records.append(
                {
                    "font": int(r.get("font", 0)),
                    "color": (
                        float(r.get("red", 0)),
                        float(r.get("green", 0)),
                        float(r.get("blue", 0)),
                        float(r.get("alpha", 0)),
                    ),
                    "unknown": (
                        float(r.get("u1", 0)),
                        float(r.get("u2", 0)),
                        float(r.get("u3", 0)),
                        float(r.get("u4", 0)),
                    ),
                    "offset": (float(r.get("tx", 0)), float(r.get("ty", 0))),
                    "textheight": float(r.get("height", 0)),
                    "glyphcount": len(glyphs),
                    "glyphs": glyphs,
                }
            )
    return {
        "type": TEXT,
        "signature": CHAR_SIG,
        "bounds": (
            float(elem.get("top", 0)),
            float(elem.get("left", 0)),
            float(elem.get("right", 0)),
            float(elem.get("bottom", 0)),
        ),
        "rotateandscale": (
            float(elem.get("rotm00", 0)),
            float(elem.get("rotm01", 0)),
            float(elem.get("rotm10", 0)),
            float(elem.get("rotm11", 0)),
        ),
        "translate": (float(elem.get("tx", 0)), float(elem.get("ty", 0))),
        "recordcount": len(records),
        "records": records,
    }


# Binary generation helpers


def _ab_size(ab):
    """Total binary footprint of an ActionBytes block: bytes + alignment."""
    return ab.actionbytecount + _getalign(ab.actionbytecount)


def _ab_extra1(ab):
    """Size of data pointed to directly by action bytes (strings, push-data arrays, etc.)."""
    total = 0
    for s in ab.actionstrings:
        total += _strlength(s["string"])
    for pd in ab.actionpushdatas:
        total += pd["count"] * 4
    for df2 in ab.actiondefinefunction2s:
        total += df2["argumentcount"] * 8
        for arg in df2["arguments"]:
            total += _strlength(arg["name"])
    for df in ab.actiondefinefunctions:
        total += df["argumentcount"] * 4
        for argname in df["arguments"]:
            total += _strlength(argname)
    return total


def _ab_extra0(ab):
    """Size of constant pool array (pointed to at offset +8 of action bytes)."""
    return ab.constantcount * 4


def _get_fi_size(frame):
    """GetFrameItemSize equivalent: size in 'fi' section per frame."""
    sz = 0
    for fi in frame["frameitems"]:
        sz += 4  # original code adds 4 per item (may be unintentional padding)
        t = fi["type"]
        if t == ACTION_ITEM:
            sz += SZ_OUTPUTACTION
        elif t == FRAMELABEL:
            sz += SZ_FRAMELABEL
        elif t == PLACEOBJECT:
            sz += SZ_PLACEOBJECT
        elif t == REMOVEOBJECT:
            sz += SZ_REMOVEOBJECT
        elif t == BACKGROUNDCOLOR:
            sz += SZ_BACKGROUNDCOLOR
        elif t == INITACTION:
            sz += SZ_OUTPUTINITACTION
    return sz


def _get_fi_ptr_size(frame):
    """GetFrameItemPointerSize: size in 'fip' section."""
    sz = 0
    for fi in frame["frameitems"]:
        t = fi["type"]
        if t in (ACTION_ITEM, INITACTION):
            sz += _ab_size(fi["ab"])
        elif t == FRAMELABEL:
            sz += _strlength(fi["label"])
        elif t == PLACEOBJECT:
            if fi["name"]:
                sz += _strlength(fi["name"])
            if fi["poa"]:
                sz += SZ_OUTPUTPLACEOBJECTACTIONS
    return sz


def _get_fi_pp_size(frame):
    """GetFrameItemPointerPointerSize: size in 'ads' section."""
    sz = 0
    for fi in frame["frameitems"]:
        t = fi["type"]
        if t in (ACTION_ITEM, INITACTION):
            sz += _ab_extra0(fi["ab"])
            sz += _ab_extra1(fi["ab"])  # NOTE: C++ lumps strings+pushdata+funcargs into 'ads' too
        elif t == PLACEOBJECT:
            if fi["poa"]:
                sz += fi["poa"]["clipactioncount"] * SZ_PLACEOBJECTACTION
    return sz


def _get_fi_ppp_size(frame):
    """GetFrameItemPointerPointerPointerSize: size in 'ads2' section."""
    sz = 0
    for fi in frame["frameitems"]:
        if fi["type"] == PLACEOBJECT and fi["poa"]:
            for act in fi["poa"]["actions"]:
                sz += _ab_size(act["ab"])
    return sz


def _get_fi_pppp_size(frame):
    """GetFrameItemPointerPointerPointerPointerSize: size in 'ads3' section."""
    sz = 0
    for fi in frame["frameitems"]:
        if fi["type"] == PLACEOBJECT and fi["poa"]:
            for act in fi["poa"]["actions"]:
                ab = act["ab"]
                sz += _ab_extra0(ab) + _ab_extra1(ab)
    return sz


def _button_fip_size(b):
    total = 0
    for ba in b["buttonactions"]:
        total += _ab_size(ba["ab"])
    return total


def _button_fipp_size(b):
    total = 0
    for ba in b["buttonactions"]:
        total += _ab_extra0(ba["ab"]) + _ab_extra1(ba["ab"])
    return total


# Main binary writer


def _generate_apt_file(m):
    """Build the .apt binary in memory. Returns `(buffer, movie_struct_offset)`
    without touching the filesystem."""

    # Section size calculation
    aptdatasize = 16  # header "Apt Data:7\x1A\0" + padding to 16
    characterdatasize = 0
    framesize = 0  # OutputFrame array
    frameitemlistsize = 0  # pointer arrays (frameitem**)
    frameitemsize = 0  # actual frame items
    fip_size = 0  # fip region
    fipp_size = 0  # ads region
    fppp_size = 0  # ads2 region
    fpppp_size = 0  # ads3 region

    for imp in m["imports"]:
        aptdatasize += SZ_IMPORT
        aptdatasize += _strlength(imp["movie"])
        aptdatasize += _strlength(imp["name"])

    for exp in m["exports"]:
        aptdatasize += SZ_EXPORT
        aptdatasize += _strlength(exp["name"])

    aptdatasize += m["charactercount"] * 4  # character pointer table

    for ch in m["characters"]:
        if ch is None:
            continue
        t = ch["type"]
        if t == SHAPE:
            aptdatasize += SZ_SHAPE
            characterdatasize += SZ_SHAPE
        elif t == EDITTEXT:
            aptdatasize += SZ_EDITTEXT
            characterdatasize += SZ_EDITTEXT
            if ch["text"] is not None:
                aptdatasize += _strlength(ch["text"])
                framesize += _strlength(ch["text"])
            if ch["variable"] is not None:
                aptdatasize += _strlength(ch["variable"])
                framesize += _strlength(ch["variable"])
        elif t == FONT:
            aptdatasize += SZ_OUTPUTFONT
            characterdatasize += SZ_OUTPUTFONT
            aptdatasize += _strlength(ch["name"])
            framesize += _strlength(ch["name"])
            aptdatasize += ch["glyphcount"] * 4
            framesize += ch["glyphcount"] * 4
        elif t == IMAGE:
            aptdatasize += SZ_IMAGE
            characterdatasize += SZ_IMAGE
        elif t == MORPH:
            aptdatasize += SZ_MORPH
            characterdatasize += SZ_MORPH
        elif t == BUTTON:
            aptdatasize += SZ_OUTPUTBUTTON
            characterdatasize += SZ_OUTPUTBUTTON
            aptdatasize += ch["vertexcount"] * SZ_VECTOR2
            frameitemsize += ch["vertexcount"] * SZ_VECTOR2
            aptdatasize += ch["trianglecount"] * SZ_TRIANGLE
            frameitemsize += ch["trianglecount"] * SZ_TRIANGLE
            tri_align = _getalign(ch["trianglecount"] * SZ_TRIANGLE)
            aptdatasize += tri_align
            frameitemsize += tri_align
            aptdatasize += ch["recordcount"] * SZ_BUTTONRECORD
            frameitemsize += ch["recordcount"] * SZ_BUTTONRECORD
            aptdatasize += ch["buttonactioncount"] * SZ_OUTPUTBUTTONACTION
            frameitemsize += ch["buttonactioncount"] * SZ_OUTPUTBUTTONACTION
            bfip = _button_fip_size(ch)
            aptdatasize += bfip
            fip_size += bfip
            bfipp = _button_fipp_size(ch)
            aptdatasize += bfipp
            fipp_size += bfipp
        elif t == SPRITE:
            aptdatasize += SZ_OUTPUTSPRITE
            characterdatasize += SZ_OUTPUTSPRITE
            for fr in ch["frames"]:
                aptdatasize += SZ_OUTPUTFRAME
                framesize += SZ_OUTPUTFRAME
                aptdatasize += fr["frameitemcount"] * 4
                frameitemlistsize += fr["frameitemcount"] * 4
                fi = _get_fi_size(fr)
                aptdatasize += fi
                frameitemsize += fi
                fip = _get_fi_ptr_size(fr)
                aptdatasize += fip
                fip_size += fip
                fipp = _get_fi_pp_size(fr)
                aptdatasize += fipp
                fipp_size += fipp
                fppp = _get_fi_ppp_size(fr)
                aptdatasize += fppp
                fppp_size += fppp
                aptdatasize += _get_fi_pppp_size(fr)
                fpppp_size += _get_fi_pppp_size(fr)
        elif t == MOVIE:
            aptdatasize += SZ_OUTPUTMOVIE
            characterdatasize += SZ_OUTPUTMOVIE
            for fr in ch["frames"]:
                aptdatasize += SZ_OUTPUTFRAME
                framesize += SZ_OUTPUTFRAME
                aptdatasize += fr["frameitemcount"] * 4
                frameitemlistsize += fr["frameitemcount"] * 4
                fi = _get_fi_size(fr)
                aptdatasize += fi
                frameitemsize += fi
                fip = _get_fi_ptr_size(fr)
                aptdatasize += fip
                fip_size += fip
                fipp = _get_fi_pp_size(fr)
                aptdatasize += fipp
                fipp_size += fipp
                fppp = _get_fi_ppp_size(fr)
                aptdatasize += fppp
                fppp_size += fppp
                aptdatasize += _get_fi_pppp_size(fr)
                fpppp_size += _get_fi_pppp_size(fr)
        elif t == TEXT:
            aptdatasize += SZ_OUTPUTTEXT
            characterdatasize += SZ_OUTPUTTEXT
            aptdatasize += ch["recordcount"] * SZ_OUTPUTTEXTRECORD
            frameitemsize += ch["recordcount"] * SZ_OUTPUTTEXTRECORD
            for rec in ch["records"]:
                aptdatasize += rec["glyphcount"] * SZ_GLYPH
                fip_size += rec["glyphcount"] * SZ_GLYPH

    aptdatasize += fpppp_size  # add ads3 size not yet counted above

    # Allocate buffer
    buf = bytearray(aptdatasize)

    # Compute section start offsets
    # header 12 bytes
    hdr_end = 12
    imp_start = hdr_end  # imports come right after header

    imp_off = imp_start
    for imp in m["imports"]:
        imp_off += SZ_IMPORT
        imp_off += _strlength(imp["movie"])
        imp_off += _strlength(imp["name"])
    exp_start = imp_off

    exp_off = exp_start
    for exp in m["exports"]:
        exp_off += SZ_EXPORT
        exp_off += _strlength(exp["name"])
    chartbl_start = exp_off
    chardata_start = chartbl_start + m["charactercount"] * 4
    frame_start = chardata_start + characterdatasize
    fil_start = frame_start + framesize
    fi_start = fil_start + frameitemlistsize
    fip_start = fi_start + frameitemsize
    ads_start = fip_start + fip_size
    ads2_start = ads_start + fipp_size
    ads3_start = ads2_start + fppp_size

    # Write header
    buf[0:12] = b"Apt Data:7\x1a\x00"

    # Write imports: struct array then strings, interleaved per C++ layout
    imp_p = imp_start
    for imp in m["imports"]:
        imp["_off"] = imp_p  # remember struct offset for pointer fill-in
        imp_p += SZ_IMPORT
    for imp in m["imports"]:
        movie_str_off = imp_p
        s = imp["movie"].encode("latin-1") + b"\x00"
        buf[imp_p : imp_p + len(s)] = s
        imp_p += _strlength(imp["movie"])
        name_str_off = imp_p
        s = imp["name"].encode("latin-1") + b"\x00"
        buf[imp_p : imp_p + len(s)] = s
        imp_p += _strlength(imp["name"])
        # Fill struct
        base = imp["_off"]
        struct.pack_into("<I", buf, base, movie_str_off)  # movie ptr
        struct.pack_into("<I", buf, base + 4, name_str_off)  # name ptr
        struct.pack_into("<I", buf, base + 8, imp["character"])
        struct.pack_into("<I", buf, base + 12, 0)  # runtime pointer

    # Write exports
    exp_p = exp_start
    for exp in m["exports"]:
        exp["_off"] = exp_p
        exp_p += SZ_EXPORT
    for exp in m["exports"]:
        name_str_off = exp_p
        s = exp["name"].encode("latin-1") + b"\x00"
        buf[exp_p : exp_p + len(s)] = s
        exp_p += _strlength(exp["name"])
        base = exp["_off"]
        struct.pack_into("<I", buf, base, name_str_off)
        struct.pack_into("<I", buf, base + 4, exp["character"])

    # Write characters
    ch_tbl = chartbl_start  # current position in character pointer table
    chd = [chardata_start]  # mutable current position in character data section
    fr_p = [frame_start]
    fil_p = [fil_start]
    fi_p = [fi_start]
    fip_p = [fip_start]
    ads_p = [ads_start]
    ads2_p = [ads2_start]
    ads3_p = [ads3_start]

    imp_struct_off = imp_start
    exp_struct_off = exp_start

    for ch in m["characters"]:
        if ch is None:
            struct.pack_into("<I", buf, ch_tbl, 0)
            ch_tbl += 4
            continue
        struct.pack_into("<I", buf, ch_tbl, chd[0])
        ch_tbl += 4

        t = ch["type"]

        if t == SHAPE:
            _write_shape(buf, chd, ch)
        elif t == EDITTEXT:
            _write_edittext(buf, chd, fr_p, ch)
        elif t == FONT:
            _write_font(buf, chd, fr_p, ch)
        elif t == IMAGE:
            _write_image(buf, chd, ch)
        elif t == MORPH:
            _write_morph(buf, chd, ch)
        elif t == BUTTON:
            _write_button(buf, chd, fi_p, fip_p, ads_p, ch)
        elif t == SPRITE:
            _write_sprite(buf, chd, fr_p, fil_p, fi_p, fip_p, ads_p, ads2_p, ads3_p, ch)
        elif t == MOVIE:
            _write_movie_char(
                buf,
                chd,
                fr_p,
                fil_p,
                fi_p,
                fip_p,
                ads_p,
                ads2_p,
                ads3_p,
                ch,
                imp_struct_off,
                exp_struct_off,
                chartbl_start,
            )
        elif t == TEXT:
            _write_text(buf, chd, fi_p, fip_p, ch)

    # Determine movie struct offset (first character = movie)
    movie_struct_off = struct.unpack_from("<I", buf, chartbl_start)[0]

    # Return the buffer plus the aptdataoffset (offset to movie struct from start)
    return bytes(buf), movie_struct_off


# Per-character write helpers


def _w32(buf, p, v):
    struct.pack_into("<I", buf, p, v & 0xFFFFFFFF)


def _wi32(buf, p, v):
    struct.pack_into("<i", buf, p, v)


def _wf(buf, p, v):
    struct.pack_into("<f", buf, p, v)


def _wstr(buf, p, s):
    b = (s or "").encode("latin-1") + b"\x00"
    buf[p : p + len(b)] = b
    return _strlength(s or "")


def _write_shape(buf, chd, ch):
    p = chd[0]
    _w32(buf, p, ch["type"])
    _w32(buf, p + 4, ch["signature"])
    top, left, right, bottom = ch["bounds"]
    _wf(buf, p + 8, left)
    _wf(buf, p + 12, top)
    _wf(buf, p + 16, right)
    _wf(buf, p + 20, bottom)
    _w32(buf, p + 24, ch["geometry"])
    chd[0] += SZ_SHAPE


def _write_edittext(buf, chd, fr_p, ch):
    p = chd[0]
    chd[0] += SZ_EDITTEXT
    _w32(buf, p, ch["type"])
    _w32(buf, p + 4, ch["signature"])
    top, left, right, bottom = ch["bounds"]
    _wf(buf, p + 8, left)
    _wf(buf, p + 12, top)
    _wf(buf, p + 16, right)
    _wf(buf, p + 20, bottom)
    _w32(buf, p + 24, ch["font"])
    _w32(buf, p + 28, ch["alignment"])
    _w32(buf, p + 32, ch["color"])
    _wf(buf, p + 36, ch["fontheight"])
    _w32(buf, p + 40, ch["readonly"])
    _w32(buf, p + 44, ch["multiline"])
    _w32(buf, p + 48, ch["wordwrap"])
    if ch["text"] is not None:
        _w32(buf, p + 52, fr_p[0])
        _wstr(buf, fr_p[0], ch["text"])
        fr_p[0] += _strlength(ch["text"])
    else:
        _w32(buf, p + 52, 0)
    if ch["variable"] is not None:
        _w32(buf, p + 56, fr_p[0])
        _wstr(buf, fr_p[0], ch["variable"])
        fr_p[0] += _strlength(ch["variable"])
    else:
        _w32(buf, p + 56, 0)


def _write_font(buf, chd, fr_p, ch):
    p = chd[0]
    chd[0] += SZ_OUTPUTFONT
    _w32(buf, p, ch["type"])
    _w32(buf, p + 4, ch["signature"])
    _w32(buf, p + 8, fr_p[0])  # name ptr
    _wstr(buf, fr_p[0], ch["name"])
    fr_p[0] += _strlength(ch["name"])
    _w32(buf, p + 12, ch["glyphcount"])
    if ch["glyphcount"]:
        _w32(buf, p + 16, fr_p[0])
        for gi, gv in enumerate(ch["glyphs"]):
            _w32(buf, fr_p[0] + gi * 4, gv)
        fr_p[0] += ch["glyphcount"] * 4
    else:
        _w32(buf, p + 16, 0)


def _write_image(buf, chd, ch):
    p = chd[0]
    chd[0] += SZ_IMAGE
    _w32(buf, p, ch["type"])
    _w32(buf, p + 4, ch["signature"])
    _w32(buf, p + 8, ch["texture"])


def _write_morph(buf, chd, ch):
    p = chd[0]
    chd[0] += SZ_MORPH
    _w32(buf, p, ch["type"])
    _w32(buf, p + 4, ch["signature"])
    _w32(buf, p + 8, ch["startshape"])
    _w32(buf, p + 12, ch["endshape"])


def _write_button(buf, chd, fi_p, fip_p, ads_p, ch):
    p = chd[0]
    chd[0] += SZ_OUTPUTBUTTON
    _w32(buf, p, ch["type"])
    _w32(buf, p + 4, ch["signature"])
    _w32(buf, p + 8, ch.get("unknown", 0))
    top, left, right, bottom = ch["bounds"]
    _wf(buf, p + 12, left)
    _wf(buf, p + 16, top)
    _wf(buf, p + 20, right)
    _wf(buf, p + 24, bottom)
    _w32(buf, p + 28, ch["trianglecount"])
    _w32(buf, p + 32, ch["vertexcount"])

    if ch["vertexcount"]:
        _w32(buf, p + 36, fi_p[0])
        for v in ch["vertexes"]:
            _wf(buf, fi_p[0], v[0])
            _wf(buf, fi_p[0] + 4, v[1])
            fi_p[0] += SZ_VECTOR2
    else:
        _w32(buf, p + 36, 0)

    if ch["trianglecount"]:
        _w32(buf, p + 40, fi_p[0])
        for tri in ch["triangles"]:
            struct.pack_into("<HHH", buf, fi_p[0], tri[0], tri[1], tri[2])
            fi_p[0] += SZ_TRIANGLE
        fi_p[0] += _getalign(ch["trianglecount"] * SZ_TRIANGLE)
    else:
        _w32(buf, p + 40, 0)

    _w32(buf, p + 44, ch["recordcount"])
    if ch["recordcount"]:
        _w32(buf, p + 48, fi_p[0])
        for rec in ch["buttonrecords"]:
            rp = fi_p[0]
            fi_p[0] += SZ_BUTTONRECORD
            _w32(buf, rp, rec["flags"])
            _w32(buf, rp + 4, rec["character"])
            _wi32(buf, rp + 8, rec["depth"])
            _wf(buf, rp + 12, rec["rotm00"])
            _wf(buf, rp + 16, rec["rotm01"])
            _wf(buf, rp + 20, rec["rotm10"])
            _wf(buf, rp + 24, rec["rotm11"])
            _wf(buf, rp + 28, rec["tx"])
            _wf(buf, rp + 32, rec["ty"])
            c = rec["color"]
            _wf(buf, rp + 36, c[0])
            _wf(buf, rp + 40, c[1])
            _wf(buf, rp + 44, c[2])
            _wf(buf, rp + 48, c[3])
            u = rec["unknown"]
            _wf(buf, rp + 52, u[0])
            _wf(buf, rp + 56, u[1])
            _wf(buf, rp + 60, u[2])
            _wf(buf, rp + 64, u[3])
    else:
        _w32(buf, p + 48, 0)

    _w32(buf, p + 52, ch["buttonactioncount"])
    if ch["buttonactioncount"]:
        _w32(buf, p + 56, fi_p[0])
        for ba in ch["buttonactions"]:
            bap = fi_p[0]
            fi_p[0] += SZ_OUTPUTBUTTONACTION
            _w32(buf, bap, ba["flags"])
            ab = ba["ab"]
            _w32(buf, bap + 4, fip_p[0])
            abcs = fip_p[0]
            buf[fip_p[0] : fip_p[0] + ab.actionbytecount] = ab.buf
            fip_p[0] += ab.actionbytecount
            fip_p[0] += _getalign(ab.actionbytecount)
            _write_ab_extras(buf, abcs, ab, ads_p)
    else:
        _w32(buf, p + 56, 0)

    _w32(buf, p + 60, ch.get("unknown2", 0))


def _write_sprite(buf, chd, fr_p, fil_p, fi_p, fip_p, ads_p, ads2_p, ads3_p, ch):
    p = chd[0]
    chd[0] += SZ_OUTPUTSPRITE
    _w32(buf, p, ch["type"])
    _w32(buf, p + 4, ch["signature"])
    _w32(buf, p + 8, ch["framecount"])
    if ch["framecount"]:
        _w32(buf, p + 12, fr_p[0])
    else:
        _w32(buf, p + 12, 0)
    _w32(buf, p + 16, ch["pointer"])
    _write_frames(buf, fr_p, fil_p, fi_p, fip_p, ads_p, ads2_p, ads3_p, ch["frames"])


def _write_movie_char(
    buf,
    chd,
    fr_p,
    fil_p,
    fi_p,
    fip_p,
    ads_p,
    ads2_p,
    ads3_p,
    ch,
    imp_start,
    exp_start,
    chartbl_start,
):
    p = chd[0]
    chd[0] += SZ_OUTPUTMOVIE
    _w32(buf, p, ch["type"])
    _w32(buf, p + 4, ch["signature"])
    _w32(buf, p + 8, ch["framecount"])
    if ch["framecount"]:
        _w32(buf, p + 12, fr_p[0])
    else:
        _w32(buf, p + 12, 0)
    _w32(buf, p + 16, ch["pointer"])
    _w32(buf, p + 20, ch["charactercount"])
    _w32(buf, p + 24, chartbl_start)  # characters pointer = start of pointer table
    _w32(buf, p + 28, ch.get("screensizex", 1024))
    _w32(buf, p + 32, ch.get("screensizey", 768))
    _w32(buf, p + 36, ch.get("unknown", 33))
    _w32(buf, p + 40, ch["importcount"])
    # imports pointer: point to import struct array (or chartbl if no imports)
    _w32(buf, p + 44, imp_start if ch["importcount"] else chartbl_start)
    _w32(buf, p + 48, ch["exportcount"])
    _w32(buf, p + 52, exp_start if ch["exportcount"] else chartbl_start)
    _w32(buf, p + 56, ch.get("count", 0))
    _write_frames(buf, fr_p, fil_p, fi_p, fip_p, ads_p, ads2_p, ads3_p, ch["frames"])


def _write_text(buf, chd, fi_p, fip_p, ch):
    p = chd[0]
    chd[0] += SZ_OUTPUTTEXT
    _w32(buf, p, ch["type"])
    _w32(buf, p + 4, ch["signature"])
    top, left, right, bottom = ch["bounds"]
    _wf(buf, p + 8, left)
    _wf(buf, p + 12, top)
    _wf(buf, p + 16, right)
    _wf(buf, p + 20, bottom)
    rs = ch["rotateandscale"]
    _wf(buf, p + 24, rs[0])
    _wf(buf, p + 28, rs[1])
    _wf(buf, p + 32, rs[2])
    _wf(buf, p + 36, rs[3])
    tx, ty = ch["translate"]
    _wf(buf, p + 40, tx)
    _wf(buf, p + 44, ty)
    _w32(buf, p + 48, ch["recordcount"])
    if ch["recordcount"]:
        _w32(buf, p + 52, fi_p[0])
        for rec in ch["records"]:
            rp = fi_p[0]
            fi_p[0] += SZ_OUTPUTTEXTRECORD
            _w32(buf, rp, rec["font"])
            c = rec["color"]
            _wf(buf, rp + 4, c[0])
            _wf(buf, rp + 8, c[1])
            _wf(buf, rp + 12, c[2])
            _wf(buf, rp + 16, c[3])
            u = rec["unknown"]
            _wf(buf, rp + 20, u[0])
            _wf(buf, rp + 24, u[1])
            _wf(buf, rp + 28, u[2])
            _wf(buf, rp + 32, u[3])
            ox, oy = rec["offset"]
            _wf(buf, rp + 36, ox)
            _wf(buf, rp + 40, oy)
            _wf(buf, rp + 44, rec["textheight"])
            _w32(buf, rp + 48, rec["glyphcount"])
            if rec["glyphcount"]:
                _w32(buf, rp + 52, fip_p[0])
                for g in rec["glyphs"]:
                    _w32(buf, fip_p[0], g["index"])
                    _wi32(buf, fip_p[0] + 4, g["advance"])
                    fip_p[0] += SZ_GLYPH
            else:
                _w32(buf, rp + 52, 0)
    else:
        _w32(buf, p + 52, 0)


def _write_frames(buf, fr_p, fil_p, fi_p, fip_p, ads_p, ads2_p, ads3_p, frames):
    for frame in frames:
        fp = fr_p[0]
        fr_p[0] += SZ_OUTPUTFRAME
        _w32(buf, fp, frame["frameitemcount"])
        if frame["frameitemcount"]:
            _w32(buf, fp + 4, fil_p[0])
        else:
            _w32(buf, fp + 4, 0)
        for fi in frame["frameitems"]:
            _w32(buf, fil_p[0], fi_p[0])
            fil_p[0] += 4
            _write_frame_item(buf, fi_p, fip_p, ads_p, ads2_p, ads3_p, fi)


def _write_frame_item(buf, fi_p, fip_p, ads_p, ads2_p, ads3_p, fi):
    t = fi["type"]

    if t == ACTION_ITEM:
        p = fi_p[0]
        fi_p[0] += SZ_OUTPUTACTION
        _w32(buf, p, ACTION_ITEM)
        ab = fi["ab"]
        _w32(buf, p + 4, fip_p[0])
        abcs = fip_p[0]
        buf[fip_p[0] : fip_p[0] + ab.actionbytecount] = ab.buf
        fip_p[0] += ab.actionbytecount + _getalign(ab.actionbytecount)
        _write_ab_extras(buf, abcs, ab, ads_p)

    elif t == FRAMELABEL:
        p = fi_p[0]
        fi_p[0] += SZ_FRAMELABEL
        _w32(buf, p, FRAMELABEL)
        _w32(buf, p + 4, fip_p[0])
        _wstr(buf, fip_p[0], fi["label"])
        fip_p[0] += _strlength(fi["label"])
        _w32(buf, p + 8, fi["flags"])
        _w32(buf, p + 12, fi["frame"])

    elif t == PLACEOBJECT:
        p = fi_p[0]
        fi_p[0] += SZ_PLACEOBJECT
        _write_placeobject_bin(buf, p, fi, fip_p, ads_p, ads2_p, ads3_p)

    elif t == REMOVEOBJECT:
        p = fi_p[0]
        fi_p[0] += SZ_REMOVEOBJECT
        _w32(buf, p, REMOVEOBJECT)
        _wi32(buf, p + 4, fi["depth"])

    elif t == BACKGROUNDCOLOR:
        p = fi_p[0]
        fi_p[0] += SZ_BACKGROUNDCOLOR
        _w32(buf, p, BACKGROUNDCOLOR)
        _w32(buf, p + 4, fi["color"])

    elif t == INITACTION:
        p = fi_p[0]
        fi_p[0] += SZ_OUTPUTINITACTION
        _w32(buf, p, INITACTION)
        _w32(buf, p + 4, fi["sprite"])
        ab = fi["ab"]
        _w32(buf, p + 8, fip_p[0])
        abcs = fip_p[0]
        buf[fip_p[0] : fip_p[0] + ab.actionbytecount] = ab.buf
        fip_p[0] += ab.actionbytecount + _getalign(ab.actionbytecount)
        _write_ab_extras(buf, abcs, ab, ads_p)


def _write_placeobject_bin(buf, p, fi, fip_p, ads_p, ads2_p, ads3_p):
    _w32(buf, p, PLACEOBJECT)
    _w32(buf, p + 4, fi["flags"])
    _wi32(buf, p + 8, fi["depth"])
    _wi32(buf, p + 12, fi["character"])
    _wf(buf, p + 16, fi["rotm00"])
    _wf(buf, p + 20, fi["rotm01"])
    _wf(buf, p + 24, fi["rotm10"])
    _wf(buf, p + 28, fi["rotm11"])
    _wf(buf, p + 32, fi["tx"])
    _wf(buf, p + 36, fi["ty"])
    _w32(buf, p + 40, fi["colortransform"])
    _w32(buf, p + 44, fi["unknown"])
    _wf(buf, p + 48, fi["ratio"])
    if fi["name"]:
        _w32(buf, p + 52, fip_p[0])
        _wstr(buf, fip_p[0], fi["name"])
        fip_p[0] += _strlength(fi["name"])
    else:
        _w32(buf, p + 52, 0)
    _wi32(buf, p + 56, fi["clipdepth"])
    if fi["poa"]:
        poa = fi["poa"]
        _w32(buf, p + 60, fip_p[0])
        poa_off = fip_p[0]
        fip_p[0] += SZ_OUTPUTPLACEOBJECTACTIONS
        _w32(buf, poa_off, poa["clipactioncount"])
        _w32(buf, poa_off + 4, ads_p[0])
        act_arr_off = ads_p[0]
        ads_p[0] += poa["clipactioncount"] * SZ_PLACEOBJECTACTION
        for k, act in enumerate(poa["actions"]):
            ap = act_arr_off + k * SZ_PLACEOBJECTACTION
            _w32(buf, ap, act["flags"])
            _w32(buf, ap + 4, act["flags2"])
            ab = act["ab"]
            _w32(buf, ap + 8, ads2_p[0])
            abcs = ads2_p[0]
            buf[ads2_p[0] : ads2_p[0] + ab.actionbytecount] = ab.buf
            ads2_p[0] += ab.actionbytecount + _getalign(ab.actionbytecount)
            _write_ab_extras(buf, abcs, ab, ads3_p)
    else:
        _w32(buf, p + 60, 0)


def _write_ab_extras(buf, abcs, ab, ads_p):
    """Write constant pool and string data into the ads region, patch pointers in action bytes."""
    if ab.constantcount:
        # patch pointer at abcs+8 to point to constants array
        _w32(buf, abcs + 8, ads_p[0])
        for val in ab.constants:
            _w32(buf, ads_p[0], val)
            ads_p[0] += 4
    for s in ab.actionstrings:
        _w32(buf, abcs + s["offset"], ads_p[0])
        _wstr(buf, ads_p[0], s["string"])
        ads_p[0] += _strlength(s["string"])
    for pd in ab.actionpushdatas:
        _w32(buf, abcs + pd["offset"], ads_p[0])
        for val in pd["data"]:
            _w32(buf, ads_p[0], val)
            ads_p[0] += 4
    for df2 in ab.actiondefinefunction2s:
        _w32(buf, abcs + df2["offset"], ads_p[0])
        arg_base = ads_p[0]
        ads_p[0] += df2["argumentcount"] * 8
        for ai, arg in enumerate(df2["arguments"]):
            _w32(buf, arg_base + ai * 8, arg["reg"])
            _w32(buf, arg_base + ai * 8 + 4, ads_p[0])
            _wstr(buf, ads_p[0], arg["name"])
            ads_p[0] += _strlength(arg["name"])
    for df in ab.actiondefinefunctions:
        _w32(buf, abcs + df["offset"], ads_p[0])
        arg_base = ads_p[0]
        ads_p[0] += df["argumentcount"] * 4
        for ai, argname in enumerate(df["arguments"]):
            _w32(buf, arg_base + ai * 4, ads_p[0])
            _wstr(buf, ads_p[0], argname)
            ads_p[0] += _strlength(argname)


# Const file writer


def _generate_const_file(data):
    """Build the .const binary in memory. Returns the buffer without touching the
    filesystem."""
    itemcount = data["itemcount"]
    size = 0x20 + itemcount * 8
    for item in data["items"]:
        if item["type"] == TYPE_STRING:
            sv = item["value"] or ""
            size += _strlength(sv)

    buf = bytearray(size)
    buf[0:20] = b"Apt constant file\x1a\x00\x00"
    struct.pack_into("<I", buf, 20, data["aptdataoffset"])
    struct.pack_into("<I", buf, 24, itemcount)
    struct.pack_into("<I", buf, 28, 0x20)  # pointer to item block

    item_base = 0x20
    str_off = item_base + itemcount * 8
    for i, item in enumerate(data["items"]):
        base = item_base + i * 8
        struct.pack_into("<I", buf, base, item["type"])
        if item["type"] == TYPE_STRING:
            struct.pack_into("<I", buf, base + 4, str_off)
            sv = item["value"] or ""
            b = sv.encode("latin-1") + b"\x00"
            buf[str_off : str_off + len(b)] = b
            str_off += _strlength(sv)
        else:
            struct.pack_into("<I", buf, base + 4, item["value"] & 0xFFFFFFFF)

    return bytes(buf)
