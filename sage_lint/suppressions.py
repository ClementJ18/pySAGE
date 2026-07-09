"""Inline suppression comments: a comment on a line silences named diagnostic codes
reported on that line.

After any SAGE comment marker (`;`, `//`, `--`):

    BuildCost = 90000              ; sagelint: ignore[out-of-range]
    Weapon RetiredBlade            ; sagelint: ignore[unused-definition, dangling-reference]
    ArmorSet = Prototype           ; sagelint: ignore

Codes are the bracketed list, comma- or space-separated, matched case-insensitively
against `Diagnostic.code`; the bare form (no brackets, or empty brackets) silences every
code on the line. A diagnostic is matched by the line its span *starts* on, so a
block-level finding like `unused-definition` is suppressed by a comment on the block's
header line.

Filtering runs inside the lint entry points (`sage_lint.linter`), re-reading each
diagnosed file once per run. Reading from disk rather than the parsed AST keeps the
mechanism uniform across every diagnostic source - parse errors on lines the block parser
never typed, conversion facts, and rule findings - and the editor daemon lints a live
buffer via a temp file written beside the real one, so unsaved suppression comments are
seen too.
"""

import re
from pathlib import Path

from sage_ini.parser.diagnostics import Diagnostic
from sage_ini.parser.io import read_text

__all__ = ["line_suppressions", "filter_suppressed"]

# `;`, `//` and `--` each start a comment anywhere on a line (see sage_ini.parser.lexer),
# so a directive found after one of them is always inside a comment - no lexing needed.
_DIRECTIVE = re.compile(r"(?:;|//|--)\s*sagelint:\s*ignore(?:\s*\[([^\]]*)\])?", re.IGNORECASE)

# Codes a bare `sagelint: ignore` suppresses: all of them.
_ALL_CODES = None


def line_suppressions(text: str) -> dict[int, frozenset[str] | None]:
    """Map each 1-based line number carrying an ignore directive to the lower-cased codes it
    suppresses, `None` meaning every code. Lines without a directive are absent."""
    if not _DIRECTIVE.search(text):
        return {}
    suppressions: dict[int, frozenset[str] | None] = {}
    for number, line in enumerate(text.splitlines(), start=1):
        match = _DIRECTIVE.search(line)
        if match is None:
            continue
        codes = match.group(1)
        if codes is None or not codes.strip():
            suppressions[number] = _ALL_CODES
        else:
            suppressions[number] = frozenset(
                token.lower() for token in re.split(r"[,\s]+", codes.strip()) if token
            )
    return suppressions


def _file_suppressions(
    file: str, cache: dict[str, dict[int, frozenset[str] | None]]
) -> dict[int, frozenset[str] | None]:
    """The suppression map for `file`, read once per run. A file that cannot be read (a
    synthetic span like `<rules>`, a path since deleted) suppresses nothing."""
    key = file.lower()
    if key not in cache:
        try:
            cache[key] = line_suppressions(read_text(Path(file)))
        except OSError:
            cache[key] = {}
    return cache[key]


def filter_suppressed(items: list[Diagnostic]) -> list[Diagnostic]:
    """Drop each diagnostic whose starting line carries an ignore directive naming its code
    (or naming no code, which suppresses everything on the line)."""
    cache: dict[str, dict[int, frozenset[str] | None]] = {}
    kept: list[Diagnostic] = []
    for diagnostic in items:
        suppressions = _file_suppressions(diagnostic.span.file, cache)
        if suppressions:
            codes = suppressions.get(diagnostic.span.line_start, frozenset())
            if codes is _ALL_CODES or diagnostic.code.lower() in codes:
                continue
        kept.append(diagnostic)
    return kept
