"""Taking ground, holding it, meeting what comes home, and finally going to end the match.

The four stages that command the army, and the target selection behind them. `stage_push` is the
last of those and the newest: see `pushing` for the pair of gates that opens it, and
`sage_mods.edain.bot` for the two earlier pushes that were measured and removed, both of which
fired while there was still map to take.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from math import ceil

from sage_live.api.observation import GameObject, Vec3, distance
from sage_live.api.session import Sent
from sage_mods.edain.bot.mechanics.signal_fire import SignalFire
from sage_mods.edain.bot.recruiting import Recruiting
from sage_mods.edain.bot.tuning import (
    AIM_STANDOFF,
    ARCHER,
    ARCHER_BEHIND,
    ARCHER_CONTACT,
    BUILD_RADIUS,
    CAPTURE,
    CAPTURE_RADIUS,
    CAPTURE_RESERVE,
    CAVALRY_MIN,
    CAVALRY_PARTY,
    CAVALRY_REORDER,
    CLOSING,
    CONTEST_ODDS,
    CONTEST_RADIUS,
    DEFEND_COMMITMENT,
    DEFEND_CONTACT,
    DEFEND_KEEPALIVE,
    DEFEND_RADIUS,
    DEFEND_REORDER,
    EXPAND_MIN_ARMY,
    EXPAND_PARTY,
    EXPAND_PATIENCE,
    FLAG_COOLDOWN,
    FLAG_GIVE_UP,
    FLAG_PATIENCE,
    GUARD_ODDS,
    GUARD_PER_RAIDER,
    LAIR_RADIUS,
    MAX_CAVALRY_ORDERS,
    MAX_RESPONSES,
    OPENING_EXPAND_MIN_ARMY,
    PUSH_ARMY,
    PUSH_ARRIVED,
    PUSH_CONTROL,
    PUSH_SPENT,
    RAID_PARTY,
    RAID_STANDOFF,
    RESPONSE_ODDS,
    SCREEN_REACH,
    SIEGE,
)


def _centre_of(force: list[GameObject]) -> Vec3:
    """The mean position of a force - where it is, for deciding what is nearest to it."""
    return (
        sum(o.position[0] for o in force) / len(force),
        sum(o.position[1] for o in force) / len(force),
        sum(o.position[2] for o in force) / len(force),
    )


class Warfare(Recruiting, SignalFire):
    """Taking ground, holding it, and meeting what comes home.

    `SignalFire` is a faction mechanic mixed in beside the generic stages rather than woven into
    them - see `sage_mods.edain.bot.mechanics`. It is inert on any seat that is not Men, and it
    is here rather than lower down because the two places it touches are both warfare's: which
    building a claimed settlement raises, and the stage that spends the rider's charges.
    """

    def expand_min_army(self) -> int:
        """How many battalions must exist before the force goes plot-hunting.

        Two answers, because the question changes: in the opening the starting battalions are
        the claiming force and there is nothing yet to defend, and afterwards a force sent out
        is a force off the wall.
        """
        return OPENING_EXPAND_MIN_ARMY if self.opening() else EXPAND_MIN_ARMY

    def expansion_parties(self) -> dict[int, list[GameObject]]:
        """The parties that go out and take settlements, kept up to date and topped up.

        **One army walking as one body is what this replaces**, and the map is the reason: a
        settlement is taken by standing on it, so two places can be claimed at once by two small
        groups and never by one large one. Each party carries its own flag commitment.

        Four things happen here, in order, and each is bookkeeping rather than a decision:

        - battalions that have died leave their party, and a party that has lost everyone is
          dissolved and gives its flag back;
        - a party below `EXPAND_PARTY` takes whatever is spare, **oldest party first**, so the
          group already out in the field is the one that gets stronger;
        - anything still spare gathers in `_forming`, which is the only place a battalion ever
          idles;
        - `_forming` becomes a party of its own once it is at strength.

        **The first party is seeded whatever its size**, because the battalions a match starts
        with have nothing else to do and a settlement claimed in the first minute pays for the
        whole match. Every party after it waits until it is full, which is the difference
        between reinforcing a group and dribbling battalions across the map one at a time.
        """
        claimed = {i for ids in self._groups.values() for i in ids} | set(self._cav)
        alive = {o.object_id: o for o in self.army() if o.object_id not in claimed}

        for party in list(self._parties):
            kept = tuple(i for i in self._parties[party] if i in alive)
            if kept:
                self._parties[party] = kept
            else:
                del self._parties[party]
                self._party_flag.pop(party, None)
        self._forming = tuple(i for i in self._forming if i in alive)

        held = {i for ids in self._parties.values() for i in ids} | set(self._forming)
        spare = [o.object_id for o in alive.values() if o.object_id not in held]

        if not self._parties and spare:
            # The opening: whatever the match handed over is a party, and it leaves now.
            self._parties[self._next_party] = tuple(spare)
            self._next_party += 1
            spare = []

        for party in sorted(self._parties):
            if not spare:
                break
            room = EXPAND_PARTY - len(self._parties[party])
            if room > 0:
                self._parties[party] += tuple(spare[:room])
                spare = spare[room:]

        self._forming += tuple(spare)
        if len(self._forming) >= EXPAND_PARTY:
            self._parties[self._next_party] = self._forming
            self._next_party += 1
            self._forming = ()

        return {
            party: [alive[i] for i in ids if i in alive]
            for party, ids in sorted(self._parties.items())
        }

    def screen(
        self, force: list[GameObject], target: GameObject, key: str
    ) -> tuple[list[GameObject], str | None]:
        """Peel part of the party off to fight what is nearby, and say who went.

        **A building does not shoot back and does not run away, so the whole party pointing at
        one while enemies stand next to it is the worst arrangement available.** The party is
        knocking down a lair or a settlement; the troops around it are hitting the party in the
        back the entire time, and nothing in the party is hitting them. Somebody has to turn
        round, and this decides who.

        **Archers first, because for them it is not just a screen.** A structure is the wrong
        thing to point a bow at in any case - the archers walk into the defenders' reach to shoot
        a building that was never going to shoot back - so if there are bows in the party they
        are the ones with something better to do. That was this method's whole original job.

        **Otherwise one battalion, which is the change.** A party of pure infantry used to send
        every last man at the building and take the beating; now the one nearest the threat turns
        to meet it. One rather than several because the building is still the objective and a
        screen that takes half the party is just the fight the party was avoiding - and never the
        whole force, so there is always somebody still swinging at the target.

        Only when the party's own target is a building: against troops the party already has the
        right idea, and splitting there would be two half-strength fights. Returns whoever was
        given their own order, so the caller sends the rest at the structure without them.
        """
        if not self.statics.has_kind(target.template_name, "STRUCTURE"):
            return [], None
        if len(force) < 2:
            # One battalion cannot both screen and attack, and the target is the reason it came.
            return [], None
        archers = [o for o in force if self.role(o, ARCHER)]
        pointed = archers if archers and len(archers) < len(force) else force
        alive = [
            o
            for o in self.observation.objects
            if self.hostile(o) and min(p.distance_to(o.position) for p in pointed) <= SCREEN_REACH
        ]
        if not alive:
            return [], None
        mark = min(alive, key=lambda o: min(p.distance_to(o.position) for p in pointed))
        if archers and len(archers) < len(force):
            return archers, self.engage(archers, mark, "what is in reach", f"{key}:bows")
        nearest = min(force, key=lambda o: o.distance_to(mark.position))
        return [nearest], self.engage([nearest], mark, "what is on us", f"{key}:screen")

    def worth_taking(
        self, army: list[GameObject], held_flag: int | None, spoken_for: set[int]
    ) -> GameObject | None:
        """The nearest external plot this army could actually take, or None.

        **Nearest was the whole rule, and nearest is not the same as takeable.** The flag a
        measured match picked was the closest one and was also held by up to twelve defenders;
        because the choice never reconsidered, the force went back to it every cycle for the
        rest of the match. Distance still decides between candidates - a near expansion is
        worth more than a far one - but only among the ones the force can expect to clear.

        A flag already ours skips the odds test: nothing has to be beaten to build on it, and
        an unpack left undone is a capture paid for and never collected.

        **Committed to, once chosen.** Re-deciding every cycle is what stopped expansion dead
        after the first two settlements: the candidates the force cannot reach yet stay
        candidates, so the nearest acceptable one kept changing as defenders wandered in and out
        of contest range, and each change restarted the walk. Measured: two settlements taken in
        the first minute, then 100 cycles cycling between plots 244, 243, 54, 247 and 45 without
        capturing one of them. A flag is held until it is taken, abandoned, or blocked - the
        three places a party's flag is cleared.

        `spoken_for` is what the other parties are already going to, so two of them never walk
        to the same settlement - the whole point of splitting them up.
        """
        mine = self.session.player_index
        # Measured against the party that would actually go, not against the army: an
        # under-strength party has to decline what it cannot beat, which is what makes it safe
        # to send one out before it is full.
        beatable = len(army) * CONTEST_ODDS
        now = time.monotonic()
        candidates = [
            flag
            for flag in self.external_plots()
            if self._blocked_flags.get(flag.object_id, 0.0) <= now
            and flag.object_id not in spoken_for
        ]
        held = next((f for f in candidates if f.object_id == held_flag), None)
        if held is not None:
            return held
        for flag in candidates:
            if flag.owner_index == mine or len(self.defenders(flag)) <= beatable:
                return flag
        return None

    def unpack_plot(self, plot: GameObject) -> tuple[Callable[[], Sent], str, str | None] | None:
        """The order that builds on `plot`, chosen from the plot's own live buttons.

        **The two unpack orders are not interchangeable and the plot does not tell you which
        it takes - its palette does.** A claimed settlement offers explicit per-building
        buttons and takes `unpack(template)`; an outpost, castle or camp keeps a single
        argument-less claim and takes `castle_unpack()`. Sending the wrong one is not a
        malformed order: the engine consumes it, charges nothing, builds nothing and reports
        nothing, which is indistinguishable from the order being broken.

        That is not a distinction that can be drawn from the template either, because claiming
        a settlement *changes* its palette - a `CommandSetUpgrade` swaps the neutral claim
        button for the owner's faction buttons the instant `owner_index` flips. So the buttons
        are read against the upgrades actually held.

        **Which of them, once there is more than one, is the plan's call.** A Men settlement
        offers three - the farm, the beacon and the ranger tents - and taking the first meant
        every settlement on the map was a farm, because slot 1 is the farm and the slots do not
        move. `wanted_external` picks between the families the plan names; the first button is
        still the answer for everything it does not recognise, which is every outpost (whose
        slot 1 is the argument-less claim) and every faction with no `external` list.

        Returns None when the palette offers nothing, which is a plot to leave alone rather
        than one to guess at. The third element is what will be built, for a caller that wants
        to price it - None for `castle_unpack`, which names nothing because the engine reads
        the template off the plot's own `CastleBehavior`.
        """
        me = self.observation.me
        held = {u.lower() for u in (me.upgrades if me is not None else ())}
        held |= {u.lower() for u in plot.upgrades}
        buttons = self.statics.unpack_buttons(plot.template_name, held)
        if not buttons:
            return None
        offered = tuple(b.template for b in buttons if b.explicit and b.template)
        # **The signal fire outranks the balance, because it is a one-off and the balance is
        # not.** `wanted_external` is asking which of two interchangeable incomes is further
        # behind - a question that will be asked again at the next flag and the one after. The
        # fire is asked once per match and only where it will survive, so a settlement that
        # qualifies is the settlement to spend it on; there may not be another. It declines on
        # every other plot, and the balance answers as usual.
        wanted = None
        if offered:
            wanted = self.signal_fire_site(plot, offered) or self.wanted_external(offered)
        button = next((b for b in buttons if b.template == wanted), buttons[0])
        template = button.template
        if button.explicit and template is not None:
            # **Named, and trimmed the way `stage_build` trims its own.** The label is what the
            # end-of-run ledger counts by, and a flat `"unpack"` reported 4 of 27 without saying
            # 4 of *what* - the one number that would have said whether a template was being
            # refused or the plots were simply contested. The slice drops the faction prefix and
            # caps the column, so `GondorFarm_Extern` reads `unpack Farm_Exte`.
            return (lambda: self.session.unpack(template), f"unpack {template[6:15]}", template)
        return (self.session.castle_unpack, "castle_unpack", None)

    def drop_flag(self, flag: GameObject, why: str, party: int | None = None) -> None:
        """Give up on a flag for `FLAG_COOLDOWN`, forgetting everything measured about it."""
        self._closest.pop(flag.object_id, None)
        self._stalled.pop(flag.object_id, None)
        self._spent.pop(flag.object_id, None)
        self._blocked_flags[flag.object_id] = time.monotonic() + FLAG_COOLDOWN
        # Counted as well as timed, because the two answer different questions - see
        # `_flag_failures` and `winnable_flags`. The cooldown decides when to try again; the tally
        # is what eventually admits that trying again is not working.
        self._flag_failures[flag.object_id] = self._flag_failures.get(flag.object_id, 0) + 1
        if party is not None:
            self._party_flag.pop(party, None)
        self.release(CAPTURE)
        print(f"      plot {flag.object_id}: {why}; giving it up for {FLAG_COOLDOWN:.0f}s")

    def giving_up(
        self, flag: GameObject, closest: float, engaged: bool, party: int | None = None
    ) -> str | None:
        """Why this capture should be abandoned, or None while it is still going somewhere.

        **Closing the distance is the progress, not standing in range.** Counting cycles that
        ended out of range gave up on flags that were merely far away: an undefended plot the
        force went on to capture was abandoned mid-walk, because eight cycles is shorter than the
        walk. What separates a force that is walking from one that is dying is whether it is
        getting closer.

        **And arriving is progress too, which is the correction the merged force needed.** Once
        the force is in the fight for the flag the distance stops shortening by construction - it
        is standing next to a lair hitting it - so the closing test alone reads the moment the
        capture starts working as the moment it failed. `engaged` is measured against
        `LAIR_RADIUS` rather than `CONTEST_RADIUS` because the thing being killed is usually the
        lair, and a lair stands outside contest range of the flag it garrisons.

        That rule has no natural end on its own, so `FLAG_PATIENCE` caps the whole commitment.
        A force parked next to something it cannot break reports progress for ever otherwise.
        """
        key = flag.object_id
        self._spent[key] = self._spent.get(key, 0) + 1
        best = self._closest.get(key)
        if engaged or best is None or closest < best - CLOSING:
            # Only ever record the nearest reached. Being engaged resets the patience without
            # moving the mark, so a force that drifts back out gets no fresh, easier target.
            self._closest[key] = min(closest, best) if best is not None else closest
            self._stalled.pop(key, None)
        else:
            self._stalled[key] = self._stalled.get(key, 0) + 1
        if self._stalled.get(key, 0) >= EXPAND_PATIENCE:
            self.drop_flag(flag, f"{EXPAND_PATIENCE} cycles without getting closer", party)
            return "abandoned, the force was not getting there"
        if self._spent[key] >= FLAG_PATIENCE:
            self.drop_flag(flag, f"{FLAG_PATIENCE} cycles committed with nothing to show", party)
            return "abandoned, it has taken too long"
        return None

    def capture_price(self, flag: GameObject) -> int:
        """What building on `flag` will cost, as well as it can be known before arriving.

        **Exact once the flag is ours, a guess before that, and the guess is the common case.**
        Claiming changes a plot's palette - a `CommandSetUpgrade` swaps the neutral claim button
        for the owner's faction buttons - so an unclaimed settlement offers only the argument-less
        claim, which names no template and therefore quotes no price. That is precisely the state
        the force spends its walk in.

        `CAPTURE_RESERVE` covers it until then. Reserving a little too much costs one delayed
        battalion; reserving nothing costs the walk, the fight and the capture, which is what the
        unreserved version actually did.
        """
        chosen = self.unpack_plot(flag)
        if chosen is None:
            return CAPTURE_RESERVE
        template = chosen[2]
        if template is None:
            return CAPTURE_RESERVE
        return max(CAPTURE_RESERVE, self.statics.build_cost(template))

    def raise_settlement(self, flag: GameObject, party: int | None = None) -> str:
        """Build on a flag that is already ours.

        The plot is not consumed by building on it, so the oracle is what *appeared* near it,
        never the flag disappearing.

        **A failure parks the flag, not the stage.** This used to strike against `"expand"`, so
        three refused unpacks - which is what a measured run's `unpack 3/15` mostly consists of -
        benched the entire expansion for three minutes at a time, on a bot whose only job is
        expanding. A plot that will not take a building is one plot's problem.
        """
        chosen = self.unpack_plot(flag)
        if chosen is None:
            return f"plot {flag.object_id}: claimed, but its palette offers no unpack"
        send, label, template = chosen
        if template is not None and not self.afford(template, purpose=CAPTURE):
            # The same silent discard as any other unaffordable order, and the one that hurts
            # most: a claimed flag left unbuilt is a capture paid for and never collected. The
            # reservation is what makes this a wait rather than a race - see `Orders.reserve`.
            return f"plot {flag.object_id}: claimed, saving for {template}"
        if not self.select([flag]):
            return f"plot {flag.object_id}: claimed, but the plot would not select"
        ok = self.session.confirm_appeared(
            lambda: self._issue(label, send),
            near=flag.position,
            within=BUILD_RADIUS,
        )
        self._report(label, ok, "built on the plot", "NOTHING APPEARED - order discarded")
        key = f"unpack:{flag.object_id}"
        self._strike(key, ok, seconds=FLAG_COOLDOWN)
        # **The second strike, against the building rather than the plot.** The one above asks
        # "is this flag worth another try"; this asks "is this *template* worth another try
        # anywhere", and without it a settlement building the engine keeps refusing is chosen
        # for ever. `wanted_external` ranks by how many are standing, so a family that never
        # succeeds stays permanently at zero and permanently furthest behind - a run measured
        # `unpack 4/27` with the balance able to see failure only as "still none of those".
        family = self.external_family(template) if template else None
        if family is not None:
            self._strike(f"unpack:{family}", ok, seconds=FLAG_COOLDOWN)
        if ok:
            # Taken and built on, so the commitment is discharged and the next cycle is free to
            # pick the next flag.
            self._closest.pop(flag.object_id, None)
            self._stalled.pop(flag.object_id, None)
            self._spent.pop(flag.object_id, None)
            if party is not None:
                self._party_flag.pop(party, None)
            self.release(CAPTURE)
        elif self._cold(key):
            self.drop_flag(flag, "three unpacks refused", party)
        return f"plot {flag.object_id}: {label}"

    def stage_expand(self) -> str | None:
        """Take a settlement flag: kill what garrisons it, stand on it, then build.

        Three problems, and only the last is an order this API issues directly. **Ownership is
        not orderable at all** - there is no capture order. A flag becomes yours because your
        units are near it and no enemy is, so the first two steps are movement and a fight, and
        the third only works once those are done.

        Which order raises the building is `unpack_plot`'s decision, not this one's: a claimed
        settlement takes `unpack(template)` and an outpost, castle or camp takes the
        argument-less `castle_unpack()`, and the palette is the only thing that says which.

        **The lair before the defenders, and that ordering is most of the fix.** A settlement's
        guards are output rather than opposition - the lair replaces every one killed - so a
        force that fights what is standing on the flag wins every fight and never takes the flag.
        `garrison_of` names the thing making them, and it is what gets attacked whenever there is
        one, whether or not anything is currently standing in contest range.

        **The lair before the building, too**, for the same reason one step later: a flag flips
        on proximity, so it can be ours while its lair still stands, and a farm raised in front
        of one is a farm the slaves take down as fast as it goes up.

        **And the whole field force goes.** The three-battalion squad this replaces refused any
        flag with more than two defenders (`CONTEST_ODDS` is measured against whoever is sent),
        and died on the approach to the ones it did accept. Measured over six runs: `unpack` 3/15
        and 7/19, twelve flags abandoned, map control never past 44%.

        A flag is given up on three ways - too many defenders to be worth it, `EXPAND_PATIENCE`
        cycles with no progress, and `FLAG_PATIENCE` cycles committed at all - and `giving_up`
        owns the last two.

        **Taking ground and taking it back are the same job, and distance decides which.**
        `reclaim_targets` - what the opponent has built on our side of the map - lived only in
        `raid_target`, and `stage_raid` only runs when this stage finds nothing to do; so for as
        long as one free flag remained anywhere, a settlement taken *back* was invisible to every
        stage. A measured run watched control oscillate 31-56% for two hundred cycles doing
        exactly that: claiming new flags at one end of the map while losing built ones at the
        other, every stage reporting success.

        Neither outranks the other, because the thing that separates them is the walk. A free flag
        is cheaper - nobody has to be beaten to build on it - and an enemy-held one is worth more,
        since razing it stops paying for the army that comes at us *and* hands its own flag back
        to this stage on the next cycle. Those roughly cancel, and what does not cancel is the
        distance: the force spends its match walking, so the nearer of the two is the one worth
        going to whichever kind it is.
        """
        self._expanding = False
        self._idle_parties = {}
        if self.besieged():
            return None
        said = []
        spoken_for: set[int] = set()
        for party, force in self.expansion_parties().items():
            if not force:
                continue
            line = self.take_flag(party, force, spoken_for)
            if line is None:
                self._idle_parties[party] = force
            else:
                said.append(line)
        self._expanding = bool(said)
        return " | ".join(said) or None

    def take_flag(self, party: int, force: list[GameObject], spoken_for: set[int]) -> str | None:
        """One party's turn: reclaim the nearest thing of ours they hold, or take a settlement.

        None means this party found nothing to do, and `stage_raid` picks it up. `spoken_for`
        collects the flags already claimed by parties ahead of it this cycle, so two parties
        never walk to the same settlement.
        """
        key = f"party:{party}"
        home = self.base_centre()
        recovering = self.reclaim_targets()
        held = recovering[0] if recovering else None
        flag = self.worth_taking(force, self._party_flag.get(party), spoken_for)
        if held is not None and (flag is None or held.distance_to(home) < flag.distance_to(home)):
            # Nearer to free than the nearest one to claim. The flag commitment is deliberately
            # left standing: this is the same job at a closer address, and razing the building
            # here usually puts a flag on the list that is nearer still.
            return f"reclaim: {self.engage(force, held, 'ground of ours they hold', key)}"
        if flag is None:
            return None
        self._party_flag[party] = flag.object_id
        spoken_for.add(flag.object_id)
        # **Set the price aside now, not on arrival.** The walk is the whole problem: a force
        # three cycles out from a settlement used to arrive at a balance that recruiting had
        # spent while it marched, so the fight and the walk bought nothing and the flag sat
        # claimed-but-empty for as long as the queues stayed hungry. Re-reserved every cycle
        # rather than accumulated - `reserve` is keyed, so this replaces itself.
        self.reserve(CAPTURE, self.capture_price(flag))

        contested = self.defenders(flag)
        nest = self.garrison_of(flag)
        # **A flag can become ours while the thing guarding it is still standing**, because
        # ownership is proximity: the force walks at the lair, passes close enough to flip the
        # flag, and this branch used to fire on the next cycle and never consult `garrison_of`
        # again. Measured live on plot 216 - `DunlandGoblinLair` left alive at 81% with its
        # `DunlandLairHole` intact 184 away, a farm raised on the flag between them, and the
        # farm knocked down and rebuilt twice by the slaves the lair kept replacing. Building
        # first is not merely premature there, it is gold spent on a building already lost.
        if nest is None and flag.owner_index == self.session.player_index and not contested:
            return self.raise_settlement(flag, party)

        closest = min(o.distance_to(flag.position) for o in force)
        near = sum(1 for o in force if o.distance_to(flag.position) < CAPTURE_RADIUS)
        quit_reason = self.giving_up(flag, closest, engaged=closest < LAIR_RADIUS, party=party)
        if quit_reason is not None:
            return f"plot {flag.object_id}: {quit_reason}"

        if nest is not None:
            what = f"its {self.nest_word(nest)}"
            # The screen meets the lair's output; the rest knock the lair down. See `screen`.
            screened, fighting = self.screen(force, nest, key)
            shot = {o.object_id for o in screened}
            rest = [o for o in force if o.object_id not in shot] or force
            said = self.engage(rest, nest, what, key)
            if fighting:
                said = f"{said}, screen: {fighting}"
        elif contested:
            target = min(contested, key=lambda o: o.distance_to(flag.position))
            said = self.engage(force, target, f"{len(contested)} defenders", key)
        else:
            said = self.march(force, flag.position, "the flag", key)
        return f"plot {flag.object_id}: {said}, {near} in range, nearest {closest:.0f}"

    def raid_target(self, spoken_for: set[int] | None = None) -> tuple[GameObject, str] | None:
        """What the force should hit when there is no flag to take, and why.

        **Expansions before bodies.** Killing a battalion costs them one battalion; killing the
        settlement that pays for battalions costs them every one it would have bought, and it
        hands the plot back to `stage_expand`. Both jobs are the same order, so this is a
        priority rather than two stages.

        **Nests before loose troops, and that ordering is the whole difference between a bot
        that takes a map and one that patrols it.** A lair replaces every slave killed near it,
        so on a map with six of them there is always something in the open to chase and the
        force never runs out of the cheapest possible target - it kills twelve wildmen, twelve
        more walk out, and no flag is any freer than it was. The lair itself is finite, and its
        hole after it. See `nests`.

        **Nothing here needs an opponent to exist.** `enemy` answers None in a skirmish with one
        player, and this used to return None with it: an army in that match had no target of any
        kind and stood in its own base for the whole run. The seat is now only used for the
        standoff that keeps the force out of a defended keep, so its absence removes a
        restriction rather than the target list.

        Their main base is deliberately out of scope - anything within `RAID_STANDOFF` of the
        centre of what they own is a fight over ground this bot is not trying to hold, and the
        module docstring records what came of marching an army into one.
        """
        seat = self.enemy()
        centre = seat[1] if seat is not None else None
        home = self.base_centre()
        claimed = spoken_for or set()

        def theirs(obj: GameObject) -> bool:
            """Whether this stands far enough from their seat to be a raid rather than a push."""
            return obj.object_id not in claimed and (
                centre is None or obj.distance_to(centre) > RAID_STANDOFF
            )

        # **Ground of ours before ground of theirs.** Both are enemy buildings and the order that
        # breaks them is the same, so the only question is which is worth the walk - and a
        # settlement they took on our side of the map is worth more than one they built on
        # theirs. It is nearer, so the force arrives sooner and is closer to home when it does;
        # the flag underneath it goes straight back to `stage_expand`; and leaving it standing is
        # how a bot conquers a map and then loses it back building by building. See
        # `reclaim_targets`, which is deliberately not filtered by `theirs` - a foothold inside
        # our own base is the clearest recovery there is and would fail that test only if the
        # opponent's centre had already walked on top of us.
        recovering = [o for o in self.reclaim_targets() if o.object_id not in claimed]
        if recovering:
            return recovering[0], "ground of ours they hold"

        outlying = [o for o in self.enemy_expansions() if theirs(o)]
        if outlying:
            return min(outlying, key=lambda o: o.distance_to(home)), "an expansion"

        # Every other nest on the map, the ones standing over a flag first. Each one razed is a
        # settlement that becomes takeable and stays takeable, which is what "take over the map"
        # actually consists of; the rest are cleared on the way because they will otherwise keep
        # feeding troops into the ground the expansions have to cross.
        flags = self.external_plots()
        nests = [o for o in self.nests() if theirs(o)]
        if nests:
            over_flag = {
                nest.object_id
                for flag in flags
                for nest in (self.garrison_of(flag),)
                if nest is not None
            }
            nest = min(nests, key=lambda o: (o.object_id not in over_flag, o.distance_to(home)))
            return nest, f"a {self.nest_word(nest)}"

        # **The keep itself, and only once the map has nothing else left to offer.**
        #
        # `theirs` holds everything within `RAID_STANDOFF` of their seat out of scope, which is
        # what stops this being a push - and for every branch above that is right. It is also the
        # reason a run could take the whole map and still not win: what `finished` counts is
        # buildings carrying `MP_COUNT_FOR_VICTORY`, and those sit exactly where the standoff
        # forbids the force from going. A match that razes every lair and holds every flag then
        # stands in the open forever, which is what the last three runs did.
        #
        # **Last, which is the whole of what makes it safe.** The module docstring records two
        # pushes and what they cost, and the failure was never the target - it was the gate. A
        # battalion count asked a question nobody can answer from inside a match; a stalemate
        # timer turned a 600-cycle undefeated run into a 394-cycle defeat, "because committing did
        # not create an army that could win, it only stopped the expansion that was paying for
        # one". This gate cannot do that: it fires only when `reclaim_targets`, `enemy_expansions`
        # and every nest are empty and there is no flag left worth walking to, so by construction
        # there is no expansion left for it to stop.
        #
        # **`winnable_flags` rather than `flags`, and that correction is what made it reachable.**
        # Asking for zero free flags sounds like the same thing and is not: two measured runs
        # finished at 94% and 88% map control with armies of 19 and 24 doing nothing, because one
        # or two flags they had already failed at repeatedly still counted as map left to take.
        # A flag is only evidence of unfinished business while the force has a way of finishing
        # it.
        #
        # **And it still could not fire, because the target list was empty by construction.** This
        # asked for `hostile(o) and counts_for_victory(o)`, and `hostile` excludes everything
        # `STRUCTURE` or `IMMOBILE` - while 573 of the game's 574 templates carrying
        # `MP_COUNT_FOR_VICTORY` are structures. So every correction above was made to a branch
        # that had no reachable target either way. `victory_targets` is the list this always
        # meant.
        finishing = [o for o in self.victory_targets() if o.object_id not in claimed]
        if not self.winnable_flags() and finishing:
            return min(finishing, key=lambda o: o.distance_to(home)), "what is left to win"

        # Nothing standing is worth the walk, so keep their numbers down instead. Units near our
        # own base are `stage_defend`'s business and are left to it.
        troops = [
            o
            for o in self.observation.objects
            if self.hostile(o) and o.distance_to(home) > DEFEND_RADIUS and theirs(o)
        ]
        if not troops:
            return None
        return min(troops, key=lambda o: o.distance_to(home)), "troops in the open"

    def winnable_flags(self) -> list[GameObject]:
        """Free flags this army could still plausibly take - the test for "is the map finished".

        **The difference between "is there map left" and "is there map left I can have".** Every
        other caller wants `external_plots` and should keep using it: a flag abandoned three times
        is still worth another attempt later, because the thing that beat the force was usually
        temporary and `FLAG_COOLDOWN` exists to schedule exactly that retry. This is the one
        question where the honest answer is different - whether the map is finished enough to go
        and end the match - and there a flag the force keeps bouncing off is not unfinished
        business, it is a standing excuse never to commit.

        **Two ways a flag stops being winnable, and the second is the one that actually happened.**

        Abandonment is counted rather than timed, because the cooldown expires and the count does
        not: gating on "blocked right now" would open the branch during the cooldown and shut it
        the moment the flag became a candidate again, which is the same order-cancelling flicker
        `settle_groups` was written to stop - only here it would be the whole army turning round.

        But counting abandonment alone missed the case entirely, because **a flag nobody attempts
        is never abandoned**. `worth_taking` declines a flag whose defenders outnumber the *party*
        that would go, so a heavily garrisoned settlement is silently never chosen, never fails,
        and keeps its zero. Measured at cycle 301 of a run: 94% map control, eighteen battalions
        across five parties, every lair razed - and the decision line was `recruit` and nothing
        else, cycle after cycle, because one flag no party would accept still counted as map left
        to take and the victory branch behind it never opened.

        So the odds are asked again here, against the **whole army** rather than a party. That is
        the right measure for this question and not for `worth_taking`'s: a party has to decline
        what it alone cannot beat, but "is the map finished" means "is there anything left I could
        take if I committed everything" - and if the answer is no, the enemy's keep is a better
        use of the army than a settlement that will never fall to it.
        """
        beatable = len(self.army()) * CONTEST_ODDS
        mine = self.session.player_index

        def reachable(flag: GameObject) -> bool:
            if self._flag_failures.get(flag.object_id, 0) >= FLAG_GIVE_UP:
                return False
            # Already ours needs nothing beaten - an unpack left undone is still map to finish.
            return flag.owner_index == mine or len(self.defenders(flag)) <= beatable

        return [flag for flag in self.external_plots() if reachable(flag)]

    def nest_word(self, nest: GameObject) -> str:
        """ "lair" or "rebuild hole", so a log line says which half of the job this is."""
        if self.statics.is_rebuild_hole(nest.template_name):
            return "rebuild hole"
        return "lair"

    def stage_raid(self) -> str | None:
        """Break what the opponent holds outside their base, when there is no flag to take.

        **Each party's fallback job, party by party.** The battalions are `stage_expand`'s -
        this runs on the parties *that stage found nothing for*, which is either every flag being
        taken or every remaining one blocked or too well held. `decide` runs the two in that
        order and `_idle_parties` is what carries the leftovers across.

        **One target per party, not one for all of them**, which is the same reasoning that
        splits the expansion up: a raid is a walk to something stationary, so four battalions at
        each of two lairs breaks both while eight at one breaks one. What that must not become is
        the standing raiding party this replaced - six battalions with their own target list, so
        an army of twelve fought in two places and was outnumbered in both. The difference is
        that a party is only ever in one job per cycle, and `RAID_PARTY` is what stops a remnant
        of one being sent anywhere at all.

        Which is not a demotion: the list `raid_target` walks is mostly the *reason* there is
        nothing to expand to. Razing a settlement the opponent took puts its flag straight back
        on `external_plots`, and razing a lair takes the defenders off a flag that was refused
        for having too many. Both hand work back to the expansion that could not find any.
        """
        if self.besieged():
            return None
        said = []
        spoken_for: set[int] = set()
        for party, force in self._idle_parties.items():
            if len(force) < RAID_PARTY:
                continue
            chosen = self.raid_target(spoken_for)
            if chosen is None:
                break
            target, what = chosen
            spoken_for.add(target.object_id)
            key = f"raid:{party}"
            screened, fighting = self.screen(force, target, key)
            shot = {o.object_id for o in screened}
            rest = [o for o in force if o.object_id not in shot] or force
            line = f"raid: {self.engage(rest, target, what, key)}"
            said.append(f"{line}, screen: {fighting}" if fighting else line)
        return " | ".join(said) or None

    def remember_keeps(self) -> None:
        """Record where their victory buildings are while they can be seen, and forget the dead.

        **The fogged view has no memory and a player does.** `Observation.under_fog` reports what
        the seat can see *now*, with nothing carried over - so a force that has crossed the whole
        map and razed every lair still has no idea where the opponent's keep is the moment it
        walks away from it. That is not the position a human is in at 85% map control, and the
        gap is memory rather than vision.

        So this is the memory, and it is deliberately the narrow kind. A position is written only
        on a cycle where the building was genuinely in the fogged view; nothing consults the
        unfogged snapshot, so a keep that has never been scouted is not here and the push simply
        has nowhere to go until it is. Buildings are what makes that honest - they do not move,
        so a remembered position stays true in a way a remembered army never would.

        **Forgetting needs the force to be standing there.** Absence from the fogged view is
        ordinarily just distance, so a keep must not be dropped for being out of sight or the
        force turns round the moment it loses vision of its own destination. Within
        `PUSH_ARRIVED` the reading means the opposite: the army is on top of the place and can
        see it, and it is not there.
        """
        visible = {o.object_id: o for o in self.victory_targets()}
        for target in visible.values():
            self._seen_keeps[target.object_id] = target.position
        army = self.army()
        if not army:
            return
        for object_id, where in list(self._seen_keeps.items()):
            if object_id in visible:
                continue
            if any(o.distance_to(where) < PUSH_ARRIVED for o in army):
                del self._seen_keeps[object_id]

    def pushing(self) -> bool:
        """Whether the endgame is on. **Latched**, and that is most of the design.

        Two gates open it, both at `PUSH_CONTROL` / `PUSH_ARMY` of 0.75: three quarters of the
        map held, and the army at three quarters of its own command-point ceiling. Neither is a
        guess about being strong enough - the first says there is nothing much left worth taking
        and the second says the army has stopped growing because it is not allowed to grow.
        Measured over run 4, both were true from cycle 619 of 1400, and the run ended undecided
        with 105,012 gold banked.

        **Both were 0.05-0.10 higher and that was too late.** Run 8 fired the push at 81% control
        and then spent 250 cycles holding 88% of the map with 31,679 gold it could not spend,
        command-point capped, while the army halved from 28 to 14. The endgame arrived after the
        point at which committing would still have been cheap.

        **The latch is not an optimisation, it is the difference between a push and a flinch.** A
        push takes casualties immediately, so an unlatched gate un-commits on the first ones and
        the army turns round in front of the keep - which spends the walk, spends the battalions,
        and buys nothing. Committing has to survive its own cost.

        It is released at `PUSH_SPENT`, and that release is what keeps this from repeating the
        history in the module docstring: a stalemate timer once turned a 600-cycle undefeated run
        into a 394-cycle defeat because committing "did not create an army that could win, it only
        stopped the expansion that was paying for one". A force ground below two fifths of its
        ceiling is not going to finish anything, and the honest move is to go back to playing the
        match and meet both gates again from scratch.
        """
        fill = self.command_fill()
        if self._pushing:
            if fill < PUSH_SPENT:
                self._pushing = False
        elif self.map_control() >= PUSH_CONTROL and fill >= PUSH_ARMY:
            self._pushing = True
            self._push_since = time.monotonic()
            # The parties are dissolved rather than re-aimed, exactly as under siege: every
            # battalion is wanted in one place, and `expansion_parties` re-forms them from
            # whatever is left if the push is ever called off.
            self._parties.clear()
            self._party_flag.clear()
            self._forming = ()
            self._cav = ()
        return self._pushing

    def push_target(self) -> GameObject | None:
        """The nearest of their victory buildings the force can currently see."""
        army = self.army()
        if not army:
            return None
        centre = _centre_of(army)
        visible = self.victory_targets()
        return min(visible, key=lambda o: o.distance_to(centre)) if visible else None

    def push_aim(self) -> Vec3 | None:
        """Where to walk when none of their victory buildings is in sight - or None.

        The nearest one *remembered*, which is the only honest answer under fog. None means the
        opponent's keep has never been seen, and then there is nowhere to push to; that is a
        scouting failure rather than something to paper over with the unfogged snapshot.
        """
        army = self.army()
        if not army or not self._seen_keeps:
            return None
        centre = _centre_of(army)
        return min(self._seen_keeps.values(), key=lambda where: distance(centre, where))

    def stage_push(self) -> str | None:
        """The endgame: everything not holding the base, at what is left to win.

        **One target, and the whole force on it.** The parties exist because a settlement is
        taken by standing on it and two can be claimed at once; a keep is not that job. It is the
        one fight on the map where being outnumbered locally loses the match, so the splitting
        that takes the map is exactly wrong for ending it.

        Held back: whatever `stage_defend` claimed this cycle, and nothing else. Losing the base
        still ends the match, and the stage above this one has already taken what it needs.

        **A siege at home outranks the push**, which is the one case where turning round is
        right: `besieged` means more raiders than the whole army can meet, so there is no version
        of continuing that keeps the base. The push is latched and survives it - the force goes
        home, wins, and comes back.

        Three ways this reports nothing to do, and they are different failures worth telling
        apart in a log: no army, nothing of theirs in sight and nothing remembered either, or
        everything already claimed by the defence.
        """
        if self.besieged():
            return None
        held = {i for ids in self._groups.values() for i in ids}
        force = [o for o in self.army() if o.object_id not in held]
        if not force:
            return None

        target = self.push_target()
        if target is not None:
            screened, fighting = self.screen(force, target, "push")
            shot = {o.object_id for o in screened}
            rest = [o for o in force if o.object_id not in shot] or force
            said = f"push: {self.engage(rest, target, 'what is left to win', 'push')}"
            return f"{said}, screen: {fighting}" if fighting else said

        aim = self.push_aim()
        if aim is None:
            return "push: nothing of theirs has been seen to walk to"
        return f"push: {self.march(force, aim, 'their base', 'push')}"

    def besieged(self) -> bool:
        """Whether what is in the base needs more battalions than there are.

        **The difference between an attack and a nuisance, and nothing used to draw it.** Every
        stage that sends units anywhere stood down while anything hostile was within
        `DEFEND_RADIUS`, and the whole army was recalled to deal with it - which is right for a
        real assault and ruinous for one wandering creep. On a map covered in creeps, and with a
        base centre that walks out behind the expansions, that condition is close to permanently
        true: the expansion and the raid were both switched off by a warg.

        So an ordinary intrusion is answered by a guard sized to it, and everything else carries
        on. This is the case that is *not* ordinary - more raiders than the army as a whole can
        meet - and there the old behaviour is exactly right and everything comes home.

        **Measured against the whole army, not against what the field force left over.** With one
        force holding nearly every battalion, "spare" is empty by construction, so the version
        that asked about spare battalions would have called a single warg a siege on every cycle
        of every match - the same permanent stand-down by the other door.
        """
        raiders = self.raiders()
        if not raiders:
            return False
        return len(raiders) * GUARD_PER_RAIDER > len(self.army())

    def group_for(
        self, key: int, where: Vec3, threat: list[GameObject], taken: set[int]
    ) -> list[GameObject]:
        """The battalions assigned to defend one holding, sized to what is standing on it.

        **Slightly stronger than the threat, and nearest to it.** `RESPONSE_ODDS` is the whole
        specification of "slightly": matched one for one a group trades evenly and then loses to
        whatever walks in behind, and at double it is a second army the map is paying for.

        **`taken` is what higher-ranked holdings have claimed *this cycle*, and nothing else.**
        Reading the standing assignments instead made rank meaningless: a farm group formed three
        cycles ago kept its battalions, so the base - processed first, and the holding whose loss
        ends the match - could only draw on what a farm had left over. Measured, and it decided a
        match: twenty-one raiders in the base answered by three battalions with an army of eleven,
        because the other eight were out holding a farm nobody was attacking any more. Ranking
        decides who is served first only if being served first can take from those served later.

        The fill is taken nearest the holding, because a response that arrives late is a response
        to a building that has already burned; existing members are kept where they are still
        available, so a group that is already fighting is not dissolved and re-formed each cycle.
        """
        available = sorted(
            (o for o in self.army() if o.object_id not in taken),
            key=lambda o: o.distance_to(where),
        )
        wanted = min(len(available), ceil(len(threat) * RESPONSE_ODDS))
        group = self.detachment(available, self._groups.get(key, ()), wanted)
        self._groups[key] = tuple(o.object_id for o in group)
        return group

    def hold(self, key: int, where: Vec3, threat: list[GameObject], taken: set[int]) -> str | None:
        """Answer one threat with its own group: engage it, or gather if too few to win.

        See `GUARD_ODDS` for the gathering half. It is not a retreat - units fight whatever
        reaches them wherever they stand - it withholds only the *walk* into the middle of an
        enemy force, which is how a measured match fed an army of 34 in one battalion at a time
        while every cycle reported a defence.

        **The order is re-sent only when something has changed**, rather than on the 8-second
        re-aiming timer: the same raider was attacked six times across one approach and each of
        those orders was booked as a failure. See `DEFEND_KEEPALIVE`, and `confirm_engaged` for
        why damage alone is the wrong question to ask about something that can run away.
        """
        group = self.group_for(key, where, threat, taken)
        if not group:
            return None
        if len(group) < len(threat) * GUARD_ODDS:
            aim = where
            stale = time.monotonic() - self._group_ordered.get(key, 0.0) >= DEFEND_REORDER
            last = self._group_aim.get(key)
            if stale or last is None or distance(aim, last) > 200.0:
                if not self.select(group):
                    return None
                self.manoeuvre("regroup", lambda: self.session.attack_move(aim), group)
                self._group_aim[key] = aim
                self._group_ordered[key] = time.monotonic()
            return f"{len(threat)} against {len(group)} - gathering"

        target = min(threat, key=lambda o: distance(o.position, where))
        last = self._group_aim.get(key)
        moved_on = last is None or distance(target.position, last) > 200.0
        # **Re-aiming and re-ordering are different events.** A raider that moved, or a nearer
        # one taking its place, is a new decision and is answered at once. An order nothing has
        # invalidated is only re-sent as a keep-alive - see `DEFEND_KEEPALIVE` for the approach
        # that was re-ordered six times in fifty seconds and booked six failures for it.
        switched = target.object_id != self._group_target.get(key)
        since = time.monotonic() - self._group_ordered.get(key, 0.0)
        if not moved_on and not switched and since < DEFEND_KEEPALIVE:
            return f"{len(threat)} met by {len(group)}"
        if not self.select(group):
            return None

        # **A raider is not a building and does not wait to be hit.** Damage alone is the wrong
        # test here whatever the distance - see `confirm_engaged`, and the 0/7 that measured it.
        ok = self.confirm_engaged(
            target,
            group,
            lambda: self._issue(
                "defend", lambda: self.session.attack(target.object_id, target.position)
            ),
        )
        self._report("defend", ok, "went at the raider", "NOTHING HAPPENED - order discarded")
        self._group_aim[key] = target.position

        # **Only a *sent* order buys the keep-alive silence.** Recording the commitment whatever
        # happened was the bug that put a third of the army in a field doing nothing: game logic
        # discards a defend order after the stream has taken it, and stamping the target and the
        # clock anyway told the next cycle both that this group was already engaged with this
        # raider (`switched` false) and that it had been ordered a moment ago (`since` under
        # `DEFEND_KEEPALIVE`) - so it returned "met by" and issued nothing, for a full 30 seconds
        # per discard. Measured at cycle 400 of a live run: 27 discards against 52 sends, a
        # 17-battalion group parked on one farm, and `defend` the only order type failing at all.
        #
        # A failure now leaves both marks untouched, so the next cycle re-decides from scratch
        # and re-issues. That is the honest reading of what happened - nothing was sent, so
        # nothing is owed silence - and the cost of being wrong is one order, against the 30
        # seconds of standing still that being wrong the other way costs.
        if not ok:
            return f"{len(group)} could not be sent at {target.template_name} - retrying"
        self._group_target[key] = target.object_id
        self._group_ordered[key] = time.monotonic()
        return f"{len(group)} sent at {len(threat)} ({target.template_name})"

    def archers_in_melee(self) -> list[tuple[GameObject, GameObject]]:
        """Owned archer battalions with something standing on them, each with its nearest attacker.

        `ARCHER_CONTACT` is the line between shooting and being fought: an archer trading arrows
        across a field is doing its job, and one with a swordsman inside its formation is a badly
        armoured swordsman.
        """
        found: list[tuple[GameObject, GameObject]] = []
        for archer in self.army():
            if not self.role(archer, ARCHER):
                continue
            close = [
                o
                for o in self.observation.objects
                if self.hostile(o) and o.distance_to(archer.position) < ARCHER_CONTACT
            ]
            if close:
                found.append((archer, min(close, key=lambda o: o.distance_to(archer.position))))
        return found

    def can_disengage(self, archer: GameObject, attacker: GameObject) -> bool:
        """Whether withdrawing beats standing, which is decided by the two speeds.

        **Not slower, rather than strictly faster**, and the difference is most of the cases.
        Foot is 55 across the tree, so infantry chasing archers is a tie - and a tie is a
        withdrawal that works: the archers give ground at the pursuer's own pace while the melee
        line closes the gap, which is the whole point of falling back *to* something. Requiring
        strictly faster would refuse every infantry pursuit in the game and leave the rule firing
        only against siege.

        **What it does refuse is running from cavalry** (120 against 55). There the archers stop
        shooting, take the same melee anyway, and take it strung out in a line instead of in
        formation - the worst of both, so they turn and fight.

        An unreadable speed on either side answers no: the order stays un-sent rather than going
        out on a guess, which is the safe direction, because not retreating is the behaviour the
        bot has always had.
        """
        mine = self.statics.speed(archer.template_name)
        theirs = self.statics.speed(attacker.template_name)
        return bool(mine) and bool(theirs) and mine >= theirs

    def stage_archers(self) -> str | None:
        """Pull one archer battalion out of melee, back behind the line that can take it.

        **An archer beats everything at range and loses to everything in contact**, which is the
        one corner of the counter triangle no armour table can express: `Statics.effectiveness`
        reads damage type against armour and answers 0.82 for archers into cavalry, because the
        advantage is not a damage multiplier - it is not being reached. So this is a positional
        rule rather than a matchup one, and it has to be written rather than derived.

        Back **to the melee line**, not away from the attacker: retreating into open ground buys
        one cycle and arrives nowhere, where a group standing behind its own swordsmen is a group
        the pursuer has to go through them to reach. `ARCHER_BEHIND` past the melee centre, so
        the archers are shooting the fight rather than standing in it.

        Three refusals, and each is a case where the order would be worse than nothing: no melee
        of ours to fall back to, a pursuer faster than the archers (`can_disengage`), and archers
        that are the whole force - a line of bowmen with nothing in front is not helped by
        walking backwards.

        One battalion per cycle, like every other order here.
        """
        engaged = self.archers_in_melee()
        if not engaged:
            return None
        melee = [o for o in self.army() if not self.role(o, ARCHER)]
        if not melee:
            return None
        for archer, attacker in engaged:
            if not self.can_disengage(archer, attacker):
                continue
            anchor = _centre_of(melee)
            spot = self._toward_point(archer.position, anchor, ARCHER_BEHIND)
            if not self.select([archer]):
                return None
            moved = self.manoeuvre(
                "archers back", lambda point=spot: self.session.move(point), [archer]
            )
            if moved:
                return (
                    f"archers: {archer.object_id} out of melee with "
                    f"{attacker.template_name}, back behind {len(melee)}"
                )
            return None
        return None

    def stage_defend(self) -> str | None:
        """Answer each place of ours that has enemies on it, with a group sized to that place.

        This runs ahead of the expansion because that sends the army away, and the match that
        produced it ended at army 5 and gold 0 - overrun while its battalions were elsewhere.
        Defending is also the cheapest way to win a fight: units at home arrive already, and
        reinforcements walk metres rather than across the map.

        **One army walking as one body was the thing to fix.** Every threat used to be measured
        against the base and answered by one guard, so an assault on the castle and two orcs
        burning a settlement farm were the same event or - much more often - the farm was not an
        event at all. Watching a match makes it obvious: the whole force marches to the next flag
        together while a holding behind it is taken by four orcs nobody was ever going to send
        anyone at. `threats` splits the map into holdings and this answers each of them with its
        own group, so a slightly stronger detachment peels off the march and the rest keeps
        going.

        **Groups are claimed in rank order and the base is first.** Losing the base ends the
        match, so it takes the battalions it needs before any farm is considered; after it the
        worst-pressed holding. `MAX_RESPONSES` bounds how many are *ordered* per cycle, not how
        many exist - an existing group holds its battalions whether or not it got an order this
        cycle, which is what stops the assignment churning.

        **Releasing them is `settle_groups`, and it is deliberately not the inverse of raising
        them.** A group was released the moment its holding stopped counting as threatened, which
        reads as obvious and is self-cancelling: the response is to walk out and meet the raider,
        which takes the fight off the holding, which ends the threat by the only measure being
        applied. See `settle_groups` for the four seconds that behaviour was measured over.
        """
        threats = self.threats()
        if not self.army():
            return None
        if self.besieged():
            # Nothing is held back and no commitment survives, because neither a settlement nor
            # an enemy farm is worth losing the base over and both can be gone back to. The
            # parties themselves are dissolved rather than merely re-aimed: every battalion is
            # wanted at home, and `expansion_parties` will re-form them from whatever is left
            # once the siege lifts.
            self._parties.clear()
            self._party_flag.clear()
            self._forming = ()
            self._field_aim.clear()
            self._field_ordered.clear()

        said = []
        taken: set[int] = set()
        answered: set[int] = set()
        for holding, threat in threats[:MAX_RESPONSES]:
            key = 0 if holding is None else holding.object_id
            where = self.base_centre() if holding is None else holding.position
            what = "defend" if holding is None else f"hold {holding.template_name}"
            self._group_home[key] = where
            answered.add(key)
            line = self.hold(key, where, threat, taken)
            taken |= set(self._groups.get(key, ()))
            if line:
                said.append(f"{what}: {line}")
        said += self.settle_groups(answered)
        return " | ".join(said) or None

    def release_group(self, key: int) -> None:
        """Give a group's battalions back to the map, and forget everything it was doing."""
        self._groups.pop(key, None)
        self._group_aim.pop(key, None)
        self._group_target.pop(key, None)
        self._group_ordered.pop(key, None)
        self._group_home.pop(key, None)
        self._group_quiet.pop(key, None)

    def settle_groups(self, answered: set[int]) -> list[str]:
        """Decide what becomes of every group that was not given an order this cycle.

        **The rule this replaces cancelled itself.** A group was deleted as soon as its holding
        stopped counting as threatened - and a holding counts as threatened only while enemies
        stand near the *building*, while the group's whole job is to walk out and meet them. So
        succeeding at the job ended the job. Measured live across cycles 122-125 of one run: two
        battalions were drawn out of two separate parties, held for two cycles, and snapped back
        to their previous march order four seconds later, with the `IsengardUrukScoutHorde` they
        had been sent at still alive and merely standing somewhere else. Watched from inside the
        game it looks exactly like what it is - a pikeman turning twice in four seconds, and a
        group breaking off a fight it had not won.

        Three outcomes, in order of what the battalions are actually doing:

        - **In contact - kept, and left alone.** Something hostile is within `DEFEND_CONTACT` of
          the group, so it is fighting, and a fight is the one thing that must not be interrupted
          by a re-assignment. This is the case the old rule got wrong every time.
        - **Quiet but inside `DEFEND_COMMITMENT` - kept, and sent home.** The raider has broken
          off. The group goes back to the holding it was raised for rather than chasing, because a
          defence that follows its raider across the map is the strung-out army that `threats`
          exists to replace - and standing on the holding is what meets the raider when it comes
          back, which is what raiders do.
        - **Quiet for longer than that - released.** The reason is gone and the battalions are
          worth more to the expansion than to a holding nobody is attacking.

        Returning the answered set rather than the threatened one is what keeps a holding ranked
        below `MAX_RESPONSES` from pinning battalions to a job it never gets ordered to do; the
        commitment window means that release is now delayed rather than instant.
        """
        now = time.monotonic()
        said: list[str] = []
        for key in list(self._groups):
            if key in answered:
                self._group_quiet.pop(key, None)
                continue
            members = [o for o in self.army() if o.object_id in self._groups[key]]
            if not members:
                self.release_group(key)
                continue
            if self.in_contact(members):
                self._group_quiet.pop(key, None)
                continue
            since = self._group_quiet.setdefault(key, now)
            if now - since >= DEFEND_COMMITMENT:
                self.release_group(key)
                continue
            home = self._group_home.get(key)
            if home is None:
                continue
            # Sent home once rather than every cycle: the aim test is the same one `hold` uses,
            # so a group already walking back is not re-ordered on top of itself.
            last = self._group_aim.get(key)
            if last is not None and distance(home, last) <= 200.0:
                continue
            if not self.select(members):
                continue
            self.manoeuvre("regroup", lambda back=home: self.session.attack_move(back), members)
            self._group_aim[key] = home
            self._group_ordered[key] = now
            said.append(f"{len(members)} back to the holding they were raised for")
        return said

    def in_contact(self, force: list[GameObject]) -> bool:
        """Whether anything hostile is close enough to `force` to be fighting it.

        Measured against the battalions rather than against the ground they were sent to hold,
        which is the whole distinction `DEFEND_CONTACT` exists to draw - see `settle_groups`.
        """
        return any(
            self.hostile(o) and any(o.distance_to(m.position) < DEFEND_CONTACT for m in force)
            for o in self.observation.objects
        )

    def cavalry_target(self) -> GameObject | None:
        """What the horse should be riding at: their siege first, then their archers.

        **Both are chosen because of what they cannot do back.** A siege engine outranges every
        battalion in the army and is helpless against anything that reaches it, so it is either
        killed by cavalry or it knocks buildings down all match; archers are the same trade one
        step down, and they are what shoots the infantry the horse is riding away from. Neither
        can escape a horse, which is the point - this is the mission speed is *for*.

        Read as `KindOf` off the fighting member, so it needs no template list and finds Mordor's
        catapults and orc archers exactly as it finds anyone else's.

        Anything within `RAID_STANDOFF` of the enemy's own centre is left alone. Riding two
        battalions of horse into a defended keep to reach a catapult parked in it is how the
        mission ends on its first outing.
        """
        seat = self.enemy()
        centre = seat[1] if seat is not None else None
        home = self.base_centre()
        prey = [
            o
            for o in self.observation.objects
            if self.hostile(o)
            and (centre is None or o.distance_to(centre) > RAID_STANDOFF)
            and self.role(o, SIEGE, ARCHER)
        ]
        if not prey:
            return None
        # Siege first among what is reachable, and nearest within that - a catapult already
        # shooting one of our buildings is both the worst thing on the map and usually the
        # closest thing to it.
        return min(prey, key=lambda o: (not self.role(o, SIEGE), o.distance_to(home)))

    def loose_buildings(self) -> list[GameObject]:
        """Enemy settlement buildings with nobody standing on them, nearest home first.

        **What cavalry is for once there is no siege left to hunt.** A building on a flag is a
        stationary pile of hit points with no weapon, which is the one target a pair of horse
        beats outright and the one job where splitting up is strictly better than massing. Razing
        it also hands the flag underneath straight back to `stage_expand`, which is the same
        recovery the field force would otherwise have had to walk across the map for.

        Undefended is asked as a fact about the ground, not about the building: anything hostile
        within `CONTEST_RADIUS` of it makes it somebody else's problem, because two battalions of
        horse sent at a defended settlement is two battalions given away.

        Whatever any expansion party is already committed to is excluded. Both would arrive, one
        of them would be wasted, and the flag can only be handed back once. **Every party, not
        one force**: they work in parallel now, so a single aim would have left the horse
        doubling up on whatever the last party happened to be sent at.
        """
        busy = list(self._field_aim.values())
        found = []
        for building in self.enemy_expansions():
            if any(distance(building.position, aim) < AIM_STANDOFF for aim in busy):
                continue
            if any(
                self.hostile(o) and o.distance_to(building.position) < CONTEST_RADIUS
                for o in self.observation.objects
            ):
                continue
            found.append(building)
        home = self.base_centre()
        return sorted(found, key=lambda o: o.distance_to(home))

    def ride_down(self, horse: list[GameObject]) -> str | None:
        """Break the horse into parties and put each on a different undefended settlement.

        One order per party at most, `MAX_CAVALRY_ORDERS` of them per cycle, and a party already
        riding needs none - a building does not move, so the only reason to reissue is that the
        last order was lost.

        Parties survive between cycles like every other detachment here, and for the same reason:
        re-picking who rides where each cycle restarts every path and nobody arrives.
        """
        loose = self.loose_buildings()
        if not loose:
            self._cav = ()
            self._cav_parties = {}
            return None
        live = {b.object_id: b for b in loose}
        for key in [k for k in self._cav_parties if k not in live]:
            # Razed, or defended now, or claimed by the field force. Either way the party is free.
            del self._cav_parties[key]
            self._cav_party_ordered.pop(key, None)

        held = {i for ids in self._cav_parties.values() for i in ids}
        spare = [o for o in horse if o.object_id not in held]
        for building in loose:
            current = self._cav_parties.get(building.object_id, ())
            party = [o for o in horse if o.object_id in current]
            while len(party) < CAVALRY_PARTY and spare:
                # Nearest to this building, because the whole advantage being spent here is
                # arrival time.
                nearest = min(spare, key=lambda o: o.distance_to(building.position))
                spare.remove(nearest)
                party.append(nearest)
            if party:
                self._cav_parties[building.object_id] = tuple(o.object_id for o in party)
        self._cav = tuple(i for ids in self._cav_parties.values() for i in ids)

        said: list[str] = []
        for building in loose:
            if len(said) >= MAX_CAVALRY_ORDERS:
                break
            key = building.object_id
            party = [o for o in horse if o.object_id in self._cav_parties.get(key, ())]
            if not party:
                continue
            if time.monotonic() - self._cav_party_ordered.get(key, 0.0) < CAVALRY_REORDER:
                continue
            if not self.select(party):
                continue
            # Bound the target into the closure: the loop rebinds `building` and the order is
            # issued inside `confirm_attacked`, so a free variable here sends every party at
            # whichever settlement the loop happened to end on.
            ride = self.attack_on(building)
            ok = self.confirm_attacked(building, ride)
            self._report("cavalry", ok, "target took damage", "target untouched")
            self._cav_party_ordered[key] = time.monotonic()
            said.append(f"{len(party)} at {building.template_name}")
        riding = len(self._cav_parties)
        return f"cavalry: {riding} parties riding down settlements" + (
            f" | {' | '.join(said)}" if said else ""
        )

    def stage_cavalry(self) -> str | None:
        """Ride the horse at their siege and their archers, separately from everyone else.

        **A horse in the main force is an expensive footman.** It walks at the pace of the
        spearmen beside it and fights what the infantry was going to fight anyway, which is the
        matchup cavalry is worst at - a formed line of pikes is exactly what it loses to. The
        only thing it has that nothing else in the army has is speed, and speed is worth nothing
        unless it is spent going somewhere the rest cannot.

        So the cavalry is a standing mission rather than a share of the force: `expansion_parties`
        skips it, and it goes at the two things in an enemy army that cannot answer it.

        **And it arrives by riding through them rather than by walking up to them.** That is the
        same argument one step further in: a horse that reaches the archers and then halts to
        swing has spent its speed on the walk and kept none of it for the fight. `Orders.charging`
        sends the party past the battalion instead, which knocks it down and hurts it on the way,
        and the stationary fight starts on the next cycle against what is left.

        **And when there is neither, it does not come home - it splits up.** Massed, the horse
        has nothing to be massed *for*; broken into pairs it can be on several undefended
        settlements at once, which is the one job where being in four places beats being strong in
        one. See `loose_buildings`. Only when there is nothing of either kind does it fall back
        into the field force, because a mission with no target is not a reason to hold battalions
        out of the fight.
        """
        if self.besieged():
            return None
        claimed = {i for ids in self._groups.values() for i in ids}
        horse = [o for o in self.cavalry() if o.object_id not in claimed]
        if len(horse) < CAVALRY_MIN:
            self._cav = ()
            self._cav_parties = {}
            return None
        target = self.cavalry_target()
        if target is None:
            return self.ride_down(horse)
        self._cav_parties = {}
        self._cav = tuple(o.object_id for o in horse)

        # **Ride through it before standing and fighting it, wherever that works.** The whole
        # advantage a horse has over the thing it is being sent at is that it arrives fast, and an
        # `attack` order spends that on nothing: the engine walks the party up to the archers and
        # halts it there. A move past them knocks the battalion down and damages it on the way in,
        # and the fight that follows starts against an enemy already on the floor. See
        # `Orders.charging` for the two orders and `World.can_trample` for which targets take
        # them - a siege engine is too big to crush and a pike line is not to be ridden at, so
        # both come back through here as an ordinary attack.
        riding = self.charging(horse, target, "cav")
        if riding is not None:
            return f"cavalry: {riding}"

        aim = target.position
        moved_on = self._cav_aim is None or distance(aim, self._cav_aim) > AIM_STANDOFF
        if not moved_on and time.monotonic() - self._cav_ordered < CAVALRY_REORDER:
            return f"cavalry: {len(horse)} riding at {target.template_name}"
        if not self.select(horse):
            return None
        ok = self.confirm_attacked(
            target,
            lambda: self._issue(
                "cavalry", lambda: self.session.attack(target.object_id, target.position)
            ),
        )
        self._report("cavalry", ok, "target took damage", "target untouched")
        self._cav_aim = aim
        self._cav_ordered = time.monotonic()
        role = "siege" if self.role(target, SIEGE) else "archers"
        return f"cavalry: {len(horse)} at their {role} ({target.template_name})"
