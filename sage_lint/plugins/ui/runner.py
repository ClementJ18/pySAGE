"""Run the `sage_lint lint` command in-process and return its JSON report, so the desktop
UI reuses every bit of the CLI's behaviour - config discovery, baseline, filtering, sorting -
rather than reimplementing it. Kept Qt-free so it can run on a worker thread (or headless).
"""

import io
import json
import sys
import tempfile
from collections import Counter
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from sage_lint.baseline import (
    BASELINE_VERSION,
    BaselineError,
    load_baseline,
)
from sage_lint.cli import main as cli_main
from sage_lint.config import CONFIG_NAME, LOCAL_CONFIG_NAME, load_config

# The lowest severities offered in the UI, matching the CLI's --level choices.
LEVELS = ("ERROR", "WARNING", "INFO")

# The project config file names, in load order (the local file overlays the shared one).
CONFIG_NAMES = (CONFIG_NAME, LOCAL_CONFIG_NAME)

# The combined baseline the UI writes when it merges several found under the mod. A fixed
# name in the temp dir, overwritten each run, so it never accumulates.
MERGED_BASELINE = "sage_lint_merged.baseline"


def app_dir() -> Path:
    """The folder the app runs from - beside the `.exe` when frozen by PyInstaller, else the
    working directory. This is where we look for a config to autoload on launch, so dropping
    the exe into a mod folder makes it ready to Check at once."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path.cwd()


def has_project_config(folder) -> bool:
    """Whether a `.sagelint` or `.sagelint.local` sits directly in `folder`."""
    base = Path(folder)
    return any((base / name).is_file() for name in CONFIG_NAMES)


def project_config(folder: str):
    """The `.sagelint` (+ `.sagelint.local`) config for `folder`, or None when the path is not
    a directory. Lets the UI reflect the project's own level/suggest settings on selection."""
    if not folder or not Path(folder).is_dir():
        return None
    return load_config(folder)


def _resolve(folder: Path, value: str) -> Path:
    """A config path resolved against the lint `folder` (an absolute value is kept as-is) -
    mirroring how the CLI resolves a relative `base`/`baseline` against the lint root."""
    path = Path(value)
    return path if path.is_absolute() else folder / path


def config_bases(config, folder: str) -> list[str]:
    """The config's base-game source(s) as absolute path strings, resolved against the lint
    folder - so the UI can show and pass them as `--base` rather than rely on the CLI's own
    config lookup (which would resolve a relative value against the wrong directory)."""
    base = Path(folder)
    return [str(_resolve(base, value)) for value in config.base]


def effective_lint_root(config, folder: str) -> Path:
    """The folder the CLI will actually lint and resolve baselines against: the config's `root`
    (resolved against the config folder) when set, else the folder itself. Baseline entries are
    stored relative to this root, so it is also what the merge re-roots to."""
    base = Path(folder)
    if config is not None and config.root:
        return _resolve(base, config.root)
    return base


def find_baselines(root) -> list[Path]:
    """Every baseline file anywhere under `root`, sorted. Matches `*.baseline` (so the
    conventional `.sagelint.baseline` and any custom name are both found) and keeps only files
    that actually parse as a baseline, so an unrelated `.baseline` file is skipped."""
    base = Path(root)
    if not base.is_dir():
        return []
    found = []
    for path in sorted(base.rglob("*.baseline")):
        try:
            load_baseline(path)
        except BaselineError:
            continue
        found.append(path)
    return found


def merge_baselines(paths, root) -> str:
    """Combine the baselines at `paths` into one temp baseline file whose entries are relative
    to `root`, and return its path ('' when nothing valid was found).

    Each baseline stores its files relative to the root it was written against - by convention
    the folder it sits in (e.g. a `_mod/.sagelint.baseline` covers `_mod`). To use them all
    when linting `root`, every entry is re-rooted: prefixed with the baseline's own directory
    relative to `root`. A baseline sitting directly at `root` needs no prefix; one outside
    `root` (no relative path) is left as-is."""
    base = Path(root)
    counts: Counter = Counter()
    for path in paths:
        try:
            baseline = load_baseline(path)
        except BaselineError:
            continue
        try:
            prefix = path.parent.relative_to(base).as_posix()
        except ValueError:
            prefix = ""
        if prefix == ".":
            prefix = ""
        for (file, code, message), count in baseline.counts.items():
            rerooted = f"{prefix}/{file}" if prefix else file
            counts[(rerooted, code, message)] += count
    if not counts:
        return ""
    entries = [
        {"file": file, "code": code, "message": message, "count": count}
        for (file, code, message), count in sorted(counts.items())
    ]
    document = {"version": BASELINE_VERSION, "total": sum(counts.values()), "entries": entries}
    out = Path(tempfile.gettempdir()) / MERGED_BASELINE
    out.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    return str(out)


def build_argv(
    folder: str,
    *,
    level: str = "WARNING",
    base: str = "",
    baseline: str = "",
    suggest: bool = False,
    fix: bool = False,
) -> list[str]:
    """The `sage_lint lint` argument list for these options. Always JSON and `--exit-zero`
    (the UI reads the report, not the exit code). Empty base/baseline are omitted so the
    project config's own values stand."""
    argv = ["lint", folder, "--output-format", "json", "--exit-zero", "--level", level]
    # The Base game field holds one or more paths separated by ';' (safe: Windows paths use
    # ':' only after a drive letter, never ';'); each becomes its own --base.
    for path in (p.strip() for p in base.split(";")):
        if path:
            argv += ["--base", path]
    if baseline.strip():
        argv += ["--baseline", baseline.strip()]
    if suggest:
        argv.append("--suggest")
    if fix:
        argv.append("--fix")
    return argv


def build_format_argv(folder: str, *, align_equals: bool = False, align_exclude=()) -> list[str]:
    """The `sage_lint format` argument list to reformat a folder in place. The align options are
    passed explicitly (from the config the UI already read) so they apply even when the config
    sits above the formatted root - where `format`'s own config lookup would miss it."""
    argv = ["format", folder, "--output-format", "json"]
    if align_equals:
        argv.append("--align-equals")
    for token in align_exclude:
        if token:
            argv += ["--align-exclude", token]
    return argv


def run_cli(argv: list[str]) -> dict:
    """Run the CLI with `argv` (any subcommand), capturing its JSON report from stdout. Raises
    `ValueError` with whatever reached stderr when no JSON came back (e.g. an argparse error)."""
    out, err = io.StringIO(), io.StringIO()
    try:
        with redirect_stdout(out), redirect_stderr(err):
            cli_main(argv)
    except SystemExit:
        pass  # argparse-style early exit; the captured stderr explains it
    try:
        return json.loads(out.getvalue())
    except json.JSONDecodeError as exc:
        message = err.getvalue().strip() or "the linter returned no results"
        raise ValueError(message) from exc
