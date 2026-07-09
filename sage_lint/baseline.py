"""A baseline of accepted diagnostics, so a noisy existing project can adopt the linter
without first fixing everything: record today's problems once, then report only what is
*new* against that record. The pre-existing set is suppressed (and the run exits clean),
which lets the linter go into CI immediately while the backlog is burned down over time.

Matching is deliberately **line-insensitive**. A baseline entry is keyed by `(file, code,
message)` with an occurrence count - never a line number - so editing a file (which shifts
every line below) does not resurface unrelated baselined diagnostics. The count is still
honoured: if a file held two of some problem and now holds three, the third is reported as
new. File paths are stored relative to the lint root with forward slashes, so the baseline
is portable across machines and checkouts.

The file is JSON (machine-written, human-diffable): a sorted list of entries, each
`{file, code, message, count}`. Generate or refresh it with `lint --write-baseline`.
"""

import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from sage_ini.parser.diagnostics import Diagnostic

BASELINE_VERSION = 1
# The conventional name, looked for beside `.sagelint` when no path is given explicitly.
BASELINE_NAME = ".sagelint.baseline"

# A diagnostic identity that survives edits: its file (root-relative), code and message.
Key = tuple[str, str, str]


class BaselineError(Exception):
    """A baseline file that exists but could not be read as a valid baseline."""


def relative_file(file: str, root: Path | None) -> str:
    """The diagnostic's file as stored in a baseline: relative to `root` with forward slashes
    when it sits under it, else the original string (a synthetic span like `<rules>`, or a path
    outside the tree, is kept verbatim). Portability hinges on this being checkout-independent."""
    if root is None:
        return file
    try:
        path = Path(file)
        if path.is_absolute() and path.is_relative_to(root):
            return path.relative_to(root).as_posix()
    except (OSError, ValueError):
        pass
    return file


def diagnostic_key(diag: Diagnostic, root: Path | None) -> Key:
    """The line-insensitive identity a baseline matches on."""
    return (relative_file(diag.span.file, root), diag.code, diag.message)


@dataclass
class Baseline:
    """Loaded baseline counts: how many of each `(file, code, message)` are accepted."""

    counts: Counter[Key]

    def partition(
        self, diagnostics: list[Diagnostic], root: Path | None
    ) -> tuple[list[Diagnostic], list[Diagnostic]]:
        """Split `diagnostics` into `(new, suppressed)`: each diagnostic whose key still has an
        unconsumed baseline allowance is suppressed, the rest are new. Input order is preserved,
        so which of several identical diagnostics counts as "new" is deterministic."""
        remaining = Counter(self.counts)
        new: list[Diagnostic] = []
        suppressed: list[Diagnostic] = []
        for diag in diagnostics:
            key = diagnostic_key(diag, root)
            if remaining.get(key, 0) > 0:
                remaining[key] -= 1
                suppressed.append(diag)
            else:
                new.append(diag)
        return new, suppressed


def load_baseline(path: Path) -> Baseline:
    """Read a baseline file into counts. A missing file is an empty baseline (suppresses
    nothing); a malformed one raises `BaselineError` so a corrupt baseline fails loudly rather
    than silently letting every diagnostic through as new."""
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return Baseline(Counter())
    except OSError as exc:
        raise BaselineError(f"{path}: {exc}") from exc
    try:
        data = json.loads(raw)
        entries = data["entries"]
        counts: Counter[Key] = Counter()
        for entry in entries:
            key = (entry["file"], entry["code"], entry["message"])
            counts[key] += int(entry.get("count", 1))
    except (ValueError, KeyError, TypeError) as exc:
        raise BaselineError(f"{path}: not a valid baseline file ({exc})") from exc
    return Baseline(counts)


def write_baseline(path: Path, diagnostics: list[Diagnostic], root: Path | None) -> int:
    """Record `diagnostics` as the new baseline at `path`, collapsing identical ones to a
    count. Returns the number of distinct entries written. Entries are sorted (file, code,
    message) so the file diffs cleanly when it is regenerated."""
    counts: Counter[Key] = Counter(diagnostic_key(diag, root) for diag in diagnostics)
    entries = [
        {"file": file, "code": code, "message": message, "count": count}
        for (file, code, message), count in sorted(counts.items())
    ]
    document = {
        "version": BASELINE_VERSION,
        "total": sum(counts.values()),
        "entries": entries,
    }
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    return len(entries)
