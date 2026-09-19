"""Extract WorldBuilder's keyboard shortcuts from `worldbuilder.exe` into
`sage_worldbuilder/keymap.json`.

Reads the exe's accelerator table (resource 128) and names each command from the main menu
(also resource 128) or, for a toolbar-only tool, from the command's status string, which MFC
stores as `description\\ntooltip`.

    python tools/extract_worldbuilder_keymap.py [path/to/worldbuilder.exe] [--check]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import struct
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pefile

__all__ = ["extract_keymap", "render_keymap"]

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_EXE = REPO_ROOT / "worldbuilder.exe"
KEYMAP = REPO_ROOT / "sage_worldbuilder" / "keymap.json"

RT_MENU, RT_STRING, RT_ACCELERATOR = 4, 6, 9
MAIN_RESOURCE = 128
FVIRTKEY, FSHIFT, FCONTROL, FALT, LAST_ENTRY = 0x01, 0x04, 0x08, 0x10, 0x80
MF_POPUP, MF_END = 0x10, 0x80
# Qt's portable spelling puts modifiers in this order.
_MODIFIERS = ((FCONTROL, "Ctrl"), (FALT, "Alt"), (FSHIFT, "Shift"))

_VIRTUAL_KEYS = {
    0x08: "Backspace",
    0x09: "Tab",
    0x0D: "Return",
    0x1B: "Esc",
    0x20: "Space",
    0x21: "PgUp",
    0x22: "PgDown",
    0x23: "End",
    0x24: "Home",
    0x25: "Left",
    0x26: "Up",
    0x27: "Right",
    0x28: "Down",
    0x2D: "Ins",
    0x2E: "Del",
    0xBA: ";",
    0xBB: "=",
    0xBC: ",",
    0xBD: "-",
    0xBE: ".",
    0xBF: "/",
    0xC0: "`",
    0xDB: "[",
    0xDC: "\\",
    0xDD: "]",
    0xDE: "'",
}
# Commands whose tooltip title is only the key itself.
_LABEL_OVERRIDES = {32918: "Place Object"}


def _resources(pe: pefile.PE, type_id: int) -> Iterator[tuple[int, bytes]]:
    for resource_type in pe.DIRECTORY_ENTRY_RESOURCE.entries:
        if resource_type.id != type_id:
            continue
        for entry in resource_type.directory.entries:
            data = entry.directory.entries[0].data.struct
            yield entry.id, pe.get_data(data.OffsetToData, data.Size)


def _string_table(pe: pefile.PE) -> dict[int, str]:
    """Every string resource by id. Block N holds the 16 strings with ids (N-1)*16 .. N*16-1."""
    strings: dict[int, str] = {}
    for block, data in _resources(pe, RT_STRING):
        pos = 0
        for index in range(16):
            (length,) = struct.unpack_from("<H", data, pos)
            pos += 2
            text = data[pos : pos + 2 * length].decode("utf-16-le")
            pos += 2 * length
            if text:
                strings[(block - 1) * 16 + index] = text
    return strings


def _menu_items(data: bytes) -> list[tuple[int, list[str]]]:
    """`(command, [popup, ..., item])` for each command in a standard (non-extended) menu."""
    version, header_size = struct.unpack_from("<HH", data, 0)
    if version != 0:
        raise ValueError(f"unsupported menu template version {version}")
    items: list[tuple[int, list[str]]] = []

    def read(pos: int, path: list[str]) -> int:
        while True:
            (flags,) = struct.unpack_from("<H", data, pos)
            pos += 2
            command = 0
            if not flags & MF_POPUP:
                (command,) = struct.unpack_from("<H", data, pos)
                pos += 2
            end = pos
            while data[end : end + 2] != b"\0\0":
                end += 2
            text = data[pos:end].decode("utf-16-le")
            pos = end + 2
            if flags & MF_POPUP:
                pos = read(pos, [*path, text])
            elif command:
                items.append((command, [*path, text]))
            if flags & MF_END:
                return pos

    read(4 + header_size, [])
    return items


def _clean(text: str) -> str:
    """A menu caption without its mnemonic markers, shortcut column or trailing ellipsis."""
    caption = text.split("\t")[0].replace("&&", "\0").replace("&", "").replace("\0", "&")
    return caption.removesuffix("...").strip()


def _key_name(flags: int, key: int) -> str:
    if not flags & FVIRTKEY:
        return chr(key)
    if 0x30 <= key <= 0x39 or 0x41 <= key <= 0x5A:
        return chr(key)
    if 0x70 <= key <= 0x87:
        return f"F{key - 0x6F}"
    if key in _VIRTUAL_KEYS:
        return _VIRTUAL_KEYS[key]
    raise ValueError(f"unmapped virtual key {key:#x}")


def extract_keymap(exe: Path) -> dict[str, Any]:
    pe = pefile.PE(str(exe), fast_load=True)
    pe.parse_data_directories(
        directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_RESOURCE"]]
    )
    strings = _string_table(pe)
    menu: dict[int, str] = {}
    for resource, data in _resources(pe, RT_MENU):
        if resource == MAIN_RESOURCE:
            for command, path in _menu_items(data):
                menu.setdefault(command, "/".join(_clean(part) for part in path))
    table = next(data for resource, data in _resources(pe, RT_ACCELERATOR) if resource == 128)

    rows: list[dict[str, Any]] = []
    for offset in range(0, len(table), 8):
        flags, key, command, _padding = struct.unpack_from("<HHHH", table, offset)
        modifiers = [name for bit, name in _MODIFIERS if flags & bit]
        description, _, tooltip = strings.get(command, "").partition("\n")
        if command in _LABEL_OVERRIDES:
            label = _LABEL_OVERRIDES[command]
        elif command in menu:
            label = menu[command].rsplit("/", 1)[-1]
        else:
            # Tooltip titles repeat the shortcut in parentheses: "Mound (Shift+H)".
            label = re.sub(r"\s*\([^()]*\)$", "", tooltip).strip()
        rows.append(
            {
                "keys": "+".join([*modifiers, _key_name(flags, key)]),
                "command": command,
                "label": label or None,
                "menu": menu.get(command),
                "description": description.strip() or None,
            }
        )
        if flags & LAST_ENTRY:
            break
    rows.sort(key=lambda row: (row["command"], row["keys"]))
    return {
        "source": {"file": exe.name, "sha1": hashlib.sha1(exe.read_bytes()).hexdigest()},
        "accelerators": rows,
    }


def render_keymap(keymap: dict[str, Any]) -> str:
    return json.dumps(keymap, indent=2) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("exe", nargs="?", type=Path, default=DEFAULT_EXE)
    parser.add_argument("--out", type=Path, default=KEYMAP)
    parser.add_argument(
        "--check", action="store_true", help="fail if the file on disk is out of date"
    )
    args = parser.parse_args(argv)

    rendered = render_keymap(extract_keymap(args.exe))
    if args.check:
        current = args.out.read_text(encoding="utf-8") if args.out.is_file() else ""
        if current != rendered:
            print(f"{args.out} is out of date", file=sys.stderr)
            return 1
        return 0
    args.out.write_text(rendered, encoding="utf-8")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
