"""Hero-recruit slot resolution: the `ReviveList` submenu model in isolation, and the
stats/narrate wiring over the three labelled Linhir fixtures (`hero recruit*.BfME2Replay`),
whose ground truth pinned the model (order_space_map.md, `0x417` flag=True / `0x418`).
Synthetic GameData - no game install needed: the fixtures' map hero roster is inlined."""

from datetime import UTC, datetime
from pathlib import Path

from sage_replay.aggregate import (
    Corpus,
    player_games,
    render_aggregate,
    render_aggregate_html,
    render_aggregate_markdown,
)
from sage_replay.heroes import ReviveList
from sage_replay.narrate import GameData, narrate
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
    parse_replay_from_path,
)
from sage_replay.stats import compute_stats

FIXTURES = Path(__file__).parent / "fixtures"

# The Linhir map.ini's Gondor `BuildableHeroesMP` - the initial revive submenu, position 0
# is the CreateAHero placeholder.
ROSTER = [
    "CreateAHero",
    "AmrothAmrothos",
    "AmrothElphir",
    "AmrothLothiriel",
    "AmrothImrahil",
    "GondorBoromir_mod",
    "GondorGandalf_mod",
    "AmrothErchirion",
]
BUILD_TIMES = {name: 30.0 for name in ROSTER}


def _list() -> ReviveList:
    return ReviveList(ROSTER, BUILD_TIMES)


def test_static_positions_while_everyone_is_in_production():
    # The burst replay: five recruits within seconds - nobody fields, so every id is the
    # hero's static BuildableHeroesMP position.
    revive = _list()
    assert revive.recruit(56.0, 1) == "AmrothAmrothos"
    assert revive.recruit(57.0, 3) == "AmrothLothiriel"
    assert revive.recruit(58.0, 6) == "GondorGandalf_mod"
    assert revive.recruit(61.0, 2) == "AmrothElphir"
    assert revive.recruit(64.0, 4) == "AmrothImrahil"


def test_fielded_heroes_collapse_the_list():
    # The fielded-wait replay: ids 1, 2, 4 name Amrothos, Lothiriel, Gandalf because each
    # fielded hero (30s revive) leaves the list and everyone behind slides forward.
    revive = _list()
    assert revive.recruit(14.0, 1) == "AmrothAmrothos"
    assert revive.recruit(49.0, 2) == "AmrothLothiriel"
    assert revive.recruit(86.0, 4) == "GondorGandalf_mod"


def test_in_production_holds_position_and_cancel_unqueues():
    revive = _list()
    assert revive.recruit(12.0, 1) == "AmrothAmrothos"
    # Amrothos is still in production: Lothiriel keeps her static position.
    assert revive.recruit(16.0, 3) == "AmrothLothiriel"
    assert revive.cancel(17.0, 3) == "AmrothLothiriel"
    # The cancelled Lothiriel never fields: 50s later only Amrothos has left the list.
    assert revive.recruit(66.0, 2) == "AmrothLothiriel"


def test_dead_hero_reenters_at_the_tail():
    revive = _list()
    revive.recruit(12.0, 1)
    # Amrothos fields (list is 7 long, positions 0..6); his later death is invisible until
    # a tail recruit - resolvable because he is the only hero that can have died.
    assert revive.recruit(90.0, 7) == "AmrothAmrothos"
    # He re-entered at the tail and is in production there; the same position cancels him.
    assert revive.cancel(96.0, 7) == "AmrothAmrothos"
    # Still dead and still listed at the tail after the cancel.
    assert revive.recruit(99.0, 7) == "AmrothAmrothos"


def test_ambiguous_tail_and_out_of_range_stay_unresolved():
    revive = _list()
    revive.recruit(0.0, 1)
    revive.recruit(1.0, 2)
    # Both fielded by 40s: a tail recruit could be either dead hero.
    assert revive.recruit(40.0, 6) is None  # tail of the 6-long list, 2 candidates
    assert revive.recruit(40.0, 99) is None
    assert revive.cancel(40.0, 99) is None
    # In-range positions still resolve (unknown dead entries sit past the tail).
    assert revive.recruit(41.0, 0) == "CreateAHero"


def test_hero_without_build_time_never_fields():
    revive = ReviveList(ROSTER, {})
    revive.recruit(0.0, 1)
    # No BuildTime known: Amrothos holds his position forever, so ids stay static.
    assert revive.recruit(500.0, 3) == "AmrothLothiriel"


def _linhir_data() -> GameData:
    # The replay slots carry faction id 3 (FactionMen); rosters index by faction id.
    return GameData(
        object_order=[],
        objects={},
        specialpowers=[],
        sciences=[],
        upgrades=[],
        displaynames={},
        hero_rosters=[[], [], [], ROSTER],
        hero_build_times=BUILD_TIMES,
    )


def _player_heroes(name: str) -> dict:
    replay = parse_replay_from_path(FIXTURES / name)
    per = compute_stats(replay, _linhir_data())[0]
    assert not per.fortress_hero_slots  # every slot id resolved to a hero name
    return dict(per.heroes)


def test_stats_resolve_the_burst_fixture():
    assert _player_heroes("hero recruit.BfME2Replay") == {
        "AmrothAmrothos": 1,
        "AmrothLothiriel": 1,
        "GondorGandalf_mod": 1,
        "AmrothElphir": 4,  # one button clicked four times; the stream records each order
        "AmrothImrahil": 1,
    }


def test_stats_resolve_the_fielded_wait_fixture():
    assert _player_heroes("hero recruit 2.BfME2Replay") == {
        "AmrothAmrothos": 1,
        "AmrothLothiriel": 1,
        "GondorGandalf_mod": 1,
    }


def test_stats_resolve_the_cancel_and_death_fixture():
    # Scripted: recruit Amrothos; recruit+cancel Lothiriel three times (in production /
    # after Amrothos fielded / after his death); recruit+cancel dead Amrothos at the tail.
    # Cancels net everything but the first Amrothos recruit.
    assert _player_heroes("hero recruit 3.BfME2Replay") == {"AmrothAmrothos": 1}


def test_narrate_names_the_fielded_wait_recruits():
    replay = parse_replay_from_path(FIXTURES / "hero recruit 2.BfME2Replay")
    texts = [e.text for e in narrate(replay, _linhir_data())]
    assert texts == [
        "recruits the hero AmrothAmrothos",
        "recruits the hero AmrothLothiriel",
        "recruits the hero GondorGandalf_mod",
    ]


def test_map_roster_override_applies_per_replay(tmp_path):
    # One GameData over a corpus: a replay on a map whose map.ini re-opens the faction with
    # its own BuildableHeroesMP resolves against that roster, not the global one - the
    # aggregate path, where GameData carries no single map.
    map_dir = tmp_path / "maps" / "linhir"
    map_dir.mkdir(parents=True)
    (map_dir / "map.ini").write_text(
        f"PlayerTemplate FactionMen\n    BuildableHeroesMP = {' '.join(ROSTER)}\nEnd\n",
        encoding="utf-8",
    )
    data = GameData(
        object_order=[],
        objects={},
        specialpowers=[],
        sciences=[],
        upgrades=[],
        displaynames={},
        hero_rosters=[[], [], [], ["CreateAHero", "GondorBoromir_mod"]],
        hero_build_times=BUILD_TIMES,
        faction_names=["FactionCivilian", "FactionA", "FactionB", "FactionMen"],
        map_sources=(tmp_path,),
    )
    assert data.hero_roster_for("maps/linhir", 3) == ROSTER
    assert "maps/linhir" in data.map_roster_cache  # parsed once, then served from the cache
    # A map nothing carries, or no map at all, falls back to the global roster.
    assert data.hero_roster_for("maps/elsewhere", 3) == ["CreateAHero", "GondorBoromir_mod"]
    assert data.hero_roster_for(None, 3) == ["CreateAHero", "GondorBoromir_mod"]

    # The real fixture resolves through the override (its header names the Linhir map path).
    replay = parse_replay_from_path(FIXTURES / "hero recruit 2.BfME2Replay")
    (tmp_path / "maps" / "map edain linhir").mkdir()
    (map_dir / "map.ini").replace(tmp_path / "maps" / "map edain linhir" / "map.ini")
    per = compute_stats(replay, data)[0]
    assert dict(per.heroes) == {
        "AmrothAmrothos": 1,
        "AmrothLothiriel": 1,
        "GondorGandalf_mod": 1,
    }


def test_renders_carry_the_hero_approximation_note():
    corpus = Corpus()
    for render in (render_aggregate, render_aggregate_markdown, render_aggregate_html):
        assert any("Hero rows are approximate" in line for line in render(corpus, []))


class _obj:
    def __init__(self, fields: dict) -> None:
        self._fields = fields


def test_player_games_recompute_random_pick_hero_slots():
    # A lobby Random records slot faction -1, so the first stats pass has no roster and
    # leaves hero recruits as raw slots; `player_games` infers the rolled faction from what
    # the player built and recomputes with that faction's roster.
    def chunk(order_type: int, args: list) -> ReplayChunk:
        order = Order(player_index=0, order_type=order_type)
        order.arguments = [OrderArgument(t, v) for t, v in args]
        return ReplayChunk(timecode=1, order_type=order_type, number=3, order=order)

    _T = OrderArgumentType
    slot = ReplaySlot(slot_type=ReplaySlotType.Human, human_name="Rando")
    slot.faction = -1
    header = ReplayHeader(
        game_type=ReplayGameType.Bfme2,
        start_time=datetime(2026, 1, 1, tzinfo=UTC),
        end_time=datetime(2026, 1, 1, 0, 1, tzinfo=UTC),
        num_timecodes=60,
        filename="",
        timestamp=ReplayTimestamp(*([0] * 8)),
        version="",
        build_date="",
        metadata=ReplayMetadata(slots=[slot]),
    )
    replay = ReplayFile(
        header=header,
        chunks=[
            # A built unit votes the faction by its Side; the hero recruit needs the roster.
            chunk(0x417, [(_T.Boolean, False), (_T.Integer, 1), (_T.Integer, 0)]),
            chunk(0x417, [(_T.Boolean, True), (_T.Integer, 1), (_T.Integer, 0)]),
        ],
    )
    data = GameData(
        object_order=["GondorSoldier"],
        objects={"GondorSoldier": _obj({"Side": "Men", "KindOf": "SELECTABLE"})},
        specialpowers=[],
        sciences=[],
        upgrades=[],
        displaynames={},
        faction_labels=["FactionMen"],
        faction_sides=["Men"],
        hero_rosters=[["CreateAHero", "AmrothImrahil"]],
        hero_build_times={"AmrothImrahil": 30.0},
    )
    game = player_games(replay, data)[0]
    assert game.faction == "FactionMen"
    assert dict(game.stats.heroes) == {"AmrothImrahil": 1}
    assert not game.stats.fortress_hero_slots


def test_unresolved_slots_keep_the_generic_line_and_bucket():
    # No roster for the faction: stats keep raw slot numbers, narration the generic line.
    data = GameData(
        object_order=[],
        objects={},
        specialpowers=[],
        sciences=[],
        upgrades=[],
        displaynames={},
    )
    replay = parse_replay_from_path(FIXTURES / "hero recruit 2.BfME2Replay")
    per = compute_stats(replay, data)[0]
    assert dict(per.fortress_hero_slots) == {1: 1, 2: 1, 4: 1}
    assert not per.heroes
    texts = [e.text for e in narrate(replay, data)]
    assert texts == [
        "recruits a fortress hero (command slot 1)",
        "recruits a fortress hero (command slot 2)",
        "recruits a fortress hero (command slot 4)",
    ]
