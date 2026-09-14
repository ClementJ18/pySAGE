"""WorldBuilder's own keyboard shortcuts, so muscle memory carries over.

`keymap.json` is extracted from `worldbuilder.exe`'s accelerator table by
`tools/extract_worldbuilder_keymap.py`. Commands are keyed by WorldBuilder's command id; the
editor binds a shortcut once it implements that command.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import cache
from importlib.resources import files

__all__ = ["Accelerator", "accelerators", "shortcuts_for"]


@dataclass(frozen=True)
class Accelerator:
    """One row of the table: `keys` in Qt's portable spelling (`Ctrl+Shift+Z`)."""

    keys: str
    command: int
    label: str | None
    menu: str | None
    description: str | None


@cache
def accelerators() -> tuple[Accelerator, ...]:
    text = files("sage_worldbuilder").joinpath("keymap.json").read_text(encoding="utf-8")
    return tuple(Accelerator(**row) for row in json.loads(text)["accelerators"])


def shortcuts_for(command: int) -> list[str]:
    """Every key sequence WorldBuilder binds to `command`, in table order."""
    return [row.keys for row in accelerators() if row.command == command]
