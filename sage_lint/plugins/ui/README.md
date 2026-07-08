# SAGE Lint — desktop window

A point-and-click PyQt6 window over `sage_lint lint`, for teammates who would rather not use
a command line. Pick a mod folder, set a couple of options, press **Check**, and browse the
errors and warnings in a searchable, sortable table.

Built in the same style as `sage_ui` and `sage_wiki`, on the shared `sage_utils` building
blocks (cards, the background `Worker`, `run_app`, bundled-resource lookup, and the shared
dark/light **theme**). The lint itself runs the CLI in-process on a worker thread (see
[runner.py](runner.py)), so it reads the same `.sagelint` config, baseline, severity rules and
sorting as the CLI and the Sublime plugin — nothing about *what* gets reported is reimplemented.

## Layout

- [app.py](app.py) — entry point; boots the shared `QApplication` via `sage_utils.run_app`.
- [window.py](window.py) — the `LintWindow` (`QMainWindow`): options, the results table, search.
- [runner.py](runner.py) — Qt-free: builds the lint argv, runs the CLI, returns the JSON report.

## Run it

From the checkout (needs `PyQt6` — `pip install -e .[lint-ui]`):

```
python -m sage_lint.plugins.ui
```

## Project config (`.sagelint`)

**On launch**, if a `.sagelint` (or `.sagelint.local`) sits in the same folder as the app —
beside the `.exe` when packaged, else the working directory — that folder is selected and its
config loaded automatically. So a teammate can drop `SAGE Lint.exe` into their mod folder, run
it, and just press Check.

When you pick a mod folder, the window reads that folder's `.sagelint` (overlaid with
`.sagelint.local`) and reflects it in the options:

- **Show** level and **Suggest fixes** are set from the config.
- **Base game** is filled with the config's `base` source(s), resolved to absolute paths
  (several are shown `;`-separated).
- **Baseline** — every baseline file (`*.baseline`) anywhere under the mod is found and merged
  on Check, so a baseline kept in a subfolder (e.g. `_mod/.sagelint.baseline`) is picked up.
  Each is re-rooted to the lint root (a baseline at `_mod/` has its paths prefixed with `_mod/`),
  on the convention that a baseline sits at the root it was generated against. The field shows
  what was found; type or **Browse** your own to use a single baseline instead.
- `ignore` / `select` / `exclude` are applied to the check by the CLI itself.

The status bar reports whether a config was found and loaded.

## Options

- **Mod folder** — the folder of `.ini` files to check. Required.
- **Base game (optional)** — your unmodified base-game folder; references into it then resolve
  instead of showing up as dangling. (Mirrors `--base`.)
- **Baseline (optional)** — a baseline file of already-accepted diagnostics; matching ones are
  suppressed so only *new* problems are listed. (Mirrors `--baseline`.)
- **Show** — the lowest severity to list: ERROR, WARNING or INFO.
- **Suggest fixes for typos** — "Did you mean …?" hints on unknown names (slower).
- **Auto-fix safe issues** — rewrites files to fix the safe casing/duplicate problems (`--fix`).
- **Format** — reformats the mod's ini files to the canonical style (`sage_lint format`),
  aligning `=` into columns when the project's `.sagelint` sets `align_equals`. Rewrites files
  on disk, so it confirms first.

## The results table

- **Search** — filter to rows containing the text (any column).
- **Sort** — click a column heading; severity sorts errors-first, line numerically.
- **Open** — double-click a row to open that file in your default editor.
- **Export CSV…** — save the currently shown rows to a file.
- **Theme** — the dark/light toggle (top right) is the shared `sage_utils` theme; the choice is
  remembered and applies to the other SAGE apps too.

## Build a standalone .exe (no Python on the teammate's machine)

```
pip install -e .[lint-ui]
pyinstaller sage_lint/sage-lint-ui.spec
```

This produces `dist/SAGE Lint.exe` — a single file you can hand to a teammate. The window icon
([icon.ico](icon.ico)) is bundled and set on the exe.

## Credits

Icon art by Ludovic Bourgeois-Lefèvre —
<https://ludovicbourgeoislefevre.artstation.com/projects/2xL1WJ>.
