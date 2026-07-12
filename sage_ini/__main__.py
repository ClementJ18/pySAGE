"""Command-line entry point: `python -m sage_ini <command>` (or `sage-ini`).

- `stats <dir>`  - the corpus parse-rate scoreboard.
- `lint <paths>` - assemble files/folders and report parse/load/conversion problems
  (the "does it convert?" facts; judgment rules live in `sage_lint`).
- `xref <dir> <name>` - what a definition references and what references it.
- `resolve <dir> <name>` - where a name or macro is defined (file:line).
- `includes <dir> <file>` - the files a file includes, and that include it.
- `brief <dir> <file>` - a single file's definitions, references, includes, and macros.
- `diff <old> <new>` - a human-readable changelog between two ini folders (or two git refs).
- `primer [full | expand <Kind> | enum <Name>]` - the compact model digest for an LLM agent.
- `install-skill` - install the bundled `bfme-ini` Claude Code skill.

The query commands (`lint`, `xref`, `resolve`, `brief`, `diff`) accept `--json` to emit the
same facts as machine-readable JSON for agents and tool builders.
- `merge` - structure-aware 3-way merge: a git merge driver, a conflict-marker resolver,
  and a git-config installer.
- `macro-merge <file>` - set-merge conflicted `#define` reference lists, reporting exactly
  what each side added/removed so one-sided deletions can be confirmed, not guessed.
"""

import argparse
import codecs
import json
import subprocess
from pathlib import Path

from sage_ini import primer as primer_module
from sage_ini.brief import brief_to_dict, build_brief, format_brief
from sage_ini.diff import diff_folders, diff_refs, format_game_diff
from sage_ini.loader import load_game
from sage_ini.macro_merge import format_macro_report, resolve_macro_conflicts
from sage_ini.merge import ConflictLabels, merge_documents, resolve_markers
from sage_ini.model.game import Game
from sage_ini.model.xref import Xref
from sage_ini.modindex import ModIndex
from sage_ini.parser.blockparser import parse, parse_file
from sage_ini.parser.diagnostics import Diagnostics, Severity
from sage_ini.parser.io import ENCODINGS
from sage_ini.parser.location import Span
from sage_ini.skill_install import install_skill
from sage_ini.stats import compute_scoreboard, format_scoreboard
from sage_ini.suggest import closest_names, did_you_mean
from sage_utils.cli import (
    add_install_skill_parser,
    existing_dir,
    existing_file,
    run_install_skill,
    utf8_stdout,
)


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


def _run_lint(paths: list[Path], as_json: bool = False) -> int:
    diagnostics = list(_lint_paths(paths))
    diagnostics.sort(key=lambda d: (d.span.file, d.span.line_start))
    errors = sum(1 for d in diagnostics if d.severity is Severity.ERROR)
    if as_json:
        print(
            json.dumps(
                {
                    "diagnostics": [d.to_dict() for d in diagnostics],
                    "summary": {"errors": errors, "others": len(diagnostics) - errors},
                },
                indent=2,
            )
        )
        return 1 if errors else 0
    for diagnostic in diagnostics:
        print(diagnostic)
    print(f"{errors} error(s), {len(diagnostics) - errors} other(s)")
    return 1 if errors else 0


def _xref_entry(obj) -> dict:
    """One graph neighbour as JSON-ready data, with its definition site when recorded."""
    span = getattr(obj, "span", None)
    return {
        "name": str(obj.name),
        "table": obj.key,
        "file": span.file if span is not None else None,
        "line": span.line_start if span is not None else None,
    }


def _run_xref(root: Path, name: str, as_json: bool = False) -> int:
    xref = Xref(load_game(root).game)
    matches = [
        (key, obj)
        for key, table in xref.game.tables.items()
        for obj_name, obj in table.items()
        if obj_name == name
    ]
    if not matches:
        if as_json:
            print(json.dumps({"name": name, "matches": []}, indent=2))
        else:
            print(f"no definition named {name!r} under {root}")
        return 1
    if as_json:
        payload = {
            "name": name,
            "matches": [
                {
                    "name": name,
                    "table": key,
                    "references": [
                        _xref_entry(target)
                        for target in sorted(
                            xref.references(obj), key=lambda o: (o.key or "", o.name)
                        )
                    ],
                    "referenced_by": [
                        _xref_entry(source)
                        for source in sorted(
                            xref.referenced_by(obj), key=lambda o: (o.key or "", o.name)
                        )
                    ],
                }
                for key, obj in matches
            ],
        }
        print(json.dumps(payload, indent=2))
        return 0
    for key, obj in matches:
        print(f"{name} [{key}]")
        print("  references:")
        for target in sorted(xref.references(obj), key=lambda o: (o.key or "", o.name)):
            print(f"    -> {target.name} [{target.key}]")
        print("  referenced by:")
        for source in sorted(xref.referenced_by(obj), key=lambda o: (o.key or "", o.name)):
            print(f"    <- {source.name} [{source.key}]")
    return 0


def _run_resolve(root: Path, name: str, as_json: bool = False) -> int:
    index = ModIndex(root)

    def site(span) -> str:
        return f"{index.rel(Path(span.file))}:{span.line_start}"

    definitions = list(index.resolve(name))
    macro = index.macro(name)

    if as_json:
        payload: dict = {
            "name": name,
            "definitions": [
                {
                    "name": str(definition.name),
                    "table": definition.table,
                    "file": str(index.rel(Path(definition.span.file))),
                    "line": definition.span.line_start,
                }
                for definition in definitions
            ],
            "macro": None,
            "suggestions": [],
        }
        if macro is not None:
            payload["macro"] = {
                "name": macro.name,
                "value": macro.value,
                "file": str(index.rel(Path(macro.span.file))) if macro.span is not None else None,
                "line": macro.span.line_start if macro.span is not None else None,
            }
        if not definitions and macro is None:
            names = {n for table in index.game.tables.values() for n in table}
            payload["suggestions"] = closest_names(name, names | set(index.game.macros))
        print(json.dumps(payload, indent=2))
        return 0 if (definitions or macro is not None) else 1

    found = False
    for definition in definitions:
        print(f"{definition.name} [{definition.table}]  {site(definition.span)}")
        found = True
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


def _run_brief(root: Path, file: Path, name: str | None, as_json: bool = False) -> int:
    index = ModIndex(root)
    brief = build_brief(index, file, focus=name)
    if as_json:
        print(json.dumps(brief_to_dict(brief, index.rel), indent=2))
    else:
        print(format_brief(brief, index.rel))
    return 0


def _run_diff(args: argparse.Namespace) -> int:
    overlays = tuple(args.overlay)
    if args.repo is not None:
        diff = diff_refs(
            args.repo,
            args.old,
            args.new,
            args.path,
            strings=args.strings,
            overlays=overlays,
        )
        old_label, new_label = args.old, args.new
    else:
        old_dir, new_dir = Path(args.old), Path(args.new)
        for label, path in (("old", old_dir), ("new", new_dir)):
            if not path.is_dir():
                print(f"{label} is not a directory: {path} (pass --repo to diff git refs)")
                return 2
        diff = diff_folders(old_dir, new_dir, strings=args.strings, overlays=overlays)
        old_label, new_label = str(old_dir), str(new_dir)
    if args.json:
        print(json.dumps({"old": old_label, "new": new_label, **diff.to_dict()}, indent=2))
    else:
        print(format_game_diff(diff, old_label, new_label), end="")
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


_MERGE_DRIVER = "sage-ini merge %O %A %B -L %L -P %P"


def _install_merge_driver(global_: bool) -> int:
    """Register the merge driver in git config and print the `.gitattributes` wiring."""
    scope = ["--global"] if global_ else []
    try:
        for key, value in (
            ("merge.sage-ini.name", "SAGE ini structure-aware merge"),
            ("merge.sage-ini.driver", _MERGE_DRIVER),
        ):
            subprocess.run(["git", "config", *scope, key, value], check=True)
    except FileNotFoundError:
        print("git not found on PATH")
        return 1
    except subprocess.CalledProcessError as exc:
        print(f"git config failed: {exc}")
        return 1
    where = "global git config" if global_ else "this repository's git config"
    print(f"registered the 'sage-ini' merge driver in {where}.")
    print("add this line to .gitattributes so git routes ini files through it:")
    print("    *.ini merge=sage-ini")
    print("    *.inc merge=sage-ini")
    return 0


def _read_once(path: Path) -> tuple[str, str]:
    """Read a file a single time and return (text, encoding-to-write-back-in), decoding with
    sage_ini's fallback (utf-8-sig / windows-1252 / latin-1, since SAGE data mixes them).

    Reading exactly once matters for the git merge driver: git's `ort` strategy creates and
    deletes the %O/%A/%B temp files around each driver call (and runs extra inner merges), so a
    second read of the same path can race and fail. A missing file is treated as empty utf-8 so
    the driver never crashes - a crash would abort the whole merge."""
    try:
        data = path.read_bytes()
    except FileNotFoundError:
        return "", "utf-8"
    encoding = ENCODINGS[-1]
    text = None
    for candidate in ENCODINGS[:-1]:
        try:
            text = data.decode(candidate)
            encoding = candidate
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        text = data.decode(encoding)
    # utf-8-sig reports even for BOM-less files; writing it back would add a BOM that was
    # never there, so downgrade to plain utf-8 unless the file actually starts with one.
    if encoding == "utf-8-sig" and not data.startswith(codecs.BOM_UTF8):
        encoding = "utf-8"
    return text, encoding


def _write_back(out: Path, text: str, encoding: str, newline: str | None = None) -> None:
    """Write the merged text in the source's encoding, falling back to utf-8 if the merged
    content (e.g. pulled from a utf-8 `theirs`) has characters the source's legacy encoding
    cannot represent - better a re-encoded file than a crash that aborts the merge.

    `newline=""` disables the platform newline translation so text that already carries its
    own CRLF/LF terminators is written verbatim (otherwise Windows would double the CR)."""
    try:
        out.write_text(text, encoding=encoding, newline=newline)
    except UnicodeEncodeError:
        out.write_text(text, encoding="utf-8", newline=newline)


def _run_macro_merge(args: argparse.Namespace) -> int:
    text, encoding = _read_once(args.file)
    result = resolve_macro_conflicts(text, marker_size=args.marker_size)
    if args.json:
        print(
            json.dumps(
                {
                    "resolved": result.resolved,
                    "remaining": result.remaining,
                    "macros": [
                        {
                            "name": m.name,
                            "merged": m.merged,
                            "added_ours": m.added_ours,
                            "added_theirs": m.added_theirs,
                            "removed_ours": m.removed_ours,
                            "removed_theirs": m.removed_theirs,
                            "removed_one_side": [
                                {"token": t, "side": s} for t, s in m.removed_one_side
                            ],
                            "duplicates": m.duplicates,
                            "has_base": m.has_base,
                        }
                        for m in result.merges
                    ],
                },
                indent=2,
            )
        )
    else:
        print(format_macro_report(result))

    if result.resolved == 0:
        return 1 if result.remaining else 0
    if args.write:
        out = args.output or args.file
        _write_back(out, result.text, encoding, newline="")
        if not args.json:
            print(f"\nwrote {out}")
    elif not args.json:
        print("\n(dry run - pass --write to apply; no files changed)")
    return 1 if result.remaining else 0


def _run_merge(args: argparse.Namespace) -> int:
    labels = ConflictLabels(ours=args.ours_label, theirs=args.theirs_label)

    if args.install:
        return _install_merge_driver(args.global_)

    if args.resolve is not None:
        text, encoding = _read_once(args.resolve)
        result = resolve_markers(text, labels=labels, marker_size=args.marker_size)
        out = args.output or args.resolve
        _write_back(out, result.text, encoding)
        print(
            f"{'unresolved' if result.conflicts else 'resolved'} "
            f"{result.conflicts} conflict(s) -> {out}"
        )
        return 1 if result.conflicts else 0

    # Driver mode: git passes base (%O), ours (%A), theirs (%B); ours is written back in its
    # own encoding. Each version is read exactly once (see _read_once) and parsed here.
    ours_text, ours_encoding = _read_once(args.ours)
    theirs_text, _ = _read_once(args.theirs)
    base_doc = None
    if args.base is not None:
        base_text, _ = _read_once(args.base)
        base_doc = parse(base_text, file=str(args.base)).document
    result = merge_documents(
        base_doc,
        parse(ours_text, file=str(args.ours)).document,
        parse(theirs_text, file=str(args.theirs)).document,
        labels=labels,
        marker_size=args.marker_size,
    )
    out = args.output or args.ours
    _write_back(out, result.text, ours_encoding)
    if result.conflicts:
        print(f"{result.conflicts} conflict(s) remain in {out}")
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    utf8_stdout()
    parser = argparse.ArgumentParser(prog="sage_ini")
    subparsers = parser.add_subparsers(dest="command", required=True)

    stats = subparsers.add_parser("stats", help="print the corpus parse-rate scoreboard")
    stats.add_argument("root", type=existing_dir, help="directory to scan for ini/inc/bhav files")
    stats.add_argument(
        "--overlay",
        type=Path,
        action="append",
        default=[],
        help="lower-priority ini root that includes may resolve into (repeatable)",
    )

    lint = subparsers.add_parser("lint", help="report parse/load/conversion problems")
    lint.add_argument("paths", type=Path, nargs="+", help="ini files or folders to assemble")
    lint.add_argument("--json", action="store_true", help="emit the report as JSON")

    xref = subparsers.add_parser("xref", help="show a definition's references, both directions")
    xref.add_argument("root", type=existing_dir, help="folder of ini files to assemble")
    xref.add_argument("name", help="definition name to look up (e.g. GondorFighter)")
    xref.add_argument("--json", action="store_true", help="emit the graph neighbours as JSON")

    resolve = subparsers.add_parser("resolve", help="where a name or macro is defined (file:line)")
    resolve.add_argument("root", type=existing_dir, help="folder of ini files to assemble")
    resolve.add_argument("name", help="definition or macro name to locate")
    resolve.add_argument("--json", action="store_true", help="emit the definition sites as JSON")

    includes = subparsers.add_parser("includes", help="a file's include edges, both directions")
    includes.add_argument("root", type=existing_dir, help="folder of ini files to assemble")
    includes.add_argument("file", type=existing_file, help="the ini file to inspect")

    brief = subparsers.add_parser("brief", help="a file's defs, references, includes, and macros")
    brief.add_argument("root", type=existing_dir, help="folder of ini files to assemble")
    brief.add_argument("file", type=existing_file, help="the ini file to brief")
    brief.add_argument("name", nargs="?", help="narrow to one definition in the file")
    brief.add_argument("--json", action="store_true", help="emit the briefing as JSON (uncapped)")

    diff = subparsers.add_parser(
        "diff", help="human-readable changelog between two ini folders (or two git refs)"
    )
    diff.add_argument("old", help="old ini folder, or a git ref with --repo")
    diff.add_argument("new", help="new ini folder, or a git ref with --repo")
    diff.add_argument(
        "--repo",
        type=Path,
        default=None,
        help="git repo: treat old/new as refs and materialise each in a temp worktree",
    )
    diff.add_argument(
        "--path",
        default=".",
        help="ini subfolder within the repo to diff (with --repo; default: repo root)",
    )
    diff.add_argument(
        "--overlay",
        type=Path,
        action="append",
        default=[],
        help="lower-priority ini root that includes may resolve into (repeatable)",
    )
    diff.add_argument(
        "--strings", action="store_true", help="also report .str/.csv display-string changes"
    )
    diff.add_argument("--json", action="store_true", help="emit the changelog as JSON")

    add_install_skill_parser(subparsers, "bfme-ini")

    merge = subparsers.add_parser(
        "merge", help="structure-aware 3-way merge (git merge driver / conflict resolver)"
    )
    merge.add_argument("base", type=Path, nargs="?", help="common ancestor (git %%O)")
    merge.add_argument("ours", type=Path, nargs="?", help="our version, written back (git %%A)")
    merge.add_argument("theirs", type=Path, nargs="?", help="their version (git %%B)")
    merge.add_argument(
        "-o", "--output", type=Path, default=None, help="write result here instead of ours"
    )
    merge.add_argument(
        "-L", "--marker-size", type=int, default=7, help="conflict marker length (git %%L)"
    )
    merge.add_argument(
        "-P", "--pathname", default=None, help="merged file's path, for messages (git %%P)"
    )
    merge.add_argument("--ours-label", default="ours", help="label on the <<< conflict side")
    merge.add_argument("--theirs-label", default="theirs", help="label on the >>> conflict side")
    merge.add_argument(
        "--resolve",
        type=Path,
        default=None,
        metavar="FILE",
        help="re-merge a file that already has conflict markers",
    )
    merge.add_argument(
        "--install",
        action="store_true",
        help="register this as a git merge driver (see --global)",
    )
    merge.add_argument(
        "--global", dest="global_", action="store_true", help="install into global git config"
    )

    macro_merge = subparsers.add_parser(
        "macro-merge",
        help="set-merge conflicted #define reference lists and report each side's adds/removes",
    )
    macro_merge.add_argument(
        "file", type=existing_file, help="a conflict-marked ini/inc file (use diff3 markers)"
    )
    macro_merge.add_argument(
        "--write", action="store_true", help="apply the merge (default: report only, no changes)"
    )
    macro_merge.add_argument(
        "-o", "--output", type=Path, default=None, help="write result here instead of in place"
    )
    macro_merge.add_argument(
        "-L", "--marker-size", type=int, default=7, help="conflict marker length (git %%L)"
    )
    macro_merge.add_argument("--json", action="store_true", help="emit the analysis as JSON")

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
        print(format_scoreboard(compute_scoreboard(args.root, overlays=tuple(args.overlay))))
        return 0

    if args.command == "lint":
        missing = [p for p in args.paths if not p.exists()]
        if missing:
            parser.error(f"no such file or directory: {missing[0]}")
        return _run_lint(args.paths, args.json)

    if args.command == "xref":
        return _run_xref(args.root, args.name, args.json)

    if args.command == "resolve":
        return _run_resolve(args.root, args.name, args.json)

    if args.command == "includes":
        return _run_includes(args.root, args.file)

    if args.command == "brief":
        return _run_brief(args.root, args.file, args.name, args.json)

    if args.command == "diff":
        return _run_diff(args)

    if args.command == "install-skill":
        return run_install_skill(install_skill, args.dest, args.force)

    if args.command == "macro-merge":
        return _run_macro_merge(args)

    if args.command == "merge":
        if not args.install and args.resolve is None:
            missing = [n for n in ("base", "ours", "theirs") if getattr(args, n) is None]
            if missing:
                parser.error("merge needs base, ours, and theirs (or --resolve / --install)")
        return _run_merge(args)

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
