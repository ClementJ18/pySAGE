"""Record a running match to a replayable snapshot, and its decode to a golden file.

This is how `tests/sage_live/fixtures/` is regenerated. Run it during a real match:

    python examples/sage_live/capture_snapshot.py tests/sage_live/fixtures/match

writing `match.snapshot.gz` (the process bytes the decode touched) and `match.expected.json`
(what those bytes decoded to). The test replays the first and compares against the second, so
a layout regression fails in the data-free suite instead of waiting for someone to notice a
live reading looks odd.

**Regenerating is a deliberate act.** The golden file is the *output* of a run believed good;
overwriting it makes any regression it would have caught disappear. Regenerate when the model
gains a field, not when a test fails.

**The registries are deliberately left out.** Walking `TheThingFactory` and
`TheSpecialPowerStore` would add five figures of templates and take the snapshot from ~170 KB
to ~1.8 MB, for facts that are corroborated on their own terms - the power store agrees with
the ini reconstruction on all 1,566 entries. What only a real process can vouch for is the
object graph: the module list, the production queue, the containment pointer, the upgrade
masks. Pass `--registries` to include them anyway.
"""

from __future__ import annotations

import json
import sys
from argparse import ArgumentParser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sage_live.memory import MemoryBackend, ProcessMemory, find_game_processes  # noqa: E402
from sage_live.snapshot import RecordingSource  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("stem", help="output path stem, e.g. tests/sage_live/fixtures/match")
    parser.add_argument("--pid", type=int, help="target process (default: first game.dat)")
    parser.add_argument(
        "--registries",
        action="store_true",
        help="also capture the thing and power tables (adds about 1.6 MB)",
    )
    args = parser.parse_args(argv)

    # Built by hand rather than through `attach`, so the recorder is in place *before*
    # `connect` runs: the build gate reads the PE headers, and a snapshot that does not carry
    # them cannot be connected to when it is replayed.
    pid = args.pid
    if pid is None:
        found = find_game_processes()
        if not found:
            raise SystemExit("no running game.dat")
        pid = found[0]
    try:
        source = ProcessMemory(pid)
    except (PermissionError, RuntimeError) as exc:
        raise SystemExit(f"{exc}\nthe game runs as administrator; this shell must be too") from exc

    recorder = RecordingSource(source)
    backend = MemoryBackend(recorder)
    backend.connect()

    backend.upgrade_table()  # the object and player upgrade masks decode to names
    if args.registries:
        backend.thing_order()
        backend.power_order()
    else:
        # Seed them empty so a production entry records its kind without dragging the whole
        # template table in behind the name lookup.
        backend._things = ()
        backend._powers = ()

    observation = backend.observe()
    if not observation.objects:
        raise SystemExit("no objects: start a match first - the menu's shell map is not one")

    stem = Path(args.stem)
    stem.parent.mkdir(parents=True, exist_ok=True)
    size = recorder.save(stem.with_suffix(".snapshot.gz"))
    golden = stem.with_suffix(".expected.json")
    golden.write_text(json.dumps(observation.to_dict(), indent=1, sort_keys=True), encoding="utf-8")

    print(f"{recorder.reads} reads over {len(recorder.merged())} merged ranges")
    print(f"  {stem.with_suffix('.snapshot.gz').name}: {size:,} bytes")
    print(f"  {golden.name}: {golden.stat().st_size:,} bytes")
    print(
        f"frame {observation.frame}, {len(observation.objects)} objects, "
        f"{len(observation.players)} players, "
        f"{sum(1 for o in observation.objects if o.parent_id is not None)} contained, "
        f"{sum(1 for o in observation.objects if o.producing)} producing, "
        f"{sum(1 for o in observation.objects if o.upgrades)} upgraded"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
