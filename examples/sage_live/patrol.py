"""Grab the starter units and walk them back and forth.

The smallest thing that shows the whole live API at once: read the world out of the running
process, decide something, and act on it through the patched engine's own input path.

Run from the repo root, in an elevated shell, with a match actually running:

    python examples/sage_live/patrol.py
    python examples/sage_live/patrol.py --laps 5 --distance 250
    python examples/sage_live/patrol.py --axis y

`--game` points at an install or an ini tree, and is what lets the starting units be named
exactly: they are the faction's `PlayerTemplate` roster, and nothing on the objects themselves
says so. Without it the script orders the first two things you own instead.
"""

import sys
import time
from argparse import ArgumentParser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # repo root on path

from _common import attach, centre_of, describe, issue, starter_units  # noqa: E402

from sage_live import orders  # noqa: E402
from sage_live.backends.bridge import BridgeBackend  # noqa: E402


def report(backend: BridgeBackend, ids: set[int]) -> None:
    observation = backend.observe()
    here = [o for o in observation.objects if o.object_id in ids]
    where = "  ".join(f"{o.object_id}:({o.position[0]:.0f},{o.position[1]:.0f})" for o in here)
    print(f"      frame {observation.frame:>6}  {where}")


def main() -> int:
    parser = ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--laps", type=int, default=3)
    parser.add_argument("--distance", type=float, default=150.0)
    parser.add_argument("--dwell", type=float, default=4.0, help="seconds to walk before turning")
    parser.add_argument("--axis", choices=("x", "y"), default="x")
    parser.add_argument(
        "--game", help="install folder or ini tree, to read the faction's starting roster from"
    )
    args = parser.parse_args()

    backend = attach()
    describe(backend)

    units = starter_units(backend, args.game)
    for unit in units:
        print(f"  {unit.object_id:>6}  {unit.template_name}")
    ids = {u.object_id for u in units}
    origin = centre_of(units)
    player = backend.observe().local_player

    # One order carries the whole selection - a Boolean plus one ObjectId per unit - so this is
    # also the widest order the command buffer ever sees.
    print(f"\nselecting {len(ids)} unit(s) in one order ({1 + len(ids)} arguments)")
    if not issue(backend, orders.select(player, sorted(ids)), "select"):
        return 1

    for lap in range(1, args.laps + 1):
        for direction, name in ((1, "out"), (-1, "back")):
            offset = direction * args.distance
            target = (
                (origin[0] + offset, origin[1], origin[2])
                if args.axis == "x"
                else (origin[0], origin[1] + offset, origin[2])
            )
            print(f"\nlap {lap} {name}: move to ({target[0]:.0f}, {target[1]:.0f})")
            if not issue(backend, orders.move(player, target), "move"):
                return 1
            deadline = time.monotonic() + args.dwell
            while time.monotonic() < deadline:
                report(backend, ids)
                time.sleep(1.0)

    print("\nstopping")
    issue(backend, orders.stop(player), "stop")
    report(backend, ids)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
