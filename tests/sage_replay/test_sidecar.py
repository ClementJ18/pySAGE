"""The ladder-metadata sidecar as the aggregate's outcome source: a `<replay>.json` beside a
replay names the winning team, which `sidecar_outcomes` maps onto the replay's human slots by
their lobby team - preferred over the concession heuristic, but only when the sidecar plainly
matches the replay."""

import json
from datetime import UTC, datetime
from pathlib import Path

from sage_replay.replay import (
    ReplayFile,
    ReplayGameType,
    ReplayHeader,
    ReplayMetadata,
    ReplaySlot,
    ReplaySlotType,
    ReplayTimestamp,
)
from sage_replay.sidecar import (
    build_sidecar_stub,
    ensure_sidecars,
    sidecar_has_winner,
    sidecar_outcomes,
    sidecar_path,
)


def _replay(slots: list[ReplaySlot]) -> ReplayFile:
    header = ReplayHeader(
        game_type=ReplayGameType.Bfme2,
        start_time=datetime(2026, 1, 1, tzinfo=UTC),
        end_time=datetime(2026, 1, 1, 0, 1, tzinfo=UTC),
        num_timecodes=60,
        filename="synthetic",
        timestamp=ReplayTimestamp(*([0] * 8)),
        version="",
        build_date="",
        metadata=ReplayMetadata(slots=slots),
        local_player_index=-1,
    )
    # `sidecar_outcomes` reads only the slot metadata, so the order stream can be empty.
    return ReplayFile(header=header, chunks=[])


def _human(name: str, *, team: int, faction: int = 0) -> ReplaySlot:
    return ReplaySlot(slot_type=ReplaySlotType.Human, human_name=name, faction=faction, team=team)


def _observer(name: str) -> ReplaySlot:
    # An observer slot: a named human with the observer faction sentinel and no team.
    return ReplaySlot(
        slot_type=ReplaySlotType.Human,
        human_name=name,
        faction=ReplaySlot.OBSERVER_FACTION,
        team=-1,
    )


def _write_sidecar(tmp_path: Path, players: list[dict], **extra) -> Path:
    """A replay file at tmp_path with a `<replay>.json` sidecar carrying `players` (each a
    `{Team, IsWinner, ...}` dict). Returns the replay path `sidecar_outcomes` is called with."""
    replay_path = tmp_path / "game.BfME2Replay"
    replay_path.write_bytes(b"")  # the sidecar is read by name; the replay bytes are unused here
    data = {"Players": players, **extra}
    replay_path.with_name(replay_path.name + ".json").write_text(json.dumps(data), encoding="utf-8")
    return replay_path


def _player(team: int, winner: bool, **extra) -> dict:
    return {"Team": team, "IsWinner": winner, "IsObserver": False, **extra}


def test_sidecar_maps_winning_team_onto_human_slots(tmp_path):
    replay = _replay([_human("Winner", team=1), _human("Loser", team=0)])
    path = _write_sidecar(tmp_path, [_player(0, False), _player(1, True)])
    assert sidecar_outcomes(replay, path) == {"Winner": "won", "Loser": "lost"}


def test_sidecar_maps_by_team_not_faction(tmp_path):
    # A lobby Random slot records faction -1 in the replay but still carries a team, so the
    # sidecar places it by team all the same - the whole point of a team-level mapping.
    replay = _replay(
        [
            _human("A", team=1, faction=9),
            _human("B", team=0, faction=3),
            _human("Random", team=1, faction=-1),
            _human("C", team=0, faction=11),
        ]
    )
    path = _write_sidecar(
        tmp_path, [_player(1, True), _player(0, False), _player(1, True), _player(0, False)]
    )
    assert sidecar_outcomes(replay, path) == {
        "A": "won",
        "B": "lost",
        "Random": "won",
        "C": "lost",
    }


def test_sidecar_absent_returns_none(tmp_path):
    replay = _replay([_human("A", team=1), _human("B", team=0)])
    # A replay path with no sidecar beside it: defer to the heuristic.
    assert sidecar_outcomes(replay, tmp_path / "game.BfME2Replay") is None


def test_sidecar_observers_ignored(tmp_path):
    # An observer entry votes for no team and is dropped before the win/loss teams are read.
    replay = _replay([_human("Winner", team=1), _human("Loser", team=0)])
    path = _write_sidecar(
        tmp_path,
        [
            _player(0, False),
            _player(1, True),
            {"Team": 0, "IsWinner": True, "IsObserver": True},  # an observer, ignored
        ],
    )
    assert sidecar_outcomes(replay, path) == {"Winner": "won", "Loser": "lost"}


def test_sidecar_rejected_when_no_winner_flagged(tmp_path):
    replay = _replay([_human("A", team=1), _human("B", team=0)])
    path = _write_sidecar(tmp_path, [_player(0, False), _player(1, False)])
    assert sidecar_outcomes(replay, path) is None


def test_sidecar_rejected_when_a_team_both_won_and_lost(tmp_path):
    # An inconsistent sidecar (a team flagged both ways) is not a real result: decline it.
    replay = _replay([_human("A", team=1), _human("B", team=0)])
    path = _write_sidecar(tmp_path, [_player(0, True), _player(0, False), _player(1, True)])
    assert sidecar_outcomes(replay, path) is None


def test_sidecar_rejected_when_a_human_is_unteamed(tmp_path):
    # An unteamed slot (team -1, an FFA lobby) can't be placed by team, so the whole verdict
    # is declined rather than guessed - this is also the shape the one mismatched corpus
    # sidecar takes (a six-player record over a two-player, unteamed replay).
    replay = _replay([_human("A", team=-1), _human("B", team=-1)])
    path = _write_sidecar(tmp_path, [_player(0, False), _player(1, True)])
    assert sidecar_outcomes(replay, path) is None


def test_sidecar_rejected_when_slot_team_absent_from_sidecar(tmp_path):
    # A sidecar for a differently shaped game (its teams don't cover the replay's) is refused
    # rather than mapped by coincidence.
    replay = _replay([_human("A", team=2), _human("B", team=0)])
    path = _write_sidecar(tmp_path, [_player(0, False), _player(1, True)])
    assert sidecar_outcomes(replay, path) is None


def test_sidecar_outcomes_ignores_observer_slot(tmp_path):
    # An unteamed observer slot in the replay must not disqualify the whole game: it is skipped,
    # and the two real players still resolve by team (a casted tournament match is this shape).
    replay = _replay([_human("A", team=1), _human("B", team=0), _observer("Caster")])
    path = _write_sidecar(tmp_path, [_player(1, True), _player(0, False)])
    assert sidecar_outcomes(replay, path) == {"A": "won", "B": "lost"}


def test_build_sidecar_stub_fills_from_header(tmp_path):
    replay = _replay([_human("Winner", team=1, faction=7), _human("Loser", team=0, faction=10)])
    replay.header.metadata.map_file = "maps/foo"
    stub = build_sidecar_stub(replay, tmp_path / "match.BfME2Replay")
    assert stub["ReplayId"] == "match.BfME2Replay"
    assert stub["MapName"] == "maps/foo"
    assert stub["GamemodeName"] == "1v1"  # two teams of one
    assert stub["Duration"] == "0:01:00"  # 60 timecodes at 1 fps (the _replay helper's timing)
    players = {p["DisplayName"]: p for p in stub["Players"]}
    assert (players["Winner"]["FactionIndex"], players["Winner"]["Team"]) == (7, 1)
    # A stub records no winner - that is the one fact the header can't supply, left for a human.
    assert not any(p["IsWinner"] for p in stub["Players"])


def test_build_sidecar_stub_flags_observer_and_omits_ai(tmp_path):
    replay = _replay(
        [
            _human("P1", team=0, faction=3),
            _human("P2", team=1, faction=5),
            _observer("Caster"),
            ReplaySlot(slot_type=ReplaySlotType.Computer, faction=5, team=1),  # AI: omitted
        ]
    )
    stub = build_sidecar_stub(replay, tmp_path / "m.BfME2Replay")
    names = {p["DisplayName"]: p for p in stub["Players"]}
    assert set(names) == {"P1", "P2", "Caster"}  # the AI slot is not listed
    assert names["Caster"]["IsObserver"] is True
    assert names["P1"]["IsObserver"] is False
    # The observer's team doesn't count toward the mode: two real players, one each side.
    assert stub["GamemodeName"] == "1v1"


def _write_players(path: Path, players: list[dict]) -> None:
    path.write_text(json.dumps({"Players": players}), encoding="utf-8")


def test_sidecar_has_winner(tmp_path):
    path = tmp_path / "x.json"
    _write_players(path, [_player(0, False), _player(1, True)])
    assert sidecar_has_winner(path) is True
    _write_players(path, [_player(0, False), _player(1, False)])
    assert sidecar_has_winner(path) is False
    # A winner flagged only on an observer doesn't count.
    _write_players(path, [{"Team": 0, "IsWinner": True, "IsObserver": True}])
    assert sidecar_has_winner(path) is False
    assert sidecar_has_winner(tmp_path / "absent.json") is False


def test_ensure_sidecars_generates_reports_and_is_idempotent(tmp_path, monkeypatch):
    replay = _replay([_human("A", team=1, faction=7), _human("B", team=0, faction=10)])
    replay_path = tmp_path / "game.BfME2Replay"
    monkeypatch.setattr(
        "sage_replay.sidecar.parse_replay_from_path", lambda path, only_header: replay
    )

    # First sweep: the stub is written, and the replay is reported as still needing a winner.
    report = ensure_sidecars([replay_path])
    assert report.generated == [replay_path]
    assert report.needs_winner == [replay_path]
    assert report.failed == []
    assert sidecar_path(replay_path).is_file()

    # A human fills in the winning team; the next sweep writes nothing and clears the warning.
    sidecar = sidecar_path(replay_path)
    data = json.loads(sidecar.read_text(encoding="utf-8"))
    data["Players"][0]["IsWinner"] = True  # team 1 (A) won
    sidecar.write_text(json.dumps(data), encoding="utf-8")
    report = ensure_sidecars([replay_path])
    assert report.generated == []
    assert report.needs_winner == []


def test_ensure_sidecars_records_unparseable_replay(tmp_path, monkeypatch):
    def boom(path, only_header):
        raise ValueError("bad header")

    monkeypatch.setattr("sage_replay.sidecar.parse_replay_from_path", boom)
    bad = tmp_path / "broken.BfME2Replay"
    report = ensure_sidecars([bad])
    assert report.generated == []
    assert report.failed == [(bad, "bad header")]
    assert not sidecar_path(bad).is_file()
