"""Run a game with some `Options.ini` preferences set, then put the player's file back.

The engine reads `Options.ini` from the user-files folder once, at startup, so a preference has to
be in the file before the launch and is fixed for the life of the process. That is what makes
graphics quality a per-launch parameter: `StaticGameLOD = Low | Medium | High | UltraHigh`
selects one of the `StaticGameLOD` buckets in `gamelod.ini` (particle cap, shadows, props,
texture reduction, heat effects).

The file is restored byte for byte on the way out, or removed if there was none, whatever the
block did. The game writes `Options.ini` itself when it exits, so the override has to outlive the
game: put the launch inside the `with`.
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path

from sage_live.launch.runner import user_files_dir

__all__ = ["OPTIONS_INI", "apply_options", "options_override"]

OPTIONS_INI = "Options.ini"


def apply_options(text: str, preferences: Mapping[str, str]) -> str:
    """`text` with each preference set: an existing line is rewritten in place, a missing one is
    added at the end. Keys match case-insensitively, as the engine's map does."""
    remaining = {key.lower(): (key, value) for key, value in preferences.items()}
    lines = text.splitlines()
    for index, line in enumerate(lines):
        match = re.match(r"\s*([^=\s]+)\s*=", line)
        if match and match.group(1).lower() in remaining:
            key, value = remaining.pop(match.group(1).lower())
            lines[index] = f"{key} = {value}"
    lines.extend(f"{key} = {value}" for key, value in remaining.values())
    newline = "\r\n" if "\r\n" in text else "\n"
    return newline.join(lines) + newline


@contextmanager
def options_override(
    preferences: Mapping[str, str], folder: str | Path | None = None
) -> Iterator[Path]:
    """Set `preferences` in `Options.ini` for the block; yields the file's path."""
    path = user_files_dir(folder) / OPTIONS_INI
    original = path.read_bytes() if path.is_file() else None
    text = original.decode("latin-1") if original is not None else ""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(apply_options(text, preferences).encode("latin-1"))
    try:
        yield path
    finally:
        if original is None:
            path.unlink(missing_ok=True)
        else:
            path.write_bytes(original)
