"""Id extraction, run-collapsing, label parsing and alignment (Phase 2 tooling)."""

from pathlib import Path

from sage_replay import (
    IdEvent,
    LabelAction,
    align,
    arg_equals,
    collapse_runs,
    id_events,
    order_id_summaries,
    parse_labels,
    parse_replay_from_path,
)

FIXTURES = Path(__file__).parent / "fixtures"
REPLAY_PATH = FIXTURES / "4.8.2 Angmar vs Isengard (Dyastro) epic.BfME2Replay"


def test_order_id_summaries_ranks_integer_orders():
    replay = parse_replay_from_path(REPLAY_PATH)
    summaries = order_id_summaries(replay)
    by_order = {s.order_type: s for s in summaries}

    # 0x415 is the recruit-like order (ObjectId, Integer); it carries a compact id set.
    assert 0x415 in by_order
    summary = by_order[0x415]
    assert summary.total > 0
    assert summary.distinct_ids >= len(summary.top)  # top is a capped view of the distinct set
    assert len(summary.top) <= 10
    # Orders without any Integer argument (pure selection/move) never appear.
    assert 0x424 not in by_order  # ScreenRectangle only
    assert 0x42F not in by_order  # Position only


def test_order_id_summaries_respects_player_filter():
    replay = parse_replay_from_path(REPLAY_PATH)
    both = {s.order_type: s.total for s in order_id_summaries(replay)}
    p0 = {s.order_type: s.total for s in order_id_summaries(replay, slot_index=0)}
    p1 = {s.order_type: s.total for s in order_id_summaries(replay, slot_index=1)}
    # Per-player totals partition the combined total for a shared order type.
    assert p0.get(0x415, 0) + p1.get(0x415, 0) == both[0x415]


def test_id_events_are_timecode_ordered():
    replay = parse_replay_from_path(REPLAY_PATH)
    events = id_events(replay, 0x415, slot_index=0)
    assert events
    assert [e.timecode for e in events] == sorted(e.timecode for e in events)
    assert all(e.slot_index == 0 for e in events)


def test_where_predicate_splits_order_modes():
    # 0x417 carries a leading Boolean that discriminates two id spaces (units vs the
    # building-local hero slot indices). arg_equals(0, ...) selects one mode.
    replay = parse_replay_from_path(REPLAY_PATH)
    all_events = id_events(replay, 0x415)
    # 0x415's arg 0 is an ObjectId; filtering on a value it never holds yields nothing,
    # and filtering trivially-true on every event returns the whole set.
    assert id_events(replay, 0x415, where=lambda c: True) == all_events
    assert id_events(replay, 0x415, where=arg_equals(0, -999999)) == []


def test_arg_equals_out_of_range_is_no_match():
    replay = parse_replay_from_path(REPLAY_PATH)
    # No 0x415 order has a 99th argument, so the predicate excludes everything.
    assert id_events(replay, 0x415, where=arg_equals(99, 0)) == []


def test_collapse_runs():
    events = [
        IdEvent(10, 603, 0),
        IdEvent(11, 603, 0),
        IdEvent(12, 603, 0),
        IdEvent(20, 606, 0),
        IdEvent(30, 603, 0),
    ]
    runs = collapse_runs(events)
    assert [(r.id, r.count) for r in runs] == [(603, 3), (606, 1), (603, 1)]
    assert runs[0].start_timecode == 10


def test_parse_labels_metadata_and_counts():
    labels = parse_labels(
        "# a comment\n"
        "faction: Angmar\n"
        "mod: Edain 4.8.2\n"
        "3x Thrall Master\n"
        "2 Dark Ranger   # trailing comment\n"
        "Gorkil\n"
    )
    assert labels.metadata == {"faction": "Angmar", "mod": "Edain 4.8.2"}
    assert labels.actions == [
        LabelAction(3, "Thrall Master"),
        LabelAction(2, "Dark Ranger"),
        LabelAction(1, "Gorkil"),
    ]


def test_parse_labels_colon_after_first_action_is_not_metadata():
    labels = parse_labels("2x Soldier\nnote: this is an action-ish line\n")
    assert labels.metadata == {}
    assert [a.name for a in labels.actions] == ["Soldier", "note: this is an action-ish line"]


def test_align_matches_runs_to_labels():
    runs = collapse_runs(
        [IdEvent(1, 605, 0), IdEvent(2, 603, 0), IdEvent(3, 603, 0), IdEvent(9, 606, 0)]
    )
    actions = [LabelAction(1, "Keep"), LabelAction(2, "Worker"), LabelAction(1, "Farm")]
    rows, warnings = align(runs, actions)

    # Three runs (the two 603s collapse) line up 1:1 with three labels, cleanly.
    assert [(r.id, r.name, r.ok) for r in rows] == [
        (605, "Keep", True),
        (603, "Worker", True),
        (606, "Farm", True),
    ]
    assert warnings == []


def test_align_flags_length_mismatch():
    runs = collapse_runs([IdEvent(1, 605, 0), IdEvent(2, 603, 0), IdEvent(3, 606, 0)])
    rows, warnings = align(runs, [LabelAction(1, "Keep")])
    # Extra runs beyond the labels are flagged, not silently dropped.
    assert any("differ in length" in w for w in warnings)
    assert any("unmatched id run" in w for w in warnings)
    assert [r.name for r in rows] == ["Keep"]


def test_align_flags_count_mismatch():
    runs = collapse_runs([IdEvent(1, 421, 0), IdEvent(2, 421, 0)])
    rows, warnings = align(runs, [LabelAction(3, "Archer")])
    assert rows[0].id == 421 and not rows[0].ok
    assert any("count mismatch" in w for w in warnings)
