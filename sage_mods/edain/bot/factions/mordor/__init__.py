"""Mordor - a build order and nothing else, so far.

No mechanic module: nothing in Mordor's palette has yet turned out to need one. That is a
statement about what has been *read*, not about the faction - Edain gives Mordor its own
resource oddities, and the first one that cannot be expressed as "a building that sells units"
belongs here beside `plan`, the way Gondor's signal fire does.

The rest - powers, spellbook, roster, army mix - is read from the tree by `Statics`, exactly as
it is for Men. See `factions.men` for why none of that is declared in code.
"""

from __future__ import annotations

from sage_mods.edain.bot.factions.mordor.plan import MORDOR

__all__ = ["MORDOR"]
