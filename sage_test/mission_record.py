"""Record the opening of a running mission, frame by frame, to compare two ways of starting it.

Built to answer "what does a skirmish start of a mission do differently from the campaign's own
start": run it once against a test launch and once against the same mission loaded through the
campaign, and diff the two logs (`python -m sage_test.mission_record diff a.jsonl b.jsonl`).

What a log holds, one JSON object per line:

- `start`: the frame the recorder attached on, the player table, the local player, and every
  script's live state. A one-shot that the map made active and that is already off has fired
  before the recorder caught up - which is how the first frames are seen at all, since the
  trace only records from attach on.
- `fired`: a script ran its true actions (`frame`, `player`, `script`).
- `var`: a counter, flag or timer appeared or changed. Timers count down every frame, so only
  their appearance and expiry are logged, not each tick.
- `money`: a player's resources changed.
- `object` / `gone`: an object appeared or went, with its owner (every player's, not only the
  local player's - an ownership difference is one of the things being looked for).
- `objectives`: the objectives screen changed, as `[bonus, shown, ticked]` per slot.
- `defeat`: the victory conditions changed their mind about someone: per player [index, the
  subsystem's `m_isDefeated` latch, the player's own flag, the frame of the defeat].
- `end`: the frame it stopped on, and every script whose live state differs from `start`.

Attaching is read-only except for the script trace, which writes a cave into the game that
nothing in the game reads, and takes it out again on exit.

    python -m sage_test.mission_record --out opening.jsonl --frames 150   # waits for a match
    python -m sage_test.mission_record diff skirmish.jsonl campaign.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

from sage_live.backends.script_trace import EventKind
from sage_test.mission import read_defeats, read_objectives
from sage_worldbuilder.live import LiveAttachError, LiveIndex, LiveSession, LiveSnapshot, side_label

__all__ = ["DEFAULT_FRAMES", "diff", "main", "record"]

#: Five logic frames a game second on a stock build: 150 frames is the first thirty seconds.
DEFAULT_FRAMES = 150


def _objectives(live: LiveSession) -> list[list[int]]:
    return [[int(o.bonus), int(o.shown), int(o.ticked)] for o in read_objectives(live.memory.read)]


def _defeats(live: LiveSession) -> list[list[int]]:
    """Per player: [player index, the subsystem's latch, the player's own flag, the frame]."""
    return [
        [d.player, int(d.latched), int(d.flagged), d.frame] for d in read_defeats(live.memory.read)
    ]


def _scripts(snapshot: LiveSnapshot) -> dict[str, dict[str, Any]]:
    states = {}
    for side in snapshot.tree.sides:
        player = side_label(side.index, snapshot.players.get(side.index, ""))
        for script in side.all_scripts():
            states[f"{player}/{script.name}"] = {
                "active": script.active,
                "authored": script.authored_active,
                "once": script.one_shot,
            }
    return states


def record(live: LiveSession, out: Path, frames: int = DEFAULT_FRAMES, poll: float = 0.05) -> Path:
    """Record from now until `frames` logic frames have passed, or the game ends."""
    live.set_recording(True)
    snapshot = live.poll()
    while snapshot is None:
        time.sleep(poll)
        snapshot = live.poll()
    observation = live.backend.observe()
    first = snapshot.frame
    scripts_at_start = _scripts(snapshot)

    with out.open("w", encoding="utf-8") as log:

        def write(**entry: Any) -> None:
            log.write(json.dumps(entry, sort_keys=True) + "\n")

        write(
            kind="start",
            frame=first,
            local=observation.local_player,
            players=[[p.index, p.name, p.faction] for p in observation.players],
            scripts=scripts_at_start,
            fired_before_attach=sorted(
                key
                for key, state in scripts_at_start.items()
                if state["once"] and state["authored"] and not state["active"]
            ),
        )
        variables: dict[str, tuple[str, int]] = {}
        objects: dict[int, tuple[str, int | None]] = {}
        money: dict[int, int] = {}
        objectives: list[list[int]] = []
        defeats: list[list[int]] = []
        frame = first
        while frame - first < frames:
            if not live.alive():
                write(kind="exited", frame=frame)
                break
            polled = live.poll()
            if polled is None:
                time.sleep(poll)
                continue
            frame = polled.frame
            index = LiveIndex(polled)
            for event in polled.trace:
                if event.kind is EventKind.FALSE_ACTIONS:
                    continue
                found = index.at(event.script)
                if found is not None:
                    write(kind="fired", frame=event.frame, player=found[0], script=found[1].name)
            for variable in polled.variables:
                # A running timer changes every frame; log it appearing and running out only.
                value = variable.value
                if variable.kind == "timer":
                    value = 1 if value > 0 else 0
                if variables.get(variable.key) != (variable.kind, value):
                    write(
                        kind="var",
                        frame=frame,
                        key=variable.key,
                        type=variable.kind,
                        value=variable.value,
                    )
                    variables[variable.key] = (variable.kind, value)
            observation = live.backend.observe()
            for player in observation.players:
                if money.get(player.index) != player.resources:
                    write(kind="money", frame=frame, player=player.name, value=player.resources)
                    money[player.index] = player.resources
            now = {o.object_id: (o.template_name, o.owner_index) for o in observation.objects}
            for object_id, (template, owner) in now.items():
                if objects.get(object_id) != (template, owner):
                    write(kind="object", frame=frame, id=object_id, template=template, owner=owner)
            for object_id in objects.keys() - now.keys():
                template, owner = objects[object_id]
                write(kind="gone", frame=frame, id=object_id, template=template, owner=owner)
            objects = now
            current = _objectives(live)
            if current != objectives:
                write(kind="objectives", frame=frame, slots=current)
                objectives = current
            beaten = _defeats(live)
            if beaten != defeats:
                write(kind="defeat", frame=frame, players=beaten)
                defeats = beaten
            time.sleep(poll)
        final = live.poll()
        changed = {}
        if final is not None:
            ended = _scripts(final)
            changed = {
                key: state
                for key, state in ended.items()
                if scripts_at_start.get(key, {}).get("active") != state["active"]
            }
        write(kind="end", frame=frame, changed=changed)
    return out


def _load(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _keyed(entries: list[dict[str, Any]], kind: str, fields: tuple[str, ...]) -> set[tuple]:
    return {tuple(entry[f] for f in fields) for entry in entries if entry["kind"] == kind}


def diff(a: Path, b: Path) -> None:
    """Print what happened in one opening and not the other, by kind, ignoring frames and ids."""
    left, right = _load(a), _load(b)
    for title, kind, fields in (
        ("scripts fired", "fired", ("player", "script")),
        ("variables", "var", ("key", "type")),
        ("objects", "object", ("template", "owner")),
        ("objects gone", "gone", ("template", "owner")),
    ):
        only_a = _keyed(left, kind, fields) - _keyed(right, kind, fields)
        only_b = _keyed(right, kind, fields) - _keyed(left, kind, fields)
        print(f"== {title}: only in {a.name} ({len(only_a)}), only in {b.name} ({len(only_b)})")
        for row in sorted(only_a, key=str):
            print(f"  < {row}")
        for row in sorted(only_b, key=str):
            print(f"  > {row}")
    for entries, path in ((left, a), (right, b)):
        start = entries[0]
        print(
            f"== {path.name}: attached at frame {start['frame']}, local {start['local']}, "
            f"players {start['players']}"
        )
        print(f"   fired before attach: {start['fired_before_attach']}")


def _attach_to_match(wait: float) -> LiveSession | None:
    """A live session on a running match, waiting up to `wait` seconds; None if none came."""
    deadline = time.monotonic() + wait
    while True:
        try:
            live = LiveSession.attach()
        except LiveAttachError as exc:
            if time.monotonic() > deadline:
                print(f"no game: {exc}", file=sys.stderr)
                return None
            time.sleep(0.5)
            continue
        # A game at the menus has no map loaded yet; wait for a match's script tree.
        if live.poll() is not None and live.backend.observe().in_match:
            return live
        live.close()
        if time.monotonic() > deadline:
            print("no match started", file=sys.stderr)
            return None
        time.sleep(0.5)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m sage_test.mission_record")
    sub = parser.add_subparsers(dest="command")
    parser.add_argument("--out", type=Path, help="the log to write")
    parser.add_argument("--frames", type=int, default=DEFAULT_FRAMES)
    parser.add_argument("--wait", type=float, default=900.0, help="seconds to wait for a match")
    compare = sub.add_parser("diff")
    compare.add_argument("a", type=Path)
    compare.add_argument("b", type=Path)
    args = parser.parse_args(argv)
    if args.command == "diff":
        diff(args.a, args.b)
        return 0
    if args.out is None:
        parser.error("--out is required")

    live = _attach_to_match(args.wait)
    if live is None:
        return 1
    print(f"attached at frame {live.backend.frame()}, recording {args.frames} frames", flush=True)
    try:
        record(live, args.out, args.frames)
    finally:
        for note in live.close():
            print(f"live session: {note}")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
