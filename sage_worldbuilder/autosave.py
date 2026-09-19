"""Periodic autosave to a rotating set of three files, never over the open map.

The behaviour follows WorldBuilder's: `WorldBuilderAutoSave1.map` is the newest and `3` the
oldest, the files live in the game's user-data folder, the interval defaults to 120 seconds and
is never shorter than 60, and a map is only autosaved when it has unsaved changes.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from sage_worldbuilder.safeio import atomic_write

if TYPE_CHECKING:
    from sage_worldbuilder.document import MapDocument

__all__ = [
    "AUTOSAVE_SLOTS",
    "AutosaveSettings",
    "Autosaver",
    "autosave_paths",
    "rotate_autosaves",
]

AUTOSAVE_SLOTS = 3
AUTOSAVE_NAME = "WorldBuilderAutoSave{}.map"
MIN_INTERVAL_SECONDS = 60
DEFAULT_INTERVAL_SECONDS = 120


@dataclass
class AutosaveSettings:
    enabled: bool = True
    interval_seconds: int = DEFAULT_INTERVAL_SECONDS

    def __post_init__(self) -> None:
        self.interval_seconds = max(self.interval_seconds, MIN_INTERVAL_SECONDS)


def autosave_paths(folder: Path) -> list[Path]:
    """The slot files, newest first."""
    return [folder / AUTOSAVE_NAME.format(slot) for slot in range(1, AUTOSAVE_SLOTS + 1)]


def rotate_autosaves(folder: Path) -> Path:
    """Shift every slot one older (the oldest is dropped) and return the freed newest slot."""
    paths = autosave_paths(folder)
    for newer, older in zip(reversed(paths[:-1]), reversed(paths[1:]), strict=True):
        if newer.is_file():
            os.replace(newer, older)
    return paths[0]


class Autosaver:
    """Decides when a document is due and writes it. The UI owns the timer."""

    def __init__(self, folder: Path, settings: AutosaveSettings | None = None) -> None:
        self.folder = folder
        self.settings = settings or AutosaveSettings()
        self._saved: tuple[int, int] | None = None  # (id(document), revision) last autosaved

    def due(self, document: MapDocument) -> bool:
        return (
            self.settings.enabled
            and document.dirty
            and self._saved != (id(document), document.revision)
        )

    def save(self, document: MapDocument) -> Path | None:
        """Autosave `document` if it is due. Returns the file written, or `None`."""
        if not self.due(document):
            return None
        # Uncompressed: the game and WorldBuilder read it all the same, and it serializes in a
        # fraction of the time, which matters for a save that interrupts editing. Done before
        # rotating, so a failure loses no slot.
        data = document.to_bytes(compress=False)
        self.folder.mkdir(parents=True, exist_ok=True)
        target = rotate_autosaves(self.folder)
        atomic_write(target, data)
        self._saved = (id(document), document.revision)
        return target
