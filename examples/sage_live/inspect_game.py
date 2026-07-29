"""A read-only tour of the live interface: attach, and describe what is in the game.

Needs no patch and writes nothing - `attach()` opens the process read-only. It does need an
elevated shell, because `game.dat` runs as administrator.

    python examples/sage_live/inspect_game.py
    python examples/sage_live/inspect_game.py --wait     # sit at the menu until a match starts

This is the script to run first: it exercises every part of the observation surface a policy
will use, so if something here reads wrong, the layout is wrong for this build and nothing
built on top of it can be trusted.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # repo root on path

import sage_live  # noqa: E402
from sage_live import AttachError, Observation  # noqa: E402


def describe_players(observation: Observation) -> None:
    print(f"\nplayers ({len(observation.players)}, {len(observation.opponents)} contesting)")
    for player in observation.players:
        role = "you" if player.index == observation.local_player else ""
        if not player.playing:
            role = role or "engine"
        used, cap = player.command_points
        print(
            f"  [{player.index}] {player.name:<16} {player.faction:<10} {role:<7}"
            f" gold {player.resources:>6}  spent {player.spent:>6}"
            f"  army {used:>4}/{cap:<4}  spellbook {player.power_points}"
        )
        if player.upgrades:
            print(f"        researched: {', '.join(sorted(player.upgrades))}")
        if player.upgrades_in_progress:
            print(f"        in progress: {', '.join(sorted(player.upgrades_in_progress))}")


def describe_army(observation: Observation) -> None:
    """What the local player owns, by real ownership rather than the template's Side.

    Structures and units are not separated: telling them apart needs the template's `KindOf`
    flags, which this reader does not have. Counting by template is the honest summary.
    """
    mine = observation.find(owner=observation.local_player, has_body=True)
    markers = len(observation.mine) - len(mine)
    print(f"\nyour objects ({len(mine)} with a body, {markers} inert map markers)")
    for name, count in observation.census(mine).most_common(12):
        print(f"  {count:>4}  {name}")

    upgraded = [o for o in mine if o.upgrades]
    if upgraded:
        print(f"\ncarrying object-scoped upgrades ({len(upgraded)})")
        for obj in upgraded[:8]:
            carried = ", ".join(sorted(obj.upgrades))
            print(f"  {obj.object_id:>7}  {obj.template_name:<32} {carried}")

    hurt = observation.find(owner=observation.local_player, damaged=True)
    if hurt:
        worst = min(hurt, key=lambda o: o.health)
        print(
            f"\n{len(hurt)} damaged; worst is {worst.template_name} #{worst.object_id} "
            f"at {worst.hit_points:.0f}/{worst.max_health:.0f}"
        )


def describe_threats(observation: Observation) -> None:
    """The nearest enemy object to each thing you own - the query a policy opens with."""
    mine = observation.find(owner=observation.local_player, has_body=True)
    if not mine:
        return
    anchor = mine[0]
    for opponent in observation.opponents:
        closest = observation.nearest(anchor.position, owner=opponent.index, has_body=True)
        if closest is None:
            print(f"\n{opponent.name} ({opponent.faction}): nothing owned that you can see")
            continue
        print(
            f"\n{opponent.name} ({opponent.faction}): nearest is {closest.template_name} "
            f"#{closest.object_id} at {anchor.distance_to(closest):.0f} units"
        )
        print(f"  they own {len(observation.owned_by(opponent.index))} objects in total")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pid", type=int, help="target process (default: first game.dat)")
    parser.add_argument("--wait", action="store_true", help="block until a match starts")
    args = parser.parse_args(argv)

    try:
        game = sage_live.attach(args.pid)
    except AttachError as exc:
        raise SystemExit(str(exc)) from exc

    with game:
        if args.wait:
            print("waiting for a match (the menu's shell map does not count)...")
            observation = game.wait_for_match()
        else:
            observation = game.observe()

        print(f"frame {observation.frame}, {len(observation.objects)} objects on the map")
        if not observation.in_match:
            print("this is the main menu's shell map, not a match - try --wait")
            return 1

        describe_players(observation)
        describe_army(observation)
        describe_threats(observation)

        for diagnostic in game.diagnostics:
            print(f"  ! {diagnostic}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
