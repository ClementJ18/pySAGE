"""Frame / label selection in the static viewer (Phase 6.3).

`render_viewer_html(xml, frame=, label=)` picks which root frame is drawn and biases each
sprite's display state; the SpellStore fixture declares `_on`/`_off` sprite labels and
`_open`/`_close` root labels."""

import shutil
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from sage_apt import apt_to_xml, render_viewer_html
from sage_apt.geometry import Fill
from sage_apt.viewer import _frame_index_map

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def spellstore_xml(tmp_path):
    shutil.copy(FIXTURES / "SpellStore.apt", tmp_path / "SpellStore.apt")
    shutil.copy(FIXTURES / "SpellStore.const", tmp_path / "SpellStore.const")
    return apt_to_xml(tmp_path / "SpellStore.apt")


def test_label_state_changes_render(spellstore_xml):
    """`_on` vs `_off` produce different SVG where sprites declare those labels."""
    default = render_viewer_html(spellstore_xml)
    on = render_viewer_html(spellstore_xml, label="_on")
    off = render_viewer_html(spellstore_xml, label="_off")
    assert on != off
    assert on != default


def test_root_frame_selection_changes_render(spellstore_xml):
    """A different root frame index renders a different stage."""
    frame0 = render_viewer_html(spellstore_xml, frame=0)
    frame5 = render_viewer_html(spellstore_xml, frame=5)
    assert frame0 != frame5
    assert "frame 5" in frame5  # header note reflects the selection


def test_root_label_selects_root_frame(spellstore_xml):
    """A root frame label (`_open`) picks that root frame."""
    html = render_viewer_html(spellstore_xml, label="_open")
    assert "label _open" in html


def test_every_declared_label_renders(spellstore_xml):
    """No label the movie declares (root or sprite) throws while rendering."""
    root = ET.parse(spellstore_xml).getroot()
    labels: set[str] = set()
    for ch in root:
        if ch.tag in ("movieclip", "sprite"):
            label_idx, _ = _frame_index_map(ch)
            labels |= set(label_idx)
    assert "_on" in labels and "_off" in labels
    for label in sorted(labels):
        assert render_viewer_html(spellstore_xml, label=label)


def test_out_of_range_frame_is_clamped(spellstore_xml):
    """An absurd frame index clamps to the last frame instead of raising."""
    assert render_viewer_html(spellstore_xml, frame=9999)


class _StubResolver:
    """Resolves every image to the same 1x1 data-URI at a fixed rect (Phase 6.4 wiring)."""

    URI = "data:image/png;base64,STUB"

    def image_data_uri(self, image_id):
        return self.URI

    def rect_of(self, image_id):
        return (0, 0, 12, 34)


_MINIMAL_APT_XML = """<?xml version="1.0" ?>
<aptdata>
  <movieclip>
    <imports/>
    <exports/>
    <frames>
      <frame id="0">
        <placeobject depth="1" character="2" tx="100" ty="50"/>
      </frame>
    </frames>
  </movieclip>
  <empty id="0"/>
  <shape id="1" left="0" top="0" right="10" bottom="10"/>
  <image id="2" image="2"/>
</aptdata>
"""


@pytest.fixture
def image_xml(tmp_path):
    path = tmp_path / "Mini.xml"
    path.write_text(_MINIMAL_APT_XML, encoding="utf-8")
    return path


def test_textures_inline_as_images(image_xml):
    """With a resolver, image characters render as <image href=data:...> not placeholders."""
    placeholder = render_viewer_html(image_xml)
    assert "stroke-dasharray" in placeholder  # crossed-box placeholder present by default

    with_art = render_viewer_html(image_xml, textures=_StubResolver())
    assert _StubResolver.URI in with_art
    assert "<image " in with_art
    assert "stroke-dasharray" not in with_art  # placeholder replaced by artwork


_SHAPE_XML = """<?xml version="1.0" ?>
<aptdata>
  <movieclip>
    <imports/><exports/>
    <frames><frame id="0">
      <placeobject depth="1" character="1" tx="100" ty="50"/>
    </frame></frames>
  </movieclip>
  <empty id="0"/>
  <shape id="1" geometry="5" left="0" top="0" right="10" bottom="10"/>
</aptdata>
"""


class _StubImageMap2:
    def texture_of(self, image_id):
        return 1


class _StubShapeResolver:
    """Provides one textured + one solid fill for geometry id 5 (Phase 6.4 shapes)."""

    image_map = _StubImageMap2()

    def shape_fills(self, gid):
        if gid != 5:
            return []
        return [
            Fill("solid", (10, 20, 30, 255), triangles=[(0, 0, 10, 0, 10, 10)]),
            Fill(
                "textured",
                (255, 255, 255, 255),
                triangles=[(0, 0, 10, 0, 10, 10)],
                image_id=102,
                matrix=(1.0, 0.0, 0.0, 1.0, 5.0, 5.0),
            ),
        ]

    def atlas_data_uri(self, image_id):
        return "data:image/png;base64,ATLAS"

    def atlas_size(self, image_id):
        return (64, 32)


def test_shape_geometry_renders_fills(spellstore_xml, tmp_path):
    path = tmp_path / "Shape.xml"
    path.write_text(_SHAPE_XML, encoding="utf-8")

    plain = render_viewer_html(path)
    assert "<polygon" not in plain  # no geometry without a resolver -> plain rect

    art = render_viewer_html(path, textures=_StubShapeResolver())
    assert "<polygon" in art  # solid fill triangles
    assert "<clipPath" in art  # textured fill clip
    assert 'href="#apt_atlas_1"' in art  # atlas shared via <use>
    assert "data:image/png;base64,ATLAS" in art  # atlas inlined once in defs
