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
  stays quiet. Pick it from the syntax menu (bottom-right, or `View > Syntax > Sage Lint`);
  it keeps the conventional `source.ini` scope, so the package's key bindings and any colour
  scheme apply unchanged.
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

You have been handed a `SageLint` folder. To install it:

1. In Sublime: `Preferences > Browse Packages...`.
2. Move the whole `SageLint` folder into the folder that opens. It must sit directly there
   as `Packages\SageLint\` - **not** inside the `User` folder.
3. Restart Sublime Text.

Done - the `SAGE Lint` commands are now in the Command Palette. Open your mod folder and run
**SAGE Lint: Lint Folder** to start.

> If the folder has a `bin/` with a `sage_lint` binary inside, that's everything you need.
> Otherwise the plugin runs `sage_lint` through Python - open
> `SageLint\SageLint.sublime-settings` and set `python` and `linter_cwd` (see **Settings**).

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

---

Building, packaging, or hacking on the plugin itself? See [DEVELOPING.md](DEVELOPING.md).
