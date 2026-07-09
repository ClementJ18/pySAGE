"""Command-line entry point: `python -m sage_lint <command>`. `format` rewrites ini
files to the canonical style (or reports them with `--check`, or formats stdin);
`lint` assembles a game from a folder and reports its problems. Both can emit JSON
(`--output-format json`) for an editor plugin. `diff` assembles the mod at two git refs
(config-aware, with the base game merged in) and reports a human-readable changelog of the
game-data changes between them; `diff-maps` does the same for the binary `.map`/`.bse` files
one commit touches.

This module owns the argument parser and dispatch; the command implementations live in
`sage_lint.commands` (one module per command, shared option/report plumbing in `common`).
"""

import argparse
from pathlib import Path

from sage_ini.parser.diagnostics import Severity
from sage_ini.parser.io import INI_SUFFIXES
from sage_lint.baseline import BASELINE_NAME
from sage_lint.commands.common import SORTERS, effective_root, load_lint_config
from sage_lint.commands.diff import run_diff, run_diff_maps
from sage_lint.commands.format import run_format
from sage_lint.commands.init import run_init
from sage_lint.commands.lint import run_lint, run_lint_maps, run_list_codes
from sage_lint.commands.serve import run_serve


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
        choices=tuple(SORTERS),
        default="file",
        help="order the report: file (path then line, default), severity (errors first), "
        "code (group same-kind problems), or line (by line number across files)",
    )
    lint.add_argument(
        "--fix",
        action="store_true",
        help="rewrite source files to resolve the auto-fixable diagnostics (enum-case, "
        "reference-case, macro-case, repeated-field, repeated-flag-field, "
        "spurious-block-label) before reporting the rest",
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
        description="Assemble the mod at two git refs the way `lint` builds a game - reading "
        "root/base from .sagelint so includes into the base game resolve - and report the "
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
    diff.add_argument(
        "--player",
        action="store_true",
        help="append a player-facing section: display names, macros resolved to their "
        "values, and each change attributed to the units that use it, grouped by faction",
    )

    diff_maps_cmd = subparsers.add_parser(
        "diff-maps",
        help="changelog of the binary .map/.bse files a git commit or range touches",
        description="For every WorldBuilder map file the commit (or range) adds, removes, "
        "modifies or renames, parse both sides out of git and report what actually changed - "
        "placed objects, teams, players, scripts, trigger areas, map settings, and a terrain "
        "summary - where git can only say 'binary files differ'. Purely structural: no game "
        "assembly, bases or .sagelint config involved.",
    )
    diff_maps_cmd.add_argument(
        "commit",
        nargs="?",
        default="HEAD",
        help="a commit (default: HEAD), diffed against its parent - or a git range old..new "
        "(net change between the endpoints; old...new diffs from the merge base, like git diff)",
    )
    diff_maps_cmd.add_argument(
        "dir",
        type=Path,
        nargs="?",
        default=None,
        help="the git repo working dir (default: current dir)",
    )
    diff_maps_cmd.add_argument(
        "--output-format",
        choices=("text", "json", "md"),
        default="text",
        help="report format: human text (default), machine-readable json, or markdown "
        "(bulleted, code-quoted - pastes cleanly into a PR or wiki page)",
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
        return run_format(args)

    if args.command == "lint":
        if args.list_codes:
            return run_list_codes()
        if args.write_baseline and args.fix:
            parser.error("--write-baseline cannot be combined with --fix")
        if args.write_baseline and args.no_config and args.baseline is None:
            parser.error("--write-baseline needs a path: pass --baseline or drop --no-config")
        config = load_lint_config(args)
        root = effective_root(args, config)
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
        return run_lint(args, config, root)

    if args.command == "lint-maps":
        config = load_lint_config(args)
        root = effective_root(args, config)
        if root is None:
            parser.error("the following arguments are required: root (or set 'root' in .sagelint)")
        if not root.is_dir():
            parser.error(f"not a directory: {root}")
        return run_lint_maps(args, config, root)

    if args.command == "diff":
        return run_diff(args, parser)

    if args.command == "diff-maps":
        return run_diff_maps(args)

    if args.command == "serve":
        return run_serve(args)

    if args.command == "init":
        return run_init(args)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
