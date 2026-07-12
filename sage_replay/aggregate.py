"""Aggregate statistics across many replays, resolved against one loaded game.

Every human slot in every replay becomes one *player-game*: the player's faction, that
player's match outcome, the match length, and the clocked per-player stats from `stats.py`
(buildings / units / heroes / sciences and when each was bought). Aggregation groups the
player-games by faction and answers the questions a corpus review asks: how often a faction
wins, which sciences it buys (and how early), what it opens with, and which structures /
units / heroes it favours - every choice carrying its own win-loss record, so "does faction
F win more with science X or science Y" and "how do games go when they build a Barracks
vs a Signal Fire" are row-vs-row comparisons in one table.

Outcomes come from the concession heuristic in `winner.py`: only `decided` games contribute
wins and losses (in a `recorder_left` game the recorder's own concession counts as their
loss, everyone else stays unknown); everything else is `undetermined` and excluded from win
rates but still counted, so choice popularity spans the whole corpus. `assume_pov_won` (the
CLI's `--winner-pov`) decides the otherwise-undetermined games in favour of the recording
player's team - for corpora whose replays are known to belong to the winner. AI slots issue
no recorded orders and are skipped entirely.

A choice's *pick rate* counts games where it was made at least once; `first ~m:ss` is the
median match clock of its first occurrence across those games; `total` counts every issued
order, so "6 games, x14" reads "built in 6 games, 14 built overall". `other`-bucket labels
in the caller's `tracked_purchases` set are the exception: for a repeatable system purchase
(Edain's CP-upgrade CPObject) each purchase within a game is its own choice, numbered in
purchase order - `CPObject1` is every game's first CP purchase, `CPObject2` the second - so
purchase depth compares directly (how many games went to the third CP upgrade, when, and
with what win rate). Untracked `other` purchases aggregate as ordinary pick-rate rows.

A lobby Random pick records no resolvable faction id in the slot; those player-games are
labeled by the `Side` the player's own build orders vote for (see `_faction_from_orders`),
so random players aggregate under the faction they actually played.

A mod overlay can sharpen faction labels before grouping: `refine_faction` (a
`FactionRefiner`) sees each human's label and clocked stats and returns the label to
aggregate under - Edain's overlay splits Dwarves into their realm (Erebor / Ered Luin /
Iron Hills) by the clan upgrade recorded at match start. Refined labels flow everywhere a
faction appears: the per-faction blocks, the `--faction` filter, and matchup opponents.
Special-power casts aggregate as a `powers` pick category (by raw code name); `relabel_power`
(a `PowerLabeler`, threaded to `stats.compute_stats`) lets the overlay rename a power from the
caster's faction Side, e.g. Edain's four shared Lichtbringer toggles read as
`Lichtbringer -> Earth/Light/Water/Air` only under Imladris.

`matchups=True` (the CLI's `--matchups`) additionally folds every player-game into one
sub-aggregate per enemy faction faced, so each pick table also exists per matchup -
buildings built vs Mordor, units built vs Gondor - rendered after the faction's own
sections. An enemy is any occupied slot (AI included) not sharing the player's nonnegative
lobby team; a game against two enemies of the same faction counts once in that matchup.

Upgrade researches (`0x415`) are aggregated only for the caller's `tracked_upgrades` set
(raw ini code names; nothing by default) - the raw upgrade stream is dominated by
per-battalion gear purchases that would swamp the tables. A mod overlay that knows which
researches deserve a row and which purchases are depth-comparable injects its own sets
(`sage_edain.replay.TRACKED_UPGRADES` / `TRACKED_PURCHASES`, wired into the `sage-edain
replay-aggregate` command).
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from html import escape
from pathlib import Path
from statistics import median

from sage_replay.coverage import find_replays
from sage_replay.narrate import GameData
from sage_replay.replay import ReplayFile, ReplaySlotType, parse_replay_from_path
from sage_replay.stats import PlayerStats, PowerLabeler, _clock, compute_stats
from sage_replay.winner import infer_winner

__all__ = [
    "UNRESOLVED_FACTION",
    "ChoiceStat",
    "Corpus",
    "FactionAggregate",
    "FactionRefiner",
    "PlayerGame",
    "aggregate",
    "collect",
    "patch_groups",
    "player_games",
    "render_aggregate",
    "render_aggregate_html",
    "render_aggregate_markdown",
    "render_index_html",
]

# The faction label for a human slot whose faction couldn't be attributed: a lobby Random
# pick whose orders vote no known Side, or (via a mod refiner) a game missing the choice that
# decides the realm - an Edain Dwarves player who never bought a clan upgrade. These games
# can't be pooled under any faction, so `collect` drops them and lists them as warnings.
UNRESOLVED_FACTION = "?"

# The stats categories aggregated per faction as pick-rate tables (sciences are handled
# separately to also capture the opening pick).
_TEMPLATE_CATEGORIES = ("buildings", "units", "heroes", "upgrades", "other", "powers", "combines")

# The HTML/index renderers take an optional label `translate` (a code name -> display string
# map); when none is given, labels render as their raw code names.
Translate = Callable[[str], str]

# An optional pick-row annotator: given the owning faction label and a pick's code name, it
# returns trailing HTML for the label cell (a badge) or "" for nothing. The aggregate core is
# faction-semantics-agnostic, so the caller injects this (e.g. to flag a pick whose unit Side
# does not match the faction - a disconnected ally's roster built from their inherited base).
Annotate = Callable[[str, str], str]


def _identity(label: str) -> str:
    return label


@dataclass(slots=True)
class PlayerGame:
    """One human slot in one replay, with everything the aggregation needs."""

    replay: str
    player: str
    faction: str
    outcome: str  # "won" | "lost" | "undetermined"
    duration: float  # recorded sim time in seconds (last order's clock)
    stats: PlayerStats
    # The enemy factions faced (one label per occupied enemy slot, AI included; a slot is an
    # enemy unless it shares the player's nonnegative lobby team).
    opponents: tuple[str, ...] = ()


@dataclass(slots=True)
class ChoiceStat:
    """One choice (a science, a structure, a unit...) within one faction's games."""

    label: str
    games: int = 0  # player-games where the choice was made at least once
    wins: int = 0
    losses: int = 0
    total: int = 0  # instances across all games (a Barracks built twice counts twice)
    first_times: list[float] = field(default_factory=list)  # first occurrence per game

    @property
    def decided(self) -> int:
        return self.wins + self.losses

    @property
    def win_rate(self) -> float | None:
        return self.wins / self.decided if self.decided else None

    @property
    def median_first(self) -> float | None:
        return median(self.first_times) if self.first_times else None

    def to_dict(self) -> dict:
        return {
            "label": self.label,
            "games": self.games,
            "wins": self.wins,
            "losses": self.losses,
            "win_rate": self.win_rate,
            "median_first_seconds": self.median_first,
            "total": self.total,
        }


@dataclass(slots=True)
class FactionAggregate:
    """Everything the corpus shows about one faction's player-games."""

    faction: str
    games: int = 0
    wins: int = 0
    losses: int = 0
    undetermined: int = 0
    durations: list[float] = field(default_factory=list)
    sciences: dict[str, ChoiceStat] = field(default_factory=dict)
    first_science: dict[str, ChoiceStat] = field(default_factory=dict)
    buildings: dict[str, ChoiceStat] = field(default_factory=dict)
    units: dict[str, ChoiceStat] = field(default_factory=dict)
    heroes: dict[str, ChoiceStat] = field(default_factory=dict)
    upgrades: dict[str, ChoiceStat] = field(default_factory=dict)
    other: dict[str, ChoiceStat] = field(default_factory=dict)
    powers: dict[str, ChoiceStat] = field(default_factory=dict)
    combines: dict[str, ChoiceStat] = field(default_factory=dict)
    # Per enemy faction, the same aggregation over just the games against it (only filled
    # when `aggregate(matchups=True)`; a game against two same-faction enemies counts once).
    matchups: dict[str, FactionAggregate] = field(default_factory=dict)

    @property
    def decided(self) -> int:
        return self.wins + self.losses

    @property
    def win_rate(self) -> float | None:
        return self.wins / self.decided if self.decided else None

    def to_dict(self) -> dict:
        payload = {
            "faction": self.faction,
            "games": self.games,
            "wins": self.wins,
            "losses": self.losses,
            "undetermined": self.undetermined,
            "win_rate": self.win_rate,
            "median_duration_seconds": median(self.durations) if self.durations else None,
            "sciences": [c.to_dict() for c in _ranked(self.sciences)],
            "first_science": [c.to_dict() for c in _ranked(self.first_science)],
        }
        for category in _TEMPLATE_CATEGORIES:
            payload[category] = [c.to_dict() for c in _ranked(getattr(self, category))]
        if self.matchups:
            payload["matchups"] = {enemy: sub.to_dict() for enemy, sub in _ranked_matchups(self)}
        return payload


@dataclass(slots=True)
class Corpus:
    """The collected corpus: the player-games plus what went into them."""

    games: list[PlayerGame] = field(default_factory=list)
    replays: int = 0  # replays successfully parsed
    warnings: list[str] = field(default_factory=list)


def _outcomes(replay: ReplayFile, assume_pov_won: bool) -> dict[str, str]:
    """Each human's outcome by name, from the winner heuristic. Only a `decided` verdict
    splits everyone into won/lost; `recorder_left` is the recorder's concession (their loss)
    with everyone else's fate beyond the recording. `assume_pov_won` decides otherwise-
    undetermined games in favour of the recording player's team (see `infer_winner`)."""
    verdict = infer_winner(replay, assume_pov_won=assume_pov_won)
    outcomes: dict[str, str] = {}
    if verdict.outcome == "decided":
        winners = set(verdict.winner_names)
        for session in verdict.sessions:
            outcomes[session.name] = "won" if session.name in winners else "lost"
    elif verdict.outcome == "recorder_left" and verdict.recorder is not None:
        outcomes[verdict.recorder] = "lost"
    return outcomes


# A mod overlay's faction refiner: the slot's faction label plus that player's clocked
# stats, returning the (possibly more specific) label to aggregate under - e.g. splitting
# Edain's Dwarves into their realm by the clan upgrade bought at match start.
FactionRefiner = Callable[[str, PlayerStats], str]


def _faction_from_orders(per: PlayerStats, data: GameData) -> str | None:
    """The faction a random-pick slot actually played, inferred from the player's own
    orders: every built template votes with its `Side`, and the most-voted side that is
    some faction's `Side` names the faction. A lobby Random records faction -1 in the
    slot - the engine rolls the real faction at load time, so it survives only in what
    the player went on to build. None when no vote lands (nothing built, or only
    templates whose side no faction claims)."""
    votes: Counter[str] = Counter()
    for event in per.events:
        if event.category in ("buildings", "units", "heroes"):
            side = data.side_of(str(event.label))
            if side:
                votes[side] += 1
    side_to_label: dict[str, str] = {}
    for label, side in zip(data.faction_labels, data.faction_sides, strict=False):
        if side:
            side_to_label.setdefault(side, label)
    for side, _ in votes.most_common():
        if side in side_to_label:
            return side_to_label[side]
    return None


def _slot_labels(
    replay: ReplayFile,
    data: GameData,
    stats: dict[str, PlayerStats],
    refine_faction: FactionRefiner | None,
) -> dict[int, str]:
    """Each occupied slot's faction label, by slot index. A human slot whose lobby pick
    was Random (no resolvable faction id) is labeled by what the player built instead.
    A refiner only sees human slots (an AI's orders are not recorded, so there are no
    stats to refine from)."""
    labels: dict[int, str] = {}
    for index, slot in enumerate(replay.header.metadata.players):
        if slot.slot_type is ReplaySlotType.Empty:
            continue
        label = data.faction_label(slot.faction)
        if slot.slot_type is ReplaySlotType.Human:
            per = stats.get(slot.human_name or "")
            if per is not None:
                if label == UNRESOLVED_FACTION:
                    label = _faction_from_orders(per, data) or label
                if refine_faction is not None:
                    label = refine_faction(label, per)
        labels[index] = label
    return labels


def _opponents(replay: ReplayFile, index: int, labels: dict[int, str]) -> tuple[str, ...]:
    """The enemy factions the slot at `index` faced, one label per occupied enemy slot
    (AI included). Another slot is an ally only when both share the same nonnegative lobby
    team; -1 is the lobby's "no team", so an unteamed slot is everyone's enemy (FFA)."""
    slot = replay.header.metadata.players[index]
    return tuple(
        labels[i]
        for i, other in enumerate(replay.header.metadata.players)
        if i != index and i in labels and (slot.team < 0 or other.team != slot.team)
    )


def player_games(
    replay: ReplayFile,
    data: GameData,
    *,
    source: str = "",
    assume_pov_won: bool = False,
    refine_faction: FactionRefiner | None = None,
    relabel_power: PowerLabeler | None = None,
) -> list[PlayerGame]:
    """The replay's human slots as player-games (AI slots issue no orders and are skipped).
    `refine_faction` sharpens faction labels from each human's own stats - both the
    player-game's faction and its appearances in other players' opponent lists.
    `relabel_power` renames power casts from the caster's faction Side (see `compute_stats`)."""
    outcomes = _outcomes(replay, assume_pov_won)
    stats = {per.player: per for per in compute_stats(replay, data, relabel_power=relabel_power)}
    duration = replay.chunks[-1].timecode * replay.seconds_per_frame if replay.chunks else 0.0
    labels = _slot_labels(replay, data, stats, refine_faction)

    games = []
    for index, slot in enumerate(replay.header.metadata.players):
        if slot.slot_type is not ReplaySlotType.Human or not slot.human_name:
            continue
        games.append(
            PlayerGame(
                replay=source or replay.header.filename,
                player=slot.human_name,
                faction=labels[index],
                outcome=outcomes.get(slot.human_name, "undetermined"),
                duration=duration,
                stats=stats.get(slot.human_name) or PlayerStats(player=slot.human_name),
                opponents=_opponents(replay, index, labels),
            )
        )
    return games


def patch_groups(paths: Iterable[Path]) -> dict[str, list[str]]:
    """The replay files grouped by `ReplayHeader.patch_fingerprint` - a header-only parse,
    cheap enough to gate on before a game root is even loaded. More than one group means
    the corpus mixes patches/mods whose recordings do not simulate identically, so their
    stats must not be pooled. Unparseable files are skipped here; `collect` turns them
    into warnings."""
    groups: dict[str, list[str]] = {}
    for path in paths:
        try:
            header = parse_replay_from_path(path, only_header=True).header
        except Exception:  # noqa: BLE001 - unparseable replays are simply skipped from grouping
            continue
        groups.setdefault(header.patch_fingerprint, []).append(path.name)
    return groups


def collect(
    paths: list[Path],
    data: GameData,
    *,
    assume_pov_won: bool = False,
    refine_faction: FactionRefiner | None = None,
    relabel_power: PowerLabeler | None = None,
) -> Corpus:
    """Parse every replay under `paths` (files or directories) into a corpus of
    player-games. Files that fail to parse and player-games whose faction couldn't be
    attributed (`UNRESOLVED_FACTION` - a lobby Random that built nothing side-voting, or a
    mod refiner that lacked the choice deciding a sub-faction) become warnings rather than
    pooling under a bogus faction, so the unparseable list surfaces both. An unresolved
    player is also scrubbed from the opponents of the games that remain, so `?` never appears
    as a faction row, page, or matchup column anywhere downstream."""
    corpus = Corpus()
    for path in find_replays(paths):
        try:
            replay = parse_replay_from_path(path)
        except Exception as error:  # noqa: BLE001 - any parse failure becomes a corpus warning
            corpus.warnings.append(f"{path.name}: {error}")
            continue
        corpus.replays += 1
        for game in player_games(
            replay,
            data,
            source=path.name,
            assume_pov_won=assume_pov_won,
            refine_faction=refine_faction,
            relabel_power=relabel_power,
        ):
            if game.faction == UNRESOLVED_FACTION:
                corpus.warnings.append(f"{path.name}: {game.player}'s faction unresolved")
                continue
            if UNRESOLVED_FACTION in game.opponents:
                game.opponents = tuple(o for o in game.opponents if o != UNRESOLVED_FACTION)
            corpus.games.append(game)
    return corpus


def _record(table: dict[str, ChoiceStat], label: str, game: PlayerGame, first: float) -> ChoiceStat:
    choice = table.setdefault(label, ChoiceStat(label=label))
    choice.games += 1
    choice.first_times.append(first)
    if game.outcome == "won":
        choice.wins += 1
    elif game.outcome == "lost":
        choice.losses += 1
    return choice


def _record_game(
    agg: FactionAggregate,
    game: PlayerGame,
    tracked_upgrades: frozenset[str],
    tracked_purchases: frozenset[str],
) -> None:
    """Fold one player-game into `agg`'s record and pick tables."""
    agg.games += 1
    agg.durations.append(game.duration)
    if game.outcome == "won":
        agg.wins += 1
    elif game.outcome == "lost":
        agg.losses += 1
    else:
        agg.undetermined += 1

    # Per category: one pick-rate row per label, counting the game once, keeping the
    # first occurrence's clock, and accumulating the per-game instance count. A tracked
    # `other` purchase instead numbers each instance into its own row (CPObject1,
    # CPObject2, ...) so purchase depth is comparable across games.
    per_label: dict[tuple[str, str], list[float]] = {}
    for event in game.stats.events:
        if event.category == "upgrades" and event.label not in tracked_upgrades:
            continue
        if event.category == "fortress_hero_slots":
            key = ("heroes", f"fortress hero (command slot {event.label})")
        else:
            key = (event.category, str(event.label))
        per_label.setdefault(key, []).append(event.seconds)
    for (category, label), times in per_label.items():
        if category == "other" and label in tracked_purchases:
            for nth, seconds in enumerate(sorted(times), start=1):
                _record(agg.other, f"{label}{nth}", game, seconds).total += 1
        else:
            table = getattr(agg, "sciences" if category == "sciences" else category)
            _record(table, label, game, min(times)).total += len(times)

    if game.stats.sciences:
        first_at, opener = game.stats.sciences[0]
        _record(agg.first_science, opener, game, first_at).total += 1


def aggregate(
    games: list[PlayerGame],
    *,
    tracked_upgrades: frozenset[str] = frozenset(),
    tracked_purchases: frozenset[str] = frozenset(),
    matchups: bool = False,
) -> list[FactionAggregate]:
    """Group player-games by faction, most-played first. Upgrade events outside
    `tracked_upgrades` (raw ini code names) are dropped; `other` purchases in
    `tracked_purchases` get per-instance depth rows - see the module docstring.
    `matchups` additionally folds each game into a per-enemy-faction sub-aggregate
    (`FactionAggregate.matchups`), so every pick table also exists per matchup."""
    factions: dict[str, FactionAggregate] = {}
    for game in games:
        agg = factions.setdefault(game.faction, FactionAggregate(faction=game.faction))
        _record_game(agg, game, tracked_upgrades, tracked_purchases)
        if matchups:
            for enemy in dict.fromkeys(game.opponents):  # dedupe: one count per game
                sub = agg.matchups.setdefault(enemy, FactionAggregate(faction=enemy))
                _record_game(sub, game, tracked_upgrades, tracked_purchases)

    return sorted(factions.values(), key=lambda a: (-a.games, a.faction))


def _percent(rate: float | None) -> str:
    return f"{round(rate * 100):3d}%" if rate is not None else "   -"


def _choice_lines(title: str, table: dict[str, ChoiceStat]) -> list[str]:
    if not table:
        return []
    ranked = _ranked(table)
    width = max(len(c.label) for c in ranked)
    lines = [f"  {title}  (games - won-lost - win% - median first - total):"]
    for choice in ranked:
        first = f"~{_clock(choice.median_first)}" if choice.median_first is not None else "-"
        lines.append(
            f"    {choice.label:{width}s}  {choice.games:3d}  "
            f"{choice.wins:2d}-{choice.losses:<2d} {_percent(choice.win_rate)}  "
            f"{first:>6s}  x{choice.total}"
        )
    return lines


def _ranked(table: dict[str, ChoiceStat]) -> list[ChoiceStat]:
    return sorted(table.values(), key=lambda c: (-c.games, -c.total, c.label))


def _ranked_matchups(agg: FactionAggregate) -> list[tuple[str, FactionAggregate]]:
    return sorted(agg.matchups.items(), key=lambda kv: (-kv[1].games, kv[0]))


def _corpus_summary(corpus: Corpus) -> str:
    decided = sum(1 for g in corpus.games if g.outcome != "undetermined")
    return (
        f"{corpus.replays} replays -> {len(corpus.games)} player-games "
        f"({decided} with a decided outcome)"
    )


def _faction_summary(agg: FactionAggregate) -> str:
    length = f", median length {_clock(median(agg.durations))}" if agg.durations else ""
    undetermined = f", {agg.undetermined} undetermined" if agg.undetermined else ""
    return (
        f"{agg.games} games: {agg.wins}-{agg.losses} "
        f"({_percent(agg.win_rate).strip()}){undetermined}{length}"
    )


# The per-faction pick tables in display order:
# (section title, FactionAggregate attribute, markdown label-column header).
_SECTIONS = (
    ("Sciences", "sciences", "Science"),
    ("First science", "first_science", "Science"),
    ("Buildings", "buildings", "Building"),
    ("Units", "units", "Unit"),
    ("Heroes", "heroes", "Hero"),
    ("Upgrades", "upgrades", "Upgrade"),
    ("Other purchases", "other", "Purchase"),
    ("Powers", "powers", "Power"),
    ("Horde combines", "combines", "Combine"),
)


def render_aggregate(corpus: Corpus, factions: list[FactionAggregate]) -> list[str]:
    """The corpus aggregation as text: a per-faction block of win rate, science picks
    (overall and opening), and the building/unit/hero pick tables, followed by the same
    block per matchup when the aggregation carried them."""
    lines = [f"Corpus: {_corpus_summary(corpus)}", ""]
    for agg in factions:
        lines.append(f"== {agg.faction}  - {_faction_summary(agg)}")
        for title, attribute, _ in _SECTIONS:
            lines.extend(_choice_lines(title, getattr(agg, attribute)))
        for enemy, sub in _ranked_matchups(agg):
            lines.append(f"  -- vs {enemy}  - {_faction_summary(sub)}")
            for title, attribute, _ in _SECTIONS:
                lines.extend(_choice_lines(title, getattr(sub, attribute)))
        lines.append("")
    return lines


def _cell(label: str) -> str:
    return label.replace("|", "\\|")


def _markdown_tables(agg: FactionAggregate, heading: str) -> list[str]:
    """The pick-category tables of one aggregate as markdown, titled at `heading` depth."""
    lines: list[str] = []
    for title, attribute, column in _SECTIONS:
        table = getattr(agg, attribute)
        if not table:
            continue
        lines.extend(
            [
                f"{heading} {title}",
                "",
                f"| {column} | Games | W-L | Win % | Median first | Total |",
                "|---|--:|--:|--:|--:|--:|",
            ]
        )
        for choice in _ranked(table):
            first = _clock(choice.median_first) if choice.median_first is not None else "-"
            lines.append(
                f"| {_cell(choice.label)} | {choice.games} "
                f"| {choice.wins}-{choice.losses} | {_percent(choice.win_rate).strip()} "
                f"| {first} | {choice.total} |"
            )
        lines.append("")
    return lines


def render_aggregate_markdown(corpus: Corpus, factions: list[FactionAggregate]) -> list[str]:
    """The same aggregation as GitHub markdown: a heading per faction and a table per
    pick category, then a `### vs <enemy>` block per matchup when the aggregation
    carried them."""
    lines = ["# Replay corpus stats", "", _corpus_summary(corpus), ""]
    for agg in factions:
        lines.extend([f"## {_cell(agg.faction)} - {_faction_summary(agg)}", ""])
        lines.extend(_markdown_tables(agg, "###"))
        for enemy, sub in _ranked_matchups(agg):
            lines.extend([f"### vs {_cell(enemy)} - {_faction_summary(sub)}", ""])
            lines.extend(_markdown_tables(sub, "####"))
    return lines


# The HTML report's stylesheet. Colors are CSS custom properties so the dark theme swaps
# in one place; the win-rate bar is a diverging mark around the 50% midpoint (blue above,
# red below, neutral track), so a faction's polarity reads before the number does.
_HTML_STYLE = """\
:root {
  --plane: #f9f9f7; --surface: #fcfcfb; --ink: #0b0b0b; --ink-2: #52514e;
  --muted: #898781; --grid: #e1e0d9; --ring: rgba(11,11,11,0.10);
  --track: #f0efec; --above: #2a78d6; --below: #e34948;
  --warn-ink: #8a5a00; --warn-bg: #fbeccb;
}
@media (prefers-color-scheme: dark) {
  :root {
    --plane: #0d0d0d; --surface: #1a1a19; --ink: #ffffff; --ink-2: #c3c2b7;
    --muted: #898781; --grid: #2c2c2a; --ring: rgba(255,255,255,0.10);
    --track: #383835; --above: #3987e5; --below: #e66767;
    --warn-ink: #e7b95a; --warn-bg: #3a2f14;
  }
}
* { box-sizing: border-box; }
body {
  margin: 0; background: var(--plane); color: var(--ink);
  font: 14px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif;
}
main { max-width: 1080px; margin: 0 auto; padding: 24px 20px 64px; }
h1 { font-size: 22px; margin: 0 0 4px; }
h2 { font-size: 18px; margin: 32px 0 8px; }
h3 { font-size: 13px; margin: 20px 0 6px; color: var(--ink-2); text-transform: uppercase; letter-spacing: 0.04em; }
p.meta { color: var(--ink-2); margin: 0 0 16px; }
.tiles { display: flex; flex-wrap: wrap; gap: 10px; margin: 12px 0 4px; }
.tile {
  background: var(--surface); border: 1px solid var(--ring); border-radius: 8px;
  padding: 10px 14px; min-width: 108px;
}
.tile .k { font-size: 11px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.05em; }
.tile .v { font-size: 20px; font-weight: 600; margin-top: 2px; }
.tile .v small { font-size: 12px; font-weight: 400; color: var(--ink-2); }
.tablewrap { overflow-x: auto; background: var(--surface); border: 1px solid var(--ring); border-radius: 8px; }
table { border-collapse: collapse; width: 100%; }
th, td { padding: 5px 12px; text-align: right; white-space: nowrap; font-variant-numeric: tabular-nums; }
th { color: var(--muted); font-size: 11px; text-transform: uppercase; letter-spacing: 0.05em; font-weight: 500; }
td:first-child, th:first-child {
  text-align: left; width: 100%;
  font-family: ui-monospace, Consolas, monospace; font-size: 13px;
}
th:first-child { font-family: inherit; }
tbody tr { border-top: 1px solid var(--grid); }
td.dim { color: var(--muted); }
.bar { display: inline-flex; align-items: center; gap: 8px; }
.track {
  position: relative; display: inline-block; width: 72px; height: 8px;
  background: var(--track); border-radius: 4px; overflow: hidden;
}
.track i { position: absolute; left: 50%; top: 0; bottom: 0; width: 1px; background: var(--muted); opacity: 0.55; }
.fill { position: absolute; top: 0; bottom: 0; }
.fill.above { left: 50%; background: var(--above); border-radius: 0 4px 4px 0; }
.fill.below { right: 50%; background: var(--below); border-radius: 4px 0 0 4px; }
.pct { min-width: 34px; text-align: right; }
.na { color: var(--muted); }
details { margin: 14px 0; background: var(--surface); border: 1px solid var(--ring); border-radius: 8px; }
details > summary {
  cursor: pointer; list-style: none; padding: 10px 14px; display: flex;
  align-items: center; gap: 12px; font-weight: 600;
}
details > summary::before { content: "\\25B8"; color: var(--muted); font-size: 11px; }
details[open] > summary::before { content: "\\25BE"; }
details > summary .rec { font-weight: 400; color: var(--ink-2); }
details > .body { padding: 0 14px 14px; }
details .tablewrap { border-left: none; border-right: none; border-radius: 0; background: none; }
td.win { color: var(--above); }
td.loss { color: var(--below); }
td.rep { font-family: ui-monospace, Consolas, monospace; font-size: 12px; color: var(--muted); }
.delta { font-variant-numeric: tabular-nums; }
.delta.up { color: var(--above); }
.delta.down { color: var(--below); }
.delta.even { color: var(--muted); }
.badge {
  display: inline-block; margin-left: 7px; padding: 0 6px; border-radius: 4px;
  font-family: system-ui, -apple-system, sans-serif; font-size: 10px; font-weight: 600;
  letter-spacing: 0.02em; vertical-align: middle; white-space: nowrap;
  color: var(--warn-ink); background: var(--warn-bg);
}
a { color: var(--above); text-decoration: none; }
a:hover { text-decoration: underline; }
.nav {
  display: inline-block; margin: 6px 0 8px; padding: 9px 15px; background: var(--surface);
  border: 1px solid var(--ring); border-radius: 8px; font-weight: 600; color: var(--ink);
}
.nav:hover { text-decoration: none; border-color: var(--above); }
"""


# Extra styling for the navigation index (`render_index_html`) only, appended after the
# shared sheet so the per-faction pages are untouched: the matchup matrix (vertical column
# heads, tinted diverging cells). The link and nav-pill rules live in the shared sheet, as
# the aggregate pages carry a back-to-index nav of their own.
_INDEX_STYLE = """\
table.matrix th, table.matrix td { text-align: center; }
table.matrix td:first-child, table.matrix th:first-child { text-align: left; }
table.matrix th.col { height: 96px; vertical-align: bottom; padding: 4px 3px; }
table.matrix th.col span {
  writing-mode: vertical-rl; transform: rotate(180deg); white-space: nowrap;
  font-family: ui-monospace, Consolas, monospace; font-size: 12px;
  text-transform: none; letter-spacing: 0;
}
table.matrix td.cell { min-width: 40px; font-variant-numeric: tabular-nums; line-height: 1.15; }
table.matrix .n { display: block; font-size: 10px; font-weight: 400; color: var(--muted); }
table.matrix td:first-child .gc { color: var(--muted); font-weight: 400; }
td.mt { color: var(--muted); }
.body ul { margin: 0; padding-left: 20px; }
.body li { font-family: ui-monospace, Consolas, monospace; font-size: 12px; color: var(--ink-2); }
"""


def _html_bar(rate: float | None) -> str:
    """A win rate as a diverging bar around the 50% mark plus the number - or a muted
    dash when no game was decided."""
    if rate is None:
        return '<span class="na">-</span>'
    span = abs(rate - 0.5) * 100
    side = "above" if rate >= 0.5 else "below"
    return (
        '<span class="bar"><span class="track">'
        f'<span class="fill {side}" style="width:{span:.0f}%"></span><i></i>'
        f'</span><span class="pct">{round(rate * 100)}%</span></span>'
    )


def _pick_rate(choice: ChoiceStat | None, games: int) -> float:
    """The share of `games` in which `choice` was picked at least once (0 when absent)."""
    return choice.games / games if choice is not None and games else 0.0


def _delta(value: float | None, unit: str = "") -> str:
    """A signed points delta as coloured HTML - blue when above, red when below, muted at
    zero - or a dash when it is undefined."""
    if value is None:
        return '<span class="na">-</span>'
    points = round(value * 100)
    cls = "up" if points > 0 else "down" if points < 0 else "even"
    text = f"{points:+d}{unit}" if points else f"0{unit}"
    return f'<span class="delta {cls}">{text}</span>'


def _html_tables(
    agg: FactionAggregate,
    heading: str,
    translate: Translate,
    baseline: FactionAggregate | None = None,
    owner: str | None = None,
    annotate: Annotate | None = None,
) -> list[str]:
    """The pick-category tables of one aggregate, titled at `heading` (h3/h4) depth. Row
    labels are shown through `translate` (raw code name when it is the identity). With
    `baseline` (the faction's overall aggregate), each row gains a `vs overall` column: this
    aggregate's pick rate for the choice minus the baseline's, in points - so a matchup table
    shows how the faction's picks shift against that enemy. `annotate(owner, label)` may append
    a badge to a row (e.g. flagging a pick that is not `owner`'s roster); `owner` is the faction
    the picks belong to, which for a matchup sub-table is the parent faction, not the enemy."""
    lines: list[str] = []
    for title, attribute, column in _SECTIONS:
        table = getattr(agg, attribute)
        if not table:
            continue
        base_table = getattr(baseline, attribute) if baseline is not None else None
        vs_head = '<th title="pick rate vs the faction overall, in points">vs overall</th>'
        lines.extend(
            [
                f"<{heading}>{escape(title)}</{heading}>",
                '<div class="tablewrap"><table>',
                f"<thead><tr><th>{escape(column)}</th><th>Games</th><th>W-L</th>"
                "<th>Win rate</th><th>Median first</th><th>Total</th>"
                f"{vs_head if baseline is not None else ''}</tr></thead>",
                "<tbody>",
            ]
        )
        for choice in _ranked(table):
            first = _clock(choice.median_first) if choice.median_first is not None else "-"
            badge = annotate(owner, choice.label) if annotate and owner is not None else ""
            vs_cell = ""
            if baseline is not None and base_table is not None:
                delta = _pick_rate(choice, agg.games) - _pick_rate(
                    base_table.get(choice.label), baseline.games
                )
                vs_cell = f"<td>{_delta(delta)}</td>"
            lines.append(
                f"<tr><td>{escape(translate(choice.label))}{badge}</td><td>{choice.games}</td>"
                f"<td>{choice.wins}-{choice.losses}</td><td>{_html_bar(choice.win_rate)}</td>"
                f'<td class="dim">{first}</td><td>x{choice.total}</td>{vs_cell}</tr>'
            )
        lines.extend(["</tbody>", "</table></div>"])
    return lines


def _html_tiles(agg: FactionAggregate) -> str:
    """One aggregate's headline record as a row of stat tiles."""
    length = _clock(median(agg.durations)) if agg.durations else "-"
    rate = _percent(agg.win_rate).strip() if agg.win_rate is not None else "-"
    tiles = (
        ("Games", str(agg.games)),
        ("Record", f"{agg.wins}-{agg.losses}"),
        ("Win rate", rate),
        ("Undetermined", str(agg.undetermined)),
        ("Median length", length),
    )
    cells = "".join(
        f'<div class="tile"><div class="k">{k}</div><div class="v">{v}</div></div>'
        for k, v in tiles
    )
    return f'<div class="tiles">{cells}</div>'


def render_aggregate_html(
    corpus: Corpus,
    factions: list[FactionAggregate],
    *,
    title: str = "Replay corpus stats",
    translate: Translate | None = None,
    extra: Callable[[FactionAggregate], list[str]] | None = None,
    annotate: Annotate | None = None,
    index_href: str | None = None,
) -> list[str]:
    """The same aggregation as one self-contained HTML page (no external assets,
    light/dark via `prefers-color-scheme`): per faction a stat-tile header and the
    pick-category tables, then a collapsible `vs <enemy>` block per matchup when the
    aggregation carried them. Win rates render as diverging bars around 50%. `translate`
    maps a code name to the display string shown for faction and pick-table labels; by
    default labels render as their raw code names. `extra`, if given, returns extra HTML
    lines appended after each faction's own block (the caller's per-faction replay list).
    `annotate(faction, label)` may badge a pick row - both the faction's own tables and its
    matchup sub-tables are annotated against that faction as the owner. `index_href`, if given,
    renders a back-to-index nav pill linking there (a page relative path from this page)."""
    tr = translate or _identity
    lines = [
        "<!doctype html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f"<title>{escape(title)}</title>",
        f"<style>{_HTML_STYLE}</style>",
        "</head>",
        "<body><main>",
        f"<h1>{escape(title)}</h1>",
        f'<p class="meta">{escape(_corpus_summary(corpus))}</p>',
    ]
    if index_href is not None:
        lines.append(f'<p><a class="nav" href="{escape(index_href)}">&larr; Back to index</a></p>')
    for agg in factions:
        lines.append(f"<h2>{escape(tr(agg.faction))}</h2>")
        lines.append(_html_tiles(agg))
        lines.extend(_html_tables(agg, "h3", tr, owner=agg.faction, annotate=annotate))
        for enemy, sub in _ranked_matchups(agg):
            swing = ""
            if sub.win_rate is not None and agg.win_rate is not None:
                swing = (
                    ' <span class="rec" title="win rate vs this faction&#39;s overall">'
                    f"&Delta; {_delta(sub.win_rate - agg.win_rate, '%')}</span>"
                )
            lines.extend(
                [
                    "<details><summary>",
                    f"vs {escape(tr(enemy))} {_html_bar(sub.win_rate)}{swing} "
                    f'<span class="rec">{escape(_faction_summary(sub))}</span>',
                    '</summary><div class="body">',
                ]
            )
            lines.extend(
                _html_tables(sub, "h3", tr, baseline=agg, owner=agg.faction, annotate=annotate)
            )
            lines.append("</div></details>")
        if extra is not None:
            lines.extend(extra(agg))
    lines.extend(["</main></body>", "</html>"])
    return lines


def _index_tiles(corpus: Corpus, factions: list[FactionAggregate]) -> str:
    """The corpus headline as stat tiles: how much data the pages are built from."""
    decided = sum(1 for g in corpus.games if g.outcome != "undetermined")
    tiles = (
        ("Replays", str(corpus.replays)),
        ("Player-games", str(len(corpus.games))),
        ("Decided", str(decided)),
        ("Factions", str(len(factions))),
        ("Unparseable", str(len(corpus.warnings))),
    )
    cells = "".join(
        f'<div class="tile"><div class="k">{k}</div><div class="v">{v}</div></div>'
        for k, v in tiles
    )
    return f'<div class="tiles">{cells}</div>'


def _index_leaderboard(
    factions: list[FactionAggregate], links: dict[str, str], translate: Translate
) -> list[str]:
    """A row per faction (most-played first) linking to its page, with its headline record.
    The faction is shown through `translate` but linked by its raw code name via `links`."""
    lines = [
        '<div class="tablewrap"><table>',
        "<thead><tr><th>Faction</th><th>Games</th><th>W-L</th>"
        "<th>Win rate</th><th>Median length</th></tr></thead>",
        "<tbody>",
    ]
    for agg in factions:
        length = _clock(median(agg.durations)) if agg.durations else "-"
        href = links.get(agg.faction)
        name = escape(translate(agg.faction))
        cell = f'<a href="{escape(href)}">{name}</a>' if href else name
        lines.append(
            f"<tr><td>{cell}</td><td>{agg.games}</td>"
            f"<td>{agg.wins}-{agg.losses}</td><td>{_html_bar(agg.win_rate)}</td>"
            f'<td class="dim">{length}</td></tr>'
        )
    lines.extend(["</tbody>", "</table></div>"])
    return lines


def _matrix_cell(sub: FactionAggregate | None) -> str:
    """One matchup matrix cell: the row faction's win rate versus this column faction over
    the game count backing it, tinted by how far the rate is from even, or a muted dot when
    the pairing has no games."""
    if sub is None or sub.games == 0:
        return '<td class="mt">&middot;</td>'
    rate = sub.win_rate
    if rate is None:
        return (
            f'<td class="mt" title="{sub.games} games, none decided">'
            f'&ndash;<span class="n">{sub.games}</span></td>'
        )
    strength = abs(rate - 0.5) * 2
    variable = "--above" if rate >= 0.5 else "--below"
    tint = 12 + strength * 48  # a floor tint so a near-even cell still reads as filled
    style = f"background: color-mix(in srgb, var({variable}) {tint:.0f}%, transparent)"
    return (
        f'<td class="cell" style="{style}" title="{sub.wins}-{sub.losses} of {sub.games}">'
        f'{round(rate * 100)}%<span class="n">{sub.games}</span></td>'
    )


def _index_matrix(
    factions: list[FactionAggregate], links: dict[str, str], translate: Translate
) -> list[str]:
    """The faction-vs-faction win-rate grid, when the aggregation carried matchups; empty
    otherwise. Rows and columns follow the leaderboard order (most-played first); faction
    names are shown through `translate`, keyed internally by their raw code names."""
    if not any(agg.matchups for agg in factions):
        return []
    order = [agg.faction for agg in factions]
    heads = "".join(f'<th class="col"><span>{escape(translate(f))}</span></th>' for f in order)
    lines = [
        "<h2>Matchup win rates</h2>",
        '<p class="meta">Row faction&rsquo;s win rate versus each column faction over the '
        "game count backing it (cell tint = distance from even; hover for the record). The "
        "count after each row faction is its total games.</p>",
        '<div class="tablewrap"><table class="matrix">',
        f"<thead><tr><th>vs &rarr;</th>{heads}</tr></thead>",
        "<tbody>",
    ]
    for agg in factions:
        href = links.get(agg.faction)
        name = escape(translate(agg.faction))
        linked = f'<a href="{escape(href)}">{name}</a>' if href else name
        label = f'{linked} <span class="gc">{agg.games}</span>'
        # The diagonal (a faction versus itself) is a mirror: every decided game is one
        # player's win and the other's loss, so the rate is 50% by construction and says
        # nothing - leave it blank rather than paint a misleading even cell.
        cells = "".join(
            '<td class="mt">&middot;</td>'
            if enemy == agg.faction
            else _matrix_cell(agg.matchups.get(enemy))
            for enemy in order
        )
        lines.append(f"<tr><td>{label}</td>{cells}</tr>")
    lines.extend(["</tbody>", "</table></div>"])
    return lines


def render_index_html(
    corpus: Corpus,
    factions: list[FactionAggregate],
    links: dict[str, str],
    *,
    title: str = "Replay corpus",
    combined_href: str = "aggregate.html",
    generated: str | None = None,
    translate: Translate | None = None,
) -> list[str]:
    """A self-contained navigation index for a set of aggregate pages (same light/dark
    styling as `render_aggregate_html`): corpus stat tiles, a link to the combined report,
    a per-faction leaderboard linking out via `links` (raw faction code name -> href), the
    matchup win-rate matrix, and the unparseable / unresolved-faction warnings. `generated` is an optional build
    stamp; `translate` maps a faction code name to the display string (raw code name by
    default) while `links` stays keyed by the raw code name."""
    tr = translate or _identity
    meta = _corpus_summary(corpus)
    if generated:
        meta += f" · generated {generated}"
    lines = [
        "<!doctype html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f"<title>{escape(title)}</title>",
        f"<style>{_HTML_STYLE}{_INDEX_STYLE}</style>",
        "</head>",
        "<body><main>",
        f"<h1>{escape(title)}</h1>",
        f'<p class="meta">{escape(meta)}</p>',
        _index_tiles(corpus, factions),
        f'<p><a class="nav" href="{escape(combined_href)}">All factions &mdash; '
        "combined report &rarr;</a></p>",
        "<h2>Factions</h2>",
    ]
    lines.extend(_index_leaderboard(factions, links, tr))
    lines.extend(_index_matrix(factions, links, tr))
    if corpus.warnings:
        lines.extend(
            [
                "<details><summary>",
                f"{len(corpus.warnings)} unparseable / unresolved",
                '</summary><div class="body"><ul>',
                *[f"<li>{escape(w)}</li>" for w in corpus.warnings],
                "</ul></div></details>",
            ]
        )
    lines.extend(["</main></body>", "</html>"])
    return lines
