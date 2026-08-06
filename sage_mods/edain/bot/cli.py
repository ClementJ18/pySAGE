"""Attach to a running match, load the ini tree, report what the plan can reach, run the loop.

The two reports printed before the first order are worth more than they look. A plan that can
reach only one of its faction's units, or a research chain whose gate is never satisfiable, both
show up here in a line - rather than as a whole match spent massing one template and buying
nothing, which is how each of them was actually found.
"""

from __future__ import annotations

import threading
from argparse import ArgumentParser

from sage_live.api.connect import AttachError, attach
from sage_live.utils.statics import Statics
from sage_mods.edain.bot.bot import Bot
from sage_mods.edain.bot.plans import PLANS, Plan

__all__ = ["main", "report_pool", "report_spellbook"]


def report_pool(statics: Statics, plan: Plan, side: str) -> str:
    """What the faction's army definition offers, and which of it the plan can reach.

    A startup check rather than a running one, so it asks the plan's buildings what they sell
    instead of the buildings owned - the base has not been laid yet. The two answers agree once
    it has, minus whatever extra producers the match happens to hand over.

    `reachable_recruits` rather than `recruits`, because the question here is what the plan can
    get to over a match and not what it could order in the first frame. A Gondor barracks gates
    three of its seven units behind its own levels; reporting only the unlevelled palette would
    say this plan reaches four of the definition's units when it reaches seven.
    """
    army = statics.army_plan(side)
    if army is None:
        return f"  no ArmyDefinition for the side {side!r} - recruiting falls back to {plan.unit}"
    sells = {
        made: template
        for template in plan.production
        for made in statics.reachable_recruits(template)
    }
    rows = [
        f"  {army.name}: {len(army.members)} units listed, "
        f"phases {army.rush_seconds:.0f}s / {army.midgame_seconds:.0f}s / on"
    ]
    reached = 0
    for member in army.members:
        producer = sells.get(member.unit.lower())
        if producer is None:
            continue
        reached += 1
        shares = " ".join(f"{s:>5.1f}%" for s in member.shares)
        rows.append(
            f"    {member.unit:<30} {statics.build_cost(member.unit):>5}g  {shares}  {producer}"
        )
    if not reached:
        rows.append("    none of them - the plan's buildings sell nothing this definition wants")
    return "\n".join(rows)


def report_spellbook(statics: Statics, side: str) -> str:
    """The faction's spell store as the bot will read it: what is on sale, and what gates it.

    Worth printing for the same reason the research report is: a book that comes back empty is
    a faction whose `PlayerTemplate` this tree spells differently, and that shows up here in a
    line rather than as a match that never buys a power and never says why.

    The first row is what the opening can afford to work toward - the powers whose only
    prerequisite is the faction's own intrinsic science, which is held from frame one.
    """
    store = [power for power in statics.spell_store(side) if power.purchasable]
    if not store:
        return f"  no spell store for the side {side!r} - the bot will buy no powers"
    intrinsic = statics.intrinsic_sciences(side)
    held = {s.lower() for s in intrinsic}
    rows = [f"  spellbook: {len(store)} powers, starting from {', '.join(intrinsic) or 'nothing'}"]
    for power in store:
        gate = " or ".join(" + ".join(g) for g in power.prerequisites)
        opens = "open" if power.enabled_for(held) else "    "
        rows.append(f"    {power.science:<34} {power.cost:>3}pt  {opens}  needs {gate}")
    return "\n".join(rows)


def main(argv: list[str] | None = None) -> int:
    parser = ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--game", required=True, help="install folder holding the .big archives")
    parser.add_argument("--cycles", type=int, default=400, help="how many decisions to make")
    parser.add_argument("--interval", type=float, default=2.0, help="seconds between decisions")
    parser.add_argument("--dry-run", action="store_true", help="decide and print, send nothing")
    parser.add_argument("--faction", help="override the plan chosen from the local player's Side")
    parser.add_argument(
        "--fog",
        action="store_true",
        help="only see what the seat can see, so opponents have to be scouted",
    )
    parser.add_argument(
        "--no-camera",
        dest="camera",
        action="store_false",
        help="leave the view alone instead of staging shots (changes nothing about the match)",
    )
    parser.add_argument(
        "--record",
        action="store_true",
        help="press F8 at both ends of the run, which is OBS's start/stop recording hotkey",
    )
    # `Session.wait_for_match` defaults to 120s, which is the right default for a call made
    # once a match is known to be starting and the wrong one for this CLI: the first thing it
    # prints is that it is waiting for a match, so it is meant to be started *before* one
    # exists - and it died on the menu after two minutes, which read as a crash rather than as
    # a timeout anybody had chosen.
    parser.add_argument(
        "--wait",
        type=float,
        default=900.0,
        help="seconds to wait at the menu for a match to start (default 900)",
    )
    args = parser.parse_args(argv)

    try:
        session = attach(writable=True, fog=args.fog)
    except AttachError as exc:
        raise SystemExit(str(exc)) from exc

    with session:
        # **The ini load starts here, before the match, and runs on a thread while we wait.**
        # It used to run after `wait_for_match` returned, on the reasoning that it should not
        # delay the attach - which is right about the attach and backwards about the match. A
        # minute of parsing after the match has begun is a minute of the opening played without
        # a bot; the same minute spent while the menu is still up costs nothing, because the
        # menu, the loading screen and the map spawn take about that long anyway.
        #
        # Nothing in the load depends on the match: the tree comes from `--game`, and the only
        # thing that needs a live player is which plan to pick, which happens below. So a run
        # started at the main menu is loaded and ready at frame 0, and one started after the
        # match has begun is no worse off than it was before this.
        #
        # A live install keeps its data in `.big` archives and the loaders want an ini tree, so
        # the install is mounted first; the mount is cached under the temp directory.
        from sage_utils.gameroot import resolve_game_root  # noqa: PLC0415

        root = resolve_game_root(args.game)
        print(f"loading {root} in the background (about half a minute) ...")
        loading: list[tuple[Statics, object]] = []
        failed: list[BaseException] = []

        def load() -> None:
            # Imported in the thread for the same reason the call was deferred before: this is
            # what pulls in `sage_ini`, and the package stays importable without it.
            from sage_ini.loader import load_game  # noqa: PLC0415
            from sage_live.utils.resolve import Resolver  # noqa: PLC0415

            try:
                # **One parse, two consumers.** `Resolver.from_root` and `Statics.from_root`
                # each used to call `load_game` on the same path, walking eleven thousand
                # definitions twice in a row for two views of one answer.
                game = load_game(root).game
                loading.append((Statics(game), Resolver.from_game(game, root)))
            except BaseException as exc:  # noqa: BLE001 - re-raised on the main thread below
                failed.append(exc)

        loader = threading.Thread(target=load, name="ini-load", daemon=True)
        loader.start()

        print("waiting for a match (the menu is a running game, so this is not trivial)")
        observation = session.wait_for_match(timeout=args.wait)
        me = observation.me
        if me is None:
            raise SystemExit("in a match but with no local player - this should not happen")
        side = (args.faction or me.faction).lower()
        plan = PLANS.get(side)
        if plan is None:
            raise SystemExit(
                f"no plan for the faction {me.faction!r}. Known: {', '.join(sorted(PLANS))}. "
                "Add one to PLANS, or pass --faction to borrow another."
            )
        print(f"playing [{session.player_index}] {me.name} ({me.faction}) with the {side} plan")

        # Collect the load started before the wait. Already finished if the bot was launched at
        # the menu; otherwise this is the wait that used to happen unconditionally.
        if loader.is_alive():
            print("  the match is up - waiting on the rest of the ini load ...")
        loader.join()
        if failed:
            # Re-raised on the main thread, where the traceback is worth reading. A thread that
            # died quietly would leave `loading` empty and the next line failing on an index,
            # which reports a parse error as a crash in the bot.
            raise failed[0]
        statics, session.names = loading[0]
        named = (plan.resource, *plan.production, *plan.research, plan.unit)
        for name in named:
            known = "" if statics.known(name) else "   <-- NOT IN THIS BUILD"
            cost = statics.build_cost(name)
            print(f"  {name:<28} -> {session.resolve('thing', name):<6} {cost:>5}g{known}")

        # What the army definition will actually be able to ask for, before a single order goes
        # out. Most of its 57 Men entries belong to sub-factions or to the AI alone, so the line
        # that matters is not how long the pool is - it is which of it the planned buildings
        # sell, and a plan that reaches only one unit shows up here rather than as a match spent
        # massing one template again.
        print(report_pool(statics, plan, side))

        # What research will actually be able to buy, before a single order goes out. A gate
        # that is never satisfiable shows up here as a button that never becomes available,
        # rather than as an upgrade the bot silently never bought across a whole match.
        for template in named:
            for button in statics.upgrade_buttons(template):
                scope = "faction" if button.player_scope else "per-object"
                gate = ", ".join(button.needed_upgrades)
                print(
                    f"    {template:<22} sells {button.upgrade:<40} "
                    f"{button.cost:>5}g  {scope}{'  needs ' + gate if gate else ''}"
                )

        # What the spellbook offers, and which row of it is open from the start. Points are a
        # currency nothing else competes for, so a book that reads as empty here is the whole
        # of that currency going unspent for the match.
        print(report_spellbook(statics, side))

        bot = Bot(
            session,
            plan,
            statics,
            side,
            dry_run=args.dry_run,
            camera=args.camera,
            record=args.record,
        )
        try:
            code = bot.run(args.cycles, args.interval)
        except KeyboardInterrupt:
            print("\ninterrupted")
            code = 1

        print("\nwhat each order type actually achieved:")
        print(bot.ledger.report())
        if session.throttled:
            print(f"  ({session.throttled} orders dropped by the APM cap)")
        return code
