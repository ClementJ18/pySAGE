"""Faction mechanics: the rules one faction has that the generic stages cannot express.

Everything in `sage_mods.edain.bot` above this package is deliberately faction-blind. A stage
asks the tree what a building sells, what a plot can carry, what the army definition wants, and
works for any `Side` that answers - which is what lets one loop play Men and Mordor without a
table of unit names. `plans.py` is the one concession, and it is a *build order*: names, counts,
priorities. Nothing structural.

A mechanic is what does not fit that. Edain gives some factions a resource the engine does not
model as a resource, spent through orders that look nothing like recruiting - and no amount of
reading command sets turns that into "a building that sells units", because it is not one. The
signal fire is the clearest case: its units are bought with a currency that accrues on a unit's
*template name*, and are ordered as special powers rather than as builds.

**Each module here is one mechanic, self-contained, and inert off its own faction.** The mixins
answer None the moment the seat is not theirs, so the generic loop can call them unconditionally
and a Mordor run pays one template check per cycle for the privilege. That is the whole reason
they are mixins rather than branches in `decide`.
"""

from __future__ import annotations

from sage_mods.edain.bot.mechanics.signal_fire import (
    CHARGE_SECONDS,
    MAX_CHARGES,
    RIDER_PREFIX,
    SUMMONS,
    SignalFire,
    Summon,
    affordable,
    best_summon,
    charges_of,
)

__all__ = [
    "CHARGE_SECONDS",
    "MAX_CHARGES",
    "RIDER_PREFIX",
    "SUMMONS",
    "SignalFire",
    "Summon",
    "affordable",
    "best_summon",
    "charges_of",
]
