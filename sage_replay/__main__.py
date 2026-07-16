"""Command-line entry point: `python -m sage_replay <command>` (or `sage-replay`).

- `info <replay>` - header summary: game, version, map, players, duration, and the
  most frequent order types.
- `orders <replay>` - dump the order stream (`--limit`, `--player`, `--order` to filter).
- `ids <replay>` - the object-referencing integer ids in the order stream: a per-order
  summary, or (with `--order`) the timecode-ordered id runs for one order type. The raw
  material for mapping ids to mod objects (see order_space_map.md).
- `align <replay> <labels>` - join a hand-written label log to the id runs of one order
  type and print the inferred `id -> object` rows; `--out` accumulates them into a JSON
  mapping.
- `narrate <replay> --game <root>` - retell the match in English, resolving recruit / build
  / special-power / spellbook / upgrade ids against a loaded game. `--game` takes an
  extracted `data/ini` tree or a live install folder (its `.big` archives are mounted
  automatically into a cache). `--game` is repeatable and layers ascending-priority - pass
  the base game first and the mod after it for a mod that relies on the base game's
  SubsystemLegend.ini / objects.
- `stats <replay> --game <root>` - per-player match statistics: buildings / units / heroes
  built (counts per template type; fortress-hero recruits resolve to hero names through
  the revive-submenu model, falling back to the raw slot number), upgrades
  researched, and the spellbook sciences in purchase order. Same `--game` resolution
  as `narrate`.
- `translate <replay> --game <root> [-o OUT.json]` - write the replay-shaped translated
  document: the order stream with every version-coupled id resolved to its code name and
  everything else kept raw, so the parse can be re-analysed against any game sharing those
  names without the recording build (see `translated.py`). Same `--game` resolution as `narrate`.
- `aggregate <replay|dir>... --game <root>` - corpus-wide stats over many replays: each
  human slot becomes a player-game (faction, won/lost from the ladder metadata sidecar beside
  the replay when present, else the `winner` heuristic, timed stats), grouped by faction into
  win rates plus science / building / unit / hero pick tables - each pick with its own
  win-loss record and median first-purchase clock
  ("does the faction win more with science X or Y?"). Upgrade researches and special-power
  casts are reported only for a tracked set, horde combines only with `--combines`, and
  repeatable system purchases get per-instance depth rows (CPObject1, CPObject2, ...) only
  for one: `--track-upgrade` / `--track-power` / `--track-purchase NAME` (repeatable, powers
  nested under Units), or the `sage-edain replay-aggregate` overlay, which registers this same
  command with Edain's sets injected. The replays must all come from one patch/mod: a
  corpus mixing patch fingerprints (the header's game-data checksum - recordings from
  different game data do not simulate identically) exits 1 listing the groups, before
  any game root is loaded. `--matchups` appends the same tables per enemy
  faction (buildings built vs Mordor, units vs Gondor) after each faction's own sections.
  `--faction` / `--player` filter
  the player-games (case-insensitive substring); `--markdown` renders the same tables
  as GitHub markdown.
- `winner <replay>` - infer the outcome from session-end signals (leave-game orders,
  checksum heartbeats, the end-of-recording marker); a concession heuristic, so the
  verdict may be `undetermined` (see `winner.py`). `winner` and `aggregate` take
  `--winner-pov`: assume the recording player's team won any game the stream leaves
  undetermined (for corpora whose replays belong to the winner).
- `coverage <replay|dir>...` - the format-coverage dashboard: distinct values of every
  still-opaque surface (header reserved blocks, unnamed order ids, raw slot fields,
  untyped metadata keys) across a corpus. `--strict` exits non-zero on any deviation from
  the documented known state; `--diff a b` reports which opaque surfaces differ between two
  replays (see `coverage.py`).

All accept `--json` for machine-readable output.
"""

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

from sage_replay.aggregate import (
    DEFAULT_POWERS_HEADING,
    aggregate,
    collect,
    command_point_weights,
    patch_groups,
    render_aggregate,
    render_aggregate_html,
    render_aggregate_markdown,
)
from sage_replay.coverage import audit, diff_replays
from sage_replay.ids import (
    AlignRow,
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
    Bfme2OrderType,
    GeneralsOrderType,
    OrderArgument,
    ReplayChunk,
    ReplayFile,
    ReplayGameType,
    ReplaySlot,
    ReplaySlotType,
    find_replays,
    parse_replay_from_path,
)
from sage_replay.stats import compute_stats, render_stats
from sage_replay.translated import TranslatedReplay
from sage_replay.winner import PlayerSession, infer_winner
from sage_utils.cli import add_game_arguments, existing_file, utf8_stdout
from sage_utils.clock import clock
from sage_utils.gameroot import resolve_game_roots


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
    """Order ids get their game's decoded name where one exists (Generals via OpenSAGE,
    BFME2 via the ✅-grade `Bfme2OrderType` map); otherwise the raw hex id."""
    if replay.game_type is ReplayGameType.Generals:
        try:
            return GeneralsOrderType(order_type).name
        except ValueError:
            pass
    elif replay.game_type is ReplayGameType.Bfme2:
        try:
            return Bfme2OrderType(order_type).name
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
        "ip": str(slot.ip) if slot.ip is not None else None,
        "port": slot.port,
        "accepted": slot.accepted,
        "has_map": slot.has_map,
        "color": slot.color,
        "faction": slot.faction,
        "start_position": slot.start_position,
        "team": slot.team,
        "nat_behavior": slot.nat_behavior,
        "raw": slot.raw,
    }


def _header_dict(replay: ReplayFile) -> dict:
    header = replay.header
    metadata = header.metadata
    return {
        "game": header.game_type.name,
        "start_time": header.start_time.isoformat(),
        "end_time": header.end_time.isoformat(),
        "num_timecodes": header.num_timecodes,
        "crc_interval": header.crc_interval,
        "abnormal_end_frame": header.abnormal_end_frame,
        "crashed": replay.crashed,
        "local_player_index": header.local_player_index,
        "data_checksum": header.data_checksum,
        "filename": header.filename,
        "timestamp": str(header.timestamp),
        "version": header.version,
        "build_date": header.build_date,
        "map_file": metadata.map_file,
        "map_contents_mask": metadata.map_contents_mask,
        "map_crc": metadata.map_crc,
        "map_size": metadata.map_size,
        "seed": metadata.seed,
        "starting_credits": metadata.starting_credits,
        "install_id": metadata.install_id,
        "game_rules": list(metadata.game_rules),
        "starting_resources": metadata.starting_resources,
        "command_points": metadata.command_points,
        "metadata": metadata.values,
        "players": [_slot_dict(s) for s in metadata.players],
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
    print(f"{header.game_type.name} replay - {header.version}")
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
            id_text = str(row.id) if row.id is not None else "-"
            print(f" {mark} {id_text:>8s}  {row.name}  ({row.replay_count}/{row.label_count})")
        for warning in warnings:
            print(f"warning: {warning}", file=sys.stderr)

    if args.out is not None:
        conflicts = _merge_mapping(Path(args.out), labels.metadata, args.order, rows)
        for conflict in conflicts:
            print(f"conflict: {conflict}", file=sys.stderr)

    return 1 if warnings else 0


def _merge_mapping(
    path: Path, metadata: dict[str, str], order_type: int, rows: list[AlignRow]
) -> list[str]:
    """Merge confidently-aligned rows into a growing `id -> object` JSON mapping keyed
    by order type, and return conflicts (an id already mapped to a different name)."""
    mapping = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    mapping.setdefault("metadata", {}).update(metadata)
    orders = mapping.setdefault("orders", {})
    key = f"0x{order_type:X}"
    table = orders.setdefault(key, {})

    conflicts = []
    for row in rows:
        # Only record rows whose run length matched the label - a mismatch means the
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


def _run_narrate(args: argparse.Namespace) -> int:
    replay = parse_replay_from_path(args.replay)
    games = resolve_game_roots(args.game, args.cache)
    data = GameData.from_root(
        games, localize=args.localized, map_file=replay.header.metadata.map_file
    )

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


def _run_stats(args: argparse.Namespace) -> int:
    replay = parse_replay_from_path(args.replay)
    games = resolve_game_roots(args.game, args.cache)
    data = GameData.from_root(
        games, localize=args.localized, map_file=replay.header.metadata.map_file
    )

    if args.json:
        payload = {
            "map_file": replay.header.metadata.map_file,
            "players": [per.to_dict() for per in compute_stats(replay, data)],
        }
        print(json.dumps(payload, indent=2))
        return 0

    for line in render_stats(replay, data):
        print(line)
    return 0


def _run_translate(args: argparse.Namespace) -> int:
    replay = parse_replay_from_path(args.replay)
    games = resolve_game_roots(args.game, args.cache)
    data = GameData.from_root(
        games, localize=args.localized, map_file=replay.header.metadata.map_file
    )
    document = TranslatedReplay.from_replay(Path(args.replay), replay, data)
    if args.out is not None:
        document.write(args.out)
        print(f"wrote {args.out}", file=sys.stderr)
    else:
        print(json.dumps(document.to_dict(), ensure_ascii=False, indent=2))
    return 0


def _session_status(session: PlayerSession, end: int, spf: float) -> str:
    """One human session's ending, in words, for the `winner` text output."""
    departed = session.departed_at(end)
    if session.left_at is not None:
        when = f" ({clock(session.left_at * spf)})" if spf else ""
        return f"left the game at frame {session.left_at}{when}"
    if departed is not None:
        when = f" ({clock(departed * spf)})" if spf else ""
        return f"went silent at frame {departed}{when} - likely dropped"
    parts = []
    if session.last_order is not None:
        parts.append(f"last order -{end - session.last_order}")
    if session.last_heartbeat is not None:
        parts.append(f"last heartbeat -{end - session.last_heartbeat}")
    return f"present at end ({', '.join(parts)} frames)" if parts else "present at end"


def _run_aggregate(args: argparse.Namespace) -> int:
    replays = find_replays(args.paths)
    if not replays:
        print("aggregate: no replays found under the given paths", file=sys.stderr)
        return 2
    groups = patch_groups(replays)
    if len(groups) > 1:
        print(
            "aggregate: the replays span multiple game patches/mods and their stats are "
            "not comparable; aggregate each group separately:",
            file=sys.stderr,
        )
        for fingerprint, group_paths in sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0])):
            names = [p.name for p in group_paths]
            print(f"  {fingerprint}: {len(names)} replays (e.g. {names[0]})", file=sys.stderr)
        return 1

    games = resolve_game_roots(args.game, args.cache)
    data = GameData.from_root(games, localize=args.localized)

    corpus = collect(
        args.paths,
        data,
        assume_pov_won=args.winner_pov,
        refine_faction=args.refine_faction,
        relabel_power=args.relabel_power,
        power_recruits=args.power_recruits,
        upgrade_recruits=args.upgrade_recruits,
        ignore_recruits=args.ignore_recruits,
    )
    if args.faction is not None:
        needle = args.faction.lower()
        corpus.games = [g for g in corpus.games if needle in g.faction.lower()]
    if args.player is not None:
        needle = args.player.lower()
        corpus.games = [g for g in corpus.games if needle in g.player.lower()]
    # Player-level researches (`Type = PLAYER` - armory tech, a clan pick) always earn rows;
    # the per-battalion OBJECT gear purchases stay out unless explicitly tracked.
    tracked = data.player_upgrades | args.tracked_upgrades | frozenset(args.track_upgrade or [])
    purchases = args.tracked_purchases | frozenset(args.track_purchase or [])
    powers = args.tracked_powers | frozenset(args.track_power or [])
    factions = aggregate(
        corpus.games,
        tracked_upgrades=tracked,
        tracked_purchases=purchases,
        tracked_powers=powers,
        include_combines=args.combines,
        matchups=args.matchups,
    )

    if args.json:
        payload = {
            "replays": corpus.replays,
            "player_games": len(corpus.games),
            "warnings": corpus.warnings,
            "games": [
                {
                    "replay": g.replay,
                    "player": g.player,
                    "faction": g.faction,
                    "outcome": g.outcome,
                    "duration_seconds": g.duration,
                }
                for g in corpus.games
            ],
            "factions": [agg.to_dict() for agg in factions],
        }
        print(json.dumps(payload, indent=2))
    elif args.html:
        html = render_aggregate_html(
            corpus,
            factions,
            powers_heading=args.powers_heading,
            weight=command_point_weights(data),
        )
        for line in html:
            print(line)
    else:
        render = render_aggregate_markdown if args.markdown else render_aggregate
        for line in render(corpus, factions, powers_heading=args.powers_heading):
            print(line)
    for warning in corpus.warnings:
        print(f"warning: {warning}", file=sys.stderr)
    return 0


def add_aggregate_command(
    subparsers,
    *,
    name: str = "aggregate",
    tracked_upgrades: frozenset[str] = frozenset(),
    tracked_purchases: frozenset[str] = frozenset(),
    tracked_powers: frozenset[str] = frozenset(),
    powers_heading: str = DEFAULT_POWERS_HEADING,
    refine_faction=None,
    relabel_power=None,
    power_recruits=None,
    upgrade_recruits=None,
    ignore_recruits: frozenset[str] = frozenset(),
) -> argparse.ArgumentParser:
    """Register the corpus-aggregate subcommand on an argparse `subparsers`. Player-level
    upgrade researches (`Type = PLAYER` in the loaded game - see `GameData.player_upgrades`)
    always earn Upgrades rows. A mod overlay that knows which further upgrade researches
    deserve a pick-rate row, which system purchases
    are depth-comparable, and which special powers are worth a row registers the same command
    on its own CLI with its `tracked_upgrades` / `tracked_purchases` / `tracked_powers`
    injected (sage_edain's `replay-aggregate`); `--track-upgrade` / `--track-purchase` /
    `--track-power` extend whatever was injected. Tracked powers render nested under Units as
    `powers_heading` (the casting unit's name - Edain's is "Loremaster"). `refine_faction` (a
    `FactionRefiner`) lets the overlay sharpen faction labels from each player's own stats,
    e.g. Edain's Dwarves into their realm. `relabel_power` (a `PowerLabeler`) renames
    special-power casts from the caster's faction Side, e.g. reading Imladris's four shared
    Lichtbringer toggle powers as `Lichtbringer -> Earth/Light/Water/Air` (the names
    `tracked_powers` then matches). `power_recruits` (a `PowerRecruits`) lets the overlay
    inject the units a power cast permanently fields as ordinary recruits, e.g. Edain's Mordor
    summons and Leuchtfeuer signal fires, so they merge into the buildings/units/heroes tables;
    `upgrade_recruits` (an `UpgradeRecruits`) does the same for dedication researches whose
    conversion fires engine-side, e.g. Edain's Angmar ThrallMaster and Rohan Hauptmann.
    `ignore_recruits` (raw template code names) drops recruits whose real signal is a later power
    cast, e.g. Edain's elementless `BruchtalLichtbringerHorde` placeholder (its Loremaster row
    comes from the toggle `power_recruits` reads instead)."""
    parser = subparsers.add_parser(
        name,
        help="corpus-wide faction stats over many replays: win rates and science/build "
        "pick tables with per-pick win-loss records and timings",
    )
    parser.add_argument(
        "paths",
        nargs="+",
        type=Path,
        help="replays and/or directories to aggregate (searched recursively)",
    )
    add_game_arguments(
        parser,
        game_help="a data/ini tree, or a live install folder whose .big archives are mounted",
    )
    parser.add_argument(
        "--localized",
        action="store_true",
        help="resolve localized DisplayNames from the string table instead of raw ini code names",
    )
    parser.add_argument(
        "--faction",
        default=None,
        help="only player-games of factions matching this name (case-insensitive substring)",
    )
    parser.add_argument(
        "--player",
        default=None,
        help="only player-games of players matching this name (case-insensitive substring)",
    )
    parser.add_argument(
        "--track-upgrade",
        action="append",
        metavar="NAME",
        default=None,
        help="report this upgrade's researches in the Upgrades pick tables (raw ini code "
        "name; repeatable). Upgrades whose Type is PLAYER are always tracked; this extends "
        "them (e.g. with a per-battalion OBJECT purchase)",
    )
    parser.add_argument(
        "--track-purchase",
        action="append",
        metavar="NAME",
        default=None,
        help="number this repeatable system purchase per instance (CPObject1, CPObject2, "
        "...) so purchase depth compares across games (raw ini template name; repeatable, "
        "extends the command's built-in tracked set)",
    )
    parser.add_argument(
        "--track-power",
        action="append",
        metavar="NAME",
        default=None,
        help="report this special power's casts in a pick table nested under Units (the "
        "power's code name, or an overlay's relabelled name; repeatable, extends the "
        "command's built-in tracked set). Powers are hidden by default",
    )
    parser.add_argument(
        "--combines",
        action="store_true",
        help="include horde combines (the Edain 0x423 horde-merge), hidden by default",
    )
    parser.add_argument(
        "--matchups",
        action="store_true",
        help="also build every pick table per enemy faction (buildings built vs Mordor, "
        "units vs Gondor), appended after each faction's own sections",
    )
    _add_winner_pov(parser)
    output_format = parser.add_mutually_exclusive_group()
    output_format.add_argument("--json", action="store_true")
    output_format.add_argument(
        "--markdown",
        action="store_true",
        help="render the aggregation as GitHub markdown (a table per pick category)",
    )
    output_format.add_argument(
        "--html",
        action="store_true",
        help="render the aggregation as one self-contained HTML page (stat tiles, "
        "win-rate bars, collapsible matchup blocks)",
    )
    parser.set_defaults(
        func=_run_aggregate,
        tracked_upgrades=tracked_upgrades,
        tracked_purchases=tracked_purchases,
        tracked_powers=tracked_powers,
        powers_heading=powers_heading,
        refine_faction=refine_faction,
        relabel_power=relabel_power,
        power_recruits=power_recruits,
        upgrade_recruits=upgrade_recruits,
        ignore_recruits=ignore_recruits,
    )
    return parser


def _run_winner(args: argparse.Namespace) -> int:
    replay = parse_replay_from_path(args.replay)
    verdict = infer_winner(replay, assume_pov_won=args.winner_pov)
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
        print(f"Verdict:  {who} {verb} - {verdict.reason} (confidence: {verdict.confidence})")
    else:
        print(f"Verdict:  {verdict.outcome} - {verdict.reason}")
    return 0


def _run_coverage(args: argparse.Namespace) -> int:
    if args.diff is not None:
        a = parse_replay_from_path(args.diff[0])
        b = parse_replay_from_path(args.diff[1])
        lines = diff_replays(a, b)
        if args.json:
            print(json.dumps({"diff": lines}, indent=2))
        else:
            print("\n".join(lines))
        return 0

    if not args.paths:
        print("coverage: give one or more replays/directories, or --diff A B", file=sys.stderr)
        return 2

    report = audit(args.paths)
    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(report.format_text())

    return 1 if args.strict and report.strict_failures() else 0


def _add_winner_pov(parser: argparse.ArgumentParser) -> None:
    """The `--winner-pov` assumption shared by `winner` and `aggregate`."""
    parser.add_argument(
        "--winner-pov",
        action="store_true",
        help="assume the recording player's team won any game the stream leaves "
        "undetermined (for corpora whose replays belong to the winner); explicit "
        "evidence - a leave-game order - still wins over the assumption",
    )


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
    add_game_arguments(
        narrate_parser,
        game_help="a data/ini tree, or a live install folder whose .big archives are mounted",
    )
    narrate_parser.add_argument(
        "--localized",
        action="store_true",
        help="resolve localized DisplayNames from the string table (Misty Mountains) instead of "
        "the raw ini code names (FactionWild), which are used by default",
    )
    narrate_parser.add_argument("--json", action="store_true")
    narrate_parser.set_defaults(func=_run_narrate)

    stats_parser = subparsers.add_parser(
        "stats",
        help="per-player building/unit/hero/upgrade counts and science purchase order",
    )
    stats_parser.add_argument("replay", type=existing_file)
    add_game_arguments(
        stats_parser,
        game_help="a data/ini tree, or a live install folder whose .big archives are mounted",
    )
    stats_parser.add_argument(
        "--localized",
        action="store_true",
        help="resolve localized DisplayNames from the string table instead of raw ini code names",
    )
    stats_parser.add_argument("--json", action="store_true")
    stats_parser.set_defaults(func=_run_stats)

    add_aggregate_command(subparsers)

    translate_parser = subparsers.add_parser(
        "translate",
        help="write the replay-shaped translated document (every version-coupled id resolved "
        "to its code name) for portable, install-free analysis",
    )
    translate_parser.add_argument("replay", type=existing_file)
    add_game_arguments(
        translate_parser,
        game_help="a data/ini tree, or a live install folder whose .big archives are mounted",
    )
    translate_parser.add_argument(
        "--localized",
        action="store_true",
        help="resolve localized DisplayNames from the string table instead of raw ini code names",
    )
    translate_parser.add_argument(
        "-o",
        "--out",
        type=Path,
        default=None,
        help="write the document here as compact JSON; without it, pretty JSON goes to stdout",
    )
    translate_parser.set_defaults(func=_run_translate)

    winner_parser = subparsers.add_parser(
        "winner", help="infer the outcome from session-end signals (concession heuristic)"
    )
    winner_parser.add_argument("replay", type=existing_file)
    _add_winner_pov(winner_parser)
    winner_parser.add_argument("--json", action="store_true")
    winner_parser.set_defaults(func=_run_winner)

    coverage_parser = subparsers.add_parser(
        "coverage",
        help="format-coverage dashboard over a corpus (--strict gate, --diff A B)",
    )
    coverage_parser.add_argument(
        "paths",
        nargs="*",
        type=Path,
        help="replays and/or directories to audit (searched recursively)",
    )
    coverage_parser.add_argument(
        "--strict",
        action="store_true",
        help="exit non-zero on any deviation from the documented known state",
    )
    coverage_parser.add_argument(
        "--diff",
        nargs=2,
        metavar=("A", "B"),
        type=existing_file,
        default=None,
        help="report which still-opaque surfaces differ between two replays",
    )
    coverage_parser.add_argument("--json", action="store_true")
    coverage_parser.set_defaults(func=_run_coverage)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
