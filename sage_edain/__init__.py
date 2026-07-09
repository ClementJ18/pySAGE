"""Comprehensive exploration of Edain factions.

An Edain faction is a `PlayerTemplate` with `PlayableSide = Yes`. From it hang a spellbook, the
starting plot flags that unpack a base (citadel + foundations) or a single structure, the buildings
constructed on those foundations, and the units / heroes / upgrades those buildings produce.
`sage_edain` walks the loaded `Game` (and the mod's binary base layouts, via sagemap) into one
explicit ownership graph - the link between a faction and everything a player of it can see.

It is an orchestration layer: resolution lives in `sage_ini.model.state` and `sage_utils.views`;
this package only assembles those primitives into the `FactionGraph` shape.
"""

from sage_edain.diff import FactionDiff, ModDiff, diff_faction, diff_graphs, format_mod_diff
from sage_edain.graph import (
    build_faction_graph,
    build_faction_graphs,
    find_faction,
    playable_factions,
)
from sage_utils.factiongraph import (
    BaseLayout,
    FactionGraph,
    Power,
    ProducedUnit,
    Producer,
    RecruitedHero,
    ResearchableUpgrade,
    Spellbook,
    StartPoint,
    StartPointKind,
    Structure,
    StructureRole,
    resolve_base_layout,
)

__all__ = [
    "BaseLayout",
    "FactionDiff",
    "FactionGraph",
    "ModDiff",
    "Power",
    "ProducedUnit",
    "Producer",
    "RecruitedHero",
    "ResearchableUpgrade",
    "Spellbook",
    "StartPoint",
    "StartPointKind",
    "Structure",
    "StructureRole",
    "build_faction_graph",
    "build_faction_graphs",
    "diff_faction",
    "diff_graphs",
    "find_faction",
    "format_mod_diff",
    "playable_factions",
    "resolve_base_layout",
]
