"""Which flag the opening walks to, when nearest is the wrong first question.

`external_plots` sorts by distance and nothing else, which is right for a force that can take
whatever it arrives at. The opening is not that force: it is four battalions, and the nearest
flag is as often an outpost with a lair sitting on it as it is an empty settlement. A settlement
is one build order for an income building; an outpost is a castle to garrison. Nearest-first
spends the opening failing at the expensive one.

The two plot families are indistinguishable to everything else in the bot - both are unclaimed
flags offering the same neutral claim button - so `Statics.plot_family` is what tells them apart,
and these tests pin the ordering it feeds.
"""

from __future__ import annotations

from types import SimpleNamespace

from sage_mods.edain.bot.warfare import Warfare

SETTLEMENT = "WirtschaftPlotFlag_Real"
OUTPOST = "ExpansionPlotFlag"


def _flag(object_id: int, template: str, x: float, owner: int = 9) -> SimpleNamespace:
    return SimpleNamespace(
        object_id=object_id,
        template_name=template,
        owner_index=owner,
        position=(x, 0.0, 0.0),
        distance_to=lambda other, _x=x: abs(other[0] - _x),
    )


class Field:
    """`expansion_order` over flags whose defenders and phase are set by hand."""

    expansion_order = Warfare.expansion_order

    def __init__(self, guards: dict[int, int] | None = None, phase: int = 0) -> None:
        self._guards = guards or {}
        self._phase = phase
        self.statics = SimpleNamespace(
            plot_family=lambda name: "settlement" if name == SETTLEMENT else "outpost"
        )

    def phase(self) -> int:
        return self._phase

    def base_centre(self) -> tuple[float, float, float]:
        return (0.0, 0.0, 0.0)

    def defenders(self, flag: SimpleNamespace) -> list:
        return [object()] * self._guards.get(flag.object_id, 0)


def _ids(flags: list) -> list[int]:
    return [flag.object_id for flag in flags]


def test_a_settlement_is_taken_before_a_nearer_outpost() -> None:
    """The bug in one line. The outpost is on the doorstep and is still the wrong opening."""
    field = Field()
    flags = [_flag(1, OUTPOST, 100.0), _flag(2, SETTLEMENT, 900.0)]
    assert _ids(field.expansion_order(flags)) == [2, 1]


def test_the_quieter_settlement_wins_between_two_settlements() -> None:
    """Refusing what the party cannot beat is not the same as choosing among what it can. The
    one that costs fewest battalions is the one that leaves an army to take the next."""
    field = Field(guards={1: 4, 2: 0})
    flags = [_flag(1, SETTLEMENT, 100.0), _flag(2, SETTLEMENT, 900.0)]
    assert _ids(field.expansion_order(flags)) == [2, 1]


def test_distance_still_decides_when_nothing_else_does() -> None:
    """The behaviour this replaces is kept as the last key, not thrown away."""
    field = Field()
    flags = [_flag(1, SETTLEMENT, 900.0), _flag(2, SETTLEMENT, 100.0)]
    assert _ids(field.expansion_order(flags)) == [2, 1]


def test_family_outranks_the_defender_count() -> None:
    """A guarded settlement is still the opening's business before an empty outpost: the outpost
    is a castle to garrison whether or not anyone is standing on it."""
    field = Field(guards={1: 0, 2: 3})
    flags = [_flag(1, OUTPOST, 100.0), _flag(2, SETTLEMENT, 100.0)]
    assert _ids(field.expansion_order(flags)) == [2, 1]


def test_past_the_rush_phase_the_order_is_left_alone() -> None:
    """**The restraint is the design.** With an army, an outpost is a second castle and worth
    more than a settlement, so this must not follow the bot through the whole match.

    The gate is `phase` and was `opening` first, which made the whole method nearly inert:
    `opening` ends when a barracks stands, measured live at cycle 5, before a single party
    had reached a flag."""
    field = Field(guards={1: 5}, phase=1)
    flags = [_flag(1, OUTPOST, 100.0), _flag(2, SETTLEMENT, 900.0)]
    assert _ids(field.expansion_order(flags)) == [1, 2]


def test_an_unknown_family_sorts_with_the_outposts() -> None:
    """`plot_family` answers None for anything that is not one of the four, and the opening's
    preference is *for* settlements rather than against any particular other thing."""
    field = Field()
    field.statics = SimpleNamespace(plot_family=lambda name: None)
    flags = [_flag(1, OUTPOST, 900.0), _flag(2, SETTLEMENT, 100.0)]
    assert _ids(field.expansion_order(flags)) == [2, 1]


class Sticky(Field):
    """`worth_taking`'s commitment, over a board where the map spawns late."""

    worth_taking = Warfare.worth_taking
    outranked_by_a_settlement = Warfare.outranked_by_a_settlement

    def __init__(self, flags: list, phase: int = 0) -> None:
        super().__init__(phase=phase)
        self._flags = flags
        self._blocked_flags: dict[int, float] = {}
        self.session = SimpleNamespace(player_index=1)

    def external_plots(self) -> list:
        return self._flags


def test_a_commitment_made_before_the_map_spawned_is_released() -> None:
    """**The race the ordering could not win.** Plots arrive in object-id order and on a
    measured Edain map the two outposts were ids 123 and 124 while every settlement was above
    939 - so cycle 2 offered two flags, both outposts, and the party committed before a single
    settlement existed. It then walked 1819 units to it."""
    outpost = _flag(124, OUTPOST, 1819.0)
    settlement = _flag(958, SETTLEMENT, 696.0)
    field = Sticky([outpost, settlement])
    assert field.worth_taking([object()] * 4, 124, set()).object_id == 958


def test_a_party_already_holding_a_settlement_keeps_it() -> None:
    """The commitment is right in every other case, and re-deciding every cycle is what stopped
    expansion dead after two settlements."""
    held = _flag(958, SETTLEMENT, 1900.0)
    nearer = _flag(959, SETTLEMENT, 100.0)
    field = Sticky([held, nearer])
    assert field.worth_taking([object()] * 4, 958, set()).object_id == 958


def test_an_outpost_is_kept_once_there_is_an_army() -> None:
    """Past the rush an outpost is a second castle, so the release must not follow the bot
    through the whole match."""
    outpost = _flag(124, OUTPOST, 1819.0)
    settlement = _flag(958, SETTLEMENT, 696.0)
    field = Sticky([outpost, settlement], phase=1)
    assert field.worth_taking([object()] * 4, 124, set()).object_id == 124


def test_an_outpost_is_kept_when_no_settlement_is_going_spare() -> None:
    """Releasing with nothing better available would drop the commitment for nothing and
    restart the walk from wherever the party had got to."""
    outpost = _flag(124, OUTPOST, 1819.0)
    other = _flag(123, OUTPOST, 200.0)
    field = Sticky([outpost, other])
    assert field.worth_taking([object()] * 4, 124, set()).object_id == 124
