"""Command-line entry point: `python -m sage_lint <command>`. `format` rewrites ini
files to the canonical style (or reports them with `--check`, or formats stdin);
`lint` assembles a game from a folder and reports its problems. Both can emit JSON
(`--output-format json`) for an editor plugin. `diff` assembles the mod at two git refs
(config-aware, with the base game merged in) and reports a human-readable changelog of the
game-data changes between them.
"""

import argparse
import enum
import json
import os
import re
import subprocess
import sys
import tempfile
from contextlib import ExitStack
from dataclasses import replace
from fnmatch import fnmatch
from pathlib import Path

from sage_ini.diff import diff_games, format_game_diff, git_worktree
from sage_ini.model.objects import (
    REGISTRY,
    IniObject,
    Module,
    NestedAttribute,
    Nugget,
    resolve_annotation,
)
from sage_ini.model.types import Reference
from sage_ini.parser.diagnostics import Diagnostic, Diagnostics, Severity
from sage_ini.parser.io import INI_SUFFIXES, iter_ini_files, read_text
from sage_ini.parser.location import Span
from sage_ini.stats import ini_root
from sage_ini.suggest import set_enabled as set_suggestions_enabled
from sage_ini.suggest import suggestions_enabled
from sage_lint.baseline import (
    BASELINE_NAME,
    BaselineError,
    load_baseline,
    write_baseline,
)
from sage_lint.config import CONFIG_NAME, Config, init_project, load_config
from sage_lint.fixer import fix_diagnostics
from sage_lint.formatter import FormatResult, format_file, format_text
from sage_lint.linter import (
    assemble_with_bases,
    build_cache,
    lint_file,
    lint_file_cached,
    lint_folder,
)
from sage_lint.ruleconfig import rule_options, set_options
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

# ANSI SGR codes used to colour the severity word in text output.
_SEVERITY_COLOR: dict[Severity, str] = {
    Severity.ERROR: "31",  # red
    Severity.WARNING: "33",  # yellow
    Severity.INFO: "36",  # cyan
}

_SEVERITY_ORDER = {Severity.ERROR: 0, Severity.WARNING: 1, Severity.INFO: 2}

# How `--sort` orders the report. Each key is a total order; later components break ties so
# the output is deterministic whatever the primary key. `file` is the default (read a file
# top to bottom); `severity` surfaces the errors first; `code` groups same-kind problems.
_SORTERS = {
    "file": lambda d: (d.span.file, d.span.line_start, _SEVERITY_ORDER[d.severity]),
    "severity": lambda d: (_SEVERITY_ORDER[d.severity], d.span.file, d.span.line_start),
    "code": lambda d: (d.code, d.span.file, d.span.line_start),
    "line": lambda d: (d.span.line_start, d.span.file, _SEVERITY_ORDER[d.severity]),
}


def _discover(paths: list[Path]) -> list[Path]:
    files: list[Path] = []
    seen: set[Path] = set()
    for path in paths:
        candidates = iter_ini_files(path) if path.is_dir() else [path]
        for candidate in candidates:
            resolved = candidate.resolve()
            if resolved not in seen:
                seen.add(resolved)
                files.append(candidate)
    return files


def _write_back(result: FormatResult) -> None:
    newline = "\r\n" if "\r\n" in result.original else "\n"
    output = result.formatted.replace("\n", newline)
    Path(result.file).write_text(output, encoding=result.encoding, newline="")


# Plain-language nouns for what `--fix` changed, keyed by diagnostic code — for a summary an
# audience nervous about a tool rewriting their mod can read at a glance.
_FIX_LABELS: dict[str, str] = {
    "reference-case": "reference casing",
    "enum-case": "enum value casing",
    "macro-case": "macro reference casing",
    "repeated-field": "duplicate field",
    "repeated-flag-field": "duplicate flag field",
    "redundant-nullification": "redundant nullification",
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


def _diagnostic_dict(diag: Diagnostic) -> dict[str, object]:
    """A JSON-serializable view of a diagnostic, flat for easy editor parsing."""
    return {
        "code": diag.code,
        "severity": diag.severity.value,
        "message": diag.message,
        "file": diag.span.file,
        "line_start": diag.span.line_start,
        "line_end": diag.span.line_end,
    }


def _tidy_type_token(token: str) -> str:
    """Drop the leading `_` of a private converter alias (`_Int`, `_List`) and a `Block`
    suffix on a model class name (`_FXListBlock` -> `FXList`), so the editor sees the name a
    modder would write rather than the internal Python identifier."""
    token = token.lstrip("_")
    if token.endswith("Block") and len(token) > 5:
        token = token[: -len("Block")]
    return token


def _type_label(annotation: object) -> str:
    """A short, readable name for a field's converter annotation, for the editor's module
    documentation. A typed field is `Annotated[PyType, converter]`; the `PyType` is the
    human-facing type, so prefer it (a `ForwardRef` cross-reference keeps its written form). A
    bare class-name string is already a label; any other converter falls back to its class
    name. Private alias/internal spellings are tidied to the form a modder recognizes."""
    metadata = getattr(annotation, "__metadata__", None)
    args = getattr(annotation, "__args__", None)
    if metadata is not None and args:
        py_type = args[0]
        raw = (
            getattr(py_type, "__forward_arg__", None)
            or getattr(py_type, "__name__", None)
            or str(py_type)
        )
    elif isinstance(annotation, str):
        raw = annotation
    else:
        cls = annotation if isinstance(annotation, type) else type(annotation)
        raw = cls.__name__
    return re.sub(r"[A-Za-z_][A-Za-z0-9_]*", lambda m: _tidy_type_token(m.group()), raw)


def _field_value_info(annotation: object) -> dict[str, object]:
    """Per-field metadata for the editor's value autocomplete: always a `type` label, plus —
    when the field's converter (or its list/flag element, or any tuple slot) is an enum — the
    enum's member names under `enum`, or — when it is a cross-`Reference` — the referenced
    table key under `ref`. Mirrors the converter shapes `references.py::_iter_refs` walks, so a
    `List[Weapon]` advertises the same `ref` a bare `Weapon` field does."""
    info: dict[str, object] = {"type": _type_label(annotation)}
    try:
        converter = resolve_annotation(annotation)
    except (KeyError, TypeError):
        return info
    seen: set[int] = set()
    while converter is not None and id(converter) not in seen:
        seen.add(id(converter))
        if isinstance(converter, type) and issubclass(converter, enum.Enum):
            info["enum"] = list(converter.__members__)
            return info
        if isinstance(converter, Reference):
            info["ref"] = converter.key
            return info
        # A field typed directly as a definition class (e.g. `CommandSet`, `Object`) names a
        # value in that class's table — the same `key` the object registers under — so it is a
        # reference too. Modules and other unstored classes carry `key = None` and are skipped.
        if isinstance(converter, type) and issubclass(converter, IniObject) and converter.key:
            info["ref"] = converter.key
            return info
        # Unwrap the single-value wrappers to the converter that actually types the value: a
        # `List`/`FlagList` element, a `Nullable` inner, or a `Tuple`'s first slot. (A
        # `KeyedRecord`'s many keys have no single value kind, so it is left as its label.)
        element = getattr(converter, "element", None) or getattr(converter, "inner", None)
        if element is None:
            element_types = getattr(converter, "element_types", None)
            element = element_types[0] if element_types else None
        if element is None:
            return info
        try:
            converter = resolve_annotation(element)
        except (KeyError, TypeError):
            return info
    return info


def _block_schemas() -> dict[str, dict[str, dict[str, object]]]:
    """`block class name -> {field: field_info}` for every modelled block — top-level objects
    (Object, Weapon, Armor, CommandSet, CommandButton, Upgrade, Science …) and module slots
    alike — read straight from the typed model's registry (the same `_fieldspec` conversion
    runs against). Each `field_info` carries a `type` label and, when known, the field's `enum`
    members or referenced `ref` table. Drives module documentation and field/value autocomplete
    without a hand-maintained data table."""
    # `_fieldspec` is the whole MRO's annotations, so it also carries the base classes'
    # configuration attributes (`key`, `unique_name`, the `_`-prefixed internals …), which are
    # never real INI fields. Drop everything declared on the infrastructure bases to leave only
    # the keys a block actually reads.
    infrastructure = set()
    for base in (IniObject, Module, NestedAttribute, Nugget):
        infrastructure.update(getattr(base, "__annotations__", {}))

    schemas: dict[str, dict[str, dict[str, object]]] = {}
    for name, cls in REGISTRY.items():
        if not (isinstance(cls, type) and issubclass(cls, IniObject)):
            continue
        fields = {
            field: _field_value_info(spec)
            for field, spec in getattr(cls, "_fieldspec", {}).items()
            if field not in infrastructure and not field.startswith("_")
        }
        if fields:
            schemas[name] = fields
    return schemas


def _module_slot_names() -> list[str]:
    """The registered module classes (behaviors, bodies, draws, updates …) — the value tokens
    valid after a `Behavior =`/`Body =`/… slot, for the editor's module-name autocomplete."""
    return sorted(
        name
        for name, cls in REGISTRY.items()
        if isinstance(cls, type) and issubclass(cls, Module) and cls is not Module
    )


def _keyed_by_label_names() -> list[str]:
    """The block classes opened by their *name* with the label as a key (`ModelConditionState =
    DAMAGED`, `AnimationState = MOVING`), as `classify_subblock` types them. The editor needs
    these to tell such a header from a plain `Field = value`, so it offers the right block's
    fields inside one."""
    return sorted(
        name
        for name, cls in REGISTRY.items()
        if isinstance(cls, type) and getattr(cls, "keyed_by_label", False)
    )


def _game_index(game, include_roots: tuple[str, ...] = ()) -> dict[str, object]:
    """A JSON-serializable symbol index of the assembled game, for the editor's go-to-definition,
    symbol browser and autocomplete: every named definition with its source span, plus the macro
    and string tables. Built from the live typed game, so kinds and locations match the parse.

    `include_roots` are the ordered include-resolution roots the linter uses (the mod's ini root,
    then any merged base-game roots) so the editor can resolve an `#include` the same way — a
    base-game-only include included by a mod file is found, not reported missing."""
    definitions = []
    for table in game.tables.values():
        for obj in table.values():
            span = getattr(obj, "span", None)
            if span is None or not isinstance(obj.name, str):
                continue
            definitions.append(
                {
                    "name": obj.name,
                    "kind": type(obj).__name__,
                    "table": obj.key,
                    "file": span.file,
                    "line": span.line_start,
                }
            )
    macros = {}
    for name, value in game.macros.items():
        span = game.macro_definitions.get(name)
        macros[name] = {
            "value": value,
            "file": span.file if span is not None else None,
            "line": span.line_start if span is not None else None,
        }
    strings = {}
    for name, value in game.strings.items():
        span = game.string_definitions.get(name)
        strings[name] = {
            "value": value,
            "file": span.file if span is not None else None,
            "line": span.line_start if span is not None else None,
        }
    return {
        "type": "index",
        "definitions": definitions,
        "macros": macros,
        "strings": strings,
        "blocks": _block_schemas(),
        "module_slots": _module_slot_names(),
        "keyed_by_label": _keyed_by_label_names(),
        "include_roots": list(include_roots),
    }


def _want_color(choice: str, stream) -> bool:
    if choice == "always":
        return True
    if choice == "never":
        return False
    return bool(getattr(stream, "isatty", lambda: False)())


def _diag_line(diag: Diagnostic, color: bool) -> str:
    """One text report line; the severity word is coloured when `color` is set."""
    severity = diag.severity.value
    if color:
        severity = f"\033[{_SEVERITY_COLOR[diag.severity]}m{severity}\033[0m"
    return f"{diag.span}: {severity}: {diag.message} [{diag.code}]"


def _load_format_config(args: argparse.Namespace) -> Config:
    """The `.sagelint` whose format options (`align_equals`, `align_exclude`) apply to this
    run, or an empty one with `--no-config`. Read from the first path's directory (the file's
    own folder for a file), else the current directory. Warnings go to stderr so stdout stays
    clean for a JSON report or formatted stdin."""
    if args.no_config:
        return Config()
    if getattr(args, "stdin", False):
        parent = Path(args.stdin_filename).parent
        directory = parent if str(parent) not in ("", ".") and parent.is_dir() else Path.cwd()
    elif args.paths:
        first = args.paths[0]
        directory = first if first.is_dir() else first.parent
    else:
        directory = Path.cwd()
    config = load_config(directory)
    for warning in config.warnings:
        print(f"sage_lint: {warning}", file=sys.stderr)
    return config


def _format_align(args: argparse.Namespace, config: Config) -> tuple[bool, tuple[str, ...]]:
    """The effective format alignment options: the CLI flag when given, else the config's. So
    `align_equals`/`align_exclude` in `.sagelint` drive `format` the way `--align-equals` does."""
    align_equals = args.align_equals or config.align_equals
    exclude = _split_codes(args.align_exclude) or set(config.align_exclude)
    return align_equals, tuple(exclude)


def _run_format(args: argparse.Namespace) -> int:
    if args.stdin:
        return _run_format_stdin(args)
    align_equals, exclude = _format_align(args, _load_format_config(args))
    results = [
        format_file(path, align_equals=align_equals, align_exclude=exclude)
        for path in _discover(args.paths)
    ]
    if args.output_format == "json":
        return _format_json(results, args.check)
    return _format_text(results, args)


def _format_text(results: list[FormatResult], args: argparse.Namespace) -> int:
    reformatted = needs_format = skipped = with_smells = 0
    for result in results:
        if result.smells:
            with_smells += 1
        if result.skipped:
            skipped += 1
            print(f"skipped {result.file}: {result.skip_reason}")
            continue
        if result.changed:
            needs_format += 1
            if args.check:
                print(f"would reformat {result.file}")
            else:
                _write_back(result)
                reformatted += 1
                if not args.quiet:
                    print(f"reformatted {result.file}")
        if not args.quiet:
            for smell in result.smells:
                print(f"  {smell}")

    if args.check:
        print(
            f"{needs_format} file(s) need formatting, {skipped} skipped, "
            f"{with_smells} with tab smells"
        )
        return 1 if (needs_format or with_smells) else 0

    print(f"reformatted {reformatted}, {skipped} skipped, {with_smells} with tab smells")
    return 0


def _format_json(results: list[FormatResult], check: bool) -> int:
    payload = []
    reformatted = needs_format = skipped = with_smells = 0
    for result in results:
        if result.smells:
            with_smells += 1
        if result.skipped:
            skipped += 1
        elif result.changed:
            needs_format += 1
            if not check:
                _write_back(result)
                reformatted += 1
        payload.append(
            {
                "file": result.file,
                "changed": result.changed,
                "skipped": result.skipped,
                "skip_reason": result.skip_reason,
                "smells": [_diagnostic_dict(d) for d in result.smells],
            }
        )

    print(
        json.dumps(
            {
                "results": payload,
                "summary": {
                    "reformatted": reformatted,
                    "need_format": needs_format,
                    "skipped": skipped,
                    "with_smells": with_smells,
                },
            },
            indent=2,
        )
    )
    if check:
        return 1 if (needs_format or with_smells) else 0
    return 0


def _run_format_stdin(args: argparse.Namespace) -> int:
    """Format a buffer from stdin to stdout. Messages go to stderr so stdout stays
    exactly the formatted source an editor can drop back into the buffer."""
    text = sys.stdin.read()
    align_equals, exclude = _format_align(args, _load_format_config(args))
    result = format_text(
        text,
        file=args.stdin_filename,
        align_equals=align_equals,
        align_exclude=exclude,
    )

    if args.output_format == "json":
        print(
            json.dumps(
                {
                    "file": result.file,
                    "changed": result.changed,
                    "skipped": result.skipped,
                    "skip_reason": result.skip_reason,
                    "smells": [_diagnostic_dict(d) for d in result.smells],
                },
                indent=2,
            )
        )
        return 1 if (result.skipped or (args.check and result.changed)) else 0

    for smell in result.smells:
        print(smell, file=sys.stderr)
    if result.skipped:
        # Can't safely reprint a recovered file: pass the buffer through untouched.
        print(f"skipped: {result.skip_reason}", file=sys.stderr)
        if not args.check:
            sys.stdout.write(text)
        return 1
    if args.check:
        return 1 if result.changed else 0
    newline = "\r\n" if "\r\n" in text else "\n"
    sys.stdout.write(result.formatted.replace("\n", newline))
    return 0


def _base_source(path: Path) -> tuple[str, str]:
    """A `--base` argument as a (kind, path) source: a .big archive or a folder."""
    kind = "big" if path.suffix.lower() == ".big" else "folder"
    return (kind, str(path))


def _split_codes(values: list[str]) -> set[str]:
    """Flatten repeated and comma-separated code values into a set of codes."""
    return {code.strip() for value in values for code in value.split(",") if code.strip()}


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


def _run_list_codes() -> int:
    catalog = _diagnostic_catalog()
    width = max((len(code) for _, codes in catalog for code in codes), default=0)
    print("Diagnostic codes accepted by --ignore and --select:\n")
    for title, codes in catalog:
        print(f"  {title}:")
        for code in sorted(codes):
            print(f"    {code.ljust(width)}  {codes[code]}")
        print()
    return 0


def _selected_rules(selected: set[str]) -> list[type] | None:
    """The rule subset to run for `--select`; None (all) when nothing selected."""
    if not selected:
        return None
    return [rule for rule in RULES if rule.code in selected]


def _resolve_rule_set(selected: set[str], include_assets: bool) -> list[type] | None:
    """The rules a run executes. An explicit `--select` wins (opt-in rules run when named). With
    no selection, `--assets` (or config `assets`) adds the asset-group opt-in rules to the default
    set; otherwise None lets `run_rules` use the plain default set. A non-asset opt-in rule (e.g.
    unused-object) is never pulled in by `--assets` — only naming it in `--select` runs it."""
    if selected:
        return _selected_rules(selected)
    if include_assets:
        return [rule for rule in RULES if rule.default or rule.assets]
    return None


def _base_paths(
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
        return list(cli_value) if cli_value else [_config_path(base_dir, b) for b in config_value]

    paths = listed(args.base, config.base)
    if include_assets:
        paths += listed(args.assets_base, config.assets_base)
    if include_maps:
        paths += listed(args.maps_base, config.maps_base)
    return paths


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


def _load_lint_config(args: argparse.Namespace) -> Config:
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


def _config_dir(args: argparse.Namespace) -> Path:
    """The directory a folder run's `.sagelint` is read from: the positional root if given,
    else the current dir. The config's `root` is resolved against this."""
    return args.root if args.root is not None else Path.cwd()


def _config_path(base: Path, value: str) -> Path:
    """A relative config path value resolved against `base` (an absolute value is kept)."""
    path = Path(value)
    return path if path.is_absolute() else base / path


def _effective_root(args: argparse.Namespace, config: Config) -> Path | None:
    """The folder to lint. The config's `root`, when set, is the target — resolved against
    the directory its `.sagelint` lives in (the positional root, else the current dir) — so a
    config placed beside a project can point the lint at a subfolder. A positional root with
    no config `root` is the target itself; `--file` uses `--root` only for include resolution
    and never the config `root`."""
    if args.file is not None:
        return args.root
    if config.root is not None:
        return _config_path(_config_dir(args), config.root)
    return args.root


def _baseline_path(args: argparse.Namespace, config: Config) -> Path | None:
    """The baseline file for this run: `--baseline` if given, else the config's `baseline`
    (resolved against the config dir), else the conventional name beside the config. The path
    is returned even when it does not exist yet — reading a missing one suppresses nothing, and
    `--write-baseline` creates it. None only when `--no-config` is set with no `--baseline`."""
    if args.baseline is not None:
        return args.baseline
    if args.no_config:
        return None
    config_dir = _config_dir(args)
    if config.baseline:
        return _config_path(config_dir, config.baseline)
    return config_dir / BASELINE_NAME


def _run_lint(args: argparse.Namespace, config: Config, root: Path | None) -> int:
    # CLI flags override the config file; the config fills in what the flags leave unset.
    # A config's relative exclude/base paths name folders inside the linted tree, so they
    # resolve against the lint root — not the process working directory (which, run from an
    # editor, is the linter checkout) — falling back to the config dir on the --file path.
    base_dir = root if root is not None else _config_dir(args)
    include_assets = args.assets or config.assets
    # Maps are a whole-folder concern (off by default), never linted on the single-file path.
    include_maps = (args.maps or config.maps) and args.file is None
    selected = _split_codes(args.select) or set(config.select)
    ignored = _split_codes(args.ignore) or set(config.ignore)
    excludes = (
        list(args.exclude) if args.exclude else [_config_path(base_dir, e) for e in config.exclude]
    )
    bases = _base_paths(args, config, base_dir, include_assets, include_maps)
    level_name = args.level or config.level

    rules = _resolve_rule_set(selected, include_assets)

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
                bases=tuple(_base_source(base) for base in bases),
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
                bases=tuple(_base_source(base) for base in bases),
            )

    remaining = list(diagnostics)
    if selected:
        remaining = [d for d in remaining if d.code in selected]
    if ignored:
        # Drop ignored codes before --fix sees them, so they are neither fixed nor reported.
        remaining = [d for d in remaining if d.code not in ignored]
    filters = _split_codes(args.filter)
    if filters:
        # Keep only diagnostics from a matching block/attribute, before --fix, so the filter
        # scopes what gets fixed too.
        remaining = [d for d in remaining if _matches_filters(d, filters)]

    threshold = Severity[level_name] if level_name else Severity.WARNING
    baseline_path = _baseline_path(args, config)

    def _at_level(diags: list[Diagnostic]) -> list[Diagnostic]:
        return [d for d in diags if _SEVERITY_ORDER[d.severity] <= _SEVERITY_ORDER[threshold]]

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
    shown.sort(key=_SORTERS[args.sort])

    errors = sum(1 for d in shown if d.severity is Severity.ERROR)
    warnings = sum(1 for d in shown if d.severity is Severity.WARNING)
    hidden = len(remaining) - len(shown)

    if args.output_format == "json":
        print(
            json.dumps(
                {
                    "diagnostics": [_diagnostic_dict(d) for d in shown],
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
        color = _want_color(args.color, sys.stdout)
        for diag in shown:
            print(_diag_line(diag, color))
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


def _run_lint_maps(args: argparse.Namespace, config: Config, root: Path) -> int:
    """Lint the binary `.map` layouts under `root` for dangling references, resolved against the
    assembled game. Reuses the same root/base/exclude resolution as `lint`, so GAME-scope checks
    (object/science/upgrade names) resolve against the *complete* world the `--base` layers build —
    without them only map-local references (teams, waypoints) are reliable. The `sage_map` overlay
    is imported lazily so `sage_lint` runs without the optional `[map]` extra installed."""
    try:
        from sage_map import lint_maps  # noqa: PLC0415 — lazy: the [map] extra is optional
    except ImportError:
        print(
            "sage_lint: map linting needs the optional 'map' extra (pip install 'sage_ini[map]')",
            file=sys.stderr,
        )
        return 2

    base_dir = root
    selected = _split_codes(args.select) or set(config.select)
    ignored = _split_codes(args.ignore) or set(config.ignore)
    excludes = (
        list(args.exclude) if args.exclude else [_config_path(base_dir, e) for e in config.exclude]
    )
    bases = list(args.base) if args.base else [_config_path(base_dir, b) for b in config.base]
    level_name = args.level or config.level

    # Build the whole game once (base layers merged in, like `lint`), then lint each crawled map
    # against it. The base layer is kept only for the duration of this run.
    game, _folder, base_layer = build_cache(
        root, exclude=tuple(excludes), bases=tuple(_base_source(base) for base in bases)
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

    shown, summary = _select_and_summarize(diagnostics.items, selected, ignored, level_name)

    if args.output_format == "json":
        print(
            json.dumps(
                {"diagnostics": [_diagnostic_dict(d) for d in shown], "summary": summary},
                indent=2,
            )
        )
        return 0 if args.exit_zero else (1 if shown else 0)

    if not args.quiet:
        color = _want_color(args.color, sys.stdout)
        for diag in shown:
            print(_diag_line(diag, color))

    maps = "1 map" if len(paths) == 1 else f"{len(paths)} maps"
    print(f"{summary['errors']} error(s), {summary['warnings']} warning(s) across {maps}")
    return 0 if args.exit_zero else (1 if shown else 0)


def _run_diff(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    """Changelog of game-data changes between two git refs, assembled the way `lint` builds a
    game: the `.sagelint` config (root, base) is read from the repo working dir, then each ref is
    checked out into a temp worktree and assembled WITH the base-game archives merged in, so an
    `#include` into the base resolves on both sides and the diff reports real changes, not
    unresolved-include load artifacts."""
    config_dir = (args.dir or Path.cwd()).resolve()
    config = Config() if args.no_config else load_config(config_dir)
    for warning in config.warnings:
        print(warning, file=sys.stderr)

    bases = list(args.base) if args.base else [_config_path(config_dir, b) for b in config.base]
    base_sources = tuple(_base_source(Path(b)) for b in bases)
    rel_root = config.root if config.root and not Path(config.root).is_absolute() else None

    def game_at(ref: str, stack: ExitStack):
        tree = stack.enter_context(git_worktree(config_dir, ref))
        root = tree / rel_root if rel_root else tree
        if not root.is_dir():
            parser.error(f"root {root.name!r} not found at ref {ref!r}")
        loaded, base_layer = assemble_with_bases(root, base_sources)
        if base_layer is not None:
            stack.callback(base_layer.cleanup)
        return loaded.game

    try:
        with ExitStack() as stack:
            old_game = game_at(args.old, stack)
            new_game = game_at(args.new, stack)
            diff = diff_games(old_game, new_game, strings=args.strings)
            print(format_game_diff(diff, args.old, args.new), end="")
    except subprocess.CalledProcessError as exc:
        print(f"git failed: {exc.stderr or exc}", file=sys.stderr)
        return 2
    return 0


def _select_and_summarize(
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
    shown = [d for d in remaining if _SEVERITY_ORDER[d.severity] <= _SEVERITY_ORDER[threshold]]
    shown.sort(key=_SORTERS["file"])
    summary = {
        "errors": sum(1 for d in shown if d.severity is Severity.ERROR),
        "warnings": sum(1 for d in shown if d.severity is Severity.WARNING),
        "hidden": len(remaining) - len(shown),
    }
    return shown, summary


def _emit(obj: dict) -> None:
    """Write one newline-delimited JSON message to stdout (the daemon's wire format)."""
    print(json.dumps(obj), flush=True)


def _lint_request(game, path, content, root, rules, include_bases=()):
    """Re-lint a daemon `lint_file` request against the cache. With `content` (the live editor
    buffer), lint that text from a temp file beside the real one — so relative `#include`s
    resolve identically — and relabel the diagnostics back onto the real path; otherwise lint
    the file on disk. `include_bases` are the merged base-game include roots, so an `#include`
    that falls through to the base resolves here just as it does on the whole-folder build."""
    if content is None:
        return lint_file_cached(
            game, path, include_root=root, rules=rules, include_bases=include_bases
        )
    handle, tmp = tempfile.mkstemp(prefix=".sagelint-", suffix=".tmp", dir=os.path.dirname(path))
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as buffer:
            buffer.write(content)
        result = lint_file_cached(
            game, tmp, include_root=root, rules=rules, include_bases=include_bases
        )
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass
    # Diagnostics carry the temp path; rewrite each onto the real file (spans are frozen).
    tmp_key = os.path.normcase(tmp)
    relabelled = Diagnostics()
    for diag in result.items:
        if os.path.normcase(diag.span.file) == tmp_key:
            span = Span(str(path), diag.span.line_start, diag.span.line_end)
            relabelled.items.append(replace(diag, span=span))
        else:
            relabelled.items.append(diag)
    return relabelled


def _run_serve(args: argparse.Namespace) -> int:
    """Long-lived daemon for an editor: build the game once, then re-lint individual files
    against that cache on demand — full-folder accuracy at single-file speed. Speaks
    newline-delimited JSON: one `{"type":"folder",...}` message once the build is ready (and
    again after each `rebuild`), one `{"type":"file",...}` per `lint_file` request, and one
    `{"type":"index",...}` (the symbol/macro/string/module tables) per `index` request. Commands
    arrive as JSON lines on stdin: `lint_file` (with `path`, optional `id`), `index`, `rebuild`,
    `shutdown`."""
    config = _load_lint_config(args)
    root = _effective_root(args, config)
    if root is None or not root.is_dir():
        _emit({"type": "error", "message": f"not a directory: {root}"})
        return 2

    # Opt-in for the daemon's lifetime: every build and re-lint then carries hints, and the
    # reference/unused rules read the project's sentinels/always-referenced from process state.
    set_suggestions_enabled(args.suggest or config.suggest)
    set_options(sentinels=config.sentinels, always_referenced=config.always_referenced)

    base_dir = root
    include_assets = args.assets or config.assets
    selected = _split_codes(args.select) or set(config.select)
    ignored = _split_codes(args.ignore) or set(config.ignore)
    level_name = args.level or config.level
    excludes = tuple(
        list(args.exclude) if args.exclude else [_config_path(base_dir, e) for e in config.exclude]
    )
    bases = tuple(_base_source(b) for b in _base_paths(args, config, base_dir, include_assets))
    rule_set = _resolve_rule_set(selected, include_assets)

    # The merged base game is kept on disk between builds so a single-file re-lint can resolve
    # `#include`s that fall through to the base; each rebuild replaces it, shutdown removes it.
    base_layer = None

    def rebuild() -> object:
        nonlocal base_layer
        _emit({"type": "building", "root": str(root)})
        if base_layer is not None:
            base_layer.cleanup()
            base_layer = None
        game, folder, base_layer = build_cache(root, rules=rule_set, exclude=excludes, bases=bases)
        shown, summary = _select_and_summarize(folder.items, selected, ignored, level_name)
        _emit(
            {
                "type": "folder",
                "diagnostics": [_diagnostic_dict(d) for d in shown],
                "summary": summary,
            }
        )
        return game

    game = rebuild()
    try:
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                command = json.loads(line)
            except ValueError:
                _emit({"type": "error", "message": "malformed command"})
                continue
            kind = command.get("cmd")
            if kind == "shutdown":
                break
            if kind == "rebuild":
                game = rebuild()
            elif kind == "index":
                include_bases = (base_layer.include_root,) if base_layer is not None else ()
                include_roots = (str(ini_root(root)), *(str(base) for base in include_bases))
                message = _game_index(game, include_roots)
                if "id" in command:
                    message["id"] = command["id"]
                _emit(message)
            elif kind == "lint_file":
                path = command.get("path")
                include_bases = (base_layer.include_root,) if base_layer is not None else ()
                try:
                    diagnostics = _lint_request(
                        game, path, command.get("content"), root, rule_set, include_bases
                    )
                    shown, summary = _select_and_summarize(
                        diagnostics.items, selected, ignored, level_name
                    )
                    payload = [_diagnostic_dict(d) for d in shown]
                    message = {
                        "type": "file",
                        "path": path,
                        "diagnostics": payload,
                        "summary": summary,
                    }
                except (OSError, ValueError, KeyError, TypeError, IndexError) as exc:
                    message = {"type": "file", "path": path, "error": str(exc)}
                if "id" in command:
                    message["id"] = command["id"]
                _emit(message)
            else:
                _emit({"type": "error", "message": f"unknown command {kind!r}"})
    finally:
        if base_layer is not None:
            base_layer.cleanup()
    return 0


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


def _run_init(args: argparse.Namespace) -> int:
    """Scaffold a `.sagelint` config in the target folder, reporting what the linter detected
    so the modder knows the string-label rule will (or won't) fire — the trap a one-shot setup
    exists to close."""
    directory = args.directory
    if not directory.is_dir():
        print(f"sage_lint: not a directory: {directory}", file=sys.stderr)
        return 2

    result = init_project(directory, force=args.force)

    print(f"Scanned {directory}:")
    print(f"  {result.ini_count} ini file(s) found")
    if result.string_files:
        print(
            f"  {len(result.string_files)} string table(s) found "
            "— the unknown-string-label rule will run"
        )
    else:
        print(
            "  no string table (.str / Lotr.csv) found — the unknown-string-label rule "
            "will be skipped until one is reachable under the lint root"
        )
    print()

    for path in result.written:
        print(f"wrote {path}")
    for path in result.skipped:
        print(f"kept existing {path} (use --force to overwrite)")
    if not result.written:
        print(f"nothing written; {CONFIG_NAME} already exists")
        return 0
    print(f"\nNext: run `sage_lint lint {directory}` to check the mod.")
    return 0


def _add_output_format(sub: argparse.ArgumentParser) -> None:
    sub.add_argument(
        "--output-format",
        choices=("text", "json"),
        default="text",
        help="report format: human text (default) or machine-readable json",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sage_lint")
    subparsers = parser.add_subparsers(dest="command", required=True)

    fmt = subparsers.add_parser("format", help="rewrite ini files to the canonical style")
    fmt.add_argument(
        "paths",
        type=Path,
        nargs="*",
        help=f"ini files or folders to format ({', '.join(sorted(INI_SUFFIXES))})",
    )
    fmt.add_argument(
        "--check",
        action="store_true",
        help="do not write; list files that need formatting and exit non-zero",
    )
    fmt.add_argument("--quiet", action="store_true", help="only print summaries and skips")
    fmt.add_argument(
        "--align-equals",
        action="store_true",
        help="pad attribute names so their '=' line up in a column, per blank-line-delimited "
        "group within each block (cosmetic: the whitespace around '=' is otherwise "
        "insignificant)",
    )
    fmt.add_argument(
        "--align-exclude",
        action="append",
        default=[],
        metavar="TYPE",
        help="block type whose attributes are left unaligned by --align-equals, by header "
        "keyword (Object, ArmorSet, Draw) or module subtype (ActiveBody); repeatable and "
        "comma-separated",
    )
    fmt.add_argument(
        "--stdin",
        action="store_true",
        help="read source from stdin and write the formatted result to stdout "
        "(the format-on-save path for an editor)",
    )
    fmt.add_argument(
        "--stdin-filename",
        default="<stdin>",
        metavar="NAME",
        help="virtual filename to report stdin under (with --stdin)",
    )
    fmt.add_argument(
        "--no-config",
        action="store_true",
        help="ignore .sagelint / .sagelint.local; use flags and built-in defaults only "
        "(the config's align_equals / align_exclude are otherwise applied)",
    )
    _add_output_format(fmt)

    lint = subparsers.add_parser("lint", help="build a game from a folder and report problems")
    lint.add_argument("root", type=Path, nargs="?", help="folder of ini files to assemble and lint")
    lint.add_argument(
        "--file",
        type=Path,
        help="lint only this single file (the editor save-time fast path): parse it and "
        "its includes instead of assembling the whole folder. References to definitions "
        "in sibling files cannot resolve in this mode. Includes resolve against the "
        "positional root (the project folder) when given, else the file's own directory.",
    )
    lint.add_argument(
        "--list-codes",
        action="store_true",
        help="list the diagnostic codes that --ignore/--select accept, then exit",
    )
    lint.add_argument(
        "--base",
        type=Path,
        action="append",
        default=[],
        help="base-game source (folder or .big) loaded beneath the mod; build-only, "
        "file-shadowed by the mod, and never reported (repeatable, highest priority first)",
    )
    lint.add_argument(
        "--assets-base",
        type=Path,
        action="append",
        default=[],
        help="extra base source loaded ONLY with --assets (or config assets): the large "
        "texture/model archives the missing-file rules need but nothing else does, so a plain "
        "run never pays to load them (repeatable, like --base)",
    )
    lint.add_argument(
        "--exclude",
        type=Path,
        action="append",
        default=[],
        help="directory to omit from the report; its files still build the game (repeatable)",
    )
    lint.add_argument(
        "--select",
        action="append",
        default=[],
        metavar="CODE",
        help="report only these diagnostic codes (the inverse of --ignore); "
        "repeatable, and a comma-separated list is also accepted. Only the "
        "selected rules are run. --ignore still subtracts from the selection.",
    )
    lint.add_argument(
        "--ignore",
        action="append",
        default=[],
        metavar="CODE",
        help="diagnostic code to omit from the report (e.g. unknown-attribute); "
        "repeatable, and a comma-separated list is also accepted. Ignored codes "
        "are neither reported nor auto-fixed.",
    )
    lint.add_argument(
        "--filter",
        action="append",
        default=[],
        metavar="TYPE.ATTR",
        help="report only diagnostics from a matching block/attribute, e.g. ArmorSet.Armor. "
        "Each side globs independently: '*.Armor' (any block's Armor), 'ArmorSet.*' (any "
        "attribute of ArmorSet); a pattern with no dot globs the attribute alone ('Armor'). "
        "Repeatable and comma-separated; matching is case-insensitive. Diagnostics that name "
        "no block/attribute (e.g. parser errors) are dropped when a filter is set.",
    )
    lint.add_argument(
        "--level",
        type=str.upper,
        choices=[level.name for level in Severity],
        help="define the diagnostic level to show",
    )
    lint.add_argument(
        "--suggest",
        action="store_true",
        help="add a \"Did you mean 'X'?\" hint to each unresolved reference, attribute, macro "
        "or string label (off by default: every miss is fuzzy-matched against the whole name "
        "table, which is the dominant cost on a large game)",
    )
    lint.add_argument(
        "--assets",
        action="store_true",
        help="also run the opt-in missing-texture/model/map-file rules (off by default: without "
        "the base-game archives loaded via --base they report every base asset as missing). "
        "Load your bases, then add --assets to check that referenced files exist.",
    )
    lint.add_argument(
        "--maps",
        action="store_true",
        help="also lint the binary .map layouts against the assembled game, so a map referencing "
        "an object/upgrade you have removed is caught (off by default: parsing every map adds "
        "time, and needs the [map] extra installed). Map checks use the map-dangling-* codes.",
    )
    lint.add_argument(
        "--maps-base",
        type=Path,
        action="append",
        default=[],
        help="extra base source loaded only with --maps (or config maps): the base-game data the "
        "map checks resolve object/upgrade references against, so a base-game object is not "
        "reported missing (repeatable, like --base)",
    )
    lint.add_argument(
        "--sort",
        choices=tuple(_SORTERS),
        default="file",
        help="order the report: file (path then line, default), severity (errors first), "
        "code (group same-kind problems), or line (by line number across files)",
    )
    lint.add_argument(
        "--fix",
        action="store_true",
        help="rewrite source files to resolve the auto-fixable diagnostics (enum-case, "
        "reference-case, macro-case, repeated-field, repeated-flag-field, "
        "redundant-nullification, spurious-block-label) before reporting the rest",
    )
    lint.add_argument(
        "--baseline",
        type=Path,
        metavar="PATH",
        help="suppress diagnostics recorded in this baseline file, reporting only new ones "
        f"(matched line-insensitively by file, code and message). Defaults to a {BASELINE_NAME} "
        "beside the .sagelint config when present; set 'baseline' in .sagelint to make it "
        "permanent. Generate or refresh it with --write-baseline.",
    )
    lint.add_argument(
        "--write-baseline",
        action="store_true",
        help="record the currently reported diagnostics as the baseline (to --baseline, the "
        f"config's 'baseline', or {BASELINE_NAME} beside the config) and exit, instead of "
        "reporting. Run this once to adopt the linter on a noisy project, then again whenever "
        "you accept new diagnostics.",
    )
    lint.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="print only the summary line, not each diagnostic",
    )
    lint.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="print the offending source line beneath each diagnostic",
    )
    lint.add_argument(
        "--statistics",
        action="store_true",
        help="print a per-code count table instead of listing each diagnostic",
    )
    lint.add_argument(
        "--exit-zero",
        action="store_true",
        help="always exit 0, even when diagnostics are reported",
    )
    lint.add_argument(
        "--no-config",
        action="store_true",
        help="ignore any .sagelint / .sagelint.local in the linted folder; use flags and "
        "built-in defaults only",
    )
    lint.add_argument(
        "--color",
        choices=("auto", "always", "never"),
        default="auto",
        help="colour the severity in text output (default: auto, on when a tty)",
    )
    _add_output_format(lint)

    lint_maps_cmd = subparsers.add_parser(
        "lint-maps",
        help="lint binary .map layouts for dangling references against the assembled game",
        description="Lint binary .map layouts for dangling references against the assembled game. "
        "Diagnostics use these codes (all accepted by --select/--ignore): "
        "map-dangling-reference (a script argument naming something undefined), "
        "map-dangling-object (a placed object whose type is undefined), "
        "map-dangling-property (an object property naming something undefined), "
        "map-parse-error. The map-dangling-object check (and the GAME-scope references) resolve "
        "against the whole game, so load your bases with --base or they report base-game content "
        "as missing; map-local checks (teams, waypoints) need no bases.",
    )
    lint_maps_cmd.add_argument(
        "root", type=Path, nargs="?", help="mod folder to assemble; its .map files are linted"
    )
    lint_maps_cmd.add_argument(
        "--base",
        type=Path,
        action="append",
        default=[],
        help="base-game source (folder or .big) loaded beneath the mod, so GAME-scope references "
        "(object/science/upgrade names) resolve against the full game (repeatable, highest first)",
    )
    lint_maps_cmd.add_argument(
        "--exclude",
        type=Path,
        action="append",
        default=[],
        help="directory whose maps are skipped; its ini files still build the game (repeatable)",
    )
    lint_maps_cmd.add_argument(
        "--select", action="append", default=[], metavar="CODE", help="report only these codes"
    )
    lint_maps_cmd.add_argument(
        "--ignore", action="append", default=[], metavar="CODE", help="omit these codes"
    )
    lint_maps_cmd.add_argument(
        "--level",
        type=str.upper,
        choices=[level.name for level in Severity],
        help="define the diagnostic level to show",
    )
    lint_maps_cmd.add_argument(
        "-q", "--quiet", action="store_true", help="print only the summary line"
    )
    lint_maps_cmd.add_argument(
        "--color",
        choices=("auto", "always", "never"),
        default="auto",
        help="colour the severity in text output (default: auto, on when a tty)",
    )
    lint_maps_cmd.add_argument(
        "--exit-zero", action="store_true", help="always exit 0, even when diagnostics are reported"
    )
    lint_maps_cmd.add_argument(
        "--no-config", action="store_true", help="ignore .sagelint config files"
    )
    lint_maps_cmd.set_defaults(file=None)  # no single-file path; satisfy the shared config helpers
    _add_output_format(lint_maps_cmd)

    serve = subparsers.add_parser(
        "serve",
        help="run a daemon that builds the game once and re-lints files against it on demand",
    )
    serve.add_argument("root", type=Path, nargs="?", help="folder to assemble (else config root)")
    serve.add_argument("--base", type=Path, action="append", default=[], help="base-game source")
    serve.add_argument(
        "--assets-base",
        type=Path,
        action="append",
        default=[],
        help="extra base source loaded only with --assets (large texture/model archives)",
    )
    serve.add_argument(
        "--exclude", type=Path, action="append", default=[], help="excluded directory"
    )
    serve.add_argument(
        "--select", action="append", default=[], metavar="CODE", help="report only these codes"
    )
    serve.add_argument(
        "--ignore", action="append", default=[], metavar="CODE", help="omit these codes"
    )
    serve.add_argument(
        "--level",
        type=str.upper,
        choices=[level.name for level in Severity],
        help="diagnostic level",
    )
    serve.add_argument("--no-config", action="store_true", help="ignore .sagelint config files")
    serve.add_argument(
        "--suggest", action="store_true", help="add 'Did you mean ...?' hints (off by default)"
    )
    serve.add_argument(
        "--assets",
        action="store_true",
        help="also run the opt-in missing-texture/model/map-file rules (off by default)",
    )
    serve.set_defaults(file=None)  # serve has no single-file path; satisfy the shared helpers

    init = subparsers.add_parser(
        "init",
        help="scaffold a .sagelint config, autodetecting the mod root and string table",
    )
    init.add_argument(
        "directory",
        type=Path,
        nargs="?",
        default=Path("."),
        help="folder to set up (default: the current directory)",
    )
    init.add_argument(
        "--force",
        action="store_true",
        help="overwrite an existing .sagelint / .sagelint.local instead of leaving it in place",
    )

    diff = subparsers.add_parser(
        "diff",
        help="changelog of game-data changes between two git refs (config-aware, base-resolved)",
        description="Assemble the mod at two git refs the way `lint` builds a game — reading "
        "root/base from .sagelint so includes into the base game resolve — and report the "
        "added / removed / changed definitions, fields and modules between them as a "
        "human-readable changelog.",
    )
    diff.add_argument("old", help="old git ref (commit, tag, or branch)")
    diff.add_argument("new", help="new git ref")
    diff.add_argument(
        "dir",
        type=Path,
        nargs="?",
        default=None,
        help="the mod repo working dir holding .sagelint / .sagelint.local (default: current "
        "dir); its config 'root' and 'base' are used and the two refs are checked out from it",
    )
    diff.add_argument(
        "--base",
        type=Path,
        action="append",
        default=[],
        help="base-game source (folder or .big) merged beneath the mod so base includes "
        "resolve; overrides the config 'base' (repeatable, highest priority first)",
    )
    diff.add_argument(
        "--no-config",
        action="store_true",
        help="ignore .sagelint / .sagelint.local; diff the repo root with no base (pass --base)",
    )
    diff.add_argument(
        "--strings",
        action="store_true",
        help="also report .str / .csv display-string changes (off by default)",
    )

    args = parser.parse_args(argv)

    if args.command == "format":
        if args.stdin:
            if args.paths:
                parser.error("paths and --stdin are mutually exclusive")
        else:
            if not args.paths:
                parser.error("the following arguments are required: paths (or use --stdin)")
            missing = [p for p in args.paths if not p.exists()]
            if missing:
                parser.error(f"no such file or directory: {missing[0]}")
        return _run_format(args)

    if args.command == "lint":
        if args.list_codes:
            return _run_list_codes()
        if args.write_baseline and args.fix:
            parser.error("--write-baseline cannot be combined with --fix")
        if args.write_baseline and args.no_config and args.baseline is None:
            parser.error("--write-baseline needs a path: pass --baseline or drop --no-config")
        config = _load_lint_config(args)
        root = _effective_root(args, config)
        if args.file is not None:
            if not args.file.is_file():
                parser.error(f"not a file: {args.file}")
            if root is not None and not root.is_dir():
                parser.error(f"not a directory: {root}")
        else:
            if root is None:
                parser.error(
                    "the following arguments are required: root "
                    "(or use --file, or set 'root' in .sagelint)"
                )
            if not root.is_dir():
                parser.error(f"not a directory: {root}")
        return _run_lint(args, config, root)

    if args.command == "lint-maps":
        config = _load_lint_config(args)
        root = _effective_root(args, config)
        if root is None:
            parser.error("the following arguments are required: root (or set 'root' in .sagelint)")
        if not root.is_dir():
            parser.error(f"not a directory: {root}")
        return _run_lint_maps(args, config, root)

    if args.command == "diff":
        return _run_diff(args, parser)

    if args.command == "serve":
        return _run_serve(args)

    if args.command == "init":
        return _run_init(args)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
