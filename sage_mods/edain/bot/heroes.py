"""Buying a hero, keeping it alive, and spending the kit it was bought for.

**A hero is the one unit in this bot's army that cannot be played as a battalion.** Everything
above this file treats the army as interchangeable bodies - a party is "four of whatever was
spare", a response group is "slightly more than the threat", and both are right, because a
battalion is 200 gold and its job is to be somewhere. A hero is 1300 to 4000 gold and 30 to 60
command points, it does not come back when it dies (it goes to the tail of the revive list and
has to be bought again), and most of what it is worth sits behind buttons nobody was pressing.

So this is three stages rather than one, and they are deliberately independent:

- **`stage_hero_recruit`** buys the plan's hero out of surplus. Without it the other two never
  run, because nothing else in the bot recruits a hero at all: `producers` reads `UNIT_BUILD`
  buttons and every hero in the game is behind a `REVIVE` one, in an index space of its own
  (`sage_live.utils.heroes`).
- **`stage_hero`** decides where the hero stands: retreating if it is hurt, and otherwise with
  the friendly force nearest to it. It is an escort rather than a target list on purpose - see
  `hero_escort`.
- **`stage_hero_cast`** fires one ability. `Statics.hero_powers` is what makes that possible
  without a table of hero names, and the level gate is the hero's own `Upgrade_Level_N`.

**What is deliberately not here.** No hero-specific target list: a hero sent hunting is one
expensive object against whatever it finds, which is how a purchase worth six battalions dies to
four orcs. No stance orders - `SET_STANCE` buttons exist on every hero command set and
`sage_live.api.orders` has no constructor for them, so that is a lever this cannot pull yet. No
mount toggling: `TOGGLE_IMAGE_ON_WEAPONSET` is filtered out of the ability list precisely because
firing it blind would put Gandalf back on foot.
"""

from __future__ import annotations

import time
from collections.abc import Callable

from sage_live.api.observation import GameObject, Observation, Vec3, distance
from sage_live.api.orders import CAST_OBJECT, CAST_SELF
from sage_live.api.session import BUILD_CONFIRM, Sent
from sage_live.utils.statics import (
    EFFECT_BUFF,
    EFFECT_HEAL,
    EFFECT_SELF_BUFF,
    EFFECT_STRIKE,
    EFFECT_SUMMON,
    CastablePower,
)
from sage_mods.edain.bot.tuning import (
    HERO_CAST_TARGETS,
    HERO_ESCORT,
    HERO_FLOOR,
    HERO_HEAL_TARGETS,
    HERO_HEAL_THRESHOLD,
    HERO_PURPOSE,
    HERO_REORDER,
    HERO_RETREAT,
    HERO_RETURN,
    QUEUE_TARGET,
    SUMMONED,
)
from sage_mods.edain.bot.warfare import Warfare

__all__ = ["HERO_AIMABLE", "Heroes"]

# The effects a hero ability can be aimed. `EFFECT_BUILD` is absent because no hero on any roster
# measured places a structure, and `EFFECT_GRANT` and `EFFECT_UNKNOWN` are the data declining to
# say what a power does - which for a hero is a large minority of the buttons and is reported
# rather than guessed at. Measured over the Men roster: 21 of 40 ability buttons land outside this
# tuple, Boromir's Last Stand and Gandalf's Lightning Sword among them.
HERO_AIMABLE = (EFFECT_SELF_BUFF, EFFECT_BUFF, EFFECT_HEAL, EFFECT_STRIKE, EFFECT_SUMMON)


def _centre_of(force: list[GameObject]) -> Vec3:
    """The mean position of a force - where the hero should be standing to be with it."""
    return (
        sum(o.position[0] for o in force) / len(force),
        sum(o.position[1] for o in force) / len(force),
        sum(o.position[2] for o in force) / len(force),
    )


class Heroes(Warfare):
    """The hero mission: buying one, keeping it alive, and firing what it holds."""

    def hero_powers(self, hero: GameObject) -> tuple[CastablePower, ...]:
        """Every ability this hero's command set offers, cached per template.

        A pure read over data that cannot change during a match, and an expensive one - it walks
        a command set, every button on it and every module on the object and its parents - so it
        is cached the way `spell_book` is read once at startup. Keyed by template because that is
        what the answer depends on; the hero's *level* is applied per cycle by `hero_ready_powers`
        against the live object.
        """
        key = hero.template_name.lower()
        if key not in self._hero_powers:
            self._hero_powers[key] = self.statics.hero_powers(hero.template_name)
        return self._hero_powers[key]

    def hero_ready_powers(self, hero: GameObject) -> list[CastablePower]:
        """The abilities this hero could fire this cycle, longest recharge first.

        Four filters, and each is the data or the engine saying no rather than a rule here: an
        effect nothing can aim, a level not yet reached, a recharge still running, and an ability
        benched for failing three times.

        **The level gate is a live set test and needs no experience counter.** Every ability
        starts paused and is opened by an `UnpauseSpecialPowerUpgrade` naming `Upgrade_Level_N`,
        which is OBJECT-scoped and therefore lands in the hero's own `GameObject.upgrades` -
        exactly what `held_by` already reads for a levelled barracks. That also means it is right
        for a hero that levelled before this process attached, which a counter could not be.

        Ordered by recharge like `castable_powers`, and for the same reason: the ability that has
        been waiting longest to be worth something is the one to spend now.
        """
        held = self.held_by(hero)
        options = [
            power
            for power in self.hero_powers(hero)
            if power.castable
            and power.effect in HERO_AIMABLE
            and power.unlocked_for(held)
            and self.ready(power, caster=hero.object_id, key=self.hero_key(hero, power))
            and not self._cold(f"hero:{self.hero_key(hero, power)}")
        ]
        options.sort(key=lambda power: -power.reload_seconds)
        return options

    @staticmethod
    def hero_key(hero: GameObject, power: CastablePower) -> str:
        """The clock key for one hero's copy of one ability.

        **A power name is not unique across casters and two of the collisions are real.**
        `SpecialAbilityAragornBladeMaster` is on Boromir and on Aragorn, and every hero in the
        game carries `SpecialAbilityCaptureBuilding` - so a clock keyed by name alone has one
        hero's cast silencing another hero's ability for its whole recharge. The object id is
        also the right identity for the *engine's* clock, which is kept per casting object.
        """
        return f"{hero.object_id}:{power.power}"

    #
    # Recruiting. Nothing else in the bot buys a hero: `producers` reads `UNIT_BUILD` buttons and
    # heroes sit behind `REVIVE` ones, addressed by a position in the player's revive list rather
    # than by template - see `sage_live.utils.heroes` for the index space and what it cost to
    # identify.

    def hero_producer(self, hero: str) -> GameObject | None:
        """An owned building whose control bar would actually offer `hero`, or None.

        **The engine's revive gate is broken in a way that makes this the bot's problem.**
        `BuildAssistant::canMakeUnit` matches a slot by counting `REVIVE` buttons and never reads
        the button it matched, so it will happily build a hero at a building that does not offer
        one - a `GondorBarracks` was made to produce Imrahil this way, and nothing in the game
        reports it. `Session.recruit_hero` refuses that under `godsight=False`; this asks the same
        question *before* the order, so a cycle where no building can serve is a stage returning
        None rather than a raised `IllegitimateOrder` climbing out of `decide`.

        The slot must also be **enabled**, which is a live reading: a revive button gated behind
        an upgrade nobody has bought is a hero the control bar is not showing.

        A full queue disqualifies a building the same way it does for an ordinary recruit - the
        order would be taken and dropped. So does a building that has not finished going up, for
        the opposite reason: its revive slots read as enabled while it is still a shell, the
        order is *accepted*, and the hero then waits on the construction instead of on a revive
        timer - with the price already committed and nothing to show that it is stalled. See
        `production_sites`.
        """
        index = self.session.revive_index(hero)
        if index is None:
            # Not in the list at all - already on the map, or not a hero of this faction. Both
            # are ordinary answers, and neither is something to send an order about.
            return None
        for building in self.production_sites():
            if self.queued_units(building) >= QUEUE_TARGET:
                continue
            slots = self.statics.revive_slots(building.template_name)
            slot = next((s for s in slots if s.roster_index == index), None)
            if slot is not None and slot.enabled_for(self.held_by(building)):
                return building
        return None

    def stage_hero_recruit(self) -> str | None:
        """Buy the plan's hero, once the economy is carrying the army as well.

        **Out of surplus, and that gate is the whole of what keeps this from being a mistake.** A
        hero bought early is 1300 gold not spent on the six battalions that would have taken six
        settlements, and it is also a hero standing alone, which is how heroes die. `HERO_FLOOR`
        says the balance has more than production can absorb, and only then.

        **Reserved rather than raced for.** `stage_recruit` runs first in every list and spends
        whatever it can see, so a hero priced against the plain balance is a hero whose price is
        gone by the next cycle - the same failure `take_flag` reserves against, where a force
        arrived at a settlement it could no longer afford to build on. The reservation is keyed,
        so re-reserving every cycle replaces itself rather than accumulating.

        One at a time: the reservation is released and the stage goes quiet the moment the hero is
        standing. If it dies it re-enters the revive list, `hero_producer` finds a slot again, and
        this buys it back - which is correct and also expensive, and being expensive is what
        `stage_hero`'s retreat exists to make rare.
        """
        wanted = self.plan.hero
        if not wanted:
            return None
        if any(o.template_name.lower() == wanted.lower() for o in self.observation.mine):
            self.release(HERO_PURPOSE)
            return None
        # **Every way out of this stage gives the gold back**, which is the half of a reservation
        # that is easy to forget and expensive to get wrong: the price is invisible to every other
        # stage while it is held, so a promise left standing for a hero nobody is going to buy is
        # 1300 gold the bot cannot see for as long as the condition lasts. Benched after three
        # refusals is two minutes of that; a barracks that has been razed is the rest of the match.
        if self._cold(f"hero:{wanted}"):
            self.release(HERO_PURPOSE)
            return None
        building = self.hero_producer(wanted)
        if building is None:
            self.release(HERO_PURPOSE)
            return None

        if self.gold < HERO_FLOOR:
            # Nothing held here, and dropped if something was: holding gold back before the
            # economy can carry it starves the recruiting that has to happen first for the hero to
            # have an army to stand with, which is the whole reason there is a floor. A balance
            # that has fallen back under it - the base was raided, the queues emptied it - is a
            # reservation that should go with it.
            self.release(HERO_PURPOSE)
            return None
        price = self.charged_cost(wanted)
        self.reserve(HERO_PURPOSE, price)
        if not self.afford(wanted, purpose=HERO_PURPOSE):
            return f"hero: saving {price} for {wanted}"

        me = self.observation.me
        free = None if me is None else me.command_points_free
        cost = self.statics.command_point_cost(wanted)
        if free is not None and cost and cost > free:
            # The same silent discard an over-cap recruit gets, and worth the same one-line wait:
            # the engine takes the order, queues nothing and reports nothing.
            return f"hero: {wanted} costs {cost} command points and {free} are free"

        if not self.select([building]):
            return None
        ok = self.session.confirm_queued(
            lambda: self._issue(
                "hero", lambda: self.session.recruit_hero(wanted, building.object_id)
            ),
            building.object_id,
        )
        self._report("hero", ok, "queued", "NOT QUEUED - logic discarded it")
        self._strike(f"hero:{wanted}", ok)
        if ok:
            self.release(HERO_PURPOSE)
        return f"hero: {wanted} at {building.object_id}"

    #
    # The mission. A hero is not given a target - it is given a force to stand with, and taken
    # out of the fight when it is losing one.

    def hero_forces(self) -> dict[str, list[GameObject]]:
        """The friendly forces a hero could attach itself to, keyed by whose job they are.

        Every job the army is currently doing, read off the bookkeeping the stages that own them
        already keep: the expansion parties, the defence groups, and the push if one is on.
        Nothing new about the world is computed here - a force is a force because another stage
        said so, the same way `Director.shots` asks rather than re-deciding.

        **Keyed rather than listed**, because the key is a commitment: `_hero_escort` remembers
        which force a hero attached itself to, and a positional index silently re-points that at
        somebody else the moment a party ahead of it dies.

        Falls back to the whole non-hero army, which covers the opening - where the starting
        battalions have not been made into a party yet - and any cycle where the bookkeeping is
        momentarily empty. A hero standing with a crowd that has no job is better than a hero
        standing on its own.
        """
        standing = {o.object_id: o for o in self.army()}
        mine = {o.object_id for o in self.heroes()}
        forces: dict[str, list[GameObject]] = {}
        for party, ids in self._parties.items():
            members = [standing[i] for i in ids if i in standing]
            if members:
                forces[f"party:{party}"] = members
        for group, ids in self._groups.items():
            members = [standing[i] for i in ids if i in standing]
            if members:
                forces[f"group:{group}"] = members
        spoken_for = {i for ids in (*self._parties.values(), *self._groups.values()) for i in ids}
        if self._pushing:
            pushing = [
                o
                for o in standing.values()
                if o.object_id not in spoken_for and o.object_id not in mine
            ]
            if pushing:
                forces["push"] = pushing
        if forces:
            return forces
        rest = [o for o in standing.values() if o.object_id not in mine]
        return {"army": rest} if rest else {}

    def hero_escort(self, hero: GameObject) -> list[GameObject] | None:
        """The force this hero should be standing with, or None if there is none.

        **An escort, not a target - and that is the most important decision in this file.**
        Everything a hero is worth assumes it survives to spend it, and a hero given its own
        target is one object arriving alone at whatever is there. Standing with a party makes the
        party better (a body that beats anything it meets one to one, and a leadership aura on
        most of the roster) and makes the hero safe (four battalions between it and whatever wants
        it dead) - and it needs no target selection of its own at all.

        **Fighting first, then nearest.** A force in contact is where the abilities are worth
        firing and where the hero's own body counts for most; among quiet forces the nearest is
        the one it reaches soonest, and usually the one it is already with.

        **Sticky, so a hero does not spend the match walking between two groups.** Two forces at
        roughly equal distance would otherwise swap it back and forth every cycle - the flicker
        `Shot.label` exists to prevent one layer up, and here it would be the hero never arriving
        anywhere. The commitment is dropped only when that force stops existing.
        """
        forces = self.hero_forces()
        if not forces:
            return None
        held = self._hero_escort.get(hero.object_id)
        if held is not None and forces.get(held):
            return forces[held]
        chosen = min(
            forces,
            key=lambda key: (
                not self.in_contact(forces[key]),
                distance(hero.position, _centre_of(forces[key])),
            ),
        )
        self._hero_escort[hero.object_id] = chosen
        return forces[chosen]

    def hero_retreating(self, hero: GameObject) -> bool:
        """Whether this hero is pulling out, latched between `HERO_RETREAT` and `HERO_RETURN`.

        **The latch is the design, not an optimisation.** One threshold makes a hero cross it,
        regenerate a percent on the walk, turn round into the same fight and cross it again -
        which spends the whole match walking and fights none of it. Two mean a withdrawal runs
        until the hero is actually fit to go back, the same way `pushing` commits until the army
        is actually spent.

        **Health, not proximity**, and that is a correction this bot has already paid for once:
        `stage_archers` is written, works, and is switched off in `Bot.decide` because it
        triggered on something being *near* rather than on damage being taken - roughly half of
        its 202 firings pulled bowmen away from a banner carrier standing next to them. A hero at
        30% is a fact about the hero.

        A hero with no readable body is not retreating: `has_body` is false where the observation
        could not read hit points, and zero there means "not applicable" rather than "dying".
        """
        if not hero.has_body:
            return False
        if hero.object_id in self._retreating:
            if hero.health >= HERO_RETURN:
                self._retreating.discard(hero.object_id)
                return False
            return True
        if hero.health < HERO_RETREAT:
            self._retreating.add(hero.object_id)
            return True
        return False

    def hero_refuge(self, hero: GameObject) -> Vec3:
        """Where a hurt hero goes: the nearest thing of ours that is standing, else the base.

        **Back to something, not away from something.** Retreating along the vector away from
        whatever is hitting you buys one cycle and arrives nowhere - it is open ground, and what
        is chasing is usually faster. A building is where the rest of the army already is, where
        a defence group answers whatever followed, and where the hero can stand still long enough
        to regenerate. The same correction `stage_archers` makes when it falls back *to* the melee
        line rather than away from the attacker.
        """
        standing = self.structures()
        if not standing:
            return self.base_centre()
        return min(standing, key=lambda s: hero.distance_to(s.position)).position

    def send_hero(self, hero: GameObject, aim: Vec3, what: str) -> str | None:
        """Walk one hero somewhere, leaving a running order alone.

        **A retreat is a `move` and an escort is an `attack_move`, and the difference is the
        point.** A withdrawal that stops to fight everything on the way home is not a withdrawal;
        an escort that walks past the fight its party is in is not an escort. Which one this is
        comes from the latch rather than from an argument, so the two can never disagree.

        Re-order suppression is per hero and works the way every other force's does - see
        `HERO_REORDER`, and `Orders.march` for the measured version of what reissuing a movement
        order every cycle does to a unit's pathing.
        """
        last = self._hero_aim.get(hero.object_id)
        moved_on = last is None or distance(aim, last) > HERO_ESCORT
        since = time.monotonic() - self._hero_ordered.get(hero.object_id, 0.0)
        if not moved_on and since < HERO_REORDER:
            return None
        if not self.select([hero]):
            return None
        retreating = hero.object_id in self._retreating
        order: Callable[[Vec3], Sent] = (
            self.session.move if retreating else self.session.attack_move
        )
        # Closed over rather than bound as a default: `aim` is this call's own parameter and the
        # order is issued inside `manoeuvre`, before it can be rebound. The default-argument form
        # elsewhere in the bot is for closures written *inside a loop*, which this is not.
        moved = self.manoeuvre("hero move", lambda: order(aim), [hero])
        self._hero_aim[hero.object_id] = aim
        self._hero_ordered[hero.object_id] = time.monotonic()
        return f"{hero.template_name} to {what}" if moved else None

    def stage_hero(self) -> str | None:
        """Put each hero where it should be: out of the fight if hurt, with a force if not.

        One order per hero per cycle at most, and usually none - a hero already standing with its
        party needs nothing, which is what `send_hero`'s re-order suppression is for.

        **A retreat outranks everything, including a siege at home.** Every other stage stands
        down under `besieged` because the army is wanted in one place; a hero at 30% health is not
        made more useful by being wanted, and the reason the rest of the bot can afford to feed
        battalions into a siege is exactly the reason it cannot afford to feed this one.
        """
        said = []
        for hero in self.heroes():
            if self.hero_retreating(hero):
                line = self.send_hero(hero, self.hero_refuge(hero), "cover")
                said.append(line or f"{hero.template_name} pulling out at {hero.health:.0%}")
                continue
            force = self.hero_escort(hero)
            if force is None:
                continue
            line = self.send_hero(hero, _centre_of(force), f"{len(force)} of ours")
            if line:
                said.append(line)
        return " | ".join(f"hero: {line}" for line in said) or None

    #
    # Casting. The aim rules are the hero's own rather than `Powers.aim`'s: that one searches the
    # whole map because a spellbook has no position, and a hero has one and has to walk.

    def hero_reach(self, power: CastablePower) -> float:
        """How far from the hero a target for this ability may be.

        **`StartAbilityRange` is a walk, not a filter.** The engine closes the distance itself
        before the ability fires, so aiming one across the map does not fail - it sends the hero
        there, alone, which is the expensive way to lose it. Gandalf's Wizard Blast declares 80.

        `HERO_ESCORT` where the ability declares nothing, because an ability with no approach of
        its own still must not pull a hero out of the force it is standing with.
        """
        return power.ability_range or HERO_ESCORT

    def hero_cast_targets(self, hero: GameObject) -> int:
        """How many enemies an area ability wants under it before this hero fires it.

        **A hero the player bought has the rest of the match to find a crowd; a summon has a
        lifetime.** Gwaihir arrives from `SpellBookAdler` with a screech that recharges in 180
        seconds and less than a minute to live, so waiting for a second battalion is how it fades
        with the charge unspent - and the eagles are aimed at the enemy army in the first place,
        which is where `Powers.aim` puts every summon. Same for Theoden out of the Rohan banner and
        for the Grey Company: everything they carry has to be spent now or not at all.

        See `SUMMONED`, which is the engine's own mark and is why this needs no template list.
        """
        if self.statics.has_kind(hero.template_name, SUMMONED):
            return 1
        return HERO_CAST_TARGETS

    def hero_aim(self, hero: GameObject, power: CastablePower) -> tuple[Vec3, int, str] | None:
        """Where to fire this ability and at what: `(position, target id, what)`, or None.

        One rule per effect, each pointed at what the ability's own data says it touches, and all
        of them measured from **the hero** rather than from the map:

        - **a self buff** wants the hero to be in a fight and nothing else. There is no target to
          count and no position to choose - the whole question is whether this is the fight worth
          spending it on, and "something is hitting me" is the only honest answer available at a
          two-second cycle.
        - **an ally buff cast on self** is the same question. Boromir's Horn declares an
          `AttributeModifierRange` of 9999999 - the whole map - so counting who is inside it
          proves nothing, and whether the army is *fighting* is what decides whether a speed buff
          is worth two minutes of recharge.
        - **an ally buff with a target** goes over the most of ours within reach.
        - **a heal with a target** goes to the worst hurt thing of ours within reach; one cast on
          self is an area heal centred on the caster, so that one counts who is standing in the
          circle instead - see `HERO_HEAL_TARGETS`.
        - **a strike** goes on the most of theirs; one cast on self goes off wherever the hero is
          standing, so that one asks whether enough of them are around the hero already.
        - **a summon** lands beside the fighting through `summon_spot`, for the same reason a
          spellbook summon does: the arrivals need room to unpack.

        An object-targeted cast takes the **nearest** rather than the densest, because it names
        one thing: density describes a circle, and there is no circle here.
        """
        radius = power.radius or HERO_ESCORT
        reach = self.hero_reach(power)

        def near(other: GameObject) -> bool:
            return hero.distance_to(other.position) <= reach

        if power.effect == EFFECT_SELF_BUFF or (
            power.effect in (EFFECT_BUFF, EFFECT_STRIKE) and power.form == CAST_SELF
        ):
            if not self.in_contact([hero]):
                return None
            if power.effect == EFFECT_STRIKE:
                # A strike that goes off around the caster is worth its recharge only if there is
                # a crowd around the caster - being in contact with one warg is not Word of Power.
                # A summon settles for one, because it will not be here for the next crowd; see
                # `hero_cast_targets`, and Gwaihir's screech for the ability that asked for it.
                under = [o for o in self.enemies() if hero.distance_to(o.position) <= radius]
                if len(under) < self.hero_cast_targets(hero):
                    return None
                return hero.position, 0, f"{len(under)} of theirs around it"
            return hero.position, 0, "the fight it is in"

        if power.effect == EFFECT_HEAL and power.form == CAST_SELF:
            # **An area heal lands where the caster is standing, not where the casualty is**, so
            # naming a target is both the wrong question and a misleading answer. The twins' Healing
            # Arts out of the Grey Company declares a `HealRadius` of 200 and recharges in 90
            # seconds; the branch below would spend it on a single battalion at 99% anywhere inside
            # `HERO_ESCORT`, and report a position the heal never reaches.
            #
            # So this counts what is actually in the circle and wants a real share of the army in
            # it - see `HERO_HEAL_THRESHOLD` and `HERO_HEAL_TARGETS`. Over `army()` rather than
            # everything owned, because these heals declare `INFANTRY CAVALRY MONSTER`: a farm at
            # half health is not what the twins are for, and rubble is not a patient.
            near_hurt = [
                o
                for o in self.army()
                if o.has_body
                and o.health < HERO_HEAL_THRESHOLD
                and hero.distance_to(o.position) <= radius
            ]
            if len(near_hurt) < HERO_HEAL_TARGETS:
                return None
            worst = min(near_hurt, key=lambda o: o.health)
            return hero.position, 0, f"{len(near_hurt)} hurt, worst at {worst.health:.0%}"

        if power.effect == EFFECT_HEAL:
            hurt = [
                o
                for o in self.observation.mine
                if o.has_body and o.is_damaged and not o.under_construction and near(o)
            ]
            if not hurt:
                return None
            worst = min(hurt, key=lambda o: o.health)
            return worst.position, worst.object_id, f"{worst.template_name} at {worst.health:.0%}"

        if power.effect == EFFECT_BUFF:
            ours = [o for o in self.army() if near(o) and o.object_id != hero.object_id]
            found = self.densest(ours, radius)
            if found is None or found[1] < self.hero_cast_targets(hero):
                return None
            return found[0], 0, f"{found[1]} of ours"

        if power.effect in (EFFECT_STRIKE, EFFECT_SUMMON):
            targets = [o for o in self.visible_targets(self.enemies()) if near(o)]
            if power.form == CAST_OBJECT:
                if not targets:
                    return None
                mark = min(targets, key=lambda o: hero.distance_to(o.position))
                return mark.position, mark.object_id, mark.template_name
            found = self.densest(targets, radius)
            if found is None or found[1] < self.hero_cast_targets(hero):
                return None
            where = self.summon_spot(found[0]) if power.effect == EFFECT_SUMMON else found[0]
            return where, 0, f"{found[1]} of theirs"

        return None

    def confirm_hero_cast(
        self,
        hero: GameObject,
        power: CastablePower,
        position: Vec3,
        act: Callable[[], Sent],
    ) -> bool | None:
        """Fire the ability and answer whether the engine took it - None when nothing can tell.

        **The recharge is the receipt, and for a hero it is a better one than the spellbook has.**
        Accepting a cast is what starts a recharge, so the ready-frame on the hero's own module
        moves when - and only when - the order landed. That answers the case `Powers.confirm_cast`
        has to return None for, which for heroes is most of the roster: a self buff changes no
        field an observation carries, drops no view marker and hurts nothing.

        It is the same lesson the signal fire paid for in a harder currency - 520 summons sent,
        520 logged as successes, and the rider's charge count never moved once, because the ledger
        was recording the *send*. Anything that can be checked against the game should be.

        Falls back to `Powers.confirm_cast` where the frame cannot be read at all: any backend
        that is not reading the process, and any ability whose module is not in the table.
        """
        before = self.session.power_cooldowns(hero.object_id).get(power.power)
        if before is None:
            return self.confirm_cast(power, position, act)
        if not act():
            return False

        def recharged(_: Observation) -> bool:
            now = self.session.power_cooldowns(hero.object_id).get(power.power)
            return now is not None and now != before

        return self.session.confirm(recharged, timeout=BUILD_CONFIRM)

    def cast_from(
        self,
        hero: GameObject,
        power: CastablePower,
        position: Vec3,
        target_id: int,
        label: str,
    ) -> Callable[[], Sent]:
        """The order firing `power` from `hero`, with everything bound rather than closed over.

        **The source slot differs between the three forms and getting it wrong is silent.** A self
        or ground cast is cast *by* an object and the order carries its id; an object-targeted
        cast must leave that slot at 0 and lets the engine take the caster from the selection.
        That asymmetry is not a choice made here - it is measured, and measured on a hero ability:
        Faramir's Wound Arrow did nothing with him named as the source and fired the moment the
        slot was zeroed. See `sage_live.api.orders.cast_at_object`.

        Bound rather than closed over for the reason `Orders.attack_on` exists: the order runs
        later, inside the confirmation, by which time the loop has moved on to another ability.
        """
        source = 0 if power.form == CAST_OBJECT else hero.object_id
        return lambda: self._issue(
            label,
            lambda: self.session.cast(
                power.power, power.form, position, target_id=target_id, source_id=source
            ),
        )

    def stage_hero_cast(self) -> str | None:
        """Fire one ability, from the first hero that has one worth firing.

        One per cycle like every other order here, and the ordering inside `hero_ready_powers`
        decides which. An ability with nothing worth hitting keeps its recharge, which is the
        stage working rather than the stage failing.

        **A retreating hero fires only what it can fire while walking.** An ability with a target
        makes the engine close `StartAbilityRange` first, so ordering one during a withdrawal
        turns the hero round and sends it back into what it is running from - the retreat undone
        by the stage that was meant to help it survive. Self-cast abilities have no approach at
        all, and are exactly the ones worth having while hurt: Last Stand, Blade Master, the Horn.
        """
        for hero in self.heroes():
            retreating = hero.object_id in self._retreating
            for power in self.hero_ready_powers(hero):
                if retreating and power.form != CAST_SELF:
                    continue
                aimed = self.hero_aim(hero, power)
                if aimed is None:
                    continue
                position, target_id, what = aimed
                # **Knowing where something is and being allowed to aim at it are different
                # rights** - the engine checks the seat's shroud when the power lands, and this
                # bot reads the object table from memory. See `Powers.can_cast_at`.
                if not self.can_cast_at(position):
                    continue
                if not self.select([hero]):
                    return None
                return self.fire_ability(hero, power, position, target_id, what)
        return None

    def fire_ability(
        self,
        hero: GameObject,
        power: CastablePower,
        position: Vec3,
        target_id: int,
        what: str,
    ) -> str:
        """Send one aimed ability, confirm it, and record what the engine did with it.

        Split out of `stage_hero_cast` so the decision and the bookkeeping read separately: above
        is which ability and where, and this is the four things that have to happen to every cast
        whatever it was - the frame read before the order, the confirmation, the ledger, and the
        clock.
        """
        key = self.hero_key(hero, power)
        label = f"hero {power.effect[:9]}"
        # Read before the order goes out, because accepting it is what moves the number - the
        # frame recorded here is the one that has to change for the next cycle to believe the
        # engine's answer. See `Powers.ready`.
        before = self.session.power_cooldowns(hero.object_id).get(power.power)
        landed = self.confirm_hero_cast(
            hero, power, position, self.cast_from(hero, power, position, target_id, label)
        )
        if before is not None:
            self._cast_frame[key] = before
        if landed is None:
            # Sent, with nothing observable to check it against. Recorded as exactly that rather
            # than as a success - the case that reported 14/14 for a power the engine was
            # refusing every time.
            print(f"    {label:<16} sent (nothing observable to confirm it against)")
            self.ledger.record(label, None)
            self._cast_at[key] = time.monotonic()
            return f"hero: {hero.template_name} {power.power} at {what}"

        self._report(label, landed, "landed", "NOTHING HAPPENED - order discarded")
        self._strike(f"hero:{key}", landed)
        if landed:
            self._cast_at[key] = time.monotonic()
            return f"hero: {hero.template_name} {power.power} at {what}"

        # **A refused cast waits out the whole recharge rather than retrying inside it**, for the
        # reason `stage_cast` sets out at length: the likeliest cause of a well-aimed cast being
        # discarded is a cooldown this bot could not read, and the three-strike bench is shorter
        # than most recharges. An ability that has never been cast cannot be recharging, so that
        # one is left alone - whatever the engine objected to there, it was not the clock.
        if key in self._cast_at:
            self._cast_at[key] = time.monotonic()
            self.back_off(power, key)
        return f"hero: {power.power} refused"
