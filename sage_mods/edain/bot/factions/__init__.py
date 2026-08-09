"""One package per faction: everything the bot knows about a side that it cannot read off the tree.

Above this package the bot is deliberately faction-blind. A stage asks the tree what a building
sells, what a plot can carry, what the army definition wants, and works for any `Side` that
answers - which is what lets one loop play Men and Mordor without a table of unit names. This is
where the exceptions live, and each one is an exception for a stated reason.

**Most faction detail is not here, and that is the point.** Powers, the spellbook, the hero
roster and the unit mix are all faction-specific and all four are already declared in the game's
own data, so the bot reads them: `Statics.spell_store`, `Statics.spell_book`,
`Statics.hero_roster`, `Statics.army_plan`, each keyed by the same `Side` token this registry is.
Restating any of them in Python would be a copy that goes stale the next time Edain patches. What
belongs in a faction package is the residue - a *judgement* the tree cannot state (which hero is
worth buying) or a *mechanic* no amount of reading command sets arrives at (Gondor's signal fire).

**`mechanics/` is the other half of the split and it is not this.** A mechanic there is
faction-agnostic: `formations` reads each battalion's own `HordeContain` and plays every side
that has formations at all. A mechanic that only ever fires on one seat is faction code and lives
in that faction's package - which is why `signal_fire` sits under `men/` rather than beside it.

## Adding a faction

Three steps, and the second is the one that is easy to forget:

1. `factions/<side>/plan.py` with a `Plan`, and `factions/<side>/__init__.py` exporting it.
2. An entry in `FACTIONS` below, keyed by the **engine's own `Side` token** lowercased. Gondor's
   is `Men`, not `Gondor` - `PlayerState.faction` is what this is matched against, and keying it
   on the faction's English name matches nothing.
3. If the faction has a mechanic of its own, a base class on `FactionMechanics`.
"""

from __future__ import annotations

from dataclasses import dataclass

from sage_mods.edain.bot.factions.men import MEN, SignalFire
from sage_mods.edain.bot.factions.mordor import MORDOR
from sage_mods.edain.bot.factions.plan import Plan

__all__ = ["FACTIONS", "Faction", "FactionMechanics", "Plan", "faction_for"]


@dataclass(frozen=True)
class Faction:
    """One playable side, as the bot understands it.

    Thin on purpose. `plan` is the only field because it is the only faction-specific thing the
    bot currently *declares* rather than reads - see the module docstring. A faction that needs
    something the tree cannot answer gets a field here and a module in its package; a faction
    that needs a whole mechanic gets a mixin instead, because a mechanic is behaviour and this is
    data.
    """

    # The engine's `Side` token as the tree spells it (`Men`, `Mordor`), for display. The
    # registry is keyed by its lowercase form, which is what a live `PlayerState.faction`
    # compares equal to.
    side: str
    plan: Plan


class FactionMechanics(SignalFire):
    """Every faction's own mechanics, composed into one mixin for the bot to inherit.

    **One base class rather than a branch, because the bot is one class chain.** Each faction
    mechanic answers None the moment the seat is not its own, so the generic loop calls them all
    unconditionally and a Mordor run pays one `Side` comparison per cycle for the privilege.

    This composite exists so that `warfare.py` names no faction. It used to inherit `SignalFire`
    directly, which put Gondor in the bases of a class whose whole claim is that it plays any
    side; adding a faction's mechanic is now one base here and nothing anywhere else.
    """


# Keyed by the engine's own `Side` token, lowercased - see the module docstring on why that is
# `men` rather than `gondor`.
FACTIONS: dict[str, Faction] = {
    "men": Faction(side="Men", plan=MEN),
    "mordor": Faction(side="Mordor", plan=MORDOR),
}


def faction_for(side: str) -> Faction | None:
    """The faction for a live `PlayerState.faction`, or None for a side with no plan.

    None rather than a default, because borrowing another faction's build order is a decision
    the caller has to make out loud - `--faction` is how a run says so. Silently falling back
    would have the bot ordering Gondor buildings on a Mordor seat and reporting nothing.
    """
    return FACTIONS.get(side.lower())
