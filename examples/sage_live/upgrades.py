"""Research an upgrade and *verify it landed* - the two scopes, and the field that lies.

Upgrades are the first thing in the live API where the obvious reading is wrong, so this example
is built around the mistake rather than around the happy path:

    player.upgrades              faction-wide researches, and only those
    obj.upgrades                 this battalion's / this structure's own upgrades
    player.upgrades_in_progress  faction-wide research under way - object ones are NOT here

A per-battalion upgrade is recorded **only** on the object. It does not change the template name
and it never reaches `player.upgrades`, so `"Upgrade_GondorHeavyArmor" in player.upgrades` is
False on a fully armoured army. The engine also sets an object upgrade's *in-progress* bit on the
player and never clears it, which is why `upgrades_in_progress` is filtered to player scope: an
unfiltered read reports every battalion upgrade ever bought as forever pending.

Run from the repo root, in an elevated shell, with a match running:

    python examples/sage_live/upgrades.py --list
    python examples/sage_live/upgrades.py --upgrade Upgrade_MarketplaceUpgradeIronOre \
        --building 533
    python examples/sage_live/upgrades.py --upgrade Upgrade_GondorHeavyArmor --building 148

`--building` is the object id to research at, and it must be named: passing 0 is accepted by the
bridge and then silently discarded by game logic. `--list` prints what you own with its ids.
"""

import sys
import time
from argparse import ArgumentParser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # repo root on path

from _common import attach, describe, issue  # noqa: E402

from sage_live import orders  # noqa: E402
from sage_live.api.observation import GameObject  # noqa: E402
from sage_live.backends.bridge import BridgeBackend  # noqa: E402


def show_state(backend: BridgeBackend) -> None:
    """Both scopes, side by side, so the difference is visible rather than asserted."""
    observation = backend.observe()
    me = observation.local_player
    player = observation.player(me)
    if player is None:
        raise SystemExit("no local player - still at the menu?")

    print(
        f"\nplayer {player.name}: {len(player.upgrades)} completed, "
        f"{len(player.upgrades_in_progress)} researching"
    )
    for name in sorted(player.upgrades):
        print(f"    done         {name}")
    for name in sorted(player.upgrades_in_progress):
        print(f"    researching  {name}")

    upgraded = [o for o in observation.owned_by(me) if o.upgrades]
    print(f"\n{len(upgraded)} owned objects carry an object-scoped upgrade:")
    for obj in sorted(upgraded, key=lambda o: (o.template_name, o.object_id))[:20]:
        print(f"    {obj.object_id:>5}  {obj.template_name:<34} {', '.join(sorted(obj.upgrades))}")
    if len(upgraded) > 20:
        print(f"    ... and {len(upgraded) - 20} more")
    print("  (a horde and each of its members carry the same set, so one purchase counts many)")


def list_holdings(backend: BridgeBackend) -> None:
    observation = backend.observe()
    mine = observation.owned_by(observation.local_player)
    print(f"\n{len(mine)} owned objects - pass one of these ids as --building:")
    for obj in sorted(mine, key=lambda o: o.template_name):
        if obj.has_body:
            marks = f"  [{', '.join(sorted(obj.upgrades))}]" if obj.upgrades else ""
            print(f"    {obj.object_id:>5}  {obj.template_name:<34}{marks}")


def find(backend: BridgeBackend, object_id: int) -> GameObject | None:
    return next((o for o in backend.observe().objects if o.object_id == object_id), None)


def main() -> int:
    parser = ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--upgrade", help="code name, e.g. Upgrade_GondorHeavyArmor")
    parser.add_argument("--building", type=int, help="object id to research at (never 0)")
    parser.add_argument("--list", action="store_true", help="print owned objects and exit")
    parser.add_argument("--watch", type=float, default=120.0, help="seconds to watch for it")
    args = parser.parse_args()

    backend = attach()
    describe(backend)

    table = backend.upgrade_table()
    by_name = {d.name: d for d in table.values()}
    print(f"\nthe engine's registry holds {len(table)} upgrades, read live - no ini load needed")
    if args.list or not args.upgrade:
        list_holdings(backend)
        show_state(backend)
        if not args.upgrade:
            print("\npass --upgrade NAME --building ID to research one")
        return 0

    definition = by_name.get(args.upgrade)
    if definition is None:
        near = [n for n in by_name if args.upgrade.lower() in n.lower()][:5]
        hint = f"\n  did you mean: {', '.join(near)}?" if near else ""
        raise SystemExit(f"this build defines no upgrade named {args.upgrade!r}{hint}")
    scope = "PLAYER" if definition.player_scoped else "OBJECT"
    print(f"  {definition.name} -> id {definition.upgrade_id}, {scope}-scoped")

    if not args.building:
        raise SystemExit("--building is required: research(0) is discarded without a word")
    building = find(backend, args.building)
    if building is None:
        raise SystemExit(f"no object {args.building} in the world - try --list")
    print(f"  researching at {building.object_id} {building.template_name}")

    show_state(backend)
    me = backend.observe().local_player
    before = backend.observe().player(me)
    if before is None:
        # The menu is a running game with no faction in the local seat, so this is the
        # ordinary "not in a match yet" case rather than an unexpected one.
        print(f"seat {me} holds no player - is a match actually under way?")
        return 1
    if not issue(backend, orders.select(me, [args.building]), "select"):
        return 1
    if not issue(backend, orders.research(me, definition.upgrade_id, args.building), "research"):
        return 1

    # A consumed order is not an accepted one: the charge is the oracle. For a player-scoped
    # upgrade there is a second, sharper one - the in-progress mask, which says the engine has
    # started the research rather than merely taken the money.
    print(f"\nwatching for up to {args.watch:.0f}s")
    deadline = time.monotonic() + args.watch
    charged = started = False
    while time.monotonic() < deadline:
        time.sleep(1.0)
        observation = backend.observe()
        player = observation.player(me)
        if player is None:
            continue
        if not charged and player.resources < before.resources:
            charged = True
            print(f"  charged {before.resources - player.resources}, so logic accepted it")
        if not started and definition.name in player.upgrades_in_progress:
            started = True
            print("  the engine reports it as researching now")
        landed = (
            definition.name in player.upgrades
            if definition.player_scoped
            else definition.name in (find(backend, args.building) or building).upgrades
        )
        if landed:
            where = "the player" if definition.player_scoped else f"object {args.building}"
            print(f"  {definition.name} is now on {where}  PASS")
            show_state(backend)
            return 0

    if started:
        print(f"  still researching after {args.watch:.0f}s - accepted, just slow. Raise --watch.")
    elif charged:
        # Object-scoped upgrades are never visible as in-progress, so this is their normal
        # "not finished yet" state and says nothing is wrong.
        print(f"  charged but not applied after {args.watch:.0f}s; it probably needs longer.")
    else:
        print("  nothing was charged: game logic refused the order. The usual cause is that the")
        print("  building's CommandSet does not offer this upgrade, or a prerequisite is unmet.")
        print("  A research already under way is refused too - check the list above.")
    show_state(backend)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
