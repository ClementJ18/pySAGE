"""The `rename` command: rename a definition and every reference to it across a mod's ini data.

The run assembles the game once, plans the rewrite from the typed model (`sage_lint.rename`),
adds the map.ini contexts - which are per-map overlays the global build deliberately leaves out -
then finishes with a whole-tree token scan so nothing the schema does not model can go silently
un-renamed. Binary `.map` layouts are reported and never touched: they belong to the map author,
and `sage-lint lint-maps` reports afterwards exactly what this warned about.

Only files under the rename root are ever rewritten. A base game merged in with `--base` is
there so the mod's references resolve, and both the definition and every reference inside it are
left alone - a base tree is not this run's to edit.

Nothing is written without `--apply`. The default is the plan, so the destructive step is always
a second, deliberate invocation.
"""

import argparse
import json
import sys
from pathlib import Path

from sage_ini.loader import map_files
from sage_ini.model.game import Game
from sage_ini.model.objects import REGISTRY, IniObject
from sage_ini.parser.io import iter_ini_files
from sage_lint.commands.common import base_paths, base_source
from sage_lint.config import Config
from sage_lint.linter import assemble_with_bases, lint_file_cached_game
from sage_lint.rename import (
    RenamePlan,
    RenameSite,
    apply_plan,
    check_conflicts,
    collect_sites,
    dedupe_sites,
    scan_text,
)

# How many unaccounted text hits the human-readable report lists before summarising the rest.
_MAX_LISTED = 40


def _tables() -> dict[str, str]:
    """`table key -> the block keywords that declare into it`, for `--list-tables`."""
    tables: dict[str, set[str]] = {}
    for name, cls in REGISTRY.items():
        if isinstance(cls, type) and issubclass(cls, IniObject) and cls.key:
            tables.setdefault(cls.key, set()).add(name)
    return {key: ", ".join(sorted(names)) for key, names in sorted(tables.items())}


def _resolve_table(game: Game, old: str, requested: str | None) -> tuple[str | None, list[str]]:
    """The table `old` lives in, as `(table, problems)`.

    Without `--table` the name is looked up in every table: exactly one hit is unambiguous and is
    used; several mean the same bareword names more than one kind of definition, which only the
    caller can resolve, so the candidates are reported rather than guessed at."""
    if requested is not None:
        return requested, []
    hits = [key for key in sorted(game.tables) if game.lookup(key, old)[0] is not None]
    if len(hits) == 1:
        return hits[0], []
    if not hits:
        return None, [f"no definition named {old!r} in any table"]
    return None, [f"{old!r} names a definition in several tables ({', '.join(hits)}); pass --table"]


def _under(path: str | Path, root: Path) -> bool:
    """Whether `path` is inside `root` - the test for "this run owns this file"."""
    try:
        Path(path).resolve().relative_to(root)
    except (ValueError, OSError):
        return False
    return True


def _map_ini_sites(game: Game, root: Path, table: str, old: str) -> list[RenameSite]:
    """Sites inside the map.ini overlays under `root`.

    Each map.ini is a per-map context the global build excludes, so its references are invisible
    to the whole-game pass and have to be planned separately. Building one is the linter's
    single-file build against the already-assembled game - the map's own objects, with everything
    else resolved through the cache - rather than a fresh per-map game, which would re-assemble
    the whole mod once per map. A text prefilter keeps a map that never mentions the name from
    being built at all."""
    sites: list[RenameSite] = []
    needle = old.lower()
    for path in map_files(root):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if needle not in text.lower():
            continue
        try:
            _diagnostics, built = lint_file_cached_game(game, path, include_root=root)
        except (OSError, ValueError, KeyError, TypeError, IndexError):
            continue  # an unbuildable map.ini is the text scan's to report
        if built is not None:
            sites.extend(collect_sites(built, table, old, origin=str(path)))
    return sites


def _scan_map_layouts(game: Game, root: Path, table: str, old: str) -> tuple[list[str], list[str]]:
    """`(warnings, unreadable)` naming every binary `.map` under `root` that references the
    symbol. Imported lazily so a rename that skips maps never pays for the binary map reader."""
    from sage_lint.rename_maps import scan_maps  # noqa: PLC0415 - lazy: only paid for on a map scan

    paths = [path for path in game.map_files if _under(path, root)]
    usages, unreadable = scan_maps(paths, table, old)
    return [str(usage) for usage in usages], unreadable


def build_plan(args: argparse.Namespace, config: Config, root: Path) -> RenamePlan:
    """Assemble the game and work out everything the rename would touch."""
    root = root.resolve()
    bases = tuple(base_source(path) for path in base_paths(args, config, root, False))
    loaded, base_layer = assemble_with_bases(root, bases)
    try:
        return _plan_for(args, loaded.game, root)
    finally:
        if base_layer is not None:
            base_layer.cleanup()


def _plan_for(args: argparse.Namespace, game: Game, root: Path) -> RenamePlan:
    """The plan for an already-assembled `game`, with every site outside `root` dropped."""
    table, problems = _resolve_table(game, args.old, args.table)
    if table is None:
        return RenamePlan("<unknown>", args.old, args.new, conflicts=problems)

    plan = RenamePlan(table, args.old, args.new)
    plan.conflicts = check_conflicts(game, table, args.old, args.new, root)

    found = dedupe_sites(
        [collect_sites(game, table, args.old), _map_ini_sites(game, root, table, args.old)]
    )
    plan.sites = [site for site in found if _under(site.file, root)]

    promoted, unaccounted = scan_text(iter_ini_files(root), table, args.old, plan.sites)
    plan.sites = dedupe_sites([plan.sites, promoted])
    plan.unaccounted = unaccounted

    if not args.no_maps:
        warnings, unreadable = _scan_map_layouts(game, root, table, args.old)
        plan.map_warnings = [*warnings, *(f"unreadable: {entry}" for entry in unreadable)]
    return plan


def _plan_dict(plan: RenamePlan, applied: dict[str, int] | None) -> dict[str, object]:
    """The JSON form of a plan, for the editor plugin."""
    return {
        "table": plan.table,
        "old": plan.old,
        "new": plan.new,
        "conflicts": plan.conflicts,
        "sites": [
            {
                "file": site.file,
                "line": site.line,
                "anchor": site.anchor.value,
                "detail": site.detail,
                "origin": site.origin,
            }
            for site in plan.sites
        ],
        "unaccounted": [
            {"file": hit.file, "line": hit.line, "text": hit.text} for hit in plan.unaccounted
        ],
        "map_warnings": plan.map_warnings,
        "applied": applied or {},
        "summary": {
            "files": len(plan.files),
            "sites": len(plan.sites),
            "unaccounted": len(plan.unaccounted),
            "maps": len(plan.map_warnings),
            "lines_changed": sum((applied or {}).values()),
        },
    }


def _print_plan(plan: RenamePlan, applied: dict[str, int] | None) -> None:
    """The human-readable report: what would change, what will break, what needs a human."""
    verb = "renamed" if applied is not None else "would rename"
    print(f"{plan.table} {plan.old!r} -> {plan.new!r}")

    if plan.conflicts:
        print("\nblocked:")
        for problem in plan.conflicts:
            print(f"  - {problem}")
        return

    grouped = plan.sites_by_file()
    print(f"\n{verb} {len(plan.sites)} site(s) in {len(grouped)} file(s):")
    for path, sites in sorted(grouped.items()):
        changed = f"  [{applied[path]} line(s) changed]" if applied and path in applied else ""
        print(f"  {path}{changed}")
        for site in sites:
            print(f"    {site.line}: {site.detail}")

    if plan.map_warnings:
        print(f"\nreferenced by {len(plan.map_warnings)} binary .map location(s) - NOT rewritten:")
        for warning in plan.map_warnings:
            print(f"  - {warning}")
        print("  these become dangling references; fix them in WorldBuilder.")

    if plan.unaccounted:
        print(f"\n{len(plan.unaccounted)} unaccounted occurrence(s) - review by hand:")
        for hit in plan.unaccounted[:_MAX_LISTED]:
            print(f"  {hit.file}:{hit.line}: {hit.text}")
        if len(plan.unaccounted) > _MAX_LISTED:
            print(f"  ... and {len(plan.unaccounted) - _MAX_LISTED} more")

    if applied is None:
        print("\nnothing written (pass --apply to perform the rename)")


def run_rename(args: argparse.Namespace, config: Config, root: Path) -> int:
    """Plan the rename, report it, and - only with `--apply` - perform it.

    Returns 1 when the rename is blocked, so a script can branch on it. An unaccounted occurrence
    is not itself a failure (it is a thing to look at), and neither is a `.map` reference.
    """
    plan = build_plan(args, config, root)

    applied: dict[str, int] | None = None
    if args.apply and not plan.conflicts:
        applied = apply_plan(plan)

    if args.json:
        json.dump(_plan_dict(plan, applied), sys.stdout, indent=2)
        print()
    else:
        _print_plan(plan, applied)
    return 1 if plan.conflicts else 0


def print_tables() -> int:
    """List the table keys `--table` accepts, with the block keywords that declare into each."""
    for key, keywords in _tables().items():
        print(f"{key:24} {keywords}")
    return 0


def add_rename_arguments(parser: argparse.ArgumentParser) -> None:
    """The `rename` argument surface."""
    # The shared config/root resolution reads `--file` (the single-file lint path); a rename is
    # always whole-tree, so it declares the attribute rather than growing a flag that does nothing.
    parser.set_defaults(file=None)
    parser.add_argument("root", type=Path, nargs="?", help="folder of ini files to assemble")
    parser.add_argument("old", nargs="?", help="the definition name to rename")
    parser.add_argument("new", nargs="?", help="the name to rename it to")
    parser.add_argument(
        "--table",
        default=None,
        help="the table the definition lives in (objects, weapons, upgrades, ...). Only needed "
        "when one bareword names a definition in more than one table; otherwise it is inferred. "
        "Use --list-tables to see them.",
    )
    parser.add_argument(
        "--list-tables",
        action="store_true",
        help="list the table keys --table accepts, with the block keywords that declare into "
        "each, then exit",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="perform the rename. Without it the command only reports what it would change, so "
        "the destructive step is always a second, deliberate invocation.",
    )
    parser.add_argument(
        "--no-maps",
        action="store_true",
        help="skip the binary .map scan. The scan parses every .map under the root to warn which "
        "layouts reference the symbol (they are never rewritten); skipping it makes the run much "
        "faster at the cost of that warning.",
    )
    parser.add_argument(
        "--base",
        type=Path,
        action="append",
        default=[],
        help="base-game source (folder or .big) loaded beneath the mod so its references "
        "resolve; never rewritten (repeatable, highest priority first)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="emit the plan as JSON (the editor plugin's format) instead of a text report",
    )
    parser.add_argument(
        "--no-config",
        action="store_true",
        help="ignore .sagelint / .sagelint.local; use flags and built-in defaults only",
    )
