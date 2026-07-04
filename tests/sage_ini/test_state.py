"""Unit-state resolution: active upgrades -> selected sets (sage_ini.model.state)."""

import pytest

import sage_ini.model.definitions  # noqa: F401  (register classes)
from sage_ini.model.game import Game
from sage_ini.model.state import (
    RankSelector,
    UnitState,
    active_armor_flags,
    active_command_set_name,
    active_locomotor_condition,
    active_weapon_flags,
    expand_target_names,
    hordes_containing,
    levels_for,
    modifier_entries,
    payload_members,
    select_armor_set,
    select_command_set,
    select_locomotor_set,
    select_weapon_set,
    set_conditions,
)
from sage_ini.parser.blockparser import parse

FIXTURE = """
Armor BaseArmor
  Armor = DEFAULT 100%
End
Armor HeavyArmor
  Armor = DEFAULT 50%
End
Armor MountedArmor
  Armor = DEFAULT 40%
End

Object TestUnit
  ArmorSet
    Conditions = None
    Armor = BaseArmor
  End
  ArmorSet
    Conditions = PLAYER_UPGRADE
    Armor = HeavyArmor
  End
  ArmorSet
    Conditions = PLAYER_UPGRADE MOUNTED
    Armor = MountedArmor
  End
  Behavior = ArmorUpgrade ModuleTag_Heavy
    TriggeredBy = Upgrade_Heavy
    ArmorSetFlag = PLAYER_UPGRADE
  End
  Behavior = ArmorUpgrade ModuleTag_Mount
    TriggeredBy = Upgrade_Mount
    ArmorSetFlag = MOUNTED
  End

  WeaponSet
    Conditions = None
    Weapon = PRIMARY BaseSword
  End
  WeaponSet
    Conditions = PLAYER_UPGRADE
    Weapon = PRIMARY UpgradedSword
  End
  Behavior = WeaponSetUpgrade ModuleTag_Forge
    TriggeredBy = Upgrade_Forge
  End

  LocomotorSet
    Locomotor = NormalLoco
    Condition = SET_NORMAL
    Speed = 50
  End
  LocomotorSet
    Locomotor = UpgradedLoco
    Condition = SET_NORMAL_UPGRADED
    Speed = 70
  End
  Behavior = LocomotorSetUpgrade ModuleTag_Loco
    TriggeredBy = Upgrade_Deploy
  End
End

Weapon BaseSword
  PrimaryDamage = 10
End
Weapon UpgradedSword
  PrimaryDamage = 25
End
Locomotor NormalLoco
  Speed = 50
End
Locomotor UpgradedLoco
  Speed = 70
End
"""


def load(text: str) -> Game:
    game = Game()
    result = parse(text, file="t.ini")
    assert not result.diagnostics
    game.load_document(result.document)
    return game


def unit():
    return load(FIXTURE).objects["TestUnit"]


def test_armor_set_conditions_parsing():
    obj = unit()
    conditions = [set_conditions(s) for s in obj.ArmorSet]
    assert conditions == [set(), {"PLAYER_UPGRADE"}, {"PLAYER_UPGRADE", "MOUNTED"}]


def test_default_armor_set_when_no_upgrades():
    assert select_armor_set(unit(), set()).Armor.name == "BaseArmor"


def test_armor_upgrade_selects_flagged_set():
    obj = unit()
    flags = active_armor_flags(obj, {"Upgrade_Heavy"})
    assert flags == {"PLAYER_UPGRADE"}
    assert select_armor_set(obj, flags).Armor.name == "HeavyArmor"


def test_most_specific_armor_set_wins():
    obj = unit()
    flags = active_armor_flags(obj, {"Upgrade_Heavy", "Upgrade_Mount"})
    assert flags == {"PLAYER_UPGRADE", "MOUNTED"}
    assert select_armor_set(obj, flags).Armor.name == "MountedArmor"


def test_armor_upgrade_without_flag_defaults_to_player_upgrade():
    # An ArmorUpgrade with no ArmorSetFlag contributes PLAYER_UPGRADE (the engine
    # default), so a PLAYER_UPGRADE-conditioned ArmorSet is selected — the
    # GondorArcher heavy-armor case.
    game = load(
        """
Armor LightArmor
  Armor = DEFAULT 100%
End
Armor PlateArmor
  Armor = DEFAULT 50%
End
Object Archer
  ArmorSet
    Conditions = None
    Armor = LightArmor
  End
  ArmorSet
    Conditions = PLAYER_UPGRADE
    Armor = PlateArmor
  End
  Behavior = ArmorUpgrade ModuleTag_Heavy
    TriggeredBy = Upgrade_HeavyArmor
  End
End
"""
    )
    obj = game.objects["Archer"]
    assert select_armor_set(obj, active_armor_flags(obj, set())).Armor.name == "LightArmor"
    flags = active_armor_flags(obj, {"Upgrade_HeavyArmor"})
    assert flags == {"PLAYER_UPGRADE"}
    assert select_armor_set(obj, flags).Armor.name == "PlateArmor"


def test_default_weapon_set_when_no_upgrades():
    weapon_set = select_weapon_set(unit(), set())
    assert weapon_set.Weapon[0][1].name == "BaseSword"


def test_weapon_set_upgrade_defaults_to_player_upgrade_flag():
    obj = unit()
    # WeaponSetUpgrade writes no WeaponCondition, so the engine default applies.
    flags = active_weapon_flags(obj, {"Upgrade_Forge"})
    assert flags == {"PLAYER_UPGRADE"}
    weapon_set = select_weapon_set(obj, flags)
    assert weapon_set.Weapon[0][1].name == "UpgradedSword"


def test_default_locomotor_is_normal():
    obj = unit()
    assert active_locomotor_condition(obj, set()) == "SET_NORMAL"
    assert select_locomotor_set(obj, "SET_NORMAL").Locomotor.name == "NormalLoco"


def test_locomotor_set_upgrade_switches_to_upgraded():
    obj = unit()
    assert active_locomotor_condition(obj, {"Upgrade_Deploy"}) == "SET_NORMAL_UPGRADED"
    state = UnitState(obj, {"Upgrade_Deploy"})
    assert state.locomotor.name == "UpgradedLoco"


def test_kill_locomotor_upgrade_reverts_to_normal():
    text = """
Object Reverter
  LocomotorSet
    Locomotor = N
    Condition = SET_NORMAL
    Speed = 10
  End
  LocomotorSet
    Locomotor = U
    Condition = SET_NORMAL_UPGRADED
    Speed = 20
  End
  Behavior = LocomotorSetUpgrade ModuleTag_On
    TriggeredBy = Upgrade_On
  End
  Behavior = LocomotorSetUpgrade ModuleTag_Off
    TriggeredBy = Upgrade_Off
    KillLocomotorUpgrade = Yes
  End
End
Locomotor N
  Speed = 10
End
Locomotor U
  Speed = 20
End
"""
    obj = load(text).objects["Reverter"]
    assert active_locomotor_condition(obj, {"Upgrade_On"}) == "SET_NORMAL_UPGRADED"
    # the kill upgrade reverts even with the on-upgrade also active
    assert active_locomotor_condition(obj, {"Upgrade_On", "Upgrade_Off"}) == "SET_NORMAL"


def test_unit_state_toggle_reresolves_all():
    state = UnitState(unit())
    assert state.armor.name == "BaseArmor"
    assert state.weapon_set.Weapon[0][1].name == "BaseSword"
    assert state.locomotor.name == "NormalLoco"

    state.set_upgrade("Upgrade_Heavy", True)
    state.set_upgrade("Upgrade_Forge", True)
    state.set_upgrade("Upgrade_Deploy", True)
    assert state.armor.name == "HeavyArmor"
    assert state.weapon_set.Weapon[0][1].name == "UpgradedSword"
    assert state.locomotor.name == "UpgradedLoco"

    state.set_upgrade("Upgrade_Forge", False)
    assert state.weapon_set.Weapon[0][1].name == "BaseSword"


MODIFIER_FIXTURE = """
ModifierList HeroBuff
  Modifier = HEALTH 200
  Modifier = RANGE 20%
  Modifier = VISION 100%
  Modifier = SPELL_DAMAGE 150%
  Modifier = DAMAGE_ADD 5
  Modifier = DAMAGE_MULT 150%
  Modifier = ARMOR 50%
  Modifier = ARMOR 25% PIERCE
End
Object Hero
  VisionRange = 100
  Behavior = ActiveBody ModuleTag_Body
    MaxHealth = 500
  End
  Behavior = AttributeModifierUpgrade ModuleTag_Buff
    TriggeredBy = Upgrade_Buff
    AttributeModifier = HeroBuff
  End
End
"""


def hero(active=()):
    return UnitState(load(MODIFIER_FIXTURE).objects["Hero"], active)


def test_modifiers_inactive_without_upgrade():
    s = hero()
    assert s.max_health == 500
    assert s.vision == 100
    assert s.range_multiplier == 1.0
    assert s.spell_damage_multiplier == 1.0
    assert s.armor_scalar("DEFAULT", 1.0) == 1.0


def test_health_modifier_is_additive():
    assert hero({"Upgrade_Buff"}).max_health == 700  # 500 + 200


HEALTH_MULT_FIXTURE = """
ModifierList HealthBuff
  Modifier = HEALTH 100
  Modifier = HEALTH_MULT 150%
End
Object Hero
  Behavior = ActiveBody ModuleTag_Body
    MaxHealth = 500
  End
  Behavior = AttributeModifierUpgrade ModuleTag_Buff
    TriggeredBy = Upgrade_Buff
    AttributeModifier = HealthBuff
  End
End
"""


def test_health_mult_scales_after_additive():
    obj = load(HEALTH_MULT_FIXTURE).objects["Hero"]
    assert UnitState(obj).max_health == 500  # no modifier, no multiplier
    # additive HEALTH applied first, then the HEALTH_MULT factor: (500 + 100) * 1.5
    assert UnitState(obj, {"Upgrade_Buff"}).max_health == 900


SPEED_PRODUCTION_FIXTURE = """
ModifierList Tier2
  Modifier = SPEED 125%
  Modifier = PRODUCTION 130%
End
Locomotor FootLoco
  Speed = 40
End
Object EconomyBuilding
  Behavior = LocomotorSet ModuleTag_Loco
    Locomotor = FootLoco
    Condition = SET_NORMAL
    Speed = 40
  End
  Behavior = TerrainResourceBehavior ModuleTag_Money
    MaxIncome = 40
    IncomeInterval = 12000
  End
  Behavior = AttributeModifierUpgrade ModuleTag_Tier2
    TriggeredBy = Upgrade_Tier2
    AttributeModifier = Tier2
  End
End
"""


def _econ(active=()):
    return UnitState(load(SPEED_PRODUCTION_FIXTURE).objects["EconomyBuilding"], active)


def test_speed_is_multiplicative():
    assert _econ().speed == 40  # no modifier
    assert _econ().speed_multiplier == 1.0
    s = _econ({"Upgrade_Tier2"})
    assert s.speed_multiplier == 1.25
    assert s.speed == 50  # 40 * 1.25


def test_production_is_multiplicative():
    assert _econ().production_multiplier == 1.0
    assert _econ({"Upgrade_Tier2"}).production_multiplier == 1.3


# A modifier list whose percentage is written as a detached `%` token (`PRODUCTION 1.25 %`),
# the way Edain's economy-level bonuses are. The whole list used to be dropped — `%` was read
# as a damage type and the conversion raised — so the building gained none of its bonuses.
DETACHED_PERCENT_FIXTURE = """
ModifierList EconBonus
  Modifier = PRODUCTION 1.25 %
  Modifier = HEALTH 500
  Modifier = ARMOR 50 % PIERCE
End
Object EconBuilding
  Behavior = ActiveBody ModuleTag_Body
    MaxHealth = 2500
  End
  Behavior = TerrainResourceBehavior ModuleTag_Money
    MaxIncome = 28
    IncomeInterval = 12000
  End
  Behavior = AttributeModifierUpgrade ModuleTag_Bonus
    TriggeredBy = Upgrade_Bonus
    AttributeModifier = EconBonus
  End
End
"""


def test_detached_percent_modifier_is_read_as_a_plain_multiplier():
    state = UnitState(load(DETACHED_PERCENT_FIXTURE).objects["EconBuilding"], {"Upgrade_Bonus"})
    # The detached `%` is ignored, so the multiplier is the plain 1.25 (a 25% boost), not
    # 0.0125; the additive HEALTH bonus applies alongside it.
    assert state.production_multiplier == 1.25
    assert state.max_health == 3000  # 2500 + HEALTH 500


def test_detached_percent_does_not_swallow_a_following_damage_type():
    game = load(DETACHED_PERCENT_FIXTURE)
    entries = modifier_entries(game.modifiers["EconBonus"])
    # All three modifiers survive (none dropped by a parse error), and the `PIERCE` after the
    # detached `%` is kept as the ARMOR modifier's damage type, not consumed by the `%`.
    assert [(name, types) for name, _value, types in entries] == [
        ("PRODUCTION", []),
        ("HEALTH", []),
        ("ARMOR", ["PIERCE"]),
    ]


def test_vision_and_range_are_additive_percentages():
    s = hero({"Upgrade_Buff"})
    assert s.vision == 200  # 100 * (1 + 1.00)
    assert s.range_multiplier == 1.2  # 1 + 0.20


def test_spell_damage_is_multiplicative():
    assert hero({"Upgrade_Buff"}).spell_damage_multiplier == 1.5


def test_weapon_damage_applies_add_and_mult():
    s = hero({"Upgrade_Buff"})
    assert s.damage_add == 5
    assert s.damage_multiplier == 1.5
    # (base 20 + 5) * 1.5 = 37.5 for a non-magic nugget
    assert s.weapon_damage(20, "SLASH") == 37.5
    # magic also takes the 1.5 SPELL_DAMAGE multiplier: 37.5 * 1.5 = 56.25
    assert s.weapon_damage(20, "MAGIC") == 56.25


def test_weapon_damage_is_identity_without_modifiers():
    assert hero().weapon_damage(20, "SLASH") == 20
    assert hero().weapon_damage(20, "MAGIC") == 20


def test_armor_modifier_scales_multiplicatively_and_is_type_specific():
    s = hero({"Upgrade_Buff"})
    # An ARMOR modifier scales the coefficient by (1 - bonus), not base - bonus;
    # with a non-unit base the two differ. Untyped 50% -> *0.5.
    assert s.armor_scalar("DEFAULT", 0.8) == pytest.approx(0.4)
    # Untyped 50% + PIERCE 25% = 0.75 bonus -> *0.25.
    assert s.armor_scalar("PIERCE", 0.8) == pytest.approx(0.2)
    # A base of 1.0 is the one case where subtractive and multiplicative agree.
    assert s.armor_scalar("DEFAULT", 1.0) == pytest.approx(0.5)


ARMOR_CAP_FIXTURE = """
ModifierList BigArmor
  Modifier = ARMOR 90%
End
Object Tank
  Behavior = AttributeModifierUpgrade ModuleTag_Buff
    TriggeredBy = Upgrade_Buff
    AttributeModifier = BigArmor
  End
End
"""


def test_armor_bonus_clamped_to_default_max():
    # ARMOR 90% exceeds the 75% default ceiling, so the bonus clamps: *0.25.
    tank = UnitState(load(ARMOR_CAP_FIXTURE).objects["Tank"], {"Upgrade_Buff"})
    assert tank.armor_max_bonus == pytest.approx(0.75)
    assert tank.armor_scalar("DEFAULT", 1.0) == pytest.approx(0.25)


def test_gamedata_overrides_armor_max_bonus():
    # GameData can raise or lower the ceiling; 60% here clamps the 90% to *0.4.
    game = load(ARMOR_CAP_FIXTURE + "\nGameData\n  AttributeModifierArmorMaxBonus = 60%\nEnd\n")
    tank = UnitState(game.objects["Tank"], {"Upgrade_Buff"})
    assert tank.armor_max_bonus == pytest.approx(0.6)
    assert tank.armor_scalar("DEFAULT", 1.0) == pytest.approx(0.4)


def test_conflicts_with_blocks_activation():
    text = """
Object Guarded
  ArmorSet
    Conditions = None
    Armor = A
  End
  ArmorSet
    Conditions = PLAYER_UPGRADE
    Armor = B
  End
  Behavior = ArmorUpgrade ModuleTag_X
    TriggeredBy = Upgrade_On
    ConflictsWith = Upgrade_Block
    ArmorSetFlag = PLAYER_UPGRADE
  End
End
Armor A
  Armor = DEFAULT 100%
End
Armor B
  Armor = DEFAULT 50%
End
"""
    obj = load(text).objects["Guarded"]
    assert active_armor_flags(obj, {"Upgrade_On"}) == {"PLAYER_UPGRADE"}
    assert active_armor_flags(obj, {"Upgrade_On", "Upgrade_Block"}) == set()


LEVEL_FIXTURE = """
#define HEROES TestHero AnotherHero

ModifierList Rank2Bonus
  Modifier = HEALTH 100
End
ModifierList Rank3Bonus
  Modifier = HEALTH 200
  Modifier = VISION 50%
End

ExperienceLevel HeroLevel3
  TargetNames = TestHero
  RequiredExperience = 3
  Rank = 3
  Upgrades = Upgrade_Level3
  AttributeModifiers = Rank3Bonus
End
ExperienceLevel HeroLevel1
  TargetNames = TestHero
  RequiredExperience = 1
  Rank = 1
  Upgrades = Upgrade_Level1
End
ExperienceLevel HeroLevel2
  TargetNames = HEROES
  RequiredExperience = 2
  Rank = 2
  Upgrades = Upgrade_Level2
  AttributeModifiers = Rank2Bonus
End

Object TestHero
  VisionRange = 100
  Behavior = ActiveBody ModuleTag_Body
    MaxHealth = 1000
  End
  ArmorSet
    Conditions = None
    Armor = WeakArmor
  End
  ArmorSet
    Conditions = VETERAN
    Armor = StrongArmor
  End
  Behavior = ArmorUpgrade ModuleTag_Vet
    TriggeredBy = Upgrade_Level3
    ArmorSetFlag = VETERAN
  End
End
Armor WeakArmor
  Armor = DEFAULT 100%
End
Armor StrongArmor
  Armor = DEFAULT 50%
End
"""


def level_game() -> Game:
    return load(LEVEL_FIXTURE)


def hero_obj():
    return level_game().objects["TestHero"]


def test_target_name_macro_expands_to_object_names():
    game = level_game()
    level = game.levels["HeroLevel2"]
    names = expand_target_names(game, level._fields.get("TargetNames"))
    assert names == {"TestHero", "AnotherHero"}


def test_levels_for_orders_by_experience():
    game = level_game()
    obj = game.objects["TestHero"]
    # HeroLevel2 targets TestHero only through the HEROES macro.
    assert [level.name for level in levels_for(game, obj)] == [
        "HeroLevel1",
        "HeroLevel2",
        "HeroLevel3",
    ]


def test_rank_ladder_min_max_and_default():
    selector = RankSelector(hero_obj())
    assert selector.min_rank == 1
    assert selector.max_rank == 3
    assert selector.rank == 1  # starts at the lowest rank


def test_rank_clamps_to_ladder():
    selector = RankSelector(hero_obj())
    selector.select(99)
    assert selector.rank == 3
    selector.select(0)
    assert selector.rank == 1


def test_object_without_levels_has_empty_ladder():
    selector = RankSelector(unit())
    assert selector.min_rank is None
    assert selector.rank is None
    selector.select(2)  # no-op, must not raise
    assert selector.granted_upgrades == set()


def test_rank_grants_upgrades_cumulatively():
    state = UnitState(hero_obj())
    assert state.effective_upgrades == {"Upgrade_Level1"}
    state.set_rank(3)
    assert state.effective_upgrades == {"Upgrade_Level1", "Upgrade_Level2", "Upgrade_Level3"}
    state.set_rank(2)
    assert state.effective_upgrades == {"Upgrade_Level1", "Upgrade_Level2"}


def test_rank_applies_level_modifiers_cumulatively():
    state = UnitState(hero_obj())
    assert state.max_health == 1000  # rank 1: no modifiers
    state.set_rank(2)
    assert state.max_health == 1100  # + Rank2Bonus HEALTH 100
    state.set_rank(3)
    assert state.max_health == 1300  # + Rank2 (100) + Rank3 (200)
    assert state.vision == 150  # base 100 * (1 + Rank3Bonus VISION 50%)


def test_rank_upgrade_fires_armor_trigger():
    state = UnitState(hero_obj())
    assert state.armor.name == "WeakArmor"
    state.set_rank(3)  # grants Upgrade_Level3, which triggers the VETERAN ArmorUpgrade
    assert state.armor_flags == {"VETERAN"}
    assert state.armor.name == "StrongArmor"


def test_rank_argument_to_unit_state():
    state = UnitState(hero_obj(), rank=3)
    assert state.rank == 3
    assert state.armor.name == "StrongArmor"


# A horde carries the experience levels for the group; the contained member has
# none of its own, so its ladder (and the rank modifiers) must come from the horde.
HORDE_LEVEL_FIXTURE = """
ModifierList HordeRank2Bonus
  Modifier = HEALTH 300
End
ExperienceLevel HordeLevel1
  TargetNames = FighterHorde
  RequiredExperience = 0
  Rank = 1
End
ExperienceLevel HordeLevel2
  TargetNames = FighterHorde
  RequiredExperience = 100
  Rank = 2
  AttributeModifiers = HordeRank2Bonus
End
Object Fighter
  Behavior = ActiveBody ModuleTag_Body
    MaxHealth = 200
  End
End
Object FighterHorde
  Behavior = HordeContain ModuleTag_Horde
    InitialPayload = Fighter 10
  End
End
"""


def test_member_has_no_levels_without_the_horde():
    game = load(HORDE_LEVEL_FIXTURE)
    member = game.objects["Fighter"]
    # On its own the member is unranked — the levels target only the horde.
    assert UnitState(member).ranks.levels == []


def test_horde_levels_rank_and_modify_the_member():
    game = load(HORDE_LEVEL_FIXTURE)
    member = game.objects["Fighter"]
    horde = game.objects["FighterHorde"]
    state = UnitState(member, rank_targets=[horde])
    # The horde's ladder is now the member's, and its rank modifiers reach the unit.
    assert [level.name for level in state.ranks.levels] == ["HordeLevel1", "HordeLevel2"]
    assert state.max_health == 200  # rank 1: no modifiers
    state.set_rank(2)
    assert state.max_health == 500  # + HordeRank2Bonus HEALTH 300


# A member that runs its own parallel ladder must NOT also inherit the horde's
# (most do — both reference the same bonus lists, so unioning would double-count).
OWN_AND_HORDE_LEVEL_FIXTURE = """
ModifierList SharedRank2Bonus
  Modifier = HEALTH 300
End
ExperienceLevel MemberLevel1
  TargetNames = Fighter
  RequiredExperience = 0
  Rank = 1
End
ExperienceLevel MemberLevel2
  TargetNames = Fighter
  RequiredExperience = 100
  Rank = 2
  AttributeModifiers = SharedRank2Bonus
End
ExperienceLevel HordeLevel2
  TargetNames = FighterHorde
  RequiredExperience = 100
  Rank = 2
  AttributeModifiers = SharedRank2Bonus
End
Object Fighter
  Behavior = ActiveBody ModuleTag_Body
    MaxHealth = 200
  End
End
Object FighterHorde
  Behavior = HordeContain ModuleTag_Horde
    InitialPayload = Fighter 10
  End
End
"""


def test_own_ladder_takes_precedence_over_the_horde():
    game = load(OWN_AND_HORDE_LEVEL_FIXTURE)
    member = game.objects["Fighter"]
    horde = game.objects["FighterHorde"]
    state = UnitState(member, rank_targets=[horde])
    # Only the member's own levels — the horde's identical bonus is not stacked.
    assert [level.name for level in state.ranks.levels] == ["MemberLevel1", "MemberLevel2"]
    state.set_rank(2)
    assert state.max_health == 500  # 200 + 300 once, not + 600


def test_direct_and_rank_upgrades_combine():
    state = UnitState(hero_obj(), active_upgrades={"Upgrade_Manual"})
    state.set_rank(2)
    assert state.effective_upgrades == {"Upgrade_Manual", "Upgrade_Level1", "Upgrade_Level2"}


XP_FIXTURE = """
ExperienceLevel SoldierVeteran
  TargetNames = Soldier
  RequiredExperience = 100
  Rank = 2
  ExperienceAward = 20
End
ExperienceLevel SoldierRecruit
  TargetNames = Soldier
  RequiredExperience = 0
  Rank = 1
  ExperienceAward = 10
End
ExperienceLevel SoldierElite
  TargetNames = Soldier
  RequiredExperience = 300
  Rank = 3
  ExperienceAward = 40
End

Object Soldier
End
"""


def soldier_ranks() -> RankSelector:
    return RankSelector(load(XP_FIXTURE).objects["Soldier"])


def test_required_experience_is_the_levels_own_value_not_cumulative():
    selector = soldier_ranks()
    assert selector.required_experience == 0  # starts at the lowest rank
    selector.select(2)
    assert selector.required_experience == 100  # the level's own threshold, not 0+100
    selector.select(3)
    assert selector.required_experience == 300  # not 0+100+300


def test_experience_award_is_per_level():
    selector = soldier_ranks()
    assert selector.experience_award == 10
    selector.select(2)
    assert selector.experience_award == 20
    selector.select(3)
    assert selector.experience_award == 40


def test_rank_experience_is_none_without_levels():
    selector = RankSelector(unit())  # TestUnit has no ExperienceLevels
    assert selector.required_experience is None
    assert selector.experience_award is None


COMMANDSET_FIXTURE = """
CommandSet UnitCommandSet
  1 = Command_Attack
  2 = Command_Stop
End
CommandSet UnitUpgradedCommandSet
  1 = Command_Attack
  2 = Command_SpecialShot
  3 = Command_Stop
End

CommandButton Command_Attack
  TextLabel = CONTROLBAR:Attack
End
CommandButton Command_Stop
  TextLabel = CONTROLBAR:Stop
End
CommandButton Command_SpecialShot
  TextLabel = CONTROLBAR:SpecialShot
  DescriptLabel = CONTROLBAR:ToolTipSpecialShot
End

Object Trooper
  CommandSet = UnitCommandSet
  Behavior = CommandSetUpgrade ModuleTag_Special
    TriggeredBy = Upgrade_Special
    CommandSet = UnitUpgradedCommandSet
  End
End

Object NoCommands
End
"""


def commandset_game() -> Game:
    return load(COMMANDSET_FIXTURE)


def trooper():
    return commandset_game().objects["Trooper"]


def test_default_command_set_when_no_upgrade():
    obj = trooper()
    assert active_command_set_name(obj, set()) == "UnitCommandSet"
    command_set = select_command_set(obj, set())
    assert [b.name for b in command_set.as_list()] == ["Command_Attack", "Command_Stop"]


def test_command_set_upgrade_swaps_the_palette():
    obj = trooper()
    assert active_command_set_name(obj, {"Upgrade_Special"}) == "UnitUpgradedCommandSet"
    command_set = select_command_set(obj, {"Upgrade_Special"})
    assert [b.name for b in command_set.as_list()] == [
        "Command_Attack",
        "Command_SpecialShot",
        "Command_Stop",
    ]


def test_command_set_via_unit_state_tracks_upgrades():
    state = UnitState(trooper())
    assert state.command_set.name == "UnitCommandSet"
    state.set_upgrade("Upgrade_Special", True)
    assert state.command_set.name == "UnitUpgradedCommandSet"


def test_object_without_command_set_has_none():
    obj = commandset_game().objects["NoCommands"]
    assert active_command_set_name(obj, set()) is None
    assert select_command_set(obj, set()) is None


HORDE_FIXTURE = """
#define GOOD_MEN_HORDE_SIZE 8

Object RohanArcherHorde
  BuildCost = 200
  BuildTime = 10.0
  CommandPoints = 15
  Behavior = HordeContain ModuleTag_HordeContain
    InitialPayload = RohanArcher GOOD_MEN_HORDE_SIZE
  End
End

Object RohanFellowshipHorde
  BuildCost = 800
  CommandPoints = 4
  Behavior = HordeContain ModuleTag_HordeContain
    InitialPayload = RohanFrodo 1
    InitialPayload = RohanSam 1
  End
End

Object RohanArcher
End
Object RohanFrodo
End
Object RohanSam
End
Object Loner
End
"""


def horde_game() -> Game:
    return load(HORDE_FIXTURE)


def test_payload_members_lists_each_initial_payload_member():
    game = horde_game()
    horde = game.objects["RohanFellowshipHorde"]
    module = next(m for m in horde.modules if m._fields.get("InitialPayload"))
    assert payload_members(module) == ["RohanFrodo", "RohanSam"]


def test_hordes_containing_finds_the_horde_for_a_member():
    game = horde_game()
    hordes = hordes_containing(game, "RohanArcher")
    assert [h.name for h in hordes] == ["RohanArcherHorde"]


def test_hordes_containing_matches_every_member_of_a_multi_unit_horde():
    game = horde_game()
    assert [h.name for h in hordes_containing(game, "RohanFrodo")] == ["RohanFellowshipHorde"]
    assert [h.name for h in hordes_containing(game, "RohanSam")] == ["RohanFellowshipHorde"]


def test_hordes_containing_is_empty_for_a_standalone_unit():
    assert hordes_containing(horde_game(), "Loner") == []


def test_horde_carries_the_build_stats_a_member_lacks():
    game = horde_game()
    member = game.objects["RohanArcher"]
    assert "BuildCost" not in member._fields  # the member itself has no cost
    horde = hordes_containing(game, member.name)[0]
    assert horde.BuildCost == 200
    assert horde.BuildTime == 10  # 10.0 -> Int
    assert horde.CommandPoints == 15
