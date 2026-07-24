# SAGE Lint plugin - developing

Build, package, and internals for the Sublime Text plugin. End-user docs (install, settings,
commands) live in [README.md](README.md), which is the copy that ships inside the package.

## Layout

```
sage_lint/plugins/sublime/
  sage_lint.py                 # the plugin
  .python-version              # "3.8" - pins Sublime's plugin host (see below); ships in the package
  Default.sublime-commands     # Command Palette entries
  Context.sublime-menu         # right-click menu
  Default (*).sublime-keymap   # per-platform key bindings
  SageLint.sublime-syntax      # generated - see "Regenerating the syntax"
  SageLint.sublime-settings    # default editor settings
  generate_syntax.py           # regenerates SageLint.sublime-syntax from sage_ini
  install.sh / install.bat     # dev install into your Packages folder
  build_package.bat            # freezes a standalone binary and stages/zips the package
```

### The `.python-version` pin (do not remove)

Sublime Text 4 runs packages under the legacy Python 3.3 plugin host unless a `.python-version`
file in the package selects otherwise. `sage_lint.py` uses f-strings and other 3.6+ syntax, so
it **must** load under the 3.8 host: the `.python-version` file (contents: `3.8`) makes that
happen. Without it the plugin fails to import with a `SyntaxError` and no commands register.
It must ship inside the installed package folder - `install.*` and `build_package.bat` copy it.

## Dev install (from a checkout)

Run `bash install.sh` (or `install.bat` on Windows) from this folder. It syntax-checks the
plugin, copies it into Sublime's `Packages/SageLint`, and - on first install only - writes
`SageLint.sublime-settings` with `linter_cwd` pre-filled to this checkout.

- `SUBLIME_PACKAGES=/path/to/Packages` - override the destination. **Set this if your
  Packages folder isn't the default:** a Sublime Text 4 upgraded in place from ST3 loads from
  `…\AppData\Roaming\Sublime Text 3\Packages`, not `…\Sublime Text\Packages`. Use
  `Preferences > Browse Packages...` in Sublime to see the real path.
- `PYTHON=...` - interpreter used for the syntax check.

You will usually also want to set `python` in the settings to the interpreter that has
`sage_ini` installed.

## Standalone package (no Python, no checkout)

The dev install needs Python and the `ini_parser` checkout on the machine. To hand the plugin
to someone who has neither, **bundle a standalone `sage_lint` binary** in the package. The
plugin auto-detects it: if a binary is present in `bin/` it runs that (one binary serves every
command, `serve` daemon included) and ignores `python` / `linter_cwd`; otherwise it falls back
to `python -m sage_lint` from the checkout, so a dev checkout keeps working.

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
     .python-version               # contains "3.8" - ships with the package, do not drop it
     bin/sage_lint(.exe)            # one binary, the host's OS
   ```

   To ship all platforms in one package, use per-OS subfolders instead - `bin/win32/`,
   `bin/darwin/`, `bin/linux/` - the plugin checks both `bin/<name>` and `bin/<platform>/<name>`.

3. **Distribute.** Give the recipient the whole `SageLint/` folder; they install it with the
   **Install** steps in [README.md](README.md) - drop it as `Packages\SageLint\` (a direct
   child of `Packages`, *not* inside `User`), keep the `.python-version` file, restart Sublime.
   No Python, no checkout, no settings - the project's `.sagelint` is still read from the
   linted folder at runtime as usual. Do **not** hand them a zipped `.sublime-package` for a
   bundled-binary build: Sublime won't extract it, so the binary won't be found (see the note
   above). The `.no-sublime-package` marker only takes effect for installs done through Package
   Control.

Notes: each binary bundles Python + `sage_ini` (~15–40 MB). One-shot commands (format/fix)
spawn the binary per call (~0.1–0.3 s cold start); the `serve` daemon is long-lived, so it
pays that startup only once per project.

## Regenerating the syntax

`SageLint.sublime-syntax` is generated, not hand-edited: its keyword lists come from
`sage_ini`'s class registry - the same source the parser uses - so they stay complete as the
model grows. Regenerate it with:

```
python sage_lint/plugins/sublime/generate_syntax.py
```

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
(see **Project config** in the README); the daemon reads them from `<folder>/.sagelint`, and
its `root` key can scope the build to a subfolder. The cache is rebuilt on the initial build
and on **Lint Folder** - a brand new definition is only visible to other files after a rebuild.

The `--file` mode parses one file plus its includes instead of assembling the whole folder,
which is what keeps saves and on-idle linting fast. Two trade-offs follow from it:

- References to definitions in **other** files cannot resolve in `--file` mode, so a
  cross-file reference may briefly show as an error until the next full **Lint Folder** run.
  Setting `base` removes most of this noise for references into the base game.
- On-idle linting of an **unsaved** buffer is done by writing the buffer to a short-lived
  temp file beside the real one (so relative `#include`s resolve the same way) and linting
  that; the temp file is removed immediately after.

`sage_lint` diagnostics are line-level (spans carry no column), so highlighting is per-line
rather than per-column.
