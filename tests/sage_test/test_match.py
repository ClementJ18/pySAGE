"""Tests for what `Match` adds over the session it wraps: liveness, harassing, toggles, casts.

Data-free: a scripted session stands in for the game. It answers `observe` from a list of
observations and records every order, which is all `Match` touches - the fast-forward needs a
process, so these run with `fast=False`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from sage_live.api.observation import GameObject, Observation
from sage_test import Scenario, Seat, harness
from sage_test.harness import Match, recharged


def _obj(object_id: int, x: float = 0.0, conditions: frozenset[str] = frozenset()) -> GameObject:
    return GameObject(
        object_id=object_id,
        template_name="Thing",
        template_side="Men",
        position=(x, 0.0, 0.0),
        angle=0.0,
        health=1.0,
        max_health=100.0,
        owner_index=3,
        conditions=conditions,
    )


@dataclass
class _Session:
    """Serves `frames` in turn, then keeps serving the last; records what it was told."""

    frames: list[Observation]
    cooldowns: list[dict[str, int]] = field(default_factory=list)
    orders: list[tuple] = field(default_factory=list)
    served: int = 0

    def observe(self) -> Observation:
        frame = self.frames[min(self.served, len(self.frames) - 1)]
        self.served += 1
        return frame

    def select(self, ids) -> None:
        self.orders.append(("select", tuple(ids)))

    def attack(self, target_id: int, position) -> None:
        self.orders.append(("attack", target_id))

    def cast(self, power: str, **kwargs) -> None:
        self.orders.append(("cast", power))

    def power_cooldowns(self, object_id: int) -> dict[str, int]:
        return self.cooldowns.pop(0) if len(self.cooldowns) > 1 else self.cooldowns[0]


def _match(session: _Session) -> Match:
    return Match(Scenario("t", seats=(Seat.human(faction=3),)), session, {})  # type: ignore[arg-type]


def _world(*objects: GameObject, frame: int = 10) -> Observation:
    return Observation(frame=frame, local_player=3, objects=objects)


@pytest.fixture(autouse=True)
def _no_waiting(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(harness.time, "sleep", lambda _seconds: None)


def test_alive_keeps_the_order_given_and_drops_the_dead():
    match = _match(_Session([_world(_obj(1), _obj(3))]))
    assert match.alive([3, 2, 1]) == [3, 1]


class TestHarass:
    def test_it_stops_as_soon_as_the_condition_holds(self):
        calm, struck = _world(_obj(1), _obj(9)), _world(_obj(1), _obj(9), frame=11)
        session = _Session([calm, calm, struck])
        stopped = _match(session).harass([1], 9, lambda o: o.frame == 11, timeout=5, fast=False)
        assert stopped == ""
        assert session.orders[:2] == [("select", (1,)), ("attack", 9)]

    def test_it_says_when_the_attackers_are_gone(self):
        session = _Session([_world(_obj(9))])
        assert _match(session).harass([1], 9, lambda o: False, 5, fast=False) == (
            "the attackers are gone"
        )

    def test_it_says_when_the_target_is_gone(self):
        session = _Session([_world(_obj(1))])
        assert _match(session).harass([1], 9, lambda o: False, 5, fast=False) == (
            "the target is gone"
        )

    def test_the_target_can_be_chosen_as_the_fight_goes(self):
        """Chosen from each observation - how a test goes after whichever hero is weakest."""
        session = _Session([_world(_obj(1), _obj(8, x=500.0), _obj(9, x=50.0))])

        def nearest_enemy(observation: Observation) -> GameObject | None:
            enemies = [o for o in observation.find(near=(0.0, 0.0, 0.0)) if o.object_id != 1]
            return enemies[0] if enemies else None

        _match(session).harass([1], nearest_enemy, lambda o: True, 5, fast=False)
        assert ("attack", 9) in session.orders

    def test_it_gives_up_after_the_timeout(self):
        session = _Session([_world(_obj(1), _obj(9))])
        stopped = _match(session).harass([1], 9, lambda o: False, 0.05, fast=False, slice_s=0.01)
        assert stopped == "nothing within 0s"


def test_toggle_until_casts_until_the_condition_shows():
    on_foot, mounted = _obj(5), _obj(5, conditions=frozenset({"MOUNTED"}))
    session = _Session([_world(on_foot), _world(on_foot), _world(mounted)])
    assert _match(session).toggle_until(5, "SpecialAbilityToggleMounted", "MOUNTED")
    assert [order for order in session.orders if order[0] == "cast"] == [
        ("cast", "SpecialAbilityToggleMounted"),
        ("cast", "SpecialAbilityToggleMounted"),
    ]


def test_cast_and_confirm_reselects_before_each_retry_when_asked():
    session = _Session([_world(_obj(5))], cooldowns=[{}, {}, {}, {}, {"Power": 900}])
    ready = _match(session).cast_and_confirm(
        "Power", 5, form="self", timeout=5, retry_every=0.05, reselect=True
    )
    assert ready == 900
    selects = [order for order in session.orders if order[0] == "select"]
    casts = [order for order in session.orders if order[0] == "cast"]
    assert len(selects) == len(casts), "one selection per attempt"


@pytest.mark.parametrize(
    "before,now,frame,cast",
    [
        (100, 600, 200, True),
        (None, 600, 200, True),
        (600, 600, 200, False),
        (600, 150, 200, False),
        (600, None, 200, False),
    ],
    ids=["moved-ahead", "first-seen-ahead", "unchanged", "cleared", "unreadable"],
)
def test_recharged_is_a_ready_frame_moved_into_the_future(before, now, frame, cast):
    assert recharged(before, now, frame) is cast
