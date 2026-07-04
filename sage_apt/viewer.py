"""Static, self-contained HTML/SVG visualisation of an APT XML file: the movieclip's
first frame rendered to scale with per-type colouring, hover tooltips, pan/zoom, and
side panels for imports and sprite frame labels. Sprites are recursed into at their
best display frame (a preferred label such as `_on`, else frame 0)."""

import html as html_mod
from collections import Counter
from pathlib import Path
from xml.etree import ElementTree as ET

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
    """Accumulate placeobject state from frame 0 to target_idx (inclusive).
    Returns the live placeobjects sorted by depth, applying removals."""
    state = {}  # depth -> placeobject elem
    for frame in frames[: target_idx + 1]:
        for item in frame:
            if item.tag == "placeobject":
                depth = int(item.get("depth", 0))
                char_id = int(item.get("character", -1))
                if char_id < 0:
                    state.pop(depth, None)
                else:
                    state[depth] = item
    return [state[d] for d in sorted(state)]


def best_frame_items(sprite_elem, preferred_labels=PREFERRED_LABELS):
    """Get accumulated placeobjects for the best display frame."""
    label_idx, frames = _frame_index_map(sprite_elem)
    if not frames:
        return [], ""
    for lbl in preferred_labels:
        if lbl in label_idx:
            items = _accumulate_to(frames, label_idx[lbl])
            if items:
                return items, lbl
    return _accumulate_to(frames, 0), ""


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


def po_to_local(item):
    return [
        float(item.get("rotm00", 1)),
        float(item.get("rotm01", 0)),
        float(item.get("rotm10", 0)),
        float(item.get("rotm11", 1)),
        float(item.get("tx", 0)),
        float(item.get("ty", 0)),
    ]


def get_po_name(item):
    pn = item.find("poname")
    return pn.get("name") if pn is not None else ""


def render_viewer_html(xml_path) -> str:
    """Render `xml_path` (APT XML) to a self-contained HTML page."""
    xml_path = Path(xml_path)
    root = ET.parse(xml_path).getroot()

    chars = {}
    for ch in root:
        cid = ch.get("id")
        if cid is not None:
            chars[int(cid)] = ch

    mc = root.find("movieclip")
    if mc is None:
        raise ValueError(f"{xml_path.name}: no <movieclip> element")
    frames_elem = mc.find("frames")
    frame0 = frames_elem.find("frame") if frames_elem is not None else None
    if frame0 is None:
        raise ValueError(f"{xml_path.name}: movieclip has no frames")

    # Background color
    bg_raw = 0xFF5E5566
    for item in frame0:
        if item.tag == "background":
            bg_raw = int(item.get("color", "0"))
            break
    bg_css = f"rgb({bg_raw & 0xFF},{(bg_raw >> 8) & 0xFF},{(bg_raw >> 16) & 0xFF})"

    layers = []  # (z-sort-key, svg fragment)
    defs_list = []
    visited = set()

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
            items, _lbl = best_frame_items(ch)
            for item in items:
                child_id = int(item.get("character", -1))
                if child_id < 0:
                    continue
                render(
                    child_id, mat_compose(world_t, po_to_local(item)), get_po_name(item), vdepth + 1
                )
            visited.discard(key)

    for item in frame0:
        if item.tag != "placeobject":
            continue
        render(int(item.get("character", -1)), po_to_local(item), get_po_name(item), 0)

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


def write_viewer_html(xml_path, out_path=None) -> Path:
    """Render `xml_path` and write the page next to it (or to `out_path`)."""
    xml_path = Path(xml_path)
    out = Path(out_path) if out_path else xml_path.with_suffix(".html")
    out.write_text(render_viewer_html(xml_path), encoding="utf-8")
    return out


HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<title>APT Viewer — {filename}</title>
<style>
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ background: #111122; color: #cdd; font: 12px/1.4 "Segoe UI", sans-serif; }}
#app {{ display: flex; flex-direction: column; align-items: center; gap: 10px; padding: 14px; }}
header {{ width: {sw}px; display: flex; justify-content: space-between; align-items: baseline; }}
header h1 {{ font-size: 15px; color: #aaccff; font-weight: 500; }}
header p  {{ font-size: 11px; color: #667; }}
#stage-wrap {{ position: relative; }}
svg#stage {{ display: block; border: 1px solid #334; border-radius: 3px; cursor: crosshair; }}
svg#stage .apt-elem:hover > rect,
svg#stage .apt-elem:hover > line {{ filter: brightness(1.8); }}
svg#stage .apt-elem:hover > text {{ font-weight: 700; }}
#tip {{ position: absolute; pointer-events: none; display: none;
        background: #1a1a2e; border: 1px solid #446; padding: 4px 10px;
        font-size: 11px; color: #dde; border-radius: 4px; z-index: 9;
        max-width: 280px; white-space: nowrap; box-shadow: 0 2px 8px #0008; }}
#zoom-btns {{ position: absolute; bottom: 8px; right: 8px; display: flex; gap: 4px; }}
button {{ background: #22223a; color: #aac; border: 1px solid #446; padding: 3px 9px;
          border-radius: 3px; cursor: pointer; font-size: 11px; }}
button:hover {{ background: #33345a; }}
.panels {{ width: {sw}px; display: flex; gap: 10px; flex-wrap: wrap; }}
.panel {{ background: #151525; border: 1px solid #2a2a44; border-radius: 4px;
          padding: 10px 14px; flex: 1; min-width: 220px; }}
.panel h2 {{ font-size: 11px; color: #99aadd; text-transform: uppercase;
             letter-spacing: 1px; margin-bottom: 6px; }}
ul {{ padding-left: 14px; }}
li {{ margin: 3px 0; font-size: 11px; color: #aab; }}
li b {{ color: #ccd; }}
code {{ background: #1e1e30; padding: 0 3px; border-radius: 2px; font-size: 10px; color: #adf; }}
.legend {{ display: flex; gap: 6px; flex-wrap: wrap; }}
.leg {{ display: flex; align-items: center; gap: 5px; font-size: 11px; color: #99a; }}
.swatch {{ width: 13px; height: 13px; border: 1.5px solid; border-radius: 2px; flex-shrink: 0; }}
#sel-info {{ font-size: 11px; color: #aab; line-height: 1.6; }}
#sel-info b {{ color: #dde; }}
</style>
</head>
<body>
<div id="app">
  <header>
    <h1>APT Viewer — {filename}</h1>
    <p>{char_summary}</p>
  </header>

  <div id="stage-wrap">
    <svg id="stage" width="{sw}" height="{sh}"
         viewBox="0 0 {sw} {sh}" xmlns="http://www.w3.org/2000/svg">
      <defs>{defs}</defs>
      <rect width="{sw}" height="{sh}" fill="{bg}"/>
      <g opacity="0.05" stroke="#fff" stroke-width="0.5">{grid}</g>
      {svg_body}
    </svg>
    <div id="tip"></div>
    <div id="zoom-btns">
      <button onclick="zv(1.25)">＋</button>
      <button onclick="zv(0.8)">－</button>
      <button onclick="rv()">⟳</button>
    </div>
  </div>

  <div class="panels">
    <div class="panel">
      <h2>Legend</h2>
      <div class="legend">
        <div class="leg"><div class="swatch" style="background:#aaddff1e;border-color:#5599cc"></div>shape</div>
        <div class="leg"><div class="swatch" style="background:#ffddaa80;border-color:#cc8833"></div>image</div>
        <div class="leg"><div class="swatch" style="background:#aaffcc72;border-color:#44cc66"></div>edittext</div>
        <div class="leg"><div class="swatch" style="background:#ffccdd72;border-color:#ee4466;border-radius:3px"></div>button</div>
        <div class="leg"><div class="swatch" style="background:#ccaaee14;border-color:#9966cc"></div>sprite (structure)</div>
      </div>
    </div>
    <div class="panel">
      <h2>Imports</h2>
      <ul>{imports_html}</ul>
    </div>
    <div class="panel" style="min-width:300px">
      <h2>Frame States</h2>
      <ul>{frames_html}</ul>
    </div>
    <div class="panel">
      <h2>Selected</h2>
      <div id="sel-info">Hover or click an element</div>
    </div>
  </div>
</div>

<script>
const stage  = document.getElementById('stage');
const tip    = document.getElementById('tip');
const selInfo= document.getElementById('sel-info');
const wrap   = document.getElementById('stage-wrap');
let vx=0, vy=0, vw={sw}, vh={sh};

function applyView(){{ stage.setAttribute('viewBox', vx+' '+vy+' '+vw+' '+vh); }}
function zv(f){{
  const cx=vx+vw/2, cy=vy+vh/2;
  vw/=f; vh/=f; vx=cx-vw/2; vy=cy-vh/2; applyView();
}}
function rv(){{ vx=0; vy=0; vw={sw}; vh={sh}; applyView(); }}

// Wheel zoom
stage.addEventListener('wheel', e=>{{
  e.preventDefault();
  const f = e.deltaY>0 ? 0.88 : 1.14;
  const r = stage.getBoundingClientRect();
  const mx=(e.clientX-r.left)/r.width*vw+vx, my=(e.clientY-r.top)/r.height*vh+vy;
  vw/=f; vh/=f; vx=mx-(mx-vx)/f; vy=my-(my-vy)/f; applyView();
}}, {{passive:false}});

// Pan
let drag=null;
stage.addEventListener('mousedown', e=>{{ drag={{x:e.clientX,y:e.clientY,vx,vy}}; }});
window.addEventListener('mousemove', e=>{{
  if(!drag) return;
  vx=drag.vx-(e.clientX-drag.x)*vw/{sw};
  vy=drag.vy-(e.clientY-drag.y)*vh/{sh};
  applyView();
}});
window.addEventListener('mouseup', ()=>{{ drag=null; }});

// Tooltips & selection
stage.querySelectorAll('.apt-elem').forEach(el=>{{
  el.addEventListener('mouseenter', e=>{{
    const t=el.querySelector('title');
    tip.textContent = t ? t.textContent : (el.dataset.type+' id='+el.dataset.id);
    tip.style.display='block';
  }});
  el.addEventListener('mousemove', e=>{{
    const r=wrap.getBoundingClientRect();
    tip.style.left=(e.clientX-r.left+14)+'px';
    tip.style.top=(e.clientY-r.top+14)+'px';
  }});
  el.addEventListener('mouseleave', ()=>{{ tip.style.display='none'; }});
  el.addEventListener('click', ()=>{{
    const t=el.querySelector('title');
    selInfo.innerHTML = '<b>'+el.dataset.type+'</b>'
      +(el.dataset.name ? '  <span style="color:#7af">'+el.dataset.name+'</span>':'')
      +'<br>id = '+el.dataset.id
      +(t ? '<br><span style="opacity:0.7">'+t.textContent.replace(/ +/g,' ')+'</span>' : '');
    stage.querySelectorAll('.apt-elem').forEach(x=>x.style.opacity='');
    el.style.opacity='1';
    stage.querySelectorAll('.apt-elem:not([style])').forEach(x=>x.style.opacity='0.4');
    setTimeout(()=>stage.querySelectorAll('.apt-elem').forEach(x=>x.style.opacity=''), 3000);
  }});
}});
</script>
</body>
</html>"""
