"""Command-line entry point: `python -m sage_map <command>` (or `sage-map`).

Engine-generic map tooling - no game data required. The mod-specific map *checks* deliberately
live in their mod package (`sage_mods.edain.map_checks`), and game-aware linting is exposed
through the `sage-lint` CLI; this front end is the parse / inspect / serialize / diff layer that
`sage_map` provides on its own.

- `info <map>` - a summary of the parsed map: terrain dimensions, object count (with the most
  common object templates), and the waypoint / team / trigger / script tallies.
- `json <map>` - the whole parsed map as a JSON document (`--out` to a file, `--compact` for a
  single line). The lossless view is the binary round-trip (`parse` -> `write`); this JSON is the
  readable structural dump.
- `diff <a> <b>` - a human-readable content diff of two maps (moved objects, script edits, terrain
  summaries) where a binary diff can only say "files differ".
"""

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

from sage_map.diff import diff_map_files, format_map_diff
from sage_map.map import parse_map_from_path
from sage_utils.cli import existing_file, utf8_stdout


def _count(section) -> int:
    """The length of an asset's inner list, or 0 when the asset is absent."""
    if section is None:
        return 0
    for attr in ("object_list", "waypoint_paths", "teams", "scripts", "areas"):
        inner = getattr(section, attr, None)
        if isinstance(inner, list):
            return len(inner)
    return 0


def _run_info(args: argparse.Namespace) -> int:
    map_ = parse_map_from_path(args.map)

    hm = map_.height_map_data
    if hm is not None:
        print(f"Terrain:   {hm.width} x {hm.height} cells ({hm.area:,} area)")
    else:
        print("Terrain:   <no height map>")

    objects = map_.objects_list.object_list if map_.objects_list is not None else []
    print(f"Objects:   {len(objects)}")

    print(f"Waypoints: {_count(map_.waypoints_list)}")
    print(f"Teams:     {_count(map_.teams)}")
    print(f"Assets:    {len(map_.assets)}")

    if objects and not args.no_objects:
        counts = Counter(o.type_name for o in objects)
        print(f"\nTop object templates ({len(counts)} distinct):")
        for name, count in counts.most_common(args.top):
            print(f"  {count:5} x {name or '<unnamed>'}")
    return 0


def _run_json(args: argparse.Namespace) -> int:
    map_ = parse_map_from_path(args.map)
    text = json.dumps(map_.to_dict(), indent=None if args.compact else 2)
    if args.out is not None:
        args.out.write_text(text, encoding="utf-8")
        print(f"wrote {args.out}")
    else:
        print(text)
    return 0


def _run_diff(args: argparse.Namespace) -> int:
    diff = diff_map_files(args.map_a, args.map_b)
    print(format_map_diff(diff, str(args.map_a), str(args.map_b)))
    return 0


def main(argv: list[str] | None = None) -> int:
    utf8_stdout()
    parser = argparse.ArgumentParser(prog="sage-map", description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    info = subparsers.add_parser("info", help="terrain / object / script summary of a map")
    info.add_argument("map", type=existing_file)
    info.add_argument("--top", type=int, default=15, help="how many object templates to list")
    info.add_argument("--no-objects", action="store_true", help="skip the object-template table")
    info.set_defaults(func=_run_info)

    to_json = subparsers.add_parser("json", help="the parsed map as a JSON document")
    to_json.add_argument("map", type=existing_file)
    to_json.add_argument("--out", type=Path, default=None, help="write to a file instead of stdout")
    to_json.add_argument("--compact", action="store_true", help="single-line JSON")
    to_json.set_defaults(func=_run_json)

    diff = subparsers.add_parser("diff", help="human-readable content diff of two maps")
    diff.add_argument("map_a", type=existing_file)
    diff.add_argument("map_b", type=existing_file)
    diff.set_defaults(func=_run_diff)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
