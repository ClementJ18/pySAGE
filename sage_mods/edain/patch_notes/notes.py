"""Turning the release spreadsheet's notes into the two BBcode forum posts.

Edain's patch notes are written in a spreadsheet and exported as CSV: one row per note, with the
faction(s) it belongs to, its English and German text, a beta flag, and - on the last row of each
batch - the date that batch was added. `render_notes` filters those rows (beta on or off, added
after a date or not), groups them by faction and formats each group as a BBcode `[list]`, giving
one post per language.

A batch is dated only once it is closed, so the newest work sits at the bottom of the sheet with
its Date cell still empty. Those undated rows are the *latest* notes, not the oldest, and every
filter keeps them: a release post must not quietly lose the work nobody has dated yet.

The note text carries two conventions the renderer expands:

* leading `-` characters set the nesting depth, so `--foo` is a sub-item of the note above it;
* `*text*`, `**text**` and `***text***` become `[i]`, `[b]` and `[b][i]` runs.

A note translated into only one language still appears in both posts, its missing side marked
`TRANSLATE ME` so it cannot be posted unnoticed.

Qt-free, so the desktop window in `ui/` and any script can share it.
"""

import csv
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime
from pathlib import Path

__all__ = [
    "COLUMNS",
    "DATE_FORMAT",
    "GERMAN_HEADERS",
    "PINNED_FACTIONS",
    "UNTRANSLATED",
    "Note",
    "PatchNotes",
    "apply_formatting",
    "batch_dates",
    "output_paths",
    "parse_notes",
    "read_notes",
    "render_notes",
    "write_notes",
]

# The columns each row is read from; anything else in the export is ignored.
COLUMNS = ("Faction", "English", "German", "Beta", "Date")

# How the spreadsheet writes a date (day first, as the sheet's authors type it).
DATE_FORMAT = "%d/%m/%Y"

# Factions that lead the post, in this order, whatever the alphabet says: the cross-faction
# changes first, then maps, then the AI. Compared lowercased against the sheet's own spelling.
PINNED_FACTIONS = ("general", "map", "ai")

# The German post's headings; a faction absent here keeps its English name.
GERMAN_HEADERS = {
    "General": "Völkerübergreifend",
    "Maps": "Karten",
    "AI": "KI",
    "Dwarves": "Zwerge",
    "Isengard": "Isengart",
    "Misty Mountains": "Nebelberge",
}

# Marks the side of a note that has not been translated yet, so it stands out in the post.
UNTRANSLATED = "TRANSLATE ME"

# The emphasis markers, longest first (see `apply_formatting`); each run is non-greedy so two
# emphasised words on one line stay two runs rather than one spanning the text between them.
_EMPHASIS = (
    (re.compile(r"\*\*\*(.+?)\*\*\*"), r"[b][i]\1[/i][/b]"),
    (re.compile(r"\*\*(.+?)\*\*"), r"[b]\1[/b]"),
    (re.compile(r"\*(.+?)\*"), r"[i]\1[/i]"),
)


@dataclass(frozen=True)
class Note:
    """One row of the sheet: the note's text in both languages and the batch it belongs to.
    `factions` holds every faction the row named (a row may list several, comma-separated), and
    `date` is the date of the batch - None for the rows of the open batch at the end of the
    sheet, which nobody has dated yet."""

    factions: tuple[str, ...]
    english: str
    german: str
    beta: bool
    date: date | None


@dataclass(frozen=True)
class PatchNotes:
    """The rendered posts: the BBcode for each language, the factions they cover in the order
    they appear, and how many notes survived the filters."""

    english: str
    german: str
    factions: tuple[str, ...]
    count: int


def apply_formatting(text: str) -> str:
    """The note's `*`-marked emphasis as BBcode tags: `***bold italic***`, `**bold**`, `*italic*`.
    Longest marker first, so the shorter ones cannot eat a `***` run's outer stars."""
    for pattern, tag in _EMPHASIS:
        text = pattern.sub(tag, text)
    return text


def parse_notes(rows: Iterable[Mapping[str, str]]) -> list[Note]:
    """The notes in `rows` (CSV records keyed by `COLUMNS`), oldest row first, as the sheet has
    them. Fully empty rows - the spacers between batches - are dropped.

    Only the last row of a batch carries its date, so dates are carried backwards over the rows
    above them. A missing column, or a date the sheet spells in some other way, leaves that field
    empty rather than failing the read; such a row keeps the date of the batch below it."""
    raw: list[tuple[Note, str]] = []
    for row in rows:
        faction = _cell(row, "Faction")
        english = _cell(row, "English")
        german = _cell(row, "German")
        if not faction and not english and not german:
            continue
        note = Note(
            factions=tuple(f.strip() for f in faction.split(",") if f.strip()),
            english=english,
            german=german,
            beta=_cell(row, "Beta").upper() == "TRUE",
            date=None,
        )
        raw.append((note, _cell(row, "Date")))

    notes: list[Note] = []
    batch: date | None = None
    for note, written in reversed(raw):
        if written:
            batch = _parse_date(written) or batch
        notes.append(replace(note, date=batch))
    notes.reverse()
    return notes


def read_notes(path: str | Path) -> list[Note]:
    """The notes in the CSV export at `path` (see `parse_notes`). Read as UTF-8, BOM tolerated -
    a spreadsheet's "CSV UTF-8" export writes one."""
    with Path(path).open(newline="", encoding="utf-8-sig") as handle:
        return parse_notes(csv.DictReader(handle))


def batch_dates(notes: Iterable[Note]) -> tuple[date, ...]:
    """Every date the sheet records a batch for, newest first - the only dates `after` can
    usefully take, since a day between two batches selects exactly what the older of them
    would. The open batch at the end of the sheet has no date to contribute; `render_notes`
    keeps it whatever date is chosen."""
    return tuple(sorted({note.date for note in notes if note.date is not None}, reverse=True))


def render_notes(
    notes: Iterable[Note], *, beta: bool = False, after: date | None = None
) -> PatchNotes:
    """The English and German posts for `notes`.

    Beta-only notes are left out unless `beta` is set, and `after` keeps only what came later
    than that date - the date names the batch already posted, so that batch is itself left out.
    Every undated note comes along regardless: it belongs to the open batch at the end of the
    sheet and is therefore newer than any date, not older. A note with only one language filled
    in is carried into both posts, the empty side marked `UNTRANSLATED`, so nothing silently goes
    missing from a post."""
    order: list[str] = []
    english: dict[str, list[str]] = {}
    german: dict[str, list[str]] = {}
    kept = 0

    for note in notes:
        if note.beta and not beta:
            continue
        if after is not None and note.date is not None and note.date <= after:
            continue
        kept += 1
        left = note.english or (f"{UNTRANSLATED} {note.german}" if note.german else "")
        right = note.german or (f"{UNTRANSLATED} {note.english}" if note.english else "")
        for faction in note.factions:
            if faction not in english:
                order.append(faction)
                english[faction] = []
                german[faction] = []
            if left:
                english[faction].append(apply_formatting(left))
            if right:
                german[faction].append(apply_formatting(right))

    factions = tuple(sorted(order, key=_faction_sort_key))
    return PatchNotes(
        english=_render_document(factions, english),
        german=_render_document(factions, german, headers=GERMAN_HEADERS),
        factions=factions,
        count=kept,
    )


def output_paths(folder: str | Path, base_name: str) -> tuple[Path, Path]:
    """Where the two posts are written for a sheet called `base_name`: one file per language,
    named after the sheet so a folder of releases stays sorted by it."""
    directory = Path(folder)
    return (
        directory / f"{base_name} - English.txt",
        directory / f"{base_name} - German.txt",
    )


def write_notes(result: PatchNotes, folder: str | Path, base_name: str) -> tuple[Path, Path]:
    """Write the rendered posts to `folder` (see `output_paths`) and return the two paths."""
    english_path, german_path = output_paths(folder, base_name)
    english_path.write_text(result.english, encoding="utf-8")
    german_path.write_text(result.german, encoding="utf-8")
    return english_path, german_path


def _cell(row: Mapping[str, str], column: str) -> str:
    value = row.get(column)
    return value.strip() if value else ""


def _parse_date(written: str) -> date | None:
    try:
        return datetime.strptime(written, DATE_FORMAT).date()
    except ValueError:
        return None


def _faction_sort_key(faction: str) -> tuple[int, int, str]:
    lowered = faction.lower()
    if lowered in PINNED_FACTIONS:
        return (0, PINNED_FACTIONS.index(lowered), faction)
    return (1, 0, faction)


# One note in the tree: its text and the notes nested under it.
_Node = tuple[str, list["_Node"]]


def _build_tree(entries: Sequence[str]) -> list[_Node]:
    """The flat notes of one faction as a nested tree, the leading `-` characters giving each
    note's depth. A note that jumps more than one level deeper than the one above it is attached
    at the deepest level that exists, so a miscounted `-` never loses the note."""
    root: list[_Node] = []
    # stack[i] is the list a note of depth i is appended to.
    stack: list[list[_Node]] = [root]
    for entry in entries:
        depth = len(entry) - len(entry.lstrip("-"))
        node: _Node = (entry[depth:].lstrip(), [])
        while len(stack) <= depth:
            stack.append(stack[-1])
        stack[depth].append(node)
        stack = stack[: depth + 1] + [node[1]]
    return root


def _render_tree(nodes: Sequence[_Node], lines: list[str]) -> None:
    for text, children in nodes:
        if not children:
            lines.append(f"[li]{text}[/li]")
            continue
        lines.append(f"[li]{text}")
        lines.append("[list]")
        _render_tree(children, lines)
        lines.append("[/list]")
        lines.append("[/li]")


def _render_document(
    factions: Sequence[str],
    by_faction: Mapping[str, Sequence[str]],
    headers: Mapping[str, str] | None = None,
) -> str:
    """One `[u]heading[/u]` + `[list]` block per faction that has notes, in `factions` order."""
    lines: list[str] = []
    for faction in factions:
        entries = by_faction.get(faction, ())
        if not entries:
            continue
        heading = headers.get(faction, faction) if headers else faction
        lines.append(f"[u]{heading}[/u]")
        lines.append("[list]")
        _render_tree(_build_tree(entries), lines)
        lines.append("[/list]")
        lines.append("")
    return ("\n".join(lines) + "\n") if lines else ""
