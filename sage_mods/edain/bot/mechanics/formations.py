"""Formations: the free bonus a battalion gets for standing still, and when standing still is free.

Most battalions in this engine have two formations and one button that swaps between them. The
ordinary one carries nothing - Gondor spells that out, giving the main formation a
`RemoveFormationBoni` list with no modifiers in it at all - and the alternate carries a
`ModifierList` that is the entire trade. `GondorFighterHordeBlock` is `ARMOR 17%` and `SPEED
70%`, which the control bar states as **"+20% Armor, -30% Speed"**.

**That trade is a good one exactly when the speed is worth nothing**, which is a question the bot
can already answer about itself: a battalion that has not moved since the last cycle and has
something hostile within reach is in a sustained fight, and a battalion crossing the map is not.
So this stage is one rule with two directions - take the alternate while standing and fighting,
give it back on the move - rather than a table of situations.

**Nothing here is faction-specific**, which is what makes this a `mechanics` module rather than a
`factions/<side>/` one. It reads every battalion's own `HordeContain` and asks its own control bar
what buttons it has, so it plays Mordor and Angmar on the same code - and it is still a *mechanic*
rather than a stage the generic loop would have arrived at, because a formation is neither a
purchase nor a unit nor a place: it is addressed by a message no other order in the bot sends, and
the state it toggles is legible only as a model-condition flag.

**What the tree says, for the units the Men plan actually fields** (`Statics.alternate_formation`
over the `MenOfTheWestArmy` pool, so this is read rather than listed):

| battalion | alternate | trade |
|---|---|---|
| `GondorFighterHorde` | `...Block` | +17% armour, x0.70 speed |
| `GondorWachterderVesteHorde` | `...ShieldWall` | +40% armour, x0.25 speed |
| `GondorTowerShieldGuardHorde` | `...ShieldWall` | +33% armour, x0.25 speed |
| `GondorSpearmanHorde` | `...Porcupine` | braces vs cavalry, -90% vision |
| `PelegirSpearmenHorde` | `...ShieldWall` | braces, +50% armour vs water, x0.75 damage |
| `GondorArcherHorde` | `...AmbushFormation` | x1.20 damage, x0.70 speed |
| `GondorKnightHorde` | `...WedgeFormation` | +33% armour vs slash/specialist, x0.50 speed |
| `MorthondBowmenHorde` | `...AmbushFormation` | x0.80 speed and nothing else |
| `GondorRangerHorde`, `RingValeSwordsmanHorde`, `LehenLossarnachAxteHorde` | - | none declared |
| `GondorKnightsofDolHorde` | `...WedgeFormation` | **no button** - declared, unreachable |

Two of those rows are why the stage weighs rather than switches. The Morthond ambush costs 20%
of their speed and buys nothing at all in this build - `Formation.worth_taking` is what refuses
it - and the Dol Amroth wedge is a full formation whose toggle button no command set offers, so
switching it would be an order no human could have given.

**The state a battalion is in is read from the engine, not remembered.** `ALTERNATE_FORMATION` is
one of the engine's own `ModelConditionFlags` - it is in the image's name table beside
`PRIMARY_FORMATION`, and 37 unit draw blocks in the tree animate off it while only 10 modifier
lists set it, so the engine is what puts it there. It lands on the battalion's **members**, which
is where the animation is; the container carries nothing. `in_alternate` is that read, and it is
what makes the toggle confirmable at all - see `switch`, and see `summon_at` in
`factions.men.signal_fire` for the run that spent 520 orders on an unconfirmable cast and called
every one a success.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from sage_live.api.observation import GameObject, Observation, distance
from sage_live.utils.statics import Formation
from sage_mods.edain.bot.tuning import (
    DEFEND_CONTACT,
    FORMATION_HOLD,
    FORMATION_PATIENCE,
    FORMATION_STILL,
)

__all__ = ["ALTERNATE", "Formations", "Posture"]

# The engine's own `ModelCondition` for "this unit is standing in the alternate formation". Read
# off the members rather than the container - see the module docstring.
ALTERNATE = "ALTERNATE_FORMATION"


@dataclass(frozen=True)
class Posture:
    """One battalion's formation situation this cycle: what it could be in, and what it is in."""

    horde: GameObject
    formation: Formation
    # Whether the engine says its members are standing in the alternate right now.
    alternate: bool
    # Whether it is holding a position with something hostile in reach - the case the alternate
    # formation is bought for.
    fighting: bool

    @property
    def wants(self) -> bool:
        """Which formation this battalion should be in: True for the alternate.

        **A defensive formation follows the fight and an offensive one does not.** Armour is
        worth having whenever the battalion is being hit and costs only movement it is not
        using, so it goes on when the fight settles and comes off when there is somewhere to be.
        Extra damage is worth having whenever the battalion is *shooting*, which is not a state
        this can see - and the archers' ambush pays for it in speed exactly as the shield wall
        does, so treating "more damage" as a reason to stand still would slow the army down for
        a bonus it might not be collecting.

        So both kinds switch on the same signal. That is deliberately conservative about the
        offensive ones rather than clever: they are the formations whose value this cannot
        measure, and a bonus taken only while the battalion is already fighting is never taken
        at the wrong moment.
        """
        return self.fighting

    @property
    def wrong(self) -> bool:
        """Whether it is in the other one."""
        return self.alternate is not self.wants


class Formations:
    """Switching battalions into and out of their alternate formations.

    A mixin like the rest of the bot's stages, reading `observation`, `statics`, `session` and
    `Orders.select`/`_issue`/`_report`. It costs one `Statics` lookup per battalion per cycle on
    a faction whose units have no formations at all, and those lookups are pure ini reads over
    data that cannot change, so the cache below is the whole of the performance story.
    """

    def formation_of(self, horde: GameObject) -> Formation | None:
        """The alternate formation this battalion could stand in, or None.

        Cached by template, because it is a question about the tree rather than about the
        object: every `GondorFighterHorde` on the map has the same answer and the walk to reach
        it crosses a command set, a button table and a modifier list.

        **Asked with the player's upgrades**, since `formation_button` resolves the live command
        set and a `CommandSetUpgrade` can swap a battalion's palette out from under the declared
        field. The cache then fixes the answer at whatever upgrades were held the first time a
        battalion of that template was seen, and that is a real limitation rather than a free
        one. Measured over the whole tree: of 1015 hordes, 296 declare an alternate formation
        and **4** have a formation button that moves when upgrades are held - all four summoned
        Imladris units, and none of them on any side this bot has a plan for. So the cache is
        exact for every battalion it will actually meet, and a mod that gated a formation behind
        a tech would want this keyed on the upgrades too.
        """
        key = horde.template_name.lower()
        if key not in self._formations:
            me = self.observation.me
            self._formations[key] = self.statics.alternate_formation(
                horde.template_name, me.upgrades if me is not None else ()
            )
        return self._formations[key]

    def in_alternate(self, horde: GameObject, observation: Observation | None = None) -> bool:
        """Whether this battalion's members are standing in the alternate formation.

        **The container answers nothing here.** The engine sets `ALTERNATE_FORMATION` on the
        units, because that is where the crouching animation is; the horde object carries the
        `HordeContain` that was swapped and no condition to show for it. So this reads through
        `Observation.members`, and a battalion whose members cannot be seen - a fogged one, or
        one still coming out of its building - reads as primary, which is the safe way round: it
        means an unreadable battalion is left alone rather than toggled on a guess.

        `any` rather than `all` because members are set one at a time as the formation forms,
        exactly as they are contained one at a time when the battalion is built.
        """
        source = self.observation if observation is None else observation
        return any(m.is_in(ALTERNATE) for m in source.members(horde.object_id))

    def standing(self, horde: GameObject) -> bool:
        """Whether this battalion has stayed put since the last cycle.

        The measurement the whole stage rests on, and it is taken from the world rather than
        from what the bot ordered: a battalion has a dozen stages that might have sent it
        somewhere, and only one position. A battalion this has never seen before reads as
        moving, so it is left in line formation until there is a second sample to compare - one
        cycle's delay, against the alternative of calling every fresh recruit stationary.
        """
        was = self._formation_seen.get(horde.object_id)
        return was is not None and distance(was, horde.position) < FORMATION_STILL

    def fighting(self, horde: GameObject) -> bool:
        """Whether this battalion is holding a position with something hostile in reach.

        The two halves are the two things a defensive formation needs to be worth its speed:
        somebody to be protected from, and nowhere to be. `DEFEND_CONTACT` is the same reach
        `settle_groups` uses to decide a response group is still in its fight, which is the same
        question asked about a different force.
        """
        if not self.standing(horde):
            return False
        return any(
            self.hostile(o) and o.distance_to(horde.position) < DEFEND_CONTACT
            for o in self.observation.objects
        )

    def postures(self) -> list[Posture]:
        """Every battalion that has a formation worth switching, and where it stands.

        Battalions only - `army()` includes heroes and siege engines, neither of which is a
        horde and neither of which has an alternate formation, so they fall out on
        `formation_of` answering None rather than needing a `KindOf` test of their own.
        """
        found = []
        for horde in self.army():
            formation = self.formation_of(horde)
            if formation is None or not formation.worth_taking:
                continue
            found.append(
                Posture(
                    horde=horde,
                    formation=formation,
                    alternate=self.in_alternate(horde),
                    fighting=self.fighting(horde),
                )
            )
        return found

    def settled(self, posture: Posture) -> bool:
        """Whether this battalion's situation has held long enough to act on.

        Two counters in one: `_formation_since` records the first cycle the battalion wanted
        something other than what it has, and the switch waits `FORMATION_PATIENCE` cycles from
        there. A battalion whose want flips back before then never pays for the change.

        The counter is cleared as soon as the want does, so a skirmish that ends in one cycle
        leaves nothing behind.
        """
        key = posture.horde.object_id
        if not posture.wrong:
            self._formation_since.pop(key, None)
            return False
        self._formation_since[key] = self._formation_since.get(key, 0) + 1
        return self._formation_since[key] >= FORMATION_PATIENCE

    def switch(self, posture: Posture) -> bool:
        """Toggle one battalion's formation, and say whether the engine actually did it.

        **The order is not the result, and here there is a real oracle for once.** The engine
        marks the members with `ALTERNATE_FORMATION`, so a switch that landed and one that was
        consumed and discarded look different from outside - which is exactly the check
        `factions.men.signal_fire` had to be taught the expensive way.

        Selected first, like every other object-scoped order in this bot: `toggle_formation`
        names the horde *and* requires a selection, because that is what a click sends.

        The wait is `DEFAULT_CONFIRM` rather than a build's four seconds. Re-forming ranks takes
        a moment, but the *flag* is set when the order is accepted rather than when the ranks
        finish moving, so a longer window would only mean waiting on the animation.
        """
        horde = posture.horde
        label = f"formation {horde.template_name[:10]}"
        if not self.select([horde]):
            return False
        want = not posture.alternate

        def switched(obs: Observation) -> bool:
            return self.in_alternate(horde, obs) is want

        if not self._issue(label, lambda: self.session.toggle_formation(horde.object_id)):
            return self._report(label, False, "", "NOT SENT")
        landed = self.session.confirm(switched)
        self._formation_at[horde.object_id] = time.monotonic()
        self._formation_since.pop(horde.object_id, None)
        into = posture.formation.alternate if want else "line"
        return self._report(label, landed, f"into {into}", "DID NOT CHANGE - order discarded")

    def stage_formation(self) -> str | None:
        """Put one battalion into the formation its situation calls for.

        **One a cycle, like every other stage here**, and the neediest first: a battalion that
        should be braced and is not is losing hit points now, where one that should be back in
        line is only walking slowly. Ties inside that go to whichever has wanted it longest,
        which is what stops a big fight starving a single battalion elsewhere forever.

        Positions are recorded for every battalion at the end, not just the one acted on -
        `standing` compares against the last cycle and a sample taken only for the acted-on
        battalion would leave every other one permanently unmeasurable.
        """
        postures = self.postures()
        candidates = [
            p
            for p in postures
            if self.settled(p)
            and time.monotonic() - self._formation_at.get(p.horde.object_id, 0.0) > FORMATION_HOLD
        ]
        self._formation_seen = {h.object_id: h.position for h in self.army()}
        if not candidates:
            held = sum(1 for p in postures if p.alternate)
            if not postures:
                return None
            return f"formations {held}/{len(postures)} braced" if held else None
        candidates.sort(
            key=lambda p: (not p.wants, -self._formation_since.get(p.horde.object_id, 0))
        )
        chosen = candidates[0]
        if not self.switch(chosen):
            return f"{chosen.horde.object_id}: formation would not change"
        where = "braced" if chosen.wants else "back in line"
        return f"{chosen.horde.object_id} {chosen.horde.template_name[:16]}: {where}"
