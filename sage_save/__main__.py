"""Command-line entry point: `python -m sage_save <command>` (or `sage-save`).

- `info <save>` - the file header, the decoded `CHUNK_GameState` header (description, date,
  map, profile) and `CHUNK_GameStateMap` summary, then the full chunk table with versions
  and payload sizes. `--coverage` swaps the chunk table for a decoding-coverage report
  (decoded-vs-opaque bytes per chunk, and the whole-save total).
- `extract-map <save>` - write the embedded `.map` out (`--out`, default `<save>.map`); every
  `sage_map` tool then runs on it.
- `objects <save>` - the live objects from `CHUNK_GameLogic`, grouped by ini template name with
  counts (`--list` for one row per object with its runtime id). `--modules` instead reports the
  objects' behavior-module tags (a frequency table, or per-object with `--list`).
- `json <save>` - everything decoded (header, chunks, game state, map summary, objects, and the
  harvested reference names) as one JSON document (`--out` to a file, `--no-objects` to omit the
  per-object list, `--compact` for a single line).
- `edit <save> <edits.json> --out <new.sav>` - apply the editable fields of a JSON document (the
  `game_state` / `game_state_map` / `campaign` sections of a `json` export) back onto a save.
  Edits must preserve each chunk's byte length (timestamp, game mode, same-length rename).
- `check <save> --game <root>` - resolve the save's ini-names (object templates, the fatal
  upgrade/science names, and the campaign hero carry-over roster) against a loaded game and report
  the danglers: a missing object template drops the object on load, a missing upgrade/science or
  carried-over hero fails the load / carry-over outright.
- `diagnose <save> [--game <root>]` - explain why a save might fail to load: runs every check
  (container integrity, per-chunk decode, chunk-version drift, unknown chunks, and - with
  `--game` - the dangling fatal-reference check) and prints the findings ranked fatal → warning
  → info. Exit code is non-zero when a fatal problem is found. The go-to command for a save the
  game refuses to load.
- `scan <dir>` - the chunk-name/version inventory across a folder of saves: per file, plus an
  aggregate of every chunk name seen and the versions it appears at. Answers "which chunks does
  this game/save-kind write" without decoding any of them.
- `tree <save>` - the nested-`KOLB`-block tree of a chunk (`--chunk NAME` for one chunk's full
  tree, else per-chunk block counts). A reversing aid for the still-opaque chunks.
- `diff <a> <b>` - the first byte at which each shared chunk diverges between two saves, with an
  aligned hex window. The tool for pinning single-sample ambiguities as the corpus grows.

`info`, `objects`, `check` and `scan` accept `--json` for machine-readable output.
"""

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

from sage_save.chunks import (
    decode_campaign,
    decode_game_logic,
    decode_game_state,
    decode_game_state_map,
    decode_living_world_logic,
    decode_tactical_view,
    object_modules,
)
from sage_save.coverage import chunk_coverage, coverage_summary
from sage_save.diagnose import Diagnostic, diagnose_save, format_diagnosis
from sage_save.edit import apply_json_text
from sage_save.export import save_to_json
from sage_save.reversing import (
    first_difference,
    format_block_tree,
    format_divergence,
    nested_block_tree,
)
from sage_save.save import SaveFile, parse_save, parse_save_from_path, write_save_to_path
from sage_save.xref import check_save, format_findings
from sage_utils.cli import add_game_arguments, existing_dir, existing_file, utf8_stdout
from sage_utils.gameroot import resolve_game_roots


def _header_lines(save: SaveFile) -> list[str]:
    lines = [f"Container: {save.header.container_id} ({save.header.value1}, {save.header.value2})"]

    state = save.chunk("CHUNK_GameState")
    if state is not None:
        header = decode_game_state(state)
        when = header.saved_at.strftime("%Y-%m-%d %H:%M:%S") if header.saved_at else "?"
        lines.append(f"Save:      {header.description!r}  ({when})")
        lines.append(f"Profile:   {header.user_name}")
        if header.hero_name:
            lines.append(f"Hero:      {header.hero_name}  (created/brought-in)")
        lines.append(f"Map:       {header.map_name}")

    state_map = save.chunk("CHUNK_GameStateMap")
    if state_map is not None:
        gsm = decode_game_state_map(state_map)
        if gsm.has_map:
            lines.append(f"GameMode:  {gsm.game_mode}    embedded map: {len(gsm.map_data)} bytes")
        else:
            lines.append("GameMode:  mission stub (no embedded map; boots a fresh map next time)")

    campaign_chunk = save.chunk("CHUNK_Campaign")
    if campaign_chunk is not None:
        campaign = decode_campaign(campaign_chunk)
        if campaign.active:
            heroes = ", ".join(sorted({h.name for h in campaign.heroes}))
            lines.append(
                f"Campaign:  {campaign.current_campaign} mission {campaign.mission_number}, "
                f"{len(campaign.heroes)} carry-over hero(es){': ' + heroes if heroes else ''}"
            )

    logic = save.chunk("CHUNK_GameLogic")
    if logic is not None:
        # A header line must never take the whole command down: a GameLogic the BFME2 model
        # can't decode (a corrupt or unmodelled-engine payload) is reported inline, not raised -
        # this is the one place `info`/`diagnose` render a save we already suspect is broken.
        try:
            logic_state = decode_game_logic(logic)
            lines.append(
                f"Objects:   {len(logic_state.objects)} live "
                f"({len(logic_state.templates)} templates), frame {logic_state.frame}"
            )
        except ValueError as exc:
            lines.append(f"Objects:   <GameLogic did not decode: {exc}>")

    view = save.chunk("CHUNK_TacticalView")
    if view is not None:
        tv = decode_tactical_view(view)
        x, y, z = tv.position
        lines.append(f"Camera:    look-at ({x:.0f}, {y:.0f}, {z:.0f}), angle {tv.angle:.2f}")

    lwl = save.chunk("CHUNK_LivingWorldLogic")
    if lwl is not None:
        lwl_state = decode_living_world_logic(lwl)
        if lwl_state.names:  # only a WotR save populates the living-world layer
            armies = sum(1 for n in lwl_state.names if n.startswith("LWA:"))
            lines.append(f"Living world: {len(lwl_state.names)} roster names ({armies} LWA armies)")
    return lines


def _coverage_lines(save: SaveFile) -> list[str]:
    """The per-chunk decoding-coverage table plus the whole-save summary."""
    rows = chunk_coverage(save)
    summary = coverage_summary(save)
    lines = [
        f"Coverage:  {summary.chunks_decoded}/{summary.chunks_total} chunks, "
        f"{summary.bytes_decoded:,}/{summary.bytes_total:,} bytes "
        f"({summary.byte_fraction:.1%}) decoded",
        "",
        f"  {'name':40} {'ver':>3}  {'size':>12}  {'decoded':>12}  {'opaque':>12}  status",
    ]
    for row in rows:
        lines.append(
            f"  {row.name:40} {row.version:3}  {row.size:12,}  "
            f"{row.decoded_bytes:12,}  {row.opaque_bytes:12,}  {row.status}"
        )
    return lines


def _run_info(args: argparse.Namespace) -> int:
    save = parse_save_from_path(args.save)
    if args.coverage:
        if args.json:
            summary = coverage_summary(save)
            payload = {
                "chunks_total": summary.chunks_total,
                "chunks_decoded": summary.chunks_decoded,
                "bytes_total": summary.bytes_total,
                "bytes_decoded": summary.bytes_decoded,
                "byte_fraction": summary.byte_fraction,
                "chunks": [
                    {
                        "name": row.name,
                        "version": row.version,
                        "size": row.size,
                        "decoded_bytes": row.decoded_bytes,
                        "opaque_bytes": row.opaque_bytes,
                        "status": row.status,
                    }
                    for row in chunk_coverage(save)
                ],
            }
            print(json.dumps(payload, indent=2))
            return 0
        for line in _header_lines(save):
            print(line)
        print()
        for line in _coverage_lines(save):
            print(line)
        return 0
    if args.json:
        state = save.chunk("CHUNK_GameState")
        state_map = save.chunk("CHUNK_GameStateMap")
        header = decode_game_state(state) if state else None
        gsm = decode_game_state_map(state_map) if state_map else None
        payload = {
            "container": save.header.container_id,
            "header_values": [save.header.value1, save.header.value2],
            "game_state": (
                {
                    "description": header.description,
                    "saved_at": header.saved_at.isoformat() if header.saved_at else None,
                    "map_name": header.map_name,
                    "hero_name": header.hero_name,
                    "user_name": header.user_name,
                }
                if header
                else None
            ),
            "game_mode": gsm.game_mode if gsm else None,
            "embedded_map_bytes": len(gsm.map_data) if gsm else None,
            "chunks": [
                {"name": c.name, "version": c.version, "size": len(c.payload)} for c in save.chunks
            ],
        }
        print(json.dumps(payload, indent=2))
        return 0

    for line in _header_lines(save):
        print(line)
    print(f"\nChunks:    {len(save.chunks)}")
    print(f"  {'name':40} {'ver':>3}  {'bytes':>12}")
    for chunk in save.chunks:
        print(f"  {chunk.name:40} {chunk.version:3}  {len(chunk.payload):12,}")
    return 0


def _run_extract_map(args: argparse.Namespace) -> int:
    save = parse_save_from_path(args.save)
    state_map = save.chunk("CHUNK_GameStateMap")
    if state_map is None:
        print("save has no CHUNK_GameStateMap", file=sys.stderr)
        return 1
    gsm = decode_game_state_map(state_map)
    if not gsm.has_map:
        msg = "save carries no embedded map (a between-missions save boots a fresh map)"
        print(msg, file=sys.stderr)
        return 1
    map_data = gsm.map_data
    out = args.out or args.save.with_suffix(args.save.suffix + ".map")
    out.write_bytes(map_data)
    print(f"wrote {len(map_data):,} bytes to {out}")
    return 0


def _run_objects(args: argparse.Namespace) -> int:
    save = parse_save_from_path(args.save)
    logic = save.chunk("CHUNK_GameLogic")
    if logic is None:
        print("save has no CHUNK_GameLogic", file=sys.stderr)
        return 1
    objects = decode_game_logic(logic).objects

    def module_tags(obj):
        """The named top-level behavior-module tags of one object."""
        return [b.name for b in object_modules(obj) if b.name is not None and b.depth == 0]

    if args.modules:
        if args.json:
            payload = [
                {"object_id": o.object_id, "template": o.template_name, "modules": module_tags(o)}
                for o in objects
            ]
            print(json.dumps(payload, indent=2))
            return 0
        if args.list:
            for obj in objects:
                tags = module_tags(obj)
                print(f"  {obj.object_id:6}  {obj.template_name}  ({len(tags)} modules)")
                for tag in tags:
                    print(f"           {tag}")
            return 0
        counts = Counter(tag for obj in objects for tag in module_tags(obj))
        total = sum(counts.values())
        print(
            f"{len(objects)} objects, {total:,} module blocks, {len(counts)} distinct module tags:"
        )
        for name, count in counts.most_common():
            print(f"  {count:5} x {name}")
        return 0

    if args.json:
        payload = [
            {"template_id": o.template_id, "object_id": o.object_id, "template": o.template_name}
            for o in objects
        ]
        print(json.dumps(payload, indent=2))
        return 0

    if args.list:
        for obj in objects:
            print(f"  {obj.object_id:6}  {obj.template_name}")
        return 0

    counts = Counter(o.template_name for o in objects)
    print(f"{len(objects)} objects, {len(counts)} distinct templates:")
    for name, count in counts.most_common():
        print(f"  {count:5} x {name}")
    return 0


def _run_json(args: argparse.Namespace) -> int:
    save = parse_save_from_path(args.save)
    text = save_to_json(
        save, indent=None if args.compact else 2, include_objects=not args.no_objects
    )
    if args.out is not None:
        args.out.write_text(text, encoding="utf-8")
        print(f"wrote {args.out}")
    else:
        print(text)
    return 0


def _run_edit(args: argparse.Namespace) -> int:
    save = parse_save_from_path(args.save)
    try:
        edited = apply_json_text(save, args.edits.read_text(encoding="utf-8"))
    except ValueError as exc:
        print(f"cannot apply edits: {exc}", file=sys.stderr)
        return 1
    write_save_to_path(edited, args.out)
    print(f"wrote {args.out}")
    return 0


def _run_check(args: argparse.Namespace) -> int:
    from sage_ini.loader import load_game  # noqa: PLC0415

    save = parse_save_from_path(args.save)
    # An overlay mod is only complete over the base game it overlays; pass the base game as an
    # earlier --game layer or its references to base-game templates show as false danglers.
    game = load_game(resolve_game_roots(args.game, args.cache)).game
    findings = check_save(save, game)

    if args.json:
        payload = [
            {
                "kind": f.reference.kind,
                "name": f.reference.name,
                "count": f.reference.count,
                "fatal": f.reference.fatal,
                "status": f.status,
                "canonical": f.canonical,
            }
            for f in findings
        ]
        print(json.dumps(payload, indent=2))
        return 1 if any(f.status == "missing" for f in findings) else 0

    missing = [f for f in findings if f.status == "missing"]
    fatal = [f for f in missing if f.reference.fatal]
    if not findings:
        print("all references (object templates, upgrades, sciences) resolve against the game")
        return 0
    print(f"{len(findings)} unresolved reference(s):")
    for line in format_findings(findings):
        print(line)
    if fatal:
        print(f"\n{len(fatal)} fatal - this save would not load under the given game")
    return 1 if missing else 0


def _diagnostics_json(diagnostics: list[Diagnostic]) -> list[dict]:
    return [
        {"severity": d.severity, "category": d.category, "chunk": d.chunk, "message": d.message}
        for d in diagnostics
    ]


def _run_diagnose(args: argparse.Namespace) -> int:
    # The container parse is the first check: a save so damaged it won't even parse is itself the
    # top finding, so catch it here rather than let it crash the command.
    try:
        save = parse_save(args.save.read_bytes())
    except (ValueError, OSError) as exc:
        if args.json:
            payload = {
                "diagnostics": [
                    {
                        "severity": "fatal",
                        "category": "container",
                        "chunk": None,
                        "message": f"container did not parse: {exc}",
                    }
                ],
                "fatal": 1,
            }
            print(json.dumps(payload, indent=2))
        else:
            print("Diagnosis: 1 fatal, 0 warning, 0 info")
            print("This save's container is damaged - it does not parse at all.\n")
            print(f"  FATAL   container did not parse: {exc}")
        return 1

    game = None
    if args.game:
        from sage_ini.loader import load_game  # noqa: PLC0415

        game = load_game(resolve_game_roots(args.game, args.cache)).game

    diagnostics = diagnose_save(save, game)
    fatal = sum(1 for d in diagnostics if d.severity == "fatal")

    if args.json:
        print(json.dumps({"diagnostics": _diagnostics_json(diagnostics), "fatal": fatal}, indent=2))
        return 1 if fatal else 0

    for line in _header_lines(save):
        print(line)
    print()
    for line in format_diagnosis(diagnostics, checked_references=game is not None):
        print(line)
    return 1 if fatal else 0


def _run_tree(args: argparse.Namespace) -> int:
    save = parse_save_from_path(args.save)
    if args.chunk is not None:
        chunk = save.chunk(args.chunk)
        if chunk is None:
            print(f"save has no chunk {args.chunk!r}", file=sys.stderr)
            return 1
        targets = [chunk]
    else:
        targets = save.chunks

    printed = False
    for chunk in targets:
        blocks = nested_block_tree(chunk.payload, chunk.payload_offset)
        if not blocks:
            if args.chunk is not None:
                print(f"{chunk.name}: no nested KOLB blocks")
            continue
        printed = True
        top = sum(1 for b in blocks if b.depth == 0)
        print(f"{chunk.name}: {len(blocks):,} nested block(s), {top:,} at top level")
        if args.chunk is not None or args.detail:
            for line in format_block_tree(blocks, limit=args.max):
                print(f"  {line}")
    if not printed and args.chunk is None:
        print("no nested KOLB blocks in any chunk")
    return 0


def _run_diff(args: argparse.Namespace) -> int:
    save_a = parse_save_from_path(args.save_a)
    save_b = parse_save_from_path(args.save_b)
    names_a = {c.name for c in save_a.chunks}
    names_b = {c.name for c in save_b.chunks}

    if args.chunk is not None:
        names = [args.chunk]
    else:
        names = [c.name for c in save_a.chunks if c.name in names_b]
        for name in sorted(names_b - names_a):
            print(f"{name}: only in B")
        for name in (c.name for c in save_a.chunks if c.name not in names_b):
            print(f"{name}: only in A")

    differing = 0
    for name in names:
        chunk_a = save_a.chunk(name)
        chunk_b = save_b.chunk(name)
        if chunk_a is None or chunk_b is None:
            print(f"{name}: missing in {'A' if chunk_a is None else 'B'}")
            continue
        at = first_difference(chunk_a.payload, chunk_b.payload)
        if at is None:
            if args.chunk is not None or args.all:
                print(f"{name}: identical ({len(chunk_a.payload):,} bytes)")
            continue
        differing += 1
        print(f"{name}:")
        for line in format_divergence(chunk_a.payload, chunk_b.payload, at):
            print(f"  {line}")
    print(f"\n{differing} chunk(s) differ")
    return 0


def _iter_saves(directory: Path):
    """Yield parsed (path, SaveFile) for every BFME save in `directory`, skipping files that
    are not saves. Detection is by the header magic, so the extension does not matter."""
    for path in sorted(directory.iterdir()):
        if not path.is_file():
            continue
        try:
            save = parse_save_from_path(path)
        except (ValueError, OSError):
            continue
        yield path, save


def _run_scan(args: argparse.Namespace) -> int:
    seen: dict[str, set[int]] = {}
    files = []
    for path, save in _iter_saves(args.dir):
        for chunk in save.chunks:
            seen.setdefault(chunk.name, set()).add(chunk.version)
        files.append((path, save))

    if args.json:
        payload = {
            "files": [
                {
                    "file": path.name,
                    "chunks": [
                        {"name": c.name, "version": c.version, "size": len(c.payload)}
                        for c in save.chunks
                    ],
                }
                for path, save in files
            ],
            "inventory": {name: sorted(vers) for name, vers in sorted(seen.items())},
        }
        print(json.dumps(payload, indent=2))
        return 0

    if not files:
        print(f"no saves found in {args.dir}")
        return 0

    for path, save in files:
        names = ", ".join(c.name.removeprefix("CHUNK_") for c in save.chunks)
        print(f"{path.name}  ({len(save.chunks)} chunks)")
        print(f"    {names}")
    print(f"\nInventory across {len(files)} save(s):")
    for name, versions in sorted(seen.items()):
        vers = ", ".join(f"v{v}" for v in sorted(versions))
        print(f"  {name:40} {vers}")
    return 0


def main(argv: list[str] | None = None) -> int:
    utf8_stdout()
    parser = argparse.ArgumentParser(prog="sage-save", description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    info = subparsers.add_parser("info", help="header + chunk table")
    info.add_argument("save", type=existing_file)
    info.add_argument(
        "--coverage",
        action="store_true",
        help="show decoding coverage (decoded-vs-opaque bytes per chunk) not the chunk table",
    )
    info.add_argument("--json", action="store_true")
    info.set_defaults(func=_run_info)

    extract = subparsers.add_parser("extract-map", help="write the embedded .map file")
    extract.add_argument("save", type=existing_file)
    extract.add_argument("--out", type=Path, default=None, help="output path (default: <save>.map)")
    extract.set_defaults(func=_run_extract_map)

    objects = subparsers.add_parser("objects", help="live objects from CHUNK_GameLogic")
    objects.add_argument("save", type=existing_file)
    objects.add_argument("--list", action="store_true", help="one row per object with its id")
    objects.add_argument(
        "--modules",
        action="store_true",
        help="the objects' behavior-module tags (frequency table, or per-object with --list)",
    )
    objects.add_argument("--json", action="store_true")
    objects.set_defaults(func=_run_objects)

    to_json = subparsers.add_parser("json", help="everything decoded, as a JSON document")
    to_json.add_argument("save", type=existing_file)
    to_json.add_argument("--out", type=Path, default=None, help="write to a file instead of stdout")
    to_json.add_argument("--no-objects", action="store_true", help="omit the per-object list")
    to_json.add_argument("--compact", action="store_true", help="single-line JSON")
    to_json.set_defaults(func=_run_json)

    edit = subparsers.add_parser("edit", help="apply edited JSON attributes back onto a save")
    edit.add_argument("save", type=existing_file)
    edit.add_argument("edits", type=existing_file, help="a (edited) JSON document from `json`")
    edit.add_argument("--out", type=Path, required=True, help="write the edited save here")
    edit.set_defaults(func=_run_edit)

    check = subparsers.add_parser("check", help="resolve object templates against a game")
    check.add_argument("save", type=existing_file)
    add_game_arguments(
        check,
        game_help="a data/ini tree, or a live install folder whose .big archives are mounted",
    )
    check.add_argument("--json", action="store_true")
    check.set_defaults(func=_run_check)

    diagnose = subparsers.add_parser(
        "diagnose", help="explain why a save might fail to load (ranked suspects)"
    )
    diagnose.add_argument("save", type=existing_file)
    add_game_arguments(
        diagnose,
        game_required=False,
        game_help="a data/ini tree or install to resolve names against - enables the dangling-"
        "reference check (the most common load-failure cause)",
    )
    diagnose.add_argument("--json", action="store_true")
    diagnose.set_defaults(func=_run_diagnose)

    scan = subparsers.add_parser("scan", help="chunk-name/version inventory across a save folder")
    scan.add_argument("dir", type=existing_dir)
    scan.add_argument("--json", action="store_true")
    scan.set_defaults(func=_run_scan)

    tree = subparsers.add_parser("tree", help="nested-KOLB-block tree of a chunk (a reversing aid)")
    tree.add_argument("save", type=existing_file)
    tree.add_argument("--chunk", help="one chunk name to dump in full (default: per-chunk counts)")
    tree.add_argument("--detail", action="store_true", help="dump every chunk's tree, not counts")
    tree.add_argument("--max", type=int, default=200, help="max block lines to print per chunk")
    tree.set_defaults(func=_run_tree)

    diff = subparsers.add_parser("diff", help="first byte-divergence per chunk between two saves")
    diff.add_argument("save_a", type=existing_file)
    diff.add_argument("save_b", type=existing_file)
    diff.add_argument("--chunk", help="restrict to one chunk name")
    diff.add_argument("--all", action="store_true", help="also list chunks that are identical")
    diff.set_defaults(func=_run_diff)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
