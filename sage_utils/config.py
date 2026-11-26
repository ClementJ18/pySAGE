"""Per-user config storage shared by the SAGE front ends: one `pySAGE` folder under the OS
config root with a subfolder per app, plus best-effort JSON read/write so a missing,
unwritable or corrupt file degrades to a default rather than aborting an app."""

import json
import os
from pathlib import Path

__all__ = [
    "VENDOR",
    "read_json",
    "user_config_dir",
    "user_file",
    "write_json",
]

#: The single folder under the config root that every app's subfolder lives in.
VENDOR = "pySAGE"


def _config_root() -> Path:
    """`%APPDATA%` on Windows, else `~/.config`."""
    base = os.environ.get("APPDATA")  # Windows
    return Path(base) if base else Path.home() / ".config"


def user_config_dir(app: str) -> Path:
    """The per-user config directory for `app`: `<config root>/pySAGE/<app>`.

    Apps used to keep their folder straight under the config root; the first call after the
    move renames such a folder into place. Best effort: a folder another process holds open
    is left where it is, and the app starts from its defaults."""
    root = _config_root()
    path = root / VENDOR / app
    legacy = root / app
    if not path.exists() and legacy.is_dir():
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            legacy.rename(path)
        except OSError:
            pass
    return path


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
