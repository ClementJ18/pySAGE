"""Pack the map editor's MCP server into a Claude Desktop extension (`SageWorldBuilder.mcpb`).

An `.mcpb` is a zip with `manifest.json` at its root (the MCPB manifest spec, a `binary` server).
Double-clicking it, or dragging it into Claude Desktop's Settings > Extensions, installs the
server, so a mapper connects Claude to WorldbuilderV2 with no Python. The manifest is written
here rather than kept as a file: its version comes from pyproject.toml and its tool list from
the server itself, so neither can drift.

    python tools/build_mcpb.py dist/sage-worldbuilder-mcp.exe  # dist/SageWorldBuilder.mcpb
    python tools/build_mcpb.py EXE --out build/release-dist/SageWorldBuilder.mcpb

`build_release.py` calls `pack` whenever sage-worldbuilder-mcp.spec was built.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import tomllib
import zipfile
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
ICON = REPO_ROOT / "sage_worldbuilder" / "assets" / "worldbuilder_icons" / "icons" / "128.png"
BUNDLE_NAME = "SageWorldBuilder.mcpb"
SERVER_DIR = "server"
EXE_NAME = "sage-worldbuilder-mcp.exe"

LONG_DESCRIPTION = """\
Lets Claude read and edit the map open in WorldbuilderV2, the Battle for Middle-earth map editor:
list, place, move, rotate and delete objects, edit their properties, read and flatten terrain,
select objects, move the view and take screenshots of it. Every edit shows in the editor at once
and can be undone there like any other.

To connect, open a map in WorldbuilderV2 and turn on Tools > Allow Agent Connections."""


def _project() -> dict[str, Any]:
    with (REPO_ROOT / "pyproject.toml").open("rb") as handle:
        return tomllib.load(handle)["project"]


def _tools() -> list[dict[str, str]]:
    """Each tool's name and the first paragraph of its description, as the server declares them."""
    sys.path.insert(0, str(REPO_ROOT))
    from sage_worldbuilder.mcp_server.server import build_server  # noqa: PLC0415 - needs mcp

    listed = asyncio.run(build_server().list_tools())
    return [
        {
            "name": tool.name,
            "description": " ".join((tool.description or "").split("\n\n")[0].split()),
        }
        for tool in listed
    ]


def manifest() -> dict[str, Any]:
    project = _project()
    author = project["authors"][0]
    urls = project.get("urls", {})
    return {
        "manifest_version": "0.3",
        "name": "sage-worldbuilder",
        "display_name": "SAGE WorldBuilder",
        "version": project["version"],
        "description": "Let Claude read and edit the map open in WorldbuilderV2.",
        "long_description": LONG_DESCRIPTION,
        "author": {"name": author["name"]},
        "homepage": urls.get("Homepage", ""),
        "repository": {"type": "git", "url": urls.get("Repository", "")},
        "support": urls.get("Issues", ""),
        "icon": "icon.png",
        "license": project.get("license", ""),
        "keywords": ["bfme", "sage", "map", "worldbuilder", "modding"],
        "server": {
            "type": "binary",
            "entry_point": f"{SERVER_DIR}/{EXE_NAME}",
            "mcp_config": {
                # Hosts add `.exe` to a binary's command on Windows.
                "command": "${__dirname}/" + f"{SERVER_DIR}/{Path(EXE_NAME).stem}",
                "args": ["--bridge"],
            },
        },
        "tools": _tools(),
        "compatibility": {"platforms": ["win32"]},
    }


def pack(exe: Path, out: Path) -> Path:
    """Write the extension for the frozen server `exe` to `out`."""
    if not exe.is_file():
        raise FileNotFoundError(f"no server binary at {exe}")
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr("manifest.json", json.dumps(manifest(), indent=2) + "\n")
        bundle.write(ICON, "icon.png")
        bundle.write(exe, f"{SERVER_DIR}/{EXE_NAME}")
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("exe", type=Path, help="the frozen sage-worldbuilder-mcp.exe")
    parser.add_argument(
        "--out", type=Path, help=f"the bundle to write (default: {BUNDLE_NAME} beside EXE)"
    )
    args = parser.parse_args()
    out = pack(args.exe, args.out or args.exe.with_name(BUNDLE_NAME))
    print(f"wrote {out} ({out.stat().st_size / 1_048_576:.1f} MiB)")


if __name__ == "__main__":
    main()
