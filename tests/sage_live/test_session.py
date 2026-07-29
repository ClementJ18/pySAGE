"""Session behaviour: the handshake gate, selection tracking, the APM cap, and a scripted
game driving a policy end to end."""

from __future__ import annotations

import pytest

from sage_live import (
    ConnectionRefused,
    GameObject,
    Handshake,
    LoopbackBackend,
    NoSelection,
    Observation,
    OrderType,
    PlayerState,
    Session,
)


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def obj(object_id: int, template: str = "GondorFighter", side: str = "Men") -> GameObject:
    return GameObject(
        object_id=object_id,
        template_name=template,
        template_side=side,
        position=(100.0 * object_id, 200.0, 61.0),
        angle=0.0,
        health=1.0,
        max_health=255.0,
        owner_index=3,
    )


def frame(n: int, objects, resources: int = 1000) -> Observation:
    return Observation(
        frame=n,
        local_player=3,
        players=(PlayerState(index=3, name="Player_1", faction="Men", resources=resources),),
        objects=tuple(objects),
    )


def test_handshake_matching_peer_connects():
    expected = Handshake(engine_build="RotWK 2.01", data_checksum="edain-4.7")
    backend = LoopbackBackend(handshake=expected, expect=expected)
    assert Session(backend).connect() == expected


@pytest.mark.parametrize(
    "peer",
    [
        Handshake(protocol_version=99, engine_build="RotWK 2.01", data_checksum="edain-4.7"),
        Handshake(engine_build="RotWK 2.02", data_checksum="edain-4.7"),
        Handshake(engine_build="RotWK 2.01", data_checksum="edain-4.6"),
    ],
)
def test_handshake_mismatch_refuses_the_connection(peer):
    expected = Handshake(engine_build="RotWK 2.01", data_checksum="edain-4.7")
    session = Session(LoopbackBackend(handshake=peer, expect=expected))
    with pytest.raises(ConnectionRefused):
        session.connect()


def test_observations_arrive_in_order_and_are_cached():
    script = [frame(1, [obj(10)]), frame(2, [obj(10), obj(11)])]
    session = Session(LoopbackBackend(script), player_index=3)
    session.connect()
    assert session.poll().frame == 1
    assert session.poll().frame == 2
    # the script is exhausted, so the last observation stands
    assert session.poll().frame == 2
    assert session.latest.frame == 2


def test_selection_is_tracked_and_orders_carry_it():
    backend = LoopbackBackend([frame(1, [obj(10), obj(11)])])
    session = Session(backend, player_index=3)
    session.connect()
    session.poll()

    session.select([10, 11])
    assert session.selection == (10, 11)
    assert backend.sent[-1].order_type == OrderType.CREATE_SELECTED_GROUP

    session.move((1200.0, 880.0, 0.0))
    assert backend.sent[-1].order_type == OrderType.DO_MOVETO

    session.deselect()
    assert session.selection == ()


def test_additive_selection_unions_without_duplicates():
    session = Session(LoopbackBackend(), player_index=3)
    session.connect()
    session.select([10, 11])
    session.select([11, 12], additive=True)
    assert session.selection == (10, 11, 12)


def test_selection_dependent_order_refuses_with_empty_selection():
    session = Session(LoopbackBackend(), player_index=3)
    session.connect()
    with pytest.raises(NoSelection):
        session.move((0.0, 0.0, 0.0))
    with pytest.raises(NoSelection):
        session.recruit(42)


def test_dead_objects_are_pruned_from_the_selection():
    script = [frame(1, [obj(10), obj(11)]), frame(2, [obj(10)])]
    session = Session(LoopbackBackend(script), player_index=3)
    session.connect()
    session.poll()
    session.select([10, 11])
    session.poll()
    assert session.selection == (10,), "11 died and should have left the selection"


def test_fogged_observations_do_not_prune_the_selection():
    script = [
        Observation(frame=1, local_player=3, objects=(obj(10), obj(11)), fogged=True),
        Observation(frame=2, local_player=3, objects=(obj(10),), fogged=True),
    ]
    session = Session(LoopbackBackend(script), player_index=3)
    session.connect()
    session.poll()
    session.select([10, 11])
    session.poll()
    assert session.selection == (10, 11), "under fog, absent means unseen, not dead"


def test_apm_cap_throttles_and_the_window_slides():
    clock = FakeClock()
    backend = LoopbackBackend()
    session = Session(backend, player_index=3, apm_cap=5, clock=clock)
    session.connect()

    accepted = sum(session.select([i]) for i in range(10))
    assert accepted == 5
    assert session.throttled == 5
    assert len(backend.sent) == 5

    clock.now += 61.0
    assert session.select([99]) == 1, "the window should have slid"


def test_apm_cap_of_zero_disables_throttling():
    session = Session(LoopbackBackend(), player_index=3, apm_cap=0)
    session.connect()
    assert sum(session.select([i]) for i in range(50)) == 50
    assert session.throttled == 0


def test_send_before_connect_is_a_diagnostic_not_a_crash():
    backend = LoopbackBackend()
    session = Session(backend, player_index=3)
    session.select([1])
    assert backend.sent == []
    assert any("before connect" in d.message for d in session.diagnostics)


def test_context_manager_connects_and_closes():
    backend = LoopbackBackend([frame(1, [obj(10)])])
    with Session(backend, player_index=3) as session:
        assert backend.connected
        assert session.poll() is not None
    assert not backend.connected


def test_connect_is_idempotent_so_attach_and_a_with_block_compose():
    """`attach` connects to read the local player's seat; the `with` block connects again."""
    backend = LoopbackBackend(handshake=Handshake(engine_build="RotWK 2.01"))
    session = Session(backend, player_index=3)
    first = session.connect()
    with session as reentered:
        assert reentered.connect() is first
    assert not session.connected, "closing should clear the handshake"


def test_observe_raises_rather_than_answering_none():
    session = Session(LoopbackBackend(), player_index=3)
    session.connect()
    with pytest.raises(LookupError):
        session.observe()


def test_observe_returns_the_snapshot_when_there_is_one():
    session = Session(LoopbackBackend([frame(7, [obj(10)])]), player_index=3)
    session.connect()
    assert session.observe().frame == 7


def test_me_mine_and_frame_track_the_latest_observation():
    session = Session(LoopbackBackend([frame(4, [obj(10), obj(11)])]), player_index=3)
    session.connect()
    assert session.me is None and session.mine == () and session.frame == 0
    session.poll()
    assert session.me.name == "Player_1"
    assert {o.object_id for o in session.mine} == {10, 11}
    assert session.frame == 4


def test_wait_until_returns_the_first_matching_observation():
    script = [frame(n, [obj(10)], resources=100 * n) for n in range(1, 5)]
    session = Session(LoopbackBackend(script), player_index=3)
    session.connect()
    reached = session.wait_until(lambda o: o.player(3).resources >= 300, timeout=5.0, poll=0.0)
    assert reached.frame == 3


def test_wait_until_times_out_rather_than_returning_none():
    session = Session(LoopbackBackend([frame(1, [obj(10)])]), player_index=3)
    session.connect()
    with pytest.raises(TimeoutError):
        session.wait_until(lambda o: False, timeout=0.0, poll=0.0)


def test_wait_for_match_skips_the_shell_map_and_adopts_the_real_seat():
    """At the menu the local player *is* the observer, so a seat fixed before the match
    started was fixed on the wrong player."""
    menu = Observation(
        frame=500,
        local_player=2,
        players=(PlayerState(index=2, name="ReplayObserver", faction="Observer", resources=0),),
        objects=(obj(4, "ShellMapMD", "Civilian"),),
    )
    session = Session(LoopbackBackend([menu, menu, frame(1, [obj(10)])]), player_index=2)
    session.connect()

    started = session.wait_for_match(timeout=5.0, poll=0.0)
    assert started.frame == 1
    assert session.player_index == 3, "the seat should be re-read on arrival"


def test_scripted_game_drives_a_policy_end_to_end():
    """The M0 acceptance test: a policy consumes observations and emits real orders,
    every one of which round-tripped through the wire codec on the way in."""
    script = [frame(n, [obj(10), obj(11)], resources=500 * n) for n in range(1, 6)]
    backend = LoopbackBackend(script)
    session = Session(backend, player_index=3, apm_cap=0)

    with session:
        while (observation := session.step()) is not None:
            mine = observation.owned_by(3)
            if mine and not session.selection:
                session.select([o.object_id for o in mine])
            elif session.selection:
                session.move((observation.frame * 10.0, 500.0, 0.0))

    assert not backend.diagnostics, "no observation should have failed to decode"
    assert len(backend.sent) == 5
    assert backend.sent[0].order_type == OrderType.CREATE_SELECTED_GROUP
    assert all(o.order_type == OrderType.DO_MOVETO for o in backend.sent[1:])
    assert all(o.player_index == 3 for o in backend.sent)
