"""Test harness for the sage_ini suite.

Two tiers of tests:
- **core**: the fast, data-free unit suite for `sage_ini` + `sage_lint`. A bare
  `pytest` runs only this - the inner loop while implementing a feature.
- **full**: core plus the `full`-marked tests (the corpus acceptance gates and
  the peripheral-package suites). These run only with `--full`; without the flag
  they are deselected, so a default run stays sub-second.

Corpus tests are parametrized over real game-data dumps: any test taking a
`corpus_file` argument is fanned out over every ini/inc/bhav file of every
available corpus root; when no root is present the corpus tests are skipped,
never failed.

Corpus roots:
- `<repo>/data` (label "data"), when present;
- extra roots listed in `tests/corpus_roots.txt` (gitignored, machine-specific),
  one `label=path` per line, `#` comments allowed.
"""

from pathlib import Path

import pytest

from sage_ini.parser.io import iter_ini_files
from sage_ini.stats import ini_root, root_files


def pytest_addoption(parser):
    parser.addoption(
        "--full",
        action="store_true",
        default=False,
        help="Run the full suite: the corpus acceptance gates (thousands of "
        "parametrized cases over real game data) and the peripheral-package "
        "tests. Without this flag only the fast, data-free core suite runs.",
    )


def pytest_collection_modifyitems(config, items):
    """Deselect `full`-marked tests unless `--full` was passed.

    Deselection (not skip) keeps a core run's output clean - the full tier shows
    only as a deselected count, not thousands of skip lines.
    """
    if config.getoption("--full"):
        return
    core, deferred = [], []
    for item in items:
        (deferred if item.get_closest_marker("full") else core).append(item)
    if deferred:
        config.hook.pytest_deselected(items=deferred)
        items[:] = core


REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"
EXTRA_ROOTS_FILE = Path(__file__).resolve().parent / "corpus_roots.txt"


def corpus_roots() -> dict[str, Path]:
    roots = {}
    if DATA_DIR.is_dir():
        roots["data"] = DATA_DIR

    if EXTRA_ROOTS_FILE.is_file():
        for raw in EXTRA_ROOTS_FILE.read_text(encoding="utf-8").splitlines():
            entry = raw.strip()
            if not entry or entry.startswith("#"):
                continue
            label, sep, path = entry.partition("=")
            if not sep:
                continue
            root = Path(path.strip())
            if root.is_dir():
                roots[label.strip()] = root

    return roots


_ROOT_FILE_CACHE: dict[str, list[Path]] = {}


def corpus_parse_roots(label: str, root: Path) -> list[Path]:
    """Root files (not included by any other) of one corpus, cached."""
    if label not in _ROOT_FILE_CACHE:
        _ROOT_FILE_CACHE[label] = root_files(root)
    return _ROOT_FILE_CACHE[label]


def _parametrize(metafunc: pytest.Metafunc, name: str, per_root):
    files = []
    ids = []
    # Enumerating the corpus walks every root directory; skip it entirely in a
    # core run (no --full) so collection stays instant. The corpus tests are
    # `full`-marked and would be deselected anyway - here we just avoid paying
    # for thousands of params we are about to drop.
    if metafunc.config.getoption("--full"):
        for label, root in corpus_roots().items():
            for path in per_root(label, root):
                files.append(path)
                ids.append(f"{label}:{path.relative_to(root).as_posix()}")

    if not files:
        full = metafunc.config.getoption("--full")
        reason = "no corpus roots present" if full else "full suite only (run with --full)"
        metafunc.parametrize(
            name,
            [pytest.param(None, marks=pytest.mark.skip(reason=reason))],
            ids=["no-corpus"],
        )
        return

    metafunc.parametrize(name, files, ids=ids)


def pytest_generate_tests(metafunc: pytest.Metafunc):
    if "corpus_file" in metafunc.fixturenames:
        _parametrize(metafunc, "corpus_file", lambda label, root: iter_ini_files(root))
    if "corpus_root_file" in metafunc.fixturenames:
        _parametrize(metafunc, "corpus_root_file", corpus_parse_roots)


@pytest.fixture(scope="session")
def include_layers_of():
    """Map a corpus file to its ordered include-resolution layers.

    A mod corpus is overlaid on the base game: its includes may resolve into
    the base corpus, so the base ini root is appended as a fallback layer.
    """
    base = ini_root(DATA_DIR) if DATA_DIR.is_dir() else None
    layered = [ini_root(root) for root in corpus_roots().values()]

    def lookup(path: Path) -> tuple[Path, ...]:
        for root in layered:
            if path.is_relative_to(root):
                if base is not None and root != base:
                    return (root, base)
                return (root,)
        raise ValueError(f"{path} is not under any corpus root")

    return lookup
