"""When a flag can be built on: two rules, both invisible in an observation, both flag-only.

A **flag** - a settlement, outpost, castle or camp - is unbuildable for about twelve *game*
seconds after whatever stood on it is gone, and unbuildable while something hostile is standing on
it. The two are independent: different rules on different clocks, either can be true without the
other, and a flag has to clear both.

A **castle foundation** obeys neither. It has no rebuild cooldown and cannot be contested, so
`free_plots` asks neither question and `buildable_sites` does not even track foundations - a
timestamp nothing reads would imply a rule that does not exist.

Neither check belongs in `external_plots`, which is a walk target chosen many cycles before the
build: a resting flag is still worth marching to, and a contested one is precisely the flag the
bot should be marching at. `raise_settlement` is where the order goes out and where both are
asked - see `test_bot_flag_rebuild`.

**The cooldown is counted in logic frames, not wall-clock seconds.** The engine advances at 4-6
logic frames a second against its nominal 30 under the bridge, so twelve game seconds is a minute
or more of real time; a wall-clock rest would expire while the flag was still refusing, which is
the bug wearing a fix. Every other rest in this bot is a heuristic about contested ground and is
rightly wall-clock. This one is a game rule.
"""

from __future__ import annotations

from types import SimpleNamespace

from sage_mods.edain.bot.tuning import PLOT_REBUILD_SECONDS
from sage_mods.edain.bot.world import World

FLAG = "WirtschaftPlotFlag"
FOUNDATION = "GondorBuildingFoundation"
FPS = 30.0
# What the rule costs in frames, which is what `resting` actually compares.
REST = PLOT_REBUILD_SECONDS * FPS


def _at(object_id: int, x: float, template: str = FLAG, owner: int | None = 1) -> SimpleNamespace:
    return SimpleNamespace(
        object_id=object_id,
        template_name=template,
        position=(x, 0.0, 0.0),
        owner_index=owner,
        distance_to=lambda other, _x=x: abs(other[0] - _x),
    )


class _Statics:
    def is_build_site(self, template: str) -> bool:
        return template.endswith("Foundation") or template.endswith("PlotFlag")

    def unpack_buttons(self, template: str, upgrades=()) -> tuple:
        # The palette is what tells a flag from a foundation, here as in `free_plots`.
        return (("slot",),) if template.endswith("PlotFlag") else ()

    def has_kind(self, template: str, *flags: str) -> bool:
        # A battalion is not a structure however it is spelled. Saying otherwise makes a raider
        # standing on a flag count as the thing occupying it, so the flag never registers as
        # *freed* - which quietly disables the very transition these tests are about.
        if "STRUCTURE" not in flags:
            return False
        return not self.is_build_site(template) and "Horde" not in template


class Board:
    """The plot-state reads over a stub board.

    Borrowed rather than inherited: `BotState.observation` is a property that reads the live
    session, so a subclass cannot be handed a fixed one.
    """

    note_freed_plots = World.note_freed_plots
    buildable_sites = World.buildable_sites
    is_flag = World.is_flag
    resting = World.resting
    contested = World.contested
    occupied = World.occupied
    structures = World.structures
    free_plots = World.free_plots
    external_plots = World.external_plots

    def __init__(self, objects: list, frame: int = 1000, raiders: list | None = None) -> None:
        self._raiders = list(raiders or [])
        self._objects = list(objects) + self._raiders
        self.observation = SimpleNamespace(mine=self._objects, objects=self._objects, frame=frame)
        self.statics = _Statics()
        self._plot_held: set[int] = set()
        self._plot_freed: dict[int, int] = {}
        self._blocked_plots: dict[int, float] = {}
        self._home = (0.0, 0.0, 0.0)
        self._fps = FPS

    def plots_now(self):
        return [o for o in self._objects if self.statics.is_build_site(o.template_name)]

    def base_centre(self):
        return (0.0, 0.0, 0.0)

    def hostile(self, obj) -> bool:
        return obj in self._raiders

    def at(self, frame: int, objects: list, raiders: list | None = None) -> None:
        """Advance to a later frame with a new board, as a cycle does."""
        if raiders is not None:
            self._raiders = list(raiders)
        self._objects = list(objects) + self._raiders
        self.observation = SimpleNamespace(mine=self._objects, objects=self._objects, frame=frame)


# --- what the rules are about ------------------------------------------------------------


def test_a_flag_is_told_from_a_foundation_by_its_palette():
    board = Board([_at(1, 0.0, FLAG), _at(2, 500.0, FOUNDATION)])
    assert board.is_flag(board._objects[0])
    assert not board.is_flag(board._objects[1])


def test_only_flags_are_tracked_between_cycles():
    """A foundation has no cooldown, so remembering when it was freed would imply a rule that
    does not exist."""
    flag, foundation = _at(1, 0.0, FLAG), _at(2, 500.0, FOUNDATION)
    farm, house = _at(60, 5.0, "GondorFarm_Extern"), _at(61, 505.0, "GondorWohnhaus01")
    board = Board([flag, foundation, farm, house], frame=1000)
    board.note_freed_plots()
    assert board._plot_held == {1}

    board.at(1030, [flag, foundation])  # both buildings die
    board.note_freed_plots()
    assert board._plot_freed == {1: 1030}
    assert board.resting(flag)
    assert not board.resting(foundation)


def test_a_foundation_is_offered_the_instant_its_building_dies():
    """Foundations obey neither rule, so `free_plots` asks neither."""
    foundation, house = _at(2, 500.0, FOUNDATION), _at(61, 505.0, "GondorWohnhaus01")
    board = Board([foundation, house], frame=1000)
    board.note_freed_plots()
    board.at(1030, [foundation])
    board.note_freed_plots()
    assert [p.object_id for p in board.free_plots()] == [2]


def test_a_raider_on_a_foundation_does_not_block_it_either():
    foundation = _at(2, 500.0, FOUNDATION)
    board = Board([foundation], raiders=[_at(90, 510.0, "IsengardUrukHorde")])
    board.note_freed_plots()
    assert [p.object_id for p in board.free_plots()] == [2]


# --- the cooldown ------------------------------------------------------------------------


def test_a_flag_nothing_was_ever_seen_on_is_not_resting():
    """Every flag at the start of a match, and the safe direction to be wrong in."""
    flag = _at(1, 0.0)
    board = Board([flag])
    board.note_freed_plots()
    assert not board.resting(flag)


def test_a_flag_whose_building_just_died_is_rested():
    """The fault, in the two cycles it takes to happen."""
    flag, farm = _at(1, 0.0), _at(60, 5.0, "GondorFarm_Extern")
    board = Board([flag, farm], frame=1000)
    board.note_freed_plots()
    assert board._plot_held == {1}

    board.at(1030, [flag])  # the farm is razed
    board.note_freed_plots()
    assert board._plot_freed == {1: 1030}
    assert board.resting(flag)


def test_the_rest_expires_on_the_games_clock():
    flag, farm = _at(1, 0.0), _at(60, 5.0, "GondorFarm_Extern")
    board = Board([flag, farm], frame=1000)
    board.note_freed_plots()
    board.at(1030, [flag])
    board.note_freed_plots()

    board.at(int(1030 + REST) - 1, [flag])
    assert board.resting(flag)
    board.at(int(1030 + REST) + 1, [flag])
    assert not board.resting(flag)


def test_a_wall_clock_rest_would_have_expired_far_too_early():
    """The reason this is counted in frames.

    Twelve seconds of the operator's time is about 60 logic frames at the 5fps the engine
    actually manages under the bridge - a fraction of the rule - so a wall-clock rest would have
    let the flag back in while it was still refusing orders.
    """
    engine_frames_in_twelve_wall_seconds = 12 * 5
    assert engine_frames_in_twelve_wall_seconds < REST


def test_building_on_a_flag_does_not_rest_it():
    """The transition is losing what stood there, not gaining it - a flag built on normally must
    not be rested, or the bot would pause after every successful capture."""
    flag = _at(1, 0.0)
    board = Board([flag], frame=1000)
    board.note_freed_plots()
    board.at(1030, [flag, _at(60, 5.0, "GondorFarm_Extern")])
    board.note_freed_plots()
    assert board._plot_freed == {}
    assert not board.resting(flag)


def test_a_resting_flag_is_still_worth_walking_to():
    """`external_plots` is a walk target chosen many cycles before the build, so the cooldown -
    which expires long before a party arrives - must not drop it from the candidates."""
    flag, farm = _at(1, 0.0), _at(60, 5.0, "GondorFarm_Extern")
    board = Board([flag, farm], frame=1000)
    board.note_freed_plots()
    board.at(1030, [flag])
    board.note_freed_plots()
    assert board.resting(flag)
    assert [p.object_id for p in board.external_plots()] == [1]


# --- contested ground, and the two together ----------------------------------------------


def test_a_raider_standing_on_a_flag_contests_it_whatever_the_clock_says():
    flag = _at(1, 0.0)
    board = Board([flag], frame=1000, raiders=[_at(90, 20.0, "IsengardUrukHorde")])
    board.note_freed_plots()
    assert not board.resting(flag)  # nothing was ever removed from it
    assert board.contested(flag)

    board.at(1030, [flag], raiders=[])
    assert not board.contested(flag)


def test_our_own_battalions_never_contest_a_flag():
    """A party that has just taken a flag is standing on it by definition."""
    flag = _at(1, 0.0)
    board = Board([flag, _at(50, 10.0, "GondorFighterHorde")])
    assert not board.contested(flag)


def test_both_refusals_can_be_true_of_one_flag_at_once():
    """The case the two rules being independent is about."""
    flag, farm = _at(1, 0.0), _at(60, 5.0, "GondorFarm_Extern")
    board = Board([flag, farm], frame=1000)
    board.note_freed_plots()

    # The raider that killed the farm is standing on the ground it stood on.
    board.at(1030, [flag], raiders=[_at(90, 15.0, "IsengardUrukHorde")])
    board.note_freed_plots()
    assert board.resting(flag) and board.contested(flag)

    # The raider leaves, and the timer is still running.
    board.at(1060, [flag], raiders=[])
    assert not board.contested(flag)
    assert board.resting(flag)

    # The timer expires with the ground still clear.
    board.at(int(1030 + REST) + 1, [flag], raiders=[])
    assert not board.resting(flag) and not board.contested(flag)
