"""Command-line entry point: `python -m sage_live <command>` (or `sage-live`).

A live game inspector over the read-only `MemoryBackend` - no injection, nothing written to
the game. It needs an **elevated** shell, because `game.dat` runs as administrator and
`ReadProcessMemory` is refused otherwise.

- `processes` - the running `game.dat` pids, so the other commands have something to attach
  to. Also the quickest check that this shell is elevated enough to read at all.
- `info` - one snapshot: logic frame, the local player, every player's faction and economy,
  and the object census by side. The command to answer "is a game running and what is it".
- `players` - the player table on its own, including the engine-managed sides (`Civilian`,
  `Creeps`, `Observer`) that a consumer must filter out rather than treat as opponents.
- `objects` - the live object list, grouped by template with counts (`--list` for one row per
  object with its id, position and health). `--side`, `--owner`, `--upgrade` and `--damaged`
  filter it; note that `--owner` is real ownership and `--side` is the template's declared
  faction, and the two genuinely disagree.
- `snapshot` - the entire observation as one JSON document, every field of every player and
  object. The export for a consumer that is not Python.
- `watch` - stream a line per logic frame: frame number, object count, the local player's
  resources. The tool for watching an opening play out, or for checking that `step()` tracks
  the engine.

`info`, `players` and `objects` accept `--json` for machine-readable output.

Every command takes `--pid` (default: the first `game.dat` found) and `--layout-json`, a file
of `EngineLayout` field overrides for a build other than RotWK 2.01 + Edain.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from dataclasses import asdict, replace
from pathlib import Path

from sage_live.api.connect import AttachError, open_backend
from sage_live.api.observation import GameObject, Observation
from sage_live.backends.memory import (
    LAYOUT_ROTWK_201,
    EngineLayout,
    MemoryBackend,
    find_game_processes,
)
from sage_patch.patches.experimental.live_bridge import SECTION_NAME

__all__ = ["main"]


def _layout(path: str | None) -> EngineLayout:
    if not path:
        return LAYOUT_ROTWK_201
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    known = set(asdict(LAYOUT_ROTWK_201))
    unknown = sorted(set(raw) - known)
    if unknown:
        raise SystemExit(f"unknown EngineLayout fields: {', '.join(unknown)}")
    return replace(LAYOUT_ROTWK_201, **raw)


def _attach(args: argparse.Namespace) -> MemoryBackend:
    try:
        return open_backend(args.pid, layout=_layout(args.layout_json))
    except AttachError as exc:
        raise SystemExit(str(exc)) from exc


def _observe(args: argparse.Namespace) -> tuple[MemoryBackend, Observation]:
    backend = _attach(args)
    observation = backend.observe()
    return backend, observation


def _object_row(o: GameObject) -> str:
    health = f"{o.health * 100:5.1f}% of {o.max_health:.0f}" if o.has_body else "    -"
    return (
        f"  {o.object_id:>6}  {o.template_side:<10} {o.template_name:<34} "
        f"({o.position[0]:8.1f}, {o.position[1]:8.1f}, {o.position[2]:6.1f})  {health}"
    )


def cmd_processes(args: argparse.Namespace) -> int:
    found = find_game_processes()
    if not found:
        print("no running game.dat")
        return 1
    for pid in found:
        print(pid)
    return 0


def cmd_info(args: argparse.Namespace) -> int:
    backend, obs = _observe(args)
    if args.json:
        identity = backend.identity
        print(
            json.dumps(
                {
                    "build": None if identity is None else identity.fingerprint,
                    "live_bridge": identity is not None and identity.carries(SECTION_NAME),
                    "frame": obs.frame,
                    "local_player": obs.local_player,
                    "fogged": obs.fogged,
                    "players": [p.to_dict() for p in obs.players],
                    "objects_by_side": dict(Counter(o.template_side for o in obs.objects)),
                    "object_count": len(obs.objects),
                },
                indent=2,
            )
        )
        return 0

    identity = backend.identity
    if identity is not None:
        bridge = "yes" if identity.carries(SECTION_NAME) else "no (read-only; orders need it)"
        print(f"build           {identity.fingerprint}")
        print(f"live-bridge     {bridge}")
    print(f"frame           {obs.frame}")
    print(f"local player    {obs.local_player}")
    print(f"fog applied     {obs.fogged}")
    print(f"\nplayers ({len(obs.players)})")
    for p in obs.players:
        marker = " <- local" if p.index == obs.local_player else ""
        print(
            f"  [{p.index}] {p.name:<16} {p.faction:<10} "
            f"resources {p.resources:>8}  collected {p.resources_collected:>8}"
            f"  spent {p.spent:>8}{marker}"
        )
    print(f"\nobjects ({len(obs.objects)})")
    for side, n in Counter(o.template_side for o in obs.objects).most_common():
        print(f"  {n:>6}  {side}")
    for d in backend.diagnostics:
        print(f"  ! {d}", file=sys.stderr)
    return 0


def cmd_players(args: argparse.Namespace) -> int:
    _, obs = _observe(args)
    if args.json:
        print(json.dumps([p.to_dict() for p in obs.players], indent=2))
        return 0
    for p in obs.players:
        print(
            f"[{p.index}] {p.name:<16} {p.faction:<10} "
            f"resources={p.resources} collected={p.resources_collected} spent={p.spent}"
        )
    return 0


def cmd_objects(args: argparse.Namespace) -> int:
    _, obs = _observe(args)
    objects = obs.find(
        side=args.side,
        owner=args.owner,
        upgrade=args.upgrade,
        damaged=True if args.damaged else None,
    )

    if args.json:
        print(json.dumps([o.to_dict() for o in objects], indent=2))
        return 0
    if args.list:
        for o in sorted(objects, key=lambda x: x.object_id):
            print(_object_row(o))
        print(f"\n{len(objects)} objects")
        return 0
    for name, n in obs.census(objects).most_common():
        print(f"  {n:>5}  {name}")
    print(f"\n{len(objects)} objects, {len({o.template_name for o in objects})} templates")
    return 0


def cmd_snapshot(args: argparse.Namespace) -> int:
    """The whole observation as JSON - every player and every object, all fields.

    The export for a consumer that is not Python: one document with the same field names the
    dataclasses carry, so a reader of `observation.py` can read this without a schema.
    """
    _, obs = _observe(args)
    print(json.dumps(obs.to_dict(), indent=None if args.compact else 2))
    return 0


def cmd_watch(args: argparse.Namespace) -> int:
    backend = _attach(args)
    local = backend.local_player_index()
    print(f"{'frame':>10} {'objects':>8} {'resources':>10}   (ctrl-c to stop)")
    try:
        for _ in range(args.frames) if args.frames else iter(int, 1):
            obs = backend.step(timeout=args.timeout)
            if obs is None:
                print("(no frame advance - game paused or ended)")
                break
            player = obs.player(local)
            resources = player.resources if player else 0
            print(f"{obs.frame:>10} {len(obs.objects):>8} {resources:>10}")
    except KeyboardInterrupt:
        pass
    finally:
        backend.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="sage-live", description="Inspect a running BFME2 / RotWK game (read-only)."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add(name: str, handler, help_text: str) -> argparse.ArgumentParser:
        sub = subparsers.add_parser(name, help=help_text)
        sub.set_defaults(handler=handler)
        sub.add_argument("--pid", type=int, help="target process (default: first game.dat)")
        sub.add_argument("--layout-json", help="EngineLayout field overrides for another build")
        return sub

    add("processes", cmd_processes, "list running game.dat pids")

    info = add("info", cmd_info, "one snapshot: frame, players, object census")
    info.add_argument("--json", action="store_true")

    players = add("players", cmd_players, "the player table")
    players.add_argument("--json", action="store_true")

    objects = add("objects", cmd_objects, "live objects, grouped or listed")
    objects.add_argument("--list", action="store_true", help="one row per object")
    objects.add_argument("--side", help="filter to one Side (Men, Mordor, Wild, ...)")
    objects.add_argument("--owner", type=int, help="filter to one player index (real ownership)")
    objects.add_argument("--upgrade", help="only objects carrying this OBJECT-scoped upgrade")
    objects.add_argument("--damaged", action="store_true", help="only objects that took damage")
    objects.add_argument("--json", action="store_true")

    snapshot = add("snapshot", cmd_snapshot, "the whole observation as JSON")
    snapshot.add_argument("--compact", action="store_true", help="one line, for piping")

    watch = add("watch", cmd_watch, "stream one line per logic frame")
    watch.add_argument("--frames", type=int, default=0, help="stop after N frames (0 = forever)")
    watch.add_argument("--timeout", type=float, default=5.0)

    args = parser.parse_args(argv)
    return int(args.handler(args))


if __name__ == "__main__":
    raise SystemExit(main())
