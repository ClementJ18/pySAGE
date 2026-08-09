"""Mordor's build order.

Thinner than Gondor's, and every gap is a decision rather than an omission.

**No `research`**, because Mordor's techs are sold by buildings the plan lays anyway: basic
training and fire arrows are on the `MordorOrcPit` itself, so naming a research centre here would
spend a plot to reach upgrades that are already reachable.

**No `economy`, `external` or `succession`** - those three were each measured on Gondor and the
readings that justify them are Gondor's. Mordor's own second economy building, its settlement
palette and its elite lines have not been read out of the tree the same way, and a plan that
guessed at them would be a table of names nobody had checked. Left empty they fall back to
behaviour that works without them: one economy building, whatever a settlement's palette lists
first, and the `ArmyDefinition`'s own shares.

**No `siege` and no `hero`** for the same reason. `MordorSiegeWorks` is already in `production`,
which is not where the push logic looks - filling `siege` properly means checking whether
Mordor's siege is an internal-plot building the way Gondor's is.
"""

from __future__ import annotations

from sage_mods.edain.bot.factions.plan import Plan

__all__ = ["MORDOR"]

MORDOR = Plan(
    resource="MordorTributposten",
    production=("MordorOrcPit", "MordorSiegeWorks", "MordorTrollCage"),
    unit="MordorFighterHorde",
    production_target=3,
)
