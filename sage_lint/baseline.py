"""A baseline of accepted diagnostics, so a noisy existing project can adopt the linter
without first fixing everything: record today's problems once, then report only what is
*new* against that record. The pre-existing set is suppressed (and the run exits clean),
which lets the linter go into CI immediately while the backlog is burned down over time.

A baseline entry is keyed by `(file, identity)` - never a line number, and never the prose
message - with an occurrence count. `identity` is the diagnostic's `code` plus the
*identifying* subset of its structured `extra` facts: the names and locations the problem is
about (which object, which field, which referenced symbol), with measured state left out (see
`INCIDENTAL_EXTRA`). That way editing a file, partially fixing a problem, or rewording a rule's
message all leave the accepted set matched. The count is still honoured: if a file held two of
some problem and now holds three, the third is reported as new. File paths are stored relative
to the lint root with forward slashes, so the baseline is portable across machines and
checkouts.

Diagnostics that carry no `extra` at all (some parser-level ones) fall back to identifying on
their message, which for those is a fixed string or a single interpolated name.

The file is JSON (machine-written, human-diffable): a sorted list of entries, each
`{file, code, id, message, count}`. Only `file`, `code` and `id` are matched on - `message` is
carried so the file can be reviewed and diffed by a human. Generate or refresh it with
`lint --write-baseline`.
"""

import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from sage_ini.parser.diagnostics import Diagnostic

BASELINE_VERSION = 2
# The conventional name, looked for beside `.sagelint` when no path is given explicitly.
BASELINE_NAME = ".sagelint.baseline"

# `extra` keys that record a diagnostic's measured state rather than what it is about: a line
# number, how many times something repeats, the offending magnitude, a schema bound, or the
# opt-in `--suggest` fuzzy match. All of them move when the file around them is edited (or, for
# `suggestion`, when the run is configured differently), while the problem stays the same one -
# so folding them into the identity would resurface accepted entries on an unrelated edit, and
# would punish a partial fix by re-reporting the remainder as new.
#
# This is a denylist, not an allowlist, so a rule that adds an unlisted key gets a *narrower*
# identity: a new key can only split one baseline entry into two (over-reporting, visible and
# fixed by regenerating), never merge two distinct problems into one (under-reporting, silent).
INCIDENTAL_EXTRA = frozenset(
    {
        "count",  # repeat count / CommandRangeCount
        "crashes",  # derived from the overflow magnitude
        "duration",  # ModifierList lifetime being compared
        "fx_duration",  # the FX lifetime it is compared against
        "highest_slot",  # derived from start + count
        "maximum",  # schema bound, not a fact about the file
        "minimum",
        "previous",  # the preceding respawn entry's level
        "ranks",  # which ranks are currently registered
        "second_line",  # line the duplicate definition sits on
        "slots",  # which slots a button is currently wired into
        "start",  # CommandRangeStart
        "suggestion",  # --suggest fuzzy match, absent unless suggestions are on
        "value",  # the offending value itself
    }
)

# A diagnostic identity that survives edits: its file (root-relative) and a canonical rendering
# of `(code, identifying facts)`.
Key = tuple[str, str]


class BaselineError(Exception):
    """A baseline file that exists but could not be read as a valid baseline."""


def resolved_root(root: Path | None) -> Path | None:
    """`root` made absolute, which is what the diagnostic file paths it is compared against
    always are. The CLI passes the positional root through as the user typed it, so without
    this a run invoked with a relative root (`lint data/ini`) would match nothing against a
    baseline and record absolute, machine-specific paths. Resolved once per run rather than
    per diagnostic, since it touches the filesystem."""
    if root is None:
        return None
    try:
        return root.resolve()
    except OSError:
        return None


def relative_file(file: str, root: Path | None) -> str:
    """The diagnostic's file as stored in a baseline: relative to `root` (already absolute, see
    `resolved_root`) with forward slashes when it sits under it, else the original string (a
    synthetic span like `<rules>`, or a path outside the tree, is kept verbatim). Portability
    hinges on this being checkout-independent."""
    if root is None:
        return file
    try:
        path = Path(file)
        if path.is_absolute() and path.is_relative_to(root):
            return path.relative_to(root).as_posix()
    except (OSError, ValueError):
        pass
    return file


def _jsonable(value: object) -> object:
    """`value` reduced to something JSON can round-trip unchanged, so the identity a written
    entry encodes is byte-identical to the one recomputed when it is read back."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (set, frozenset)):
        return sorted(str(item) for item in value)
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return str(value)


def identity(diag: Diagnostic) -> dict[str, object]:
    """The facts that say which problem this is: the diagnostic's `extra` minus the incidental
    keys. Diagnostics with no usable facts fall back to their message, which is the only thing
    distinguishing them."""
    facts = {
        key: _jsonable(value) for key, value in diag.extra.items() if key not in INCIDENTAL_EXTRA
    }
    return facts or {"message": diag.message}


def _fingerprint(code: str, facts: dict) -> str:
    """A canonical string for `(code, facts)`, so identities compare and hash as a unit
    regardless of the order the rule happened to build its `extra` in."""
    return json.dumps([code, facts], sort_keys=True, separators=(",", ":"))


def diagnostic_key(diag: Diagnostic, root: Path | None) -> Key:
    """The edit-insensitive identity a baseline matches on."""
    return (relative_file(diag.span.file, root), _fingerprint(diag.code, identity(diag)))


def entry_key(entry: dict) -> Key:
    """The identity of a stored entry - the same `Key` `diagnostic_key` builds for the
    diagnostics that entry accepts, so records can be matched and merged across baselines.
    Raises `KeyError`/`TypeError` on a record that is not shaped like an entry."""
    facts = entry["id"]
    if not isinstance(facts, dict):
        raise TypeError(f"'id' must be an object, got {type(facts).__name__}")
    return (entry["file"], _fingerprint(entry["code"], facts))


@dataclass
class Baseline:
    """A loaded baseline: the records as stored (for tools that re-emit them) and the counts
    matching uses - how many of each `(file, identity)` are accepted."""

    entries: list[dict]
    counts: Counter[Key]

    def partition(
        self, diagnostics: list[Diagnostic], root: Path | None
    ) -> tuple[list[Diagnostic], list[Diagnostic]]:
        """Split `diagnostics` into `(new, suppressed)`: each diagnostic whose key still has an
        unconsumed baseline allowance is suppressed, the rest are new. Input order is preserved,
        so which of several identical diagnostics counts as "new" is deterministic."""
        root = resolved_root(root)
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
        return Baseline([], Counter())
    except OSError as exc:
        raise BaselineError(f"{path}: {exc}") from exc
    try:
        data = json.loads(raw)
        version = data["version"]
        if version != BASELINE_VERSION:
            raise BaselineError(
                f"{path}: baseline format v{version} is not supported (expected "
                f"v{BASELINE_VERSION}); regenerate it with --write-baseline"
            )
        entries = list(data["entries"])
        counts: Counter[Key] = Counter()
        for entry in entries:
            counts[entry_key(entry)] += int(entry.get("count", 1))
    except (ValueError, KeyError, TypeError) as exc:
        raise BaselineError(f"{path}: not a valid baseline file ({exc})") from exc
    return Baseline(entries, counts)


def write_entries(path: Path, entries: list[dict]) -> int:
    """Write `entries` as the baseline document at `path`, returning how many were written."""
    document = {
        "version": BASELINE_VERSION,
        "total": sum(int(entry.get("count", 1)) for entry in entries),
        "entries": entries,
    }
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    return len(entries)


def write_baseline(path: Path, diagnostics: list[Diagnostic], root: Path | None) -> int:
    """Record `diagnostics` as the new baseline at `path`, collapsing ones with the same
    identity to a count. Returns the number of distinct entries written. Entries are sorted by
    key so the file diffs cleanly when it is regenerated."""
    root = resolved_root(root)
    counts: Counter[Key] = Counter()
    # The first diagnostic seen for a key supplies the entry's fields; every later one has the
    # same identity, so which of them it is only affects the human-readable `message`.
    first: dict[Key, Diagnostic] = {}
    for diag in diagnostics:
        key = diagnostic_key(diag, root)
        counts[key] += 1
        first.setdefault(key, diag)
    entries = [
        {
            "file": key[0],
            "code": first[key].code,
            "id": identity(first[key]),
            "message": first[key].message,
            "count": count,
        }
        for key, count in sorted(counts.items())
    ]
    return write_entries(path, entries)
