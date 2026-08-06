"""The build order, per faction - the part an ML policy replaces first."""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["PLANS", "Plan"]


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
    # **The production buildings, in the order they are wanted.** The first is the opening's -
    # nothing else is built until it stands - and the rest widen what can be recruited at all.
    # A barracks alone caps the army at whatever infantry that one building sells, so the
    # archery range and the stable are not luxuries: the faction's own `ArmyDefinition` asks
    # for a quarter archers and 5-15% cavalry, and neither is orderable without the building
    # that sells it. Read off `GondorFoundationCommandSet`, like every other template here.
    production: tuple[str, ...]
    # The unit to fall back on when the army pool can offer nothing - an unknown `Side`, or a
    # phase where nothing reachable has a share. `stage_recruit` normally picks from the
    # faction's `ArmyDefinition` instead, so this is a floor rather than the plan.
    unit: str
    # **The research centres, in the order the tech chain needs them** - laid only once there
    # is a surplus, see `RESEARCH_FLOOR`. Empty for a faction whose techs are already sold by
    # buildings the plan lays for other reasons: Mordor's basic training and fire arrows are on
    # the `MordorOrcPit` itself, so a Mordor plan that named a research building would be
    # spending a plot to reach upgrades it can already buy.
    #
    # Gondor's are neither optional nor reachable any other way. `GondorForge` sells all three
    # armour and blade techs and every one of them is gated on
    # `Upgrade_MarketplaceUpgradeIronOre`, which only `GondorMarketPlace` sells - so the pair is
    # a chain rather than two independent buildings, and the marketplace comes first or the
    # forge sells nothing that can be bought.
    research: tuple[str, ...] = ()
    # **The economy buildings that partner `resource`, laid in balance with it.** Together with
    # `resource` these form one set that is filled evenly - fewest standing first - rather than
    # in sequence, and each is capped at `ECONOMY_CAP`.
    #
    # **Evenly, because each of them carries its own discount ladder and the ladders are
    # independent.** A `GondorWohnhaus` takes a slice off the faction's elites and off
    # `CPObject`; a `GondorForge` takes the same slice off the five per-object unit upgrades.
    # Filling one set of six before starting the other reaches -30% on elites while unit upgrades
    # are still at full price for most of the match, and a base is plot-limited long before it is
    # gold-limited - a measured castle offered nine plots against the twelve this wants. So the
    # question a free plot asks is never "houses or forges", it is "which ladder is further
    # behind", and the answer keeps both climbing.
    #
    # `research` is the other thing a plot can carry and it is not this: a centre is bought for
    # what it *sells*, so it waits on a gold surplus (`RESEARCH_FLOOR`), where these are bought
    # for what they *are* and want only a plot.
    economy: tuple[str, ...] = ()
    # **The buildings worth raising on a claimed settlement, balanced the same way `economy` is.**
    # A settlement's palette offers several and `stage_expand` used to take the first button on
    # it, which for Men is the farm and only ever the farm.
    #
    # Named by their **level 1** template, because the palette swaps in a tier as the owner's
    # economy upgrades land - `GondorFarm_Extern` becomes `_Extern2` with
    # `Upgrade_EdainEconomyProduktionserhohungExtern` and `_Extern3` with
    # `Upgrade_EdainSiedlerWerkzeuge`, and the ranger tents do the same. `descends_from` is what
    # matches a tier back to the family it belongs to.
    #
    # **Only members that are genuinely interchangeable as income belong here.** For Men the two
    # carry the identical `TerrainResourceBehavior` - 28 gold per 12s - the identical
    # `EDAIN_ECONOMY_FLAG_UNPACK_COST_LEVEL1` of 200, and the identical build time, so which one
    # a flag gets is free. What they do *not* share is worth knowing and is why this is a balance
    # rather than a preference: the farm alone takes the marketplace's `GrandHarvest` bonus
    # (+130%), and the tents alone spawn slaved rangers on completion, so a tented settlement
    # defends itself. Empty leaves the old behaviour - take whatever the palette lists first.
    external: tuple[str, ...] = ()
    # **`(basic, elite)` pairs where the second is what the first becomes once a building
    # levels.** Edain gates the better version of a line behind its producer's own level rather
    # than behind a tech: `GondorWachterderVesteHorde` (the citadel guard, 600g) carries
    # `NeededUpgrade = Upgrade_StructureLevel2` on the barracks, and `GondorRangerHorde` (600g)
    # carries the same on the archery range. Both are simply absent from the command set until
    # then, which is why this needs no condition of its own - `producers` is level-aware, so the
    # elite appears in it exactly when the control bar would have offered it.
    #
    # The `ArmyDefinition` will not do this on its own. It asks for the citadel guard at 0% for
    # two of its three phases and 5% in the last, which is a number about an army in the
    # abstract and not about a barracks that has just been paid 400g to level up. `SUCCESSION`
    # moves most of the basic unit's share across instead - see `SUCCESSION_SHARE` for why most
    # and not all.
    succession: tuple[tuple[str, str], ...] = ()
    # How many economy buildings before spending on army. Low: an Easy AI does not punish a
    # fast army, and a bot that economises forever never attacks. **A floor, not a ceiling** -
    # `stage_build` keeps laying these on whatever plots are still free afterwards.
    resource_target: int = 3
    # **How many of `production` to lay** - types, not copies. One barracks with a queue cap of
    # four is a hard ceiling on spending: a match ended with 12,107 gold banked and only 22
    # recruit attempts in 456 cycles, because there was nowhere to put an order. Answering that
    # with more barracks was worse (plots are scarcer than gold, and `build Wohnhaus` landed 2
    # of 39); answering it with *different* buildings buys the same queue depth and a wider
    # army at once, which is the only version of this that pays for its plot twice.
    production_target: int = 4


# Keyed by the engine's own `Side` token, which is what `PlayerState.faction` carries. Note
# that Gondor's token is **`Men`** - keying this table on "gondor" matches nothing.
#
# **A plan names research centres, and the timing is the whole of why it can.** An earlier table
# named Gondor's marketplace-then-forge chain unconditionally and it was a bad trade: a measured
# match spent 1800g and two of a castle's handful of plots on the pair in the opening, bought
# nothing at all from either, and never got the gold back - because a plot spent on a shop in the
# first minutes is a plot not spent on the economy that would have paid for it.
#
# What was wrong there was not the buildings, it was laying them out of an opening's budget.
# `RESEARCH_FLOOR` moves them behind a surplus: at 1500 gold the economy is already running, the
# plots the economy wanted have been laid, and the money has nowhere better to go - which is the
# state the same measured match reached by cycle 7 and then sat in for 145 cycles.
#
# `stage_upgrade` still names no upgrade. It buys whatever the buildings actually owned happen
# to sell, because `upgrade_options` reads their live command sets; what a research centre does
# is widen that set, not add a line to a table here.
PLANS: dict[str, Plan] = {
    "men": Plan(
        resource="GondorWohnhaus",
        # **No siege works.** `RECRUIT_NEVER` bans siege from the mix, so the workshop is a plot
        # and 600 gold spent on a building whose whole output this bot will not order - and a
        # castle has a handful of plots, every one of which an economy building would have paid
        # back. It bought its own level-up in a measured run, which is a shop upgrading itself
        # while nobody shops there. Put it back the same day escorts exist.
        production=("GondorBarracks", "GondorArcherRange", "GondorStable"),
        production_target=3,
        unit="GondorFighterHorde",
        research=("GondorMarketPlace", "GondorForge"),
        # **The forge is a second town house, and the ini says so rather than the name.** It
        # carries the same `TerrainResourceBehavior` with the same `EDAIN_ECONOMY_INTERNAL_MONEY`
        # amount and interval, the same `EDAIN_ECONOMY_INTERNAL_BUILDCOST` of 400, and the same
        # six-rung `CostModifierUpgrade` ladder - pointed at the five per-object unit upgrades
        # where the house points its own at the elites. So as income the two are interchangeable
        # and the only thing that distinguishes a plot spent on one is which ladder it climbs,
        # which is exactly why they are laid in balance rather than in order.
        #
        # It stays in `research` as well, because the tech chain is still real: the three techs a
        # forge sells are all gated on `Upgrade_MarketplaceUpgradeIronOre`. Once the economy path
        # has put one up, `missing_research` is the marketplace alone and the plot reserve works
        # for the building that actually still needs one.
        economy=("GondorForge",),
        # `GondorEconomyPlotCommandSet` slot 1 and slot 3. Slot 2 is `GondorLeuchtfeuer`, which
        # is deliberately not here: at 400g it is twice the price, it earns nothing at all, and
        # what it sells is the fiefdom units - a production building on a settlement, which is a
        # different decision from this one and belongs to whatever stage learns to want them.
        external=("GondorFarm_Extern", "GondorRangerTents"),
        succession=(
            # The barracks' level 2 replaces the pikeman with the citadel guard, and the archery
            # range's replaces the archer with the ranger. Both elites deal the same damage type
            # as the unit they succeed - SPECIALIST and PIERCE respectively - so the counter
            # weighting that follows treats them as the same answer to the same threat, only a
            # better one.
            ("GondorSpearmanHorde", "GondorWachterderVesteHorde"),
            ("GondorArcherHorde", "GondorRangerHorde"),
        ),
    ),
    "mordor": Plan(
        resource="MordorTributposten",
        production=("MordorOrcPit", "MordorSiegeWorks", "MordorTrollCage"),
        unit="MordorFighterHorde",
        production_target=3,
    ),
}
