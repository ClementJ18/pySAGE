"""Reading the annotation records a patched recording client writes, and folding them into the
aggregation.

No corpus fixture carries them yet, so the records are synthesized onto a real fixture and
round-tripped through the real serializer - which is what makes them the same bytes the patch
writes rather than a convenient in-memory object. That the layout here matches the one the cave
lays down is asserted on the patch's side, in `tests/sage_patch/test_replay_annotations.py`.
"""

from pathlib import Path

import pytest

from sage_replay import parse_replay, parse_replay_from_path, serialize_replay
from sage_replay.annotations import (
    MAX_PLAYER_COUNT,
    SCHEMA_VERSION,
    SCORE_FIELDS,
    manifest,
    player_scores,
)
from sage_replay.replay import (
    Bfme2OrderType,
    Order,
    OrderArgument,
    OrderArgumentType,
    ReplayChunk,
)

FIXTURES = Path(__file__).parent / "fixtures"
DECIDED_FIXTURE = "1v1 Misty vs Mordor (Elendil wins).BfME2Replay"

#: Chunk player numbers are the slot index plus this, the same offset every engine order
#: carries - which is why the patch writes `Player::m_playerIndex` into the field.
FIRST_SLOT_NUMBER = 3

WRITER_ID = 0x53414745
KIND_PLAYER_SCORE = 1


def _chunk(timecode: int, order_type: int, number: int, values: list[int]) -> ReplayChunk:
    return ReplayChunk(
        timecode=timecode,
        order_type=order_type,
        number=number,
        order=Order(
            player_index=number - 1,
            order_type=order_type,
            arguments=[OrderArgument(OrderArgumentType.Integer, v) for v in values],
        ),
    )


def score_values(schema: int = SCHEMA_VERSION, **overrides: int) -> list[int]:
    """A score record's Integers: the schema version, then the `SCORE_FIELDS` that version
    defines, in order. Scalars default to 0 and arrays to 20 zeroes; `units_destroyed=[...]`
    sets an array outright and `units_built=7` a scalar.

    `schema=1` builds the record the first shipped build wrote - the v2 tail simply absent,
    which is what a replay recorded before this schema really looks like."""
    values = [schema]
    for name, width, since in SCORE_FIELDS:
        if since > schema:
            overrides.pop(name, None)
            continue
        given = overrides.pop(name, None)
        if width == 1:
            values.append(int(given or 0))
        else:
            array = list(given or [])
            values.extend(array + [0] * (MAX_PLAYER_COUNT - len(array)))
    assert not overrides, f"unknown score fields: {sorted(overrides)}"
    return values


def with_annotations(scores: dict[int, list[int]], *, declared: bool = True):
    """The fixture re-recorded as a patched client would have written it: the manifest and one
    score record per player, at the closing frame, after the `0x1D` end-of-recording marker -
    where the patch puts them, because `replay-outcome` owns the call before it."""
    replay = parse_replay_from_path(FIXTURES / DECIDED_FIXTURE)
    end = replay.chunks[-1].timecode
    recorder = replay.header.local_player_index + FIRST_SLOT_NUMBER
    appended = []
    if declared:
        appended.append(
            _chunk(
                end,
                Bfme2OrderType.AnnotationManifest,
                recorder,
                [1, KIND_PLAYER_SCORE, WRITER_ID],
            )
        )
    appended.extend(
        _chunk(end, Bfme2OrderType.PlayerScore, slot + FIRST_SLOT_NUMBER, values)
        for slot, values in sorted(scores.items())
    )
    replay.chunks.extend(appended)
    return parse_replay(serialize_replay(replay))


@pytest.fixture(scope="module")
def unpatched():
    return parse_replay_from_path(FIXTURES / DECIDED_FIXTURE)


def test_an_unpatched_replay_carries_nothing(unpatched):
    """The whole existing corpus. Both readers answer emptily rather than raising."""
    assert manifest(unpatched) is None
    assert player_scores(unpatched) == {}


def test_the_records_survive_a_serializer_round_trip():
    """The bytes are the contract: what is written is read back identically, and the parse
    still runs to end-of-file with the header's timecode count intact."""
    replay = with_annotations({0: score_values(units_built=41)})
    assert replay.chunks[-1].order_type == Bfme2OrderType.PlayerScore
    assert player_scores(replay)[0].units_built == 41


def test_the_manifest_says_what_the_build_writes():
    declared = manifest(with_annotations({}))
    assert declared is not None
    assert declared.schema_version == 1
    assert declared.writer_id == WRITER_ID
    assert declared.writes_player_scores


def test_a_manifest_that_declares_no_scores_is_not_the_same_as_no_manifest():
    """The distinction the manifest exists for: 'this build records no scores' against 'this
    game scored nothing'."""
    replay = with_annotations({})
    replay.chunks[-1].order.arguments[1] = OrderArgument(OrderArgumentType.Integer, 0)
    declared = manifest(replay)
    assert declared is not None
    assert not declared.writes_player_scores
    assert manifest(with_annotations({}, declared=False)) is None


def test_every_field_lands_where_the_schema_says():
    replay = with_annotations(
        {
            0: score_values(
                money_earned=9100,
                money_spent=8700,
                units_alive=12,
                structures_alive=9,
                end_frame=0,
                units_built=41,
                units_lost=29,
                structures_built=14,
                structures_lost=2,
                units_destroyed=[0, 0, 0, 0, 33],
                structures_destroyed=[0, 0, 0, 0, 6],
            )
        }
    )
    score = player_scores(replay)[0]
    assert (score.money_earned, score.money_spent) == (9100, 8700)
    assert (score.units_built, score.units_lost) == (41, 29)
    assert (score.structures_built, score.structures_lost) == (14, 2)
    assert (score.units_alive, score.structures_alive) == (12, 9)
    assert score.total_units_destroyed == 33
    assert score.total_structures_destroyed == 6
    assert len(score.units_destroyed) == MAX_PLAYER_COUNT


def test_the_destruction_arrays_map_onto_slots():
    """The arrays are indexed by the victim's engine player number; slot 1 of this fixture is
    number 4, so an entry there is what the other player lost."""
    replay = with_annotations(
        {0: score_values(units_destroyed=[0, 0, 0, 0, 33], structures_destroyed=[0, 0, 0, 0, 6])}
    )
    assert player_scores(replay)[0].destroyed_by_slot(replay) == {1: (33, 6)}


def test_entries_outside_the_occupied_slots_are_dropped():
    """The neutral player and unfilled positions have numbers no metadata slot answers to;
    those are dropped rather than attributed to whoever happens to be nearby."""
    destroyed = [7] + [0] * (MAX_PLAYER_COUNT - 1)  # number 0: not a lobby slot here
    replay = with_annotations({0: score_values(units_destroyed=destroyed)})
    assert player_scores(replay)[0].destroyed_by_slot(replay) == {}


def test_a_record_short_of_the_schema_is_skipped_not_guessed():
    """Short of the *v1 prefix*, which every schema shares - that is malformed, not old."""
    replay = with_annotations({0: score_values(schema=1)})
    del replay.chunks[-1].order.arguments[-1]
    assert player_scores(parse_replay(serialize_replay(replay))) == {}


def test_a_longer_record_still_reads_for_the_part_the_schema_knows():
    """Forward compatibility: a later schema appends arguments, and this reader keeps working
    on the prefix it understands."""
    replay = with_annotations({0: score_values(units_built=41)})
    replay.chunks[-1].order.arguments.append(OrderArgument(OrderArgumentType.Integer, 999))
    score = player_scores(parse_replay(serialize_replay(replay)))[0]
    assert score.units_built == 41
    assert score.schema_version == SCHEMA_VERSION


def test_a_v1_record_reads_with_the_later_fields_absent():
    """Backward compatibility, and the reason the v2 fields are `| None`: the corpus recorded
    before this schema must keep reading, and must not report a zero it never carried."""
    replay = with_annotations({0: score_values(schema=1, units_built=41, money_earned=900)})
    score = player_scores(parse_replay(serialize_replay(replay)))[0]
    assert (score.schema_version, score.units_built, score.money_earned) == (1, 41, 900)
    assert score.resources is None
    assert score.faction_name_key is None
    assert score.command_points_used is None
    assert score.command_point_ceiling is None


def test_the_v2_tail_lands_where_the_schema_says():
    replay = with_annotations(
        {
            0: score_values(
                faction_name_key=1690,
                resources=5840,
                power_points=3,
                power_points_total=7,
                command_points_used=120,
                command_points_cap=500,
                command_points_bonus=250,
                command_points_hard_cap=1500,
            )
        }
    )
    score = player_scores(parse_replay(serialize_replay(replay)))[0]
    assert score.faction_name_key == 1690
    assert score.resources == 5840
    assert (score.power_points, score.power_points_total) == (3, 7)
    assert score.command_points_used == 120
    # min(500 + 250, 1500) - the engine's own combination, minus the filtered term no reader
    # outside the running game can evaluate.
    assert score.command_point_ceiling == 750


def test_the_command_point_ceiling_is_clamped_by_the_hard_cap():
    """A bonus past the hard cap buys nothing, which is the whole point of recording all four
    fields rather than a sum."""
    replay = with_annotations(
        {
            0: score_values(
                command_points_cap=500, command_points_bonus=6000, command_points_hard_cap=1500
            )
        }
    )
    assert player_scores(parse_replay(serialize_replay(replay)))[0].command_point_ceiling == 1500
