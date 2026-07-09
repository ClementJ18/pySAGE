"""Option resolution and report formatting shared by the `sage_lint` subcommands: how a run
finds its `.sagelint` config, root, base sources and rule set, and how a diagnostic renders
as a text line or a JSON dict. Anything used by a single command lives in that command's
module instead.
"""

import argparse
import sys
from pathlib import Path

from sage_ini.parser.diagnostics import Diagnostic, Severity
from sage_lint.config import Config, load_config
from sage_lint.rules.base import RULES

# ANSI SGR codes used to colour the severity word in text output.
SEVERITY_COLOR: dict[Severity, str] = {
    Severity.ERROR: "31",  # red
    Severity.WARNING: "33",  # yellow
    Severity.INFO: "36",  # cyan
}

SEVERITY_ORDER = {Severity.ERROR: 0, Severity.WARNING: 1, Severity.INFO: 2}

# How `--sort` orders the report. Each key is a total order; later components break ties so
# the output is deterministic whatever the primary key. `file` is the default (read a file
# top to bottom); `severity` surfaces the errors first; `code` groups same-kind problems.
SORTERS = {
    "file": lambda d: (d.span.file, d.span.line_start, SEVERITY_ORDER[d.severity]),
    "severity": lambda d: (SEVERITY_ORDER[d.severity], d.span.file, d.span.line_start),
    "code": lambda d: (d.code, d.span.file, d.span.line_start),
    "line": lambda d: (d.span.line_start, d.span.file, SEVERITY_ORDER[d.severity]),
}


def diagnostic_dict(diag: Diagnostic) -> dict[str, object]:
    """A JSON-serializable view of a diagnostic, flat for easy editor parsing."""
    return diag.to_dict()


def want_color(choice: str, stream) -> bool:
    if choice == "always":
        return True
    if choice == "never":
        return False
    return bool(getattr(stream, "isatty", lambda: False)())


def diag_line(diag: Diagnostic, color: bool) -> str:
    """One text report line; the severity word is coloured when `color` is set."""
    severity = diag.severity.value
    if color:
        severity = f"\033[{SEVERITY_COLOR[diag.severity]}m{severity}\033[0m"
    return f"{diag.span}: {severity}: {diag.message} [{diag.code}]"


def split_codes(values: list[str]) -> set[str]:
    """Flatten repeated and comma-separated code values into a set of codes."""
    return {code.strip() for value in values for code in value.split(",") if code.strip()}


def base_source(path: Path) -> tuple[str, str]:
    """A `--base` argument as a (kind, path) source: a .big archive or a folder."""
    kind = "big" if path.suffix.lower() == ".big" else "folder"
    return (kind, str(path))


def load_lint_config(args: argparse.Namespace) -> Config:
    """The project `.sagelint` config for this run, or an empty one with `--no-config`. Read
    from the positional root when given, else the linted file's directory, else the current
    directory (so a config there can name the root to lint). Config warnings go to stderr so
    they never pollute stdout (text reports or JSON)."""
    if args.no_config:
        return Config()
    directory = args.root or (args.file.parent if args.file else Path.cwd())
    config = load_config(directory)
    for warning in config.warnings:
        print(f"sage_lint: {warning}", file=sys.stderr)
    return config


def config_dir(args: argparse.Namespace) -> Path:
    """The directory a folder run's `.sagelint` is read from: the positional root if given,
    else the current dir. The config's `root` is resolved against this."""
    return args.root if args.root is not None else Path.cwd()


def config_path(base: Path, value: str) -> Path:
    """A relative config path value resolved against `base` (an absolute value is kept)."""
    path = Path(value)
    return path if path.is_absolute() else base / path


def effective_root(args: argparse.Namespace, config: Config) -> Path | None:
    """The folder to lint. The config's `root`, when set, is the target - resolved against
    the directory its `.sagelint` lives in (the positional root, else the current dir) - so a
    config placed beside a project can point the lint at a subfolder. A positional root with
    no config `root` is the target itself; `--file` uses `--root` only for include resolution
    and never the config `root`."""
    if args.file is not None:
        return args.root
    if config.root is not None:
        return config_path(config_dir(args), config.root)
    return args.root


def base_paths(
    args: argparse.Namespace,
    config: Config,
    base_dir: Path,
    include_assets: bool,
    include_maps: bool = False,
) -> list[Path]:
    """The base sources to load: the always-on `base`, plus `assets_base` only when asset checking
    is on and `maps_base` only when map linting is on. Those conditional sources are the heavy
    base-game data each pass needs but nothing else does, so a plain run never pays to load them. A
    CLI list (`--base` / `--assets-base` / `--maps-base`) overrides the matching config list
    wholesale; config relative paths resolve against `base_dir`."""

    def listed(cli_value, config_value):
        return list(cli_value) if cli_value else [config_path(base_dir, b) for b in config_value]

    paths = listed(args.base, config.base)
    if include_assets:
        paths += listed(args.assets_base, config.assets_base)
    if include_maps:
        paths += listed(args.maps_base, config.maps_base)
    return paths


def _selected_rules(selected: set[str]) -> list[type] | None:
    """The rule subset to run for `--select`; None (all) when nothing selected."""
    if not selected:
        return None
    return [rule for rule in RULES if rule.code in selected]


def resolve_rule_set(selected: set[str], include_assets: bool) -> list[type] | None:
    """The rules a run executes. An explicit `--select` wins (opt-in rules run when named). With
    no selection, `--assets` (or config `assets`) adds the asset-group opt-in rules to the default
    set; otherwise None lets `run_rules` use the plain default set. A non-asset opt-in rule (e.g.
    unused-object) is never pulled in by `--assets` - only naming it in `--select` runs it."""
    if selected:
        return _selected_rules(selected)
    if include_assets:
        return [rule for rule in RULES if rule.default or rule.assets]
    return None


def select_and_summarize(
    items, selected: set[str], ignored: set[str], level_name: str | None
) -> tuple[list[Diagnostic], dict[str, int]]:
    """Apply `select`/`ignore`/`level` to a diagnostic list (the JSON report's filtering),
    returning the shown diagnostics (file-sorted) and a summary count dict."""
    remaining = list(items)
    if selected:
        remaining = [d for d in remaining if d.code in selected]
    if ignored:
        remaining = [d for d in remaining if d.code not in ignored]
    threshold = Severity[level_name] if level_name else Severity.WARNING
    shown = [d for d in remaining if SEVERITY_ORDER[d.severity] <= SEVERITY_ORDER[threshold]]
    shown.sort(key=SORTERS["file"])
    summary = {
        "errors": sum(1 for d in shown if d.severity is Severity.ERROR),
        "warnings": sum(1 for d in shown if d.severity is Severity.WARNING),
        "hidden": len(remaining) - len(shown),
    }
    return shown, summary
