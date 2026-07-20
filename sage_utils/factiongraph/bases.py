"""Resolving a base layout (`.bse`) into the structures it places.

A faction's castle/camp/outpost does not name its buildings in the ini - the start flag's
`CastleBehavior` names a *base layout* (`CastleToUnpackForFaction = Men gondor_castle …`), and the
layout itself is a binary WorldBuilder file under the mod's `bases/` folder (`gondor_castle.bse`).
The placed objects in that file - the citadel keep, the build foundations, the prebuilt walls and
gates - are the structures a player actually sees once the base unpacks.

So this module bridges `sagemap` (which parses the `.bse`) and the loaded `Game` (which knows each
placed template's KindOf): it finds the layout file, reads the distinct placed templates, and
classifies them into citadel / foundation / prebuilt by KindOf. `sagemap` is an optional
dependency; without it base decomposition degrades to empty rather than failing.

Two consumption paths: `resolve_base_layout` reads a mod checkout's `bases/` folder on demand
(the `sage-edain` CLI), and `collect_base_layouts` sweeps every `.bse` under a root once - the
source loader calls it on the merged tree extracted from `.big` archives, so a game loaded from
archives carries its layouts (`game.base_layouts`) for the graph to use.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from sage_ini.model.state import has_kindof

# KindOf flags that classify a placed base object. A keep is the citadel; a BASE_FOUNDATION is a
# build plot; any other STRUCTURE that survives is a prebuilt wall/gate/tower.
_KEEP_KINDS = ("CASTLE_KEEP", "COMMANDCENTER")
_FOUNDATION_KIND = "BASE_FOUNDATION"
_STRUCTURE_KIND = "STRUCTURE"

# Placed templates to drop outright - engine markers that classify as structures/foundations but are
# not buildings the player sees (the base-center bone carries BASE_FOUNDATION but builds nothing).
_IGNORE_TEMPLATES = frozenset({"BaseCenterGeneric"})


@dataclass
class BaseLayout:
    """The structures a base layout places, classified by KindOf. `citadel` is the keep object's
    name (the first CASTLE_KEEP/COMMANDCENTER placed); `foundations` the build plots; `prebuilt`
    the remaining structures (walls, gates, towers). Non-structure markers (camp/castle toggles,
    base-center bones, floors) are dropped."""

    name: str
    citadel: str | None = None
    foundations: list[str] = field(default_factory=list)
    prebuilt: list[str] = field(default_factory=list)


def find_base_file(bases_dir: Path, base_name: str) -> Path | None:
    """The `.bse` file for `base_name` under `bases_dir`, or None. Edain stores each base in a
    same-named folder (`bases/gondor_castle/gondor_castle.bse`); orientation variants
    (`gondor_castleNW`) share the object set, so the canonical name is enough."""
    candidates = [
        bases_dir / base_name / f"{base_name}.bse",
        bases_dir / f"{base_name}.bse",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    # Fall back to a case-insensitive search for the file anywhere under bases_dir.
    target = f"{base_name}.bse".casefold()
    for path in bases_dir.rglob("*.bse"):
        if path.name.casefold() == target:
            return path
    return None


def _placed_templates(base_file: Path) -> list[str]:
    """Distinct placed object template names in a `.bse`, in first-seen order. Returns empty when
    sagemap is unavailable or the file has no object list."""
    try:
        from sage_map import parse_map_from_path  # noqa: PLC0415 - lazy: only for base layouts
    except ImportError:
        return []
    try:
        raw = parse_map_from_path(str(base_file))
    except Exception:  # noqa: BLE001 - a failure on one binary base must not abort the graph
        return []
    objects_list = getattr(raw, "objects_list", None)
    if objects_list is None:
        return []
    names: list[str] = []
    seen: set[str] = set()
    for obj in objects_list.object_list:
        name = getattr(obj, "type_name", None)
        if name and name not in seen:
            seen.add(name)
            names.append(name)
    return names


def layout_from_file(game, base_file: Path, base_name: str) -> BaseLayout:
    """The `BaseLayout` for one `.bse` file: parse it and classify each distinct placed
    template against `game` by KindOf. Degrades to an empty layout (name only) when sagemap
    is not installed or the file cannot be parsed."""
    layout = BaseLayout(name=base_name)
    for template in _placed_templates(base_file):
        if template in _IGNORE_TEMPLATES:
            continue
        obj = game.objects.get(template)
        if obj is None:
            continue
        if layout.citadel is None and any(has_kindof(obj, k) for k in _KEEP_KINDS):
            layout.citadel = template
        elif has_kindof(obj, _FOUNDATION_KIND):
            layout.foundations.append(template)
        elif has_kindof(obj, _STRUCTURE_KIND):
            layout.prebuilt.append(template)
    return layout


def resolve_base_layout(game, bases_dir: Path | None, base_name: str) -> BaseLayout:
    """The `BaseLayout` for `base_name`: parse its `.bse` (under `bases_dir`) and classify each
    distinct placed template against `game` by KindOf. Degrades to an empty layout (name only) when
    `bases_dir` is None, the file is missing, or sagemap is not installed."""
    if bases_dir is None:
        return BaseLayout(name=base_name)
    base_file = find_base_file(bases_dir, base_name)
    if base_file is None:
        return BaseLayout(name=base_name)
    return layout_from_file(game, base_file, base_name)


def collect_base_layouts(game, root: Path) -> dict[str, BaseLayout]:
    """Every base layout under `root`, keyed by its lower-cased base name (the file stem -
    the same token a `CastleToUnpackForFaction` row uses, matched case-insensitively). One
    sweep at load time, so a game assembled from `.big` archives can answer layout lookups
    without the archives on disk. Empty when sagemap is not installed or no `.bse` exists;
    an unparsable file contributes an empty layout rather than aborting the load."""
    layouts: dict[str, BaseLayout] = {}
    for path in sorted(root.rglob("*.bse")):
        name = path.stem
        key = name.casefold()
        if key not in layouts:
            layouts[key] = layout_from_file(game, path, name)
    return layouts


def game_base_layout(game, base_name: str) -> BaseLayout | None:
    """The layout `base_name` resolves to from the table a loader attached to the game
    (`game.base_layouts`, written by `sage_utils.sources.load_sources`), or None when the
    game carries no layouts or doesn't know this one - the default resolver the faction
    graph uses when no `bases/` folder is at hand."""
    layouts = getattr(game, "base_layouts", None)
    if not layouts:
        return None
    return layouts.get(str(base_name).casefold())
