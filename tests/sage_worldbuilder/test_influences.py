"""The influence views' ranges: sight from the template, weapon range from its default weapon
set, and an object's customized ambient sound ranges."""

from types import SimpleNamespace

from sage_worldbuilder.influences import Influences, sound_ranges


def weapon_set(conditions, *ranges):
    weapons = [("PRIMARY", SimpleNamespace(AttackRange=value)) for value in ranges]
    return SimpleNamespace(Conditions=conditions, Weapon=[*weapons, ("TERTIARY", None)])


def game(**objects):
    return SimpleNamespace(objects=objects)


def test_sight_is_the_templates_vision_range_whatever_the_names_case():
    influences = Influences(game(Archer=SimpleNamespace(VisionRange=395.0)))
    assert influences.sight_range("archer") == 395.0
    assert influences.sight_range("Missing") is None


def test_the_weapon_range_is_the_longest_in_the_default_weapon_set():
    archer = SimpleNamespace(
        WeaponSet=[
            weapon_set(["WEAPONSET_TOGGLE_1"], 900.0),
            weapon_set([None], 365.0, 390.0),
        ]
    )
    assert Influences(game(Archer=archer)).weapon_range("Archer") == 390.0


def test_without_a_default_set_the_first_is_used_and_unknown_ranges_are_skipped():
    tower = SimpleNamespace(WeaponSet=[weapon_set(["GARRISONED"], 250.0, "RANGE_MACRO")])
    influences = Influences(game(Tower=tower, Wall=SimpleNamespace()))
    assert influences.weapon_range("Tower") == 250.0
    assert influences.weapon_range("Wall") is None


def test_sound_ranges_come_from_a_customized_ambient_sound_only():
    def placed(**properties):
        return SimpleNamespace(properties={k: {"value": v} for k, v in properties.items()})

    customized = placed(
        objectSoundAmbientCustomized=True,
        objectSoundAmbientMinRange=200.0,
        objectSoundAmbientMaxRange=500.0,
    )
    assert sound_ranges(customized) == (200.0, 500.0)
    assert sound_ranges(placed(objectSoundAmbientCustomized=False)) is None
    assert sound_ranges(placed(objectSoundAmbientCustomized=True)) is None
    assert sound_ranges(placed()) is None
