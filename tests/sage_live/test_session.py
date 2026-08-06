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
    ProductionItem,
    Session,
    ViewLocation,
)
from sage_live.api.session import MAX_SELECTION, IllegitimateOrder


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


class TickingClock:
    """A clock that advances every time it is read.

    Lets a timeout be reached in a bounded number of steps with `poll=0`, so the confirmation
    helpers are tested at full speed instead of waiting out real seconds.
    """

    def __init__(self, tick: float = 0.5) -> None:
        self.now = 0.0
        self.tick = tick

    def __call__(self) -> float:
        self.now += self.tick
        return self.now


def obj(
    object_id: int,
    template: str = "GondorFighter",
    side: str = "Men",
    position: tuple[float, float, float] | None = None,
) -> GameObject:
    return GameObject(
        object_id=object_id,
        template_name=template,
        template_side=side,
        position=position or (100.0 * object_id, 200.0, 61.0),
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


def test_a_selection_larger_than_the_buffer_is_split_across_orders():
    """One order cannot carry more ids than the command buffer has argument slots.

    The encoder refuses an oversized order outright rather than truncating it, so before this
    an army that outgrew the buffer was not selected at all - and the engine kept the previous
    selection, which the next order then acted on.
    """
    backend = LoopbackBackend()
    session = Session(backend, player_index=3)
    session.connect()

    ids = list(range(100, 100 + MAX_SELECTION + 5))
    sent = session.select(ids)

    assert sent == 2
    assert session.selection == tuple(ids)
    assert [o.order_type for o in backend.sent] == [OrderType.CREATE_SELECTED_GROUP] * 2
    # The first chunk replaces the selection and the rest extend it, which is what makes the
    # pieces add up to one selection rather than to the last chunk alone.
    assert backend.sent[0].arguments[0].value is True
    assert backend.sent[1].arguments[0].value is False
    assert len(backend.sent[0].arguments) - 1 == MAX_SELECTION
    assert len(backend.sent[1].arguments) - 1 == 5


def test_a_selection_that_fits_still_goes_as_one_order():
    backend = LoopbackBackend()
    session = Session(backend, player_index=3)
    session.connect()
    assert session.select(list(range(MAX_SELECTION))) == 1
    assert len(backend.sent) == 1


def test_a_split_selection_stops_at_the_first_chunk_that_does_not_go():
    """A cap that bites mid-selection leaves a partial selection, and says so by the count.

    Continuing would leave the engine holding neither the old selection nor the requested one,
    with nothing in the return value to tell the caller which.
    """
    clock = FakeClock()
    backend = LoopbackBackend()
    # The cap counts orders, not ids: two left, and the second select wants three.
    session = Session(backend, player_index=3, apm_cap=2, clock=clock)
    session.connect()

    session.select(list(range(MAX_SELECTION)))  # one order, leaving room for one more
    sent = session.select(list(range(500, 500 + MAX_SELECTION * 2)))

    assert sent == 1
    assert sent.throttled == 1
    assert len(backend.sent) == 2
    assert session.selection == tuple(range(500, 500 + MAX_SELECTION))


def test_duplicate_ids_do_not_consume_buffer_slots():
    backend = LoopbackBackend()
    session = Session(backend, player_index=3)
    session.connect()
    assert session.select([7] * (MAX_SELECTION + 10)) == 1
    assert session.selection == (7,)


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


def confirming(script) -> Session:
    """A session whose confirmations neither sleep nor wait for a real clock."""
    session = Session(LoopbackBackend(script), player_index=3, clock=TickingClock())
    session.connect()
    return session


def test_a_throttled_order_is_not_a_refused_one():
    """`send` returning 0 has two causes and only one of them means something is wrong."""
    session = Session(LoopbackBackend(), player_index=3, apm_cap=1, clock=FakeClock())
    session.connect()

    first = session.select([10])
    assert first == 1 and first.reason == ""

    second = session.select([11])
    assert second == 0
    assert second.throttled == 1 and second.refused == 0
    assert "APM cap" in second.reason


def test_an_order_the_backend_would_not_take_is_reported_as_refused():
    backend = LoopbackBackend()  # never connected, so it accepts nothing
    session = Session(backend, player_index=3)
    session.handshake = Handshake()  # connected as far as the session knows
    sent = session.select([10])
    assert sent == 0
    assert sent.refused == 1 and sent.throttled == 0
    assert "backend refused" in sent.reason


def test_confirm_spend_wants_the_balance_to_fall():
    """The oracle for a purchase: the order being taken says nothing, the gold does."""
    session = confirming([frame(1, [], resources=1000), frame(2, [], resources=650)])
    assert session.confirm_spend(lambda: session.select([10]), timeout=2.0) is True


def test_confirm_spend_is_false_when_logic_quietly_discarded_the_order():
    """The failure this exists for: accepted by the stream, discarded by logic, nothing said."""
    session = confirming([frame(n, [], resources=1000) for n in range(1, 6)])
    assert session.confirm_spend(lambda: session.select([10]), timeout=1.0) is False


def test_confirm_moved_ignores_a_unit_that_stayed_put():
    still = [obj(10, position=(100.0, 200.0, 61.0))]
    session = confirming([frame(1, still), frame(2, still), frame(3, still)])
    assert session.confirm_moved(lambda: session.select([10]), [10], timeout=1.0) is False


def test_confirm_moved_sees_a_unit_that_left_its_position():
    session = confirming(
        [
            frame(1, [obj(10, position=(100.0, 200.0, 61.0))]),
            frame(2, [obj(10, position=(400.0, 200.0, 61.0))]),
        ]
    )
    assert session.confirm_moved(lambda: session.select([10]), [10], timeout=2.0) is True


def test_confirm_appeared_finds_a_building_it_never_named():
    """`BuildVariations` means the ordered template never appears, so the test has to be what
    turned up rather than what it is called."""
    session = confirming(
        [
            frame(1, [obj(10)]),
            frame(2, [obj(10), obj(12, template="GondorWohnhaus01", position=(50.0, 60.0, 0.0))]),
        ]
    )
    appeared = session.confirm_appeared(
        lambda: session.select([10]), near=(55.0, 62.0, 0.0), timeout=2.0
    )
    assert appeared is True


def test_confirm_appeared_ignores_something_that_turned_up_elsewhere():
    session = confirming(
        [
            frame(1, [obj(10)]),
            frame(2, [obj(10), obj(12, position=(9000.0, 9000.0, 0.0))]),
            frame(3, [obj(10), obj(12, position=(9000.0, 9000.0, 0.0))]),
        ]
    )
    appeared = session.confirm_appeared(
        lambda: session.select([10]), near=(50.0, 60.0, 0.0), timeout=1.0
    )
    assert appeared is False


def test_a_scripted_session_is_alive_because_it_has_no_process_to_lose():
    session = Session(LoopbackBackend(), player_index=3)
    session.connect()
    assert session.alive


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


def test_a_session_without_godsight_censors_every_observation():
    """Applied in one place, so a policy cannot reach privileged state by using `step` instead
    of `poll`, or by reading `latest` directly."""
    enemy = GameObject(
        object_id=99,
        template_name="MordorOrcPit",
        template_side="Mordor",
        position=(0.0, 0.0, 0.0),
        angle=0.0,
        health=1.0,
        max_health=100.0,
        owner_index=4,
        production=(ProductionItem("unit", "MordorFighterHorde"),),
    )
    script = [
        Observation(
            frame=n,
            local_player=3,
            players=(
                PlayerState(index=3, name="me", faction="Men", resources=100),
                PlayerState(index=4, name="foe", faction="Mordor", resources=7777),
            ),
            objects=(enemy,),
        )
        for n in (1, 2)
    ]
    session = Session(LoopbackBackend(script), player_index=3, godsight=False)
    session.connect()

    polled = session.poll()
    assert polled.obj(99).production == ()
    assert polled.player(4).resources == 0
    assert polled.godsight is False
    assert session.latest.player(4).resources == 0, "the cached snapshot is censored too"

    stepped = session.step()
    assert stepped.obj(99).production == ()


def test_godsight_is_on_by_default():
    """Changing what a session reports is a decision, not something that happens by upgrade."""
    assert Session(LoopbackBackend()).godsight is True


def _barracks(object_id: int, queued: int) -> GameObject:
    return GameObject(
        object_id=object_id,
        template_name="GondorBarracks",
        template_side="Men",
        position=(0.0, 0.0, 0.0),
        angle=0.0,
        health=1.0,
        max_health=3000.0,
        owner_index=3,
        production=tuple(ProductionItem("unit", "GondorFighterHorde") for _ in range(queued)),
    )


def test_confirm_queued_watches_the_building_rather_than_the_gold():
    """The sound oracle for a recruit. Gold is contested - an enemy ability can steal it and a
    grant can hide a spend under a rise - but the queue belongs to the building the order
    named."""
    session = confirming([frame(1, [_barracks(7, 0)]), frame(2, [_barracks(7, 1)])])
    assert session.confirm_queued(lambda: session.select([7]), 7, timeout=2.0) is True


def test_confirm_queued_is_false_when_nothing_joined_the_queue():
    session = confirming([frame(n, [_barracks(7, 1)]) for n in range(1, 6)])
    assert session.confirm_queued(lambda: session.select([7]), 7, timeout=1.0) is False


def test_confirm_queued_measures_growth_not_emptiness():
    """A queue that was already working must still register the new item - a building can hold
    about twenty, so "is it busy" is not the question."""
    session = confirming([frame(1, [_barracks(7, 3)]), frame(2, [_barracks(7, 4)])])
    assert session.confirm_queued(lambda: session.select([7]), 7, timeout=2.0) is True


def spellbook(n: int, sciences) -> Observation:
    """One frame of a match where the only thing that moves is the spellbook."""
    return Observation(
        frame=n,
        local_player=3,
        players=(
            PlayerState(
                index=3,
                name="Player_1",
                faction="Men",
                resources=1000,
                power_points=11,
                sciences=frozenset(sciences),
            ),
        ),
    )


def test_confirm_power_watches_the_science_rather_than_the_points():
    """The direct signal. Points are the `confirm_spend` trap in a second currency - they rise
    on their own clock, so this frame pair (a purchase *and* a tick of income) is exactly the
    case a balance test calls a failure."""
    session = confirming([spellbook(1, {16}), spellbook(2, {16, 36})])
    assert session.confirm_power(lambda: session.select([10]), 36, timeout=2.0) is True


def test_confirm_power_is_false_when_logic_discarded_the_purchase():
    session = confirming([spellbook(n, {16}) for n in range(1, 6)])
    assert session.confirm_power(lambda: session.select([10]), 36, timeout=1.0) is False


def test_confirm_power_does_not_accept_a_different_power_landing():
    """Two powers on one row cost the same, so "a science appeared" is not the question - the
    one that was ordered is."""
    session = confirming([spellbook(1, {16}), spellbook(2, {16, 37})])
    assert session.confirm_power(lambda: session.select([10]), 36, timeout=1.0) is False


def test_confirm_power_is_false_when_the_order_never_went():
    """An order held back by the APM cap was never discarded by logic - it was never sent. The
    science arrives in the very next frame here, and this must still not claim the purchase:
    something else buying it (a scripted grant) is not this order having worked."""
    script = [spellbook(1, {16}), spellbook(2, {16, 36})]
    session = Session(LoopbackBackend(script), player_index=3, apm_cap=1, clock=TickingClock())
    session.connect()
    assert session.purchase_power(36)  # spends the cap's one allowance
    assert session.confirm_power(lambda: session.purchase_power(36), 36, timeout=1.0) is False


def test_cast_dispatches_on_the_form_the_button_declared():
    """The three constructors send three different order types, and the button decides which.
    A power sent through the wrong one is accepted, charged nothing and does nothing."""
    backend = LoopbackBackend()
    session = Session(backend, player_index=3)
    session.connect()

    session.cast(551, "location", (100.0, 200.0, 0.0))
    assert backend.sent[-1].order_type == OrderType.DO_SPECIAL_POWER_AT_LOCATION

    session.cast(551, "self")
    assert backend.sent[-1].order_type == OrderType.DO_SPECIAL_POWER

    session.cast(551, "object", (100.0, 200.0, 0.0), target_id=42)
    assert backend.sent[-1].order_type == OrderType.DO_SPECIAL_POWER_AT_OBJECT


def test_casting_a_passive_power_raises_rather_than_sending():
    """Its whole effect landed when it was bought and the control bar shows no button. Sending
    one anyway would be indistinguishable from a cast that failed."""
    session = Session(LoopbackBackend(), player_index=3)
    session.connect()
    with pytest.raises(IllegitimateOrder, match="fired when it was bought"):
        session.cast(551, "passive")


def test_a_ground_cast_without_a_position_is_refused():
    """The position is the target. Defaulting it to the origin would send a well-formed order
    at the corner of the map."""
    session = Session(LoopbackBackend(), player_index=3)
    session.connect()
    with pytest.raises(ValueError, match="needs a position"):
        session.cast(551, "location")


class CameraBackend(LoopbackBackend):
    """A scripted backend that also carries a camera, as a bridge-backed one does."""

    def __init__(self, view: ViewLocation | None = None) -> None:
        super().__init__()
        self.view = ViewLocation() if view is None else view
        self.applied: list[ViewLocation] = []

    def capture_camera(self) -> ViewLocation | None:
        return self.view

    def set_camera(self, location: ViewLocation) -> bool:
        self.applied.append(location)
        self.view = location
        return True


def test_a_session_whose_backend_has_no_camera_says_so():
    """None is "this backend cannot say", never a default placement - a scripted or recorded
    game has no camera at all, and inventing one would be a placement nobody asked for."""
    session = Session(LoopbackBackend(), player_index=3)
    session.connect()
    assert session.camera() is None
    assert session.set_camera(ViewLocation()) is False
    assert session.look_at((100.0, 200.0, 0.0)) is False


def test_look_at_re_aims_the_camera_and_keeps_everything_else():
    """The zoom, facing and tilt are the player's. A "look over there" that also reset them
    would fight whoever is at the keyboard and look nothing like the game it is filming."""
    held = ViewLocation((10.0, 20.0, 0.0), angle=0.75, pitch=1.25, zoom=1.5, extra=2.5)
    backend = CameraBackend(held)
    session = Session(backend, player_index=3)
    session.connect()

    assert session.look_at((1200.0, 880.0, 0.0))
    placed = backend.applied[-1]
    assert placed.position == (1200.0, 880.0, 0.0)
    assert (placed.angle, placed.pitch, placed.zoom, placed.extra) == (0.75, 1.25, 1.5, 2.5)


def test_look_at_overrides_only_what_it_was_given():
    backend = CameraBackend(ViewLocation((0.0, 0.0, 0.0), angle=0.75, pitch=1.25, zoom=1.5))
    session = Session(backend, player_index=3)
    session.connect()

    assert session.look_at((5.0, 6.0, 7.0), zoom=0.5)
    placed = backend.applied[-1]
    assert placed.zoom == 0.5
    assert (placed.angle, placed.pitch) == (0.75, 1.25)


def test_look_at_refuses_when_the_camera_cannot_be_read():
    """There is nothing to keep, and a placement with invented scalars is worse than none."""
    backend = CameraBackend()
    backend.view = None
    session = Session(backend, player_index=3)
    session.connect()
    assert session.look_at((5.0, 6.0, 7.0)) is False
    assert backend.applied == []


class MovingCameraBackend(CameraBackend):
    """A backend that can re-aim without a whole placement, as the live bridge can."""

    def __init__(self, view: ViewLocation | None = None) -> None:
        super().__init__(view)
        self.moved: list[tuple[float, float, float]] = []

    def move_camera(self, position) -> bool:
        self.moved.append(position)
        return True


def test_look_at_re_aims_without_a_placement_where_the_backend_can():
    """**Keeping the zoom means not writing it, not writing it back.**

    `View::setLocation` writes all four scalars every call, and the zoom it writes is not the
    zoom it reports - they are different fields. Measured live, handing back a location captured
    a moment earlier still moved the zoom from 1.281116 to 1.234136 and the client restored it
    over the next 0.6s; asking for the reported value was refused identically. At one placement
    per policy cycle that is a permanent zoom-in-and-snap, so a re-aim must not go near it.
    """
    backend = MovingCameraBackend(ViewLocation((0.0, 0.0, 0.0), zoom=1.281116))
    session = Session(backend, player_index=3)
    session.connect()

    assert session.look_at((1200.0, 880.0, 150.0))
    assert backend.moved == [(1200.0, 880.0, 150.0)]
    assert backend.applied == []  # setLocation was never called, so no zoom was written


def test_look_at_takes_the_long_way_round_when_a_scalar_is_overridden():
    """Asking for a zoom is asking for the write that the position-only path exists to avoid,
    so it goes through the whole placement - deliberately, and only when told to."""
    backend = MovingCameraBackend(ViewLocation((0.0, 0.0, 0.0), angle=0.75, zoom=1.5))
    session = Session(backend, player_index=3)
    session.connect()

    assert session.look_at((5.0, 6.0, 7.0), zoom=0.5)
    assert backend.moved == []
    assert backend.applied[-1].zoom == 0.5
    assert backend.applied[-1].angle == 0.75


def test_a_re_aim_does_not_read_the_camera_first():
    """The read was only ever there to have scalars to hand back. Dropping it also drops a
    bridge round-trip per placement, which is what lets a pan run far faster than a policy."""
    backend = MovingCameraBackend()
    backend.view = None  # unreadable, and it must not matter
    session = Session(backend, player_index=3)
    session.connect()
    assert session.look_at((5.0, 6.0, 7.0))
    assert backend.moved == [(5.0, 6.0, 7.0)]


def test_moving_the_camera_spends_no_apm():
    """It is not an order: nothing enters the message stream and no logic reads the camera,
    so throttling it would only stop a policy from framing what it is doing."""
    backend = CameraBackend()
    session = Session(backend, player_index=3, apm_cap=1)
    session.connect()
    for _ in range(5):
        assert session.look_at((1.0, 2.0, 3.0))
    assert session.throttled == 0
