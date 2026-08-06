"""When a defence group is released, and when it holds on.

The rule these replace cancelled itself. A group was deleted as soon as its holding stopped
counting as threatened - but a holding is threatened only while enemies stand near the *building*,
and the group's job is to walk out and meet them, so succeeding at the job ended the job.

Measured live across cycles 122-125 of one run: two battalions were drawn out of two separate
parties, held for two cycles, then snapped straight back to their previous march order while the
raider they were sent at was still alive. Four seconds, two turns, nothing killed.
"""

from __future__ import annotations

import time
from types import SimpleNamespace

from sage_mods.edain.bot.ledger import Ledger
from sage_mods.edain.bot.tuning import DEFEND_COMMITMENT, DEFEND_CONTACT
from sage_mods.edain.bot.warfare import Warfare

HOME = (0.0, 0.0, 0.0)


def _at(x: float, ident: int = 1) -> SimpleNamespace:
    """A stand-in object on the x axis, with the only two members these paths touch."""
    position = (x, 0.0, 0.0)
    return SimpleNamespace(
        object_id=ident,
        position=position,
        distance_to=lambda other, here=position: abs(here[0] - other[0]),
    )


class Defence:
    """`settle_groups` and `in_contact` over stub state.

    A real `Warfare` needs a session, an ini tree and a match; these two need the group table, the
    army, and whatever is standing near it.
    """

    settle_groups = Warfare.settle_groups
    release_group = Warfare.release_group
    in_contact = Warfare.in_contact

    def __init__(self, members: list[SimpleNamespace], enemies: list[SimpleNamespace]) -> None:
        self._army = members
        self._groups = {7: tuple(m.object_id for m in members)}
        self._group_aim: dict[int, tuple[float, float, float]] = {}
        self._group_ordered: dict[int, float] = {}
        self._group_target: dict[int, int] = {}
        self._group_home = {7: HOME}
        self._group_quiet: dict[int, float] = {}
        self.observation = SimpleNamespace(objects=enemies)
        self.ordered: list[tuple[float, float, float]] = []
        self.session = SimpleNamespace(attack_move=self._attack_move)

    def army(self) -> list[SimpleNamespace]:
        return self._army

    def hostile(self, obj: SimpleNamespace) -> bool:
        return True  # the stub's object list holds only enemies

    def select(self, units: list[SimpleNamespace]) -> bool:
        return True

    def manoeuvre(self, label: str, act, units: list[SimpleNamespace]) -> bool:
        act()
        return True

    def _attack_move(self, where: tuple[float, float, float]) -> bool:
        self.ordered.append(where)
        return True


def test_a_group_that_got_its_order_is_left_alone() -> None:
    defence = Defence([_at(100.0)], [])
    assert defence.settle_groups({7}) == []
    assert 7 in defence._groups
    assert defence.ordered == []


def test_a_group_in_contact_is_never_released_or_re_aimed() -> None:
    """The case the old rule got wrong every time: the fight moved off the holding, so the
    holding read as clear while the battalions were still swinging."""
    defence = Defence([_at(900.0)], [_at(900.0 + DEFEND_CONTACT / 2, ident=99)])
    assert defence.settle_groups(set()) == []
    assert 7 in defence._groups
    assert defence.ordered == []  # not sent home - it is busy
    assert 7 not in defence._group_quiet


def test_a_raider_that_breaks_off_sends_the_group_home_rather_than_chasing() -> None:
    defence = Defence([_at(900.0)], [_at(900.0 + DEFEND_CONTACT * 2, ident=99)])
    said = defence.settle_groups(set())
    assert 7 in defence._groups  # still committed
    assert defence.ordered == [HOME]  # back to the holding, not after the raider
    assert said and "back to the holding" in said[0]


def test_the_group_is_not_re_ordered_home_every_cycle() -> None:
    """A group already walking back has the aim it would be given, so nothing is re-sent."""
    defence = Defence([_at(900.0)], [])
    defence.settle_groups(set())
    defence.settle_groups(set())
    defence.settle_groups(set())
    assert defence.ordered == [HOME]


def test_a_group_quiet_past_the_commitment_is_released() -> None:
    defence = Defence([_at(900.0)], [])
    defence.settle_groups(set())
    assert 7 in defence._groups
    defence._group_quiet[7] = time.monotonic() - DEFEND_COMMITMENT - 1.0
    defence.settle_groups(set())
    assert 7 not in defence._groups
    assert 7 not in defence._group_home


def test_contact_resets_the_commitment_clock() -> None:
    """A raider that steps out and back does not get a free order-cancel by waiting us out."""
    defence = Defence([_at(900.0)], [])
    defence.settle_groups(set())
    assert 7 in defence._group_quiet
    defence.observation = SimpleNamespace(objects=[_at(900.0, ident=99)])
    defence.settle_groups(set())
    assert 7 not in defence._group_quiet


def test_a_group_whose_battalions_all_died_is_released_at_once() -> None:
    """No commitment is owed to nobody, and holding the key would leak it for the match."""
    defence = Defence([], [])
    assert defence.settle_groups(set()) == []
    assert 7 not in defence._groups


class Holding:
    """`hold` over stub state, recording every order it actually tries to send.

    Narrower than `Defence` on purpose: the question here is only what a *discarded* order does
    to the group's memory, so everything either side of the send is stubbed to a constant.
    """

    hold = Warfare.hold

    def __init__(self, sends: bool) -> None:
        self._sends = sends
        self._group_aim: dict[int, tuple[float, float, float]] = {}
        self._group_ordered: dict[int, float] = {}
        self._group_target: dict[int, int] = {}
        self._groups: dict[int, tuple[int, ...]] = {}
        self.ledger = Ledger()
        self.attempts = 0

    def group_for(self, key, where, threat, taken):
        return [_at(50.0, 11), _at(60.0, 12)]

    def select(self, units) -> bool:
        return True

    def confirm_engaged(self, target, group, act) -> bool:
        act()
        return self._sends

    def _issue(self, label: str, act) -> bool:
        self.attempts += 1
        return self._sends

    def _report(self, label: str, ok: bool, good: str, bad: str) -> bool:
        self.ledger.record(label, ok)
        return ok

    session = SimpleNamespace(attack=lambda *a, **k: True)


def test_a_discarded_defend_order_does_not_buy_the_keepalive_silence() -> None:
    """The bug that parked a third of the army in a field.

    Game logic discards a defend order after the stream has taken it. Recording the target and
    the clock anyway told the next cycle the group was already engaged with this raider and had
    just been ordered, so it returned "met by" and sent nothing for a full `DEFEND_KEEPALIVE`.
    """
    holding = Holding(sends=False)
    raider = _at(300.0, 99)
    raider.template_name = "IsengardRamCrew"

    said = holding.hold(7, HOME, [raider], set())
    assert said is not None and "retrying" in said
    assert holding.attempts == 1
    # Neither mark may be left behind: either one alone is enough to silence the next cycle.
    assert holding._group_target == {}
    assert holding._group_ordered == {}

    # The next cycle must therefore try again rather than report "met by".
    said = holding.hold(7, HOME, [raider], set())
    assert holding.attempts == 2
    assert said is not None and "met by" not in said


def test_an_order_that_was_sent_still_holds_its_group_quiet() -> None:
    """The behaviour the keep-alive exists for, which the fix must not cost.

    A raider that has not moved and has not been replaced is not a new decision, and re-ordering
    it every cycle was six orders and six booked failures across one approach.
    """
    holding = Holding(sends=True)
    raider = _at(300.0, 99)
    raider.template_name = "IsengardRamCrew"

    said = holding.hold(7, HOME, [raider], set())
    assert said is not None and "sent at" in said
    assert holding._group_target == {7: 99}
    assert holding._group_ordered

    assert holding.hold(7, HOME, [raider], set()) == "1 met by 2"
    assert holding.attempts == 1  # nothing re-sent
