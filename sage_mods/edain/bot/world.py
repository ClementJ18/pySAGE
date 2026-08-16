"""Reading the board.

Everything that answers a question about what is on the map, and nothing that changes it. The
join from a live object to what the ini says about it is `Statics`; this layer turns that into
the categories the stages actually reason about - the army, the plots, the nests, the raiders.
"""

from __future__ import annotations

import time
from collections.abc import Sequence

from sage_live.api.observation import GameObject, Observation, Vec3
from sage_live.utils.statics import CostLadder
from sage_mods.edain.bot.state import BotState
from sage_mods.edain.bot.tuning import (
    BASE_RADIUS,
    CAVALRY,
    CIVILIAN_SEAT,
    CONTEST_RADIUS,
    CRATE,
    CRUSH_REVENGE_CHARGED,
    DEFEND_RADIUS,
    HARMLESS,
    HERO,
    HOLDING_RADIUS,
    IN_FLIGHT,
    INFANTRY,
    LAIR_RADIUS,
    NEST_GONE,
    NO_BASE_CAPTURE,
    NOT_ARMY,
    OCCUPIED,
    PIKE,
    PLOT_CONTESTED,
    PLOT_RADIUS,
    PLOT_REBUILD_SECONDS,
    ROLES,
    SELECTABLE,
    UNTOUCHABLE,
)


class World(BotState):
    """Reading the board."""

    def base_centre(self) -> Vec3:
        """The mean position of the immobile things owned near where the base last was.

        Anchored on the base rather than on everything owned, so it does not drift across the
        map with the army and turn `free_plots` into a distance test against the front line.

        **And anchored on the *previous* reading, not just on what is immobile.** A settlement
        taken across the map is a building like any other, so a plain mean walks the base out
        behind the expansions - which is fatal in both directions at once. `DEFEND_RADIUS`
        travels with it, so a bot that had claimed a few flags read every creep in the middle of
        the map as an attack on its base and stood every other stage down; and `free_plots`
        measures from the same point, so it stopped seeing the castle plots it had not built on.
        Taking each reading over the buildings within `BASE_RADIUS` of the last one keeps it
        where the match put it, and falling back to the whole set when nothing is left there
        lets it re-seat rather than stay pinned to a razed base.
        """
        pool = [
            o
            for o in self.observation.mine
            if self.statics.has_kind(o.template_name, "STRUCTURE", "IMMOBILE")
            or self.statics.is_build_site(o.template_name)
        ] or list(self.observation.mine)
        if self._home is not None:
            pool = [o for o in pool if o.distance_to(self._home) <= BASE_RADIUS] or pool
        if not pool:
            return self._home or (0.0, 0.0, 0.0)
        centre = (
            sum(o.position[0] for o in pool) / len(pool),
            sum(o.position[1] for o in pool) / len(pool),
            sum(o.position[2] for o in pool) / len(pool),
        )
        self._home = centre
        return centre

    def structures(self) -> list[GameObject]:
        """Owned buildings - things that are structures but are not themselves plots."""
        return [
            o
            for o in self.observation.mine
            if self.statics.has_kind(o.template_name, "STRUCTURE")
            and not self.statics.is_build_site(o.template_name)
        ]

    def production_sites(self) -> list[GameObject]:
        """Owned buildings whose queue will actually move - finished, and not wreckage.

        **A building still going up accepts production orders and cannot work them, and the
        acceptance is what makes this expensive.** There is no refusal to notice: the order is
        taken, the cost is committed, and the item sits in the queue of a structure that will not
        start it until it has finished being built. Nothing reports that, because from the
        outside it is indistinguishable from an ordinary queued unit.

        **And an empty queue is exactly what the producer choice rewards.** `next_recruit` picks
        `min(usable, key=queued_units)` to spread orders across buildings, so a barracks placed
        this cycle - queue empty, because nothing in it can start - outranks every finished
        building on the map and keeps outranking them until `QUEUE_TARGET` units are stacked
        behind it. `Recruiting.held` then counts all of them as already coming, so the mix reads
        as satisfied and the finished buildings are left idle. One freshly-placed plot can absorb
        the whole of production this way.

        `under_construction` is the engine's own `ACTIVELY_BEING_CONSTRUCTED`. Health cannot
        stand in for it: a structure ramps its hit points as it builds, so a half-built one is
        indistinguishable from a damaged one by health alone.

        Wreckage is out too, and is not the same state: a destroyed keep stays in the object
        table wearing `RUBBLE`, owned and not under construction, and it sells nothing.
        `stage_heal` already pairs these two checks for the same reason.

        Separate from `structures()` rather than folded into it, because most callers want the
        unfiltered list: a half-built building still occupies its plot, still counts toward map
        control, and is still worth defending.
        """
        return [o for o in self.structures() if not o.under_construction and not o.is_rubble]

    def occupied(self, plot: GameObject, standing: list[GameObject]) -> bool:
        return any(s.distance_to(plot.position) < PLOT_RADIUS for s in standing)

    def is_flag(self, plot: GameObject) -> bool:
        """Whether this build site is an external flag rather than an internal foundation.

        The palette is the discriminator, as it is everywhere else here: a settlement, outpost,
        castle or camp flag carries unpack buttons and a castle foundation carries
        `FOUNDATION_CONSTRUCT` ones. `free_plots` tells them apart the same way and for the same
        reason.

        **The two obey different rules about when they can be built on**, which is the whole
        reason this exists: a flag goes unbuildable for a while after whatever stood on it is
        gone and while something hostile stands on it, and a foundation does neither.
        """
        return bool(self.statics.unpack_buttons(plot.template_name))

    def buildable_sites(self) -> list[GameObject]:
        """The flags on the map whose state is worth watching between cycles.

        **Flags only.** A castle foundation has no rebuild cooldown, so there is nothing about it
        to remember; watching one would fill `_plot_freed` with timestamps nothing ever reads and
        imply a rule that does not exist. Read from `plots_now` rather than from what is owned, so
        a flag razed while somebody else held it is still tracked.
        """
        return [
            o
            for o in self.plots_now()
            if self.statics.is_build_site(o.template_name) and self.is_flag(o)
        ]

    def note_freed_plots(self) -> None:
        """Record the frame each plot lost the thing standing on it. Once per cycle.

        **The transition is the only observable, and nothing was watching for it.** A plot is
        unbuildable for about twelve game seconds after its building goes away, and no field
        reports that: the plot is owned, nothing stands on it, and it reads free on the very next
        cycle. So the bot ordered a replacement immediately, the engine discarded the order in
        silence, and the plot was parked for `PLOT_COOLDOWN` - after which it was tried again, and
        again. Plot 527 was paid for five times in one match this way.

        Watching what *was* occupied and is not any more gives the one timestamp the rule needs.
        A plot built on normally is caught by the same transition when its building later dies,
        and a plot that has always been empty never enters `_plot_held` and so is never rested -
        which is right, because nothing was ever removed from it.

        Called from `decide` beside `remember_keeps` rather than from `free_plots`, because it
        mutates memory and `free_plots` is asked several times a cycle.
        """
        standing = self.structures()
        held = {plot.object_id for plot in self.buildable_sites() if self.occupied(plot, standing)}
        frame = self.observation.frame
        for object_id in self._plot_held - held:
            self._plot_freed[object_id] = frame
        self._plot_held = held

    def resting(self, plot: GameObject) -> bool:
        """Whether this **flag** is still inside the engine's rebuild cooldown.

        Foundations do not have one and are never tracked, so this answers False for every castle
        plot - see `buildable_sites`.

        Answers False for a plot nothing was ever seen standing on, which covers every plot at
        the start of a match and every one this bot has not been watching long enough to have an
        opinion about. That is the safe direction: the cost of trying a plot that turns out to be
        resting is one refused order, and the cost of refusing to try one that was fine is a plot
        the bot never builds on at all.
        """
        freed = self._plot_freed.get(plot.object_id)
        if freed is None:
            return False
        return self.observation.frame - freed < PLOT_REBUILD_SECONDS * self._fps

    def contested(self, plot: GameObject, raiders: list[GameObject] | None = None) -> bool:
        """Whether something hostile is standing close enough to stop a building going up on a flag.

        **The other reason a flag refuses a building, and it stacks with `resting` rather than
        replacing it.** The two are different rules on different clocks: a flag inside its rebuild
        cooldown refuses whatever is standing near it, and a flag with a raider on it refuses
        however long ago the last building died. Both can be true of the same flag at the same
        time, and each has to be asked separately.

        **Flags only, like `resting`.** A castle foundation cannot be contested, so the callers
        that build on one do not ask - see `free_plots`, which asks neither.

        `hostile` and not "anything that is not a building": it already drops wildlife,
        projectiles, spellbook eyes and horde members, all of which stand near plots harmlessly.
        Our own battalions are deliberately not counted - they walk through the base constantly,
        and a party that has just taken a flag is standing on it by definition, so counting them
        would stop the bot building on the settlement it had only this moment captured.
        """
        threat = (
            [o for o in self.observation.objects if self.hostile(o)] if raiders is None else raiders
        )
        return any(o.distance_to(plot.position) < PLOT_CONTESTED for o in threat)

    def free_plots(self) -> list[GameObject]:
        """Owned build plots with nothing standing on them, nearest the base first.

        **Building on a plot does not consume it.** The `GondorBuildingFoundation` object stays
        underneath the finished structure, so a plot appearing in the object table says nothing
        about whether it is available. A bot that assumed otherwise re-ordered onto plot 508 for
        an entire match while its economy sat at one building, reporting each attempt as a
        failed order rather than as a plot that was already taken.

        Occupancy is therefore a proximity test against the buildings actually standing, which
        is also immune to `BuildVariations` - it asks what is there, not what it is called.

        **Every plot owned, not only the ones at home.** This used to keep to `BASE_RADIUS` of
        the base centre, which was a way of saying "an outlying plot belongs to an expansion
        nobody has claimed" - but an unclaimed expansion's plots are not owned in the first
        place, so the filter never did that job. What it did do was throw away the plots a
        claimed camp or castle brings with it, which is most of what claiming one is for.

        The plots it must not offer are the **external** ones, and those are told apart by their
        palette rather than by distance: a settlement or outpost flag is built on with an unpack
        order, which is `stage_expand`'s job, and handing the same flag to `stage_build` has the
        two stages issuing different orders at one plot in the same cycle.

        **Neither the rebuild cooldown nor contested ground is asked here**, and that is a fact
        about foundations rather than an omission: both rules belong to flags, and this list is
        foundations by construction. See `is_flag`.
        """
        anchor = self.base_centre()
        standing = self.structures()
        now = time.monotonic()
        plots = [
            o
            for o in self.observation.mine
            if self.statics.is_build_site(o.template_name)
            and not self.statics.unpack_buttons(o.template_name)
            and not self.occupied(o, standing)
            and self._blocked_plots.get(o.object_id, 0.0) < now
        ]
        return sorted(plots, key=lambda o: o.distance_to(anchor))

    def crates(self) -> list[GameObject]:
        """Every pickup on the map the seat can see, nearest the base first.

        **Picked up by walking over one, not by ordering anything at it.** `SalvageCrate` carries
        a `SalvageCrateCollide`, so the whole interaction is a move order that happens to end on
        top of it - which is also why a crate is `NOT_AUTOACQUIRABLE` and `UNATTACKABLE`, and why
        nothing an army does of its own accord will ever collect one.

        Found by the `CRATE` flag rather than by the fifteen names in `crate.ini`, the same rule
        the rest of this file follows. That covers the ordinary treasure chests, the experience
        chests, the palantír shards and `TheDroppedRing` without naming any of them.

        **Not remembered, unlike the nests and the plots.** A crate is on a `DeletionUpdate` of
        thirty to thirty-five seconds, so a remembered one is a battalion sent to stand where
        something used to be. Where the fog is a reason to keep a lair on the books forever, it is
        a reason to forget a crate immediately.
        """
        anchor = self.base_centre()
        found = [
            o for o in self.observation.objects if self.statics.has_kind(o.template_name, CRATE)
        ]
        return sorted(found, key=lambda o: o.distance_to(anchor))

    def base_plots(self) -> list[GameObject]:
        """Every build plot the starting base has, whether or not something stands on it.

        **`free_plots` with the two filters that make it a to-do list taken off**, because this
        answers a different question: not "where can I build now" but "how much base is there".
        Occupancy is exactly what must not be filtered - a plot with a house on it is still one
        of the base's plots, and a base is not smaller for having been built on.

        **Kept to `BASE_RADIUS`, which `free_plots` deliberately is not.** That method dropped
        the radius so a claimed camp's plots would be offered to `stage_build`, and it is right
        to. Here the radius is the whole point: this is the size of the base the match *dealt*,
        and counting a captured castle's plots into it would make the answer a running total of
        conquest rather than a fact about the opening.
        """
        anchor = self.base_centre()
        return [
            o
            for o in self.observation.mine
            if self.statics.is_build_site(o.template_name)
            and not self.statics.unpack_buttons(o.template_name)
            and o.distance_to(anchor) < BASE_RADIUS
        ]

    def base_capacity(self) -> int:
        """How many plots the starting base has - the largest honest reading so far.

        **A latch, and the latch is the whole design.** The obvious version reads the plots once
        at cycle 1 and keeps the number, and it reads **zero**: `wait_for_match` returns at frame
        0 with the map still spawning, which is the same trap `plot_ghosts` records for the
        claimable flags. Measured live, the bot's own status line sat at `plots 0` for the first
        cycles of both runs of a session before the castle appeared.

        Reading it fresh every cycle is wrong the other way: plots are destroyed and rebuilt, and
        a base under siege would report itself shrinking and re-plan its economy around the
        damage. The high-water mark answers what the base *is* rather than what is left of it.

        Zero until the base exists, which callers must treat as "not known yet" rather than as a
        base with nowhere to build - see `economy_room`, which stands aside while it is zero.
        """
        self._base_capacity = max(self._base_capacity, len(self.base_plots()))
        return self._base_capacity

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

    def charged_cost(self, template: str) -> int:
        """What `template` will actually be charged at, given the buildings standing.

        `Statics.build_cost` quotes the ini price and Edain rarely charges it: a town house takes
        another slice off the faction's elites and off `CPObject` with every copy built, so a
        citadel guard quoted at 600 costs 420 in a base with six. Reading only the quote makes the
        bot refuse recruits it can pay for, and it refuses them at exactly the moment `succession`
        is trying to move the army onto those units.

        **Conservative wherever the data is not certain, because the two errors are not
        symmetrical.** Over-estimating a price costs a delayed order; under-estimating one sends an
        order the logic silently discards, which is the failure `afford` exists to prevent and
        which comes back indistinguishable from a malformed order. So a carrier that cannot be
        seen contributes nothing rather than an assumed discount - which matters for
        `GondorForgeDiscountPing`, whose ladder is real but whose spawn is gated on an upgrade
        rather than on the forge being built, so its presence is not safe to infer from a standing
        forge.

        **And where several ladders apply at once, the least generous wins.** Only ladders with a
        carrier actually standing are considered - an unowned one is at rung zero and would
        otherwise drag every result to no discount at all - but among those the engine's stacking
        rule is unknown, so this takes the smallest markdown rather than guessing that they
        compound.
        """
        return self._marked_down(
            self.statics.build_cost(template), self.statics.ladders_for_template(template)
        )

    def charged_upgrade_cost(self, upgrade: str) -> int:
        """What `upgrade` will actually be charged at - the forge's ladder, on the same rules."""
        return self._marked_down(
            self.statics.upgrade_cost(upgrade), self.statics.ladders_for_upgrade(upgrade)
        )

    def _marked_down(self, quoted: int, ladders: Sequence[CostLadder]) -> int:
        """`quoted` after the applicable ladders, rounded the way a price is rather than down."""
        rates = [
            ladder.rate(len(self.owned_building(ladder.carrier)))
            for ladder in ladders
            if self.owned_building(ladder.carrier)
        ]
        if not rates or quoted <= 0:
            return quoted
        return int(round(quoted * (1 + max(rates))))

    def production_buildings(self) -> list[GameObject]:
        """Owned instances of anything on the plan's production list, variations resolved.

        Deliberately the plan's list rather than "every building that can recruit": this is what
        the build order is measured against, and `producers` is what recruiting is measured
        against. The two differ on purpose - a fortress citadel recruits and is not something
        the plan ever builds.
        """
        return [b for template in self.plan.production for b in self.owned_building(template)]

    def opening(self) -> bool:
        """Whether the build order is still in its opening - no production building yet.

        The whole build order turns on this one fact, so it is read from what is standing
        rather than from a clock: a bot whose builds are failing stays in the opening until it
        actually has a barracks, which is the behaviour that matters. A timer would move on
        without it and then recruit at nothing for the rest of the match.
        """
        return not self.production_buildings()

    def army(self) -> list[GameObject]:
        """Owned fighting objects that an order should be addressed to.

        **Horde containers, never horde members.** A battalion appears in an observation as its
        15 members *plus* the container, and the members are slaved: `HordeAIUpdate` on the
        container is what moves them. Selecting the members and issuing a move produced an
        order the engine recorded and then ignored - the "sometimes recorded but nothing moved"
        symptom. `is_horde_member` reads `HordeContain.InitialPayload` to know which templates
        those are.

        **And slaves, never masters' property.** `is_slaved` is the same relationship one step
        out: a `SlavedUpdate` object is driven by whatever it belongs to, so it takes no orders
        either. Together with `SELECTABLE` that is the whole test, and it was missing - this used
        to accept anything mobile with a body, while its own docstring claimed the tighter rule.
        Measured in one live match, the army it reported was 45 objects of which 21 could not
        fight: 14 `GondorZiviliist`, the civilians an economy building spawns and slaves to
        itself, five `CPObject`, and two banner carriers. Ids run oldest-first, so those sat at
        the *front* of the list, and `detachment` takes the capture squad off the front - the
        squad sent to take the map's last seven settlements was **seven farm civilians**, which
        wandered between the farms and never closed a metre. Every flag was then given up on for
        "the squad was not getting there", which was true and said nothing about the flag. The
        24-battalion push threshold was measured against the same number.

        **The pair costs nothing that should be in.** Across the whole tree, no template any
        command set can recruit is slaved and no hero on any of the seven rosters is - so this
        keeps every battalion, every siege engine and every hero, and a lone hero in no horde
        stays in as it always did. `ARMY_SUMMARY` was tried here first and is worse: it drops
        three small heroes and answers a question about the summary panel rather than about who
        is taking orders.

        Everything else is still classified by `KindOf` so this holds for whatever the plan
        recruits and for the starting roster, without listing a faction's unit templates.

        The count is therefore in *battalions and heroes*, not soldiers.
        """
        return [
            o
            for o in self.observation.mine
            if o.has_body
            and self.statics.has_kind(o.template_name, SELECTABLE)
            and not self.statics.has_kind(o.template_name, *NOT_ARMY)
            and not self.statics.is_horde_member(o.template_name)
            and not self.statics.is_slaved(o.template_name)
        ]

    def role(self, obj: GameObject, *flags: str) -> bool:
        """Whether `obj` fights in one of these roles, asked of the thing that does the fighting.

        **A battalion's own template answers almost nothing.** `GondorKnightHorde` carries no
        `CAVALRY` flag and no weapon - it is a container, and the horse is its payload
        `GondorCavalry`, which carries `CAVALRY`, `INFANTRY` and the weapon that decides matchups.
        Asking the container is how a cavalry mission ends up with no cavalry in it.

        `Statics.fighting_template` is the same horde-to-member step `damage_types` already
        makes, so a lone hero or a siege engine - neither of which is a horde - answers for
        itself.
        """
        return self.statics.has_kind(
            self.statics.fighting_template(obj.template_name) or obj.template_name, *flags
        )

    def role_of(self, template: str) -> str:
        """The **one** role this template fights in - a member of `ROLES`, or `INFANTRY`.

        `role` asks "is this thing any of these", which is the right question when a stage wants
        the archers or wants to know whether a charge is safe. This asks the other one: *which*
        of them is it, so that an army can be counted into buckets that add up to itself. A unit
        counted twice is an army whose shares sum past one, and shares that do not sum to one
        cannot say what the army is short of.

        The order is `ROLES`, and it is doing real work rather than tidying - see there. Asked of
        the fighting member for the reason `role` is: a `GondorKnightHorde` is a container and
        carries none of these flags.

        A template with no fighting member and no flags answers `INFANTRY`, which is the honest
        default: it is the bucket that means "an ordinary body in the line", and a thing nobody
        tagged is far more often that than it is a horse.
        """
        fighting = self.statics.fighting_template(template) or template
        for flag in ROLES:
            if self.statics.has_kind(fighting, flag):
                return flag
        return INFANTRY

    def cavalry(self) -> list[GameObject]:
        """The mounted part of the army. `CAVALRY` before `INFANTRY`, because a horse is both."""
        return [o for o in self.army() if self.role(o, CAVALRY)]

    def heroes(self) -> list[GameObject]:
        """The heroes in the army - the part of it that is worth micromanaging.

        **Asked of the template rather than of the roster**, which is what makes this work on a
        hero nobody bought: a summoned Osgiliath veteran captain and a Ring hero are `HERO` in the
        object table exactly as Beregond is, and neither is in `BuildableHeroesMP`. It also needs
        no faction table, so it answers on a side this bot has never played.

        `role` rather than a flat `KindOf`, for the reason `cavalry` uses it too: a mounted hero
        is a container over its rider on some templates, and the container carries none of the
        flags. Heroes are not hordes, so this is almost always the template answering for itself -
        but "almost always" is where the `GondorKnightHorde` bug came from.
        """
        return [o for o in self.army() if self.role(o, HERO)]

    def can_trample(self, force: list[GameObject], target: GameObject) -> bool:
        """Whether riding this force through `target` would knock it down rather than bounce.

        Three questions, and only the last is this bot's opinion.

        **Does the engine crush it?** `Statics.crushes` is the engine's own comparison -
        `CrusherLevel` strictly greater than `CrushableLevel` - and it is what makes "cavalry
        trample infantry and not each other" true without a unit list: a knight battalion carries
        1, a foot battalion carries 0, and every mounted battalion in the tree carries 2 or more.
        158 of the 161 cavalry battalions in RotWK+Edain are ruled out by that number alone.

        **Every rider, not the party.** `all` rather than `any`, because the order goes to the
        whole selection: one battalion in the party that cannot crush is one battalion walking
        past the enemy for no reason, and its own fight starts late.

        **And is it a fight worth having at all?** The crush arithmetic says the charge lands;
        what makes it a bad trade is the `CrushRevengeWeapon` bill afterwards, which the
        arithmetic knows nothing about. Two tests answer that, and they are an `or` rather than a
        replacement: the `PIKE` flag, asked of the horde *and* of the soldiers inside it because
        the two do not always agree, and `crush_revenge_multiple` against
        `CRUSH_REVENGE_CHARGED`. See those constants - the flag is what actually carries the rule
        on this tree, and the number is what covers a unit nobody tagged.
        """
        if (
            self.role(target, PIKE)
            or self.statics.has_kind(target.template_name, PIKE)
            or self.statics.crush_revenge_multiple(target.template_name) >= CRUSH_REVENGE_CHARGED
        ):
            return False
        return bool(force) and all(
            self.statics.crushes(o.template_name, target.template_name) for o in force
        )

    def queued_units(self, building: GameObject) -> int:
        """Battalions waiting at this building - **not** the upgrades sharing the same queue."""
        return sum(1 for item in building.production if not item.is_upgrade)

    def queued_upgrades(self, building: GameObject) -> int:
        """Upgrades waiting at this building, which is the other half of the same queue."""
        return sum(1 for item in building.production if item.is_upgrade)

    def match_seconds(self) -> float:
        """How long this bot has been playing, in match time rather than wall time.

        Derived from the logic frame counter, which is the only clock the observation carries
        and which the engine advances at a fixed rate regardless of how fast a cycle runs. See
        `_start_frame` for why it is counted from the bot's own first frame.
        """
        return max(0.0, (self.observation.frame - self._start_frame) / self._fps)

    def phase(self) -> int:
        """Which of the army definition's three build phases the match is in.

        The durations are the definition's own `PhaseDuration_Rush` and `_MidGame`, so a faction
        that rushes for longer gets a longer rush here too. Phase 0 for a side with no army
        definition, which is what the fallback staple is recruited under anyway.
        """
        return 0 if self.army_plan is None else self.army_plan.phase(self.match_seconds())

    def enemy(self) -> tuple[int, Vec3] | None:
        """The strongest opponent's index and the centre of their holdings, or None.

        Picks by object count because that is the honest proxy for "who is actually still
        playing" without any static data.

        **Under fog this is a scouting result, not a lookup**, and the centre it returns is the
        centre of what can be *seen* of that opponent - which early on is nothing, so this
        returns None and every caller falls back to whatever it does with no known enemy. That
        is the correct shape for a fogged bot: it has to find the opponent before it can plan
        against them. Without fog it stays the whole-map lookup it always was.
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

    def hostile(self, obj: GameObject) -> bool:
        """Whether `obj` is something of theirs that this army could actually fight.

        The seven tests are not interchangeable and dropping any one of them was a real bug: not
        ours and not neutral, a body to damage, mobile rather than a structure, **fightable at
        all**, **willing to fight back**, **standing rather than in flight**, and addressed as a
        battalion rather than as one of its soldiers.

        `UNTOUCHABLE` is the one a spellbook eye slips past - it takes no damage from anything.
        `HARMLESS` is the one the map's wildlife slips past, and that one decided whole matches:
        a fish is not a raider, and while the bot thought it was, nothing but defence ran.
        `IN_FLIGHT` is the one ammunition slips past: a crossbow bolt is enemy-owned and carries
        an `ActiveBody`, so a measured run counted six of them as an attacking force and sent
        five battalions to fight them.

        The last is `is_horde_member`, and it is what makes every count taken over this list
        mean something. A battalion arrives as its fifteen soldiers plus a container, so
        counting soldiers put a single enemy battalion on a flag at sixteen defenders against a
        squad of three - a comparison `worth_taking` could never pass, whatever the odds really
        were. `army` has always counted containers; now both sides of the comparison do.

        **And the civilian seat is out entirely, which is the one test here that is about who
        owns a thing rather than about what it is.** Every other exclusion reads a `KindOf`, and
        that is precisely why they cannot be relied on alone: a flag the tree does not define
        resolves to *no* flags at all, so `STRUCTURE`, `IMMOBILE`, `HARMLESS` and the rest all
        fail open and the object reads as a mobile living thing. Measured live on an Edain map,
        the complete list of civilian-owned objects this predicate accepted was three `Crow` -
        whose `KindOf` is written out longhand and drops the `INERT` every other animal inherits
        from `NATUREUNITS_KINDOF` - and one `Mirkwood_Vinecellar1`, a map-local object resolving
        to an empty kind set. A battalion spent ten minutes of a push trying to attack a bird it
        could not hit, and the order was refused every cycle without ever being given up on.

        **`PlyrCreeps` stays hostile, and the split is the whole point.** Lairs and the slaves
        they keep replacing are what a flag has to be cleared of, and they are the creeps' - the
        same match had a `WargLair` and its `NeutralWarg` both on that seat. The civilians own
        scenery, wildlife and map furniture, and none of it is ever worth an order. See `wild`,
        which deliberately answers True for both because "is this the engine's" and "is this
        something to fight" are different questions.
        """
        return (
            self.not_ours(obj)
            and not self.civilian(obj)
            and obj.has_body
            and not self.statics.has_kind(obj.template_name, "STRUCTURE", "IMMOBILE")
            and not self.statics.has_kind(obj.template_name, *UNTOUCHABLE)
            and not self.statics.has_kind(obj.template_name, *HARMLESS)
            and not self.statics.has_kind(obj.template_name, *IN_FLIGHT)
            and not self.statics.is_horde_member(obj.template_name)
        )

    def civilian(self, obj: GameObject) -> bool:
        """Whether `obj` belongs to the map's civilian seat - scenery, wildlife, furniture.

        **Read off the seat's name, which is the one name test in this file that is safe.** The
        codebase avoids matching template names because a mod renames templates freely; the
        non-playing seats are engine fixtures, spelled `PlyrCivilian` and `PlyrCreeps` in every
        match observed. Nothing else distinguishes them: both report a `Civilian` faction and
        both answer False to `playing`, so `wild` cannot tell them apart and does not try.

        False when the seat cannot be read at all, which keeps this from quietly disarming the
        bot against a player whose entry is missing.
        """
        owner = obj.owner_index
        if owner is None:
            return False
        player = self.observation.player(owner)
        return player is not None and player.name == CIVILIAN_SEAT

    def not_ours(self, obj: GameObject) -> bool:
        """Whether `obj` belongs to somebody else - falling back to `Side` when nobody can be read.

        **`owner_index is None` does not mean "nobody", it means "not resolvable".** An object
        names its owner by `Team*` and `_team_owners` inverts each player's *primary* team, so
        anything on a script team - which is what a superweapon's summons are - comes back
        unresolved. Treating that as neutral is what this fixes, and it was not a small hole:
        measured live at frame 21697, the `None` bucket held **an entire Isengard attacking
        force** - 18 `IsengardFighter`, 15 `IsengardUrukCrossbow`, 7 `IsengardWargRider`, a
        ballista and their hordes - standing in CLEAR cells, present in the fogged view, and
        invisible to every decision that asks `hostile`. A crossbow battalion shot a farm down
        while the bot read it as belonging to no one.

        **The fallback is the template's declared `Side`, and only where the owner is missing.**
        `Side` is emphatically not the owner in general - the creeps own `Neutral` templates and
        the local player owned a `Civilian` one in a measured match, which is why `owned_by`
        exists and why nothing else here reads it. But for an object whose owner cannot be read
        at all it is the only signal there is, and it is the right one for exactly this case: the
        summoned battalion carries `Isengard` and our own five unresolved `CPObject`s do not.

        An unresolved object whose `Side` is blank stays ours-by-default rather than becoming an
        enemy, because the cost of that mistake is the army attacking its own command-point
        objects.
        """
        if obj.owner_index is not None:
            return obj.owner_index != self.session.player_index
        side = (obj.template_side or "").lower()
        return bool(side) and side != self.side.lower()

    def wild(self, obj: GameObject) -> bool:
        """Whether `obj` belongs to a seat the engine runs itself - the creeps or the civilians.

        Not the same question as "is it an enemy". A live skirmish carries `PlyrCivilian` and
        `PlyrCreeps` alongside the real players and both report a `Civilian` faction, so
        `Observation.opponents` correctly leaves them out - and the lairs, the map's animals and
        every unclaimed flag are theirs. Anything that has to tell a creep camp from an
        opponent's farm has to ask this rather than ask who is playing.
        """
        if obj.owner_index in (self.session.player_index, None):
            return False
        player = self.observation.player(obj.owner_index)
        return player is not None and not player.playing

    def is_lair(self, obj: GameObject) -> bool:
        """Whether `obj` is a creep lair - a structure that garrisons itself for ever.

        Two facts together, because neither alone is enough. `Statics.spawns` finds the
        `SpawnBehavior`, which is what makes the defenders around it a tap rather than a force -
        but plenty of ordinary buildings spawn something, a farm its workers and a tower its
        garrison, so on its own it would point six battalions at an opponent's farm. `wild` is
        the other half: this belongs to the seat the engine plays creeps with.

        No name list and no `KindOf` of its own: `DunlandGoblinLair` and `WargLair` carry
        exactly the flags any structure carries, and the lairs across the tree share no naming
        convention worth matching on.
        """
        return (
            self.wild(obj)
            and self.statics.has_kind(obj.template_name, "STRUCTURE")
            and bool(self.statics.spawns(obj.template_name))
        )

    def nests_visible(self) -> list[GameObject]:
        """The nests the seat can see right now - what `remember_nests` writes its memory from.

        Two kinds, and clearing one means clearing both in order. A **lair** replaces every
        defender killed near it, so the fight for the flag it guards cannot be won by winning
        it. A **hole** is what the lair leaves behind, and it rebuilds the lair a couple of
        minutes later - so a raid that stops at the lair has bought two minutes.

        The hole is deliberately not filtered to the creep seat: an opponent's razed building
        leaves one too, and it rebuilds for them exactly the same way.

        **The live reading only.** This was `nests` itself, and being live was the whole of what
        was wrong with it - see `nests`.
        """
        return [
            o
            for o in self.observation.objects
            if o.owner_index not in (self.session.player_index, None)
            and o.has_body
            and not self.statics.has_kind(o.template_name, *UNTOUCHABLE)
            and (self.statics.is_rebuild_hole(o.template_name) or self.is_lair(o))
        ]

    def remember_nests(self) -> None:
        """Record every nest while it can be seen, and forget the ones proved gone.

        **The same memory as `remember_keeps`, written for the same reason.** A nest does not
        move, so a position once seen stays true; the fogged view simply has no way of saying so.

        Forgetting needs the army standing there, exactly as it does for a keep: absence from
        the fogged view is ordinarily distance, and dropping a nest for being out of sight is how
        the list emptied itself in the first place. Within `NEST_GONE` the reading means the
        opposite - something of ours is on top of the place and can see it, and it is not there.

        **`NEST_GONE` rather than the `PUSH_ARRIVED` this first used, and the 400 was a bug.**
        It is wider than a unit's vision, so a battalion walking past a fogged lair at 350 was
        deleting it - "near it and not seeing it" is the ordinary state of moving through the
        dark, not evidence. Measured live across two runs, the `nests` column fell 2 -> 0 and
        4 -> 1 on maps where nothing had been destroyed, and a lair hole was abandoned
        undestroyed because it had been forgotten rather than because anything gave up on it.

        That rule is also what retires a razed lair. The party that knocks one down is standing
        on it, so the lair goes on the cycle it dies and the hole underneath it is picked up as a
        new object in the same breath.
        """
        visible = {o.object_id: o for o in self.nests_visible()}
        self._seen_nests.update(visible)
        army = self.army()
        if not army:
            return
        for object_id, nest in list(self._seen_nests.items()):
            if object_id in visible:
                continue
            if any(o.distance_to(nest.position) < NEST_GONE for o in army):
                del self._seen_nests[object_id]

    def nests(self) -> list[GameObject]:
        """Everything on the map that will keep re-arming until it is knocked down, remembered.

        **Live where the seat can see it, remembered everywhere else**, which is the same
        arrangement `plots_now` uses and for the same reason: where a building is does not change
        when the fog closes over it.

        **This read the observation directly and nothing else, and that quietly cost the map.**
        A nest was a target only on the cycles something of ours happened to be looking at it, so
        the list emptied every time the army turned round. Measured live: the `nests` column read
        21 at cycle 4, 2 at cycle 14, and 0 for most of the rest of a match on a map still
        covered in lairs.

        **The rebuild hole is the case that made it a bug rather than a limitation.** A hole
        exists only once its lair is down - the one moment the force is guaranteed to be standing
        on top of it - and `RebuildHoleBehavior` raises the lair again two minutes later. Read
        live, the hole left the target list with the party that made it and the lair came back
        untouched, so razing one bought exactly the two minutes the module docstring warns about.
        Remembered, the hole stays a target until something of ours is standing where it was and
        can see it is gone.

        These are the targets that make a map a thing that can be taken rather than a thing to
        be walked around, and they are also the answer to "what does an army do in a match with
        no opponent" - see `raid_target` and `push_target`.
        """
        return list(self._seen_nests.values())

    def garrison_of(self, flag: GameObject) -> GameObject | None:
        """The nest that keeps `flag` defended, or None if nothing does.

        **The hole first where there is one**, because a hole only exists once its lair is
        already down: finishing it is what makes that kill permanent, and it is a 500-point
        target rather than a 2000-point one. Otherwise the nearest lair within `LAIR_RADIUS`,
        which is the range its slaves keep to.
        """
        near = [o for o in self.nests() if o.distance_to(flag.position) < LAIR_RADIUS]
        holes = [o for o in near if self.statics.is_rebuild_hole(o.template_name)]
        pool = holes or near
        return min(pool, key=lambda o: o.distance_to(flag.position), default=None)

    def raiders(self) -> list[GameObject]:
        """Enemy fighting units inside our base.

        Anything mobile, damageable and hostile standing close to home. Deliberately broader
        than `opponents`: map creeps are `Civilian` and so are filtered out of that list, but
        they will happily kill a porter.

        **What counts as a raider decides far more than defence**, so two things wrongly in it
        each cost a match. `EyeOfSauron` is `UNATTACKABLE` and drifts over the base, and the
        whole army was ordered to attack a thing that takes no damage. The map's wildlife is
        `INERT` and grazes, and a goat was read as an assault. Both are answered by `hostile`
        now, and `besieged` answers the rest: this being non-empty no longer switches the other
        stages off, only a force larger than the spare battalions does.
        """
        home = self.base_centre()
        return [
            o
            for o in self.observation.objects
            if self.hostile(o) and o.distance_to(home) < DEFEND_RADIUS
        ]

    def threats(self) -> list[tuple[GameObject | None, list[GameObject]]]:
        """Every place of ours with enemies on it, and who is on it - worst first.

        **A map is not one place, and answering it as one place is what the army was doing
        wrong.** Everything used to be measured against `base_centre`: enemies near home were a
        raid to meet and enemies anywhere else were somebody else's problem, so two orcs burning
        a settlement farm on the far side of the map were invisible until they had finished and
        walked home. Meanwhile the whole force walked to the next flag together, because there
        was no other shape available to it.

        So each **holding** is asked separately - the base first, then every building standing
        away from it, which is what a captured settlement is. A holding with hostiles near it is a
        threat, and it is answered by a group sized to that threat rather than by the army.

        Ranked by what a loss would cost, not by distance. The base leads because losing it ends
        the match; after it the count of attackers, because that is what tells a farm being
        wandered past from a farm being taken. `None` is the base's stand-in - it is a centre
        rather than a building, and the building the mean is taken over may already be rubble.

        Duplicates are impossible by construction: a hostile is assigned to the nearest holding
        it threatens, so two farms side by side do not each demand their own group for the same
        orcs.
        """
        home = self.base_centre()
        # The base counts as one holding wherever its buildings happen to stand, so the ones
        # inside it are not offered separately - answering each farm in the castle individually
        # is how one assault becomes six groups. Taken from a single `structures()` reading and
        # compared by distance rather than by membership: each call builds fresh `GameObject`s,
        # so an `in` test against a second reading is an identity test that never matches.
        holdings: list[tuple[GameObject | None, Vec3]] = [(None, home)]
        holdings += [
            (o, o.position) for o in self.structures() if o.distance_to(home) >= BASE_RADIUS
        ]
        found: dict[int, tuple[GameObject | None, list[GameObject]]] = {}
        for obj in self.observation.objects:
            if not self.hostile(obj):
                continue
            reach = [
                (holding, where)
                for holding, where in holdings
                if obj.distance_to(where) < (DEFEND_RADIUS if holding is None else HOLDING_RADIUS)
            ]
            if not reach:
                continue
            holding, _ = min(reach, key=lambda pair: obj.distance_to(pair[1]))
            key = 0 if holding is None else holding.object_id
            found.setdefault(key, (holding, []))[1].append(obj)
        return sorted(found.values(), key=lambda pair: (pair[0] is not None, -len(pair[1])))

    def plot_ghosts(self) -> dict[int, GameObject]:
        """Every claimable plot on the map by object id, accumulated through the fog.

        **Read unfogged, for placement only.** A settlement plot is drawn as a ghost from the
        first frame - the game shows every one of them to every player before anybody has scouted
        anything - so where the plots *are* is not information fog was ever hiding. Reading it
        from the filtered snapshot instead was strictly worse than what a human is given, and it
        failed silently: `under_fog` documents that it keeps no memory of what was seen before, so
        a plot did not merely start hidden, it went back to being hidden every time the army
        looked away. A run measured `flags 0` on every cycle of a whole match, which left
        `stage_expand` with nothing to claim and the opening's army standing still.

        **Placement only.** What is *on* a plot - who owns it, whether something is standing there
        - is live state that fog is entitled to hide, and that half is not answered here:
        `plots_now` overlays whatever the current observation can actually see. So the bot knows
        where to walk, exactly like a player reading the ghosts, and still has to arrive to find
        out who got there first.

        **A union across cycles, not one look, and that is a repair of a silent half-blindness.**
        This used to cache the first *non-empty* reading, which guards against a census taken
        before the map has spawned anything - but not against one taken while it is still
        spawning, which is a different thing and reads as success. Since the bot began attaching
        at the menu it arrives at frame 0 and catches exactly that: two plots had spawned and
        fourteen had not, so it remembered two for the whole match. Measured live against a
        running game - the unfogged snapshot held **16** claimable plots (12 settlements, 2
        outposts, 2 fortress plots) while the bot reported `flags 1` - across two matches whose
        ledgers read `unpack never did anything`.

        Merging instead of replacing is safe because this is placement: a plot does not move and
        is not destroyed, so the union only ever grows and settles once the map finishes
        spawning. It costs one walk of the unfogged object list per cycle, which is what the
        first version was avoiding - and half a map's expansions is not a price worth paying for
        it.
        """
        whole = self.session.latest_unfogged or self.observation
        found = {
            o.object_id: o for o in whole.objects if self.statics.unpack_buttons(o.template_name)
        }
        if self._ghosts is None:
            self._ghosts = {}
        # New ids only. An id already censused keeps its original ghost, so a plot the seat can
        # no longer see does not get overwritten by a later, emptier reading of the same frame -
        # the placement was right the first time, and `plots_now` is what refreshes state.
        for object_id, ghost in found.items():
            self._ghosts.setdefault(object_id, ghost)
        return self._ghosts

    def plots_now(self) -> list[GameObject]:
        """The censused plots, each as freshly as it can honestly be read.

        A plot the seat can see now comes from the live observation, so its owner and occupancy
        are current. One it cannot see falls back to the ghost, which is the frame-0 reading -
        unclaimed, because that is what it was and the bot has no way to know otherwise. Marching
        to a plot the opponent quietly took is therefore possible, and it is the same mistake the
        ghost invites a human into.
        """
        live = {o.object_id: o for o in self.observation.objects}
        return [live.get(object_id, ghost) for object_id, ghost in self.plot_ghosts().items()]

    def map_flags(self) -> list[GameObject]:
        """Every claimable plot on the map, whoever holds it and whatever stands on it.

        The denominator of `map_control`, and deliberately a wider census than
        `external_plots`: that one answers "where could the force go next" and so drops the flags
        already built on, which are exactly the ones that count as taken. Found by the same
        palette test everything else here uses, so it covers settlements, outposts, castles and
        camps without a name list.

        A castle plot inside a base is **not** one of these. `free_plots` tells them apart by
        the same rule - an internal foundation carries `FOUNDATION_CONSTRUCT` buttons and no
        unpack button at all - so the denominator is the contested map rather than our own base.

        **A fixed denominator, which is what makes `map_control` a score at all.** Counting only
        the visible flags had it dividing by zero-or-nearly under fog and reporting `map 100%` -
        "a map with nothing to take is a map already controlled" - for a bot that had taken
        nothing and could see nothing.
        """
        return self.plots_now()

    def map_control(self) -> float:
        """The share of the map's flags that are ours, 0.0 to 1.0.

        Ours two ways, because claiming and building are two steps and both count: the flag
        reads as owned, or something of ours is standing on it. Reading only the first misses
        every settlement already built on - `owner_index` goes to `None` once a base stands
        there, which `external_plots` documents as "occupied, not free" - and that is most of
        what a bot late in a match has actually taken.

        1.0 when the map carries no claimable flag at all, which is not a special case to guard
        against: a map with nothing to take is a map already controlled.

        **One thing branches on this, and only in company.** Two versions of this file made it a
        decision on its own - commit the army at three flags in four, and commit anyway after
        sixty cycles of no progress - and both answered the wrong question. Map control is the
        score, so a threshold on it alone is a rule about when to stop playing for the score: the
        run that took one gave up expanding at 38% and was beaten inside two hundred cycles, where
        the run before it kept expanding at the same 38% and was never beaten at all.

        `Warfare.pushing` reads it at `PUSH_CONTROL`, and what makes that different is the second
        gate beside it. 38% is a bot with most of a map still to take; 85% *with the army against
        its own command-point ceiling* is a bot that has run out of both map and army, which is a
        different state that happens to share a number's units. See `PUSH_CONTROL`.
        """
        flags = self.map_flags()
        if not flags:
            return 1.0
        standing = self.structures()
        mine = self.session.player_index
        held = sum(1 for flag in flags if flag.owner_index == mine or self.occupied(flag, standing))
        return held / len(flags)

    def external_plots(self) -> list[GameObject]:
        """Claimable plots outside the base - settlements, outposts, castles, camps - nearest
        first.

        Found by asking each object whether its *unclaimed* command set offers an unpack
        button, never by matching a template name. That is what makes this one method cover
        all four families across every faction: the names give nothing away (Edain's settlement
        is `WirtschaftPlotFlag_Real`, "Wirtschaft" being economy), and the previous version
        named the settlement alone and walked past every outpost, castle and camp on the map.

        **A plot we already own stays on this list until something stands on it.** Claiming and
        unpacking are two steps and only the first happens by walking, so dropping a plot the
        moment `owner_index` flips strands it: the force captures a flag, the flag leaves the
        candidate list, and the order that would have built on it is never reached. That is a
        capture the bot pays for and never collects, and it is silent - the flag is genuinely
        ours, so nothing looks wrong. Occupancy is the test that ends the job, exactly as in
        `free_plots`, because building on a plot does not consume it.

        One exclusion: **`owner_index is None`** marks an occupied plot, one an existing base
        stands on. A free plot reads as the civilian player instead. This is not "unowned", it
        is "taken", and a force parked 43-64 units off one for 90 seconds never moved it.

        `free_plots` deliberately does not find these: it filters to plots near the base, which
        is exactly what an external plot is not.

        The candidates come from `plots_now`, so under fog this still offers the plots the seat
        cannot currently see - their placement was read once from the ghosts, which is what a
        player has too. Only their *state* is stale, and walking there is how that gets settled.
        """
        anchor = self.base_centre()
        standing = self.structures()
        found = [
            o
            for o in self.plots_now()
            if o.owner_index is not OCCUPIED and not self.occupied(o, standing)
        ]
        return sorted(found, key=lambda o: o.distance_to(anchor))

    def defenders(self, flag: GameObject) -> list[GameObject]:
        """Enemy fighters close enough to a flag to deny it, in battalions.

        `NO_BASE_CAPTURE` is the engine's own answer to "does this thing deny a capture", so it
        is what decides rather than a judgement about which templates can fight. `hostile` has
        already dropped the map's wildlife and every horde member, which is what makes the count
        comparable with the force's - see `worth_taking`.
        """
        return [
            o
            for o in self.observation.objects
            if self.hostile(o)
            and not self.statics.has_kind(o.template_name, NO_BASE_CAPTURE)
            and o.distance_to(flag.position) < CONTEST_RADIUS
        ]

    def enemy_structures(self) -> list[GameObject]:
        """Every opponent building an order could actually damage.

        Plots are out because a plot is not a building - it is where one goes, and it belongs to
        whoever holds it whether or not anything stands there. `UNTOUCHABLE` is out for the
        reason that constant records: a thing that takes no damage is not a target however
        enemy-owned it is.
        """
        return [
            structure
            for p in self.observation.opponents
            for structure in self.observation.owned_by(p.index)
            if self.statics.has_kind(structure.template_name, "STRUCTURE")
            and not self.statics.is_build_site(structure.template_name)
            and not self.statics.has_kind(structure.template_name, *UNTOUCHABLE)
        ]

    def victory_targets(self) -> list[GameObject]:
        """Their buildings whose destruction is what actually ends the match, if any are visible.

        **The same flag `finished` counts, from the other side.** A player is beaten when they
        hold nothing carrying `MP_COUNT_FOR_VICTORY`, so this is the whole of what an attack has
        to get through - and everything else on the map is a step toward reaching it rather than
        a way of winning.

        **Built on `enemy_structures` rather than on `hostile`, and that is the correction.**
        `raid_target` asked for `hostile(o) and counts_for_victory(o)` and could never get an
        answer: `hostile` excludes anything `STRUCTURE` or `IMMOBILE`, and checked against the
        game's own data, **573 of the 574 templates carrying `MP_COUNT_FOR_VICTORY` are
        structures** - the one that is not is `testherohacksreal`, a debug template. So that
        intersection was empty by construction and the branch behind it was unreachable code.
        It is the reason a run could raze every lair, hold 94% of the map with a full army and
        105,012 gold, and never once attack anything that could end the match.

        `enemy_structures` also drops the two things that are enemy-owned and still not targets:
        `UNTOUCHABLE`, and build sites - a foundation carries `MP_COUNT_FOR_VICTORY` and an
        `ImmortalBody`, so it counts toward their survival and cannot be attacked out of the way.
        That asymmetry is real and is why taking the map is not the same as winning it.
        """
        return [
            structure
            for structure in self.enemy_structures()
            if self.statics.counts_for_victory(structure.template_name)
        ]

    def command_fill(self) -> float:
        """How full the army is against its own ceiling, 0.0 to 1.0.

        **The answerable form of "am I strong enough".** A battalion count is not - what it takes
        to win depends on the opponent, and the number is spent as fast as it is built. This asks
        a smaller question with an exact answer: is the army as large as this player is allowed to
        make it. At the ceiling, waiting builds nothing, and the gold has nowhere to go.

        1.0 when the cap reads zero, which is a cap that has not loaded rather than an army with
        no room - reporting "empty" there would hold a push open forever on a reading that means
        nothing.
        """
        me = self.observation.me
        if me is None:
            return 0.0
        used, cap = me.command_points
        return 1.0 if cap <= 0 else min(1.0, used / cap)

    def enemy_expansions(self) -> list[GameObject]:
        """Opponent buildings standing on an external plot - their settlements and outposts.

        **This is how an enemy-held plot becomes takeable again.** `external_plots` will not
        offer one, and correctly: something is standing on it, so there is nothing to unpack.
        The flag underneath is not consumed by the building on it though - the same fact
        `free_plots` turns on - so destroying the building puts the plot back on the list and
        the capture squad picks it up on a later cycle.

        Found by standing rather than by name: any structure of theirs sitting within a plot's
        radius of a flag is on that flag, whatever either is called.
        """
        flags = [
            o for o in self.observation.objects if self.statics.unpack_buttons(o.template_name)
        ]
        if not flags:
            return []
        return [
            structure
            for structure in self.enemy_structures()
            if any(structure.distance_to(f.position) < PLOT_RADIUS for f in flags)
        ]

    def reclaim_targets(self) -> list[GameObject]:
        """Enemy buildings standing on ground that is this bot's to take back, nearest first.

        **Taking a map and holding one are different jobs, and only the first had a stage.**
        `stage_expand` walks to flags nobody has built on and `push_target` walks at whatever
        counts for victory; between them, a settlement the opponent took - or took *back* - is
        invisible. It is not a free flag, because a building stands on it; it is not usually a
        victory target, because an economy building is explicitly `IGNORE_FOR_VICTORY`. So a
        map could be conquered flag by flag and then quietly conquered back, with every stage
        reporting success the whole way.

        Two kinds of ground qualify, and both are answers to "is this mine to recover" rather
        than to "is this reachable":

        - **a plot on our side of the map.** An expansion nearer this base than the opponent's
          own centre is ground they took from in front of us, and razing the building puts the
          flag straight back on `external_plots` for the capture squad. One nearer *their*
          centre is their expansion in their half, which is `stage_raid`'s ordinary business and
          not a recovery.
        - **anything of theirs inside `BASE_RADIUS` of home.** A building in our own base is not
          an expansion to contest, it is a foothold, and it is worth breaking whether or not it
          happens to sit on a flag.

        A structure can qualify both ways, so they are merged by id rather than concatenated.
        """
        home = self.base_centre()
        seat = self.enemy()
        centre = seat[1] if seat is not None else None
        taken = {
            o.object_id: o
            for o in self.enemy_expansions()
            if centre is None or o.distance_to(home) < o.distance_to(centre)
        }
        for structure in self.enemy_structures():
            if structure.distance_to(home) < BASE_RADIUS:
                taken[structure.object_id] = structure
        return sorted(taken.values(), key=lambda o: o.distance_to(home))

    def held_by(self, obj: GameObject) -> set[str]:
        """Every upgrade that applies to `obj` - the player's own plus the object's, lowercased.

        The two scopes are separate fields on a live observation and a command set may turn on
        either: a faction tech lands on the player, a building's level on the building. Reading
        one of the two is how a levelled barracks reads as unlevelled.
        """
        me = self.observation.me
        held = {u.lower() for u in (me.upgrades if me is not None else ())}
        return held | {u.lower() for u in obj.upgrades}

    def enemy_army(self) -> dict[str, int]:
        """What the opponents actually have standing, by template - the thing to counter.

        Battalions rather than soldiers, because `hostile` already drops horde members, and
        because a share of an army only means anything if both sides are counted the same way.
        Structures are out for the same reason they are out of `army`: a plan for beating a
        farm is not a plan for beating an army.

        **What this counts is what can be seen.** Without fog that is a census of their whole
        army, which is the privilege the module docstring states. Under fog it is a sighting
        report: battalions that nothing of ours is watching are simply absent, so a counter
        built on this reacts to what has been scouted and not to what exists. Neither reading
        needs a different call - `Observation.fogged` says which one you are holding.
        """
        counts: dict[str, int] = {}
        for obj in self.observation.objects:
            if not self.hostile(obj) or self.wild(obj):
                continue
            key = obj.template_name.lower()
            counts[key] = counts.get(key, 0) + 1
        return counts

    def _holdings(self, index: int, observation: Observation | None = None) -> list[GameObject]:
        """A player's objects that count toward the engine's multiplayer defeat check.

        `MP_COUNT_FOR_VICTORY` is the engine's own flag for this. Counting all objects instead
        would keep a beaten player alive on their economy buildings, which carry
        `IGNORE_FOR_VICTORY` precisely so they do not count.

        Counts against `observation` when one is passed, so that the caller deciding whether the
        match is over can ask it of the unfogged snapshot while every tactical caller keeps the
        filtered one. See `Bot.finished`.
        """
        obs = self.observation if observation is None else observation
        return [o for o in obs.owned_by(index) if self.statics.counts_for_victory(o.template_name)]
