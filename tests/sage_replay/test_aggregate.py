"""Corpus aggregation: player-game outcomes from the winner heuristic, per-faction
pick tables with win-loss records and first-purchase timings. Synthetic GameData and
chunks - no game install needed - plus the fixture-backed patch-fingerprint gate."""

import json
import re
from datetime import UTC, datetime
from pathlib import Path

import pytest

from sage_replay.__main__ import main
from sage_replay.aggregate import (
    UNRESOLVED_FACTION,
    ChoiceStat,
    Corpus,
    FactionAggregate,
    _faction_summary,
    _heatmap_block,
    _html_tiles,
    _timeline_block,
    aggregate,
    collect,
    patch_groups,
    player_games,
    render_aggregate,
    render_aggregate_html,
    render_aggregate_markdown,
    render_index_html,
    version_groups,
    version_labels,
)
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
    # top-level block then draws its own Sciences heatmap (g2) before its Buildings timeline
    # (g3), and its matchup block repeats the pair (g4, g5).
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
    assert 'data-graph-all="g3"' in text and 'data-graph-all="g5"' in text
    # The matchup sub-table's graph draws its own id, so its checkboxes never cross-wire
    # with the faction-level graph over the same picks.
    assert 'data-graph="g5"' in text
    # Sections without a timeline stay checkbox-free: the fortress-hero row (Heroes) and the
    # science rows carry plain label cells (Sciences gets a heatmap, not a per-row checkbox).
    assert "<td>fortress hero (command slot 2)</td>" in text
    assert "<td>SCIENCE_One</td>" in text
    # The graph renderer ships with the page.
    assert "details.timeline" in text and 'class="tl-data"' in text


def test_timeline_payload_escapes_early_script_close():
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
    block = _heatmap_block([choice], "g9", lambda label: label)
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
