"""Smoke test for the browser editor: start `serve()` on a background thread and
drive the three endpoints the UI depends on. Also proves the editor page loads
from the packaged `assets/editor.html` (a broken extraction would fail `/`)."""

import json
import shutil
import socket
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from sage_apt import apt_to_xml
from sage_apt.editor import serve

FIXTURES = Path(__file__).parent / "fixtures"


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _fetch(url, payload=None):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Content-Type": "application/json"} if payload is not None else {}
    req = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=5) as r:
        return r.read().decode("utf-8")


@pytest.fixture
def served(tmp_path):
    shutil.copy(FIXTURES / "SpellStore.apt", tmp_path / "SpellStore.apt")
    shutil.copy(FIXTURES / "SpellStore.const", tmp_path / "SpellStore.const")
    xml_path = apt_to_xml(tmp_path / "SpellStore.apt")

    port = _free_port()
    thread = threading.Thread(target=serve, args=(xml_path, port, False), daemon=True)
    thread.start()

    base = f"http://127.0.0.1:{port}"
    deadline = time.time() + 5
    while True:
        try:
            _fetch(base + "/")
            break
        except OSError:
            if time.time() > deadline:
                raise
            time.sleep(0.05)
    return base, xml_path, tmp_path


def test_page_loads_from_asset(served):
    base, _xml_path, _tmp = served
    page = _fetch(base + "/")
    assert "<title>APT Editor</title>" in page
    # the frame-label state dropdown (Phase 6.3) ships in the page
    assert 'id="label-select"' in page
    # the editing controls (Phase 6.5) ship in the page
    for control in ("undo-btn", "redo-btn", "add-btn", "dup-btn", "del-btn"):
        assert f'id="{control}"' in page


def test_api_xml_returns_file(served):
    base, xml_path, _tmp = served
    data = json.loads(_fetch(base + "/api/xml"))
    assert data["filename"] == "SpellStore.xml"
    assert data["content"] == xml_path.read_text("utf-8")


def test_api_convert_writes_apt(served):
    base, _xml_path, tmp_path = served
    apt_path = tmp_path / "SpellStore.apt"
    apt_path.unlink()
    assert not apt_path.exists()

    data = json.loads(_fetch(base + "/api/convert", payload={}))
    assert data["ok"] is True
    assert apt_path.exists()


# A 1x1 red PNG, base64-decoded — enough to prove /api/texture streams image bytes.
_PNG_1PX = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000d49444154789c63f8cfc0f01f000500010ff6a5a4e40000000049454e44ae426082"
)


class _StubImageMap:
    rects = {7: (0, 0, 5, 9)}


class _StubResolver:
    image_map = _StubImageMap()

    def rect_of(self, image_id):
        return (0, 0, 5, 9) if image_id == 7 else None

    def image_png(self, image_id):
        return _PNG_1PX if image_id == 7 else None

    def geometry_manifest(self):
        return {
            "5": [
                {"kind": "solid", "color": [10, 20, 30, 255], "tris": [[0, 0, 5, 0, 5, 5]]},
                {
                    "kind": "textured",
                    "tex": 1,
                    "w": 64,
                    "h": 32,
                    "inv": [1.0, 0.0, 0.0, 1.0, -3.0, -4.0],
                    "tris": [[0, 0, 5, 0, 5, 5]],
                },
            ]
        }

    def atlas_png_by_texture(self, texture_id):
        return _PNG_1PX if texture_id == 1 else None


@pytest.fixture
def served_with_textures(tmp_path):
    shutil.copy(FIXTURES / "SpellStore.apt", tmp_path / "SpellStore.apt")
    shutil.copy(FIXTURES / "SpellStore.const", tmp_path / "SpellStore.const")
    xml_path = apt_to_xml(tmp_path / "SpellStore.apt")

    port = _free_port()
    thread = threading.Thread(
        target=serve, args=(xml_path, port, False, _StubResolver()), daemon=True
    )
    thread.start()
    base = f"http://127.0.0.1:{port}"
    deadline = time.time() + 5
    while True:
        try:
            _fetch(base + "/")
            break
        except OSError:
            if time.time() > deadline:
                raise
            time.sleep(0.05)
    return base


def test_texture_manifest_and_bytes(served_with_textures):
    base = served_with_textures
    manifest = json.loads(_fetch(base + "/api/textures"))
    assert manifest == {"7": [5, 9]}

    req = urllib.request.Request(base + "/api/texture/7")
    with urllib.request.urlopen(req, timeout=5) as r:
        assert r.headers["Content-Type"] == "image/png"
        assert r.read() == _PNG_1PX

    # An unmapped id 404s rather than serving garbage.
    try:
        urllib.request.urlopen(base + "/api/texture/999", timeout=5)
        raise AssertionError("expected 404")
    except urllib.error.HTTPError as exc:
        assert exc.code == 404


def test_no_resolver_serves_empty_manifest(served):
    base, _xml_path, _tmp = served
    assert json.loads(_fetch(base + "/api/textures")) == {}
    assert json.loads(_fetch(base + "/api/geometry")) == {}


def test_geometry_manifest_and_atlas(served_with_textures):
    base = served_with_textures
    manifest = json.loads(_fetch(base + "/api/geometry"))
    assert set(manifest) == {"5"}
    kinds = [f["kind"] for f in manifest["5"]]
    assert kinds == ["solid", "textured"]
    assert manifest["5"][1]["tex"] == 1

    req = urllib.request.Request(base + "/api/atlas/1")
    with urllib.request.urlopen(req, timeout=5) as r:
        assert r.headers["Content-Type"] == "image/png"
        assert r.read() == _PNG_1PX

    try:
        urllib.request.urlopen(base + "/api/atlas/999", timeout=5)
        raise AssertionError("expected 404")
    except urllib.error.HTTPError as exc:
        assert exc.code == 404
