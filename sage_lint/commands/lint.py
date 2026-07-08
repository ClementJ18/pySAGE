"""The `lint` family: assemble a game from a folder and report its problems (`lint`, with
`--fix`, baselines and filtering), lint the binary `.map` layouts against it (`lint-maps`),
and list the accepted diagnostic codes (`--list-codes`).
"""

import argparse
import json
import sys
from fnmatch import fnmatch
from pathlib import Path

from sage_ini.parser.diagnostics import Diagnostic, Diagnostics, Severity
from sage_ini.parser.io import read_text
from sage_ini.suggest import suggestions_enabled
from sage_lint.baseline import (
    BASELINE_NAME,
    BaselineError,
    load_baseline,
    write_baseline,
)
from sage_lint.commands.common import (
    SEVERITY_ORDER,
    SORTERS,
    base_paths,
    base_source,
    config_dir,
    config_path,
    diag_line,
    diagnostic_dict,
    resolve_rule_set,
    select_and_summarize,
    split_codes,
    want_color,
)
from sage_lint.config import Config
from sage_lint.fixer import fix_diagnostics
from sage_lint.linter import build_cache, lint_file, lint_folder
from sage_lint.ruleconfig import rule_options
from sage_lint.rules.base import RULES

# Diagnostic codes emitted outside the rule framework (parser, loader, conversion)
# that are still valid `--ignore`/`--select` targets. Rule codes are read live from
# the RULES registry by `_diagnostic_catalog`, not duplicated here.
_NONRULE_CODES: dict[str, str] = {
    "conversion-error": "a value failed to convert: bad number, dangling reference, or bad macro",
    "enum-case": "an enum token matched only by ignoring case; canonical spelling differs",
    "reference-case": "a cross-reference matched a definition only by ignoring case; casing differs",  # noqa: E501
    "macro-case": "a macro reference matched a #define only by ignoring case; casing differs",
    "extra-header-tokens": "a definition header had tokens past the name; first names it, rest ignored",  # noqa: E501
    "ignored-trailing-tokens": "a scalar reference had extra trailing tokens; first is used",
    "repeated-flag-field": "a whole-set flag field (e.g. KindOf) set twice; last wins",
    "stray-end": "an `End` with no open block",
    "unclosed-block": "a block opened but was never closed by `End`",
    "unclosed-script": "a `BeginScript` with no matching `EndScript`",
    "unresolved-include": "an `#include` target could not be found",
    "include-cycle": "an `#include` chain refers back to itself",
    "malformed-define": "a `#define` directive that could not be parsed",
    "malformed-include": "an `#include` directive that could not be parsed",
    "unknown-directive": "an unrecognized `#` directive",
    "load-error": "a file failed to build into the game",
    "rule-error": "a lint rule raised while running (internal)",
}

# Plain-language nouns for what `--fix` changed, keyed by diagnostic code — for a summary an
# audience nervous about a tool rewriting their mod can read at a glance.
_FIX_LABELS: dict[str, str] = {
    "reference-case": "reference casing",
    "enum-case": "enum value casing",
    "macro-case": "macro reference casing",
    "repeated-field": "duplicate field",
    "repeated-flag-field": "duplicate flag field",
    "spurious-block-label": "spurious block `=`",
}


def _and_list(items: list[str]) -> str:
    """Join phrases as prose: 'a', 'a and b', 'a, b and c'."""
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def _fix_summary(applied: list[Diagnostic], file_count: int) -> str:
    """One plain-language sentence describing what `--fix` touched, grouped by kind of fix.
    Keeps the bare `fixed N issue(s)` count, then names the kinds and reassures that nothing
    else changed."""
    counts: dict[str, int] = {}
    for diag in applied:
        counts[diag.code] = counts.get(diag.code, 0) + 1
    parts = []
    for code in sorted(counts):
        noun = _FIX_LABELS.get(code, code)
        count = counts[code]
        parts.append(f"{count} {noun if count == 1 else noun + 's'}")
    files = "1 file" if file_count == 1 else f"{file_count} files"
    return (
        f"fixed {len(applied)} issue(s): {_and_list(parts)}, across {files}. "
        "Nothing else was touched."
    )


def _diag_origin(diag: Diagnostic) -> tuple[str | None, str | None]:
    """The block type and attribute a diagnostic emerged from, as `(type, attr)` — the
    `type`/`field` (or `key`) structured facts the schema, conversion and rule layers attach.
    Either is None when the diagnostic doesn't name it (e.g. a parser-level problem)."""
    extra = diag.extra
    return extra.get("type"), (extra.get("field") or extra.get("key"))


def _side_matches(value: str | None, pattern: str) -> bool:
    """One side of a `TYPE.ATTR` filter: a bare `*` (or empty) matches anything, including a
    missing value; otherwise the value must exist and glob-match the pattern (case-insensitive,
    SAGE being case-insensitive)."""
    if pattern in ("", "*"):
        return True
    return value is not None and fnmatch(value.casefold(), pattern.casefold())


def _matches_filters(diag: Diagnostic, filters: set[str]) -> bool:
    """Whether a diagnostic matches any `TYPE.ATTR` filter. Each filter globs the block type
    and the attribute independently (`ArmorSet.Armor`, `*.Armor`, `ArmorSet.*`); a filter with
    no dot globs the attribute alone (`Armor`, `Max*`)."""
    dtype, attr = _diag_origin(diag)
    for pattern in filters:
        type_pat, attr_pat = pattern.split(".", 1) if "." in pattern else ("*", pattern)
        if _side_matches(dtype, type_pat) and _side_matches(attr, attr_pat):
            return True
    return False


def _rule_summary(rule: type) -> str:
    """The one-line summary of a rule, from the first line of its docstring."""
    for line in (rule.__doc__ or "").strip().splitlines():
        if line.strip():
            return line.strip()
    return ""


def _diagnostic_catalog() -> list[tuple[str, dict[str, str]]]:
    """The `--ignore`/`--select`-able codes, grouped by source (rule codes read live). Opt-in
    rules (skipped by a plain run) are flagged so a reader knows to enable them with --assets."""

    def _opt_in(rule: type) -> str:
        if rule.default:
            return ""
        return "  [opt-in: --assets]" if rule.assets else "  [opt-in: --select]"

    rules = {rule.code: _rule_summary(rule) + _opt_in(rule) for rule in RULES}
    return [("rules", rules), ("parser / loader / conversion", _NONRULE_CODES)]


def run_list_codes() -> int:
    catalog = _diagnostic_catalog()
    width = max((len(code) for _, codes in catalog for code in codes), default=0)
    print("Diagnostic codes accepted by --ignore and --select:\n")
    for title, codes in catalog:
        print(f"  {title}:")
        for code in sorted(codes):
            print(f"    {code.ljust(width)}  {codes[code]}")
        print()
    return 0


def _lint_map_files(root: Path, game, excludes: tuple[Path, ...]) -> Diagnostics:
    """Lint the binary `.map` layouts under `root` against the already-assembled `game`, skipping
    any map in an excluded directory. `sage_map` is imported lazily; when the optional `[map]`
    extra is not installed, map linting is silently skipped (no diagnostics)."""
    try:
        from sage_map import lint_maps  # noqa: PLC0415 — lazy: the [map] extra is optional
    except ImportError:
        return Diagnostics()
    excluded = tuple(Path(directory).resolve() for directory in excludes)
    paths = [
        path
        for path in game.map_files
        if not any(path.resolve().is_relative_to(directory) for directory in excluded)
    ]
    return lint_maps(root, game=game, paths=paths)


def _print_statistics(remaining: list[Diagnostic]) -> None:
    """A per-code count table, the 'where is the noise' view (`--statistics`)."""
    counts: dict[str, tuple[int, Severity]] = {}
    for diag in remaining:
        count, _ = counts.get(diag.code, (0, diag.severity))
        counts[diag.code] = (count + 1, diag.severity)
    if not counts:
        print("no diagnostics")
        return
    width = max(len(str(count)) for count, _ in counts.values())
    for code in sorted(counts, key=lambda c: (-counts[c][0], c)):
        count, severity = counts[code]
        print(f"{str(count).rjust(width)}  {severity.value:<7}  {code}")


def _baseline_path(args: argparse.Namespace, config: Config) -> Path | None:
    """The baseline file for this run: `--baseline` if given, else the config's `baseline`
    (resolved against the config dir), else the conventional name beside the config. The path
    is returned even when it does not exist yet — reading a missing one suppresses nothing, and
    `--write-baseline` creates it. None only when `--no-config` is set with no `--baseline`."""
    if args.baseline is not None:
        return args.baseline
    if args.no_config:
        return None
    directory = config_dir(args)
    if config.baseline:
        return config_path(directory, config.baseline)
    return directory / BASELINE_NAME


_SOURCE_CACHE: dict[str, list[str]] = {}


def _source_line(diag: Diagnostic) -> str | None:
    """The source text at a diagnostic's start line, for `--verbose`."""
    lines = _SOURCE_CACHE.get(diag.span.file)
    if lines is None:
        try:
            lines = read_text(diag.span.file).splitlines()
        except OSError:
            lines = []
        _SOURCE_CACHE[diag.span.file] = lines
    index = diag.span.line_start - 1
    if 0 <= index < len(lines):
        return lines[index].strip()
    return None


def run_lint(args: argparse.Namespace, config: Config, root: Path | None) -> int:
    # CLI flags override the config file; the config fills in what the flags leave unset.
    # A config's relative exclude/base paths name folders inside the linted tree, so they
    # resolve against the lint root — not the process working directory (which, run from an
    # editor, is the linter checkout) — falling back to the config dir on the --file path.
    base_dir = root if root is not None else config_dir(args)
    include_assets = args.assets or config.assets
    # Maps are a whole-folder concern (off by default), never linted on the single-file path.
    include_maps = (args.maps or config.maps) and args.file is None
    selected = split_codes(args.select) or set(config.select)
    ignored = split_codes(args.ignore) or set(config.ignore)
    excludes = (
        list(args.exclude) if args.exclude else [config_path(base_dir, e) for e in config.exclude]
    )
    bases = base_paths(args, config, base_dir, include_assets, include_maps)
    level_name = args.level or config.level

    rules = resolve_rule_set(selected, include_assets)

    # Suggestions are opt-in (they fuzzy-match every miss against the whole name table); enable
    # them only for the build/validate that produces this report. The reference/unused rules read
    # the project's `sentinels`/`always_referenced` from process state for the same window.
    with (
        suggestions_enabled(args.suggest or config.suggest),
        rule_options(sentinels=config.sentinels, always_referenced=config.always_referenced),
    ):
        if args.file is not None:
            # Save-time fast path: lint just one file, resolving includes against the positional
            # root (the project folder) when given, else the file's directory. Base sources are
            # build-only and folder-scoped, so the single-file path never applies them.
            diagnostics = lint_file(args.file, include_root=root, rules=rules)
        elif include_maps:
            # Build the game once (keeping it), lint the ini, then also lint the binary `.map`
            # layouts against that same game so a map referencing removed content is caught. The
            # base layer is cleaned up once both passes are done.
            game, diagnostics, base_layer = build_cache(
                root,
                rules=rules,
                exclude=tuple(excludes),
                bases=tuple(base_source(base) for base in bases),
            )
            try:
                diagnostics.items.extend(_lint_map_files(root, game, tuple(excludes)).items)
                diagnostics.items = list(dict.fromkeys(diagnostics.items))
            finally:
                if base_layer is not None:
                    base_layer.cleanup()
        else:
            diagnostics = lint_folder(
                root,
                rules=rules,
                exclude=tuple(excludes),
                bases=tuple(base_source(base) for base in bases),
            )

    remaining = list(diagnostics)
    if selected:
        remaining = [d for d in remaining if d.code in selected]
    if ignored:
        # Drop ignored codes before --fix sees them, so they are neither fixed nor reported.
        remaining = [d for d in remaining if d.code not in ignored]
    filters = split_codes(args.filter)
    if filters:
        # Keep only diagnostics from a matching block/attribute, before --fix, so the filter
        # scopes what gets fixed too.
        remaining = [d for d in remaining if _matches_filters(d, filters)]

    threshold = Severity[level_name] if level_name else Severity.WARNING
    baseline_path = _baseline_path(args, config)

    def _at_level(diags: list[Diagnostic]) -> list[Diagnostic]:
        return [d for d in diags if SEVERITY_ORDER[d.severity] <= SEVERITY_ORDER[threshold]]

    if args.write_baseline:
        # Snapshot exactly what a plain run would report (post select/ignore/filter/level, but
        # unfixed and unsuppressed) as the accepted set, so the next run is clean.
        recordable = _at_level(remaining)
        written = write_baseline(baseline_path, recordable, root)
        if args.output_format == "json":
            print(
                json.dumps(
                    {
                        "baseline": {
                            "path": str(baseline_path),
                            "entries": written,
                            "diagnostics": len(recordable),
                        }
                    },
                    indent=2,
                )
            )
        elif not args.quiet:
            print(
                f"wrote {written} baseline entry(ies) covering {len(recordable)} "
                f"diagnostic(s) to {baseline_path}"
            )
        return 0

    fixed_count = 0
    if args.fix:
        fixed_by_file, applied = fix_diagnostics(remaining)
        fixed_count = len(applied)
        if applied:
            applied_set = set(applied)
            remaining = [d for d in remaining if d not in applied_set]
            if args.output_format != "json" and not args.quiet:
                print(_fix_summary(applied, len(fixed_by_file)))
                if args.verbose:
                    for file in sorted(fixed_by_file):
                        print(f"  {file}: {fixed_by_file[file]} fix(es)")
        elif args.output_format != "json" and not args.quiet:
            print("nothing to fix")

    # Suppress baselined diagnostics last, so --fix still operates on the whole set (fixing a
    # pre-existing problem is progress) and only genuinely new problems reach the report.
    baselined = 0
    if baseline_path is not None:
        try:
            baseline = load_baseline(baseline_path)
        except BaselineError as exc:
            # A corrupt baseline must not silently let everything through: report it and treat
            # the baseline as empty, so the run is loud rather than falsely clean.
            print(f"sage_lint: {exc}", file=sys.stderr)
            baseline = None
        if baseline is not None and baseline.counts:
            remaining, suppressed = baseline.partition(remaining, root)
            baselined = len(suppressed)

    shown = _at_level(remaining)
    shown.sort(key=SORTERS[args.sort])

    errors = sum(1 for d in shown if d.severity is Severity.ERROR)
    warnings = sum(1 for d in shown if d.severity is Severity.WARNING)
    hidden = len(remaining) - len(shown)

    if args.output_format == "json":
        print(
            json.dumps(
                {
                    "diagnostics": [diagnostic_dict(d) for d in shown],
                    "summary": {
                        "errors": errors,
                        "warnings": warnings,
                        "hidden": hidden,
                        "fixed": fixed_count,
                        "baselined": baselined,
                    },
                },
                indent=2,
            )
        )
        return 0 if args.exit_zero else (1 if shown else 0)

    if args.statistics:
        _print_statistics(remaining)
    elif not args.quiet:
        color = want_color(args.color, sys.stdout)
        for diag in shown:
            print(diag_line(diag, color))
            if args.verbose:
                excerpt = _source_line(diag)
                if excerpt is not None:
                    print(f"    | {excerpt}")

    summary = f"{errors} error(s), {warnings} warning(s)"
    notes = []
    if hidden:
        notes.append(f"{hidden} info hidden; use --level INFO to show")
    if baselined:
        notes.append(f"{baselined} baselined")
    if notes:
        summary += f" ({'; '.join(notes)})"
    print(summary)
    return 0 if args.exit_zero else (1 if shown else 0)


def run_lint_maps(args: argparse.Namespace, config: Config, root: Path) -> int:
    """Lint the binary `.map` layouts under `root` for dangling references, resolved against the
    assembled game. Reuses the same root/base/exclude resolution as `lint`, so GAME-scope checks
    (object/science/upgrade names) resolve against the *complete* world the `--base` layers build —
    without them only map-local references (teams, waypoints) are reliable. The `sage_map` overlay
    is imported lazily so `sage_lint` runs without the optional `[map]` extra installed."""
    try:
        from sage_map import lint_maps  # noqa: PLC0415 — lazy: the [map] extra is optional
    except ImportError:
        print(
            "sage_lint: map linting needs the optional 'map' extra (pip install 'pysage[map]')",
            file=sys.stderr,
        )
        return 2

    base_dir = root
    selected = split_codes(args.select) or set(config.select)
    ignored = split_codes(args.ignore) or set(config.ignore)
    excludes = (
        list(args.exclude) if args.exclude else [config_path(base_dir, e) for e in config.exclude]
    )
    bases = list(args.base) if args.base else [config_path(base_dir, b) for b in config.base]
    level_name = args.level or config.level

    # Build the whole game once (base layers merged in, like `lint`), then lint each crawled map
    # against it. The base layer is kept only for the duration of this run.
    game, _folder, base_layer = build_cache(
        root, exclude=tuple(excludes), bases=tuple(base_source(base) for base in bases)
    )
    try:
        excluded = tuple(Path(directory).resolve() for directory in excludes)
        paths = [
            path
            for path in game.map_files
            if not any(path.resolve().is_relative_to(directory) for directory in excluded)
        ]
        diagnostics = lint_maps(root, game=game, paths=paths)
    finally:
        if base_layer is not None:
            base_layer.cleanup()

    shown, summary = select_and_summarize(diagnostics.items, selected, ignored, level_name)

    if args.output_format == "json":
        print(
            json.dumps(
                {"diagnostics": [diagnostic_dict(d) for d in shown], "summary": summary},
                indent=2,
            )
        )
        return 0 if args.exit_zero else (1 if shown else 0)

    if not args.quiet:
        color = want_color(args.color, sys.stdout)
        for diag in shown:
            print(diag_line(diag, color))

    maps = "1 map" if len(paths) == 1 else f"{len(paths)} maps"
    print(f"{summary['errors']} error(s), {summary['warnings']} warning(s) across {maps}")
    return 0 if args.exit_zero else (1 if shown else 0)
