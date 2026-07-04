"""Command-line interface for the Edain map checks (`python -m sage_edain.map_checks`)."""

import argparse
import sys
from pathlib import Path

from sage_ini.parser.diagnostics import Diagnostic, Severity
from sage_map.map import parse_map_from_path

from .findings import FINDINGS
from .linter import LintConfig, lint_map

_SEVERITY_ORDER = {Severity.INFO: 0, Severity.WARNING: 1, Severity.ERROR: 2}


def format_finding(diagnostic: Diagnostic, verbose: bool = False) -> str:
    """Format a finding for display."""
    severity_colors = {
        Severity.ERROR: "\033[91m",  # Red
        Severity.WARNING: "\033[93m",  # Yellow
        Severity.INFO: "\033[94m",  # Blue
    }
    reset_color = "\033[0m"

    line = f"[{diagnostic.code}] {diagnostic.message}"
    if verbose:
        color = severity_colors.get(diagnostic.severity, "")
        return f"{color}{diagnostic.severity.name}{reset_color} {line}"
    else:
        return line


def main():
    """Main entry point for the CLI."""
    parser = argparse.ArgumentParser(
        description="Lint BFME map files for common issues and best practices.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s map.map
  %(prog)s map.map --exclude MAP-013 MAP-014
  %(prog)s map.map --severity ERROR
  %(prog)s map.map --no-color --quiet
        """,
    )

    parser.add_argument("map_file", type=Path, help="Path to the .map file to lint")

    parser.add_argument(
        "-e",
        "--exclude",
        nargs="+",
        metavar="CODE",
        help="Error codes to exclude from results (e.g., MAP-013 MAP-014)",
    )

    parser.add_argument(
        "-s",
        "--severity",
        choices=["ERROR", "WARNING", "INFO"],
        help="Only show errors of this severity or higher",
    )

    parser.add_argument("--no-color", action="store_true", help="Disable colored output")

    parser.add_argument(
        "-q", "--quiet", action="store_true", help="Only show error count, not individual errors"
    )

    parser.add_argument("-v", "--verbose", action="store_true", help="Show verbose error messages")

    parser.add_argument(
        "--list-codes", action="store_true", help="List all possible error codes and exit"
    )

    # LintConfig toggles
    parser.add_argument("--no-validation", action="store_true", help="Skip validation checks")
    parser.add_argument("--no-flatness", action="store_true", help="Skip flatness checks")
    parser.add_argument("--no-resources", action="store_true", help="Skip resource checks")
    parser.add_argument("--no-performance", action="store_true", help="Skip performance checks")

    # LintConfig thresholds
    defaults = LintConfig()
    parser.add_argument(
        "--min-camera-max-height",
        type=int,
        default=defaults.min_camera_max_height,
        metavar="N",
        help=f"Minimum cameraMaxHeight value (default: {defaults.min_camera_max_height})",
    )
    parser.add_argument(
        "--min-border-distance",
        type=int,
        default=defaults.min_border_distance,
        metavar="N",
        help="Minimum distance from map border for plot flags "
        f"(default: {defaults.min_border_distance})",
    )
    parser.add_argument(
        "--farm-flatness-check-radius",
        type=int,
        default=defaults.farm_flatness_check_radius,
        metavar="N",
        help="Radius used when checking farm template flatness "
        f"(default: {defaults.farm_flatness_check_radius})",
    )
    parser.add_argument(
        "--farm-flatness-threshold",
        type=float,
        default=defaults.farm_flatness_threshold,
        metavar="F",
        help="Minimum flat-tile ratio for farm templates, 0–1 "
        f"(default: {defaults.farm_flatness_threshold})",
    )
    parser.add_argument(
        "--required-trees-near-wirtschaft",
        type=int,
        default=defaults.required_trees_near_wirtschaft,
        metavar="N",
        help="Minimum trees required near a Wirtschaft flag "
        f"(default: {defaults.required_trees_near_wirtschaft})",
    )
    parser.add_argument(
        "--wirtschaft-tree-search-radius",
        type=int,
        default=defaults.wirtschaft_tree_search_radius,
        metavar="N",
        help="Search radius for trees around a Wirtschaft flag "
        f"(default: {defaults.wirtschaft_tree_search_radius})",
    )
    parser.add_argument(
        "--max-recommended-objects",
        type=int,
        default=defaults.max_recommended_objects,
        metavar="N",
        help="Object count above which a performance warning is raised "
        f"(default: {defaults.max_recommended_objects})",
    )

    args = parser.parse_args()

    if args.list_codes:
        print_error_codes()
        return 0

    if not args.map_file.exists():
        print(f"Error: Map file not found: {args.map_file}", file=sys.stderr)
        return 1

    try:
        print(f"Linting {args.map_file}...")
        map_obj = parse_map_from_path(str(args.map_file))
    except Exception as e:  # noqa: BLE001 — CLI boundary: report the parse failure and exit
        print(f"Error: Failed to parse map file: {e}", file=sys.stderr)
        return 1

    config = LintConfig(
        run_validation=not args.no_validation,
        run_flatness=not args.no_flatness,
        run_resources=not args.no_resources,
        run_performance=not args.no_performance,
        exclude_codes=args.exclude or [],
        min_camera_max_height=args.min_camera_max_height,
        min_border_distance=args.min_border_distance,
        farm_flatness_check_radius=args.farm_flatness_check_radius,
        farm_flatness_threshold=args.farm_flatness_threshold,
        required_trees_near_wirtschaft=args.required_trees_near_wirtschaft,
        wirtschaft_tree_search_radius=args.wirtschaft_tree_search_radius,
        max_recommended_objects=args.max_recommended_objects,
    )

    findings = list(lint_map(map_obj, config, path=args.map_file))

    if args.severity:
        min_severity = _SEVERITY_ORDER[Severity[args.severity]]
        findings = [d for d in findings if _SEVERITY_ORDER[d.severity] >= min_severity]

    if not args.quiet:
        if findings:
            for diagnostic in findings:
                if args.no_color:
                    print(f"[{diagnostic.code}] {diagnostic.message}")
                else:
                    print(format_finding(diagnostic, args.verbose))
        else:
            print("✓ No issues found!")

    error_count = sum(1 for d in findings if d.severity is Severity.ERROR)
    warning_count = sum(1 for d in findings if d.severity is Severity.WARNING)
    info_count = sum(1 for d in findings if d.severity is Severity.INFO)

    print(f"\nSummary: {error_count} error(s), {warning_count} warning(s), {info_count} info")

    return 1 if error_count > 0 else 0


def print_error_codes():
    print("Available error codes:\n")
    for code, (severity, template) in sorted(FINDINGS.items()):
        description = template.split("{")[0].strip() or template
        severity_label = f"[{severity.name}]".ljust(10)
        print(f"  {code}: {severity_label} {description}")


if __name__ == "__main__":
    sys.exit(main())
