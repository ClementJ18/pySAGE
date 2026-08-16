# Edain Patch Notes - desktop window

A small PyQt6 window that turns the release spreadsheet into the two BBcode posts a release
needs - one English, one German - for the people writing the notes rather than the people
running scripts.

Point it at the sheet's `.csv` export (or drop the file on the window), tick whether beta-only
notes come along and - from the batch dates the sheet itself records, or All - which posted batch
to carry on from, then
press **Generate**: both posts appear in the preview
tabs, ready to copy into a forum post, and are written as `<sheet> - English.txt` /
`<sheet> - German.txt` beside the sheet. The sheet, output folder and filter choices come back on
the next launch.

Built on the shared `sage_utils` building blocks (cards, `run_app`, bundled-resource lookup, the
Help menu, and the shared dark/light **theme**). Nothing about *how* the notes are rendered lives
in the window: that is the Qt-free [`sage_mods.edain.patch_notes`](../notes.py), which a script
can call just as well.

## Layout

- [app.py](app.py) - entry point; boots the shared `QApplication` via `sage_utils.run_app`.
- [window.py](window.py) - the `PatchNotesWindow` (`QMainWindow`): the options card, the two
  preview tabs, and the settings it remembers.
- [../notes.py](../notes.py) - Qt-free: reads the CSV, filters, groups by faction and renders
  the BBcode.

## Run it

Needs `PyQt6`, via the `edain-ui` extra - `pip install "pysage-tools[edain-ui]"`, or
`pip install -e .[edain-ui]` from a checkout:

```
sage-edain-notes                     # or, from a checkout:
python -m sage_mods.edain.patch_notes.ui
```

For a teammate who has no Python, freeze it into a single windowed `Edain Patch Notes.exe` with
[`sage-edain-notes.spec`](../../sage-edain-notes.spec) (kept apart from `sage-edain.spec`, the
CLI + Edain Linter build, so this window can be rebuilt and handed over on its own):

```sh
pyinstaller sage_mods/edain/sage-edain-notes.spec   # -> dist/Edain Patch Notes.exe
python tools/build_release.py edain                 # or with every other Edain binary
```

## The sheet

One row per note. The columns read are **Faction**, **English**, **German**, **Beta** and
**Date**; anything else in the export is ignored, and fully empty rows (the spacers between
batches) are dropped.

- **Faction** - the heading the note goes under. Several, comma-separated, put the note under
  each. `General`, `Map` and `AI` lead the post; the rest follow alphabetically. The German post
  translates the headings it knows (`Dwarves` → `Zwerge`, …).
- **English** / **German** - the note. A row filled in for one language only still appears in
  both posts, its missing side marked `TRANSLATE ME`, so it cannot be posted unnoticed.
- **Beta** - `TRUE` for a note that only applies to the beta; left out unless **Include
  beta-only notes** is ticked.
- **Date** - `DD/MM/YYYY`, only on the *last* row of a batch: it applies to every row above it,
  up to the previous date. That is what **Only notes added since** filters on.

Inside a note, leading `-` characters set the nesting depth (`--foo` is a sub-item of the note
above it), and `*italic*`, `**bold**`, `***both***` become the matching BBcode tags.

## Options

- **Notes CSV** - the spreadsheet export. Required.
- **Output folder** - where the two `.txt` posts go. Empty means beside the CSV.
- **Include beta-only notes** - add the `Beta = TRUE` rows.
- **Notes added after** - how far back to go. The list holds **All** and then the batch dates the
  sheet itself records, spelled out in full (`2 February 2026`, so the day and the month cannot be
  read the wrong way round) and newest first, filled as soon as a CSV is chosen. Pick the batch
  you last posted: only what came after it is kept, that batch itself left out. **All** keeps
  every note, and is all a sheet without dates offers. The undated rows at the end of the sheet
  are the open batch - the newest work, waiting for the date that closes it - so they are kept
  whatever is chosen, rather than being read as older than every date and quietly dropped from
  the post.
- **Copy** - put the post shown in the current tab on the clipboard.
