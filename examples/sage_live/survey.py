"""Read-only reconnaissance of a live match: everything a bot needs to know before it acts.

Run this once at the start of a match, before writing any policy against it. It answers the
four questions that decide whether a bot can play at all, and it answers them by *measuring*
rather than by assuming:

1. **Do the live and ini thing-id tables agree?** They are two different reconstructions of
   the same registration order and they do not have to match - the live walk reads ten more
   templates than the ini tree does. Only the ini rule is corpus-validated (491/491
   `FOUNDATION_CONSTRUCT` orders across 12 fixtures, `order_space_map.md` section A), so a
   disagreement means `LiveNames.thing` is the one that is wrong. This prints where the two
   diverge, because a divergence *after* every template in play is harmless and one *before*
   is fatal.

2. **Where are the build plots?** A castle plot is an object with no body, so it is invisible
   to any filter that looks for units. `build_at` needs its position.

3. **What does the local player actually own**, by template, so a build order can be written
   against real names rather than guessed ones.

4. **Where is the opponent?** There is no fog here, so this is simply readable.

Nothing is sent. This opens the process read-only, so it needs neither the live-bridge patch
nor a writable handle - only an elevated shell.

    python examples/sage_live/survey.py
    python examples/sage_live/survey.py --game "C:/Program Files (x86)/Games/bfme/rotwk"

`--game` is what enables the id cross-check and costs about a minute to load; without it the
rest of the survey still runs.
"""

from __future__ import annotations

import sys
from argparse import ArgumentParser
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # repo root on path

from sage_live.connect import AttachError, open_backend  # noqa: E402
from sage_live.memory import MemoryBackend  # noqa: E402
from sage_live.naming import LiveNames  # noqa: E402
from sage_live.observation import GameObject, Observation  # noqa: E402
from sage_live.statics import Statics  # noqa: E402

__all__ = ["main", "report_ids", "report_plots", "report_players"]

# How far from the fortress a bodyless object still counts as part of the base. Castle plots
# ring the fortress closely; map scenery does not. Generous rather than tight - this is a
# report, and a false positive here costs a line of output.
BASE_RADIUS = 900.0


def report_players(observation: Observation) -> None:
    """Every seat, so a policy knows which indices are real opponents.

    A match always carries seats the engine runs itself - `Civilian`, `Observer`, an unnamed
    neutral - and a bot that treats them as enemies attacks map scenery, so the `playing`
    column is the one that matters.
    """
    print(f"\nframe {observation.frame}, {len(observation.objects)} objects on the map")
    print(f"in_match: {observation.in_match}   local player: [{observation.local_player}]")
    print("\n  idx  playing  faction      resources   CP        spell  name")
    for player in observation.players:
        owned = len(observation.owned_by(player.index))
        used, cap = player.command_points
        mark = "*" if player.index == observation.local_player else " "
        print(
            f" {mark}[{player.index}] {str(player.playing):>7}  {player.faction:<12} "
            f"{player.resources:>9}   {used:>4}/{cap:<4} {player.power_points:>5}  "
            f"{player.name} ({owned} objects)"
        )


def _centre(objects: list[GameObject]) -> tuple[float, float, float]:
    return (
        sum(o.position[0] for o in objects) / len(objects),
        sum(o.position[1] for o in objects) / len(objects),
        sum(o.position[2] for o in objects) / len(objects),
    )


def report_plots(observation: Observation, statics: Statics | None) -> None:
    """The local player's build plots, with the positions `build_at` needs as its argument.

    A plot is identified by its template's `KindOf` carrying `BASE_FOUNDATION` or `BASE_SITE`,
    which needs `--game`. Nothing on the live object says "plot": the first version of this
    looked for objects with no body, and found none, because a plot has an `ImmortalBody` of
    15,000. Template names do not work either - `GondorBuildingFoundation` looks like a
    convention until `MordorFortressExpansionPadCorner` turns up.
    """
    mine = list(observation.mine)
    if not mine:
        print("\nno owned objects - is a match actually running?")
        return

    bodied = [o for o in mine if o.has_body]
    anchor = _centre(bodied) if bodied else _centre(mine)
    print(f"\nowned: {len(bodied)} with a body, {len(mine) - len(bodied)} without")
    print(f"base centre (mean of bodied objects): {anchor[0]:.0f}, {anchor[1]:.0f}")

    if statics is None:
        print("\n  build plots: pass --game to classify them (needs KindOf from the ini tree)")
        return

    plots = [o for o in mine if statics.is_build_site(o.template_name)]
    near = [o for o in plots if o.distance_to(anchor) <= BASE_RADIUS]
    print(f"\n  build plots (BASE_FOUNDATION / BASE_SITE), {len(near)} near the base:")
    if not plots:
        print("    none owned - this faction may build from a mobile builder (DOZER_CONSTRUCT)")
    for obj in sorted(near, key=lambda o: o.distance_to(anchor)):
        x, y, z = obj.position
        print(
            f"    [{obj.object_id:>6}] {obj.template_name:<44} "
            f"({x:8.1f},{y:8.1f},{z:7.1f})  {obj.distance_to(anchor):6.0f} away"
        )
    if len(plots) > len(near):
        print(f"    ({len(plots) - len(near)} more beyond {BASE_RADIUS:.0f}, likely an expansion)")


def report_army(observation: Observation) -> None:
    """What the local player owns, by template - the vocabulary a build order is written in."""
    print("\n  owned templates:")
    for name, count in observation.census(observation.mine).most_common():
        print(f"    {count:>4}  {name}")


def report_enemies(observation: Observation) -> None:
    """Opponent holdings and where they are. No fog applies, so this is simply readable."""
    for player in observation.opponents:
        owned = list(observation.owned_by(player.index))
        if not owned:
            print(f"\n  [{player.index}] {player.name} ({player.faction}): nothing owned")
            continue
        centre = _centre(owned)
        print(
            f"\n  [{player.index}] {player.name} ({player.faction}): {len(owned)} objects, "
            f"centred on ({centre[0]:.0f}, {centre[1]:.0f})"
        )
        for name, count in Counter(o.template_name for o in owned).most_common(8):
            print(f"      {count:>4}  {name}")


def report_ids(backend: MemoryBackend, observation: Observation, resolver: object | None) -> None:
    """Cross-check the live thing table against the ini one, on the templates actually in play.

    The two tables are independent reconstructions of the engine's registration order and they
    disagree in size, so at most one is right. The ini rule is the corpus-validated one, which
    makes this a check on `LiveNames` - and specifically on *where* it first goes wrong, since
    a divergence past the last template in play cannot affect a match.
    """
    live = LiveNames(backend)
    try:
        live_names = live.source.thing_order()
    except (OSError, ValueError) as exc:  # a walk that could not complete says so, not raises
        print(f"\nlive thing table unreadable: {exc}")
        return
    print(f"\nlive thing table: {len(live_names)} templates")

    if resolver is None:
        print("  (pass --game to compare it against the ini tree)")
        return
    ini_names = resolver.game.object_order  # type: ignore[attr-defined]
    print(f"ini thing table:  {len(ini_names)} templates")

    first_divergence = next(
        (
            i
            for i in range(min(len(live_names), len(ini_names)))
            if live_names[i].lower() != ini_names[i].lower()
        ),
        None,
    )
    if first_divergence is None:
        print("  the two tables agree over their common length")
    else:
        print(f"  first divergence at index {first_divergence}:")
        print(f"    live: {live_names[first_divergence]}")
        print(f"    ini:  {ini_names[first_divergence]}")

    print("\n  templates in play, live id vs ini id:")
    disagreements = 0
    for name in sorted(observation.census().keys()):
        try:
            live_id: int | str = live.thing(name)
        except KeyError:
            live_id = "-"
        try:
            ini_id: int | str = resolver.thing(name)  # type: ignore[attr-defined]
        except KeyError:
            ini_id = "-"
        flag = "  <-- DISAGREE" if live_id != ini_id else ""
        if flag:
            disagreements += 1
        print(f"    {name:<44} live {live_id:>7}   ini {ini_id:>7}{flag}")
    print(f"\n  {disagreements} of {len(observation.census())} templates disagree")
    if disagreements:
        print("  -> use Resolver (ini) ids for recruit and build; the ini rule is the")
        print("     corpus-validated one (order_space_map.md section A).")


def main(argv: list[str] | None = None) -> int:
    parser = ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--game", help="install folder or ini tree, to cross-check thing ids")
    parser.add_argument("--pid", type=int, help="which game.dat, when several are running")
    args = parser.parse_args(argv)

    try:
        backend = open_backend(args.pid)
    except AttachError as exc:
        raise SystemExit(str(exc)) from exc

    try:
        observation = backend.observe()
        report_players(observation)
        if not observation.in_match:
            print("\nthis is the menu's shell map, not a match - start a skirmish first")
            return 1

        statics: Statics | None = None
        resolver: object | None = None
        if args.game is not None:
            # Both loaders want an ini tree, and a live install keeps its data in `.big`
            # archives - so mount first. The mount is cached under the temp directory, and
            # loading once here means the two reports below do not each pay for it. Imported
            # at point of use: these pull in `sage_ini`, which the rest of the survey does not
            # need.
            from sage_live.resolve import Resolver  # noqa: PLC0415
            from sage_utils.gameroot import resolve_game_root  # noqa: PLC0415

            root = resolve_game_root(args.game)
            print(f"\nloading {root} (about a minute) ...")
            statics = Statics.from_root(root)
            resolver = Resolver.from_root(root)

        report_plots(observation, statics)
        report_army(observation)
        report_enemies(observation)
        report_ids(backend, observation, resolver)
    finally:
        backend.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
