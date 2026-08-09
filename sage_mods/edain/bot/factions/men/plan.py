"""Gondor's build order.

**The `Side` token is `Men`, not `Gondor`** - that is what `PlayerState.faction` carries and what
this package is named for. Keying anything here on "gondor" matches nothing.

**A plan names research centres, and the timing is the whole of why it can.** An earlier table
named Gondor's marketplace-then-forge chain unconditionally and it was a bad trade: a measured
match spent 1800g and two of a castle's handful of plots on the pair in the opening, bought
nothing at all from either, and never got the gold back - because a plot spent on a shop in the
first minutes is a plot not spent on the economy that would have paid for it.

What was wrong there was not the buildings, it was laying them out of an opening's budget.
`RESEARCH_FLOOR` moves them behind a surplus: at 1500 gold the economy is already running, the
plots the economy wanted have been laid, and the money has nowhere better to go - which is the
state the same measured match reached by cycle 7 and then sat in for 145 cycles.

`stage_upgrade` still names no upgrade. It buys whatever the buildings actually owned happen to
sell, because `upgrade_options` reads their live command sets; what a research centre does is
widen that set, not add a line to a table here.
"""

from __future__ import annotations

from sage_mods.edain.bot.factions.plan import Plan

__all__ = ["MEN"]

MEN = Plan(
    resource="GondorWohnhaus",
    # **No siege works in `production`.** `RECRUIT_NEVER` bans siege from the ordinary mix, so
    # outside a push the workshop is a plot and 600 gold spent on a building whose output this
    # bot will not order - and a castle has a handful of plots, every one of which an economy
    # building would have paid back. It bought its own level-up in a measured run, which is a
    # shop upgrading itself while nobody shops there. `siege` below is where it belongs.
    production=("GondorBarracks", "GondorArcherRange", "GondorStable"),
    production_target=3,
    unit="GondorFighterHorde",
    research=("GondorMarketPlace", "GondorForge"),
    # **The forge is a second town house, and the ini says so rather than the name.** It carries
    # the same `TerrainResourceBehavior` with the same `EDAIN_ECONOMY_INTERNAL_MONEY` amount and
    # interval, the same `EDAIN_ECONOMY_INTERNAL_BUILDCOST` of 400, and the same six-rung
    # `CostModifierUpgrade` ladder - pointed at the five per-object unit upgrades where the house
    # points its own at the elites. So as income the two are interchangeable and the only thing
    # that distinguishes a plot spent on one is which ladder it climbs, which is exactly why they
    # are laid in balance rather than in order.
    #
    # It stays in `research` as well, because the tech chain is still real: the three techs a
    # forge sells are all gated on `Upgrade_MarketplaceUpgradeIronOre`. Once the economy path has
    # put one up, `missing_research` is the marketplace alone and the plot reserve works for the
    # building that actually still needs one.
    economy=("GondorForge",),
    # `GondorEconomyPlotCommandSet` slot 1 and slot 3. Slot 2 is `GondorLeuchtfeuer`, which is
    # deliberately not here: at 400g it is twice the price, it earns nothing at all, and what it
    # sells is the fiefdom units - a production building on a settlement, which is a different
    # decision from this one and belongs to `signal_fire`, which makes it.
    external=("GondorFarm_Extern", "GondorRangerTents"),
    succession=(
        # The barracks' level 2 replaces the pikeman with the citadel guard, and the archery
        # range's replaces the archer with the ranger. Both elites deal the same damage type as
        # the unit they succeed - SPECIALIST and PIERCE respectively - so the counter weighting
        # that follows treats them as the same answer to the same threat, only a better one.
        ("GondorSpearmanHorde", "GondorWachterderVesteHorde"),
        ("GondorArcherHorde", "GondorRangerHorde"),
    ),
    # `GondorWorkshopCommandSet` slots 1-3: the siege shield, the battering ram and the trebuchet.
    # It is the only building on Gondor's palette that sells any of them.
    siege=("GondorWorkshop",),
    # `FactionMen[2]`, and one of the two ungated revive slots on the barracks the plan already
    # builds first. See `Plan.hero` for why it is this one.
    hero="GondorBeregond",
    # The signal fire, which is the one holding on this palette worth a tower ahead of whatever
    # is nearest the enemy - see `Plan.precious` and `signal_fire`, which explains what makes it
    # unlike every other outlying building Gondor puts up.
    precious=("GondorLeuchtfeuer",),
)
