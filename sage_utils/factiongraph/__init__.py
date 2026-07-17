"""The faction ownership graph - engine-generic, shared by the front ends.

A `FactionGraph` links a `PlayerTemplate` to everything a player of it can field: its
spellbook powers, the start points that unpack its base, the structures placed or built,
and the units / heroes / upgrades those structures produce. The walk handles both base
mechanics - BFME1-style build plots (Edain) and vanilla builder units - see `graph`.
`sage_mods.edain` layers the Edain-specific pieces (a mod checkout's `bases/` folder, the CLI,
report and diff) on top; `sage_ui` renders the drill-down.
"""

from sage_utils.factiongraph.bases import (
    BaseLayout,
    collect_base_layouts,
    find_base_file,
    game_base_layout,
    resolve_base_layout,
)
from sage_utils.factiongraph.graph import (
    LayoutResolver,
    build_faction_graph,
    build_faction_graphs,
    builder_targets,
    find_faction,
    playable_factions,
    plot_flags,
    start_points,
)
from sage_utils.factiongraph.model import (
    CreatedObject,
    FactionGraph,
    Power,
    ProducedUnit,
    Producer,
    Profile,
    RecruitedHero,
    ResearchableUpgrade,
    Spellbook,
    StartPoint,
    StartPointKind,
    Structure,
    StructureRole,
    ToDictMixin,
    Weapon,
)
from sage_utils.factiongraph.profile import build_profile

__all__ = [
    "BaseLayout",
    "CreatedObject",
    "FactionGraph",
    "LayoutResolver",
    "Power",
    "ProducedUnit",
    "Producer",
    "Profile",
    "RecruitedHero",
    "ResearchableUpgrade",
    "Spellbook",
    "StartPoint",
    "StartPointKind",
    "Structure",
    "StructureRole",
    "ToDictMixin",
    "Weapon",
    "build_faction_graph",
    "build_faction_graphs",
    "build_profile",
    "builder_targets",
    "collect_base_layouts",
    "find_base_file",
    "find_faction",
    "game_base_layout",
    "playable_factions",
    "plot_flags",
    "resolve_base_layout",
    "start_points",
]
