# Edain Linter - desktop window

A point-and-click PyQt6 window that runs **both** linters an Edain modder needs, over one
shared game-data panel, for people who would rather not use a command line:

- **Mod (ini)** tab - point at the mod folder and get the findings `sage-lint` would report.
- **Maps** tab - add a maps folder (or individual `.map` files, or drag and drop them onto the
  window) and get the findings `sage-edain lint-maps` would report.

Both tabs resolve references against the same **GAME DATA** sources (base game first, then the
mod) and show their results in the same searchable, sortable table.

Built on the shared `sage_utils` building blocks (cards, the background `Worker`, `run_app`,
bundled-resource lookup, the shared dark/light **theme**, and the shared `FindingsView` results
table the standalone SAGE Lint window also uses). The checks run in-process on a worker thread
and are exactly the ones the command line runs - the ini rules via the `sage_lint` CLI, and the
game-resolved dangling-reference checks plus the Edain mapping conventions (the MAP-xxx codes)
via [runner.py](runner.py). Nothing about *what* gets reported is reimplemented. Unlike one CLI
run per file, the game data is loaded once per Check.

## Layout

- [app.py](app.py) - entry point; boots the shared `QApplication` via `sage_utils.run_app`.
- [window.py](window.py) - the `EdainLinterWindow` (`QMainWindow`): the shared sources panel,
  the two tabs, and their `FindingsView` result tables.
- [runner.py](runner.py) - Qt-free: crawls the targets for maps, loads the game once, lints
  every map, returns the CLI-shaped JSON report. (The ini tab drives `sage_lint`'s own runner.)

## Run it

Needs `PyQt6` and the map layer, via the `edain-ui` extra - `pip install "pysage-tools[edain-ui]"`,
or `pip install -e .[edain-ui]` from a checkout:

```
sage-edain-lint                      # or, from a checkout:
python -m sage_mods.edain.map_checks.ui
```

or, once installed, `sage-edain-lint`.

## Options

**Shared**

- **Game data (optional)** - the game and mod folders / `.big` archives, loaded top to bottom
  (base game first, then the mod; reorder with the ↑/↓ buttons). The ini tab layers them as
  `--base` so references into them resolve instead of showing up as dangling; the Maps tab
  resolves each map's placed objects, upgrades and sciences against them. Remembered for the
  next launch. A `.sagelint` in the mod folder (or beside the `.exe`) fills this in for you.

**Mod (ini) tab**

- **Mod folder** - the folder of `.ini` files to check (everything under it). Required.
- **Baseline (optional)** - a baseline of already-accepted diagnostics, so only new findings
  are reported. Baselines found under the mod are merged automatically.
- **Show** / **Suggest fixes for typos** / **Auto-fix safe issues** - as in SAGE Lint.
- **Format** - reprint the ini files in the canonical style (rewrites files, and confirms first).

**Maps tab**

- **Maps to check** - folders (searched recursively for `.map` files) and/or individual map
  files. You can also drag and drop maps or folders anywhere on the window. Required.
- **Show** - the lowest severity to list: ERROR, WARNING or INFO.

## The results table

- **Search** - filter to rows containing the text (any column).
- **Sort** - click a column heading; severity sorts errors-first.
- **Open** - double-click a row to open that file with whatever your OS associates with it (an
  editor for an `.ini`, Worldbuilder for a `.map`), falling back to its folder.
- **Export CSV…** - save the currently shown rows to a file.
- **Theme** - the dark/light toggle (top right) is the shared `sage_utils` theme; the choice
  is remembered and applies to the other SAGE apps too.

## Build a standalone .exe (no Python on the modder's machine)

```
pip install -e .[edain-ui]
pyinstaller sage_mods/edain/sage-edain.spec
```

This produces `dist/Edain Linter.exe` - a single file you can hand to a modder - alongside the
console `sage_edain` CLI binary the same spec builds (every `sage-edain` subcommand,
`lint-maps` included). The window icon ([icon.ico](icon.ico)) is bundled and set on the exe.
Dropping it into a mod folder that has a `.sagelint` makes it ready to Check on launch.

## Credits

Icon art by Ludovic Bourgeois-Lefèvre -
<https://ludovicbourgeoislefevre.artstation.com/projects/2xL1WJ>.
