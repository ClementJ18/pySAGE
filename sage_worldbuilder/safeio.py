"""Crash-safe file writes: a save never leaves a half-written map behind."""

from __future__ import annotations

import contextlib
import os
import tempfile
from pathlib import Path

__all__ = ["atomic_write"]


def atomic_write(path: str | Path, data: bytes) -> None:
    """Write `data` to `path` through a synced temporary file in the same folder, then rename it
    over the target. A crash or a failed write leaves the previous file untouched."""
    path = Path(path)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(temp_name)
        raise
