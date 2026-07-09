"""What an object *instance property* references, by property key - the object-side companion to
`scripts.ARG_SPECS`.

A placed object carries a dict of properties; most are scalars (health, enabled, scale), but a few
name another entity: the team that owns it, an upgrade it starts with. This registry types those so
the linter can flag a property pointing at something the map or game never defines.

Typed incrementally, the sage_ini schema-coverage way: a property whose target is uncertain is left
out rather than guessed at (a wrong scope is a false positive, an absent one merely a gap). Scopes
mirror `scripts.Scope`; only GAME and MAP entries are resolved.
"""

from dataclasses import dataclass

from sage_map.scripts import Scope


@dataclass(frozen=True)
class PropertySpec:
    """How an object property resolves: `target` is the `Game` table key for `GAME`, or the
    map-local `MapSymbols` table for `MAP`. `multi` marks a space-separated list of names, each
    resolved independently (the value carries one or more, with a trailing space)."""

    scope: Scope
    target: str
    multi: bool = False


# Object property key -> what its value must resolve against.
OBJECT_PROPERTY_SPECS: dict[str, PropertySpec] = {
    # The team that owns a placed object, written in the qualified `<owner>/<team>` form teams are
    # harvested under (the neutral owner is the bare `/team`).
    "originalOwner": PropertySpec(Scope.MAP, "teams"),
    # The upgrades a placed object starts already owning - a space-separated list of Upgrade names
    # (e.g. `Upgrade_StructureLevel1 Upgrade_StructureLevel2`).
    "objectUpgradesList": PropertySpec(Scope.GAME, "upgrades", multi=True),
    # deferred: objectInitialStance -> a stance enum (value validation, not yet done). Audio/name
    # properties (objectSoundAmbient, objectName) are not references to resolve here.
}
