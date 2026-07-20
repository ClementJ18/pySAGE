# SAGE Lint - Sublime Text 4 plugin

**Version 0.2.0** - Lint and format SAGE-engine (BFME) ini files inline with `sage_lint`.

Lints SAGE `.ini` / `.inc` / `.bhav` files with `sage_lint` and shows the errors and
warnings inline in Sublime Text 4.

- Opening a project folder lints the whole folder and spreads each diagnostic onto the
  file and line it belongs to.
- Saving a file - or, with `lint_on_idle`, pausing while typing - re-lints **only that
  file**, so neither re-parses the whole folder. When a save adds or removes definitions
  (things sibling files may reference), a debounced folder rebuild follows automatically,
  so new names resolve everywhere and references to deleted ones re-flag without a manual
  **Lint Folder** (`auto_rebuild`). While a build is in flight, per-file lints wait for it
  and re-run against the fresh cache - never reported from stale state.
- Each diagnostic is drawn as a squiggly underline under the offending line, a gutter
  icon, and its message on a phantom line below the code, where it stays visible no matter
  how long the line is (`diagnostic_display` switches to right-aligned annotations or
  message-less; `phantom_scope: "caret-line"` shows only the caret line's message). The
  full message also appears in the status bar when the caret is on the line, and on hover
  together with the diagnostic code's description. A per-file `SAGE E:n W:m` counter sits
  in the status bar.
- Format the buffer in `sage_lint`'s canonical style on demand or on save, apply the
  auto-fixable diagnostics, and jump between issues - see Commands below.
- **Syntax highlighting** for SAGE ini. A `Sage Lint` syntax colours block headers, field
  keys, the module class after a `Behavior =` / `Body =` slot, numbers, booleans, strings,
  comments and `#` directives. Class names are only highlighted in value position, so words
  that double as class names (`Fire`, `Road`, `Color`) stay plain elsewhere - the colouring
  stays quiet. Its keyword lists are generated from `sage_ini`'s class registry - the same
  source the parser uses - so they stay complete as the model grows. Pick it from the syntax
  menu (bottom-right, or
  `View > Syntax > Sage Lint`); it keeps the conventional `source.ini` scope, so the
  package's key bindings and any colour scheme apply unchanged.
- **Navigate the game like a code base.** The same daemon that lints also serves a symbol
  index built from the real `sage_ini` parse - every definition with its source location and
  game table, the macro and string tables, and every block's typed field schema. From it you
  get Go to Definition, a symbol browser, per-file defined/referenced symbol lists, hover
  previews (macro values, field types, include targets) and context-aware autocomplete - all
  under the right-click **Sage Lint** menu and the Command Palette. No separate index to
  build: it refreshes with every folder lint.
- **Context-aware autocomplete.** Inside any block - a top-level `Object`/`Weapon`/`Armor`/
  `CommandSet`/`CommandButton`/`Upgrade`/… or a module slot - typing at the start of a line
  suggests that block's **attribute names**; the module class after a `Behavior =`/`Body =`
  slot is offered too. On the value side of a field, you get **its values**: an enum field
  suggests its members (static values), and a reference field suggests exactly the names of
  its target table (dynamic values - objects, weapons, command buttons, command sets, …),
  filtered to that kind so a wrong-kind name never appears.

## Install

Quickest: run `bash install.sh` from this folder. It syntax-checks the plugin, copies it
into Sublime's `Packages/SageLint`, and - on first install only - writes
`SageLint.sublime-settings` with `linter_cwd` pre-filled to this checkout. Override the
destination with `SUBLIME_PACKAGES=/path/to/Packages` and the interpreter with `PYTHON=...`.
You will usually still want to set `python` to the interpreter that has `sage_ini` installed.

Manual install:

1. In Sublime: `Preferences > Browse Packages...` to open the `Packages` directory.
2. Copy this `sublime` folder into it (rename it to e.g. `SageLint` if you like).
3. Open `Preferences > Package Settings`… or just edit `SageLint.sublime-settings` in the
   copied folder and set:
   - `python` - the interpreter that can run `python -m sage_lint` (a venv path is fine).
   - `linter_cwd` - the absolute path to your `ini_parser` checkout. This can be left
     empty only if you load the plugin from inside the checkout (e.g. via a symlink).

## Standalone package (no Python, no checkout)

The two installs above need Python and the `ini_parser` checkout on the machine. To hand the
plugin to a teammate who has neither, **bundle a standalone `sage_lint` binary** in the
package. The plugin auto-detects it: if a binary is present in `bin/` it runs that (one binary
serves every command, `serve` daemon included) and ignores `python` / `linter_cwd`; otherwise
it falls back to `python -m sage_lint` from the checkout, so a dev checkout keeps working.

### One step (Windows)

Run [build_package.bat](build_package.bat) - it freezes the binary, stages the plugin with it
in `bin/`, and zips a `.sublime-package`, all into `dist/` (needs PyInstaller:
`pip install -e .[lint-ui]`):

```
sage_lint\plugins\sublime\build_package.bat
```

Output: `dist\SageLint\` (drop into the `Packages` directory) and `dist\SageLint.sublime-package`.
Build once per OS - PyInstaller binaries aren't cross-platform.

**For a bundled binary, install the folder, not the zip.** Sublime never extracts a
`.sublime-package` to disk, so a binary inside one has no filesystem path and can't be
`exec`'d - the plugin would report "no sage_lint found" and fall back to `python -m sage_lint`.
The `.sublime-package` is only useful when installed **through Package Control**, which honors
the bundled `.no-sublime-package` marker and unpacks it into `Packages/SageLint` (giving the
binary a real path). A manual install must use the `dist\SageLint\` folder.

### By hand

1. **Build the binary** (needs PyInstaller - `pip install -e .[lint-ui]` brings it in), from
   the repo root:

   ```
   pyinstaller sage_lint/sage-lint.spec
   ```

   This produces `dist/sage_lint` (`dist/sage_lint.exe` on Windows), alongside the desktop
   `SAGE Lint` app the same spec builds (see plugins/ui/README.md). PyInstaller binaries are
   **not** cross-platform, so build once on each OS you support.

2. **Drop it into the package.** Put the binary in this folder's `bin/`:

   ```
   SageLint/
     sage_lint.py, *.sublime-*, SageLint.sublime-settings, README.md
     bin/sage_lint(.exe)            # one binary, the host's OS
   ```

   To ship all platforms in one package, use per-OS subfolders instead - `bin/win32/`,
   `bin/darwin/`, `bin/linux/` - the plugin checks both `bin/<name>` and `bin/<platform>/<name>`.

3. **Distribute.** Give the teammate the whole `SageLint/` folder to drop in
   `Preferences > Browse Packages…`. No Python, no checkout, no settings - the project's
   `.sagelint` is still read from the linted folder at runtime as usual. Do **not** hand them a
   zipped `.sublime-package` for a bundled-binary build: Sublime won't extract it, so the
   binary won't be found (see the note above). The `.no-sublime-package` marker in this folder
   only takes effect for installs done through Package Control.

Notes: each binary bundles Python + `sage_ini` (~15–40 MB). One-shot commands (format/fix)
spawn the binary per call (~0.1–0.3 s cold start); the `serve` daemon is long-lived, so it
pays that startup only once per project.

## Settings

These settings cover how the editor *runs* the linter. What the linter *reports* (severity
level, ignored codes, base-game sources) is project configuration - see **Project config**
below.

| Key              | Default                      | Meaning                                                  |
| ---------------- | ---------------------------- | -------------------------------------------------------- |
| `python`         | `"python"`                   | Interpreter used to run `sage_lint`.                     |
| `linter_cwd`     | `""` (auto-detect)           | The `ini_parser` checkout root to run from.              |
| `extensions`     | `[".ini", ".inc", ".bhav"]`  | File extensions that trigger linting.                    |
| `format_on_save` | `false`                      | Reformat the buffer to canonical style on every save.    |
| `lint_on_idle`   | `true`                       | Re-lint the live buffer shortly after you stop typing.   |
| `idle_delay_ms`  | `800`                        | Idle delay before an on-idle lint fires.                 |
| `diagnostic_display` | `"phantom"`              | Message placement: `"phantom"` (own line below the code), `"annotation"` (right-aligned inline), `"none"`. |
| `phantom_scope`  | `"all"`                      | Phantom messages on `"all"` lines, or `"caret-line"` only. |
| `auto_rebuild`   | `true`                       | Rebuild the folder cache when a save changes the definition set. |
| `rebuild_delay_ms` | `2500`                     | Debounce before such an automatic rebuild fires.         |

## Project config (`.sagelint`)

Lint *rules* live with the mod, not the editor, so the `sage_lint` CLI reads them from the
linted folder - which means the plugin, the command line and CI all behave identically.
Two TOML files, both optional, sitting in the folder you lint:

- **`.sagelint`** - shared rules, meant to be committed so everyone working on the mod
  lints the same way.
- **`.sagelint.local`** - machine-specific paths and personal overrides; **gitignore this
  one**. It overrides `.sagelint` per key.

```toml
# .sagelint  (committed)
level   = "WARNING"                         # ERROR | WARNING | INFO
ignore  = ["ignored-trailing-tokens"]       # codes never reported or auto-fixed
exclude = ["maps"]                          # directories kept out of the report
# root  = "data/ini"                        # folder to lint, relative to this file;
                                            # lets `sage_lint lint` run with no path
# select = ["repeated-field"]               # if set, report only these codes
```

```toml
# .sagelint.local  (gitignored)
base = ['C:/Games/BfME2']                   # base-game folder(s) or .big, for reference resolution
# level = "INFO"                            # e.g. a stricter personal level
```

Each key mirrors the matching CLI flag; a value may be a string or a list. Explicit CLI
flags still override the files, and `sage_lint lint --no-config` ignores them entirely.
Run `sage_lint lint --list-codes` to see the codes you can put in `ignore` / `select`.
`base` sources are built into the daemon's cache, so save/idle lints resolve against them
too (the cache is shared by the whole-folder report and every per-file re-lint).

## Commands

All under the Command Palette as **SAGE Lint: ...**

- **Lint Folder** - rebuild the daemon's whole-game cache and re-report. A daemon also
  starts automatically on load and builds the cache once.
- **Format File** - reprint the buffer in `sage_lint`'s canonical style.
- **Fix File / Fix Folder (auto-fixable)** - apply the auto-fixable diagnostics
  (`enum-case`, `reference-case`, `repeated-field`) in place, then re-lint.
- **Show Diagnostics (Project / Current File)** - a quick panel of issues; pick one to jump.
- **Next / Previous Diagnostic** - move the caret between issue lines in the current file.
- **Copy Message (Current Line)** - copy the diagnostic(s) on the caret's line to the
  clipboard as `path:line: [code] message`, ready to paste into a report.
- **Go to Definition** - jump to the definition of the symbol under the caret: an object,
  a macro, an `#include` target, or a string label (to its `.str` / `Lotr.csv` line). A
  string defined only in the base game has no location to jump to, so it shows its value.
- **Browse Symbols** - a searchable list of every indexed definition, macro and string;
  pick one to jump to it.
- **Show Module Documentation** - pop up the typed field schema of the block under the
  caret (a module, or a top-level block like `Object` / `Weapon` / `CommandSet`), with each
  field's type and, where known, its enum members or referenced table.
- **Symbols in File** - list the definitions and macros declared in the active file.
- **Referenced Symbols** - list the symbols defined elsewhere that the active file mentions;
  pick one to jump to its usage or its definition.
- **Edit Macro Values** - add / subtract / remove / list the `+token` / `-token` values of
  the `#define` on the current line, with indexed symbol names offered as candidates.
- **About** - show the plugin version and description.

**Go to Definition** and **Browse Symbols** sit at the top level of the right-click menu (as
`Sage Lint: …`); the rest are grouped under a **Sage Lint** submenu. They need the index,
which the daemon builds on load and refreshes on every folder lint - **Lint Folder** doubles
as a reindex. Until the first build finishes they report "index not ready".

## Default key bindings

| Binding (Win/Linux)      | macOS                   | Command                       |
| ------------------------ | ----------------------- | ----------------------------- |
| `ctrl+alt+l`             | `super+alt+l`           | Lint Folder                   |
| `ctrl+alt+d`             | `super+alt+d`           | Show Diagnostics (Project)    |
| `ctrl+alt+f`             | `super+alt+f`           | Format File                   |
| `ctrl+alt+x`             | `super+alt+x`           | Fix File (auto-fixable)       |
| `f8` / `shift+f8`        | `f8` / `shift+f8`       | Next / Previous Diagnostic    |

The per-file bindings (format, fix, next/prev) are scoped to `source.ini`, so they only
fire while editing an ini file. The bundled **Sage Lint** syntax uses that `source.ini`
scope for `.ini` / `.inc` / `.bhav`, so selecting it makes the bindings fire on all three;
if a file is highlighted by some other syntax with a different scope, use the Command
Palette or widen the binding's scope. Edit `Default (<platform>).sublime-keymap` in the
package to change them.

## How it maps to `sage_lint`

The plugin runs a long-lived **daemon** per project folder and shells out for the rest:

- Daemon: `python -m sage_lint serve <folder>` - builds the game once, then takes
  newline-delimited JSON commands on stdin (`lint_file` on save/idle, `rebuild` on
  Lint Folder, `index` after each build) and answers with `folder` / `file` / `index` JSON
  messages. This is what gives save-time lints full cross-file reference resolution at
  single-file speed, and the navigation commands a symbol index from the same parsed game.
- Format: `python -m sage_lint format --stdin --stdin-filename <file>`
- Fix: `python -m sage_lint lint ... --fix` (one-shot), then a daemon rebuild

The level, ignored codes, exclude dirs and base sources come from the project's `.sagelint`
(see **Project config**); the daemon reads them from `<folder>/.sagelint`, and its `root`
key can scope the build to a subfolder. The cache is rebuilt on the initial build and on
**Lint Folder** - a brand new definition is only visible to other files after a rebuild.

The `--file` mode parses one file plus its includes instead of assembling the whole
folder, which is what keeps saves and on-idle linting fast. Two trade-offs follow from it:

- References to definitions in **other** files cannot resolve in `--file` mode, so a
  cross-file reference may briefly show as an error until the next full **Lint Folder**
  run. Setting `base` removes most of this noise for references into the base game.
- On-idle linting of an **unsaved** buffer is done by writing the buffer to a short-lived
  temp file beside the real one (so relative `#include`s resolve the same way) and linting
  that; the temp file is removed immediately after.

`sage_lint` diagnostics are line-level (spans carry no column), so highlighting is
per-line rather than per-column.
