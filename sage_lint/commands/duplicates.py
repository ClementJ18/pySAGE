"""The `duplicates` command: parse every ini file under the root (includes left literal, so
already-shared content is never re-flagged) and report duplicated chunks - identical blocks
and identical contiguous runs of sibling lines - worth extracting into a shared `#include`.
Detection lives in `sage_lint.duplicates`; this module is the option plumbing and the report.
"""

import argparse
import json
import sys
from pathlib import Path

from sage_lint.commands.common import config_path
from sage_lint.config import Config

DEFAULT_MIN_LINES = 10
DEFAULT_MIN_OCCURRENCES = 2

# --verbose snippets are truncated to this many lines: enough to recognise the chunk, short
# enough that a report of many clusters stays scrollable.
_SNIPPET_LINES = 20


def _cluster_dict(cluster) -> dict[str, object]:
    return {
        "kind": cluster.kind,
        "title": cluster.title,
        "lines": cluster.lines,
        "saved_lines": cluster.saved_lines,
        "snippet": cluster.snippet,
        "occurrences": [
            {"file": span.file, "line_start": span.line_start, "line_end": span.line_end}
            for span in cluster.occurrences
        ],
    }


def _print_snippet(snippet: str) -> None:
    lines = snippet.splitlines()
    for line in lines[:_SNIPPET_LINES]:
        print(f"    | {line}")
    if len(lines) > _SNIPPET_LINES:
        print(f"    | ... (+{len(lines) - _SNIPPET_LINES} more lines)")


def run_duplicates(args: argparse.Namespace, config: Config, root: Path) -> int:
    """Scan `root`, report duplicate clusters largest-saving-first, and exit 0 - the report
    is advisory (SAGE data is pervasively duplicated by history; there is no 'clean' state to
    enforce), so the exit code never fails a pipeline. Parse errors are counted on stderr and
    the affected files still contribute whatever the parser recovered."""
    # Lazy: parsing and detection are only paid for by this command.
    from sage_ini.parser.blockparser import parse_file  # noqa: PLC0415 - lazy
    from sage_ini.parser.diagnostics import Severity  # noqa: PLC0415 - lazy
    from sage_ini.parser.io import iter_ini_files  # noqa: PLC0415 - lazy
    from sage_lint.duplicates import find_duplicates  # noqa: PLC0415 - lazy

    min_lines = args.min_lines or config.duplicate_min_lines or DEFAULT_MIN_LINES
    min_occurrences = (
        args.min_occurrences or config.duplicate_min_occurrences or DEFAULT_MIN_OCCURRENCES
    )
    excludes = (
        list(args.exclude) if args.exclude else [config_path(root, e) for e in config.exclude]
    )
    excluded = tuple(Path(directory).resolve() for directory in excludes)

    documents = []
    error_files = 0
    for path in iter_ini_files(root):
        if any(path.resolve().is_relative_to(directory) for directory in excluded):
            continue
        result = parse_file(path, resolve_includes=False)
        if any(diag.severity is Severity.ERROR for diag in result.diagnostics):
            error_files += 1
        documents.append(result.document)
    if error_files:
        print(
            f"sage_lint: {error_files} file(s) had parse errors; "
            "duplicates reported from the recovered tree",
            file=sys.stderr,
        )

    clusters = find_duplicates(documents, min_lines=min_lines, min_occurrences=min_occurrences)
    saved_total = sum(cluster.saved_lines for cluster in clusters)
    files_involved = len({span.file for cluster in clusters for span in cluster.occurrences})

    if args.output_format == "json":
        report = {
            "clusters": [_cluster_dict(cluster) for cluster in clusters],
            "summary": {
                "clusters": len(clusters),
                "saved_lines": saved_total,
                "files_scanned": len(documents),
                "parse_error_files": error_files,
            },
        }
        print(json.dumps(report, indent=2))
        return 0

    if not args.quiet:
        for cluster in clusters:
            print(
                f"duplicate {cluster.kind} '{cluster.title}': "
                f"{len(cluster.occurrences)} occurrences x {cluster.lines} lines "
                f"(~{cluster.saved_lines} lines saved with an #include)"
            )
            for span in cluster.occurrences:
                print(f"  {span}")
            if args.verbose:
                _print_snippet(cluster.snippet)
    if clusters:
        print(
            f"{len(clusters)} duplicate cluster(s), ~{saved_total} line(s) extractable "
            f"across {files_involved} file(s)"
        )
    else:
        print("no duplicates found")
    return 0
