"""The spellbook: buying powers with spellbook points, and firing the ones that are bought.

**A second currency, and it is the reason this is a stage of its own.** Spellbook points accrue
on their own clock and buy nothing but powers, so nothing here competes with a barracks, a farm
or a battalion for the one purse that `economy` and `recruiting` arbitrate. There is no floor to
clear and no reservation to respect: points not spent are points doing nothing at all, and a
match that ends with ten of them banked has thrown away everything they would have bought.

**The store is the authority, the same way a command set is everywhere else.** A power is bought
through a `PURCHASE_SCIENCE` button on the faction's `PurchaseScienceCommandSetMP`, which is the
palette the spell store puts on screen - so ordering only from there is what keeps this playing
the game a human plays. No name list, no per-faction table: `Statics.spell_store` reads the book
for whichever side the match handed over.

**What is already held is read, not remembered.** A science lands in neither upgrade mask, so
until `PlayerState.sciences` there was nothing to ask - and bookkeeping would have been wrong
anyway, in the direction that costs points: a skirmish AI is *granted* spells by script, with the
prerequisites in the ini simply bypassed (a measured Mordor seat held `SCIENCE_Darkness` holding
none of the three sciences that unlock it). A bot handed one the same way would have kept trying
to buy what it already had.

**Casting is a different command set from buying**, and the split runs through this whole file.
The store hangs off the `PlayerTemplate` and sells; the book hangs off the `SpellBookMp` object
and fires. They are different lengths and only overlap in the middle - Gondor sells 11 powers and
its book shows 14 buttons, and the two ends of that mismatch are what `castable_powers` filters
out. Every cast this bot sends is a `SPELL_BOOK` button on the faction's own book, which is the
same "the command set is the authority" rule the rest of the bot obeys.

**A cast is scarce rather than expensive**, and that inverts the usual decision. Nothing here
competes for gold or for points; what a cast spends is its own recharge, which runs from 180 to
940 seconds. So there is no floor to clear and no reserve to respect - only the question of
whether this target is worth more than the same spell three minutes from now, which is what
`CAST_MIN_TARGETS` and `CAST_PATIENCE` arbitrate.

**Three of the buttons on every book are not spells at all.** Gondor's first three are the
disband tool and two palantír view toggles, and firing the first would disband the bot's own
hordes. They are not excluded by name: their `RequiredSciences` are the view sciences every seat
already holds at frame zero, so no spell store sells them - and "the store never sold it" is
exactly the test that separates a power from a UI button, for this faction and the next.

**Where to aim comes from what the power does**, which is read off the module implementing it
rather than from its name - see `Statics.spell_book`. A summon and a bombardment are the same
module and differ only in where their creation chain ends, and a friendly spell can be delivered
through the same weapon-firing shape as a hostile one. A power the data cannot place is skipped
rather than guessed at: three of Mordor's sixteen come back `unknown`, and a wrong guess spends
minutes of recharge helping the wrong army.
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable

from sage_live.api.observation import GameObject, Observation, Vec3, distance
from sage_live.api.session import BUILD_CONFIRM, Sent
from sage_live.utils.naming import UnknownDefinition
from sage_live.utils.statics import (
    EFFECT_BUFF,
    EFFECT_BUILD,
    EFFECT_HEAL,
    EFFECT_STRIKE,
    EFFECT_SUMMON,
    CastablePower,
    PowerButton,
)
from sage_mods.edain.bot.economy import Economy
from sage_mods.edain.bot.mechanics.signal_fire import SIGNAL_FIRE
from sage_mods.edain.bot.tuning import (
    BASE_RADIUS,
    CAST_BACKOFF,
    CAST_BACKOFF_CAP,
    CAST_BUILD_CLEARANCE,
    CAST_BUILD_RINGS,
    CAST_GROUND_COOLDOWN,
    CAST_HEAL_THRESHOLD,
    CAST_HEAL_URGENT,
    CAST_MIN_TARGETS,
    CAST_PATIENCE,
    CAST_RADIUS_FLOOR,
    CAST_SUMMON_CLEARANCE,
    CAST_SUMMON_RINGS,
    TOWER_STANDOFF,
)

# The effects this bot knows where to point. `EFFECT_GRANT` is deliberately absent - a granted
# upgrade takes no target and the ones measured are all passive anyway - and so is
# `EFFECT_UNKNOWN`, which is the data declining to say whose side a power is on.
AIMABLE = (EFFECT_HEAL, EFFECT_BUFF, EFFECT_SUMMON, EFFECT_STRIKE, EFFECT_BUILD)


class Powers(Economy):
    """Reading the faction's spellbook, buying from it, and firing what it holds."""

    def science_id(self, science: str) -> int | None:
        """The order id for a science name, or None for a name this build does not define.

        None is an ordinary answer. A prerequisite may name a science from a sub-faction the
        loaded tree spells differently, and the id space is the one that still needs an ini
        load - so a name that will not resolve is a fact about the data rather than a fault,
        and it means only that this power cannot be reasoned about.
        """
        if science.lower() not in self._science_ids:
            try:
                self._science_ids[science.lower()] = self.session.resolve("science", science)
            except UnknownDefinition:
                self._science_ids[science.lower()] = None
        return self._science_ids[science.lower()]

    def held_powers(self) -> frozenset[str]:
        """The sciences this player holds, by lowercased name - live, not remembered.

        **The live set carries ids and the store carries names**, and the join runs one way
        only: names are resolvable to ids (`Resolver.science`), ids are not resolvable back to
        names without walking a table nothing here has. So this asks the question the other way
        round - of every science the store *mentions*, which ones is the player holding - which
        needs no reverse map and covers exactly the names any decision below turns on.

        Prerequisite names are included as well as the powers themselves, and they are the half
        that matters: a faction's intrinsic science (`SCIENCE_MEN`) is what unlocks the whole
        first row, and it is never on sale.
        """
        me = self.observation.me
        if me is None:
            return frozenset()
        held = set()
        for name in self._store_names():
            found = self.science_id(name)
            if found is not None and found in me.sciences:
                held.add(name.lower())
        return frozenset(held)

    def _store_names(self) -> tuple[str, ...]:
        """Every science name the faction's book mentions - what is sold, and what gates it."""
        if self._science_names is None:
            names: dict[str, None] = {}
            for power in self.spell_store:
                names[power.science] = None
                for group in power.prerequisites:
                    for gate in group:
                        names[gate] = None
            self._science_names = tuple(names)
        return self._science_names

    def power_options(self) -> list[PowerButton]:
        """Every power the spell store would sell right now, cheapest first.

        Four things disqualify a power, and each is the data saying so rather than a rule here:

        - the slot sells nothing (`purchasable`) - every book is padded to twenty slots with
          `Command_PurchaseSpellEmpty`, and its `SCIENCE_Empty` is not grantable and asks for
          both alignments at once;
        - it is already held, which is the live answer and includes anything granted;
        - its prerequisites are unmet, so the store would show it greyed out;
        - the points do not cover it.

        **Cheapest first, which is what opens the tree.** The book is a tree with the powers
        worth having at the top of it, so buying by value would mean saving for something no
        prerequisite has unlocked yet - a rank-4 spell costs 10 points and is gated behind two
        rungs of cheaper ones, so there is no path to it that does not go through them. Spending
        every point as it arrives therefore *is* the fastest route up, and it has the property
        that matters more early on: a power held is a power that can be cast, and a bank of
        points is nothing at all.

        Unmeasured, unlike most of the numbers this bot plays by - there is no run yet that
        bought a different order and did worse. It is the reading of the tree, not a result.
        """
        me = self.observation.me
        if me is None:
            return []
        held = self.held_powers()
        options = [
            power
            for power in self.spell_store
            if power.purchasable
            and power.science.lower() not in held
            and power.enabled_for(held)
            and power.cost <= me.power_points
            and self.science_id(power.science) is not None
            and not self._cold(f"power:{power.science.lower()}")
        ]
        options.sort(key=lambda power: (power.cost, power.command_slot))
        return options

    def stage_powers(self) -> str | None:
        """Buy one power, whenever the points cover the cheapest one on offer.

        **Runs in every phase, including the opening.** Every other stage is gated on the build
        order because they all spend the same gold; this one cannot take anything from them, so
        withholding it early would buy nothing and cost the whole opening's worth of points.

        One per cycle, like every other spend here. The confirmation is direct - the science is
        either held afterwards or it is not - so a discarded purchase is visible immediately
        rather than inferred from a balance.
        """
        options = self.power_options()
        if not options:
            return None
        power = options[0]
        key = f"power:{power.science.lower()}"
        ok = self.session.confirm_power(
            lambda: self._issue("power", lambda: self.session.purchase_power(power.science)),
            power.science,
        )
        self._report("power", ok, "bought", "NOT BOUGHT - logic discarded it")
        self._strike(key, ok)
        me = self.observation.me
        left = me.power_points if me else 0
        return f"power: {power.science} ({power.cost}pt, {left} left)"

    def sold_sciences(self) -> frozenset[str]:
        """The sciences this faction's spell store actually sells, lowercased.

        The test that separates a spell from a UI button, and it needs no name list: the first
        three buttons of every book are gated on the view sciences (`SCIENCE_GENERAL_VIEW` and
        friends), which every seat holds from frame zero and no store ever offers. Gondor's first
        button is the **disband** tool - `ANY +HORDE SAME_PLAYER`, 60-second recharge - so a bot
        firing whatever its book offers would spend the match disbanding its own army.
        """
        return frozenset(p.science.lower() for p in self.spell_store if p.purchasable)

    def wait_for(self, power: CastablePower) -> float:
        """How long the fallback clock makes this power wait, in seconds.

        The ini's declared recharge until the engine refuses a cast made on it, and longer after
        each one - see `CAST_BACKOFF`. Grown rather than tuned because the true figure is not in
        the data: Edain rescales it per player, so the only place the real number shows up is in
        which casts the engine takes.
        """
        return self._cast_wait.get(power.power, power.reload_seconds)

    def back_off(self, power: CastablePower) -> None:
        """Make this power's fallback clock wait longer, after the engine refused it."""
        grown = self.wait_for(power) * CAST_BACKOFF
        self._cast_wait[power.power] = min(grown, power.reload_seconds * CAST_BACKOFF_CAP)

    def ready(self, power: CastablePower) -> bool:
        """Whether the engine will accept this power now.

        **The engine's own answer where it can be had.** Every special-power module carries the
        frame its power is next usable on, and `Session.power_cooldowns` reads it off the
        spellbook - so this is the same number the engine checks rather than an estimate of it.

        That matters in both directions. `SpecialPower.ReloadTime` is the *undiscounted* figure
        and Edain scales it per player: measured live, Rallying Call recharged in 30 seconds
        against a declared 180, so a bot pricing it from the ini sits out six times too long.
        And a local clock is blind to any cast this process did not make and is wiped by a
        restart - which is what produced a run of 33 refusals in 34 summon attempts, every one
        fired into a cooldown the bot could not see.

        **Most of the book is not in that table, and a miss is not a readiness.** The spellbook
        object carries a module per power it *can* hold, which is not the set this faction casts:
        measured on a live Gondor seat, `power_cooldowns` answered 44 entries - most of them
        other factions' spells, `SpellBookHealRohan` and `SpellBookArrowVolleyArnor` among them -
        while `SpellBookRebuild`, `SpellBookArrowVolleyGood` and `SpellBookSpawnLoneTower_Edain`,
        which are three of the four powers that run actually cast, were absent. So a `.get` miss
        is the reading failing, not the power being ready, and it falls through to the clock.

        **A frame that has not moved since the last cast is also a miss.** Accepting a cast is
        what starts a recharge, so the engine declining one leaves its frame where it was - in
        the past, which reads as permission and fires the power again on the very next cycle.
        That is not hypothetical: Rallying Call sat frozen at 10852 through five casts while the
        match ran to frame 11360, going out every few seconds, every one of them recorded as a
        success because a buff with no view marker has nothing to confirm against. So a frame
        this bot has already cast on is not evidence, and the clock decides instead.

        **The fallback is the old clock, not optimism.** A backend that cannot read modules
        answers empty, and empty means "unknown" - so this falls back to counting from the last
        cast rather than treating silence as permission.
        """
        cooldowns = self.session.power_cooldowns(self.spellbook_id())
        ready_frame = cooldowns.get(power.power)
        if ready_frame is not None and ready_frame != self._cast_frame.get(power.power):
            return ready_frame <= self.observation.frame
        last = self._cast_at.get(power.power)
        return last is None or time.monotonic() - last >= self.wait_for(power)

    def castable_powers(self) -> list[CastablePower]:
        """Every power the book could fire this cycle, dearest recharge first.

        Six filters, and each removes something that would otherwise be an order into the dark:
        a passive that fired when it was bought, a power whose science is not held, a UI button
        the store never sold, an effect the data will not place, a recharge that has not elapsed,
        and one benched for failing three times.

        **Ordered by recharge, longest first**, which is the opposite of the buying stage and for
        the opposite reason. Points are spent cheapest-first because that opens the tree fastest;
        a cast opens nothing, so the power worth firing is the one that has been waiting longest
        to be worth something - and a 830-second spell that finds a target now may not find
        another this match.
        """
        held = self.held_powers()
        sold = self.sold_sciences()
        options = [
            power
            for power in self.spell_book
            if power.castable
            and power.effect in AIMABLE
            and power.enabled_for(held)
            and any(s.lower() in sold for s in power.sciences)
            and self.ready(power)
            and not self._cold(f"cast:{power.power.lower()}")
        ]
        options.sort(key=lambda power: -power.reload_seconds)
        return options

    def can_cast_at(self, position: Vec3) -> bool:
        """Whether the seat can see `position` well enough for the engine to accept a cast there.

        **Knowing where something is and being allowed to aim at it are different rights**, and
        this bot holds the first without the second. It reads the whole object table from memory,
        so `--fog` off means it can name every enemy building on the map - but the engine still
        checks the *seat's* shroud when a power is fired, and refuses a cast onto ground nobody
        is watching. Measured this run, on two refusals in the same minute: Arrow Volley aimed at
        `(1041, 2618)`, which the seat could not see, was discarded; Rebuild aimed at
        `(3263, 1516)`, which it could, was refused for an unrelated reason.

        **Unknown means yes**, in line with every other reading here. A backend with no shroud
        grid, or a match with fog switched off, answers None and nothing is filtered - the old
        behaviour, which is right when there is no shroud to respect.
        """
        grid = self.observation.shroud
        if grid is None or not grid.fog_enabled:
            return True
        return grid.visible(position, self.session.player_index)

    def enemies(self) -> list[GameObject]:
        """Opponents' troops on the map - what a spell is worth spending on.

        **A creep is not an opponent, and a spell aimed at one is a spell thrown away.** The map
        seats (`PlyrCreeps`, `PlyrCivilian`) own the lairs, their endlessly respawning slaves and
        every animal, and `hostile` counts all of it because the *army* has to fight what is in
        front of it. A power does not: it recharges in minutes, the slaves are replaced for free
        by a lair that is still standing, and the same charge spent on the opponent's battalions
        is spent on something that will not come back. Measured live: Eagles at 630 seconds and
        Arrow Volley at 360 both landed on clusters of `IsengardWildman_Slaved`.

        `wild` is the test rather than a name list - see `World.wild`, and note that
        `enemy_structures` has always asked the same question by walking `opponents` directly.
        """
        return [o for o in self.observation.objects if self.hostile(o) and not self.wild(o)]

    def visible_targets(self, objects: list[GameObject]) -> list[GameObject]:
        """Those of `objects` the seat can currently see - the only ones a cast may be aimed at."""
        return [o for o in objects if self.can_cast_at(o.position)]

    def wanted_targets(self, power: CastablePower) -> int:
        """How many objects this power needs under it before it is worth firing.

        The bar drops rather than disappearing. A power that has been ready and unused for
        `CAST_PATIENCE` settles for half, floored at one, because an uncast spell is worth
        nothing at all - the same arithmetic that makes a banked spellbook point worthless.
        """
        since = self._ready_since.setdefault(power.power, time.monotonic())
        if time.monotonic() - since < CAST_PATIENCE:
            return CAST_MIN_TARGETS
        return max(1, CAST_MIN_TARGETS // 2)

    def densest(self, objects: list[GameObject], radius: float) -> tuple[Vec3, int] | None:
        """The spot covering the most of `objects`, and how many that is.

        Every object's own position is tried as the centre, which is enough: the best circle over
        a set of points can always be slid until one of them is at its centre without losing any,
        and a spell's radius is generous next to the spacing of a battalion.
        """
        if not objects:
            return None
        best: tuple[Vec3, int] | None = None
        for candidate in objects:
            covered = sum(1 for o in objects if distance(o.position, candidate.position) <= radius)
            if best is None or covered > best[1]:
                best = (candidate.position, covered)
        return best

    def tower_spot(self) -> tuple[Vec3, str] | None:
        """Where to put a lone tower: covering an outlying holding, on the enemy's side of it.

        **A settlement is what a tower is for.** The placement this replaces aimed at the base
        centre, which is both the best-defended ground on the map and the worst place to fit a
        building - `open_ground` exists because that aim was refused three times running. The
        holdings that actually need help are the settlements and outposts out on the map: no
        wall, no spread, and the first thing a raid reaches.

        **Between the holding and the enemy**, so the tower is in the way rather than behind the
        thing it is covering. The enemy's centre is a scouting result under fog and is often not
        known, so the fallback is the direction away from our own base - the side an attack
        arrives from, on any map where the two bases are not on top of each other. Both are
        offsets of `TOWER_STANDOFF` from the holding, which is inside `HOLDING_RADIUS` so that
        whatever comes for the settlement is in the tower's arc.

        **One per holding**, tracked in `_towered` rather than counted on the map - see there for
        why the spawned tower cannot be found by name, and for what that costs.

        None when every holding already has one, when there are no outlying holdings yet, or when
        `open_ground` cannot fit a building near the chosen one. The caller keeps the charge in
        all three cases, which is right: a spell with nowhere good to go is worth holding.
        """
        home = self.base_centre()
        holdings = [o for o in self.structures() if distance(o.position, home) >= BASE_RADIUS]
        wanted = [o for o in holdings if o.object_id not in self._towered]
        if not wanted:
            return None

        seat = self.enemy()
        threat_from = seat[1] if seat is not None else None
        # Nearest to the enemy first where one is known, else nearest the front - which is the
        # same ordering by a different name, and the holding most likely to be hit next.
        reference = threat_from if threat_from is not None else home
        wanted.sort(key=lambda o: distance(o.position, reference), reverse=threat_from is None)

        # **The signal fire takes the first tower, ahead of whatever is nearest the enemy.** Every
        # other outlying holding is replaceable - a farm razed is 200g and a walk - where the fire
        # is bought once, is never rebuilt, and is only worth anything after its rider has spent
        # ten minutes accruing. It is also the one holding that cannot defend itself at all: no
        # garrison, no spawn, nothing but the rider standing next to it. So the tower that would
        # have gone to the most exposed farm goes here instead, and the ordering below decides
        # every tower after this one.
        fires = [o for o in wanted if o.template_name.lower().startswith(SIGNAL_FIRE.lower())]
        holding = fires[0] if fires else wanted[0]
        toward = threat_from if threat_from is not None else self._away_from(home, holding.position)
        aim = self._toward_point(holding.position, toward, TOWER_STANDOFF)
        spot = self.open_ground(aim)
        if spot is None:
            return None
        self._towered.add(holding.object_id)
        side = "the enemy" if threat_from is not None else "the front"
        return spot, f"{holding.template_name}, {side} side"

    @staticmethod
    def _away_from(home: Vec3, holding: Vec3) -> Vec3:
        """A point beyond `holding` on the line out from `home` - the side an attack arrives on."""
        return (
            holding[0] + (holding[0] - home[0]),
            holding[1] + (holding[1] - home[1]),
            holding[2],
        )

    @staticmethod
    def _toward_point(start: Vec3, target: Vec3, span: float) -> Vec3:
        """`span` units from `start` in the direction of `target`, keeping `start`'s height.

        The height is kept rather than interpolated because these are ground positions and the
        engine places on terrain anyway; carrying the target's Z would aim a placement at the
        altitude of somewhere else on the map.
        """
        dx, dy = target[0] - start[0], target[1] - start[1]
        length = math.hypot(dx, dy)
        if not length:
            return start
        reach = min(span, length)
        return (start[0] + dx / length * reach, start[1] + dy / length * reach, start[2])

    def open_ground(self, centre: Vec3) -> Vec3 | None:
        """Somewhere near `centre` with room to put a building, or None if there is nowhere.

        **The engine refuses a placement it cannot fit and says nothing**, so a power that builds
        has to be aimed at ground rather than at an average - see `CAST_BUILD_CLEARANCE` for the
        three refusals that came of aiming at the base's centre, which is precisely where a base
        has least room.

        Searched outwards in rings, so the tower still goes up as near the middle as it fits.
        Everything with a body blocks, theirs as well as ours: a structure cannot be placed on
        top of a battalion either, and a spot with an enemy standing on it is not somewhere to
        put a building even when the engine would allow it.

        **Empty ground is not the same as ground that will take a building**, and nothing here
        can tell the difference: an observation carries objects, not terrain, so a spot with
        nothing standing on it may still be water, cliff or slope the engine refuses a
        foundation on. That is not hypothetical - the first version of this scan picked
        `(4144.94, 1490.06, 150.0)` and was refused there in two consecutive matches, to the last
        decimal, because the scan is deterministic and so is the base it measures from.

        So refusals are remembered, and the scan works through the rings instead of repeating one
        wrong answer. Remembered per position rather than per power, since whatever the engine
        objected to is a fact about the place rather than about the spell.

        **Avoided for a while, not condemned.** Terrain is only one reason a placement is
        refused; a battalion wandering into the spot between the aim and the cast is another, and
        an observation cannot tell those apart. A permanent mark would blacklist good ground on
        the strength of a passing unit, so the mark expires - see `CAST_GROUND_COOLDOWN`.

        None is an ordinary answer and the caller keeps the charge for it. A base with no room
        anywhere inside the last ring will have room again once something in it dies.
        """
        return self.clear_spot(centre, CAST_BUILD_CLEARANCE, CAST_BUILD_RINGS)

    def clear_spot(self, centre: Vec3, clearance: float, rings: tuple[float, ...]) -> Vec3 | None:
        """The nearest point to `centre` with nothing standing within `clearance`, or None.

        Searched outwards in rings, so whatever is being placed goes as near the middle as it
        fits. Everything with a body blocks, theirs as well as ours: nothing can be put down on
        top of a battalion, and a spot with an enemy standing on it is not somewhere to put
        anything even where the engine would allow it.
        """
        standing = [o for o in self.observation.objects if o.has_body]
        for ring in rings:
            for step in range(8):
                angle = step * math.pi / 4
                spot = (
                    centre[0] + ring * math.cos(angle),
                    centre[1] + ring * math.sin(angle),
                    centre[2],
                )
                if not self.refused_ground(spot) and all(
                    distance(spot, o.position) >= clearance for o in standing
                ):
                    return spot
                if ring == 0.0:
                    # Every angle names the same point at radius zero.
                    break
        return None

    def summon_spot(self, fight: Vec3) -> Vec3:
        """Where to put a summon called down on the fighting at `fight`.

        **Beside the fight rather than on it, because a summon needs room to unpack.** Measured
        by hand: a summon arrives as a spread of spawn points over a hundred units across, and
        aimed into a crowd there is nowhere for them to stand - `SpellBookArmyoftheDead` and
        `SpellBookDieGraueSchaar` were both discarded on a cluster of twelve, and both landed in
        open ground. See `CAST_SUMMON_CLEARANCE`.

        **Falls back to the cluster itself**, which is what this used to do unconditionally. A
        flying summon needs no ground at all - `SpellBookAdler` landed on the same crowd that
        refused the other two - so when there is no clear spot to be had, the old aim is still
        the right answer for some of the book and no worse than not casting for the rest.
        """
        spot = self.clear_spot(fight, CAST_SUMMON_CLEARANCE, CAST_SUMMON_RINGS)
        return spot if spot is not None else fight

    def refused_ground(self, spot: Vec3) -> bool:
        """Whether the engine declined to build at this spot recently enough to still avoid it.

        Matched by proximity rather than equality. `base_centre` is a mean over a changing set of
        buildings, so it drifts by a few units between cycles and every spot measured from it
        drifts with it - an exact test would call each drifted copy a fresh spot and be refused
        at all of them in turn.
        """
        now = time.monotonic()
        return any(
            until > now and distance(spot, bad) < CAST_BUILD_CLEARANCE
            for bad, until in self._refused_ground.items()
        )

    def filter_targets(self, power: CastablePower) -> list[GameObject] | None:
        """The owned objects a power's filter names by template, or None if it names none.

        None and an empty list mean different things and the caller depends on both: None is
        "this power is not template-specific, aim it however its effect suggests", while an
        empty list is "it wants a `GondorLeuchtfeuer` and this player has none standing", which
        is a cast that would be refused.

        A filter's `+` entries mix `KindOf` flags with template names, and the two are told
        apart by asking the build: a token this tree defines an `Object` for is a template, and
        anything else is a flag this does not have to understand. **Not by whether one is
        standing** - that reads "the signal fire is destroyed" as "this power is not about
        signal fires" and aims it at the army again, which is the bug this exists to fix.
        """
        wanted = {t.lstrip("+-") for t in power.affects if t.startswith("+")}
        templates = {t.lower() for t in wanted if self.statics.known(t)}
        if not templates:
            return None
        return [o for o in self.observation.mine if o.template_name.lower() in templates]

    def aim(self, power: CastablePower) -> tuple[Vec3, str] | None:
        """Where to fire this power, and what it is being fired at - None for nothing worth it.

        One rule per effect, and each points at what the power's own data says it touches:

        - **heal** repairs `STRUCTURE`, so it goes where the damage is. One building is enough to
          be worth it - `wanted_targets` is not applied, because a keep at half health is not
          three of anything - but it has to be hurt past `CAST_HEAL_THRESHOLD` to count at all.
        - **buff** changes units in place, so it goes over the most of this army it can cover.
        - **strike** goes over the most of theirs. Enemy structures come first because that is
          what Gondor's Arrow Volley itself prefers (`NONE +STRUCTURE ENEMIES`), and buildings
          also cannot walk out of the circle between the order and the impact.
        - **summon** puts units on the map, so it lands where the fighting is - next to their
          army if there is one to fight, and on their buildings otherwise. A summon has no side
          of its own; this is the one aim that is a tactical choice rather than a lookup. Beside
          the fight rather than in it, because the arrivals need room to stand - see
          `summon_spot`.
        - **build** puts a structure down, and a structure wants to be somewhere that will still
          be ours next cycle: the base. There is no target to test - a free building is worth
          having wherever it lands, Gondor's Lone Tower being a 250g `FS_BASE_DEFENSE` tower for
          two points - but there is *ground* to test, which is what `open_ground` does and what
          three measured refusals came of not doing.

        **What a built structure then does can be invisible here.** Gondor's Rohan Answers places
        `GondorRohanRallyPoint`, whose command set is a sell button and four `Command = None`
        portraits - so whatever produces the Rohirrim is script-driven and not in the ini at all.
        It is also `REVEAL_TO_ALL`, which broadcasts its position to the opponent. Placing it at
        the base is therefore the conservative reading of a power this cannot fully model.
        """
        radius = power.radius or CAST_RADIUS_FLOOR
        wanted = self.wanted_targets(power)

        if power.effect == EFFECT_HEAL:
            # **A building going up is not a building that needs repairing**, and health cannot
            # tell them apart: a structure ramps its hit points from zero as it builds, so the
            # newest construction is always the "most damaged" thing owned. Measured on the
            # first live cast this stage ever made - the bot placed a `GondorBarracks` and spent
            # Rebuild on it in the same cycle, reporting it "at 0%". `ACTIVELY_BEING_CONSTRUCTED`
            # is the engine's own answer and the only one that works.
            # **Damaged is not the same as worth a charge**, and `is_damaged` is the looser of
            # the two on purpose - see `CAST_HEAL_THRESHOLD` for the buildings at 98% and 94%
            # that spent it while a farm burned at 11%.
            #
            # **And a wreck is not a patient.** A keep destroyed does not leave the object table:
            # it stands at zero health wearing `RUBBLE`, which is not under construction and is
            # the most damaged thing owned by a wide margin, so it wins every heal it is offered
            # and none of them do anything. That is the `GondorCampKeep at 0%` of two runs.
            # **Picky while the charge is fresh, and less so once it has been idle.** A building
            # merely scratched is not what a three-minute recharge is for - see
            # `CAST_HEAL_URGENT` for the cast at 70% that left the next casualty waiting.
            # `wanted_targets` above is what keeps `_ready_since` current for this power.
            since = self._ready_since.get(power.power, time.monotonic())
            limit = (
                CAST_HEAL_THRESHOLD
                if time.monotonic() - since >= CAST_PATIENCE
                else CAST_HEAL_URGENT
            )
            hurt = [
                s
                for s in self.structures()
                if s.health < limit and s.has_body and not s.under_construction and not s.is_rubble
            ]
            if not hurt:
                return None
            # **A repair is refused outright unless a damaged building is inside the radius**,
            # which makes aiming at the *single worst* building the wrong rule twice over. It is
            # the building most likely to die between the order and its execution - and when it
            # does, the cast lands on nothing damaged and logic discards it. Measured live: nine
            # straight refusals aimed at a house on 23% while the base was under attack, against
            # a hand-fired cast on a cluster that repaired three buildings at once.
            #
            # So this aims where the damage *is*, which survives losing any one building and is
            # worth more anyway - a heal covers a radius, and healing three is three times the
            # spell. The worst building breaks the tie, so a lone casualty is still repaired.
            found = self.densest(hurt, radius)
            if found is None:
                return None
            centre, covered = found
            near = [s for s in hurt if distance(s.position, centre) <= radius]
            worst = min(near, key=lambda s: s.health)
            return centre, f"{covered} damaged, worst {worst.template_name} at {worst.health:.0%}"

        if power.effect == EFFECT_BUFF:
            # **Some buffs act on one named building, not on the army**, and pointing one of
            # those at a battalion is refused outright. Gondor's Assistance in Time of Need
            # attaches to `+GondorLeuchtfeuer` - the signal fire - so its filter names the
            # template rather than a `KindOf`, and the objects it wants may be nowhere near the
            # troops. Measured live: three refusals reported against "1 of ours" before the aim
            # read the filter's names.
            #
            # Matched against what is owned rather than against a list of known flags: a token
            # that names a template this player has standing is a target, and one that does not
            # is a `KindOf` or a word this does not need to understand.
            named = self.filter_targets(power)
            if named is not None:
                # Template-specific: it goes on those or it goes nowhere. An empty list is a
                # power whose building this player does not have standing, which is a cast the
                # engine would refuse - so the charge is kept instead.
                found = self.densest(named, radius)
                if found is None:
                    return None
                return found[0], f"{found[1]} x {named[0].template_name}"
            found = self.densest(self.army(), radius)
            if found is None or found[1] < wanted:
                return None
            return found[0], f"{found[1]} of ours"

        # **Only what the seat can actually see.** These two aim across the map at things this
        # bot knows about by reading memory rather than by watching, and the engine checks the
        # shroud when the order lands - so a target nobody is looking at is a discarded cast and
        # a spent recharge. See `can_cast_at`.
        if power.effect == EFFECT_STRIKE:
            for what, targets in (
                ("their buildings", self.visible_targets(self.enemy_structures())),
                ("their army", self.visible_targets(self.enemies())),
            ):
                found = self.densest(targets, radius)
                if found is not None and found[1] >= wanted:
                    return found[0], f"{found[1]} of {what}"
            return None

        if power.effect == EFFECT_SUMMON:
            for what, targets in (
                ("their army", self.visible_targets(self.enemies())),
                ("their buildings", self.visible_targets(self.enemy_structures())),
            ):
                found = self.densest(targets, radius)
                if found is not None and found[1] >= wanted:
                    return self.summon_spot(found[0]), f"{found[1]} of {what}"
            return None

        if power.effect == EFFECT_BUILD:
            return self.tower_spot()

        return None

    def confirm_cast(self, power: CastablePower, position: Vec3, act) -> bool | None:
        """Fire the power and answer whether the game visibly did something - None when nothing
        here can tell.

        **The oracle is different per effect, because what a cast produces is different**, and
        three of the four are as direct as any order in this bot:

        - **summon** and **build** put an object on the map, which is `confirm_appeared` - the
          same test a structure gets, and immune to the summoned template not being the one the
          OCL named at the top of its chain.
        - **strike** must hurt something, so this watches the objects that were standing under it
          and asks whether any lost health. Nothing else in the match can forge that against the
          specific objects named here.
        - **heal** must repair, so the same reading with the sign reversed - and over structures
          only, because that is all a `HealAffects = STRUCTURE` power can touch and a battalion
          regenerating under it would otherwise sign for the spell's work.

        **A buff is answered by its reveal marker where it has one.** An attribute modifier
        lands on a unit and changes nothing an observation carries - not health, not upgrades,
        not conditions - so there is nothing of the *effect* to watch. What some powers do leave
        is the marker their `ViewObjectDuration` drops at the cast point, and an object appearing
        where the order was aimed is as direct as any confirmation here.

        **Only where the data says so.** The marker is not universal - measured on Gondor's
        book, 4 of the 8 real spells declare a view object and the other 4 leave nothing - so
        assuming it would report every cast of Rallying Call as failed for the rest of the
        match. A power with no marker and no observable effect still answers `None`: recorded as
        unverified, with the cooldown started anyway, because the alternative is re-firing a
        working spell every cycle.
        """
        radius = power.radius or CAST_RADIUS_FLOOR
        watched = {
            o.object_id: o.health
            for o in self.observation.objects
            if distance(o.position, position) <= radius
            and o.has_body
            # **A structure under construction forges a heal**, because its health climbs on its
            # own - so "something here got healthier" is true of a building site whatever the
            # spell did. That is how the first live Rebuild reported `landed` while healing
            # nothing. Only the heal direction is affected: a rising ramp cannot fake a *fall*,
            # so a strike still watches everything and does not under-report a real hit.
            and not (power.effect == EFFECT_HEAL and o.under_construction)
            # **A heal that can only touch buildings must only be checked against buildings.**
            # `SpellBookRebuild` is a `PlayerHealSpecialPower` with `HealAffects = STRUCTURE`, so
            # a battalion standing under it cannot have been healed by it - but battalions
            # regenerate on their own, and a watch over every body in the radius credits the
            # spell with that. Both casts this run made on wreckage came back `landed` with
            # nothing they could have repaired, which is what that reads like from here.
            and not (
                power.effect == EFFECT_HEAL
                and not self.statics.has_kind(o.template_name, "STRUCTURE")
            )
        }

        if power.effect in (EFFECT_SUMMON, EFFECT_BUILD):
            return self.session.confirm_appeared(act, near=position, within=radius * 2)

        if power.effect in (EFFECT_STRIKE, EFFECT_HEAL):
            if not act():
                return False
            worse = power.effect == EFFECT_STRIKE

            def changed(obs: Observation) -> bool:
                for object_id, before in watched.items():
                    found = obs.obj(object_id)
                    if found is None:
                        # Only a strike can be credited with something vanishing.
                        if worse:
                            return True
                        continue
                    if worse and found.health < before - 0.001:
                        return True
                    if not worse and found.health > before + 0.001:
                        return True
                return False

            return self.session.confirm(changed, timeout=BUILD_CONFIRM)

        if power.view_seconds > 0:
            # The power drops a marker where it was aimed, so something appearing there is the
            # cast landing. Not owner-scoped, unlike `confirm_appeared`: the marker belongs to
            # whatever the engine makes it belong to, and it is the *appearing* that carries the
            # meaning. Anything else turning up inside the radius in the same second would have
            # to be a coincidence of the kind nothing else in this match produces.
            standing = {o.object_id for o in self.observation.objects}
            if not act():
                return False

            def marked(obs: Observation) -> bool:
                return any(
                    o.object_id not in standing and distance(o.position, position) <= radius * 2
                    for o in obs.objects
                )

            return self.session.confirm(marked, timeout=BUILD_CONFIRM)

        return None if act() else False

    def spellbook_id(self) -> int:
        """The live id of this player's spellbook object, or 0 if it is not on the map.

        **Every cast needs it and a cast without it does nothing.** The order names the object
        the power is cast *by*, and leaving that slot at 0 is discarded in silence - measured in
        a controlled match, where Eagles at source 0 did nothing and the identical order naming
        the `GondorSpellBook` summoned all three immediately.

        Re-read rather than cached across cycles: the object is present for every seat in every
        match observed, but it is an object like any other and a policy that cached a stale id
        would fire every remaining cast into nothing.
        """
        wanted = self.statics.spell_book_object(self.side).lower()
        if not wanted:
            return 0
        found = next((o for o in self.observation.mine if o.template_name.lower() == wanted), None)
        return found.object_id if found is not None else 0

    def cast_on(self, power: CastablePower, position: Vec3, label: str) -> Callable[[], Sent]:
        """An order that fires `power` at `position`, with both bound rather than closed over.

        The same trap `Orders.attack_on` exists for, in the same shape: the order runs later,
        inside the confirmation, by which time the loop in `stage_cast` has moved on - so a
        closure written inline would fire whichever power the loop ended on, at whichever point.
        """
        book = self.spellbook_id()
        return lambda: self._issue(
            label,
            lambda: self.session.cast(power.power, power.form, position, source_id=book),
        )

    def stage_cast(self) -> str | None:
        """Fire one power, at the best thing the map is currently offering it.

        One per cycle like every other order here, and the ordering inside `castable_powers` is
        what decides which. A power with nothing worth hitting returns nothing and keeps its
        charge - that is the stage working, not the stage failing.
        """
        for power in self.castable_powers():
            aimed = self.aim(power)
            if aimed is None:
                continue
            position, what = aimed
            key = f"cast:{power.power.lower()}"
            label = f"cast {power.effect}"
            # Read before the order goes out, because accepting it is what moves the number: the
            # frame recorded here is the one that has to *change* for the next cycle to believe
            # the engine's answer. See `ready`.
            before = self.session.power_cooldowns(self.spellbook_id()).get(power.power)
            landed = self.confirm_cast(power, position, self.cast_on(power, position, label))
            if before is not None:
                self._cast_frame[power.power] = before
            if landed is None:
                # Sent, and nothing observable to check it against - see `confirm_cast`. Recorded
                # as exactly that rather than as a success: this is the case that reported 14/14
                # for a power the engine was refusing every time.
                print(f"    {label:<16} sent (a buff leaves no trace to confirm)")
                self.ledger.record(label, None)
            else:
                self._report(label, landed, "landed", "NOTHING HAPPENED - order discarded")
                self._strike(key, landed)
                if not landed:
                    # **A refused cast waits out the whole recharge before trying again.** By
                    # far the likeliest reason a well-aimed cast is discarded is that the engine
                    # is still recharging it, and the bot's own clock cannot see that - it is
                    # reset by a restart and blind to any cast made outside this process. The
                    # flat three-strikes bench is *shorter* than most recharges (120s against
                    # 180-940), so it retried inside the cooldown and failed again: one measured
                    # run refused Rebuild nine times and another spent most of a match refusing
                    # powers that had each just fired successfully.
                    #
                    # Treating the failure as if it had fired costs at most one window of
                    # opportunity when the real cause was the target, and that case is already
                    # covered - the aim simply will not offer it again until the target is back.
                    #
                    # **Unless the ground is the better explanation.** A power that places a
                    # structure is refused by *where* it was aimed far more often than by its
                    # clock, and that cause is recorded and routed around below - so charging it
                    # a recharge as well punishes it twice for one refusal and leaves the next
                    # spot untried for minutes. Measured: Lone Tower bought and cast at 367s,
                    # refused on placement, and then not attempted again until 781s.
                    #
                    # **And a power that has never been cast cannot be recharging.** `ready` let
                    # it through on the "never cast" branch, so whatever the engine objected to,
                    # it was not the clock - and lengthening the clock is the one response that
                    # cannot be right.
                    first_cast = power.power not in self._cast_at
                    if power.effect == EFFECT_BUILD:
                        # A structure refused where it was placed says something about that
                        # place, which nothing else here can read - so the spot is set aside and
                        # the next scan works past it. Set aside rather than struck off: the
                        # objection may have been a battalion standing there, which will move.
                        # See `open_ground`.
                        self._refused_ground[position] = time.monotonic() + CAST_GROUND_COOLDOWN
                    elif not first_cast:
                        self._cast_at[power.power] = time.monotonic()
                        # And wait longer than that next time. Waiting out the *declared*
                        # recharge is what produced these refusals in the first place - it is an
                        # estimate of a number Edain rescales, and a measured run had it a few
                        # seconds short. See `CAST_BACKOFF`.
                        self.back_off(power)
                    # Name the target on the way out. A refusal with no target in it is the one
                    # log line that cannot be diagnosed afterwards: "Rebuild refused" is equally
                    # consistent with a recharge that has not elapsed, a target the engine will
                    # not accept, and an aim that picked something absurd - and those want three
                    # different fixes. Measured the hard way, on a run that refused it six times.
                    return f"cast {power.power} refused at {what} {position}"
            self._cast_at[power.power] = time.monotonic()
            self._ready_since.pop(power.power, None)
            return f"cast {power.power} on {what} ({power.reload_seconds:.0f}s recharge)"
        return None
