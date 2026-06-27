"""Command-line entry point: `python -m sage_ini <command>` (or `sage-ini`).

- `stats <dir>`  — the corpus parse-rate scoreboard.
- `lint <paths>` — assemble files/folders and report parse/load/conversion problems
  (the "does it convert?" facts; judgment rules live in `sage_lint`).
- `xref <dir> <name>` — what a definition references and what references it.
- `resolve <dir> <name>` — where a name or macro is defined (file:line).
- `includes <dir> <file>` — the files a file includes, and that include it.
- `brief <dir> <file>` — a single file's definitions, references, includes, and macros.
- `primer [full | expand <Kind> | enum <Name>]` — the compact model digest for an LLM agent.
- `install-skill` — install the bundled `bfme-ini` Claude Code skill.
"""

import argparse
from pathlib import Path

from sage_ini import primer as primer_module
from sage_ini.brief import build_brief, format_brief
from sage_ini.loader import load_game
from sage_ini.model.game import Game
from sage_ini.model.xref import Xref
from sage_ini.modindex import ModIndex
from sage_ini.parser.blockparser import parse_file
from sage_ini.parser.diagnostics import Diagnostics, Severity
from sage_ini.parser.location import Span
from sage_ini.skill_install import default_skills_dir, install_skill
from sage_ini.stats import compute_scoreboard, format_scoreboard
from sage_ini.suggest import did_you_mean


def _lint_paths(paths: list[Path]) -> Diagnostics:
    """Parse + load + validate each path (a folder is assembled as a whole game)."""
    diagnostics = Diagnostics()
    for path in paths:
        if path.is_dir():
            loaded = load_game(path)
            diagnostics.items.extend(loaded.diagnostics.items)
            diagnostics.items.extend(loaded.game.validate().items)
            continue
        result = parse_file(path, resolve_includes=True)
        diagnostics.items.extend(result.diagnostics.items)
        game = Game()
        try:
            game.load_document(result.document)
        except (ValueError, KeyError, TypeError, IndexError) as exc:
            diagnostics.add("load-error", f"{exc}", Span(str(path), 1, 1))
        diagnostics.items.extend(game.validate().items)
    return diagnostics


def _run_lint(paths: list[Path]) -> int:
    diagnostics = list(_lint_paths(paths))
    diagnostics.sort(key=lambda d: (d.span.file, d.span.line_start))
    for diagnostic in diagnostics:
        print(diagnostic)
    errors = sum(1 for d in diagnostics if d.severity is Severity.ERROR)
    print(f"{errors} error(s), {len(diagnostics) - errors} other(s)")
    return 1 if errors else 0


def _run_xref(root: Path, name: str) -> int:
    xref = Xref(load_game(root).game)
    matches = [
        (key, obj)
        for key, table in xref.game.tables.items()
        for obj_name, obj in table.items()
        if obj_name == name
    ]
    if not matches:
        print(f"no definition named {name!r} under {root}")
        return 1
    for key, obj in matches:
        print(f"{name} [{key}]")
        print("  references:")
        for target in sorted(xref.references(obj), key=lambda o: (o.key or "", o.name)):
            print(f"    -> {target.name} [{target.key}]")
        print("  referenced by:")
        for source in sorted(xref.referenced_by(obj), key=lambda o: (o.key or "", o.name)):
            print(f"    <- {source.name} [{source.key}]")
    return 0


def _run_resolve(root: Path, name: str) -> int:
    index = ModIndex(root)

    def site(span) -> str:
        return f"{index.rel(Path(span.file))}:{span.line_start}"

    found = False
    for definition in index.resolve(name):
        print(f"{definition.name} [{definition.table}]  {site(definition.span)}")
        found = True
    macro = index.macro(name)
    if macro is not None:
        where = f"  {site(macro.span)}" if macro.span is not None else "  (no recorded site)"
        print(f"#define {macro.name} = {macro.value}{where}")
        found = True
    if not found:
        names = {n for table in index.game.tables.values() for n in table}
        hint = did_you_mean(name, names | set(index.game.macros))
        print(f"no definition or macro named {name!r} under {root}" + (f"; {hint}" if hint else ""))
        return 1
    return 0


def _run_install_skill(dest: Path | None, force: bool) -> int:
    try:
        installed = install_skill(dest, force=force)
    except FileExistsError as exc:
        print(f"{exc} already exists; pass --force to overwrite")
        return 1
    print(f"installed skill to {installed}")
    return 0


def _run_brief(root: Path, file: Path, name: str | None) -> int:
    index = ModIndex(root)
    print(format_brief(build_brief(index, file, focus=name), index.rel))
    return 0


def _run_includes(root: Path, file: Path) -> int:
    index = ModIndex(root)
    target = file.resolve()
    includes = index.includes(target)
    included_by = index.included_by(target)
    print(f"{index.rel(target)} includes ({len(includes)}):")
    for path in includes:
        print(f"  -> {index.rel(path)}")
    print(f"included by ({len(included_by)}):")
    for path in included_by:
        print(f"  <- {index.rel(path)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sage_ini")
    subparsers = parser.add_subparsers(dest="command", required=True)

    stats = subparsers.add_parser("stats", help="print the corpus parse-rate scoreboard")
    stats.add_argument("root", type=Path, help="directory to scan for ini/inc/bhav files")
    stats.add_argument(
        "--overlay",
        type=Path,
        action="append",
        default=[],
        help="lower-priority ini root that includes may resolve into (repeatable)",
    )

    lint = subparsers.add_parser("lint", help="report parse/load/conversion problems")
    lint.add_argument("paths", type=Path, nargs="+", help="ini files or folders to assemble")

    xref = subparsers.add_parser("xref", help="show a definition's references, both directions")
    xref.add_argument("root", type=Path, help="folder of ini files to assemble")
    xref.add_argument("name", help="definition name to look up (e.g. GondorFighter)")

    resolve = subparsers.add_parser("resolve", help="where a name or macro is defined (file:line)")
    resolve.add_argument("root", type=Path, help="folder of ini files to assemble")
    resolve.add_argument("name", help="definition or macro name to locate")

    includes = subparsers.add_parser("includes", help="a file's include edges, both directions")
    includes.add_argument("root", type=Path, help="folder of ini files to assemble")
    includes.add_argument("file", type=Path, help="the ini file to inspect")

    brief = subparsers.add_parser("brief", help="a file's defs, references, includes, and macros")
    brief.add_argument("root", type=Path, help="folder of ini files to assemble")
    brief.add_argument("file", type=Path, help="the ini file to brief")
    brief.add_argument("name", nargs="?", help="narrow to one definition in the file")

    install = subparsers.add_parser("install-skill", help="install the bundled bfme-ini skill")
    install.add_argument(
        "--dest",
        type=Path,
        default=None,
        help=f"skills directory to install into (default: {default_skills_dir()})",
    )
    install.add_argument("--force", action="store_true", help="overwrite an existing install")

    primer = subparsers.add_parser("primer", help="emit the compact model digest for an LLM agent")
    primer.add_argument(
        "action",
        nargs="?",
        choices=["full", "expand", "enum"],
        help="full digest, expand one kind's schema, or list one enum's members "
        "(default: the lean index)",
    )
    primer.add_argument("name", nargs="?", help="kind name (expand) or enum name (enum)")

    args = parser.parse_args(argv)

    if args.command == "stats":
        if not args.root.is_dir():
            parser.error(f"not a directory: {args.root}")
        print(format_scoreboard(compute_scoreboard(args.root, overlays=tuple(args.overlay))))
        return 0

    if args.command == "lint":
        missing = [p for p in args.paths if not p.exists()]
        if missing:
            parser.error(f"no such file or directory: {missing[0]}")
        return _run_lint(args.paths)

    if args.command == "xref":
        if not args.root.is_dir():
            parser.error(f"not a directory: {args.root}")
        return _run_xref(args.root, args.name)

    if args.command == "resolve":
        if not args.root.is_dir():
            parser.error(f"not a directory: {args.root}")
        return _run_resolve(args.root, args.name)

    if args.command == "includes":
        if not args.root.is_dir():
            parser.error(f"not a directory: {args.root}")
        if not args.file.is_file():
            parser.error(f"not a file: {args.file}")
        return _run_includes(args.root, args.file)

    if args.command == "brief":
        if not args.root.is_dir():
            parser.error(f"not a directory: {args.root}")
        if not args.file.is_file():
            parser.error(f"not a file: {args.file}")
        return _run_brief(args.root, args.file, args.name)

    if args.command == "install-skill":
        return _run_install_skill(args.dest, args.force)

    if args.command == "primer":
        if args.action in ("expand", "enum") and not args.name:
            parser.error(f"{args.action} needs a name")
        if args.action == "expand":
            print(primer_module.expand_kind(args.name))
        elif args.action == "enum":
            print(primer_module.dump_enum(args.name))
        elif args.action == "full":
            print(primer_module.build_digest(), end="")
        else:
            print(primer_module.build_index(), end="")
        return 0

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
