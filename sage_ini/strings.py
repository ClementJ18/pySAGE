"""The localization string table: a SAGE `.str` table (`LABEL`/`"value"`/`END` blocks) or
Edain's semicolon-delimited `Lotr.csv` (`label;German;English`). Either populates
`Game.strings`.

Strings live outside the ini object model, so they carry no parse span the way objects and
macros do. `load_string_locations` recovers one - the `LABEL`/row line each label is defined
on - by re-reading the same files with line tracking, so an editor can jump to a string's
definition (see `Game.string_definitions`).
"""

from pathlib import Path

from sage_ini.parser.io import read_text
from sage_ini.parser.location import Span
from sage_ini.stats import is_map_path

__all__ = [
    "load_strings",
    "load_string_locations",
    "string_files",
    "parse_str",
    "parse_csv",
    "parse_str_spans",
    "parse_csv_spans",
    "STR_SUFFIX",
    "CSV_NAME",
]

STR_SUFFIX = ".str"
CSV_NAME = "lotr.csv"


def _iter_str(text: str):
    """Yield `(label, value, line)` for each `LABEL` / `"value"` / `END` block, where `line`
    is the 1-based line the label sits on. A value may span several quoted lines (concatenated);
    `//` and `;` lines are comments. The shared engine for `parse_str` and `parse_str_spans`."""
    label: str | None = None
    label_line = 0
    parts: list[str] = []
    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("//") or line.startswith(";"):
            continue
        if label is None:
            label = line
            label_line = number
            parts = []
        elif line.upper() == "END":
            yield label, "".join(parts), label_line
            label = None
        else:
            if len(line) >= 2 and line.startswith('"') and line.endswith('"'):
                line = line[1:-1]
            parts.append(line)


def _iter_csv(text: str):
    """Yield `(label, value, line)` for each `label;German;English` row: the first column is
    the label, the last the English text, `line` the 1-based row. Rows whose first column is
    not a `NAMESPACE:key` label (the header included) are skipped. Shared by `parse_csv` and
    `parse_csv_spans`."""
    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line:
            continue
        columns = line.split(";")
        label = columns[0].strip()
        if ":" not in label:
            continue  # header row or malformed line - a real label is `NAMESPACE:key`
        yield label, columns[-1].strip(), number


def parse_str(text: str) -> dict[str, str]:
    """Parse a `.str` table to `label -> value` (last definition wins within a file)."""
    return {label: value for label, value, _line in _iter_str(text)}


def parse_csv(text: str) -> dict[str, str]:
    """Parse Edain's `Lotr.csv` to `label -> English value` (last row wins within a file)."""
    return {label: value for label, value, _line in _iter_csv(text)}


def parse_str_spans(text: str, file: str) -> dict[str, Span]:
    """`label -> Span` of each label's `LABEL` line in a `.str` table, last-wins per file (so
    the recorded line is the one whose value `parse_str` keeps)."""
    return {label: Span(file, line, line) for label, _value, line in _iter_str(text)}


def parse_csv_spans(text: str, file: str) -> dict[str, Span]:
    """`label -> Span` of each label's row in a `Lotr.csv`, last-wins per file."""
    return {label: Span(file, line, line) for label, _value, line in _iter_csv(text)}


def _string_files(base: Path):
    """Every global `.str` file and any `Lotr.csv` under `base`, recursively. Map-scoped
    tables (`maps/.../map.str`) are skipped - not part of the global string table."""
    if not base.is_dir():
        return
    for path in base.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() == STR_SUFFIX or path.name.lower() == CSV_NAME:
            if not is_map_path(path, base):
                yield path


def string_files(root: str | Path) -> list[Path]:
    """Every localization table file (`.str` or `Lotr.csv`) under `root`, map-scoped tables
    excluded - a public view of the loader's file scan. `sage_lint init` uses it to tell the
    user whether a string table will be found, since the string-label rule no-ops without one."""
    return list(_string_files(Path(root)))


def load_strings(root: str | Path, overlays: tuple[str | Path, ...] = ()) -> dict[str, str]:
    """Every localization label defined under `root` and `overlays`, merged with `root`
    (the mod) taking precedence over `overlays` (the base game). Unreadable files are skipped."""
    strings: dict[str, str] = {}
    for base in (Path(root), *(Path(overlay) for overlay in overlays)):
        for path in _string_files(base):
            try:
                text = read_text(path)
            except OSError:
                continue
            table = parse_csv(text) if path.name.lower() == CSV_NAME else parse_str(text)
            for label, value in table.items():
                strings.setdefault(label, value)
    return strings


def load_string_locations(root: str | Path) -> dict[str, Span]:
    """`label -> Span` of where each label is defined, for the string files directly under
    `root`. Scans only `root` (not base/overlay layers): a base-game string reaches the build
    through a merged temp folder that is later removed, so its location would not point at a
    file the user can open - those labels keep their value-only fallback in the editor. The
    first file to define a label wins, matching `load_strings`' merge order under one root."""
    locations: dict[str, Span] = {}
    for path in _string_files(Path(root)):
        try:
            text = read_text(path)
        except OSError:
            continue
        spans = (
            parse_csv_spans(text, str(path))
            if path.name.lower() == CSV_NAME
            else parse_str_spans(text, str(path))
        )
        for label, span in spans.items():
            locations.setdefault(label, span)
    return locations
