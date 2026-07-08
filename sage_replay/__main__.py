"""Command-line entry point: `python -m sage_replay <command>` (or `sage-replay`).

- `info <replay>` — header summary: game, version, map, players, duration, and the
  most frequent order types.
- `orders <replay>` — dump the order stream (`--limit`, `--player`, `--order` to filter).
- `ids <replay>` — the object-referencing integer ids in the order stream: a per-order
  summary, or (with `--order`) the timecode-ordered id runs for one order type. The raw
  material for mapping ids to mod objects (see object_id_mapping_plan.md).
- `align <replay> <labels>` — join a hand-written label log to the id runs of one order
  type and print the inferred `id -> object` rows; `--out` accumulates them into a JSON
  mapping.
- `narrate <replay> --game <root>` — retell the match in English, resolving recruit / build
  / special-power / spellbook / upgrade ids against a loaded game. `--game` takes an
  extracted `data/ini` tree or a live install folder (its `.big` archives are mounted
  automatically into a cache).
- `winner <replay>` — infer the outcome from session-end signals (leave-game orders,
  checksum heartbeats, the end-of-recording marker); a concession heuristic, so the
  verdict may be `undetermined` (see `winner.py`).

All accept `--json` for machine-readable output.
"""

import argparse
import json
import sys
import tempfile
from collections import Counter
from pathlib import Path

from sage_replay.ids import (
    ChunkPredicate,
    IdRun,
    align,
    arg_equals,
    collapse_runs,
    id_events,
    order_id_summaries,
    parse_labels,
)
from sage_replay.narrate import GameData, narrate, render
from sage_replay.replay import (
    GeneralsOrderType,
    OrderArgument,
    ReplayChunk,
    ReplayFile,
    ReplayGameType,
    ReplaySlot,
    ReplaySlotType,
    parse_replay_from_path,
)
from sage_replay.winner import PlayerSession, infer_winner
from sage_utils.cli import existing_file, utf8_stdout


def _parse_order_type(value: str) -> int:
    """Argparse `type=` accepting an order id as hex (`0x415`) or decimal (`1045`)."""
    return int(value, 0)


def _parse_where_value(text: str) -> object:
    """Interpret a `--where` right-hand side: `true`/`false` → bool, then int (`0x`/dec),
    else the raw string."""
    lowered = text.lower()
    if lowered in ("true", "false"):
        return lowered == "true"
    try:
        return int(text, 0)
    except ValueError:
        return text


def _build_where(specs: list[str] | None) -> ChunkPredicate | None:
    """Combine `--where INDEX=VALUE` specs into one AND-ed predicate over an order's
    argument list (e.g. `--where 0=false` picks `0x417`'s unit/upgrade mode)."""
    if not specs:
        return None
    predicates = []
    for spec in specs:
        index_text, sep, value_text = spec.partition("=")
        if not sep:
            raise argparse.ArgumentTypeError(f"--where expects INDEX=VALUE, got {spec!r}")
        try:
            index = int(index_text)
        except ValueError:
            raise argparse.ArgumentTypeError(
                f"--where index must be an integer: {spec!r}"
            ) from None
        predicates.append(arg_equals(index, _parse_where_value(value_text)))

    def combined(chunk: ReplayChunk) -> bool:
        return all(predicate(chunk) for predicate in predicates)

    return combined


def _order_name(replay: ReplayFile, order_type: int) -> str:
    """Generals order ids have OpenSAGE names; BFME ids are unmapped, so raw hex."""
    if replay.game_type is ReplayGameType.Generals:
        try:
            return GeneralsOrderType(order_type).name
        except ValueError:
            pass
    return f"0x{order_type:X}"


def _slot_name(slot: ReplaySlot | None) -> str | None:
    if slot is None:
        return None
    if slot.slot_type is ReplaySlotType.Human:
        return slot.human_name or "?"
    difficulty = slot.computer_difficulty.name if slot.computer_difficulty else "?"
    return f"Computer ({difficulty})"


def _slot_label(slot: ReplaySlot) -> str:
    return f"{_slot_name(slot)}  faction={slot.faction} color={slot.color} team={slot.team}"


def _issuer_label(replay: ReplayFile, chunk: ReplayChunk) -> str:
    """The issuing player's name when the chunk maps to a slot, else the raw number."""
    return _slot_name(replay.slot_for(chunk)) or f"#{chunk.number}"


def _argument_value(argument: OrderArgument) -> object:
    value = argument.value
    return value.hex() if isinstance(value, bytes) else value


def _slot_dict(slot: ReplaySlot) -> dict:
    return {
        "type": slot.slot_type.name,
        "name": slot.human_name,
        "difficulty": slot.computer_difficulty.name if slot.computer_difficulty else None,
        "color": slot.color,
        "faction": slot.faction,
        "start_position": slot.start_position,
        "team": slot.team,
        "raw": slot.raw,
    }


def _header_dict(replay: ReplayFile) -> dict:
    header = replay.header
    return {
        "game": header.game_type.name,
        "start_time": header.start_time.isoformat(),
        "end_time": header.end_time.isoformat(),
        "num_timecodes": header.num_timecodes,
        "filename": header.filename,
        "timestamp": str(header.timestamp),
        "version": header.version,
        "build_date": header.build_date,
        "map_file": header.metadata.map_file,
        "map_crc": header.metadata.map_crc,
        "map_size": header.metadata.map_size,
        "seed": header.metadata.seed,
        "starting_credits": header.metadata.starting_credits,
        "metadata": header.metadata.values,
        "players": [_slot_dict(s) for s in header.metadata.players],
    }


def _chunk_dict(replay: ReplayFile, chunk: ReplayChunk) -> dict:
    return {
        "timecode": chunk.timecode,
        "slot_index": replay.slot_index(chunk),
        "player": _slot_name(replay.slot_for(chunk)),
        "order_type": chunk.order_type,
        "order_name": _order_name(replay, chunk.order_type),
        "arguments": [
            {"type": a.argument_type.name, "value": _argument_value(a)}
            for a in chunk.order.arguments
        ],
    }


def _run_info(args: argparse.Namespace) -> int:
    replay = parse_replay_from_path(args.replay)
    if args.json:
        payload = _header_dict(replay)
        payload["chunks"] = len(replay.chunks)
        print(json.dumps(payload, indent=2))
        return 0

    header = replay.header
    print(f"{header.game_type.name} replay — {header.version}")
    print(f"Map:      {header.metadata.map_file}")
    print(
        f"Played:   {header.start_time:%Y-%m-%d %H:%M} UTC, "
        f"duration {header.end_time - header.start_time} ({header.num_timecodes} timecodes)"
    )
    print("Players:")
    for slot in header.metadata.players:
        print(f"  {_slot_label(slot)}")

    print(f"Orders:   {len(replay.chunks)} chunks")
    by_player = Counter(_issuer_label(replay, chunk) for chunk in replay.chunks)
    for player, count in by_player.most_common():
        print(f"  {count:6d} × {player}")
    counts = Counter(chunk.order_type for chunk in replay.chunks)
    for order_type, count in counts.most_common(10):
        print(f"  {count:6d} × {_order_name(replay, order_type)}")
    return 0


def _run_orders(args: argparse.Namespace) -> int:
    replay = parse_replay_from_path(args.replay)
    chunks = replay.chunks
    if args.order is not None:
        chunks = [c for c in chunks if c.order_type == args.order]
    if args.player is not None:
        chunks = [c for c in chunks if replay.slot_index(c) == args.player]
    if args.limit is not None:
        chunks = chunks[: args.limit]

    if args.json:
        print(json.dumps([_chunk_dict(replay, c) for c in chunks], indent=2))
        return 0

    for chunk in chunks:
        arguments = ", ".join(
            f"{a.argument_type.name}={_argument_value(a)}" for a in chunk.order.arguments
        )
        print(
            f"[{chunk.timecode:6d}] {_issuer_label(replay, chunk)} "
            f"{_order_name(replay, chunk.order_type)} {arguments}"
        )
    return 0


def _run_ids(args: argparse.Namespace) -> int:
    replay = parse_replay_from_path(args.replay)
    where = _build_where(args.where)

    if args.order is None:
        summaries = order_id_summaries(
            replay, slot_index=args.player, arg_index=args.arg, where=where
        )
        if args.json:
            print(
                json.dumps(
                    [
                        {
                            "order_type": s.order_type,
                            "order_name": _order_name(replay, s.order_type),
                            "total": s.total,
                            "distinct_ids": s.distinct_ids,
                            "top": s.top,
                        }
                        for s in summaries
                    ],
                    indent=2,
                )
            )
            return 0
        print(f"{'order':7s} {'total':>6s} {'distinct':>8s}  top ids (id×count)")
        for summary in summaries:
            top = ", ".join(f"{i}×{c}" for i, c in summary.top)
            name = _order_name(replay, summary.order_type)
            print(f"{name:7s} {summary.total:6d} {summary.distinct_ids:8d}  {top}")
        return 0

    events = id_events(replay, args.order, slot_index=args.player, arg_index=args.arg, where=where)
    runs = collapse_runs(events)
    if args.json:
        print(json.dumps([_run_dict(r) for r in runs], indent=2))
        return 0

    print(f"{_order_name(replay, args.order)}: {len(events)} orders in {len(runs)} runs")
    for run in runs:
        suffix = f" ×{run.count}" if run.count > 1 else ""
        print(f"  [{run.start_timecode:6d}] {run.id}{suffix}")
    return 0


def _run_dict(run: IdRun) -> dict:
    return {"start_timecode": run.start_timecode, "id": run.id, "count": run.count}


def _run_align(args: argparse.Namespace) -> int:
    replay = parse_replay_from_path(args.replay)
    labels = parse_labels(Path(args.labels).read_text(encoding="utf-8"))
    where = _build_where(args.where)
    events = id_events(replay, args.order, slot_index=args.player, arg_index=args.arg, where=where)
    runs = collapse_runs(events)
    rows, warnings = align(runs, labels.actions)

    if args.json:
        print(
            json.dumps(
                {
                    "order_type": args.order,
                    "metadata": labels.metadata,
                    "rows": [
                        {
                            "id": r.id,
                            "name": r.name,
                            "replay_count": r.replay_count,
                            "label_count": r.label_count,
                            "ok": r.ok,
                        }
                        for r in rows
                    ],
                    "warnings": warnings,
                },
                indent=2,
            )
        )
    else:
        print(f"{_order_name(replay, args.order)}  ({len(rows)} rows)")
        for row in rows:
            mark = " " if row.ok else "!"
            id_text = str(row.id) if row.id is not None else "—"
            print(f" {mark} {id_text:>8s}  {row.name}  ({row.replay_count}/{row.label_count})")
        for warning in warnings:
            print(f"warning: {warning}", file=sys.stderr)

    if args.out is not None:
        conflicts = _merge_mapping(Path(args.out), labels.metadata, args.order, rows)
        for conflict in conflicts:
            print(f"conflict: {conflict}", file=sys.stderr)

    return 1 if warnings else 0


def _merge_mapping(path: Path, metadata: dict, order_type: int, rows: list) -> list[str]:
    """Merge confidently-aligned rows into a growing `id -> object` JSON mapping keyed
    by order type, and return conflicts (an id already mapped to a different name)."""
    mapping = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    mapping.setdefault("metadata", {}).update(metadata)
    orders = mapping.setdefault("orders", {})
    key = f"0x{order_type:X}"
    table = orders.setdefault(key, {})

    conflicts = []
    for row in rows:
        # Only record rows whose run length matched the label — a mismatch means the
        # alignment slipped and the id is not trustworthy.
        if row.id is None or not row.ok:
            continue
        existing = table.get(str(row.id))
        if existing is not None and existing != row.name:
            conflicts.append(f"id {row.id}: '{existing}' vs '{row.name}'")
            continue
        table[str(row.id)] = row.name

    path.write_text(json.dumps(mapping, indent=2, sort_keys=True), encoding="utf-8")
    return conflicts


def _resolve_game_root(game: Path, cache: Path | None) -> Path:
    """Return a `data/ini` tree to load. `game` may already be one (or an extracted corpus),
    or a live install holding `.big` archives — those are mounted into `cache` (default: a
    per-install folder under the system temp dir), cached across runs."""
    if (game / "data" / "ini").is_dir() or (game / "default" / "subsystemlegend.ini").is_file():
        return game
    if not list(game.glob("*.big")):
        raise SystemExit(f"{game} is neither a data/ini tree nor an install with .big archives")

    # tools/ is a dev-only, unpackaged helper; import it only when a live install must be
    # mounted, so the other subcommands never depend on it being importable.
    from tools.mount_game import mount_ini_tree  # noqa: PLC0415

    if cache is None:
        cache = Path(tempfile.gettempdir()) / "sage_mount" / game.resolve().name
    return mount_ini_tree(game, cache)


def _run_narrate(args: argparse.Namespace) -> int:
    replay = parse_replay_from_path(args.replay)
    data = GameData.from_root(_resolve_game_root(args.game, args.cache))

    if args.json:
        events = [
            {
                "timecode": e.timecode,
                "clock": e.clock,
                "player": e.player,
                "text": e.text,
                "count": e.count,
            }
            for e in narrate(replay, data)
        ]
        print(json.dumps({"header": _header_dict(replay), "events": events}, indent=2))
        return 0

    for line in render(replay, data):
        print(line)
    return 0


def _clock(seconds: float) -> str:
    return f"{int(seconds) // 60:d}:{int(seconds) % 60:02d}"


def _session_status(session: PlayerSession, end: int, spf: float) -> str:
    """One human session's ending, in words, for the `winner` text output."""
    departed = session.departed_at(end)
    if session.left_at is not None:
        when = f" ({_clock(session.left_at * spf)})" if spf else ""
        return f"left the game at frame {session.left_at}{when}"
    if departed is not None:
        when = f" ({_clock(departed * spf)})" if spf else ""
        return f"went silent at frame {departed}{when} — likely dropped"
    parts = []
    if session.last_order is not None:
        parts.append(f"last order -{end - session.last_order}")
    if session.last_heartbeat is not None:
        parts.append(f"last heartbeat -{end - session.last_heartbeat}")
    return f"present at end ({', '.join(parts)} frames)" if parts else "present at end"


def _run_winner(args: argparse.Namespace) -> int:
    replay = parse_replay_from_path(args.replay)
    verdict = infer_winner(replay)
    end = replay.chunks[-1].timecode if replay.chunks else 0
    spf = replay.seconds_per_frame

    if args.json:
        payload = {
            "outcome": verdict.outcome,
            "winner": verdict.winner,
            "winner_names": verdict.winner_names,
            "confidence": verdict.confidence,
            "reason": verdict.reason,
            "recorder": verdict.recorder,
            "sessions": [
                {
                    "slot_index": s.slot_index,
                    "name": s.name,
                    "team": s.slot.team,
                    "last_order": s.last_order,
                    "last_heartbeat": s.last_heartbeat,
                    "left_at": s.left_at,
                    "departed_at": s.departed_at(end),
                    "is_recorder": s.is_recorder,
                }
                for s in verdict.sessions
            ],
        }
        print(json.dumps(payload, indent=2))
        return 0

    if verdict.recorder:
        print(f"PoV:      {verdict.recorder} (wrote the recording)")
    print("Sessions:")
    for session in verdict.sessions:
        print(
            f"  {session.name:20s} team={session.slot.team:>2}  "
            f"{_session_status(session, end, spf)}"
        )
    if verdict.outcome == "decided":
        verb = "wins" if len(verdict.winner_names) == 1 else "win"
        who = ", ".join(verdict.winner_names)
        print(f"Verdict:  {who} {verb} — {verdict.reason} (confidence: {verdict.confidence})")
    else:
        print(f"Verdict:  {verdict.outcome} — {verdict.reason}")
    return 0


def _add_id_arguments(parser: argparse.ArgumentParser) -> None:
    """The player / integer-argument selectors shared by `ids` and `align`."""
    parser.add_argument("--player", type=int, default=None, help="only this slot index")
    parser.add_argument(
        "--arg",
        type=int,
        default=0,
        help="which Integer argument is the id (0 = the first, default)",
    )
    parser.add_argument(
        "--where",
        action="append",
        metavar="INDEX=VALUE",
        help="only orders whose argument INDEX equals VALUE (true/false/int); repeatable. "
        "e.g. --where 0=false selects 0x417's unit/upgrade mode, 0=true its hero mode",
    )


def main(argv: list[str] | None = None) -> int:
    utf8_stdout()
    parser = argparse.ArgumentParser(prog="sage-replay", description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    info = subparsers.add_parser("info", help="header summary: map, players, order counts")
    info.add_argument("replay", type=existing_file)
    info.add_argument("--json", action="store_true")
    info.set_defaults(func=_run_info)

    orders = subparsers.add_parser("orders", help="dump the order stream")
    orders.add_argument("replay", type=existing_file)
    orders.add_argument("--limit", type=int, default=None, help="only the first N orders")
    orders.add_argument("--player", type=int, default=None, help="only this slot index")
    orders.add_argument(
        "--order",
        type=_parse_order_type,
        default=None,
        help="only this order type (hex 0x415 or decimal)",
    )
    orders.add_argument("--json", action="store_true")
    orders.set_defaults(func=_run_orders)

    ids = subparsers.add_parser("ids", help="object-referencing integer ids in the order stream")
    ids.add_argument("replay", type=existing_file)
    ids.add_argument(
        "--order",
        type=_parse_order_type,
        default=None,
        help="show the id runs for this order type instead of the per-order summary",
    )
    _add_id_arguments(ids)
    ids.add_argument("--json", action="store_true")
    ids.set_defaults(func=_run_ids)

    align_parser = subparsers.add_parser(
        "align", help="join a label log to one order's id runs → id/object rows"
    )
    align_parser.add_argument("replay", type=existing_file)
    align_parser.add_argument("labels", type=existing_file, help="plain-text label log")
    align_parser.add_argument(
        "--order",
        type=_parse_order_type,
        required=True,
        help="the id-bearing order type to align (hex 0x415 or decimal)",
    )
    _add_id_arguments(align_parser)
    align_parser.add_argument(
        "--out", type=Path, default=None, help="accumulate the mapping into this JSON file"
    )
    align_parser.add_argument("--json", action="store_true")
    align_parser.set_defaults(func=_run_align)

    narrate_parser = subparsers.add_parser(
        "narrate", help="retell the match in English, resolving ids against a loaded game"
    )
    narrate_parser.add_argument("replay", type=existing_file)
    narrate_parser.add_argument(
        "--game",
        type=Path,
        required=True,
        help="a data/ini tree, or a live install folder whose .big archives are mounted",
    )
    narrate_parser.add_argument(
        "--cache", type=Path, default=None, help="where to mount an install's .big archives"
    )
    narrate_parser.add_argument("--json", action="store_true")
    narrate_parser.set_defaults(func=_run_narrate)

    winner_parser = subparsers.add_parser(
        "winner", help="infer the outcome from session-end signals (concession heuristic)"
    )
    winner_parser.add_argument("replay", type=existing_file)
    winner_parser.add_argument("--json", action="store_true")
    winner_parser.set_defaults(func=_run_winner)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
