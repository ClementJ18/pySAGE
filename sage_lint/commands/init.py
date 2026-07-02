"""The `init` command: scaffold a `.sagelint` config (and a commented `.sagelint.local`)
in a mod folder, reporting what the linter detected there.
"""

import argparse
import sys

from sage_lint.config import CONFIG_NAME, init_project


def run_init(args: argparse.Namespace) -> int:
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
