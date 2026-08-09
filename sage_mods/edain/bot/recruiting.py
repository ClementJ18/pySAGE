"""What to build an army out of.

The mix comes from the faction's own `ArmyDefinition`, intersected with what the buildings owned
can actually recruit and tilted by what the opponent has standing. Nothing here names a matchup.
"""

from __future__ import annotations

from sage_live.api.observation import GameObject
from sage_mods.edain.bot.powers import Powers
from sage_mods.edain.bot.tuning import (
    COUNTER_RANGE,
    QUEUE_TARGET,
    RECRUIT_NEVER,
    SUCCESSION_SHARE,
)


class Recruiting(Powers):
    """What to build an army out of."""

    def producers(self) -> dict[str, list[GameObject]]:
        """For each unit the army definition wants, the owned buildings that can recruit it.

        **This is the whole legitimacy filter, and it is the reason the pool can be trusted.**
        The definition names units for every sub-faction and several AI-only stand-ins, and the
        naming gives nothing away - some carry `_AI`, `ArnorArcherHordeMod` does not, and
        `AmrothFighterHorde` is an ordinary-looking template no Gondor building sells. Asking
        each owned building what its own `CommandSet` builds keeps only what the control bar
        would really have offered, and needs no list to maintain.

        It also finds producers no plan names: a Men fortress citadel sells two of the pool's
        units, so building one hands the mix two more entries without a line of code.

        **Asked of each building as it currently stands, not as it was raised.** A Gondor
        barracks sells seven units and gates three of them behind its own levels, so the flat
        answer is wrong both ways: it offered `GondorTowerShieldGuardHorde` at a level-1
        barracks, which the engine discarded in silence, and it could never see the level-2 and
        level-3 palettes at all - which is where the variety this stage is for actually lives.
        `stage_upgrade` buys those levels; this is what collects on them.

        **Minus what this bot will not field at all.** `RECRUIT_NEVER` is a `KindOf` test rather
        than a template list, and it currently holds siege: a measured run bought eight battering
        rams that walked to their targets alone and achieved nothing, because escorting them is a
        behaviour this bot does not have. Filtering here rather than at the order is deliberate -
        the mix is a set of shares, so a unit that is never ordered but stays in the mix
        permanently owns a share of an army that never gets built.
        """
        if self.army_plan is None:
            return {}
        # **The ban lifts for the push, because the reason for it does.** Siege is barred
        # everywhere else for want of an escort - eight battering rams once walked to their
        # targets alone - and a push is the one formation where that behaviour exists for free:
        # the whole force moves to one place as one body, so a ram ordered during one arrives
        # inside it. It also has something to do there, which it does not at a settlement flag.
        pool = {
            m.unit.lower(): m.unit
            for m in self.army_plan.members
            if self._pushing
            or not self.statics.has_kind(
                self.statics.fighting_template(m.unit) or m.unit, *RECRUIT_NEVER
            )
        }
        found: dict[str, list[GameObject]] = {}
        for building in self.structures():
            for made in self.statics.recruits(building.template_name, self.held_by(building)):
                unit = pool.get(made)
                if unit is not None:
                    found.setdefault(unit, []).append(building)
        return found

    def counter_score(self, unit: str, threat: dict[str, int]) -> float:
        """How well `unit` trades into `threat`, the army that is actually on the map - ~1.0.

        **The engine computes this, and nothing here names a matchup.** `Statics.effectiveness`
        joins the attacker's `DamageType` to the defender's `Armor` block, which is where the
        game's rock-paper-scissors is really written down: Gondor's pikes deal `SPECIALIST`,
        `EdainCavalryArmor` takes 170% of it and `EdainInfantryArmor` 65%. So "pikes are
        required against Mordor" is not a rule this file states - it is what the numbers say
        the moment Mordor fields `MordorMorgulriderHorde` or a mountain troll, and the same
        walk answers for a faction and a mod nobody here has heard of.

        Weighted by how many of each the opponents have, so one troll does not re-aim the whole
        build order and a wall of orcs does. Clamped by `COUNTER_RANGE`, because the raw spread
        is wide enough to zero a unit out entirely - see there.

        `threat` is passed in rather than read, so one census answers for the whole mix instead
        of being walked once per candidate unit.
        """
        total = sum(threat.values())
        if not total:
            return 1.0
        score = (
            sum(self.statics.effectiveness(unit, template) * n for template, n in threat.items())
            / total
        )
        low, high = COUNTER_RANGE
        return min(max(score, low), high)

    def promote(
        self, shares: dict[str, float], producers: dict[str, list[GameObject]]
    ) -> dict[str, float]:
        """Move most of a basic unit's share to the elite that succeeds it, once it is orderable.

        **The trigger is that the elite has a producer, and nothing else needs checking.** A
        levelled building is the only thing that puts `GondorWachterderVesteHorde` or
        `GondorRangerHorde` on a command set, so `producers` containing one *is* the statement
        "the barracks reached level 2". Testing the upgrade name directly would be the same
        answer arrived at less honestly, and would have to be rewritten for the next faction.

        Applied before the counter weighting rather than after, so the elite is judged on its
        own matchup like everything else. That costs nothing here - each pair deals the damage
        type its predecessor did - and it keeps one rule instead of two.

        The basic keeps a third of the role. `SUCCESSION_SHARE` records why.
        """
        promoted = dict(shares)
        for basic, elite in self.plan.succession:
            if elite not in producers or basic not in promoted:
                continue
            moved = promoted[basic] * SUCCESSION_SHARE
            promoted[basic] -= moved
            promoted[elite] = promoted.get(elite, 0.0) + moved
        return promoted

    def wanted_mix(self) -> dict[str, float]:
        """The target share of the army per unit this phase, over what is reachable now.

        **Normalised across the survivors, never across the file.** The percentages are shares
        of an army and the file does not make them sum to anything: Men's phase 1 totals over
        700 across 57 members and Mordor's `MordorFighterHorde` alone reads 150. They are only
        meaningful against each other, and only among the units this base can actually produce -
        so the sum that matters is the one taken after `producers` has filtered.

        A unit listed twice keeps its largest share rather than the sum of the two, which is not
        a hypothetical: `MordorArmy` names `MordorCirithOrkHorde` in two different roles.

        **And tilted toward what beats what the opponent actually fielded.** The definition is
        authoritative about the shape of a good army in the abstract and knows nothing about who
        it is playing - it asks for the same quarter archers whether the enemy is massing horses
        or pikes. `counter_score` multiplies each share by how that unit trades into the army on
        the map, so the mix stays the faction's own and moves toward its answer: against Mordor
        cavalry the spearmen's share roughly doubles and the swordsmen's halves, and neither
        disappears, which is the difference between countering and swapping one wall of a single
        unit for another.
        """
        producers = self.producers()
        if not producers:
            return {}
        phase = self.phase()
        shares: dict[str, float] = {}
        for member in self.army_plan.members if self.army_plan else ():
            if member.unit in producers and member.share(phase) > 0:
                shares[member.unit] = max(shares.get(member.unit, 0.0), member.share(phase))
        shares = self.promote(shares, producers)
        threat = self.enemy_army()
        shares = {unit: share * self.counter_score(unit, threat) for unit, share in shares.items()}
        total = sum(shares.values())
        if total <= 0:
            return {}
        return {unit: share / total for unit, share in shares.items()}

    def held(self) -> dict[str, int]:
        """How many of each unit template this player has **or has coming**, lowercased.

        The queues count, and leaving them out is what turns a mix into an oscillation: a
        recruit takes many cycles to become a battalion, so a bot reading only what is standing
        sees no progress on the unit it just ordered and orders it again, and again, until the
        first one finally lands. Twelve archers arrive where four were wanted.
        """
        counts: dict[str, int] = {}
        for unit in self.army():
            key = unit.template_name.lower()
            counts[key] = counts.get(key, 0) + 1
        for building in self.structures():
            for item in building.production:
                if not item.is_upgrade and item.name:
                    key = item.name.lower()
                    counts[key] = counts.get(key, 0) + 1
        return counts

    def next_recruit(self) -> tuple[str, GameObject] | None:
        """The unit furthest below its target share, and the building to order it at.

        **The whole mix is ranked, not just its head.** Taking only the neediest unit and
        returning when it cannot be paid for stalls production behind whatever is dearest -
        Gondor's tower shield guard is 1200 and its swordsmen 200, so one unaffordable entry
        would idle a barracks that could have been filling. Everything below it gets its turn in
        the same cycle instead, cheapest first among equals.

        A unit with nothing left to recruit it - the building died, or its queue is full - drops
        out the same way, so losing the stable degrades the mix rather than stopping it.
        """
        mix = self.wanted_mix()
        if not mix:
            return None
        producers = self.producers()
        counts = self.held()
        total = sum(counts.get(unit.lower(), 0) for unit in mix)
        reserve = self.building_reserve()

        def deficit(unit: str) -> tuple[float, int]:
            have = counts.get(unit.lower(), 0) / total if total else 0.0
            return (mix[unit] - have, -self.statics.build_cost(unit))

        for unit in sorted(mix, key=deficit, reverse=True):
            if not self.afford(unit, reserve=reserve):
                continue
            usable = [b for b in producers[unit] if self.queued_units(b) < QUEUE_TARGET]
            if usable:
                return unit, min(usable, key=self.queued_units)
        return None

    def staple_recruit(self) -> tuple[str, GameObject] | None:
        """The plan's one named unit, for when the pool can offer nothing.

        Reached when the tree defines no army for this side, when nothing the definition asks
        for is buildable yet, or when every producer in the mix is full or unaffordable. The
        opening runs through here too: the first barracks is standing well before the mix has
        anything to say about it.
        """
        usable = [
            b
            for b in self.owned_building(self.plan.production[0])
            if self.queued_units(b) < QUEUE_TARGET
        ]
        if not usable or not self.afford(self.plan.unit, reserve=self.building_reserve()):
            return None
        return self.plan.unit, min(usable, key=self.queued_units)

    def stage_recruit(self) -> str | None:
        """Keep the production queues topped up. **Runs before anything else spends gold.**

        Units come first because they are the only thing that both defends and wins, and
        because everything else - upgrades, expansions, the command-point ceiling - is worth
        nothing without them. An earlier ordering bought upgrades whenever gold crossed a
        floor, which starved production exactly when the economy was finally good enough to
        run it hard.

        **What to order is a ratio, not a template.** `next_recruit` picks whichever unit the
        army is furthest short of against the faction's own `ArmyDefinition` mix, so a cycle
        adds spears to a wall of swordsmen rather than a fifteenth swordsman. `staple_recruit`
        is the floor underneath it, for a side the tree defines no army for.

        **Queue depth, not "is it busy".** A queue holds about twenty, so refusing to order at
        a building that is merely working throws most of the faction's output away. What the
        queue is good for is knowing how much is already coming, so orders spread across
        buildings instead of filling one.

        **Nothing here stands down at the command-point cap, and an earlier version's doing so
        was the single most expensive line in the file.** The reasoning was sound - at a real
        cap the engine takes a recruit order, charges nothing, queues nothing and reports
        nothing, and that cap is genuinely enforced. What was wrong was the number: the reader
        reported the *base* cap, a flat 500 for every seat, while the engine checks base plus the
        bonus each built `CPObject` adds. So a player at 1262 points of army read as 1262/500 and
        this test said "full" from about a third of the way in; the stage returned without
        ordering for 60 cycles, gold banked past 3000, and the army it refused to build was the
        army that was needed on the map. The reader sums both fields now, so the arithmetic is
        sound - but the test stays out, because `confirm_queued` already
        reports a recruit that did not take, which is the honest version of the same question.
        """
        # **Nothing new goes in the queue at a hard cap**, and that is a narrower test than the
        # one this file used to carry. See the paragraph above for the version that was removed:
        # it compared against the *base* cap, a flat 500, and shut recruiting down from a third
        # of the way in. This asks only whether the headroom is gone outright - zero, from a
        # reader that now sums base and bonus - which cannot repeat that mistake.
        #
        # Two things go wrong without it, and the second is the expensive one. The engine takes
        # an order it cannot fill, charges nothing and queues nothing, so 57 of one match's 121
        # recruit orders were discarded, each costing a selection and a confirmation window. And
        # a building's queue is shared with its upgrades and runs in order, so the units already
        # queued when the cap arrived sit there unable to finish and an upgrade behind them never
        # starts - a `GondorArcherRange` level-up stuck behind battalions the engine would not
        # build.
        me = self.observation.me
        if me is not None and me.command_points_free <= 0:
            return None
        chosen = self.next_recruit() or self.staple_recruit()
        if chosen is None:
            return None
        unit, target = chosen

        # **Headroom is not the same question as "is there any headroom".** The test above asks
        # whether the ceiling is gone outright, which is true only at exactly the cap; a
        # battalion charges 12 to 60 points and an elite archer horde a good deal more, so a
        # player with 46 free points passes that test and still cannot recruit anything. That
        # band is where the discards actually live: measured across a whole match, 71 of 219
        # recruit orders were thrown away at a mean of 46 free points, against 409 for the ones
        # that queued - 99% of the failures under 150, and 18 of them the same
        # `GondorRangerHorde` at the same archer range.
        #
        # An unaffordable recruit is refused the same silent way as an unaffordable build, so
        # each of those cost a selection and a confirmation window and reported nothing. Pricing
        # the unit first turns that into one skipped stage. Nothing is lost by waiting either:
        # `CP_FLOOR` is sized above a battalion, so headroom this short is already what triggers
        # `stage_command_points` to go and buy more ceiling.
        free = None if me is None else me.command_points_free
        cost = self.statics.command_point_cost(unit)
        if free is not None and cost and cost > free:
            return f"{unit} costs {cost} command points and {free} are free - waiting for ceiling"
        # Recruiting acts on the selection, so the building must be selected first - and that
        # clobbers any army selection, which is why every stage that moves units re-selects.
        if not self.select([target]):
            return None
        ok = self.session.confirm_queued(
            lambda: self._issue("recruit", lambda: self.session.recruit(unit)),
            target.object_id,
        )
        self._report("recruit", ok, "queued", "NOT QUEUED - logic discarded it")
        return f"recruit {unit} at {target.object_id}"
