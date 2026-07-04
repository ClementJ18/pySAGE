"""Command-line entry point: `python -m sage_apt <command>` (or `sage-apt`).

- `to-xml <file.apt>` — decompile a `.apt`/`.const` pair to an editable `.xml`.
- `to-apt <file.xml>` — compile the XML back into the `.apt`/`.const` pair.
- `check <paths...>` — batch round-trip validator; reports `ok`/`unstable`/`error`
  per pair and exits non-zero on any failure (`--json` for machine-readable output).
- `view <file.xml>` — write a self-contained HTML/SVG visualisation next to the file.
- `edit <file.xml>` — serve the browser editor for the file (`--port`, `--no-browser`).
"""

import argparse
import json
import sys
from pathlib import Path

from sage_apt.aptfile import AptError, apt_to_xml, xml_to_apt
from sage_apt.check import OK, check_paths
from sage_apt.editor import serve
from sage_apt.viewer import write_viewer_html
from sage_utils.cli import existing_dir, existing_file, utf8_stdout


def _build_texture_resolver(path, game_dir):
    """Build an `AptTextureResolver` for real-artwork rendering, or None. Returns None
    (placeholders) when no `--game-dir` was given or the `[apt]`/`[ui]` extras (Pillow +
    pyBIG) are not installed; the resolver code is imported lazily so the core needs no
    extra."""
    if not game_dir:
        return None
    try:
        from sage_apt.textures import build_resolver  # noqa: PLC0415 — lazy: needs [apt]/[ui]
    except ImportError:
        print("note: install the [apt] or [ui] extra for real textures", file=sys.stderr)
        return None
    return build_resolver(path, game_dir)


def _run_to_xml(args: argparse.Namespace) -> int:
    try:
        xml_path = apt_to_xml(args.apt, game_dir=args.game_dir)
    except AptError as exc:
        print(exc, file=sys.stderr)
        return 1
    print(f"wrote {xml_path}")
    return 0


def _run_to_apt(args: argparse.Namespace) -> int:
    try:
        apt_path, const_path = xml_to_apt(args.xml)
    except AptError as exc:
        print(exc, file=sys.stderr)
        return 1
    print(f"wrote {apt_path} and {const_path}")
    return 0


def _run_check(args: argparse.Namespace) -> int:
    results = check_paths(args.paths)

    if args.json:
        print(json.dumps([r.as_dict() for r in results], indent=2))
    else:
        for r in results:
            line = f"{r.status:8s} {r.path}"
            if r.message:
                line += f"  — {r.message}"
            print(line)
        if not results:
            print("no .apt pairs found")
        else:
            ok = sum(r.status == OK for r in results)
            unstable = sum(r.status == "unstable" for r in results)
            errors = sum(r.status == "error" for r in results)
            print(f"\n{ok}/{len(results)} ok, {unstable} unstable, {errors} error")

    if not results:
        return 1
    return 0 if all(r.status == OK for r in results) else 1


def _run_view(args: argparse.Namespace) -> int:
    textures = _build_texture_resolver(args.xml, args.game_dir)
    out = write_viewer_html(
        args.xml, args.out, frame=args.frame, label=args.label, textures=textures
    )
    print(f"wrote {out}")
    return 0


def _run_edit(args: argparse.Namespace) -> int:
    resolver = _build_texture_resolver(args.xml, args.game_dir)
    serve(args.xml, port=args.port, open_browser=not args.no_browser, resolver=resolver)
    return 0


def main(argv: list[str] | None = None) -> int:
    utf8_stdout()
    parser = argparse.ArgumentParser(prog="sage-apt", description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    to_xml = subparsers.add_parser("to-xml", help="decompile .apt/.const to .xml")
    to_xml.add_argument("apt", type=Path, help=".apt (or .const) file")
    to_xml.add_argument(
        "--game-dir",
        type=existing_dir,
        default=None,
        help="game directory to search for a .const (or the .apt) packed in a .big",
    )
    to_xml.set_defaults(func=_run_to_xml)

    to_apt = subparsers.add_parser("to-apt", help="compile .xml back to .apt/.const")
    to_apt.add_argument("xml", type=existing_file)
    to_apt.set_defaults(func=_run_to_apt)

    check = subparsers.add_parser(
        "check", help="round-trip .apt pairs and report ok/unstable/error"
    )
    check.add_argument(
        "paths",
        nargs="+",
        type=Path,
        help=".apt files or directories to scan for *.apt with a sibling .const",
    )
    check.add_argument("--json", action="store_true", help="machine-readable output")
    check.set_defaults(func=_run_check)

    view = subparsers.add_parser("view", help="write an HTML/SVG visualisation of the XML")
    view.add_argument("xml", type=existing_file)
    view.add_argument("--out", default=None, help="output path (default: alongside the XML)")
    view.add_argument(
        "--frame", type=int, default=None, help="root frame index to render (default: 0)"
    )
    view.add_argument(
        "--label",
        default=None,
        help="render this frame label (root frame + biases each sprite's display state)",
    )
    view.add_argument(
        "--game-dir",
        type=existing_dir,
        default=None,
        help="texture directory for real artwork instead of placeholders (needs [apt]/[ui])",
    )
    view.set_defaults(func=_run_view)

    edit = subparsers.add_parser("edit", help="open the browser editor for the XML")
    edit.add_argument("xml", type=existing_file)
    edit.add_argument("--port", type=int, default=8080)
    edit.add_argument("--no-browser", action="store_true", help="don't open a browser tab")
    edit.add_argument(
        "--game-dir",
        type=existing_dir,
        default=None,
        help="texture directory for real artwork instead of placeholders (needs [apt]/[ui])",
    )
    edit.set_defaults(func=_run_edit)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
