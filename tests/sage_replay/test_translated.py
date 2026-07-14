"""Tests for `sage_replay.translated`: the document's dict/JSON round trip, the `from_dict`
validation contract (unknown versions and malformed documents raise, unknown extra keys are
ignored), replay-identity matching by size + content hash, and `to_player_games`' outcome
override semantics."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from sage_replay.aggregate import PlayerGame
from sage_replay.replay import (
    ReplayFile,
    ReplayGameType,
    ReplayHeader,
    ReplayMetadata,
    ReplaySlot,
    ReplaySlotType,
    ReplayTimestamp,
)
from sage_replay.stats import PlayerStats, StatEvent
from sage_replay.translated import FORMAT, FORMAT_VERSION, TranslatedReplay


def _replay(slots: list[ReplaySlot]) -> ReplayFile:
    header = ReplayHeader(
        game_type=ReplayGameType.Bfme2,
        start_time=datetime(2026, 1, 1, tzinfo=UTC),
        end_time=datetime(2026, 1, 1, 0, 5, tzinfo=UTC),
        num_timecodes=300,
        filename="synthetic",
        timestamp=ReplayTimestamp(*([0] * 8)),
        version="",
        build_date="",
        metadata=ReplayMetadata(slots=slots),
        local_player_index=-1,
    )
    return ReplayFile(header=header, chunks=[])


def _human(name: str, *, team: int, faction: int = 0) -> ReplaySlot:
    return ReplaySlot(slot_type=ReplaySlotType.Human, human_name=name, faction=faction, team=team)


def _game(player: str, faction: str, *, opponents: tuple[str, ...] = ()) -> PlayerGame:
    events = [
        StatEvent(12.0, "buildings", "dunedain_barracks (unpacks dunedain_outpost)"),
        StatEvent(30.0, "fortress_hero_slots", 2),
        StatEvent(45.0, "sciences", "ScienceLeadership"),
    ]
    return PlayerGame(
        replay="game.BfME2Replay",
        player=player,
        faction=faction,
        outcome="undetermined",
        duration=180.0,
        stats=PlayerStats(player=player, events=events),
        opponents=opponents,
    )


def _document(tmp_path: Path) -> tuple[TranslatedReplay, Path]:
    """A document freshly produced from a synthetic parse, plus its replay file's path."""
    replay_path = tmp_path / "game.BfME2Replay"
    replay_path.write_bytes(b"synthetic replay bytes")
    replay = _replay([_human("A", team=1), _human("B", team=0)])
    games = [
        _game("A", "Men (Arnor)", opponents=("Mordor",)),
        _game("B", "Mordor", opponents=("Men (Arnor)",)),
    ]
    document = TranslatedReplay.from_parse(
        replay_path,
        replay,
        games,
        heuristic_outcomes={"A": "won", "B": "lost"},
        side_of=lambda label: "Men" if "dunedain" in label else None,
        assume_pov_won=True,
    )
    return document, replay_path


def test_dict_round_trip_is_lossless(tmp_path):
    document, _ = _document(tmp_path)
    rebuilt = TranslatedReplay.from_dict(document.to_dict())
    assert rebuilt == document
    # The wire shape keeps the int label an int, so the round trip is exact, not stringly.
    assert rebuilt.players[0].events[1].label == 2
    assert isinstance(rebuilt.players[0].events[1].label, int)


def test_json_file_round_trip(tmp_path):
    document, _ = _document(tmp_path)
    path = tmp_path / "shared.json"
    document.write(path)
    assert TranslatedReplay.read(path) == document
    # The serialized form self-identifies, so a shared file is recognisable on sight.
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["format"] == FORMAT
    assert payload["format_version"] == FORMAT_VERSION


def test_from_dict_ignores_unknown_keys(tmp_path):
    document, _ = _document(tmp_path)
    payload = document.to_dict()
    payload["produced_by"] = "someone else's tool"
    payload["players"][0]["notes"] = "annotated"
    assert TranslatedReplay.from_dict(payload) == document


def test_from_dict_rejects_wrong_magic_and_version(tmp_path):
    document, _ = _document(tmp_path)
    wrong_magic = document.to_dict() | {"format": "something/else"}
    with pytest.raises(ValueError, match="not a"):
        TranslatedReplay.from_dict(wrong_magic)
    newer = document.to_dict() | {"format_version": FORMAT_VERSION + 1}
    with pytest.raises(ValueError, match="unsupported format_version"):
        TranslatedReplay.from_dict(newer)


def test_from_dict_rejects_malformed_documents(tmp_path):
    document, _ = _document(tmp_path)
    missing = document.to_dict()
    del missing["sha256"]
    with pytest.raises(ValueError, match="missing"):
        TranslatedReplay.from_dict(missing)
    bad_outcome = document.to_dict()
    bad_outcome["players"][0]["heuristic_outcome"] = "victorious"
    with pytest.raises(ValueError, match="heuristic_outcome"):
        TranslatedReplay.from_dict(bad_outcome)
    with pytest.raises(ValueError, match="JSON object"):
        TranslatedReplay.from_dict(["not", "an", "object"])


def test_read_raises_value_error_for_non_json(tmp_path):
    path = tmp_path / "broken.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError, match="not JSON"):
        TranslatedReplay.read(path)


def test_matches_replay_by_size_and_content(tmp_path):
    document, replay_path = _document(tmp_path)
    assert document.matches_replay(replay_path)

    # Same size, different bytes: caught by the hash - the property that makes a shared
    # replay+document pair verifiable after copying, where an mtime check would misfire.
    original = replay_path.read_bytes()
    replay_path.write_bytes(bytes(reversed(original)))
    assert not document.matches_replay(replay_path)

    replay_path.write_bytes(original)
    assert document.matches_replay(replay_path)
    assert not document.matches_replay(tmp_path / "missing.BfME2Replay")


def test_from_parse_records_identity_and_teams(tmp_path):
    document, replay_path = _document(tmp_path)
    assert document.replay == "game.BfME2Replay"
    assert document.size == replay_path.stat().st_size
    assert document.duration == 180.0
    assert document.assume_pov_won is True
    assert document.player_teams == [("A", 1), ("B", 0)]
    assert document.sides == {"dunedain_barracks (unpacks dunedain_outpost)": "Men"}


def test_to_player_games_outcome_override(tmp_path):
    document, _ = _document(tmp_path)

    # Without an override, the frozen heuristic outcomes stand.
    by_name = {g.player: g for g in document.to_player_games()}
    assert by_name["A"].outcome == "won"
    assert by_name["B"].outcome == "lost"

    # An override (e.g. the current sidecar's verdict) replaces every outcome - a player it
    # doesn't name is undetermined, not their heuristic fallback, matching a fresh parse fed
    # an explicit outcomes map.
    overridden = {g.player: g for g in document.to_player_games({"B": "won"})}
    assert overridden["B"].outcome == "won"
    assert overridden["A"].outcome == "undetermined"

    # The games are aggregate-ready: stats, opponents and duration travel intact.
    assert by_name["A"].stats.events[0].category == "buildings"
    assert by_name["A"].opponents == ("Mordor",)
    assert by_name["A"].duration == 180.0
