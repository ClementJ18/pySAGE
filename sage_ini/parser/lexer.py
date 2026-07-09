"""Line tokenizer for SAGE ini text. `;`, `//`, and `--` each start a comment anywhere on
a line (first marker wins, no quote/URL awareness), matching the engine - so an unquoted
URL truncates at `//`. Directives and in-value expressions are ordinary content here; the
block parser gives them meaning.
"""

import os
from dataclasses import dataclass
from pathlib import Path

from sage_ini.parser.io import read_text
from sage_ini.parser.location import Span

COMMENT_MARKERS = (";", "//", "--")


@dataclass(frozen=True, slots=True)
class Line:
    file: str
    number: int  # 1-based
    raw: str  # original text, no newline
    content: str  # comment stripped, surrounding whitespace stripped
    comment: str | None  # original comment substring including its marker

    @property
    def span(self) -> Span:
        return Span(self.file, self.number, self.number)

    @property
    def is_blank(self) -> bool:
        return not self.content and self.comment is None


def _find_comment_start(text: str) -> int:
    """Index where the first comment marker begins, or -1. Each marker is located with
    `str.find` (a C-level scan) and the earliest hit wins; a doubled marker (`//`, `--`) only
    counts as a comment, matching the engine, while a lone `/` or `-` is ordinary content."""
    best = text.find(";")
    for marker in ("//", "--"):
        index = text.find(marker)
        if index != -1 and (best == -1 or index < best):
            best = index
    return best


def split_comment(text: str) -> tuple[str, str | None]:
    """Split one raw line into (content, comment-with-marker-or-None)."""
    marker = _find_comment_start(text)
    if marker == -1:
        return text.strip(), None
    return text[:marker].strip(), text[marker:].rstrip()


def tokenize(text: str, file: str = "<string>") -> list[Line]:
    lines = []
    for number, raw in enumerate(text.splitlines(), start=1):
        content, comment = split_comment(raw)
        lines.append(Line(file=file, number=number, raw=raw, content=content, comment=comment))
    return lines


def tokenize_file(path: str | Path) -> list[Line]:
    path = Path(path)
    return tokenize(read_text(path), file=str(path))


# Tokenized lines per file, keyed by path string -> ((mtime_ns, size), lines). One physical
# file is tokenized many times in a load - by the root-discovery scan, then by every root that
# `#include`s it - so caching collapses that to once. Keyed on stat so an edited file
# re-tokenizes; safe for a long-lived process (the linter) without serving stale lines.
_FILE_CACHE: dict[str, tuple[tuple[int, int], list[Line]]] = {}


def tokenize_path(path: str | Path) -> list[Line]:
    """Tokenize a file, caching by (mtime, size). Pass a resolved path so callers reading the
    same physical file share one entry. The returned list is shared and must not be mutated -
    every consumer only iterates it."""
    key = str(path)
    try:
        st = os.stat(path)
    except OSError:
        return tokenize(read_text(path), file=key)
    sig = (st.st_mtime_ns, st.st_size)
    cached = _FILE_CACHE.get(key)
    if cached is not None and cached[0] == sig:
        return cached[1]
    lines = tokenize(read_text(path), file=key)
    _FILE_CACHE[key] = (sig, lines)
    return lines


def forget_path(path: str | Path) -> None:
    """Drop a file's cached tokens so the next `tokenize_path` re-reads it. An in-process writer
    (the linter's fixer) must call this after rewriting a file: a case-only edit keeps the same
    size, and a rewrite landing in the same mtime tick keeps the same `st_mtime_ns`, so the
    `(mtime, size)` signature alone would miss the change and serve stale lines."""
    _FILE_CACHE.pop(str(path), None)
