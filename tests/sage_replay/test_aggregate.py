"""Corpus aggregation: player-game outcomes from the winner heuristic, per-faction
pick tables with win-loss records and first-purchase timings. Synthetic GameData and
chunks - no game install needed - plus the fixture-backed patch-fingerprint gate."""

import argparse
import json
import re
from datetime import UTC, datetime
from pathlib import Path

import pytest

from sage_replay import build_orders
from sage_replay.__main__ import add_aggregate_command, main
from sage_replay.aggregate import (
    _BUILD_MIN_GAMES,
    _SCIENCE_LINE_MIN_SHARE,
    UNRESOLVED_FACTION,
    ChoiceStat,
    Corpus,
    FactionAggregate,
    PlayerGame,
    _faction_summary,
    _heatmap_block,
    _html_tiles,
    _timeline_block,
    aggregate,
    collect,
    command_point_weights,
    patch_groups,
    player_games,
    render_aggregate,
    render_aggregate_html,
    render_aggregate_markdown,
    render_index_html,
    version_groups,
    version_labels,
)
from sage_replay.narrate import GameData, _command_points, _upgrade_tables
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
from sage_replay.stats import PlayerStats, StatEvent
from sage_replay.winner import infer_winner

_T = OrderArgumentType


class _obj:
    def __init__(self, fields: dict) -> None:
        self._fields = fields


def _data() -> GameData:
    return GameData(
        object_order=["Barracks", "CPBounty"],
        objects={
            "Barracks": _obj({"KindOf": "STRUCTURE SELECTABLE"}),
            "CPBounty": _obj({"KindOf": "PRELOAD"}),  # a CPObject-like system purchase
        },
        specialpowers=[],
        sciences=["SCIENCE_One", "SCIENCE_Two"],
        upgrades=["Upgrade_Economy", "Upgrade_ForgedBlades"],  # id = 0-based index + 3
        displaynames={},
        faction_labels=["Rohan", "Isengard"],
    )


# The upgrade whitelist the tests aggregate with (only Upgrade_Economy makes the tables).
_TRACKED = frozenset({"Upgrade_Economy"})


def _chunk(order_type: int, args: list, *, timecode: int = 0, number: int = 3) -> ReplayChunk:
    order = Order(player_index=number - 3, order_type=order_type)
    order.arguments = [OrderArgument(t, v) for t, v in args]
    return ReplayChunk(timecode=timecode, order_type=order_type, number=number, order=order)


def _replay(chunks: list[ReplayChunk], *, pov: int = -1) -> ReplayFile:
    slots = [
        ReplaySlot(slot_type=ReplaySlotType.Human, human_name=f"Player{i}", faction=i)
        for i in range(2)
    ]
    header = ReplayHeader(
        game_type=ReplayGameType.Bfme2,
        start_time=datetime(2026, 1, 1, tzinfo=UTC),
        end_time=datetime(2026, 1, 1, 0, 1, tzinfo=UTC),
        num_timecodes=60,  # 1 frame per second
        filename="synthetic",
        timestamp=ReplayTimestamp(*([0] * 8)),
        version="",
        build_date="",
        metadata=ReplayMetadata(slots=slots),
        local_player_index=pov,
    )
    return ReplayFile(header=header, chunks=chunks)


def _science(science_id: int, *, timecode: int, number: int = 3) -> ReplayChunk:
    return _chunk(
        0x414, [(_T.Integer, 3), (_T.Integer, science_id)], timecode=timecode, number=number
    )


def _recruit(object_id: int, *, timecode: int, number: int = 3) -> ReplayChunk:
    return _chunk(
        0x417,
        [(_T.Boolean, False), (_T.Integer, object_id), (_T.Integer, 0)],
        timecode=timecode,
        number=number,
    )


# Player1 concedes: Player0 (Rohan) wins after building a Barracks, buying SCIENCE_One,
# researching one tracked and one untracked upgrade, and purchasing the CP-style
# CPBounty twice.
_REPLAY_A = _replay(
    [
        _chunk(0x419, [(_T.Integer, 1)], timecode=5),
        _recruit(2, timecode=7),  # first CPBounty purchase
        _science(1, timecode=9),
        _chunk(0x415, [(_T.Integer, 3)], timecode=15),  # Upgrade_Economy (tracked)
        _chunk(0x415, [(_T.Integer, 4)], timecode=16),  # Upgrade_ForgedBlades (untracked)
        _chunk(0x417, [(_T.Boolean, True), (_T.Integer, 2)], timecode=11),  # fortress hero
        _science(2, timecode=12, number=4),
        _recruit(2, timecode=40),  # second CPBounty purchase
        _chunk(0x448, [(_T.Boolean, True)], timecode=50, number=4),  # Player1 leaves
        _chunk(0x44A, [], timecode=60),  # Player0 present at the end
    ]
)

# Player0 concedes after buying SCIENCE_One later than in replay A: Isengard wins.
_REPLAY_B = _replay(
    [
        _science(1, timecode=20),
        _chunk(0x448, [(_T.Boolean, True)], timecode=30),  # Player0 leaves
        _chunk(0x44A, [], timecode=60, number=4),
    ]
)

# Nobody leaves before the recording ends: both outcomes stay undetermined.
_REPLAY_C = _replay(
    [
        _science(2, timecode=10),
        _chunk(0x44A, [], timecode=60),
        _chunk(0x44A, [], timecode=60, number=4),
    ]
)


def test_player_games_outcomes_and_factions():
    games = {g.player: g for g in player_games(_REPLAY_A, _data(), source="a.rep")}
    assert games["Player0"].faction == "Rohan"
    assert games["Player0"].outcome == "won"
    assert games["Player1"].faction == "Isengard"
    assert games["Player1"].outcome == "lost"
    assert games["Player0"].replay == "a.rep"
    assert games["Player0"].duration == 60.0

    undetermined = player_games(_REPLAY_C, _data())
    assert {g.outcome for g in undetermined} == {"undetermined"}


def test_aggregate_pick_tables():
    data = _data()
    games = [g for replay in (_REPLAY_A, _REPLAY_B, _REPLAY_C) for g in player_games(replay, data)]
    by_faction = {
        agg.faction: agg
        for agg in aggregate(
            games, tracked_upgrades=_TRACKED, tracked_purchases=frozenset({"CPBounty"})
        )
    }

    rohan = by_faction["Rohan"]
    assert (rohan.games, rohan.wins, rohan.losses, rohan.undetermined) == (3, 1, 1, 1)
    assert rohan.win_rate == 0.5

    # SCIENCE_One was bought in two Rohan games (one won, one lost) at 9s and 20s.
    one = rohan.sciences["SCIENCE_One"]
    assert (one.games, one.wins, one.losses, one.total) == (2, 1, 1, 2)
    assert one.median_first == 14.5
    # SCIENCE_Two only appears in the undetermined game: no decided record.
    two = rohan.sciences["SCIENCE_Two"]
    assert (two.games, two.wins, two.losses) == (1, 0, 0)
    assert two.win_rate is None
    assert rohan.first_science["SCIENCE_One"].games == 2

    barracks = rohan.buildings["Barracks"]
    assert (barracks.games, barracks.wins, barracks.losses, barracks.total) == (1, 1, 0, 1)
    assert barracks.first_times == [5.0]
    # The 0x417 flag=True recruit folds into the heroes table under a slot label.
    assert rohan.heroes["fortress hero (command slot 2)"].games == 1

    # Upgrade researches only make the table when the caller tracks them.
    economy = rohan.upgrades["Upgrade_Economy"]
    assert (economy.games, economy.wins, economy.total) == (1, 1, 1)
    assert economy.first_times == [15.0]
    assert "Upgrade_ForgedBlades" not in rohan.upgrades
    # Without a tracked set (the default), no upgrade gets a row at all.
    untracked = {agg.faction: agg for agg in aggregate(games)}
    assert not untracked["Rohan"].upgrades

    # A tracked `other` purchase is numbered per instance: the two CPBounty purchases of
    # replay A become CPBounty1/CPBounty2 rows with their own clocks, not one row with
    # total 2.
    assert "CPBounty" not in rohan.other
    assert (rohan.other["CPBounty1"].games, rohan.other["CPBounty1"].total) == (1, 1)
    assert rohan.other["CPBounty1"].first_times == [7.0]
    assert rohan.other["CPBounty2"].first_times == [40.0]
    # Untracked (the default), the same purchases aggregate as one ordinary pick-rate row.
    plain = untracked["Rohan"].other["CPBounty"]
    assert (plain.games, plain.total) == (1, 2)
    assert plain.first_times == [7.0]
    assert "CPBounty1" not in untracked["Rohan"].other

    isengard = by_faction["Isengard"]
    assert (isengard.games, isengard.wins, isengard.losses) == (3, 1, 1)
    assert isengard.sciences["SCIENCE_Two"].losses == 1


def test_hero_counts_once_at_first_fielding():
    # A hero re-recruited after dying (or clicked several times) is a revive, not a new pick:
    # the aggregate keeps only its first fielding, so the row reads games=1, total=1 with the
    # earliest recruit's clock - never games=1 with an inflated total.
    replay = _replay(
        [
            _chunk(0x417, [(_T.Boolean, True), (_T.Integer, 2)], timecode=11),  # first fielding
            _chunk(0x417, [(_T.Boolean, True), (_T.Integer, 2)], timecode=90),  # revive
            _chunk(0x448, [(_T.Boolean, True)], timecode=95, number=4),  # Player1 concedes
            _chunk(0x44A, [], timecode=100),  # Player0 present at the end -> Rohan wins
        ]
    )
    rohan = {a.faction: a for a in aggregate(player_games(replay, _data()))}["Rohan"]
    hero = rohan.heroes["fortress hero (command slot 2)"]
    assert (hero.games, hero.total) == (1, 1)
    assert hero.first_times == [11.0]


def test_outpost_milestone_named_by_unpacked_base():
    # A plot unpack whose CastleBehavior yields a `*_outpost` base for the issuing player's
    # Side is the standard-outpost claim: it pools into the faction's `outpost` milestone
    # (median unpack clock + how many games claimed one), on top of its ordinary building row.
    data = _data()
    data.faction_sides = ["Rohan", "Isengard"]
    data.castle_bases["Barracks"] = {"rohan": "rohan_outpost"}
    replay = _replay(
        [
            _chunk(0x419, [(_T.Integer, 1)], timecode=12),  # Player0 unpacks the Rohan outpost
            _chunk(0x448, [(_T.Boolean, True)], timecode=30, number=4),  # Player1 concedes
            _chunk(0x44A, [], timecode=60),  # Player0 present at the end -> Rohan wins
        ]
    )
    by_faction = {a.faction: a for a in aggregate(player_games(replay, data))}
    rohan = by_faction["Rohan"]
    # The unpack still gets its ordinary building row...
    assert "Barracks (unpacks rohan_outpost)" in rohan.buildings
    # ...and folds into the milestone, which is labelled by the unpacked base so the base can
    # be given a custom name of its own.
    assert rohan.outpost is not None
    assert rohan.outpost.label == "rohan_outpost"
    assert (rohan.outpost.games, rohan.outpost.total, rohan.outpost.wins) == (1, 1, 0 + 1)
    assert rohan.outpost.first_times == [12.0]
    # The base name flows into the summary line and the HTML tile, and is shown through
    # `translate`, so a hand-given name for the base appears in the report.
    named = {"rohan_outpost": "Exile Camp"}.get
    assert "outpost rohan_outpost ~0:12 (1/1)" in _faction_summary(rohan)
    assert "outpost Exile Camp ~0:12 (1/1)" in _faction_summary(rohan, named)
    # The stat tiles only carry Games/Record/Win rate/Median length - the outpost milestone
    # (like the undetermined count) lives in the summary line above, not its own tile.
    assert "Exile Camp" not in _html_tiles(rohan)

    assert rohan.to_dict()["outpost"]["label"] == "rohan_outpost"

    # A faction that never unpacks a standard outpost keeps the milestone empty/null.
    isengard = by_faction["Isengard"]
    assert isengard.outpost is None
    assert isengard.to_dict()["outpost"] is None
    assert "outpost" not in _faction_summary(isengard)
    # No "Std outpost" or "Undetermined" tile at all, decided or not.
    assert "Std outpost" not in _html_tiles(isengard)
    assert "Undetermined" not in _html_tiles(isengard)


def test_matchup_tables():
    data = _data()
    games = [g for replay in (_REPLAY_A, _REPLAY_B, _REPLAY_C) for g in player_games(replay, data)]
    # Every player-game knows the enemy factions it faced (2-player FFA: the other slot).
    assert all(g.opponents == ("Isengard",) for g in games if g.faction == "Rohan")

    # Without the flag (the default), no matchup sub-aggregates are built.
    assert not aggregate(games)[0].matchups

    by_faction = {agg.faction: agg for agg in aggregate(games, matchups=True)}
    rohan_vs_isengard = by_faction["Rohan"].matchups["Isengard"]
    # All three Rohan games were against Isengard, so the matchup mirrors the faction
    # block: same record, same pick tables.
    assert (rohan_vs_isengard.games, rohan_vs_isengard.wins, rohan_vs_isengard.losses) == (
        3,
        1,
        1,
    )
    assert rohan_vs_isengard.buildings["Barracks"].games == 1
    assert rohan_vs_isengard.sciences["SCIENCE_One"].median_first == 14.5

    # The matchup blocks render after the faction's own sections.
    corpus = Corpus(games=games, replays=3)
    text = "\n".join(render_aggregate(corpus, list(by_faction.values())))
    assert "-- vs Isengard" in text
    markdown = "\n".join(render_aggregate_markdown(corpus, aggregate(games, matchups=True)))
    assert "### vs Isengard - 3 games: 1-1" in markdown
    assert "#### Sciences" in markdown
    payload = by_faction["Rohan"].to_dict()
    assert payload["matchups"]["Isengard"]["games"] == 3


def test_refine_faction_flows_to_factions_and_opponents():
    data = _data()
    # A refiner keyed on the player's own stats: anyone who bought a science gets a mark. The
    # game/map arguments (for map-scoped refinements) are part of the signature but unused here.
    refiner = lambda label, stats, data, map_file: (  # noqa: E731
        f"{label} (opener)" if stats.sciences else label
    )

    games = {g.player: g for g in player_games(_REPLAY_A, data, refine_faction=refiner)}
    # Player0 bought a science; Player1 (number=4) bought one too in replay A.
    assert games["Player0"].faction == "Rohan (opener)"
    assert games["Player0"].opponents == ("Isengard (opener)",)
    assert games["Player1"].faction == "Isengard (opener)"
    assert games["Player1"].opponents == ("Rohan (opener)",)


def test_power_casts_aggregate_with_faction_aware_relabel():
    # Special-power casts aggregate as a `powers` pick category, but only for the caller's
    # tracked set (matched on the relabelled name); a `relabel_power` hook renames a shared
    # power per caster Side, so it groups under different labels for each faction.
    data = _data()
    data.specialpowers = ["SpecialAbilityShared"]
    data.faction_sides = ["RohanSide", "IsengardSide"]

    def relabel(side, power):
        return f"Rohan:{power}" if side == "RohanSide" else power

    replay = _replay(
        [
            _chunk(0x410, [(_T.Integer, 1), (_T.Integer, 0)], timecode=5),  # Player0 / Rohan
            _chunk(0x410, [(_T.Integer, 1), (_T.Integer, 0)], timecode=6, number=4),  # Player1
        ]
    )
    games = player_games(replay, data, relabel_power=relabel)
    tracked = frozenset({"Rohan:SpecialAbilityShared", "SpecialAbilityShared"})
    by_faction = {a.faction: a for a in aggregate(games, tracked_powers=tracked)}
    assert list(by_faction["Rohan"].powers) == ["Rohan:SpecialAbilityShared"]
    assert list(by_faction["Isengard"].powers) == ["SpecialAbilityShared"]

    # Without a tracked set (the default), no power gets a row at all.
    untracked = {a.faction: a for a in aggregate(games)}
    assert not untracked["Rohan"].powers
    assert not untracked["Isengard"].powers

    # A tracked power renders nested under the Units section as `powers_heading` (its caster is
    # a unit, not a recruitable hero), not as a flat top-level section. No unit was recruited
    # here (the casters built nothing), so a bare Units header still anchors the powers - they
    # never dangle under another category.
    corpus = Corpus(games=games, replays=1)
    factions = aggregate(games, tracked_powers=tracked)
    text = "\n".join(render_aggregate(corpus, factions, powers_heading="Loremaster"))
    assert "  Units  (games" in text
    assert text.index("Units") < text.index("Loremaster:")
    assert "Rohan:SpecialAbilityShared" in text
    markdown = "\n".join(render_aggregate_markdown(corpus, factions, powers_heading="Loremaster"))
    assert "### Units" in markdown  # the anchor heading
    assert "#### Loremaster" in markdown  # nested one level under it
    assert markdown.index("### Units") < markdown.index("#### Loremaster")
    html = "\n".join(render_aggregate_html(corpus, factions, powers_heading="Loremaster"))
    assert "<h3>Units</h3>" in html
    assert "<h4>Loremaster</h4>" in html
    assert html.index("<h3>Units</h3>") < html.index("<h4>Loremaster</h4>")


def test_horde_combines_hidden_unless_included():
    # Horde combines (0x423) are off by default and only aggregate with include_combines.
    data = _data()
    replay = _replay(
        [
            _chunk(0x423, [(_T.Integer, 999)], timecode=5),  # Player0 merges two hordes
            _chunk(0x44A, [], timecode=60),
            _chunk(0x44A, [], timecode=60, number=4),
        ]
    )
    games = player_games(replay, data)
    assert not aggregate(games)[0].combines  # default: no combines row
    by_faction = {a.faction: a for a in aggregate(games, include_combines=True)}
    assert by_faction["Rohan"].combines["horde combine"].games == 1


def test_random_slot_resolved_from_build_orders():
    # A lobby Random pick records an unresolvable faction id; the slot is labeled by the
    # Side its build orders vote for instead.
    data = _data()
    data.objects["Barracks"] = _obj({"KindOf": "STRUCTURE SELECTABLE", "Side": "RohanSide"})
    data.faction_sides = ["RohanSide", "IsengardSide"]
    replay = _replay([_recruit(1, timecode=5), _chunk(0x44A, [], timecode=60)])
    replay.header.metadata.players[0].faction = -1

    games = {g.player: g for g in player_games(replay, data)}
    assert games["Player0"].faction == "Rohan"
    assert games["Player1"].opponents == ("Rohan",)

    # A random slot whose orders build nothing side-attributable keeps the unknown label.
    replay.header.metadata.players[1].faction = -1
    games = {g.player: g for g in player_games(replay, data)}
    assert games["Player1"].faction == UNRESOLVED_FACTION


def test_collect_routes_unresolved_faction_to_warnings(monkeypatch):
    # A player-game whose faction can't be attributed (here a Random pick that builds nothing
    # side-voting; the Edain overlay's clan-less Dwarf is the same case) is listed as a
    # warning - it surfaces in the unparseable section - instead of pooling under a bogus
    # `?` faction. The resolvable slot's game is still collected.
    data = _data()
    replay = _replay([_chunk(0x44A, [], timecode=60)])
    replay.header.metadata.players[1].faction = -1  # Random, no orders -> unresolved

    monkeypatch.setattr(
        "sage_replay.aggregate.find_replays", lambda paths: [Path("game.BfME2Replay")]
    )
    monkeypatch.setattr("sage_replay.aggregate.parse_replay_from_path", lambda path: replay)

    corpus = collect([Path("game.BfME2Replay")], data)
    assert corpus.replays == 1
    assert [g.player for g in corpus.games] == ["Player0"]
    assert UNRESOLVED_FACTION not in {g.faction for g in corpus.games}
    assert corpus.warnings == ["game.BfME2Replay: Player1's faction unresolved"]
    # The unresolved player is scrubbed from the surviving game's opponents too, so `?`
    # never surfaces as a matchup column.
    assert UNRESOLVED_FACTION not in corpus.games[0].opponents
    assert corpus.games[0].opponents == ()


def test_player_games_prefers_given_outcomes_over_heuristic():
    data = _data()
    # The heuristic reads replay A as Player0 won / Player1 conceded; an explicit outcomes map
    # (the ladder sidecar's verdict) is authoritative and overrides it outright - here flipping
    # even a decided result, to prove the map wins rather than merely filling gaps.
    games = {
        g.player: g
        for g in player_games(_REPLAY_A, data, outcomes={"Player0": "lost", "Player1": "won"})
    }
    assert games["Player0"].outcome == "lost"
    assert games["Player1"].outcome == "won"


def test_collect_reads_sidecar_by_default(tmp_path, monkeypatch):
    data = _data()
    # An elimination ending the heuristic can only call undetermined (nobody leaves, no PoV).
    replay = _replay([_chunk(0x44A, [], timecode=60)])
    replay.header.metadata.players[0].team = 1
    replay.header.metadata.players[1].team = 0
    replay_path = tmp_path / "game.BfME2Replay"
    replay_path.write_bytes(b"")
    replay_path.with_name(replay_path.name + ".json").write_text(
        json.dumps(
            {
                "Players": [
                    {"Team": 0, "IsWinner": False, "IsObserver": False},
                    {"Team": 1, "IsWinner": True, "IsObserver": False},
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("sage_replay.aggregate.find_replays", lambda paths: [replay_path])
    monkeypatch.setattr("sage_replay.aggregate.parse_replay_from_path", lambda path: replay)

    # By default the sidecar decides the game the heuristic left open: Player0 is on the
    # winning team, Player1 on the losing one.
    corpus = collect([replay_path], data)
    assert {g.player: g.outcome for g in corpus.games} == {"Player0": "won", "Player1": "lost"}

    # `outcome_source=None` opts back out to the heuristic alone, which here decides nothing.
    corpus = collect([replay_path], data, outcome_source=None)
    assert {g.outcome for g in corpus.games} == {"undetermined"}


def test_winner_pov_assumption():
    data = _data()
    # An elimination-style ending (nobody leaves), recorded by Player0.
    replay = _replay(list(_REPLAY_C.chunks), pov=0)
    assert {g.outcome for g in player_games(replay, data)} == {"undetermined"}

    verdict = infer_winner(replay, assume_pov_won=True)
    assert (verdict.outcome, verdict.confidence) == ("decided", "assumed")
    assert verdict.winner_names == ["Player0"]

    games = {g.player: g for g in player_games(replay, data, assume_pov_won=True)}
    assert games["Player0"].outcome == "won"
    assert games["Player1"].outcome == "lost"

    # Explicit evidence beats the assumption: in Player1's own PoV recording of the game
    # they conceded, the leave order still makes them the loser.
    conceded = _replay(list(_REPLAY_A.chunks), pov=1)
    games = {g.player: g for g in player_games(conceded, data, assume_pov_won=True)}
    assert games["Player1"].outcome == "lost"
    assert games["Player0"].outcome == "won"

    # Without a point of view (no local player index) the assumption cannot apply.
    assert {g.outcome for g in player_games(_REPLAY_C, data, assume_pov_won=True)} == {
        "undetermined"
    }


def test_render_aggregate_smoke():
    data = _data()
    games = [g for r in (_REPLAY_A, _REPLAY_B) for g in player_games(r, data)]
    corpus = Corpus(games=games, replays=2)
    text = "\n".join(render_aggregate(corpus, aggregate(games)))
    assert "2 replays -> 4 player-games (4 with a decided outcome)" in text
    assert "== Rohan" in text
    assert "SCIENCE_One" in text
    assert "Barracks" in text


def test_render_aggregate_markdown():
    data = _data()
    games = [g for r in (_REPLAY_A, _REPLAY_B) for g in player_games(r, data)]
    corpus = Corpus(games=games, replays=2)
    lines = render_aggregate_markdown(corpus, aggregate(games, tracked_upgrades=_TRACKED))
    text = "\n".join(lines)
    assert lines[0] == "# Replay corpus stats"
    assert "## Rohan - 2 games: 1-1 (50%)" in text
    assert "| Science | Games | W-L | Win % | Median first | Total |" in text
    assert "| SCIENCE_One | 2 | 1-1 | 50% | 0:14 | 2 |" in text
    assert "| Barracks | 1 | 1-0 | 100% | 0:05 | 1 |" in text
    assert "| Upgrade_Economy | 1 | 1-0 | 100% | 0:15 | 1 |" in text
    # Empty pick categories produce no table (Rohan bought no units in these games).
    assert "| Unit |" not in text


def test_render_aggregate_html():
    data = _data()
    games = [g for r in (_REPLAY_A, _REPLAY_B) for g in player_games(r, data)]
    corpus = Corpus(games=games, replays=2)
    text = "\n".join(
        render_aggregate_html(corpus, aggregate(games, matchups=True), title="Rohan corpus")
    )
    assert text.startswith("<!doctype html>")
    assert "<title>Rohan corpus</title>" in text
    assert "2 replays -&gt; 4 player-games" in text or "2 replays -> 4 player-games" in text
    assert '<h2 id="f-rohan">Rohan</h2>' in text
    assert "SCIENCE_One" in text
    # The 50% win rate renders as a diverging bar of zero extent plus the number.
    assert '<span class="pct">50%</span>' in text
    # Matchup blocks are collapsible.
    assert "<details><summary>" in text
    assert "vs Isengard" in text
    # The matchup block shows how its picks differ from the faction overall: a delta column
    # in its tables and a win-rate swing in the summary (0 here - the only enemy is Isengard,
    # so the matchup equals the overall).
    assert ">vs overall</th>" in text
    assert 'class="delta' in text
    assert "&Delta;" in text
    # The top-level (non-matchup) faction tables carry no delta column.
    assert text.index(">vs overall</th>") > text.index("<details>")
    # Undecided-only choices show the muted dash, not a bar.
    assert '<span class="na">-</span>' in text or "100%" in text
    # Self-contained: no external fetches.
    assert "http" not in text.lower().replace("http-equiv", "")


def test_render_aggregate_html_annotate_badges_rows_by_owner():
    data = _data()
    games = [g for r in (_REPLAY_A, _REPLAY_B) for g in player_games(r, data)]
    corpus = Corpus(games=games, replays=2)
    calls = []

    def annotate(owner, label):
        calls.append((owner, label))
        return '<span class="badge">flag</span>' if label == "Barracks" else ""

    text = "\n".join(
        render_aggregate_html(corpus, aggregate(games, matchups=True), annotate=annotate)
    )
    # The owner passed is the faction the picks belong to - including inside a matchup
    # sub-table, where it is the parent faction (Rohan), never the enemy column.
    assert ("Rohan", "Barracks") in calls
    owners = {owner for owner, _ in calls}
    assert "Rohan" in owners and "Isengard" in owners
    # Rohan's Barracks is badged in both its own table and its vs-Isengard sub-table.
    assert text.count('<span class="badge">flag</span>') >= 2


def test_timeline_occurrences_collect_every_instance():
    # Two Barracks in one game: the timeline keeps both clocks, each paired with the match's
    # duration, while `first_times` still holds only the first-per-game clock the median-first
    # column reads.
    data = _data()
    replay = _replay(
        [
            _chunk(0x419, [(_T.Integer, 1)], timecode=5),
            _chunk(0x419, [(_T.Integer, 1)], timecode=25),
            _science(1, timecode=9),
            _chunk(0x448, [(_T.Boolean, True)], timecode=30, number=4),  # Player1 concedes
            _chunk(0x44A, [], timecode=60),
        ]
    )
    rohan = {a.faction: a for a in aggregate(player_games(replay, data))}["Rohan"]
    barracks = rohan.buildings["Barracks"]
    assert barracks.occurrences == [(5.0, 60.0), (25.0, 60.0)]
    assert barracks.first_times == [5.0]
    # Sciences collect occurrences too (a science is bought at most once per game, so this
    # game's SCIENCE_One contributes exactly one pair), and the JSON payload is still
    # unchanged by the new field regardless of category.
    assert rohan.sciences["SCIENCE_One"].occurrences == [(9.0, 60.0)]
    assert "occurrences" not in barracks.to_dict()
    assert "occurrences" not in rohan.sciences["SCIENCE_One"].to_dict()


def test_render_aggregate_html_timeline_graphs():
    data = _data()
    games = [g for r in (_REPLAY_A, _REPLAY_B) for g in player_games(r, data)]
    corpus = Corpus(games=games, replays=2)
    text = "\n".join(render_aggregate_html(corpus, aggregate(games, matchups=True), title="T"))
    # Sciences heatmaps claim ids before any Buildings timeline: factions render alphabetically
    # when tied on games (Isengard before Rohan), and Isengard never builds anything, so its
    # top-level and matchup Sciences heatmaps (g0, g1) are the only graphs it draws. Rohan's
    # top-level block then draws its Sciences heatmap (g2), its Buildings timeline (g3), and the
    # Other-purchases heatmap over its untracked CPBounty buys (g4); its matchup block repeats
    # the trio (g5, g6, g7).
    assert '<details class="timeline" data-graph="g3">' in text
    assert '<details class="timeline" open' not in text
    assert 'data-mode="pct"' in text and 'data-mode="abs"' in text
    assert '"occ":[[5.0,60.0]]' in text
    # The y-mode toggle ships all four modes with share as the default (the one marked on),
    # and the note starts as share's.
    assert '<button type="button" class="on" data-ymode="share">' in text
    for ymode in ("lifecycle", "count", "cumulative"):
        assert f'data-ymode="{ymode}"' in text
        assert f'class="on" data-ymode="{ymode}"' not in text
    assert "share of visible series' orders per bin" in text
    # The old per-game rate is gone: the payload carries only the series, no game count.
    assert '"games":' not in text
    # Each row's label cell leads with a checked checkbox + swatch keyed to its series.
    assert 'data-graph="g3" data-series="0"' in text
    assert '<input type="checkbox" checked' in text
    # The label header carries the select-all, one per timeline graph (never for a heatmap).
    assert 'data-graph-all="g3"' in text and 'data-graph-all="g6"' in text
    # The matchup sub-table's graph draws its own id, so its checkboxes never cross-wire
    # with the faction-level graph over the same picks.
    assert '<details class="timeline" data-graph="g6">' in text
    # Sections without a timeline stay checkbox-free: the fortress-hero row (Heroes) and the
    # science rows carry plain label cells (Sciences gets a heatmap, not a per-row checkbox).
    assert "<td>fortress hero (command slot 2)</td>" in text
    assert "<td>SCIENCE_One</td>" in text
    # The graph renderer ships with the page.
    assert "details.timeline" in text and 'class="tl-data"' in text


class _game:
    """The two members `_command_points` reads off a loaded Game: the object table and the
    gamedata macro lookup (a non-macro token comes back unchanged, like the real one)."""

    def __init__(self, objects: dict, macros: dict | None = None) -> None:
        self.objects = objects
        self._macros = macros or {}

    def get_macro(self, token: str):
        return self._macros.get(token, token)


def test_command_points_resolution():
    parent = _obj({"CommandPoints": "COMMAND_POINTS_INFANTRY_15_HORDE"})
    child = _obj({})
    child.parent = parent  # a ChildObject with no CommandPoints of its own
    game = _game(
        {
            "PeasantHorde": parent,
            "PeasantHorde_Variant": child,
            "Hero": _obj({"CommandPoints": 90}),
            "SummonHorde": _obj({"KindOf": "SELECTABLE"}),  # no CP anywhere in the chain
            "Broken": _obj({"CommandPoints": "NOT_A_DEFINED_MACRO"}),
        },
        macros={"COMMAND_POINTS_INFANTRY_15_HORDE": 15},
    )
    assert _command_points(game, "PeasantHorde") == 15  # macro-resolved
    assert _command_points(game, "PeasantHorde_Variant") == 15  # inherited through the chain
    assert _command_points(game, "Hero") == 90  # a literal value
    assert _command_points(game, "SummonHorde") is None
    assert _command_points(game, "Broken") is None  # an unresolvable token, not a crash
    assert _command_points(game, "Missing") is None


def test_upgrade_tables():
    upgrades = {
        "Upgrade_Tech": _obj({"Type": "PLAYER", "DisplayName": "UPGRADE:Tech"}),
        "Upgrade_Gear": _obj({"Type": "OBJECT", "DisplayName": "UPGRADE:Gear"}),
        "Upgrade_Repeated": _obj({"Type": ["OBJECT", "PLAYER"]}),  # a repeated field: last wins
        "Upgrade_Placeholder": _obj({}),  # no Type at all: never a player research
        "Upgrade_Unstrung": _obj({"Type": "player", "DisplayName": "UPGRADE:Missing"}),
    }
    strings = {"UPGRADE:TECH": "Steel Weapons", "UPGRADE:GEAR": "Forged Blades"}
    player, displaynames = _upgrade_tables(upgrades, strings)
    # Type matches case-insensitively; only an explicit PLAYER joins the tracked-by-default set.
    assert player == {"Upgrade_Tech", "Upgrade_Repeated", "Upgrade_Unstrung"}
    # DisplayNames resolve for every upgrade the string table covers, whatever its Type, and
    # independently of the localize flag - the aggregate names flow seeds display strings here.
    assert displaynames == {"Upgrade_Tech": "Steel Weapons", "Upgrade_Gear": "Forged Blades"}


def test_command_point_weights():
    data = GameData(
        object_order=[],
        objects={},
        specialpowers=[],
        sciences=[],
        upgrades=[],
        displaynames={"TwinA": "Twin", "TwinB": "Twin"},
        faction_labels=[],
        command_points={"PeasantHorde": 15, "FreeSummon": 0, "TwinA": 30, "TwinB": 45},
    )
    weight = command_point_weights(data)
    assert weight("PeasantHorde") == 15
    assert weight("FreeSummon") == 0  # weightless, not missing
    assert weight("Twin") == 45  # two templates behind one display label: the largest CP wins
    assert weight("<object id 7?>") == 0


def test_units_timeline_cp_share_mode():
    data = GameData(
        object_order=["Barracks", "Peasant"],
        objects={
            "Barracks": _obj({"KindOf": "STRUCTURE SELECTABLE"}),
            "Peasant": _obj({"KindOf": "SELECTABLE"}),
        },
        specialpowers=[],
        sciences=[],
        upgrades=[],
        displaynames={},
        faction_labels=["Rohan", "Isengard"],
        command_points={"Peasant": 20},
    )
    replay = _replay(
        [
            _chunk(0x419, [(_T.Integer, 1)], timecode=5),
            _recruit(2, timecode=10),
            _chunk(0x448, [(_T.Boolean, True)], timecode=30, number=4),  # Player1 concedes
            _chunk(0x44A, [], timecode=60),
        ]
    )
    games = list(player_games(replay, data))
    corpus = Corpus(games=games, replays=1)
    factions = aggregate(games)
    # Without a weight hook the y-toggle stays as before - no CP-share button anywhere
    # (the script always ships the mode; only the button and the weights gate it).
    plain = "\n".join(render_aggregate_html(corpus, factions, title="T"))
    assert 'data-ymode="cpshare"' not in plain
    text = "\n".join(
        render_aggregate_html(corpus, factions, title="T", weight=command_point_weights(data))
    )
    # Only the Units timeline gains the mode and its per-series cp weight; the Buildings
    # timeline on the same page stays unweighted (structures occupy no command points).
    assert text.count('<button type="button" data-ymode="cpshare">CP share</button>') == 1
    assert text.count('"cp":') == 1
    assert '"label":"Peasant","occ":[[10.0,60.0]],"cp":20' in text
    # The mode ships its note text and tooltip readout with the graph script (the note
    # lives only in the script's NOTES map, apostrophe still JS-escaped).
    assert "share of visible series\\' command points per bin" in text
    assert "of CP spent" in text
    # A label containing `</script>` must not close the payload element early: the block's
    # only `</script>` is its own closing tag, and the payload still parses as JSON (the
    # escaped `<\/` is a legal JSON escape for `/`).
    choice = ChoiceStat(label="Evil</script>x")
    choice.occurrences.append((1.0, 60.0))
    block = _timeline_block([choice], "g9", lambda label: label)
    payload = block.split('class="tl-data">', 1)[1].split("</script>", 1)[0]
    assert json.loads(payload)["series"][0]["label"] == "Evil</script>x"


def test_render_aggregate_html_science_heatmap():
    data = _data()
    games = [g for r in (_REPLAY_A, _REPLAY_B) for g in player_games(r, data)]
    corpus = Corpus(games=games, replays=2)
    text = "\n".join(render_aggregate_html(corpus, aggregate(games, matchups=True), title="T"))
    # The Sciences section carries a purchase-timing heatmap, drawing an id from the same
    # page-wide counter as every Buildings/Units timeline but never sharing one with them.
    heatmap_ids = set(re.findall(r'<details class="heatmap" data-graph="(g\d+)">', text))
    timeline_ids = set(re.findall(r'<details class="timeline" data-graph="(g\d+)">', text))
    assert heatmap_ids and timeline_ids
    assert heatmap_ids.isdisjoint(timeline_ids)
    assert 'class="hm-data"' in text
    payloads = [
        json.loads(chunk.split("</script>", 1)[0]) for chunk in text.split('class="hm-data">')[1:]
    ]
    assert any(s["label"] == "SCIENCE_One" for payload in payloads for s in payload["series"])
    # Only the axis toggle ships (no y-mode buttons, which mean nothing for a heatmap cell).
    assert '<span class="tl-note">each row shaded by where its own purchases fall</span>' in text
    # The heatmap script ships with the page.
    assert "details.heatmap" in text


def test_render_aggregate_html_upgrade_and_purchase_heatmaps():
    data = _data()
    games = [g for r in (_REPLAY_A, _REPLAY_B) for g in player_games(r, data)]
    factions = aggregate(
        games, tracked_upgrades=_TRACKED, tracked_purchases=frozenset({"CPBounty"})
    )
    rohan = next(a for a in factions if a.faction == "Rohan")
    # Upgrades and tracked `other` purchases collect heatmap occurrences like sciences do: the
    # tracked research keeps its clock, and each depth-numbered CPBounty row carries exactly its
    # own instance's clock (one per game by construction). None of it leaks into the JSON dump.
    assert rohan.upgrades["Upgrade_Economy"].occurrences == [(15.0, 60.0)]
    assert rohan.other["CPBounty1"].occurrences == [(7.0, 60.0)]
    assert rohan.other["CPBounty2"].occurrences == [(40.0, 60.0)]
    assert "occurrences" not in rohan.other["CPBounty1"].to_dict()

    corpus = Corpus(games=games, replays=2)
    text = "\n".join(render_aggregate_html(corpus, factions, title="T"))
    # Both sections draw purchase-timing heatmaps, each under its own summary blurb, and the
    # depth rows ride the payload as their own series.
    assert "when each upgrade is researched across match length" in text
    assert "when each purchase is made across match length" in text
    payloads = [
        json.loads(chunk.split("</script>", 1)[0]) for chunk in text.split('class="hm-data">')[1:]
    ]
    labels = {s["label"] for payload in payloads for s in payload["series"]}
    assert {"Upgrade_Economy", "CPBounty1", "CPBounty2"} <= labels


def test_science_rows_carry_no_series_key():
    data = _data()
    games = [g for r in (_REPLAY_A, _REPLAY_B) for g in player_games(r, data)]
    corpus = Corpus(games=games, replays=2)
    text = "\n".join(render_aggregate_html(corpus, aggregate(games, matchups=True), title="T"))
    heatmap_ids = set(re.findall(r'<details class="heatmap" data-graph="(g\d+)">', text))
    assert heatmap_ids
    # A heatmap has no line to key a row to: no header select-all and no per-row checkbox
    # naming a heatmap id, unlike the timeline graphs' `data-graph-all` / `data-series` rows.
    for hid in heatmap_ids:
        assert f'data-graph-all="{hid}"' not in text
        assert f'data-graph="{hid}" data-series=' not in text
    # A science row's label cell stays plain - no leading checkbox/swatch.
    assert "<td>SCIENCE_One</td>" in text


def test_heatmap_payload_escapes_early_script_close():
    # Mirrors test_timeline_payload_escapes_early_script_close for the heatmap's own payload:
    # a label containing `</script>` must not close the element early, and the escaped `<\/`
    # is still a legal JSON escape for `/`.
    choice = ChoiceStat(label="Evil</script>x")
    choice.occurrences.append((1.0, 60.0))
    block = _heatmap_block([choice], "g9", lambda label: label, "when each science is bought")
    payload = block.split('class="hm-data">', 1)[1].split("</script>", 1)[0]
    assert json.loads(payload)["series"][0]["label"] == "Evil</script>x"


def test_science_heatmap_omitted_without_measurable_duration():
    # A replay with no chunk after timecode 0 leaves both players' match duration at 0.0 (no
    # heartbeat/leave to measure it by): the science pick still counts in the pick-rate table,
    # but with no match length to normalise against it contributes no heatmap occurrence, so
    # the Sciences section renders no heatmap block at all.
    data = _data()
    replay = _replay([_science(1, timecode=0)])
    games = player_games(replay, data)
    corpus = Corpus(games=games, replays=1)
    factions = aggregate(games)
    rohan = next(a for a in factions if a.faction == "Rohan")
    assert rohan.sciences["SCIENCE_One"].games == 1
    assert rohan.sciences["SCIENCE_One"].occurrences == []
    text = "\n".join(render_aggregate_html(corpus, factions, title="T"))
    assert '<details class="heatmap"' not in text
    assert "<td>SCIENCE_One</td>" in text


def test_render_index_html():
    data = _data()
    games = [g for r in (_REPLAY_A, _REPLAY_B) for g in player_games(r, data)]
    corpus = Corpus(games=games, replays=2, warnings=["broken.BfME2Replay: boom"])
    factions = aggregate(games, matchups=True)
    links = {"Rohan": "aggregate/rohan.html", "Isengard": "aggregate/isengard.html"}
    text = "\n".join(
        render_index_html(corpus, factions, links, title="My corpus", generated="2026-07-12 09:00")
    )
    assert text.startswith("<!doctype html>")
    assert "<title>My corpus</title>" in text
    # The corpus summary carries the build stamp.
    assert "generated 2026-07-12 09:00" in text
    # The leaderboard links each faction out to its page.
    assert '<a href="aggregate/rohan.html">Rohan</a>' in text
    assert '<a href="aggregate/isengard.html">Isengard</a>' in text
    # A prominent link to the combined report (default href).
    assert '<a class="nav" href="aggregate.html">' in text
    # The matchup matrix renders with tinted cells (both factions faced each other).
    assert "Matchup win rates" in text
    assert "color-mix(in srgb" in text
    # Each matchup cell shows the game count backing the win rate (2 games per pairing here),
    # and each row faction carries its total games next to its name.
    assert '<span class="n">2</span>' in text
    assert '<span class="gc">2</span>' in text
    # Unparseable files are listed in a collapsible block.
    assert "1 unparseable / unresolved" in text
    assert "broken.BfME2Replay: boom" in text
    # Self-contained: no external fetches.
    assert "http" not in text.lower().replace("http-equiv", "")


def test_render_index_matrix_leaves_mirror_diagonal_blank():
    # A faction that faced its own mirror: the diagonal cell is a 50%-by-construction
    # mirror (one side's win is the other's loss), so it renders as a muted dot rather
    # than a tinted cell carrying the meaningless 50%.
    data = _data()
    games = [g for r in (_REPLAY_A, _REPLAY_B) for g in player_games(r, data)]
    factions = aggregate(games, matchups=True)
    # Synthesize a Rohan-vs-Rohan mirror into Rohan's matchups.
    rohan = next(a for a in factions if a.faction == "Rohan")
    rohan.matchups["Rohan"] = FactionAggregate(faction="Rohan", games=4, wins=2, losses=2)
    text = "\n".join(render_index_html(Corpus(games=games, replays=2), factions, {}))
    # The mirror contributes no tinted cell and no 50% number to the matrix.
    assert '50%<span class="n">4</span>' not in text
    assert "Matchup win rates" in text  # the matrix still renders


def test_render_aggregate_html_extra_hook_appends_per_faction():
    data = _data()
    games = [g for r in (_REPLAY_A, _REPLAY_B) for g in player_games(r, data)]
    corpus = Corpus(games=games, replays=2)
    factions = aggregate(games)
    seen = []

    def extra(agg):
        seen.append(agg.faction)
        return [f'<div class="marker">replays for {agg.faction}</div>']

    text = "\n".join(render_aggregate_html(corpus, factions, extra=extra))
    # The hook is called once per faction and its lines land in the page.
    assert set(seen) == {"Rohan", "Isengard"}
    assert '<div class="marker">replays for Rohan</div>' in text
    # It is appended after the faction's own <h2> block.
    assert text.index('<h2 id="f-rohan">Rohan</h2>') < text.index("replays for Rohan")


def test_render_aggregate_html_contents_box():
    data = _data()
    games = [g for r in (_REPLAY_A, _REPLAY_B) for g in player_games(r, data)]
    corpus = Corpus(games=games, replays=2)
    factions = aggregate(games, matchups=True)

    # A multi-faction report: the contents box lists each faction, linking to its <h2>, and
    # sits ahead of the first faction block.
    multi = "\n".join(render_aggregate_html(corpus, factions))
    assert '<nav class="toc">' in multi
    assert '<a href="#f-rohan">Rohan</a>' in multi
    assert '<a href="#f-isengard">Isengard</a>' in multi
    assert multi.index('<nav class="toc">') < multi.index('<h2 id="f-rohan">')

    # A single-faction page: the contents box lists that faction's own sections, then the
    # Matchups block and (via the extra hook) the Replays list - every link resolving to an id
    # that is actually present on the page.
    rohan = [a for a in factions if a.faction == "Rohan"]
    single = "\n".join(
        render_aggregate_html(
            corpus, rohan, extra=lambda agg: ['<h3 id="replays">Replays (2)</h3>']
        )
    )
    assert '<a href="#matchups">Matchups</a>' in single
    assert '<a href="#replays">Replays</a>' in single
    assert '<h3 id="matchups">Matchups</h3>' in single
    toc = single[single.index('<nav class="toc">') : single.index("</nav>")]
    targets = re.findall(r'href="#([^"]+)"', toc)
    assert any(t.startswith("sec-") for t in targets)  # at least one pick section is listed
    for target in targets:
        assert f'id="{target}"' in single  # every contents link resolves


def test_render_index_html_without_matchups_omits_matrix():
    # An aggregation built without matchups has no matrix section to render.
    data = _data()
    games = [g for r in (_REPLAY_A, _REPLAY_B) for g in player_games(r, data)]
    corpus = Corpus(games=games, replays=2)
    text = "\n".join(render_index_html(corpus, aggregate(games), {}))
    assert "Matchup win rates" not in text
    assert "<h2>Factions</h2>" in text  # the leaderboard still renders


def test_translate_maps_code_names_to_display_strings():
    data = _data()
    games = [g for r in (_REPLAY_A, _REPLAY_B) for g in player_games(r, data)]
    corpus = Corpus(games=games, replays=2)
    factions = aggregate(games, matchups=True)
    names = {"Rohan": "Rohan (Riders)", "Barracks": "Barracks Hall", "SCIENCE_One": "First Science"}
    translate = lambda code: names.get(code) or code  # noqa: E731

    html = "\n".join(render_aggregate_html(corpus, factions, title="T", translate=translate))
    assert '<h2 id="f-rohan">Rohan (Riders)</h2>' in html
    # A mapped label renders its display string, not the raw code name (the buildings cell
    # leads with its timeline checkbox, so match the label against the cell's tail).
    assert ">Barracks Hall</td>" in html and ">Barracks</td>" not in html
    assert "<td>First Science</td>" in html
    # An unmapped code name (Isengard) falls back to itself.
    assert '<h2 id="f-isengard">Isengard</h2>' in html

    links = {"Rohan": "aggregate/rohan.html", "Isengard": "aggregate/isengard.html"}
    index = "\n".join(render_index_html(corpus, factions, links, translate=translate))
    # The leaderboard shows the display string but still links by the raw code name.
    assert '<a href="aggregate/rohan.html">Rohan (Riders)</a>' in index
    # An unmapped faction keeps its code name, still correctly linked.
    assert '<a href="aggregate/isengard.html">Isengard</a>' in index
    # Without a translate, labels stay as raw code names (default identity).
    plain = "\n".join(render_aggregate_html(corpus, factions, title="T"))
    assert '<h2 id="f-rohan">Rohan</h2>' in plain and ">Barracks</td>" in plain


def _bo_game(faction, outcome, steps, *, opponents=("Isengard",), duration=300.0):
    """A PlayerGame carrying a hand-built stats timeline, so a build-order tree can be exercised
    without threading a whole synthetic replay per game. `steps` is (seconds, category, label)."""
    events = [StatEvent(seconds, category, label) for seconds, category, label in steps]
    return PlayerGame(
        replay="r",
        player="p",
        faction=faction,
        outcome=outcome,
        duration=duration,
        stats=PlayerStats(player="p", events=events),
        opponents=opponents,
    )


# A common Rohan opening (Farm x2 -> Barracks -> Haldir) plus a rare divergent one that must be
# pruned. The Farm run-length-encodes to one step of count 2; the rare Smithy game holds the
# whole faction just above the share floor while staying under `_BUILD_MIN_GAMES`.
def _rohan_build_games():
    games = []
    for i in range(4):
        games.append(
            _bo_game(
                "Rohan",
                "won" if i < 3 else "lost",
                [
                    (5, "buildings", "Farm"),
                    (20, "buildings", "Farm"),
                    (40, "buildings", "Barracks"),
                    (250, "heroes", "Haldir"),
                ],
            )
        )
    games.append(_bo_game("Rohan", "won", [(5, "buildings", "Smithy")]))
    return games


def test_build_orders_tree_root_counts_and_prune():
    games = _rohan_build_games()
    rohan = {a.faction: a for a in aggregate(games)}["Rohan"]
    tree = rohan.build_orders
    assert tree is not None
    # The root counts every inserted game (the four common + the one rare), so a top-level
    # child's share is a share of the whole faction.
    assert tree.games == 5
    # The earliest step of every kept opening is the RLE'd Farm (count 2), surviving the prune;
    # the rare Smithy branch (1 game < _BUILD_MIN_GAMES) is dropped.
    assert ("buildings", "Farm") in tree.children
    assert ("buildings", "Smithy") not in tree.children
    farm = tree.children[("buildings", "Farm")]
    assert (farm.games, farm.median_count) == (4, 2)
    assert ("buildings", "Barracks") in farm.children
    # openings reads the top path back out, leaf last.
    top = build_orders.openings(tree, limit=8)[0]
    assert [n.label for n in top] == ["Farm", "Barracks", "Haldir"]
    assert top[-1].games == 4
    assert _BUILD_MIN_GAMES == 3


def test_build_orders_render_all_formats_and_matchups():
    games = _rohan_build_games()
    corpus = Corpus(games=games, replays=5)
    factions = aggregate(games, matchups=True)
    rohan = {a.faction: a for a in factions}["Rohan"]
    # matchups=True gives each matchup sub-aggregate its own tree.
    assert rohan.matchups["Isengard"].build_orders is not None
    assert rohan.matchups["Isengard"].build_orders.children

    text = "\n".join(render_aggregate(corpus, factions))
    assert "Build orders  (games - won-lost - win% - ~complete):" in text
    assert "Farm x2 -> Barracks -> Haldir" in text

    markdown = "\n".join(render_aggregate_markdown(corpus, factions))
    assert "### Build orders" in markdown
    assert "| Build order | Games | W-L | Win % | ~Complete |" in markdown
    assert "Farm x2 -> Barracks -> Haldir" in markdown

    # An `extra` (the per-faction replay list) so the build-order placement can be checked:
    # single faction -> the section carries its anchor, and it sits after the matchups and just
    # above the replays rather than leading the block.
    extra = lambda agg: ['<h3 id="replays">Replays</h3>']  # noqa: E731
    html = "\n".join(render_aggregate_html(corpus, factions, title="T", extra=extra))
    assert '<h3 id="sec-buildorders">Build orders</h3>' in html
    assert '<a href="#sec-buildorders">Build orders</a>' in html
    assert "Farm &times;2 &rarr; Barracks &rarr; Haldir" in html
    # Build orders now follow the pick sections and the matchups, and lead the replay list.
    assert html.index('id="sec-heroes"') < html.index('id="sec-buildorders"')
    assert html.index('id="matchups"') < html.index('id="sec-buildorders"')
    assert html.index('id="sec-buildorders"') < html.index('id="replays"')
    # A hero step in the tree pulls in the build-order variant of the extrapolation caveat
    # (scoped to hero steps, not the Heroes table's whole-section wording) right under the
    # faction's own heading - check within its section, since a matchup sub-block carries the
    # same note earlier on the page.
    own_section = html[html.index('id="sec-buildorders"') :]
    assert "Hero steps are extrapolated" in own_section
    # The Explorer ships its translated payload and the drawing script.
    assert '<details class="botree">' in html
    assert 'class="bo-data"' in html
    assert "details.botree" in html


def test_build_orders_science_annotates_leaf_and_renders_sciences_line():
    # Games differ only in *when* they bought the science; sciences never fork the eco tree, so
    # all five fold into one shared opening, and the leaf's science annotations aggregate the
    # differing clocks (median 20.0) for the text renderer's second line.
    science_clocks = [2.0, 15.0, 20.0, 25.0, 100.0]  # median 20.0
    games = [
        _bo_game(
            "Rohan",
            "won",
            [
                (5.0, "buildings", "Farm"),
                (sci_seconds, "sciences", "SCIENCE_A"),
                (40.0, "buildings", "Barracks"),
            ],
        )
        for sci_seconds in science_clocks
    ]
    corpus = Corpus(games=games, replays=len(games))
    factions = aggregate(games)
    rohan = {a.faction: a for a in factions}["Rohan"]
    tree = rohan.build_orders
    assert tree is not None

    top = build_orders.openings(tree, limit=8)
    assert len(top) == 1  # one shared eco opening - science never forks the tree
    assert [n.label for n in top[0]] == ["Farm", "Barracks"]  # eco-only path
    leaf = top[0][-1]
    assert leaf.games == len(games)
    assert leaf.sciences_taken["SCIENCE_A"] == science_clocks

    text = "\n".join(render_aggregate(corpus, factions))
    assert "Farm -> Barracks" in text
    assert "sciences: SCIENCE_A (0:20, 100%)" in text


def test_build_orders_html_payload_translates_labels():
    games = _rohan_build_games()
    corpus = Corpus(games=games, replays=5)
    factions = aggregate(games)
    names = {"Farm": "Farmstead", "Barracks": "Barracks Hall"}
    translate = lambda code: names.get(code) or code  # noqa: E731
    html = "\n".join(render_aggregate_html(corpus, factions, title="T", translate=translate))
    payload = html.split('class="bo-data">', 1)[1].split("</script>", 1)[0]
    data = json.loads(payload)
    # The payload is the root; its first child is the translated Farm step.
    labels = {child["label"] for child in data["children"]}
    assert "Farmstead" in labels
    assert data["games"] == 5  # the root still counts every inserted game after the prune


def test_build_orders_icicle_renders():
    games = _rohan_build_games()
    corpus = Corpus(games=games, replays=5)
    factions = aggregate(games, matchups=True)
    html = "\n".join(render_aggregate_html(corpus, factions, title="T"))
    # The build-order section leads with an icicle: a wrapper, its SVG host, and a JSON payload.
    assert 'class="bo-ice-wrap"' in html
    assert 'class="bo-ice"' in html
    assert 'class="ice-data"' in html
    # The drawing script ships exactly once (its `.bo-ice-wrap` querySelector marker) and renders
    # lazily as each wrap scrolls into view.
    assert html.count("querySelectorAll('.bo-ice-wrap')") == 1
    assert "IntersectionObserver" in html
    # The icicle is the section headline: it precedes the openings table within the section.
    section = html[html.index(">Build orders</") :]
    assert section.index('class="bo-ice-wrap"') < section.index("<th>Build order</th>")


def test_build_orders_icicle_legend_names_every_category():
    games = _rohan_build_games()
    corpus = Corpus(games=games, replays=5)
    factions = aggregate(games, matchups=True)
    html = "\n".join(render_aggregate_html(corpus, factions, title="T"))
    # Rohan's own tree plus its Isengard matchup each carry an icicle, each with its own legend
    # and its own science readout box.
    assert html.count('class="bo-ice-wrap"') >= 2
    assert html.count('class="bo-ice-wrap"') == html.count('class="ice-legend"')
    assert html.count('class="bo-ice-wrap"') == html.count('class="ice-sci"')
    assert "hover a step for its sciences" in html
    # Every legend names exactly the three eco categories, in tree order, each swatch tied to its
    # slot - the tree is eco-only, so sciences never earn a box, a slot, or a legend entry.
    for chunk in html.split('class="ice-legend"')[1:]:
        legend = chunk.split("</div>", 1)[0]
        assert legend.index("--s1") < legend.index("--s2") < legend.index("--s3")
        assert "buildings" in legend
        assert "units" in legend
        assert "heroes" in legend
        assert "sciences" not in legend
        assert "--s5" not in legend


def test_build_orders_icicle_payload_translates_labels():
    games = _rohan_build_games()
    corpus = Corpus(games=games, replays=5)
    factions = aggregate(games)
    names = {"Farm": "Farmstead", "Barracks": "Barracks Hall"}
    translate = lambda code: names.get(code) or code  # noqa: E731
    html = "\n".join(render_aggregate_html(corpus, factions, title="T", translate=translate))
    payload = html.split('class="ice-data">', 1)[1].split("</script>", 1)[0]
    data = json.loads(payload)
    labels = {child["label"] for child in data["children"]}
    assert "Farmstead" in labels
    assert data["games"] == 5
    # The faction's own icicle is non-diff: no top-level `diff` flag, no per-node `base_share`.
    assert "diff" not in data
    assert all("base_share" not in child for child in data["children"])


def _diverging_matchup_games():
    """Rohan opening Farm -> Barracks against Isengard (40 games) but the rare Smithy -> Rider
    against Mordor (4 games): the Smithy opening is too rare in the faction overall to survive its
    prune (4 < 0.10 * 44), so vs Mordor it reads as NEW, while vs Isengard the shared Farm opening
    reads as a share delta against the overall."""
    games = []
    for i in range(40):
        games.append(
            _bo_game(
                "Rohan",
                "won" if i % 2 else "lost",
                [(5, "buildings", "Farm"), (40, "buildings", "Barracks")],
                opponents=("Isengard",),
            )
        )
    for _ in range(4):
        games.append(
            _bo_game(
                "Rohan",
                "won",
                [(5, "buildings", "Smithy"), (30, "units", "Rider")],
                opponents=("Mordor",),
            )
        )
    return games


def test_build_orders_matchup_diff():
    games = _diverging_matchup_games()
    corpus = Corpus(games=games, replays=44)
    factions = aggregate(games, matchups=True)
    rohan = {a.faction: a for a in factions}["Rohan"]
    # The overall tree kept only the common Farm opening; the rare Smithy is pruned there but
    # survives inside its own matchup.
    assert rohan.build_orders is not None
    assert ("buildings", "Farm") in rohan.build_orders.children
    assert ("buildings", "Smithy") not in rohan.build_orders.children

    html = "\n".join(render_aggregate_html(corpus, factions, title="T"))
    body = html.split("</main>", 1)[0]  # exclude the appended scripts (which carry literal markup)

    # A matchup build-order openings table carries a `vs overall` column (its own header wording,
    # distinct from the pick tables'); the faction's own build-order table does not.
    bo_vs = (
        '~Complete</th><th title="opening share vs the faction overall, in points">vs overall</th>'
    )
    assert bo_vs in body
    assert "<th>Win rate</th><th>~Complete</th></tr></thead>" in body  # the own (non-diff) table
    # vs Mordor's Smithy opening is absent overall -> a NEW badge; vs Isengard's Farm opening is
    # shared -> a `_delta`-classed cell.
    assert '<span class="badge">NEW</span>' in body
    assert 'class="delta' in body

    # The matchup icicle/Explorer payloads diff (top-level flag) and carry a `base_share` on a
    # node whose path is shared with the overall (vs Isengard's Farm); the faction's own payload
    # is non-diff.
    ice = [chunk.split("</script>", 1)[0] for chunk in html.split('class="ice-data">')[1:]]
    payloads = [json.loads(p) for p in ice]
    diffed = [p for p in payloads if p.get("diff")]
    own = [p for p in payloads if not p.get("diff")]
    assert diffed and own

    def has_base_share(node):
        if node.get("base_share") is not None:
            return True
        return any(has_base_share(child) for child in node["children"])

    assert any(has_base_share(p) for p in diffed)
    for p in own:
        assert all("base_share" not in child for child in p["children"])


def test_build_depth_zero_disables_section():
    games = _rohan_build_games()
    corpus = Corpus(games=games, replays=5)
    factions = aggregate(games, build_depth=0, matchups=True)
    rohan = {a.faction: a for a in factions}["Rohan"]
    assert rohan.build_orders is None
    assert rohan.matchups["Isengard"].build_orders is None
    assert rohan.to_dict()["build_orders"] is None
    assert "Build orders" not in "\n".join(render_aggregate(corpus, factions))
    assert "Build orders" not in "\n".join(render_aggregate_markdown(corpus, factions))
    html = "\n".join(render_aggregate_html(corpus, factions, title="T"))
    assert "sec-buildorders" not in html
    assert 'class="bo-data"' not in html
    assert '<details class="botree">' not in html
    # The icicle goes with it: no rendered wrapper or payload (the drawing script, keyed off
    # `.bo-ice-wrap`, still ships but finds nothing to draw).
    assert 'class="bo-ice-wrap"' not in html
    assert 'class="ice-data"' not in html


def test_build_orders_to_dict_roundtrips():
    games = _rohan_build_games()
    rohan = {a.faction: a for a in aggregate(games, matchups=True)}["Rohan"]
    payload = rohan.to_dict()["build_orders"]
    assert payload is not None
    assert payload["games"] == 5
    assert any(child["label"] == "Farm" for child in payload["children"])
    # A matchup sub-aggregate carries its own nested tree in its own to_dict.
    assert rohan.to_dict()["matchups"]["Isengard"]["build_orders"] is not None


def _rohan_science_games():
    """4 games with a common eco opening (Farm -> Barracks -> Haldir) that also buys SCIENCE_A,
    one game with a rare eco opening (Smithy) and no science purchases at all, and one game on
    that same rare eco opening with a science - so a game whose eco path gets pruned still
    annotates every node that path visited before pruning drops it, taking those annotations
    (here, one too rare to itself survive) along with the branch."""
    games = []
    for i in range(4):
        games.append(
            _bo_game(
                "Rohan",
                "won" if i < 3 else "lost",
                [
                    (5, "buildings", "Farm"),
                    (40, "buildings", "Barracks"),
                    (60, "sciences", "SCIENCE_A"),
                    (250, "heroes", "Haldir"),
                ],
            )
        )
    games.append(_bo_game("Rohan", "won", [(5, "buildings", "Smithy")]))  # no science at all
    games.append(
        _bo_game("Rohan", "won", [(5, "buildings", "Smithy"), (10, "sciences", "SCIENCE_RARE")])
    )
    return games


def test_build_orders_science_annotation_survives_prune_and_root_never_annotated():
    games = _rohan_science_games()
    rohan = {a.faction: a for a in aggregate(games, matchups=True)}["Rohan"]
    tree = rohan.build_orders
    assert tree is not None
    # The root counts every inserted game, including the two on the pruned Smithy opening, but
    # is never itself annotated.
    assert tree.games == 6
    assert tree.sciences_taken == {}
    # The rare Smithy eco branch (2 games < _BUILD_MIN_GAMES) does not survive pruning.
    assert ("buildings", "Smithy") not in tree.children

    farm = tree.children[("buildings", "Farm")]
    barracks = farm.children[("buildings", "Barracks")]
    haldir = barracks.children[("heroes", "Haldir")]
    # SCIENCE_A rides as an annotation on every node its own games' eco path visits, including
    # the leaf (Haldir) - one clock per game, all 4 games sharing the same 60.0s purchase.
    assert haldir.sciences_taken["SCIENCE_A"] == [60.0, 60.0, 60.0, 60.0]
    assert haldir.sciences_by_step["SCIENCE_A"] == [60.0, 60.0, 60.0, 60.0]  # by Haldir's own clock
    assert farm.sciences_taken["SCIENCE_A"] == [60.0, 60.0, 60.0, 60.0]
    assert "SCIENCE_A" not in farm.sciences_by_step  # not yet bought by Farm's own step clock (5.0)

    # SCIENCE_RARE only ever rode the pruned Smithy branch, so it never survives anywhere in the
    # tree - the pruned branch takes its own annotations along with it.
    def _walk(node: build_orders.BuildNode) -> None:
        assert "SCIENCE_RARE" not in node.sciences_taken
        assert "SCIENCE_RARE" not in node.sciences_by_step
        for child in node.children.values():
            _walk(child)

    _walk(tree)

    # matchups=True gives each matchup sub-aggregate its own annotated tree too.
    assert rohan.matchups["Isengard"].build_orders is not None
    assert rohan.matchups["Isengard"].build_orders.children

    assert "science_orders" not in rohan.to_dict()


# 5 identical games: Farm -> SCIENCE_A -> Barracks by clock, all sharing the same short eco
# prefix and science pick, so the eco tree stays a single Farm -> Barracks branch and SCIENCE_A
# annotates both nodes (bought after Farm's own clock, before Barracks's).
def _science_suffix_games():
    return [
        _bo_game(
            "Rohan",
            "won",
            [
                (5.0, "buildings", "Farm"),
                (20.0, "sciences", "SCIENCE_A"),
                (40.0, "buildings", "Barracks"),
            ],
        )
        for _ in range(5)
    ]


def test_no_science_paths_heading_anywhere():
    games = _rohan_science_games()
    corpus = Corpus(games=games, replays=len(games))
    factions = aggregate(games, matchups=True)

    assert "Science paths" not in "\n".join(render_aggregate(corpus, factions))
    assert "Science paths" not in "\n".join(render_aggregate_markdown(corpus, factions))
    assert "Science paths" not in "\n".join(render_aggregate_html(corpus, factions, title="T"))


def test_science_leaf_annotation_renders_second_line_in_all_formats():
    games = _science_suffix_games()
    corpus = Corpus(games=games, replays=len(games))
    factions = aggregate(games)

    text = "\n".join(render_aggregate(corpus, factions))
    assert "Farm -> Barracks" in text
    assert "      sciences: SCIENCE_A (0:20, 100%)" in text

    markdown = "\n".join(render_aggregate_markdown(corpus, factions))
    assert "Farm -> Barracks<br>sciences: SCIENCE_A (0:20, 100%)" in markdown

    html = "\n".join(render_aggregate_html(corpus, factions, title="T"))
    assert '<div class="bo-sci">sciences: SCIENCE_A (0:20, 100%)</div>' in html


def test_build_order_icicle_and_explorer_are_eco_only_with_science_readout_data():
    games = _science_suffix_games()
    corpus = Corpus(games=games, replays=len(games))
    factions = aggregate(games)
    rohan = {a.faction: a for a in factions}["Rohan"]
    assert rohan.build_orders is not None
    # The tree's canonical path is eco-only.
    top = build_orders.openings(rohan.build_orders, limit=8)[0]
    assert [n.category for n in top] == ["buildings", "buildings"]

    html = "\n".join(render_aggregate_html(corpus, factions, title="T"))

    def has_science_category(node):
        if node["category"] == "sciences":
            return True
        return any(has_science_category(child) for child in node["children"])

    ice_payloads = [
        json.loads(chunk.split("</script>", 1)[0]) for chunk in html.split('class="ice-data">')[1:]
    ]
    bo_payloads = [
        json.loads(chunk.split("</script>", 1)[0]) for chunk in html.split('class="bo-data">')[1:]
    ]
    # One icicle, one Explorer - no separate Science paths block - and no payload node anywhere
    # carries the sciences category (the tree is eco-only).
    assert len(ice_payloads) == 1
    assert len(bo_payloads) == 1
    assert not has_science_category(ice_payloads[0])
    assert not has_science_category(bo_payloads[0])

    # The Barracks leaf's by-step science annotation rides in the icicle's payload for the
    # readout, translated and clock-sorted; Farm's own by-step annotation is empty (SCIENCE_A was
    # bought after Farm's own clock), so Farm's payload carries no "sciences" key at all.
    farm_node = ice_payloads[0]["children"][0]
    barracks_node = farm_node["children"][0]
    assert farm_node["label"] == "Farm"
    assert "sciences" not in farm_node
    assert barracks_node["label"] == "Barracks"
    assert barracks_node["sciences"] == [{"label": "SCIENCE_A", "games": 5, "median_seconds": 20.0}]

    section = html[html.index(">Build orders</") :]
    assert "Farm &rarr; Barracks" in section
    assert "sciences: SCIENCE_A (0:20, 100%)" in section


def test_icicle_sciences_payload_translates_labels():
    games = _science_suffix_games()
    corpus = Corpus(games=games, replays=len(games))
    factions = aggregate(games)
    names = {"SCIENCE_A": "First Science"}
    translate = lambda code: names.get(code) or code  # noqa: E731
    html = "\n".join(render_aggregate_html(corpus, factions, title="T", translate=translate))
    payload = html.split('class="ice-data">', 1)[1].split("</script>", 1)[0]
    data = json.loads(payload)
    barracks_node = data["children"][0]["children"][0]
    assert barracks_node["sciences"] == [
        {"label": "First Science", "games": 5, "median_seconds": 20.0}
    ]


def _rohan_two_science_orders_games():
    """10 games sharing one eco opening (Farm -> Barracks), split evenly between two science
    picks bought at the same clock - sciences never fork the eco tree, so all ten land on one
    shared opening whose leaf annotates both picks at 50% each."""
    games = []
    for label in ("SCIENCE_A", "SCIENCE_B"):
        for _ in range(5):
            games.append(
                _bo_game(
                    "Rohan",
                    "won",
                    [
                        (5, "buildings", "Farm"),
                        (40, "buildings", "Barracks"),
                        (60, "sciences", label),
                    ],
                )
            )
    return games


def test_two_science_picks_over_same_eco_stay_one_opening_with_both_annotated():
    games = _rohan_two_science_orders_games()
    corpus = Corpus(games=games, replays=len(games))
    factions = aggregate(games)
    rohan = {a.faction: a for a in factions}["Rohan"]
    tree = rohan.build_orders
    assert tree is not None
    barracks = tree.children[("buildings", "Farm")].children[("buildings", "Barracks")]
    assert barracks.children == {}  # sciences never grow their own nodes

    top = build_orders.openings(tree, limit=8)
    assert len(top) == 1  # one shared eco opening, not split by science
    assert top[0][-1].games == 10

    assert set(barracks.sciences_taken) == {"SCIENCE_A", "SCIENCE_B"}
    assert len(barracks.sciences_taken["SCIENCE_A"]) == 5
    assert len(barracks.sciences_taken["SCIENCE_B"]) == 5

    text = "\n".join(render_aggregate(corpus, factions))
    # Both picks clear the 25% floor at 50% each, ordered alphabetically on a median-clock tie.
    assert "sciences: SCIENCE_A (1:00, 50%) -> SCIENCE_B (1:00, 50%)" in text


def _science_matchup_games():
    """40 games vs Isengard opening Farm, 4 vs Mordor opening Smithy, all buying SCIENCE_A right
    after: exercises a matchup's own leaf-level science annotation and its openings table's
    `vs overall` column together."""
    games = []
    for i in range(40):
        games.append(
            _bo_game(
                "Rohan",
                "won" if i % 2 else "lost",
                [(5, "buildings", "Farm"), (20, "sciences", "SCIENCE_A")],
                opponents=("Isengard",),
            )
        )
    for _ in range(4):
        games.append(
            _bo_game(
                "Rohan",
                "won",
                [(5, "buildings", "Smithy"), (20, "sciences", "SCIENCE_A")],
                opponents=("Mordor",),
            )
        )
    return games


def test_science_annotation_in_matchup_openings_table_with_vs_overall_column():
    games = _science_matchup_games()
    corpus = Corpus(games=games, replays=len(games))
    factions = aggregate(games, matchups=True)
    rohan = {a.faction: a for a in factions}["Rohan"]
    assert rohan.build_orders is not None
    farm = rohan.build_orders.children[("buildings", "Farm")]
    assert farm.children == {}  # sciences never grow their own nodes
    assert farm.sciences_taken["SCIENCE_A"] == [20.0] * 40

    isengard = rohan.matchups["Isengard"]
    assert isengard.build_orders is not None
    isengard_farm = isengard.build_orders.children[("buildings", "Farm")]
    assert isengard_farm.sciences_taken["SCIENCE_A"] == [20.0] * 40

    html = "\n".join(render_aggregate_html(corpus, factions, title="T"))
    body = html.split("</main>", 1)[0]
    blocks = body.split("<details><summary>")[1:]
    isengard_block = next(b for b in blocks if "Isengard" in b.split("</summary>", 1)[0])
    build_order_block = isengard_block.split(">Build orders<", 1)[1]
    assert (
        '<th title="opening share vs the faction overall, in points">vs overall</th>'
        in build_order_block
    )
    assert "sciences: SCIENCE_A (0:20, 100%)" in build_order_block


def test_science_line_omitted_when_below_min_share_floor():
    assert _SCIENCE_LINE_MIN_SHARE == 0.25
    # 8 games share one eco opening; SCIENCE_A rides on only 1 of them (12.5%), below the 25%
    # floor, so the row's science line is empty even though the leaf carries the annotation.
    games = [_bo_game("Rohan", "won", [(5, "buildings", "Farm")]) for _ in range(7)]
    games.append(
        _bo_game("Rohan", "won", [(5, "buildings", "Farm"), (20, "sciences", "SCIENCE_A")])
    )
    corpus = Corpus(games=games, replays=len(games))
    factions = aggregate(games)
    rohan = {a.faction: a for a in factions}["Rohan"]
    assert rohan.build_orders is not None
    farm = rohan.build_orders.children[("buildings", "Farm")]
    assert farm.sciences_taken["SCIENCE_A"] == [20.0]  # annotated, but under the floor

    text = "\n".join(render_aggregate(corpus, factions))
    assert "sciences:" not in text

    markdown = "\n".join(render_aggregate_markdown(corpus, factions))
    assert "<br>sciences:" not in markdown

    html = "\n".join(render_aggregate_html(corpus, factions, title="T"))
    assert 'class="bo-sci"' not in html


def test_aggregate_cli_accepts_build_depth():
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers()
    add_aggregate_command(subparsers)
    args = parser.parse_args(["aggregate", "x.rep", "--game", "g", "--build-depth", "0"])
    assert args.build_depth == 0
    default = parser.parse_args(["aggregate", "x.rep", "--game", "g"])
    assert default.build_depth == 12


# Fixture replays for the patch-fingerprint gate: two from the same install, one from
# another (their headers carry different data checksums).
_FIXTURES = Path(__file__).parent / "fixtures"
_SAME_PATCH = (
    _FIXTURES / "8e9c9d92-e901-4dc8-be23-d75525ba75c6.BfME2Replay",
    _FIXTURES / "c1086512-509f-406b-ac58-5691837ea032.BfME2Replay",
)
_OTHER_PATCH = _FIXTURES / "2v3.BfME2Replay"


def test_patch_groups():
    # A homogeneous corpus is one group, keyed by the shared fingerprint, holding the full
    # paths back (so a caller can feed a group straight back into `collect`).
    groups = patch_groups(_SAME_PATCH)
    assert list(groups.values()) == [list(_SAME_PATCH)]
    # Mixed installs split into their groups; an unparseable file is skipped, not fatal.
    mixed = patch_groups([*_SAME_PATCH, _OTHER_PATCH, _FIXTURES / "missing.BfME2Replay"])
    assert sorted(len(paths) for paths in mixed.values()) == [1, 2]


def test_aggregate_cli_rejects_mixed_patches(capsys):
    # The gate fires before any game root is resolved, so --game never gets touched.
    rc = main(["aggregate", str(_SAME_PATCH[0]), str(_OTHER_PATCH), "--game", "unused"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "not comparable" in err
    assert _OTHER_PATCH.name in err


def test_version_labels_creates_blank_entries(tmp_path):
    path = tmp_path / "versions.json"
    labels = version_labels(path, ["Bfme2 data=0xAAA", "Bfme2 data=0xBBB"])
    assert labels == {"Bfme2 data=0xAAA": "", "Bfme2 data=0xBBB": ""}
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert on_disk == labels
    assert path.read_text(encoding="utf-8").endswith("\n")


def test_version_labels_preserves_hand_fill_and_adds_new_blanks(tmp_path):
    path = tmp_path / "versions.json"
    path.write_text(
        json.dumps({"Bfme2 data=0xAAA": "Edain 4.8.4.3"}, indent=2) + "\n", encoding="utf-8"
    )
    labels = version_labels(path, ["Bfme2 data=0xAAA", "Bfme2 data=0xBBB"])
    assert labels == {"Bfme2 data=0xAAA": "Edain 4.8.4.3", "Bfme2 data=0xBBB": ""}
    assert json.loads(path.read_text(encoding="utf-8")) == labels


def test_version_labels_no_rewrite_when_nothing_changed(tmp_path):
    path = tmp_path / "versions.json"
    path.write_text(
        json.dumps({"Bfme2 data=0xAAA": "Edain 4.8.4.3"}, indent=2) + "\n", encoding="utf-8"
    )
    before = path.stat().st_mtime_ns
    labels = version_labels(path, ["Bfme2 data=0xAAA"])
    assert labels == {"Bfme2 data=0xAAA": "Edain 4.8.4.3"}
    assert path.stat().st_mtime_ns == before


def test_version_groups_merges_labels_sharing_a_version():
    groups = {
        "Bfme2 data=0xAAA": [Path("a1.BfME2Replay"), Path("a2.BfME2Replay")],
        "Bfme2 data=0xBBB": [Path("b1.BfME2Replay")],
    }
    # Both fingerprints are the same hand-labeled version (a hotfix that changed nothing
    # gameplay-visible), so they pool under its one entry.
    labels = {"Bfme2 data=0xAAA": "Edain 4.8.4.3", "Bfme2 data=0xBBB": "Edain 4.8.4.3"}
    merged = version_groups(groups, labels)
    assert merged == {
        "Edain 4.8.4.3": [
            Path("a1.BfME2Replay"),
            Path("a2.BfME2Replay"),
            Path("b1.BfME2Replay"),
        ]
    }


def test_version_groups_follows_label_order_not_hash_order():
    # Fingerprints whose sorted-hash order is the reverse of their versions.json order: the
    # merged versions must come out in label (file) order, so the build's install-switch
    # prompts follow the hand-arranged versions.json rather than the hash sort.
    groups = {
        "Bfme2 data=0xCCC": [Path("c1.BfME2Replay")],
        "Bfme2 data=0xAAA": [Path("a1.BfME2Replay")],
    }
    labels = {"Bfme2 data=0xCCC": "Lorienpatch 1.1", "Bfme2 data=0xAAA": "Lorienpatch 2.0"}
    merged = version_groups(groups, labels)
    assert list(merged) == ["Lorienpatch 1.1", "Lorienpatch 2.0"]


def test_version_groups_ignores_labels_absent_from_this_corpus():
    # versions.json may list historical versions this corpus's replays don't include; only the
    # present fingerprints appear, still in label order.
    groups = {"Bfme2 data=0xBBB": [Path("b1.BfME2Replay")]}
    labels = {
        "Bfme2 data=0xAAA": "Lorienpatch 1.1",
        "Bfme2 data=0xBBB": "Lorienpatch 1.2",
        "Bfme2 data=0xCCC": "Lorienpatch 1.3",
    }
    assert version_groups(groups, labels) == {"Lorienpatch 1.2": [Path("b1.BfME2Replay")]}


def test_version_groups_rejects_unlabeled_fingerprints():
    groups = {
        "Bfme2 data=0xAAA": [Path("a1.BfME2Replay")],
        "Bfme2 data=0xBBB": [Path("b1.BfME2Replay")],
    }
    labels = {"Bfme2 data=0xAAA": "Edain 4.8.4.3", "Bfme2 data=0xBBB": ""}
    with pytest.raises(ValueError, match="Bfme2 data=0xBBB"):
        version_groups(groups, labels)
