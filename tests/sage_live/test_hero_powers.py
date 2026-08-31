"""Reading a hero's own abilities off its command set, and the four ways that goes wrong.

`Statics.spell_book` looks like it should answer this and does not. Every case below is one of
the reasons, and each was measured against RotWK 2.01 + Edain before it was written down:

- a hero splits one ability over two or three modules and the first is almost always the one that
  says nothing about the effect, so first-won classification put the **entire** Men roster at
  `EFFECT_GRANT`, which `AIMABLE` filters out;
- two module shapes carry a hero's meaning and no spellbook uses either;
- a weapon fired at an *ally* is the same module shape as one fired at an enemy, and only the
  button distinguishes them;
- three of a hero's `SPECIAL_POWER` buttons are not abilities at all.

Data-free, like `test_statics`: the stand-ins are the shapes the real tree writes, named after
the abilities they were copied from.
"""

from __future__ import annotations

from sage_live.utils.statics import (
    CAST_LOCATION,
    CAST_OBJECT,
    CAST_SELF,
    EFFECT_BUFF,
    EFFECT_BUILD,
    EFFECT_HEAL,
    EFFECT_SELF_BUFF,
    EFFECT_STRIKE,
    EFFECT_SUMMON,
    EFFECT_UNKNOWN,
    Statics,
)
from tests.sage_live.test_statics import FakeGame, FakeModule, FakeObject, _link

# The effects a caller can actually aim a hero ability at. `EFFECT_BUILD` is absent because no
# hero on any roster measured places a structure, and `EFFECT_GRANT` / `EFFECT_UNKNOWN` are the
# data declining to say what a power does. A consumer that aims abilities (a bot) keeps its own
# copy of this policy; here it is only the yardstick for "the walk placed this power".
AIMABLE = (EFFECT_SELF_BUFF, EFFECT_BUFF, EFFECT_HEAL, EFFECT_STRIKE, EFFECT_SUMMON)


class FakeButton:
    """A `CommandButton`. Only `fields` is read, plus the declared `Command` in the name line."""

    def __init__(self, command: str, fields: dict[str, str]) -> None:
        self.fields = {"Command": command, **fields}
        self._fields = self.fields
        self.name = ""


class FakeSet:
    """A `CommandSet`: slot number to button name, which is all `command_buttons` walks."""

    def __init__(self, slots: dict[int, str]) -> None:
        self.fields = {str(slot): name for slot, name in slots.items()}
        self._fields = self.fields


class FakeOCL:
    """An `ObjectCreationList`. `creates` walks the typed `CreateObject` entries, not the raw
    fields, because the real model parses each `CreateObject` block into one."""

    def __init__(self, *names: str) -> None:
        self.fields: dict[str, str] = {}
        self._fields = self.fields
        self.CreateObject = [FakeModule({"ObjectNames": " ".join(names)})]


class FakePower:
    """A `SpecialPower` block - the recharge and the radius, and nothing about the effect."""

    def __init__(self, reload_ms: int = 60000, radius: float = 0.0) -> None:
        self.fields = {"ReloadTime": str(reload_ms), "RadiusCursorRadius": str(radius)}
        self._fields = self.fields
        self.ReloadTime = reload_ms
        self.RadiusCursorRadius = radius


def _hero() -> Statics:
    """One hero carrying every shape that matters, copied from the Men roster.

    The module *order* is deliberate and is the point of half these tests: on the real tree the
    `UnpauseSpecialPowerUpgrade` is declared first for every ability, and it carries the unlock
    level and nothing else.
    """
    objects = {
        "TestHero": FakeObject(
            {"KindOf": "INFANTRY HERO SELECTABLE", "CommandSet": "TestHeroCommandSet"},
            modules=[
                # Wizard Blast: a weapon at an enemy, with the approach the caster must close.
                FakeModule(
                    {"SpecialPowerTemplate": "AbilityBlast", "TriggeredBy": "Upgrade_Level_1"},
                    "UnpauseSpecialPowerUpgrade",
                ),
                FakeModule(
                    {"SpecialPowerTemplate": "AbilityBlast", "StartsPaused": "Yes"},
                    "SpecialPowerModule",
                ),
                FakeModule(
                    {
                        "SpecialPowerTemplate": "AbilityBlast",
                        "SpecialWeapon": "TestBlastWeapon",
                        "StartAbilityRange": "80.0",
                    },
                    "WeaponFireSpecialAbilityUpdate",
                ),
                # Blade Master: a modifier on the caster and nobody else.
                FakeModule(
                    {"SpecialPowerTemplate": "AbilityBlades", "TriggeredBy": "Upgrade_Level_6"},
                    "UnpauseSpecialPowerUpgrade",
                ),
                FakeModule(
                    {
                        "SpecialPowerTemplate": "AbilityBlades",
                        "HeroAttributeModifier": "TestBladeModifier",
                        "HeroEffectDuration": "30000",
                    },
                    "HeroModeSpecialAbilityUpdate",
                ),
                # Horn of Gondor: a modifier over everyone on our side.
                FakeModule(
                    {"SpecialPowerTemplate": "AbilityHorn", "TriggeredBy": "Upgrade_Level_3"},
                    "UnpauseSpecialPowerUpgrade",
                ),
                FakeModule(
                    {
                        "SpecialPowerTemplate": "AbilityHorn",
                        "AttributeModifier": "TestHornBuff",
                        "AttributeModifierAffects": "ANY +INFANTRY ALLIES",
                        "AttributeModifierRange": "9999999.0",
                    },
                    "SpecialPowerModule",
                ),
                # TalkToMe: the same weapon shape as the blast, pointed at a friend.
                FakeModule(
                    {"SpecialPowerTemplate": "AbilityTalk", "SpecialWeapon": "TestTalkWeapon"},
                    "WeaponFireSpecialAbilityUpdate",
                ),
                # A summon, through an OCL, at a level nothing has reached.
                FakeModule(
                    {"SpecialPowerTemplate": "AbilitySummon", "TriggeredBy": "Upgrade_Level_10"},
                    "UnpauseSpecialPowerUpgrade",
                ),
                FakeModule(
                    {"SpecialPowerTemplate": "AbilitySummon", "OCL": "OCL_TestSummon"},
                    "OCLSpecialPower",
                ),
                # Last Stand: nothing anywhere says what it does.
                FakeModule(
                    {"SpecialPowerTemplate": "AbilityMystery", "TriggeredBy": "Upgrade_Level_1"},
                    "UnpauseSpecialPowerUpgrade",
                ),
                FakeModule(
                    {"SpecialPowerTemplate": "AbilityMystery", "StartsPaused": "Yes"},
                    "SpecialPowerModule",
                ),
                # The two passive-aura portraits and the mount toggle live on the buttons.
                FakeModule(
                    {"SpecialPowerTemplate": "AbilityAura", "StartsPaused": "Yes"},
                    "SpecialPowerModule",
                ),
                FakeModule(
                    {"SpecialPowerTemplate": "AbilityMount", "StartsPaused": "Yes"},
                    "SpecialPowerModule",
                ),
            ],
        ),
        "TestSummonedHorde": FakeObject({"KindOf": "INFANTRY SELECTABLE HORDE"}),
    }
    buttons = {
        "Command_Blast": FakeButton(
            "SPECIAL_POWER",
            {"SpecialPower": "AbilityBlast", "Options": "NEED_TARGET_ENEMY_OBJECT"},
        ),
        "Command_Blades": FakeButton("SPECIAL_POWER", {"SpecialPower": "AbilityBlades"}),
        "Command_Horn": FakeButton("SPECIAL_POWER", {"SpecialPower": "AbilityHorn"}),
        "Command_Talk": FakeButton(
            "SPECIAL_POWER",
            {"SpecialPower": "AbilityTalk", "Options": "NEED_TARGET_ALLY_OBJECT"},
        ),
        "Command_Summon": FakeButton(
            "SPECIAL_POWER",
            {"SpecialPower": "AbilitySummon", "Options": "NEED_TARGET_POS CONTEXTMODE_COMMAND"},
        ),
        "Command_Mystery": FakeButton("SPECIAL_POWER", {"SpecialPower": "AbilityMystery"}),
        "Command_Aura": FakeButton(
            "SPECIAL_POWER", {"SpecialPower": "AbilityAura", "Options": "NONPRESSABLE"}
        ),
        "Command_Mount": FakeButton(
            "SPECIAL_POWER",
            {"SpecialPower": "AbilityMount", "Options": "TOGGLE_IMAGE_ON_WEAPONSET ON_GROUND_ONLY"},
        ),
        "Command_AttackMove": FakeButton("ATTACK_MOVE", {}),
        "Command_Stop": FakeButton("STOP", {}),
    }
    sets = {
        "TestHeroCommandSet": FakeSet(
            {
                1: "Command_Blast",
                2: "Command_Blades",
                3: "Command_Horn",
                4: "Command_Talk",
                5: "Command_Summon",
                6: "Command_Mystery",
                7: "Command_Aura",
                8: "Command_Mount",
                13: "Command_AttackMove",
                14: "Command_Stop",
            }
        )
    }
    powers = {
        "AbilityBlast": FakePower(40000),
        "AbilityBlades": FakePower(120000),
        "AbilityHorn": FakePower(120000),
        "AbilityTalk": FakePower(300000),
        "AbilitySummon": FakePower(240000, radius=100.0),
        "AbilityMystery": FakePower(1),
        "AbilityAura": FakePower(1),
        "AbilityMount": FakePower(1),
    }
    ocls = {"OCL_TestSummon": FakeOCL("TestSummonedHorde")}
    return Statics(
        FakeGame(
            _link(objects),
            commandsets=sets,
            commandbuttons=buttons,
            specialpowers=powers,
            objectcreationlists=ocls,
        )
    )


def _egg_hero() -> Statics:
    """A hero whose two OCL abilities both create something that *spawns*.

    One creates an inert marker that hatches a battalion - the Beregond shape - and the other
    raises a tower that spawns its own guard. They must not classify the same way.
    """
    objects = {
        "EggHero": FakeObject(
            {"KindOf": "INFANTRY HERO SELECTABLE", "CommandSet": "EggHeroCommandSet"},
            modules=[
                FakeModule(
                    {"SpecialPowerTemplate": "AbilityHatch", "OCL": "OCL_TestEgg"},
                    "OCLSpecialPower",
                ),
                FakeModule(
                    {"SpecialPowerTemplate": "AbilityRaise", "OCL": "OCL_TestTower"},
                    "OCLSpecialPower",
                ),
            ],
        ),
        # The marker: no body worth the name, no side, and a spawn behaviour that is the whole
        # point of it. `INERT UNATTACKABLE` is exactly what `BeregondKompanieObject` carries.
        "TestEggObject": FakeObject(
            {"KindOf": "INERT UNATTACKABLE"},
            modules=[FakeModule({"SpawnTemplateName": "TestSummonedHorde"})],
        ),
        "TestSummonedHorde": FakeObject({"KindOf": "INFANTRY SELECTABLE HORDE"}),
        # A building that spawns a garrison, which is every tower and every creep lair.
        "TestSpawningTower": FakeObject(
            {"KindOf": "STRUCTURE IMMOBILE SELECTABLE"},
            modules=[FakeModule({"SpawnTemplateName": "TestSummonedHorde"})],
        ),
    }
    buttons = {
        "Command_Hatch": FakeButton("SPECIAL_POWER", {"SpecialPower": "AbilityHatch"}),
        "Command_Raise": FakeButton("SPECIAL_POWER", {"SpecialPower": "AbilityRaise"}),
    }
    sets = {"EggHeroCommandSet": FakeSet({1: "Command_Hatch", 2: "Command_Raise"})}
    powers = {"AbilityHatch": FakePower(90000), "AbilityRaise": FakePower(90000)}
    ocls = {"OCL_TestEgg": FakeOCL("TestEggObject"), "OCL_TestTower": FakeOCL("TestSpawningTower")}
    return Statics(
        FakeGame(
            _link(objects),
            commandsets=sets,
            commandbuttons=buttons,
            specialpowers=powers,
            objectcreationlists=ocls,
        )
    )


def _by_power(statics: Statics, name: str):  # noqa: ANN202
    return next((p for p in statics.hero_powers("TestHero") if p.power == name), None)


def test_the_abilities_are_read_off_the_heros_own_command_set() -> None:
    """The `SPECIAL_POWER` buttons and nothing else - a move and a stop are on every hero's
    command set and neither is an ability."""
    found = {p.power for p in _hero().hero_powers("TestHero")}
    assert found == {
        "AbilityBlast",
        "AbilityBlades",
        "AbilityHorn",
        "AbilityTalk",
        "AbilitySummon",
        "AbilityMystery",
    }


def test_a_passive_aura_portrait_is_not_a_button() -> None:
    """`NONPRESSABLE`. Beregond carries two of these and firing them is not a thing the control
    bar can do either - the portrait shows an aura that is always on."""
    assert _by_power(_hero(), "AbilityAura") is None


def test_a_mount_toggle_is_not_an_ability() -> None:
    """`TOGGLE_IMAGE_ON_WEAPONSET` is a real decision and not one a stage hunting for something to
    cast can make: fired blind on Gandalf it puts him back on foot."""
    assert _by_power(_hero(), "AbilityMount") is None


def test_the_effect_survives_being_spread_over_several_modules() -> None:
    """**The bug this whole walk exists for.** `_spell_modules` keeps the first module per power
    and a hero's first is the `UnpauseSpecialPowerUpgrade`, which carries the unlock level and
    nothing else - so first-won classification answered `EFFECT_GRANT` for every ability on every
    hero of the Men roster, and `AIMABLE` then filtered the lot."""
    assert _by_power(_hero(), "AbilityBlast").effect == EFFECT_STRIKE


def test_a_modifier_on_the_caster_is_told_from_one_on_the_army() -> None:
    """Two different aims and one word between them. A self buff wants the hero to be in a fight;
    an ally buff wants the densest part of the army, which for a self buff is somebody else."""
    assert _by_power(_hero(), "AbilityBlades").effect == EFFECT_SELF_BUFF
    assert _by_power(_hero(), "AbilityHorn").effect == EFFECT_BUFF


def test_a_weapon_pointed_at_a_friend_is_not_a_strike() -> None:
    """The same `WeaponFireSpecialAbilityUpdate` as the blast, and only the button says which way
    it points. Beregond has four of these; read from the module alone, half his kit is an attack
    on our own battalions."""
    talk = _by_power(_hero(), "AbilityTalk")
    assert talk.effect == EFFECT_UNKNOWN
    assert not talk.hostile


def test_an_ability_the_data_cannot_place_is_reported_rather_than_guessed() -> None:
    """Boromir's Last Stand and Gandalf's Lightning Sword are both like this on the real tree: a
    `SpecialPowerModule` that says only that the power starts paused, and the effect delivered
    somewhere this walk cannot see.

    `EFFECT_GRANT` rather than `EFFECT_UNKNOWN`, which is a distinction worth keeping even though
    both are unaimable: unknown means a chain was followed and named no side, and grant means
    there was no chain to follow. Neither is guessed at, which is the property that matters - a
    wrong guess spends a recharge helping the wrong army."""
    assert _by_power(_hero(), "AbilityMystery").effect not in AIMABLE


def test_a_summon_is_still_read_through_its_ocl() -> None:
    """The one shape heroes share with the spellbook, and it must keep working."""
    summon = _by_power(_hero(), "AbilitySummon")
    assert summon.effect == EFFECT_SUMMON
    assert summon.spawns == ("TestSummonedHorde",)


def test_a_summon_delivered_by_an_egg_that_spawns_is_still_a_summon() -> None:
    """**Beregond's level-1 ability, and it read as unaimable until the fallback existed.**
    `OCL_SummonBeregondKompanie` creates one `INERT UNATTACKABLE` marker with a 40-second lifetime
    and six `SpawnBehavior` modules; through the OCL alone that is a piece of scenery naming no
    side. The hero the shipped Men plan buys would have had nothing to fire until level 3."""
    statics = _egg_hero()
    hatching = next(p for p in statics.hero_powers("EggHero") if p.power == "AbilityHatch")

    assert hatching.effect == EFFECT_SUMMON
    assert hatching.spawns == ("TestSummonedHorde",)


def test_a_structure_that_spawns_is_still_a_building() -> None:
    """**The guard on the rule above, and it is not hypothetical.** Buildings spawn things too - a
    creep lair spawns slaves, Isengard's summoned lumber mill spawns workers, the Lone Tower spawns
    its guard - so asking the spawns before testing for a structure turned three correct
    `EFFECT_BUILD` powers into summons. A build is aimed at our own base and a summon at their
    army, so Untamed Allegiance would have gone from placing lairs at home to placing them on the
    enemy."""
    statics = _egg_hero()
    building = next(p for p in statics.hero_powers("EggHero") if p.power == "AbilityRaise")

    assert building.effect == EFFECT_BUILD
    assert building.spawns == ("TestSpawningTower",)


def test_the_cast_form_comes_from_the_button() -> None:
    """A power sent through the wrong constructor is accepted, charged nothing and does nothing.
    The `NEED_TARGET_*` bits decide it, exactly as they do for a spellbook power."""
    assert _by_power(_hero(), "AbilityBlast").form == CAST_OBJECT
    assert _by_power(_hero(), "AbilitySummon").form == CAST_LOCATION
    assert _by_power(_hero(), "AbilityBlades").form == CAST_SELF


def test_the_unlock_level_is_carried() -> None:
    """The gate is an `Upgrade_Level_N` on an `UnpauseSpecialPowerUpgrade`, and it is OBJECT-scoped
    - so the live answer is a set test against the hero's own `GameObject.upgrades` rather than an
    experience counter a bot would have to keep and could not seed after attaching mid-match."""
    assert _by_power(_hero(), "AbilityBlast").unlocked_by == "Upgrade_Level_1"
    assert _by_power(_hero(), "AbilityBlades").unlocked_by == "Upgrade_Level_6"


def test_an_ability_with_no_unlock_is_open() -> None:
    """Not every ability is gated - Gandalf's shield bubble carries no unpause module at all - and
    a missing gate must read as open rather than as permanently shut."""
    talk = _by_power(_hero(), "AbilityTalk")
    assert talk.unlocked_by == ""
    assert talk.unlocked_for(set())


def test_the_level_gate_is_matched_lowercased() -> None:
    """A live observation spells an upgrade however the engine registered it, which is not always
    how the ini declares it - the same reason `held_by` lowercases both scopes."""
    blast = _by_power(_hero(), "AbilityBlast")
    assert blast.unlocked_for({"upgrade_level_1"})
    assert not blast.unlocked_for({"upgrade_level_2"})


def test_the_approach_range_is_carried() -> None:
    """`StartAbilityRange` is a walk rather than a filter: the engine closes the distance before
    the ability fires, so an ability aimed past it is a hero sent there alone."""
    assert _by_power(_hero(), "AbilityBlast").ability_range == 80.0
    assert _by_power(_hero(), "AbilityHorn").ability_range == 0.0


def test_a_unit_with_no_command_set_has_no_abilities() -> None:
    """Most of the army. The answer is empty rather than an error."""
    assert _hero().hero_powers("TestSummonedHorde") == ()
