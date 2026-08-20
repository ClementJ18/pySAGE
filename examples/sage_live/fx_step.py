"""How fast does `ParticleSystemManager` actually step, against the client frame?

`[TheParticleSystemManager+0x74]` is the stamp the update gate compares. Stock writes the raw
client frame there, so particle systems take one step per client frame and every effect in the
game runs at the frame rate - `render-rate.md` §9.4, and the last defect that was really the
render-rate patch's own. The cave that section installs writes ``clientFrame * 30 / clientRate``
instead, a tick that advances 30 times a second whatever the client rate is.

So the ratio of the stamp's rate to the client frame's rate is the whole measurement:

    1.000  the defect - one step per client frame
    0.500  the cave, at client rate 60
    1.000  the cave, at client rate 30 (it is an identity there, by design)

Read-only; needs a running match with something on screen, though the stamp advances whether or
not any particle system exists.

    python examples/sage_live/fx_step.py
    python examples/sage_live/fx_step.py --seconds 10
"""

from __future__ import annotations

import argparse
import struct
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # repo root on path

from sage_live.backends.memory import ProcessMemory, find_game_processes  # noqa: E402

#: The manager and its step stamp (§9.4). One read and one write in the whole image, which is
#: what makes the stamp safe for the cave to redefine - and what makes it honest to measure.
PARTICLE_MANAGER = 0x00DE3744
STAMP = 0x74

#: `TheGameClient` and its frame counter, the thing the stamp is being compared against.
GAME_CLIENT = 0x00DE4388
CLIENT_FRAME = 0x10

#: The client rate the binary was built with, and the rate the content was authored at.
CLIENT_RATE = 0x00D9F60C
AUTHORED_RATE = 30


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=float, default=4.0, help="sampling window")
    args = parser.parse_args()

    pids = find_game_processes()
    if not pids:
        raise SystemExit("no game.dat running - start a match first")
    try:
        memory = ProcessMemory(pids[0])
    except PermissionError as exc:
        raise SystemExit(f"{exc}\nrun this from an elevated shell") from exc

    def u32(address: int) -> int:
        raw = memory.read(address, 4)
        if not raw:
            raise SystemExit(f"could not read 0x{address:08X}")
        return int(struct.unpack("<I", raw)[0])

    rate_raw = memory.read(CLIENT_RATE, 4)
    rate = struct.unpack("<i", rate_raw)[0] if rate_raw else AUTHORED_RATE
    manager, client = u32(PARTICLE_MANAGER), u32(GAME_CLIENT)
    if not manager or not client:
        raise SystemExit("the manager or the client is null - attach once a match is running")
    print(f"pid {pids[0]}  TheParticleSystemManager 0x{manager:08X}  client rate {rate}")

    first_frame, first_stamp = u32(client + CLIENT_FRAME), u32(manager + STAMP)
    started = time.perf_counter()
    while time.perf_counter() - started < args.seconds:
        u32(client + CLIENT_FRAME)  # sample continuously so nothing is missed between reads
        u32(manager + STAMP)
    elapsed = time.perf_counter() - started
    frames = u32(client + CLIENT_FRAME) - first_frame
    steps = u32(manager + STAMP) - first_stamp
    memory.close()

    print(f"  over {elapsed:.2f}s:  client frames +{frames} ({frames / elapsed:.1f} Hz)")
    print(f"{'':21}particle steps +{steps} ({steps / elapsed:.1f} Hz)")
    if not frames:
        print("\n  the client frame did not move - is the game paused?")
        return
    expected = AUTHORED_RATE / rate
    print(f"\n  steps per client frame = {steps / frames:.3f}")
    print(f"    1.000 = the §9.4 defect;  {expected:.3f} = the cave working at rate {rate}")


if __name__ == "__main__":
    main()
