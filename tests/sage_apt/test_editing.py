"""Phase 6.5 editing depth - add / delete a placeobject and prove it survives the writer.

The add/duplicate/delete/drag/undo operations live in the editor's JavaScript (manual
checklist); what an automated test can pin is that the *shape of XML the JS produces*
saves through `/api/xml` and compiles through `/api/convert` into a valid `.apt` that
re-decompiles with the edit intact. That is the risky seam - a hand-built placeobject that
the compiler rejects would corrupt the export."""

import json
import shutil
import socket
import threading
import time
import urllib.request
from pathlib import Path
from xml.etree import ElementTree as ET

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
    threading.Thread(target=serve, args=(xml_path, port, False), daemon=True).start()
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


def _frame0(root):
    return root.find("movieclip").find("frames").find("frame")


def _placeobjects(frame):
    return [c for c in frame if c.tag == "placeobject"]


def test_added_placeobject_round_trips(served):
    """A hand-built placeobject (as the editor's Add produces) saves, exports, and
    re-decompiles with the same character and placement."""
    base, xml_path, tmp_path = served
    content = json.loads(_fetch(base + "/api/xml"))["content"]
    root = ET.fromstring(content)

    shape_id = next(ch.get("id") for ch in root if ch.tag == "shape")
    frame = _frame0(root)
    before = len(_placeobjects(frame))

    po = ET.SubElement(frame, "placeobject")
    po.set("depth", "990")
    po.set("character", shape_id)
    po.set("rotm00", "1")
    po.set("rotm11", "1")
    po.set("tx", "512.0")
    po.set("ty", "384.0")
    ET.SubElement(po, "poflags").set("value", "HasCharacter|HasMatrix")

    saved = _fetch(base + "/api/xml", payload={"content": ET.tostring(root, encoding="unicode")})
    assert json.loads(saved)["ok"] is True
    exported = json.loads(_fetch(base + "/api/convert", payload={}))
    assert exported["ok"] is True

    # Re-decompile the exported .apt and confirm the new placeobject persisted.
    rexml = apt_to_xml(tmp_path / "SpellStore.apt")
    reroot = ET.parse(rexml).getroot()
    reframe = _frame0(reroot)
    added = [p for p in _placeobjects(reframe) if p.get("depth") == "990"]
    assert len(_placeobjects(reframe)) == before + 1
    assert len(added) == 1
    assert added[0].get("character") == shape_id
    assert float(added[0].get("tx")) == 512.0


def test_deleted_placeobject_round_trips(served):
    """Removing a placeobject saves, exports, and re-decompiles with one fewer."""
    base, xml_path, tmp_path = served
    content = json.loads(_fetch(base + "/api/xml"))["content"]
    root = ET.fromstring(content)
    frame = _frame0(root)
    pos = _placeobjects(frame)
    before = len(pos)
    assert before >= 1
    gone_depth = pos[0].get("depth")
    frame.remove(pos[0])

    _fetch(base + "/api/xml", payload={"content": ET.tostring(root, encoding="unicode")})
    assert json.loads(_fetch(base + "/api/convert", payload={}))["ok"] is True

    reroot = ET.parse(apt_to_xml(tmp_path / "SpellStore.apt")).getroot()
    assert len(_placeobjects(_frame0(reroot))) == before - 1
    # the removed depth is gone (unless another placeobject shared it)
    remaining = [p.get("depth") for p in _placeobjects(_frame0(reroot))]
    assert remaining.count(gone_depth) == [p.get("depth") for p in pos].count(gone_depth) - 1
