"""The shape of a faction's build order - the part an ML policy replaces first.

The *schema*, not the data. Each faction fills this in in its own package under
`factions/<side>/plan.py`, and `factions/__init__.py` collects them; this file stays here beside
them because it is the one thing every faction has in common and belongs to none of them.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["Plan"]


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
    # **The siege works, wanted only once the push is on.** It is worth no plot at all while
    # there is map to take - it sells nothing that helps take a settlement, and every plot spent
    # on it is a discount ladder that stops climbing - which is why this is a field of its own
    # rather than another entry in `production`.
    #
    # The endgame is the one part of the match where that reverses. What is left to win is a keep,
    # keeps are what siege is for, and the escort problem that banned siege everywhere else
    # (`RECRUIT_NEVER`) does not exist during a push: the whole force is already walking to one
    # place as one body, so a ram in it is escorted by definition.
    #
    # **Internal plots only, for Gondor.** `GondorFoundationCommandSet` slot 6 is
    # `Command_ConstructGondorWorkshop` and no external palette offers it, so a base with its
    # castle full has to sell something to raise one - which is `stage_sell`'s existing job the
    # moment this names a building it wants.
    siege: tuple[str, ...] = ()
    # **The one hero worth fielding, by template. Empty means this faction fields none.**
    #
    # One rather than a list, and named here rather than derived, because a hero is the purchase
    # the army mix cannot price. `wanted_mix` reasons in shares of an army - a unit is wanted
    # because the army is short of what it does - and a hero is not a share of anything: it is one
    # object at 1300 to 4000 gold whose value is a kit, a level curve and a body that has to be
    # kept alive. Handing that to a ratio buys the cheapest hero on the roster forever, or six of
    # them, depending on which way the arithmetic falls.
    #
    # Which one is a judgement, and the argument for Gondor's is cost against what the casting
    # stage can actually use. `GondorBarracksCommandSet` - the plan's own first building - has
    # exactly two ungated revive slots: Beregond at 1300g and 30 command points, and Boromir at
    # 1800. Beregond's level-1 `Kompanie` is a summon of six citadel guards, which is the earliest
    # aimable ability either of them has; Boromir's level-1 Last Stand is one of the abilities
    # `Statics.hero_powers` cannot classify at all, and his Horn waits for level 3. So the cheaper
    # hero is also the one that does something sooner.
    hero: str = ""
    # **Holdings worth defending ahead of whatever is simply nearest the enemy**, by template.
    #
    # `tower_spot` normally picks the most exposed outlying building, which is the right rule for
    # the farms and tents that make up almost all of them: one razed is 200g and a walk. A few
    # buildings are not like that, and the plan is the only thing that can say which - Gondor's
    # signal fire is bought once, is never rebuilt, has no garrison and no spawn, and is worth
    # nothing until its rider has spent ten minutes accruing charges.
    #
    # This field is why `powers.py` names no faction. It used to import `SIGNAL_FIRE` from the
    # signal-fire mechanic to special-case exactly this, which put a Gondor template inside a
    # module whose whole claim is that it plays any side.
    precious: tuple[str, ...] = ()
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
