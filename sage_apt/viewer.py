"""Static, self-contained HTML/SVG visualisation of an APT XML file: the movieclip's
frame rendered to scale with per-type colouring, hover tooltips, pan/zoom, and side
panels for imports and sprite frame labels. The root frame is frame 0 by default and
can be picked by index (`--frame`) or by a root frame label (`--label`); the same label
also biases which display frame each sprite recurses into (a preferred label such as
`_on`, else frame 0)."""

import html as html_mod
import importlib.resources
from collections import Counter
from pathlib import Path
from typing import NamedTuple
from xml.etree import ElementTree as ET

from sage_apt.flags import _split_flags
from sage_apt.geometry import invert_matrix


def _asset(name: str) -> str:
    return (importlib.resources.files("sage_apt") / "assets" / name).read_text("utf-8")


SCREEN_W = 1024
SCREEN_H = 768

# tag -> (stroke, fill, fill-opacity, label colour)
TYPE_STYLE = {
    "shape": ("#5599cc", "#aaddff", 0.12, "#88bbdd"),
    "image": ("#cc8833", "#ffddaa", 0.50, "#ffbb66"),
    "edittext": ("#44cc66", "#aaffcc", 0.45, "#88ffbb"),
    "button": ("#ee4466", "#ffccdd", 0.45, "#ff99aa"),
    "sprite": ("#9966cc", "#ccaaee", 0.08, "#bb99dd"),
}

PREFERRED_LABELS = ("_fade_in", "_on", "_active", "_purchased")

# PlaceObject flag -> the attributes a record carries when that flag is set. A Move record
# only overwrites the fields its own flags name; everything else stays as the placement left it.
_MOVE_ATTRS = {
    "hasmatrix": ("rotm00", "rotm01", "rotm10", "rotm11", "tx", "ty"),
    "hascolortransform": ("red", "green", "blue", "alpha"),
    "hasratio": ("ratio",),
    "hasclipdepth": ("clipdepth",),
}


class Placed(NamedTuple):
    """One live object on the stage: the placeobject that put it there, plus the attributes
    and instance name left by any later Move records at the same depth. `elem` stays the
    placing record so callers that edit the XML (the browser editor) write to the node that
    actually owns the character."""

    elem: ET.Element
    attrs: dict[str, str]
    name: str

    @property
    def character(self) -> int:
        return int(self.attrs.get("character", -1))


def _po_flags(item):
    """The PlaceObject flags set on `item`, lowercased. Records with no `<poflags>` child
    (hand-written XML, minimal fixtures) are read as a plain placement."""
    flags_elem = item.find("poflags")
    if flags_elem is None:
        return {"hascharacter"} if int(item.get("character", -1)) >= 0 else set()
    return set(_split_flags(flags_elem.get("value", "")))


def _apply_move(placed, item, flags):
    """Overlay a Move record's flagged fields onto the object already at that depth."""
    attrs = dict(placed.attrs)
    for flag, names in _MOVE_ATTRS.items():
        if flag in flags:
            attrs.update({n: item.get(n) for n in names if item.get(n) is not None})
    return Placed(placed.elem, attrs, get_po_name(item) if "hasname" in flags else placed.name)


def _frame_index_map(sprite_elem):
    """Build {label: frame_index, ...} and a list of frames."""
    frames_elem = sprite_elem.find("frames")
    if frames_elem is None:
        return {}, []
    frames = list(frames_elem)
    label_idx = {}
    for fi, frame in enumerate(frames):
        for item in frame:
            if item.tag == "framelabel":
                lbl = item.get("label", "")
                if lbl not in label_idx:
                    label_idx[lbl] = fi
    return label_idx, frames


def _accumulate_to(frames, target_idx):
    """Accumulate stage state from frame 0 to target_idx (inclusive), returning the live
    `Placed` objects sorted by depth.

    A placeobject with HasCharacter places a new object at its depth. One with Move and no
    HasCharacter *updates* whatever already sits there - it carries no character (the XML
    writes `character="-1"`) and only the fields its flags name, which is how a fade-in
    frame raises alpha on objects an earlier frame placed. Removal is its own
    `removeobject` record."""
    state = {}  # depth -> Placed
    for frame in frames[: target_idx + 1]:
        for item in frame:
            if item.tag == "removeobject":
                state.pop(int(item.get("depth", 0)), None)
                continue
            if item.tag != "placeobject":
                continue
            depth = int(item.get("depth", 0))
            flags = _po_flags(item)
            if "hascharacter" in flags:
                state[depth] = Placed(item, dict(item.attrib), get_po_name(item))
            elif "move" in flags and depth in state:
                state[depth] = _apply_move(state[depth], item, flags)
    return [state[d] for d in sorted(state)]


def best_frame_items(sprite_elem, preferred_labels=PREFERRED_LABELS):
    """Get accumulated placeobjects for the best display frame: the first preferred label
    that yields content, else frame 0.

    When both come up empty the sprite is one whose frame 0 is a placeholder and whose real
    content lives on named state frames - a faction switcher holding `_Men` / `_Elves` /
    `_Mordor` images, say - so fall back to the earliest labelled frame that has anything.
    Showing the sprite in *some* state beats leaving a hole on the stage."""
    label_idx, frames = _frame_index_map(sprite_elem)
    if not frames:
        return [], ""
    for lbl in preferred_labels:
        if lbl in label_idx:
            items = _accumulate_to(frames, label_idx[lbl])
            if items:
                return items, lbl
    items = _accumulate_to(frames, 0)
    if items:
        return items, ""
    for lbl, idx in sorted(label_idx.items(), key=lambda kv: kv[1]):
        items = _accumulate_to(frames, idx)
        if items:
            return items, lbl
    return [], ""


def _resolve_target_frame(label_idx, frames, frame, label):
    """The root frame index to render: an explicit `frame` (clamped) wins, else a `label`
    that names a root frame, else frame 0."""
    if frame is not None:
        return max(0, min(int(frame), len(frames) - 1))
    if label is not None and label in label_idx:
        return label_idx[label]
    return 0


def mat_compose(parent, child):
    p00, p01, p10, p11, ptx, pty = parent
    c00, c01, c10, c11, ctx, cty = child
    return [
        p00 * c00 + p10 * c01,
        p01 * c00 + p11 * c01,
        p00 * c10 + p10 * c11,
        p01 * c10 + p11 * c11,
        p00 * ctx + p10 * cty + ptx,
        p01 * ctx + p11 * cty + pty,
    ]


def svg_mat(m):
    return "matrix({:.4f},{:.4f},{:.4f},{:.4f},{:.3f},{:.3f})".format(*tuple(m))


def po_to_local(placed):
    a = placed.attrs
    return [
        float(a.get("rotm00", 1)),
        float(a.get("rotm01", 0)),
        float(a.get("rotm10", 0)),
        float(a.get("rotm11", 1)),
        float(a.get("tx", 0)),
        float(a.get("ty", 0)),
    ]


def get_po_name(item):
    pn = item.find("poname")
    return pn.get("name") if pn is not None else ""


def _tri_points(tri):
    return f"{tri[0]:.2f},{tri[1]:.2f} {tri[2]:.2f},{tri[3]:.2f} {tri[4]:.2f},{tri[5]:.2f}"


def _shape_fills_svg(fills, mat, char_id, name, tip, textures, defs_list, atlas_defs, clip_defs):
    """SVG for a shape drawn from its geometry fills: solid fills as coloured triangles,
    textured fills as the atlas clipped to their triangles and mapped by the fill's inverse
    matrix. The atlas `<image>` is added to `defs` once per texture and shared via `<use>`;
    returns "" when nothing textured/solid could be drawn."""
    body = []
    for fi, fill in enumerate(fills):
        if fill.kind == "solid":
            r, g, b, a = fill.color
            col = f"rgba({r},{g},{b},{a / 255:.3f})"
            for tri in fill.triangles:
                body.append(f'<polygon points="{_tri_points(tri)}" fill="{col}"/>')
        elif fill.kind == "textured" and fill.image_id is not None and fill.matrix is not None:
            uri = textures.atlas_data_uri(fill.image_id)
            size = textures.atlas_size(fill.image_id)
            inv = invert_matrix(fill.matrix)
            if uri is None or size is None or inv is None:
                continue
            tex_id = textures.image_map.texture_of(fill.image_id)
            atlas_id = f"apt_atlas_{tex_id}"
            if tex_id not in atlas_defs:
                atlas_defs.add(tex_id)
                defs_list.append(
                    f'<image id="{atlas_id}" href="{uri}" width="{size[0]}" height="{size[1]}"/>'
                )
            clip_id = f"gclip_{char_id}_{fi}"
            if clip_id not in clip_defs:
                clip_defs.add(clip_id)
                polys = "".join(f'<polygon points="{_tri_points(t)}"/>' for t in fill.triangles)
                defs_list.append(f'<clipPath id="{clip_id}">{polys}</clipPath>')
            xform = "matrix({:.6f},{:.6f},{:.6f},{:.6f},{:.4f},{:.4f})".format(*inv)
            body.append(
                f'<g clip-path="url(#{clip_id})"><use href="#{atlas_id}" transform="{xform}"/></g>'
            )
    if not body:
        return ""
    return (
        f'<g transform="{mat}" class="apt-elem" data-type="shape" data-id="{char_id}"'
        f' data-name="{html_mod.escape(name)}"><title>{tip}</title>{"".join(body)}</g>'
    )


def render_viewer_html(xml_path, frame=None, label=None, textures=None) -> str:
    """Render `xml_path` (APT XML) to a self-contained HTML page. `frame` / `label` pick
    which root frame to draw (index, or a root frame label); `label` also biases which
    display frame each recursed sprite shows, so `--label _on` vs `_off` renders the
    matching state where a sprite declares those labels. `textures`, when given, is an
    `AptTextureResolver`: `image` characters it resolves are drawn as inlined artwork
    instead of crossed-box placeholders."""
    xml_path = Path(xml_path)
    root = ET.parse(xml_path).getroot()

    chars = {}
    for ch in root:
        cid_attr = ch.get("id")
        if cid_attr is not None:
            chars[int(cid_attr)] = ch

    mc = root.find("movieclip")
    if mc is None:
        raise ValueError(f"{xml_path.name}: no <movieclip> element")
    root_label_idx, root_frames = _frame_index_map(mc)
    if not root_frames:
        raise ValueError(f"{xml_path.name}: movieclip has no frames")
    target_idx = _resolve_target_frame(root_label_idx, root_frames, frame, label)

    # A requested label biases every sprite's display frame toward that state first.
    sprite_prefs = (label, *PREFERRED_LABELS) if label else PREFERRED_LABELS

    # Background color: last one set up to and including the target frame.
    bg_raw = 0xFF5E5566
    for f in root_frames[: target_idx + 1]:
        for item in f:
            if item.tag == "background":
                bg_raw = int(item.get("color", "0"))
    bg_css = f"rgb({bg_raw & 0xFF},{(bg_raw >> 8) & 0xFF},{(bg_raw >> 16) & 0xFF})"

    layers = []  # (z-sort-key, svg fragment)
    defs_list: list[str] = []
    visited = set()
    atlas_defs: set[int] = set()  # texture ids whose atlas <image> is already in defs
    clip_defs: set[str] = set()  # geometry clipPath ids already in defs

    def render(char_id, world_t, name="", vdepth=0):
        if vdepth > 14:
            return
        ch = chars.get(char_id)
        if ch is None:
            return
        tag = ch.tag
        mat = svg_mat(world_t)
        stroke, fill, fop, lc = TYPE_STYLE.get(tag, ("#999", "#ddd", 0.2, "#bbb"))
        tip = html_mod.escape(f"id={char_id}  type={tag}  name={name}")

        if tag == "shape" and textures is not None:
            gid = int(ch.get("geometry")) if ch.get("geometry") else -1
            fills = textures.shape_fills(gid)
            if fills:
                frag = _shape_fills_svg(
                    fills, mat, char_id, name, tip, textures, defs_list, atlas_defs, clip_defs
                )
                if frag:
                    layers.append((vdepth * 100, frag))
                    return

        if tag in ("shape", "button"):
            left = float(ch.get("left", 0))
            top = float(ch.get("top", 0))
            w = float(ch.get("right", 0)) - left
            h = float(ch.get("bottom", 0)) - top
            rx = 4 if tag == "button" else 1
            label = (name or tag)[:22]
            sw = 1.5 if vdepth < 3 else 1.0
            s = (
                f'<g transform="{mat}" class="apt-elem" data-type="{tag}" data-id="{char_id}"'
                f' data-name="{html_mod.escape(name)}">'
                f"<title>{tip}</title>"
                f'<rect x="{left:.2f}" y="{top:.2f}" width="{w:.2f}" height="{h:.2f}" '
                f'stroke="{stroke}" stroke-width="{sw:.1f}" fill="{fill}" '
                f'fill-opacity="{fop:.2f}" rx="{rx}"/>'
            )
            if w > 25 and h > 12:
                fs = min(10, h * 0.32, w * 0.09)
                cx, cy = left + w / 2, top + h / 2
                s += (
                    f'<text x="{cx:.1f}" y="{cy + fs * 0.35:.1f}" text-anchor="middle" '
                    f'font-size="{fs:.1f}" fill="{lc}" pointer-events="none" '
                    f'opacity="0.85">{html_mod.escape(label)}</text>'
                )
            s += "</g>"
            layers.append((vdepth * 100 + int(tag == "button") * 10, s))

        elif tag == "image":
            img_id = int(ch.get("image", char_id))
            data_uri = textures.image_data_uri(img_id) if textures is not None else None
            if data_uri is not None:
                x, y, w, h = textures.rect_of(img_id)
                s = (
                    f'<g transform="{mat}" class="apt-elem" data-type="image"'
                    f' data-id="{char_id}" data-name="{html_mod.escape(name)}">'
                    f"<title>{tip}</title>"
                    f'<image x="0" y="0" width="{w}" height="{h}" href="{data_uri}"'
                    f' preserveAspectRatio="none"/>'
                    "</g>"
                )
                layers.append((vdepth * 100 + 5, s))
            else:
                label = (name or f"img{img_id}")[:18]
                half = 36
                s = (
                    f'<g transform="{mat}" class="apt-elem" data-type="image" data-id="{char_id}"'
                    f' data-name="{html_mod.escape(name)}">'
                    f"<title>{tip}</title>"
                    f'<rect x="{-half}" y="{-half}" width="{half * 2}" height="{half * 2}" '
                    f'stroke="{stroke}" stroke-width="1.5" fill="{fill}" '
                    f'fill-opacity="{fop:.2f}" stroke-dasharray="5 2"/>'
                    f'<line x1="{-half}" y1="{-half}" x2="{half}" y2="{half}" '
                    f'stroke="{stroke}" stroke-width="0.8" opacity="0.4"/>'
                    f'<line x1="{half}" y1="{-half}" x2="{-half}" y2="{half}" '
                    f'stroke="{stroke}" stroke-width="0.8" opacity="0.4"/>'
                    f'<text x="0" y="5" text-anchor="middle" font-size="10" '
                    f'fill="{lc}">{html_mod.escape(label)}</text>'
                    "</g>"
                )
                layers.append((vdepth * 100 + 5, s))

        elif tag == "edittext":
            left = float(ch.get("left", 0))
            top = float(ch.get("top", 0))
            w = float(ch.get("right", 0)) - left
            h = float(ch.get("bottom", 0)) - top
            ettext = ch.find("ettext")
            txt = (ettext.get("text", "") if ettext is not None else "")[:40]
            red = int(ch.get("red", 255))
            green = int(ch.get("green", 255))
            blue = int(ch.get("blue", 255))
            fh = min(float(ch.get("height", 12)), h * 0.85, 13)
            clip_id = f"clip_{char_id}"
            defs_list.append(
                f'<clipPath id="{clip_id}"><rect x="{left:.2f}" y="{top:.2f}" '
                f'width="{w:.2f}" height="{h:.2f}"/></clipPath>'
            )
            s = (
                f'<g transform="{mat}" class="apt-elem" data-type="edittext" data-id="{char_id}"'
                f' data-name="{html_mod.escape(name)}">'
                f"<title>{tip}</title>"
                f'<rect x="{left:.2f}" y="{top:.2f}" width="{w:.2f}" height="{h:.2f}" '
                f'stroke="{stroke}" stroke-width="1" fill="#081408" fill-opacity="0.7"/>'
                f'<text x="{left + 2:.2f}" y="{top + fh:.2f}" font-size="{fh:.1f}" '
                f'fill="rgb({red},{green},{blue})" font-family="sans-serif" '
                f'clip-path="url(#{clip_id})">{html_mod.escape(txt)}</text>'
                "</g>"
            )
            layers.append((vdepth * 100 + 20, s))

        elif tag == "sprite":
            key = (char_id, round(world_t[4], 1), round(world_t[5], 1))
            if key in visited:
                return
            visited.add(key)
            items, _lbl = best_frame_items(ch, sprite_prefs)
            for placed in items:
                if placed.character < 0:
                    continue
                render(
                    placed.character,
                    mat_compose(world_t, po_to_local(placed)),
                    placed.name,
                    vdepth + 1,
                )
            visited.discard(key)

    for placed in _accumulate_to(root_frames, target_idx):
        render(placed.character, po_to_local(placed), placed.name, 0)

    layers.sort(key=lambda x: x[0])
    svg_body = "\n".join(s for _, s in layers)

    # Imports panel
    imports_html = ""
    imports_elem = mc.find("imports")
    if imports_elem is not None:
        for imp in imports_elem:
            imports_html += "<li><b>{}</b> ← {} char={}</li>".format(
                html_mod.escape(imp.get("name", "")),
                html_mod.escape(imp.get("movie", "")),
                imp.get("character", ""),
            )

    char_counts = Counter(ch.tag for ch in chars.values())
    char_summary = " · ".join(f"{v} {k}" for k, v in sorted(char_counts.items()))
    if label:
        char_summary += f" · label {label}"
    elif target_idx:
        char_summary += f" · frame {target_idx}"

    # Frame-label panel: the labelled sprites, richest first
    labelled = []
    for cid in sorted(chars):
        ch = chars[cid]
        if ch.tag != "sprite":
            continue
        label_idx, _ = _frame_index_map(ch)
        if label_idx:
            labelled.append((cid, list(label_idx)))
    labelled.sort(key=lambda x: -len(x[1]))
    frames_html = ""
    for cid, labels in labelled[:8]:
        codes = ", ".join(f"<code>{html_mod.escape(lbl)}</code>" for lbl in labels[:12])
        frames_html += f"<li><b>sprite {cid}</b>: {codes}</li>"

    grid = []
    for x in range(0, SCREEN_W + 1, 64):
        grid.append(f'<line x1="{x}" y1="0" x2="{x}" y2="{SCREEN_H}"/>')
    for y in range(0, SCREEN_H + 1, 64):
        grid.append(f'<line x1="0" y1="{y}" x2="{SCREEN_W}" y2="{y}"/>')

    return HTML.format(
        filename=html_mod.escape(xml_path.name),
        sw=SCREEN_W,
        sh=SCREEN_H,
        bg=bg_css,
        defs="\n".join(defs_list),
        grid="\n".join(grid),
        svg_body=svg_body,
        imports_html=imports_html,
        char_summary=html_mod.escape(char_summary),
        frames_html=frames_html,
    )


def write_viewer_html(xml_path, out_path=None, frame=None, label=None, textures=None) -> Path:
    """Render `xml_path` and write the page next to it (or to `out_path`). `frame`/`label`
    select which frame is drawn and `textures` resolves real artwork (see
    `render_viewer_html`)."""
    xml_path = Path(xml_path)
    out = Path(out_path) if out_path else xml_path.with_suffix(".html")
    out.write_text(
        render_viewer_html(xml_path, frame=frame, label=label, textures=textures),
        encoding="utf-8",
    )
    return out


HTML = _asset("viewer.html")
