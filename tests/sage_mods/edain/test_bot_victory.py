"""Deciding the map is finished, which is what lets a run actually end.

`raid_target`'s last resort is the opponent's victory-counting buildings, and it is gated on
there being no map left worth taking. The first version of that gate asked for zero free flags and
never opened once: two measured runs reached 94% and 88% map control, with armies of 19 and 24
standing spare, and spent their whole endgame walking at one or two settlements they had already
failed to take. Plot 202 was abandoned four times in one run and was still counted as unfinished
business at cycle 400.

`winnable_flags` is the correction. The subtlety is that it must count failures rather than read
the cooldown: `FLAG_COOLDOWN` expires, so a gate on "blocked right now" would open the branch
during the cooldown and close it the moment the flag became a candidate again - turning the whole
army round every two minutes.
"""

from __future__ import annotations

import time
from types import SimpleNamespace

from sage_mods.edain.bot.tuning import FLAG_COOLDOWN, FLAG_GIVE_UP
from sage_mods.edain.bot.warfare import Warfare


class Mapping:
    """`winnable_flags` and `drop_flag`'s bookkeeping, over a stub map."""

    winnable_flags = Warfare.winnable_flags
    drop_flag = Warfare.drop_flag

    def __init__(
        self,
        flag_ids: list[int],
        army: int = 20,
        defenders: dict[int, int] | None = None,
    ) -> None:
        self._flags = [SimpleNamespace(object_id=i, owner_index=9) for i in flag_ids]
        self._army = army
        self._defenders = defenders or {}
        self.session = SimpleNamespace(player_index=1)
        self._flag_failures: dict[int, int] = {}
        self._blocked_flags: dict[int, float] = {}
        self._closest: dict[int, float] = {}
        self._stalled: dict[int, int] = {}
        self._spent: dict[int, int] = {}
        self._party_flag: dict[int, int] = {}
        self.released: list[str] = []

    def external_plots(self) -> list[SimpleNamespace]:
        return self._flags

    def army(self) -> list[object]:
        return [object()] * self._army

    def defenders(self, flag: SimpleNamespace) -> list[object]:
        return [object()] * self._defenders.get(flag.object_id, 0)

    def release(self, purpose: str) -> None:
        self.released.append(purpose)


def test_an_untouched_map_is_all_winnable() -> None:
    world = Mapping([201, 202, 203])
    assert len(world.winnable_flags()) == 3


def test_one_abandonment_does_not_write_a_flag_off() -> None:
    """Ordinary: a lair repopulated, a party arrived under-strength, a raid interrupted the walk.

    Treating that as permanent would write off half a map on the first bad approach.
    """
    world = Mapping([201, 202])
    world.drop_flag(world._flags[0], "a lair repopulated")
    assert len(world.winnable_flags()) == 2


def test_a_flag_abandoned_enough_times_stops_counting() -> None:
    world = Mapping([201, 202])
    for _ in range(FLAG_GIVE_UP):
        world.drop_flag(world._flags[0], "not getting there")
    remaining = world.winnable_flags()
    assert [f.object_id for f in remaining] == [202]


def test_the_measured_endgame_now_opens_the_gate() -> None:
    """94% of the map held, two flags left, both repeatedly failed - the run that could not end."""
    world = Mapping([202, 212])
    for _ in range(FLAG_GIVE_UP):
        world.drop_flag(world._flags[0], "not getting there")
        world.drop_flag(world._flags[1], "not getting there")
    assert world.winnable_flags() == []


def test_the_count_survives_the_cooldown_expiring() -> None:
    """The whole reason this counts instead of reading `_blocked_flags`.

    A cooldown answers "may I try again yet"; expiring it must not re-open a gate that says the
    map is finished, or the army turns round every two minutes.
    """
    world = Mapping([202])
    for _ in range(FLAG_GIVE_UP):
        world.drop_flag(world._flags[0], "not getting there")
    assert world.winnable_flags() == []
    # Expire every cooldown - the flag is a live candidate for `worth_taking` again.
    world._blocked_flags = {k: time.monotonic() - 1.0 for k in world._blocked_flags}
    assert world._blocked_flags[202] < time.monotonic()
    assert world.winnable_flags() == []  # still finished, because the failures still happened


def test_dropping_a_flag_still_does_its_original_bookkeeping() -> None:
    """The tally is added to `drop_flag`, and must not have displaced what it already did."""
    world = Mapping([202])
    world._closest[202] = 50.0
    world._stalled[202] = 3
    world._spent[202] = 9
    world._party_flag[1] = 202
    world.drop_flag(world._flags[0], "not getting there", party=1)
    assert 202 not in world._closest
    assert 202 not in world._stalled
    assert 202 not in world._spent
    assert 1 not in world._party_flag
    assert world._blocked_flags[202] > time.monotonic() + FLAG_COOLDOWN - 5.0
    assert world.released == ["capture"]


def test_a_flag_nobody_will_attempt_does_not_count_as_map_left() -> None:
    """The case counting abandonment alone missed entirely: a flag that never fails.

    `worth_taking` declines a flag whose defenders outnumber the party that would go, so a heavily
    garrisoned settlement is never chosen, never abandoned, and keeps a failure count of zero.
    Measured at cycle 301 of a run: 94% map control, eighteen battalions across five parties, every
    lair razed, and the decision line was `recruit` and nothing else - because one flag no party
    would accept still counted as map left to take.
    """
    world = Mapping([202], army=18, defenders={202: 200})
    assert world._flag_failures == {}  # never attempted, so never failed
    assert world.winnable_flags() == []


def test_the_odds_are_asked_against_the_whole_army_not_a_party() -> None:
    """A party has to decline what it alone cannot beat; this question is what *could* be taken."""
    lightly_held = {202: 6}
    assert Mapping([202], army=20, defenders=lightly_held).winnable_flags() != []
    assert Mapping([202], army=2, defenders=lightly_held).winnable_flags() == []


def test_a_flag_already_ours_is_always_winnable() -> None:
    """Nothing has to be beaten to build on it - an unpack left undone is map still to finish."""
    world = Mapping([202], army=1, defenders={202: 500})
    world._flags[0].owner_index = world.session.player_index
    assert len(world.winnable_flags()) == 1
