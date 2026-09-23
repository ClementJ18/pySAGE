"""Per-user config storage shared by the SAGE front ends: a per-app directory under the
OS config root, plus best-effort JSON read/write so a missing, unwritable or corrupt file
degrades to a default rather than aborting an app."""

import json
import os
from pathlib import Path

__all__ = [
    "read_json",
    "user_config_dir",
    "user_file",
    "write_json",
]


def user_config_dir(app: str) -> Path:
    """The per-user config directory for `app` (one subfolder per app): under `%APPDATA%`
    on Windows, else `~/.config`."""
    base = os.environ.get("APPDATA")  # Windows
    root = Path(base) if base else Path.home() / ".config"
    return root / app


def user_file(app: str, name: str) -> Path:
    """The path to the per-user file `name` in `app`'s config directory."""
    return user_config_dir(app) / name


def read_json(app: str, name: str, default=None):
    """The parsed JSON in `app`'s `name` file, or `default` when it is missing or unreadable."""
    try:
        return json.loads(user_file(app, name).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def write_json(app: str, name: str, data) -> bool:
    """Write `data` as JSON to `app`'s `name` file, creating the directory. Best effort:
    returns False (rather than raising) when the file could not be written."""
    path = user_file(app, name)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except OSError:
        return False
    return True
