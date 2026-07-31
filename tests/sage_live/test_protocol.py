"""Codec conformance: every message type survives a round trip, and malformed input
produces diagnostics rather than exceptions."""

from __future__ import annotations

import logging

import pytest

from sage_live.observation import GameObject, Observation, PlayerState, ProductionItem
from sage_live.protocol import (
    FRAME_HEADER,
    FRAME_MAGIC,
    OBSERVATION_STRUCT_VERSION,
    PROTOCOL_VERSION,
    Diagnostic,
    DiagnosticLog,
    Handshake,
    MessageType,
    decode_frames,
    decode_handshake,
    decode_observation,
    encode_frame,
    encode_handshake,
    encode_observation,
)


def make_observation() -> Observation:
    return Observation(
        frame=8688,
        local_player=3,
        players=(
            PlayerState(
                index=3,
                name="Player_1",
                faction="Men",
                resources=2870,
                resources_collected=5020,
                power_points=4,
                command_points=(12, 80),
                upgrades=frozenset({"Upgrade_GondorForgedBlades", "Upgrade_GondorHeavyArmor"}),
            ),
            PlayerState(index=2, name="PlyrCreeps", faction="Civilian", resources=1000),
        ),
        objects=(
            GameObject(
                object_id=133,
                template_name="GondorFighter",
                template_side="Men",
                position=(2153.35, 3443.12, 61.02),
                angle=0.849,
                health=237.9 / 255.0,
                max_health=255.0,
                owner_index=3,
                parent_id=132,
            ),
            GameObject(
                object_id=124,
                template_name="MoriarGoblinLair",
                template_side="Neutral",
                position=(1422.1, 3095.6, 88.8),
                angle=0.0,
                health=1.0,
                max_health=2000.0,
            ),
        ),
        fogged=True,
    )


def test_frame_round_trip():
    payload = b"\x01\x02\x03\x04"
    frames, tail, diags = decode_frames(encode_frame(MessageType.CONTROL, payload))
    assert not diags and not tail
    assert len(frames) == 1
    assert frames[0].message_type == MessageType.CONTROL
    assert frames[0].payload == payload


def test_frame_header_carries_magic_type_and_payload_length():
    wire = encode_frame(MessageType.EVENT, b"abcd")
    magic, message_type, length = FRAME_HEADER.unpack_from(wire, 0)
    assert magic == FRAME_MAGIC
    assert message_type == MessageType.EVENT
    assert length == 4


def test_several_frames_in_one_buffer():
    wire = b"".join(encode_frame(t, bytes([i] * i)) for i, t in enumerate(MessageType, start=1))
    frames, tail, diags = decode_frames(wire)
    assert not diags and not tail
    assert [f.message_type for f in frames] == list(MessageType)


def test_partial_frame_is_kept_as_tail():
    wire = encode_frame(MessageType.OBSERVATION, b"0123456789")
    frames, tail, diags = decode_frames(wire[:-3])
    assert frames == [] and not diags
    assert tail == wire[:-3]
    # feeding the remainder completes it
    frames, tail, diags = decode_frames(tail + wire[-3:])
    assert len(frames) == 1 and not tail and not diags


def test_empty_payload_round_trips():
    frames, tail, diags = decode_frames(encode_frame(MessageType.CONTROL, b""))
    assert len(frames) == 1 and frames[0].payload == b"" and not tail and not diags


def test_garbage_before_a_frame_resynchronises():
    good = encode_frame(MessageType.CONTROL, b"ok")
    frames, tail, diags = decode_frames(b"\xff\xff\xff\xff\x00\x00" + good)
    assert diags, "the garbage should be reported"
    assert any(f.payload == b"ok" for f in frames), "decoding should resynchronise"


def test_implausible_length_resynchronises_to_the_next_frame():
    bad = FRAME_HEADER.pack(FRAME_MAGIC, MessageType.CONTROL, 0xFFFFFFFF)
    good = encode_frame(MessageType.CONTROL, b"ok")
    frames, tail, diags = decode_frames(bad + good)
    assert diags and "implausible" in diags[0].message
    assert any(f.payload == b"ok" for f in frames)


def test_handshake_round_trip():
    hs = Handshake(
        protocol_version=PROTOCOL_VERSION,
        engine_build="RotWK 2.01",
        data_checksum="edain-4.7",
        fog_of_war=True,
        apm_cap=300,
    )
    got, diags = decode_handshake(encode_handshake(hs))
    assert not diags
    assert got == hs


def test_truncated_handshake_is_a_diagnostic_not_an_exception():
    got, diags = decode_handshake(encode_handshake(Handshake(engine_build="x"))[:3])
    assert got is None
    assert diags and "truncated" in diags[0].message


def test_observation_round_trip_preserves_every_field():
    obs = make_observation()
    got, diags = decode_observation(encode_observation(obs))
    assert not diags
    assert got is not None
    assert got.frame == obs.frame
    assert got.local_player == obs.local_player
    assert got.fogged == obs.fogged
    assert got.players == obs.players
    # floats survive as float32, so compare with tolerance
    assert len(got.objects) == len(obs.objects)
    for a, b in zip(got.objects, obs.objects, strict=True):
        assert a.object_id == b.object_id
        assert a.template_name == b.template_name
        assert a.template_side == b.template_side
        assert a.owner_index == b.owner_index
        assert a.parent_id == b.parent_id
        assert a.position == pytest.approx(b.position, rel=1e-6)
        assert a.health == pytest.approx(b.health, rel=1e-6)
        assert a.max_health == pytest.approx(b.max_health, rel=1e-6)


def test_empty_observation_round_trips():
    got, diags = decode_observation(encode_observation(Observation(frame=0, local_player=0)))
    assert not diags
    assert got is not None and got.players == () and got.objects == ()


def test_none_owner_and_parent_survive_as_none():
    obs = Observation(
        frame=1,
        local_player=0,
        objects=(
            GameObject(
                object_id=7,
                template_name="FarmTemplate",
                template_side="Neutral",
                position=(1.0, 2.0, 3.0),
                angle=0.0,
                health=1.0,
                max_health=500.0,
            ),
        ),
    )
    got, _ = decode_observation(encode_observation(obs))
    assert got is not None
    assert got.objects[0].owner_index is None
    assert got.objects[0].parent_id is None


def test_unknown_struct_version_is_refused():
    payload = bytearray(encode_observation(Observation(frame=1, local_player=0)))
    payload[0] = OBSERVATION_STRUCT_VERSION + 7
    got, diags = decode_observation(bytes(payload))
    assert got is None
    assert diags and "struct version" in diags[0].message


def test_truncated_observation_is_a_diagnostic():
    wire = encode_observation(make_observation())
    got, diags = decode_observation(wire[: len(wire) // 2])
    assert got is None
    assert diags


@pytest.mark.parametrize("cut", [1, 5, 11, 23, 47])
def test_no_truncation_ever_raises(cut):
    wire = encode_observation(make_observation())
    obs, diags = decode_observation(wire[:cut])
    assert obs is None or diags == []


def test_the_diagnostic_log_is_bounded():
    """A backend appends per observation, and a game that has gone away appends the same
    sentence every cycle. Unbounded, an hour-long run keeps every copy."""
    log = DiagnosticLog(limit=4)
    log.extend(Diagnostic(f"problem {i}") for i in range(100))
    assert len(log) == 4
    assert log.seen == 100
    assert log[-1].message == "problem 99", "the newest are what a reader wants"


def test_draining_reports_each_problem_once():
    log = DiagnosticLog()
    log.append(Diagnostic("first"))
    assert [d.message for d in log.drain()] == ["first"]
    assert list(log) == []
    log.append(Diagnostic("second"))
    assert [d.message for d in log.drain()] == ["second"]
    assert log.seen == 2, "draining reports what is held, not what has happened"


def test_every_diagnostic_reaches_the_logger(caplog):
    """A diagnostic nobody reads is not a diagnostic - and a library must not decide to print,
    so it logs and the application chooses."""
    with caplog.at_level(logging.WARNING, logger="sage_live"):
        DiagnosticLog().append(Diagnostic("the object table is unreadable", offset=8))
    assert "the object table is unreadable" in caplog.text


def test_object_scoped_upgrades_survive_the_round_trip():
    """Struct version 1 dropped these silently. `LoopbackBackend` round-trips every
    observation through this codec, so a policy tested against it saw an upgraded battalion as
    a fresh one - and that set is the *only* thing distinguishing the two."""
    obs = Observation(
        frame=1,
        local_player=0,
        objects=(
            GameObject(
                object_id=5,
                template_name="GondorFighterHorde",
                template_side="Men",
                position=(1.0, 2.0, 3.0),
                angle=0.0,
                health=1.0,
                max_health=400.0,
                upgrades=frozenset({"Upgrade_GondorHeavyArmor", "Upgrade_ObjectLevel2"}),
            ),
        ),
    )
    got, diags = decode_observation(encode_observation(obs))
    assert diags == []
    assert got is not None
    assert got.objects[0].upgrades == obs.objects[0].upgrades
    assert got.objects[0].veterancy == 2


def test_player_upgrades_in_progress_survive_the_round_trip():
    obs = Observation(
        frame=1,
        local_player=0,
        players=(
            PlayerState(
                index=0,
                name="Player_1",
                faction="Men",
                resources=100,
                upgrades=frozenset({"Upgrade_A"}),
                upgrades_in_progress=frozenset({"Upgrade_B"}),
            ),
        ),
    )
    got, _ = decode_observation(encode_observation(obs))
    assert got is not None
    assert got.players[0].upgrades_in_progress == frozenset({"Upgrade_B"})
    assert got.players[0].researching("upgrade_b")


def test_a_production_queue_survives_the_round_trip():
    obs = Observation(
        frame=1,
        local_player=0,
        objects=(
            GameObject(
                object_id=7,
                template_name="GondorBarracks",
                template_side="Men",
                position=(0.0, 0.0, 0.0),
                angle=0.0,
                health=1.0,
                max_health=3000.0,
                production=(
                    ProductionItem("unit", "GondorFighterHorde"),
                    ProductionItem("upgrade", "Upgrade_GondorHeavyArmor"),
                ),
            ),
        ),
    )
    got, _ = decode_observation(encode_observation(obs))
    assert got is not None
    assert got.objects[0].producing
    assert got.objects[0].production == obs.objects[0].production
