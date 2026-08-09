"""Gondor's signal fire: a recruitment building nobody recruits from.

`GondorLeuchtfeuer` costs 400g, earns nothing, and has no recruit buttons of its own. What it
does is spawn an **errand rider** (`Meldereiter`) when it finishes, and the rider is how the
building is used: it accumulates charges over time, and spending them fires a weapon that makes
the signal fire recruit a pair of fiefdom battalions. So the building is bought once and then
pays out in units for the rest of the match, on a currency that is not gold and that nothing else
in the bot models.

**The building recruits, not the rider.** The rider is the trigger and the charges are the price;
the battalions are produced by the signal fire and arrive at its exit like anything else it
built. That is also why the command-point ceiling applies exactly as it does to an ordinary
recruit - see `summon_fits`, which exists because an over-cap summon queues nothing and spends
the charges anyway.

**The charge count is the rider's template name.** There is no counter to read. Edain declares
fifteen objects, `ErrandRider0` through `ErrandRider14`, and the rider *becomes* the next one
every time a charge lands - `ToggleMountedSpecialAbilityUpdate` with `MountedTemplate =
ErrandRider1` on `ErrandRider0`, and so on up the ladder. The rate is the mount power's
`ReloadTime`: **75 seconds a charge**, capped at 14.

This is the identity trap in its purest form, and it is worse than it first reads: the rider is
not one object whose name changes, it is **a new object at every rung**. Measured live, spending
two charges turned `rider 1276` into `rider 1373` - the old one destroyed, a new id created. So
anything that remembers a rider by template is wrong within 75 seconds, and anything that
remembers one by `object_id` is wrong the moment it spends. `charges_held` is what the mechanic
confirms against for that reason.

**What each summon costs is written in the ini twice, and the two agree.** Each
`WeaponFireSpecialAbilityUpdate` names a `ChainedButton` - `Command_LeuchtfeuerMeldereiter_
Downgrade2`, `_Downgrade3`, `_Downgrade8` - which is the engine deducting the charges by
dismounting the rider that many rungs. Independently, the rider's command set at charge N enables
exactly the summons costing N or less: `GondorErrandRiderCommandset1` at 2 charges opens Ring
Vale and Lossarnach, `...set2` at 3 adds Pelargir and Morthond, `...set3` at 8 adds Lehen. So the
table below is the ini's own arithmetic, not a tuning guess.

**Lehen is the whole reason to save**, though by less than it first looks. Eight charges is ten
minutes of accrual and it recruits four battalions, one of each fiefdom and every one veteran -
against the two ordinary battalions a three-charge summon gives, which is five or six battalions
if the same eight charges are spent as they arrive. So Lehen buys *quality*, not quantity, and
`best_summon` weighs it accordingly rather than treating the wait as free.

`stage_signal_fire` runs in `Bot.decide` ahead of `stage_recruit` - it spends no gold, so the
only thing it takes from the loop is command points, and a free pair of battalions beats a paid
single one. It answers None on any seat that is not Men.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from sage_live.api.observation import GameObject, Observation, Vec3, distance
from sage_live.api.orders import CAST_SELF
from sage_live.api.session import BUILD_CONFIRM
from sage_mods.edain.bot.tuning import HOLDING_RADIUS

__all__ = [
    "CHARGE_SECONDS",
    "FIEFDOM_SIDE",
    "MAX_CHARGES",
    "RIDER_PREFIX",
    "SIGNAL_FIRE",
    "SUMMONS",
    "SUMMON_RANGE",
    "SignalFire",
    "Summon",
    "charges_of",
]

SIGNAL_FIRE = "GondorLeuchtfeuer"
# Every rider template shares this stem and ends in its charge count. Matching on the stem rather
# than on the fifteen names is not a shortcut - it is the only form that survives the object
# changing template underneath a cycle.
RIDER_PREFIX = "errandrider"
# `ErrandRider14` is the last one declared, and its command set offers nothing `ErrandRider8`'s
# does not - so charges past this are accrued and wasted.
MAX_CHARGES = 14
# `SpecialAbilityErrandRiderMount`, `ReloadTime = 75000`. Not read from the tree because it is
# not a decision the bot makes - it is here so a caller can say how long a saved charge costs.
CHARGE_SECONDS = 75.0
# `StartAbilityRange` on every one of the five `WeaponFireSpecialAbilityUpdate` modules. The
# rider walks to within this of the target point before the summon lands, so a point chosen
# across the map is a rider crossing the map, not a refused order.
SUMMON_RANGE = 400.0
# The `Side` token the mechanic belongs to. Gondor's is `Men` - see `PLANS`, which is keyed the
# same way and for the same reason.
FIEFDOM_SIDE = "men"


@dataclass(frozen=True)
class Summon:
    """One fiefdom the rider can call, and what calling it costs.

    `charges` is the `ChainedButton` deduction and equally the lowest charge count whose command
    set enables the button - the ini states it both ways and they agree.

    **`form` was `CAST_LOCATION`, and that was wrong for two whole matches.** The firing button
    declares no `Options`, so `Statics._cast_form` - the codebase's own rule, read off the
    `NEED_TARGET_*` bits and confirmed against the replay corpus - classifies these as self-cast.
    That was overridden here on circumstantial evidence: a `RadiusCursorType` of
    `PalantirVisionRadiusCursor`, a `StartAbilityRange` of 400 that only means anything against a
    point, and a `SPECIAL_SPELL_BOOK_PALANTIR_VISION` enum whose vanilla counterpart takes a
    location.

    A cast sent through the wrong constructor is accepted, charged nothing and does nothing - so
    the mistake was invisible in the ledger, which counts orders *sent*. What caught it was the
    rider: **520 summons in one match and its charge count never once went down.** See
    `summon_at`, which now checks precisely that rather than trusting the send.
    """

    button: str
    power: str
    charges: int
    spawns: tuple[str, ...]
    form: str = CAST_SELF

    @property
    def veteran(self) -> bool:
        """Whether this summons the `_Veteranen` line, which only Lehen does."""
        return any(name.endswith("_Veteranen") for name in self.spawns)


# In ascending charge order, which is also the order `affordable` reports and the order
# `best_summon` walks backwards.
#
# **`spawns` lists every battalion the order puts on the map, repeats included** - so a fiefdom
# appears twice, because one cast recruits two of them. That is not a modelling flourish; it is
# what makes `summon_command_points` a sum rather than a lookup, and the difference between
# reading Ring Vale as 60 points and as the 120 it actually charges. The OCL named by each
# special weapon (`ocl_spawnleuchtfeuerringvale` and friends) lists the type once, so the count
# is not visible there and cannot be read off it.
SUMMONS: tuple[Summon, ...] = (
    Summon(
        button="Command_LeuchtfeuerRingVale",
        power="SpecialAbilityLeuchtfeuerRingVale",
        charges=2,
        spawns=("RingValeSwordsmanHorde",) * 2,
    ),
    Summon(
        button="Command_LeuchtfeuerLossarnach",
        power="SpecialAbilityLeuchtfeuerLossarnach",
        charges=2,
        spawns=("LehenLossarnachAxteHorde",) * 2,
    ),
    Summon(
        button="Command_LeuchtfeuerMorthond",
        power="SpecialAbilityLeuchtfeuerMorthond",
        charges=3,
        spawns=("MorthondBowmenHorde",) * 2,
    ),
    Summon(
        button="Command_LeuchtfeuerPelagir",
        power="SpecialAbilityLeuchtfeuerPelagir",
        charges=3,
        spawns=("PelegirSpearmenHorde",) * 2,
    ),
    # The exception to the pair: one of each fiefdom rather than two of one, and every one of
    # them veteran. Four battalions for eight charges against two for three, which is why this is
    # the only summon worth saving toward.
    Summon(
        button="Command_LeuchtfeuerLehen",
        power="SpecialAbilityLeuchtfeuerLehen",
        charges=8,
        spawns=(
            "RingValeSwordsmanHorde_Veteranen",
            "LehenLossarnachAxteHorde_Veteranen",
            "PelegirSpearmenHorde_Veteranen",
            "MorthondBowmenHorde_Veteranen",
        ),
    ),
)

# What `best_summon` will hold charges for. Below this it spends on whatever is affordable,
# because a charge saved earns nothing and a battalion on the map does.
SAVE_FOR = SUMMONS[-1]
# How close to Lehen the rider must already be before saving beats spending. At 6 the wait is two
# charges - 150 seconds - against two ordinary battalions now; at 4 it is five minutes, which is
# most of an opening spent holding a currency that does nothing while held.
SAVE_FROM = 6


def charges_of(template: str) -> int | None:
    """How many charges a rider template carries, or None if it is not a rider.

    The name *is* the counter, so this is the whole of reading it. An unknown suffix answers None
    rather than raising: a differently-modded tree may declare riders this does not know, and the
    right response to one is to leave it alone.
    """
    name = template.lower()
    if not name.startswith(RIDER_PREFIX):
        return None
    suffix = name[len(RIDER_PREFIX) :]
    if not suffix.isdigit():
        return None
    return int(suffix)


def affordable(charges: int) -> tuple[Summon, ...]:
    """Every summon `charges` covers, cheapest first."""
    return tuple(summon for summon in SUMMONS if summon.charges <= charges)


def best_summon(charges: int, fits: Callable[[Summon], bool] | None = None) -> Summon | None:
    """What to spend on now, or None to keep saving.

    **The interesting case is the one where the answer is to buy nothing.** Lehen is four veteran
    battalions for eight charges and everything else is one ordinary battalion for two or three,
    so charges spent as they arrive buy strictly less army than charges saved - but only if the
    saving actually finishes, and at 75 seconds a charge the wait is minutes of a currency
    sitting idle while the match is decided elsewhere.

    So: spend freely while Lehen is far away, and stop spending once it is close enough that the
    wait is short. `SAVE_FROM` is where those cross. Above it this returns None even though
    something is affordable, which is the stage holding rather than the stage failing - the same
    distinction `stage_cast` draws about a power with nothing worth hitting.

    **`fits` is the second currency, and charges are the one that is not refundable.** A summon
    the command-point ceiling has no room for is discarded exactly as an over-cap recruit is -
    taken by the stream, dropped by logic, nothing reported - except that a recruit refused this
    way costs a selection and this costs *the charges*. Lehen is 270 points in one order against
    a battalion's 60, so it is the summon most likely to be refused and the most expensive one to
    have refused. The predicate filters every branch below rather than gating the last one.

    **Holding when Lehen does not fit, except at the cap.** Blocked on points rather than on
    charges, the right move is usually to wait: `stage_command_points` exists to raise the
    ceiling and a few cycles buys the room. At `MAX_CHARGES` that stops being true - accrual is
    being thrown away every 75 seconds - so at the cap this takes the best thing that does fit.

    Ties inside a charge band go to the earlier entry, so the table's order is the preference.
    """
    allowed = fits or (lambda _: True)
    if charges >= SAVE_FOR.charges and allowed(SAVE_FOR):
        return SAVE_FOR
    if SAVE_FROM <= charges < MAX_CHARGES:
        return None
    options = [summon for summon in affordable(charges) if allowed(summon)]
    return options[-1] if options else None


class SignalFire:
    """The signal fire mechanic, as a stage the generic loop can call on any faction.

    Mixed into the bot beside the other stages and reads the same members - `observation`,
    `session`, `side`, and `Orders.select`/`_issue`/`_report`. Everything it does is gated on the
    seat being Men and on a rider actually existing, so a Mordor run costs one string comparison.
    """

    def signal_fire_site(self, plot: GameObject, offered: tuple[str, ...]) -> str | None:
        """`SIGNAL_FIRE` when this claimed settlement is the one to spend on it, else None.

        **One standing at all times - a target to hold, not a purchase to make once.** The
        building earns nothing and defends nothing; what it buys is a rider, and one rider
        accruing a charge every 75 seconds is the whole of the mechanic. A second fire doubles the
        outlay for a second trickle, where 400g is two battalions or two farms - so the answer is
        never two.

        But nor is the answer "one, ever". The test is `owned_building`, which counts what is
        *standing*, so a fire that is razed puts the bot back in the market for one and the next
        qualifying settlement gets it. That is deliberate: the mechanic is worth nothing without a
        rider, and a match played out after losing the only fire is a match played without it. A
        measured run built on plot 215, lost it, reclaimed the plot and rebuilt - which is this
        working, not a leak.

        **Safe means it will still be standing in ten minutes**, which is a longer horizon than
        anything else the bot builds has to meet: a farm that dies has paid for part of itself
        already, where a signal fire that dies before its rider reaches two charges has bought
        nothing at all. Two tests, both deliberately blunt - no enemy within `HOLDING_RADIUS` of
        the plot right now, and the plot nearer our own base than the enemy's. The second is
        skipped when no enemy is known, which under fog is most of the opening; a plot with
        nothing visibly on it is the best answer available then.

        Returns None the moment either test fails, and the caller falls through to the ordinary
        farm-or-tents balance - a contested settlement is still worth a farm.
        """
        if SIGNAL_FIRE not in offered or self.owned_building(SIGNAL_FIRE):
            return None
        if any(
            self.hostile(other) and other.distance_to(plot.position) < HOLDING_RADIUS
            for other in self.observation.objects
        ):
            return None
        seat = self.enemy()
        if seat is not None:
            home = self.base_centre()
            if distance(plot.position, seat[1]) < distance(plot.position, home):
                return None
        return SIGNAL_FIRE

    def charges_held(self, observation: Observation | None = None) -> int:
        """Every charge this seat is holding, summed over all riders.

        **The oracle for a summon, and it has to be a sum because the rider is replaced.**
        Spending charges does not edit the rider in place: the engine destroys it and creates the
        lower-rung template, with a **new `object_id`** - measured live, `rider 1276` at 2 charges
        became `rider 1373` at 0. So a confirmation that looks up the old id finds nothing and
        reads a summon that worked as one that failed, which is exactly what the first version of
        `summon_at` did.

        Summing rather than tracking one rider also survives the case an id could not: two signal
        fires, two riders, and no way to say which of them the engine rebuilt. Charges only go up
        by accrual - one per rider per 75 seconds - so a total that has *fallen* inside a
        confirmation window is a spend and nothing else.
        """
        source = self.observation if observation is None else observation
        total = 0
        for owned in source.mine:
            charges = charges_of(owned.template_name)
            if charges is not None:
                total += charges
        return total

    def signal_fire_riders(self) -> list[tuple[GameObject, int]]:
        """Every errand rider owned, with its charge count, richest first.

        More than one is ordinary: a rider comes with each signal fire, and nothing stops a
        player building two. They accrue independently, so they are answered independently.
        """
        found = []
        for owned in self.observation.mine:
            charges = charges_of(owned.template_name)
            if charges is not None:
                found.append((owned, charges))
        return sorted(found, key=lambda pair: -pair[1])

    def summon_command_points(self, summon: Summon) -> int:
        """What this summon charges against the command-point ceiling.

        **The sum over everything it recruits, which is the whole reason this is not just
        `command_point_cost`.** Every other order in the bot queues one battalion and prices as
        one; **every summon here queues at least two**, and Lehen four. So the cheapest of them
        charges 120 points rather than 60 and Lehen charges 270 - and a price read off the first
        entry would clear the guard at half the true cost on every summon, and at a quarter of it
        on the one that must not be refused.

        Asked of the horde templates, because that is what the building produces and what carries
        a battalion's whole charge - see `Statics.command_point_cost` on why the member template
        under-counts.
        """
        return sum(self.statics.command_point_cost(name) for name in summon.spawns)

    def summon_fits(self, summon: Summon) -> bool:
        """Whether the ceiling has room for `summon` right now.

        A seat with no player state answers yes: the reading is the guard, not the mechanic, and
        an unreadable ceiling should not silently disable the whole stage. That matches
        `stage_recruit`, which also treats a missing `me` as "no opinion" rather than as "no".
        """
        me = self.observation.me
        if me is None:
            return True
        cost = self.summon_command_points(summon)
        return not cost or cost <= me.command_points_free

    def signal_fire_target(self, rider: GameObject) -> Vec3:
        """Where to aim the cast - the signal fire, falling back to the rider.

        **This is not where the troops appear, and that correction is the point of the method.**
        The rider fires a weapon and the *building* recruits, so the battalions arrive at the
        signal fire's exit wherever the cast was aimed. Aiming is therefore about reaching the
        building, not about placing an army: `StartAbilityRange` is 400, and a rider that has
        wandered further than that from its signal fire has to close the distance before the
        weapon can fire at all.

        The rider's own position is the fallback for the case where no signal fire is visible -
        a fogged observation, or the building destroyed while its rider lives. It is the best
        guess available and it is a guess; a rider outliving its building is a state this
        mechanic has nothing useful to do with anyway.
        """
        fires = [
            owned
            for owned in self.observation.mine
            if owned.template_name.lower().startswith(SIGNAL_FIRE.lower())
        ]
        if not fires:
            return rider.position
        return min(fires, key=lambda fire: rider.distance_to(fire.position)).position

    def summon_at(self, rider: GameObject, summon: Summon, position: Vec3) -> bool:
        """Fire one summon from `rider`, and say whether the **charges were actually spent**.

        **Selected first, like every other object-scoped order here.** The cast names the rider
        as its source, and an order acting on an unselected object is the failure `Orders.select`
        was written for.

        **The rider is its own oracle, and this used to report the send instead.** It looked as
        though a summon left no trace to confirm - the spawned battalions have no id to wait for
        and the engine reports neither charge spent nor refused. But the *rider* records it, in
        the one place this mechanic reads anyway: spending charges dismounts it down the ladder,
        so `ErrandRider13` becomes `ErrandRider5` and the template name is the receipt.

        Reporting the send was not a smaller version of this, it was the wrong answer entirely: a
        cast through the wrong constructor is accepted and discarded, so a run logged **520
        summons whose charge count never moved** and the ledger called every one of them a
        success. Anything that can be checked against the game should be, and the ledger line
        now means what it says.
        """
        if not self.select([rider]):
            return False
        before = self.charges_held()
        label = f"summon {summon.spawns[0][:12]}"

        def spent(obs: Observation) -> bool:
            return self.charges_held(obs) < before

        if not self._issue(
            label,
            lambda: self.session.cast(
                summon.power, summon.form, position, source_id=rider.object_id
            ),
        ):
            return self._report(label, False, "", "NOT SENT")
        landed = self.session.confirm(spent, timeout=BUILD_CONFIRM)
        return self._report(label, landed, "charges spent", "CHARGES UNSPENT - order discarded")

    def signal_fire_holding(self, charges: int) -> str:
        """Why nothing was spent, which is two different reasons and worth telling apart.

        Short of charges is the mechanic working - time passes and it resolves itself. Short of
        command points is a state something else has to fix, and a run that spends the whole
        match reporting it is a run whose `stage_command_points` is not keeping up. Reading one
        as the other in a log is how a ceiling problem hides behind a currency that is fine.
        """
        me = self.observation.me
        free = None if me is None else me.command_points_free
        if charges >= SAVE_FOR.charges:
            cost = self.summon_command_points(SAVE_FOR)
            return (
                f"{charges} charges is enough for {SAVE_FOR.spawns[0]} and three more, "
                f"but it costs {cost} command points and {free} are free"
            )
        missing = SAVE_FOR.charges - charges
        return (
            f"{charges} charges, saving the last {missing} for {SAVE_FOR.spawns[0]} and three more"
        )

    def stage_signal_fire(self) -> str | None:
        """Spend one rider's charges, or say why nothing was spent.

        One order per cycle like every other stage, and the richest rider goes first - it is the
        one closest to Lehen and the one whose charges are closest to being wasted at the cap.
        """
        if self.side.lower() != FIEFDOM_SIDE:
            return None
        riders = self.signal_fire_riders()
        if not riders:
            return None
        rider, charges = riders[0]
        summon = best_summon(charges, self.summon_fits)
        if summon is None:
            return f"rider {rider.object_id}: {self.signal_fire_holding(charges)}"
        if not self.summon_at(rider, summon, self.signal_fire_target(rider)):
            return f"rider {rider.object_id}: {summon.button} would not go out"
        left = charges - summon.charges
        return f"rider {rider.object_id}: {summon.spawns[0]} for {summon.charges}, {left} left"
