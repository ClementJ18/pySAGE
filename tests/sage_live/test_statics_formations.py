"""Reading a battalion's alternate formation out of the ini tree.

Three things here are easy to get wrong and none of them reports an error.

**The link is a pair, not a direction.** `GondorFighterHorde` names `GondorFighterHordeBlock` as
its `AlternateFormation` and the block names the fighter straight back, so a reader that follows
the field answers for both halves - and a bot that trusts it toggles a braced battalion "into"
the wall it is already standing in. `ThisFormationIsTheMainFormation` is the only discriminator.

**A command set may name a button the tree does not declare**, and the engine draws nothing for
one it cannot find. So `AlternateFormation` is not sufficient authority to send the order: the
button has to exist and has to carry `HORDE_TOGGLE_FORMATION`.

**And the modifiers combine three different ways.** `SPEED` and `DAMAGE_MULT` are multipliers
where 1.0 is neutral; `ARMOR` is a summed fraction where 0.0 is, and it may be scoped to damage
types. `sage_ini.model.state` owns that arithmetic and these check it is being *asked* rather
than reimplemented.
"""

from __future__ import annotations

import pytest

from sage_ini.model.enums import DamageType, ModifierType
from sage_live.utils.statics import Statics


class FakeModule:
    """A behaviour module, with the two ways `Statics` reads one.

    `fields` is the raw declaration. The typed attributes beside it are what the real
    `sage_ini` model exposes and what `_yes` reads, and the distinction is load-bearing here:
    `ThisFormationIsTheMainFormation = No` is a `Bool` on the real module, so a stub that
    offered only the string would make `bool("No")` true and hide the direction check this file
    exists to test.
    """

    def __init__(self, fields: dict[str, str]) -> None:
        self.fields = fields
        self._fields = fields
        self.name = ""
        for key, value in fields.items():
            setattr(self, key, {"yes": True, "no": False}.get(value.lower(), value))


class FakeObject:
    def __init__(self, fields, parent_name=None, modules=None) -> None:
        self.fields = fields
        self._fields = fields
        self.parent_name = parent_name
        self.parent: FakeObject | None = None
        self.modules = modules or []


class FakeEntry:
    """One `Modifier =` line, as `sage_ini.model.state` reads it."""

    def __init__(self, kind: ModifierType, amount: float, damage_types=()) -> None:
        self.Type = kind
        self.Value = str(amount)
        self.Amount = amount
        self.DamageTypes = list(damage_types)


class FakeModifierList:
    def __init__(self, *entries: FakeEntry) -> None:
        self.Modifier = list(entries)


class FakeGame:
    def __init__(self, objects, **tables) -> None:
        self.tables = {"objects": objects, **tables}
        self.macros: dict[str, str] = {}

    def has_macro(self, name: object) -> bool:
        return False

    def get_macro(self, value: object) -> object:
        return value


BLOCK_MODIFIERS = FakeModifierList(
    FakeEntry(ModifierType.ARMOR, 0.17),
    FakeEntry(ModifierType.SPEED, 0.70),
)
# The knights' wedge: armour, but only against two damage types.
WEDGE_MODIFIERS = FakeModifierList(
    FakeEntry(ModifierType.ARMOR, 0.33, [DamageType.SLASH, DamageType.SPECIALIST]),
    FakeEntry(ModifierType.SPEED, 0.50),
)
# The pikemen's porcupine: strictly worse by every number, and the thing you want against horse.
PORCUPINE_MODIFIERS = FakeModifierList(
    FakeEntry(ModifierType.CRUSHED_DECELERATE, 20.0),
    FakeEntry(ModifierType.VISION, -0.90),
)


def _horde(payload: str, alternate: str, command_set: str, main: bool = True) -> FakeObject:
    return FakeObject(
        {"KindOf": "INFANTRY SELECTABLE HORDE", "CommandSet": command_set},
        modules=[
            FakeModule(
                {
                    "InitialPayload": f"{payload} 15",
                    "AlternateFormation": alternate,
                    "ThisFormationIsTheMainFormation": "Yes" if main else "No",
                }
            )
        ],
    )


def _alternate(payload: str, back: str, command_set: str, modifiers: str) -> FakeObject:
    return FakeObject(
        {"KindOf": "INFANTRY SELECTABLE HORDE", "CommandSet": command_set},
        modules=[
            FakeModule(
                {
                    "InitialPayload": f"{payload} 15",
                    "AlternateFormation": back,
                    "ThisFormationIsTheMainFormation": "No",
                    "AttributeModifiers": modifiers,
                }
            )
        ],
    )


def build() -> Statics:
    return Statics(
        FakeGame(
            {
                "GondorFighterHorde": _horde(
                    "GondorFighter", "GondorFighterHordeBlock", "FighterSet"
                ),
                "GondorFighterHordeBlock": _alternate(
                    "GondorFighter", "GondorFighterHorde", "FighterSet", "GondorFighterBlock"
                ),
                # A child that restates nothing: it must inherit the whole arrangement.
                "GondorFighterHorde_Summoned": FakeObject({}, parent_name="GondorFighterHorde"),
                # Declared alternate, and a command set naming a button nothing declares.
                "GondorKnightsofDolHorde": _horde(
                    "GondorKnightDol", "GondorKnightsofDolHordeWedge", "DolSet"
                ),
                "GondorKnightsofDolHordeWedge": _alternate(
                    "GondorKnightDol", "GondorKnightsofDolHorde", "DolSet", "DolWedge"
                ),
                # Scoped armour.
                "GondorKnightHorde": _horde("GondorCavalry", "GondorKnightWedge", "KnightSet"),
                "GondorKnightWedge": _alternate(
                    "GondorCavalry", "GondorKnightHorde", "KnightSet", "KnightWedge"
                ),
                # A brace with no armour at all.
                "GondorSpearmanHorde": _horde(
                    "GondorPikeman", "GondorSpearmanHordePorcupine", "PikeSet"
                ),
                "GondorSpearmanHordePorcupine": _alternate(
                    "GondorPikeman", "GondorSpearmanHorde", "PikeSet", "Porcupine"
                ),
                # An alternate naming a modifier list the tree does not declare.
                "GondorArcherHorde": _horde("GondorArcher", "GondorArcherAmbush", "ArcherSet"),
                "GondorArcherAmbush": _alternate(
                    "GondorArcher", "GondorArcherHorde", "ArcherSet", "NoSuchList"
                ),
                # A battalion with no alternate formation at all.
                "GondorRangerHorde": FakeObject(
                    {"KindOf": "INFANTRY SELECTABLE HORDE", "CommandSet": "RangerSet"},
                    modules=[FakeModule({"InitialPayload": "GondorRanger 15"})],
                ),
            },
            commandsets={
                "FighterSet": FakeObject({"1": "Command_ToggleStance", "2": "Command_Block"}),
                "KnightSet": FakeObject({"2": "Command_Wedge"}),
                "PikeSet": FakeObject({"2": "Command_Porcupine"}),
                "ArcherSet": FakeObject({"2": "Command_Ambush"}),
                "RangerSet": FakeObject({"1": "Command_ToggleStance"}),
                # Names a button no `commandbuttons` entry declares - the engine draws nothing.
                "DolSet": FakeObject({"2": "Command_ToggleFormationKnightsOfDol"}),
            },
            commandbuttons={
                "Command_ToggleStance": FakeObject({"Command": "TOGGLE_STANCE"}),
                "Command_Block": FakeObject({"Command": "HORDE_TOGGLE_FORMATION"}),
                "Command_Wedge": FakeObject({"Command": "HORDE_TOGGLE_FORMATION"}),
                "Command_Porcupine": FakeObject({"Command": "HORDE_TOGGLE_FORMATION"}),
                "Command_Ambush": FakeObject({"Command": "HORDE_TOGGLE_FORMATION"}),
            },
            modifiers={
                "GondorFighterBlock": BLOCK_MODIFIERS,
                "KnightWedge": WEDGE_MODIFIERS,
                "Porcupine": PORCUPINE_MODIFIERS,
                "DolWedge": BLOCK_MODIFIERS,
            },
        )
    )


@pytest.fixture
def statics() -> Statics:
    return build()


def test_a_battalion_reports_the_formation_it_can_switch_into(statics):
    formation = statics.alternate_formation("GondorFighterHorde")
    assert formation is not None
    assert formation.alternate == "GondorFighterHordeBlock"
    assert formation.button == "Command_Block"


def test_the_alternate_does_not_report_one_back(statics):
    """The pair name each other; only the main-formation flag says which way round they are."""
    assert statics.alternate_formation("GondorFighterHordeBlock") is None


def test_a_child_inherits_the_contain_module_it_does_not_restate(statics):
    formation = statics.alternate_formation("GondorFighterHorde_Summoned")
    assert formation is not None and formation.alternate == "GondorFighterHordeBlock"


def test_a_battalion_with_no_alternate_answers_none(statics):
    assert statics.alternate_formation("GondorRangerHorde") is None


def test_an_unknown_template_answers_none(statics):
    assert statics.alternate_formation("NoSuchHorde") is None


def test_a_formation_whose_button_is_undeclared_is_not_ours_to_use(statics):
    """The command set names it, the tree does not declare it, so no human ever sees it."""
    formation = statics.alternate_formation("GondorKnightsofDolHorde")
    assert formation is not None
    assert formation.button == ""
    assert not formation.worth_taking


def test_speed_and_armour_are_combined_the_two_different_ways(statics):
    """`SPEED 70%` is a multiplier and `ARMOR 17%` a bonus - the tooltip's "+20%, -30%"."""
    formation = statics.alternate_formation("GondorFighterHorde")
    assert formation is not None
    assert formation.speed == pytest.approx(0.70)
    assert formation.armour == pytest.approx(0.17)
    assert formation.damage == pytest.approx(1.0)
    assert formation.tougher and formation.slower and formation.defensive


def test_scoped_armour_is_kept_apart_from_the_kind_that_applies_to_everything(statics):
    formation = statics.alternate_formation("GondorKnightHorde")
    assert formation is not None
    assert formation.armour == pytest.approx(0.0)
    assert formation.armour_scoped == pytest.approx(0.33)
    assert formation.armour_types == ("SLASH", "SPECIALIST")
    assert formation.tougher


def test_a_brace_is_read_from_what_it_does(statics):
    """No armour, worse vision, and the one thing that stops a cavalry charge."""
    formation = statics.alternate_formation("GondorSpearmanHorde")
    assert formation is not None
    assert formation.braces
    assert not formation.tougher
    assert formation.vision == pytest.approx(-0.90)
    assert formation.defensive and formation.worth_taking


def test_a_missing_modifier_list_reads_as_the_neutral_formation_it_is(statics):
    formation = statics.alternate_formation("GondorArcherHorde")
    assert formation is not None
    assert formation.modifiers == "NoSuchList"
    assert formation.speed == 1.0 and formation.armour == 0.0
    assert not formation.worth_taking


def test_formation_button_ignores_buttons_that_are_not_formation_toggles(statics):
    assert statics.formation_button("GondorFighterHorde") == "Command_Block"
    assert statics.formation_button("GondorRangerHorde") == ""
