"""Page-draft generation from a parsed object (sage_wiki.pagegen)."""

import pytest

import sage_ini.model.definitions  # noqa: F401  (register classes)
from sage_ini.model.game import Game
from sage_ini.parser.blockparser import parse
from sage_wiki.links import build_linker
from sage_wiki.mapping import building_levels, computed_fields
from sage_wiki.pagegen import (
    _clean_tooltip,
    _intro,
    _lore_prose,
    _split_name,
    ability_block,
    available_upgrades,
    building_heroes,
    building_units,
    button_overlay_kind,
    command_entries,
    generate_page,
    infobox_block,
    upgrade_block,
    upgrade_hints,
)

# Peripheral package (sage_wiki, deferred project): full suite only.
pytestmark = pytest.mark.full


def load(text: str) -> Game:
    game = Game()
    result = parse(text, file="t.ini")
    assert not result.diagnostics
    game.load_document(result.document)
    return game


def test_split_name_extracts_shortcut():
    assert _split_name("For Honor (&C)") == ("For Honor", "C")


def test_split_name_without_shortcut():
    assert _split_name("Mount / Dismount") == ("Mount / Dismount", None)


def test_clean_tooltip_pulls_level_and_joins_segments():
    level, requirement, description = _clean_tooltip(
        "Requires: Level 3 \\n Only on horse \\n\\n Charges the enemy"
    )
    assert level == 3
    assert requirement is None
    # A period is added after a segment that does not already end a sentence.
    assert description == "Only on horse. Charges the enemy"


def test_clean_tooltip_pulls_named_requirement():
    level, requirement, description = _clean_tooltip(
        "Requires: Forged Blades \\n Deals more damage"
    )
    assert level is None
    assert requirement == "Forged Blades"
    assert description == "Deals more damage"


def test_clean_tooltip_without_requires_clause():
    level, requirement, description = _clean_tooltip("A simple effect")
    assert (level, requirement) == (None, None)
    assert description == "A simple effect"


def test_lore_prose_drops_metadata_and_flavor():
    text = (
        "Type: Cavalry \\n Prerequisites: None \\n Strengths: Unit Support \\n "
        "Lead the Prince into battle. \\n\\n ''A bitter victory.''"
    )
    assert _lore_prose(text) == "Lead the Prince into battle."


def test_lore_prose_empty_when_blank():
    assert _lore_prose("") == ""


INTRO_FIXTURE = """
Object Soldier
  DisplayName = OBJECT:Soldier
  Description = CONTROLBAR:SoldierDesc
End
Object Recruit
  DisplayName = OBJECT:Recruit
  Description = CONTROLBAR:RecruitDesc
  RecruitText = CONTROLBAR:RecruitBlurb
End
Object Plain
  DisplayName = OBJECT:Plain
  Description = CONTROLBAR:PlainDesc
End
"""
_INTRO_STRINGS = {
    "OBJECT:Soldier": "Gondor Soldiers",
    "CONTROLBAR:SoldierDesc": "Type: Infantry \\n The stalwart shield of Gondor.",
    "OBJECT:Recruit": "Imrahil",
    "CONTROLBAR:RecruitDesc": "Strengths: Support \\n Description prose.",
    "CONTROLBAR:RecruitBlurb": "Prerequisites: None \\n Lead the prince into battle.",
    "OBJECT:Plain": "Watchtower",
    "CONTROLBAR:PlainDesc": "Watchtower",
}


def _intro_game() -> Game:
    game = load(INTRO_FIXTURE)
    game.strings.update(_INTRO_STRINGS)
    return game


def test_intro_uses_description():
    game = _intro_game()
    intro = _intro(game, game.objects["Soldier"])
    assert intro == "The stalwart shield of Gondor."


def test_intro_prefers_recruit_text_over_description():
    game = _intro_game()
    intro = _intro(game, game.objects["Recruit"])
    assert intro == "Lead the prince into battle."


def test_intro_returns_description_even_when_it_matches_the_name():
    game = _intro_game()
    assert _intro(game, game.objects["Plain"]) == "Watchtower"


def test_clean_tooltip_keeps_existing_terminal_punctuation():
    # Segments that already end a sentence are not given a second period.
    _, _, description = _clean_tooltip("Charges forward! \\n Knocks foes down.")
    assert description == "Charges forward! Knocks foes down."


def test_clean_tooltip_joins_lowercase_continuation_without_period():
    # A lower-case next segment is a mid-sentence wrap, not a new sentence.
    _, _, description = _clean_tooltip("Left click to switch between \\n mounted and on foot")
    assert description == "Left click to switch between mounted and on foot"


def test_ability_block_emits_only_set_params():
    block = ability_block(
        {"name": "Charge", "shortcut": "C", "level": 3, "requirement": None, "description": "Dash"}
    )
    assert block == "\n".join(
        [
            "{{Ability",
            "|image=",
            "|level=3",
            "|name=Charge",
            "|shortcut=C",
            "|description=Dash",
            "}}",
        ]
    )


def test_ability_block_prefills_image_from_button_icon():
    # The image slot carries the file name the button-icon uploader will produce.
    block = ability_block(
        {
            "name": "Charge",
            "image": "Icon_Charge.png",
            "shortcut": None,
            "level": None,
            "requirement": None,
            "description": "",
        }
    )
    assert block == "{{Ability\n|image=Icon_Charge.png\n|name=Charge\n}}"


def test_ability_block_omits_absent_level_and_shortcut():
    block = ability_block(
        {"name": "Aura", "shortcut": None, "level": None, "requirement": None, "description": ""}
    )
    assert block == "{{Ability\n|image=\n|name=Aura\n}}"


def test_ability_block_appends_cooldown_to_description():
    block = ability_block(
        {
            "name": "Charge",
            "shortcut": None,
            "level": None,
            "requirement": None,
            "description": "Dash forward.",
            "cooldown": 30,
        }
    )
    assert "|description=Dash forward. Cooldown: 30" in block


def test_ability_block_closes_the_description_sentence_before_the_cooldown():
    # A tooltip without trailing punctuation gets a period so the cooldown reads as its own
    # sentence rather than running on from the description.
    block = ability_block(
        {
            "name": "Charge",
            "shortcut": None,
            "level": None,
            "requirement": None,
            "description": "Dash forward",
            "cooldown": 30,
        }
    )
    assert "|description=Dash forward. Cooldown: 30" in block


def test_ability_block_emits_cooldown_even_without_description():
    block = ability_block(
        {
            "name": "Aura",
            "shortcut": None,
            "level": None,
            "requirement": None,
            "description": "",
            "cooldown": 15,
        }
    )
    assert "|description=Cooldown: 15" in block


def test_ability_block_does_not_double_a_cooldown_the_tooltip_already_states():
    # Some Edain tooltips spell the cooldown out themselves; appending ours would repeat it.
    block = ability_block(
        {
            "name": "Camouflage",
            "shortcut": None,
            "level": None,
            "requirement": None,
            "description": "Hides allies. Cooldown: 60 seconds",
            "cooldown": 60,
        }
    )
    assert block.count("Cooldown") == 1
    assert "|description=Hides allies. Cooldown: 60 seconds" in block


def test_upgrade_hints_lists_each_upgrade_in_a_comment():
    hints = upgrade_hints(
        [
            {"name": "Heavy Armor", "description": "Tougher"},
            {"name": "Forged Blades", "description": ""},
        ]
    )
    assert hints.startswith("<!--")
    assert hints.endswith("-->")
    assert "  Heavy Armor: Tougher" in hints
    assert "  Forged Blades" in hints and "Forged Blades:" not in hints


# Slots exercise the engine's visibility rule: slots 1-6 show only with InPalantir, later
# slots only with Radial. Command_Hidden (no InPalantir) and Command_Capture (a high slot
# without Radial) are invisible; Command_Radial (a high slot with Radial) is visible.
COMMAND_FIXTURE = """
SpecialPower HeroPower
  ReloadTime = 90000
End
SpecialPower RadialPower
  ReloadTime = 500
End
Upgrade Upgrade_Armor
End

CommandButton Command_Special
  Command = SPECIAL_POWER
  SpecialPower = HeroPower
  InPalantir = Yes
  TextLabel = CONTROLBAR:HeroSpecial
  DescriptLabel = CONTROLBAR:ToolTipHeroSpecial
End
CommandButton Command_Upgrade
  Command = OBJECT_UPGRADE
  Upgrade = Upgrade_Armor
  InPalantir = Yes
  TextLabel = CONTROLBAR:BuyArmor
  DescriptLabel = CONTROLBAR:ToolTipBuyArmor
End
CommandButton Command_Stance
  Command = TOGGLE_STANCE
  InPalantir = Yes
  TextLabel = CONTROLBAR:Stance
End
CommandButton Command_Hidden
  Command = SPECIAL_POWER
  TextLabel = CONTROLBAR:Hidden
  DescriptLabel = CONTROLBAR:ToolTipHidden
End
CommandButton Command_Passive
  Command = NONE
  Options = NONPRESSABLE
  InPalantir = Yes
  TextLabel = CONTROLBAR:Passive
  DescriptLabel = CONTROLBAR:ToolTipPassive
End
CommandButton Command_Divider
  Command = NONE
  InPalantir = Yes
  TextLabel = CONTROLBAR:Divider
End
CommandButton Command_Radial
  Command = SPECIAL_POWER
  SpecialPower = RadialPower
  Radial = Yes
  TextLabel = CONTROLBAR:Radial
  DescriptLabel = CONTROLBAR:ToolTipRadial
End
CommandButton Command_Capture
  Command = SPECIAL_POWER
  InPalantir = Yes
  TextLabel = CONTROLBAR:Capture
  DescriptLabel = CONTROLBAR:ToolTipCapture
End

CommandSet HeroCommandSet
  1 = Command_Special
  2 = Command_Upgrade
  3 = Command_Stance
  4 = Command_Hidden
  5 = Command_Passive
  6 = Command_Divider
  8 = Command_Radial
  12 = Command_Capture
End

Object TestHero
  KindOf = HERO SELECTABLE
  CommandSet = HeroCommandSet
  RecruitText = CONTROLBAR:TestHeroRecruit
  BuildCost = 1000
  BuildTime = 30
End
"""

_STRINGS = {
    "CONTROLBAR:HeroSpecial": "Battle Cry (&Q)",
    "CONTROLBAR:ToolTipHeroSpecial": "Requires: Level 5 \\n A mighty shout \\n\\n Boosts allies",
    "CONTROLBAR:BuyArmor": "Purchase Heavy Armor (&C)",
    "CONTROLBAR:ToolTipBuyArmor": "Upgrades the unit with heavy armor",
    "CONTROLBAR:Stance": "Hold Ground Stance",
    "CONTROLBAR:Hidden": "Hidden Power (&Z)",
    "CONTROLBAR:ToolTipHidden": "A power the player never sees",
    "CONTROLBAR:Passive": "Town Guard",
    "CONTROLBAR:ToolTipPassive": "Requires: Level 10 \\n Always heals nearby allies",
    "CONTROLBAR:Radial": "Radial Power (&R)",
    "CONTROLBAR:ToolTipRadial": "A radial-menu ability",
    "CONTROLBAR:Capture": "Capture Building",
    "CONTROLBAR:ToolTipCapture": "Capture the building",
    "CONTROLBAR:TestHeroRecruit": "Prerequisites: None \\n Strengths: Melee \\n A bold hero.",
}


def hero_game() -> Game:
    game = load(COMMAND_FIXTURE)
    game.strings.update(_STRINGS)
    return game


def test_command_entries_classifies_and_filters():
    game = hero_game()
    entries = command_entries(game, game.objects["TestHero"])

    # Kept: visible abilities/upgrades, including a passive (NONE + tooltip) and a
    # radial-menu power. Dropped: the stance toggle (not an ability), the divider (NONE,
    # no tooltip), the slot-4 power with no InPalantir, and the capture power on a high
    # slot without Radial - all invisible or non-ability.
    assert [(e["kind"], e["name"]) for e in entries] == [
        ("ability", "Battle Cry"),
        ("upgrade", "Purchase Heavy Armor"),
        ("ability", "Town Guard"),
        ("ability", "Radial Power"),
    ]
    ability = entries[0]
    assert ability["level"] == 5
    assert ability["shortcut"] == "Q"
    assert ability["description"] == "A mighty shout. Boosts allies"
    assert ability["cooldown"] == 90  # 90000 ms ReloadTime, in seconds
    passive = entries[2]
    assert passive["level"] == 10
    assert passive["description"] == "Always heals nearby allies"
    assert passive["cooldown"] is None  # the passive button has no SpecialPower
    radial = entries[3]
    assert radial["cooldown"] is None  # 500 ms reload is sub-second, not a real cooldown


def test_button_overlay_kind_frames_every_button_passive_only_for_nonpressable():
    game = hero_game()
    buttons = game.commandbuttons
    # A button the player can click is active; one flagged NONPRESSABLE (a display-only
    # aura) is passive.
    assert button_overlay_kind(buttons["Command_Special"]) == "active"
    assert button_overlay_kind(buttons["Command_Radial"]) == "active"
    assert button_overlay_kind(buttons["Command_Passive"]) == "passive"
    # Non-abilities are framed too - an upgrade, a stance toggle and a tooltip-less divider
    # all take the active frame, since none carries the NONPRESSABLE option.
    assert button_overlay_kind(buttons["Command_Upgrade"]) == "active"
    assert button_overlay_kind(buttons["Command_Stance"]) == "active"
    assert button_overlay_kind(buttons["Command_Divider"]) == "active"


def test_button_overlay_kind_passive_is_driven_by_the_nonpressable_option():
    # The NONPRESSABLE option - not the presence of a special power - decides passivity: the
    # same special-power ability is active when clickable and passive when flagged NONPRESSABLE.
    game = load(
        """
SpecialPower AuraPower
End
CommandButton Command_Clickable
  Command = SPECIAL_POWER
  SpecialPower = AuraPower
  InPalantir = Yes
  TextLabel = CONTROLBAR:Aura
  DescriptLabel = CONTROLBAR:ToolTipAura
End
CommandButton Command_Aura
  Command = SPECIAL_POWER
  SpecialPower = AuraPower
  Options = NONPRESSABLE
  InPalantir = Yes
  TextLabel = CONTROLBAR:Aura
  DescriptLabel = CONTROLBAR:ToolTipAura
End
"""
    )
    assert button_overlay_kind(game.commandbuttons["Command_Clickable"]) == "active"
    assert button_overlay_kind(game.commandbuttons["Command_Aura"]) == "passive"


def test_generate_page_assembles_hero_sections():
    game = hero_game()
    page = generate_page(game, game.objects["TestHero"], "Gondor")

    assert page.startswith("{{Hero\n|faction=Gondor")
    assert "|object=TestHero" in page
    assert "|title=" in page  # manual placeholder present
    assert "A bold hero." in page  # intro from RecruitText, metadata stripped
    assert "Strengths:" not in page
    assert "== Abilities ==" in page
    assert "{{Ability\n|image=\n|level=5\n|name=Battle Cry\n|shortcut=Q" in page
    assert "Boosts allies. Cooldown: 90" in page  # the special power's recharge, in seconds
    assert "== Upgrades ==" in page
    assert "{{Heavy Armor|Gondor}}" in page  # mapped from the "Purchase Heavy Armor" button
    assert "{{Gondor Navbox}}" in page
    assert "|type=Hero" in page


def test_generate_page_prefills_the_portrait_image():
    game = hero_game()
    page = generate_page(game, game.objects["TestHero"], "Gondor")
    # The infobox image is pre-filled with the portrait filename the uploader produces.
    assert "|image=TestHero.png" in page


def test_generate_building_page_prefills_the_portrait_image():
    game = recruit_game()
    page = generate_page(game, game.objects["TestBarracks"], "Gondor")
    assert "|image=TestBarracks.png" in page


def test_generate_page_without_faction_leaves_navbox_placeholder():
    game = hero_game()
    page = generate_page(game, game.objects["TestHero"])
    assert "<!-- {{Faction Navbox}} -->" in page
    assert "|faction=\n}}" in page


WEAPON_FIXTURE = """
Weapon BasicBow
  AttackRange = 400
  ClipSize = 1
  ClipReloadTime = Min:1500 Max:2000
  AutoReloadsClip = Yes
  DamageNugget
    Damage = 57
    DamageType = PIERCE
    Radius = 0
  End
End
Weapon SalvoWeapon
  AttackRange = 450
  DelayBetweenShots = 1000
  DamageNugget
    Damage = 120
    DamageType = CAVALRY_RANGED
    Radius = 0
  End
End
Object Archer
  BuildCost = 600
  WeaponSet
    Conditions = None
    Weapon = PRIMARY BasicBow
    Weapon = QUINARY SalvoWeapon
  End
  Behavior = ActiveBody ModuleTag_Body
    MaxHealth = 247
  End
End
"""


def test_stats_come_from_the_primary_weapon_not_special_slots():
    fields = computed_fields(load(WEAPON_FIXTURE).objects["Archer"])
    assert (
        fields["damage"] == "'''vs General''': 57 PIERCE"
    )  # PRIMARY bow, not the 120 salvo in QUINARY
    assert fields["damage_type"] == "PIERCE"
    assert fields["range"] == "400"  # PRIMARY reach, not the salvo's 450
    assert fields["attack_speed"] == "2000 ms"  # ClipReloadTime Max, since the cycle is 0


TOGGLE_FIXTURE = """
Weapon HeroSword
  AttackRange = 20
  FiringDuration = 0
  DelayBetweenShots = 1466
  DamageNugget
    Damage = 120
    DamageType = HERO
    Radius = 0
  End
End
Weapon HeroRock
  AttackRange = 300
  FiringDuration = 1200
  DelayBetweenShots = 1700
  DamageNugget
    Damage = 100
    DamageType = HERO_RANGED
    Radius = 0
  End
End
Armor HeroArmor
  Armor = DEFAULT 100%
End
CommandButton Command_Toggle
  Command = TOGGLE_WEAPONSET
  FlagsUsedForToggle = WEAPONSET_TOGGLE_1
  InPalantir = Yes
  TextLabel = CONTROLBAR:Toggle
End
CommandSet ToggleHeroSet
  1 = Command_Toggle
End
Object ToggleHero
  KindOf = HERO SELECTABLE
  CommandSet = ToggleHeroSet
  BuildCost = 150
  ArmorSet
    Conditions = None
    Armor = HeroArmor
  End
  WeaponSet
    Conditions = None
    Weapon = PRIMARY HeroSword
    Weapon = SECONDARY HeroRock
  End
  WeaponSet
    Conditions = WEAPONSET_TOGGLE_1
    Weapon = PRIMARY HeroRock
  End
  Behavior = ActiveBody ModuleTag_Body
    MaxHealth = 1500
  End
End
"""


def test_toggle_hero_splits_weapon_stats_by_stance():
    fields = computed_fields(load(TOGGLE_FIXTURE).objects["ToggleHero"])
    # The shorter-range PRIMARY (the sword) is melee, the longer-range rock is ranged.
    assert fields["damage_melee"] == "'''vs General''': 120 HERO"
    assert fields["damage_ranged"] == "'''vs General''': 100 HERO_RANGED"
    assert fields["damage_type_melee"] == "HERO"
    assert fields["damage_type_ranged"] == "HERO_RANGED"
    assert fields["range_melee"] == "20"
    assert fields["range_ranged"] == "300"
    assert fields["attack_speed_melee"] == "1466 ms"
    assert fields["attack_speed_ranged"] == "2900 ms"  # 1200 firing + 1700 delay
    # The generic (single) weapon fields are not emitted in split mode.
    assert "damage" not in fields and "range" not in fields


def test_toggle_hero_duplicates_shared_stats_and_keeps_health_single():
    fields = computed_fields(load(TOGGLE_FIXTURE).objects["ToggleHero"])
    # Armor and speed don't change with the weapon set, but the Hero infobox carries
    # them per stance, so they are emitted to both columns with the same value.
    assert fields["armor_melee"] == fields["armor_ranged"] == "heroarmor"
    # Health is stance-independent and stays a single field.
    assert fields["health"] == "1500"
    assert "armor" not in fields and "health_melee" not in fields


# A non-hero toggle unit (the Galadhrim's bow/sword) - the switch is wired without a
# TOGGLE_WEAPONSET button, so detection rests on the WEAPONSET_TOGGLE_1 weapon set.
TOGGLE_UNIT_FIXTURE = """
Weapon UnitBow
  AttackRange = 340
  FiringDuration = 0
  DelayBetweenShots = 2000
  DamageNugget
    Damage = 66
    DamageType = PIERCE
    Radius = 0
  End
End
Weapon UnitSword
  AttackRange = 10
  FiringDuration = 0
  DelayBetweenShots = 1500
  DamageNugget
    Damage = 95
    DamageType = URUK
    Radius = 0
  End
End
Armor UnitArmor
  Armor = DEFAULT 100%
End
Object ToggleUnit
  KindOf = INFANTRY SELECTABLE
  BuildCost = 900
  ArmorSet
    Conditions = None
    Armor = UnitArmor
  End
  WeaponSet
    Conditions = None
    Weapon = PRIMARY UnitBow
  End
  WeaponSet
    Conditions = WEAPONSET_TOGGLE_1
    Weapon = PRIMARY UnitSword
  End
  Behavior = ActiveBody ModuleTag_Body
    MaxHealth = 1125
  End
End
"""


# A mountable hero (Eomer): MOUNTED armor and SET_MOUNTED locomotor differ from the
# foot stance, and the crush weapon gives the mounted trample. Detected from the
# ToggleMountedSpecialAbilityUpdate, with no MountedTemplate (mounts in place).
MOUNT_FIXTURE = """
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
  WeaponSet
    Conditions = MOUNTED
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


def test_mountable_hero_splits_foot_and_mounted_stances():
    fields = computed_fields(load(MOUNT_FIXTURE).objects["MountHero"])
    # Foot stance is `_melee`, mounted is `_mounted`.
    assert fields["speed_melee"] == "50" and fields["speed_mounted"] == "110"
    assert fields["armor_melee"] == "footarmor" and fields["armor_mounted"] == "mountarmor"
    assert (
        fields["damage_melee"] == "'''vs General''': 260 HERO"
        and fields["damage_mounted"] == "'''vs General''': 260 HERO"
    )
    assert fields["damage_type_melee"] == "HERO" and fields["damage_type_mounted"] == "HERO"
    assert fields["range_melee"] == "10" and fields["range_mounted"] == "10"
    assert fields["attack_speed_melee"] == "1500 ms"
    assert fields["attack_speed_mounted"] == "1500 ms"
    # The mounted unit tramples (the crush weapon); a foot unit does not.
    assert fields["trample_damage_mounted"] == "65"
    assert "trample_damage_melee" not in fields and "trample_damage" not in fields
    # Health is a single field; this is not a weapon-set toggle, so no `_ranged`/`_alt`.
    assert fields["health"] == "4500"
    assert "damage_ranged" not in fields and "damage_alt" not in fields


def test_mountable_hero_reads_mounted_stats_from_mounted_template():
    # When the toggle names a MountedTemplate, the mounted stats come from that
    # separate object (its own weapon, armor, locomotor and crush), not from in-place
    # MOUNTED flags.
    fixture = """
Weapon FootSword
  AttackRange = 10
  FiringDuration = 0
  DelayBetweenShots = 1500
  DamageNugget
    Damage = 100
    DamageType = HERO
    Radius = 0
  End
End
Weapon LanceWeapon
  AttackRange = 20
  FiringDuration = 0
  DelayBetweenShots = 1200
  DamageNugget
    Damage = 300
    DamageType = CAVALRY
    Radius = 0
  End
End
Weapon RiderCrush
  AttackRange = 0
  DamageNugget
    Damage = 80
    DamageType = CRUSH
    Radius = 0
  End
End
Armor FootArmor
  Armor = DEFAULT 100%
End
Armor RiderArmor
  Armor = DEFAULT 100%
End
Locomotor FootLoco
End
Locomotor RiderLoco
End
Object RiderForm
  KindOf = HERO CAVALRY
  CrushWeapon = RiderCrush
  ArmorSet
    Conditions = None
    Armor = RiderArmor
  End
  WeaponSet
    Conditions = None
    Weapon = PRIMARY LanceWeapon
  End
  LocomotorSet
    Locomotor = RiderLoco
    Condition = SET_NORMAL
    Speed = 160
  End
  Behavior = ActiveBody ModuleTag_Body
    MaxHealth = 3000
  End
End
Object FootHero
  KindOf = HERO
  ArmorSet
    Conditions = None
    Armor = FootArmor
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
  Behavior = ToggleMountedSpecialAbilityUpdate ModuleTag_Mount
    MountedTemplate = RiderForm
  End
  Behavior = ActiveBody ModuleTag_Body
    MaxHealth = 3000
  End
End
"""
    fields = computed_fields(load(fixture).objects["FootHero"])
    # Foot stance from FootHero, mounted stance from the RiderForm template.
    assert (
        fields["damage_melee"] == "'''vs General''': 100 HERO"
        and fields["damage_mounted"] == "'''vs General''': 300 CAVALRY"
    )
    assert fields["speed_melee"] == "50" and fields["speed_mounted"] == "160"
    assert fields["range_melee"] == "10" and fields["range_mounted"] == "20"
    assert fields["damage_type_mounted"] == "CAVALRY"
    assert fields["trample_damage_mounted"] == "80"  # the rider's crush weapon


# A flying hero (the Great Eagles): the hero itself carries GiantBirdAIUpdate, so its
# single combat stance fills the Hero infobox's `_flying` column. It also expires, so its
# LifetimeUpdate gives the summon timer.
FLYER_FIXTURE = """
Weapon TalonStrike
  AttackRange = 20
  FiringDuration = 0
  DelayBetweenShots = 1000
  DamageNugget
    Damage = 400
    DamageType = HERO
    Radius = 30
  End
End
Armor EagleArmor
  Armor = DEFAULT 100%
End
Locomotor SkyLoco
End
Object EagleHero
  KindOf = HERO
  ArmorSet
    Conditions = None
    Armor = EagleArmor
  End
  WeaponSet
    Conditions = None
    Weapon = PRIMARY TalonStrike
  End
  LocomotorSet
    Locomotor = SkyLoco
    Condition = SET_NORMAL
    Speed = 200
  End
  Behavior = GiantBirdAIUpdate ModuleTag_Bird
  End
  Behavior = LifetimeUpdate ModuleTag_Life
    MaxLifetime = 60000
  End
  Behavior = ActiveBody ModuleTag_Body
    MaxHealth = 3000
  End
End
"""


def test_flying_hero_emits_a_single_flying_stance():
    fields = computed_fields(load(FLYER_FIXTURE).objects["EagleHero"])
    # A hero that flies in its own right: weapon stats, armor and speed under `_flying`.
    assert (
        fields["damage_flying"] == "'''vs General''': 400 HERO (30R)"
        and fields["damage_type_flying"] == "HERO"
    )
    assert fields["range_flying"] == "20" and fields["radius_flying"] == "30"
    assert fields["armor_flying"] == "eaglearmor" and fields["speed_flying"] == "200"
    # Health stays a single field; no foot/mounted/ranged columns for a pure flyer.
    assert fields["health"] == "3000"
    assert "damage_melee" not in fields and "damage_mounted" not in fields


def test_summoned_hero_timer_comes_from_its_lifetime():
    fields = computed_fields(load(FLYER_FIXTURE).objects["EagleHero"])
    # MaxLifetime is milliseconds; the infobox timer is its lifespan in seconds.
    assert fields["timer"] == "60"


# A hero that mounts a separate flying template (mounts an eagle): its on-foot stats are
# `_melee`, and the eagle mount's - because the mount carries GiantBirdAIUpdate - go to
# `_flying` rather than `_mounted`.
EAGLE_MOUNT_FIXTURE = """
Weapon FootSword
  AttackRange = 10
  FiringDuration = 0
  DelayBetweenShots = 1500
  DamageNugget
    Damage = 100
    DamageType = HERO
    Radius = 0
  End
End
Weapon TalonStrike
  AttackRange = 20
  FiringDuration = 0
  DelayBetweenShots = 1000
  DamageNugget
    Damage = 300
    DamageType = HERO
    Radius = 0
  End
End
Armor FootArmor
  Armor = DEFAULT 100%
End
Armor EagleArmor
  Armor = DEFAULT 100%
End
Locomotor FootLoco
End
Locomotor SkyLoco
End
Object EagleForm
  KindOf = HERO
  ArmorSet
    Conditions = None
    Armor = EagleArmor
  End
  WeaponSet
    Conditions = None
    Weapon = PRIMARY TalonStrike
  End
  LocomotorSet
    Locomotor = SkyLoco
    Condition = SET_NORMAL
    Speed = 200
  End
  Behavior = GiantBirdAIUpdate ModuleTag_Bird
  End
  Behavior = ActiveBody ModuleTag_Body
    MaxHealth = 3000
  End
End
Object RiderHero
  KindOf = HERO
  ArmorSet
    Conditions = None
    Armor = FootArmor
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
  Behavior = ToggleMountedSpecialAbilityUpdate ModuleTag_Mount
    MountedTemplate = EagleForm
  End
  Behavior = ActiveBody ModuleTag_Body
    MaxHealth = 3000
  End
End
"""


def test_mountable_hero_with_flying_mount_uses_the_flying_column():
    fields = computed_fields(load(EAGLE_MOUNT_FIXTURE).objects["RiderHero"])
    # On foot is `_melee`; the eagle mount is a flyer, so its stats fill `_flying`.
    assert (
        fields["damage_melee"] == "'''vs General''': 100 HERO"
        and fields["damage_flying"] == "'''vs General''': 300 HERO"
    )
    assert fields["speed_melee"] == "50" and fields["speed_flying"] == "200"
    assert fields["range_flying"] == "20"
    assert "damage_mounted" not in fields and "speed_mounted" not in fields


# A hero with both a ground mount and a flying one (the Dark Marshal's Ring Hunter form:
# on foot, on a horse, or on a fell beast). The in-place MOUNTED weapon/armor/locomotor give
# the `_mounted` column, and the GiantBird mount template gives `_flying` - all three stances
# emitted together.
THREE_STANCE_FIXTURE = """
Weapon FootSword
  AttackRange = 10
  FiringDuration = 0
  DelayBetweenShots = 1500
  DamageNugget
    Damage = 100
    DamageType = HERO
    Radius = 0
  End
End
Weapon MountSword
  AttackRange = 10
  FiringDuration = 0
  DelayBetweenShots = 1500
  DamageNugget
    Damage = 150
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
Weapon FellTalon
  AttackRange = 20
  FiringDuration = 0
  DelayBetweenShots = 4000
  DamageNugget
    Damage = 300
    DamageType = HERO
    Radius = 0
  End
End
Armor FootArmor
  Armor = DEFAULT 100%
End
Armor MountArmor
  Armor = DEFAULT 100%
End
Armor FellArmor
  Armor = DEFAULT 100%
End
Locomotor FootLoco
End
Locomotor HorseLoco
End
Locomotor SkyLoco
End
Object FellMount
  KindOf = HERO MONSTER
  ArmorSet
    Conditions = None
    Armor = FellArmor
  End
  WeaponSet
    Conditions = None
    Weapon = PRIMARY FellTalon
  End
  LocomotorSet
    Locomotor = SkyLoco
    Condition = SET_NORMAL
    Speed = 95
  End
  Behavior = GiantBirdAIUpdate ModuleTag_Bird
  End
  Behavior = ActiveBody ModuleTag_Body
    MaxHealth = 4000
  End
End
Object RingHunter
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
  WeaponSet
    Conditions = MOUNTED
    Weapon = PRIMARY MountSword
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
  Behavior = ToggleMountedSpecialAbilityUpdate ModuleTag_Horse
  End
  Behavior = ToggleMountedSpecialAbilityUpdate ModuleTag_FellBeast
    MountedTemplate = FellMount
  End
  Behavior = ActiveBody ModuleTag_Body
    MaxHealth = 3500
  End
End
"""


def test_hero_with_ground_and_flying_mounts_emits_three_stances():
    fields = computed_fields(load(THREE_STANCE_FIXTURE).objects["RingHunter"])
    # Foot (`_melee`), horse (`_mounted`, in place) and fell beast (`_flying`, the mount
    # template) all present in the one infobox.
    assert fields["damage_melee"] == "'''vs General''': 100 HERO"
    assert fields["damage_mounted"] == "'''vs General''': 150 HERO"
    assert fields["damage_flying"] == "'''vs General''': 300 HERO"
    assert fields["speed_melee"] == "50"
    assert fields["speed_mounted"] == "110"
    assert fields["speed_flying"] == "95"
    assert fields["range_melee"] == "10" and fields["range_flying"] == "20"
    assert fields["armor_flying"] == "fellarmor"
    # Trample is the ground mount's crush; health stays a single field.
    assert fields["trample_damage_mounted"] == "65"
    assert "trample_damage_flying" not in fields
    assert fields["health"] == "3500"


def test_toggle_unit_splits_into_primary_and_alt_stances():
    fields = computed_fields(load(TOGGLE_UNIT_FIXTURE).objects["ToggleUnit"])
    # The default (Conditions = None) weapon set is the unsuffixed primary; the toggled
    # set is `_alt`. Detection uses the weapon set, not a command button.
    assert (
        fields["damage"] == "'''vs General''': 66 PIERCE"
        and fields["damage_alt"] == "'''vs General''': 95 URUK"
    )
    assert fields["damage_type"] == "PIERCE" and fields["damage_type_alt"] == "URUK"
    assert fields["range"] == "340" and fields["range_alt"] == "10"
    assert fields["attack_speed"] == "2000 ms" and fields["attack_speed_alt"] == "1500 ms"
    # Stance-independent stats are duplicated to `_alt` with the same value.
    assert fields["health"] == fields["health_alt"] == "1125"
    assert fields["armor"] == fields["armor_alt"] == "unitarmor"
    # A unit uses the primary/`_alt` scheme, never the hero `_melee`/`_ranged` columns.
    assert "damage_melee" not in fields and "damage_ranged" not in fields


# A unit whose two weapon sets are AoE: the basic attack's blast radius is reported, and
# the toggled set's under `_alt`. A zero-radius (single-target) weapon reports no radius.
RADIUS_FIXTURE = """
Weapon BlastBow
  AttackRange = 300
  FiringDuration = 0
  DelayBetweenShots = 2000
  DamageNugget
    Damage = 50
    DamageType = PIERCE
    Radius = 25
  End
End
Weapon SmashHammer
  AttackRange = 10
  FiringDuration = 0
  DelayBetweenShots = 1500
  DamageNugget
    Damage = 80
    DamageType = CRUSH
    Radius = 40
  End
End
Armor RadArmor
  Armor = DEFAULT 100%
End
Object RadiusUnit
  KindOf = INFANTRY SELECTABLE
  ArmorSet
    Conditions = None
    Armor = RadArmor
  End
  WeaponSet
    Conditions = None
    Weapon = PRIMARY BlastBow
  End
  WeaponSet
    Conditions = WEAPONSET_TOGGLE_1
    Weapon = PRIMARY SmashHammer
  End
  Behavior = ActiveBody ModuleTag_Body
    MaxHealth = 500
  End
End
"""


def test_unit_weapon_radius_maps_base_and_alt():
    fields = computed_fields(load(RADIUS_FIXTURE).objects["RadiusUnit"])
    # The PRIMARY attack's nugget radius, default stance unsuffixed and toggled as `_alt`.
    assert fields["radius"] == "25" and fields["radius_alt"] == "40"


def test_single_target_weapon_reports_no_radius():
    # The toggle-unit fixture's weapons are all Radius = 0, so no radius field is emitted.
    fields = computed_fields(load(TOGGLE_UNIT_FIXTURE).objects["ToggleUnit"])
    assert "radius" not in fields and "radius_alt" not in fields


def test_upgrade_block_renders_known_templates_and_hints_the_rest():
    entries = [
        {"name": "Purchase Banner Carrier", "description": "promote"},
        {"name": "Fire Arrows", "description": "burn"},
        {"name": "Composite Bows", "description": "pierce"},
        {"name": "Mystery Upgrade", "description": "does something"},
    ]
    block = upgrade_block(entries, "Gondor", "Good")
    assert "The unit has access to the following upgrades:<br>" in block
    assert "{{Banner Carrier|Gondor}}<br>" in block  # faction param
    assert "{{Fire Arrows|Good}}<br>" in block  # alignment param
    assert "{{Composite Bows}}<br>" in block  # no param
    # the unmapped upgrade falls through to the hint comment, nothing lost
    assert "<!--" in block and "Mystery Upgrade" in block


UPGRADE_FIXTURE = """
SpecialPower P1
End
SpecialPower P2
End
CommandButton Command_Base
  Command = SPECIAL_POWER
  SpecialPower = P1
  InPalantir = Yes
  TextLabel = CONTROLBAR:Base
  DescriptLabel = CONTROLBAR:ToolTipBase
End
CommandButton Command_Extra
  Command = SPECIAL_POWER
  SpecialPower = P2
  InPalantir = Yes
  TextLabel = CONTROLBAR:Extra
  DescriptLabel = CONTROLBAR:ToolTipExtra
End
CommandSet BaseSet
  1 = Command_Base
End
CommandSet UpgradedSet
  1 = Command_Base
  2 = Command_Extra
End
Object UpgradeHero
  KindOf = HERO
  CommandSet = BaseSet
  Behavior = CommandSetUpgrade ModuleTag_U
    TriggeredBy = Upgrade_Reinforced
    CommandSet = UpgradedSet
  End
End
"""
_UPGRADE_STRINGS = {
    "CONTROLBAR:Base": "Base Power",
    "CONTROLBAR:ToolTipBase": "A base power",
    "CONTROLBAR:Extra": "Extra Power",
    "CONTROLBAR:ToolTipExtra": "An unlocked power",
}


SIZE_FIXTURE = """
Object Battalion
  KindOf = INFANTRY
  Behavior = HordeContain ModuleTag_Horde
    Slots = 12
  End
End
Object LoneWolf
  KindOf = INFANTRY
End
"""


def test_unit_infobox_uses_unit_template_and_horde_size():
    obj = load(SIZE_FIXTURE).objects["Battalion"]
    box = infobox_block(obj, "unit", "Gondor")
    assert box.startswith("{{Unit\n|faction=Gondor")
    assert "|size=12" in box
    assert "|size=\n" not in box  # the derived value, not also an empty placeholder


def test_unit_infobox_lone_unit_leaves_size_blank():
    obj = load(SIZE_FIXTURE).objects["LoneWolf"]
    box = infobox_block(obj, "unit", "Gondor")
    assert "|size=\n" in box  # no horde to size from, so the placeholder stays empty


BUILDING_FIXTURE = """
Object FarmHouse
  KindOf = STRUCTURE SELECTABLE
  BuildCost = 300
  BuildTime = 30
  Behavior = ActiveBody ModuleTag_Body
    MaxHealth = 1500
  End
End
"""


def test_building_infobox_names_the_object_param():
    obj = load(BUILDING_FIXTURE).objects["FarmHouse"]
    box = infobox_block(obj, "building", "Gondor")
    # The Building infobox's name field is `object`, not the computed `object_name` key.
    assert "|object=FarmHouse" in box
    assert "object_name" not in box


def test_building_infobox_emits_full_skeleton():
    box = infobox_block(load(BUILDING_FIXTURE).objects["FarmHouse"], "building", "Gondor")
    # Every template field is present, blank where the (unleveled) building has no value.
    for field in ("image", "type", "level_up", "location"):
        assert f"|{field}=\n" in box
    # Three level columns, each with the full per-level field run.
    for level in (1, 2, 3):
        for field in (
            "label",
            "armor",
            "health",
            "resources",
            "interval",
            "damage",
            "attack_speed",
            "range",
            "level_effect",
        ):
            assert f"|{field}{level}=" in box
    # The unleveled building's stats land in level 1; later columns stay blank.
    assert "|health1=1500" in box
    assert "|health2=\n" in box and "|health3=\n" in box


def test_available_upgrades_lists_object_triggers():
    game = load(UPGRADE_FIXTURE)
    assert "Upgrade_Reinforced" in available_upgrades(game.objects["UpgradeHero"])


def test_available_upgrades_includes_inherited_triggers():
    # A ChildObject's upgrade module lives in the base template; the toggles must still find it.
    game = load(UPGRADE_FIXTURE + "\nChildObject HeroVariant UpgradeHero\nEnd\n")
    assert "Upgrade_Reinforced" in available_upgrades(game.objects["HeroVariant"])


# A unit-production building that levels through a LevelUpUpgrade veterancy ladder (not the
# economy AttributeModifierUpgrade), builds two units, and revives heroes through generic
# REVIVE slots indexed against the faction's buildable heroes.
BUILDING_RECRUIT_FIXTURE = """
ModifierList Rank2Health
  Modifier = HEALTH 1500
End
ModifierList Rank3Health
  Modifier = HEALTH 2500
End
ExperienceLevel BarracksLvl1
  TargetNames = TestBarracks
  RequiredExperience = 1
  Rank = 1
End
ExperienceLevel BarracksLvl2
  TargetNames = TestBarracks
  RequiredExperience = 2
  Rank = 2
  AttributeModifiers = Rank2Health
End
ExperienceLevel BarracksLvl3
  TargetNames = TestBarracks
  RequiredExperience = 3
  Rank = 3
  AttributeModifiers = Rank3Health
End
Upgrade Upgrade_Level2
End
Upgrade Upgrade_DragonNest
End
Object Swordsmen
  KindOf = INFANTRY
  DisplayName = OBJECT:Swordsmen
  BuildCost = 200
  CommandPoints = 60
End
Object Pikemen
  KindOf = INFANTRY
  DisplayName = OBJECT:Pikemen
  BuildCost = 300
  CommandPoints = 60
End
Object HeroAlpha
  KindOf = HERO
  DisplayName = OBJECT:HeroAlpha
  BuildCost = 1100
End
Object HeroBeta
  KindOf = HERO
  DisplayName = OBJECT:HeroBeta
  BuildCost = 1800
End
CommandButton Command_BuildSwordsmen
  Command = UNIT_BUILD
  Object = Swordsmen
  TextLabel = CONTROLBAR:BuildSwordsmen
End
CommandButton Command_BuildPikemen
  Command = UNIT_BUILD
  Object = Pikemen
  TextLabel = CONTROLBAR:BuildPikemen
End
CommandButton Command_Sell
  Command = SELL
  TextLabel = CONTROLBAR:Sell
End
CommandButton Command_ReviveRing
  Command = REVIVE
  Options = NEED_UPGRADE CANCELABLE
  TextLabel = CONTROLBAR:Revive
End
CommandButton Command_ReviveCAH
  Command = REVIVE
  Options = NEED_UPGRADE CANCELABLE
  TextLabel = CONTROLBAR:Revive
End
CommandButton Command_ReviveSlot1
  Command = REVIVE
  Options = NEED_UPGRADE CANCELABLE
  NeededUpgrade = Upgrade_DragonNest
  TextLabel = CONTROLBAR:Revive
End
CommandButton Command_ReviveSlot2
  Command = REVIVE
  Options = CANCELABLE
  TextLabel = CONTROLBAR:Revive
End
CommandButton Command_ReviveSlot3
  Command = REVIVE
  Options = NEED_UPGRADE CANCELABLE
  NeededUpgrade = Upgrade_DragonNest
  TextLabel = CONTROLBAR:Revive
End
CommandButton Command_ReviveSlot4
  Command = REVIVE
  Options = CANCELABLE
  TextLabel = CONTROLBAR:Revive
End
CommandSet TestBarracksSet
  1 = Command_BuildSwordsmen
  2 = Command_BuildPikemen
  3 = Command_Sell
  15 = Command_ReviveRing
  16 = Command_ReviveCAH
  17 = Command_ReviveSlot1
  18 = Command_ReviveSlot2
  19 = Command_ReviveSlot3
  20 = Command_ReviveSlot4
End
Object TestBarracks
  KindOf = STRUCTURE SELECTABLE
  Side = Men
  DisplayName = OBJECT:TestBarracks
  BuildCost = 300
  BuildTime = 25
  CommandSet = TestBarracksSet
  Behavior = ActiveBody ModuleTag_Body
    MaxHealth = 3500
  End
  Behavior = LevelUpUpgrade ModuleTag_Lvl
    TriggeredBy = Upgrade_Level2
    LevelsToGain = 1
    LevelCap = 3
  End
End
PlayerTemplate FactionTestMen
  Side = Men
  PlayableSide = Yes
  BuildableRingHeroesMP = RingHeroDummy
  BuildableHeroesMP = CreateAHero PippinFiller HeroAlpha LockedHero HeroBeta
End
"""
_RECRUIT_STRINGS = {
    "OBJECT:Swordsmen": "Soldiers",
    "OBJECT:Pikemen": "Pikemen",
    "OBJECT:HeroAlpha": "Alpha",
    "OBJECT:HeroBeta": "Beta",
    "OBJECT:TestBarracks": "Barracks",
    "CONTROLBAR:BuildSwordsmen": "Soldiers (&Y)",
    "CONTROLBAR:BuildPikemen": "Pikemen (&X)",
}


def recruit_game() -> Game:
    game = load(BUILDING_RECRUIT_FIXTURE)
    game.strings.update(_RECRUIT_STRINGS)
    return game


def test_building_levels_detect_a_veterancy_rank_ladder():
    # The building levels through a LevelUpUpgrade rank ladder, not economy upgrades, so each
    # level is a rank (no extra upgrade) - three of them.
    levels = building_levels(load(BUILDING_RECRUIT_FIXTURE).objects["TestBarracks"])
    assert [rank for _active, rank in levels] == [1, 2, 3]


def test_building_stats_are_computed_per_level():
    fields = computed_fields(load(BUILDING_RECRUIT_FIXTURE).objects["TestBarracks"])
    # Health is read at each rank's cumulative modifiers, not just the base level.
    assert fields["health1"] == "3500"
    assert fields["health2"] == "5000"  # + Rank2Health 1500
    assert fields["health3"] == "7500"  # + Rank2 (1500) + Rank3 (2500)
    assert "health" not in fields  # a leveled building uses the suffixed columns only


# An economy building that levels the Wirtschaftssystem-4.0 way (Edain's AmrothLighthouse): two
# globally-researched upgrades each level it up (a LevelUpUpgrade) and grant the per-level stats
# (a paired AttributeModifierUpgrade). It also carries a one-off buff (a hero's gift) that grants
# only an AttributeModifierUpgrade - that must NOT count as a level.
ECONOMY_LEVEL_FIXTURE = """
ModifierList EconStepOne
  Modifier = HEALTH 500
End
ModifierList EconStepTwo
  Modifier = HEALTH 500
End
ModifierList HeroGift
  Modifier = PRODUCTION 120%
End
Upgrade Upgrade_EconOne
End
Upgrade Upgrade_EconTwo
End
Upgrade Upgrade_HeroGift
End
Object EconomyLighthouse
  KindOf = STRUCTURE SELECTABLE
  Side = Men
  BuildCost = 300
  BuildTime = 30
  Behavior = ActiveBody ModuleTag_Body
    MaxHealth = 1000
  End
  Behavior = LevelUpUpgrade ModuleTag_LvlOne
    TriggeredBy  = Upgrade_EconOne
    LevelsToGain = 1
    LevelCap     = 3
  End
  Behavior = AttributeModifierUpgrade ModuleTag_ModOne
    TriggeredBy       = Upgrade_EconOne
    AttributeModifier = EconStepOne
  End
  Behavior = LevelUpUpgrade ModuleTag_LvlTwo
    TriggeredBy  = Upgrade_EconTwo
    LevelsToGain = 1
    LevelCap     = 3
  End
  Behavior = AttributeModifierUpgrade ModuleTag_ModTwo
    TriggeredBy       = Upgrade_EconTwo
    AttributeModifier = EconStepTwo
  End
  Behavior = AttributeModifierUpgrade ModuleTag_HeroGift
    TriggeredBy       = Upgrade_HeroGift
    AttributeModifier = HeroGift
  End
End
"""


def test_economy_building_levels_count_only_the_level_up_upgrades():
    # Two level-granting economy upgrades → three levels (base + one step each). The hero-gift
    # buff has no LevelUpUpgrade, so it is not a fourth level.
    levels = building_levels(load(ECONOMY_LEVEL_FIXTURE).objects["EconomyLighthouse"])
    assert len(levels) == 3


def test_economy_building_stats_step_with_each_level_upgrade():
    fields = computed_fields(load(ECONOMY_LEVEL_FIXTURE).objects["EconomyLighthouse"])
    assert fields["health1"] == "1000"  # base
    assert fields["health2"] == "1500"  # + EconStepOne 500
    assert fields["health3"] == "2000"  # + EconStepOne (500) + EconStepTwo (500)
    assert "health4" not in fields  # the hero-gift buff is no extra level


# A structure that levels purely through its ExperienceLevel ladder - rank is earned by
# RequiredExperience, with no LevelUpUpgrade pushing it (Edain's Dol Guldur / Morgul outpost
# fortresses). The per-rank HEALTH modifiers carry the gain, the same as the ladder above.
EXP_LEVELED_FIXTURE = """
ModifierList OutpostHealthLvl2
  Modifier = HEALTH 1500
End
ExperienceLevel OutpostLvl1
  TargetNames = TestOutpost
  RequiredExperience = 1
  Rank = 1
End
ExperienceLevel OutpostLvl2
  TargetNames = TestOutpost
  RequiredExperience = 100
  Rank = 2
  AttributeModifiers = OutpostHealthLvl2
End
ExperienceLevel OutpostLvl3
  TargetNames = TestOutpost
  RequiredExperience = 200
  Rank = 3
End
Object TestOutpost
  KindOf = STRUCTURE SELECTABLE
  Side = Mordor
  DisplayName = OBJECT:TestOutpost
  BuildCost = 1000
  BuildTime = 30
  Behavior = ActiveBody ModuleTag_Body
    MaxHealth = 4500
  End
End
"""


def test_building_levels_detect_an_experience_only_rank_ladder():
    # No LevelUpUpgrade: the building still levels because its ExperienceLevel ladder has more
    # than one rank, earned by RequiredExperience. All three ranks become columns.
    levels = building_levels(load(EXP_LEVELED_FIXTURE).objects["TestOutpost"])
    assert [rank for _active, rank in levels] == [1, 2, 3]


def test_experience_only_building_stats_are_computed_per_level():
    fields = computed_fields(load(EXP_LEVELED_FIXTURE).objects["TestOutpost"])
    assert fields["health1"] == "4500"
    assert fields["health2"] == "6000"  # + OutpostHealthLvl2 1500
    assert fields["health3"] == "6000"  # rank 3 adds no HEALTH modifier, so it holds
    assert "health" not in fields  # leveled building uses the suffixed columns only


def test_building_units_table_lists_unit_build_targets():
    game = recruit_game()
    rows = building_units(game, game.objects["TestBarracks"])
    # Each UNIT_BUILD button: name, blank type, cost, command points, shortcut. The Sell
    # button is not a build button, so it is dropped.
    assert rows == [
        ["Soldiers", "", "200", "60", "Y"],
        ["Pikemen", "", "300", "60", "X"],
    ]


def test_building_heroes_index_revive_slots_against_buildable_heroes():
    game = recruit_game()
    heroes = building_heroes(game, game.objects["TestBarracks"])
    # The revive order is [RingHeroDummy, CreateAHero, PippinFiller, HeroAlpha, LockedHero,
    # HeroBeta]; every REVIVE slot advances the index, but only the two without NEED_UPGRADE
    # (mapping to HeroAlpha and HeroBeta) recruit. Placeholders and locked slots are skipped.
    assert [hero.name for hero in heroes] == ["HeroAlpha", "HeroBeta"]


# A plain resource building (no levels): its production interval carries the `seconds` unit.
RESOURCE_FIXTURE = """
Object FarmHouse
  KindOf = STRUCTURE
  Behavior = ActiveBody ModuleTag_Body
    MaxHealth = 1000
  End
  Behavior = TerrainResourceBehavior ModuleTag_Money
    MaxIncome = 28
    IncomeInterval = 12000
  End
End
"""


def test_resource_interval_carries_the_seconds_unit():
    fields = computed_fields(load(RESOURCE_FIXTURE).objects["FarmHouse"])
    assert fields["resources"] == "28"
    assert fields["interval"] == "12 seconds"


def test_generate_building_page_has_recruitment_and_hero_tables():
    game = recruit_game()
    page = generate_page(game, game.objects["TestBarracks"], "Gondor")
    assert "== Unit Production ==" in page
    assert "This structure produces the following units:" in page
    assert '{| class="article-table"' in page
    assert "! Name\n! Type\n! Cost\n! CP Cost\n! Shortcut" in page
    assert "| Soldiers\n|\n| 200\n| 60\n| Y" in page
    # The hero table follows, indexed from the REVIVE slots, with editorial columns blank.
    assert "It can also recruit the following heroes:" in page
    assert "! Name\n! Weapon(s)\n! Role\n! Cost\n! Importance" in page
    assert "| Alpha\n|\n|\n| 1100\n|" in page
    # Abilities/upgrades still render for a building.
    assert "== Abilities ==" in page


def test_generate_page_hyperlinks_recruited_names_that_have_a_page():
    game = recruit_game()
    # The wiki has pages for Soldiers and Alpha, but not Pikemen or Beta.
    linker = build_linker(game, {"Soldiers", "Alpha"})
    page = generate_page(game, game.objects["TestBarracks"], "Gondor", linker=linker)
    # The unit and hero name cells link only where a page exists; the rest stay plain.
    assert "| [[Soldiers]]\n" in page
    assert "| Pikemen\n" in page
    assert "| [[Alpha]]\n" in page
    assert "| Beta\n" in page


def test_building_units_links_known_names_only():
    game = recruit_game()
    linker = build_linker(game, {"Soldiers"})
    rows = building_units(game, game.objects["TestBarracks"], linker)
    assert rows[0][0] == "[[Soldiers]]"  # has a page
    assert rows[1][0] == "Pikemen"  # no page, left plain


def test_ability_block_hyperlinks_units_named_in_the_description():
    game = recruit_game()
    linker = build_linker(game, {"Soldiers"})
    entry = {
        "name": "Rally",
        "image": "",
        "shortcut": None,
        "level": None,
        "requirement": None,
        "description": "Summons Soldiers to the front.",
        "cooldown": None,
    }
    assert "|description=Summons [[Soldiers]] to the front." in ability_block(entry, linker)


def test_active_upgrade_swaps_command_set():
    game = load(UPGRADE_FIXTURE)
    game.strings.update(_UPGRADE_STRINGS)
    obj = game.objects["UpgradeHero"]

    assert [e["name"] for e in command_entries(game, obj)] == ["Base Power"]
    upgraded = command_entries(game, obj, {"Upgrade_Reinforced"})
    assert [e["name"] for e in upgraded] == ["Base Power", "Extra Power"]
    # The same upgrade reaches generate_page's ability section.
    page = generate_page(game, obj, "Gondor", {"Upgrade_Reinforced"})
    assert "|name=Extra Power" in page
