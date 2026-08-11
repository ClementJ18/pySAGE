"""Spending gold: buildings, research centres, upgrades and the command-point ceiling.

The stages that turn a balance into something standing. They compete with `recruiting` for one
purse, which is what `building_reserve` and the two floors arbitrate.
"""

from __future__ import annotations

from sage_live.api.observation import GameObject
from sage_live.api.session import BUILD_CONFIRM
from sage_live.utils.statics import UpgradeButton
from sage_mods.edain.bot.orders import Orders
from sage_mods.edain.bot.tuning import (
    CP_CAP_MAX,
    CP_FLOOR,
    CP_MIN_ARMY,
    CP_OBJECT,
    ECONOMY_CAP,
    HOLDING_RADIUS,
    NOT_WORTH_UPGRADING,
    QUEUE_TARGET,
    REPAIR,
    RESEARCH_FLOOR,
    SELF_REPAIR_COST,
    UPGRADE_ATTEMPTS,
    UPGRADE_FLOOR,
    UPGRADE_QUEUE,
)


class Economy(Orders):
    """Spending gold: buildings, research centres, upgrades and the command-point ceiling."""

    def building_reserve(self) -> int:
        """Gold the next building has a claim on, which units may not spend.

        **Checking affordability turned the priority order into a starvation order.** Stages
        run cheapest-first by accident of their priority - a battalion is 200 and an economy
        building 400 - so once orders that cannot be paid for stopped being sent, recruiting
        took every balance the moment it crossed 200 and the building behind it was never
        reached. Measured: four economy buildings, three empty plots, and 20 straight cycles
        alternating "recruit" and "nothing to do" while gold never once got past 236.

        Before affordability was checked this hid, because the unaffordable build order went
        out anyway and was discarded - so gold climbed regardless and the building eventually
        landed. Refusing to send it made the bot poorer.

        **Bounded by the plots.** A reserve that never lifts would starve the army instead, so
        this claims gold only while there is somewhere to put a building. Plots are finite; when
        the last one is built on, `stage_build` wants nothing and the whole balance is the
        army's.
        """
        if not self.free_plots() or self.held_for_research():
            # Nothing is going to be built this cycle, so nothing has a claim. Reserving against
            # a building `stage_build` has already decided to skip is the starvation this method
            # exists to prevent, arriving by the other door: the plot is being kept for a
            # research centre, and taxing every recruit 400g to hold it buys nothing at all.
            return 0
        return self.statics.build_cost(self.wanted_building())

    def stage_sell(self) -> str | None:
        """Sell a surplus economy building when a plot is the only thing missing.

        **A base runs out of ground long before it runs out of gold.** The match this was
        written for finished holding 11,634 gold with `plots 0` - so the marketplace it had
        wanted since the first minute was never unbuildable for want of money, it was
        unbuildable for want of somewhere to stand. Selling a house is how that plot is bought,
        and the refund is incidental.

        **Only when the balance is not the problem**, and only for something that is not itself
        economy: trading a house for a house is a plot changing hands for nothing, and selling
        into a shortage is selling the economy that would have fixed it.

        The most damaged one goes. It is the one nearest to being lost anyway, so the refund is
        the largest share of what is left to lose - and a building at full health standing in a
        working base is the last thing to give up.

        **Sold from the tallest stack in the economy set, which is what keeps the balance a
        balance.** Capping each member at `ECONOMY_CAP` removed the surplus this used to sell out
        of - houses can no longer run past their own floor - so the question is no longer "is
        there a spare house" but "which ladder can spare a rung". Taking from the member with the
        most standing costs the smallest discount and leaves the set as even as it found it.

        Kept above `resource_target`, the opening's own floor: below that the economy *is* the
        plan, and a base that sells into it will simply build the same building again next cycle.
        """
        if self.free_plots() or self.spendable() < RESEARCH_FLOOR:
            return None
        economy = self.economy_set()
        wanted = [
            b for b in self.wanted_buildings() if b not in economy and not self.owned_building(b)
        ]
        if not wanted:
            return None
        # **Not one that is being fought over.** "Most damaged" and "under attack right now" are
        # nearly the same building, and selling that one is wrong twice: the plot it frees is
        # contested ground nothing should be built on this minute, and `stage_defend` may have a
        # group standing on it for exactly that reason. The one to give up is one nobody is
        # arguing about.
        quiet = {
            b: [
                h
                for h in self.owned_building(b)
                if not any(
                    self.hostile(o) and o.distance_to(h.position) < HOLDING_RADIUS
                    for o in self.observation.objects
                )
            ]
            for b in economy
        }
        tallest = max(quiet, key=lambda b: len(quiet[b]))
        if len(quiet[tallest]) <= self.plan.resource_target:
            return None
        spare = min(quiet[tallest], key=lambda h: h.health)
        key = f"sell:{spare.object_id}"
        if self._cold(key) or not self.select([spare]):
            return None
        if not self._issue("sell", self.session.sell):
            return None
        # The building leaving the table is the whole of the evidence: a sell that the engine
        # declines is the usual silent discard, and the refund is too small a fraction of a
        # working balance to read reliably as a change in gold.
        gone = self.session.confirm(
            lambda obs: obs.obj(spare.object_id) is None, timeout=BUILD_CONFIRM
        )
        self._report("sell", gone, "sold", "STILL STANDING - order discarded")
        self._strike(key, gone)
        return f"sell {spare.template_name} to free a plot for {wanted[0]}" if gone else None

    def stage_repair(self) -> str | None:
        """Put a destroyed keep back up, whenever the balance covers it.

        **A ruin is not a loss until it is left standing as one.** A camp or castle keep that
        falls stays in the object table at zero health wearing `RUBBLE`, and its own control bar
        offers the self-repair the engine prices at `SELF_REPAIR_COST` - so the alternative to
        spending that is not saving it, it is holding the ground with the anchor of the base
        knocked down.

        Confirmed by the gold leaving, which is the honest oracle here: the repair takes time and
        the health it restores arrives long after any confirmation window, but the charge lands
        at once.

        Ahead of every other spend in the phase order for the same reason `stage_defend` runs
        before the expansion: what is already ours and already paid for is worth more than the
        next thing bought.

        **And running first is not the same as being paid first, which is what this used to get
        wrong.** Priority decides who is *asked* first, not who keeps the gold: recruiting spends
        the balance back down every cycle, so whether a rubbled keep goes up now or in three
        minutes depends on where the balance happens to sit at the instant this stage runs.
        Measured, that gap was seventy-eight cycles - the castle keep was down from cycle 283 to
        361, and the castle could neither cast nor build for all of it. A rubbled keep therefore
        *reserves* what it needs, the moment the rubble is seen rather than when the balance is
        ready; the gold was never unreachable, it just arrived by luck.

        **The reservation is lifted the moment there is nothing to repair**, so a base with its
        keep standing is not quietly taxed 1000 for the rest of the match.

        **And it is lifted again when the base can no longer fight for itself, which is the
        deadlock the first version of this walked straight into.** An unbounded promise against a
        balance that is not growing stops being a promise and becomes a freeze: measured at cycle
        251 of a run, the bot held 875 gold with 1200 reserved, which is `spendable` of zero - no
        recruit, no building, nothing - while its base was being taken apart around it. It had
        `army 0` and `prod 0` and gold it was not allowed to touch, and it lost the match from
        there. This is the same shape as the plot deadlock `held_for_research` documents, moved
        into the gold dimension: gold was held for a purchase the held gold guaranteed it could
        never afford.

        So the docstring on `REPAIR` claiming nothing is worth more than the keep is wrong, and
        the counter-example is the army. A keep is worth banking for while there is something
        standing to defend it and something standing to rebuild it; with neither, the gold is
        worth incomparably more as troops, and the keep is not the reason the match is being lost.
        """
        wrecked = [s for s in self.structures() if s.is_rubble]
        if not wrecked:
            self.reserve(REPAIR, 0)
            return None
        # **Banking is what gets bounded, not repairing.** A base with nothing standing still
        # wants its keep back the moment it can genuinely pay for it - what it must not do is
        # promise gold it has no way of accumulating and freeze the balance in the meantime.
        banking = bool(self.production_buildings()) and bool(self.army())
        self.reserve(REPAIR, SELF_REPAIR_COST if banking else 0)
        # Its own promised gold, which is the point of holding it - `spendable()` without this
        # subtracts the reservation the repair itself made and can never reach the price.
        if self.spendable(REPAIR) < SELF_REPAIR_COST:
            return None
        keep = wrecked[0]
        key = f"repair:{keep.object_id}"
        if self._cold(key):
            return None
        if not self.select([keep]):
            return None
        ok = self.spend("repair", self.session.start_self_repair)
        self._strike(key, ok)
        return f"repair {keep.template_name} ({SELF_REPAIR_COST}g)" if ok else None

    def stage_build(self) -> str | None:
        """Place one structure: production, then economy to target, then economy for ever.

        One per cycle rather than one per *decision* - the difference is the whole point of
        splitting these stages. Building used to return out of `decide`, so a bot laying its
        third farm was not also recruiting, and the barracks stood idle through the entire
        economy phase.

        **A plot with nothing wanted on it is a plot wasted for the rest of the match.** The
        targets used to be a complete answer, and a measured match reached all of them by cycle
        7 and then left two castle plots empty for the next 145 cycles while gold banked past
        3000 with nothing to spend it on. Targets are the *opening* - what must exist before the
        army does - and after them the answer to a free plot is another economy building,
        because income is the only thing that keeps queues that deep fed.

        **Except for the plots the research centres are waiting on.** A gold floor alone cannot
        buy a building that needs somewhere to stand, and the two constraints do not arrive
        together: the economy fills every castle plot within the first minute, and gold does not
        reach `RESEARCH_FLOOR` until several minutes later. A measured match laid five economy
        buildings by cycle 45, ran `free_plots` at zero for the next two hundred, and passed
        1500 gold repeatedly with `wanted_research` naming a marketplace it could never place -
        a stage that attempts nothing for the whole match while reporting nothing wrong.
        `held_for_research` keeps the last plots free so the surplus has somewhere to land.
        """
        plots = self.free_plots()
        if not plots:
            return None
        for wanted in self.wanted_buildings():
            # **The whole economy set stands aside for the reserved plot, not just `resource`.**
            # The reserve exists because gold reaches `RESEARCH_FLOOR` minutes after the last plot
            # is taken, so a centre needs somewhere to land when the surplus finally arrives. A
            # partner building that walked past this guard would take that plot for a ladder rung
            # and put the marketplace back to waiting for ground that never frees.
            if wanted in self.economy_set() and self.held_for_research():
                continue
            if self._cold(f"build:{wanted}") or not self.afford(wanted):
                continue
            if self.build_on_plot(wanted, plots[0]):
                self._strike(f"build:{wanted}", True)
            return f"build {wanted}"
        return None

    def wanted_buildings(self) -> list[str]:
        """What the next plot could carry, best first - always non-empty, because a plot is
        always worth something.

        **Production before economy.** The barracks is what makes the parallel loop worth
        anything: until it exists `stage_recruit` has nothing to order and the whole opening is
        one building at a time. An earlier ordering put three farms first, so a bot whose builds
        were failing never reached the barracks at all and never recruited once.

        **A list rather than one answer, and that is a repair of a dead end.** This used to
        return the single best building, which `stage_build` then dropped if it was benched or
        unaffordable - and while no production building stands the best answer is always
        `production[0]`, so three failed barracks placements silenced the whole stage for ever.
        A measured match lost its base at cycle 500 and spent its last forty cycles on **5,910
        gold and eight free plots** reporting "nothing to do", because the one building it would
        consider was on cooldown and there was no second choice. Every entry here is somewhere
        worth putting a plot, so `stage_build` walks down the list instead of giving up on the
        first.

        Separate from `stage_build` because `building_reserve` needs the price of the next
        building without placing it, and a second copy of this ordering would drift from the
        first.
        """
        plan = self.plan
        wanted: list[str] = []
        # **The siege works leads, and only while the push is on.** It is the one building whose
        # worth is a function of the phase rather than of the base: nothing before the endgame,
        # and ahead of everything once what is left to win is a keep. Reading `_pushing` rather
        # than calling `pushing()` because that one latches and dissolves the parties - a query
        # asked from here must not decide the match.
        #
        # First in the list is what makes `stage_sell` work for it. That stage sells a surplus
        # house when something it wants has nowhere to stand, and Gondor's workshop is on an
        # internal plot only - so on a full castle this entry is the whole mechanism by which a
        # plot is freed for one.
        if self._pushing:
            wanted += [b for b in plan.siege if not self.owned_building(b)]
        if not self.production_buildings():
            wanted.append(plan.production[0])
        if len(self.owned_building(plan.resource)) < plan.resource_target:
            wanted.append(plan.resource)
        # **The next production building is a different one, not another of the same.** Both
        # spend a plot to buy queue depth; only one of them also widens what can be recruited,
        # and the mix is the thing the recruiting stage is now trying to reach. A second barracks
        # cannot make an archer.
        wanted += [
            b for b in plan.production[: plan.production_target] if not self.owned_building(b)
        ]
        # **The economy set, whichever member is furthest behind.** Ahead of the research centre
        # because these are not ones: they are laid for what they produce, not for what they
        # sell. See `wanted_economy` for why the order within the set is a balance and not a
        # sequence.
        wanted += self.wanted_economy()
        centre = self.wanted_research()
        if centre is not None:
            wanted.append(centre)
        wanted.append(plan.resource)
        return list(dict.fromkeys(wanted))

    def economy_set(self) -> tuple[str, ...]:
        """Every building laid for its own output - the resource building and its partners.

        One list rather than a primary and an afterthought, because the engine treats them the
        same: for Men both carry the identical `TerrainResourceBehavior` and the identical build
        cost, and differ only in which `CostModifierUpgrade` ladder they climb.
        """
        return (self.plan.resource, *self.plan.economy)

    def wanted_economy(self) -> list[str]:
        """The economy buildings still short of `ECONOMY_CAP`, the one furthest behind first.

        **A balance rather than a sequence, because the discount ladders are independent.** Each
        member carries its own six-rung `CostModifierUpgrade` and each rung is indexed by how many
        of *that* building stand - so filling one set of six before starting the other reaches the
        full -30% on one ladder while the other is still at zero. For Men that means either elites
        at -30% while every unit upgrade is full price, or the reverse, for most of a match.

        **And the plots run out first, which is what makes this the whole decision rather than a
        refinement of it.** A measured castle offered nine free plots at cycle 1 against the twelve
        a capped set wants, and `free_plots` sat at zero or one from cycle 45 onward - so in
        practice the base never chooses *whether* to build both, only how to split the plots it
        has. Sequenced, that split is "all houses"; balanced, it is even, which is the only version
        that gets both ladders off the ground.

        Ties go to the plan's own order, so `resource` stays the opening's building and a base with
        nothing standing still lays a house first.

        **The cap orders the preference, it does not end the economy.** Past six of everything this
        returns nothing and `wanted_buildings` falls through to its `resource` backstop, which is
        right: the sixth rung is the last one that improves a *discount*, but the
        `TerrainResourceBehavior` on a seventh building earns exactly what the first one does. What
        the cap buys is the ordering - no plot goes to a rung that cannot improve while the other
        ladder is still short of one that can.
        """
        standing = {b: len(self.owned_building(b)) for b in self.economy_set()}
        order = {b: i for i, b in enumerate(self.economy_set())}
        behind = [b for b, count in standing.items() if count < ECONOMY_CAP]
        return sorted(behind, key=lambda b: (standing[b], order[b]))

    def external_family(self, template: str) -> str | None:
        """Which of the plan's settlement buildings `template` is one of, or None.

        Membership follows the `ChildObject` chain rather than the name, because the palette
        offers a *tier* - `GondorFarm_Extern2` once the extern economy upgrade is held, `_Extern3`
        after the settler tools - and every tier descends from the level 1 template the plan
        names. See `Statics.descends_from` for why the obvious prefix test is not this.
        """
        for root in self.plan.external:
            if self.statics.descends_from(template, root):
                return root
        return None

    def external_standing(self) -> dict[str, int]:
        """How many of each of the plan's settlement buildings are standing, tiers included.

        Counted over everything owned rather than over `structures()`, because a settlement
        building raised this cycle is what the balance is about and the answer must include it.
        """
        counts = dict.fromkeys(self.plan.external, 0)
        for owned in self.observation.mine:
            family = self.external_family(owned.template_name)
            if family is not None:
                counts[family] += 1
        return counts

    def wanted_external(self, offered: tuple[str, ...]) -> str | None:
        """Which of `offered` a claimed settlement should raise - the family furthest behind.

        **The same balance as `wanted_economy`, for the same reason and one more.** Taking the
        first button on the plot is what the farm-only behaviour was, and it left every
        settlement identical; alternating spreads the two things that are *not* identical about
        them, since only the farm takes `GrandHarvest` and only the tents spawn defenders. A map
        of nothing but farms is a map where every expansion is undefended, and a map of nothing
        but tents is one where the marketplace bonus buys nothing.

        Ties go to the plan's order, so the first flag of a match still gets the farm.

        **A family the engine keeps refusing is dropped, and that is not a refinement.** Ranking
        by how many are standing means failure is invisible to this: a template that never gets
        built stays at zero, zero is always furthest behind, and so it is chosen at every flag
        for the rest of the match while the one that works is never reconsidered. One bad
        template poisons the whole of expansion. `raise_settlement` strikes against the family,
        and three refusals bench it here.

        None when nothing offered belongs to a family the plan names - an outpost's castle claim,
        a faction with no `external` list - **or when every family it does name is benched**. All
        three answers mean the same thing to the caller: keep the first-button behaviour, which
        is the palette's own slot 1 and the thing this was doing before there was a plan.
        """
        standing = self.external_standing()
        order = {root: i for i, root in enumerate(self.plan.external)}
        families = [(t, self.external_family(t)) for t in offered]
        known = [(t, f) for t, f in families if f is not None and not self._cold(f"unpack:{f}")]
        if not known:
            return None
        return min(known, key=lambda pair: (standing[pair[1]], order[pair[1]]))[0]

    def wanted_building(self) -> str:
        """The single best thing to put on the next plot - what `building_reserve` prices."""
        return self.wanted_buildings()[0]

    def wanted_research(self) -> str | None:
        """The next research centre worth a plot, or None while gold is better spent elsewhere.

        **A surplus is the entire justification, so the floor is the whole method.** Laying
        Gondor's marketplace and forge is a good trade out of a bank that has nowhere else to go
        and a bad one out of an opening's budget - a measured match spent 1800g and two of a
        castle's handful of plots on the pair, bought nothing from either, and lost the game it
        would otherwise have had the economy for. Below `RESEARCH_FLOOR` the answer is the
        economy building that raises the floor; above it the balance is already larger than the
        queues can absorb, which is the state that used to end with gold climbing past 3000
        against a fully built base.

        In order, and the order is a prerequisite chain rather than a preference: every tech
        `GondorForge` sells needs `Upgrade_MarketplaceUpgradeIronOre`, and only
        `GondorMarketPlace` sells that. A forge laid first is a forge whose whole palette is
        greyed out.
        """
        if self.spendable() < RESEARCH_FLOOR:
            return None
        return next(iter(self.missing_research()), None)

    def missing_research(self) -> list[str]:
        """The plan's research centres that are not standing, in chain order."""
        return [b for b in self.plan.research if not self.owned_building(b)]

    def held_for_research(self) -> bool:
        """Whether the free plots left are the ones a research centre is waiting for.

        **A plot and a surplus do not arrive at the same time, and the building needs both.**
        `wanted_research` is gated on gold, which is right - a shop laid out of an opening's
        budget is the 1800g mistake this file already records. But the economy reaches the last
        castle plot in about a minute and gold reaches `RESEARCH_FLOOR` several minutes after
        that, so by the time the surplus exists there is nowhere to spend it: measured live,
        `free_plots` sat at zero from cycle 45 to the end while `stage_upgrade` ran and the
        marketplace was never laid once.

        **One plot, and only once the economy is past its own target.** Reserving one per
        outstanding centre is the obvious reading and it deadlocks: measured live, it held both
        free plots from cycle 40 to the end of the match, which froze the economy at three farms,
        which meant gold never came near `RESEARCH_FLOOR`, which meant the plots were held for a
        purchase that could never happen. The reservation has to be small enough that the economy
        can still grow past it, because the economy is what pays for the thing being reserved
        for - so one plot waits, the rest keep earning, and the second centre takes the next plot
        that frees up.

        Three bounds, each closing a different way this can go wrong: nothing is held while a
        production building is still missing, nothing is held until the economy is *past*
        `resource_target` rather than merely at it, and nothing is held once the centres stand.
        """
        if not self.missing_research():
            return False
        planned = self.plan.production[: self.plan.production_target]
        if any(not self.owned_building(b) for b in planned):
            # The opening still owes a production building, and those come before everything.
            return False
        if len(self.owned_building(self.plan.resource)) <= self.plan.resource_target:
            # The economy has not cleared its own floor yet, and a plot held against a surplus
            # the economy is too small to generate is a plot held for ever.
            return False
        return len(self.free_plots()) <= 1

    def cp_in_flight(self) -> bool:
        """Whether a `CPObject` is already queued somewhere and simply not finished yet.

        The queue is the only place a bought-but-unbuilt one is visible: the capacity it will
        grant is not in the player's numbers until it completes, so every reading a policy has
        still says "at the cap" for the whole build time.
        """
        wanted = CP_OBJECT.lower()
        return any(
            item.name.lower() == wanted for obj in self.observation.mine for item in obj.production
        )

    def stage_command_points(self) -> str | None:
        """Raise the army ceiling before it stops production.

        `CPObject` is a buildable object rather than an upgrade: it is queued at a keep like a
        unit and each one bought lifts the cap. It matters more than it looks, because hitting
        the cap does not fail loudly - the engine takes the recruit order, charges nothing,
        queues nothing and says nothing, so a bot reads it as a working recruit that keeps not
        producing.

        The producer is found by asking each owned building what its command set can build,
        never by naming a keep: every faction sells `CPObject` through a different button on a
        different command set.

        **This is what clears a jammed production line, and it was nearly deleted as useless.**
        The purchase used to look like it did nothing from the outside, because the reader
        reported only the *base* cap - a flat 500 that never moves however many are bought.
        Isolated live: a match pinned at 472/500 with the army stuck at 23 battalions and
        recruits being discarded bought one, and when it finished building the reading went
        472 -> 484 -> 532 and production resumed. That was the bonus arriving, seen indirectly.
        It is now read directly at `+0x6C` and added to the cap, so the effect of a purchase is
        visible in `command_points_free` the moment the object finishes.

        **A `CPObject` is built, not granted**, which is why only one is bought at a time. It
        occupies the keep's queue for its build time and the capacity arrives at the end of it -
        so the "we are at the cap" condition that triggered the purchase is still true on the
        next cycle and the one after. Buying on each of those bought five in fourteen cycles,
        2500g, for one object's worth of ceiling.
        """
        me = self.observation.me
        if me is None or me.command_points_free > CP_FLOOR or self._cold("cp"):
            return None
        if me.command_points[1] >= CP_CAP_MAX:
            # **The ceiling has its own ceiling.** Five `CPObject`s is all the engine will honour -
            # a flat base of 500 plus 200 apiece - and past that a purchase is 500 gold and a keep
            # queue slot for nothing, on a condition (`command_points_free` at the floor) that is
            # now permanently true and so would buy one every cycle for the rest of the match.
            #
            # Read off the cap the game reports rather than by counting purchases, because the
            # objects can be destroyed with the keep that holds them: what matters is the ceiling
            # in force now, not how many were ever bought.
            return None
        if len(self.army()) < CP_MIN_ARMY:
            # Ceiling bought before there is an army under it is a keep queue slot spent on
            # nothing. The cap cannot bind on four battalions, so wait until it can.
            return None
        if not self.afford(CP_OBJECT):
            # 500 undiscounted, and the three strikes that used to follow an unaffordable
            # attempt benched the whole stage for two minutes at a time.
            return None
        if self.cp_in_flight():
            # **One at a time, because a `CPObject` is built rather than granted.** It sits in
            # the keep's queue for its build time like any unit, and the capacity does not
            # arrive until it finishes - so the condition that triggered this purchase is still
            # true on the next cycle, and on the one after that. A measured match bought five in
            # fourteen cycles, 2500g, while the first was still being built; the cap then rose
            # once, by one object's worth, and the other four followed as pure surplus.
            return None
        keeps = [
            o
            for o in self.observation.mine
            if CP_OBJECT.lower() in self.statics.recruits(o.template_name, self.held_by(o))
        ]
        if not keeps:
            return None
        keep = min(keeps, key=lambda o: len(o.production))
        if len(keep.production) >= QUEUE_TARGET:
            return None
        if not self.select([keep]):
            return None
        ok = self.session.confirm_queued(
            lambda: self._issue("cp", lambda: self.session.recruit(CP_OBJECT)),
            keep.object_id,
        )
        self._report("cp", ok, "queued", "NOT QUEUED - logic discarded it")
        self._strike("cp", ok)
        used, cap = me.command_points
        return f"command points {used}/{cap}, queued a {CP_OBJECT}"

    def upgrade_options(self) -> list[tuple[GameObject, UpgradeButton]]:
        """Every upgrade this player could legitimately buy right now, best first.

        **The command set is the authority, so this cannot order what the game would not
        offer.** An upgrade reachable here is one whose button exists on the target's own
        `CommandSet` and whose `NeededUpgrade` is satisfied - which is exactly the set a human's
        control bar would have shown as clickable. No name list, no faction table: the same walk
        finds Gondor's forge techs, Mordor's fire arrows and a barracks level-up.

        Four things disqualify a candidate, and each is a different field:

        - the prerequisite is unmet (`enabled_for`), so the button would be greyed out;
        - it is already held - `PlayerState.upgrades` for a faction tech, `GameObject.upgrades`
          for a per-object one, and reading the wrong one of those two buys it twice;
        - a faction tech is already being researched (`researching`), which the engine reports
          only at player scope;
        - this object's own queue already holds it, which is the only way to notice a
          per-object upgrade that is on its way but not yet landed.

        **Sorted gates first, then cheapest**, where a gate is an upgrade some other button
        currently visible is waiting on. Buying one is never wasted - it strictly widens what
        can be bought next - and it is what keeps the chain moving: ranking faction techs above
        per-object ones instead would buy the marketplace's five economy upgrades before
        putting armour on a single battalion, because those are faction-scope too.
        """
        me = self.observation.me
        if me is None:
            return []
        player_held = {u.lower() for u in me.upgrades}
        options: list[tuple[GameObject, UpgradeButton]] = []
        gates: set[str] = set()
        for obj in self.observation.mine:
            if self.statics.has_kind(obj.template_name, *NOT_WORTH_UPGRADING):
                continue
            if obj.under_construction:
                # **A building still going up takes the order and cannot work it.** It carries
                # its finished command set, so every prerequisite reads as met and the buy is
                # accepted - into a queue that will not move until the structure is built. The
                # cost is committed now for a tech that lands whenever construction happens to
                # end, and `queued_upgrades` then reads this building as busy, so the one-at-a-
                # time rule above holds it there. An upgrade is only worth its price if it
                # changes the battalions being built *now*; bought against a shell it does not.
                continue
            if self.queued_upgrades(obj) >= UPGRADE_QUEUE:
                # **One at a time, per building.** The queue is shared with units and runs in
                # order, so a second upgrade stacked behind the first arrives after everything
                # else waiting - and the whole value of an upgrade is that it changes the
                # battalions being built *now*. Stacking them also hides the gate: a level 3
                # queued behind a level 2 is bought before the level 2 has granted the flag that
                # makes level 3 legal, which the engine takes and silently discards.
                continue
            own = {u.lower() for u in obj.upgrades}
            # **Read against what this object already holds, which is what makes a level chain
            # more than one rung.** A structure's levels are `CommandSetUpgrade` modules: the
            # barracks offers `Upgrade_GondorStructureLevel2`, and only the palette that arrives
            # with it offers `Upgrade_GondorStructureLevel3_Barracks`. Asking for the static
            # command set buys the first level and then reports the building as fully upgraded.
            for button in self.statics.upgrade_buttons(obj.template_name, player_held | own):
                name = button.upgrade.lower()
                gates.update(u.lower() for u in button.needed_upgrades)
                if not button.enabled_for(player_held | own):
                    continue
                if name in (player_held if button.player_scope else own):
                    continue
                if button.player_scope and me.researching(button.upgrade):
                    continue
                if any(i.is_upgrade and i.name.lower() == name for i in obj.production):
                    continue
                options.append((obj, button))
        options.sort(key=lambda pair: (pair[1].upgrade.lower() not in gates, pair[1].cost))
        return options

    def research_something(self) -> str | None:
        """Buy the best available upgrade, or None when there is nothing worth buying.

        None is a real answer rather than a failure: early on every button is gated, and once
        the chain is exhausted there is nothing left to buy for the rest of the match.
        """
        options = [
            (o, b)
            for o, b in self.upgrade_options()
            if self._blocked_upgrades.get(self._upgrade_key(o, b), 0) < UPGRADE_ATTEMPTS
        ]
        if not options:
            return None
        target, button = options[0]
        scope = "faction" if button.player_scope else target.template_name
        ok = self.confirm_research(target, button)
        self._report("research", ok, "queued", "NOT QUEUED - logic discarded it")
        if not ok:
            # The command set offers it and the prerequisites read as met, yet logic threw it
            # away - some condition the observation does not expose. Retry once, then stop
            # paying a confirmation window for it every cycle.
            key = self._upgrade_key(target, button)
            self._blocked_upgrades[key] = self._blocked_upgrades.get(key, 0) + 1
        return f"research: {button.upgrade} ({button.cost}g) on {scope}"

    @staticmethod
    def _upgrade_key(target: GameObject, button: UpgradeButton) -> str:
        """What a refusal is remembered against - which has to be the button's own scope.

        **Keying everything by name disarmed an army.** A faction tech is bought once and the
        name is the whole of it, so remembering `upgrade_technologygondorheavyarmor` is exactly
        right. A *per-object* upgrade is bought once per battalion, and remembering it by name
        means two refusals anywhere retire it everywhere.

        That is not hypothetical. Measured across one match: `Upgrade_GondorHeavyArmor`,
        `Upgrade_GondorForgedBlades` and `Upgrade_GondorBasicTraining` were each bought three or
        four times, then refused twice on a single `GondorFighterHorde` - and with
        `UPGRADE_ATTEMPTS` at two, all three were retired for every battalion for the rest of the
        match. The run finished with 35,727 gold banked, its last research at cycle 931, and
        twenty-five battalions carrying none of the three upgrades the forge had already paid to
        unlock.

        A per-object refusal is a fact about *that object* - its queue, its state, whatever the
        observation does not show - so it is remembered against that object and the next
        battalion is asked on its own merits.
        """
        name = button.upgrade.lower()
        return name if button.player_scope else f"{target.object_id}:{name}"

    def stage_upgrade(self) -> str | None:
        """Spend the surplus on upgrades - **after** production has had its turn.

        The floor is what keeps this from competing with units: below it the gold belongs to
        the queues, above it there is more than production can absorb anyway.

        **On, and the only consumer of a surplus there is.** It was off while the opening was
        being rebuilt, on the grounds that research is the most expensive thing a half-built bot
        can get wrong. The opening now works, and the thing it gets wrong instead is having
        nowhere to put the money: a measured match finished with gold climbing past 3000, every
        queue full, every plot built on, and not one upgrade bought.

        What it buys is whatever the buildings that earned their place happen to sell - no plan
        names an upgrade, because `upgrade_options` walks the target's own command set and a
        button that is there is a button the control bar would have shown.
        """
        if self.spendable() < UPGRADE_FLOOR:
            return None
        return self.research_something()
