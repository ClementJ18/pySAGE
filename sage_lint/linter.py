"""Lint a whole game: assemble it, then merge three diagnostic sources into one report
- parse/load problems (sage_ini.loader), conversion facts from `Game.validate()`, and
sage_lint `Rule` judgments.

Excluded directories are dropped from the *report*, not the *build*: the whole game is
still assembled (so cross-file references resolve), but diagnostics inside an excluded
directory are filtered out. Base-game sources are silenced the same way. Last, inline
`; sagelint: ignore[...]` comments drop the named codes on their own line (see
`sage_lint.suppressions`).
"""

import shutil
import tempfile
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from sage_ini.loader import LoadedGame, load_game, map_files
from sage_ini.model.game import Game
from sage_ini.model.xref import references_into
from sage_ini.parser.blockparser import parse_file
from sage_ini.parser.diagnostics import Diagnostic, Diagnostics
from sage_ini.parser.io import ASSET_SUFFIXES, MAP_SUFFIXES, iter_asset_files
from sage_ini.parser.location import Span
from sage_ini.stats import ini_root, is_map_path
from sage_lint.rules.base import Rule, run_rules
from sage_lint.suppressions import filter_suppressed
from sage_utils.sources import (
    LOAD_SUFFIXES,
    big_member_basenames,
    loadable_files,
    merge_shadowed,
)

# What a base source contributes to the merged folder: the ini/str the engine loads, plus the
# `.map`/`.bse` layouts so a base-game map both registers in the index and can be parsed/linted.
# Textures/models are deliberately excluded - they are bulky and only their names are indexed
# (`_base_asset_names`), never their bytes.
_BASE_MERGE_SUFFIXES = LOAD_SUFFIXES | MAP_SUFFIXES


@dataclass
class BaseLayer:
    """A merged base-game folder built from `(kind, path)` sources (folders and extracted
    `.big`s) and kept on disk, so a daemon can resolve `#include`s that fall through to the
    base game when re-linting a single file - not only on the initial whole-folder build.
    `root` is the merged folder, `include_root` its include-resolution anchor, `workdir` the
    temp tree to remove via `cleanup()` once the daemon no longer needs it."""

    root: Path
    include_root: Path
    workdir: Path

    def cleanup(self) -> None:
        shutil.rmtree(self.workdir, ignore_errors=True)


def _prepare_base(root: str | Path, bases: tuple[tuple[str, str], ...]) -> BaseLayer | None:
    """Merge `bases` (highest priority first) into a temp folder, skipping paths the mod under
    `root` already owns, and return it as a `BaseLayer` the caller must `cleanup()`. None when
    there are no bases."""
    if not bases:
        return None
    workdir = Path(tempfile.mkdtemp(prefix="sage_lint_bases_"))
    try:
        shadow = frozenset(rel for rel, _ in loadable_files(Path(root), _BASE_MERGE_SUFFIXES))
        merged = merge_shadowed(list(bases), workdir, shadow=shadow, suffixes=_BASE_MERGE_SUFFIXES)
    except BaseException:
        shutil.rmtree(workdir, ignore_errors=True)
        raise
    return BaseLayer(root=merged, include_root=ini_root(merged), workdir=workdir)


def _base_asset_names(bases: tuple[tuple[str, str], ...]) -> set[str]:
    """The loose-asset basenames each base source contributes to the index: a folder is crawled
    for its textures/models, a `.big` is read for its matching entry names (without extracting any
    bytes). The base merge only carries ini/str, so without this a base-game texture packed in a
    `.big` is invisible and every mod reference to it is wrongly flagged missing."""
    names: set[str] = set()
    for kind, path in bases:
        if kind == "big":
            names |= big_member_basenames(path, ASSET_SUFFIXES)
        else:
            names |= {asset.name.lower() for asset in iter_asset_files(path)}
    return names


def _under(span_file: str, directories: tuple[Path, ...]) -> bool:
    """Whether a diagnostic's source file lives in any excluded directory."""
    try:
        path = Path(span_file).resolve()
    except OSError:
        return False  # synthetic spans like "<rules>" are never excluded
    return any(path.is_relative_to(directory) for directory in directories)


def _keep(diagnostic: Diagnostic, excluded: tuple[Path, ...]) -> bool:
    return not excluded or not _under(diagnostic.span.file, excluded)


# Findings retracted when a map build turns out to reference the definition (their `extra`
# carries the `(table, name)` identity the map-reference set is keyed by).
_UNUSED_CODES = frozenset({"unused-definition", "unused-object"})


def _used_by_a_map(diagnostic: Diagnostic, map_used: set[tuple[str, str]]) -> bool:
    return (
        diagnostic.code in _UNUSED_CODES
        and (diagnostic.extra.get("table"), diagnostic.extra.get("name")) in map_used
    )


def lint_game(
    loaded: LoadedGame,
    rules: Iterable[type[Rule]] | None = None,
    exclude: tuple[str | Path, ...] = (),
) -> Diagnostics:
    excluded = tuple(Path(directory).resolve() for directory in exclude)
    diagnostics = Diagnostics()
    diagnostics.items.extend(loaded.diagnostics.items)
    diagnostics.items.extend(loaded.game.validate().items)
    diagnostics.items.extend(run_rules(loaded.game, rules).items)
    kept = (d for d in diagnostics.items if _keep(d, excluded))
    # A file `#include`d by many roots is built once per root, so collapse exact
    # duplicate diagnostics (same code, message, span, severity) to one line.
    diagnostics.items = filter_suppressed(list(dict.fromkeys(kept)))
    return diagnostics


def lint_file(
    path: str | Path,
    include_root: str | Path | None = None,
    rules: Iterable[type[Rule]] | None = None,
) -> Diagnostics:
    """Lint a single file in isolation: parse it (expanding includes) and build just that
    file into a fresh game, then report its parse, conversion, and rule diagnostics.

    This is the save-time fast path for an editor: it parses one file plus its includes
    instead of re-assembling the whole folder. Because no sibling root files are built,
    references to definitions defined elsewhere cannot resolve and may surface here as
    conversion/reference diagnostics; those are only authoritative under `lint_folder`.
    Includes resolve against `include_root` (the project root), defaulting to the file's
    own directory.
    """
    path = Path(path)
    base = Path(include_root) if include_root is not None else path.parent
    result = parse_file(path, resolve_includes=True, include_layers=(ini_root(base),))

    diagnostics = Diagnostics()
    diagnostics.items.extend(result.diagnostics.items)
    game = Game()
    try:
        game.load_document(result.document)
    except (ValueError, KeyError, TypeError, IndexError) as exc:
        diagnostics.add("load-error", f"{exc}", Span(str(path), 1, 1))
        return diagnostics

    diagnostics.items.extend(game.validate().items)
    diagnostics.items.extend(run_rules(game, rules).items)
    diagnostics.items = filter_suppressed(list(dict.fromkeys(diagnostics.items)))
    return diagnostics


def lint_file_cached(
    cache: Game,
    path: str | Path,
    include_root: str | Path | None = None,
    rules: Iterable[type[Rule]] | None = None,
    include_bases: tuple[Path, ...] = (),
) -> Diagnostics:
    """Re-lint one file against an already-built `cache` game (see `lint_file_cached_game`,
    which this wraps for callers that only need the diagnostics)."""
    diagnostics, _built = lint_file_cached_game(
        cache, path, include_root=include_root, rules=rules, include_bases=include_bases
    )
    return diagnostics


def lint_file_cached_game(
    cache: Game,
    path: str | Path,
    include_root: str | Path | None = None,
    rules: Iterable[type[Rule]] | None = None,
    include_bases: tuple[Path, ...] = (),
) -> tuple[Diagnostics, Game | None]:
    """Re-lint one file against an already-built `cache` game: parse just this file and build
    only its objects, but resolve cross-references (and macros) against `cache`, so a name a
    sibling file declares resolves instead of dangling. This is the incremental path behind
    the editor daemon - full-folder accuracy at single-file speed, since only the changed
    file is parsed and validated, not the whole game rebuilt.

    `include_bases` are lower-priority include roots (the merged base game) an `#include` may
    fall through to, so a base-game include resolves here exactly as it does on the full build.

    The cache is read, never mutated: the file's own (possibly edited) definitions shadow the
    cache only within this throwaway build, so stale copies in the cache do not leak in.

    Returns the diagnostics *and* the throwaway single-file build (None when it failed to
    load), so the daemon can diff the file's contributed definitions against the cache."""
    path = Path(path)
    base = Path(include_root) if include_root is not None else path.parent
    layers = (ini_root(base), *include_bases)
    result = parse_file(path, resolve_includes=True, include_layers=layers)

    diagnostics = Diagnostics()
    diagnostics.items.extend(result.diagnostics.items)
    game = Game()
    game.add_macros(cache.macros)  # so `#define`s from sibling files still expand
    game.strings.update(cache.strings)
    game.string_definitions.update(cache.string_definitions)
    game.assets.update(cache.assets)  # so the missing-texture/model-file rules see the crawled art
    game.map_files.extend(cache.map_files)  # and the crawled maps/bases/libraries
    game._reference_fallback = cache  # so cross-references resolve against the whole game
    # A map.ini patches the global objects it re-opens (the engine's map override); flag the
    # throwaway build so `register` links each re-opened object to its cache definition, letting
    # module edits resolve against the inherited modules. Off for a normal file, where a
    # re-definition is a plain override, never a patch.
    game._map_override = is_map_path(path, base)
    try:
        game.load_document(result.document)
    except (ValueError, KeyError, TypeError, IndexError) as exc:
        diagnostics.add("load-error", f"{exc}", Span(str(path), 1, 1))
        return diagnostics, None

    diagnostics.items.extend(game.validate().items)
    diagnostics.items.extend(run_rules(game, rules).items)
    diagnostics.items = filter_suppressed(list(dict.fromkeys(diagnostics.items)))
    return diagnostics, game


def _lint_maps(
    game: Game,
    root: str | Path,
    rules: Iterable[type[Rule]] | None,
    excluded: tuple[Path, ...],
    include_bases: tuple[Path, ...] = (),
) -> tuple[list[Diagnostic], set[tuple[str, str]]]:
    """Lint each map.ini under `root` in its own context: a map is excluded from the global
    build, so it is re-linted against `game` as a reference fallback (cheap - no per-map global
    rebuild) and only its own (map-scoped) diagnostics are kept. A map under an excluded
    directory is skipped, never built.

    Also returns the `(table, name)` of every *global* definition some map build references -
    edges the global reference graph cannot see (a campaign map.ini's command set naming a
    base-game button), which `build_cache` uses to retract unused-definition findings."""
    root = Path(root)
    diagnostics: list[Diagnostic] = []
    map_used: set[tuple[str, str]] = set()
    for map_path in map_files(root):
        if excluded and _under(str(map_path), excluded):
            continue
        cached, built = lint_file_cached_game(
            game, map_path, include_root=root, rules=rules, include_bases=include_bases
        )
        if built is not None:
            map_used.update((obj.key, obj.name) for obj in references_into(built, game))
        for diagnostic in cached.items:
            if is_map_path(diagnostic.span.file, root) and _keep(diagnostic, excluded):
                diagnostics.append(diagnostic)
    return diagnostics, map_used


def build_cache(
    root: str | Path,
    rules: Iterable[type[Rule]] | None = None,
    exclude: tuple[str | Path, ...] = (),
    bases: tuple[tuple[str, str], ...] = (),
) -> tuple[Game, Diagnostics, BaseLayer | None]:
    """Assemble the game under `root` and return it, its full-folder diagnostics, and the
    `BaseLayer` (or None) the bases merged into.

    The game is kept so an editor daemon can re-lint individual files against it
    (`lint_file_cached`) without rebuilding; the diagnostics are the initial whole-folder
    report, including each map.ini linted in its own context. `bases` are lower-priority
    `(kind, path)` sources merged in build-only (their merged folder is excluded, so only
    diagnostics under `root` show). The returned `BaseLayer` stays on disk so per-file re-lints
    can resolve base-game `#include`s; **the caller owns `BaseLayer.cleanup()`**."""
    excluded = tuple(Path(directory).resolve() for directory in exclude)
    base_layer = _prepare_base(root, bases)
    try:
        if base_layer is None:
            loaded = load_game(root)
            diagnostics = lint_game(loaded, rules, exclude)
            include_bases: tuple[Path, ...] = ()
        else:
            loaded = load_game(root, bases=(base_layer.root,))
            # The base merge only carries loadable ini/str, so a base's *art* (textures/models)
            # never reaches the asset index - a mod reference to a base-game texture would look
            # missing. Index those names directly: crawl a folder base, read a .big's entry list.
            loaded.game.assets.update(_base_asset_names(bases))
            diagnostics = lint_game(loaded, rules, (*exclude, base_layer.root))
            include_bases = (base_layer.include_root,)

        map_diagnostics, map_used = _lint_maps(loaded.game, root, rules, excluded, include_bases)
    except BaseException:
        if base_layer is not None:
            base_layer.cleanup()
        raise
    if map_used:
        # A definition only a map.ini reaches is not unused - the global graph just cannot
        # see the per-map contexts. Retract those findings now that the maps are built.
        diagnostics.items = [d for d in diagnostics.items if not _used_by_a_map(d, map_used)]
    if map_diagnostics:
        diagnostics.items.extend(map_diagnostics)
        diagnostics.items = list(dict.fromkeys(diagnostics.items))
    return loaded.game, diagnostics, base_layer


def assemble_with_bases(
    root: str | Path, bases: tuple[tuple[str, str], ...] = ()
) -> tuple[LoadedGame, BaseLayer | None]:
    """Assemble the game under `root` with `bases` (folder / `.big` sources) merged beneath it,
    without running any lint rules - the loaded game and the `BaseLayer` (or None) it merged into.
    For consumers that only need the assembled, base-resolved `Game` (e.g. the `diff` command),
    where `build_cache`'s rule and map-lint passes would be wasted work. **Caller owns
    `BaseLayer.cleanup()`.**"""
    base_layer = _prepare_base(root, bases)
    try:
        if base_layer is None:
            return load_game(root), None
        loaded = load_game(root, bases=(base_layer.root,))
        return loaded, base_layer
    except BaseException:
        if base_layer is not None:
            base_layer.cleanup()
        raise


def lint_folder(
    root: str | Path,
    rules: Iterable[type[Rule]] | None = None,
    exclude: tuple[str | Path, ...] = (),
    bases: tuple[tuple[str, str], ...] = (),
) -> Diagnostics:
    """Assemble the game under `root` and report its problems (see `build_cache`). A one-shot:
    the base layer is removed before returning, since nothing re-lints against it afterwards."""
    game, diagnostics, base_layer = build_cache(root, rules, exclude, bases)
    if base_layer is not None:
        base_layer.cleanup()
    return diagnostics
