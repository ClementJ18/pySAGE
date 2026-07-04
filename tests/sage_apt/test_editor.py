"""Smoke test for the browser editor: start `serve()` on a background thread and
drive the three endpoints the UI depends on. Also proves the editor page loads
from the packaged `assets/editor.html` (a broken extraction would fail `/`)."""

import json
import shutil
import socket
import threading
import time
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
