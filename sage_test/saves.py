"""Saving a running match from a test, and finding the file the engine wrote.

`save_game` drives the engine's own `GameState::saveGame` through the live-bridge call command
(`BridgeBackend.save_game`), so the file is exactly what the save menu would write. It needs a
writable session on a `game.dat` carrying live-bridge **with `--cheats`**, the build with the call
command. The engine names the file itself (`Saved Game N` and the extension of the game's type,
`.BfME2Skirmish` for a `-file` match), so the new file is found by comparing the save folder
before and after.

Loading a save back is a menu action - the engine has no command-line or message route to it -
so it is the caller's to drive; the mod decides where the menu's buttons are.
"""

from __future__ import annotations

import os
from pathlib import Path

from sage_live.api.session import Session
from sage_live.backends.bridge import BridgeBackend
from sage_test.run import EngineUnavailable

__all__ = ["SAVE_FOLDER", "save_game"]

#: Where RotWK keeps saves: the user's `My Rise of the Witch-king Files\Save`.
SAVE_FOLDER = Path(os.path.expandvars(r"%APPDATA%\My Rise of the Witch-king Files\Save"))


def save_game(session: Session, folder: Path = SAVE_FOLDER, timeout: float = 120.0) -> Path:
    """Save the match `session` is attached to as a new save, and return the file.

    Raises `EngineUnavailable` when the session cannot call engine code (no writable bridge, or
    one without the call command) or the save did not appear. The call runs at the start of a
    logic frame and blocks until the save is written, so a game whose logic is paused - a
    single-player game in a window that lost focus - never serves it.
    """
    backend = session.backend
    if not isinstance(backend, BridgeBackend) or not backend.can_call:
        raise EngineUnavailable(
            "saving needs a writable session on a game.dat whose live-bridge has the call "
            "command (`sage-patch apply live-bridge --cheats`)"
        )
    before = {path.name for path in folder.iterdir()} if folder.is_dir() else set()
    if not backend.save_game(timeout=timeout):
        problems = "; ".join(d.message for d in backend.diagnostics[-3:])
        raise EngineUnavailable(f"the save call was not served: {problems}")
    new = sorted(
        (path for path in folder.iterdir() if path.name not in before and path.is_file()),
        key=lambda path: path.stat().st_mtime,
    )
    if not new:
        raise EngineUnavailable(f"the engine reported a save, but nothing new is in {folder}")
    return new[-1]
