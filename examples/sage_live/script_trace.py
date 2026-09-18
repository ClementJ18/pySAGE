"""Trace which scripts a running game fires, frame by frame - or break when one of them does.

**This writes code into a running game** - five redirected `call`s and a 256 KB cave, plus the
frame gate for `--break` - and takes it out again on exit. The game behaves exactly as before
while only recording. Nothing touches `game.dat` on disk, and a network game is refused. Needs an
elevated shell.

    python examples/sage_live/script_trace.py              # ten seconds, every event
    python examples/sage_live/script_trace.py --seconds 30 --summary
    python examples/sage_live/script_trace.py --break "Win Condition"

`--break` is the breakpoint spike (`sage_patch/docs/script-debugger.md` slice D): it waits for the
named script to fire, checks the game then holds on that frame for three seconds, and resumes.

Each line names the script through the live script tree, so it reads the same as the Scripts
panel; a script the tree does not know (one created after the trace started) prints its address.
"""

from __future__ import annotations

import argparse
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # repo root on path

from sage_live.backends.live_patch import LivePatchError, WindowsProcess  # noqa: E402
from sage_live.backends.memory import find_game_processes  # noqa: E402
from sage_live.backends.script_debugger import FrameGate  # noqa: E402
from sage_live.backends.script_trace import EventKind, ScriptTrace, kind_mask  # noqa: E402
from sage_live.backends.scripts import read_script_tree  # noqa: E402

KIND = {
    EventKind.TRUE_ACTIONS: "true",
    EventKind.FALSE_ACTIONS: "false",
    EventKind.SEQUENTIAL: "sequential",
}


def trace(process: WindowsProcess, names: dict[int, str], seconds: float, summary: bool) -> None:
    recorder = ScriptTrace(process)
    try:
        recorder.attach()
    except LivePatchError as exc:
        raise SystemExit(f"cannot attach: {exc}") from exc
    counts: Counter[str] = Counter()
    try:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            time.sleep(0.25)
            for event in recorder.read():
                name = names.get(event.script, f"0x{event.script:08X}")
                counts[f"{name} ({KIND[event.kind]})"] += 1
                if not summary:
                    member = f"  for object {event.object_id}" if event.object_id else ""
                    print(f"f{event.frame:<7} {KIND[event.kind]:<10} {name}{member}")
    finally:
        notes = recorder.close()
    if summary:
        for name, count in counts.most_common():
            print(f"{count:>6}  {name}")
    print(f"\n{sum(counts.values())} events, {recorder.dropped} dropped")
    for note in notes:
        print(f"! {note}")


def break_on(process: WindowsProcess, names: dict[int, str], target: str, seconds: float) -> bool:
    addresses = {
        address: kind_mask([EventKind.TRUE_ACTIONS, EventKind.SEQUENTIAL])
        for address, name in names.items()
        if name.split(":", 1)[1].casefold() == target.casefold()
    }
    if not addresses:
        raise SystemExit(f"no live script is called {target!r}")
    print(
        f"breaking on {len(addresses)} live cop{'y' if len(addresses) == 1 else 'ies'} of {target}"
    )
    gate, recorder = FrameGate(process), ScriptTrace(process)
    try:
        gate.attach()
        recorder.attach(recording=False)
        recorder.set_gate(gate.mode_address)
        recorder.set_breakpoints(addresses)
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline and recorder.hit() is None:
            time.sleep(0.1)
        hit = recorder.hit()
        if hit is None:
            print(f"{target} did not fire within {seconds:g} s")
            return False
        print(f"hit: {names.get(hit.script, hex(hit.script))} fired at frame {hit.frame}")
        held = gate.wait_paused(2.0)
        time.sleep(3.0)
        still = gate.frame()
        ok = held is not None and still == held
        print(f"  [{'ok' if ok else 'FAIL'}] held at frame {held}, still {still} after 3 s")
        boundary = held is not None and held - hit.frame <= 1
        verdict = "ok" if boundary else "FAIL"
        print(f"  [{verdict}] held on the frame boundary right after the hit")
        return ok and boundary
    except LivePatchError as exc:
        raise SystemExit(f"cannot attach: {exc}") from exc
    finally:
        for note in recorder.close() + gate.close():
            print(f"! {note}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--seconds", type=float, default=10.0)
    parser.add_argument("--summary", action="store_true", help="counts per script, not lines")
    parser.add_argument("--break", dest="target", metavar="SCRIPT", help="break when it fires")
    args = parser.parse_args()

    pids = find_game_processes()
    if not pids:
        raise SystemExit("no game.dat process is running")
    process = WindowsProcess(pids[0])
    try:
        tree = read_script_tree(process.read)
        if tree is None:
            raise SystemExit("no map is loaded")
        names = {
            script.address: f"{side.index}:{script.name}"
            for side in tree.sides
            for script in side.all_scripts()
        }
        if args.target:
            seconds = args.seconds if args.seconds != 10.0 else 60.0
            sys.exit(0 if break_on(process, names, args.target, seconds) else 1)
        trace(process, names, args.seconds, args.summary)
    finally:
        process.close()


if __name__ == "__main__":
    main()
