"""The Open Map dialog's categories and the maps each one lists.

WorldBuilder's Open and Save As dialogs share six categories, each a game folder holding one
`<name>\\<name>.map` per map. All but User Maps resolve through the game's virtual file system,
so maps shipped inside `.big` archives are listed too (and open read-only). User Maps come from
the game's user-data folder.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from sage_utils.vfs import VfsEntry, VirtualFileSystem

__all__ = ["MapCategory", "MapEntry", "category_filesystem", "list_maps"]


class MapCategory(Enum):
    SYSTEM = "System Maps"
    USER = "User Maps"
    BASES = "Bases"
    LIBRARIES = "Libraries"
    LIVING_WORLD_SCRIPTS = "Living World Scripts"
    LIVING_WORLD_LIBRARIES = "Living World Libraries"

    @property
    def label(self) -> str:
        return self.value

    @property
    def folder(self) -> str:
        return _FOLDERS[self]

    @property
    def suffixes(self) -> tuple[str, ...]:
        # The stock bases ship as `.bse`, a map layout under another extension.
        return (".map", ".bse") if self is MapCategory.BASES else (".map",)


_FOLDERS = {
    MapCategory.SYSTEM: "Maps",
    MapCategory.USER: "Maps",
    MapCategory.BASES: "Bases",
    MapCategory.LIBRARIES: "Libraries",
    MapCategory.LIVING_WORLD_SCRIPTS: "LivingWorldScripts",
    MapCategory.LIVING_WORLD_LIBRARIES: "LivingWorldLibraries",
}


@dataclass(frozen=True)
class MapEntry:
    name: str
    category: MapCategory
    entry: VfsEntry

    @property
    def read_only(self) -> bool:
        return self.entry.in_archive


def category_filesystem(
    category: MapCategory, game: VirtualFileSystem, user_data: Path | None
) -> VirtualFileSystem | None:
    """The file system `category` lists from; `None` for User Maps with no user-data folder."""
    if category is MapCategory.USER:
        return VirtualFileSystem([user_data], archives=False) if user_data is not None else None
    return game


def list_maps(
    category: MapCategory, game: VirtualFileSystem, user_data: Path | None = None
) -> list[MapEntry]:
    """Every map in `category`, sorted by name."""
    filesystem = category_filesystem(category, game, user_data)
    if filesystem is None:
        return []
    maps: list[MapEntry] = []
    for entry in filesystem.listdir(category.folder):
        parts = entry.path.replace("/", "\\").split("\\")
        if len(parts) != 3:
            continue
        stem, _, extension = parts[2].rpartition(".")
        if stem.lower() == parts[1].lower() and f".{extension.lower()}" in category.suffixes:
            maps.append(MapEntry(parts[1], category, entry))
    return sorted(maps, key=lambda found: found.name.casefold())
