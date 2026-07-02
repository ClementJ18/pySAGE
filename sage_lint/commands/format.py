"""The `format` command: rewrite ini files to the canonical style (or report them with
`--check`, or format a stdin buffer for an editor's format-on-save), honouring the
`.sagelint` alignment options.
"""

import argparse
import json
import sys
from pathlib import Path

from sage_ini.parser.io import iter_ini_files
from sage_lint.commands.common import diagnostic_dict, split_codes
from sage_lint.config import Config, load_config
from sage_lint.formatter import FormatResult, format_file, format_text


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
    exclude = split_codes(args.align_exclude) or set(config.align_exclude)
    return align_equals, tuple(exclude)


def run_format(args: argparse.Namespace) -> int:
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
                "smells": [diagnostic_dict(d) for d in result.smells],
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
                    "smells": [diagnostic_dict(d) for d in result.smells],
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
