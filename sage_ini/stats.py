"""Corpus scoreboard: parse-rate metrics applied to every file, plus the root-file
construct/validate counts, formatted as a single comparable table."""

from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from sage_ini.model.game import Game
from sage_ini.parser.blockparser import include_target, parse, parse_file, resolve_include
from sage_ini.parser.io import iter_ini_files, read_text, read_text_with_encoding
from sage_ini.parser.lexer import COMMENT_MARKERS, tokenize, tokenize_path
from sage_ini.parser.printer import print_document

__all__ = [
    "ini_root",
    "as_root_list",
    "is_map_path",
    "root_files",
    "included_files",
    "compute_scoreboard",
    "format_scoreboard",
    "Scoreboard",
]

# Metrics planned but not yet implemented; printed as pending so the scoreboard
# shape stays stable across phases.
PENDING_METRICS: tuple[str, ...] = ()


def _reads(path: Path) -> bool:
    read_text_with_encoding(path)
    return True


def _tokenizes(path: Path) -> bool:
    text = read_text(path)
    lines = tokenize(text, file=str(path))
    if len(lines) != len(text.splitlines()):
        return False
    return all(marker not in line.content for line in lines for marker in COMMENT_MARKERS)


def _round_trips(path: Path) -> bool:
    first = parse_file(path)
    reparsed = parse(print_document(first.document), file="reprint")
    return first.document.children == reparsed.document.children


METRICS: dict[str, Callable[[Path], bool]] = {
    "reads with supported encoding": _reads,
    "tokenizes": _tokenizes,
    "round-trips": _round_trips,
}


def ini_root(root: str | Path) -> Path:
    """The directory root-relative includes resolve against: the scan root, or its nested
    `data/ini` when the corpus dump keeps the full game layout."""
    root = Path(root)
    nested = root / "data" / "ini"
    return nested if nested.is_dir() else root


def as_root_list(root: str | Path | Sequence[str | Path]) -> list[Path]:
    """Normalize a game-root argument - a single root, or an ascending-priority sequence of them
    (a later root shadows an earlier one) - to a list of `Path`s. The shared spelling the loader
    and the ThingTemplate walk use so multiple `--game` roots layer the same way in both."""
    if isinstance(root, (str, Path)):
        return [Path(root)]
    return [Path(part) for part in root]


def is_map_path(path: str | Path, root: str | Path) -> bool:
    """Whether `path` is map-scoped - beneath a `maps/` directory under `root`. A map.ini
    is per-map (its definitions never leak to the global game), so whole-game assembly
    excludes these files."""
    root = Path(root)
    try:
        parts = Path(path).relative_to(root).parts
    except ValueError:
        parts = Path(path).parts
    return any(part.lower() == "maps" for part in parts[:-1])


def included_files(root: str | Path) -> set[str]:
    """Lowercased resolved paths of every file `#include`d by another."""
    layers = (ini_root(root),)
    included: set[str] = set()
    for path in iter_ini_files(root):
        source = path.resolve()
        for line in tokenize_path(source):
            target = include_target(line.content)
            if target is not None:
                resolved = resolve_include(target, source, layers)
                if resolved is not None:
                    included.add(str(resolved).lower())
    return included


def root_files(root: str | Path) -> list[Path]:
    """Files that are not included by any other file - the parse units."""
    included = included_files(root)
    return [path for path in iter_ini_files(root) if str(path.resolve()).lower() not in included]


STRUCTURAL_CODES = frozenset({"stray-end", "unclosed-block", "unclosed-script"})
ENVIRONMENTAL_CODES = frozenset({"unresolved-include", "include-cycle"})


@dataclass
class Scoreboard:
    total: int = 0
    passed: dict[str, int] = field(default_factory=dict)
    encodings: Counter = field(default_factory=Counter)
    suffixes: Counter = field(default_factory=Counter)
    roots_total: int = 0
    roots_clean: int = 0
    roots_missing_includes: int = 0
    roots_structural_fail: int = 0
    roots_typed_ok: int = 0
    roots_typed_fail: int = 0
    roots_validate_ok: int = 0
    roots_validate_diags: int = 0


def compute_scoreboard(root: str | Path, overlays: tuple[Path, ...] = ()) -> Scoreboard:
    """Scoreboard for one corpus; `overlays` are lower-priority ini roots
    (e.g. the base game under a mod) that includes may resolve into."""
    board = Scoreboard(passed=dict.fromkeys(METRICS, 0))

    for path in iter_ini_files(root):
        board.total += 1
        board.suffixes[path.suffix.lower()] += 1

        _, encoding = read_text_with_encoding(path)
        board.encodings[encoding] += 1

        for name, metric in METRICS.items():
            if metric(path):
                board.passed[name] += 1

    layers = (ini_root(root), *(ini_root(overlay) for overlay in overlays))
    for path in root_files(root):
        board.roots_total += 1
        result = parse_file(path, resolve_includes=True, include_layers=layers)
        codes = {d.code for d in result.diagnostics}
        if not result.diagnostics:
            board.roots_clean += 1
        elif codes & STRUCTURAL_CODES:
            board.roots_structural_fail += 1
        elif codes & ENVIRONMENTAL_CODES:
            board.roots_missing_includes += 1

        if not (codes & ENVIRONMENTAL_CODES):
            game = Game()
            try:
                game.load_document(result.document)
                board.roots_typed_ok += 1
            except Exception:  # noqa: BLE001 - scoreboard counts failures, does not raise
                board.roots_typed_fail += 1
                continue
            try:
                diagnostics = game.validate()
                board.roots_validate_ok += 1
                board.roots_validate_diags += len(diagnostics)
            except Exception:  # noqa: BLE001 - scoreboard counts failures, does not raise
                pass

    return board


def format_scoreboard(board: Scoreboard) -> str:
    lines = [f"files: {board.total}"]

    by_suffix = ", ".join(f"{suffix}: {count}" for suffix, count in sorted(board.suffixes.items()))
    lines.append(f"  by extension: {by_suffix or 'none'}")

    by_encoding = ", ".join(
        f"{encoding}: {count}" for encoding, count in board.encodings.most_common()
    )
    lines.append(f"  by encoding: {by_encoding or 'none'}")

    lines.append("metrics:")
    for name, passed in board.passed.items():
        rate = 100 * passed / board.total if board.total else 0.0
        lines.append(f"  {name}: {passed}/{board.total} ({rate:.1f}%)")

    # Roots blocked by a missing include are unverifiable, so they are excluded from the
    # denominator and reported separately.
    verifiable = board.roots_total - board.roots_missing_includes
    structural_ok = verifiable - board.roots_structural_fail
    rate = 100 * structural_ok / verifiable if verifiable else 0.0
    lines.append(
        f"  block-parses (roots, includes expanded): {structural_ok}/{verifiable} ({rate:.1f}%)"
    )
    if board.roots_missing_includes:
        lines.append(
            f"  (+ {board.roots_missing_includes} roots unverifiable - missing include files)"
        )

    typed_total = board.roots_typed_ok + board.roots_typed_fail
    typed_rate = 100 * board.roots_typed_ok / typed_total if typed_total else 0.0
    lines.append(
        f"  typed-constructs (roots): {board.roots_typed_ok}/{typed_total} ({typed_rate:.1f}%)"
    )

    # "validates" = the field-conversion pass completed without an unhandled exception;
    # conversion problems are recorded as diagnostics, not failures.
    validate_rate = (
        100 * board.roots_validate_ok / board.roots_typed_ok if board.roots_typed_ok else 0.0
    )
    lines.append(
        f"  validates (roots): {board.roots_validate_ok}/{board.roots_typed_ok} "
        f"({validate_rate:.1f}%); {board.roots_validate_diags} conversion diagnostics"
    )

    for name in PENDING_METRICS:
        lines.append(f"  {name}: pending")

    return "\n".join(lines)
