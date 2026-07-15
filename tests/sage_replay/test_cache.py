"""Tests for `sage_replay.cache`: the mirrored cache-tree path convention, the translate/load
round trip (a cached load reproduces a fresh `player_games` run), outcome re-resolution against a
sidecar written or edited after caching, and the trust checks that turn a stale document into a
miss. Synthetic replay + GameData, so no game install is needed - the same helper style as
`tests/sage_replay/test_stats.py` and `test_translated.py`."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from sage_replay.aggregate import player_games
from sage_replay.cache import cache_path, cached_document, load_replay_cache, write_replay_cache
from sage_replay.narrate import GameData
from sage_replay.replay import (
    Order,
    OrderArgument,
    OrderArgumentType,
    ReplayChunk,
    ReplayFile,
    ReplayGameType,
    ReplayHeader,
    ReplayMetadata,
    ReplaySlot,
    ReplaySlotType,
    ReplayTimestamp,
)
from sage_replay.sidecar import sidecar_path
from sage_replay.translated import FORMAT_VERSION

_T = OrderArgumentType


class _obj:
    """Stand-in for a loaded Object: a `_fields` dict, optional ChildObject-style parent."""

    def __init__(self, fields: dict, parent=None) -> None:
        self._fields = fields
        if parent is not None:
            self.parent = parent


def _data() -> GameData:
    """A GameData with two factions (Gondor/Mordor) and a small object/upgrade/science table -
    enough to translate the id spaces the synthetic replay uses and to name a fortress hero."""
    return GameData(
        object_order=["GondorBarracks", "OrcHorde", "Boromir", "MordorFighter"],
        objects={
            "GondorBarracks": _obj({"KindOf": "STRUCTURE SELECTABLE", "Side": "Men"}),
            "OrcHorde": _obj({"KindOf": "HORDE SELECTABLE", "Side": "Mordor"}),
            "Boromir": _obj({"KindOf": "HERO SELECTABLE", "Side": "Men"}),
            "MordorFighter": _obj({"KindOf": "SELECTABLE", "Side": "Mordor"}),
        },
        specialpowers=["SpecialAbilityHeal"],
        sciences=["ScienceOne", "ScienceTwo"],
        upgrades=["DefaultUpgrade", "Upgrade_ForgedBlades"],
        displaynames={},
        faction_labels=["FactionGondor", "FactionMordor"],
        faction_sides=["Men", "Mordor"],
        faction_names=["FactionGondor", "FactionMordor"],
        hero_rosters=[["Boromir"], []],
        hero_build_times={"Boromir": 30.0},
    )


def _human(name: str, *, team: int, faction: int = 0) -> ReplaySlot:
    return ReplaySlot(slot_type=ReplaySlotType.Human, human_name=name, faction=faction, team=team)


def _chunk(order_type: int, args: list, *, timecode: int = 0, number: int = 3) -> ReplayChunk:
    order = Order(player_index=number - 1, order_type=order_type)
    order.arguments = [OrderArgument(t, v) for t, v in args]
    return ReplayChunk(timecode=timecode, order_type=order_type, number=number, order=order)


def _replay() -> ReplayFile:
    """A 1v1 whose recorder (slot 0, `local_player_index` 0) builds and fields a fortress hero,
    the opponent recruiting a unit - so both slots carry stats and both appear as sessions."""
    slots = [_human("A", team=1, faction=0), _human("B", team=0, faction=1)]
    chunks = [
        _chunk(0x419, [(_T.Integer, 1), (_T.Position, (1.0, 2.0, 3.0))], timecode=5),  # GondorBarr.
        _chunk(0x417, [(_T.Boolean, True), (_T.Integer, 0), (_T.Integer, 0)], timecode=20),  # Boro
        _chunk(
            0x417, [(_T.Boolean, False), (_T.Integer, 2), (_T.Integer, 0)], number=4, timecode=30
        ),
    ]
    header = ReplayHeader(
        game_type=ReplayGameType.Bfme2,
        start_time=datetime(2026, 1, 1, tzinfo=UTC),
        end_time=datetime(2026, 1, 1, 0, 5, tzinfo=UTC),  # 300 s span, 1 s per timecode
        num_timecodes=300,
        filename="game.BfME2Replay",
        timestamp=ReplayTimestamp(*([0] * 8)),
        version="",
        build_date="",
        metadata=ReplayMetadata(map_file="maps/synthetic", slots=slots),
        local_player_index=0,
    )
    return ReplayFile(header=header, chunks=chunks)


def _roots(tmp_path: Path) -> tuple[Path, Path]:
    """The replay tree and the cache tree that mirrors it, as a corpus build lays them out."""
    return tmp_path / "replays", tmp_path / "cached"


def _write_replay_file(tmp_path: Path, name: str = "game.BfME2Replay", subfolder: str = "") -> Path:
    # The document records the replay's size and hash; the bytes are never parsed here.
    replay_root, _ = _roots(tmp_path)
    folder = replay_root / subfolder if subfolder else replay_root
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_bytes(b"synthetic replay bytes")
    return path


def _cache_file(tmp_path: Path, replay_path: Path) -> Path:
    replay_root, cache_root = _roots(tmp_path)
    return cache_path(replay_path, replay_root, cache_root)


def _write(tmp_path: Path, replay_path: Path, replay: ReplayFile, data: GameData) -> Path:
    return write_replay_cache(
        replay_path, replay, data, cache_file=_cache_file(tmp_path, replay_path)
    )


def _load(tmp_path: Path, replay_path: Path, data: GameData, *, assume_pov_won: bool = True):
    return load_replay_cache(
        replay_path, _cache_file(tmp_path, replay_path), data, assume_pov_won=assume_pov_won
    )


def _sidecar_player(team: int, winner: bool) -> dict:
    return {"Team": team, "IsWinner": winner, "IsObserver": False}


def _outcomes(games) -> dict[str, str]:
    return {game.player: game.outcome for game in games}


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
    data = _data()
    replay_path = _write_replay_file(tmp_path, subfolder="1v1")
    path = _write(tmp_path, replay_path, _replay(), data)
    _, cache_root = _roots(tmp_path)
    assert path == cache_root / "1v1" / "game.BfME2Replay.json"
    assert path.is_file()
    assert _load(tmp_path, replay_path, data) is not None


def test_cached_load_matches_a_fresh_player_games_run(tmp_path):
    # The whole contract: a cache hit reproduces a fresh parse's player-games, because the load
    # rehydrates the document and runs the very same pipeline against the paired game.
    data = _data()
    replay = _replay()
    replay_path = _write_replay_file(tmp_path)
    _write(tmp_path, replay_path, replay, data)

    fresh = player_games(replay, data, source=replay_path.name, assume_pov_won=True)
    cached = _load(tmp_path, replay_path, data, assume_pov_won=True)
    assert cached is not None

    key = lambda games: sorted(games, key=lambda g: g.player)  # noqa: E731
    assert key(cached) == key(fresh)
    # Concretely: the recorder built a Barracks and fielded Boromir; both slots are sessions, so
    # assume_pov_won decides the recorder's team the winner.
    by_name = {g.player: g for g in cached}
    assert by_name["A"].faction == "FactionGondor"
    assert by_name["A"].stats.heroes == {"Boromir": 1}
    assert by_name["A"].stats.buildings == {"GondorBarracks": 1}
    assert by_name["B"].stats.units == {"OrcHorde": 1}
    assert _outcomes(cached) == {"A": "won", "B": "lost"}


def test_outcome_reresolves_from_a_sidecar_written_after_caching(tmp_path):
    data = _data()
    replay_path = _write_replay_file(tmp_path)
    _write(tmp_path, replay_path, _replay(), data)

    # No sidecar yet: the concession heuristic (assume_pov_won) decides the recorder's team.
    assert _outcomes(_load(tmp_path, replay_path, data)) == {"A": "won", "B": "lost"}

    # A sidecar appears after caching, naming the *other* team the winner - proving a winner
    # filled in after caching is honored on the next load, with no reparse.
    sidecar_path(replay_path).write_text(
        json.dumps({"Players": [_sidecar_player(0, True), _sidecar_player(1, False)]}),
        encoding="utf-8",
    )
    assert _outcomes(_load(tmp_path, replay_path, data)) == {"A": "lost", "B": "won"}


def test_untrusted_sidecar_falls_back_to_the_heuristic(tmp_path):
    data = _data()
    replay_path = _write_replay_file(tmp_path)
    _write(tmp_path, replay_path, _replay(), data)

    # Team 0 flagged both winner and loser: not a real result, so the sidecar is declined and
    # the heuristic (assume_pov_won) stands.
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
    assert _outcomes(_load(tmp_path, replay_path, data)) == {"A": "won", "B": "lost"}


def test_same_document_loads_under_either_pov_assumption(tmp_path):
    # The assumption is no longer baked into the document; it is a load-time argument that only
    # fills in outcomes the heuristic leaves undetermined.
    data = _data()
    replay_path = _write_replay_file(tmp_path)
    _write(tmp_path, replay_path, _replay(), data)

    assert _outcomes(_load(tmp_path, replay_path, data, assume_pov_won=False)) == {
        "A": "undetermined",
        "B": "undetermined",
    }
    assert _outcomes(_load(tmp_path, replay_path, data, assume_pov_won=True)) == {
        "A": "won",
        "B": "lost",
    }


def test_stale_replay_size_invalidates_cache(tmp_path):
    data = _data()
    replay_path = _write_replay_file(tmp_path)
    _write(tmp_path, replay_path, _replay(), data)
    assert _load(tmp_path, replay_path, data) is not None

    replay_path.write_bytes(b"a completely different, longer set of replay bytes on disk")
    assert _load(tmp_path, replay_path, data) is None


def test_stale_replay_content_invalidates_cache_even_at_the_same_size(tmp_path):
    data = _data()
    replay_path = _write_replay_file(tmp_path)
    _write(tmp_path, replay_path, _replay(), data)
    original = replay_path.read_bytes()

    # Same length, different bytes: only the content hash can tell them apart.
    replay_path.write_bytes(bytes(reversed(original)))
    assert _load(tmp_path, replay_path, data) is None


def test_format_version_bump_invalidates_cache(tmp_path):
    data = _data()
    replay_path = _write_replay_file(tmp_path)
    path = _write(tmp_path, replay_path, _replay(), data)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["format_version"] == FORMAT_VERSION
    payload["format_version"] = FORMAT_VERSION + 1
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert _load(tmp_path, replay_path, data) is None


def test_missing_cache_returns_none(tmp_path):
    data = _data()
    replay_path = _write_replay_file(tmp_path)
    assert _load(tmp_path, replay_path, data) is None
    assert cached_document(replay_path, _cache_file(tmp_path, replay_path)) is None


def test_cached_document_is_the_shared_freshness_check(tmp_path):
    data = _data()
    replay_path = _write_replay_file(tmp_path)
    _write(tmp_path, replay_path, _replay(), data)
    cache_file = _cache_file(tmp_path, replay_path)

    document = cached_document(replay_path, cache_file)
    assert document is not None
    assert [p.name for p in document.players] == ["A", "B"]

    replay_path.write_bytes(b"changed")
    assert cached_document(replay_path, cache_file) is None
