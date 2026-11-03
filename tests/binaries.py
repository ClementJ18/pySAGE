"""Where the real RotWK binaries are on this machine, for the checks that read them.

None of them is committed, so every check that reads one skips when its file is absent. Each path
can be given by hand: `PYSAGE_ROTWK_GAME_DAT` (an unpatched 2.01.2614 `game.dat`),
`PYSAGE_ROTWK_INSTALL` (the install folder) and `PYSAGE_WORLDBUILDER_EXE` (the shipped
`worldbuilder.exe`). Otherwise the stock `game.dat` is the one at the repo root, the install is
the one the registry names, and WorldBuilder is the repo root's copy or else the install's.
"""

import os
import sys
from pathlib import Path

__all__ = ["REPO_ROOT", "ROTWK_INSTALL", "STOCK_GAME_DAT", "STOCK_GAME_DAT_SHA256", "WORLDBUILDER"]

REPO_ROOT = Path(__file__).resolve().parent.parent

#: The unpatched RotWK 2.01.2614 `game.dat` (11,346,944 bytes) every address in `sage_patch` is
#: read from.
STOCK_GAME_DAT_SHA256 = "5481de75b63e22483660ea8097478faef594f90b9ade7de893e092256ba68a26"

_ROTWK_REGISTRY_KEY = (
    r"SOFTWARE\WOW6432Node\Electronic Arts\Electronic Arts"
    r"\The Lord of the Rings, The Rise of the Witch-king"
)
_DEFAULT_INSTALL = Path(r"C:\Program Files (x86)\Games\bfme\rotwk")


def _registry_install() -> Path | None:
    if sys.platform != "win32":
        return None
    import winreg  # noqa: PLC0415 - Windows-only stdlib module, imported behind the guard

    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _ROTWK_REGISTRY_KEY) as key:
            path = winreg.QueryValueEx(key, "InstallPath")[0]
    except OSError:
        return None
    return Path(path) if path else None


def _given(variable: str) -> Path | None:
    value = os.environ.get(variable)
    return Path(value) if value else None


STOCK_GAME_DAT = _given("PYSAGE_ROTWK_GAME_DAT") or REPO_ROOT / "game.dat"
ROTWK_INSTALL = _given("PYSAGE_ROTWK_INSTALL") or _registry_install() or _DEFAULT_INSTALL
WORLDBUILDER = _given("PYSAGE_WORLDBUILDER_EXE") or next(
    (
        path
        for path in (REPO_ROOT / "worldbuilder.exe", ROTWK_INSTALL / "worldbuilder.exe")
        if path.is_file()
    ),
    REPO_ROOT / "worldbuilder.exe",
)
