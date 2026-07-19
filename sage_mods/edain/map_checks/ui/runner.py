"""Run the Edain map checks in-process for the desktop UI: crawl the chosen folders and files
for `.map` layouts, load the optional game data once, and lint every map with the same checks
`sage-edain lint-maps` runs - the game-resolved dangling-reference checks plus the Edain
mapping conventions (the MAP-xxx codes). Game data is the ordered (kind, path) source list
the other SAGE front ends use (sage_utils.sources: ini folders and .big archives, loaded top
to bottom, later overriding earlier), so the panel, persistence and loading are shared with
sage_ui / sage_wiki. Kept Qt-free so it can run on a worker thread (or headless).
"""

from collections.abc import Callable, Iterable
from pathlib import Path

from sage_ini.model.game import Game
from sage_ini.parser.diagnostics import Diagnostics
from sage_ini.parser.location import Span
from sage_lint.commands.common import diagnostic_dict, select_and_summarize
from sage_lint.config import Config
from sage_map import MapModel
from sage_map import lint_map as lint_map_references
from sage_mods.edain.map_checks import LintConfig
from sage_mods.edain.map_checks import lint_map as lint_map_conventions
from sage_utils.sources import load_sources

# The lowest severities offered in the UI, matching the CLI's --level choices.
LEVELS = ("ERROR", "WARNING", "INFO")

# One game-data source: ("folder" | "big", path) - the shape SourcesPanel holds and
# sage_utils.sources loads.
Source = tuple[str, str]


def source_kind(path: str | Path) -> str:
    """The source kind for a game-data path: a `.big` archive or a folder (mirrors how the
    lint CLI classifies a `--base`)."""
    return "big" if str(path).lower().endswith(".big") else "folder"


def config_game_sources(config: Config, folder: str | Path) -> list[Source]:
    """The `.sagelint` game data for map checking, as ordered (kind, path) sources: the
    always-on `base` list plus `maps_base` (the extras only the map pass needs), each resolved
    against the config's `folder` - the same resolution the lint CLI applies."""
    base = Path(folder)
    sources: list[Source] = []
    for value in [*config.base, *config.maps_base]:
        path = Path(value)
        resolved = path if path.is_absolute() else base / path
        sources.append((source_kind(resolved), str(resolved)))
    return sources


def crawl_maps(targets: Iterable[str | Path]) -> list[Path]:
    """Every `.map` file the targets name, in a stable order: a folder is crawled recursively
    (sorted, like the CLI), a file is taken as-is. Duplicates - the same map named twice, or a
    file also covered by a folder - are kept once."""
    seen: set[Path] = set()
    found: list[Path] = []
    for target in targets:
        path = Path(target)
        maps = sorted(path.rglob("*.map")) if path.is_dir() else [path]
        for map_path in maps:
            key = map_path.resolve()
            if key not in seen:
                seen.add(key)
                found.append(map_path)
    return found


def run_check(
    targets: Iterable[str | Path],
    games: Iterable[str | Path] = (),
    level: str = "WARNING",
    progress: Callable[[str], None] | None = None,
) -> dict:
    """Lint every map under `targets` and return the report `sage-edain lint-maps` would emit
    as JSON (`{"diagnostics": [...], "summary": {...}}`), plus the crawled map count under
    `"maps"`. `games` is the ordered optional game data (base game first, then the mod): each
    folder or `.big` path the maps' object references resolve against - with none, only the
    parse, map-local and convention checks run. Unlike one CLI run per target, the game is
    loaded once for the whole batch. `progress`, when given, receives one status line per stage
    (thread-safe to point at a Qt signal's `emit`)."""

    def tell(text: str) -> None:
        if progress is not None:
            progress(text)

    # Each game path becomes a (kind, path) source, classified the way the lint CLI classifies
    # a --base, so the shared game-sources panel's list drives the object-resolution check.
    source_list: list[Source] = [(source_kind(path), str(path)) for path in games]
    if source_list:
        tell("Loading game data… this can take a moment.")
        game, _names = load_sources(source_list, progress=progress)
    else:
        game = Game()

    paths = crawl_maps(targets)
    diagnostics = Diagnostics()
    for index, path in enumerate(paths, start=1):
        tell(f"Checking map {index}/{len(paths)}: {path.name}")
        # Parse each map once and run every check over it. A binary map that fails to parse (or
        # a check that blows up on it) becomes one map-parse-error rather than aborting the batch.
        try:
            model = MapModel.from_path(str(path))
            found = list(lint_map_references(model, game, path).items)
            found.extend(lint_map_conventions(model.raw, LintConfig(), path).items)
        except Exception as exc:  # noqa: BLE001 - one bad binary map must not abort the run
            diagnostics.add("map-parse-error", f"failed to parse map: {exc}", Span(str(path), 1, 1))
            continue
        diagnostics.items.extend(found)

    shown, summary = select_and_summarize(diagnostics.items, set(), set(), level)
    return {
        "diagnostics": [diagnostic_dict(d) for d in shown],
        "summary": summary,
        "maps": len(paths),
    }
