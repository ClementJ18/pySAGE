"""The game behind the editor: which install and mod folders to read, and the data loaded from them.

`GameLayers` names the folders. `GameContext.open` builds their virtual file system, which is
quick and is all the Open and Save dialogs need. `GameContext.load` extracts the game's ini tree
from that file system and assembles it into a `sage_ini` `Game`; it takes tens of seconds on a
full install, so callers run it off the UI thread.

An expansion reads art from the game it expands as well (Rise of the Witch-king's terrain
textures are in Battle for Middle-earth II's `terrain.big`), so texture lookups use a second
file system with that base install beneath.

A `.sagepatch` names the patched `game.dat` the data is written for. `GameContext.apply_engine`
teaches the `sage_ini` model the INI surface it adds - fields, block types, name-table tokens -
before the data loads, so a patched field reads as the field it is.
"""

from __future__ import annotations

import hashlib
import io
import struct
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from sage_ini.engine import STOCK, Engine, load_engine
from sage_ini.loader import load_game
from sage_ini.model.game import Game
from sage_map.map import Map, parse_map
from sage_utils.installs import find_install, user_data_dir
from sage_utils.vfs import VirtualFileSystem, mount_order
from sage_worldbuilder.categories import MapCategory, MapEntry, list_maps
from sage_worldbuilder.document import MapDocument

__all__ = [
    "GameContext",
    "GameLayers",
    "base_install",
    "is_mod_folder",
    "keep_game_data",
    "resolve_mod_folder",
]

Progress = Callable[[str], None]

# What reading a map that is not one raises: the chunk parsers are not defensive.
_MAP_ERRORS = (OSError, ValueError, KeyError, IndexError, struct.error)

# An expansion -> the game whose install it reads art from.
_BASE_GAMES = {"rotwk": "bfme2"}


def base_install(game: str) -> Path | None:
    """The installed game `game` expands, or None when it expands none or that is not found."""
    base = _BASE_GAMES.get(game)
    install = find_install(base) if base is not None else None
    return install.path if install is not None else None


def resolve_mod_folder(value: str | Path, user_data: Path | None) -> Path:
    """The folder `-mod <value>` names. The game takes an absolute path as given and looks a
    relative one up in the user-data folder's `Mods`; when that has no such folder, the path is
    taken from the working directory instead, as a command line would."""
    path = Path(value)
    if not path.is_absolute() and user_data is not None:
        under_user = user_data / "Mods" / path
        if under_user.is_dir():
            return under_user
    return path.resolve()


def is_mod_folder(folder: Path) -> bool:
    """Whether `folder` holds what the game mounts from a mod: `data` or `.big` archives."""
    if not folder.is_dir():
        return False
    if any(child.is_dir() and child.name.lower() == "data" for child in folder.iterdir()):
        return True
    return bool(mount_order(folder))


# Game folder -> the category that lists it. `Maps` means System Maps here: User Maps are a
# separate file system, never found through the game's.
_CATEGORY_BY_FOLDER = {
    category.folder.lower(): category
    for category in MapCategory
    if category is not MapCategory.USER
}


def keep_game_data(key: str) -> bool:
    """Whether a game path belongs in the tree the ini loader reads: the `data\\ini` sources and
    the global `.str` string tables. A map's own `map.ini` is left to that map's context."""
    if key.startswith("data\\ini\\") and key.endswith((".ini", ".inc")):
        return True
    return key.startswith("data\\") and key.endswith(".str") and "\\maps\\" not in key


@dataclass(frozen=True)
class GameLayers:
    """An install folder, the mod folders mounted above it and the install of the game it expands
    beneath it (read for art only).

    `mods` is in load order, as the game's repeated `-mod` takes them: a later mod wins over an
    earlier one, and every mod wins over the install. `sagepatch` describes the patched binary the
    data is written for, or is `None` for the stock one."""

    install: Path
    mods: tuple[Path, ...] = ()
    game: str = "rotwk"
    base: Path | None = None
    sagepatch: Path | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "mods", tuple(self.mods))

    @property
    def top_mod(self) -> Path | None:
        """The last mod loaded: the one that wins over the others."""
        return self.mods[-1] if self.mods else None

    @classmethod
    def detect(cls, game: str = "rotwk") -> GameLayers | None:
        """The installed `game`, with no mod, or `None` when it cannot be found."""
        install = find_install(game)
        if install is None:
            return None
        return cls(install.path, game=game, base=base_install(game))

    def filesystem(self) -> VirtualFileSystem:
        return VirtualFileSystem([*reversed(self.mods), self.install])

    def art_filesystem(self) -> VirtualFileSystem:
        """The file system textures are looked up in: the mods, the install, then the base."""
        layers = [*reversed(self.mods), self.install]
        if self.base is not None:
            layers.append(self.base)
        return VirtualFileSystem(layers)

    def cache_dir(self) -> Path:
        """Where this combination's extracted ini tree is cached, one folder per combination (the
        same mods in another order are another combination)."""
        identity = "\n".join(str(folder.resolve()).lower() for folder in (self.install, *self.mods))
        digest = hashlib.sha1(identity.encode("utf-8")).hexdigest()[:12]
        return Path(tempfile.gettempdir()) / "sage_worldbuilder" / f"{self.install.name}-{digest}"


@dataclass
class GameContext:
    layers: GameLayers
    filesystem: VirtualFileSystem
    user_data: Path | None
    game: Game | None = None
    # The layers' `.sagepatch`, read when they are mounted; `STOCK` without one.
    engine: Engine = STOCK
    _art: VirtualFileSystem | None = field(default=None, repr=False)

    @classmethod
    def open(
        cls, layers: GameLayers, user_data: Path | None = None, *, detect_user_data: bool = True
    ) -> GameContext:
        """Mount `layers` and read their `.sagepatch`. The user-data folder defaults to the one
        the game's installer registered, unless `detect_user_data` is off."""
        if not layers.install.is_dir():
            raise FileNotFoundError(f"no game install at {layers.install}")
        if user_data is None and detect_user_data:
            user_data = user_data_dir(layers.game)
        return cls(layers, layers.filesystem(), user_data, engine=_read_engine(layers.sagepatch))

    def apply_engine(self) -> list[str]:
        """Make the `sage_ini` model describe this context's engine, replacing whichever was
        active, and return what went wrong reading or applying it (empty when nothing did).

        The model is process state, read by everything that looks at a loaded game, so this runs
        on the thread that owns the game - before `load`, which does not apply it."""
        return [*self.engine.warnings, *self.engine.apply()]

    def art_filesystem(self) -> VirtualFileSystem:
        """Where textures are found: the game's own file system, with the base install beneath
        when there is one. Mounted on first use, since the base adds a hundred archives."""
        if self._art is None:
            base = self.layers.base
            if base is not None and base.is_dir():
                self._art = self.layers.art_filesystem()
            else:
                self._art = self.filesystem
        return self._art

    def load(self, progress: Progress | None = None, cache: Path | None = None) -> Game:
        """Extract and assemble the game data, typed against the engine `apply_engine` applied.
        Returns the `Game` without storing it, so a load running on a worker never swaps data
        under the UI; the caller assigns `game`."""
        report = progress if progress is not None else _ignore
        report("Extracting game data…")
        root = self.filesystem.extract(
            cache if cache is not None else self.layers.cache_dir(), ("data",), keep_game_data
        )
        report("Loading game data…")
        return load_game(root).game

    def maps(self, category: MapCategory) -> list[MapEntry]:
        return list_maps(category, self.filesystem, self.user_data)

    def find_map(self, game_path: str) -> MapEntry | None:
        """The map at a game path such as `maps\\foo\\foo.map`, if the game still has it."""
        entry = self.filesystem.find(game_path)
        if entry is None:
            return None
        parts = entry.path.split("\\")
        category = _CATEGORY_BY_FOLDER.get(parts[0].lower())
        if category is None or len(parts) != 3:
            return None
        return MapEntry(parts[1], category, entry)

    def open_map(self, entry: MapEntry) -> MapDocument:
        """Open a listed map: a loose file keeps its path, an archive member opens read-only."""
        if entry.entry.file is not None:
            return MapDocument.open(entry.entry.file)
        data = self.filesystem.read_bytes(entry.entry)
        return MapDocument.from_bytes(data, read_only=True, name=entry.name)

    def read_map(self, game_path: str) -> Map | None:
        """The map at a game path, parsed and not opened for editing - what reading a library map
        needs. `None` when the game has no such map, or when its bytes do not parse."""
        entry = self.find_map(game_path)
        if entry is None:
            return None
        try:
            return parse_map(io.BytesIO(self.filesystem.read_bytes(entry.entry)))
        except _MAP_ERRORS:
            return None

    def save_root(self, category: MapCategory) -> Path | None:
        """The folder a category saves into: User Maps into the user-data folder, the others into
        the last mod loaded, whose files win. The install's own categories live in archives and
        cannot be written."""
        if category is MapCategory.USER:
            return self.user_data
        return self.layers.top_mod

    def save_path(self, category: MapCategory, name: str) -> Path | None:
        """Where `name` is saved in `category` (`<folder>\\<name>\\<name>.map`), or `None`."""
        root = self.save_root(category)
        if root is None:
            return None
        return root / category.folder / name / f"{name}.map"


def _read_engine(path: Path | None) -> Engine:
    """The engine a `.sagepatch` describes. A file that was chosen and is gone is worth saying,
    unlike `load_engine`'s silent stock engine for a project that simply has none."""
    if path is None:
        return STOCK
    if not path.is_file():
        return Engine(warnings=(f"no .sagepatch at {path} (reading the stock engine's INI)",))
    return load_engine(path)


def _ignore(_text: str) -> None:
    return None
