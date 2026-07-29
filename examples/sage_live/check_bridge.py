"""Check that a patched game really is accepting injected orders, one stage at a time.

Run this first when the bridge is not behaving, or after patching a build for the first time.
The stages are ordered by how much machinery they exercise, so the first one that fails tells
you where the problem is:

    stage 0   attach only     no writes; proves the read path and that `.livebrg` is present
    stage 1   stop            0 arguments; proves the hook actually runs each logic frame
    stage 2   select          Boolean + ObjectId, passed by *value*
    stage 3   move            Position, passed by *pointer* into the command buffer

A `ready` flag that never clears is the signature failure: the patch installed and verified,
but the hook is not being called. That is what a wrong hook site looks like from outside.

Run from the repo root, in an elevated shell, with a match running:

    python examples/sage_live/check_bridge.py          # every stage in order
    python examples/sage_live/check_bridge.py --stage 2
    python examples/sage_live/check_bridge.py --ids 132,133
"""

import sys
import time
from argparse import ArgumentParser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # repo root on path

from _common import attach, describe, issue, my_units  # noqa: E402

from sage_live import orders  # noqa: E402
from sage_live.bridge import BridgeBackend  # noqa: E402


def stage_0(backend: BridgeBackend, player: int, ids: list[int]) -> bool:
    print("  section present, buffer readable, nothing written")
    return not backend.pending


def stage_1(backend: BridgeBackend, player: int, ids: list[int]) -> bool:
    return issue(backend, orders.stop(player), "stop")


def stage_2(backend: BridgeBackend, player: int, ids: list[int]) -> bool:
    ok = issue(backend, orders.select(player, ids), "select")
    if ok:
        print("  check the game window: are those units selected?")
    return ok


def stage_3(backend: BridgeBackend, player: int, ids: list[int]) -> bool:
    tracked = next((o for o in backend.observe().objects if o.object_id == ids[0]), None)
    if tracked is None:
        print(f"  object {ids[0]} is gone")
        return False
    start = tracked.position
    target = (start[0] + 200.0, start[1], start[2])
    print(
        f"  moving the selection from ({start[0]:.0f}, {start[1]:.0f}) toward "
        f"({target[0]:.0f}, {target[1]:.0f})"
    )
    if not issue(backend, orders.move(player, target), "move"):
        return False

    # Sample until it stops, not at a fixed delay: a mid-path sample can sit well off-axis
    # while the unit paths around terrain, which reads like a misdecoded Position.
    previous = start
    for _ in range(12):
        time.sleep(1.0)
        now = next((o for o in backend.observe().objects if o.object_id == ids[0]), None)
        if now is None:
            print("  the tracked object is gone")
            return False
        if now.position == previous and now.position != start:
            break
        previous = now.position
    travelled = ((previous[0] - start[0]) ** 2 + (previous[1] - start[1]) ** 2) ** 0.5
    print(f"  settled at ({previous[0]:.0f}, {previous[1]:.0f}) after {travelled:.0f} units")
    if travelled <= 1.0:
        print("  it did not move - was anything selected? (run stage 2 first)")
        return False
    return True


STAGES = {0: stage_0, 1: stage_1, 2: stage_2, 3: stage_3}


def main() -> int:
    parser = ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--stage", type=int, choices=sorted(STAGES), help="just this one")
    parser.add_argument("--ids", help="comma-separated object ids to use (default: pick some)")
    args = parser.parse_args()

    backend = attach()
    describe(backend)
    if backend.pending:
        print("! an order is already pending and unconsumed - the game may be paused")

    player = backend.observe().local_player
    if args.ids:
        ids = [int(part) for part in args.ids.split(",")]
    else:
        ids = [unit.object_id for unit in my_units(backend)[:1]]
        print(f"using object {ids[0]}")

    wanted = [args.stage] if args.stage is not None else sorted(STAGES)
    failed = []
    for number in wanted:
        print(f"\n--- stage {number} ---")
        if STAGES[number](backend, player, ids):
            print(f"  stage {number} PASS")
        else:
            print(f"  stage {number} FAIL")
            failed.append(number)
            break  # a later stage assumes the earlier ones worked

    print("\nall stages passed" if not failed else f"\nstopped at stage {failed[0]}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
