"""Discovering, merging and loading SAGE data sources (folders and .big archives).

Sources are merged into one folder (later sources overwrite earlier ones by path)
then loaded into a Game. Kept Qt-free so it can run headless.
"""

import shutil
import tempfile
from pathlib import Path, PurePosixPath

from sage_ini.model.game import Game
from sage_ini.parser.blockparser import parse_file
from sage_ini.parser.io import read_text
from sage_ini.stats import ini_root, root_files
from sage_ini.strings import parse_str  # re-exported: the canonical .str parser
from sage_utils.config import read_json, write_json
from sage_utils.factiongraph.bases import collect_base_layouts

INI_SUFFIXES = frozenset({".ini", ".inc", ".bhav"})
STR_SUFFIX = ".str"
LOAD_SUFFIXES = INI_SUFFIXES | {STR_SUFFIX}
# Base layouts (`.bse`) ride along with a full source load so the faction graph can
# decompose castle/camp plots; the narrower LOAD_SUFFIXES stays for callers (the linter's
# base layers) that don't want them.
BSE_SUFFIX = ".bse"
GAME_SUFFIXES = LOAD_SUFFIXES | {BSE_SUFFIX}

SOURCES_FILE = "sources.json"


def save_sources(sources: list[tuple[str, str]], app: str = "sage_ui") -> None:
    """Persist the ordered (kind, path) source list (best effort)."""
    write_json(app, SOURCES_FILE, [list(s) for s in sources])


def load_saved_sources(app: str = "sage_ui") -> list[tuple[str, str]]:
    """The remembered source list, or empty when none is saved or it is unreadable."""
    data = read_json(app, SOURCES_FILE, [])
    sources: list[tuple[str, str]] = []
    for item in data if isinstance(data, list) else []:
        if isinstance(item, list) and len(item) == 2 and all(isinstance(x, str) for x in item):
            sources.append((item[0], item[1]))
    return sources


def norm_key(path) -> str:
    """A source-relative path normalized to a lowercase forward-slash key."""
    return str(path).replace("\\", "/").lstrip("/").lower()


def loadable_files(folder: Path, suffixes: frozenset[str] = LOAD_SUFFIXES):
    """Yield (relative-path key, absolute path) for each file in a folder whose suffix is in
    `suffixes` (the ini/str the engine loads by default; callers that also want `.map`/`.bse`
    layouts merged pass a wider set)."""
    base = Path(folder)
    for path in base.rglob("*"):
        if path.is_file() and path.suffix.lower() in suffixes:
            yield norm_key(path.relative_to(base)), path


def big_entry_basename(name: str) -> str:
    """The lowercased file name of a .big entry path.

    Entry paths are stored Windows-style (`art\\HeroUI_001.dds`). `norm_key` folds both `\\` and
    `/` to `/` before the split, so the basename is correct on POSIX too, where a backslash is an
    ordinary character that `Path(name).name` would not treat as a separator."""
    return norm_key(name).rsplit("/", 1)[-1]


def extract_big(big_path: str, dest: Path, suffixes: frozenset[str] = LOAD_SUFFIXES) -> Path:
    """Extract a .big's files whose suffix is in `suffixes` to `dest`, reading entries off disk
    rather than buffering the whole archive in memory. Defaults to the loadable ini/str; the
    linter widens this to include `.map`/`.bse` so a base-game map can be parsed and linted (but
    never textures/models - those are huge and only their names are indexed, see
    `big_member_basenames`)."""
    from pyBIG import InDiskArchive  # noqa: PLC0415 - lazy: the [ui]/[wiki] extra is optional

    archive = InDiskArchive(str(big_path))
    # Filter on the normalized basename (entry paths are Windows-style; see `big_entry_basename`),
    # but keep the original names - they are the keys `extract` looks the entries up by.
    wanted = [
        name
        for name in archive.file_list()
        if PurePosixPath(big_entry_basename(name)).suffix in suffixes
    ]
    dest.mkdir(parents=True, exist_ok=True)
    archive.extract(str(dest), files=wanted)
    return dest


def big_member_basenames(big_path: str | Path, suffixes: frozenset[str]) -> set[str]:
    """The lowercased basenames of a .big's entries whose suffix is in `suffixes`, read from the
    archive's file list without extracting any bytes. Enough for the linter's asset-membership
    check: a packed texture or model counts as present without unpacking it (and `extract_big`
    only unpacks the loadable ini/str, so a base .big's art is otherwise invisible to the index)."""
    from pyBIG import InDiskArchive  # noqa: PLC0415 - lazy: the [ui]/[wiki] extra is optional

    archive = InDiskArchive(str(big_path))
    names = {big_entry_basename(name) for name in archive.file_list()}
    return {name for name in names if PurePosixPath(name).suffix in suffixes}


def source_root(
    kind: str, path: str, workdir: Path, index: int, suffixes: frozenset[str] = LOAD_SUFFIXES
) -> Path:
    """The on-disk folder for a source: the folder itself, or a .big with its `suffixes` entries
    extracted under `workdir`."""
    if kind == "folder":
        return Path(path)
    return extract_big(path, workdir / f"big_{index}", suffixes)


def build_merged(
    sources: list[tuple[str, str]],
    workdir: Path,
    progress=None,
    suffixes: frozenset[str] = LOAD_SUFFIXES,
) -> Path:
    """Copy every source's loadable files into one folder, later sources overwriting
    earlier ones at the same path. `progress`, if given, is called with a status
    string before each source (extracting a .big is the slow step)."""
    merged = workdir / "merged"
    merged.mkdir(parents=True, exist_ok=True)
    for index, (kind, path) in enumerate(sources):
        if progress is not None:
            progress(f"Loading {Path(path).name}…")
        root = source_root(kind, path, workdir, index, suffixes)
        for rel, file_path in loadable_files(root, suffixes):
            dest = merged / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(file_path, dest)
    return merged


def merge_shadowed(
    sources: list[tuple[str, str]],
    workdir: Path,
    shadow: frozenset[str] = frozenset(),
    suffixes: frozenset[str] = LOAD_SUFFIXES,
) -> Path:
    """Merge sources highest-priority-first, copying a file (of a `suffixes` kind) only if its
    path is not already claimed by `shadow` (paths owned by a higher-priority source outside
    this list) or an earlier source here. Used to load base-game files only where a mod does
    not already override them."""
    merged = workdir / "base_merged"
    merged.mkdir(parents=True, exist_ok=True)
    claimed = set(shadow)
    for index, (kind, path) in enumerate(sources):
        root = source_root(kind, path, workdir, index, suffixes)
        here: set[str] = set()
        for rel, file_path in loadable_files(root, suffixes):
            here.add(rel)
            if rel in claimed:
                continue
            dest = merged / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(file_path, dest)
        claimed.update(here)  # later, lower-priority sources cannot reclaim these
    return merged


def load_sources(sources: list[tuple[str, str]], progress=None) -> tuple[Game, list[str]]:
    """Build the merged folder (extracting any .big) and load it into a Game, so the
    root/include machinery can resolve `#include`s across all sources; the temp tree
    is removed afterwards. `progress`, if given, gets status strings as work proceeds.

    Base layouts (`bases/*.bse`) are carried along and resolved once the game is built,
    attached as `game.base_layouts` - the faction graph reads them to decompose a plot
    flag's castle/camp base into its citadel and foundations (needs sagemap; without it
    the table is simply empty)."""
    game = Game()
    workdir = Path(tempfile.mkdtemp(prefix="sage_sources_"))
    try:
        merged = build_merged(sources, workdir, progress=progress, suffixes=GAME_SUFFIXES)

        if progress is not None:
            progress("Parsing game data…")
        layers = (ini_root(merged),)
        for path in root_files(merged):
            try:
                game.load_document(
                    parse_file(path, resolve_includes=True, include_layers=layers).document
                )
            except Exception:  # noqa: BLE001  (one bad file shouldn't abort the load)
                pass

        if progress is not None:
            progress("Loading string tables…")
        for str_path in merged.rglob("*" + STR_SUFFIX):
            try:
                game.strings.update(parse_str(read_text(str_path)))
            except Exception:  # noqa: BLE001
                pass

        # Classification is KindOf-based, so the layouts resolve only after the game is
        # loaded - and must resolve before the merged tree is deleted.
        if progress is not None:
            progress("Reading base layouts…")
        game.base_layouts = collect_base_layouts(game, merged)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    return game, sorted(game.objects)
