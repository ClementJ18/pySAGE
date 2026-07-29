"""Acceptance test, part 2: check the recorded replay against what was injected.

Answers three questions, reported separately because they fail independently:

1. **Did the orders reach the replay at all?** If they did, injection goes through the engine's
   real input path, which is the whole claim the patch rests on.
2. **Did the arguments survive?** Type and value per argument, with a float tolerance applied
   only to `Position`.
3. **Is the live object id the same id the stream uses?** The injected `select` carries an
   ObjectId read straight from the runtime object table, so whatever the replay records for it
   answers this directly.

Run from the repo root after ending the game:

    python examples/sage_live/acceptance_verify.py
    python examples/sage_live/acceptance_verify.py --replay "path/to/Some Replay.BfME2Replay"
"""

import json
import os
import sys
from argparse import ArgumentParser
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # repo root on path

from sage_replay import ReplayChunk, parse_replay_from_path  # noqa: E402

DEFAULT_LOG = Path("acceptance_log.json")
DEFAULT_REPLAY = Path(
    os.path.expandvars(
        r"%APPDATA%\My The Lord of the Rings, The Rise of the Witch-king Files"
        r"\Replays\Last Replay.BfME2Replay"
    )
)
TOLERANCE = 0.5  # float32 round-trip, plus any snapping the engine applies


def values_match(expected: object, actual: object) -> bool:
    if isinstance(expected, (list, tuple)) and isinstance(actual, (list, tuple)):
        return len(expected) == len(actual) and all(
            values_match(e, a) for e, a in zip(expected, actual, strict=True)
        )
    if isinstance(expected, bool) or isinstance(actual, bool):
        return bool(expected) == bool(actual)
    if isinstance(expected, float) or isinstance(actual, float):
        return abs(float(expected) - float(actual)) <= TOLERANCE  # type: ignore[arg-type]
    return expected == actual


def main() -> int:
    parser = ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--log", type=Path, default=DEFAULT_LOG)
    parser.add_argument("--replay", type=Path, default=DEFAULT_REPLAY)
    args = parser.parse_args()

    if not args.log.exists():
        raise SystemExit(f"no injection log at {args.log} - run acceptance_inject.py first")
    if not args.replay.exists():
        raise SystemExit(f"no replay at {args.replay}")
    log = json.loads(args.log.read_text(encoding="utf-8"))

    replay = parse_replay_from_path(str(args.replay))
    print(f"replay: {args.replay.name}  {len(replay.chunks)} chunks")
    print(f"order types present: {Counter(c.order_type for c in replay.chunks).most_common(8)}")
    print(f"\ninjected {len(log['orders'])} orders as player_index {log['local_player_index']}")

    # Match in sequence, so a repeated order type cannot match the same chunk twice.
    cursor = 0
    results: list[tuple[dict, ReplayChunk | None]] = []
    for entry in log["orders"]:
        found = None
        for i in range(cursor, len(replay.chunks)):
            if replay.chunks[i].order.order_type == entry["order_type"]:
                found = i
                break
        results.append((entry, None if found is None else replay.chunks[found]))
        if found is not None:
            cursor = found + 1

    ok = True
    print("\n=== 1. did the injected orders reach the replay? ===")
    for entry, chunk in results:
        if chunk is None:
            print(f"  MISSING  {entry['label']:<11} type {entry['order_type']:#06x}")
            ok = False
        else:
            print(
                f"  found    {entry['label']:<11} type {entry['order_type']:#06x}  "
                f"timecode {chunk.timecode}  player {chunk.order.player_index}"
            )

    print("\n=== 2. do the arguments survive? ===")
    for entry, chunk in results:
        if chunk is None:
            continue
        expected, actual = entry["arguments"], chunk.order.arguments
        if len(expected) != len(actual):
            print(f"  {entry['label']}: sent {len(expected)} args, recorded {len(actual)}")
            ok = False
            continue
        for e, a in zip(expected, actual, strict=True):  # lengths checked just above
            good = int(e["argument_type"]) == int(a.argument_type) and values_match(
                e["value"], a.value
            )
            ok = ok and good
            print(
                f"  {'ok  ' if good else 'DIFF'} {entry['label']:<11} "
                f"type {e['argument_type']}->{int(a.argument_type)}  "
                f"sent {e['value']!r}  recorded {a.value!r}"
            )

    print("\n=== 3. is the live object id the stream's ObjectId? ===")
    select = next((c for e, c in results if c is not None and e["label"] == "select"), None)
    if select is None:
        print("  no select chunk recorded - cannot answer")
    else:
        from_memory = log["subject_object_id"]
        ids = [a.value for a in select.order.arguments if int(a.argument_type) == 3]
        print(f"  read from the live object table : {from_memory}")
        print(f"  recorded in the replay          : {ids}")
        if ids and ids[0] == from_memory:
            print("  MATCH - one id space, so ids cross between memory and stream directly.")
        else:
            print("  DIFFERENT - two id spaces; a mapping is needed before ids can cross.")

    print("\nRESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
