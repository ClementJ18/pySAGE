"""Read the running game's map scripts, and check them against the `.map` they came from.

The script debugger's first spike (`sage_patch/docs/script-debugger.md` §6.1): walk every side's
live script tree and confirm the `Script` layout by matching each script's flags against the file.
Read-only - it opens the process for reading and writes nothing, so it is safe against any game.
It needs an elevated shell, because `game.dat` runs as administrator.

    python examples/sage_live/script_tree.py                        # the tree, and what has fired
    python examples/sage_live/script_tree.py --map "path/to/x.map"  # plus the cross-check
    python examples/sage_live/script_tree.py --vars                 # counters, timers, flags
    python examples/sage_live/script_tree.py --watch 30             # changes, for 30 seconds

A skirmish does not run the map's sides as authored: the engine synthesises one side per slot and
merges each AI's library scripts into it, so the cross-check matches scripts **by name** across
the whole map and reports what exists on only one side of the comparison.
"""

from __future__ import annotations

import argparse
import struct
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # repo root on path

from sage_live.backends.memory import (  # noqa: E402
    MemoryBackend,
    ProcessMemory,
    find_game_processes,
)
from sage_live.backends.scripts import (  # noqa: E402
    LiveScript,
    LiveScriptGroup,
    ScriptTree,
    read_script_tree,
    read_script_variables,
)
from sage_map.assets.player_scripts import Script, ScriptGroup  # noqa: E402
from sage_map.map import parse_map_from_path  # noqa: E402
from sage_patch.addresses import GAME_INFO_MAP, THE_GAME_INFO, THE_SKIRMISH_GAME_INFO  # noqa: E402

DIFFICULTY = {0: "easy", 1: "normal", 2: "hard", 3: "brutal"}


def flags(script: LiveScript) -> str:
    marks = [
        "on" if script.active else "off",
        "1x" if script.one_shot else "",
        "sub" if script.subroutine else "",
        "seq" if script.sequential else "",
        "" if (script.easy and script.normal and script.hard) else _levels(script),
    ]
    if script.active != script.authored_active:
        marks.append("FIRED" if script.one_shot and not script.active else "toggled")
    return " ".join(mark for mark in marks if mark)


def _levels(script: LiveScript) -> str:
    on = [
        name
        for name, set_ in (("E", script.easy), ("N", script.normal), ("H", script.hard))
        if set_
    ]
    return "only " + "".join(on) if on else "no difficulty"


def print_group(group: LiveScriptGroup, frame: int, depth: int) -> None:
    pad = "  " * depth
    state = ("on" if group.active else "OFF") + (" sub" if group.subroutine else "")
    print(f"{pad}[{group.name}] {state}")
    for script in group.scripts:
        print_script(script, frame, depth + 1)
    for child in group.groups:
        print_group(child, frame, depth + 1)


def print_script(script: LiveScript, frame: int, depth: int) -> None:
    due = script.next_frame - frame
    when = f"next in {due}f" if due > 0 else ""
    delay = f"every {script.delay_seconds}s" if script.delay_seconds else ""
    print(f"{'  ' * depth}{script.name:<48} {flags(script):<24} {delay:<10} {when}")


def print_tree(tree: ScriptTree, names: dict[int, str], frame: int) -> None:
    difficulty = DIFFICULTY.get(tree.difficulty or 0, str(tree.difficulty))
    print(f"frame {frame}, script difficulty {difficulty}")
    for side in tree.sides:
        count = len(side.all_scripts())
        if not count:
            continue
        print(f"\nside {side.index} {names.get(side.index, '?')} - {count} scripts")
        for script in side.scripts:
            print_script(script, frame, 1)
        for group in side.groups:
            print_group(group, frame, 1)


def map_scripts(path: Path) -> dict[str, Script]:
    parsed = parse_map_from_path(path)
    out: dict[str, Script] = {}
    if parsed.player_scripts_list is None:
        return out
    stack: list[Script | ScriptGroup] = []
    for script_list in parsed.player_scripts_list.script_lists:
        stack.extend(script_list.items)
    while stack:
        item = stack.pop()
        if isinstance(item, ScriptGroup):
            stack.extend(item.items)
        else:
            out.setdefault(item.name, item)
    return out


def cross_check(tree: ScriptTree, path: Path) -> int:
    """Compare every live script's authored fields against the file. Returns the mismatch count."""
    authored = map_scripts(path)
    live = {script.name: script for side in tree.sides for script in side.all_scripts()}
    mismatches = 0
    for name, script in sorted(live.items()):
        source = authored.get(name)
        if source is None:
            continue
        expected = {
            "active": source.is_active,
            "one_shot": source.deactivate_upon_success,
            "subroutine": source.is_subroutine,
            "easy": source.active_in_easy,
            "normal": source.active_in_medium,
            "hard": source.active_in_hard,
            "delay_seconds": source.evaluation_interval or 0,
            "sequential": bool(source.actions_fire_sequentially),
        }
        got = {
            "active": script.authored_active,
            "one_shot": script.one_shot,
            "subroutine": script.subroutine,
            "easy": script.easy,
            "normal": script.normal,
            "hard": script.hard,
            "delay_seconds": script.delay_seconds,
            "sequential": script.sequential,
        }
        wrong = {k: (expected[k], got[k]) for k in expected if expected[k] != got[k]}
        if wrong:
            mismatches += 1
            detail = ", ".join(f"{k}: map {e} live {g}" for k, (e, g) in wrong.items())
            print(f"  MISMATCH {name}: {detail}")
    matched = len(set(live) & set(authored))
    only_live = sorted(set(live) - set(authored))
    only_map = sorted(set(authored) - set(live))
    print(f"\ncross-check against {path.name}: {matched} matched, {mismatches} mismatched")
    print(f"  live only (AI libraries, synthesised sides): {len(only_live)}")
    for name in only_live[:20]:
        print(f"    {name}")
    print(f"  map only (sides the engine did not keep): {len(only_map)}")
    for name in only_map[:20]:
        print(f"    {name}")
    return mismatches


def running_map(source: ProcessMemory) -> str:
    """`GameInfo::m_map`, from whichever of the two game-info globals is set."""

    def u32(address: int) -> int:
        raw = source.read(address, 4)
        return struct.unpack("<I", raw)[0] if raw else 0

    for global_ in (THE_GAME_INFO, THE_SKIRMISH_GAME_INFO):
        info = u32(global_)
        block = u32(info + GAME_INFO_MAP) if info else 0
        raw = source.read(block + 8, 256) if block else None
        if raw:
            return raw.split(b"\x00")[0].decode("latin-1", errors="replace")
    return "?"


def watch(backend: MemoryBackend, source: ProcessMemory, seconds: float) -> None:
    """Print each script whose live state changes: fired one-shots, toggles, evaluations."""
    before = read_script_tree(source.read)
    if before is None:
        raise SystemExit("no script tree - is a map loaded?")
    last = {(s.index, x.name): x for s in before.sides for x in s.all_scripts()}
    last_frame = backend.frame()
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        time.sleep(0.2)
        tree = read_script_tree(source.read)
        if tree is None:
            print("script tree gone - the map was unloaded")
            return
        frame = backend.frame()
        for side in tree.sides:
            for script in side.all_scripts():
                old = last.get((side.index, script.name))
                last[(side.index, script.name)] = script
                if old is None:
                    continue
                if old.active != script.active:
                    state = "activated" if script.active else "deactivated"
                    print(f"f{frame} side {side.index} {script.name}: {state}")
                elif old.next_frame != script.next_frame and script.delay_seconds:
                    # `runScript` reschedules before the conditions are tested, so this is an
                    # evaluation, not a firing; a firing only shows when it toggles `active`.
                    print(
                        f"f{frame} side {side.index} {script.name}: evaluated"
                        f" (next f{script.next_frame})"
                    )
        if frame < last_frame:
            print("frame counter went backwards - a new map loaded")
        last_frame = frame


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--map", type=Path, help="the .map to cross-check the live tree against")
    parser.add_argument("--vars", action="store_true", help="also list counters, timers, flags")
    parser.add_argument("--watch", type=float, metavar="SECONDS", help="print changes over time")
    args = parser.parse_args()

    pids = find_game_processes()
    if not pids:
        raise SystemExit("no game.dat process is running")
    source = ProcessMemory(pids[0])
    backend = MemoryBackend(source, read_production=False)
    backend.connect()

    tree = read_script_tree(source.read)
    if tree is None:
        raise SystemExit("no script tree - still at the menu?")
    names = {player.index: player.name for player in backend.read_players()}
    print(f"map {running_map(source)}")
    print_tree(tree, names, backend.frame())

    if args.vars:
        print("\nvariables")
        for variable in read_script_variables(source.read):
            unit = " (authored in seconds)" if variable.seconds else ""
            print(f"  {variable.kind:<7} {variable.key:<48} {variable.value}{unit}")

    if args.map:
        cross_check(tree, args.map)

    if args.watch:
        print(f"\nwatching for {args.watch:g}s")
        watch(backend, source, args.watch)


if __name__ == "__main__":
    main()
