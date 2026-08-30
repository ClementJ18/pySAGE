"""Command-line entry point: `python -m sage_apt <command>` (or `sage-apt`).

- `to-xml <file.apt>` - decompile a `.apt`/`.const` pair to an editable `.xml`.
- `to-apt <file.xml>` - compile the XML back into the `.apt`/`.const` pair.
- `check <paths...>` - batch round-trip validator; reports `ok`/`unstable`/`error`
  per pair and exits non-zero on any failure (`--json` for machine-readable output).
- `view <file.xml>` - write a self-contained HTML/SVG visualisation next to the file.
- `edit <file.xml>` - serve the browser editor for the file (`--port`, `--no-browser`).
- `import-character <dest.xml> <source.xml> <id>` - copy a character and everything it
  draws from one movie into another, renumbering characters, meshes and textures.
"""

import argparse
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from sage_apt.aptfile import AptError, apt_to_xml, xml_to_apt
from sage_apt.check import OK, check_paths
from sage_apt.editor import serve
from sage_apt.merge import merge_character, rewrite_geometry
from sage_apt.viewer import write_viewer_html
from sage_utils.cli import existing_dir, existing_file, utf8_stdout


def _build_texture_resolver(path, game_dir):
    """Build an `AptTextureResolver` for real-artwork rendering, or None. Returns None
    (placeholders) when no `--game` was given or the `[apt]`/`[ui]` extras (Pillow +
    pyBIG) are not installed; the resolver code is imported lazily so the core needs no
    extra."""
    if not game_dir:
        return None
    try:
        from sage_apt.textures import build_resolver  # noqa: PLC0415 - lazy: needs [apt]/[ui]
    except ImportError:
        print("note: install the [apt] or [ui] extra for real textures", file=sys.stderr)
        return None
    return build_resolver(path, game_dir)


def _run_to_xml(args: argparse.Namespace) -> int:
    try:
        xml_path = apt_to_xml(args.apt, game_dir=args.game)
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
                line += f"  - {r.message}"
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
    textures = _build_texture_resolver(args.xml, args.game)
    out = write_viewer_html(
        args.xml, args.out, frame=args.frame, label=args.label, textures=textures
    )
    print(f"wrote {out}")
    return 0


def _run_edit(args: argparse.Namespace) -> int:
    resolver = _build_texture_resolver(args.xml, args.game)
    serve(
        args.xml,
        port=args.port,
        open_browser=not args.no_browser,
        resolver=resolver,
        frame=args.frame,
        label=args.label,
    )
    return 0


def _load_meshes(directory: Path | None, movie: str) -> dict[int, str]:
    """`geometry id -> .ru text` from a `<Movie>_geometry` folder, or `{}` when there is none.

    Without it a merge cannot see which `image` characters a shape's mesh samples, so the copy
    would leave its textures behind - which is why `import-character` warns when the source movie
    has shapes and no meshes were found.
    """
    if directory is None:
        return {}
    folder = directory / f"{movie}_geometry"
    if not folder.is_dir():
        folder = directory
    found: dict[int, str] = {}
    for path in folder.glob("*.ru"):
        if re.fullmatch(r"\d+", path.stem):
            found[int(path.stem)] = path.read_text(encoding="latin-1")
    return found


def _run_import_character(args: argparse.Namespace) -> int:
    destination_tree = ET.parse(args.destination)
    destination = destination_tree.getroot()
    source = ET.parse(args.source).getroot()
    meshes = _load_meshes(args.geometry, args.source.stem)
    if not meshes and any(source.iter("shape")):
        print(
            "note: the source has shapes but no geometry was found - pass --geometry so the "
            "textures its meshes sample come across too",
            file=sys.stderr,
        )
    try:
        plan = merge_character(destination, source, args.character, meshes)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 1

    out = args.out or args.destination
    destination_tree.write(out, encoding="utf-8", xml_declaration=True)
    print(f"wrote {out}; the character is now {plan.character}")
    if plan.imports:
        for movie, name, slot in plan.imports:
            print(f"  import  {name} from {movie} -> character {slot}")
    if args.geometry_out and plan.geometry:
        args.geometry_out.mkdir(parents=True, exist_ok=True)
        for old, new in sorted(plan.geometry.items()):
            (args.geometry_out / f"{new}.ru").write_text(
                rewrite_geometry(meshes[old], plan), encoding="latin-1"
            )
        print(f"  wrote {len(plan.geometry)} renumbered meshes to {args.geometry_out}")
    elif plan.geometry:
        moved = ", ".join(f"{o}->{n}" for o, n in sorted(plan.geometry.items()))
        print(f"  geometry to copy: {moved}")
    if plan.textures:
        moved = ", ".join(f"{o}->{n}" for o, n in sorted(plan.textures.items()))
        print(f"  textures to copy: {moved}")
    return 0


def main(argv: list[str] | None = None) -> int:
    utf8_stdout()
    parser = argparse.ArgumentParser(prog="sage-apt", description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    to_xml = subparsers.add_parser("to-xml", help="decompile .apt/.const to .xml")
    to_xml.add_argument("apt", type=Path, help=".apt (or .const) file")
    to_xml.add_argument(
        "--game",
        type=existing_dir,
        default=None,
        metavar="ROOT",
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
        "--game",
        type=existing_dir,
        default=None,
        metavar="ROOT",
        help="texture directory for real artwork instead of placeholders (needs [apt]/[ui])",
    )
    view.set_defaults(func=_run_view)

    edit = subparsers.add_parser("edit", help="open the browser editor for the XML")
    edit.add_argument("xml", type=existing_file)
    edit.add_argument("--port", type=int, default=8080)
    edit.add_argument("--no-browser", action="store_true", help="don't open a browser tab")
    edit.add_argument(
        "--frame", type=int, default=None, help="root frame index to open on (default: 0)"
    )
    edit.add_argument(
        "--label",
        default=None,
        help="frame-label state to open in (root frame + each sprite's display state)",
    )
    edit.add_argument(
        "--game",
        type=existing_dir,
        default=None,
        metavar="ROOT",
        help="texture directory for real artwork instead of placeholders (needs [apt]/[ui])",
    )
    edit.set_defaults(func=_run_edit)

    imp = subparsers.add_parser(
        "import-character",
        help="copy a character and everything it draws from one movie's XML into another's",
    )
    imp.add_argument("destination", type=existing_file, help="the XML to copy into")
    imp.add_argument("source", type=existing_file, help="the XML to copy from")
    imp.add_argument("character", type=int, help="the source character id to copy")
    imp.add_argument(
        "--geometry",
        type=existing_dir,
        default=None,
        metavar="DIR",
        help="the source's <Movie>_geometry folder (or its parent), so mesh textures come too",
    )
    imp.add_argument(
        "--geometry-out",
        type=Path,
        default=None,
        metavar="DIR",
        help="write the renumbered meshes here (otherwise the renaming is only printed)",
    )
    imp.add_argument(
        "--out", type=Path, default=None, help="output XML (default: overwrite the destination)"
    )
    imp.set_defaults(func=_run_import_character)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
