"""Sublime Text 4 plugin: lint and format SAGE ini files with sage_lint, inline.

Each project folder gets a long-lived `sage_lint serve` daemon: it assembles the whole game
once, reports it, then re-lints individual files against that cache on save (or, with
`lint_on_idle`, while typing) in milliseconds — so cross-file references resolve without
re-parsing the folder every keystroke. Diagnostics are line-level (sage_lint spans carry no
column), so each is drawn as a squiggly underline under the offending line, a gutter icon,
and an inline annotation; the full message also shows in the status bar when the caret is on
the line, and on hover with the code's description.

The cache refreshes on the initial build and on **Lint Folder** (a daemon rebuild); a brand
new definition added since the last build is only seen by sibling files after a rebuild.

The same daemon also serves a **symbol index** from the assembled game (an `index` request
after every build): every definition with its source span, the macro and string tables, and
each module's typed field schema. That index — the real parse, not a separate regex pass —
backs Go to Definition, Browse Symbols, the per-file defined/referenced symbol lists, the
module-documentation popups, hover previews and name/module/field completions.

Commands (Command Palette, "SAGE Lint: ...", and the right-click "Sage Lint" submenu): Lint
Folder, Format File, Fix File / Fix Folder (auto-fixable diagnostics), Show Diagnostics, Next
/ Previous Diagnostic, Copy Message, Go to Definition, Browse Symbols, Show Module
Documentation, Symbols in File, Referenced Symbols, Edit Macro Values.

Install with the bundled `install.sh`, or copy this folder into Sublime's `Packages`
directory. Configure the interpreter and the checkout path in `SageLint.sublime-settings`
— see the README.
"""

import html
import json
import os
import re
import subprocess
import sys
import threading
import time

import sublime
import sublime_plugin

__version__ = "0.1.0"
__description__ = "Lint and format SAGE-engine (BFME) ini files inline with sage_lint."

SETTINGS_FILE = "SageLint.sublime-settings"

# One add_regions layer per severity, so a re-lint of one severity never wipes another.
REGION_KEYS = {
    "error": "sage_lint.error",
    "warning": "sage_lint.warning",
    "info": "sage_lint.info",
}
# scope drives the underline/gutter colour; annotation_color is the inline message colour.
SEVERITY_STYLE = {
    "error": ("region.redish", "circle", "#e05c4a"),
    "warning": ("region.yellowish", "dot", "#d8b44a"),
    "info": ("region.bluish", "dot", "#5a9bd8"),
}
SEVERITY_ORDER = {"error": 0, "warning": 1, "info": 2}
COUNT_STATUS = "sage_lint_counts"
CARET_STATUS = "sage_lint"

# Diagnostics keyed by normalised absolute file path -> list of diagnostic dicts as emitted
# by `sage_lint ... --output-format json`. The single source of truth the views render from.
_diagnostics = {}
# Per-view debounce token for lint-on-idle.
_pending_edits = {}
_code_desc_cache = None
_lock = threading.Lock()


def _log(message):
    """Print a one-line note to the Sublime console (View > Show Console) so each action
    leaves a trace — the status bar is transient, the console is a scrollback."""
    print("SAGE Lint: " + message)


def _settings():
    return sublime.load_settings(SETTINGS_FILE)


def _normcase(path):
    return os.path.normcase(os.path.normpath(os.path.abspath(path)))


def _python():
    return _settings().get("python", "python")


def _extensions():
    return tuple(_settings().get("extensions", [".ini", ".inc", ".bhav"]))


def _linter_cwd():
    """The directory `python -m sage_lint` must run from (the ini_parser checkout root).
    Taken from the setting, else inferred from this file's location when run in-place."""
    configured = _settings().get("linter_cwd", "")
    if configured:
        return configured
    # This file lives at <root>/sage_lint/plugins/sublime/sage_lint.py.
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
    if os.path.isdir(os.path.join(root, "sage_lint")):
        return root
    return None


def _is_lintable(file_name):
    return bool(file_name) and file_name.lower().endswith(_extensions())


def _project_root(window, file_name=None):
    """The window's first folder that contains `file_name` (or just the first folder)."""
    folders = window.folders() if window else []
    if file_name:
        normalised = _normcase(file_name)
        for folder in folders:
            if normalised.startswith(_normcase(folder) + os.sep):
                return folder
    return folders[0] if folders else None


# Shown when neither a bundled binary nor a runnable checkout can be found.
_NO_LINTER = (
    "no sage_lint found: ship a standalone binary in the package's bin/ folder, "
    "or set 'linter_cwd' in SageLint.sublime-settings to the ini_parser folder"
)


def _bundled_binary():
    """Path to a standalone `sage_lint` binary shipped inside the package, or None. This is
    what makes the package self-contained — no Python or checkout needed. Looked for beside
    this file as `bin/<name>` and `bin/<platform>/<name>`, so a package can carry one binary
    or one per OS (win32 / darwin / linux)."""
    name = "sage_lint.exe" if sys.platform == "win32" else "sage_lint"
    here = os.path.dirname(__file__)
    for candidate in (
        os.path.join(here, "bin", name),
        os.path.join(here, "bin", sys.platform, name),
    ):
        if os.path.isfile(candidate):
            return candidate
    return None


def _linter_command():
    """How to invoke sage_lint, as `(prefix, cwd)`. Prefers a bundled standalone binary (the
    package is then self-contained); otherwise falls back to `python -m sage_lint` run from
    the checkout. `cwd` matters only for the module fallback — the binary carries its own
    everything. Returns `(None, None)` when neither is available, so callers report `_NO_LINTER`."""
    binary = _bundled_binary()
    if binary is not None:
        return [binary], None
    cwd = _linter_cwd()
    if cwd is None:
        return None, None
    return [_python(), "-m", "sage_lint"], cwd


def _run_module(args, stdin_text=None, timeout=300):
    """Run sage_lint with `args` (bundled binary if present, else the checkout module). Returns
    (CompletedProcess, None) or (None, error_message). Runs off the main thread; never touches
    the Sublime API."""
    prefix, cwd = _linter_command()
    if prefix is None:
        return None, _NO_LINTER
    command = [*prefix, *args]
    creationflags = 0x08000000 if sys.platform == "win32" else 0  # CREATE_NO_WINDOW
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            input=stdin_text,
            capture_output=True,
            text=True,
            creationflags=creationflags,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, str(exc)
    return completed, None


def _run_lint_json(args):
    """Run a `lint` invocation and return its parsed JSON, or {"_error": ...}."""
    completed, error = _run_module(["lint", *args, "--output-format", "json"])
    if error:
        return {"_error": error}
    if not completed.stdout.strip():
        return {"_error": completed.stderr.strip() or "no output from sage_lint"}
    try:
        return sublime.decode_value(completed.stdout)
    except ValueError:
        return {"_error": completed.stderr.strip() or "could not parse sage_lint output"}


# One long-lived `sage_lint serve` daemon per project root builds the game once and then
# re-lints individual files against that cache in milliseconds, so cross-file references
# resolve without re-assembling the whole folder on every save. The plugin talks to it over
# newline-delimited JSON on stdin/stdout (see `_run_serve` in the CLI): a `folder` message
# after each build/rebuild, a `file` message per `lint_file` request.

_daemons = {}  # root key -> Popen
_daemon_lock = threading.Lock()


def _ensure_daemon(root):
    """The running daemon for `root`, started if needed. Returns (proc, started_now). The
    config in `<root>/.sagelint` may scope the build to a subfolder (its `root` key)."""
    key = _normcase(root)
    with _daemon_lock:
        proc = _daemons.get(key)
        if proc is not None and proc.poll() is None:
            return proc, False
        prefix, cwd = _linter_command()
        if prefix is None:
            _log(_NO_LINTER)
            return None, False
        creationflags = 0x08000000 if sys.platform == "win32" else 0  # CREATE_NO_WINDOW
        try:
            proc = subprocess.Popen(
                [*prefix, "serve", root],
                cwd=cwd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                creationflags=creationflags,
            )
        except OSError as exc:
            _log("daemon failed to start: " + str(exc))
            return None, False
        _daemons[key] = proc
        threading.Thread(target=_daemon_reader, args=(proc, key, root), daemon=True).start()
        threading.Thread(target=_daemon_stderr, args=(proc,), daemon=True).start()
        _log("daemon started for " + root)
        return proc, True


def _daemon_send(root, command):
    """Send one command to `root`'s daemon, starting it if needed. On a fresh start the
    initial folder build is already coming, so a redundant `rebuild` is dropped."""
    proc, started = _ensure_daemon(root)
    if proc is None:
        return
    if started and command.get("cmd") == "rebuild":
        return  # the initial build will emit the folder report
    try:
        proc.stdin.write(json.dumps(command) + "\n")
        proc.stdin.flush()
    except (OSError, ValueError) as exc:
        _log("daemon write failed: " + str(exc))


def _daemon_reader(proc, key, root):
    for line in proc.stdout:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except ValueError:
            continue
        sublime.set_timeout(lambda m=message: _on_daemon_message(root, m), 0)
    sublime.set_timeout(lambda: _on_daemon_exit(key, root), 0)


def _daemon_stderr(proc):
    for line in proc.stderr:
        line = line.strip()
        if line:
            sublime.set_timeout(lambda text=line: _log("daemon: " + text), 0)


def _on_daemon_exit(key, root):
    with _daemon_lock:
        proc = _daemons.get(key)
        if proc is not None and proc.poll() is not None:
            _daemons.pop(key, None)
    _log("daemon stopped for " + os.path.basename(root.rstrip(os.sep)))


def _shutdown_daemons():
    with _daemon_lock:
        procs = list(_daemons.values())
        _daemons.clear()
    for proc in procs:
        try:
            proc.stdin.write('{"cmd": "shutdown"}\n')
            proc.stdin.flush()
        except (OSError, ValueError):
            try:
                proc.terminate()
            except OSError:
                pass


# When each root's current build started (monotonic seconds), set on the daemon's `building`
# message and consumed by the matching `folder` report to time the whole-folder lint. Both
# handlers run on the main thread (via set_timeout), so no lock is needed.
_build_started = {}


def _on_daemon_message(root, message):
    kind = message.get("type")
    if kind == "building":
        _build_started[_normcase(root)] = time.monotonic()
        sublime.status_message("sage_lint: building " + os.path.basename(root.rstrip(os.sep)) + "…")
    elif kind == "folder":
        _apply_folder_message(root, message)
    elif kind == "index":
        _apply_index_message(message)
    elif kind == "file":
        _apply_file_message(message)
    elif kind == "error":
        _log("daemon error: " + message.get("message", "?"))
        sublime.status_message("sage_lint: " + message.get("message", "error"))


def _apply_folder_message(root, message):
    grouped = {}
    for diag in message.get("diagnostics", []):
        grouped.setdefault(_normcase(diag["file"]), []).append(diag)
    root_prefix = _normcase(root) + os.sep
    with _lock:
        # Replace every diagnostic under this root; files now clean are emptied.
        for path in [p for p in _diagnostics if p.startswith(root_prefix)]:
            _diagnostics[path] = []
        for path, diags in grouped.items():
            _diagnostics[path] = diags
    _render_all_views()
    # The cache the daemon just (re)built is the source for the symbol index too; pull it now
    # so Go to Definition and the other index features track the latest build.
    _daemon_send(root, {"cmd": "index"})
    summary = message.get("summary", {})
    errors, warnings = summary.get("errors", 0), summary.get("warnings", 0)
    started = _build_started.pop(_normcase(root), None)
    took = f" in {time.monotonic() - started:.1f}s" if started is not None else ""
    _log(f"folder lint done{took}: {errors} error(s), {warnings} warning(s)")
    sublime.status_message(f"sage_lint: {errors} error(s), {warnings} warning(s)")


def _apply_file_message(message):
    path = message.get("path")
    if not path:
        return
    if "error" in message:
        _log("lint file failed ({}): {}".format(os.path.basename(path), message["error"]))
        return
    key = _normcase(path)
    own = [d for d in message.get("diagnostics", []) if _normcase(d["file"]) == key]
    with _lock:
        _diagnostics[key] = own
    view = _view_for_path(path)
    if view is not None and view.is_valid():
        _render_view(view)


def _view_for_path(path):
    key = _normcase(path)
    for window in sublime.windows():
        for view in window.views():
            name = view.file_name()
            if name and _normcase(name) == key:
                return view
    return None


def _lint_folder_async(window, root):
    """Re-lint the whole folder: rebuild the daemon's cache (a fresh daemon builds once)."""
    _daemon_send(root, {"cmd": "rebuild"})


def _lint_file_async(view, root, file_name):
    """Re-lint a saved file against the daemon's cache (cross-file references resolve)."""
    _daemon_send(
        root or _project_root(view.window(), file_name),
        {
            "cmd": "lint_file",
            "path": file_name,
        },
    )


def _lint_buffer_async(view, root, file_name, content):
    """Re-lint the live (unsaved) buffer against the daemon's cache."""
    _daemon_send(
        root or _project_root(view.window(), file_name),
        {
            "cmd": "lint_file",
            "path": file_name,
            "content": content,
        },
    )


def _line_region(view, line_start):
    """The region to underline for a 1-based line: its text from the first non-whitespace
    character to the line end, so the squiggle tracks the content rather than the indent."""
    last_row, _ = view.rowcol(view.size())
    row = line_start - 1
    if row < 0 or row > last_row:
        return None
    point = view.text_point(row, 0)
    region = view.line(point)
    text = view.substr(region)
    indent = len(text) - len(text.lstrip())
    if region.a + indent >= region.b:
        return region  # blank or whitespace-only line: underline the whole line
    return sublime.Region(region.a + indent, region.b)


def _render_view(view):
    file_name = view.file_name()
    if not file_name:
        return
    diags = _diagnostics.get(_normcase(file_name), [])

    # Merge diagnostics that share a line+severity into one region, joining their messages,
    # so a single annotation sits at the end of the line instead of several overlapping ones.
    merged = {}  # (severity, line) -> [messages]
    errors = warnings = 0
    for diag in diags:
        severity = diag.get("severity", "error")
        if severity == "error":
            errors += 1
        elif severity == "warning":
            warnings += 1
        if severity not in REGION_KEYS:
            continue
        message = "[{}] {}".format(diag["code"], diag["message"])
        merged.setdefault((severity, diag["line_start"]), []).append(message)

    underline = sublime.DRAW_SQUIGGLY_UNDERLINE | sublime.DRAW_NO_FILL | sublime.DRAW_NO_OUTLINE
    for severity, region_key in REGION_KEYS.items():
        regions, annotations = [], []
        scope, icon, color = SEVERITY_STYLE[severity]
        for (sev, line), messages in merged.items():
            if sev != severity:
                continue
            region = _line_region(view, line)
            if region is None:
                continue
            regions.append(region)
            annotations.append("<body>{}</body>".format(html.escape(" | ".join(messages))))
        if regions:
            view.add_regions(
                region_key,
                regions,
                scope=scope,
                icon=icon,
                flags=underline,
                annotations=annotations,
                annotation_color=color,
            )
        else:
            view.erase_regions(region_key)

    if errors or warnings:
        view.set_status(COUNT_STATUS, f"SAGE E:{errors} W:{warnings}")
    else:
        view.erase_status(COUNT_STATUS)


def _render_all_views():
    for window in sublime.windows():
        for view in window.views():
            _render_view(view)


def _status_for_caret(view):
    """Show the diagnostics on the caret's line in the status bar."""
    file_name = view.file_name()
    if not file_name:
        return
    diags = _diagnostics.get(_normcase(file_name))
    if not diags:
        view.erase_status(CARET_STATUS)
        return
    caret_row = view.rowcol(view.sel()[0].b)[0] + 1 if view.sel() else 0
    here = [d for d in diags if d["line_start"] == caret_row]
    if here:
        view.set_status(
            CARET_STATUS,
            " | ".join("{}: {} [{}]".format(d["severity"], d["message"], d["code"]) for d in here),
        )
    else:
        view.erase_status(CARET_STATUS)


def _code_descriptions():
    """`code -> one-line description`, parsed from `lint --list-codes` and cached. The first
    call returns an empty dict and loads in the background, so it never blocks a hover."""
    global _code_desc_cache
    if _code_desc_cache is not None:
        return _code_desc_cache
    _code_desc_cache = {}  # mark loading so concurrent hovers do not respawn it

    def work():
        completed, error = _run_module(["lint", "--list-codes"])
        result = {}
        if not error and completed.returncode == 0:
            for line in completed.stdout.splitlines():
                match = re.match(r"^\s{4}(\S+)\s{2,}(.+)$", line)
                if match:
                    result[match.group(1)] = match.group(2).strip()

        def store():
            global _code_desc_cache
            _code_desc_cache = result

        sublime.set_timeout(store, 0)

    threading.Thread(target=work, daemon=True).start()
    return _code_desc_cache


# The daemon answers an `index` request with the assembled game's tables: every named
# definition with its source span, the macro and string tables, and each module's typed
# field schema, cached here (refreshed after every folder build) to power navigation and
# completion from the real parse rather than re-deriving them with regexes.

_index_lock = threading.Lock()
_definitions = {}  # lower-cased name -> list of {name, kind, file, line}
_macros = {}  # lower-cased name -> {name, value, file, line}
_strings = {}  # lower-cased name -> {name, value}
# Every modelled block class (top-level objects *and* module slots) -> {field: field_info},
# where field_info is {"type": label, optional "enum": [members], optional "ref": table key}.
# Backs field-name + value autocomplete, module documentation and field-type hovers.
_blocks = {}  # block class name (e.g. "Object", "Weapon", "AutoHealBehavior") -> {field: info}
_blocks_lower = {}  # lower-cased block class name -> canonical block class name
# The module classes valid after a `Behavior =`/`Body =`/… slot (a subset of `_blocks`), for
# module-name completion and telling a module slot apart from a top-level block header.
_module_slots = set()  # canonical module class names
_module_slots_lower = {}  # lower-cased module class name -> canonical
# Block classes opened by their name with the label as a key (`ModelConditionState = DAMAGED`),
# so a `Keyword = LABEL` header is told apart from a plain `Field = value` assignment.
_keyed_by_label_lower = {}  # lower-cased class name -> canonical
# Definition names grouped by their game table key (`obj.key`: "objects", "weapon", …), so a
# reference-typed field can offer exactly the names its target table holds.
_defs_by_table = {}  # table key -> sorted list of definition names
# Ordered include-resolution roots from the daemon (mod ini root, then any merged base game),
# so an `#include` resolves the way the linter does — base-game includes included by a mod file
# are found rather than reported missing. Empty until the first index arrives.
_include_roots = []

INCLUDE_RE = re.compile(r'#include\s+"([^"]+)"', re.I)
# A `key = value` line: a module slot (`Behavior = AutoHealBehavior Tag`) when the value token
# names a module class, otherwise a field assignment (`DamageType = SLASH`). The first group is
# the field/slot keyword, the second the value's first token.
MODULE_DECL_RE = re.compile(r"^\s*(\w+)\s*=\s*(\w+)", re.I)
# A block header in the plain `Keyword Name` form (`Object Hero`, `Weapon MyBow`, `CommandSet
# Foo`): the first token names the block class.
BLOCK_HEADER_RE = re.compile(r"^\s*(\w+)", re.I)
# Characters that make up a symbol name: words, the `NAMESPACE:key` colon of a string label,
# and the `+`/`-` a faction-prefixed name can carry.
_NAME_CHAR_RE = re.compile(r"[\w:+\-]")


def _apply_index_message(message):
    """Replace the cached index with the daemon's latest `index` report."""
    definitions = {}
    by_table = {}
    for entry in message.get("definitions", []):
        definitions.setdefault(entry["name"].lower(), []).append(entry)
        table = entry.get("table")
        if table:
            by_table.setdefault(table, []).append(entry["name"])
    macros = {
        name.lower(): {"name": name, **info} for name, info in message.get("macros", {}).items()
    }
    strings = {
        name.lower(): {"name": name, **info} for name, info in message.get("strings", {}).items()
    }
    blocks = message.get("blocks", {})
    module_slots = message.get("module_slots", [])
    keyed_by_label = message.get("keyed_by_label", [])
    include_roots = message.get("include_roots", [])
    with _index_lock:
        for cache, fresh in (
            (_definitions, definitions),
            (_macros, macros),
            (_strings, strings),
            (_blocks, blocks),
        ):
            cache.clear()
            cache.update(fresh)
        _blocks_lower.clear()
        _blocks_lower.update({name.lower(): name for name in blocks})
        _module_slots.clear()
        _module_slots.update(module_slots)
        _module_slots_lower.clear()
        _module_slots_lower.update({name.lower(): name for name in module_slots})
        _keyed_by_label_lower.clear()
        _keyed_by_label_lower.update({name.lower(): name for name in keyed_by_label})
        _defs_by_table.clear()
        _defs_by_table.update({table: sorted(names) for table, names in by_table.items()})
        _include_roots[:] = include_roots
    _log(
        f"index updated: {len(definitions)} symbol(s), {len(macros)} macro(s), "
        f"{len(strings)} string(s), {len(blocks)} block(s)"
    )


def _has_index():
    return bool(_definitions or _macros or _strings)


def _lookup_symbol(name):
    """`(category, payload)` for `name`, matched case-insensitively, where category is one of
    `definition` (payload: list of entries), `macro` or `string` (payload: one entry); or None
    when the name is not indexed."""
    key = name.lower()
    if key in _definitions:
        return "definition", _definitions[key]
    if key in _macros:
        return "macro", _macros[key]
    if key in _strings:
        return "string", _strings[key]
    return None


def _word_at(view, region):
    """The full symbol name under `region`, widened past Sublime's word boundaries to keep a
    `NAMESPACE:key` string label or a `+`/`-`-prefixed name in one piece."""
    word = view.word(region)
    begin, end = word.begin(), word.end()
    while begin > 0 and _NAME_CHAR_RE.match(view.substr(begin - 1)):
        begin -= 1
    while end < view.size() and _NAME_CHAR_RE.match(view.substr(end)):
        end += 1
    return view.substr(sublime.Region(begin, end)).strip()


def _block_decl(line):
    """The block class a line opens, mirroring the engine's `classify_subblock`:
    - a `=` line is a **module slot** when its value token names a module class
      (`Behavior = AutoHealBehavior …`), or a **keyed-by-label block** when its left keyword is
      a class typed by name with the label as key (`ModelConditionState = DAMAGED`);
    - a plain `Keyword Name` line is a **top-level/named block header** (`Object Hero`,
      `Weapon MyBow`) when its first token names a known block class.
    None when the line opens no modelled block (e.g. a plain `Field = value` assignment)."""
    if "=" in line:
        match = MODULE_DECL_RE.match(line)
        if not match:
            return None
        # The value token names the module class; failing that, the left keyword names a
        # keyed-by-label block (its label being the key, not a class).
        return _module_slots_lower.get(match.group(2).lower()) or _keyed_by_label_lower.get(
            match.group(1).lower()
        )
    match = BLOCK_HEADER_RE.match(line)
    return _blocks_lower.get(match.group(1).lower()) if match else None


def _enclosing_block(view, point):
    """The block class whose body contains `point` — a module slot or a top-level/named block —
    found by scanning upward to the nearest shallower-indented block opener (stopping at an `End`
    that closes a sibling block), or None when the caret is not inside a modelled block."""
    target = view.line(point)
    target_text = view.substr(target)
    target_indent = len(target_text) - len(target_text.lstrip())
    row = view.rowcol(target.begin())[0]
    while row >= 0:
        text = view.substr(view.line(view.text_point(row, 0)))
        indent = len(text) - len(text.lstrip())
        if indent < target_indent:
            if text.strip().lower() == "end":
                break
            decl = _block_decl(text)
            if decl:
                return decl
        row -= 1
    return None


def _open_location(window, file, line):
    window.open_file(f"{file}:{line}", sublime.ENCODED_POSITION)


def _is_within(path, base):
    """Whether `path` is `base` or nested under it (case-insensitively, as Windows paths are)."""
    path = os.path.normcase(os.path.abspath(path))
    base = os.path.normcase(os.path.abspath(base))
    return path == base or path.startswith(base + os.sep)


def _resolve_include(view, include_path):
    """Absolute path an `#include "..."` resolves to, mirroring the linter (sage_ini's
    `resolve_include`): when the including file sits under a known include root, anchor the
    target there and try every root — the mod's ini root *and* the merged base game — so a
    base-game-only include resolves; otherwise fall back to a path relative to the file. None
    only when the file is unsaved. Existence is the caller's to check."""
    current = view.file_name()
    if not current:
        return None
    current = os.path.abspath(current)
    source_dir = os.path.dirname(current)
    # The engine treats a leading slash as root-anchored-but-stripped; backslashes are separators.
    normalised = include_path.replace("\\", "/").lstrip("/")
    with _index_lock:
        roots = list(_include_roots)
    for layer in roots:
        if not _is_within(source_dir, layer):
            continue
        virtual_dir = os.path.relpath(source_dir, layer)
        relative = os.path.normpath(os.path.join(virtual_dir, normalised))
        for candidate_layer in roots:
            candidate = os.path.normpath(os.path.join(os.path.abspath(candidate_layer), relative))
            if os.path.isfile(candidate):
                return candidate
        # Anchored under a root but absent from every layer: report the mod-root guess as missing.
        return os.path.normpath(os.path.join(os.path.abspath(layer), relative))
    # No known root contains the file (or the index has not arrived): resolve against the file.
    return os.path.normpath(os.path.join(source_dir, normalised))


def _field_type_label(info):
    """The display type for a field_info dict (or a bare label string, for resilience). An
    enum/reference field shows what it expects — `enum: A | B | …` or `ref: <table>` — so the
    documentation popup hints what its value autocomplete will offer."""
    if not isinstance(info, dict):
        return str(info)
    if "enum" in info:
        members = info["enum"]
        shown = " | ".join(members[:6]) + (" | …" if len(members) > 6 else "")
        return f"enum: {shown}"
    if "ref" in info:
        return f"{info.get('type', 'ref')} → {info['ref']}"
    return info.get("type", "")


def _module_doc_html(name, fields):
    """An HTML popup body listing a block's fields and their types (the typed schema sage_ini
    converts against), styled to match the editor's colour variables."""
    rows = "".join(
        f'<div class="row"><span class="field">{html.escape(field)} </span>'
        f'<span class="type">{html.escape(_field_type_label(info))}</span></div>'
        for field, info in sorted(fields.items())
    )
    if not rows:
        rows = '<div class="none">No typed fields modelled for this block.</div>'
    style = (
        "h1 { color: var(--orangish); font-size: 1.1rem; margin: 0 0 0.4rem 0; }"
        ".count { color: var(--bluish); font-style: italic; margin-bottom: 0.5rem; }"
        ".field { color: var(--bluish); font-weight: bold; }"
        ".type { color: var(--greenish); margin-left: 1rem; }"
        ".row { padding: 1px 0; }"
        ".none { font-style: italic; }"
    )
    return (
        f"<body><style>{style}</style><h1>{html.escape(name)}</h1>"
        f'<div class="count">{len(fields)} field(s)</div>{rows}</body>'
    )


class SageLintAboutCommand(sublime_plugin.ApplicationCommand):
    """SAGE Lint: About — show the plugin version and description."""

    def run(self):
        _log(f"about (v{__version__})")
        sublime.message_dialog(f"SAGE Lint {__version__}\n\n{__description__}")


class SageLintFolderCommand(sublime_plugin.WindowCommand):
    """SAGE Lint: Lint Folder — re-lint the whole project folder."""

    def run(self):
        root = _project_root(self.window)
        if root is None:
            _log("lint folder: no project folder open")
            sublime.status_message("sage_lint: no project folder open")
            return
        _log("lint folder: " + root)
        sublime.status_message(f"sage_lint: linting {root}...")
        _lint_folder_async(self.window, root)

    def is_enabled(self):
        return bool(self.window.folders())


class SageLintFormatCommand(sublime_plugin.TextCommand):
    """SAGE Lint: Format File — reprint the buffer in sage_lint's canonical style."""

    def run(self, edit):
        view = self.view
        name = os.path.basename(view.file_name() or "<stdin>")
        _log("format file: " + name)
        content = view.substr(sublime.Region(0, view.size()))
        completed, error = _run_module(
            ["format", "--stdin", "--stdin-filename", view.file_name() or "<stdin>"],
            stdin_text=content,
            timeout=30,
        )
        if error:
            _log("format failed: " + error)
            sublime.status_message("sage_lint: " + error)
            return
        if completed.returncode == 0 and completed.stdout and completed.stdout != content:
            view.replace(edit, sublime.Region(0, view.size()), completed.stdout)
            _log("format done: reprinted " + name)
            sublime.status_message("sage_lint: formatted")
        elif completed.returncode != 0:
            note = (completed.stderr or "").strip().splitlines()
            reason = note[-1] if note else "format skipped"
            _log("format skipped: " + reason)
            sublime.status_message("sage_lint: " + reason)
        else:
            _log("format done: already formatted")
            sublime.status_message("sage_lint: already formatted")

    def is_enabled(self):
        return _is_lintable(self.view.file_name())


class SageLintFixCommand(sublime_plugin.WindowCommand):
    """SAGE Lint: Fix File / Fix Folder — apply the auto-fixable diagnostics in place."""

    def run(self, scope="file"):
        if scope == "file":
            view = self.window.active_view()
            if not view or not _is_lintable(view.file_name()):
                _log("fix file: no lintable file")
                sublime.status_message("sage_lint: no lintable file")
                return
            if view.is_dirty():
                view.run_command("save")  # --fix rewrites the file on disk
            file_name = view.file_name()
            root = _project_root(self.window, file_name)
            args = ([root] if root else []) + ["--file", file_name, "--fix"]
            _log("fix file: " + os.path.basename(file_name))
        else:
            root = _project_root(self.window)
            if not root:
                _log("fix folder: no project folder open")
                sublime.status_message("sage_lint: no project folder open")
                return
            file_name = None
            args = [root, "--fix"]
            _log("fix folder: " + root)

        sublime.status_message("sage_lint: fixing...")

        def work():
            result = _run_lint_json(args)
            sublime.set_timeout(lambda: self._done(result, root, file_name), 0)

        threading.Thread(target=work, daemon=True).start()

    def _done(self, result, root, file_name):
        if "_error" in result:
            _log("fix failed: " + result["_error"])
            sublime.status_message("sage_lint: " + result["_error"])
            return
        fixed = result.get("summary", {}).get("fixed", 0)
        _log(f"fix done: {fixed} issue(s) fixed")
        # Reload any open, unmodified views so the buffer reflects the rewritten file.
        root_prefix = _normcase(root) + os.sep
        for window in sublime.windows():
            for view in window.views():
                name = view.file_name()
                if not name or view.is_dirty():
                    continue
                if file_name is not None and _normcase(name) != _normcase(file_name):
                    continue
                if file_name is None and not _normcase(name).startswith(root_prefix):
                    continue
                view.run_command("revert")
        if file_name is not None:
            view = self.window.active_view()
            if view:
                _lint_file_async(view, root, file_name)
        else:
            _lint_folder_async(self.window, root)
        sublime.status_message(f"sage_lint: fixed {fixed} issue(s)")

    def is_enabled(self):
        return bool(self.window.folders())


class SageLintShowDiagnosticsCommand(sublime_plugin.WindowCommand):
    """SAGE Lint: Show Diagnostics — list issues in a quick panel; pick one to jump to it."""

    def run(self, current_file_only=False):
        active = self.window.active_view()
        only = None
        if current_file_only and active and active.file_name():
            only = _normcase(active.file_name())
        entries = []
        for path, diags in _diagnostics.items():
            if only and path != only:
                continue
            for diag in diags:
                entries.append((path, diag))
        entries.sort(
            key=lambda e: (e[0], e[1]["line_start"], SEVERITY_ORDER.get(e[1]["severity"], 9))
        )
        scope = "current file" if current_file_only else "all files"
        if not entries:
            _log(f"show diagnostics ({scope}): none")
            sublime.status_message("sage_lint: no diagnostics")
            return
        _log(f"show diagnostics ({scope}): {len(entries)} issue(s)")

        self._entries = entries
        items = [
            [
                "[{}] {} [{}]".format(d["severity"][0].upper(), d["message"], d["code"]),
                "{}:{}".format(os.path.basename(d["file"]), d["line_start"]),
            ]
            for _, d in entries
        ]
        self.window.show_quick_panel(items, self._on_done)

    def _on_done(self, index):
        if index < 0:
            return
        _, diag = self._entries[index]
        self.window.open_file(
            "{}:{}:1".format(diag["file"], diag["line_start"]), sublime.ENCODED_POSITION
        )

    def is_enabled(self):
        return bool(_diagnostics)


class SageLintGotoCommand(sublime_plugin.TextCommand):
    """SAGE Lint: Next / Previous Diagnostic — move the caret to the next issue line."""

    def run(self, edit, forward=True):
        view = self.view
        _log("goto {} diagnostic".format("next" if forward else "previous"))
        diags = _diagnostics.get(_normcase(view.file_name() or ""), [])
        if not diags:
            _log("goto: no diagnostics in this file")
            sublime.status_message("sage_lint: no diagnostics in this file")
            return
        rows = sorted({d["line_start"] for d in diags})
        current = view.rowcol(view.sel()[0].b)[0] + 1 if view.sel() else 1
        if forward:
            target = next((r for r in rows if r > current), rows[0])
        else:
            target = next((r for r in reversed(rows) if r < current), rows[-1])
        point = view.text_point(target - 1, 0)
        view.sel().clear()
        view.sel().add(sublime.Region(point, point))
        view.show_at_center(point)
        _status_for_caret(view)


class SageLintCopyMessageCommand(sublime_plugin.TextCommand):
    """SAGE Lint: Copy Message — copy the diagnostic(s) on the caret's line to the clipboard,
    each as `path:line: [code] message`, so it can be pasted into a report or jumped to."""

    def run(self, edit):
        view = self.view
        file_name = view.file_name()
        diags = _diagnostics.get(_normcase(file_name or ""), [])
        if not diags:
            sublime.status_message("sage_lint: no diagnostics in this file")
            return
        caret_row = view.rowcol(view.sel()[0].b)[0] + 1 if view.sel() else 0
        here = [d for d in diags if d["line_start"] == caret_row]
        if not here:
            sublime.status_message("sage_lint: no diagnostic on this line")
            return
        text = "\n".join(
            "{}:{}: [{}] {}".format(d["file"], d["line_start"], d["code"], d["message"])
            for d in here
        )
        sublime.set_clipboard(text)
        _log("copy message: " + text.replace("\n", " ⏎ "))
        sublime.status_message(
            f"sage_lint: copied {len(here)} message(s)"
            if len(here) > 1
            else "sage_lint: copied message"
        )

    def is_enabled(self):
        return bool(_diagnostics.get(_normcase(self.view.file_name() or "")))


# The index-powered navigation commands below read the symbol index the daemon serves. It is
# (re)built by a folder lint, so **Lint Folder** doubles as "reindex".


class SageLintGotoDefinitionCommand(sublime_plugin.TextCommand):
    """Sage Lint: Go to Definition — jump to the definition of the symbol under the caret
    (object, macro, `#include`, or string label), resolved against the indexed game. A string
    defined only in the base game has no recorded location, so its value is shown instead."""

    def run(self, edit):
        view = self.view
        sel = view.sel()[0]
        line_text = view.substr(view.line(sel))

        include = INCLUDE_RE.search(line_text)
        if include:
            self._open_include(include.group(1))
            return

        if not _has_index():
            sublime.status_message("sage_lint: index not ready — run Sage Lint: Lint Folder")
            return

        word = _word_at(view, sel)
        if not word:
            sublime.status_message("sage_lint: no symbol under the caret")
            return
        found = _lookup_symbol(word)
        if found is None and ":" in word:
            found = _lookup_symbol(word.replace(":", ""))
        if found is None:
            sublime.status_message(f"sage_lint: no definition for {word!r}")
            return

        category, payload = found
        if category == "definition":
            self._open_definitions(word, payload)
        elif category == "macro":
            self._open_macro(payload)
        else:
            self._open_string(payload)

    def _open_include(self, include_path):
        full = _resolve_include(self.view, include_path)
        if full is None:
            sublime.status_message("sage_lint: save the file to resolve its includes")
        elif os.path.exists(full):
            self.view.window().open_file(full)
            sublime.status_message("sage_lint: opened " + os.path.basename(full))
        else:
            sublime.status_message("sage_lint: include not found: " + full)

    def _open_definitions(self, word, entries):
        if len(entries) == 1:
            entry = entries[0]
            _open_location(self.view.window(), entry["file"], entry["line"])
            sublime.status_message("sage_lint: jumped to " + word)
            return
        items = [
            ["{} [{}]".format(e["name"], e["kind"]), "{}:{}".format(e["file"], e["line"])]
            for e in entries
        ]

        def on_done(index):
            if index >= 0:
                _open_location(self.view.window(), entries[index]["file"], entries[index]["line"])

        self.view.window().show_quick_panel(items, on_done)

    def _open_macro(self, payload):
        if payload.get("file"):
            _open_location(self.view.window(), payload["file"], payload["line"])
            sublime.status_message("sage_lint: jumped to " + payload["name"])
        else:
            sublime.status_message(
                "sage_lint: #define {} {}".format(payload["name"], payload["value"])
            )

    def _open_string(self, payload):
        # A mod-defined label carries its `.str`/`.csv` location; a base-game-only label does
        # not, so fall back to showing its value.
        if payload.get("file"):
            _open_location(self.view.window(), payload["file"], payload["line"])
            sublime.status_message("sage_lint: jumped to " + payload["name"])
        else:
            sublime.status_message("sage_lint: {} = {}".format(payload["name"], payload["value"]))


class SageLintBrowseSymbolsCommand(sublime_plugin.WindowCommand):
    """Sage Lint: Browse Symbols — a searchable list of every indexed definition, macro and
    string; pick one to jump to it (a base-game-only string, lacking a location, shows its
    value)."""

    def run(self):
        if not _has_index():
            sublime.status_message("sage_lint: index not ready — run Sage Lint: Lint Folder")
            return
        self._entries = []  # (display detail, file or None, line or None, status)
        with _index_lock:
            for entries in _definitions.values():
                for entry in entries:
                    self._entries.append(
                        (
                            ["{}  [{}]".format(entry["name"], entry["kind"]), entry["file"]],
                            entry["file"],
                            entry["line"],
                            None,
                        )
                    )
            for payload in _macros.values():
                self._entries.append(
                    (
                        ["{}  [macro]".format(payload["name"]), payload["value"]],
                        payload.get("file"),
                        payload.get("line"),
                        "#define {} {}".format(payload["name"], payload["value"]),
                    )
                )
            for payload in _strings.values():
                self._entries.append(
                    (
                        ["{}  [string]".format(payload["name"]), payload["value"]],
                        payload.get("file"),
                        payload.get("line"),
                        "{} = {}".format(payload["name"], payload["value"]),
                    )
                )
        self._entries.sort(key=lambda e: e[0][0].lower())
        self.window.show_quick_panel(
            [e[0] for e in self._entries], self._on_done, on_highlight=self._on_highlight
        )

    def _on_highlight(self, index):
        if 0 <= index < len(self._entries):
            _, file, line, _status = self._entries[index]
            if file is not None:
                self.window.open_file(
                    f"{file}:{line}", sublime.ENCODED_POSITION | sublime.TRANSIENT
                )

    def _on_done(self, index):
        if index < 0:
            return
        _, file, line, status = self._entries[index]
        if file is not None:
            _open_location(self.window, file, line)
        elif status:
            sublime.status_message("sage_lint: " + status)

    def is_enabled(self):
        return _has_index()


class SageLintModuleDocCommand(sublime_plugin.TextCommand):
    """Sage Lint: Show Module Documentation — pop up the typed field schema of the module
    named under the caret (or declared on the current `Behavior =`/`Body =`/… line)."""

    def run(self, edit):
        view = self.view
        sel = view.sel()[0]
        name = view.substr(sel).strip() if not sel.empty() else _word_at(view, sel)
        block = _blocks_lower.get((name or "").lower())
        if block is None:
            block = _block_decl(view.substr(view.line(sel)))
        if block is None:
            sublime.status_message(f"sage_lint: no block named {name!r}")
            return
        with _index_lock:
            fields = dict(_blocks.get(block, {}))
        view.show_popup(
            _module_doc_html(block, fields),
            flags=sublime.HIDE_ON_MOUSE_MOVE_AWAY | sublime.COOPERATE_WITH_AUTO_COMPLETE,
            location=-1,
            max_width=900,
            max_height=600,
        )
        sublime.status_message(f"sage_lint: {block} ({len(fields)} fields)")

    def is_visible(self):
        return _is_lintable(self.view.file_name()) or bool(_blocks)


class SageLintFileSymbolsCommand(sublime_plugin.WindowCommand):
    """Sage Lint: Symbols in File — list the definitions and macros declared in the active
    file; pick one to jump to it."""

    def run(self):
        view = self.window.active_view()
        current = view.file_name() if view else None
        if not current:
            sublime.status_message("sage_lint: no file open")
            return
        if not _has_index():
            sublime.status_message("sage_lint: index not ready — run Sage Lint: Lint Folder")
            return
        key = _normcase(current)
        self._entries = []
        with _index_lock:
            for entries in _definitions.values():
                for entry in entries:
                    if _normcase(entry["file"]) == key:
                        self._entries.append((entry["name"], entry["kind"], entry["line"]))
            for payload in _macros.values():
                if payload.get("file") and _normcase(payload["file"]) == key:
                    self._entries.append((payload["name"], "macro", payload["line"]))
        if not self._entries:
            sublime.status_message("sage_lint: no indexed symbols in this file")
            return
        self._entries.sort(key=lambda e: e[2])
        self._file = current
        items = [[f"{name}  [{kind}]", f"line {line}"] for name, kind, line in self._entries]
        self.window.show_quick_panel(items, self._on_done, on_highlight=self._on_highlight)

    def _on_highlight(self, index):
        if 0 <= index < len(self._entries):
            self.window.open_file(
                f"{self._file}:{self._entries[index][2]}",
                sublime.ENCODED_POSITION | sublime.TRANSIENT,
            )

    def _on_done(self, index):
        if index >= 0:
            _open_location(self.window, self._file, self._entries[index][2])

    def is_enabled(self):
        return _has_index()


class SageLintReferencedSymbolsCommand(sublime_plugin.WindowCommand):
    """Sage Lint: Referenced Symbols — list the symbols defined elsewhere that the active
    file mentions; pick one to jump to its usage or its definition."""

    def run(self):
        view = self.window.active_view()
        current = view.file_name() if view else None
        if not current:
            sublime.status_message("sage_lint: no file open")
            return
        if not _has_index():
            sublime.status_message("sage_lint: index not ready — run Sage Lint: Lint Folder")
            return
        key = _normcase(current)
        # Candidate external symbols: definitions (and located macros) not declared in this file.
        external = {}  # lower name -> (display name, kind, file, line)
        with _index_lock:
            for entries in _definitions.values():
                entry = entries[0]
                if all(_normcase(e["file"]) != key for e in entries):
                    external[entry["name"].lower()] = (
                        entry["name"],
                        entry["kind"],
                        entry["file"],
                        entry["line"],
                    )
            for payload in _macros.values():
                if payload.get("file") and _normcase(payload["file"]) != key:
                    external[payload["name"].lower()] = (
                        payload["name"],
                        "macro",
                        payload["file"],
                        payload["line"],
                    )

        lines = view.substr(sublime.Region(0, view.size())).split("\n")
        self._entries = []  # (name, kind, used_line, def_file, def_line)
        seen = set()
        for number, line in enumerate(lines, 1):
            stripped = line.strip()
            if not stripped or stripped[0] in ";/":
                continue
            for token in set(re.findall(r"[\w:+\-]+", line)):
                lowered = token.lower()
                if lowered in external and lowered not in seen:
                    name, kind, def_file, def_line = external[lowered]
                    self._entries.append((name, kind, number, def_file, def_line))
                    seen.add(lowered)
        if not self._entries:
            sublime.status_message("sage_lint: no external symbols referenced here")
            return
        self._entries.sort(key=lambda e: e[2])
        self._file = current
        items = [
            [
                f"{name}  [{kind}]",
                f"used line {used} → {os.path.basename(def_file)}:{def_line}",
            ]
            for name, kind, used, def_file, def_line in self._entries
        ]
        self.window.show_quick_panel(items, self._on_done, on_highlight=self._on_highlight)

    def _on_highlight(self, index):
        if 0 <= index < len(self._entries):
            self.window.open_file(
                f"{self._file}:{self._entries[index][2]}",
                sublime.ENCODED_POSITION | sublime.TRANSIENT,
            )

    def _on_done(self, index):
        if index < 0:
            return
        name, kind, used, def_file, def_line = self._entries[index]
        choices = [
            f"Go to usage (line {used})",
            f"Go to definition ({os.path.basename(def_file)}:{def_line})",
        ]

        def on_choice(choice):
            if choice == 0:
                _open_location(self.window, self._file, used)
            elif choice == 1:
                _open_location(self.window, def_file, def_line)

        self.window.show_quick_panel(choices, on_choice)

    def is_enabled(self):
        return _has_index()


class SageLintEditDefineCommand(sublime_plugin.TextCommand):
    """Sage Lint: Edit Macro Values — add, subtract, remove or list the `+token`/`-token`
    values of the `#define` on the current line. Add/subtract offer indexed symbol names as
    candidates (or free entry); edits rewrite the line in place."""

    _TOKENS_RE = re.compile(r"[+-]\S+")
    _DEFINE_RE = re.compile(r"#define\s+(\w+)\s+(.+)")

    def run(self, edit):
        region = self.view.line(self.view.sel()[0])
        match = self._DEFINE_RE.match(self.view.substr(region))
        if not match:
            sublime.status_message("sage_lint: caret must be on a #define line with values")
            return
        self.region = region
        self.macro_name = match.group(1)
        self.values = self._TOKENS_RE.findall(match.group(2))
        self.view.window().show_quick_panel(
            ["Add value", "Subtract value", "Remove value", "List values"], self._on_action
        )

    def _candidates(self):
        with _index_lock:
            names = {e["name"] for entries in _definitions.values() for e in entries}
            names.update(p["name"] for p in _macros.values())
        return sorted(names)

    def _on_action(self, index):
        if index in (0, 1):
            self._pick_to_add(subtract=index == 1)
        elif index == 2:
            self._pick_to_remove()
        elif index == 3:
            self.view.window().show_quick_panel(self.values or ["(no values)"], lambda _i: None)

    def _pick_to_add(self, subtract):
        sign = "-" if subtract else "+"
        items = [name for name in self._candidates() if sign + name not in self.values]
        items.append("[Enter manually]")

        def on_done(index):
            if index < 0:
                return
            if index == len(items) - 1:
                self.view.window().show_input_panel(
                    "Value to {}:".format("subtract" if subtract else "add"),
                    "",
                    lambda value: self._add(value, subtract),
                    None,
                    None,
                )
            else:
                self._add(items[index], subtract)

        self.view.window().show_quick_panel(items, on_done)

    def _pick_to_remove(self):
        if not self.values:
            sublime.status_message("sage_lint: this #define has no values to remove")
            return

        def on_done(index):
            if index >= 0:
                del self.values[index]
                self._rewrite()

        self.view.window().show_quick_panel(self.values, on_done)

    def _add(self, value, subtract):
        value = (value or "").strip()
        if not value:
            return
        token = ("-" if subtract else "+") + value.lstrip("+-")
        if token in self.values:
            sublime.status_message("sage_lint: value already present")
            return
        self.values.append(token)
        self._rewrite()

    def _rewrite(self):
        self.view.run_command(
            "sage_lint_replace_line",
            {
                "start": self.region.begin(),
                "end": self.region.end(),
                "text": "#define {} {}".format(self.macro_name, " ".join(self.values)),
            },
        )
        # The buffer shifted; re-anchor the region to the (possibly shorter/longer) line.
        self.region = self.view.line(self.region.begin())

    def is_enabled(self):
        return _is_lintable(self.view.file_name())


class SageLintReplaceLineCommand(sublime_plugin.TextCommand):
    """Internal: replace a line region with new text inside an edit (used by Edit Macro
    Values, which builds the replacement outside any single edit)."""

    def run(self, edit, start, end, text):
        self.view.replace(edit, sublime.Region(start, end), text)


class SageLintEventListener(sublime_plugin.EventListener):
    def on_pre_save(self, view):
        if _settings().get("format_on_save", False) and _is_lintable(view.file_name()):
            _log("format on save: " + os.path.basename(view.file_name()))
            view.run_command("sage_lint_format")

    def on_post_save_async(self, view):
        if not _is_lintable(view.file_name()):
            return
        _log("lint on save: " + os.path.basename(view.file_name()))
        _lint_file_async(view, _project_root(view.window(), view.file_name()), view.file_name())

    def on_modified_async(self, view):
        if not _settings().get("lint_on_idle", True) or not _is_lintable(view.file_name()):
            return
        vid = view.id()
        token = _pending_edits.get(vid, 0) + 1
        _pending_edits[vid] = token
        delay = _settings().get("idle_delay_ms", 800)
        sublime.set_timeout_async(lambda: _maybe_lint_idle(view, vid, token), delay)

    def on_load_async(self, view):
        # A view opened after the folder lint ran already has stored diagnostics to draw.
        _render_view(view)

    def on_activated_async(self, view):
        _render_view(view)

    def on_selection_modified_async(self, view):
        _status_for_caret(view)

    def on_hover(self, view, point, hover_zone):
        if hover_zone not in (sublime.HOVER_TEXT, sublime.HOVER_GUTTER):
            return
        # A diagnostic on the hovered line takes precedence; otherwise fall through to the
        # symbol index (macro value, module schema, include target) when hovering text.
        if self._hover_diagnostics(view, point):
            return
        if hover_zone == sublime.HOVER_TEXT:
            self._hover_symbol(view, point)

    def _hover_diagnostics(self, view, point):
        diags = _diagnostics.get(_normcase(view.file_name() or ""), [])
        row = view.rowcol(point)[0] + 1
        here = [d for d in diags if d["line_start"] == row] if diags else []
        if not here:
            return False
        descriptions = _code_descriptions()
        blocks = []
        for diag in here:
            desc = descriptions.get(diag["code"], "")
            blocks.append(
                '<span class="{0}">{0}</span> {1}<br><strong>[{2}]</strong>{3}'.format(
                    html.escape(diag["severity"]),
                    html.escape(diag["message"]),
                    html.escape(diag["code"]),
                    "<br><em>" + html.escape(desc) + "</em>" if desc else "",
                )
            )
        style = (
            ".error { color: #e05c4a; } .warning { color: #d8b44a; } .info { color: #5a9bd8; }"
            "em { color: color(var(--foreground) alpha(0.7)); }"
        )
        body = "<body><style>{}</style>{}</body>".format(style, "<br><br>".join(blocks))
        view.show_popup(body, sublime.HIDE_ON_MOUSE_MOVE_AWAY, location=point, max_width=640)
        return True

    def _hover_symbol(self, view, point):
        if not _is_lintable(view.file_name()) and not _has_index():
            return
        line_text = view.substr(view.line(point))

        include = INCLUDE_RE.search(line_text)
        if include:
            full = _resolve_include(view, include.group(1))
            if full is not None:
                found = os.path.exists(full)
                body = "<b>Include:</b> {}<br><i>{}:</i> {}".format(
                    html.escape(include.group(1)),
                    "found" if found else "not found",
                    html.escape(full),
                )
                view.show_popup(
                    f"<body>{body}</body>",
                    sublime.HIDE_ON_MOUSE_MOVE_AWAY,
                    location=point,
                    max_width=1000,
                )
            return

        # A block header / module slot declaration on this line: document the whole block.
        block = _block_decl(line_text)
        if block is not None and _blocks.get(block):
            with _index_lock:
                fields = dict(_blocks[block])
            view.show_popup(
                _module_doc_html(block, fields),
                sublime.HIDE_ON_MOUSE_MOVE_AWAY,
                location=point,
                max_width=900,
                max_height=500,
            )
            return

        word = _word_at(view, sublime.Region(point, point))
        if not word:
            return

        # A field of the enclosing block: show its type.
        enclosing = _enclosing_block(view, point)
        if enclosing is not None:
            with _index_lock:
                field_info = _blocks.get(enclosing, {}).get(word)
            if field_info is not None:
                view.show_popup(
                    f"<body><b>{html.escape(word)}</b><br>"
                    f"<i>{html.escape(enclosing)} field</i><br>"
                    f"Type: {html.escape(_field_type_label(field_info))}</body>",
                    sublime.HIDE_ON_MOUSE_MOVE_AWAY,
                    location=point,
                    max_width=600,
                )
                return

        found = _lookup_symbol(word)
        if found is None:
            return
        category, payload = found
        if category == "macro":
            body = "<b>{}</b> = {}".format(
                html.escape(payload["name"]), html.escape(str(payload["value"]))
            )
        elif category == "string":
            body = "<b>{}</b><br>{}".format(
                html.escape(payload["name"]), html.escape(str(payload["value"]))
            )
        else:
            entry = payload[0]
            body = "<b>{}</b><br><i>{}</i> — {}".format(
                html.escape(entry["name"]),
                html.escape(entry["kind"]),
                html.escape(os.path.basename(entry["file"])),
            )
        view.show_popup(
            f"<body>{body}</body>",
            sublime.HIDE_ON_MOUSE_MOVE_AWAY,
            location=point,
            max_width=800,
        )

    @staticmethod
    def _value_completions(info, lowered):
        """A `CompletionList` of the values a field accepts — its enum members (static values)
        or, for a reference, the names of its target table (dynamic values) — filtered by the
        typed prefix, or None when the field has no completable value kind. A field with a known
        kind is strict: only its own values are offered (never the generic symbol list), so a
        wrong-kind name is conspicuously absent."""
        flags = sublime.INHIBIT_WORD_COMPLETIONS | sublime.INHIBIT_EXPLICIT_COMPLETIONS
        if "enum" in info:
            items = [
                sublime.CompletionItem(
                    m, completion=m, kind=sublime.KIND_KEYWORD, annotation="enum"
                )
                for m in info["enum"]
                if m.lower().startswith(lowered)
            ]
        elif "ref" in info:
            table = info["ref"]
            with _index_lock:
                names = [n for n in _defs_by_table.get(table, []) if n.lower().startswith(lowered)]
            items = [
                sublime.CompletionItem(
                    n, completion=n, kind=sublime.KIND_NAVIGATION, annotation=table
                )
                for n in names[:200]
            ]
        else:
            return None
        return sublime.CompletionList(items, flags=flags)

    def on_query_completions(self, view, prefix, locations):
        if not _is_lintable(view.file_name()) or not locations or not _has_index():
            return None
        location = locations[0]
        scope = view.scope_name(location)
        if "comment" in scope:
            return None
        line_start = view.line(location).begin()
        before = view.substr(sublime.Region(line_start, location))

        flags = sublime.INHIBIT_WORD_COMPLETIONS | sublime.INHIBIT_EXPLICIT_COMPLETIONS
        lowered = prefix.lower()

        # On the value side of `Field = …`: complete the field's enum members or, for a
        # reference-typed field, exactly the names its target table holds. The trailing
        # `(?:\S+\s+)*\S*` skips any already-typed tokens (a flag list keeps completing after
        # each space) and leaves the current partial token for the prefix filter.
        assignment = re.match(r"^\s*(\w+)\s*=\s*(?:\S+\s+)*\S*$", before)
        if assignment is not None:
            field = assignment.group(1)
            enclosing = _enclosing_block(view, location)
            with _index_lock:
                info = _blocks.get(enclosing, {}).get(field) if enclosing else None
            values = self._value_completions(info, lowered) if info else None
            if values is not None:
                return values
            # `Behavior = Au…` — the value of a module slot names a module class.
            if re.match(r"^\s*\w+\s*=\s*\w*$", before):
                with _index_lock:
                    names = [n for n in _module_slots if n.lower().startswith(lowered)]
                items = [
                    sublime.CompletionItem(
                        n, completion=n, kind=sublime.KIND_TYPE, annotation="module"
                    )
                    for n in sorted(names)
                ]
                if items:
                    return sublime.CompletionList(items, flags=flags)

        completions = []

        # At the start of a line inside a block: offer that block's field (attribute) names.
        enclosing = _enclosing_block(view, location)
        if enclosing is not None and re.match(r"^\s*\w*$", before):
            with _index_lock:
                fields = dict(_blocks.get(enclosing, {}))
            for field, info in sorted(fields.items()):
                if field.lower().startswith(lowered):
                    completions.append(
                        sublime.CompletionItem(
                            field,
                            completion=field,
                            kind=sublime.KIND_VARIABLE,
                            annotation=_field_type_label(info),
                        )
                    )

        # Symbol names (definitions, macros, strings) — capped so a huge game stays responsive.
        if len(prefix) >= 2:
            with _index_lock:
                for entries in _definitions.values():
                    entry = entries[0]
                    if entry["name"].lower().startswith(lowered):
                        completions.append(
                            sublime.CompletionItem(
                                entry["name"],
                                completion=entry["name"],
                                kind=sublime.KIND_NAVIGATION,
                                annotation=entry["kind"],
                            )
                        )
                for payload in _macros.values():
                    if payload["name"].lower().startswith(lowered):
                        completions.append(
                            sublime.CompletionItem(
                                payload["name"],
                                completion=payload["name"],
                                kind=sublime.KIND_SNIPPET,
                                annotation="macro",
                            )
                        )
                for payload in _strings.values():
                    if payload["name"].lower().startswith(lowered):
                        completions.append(
                            sublime.CompletionItem(
                                payload["name"],
                                completion=payload["name"],
                                kind=sublime.KIND_MARKUP,
                                annotation="string",
                            )
                        )
        if not completions:
            return None
        completions.sort(key=lambda c: c.trigger.lower())
        return sublime.CompletionList(completions[:200], flags=flags)


def _maybe_lint_idle(view, vid, token):
    if _pending_edits.get(vid) != token or not view.is_valid():
        return
    file_name = view.file_name()
    if not _is_lintable(file_name):
        return
    root = _project_root(view.window(), file_name)
    _log("idle lint: " + os.path.basename(file_name))
    if view.is_dirty():
        content = view.substr(sublime.Region(0, view.size()))
        _lint_buffer_async(view, root, file_name, content)
    else:
        _lint_file_async(view, root, file_name)


def plugin_loaded():
    """Start a linter daemon for each open window's project folder (it builds the game once,
    then re-lints files against that cache), and warm the code-description cache."""

    def start():
        _log(f"v{__version__} loaded")
        _code_descriptions()
        for window in sublime.windows():
            root = _project_root(window)
            if root is not None:
                _ensure_daemon(root)  # builds the cache and emits the first folder report

    sublime.set_timeout(start, 500)


def plugin_unloaded():
    """Stop every daemon when the plugin reloads or Sublime exits, so no orphan processes
    linger (a reload re-imports this module and starts fresh ones in `plugin_loaded`)."""
    _shutdown_daemons()
