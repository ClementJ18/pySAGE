"""A scripted bot that plays a 1v1 skirmish: build economy, mass one unit, push.

The point is not the strategy - it is deliberately the simplest thing that can beat an Easy
AI - but the **control loop**, which is what an ML policy would later replace. Everything
below the `decide` boundary is reusable: attach, resolve names, find plots, verify that an
order did something, and notice the match ended.

    python examples/sage_live/bot.py --game "C:/Program Files (x86)/Games/bfme/rotwk"
    python examples/sage_live/bot.py --game ... --dry-run    # decide, print, send nothing

**Every order is verified, never assumed.** Game logic silently discards a malformed or
unaffordable order *after* the stream has taken it - no error, no diagnostic, and it still
reaches the replay. So this bot does not count a spend order as done until the player's gold
actually falls, and does not count a move as done until units actually move. That is the
oracle `sage_live`'s README prescribes, and here it doubles as instrumentation: `unpack` and
`attack_move` have never been confirmed live, so the run prints exactly which order types
made the game do something and which quietly did nothing.

**Classification comes from `KindOf`, not from names.** A live object carries a template name
and nothing else, and the interesting categories are not guessable from it:

- A **build plot** is `BASE_FOUNDATION` or `BASE_SITE`. It cannot be found by looking for an
  object with no body - a plot has an `ImmortalBody` of 15,000 - and its name follows no
  convention that holds across factions (`GondorBuildingFoundation`, but also
  `MordorFortressExpansionPadCorner`).
- A **defeated player** owns nothing carrying `MP_COUNT_FOR_VICTORY`. Note that an economy
  building is explicitly `IGNORE_FOR_VICTORY`, so counting buildings is not the same test.
- An **army** is what is selectable, mobile, and neither a structure nor a builder - which is
  how a porter (`DOZER PORTER`) stays out of the push and off the casualty list.

That join lives in `sage_live.statics` and costs one ini load at startup, about 35 seconds.

**Names, not ids.** Ids come from `sage_live.resolve.Resolver` - the ini path - rather than
from the engine's own live table. The two disagree (the live walk reads ten more templates),
and only the ini rule is corpus-validated: 491/491 `FOUNDATION_CONSTRUCT` orders across 12
fixtures resolve faction-consistently, per `order_space_map.md` section A. That section also
warns that ids must be resolved against a **live-install mount** and not against Edain's
`_mod` overlay tree, whose table is shifted one low - so pass the install folder to `--game`.

**No fog applies.** This reads the whole map, so finding the opponent's base is a lookup
rather than a scouting problem. That is an advantage a human does not have, and it is stated
here rather than hidden: a policy trained on this is training on privileged information.
"""

from __future__ import annotations

import sys
import time
from argparse import ArgumentParser
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # repo root on path

from sage_live.connect import AttachError, attach  # noqa: E402
from sage_live.naming import UnknownDefinition  # noqa: E402
from sage_live.observation import GameObject, Observation, Vec3  # noqa: E402
from sage_live.session import NoSelection, Session  # noqa: E402
from sage_live.statics import Statics  # noqa: E402

__all__ = ["PLANS", "Bot", "Plan", "main"]


@dataclass(frozen=True)
class Plan:
    """What to build and what to mass, for one faction.

    Deliberately tiny, and every template here was read off the faction's own command sets
    rather than guessed: `GondorFoundationCommandSet` slot 1 is the economy building and slot 3
    the barracks, and `GondorBarracksCommandSet` slot 1 is the basic infantry horde. Guessing
    produced `GondorFarm`, which is a BFME1 name Edain does not build.

    A build order is the part an ML policy replaces first, so the interesting code is the loop
    that executes one, not the contents of this table.
    """

    resource: str
    production: str
    unit: str
    # How many economy buildings before spending on army. Low: an Easy AI does not punish a
    # fast army, and a bot that economises forever never attacks.
    resource_target: int = 3
    # Battalions and heroes before the push - **not** soldiers. `army` counts horde containers
    # and skips their members, because that is what an order is addressed to, so a Men start of
    # two battalions of 15 reads as 2 here rather than 30.
    army_target: int = 8


# Keyed by the engine's own `Side` token, which is what `PlayerState.faction` carries. Note
# that Gondor's token is **`Men`** - keying this table on "gondor" matches nothing.
PLANS: dict[str, Plan] = {
    "men": Plan(
        resource="GondorWohnhaus",
        production="GondorBarracks",
        unit="GondorFighterHorde",
    ),
    "mordor": Plan(
        resource="MordorTributposten",
        production="MordorOrcPit",
        unit="MordorFighterHorde",
    ),
}

# How long to give the engine to act on an order before deciding it did nothing. Comfortably
# more than a logic frame, and short enough that a whole cycle stays responsive.
VERIFY_WINDOW = 1.5
VERIFY_POLL = 0.15

# Builds get longer: the order goes through the placement interface and the foundation has to
# be laid before anything is observable, which is more than one frame's worth of work.
BUILD_WINDOW = 4.0

# How near a plot a structure must stand to be the thing built on it. **A plot is not consumed
# by building on it** - the `GondorBuildingFoundation` object stays put underneath, so "is this
# plot free?" is a question about what is standing there, not about whether the plot still
# exists. Measured spacing between adjacent plots in a Men castle is about 150, so this is
# comfortably tight enough not to let one plot claim its neighbour's building.
PLOT_RADIUS = 60.0

# How far from the base's centre an owned build plot still counts as part of this base. Plots
# further out belong to an expansion that has not been claimed.
BASE_RADIUS = 900.0

# How close to the opponent's centre the push aims. Short of it, so the army arrives as a
# group and engages the base edge rather than walking into the middle of it.
PUSH_STANDOFF = 250.0

# `KindOf` flags that disqualify an object from the army: structures and plots do not move,
# and a builder sent to the front is a builder lost.
NOT_ARMY = ("STRUCTURE", "IMMOBILE", "DOZER", "PORTER", "BASE_FOUNDATION", "BASE_SITE")


@dataclass
class Ledger:
    """What each order type actually achieved, so a run reports rather than assumes.

    `unpack` and `attack_move` are unverified constructors; this is how a run says which of
    them worked. Kept as counts rather than a log because the interesting question is "did
    this order type ever do anything", not "what happened at 14:32".
    """

    sent: dict[str, int] = field(default_factory=dict)
    worked: dict[str, int] = field(default_factory=dict)

    def record(self, label: str, ok: bool) -> None:
        self.sent[label] = self.sent.get(label, 0) + 1
        if ok:
            self.worked[label] = self.worked.get(label, 0) + 1

    def report(self) -> str:
        if not self.sent:
            return "  no orders were sent"
        rows = []
        for label in sorted(self.sent):
            good, total = self.worked.get(label, 0), self.sent[label]
            verdict = "never did anything" if good == 0 else f"{good}/{total} took effect"
            rows.append(f"    {label:<16} {verdict}")
        return "\n".join(rows)


class Bot:
    """The control loop. `decide` is the seam an ML policy would replace."""

    def __init__(
        self, session: Session, plan: Plan, statics: Statics, dry_run: bool = False
    ) -> None:
        self.session = session
        self.plan = plan
        self.statics = statics
        self.dry_run = dry_run
        self.ledger = Ledger()
        self.observation: Observation = session.observe()

    # ---- reading the world -------------------------------------------------------------

    def refresh(self) -> Observation:
        self.observation = self.session.observe()
        return self.observation

    @property
    def gold(self) -> int:
        me = self.observation.me
        return 0 if me is None else me.resources

    def base_centre(self) -> Vec3:
        """The mean position of the immobile things owned - structures and plots.

        Anchored on the base rather than on everything owned, so it does not drift across the
        map with the army and turn `free_plots` into a distance test against the front line.
        """
        pool = [
            o
            for o in self.observation.mine
            if self.statics.has_kind(o.template_name, "STRUCTURE", "IMMOBILE")
            or self.statics.is_build_site(o.template_name)
        ] or list(self.observation.mine)
        if not pool:
            return (0.0, 0.0, 0.0)
        return (
            sum(o.position[0] for o in pool) / len(pool),
            sum(o.position[1] for o in pool) / len(pool),
            sum(o.position[2] for o in pool) / len(pool),
        )

    def structures(self) -> list[GameObject]:
        """Owned buildings - things that are structures but are not themselves plots."""
        return [
            o
            for o in self.observation.mine
            if self.statics.has_kind(o.template_name, "STRUCTURE")
            and not self.statics.is_build_site(o.template_name)
        ]

    def occupied(self, plot: GameObject, standing: list[GameObject]) -> bool:
        return any(s.distance_to(plot.position) < PLOT_RADIUS for s in standing)

    def free_plots(self) -> list[GameObject]:
        """Owned build plots near the base with nothing standing on them, nearest first.

        **Building on a plot does not consume it.** The `GondorBuildingFoundation` object stays
        underneath the finished structure, so a plot appearing in the object table says nothing
        about whether it is available. A bot that assumed otherwise re-ordered onto plot 508 for
        an entire match while its economy sat at one building, reporting each attempt as a
        failed order rather than as a plot that was already taken.

        Occupancy is therefore a proximity test against the buildings actually standing, which
        is also immune to `BuildVariations` - it asks what is there, not what it is called.
        """
        anchor = self.base_centre()
        standing = self.structures()
        plots = [
            o
            for o in self.observation.mine
            if self.statics.is_build_site(o.template_name)
            and o.distance_to(anchor) <= BASE_RADIUS
            and not self.occupied(o, standing)
        ]
        return sorted(plots, key=lambda o: o.distance_to(anchor))

    def owned_building(self, template: str) -> list[GameObject]:
        """Owned instances of `template`, counting the variations it may have been built as.

        **Neither a plain name nor a `KindOf` flag works here, for opposite reasons.** A name
        misses `BuildVariations`: ordering a `GondorWohnhaus` places a `GondorWohnhaus01`, so
        counting the ordered name reports zero forever and rebuilds every cycle. A flag is too
        broad: `GondorCastleBaseKeep` carries `FS_FACTORY` but its command set offers ring
        mechanics and hero revives, so counting factories finds the fortress, never builds a
        barracks, and then sends every recruit to a building that cannot make soldiers.

        `same_building` is the ordered name plus exactly its declared variations, which is
        precise and variation-proof at once.
        """
        wanted = self.statics.same_building(template)
        return [o for o in self.observation.mine if o.template_name.lower() in wanted]

    def army(self) -> list[GameObject]:
        """Owned fighting objects that an order should be addressed to.

        **Horde containers, never horde members.** A battalion appears in an observation as its
        15 members *plus* the container, and the members are slaved: `HordeAIUpdate` on the
        container is what moves them. Selecting the members and issuing a move produced an
        order the engine recorded and then ignored - the "sometimes recorded but nothing moved"
        symptom. `is_horde_member` reads `HordeContain.InitialPayload` to know which templates
        those are.

        Everything else is classified by `KindOf` so this holds for whatever the plan recruits
        and for the starting roster, without listing a faction's unit templates: selectable and
        mobile, not a structure, not a plot, not a builder. A lone hero is in no horde and so
        stays in, correctly.

        The count is therefore in *battalions and heroes*, not soldiers.
        """
        return [
            o
            for o in self.observation.mine
            if o.has_body
            and not self.statics.has_kind(o.template_name, *NOT_ARMY)
            and not self.statics.is_horde_member(o.template_name)
        ]

    def enemy(self) -> tuple[int, Vec3] | None:
        """The strongest opponent's index and the centre of their holdings, or None.

        No fog, so this is a lookup. Picks by object count because that is the honest proxy
        for "who is actually still playing" without any static data.
        """
        best: tuple[int, list[GameObject]] | None = None
        for player in self.observation.opponents:
            owned = list(self.observation.owned_by(player.index))
            if owned and (best is None or len(owned) > len(best[1])):
                best = (player.index, owned)
        if best is None:
            return None
        index, owned = best
        return index, (
            sum(o.position[0] for o in owned) / len(owned),
            sum(o.position[1] for o in owned) / len(owned),
            sum(o.position[2] for o in owned) / len(owned),
        )

    # ---- acting, and checking that the action landed -----------------------------------

    def _verify(self, changed: Callable[[], bool], window: float = VERIFY_WINDOW) -> bool:
        """Poll until `changed` holds or the window expires."""
        deadline = time.monotonic() + window
        while time.monotonic() < deadline:
            time.sleep(VERIFY_POLL)
            self.refresh()
            if changed():
                return True
        return False

    def spend(self, label: str, act: Callable[[], int]) -> bool:
        """Issue an order that should cost gold, and confirm the gold actually left.

        **A consumed order is not an accepted order.** Logic discards an unaffordable or
        malformed order after the stream has taken it, reporting nothing at all, so the only
        honest confirmation of a purchase is the balance falling.
        """
        before = self.gold
        if not self._issue(label, act):
            return False
        ok = self._verify(lambda: self.gold < before)
        self.ledger.record(label, ok)
        print(f"    {label:<16} {'charged' if ok else 'NOT CHARGED - logic discarded it'}")
        return ok

    def manoeuvre(self, label: str, act: Callable[[], int], units: list[GameObject]) -> bool:
        """Issue a movement order, and confirm the units actually moved.

        A move costs nothing, so the resource oracle says nothing about it. Positions do.
        """
        origin = {u.object_id: u.position for u in units}
        if not self._issue(label, act):
            return False

        def moved() -> bool:
            return any(
                (found := self.observation.obj(oid)) is not None and found.distance_to(was) > 5.0
                for oid, was in origin.items()
            )

        ok = self._verify(moved)
        self.ledger.record(label, ok)
        print(f"    {label:<16} {'units moved' if ok else 'NOTHING MOVED - order discarded'}")
        return ok

    def _issue(self, label: str, act: Callable[[], int]) -> bool:
        """Send, reporting the two failures that happen before the engine ever sees it."""
        if self.dry_run:
            print(f"    {label:<16} (dry run)")
            return False
        try:
            accepted = act()
        except (UnknownDefinition, NoSelection) as exc:
            print(f"    {label:<16} refused: {exc}")
            self.ledger.record(label, False)
            return False
        if not accepted:
            reason = "APM cap" if self.session.throttled else "backend refused it"
            print(f"    {label:<16} not sent ({reason})")
            self.ledger.record(label, False)
            return False
        return True

    def raise_building(self, label: str, act: Callable[[], int], plot: GameObject) -> bool:
        """Issue a build order, and confirm it by watching the **plot**, not the gold.

        Two oracles were wrong before this one. **Gold** produced a false negative on the very
        first build - a `GondorWohnhaus` went up while this reported `NOT CHARGED`. **The plot
        disappearing** never happens: a plot is not consumed by building on it, so that test
        reported failure for every build in a match.

        What is left is the only direct evidence: a structure standing on the plot that was not
        there before. That is immune to `BuildVariations` too, because it asks what appeared
        rather than what it is called.
        """
        before = {o.object_id for o in self.observation.mine}
        if not self._issue(label, act):
            return False

        def raised() -> bool:
            return any(
                o.object_id not in before and o.distance_to(plot.position) < PLOT_RADIUS
                for o in self.structures()
            )

        ok = self._verify(raised, window=BUILD_WINDOW)
        self.ledger.record(label, ok)
        print(f"    {label:<16} {'built' if ok else 'NOTHING APPEARED - order discarded'}")
        return ok

    def build_on_plot(self, template: str, plot: GameObject) -> bool:
        """Place `template` on `plot`, trying both build paths.

        There are two, and which one a faction and map use is not something this can know in
        advance. `build_at` drives the placement interface and carries a world position; it is
        the one confirmed live. `unpack` names only the template and takes its location from
        the selected plot, and is the documented path for fixed castle spots - but it has
        never been watched to build anything, so it is the fallback rather than the default.
        """
        label = f"build {template[6:15]}"
        if self.raise_building(label, lambda: self.session.build(template, plot.position), plot):
            return True
        print(f"      placement build failed on plot {plot.object_id}; trying the unpack path")
        self.session.select([plot.object_id])
        return self.raise_building("unpack", lambda: self.session.unpack(template), plot)

    # ---- the policy --------------------------------------------------------------------

    def decide(self) -> str:
        """One cycle. Returns a one-line description of what it chose to do.

        The ordering is the whole strategy: economy until it is sufficient, then a production
        building, then units forever, and a push once there are enough of them. An Easy AI
        does not punish the greed, and anything cleverer belongs in a learned policy.
        """
        self.refresh()
        plan = self.plan

        resources = self.owned_building(plan.resource)
        production = self.owned_building(plan.production)
        army = self.army()

        if len(resources) < plan.resource_target:
            plots = self.free_plots()
            if plots:
                self.build_on_plot(plan.resource, plots[0])
                return f"economy: {len(resources)}/{plan.resource_target} {plan.resource}"
            return "economy: wanted a resource building but no free plot is visible"

        if not production:
            plots = self.free_plots()
            if plots:
                self.build_on_plot(plan.production, plots[0])
                return f"production: placing a {plan.production}"
            return "production: wanted a production building but no free plot is visible"

        if len(army) < plan.army_target:
            # Recruiting acts on the selection, so the production building must be selected
            # first - and that clobbers any army selection, which is why the push re-selects.
            self.session.select([production[0].object_id])
            self.spend("recruit", lambda: self.session.recruit(plan.unit))
            return f"army: {len(army)}/{plan.army_target} battalions"

        target = self.enemy()
        if target is None:
            return "push: no opponent owns anything - the match looks decided"
        _, centre = target
        aim = self._standoff(centre)
        self.session.select([u.object_id for u in army])
        self.manoeuvre("attack_move", lambda: self.session.attack_move(aim), army)
        return f"push: {len(army)} objects toward ({aim[0]:.0f}, {aim[1]:.0f})"

    def _standoff(self, centre: Vec3) -> Vec3:
        """A point `PUSH_STANDOFF` short of `centre`, on the line from this base.

        Aiming at the middle of the enemy base walks the army through its defences to reach a
        coordinate; stopping at the edge lets it engage what it meets. Degenerate cases - the
        two centres coinciding, or a standoff longer than the gap - fall back to the centre
        itself rather than overshooting backwards past it.
        """
        home = self.base_centre()
        dx, dy = centre[0] - home[0], centre[1] - home[1]
        span = (dx * dx + dy * dy) ** 0.5
        if span <= PUSH_STANDOFF:
            return centre
        scale = (span - PUSH_STANDOFF) / span
        return (home[0] + dx * scale, home[1] + dy * scale, centre[2])

    def _holdings(self, index: int) -> list[GameObject]:
        """A player's objects that count toward the engine's multiplayer defeat check.

        `MP_COUNT_FOR_VICTORY` is the engine's own flag for this. Counting all objects instead
        would keep a beaten player alive on their economy buildings, which carry
        `IGNORE_FOR_VICTORY` precisely so they do not count.
        """
        return [
            o
            for o in self.observation.owned_by(index)
            if self.statics.counts_for_victory(o.template_name)
        ]

    def finished(self) -> str | None:
        """Why the match is over, or None while it continues.

        Derived from ownership rather than read from the engine. `TheVictorySystem` is *not*
        this - `victorysystem.ini` shows it is a per-cell battle-momentum bonus, not a win
        condition - and `TheVictoryConditions` has an address but has never been walked. So
        this infers, using the engine's own victory-counting flag, and says so.
        """
        if not self.observation.in_match:
            return "the match ended (the local player is no longer a faction)"
        if not self._holdings(self.session.player_index):
            return "defeat: nothing left that counts for victory"
        if all(not self._holdings(p.index) for p in self.observation.opponents):
            return "victory: no opponent holds anything that counts for victory"
        return None

    def run(self, cycles: int, interval: float) -> int:
        started = time.monotonic()
        for cycle in range(1, cycles + 1):
            me = self.observation.me
            print(
                f"\n[{cycle:>3}] frame {self.observation.frame}  "
                f"gold {self.gold}  army {len(self.army())}  "
                f"eco {len(self.owned_building(self.plan.resource))}  "
                f"prod {len(self.owned_building(self.plan.production))}  "
                f"plots {len(self.free_plots())}  "
                f"cp {me.command_points[0] if me else 0}/{me.command_points[1] if me else 0}  "
                f"{time.monotonic() - started:5.0f}s"
            )
            print(f"  {self.decide()}")
            over = self.finished()
            if over is not None:
                print(f"\n{over}")
                return 0
            time.sleep(interval)
        print(f"\nstopped after {cycles} cycles without a decision")
        return 0


def main(argv: list[str] | None = None) -> int:
    parser = ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--game", required=True, help="install folder holding the .big archives")
    parser.add_argument("--cycles", type=int, default=400, help="how many decisions to make")
    parser.add_argument("--interval", type=float, default=2.0, help="seconds between decisions")
    parser.add_argument("--dry-run", action="store_true", help="decide and print, send nothing")
    parser.add_argument("--faction", help="override the plan chosen from the local player's Side")
    args = parser.parse_args(argv)

    try:
        session = attach(writable=True)
    except AttachError as exc:
        raise SystemExit(str(exc)) from exc

    with session:
        print("waiting for a match (the menu is a running game, so this is not trivial)")
        observation = session.wait_for_match()
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

        # The ini work is the slow part - about 35s for the object model, plus the id tables -
        # so it happens once, after the match is confirmed, rather than delaying the attach. A
        # live install keeps its data in `.big` archives and both loaders want an ini tree, so
        # the install is mounted first; the mount is cached under the temp directory.
        from sage_live.resolve import Resolver  # noqa: PLC0415 - pulls in sage_ini
        from sage_utils.gameroot import resolve_game_root  # noqa: PLC0415

        root = resolve_game_root(args.game)
        print(f"loading {root} (about a minute) ...")
        session.names = Resolver.from_root(root)
        statics = Statics.from_root(root)
        for name in (plan.resource, plan.production, plan.unit):
            known = "" if statics.known(name) else "   <-- NOT IN THIS BUILD"
            print(f"  {name:<28} -> {session.resolve('thing', name)}{known}")

        bot = Bot(session, plan, statics, dry_run=args.dry_run)
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


if __name__ == "__main__":
    raise SystemExit(main())
