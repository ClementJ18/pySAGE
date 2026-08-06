"""Keep the camera on wherever the fighting is, so a bot's match can be filmed unattended.

The camera half of the live bridge, doing the job it exists for. Each cycle this reads the
whole board, decides where the action is, and eases the camera toward it - no orders are sent
and nothing about the match is touched, so it is safe to run alongside a policy that is
actually playing, or over a game a human is playing.

**Where the action is** is the densest cluster of units owned by two different players, which
is a fight; a lone army marching is second best, and the player's own base is the fallback
when nothing is happening. Nothing here is clever, and that is the point - it is a starting
policy to replace, not a finished director.

**The easing is this script's**, because `setLocation` is a jump and the engine interpolates
nothing. The camera walks a fraction of the remaining distance each cycle, which is what turns
a sequence of placements into a shot.

Run from the repo root, in an elevated shell, against a patched game:

    python examples/sage_live/follow_action.py
    python examples/sage_live/follow_action.py --zoom 0.6 --seconds 300
    python examples/sage_live/follow_action.py --ease 1.0      # cut instead of pan
"""

import sys
import time
from argparse import ArgumentParser
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # repo root on path

from _common import attach, describe  # noqa: E402

from sage_live.api.observation import GameObject, Observation, Vec3, distance  # noqa: E402

# How far apart two units can be and still count as being in the same fight. About the width
# of a battle line rather than of a base, so two armies meeting read as one cluster and two
# bases minding their own business do not.
CLUSTER_RADIUS = 220.0


def interesting(observation: Observation) -> list[GameObject]:
    """Units worth pointing a camera at: mobile, owned, and not a battalion's members.

    `orderable` is the container-level view of the board - a battalion is one object there
    rather than fifteen, so a single horde cannot outvote a real fight simply by having more
    bodies in it.
    """
    return [
        o
        for player in {o.owner_index for o in observation.objects if o.owner_index is not None}
        for o in observation.orderable(player)
    ]


def hotspot(observation: Observation, home: Vec3 | None) -> tuple[Vec3, str]:
    """Where to look, and why - so the run prints what it is doing rather than just moving.

    Scores every unit by the crowd around it, doubling the score where that crowd contains
    more than one player: two armies in one place is the shot, one army walking is not.
    """
    units = interesting(observation)
    if not units:
        return (home or (0.0, 0.0, 0.0)), "nothing owned"

    best: tuple[float, Vec3, int, bool] | None = None
    for unit in units:
        near = [o for o in units if distance(o.position, unit.position) < CLUSTER_RADIUS]
        owners = {o.owner_index for o in near}
        contested = len(owners) > 1
        score = len(near) * (2.0 if contested else 1.0)
        if best is None or score > best[0]:
            centre = (
                sum(o.position[0] for o in near) / len(near),
                sum(o.position[1] for o in near) / len(near),
                sum(o.position[2] for o in near) / len(near),
            )
            best = (score, centre, len(near), contested)

    if best is None:  # unreachable while `units` is non-empty, but do not place a camera on a guess
        return (home or (0.0, 0.0, 0.0)), "no cluster"
    _, centre, size, contested = best
    return centre, f"{size} units, {'contested' if contested else 'one player'}"


def ease(here: Vec3, there: Vec3, fraction: float) -> Vec3:
    """A step from `here` toward `there`. `fraction` of 1.0 is a cut."""
    return tuple(a + (b - a) * fraction for a, b in zip(here, there, strict=True))  # type: ignore[return-value]


def main() -> int:
    parser = ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--seconds", type=float, default=120.0, help="how long to keep filming")
    parser.add_argument("--interval", type=float, default=0.5, help="seconds between placements")
    parser.add_argument("--ease", type=float, default=0.25, help="0 holds still, 1 cuts")
    parser.add_argument("--zoom", type=float, help="override the zoom; default keeps the game's")
    args = parser.parse_args()

    backend = attach()
    describe(backend)

    start = backend.capture_camera()
    if start is None:
        # Not a failure worth a traceback: at a loading screen the client has no view yet.
        print("the camera could not be read - is a match actually running?")
        return 1
    print(f"camera at ({start.position[0]:.0f},{start.position[1]:.0f}) zoom {start.zoom:.2f}")

    observation = backend.observe()
    mine = observation.owned_by(observation.local_player)
    home = mine[0].position if mine else None

    deadline = time.monotonic() + args.seconds
    said = ""
    while time.monotonic() < deadline:
        target, why = hotspot(backend.observe(), home)
        # Re-read every cycle rather than tracking it here: a human at the keyboard may have
        # rotated or zoomed since the last placement, and this should pan from where the camera
        # actually is, not from where this script last put it.
        current = backend.capture_camera()
        if current is None:
            print("lost the camera - the match may have ended")
            return 1
        stepped = ease(current.position, target, args.ease)
        zoom = current.zoom if args.zoom is None else args.zoom
        if not backend.set_camera(replace(current, position=stepped, zoom=zoom)):
            print("the camera command was not served:")
            for diagnostic in backend.diagnostics.drain():
                print(f"  ! {diagnostic}")
            return 1
        if why != said:
            print(f"  looking at ({target[0]:.0f},{target[1]:.0f}) - {why}")
            said = why
        time.sleep(args.interval)

    print("done; putting the camera back")
    backend.set_camera(start)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
