"""Hand-labeled object-filter -> archetype registry, plus a discovery tool to grow it.

A weapon's `DamageScalar` lines scope a multiplier to an object filter (`250% ANY +HERO`).
To summarise a weapon for an infobox we name the recognisable filter shapes: `+HERO +MACHINE
+MONSTER` is a "Single" target (a unit not in a horde), `+STRUCTURE` is a "Structure".
`ARCHETYPES` maps a filter's shape to that label; the renderer interprets the multiplier
context (0% excludes, >100% is a bonus) on top of the label.

The key is the `(included, excluded)` pair of object/kindof name sets, so `+INFANTRY -CAVALRY
-HERO` ("infantry, but not cavalry/hero") stays distinct from `+CAVALRY +HERO +INFANTRY`. The
descriptor (ANY/ALL/NONE) and relations (ENEMIES/ALLIES) are dropped - they scope targeting,
not the object category. A `0%`-on-exclusion filter (`ALL -STRUCTURE` = only structures are
hit) is the renderer's job to read as its complement, not a label mapping.

`ARCHETYPES` is grown by hand. Run this module over a corpus to list the distinct filter
shapes by frequency, then label the common ones:

    .venv/Scripts/python -m sage_wiki.archetypes <source-folder>...

Unlabeled shapes fall back to a readable auto-string so nothing breaks while labeling.
"""

from collections import Counter

from sage_ini.model.nuggets import DamageNugget
from sage_utils.sources import load_sources
from sage_utils.views import filter_signature, safe

# An archetype key is the `(included, excluded)` pair of a filter's object/kindof names.
# Label the common ones discovered by `discovery_report`; the empty pair is the unscoped
# "everything".
ArchetypeKey = tuple[frozenset[str], frozenset[str]]

ARCHETYPES: dict[ArchetypeKey, str] = {
    (frozenset({"STRUCTURE"}), frozenset()): "Structure",
    (frozenset({"HERO"}), frozenset()): "Hero",
    (frozenset({"INFANTRY"}), frozenset({"CAVALRY", "HERO"})): "Infantry",
    # An ally-scoped filter with no kindof (`ALL ALLIES`) reduces to the empty pair. A bare
    # unscoped multiplier (`object_filter is None`) is the renderer's global "All", handled
    # before this lookup, so it does not collide with this label.
    (frozenset(), frozenset()): "Units and heroes",
    (frozenset({"CAVALRY", "INFANTRY"}), frozenset({"HERO", "MACHINE", "MONSTER"})): "Units",
    (frozenset({"DOZER", "HERO", "MACHINE", "MONSTER"}), frozenset()): "Single units",
    (frozenset({"CAVALRY"}), frozenset()): "Cavalry",
    (frozenset({"CAVALRY", "DOZER", "HERO", "INFANTRY", "MACHINE", "MONSTER"}), frozenset()): (
        "All unit"
    ),
    (frozenset({"MONSTER"}), frozenset()): "Monster",
    (frozenset({"COMMANDCENTER"}), frozenset()): "Citadel",
    (frozenset({"TROLL"}), frozenset()): "Troll",
    (frozenset({"MACHINE"}), frozenset()): "Machine",
    (frozenset({"ElvenEntMoot", "EntMoot"}), frozenset()): "Ent moot",
    (frozenset({"HERO", "MACHINE", "MONSTER"}), frozenset()): "Single",
    (frozenset({"PIKE"}), frozenset()): "Pikemen",
    (frozenset({"INFANTRY"}), frozenset({"CAVALRY"})): "Infantry",
    (frozenset({"ARCHER"}), frozenset()): "Archer",
    (frozenset(), frozenset({"HERO"})): "Units",
    (frozenset({"MACHINE", "STRUCTURE"}), frozenset()): "Machines and structures",
    (frozenset({"HERO", "MONSTER"}), frozenset()): "Hero and monster",
    (frozenset({"CAVALRY", "INFANTRY"}), frozenset()): "Infantry",
    (frozenset({"CAVALRY", "MONSTER"}), frozenset()): "Cavalry and Monsters",
    (
        frozenset(
            {
                "GondorTrebuchet",
                "GondorTrebuchetWall",
                "IsengardBallista",
                "MordorCatapult",
                "STRUCTURE",
            }
        ),
        frozenset(),
    ): "Catapults",
    (frozenset({"GondorGwaihir", "MordorFellBeast", "MordorWitchKingOnFellBeast"}), frozenset()): (
        "Flyers"
    ),
    (frozenset({"MACHINE", "MONSTER", "SHIP"}), frozenset()): "Machines, monsters and ships",
    (frozenset({"ShipWright"}), frozenset()): "Shipyard",
    (
        frozenset(),
        frozenset({"CAVALRY", "DOZER", "HERO", "INFANTRY", "MACHINE", "MONSTER", "SHIP"}),
    ): "Structures",
    (frozenset({"INFANTRY"}), frozenset({"CAVALRY", "PIKE"})): "Swordsmen",
    (frozenset({"WALK_ON_TOP_OF_WALL"}), frozenset()): "Walls",
    (
        frozenset(
            {
                "Drogoth",
                "ElvenFortressEagle",
                "GondorGwaihir",
                "GondorGwaihir_Summoned",
                "MordorFellBeast",
                "MordorWitchKingOnFellBeast",
                "SpellBookDragonStrikeDragon",
            }
        ),
        frozenset(),
    ): "Flyers",
    (frozenset({"HERO", "TROLL"}), frozenset()): "Hero and trolls",
}


def archetype_key(object_filter) -> ArchetypeKey:
    """The archetype lookup key for a filter: its `(included, excluded)` object/kindof name
    sets (descriptor and relations dropped). The empty pair for the unscoped "everything"."""
    signature = filter_signature(object_filter)
    if signature is None:
        return frozenset(), frozenset()
    return signature.inclusion, signature.exclusion


def _auto_label(key: ArchetypeKey) -> str:
    """A readable fallback label for an unlabeled archetype key (`({"HERO"}, {"CAVALRY"})` ->
    `"HERO-CAVALRY"`); the empty pair is "All"."""
    included, excluded = key
    base = "+".join(sorted(included)) if included else "All"
    return base + "".join(f"-{name}" for name in sorted(excluded))


def label_for_key(key: ArchetypeKey) -> str:
    """The archetype label of a `(included, excluded)` key - its registered name, else an
    auto-string. Used by the renderer to label a complement (an exclusion's spared set)."""
    return ARCHETYPES.get(key) or _auto_label(key)


def label_for(object_filter) -> str:
    """The archetype label of a filter - its registered name, else an auto-string. A bare
    unscoped multiplier (no filter) is the global "All", distinct from a relation-only filter
    like `ALL ALLIES` that reduces to the same empty key but carries its own label."""
    if object_filter is None:
        return "All"
    return label_for_key(archetype_key(object_filter))


def describe_filter(object_filter) -> str:
    """A filter reconstructed as a readable token string (`ANY ENEMIES +HERO -STRUCTURE`), for
    the discovery report so the descriptor/relation context behind an archetype key is visible."""
    signature = filter_signature(object_filter)
    if signature is None:
        return "(none)"
    parts: list[str] = []
    if signature.descriptor:
        parts.append(signature.descriptor)
    parts.extend(sorted(signature.relations))
    parts.extend(f"+{name}" for name in sorted(signature.inclusion))
    parts.extend(f"-{name}" for name in sorted(signature.exclusion))
    return " ".join(parts) if parts else "(empty)"


def _iter_damage_scalars(game):
    """Every `(weapon, DamageNugget, scaled_filter)` across the game's weapons. Limited to
    DamageNuggets - the in-scope nugget for the weapon summary."""
    for weapon in game.weapons.values():
        for nugget in safe(lambda w=weapon: w.Nuggets, []) or []:
            if not isinstance(nugget, DamageNugget):
                continue
            for scaled in safe(lambda n=nugget: n.DamageScalar, []) or []:
                yield weapon, nugget, scaled


def collect_archetypes(game) -> tuple[Counter, dict[ArchetypeKey, tuple[str, list[str]]]]:
    """Tally the distinct DamageScalar filter shapes across the game. Returns `(counts,
    examples)`: `counts` maps each archetype key to how many scalars use it; `examples` maps
    it to a sample reconstructed filter and up to five weapon names that use it."""
    counts: Counter = Counter()
    examples: dict[ArchetypeKey, tuple[str, list[str]]] = {}
    for weapon, _nugget, scaled in _iter_damage_scalars(game):
        key = archetype_key(scaled.ObjectFilter)
        counts[key] += 1
        sample, names = examples.setdefault(key, (describe_filter(scaled.ObjectFilter), []))
        if weapon.name not in names and len(names) < 5:
            names.append(weapon.name)
    return counts, examples


def discovery_report(game) -> str:
    """A frequency-sorted listing of the corpus's DamageScalar filter shapes, each with its
    archetype label (or an UNLABELED marker), a sample filter and example weapons - the input
    for hand-labeling `ARCHETYPES`."""
    counts, examples = collect_archetypes(game)
    lines: list[str] = []
    for key, count in counts.most_common():
        sample, names = examples[key]
        label = ARCHETYPES.get(key)
        status = f'"{label}"' if label is not None else f"UNLABELED (auto: {_auto_label(key)!r})"
        included, excluded = key
        lines.append(f"{count:5d}  {status}")
        lines.append(f"        shape : {sample}")
        lines.append(f"        include : {sorted(included)}  exclude : {sorted(excluded)}")
        lines.append(f"        e.g.  : {', '.join(names)}")
    return "\n".join(lines)


def _main(argv: list[str]) -> None:
    if not argv:
        print("usage: python -m sage_wiki.archetypes <source-folder>...")
        return
    game, _names = load_sources([("folder", path) for path in argv])
    print(discovery_report(game))


if __name__ == "__main__":
    import sys

    _main(sys.argv[1:])
