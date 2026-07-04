"""Infobox/object diffing and resolution (sage_wiki.diff)."""

import pytest

import sage_ini.model.definitions  # noqa: F401  (register classes)
from sage_ini.model.game import Game
from sage_ini.parser.blockparser import parse
from sage_wiki.diff import apply_all, diff_infobox, resolve_object, resolve_objects
from sage_wiki.infobox import parse_infobox, parse_infoboxes

# Peripheral package (sage_wiki, deferred project): full suite only.
pytestmark = pytest.mark.full


def load(text: str) -> Game:
    game = Game()
    result = parse(text, file="t.ini")
    assert not result.diagnostics
    game.load_document(result.document)
    return game


# A mixed-case object name like SAGE's own (lowercase "for", uppercase "MM"),
# which a wiki editor would never reproduce by hand.
GAME = """\
Object ImladrisTest_forMM_Summoned
  KindOf = INFANTRY
End
"""


def test_resolve_object_matches_exact_case():
    game = load(GAME)
    box = parse_infobox("{{Hero|object=ImladrisTest_forMM_Summoned|health=100}}")
    assert resolve_object(box, game).name == "ImladrisTest_forMM_Summoned"


def test_resolve_object_matches_case_insensitively():
    game = load(GAME)
    box = parse_infobox("{{Hero|object=imladristest_formm_summoned|health=100}}")
    assert resolve_object(box, game).name == "ImladrisTest_forMM_Summoned"


def test_resolve_object_none_when_no_such_object():
    game = load(GAME)
    box = parse_infobox("{{Hero|object=NotLoaded|health=100}}")
    assert resolve_object(box, game) is None


# Two forms on one page, written as a slash-separated object id.
TWO_FORMS = """\
Object GondorCaptain
  KindOf = INFANTRY
End
Object GondorCaptainMounted
  KindOf = INFANTRY
End
"""


def test_resolve_objects_splits_slash_separated_names():
    game = load(TWO_FORMS)
    box = parse_infobox("{{Hero|object=GondorCaptain/GondorCaptainMounted|health=100}}")
    assert [o.name for o in resolve_objects(box, game)] == [
        "GondorCaptain",
        "GondorCaptainMounted",
    ]


def test_resolve_objects_drops_unloaded_parts():
    game = load(TWO_FORMS)
    box = parse_infobox("{{Hero|object=GondorCaptain/NotLoaded|health=100}}")
    assert [o.name for o in resolve_objects(box, game)] == ["GondorCaptain"]


def test_resolve_objects_dedupes_same_object():
    game = load(TWO_FORMS)
    box = parse_infobox("{{Hero|object=GondorCaptain/gondorcaptain|health=100}}")
    assert [o.name for o in resolve_objects(box, game)] == ["GondorCaptain"]


def test_resolve_object_returns_first_of_slash_separated():
    game = load(TWO_FORMS)
    box = parse_infobox("{{Hero|object=GondorCaptain/GondorCaptainMounted|health=100}}")
    assert resolve_object(box, game).name == "GondorCaptain"


def test_diff_rewrites_object_field_to_canonical_casing():
    game = load(GAME)
    box = parse_infobox("{{Hero|object=imladristest_formm_summoned|health=100}}")
    obj = resolve_object(box, game)
    change = next(c for c in diff_infobox(box, obj) if c.param == "object")
    assert change.old == "imladristest_formm_summoned"
    assert change.new == "ImladrisTest_forMM_Summoned"
    assert change.changed


def test_diff_keeps_all_names_when_page_lists_several_forms():
    game = load(TWO_FORMS)
    box = parse_infobox("{{Hero|object=GondorCaptain/GondorCaptainMounted|health=100}}")
    obj = resolve_object(box, game)  # the user picked the first form
    change = next(c for c in diff_infobox(box, obj) if c.param == "object")
    assert change.new == "GondorCaptain/GondorCaptainMounted"
    assert not change.changed


# A weapon-set toggle hero: a melee PRIMARY (short range) and a ranged toggle set.
TOGGLE_HERO = """\
Weapon Sword
  AttackRange = 20
  DelayBetweenShots = 1500
  DamageNugget
    Damage = 120
    DamageType = HERO
    Radius = 0
  End
End
Weapon Bow
  AttackRange = 300
  DelayBetweenShots = 2200
  DamageNugget
    Damage = 100
    DamageType = HERO_RANGED
    Radius = 0
  End
End
CommandButton Command_Toggle
  Command = TOGGLE_WEAPONSET
  FlagsUsedForToggle = WEAPONSET_TOGGLE_1
  TextLabel = CONTROLBAR:Toggle
End
CommandSet ToggleSet
  1 = Command_Toggle
End
Object ToggleHero
  KindOf = HERO
  CommandSet = ToggleSet
  WeaponSet
    Conditions = None
    Weapon = PRIMARY Sword
  End
  WeaponSet
    Conditions = WEAPONSET_TOGGLE_1
    Weapon = PRIMARY Bow
  End
  Behavior = ActiveBody ModuleTag_Body
    MaxHealth = 1500
  End
End
"""


def test_diff_fills_split_melee_and_ranged_params():
    game = load(TOGGLE_HERO)
    box = parse_infobox(
        "{{Hero|object=ToggleHero|damage_melee=1|damage_ranged=1|range_melee=1|range_ranged=1}}"
    )
    obj = resolve_object(box, game)
    changes = {c.param: c.new for c in diff_infobox(box, obj)}
    assert changes["damage_melee"] == "'''vs General''': 120 HERO"
    assert changes["damage_ranged"] == "'''vs General''': 100 HERO_RANGED"
    assert changes["range_melee"] == "20"  # the shorter-range stance
    assert changes["range_ranged"] == "300"  # the longer-range stance


def test_diff_clears_a_redundant_damage_targets_param():
    game = load(TOGGLE_HERO)
    box = parse_infobox(
        "{{Hero|object=ToggleHero|damage_melee=1|damage_targets=All: old<br>Structure: stale}}"
    )
    obj = resolve_object(box, game)
    changes = {c.param: c for c in diff_infobox(box, obj)}
    # The summary now lives in the damage cell, so the leftover damage_targets is emptied.
    assert changes["damage_targets"].new == ""
    assert changes["damage_targets"].changed
    # A page without the param gets no such change.
    plain = parse_infobox("{{Hero|object=ToggleHero|damage_melee=1}}")
    assert "damage_targets" not in {c.param for c in diff_infobox(plain, obj)}


# A mountable hero: MOUNTED armor and SET_MOUNTED locomotor differ on horseback, and
# the crush weapon gives the mounted trample.
MOUNT_HERO = """\
Weapon FootSword
  AttackRange = 10
  FiringDuration = 0
  DelayBetweenShots = 1500
  DamageNugget
    Damage = 260
    DamageType = HERO
    Radius = 0
  End
End
Weapon HeroCrush
  AttackRange = 0
  DamageNugget
    Damage = 65
    DamageType = CRUSH
    Radius = 0
  End
End
Armor FootArmor
  Armor = DEFAULT 100%
End
Armor MountArmor
  Armor = DEFAULT 100%
End
Locomotor FootLoco
End
Locomotor HorseLoco
End
Object MountHero
  KindOf = HERO
  CrushWeapon = HeroCrush
  ArmorSet
    Conditions = None
    Armor = FootArmor
  End
  ArmorSet
    Conditions = MOUNTED
    Armor = MountArmor
  End
  WeaponSet
    Conditions = None
    Weapon = PRIMARY FootSword
  End
  LocomotorSet
    Locomotor = FootLoco
    Condition = SET_NORMAL
    Speed = 50
  End
  LocomotorSet
    Locomotor = HorseLoco
    Condition = SET_MOUNTED
    Speed = 110
  End
  Behavior = ToggleMountedSpecialAbilityUpdate ModuleTag_Mount
  End
  Behavior = ActiveBody ModuleTag_Body
    MaxHealth = 4500
  End
End
"""


# A leveled building (veterancy-rank ladder): its health rises each rank, so the diff must
# compare every level's column, not just the base.
LEVEL_BUILDING = """\
ModifierList Lvl2HP
  Modifier = HEALTH 1500
End
ModifierList Lvl3HP
  Modifier = HEALTH 2500
End
ExperienceLevel BLvl1
  TargetNames = LevelBarracks
  RequiredExperience = 1
  Rank = 1
End
ExperienceLevel BLvl2
  TargetNames = LevelBarracks
  RequiredExperience = 2
  Rank = 2
  AttributeModifiers = Lvl2HP
End
ExperienceLevel BLvl3
  TargetNames = LevelBarracks
  RequiredExperience = 3
  Rank = 3
  AttributeModifiers = Lvl3HP
End
Object LevelBarracks
  KindOf = STRUCTURE
  BuildCost = 300
  Behavior = ActiveBody ModuleTag_Body
    MaxHealth = 3500
  End
  Behavior = LevelUpUpgrade ModuleTag_Up
    TriggeredBy = Upgrade_Lvl
    LevelsToGain = 1
    LevelCap = 3
  End
End
"""


def test_diff_compares_each_building_level_not_just_the_base():
    game = load(LEVEL_BUILDING)
    box = parse_infobox(
        "{{Infobox Building|object=LevelBarracks|health1=1|health2=1|health3=9999}}"
    )
    obj = resolve_object(box, game)
    changes = {c.param: c.new for c in diff_infobox(box, obj)}
    # Every per-level health column is computed and diffed, including the higher ranks the
    # old base-only diff ignored.
    assert changes["health1"] == "3500"
    assert changes["health2"] == "5000"
    assert changes["health3"] == "7500"


def test_diff_fills_mounted_params():
    game = load(MOUNT_HERO)
    box = parse_infobox(
        "{{Hero|object=MountHero|speed_melee=1|speed_mounted=1"
        "|armor_mounted=x|trample_damage_mounted=1}}"
    )
    obj = resolve_object(box, game)
    changes = {c.param: c.new for c in diff_infobox(box, obj)}
    assert changes["speed_melee"] == "50" and changes["speed_mounted"] == "110"
    assert changes["armor_mounted"] == "mountarmor"
    assert changes["trample_damage_mounted"] == "65"


TWO_INFOBOX_OBJECTS = """\
Object GondorSoldier
  KindOf = INFANTRY
  CommandPoints = 2
End
Object GondorArcher
  KindOf = INFANTRY
  CommandPoints = 4
End
"""

TWO_INFOBOX_PAGE = """\
Intro prose.
{{Infobox unit
|object_name = gondorsoldier
|command_points = 99
}}
A sentence with an {{Ability|name=Foo|image=x.png}} inline.
{{Infobox unit
|object = GondorArcher
|command_points = 99
}}
{{Gondor Navbox}}
"""


def test_parse_infoboxes_finds_each_object_infobox_only():
    # The two unit infoboxes are found in order; the inline ability and the navbox (no
    # object field) are not mistaken for infoboxes.
    boxes = parse_infoboxes(TWO_INFOBOX_PAGE)
    assert [b.name for b in boxes] == ["Infobox unit", "Infobox unit"]
    assert [b.get("command_points") for b in boxes] == ["99", "99"]


def test_parse_infoboxes_skips_object_naming_non_infoboxes():
    # A lone template that merely mentions an object but carries no other infobox params
    # (here only `object`) is not an infobox.
    assert parse_infoboxes("{{SomeTemplate|object=GondorSoldier}}") == []


def test_apply_all_updates_every_infobox_on_the_shared_page():
    game = load(TWO_INFOBOX_OBJECTS)
    boxes = parse_infoboxes(TWO_INFOBOX_PAGE)
    edited = [(box, diff_infobox(box, resolve_object(box, game))) for box in boxes]
    rendered = apply_all(edited)
    # Both infoboxes are rewritten in place: each command_points to its own object's value,
    # the hand-typed object id recased to canonical, and the rest of the page left intact.
    assert "|object_name = GondorSoldier" in rendered
    assert "|object = GondorArcher" in rendered
    assert rendered.count("|command_points = 99") == 0
    assert "|command_points = 2" in rendered and "|command_points = 4" in rendered
    assert "{{Ability|name=Foo|image=x.png}}" in rendered  # untouched
    assert "{{Gondor Navbox}}" in rendered


def test_apply_all_empty_is_noop():
    assert apply_all([]) == ""
