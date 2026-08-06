"""Recruit a unit by **name** - the whole point of `sage_live.utils.resolve`.

Everything else in these examples orders things by ids read live out of the game: select and
move only ever name objects that already exist. Recruiting, building, researching and casting
need ids from the game's *data tables*, and those are what `Resolver` supplies:

    orders.recruit(player, 6114)                    # what the wire carries
    resolver.recruit("ElvenLorienWarriorHorde")     # what a policy should say

Ids are not stable across Edain releases, so a policy holding raw integers silently means
something different after an update. A name either resolves or fails loudly.

Run from the repo root, in an elevated shell, with a match running:

    python examples/sage_live/recruit_by_name.py --game "C:/Program Files (x86)/Games/bfme/rotwk" \
        --unit ElvenLorienWarriorHorde

The first run mounts the install's `.big` archives and parses the ini tree, which takes about a
minute; the mount is cached, the parse is not.
"""

import sys
import time
from argparse import ArgumentParser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # repo root on path

from _common import attach, describe, issue, my_units  # noqa: E402

from sage_live import orders  # noqa: E402
from sage_live.backends.bridge import BridgeBackend  # noqa: E402
from sage_live.utils.resolve import Resolver, UnknownDefinition  # noqa: E402
from sage_utils.gameroot import resolve_game_root  # noqa: E402


def producers(backend: BridgeBackend, wanted: str) -> list:
    """Owned objects whose template name contains `wanted` - the production building to use.

    Which buildings can actually produce which units lives in the CommandSet tables; this
    example takes the building as an argument instead of deriving it, so it stays about name
    resolution rather than about command sets.
    """
    return [u for u in my_units(backend) if wanted.lower() in u.template_name.lower()]


def count_of(backend: BridgeBackend, template: str) -> int:
    return sum(1 for o in backend.observe().objects if o.template_name == template)


def main() -> int:
    parser = ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--game", required=True, help="install folder, or an extracted ini tree")
    parser.add_argument("--unit", required=True, help="template name to recruit")
    parser.add_argument(
        "--building", default="Fortress", help="substring of the producing building's template"
    )
    parser.add_argument("--watch", type=float, default=30.0, help="seconds to watch for the unit")
    args = parser.parse_args()

    backend = attach()
    describe(backend)

    building = producers(backend, args.building)
    if not building:
        raise SystemExit(f"no owned building matching {args.building!r} - try --building")
    producer = building[0]
    print(f"producer: {producer.object_id} {producer.template_name}")

    print(f"\nloading the game tables from {args.game} (about a minute the first time)")
    started = time.time()
    resolver = Resolver.from_root(
        resolve_game_root(args.game), player_index=backend.observe().local_player
    )
    print(f"  loaded {len(resolver.game.object_order)} templates in {time.time() - started:.0f}s")

    try:
        order = resolver.recruit(args.unit)
    except UnknownDefinition as exc:
        raise SystemExit(str(exc)) from exc
    template_id = next(a.value for a in order.arguments if a.argument_type == 0)
    print(f"  {args.unit} -> id {template_id}")

    before = count_of(backend, args.unit)
    print(f"\n{before} {args.unit} in the world right now")

    if not issue(backend, orders.select(resolver.player_index, [producer.object_id]), "select"):
        return 1
    if not issue(backend, order, "recruit"):
        return 1

    print(f"\nwatching for a new {args.unit} (up to {args.watch:.0f}s)")
    deadline = time.monotonic() + args.watch
    while time.monotonic() < deadline:
        now = count_of(backend, args.unit)
        if now > before:
            print(f"  {args.unit} count {before} -> {now}  PASS")
            return 0
        time.sleep(1.0)

    print("  no new unit appeared.")
    print("  Check the player's resources first: if they did not drop, game logic rejected the")
    print("  order rather than queueing it. The usual cause is an unmet prerequisite - the")
    print("  button is disabled in the sidebar, and logic refuses it however it is ordered.")
    print("  If resources *did* drop, the unit is queued and just needs longer than --watch.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
