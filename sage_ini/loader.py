"""Whole-game assembly: build one `Game` from a folder of ini files, so cross-file
references resolve. Root files (those nothing `#include`s) are parsed with their includes
expanded, in mod-over-base overlay order; a file that fails to construct becomes a
`load-error` diagnostic rather than aborting the run.

Map files (`maps/.../map.ini`) are excluded - each is a per-map context (`load_map`).
"""

from dataclasses import dataclass
from pathlib import Path

from sage_ini.model.game import Game
from sage_ini.parser.blockparser import parse_file
from sage_ini.parser.diagnostics import Diagnostics
from sage_ini.parser.io import iter_asset_files, iter_map_files
from sage_ini.parser.location import Span
from sage_ini.stats import ini_root, is_map_path, root_files
from sage_ini.strings import load_string_locations, load_strings

__all__ = ["LoadedGame", "load_game", "load_map", "map_files"]


@dataclass(slots=True)
class LoadedGame:
    game: Game
    diagnostics: Diagnostics  # parse + load problems gathered while assembling


def _load_into(game: Game, diagnostics: Diagnostics | None, path: Path, layers) -> None:
    """Parse one root file (includes expanded) and build it into `game`. `diagnostics` None
    builds it silently - how base sources load, since they only resolve the mod's references."""
    result = parse_file(path, resolve_includes=True, include_layers=layers)
    if diagnostics is not None:
        diagnostics.items.extend(result.diagnostics.items)
    try:
        game.load_document(result.document)
    except (ValueError, KeyError, TypeError, IndexError) as exc:
        if diagnostics is not None:
            diagnostics.add("load-error", f"{exc}", Span(str(path), 1, 1))


def load_game(
    root: str | Path,
    overlays: tuple[str | Path, ...] = (),
    bases: tuple[str | Path, ...] = (),
) -> LoadedGame:
    """Assemble every non-map root file under `root` into one `Game`.

    `overlays` are lower-priority ini roots that `#include`s may resolve into (the engine's
    overlay). `bases` are lower-priority game folders built into the game (silently, and
    first, so a mod definition of the same name overrides them) so the mod's references
    resolve; their own problems are not reported.
    """
    root = Path(root)
    bases = tuple(Path(base) for base in bases)
    layers = (
        ini_root(root),
        *(ini_root(base) for base in bases),
        *(ini_root(overlay) for overlay in overlays),
    )
    game = Game()
    diagnostics = Diagnostics()

    for base in bases:
        for path in root_files(base):
            if is_map_path(path, base):
                continue
            _load_into(game, None, path, layers)

    for path in root_files(root):
        if is_map_path(path, root):
            continue
        _load_into(game, diagnostics, path, layers)

    game.strings.update(load_strings(root, (*overlays, *bases)))
    game.string_definitions.update(load_string_locations(root))

    # Index assets and map layouts from every layer so a mod reference to a base-game asset
    # resolves. Membership-only, so layer order and duplicate names are immaterial.
    for source in (root, *overlays, *bases):
        game.assets.update(path.name.lower() for path in iter_asset_files(source))
        game.map_files.extend(iter_map_files(source))

    return LoadedGame(game=game, diagnostics=diagnostics)


def map_files(root: str | Path) -> list[Path]:
    """Every map-scoped root ini under `root` (files beneath a `maps/` directory)."""
    root = Path(root)
    return [path for path in root_files(root) if is_map_path(path, root)]


def load_map(
    map_path: str | Path, root: str | Path, overlays: tuple[str | Path, ...] = ()
) -> LoadedGame:
    """The global game with one `map_path` layered on top, as its own context: the map's
    definitions and overrides are visible only here, never leaking into the global game or
    another map. Its `.str` table layers on the global strings the same way."""
    map_path = Path(map_path)
    root = Path(root)
    layers = (ini_root(root), *(ini_root(overlay) for overlay in overlays))

    loaded = load_game(root, overlays)
    # The map layer patches the global objects it re-opens rather than replacing them (the
    # engine's map override), so flag the build while it loads; see `Game.register`.
    loaded.game._map_override = True
    try:
        _load_into(loaded.game, loaded.diagnostics, map_path, layers)
    finally:
        loaded.game._map_override = False
    loaded.game.strings.update(load_strings(map_path.parent))
    loaded.game.string_definitions.update(load_string_locations(map_path.parent))

    return loaded
