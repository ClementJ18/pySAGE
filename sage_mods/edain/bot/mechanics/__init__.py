"""Mechanics: rules the generic stages cannot express, on any faction.

Everything in `sage_mods.edain.bot` above this package is deliberately faction-blind. A stage asks
the tree what a building sells, what a plot can carry, what the army definition wants, and works
for any `Side` that answers - which is what lets one loop play Men and Mordor without a table of
unit names.

A mechanic is what does not fit that shape. Not because it belongs to a faction - **nothing here
does; see below** - but because it is neither a purchase, nor a unit, nor a place, so no amount of
reading command sets for things to build and ground to take ever arrives at it. `formations` is
the case in point: a battalion's second formation is addressed by a message nothing else in the
bot sends, and the state it toggles is legible only as a model-condition flag on the battalion's
members. It is also completely generic - it reads each battalion's own `HordeContain` and asks its
own control bar what buttons it has, so it plays every side that has formations at all.

**Faction-specific mechanics live under `factions/<side>/`, not here.** Gondor's signal fire is
the example and it used to sit in this package: a recruitment building nobody recruits from, paid
for in a currency that accrues on a *unit's template name*. It is a mechanic by the test above and
it is also Gondor's alone, and the second fact is what decides where it goes. The rule is worth
stating because it is the one that rotted: this package's docstring used to open by describing
mechanics as inert-off-their-own-faction mixins, which was true of the only one it had and false
of the idea.

**Each module here is one mechanic, self-contained, and mixed into the bot as a class.** That is
what lets the loop call them unconditionally, and what keeps a mechanic that finds nothing to do
costing a comparison rather than a branch in `decide`.
"""

from __future__ import annotations

from sage_mods.edain.bot.mechanics.formations import ALTERNATE, Formations, Posture

__all__ = ["ALTERNATE", "Formations", "Posture"]
