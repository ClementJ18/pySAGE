"""Pause and single-step a running game's simulation, with the script debugger's frame gate.

**This writes code into a running game** - one redirected `call` and a 256-byte cave - and takes
it out again on exit. Nothing touches `game.dat` on disk, and a network game is refused. If this
script is killed while the game is paused, the game resumes by itself within about fifteen
seconds (the gate's lease). Needs an elevated shell.

    python examples/sage_live/frame_gate.py --check   # the automated spike: pause, step, resume
    python examples/sage_live/frame_gate.py           # interactive: p, r, s [n], f, q

The check is `sage_patch/docs/script-debugger.md` §6.5: while held, the logic frame must not move
while the dispatcher keeps being called - which is the client (rendering, camera, input) still
running. What it cannot see is whether the screen *looks* alive; look at the game while it runs.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # repo root on path

from sage_live.backends.live_patch import LivePatchError, WindowsProcess  # noqa: E402
from sage_live.backends.memory import find_game_processes  # noqa: E402
from sage_live.backends.script_debugger import FrameGate  # noqa: E402
from sage_patch.addresses import (  # noqa: E402
    FRAME_DISPATCHER_PAUSE_CALL,
    FRAME_DISPATCHER_PAUSE_CALL_BYTES,
)


def check(gate: FrameGate, process: WindowsProcess) -> bool:
    ok = True

    def verdict(passed: bool, what: str) -> None:
        nonlocal ok
        ok &= passed
        print(f"  [{'ok' if passed else 'FAIL'}] {what}")

    start = gate.state()
    time.sleep(1.0)
    running = gate.state()
    print(f"attached at frame {start.frame}, cave 0x{gate.cave or 0:08X}")
    verdict(
        (running.frame or 0) > (start.frame or 0),
        f"running: frame {start.frame} -> {running.frame} in 1s (the game must not be paused)",
    )

    gate.pause()
    held_at = gate.wait_paused()
    before = gate.state()
    time.sleep(2.0)
    after = gate.state()
    verdict(after.frame == before.frame, f"paused: frame held at {after.frame} for 2s")
    verdict(
        after.hits - before.hits > 10,
        f"client alive while paused: dispatcher called {after.hits - before.hits} times in 2s",
    )

    stepped = gate.step(1)
    verdict(
        stepped == (held_at or 0) + 1,
        f"step 1: frame {held_at} -> {stepped}",
    )
    stepped10 = gate.step(10)
    verdict(stepped10 == (stepped or 0) + 10, f"step 10: frame {stepped} -> {stepped10}")
    time.sleep(0.5)
    verdict(gate.state().frame == stepped10, "still held after the step")

    gate.resume()
    time.sleep(1.0)
    resumed = gate.state()
    verdict(
        (resumed.frame or 0) > (stepped10 or 0),
        f"resumed: frame {stepped10} -> {resumed.frame} in 1s",
    )

    notes = gate.close()
    restored = process.read(FRAME_DISPATCHER_PAUSE_CALL, 5) == FRAME_DISPATCHER_PAUSE_CALL_BYTES
    verdict(restored and not notes, "detached: the dispatcher's call is stock again")
    for note in notes:
        print(f"    ! {note}")
    return ok


def interactive(gate: FrameGate) -> None:
    print("p pause | r resume | s [n] step n logic frames | f frame | q quit (resumes)")
    while True:
        try:
            line = input(f"[frame {gate.frame()}] > ").strip().split()
        except EOFError:
            return
        if not line:
            continue
        command, args = line[0], line[1:]
        if command == "q":
            return
        if command == "p":
            gate.pause()
            print(f"held at frame {gate.wait_paused()}")
        elif command == "r":
            gate.resume()
        elif command == "s":
            frames = int(args[0]) if args else 1
            print(f"stepped to frame {gate.step(frames, timeout=max(5.0, frames / 5 + 2))}")
        elif command == "f":
            state = gate.state()
            print(f"mode {state.mode}, frame {state.frame}, lease {state.lease}, hits {state.hits}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="run the automated spike and exit")
    args = parser.parse_args()

    pids = find_game_processes()
    if not pids:
        raise SystemExit("no game.dat process is running")
    process = WindowsProcess(pids[0])
    gate = FrameGate(process)
    try:
        gate.attach()
    except LivePatchError as exc:
        raise SystemExit(f"cannot attach: {exc}") from exc
    try:
        if args.check:
            ok = check(gate, process)
            print("\nspike passed" if ok else "\nspike FAILED")
            sys.exit(0 if ok else 1)
        interactive(gate)
    finally:
        for note in gate.close():
            print(f"! {note}")
        process.close()


if __name__ == "__main__":
    main()
