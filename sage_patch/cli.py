"""``sage-patch`` — apply, verify and list binary patches for the ROTWK SAGE engine (`game.dat`).

    sage-patch list
    sage-patch apply  commandset-limit --count 64 --in game.dat.backup --out game.dat
    sage-patch verify commandset-limit --count 64 game.dat
    sage-patch sagepatch game.dat -o /path/to/mod/.sagepatch

Each registered patch (see :mod:`sage_patch.registry`) supplies its own parameters; ``apply``
and ``verify`` grow a sub-command per patch. ``apply`` never modifies its input — it writes the
patched copy to ``--out`` (or overwrites ``--in`` when ``--out`` is omitted). ``verify`` exits
non-zero and prints the mismatches when a file does not carry the requested patch.

``sagepatch`` goes the other way: instead of naming a patch, it reads a binary and reports what
is *in* it, as the `.sagepatch` file `sage_ini` and `sage_lint` load so the mod's INI is checked
against the engine it actually runs on (see :mod:`sage_patch.sagepatch`).
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from sage_ini.engine import dump_engine, load_engine
from sage_patch.patcher import apply_patches
from sage_patch.registry import PATCHES
from sage_patch.sagepatch import Generated, differences, generate, generate_from_patches


def _cmd_list(args: argparse.Namespace) -> int:
    width = max((len(name) for name in PATCHES), default=0)
    for name, cls in PATCHES.items():
        print(f"{name:<{width}}  {cls.description}")
    return 0


def _cmd_apply(args: argparse.Namespace) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    patch = PATCHES[args.patch].from_cli_args(args)
    out = apply_patches(args.src, [patch], output=args.out)
    print(f"wrote {out}")
    return 0


def _cmd_verify(args: argparse.Namespace) -> int:
    patch = PATCHES[args.patch].from_cli_args(args)
    data = Path(args.file).read_bytes()
    problems = patch.verify(data)
    if problems:
        print(f"FAIL: {args.file} does not carry {patch}:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    print(f"OK: {args.file} carries {patch}")
    return 0


def _report(generated: Generated, stream) -> None:
    """The human half of `sagepatch`: what was recognised and anything worth knowing."""
    if generated.patches:
        print("patches found:", file=stream)
        for patch in generated.patches:
            print(f"  - {patch}", file=stream)
    else:
        print("no known patch found in this binary", file=stream)
    for note in generated.notes:
        print(f"note: {note}", file=stream)


def _cmd_sagepatch(args: argparse.Namespace) -> int:
    if not args.patch_name and args.file is None:
        print(
            "sagepatch needs a game.dat to read, or --patch NAME to describe patches by name",
            file=sys.stderr,
        )
        return 2
    if args.patch_name:
        generated, unknown = generate_from_patches(args.patch_name)
        for name in unknown:
            print(
                f"unknown patch {name!r} (ignored); `sage-patch list` names them", file=sys.stderr
            )
    else:
        data = Path(args.file).read_bytes()
        generated = generate(data, Path(args.file))

    if args.check:
        # Drift check: does the committed file still describe this binary? `[source]` is excluded
        # (a path and a hash differ per machine and per rebuild), so only the deltas are compared.
        committed = load_engine(args.check)
        for warning in committed.warnings:
            print(f"{args.check}: {warning}", file=sys.stderr)
        problems = differences(committed, generated.engine)
        if problems:
            print(f"FAIL: {args.check} no longer describes this engine:", file=sys.stderr)
            for problem in problems:
                print(f"  - {problem}", file=sys.stderr)
            return 1
        print(f"OK: {args.check} matches this engine")
        return 0

    header = (
        "Written by `sage-patch sagepatch` - the INI surface this game.dat accepts.",
        "Commit it beside .sagelint; sage_lint and sage_ini read it (see sage_ini.engine).",
        "Regenerate it whenever the binary is repatched: `sage-patch sagepatch <game.dat>`.",
    )
    text = dump_engine(generated.engine, "\n".join(header))
    if args.out is None:
        print(text, end="")
        _report(generated, sys.stderr)
        return 0
    Path(args.out).write_text(text, encoding="utf-8")
    _report(generated, sys.stdout)
    print(f"wrote {args.out}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sage-patch",
        description="Binary patches for the ROTWK SAGE engine (game.dat).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="list the registered patches").set_defaults(func=_cmd_list)

    sagepatch = sub.add_parser(
        "sagepatch",
        help="write the .sagepatch describing the INI surface a patched game.dat accepts",
        description="Read a patched game.dat and write the .sagepatch that teaches sage_ini and "
        "sage_lint what INI it accepts: the fields, name-table tokens and raised limits its "
        "patches add. Commit the result beside .sagelint.",
    )
    sagepatch.add_argument(
        "file",
        nargs="?",
        metavar="GAME_DAT",
        help="the patched binary to read (omit only with --patch)",
    )
    sagepatch.add_argument(
        "-o",
        "--out",
        default=None,
        metavar="PATH",
        help="where to write it (default: stdout, so it can be piped or reviewed first)",
    )
    sagepatch.add_argument(
        "--patch",
        dest="patch_name",
        action="append",
        default=[],
        metavar="NAME",
        help="describe these patches with their DEFAULT parameters instead of reading a binary, "
        "for a project that knows what it builds with and would rather not wire a game.dat path "
        "into CI. A patch applied with any other parameter is described wrongly this way "
        "(repeatable)",
    )
    sagepatch.add_argument(
        "--check",
        default=None,
        metavar="SAGEPATCH",
        help="compare an existing .sagepatch against what this binary actually is, and exit "
        "non-zero on any difference - the drift check for a committed file",
    )
    sagepatch.set_defaults(func=_cmd_sagepatch)

    apply_p = sub.add_parser("apply", help="apply a patch to a copy of a game.dat")
    verify_p = sub.add_parser("verify", help="check a game.dat already carries a patch")
    apply_sub = apply_p.add_subparsers(dest="patch", required=True)
    verify_sub = verify_p.add_subparsers(dest="patch", required=True)

    for name, cls in PATCHES.items():
        ap = apply_sub.add_parser(name, help=cls.description)
        ap.add_argument(
            "--in",
            dest="src",
            required=True,
            metavar="GAME_DAT",
            help="clean input binary (read, never modified)",
        )
        ap.add_argument(
            "--out",
            dest="out",
            default=None,
            metavar="OUT",
            help="where to write the patched binary (default: overwrite --in)",
        )
        cls.add_cli_arguments(ap)
        ap.set_defaults(func=_cmd_apply)

        vp = verify_sub.add_parser(name, help=cls.description)
        vp.add_argument("file", metavar="GAME_DAT", help="patched binary to check")
        cls.add_cli_arguments(vp)
        vp.set_defaults(func=_cmd_verify)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
