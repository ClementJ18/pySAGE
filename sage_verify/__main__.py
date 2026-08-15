"""`sage-verify` - check a replay's orders against what its players could see, and check that a
running client is the binary it claims to be.

Two subcommands, one for each half of the anti-cheat work:

- `watch <replay>` - follow that replay playing back in the running game and judge every targeted
  order against the engine's own shroud grid. Start the replay in game first, then run this.
- `attest <game.dat>` - read the live attestation value out of the running process and compare it
  with the one recomputed from the file. Says whether the client is running the binary you have.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from sage_verify.report import Report

__all__ = ["main"]


def _watch(args: argparse.Namespace) -> int:
    # Deferred: `attach` reaches for Windows process APIs, and the parser must stay usable (and
    # `--help` printable) on a machine with no game.
    from sage_live import attach  # noqa: PLC0415
    from sage_replay.replay import parse_replay_from_path  # noqa: PLC0415
    from sage_verify.watch import Watcher  # noqa: PLC0415

    replay = parse_replay_from_path(args.replay)
    print(f"replay: {replay.header.metadata.map_file}  {len(replay.chunks)} chunks")
    print(
        "slots: "
        + ", ".join(
            f"{index}:{slot.human_name!r}"
            for index, slot in enumerate(replay.header.metadata.players)
            if slot.human_name
        )
    )

    session = attach(pid=args.pid)
    print("attached; following playback - start the replay in game if it is not running yet\n")
    try:
        watcher = Watcher(
            replay=replay,
            poll=session.poll,
            max_lag=args.max_lag,
            interval=args.interval,
        )
        report = watcher.run(timeout=args.timeout)
    finally:
        session.close()

    return _emit(report, args)


def _emit(report: Report, args: argparse.Namespace) -> int:
    if args.json:
        print(report.to_json())
    else:
        if report.findings:
            print("violations:")
            for finding in report.findings:
                print(finding.line())
        print(report.summary())
    # A findings-based exit code, so this can gate something. Coverage too low to mean anything
    # is its own code rather than a pass, because "checked nothing" must not read as "clean".
    if report.findings:
        return 1
    if report.coverage < args.min_coverage:
        return 2
    return 0


def _attest(args: argparse.Namespace) -> int:
    # Deferred for the same reason as `_watch`, plus `sage_patch` is a heavier import than a
    # `--help` should pay for.
    from sage_live.backends.memory import ProcessMemory, find_game_processes  # noqa: PLC0415
    from sage_patch.patches.binary_attest import (  # noqa: PLC0415
        HASH_OFF,
        READY_OFF,
        SECTION_NAME,
        expected_hash,
    )
    from sage_patch.utils import find_section  # noqa: PLC0415

    data = Path(args.game_dat).read_bytes()
    located = find_section(data, SECTION_NAME)
    if located is None:
        print(f"{args.game_dat} does not carry binary-attest ({SECTION_NAME} is absent)")
        return 2
    section_va, _, _ = located
    predicted = expected_hash(data)
    print(f"{args.game_dat}\n  expects  0x{predicted:08x}")

    pid = args.pid
    if pid is None:
        found = find_game_processes()
        if not found:
            print("  no running game.dat - launch the game to compare against a live client")
            return 2
        pid = found[0]

    source = ProcessMemory(pid, writable=False)
    try:
        ready = source.read(section_va + READY_OFF, 4)
        live = source.read(section_va + HASH_OFF, 4)
    finally:
        source.close()

    if ready is None or live is None:
        print(f"  pid {pid}: could not read the attest section - is the shell elevated?")
        return 2
    if not int.from_bytes(ready, "little"):
        print(
            f"  pid {pid}: the hash has not been computed yet - it is folded at the first "
            "MSG_LOGIC_CRC heartbeat, so start a match and wait ~100 frames"
        )
        return 2

    value = int.from_bytes(live, "little")
    print(f"  pid {pid} holds 0x{value:08x}")
    if value == predicted:
        print("  MATCH - the running client is this binary")
        return 0
    print("  MISMATCH - the running client is NOT this binary")
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sage-verify", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    watch = sub.add_parser("watch", help="judge a replay's orders against live visibility")
    watch.add_argument("replay", help="the .BfME2Replay file being played back")
    watch.add_argument("--pid", type=int, default=None, help="game.dat pid (default: find it)")
    watch.add_argument(
        "--max-lag",
        type=int,
        default=30,
        help="how stale a visibility sample may be and still judge an order (frames)",
    )
    watch.add_argument("--interval", type=float, default=0.05, help="seconds between polls")
    watch.add_argument("--timeout", type=float, default=None, help="stop after this many seconds")
    watch.add_argument(
        "--min-coverage",
        type=float,
        default=0.5,
        help="exit 2 if fewer than this fraction of targeted orders could be judged",
    )
    watch.add_argument("--json", action="store_true", help="emit the report as JSON")
    watch.set_defaults(func=_watch)

    attest = sub.add_parser("attest", help="compare a running client against a patched game.dat")
    attest.add_argument("game_dat", help="the patched game.dat the client should be running")
    attest.add_argument("--pid", type=int, default=None, help="game.dat pid (default: find it)")
    attest.set_defaults(func=_attest)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
