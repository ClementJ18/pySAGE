"""Resolve a unit's current state from its active upgrades: engine-faithful evaluation over
the typed model, working out which templates the engine would currently use. Pure and
side-effect free, so the linter and UI share one implementation.

Upgrade-driven selections are modelled for ArmorSet, WeaponSet and LocomotorSet (the
flag-subset machinery below). On top sits the experience rank: the `ExperienceLevel`s whose
`TargetNames` name the object form its ladder; reaching a rank attains every level up to it,
each granting its `Upgrades` and `AttributeModifiers` — which feed back into the upgrade
machinery (`RankSelector`, `UnitState.set_rank`). Flags are compared as upper-case name
tokens, which sidesteps the partial flag enums and stays lossless.
"""

from sage_ini.model.behaviors import (
    ArmorUpgrade,
    AttributeModifierUpgrade,
    Body,
    CommandSetUpgrade,
    ContainBehavior,
    LevelUpUpgrade,
    LocomotorSetUpgrade,
    WeaponSetUpgrade,
)
from sage_ini.model.enums import ModifierType
from sage_ini.model.types import eval_number, to_number
from sage_ini.parser.ast import Attribute, Block

# An Armor/WeaponSetUpgrade with no explicit flag sets this one (engine default).
UPGRADE_DEFAULT_FLAG = "PLAYER_UPGRADE"
LOCOMOTOR_NORMAL = "SET_NORMAL"
LOCOMOTOR_UPGRADED = "SET_NORMAL_UPGRADED"
MAGIC_DAMAGE = "MAGIC"


def _climb(obj):
    """The object and its ChildObject parent chain (own value wins, else inherit)."""
    while obj is not None:
        yield obj
        obj = getattr(obj, "parent", None)


def _tokens(raw) -> list[str]:
    """Whitespace-split a raw field value (a string, or a list if repeated)."""
    if raw is None:
        return []
    values = raw if isinstance(raw, list) else [raw]
    out: list[str] = []
    for value in values:
        out.extend(str(value).split())
    return out


def _flags(raw) -> set[str]:
    """Upper-case flag tokens of a raw field, dropping the `None` default marker."""
    return {token.upper() for token in _tokens(raw) if token.upper() != "NONE"}


def _is_truthy(raw) -> bool:
    tokens = _tokens(raw)
    return bool(tokens) and tokens[-1].lower() in {"yes", "true", "1"}


def _group_sets(obj, group: str) -> list:
    """The object's (or nearest parent's) sets in a nested group (ArmorSet, ...)."""
    for owner in _climb(obj):
        sets = getattr(owner, group, None)
        if sets:
            return sets
    return []


def _is_active(module, active_upgrades: set[str]) -> bool:
    """Whether an upgrade behavior is currently triggered: no `ConflictsWith` upgrade is on
    and its triggers are satisfied (any `TriggeredBy`, or all with `RequiresAllTriggers`); a
    behavior with no triggers is always on."""
    if any(name in active_upgrades for name in _tokens(module._fields.get("ConflictsWith"))):
        return False
    triggers = _tokens(module._fields.get("TriggeredBy"))
    if not triggers:
        return True
    requires_all = _is_truthy(module._fields.get("RequiresAllTriggers"))
    check = all if requires_all else any
    return check(name in active_upgrades for name in triggers)


UPGRADE_FIELDS = ("TriggeredBy", "UpgradeRequired")


def find_upgrades(obj) -> list[str]:
    """Upgrade names this object can obtain, from every TriggeredBy/UpgradeRequired field in
    it (typed modules, sub-blocks and generic blocks), de-duplicated in first-seen order.
    Inherited modules count: a ChildObject's upgrades often live in the base template, so the
    parent chain is walked too."""
    names: list[str] = []

    def visit_typed(node) -> None:
        for key in UPGRADE_FIELDS:
            if key in node._fields:
                names.extend(_tokens(node._fields[key]))
        for module in node._modules:
            visit_typed(module)
        for items in node._nested_data.values():
            for item in items:
                visit_typed(item)
        for extra in node._extras:
            visit_block(extra)

    def visit_block(node) -> None:
        for child in getattr(node, "children", ()):
            if isinstance(child, Attribute) and child.key in UPGRADE_FIELDS:
                names.extend(_tokens(child.value))
            elif isinstance(child, Block):
                visit_block(child)

    for owner in _climb(obj):
        visit_typed(owner)
    seen, ordered = set(), []
    for name in names:
        if name not in seen:
            seen.add(name)
            ordered.append(name)
    return ordered


def has_kindof(obj, flag: str) -> bool:
    """Whether `obj`, or a template it inherits from, declares the KindOf `flag`. Matched as
    raw name tokens up the parent chain; a `#define` macro token (`HOBBIT_KINDOF`) is expanded
    so a kind contributed only through it is still recognised."""
    game = getattr(obj, "_game", None)
    for owner in _climb(obj):
        for token in _tokens(owner._fields.get("KindOf")):
            if token == flag:
                return True
            if game is not None and flag in str(game.get_macro(token)).split():
                return True
    return False


# Flag-subset selection (ArmorSet, WeaponSet)
def set_conditions(conditioned_set) -> set[str]:
    """The flags in a set's `Conditions` (`None` -> empty = the default set)."""
    return _flags(conditioned_set._fields.get("Conditions"))


def _select_by_flags(sets: list, active_flags: set[str]):
    """Among `sets`, the one whose `Conditions` are all active; most-specific
    (most flags) wins, the no-condition set is the default fallback."""
    best, best_specificity = None, -1
    for conditioned_set in sets:
        conditions = set_conditions(conditioned_set)
        if conditions <= active_flags and len(conditions) > best_specificity:
            best, best_specificity = conditioned_set, len(conditions)
    return best


def _upgrade_flags(obj, active_upgrades, behavior, flag_field, default=()) -> set[str]:
    """Union the flag set contributed by each active upgrade behavior of a type;
    a behavior whose `flag_field` is empty contributes `default` (engine default)."""
    flags: set[str] = set()
    for owner in _climb(obj):
        for module in owner.modules:
            if isinstance(module, behavior) and _is_active(module, active_upgrades):
                flags |= _flags(module._fields.get(flag_field)) or set(default)
    return flags


def active_armor_flags(obj, active_upgrades: set[str]) -> set[str]:
    # An ArmorUpgrade with no explicit ArmorSetFlag contributes PLAYER_UPGRADE
    # (the engine default), so a PLAYER_UPGRADE-conditioned ArmorSet is selected.
    return _upgrade_flags(
        obj, active_upgrades, ArmorUpgrade, "ArmorSetFlag", (UPGRADE_DEFAULT_FLAG,)
    )


def select_armor_set(obj, active_flags: set[str]):
    """The ArmorSet the engine would use under `active_flags` (or None)."""
    return _select_by_flags(_group_sets(obj, "ArmorSet"), active_flags)


def active_weapon_flags(obj, active_upgrades: set[str]) -> set[str]:
    return _upgrade_flags(
        obj, active_upgrades, WeaponSetUpgrade, "WeaponCondition", (UPGRADE_DEFAULT_FLAG,)
    )


def select_weapon_set(obj, active_flags: set[str]):
    """The WeaponSet the engine would use under `active_flags` (or None)."""
    return _select_by_flags(_group_sets(obj, "WeaponSet"), active_flags)


# Locomotor switch (SET_NORMAL <-> SET_NORMAL_UPGRADED)
def active_locomotor_condition(obj, active_upgrades: set[str]) -> str:
    """`SET_NORMAL_UPGRADED` while a LocomotorSetUpgrade is active, else
    `SET_NORMAL`; an active `KillLocomotorUpgrade` forces `SET_NORMAL`."""
    upgraded = False
    for owner in _climb(obj):
        for module in owner.modules:
            if isinstance(module, LocomotorSetUpgrade) and _is_active(module, active_upgrades):
                if _is_truthy(module._fields.get("KillLocomotorUpgrade")):
                    return LOCOMOTOR_NORMAL
                upgraded = True
    return LOCOMOTOR_UPGRADED if upgraded else LOCOMOTOR_NORMAL


def select_locomotor_set(obj, condition: str):
    """The LocomotorSet matching `condition`, falling back to `SET_NORMAL`."""
    by_condition: dict[str, object] = {}
    for locomotor_set in _group_sets(obj, "LocomotorSet"):
        tokens = _tokens(locomotor_set._fields.get("Condition"))
        if tokens:
            by_condition.setdefault(tokens[0].upper(), locomotor_set)
    return by_condition.get(condition) or by_condition.get(LOCOMOTOR_NORMAL)


# CommandSet — the button palette, replaced by an active CommandSetUpgrade
def _own_field(obj, field: str):
    """The nearest value of a raw field up the parent chain (own value wins)."""
    for owner in _climb(obj):
        raw = owner._fields.get(field)
        if raw is not None:
            return raw[-1] if isinstance(raw, list) else raw
    return None


def active_command_set_name(obj, active_upgrades: set[str]) -> str | None:
    """The CommandSet name the engine would show under the active upgrades: the object's own
    `CommandSet`, replaced by each active `CommandSetUpgrade` (last active wins). None when it
    defines no command set."""
    name = _own_field(obj, "CommandSet")
    for owner in _climb(obj):
        for module in owner.modules:
            if isinstance(module, CommandSetUpgrade) and _is_active(module, active_upgrades):
                raw = module._fields.get("CommandSet")
                if raw is not None:
                    name = raw[-1] if isinstance(raw, list) else raw
    return name


def select_command_set(obj, active_upgrades: set[str]):
    """The resolved `CommandSet` object for `obj` under the active upgrades."""
    name = active_command_set_name(obj, active_upgrades)
    if name is None:
        return None
    game = getattr(obj, "_game", None)
    if game is None:
        return None
    return game.tables.get("commandsets", {}).get(name)


def command_set_names(obj) -> list[str]:
    """Every CommandSet name `obj` can display — its own palette plus any a `CommandSetUpgrade`
    can swap in (active or not), in first-seen order. Used to find what an object can build, so
    every set it could ever show is included."""
    names: list[str] = []
    base = _own_field(obj, "CommandSet")
    if base is not None:
        names.append(base)
    for owner in _climb(obj):
        for module in owner.modules:
            if isinstance(module, CommandSetUpgrade):
                raw = module._fields.get("CommandSet")
                if raw is not None:
                    name = raw[-1] if isinstance(raw, list) else raw
                    if name not in names:
                        names.append(name)
    return names


# Hordes — a unit's cost often lives on the horde that fields it
def _tokens_each(raw) -> list[str]:
    """A repeated raw field's values as a list of strings (one string, or a list when the key
    repeated)."""
    if raw is None:
        return []
    return [str(v) for v in (raw if isinstance(raw, list) else [raw])]


def payload_members(module) -> list[str]:
    """The member object names a horde-contain module's `InitialPayload` lists. Each
    `InitialPayload = Member Count` line names one member; the count is ignored."""
    members: list[str] = []
    for entry in _tokens_each(module._fields.get("InitialPayload")):
        tokens = entry.split()
        if tokens:
            members.append(tokens[0])
    return members


def horde_members(obj) -> list[str]:
    """The distinct member object names `obj` fields through its horde-contain modules, in
    first-seen order (empty for a non-horde). A horde's combat stats live on these members."""
    members: list[str] = []
    for owner in _climb(obj):
        for module in owner.modules:
            if isinstance(module, ContainBehavior):
                for name in payload_members(module):
                    if name not in members:
                        members.append(name)
    return members


def horde_member_object(obj):
    """The first member object `obj` fields through its horde-contain modules, or None for a
    non-horde (or a horde whose members aren't loaded). A horde carries no combat stats or
    portrait of its own — both come from this contained unit."""
    game = getattr(obj, "_game", None)
    if game is None:
        return None
    for name in horde_members(obj):
        member = game.objects.get(name)
        if member is not None:
            return member
    return None


def hordes_containing(game, member_name: str) -> list:
    """Objects whose horde-contain module's `InitialPayload` names `member_name`, in
    object-table order. Many units are only built in a horde, so their cost sits on the
    containing horde rather than the member."""
    if game is None:
        return []
    hordes = []
    for obj in game.tables.get("objects", {}).values():
        for owner in _climb(obj):
            if any(
                isinstance(module, ContainBehavior) and member_name in payload_members(module)
                for module in owner.modules
            ):
                hordes.append(obj)
                break
    return hordes


# Attribute modifiers — AttributeModifierUpgrade grants a ModifierList
def _number(game, token: str):
    """A modifier value token (`200`, `20%`, or a #define macro) as a float."""
    resolved = game.get_macro(token) if game is not None else token
    try:
        return to_number(resolved)
    except (ValueError, TypeError):
        return None


def _number_attr(obj, name: str):
    """A numeric field of `obj`, or None if absent or non-numeric (`obj` may be None, so an
    AttributeError degrades to None too)."""
    try:
        value = getattr(obj, name)
    except (AttributeError, ValueError, KeyError, TypeError, IndexError):
        return None
    return float(value) if isinstance(value, (int, float)) else None


def _find_body(obj):
    for owner in _climb(obj):
        for module in owner.modules:
            if isinstance(module, Body):
                return module
    return None


def find_body(obj):
    """The `Body` module governing `obj` (own or inherited), or None — a build-shell object
    that only places `BuildVariations` has none, so None marks it as needing a variation."""
    return _find_body(obj)


def build_variations(obj) -> list[str]:
    """The object names a build shell's `BuildVariations` lists (the variation objects that
    carry the real Body/armor/behaviors), in order. Empty for an object that builds as itself."""
    return _tokens(_own_field(obj, "BuildVariations"))


def active_modifier_lists(obj, active_upgrades: set[str]) -> list:
    """ModifierLists granted by AttributeModifierUpgrades active under the upgrades."""
    lists = []
    for owner in _climb(obj):
        for module in owner.modules:
            if isinstance(module, AttributeModifierUpgrade) and _is_active(module, active_upgrades):
                raw = module._fields.get("AttributeModifier")
                name = raw[-1] if isinstance(raw, list) else raw
                modifier_list = module._game.tables.get("modifiers", {}).get(name)
                if modifier_list is not None:
                    lists.append(modifier_list)
    return lists


def _attribute_modifier_list(module):
    """The `ModifierList` an `AttributeModifierUpgrade` grants, or None."""
    raw = module._fields.get("AttributeModifier")
    name = raw[-1] if isinstance(raw, list) else raw
    game = getattr(module, "_game", None)
    if not name or game is None:
        return None
    return game.tables.get("modifiers", {}).get(name)


# Stat keys whose modifiers mark an AttributeModifierUpgrade as a "level" step
# (an economy building gains health and production as it is upgraded).
LEVEL_MODIFIER_KEYS = frozenset({"HEALTH", "PRODUCTION"})


def economy_level_upgrades(obj) -> list[str]:
    """The upgrades that step an economy building through its levels, in level order,
    deduplicated. Edain's economy buildings (Wirtschaftssystem 4.0) level from globally-researched
    upgrades: each level-granting upgrade triggers a `LevelUpUpgrade` (`LevelsToGain`/`LevelCap`)
    and a paired `AttributeModifierUpgrade` whose `ModifierList` carries the per-level HEALTH or
    PRODUCTION gain. Both signals are required:

    - the `AttributeModifierUpgrade` proves the per-level stats live on the object (not on a
      veterancy `ExperienceLevel` ladder — those go through `RankSelector` instead);
    - the `LevelUpUpgrade` proves the upgrade is a level step, not a one-off buff (a hero's gift
      grants only an `AttributeModifierUpgrade`, so it must not count as a level).

    Capped at the `LevelUpUpgrade`'s `LevelCap` (base level plus one step per upgrade). Empty for
    a non-economy or unleveled object."""
    level_triggers: set[str] = set()  # upgrades that grant a level (a LevelUpUpgrade trigger)
    cap: int | None = None  # the highest LevelCap, the building's level ceiling
    names: list[str] = []  # upgrades whose AttributeModifierUpgrade carries the per-level stats
    for owner in _climb(obj):
        for module in owner.modules:
            if isinstance(module, LevelUpUpgrade):
                level_triggers.update(_tokens(module._fields.get("TriggeredBy")))
                module_cap = _module_int(getattr(module, "_game", None), module, "LevelCap", None)
                if module_cap is not None:
                    cap = module_cap if cap is None else max(cap, module_cap)
                continue
            if not isinstance(module, AttributeModifierUpgrade):
                continue
            modifier_list = _attribute_modifier_list(module)
            if modifier_list is None:
                continue
            keys = {entry.Type.name for _ml, entry in _iter_modifiers([modifier_list])}
            if keys & LEVEL_MODIFIER_KEYS:
                triggers = _tokens(module._fields.get("TriggeredBy"))
                if triggers and triggers[0] not in names:
                    names.append(triggers[0])
    ordered = [name for name in names if name in level_triggers]
    if cap is not None:
        ordered = ordered[: max(cap - 1, 0)]  # base is level 1, +1 per upgrade, ceiling LevelCap
    return ordered


def modifier_entries(modifier_list) -> list[tuple[str, str, list[str]]]:
    """The (KEY, value, [extra tokens]) of each `Modifier =` line in one list — the public
    single-list view used to show what a ModifierList grants. KEY and the scoping damage types
    are enum names; value is the raw amount token (resolved for display by the caller)."""
    return [
        (entry.Type.name, entry.Value, [damage.name for damage in entry.DamageTypes])
        for _ml, entry in _iter_modifiers([modifier_list])
        if entry.Value is not None
    ]


def _iter_modifiers(modifier_lists):
    """Yield (modifier_list, ModifierEntry) per `Modifier =` line. A list whose `Modifier`
    field cannot be converted is skipped — a malformed line is the validate pass's concern."""
    for modifier_list in modifier_lists:
        try:
            entries = modifier_list.Modifier or []
        except (ValueError, KeyError, TypeError, IndexError):
            continue
        for entry in entries:
            yield modifier_list, entry


def modifier_sum(modifier_lists, name: str) -> float:
    """Additive total of a modifier (HEALTH, RANGE, VISION, ...) across the lists."""
    total = 0.0
    for _ml, entry in _iter_modifiers(modifier_lists):
        if entry.Type.name == name and entry.Amount is not None:
            total += entry.Amount
    return total


def modifier_product(modifier_lists, name: str) -> float:
    """Multiplicative product of a modifier (SPELL_DAMAGE) across the lists."""
    product = 1.0
    for _ml, entry in _iter_modifiers(modifier_lists):
        if entry.Type.name == name and entry.Amount is not None:
            product *= entry.Amount
    return product


# The engine's default cap on the summed ARMOR modifier bonus when GameData
# declares no `AttributeModifierArmorMaxBonus` (0.75 -> the +300% armor ceiling).
ARMOR_MAX_BONUS_DEFAULT = 0.75


def armor_scalar_bonus(modifier_lists, damage_type: str) -> float:
    """Sum of ARMOR modifier fractions applying to a damage type (untyped apply to all) — the
    bonus `v` the engine feeds into `1/(1-v)`. Clamped to the game's max bonus by
    `UnitState.armor_scalar` before it is applied."""
    total = 0.0
    for _ml, entry in _iter_modifiers(modifier_lists):
        if entry.Type is not ModifierType.ARMOR or entry.Amount is None:
            continue
        types = [damage.name for damage in entry.DamageTypes]
        if not types or damage_type.upper() in types:
            total += entry.Amount
    return total


def armor_max_bonus(game) -> float:
    """The cap on the summed ARMOR modifier bonus fraction — `GameData`'s
    `AttributeModifierArmorMaxBonus` (the +300% effective-armor ceiling), defaulting to
    `ARMOR_MAX_BONUS_DEFAULT` when none declares it."""
    if game is not None:
        for data in game.tables.get("gamedatas", {}).values():
            raw = data._fields.get("AttributeModifierArmorMaxBonus")
            if raw is None:
                continue
            value = raw[-1] if isinstance(raw, list) else raw
            number = _number(game, value)
            if number is not None:
                return number
    return ARMOR_MAX_BONUS_DEFAULT


# Experience ranks — ExperienceLevels grant upgrades and modifiers per rank
def expand_target_names(game, raw) -> set[str]:
    """The flattened set of object-template names an `ExperienceLevel.TargetNames` names (a
    token may be a `#define` list macro that expands to several)."""
    names: set[str] = set()
    for token in _tokens(raw):
        names.update(str(game.get_macro(token)).split())
    return names


def _level_number(game, level, field: str, default: float = 0.0) -> float:
    """A numeric field of a level (`Rank`, `RequiredExperience`), macros resolved."""
    raw = level._fields.get(field)
    if raw is None:
        return default
    value = raw[-1] if isinstance(raw, list) else raw
    try:
        return eval_number(game, value)
    except (ValueError, TypeError, KeyError):
        return default


def levels_for_names(game, names: set[str]) -> list:
    """The `ExperienceLevel`s targeting any of `names`, ordered by `RequiredExperience` then
    `Rank` so attainment is cumulative."""
    if game is None or not names:
        return []
    matched = [
        level
        for level in game.tables.get("levels", {}).values()
        if expand_target_names(game, level._fields.get("TargetNames")) & names
    ]
    matched.sort(
        key=lambda level: (
            _level_number(game, level, "RequiredExperience"),
            _level_number(game, level, "Rank"),
        )
    )
    return matched


def levels_for(game, obj) -> list:
    """The `ExperienceLevel`s targeting `obj` alone, ascending by required experience."""
    if game is None:
        return []
    return levels_for_names(game, {obj.name})


def level_upgrades(levels) -> set[str]:
    """Every upgrade name granted by `levels` (granting is permanent → cumulative)."""
    upgrades: set[str] = set()
    for level in levels:
        upgrades.update(_tokens(level._fields.get("Upgrades")))
    return upgrades


def level_modifier_lists(game, levels) -> list:
    """The `ModifierList`s named by the `AttributeModifiers` of `levels`."""
    lists = []
    for level in levels:
        for name in _tokens(level._fields.get("AttributeModifiers")):
            modifier_list = game.tables.get("modifiers", {}).get(name)
            if modifier_list is not None:
                lists.append(modifier_list)
    return lists


# LevelUpUpgrade — an acquired upgrade that raises veterancy rank (gain, capped)
def _module_int(game, module, field, default):
    """An integer field of a module (`LevelsToGain`, `LevelCap`), macros resolved."""
    raw = module._fields.get(field)
    if raw is None:
        return default
    value = raw[-1] if isinstance(raw, list) else raw
    try:
        return int(eval_number(game, value))
    except (ValueError, TypeError, KeyError):
        return default


def level_up_trigger_upgrades(obj) -> list[str]:
    """The upgrade names that trigger a `LevelUpUpgrade` on `obj` or its parents (acquiring one
    raises veterancy rank), surfaced as toggles. First-seen order, de-duplicated."""
    names: list[str] = []
    for owner in _climb(obj):
        for module in owner.modules:
            if isinstance(module, LevelUpUpgrade):
                for name in _tokens(module._fields.get("TriggeredBy")):
                    if name not in names:
                        names.append(name)
    return names


def level_up_rank_floor(obj, active_upgrades: set[str], base_rank):
    """The veterancy rank the active `LevelUpUpgrade`s raise `obj` to: each adds its
    `LevelsToGain` to the running rank, clamped to its `LevelCap`. Starts from `base_rank`,
    returned unchanged when none is active."""
    game = getattr(obj, "_game", None)
    rank = base_rank
    for owner in _climb(obj):
        for module in owner.modules:
            if isinstance(module, LevelUpUpgrade) and _is_active(module, active_upgrades):
                rank += _module_int(game, module, "LevelsToGain", 0)
                cap = _module_int(game, module, "LevelCap", None)
                if cap is not None:
                    rank = min(rank, cap)
    return rank


class RankSelector:
    """An object's experience-rank ladder (the `ExperienceLevel`s naming it, by required
    experience) and the grants of the chosen rank. Selecting a rank attains every level up to
    it, accumulating their `Upgrades`/`AttributeModifier`s. Starts at the lowest rank; `select`
    moves it, clamped to the ladder."""

    def __init__(self, obj, game=None, extra_targets=()):
        self.object = obj
        self.game = game if game is not None else getattr(obj, "_game", None)
        # The object's own ExperienceLevels win; a horde's (extra_targets) are consulted only
        # when the member has none, since unioning would double-count the shared per-rank bonuses.
        self.levels = levels_for_names(self.game, {obj.name})
        if not self.levels:
            names = {target.name for target in extra_targets if target is not None}
            self.levels = levels_for_names(self.game, names)
        self.index = 0 if self.levels else -1

    @property
    def ranks(self) -> list[float]:
        """The `Rank` value of each level on the ladder, ascending."""
        return [_level_number(self.game, level, "Rank") for level in self.levels]

    @property
    def min_rank(self):
        ranks = self.ranks
        return ranks[0] if ranks else None

    @property
    def max_rank(self):
        ranks = self.ranks
        return ranks[-1] if ranks else None

    @property
    def rank(self):
        """The currently selected rank, or `None` when the object has no levels."""
        if self.index < 0:
            return None
        return _level_number(self.game, self.levels[self.index], "Rank")

    @property
    def current_level(self):
        """The `ExperienceLevel` of the selected rank, or `None`."""
        return self.levels[self.index] if self.index >= 0 else None

    @property
    def required_experience(self):
        """The selected level's own `RequiredExperience` (an absolute threshold, not
        cumulative), or None."""
        level = self.current_level
        return _level_number(self.game, level, "RequiredExperience", None) if level else None

    @property
    def experience_award(self):
        """Experience granted to the killer when the unit dies at this level, or None."""
        level = self.current_level
        return _level_number(self.game, level, "ExperienceAward", None) if level else None

    @property
    def attained_levels(self) -> list:
        """Every level up to and including the selected rank."""
        return self.levels[: self.index + 1] if self.index >= 0 else []

    def select(self, rank) -> None:
        """Select the highest rank not exceeding `rank` (clamped to the ladder)."""
        if not self.levels:
            return
        chosen = 0
        for i, level in enumerate(self.levels):
            if _level_number(self.game, level, "Rank") <= rank:
                chosen = i
        self.index = chosen

    @property
    def granted_upgrades(self) -> set[str]:
        """Upgrade names granted by every attained level."""
        return level_upgrades(self.attained_levels)

    @property
    def modifier_lists(self) -> list:
        """`ModifierList`s applied by every attained level's `AttributeModifiers`."""
        return level_modifier_lists(self.game, self.attained_levels)


# State holder — the resolved view a caller mutates as upgrades toggle
class UnitState:
    """An object plus the upgrades active on it; reading a resolved property (`armor`,
    `weapon_set`, …) takes them into account. The active set combines directly-toggled
    upgrades (`set_upgrade`) and those granted by the current rank (`set_rank`) into
    `effective_upgrades`, which drives every selection.

    `rank_targets` names extra objects whose ExperienceLevels feed this unit's ladder (a
    horde fielding it), applying the horde's per-rank modifiers to the member's stats.
    """

    def __init__(self, obj, active_upgrades=(), rank=None, rank_targets=()):
        self.object = obj
        self.active_upgrades: set[str] = set(active_upgrades)
        # ModifierLists applied on top of the upgrade/rank ones (a toggled
        # SpecialPowerModule's AttributeModifier lands here).
        self.extra_modifiers: list = []
        self.ranks = RankSelector(obj, extra_targets=rank_targets)
        if rank is not None:
            self.ranks.select(rank)

    def set_upgrade(self, name: str, active: bool) -> None:
        if active:
            self.active_upgrades.add(name)
        else:
            self.active_upgrades.discard(name)

    @property
    def effective_upgrades(self) -> set[str]:
        """Directly-toggled upgrades plus those granted by the current rank."""
        return self.active_upgrades | self.ranks.granted_upgrades

    # experience rank
    @property
    def rank(self):
        return self.ranks.rank

    @property
    def min_rank(self):
        return self.ranks.min_rank

    @property
    def max_rank(self):
        return self.ranks.max_rank

    def set_rank(self, rank) -> None:
        """Select an experience rank; its level upgrades/modifiers apply at once."""
        self.ranks.select(rank)

    # armor
    @property
    def armor_flags(self) -> set[str]:
        return active_armor_flags(self.object, self.effective_upgrades)

    @property
    def armor_set(self):
        return select_armor_set(self.object, self.armor_flags)

    @property
    def armor(self):
        armor_set = self.armor_set
        return armor_set.Armor if armor_set is not None else None

    # weapon
    @property
    def weapon_flags(self) -> set[str]:
        return active_weapon_flags(self.object, self.effective_upgrades)

    @property
    def weapon_set(self):
        return select_weapon_set(self.object, self.weapon_flags)

    # locomotor
    @property
    def locomotor_condition(self) -> str:
        return active_locomotor_condition(self.object, self.effective_upgrades)

    @property
    def locomotor_set(self):
        return select_locomotor_set(self.object, self.locomotor_condition)

    @property
    def locomotor(self):
        locomotor_set = self.locomotor_set
        return locomotor_set.Locomotor if locomotor_set is not None else None

    @property
    def base_speed(self):
        """The active LocomotorSet's `Speed`, or None when it has no locomotor."""
        locomotor_set = self.locomotor_set
        if locomotor_set is None:
            return None
        try:
            return float(locomotor_set.Speed)
        except (AttributeError, ValueError, TypeError, KeyError):
            return None

    @property
    def speed_multiplier(self) -> float:
        """Movement-speed multiplier from the multiplicative SPEED modifiers."""
        return modifier_product(self.modifier_lists, "SPEED")

    @property
    def speed(self):
        """The active locomotor's speed scaled by the active SPEED modifiers."""
        base = self.base_speed
        return None if base is None else base * self.speed_multiplier

    # command set (button palette), swapped by an active CommandSetUpgrade
    @property
    def command_set(self):
        return select_command_set(self.object, self.effective_upgrades)

    # attribute modifiers (from active AttributeModifierUpgrades + the current rank)
    @property
    def modifier_lists(self) -> list:
        upgrade_lists = active_modifier_lists(self.object, self.effective_upgrades)
        return upgrade_lists + self.ranks.modifier_lists + self.extra_modifiers

    @property
    def base_max_health(self):
        return _number_attr(_find_body(self.object), "MaxHealth")

    @property
    def health_multiplier(self) -> float:
        """Max-health multiplier from the multiplicative HEALTH_MULT modifiers."""
        return modifier_product(self.modifier_lists, "HEALTH_MULT")

    @property
    def max_health(self):
        """Base MaxHealth plus the additive HEALTH modifiers, then scaled by HEALTH_MULT
        (the engine's additive-then-multiplicative order)."""
        base = self.base_max_health
        if base is None:
            return None
        return (base + modifier_sum(self.modifier_lists, "HEALTH")) * self.health_multiplier

    @property
    def base_vision(self):
        return _number_attr(self.object, "VisionRange")

    @property
    def vision(self):
        """Base VisionRange scaled by the additive VISION percentages."""
        base = self.base_vision
        return None if base is None else base * (1 + modifier_sum(self.modifier_lists, "VISION"))

    @property
    def range_multiplier(self) -> float:
        """Weapon-range multiplier from the additive RANGE percentages."""
        return 1 + modifier_sum(self.modifier_lists, "RANGE")

    @property
    def spell_damage_multiplier(self) -> float:
        """Magic-damage multiplier from the multiplicative SPELL_DAMAGE modifiers."""
        return modifier_product(self.modifier_lists, "SPELL_DAMAGE")

    @property
    def production_multiplier(self) -> float:
        """Resource-output multiplier from the multiplicative PRODUCTION modifiers — what
        makes a leveled economy building produce more at higher levels."""
        return modifier_product(self.modifier_lists, "PRODUCTION")

    @property
    def damage_add(self) -> float:
        """Flat per-hit weapon-damage bonus from additive DAMAGE_ADD modifiers."""
        return modifier_sum(self.modifier_lists, "DAMAGE_ADD")

    @property
    def damage_multiplier(self) -> float:
        """All-damage multiplier from the multiplicative DAMAGE_MULT modifiers."""
        return modifier_product(self.modifier_lists, "DAMAGE_MULT")

    def weapon_damage(self, base_damage, damage_type=None) -> float:
        """A damage nugget's per-hit output with the active modifiers: `DAMAGE_ADD` (flat),
        `DAMAGE_MULT` (all damage), then `SPELL_DAMAGE` (a further multiplier on MAGIC only)."""
        damage = (base_damage + self.damage_add) * self.damage_multiplier
        if damage_type is not None and str(damage_type).upper() == MAGIC_DAMAGE:
            damage *= self.spell_damage_multiplier
        return damage

    @property
    def armor_max_bonus(self) -> float:
        """The game's cap on the summed ARMOR modifier bonus."""
        return armor_max_bonus(getattr(self.object, "_game", None))

    def armor_scalar(self, damage_type: str, base_scalar: float) -> float:
        """A base armor coefficient (fraction of damage taken) with the active ARMOR modifiers
        applied: a bonus `v` (summed, then clamped to `armor_max_bonus`) scales the damage let
        through by `(1 - v)`, i.e. multiplies effective armor by `1/(1-v)`."""
        bonus = min(armor_scalar_bonus(self.modifier_lists, damage_type), self.armor_max_bonus)
        return base_scalar * (1 - bonus)
