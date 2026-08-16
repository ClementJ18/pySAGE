"""Static per-template facts, joined to a live observation by `template_name`.

An `Observation` is deliberately small: it names each object's `ThingTemplate` and stops
there, because everything else about that template is already on disk. This is the join. It
turns a template name into the ini facts a policy needs and the engine does not re-send every
frame - starting with `KindOf`, which is how the game itself classifies objects.

`KindOf` answers two questions no live field does:

- **Where can I build?** A build plot carries `BASE_FOUNDATION` or `BASE_SITE`. Nothing in the
  live object identifies a plot otherwise: a plot has a `Body` (an `ImmortalBody` of 15,000),
  so "no body" does not find it, and its template name follows no reliable convention across
  factions or mods.
- **Who has lost?** `MP_COUNT_FOR_VICTORY` is the flag the engine's own multiplayer defeat
  check counts. A player owning nothing that carries it is beaten. That is a far better
  test than "owns no objects", which calls a player dead while their walls are still standing.

Like `resolve`, this imports `sage_ini` and is therefore **not** re-exported from the package
root - import it from here. The package root stays install-free.

**Inheritance is resolved, not ignored.** A `ChildObject` does not restate its parent's
`KindOf`, so reading the field directly reports nothing for a large share of real templates -
`GondorBuildingFoundation_Independant`, a plot, is one of them. `kind_of` walks the parent
chain. It also honours SAGE's delta form (`KindOf = +SUMMONED`), which adds to and subtracts
from the inherited set rather than replacing it; 472 definitions in RotWK+Edain use it, none
of them for the two plot flags, but a rule that is only right for today's data is not a rule.

**And `#define`s are expanded.** A `KindOf` may be written as a macro - `KindOf =
NATUREUNITS_KINDOF` - and reading the raw field then yields one token that is not a flag at
all, so the template answers "carries nothing" to every question. 136 objects in RotWK+Edain
are written that way and two of the macros matter a great deal here: `NATUREUNITS_KINDOF` is
`INERT NO_BASE_CAPTURE ...`, which is how a live match tells a rabbit from a raider, and
`WILD_HOLE_KINDOF` is `REBUILD_HOLE ...`, which is the whole of what a razed lair leaves
behind.
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

# `Options` tokens that mark a `SPECIAL_POWER` button as something other than an ability to fire.
#
# **The spellbook had an equivalent problem and solved it a way heroes cannot borrow.** There, a
# UI button is one the spell store never sold; a hero has no store, so the button's own options
# are what is left - and they are enough, because both cases declare themselves. `NONPRESSABLE`
# is a portrait showing a passive aura and not a button at all (Beregond carries two of them),
# and `TOGGLE_IMAGE_ON_WEAPONSET` is a mount, a dismount or a weapon swap - a real decision, and
# not one that can be made by a stage looking for something to cast: firing Gandalf's would put
# him back on foot.
NOT_AN_ABILITY = frozenset({"NONPRESSABLE", "TOGGLE_IMAGE_ON_WEAPONSET"})

# How a cast order must be addressed, read off the firing button's `Options`. The engine picks
# the order type to match the `NEED_TARGET_*` bits and the corpus confirms the pairing on every
# recorded cast, so this is the button's decision rather than a guess about the power.
#
# Defined next to the constructors they choose between (`sage_live.api.orders`) and re-exported
# here, because this module is where the *answer* is derived and that one is where getting it
# wrong costs an order. `CAST_PASSIVE` is the one that is not an order at all: a button with no
# reload and no target is a power whose whole effect landed when it was **bought**. Gondor's
# Gandalf the White and Formationen Gondors are both this.

# What a power actually does. **Nothing in the `SpecialPower` block says this** - it carries the
# radius, the recharge and the prerequisites and stops there - so it is read off the module on
# the spellbook object that implements the power, which is the same "ask the module" rule that
# finds production queues and lair spawns.
#
# `Enum` looks like it should answer and does not: Edain reuses the engine's enum slots freely,
# declaring Army of the Dead as `SPECIAL_SPELL_BOOK_BOMBARD` with the army-of-the-dead slot
# commented out beside it. Names are no better. The module is the only honest source.
EFFECT_SUMMON = "summon"
EFFECT_STRIKE = "strike"
EFFECT_BUILD = "build"
EFFECT_BUFF = "buff"
EFFECT_HEAL = "heal"
EFFECT_GRANT = "grant"
EFFECT_UNKNOWN = "unknown"
# A buff that lands on the **caster** and on nothing else - Boromir's Blade Master, Faramir's
# poisoned blades. Kept apart from `EFFECT_BUFF` because the two are aimed by opposite questions:
# an ally buff is worth firing where the most of your army is standing, and a self buff is worth
# firing when the caster itself is in a fight, wherever that happens to be. Declared by a module
# field of its own (`HeroAttributeModifier`) rather than inferred, so nothing has to guess.
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

# The `Options` tokens that say whose side a button's target is on, mapped to the filter
# vocabulary the rest of this module already speaks.
#
# **The button is the only place some abilities say this.** A module that fires a `SpecialWeapon`
# looks identical whether the weapon lands on an enemy or on a friend, and both exist: Gandalf's
# Wizard Blast is `NEED_TARGET_ENEMY_OBJECT` and Beregond's four `TalkToMe` abilities are
# `NEED_TARGET_ALLY_OBJECT` - the same module shape pointed the opposite way. Reading the module
# alone calls both a strike, which would have a bot firing hero abilities at its own battalions.
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

# The two `CommandButton` commands that build on a plot, and the orders they send. They are not
# interchangeable and the button decides which one a target takes: `CASTLE_UNPACK` sends an
# **argument-less** `0x43D` and lets the engine read the target's own `CastleBehavior`, while
# `CASTLE_UNPACK_EXPLICIT_OBJECT` sends `0x43F` naming the button's `Object`.
#
# The split is not "flag versus plot" - it is "let the faction decide" versus "build this". In
# RotWK 2.01 + Edain the explicit form carries 133 of the 166 unpack buttons and every one of
# them names an `Object`; the 17 plain ones are the neutral claims (`command_unpackoutpost*`,
# `command_unpackcamp`, `command_unpackcastle`). Read the target's buttons rather than guessing,
# which is what `Statics.unpack_buttons` is for.
CASTLE_UNPACK = "CASTLE_UNPACK"
CASTLE_UNPACK_EXPLICIT = "CASTLE_UNPACK_EXPLICIT_OBJECT"
UNPACK_COMMANDS = frozenset({CASTLE_UNPACK, CASTLE_UNPACK_EXPLICIT})

# Edain's four buildable-plot families, keyed by the name the *interface* gives each, because
# the template names give nothing away and reading them as English gets it wrong.
# `WirtschaftPlotFlag_Real` is the **settlement** - "Wirtschaft" is economy, and calling it an
# economy plot is what led to sending it the wrong order for a week.
#
# Outposts, castles and camps take the plain `CASTLE_UNPACK`. **A settlement does not**, though
# it is the one that looks most like a neutral claim: its plain button is on the *unowned*
# palette only, and claiming the flag swaps that away for explicit per-building buttons, so a
# player never sees it. This mapping is a guide to reading a map, not a substitute for
# `unpack_buttons` - a family does not decide the order, the live palette does.
# **The castle and camp entries carried a literal `<XX>` and matched nothing.** They were written
# as `FestungPlotFlag<XX>_Real` and `LagerPlotFlag<XX>_Real`, as though the tree spelled a number
# or a faction code into the middle of the name; it does not. Checked against RotWK 2.01 + Edain,
# the declared objects are `FestungPlotFlag_Real` and `LagerPlotFlag_Real`, each beside a plain
# form without the suffix. Nothing read this mapping until `Warfare.worth_taking` did, which is
# why a constant that answered "no such plot family" for half its entries went unnoticed.
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

# The `KindOf` on the stump a rebuildable structure leaves when it dies. A creep lair's
# `RebuildHoleExposeDie` names a `HoleName` and gives it a few hundred hit points, and the hole
# then quietly rebuilds the lair after its `WorkerRespawnDelay` - two minutes for the shipped
# ones. It is also `NOT_AUTOACQUIRABLE`, so no unit will ever pick the fight itself: razing a
# lair for good means naming the hole in an attack order, which is a thing a policy has to know
# to do. This flag is how it is found, for every lair and every faction, with no name list.
REBUILD_HOLE = "REBUILD_HOLE"

# The `CommandButton` command that switches a battalion between its two formations. It carries
# no `Object`, no cost and no argument of its own: what the alternate formation *is* is declared
# on the horde, not on the button, and the button's only job is to say the interface offers the
# switch at all.
#
# **Which is a real question rather than a formality**, because a command set may name a button
# the tree does not declare and the engine simply draws nothing for it. RotWK's own
# `commandbutton.ini` has most of the vanilla formation buttons commented out - including the
# two `GondorArcherHordeCommandSet` and `GondorKnightHordeCommandSet` name in slot 2 - and it is
# only Edain's `includes/commandbutton.inc`, 67 toggles of its own, that puts them back. So
# whether a battalion can be switched is a fact about the merged tree, not about either file,
# and `formation_button` asks the merged tree.
HORDE_TOGGLE_FORMATION = "HORDE_TOGGLE_FORMATION"

# The three `HordeContain` fields the formation system is written in.
#
# `AlternateFormation` names *another object* - a `ChildObject` of the horde whose only real
# content is a second `HordeContain`. Toggling does not create it: the engine reads that module
# and applies it to the battalion already standing there, which is what the tree's own comment
# ("for alternate formations, all info outside of the Contain Behavior module is ignored") is
# saying. Both objects name each other, so the link is a pair rather than a direction, and
# `ThisFormationIsTheMainFormation` is the only thing that says which half is which.
ALTERNATE_FORMATION = "AlternateFormation"
MAIN_FORMATION = "ThisFormationIsTheMainFormation"
FORMATION_MODIFIERS = "AttributeModifiers"

# The `SpawnBehavior` field naming what a structure garrisons itself with. A creep lair is
# nothing but this: `DunlandGoblinLair` spawns twelve wildmen and replaces each one that dies,
# so the defenders around it are not a force to be killed but a tap to be turned off.
SPAWN_TEMPLATE = "SpawnTemplateName"

# The module marking an object that belongs to a master rather than to a player. It is the same
# relationship `HordeContain` describes and the same consequence: the master drives it, and an
# order addressed to it is an order to something that is not taking orders.
#
# What it catches is everything a base produces that is not an army. A `GondorWohnhaus` spawns
# `GondorZiviliist01` with `SlavedUpdate` and `DieOnMastersDeath`, a battalion's standard is
# slaved to the battalion, and a creep lair's defenders are slaved to the lair. None of them
# is orderable, and all of them are `SELECTABLE`, mobile, and carry a body - so nothing shorter
# than this tells them from a battalion. Measured over the whole tree: **no** template any
# command set can recruit is slaved, and no hero on any of the seven rosters is.
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

# The three fields the engine's crush system is written in, and they are a matched set: a mover
# crushes a stander when its `CrusherLevel` is **strictly greater** than that stander's
# `CrushableLevel`, unless the stander's body resists at that level. The tree spells the scale
# out in a comment on nearly every declaration - `0 = small animals, 1 = infantry, 2 = trees,
# 3 = vehicles` for the crusher, `0 = for infantry, 1 = for trees, 2 = cavalry/heroes` for the
# crushable - so one number answers both "can this trample" and "can this be trampled".
#
# **All three are ordinary `Object` fields rather than modules**, except the resist, which hangs
# off a body: `PorcupineFormationBodyModule` is what a pike formation is, and `CrusherLevelResisted
# = 1` on it is the engine's own statement that infantry-level crushing does not work here. 52
# templates in RotWK+Edain declare one.
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
    """One upgrade a producer's `CommandSet` offers, and what it costs to take it.

    **Upgrades come in two tiers and buying only the first does nothing.** A faction tech is
    `PLAYER` scope, bought once at a structure, and it does not touch a single unit - what it
    does is satisfy the `NeededUpgrade` of an `OBJECT`-scope button on the battalions, which
    is where the armour or the blades actually land. `GondorForge` sells
    `Upgrade_TechnologyGondorHeavyArmor`; `GondorFighterHorde` sells `Upgrade_GondorHeavyArmor`
    and is gated on the first. A policy that stops after the tech has spent its gold for no
    combat effect, and nothing in the game reports that.

    `player_scope` decides which of the two live fields answers "do I already have this":
    `PlayerState.upgrades` for a faction tech, `GameObject.upgrades` for a per-object one.
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

    **The currency is not gold.** A power costs spellbook points, which accrue on their own
    clock and buy nothing else, so this competes with no other spend the bot makes - which is
    why the stage that reads these needs no floor and no reservation.

    `cost` is `SciencePurchasePointCostMP`, deliberately not `SciencePurchasePointCost`. The
    two are different numbers for nearly every power in RotWK+Edain - Gondor's Army of the Dead
    is 10 in multiplayer and `GOOD_RANK_4_COST` in single player - and a skirmish is
    multiplayer, so reading the single-player field prices the whole book wrong.

    `prerequisites` is the science tree, as **alternative groups**: `SCIENCE_GOOD OR
    SCIENCE_MEN SCIENCE_RebuildMen` is two ways of unlocking, the second of which wants both of
    its entries. Whitespace is *and*, `OR` separates the alternatives - so reading the field as
    a flat list gets the tree wrong in both directions at once.

    **`triggers` is the second half of buying a passive, and buying without it does nothing
    visible.** A purchase button may carry a `CommandTrigger` naming another button, and the
    engine fires that one as well - so the click a player makes is two orders, not one. For the
    passives that is where the whole effect lives: `Command_PurchaseSpellFormationenGondors`
    grants `SCIENCE_FormationenGondors` and triggers `Command_SpellBookFormationenGondors`,
    whose `SpecialPower` is what actually turns the aura on. The science alone changes nothing -
    the aura is `StartsActive = No` and is `TriggeredBy` an upgrade the science does not grant.

    Measured live: a bot that sent only the `PURCHASE_SCIENCE` order held the science, passed
    its own confirmation, showed the power as bought in the store, and never once put the
    formation bonus on a battalion. 23 of the tree's 164 purchase buttons carry one of these.

    None where the button names no trigger, which is the ordinary case - an active power is
    bought and then cast on its own schedule, and needs nothing extra at purchase time.
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

        Every store is padded to twenty slots with `Command_PurchaseSpellEmpty`, and the padding
        does not need a name list to recognise: `SCIENCE_Empty` is `IsGrantable = No` and its
        single prerequisite group is `SCIENCE_EVIL SCIENCE_GOOD` - both alignments at once,
        which no player holds. Either test alone excludes it; both are checked because each is
        the data saying "not for sale" in its own words.
        """
        return self.grantable and self.cost > 0


@dataclass(frozen=True)
class CastablePower:
    """One power on a faction's spellbook: how to fire it, what it does, and how often.

    The casting counterpart of `PowerButton`, and read off a different command set - the store
    sells, the book casts. They are joined by the science: `sciences` is the power's
    `RequiredSciences`, which is exactly what `PowerButton.science` bought.

    **`form` decides the order and getting it wrong is silent.** A power sent through the wrong
    constructor is accepted, charged nothing and does nothing, which reads exactly like a broken
    encoder - see `sage_live.api.orders.cast_self`. It comes from the firing button's `Options`,
    not from what the spell sounds like.

    **`effect` decides where to aim**, and it is the one thing no ini field states outright; see
    the `EFFECT_*` constants for where it is read from instead. `spawns` carries what a summon
    or a build finally puts on the map, so a policy can price it with `build_cost` and
    `effectiveness` like any other unit rather than treating a summon as an opaque good thing.

    **`reload_seconds` is long and that is the whole shape of the decision.** The cheapest
    Gondor power recharges in 180 seconds and Army of the Dead in 830, so a power fires a
    handful of times in a match: a cast dumped on a poor target costs minutes, and a cast never
    made costs everything it would have done. Note this is the *undiscounted* figure - Edain's
    `SpellRechargeModifierUpgrade` shortens it and that modifier is live player state - so
    treating it as the cooldown is conservative and never early.
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
    # How long the power reveals the ground it was cast on, from `ViewObjectDuration`. **Worth
    # carrying because it is an oracle**: a power that declares one drops a visible marker
    # object at the cast point, so "did this fire" has a direct answer even for an effect that
    # changes nothing observable otherwise. That is the only confirmation a buff can have -
    # an attribute modifier touches no field an observation carries.
    #
    # Not every power has one, and assuming otherwise would build a confirmation that reports
    # every cast as failed: measured on Gondor's book, 4 of the 8 real spells declare it, and
    # the four that do are exactly the four whose marker was seen live.
    view_seconds: float = 0.0
    # The OBJECT-scoped upgrades this power permanently confers on what it touches, which is the
    # one thing a buff leaves behind that an observation can see. A target already carrying them
    # has had this power and would gain nothing from another - see `granted_upgrades` for why
    # only the permanent ones are here.
    grants: tuple[str, ...] = ()
    # **The upgrade that unpauses this power, for a hero ability. Empty for a spellbook power**,
    # which is gated by a science instead - see `sciences` and `enabled_for`.
    #
    # Every hero ability starts paused and is opened by an `UnpauseSpecialPowerUpgrade` naming
    # `Upgrade_Level_N`, which is the hero's level. That upgrade is OBJECT-scoped, so it lands in
    # the hero's own `GameObject.upgrades` and the gate is a live read rather than an experience
    # counter something would otherwise have to keep. Measured across the Men roster: Beregond's
    # eight abilities open at levels 1, 1, 3, 3, 5, 8, 8 and 10.
    unlocked_by: str = ""
    # `StartAbilityRange` - how close the caster must be before the ability fires at all. **The
    # caster walks to it**, so this is not a filter on targets, it is the distance a policy is
    # committing its hero to travelling: Gandalf's Wizard Blast is 80, so an order aimed across
    # the map is a wizard walking alone into whatever is over there. Zero where the ability
    # declares none, which means the engine imposes no approach of its own.
    ability_range: float = 0.0

    def unlocked_for(self, upgrades: Container[str]) -> bool:
        """Whether the caster has reached the level this ability opens at, matched lowercased.

        A power that names no unlock upgrade is open, which covers every spellbook power and the
        handful of hero abilities that carry no `UnpauseSpecialPowerUpgrade` at all - Gandalf's
        shield bubble among them.
        """
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

    A castle plot inside your own base offers one of these per thing it can become, each
    naming its `template`; an unclaimed outpost, castle or camp offers a single one with no
    template, because the engine picks the base layout from the plot's own
    `CastleToUnpackForFaction` row for the claiming faction.

    `explicit` is the whole decision a caller has to make. Sending the wrong order of the two
    is not a malformed order - it is a well-formed order the engine consumes and discards in
    silence, which looks exactly like nothing happening.
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
    """The alternate formation a battalion can be told to stand in, and what standing in it buys.

    A battalion in this engine has at most two formations and one button that swaps between them.
    The ordinary one carries no bonus - Gondor's spells that out, giving the main formation a
    `RemoveFormationBoni` modifier list with nothing in it but the `Category` - and the alternate
    carries a `ModifierList` that is the whole of the trade. `GondorFighterHordeBlock`'s is
    `ARMOR 17%` and `SPEED 70%`, which the control bar shows as "+20% Armor, -30% Speed".

    **The two numbers are combined differently and the difference is not cosmetic.**
    `sage_ini.model.state` is the authority here and this reads through it rather than
    reimplementing the arithmetic: `SPEED` and `DAMAGE_MULT` are *multipliers* where 1.0 is
    neutral, while `ARMOR` is a summed *fraction* the engine feeds into `1/(1-v)`, so 0.0 is
    neutral there and 0.17 is the +20% the tooltip claims. Reading either one as the other gets
    the sign right and the size wrong, or - for a formation that trades the other way - the sign
    wrong too.

    **The armour comes in two kinds and collapsing them loses whole formations.** An `ARMOR`
    line may name damage types it is scoped to, and several here do: the knights' wedge is
    `ARMOR 33% SLASH SPECIALIST`, the Morthond ambush is armour against ranged fire only, and
    Pelargir's shield wall is `ARMOR 50% WATER`. Summed with the untyped bonuses those read as
    protection against everything, which is false; dropped, three of Gondor's formations read as
    pure downside, which is also false. So `armour` is the bonus that applies to all damage and
    `armour_scoped` the one that applies only to `armour_types`.
    """

    # The horde in its ordinary formation, and the child object the toggle swaps its contain
    # module for. Both spelled as the tree spells them.
    template: str
    alternate: str
    # The `HORDE_TOGGLE_FORMATION` button the owner's control bar really offers, and the
    # `ModifierList` the alternate applies. Either may be empty, and they fail differently: no
    # button means a human could not switch and neither may we, while no modifier list means the
    # switch is legitimate and buys nothing worth spending an order on.
    button: str
    modifiers: str = ""
    # Summed `ARMOR` fractions: the `v` in the engine's `1/(1-v)`. Positive is tougher, and
    # negative happens - the Dol Amroth wedge buys its damage with `ARMOR -25%`.
    armour: float = 0.0
    armour_scoped: float = 0.0
    armour_types: tuple[str, ...] = ()
    # Multiplicative, 1.0 being unchanged.
    speed: float = 1.0
    damage: float = 1.0
    # Summed, as `UnitState.vision` applies it: `base * (1 + vision)`.
    vision: float = 0.0
    # Whether the formation holds its ground - a pike wall, or a shield wall that cannot be
    # knocked out of its ranks. **Not derivable from the numbers above**, which is why it is a
    # field of its own: the pikemen's porcupine gives no armour at all and costs 90% of their
    # vision, so by every figure here it makes the battalion strictly worse. What it actually
    # does is `CRUSHED_DECELERATE 2000%` - a cavalry charge that hits it stops dead - and
    # Pelargir's wall does the same job through `RESIST_KNOCKBACK`. Both are worth a great deal
    # against the thing they are for and nothing at all against anything else.
    braces: bool = False

    @property
    def tougher(self) -> bool:
        """Whether the alternate is the more survivable of the two, against anything.

        Scoped armour counts. A formation that is only tougher against slashing is still a
        formation bought to survive, and the alternative reading - that a bonus against most of
        what melees it is no bonus - would throw away three of Gondor's five usable formations.
        """
        return self.armour > 0.0 or self.armour_scoped > 0.0

    @property
    def slower(self) -> bool:
        return self.speed < 1.0

    @property
    def deadlier(self) -> bool:
        return self.damage > 1.0

    @property
    def worth_taking(self) -> bool:
        """Whether the alternate buys anything at all a caller could want.

        A formation with a button and no modifier list is real and empty - the toggle works and
        changes only the ranks the units stand in. Nothing here is worth an order.
        """
        return bool(self.button) and (
            self.tougher or self.deadlier or self.braces or self.vision > 0.0
        )

    @property
    def defensive(self) -> bool:
        """Whether this formation is bought to survive rather than to kill.

        The distinction the caller acts on: a defensive formation is worth standing in while a
        fight is being held and worth leaving the moment the battalion has somewhere to be, and
        an offensive one is not obviously worth either. `braces` counts because a pike wall is a
        defensive posture whatever its modifiers say.
        """
        return self.braces or (self.tougher and not self.deadlier)


@dataclass(frozen=True)
class CostLadder:
    """One `CostModifierUpgrade`: the discount an owner gets for holding several of a thing.

    **A price the ini quotes and the engine never charges.** Edain's economy buildings each carry
    one of these with `StartsActive = Yes`, so it needs no upgrade and applies from the moment the
    building stands. Six rungs is the shipped shape - 0, -10, -15, -20, -25, -30 percent - indexed
    by how many `carrier` objects the player owns, which makes the sixth the last one worth
    building for.

    **`carrier` is the object the module sits on, and it is often not the building.**
    `GondorWohnhaus` declares nothing; its ladder is on the `GondorWohnhaus01..03`
    `BuildVariations`, one of which is what actually gets placed. `GondorForge` is stranger still:
    the module on the forge itself is a stub of a single 0% rung, commented in the ini as being
    only to draw the discount in the palantir, and the real six-rung ladder lives on
    `GondorForgeDiscountPing` - a `SLAVED`, `UNATTACKABLE`, `IGNORE_FOR_VICTORY` helper the forge
    spawns and which dies with it. One ping per standing forge, so counting either gives the same
    rung, but only one of them carries the numbers.

    **Two scopes, and a ladder has exactly one.** `upgrades` is non-empty when the module sets
    `UpgradeDiscount`, and then it marks down those upgrades' purchase price; otherwise
    `templates` holds the `ObjectFilter`'s inclusion list and it marks down building or recruiting
    those. The town house's filter is the faction's elites plus `CPObject`, which is why a citadel
    guard quoted at 600 is charged 420 in a base with six houses.
    """

    carrier: str
    percentages: tuple[float, ...]
    upgrades: frozenset[str] = frozenset()
    templates: frozenset[str] = frozenset()

    def rate(self, count: int) -> float:
        """The multiplier applied at `count` carriers - -0.3 at the top of a shipped ladder.

        **Indexed by count, saturating at both ends.** One carrier is the first rung and a
        seventh cannot improve on the sixth, so a base past the cap pays the same as one at it.
        Zero carriers is no discount at all rather than the first rung, which matters because the
        first rung is 0% anyway and a caller that owns none should never reach this.
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

    The three shares are `PercentageOfArmyPhase1..3` - what proportion of the army this unit
    should be during the rush, the mid game and the end game. They are percentages of an army
    rather than of each other and the file does not normalise them: Men's phase 1 sums to well
    over 100 across 57 members, because most of those members belong to sub-factions a given
    match never fields. Normalise across whatever survives filtering, never across the file.
    """

    unit: str
    shares: tuple[float, float, float]

    def share(self, phase: int) -> float:
        """This unit's target share in `phase` (0, 1 or 2), clamped to the three that exist."""
        return self.shares[min(max(phase, 0), 2)]


@dataclass(frozen=True)
class ArmyPlan:
    """A faction's whole `ArmyDefinition`: what the skirmish AI would build, and when.

    **A pool and its weights, never a legality check.** The list mixes in units no player can
    reach - sub-faction rosters the match did not pick (`AmrothFighterHorde`,
    `ArnorTowerShieldGuardHorde_Cardolan`), and AI-only stand-ins that no command set offers.
    Some of the latter are marked `_AI` and some are not, so the suffix cannot be filtered on.
    The only sound filter is the one the rest of this module already applies to everything else:
    intersect with `Statics.recruits` of the buildings actually owned, which is the set a human's
    control bar would have shown.

    What the definition is genuinely authoritative about is the *mix* - that Gondor wants a
    quarter archers and 5% cavalry early, and shifts toward elites late - which is exactly the
    part no command set can answer.
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
    """A block's declared fields, for the walks that hold one as an opaque object.

    Several lookups here take whatever the ini model handed back rather than a narrowed type -
    a `PlayerTemplate` found by Side, a command button found by name - and reading `.fields` off
    those is only safe because every block in the tree has them. Saying so once, in a typed
    helper, is cheaper than an assertion at each site and keeps a block that genuinely lacks them
    from raising in the middle of a match.
    """
    found = getattr(block, "fields", None)
    return found if isinstance(found, dict) else {}


def _condition_free(block: object) -> bool:
    """Whether a `WeaponSet` or `ArmorSet` is the one that applies with nothing bought.

    Both families are declared once per combination of conditions - `Conditions = None`, then
    `PLAYER_UPGRADE`, `ALTERNATE_FORMATION` and their products, eight of them on an ordinary
    Gondor soldier. `None` is the ini's own word for the unconditional set, so it is the one
    that describes a unit as recruited, which is the honest baseline for comparing two units a
    policy has not bought anything for yet.
    """
    declared = str(getattr(block, "fields", {}).get("Conditions", "")).strip()
    return declared == "" or declared.upper() == "NONE"


def _number(block: object, field: str, fallback: float) -> float:
    """One numeric ini field off a raw block, tolerating what the file actually writes.

    These carry trailing `f` suffixes, percent signs and comment tails in the wild
    (`PhaseDuration_Rush = 300.0 ;//amount of time`), and a field the block simply omits is
    normal rather than an error - so anything unreadable falls back rather than raising.
    """
    tokens = str(getattr(block, "fields", {}).get(field, "")).split()
    if not tokens:
        return fallback
    try:
        return float(tokens[0].rstrip("f%"))
    except ValueError:
        return fallback


class _Merged:
    """Several modules implementing one power, read as though they were a single module.

    Exists because a hero splits an ability across two or three of them and `_classify` reads
    fields - see `Statics._ability_modules`. Presents the union of their raw fields, and forwards
    anything else to the first source module that has it, so the **typed** accessors keep
    working: a range written as a macro expands through `_float_field`'s typed path and floats to
    nothing through the raw one, which is the trap `_float_field` itself was written for.
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
    """A module's declared type - the `SlavedUpdate` of `Behavior = SlavedUpdate ModuleTag_Slave`.

    Read off the block's own name rather than off the Python class, so a module this model has
    no class for still answers with what the ini called it; the class name is the fallback for a
    block the loader named some other way.
    """
    declared = str(getattr(module, "name", "") or "").split()
    return declared[0] if declared else type(module).__name__


def _definition_name(reference: object) -> str:
    """The name of a definition a field points at, whether it resolved or stayed a string.

    `sage_ini` hands back the referenced block where it can find one and the raw token where it
    cannot, and a list like `ApplyToTheseUpgrades` routinely holds both - an upgrade defined in a
    file this tree loaded, next to one that is only named. Both are the same answer to "what is
    this called", so this flattens them rather than making the caller test.
    """
    tokens = str(getattr(reference, "name", reference) or "").split()
    return tokens[0] if tokens else ""


def _int_field(block: object | None, field: str) -> int:
    """One integer off a **typed** block, or 0 where it is missing or not a number.

    The typed accessor rather than the raw field, for the reason `upgrade_cost` records: a cost
    is routinely written as a macro (`GOOD_RANK_1_COST`) and only the typed path expands it.
    """
    value = getattr(block, field, None)
    return int(value) if isinstance(value, int | float) else 0


def _float_field(block: object | None, field: str, fallback: float = 0.0) -> float:
    """One float off a block, **typed first** so a macro expands, raw as the fallback.

    The two paths are not interchangeable and reading only the raw one is a silent zero: a
    spell's radius is routinely written as a `#define` (`RadiusCursorRadius =
    SPELL_REBUILD_RADIUS_CURSOR`, which is 150), and the raw field then answers with the macro's
    *name*, which floats to nothing. Measured live - the bot sized Rebuild's circle at a
    fallback 100 while the game drew 150 and scanned 300.
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

    `sage_ini` parses `A OR B C` into `[[A], [B, C]]` and resolves each entry to the `Science`
    it names where the tree defines one, so this reads back a name from either form - the
    definition's own or the raw token for one nothing defines.

    **Two blocks spell the same expression under different keys**, which is worth a parameter
    rather than two copies: a `Science` gates itself with `PrerequisiteSciences` (what the spell
    store checks before selling) and a `SpecialPower` gates itself with `RequiredSciences` (what
    the book checks before casting). Reading the wrong one returns nothing at all - silently, and
    with the shape of a power that needs no science, which is the most permissive possible wrong
    answer.
    """
    groups = getattr(block, field, None) or ()
    return tuple(
        tuple(str(getattr(entry, "name", entry)) for entry in group) for group in groups if group
    )


def _cast_form(options: Iterable[str], reload_ms: int) -> str:
    """Which cast order a spellbook button sends, from its `Options` and its recharge.

    The `NEED_TARGET_*` bits decide it and the engine picks the order type to match - an
    invariant the replay corpus confirms on every recorded cast (`order_space_map.md`). So the
    button is the authority here, exactly as it is for the two unpack orders.

    **A button with no target *and* no recharge is not a cast at all.** Both halves are needed:
    `NONPRESSABLE` alone would also catch a power that is merely not clickable in some state,
    and a zero recharge alone would catch one that is simply always ready. Together they are
    Gondor's Gandalf the White - bought once, granted permanently, and never fired.
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
        # Keyed lowercase once, so every later lookup is a dict hit rather than a scan over
        # eleven thousand names.
        self._objects = {str(name).lower(): obj for name, obj in objects.items()}
        self._sets = {str(n).lower(): s for n, s in game.tables.get("commandsets", {}).items()}
        self._buttons = {
            str(n).lower(): b for n, b in game.tables.get("commandbuttons", {}).items()
        }
        self._upgrades = {str(n).lower(): u for n, u in game.tables.get("upgrades", {}).items()}
        # The two halves of the engine's counter system - what a weapon deals, and what an
        # armour block is worth against it. See `effectiveness`.
        self._weapons = {str(n).lower(): w for n, w in game.tables.get("weapons", {}).items()}
        self._armours = {str(n).lower(): a for n, a in game.tables.get("armorsets", {}).items()}
        # `ModifierList` blocks, which are where a buff finally says what it does. Indexed
        # because an upgrade granted through one is the only mark a permanent buff leaves on
        # its target - see `granted_upgrades`.
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

        `root` must already be an ini tree - a live install keeps its data in `.big` archives,
        so mount it first with `sage_utils.gameroot.resolve_game_root`, which is also what
        makes the load cheap on a second run.
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

        An unknown template answers the empty set rather than raising: a live game routinely
        carries templates a differently-modded tree has never heard of, and that is a reason
        to skip the object, not to stop the session.
        """
        key = template.lower()
        cached = self._kinds.get(key)
        if cached is None:
            cached = self._resolve_kinds(key)
            self._kinds[key] = cached
        return cached

    def _resolve_kinds(self, key: str) -> frozenset[str]:
        """Walk to the root of the parent chain, then apply each `KindOf` on the way back down.

        Order matters: a plain `KindOf` replaces whatever was inherited, while `+FLAG`/`-FLAG`
        edit it. Collecting the chain first and applying it root-first is what gets both right;
        reading only the nearest declaration would drop a parent's flags whenever a child used
        the delta form.

        **One block may state the field more than once, and the second line edits the first
        rather than replacing it.** `RohanTheoden_mod_Summoned` spells its flags out and then
        adds `KindOf = +SUMMONED` further down, so the field arrives here as a *list* of two
        declarations - and stringifying that list produced tokens like `['HERO` and `SUMMONED',`,
        which match nothing. Theoden therefore answered no to `HERO`, and the hero stages never
        saw the one summon on Gondor's book carrying a 240-second ability.
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
        """One `KindOf` declaration split into flags, with any `#define` expanded.

        **A macro in this field is not decoration, it is the whole declaration.** `Rabbit`,
        `Fish` and every other animal write `KindOf = NATUREUNITS_KINDOF` and nothing else, so
        reading the raw tokens gives one word that matches no flag and the template answers no
        to every question asked of it - including `INERT`, which is the engine's own way of
        saying "this is scenery, not a combatant". A live match then reads six fish near the
        base as six enemy raiders. `WILD_HOLE_KINDOF` hides `REBUILD_HOLE` the same way.

        Expanded in a loop rather than once, because a macro may name another; the sign of a
        delta token is carried onto every flag the macro brings, so `-SOME_MACRO` subtracts all
        of them. `has_macro` is asked first so a plain flag is never put through `get_macro`,
        which would warn about the case of a name that is not a macro at all.
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
        """Which of `PLOT_FAMILIES` this plot belongs to, or None for anything that is not one.

        **A guide to reading a map, and deliberately not a way of choosing an order.** What order
        a plot takes is `unpack_buttons`' answer and only ever that - the live palette knows, and
        a settlement's changes the moment it is claimed. This answers the different question a
        policy asks before it walks anywhere: what *kind* of expansion is this, so that a cheap
        settlement can be preferred to an outpost while both are still unclaimed and both are
        still showing the same neutral claim button.

        Matched by name, which is the one place in this class that is right rather than a
        shortcut: a plot family is a fixed set of four map objects rather than a tier with
        variations, so there is no `ChildObject` chain to follow and no `BuildVariations` to be
        fooled by.
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
        """Whether this is the stump a razed structure left, which will rebuild it.

        See `REBUILD_HOLE`. The reason a policy has to care is that the hole is
        `NOT_AUTOACQUIRABLE`: an army standing on top of one will never attack it of its own
        accord, so a lair killed and left alone is a lair that comes back.
        """
        return REBUILD_HOLE in self.kind_of(template)

    def is_slaved(self, template: str) -> bool:
        """Whether this template belongs to a master rather than to a player.

        See `SLAVED`. The counterpart to `is_horde_member` and needed for the same reason: both
        describe an object a player owns and cannot command, and both are otherwise
        indistinguishable from a battalion in a live observation. A farm's civilians, a
        battalion's standard bearer and a creep lair's defenders are all slaves.

        Read as a module along the parent chain, since a `ChildObject` inherits the module it
        does not restate - `IsengardWildman_Slaved` declares its own, and the snow variants of
        several lairs' spawns do not.
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

        **This is what makes a creep lair a different kind of target from a battalion.** The
        module replaces every slave that dies, so the units around a lair are output rather
        than opposition and a fight against them has no end; what ends it is the building.
        Empty for anything that spawns nothing, which is most templates.

        Read as a module rather than by name because the lairs share no naming convention and
        no distinguishing `KindOf` - `DunlandGoblinLair` and `WargLair` carry exactly the flags
        an ordinary structure does. Follows the parent chain, since a `ChildObject` inherits
        the module it does not restate.

        **Not a creep test on its own.** Plenty of ordinary buildings spawn something - a farm
        its workers, a tower its garrison - so the caller must also know who owns the thing.
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

        `BuildVariations` is a list of visually different stand-ins - `GondorWohnhaus` declares
        `GondorWohnhaus01 GondorWohnhaus02 GondorWohnhaus03` - and the engine picks one at
        build time. **The ordered template is therefore never the one that appears**, which
        makes "did my building get built?" unanswerable by name, and makes a bot that counts
        `GondorWohnhaus` rebuild forever.
        """
        declared = self.field(template, "BuildVariations")
        return tuple(declared.split()) if declared else ()

    def canonical(self, template: str) -> str:
        """The template that was *ordered* to produce `template`, or `template` itself.

        The inverse of `build_variations`, so a live object can be traced back to the thing a
        build order names. Built once over the whole table and cached.
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
        """`template` and every variation of it, lowercased - what "one of these" means.

        Counting by this is name-based and exact; counting by `KindOf` is broader and needs no
        variation table. Both are here because they answer different questions: "how many
        Wohnhaus" versus "how many economy buildings".
        """
        return frozenset({template.lower(), *(v.lower() for v in self.build_variations(template))})

    def descends_from(self, template: str, ancestor: str) -> bool:
        """Whether `template` is `ancestor` or a `ChildObject` of it, at any depth.

        **The family a tiered building belongs to, which no name test answers.** Edain declares
        an upgraded settlement building as a child of the base one - `GondorFarm_Extern2` and
        `GondorFarm_Extern3` both descend from `GondorFarm_Extern` - and swaps which tier the
        plot offers as the owner's economy upgrades land. So "is this one of my farms" has to
        follow the parent chain.

        A prefix test on the name is the tempting shortcut and it is wrong in both directions:
        `GondorRangerTentsDiscountPing` shares a prefix with the ranger tents while being an
        invisible helper object rather than a tent, and `GondorFarm_Extern` shares none with
        variations declared under another name.
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

        **Orders address the horde, not its members.** A battalion appears in a live
        observation as its individual members *plus* the container, and selecting the members
        is not how the engine expects to be talked to - `HordeAIUpdate` on the container is
        what drives them. Selecting 30 `GondorFighter` and issuing a move produced an order
        that was recorded and then did nothing.

        This is the set to exclude when building a selection. Computed once over the whole
        table, since a horde names its payload and nothing names the reverse.
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

        Found by what it declares rather than by its class name, the same way `spawns` finds a
        `SpawnBehavior`: a `ChildObject` that restates the module carries its own, and one that
        does not inherits its parent's. The three fields below are all read off the same module
        object, so a template whose contain module is inherited answers consistently rather than
        mixing one object's payload with another's formation.
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

        **The legitimacy check for a formation switch.** A command set may name a toggle button
        the tree never declares, and the engine draws nothing for a button it cannot find - so
        the human would see no formation control while `AlternateFormation` sits on the horde
        saying one exists. Reading the horde alone therefore finds formations a player may not
        have; this is what keeps the bot to the ones they do.

        `button_command` answers `""` for a button this tree lacks, which is what makes the
        undeclared case fall out rather than needing its own test. It is not a hypothetical
        case - RotWK's own file comments most of these buttons out and Edain declares its own
        set, so the answer depends on the merge and is worth asking rather than assuming.

        Read through `live_command_set` for the same reason `unpack_buttons` is: a
        `CommandSetUpgrade` can swap the palette out from under the declared field.
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

        None covers four different states and deliberately does not distinguish them, because a
        caller can do nothing about any of them: the template is not a horde, its contain module
        names no `AlternateFormation`, the object it names is not in this tree, or the object it
        names is itself a main formation.

        **That last one is the direction check, and without it this answers for both halves of
        every pair.** The two objects name *each other*: `GondorFighterHorde` names
        `GondorFighterHordeBlock` and the block names the fighter straight back. Only
        `ThisFormationIsTheMainFormation` says which of them carries the bonus, so a formation is
        returned only when the thing on the far end declares itself not to be the main one - and
        asking this of a battalion that is already in its alternate formation answers None, which
        is the truthful answer to "what else could it be standing in".

        The modifiers are read through `sage_ini.model.state`, which owns how each modifier type
        combines; see `Formation` for why that matters.
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
        """What one alternate formation's `ModifierList` is worth, as the `Formation` itself.

        Every combination rule here belongs to `sage_ini.model.state` and is called rather than
        copied - `armor_scalar_bonus` for the summed armour fractions, `modifier_product` for the
        two multipliers, `modifier_sum` for vision. A formation naming a list this tree does not
        declare reads as the neutral formation it effectively is.
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

        The legitimacy check for a recruit, and the only way to find a producer without naming
        one per faction. `CPObject`, the object that raises the command-point ceiling, is sold
        by every faction's keep through a differently-named button on a differently-named
        command set, so asking each owned building what it can build finds it everywhere and
        hard-coding a keep name finds it for one faction.

        **`upgrades` is what makes the answer true of a real building rather than of a fresh
        one**, and leaving it out is wrong in both directions at once. A `GondorBarracks` at
        level 1 answered with all seven of its buttons, four of which carry a `NeededUpgrade`
        the building does not hold - so a bot ordered `GondorTowerShieldGuardHorde` at a
        barracks that could not make one, and the engine discarded it in silence. The same
        omission hides the other half: the level-2 palette arrives through a `CommandSetUpgrade`
        (`GondorBarracksCommandSetLevel2`), and a caller reading the static `CommandSet` field
        never sees a levelled building's wider list at all.

        Pass the union of the owning player's upgrades and the object's own; the default of
        none describes a building as it stands the moment it is raised, which is what a
        pre-match report wants and what a live cycle does not.
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

        `recruits` answers for a building as it stands, which is what a live cycle needs and
        what a pre-match report must not use: a `GondorBarracks` as raised sells two battalions
        and sells four once its levels are bought, so a report built on the first number says
        the plan reaches half the army it reaches. This unions the declared `CommandSet` with
        every one any `CommandSetUpgrade` on the object names, and ignores `NeededUpgrade`
        entirely - the question it answers is "is this unit on the plan's path at all", not "can
        it be ordered this frame".
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
        """The `CommandSet` the control bar would really show for this template, given the
        upgrades its owner holds - which is **not** the `CommandSet` field.

        A `CommandSetUpgrade` module replaces the palette whenever its `TriggeredBy` upgrades
        are held, and plots lean on this hard: `WirtschaftPlotFlag_Real`, the shared economy
        plot, carries **26** of them. Its declared `CommandSet` belongs to nobody in
        particular, and each faction's real one arrives with `Upgrade_MenFaction`,
        `Upgrade_IsengardFaction` and so on - with second and third palettes layered on top by
        the economy techs. Reading the static field answers for a plot no player owns.

        `upgrades` is the union of the owning player's and the object's own, matched
        case-insensitively; the engine's own rule of *last active module wins* is applied by
        `sage_ini.model.state`, which owns this logic for every module family.
        """
        obj = self._objects.get(template.lower())
        if obj is None:
            return None
        return active_command_set_name(obj, _FoldedUpgrades(upgrades))

    def unpack_buttons(
        self, template: str, upgrades: Iterable[str] = ()
    ) -> tuple[UnpackButton, ...]:
        """Every way this plot can be built on, in slot order - empty for anything but a plot.

        This answers "which unpack order do I send, and with what" from the data instead of
        from a rule of thumb, which is the only reliable way: the two orders are not
        interchangeable, the choice belongs to the button rather than to the kind of plot, and
        sending the wrong one is silently discarded (see `UNPACK_COMMANDS`).

        **`upgrades` is not optional in practice.** The palette is resolved through
        `live_command_set`, so the default of "no upgrades held" describes an unowned plot and
        will report the wrong buttons - often none at all - for a plot in a real base. Pass the
        owning player's upgrades union the object's own.

        A button whose command is `CASTLE_UNPACK_EXPLICIT_OBJECT` but which names no `Object`
        is dropped: that order's entire payload is the template, so there would be nothing to
        send. The reverse is kept as-is - one `CASTLE_UNPACK` button in RotWK 2.01 + Edain
        (`command_constructentmoot`) does name an `Object`, and the engine ignores it, so
        `template` is reported for what it is and `explicit` still says which order to send.
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

        The typed accessor rather than `field`, for the same reason `upgrade_cost` uses it: the
        ini spells these as macros - `GONDOR_SOLDIER_BUILDCOST`, not `200` - so the raw field
        answers with the macro's *name*, which compares against a gold balance as nonsense
        rather than as an error.

        **A quoted price, not the price charged.** Edain discounts several of these from the
        buildings you own - each `GondorWohnhaus` takes another slice off `CPObject` and off the
        faction's elites through a `CostModifierUpgrade`, up to -30%. So the number here is the
        undiscounted ceiling: safe to refuse a spend below, never safe to treat as exact.

        The discount itself is not unknowable, only absent from this method: `cost_ladders` reads
        the modifiers out of the same tree, and a caller who can count the buildings standing can
        join the two. `Statics` holds no live state, so that join belongs to whoever does.

        Follows the parent chain, because a template that declares no cost of its own inherits
        one - `CPObject` gets its 500 from `CPObject_Unlimited`.
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

        **The other currency, and the one nothing was checking.** Gold is not the only thing a
        recruit spends: the engine refuses an order that would take a player past their command
        point cap, and it refuses it the same silent way it refuses an unaffordable one - the
        stream takes the order, logic discards it, nothing is reported. Measured over one live
        match: 71 of 219 recruit orders discarded, at a mean of **46** free command points
        against 409 for the ones that queued, with 99% of the failures under 150.

        Read through the typed accessor for the same reason `build_cost` is: the ini spells these
        as macros - `COMMAND_POINTS_ARCHER_15_HORDE`, not a number - so the raw field answers with
        the macro's name, which compares against a ceiling as nonsense rather than as an error.

        **Ask it of the horde, not the soldier.** A battalion is recruited as one `...Horde`
        object and that is what carries the battalion's whole charge; the member template
        declares its own smaller number for the single unit, so pricing a recruit off the member
        under-counts it by the size of the horde.

        Follows the parent chain, because a template that declares no cost of its own inherits
        one - exactly as `build_cost` does.
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

        **A whole-tree scan rather than a lookup, because the carrier is not the thing you own.**
        A caller holding six town houses cannot ask "what discount does a town house give?" and get
        an answer - `GondorWohnhaus` declares no module at all, and the ladder is on the build
        variation the engine happened to place. Scanning once and letting the caller match by
        carrier is the only version of this that finds both that case and the forge's, where the
        numbers live on a slaved helper object with a different name again.

        **Stubs are kept rather than filtered.** The forge's own module is a single 0% rung that
        exists to draw a label in the palantir; it is a real ladder that happens to discount
        nothing, and `rate` returns 0 for it without needing a rule about which modules are
        decorative. Dropping them by length would be a guess about intent that the data does not
        support.

        Cached, since it walks every object once.
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
        """The nearest declaration of a nested block family along the parent chain.

        `WeaponSet` and `ArmorSet` are sub-blocks rather than fields or modules, and
        `sage_ini` hangs each family off the object as a list under its own name. A
        `ChildObject` that restates neither inherits both, so this walks the chain and returns
        the first list that is not empty - the same "nearest declaration wins" rule `field`
        applies, which is what the engine does with these.
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

        A battalion is a container: `GondorSpearmanHorde` has a `HordeContain` and no
        `WeaponSet` or `ArmorSet` of its own, because it is the fifteen `GondorSpearman` inside
        it that fight. Every combat question below therefore has to be asked of the payload,
        and asking it of the horde answers "this thing has no weapon" for every battalion in
        the game. Anything that is not a horde - a hero, a siege engine - answers for itself.
        """
        return self.horde_payload(template) or template

    def damage_types(self, template: str) -> frozenset[str]:
        """The `DamageType`s this template's units deal, uppercased.

        **This is the attacking half of the engine's own counter system**, and it is a real
        field rather than a genre convention: `GondorPikemanWeapon` deals `SPECIALIST`,
        `GondorSword` deals `SLASH`, `GondorArcherBow` deals `PIERCE`. Pair it with `armour`
        and the question "do pikes beat this" is answered by the data instead of by a table of
        unit names that would need maintaining per faction and per mod.

        Two hops are needed and both are ordinary. A `WeaponSet` names its weapon as
        `PRIMARY <name>`, so the slot is stripped; and a ranged weapon carries no damage of its
        own - `GondorArcherBow` is a `ProjectileNugget` whose `WarheadTemplateName` is the
        weapon that does - so a projectile is followed to its warhead.

        Only the unconditional `WeaponSet` is read where there is one. The others are the
        upgraded and alternate-formation variants, and in this tree they deal the same type as
        the base weapon; taking their union instead would blur a unit whose alternate stance
        genuinely changes type.
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

        **On the `LocomotorSet` block, not on the `Locomotor` it names.** The locomotor
        definition carries turning, braking and suspension; the *speed* is written beside the
        reference - `LocomotorSet { Locomotor = HumanLocomotor; Condition = SET_NORMAL; Speed =
        NORMAL_FOOT_MED_MEMBER_SPEED }` - so a reader that follows the name into the locomotors
        table finds everything except the number it went looking for.

        Only `SET_NORMAL` is read. The other conditions are damaged, burning-death and wander
        states, and taking the maximum across them would answer with a panic speed no unit moves
        at while it is being asked about.

        Measured on this tree: foot 55, cavalry 120 - which is the whole of what a "can I
        outrun this" test needs.
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

        **The comparable half of crush revenge**, and the reason the raw damage is not. Edain
        writes the revenge as arithmetic - `GondorPikemanCrushRevenge` is `#MULTIPLY(
        BASE_DAMAGE_PIKEMAN_15 CRUSH_REVENGE_MULT_PIKEMAN_15 )` - so the product carries the
        unit's own power and cannot be compared across factions: a Gondor *swordsman* bills 160
        where a Mordor *pikeman* bills 84. The multiplier is the operand, and it is the design:

            CRUSH_REVENGE_MULT_INFANTRY_*   2.0
            CRUSH_REVENGE_MULT_PIKEMAN_*    3.0 / 4.0 / 4.5 / 6.0

        Measured over the whole tree: of 117 battalions declaring one, **all 69 non-`PIKE` read
        exactly 2.0** and the 48 `PIKE` read 2.0 through 6.0. So the design is consistent and a
        cutoff at `CRUSH_REVENGE_CHARGED` separates them with no false positives.

        Found by scanning the expression's identifiers for a `CRUSH_REVENGE_MULT` macro rather
        than by parsing the operand order, because the shared weapons state a flat damage with no
        multiplier at all and would otherwise have to be special-cased.

        0.0 where nothing declares one, which reads as "no special danger" - the same direction
        `effectiveness` takes for an unknown matchup.
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

        The defending half of the counter system. An `ArmorSet` names an `Armor` block and that
        block is a list of `<DAMAGE TYPE> <percent>` lines, which is where the whole rock-paper-
        scissors of the game actually lives: `EdainCavalryArmor` takes **170%** from
        `SPECIALIST` and 30% from `SLASH`, while `EdainInfantryArmor` takes 65% from
        `SPECIALIST` and 135% from `CAVALRY`. That is "pikes beat horses, swords beat pikes,
        horses beat swords" written down by the people who balanced it.

        `DEFAULT` is the engine's own fallback for a type the block does not list, so it is
        kept in the mapping rather than being applied here - see `effectiveness`.
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

        The join of `damage_types` and `armour`, and the whole point of both: a policy asking
        "what should I build against what is on the map" gets a number the game itself
        computes, rather than a hand-written counter table that is wrong the moment a mod
        rebalances an armour block. Gondor pikes into Mordor cavalry reads 1.7; the same pikes
        into Mordor orcs read 0.65, which is the reason a wall of one unit loses.

        1.0 whenever either side is unreadable - a template this build does not define, a
        thing with no weapon at all - because an unknown matchup is not evidence of a good one
        or a bad one, and a caller weighting by this should be left where it started.
        """
        types = self.damage_types(attacker)
        table = self.armour(defender)
        if not types or not table:
            return 1.0
        fallback = table.get("DEFAULT", 1.0)
        return sum(table.get(t, fallback) for t in types) / len(types)

    def _level(self, template: str, name: str) -> int | None:
        """One crush level off `template`'s own chain, or None where nothing declares it.

        None and zero are different answers and the difference decides a charge. Zero is a
        template that says it crushes nothing, which every foot soldier in the tree says out
        loud; None is a template that never mentions the field, and for a battalion that is the
        ordinary case - the horde container declares it and the payload frequently does not, or
        the other way round. Only None may be answered by asking the other half.
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
        """How much this template flattens by walking over it - 0 for anything that does not.

        **Asked of the object that moves, not of the thing that fights.** A battalion crushes as
        a battalion: `GondorKnightHorde` carries `CrusherLevel = 1` alongside the
        `MinCrushVelocityPercent` and `CrushKnockback` that go with it, and its payload
        `GondorCavalry` happens to repeat the 1 - but it is the container that has the
        `PhysicsBehavior` and the container that an order is addressed to. The payload is the
        fallback for the templates that are not hordes at all.
        """
        own = self._level(template, CRUSHER_LEVEL)
        if own is not None:
            return own
        member = self.fighting_template(template)
        return 0 if member == template else (self._level(member, CRUSHER_LEVEL) or 0)

    def crushable_level(self, template: str) -> int:
        """What it takes to flatten this template - **the higher of the horde's and its members'**.

        The two disagree, and in the direction that matters: `GondorKnightHorde` declares 2 and
        the `GondorCavalry` inside it declares 3. Taking the larger errs toward leaving something
        alone, which is the cheap direction - a charge that should have been an ordinary attack
        costs one order, and a charge into something that does not go down costs the battalion
        that made it.
        """
        member = self.fighting_template(template)
        levels = [self._level(template, CRUSHABLE_LEVEL)]
        if member != template:
            levels.append(self._level(member, CRUSHABLE_LEVEL))
        return max((level for level in levels if level is not None), default=0)

    def crush_resisted(self, template: str) -> int:
        """The crush level this template's body shrugs off, 0 for a body that shrugs off none.

        **This is a module rather than a field**, and it is the engine's own exception to the
        arithmetic above: `PorcupineFormationBodyModule` is what a braced pike formation is, and
        `CrusherLevelResisted = 1` on it says that infantry-level crushing does not happen here
        whatever the numbers say. It is declared on the *member* - the container has an
        `ImmortalBody` and nothing else - so both are read and the larger taken.

        **Not the whole answer to "is this a pike", and must not be used as one.** Of the 222
        `PIKE` battalions in RotWK+Edain only about half declare a resist, because in this engine
        bracing is a formation the unit may or may not be standing in. A caller deciding whether
        to ride at something wants the `PIKE` flag as well; this is the narrower fact that the
        crush itself will not land.
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
        """Whether `attacker` riding over `defender` would flatten it, by the engine's own rule.

        Strictly greater, which is the whole of the comparison the crush system makes: a
        `CrusherLevel` of 1 goes through the `CrushableLevel = 0` that every foot soldier carries
        and stops dead at the 2 every cavalry battalion carries. So "cavalry crush infantry and
        do not crush each other" needs no unit list and no `KindOf` - it is already written down,
        once, in the data both sides are balanced from.

        The resist is the exception the same system carries for the units built to stand in front
        of a horse. See `crush_resisted` for why it is not the only test a caller wants.
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

        This is the whole legitimacy question for a research order answered in one call: an
        upgrade reachable from here is one the control bar would have shown, and one that is
        not is an order a human could not have given. Empty for anything that sells no
        upgrades, which is most templates.

        **A levelled building sells a different list, and reading the static `CommandSet` field
        can only ever see the first entry in it.** Edain builds a structure's levels as a chain
        of `CommandSetUpgrade` modules: `GondorBarracks` offers `Upgrade_GondorStructureLevel2`,
        buying it swaps the palette to `GondorBarracksCommandSetLevel2`, and *that* set is the
        only place `Upgrade_GondorStructureLevel3_Barracks` is offered. A caller passing no
        upgrades therefore sees one rung of a three-rung ladder, buys it, and then reports
        nothing left to buy at a building that has just unlocked its next level - and with it
        the units gated on `Upgrade_StructureLevel3`.

        `upgrades` is the union of the owning player's and the object's own, exactly as in
        `recruits` and `unpack_buttons`.
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

        Empty for anything that cannot recruit a hero, which is almost everything. A building
        with slots offers only the ones whose `NeededUpgrade` it can satisfy; the rest are
        present because heroes bind to these slots **by position**, so a building that recruits
        the fourth hero must carry the first three slots as well. See `sage_live.utils.heroes` for
        why the position is offset by one, and for what the engine does and does not check.
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

        `faction` is matched against the block name (`FactionMen`) *and* against its `Side` - a
        live observation reports the Side token, `Men`, and the two are not the same string.
        Where several templates share a Side, the playable one wins: `FactionTutorial` is also
        `Side = Men` and carries a different roster and a different spell store.
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
        """The sciences a faction starts a **multiplayer** match holding.

        `IntrinsicSciencesMP` rather than `IntrinsicSciences`, and the two differ in the way
        that matters: Men start a skirmish with `SCIENCE_MEN` and a campaign with
        `SCIENCE_GOOD`, and nearly every power in the book is unlocked by one of those two
        alone. Read the wrong field and the whole tier-1 row looks open when it is not, or
        closed when it is.

        Only worth reading before the match hands over a live answer - `PlayerState.sciences`
        carries these too, and carries whatever else the seat has been given since.
        """
        block = self.faction_template(faction)
        if block is None:
            return ()
        return tuple(str(_fields(block).get("IntrinsicSciencesMP", "")).split())

    def creates(
        self, ocl: str, depth: int = 0, seen: frozenset[str] = frozenset()
    ) -> tuple[str, ...]:
        """Every template an `ObjectCreationList` finally puts on the map, eggs followed through.

        **A spellbook power almost never creates the thing you want directly.** It creates an
        *egg*: `OCL_GondorArmyofTheDeadEgg` makes four `GondorArmyofTheDeadSmallEggs`, each of
        which dies immediately and whose `SlowDeathBehavior` names the OCL that makes the actual
        Oathbreakers. Reading one hop answers "this power creates an egg", which is true and
        useless.

        Following the chain is what separates a summon from a bombardment, and the two really are
        the same module with different contents: Gondor's Arrow Volley is an `OCLSpecialPower`
        whose chain ends at `SpellBookBombardSeedGondor`, an `UNATTACKABLE` effect object that
        carries the weapon, while the Grey Company's ends at three battalions and two heroes.

        **Cycles are real, not hypothetical.** `OCL_SpawnEagles` recreates its own members, so
        this is both visited-guarded and depth-bounded; the guard is what makes the walk finite
        rather than a rule about how the data ought to look.
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

        Any module field whose name mentions an OCL counts, because the phase keyword sits in
        the value rather than the key (`OCL = FINAL OCL_Foo`) and the module families that carry
        one are not a closed set. Only tokens that name a real list are kept, which drops the
        `FINAL`/`MIDPOINT` phase words without needing to know them.
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

        **Needed to fire anything at all**, not merely to read the book: a cast whose source slot
        is 0 is consumed by the stream and discarded by logic, and one naming this object's live
        id works immediately. See `Session.cast`.

        Every seat carries exactly one, owned and at the world origin, so the live object is
        found by matching this template against the objects that seat owns.
        """
        block = self.faction_template(faction)
        if block is None:
            return ""
        return str(_fields(block).get("SpellBookMp", "")).strip()

    def spell_book(self, faction: str) -> tuple[CastablePower, ...]:
        """Every power a faction's spellbook can fire, in slot order - its `SpellBookMp`'s
        command set, joined to the module that implements each one.

        The casting counterpart of `spell_store`, and it has to be a separate walk rather than a
        field on the store's entries: the store's `PurchaseScienceCommandSetMP` and the book's
        command set are different lists of different lengths - Gondor sells 11 powers and its
        book shows 15 buttons, three of which are the view powers nobody buys.

        **The book is also what disambiguates the science.** `RequiredSciences` is one-to-many -
        `SCIENCE_RebuildMen` is required by both `SpellBookRebuild` and `SpellBookBelfalasGuards`,
        and `SCIENCE_GraueSchaar` by three sub-faction variants - so going science-first picks
        arbitrarily between powers the faction cannot all cast. Only one of each family is on the
        book, and that one is the answer.

        Powers whose module cannot be found are returned with `EFFECT_UNKNOWN` rather than
        dropped: a policy should be able to see that a slot exists and that nothing here can say
        what it does, which is a different fact from the slot not existing.
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

        Walks the parent chain because a faction's book is a `ChildObject` that overrides only
        the command set - `GondorSpellBook` restates nothing, and every module it uses belongs to
        `GoodSpellBook`. The parent therefore carries every good-faction power's module and the
        command set is what narrows those to the ones this faction can actually reach.
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

        The difference from `_spell_modules` is the whole reason heroes need their own walk. A
        spellbook implements a power in one module, so taking the first is taking the only one. A
        hero spreads each ability over two or three, and they carry different halves of the
        answer:

        | module | what it alone says |
        |---|---|
        | `UnpauseSpecialPowerUpgrade` | the level it opens at, and nothing else |
        | `SpecialPowerModule` | that it starts paused, sometimes the modifier |
        | `WeaponFireSpecialAbilityUpdate` | the weapon, and the range the caster closes to |
        | `HeroModeSpecialAbilityUpdate` | the modifier it puts on the caster |
        | `OCLSpecialPower` | what it summons |

        And the one declared first is almost always `UnpauseSpecialPowerUpgrade`, which says
        nothing about the effect at all. Measured before this was written: `_spell_modules` over
        the Men roster classified **every** ability `EFFECT_GRANT`, so `AIMABLE` filtered the
        whole roster out and a hero casting stage would have had nothing to fire, on any faction.

        Merging is safe because the fields are near-disjoint; the one that genuinely collides is
        `StartsPaused`, which is not read here - the unlock upgrade is what answers that question.

        Walks the parent chain like `_spell_modules`, for the same reason: an Edain hero is
        frequently a `ChildObject` of the vanilla one and restates only what it changes.
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

        The unit-scoped counterpart of `spell_book`, and the same three-part join: the command
        set says which buttons exist, the button says how the order is addressed, and the module
        on the object says what the power does. What differs is every one of those three sources
        and none of the shape.

        - **`SPECIAL_POWER`, not `SPELL_BOOK`.** The caster is the object rather than the
          player's book, which is also why `Session.cast` takes the hero's id as the source for a
          self or ground cast and 0 for an object cast - see `sage_live.api.orders.cast_at_object`,
          whose whole note was written against Faramir's Wound Arrow.
        - **Gated by a level, not by a science.** `unlocked_by` carries the `Upgrade_Level_N` the
          ability's `UnpauseSpecialPowerUpgrade` names, and the hero's own `GameObject.upgrades`
          answers it live.
        - **Merged modules.** See `_ability_modules` for why first-won classifies the entire
          roster as `EFFECT_GRANT`.

        **Two kinds of button are dropped and neither by name**, which is the same standard the
        spellbook's "the store never sold it" test meets: `NONPRESSABLE` is a portrait for a
        passive aura, and `TOGGLE_IMAGE_ON_WEAPONSET` is a mount or weapon swap. See
        `NOT_AN_ABILITY`.

        A power whose merged modules say nothing recognisable is returned rather than dropped, so
        a caller can see the ability exists and that nothing here can aim it. Measured on the Men
        roster, that is a large minority of the buttons: Boromir's Last Stand and Gandalf's
        Lightning Sword both carry a `SpecialPowerModule` saying only that the power starts
        paused, and deliver their effect somewhere this walk cannot follow. Both come back
        `EFFECT_GRANT` - the honest reading of "no heal, no modifier, no OCL and no weapon" - and
        that is a different statement from `EFFECT_UNKNOWN`, which means a chain *was* followed
        and named no side.
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
            # **A weapon pointed at a friend is not a strike, and the module cannot tell.** See
            # `TARGET_SIDE`: Beregond's `TalkToMe` abilities are the same
            # `WeaponFireSpecialAbilityUpdate` shape as Wizard Blast and target an ally, so the
            # module-only reading has four of his eight buttons down as attacks on our own side.
            # What they actually do is not in any field read here, so they are reported unknown -
            # a caller declines to fire what it cannot aim, which is the same answer `_classify`
            # gives an OCL chain that names no side.
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

        Six module shapes cover both books and the hero rosters, and each is read by the field
        that carries its meaning rather than by the module's class name - a mod is free to
        implement a buff through a class this has never heard of, and `AttributeModifier` still
        says what it is.

        **The last two exist for heroes and neither appears on a spellbook.** A hero implements an
        ability across two or three modules, so what is passed here is the *merge* of them - see
        `_ability_modules`, which is what makes reading a field enough.
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

            # **An egg can deliver its units through a `SpawnBehavior` rather than through another
            # OCL, and `creates` follows only the OCL half.** Beregond's level-1 summon is the
            # case: `OCL_SummonBeregondKompanie` makes one `BeregondKompanieObject`, an `INERT
            # UNATTACKABLE` marker with a 40-second lifetime and six `SpawnBehavior` modules that
            # put six citadel guards on the map. Read through the OCL alone it creates a piece of
            # scenery naming no side, which is `EFFECT_UNKNOWN` and therefore unaimable; read with
            # the spawns it is plainly a summon. This is the same reader `nests` uses to find what
            # a creep lair replaces its slaves from - a lair and a summon egg are the same module,
            # and only the lifetime tells them apart.
            #
            # **Last, and only for what neither branch above claimed, which is the whole of what
            # makes it safe.** Buildings spawn things too: a lair spawns slaves, Isengard's summoned
            # lumber mill spawns workers, and the Lone Tower spawns its guard. Asked before the
            # `built` test, this turned three correct `EFFECT_BUILD` powers into summons - and a
            # build is aimed at our own base while a summon is aimed at their army, so Untamed
            # Allegiance would have gone from placing lairs at home to placing them on the enemy.
            # Measured over all seven books: here, it changes nothing that was already classified.
            hatched = tuple(dict.fromkeys(t for made in spawns for t in self.spawns(made)))
            army = [t for t in hatched if self.kind_of(t) & SUMMON_KINDS]
            if army:
                return EFFECT_SUMMON, tuple(army), affects, 0.0
            # **What it puts down is neither a unit nor a building, and that alone does not say
            # whose side it is on.** Edain delivers friendly effects through the same shape as
            # hostile ones - `EndloseHordenPing` fires a weapon that hands every horde a banner,
            # and `BeistandinderNotNormalEgg` attaches itself to your own beacon and fires a
            # weapon from there - so "creates scenery carrying a weapon" describes a bombardment
            # and a blessing equally well.
            #
            # What does separate them is the relationship token on the filters those created
            # objects carry, so the chain is asked rather than the shape.
            #
            # **The whole filter is kept, not just the relationship word.** Those filters often
            # name the exact templates the power acts on - Gondor's Assistance in Time of Need
            # attaches to `+GondorLeuchtfeuer`, the signal fire - and a caller that knows only
            # "friendly" aims it at the nearest battalion, where there is no signal fire in
            # radius and the cast is refused. Measured live: three straight refusals reported
            # against "1 of ours" before the tokens were carried through.
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

        # **A weapon fired at whatever the button was pointed at**, which is the shape most of a
        # hero's offensive kit takes: Gandalf's Wizard Blast, his Istari Light and Faramir's Wound
        # Arrow are all `WeaponFireSpecialAbilityUpdate` with a `SpecialWeapon` and no OCL,
        # modifier or heal anywhere on them.
        #
        # Read as a strike because that is what firing a weapon at something does to it, and the
        # one shape in this tree that fires a weapon at a *friend* is not reached from here: the
        # errand rider's summons are a faction mechanic with its own module, and the rider is not
        # a hero. A future caller that points this at some other unit's weapon ability should
        # know that is the assumption being made.
        if fields.get(MODULE_WEAPON):
            return EFFECT_STRIKE, (), (), 0.0

        # No OCL, no modifier, no heal, no weapon: it changes the player rather than the map. A
        # granted upgrade (`PlayerUpgradeSpecialPower`) and a production bonus both land here.
        return EFFECT_GRANT, (), (), 0.0

    def _chain_filter(self, templates: Iterable[str]) -> frozenset[str]:
        """Every object-filter token carried by anything a power creates.

        Every filter on every module of every created object is read, because the field that
        carries the answer is not fixed: `AttachUpdate` calls it `ObjectFilter`, an aura calls it
        `AttributeModifierAffects`, and a mod may call it something else again. What they share
        is the engine's vocabulary - a relationship word, and the `+Template` and `+KINDOF`
        entries that say *what* is touched.

        Both halves matter to a caller. The relationship decides whose side the power is on;
        the named templates decide where it has to be pointed, because a power that attaches to
        one specific building is refused anywhere that building is not.
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

        **A buff is otherwise invisible after the fact.** An attribute modifier touches no field
        an observation carries, so "has this building already had it" has no direct answer - and
        a power on a three-minute recharge spent a second time on the same target is a charge
        thrown away. Where the modifier grants an upgrade, though, the target carries that
        upgrade in `GameObject.upgrades` forever after, and the question becomes a set test.

        The chain is walked rather than guessed, because it is longer than it looks. Gondor's
        Assistance in Time of Need goes power -> `OCL_BeistandinderNotNormalModifier` ->
        `BeistandinderNotNormalEgg`, which attaches itself to the signal fire and dies; its
        `SlowDeathBehavior` fires `BeistandinderNotNormalWeapon`, whose `AttributeModifierNugget`
        names `BeistandinderNotNormalModifier`, and only there does `Upgrade =
        Upgrade_SwitchToRockThrowing` appear. Four hops, none of which state the upgrade.

        **Tokens are matched against the indexes rather than against field names.** `AttachUpdate`
        names a weapon in `Weapon`, a slow death in `DeathWeapon`, a nugget names a modifier in
        `AttributeModifier` and a bonus names one in `BonusName` - so every token of every field
        is offered to `_weapons` and `_modifiers`, and a token those tables know is what it is.
        The same rule `filter_targets` uses to tell a template from a `KindOf`.

        **Only `Duration = 0` counts.** A timed modifier wears off, so its upgrade is a state the
        target leaves again and recasting is the whole point; treating it as a permanent mark
        would make a repeatable buff castable exactly once per target per match.
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
        """Every power a faction's spellbook sells, in slot order.

        The list is its `PurchaseScienceCommandSetMP` - the spell store's own palette.

        The same command-set rule the rest of this module obeys, applied to the one palette that
        hangs off the player rather than off an object: a button on this set is a button the
        spell store would have shown, so buying only from here is what keeps a policy playing
        the game a human plays.

        **`...MP`, not `PurchaseScienceCommandSet`.** A faction has two whole books and they are
        not the same list - Gondor's skirmish store leads with Rebuild and the campaign one does
        not exist for the same sub-faction at all.

        **Slots that sell nothing are dropped**, and by what the data says rather than by their
        name - see `PowerButton.purchasable`. Every store is padded to twenty with
        `Command_PurchaseSpellEmpty`, which is 8 of Gondor's 20 and 9 of Mordor's.

        **Edain's sub-factions are not resolved.** A `PlayerTemplate` names one store, and the
        mod swaps in another (`BelfalasSpellStoreCommandSet`, `MMGondorSpellStoreCommandSet`)
        when a match commits to a sub-faction - by script, which is not in this tree and is not
        readable off a live player either. So this is the faction's default book; a purchase
        from it is still legitimate, but a sub-faction's own row is invisible here.
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

        **Two hops, and neither can be skipped.** The purchase button names a *button*, not a
        power; that second button is what carries the `SpecialPower`. Reading `SpecialPower` off
        the purchase button itself finds nothing, which is how this went unnoticed - a passive
        looks like a power with no cast, rather than like a power whose cast was never sent.

        The triggered button is `NONPRESSABLE` and appears on no palette a player can reach, so
        it is deliberately not required to pass the command-set test the rest of this module
        applies. It is not a button anybody clicks; it is the other half of the one they did.
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

        `side` is the token a live observation reports in `PlayerState.faction` - `Men`, not
        `Gondor` and not `FactionMen` - which is the same string the definition's own `Side`
        field carries, so the two join directly. Matched on `Side` rather than on the block name
        because the names are decorative (`MenOfTheWestArmy`) and the `Side` is the key the
        engine itself picks a definition by.

        None is an ordinary answer, not a failure: a build may define no army for a playable
        side at all - the mounted RotWK+Edain install carries nine definitions and the mod's
        own overlay tree carries eleven, so `Arnor` and `Belfalas` resolve in one and not the
        other.
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

        An **enabled** slot serving an index outside the roster cannot be right: the positional
        rule has landed somewhere there is no hero, so this block does not line up and the
        heroes it appears to offer are fiction. Reported rather than resolved - a policy running
        without `godsight` should treat such a producer as unknown rather than trust it.

        Restricted to slots enabled with no upgrade held, because the permanently-gated
        `Command_FakeHeroReviveSlotN` fillers are not meant to line up with anything: they exist
        only to hold positions so the real buttons land in the right places.

        **Button names are deliberately not checked.** It is tempting - Edain appears to number
        these after the roster entry they serve - but `Command_GenericReviveSlot1` occurs at
        positions 0, 1, 3 and 4 in different sets, so its number identifies the button and not
        a hero. The names that *are* meaningful are the ones naming a hero outright
        (`Command_HaldirGenericReviveSlot`), and 220 of 231 of those land on their own roster
        entry - measured once, recorded in `sage_live.utils.heroes`, not re-derived here by guessing
        at hero names.
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
