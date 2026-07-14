"""Tests for `sage_replay.cache`: the mirrored cache-tree path convention, the round trip
through an explicit cache file, outcome re-resolution against a sidecar written or edited
after caching, and the trust checks that turn a stale document into a miss."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from sage_replay.aggregate import PlayerGame
from sage_replay.cache import cache_path, cached_document, load_replay_cache, write_replay_cache
from sage_replay.replay import (
    ReplayFile,
    ReplayGameType,
    ReplayHeader,
    ReplayMetadata,
    ReplaySlot,
    ReplaySlotType,
    ReplayTimestamp,
)
from sage_replay.sidecar import sidecar_path, sidecar_team_outcomes
from sage_replay.stats import PlayerStats, StatEvent
from sage_replay.translated import FORMAT_VERSION


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


def _roots(tmp_path: Path) -> tuple[Path, Path]:
    """The replay tree and the cache tree that mirrors it, as a corpus build lays them out."""
    return tmp_path / "replays", tmp_path / "cached"


def _write_replay(tmp_path: Path, name: str = "game.BfME2Replay", subfolder: str = "") -> Path:
    # The document records the replay's size and hash - the bytes are never parsed here.
    replay_root, _ = _roots(tmp_path)
    folder = replay_root / subfolder if subfolder else replay_root
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_bytes(b"synthetic replay bytes")
    return path


def _cache_file(tmp_path: Path, replay_path: Path) -> Path:
    replay_root, cache_root = _roots(tmp_path)
    return cache_path(replay_path, replay_root, cache_root)


def _write(tmp_path: Path, replay_path: Path, replay, games, heuristic=None) -> Path:
    return write_replay_cache(
        replay_path,
        replay,
        games,
        cache_file=_cache_file(tmp_path, replay_path),
        heuristic_outcomes=heuristic or {},
        side_of=_side_of,
        assume_pov_won=True,
    )


def _load(tmp_path: Path, replay_path: Path, *, assume_pov_won: bool = True):
    return load_replay_cache(
        replay_path, _cache_file(tmp_path, replay_path), assume_pov_won=assume_pov_won
    )


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


def _side_of(label: str) -> str | None:
    # A stand-in `GameData.effective_side`: only the building label carries a resolvable Side.
    return "Men" if "dunedain" in label else None


def _sidecar_player(team: int, winner: bool) -> dict:
    return {"Team": team, "IsWinner": winner, "IsObserver": False}


def test_cache_path_mirrors_the_replay_tree(tmp_path):
    replay_root, cache_root = _roots(tmp_path)
    nested = replay_root / "corpus" / "1v1" / "game.BfME2Replay"
    assert cache_path(nested, replay_root, cache_root) == (
        cache_root / "corpus" / "1v1" / "game.BfME2Replay.json"
    )
    flat = replay_root / "game.BfME2Replay"
    assert cache_path(flat, replay_root, cache_root) == cache_root / "game.BfME2Replay.json"
    # A replay outside the mirrored tree has no cache location.
    with pytest.raises(ValueError):
        cache_path(tmp_path / "elsewhere.BfME2Replay", replay_root, cache_root)


def test_write_creates_the_mirrored_folders(tmp_path):
    replay_path = _write_replay(tmp_path, subfolder="1v1")
    replay = _replay([_human("A", team=1), _human("B", team=0)])
    path = _write(tmp_path, replay_path, replay, [_game("A", "Men"), _game("B", "Mordor")])
    _, cache_root = _roots(tmp_path)
    assert path == cache_root / "1v1" / "game.BfME2Replay.json"
    assert path.is_file()
    assert _load(tmp_path, replay_path) is not None


def test_round_trip_preserves_players_events_and_sides(tmp_path):
    replay_path = _write_replay(tmp_path)
    replay = _replay([_human("A", team=1), _human("B", team=0)])
    games = [
        _game("A", "Men (Arnor)", opponents=("Mordor",)),
        _game("B", "Mordor", opponents=("Men (Arnor)",)),
    ]
    _write(tmp_path, replay_path, replay, games, heuristic={"A": "won", "B": "lost"})
    cached = _load(tmp_path, replay_path)

    assert cached is not None
    by_name = {g.player: g for g in cached.games}
    assert set(by_name) == {"A", "B"}
    assert by_name["A"].faction == "Men (Arnor)"
    assert by_name["A"].opponents == ("Mordor",)
    assert by_name["A"].duration == 180.0
    # No sidecar exists yet, so the heuristic outcome recorded at write time is what comes back.
    assert by_name["A"].outcome == "won"
    assert by_name["B"].outcome == "lost"

    original_events = games[0].stats.events
    round_tripped_events = by_name["A"].stats.events
    assert round_tripped_events == original_events
    # The fortress_hero_slots label stays an int through the JSON round trip, not "2".
    assert isinstance(round_tripped_events[1].label, int)
    assert isinstance(round_tripped_events[0].label, str)

    # Only the building label resolves a Side; the science and the int-labeled slot don't.
    assert cached.sides == {"dunedain_barracks (unpacks dunedain_outpost)": "Men"}


def test_outcome_reresolves_from_a_sidecar_written_after_caching(tmp_path):
    replay_path = _write_replay(tmp_path)
    replay = _replay([_human("A", team=1), _human("B", team=0)])
    _write(
        tmp_path,
        replay_path,
        replay,
        [_game("A", "Men"), _game("B", "Mordor")],
        heuristic={"A": "won", "B": "lost"},
    )

    # No sidecar yet: the cached heuristic outcomes stand.
    cached = _load(tmp_path, replay_path)
    assert cached is not None
    assert {g.player: g.outcome for g in cached.games} == {"A": "won", "B": "lost"}

    # A sidecar appears after the cache was written, naming the *other* team the winner - proving
    # a winner filled in after caching is honored without any reparse.
    sidecar_path(replay_path).write_text(
        json.dumps({"Players": [_sidecar_player(0, True), _sidecar_player(1, False)]}),
        encoding="utf-8",
    )
    reloaded = _load(tmp_path, replay_path)
    assert reloaded is not None
    assert {g.player: g.outcome for g in reloaded.games} == {"A": "lost", "B": "won"}


def test_untrusted_sidecar_falls_back_to_heuristic(tmp_path):
    replay_path = _write_replay(tmp_path)
    replay = _replay([_human("A", team=1), _human("B", team=0)])
    _write(
        tmp_path,
        replay_path,
        replay,
        [_game("A", "Men"), _game("B", "Mordor")],
        heuristic={"A": "won", "B": "lost"},
    )

    # Team 0 is flagged both winner and loser: not a real result, so the sidecar is declined.
    sidecar_path(replay_path).write_text(
        json.dumps(
            {
                "Players": [
                    _sidecar_player(0, True),
                    _sidecar_player(0, False),
                    _sidecar_player(1, True),
                ]
            }
        ),
        encoding="utf-8",
    )
    cached = _load(tmp_path, replay_path)
    assert cached is not None
    assert {g.player: g.outcome for g in cached.games} == {"A": "won", "B": "lost"}


def test_stale_replay_size_invalidates_cache(tmp_path):
    replay_path = _write_replay(tmp_path)
    replay = _replay([_human("A", team=1), _human("B", team=0)])
    _write(tmp_path, replay_path, replay, [_game("A", "Men"), _game("B", "Mordor")])
    assert _load(tmp_path, replay_path) is not None

    replay_path.write_bytes(b"a completely different, longer set of replay bytes on disk")
    assert _load(tmp_path, replay_path) is None


def test_stale_replay_content_invalidates_cache_even_at_the_same_size(tmp_path):
    replay_path = _write_replay(tmp_path)
    replay = _replay([_human("A", team=1), _human("B", team=0)])
    _write(tmp_path, replay_path, replay, [_game("A", "Men"), _game("B", "Mordor")])
    original = replay_path.read_bytes()

    # Same length, different bytes: only the content hash can tell them apart.
    replay_path.write_bytes(bytes(reversed(original)))
    assert _load(tmp_path, replay_path) is None


def test_format_version_bump_invalidates_cache(tmp_path):
    replay_path = _write_replay(tmp_path)
    replay = _replay([_human("A", team=1), _human("B", team=0)])
    path = _write(tmp_path, replay_path, replay, [_game("A", "Men"), _game("B", "Mordor")])
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["format_version"] == FORMAT_VERSION
    payload["format_version"] = FORMAT_VERSION + 1
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert _load(tmp_path, replay_path) is None


def test_assume_pov_won_mismatch_invalidates_cache(tmp_path):
    replay_path = _write_replay(tmp_path)
    replay = _replay([_human("A", team=1), _human("B", team=0)])
    _write(tmp_path, replay_path, replay, [_game("A", "Men"), _game("B", "Mordor")])
    assert _load(tmp_path, replay_path, assume_pov_won=False) is None
    assert _load(tmp_path, replay_path, assume_pov_won=True) is not None


def test_missing_cache_returns_none(tmp_path):
    replay_path = _write_replay(tmp_path)
    assert _load(tmp_path, replay_path) is None
    assert (
        cached_document(replay_path, _cache_file(tmp_path, replay_path), assume_pov_won=True)
        is None
    )


def test_cached_document_is_the_freshness_check(tmp_path):
    replay_path = _write_replay(tmp_path)
    replay = _replay([_human("A", team=1), _human("B", team=0)])
    _write(tmp_path, replay_path, replay, [_game("A", "Men"), _game("B", "Mordor")])
    cache_file = _cache_file(tmp_path, replay_path)

    document = cached_document(replay_path, cache_file, assume_pov_won=True)
    assert document is not None
    assert document.player_teams == [("A", 1), ("B", 0)]

    replay_path.write_bytes(b"changed")
    assert cached_document(replay_path, cache_file, assume_pov_won=True) is None


def test_sidecar_team_outcomes_trusted_mapping(tmp_path):
    replay_path = _write_replay(tmp_path)
    sidecar_path(replay_path).write_text(
        json.dumps({"Players": [_sidecar_player(0, False), _sidecar_player(1, True)]}),
        encoding="utf-8",
    )
    assert sidecar_team_outcomes(replay_path, [("Winner", 1), ("Loser", 0)]) == {
        "Winner": "won",
        "Loser": "lost",
    }


def test_sidecar_team_outcomes_declines_when_players_empty(tmp_path):
    replay_path = _write_replay(tmp_path)
    sidecar_path(replay_path).write_text(
        json.dumps({"Players": [_sidecar_player(0, False), _sidecar_player(1, True)]}),
        encoding="utf-8",
    )
    assert sidecar_team_outcomes(replay_path, []) is None


def test_sidecar_team_outcomes_declines_unteamed_player(tmp_path):
    replay_path = _write_replay(tmp_path)
    sidecar_path(replay_path).write_text(
        json.dumps({"Players": [_sidecar_player(0, False), _sidecar_player(1, True)]}),
        encoding="utf-8",
    )
    # An unteamed (-1) pair can't be placed by team, so the whole verdict is declined.
    assert sidecar_team_outcomes(replay_path, [("A", -1), ("B", 0)]) is None


def test_sidecar_team_outcomes_declines_missing_sidecar(tmp_path):
    replay_path = _write_replay(tmp_path)
    assert sidecar_team_outcomes(replay_path, [("A", 0), ("B", 1)]) is None
