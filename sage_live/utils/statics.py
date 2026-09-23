"""Static per-template facts from the ini, joined to a live observation by `template_name`.

An `Observation` names each object's `ThingTemplate` and nothing more; this module answers what
that template is. Chiefly its `KindOf`, which says where a player can build (`BASE_SITE_KINDS`) and
who has lost (`MP_COUNT_FOR_VICTORY`). Parent inheritance, `+`/`-` deltas and `#define` macros are
all resolved.

Imports `sage_ini`, so it is not re-exported from the package root; import it from here.
"""

from __future__ import annotations

import re
from collections.abc import Container, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from sage_ini import load_game
from sage_ini.model.game import Game
from sage_ini.model.state import (
    active_command_set_name,
    armor_scalar_bonus,
    modifier_entries,
    modifier_product,
    modifier_sum,
)
from sage_ini.model.types import eval_number
from sage_live.api.orders import CAST_LOCATION, CAST_OBJECT, CAST_PASSIVE, CAST_SELF
from sage_live.utils.heroes import ReviveSlot

__all__ = [
    "BASE_SITE_KINDS",
    "CASTLE_UNPACK",
    "CASTLE_UNPACK_EXPLICIT",
    "CAST_LOCATION",
    "CAST_OBJECT",
    "CAST_PASSIVE",
    "CAST_SELF",
    "CRUSHABLE_LEVEL",
    "ALTERNATE_FORMATION",
    "CRUSHER_LEVEL",
    "CRUSHER_RESISTED",
    "EFFECT_BUFF",
    "EFFECT_BUILD",
    "EFFECT_GRANT",
    "EFFECT_HEAL",
    "EFFECT_SELF_BUFF",
    "EFFECT_STRIKE",
    "EFFECT_SUMMON",
    "EFFECT_UNKNOWN",
    "FORMATION_MODIFIERS",
    "HORDE_TOGGLE_FORMATION",
    "LOGIC_FRAMES_PER_SECOND",
    "MAIN_FORMATION",
    "MP_COUNT_FOR_VICTORY",
    "NOT_AN_ABILITY",
    "PLOT_FAMILIES",
    "PURCHASE_SCIENCE",
    "SPECIAL_POWER",
    "SPELL_BOOK",
    "SUMMON_KINDS",
    "REBUILD_HOLE",
    "REVIVE",
    "SLAVED",
    "SPAWN_TEMPLATE",
    "UNIT_BUILD",
    "UNPACK_COMMANDS",
    "UPGRADE_COMMANDS",
    "ArmyMember",
    "ArmyPlan",
    "CastablePower",
    "CostLadder",
    "Formation",
    "PowerButton",
    "Statics",
    "UnpackButton",
    "UpgradeButton",
]

# The `CommandButton` command that recruits a hero. Every hero in the game is reached through
# one of these; see `sage_live.utils.heroes` for the index space they are addressed by.
REVIVE = "REVIVE"

# The `CommandButton` command that queues a unit. `Statics.recruits` reads the `Object` such a
# button names, which is how a producer is found for a template rather than named per faction.
UNIT_BUILD = "UNIT_BUILD"

# The `CommandButton` command that buys a spellbook power. Every entry on a faction's spell
# store carries it, including the empty padding slots - so it identifies the *kind* of button
# and says nothing about whether that button sells anything (see `PowerButton.purchasable`).
PURCHASE_SCIENCE = "PURCHASE_SCIENCE"

# The `CommandButton` command that **fires** a power already bought. The spell store and the
# spellbook are two different command sets on two different things - the store hangs off the
# `PlayerTemplate` and sells, the book hangs off the `SpellBookMp` object and casts.
SPELL_BOOK = "SPELL_BOOK"

# The `CommandButton` command a **unit's own** ability sits behind - a hero's, and equally the
# errand rider's summons. Same order shapes as `SPELL_BOOK` and a different command, because the
# caster is the object rather than the player's book.
SPECIAL_POWER = "SPECIAL_POWER"

# `Options` tokens that mark a `SPECIAL_POWER` button as not an ability to fire: `NONPRESSABLE` is
# a portrait showing a passive aura, `TOGGLE_IMAGE_ON_WEAPONSET` a mount, dismount or weapon swap.
NOT_AN_ABILITY = frozenset({"NONPRESSABLE", "TOGGLE_IMAGE_ON_WEAPONSET"})

# `CAST_*` (re-exported from `sage_live.api.orders`) say how a cast order must be addressed. They
# are read off the firing button's `NEED_TARGET_*` options.

# What a power does, read off the module that implements it on the spellbook object. Neither the
# `SpecialPower` block nor its `Enum` says this reliably (Edain reuses enum slots freely).
EFFECT_SUMMON = "summon"
EFFECT_STRIKE = "strike"
EFFECT_BUILD = "build"
EFFECT_BUFF = "buff"
EFFECT_HEAL = "heal"
EFFECT_GRANT = "grant"
EFFECT_UNKNOWN = "unknown"
# A buff on the caster only (`HeroAttributeModifier`). Aimed differently from an ally buff: fire it
# when the caster is in a fight, wherever that is.
EFFECT_SELF_BUFF = "self buff"

# The module field that names an `ObjectCreationList`, and the two that mark a power as a buff
# or a heal. A module carrying `AttributeModifier` changes units in place; one carrying
# `HealAffects` repairs them; one carrying an OCL puts something on the map, and *what* it puts
# there is what separates a summon from a bombardment - see `Statics.creates`.
MODULE_OCL = "OCL"
MODULE_MODIFIER = "AttributeModifier"
MODULE_HEAL = "HealAffects"
# The two shapes a **hero** ability uses that no spellbook power does, and without which the
# whole roster classifies as `EFFECT_GRANT` and is skipped. `HeroAttributeModifier` is a buff on
# the caster (`HeroModeSpecialAbilityUpdate`); `SpecialWeapon` is a weapon fired at whatever the
# button was pointed at (`WeaponFireSpecialAbilityUpdate`) - Gandalf's Wizard Blast, Faramir's
# Wound Arrow. See `Statics.hero_powers`.
MODULE_SELF_MODIFIER = "HeroAttributeModifier"
MODULE_WEAPON = "SpecialWeapon"

# `KindOf` flags that make a created template an army rather than an effect. A summon ends at
# one of these; a strike ends at `UNATTACKABLE` scenery that exists to carry a weapon.
SUMMON_KINDS = frozenset({"INFANTRY", "CAVALRY", "MONSTER", "HERO", "SIEGEENGINE"})

# The relationship token an object filter uses for "the other side". Its presence is the data
# saying outright that a power is aimed at the enemy - `NearestSecondaryObjectFilter = NONE
# +STRUCTURE ENEMIES` on Gondor's Arrow Volley.
FILTER_ENEMIES = "ENEMIES"

# The relationship tokens that mean "your side". The engine's filter vocabulary distinguishes
# your own objects from an ally's, and for aiming they are the same answer - both are somewhere
# the power should be pointed at rather than away from.
FILTER_ALLIES = "ALLIES"
FRIENDLY_TOKENS = frozenset({"SAME_PLAYER", FILTER_ALLIES})

# `Options` tokens saying whose side a button's target is on. For some abilities the button is the
# only place this is stated: Wizard Blast and Beregond's `TalkToMe` share a module shape but target
# enemies and allies respectively.
TARGET_SIDE = {
    "NEED_TARGET_ENEMY_OBJECT": FILTER_ENEMIES,
    "NEED_TARGET_ALLY_OBJECT": FILTER_ALLIES,
}

# An OCL chain longer than this is a cycle rather than a summon. Real ones are two or three
# hops - a power creates an "egg", the egg dies, and its `SlowDeathBehavior` creates the units -
# but the eagles genuinely loop (`OCL_SpawnEagles` recreates its own members), so the walk is
# bounded as well as visited-guarded.
_MAX_OCL_DEPTH = 6

# The two `CommandButton` commands that buy an upgrade. Both send the same order - what differs
# is where the finished upgrade lands, and that is declared by the `Upgrade` block's own `Type`
# rather than by the button, which is why `UpgradeButton.player_scope` reads the former.
UPGRADE_COMMANDS = frozenset({"OBJECT_UPGRADE", "PLAYER_UPGRADE"})

# The two `CommandButton` commands that build on a plot. `CASTLE_UNPACK` sends an argument-less
# `0x43D` and lets the target's `CastleBehavior` decide; `CASTLE_UNPACK_EXPLICIT_OBJECT` sends
# `0x43F` naming the button's `Object`. Read the target's buttons (`Statics.unpack_buttons`).
CASTLE_UNPACK = "CASTLE_UNPACK"
CASTLE_UNPACK_EXPLICIT = "CASTLE_UNPACK_EXPLICIT_OBJECT"
UNPACK_COMMANDS = frozenset({CASTLE_UNPACK, CASTLE_UNPACK_EXPLICIT})

# Edain's four buildable-plot families, keyed by the name the interface gives each; the German
# template names mislead (`Wirtschaft` is the settlement). A guide for reading a map only: which
# unpack order a plot takes comes from its live buttons (`Statics.unpack_buttons`).
PLOT_FAMILIES = {
    "settlement": ("WirtschaftPlotFlag_Real", "WirtschaftPlotFlag"),
    "outpost": ("ExpansionPlotFlag",),
    "castle": ("FestungPlotFlag_Real", "FestungPlotFlag"),
    "camp": ("LagerPlotFlag_Real", "LagerPlotFlag"),
}

# The two flags that mark somewhere a structure can be placed. Both, not either: `BASE_SITE`
# is the settlement/outpost spot and `BASE_FOUNDATION` the castle plot, and a faction may use
# one, the other, or both on the same map.
BASE_SITE_KINDS = frozenset({"BASE_FOUNDATION", "BASE_SITE"})

# What the engine's multiplayer defeat check counts. Structures and plots carry it; ordinary
# units generally do not, which is why a player with an army but no buildings is still losing.
MP_COUNT_FOR_VICTORY = "MP_COUNT_FOR_VICTORY"

# The `KindOf` on the stump a rebuildable structure (a creep lair) leaves when it dies. The hole
# rebuilds the lair after a delay and is never auto-targeted, so razing a lair for good means
# attacking the hole explicitly.
REBUILD_HOLE = "REBUILD_HOLE"

# The `CommandButton` command that switches a battalion between its two formations. The button only
# says the switch is offered; the formation itself is declared on the horde. RotWK comments many of
# these buttons out and mods restore them, so `formation_button` asks the merged tree.
HORDE_TOGGLE_FORMATION = "HORDE_TOGGLE_FORMATION"

# The `HordeContain` fields formations are written in. `AlternateFormation` names another object
# whose `HordeContain` the engine applies to the standing battalion; the two name each other, and
# `ThisFormationIsTheMainFormation` says which is the main one.
ALTERNATE_FORMATION = "AlternateFormation"
MAIN_FORMATION = "ThisFormationIsTheMainFormation"
FORMATION_MODIFIERS = "AttributeModifiers"

# The `SpawnBehavior` field naming what a structure garrisons itself with. A creep lair is
# nothing but this: `DunlandGoblinLair` spawns twelve wildmen and replaces each one that dies,
# so the defenders around it are not a force to be killed but a tap to be turned off.
SPAWN_TEMPLATE = "SpawnTemplateName"

# The module marking an object that belongs to a master rather than a player: a house's civilians,
# a battalion's standard, a lair's defenders. They look like units but take no orders. No
# recruitable template and no roster hero is slaved.
SLAVED = "SlavedUpdate"

# The module that marks a price down for owning several of something. Edain prices most of its
# economy through this rather than through the quoted `BuildCost`, so a bot that reads only the
# ini number is wrong by up to 30% on exactly the elite units and upgrades an economy is built to
# afford. See `CostLadder` for why the module is rarely on the building you own.
COST_MODIFIER = "CostModifierUpgrade"

# The module that replaces a template's whole palette once an upgrade is held. It is how Edain
# builds a structure's levels - `GondorBarracks` names `GondorBarracksCommandSetLevel2` and
# `...Level3` through two of these - so a walk that reads only the declared `CommandSet` sees
# the first rung of a ladder and nothing above it. `live_command_set` resolves which one is
# active; `reachable_recruits` reads them all at once.
COMMAND_SET_UPGRADE = "CommandSetUpgrade"

# SAGE logic runs at a fixed 30 frames a second, and `GameData` may cap it lower with
# `FramesPerSecondLimit`. This is the fallback for a tree that declares neither, which is the
# usual case - RotWK 2.01 + Edain leaves the field out entirely.
LOGIC_FRAMES_PER_SECOND = 30.0

# The crush fields: a mover crushes a stander when its `CrusherLevel` is strictly greater than the
# stander's `CrushableLevel`, unless the stander's body resists that level (`CrusherLevelResisted`,
# as a pike formation's body does).
CRUSHER_LEVEL = "CrusherLevel"
CRUSHABLE_LEVEL = "CrushableLevel"
CRUSHER_RESISTED = "CrusherLevelResisted"

# A parent chain longer than this is a cycle in the data, not a deep hierarchy.
_MAX_DEPTH = 32

# Identifier-shaped tokens inside a `#MULTIPLY( A B )` expression, so a macro name is found
# whatever the arithmetic around it looks like. See `crush_revenge_multiple`.
_IDENTIFIERS = re.compile(r"[A-Za-z_][A-Za-z_0-9]*")


class _FoldedUpgrades(set):
    """A held-upgrades set whose membership test folds case.

    `sage_ini.model.state` tests `TriggeredBy` names against this set with a plain `in`, and
    those names carry the ini's spelling (`Upgrade_MenFaction`) while a live observation is
    lowercased everywhere else in this module. Folding on lookup keeps one convention for
    callers without asking `state` to know about it.
    """

    def __init__(self, names: Iterable[str] = ()) -> None:
        super().__init__(str(n).lower() for n in names)

    def __contains__(self, name: object) -> bool:
        return super().__contains__(str(name).lower())


@dataclass(frozen=True)
class UpgradeButton:
    """One upgrade a producer's `CommandSet` offers, and what it costs.

    Upgrades come in two tiers. A `PLAYER`-scope faction tech bought at a structure only unlocks
    (through `NeededUpgrade`) the `OBJECT`-scope button on each battalion, which is where the effect
    lands; buying only the tech has no combat effect. `player_scope` says where "already have it"
    is read: `PlayerState.upgrades` or `GameObject.upgrades`.
    """

    command_slot: int
    button: str
    upgrade: str
    player_scope: bool
    cost: int = 0
    needed_upgrades: tuple[str, ...] = ()

    def enabled_for(self, upgrades: Container[str]) -> bool:
        """Whether this button's `NeededUpgrade` requirement is met by `upgrades`.

        `upgrades` must be lowercased, and must be the union of the player's completed
        upgrades and the target object's own - the two scopes are separate fields on a live
        observation and a button may be gated by either. A multi-entry `NeededUpgrade` is read
        as *any of*, the same reading `ReviveSlot.enabled_for` documents.
        """
        if not self.needed_upgrades:
            return True
        return any(u.lower() in upgrades for u in self.needed_upgrades)


@dataclass(frozen=True)
class PowerButton:
    """One spellbook power a faction's spell store sells, and what it takes to buy it.

    `cost` is in spellbook points and is the multiplayer price (`SciencePurchasePointCostMP`),
    which differs from the single-player one for nearly every power.

    `prerequisites` are alternative groups: whitespace means *and*, `OR` separates alternatives.

    `triggers` names a button the engine fires alongside the purchase. For passives that second
    order is the whole effect - the science alone does nothing - so a bot must send it too.
    None for most powers.
    """

    command_slot: int
    button: str
    science: str
    cost: int = 0
    prerequisites: tuple[tuple[str, ...], ...] = ()
    grantable: bool = True
    triggers: str | None = None

    def enabled_for(self, sciences: Container[str]) -> bool:
        """Whether some prerequisite group is fully held by `sciences`, which must be lowercased.

        A power with no prerequisites at all is open, and a power whose groups are all unmet is
        one the spell store would have shown greyed out.
        """
        if not self.prerequisites:
            return True
        return any(all(name.lower() in sciences for name in group) for group in self.prerequisites)

    @property
    def purchasable(self) -> bool:
        """Whether this slot sells anything at all.

        The store's padding slots (`SCIENCE_Empty`) are neither grantable nor priced.
        """
        return self.grantable and self.cost > 0


@dataclass(frozen=True)
class CastablePower:
    """One power on a faction's spellbook: how to fire it, what it does, and how often.

    The casting counterpart of `PowerButton`, joined to it by science (`sciences`).

    - `form` picks the order constructor, from the firing button's `Options`. The wrong one is
      silently discarded (see `sage_live.api.orders.cast_self`).
    - `effect` decides where to aim (see the `EFFECT_*` constants); `spawns` is what a summon or
      build puts on the map.
    - `reload_seconds` is the undiscounted recharge, so treating it as the cooldown is never early.
    """

    command_slot: int
    button: str
    power: str
    sciences: tuple[str, ...] = ()
    form: str = CAST_LOCATION
    effect: str = EFFECT_UNKNOWN
    radius: float = 0.0
    reload_seconds: float = 0.0
    spawns: tuple[str, ...] = ()
    affects: tuple[str, ...] = ()
    # How long the power reveals its cast point (`ViewObjectDuration`). The marker it drops is the
    # only way to confirm a buff fired; about half of the powers declare one.
    view_seconds: float = 0.0
    # The OBJECT-scoped upgrades this power permanently confers on what it touches, which is the
    # one thing a buff leaves behind that an observation can see. A target already carrying them
    # has had this power and would gain nothing from another - see `granted_upgrades` for why
    # only the permanent ones are here.
    grants: tuple[str, ...] = ()
    # For a hero ability, the `Upgrade_Level_N` upgrade that unpauses it - OBJECT-scoped, so it is
    # read from the hero's `GameObject.upgrades`. Empty for a spellbook power, gated by `sciences`.
    unlocked_by: str = ""
    # `StartAbilityRange`: how close the caster walks before firing, committing the hero to the
    # trip. Zero means no approach.
    ability_range: float = 0.0

    def unlocked_for(self, upgrades: Container[str]) -> bool:
        """Whether the caster has reached the level this ability opens at, matched lowercased.
        An ability with no unlock upgrade is always open."""
        return not self.unlocked_by or self.unlocked_by.lower() in upgrades

    @property
    def castable(self) -> bool:
        """Whether this is an order at all, rather than a power that fired when it was bought."""
        return self.form != CAST_PASSIVE

    @property
    def hostile(self) -> bool:
        """Whether the power is aimed at the enemy rather than at your own side.

        True only where the data says so - a strike, or a filter naming `ENEMIES`. A **summon is
        neither**, deliberately: it puts your units at a point you choose, so whether it lands on
        your army or on their base is a tactical decision and not a property of the spell.
        """
        return self.effect == EFFECT_STRIKE or FILTER_ENEMIES in self.affects

    def enabled_for(self, sciences: Container[str]) -> bool:
        """Whether the player holds the science this power needs, matched lowercased.

        A power with none named is open - the three view powers every book carries are like
        this - and any one of several is enough, since the field parses to alternative groups
        the same way `PowerButton.prerequisites` does.
        """
        if not self.sciences:
            return True
        return any(name.lower() in sciences for name in self.sciences)


@dataclass(frozen=True)
class UnpackButton:
    """One way a plot can be built on, and which of the two unpack orders sends it.

    A plot in your own base offers one per thing it can become, each naming its `template`; an
    unclaimed outpost, castle or camp offers one with no template. `explicit` picks the order,
    and the wrong one is silently discarded.
    """

    command_slot: int
    button: str
    command: str
    template: str | None
    needed_upgrades: tuple[str, ...] = ()

    @property
    def explicit(self) -> bool:
        """Whether this button sends `unpack(template)` rather than a bare `castle_unpack()`."""
        return self.command == CASTLE_UNPACK_EXPLICIT

    def enabled_for(self, upgrades: Container[str]) -> bool:
        """Whether this button's `NeededUpgrade` requirement is met by `upgrades`, read as
        *any of* - the same reading `UpgradeButton.enabled_for` documents."""
        if not self.needed_upgrades:
            return True
        return any(u.lower() in upgrades for u in self.needed_upgrades)


@dataclass(frozen=True)
class Formation:
    """The alternate formation a battalion can stand in, and what it buys.

    A battalion has at most two formations and one button that swaps them. The main one carries no
    bonus; the alternate carries a `ModifierList` that is the whole trade
    (`GondorFighterHordeBlock`: `ARMOR 17%`, `SPEED 70%`, shown as "+20% Armor, -30% Speed").

    The numbers combine as `sage_ini.model.state` combines them: `speed` and `damage` are
    multipliers (1.0 neutral), `armour` is a summed fraction fed into `1/(1-v)` (0.0 neutral).
    `armour_scoped` is armour that applies only to `armour_types` (the knights' wedge is `ARMOR 33%
    SLASH SPECIALIST`), kept apart from `armour` so it is neither overstated nor lost.
    """

    # The horde in its ordinary formation, and the child object the toggle swaps its contain
    # module for. Both spelled as the tree spells them.
    template: str
    alternate: str
    # The `HORDE_TOGGLE_FORMATION` button the owner's control bar offers, and the alternate's
    # `ModifierList`. No button means the switch is not allowed; no modifier list means it buys
    # nothing.
    button: str
    modifiers: str = ""
    # Summed `ARMOR` fractions (the `v` in `1/(1-v)`); may be negative.
    armour: float = 0.0
    armour_scoped: float = 0.0
    armour_types: tuple[str, ...] = ()
    # Multiplicative, 1.0 being unchanged.
    speed: float = 1.0
    damage: float = 1.0
    # Summed, as `UnitState.vision` applies it: `base * (1 + vision)`.
    vision: float = 0.0
    # Whether the formation holds its ground against a charge (`CRUSHED_DECELERATE`,
    # `RESIST_KNOCKBACK`). Not visible in the numbers above: the pike porcupine gives no armour at
    # all.
    braces: bool = False

    @property
    def tougher(self) -> bool:
        """Whether the alternate is the more survivable of the two; scoped armour counts."""
        return self.armour > 0.0 or self.armour_scoped > 0.0

    @property
    def slower(self) -> bool:
        return self.speed < 1.0

    @property
    def deadlier(self) -> bool:
        return self.damage > 1.0

    @property
    def worth_taking(self) -> bool:
        """Whether the alternate buys anything at all; one with a button and no modifiers only
        changes the ranks.
        """
        return bool(self.button) and (
            self.tougher or self.deadlier or self.braces or self.vision > 0.0
        )

    @property
    def defensive(self) -> bool:
        """Whether this formation is bought to survive rather than to kill - worth holding while a
        fight is held, and leaving when the battalion has somewhere to be.
        """
        return self.braces or (self.tougher and not self.deadlier)


@dataclass(frozen=True)
class CostLadder:
    """One `CostModifierUpgrade`: the discount for owning several of a thing.

    Edain prices much of its economy this way, so the ini's quoted cost is not what the engine
    charges. A shipped ladder has six rungs (0, -10, -15, -20, -25, -30 percent), indexed by how
    many `carrier` objects the player owns.

    `carrier` is the object the module sits on, which is often not the building itself: it may be a
    `BuildVariations` stand-in, or a hidden helper the building spawns (`GondorForgeDiscountPing`).

    A ladder discounts either `upgrades` (when it sets `UpgradeDiscount`) or `templates` (its
    `ObjectFilter`'s inclusion list), never both.
    """

    carrier: str
    percentages: tuple[float, ...]
    upgrades: frozenset[str] = frozenset()
    templates: frozenset[str] = frozenset()

    def rate(self, count: int) -> float:
        """The multiplier applied at `count` carriers (-0.3 at the top of a shipped ladder).

        Saturates at both ends: zero carriers is no discount, and past the last rung pays the same.
        """
        if count <= 0 or not self.percentages:
            return 0.0
        return self.percentages[min(count, len(self.percentages)) - 1]

    def covers_upgrade(self, upgrade: str) -> bool:
        return upgrade.lower() in self.upgrades

    def covers_template(self, template: str) -> bool:
        return template.lower() in self.templates


@dataclass(frozen=True)
class ArmyMember:
    """One unit a faction's skirmish-AI `ArmyDefinition` asks for, and how much of it.

    `shares` are `PercentageOfArmyPhase1..3`. The file does not normalise them (a faction's phase 1
    can sum well over 100 across sub-faction rosters), so normalise across whatever survives
    filtering.
    """

    unit: str
    shares: tuple[float, float, float]

    def share(self, phase: int) -> float:
        """This unit's target share in `phase` (0, 1 or 2), clamped to the three that exist."""
        return self.shares[min(max(phase, 0), 2)]


@dataclass(frozen=True)
class ArmyPlan:
    """A faction's whole `ArmyDefinition`: what the skirmish AI would build, and when.

    A pool and its weights, not a legality check: it lists sub-faction and AI-only units no player
    can recruit. Intersect with `Statics.recruits` of the buildings actually owned. What it is
    authoritative about is the mix over the three phases.
    """

    name: str
    side: str
    members: tuple[ArmyMember, ...]
    # `PhaseDuration_Rush` and `PhaseDuration_MidGame`, in seconds. The end game is what is left,
    # so the definition declares no third duration.
    rush_seconds: float
    midgame_seconds: float

    def phase(self, seconds: float) -> int:
        """Which build phase a match `seconds` old is in: 0 rush, 1 mid game, 2 end game."""
        if seconds < self.rush_seconds:
            return 0
        if seconds < self.rush_seconds + self.midgame_seconds:
            return 1
        return 2


def _fields(block: object) -> dict[str, object]:
    """A block's declared fields, or `{}` for an object without them."""
    found = getattr(block, "fields", None)
    return found if isinstance(found, dict) else {}


def _condition_free(block: object) -> bool:
    """Whether a `WeaponSet` or `ArmorSet` is the unconditional one (`Conditions = None`) - the unit
    as recruited, before anything is bought.
    """
    declared = str(getattr(block, "fields", {}).get("Conditions", "")).strip()
    return declared == "" or declared.upper() == "NONE"


def _number(block: object, field: str, fallback: float) -> float:
    """One numeric ini field off a raw block, tolerating `f` and `%` suffixes and comment tails.
    Missing or unreadable fields return `fallback`.
    """
    tokens = str(getattr(block, "fields", {}).get(field, "")).split()
    if not tokens:
        return fallback
    try:
        return float(tokens[0].rstrip("f%"))
    except ValueError:
        return fallback


class _Merged:
    """Several modules implementing one power, read as though they were one module.

    A hero splits an ability across two or three modules (see `Statics._ability_modules`). This
    presents the union of their raw fields and forwards anything else to the first source that has
    it, so the typed accessors (which expand macros) keep working.
    """

    def __init__(self, fields: dict[str, object], sources: tuple[object, ...] = ()) -> None:
        self.fields = fields
        self._sources = sources

    def __getattr__(self, name: str) -> object:
        for source in self._sources:
            found = getattr(source, name, None)
            if found is not None:
                return found
        raise AttributeError(name)


def _module_name(module: object) -> str:
    """A module's declared type - the `SlavedUpdate` of `Behavior = SlavedUpdate ModuleTag_Slave`
    - falling back to the Python class name.
    """
    declared = str(getattr(module, "name", "") or "").split()
    return declared[0] if declared else type(module).__name__


def _definition_name(reference: object) -> str:
    """The name of a definition a field points at, whether `sage_ini` resolved it to a block or left
    it a raw token.
    """
    tokens = str(getattr(reference, "name", reference) or "").split()
    return tokens[0] if tokens else ""


def _int_field(block: object | None, field: str) -> int:
    """One integer off a **typed** block, or 0 where missing; typed so a macro value
    (`GOOD_RANK_1_COST`) expands.
    """
    value = getattr(block, field, None)
    return int(value) if isinstance(value, int | float) else 0


def _float_field(block: object | None, field: str, fallback: float = 0.0) -> float:
    """One float off a block, typed first so a macro expands, raw as the fallback.

    Reading only the raw field turns a `#define`d value (`RadiusCursorRadius =
    SPELL_REBUILD_RADIUS_CURSOR`) into the fallback.
    """
    value = getattr(block, field, None)
    if isinstance(value, int | float):
        return float(value)
    return _number(block, field, fallback)


def _yes(block: object | None, field: str) -> bool:
    """One boolean off a typed block, defaulting to False for a block that omits it."""
    return bool(getattr(block, field, False))


def _science_groups(
    block: object | None, field: str = "PrerequisiteSciences"
) -> tuple[tuple[str, ...], ...]:
    """A science expression as alternative all-required groups, by name.

    `sage_ini` parses `A OR B C` into `[[A], [B, C]]`. A `Science` uses `PrerequisiteSciences` and a
    `SpecialPower` uses `RequiredSciences`; reading the wrong key silently returns no requirement.
    """
    groups = getattr(block, field, None) or ()
    return tuple(
        tuple(str(getattr(entry, "name", entry)) for entry in group) for group in groups if group
    )


def _cast_form(options: Iterable[str], reload_ms: int) -> str:
    """Which cast order a spellbook button sends, from its `Options` and its recharge.

    `NEED_TARGET_POS` is a location cast, any other `NEED_TARGET_*` an object cast. With no target,
    a recharge makes it a self cast and no recharge makes it passive (the power fired when bought).
    """
    tokens = {str(o).strip().upper() for o in options}
    if "NEED_TARGET_POS" in tokens:
        return CAST_LOCATION
    if any(t.startswith("NEED_TARGET_") for t in tokens):
        return CAST_OBJECT
    return CAST_SELF if reload_ms > 0 else CAST_PASSIVE


def _shares(entry: object) -> tuple[float, float, float]:
    """An `ArmyMemberDefinition`'s three phase percentages, missing ones read as zero."""
    return (
        _number(entry, "PercentageOfArmyPhase1", 0.0),
        _number(entry, "PercentageOfArmyPhase2", 0.0),
        _number(entry, "PercentageOfArmyPhase3", 0.0),
    )


class Statics:
    """Template name to the static ini facts about it, for one loaded build.

    Case-insensitive throughout, because ini identifiers are and a live observation spells a
    template however the engine registered it.
    """

    def __init__(self, game: Game) -> None:
        self.game = game
        objects = game.tables.get("objects", {})
        # Keyed lowercase once, so lookups are dict hits.
        self._objects = {str(name).lower(): obj for name, obj in objects.items()}
        self._sets = {str(n).lower(): s for n, s in game.tables.get("commandsets", {}).items()}
        self._buttons = {
            str(n).lower(): b for n, b in game.tables.get("commandbuttons", {}).items()
        }
        self._upgrades = {str(n).lower(): u for n, u in game.tables.get("upgrades", {}).items()}
        # What a weapon deals, and what an armour block is worth against it (see `effectiveness`).
        self._weapons = {str(n).lower(): w for n, w in game.tables.get("weapons", {}).items()}
        self._armours = {str(n).lower(): a for n, a in game.tables.get("armorsets", {}).items()}
        # `ModifierList` blocks: where a buff says what it does (see `granted_upgrades`).
        self._modifiers = {str(n).lower(): m for n, m in game.tables.get("modifiers", {}).items()}
        # `PlayerTemplate` blocks live in the `factions` table, keyed `FactionMen` and so on.
        self._factions = {str(n).lower(): f for n, f in game.tables.get("factions", {}).items()}
        self._sciences = {str(n).lower(): s for n, s in game.tables.get("sciences", {}).items()}
        self._powers = {str(n).lower(): p for n, p in game.tables.get("specialpowers", {}).items()}
        ocls = game.tables.get("objectcreationlists", {})
        self._ocls = {str(n).lower(): o for n, o in ocls.items()}
        armies = game.tables.get("armydefinitions", {})
        self._armies = {str(n).lower(): a for n, a in armies.items()}
        self._kinds: dict[str, frozenset[str]] = {}
        self._canonical: dict[str, str] | None = None
        self._members: frozenset[str] | None = None
        self._revives: dict[str, tuple[ReviveSlot, ...]] = {}
        self._upgrade_buttons: dict[tuple[str, frozenset[str]], tuple[UpgradeButton, ...]] = {}
        self._unpack_buttons: dict[tuple[str, frozenset[str]], tuple[UnpackButton, ...]] = {}
        self._recruits: dict[tuple[str, frozenset[str]], frozenset[str]] = {}
        self._spawns: dict[str, tuple[str, ...]] = {}
        self._damage: dict[str, frozenset[str]] = {}
        self._speed: dict[str, float] = {}
        self._multiple: dict[str, float] = {}
        self._armour: dict[str, dict[str, float]] = {}
        self._ladders: tuple[CostLadder, ...] | None = None

    @classmethod
    def from_root(cls, root: str | Path) -> Statics:
        """Load a game tree and index it.

        `root` must already be an ini tree; mount a live install's `.big` archives first with
        `sage_utils.gameroot.resolve_game_root`.
        """
        return cls(load_game(root).game)

    def known(self, template: str) -> bool:
        return template.lower() in self._objects

    def field(self, template: str, name: str) -> str | None:
        """One raw ini field, following the parent chain. None when nothing declares it."""
        current = self._objects.get(template.lower())
        for _ in range(_MAX_DEPTH):
            if current is None:
                return None
            value = current.fields.get(name)
            if value is not None:
                return str(value)
            parent = getattr(current, "parent_name", None)
            current = self._objects.get(str(parent).lower()) if parent else None
        return None

    def kind_of(self, template: str) -> frozenset[str]:
        """The template's resolved `KindOf` flags, inheritance and deltas applied.

        An unknown template answers the empty set: a live game may carry templates this tree lacks,
        and that is a reason to skip the object, not to fail.
        """
        key = template.lower()
        cached = self._kinds.get(key)
        if cached is None:
            cached = self._resolve_kinds(key)
            self._kinds[key] = cached
        return cached

    def _resolve_kinds(self, key: str) -> frozenset[str]:
        """Walk to the root of the parent chain, then apply each `KindOf` on the way down.

        A plain `KindOf` replaces the inherited set; `+FLAG`/`-FLAG` edit it. One block may state
        the field several times (the value is then a list), and each later statement edits the
        earlier.
        """
        chain = []
        current = self._objects.get(key)
        for _ in range(_MAX_DEPTH):
            if current is None:
                break
            chain.append(current)
            parent = getattr(current, "parent_name", None)
            current = self._objects.get(str(parent).lower()) if parent else None

        flags: set[str] = set()
        for obj in reversed(chain):
            declared = obj.fields.get("KindOf")
            if declared is None:
                continue
            statements = declared if isinstance(declared, (list, tuple)) else (declared,)
            for statement in statements:
                flags = self._apply_kinds(flags, self._kind_tokens(str(statement)))
        return frozenset(flags)

    @staticmethod
    def _apply_kinds(flags: set[str], tokens: list[str]) -> set[str]:
        """One `KindOf` declaration applied to the flags standing before it."""
        if not any(t.startswith(("+", "-")) for t in tokens):
            return {t.upper() for t in tokens}
        for token in tokens:
            if token.startswith("+"):
                flags.add(token[1:].upper())
            elif token.startswith("-"):
                flags.discard(token[1:].upper())
            else:
                flags.add(token.upper())
        return flags

    def _kind_tokens(self, declared: str) -> list[str]:
        """One `KindOf` declaration split into flags, with `#define`s expanded.

        Animals are declared as `KindOf = NATUREUNITS_KINDOF`, so without expansion they miss
        `INERT` and read as combatants. Macros may nest, and a delta sign carries onto every flag a
        macro brings.
        """
        tokens = declared.split()
        for _ in range(_MAX_DEPTH):
            if not any(self.game.has_macro(t.lstrip("+-")) for t in tokens):
                break
            widened: list[str] = []
            for token in tokens:
                sign = token[0] if token[:1] in ("+", "-") else ""
                name = token[len(sign) :]
                if not self.game.has_macro(name):
                    widened.append(token)
                    continue
                widened.extend(f"{sign}{part}" for part in str(self.game.get_macro(name)).split())
            tokens = widened
        return tokens

    def has_kind(self, template: str, *flags: str) -> bool:
        """Whether the template carries **any** of `flags`."""
        kinds = self.kind_of(template)
        return any(flag.upper() in kinds for flag in flags)

    def is_build_site(self, template: str) -> bool:
        """Whether a structure can be placed here - a castle plot or a settlement spot."""
        return bool(self.kind_of(template) & BASE_SITE_KINDS)

    def plot_family(self, template: str) -> str | None:
        """Which of `PLOT_FAMILIES` this plot belongs to, or None.

        For judging what kind of expansion a plot is before walking there; which order it takes is
        `unpack_buttons`' answer.
        """
        key = template.lower()
        for family, templates in PLOT_FAMILIES.items():
            if any(key == name.lower() for name in templates):
                return family
        return None

    def counts_for_victory(self, template: str) -> bool:
        """Whether losing this counts toward the engine's own multiplayer defeat check."""
        return MP_COUNT_FOR_VICTORY in self.kind_of(template)

    def is_rebuild_hole(self, template: str) -> bool:
        """Whether this is the stump a razed structure left, which will rebuild it. It is never
        auto-targeted (see `REBUILD_HOLE`).
        """
        return REBUILD_HOLE in self.kind_of(template)

    def is_slaved(self, template: str) -> bool:
        """Whether this template belongs to a master rather than a player (see `SLAVED`).

        Like `is_horde_member`, it marks something a player owns but cannot command. Read along the
        parent chain.
        """
        obj = self._objects.get(template.lower())
        for _ in range(_MAX_DEPTH):
            if obj is None:
                return False
            if any(SLAVED == _module_name(m) for m in getattr(obj, "modules", ())):
                return True
            parent = getattr(obj, "parent_name", None)
            obj = self._objects.get(str(parent).lower()) if parent else None
        return False

    def spawns(self, template: str) -> tuple[str, ...]:
        """The templates a structure garrisons itself with - its `SpawnBehavior`'s payload.

        A creep lair replaces every defender that dies, so the fight ends with the building, not the
        units. Many ordinary buildings spawn things too, so this is not a creep test on its own.
        Empty for most templates.
        """
        key = template.lower()
        cached = self._spawns.get(key)
        if cached is not None:
            return cached
        obj = self._objects.get(key)
        found: tuple[str, ...] = ()
        for _ in range(_MAX_DEPTH):
            if obj is None:
                break
            declared = next(
                (
                    getattr(m, "fields", {}).get(SPAWN_TEMPLATE)
                    for m in getattr(obj, "modules", ())
                    if getattr(m, "fields", {}).get(SPAWN_TEMPLATE)
                ),
                None,
            )
            if declared:
                found = tuple(str(declared).split())
                break
            parent = getattr(obj, "parent_name", None)
            obj = self._objects.get(str(parent).lower()) if parent else None
        self._spawns[key] = found
        return found

    def build_variations(self, template: str) -> tuple[str, ...]:
        """The templates the engine may actually place when asked to build `template`.

        `BuildVariations` are visual stand-ins picked at build time, so the ordered template never
        appears on the map under its own name.
        """
        declared = self.field(template, "BuildVariations")
        return tuple(declared.split()) if declared else ()

    def canonical(self, template: str) -> str:
        """The template that was *ordered* to produce `template` - the inverse of
        `build_variations`.
        """
        if self._canonical is None:
            mapping: dict[str, str] = {}
            for name, obj in self._objects.items():
                declared = obj.fields.get("BuildVariations")
                if declared:
                    for variation in str(declared).split():
                        mapping[variation.lower()] = name
            self._canonical = mapping
        key = template.lower()
        return self._canonical.get(key, template)

    def same_building(self, template: str) -> frozenset[str]:
        """`template` and every variation of it, lowercased - what "one of these" means by name. Use
        `KindOf` to count a broader category.
        """
        return frozenset({template.lower(), *(v.lower() for v in self.build_variations(template))})

    def descends_from(self, template: str, ancestor: str) -> bool:
        """Whether `template` is `ancestor` or a `ChildObject` of it, at any depth.

        Tiered buildings are children of the base one (`GondorFarm_Extern2` descends from
        `GondorFarm_Extern`). A name-prefix test gets this wrong in both directions.
        """
        wanted = ancestor.lower()
        key = template.lower()
        current = self._objects.get(key)
        for _ in range(_MAX_DEPTH):
            if key == wanted:
                return True
            if current is None:
                return False
            parent = getattr(current, "parent_name", None)
            if not parent:
                return False
            key = str(parent).lower()
            current = self._objects.get(key)
        return False

    def horde_payload(self, template: str) -> str | None:
        """The member template a horde is filled with, or None if this is not a horde.

        Read off the `HordeContain` module's `InitialPayload`, whose first token is the member
        template and whose second is the count (`GondorFighter GOOD_MEN_GIANT_HORDE_SIZE`).
        """
        obj = self._objects.get(template.lower())
        if obj is None:
            return None
        for module in getattr(obj, "modules", ()):
            declared = getattr(module, "fields", {}).get("InitialPayload")
            if declared:
                tokens = str(declared).split()
                if tokens:
                    return tokens[0]
        return None

    def horde_members(self) -> frozenset[str]:
        """Every template that exists only as the contents of a horde, lowercased.

        Orders address the horde container, not its members: an order to the members is recorded and
        ignored. Exclude this set when building a selection.
        """
        if self._members is None:
            members: set[str] = set()
            for name in self._objects:
                payload = self.horde_payload(name)
                if payload:
                    members.add(payload.lower())
            self._members = frozenset(members)
        return self._members

    def is_horde(self, template: str) -> bool:
        """Whether this template is a horde container - the thing an order should name."""
        return "HORDE" in self.kind_of(template)

    def is_horde_member(self, template: str) -> bool:
        """Whether this template only ever appears as the contents of a horde.

        A horde container is not a member of one, even where a template somehow appears in
        both roles - the container is always the correct thing to order.
        """
        return template.lower() in self.horde_members() and not self.is_horde(template)

    def _contain(self, template: str) -> object | None:
        """The `HordeContain` module governing this template, following the parent chain.

        Found by the fields it declares, so every formation field is read off the same module
        object.
        """
        obj = self._objects.get(template.lower())
        for _ in range(_MAX_DEPTH):
            if obj is None:
                return None
            for module in getattr(obj, "modules", ()) or ():
                fields = getattr(module, "fields", {}) or {}
                wanted = (ALTERNATE_FORMATION, MAIN_FORMATION, "InitialPayload")
                if any(f in fields for f in wanted):
                    return module
            parent = getattr(obj, "parent_name", None)
            obj = self._objects.get(str(parent).lower()) if parent else None
        return None

    def formation_button(self, template: str, upgrades: Iterable[str] = ()) -> str:
        """The formation-toggle button this template's control bar really offers, or `""`.

        The legitimacy check for a formation switch: a horde may declare an `AlternateFormation`
        whose button the merged tree never declares, and then a human sees no control. Read through
        `live_command_set`, since an upgrade can swap the palette.
        """
        command_set = self.live_command_set(template, upgrades)
        if not command_set:
            return ""
        for _slot, button in self.command_buttons(command_set):
            if self.button_command(button) == HORDE_TOGGLE_FORMATION:
                return button
        return ""

    def alternate_formation(self, template: str, upgrades: Iterable[str] = ()) -> Formation | None:
        """The other formation this battalion can stand in, or None when it has none.

        The two formations of a pair name each other; only the one that is not
        `ThisFormationIsTheMainFormation` carries the bonus. So a battalion already in its alternate
        formation answers None. Modifiers are combined by `sage_ini.model.state` (see `Formation`).
        """
        contain = self._contain(template)
        if contain is None:
            return None
        named = str(getattr(contain, "fields", {}).get(ALTERNATE_FORMATION, "")).strip()
        if not named:
            return None
        other = self._contain(named)
        if other is None or _yes(other, MAIN_FORMATION):
            return None
        return self._formation_effect(
            other, template, named, self.formation_button(template, upgrades)
        )

    def _formation_effect(
        self, contain: object, template: str, alternate: str, button: str
    ) -> Formation:
        """What one alternate formation's `ModifierList` is worth, as a `Formation`.

        The combination rules are `sage_ini.model.state`'s. An undeclared list reads as neutral.
        """
        name = str(getattr(contain, "fields", {}).get(FORMATION_MODIFIERS, "")).split()
        block = self._modifiers.get(name[0].lower()) if name else None
        if block is None:
            return Formation(template, alternate, button, name[0] if name else "")
        lists = [block]
        entries = modifier_entries(block)
        types = {
            damage
            for kind, _value, damage_types in entries
            if kind == "ARMOR"
            for damage in damage_types
        }
        # `armor_scalar_bonus` sums the entries that apply to one damage type, counting untyped
        # ones as applying to all - so asking it for a type no entry names returns exactly the
        # untyped total, and the scoped remainder is what the whole sum has over that.
        untyped = armor_scalar_bonus(lists, "")
        return Formation(
            template=template,
            alternate=alternate,
            button=button,
            modifiers=name[0],
            armour=untyped,
            # The best of the scoped bonuses rather than their sum: they are alternatives, not
            # cumulative, since an attack deals one damage type.
            armour_scoped=max(
                (armor_scalar_bonus(lists, damage) - untyped for damage in types), default=0.0
            ),
            armour_types=tuple(sorted(types)),
            speed=modifier_product(lists, "SPEED"),
            damage=modifier_product(lists, "DAMAGE_MULT"),
            vision=modifier_sum(lists, "VISION"),
            # The pike wall, by what it does rather than by the word "porcupine" in a template
            # name. `CRUSHED_DECELERATE` is the modifier that stops a charge; `RESIST_KNOCKBACK`
            # is the shield wall's version of the same idea, keeping the ranks standing through
            # what would otherwise scatter them.
            braces=any(
                kind in ("CRUSHED_DECELERATE", "RESIST_KNOCKBACK") for kind, _v, _t in entries
            ),
        )

    def command_set(self, template: str) -> str | None:
        """The template's `CommandSet` name, following the parent chain."""
        return self.field(template, "CommandSet")

    def command_buttons(self, command_set: str) -> tuple[tuple[int, str], ...]:
        """`(slot, button name)` for one `CommandSet`, in slot order.

        Slots are sparse and unordered in the file - a set may define 1-7 then jump to 12 -
        so they are read as the integer keys they are and sorted, never enumerated.
        """
        block = self._sets.get(command_set.lower())
        if block is None:
            return ()
        found = [
            (int(key.strip()), str(value).strip())
            for key, value in block.fields.items()
            if str(key).strip().isdigit()
        ]
        return tuple(sorted(found))

    def button_command(self, button: str) -> str:
        """A `CommandButton`'s `Command`, uppercased. Empty for a button this tree lacks."""
        block = self._buttons.get(button.lower())
        if block is None:
            return ""
        return str(_fields(block).get("Command", "")).strip().upper()

    def recruits(self, template: str, upgrades: Iterable[str] = ()) -> frozenset[str]:
        """The templates this one can build **right now** - its live `UNIT_BUILD` buttons.

        The legitimacy check for a recruit, and the way to find a producer without naming one per
        faction. Pass the union of the owner's and the object's upgrades: they decide which
        `NeededUpgrade` buttons are open and which `CommandSetUpgrade` palette is showing. The
        default (none) describes a freshly raised building.
        """
        held = frozenset(u.lower() for u in upgrades)
        key = (template.lower(), held)
        cached = self._recruits.get(key)
        if cached is None:
            name = self.live_command_set(template, held)
            found: set[str] = set()
            if name:
                for _, button in self.command_buttons(name):
                    if self.button_command(button) != UNIT_BUILD:
                        continue
                    block = self._buttons.get(button.lower())
                    if block is None:
                        continue
                    needed = str(_fields(block).get("NeededUpgrade", "")).split()
                    if needed and not any(u.lower() in held for u in needed):
                        continue
                    made = str(_fields(block).get("Object", "")).strip()
                    if made:
                        found.add(made.lower())
            cached = frozenset(found)
            self._recruits[key] = cached
        return cached

    def reachable_recruits(self, template: str) -> frozenset[str]:
        """Everything this template could **ever** build, across every palette it can reach.

        For planning, not for ordering: unions the declared `CommandSet` with every
        `CommandSetUpgrade` palette and ignores `NeededUpgrade`.
        """
        obj = self._objects.get(template.lower())
        sets = {self.command_set(template) or ""}
        current = obj
        for _ in range(_MAX_DEPTH):
            if current is None:
                break
            for module in getattr(current, "modules", ()):
                if _module_name(module) == COMMAND_SET_UPGRADE:
                    named = str(getattr(module, "fields", {}).get("CommandSet", "")).strip()
                    if named:
                        sets.add(named)
            parent = getattr(current, "parent_name", None)
            current = self._objects.get(str(parent).lower()) if parent else None
        found: set[str] = set()
        for name in sets:
            if not name:
                continue
            for _, button in self.command_buttons(name):
                if self.button_command(button) != UNIT_BUILD:
                    continue
                made = self.button_object(button)
                if made:
                    found.add(made.lower())
        return frozenset(found)

    def button_object(self, button: str) -> str:
        """A `CommandButton`'s `Object` - what it creates. Empty for a button that names none."""
        block = self._buttons.get(button.lower())
        if block is None:
            return ""
        return str(_fields(block).get("Object", "")).strip()

    def live_command_set(self, template: str, upgrades: Iterable[str] = ()) -> str | None:
        """The `CommandSet` the control bar would really show, given the owner's upgrades.

        Not the `CommandSet` field: a `CommandSetUpgrade` replaces the palette while its
        `TriggeredBy` upgrades are held, and plots rely on this heavily (a settlement plot carries
        26 of them, one per faction and tech level). `upgrades` is the owner's and the object's,
        case-insensitive; the last-active-module rule is `sage_ini.model.state`'s.
        """
        obj = self._objects.get(template.lower())
        if obj is None:
            return None
        return active_command_set_name(obj, _FoldedUpgrades(upgrades))

    def unpack_buttons(
        self, template: str, upgrades: Iterable[str] = ()
    ) -> tuple[UnpackButton, ...]:
        """Every way this plot can be built on, in slot order - empty for anything but a plot.

        The button decides which unpack order to send (see `UNPACK_COMMANDS`). Pass the owner's and
        the object's upgrades: without them the palette is an unowned plot's, often empty. An
        explicit button that names no `Object` is dropped, since there would be nothing to send.
        """
        held = frozenset(u.lower() for u in upgrades)
        key = (template.lower(), held)
        cached = self._unpack_buttons.get(key)
        if cached is not None:
            return cached
        name = self.live_command_set(template, held)
        found: list[UnpackButton] = []
        if name:
            for command_slot, button in self.command_buttons(name):
                command = self.button_command(button)
                if command not in UNPACK_COMMANDS:
                    continue
                made = self.button_object(button)
                if command == CASTLE_UNPACK_EXPLICIT and not made:
                    continue
                block = self._buttons.get(button.lower())
                fields = block.fields if block is not None else {}
                found.append(
                    UnpackButton(
                        command_slot=command_slot,
                        button=button,
                        command=command,
                        template=made or None,
                        needed_upgrades=tuple(str(fields.get("NeededUpgrade", "")).split()),
                    )
                )
        result = tuple(found)
        self._unpack_buttons[key] = result
        return result

    def button_upgrade(self, button: str) -> str:
        """A `CommandButton`'s `Upgrade` - what it buys. Empty for a button that buys none."""
        block = self._buttons.get(button.lower())
        if block is None:
            return ""
        return str(_fields(block).get("Upgrade", "")).strip()

    def upgrade_cost(self, upgrade: str) -> int:
        """An upgrade's `BuildCost`, or 0 for one this tree does not define.

        Read through the typed model rather than the raw field, because the ini spells these
        as macros - `GONDOR_PERSONAL_HEAVY_ARMOR_BUILDCOST`, not `300` - and only the typed
        accessor expands them. `build_cost` is the same question for an object.
        """
        block = self._upgrades.get(upgrade.lower())
        if block is None:
            return 0
        cost = getattr(block, "BuildCost", None)
        return int(cost) if isinstance(cost, int | float) else 0

    def build_cost(self, template: str) -> int:
        """What an object costs to build or recruit, or 0 for one this tree does not define.

        Read through the typed accessor so a macro (`GONDOR_SOLDIER_BUILDCOST`) expands, following
        the parent chain. This is the quoted price: a `CostModifierUpgrade` may discount it by up to
        30% (see `cost_ladders`), so it is a safe ceiling, not the exact charge.
        """
        current = self._objects.get(template.lower())
        for _ in range(_MAX_DEPTH):
            if current is None:
                return 0
            cost = getattr(current, "BuildCost", None)
            if isinstance(cost, int | float) and cost:
                return int(cost)
            parent = getattr(current, "parent_name", None)
            current = self._objects.get(str(parent).lower()) if parent else None
        return 0

    def command_point_cost(self, template: str) -> int:
        """What recruiting this object charges against the command-point ceiling, or 0.

        The engine silently discards a recruit that would exceed the cap, just as it does an
        unaffordable one. Ask it of the horde, not the soldier: the `...Horde` object carries the
        battalion's whole charge. Typed (macros expand) and inherited, like `build_cost`.
        """
        current = self._objects.get(template.lower())
        for _ in range(_MAX_DEPTH):
            if current is None:
                return 0
            cost = getattr(current, "CommandPoints", None)
            if isinstance(cost, int | float) and cost:
                return int(cost)
            parent = getattr(current, "parent_name", None)
            current = self._objects.get(str(parent).lower()) if parent else None
        return 0

    def cost_ladders(self) -> tuple[CostLadder, ...]:
        """Every `CostModifierUpgrade` in the tree, as ladders indexed by their carrier's count.

        A whole-tree scan, because the carrier is often not the thing you own (see `CostLadder`);
        match by carrier. Stub ladders of a single 0% rung are kept - `rate` returns 0 for them.
        Cached.
        """
        if self._ladders is not None:
            return self._ladders
        found: list[CostLadder] = []
        for name, obj in self._objects.items():
            for module in getattr(obj, "modules", ()):
                if _module_name(module) != COST_MODIFIER:
                    continue
                percentages = tuple(
                    float(p) for p in (getattr(module, "Percentage", None) or ()) if p is not None
                )
                if not percentages:
                    continue
                upgrades = frozenset(
                    _definition_name(u).lower()
                    for u in (getattr(module, "ApplyToTheseUpgrades", None) or ())
                )
                filtered = getattr(module, "ObjectFilter", None)
                templates = frozenset(
                    _definition_name(t).lower()
                    for t in (getattr(filtered, "inclusion", None) or ())
                )
                # **Attributed to the building, not to the block the module was written in.**
                # The ladder is declared on `GondorWohnhaus01` and inherited by the `02` and `03`
                # `ChildObject`s, so the carrier as written names one of the three things the
                # engine might have placed. Folding it to the canonical name lets a caller count
                # with `same_building`, which is the whole variation family and therefore the
                # count the engine is indexing by.
                found.append(CostLadder(self.canonical(name), percentages, upgrades, templates))
        self._ladders = tuple(found)
        return self._ladders

    def ladders_for_template(self, template: str) -> tuple[CostLadder, ...]:
        """The ladders that mark down building or recruiting `template`."""
        return tuple(lad for lad in self.cost_ladders() if lad.covers_template(template))

    def ladders_for_upgrade(self, upgrade: str) -> tuple[CostLadder, ...]:
        """The ladders that mark down buying `upgrade`."""
        return tuple(lad for lad in self.cost_ladders() if lad.covers_upgrade(upgrade))

    def _nested(self, template: str, attribute: str) -> list[object]:
        """The nearest declaration of a nested block family (`WeaponSet`, `ArmorSet`) along the
        parent chain.
        """
        current = self._objects.get(template.lower())
        for _ in range(_MAX_DEPTH):
            if current is None:
                return []
            found = getattr(current, attribute, None)
            if isinstance(found, list) and found:
                return list(found)
            if found is not None and not isinstance(found, list):
                return [found]
            parent = getattr(current, "parent_name", None)
            current = self._objects.get(str(parent).lower()) if parent else None
        return []

    def fighting_template(self, template: str) -> str:
        """The object that actually carries the weapon and the armour.

        A battalion's container has no `WeaponSet` or `ArmorSet`; its members fight. So combat
        questions are asked of the payload. Anything that is not a horde answers for itself.
        """
        return self.horde_payload(template) or template

    def damage_types(self, template: str) -> frozenset[str]:
        """The `DamageType`s this template's units deal, uppercased.

        The attacking half of the engine's counter system (pair with `armour`). Follows `PRIMARY
        <name>` to the weapon and a projectile to its warhead. Only the unconditional `WeaponSet` is
        read where there is one.
        """
        key = template.lower()
        cached = self._damage.get(key)
        if cached is not None:
            return cached
        found: set[str] = set()
        for weapon in self._primary_weapons(self.fighting_template(template)):
            found.update(self._weapon_damage(weapon, depth=0))
        cached = frozenset(found)
        self._damage[key] = cached
        return cached

    def _primary_weapons(self, template: str) -> list[str]:
        """The `PRIMARY` weapon named by this template's unconditional `WeaponSet`."""
        sets = self._nested(template, "WeaponSet")
        plain = [s for s in sets if _condition_free(s)] or sets
        names: list[str] = []
        for block in plain:
            declared = getattr(block, "fields", {}).get("Weapon", ())
            entries = declared if isinstance(declared, list) else [declared]
            for entry in entries:
                tokens = str(entry).split()
                if len(tokens) >= 2 and tokens[0].upper() == "PRIMARY":
                    names.append(tokens[1])
        return names

    def _weapon_damage(self, weapon: str, depth: int) -> set[str]:
        """The damage types one weapon deals, following a projectile to its warhead."""
        if depth > 4:
            return set()
        block = self._weapons.get(weapon.lower())
        if block is None:
            return set()
        found: set[str] = set()
        for nugget in getattr(block, "Nuggets", ()) or ():
            fields = getattr(nugget, "fields", {})
            declared = str(fields.get("DamageType", "")).strip()
            if declared:
                found.add(declared.upper())
            warhead = str(fields.get("WarheadTemplateName", "")).strip()
            if warhead:
                found |= self._weapon_damage(warhead, depth + 1)
        return found

    def speed(self, template: str) -> float:
        """How fast this template moves, or 0.0 where nothing readable declares it.

        Read from the `LocomotorSet` block's `Speed` (not from the `Locomotor` it names), for the
        `SET_NORMAL` condition only. Foot is 55 and cavalry 120 on RotWK + Edain.
        """
        key = template.lower()
        cached = self._speed.get(key)
        if cached is not None:
            return cached
        found = 0.0
        for block in self._nested(self.fighting_template(template), "LocomotorSet"):
            fields = getattr(block, "fields", {})
            if str(fields.get("Condition", "")).upper() != "SET_NORMAL":
                continue
            try:
                found = max(found, float(eval_number(self.game, fields.get("Speed", 0))))
            except (TypeError, ValueError):
                continue
        self._speed[key] = found
        return found

    def crush_revenge_multiple(self, template: str) -> float:
        """How many times its own damage this template is paid for being ridden down.

        The multiplier, not the product, so it compares across factions: Edain writes the revenge as
        `#MULTIPLY( BASE_DAMAGE_* CRUSH_REVENGE_MULT_* )`. Non-pike battalions read 2.0 and pikes
        2.0 to 6.0, so `CRUSH_REVENGE_CHARGED` separates them. 0.0 where nothing declares one.
        """
        key = template.lower()
        cached = self._multiple.get(key)
        if cached is not None:
            return cached
        named = self.field(self.fighting_template(template), "CrushRevengeWeapon")
        block = self._weapons.get(named.lower()) if named else None
        found = 0.0
        for nugget in (getattr(block, "Nuggets", ()) or ()) if block is not None else ():
            declared = getattr(nugget, "fields", {}).get("Damage")
            for token in _IDENTIFIERS.findall(str(declared or "")):
                if "CRUSH_REVENGE_MULT" not in token or not self.game.has_macro(token):
                    continue
                try:
                    found = max(found, float(eval_number(self.game, token)))
                except (TypeError, ValueError):
                    continue
        self._multiple[key] = found
        return found

    def armour(self, template: str) -> dict[str, float]:
        """What each damage type is worth against this template, as a multiplier.

        The defending half of the counter system: `EdainCavalryArmor` takes 170% from `SPECIALIST`
        and 30% from `SLASH`. `DEFAULT` (the fallback for unlisted types) is kept in the mapping;
        see `effectiveness`.
        """
        key = template.lower()
        cached = self._armour.get(key)
        if cached is not None:
            return cached
        table: dict[str, float] = {}
        sets = self._nested(self.fighting_template(template), "ArmorSet")
        plain = [s for s in sets if _condition_free(s)] or sets
        for block in plain[:1]:
            named = str(getattr(block, "fields", {}).get("Armor", "")).strip()
            armour = self._armours.get(named.lower())
            if armour is None:
                continue
            declared = armour.fields.get("Armor", ())
            for line in declared if isinstance(declared, list) else [declared]:
                tokens = str(line).split()
                if len(tokens) >= 2:
                    try:
                        table[tokens[0].upper()] = float(tokens[1].rstrip("%")) / 100.0
                    except ValueError:
                        continue
        self._armour[key] = table
        return table

    def effectiveness(self, attacker: str, defender: str) -> float:
        """How well `attacker` trades into `defender` - 1.0 for an even matchup.

        Joins `damage_types` and `armour`, so the answer comes from the balance data rather than a
        hand-written table (Gondor pikes into Mordor cavalry: 1.7; into Mordor orcs: 0.65). 1.0 when
        either side is unreadable.
        """
        types = self.damage_types(attacker)
        table = self.armour(defender)
        if not types or not table:
            return 1.0
        fallback = table.get("DEFAULT", 1.0)
        return sum(table.get(t, fallback) for t in types) / len(types)

    def _level(self, template: str, name: str) -> int | None:
        """One crush level off `template`'s own chain, or None where nothing declares it.

        None (not mentioned) differs from 0 (crushes nothing): only None may be answered by the
        other half of a battalion.
        """
        declared = self.field(template, name)
        if declared is None:
            return None
        token = declared.split()[0].rstrip(";") if declared.split() else ""
        try:
            return int(token)
        except ValueError:
            return None

    def crusher_level(self, template: str) -> int:
        """How much this template flattens by moving over it - 0 for anything that does not.

        Asked of the container that moves and takes orders; the payload is the fallback.
        """
        own = self._level(template, CRUSHER_LEVEL)
        if own is not None:
            return own
        member = self.fighting_template(template)
        return 0 if member == template else (self._level(member, CRUSHER_LEVEL) or 0)

    def crushable_level(self, template: str) -> int:
        """What it takes to flatten this template: the higher of the horde's and its members'.

        Erring high only costs a charge that should have been an attack.
        """
        member = self.fighting_template(template)
        levels = [self._level(template, CRUSHABLE_LEVEL)]
        if member != template:
            levels.append(self._level(member, CRUSHABLE_LEVEL))
        return max((level for level in levels if level is not None), default=0)

    def crush_resisted(self, template: str) -> int:
        """The crush level this template's body shrugs off, 0 for none.

        A body module on the member (a braced pike formation's `PorcupineFormationBodyModule`), so
        both halves are read and the larger taken. Not a pike test: only about half of `PIKE`
        battalions declare one, because bracing is a formation. Check the `PIKE` flag too.
        """
        best = 0
        seen = {template.lower()}
        queue = [template]
        member = self.fighting_template(template)
        if member.lower() not in seen:
            queue.append(member)
        for name in queue:
            obj = self._objects.get(name.lower())
            for _ in range(_MAX_DEPTH):
                if obj is None:
                    break
                for module in getattr(obj, "modules", ()):
                    declared = _fields(module).get(CRUSHER_RESISTED)
                    tokens = str(declared).split() if declared is not None else []
                    if tokens:
                        try:
                            best = max(best, int(tokens[0].rstrip(";")))
                        except ValueError:
                            pass
                parent = getattr(obj, "parent_name", None)
                obj = self._objects.get(str(parent).lower()) if parent else None
        return best

    def crushes(self, attacker: str, defender: str) -> bool:
        """Whether `attacker` riding over `defender` would flatten it, by the engine's rule:
        `CrusherLevel` strictly greater than `CrushableLevel`, unless the body resists.
        """
        level = self.crusher_level(attacker)
        if level <= 0:
            return False
        return level > self.crushable_level(defender) and level > self.crush_resisted(defender)

    def upgrade_is_player_scope(self, upgrade: str) -> bool:
        """Whether the finished upgrade lands on the player rather than on one object.

        The `Upgrade` block's own `Type`, which is the engine's answer. The button's `Command`
        agrees in this tree, but the block is the declaration and the button is the offer.
        """
        block = self._upgrades.get(upgrade.lower())
        if block is None:
            return False
        return str(getattr(block, "Type", "")).upper().endswith("PLAYER")

    def upgrade_buttons(
        self, template: str, upgrades: Iterable[str] = ()
    ) -> tuple[UpgradeButton, ...]:
        """Every upgrade this template offers **as it currently stands**, in slot order.

        The legitimacy check for a research order. Pass the owner's and the object's upgrades: a
        building's levels are a chain of `CommandSetUpgrade` palettes, and each level's upgrade is
        only offered on the palette before it. Empty for most templates.
        """
        held = frozenset(u.lower() for u in upgrades)
        key = (template.lower(), held)
        cached = self._upgrade_buttons.get(key)
        if cached is not None:
            return cached
        name = self.live_command_set(template, held)
        found: list[UpgradeButton] = []
        if name:
            for command_slot, button in self.command_buttons(name):
                if self.button_command(button) not in UPGRADE_COMMANDS:
                    continue
                upgrade = self.button_upgrade(button)
                if not upgrade:
                    continue
                block = self._buttons.get(button.lower())
                fields = block.fields if block is not None else {}
                found.append(
                    UpgradeButton(
                        command_slot=command_slot,
                        button=button,
                        upgrade=upgrade,
                        player_scope=self.upgrade_is_player_scope(upgrade),
                        cost=self.upgrade_cost(upgrade),
                        needed_upgrades=tuple(str(fields.get("NeededUpgrade", "")).split()),
                    )
                )
        result = tuple(found)
        self._upgrade_buttons[key] = result
        return result

    def revive_slots(self, template: str) -> tuple[ReviveSlot, ...]:
        """The producer's `Command = REVIVE` buttons, in slot order - its hero slots.

        Heroes bind to these slots by position, so a building carries every slot up to the last hero
        it recruits. See `sage_live.utils.heroes` for the index space.
        """
        key = template.lower()
        cached = self._revives.get(key)
        if cached is not None:
            return cached
        name = self.command_set(template)
        slots: list[ReviveSlot] = []
        if name:
            for command_slot, button in self.command_buttons(name):
                if self.button_command(button) != REVIVE:
                    continue
                block = self._buttons.get(button.lower())
                fields = block.fields if block is not None else {}
                needed = str(fields.get("NeededUpgrade", "")).split()
                options = str(fields.get("Options", "")).upper().split()
                slots.append(
                    ReviveSlot(
                        position=len(slots),
                        command_slot=command_slot,
                        button=button,
                        needed_upgrades=tuple(needed),
                        hide_while_disabled="HIDE_WHILE_DISABLED" in options,
                    )
                )
        result = tuple(slots)
        self._revives[key] = result
        return result

    def revive_slot_for(self, template: str, roster_index: int) -> ReviveSlot | None:
        """The producer's slot serving `roster_index`, or None if it carries no such slot."""
        for slot in self.revive_slots(template):
            if slot.roster_index == roster_index:
                return slot
        return None

    def faction_template(self, faction: str) -> object | None:
        """One faction's `PlayerTemplate` block, or None where the name resolves to no single one.

        `faction` matches the block name (`FactionMen`) or its `Side` (`Men`, what a live
        observation reports). Where several share a Side, the playable one wins over e.g.
        `FactionTutorial`.
        """
        key = faction.lower()
        block = self._factions.get(key) or self._factions.get(f"faction{key}")
        if block is not None:
            return block
        playable = [
            f
            for f in self._factions.values()
            if str(f.fields.get("Side", "")).lower() == key
            and str(f.fields.get("PlayableSide", "")).lower() in ("yes", "true")
        ]
        return playable[0] if len(playable) == 1 else None

    def hero_roster(self, faction: str) -> tuple[str, ...]:
        """A faction's `BuildableHeroesMP`, which is the revive list's starting order.

        **Map-scoped overrides are not applied.** A `map.ini` may redefine `BuildableHeroesMP`
        for the map being played, and several Edain maps do; this reads the base tree only.
        """
        block = self.faction_template(faction)
        if block is None:
            return ()
        return tuple(str(_fields(block).get("BuildableHeroesMP", "")).split())

    def intrinsic_sciences(self, faction: str) -> tuple[str, ...]:
        """The sciences a faction starts a **multiplayer** match holding (`IntrinsicSciencesMP`,
        which differs from the campaign field). Once the match is live, `PlayerState.sciences` is
        the fuller answer.
        """
        block = self.faction_template(faction)
        if block is None:
            return ()
        return tuple(str(_fields(block).get("IntrinsicSciencesMP", "")).split())

    def creates(
        self, ocl: str, depth: int = 0, seen: frozenset[str] = frozenset()
    ) -> tuple[str, ...]:
        """Every template an `ObjectCreationList` finally puts on the map, eggs followed through.

        Spellbook powers usually create an egg whose death creates the real units, so one hop is not
        enough. The end of the chain is what separates a summon (battalions, heroes) from a
        bombardment (an `UNATTACKABLE` object carrying a weapon). Some chains loop
        (`OCL_SpawnEagles`), so the walk is visited-guarded and depth-bounded.
        """
        block = self._ocls.get(ocl.lower())
        if block is None or depth > _MAX_OCL_DEPTH or ocl.lower() in seen:
            return ()
        seen = seen | {ocl.lower()}
        found: list[str] = []
        for entry in getattr(block, "CreateObject", None) or ():
            names = str(getattr(entry, "fields", {}).get("ObjectNames", "")).split()
            for template in names:
                found.append(template)
                for onward in self._ocls_fired_by(template):
                    found.extend(self.creates(onward, depth + 1, seen))
        return tuple(dict.fromkeys(found))

    def _ocls_fired_by(self, template: str) -> tuple[str, ...]:
        """The `ObjectCreationList`s a template's own modules name - how an egg hatches.

        Any field whose name mentions `OCL` counts; only tokens naming a real list are kept, which
        drops phase words like `FINAL`.
        """
        found: list[str] = []
        current = self._objects.get(template.lower())
        for _ in range(_MAX_DEPTH):
            if current is None:
                break
            for module in getattr(current, "modules", ()) or ():
                for key, value in (getattr(module, "fields", {}) or {}).items():
                    if MODULE_OCL.lower() not in str(key).lower():
                        continue
                    found.extend(t for t in str(value).split() if t.lower() in self._ocls)
            parent = getattr(current, "parent_name", None)
            current = self._objects.get(str(parent).lower()) if parent else None
        return tuple(dict.fromkeys(found))

    def spell_book_object(self, faction: str) -> str:
        """The faction's `SpellBookMp` template - the object a cast from the book is cast *by*.

        Needed to fire anything: a cast whose source is 0 is discarded (see `Session.cast`). Each
        seat owns exactly one, at the world origin.
        """
        block = self.faction_template(faction)
        if block is None:
            return ""
        return str(_fields(block).get("SpellBookMp", "")).strip()

    def spell_book(self, faction: str) -> tuple[CastablePower, ...]:
        """Every power a faction's spellbook can fire, in slot order, joined to the module that
        implements each.

        A separate walk from `spell_store`: the book's command set differs from the store's (it also
        holds view powers nobody buys), and it disambiguates sciences that several sub-faction
        powers share. Powers whose module cannot be found come back as `EFFECT_UNKNOWN` rather than
        dropped.
        """
        block = self.faction_template(faction)
        if block is None:
            return ()
        book = str(_fields(block).get("SpellBookMp", "")).strip()
        command_set = self.command_set(book) or ""
        if not command_set:
            return ()
        modules = self._spell_modules(book)
        found: list[CastablePower] = []
        for slot, button in self.command_buttons(command_set):
            entry = self._buttons.get(button.lower())
            if entry is None or self.button_command(button) != SPELL_BOOK:
                continue
            power = str(entry.fields.get("SpecialPower", "")).strip()
            if not power:
                continue
            definition = self._powers.get(power.lower())
            options = str(entry.fields.get("Options", "")).split()
            reload_ms = _int_field(definition, "ReloadTime")
            module = modules.get(power.lower())
            effect, spawns, affects, module_radius = self._classify(module)
            found.append(
                CastablePower(
                    command_slot=slot,
                    button=button,
                    power=power,
                    sciences=tuple(
                        name
                        for group in _science_groups(definition, "RequiredSciences")
                        for name in group
                    ),
                    form=_cast_form(options, reload_ms),
                    effect=effect,
                    radius=_float_field(definition, "RadiusCursorRadius") or module_radius,
                    reload_seconds=reload_ms / 1000.0,
                    spawns=spawns,
                    affects=affects,
                    view_seconds=_float_field(definition, "ViewObjectDuration") / 1000.0,
                    grants=self.granted_upgrades(spawns, module),
                )
            )
        return tuple(found)

    def _spell_modules(self, book: str) -> dict[str, object]:
        """The spellbook object's modules, keyed by the `SpecialPower` each implements.

        Walks the parent chain: a faction's book is a `ChildObject` that overrides only the command
        set.
        """
        table: dict[str, object] = {}
        current = self._objects.get(book.lower())
        for _ in range(_MAX_DEPTH):
            if current is None:
                break
            for module in getattr(current, "modules", ()) or ():
                named = str((getattr(module, "fields", {}) or {}).get("SpecialPowerTemplate", ""))
                if named.strip():
                    table.setdefault(named.strip().lower(), module)
            parent = getattr(current, "parent_name", None)
            current = self._objects.get(str(parent).lower()) if parent else None
        return table

    def _ability_modules(self, template: str) -> dict[str, _Merged]:
        """One object's special-power modules, **merged** per power rather than first-won.

        A spellbook implements a power in one module; a hero spreads each ability over two or three,
        each saying a different part:

        | module | what it says |
        |---|---|
        | `UnpauseSpecialPowerUpgrade` | the level it opens at |
        | `SpecialPowerModule` | that it starts paused, sometimes the modifier |
        | `WeaponFireSpecialAbilityUpdate` | the weapon, and the range the caster closes to |
        | `HeroModeSpecialAbilityUpdate` | the modifier it puts on the caster |
        | `OCLSpecialPower` | what it summons |

        The fields are near-disjoint, so merging is safe (`StartsPaused`, the one collision, is not
        read). Walks the parent chain like `_spell_modules`.
        """
        table: dict[str, dict[str, object]] = {}
        sources: dict[str, list[object]] = {}
        current = self._objects.get(template.lower())
        for _ in range(_MAX_DEPTH):
            if current is None:
                break
            for module in getattr(current, "modules", ()) or ():
                fields = getattr(module, "fields", {}) or {}
                named = str(fields.get("SpecialPowerTemplate", "")).strip()
                if not named:
                    continue
                key = named.lower()
                merged = table.setdefault(key, {})
                sources.setdefault(key, []).append(module)
                for field, value in fields.items():
                    # The child's own modules are walked first, so whatever it declared stands
                    # and the parent only fills gaps - the same override the engine applies.
                    merged.setdefault(field, value)
            parent = getattr(current, "parent_name", None)
            current = self._objects.get(str(parent).lower()) if parent else None
        return {
            power: _Merged(fields, tuple(sources.get(power, ()))) for power, fields in table.items()
        }

    def hero_powers(self, template: str) -> tuple[CastablePower, ...]:
        """Every ability a unit can fire from its own command set, in slot order.

        The unit counterpart of `spell_book`, with three differences:

        - The buttons are `SPECIAL_POWER`, cast by the unit rather than the player's book.
        - An ability is gated by the hero's level (`unlocked_by`), not by a science.
        - The modules are merged (see `_ability_modules`).

        `NOT_AN_ABILITY` buttons (passive portraits, mount and weapon swaps) are dropped. An ability
        whose modules say nothing recognisable comes back as `EFFECT_GRANT`, which differs from
        `EFFECT_UNKNOWN` (a chain was followed and named no side).
        """
        command_set = self.command_set(template) or ""
        if not command_set:
            return ()
        modules = self._ability_modules(template)
        found: list[CastablePower] = []
        for slot, button in self.command_buttons(command_set):
            entry = self._buttons.get(button.lower())
            if entry is None or self.button_command(button) != SPECIAL_POWER:
                continue
            power = str(entry.fields.get("SpecialPower", "")).strip()
            if not power:
                continue
            options = str(entry.fields.get("Options", "")).split()
            tokens = {token.strip().upper() for token in options}
            if NOT_AN_ABILITY & tokens:
                continue
            definition = self._powers.get(power.lower())
            reload_ms = _int_field(definition, "ReloadTime")
            module = modules.get(power.lower())
            effect, spawns, affects, module_radius = self._classify(module)
            side = {TARGET_SIDE[t] for t in tokens if t in TARGET_SIDE}
            # A weapon aimed at a friend is not a strike, and the module cannot tell (see
            # `TARGET_SIDE`). What such abilities do is not in any field read here, so they are
            # reported unknown and a caller declines to fire them.
            if effect == EFFECT_STRIKE and side == {FILTER_ALLIES}:
                effect = EFFECT_UNKNOWN
            found.append(
                CastablePower(
                    command_slot=slot,
                    button=button,
                    power=power,
                    sciences=tuple(
                        name
                        for group in _science_groups(definition, "RequiredSciences")
                        for name in group
                    ),
                    form=_cast_form(options, reload_ms),
                    effect=effect,
                    radius=_float_field(definition, "RadiusCursorRadius") or module_radius,
                    reload_seconds=reload_ms / 1000.0,
                    spawns=spawns,
                    affects=(*affects, *sorted(side)),
                    view_seconds=_float_field(definition, "ViewObjectDuration") / 1000.0,
                    grants=self.granted_upgrades(spawns, module),
                    unlocked_by=_definition_name(
                        (getattr(module, "fields", {}) or {}).get("TriggeredBy", "")
                    ),
                    ability_range=_float_field(module, "StartAbilityRange"),
                )
            )
        return tuple(found)

    def _classify(
        self, module: object | None
    ) -> tuple[str, tuple[str, ...], tuple[str, ...], float]:
        """What a power does, from the module implementing it: `(effect, spawns, affects, radius)`.

        Each shape is recognised by the field that carries its meaning, not by the module's class
        name, so a mod's own module classes still classify. The last two shapes (a caster buff, a
        weapon) come from heroes; for them the module passed in is a merge (see `_ability_modules`).
        """
        fields = getattr(module, "fields", {}) or {}
        if not fields:
            return EFFECT_UNKNOWN, (), (), 0.0

        if fields.get(MODULE_HEAL):
            affects = tuple(str(fields[MODULE_HEAL]).split())
            return EFFECT_HEAL, (), affects, _float_field(module, "HealRadius")

        # **Before the ordinary modifier, because a hero ability can declare both** and the
        # narrower reading is the true one: `HeroModeSpecialAbilityUpdate` puts its modifier on
        # the caster and nowhere else, so aiming it at the densest part of the army - which is
        # what `EFFECT_BUFF` means to a caller - would be aiming a self buff at somebody else.
        if fields.get(MODULE_SELF_MODIFIER):
            return EFFECT_SELF_BUFF, (), (), 0.0

        if fields.get(MODULE_MODIFIER):
            affects = tuple(str(fields.get("AttributeModifierAffects", "")).split())
            expanded = tuple(self._expand_filter(affects))
            return EFFECT_BUFF, (), expanded, _float_field(module, "AttributeModifierRange")

        ocl = str(fields.get(MODULE_OCL, "")).split()
        if ocl:
            spawns = self.creates(ocl[-1])
            affects = tuple(
                self._expand_filter(str(fields.get("NearestSecondaryObjectFilter", "")).split())
            )
            army = [t for t in spawns if self.kind_of(t) & SUMMON_KINDS]
            if FILTER_ENEMIES in affects and not army:
                return EFFECT_STRIKE, spawns, affects, 0.0
            if army:
                return EFFECT_SUMMON, tuple(army), affects, 0.0
            built = [t for t in spawns if "STRUCTURE" in self.kind_of(t)]
            if built:
                return EFFECT_BUILD, tuple(built), affects, 0.0

            # An egg may deliver its units through `SpawnBehavior` rather than another OCL
            # (Beregond's summon is a short-lived marker with six spawn modules), which `creates`
            # does not follow. Checked last, only for what the branches above left unclaimed:
            # buildings spawn things too, and asked earlier this would turn build powers into
            # summons.
            hatched = tuple(dict.fromkeys(t for made in spawns for t in self.spawns(made)))
            army = [t for t in hatched if self.kind_of(t) & SUMMON_KINDS]
            if army:
                return EFFECT_SUMMON, tuple(army), affects, 0.0
            # What it puts down is neither a unit nor a building, which fits a bombardment and a
            # friendly effect equally well. The filters on the created objects say whose side it is
            # on, and the whole filter is kept because it may also name the exact target (a signal
            # fire) the power must be aimed at.
            chain = self._chain_filter(spawns)
            side = next((t for t in sorted(chain & FRIENDLY_TOKENS)), "")
            if not side and FILTER_ENEMIES in chain:
                return EFFECT_STRIKE, spawns, (*affects, *sorted(chain)), 0.0
            if side:
                return EFFECT_BUFF, spawns, (*affects, *sorted(chain)), 0.0
            # Nothing anywhere in the chain names a side. Reported as unknown rather than
            # guessed: a policy can decline to fire a power it cannot aim, and a wrong guess
            # here spends a recharge measured in minutes on helping the wrong army.
            return EFFECT_UNKNOWN, spawns, affects, 0.0

        # A weapon fired at whatever the button was pointed at (Wizard Blast, Wound Arrow): read as
        # a strike. Weapons aimed at friends are handled above through the button's target side.
        if fields.get(MODULE_WEAPON):
            return EFFECT_STRIKE, (), (), 0.0

        # No OCL, no modifier, no heal, no weapon: it changes the player rather than the map. A
        # granted upgrade (`PlayerUpgradeSpecialPower`) and a production bonus both land here.
        return EFFECT_GRANT, (), (), 0.0

    def _chain_filter(self, templates: Iterable[str]) -> frozenset[str]:
        """Every object-filter token carried by anything a power creates.

        Read from every filter field, since the field name varies (`ObjectFilter`,
        `AttributeModifierAffects`, ...). The relationship word says whose side the power is on; the
        `+Template` entries say where it must be pointed, since a power that attaches to one
        building is refused anywhere else.
        """
        found: set[str] = set()
        for template in templates:
            current = self._objects.get(template.lower())
            for _ in range(_MAX_DEPTH):
                if current is None:
                    break
                for module in getattr(current, "modules", ()) or ():
                    for key, value in (getattr(module, "fields", {}) or {}).items():
                        lowered = str(key).lower()
                        if "filter" not in lowered and "affects" not in lowered:
                            continue
                        found.update(self._expand_filter(str(value).split()))
                parent = getattr(current, "parent_name", None)
                current = self._objects.get(str(parent).lower()) if parent else None
        return frozenset(found)

    def granted_upgrades(
        self, templates: Iterable[str], module: object | None = None
    ) -> tuple[str, ...]:
        """The permanent object-scoped upgrades anything this power creates confers.

        A buff is otherwise invisible after the fact, but a granted upgrade stays in the target's
        `GameObject.upgrades`, so "has this target had it" becomes a set test. The chain is walked
        through eggs, weapons and modifiers, offering every field token to the weapon and modifier
        indexes. Only `Duration = 0` modifiers count: a timed one wears off, and recasting it is the
        point.
        """
        modifiers: set[str] = set()
        weapons: set[str] = set()

        def read(fields: Mapping[str, object] | None) -> None:
            for value in (fields or {}).values():
                for token in str(value).split():
                    lowered = token.lower()
                    if lowered in self._modifiers:
                        modifiers.add(lowered)
                    elif lowered in self._weapons:
                        weapons.add(lowered)

        if module is not None:
            read(getattr(module, "fields", {}))
        for template in templates:
            current = self._objects.get(str(template).lower())
            for _ in range(_MAX_DEPTH):
                if current is None:
                    break
                for behaviour in getattr(current, "modules", ()) or ():
                    read(getattr(behaviour, "fields", {}))
                parent = getattr(current, "parent_name", None)
                current = self._objects.get(str(parent).lower()) if parent else None
        # A worklist rather than a loop over the set, because reading a nugget can name another
        # weapon - a projectile's `WarheadTemplateName` is where the effect usually is, and the
        # modifier can sit one hop further along than the weapon the module named.
        seen: set[str] = set()
        while weapons - seen:
            weapon = (weapons - seen).pop()
            seen.add(weapon)
            block = self._weapons.get(weapon)
            for nugget in (getattr(block, "Nuggets", ()) or ()) if block is not None else ():
                read(getattr(nugget, "fields", {}))

        found: set[str] = set()
        for name in modifiers:
            block = self._modifiers.get(name)
            fields = getattr(block, "fields", {}) or {}
            if str(fields.get("Duration", "0")).split()[:1] not in ([], ["0"]):
                continue
            # `Upgrade` is an `UpgradeWithDelay`, so a delay may follow the name.
            granted = str(fields.get("Upgrade", "")).split()[:1]
            if granted:
                found.add(granted[0])
        return tuple(sorted(found))

    def _expand_filter(self, tokens: Iterable[str]) -> list[str]:
        """An object filter's tokens with any `#define` expanded - `HORN_BUFF_FILTER` is one.

        Reading the raw token would lose the relationship word that says who a power is aimed
        at, which is the whole reason the filter is read at all.
        """
        out: list[str] = []
        for token in tokens:
            if self.game.has_macro(token):
                out.extend(str(self.game.get_macro(token)).split())
            else:
                out.append(token)
        return out

    def spell_store(self, faction: str) -> tuple[PowerButton, ...]:
        """Every power a faction's spellbook sells, in slot order - its
        `PurchaseScienceCommandSetMP`, the skirmish store.

        Padding slots are dropped (see `PowerButton.purchasable`). Edain sub-faction stores, swapped
        in by script mid-match, are not visible here: this is the faction's default store.
        """
        block = self.faction_template(faction)
        if block is None:
            return ()
        store = str(_fields(block).get("PurchaseScienceCommandSetMP", "")).strip()
        if not store:
            return ()
        found: list[PowerButton] = []
        for slot, button in self.command_buttons(store):
            if self.button_command(button) != PURCHASE_SCIENCE:
                continue
            entry = self._buttons.get(button.lower())
            if entry is None:
                continue
            science = str(entry.fields.get("Science", "")).strip()
            if not science:
                continue
            definition = self._sciences.get(science.lower())
            found.append(
                PowerButton(
                    command_slot=slot,
                    button=button,
                    science=science,
                    cost=_int_field(definition, "SciencePurchasePointCostMP"),
                    prerequisites=_science_groups(definition),
                    grantable=_yes(definition, "IsGrantable"),
                    triggers=self._triggered_power(button),
                )
            )
        return tuple(found)

    def _triggered_power(self, button: str) -> str | None:
        """The `SpecialPower` a purchase button's `CommandTrigger` fires, if it has one.

        Two hops: the purchase button names another button, which carries the power. That button is
        on no palette a player can reach, so it is not held to the command-set test.
        """
        entry = self._buttons.get(button.lower())
        trigger = str(_fields(entry).get("CommandTrigger", "")).strip()
        if not trigger:
            return None
        triggered = self._buttons.get(trigger.lower())
        if triggered is None:
            return None
        power = str(_fields(triggered).get("SpecialPower", "")).strip()
        return power or None

    def frames_per_second(self) -> float:
        """The logic frame rate, so a frame count can be read as a match age.

        `GameData.FramesPerSecondLimit` when the tree declares it, and the engine's fixed 30
        when it does not - which is the usual case, RotWK 2.01 + Edain among them.
        """
        for block in self.game.tables.get("gamedatas", {}).values():
            declared = block.fields.get("FramesPerSecondLimit")
            if declared:
                try:
                    return float(str(declared).split()[0])
                except ValueError:
                    break
        return LOGIC_FRAMES_PER_SECOND

    def army_plan(self, side: str) -> ArmyPlan | None:
        """The skirmish AI's `ArmyDefinition` for a `Side`, or None where the tree has none.

        `side` is the token in `PlayerState.faction` (`Men`), matched against the definition's
        `Side` field as the engine does. None is normal: not every build defines an army for every
        side.
        """
        wanted = side.lower()
        block = next(
            (b for b in self._armies.values() if str(b.fields.get("Side", "")).lower() == wanted),
            None,
        )
        if block is None:
            return None
        members = []
        for entry in block.ArmyMemberDefinition:
            unit = str(entry.fields.get("Unit", "")).strip()
            if not unit:
                continue
            members.append(ArmyMember(unit=unit, shares=_shares(entry)))
        return ArmyPlan(
            name=str(block.name),
            side=str(_fields(block).get("Side", side)),
            members=tuple(members),
            rush_seconds=_number(block, "PhaseDuration_Rush", 300.0),
            midgame_seconds=_number(block, "PhaseDuration_MidGame", 400.0),
        )

    def check_revive_slots(self, template: str, roster: Sequence[str]) -> tuple[str, ...]:
        """Whether this producer's slot block can be read against `roster` at all.

        An enabled slot pointing past the roster means the positional rule does not line up, so
        treat the producer as unknown (unless running with `godsight`). Only slots enabled with no
        upgrade are checked: the permanently gated filler slots only hold positions. Button names
        are not checked, because generic names like `Command_GenericReviveSlot1` sit at different
        positions in different sets.
        """
        problems: list[str] = []
        for slot in self.revive_slots(template):
            if not slot.enabled_for(frozenset()):
                continue
            if not 0 <= slot.roster_index < len(roster):
                problems.append(
                    f"{slot.button} sits at position {slot.position}, which serves roster "
                    f"index {slot.roster_index} - outside a roster of {len(roster)}"
                )
        return tuple(problems)

    def templates_with(self, *flags: str) -> frozenset[str]:
        """Every known template carrying any of `flags`, for surveying a build rather than
        asking about one object at a time."""
        wanted: Iterable[str] = [f.upper() for f in flags]
        return frozenset(
            name for name in self._objects if any(f in self.kind_of(name) for f in wanted)
        )
