"""Edain patch notes: the release spreadsheet's CSV export turned into the two BBcode forum
posts, English and German.

`notes.py` holds the whole transform - read the rows, filter them (beta, added-since), group them
by faction and render each group as a nested `[list]`. `ui/` is a small PyQt6 window over it, for
the people writing the notes rather than the people running scripts.
"""

from sage_mods.edain.patch_notes.notes import (
    COLUMNS,
    DATE_FORMAT,
    GERMAN_HEADERS,
    PINNED_FACTIONS,
    UNTRANSLATED,
    Note,
    PatchNotes,
    apply_formatting,
    batch_dates,
    output_paths,
    parse_notes,
    read_notes,
    render_notes,
    write_notes,
)

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
