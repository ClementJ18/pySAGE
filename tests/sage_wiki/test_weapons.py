"""Tests for the compact weapon summary (sage_wiki.weapons)."""

import pytest

import sage_ini.model.definitions  # noqa: F401  (register classes)
from sage_ini.model.game import Game
from sage_ini.model.state import UnitState
from sage_ini.parser.blockparser import parse
from sage_wiki.weapons import weapon_summary_lines

# Peripheral package (sage_wiki, deferred project): full suite only.
pytestmark = pytest.mark.full

TROLL_FIXTURE = """
Weapon MordorCaveTrollPunch
  AttackRange = 12
  MeleeWeapon = Yes
  DamageNugget
    Damage = 150
    Radius = 50.0
    DamageType = WATER
    DamageScalar = 250% ANY +HERO +MACHINE +MONSTER
    DamageScalar = 0% ANY +STRUCTURE
  End
  DamageNugget
    Damage = 240
    Radius = 30.0
    DamageType = SIEGE
    DamageScalar = 0% ALL -STRUCTURE ENEMIES
  End
  MetaImpactNugget
    ShockWaveAmount = 20.0
    ShockWaveRadius = 50.0
    HeroResist = 1.0
  End
End
Object TrollUnit
  WeaponSet
    Conditions = None
    Weapon = PRIMARY MordorCaveTrollPunch
  End
  Behavior = ActiveBody ModuleTag_Body
    MaxHealth = 4000
  End
End
"""


def _state() -> UnitState:
    game = Game()
    result = parse(TROLL_FIXTURE, file="t.ini")
    assert not result.diagnostics
    game.load_document(result.document)
    return UnitState(game.objects["TrollUnit"]), game.weapons["MordorCaveTrollPunch"]


def test_troll_punch_summary_matches_the_target_layout():
    state, weapon = _state()
    # The general line carries the bonus and the knockback; the structure-only nugget is its own
    # line. Radius comes from each nugget's own Radius (the first is 50, not the ToDo mock's 30).
    assert weapon_summary_lines(weapon, state) == [
        "'''vs General''': 150 WATER (50R)",
        "* +150% vs Single",
        "* Knockback (50R) vs Non-hero",
        "'''vs Structure''': 240 SIEGE (30R)",
    ]


def test_knockback_target_is_all_when_heroes_are_not_resistant():
    game = Game()
    result = parse(
        "Weapon W\n"
        "  DamageNugget\n    Damage = 100\n    Radius = 10\n  End\n"
        "  MetaImpactNugget\n    ShockWaveRadius = 20\n    HeroResist = 0.5\n  End\n"
        "End\n"
        "Object O\n  WeaponSet\n    Conditions = None\n    Weapon = PRIMARY W\n  End\n"
        "  Behavior = ActiveBody ModuleTag_Body\n    MaxHealth = 1\n  End\nEnd\n",
        file="t.ini",
    )
    assert not result.diagnostics
    game.load_document(result.document)
    state = UnitState(game.objects["O"])
    # HeroResist < 1 throws everyone, so the knockback target is All.
    # This nugget declares no DamageType, so the header carries the damage alone; the
    # knockback hangs below it as a bullet.
    assert weapon_summary_lines(game.weapons["W"], state) == [
        "'''vs General''': 100 (10R)",
        "* Knockback (20R) vs All",
    ]


def test_dot_nugget_renders_as_a_rate_and_duration_bullet():
    game = Game()
    result = parse(
        "Weapon PoisonBlade\n"
        "  DamageNugget\n    Damage = 30\n    Radius = 0\n    DamageType = SLASH\n  End\n"
        "  DOTNugget\n    Damage = 20\n    DamageType = POISON\n"
        "    DamageInterval = 1000\n    DamageDuration = 30000\n  End\n"
        "End\n"
        "Object O\n  WeaponSet\n    Conditions = None\n    Weapon = PRIMARY PoisonBlade\n  End\n"
        "  Behavior = ActiveBody ModuleTag_Body\n    MaxHealth = 1\n  End\nEnd\n",
        file="t.ini",
    )
    assert not result.diagnostics
    game.load_document(result.document)
    state = UnitState(game.objects["O"])
    # 20 dmg / 1000 ms tick = 20/s, over 30000 ms = 30s; hangs under the general header.
    assert weapon_summary_lines(game.weapons["PoisonBlade"], state) == [
        "'''vs General''': 30 SLASH",
        "* POISON DoT 20/s for 30s",
    ]


def test_dot_only_weapon_is_a_lone_line():
    game = Game()
    result = parse(
        "Weapon PoisonCloud\n"
        "  DOTNugget\n    Damage = 50\n    DamageType = POISON\n"
        "    DamageInterval = 500\n    DamageDuration = 10000\n  End\n"
        "End\n"
        "Object O\n  WeaponSet\n    Conditions = None\n    Weapon = PRIMARY PoisonCloud\n  End\n"
        "  Behavior = ActiveBody ModuleTag_Body\n    MaxHealth = 1\n  End\nEnd\n",
        file="t.ini",
    )
    assert not result.diagnostics
    game.load_document(result.document)
    state = UnitState(game.objects["O"])
    # No direct-damage nugget, so the DoT is a lone, unbulleted line. 50 per 500 ms = 100/s.
    assert weapon_summary_lines(game.weapons["PoisonCloud"], state) == ["POISON DoT 100/s for 10s"]


def test_single_target_weapon_omits_the_radius():
    game = Game()
    result = parse(
        "Weapon Bow\n  AttackRange = 200\n"
        "  DamageNugget\n    Damage = 40\n    Radius = 0\n    DamageType = PIERCE\n  End\nEnd\n"
        "Object Archer\n  WeaponSet\n    Conditions = None\n    Weapon = PRIMARY Bow\n  End\n"
        "  Behavior = ActiveBody ModuleTag_Body\n    MaxHealth = 1\n  End\nEnd\n",
        file="t.ini",
    )
    assert not result.diagnostics
    game.load_document(result.document)
    state = UnitState(game.objects["Archer"])
    assert weapon_summary_lines(game.weapons["Bow"], state) == ["'''vs General''': 40 PIERCE"]


def test_damage_modifiers_apply_to_the_summary():
    game = Game()
    result = parse(
        "ModifierList Buff\n  Modifier = DAMAGE_MULT 200%\nEnd\n"
        "Weapon Sword\n"
        "  DamageNugget\n    Damage = 50\n    Radius = 5\n    DamageType = SLASH\n  End\nEnd\n"
        "Object Hero\n  WeaponSet\n    Conditions = None\n    Weapon = PRIMARY Sword\n  End\n"
        "  Behavior = ActiveBody ModuleTag_Body\n    MaxHealth = 1\n  End\nEnd\n",
        file="t.ini",
    )
    assert not result.diagnostics
    game.load_document(result.document)
    state = UnitState(game.objects["Hero"])
    state.extra_modifiers = [game.modifiers["Buff"]]
    # DAMAGE_MULT 200% doubles the nugget damage in the rendered line.
    assert weapon_summary_lines(game.weapons["Sword"], state) == [
        "'''vs General''': 100 SLASH (5R)"
    ]
