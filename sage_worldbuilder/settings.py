"""The editor's per-user settings, stored as JSON beside the other SAGE apps' settings.

Reading is forgiving: a missing, corrupt or partly wrong file gives defaults for what it cannot
use, so a bad settings file never stops the editor from starting.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path, PureWindowsPath
from typing import Any

from sage_utils.config import read_json, write_json
from sage_worldbuilder.arrays import ArrayOptions
from sage_worldbuilder.autosave import DEFAULT_INTERVAL_SECONDS, AutosaveSettings
from sage_worldbuilder.brush_options import BrushOptions, CopyTerrainOptions, PaintOptions
from sage_worldbuilder.gamedata import GameLayers, base_install
from sage_worldbuilder.jump import JumpMatch, JumpOptions
from sage_worldbuilder.objects import GroupEditMethod
from sage_worldbuilder.pick import ANYTHING, PickCategory
from sage_worldbuilder.viewport import ViewOptions

__all__ = ["APP", "MAX_RECENT", "RecentMap", "Settings", "same_folder"]

APP = "sage_worldbuilder"
SETTINGS_FILE = "settings.json"
MAX_RECENT = 10
RECENT_KINDS = ("file", "game")


@dataclass(frozen=True)
class RecentMap:
    """A recently opened map: a file on disk (`file`), or a game path inside the game's file
    system (`game`, for a map read out of an archive)."""

    kind: str
    path: str

    def label(self) -> str:
        if self.kind == "game":
            return f"{PureWindowsPath(self.path).stem} (game)"
        return self.path

    def same_as(self, other: RecentMap) -> bool:
        return self.kind == other.kind and self.path.lower() == other.path.lower()


@dataclass
class Settings:
    install: str | None = None
    # The loaded mod folders in load order: a later one wins over an earlier one.
    mods: list[str] = field(default_factory=list)
    # The `.sagepatch` of the patched game.dat the data is written for.
    sagepatch: str | None = None
    recent: list[RecentMap] = field(default_factory=list)
    recent_mods: list[str] = field(default_factory=list)
    autosave_enabled: bool = True
    autosave_interval_seconds: int = DEFAULT_INTERVAL_SECONDS
    jump_windowed: bool = True
    jump_script_debug: bool = False
    jump_extra_arguments: str = ""
    jump_match: JumpMatch = field(default_factory=JumpMatch)
    view: ViewOptions = field(default_factory=ViewOptions)
    group_edit_method: GroupEditMethod = GroupEditMethod.AS_GROUP
    pick_allowances: frozenset[PickCategory] = ANYTHING
    brush: BrushOptions = field(default_factory=BrushOptions)
    paint: PaintOptions = field(default_factory=PaintOptions)
    copy_terrain: CopyTerrainOptions = field(default_factory=CopyTerrainOptions)
    array: ArrayOptions = field(default_factory=ArrayOptions)
    # Lock Layout: panels stay where they are and never dock or tab into one another, so a
    # floating panel can be dragged over the others without being swallowed by them.
    lock_layout: bool = False
    # Base64 of Qt's saveGeometry / saveState, so docks come back where they were left.
    window_geometry: str | None = None
    window_state: str | None = None

    @classmethod
    def load(cls) -> Settings:
        return cls.from_dict(read_json(APP, SETTINGS_FILE, {}))

    @classmethod
    def from_dict(cls, data: Any) -> Settings:
        settings = cls()
        if not isinstance(data, dict):
            return settings
        for name in (
            "install",
            "sagepatch",
            "window_geometry",
            "window_state",
            "jump_extra_arguments",
        ):
            value = data.get(name)
            if isinstance(value, str) and value:
                setattr(settings, name, value)
        mods = data.get("mods")
        # A settings file from before several mods could load holds the one as `mod`.
        single = data.get("mod")
        if not isinstance(mods, list):
            mods = [single] if isinstance(single, str) else []
        for folder in mods:
            if isinstance(folder, str) and folder:
                settings.load_mod(folder)
        for name in ("autosave_enabled", "jump_windowed", "jump_script_debug", "lock_layout"):
            if isinstance(data.get(name), bool):
                setattr(settings, name, data[name])
        interval = data.get("autosave_interval_seconds")
        if isinstance(interval, int) and not isinstance(interval, bool):
            settings.autosave_interval_seconds = interval
        settings.jump_match = JumpMatch.from_dict(data.get("jump_match"))
        settings.view = ViewOptions.from_dict(data.get("view"))
        settings.brush = BrushOptions.from_dict(data.get("brush"))
        settings.paint = PaintOptions.from_dict(data.get("paint"))
        settings.copy_terrain = CopyTerrainOptions.from_dict(data.get("copy_terrain"))
        settings.array = ArrayOptions.from_dict(data.get("array"))
        method = data.get("group_edit_method")
        if method in {member.value for member in GroupEditMethod}:
            settings.group_edit_method = GroupEditMethod(method)
        allowances = data.get("pick_allowances")
        if isinstance(allowances, list):
            values = {member.value for member in PickCategory}
            settings.pick_allowances = frozenset(
                PickCategory(name) for name in allowances if name in values
            )
        for row in data.get("recent", []) if isinstance(data.get("recent"), list) else []:
            if (
                isinstance(row, dict)
                and row.get("kind") in RECENT_KINDS
                and isinstance(row.get("path"), str)
            ):
                settings.add_recent(RecentMap(row["kind"], row["path"]), front=False)
        mods = data.get("recent_mods")
        for folder in mods if isinstance(mods, list) else []:
            if isinstance(folder, str) and folder:
                settings.add_recent_mod(folder, front=False)
        return settings

    def to_dict(self) -> dict[str, Any]:
        return {
            "install": self.install,
            "mods": list(self.mods),
            "sagepatch": self.sagepatch,
            "recent": [{"kind": recent.kind, "path": recent.path} for recent in self.recent],
            "recent_mods": list(self.recent_mods),
            "autosave_enabled": self.autosave_enabled,
            "autosave_interval_seconds": self.autosave_interval_seconds,
            "jump_windowed": self.jump_windowed,
            "jump_script_debug": self.jump_script_debug,
            "jump_extra_arguments": self.jump_extra_arguments,
            "jump_match": self.jump_match.to_dict(),
            "view": self.view.to_dict(),
            "brush": self.brush.to_dict(),
            "paint": self.paint.to_dict(),
            "copy_terrain": self.copy_terrain.to_dict(),
            "array": self.array.to_dict(),
            "group_edit_method": self.group_edit_method.value,
            "pick_allowances": [
                category.value for category in PickCategory if category in self.pick_allowances
            ],
            "lock_layout": self.lock_layout,
            "window_geometry": self.window_geometry,
            "window_state": self.window_state,
        }

    def save(self) -> bool:
        return write_json(APP, SETTINGS_FILE, self.to_dict())

    def add_recent(self, recent: RecentMap, *, front: bool = True) -> None:
        """Record `recent` (newest first by default), dropping a duplicate and the overflow."""
        self.recent = [existing for existing in self.recent if not existing.same_as(recent)]
        if front:
            self.recent.insert(0, recent)
        else:
            self.recent.append(recent)
        del self.recent[MAX_RECENT:]

    def remove_recent(self, recent: RecentMap) -> None:
        self.recent = [existing for existing in self.recent if not existing.same_as(recent)]

    def add_recent_mod(self, folder: str, *, front: bool = True) -> None:
        """Record a loaded mod folder (newest first by default), like `add_recent`."""
        self.remove_recent_mod(folder)
        if front:
            self.recent_mods.insert(0, folder)
        else:
            self.recent_mods.append(folder)
        del self.recent_mods[MAX_RECENT:]

    def remove_recent_mod(self, folder: str) -> None:
        self.recent_mods = [
            existing for existing in self.recent_mods if not same_folder(existing, folder)
        ]

    def has_mod(self, folder: str) -> bool:
        return any(same_folder(loaded, folder) for loaded in self.mods)

    def load_mod(self, folder: str) -> None:
        """Load `folder` last, above every mod already loaded; one already loaded moves there."""
        self.unload_mod(folder)
        self.mods.append(folder)

    def unload_mod(self, folder: str) -> None:
        self.mods = [loaded for loaded in self.mods if not same_folder(loaded, folder)]

    def layers(self) -> GameLayers | None:
        """The configured install, mod folders and `.sagepatch`, or the detected install when no
        install is set."""
        sagepatch = Path(self.sagepatch) if self.sagepatch else None
        if self.install is None:
            detected = GameLayers.detect()
            return replace(detected, sagepatch=sagepatch) if detected is not None else None
        return GameLayers(
            Path(self.install),
            tuple(Path(folder) for folder in self.mods),
            base=base_install("rotwk"),
            sagepatch=sagepatch,
        )

    def autosave_settings(self) -> AutosaveSettings:
        return AutosaveSettings(self.autosave_enabled, self.autosave_interval_seconds)

    def jump_options(self, game_info: str | None = None) -> JumpOptions:
        """The launch options, with `game_info` the match (`JumpMatch.game_info`) when one is
        chosen."""
        return JumpOptions(
            self.jump_windowed,
            self.jump_script_debug,
            self.jump_extra_arguments,
            game_info=game_info,
        )


def same_folder(first: str, second: str) -> bool:
    """Whether two spellings name the same Windows folder (case, separators, a trailing slash)."""
    return _folder_key(first) == _folder_key(second)


def _folder_key(folder: str) -> str:
    return str(PureWindowsPath(folder)).rstrip("\\").lower()
