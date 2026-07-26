"""``sage-patch`` — apply, verify and list binary patches for the ROTWK SAGE engine (`game.dat`).

    sage-patch list
    sage-patch apply  commandset-limit --count 64 --in game.dat.backup --out game.dat
    sage-patch verify commandset-limit --count 64 game.dat

Each registered patch (see :mod:`sage_patch.registry`) supplies its own parameters; ``apply``
and ``verify`` grow a sub-command per patch. ``apply`` never modifies its input — it writes the
patched copy to ``--out`` (or overwrites ``--in`` when ``--out`` is omitted). ``verify`` exits
non-zero and prints the mismatches when a file does not carry the requested patch.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from sage_patch.patcher import apply_patches
from sage_patch.registry import PATCHES


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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sage-patch",
        description="Binary patches for the ROTWK SAGE engine (game.dat).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="list the registered patches").set_defaults(func=_cmd_list)

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
