"""The Edain wiring over the shared faction-graph core (`sage_utils.factiongraph`).

The walk, the seeding strategies and the model are engine-generic and live in the shared
package; what is Edain-specific here is the mod's canonical plot-flag names (the shared
core otherwise *discovers* flags by scanning CastleBehaviors) and where base layouts come
from - a mod checkout's `bases/` folder, resolved on demand - which the CLI passes as
`bases_dir`. Without one, the core falls back to any layout table the source loader
attached to the game, then to recording bare base names."""

from __future__ import annotations

from functools import partial
from pathlib import Path

from sage_utils.factiongraph import (
    FactionGraph,
    find_faction,
    playable_factions,
    resolve_base_layout,
)
from sage_utils.factiongraph import build_faction_graph as _build_faction_graph
from sage_utils.factiongraph.graph import LayoutResolver

__all__ = [
    "START_FLAGS",
    "build_faction_graph",
    "build_faction_graphs",
    "find_faction",
    "playable_factions",
]

# The canonical Edain plots (castle, camp, economy, expansion), named explicitly rather
# than discovered: Edain's data carries dozens of noisy CastleBehavior variants - castle
# orientations (…NW/…NE), prebuilt/AI/map-template flags, captured flags - and the named
# set keeps the CLI's reports exact.
START_FLAGS = (
    "FestungPlotFlag_Real",
    "LagerPlotFlag_Real",
    "WirtschaftPlotFlag_Real",
    "ExpansionPlotFlag",
)


def _bases_resolver(bases_dir: Path | None) -> LayoutResolver | None:
    """A layout resolver over the mod's `bases/` folder, or None (the core's default -
    the game's own layout table) when no folder was given."""
    if bases_dir is None:
        return None
    return partial(_resolve_from_dir, bases_dir)


def _resolve_from_dir(bases_dir: Path, game, base_name: str):
    return resolve_base_layout(game, bases_dir, base_name)


def build_faction_graph(
    game, faction, bases_dir: Path | None = None, start_flags=START_FLAGS
) -> FactionGraph:
    """The full ownership graph for one `PlayerTemplate`. `bases_dir` (the mod's `bases/`
    folder) enables base-layout decomposition; without it the loader-attached layout table
    is used when present, else start points record only the base name. `start_flags` are
    the plot-flag object names whose buildings/bases are gathered (defaults to the
    canonical Edain plots)."""
    return _build_faction_graph(game, faction, start_flags, _bases_resolver(bases_dir))


def build_faction_graphs(game, bases_dir: Path | None = None) -> list[FactionGraph]:
    """A graph for every playable faction, in faction-table order - what the CLI builds when no
    single faction is named."""
    return [build_faction_graph(game, faction, bases_dir) for faction in playable_factions(game)]
