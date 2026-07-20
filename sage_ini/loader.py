"""Whole-game assembly: build one `Game` from a folder of ini files, so cross-file
references resolve. Root files (those nothing `#include`s) are parsed with their includes
expanded, in mod-over-base overlay order; a file that fails to construct becomes a
`load-error` diagnostic rather than aborting the run.

Map files (`maps/.../map.ini`) are excluded - each is a per-map context (`load_map`).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from sage_ini.model.game import Game
from sage_ini.parser.blockparser import parse_file
from sage_ini.parser.diagnostics import Diagnostics
from sage_ini.parser.io import iter_asset_files, iter_map_files
from sage_ini.parser.location import Span
from sage_ini.stats import as_root_list, ini_root, is_map_path, root_files
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


def _rel_key(path: Path, base_dir: Path) -> str:
    """A root file's engine identity for shadowing: its `ini_root`-relative path, lowercased and
    forward-slashed, so the same file in two layers (whatever each layer's on-disk layout) collides.
    A file outside the ini root falls back to its bare name."""
    try:
        rel = path.resolve().relative_to(base_dir.resolve())
    except ValueError:
        return path.name.lower()
    return rel.as_posix().lower()


def load_game(
    root: str | Path | Sequence[str | Path],
    overlays: tuple[str | Path, ...] = (),
    bases: tuple[str | Path, ...] = (),
    game: Game | None = None,
) -> LoadedGame:
    """Assemble every non-map root file under `root` into one `Game`.

    `root` is a single game root or an ascending-priority sequence of them (a later root shadows
    an earlier one): every root is reported. `overlays` are lower-priority ini roots that
    `#include`s may resolve into (the engine's overlay). `bases` are lower-priority game folders
    built into the game (silently, and first, so a mod definition of the same name overrides them)
    so the mod's references resolve; their own problems are not reported.

    `game`, when given, is a pre-seeded `Game` to build into rather than a fresh one - the same
    below-every-root layering as `bases`, but for symbols materialized from a manifest: the mod's
    files build on top, so a same-name definition overrides the stand-in exactly as it would a
    real base file.

    A root file present at the same `ini_root`-relative path in more than one layer is built once,
    from the highest-priority layer ("keep the latest of a file" - the engine's file shadowing).
    """
    roots = as_root_list(root)  # reported, ascending priority (the last one wins)
    base_paths = [Path(base) for base in bases]  # silent, below every root
    overlay_paths = [Path(overlay) for overlay in overlays]

    # The full layer stack, lowest priority first: silent bases, then the reported game roots.
    stack: list[tuple[Path, bool]] = [(b, False) for b in base_paths] + [(r, True) for r in roots]

    # Include resolution sees every layer, highest priority first, then the include-only overlays.
    layers = tuple(ini_root(src) for src, _ in reversed(stack)) + tuple(
        ini_root(overlay) for overlay in overlay_paths
    )
    game = game if game is not None else Game()
    diagnostics = Diagnostics()

    # File-level shadowing: record the highest-priority layer that supplies each relative path,
    # then build each layer's winners in low->high order so a same-*named* definition in a higher
    # layer still overrides a lower one (name override survives across differently-named files too).
    winner: dict[str, int] = {}
    per_layer: list[list[tuple[str, Path, bool]]] = []
    for index, (src, reported) in enumerate(stack):
        base_dir = ini_root(src)
        entries: list[tuple[str, Path, bool]] = []
        for path in root_files(src):
            if is_map_path(path, src):
                continue
            key = _rel_key(path, base_dir)
            entries.append((key, path, reported))
            winner[key] = index  # a later (higher-priority) layer overwrites the winner
        per_layer.append(entries)

    for index, entries in enumerate(per_layer):
        for key, path, reported in entries:
            if winner[key] == index:
                _load_into(game, diagnostics if reported else None, path, layers)

    # Strings: highest-priority root first (first definition wins), then overlays and bases.
    string_layers = [*reversed(roots), *overlays, *bases]
    game.strings.update(load_strings(string_layers[0], tuple(string_layers[1:])))
    locations: dict[str, Span] = {}
    for reported_root in reversed(roots):  # high -> low; only the editable user folders
        for label, span in load_string_locations(reported_root).items():
            locations.setdefault(label, span)
    game.string_definitions.update(locations)

    # Index assets and map layouts from every layer so a mod reference to a base-game asset
    # resolves. Membership-only, so layer order and duplicate names are immaterial.
    for source in (*roots, *overlays, *bases):
        game.assets.update(path.name.lower() for path in iter_asset_files(source))
        game.map_files.extend(iter_map_files(source))

    return LoadedGame(game=game, diagnostics=diagnostics)


def map_files(root: str | Path) -> list[Path]:
    """Every map-scoped root ini under `root` (files beneath a `maps/` directory)."""
    root = Path(root)
    return [path for path in root_files(root) if is_map_path(path, root)]


def load_map(
    map_path: str | Path,
    root: str | Path | Sequence[str | Path],
    overlays: tuple[str | Path, ...] = (),
    bases: tuple[str | Path, ...] = (),
) -> LoadedGame:
    """The global game with one `map_path` layered on top, as its own context: the map's
    definitions and overrides are visible only here, never leaking into the global game or
    another map. Its `.str` table layers on the global strings the same way. `root`,
    `overlays` and `bases` are `load_game`'s."""
    map_path = Path(map_path)
    roots = as_root_list(root)
    layers = (
        *(ini_root(r) for r in reversed(roots)),
        *(ini_root(Path(overlay)) for overlay in overlays),
        *(ini_root(Path(base)) for base in bases),
    )

    loaded = load_game(root, overlays, bases)
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
