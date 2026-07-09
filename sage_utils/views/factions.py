"""Faction and production-graph views: the playable factions, which faction a building
belongs to, hero recruitment (the index-based REVIVE mapping), and the who-builds-whom
index behind UNIT_BUILD navigation."""

from sage_ini.model.state import command_set_names
from sage_utils.views.base import safe, upgrade_names
from sage_utils.views.buttons import command_set_buttons
from sage_utils.views.text import display_name

# Non-hero entries that appear in the buildable-hero lists: the Create-A-Hero
# customizer and the ring-hero slot placeholder, neither a real fielded hero.
_HERO_PLACEHOLDERS = frozenset({"CreateAHero", "RingHeroDummy"})


def playable_faction_objects(game) -> list:
    """The playable `PlayerTemplate`s (a faction with `PlayableSide = Yes`), in faction-table
    order - the raw objects, for callers that walk the model themselves."""
    return [f for f in game.factions.values() if safe(lambda f=f: f.PlayableSide)]


def playable_factions(game) -> list[dict]:
    """Playable factions (a `PlayerTemplate` with `PlayableSide = Yes`) in faction-table
    order, for the Faction Info panel. Each entry carries:

    - `name` / `display` - the raw template name and its localized DisplayName.
    - `heroes` - buildable heroes (`BuildableHeroesMP` then `BuildableRingHeroesMP`),
      de-duplicated, with the `CreateAHero`/`RingHeroDummy` placeholders dropped.
    - `spellbook` - the faction-specific `SpellBookMp`, else the shared `SpellBook`, or None.
    """
    factions = []
    for faction in playable_faction_objects(game):
        heroes: list[str] = []
        for field in ("BuildableHeroesMP", "BuildableRingHeroesMP"):
            for hero in upgrade_names(faction._fields.get(field)):
                if hero not in _HERO_PLACEHOLDERS and hero not in heroes:
                    heroes.append(hero)
        raw = faction._fields.get("SpellBookMp") or faction._fields.get("SpellBook")
        spellbook = None
        if raw is not None:
            spellbook = str(raw[-1] if isinstance(raw, list) else raw).split()[0]
        factions.append(
            {
                "name": faction.name,
                "display": display_name(game, faction) or faction.name,
                "heroes": heroes,
                "spellbook": spellbook,
            }
        )
    return factions


def faction_for_side(game, side):
    """The playable `PlayerTemplate` whose `Side` is `side`, or None. A faction's `Side` ties
    its structures, foundations and start flags back to it (the same token a `CastleBehavior`'s
    `CastleToUnpackForFaction` and a building's `Side` field use)."""
    if side is None:
        return None
    for faction in game.factions.values():
        if not safe(lambda f=faction: f.PlayableSide):
            continue
        other = faction._fields.get("Side")
        if other is not None and str(other[-1] if isinstance(other, list) else other) == str(side):
            return faction
    return None


def building_faction(game, obj):
    """The playable faction a building belongs to - matched on its `Side` field - or None."""
    raw = obj._fields.get("Side")
    side = str(raw[-1] if isinstance(raw, list) else raw) if raw else None
    return faction_for_side(game, side)


def revive_order(faction) -> list[str]:
    """A faction's heroes in REVIVE-slot order - its ring heroes then its regular buildable
    heroes, raw and in declaration order. The `CreateAHero`/`RingHeroDummy` placeholders are
    kept so each entry's index lines up with a command set's revive slots."""
    order: list[str] = []
    for field in ("BuildableRingHeroesMP", "BuildableHeroesMP"):
        order.extend(upgrade_names(faction._fields.get(field)))
    return order


def recruited_hero_names(game, obj) -> list[str]:
    """The hero object names a building recruits. Its REVIVE buttons are enumerated in slot order
    and mapped by position to the faction's `revive_order`; every REVIVE button advances the
    index, but a hero is only recruited when its button lacks the `NEED_UPGRADE` option (the rest
    are locked behind a tech). Placeholders are dropped; de-duplicated across the building's
    command sets, in first-recruited order."""
    faction = building_faction(game, obj)
    if faction is None:
        return []
    order = revive_order(faction)
    if not order:
        return []
    recruited: list[str] = []
    for set_name in command_set_names(obj):
        command_set = game.commandsets.get(set_name)
        if command_set is None:
            continue
        index = 0
        for _slot, _button_name, button in command_set_buttons(game, command_set):
            if getattr(safe(lambda b=button: b.Command), "name", None) != "REVIVE":
                continue
            hero = order[index] if index < len(order) else None
            index += 1
            if hero is None or hero in _HERO_PLACEHOLDERS or hero in recruited:
                continue
            options = safe(lambda b=button: b.Options, []) or []
            if any(getattr(o, "name", str(o)) == "NEED_UPGRADE" for o in options):
                continue
            recruited.append(hero)
    return recruited


def _unit_build_targets(game, command_set) -> list[str]:
    """The object names the UNIT_BUILD buttons of `command_set` build, in slot order,
    de-duplicated. A lean read for the builder index; unloaded buttons are skipped."""
    buttons = game.commandbuttons
    targets: list[str] = []
    for slot, raw in command_set.fields.items():
        if not slot.isdigit():
            continue
        button_name = raw[-1] if isinstance(raw, list) else raw
        button = buttons.get(button_name)
        if button is None:
            continue
        if getattr(safe(lambda b=button: b.Command), "name", None) != "UNIT_BUILD":
            continue
        obj_name = getattr(safe(lambda b=button: b.Object), "name", None)
        if obj_name and obj_name not in targets:
            targets.append(obj_name)
    return targets


def builder_index(game) -> dict[str, list[str]]:
    """Map each buildable object's name to the objects that build it (the inverse of
    UNIT_BUILD navigation), in object-table order. An object builds another when one of
    its command sets has a UNIT_BUILD button naming it. Cached on the game by `builders_of`."""
    index: dict[str, list[str]] = {}
    commandsets = game.commandsets
    # Command sets are shared across many objects, so resolve each one's targets once.
    targets_cache: dict[str, list[str]] = {}

    def targets(set_name: str) -> list[str]:
        if set_name not in targets_cache:
            command_set = commandsets.get(set_name)
            targets_cache[set_name] = (
                _unit_build_targets(game, command_set) if command_set is not None else []
            )
        return targets_cache[set_name]

    for builder in game.objects.values():
        for set_name in command_set_names(builder):
            for built_name in targets(set_name):
                builders = index.setdefault(built_name, [])
                if builder.name not in builders:
                    builders.append(builder.name)
    return index


def builders_of(game, name: str) -> list[str]:
    """The objects that build `name`, from the `builder_index` cached on the game (a
    fresh Game per load, so it never goes stale)."""
    index = getattr(game, "_builder_index", None)
    if index is None:
        index = builder_index(game)
        game._builder_index = index
    return index.get(name, [])
