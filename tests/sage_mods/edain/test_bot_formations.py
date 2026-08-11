"""Formations: the bonus a battalion gets for standing still, and when standing still is free.

Two halves, and they fail in different ways. Reading the tree wrong finds formations that are not
there - the pair of objects name each other, so a naive read answers for both directions and puts
a braced battalion back into the wall it is already in. Reading the *match* wrong is worse: the
trade is armour for speed, so a rule that fires while the army is marching slows the whole force
down for protection it is not being shot at with.

The stage's own oracle is covered too. A formation toggle is a well-formed order the engine may
consume and discard, exactly as `test_bot_signal_fire` covers for a cast, and the only thing that
tells the difference is the engine's `ALTERNATE_FORMATION` flag on the battalion's members.
"""

from __future__ import annotations

from types import SimpleNamespace

from sage_live.utils.statics import Formation
from sage_mods.edain.bot.ledger import Ledger
from sage_mods.edain.bot.mechanics.formations import (
    ALTERNATE,
    Formations,
    Posture,
    blinding_brace,
)
from sage_mods.edain.bot.tuning import (
    DEFEND_CONTACT,
    FORMATION_HOLD,
    FORMATION_PATIENCE,
    FORMATION_STILL,
)

# `GondorFighterHordeBlock` as the tree declares it: +17% armour for 70% of the speed, which the
# control bar states as "+20% Armor, -30% Speed".
BLOCK = Formation(
    template="GondorFighterHorde",
    alternate="GondorFighterHordeBlock",
    button="Command_ToggleFormationGondorFighter",
    modifiers="GondorFighterBlock_Edain",
    armour=0.17,
    speed=0.70,
)
# The pikemen's porcupine: no armour at all, 90% of their vision gone, and a cavalry charge that
# hits it stops dead. Worth taking, and nothing but `braces` says so.
PORCUPINE = Formation(
    template="GondorSpearmanHorde",
    alternate="GondorSpearmanHordePorcupine",
    button="Command_TowerGuardPorcupineFormation",
    modifiers="GondorSpearmanHordePorcupine",
    vision=-0.90,
    braces=True,
)
# The Morthond ambush in this build: 80% speed and no bonus at all. Declared, reachable, and not
# worth an order.
EMPTY = Formation(
    template="MorthondBowmenHorde",
    alternate="MorthondBowmenHordeAmbushFormation",
    button="Command_ToggleFormationMorthondBowmen",
    modifiers="MorthondArcherAmbushFormation",
    speed=0.80,
)
# Dol Amroth's wedge: a real formation whose toggle button no command set offers.
UNREACHABLE = Formation(
    template="GondorKnightsofDolHorde",
    alternate="GondorKnightsofDolHordeWedgeFormation",
    button="",
    modifiers="GondorKnightWedge",
    armour=-0.25,
    damage=1.25,
)


def _horde(object_id: int, template: str = "GondorFighterHorde", x: float = 0.0):
    return SimpleNamespace(
        object_id=object_id,
        template_name=template,
        position=(x, 0.0, 0.0),
        distance_to=lambda other, _x=x: abs(other[0] - _x),
    )


def _member(parent: int, alternate: bool):
    return SimpleNamespace(
        parent_id=parent,
        is_in=lambda name, _a=alternate: _a and name == ALTERNATE,
    )


class _Observation:
    def __init__(self, army, enemies, alternate: set[int]) -> None:
        self.objects = list(army) + list(enemies)
        self._members = [_member(h.object_id, h.object_id in alternate) for h in army]
        self.me = SimpleNamespace(upgrades=frozenset())

    def members(self, object_id: int):
        return tuple(m for m in self._members if m.parent_id == object_id)


class _Session:
    """Takes toggles and reports whether the engine acted, which is the whole question."""

    def __init__(self, obeys: bool) -> None:
        self.obeys = obeys
        self.toggled: list[int] = []

    def toggle_formation(self, horde_id: int) -> int:
        self.toggled.append(horde_id)
        return 1

    def confirm(self, predicate, timeout: float = 0.0) -> bool:
        return self.obeys


class Formed(Formations):
    """`stage_formation` over stub battalions, with the tree read replaced by a table."""

    def __init__(
        self,
        army,
        enemies=(),
        formations=None,
        alternate=(),
        obeys: bool = True,
        seen=None,
    ) -> None:
        self._army = list(army)
        self.observation = _Observation(self._army, enemies, set(alternate))
        self._formations = dict(formations or {"gondorfighterhorde": BLOCK})
        # `seen={}` is a real case - a battalion this bot has never sampled - so `or` would be
        # wrong here.
        if seen is None:
            seen = {h.object_id: h.position for h in self._army}
        self._formation_seen = dict(seen)
        self._formation_since: dict[int, int] = {}
        self._formation_at: dict[int, float] = {}
        self.session = _Session(obeys)
        self.ledger = Ledger()
        self.dry_run = False
        self.said: list[str] = []

    def army(self):
        return list(self._army)

    def hostile(self, obj) -> bool:
        return getattr(obj, "enemy", False)

    def select(self, objects) -> bool:
        return True

    def _issue(self, label, act) -> int:
        return act()

    def _report(self, label, ok, good, bad) -> bool:
        self.ledger.record(label, ok)
        self.said.append(f"{label} {good if ok else bad}")
        return ok


def _enemy(x: float):
    return SimpleNamespace(
        object_id=900,
        template_name="IsengardUrukHorde",
        position=(x, 0.0, 0.0),
        enemy=True,
        distance_to=lambda other, _x=x: abs(other[0] - _x),
    )


def _settle(bot: Formed, cycles: int = FORMATION_PATIENCE) -> str | None:
    """Run the stage until its patience is satisfied, answering the last thing it said."""
    said = None
    for _ in range(cycles):
        said = bot.stage_formation()
    return said


# --- reading the tree -------------------------------------------------------------------


def test_worth_taking_needs_a_button_and_a_bonus():
    assert BLOCK.worth_taking
    assert PORCUPINE.worth_taking
    # 80% speed and nothing else is a legitimate switch that buys nothing.
    assert not EMPTY.worth_taking
    # A full formation the control bar never offers is not ours to use.
    assert not UNREACHABLE.worth_taking


def test_defensive_reads_the_trade_and_not_the_name():
    assert BLOCK.defensive and BLOCK.tougher and BLOCK.slower
    # No armour, no damage, worse vision - and defensive, because it stops a charge.
    assert PORCUPINE.defensive and not PORCUPINE.tougher
    # Armour bought with damage is not a defensive formation.
    assert not UNREACHABLE.defensive


def test_a_brace_bought_with_sight_is_refused():
    """The porcupine is reachable and does something real, and is still not worth the blindness.

    `worth_taking` says yes on `braces` alone, so the refusal has to be its own test - and it has
    to read the trade rather than the template name, because six templates in the Men pool take
    an identical porcupine.
    """
    assert PORCUPINE.worth_taking
    assert blinding_brace(PORCUPINE)


def test_a_brace_that_costs_no_sight_is_kept():
    """Pelargir's wall braces too, and is separated by what it buys rather than by its name."""
    wall = Formation(
        template="PelegirSpearmenHorde",
        alternate="PelegirSpearmenHordeShieldWall",
        button="Command_ToggleFormationPelegirSpearmen",
        armour_scoped=0.50,
        armour_types=("WATER",),
        damage=0.75,
        braces=True,
    )
    assert not blinding_brace(wall)
    # And nothing that fails to brace is caught by it either.
    assert not blinding_brace(BLOCK)


def test_spearmen_are_left_in_line_even_in_a_settled_fight():
    """The stage-level consequence: a braced-worthy battalion that never gets the order."""
    bot = Formed(
        [_horde(1, "GondorSpearmanHorde")],
        enemies=[_enemy(DEFEND_CONTACT / 2)],
        formations={"gondorspearmanhorde": PORCUPINE},
    )
    assert _settle(bot, cycles=5) is None
    assert bot.session.toggled == []


def test_scoped_armour_still_counts_as_tougher():
    """The knights' wedge is `ARMOR 33% SLASH SPECIALIST` - narrower, not absent."""
    wedge = Formation(
        template="GondorKnightHorde",
        alternate="GondorKnightHordeWedgeFormation",
        button="Command_ToggleFormationKnight",
        armour_scoped=0.33,
        armour_types=("SLASH", "SPECIALIST"),
        speed=0.50,
    )
    assert wedge.tougher and wedge.defensive and wedge.worth_taking


# --- reading the match ------------------------------------------------------------------


def test_a_battalion_that_moved_is_not_fighting():
    """The whole trade is armour for speed, so a marching battalion must stay in line."""
    horde = _horde(1, x=FORMATION_STILL * 3)
    bot = Formed([horde], enemies=[_enemy(FORMATION_STILL * 3)], seen={1: (0.0, 0.0, 0.0)})
    assert not bot.standing(horde)
    assert not bot.fighting(horde)


def test_standing_alone_is_not_fighting():
    horde = _horde(1)
    bot = Formed([horde], enemies=[_enemy(DEFEND_CONTACT * 2)])
    assert bot.standing(horde)
    assert not bot.fighting(horde)


def test_standing_in_contact_is_fighting():
    horde = _horde(1)
    bot = Formed([horde], enemies=[_enemy(DEFEND_CONTACT / 2)])
    assert bot.fighting(horde)


def test_a_battalion_never_seen_before_counts_as_moving():
    """One cycle's delay rather than calling every fresh recruit stationary."""
    horde = _horde(1)
    bot = Formed([horde], enemies=[_enemy(0.0)], seen={})
    assert not bot.standing(horde)


def test_alternate_is_read_off_the_members_not_the_container():
    horde = _horde(1)
    assert not Formed([horde]).in_alternate(horde)
    assert Formed([horde], alternate=[1]).in_alternate(horde)


# --- switching --------------------------------------------------------------------------


def test_a_fighting_battalion_is_braced():
    bot = Formed([_horde(1)], enemies=[_enemy(DEFEND_CONTACT / 2)])
    said = _settle(bot)
    assert bot.session.toggled == [1]
    assert said is not None and "braced" in said
    assert bot.ledger.sent["formation GondorFigh"] == 1
    assert bot.ledger.worked["formation GondorFigh"] == 1


def test_patience_holds_the_switch_for_a_skirmish_that_ends():
    """One cycle of contact must not pay for a formation change."""
    bot = Formed([_horde(1)], enemies=[_enemy(DEFEND_CONTACT / 2)])
    bot.stage_formation()
    assert bot.session.toggled == []


def test_a_braced_battalion_left_alone_while_the_fight_lasts():
    bot = Formed([_horde(1)], enemies=[_enemy(DEFEND_CONTACT / 2)], alternate=[1])
    said = _settle(bot, cycles=4)
    assert bot.session.toggled == []
    assert said is not None and "1/1 braced" in said


def test_a_braced_battalion_that_marched_goes_back_into_line():
    horde = _horde(1, x=FORMATION_STILL * 4)
    bot = Formed([horde], alternate=[1], seen={1: (0.0, 0.0, 0.0)})
    said = _settle(bot)
    assert bot.session.toggled == [1]
    assert said is not None and "back in line" in said


def test_an_order_the_engine_drops_is_reported_as_a_failure():
    """The flag on the members is the oracle; a send that changed nothing is not a success."""
    bot = Formed([_horde(1)], enemies=[_enemy(DEFEND_CONTACT / 2)], obeys=False)
    _settle(bot)
    assert bot.session.toggled == [1]
    assert bot.ledger.sent["formation GondorFigh"] == 1
    assert "formation GondorFigh" not in bot.ledger.worked
    assert any("DID NOT CHANGE" in s for s in bot.said)


def test_a_switch_is_not_repeated_inside_its_hold():
    bot = Formed([_horde(1)], enemies=[_enemy(DEFEND_CONTACT / 2)])
    _settle(bot)
    assert bot.session.toggled == [1]
    # The engine confirmed the switch, so the stub's `alternate` set is now stale - force the
    # disagreement back on and check the hold, not the state, is what refuses.
    bot.observation = _Observation(bot.army(), [], set())
    for _ in range(5):
        bot.stage_formation()
    assert bot.session.toggled == [1]
    assert FORMATION_HOLD > 0


def test_a_formation_with_no_bonus_is_never_switched():
    bot = Formed(
        [_horde(1, "MorthondBowmenHorde")],
        enemies=[_enemy(DEFEND_CONTACT / 2)],
        formations={"morthondbowmenhorde": EMPTY},
    )
    assert _settle(bot, cycles=5) is None
    assert bot.session.toggled == []


def test_a_battalion_with_no_formation_costs_nothing():
    bot = Formed([_horde(1, "GondorRangerHorde")], formations={"gondorrangerhorde": None})
    assert bot.stage_formation() is None
    assert bot.session.toggled == []


def test_one_order_a_cycle_and_the_needy_go_first():
    """Two battalions want opposite things; the one about to be hit is answered first."""
    marching = _horde(1, x=FORMATION_STILL * 4)
    fighting = _horde(2, x=1000.0)
    bot = Formed(
        [marching, fighting],
        enemies=[_enemy(1000.0)],
        alternate=[1],
        seen={1: (0.0, 0.0, 0.0), 2: (1000.0, 0.0, 0.0)},
    )
    _settle(bot)
    assert bot.session.toggled == [2]


def test_positions_are_recorded_for_every_battalion_not_just_the_one_acted_on():
    """`standing` compares against last cycle, so a battalion never sampled is never readable."""
    bot = Formed(
        [_horde(1), _horde(2, x=500.0)],
        enemies=[_enemy(DEFEND_CONTACT / 2)],
        seen={},
    )
    bot.stage_formation()
    assert set(bot._formation_seen) == {1, 2}


def test_posture_wrong_is_the_disagreement():
    braced = Posture(horde=_horde(1), formation=BLOCK, alternate=True, fighting=True)
    assert braced.wants and not braced.wrong
    marching = Posture(horde=_horde(1), formation=BLOCK, alternate=True, fighting=False)
    assert not marching.wants and marching.wrong
