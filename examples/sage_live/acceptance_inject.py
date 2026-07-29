"""Acceptance test, part 1: inject a scripted opening and record exactly what was sent.

The claim the live-bridge patch rests on is that an injected order goes through the engine's
*own* input path - network-ordered and check-summed like a mouse click - rather than being
poked into game logic. That is testable: if it is true, the engine writes injected orders into
the replay it records, and `acceptance_verify.py` finds them there.

**Skirmish mode does not record replays.** Use a one-player *online* game.

    python examples/sage_live/acceptance_inject.py
    ...end the game so the replay is flushed...
    python examples/sage_live/acceptance_verify.py

Keep your hands off the mouse while this runs, so every order in the window is one of these.
"""

import json
import sys
import time
from argparse import ArgumentParser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # repo root on path

from _common import attach, describe, my_units  # noqa: E402

from sage_live import orders  # noqa: E402

DEFAULT_LOG = Path("acceptance_log.json")

# A distinctive offset: exact in float32, and an unlikely thing to produce by clicking.
DX, DY = 137.25, 42.5


def main() -> int:
    parser = ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--log", type=Path, default=DEFAULT_LOG, help="where to record what was sent"
    )
    args = parser.parse_args()

    backend = attach()
    describe(backend)

    observation = backend.observe()
    player = observation.local_player
    unit = my_units(backend)[0]
    print(f"subject: object {unit.object_id} {unit.template_name} at {unit.position}")
    destination = (unit.position[0] + DX, unit.position[1] + DY, unit.position[2])

    # A shape that is easy to find in a replay and hard to produce by accident: a bare stop as
    # an opening marker, the select/move pair under test, then a closing stop.
    script = [
        ("stop-open", orders.stop(player)),
        ("select", orders.select(player, [unit.object_id])),
        ("move", orders.move(player, destination)),
        ("stop-close", orders.stop(player)),
    ]

    sent = []
    for label, order in script:
        before = backend.observe().frame
        if backend.send([order]) != 1 or not backend.wait_until_idle():
            print(f"  {label}: not accepted")
            for diagnostic in backend.diagnostics:
                print(f"    ! {diagnostic}")
            return 1
        after = backend.observe().frame
        print(f"  {label:<11} type {order.order_type:#06x}  frame {before} -> {after}")
        sent.append(
            {
                "label": label,
                "player_index": order.player_index,
                "order_type": int(order.order_type),
                "arguments": [
                    {"argument_type": int(a.argument_type), "value": a.value}
                    for a in order.arguments
                ],
                "frame_before": before,
                "frame_after": after,
            }
        )
        time.sleep(0.4)  # keep them on separate frames, so replay order is unambiguous

    args.log.write_text(
        json.dumps(
            {
                "local_player_index": player,
                "subject_object_id": unit.object_id,
                "subject_template": unit.template_name,
                "subject_position": list(unit.position),
                "destination": list(destination),
                "orders": sent,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\nwrote {args.log}")
    print("Now END THE GAME so the replay is flushed, then run acceptance_verify.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
