"""Data-free tests for `sage_cah.gamedata`: a miniature game tree is written to disk and
scanned, so these check the extraction (ordered classes, per-class powers, the two ways a bling
index counts) against data whose right answer is written out here, not against a real install."""

from pathlib import Path

import pytest

from sage_cah.gamedata import scan_ini_root

_COMMAND_BUTTONS = """
CommandButton Command_CreateAHero_Slash
    Command                        = SPECIAL_POWER
    TextLabel                      = CONTROLBAR:Slash
    CreateAHeroUIAllowableUpgrades = Upgrade_Class_Captain
    CreateAHeroUIMinimumLevel      = 1
    CreateAHeroUIPrerequisiteButtonName = None
End

CommandButton Command_CreateAHero_Slash2
    Command                        = SPECIAL_POWER
    TextLabel                      = CONTROLBAR:Slash2
    CreateAHeroUIAllowableUpgrades = Upgrade_Class_Captain
    CreateAHeroUIMinimumLevel      = 5
    CreateAHeroUIPrerequisiteButtonName = Command_CreateAHero_Slash
End

CommandButton Command_CreateAHero_Roar
    Command                        = SPECIAL_POWER
    CreateAHeroUIAllowableUpgrades = Upgrade_Class_Troll
    CreateAHeroUIMinimumLevel      = 3
End

CommandButton Command_AttackMove
    Command = ATTACK_MOVE
End
"""

_SYSTEM = """
CreateAHeroSystem
    WeaponGroupName = CreateAHero_Weapon

    CreateAHeroBlingBinder
        GroupName      = CreateAHero_ArmorAttribute
        LabelTag       = CAH:ArmorMenuLabel
        UISlot         = 0
        BlingType      = ATTRIBUTE
    End

    CreateAHeroBlingBinder
        GroupName      = CreateAHero_Helmet
        LabelTag       = CAH:HelmetMenuLabel
        UISlot         = 1
        BlingType      = APPEARANCE
    End

    CreateAHeroBling
        GroupName        = CreateAHero_ArmorAttribute
        BlingUpgradeName = Upgrade_Armor01
    End
    CreateAHeroBling
        GroupName        = CreateAHero_ArmorAttribute
        BlingUpgradeName = Upgrade_Armor02
    End
    CreateAHeroBling
        GroupName        = CreateAHero_ArmorAttribute
        BlingUpgradeName = Upgrade_Armor03
    End

    CreateAHeroBling
        NameTag          = CAH:BareHead
        GroupName        = CreateAHero_Helmet
        BlingUpgradeName = Upgrade_NoHelmet
    End
    CreateAHeroBling
        NameTag          = CAH:CaptainHelm
        GroupName        = CreateAHero_Helmet
        BlingUpgradeName = Upgrade_CaptainHelm
    End
    CreateAHeroBling
        NameTag          = CAH:TrollHelm
        GroupName        = CreateAHero_Helmet
        BlingUpgradeName = Upgrade_TrollHelm
    End

#include "classes.inc"
End
"""

_CLASSES = """
CreateAHeroClass
    NameTag     = CAH:ClassCaptain
    UpgradeName = Upgrade_Class_Captain

    SubClass
        NameTag       = CAH:SubClassGondor
        UpgradeName   = Upgrade_SubClass_0
        BlingUpgrades = Upgrade_NoHelmet @Upgrade_CaptainHelm
    End

    SubClass
        NameTag       = CAH:SubClassRohan
        UpgradeName   = Upgrade_SubClass_1
        BlingUpgrades = Upgrade_CaptainHelm
    End
End

CreateAHeroClass
    NameTag     = CAH:ClassTroll
    UpgradeName = Upgrade_Class_Troll

    SubClass
        NameTag       = CAH:SubClassHillTroll
        UpgradeName   = Upgrade_SubClass_0
        BlingUpgrades = Upgrade_TrollHelm Upgrade_NoHelmet
    End
End
"""

_STRINGS = """CONTROLBAR:Slash
"Slash"
END

CONTROLBAR:Slash2
"Mighty Slash"
END

CAH:ClassCaptain
"Captain"
END

CAH:ClassTroll
"Troll"
END

CAH:SubClassGondor
"Captain of Gondor"
END

CAH:SubClassRohan
"Rider of Rohan"
END

CAH:SubClassHillTroll
"Hill Troll"
END

CAH:ArmorMenuLabel
"Armour"
END

CAH:HelmetMenuLabel
"Helmet"
END

CAH:BareHead
"Bare head"
END

CAH:CaptainHelm
"Captain's helm"
END

CAH:TrollHelm
"Troll helm"
END
"""


@pytest.fixture(scope="module")
def game_root(tmp_path_factory) -> Path:
    """A miniature game tree: two hero classes, three CaH powers and two bling groups."""
    root = tmp_path_factory.mktemp("game")
    ini = root / "data" / "ini"
    ini.mkdir(parents=True)
    (ini / "commandbutton.ini").write_text(_COMMAND_BUTTONS, encoding="utf-8")
    (ini / "createaherosystem.ini").write_text(_SYSTEM, encoding="utf-8")
    (ini / "classes.inc").write_text(_CLASSES, encoding="utf-8")
    (root / "data" / "lotr.str").write_text(_STRINGS, encoding="utf-8")
    return root


@pytest.fixture(scope="module")
def data(game_root: Path):
    return scan_ini_root(game_root)


def test_classes_come_through_in_declaration_order_with_their_sub_classes(data):
    """`class_index` counts the CreateAHeroClass blocks as the data declares them - which is
    the only way to read a .cah whose mod reorders or drops one."""
    assert [hero_class.name for hero_class in data.classes] == ["Captain", "Troll"]
    assert data.classes[0].upgrade == "Upgrade_Class_Captain"
    assert [sub.name for sub in data.classes[0].sub_classes] == [
        "Captain of Gondor",
        "Rider of Rohan",
    ]
    assert data.sub_class(1, 0).name == "Hill Troll"
    assert data.hero_class(7) is None
    assert data.sub_class(0, 9) is None


def test_only_create_a_hero_buttons_are_powers(data):
    """A CommandButton without CreateAHeroUIAllowableUpgrades is an ordinary in-game button."""
    names = [power.command_button for power in data.powers]
    assert names == [
        "Command_CreateAHero_Roar",
        "Command_CreateAHero_Slash",
        "Command_CreateAHero_Slash2",
    ]


def test_a_power_carries_its_label_level_and_prerequisite(data):
    power = next(p for p in data.powers if p.command_button == "Command_CreateAHero_Slash2")

    assert power.display == "Mighty Slash"
    assert power.min_level == 5
    assert power.prerequisite == "Command_CreateAHero_Slash"

    first = next(p for p in data.powers if p.command_button == "Command_CreateAHero_Slash")
    assert first.prerequisite is None  # `None` in the ini means no prerequisite, not a button
    assert next(p for p in data.powers if p.command_button.endswith("Roar")).display.endswith(
        "Roar"
    )  # no TextLabel: the raw name stands in


def test_powers_are_filtered_to_the_class_that_may_buy_them(data):
    assert [p.command_button for p in data.powers_for(0)] == [
        "Command_CreateAHero_Slash",
        "Command_CreateAHero_Slash2",
    ]
    assert [p.command_button for p in data.powers_for(1)] == ["Command_CreateAHero_Roar"]
    assert data.powers_for(4) == ()  # unknown class: no filter, the caller falls back


def test_bling_groups_carry_their_type_label_and_options(data):
    armour = data.group("createahero_armorattribute")  # matched case-insensitively
    helmet = data.group("CreateAHero_Helmet")

    assert armour.is_attribute and armour.display == "Armour"
    assert [option.upgrade for option in armour.options] == [
        "Upgrade_Armor01",
        "Upgrade_Armor02",
        "Upgrade_Armor03",
    ]
    assert not helmet.is_attribute and helmet.ui_slot == 1
    assert data.group("CreateAHero_Boots") is None


def test_an_attribute_index_counts_into_the_whole_group(data):
    """Stat groups are shared: index 0 is in-game value 1 whichever class holds it."""
    choices = data.bling_choices("CreateAHero_ArmorAttribute", 0, 0)

    assert [option.upgrade for option in choices] == [
        "Upgrade_Armor01",
        "Upgrade_Armor02",
        "Upgrade_Armor03",
    ]
    assert data.bling_choices("CreateAHero_ArmorAttribute", 1, 0) == choices


def test_an_appearance_index_counts_into_the_sub_class_own_list(data):
    """The same helmet index means a different helmet per sub-class, in the order that
    sub-class's BlingUpgrades list them (the `@` marking its default is not part of the name)."""
    gondor = data.bling_choices("CreateAHero_Helmet", 0, 0)
    rohan = data.bling_choices("CreateAHero_Helmet", 0, 1)
    troll = data.bling_choices("CreateAHero_Helmet", 1, 0)

    assert [option.display for option in gondor] == ["Bare head", "Captain's helm"]
    assert [option.display for option in rohan] == ["Captain's helm"]
    assert [option.display for option in troll] == ["Troll helm", "Bare head"]
    assert data.bling_choices("CreateAHero_Helmet", 9, 0) == ()


def test_a_tree_without_create_a_hero_data_scans_to_nothing(tmp_path):
    """An empty scan is the "no completion available" case the editor falls back on, not an
    error - pointing it at the wrong folder must not raise."""
    (tmp_path / "data" / "ini").mkdir(parents=True)
    (tmp_path / "data" / "ini" / "weapon.ini").write_text("Weapon Sword\nEnd\n", encoding="utf-8")

    data = scan_ini_root(tmp_path)

    assert data.classes == ()
    assert data.powers == ()
    assert data.bling_groups == ()
