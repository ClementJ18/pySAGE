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
- `desync-watch` - follow a match and stop when the engine declares this client out of sync,
  logging the simulation state of every frame on the way. Run it on both machines; the pair of
  logs is what `desync-diff` needs.
- `desync-diff` - the first frame two machines' logs stop agreeing, and whose objects moved.

`info`, `players` and `objects` accept `--json` for machine-readable output.

Every command takes `--pid` (default: the first `game.dat` found) and `--layout-json`, a file
of `EngineLayout` field overrides for a build other than RotWK 2.01 + Edain.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from dataclasses import asdict, replace
from pathlib import Path

from sage_live.api.connect import AttachError, open_backend
from sage_live.api.desync import DEFAULT_HISTORY, DesyncWatcher, compare, read_log
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


def _next_log(args: argparse.Namespace) -> Path | None:
    """A fresh log file for the next match. One file per match, because every match restarts the
    frame counter at 1 and two of them in one file cannot be told apart by frame number."""
    if not args.out:
        return None
    out = Path(args.out)
    if out.is_dir() or not out.suffix:
        out.mkdir(parents=True, exist_ok=True)
        return out / f"desync-{int(time.time())}.jsonl"
    return out


def cmd_desync_watch(args: argparse.Namespace) -> int:
    """Watch until the engine says this client is out of sync.

    Exit codes are the point of this command: **3 means a desync was seen**, 0 means the watch
    ended for a reason that is not one. A run that stopped because the game closed must never
    read as a clean match, so every ending is named rather than collapsed into success.
    """
    # Wait for the process rather than refusing: the watcher has to be armed *before* the match,
    # and on this build alt-tabbing to start one mid-match crashes the game outright. So "the game
    # is not running yet" is the normal state to be started in, not an error.
    #
    # And waiting for the *process* is not enough. `game.dat` exists for several seconds of splash
    # and loading before it constructs `TheGameLogic`, and attaching in that window is refused -
    # which lost a launch. So the whole attach is retried, not just the process lookup.
    if args.await_game:
        if not find_game_processes():
            print("no game.dat yet - waiting for it to start")
        backend = None
        while backend is None:
            if find_game_processes():
                try:
                    backend = open_backend(args.pid, layout=_layout(args.layout_json))
                except AttachError:
                    pass  # still booting: no engine yet, or the handle is not ready
            if backend is None:
                time.sleep(1.0)
    else:
        backend = _attach(args)
    log = Path(args.out) if args.out else None
    if log is not None and (log.is_dir() or not log.suffix):
        # A path with no suffix is meant as a directory even when it does not exist yet. Guessing
        # the other way writes the run to a *file* of that name, which then makes `--summary`
        # underneath it fail at the end - the one moment the summary is worth having.
        log.mkdir(parents=True, exist_ok=True)
        log = log / f"desync-{int(time.time())}.jsonl"

    print(f"frame           {backend.frame()}")
    declared = backend.desync_declared()
    if declared is None:
        raise SystemExit("cannot read the desync latch - is a match actually running?")
    if declared:
        print(
            "NOTE: this client has ALREADY declared a desync; watching from here tells you "
            "nothing new. Restart the match before attaching."
        )
    if log is not None:
        print(f"log             {log}")
    cadence = "latch only" if not args.sample_every else f"every {args.sample_every} frame(s)"
    print(f"sampling        {cadence}")
    if backend.frame() == 0:
        print("no match yet - waiting at the menu for the first logic frame")
    print("watching (ctrl-c to stop)\n")

    # A test session is many matches, and returning to the menu is not a result - it is the gap
    # before the next one. Exiting there means somebody has to re-arm the watcher between every
    # game, which on a build where alt-tabbing crashes the client is exactly the thing to avoid.
    # A desync or a crash still stops: those are results.
    while True:
        with DesyncWatcher(
            backend,
            log=log,
            history=args.history,
            sample_every=args.sample_every,
            poll=args.poll,
            stall_after=args.stall_after,
        ) as watcher:
            reason = watcher.run(limit=args.frames)
        if reason != "left-match" or not args.follow:
            backend.close()
            break
        span = ""
        if watcher.samples:
            span = f" (frames {watcher.samples[0].frame}..{watcher.samples[-1].frame})"
        print(f"match ended{span} - waiting for the next one")
        log = _next_log(args)
        if log is not None:
            print(f"log             {log}")

    summary = watcher.summary()
    # Everything below is reporting, and none of it may throw: by this point the match is over and
    # the JSONL is the deliverable. A bad `--summary` path must cost a warning, not the report.
    if args.summary:
        try:
            target = Path(args.summary)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        except OSError as exc:
            print(
                f"! could not write --summary ({exc}); the JSONL log has the same data",
                file=sys.stderr,
            )

    span = ""
    if summary["first_frame"] is not None:
        span = f", frames {summary['first_frame']}..{summary['last_frame']}"
    print(f"stopped: {reason} ({summary['samples']} samples{span}, {summary['torn']} torn)")
    if reason == "crashed":
        print("the game CRASHED (or was killed) - this is not a clean match")
        print(r"check C:\RotWK for a new DUMP_*.dmp")
        return 4
    if reason == "desync":
        print(f"\nOUT OF SYNC declared at frame {watcher.trigger_frame}")
        print(
            "the divergence is older than that frame - diff this log against the other "
            "machine's with `sage-live desync-diff`"
        )
        return 3
    return 0


def cmd_desync_diff(args: argparse.Namespace) -> int:
    here, there = read_log(Path(args.here)), read_log(Path(args.there))
    print(f"{args.here}: {len(here)} samples")
    print(f"{args.there}: {len(there)} samples")
    divergence = compare(here, there)
    if divergence is None:
        print("\nno divergence in the frames both logs cover")
        return 0
    print()
    print(divergence.describe())
    return 1


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

    dw = add("desync-watch", cmd_desync_watch, "watch until this client declares out of sync")
    dw.add_argument("--out", help="JSONL log file, or a directory to name one in")
    dw.add_argument("--summary", help="write the pre-desync window here as JSON when it stops")
    dw.add_argument(
        "--history",
        type=int,
        default=DEFAULT_HISTORY,
        help=f"samples kept for the summary (default {DEFAULT_HISTORY})",
    )
    dw.add_argument(
        "--sample-every",
        type=int,
        default=1,
        help="take a full state sample every N logic frames (0 = latch only)",
    )
    dw.add_argument("--poll", type=float, default=0.05, help="seconds between latch reads")
    dw.add_argument("--frames", type=int, default=0, help="stop after N frames (0 = forever)")
    dw.add_argument(
        "--stall-after",
        type=float,
        default=30.0,
        help="give up after N seconds with the logic frame frozen (0 = never)",
    )
    dw.add_argument(
        "--no-follow",
        dest="follow",
        action="store_false",
        help="stop when a match ends instead of waiting for the next one",
    )
    dw.add_argument(
        "--no-await-game",
        dest="await_game",
        action="store_false",
        help="fail immediately if no game.dat is running, instead of waiting for one",
    )

    dd = add("desync-diff", cmd_desync_diff, "first frame two machines' logs disagree")
    dd.add_argument("here")
    dd.add_argument("there")

    args = parser.parse_args(argv)
    return int(args.handler(args))


if __name__ == "__main__":
    raise SystemExit(main())
