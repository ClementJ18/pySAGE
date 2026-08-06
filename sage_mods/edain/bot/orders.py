"""Issuing orders, and proving they did something.

**Nothing here counts as done until the game visibly does it.** Game logic silently discards a
malformed or unaffordable order after the stream has taken it - no error, no diagnostic - so
every send in this file is paired with the oracle that can tell the difference, and the ledger
is written exactly once per attempt.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence

from sage_live.api.observation import GameObject, Observation, Vec3, distance
from sage_live.api.session import BUILD_CONFIRM, NoSelection, Sent
from sage_live.utils.naming import UnknownDefinition
from sage_live.utils.statics import UpgradeButton
from sage_mods.edain.bot.tuning import (
    AIM_STANDOFF,
    BUILD_RADIUS,
    CAPTURE_RADIUS,
    ENGAGE_REORDER,
    FIELD_REORDER,
    PLOT_COOLDOWN,
    TRAMPLE_OVERSHOOT,
    TRAMPLE_RUNUP,
    TRAMPLE_SECONDS,
)
from sage_mods.edain.bot.world import World


def _centre(force: list[GameObject]) -> Vec3:
    """Where a group of units is, as one point - the mean of their positions."""
    return (
        sum(o.position[0] for o in force) / len(force),
        sum(o.position[1] for o in force) / len(force),
        sum(o.position[2] for o in force) / len(force),
    )


def _beyond(start: Vec3, through: Vec3, past: float) -> Vec3:
    """The point `past` units further along the line from `start` through `through`.

    What a ride-through is aimed at. Height is carried from the target rather than extrapolated:
    the run is over ground the engine paths across anyway, and continuing a slope beyond the enemy
    aims the order under a hill as readily as over one. `start` and `through` being the same point
    is not a case to guard against here - the caller has already refused a charge from inside
    `TRAMPLE_RUNUP` - but it answers `through` rather than dividing by zero.
    """
    dx, dy = through[0] - start[0], through[1] - start[1]
    span = (dx * dx + dy * dy) ** 0.5
    if span <= 0.0:
        return through
    return (through[0] + dx / span * past, through[1] + dy / span * past, through[2])


class Orders(World):
    """Issuing orders, and proving they did something."""

    def reserve(self, purpose: str, amount: int) -> None:
        """Promise `amount` of the balance to something already committed to.

        **A reservation is a decision already taken, not a budget.** The bot commits to things
        several cycles before it can pay for them - a settlement is chosen, then walked to, and
        only then built on - and in between, every other stage sees a balance that looks free and
        spends it. Watching a match makes the cost obvious: battalions criss-crossing the map to
        flags they arrive at and cannot afford, so the walk, the fight and the capture are all
        thrown away for a battalion that was queued while they marched.

        So the gold stops existing for everyone except the promise-holder. `spendable` is what
        every other stage prices against, and `afford(..., purpose=...)` is how the holder spends
        what it set aside.

        Keyed by purpose so a promise replaces itself rather than accumulating - `stage_expand`
        re-reserves for the same flag every cycle it is walking, and the total must not climb.
        """
        self._reserved[purpose] = max(0, amount)

    def release(self, purpose: str) -> None:
        """Drop a promise - the thing was bought, or given up on."""
        self._reserved.pop(purpose, None)

    def reserved(self, exclude: str = "") -> int:
        """Gold promised elsewhere, which is gold this caller must treat as absent."""
        return sum(gold for why, gold in self._reserved.items() if why != exclude)

    def spendable(self, exclude: str = "") -> int:
        """The balance as everyone except `exclude`'s owner should see it."""
        return max(0, self.gold - self.reserved(exclude))

    def afford(self, template: str, reserve: int = 0, purpose: str = "") -> bool:
        """Whether the spendable balance covers `template`'s price, on top of `reserve`.

        **The cheapest failure to avoid, and the one that reads as a bug.** An order that costs
        more than the balance is consumed by the stream and discarded by logic in silence, so
        it comes back through the confirmation as "NOT QUEUED - logic discarded it" - the same
        message as a malformed order or an unmet prerequisite. A measured match logged 46 of
        those and 9 more against `CPObject`, every one of them simply unaffordable, and three
        in a row was enough to bench the action for two minutes.

        Still a floor rather than an exact test, but a much closer one than the quoted price:
        `charged_cost` applies the `CostModifierUpgrade` ladders the standing buildings have
        already earned, and only those it can see. Pricing against the quote instead was wrong by
        up to 30% on precisely the elite units and the `CPObject` a built-up base exists to buy -
        a citadel guard quoted at 600 is charged 420 behind six town houses, so a bot holding 500
        refused a recruit it could afford and banked the gold instead.

        `purpose` names a reservation this spend is *the point of*, so its holder can see its own
        promised gold. Everyone else prices against the balance without it - see `reserve`.
        """
        cost = self.charged_cost(template)
        return cost <= 0 or self.spendable(purpose) >= cost + reserve

    def _issue(self, label: str, act: Callable[[], Sent]) -> Sent:
        """Send, reporting the two failures that happen before the engine ever sees it.

        `Sent` says which: the APM cap holding an order back is normal pacing, the backend
        turning it down is a fault. Guessing between them from a running throttle count gets
        it wrong the moment a cap has ever fired.

        Reports but does not record. The ledger is written once, by `_report`, so an order
        that never left is not counted twice - once here and once when the confirmation that
        was never given comes back false.
        """
        if self.dry_run:
            print(f"    {label:<16} (dry run)")
            return Sent(0)
        try:
            sent = act()
        except (UnknownDefinition, NoSelection) as exc:
            print(f"    {label:<16} refused: {exc}")
            return Sent(0)
        if not sent:
            print(f"    {label:<16} not sent ({sent.reason})")
        return sent

    def _report(self, label: str, ok: bool, good: str, bad: str) -> bool:
        """The one place the ledger is written, so every issued order counts exactly once."""
        self.ledger.record(label, ok)
        print(f"    {label:<16} {good if ok else bad}")
        return ok

    def select(self, objects: Sequence[GameObject] | Sequence[int]) -> bool:
        """Select these, and say whether the selection actually changed.

        **Every order below acts on the selection, and a selection order can fail.** Nothing
        used to read the result: `Session.select` returns a `Sent` and all nine call sites
        discarded it. When one failed the engine kept the *previous* selection, so the order
        that followed went to whatever had been selected last - a push of 24 battalions
        attacked with the barracks it had been recruiting at, and reported the target
        untouched. The failure was in the log as a warning and nowhere in the bot's behaviour.

        `Session.select` now splits a selection too large for one order, so the size that
        caused that is handled below this. What is left is the ordinary reasons a send does not
        go - the APM cap, a backend that refused - and those are worth a line and a skipped
        stage rather than an order issued into the dark.
        """
        ids = [o.object_id if isinstance(o, GameObject) else o for o in objects]
        if self.dry_run:
            return True
        if not ids:
            return False
        sent = self.session.select(ids)
        if not sent:
            print(f"    {'select':<16} not sent ({sent.reason}) - skipping what depended on it")
            return False
        if len(self.session.selection) < len(ids):
            # A partial selection is not the one that was decided against, and acting on it
            # sends a fraction of the army at something sized for all of it.
            print(
                f"    {'select':<16} only {len(self.session.selection)}/{len(ids)} selected "
                "- skipping what depended on it"
            )
            return False
        return True

    def spend(self, label: str, act: Callable[[], Sent]) -> bool:
        """Issue an order that should cost gold, and confirm the gold actually left."""
        ok = self.session.confirm_spend(lambda: self._issue(label, act))
        return self._report(label, ok, "charged", "NOT CHARGED - logic discarded it")

    def manoeuvre(self, label: str, act: Callable[[], Sent], units: list[GameObject]) -> bool:
        """Issue a movement order, and confirm the units actually moved."""
        ok = self.session.confirm_moved(
            lambda: self._issue(label, act), [u.object_id for u in units]
        )
        return self._report(label, ok, "units moved", "NOTHING MOVED - order discarded")

    def _cold(self, key: str) -> bool:
        """Whether this action is sitting out after repeated failures."""
        return self._cooldowns.get(key, 0.0) > time.monotonic()

    def _strike(self, key: str, ok: bool, seconds: float = 120.0) -> bool:
        """Record an attempt; bench the action for `seconds` once it has failed three times.

        Three rather than one, because a single failure is often a real game state - the queue
        was full, the plot was briefly contested - while a third in a row means the order is
        never going to work and the cycles are better spent elsewhere.
        """
        if ok:
            self._strikes.pop(key, None)
            return ok
        self._strikes[key] = self._strikes.get(key, 0) + 1
        if self._strikes[key] >= 3:
            self._cooldowns[key] = time.monotonic() + seconds
            self._strikes[key] = 0
            print(f"      {key} has failed three times; benching it for {seconds:.0f}s")
        return ok

    def attack_on(self, target: GameObject, label: str = "attack") -> Callable[[], Sent]:
        """An order that attacks `target`, with the target bound rather than closed over.

        A closure written inline inside a loop reads the loop variable when it *runs*, and every
        order here runs later - inside `confirm_attacked`, after the target has been rebound. So
        a loop that issues one order per party sends them all at whichever object the loop ended
        on. Binding it here is one line and removes the whole class of mistake.
        """
        return lambda: self._issue(
            label, lambda: self.session.attack(target.object_id, target.position)
        )

    def confirm_attacked(self, target: GameObject, act: Callable[[], Sent]) -> bool:
        """Confirm an attack by what happens to the **target**, not by our units moving.

        `confirm_moved` is the wrong question here and quietly under-reports: once the army is
        adjacent and swinging, it does not move at all, so a working attack reads as a discarded
        order. Measured: the same push logged 69/74 while closing and 8/71 once it arrived.

        Damage or death is the honest signal, and nothing else in the match can forge it against
        the specific object we named.
        """
        before = target.health
        if not act():
            return False

        def hurt(obs: Observation) -> bool:
            found = obs.obj(target.object_id)
            return found is None or found.health < before - 0.001

        return self.session.confirm(hurt, timeout=BUILD_CONFIRM)

    def confirm_engaged(
        self, target: GameObject, group: list[GameObject], act: Callable[[], Sent]
    ) -> bool:
        """Confirm an attack on something that can run away: it was hurt, or we set off after it.

        **`confirm_attacked` asks the right question of a building and the wrong one of a
        raider.** A lair stands still and takes the hit, so damage inside the window is a fair
        test - `attack` scores 6/9 on it. A warg rider does not: the group is ordered, the rider
        moves, the group chases, and four seconds later nothing has been damaged and a working
        order reads as discarded. Measured over one match with the two split by distance instead:
        `defend` went 0/7 on the damage oracle while `attack` went 6/9 on the same oracle in the
        same match, and the difference was not the distance - it was that one target was a
        building and the other had legs.

        So either signal counts. Damage or death settles it outright; failing that, our own units
        setting off is the engine acting on the order, which is the whole of what is being asked.
        An order the engine dropped produces neither, so nothing here forges a success.
        """
        before = target.health
        watched = {u.object_id: u.position for u in group}
        if not act():
            return False

        def engaged(obs: Observation) -> bool:
            found = obs.obj(target.object_id)
            if found is None or found.health < before - 0.001:
                return True
            return any(
                (unit := obs.obj(i)) is not None and unit.distance_to(was) > 5.0
                for i, was in watched.items()
            )

        return self.session.confirm(engaged, timeout=BUILD_CONFIRM)

    def confirm_built(self, template: str, plot: GameObject, act: Callable[[], Sent]) -> bool:
        """Confirm a build two ways, because one radius cannot answer for every building.

        `confirm_appeared` asks whether something new is standing near where the order was
        aimed, which is right in principle and depends on a radius in practice - and a large
        structure's centre lands further from the plot marker than a small one's. Barracks
        builds were being charged and raised and still read as "NOTHING APPEARED", which then
        parked a perfectly good plot.

        So the second oracle counts the buildings themselves: `owned_building` resolves
        `BuildVariations`, so ordering a `GondorWohnhaus` and getting a `GondorWohnhaus01`
        still counts. Either signal is enough; neither is forgeable by anything else in the
        match.
        """
        before_ids = {o.object_id for o in self.observation.objects}
        before_count = len(self.owned_building(template))
        if not act():
            return False

        def landed(obs: Observation) -> bool:
            if len(self.owned_building(template)) > before_count:
                return True
            return any(
                o.object_id not in before_ids
                and o.owner_index == self.session.player_index
                and o.distance_to(plot.position) < BUILD_RADIUS
                for o in obs.objects
            )

        return self.session.confirm(landed, timeout=BUILD_CONFIRM)

    def build_on_plot(self, template: str, plot: GameObject) -> bool:
        """Place `template` on `plot`, trying both build paths.

        There are two, and the plot's own command set says which it takes: an internal castle
        plot carries `FOUNDATION_CONSTRUCT` buttons and takes `build_at`, while an external
        plot carries unpack buttons and takes `unpack`/`castle_unpack`. `GondorFoundationCommandSet`
        is eleven `FOUNDATION_CONSTRUCT` buttons and not one unpack, so the fallback below can
        never rescue an internal plot - it is there for the mixed cases, not as a real second
        chance.

        **Select the plot first, even for the placement build.** A human's recorded clicks are
        `Select <plot>` and only then `FOUNDATION_CONSTRUCT`, and the order carries no object
        id - just a template, a position and an angle - so the selection is how the engine
        knows which foundation is being built on. Sending it unselected leaves that to whatever
        was selected last, which is why this used to land about one build in three.
        """
        label = f"build {template[6:15]}"
        if not self.select([plot]):
            return False
        placed = self.confirm_built(
            template,
            plot,
            lambda: self._issue(label, lambda: self.session.build(template, plot.position)),
        )
        self._report(label, placed, "built", "NOTHING APPEARED - order discarded")
        if placed:
            self._spent_plot(plot)
            return True
        print(f"      placement build failed on plot {plot.object_id}; trying the unpack path")
        if not self.select([plot]):
            return False
        unpacked = self.confirm_built(
            template, plot, lambda: self._issue("unpack", lambda: self.session.unpack(template))
        )
        self._report("unpack", unpacked, "built", "NOTHING APPEARED - order discarded")
        if unpacked:
            self._spent_plot(plot)
            return True
        # Both paths refused. Something about this spot is wrong in a way the observation does
        # not show - a building already on it whose centre is further off than PLOT_RADIUS, or
        # a pad that takes a different order - so stop paying for it and try the next one.
        self._blocked_plots[plot.object_id] = time.monotonic() + PLOT_COOLDOWN
        print(f"      plot {plot.object_id} refused both build paths; parking it")
        self._strike(f"build:{template}", False)
        return False

    def _spent_plot(self, plot: GameObject) -> None:
        """Rest a plot that was just built on, whatever happens to the building next.

        **Inert in the ordinary case and load-bearing in exactly one.** A plot with a building
        standing on it is already excluded by `free_plots`, which tests occupancy rather than
        ownership - so resting it costs nothing while the building lives. The case it exists for
        is the building *not* living: razed at 0% construction, the plot is free again the next
        cycle, `free_plots` offers it straight back, and the bot pays the full price again. Seen
        live: the same plot built and destroyed four times in five seconds.

        Cooldown rather than a permanent block, because a plot lost to a raid that has since
        been driven off is worth having, and because the only alternative test - "was this
        building destroyed rather than sold or upgraded" - needs a death the observation does not
        report. Waiting is the cheap way to tell a contested plot from a safe one.

        Shares `PLOT_COOLDOWN` with the refusal path deliberately: both are the same statement,
        that this spot has just cost something and should not be the next thing tried.
        """
        self._blocked_plots[plot.object_id] = time.monotonic() + PLOT_COOLDOWN

    def confirm_research(self, target: GameObject, button: UpgradeButton) -> bool:
        """Issue a research order and confirm it, accepting either of the two honest signals.

        **Which oracle is right depends on what was ordered, so this watches for both.** A
        structure queues an upgrade on the same `ProductionUpdate` it queues units on, so the
        queue growing is immediate and direct. A battalion has no such queue - the upgrade
        simply appears in its `upgrades` when it completes - so there the only evidence is the
        object gaining the name, and that takes the upgrade's build time rather than a frame.

        Gold is deliberately not the test. It moves for reasons that have nothing to do with
        this order in both directions, which is the same trap `confirm_spend` documents.
        """
        before = len(target.production)

        def landed(obs: Observation) -> bool:
            found = obs.obj(target.object_id)
            if found is None:
                return False
            return len(found.production) > before or found.has(button.upgrade)

        def buy() -> Sent:
            return self.session.research(button.upgrade, target.object_id)

        # Select first. `Session.research` names the building outright and does not require it,
        # but selecting is what the control bar does and costs one cheap order to match.
        if not self.select([target]):
            return False
        if not self._issue("research", buy):
            return False
        return self.session.confirm(landed, timeout=BUILD_CONFIRM)

    def detachment(
        self,
        available: list[GameObject],
        current: tuple[int, ...],
        size: int,
    ) -> list[GameObject]:
        """The survivors of a detachment, brought back up to `size` from what is spare.

        **A detachment that is never reinforced is a detachment that dwindles to nothing while
        still being sent to fight.** Holding the original ids kept the group stable across
        cycles, which is what stopped it re-picking every frame - but it also meant casualties
        were never replaced: a measured match had a guard of one still being sent at three
        raiders, simply feeding kills to an opponent who kept reinforcing.

        Survivors stay, so the commitment holds and nobody's walk restarts; the shortfall is
        made up from the front of `available`, which every caller orders by how well suited it
        is - the guard by how near home each battalion already stands.
        """
        kept = [o for o in available if o.object_id in current]
        if len(kept) >= size:
            return kept[:size]
        held = {o.object_id for o in kept}
        spare = [o for o in available if o.object_id not in held]
        return kept + spare[: size - len(kept)]

    def charging(self, force: list[GameObject], target: GameObject, key: str) -> str | None:
        """Ride `force` **through** `target`, or say nothing and let the caller fight normally.

        **The whole of the trample mechanic is which order is sent.** `attack` names an object,
        so the engine walks the horse up to it and halts it there to swing - and a halted horse
        is an expensive footman fighting the matchup it is worst at. A `move` aimed at a point on
        the far side sends the same battalion straight through: the engine's crush system knocks
        the enemy down, damages it, and takes some speed off the rider for it. That is the
        cheapest way this army has of taking a battalion apart, and it costs one different order.
        Which battalions it works on is `World.can_trample`; this is only the sending.

        Three states, and the return value says which:

        - **a charge is already running** - a line, and no order at all. This is the state that
          makes the whole thing work: an attack reissued on the cycle after the charge cancels
          the move and the horse finishes its approach at a walk, which is the failure the two
          state fields exist to prevent.
        - **a charge is worth starting** - the move goes, and a line comes back.
        - **it is not** - None, and the caller attacks in the ordinary way. Either this force
          cannot crush this target, or it is already standing on it: a crush is a momentum check
          (`MinCrushVelocityPercent`), so a charge begun inside `TRAMPLE_RUNUP` arrives too slow
          to flatten anything and is just a move order away from a fight.

        **One trample per commitment, not one per cycle.** Once the ride-through has had
        `TRAMPLE_SECONDS` this answers None for that target for as long as it stays the target, so
        the horse turns and fights where the charge left it - which is what was asked for, and
        also what stops a party spending the match riding back and forth through the same enemy
        while never landing a sword blow.
        """
        now = time.monotonic()
        if self._charge_target.get(key) == target.object_id:
            if now - self._charged.get(key, 0.0) < TRAMPLE_SECONDS:
                return f"{len(force)} riding through {target.template_name}"
            return None
        if not self.can_trample(force, target):
            return None
        closest = min(o.distance_to(target.position) for o in force)
        if closest < TRAMPLE_RUNUP:
            return None
        if not self.select(force):
            return None
        through = _beyond(_centre(force), target.position, TRAMPLE_OVERSHOOT)
        self.manoeuvre("trample", lambda: self.session.move(through), force)
        self._charge_target[key] = target.object_id
        self._charged[key] = now
        return f"{len(force)} trampling {target.template_name} from {closest:.0f}"

    def engage(self, force: list[GameObject], target: GameObject, what: str, key: str = "") -> str:
        """Attack one object with the whole force, leaving a running order alone.

        `attack` on the object rather than `attack_move` at a point: the order names what to
        destroy, so the force commits to it instead of stopping to fight everything between here
        and a coordinate - which against a lair means fighting the slaves it keeps replacing and
        never reaching the thing making them.
        """
        aim = target.position
        last = self._field_aim.get(key)
        moved_on = last is None or distance(aim, last) > AIM_STANDOFF
        if not moved_on and time.monotonic() - self._field_ordered.get(key, 0.0) < ENGAGE_REORDER:
            return f"{len(force)} en route to {what}"
        if not self.select(force):
            return f"{len(force)} could not be selected against {what}"
        ok = self.confirm_attacked(
            target,
            lambda: self._issue(
                "attack", lambda: self.session.attack(target.object_id, target.position)
            ),
        )
        self._report("attack", ok, "target took damage", "target untouched")
        self._field_aim[key] = aim
        self._field_ordered[key] = time.monotonic()
        return f"{len(force)} at {what} ({target.template_name})"

    def march(self, force: list[GameObject], aim: Vec3, what: str, key: str = "") -> str:
        """Walk the force somewhere, fighting what it meets, leaving a running order alone.

        **Re-issuing a move every cycle is how a force never arrives**: each order restarts the
        path, so units take one step, get a fresh order, and take one more. They visibly move the
        whole time and close no distance - measured at 3 battalions over 20 cycles, still "0 in
        range".
        """
        last = self._field_aim.get(key)
        moved_on = last is None or distance(aim, last) > CAPTURE_RADIUS
        if not moved_on and time.monotonic() - self._field_ordered.get(key, 0.0) < FIELD_REORDER:
            return f"{len(force)} en route to {what}"
        if not self.select(force):
            return f"{len(force)} could not be selected to walk to {what}"
        self.manoeuvre("attack_move", lambda: self.session.attack_move(aim), force)
        self._field_aim[key] = aim
        self._field_ordered[key] = time.monotonic()
        return f"{len(force)} sent at {what}"
