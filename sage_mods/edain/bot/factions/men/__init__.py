"""Gondor - everything this bot knows about the Men seat that it cannot read off the tree.

Two things, and the split between them is the honest state of the code rather than a design:

- [`plan`](plan.py) - the build order. Which buildings, in which order, which unit to fall back
  on, which hero, which siege works, which holdings are worth defending first.
- [`signal_fire`](signal_fire.py) - the mechanic. A recruitment building nobody recruits from,
  paid for in a currency that accrues on a *unit's template name*, spent through special powers.
  Nothing generic arrives at that by reading command sets, which is what makes it faction code
  rather than a stage.

**What is deliberately not here: powers, the spellbook, and the unit roster.** All three are
faction-specific facts and all three are already declared in the game's own data, so the bot
reads them instead of restating them - `Statics.spell_store("Men")` for what the store sells,
`Statics.spell_book("Men")` for what the book can fire and how each one casts,
`Statics.army_plan("Men")` for the shipped `MenOfTheWestArmy` mix, `Statics.hero_roster("Men")`
and `Statics.revive_slots` for the heroes. A `powers.py` here would be a copy of `SpellBookMp`
that goes stale the next time Edain patches. The seam exists if a *judgement* about one of them
ever needs writing down - `Plan.hero` is exactly that, one line, because which hero to buy is not
in the tree.
"""

from __future__ import annotations

from sage_mods.edain.bot.factions.men.plan import MEN
from sage_mods.edain.bot.factions.men.signal_fire import (
    CHARGE_SECONDS,
    MAX_CHARGES,
    RIDER_PREFIX,
    SECOND_FIRE_EXTERNAL,
    SIGNAL_FIRE,
    SUMMONS,
    SignalFire,
    Summon,
    affordable,
    best_summon,
    charges_of,
    role_wait,
)

__all__ = [
    "CHARGE_SECONDS",
    "MAX_CHARGES",
    "MEN",
    "RIDER_PREFIX",
    "SECOND_FIRE_EXTERNAL",
    "SIGNAL_FIRE",
    "SUMMONS",
    "SignalFire",
    "Summon",
    "affordable",
    "best_summon",
    "charges_of",
    "role_wait",
]
