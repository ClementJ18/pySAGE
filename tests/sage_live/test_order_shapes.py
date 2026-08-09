"""Every constructor's argument shape, against what the engine actually records.

These were written from the order map's prose, and five of them were wrong: `recruit` emitted
2 arguments where the engine records 5, `attack_object` 1 where it records 2, and the three
casts were each one short. A short order is the worst kind of wrong - `appendMessage` takes
it, it is network-ordered, it reaches the replay, and then game logic silently discards it.
Nothing errors, nothing is charged, nothing happens.

The shapes below come from a survey of 5 recorded RotWK/Edain games (`0x417` 823 orders,
`0x425` 966, `0x42F` 6945, `0x3E9` 3942, `0x410` 142, `0x411` 165, `0x412` 24). Where the
survey found a position constant across every recorded order, the constructor hardcodes it and
the test pins the value too.

Data-free by construction: the shapes are the assertion, no corpus is read here.
"""

from __future__ import annotations

import pytest

from sage_live import orders
from sage_replay.replay import OrderArgumentType as T

POSITION = (1.0, 2.0, 3.0)


def shape(order) -> list[int]:
    return [int(a.argument_type) for a in order.arguments]


def values(order) -> list:
    return [a.value for a in order.arguments]


@pytest.mark.parametrize(
    "order,expected",
    [
        (orders.select(0, [7]), [T.Boolean, T.ObjectId]),
        (orders.select(0, [7, 8, 9]), [T.Boolean, T.ObjectId, T.ObjectId, T.ObjectId]),
        (orders.deselect(0), [T.Boolean]),
        (orders.move(0, POSITION), [T.Position]),
        (orders.stop(0), []),
        (orders.attack_object(0, 7, POSITION), [T.ObjectId, T.Position]),
        (orders.build_at(0, 7, POSITION), [T.Integer, T.Position, T.Float]),
        (
            orders.recruit(0, 7),
            [T.Boolean, T.Integer, T.Integer, T.Boolean, T.Boolean],
        ),
        (orders.research(0, 7, 545), [T.ObjectId, T.Integer]),
        (orders.purchase_power(0, 7), [T.Integer, T.Integer]),
        (orders.cast_self(0, 7), [T.Integer, T.Integer, T.ObjectId, T.ObjectId]),
        (
            orders.cast_at_location(0, 7, POSITION),
            [T.Integer, T.Position, T.ObjectId, T.Integer, T.ObjectId],
        ),
        (
            orders.cast_at_object(0, 7, 8, POSITION),
            [T.Integer, T.ObjectId, T.Integer, T.ObjectId, T.Position],
        ),
        (orders.set_stance(0, 2), [T.Integer]),
        (orders.toggle_formation(0, 7), [T.ObjectId]),
        (orders.unpack(0, 7), [T.Integer]),
        (orders.attack_move(0, POSITION), [T.Position]),
    ],
)
def test_argument_shape_matches_what_the_engine_records(order, expected):
    assert shape(order) == [int(t) for t in expected]


def test_unpack_carries_only_the_template_it_creates():
    """No position: the selected plot is the location. A single Int is the whole order."""
    assert values(orders.unpack(0, 4411)) == [4411]


def test_toggle_formation_names_the_horde_and_carries_nothing_else():
    """No formation id: the order flips whichever of the two the battalion is in, and which
    that is comes from `HordeContain.AlternateFormation` rather than from the order. There is
    no way to *ask* for a named formation - `MSG_HORDE_SET_FORMATION` is a separate message
    and every button in RotWK+Edain that would send it is commented out."""
    assert values(orders.toggle_formation(0, 4411)) == [4411]
    assert int(orders.toggle_formation(0, 1).order_type) == 0x453


def test_attack_move_is_a_distinct_type_from_move():
    """Same shape, different id. Sending `move` where A-move was meant walks units past
    enemies that are shooting at them, which looks like broken combat rather than a wrong
    order type."""
    a, m = orders.attack_move(0, POSITION), orders.move(0, POSITION)
    assert shape(a) == shape(m)
    assert a.order_type != m.order_type


def test_recruit_carries_the_constant_tail():
    """`-1, False, False` in 822 of 822 recorded orders. Omitting them is silently ignored."""
    assert values(orders.recruit(0, 6114)) == [False, 6114, -1, False, False]


def test_recruit_flags_a_template_id_rather_than_a_command_slot():
    """The leading Boolean picks how argument 1 is read; True would make 6114 a slot index."""
    assert values(orders.recruit(0, 6114))[0] is False


def test_research_names_the_building_in_the_first_argument():
    """Verified live: 0 here is consumed and then discarded - nothing charged, nothing built.

    The building must be named even when it is the current selection, so `building_id` has no
    default. This test exists to stop a well-meaning default coming back.
    """
    assert values(orders.research(0, 289, 545)) == [545, 289]
    with pytest.raises(TypeError):
        orders.research(0, 289)  # type: ignore[call-arg]


def test_a_ground_cast_defaults_to_an_options_value_the_corpus_actually_uses():
    """0 is never recorded for this field, so it was a bad default to ship."""
    assert orders.DEFAULT_CAST_OPTIONS != 0
    assert values(orders.cast_at_location(0, 7, POSITION))[3] == orders.DEFAULT_CAST_OPTIONS


def test_an_object_cast_carries_the_target_position_last():
    assert values(orders.cast_at_object(0, 7, 8, POSITION))[-1] == POSITION


def test_castle_unpack_carries_no_arguments():
    """What the flag's own button sends. The engine reads what to build off the target's
    `CastleBehavior`, so naming a template here is the *other* order."""
    order = orders.castle_unpack(3)
    assert order.order_type == orders.OrderType.CASTLE_UNPACK == 0x43D
    assert order.arguments == []


def test_the_two_unpack_orders_are_different_ids():
    """`0x43D` is what a player clicks; `0x43F` names a template explicitly. Conflating them
    is why the unpack path stayed unverified for so long."""
    assert orders.castle_unpack(0).order_type != orders.unpack(0, 5).order_type
