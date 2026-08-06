"""When the bot calls a match over, and - mostly - when it refuses to.

Every failure here is a result that looks real and means nothing, which is why the refusals get
more tests than the calls. A crashed game and a won match produce the same empty observation; a
match at frame 0 has spawned nobody's base yet and so reads as everyone simultaneously defeated;
and a fogged opponent who has merely walked out of sight reads exactly like a destroyed one.

The last of those is the reason this file exists. Victory used to be abandoned outright under
fog, because the filtered snapshot cannot distinguish those two - so the test that matters is
that reading the *unfogged* snapshot restores it without letting anything else through.
"""

from __future__ import annotations

from types import SimpleNamespace

from sage_mods.edain.bot.bot import Bot


class Ending:
    """`finished` over hand-built snapshots, with the fogged and unfogged halves set apart."""

    finished = Bot.finished
    started = Bot.started

    def __init__(
        self,
        mine: list[int],
        theirs: list[int],
        *,
        fogged_theirs: list[int] | None = None,
        alive: bool = True,
        in_match: bool = True,
    ) -> None:
        self._held = False
        self._opposed = False
        self.statics = SimpleNamespace(counts_for_victory=lambda name: name == "keep")
        # The fogged view is what every tactical stage reads; `fogged_theirs` defaults to the
        # unfogged list so a test only has to say so when it wants the two to disagree.
        seen = theirs if fogged_theirs is None else fogged_theirs
        self.observation = self._snapshot(mine, seen, in_match)
        self.session = SimpleNamespace(
            player_index=1,
            alive=alive,
            latest_unfogged=self._snapshot(mine, theirs, in_match),
        )

    def _snapshot(self, mine: list[int], theirs: list[int], in_match: bool) -> SimpleNamespace:
        objects = [SimpleNamespace(owner_index=1, template_name=n) for n in _named(mine)]
        objects += [SimpleNamespace(owner_index=2, template_name=n) for n in _named(theirs)]
        return SimpleNamespace(
            in_match=in_match,
            opponents=(SimpleNamespace(index=2),),
            owned_by=lambda i, objs=objects: tuple(o for o in objs if o.owner_index == i),
        )

    _holdings = Bot._holdings


def _named(counts: list[int]) -> list[str]:
    """`[1, 2]` -> one object that counts for victory and two that do not."""
    return ["keep"] * counts[0] + ["farm"] * (counts[1] if len(counts) > 1 else 0)


def test_a_match_still_being_played_is_not_a_result() -> None:
    assert Ending(mine=[1], theirs=[1]).finished() is None


def test_losing_the_last_holding_is_a_defeat() -> None:
    match = Ending(mine=[1], theirs=[1])
    assert match.finished() is None  # the latch has to see us hold something first
    match.observation = match._snapshot([0], [1], True)
    match.session.latest_unfogged = match._snapshot([0], [1], True)
    assert "defeat" in (match.finished() or "")


def test_taking_the_last_opposing_holding_is_a_victory() -> None:
    match = Ending(mine=[1], theirs=[1])
    assert match.finished() is None
    match.session.latest_unfogged = match._snapshot([1], [0], True)
    assert "victory" in (match.finished() or "")


def test_victory_is_called_under_fog_from_the_unfogged_snapshot() -> None:
    """The behaviour this change is for.

    The fogged view shows no opposing holdings because nothing of ours is watching them, which is
    exactly what a destroyed base looks like. The unfogged view still has them, so this is a match
    in progress and not a win - and the old code, reading only the filtered snapshot, could not
    tell the difference in either direction.
    """
    match = Ending(mine=[1], theirs=[1], fogged_theirs=[0])
    assert match.finished() is None
    assert match._opposed  # seen through the fog, so the latch is armed

    # Now they really are gone, and only the unfogged snapshot can say so.
    match.session.latest_unfogged = match._snapshot([1], [0], True)
    assert "victory" in (match.finished() or "")


def test_an_economy_building_does_not_keep_a_beaten_player_alive() -> None:
    """`IGNORE_FOR_VICTORY` is on the farms precisely so counting all objects is wrong."""
    match = Ending(mine=[1], theirs=[1])
    match.finished()
    match.session.latest_unfogged = match._snapshot([0, 3], [1], True)
    assert "defeat" in (match.finished() or "")


def test_nobody_is_defeated_before_the_map_has_spawned_anything() -> None:
    """`wait_for_match` returns before the bases exist, and frame 0 owns nothing at all."""
    assert Ending(mine=[0], theirs=[0]).finished() is None


def test_a_crashed_game_is_not_a_result() -> None:
    """It reads identically to a won match - no objects, no local player - so the process is
    asked first and the answer says plainly that it is not a result."""
    over = Ending(mine=[0], theirs=[0], alive=False).finished()
    assert over is not None and "not a result" in over


def test_the_match_ending_outright_is_reported_before_anything_is_inferred() -> None:
    assert "the match ended" in (Ending(mine=[1], theirs=[1], in_match=False).finished() or "")


def test_a_match_has_begun_only_once_both_sides_have_held_something() -> None:
    match = Ending(mine=[1], theirs=[1])
    assert not match.started
    match.finished()
    assert match.started
