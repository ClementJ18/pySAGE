"""Resolve the installed games' folders from the Windows registry, falling back to a
folder picker when the read fails (game not installed, or a non-standard layout)."""

import os
import winreg
from pathlib import Path

from PyQt6.QtWidgets import QFileDialog, QMessageBox

# Registry keys holding each game's install path (under the 32-bit WOW6432Node).
BFME2_REGISTRY_KEY = (
    r"SOFTWARE\WOW6432Node\Electronic Arts\Electronic Arts\The Battle for Middle-earth II"
)
ROTWK_REGISTRY_KEY = (
    r"SOFTWARE\WOW6432Node\Electronic Arts\Electronic Arts"
    r"\The Lord of the Rings, The Rise of the Witch-king"
)


def _read_game_path_from_registry(registry_key: str, game_name: str) -> str:
    """A game's InstallPath from the registry, falling back to a folder picker. Returns
    "" when the read fails and the user cancels the picker."""
    try:
        with winreg.ConnectRegistry(None, winreg.HKEY_LOCAL_MACHINE) as hkey:
            with winreg.OpenKey(hkey, registry_key, 0, winreg.KEY_READ) as sub_key:
                return winreg.QueryValueEx(sub_key, "InstallPath")[0]
    except OSError as e:
        QMessageBox.information(
            None,
            "Info",
            f"Path could not be read automatically.\nSelect your {game_name} folder!\n\n{e}",
        )
        selected_path = QFileDialog.getExistingDirectory(None, f"Select your {game_name} folder")
        return os.path.join(selected_path, "") if selected_path else ""


def _registry_install_path(registry_key: str) -> str | None:
    """A game's InstallPath read straight from the registry, or None when it isn't there - a
    silent probe with no folder-picker fallback, for deciding whether to show onboarding."""
    try:
        with winreg.ConnectRegistry(None, winreg.HKEY_LOCAL_MACHINE) as hkey:
            with winreg.OpenKey(hkey, registry_key, 0, winreg.KEY_READ) as sub_key:
                path = winreg.QueryValueEx(sub_key, "InstallPath")[0]
    except OSError:
        return None
    return path or None


def detect_installed_games() -> dict[str, str]:
    """The installed BfMe games found in the registry as `label -> install path`, without
    prompting. Empty when neither is installed, which the onboarding state uses to switch from
    "Load Edain" to guidance for adding game files by hand."""
    found: dict[str, str] = {}
    for label, key in (("BfMe II", BFME2_REGISTRY_KEY), ("RotWK", ROTWK_REGISTRY_KEY)):
        path = _registry_install_path(key)
        if path:
            found[label] = path
    return found


def vanilla_archives(root: Path) -> tuple[list[Path], list[Path]]:
    """The `(data archives, texture archives)` present under one game install: `ini.big`
    plus whatever `lang/*.big` archives exist (an installer ships only the installed
    language, so globbing adds exactly the right string tables), and the `textures*.big`
    the portraits / button icons are cropped from. Everything is probed - a missing
    archive is simply not offered - so the one-click vanilla load never errors."""
    data = [path for path in (root / "ini.big",) if path.is_file()]
    lang = root / "lang"
    if lang.is_dir():
        data += sorted(lang.glob("*.big"))
    textures = sorted(root.glob("textures*.big"))
    return data, textures


def registry_read_paths_rotwk() -> str:
    """Read the BfMe II RotWK install path from the registry."""
    return _read_game_path_from_registry(ROTWK_REGISTRY_KEY, "BfMe 2 RotWk")


def registry_read_paths_bfme2() -> str:
    """Read the BfMe II install path from the registry."""
    return _read_game_path_from_registry(BFME2_REGISTRY_KEY, "BfMe 2")
