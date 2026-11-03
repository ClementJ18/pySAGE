"""The Claude Desktop extension `tools/build_mcpb.py` packs: the layout a host expects, and a
manifest that follows the project and the server instead of drifting from them."""

import importlib.util
import json
import tomllib
import zipfile
from pathlib import Path

import pytest

pytest.importorskip("mcp", reason="the [worldbuilder-mcp] extra (mcp) is not installed")

from sage_worldbuilder.mcp_server.tools import TOOLS  # noqa: E402

REPO_ROOT = Path(__file__).parents[2]


def load_packer():
    spec = importlib.util.spec_from_file_location(
        "build_mcpb", REPO_ROOT / "tools" / "build_mcpb.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_bundle_holds_the_manifest_icon_and_server(tmp_path):
    packer = load_packer()
    exe = tmp_path / packer.EXE_NAME
    exe.write_bytes(b"MZ stand-in")
    out = packer.pack(exe, tmp_path / "out" / packer.BUNDLE_NAME)
    with zipfile.ZipFile(out) as bundle:
        assert set(bundle.namelist()) == {
            "manifest.json",
            "icon.png",
            "server/sage-worldbuilder-mcp.exe",
        }
        manifest = json.loads(bundle.read("manifest.json"))
        assert bundle.read("server/sage-worldbuilder-mcp.exe") == b"MZ stand-in"
        assert bundle.read("icon.png").startswith(b"\x89PNG")
    server = manifest["server"]
    assert server["type"] == "binary"
    assert server["entry_point"] == "server/sage-worldbuilder-mcp.exe"
    # The host adds `.exe`, and the bundle always drives the running editor.
    assert server["mcp_config"] == {
        "command": "${__dirname}/server/sage-worldbuilder-mcp",
        "args": ["--bridge"],
    }


def test_the_manifest_follows_the_project_and_the_server():
    manifest = load_packer().manifest()
    with (REPO_ROOT / "pyproject.toml").open("rb") as handle:
        assert manifest["version"] == tomllib.load(handle)["project"]["version"]
    assert sorted(tool["name"] for tool in manifest["tools"]) == sorted(TOOLS)
    assert all(tool["description"] for tool in manifest["tools"])
    assert manifest["compatibility"] == {"platforms": ["win32"]}


def test_a_missing_server_binary_is_an_error(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_packer().pack(tmp_path / "nope.exe", tmp_path / "out.mcpb")
