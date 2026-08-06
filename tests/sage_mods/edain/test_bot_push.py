"""The endgame: when the bot stops taking ground and goes to end the match.

**Two pushes were built and removed before this one**, and the module docstring records why: the
gate was wrong both times. A battalion count asked "am I strong enough", which cannot be answered
from inside a match; a stalemate timer turned a 600-cycle undefeated run into a 394-cycle defeat,
because committing "did not create an army that could win, it only stopped the expansion that was
paying for one". Both fired while there was still map to take.

So the tests that matter here are mostly about *not* firing, and about surviving the firing once
it has. The measurements they are written against come from run 4 (1400 cycles, gap of rohan):
map control crossed 85% at cycle 619 and finished at 94%; command-point fill sat at 96-99% for
the last four hundred cycles; the run ended undecided with 105,012 gold banked and army 18.
"""

from __future__ import annotations

from types import SimpleNamespace

from sage_mods.edain.bot.tuning import (
    PUSH_ARMY,
    PUSH_ARRIVED,
    PUSH_CONTROL,
    PUSH_SPENT,
)
from sage_mods.edain.bot.warfare import Warfare
from sage_mods.edain.bot.world import World


class Endgame:
    """`pushing` and the memory it leans on, over supplied readings."""

    pushing = Warfare.pushing
    remember_keeps = Warfare.remember_keeps
    push_aim = Warfare.push_aim
    push_target = Warfare.push_target

    def __init__(self, control: float, fill: float) -> None:
        self._control = control
        self._fill = fill
        self._pushing = False
        self._push_since = 0.0
        self._seen_keeps: dict[int, tuple[float, float, float]] = {}
        self._parties: dict[int, tuple[int, ...]] = {}
        self._party_flag: dict[int, int] = {}
        self._forming: tuple[int, ...] = ()
        self._cav: tuple[int, ...] = ()
        self._army: list[SimpleNamespace] = []
        self._visible: list[SimpleNamespace] = []

    def map_control(self) -> float:
        return self._control

    def command_fill(self) -> float:
        return self._fill

    def army(self) -> list[SimpleNamespace]:
        return self._army

    def victory_targets(self) -> list[SimpleNamespace]:
        return self._visible


def _at(x: float, y: float = 0.0, object_id: int = 1) -> SimpleNamespace:
    where = (x, y, 0.0)
    return SimpleNamespace(
        object_id=object_id,
        position=where,
        template_name="GondorCastleKeep",
        distance_to=lambda other, here=where: (
            ((here[0] - other[0]) ** 2 + (here[1] - other[1]) ** 2) ** 0.5
        ),
    )


def test_a_bot_still_taking_the_map_does_not_push() -> None:
    """The failure both earlier versions had. Committing while there is map left is what stops
    the expansion that pays for the army."""
    assert not Endgame(control=PUSH_CONTROL - 0.10, fill=1.0).pushing()


def test_a_bot_holding_the_map_with_no_army_does_not_push() -> None:
    """Map control alone was the second removed gate - it asks about the score, not the army."""
    assert not Endgame(control=1.0, fill=PUSH_ARMY - 0.10).pushing()


def test_both_gates_together_commit() -> None:
    """Run 4 satisfied both from cycle 619 of 1400 and never attacked anything."""
    assert Endgame(control=PUSH_CONTROL, fill=PUSH_ARMY).pushing()


def test_the_run_4_endgame_reading_commits() -> None:
    """The exact numbers the bot sat on for four hundred cycles: 94% of the map, 1440/1500."""
    assert Endgame(control=0.94, fill=1440 / 1500).pushing()


def test_the_commitment_survives_its_own_casualties() -> None:
    """**The whole point of the latch.** A push takes losses at once, so a gate re-read every
    cycle un-commits in front of the keep - which spends the walk and the battalions and buys
    nothing. Turning round is the one thing worse than not going."""
    endgame = Endgame(control=0.94, fill=0.95)
    assert endgame.pushing()

    endgame._fill = PUSH_ARMY - 0.20  # bloodied, and well under the gate that opened it
    assert endgame.pushing()


def test_a_force_ground_down_far_enough_goes_back_to_playing() -> None:
    """**And the whole point of the release.** A latch with no way out is the 394-cycle defeat
    again: an army below two fifths of its ceiling finishes nothing, and standing in their base
    being killed is the same failure with extra steps."""
    endgame = Endgame(control=0.94, fill=0.95)
    assert endgame.pushing()

    endgame._fill = PUSH_SPENT - 0.05
    assert not endgame.pushing()


def test_re_committing_needs_both_gates_again() -> None:
    """Released is released - the map may have been lost while the army was away."""
    endgame = Endgame(control=0.94, fill=0.95)
    endgame.pushing()
    endgame._fill = PUSH_SPENT - 0.05
    endgame.pushing()

    endgame._fill = 1.0
    endgame._control = PUSH_CONTROL - 0.10
    assert not endgame.pushing()


def test_committing_dissolves_the_parties() -> None:
    """One force with one destination. The parties are dissolved rather than re-aimed, exactly as
    under siege, so nothing else is still holding battalions by id."""
    endgame = Endgame(control=0.94, fill=0.95)
    endgame._parties = {0: (1, 2), 1: (3, 4)}
    endgame._party_flag = {0: 99}
    endgame._forming = (5,)
    endgame._cav = (6,)

    assert endgame.pushing()
    assert endgame._parties == {}
    assert endgame._party_flag == {}
    assert endgame._forming == ()
    assert endgame._cav == ()


def test_a_keep_is_remembered_where_it_was_seen() -> None:
    """The fogged view has no memory and a player does. Buildings are what makes that honest -
    they do not move, so a remembered position stays true."""
    endgame = Endgame(control=0.5, fill=0.5)
    endgame._army = [_at(0.0, object_id=100)]
    endgame._visible = [_at(2000.0, object_id=7)]
    endgame.remember_keeps()

    endgame._visible = []  # walked away; the fog closed
    endgame.remember_keeps()
    assert endgame._seen_keeps == {7: (2000.0, 0.0, 0.0)}
    assert endgame.push_aim() == (2000.0, 0.0, 0.0)


def test_losing_sight_of_a_keep_is_not_evidence_it_is_gone() -> None:
    """**The bug this ordering avoids**: forgetting on absence turns the force round the moment
    it loses vision of its own destination, which under fog is most of the walk."""
    endgame = Endgame(control=0.5, fill=0.5)
    endgame._army = [_at(0.0, object_id=100)]
    endgame._visible = [_at(PUSH_ARRIVED * 4, object_id=7)]
    endgame.remember_keeps()

    endgame._visible = []
    endgame.remember_keeps()
    assert 7 in endgame._seen_keeps


def test_standing_where_a_keep_was_and_not_seeing_it_forgets_it() -> None:
    """Close up, absence means the opposite: the army is on top of the place and it is not there.
    Without this the force keeps walking at ground it has already taken."""
    endgame = Endgame(control=0.5, fill=0.5)
    endgame._army = [_at(0.0, object_id=100)]
    endgame._visible = [_at(PUSH_ARRIVED / 2, object_id=7)]
    endgame.remember_keeps()

    endgame._visible = []
    endgame.remember_keeps()
    assert endgame._seen_keeps == {}
    assert endgame.push_aim() is None


def test_nothing_ever_seen_is_nowhere_to_push() -> None:
    """A scouting failure, reported rather than papered over with the unfogged snapshot: what has
    never been seen is not something this bot is entitled to know."""
    endgame = Endgame(control=0.94, fill=0.95)
    endgame._army = [_at(0.0, object_id=100)]
    assert endgame.pushing()
    assert endgame.push_aim() is None


def test_the_nearest_visible_target_is_the_one_attacked() -> None:
    """One target at a time, nearest to the force - a push that splits is the thing the parties
    do to take a map, and it is exactly wrong for ending one."""
    endgame = Endgame(control=0.94, fill=0.95)
    endgame._army = [_at(0.0, object_id=100)]
    endgame._visible = [_at(3000.0, object_id=7), _at(500.0, object_id=8)]
    assert endgame.push_target().object_id == 8


def test_a_remembered_keep_is_chosen_nearest_first() -> None:
    endgame = Endgame(control=0.94, fill=0.95)
    endgame._army = [_at(0.0, object_id=100)]
    endgame._visible = [_at(3000.0, object_id=7), _at(900.0, object_id=8)]
    endgame.remember_keeps()
    endgame._visible = []
    assert endgame.push_aim() == (900.0, 0.0, 0.0)


class Fill:
    """`command_fill` over a supplied `command_points` pair."""

    command_fill = World.command_fill

    def __init__(self, pair: tuple[int, int] | None) -> None:
        me = None if pair is None else SimpleNamespace(command_points=pair)
        self.observation = SimpleNamespace(me=me)


def test_the_fill_is_the_army_against_its_own_ceiling() -> None:
    """Run 4's endgame reading, which held for four hundred cycles."""
    assert Fill((1440, 1500)).command_fill() == 1440 / 1500


def test_no_local_player_is_an_empty_army_rather_than_a_full_one() -> None:
    """Between matches, or at a loading screen. Reading this as full would commit the push on a
    reading that means nothing."""
    assert Fill(None).command_fill() == 0.0


def test_a_cap_that_has_not_loaded_does_not_hold_a_push_open() -> None:
    """A zero cap is a reading that has not arrived, not an army with no room. Dividing by it is
    the obvious crash; calling it empty is the subtler bug, since a permanently unmet gate is
    indistinguishable from a bot that never wants to win."""
    assert Fill((0, 0)).command_fill() == 1.0


class Assault:
    """`stage_push` with the orders recorded rather than sent."""

    stage_push = Warfare.stage_push
    push_target = Warfare.push_target
    push_aim = Warfare.push_aim

    def __init__(self, army: list[SimpleNamespace], visible: list[SimpleNamespace]) -> None:
        self._army = army
        self._visible = visible
        self._groups: dict[int, tuple[int, ...]] = {}
        self._seen_keeps: dict[int, tuple[float, float, float]] = {}
        self._siege = False
        self.engaged: list[SimpleNamespace] = []
        self.marched: list[tuple[float, float, float]] = []
        self.sent: list[int] = []

    def army(self) -> list[SimpleNamespace]:
        return self._army

    def victory_targets(self) -> list[SimpleNamespace]:
        return self._visible

    def besieged(self) -> bool:
        return self._siege

    def screen(self, force, target, key):  # noqa: ANN001, ANN201
        return [], None

    def engage(self, force, target, what, key):  # noqa: ANN001, ANN201
        self.engaged.append(target)
        self.sent.append(len(force))
        return f"{len(force)} at {what}"

    def march(self, force, aim, what, key):  # noqa: ANN001, ANN201
        self.marched.append(aim)
        self.sent.append(len(force))
        return f"{len(force)} sent at {what}"


def test_the_whole_force_goes_at_the_nearest_target() -> None:
    army = [_at(0.0, object_id=i) for i in range(1, 7)]
    assault = Assault(army, [_at(3000.0, object_id=7), _at(600.0, object_id=8)])
    said = assault.stage_push()

    assert said is not None and "push" in said
    assert [o.object_id for o in assault.engaged] == [8]
    assert assault.sent == [6]


def test_the_defence_keeps_what_it_claimed_and_the_rest_pushes() -> None:
    """Losing the base still ends the match, and `stage_defend` has already run this cycle."""
    army = [_at(0.0, object_id=i) for i in range(1, 7)]
    assault = Assault(army, [_at(600.0, object_id=8)])
    assault._groups = {42: (1, 2)}

    assault.stage_push()
    assert assault.sent == [4]


def test_a_siege_at_home_outranks_the_push() -> None:
    """The one case where turning round is right - `besieged` is more raiders than the whole army
    can meet, so there is no version of continuing that keeps the base. The latch survives it."""
    assault = Assault([_at(0.0, object_id=1)], [_at(600.0, object_id=8)])
    assault._siege = True
    assert assault.stage_push() is None
    assert assault.engaged == []


def test_a_force_entirely_spoken_for_by_the_defence_pushes_with_nobody() -> None:
    assault = Assault([_at(0.0, object_id=1)], [_at(600.0, object_id=8)])
    assault._groups = {42: (1,)}
    assert assault.stage_push() is None


def test_with_nothing_in_sight_the_force_walks_at_what_it_remembers() -> None:
    assault = Assault([_at(0.0, object_id=1)], [])
    assault._seen_keeps = {7: (2500.0, 0.0, 0.0)}
    said = assault.stage_push()

    assert assault.marched == [(2500.0, 0.0, 0.0)]
    assert said is not None and "their base" in said


def test_nothing_seen_and_nothing_remembered_says_so() -> None:
    """Reported rather than silent: a push with nowhere to go is a scouting failure, and a stage
    that returned None would be indistinguishable from one that had already won."""
    assault = Assault([_at(0.0, object_id=1)], [])
    assert assault.stage_push() == "push: nothing of theirs has been seen to walk to"
