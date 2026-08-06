"""Where a lone tower goes: covering an outlying holding, on the side the attack comes from.

The placement this replaces aimed at the base centre, which is both the best-defended ground on
the map and the worst place to fit a building - `open_ground` exists because that aim was refused
three times running, and the live ledger read `cast build 6/15`.

A settlement or outpost is what a tower is actually for: no wall, no spread, and the first thing
a raid reaches. The tests here pin the two halves of that - which holding is chosen, and which
side of it the tower lands on - plus the "one per" bookkeeping.
"""

from __future__ import annotations

from types import SimpleNamespace

from sage_mods.edain.bot.powers import Powers
from sage_mods.edain.bot.tuning import BASE_RADIUS, TOWER_STANDOFF

HOME = (0.0, 0.0, 0.0)


def _holding(object_id: int, x: float, y: float = 0.0) -> SimpleNamespace:
    return SimpleNamespace(object_id=object_id, position=(x, y, 0.0), template_name="GondorFarm")


class Placing:
    """`tower_spot` over a fixed set of holdings, with `open_ground` returning what it was given."""

    tower_spot = Powers.tower_spot
    # Borrowed as statics, or Python binds `self` into their first argument and they get three.
    _away_from = staticmethod(Powers._away_from)
    _toward_point = staticmethod(Powers._toward_point)

    def __init__(self, holdings: list, enemy_at: tuple | None) -> None:
        self._holdings = holdings
        self._enemy_at = enemy_at
        self._towered: set[int] = set()
        self.asked: list[tuple] = []

    def base_centre(self):
        return HOME

    def structures(self):
        return self._holdings

    def enemy(self):
        return None if self._enemy_at is None else (2, self._enemy_at)

    def open_ground(self, centre):
        self.asked.append(centre)
        return centre


def test_no_outlying_holding_means_no_tower() -> None:
    """A building inside the base is not what this is for, and the charge is worth keeping."""
    inside = _holding(1, BASE_RADIUS - 100.0)
    assert Placing([inside], enemy_at=None).tower_spot() is None


def test_the_tower_goes_between_the_holding_and_the_enemy() -> None:
    """The whole placement rule: in the way, not behind the thing it covers."""
    farm = _holding(1, 1000.0)
    placing = Placing([farm], enemy_at=(3000.0, 0.0, 0.0))

    result = placing.tower_spot()
    assert result is not None
    (x, y, _), where = result

    # Enemy is further along +x, so the tower sits TOWER_STANDOFF beyond the farm toward them.
    assert x == 1000.0 + TOWER_STANDOFF
    assert y == 0.0
    assert "enemy" in where


def test_with_no_scouted_enemy_the_tower_goes_on_the_far_side_from_home() -> None:
    """Under fog the enemy is often unknown; away-from-home is the side an attack arrives on."""
    farm = _holding(1, 1000.0)
    placing = Placing([farm], enemy_at=None)

    result = placing.tower_spot()
    assert result is not None
    (x, _, _), where = result

    assert x == 1000.0 + TOWER_STANDOFF  # beyond the farm, not back toward the base
    assert "front" in where


def test_one_tower_per_holding() -> None:
    """ "Start with one per": a holding already covered is not offered again."""
    near, far = _holding(1, 1000.0), _holding(2, 2000.0)
    placing = Placing([near, far], enemy_at=(5000.0, 0.0, 0.0))

    first = placing.tower_spot()
    second = placing.tower_spot()
    assert first is not None and second is not None
    assert placing._towered == {1, 2}

    # Both are spoken for, so a third cast has nowhere to go and keeps its charge.
    assert placing.tower_spot() is None


def test_the_holding_nearest_the_enemy_is_covered_first() -> None:
    """The one most likely to be hit next, where there is a scouted enemy to measure from."""
    near, far = _holding(1, 1000.0), _holding(2, 2000.0)
    placing = Placing([near, far], enemy_at=(5000.0, 0.0, 0.0))

    placing.tower_spot()
    assert placing._towered == {2}  # the far one, which is nearest the enemy


def test_ground_that_cannot_take_a_building_leaves_the_holding_uncovered() -> None:
    """`open_ground` answering None must not consume the holding's one tower."""
    placing = Placing([_holding(1, 1000.0)], enemy_at=None)
    placing.open_ground = lambda centre: None

    assert placing.tower_spot() is None
    assert placing._towered == set()  # still owed a tower, so a later cast can try again


def _signal_fire(object_id: int, x: float, y: float = 0.0) -> SimpleNamespace:
    return SimpleNamespace(
        object_id=object_id, position=(x, y, 0.0), template_name="GondorLeuchtfeuer"
    )


def test_the_signal_fire_takes_the_first_tower() -> None:
    """It is bought once, never rebuilt, and worth nothing until its rider has spent ten minutes
    accruing - and unlike a farm it has no garrison of its own. So it outranks the ordering that
    would otherwise send this tower to whatever sits nearest the enemy."""
    exposed = _holding(1, BASE_RADIUS + 2000.0)
    fire = _signal_fire(2, BASE_RADIUS + 100.0)
    placing = Placing([exposed, fire], enemy_at=(BASE_RADIUS + 4000.0, 0.0, 0.0))
    spot = placing.tower_spot()
    assert spot is not None
    assert "GondorLeuchtfeuer" in spot[1]


def test_the_tower_after_the_signal_fires_goes_back_to_the_ordinary_rule() -> None:
    """One preference, not a permanent override - the fire is towered and the next charge is
    spent on the holding the enemy is nearest to, exactly as before."""
    exposed = _holding(1, BASE_RADIUS + 2000.0)
    fire = _signal_fire(2, BASE_RADIUS + 100.0)
    placing = Placing([exposed, fire], enemy_at=(BASE_RADIUS + 4000.0, 0.0, 0.0))
    placing.tower_spot()
    second = placing.tower_spot()
    assert second is not None
    assert "GondorFarm" in second[1]


def test_a_seat_with_no_signal_fire_is_unaffected() -> None:
    """Every other faction, and every Men run that never built one."""
    exposed = _holding(1, BASE_RADIUS + 2000.0)
    near = _holding(2, BASE_RADIUS + 100.0)
    placing = Placing([exposed, near], enemy_at=(BASE_RADIUS + 4000.0, 0.0, 0.0))
    spot = placing.tower_spot()
    assert spot is not None and "GondorFarm" in spot[1]
