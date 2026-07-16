"""Aggregate statistics across many replays, resolved against one loaded game.

Every human slot in every replay becomes one *player-game*: the player's faction, match
outcome, match length, and the clocked per-player stats from `stats.py` (buildings / units /
heroes / sciences and when each was bought). Aggregation groups player-games by faction and
answers what a corpus review asks: how often a faction wins, which sciences it buys (and how
early), what it opens with, when it claims its standard outpost (the `*_outpost` plot unpack,
pooled into one per-faction milestone named by the unpacked base - see `_outpost_base`), and
which structures / units / heroes it favours - every choice carrying its own win-loss record,
so "science X or Y" and "Barracks vs Signal Fire" are row-vs-row comparisons in one table.

Outcomes come first from the ladder metadata sidecar beside each replay, which states the
winner outright (see `sidecar.py`); `collect` falls back, per replay lacking a trustworthy
sidecar, to the concession heuristic in `winner.py`: only `decided` games contribute wins and
losses (a `recorder_left` game counts the recorder's own concession as their loss, everyone
else stays unknown); everything else is `undetermined` - excluded from win rates but still
counted, so choice popularity spans the whole corpus. `assume_pov_won` (the CLI's
`--winner-pov`) decides otherwise-undetermined games for the recording player's team. AI slots
issue no recorded orders and are skipped entirely.

A choice's *pick rate* counts games where it was made at least once; `first ~m:ss` is the
median match clock of its first occurrence across those games; `total` counts every issued
order, so "6 games, x14" reads "built in 6 games, 14 built overall". Heroes are the one
exception: each hero counts once per game, at its first fielding. `other`-bucket labels in
`tracked_purchases` are the other exception: each purchase within a game is its own choice,
numbered in purchase order (`CPObject1` is every game's first purchase of that kind,
`CPObject2` the second), so purchase depth compares directly across games. Untracked `other`
purchases aggregate as ordinary pick-rate rows.

A mod overlay sharpens the corpus before grouping: `refine_faction` (a `FactionRefiner`)
relabels a human's faction from their clocked stats, the loaded game, and the replay's map;
`relabel_power`, `power_recruits`, and `upgrade_recruits`, all threaded through
`stats.compute_stats`, rename a special-power cast from the caster's faction Side and let a
permanently-fielding cast or dedication research merge into the pick tables like an ordinary
recruit; `tracked_upgrades` / `tracked_purchases` /
`tracked_powers` gate which upgrade researches, purchases, and power casts earn a row at all
(nothing by default here in the core; the CLI and rebuild paths always pass the game's
`Type = PLAYER` upgrade set - `GameData.player_upgrades` - so faction-wide researches earn
rows while per-battalion OBJECT gear stays out), and `include_combines` gates horde combines
(`0x423`) the same way. See
the alias definitions below for each hook's shape, and `sage_edain.replay` for Edain's concrete
refiners and tables.

Each faction also carries a *build-order tree* (`build_orders.py`): every game's eco steps
(buildings/units/heroes) fold into one per-faction prefix tree (`build_orders.build_tree`), while
its sciences - a separate currency, extracted by `build_sequence` as their own stream - never grow
tree nodes of their own, riding instead as two per-node annotations built alongside the insert:
`sciences_by_step` (what a game had bought by that step's own clock) and `sciences_taken` (the
game's whole science order, unconditionally) - so a node can answer both "what's typically in hand
here" and "what science order rides with this opening." Two games that bought the same things in a
different relative order still land on one shared opening. A report reads the tree's eco identity
directly for the icicle, Explorer, and openings table, and layers the science annotations back in
per renderer: the icicle's readout box shows a hovered/pinned step's by-step sciences, and the
openings table appends each row's leaf-wide science order as a second line. What one step is, and
how a tree is built, pruned, and annotated, lives in `build_orders.py`'s docstring.

A lobby Random pick is labeled by the `Side` the player's own build orders vote for (see
`_faction_from_orders`), so random players aggregate under the faction they actually played.

`matchups=True` (the CLI's `--matchups`) additionally folds every player-game into a
sub-aggregate per enemy faction faced, rendered after the faction's own sections. An enemy is
any occupied slot (AI included) not sharing the player's nonnegative lobby team.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Callable, Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from html import escape
from itertools import count
from pathlib import Path
from statistics import median

from sage_replay import build_orders
from sage_replay.build_orders import BuildNode
from sage_replay.narrate import GameData
from sage_replay.replay import ReplayFile, ReplaySlotType, find_replays, parse_replay_from_path
from sage_replay.sidecar import sidecar_outcomes
from sage_replay.stats import (
    PlayerStats,
    PowerLabeler,
    PowerRecruits,
    UpgradeRecruits,
    compute_stats,
)
from sage_replay.winner import infer_winner
from sage_utils.clock import clock

__all__ = [
    "DEFAULT_POWERS_HEADING",
    "UNRESOLVED_FACTION",
    "ChoiceStat",
    "Corpus",
    "FactionAggregate",
    "FactionRefiner",
    "PlayerGame",
    "aggregate",
    "collect",
    "command_point_weights",
    "patch_groups",
    "player_games",
    "render_aggregate",
    "render_aggregate_html",
    "render_aggregate_markdown",
    "render_index_html",
    "version_groups",
    "version_labels",
]

# The faction label for a human slot whose faction couldn't be attributed: a lobby Random
# pick whose orders vote no known Side, or (via a mod refiner) a game missing the choice that
# decides the realm - an Edain Dwarves player who never bought a clan upgrade. These games
# can't be pooled under any faction, so `collect` drops them and lists them as warnings.
UNRESOLVED_FACTION = "?"

# The stats categories aggregated per faction as pick-rate tables (sciences are handled
# separately to also capture the opening pick).
_TEMPLATE_CATEGORIES = ("buildings", "units", "heroes", "upgrades", "other", "powers", "combines")

# The prune thresholds for a faction's build-order tree: a branch is kept only when at least
# `_BUILD_MIN_GAMES` games took it and it holds at least `_BUILD_MIN_SHARE` of its parent's
# games, so a rare or under-sampled fork is dropped along with everything under it.
_BUILD_MIN_GAMES = 3
_BUILD_MIN_SHARE = 0.10

# The floor an opening row's science line applies to a leaf's full science order
# (`BuildNode.sciences_taken`): a label renders on the line only when at least this share of the
# leaf's games bought it, so a one-off purchase in an otherwise unrelated game doesn't clutter
# every row's science summary.
_SCIENCE_LINE_MIN_SHARE = 0.25

# The default sub-heading the tracked powers render under, nested inside the Units section.
# A mod overlay names it for the caster the powers belong to.
DEFAULT_POWERS_HEADING = "Special powers"

# Rendered under every aggregation's corpus summary: hero rows come from an approximation.
# A hero-recruit order carries a shifting revive-submenu position, not a hero id; the
# position is replayed per player (each replay against its own map's roster), but a
# position that stays ambiguous - several fallen heroes could hold a tail slot - keeps its
# raw slot label (see sage_replay/order_space_map.md, `0x417` flag=True).
_HERO_NOTE = (
    "Hero rows are approximate: recruit orders carry a shifting revive-menu position, "
    "not a hero id. Positions are replayed per player against each map's own roster; "
    'an ambiguous position stays as "fortress hero (command slot N)".'
)

# The shorter warning rendered inside each Heroes section (right under the heading), so the
# caveat sits next to the data rather than only in the corpus header. A "command slot N" row
# is the unresolved case - a recruit whose menu position could not be pinned to a hero (a
# faction with no loaded roster, or a tail slot after several unseen hero deaths).
_HERO_SECTION_NOTE = (
    "Extrapolated from revive-menu positions, not hero ids - these rows may be inaccurate, "
    'especially any "command slot N" row, whose position could not be resolved to a hero.'
)

# The Build orders section's variant of the hero caveat: only the hero *steps* inside a
# sequence carry the extrapolation, the building/unit steps around them are exact - so the
# wording scopes the doubt to those steps rather than repeating the Heroes table's whole-section
# warning.
_BUILD_ORDER_HERO_NOTE = (
    "Hero steps are extrapolated from revive-menu positions, not hero ids - a hero named in "
    'an opening may be wrong, especially a "fortress hero (command slot N)" step, whose '
    "position never resolved. The steps around it are exact."
)

# The HTML/index renderers take an optional label `translate` (a code name -> display string
# map); when none is given, labels render as their raw code names.
Translate = Callable[[str], str]

# An optional pick-row annotator: given the owning faction label and a pick's code name, it
# returns trailing HTML for the label cell (a badge) or "" for nothing. The aggregate core is
# faction-semantics-agnostic, so the caller injects this (e.g. to flag a pick whose unit Side
# does not match the faction - a disconnected ally's roster built from their inherited base).
Annotate = Callable[[str, str], str]

# An optional pick-weight hook for the Units timeline graph: given a pick's label as the
# tables record it (before `translate`), returns the command points one order of it occupies -
# the per-series weight behind the graph's "CP share" y-mode (see `command_point_weights`).
# 0 means weightless (a free summon, an unknown label); without the hook the mode isn't
# offered at all.
Weight = Callable[[str], int]

# An optional faction-icon hook: given a faction code name, returns the icon's URL (already
# relative to the page being rendered) to show immediately before that faction's display name,
# or "" for none. The aggregate core is engine-generic and ships no art, so the caller injects
# this - Edain's overlay maps each faction label to the front-page icon it ships and, owning the
# output tree, resolves the URL relative to each page's depth. The renderer wraps the URL in the
# `<img>` markup itself (see `_icon_img`), so styling stays here while the caller owns only paths.
FactionIcon = Callable[[str], str]


def _identity(label: str) -> str:
    return label


def command_point_weights(data: GameData) -> Weight:
    """A `render_aggregate_html` `weight` hook mapping a pick label to its template's
    effective `CommandPoints` (`data.command_points`, macro-resolved and inherited through
    the ChildObject parent chain at load time - hordes carry theirs as gamedata macros) -
    the army-cap cost one order of it occupies while fielded - behind the Units timeline's
    "CP share" y-mode. Labels mirror how `stats.py` records recruits
    (`data.label(name) or name`), so the keys match the pick tables whether or not the game
    was loaded localized; when several templates share one display label the largest CP wins.
    A label with no known positive CP weighs 0: a free summon genuinely occupies no command
    points, and an unknown label reads the same way (a flat zero line, never a dropped row)."""
    weights: dict[str, int] = {}
    for name, cp in data.command_points.items():
        if cp <= 0:
            continue
        label = data.label(name) or name
        if cp > weights.get(label, 0):
            weights[label] = cp
    return lambda label: weights.get(label, 0)


def _no_icon(label: str) -> str:
    return ""


def _icon_img(src: str, cls: str = "ficon") -> str:
    """The `<img>` for a faction icon URL (`""` -> nothing), at CSS class `cls`: the inline
    `ficon` before a faction name, or the `cico` pinned under a matrix column header."""
    return f'<img class="{cls}" src="{escape(src)}" alt="">' if src else ""


def _anchor(label: str) -> str:
    """A faction code name as a stable in-page anchor slug (`FactionMen` -> `factionmen`), for
    the contents box's links to each faction's `<h2>`."""
    slug = re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")
    return slug or "x"


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
    # Every instance across all games as (order seconds, that match's duration) pairs - the
    # raw material for the HTML timeline graphs (buildings/units) and the purchase-timing
    # heatmaps (sciences/upgrades/other), which both bin client-side so one payload serves
    # either the %-of-match or the absolute-clock axis. Only those five categories collect
    # these (see `_record_game`); everywhere else the list stays empty, and it is deliberately
    # absent from `to_dict()` so the JSON output is unchanged.
    occurrences: list[tuple[float, float]] = field(default_factory=list)

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
    # The standard-outpost claim as a single build-order milestone: one ChoiceStat pooling
    # every `*_outpost` plot unpack (see `_outpost_base`) so a faction's outpost timing reads as
    # "unpacked in N games, median ~m:ss" regardless of which template carried it. Its `label`
    # is the unpacked base name (`dunedain_outpost`), so the base gets its own translatable
    # aggregate name. None until a game unpacks one.
    outpost: ChoiceStat | None = None
    # The faction's openings as a pruned prefix tree (`build_orders.py`): None until a game
    # contributes one, and a tree pruned down to no children (`not build_orders.children`) is
    # treated as absent everywhere downstream, the same as None. The tree's identity is eco-only;
    # each node also carries its games' sciences as two annotations (`build_orders.build_tree`).
    build_orders: BuildNode | None = None
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
            "outpost": self.outpost.to_dict() if self.outpost is not None else None,
            "build_orders": (
                self.build_orders.to_dict()
                if self.build_orders is not None and self.build_orders.children
                else None
            ),
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


# A match-outcome source keyed to a replay's file path: given the parsed replay and where it
# was read from, it returns each human slot's outcome ("won"/"lost" by name), or None to defer
# to the concession heuristic. `collect` calls it per replay before falling back to `winner.py`;
# the default (`sidecar_outcomes`) reads the ladder metadata sidecar beside the replay.
OutcomeSource = Callable[[ReplayFile, Path], dict[str, str] | None]


# A mod overlay's faction refiner: the slot's faction label, that player's clocked stats, the
# loaded `GameData`, and the replay's map file, returning the (possibly more specific) label to
# aggregate under - e.g. splitting Edain's Dwarves into their realm by the clan upgrade bought at
# match start (stats), or its Men into Gondor/Arnor/Belfalas by the map's Gondor hero roster
# (game + map). A stats-only refiner simply ignores the last two arguments.
FactionRefiner = Callable[[str, PlayerStats, GameData, str | None], str]

# `collect`'s optional `record` hook: called once per successfully parsed replay with
# `(path, replay, games, heuristic_outcomes)`, right before that replay's games fold into the
# corpus. It is the caller's snapshot point for caching a translated parse (`sage_replay.cache`)
# without this module knowing anything about caching.
RecordHook = Callable[[Path, ReplayFile, list[PlayerGame], dict[str, str]], None]


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
    stats to refine from); it also receives the loaded game and the replay's map file, so a
    map-scoped refinement (Edain's Men -> Gondor/Arnor/Belfalas by the map's roster) can resolve."""
    map_file = replay.header.metadata.map_file
    labels: dict[int, str] = {}
    for index, slot in enumerate(replay.header.metadata.players):
        if slot.slot_type is ReplaySlotType.Empty or slot.is_observer:
            continue
        label = data.faction_label(slot.faction)
        if slot.slot_type is ReplaySlotType.Human:
            per = stats.get(slot.human_name or "")
            if per is not None:
                if label == UNRESOLVED_FACTION:
                    label = _faction_from_orders(per, data) or label
                if refine_faction is not None:
                    label = refine_faction(label, per, data, map_file)
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


def _random_pick_factions(
    replay: ReplayFile, data: GameData, stats: dict[str, PlayerStats]
) -> dict[str, int]:
    """The faction id each lobby-Random player (slot faction -1, no roster) actually
    rolled, for the ones whose first stats pass left hero recruits unresolved - inferred
    from what they built, and only when the inferred faction carries a hero roster (so a
    recompute can improve on the raw slot numbers)."""
    overrides: dict[str, int] = {}
    for slot in replay.header.metadata.players:
        per = stats.get(slot.human_name or "")
        if per is None or not per.fortress_hero_slots:
            continue
        if data.faction_label(slot.faction) != UNRESOLVED_FACTION:
            continue
        label = _faction_from_orders(per, data)
        if label is None or label not in data.faction_labels:
            continue
        faction_id = data.faction_labels.index(label)
        if data.hero_roster_for(replay.header.metadata.map_file, faction_id):
            overrides[per.player] = faction_id
    return overrides


def player_games(
    replay: ReplayFile,
    data: GameData,
    *,
    source: str = "",
    assume_pov_won: bool = False,
    outcomes: dict[str, str] | None = None,
    refine_faction: FactionRefiner | None = None,
    relabel_power: PowerLabeler | None = None,
    power_recruits: PowerRecruits | None = None,
    upgrade_recruits: UpgradeRecruits | None = None,
    ignore_recruits: frozenset[str] = frozenset(),
) -> list[PlayerGame]:
    """The replay's human slots as player-games (AI slots issue no orders, and observer slots
    play no side - both are skipped, and an observer never appears as an opponent either).
    `outcomes` (a `{human name: "won"|"lost"}` map) states the match result outright - the
    ladder-sidecar verdict `collect` reads - taking the place of the `winner.py` heuristic when
    given; without it the outcome falls back to that heuristic (`assume_pov_won` layers the
    point-of-view assumption over it). `refine_faction` sharpens faction labels from each
    human's own stats - both the player-game's faction and its appearances in other players'
    opponent lists. `relabel_power`, `power_recruits`, `upgrade_recruits`, and
    `ignore_recruits` thread straight through to `compute_stats`, which documents their
    contracts.

    Hero recruits resolve against the slot faction's revive roster, which a lobby Random (slot
    faction -1) doesn't carry - so when such a player's first stats pass leaves hero slots
    unresolved, the faction they actually rolled is inferred from what they built
    (`_faction_from_orders`) and their stats recomputed with that faction's roster."""
    if outcomes is None:
        outcomes = _outcomes(replay, assume_pov_won)
    stats = {
        per.player: per
        for per in compute_stats(
            replay,
            data,
            relabel_power=relabel_power,
            power_recruits=power_recruits,
            upgrade_recruits=upgrade_recruits,
            ignore_recruits=ignore_recruits,
        )
    }
    overrides = _random_pick_factions(replay, data, stats)
    if overrides:
        stats = {
            per.player: per
            for per in compute_stats(
                replay,
                data,
                relabel_power=relabel_power,
                power_recruits=power_recruits,
                upgrade_recruits=upgrade_recruits,
                ignore_recruits=ignore_recruits,
                faction_overrides=overrides,
            )
        }
    duration = replay.chunks[-1].timecode * replay.seconds_per_frame if replay.chunks else 0.0
    labels = _slot_labels(replay, data, stats, refine_faction)

    games = []
    for index, slot in enumerate(replay.header.metadata.players):
        if slot.slot_type is not ReplaySlotType.Human or not slot.human_name or slot.is_observer:
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


def patch_groups(paths: Iterable[Path]) -> dict[str, list[Path]]:
    """The replay files grouped by `ReplayHeader.patch_fingerprint` - a header-only parse,
    cheap enough to gate on before a game root is even loaded. More than one group means
    the corpus mixes patches/mods whose recordings do not simulate identically, so their
    stats must not be pooled. Unparseable files are skipped here; `collect` turns them
    into warnings. Each group's paths feed straight back into `collect`, so a caller that
    wants to aggregate the groups separately never has to re-resolve them from names."""
    groups: dict[str, list[Path]] = {}
    for path in paths:
        try:
            header = parse_replay_from_path(path, only_header=True).header
        except Exception:  # noqa: BLE001 - unparseable replays are simply skipped from grouping
            continue
        groups.setdefault(header.patch_fingerprint, []).append(path)
    return groups


def version_labels(path: Path, fingerprints: Iterable[str]) -> dict[str, str]:
    """The hand-maintained patch-fingerprint -> version-label map at `path`, e.g.
    `{"Bfme2 data=0xC14360E4": "Edain 4.8.4.3"}`. Every fingerprint in `fingerprints` missing
    from the file gets a blank entry ("" - not yet labeled by hand), the same blank-then-fill
    pattern as `tools/rebuild_aggregates.py`'s `_load_names`; a tournament corpus spanning
    patches hands this to `version_groups` once every fingerprint is filled in. Existing entries
    keep their file order and a new blank is appended at the end - the order is hand-maintained
    (`version_groups` prompts the build's version switches in it) and must not be re-sorted out
    from under the user. The file is rewritten only when an entry was added or it did not exist
    yet, so a fully hand-filled file is left untouched run to run."""
    labels: dict[str, str] = {}
    if path.exists():
        # utf-8-sig, not utf-8: the file is hand-edited, and a Windows editor (or PowerShell
        # redirect) that saves UTF-8 with a BOM must not crash the build.
        labels = json.loads(path.read_text(encoding="utf-8-sig"))
    before = len(labels)
    for fingerprint in fingerprints:
        labels.setdefault(fingerprint, "")  # appended after the existing hand-ordered entries
    if len(labels) != before or not path.exists():
        text = json.dumps(labels, ensure_ascii=False, indent=2)
        path.write_text(text + "\n", encoding="utf-8")
    return labels


def version_groups(groups: dict[str, list[Path]], labels: dict[str, str]) -> dict[str, list[Path]]:
    """`patch_groups`' fingerprint-keyed groups, merged under their hand-assigned version
    labels - two fingerprints sharing a label (a hotfix that changed nothing gameplay-visible)
    pool into that label's one entry, so the caller aggregates each version's replays in a
    single pass. Raises `ValueError` naming every fingerprint in `groups` that `labels` leaves
    blank or unlabeled, pointing the caller at `version_labels`' output instead of aggregating a
    mislabeled fingerprint by accident.

    The merged versions keep the order they appear in `labels` (the hand-maintained
    versions.json order `version_labels` preserves) rather than fingerprint-hash order, so a
    multi-version build's per-version install-switch prompts follow that file - letting the
    corpus arrange its versions.json to minimise how much the game install has to change
    between passes."""
    unlabeled = [fingerprint for fingerprint in groups if not labels.get(fingerprint)]
    if unlabeled:
        raise ValueError("no version label for: " + ", ".join(sorted(unlabeled)))
    merged: dict[str, list[Path]] = {}
    # Walk labels in file order, keeping only fingerprints this corpus actually recorded; the
    # guard above guarantees every group fingerprint is a labeled key, so none is dropped.
    for fingerprint in labels:
        if fingerprint in groups:
            merged.setdefault(labels[fingerprint], []).extend(groups[fingerprint])
    return merged


def _absorb(corpus: Corpus, name: str, games: Iterable[PlayerGame]) -> None:
    """Fold one replay's raw player-games (`player_games()`'s output, unfiltered) into
    `corpus`: a player-game whose faction couldn't be attributed (`UNRESOLVED_FACTION`) becomes
    a warning instead of pooling under a bogus faction, `?` is scrubbed from the opponents of
    the games that remain (so it never appears as a faction row, page, or matchup column
    anywhere downstream), and everything else lands in `corpus.games`. Does not touch
    `corpus.replays` - the caller (a fresh parse, or a cache hit replaying the same games) is
    the one that knows whether this replay should count once."""
    for game in games:
        if game.faction == UNRESOLVED_FACTION:
            corpus.warnings.append(f"{name}: {game.player}'s faction unresolved")
            continue
        if UNRESOLVED_FACTION in game.opponents:
            game.opponents = tuple(o for o in game.opponents if o != UNRESOLVED_FACTION)
        corpus.games.append(game)


def collect(
    paths: list[Path],
    data: GameData,
    *,
    assume_pov_won: bool = False,
    outcome_source: OutcomeSource | None = sidecar_outcomes,
    refine_faction: FactionRefiner | None = None,
    relabel_power: PowerLabeler | None = None,
    power_recruits: PowerRecruits | None = None,
    upgrade_recruits: UpgradeRecruits | None = None,
    ignore_recruits: frozenset[str] = frozenset(),
    record: RecordHook | None = None,
) -> Corpus:
    """Parse every replay under `paths` (files or directories) into a corpus of
    player-games. Files that fail to parse and player-games whose faction couldn't be
    attributed (`UNRESOLVED_FACTION` - a lobby Random that built nothing side-voting, or a
    mod refiner that lacked the choice deciding a sub-faction) become warnings rather than
    pooling under a bogus faction, so the unparseable list surfaces both. An unresolved
    player is also scrubbed from the opponents of the games that remain, so `?` never appears
    as a faction row, page, or matchup column anywhere downstream.

    Each replay's outcome comes from `outcome_source` (given the parsed replay and its path),
    defaulting to the ladder metadata sidecar beside it (`sidecar_outcomes`); only where that
    source has no verdict does the game fall back to the `winner.py` concession heuristic (with
    `assume_pov_won` layered over it). Pass `outcome_source=None` to use the heuristic alone.

    `record` (a `RecordHook`) is called once per successfully parsed replay, right before that
    replay's games fold into the corpus; `games` is still the raw, unfiltered `player_games()`
    output, and `heuristic` is the concession-heuristic verdict for every human in it, computed
    once here (rather than inside `player_games`) so a caller that also wants it - to cache as a
    fallback outcome - doesn't pay for it twice."""
    corpus = Corpus()
    for path in find_replays(paths):
        try:
            replay = parse_replay_from_path(path)
        except Exception as error:  # noqa: BLE001 - any parse failure becomes a corpus warning
            corpus.warnings.append(f"{path.name}: {error}")
            continue
        corpus.replays += 1
        outcomes = outcome_source(replay, path) if outcome_source is not None else None
        heuristic = _outcomes(replay, assume_pov_won) if record is not None else None
        games = player_games(
            replay,
            data,
            source=path.name,
            assume_pov_won=assume_pov_won,
            outcomes=outcomes if outcomes is not None else heuristic,
            refine_faction=refine_faction,
            relabel_power=relabel_power,
            power_recruits=power_recruits,
            upgrade_recruits=upgrade_recruits,
            ignore_recruits=ignore_recruits,
        )
        if record is not None:
            assert heuristic is not None  # computed above under the same `record is not None` guard
            record(path, replay, games, heuristic)
        _absorb(corpus, path.name, games)
    return corpus


def _bump(choice: ChoiceStat, game: PlayerGame, first: float) -> ChoiceStat:
    """Fold one game's occurrence of a choice into `choice`: count the game, keep this game's
    first-occurrence clock, and credit the game's outcome. `total` (the per-game instance
    count) is left to the caller, which knows how many instances the game held."""
    choice.games += 1
    choice.first_times.append(first)
    if game.outcome == "won":
        choice.wins += 1
    elif game.outcome == "lost":
        choice.losses += 1
    return choice


def _record(table: dict[str, ChoiceStat], label: str, game: PlayerGame, first: float) -> ChoiceStat:
    return _bump(table.setdefault(label, ChoiceStat(label=label)), game, first)


# The `<plot> (unpacks <base>)` label `stats.py` writes for a castle/camp/outpost plot unpack;
# the captured group is the base-layout name the issuing player's faction claimed.
_UNPACK_LABEL = re.compile(r" \(unpacks (\w+)\)$")


def _outpost_base(label: str) -> str | None:
    """The standard-outpost base a building pick claims, or None when it is not one. `stats.py`
    labels a plot unpack `<plot> (unpacks <base>)`, and the neutral outpost plot unpacks to the
    claiming faction's `*_outpost` layout (gondor_outpost, mirkwood_outpost, dunedain_outpost,
    ...); the `_outpost` base suffix marks the standard outpost apart from a main-castle unpack
    (e.g. `orkstadt_main`), whatever the plot template was called. Returning the base name -
    rather than a bare yes/no - lets the milestone be keyed and named by that base."""
    match = _UNPACK_LABEL.search(label)
    base = match.group(1) if match else None
    return base if base is not None and base.endswith("_outpost") else None


def _record_game(
    agg: FactionAggregate,
    game: PlayerGame,
    tracked_upgrades: frozenset[str],
    tracked_purchases: frozenset[str],
    tracked_powers: frozenset[str],
    include_combines: bool,
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
        if event.category == "powers" and event.label not in tracked_powers:
            continue
        if event.category == "combines" and not include_combines:
            continue
        if event.category == "fortress_hero_slots":
            key = ("heroes", f"fortress hero (command slot {event.label})")
        else:
            key = (event.category, str(event.label))
        # A hero counts only at its first fielding. A hero re-recruited after dying is a
        # revive, not a new build-order choice, and repeated recruit clicks field the same
        # unique hero once - so a hero key already seen this game (events are chronological)
        # is dropped, leaving its earliest recruit as the sole occurrence.
        if key[0] == "heroes" and key in per_label:
            continue
        per_label.setdefault(key, []).append(event.seconds)
    for (category, label), times in per_label.items():
        if category == "other" and label in tracked_purchases:
            for nth, seconds in enumerate(sorted(times), start=1):
                choice = _record(agg.other, f"{label}{nth}", game, seconds)
                choice.total += 1
                # A depth row is one instance per game by construction, so its heatmap
                # occurrence is exactly that instance's clock.
                if game.duration > 0:
                    choice.occurrences.append((seconds, game.duration))
        else:
            table = getattr(agg, "sciences" if category == "sciences" else category)
            choice = _record(table, label, game, min(times))
            choice.total += len(times)
            # Keep every instance's clock alongside its match's length for the buildings/units
            # timeline graphs and the sciences/upgrades/other purchase-timing heatmaps; a game
            # without a measurable duration (no chunks) has no match length to normalise
            # against, so it contributes nothing to either graph.
            if category in ("buildings", "units", "sciences", "upgrades", "other") and (
                game.duration > 0
            ):
                choice.occurrences.extend((seconds, game.duration) for seconds in sorted(times))

    # The standard-outpost milestone: pool every `*_outpost` unpack this game made into one
    # per-faction ChoiceStat, so it reads as a single "unpacked in N games, median ~m:ss"
    # figure rather than being split across whichever plot templates carried the claim. The
    # ChoiceStat is *labelled by the base* (a faction claims one standard outpost, so the
    # earliest-claimed base names it), so that base becomes its own translatable aggregate name.
    outpost_total = 0
    outpost_first: float | None = None
    outpost_base: str | None = None
    for (category, label), times in per_label.items():
        if category != "buildings":
            continue
        base = _outpost_base(label)
        if base is None:
            continue
        outpost_total += len(times)
        if outpost_first is None or min(times) < outpost_first:
            outpost_first, outpost_base = min(times), base
    if outpost_first is not None:
        assert outpost_base is not None  # set in lockstep with outpost_first
        if agg.outpost is None:
            agg.outpost = ChoiceStat(label=outpost_base)
        _bump(agg.outpost, game, outpost_first).total += outpost_total

    if game.stats.sciences:
        first_at, opener = game.stats.sciences[0]
        _record(agg.first_science, opener, game, first_at).total += 1


def aggregate(
    games: list[PlayerGame],
    *,
    tracked_upgrades: frozenset[str] = frozenset(),
    tracked_purchases: frozenset[str] = frozenset(),
    tracked_powers: frozenset[str] = frozenset(),
    include_combines: bool = False,
    matchups: bool = False,
    build_depth: int = 12,
) -> list[FactionAggregate]:
    """Group player-games by faction, most-played first. Upgrade events outside
    `tracked_upgrades` and power casts outside `tracked_powers` (matched on the relabelled name)
    are dropped - the raw upgrade stream is dominated by per-battalion gear purchases and the
    raw power stream by routine hero abilities and unit toggles, either of which would swamp
    the tables - as are horde combines unless `include_combines`. `other` purchases in
    `tracked_purchases` get per-instance depth rows instead of one pooled row - see the module
    docstring. `matchups` additionally folds each game into a per-enemy-faction sub-aggregate
    (`FactionAggregate.matchups`), so every pick table also exists per matchup.

    `build_depth` is how many distinct opening steps - each thing's first appearance - a game
    contributes to the build-order tree's eco sequence (`build_sequence(depth=)`); the science
    sequence is capped separately by `build_sequence`'s own `science_depth` default, since
    aggregation does not grow a matching parameter for it - that cap also bounds how many
    sciences a game's per-node annotations (`build_orders.build_tree`) can carry. `build_depth
    <= 0` skips the tree entirely here rather than asking the core for an unlimited sequence
    (where 0 means unlimited), leaving every `build_orders` None so the renderers omit the
    section."""
    factions: dict[str, FactionAggregate] = {}
    # Each aggregate's games collected here (keyed by identity - a `FactionAggregate` is
    # unhashable) and turned into its pruned tree in one pass after the loop
    # (`build_orders.build_tree`), so pruning runs once over the whole batch rather than needing
    # its own incremental insert/prune bookkeeping here.
    pending: dict[int, list[tuple[Sequence[build_orders.BuildStep], str]]] = {}
    for game in games:
        agg = factions.setdefault(game.faction, FactionAggregate(faction=game.faction))
        _record_game(
            agg, game, tracked_upgrades, tracked_purchases, tracked_powers, include_combines
        )
        # One extraction per game, collected for `agg`'s (and each matchup's) tree; an empty
        # sequence is still collected, so the tree's root ends up counting every game.
        steps: Sequence[build_orders.BuildStep] = ()
        if build_depth > 0:
            steps = build_orders.build_sequence(game.stats, depth=build_depth)
            pending.setdefault(id(agg), []).append((steps, game.outcome))
        if matchups:
            for enemy in dict.fromkeys(game.opponents):  # dedupe: one count per game
                sub = agg.matchups.setdefault(enemy, FactionAggregate(faction=enemy))
                _record_game(
                    sub, game, tracked_upgrades, tracked_purchases, tracked_powers, include_combines
                )
                if build_depth > 0:
                    pending.setdefault(id(sub), []).append((steps, game.outcome))

    if build_depth > 0:
        for agg in factions.values():
            agg_games = pending.get(id(agg))
            if agg_games:
                agg.build_orders = build_orders.build_tree(
                    agg_games, min_games=_BUILD_MIN_GAMES, min_share=_BUILD_MIN_SHARE
                )
            for sub in agg.matchups.values():
                sub_games = pending.get(id(sub))
                if sub_games:
                    sub.build_orders = build_orders.build_tree(
                        sub_games, min_games=_BUILD_MIN_GAMES, min_share=_BUILD_MIN_SHARE
                    )

    return sorted(factions.values(), key=lambda a: (-a.games, a.faction))


def _percent(rate: float | None) -> str:
    return f"{round(rate * 100):3d}%" if rate is not None else "   -"


def _choice_header(title: str) -> str:
    return f"  {title}  (games - won-lost - win% - median first - total):"


def _choice_lines(title: str, table: dict[str, ChoiceStat]) -> list[str]:
    if not table:
        return []
    ranked = _ranked(table)
    width = max(len(c.label) for c in ranked)
    lines = [_choice_header(title)]
    for choice in ranked:
        first = f"~{clock(choice.median_first)}" if choice.median_first is not None else "-"
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


def _outpost_value(agg: FactionAggregate, translate: Translate = _identity) -> str | None:
    """The standard-outpost milestone as a compact `<base> ~m:ss (N/M)` string - the unpacked
    base (shown through `translate`, so a custom name for it appears), the median clock of the
    first unpack, and how many of the faction's games unpacked one - or None when no game
    claimed a standard outpost (so callers can omit the metric entirely)."""
    if agg.outpost is None or agg.outpost.median_first is None:
        return None
    base = translate(agg.outpost.label) if agg.outpost.label else "outpost"
    return f"{base} ~{clock(agg.outpost.median_first)} ({agg.outpost.games}/{agg.games})"


def _faction_summary(
    agg: FactionAggregate, translate: Translate = _identity, *, include_outpost: bool = True
) -> str:
    length = f", median length {clock(median(agg.durations))}" if agg.durations else ""
    undetermined = f", {agg.undetermined} undetermined" if agg.undetermined else ""
    outpost_value = _outpost_value(agg, translate) if include_outpost else None
    outpost = f", outpost {outpost_value}" if outpost_value else ""
    return (
        f"{agg.games} games: {agg.wins}-{agg.losses} "
        f"({_percent(agg.win_rate).strip()}){undetermined}{length}{outpost}"
    )


# The per-faction pick tables in display order:
# (section title, FactionAggregate attribute, markdown label-column header). Powers are not
# a flat section: they render nested under Units (see `_power_lines` / `_html_tables`), only
# for the caller's tracked set. Horde combines only appear with `include_combines`.
_SECTIONS = (
    ("Sciences", "sciences", "Science"),
    ("First science", "first_science", "Science"),
    ("Buildings", "buildings", "Building"),
    ("Units", "units", "Unit"),
    ("Heroes", "heroes", "Hero"),
    ("Upgrades", "upgrades", "Upgrade"),
    ("Other purchases", "other", "Purchase"),
    ("Horde combines", "combines", "Combine"),
)

# The sections that carry a timing graph in the HTML report, and which kind: many-instance
# categories get the Buildings/Units timeline, at-most-once-per-row categories the purchase-
# timing heatmap (see `_HEATMAP_SCRIPT`'s comment for why). The heatmap sections each carry
# their own summary blurb, since "science" / "upgrade" / "purchase" read differently.
_TIMELINE_SECTIONS = frozenset({"buildings", "units"})
_HEATMAP_REC = {
    "sciences": "when each science is bought across match length",
    "upgrades": "when each upgrade is researched across match length",
    "other": "when each purchase is made across match length",
}
_GRAPH_SECTIONS = _TIMELINE_SECTIONS | frozenset(_HEATMAP_REC)


def _power_lines(heading: str, table: dict[str, ChoiceStat]) -> list[str]:
    """The tracked powers as a sub-block nested one level under the Units section: a titled
    header (the casting unit's name) and the same columns as `_choice_lines`, indented deeper."""
    if not table:
        return []
    ranked = _ranked(table)
    width = max(len(c.label) for c in ranked)
    lines = [f"    {heading}:"]
    for choice in ranked:
        first = f"~{clock(choice.median_first)}" if choice.median_first is not None else "-"
        lines.append(
            f"      {choice.label:{width}s}  {choice.games:3d}  "
            f"{choice.wins:2d}-{choice.losses:<2d} {_percent(choice.win_rate)}  "
            f"{first:>6s}  x{choice.total}"
        )
    return lines


def _section_lines(agg: FactionAggregate, powers_heading: str) -> list[str]:
    """One aggregate's pick tables as text, with the tracked powers nested under Units (their
    caster - Edain's Loremaster/Lichtbringer - is a unit, not a recruitable hero). When powers
    exist but no unit was recruited, a bare Units header still anchors them."""
    lines: list[str] = []
    for title, attribute, _ in _SECTIONS:
        if attribute == "units":
            unit_lines = _choice_lines(title, agg.units)
            power_lines = _power_lines(powers_heading, agg.powers)
            if power_lines and not unit_lines:
                unit_lines = [_choice_header(title)]
            lines.extend(unit_lines)
            lines.extend(power_lines)
        elif attribute == "heroes":
            hero_lines = _choice_lines(title, agg.heroes)
            if hero_lines:  # caveat line right under the Heroes header
                hero_lines.insert(1, f"    ! {_HERO_SECTION_NOTE}")
            lines.extend(hero_lines)
        else:
            lines.extend(_choice_lines(title, getattr(agg, attribute)))
    return lines


def _build_order_present(agg: FactionAggregate) -> bool:
    """Whether `agg` carries a build-order tree worth rendering: one exists and it survived
    pruning with at least one branch (an empty pruned tree reads as absent)."""
    return agg.build_orders is not None and bool(agg.build_orders.children)


def _build_path_label(
    path: list[BuildNode],
    translate: Translate,
    *,
    arrow: str,
    times: str,
    esc: Callable[[str], str] = _identity,
) -> str:
    """One opening path as its step labels joined by `arrow`, each label through `translate`
    (then `esc`, e.g. HTML-escaping) with a `{times}<count>` suffix when the step's typical
    count is above one - so `[Farm x2, Barracks]` reads `Farm x2 -> Barracks` for text and
    `Farm &times;2 &rarr; Barracks` for HTML."""
    parts = []
    for node in path:
        label = esc(translate(node.label))
        if node.median_count is not None and node.median_count > 1:
            label += f"{times}{node.median_count}"
        parts.append(label)
    return arrow.join(parts)


def _science_line(
    leaf: BuildNode,
    translate: Translate,
    *,
    arrow: str,
    esc: Callable[[str], str] = _identity,
) -> str:
    """One opening row's science summary, read off the leaf's full science order
    (`BuildNode.sciences_taken`): every label bought by at least `_SCIENCE_LINE_MIN_SHARE` of the
    leaf's games, sorted by median clock (ties by label), each formatted `label (m:ss, NN%)` -
    the label through the same `translate`/`esc` treatment `_build_path_label` gives the main
    label, the percent the label's share of the leaf's games, rounded. Joined with `arrow`, the
    same one the caller used for the main label. Empty when nothing clears the floor (or the leaf
    has no games)."""
    if not leaf.games:
        return ""
    entries = [
        (label, clocks)
        for label, clocks in leaf.sciences_taken.items()
        if len(clocks) / leaf.games >= _SCIENCE_LINE_MIN_SHARE
    ]
    entries.sort(key=lambda entry: (median(entry[1]), entry[0]))
    parts = []
    for label, clocks in entries:
        pct = round(len(clocks) / leaf.games * 100)
        parts.append(f"{esc(translate(label))} ({clock(median(clocks))}, {pct}%)")
    return arrow.join(parts)


def _build_order_lines(agg: FactionAggregate, translate: Translate = _identity) -> list[str]:
    """One aggregate's common openings as a `Build orders` text block mirroring `_choice_lines`
    (`_build_order_present` gates it, empty otherwise); `~complete` is the leaf's own median
    clock. A row is followed by an indented `sciences: ...` continuation line naming the leaf's
    typical science order (`_science_line`), omitted when nothing clears
    `_SCIENCE_LINE_MIN_SHARE`."""
    if not _build_order_present(agg):
        return []
    assert agg.build_orders is not None
    paths = build_orders.openings(agg.build_orders, limit=8)
    labels = [_build_path_label(p, translate, arrow=" -> ", times=" x") for p in paths]
    width = max(len(label) for label in labels)
    lines = ["  Build orders  (games - won-lost - win% - ~complete):"]
    for label, path in zip(labels, paths, strict=True):
        leaf = path[-1]
        complete_at = leaf.median_seconds
        complete = f"~{clock(complete_at)}" if complete_at is not None else "-"
        lines.append(
            f"    {label:{width}s}  {leaf.games:3d}  "
            f"{leaf.wins:2d}-{leaf.losses:<2d} {_percent(leaf.win_rate)}  {complete:>6s}"
        )
        science_line = _science_line(leaf, translate, arrow=" -> ")
        if science_line:
            lines.append(f"      sciences: {science_line}")
    return lines


def render_aggregate(
    corpus: Corpus,
    factions: list[FactionAggregate],
    *,
    powers_heading: str = DEFAULT_POWERS_HEADING,
) -> list[str]:
    """The corpus aggregation as text: a per-faction block of win rate, the common openings,
    science picks (overall and opening), and the building/unit/hero pick tables (tracked powers
    nested under Units as `powers_heading`), followed by the same block per matchup when the
    aggregation carried them."""
    lines = [f"Corpus: {_corpus_summary(corpus)}", f"Note: {_HERO_NOTE}", ""]
    for agg in factions:
        lines.append(f"== {agg.faction}  - {_faction_summary(agg)}")
        lines.extend(_build_order_lines(agg))
        lines.extend(_section_lines(agg, powers_heading))
        for enemy, sub in _ranked_matchups(agg):
            lines.append(f"  -- vs {enemy}  - {_faction_summary(sub, include_outpost=False)}")
            lines.extend(_build_order_lines(sub))
            lines.extend(_section_lines(sub, powers_heading))
        lines.append("")
    return lines


def _cell(label: str) -> str:
    return label.replace("|", "\\|")


def _markdown_table(
    table: dict[str, ChoiceStat], title: str, column: str, heading: str
) -> list[str]:
    """One pick-category table as markdown, titled at `heading` depth; empty when the table
    is (so a category nobody picked leaves no heading)."""
    if not table:
        return []
    lines = [
        f"{heading} {title}",
        "",
        f"| {column} | Games | W-L | Win % | Median first | Total |",
        "|---|--:|--:|--:|--:|--:|",
    ]
    for choice in _ranked(table):
        first = clock(choice.median_first) if choice.median_first is not None else "-"
        lines.append(
            f"| {_cell(choice.label)} | {choice.games} "
            f"| {choice.wins}-{choice.losses} | {_percent(choice.win_rate).strip()} "
            f"| {first} | {choice.total} |"
        )
    lines.append("")
    return lines


def _markdown_tables(agg: FactionAggregate, heading: str, powers_heading: str) -> list[str]:
    """The pick-category tables of one aggregate as markdown, titled at `heading` depth, with
    the tracked powers nested a heading level deeper under Units (their caster is a unit; a bare
    Units heading anchors them when no unit was recruited)."""
    lines: list[str] = []
    for title, attribute, column in _SECTIONS:
        if attribute == "units":
            unit_lines = _markdown_table(agg.units, title, column, heading)
            power_lines = _markdown_table(agg.powers, powers_heading, "Power", heading + "#")
            if power_lines and not unit_lines:
                unit_lines = [f"{heading} {title}", ""]
            lines.extend(unit_lines)
            lines.extend(power_lines)
        elif attribute == "heroes":
            hero_lines = _markdown_table(agg.heroes, title, column, heading)
            if hero_lines:
                # After the heading and its blank line, before the table: an italic caveat.
                hero_lines[2:2] = [f"_{_HERO_SECTION_NOTE}_", ""]
            lines.extend(hero_lines)
        else:
            lines.extend(_markdown_table(getattr(agg, attribute), title, column, heading))
    return lines


def _build_order_markdown(agg: FactionAggregate, heading: str) -> list[str]:
    """One aggregate's common openings as a `Build orders` markdown table at `heading` depth
    (`_build_order_present` gates it, empty otherwise); `~Complete` is the leaf's own median
    clock. Pipes in a step label are escaped through `_cell` so a label never breaks the table; a
    non-empty science line (`_science_line`) appends as a `<br>sciences: ...` continuation inside
    the same cell (GitHub renders `<br>` in table cells)."""
    if not _build_order_present(agg):
        return []
    assert agg.build_orders is not None
    lines = [
        f"{heading} Build orders",
        "",
        "| Build order | Games | W-L | Win % | ~Complete |",
        "|---|--:|--:|--:|--:|",
    ]
    for path in build_orders.openings(agg.build_orders, limit=8):
        leaf = path[-1]
        label = _build_path_label(path, _identity, arrow=" -> ", times=" x", esc=_cell)
        complete_at = leaf.median_seconds
        complete = clock(complete_at) if complete_at is not None else "-"
        science_line = _science_line(leaf, _identity, arrow=" -> ", esc=_cell)
        if science_line:
            label += f"<br>sciences: {science_line}"
        lines.append(
            f"| {label} | {leaf.games} | {leaf.wins}-{leaf.losses} "
            f"| {_percent(leaf.win_rate).strip()} | {complete} |"
        )
    lines.append("")
    return lines


def render_aggregate_markdown(
    corpus: Corpus,
    factions: list[FactionAggregate],
    *,
    powers_heading: str = DEFAULT_POWERS_HEADING,
) -> list[str]:
    """The same aggregation as GitHub markdown: a heading per faction, the common openings, and
    a table per pick category (tracked powers nested under Units as `powers_heading`), then a
    `### vs <enemy>` block per matchup when the aggregation carried them."""
    lines = ["# Replay corpus stats", "", _corpus_summary(corpus), "", f"_{_HERO_NOTE}_", ""]
    for agg in factions:
        lines.extend([f"## {_cell(agg.faction)} - {_faction_summary(agg)}", ""])
        lines.extend(_build_order_markdown(agg, "###"))
        lines.extend(_markdown_tables(agg, "###", powers_heading))
        for enemy, sub in _ranked_matchups(agg):
            lines.extend(
                [f"### vs {_cell(enemy)} - {_faction_summary(sub, include_outpost=False)}", ""]
            )
            lines.extend(_build_order_markdown(sub, "####"))
            lines.extend(_markdown_tables(sub, "####", powers_heading))
    return lines


# The HTML report's stylesheet. Colors are CSS custom properties so the dark theme swaps
# in one place; the win-rate bar is a diverging mark around the 50% midpoint (blue above,
# red below, neutral track), so a faction's polarity reads before the number does. The
# `--s1`..`--s8` slots are the timeline graphs' categorical series palette in its fixed
# order (a validated CVD-safe ordering; the dark column is the same eight hues re-stepped
# for the dark surface, not an automatic flip) - a ninth series never gets a new hue, it
# reuses the cycle with a dash pattern as the distinguishing second channel.
_HTML_STYLE = """\
:root {
  --plane: #f9f9f7; --surface: #fcfcfb; --ink: #0b0b0b; --ink-2: #52514e;
  --muted: #898781; --grid: #e1e0d9; --ring: rgba(11,11,11,0.10);
  --track: #f0efec; --above: #2a78d6; --below: #e34948;
  --warn-ink: #8a5a00; --warn-bg: #fbeccb;
  --s1: #2a78d6; --s2: #1baf7a; --s3: #eda100; --s4: #008300;
  --s5: #4a3aa7; --s6: #e34948; --s7: #e87ba4; --s8: #eb6834;
}
@media (prefers-color-scheme: dark) {
  :root {
    --plane: #0d0d0d; --surface: #1a1a19; --ink: #ffffff; --ink-2: #c3c2b7;
    --muted: #898781; --grid: #2c2c2a; --ring: rgba(255,255,255,0.10);
    --track: #383835; --above: #3987e5; --below: #e66767;
    --warn-ink: #e7b95a; --warn-bg: #3a2f14;
    --s1: #3987e5; --s2: #199e70; --s3: #c98500; --s4: #008300;
    --s5: #9085e9; --s6: #e66767; --s7: #d55181; --s8: #d95926;
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
h4 { font-size: 12px; margin: 14px 0 6px 16px; color: var(--ink-2); text-transform: uppercase; letter-spacing: 0.04em; }
h4 + .tablewrap { margin-left: 16px; }
.ficon { height: 1.15em; width: auto; vertical-align: -0.2em; margin-right: 6px; border-radius: 3px; }
h2 .ficon { height: 1.5em; vertical-align: -0.28em; margin-right: 9px; }
p.meta { color: var(--ink-2); margin: 0 0 16px; }
.tiles { display: flex; flex-wrap: wrap; gap: 10px; margin: 12px 0 4px; }
.tile {
  background: var(--surface); border: 1px solid var(--ring); border-radius: 8px;
  padding: 10px 14px; min-width: 108px;
}
.tile .k { font-size: 11px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.05em; }
.tile .v { font-size: 20px; font-weight: 600; margin-top: 2px; }
.tile .v small { font-size: 12px; font-weight: 400; color: var(--ink-2); }
/* padding-bottom keeps the horizontal scrollbar off the last row when a table overflows. */
.tablewrap { overflow-x: auto; padding-bottom: 10px; background: var(--surface); border: 1px solid var(--ring); border-radius: 8px; }
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
p.note {
  margin: 0 0 8px; padding: 6px 10px; border-radius: 6px; font-size: 12px;
  color: var(--warn-ink); background: var(--warn-bg);
}
a { color: var(--above); text-decoration: none; }
a:hover { text-decoration: underline; }
.nav {
  display: inline-block; margin: 6px 0 8px; padding: 9px 15px; background: var(--surface);
  border: 1px solid var(--ring); border-radius: 8px; font-weight: 600; color: var(--ink);
}
.nav:hover { text-decoration: none; border-color: var(--above); }
.toc {
  margin: 14px 0 24px; padding: 12px 16px; background: var(--surface);
  border: 1px solid var(--ring); border-radius: 8px;
}
.toc-title {
  margin: 0 0 8px; font-size: 11px; color: var(--muted);
  text-transform: uppercase; letter-spacing: 0.05em; font-weight: 600;
}
.toc ul { margin: 0; padding: 0; list-style: none; display: flex; flex-wrap: wrap; gap: 4px 20px; }
.toc li { line-height: 1.7; }
.toc .ficon { height: 1em; vertical-align: -0.15em; margin-right: 5px; }
th.sortable { cursor: pointer; user-select: none; }
th.sortable:hover { color: var(--ink-2); }
th.sortable.asc::after { content: " \\2191"; color: var(--above); }
th.sortable.desc::after { content: " \\2193"; color: var(--above); }
.serieskey { display: inline-flex; align-items: center; gap: 5px; margin-right: 8px; vertical-align: middle; }
.serieskey input { margin: 0; cursor: pointer; }
.swatch { width: 14px; height: 4px; border-radius: 2px; background: var(--c, var(--muted)); }
.swatch.dashed { background: repeating-linear-gradient(90deg, var(--c, var(--muted)) 0 4px, transparent 4px 6px); }
details.timeline { margin: 6px 0 10px; }
details.timeline > summary { padding: 8px 14px; font-size: 13px; font-weight: 500; }
.tl-head { display: flex; align-items: center; gap: 10px; margin: 4px 0 10px; }
.tl-toggle { display: inline-flex; border: 1px solid var(--ring); border-radius: 6px; overflow: hidden; }
.tl-toggle button {
  border: none; background: none; color: var(--ink-2); font: inherit; font-size: 12px;
  padding: 3px 10px; cursor: pointer;
}
.tl-toggle button.on { background: var(--track); color: var(--ink); font-weight: 600; }
.tl-note { font-size: 11px; color: var(--muted); }
.tl-wrap { position: relative; }
.tl-svg svg { display: block; width: 100%; height: auto; }
.tl-svg text { fill: var(--muted); font: 10px system-ui, -apple-system, "Segoe UI", sans-serif; }
.tl-svg .grid { stroke: var(--grid); }
.tl-svg .series { fill: none; stroke-width: 2; stroke-linecap: round; stroke-linejoin: round; }
.tl-svg .tl-cross { stroke: var(--muted); stroke-dasharray: 2 3; }
.tl-svg .tl-dot { stroke: var(--surface); stroke-width: 1.5; }
.tl-tip {
  position: absolute; pointer-events: none; background: var(--surface);
  border: 1px solid var(--ring); border-radius: 6px; padding: 4px 8px;
  font-size: 11px; color: var(--ink-2); white-space: nowrap;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.15);
}
.tl-tip b { color: var(--ink); font-weight: 600; }
details.heatmap { margin: 6px 0 10px; }
details.heatmap > summary { padding: 8px 14px; font-size: 13px; font-weight: 500; }
.hm-wrap { position: relative; }
.hm-grid { display: flex; flex-direction: column; gap: 2px; }
.hm-row { display: flex; align-items: center; gap: 6px; height: 18px; }
.hm-label {
  width: 200px; flex: 0 0 auto; font-family: ui-monospace, Consolas, monospace; font-size: 12px;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.hm-label .n { color: var(--muted); margin-left: 5px; }
.hm-cells { display: flex; flex: 1 1 auto; gap: 1px; height: 100%; }
.hm-cell { flex: 1; height: 100%; border-radius: 2px; background: var(--track); }
.hm-axis { position: relative; height: 14px; margin: 3px 0 0 206px; }
.hm-axis span { position: absolute; font-size: 10px; color: var(--muted); white-space: nowrap; }
details.botree { margin: 6px 0 10px; }
details.botree > summary { padding: 8px 14px; font-size: 13px; font-weight: 500; }
.bo-rows { margin: 4px 0 2px; }
.bo-row { display: flex; align-items: center; gap: 8px; height: 24px; padding: 0 6px; border-radius: 4px; }
.bo-row[hidden] { display: none; }
.bo-row.bo-open { cursor: pointer; }
.bo-row.bo-open:hover { background: var(--track); }
.bo-mark { width: 12px; flex: 0 0 auto; text-align: center; font-size: 11px; color: var(--muted); }
.bo-dot { width: 10px; height: 10px; flex: 0 0 auto; border-radius: 50%; }
.bo-label {
  flex: 1 1 auto; min-width: 0; font-family: ui-monospace, Consolas, monospace; font-size: 12px;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.bo-share { flex: 0 0 auto; min-width: 36px; text-align: right; font-weight: 600; color: var(--ink); font-variant-numeric: tabular-nums; }
.bo-games, .bo-wl, .bo-time { flex: 0 0 auto; color: var(--muted); font-size: 12px; font-variant-numeric: tabular-nums; }
.bo-games { min-width: 26px; text-align: right; }
.bo-wl { min-width: 34px; text-align: right; }
.bo-time { min-width: 34px; text-align: right; }
.bo-vs { flex: 0 0 auto; min-width: 40px; text-align: right; font-size: 11px; }
.bo-sci { margin: 2px 0 0; font-size: 11px; color: var(--muted); }
.ice-legend { display: flex; flex-wrap: wrap; gap: 4px 14px; margin: 0 0 4px; font-size: 11px; color: var(--muted); }
.ice-legend-item { display: inline-flex; align-items: center; gap: 5px; }
.ice-sci { min-height: 14px; margin: 0 0 6px; font-size: 11px; color: var(--muted); }
.ice-sci b { color: var(--ink); }
.bo-ice-wrap { position: relative; margin: 4px 0 10px; }
.bo-ice svg { display: block; width: 100%; height: auto; }
.ice-box { cursor: default; }
.ice-box.ice-pin { stroke: var(--ink); stroke-width: 2; }
/* The label reads over saturated --sN fills in both themes: --ink text haloed by --surface
   (paint-order draws the stroke behind the fill), so neither an --ink nor an --surface fill
   alone has to read on every hue. */
.ice-label {
  fill: var(--ink); paint-order: stroke; stroke: var(--surface); stroke-width: 2px;
  stroke-linejoin: round; pointer-events: none;
  font: 10px system-ui, -apple-system, "Segoe UI", sans-serif;
}
"""


# Client-side column sorting for every rendered page, self-contained (no external assets) to
# match the reports themselves. Each table header becomes clickable; a click sorts the rows by
# that column and toggles direction (first click descending for numeric columns, ascending for
# text). The sort key is read straight off each cell's text - clocks (`m:ss`), percentages,
# `x`-prefixed totals and signed deltas all parse - so no table-generation code has to emit
# anything extra. A column is treated as numeric when most of its cells parse as numbers; blank
# / dash cells always sort last. The matchup matrix (`table.matrix`) is left alone: its cells
# pack two numbers and its axes are factions, not a sortable column.
_SORT_SCRIPT = """\
(function () {
  function key(cell) {
    var s = cell.textContent.trim();
    if (s === '' || s === '-' || s === '\\u2013' || s === '\\u2014') return null;
    var m = s.match(/^(\\d+):([0-5]\\d)$/);
    if (m) return (+m[1]) * 60 + (+m[2]);
    var f = parseFloat(s.replace(/^x/, '').replace(/%$/, '').replace(/,/g, ''));
    return isNaN(f) ? null : f;
  }
  function sortRows(table, col, numeric, dir) {
    var body = table.tBodies[0];
    var rows = Array.prototype.slice.call(body.rows);
    rows.forEach(function (r, i) { r._i = i; });
    rows.sort(function (a, b) {
      var r;
      if (numeric) {
        var ka = key(a.cells[col]), kb = key(b.cells[col]);
        if (ka === null && kb === null) r = 0;
        else if (ka === null) r = 1;
        else if (kb === null) r = -1;
        else r = ka - kb;
      } else {
        r = a.cells[col].textContent.trim().localeCompare(b.cells[col].textContent.trim());
      }
      return r ? (dir === 'asc' ? r : -r) : a._i - b._i;
    });
    rows.forEach(function (r) { body.appendChild(r); });
  }
  Array.prototype.forEach.call(document.querySelectorAll('table:not(.matrix)'), function (table) {
    if (!table.tHead || !table.tBodies.length) return;
    var ths = table.tHead.rows[0].cells;
    Array.prototype.forEach.call(ths, function (th, col) {
      th.classList.add('sortable');
      th.addEventListener('click', function () {
        var vals = 0, nums = 0;
        Array.prototype.forEach.call(table.tBodies[0].rows, function (row) {
          var c = row.cells[col];
          if (!c) return;
          if (c.textContent.trim() !== '') vals++;
          if (key(c) !== null) nums++;
        });
        var numeric = nums * 2 >= vals;
        var dir = th.dataset.dir === 'asc' ? 'desc'
                : th.dataset.dir === 'desc' ? 'asc'
                : (numeric ? 'desc' : 'asc');
        Array.prototype.forEach.call(ths, function (o) {
          delete o.dataset.dir;
          o.classList.remove('asc', 'desc');
        });
        th.dataset.dir = dir;
        th.classList.add(dir);
        sortRows(table, col, numeric, dir);
      });
    });
  });
})();
"""


# The timeline graphs for the Buildings and Units sections, self-contained like the sort
# script. Each `details.timeline` block carries a JSON payload of raw per-instance clocks
# (each order's seconds paired with its own match's duration), and this script bins them
# client-side, so both toggles rebin and re-derive the same data. The x toggle picks the
# axis: % of match length (the default - every order normalised by its own game, 20 bins
# of 5%) or the absolute game clock (fixed-size bins chosen from the section's longest
# match, ticks as m:ss). The y toggle picks what a bin's value means:
#   share (the default) - the series' orders over all *visible* series' orders in the bin,
#     "of what players were buying at this stage, how much was X"; unchecking rows
#     re-normalises the denominator to the visible set, so two checked rows read as a
#     head-to-head, and a bin no visible series bought in has no share at all - a gap that
#     breaks the line, never a fabricated 0;
#   CP share (only when the block ships per-series `cp` weights - the Units tables, via the
#     renderer's `weight` hook) - share with each series' orders weighted by the template's
#     CommandPoints, "of the army capacity bought at this stage, how much was X"; an elite
#     order outweighs a cheap one instead of counting the same, a 0-CP series (a free
#     summon) draws along the zero line rather than vanishing, and the order stream carries
#     no unit deaths, so this is CP *spent* per stage, not a standing-army snapshot;
#   lifecycle - the series' orders over its own total, so each curve integrates to 100%
#     and reads as the pure timing arc, independent of what else is visible;
#   count - the raw corpus orders per bin, unnormalised;
#   cumulative - the running % of the series' own orders, 0 to 100% and monotonic.
# Per-series bin counts are smoothed first - a centred 3-bin moving average, an edge bin
# averaging over the neighbours it has - and share/lifecycle/count derive from the smoothed
# counts; the share denominator is the sum of the smoothed visible counts, so shares still
# sum to ~1 with no null-juggling inside the smoother. Cumulative alone runs over the raw
# counts: it is already noise-proof and must stay monotonic. One SVG line per series,
# coloured from the `--s1`..`--s8` palette slots in row order (a ninth series reuses the
# cycle dashed - a second channel, never a new hue); the same slot is stamped onto the
# row's swatch, so the pick table doubles as the legend. Unchecking a row's checkbox drops
# its line and rescales Y to what remains; the label header's select-all drives every row
# at once, reads indeterminate when they disagree, and stops its clicks from bubbling into
# the header's column sort. Charts render lazily on first open (a matchup-heavy page holds
# many), and the SVG is built as markup handed to innerHTML - no namespace plumbing, and
# nothing external. Hovering reads out the nearest series point in the current mode's
# terms (skipping gap bins), and the note under the toggles names the mode.
_GRAPH_SCRIPT = """\
(function () {
  var W = 720, H = 240;
  var PAD = { l: 46, r: 14, t: 10, b: 28 };
  var STEPS = [15, 30, 60, 120, 300, 600, 1200];
  var NOTES = {
    share: 'share of visible series\\' orders per bin',
    cpshare: 'share of visible series\\' command points per bin',
    lifecycle: '% of the unit\\'s own orders per bin',
    count: 'total orders per bin',
    cumulative: 'cumulative % of the unit\\'s orders'
  };

  function clock(seconds) {
    var m = Math.floor(seconds / 60), s = Math.round(seconds % 60);
    if (s === 60) { m += 1; s = 0; }
    return m + ':' + (s < 10 ? '0' : '') + s;
  }
  function fmt(v) { return v ? parseFloat(v.toPrecision(3)).toString() : '0'; }
  function asPct(v) { return fmt(v * 100) + '%'; }
  function esc(s) { return s.replace(/&/g, '&amp;').replace(/</g, '&lt;'); }
  function slot(i) { return 'var(--s' + ((i % 8) + 1) + ')'; }
  function niceStep(raw) {
    var mag = Math.pow(10, Math.floor(Math.log(raw) / Math.LN10));
    var norm = raw / mag;
    return (norm <= 1 ? 1 : norm <= 2 ? 2 : norm <= 5 ? 5 : 10) * mag;
  }
  function total(arr) {
    var t = 0;
    arr.forEach(function (v) { t += v; });
    return t;
  }

  Array.prototype.forEach.call(document.querySelectorAll('details.timeline'), function (details) {
    var id = details.dataset.graph;
    var payload = JSON.parse(details.querySelector('script.tl-data').textContent);
    var wrap = details.querySelector('.tl-wrap');
    var tip = details.querySelector('.tl-tip');
    var note = details.querySelector('.tl-note');
    var boxes = document.querySelectorAll('input[data-graph="' + id + '"]');
    var master = document.querySelector('input[data-graph-all="' + id + '"]');
    var mode = 'pct';
    var ymode = 'share';
    var rendered = false;
    var view = null;

    function syncMaster() {
      if (!master) return;
      var on = 0;
      Array.prototype.forEach.call(boxes, function (box) { if (box.checked) on++; });
      master.checked = on === boxes.length;
      master.indeterminate = on > 0 && on < boxes.length;
    }

    Array.prototype.forEach.call(boxes, function (box) {
      var i = +box.dataset.series;
      var swatch = box.nextElementSibling;
      if (swatch) {
        swatch.style.setProperty('--c', slot(i));
        if (i >= 8) swatch.classList.add('dashed');
      }
      box.addEventListener('change', function () { syncMaster(); if (rendered) render(); });
    });

    if (master) {
      // The select-all lives inside a sortable column header: swallow the click so ticking
      // it never also re-sorts the table.
      master.addEventListener('click', function (e) { e.stopPropagation(); });
      master.addEventListener('change', function () {
        Array.prototype.forEach.call(boxes, function (box) { box.checked = master.checked; });
        if (rendered) render();
      });
    }

    function binning() {
      if (mode === 'pct') return { bins: 20, size: 5, pct: true };
      var max = 0;
      payload.series.forEach(function (s) {
        s.occ.forEach(function (p) { if (p[1] > max) max = p[1]; });
      });
      if (!max) max = 60;
      var size = STEPS[STEPS.length - 1];
      for (var i = 0; i < STEPS.length; i++) {
        if (Math.ceil(max / STEPS[i]) <= 24) { size = STEPS[i]; break; }
      }
      return { bins: Math.max(1, Math.ceil(max / size)), size: size, pct: false };
    }

    function counts(s, spec) {
      var out = [], b;
      for (b = 0; b < spec.bins; b++) out.push(0);
      s.occ.forEach(function (p) {
        if (spec.pct) b = Math.floor(p[0] / p[1] * spec.bins);
        else b = Math.floor(p[0] / spec.size);
        out[Math.max(0, Math.min(spec.bins - 1, b))] += 1;
      });
      return out;
    }

    // The centred 3-bin moving average the derived modes read; an edge bin averages over
    // the neighbours it has.
    function smooth(raw) {
      return raw.map(function (c, b) {
        var sum = c, n = 1;
        if (b > 0) { sum += raw[b - 1]; n += 1; }
        if (b + 1 < raw.length) { sum += raw[b + 1]; n += 1; }
        return sum / n;
      });
    }

    function render() {
      rendered = true;
      var spec = binning();
      var series = [];
      Array.prototype.forEach.call(boxes, function (box) {
        var i = +box.dataset.series;
        if (box.checked && payload.series[i]) {
          var raw = counts(payload.series[i], spec);
          series.push({ i: i, label: payload.series[i].label, raw: raw, sm: smooth(raw) });
        }
      });
      // Derive what each visible series plots in the current y-mode. share, lifecycle
      // and count read the smoothed counts; cumulative runs over the raw counts, which is
      // already noise-proof and must stay monotonic. A null value is a gap the path breaks
      // over: a share where no visible series bought anything, or a series with no orders
      // at all - never a fabricated 0.
      if (ymode === 'share' || ymode === 'cpshare') {
        // cpshare is share with each series' smoothed counts scaled by its CommandPoints
        // weight (cp, shipped per series only when the renderer had a `weight` hook). A
        // 0-CP series contributes nothing to the denominator and draws along zero; a bin
        // where every visible series weighs out entirely gaps like an empty share bin.
        var denom = [];
        series.forEach(function (l) {
          l.w = ymode === 'cpshare' ? (payload.series[l.i].cp || 0) : 1;
          l.sm.forEach(function (v, b) { denom[b] = (denom[b] || 0) + v * l.w; });
        });
        series.forEach(function (l) {
          l.vals = l.sm.map(function (v, b) {
            return denom[b] > 0 ? v * l.w / denom[b] : null;
          });
        });
      } else if (ymode === 'lifecycle') {
        series.forEach(function (l) {
          var t = total(l.sm);
          l.vals = l.sm.map(function (v) { return t > 0 ? v / t : null; });
        });
      } else if (ymode === 'count') {
        series.forEach(function (l) { l.vals = l.sm; });
      } else {
        series.forEach(function (l) {
          var t = total(l.raw), run = 0;
          l.vals = l.raw.map(function (c) { run += c; return t > 0 ? run / t : null; });
        });
      }
      var pctY = ymode !== 'count';
      var ymax = 0;
      series.forEach(function (l) {
        l.vals.forEach(function (v) { if (v !== null && v > ymax) ymax = v; });
      });
      if (!ymax) ymax = 1;
      var step = niceStep(ymax / 4);
      var top = Math.ceil(ymax / step - 1e-9) * step;
      var pw = W - PAD.l - PAD.r, ph = H - PAD.t - PAD.b;
      function x(b) { return PAD.l + (b + 0.5) / spec.bins * pw; }
      function y(v) { return PAD.t + ph - v / top * ph; }
      var svg = [], k, t, tx;
      for (k = 0; k * step <= top + step / 2; k++) {
        var gy = y(k * step);
        svg.push('<line class="grid" x1="' + PAD.l + '" x2="' + (W - PAD.r) +
          '" y1="' + gy.toFixed(1) + '" y2="' + gy.toFixed(1) + '"/>');
        svg.push('<text x="' + (PAD.l - 6) + '" y="' + (gy + 3).toFixed(1) +
          '" text-anchor="end">' + (pctY ? asPct(k * step) : fmt(k * step)) + '</text>');
      }
      if (spec.pct) {
        for (t = 0; t <= 100; t += 25) {
          tx = PAD.l + t / 100 * pw;
          svg.push('<text x="' + tx.toFixed(1) + '" y="' + (H - PAD.b + 15) +
            '" text-anchor="middle">' + t + '%</text>');
        }
      } else {
        var span = spec.bins * spec.size;
        var tickStep = spec.size * Math.max(1, Math.ceil(spec.bins / 6));
        for (t = 0; t <= span; t += tickStep) {
          tx = PAD.l + t / span * pw;
          svg.push('<text x="' + tx.toFixed(1) + '" y="' + (H - PAD.b + 15) +
            '" text-anchor="middle">' + clock(t) + '</text>');
        }
      }
      series.forEach(function (l) {
        var d = '', pen = false;
        l.vals.forEach(function (v, b) {
          if (v === null) { pen = false; return; }
          d += (pen ? 'L' : 'M') + x(b).toFixed(1) + ' ' + y(v).toFixed(1);
          pen = true;
        });
        if (!d) return;
        svg.push('<path class="series" style="stroke: ' + slot(l.i) + '"' +
          (l.i >= 8 ? ' stroke-dasharray="5 4"' : '') + ' d="' + d + '"/>');
      });
      svg.push('<line class="tl-cross" y1="' + PAD.t + '" y2="' + (H - PAD.b) +
        '" style="display:none"/>');
      svg.push('<circle class="tl-dot" r="3.5" style="display:none"/>');
      details.querySelector('.tl-svg').innerHTML =
        '<svg viewBox="0 0 ' + W + ' ' + H + '" role="img">' + svg.join('') + '</svg>';
      view = { spec: spec, series: series, x: x, y: y };
    }

    // Each pill toggle is its own group: the x-axis buttons carry data-mode, the y-mode
    // buttons data-ymode, and a click only repaints the on-state within its own group.
    Array.prototype.forEach.call(details.querySelectorAll('.tl-toggle'), function (group) {
      var buttons = group.querySelectorAll('button');
      Array.prototype.forEach.call(buttons, function (btn) {
        btn.addEventListener('click', function () {
          var isY = !btn.dataset.mode;
          var next = isY ? btn.dataset.ymode : btn.dataset.mode;
          if (next === (isY ? ymode : mode)) return;
          if (isY) { ymode = next; note.textContent = NOTES[ymode]; }
          else mode = next;
          Array.prototype.forEach.call(buttons, function (o) {
            o.classList.toggle('on', o === btn);
          });
          render();
        });
      });
    });

    details.addEventListener('toggle', function () {
      if (details.open && !rendered) render();
    });
    if (details.open) render();

    wrap.addEventListener('mousemove', function (e) {
      var svgEl = wrap.querySelector('svg');
      if (!view || !view.series.length || !svgEl) return;
      var rect = svgEl.getBoundingClientRect();
      if (!rect.width || !rect.height) return;
      var mx = (e.clientX - rect.left) / rect.width * W;
      var my = (e.clientY - rect.top) / rect.height * H;
      var b = Math.round((mx - PAD.l) / (W - PAD.l - PAD.r) * view.spec.bins - 0.5);
      b = Math.max(0, Math.min(view.spec.bins - 1, b));
      var best = null, dist = Infinity;
      view.series.forEach(function (l) {
        if (l.vals[b] === null) return;  // a gap bin has no point to read out
        var d = Math.abs(view.y(l.vals[b]) - my);
        if (d < dist) { dist = d; best = l; }
      });
      var cross = svgEl.querySelector('.tl-cross'), dot = svgEl.querySelector('.tl-dot');
      if (!best) {  // every visible series gaps here - nothing to point at
        tip.hidden = true;
        cross.style.display = 'none';
        dot.style.display = 'none';
        return;
      }
      var cx = view.x(b), cy = view.y(best.vals[b]);
      cross.setAttribute('x1', cx); cross.setAttribute('x2', cx);
      cross.style.display = '';
      dot.setAttribute('cx', cx); dot.setAttribute('cy', cy);
      dot.style.fill = slot(best.i);
      dot.style.display = '';
      var size = view.spec.size;
      var range = view.spec.pct
        ? b * size + '\\u2013' + (b + 1) * size + '% of match'
        : clock(b * size) + '\\u2013' + clock((b + 1) * size);
      var v = best.vals[b], text;
      if (ymode === 'share') {
        text = asPct(v) + ' of buys &middot; ' + range + ' (n=' + best.raw[b] + ')';
      } else if (ymode === 'cpshare') {
        text = asPct(v) + ' of CP spent &middot; ' + range + ' (n=' + best.raw[b] + ')';
      } else if (ymode === 'lifecycle') {
        text = asPct(v) + ' of its orders &middot; ' + range;
      } else if (ymode === 'count') {
        text = best.raw[b] + (best.raw[b] === 1 ? ' order' : ' orders') + ' &middot; ' + range;
      } else {
        text = asPct(v) + ' by ' +
          (view.spec.pct ? (b + 1) * size + '% of match' : clock((b + 1) * size));
      }
      tip.innerHTML = '<b>' + esc(best.label) + '</b> ' + text;
      tip.hidden = false;
      var left = cx / W * rect.width + 12;
      if (left + tip.offsetWidth > rect.width - 4) left -= tip.offsetWidth + 24;
      tip.style.left = Math.max(0, left) + 'px';
      tip.style.top = Math.max(0, cy / H * rect.height - 30) + 'px';
    });
    wrap.addEventListener('mouseleave', function () {
      tip.hidden = true;
      var svgEl = wrap.querySelector('svg');
      if (!svgEl) return;
      svgEl.querySelector('.tl-cross').style.display = 'none';
      svgEl.querySelector('.tl-dot').style.display = 'none';
    });
  });
})();
"""


# The purchase-timing heatmaps for the Sciences, Upgrades, and Other purchases sections,
# self-contained like `_GRAPH_SCRIPT` (small helpers - clock(), the STEPS ladder, binning, the
# centred 3-bin smoother - are duplicated here rather than shared, so either script still
# stands alone with no external assets). These categories' picks mostly happen once per game
# per row (a science or player-wide upgrade is bought once; a tracked CP purchase is depth-
# numbered so each row is a game's nth buy; only an untracked pooled purchase can repeat,
# which is why the tooltip counts purchases, not games) and a faction only carries 10-20 of
# them, so more timeline lines would just overlap; a heatmap instead gives one row per pick
# (table rank order) with every row visible at once, reading as a bank of timing fingerprints
# rather than a legend to toggle. Binning matches the timeline's: pct mode bins every purchase's %-
# of-match into 20 bins of 5%; abs mode picks a bin size off the same STEPS ladder so the
# longest purchase's match spans at most 24 bins. Raw per-bin counts are smoothed with the same
# centred 3-bin moving average before shading (never before the tooltip's raw counts, which stay
# exact). Shading is row-normalised - each row's intensity is its own smoothed bin over its own
# smoothed max - so a row reads as *when* that science tends to be bought, independent of how
# often it is bought at all; a bin whose smoothed value is exactly 0 is left untinted (the bare
# `--track` row background), never painted with a fabricated floor tint. There is no y-mode
# toggle (a heatmap cell has only one meaning) and no per-row checkbox - a heatmap row has no
# line to hide - so only the %/abs axis toggle does anything. Charts render lazily on first open,
# like the timeline, and the grid is built as markup handed to innerHTML.
_HEATMAP_SCRIPT = """\
(function () {
  var STEPS = [15, 30, 60, 120, 300, 600, 1200];

  function clock(seconds) {
    var m = Math.floor(seconds / 60), s = Math.round(seconds % 60);
    if (s === 60) { m += 1; s = 0; }
    return m + ':' + (s < 10 ? '0' : '') + s;
  }
  // Unlike the timeline's escaper this one also covers `"`: heatmap labels land in a
  // title attribute as well as element text.
  function esc(s) {
    return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/"/g, '&quot;');
  }

  function binning(payload, mode) {
    if (mode === 'pct') return { bins: 20, size: 5, pct: true };
    var max = 0;
    payload.series.forEach(function (s) {
      s.occ.forEach(function (p) { if (p[1] > max) max = p[1]; });
    });
    if (!max) max = 60;
    var size = STEPS[STEPS.length - 1];
    for (var i = 0; i < STEPS.length; i++) {
      if (Math.ceil(max / STEPS[i]) <= 24) { size = STEPS[i]; break; }
    }
    return { bins: Math.max(1, Math.ceil(max / size)), size: size, pct: false };
  }

  function counts(s, spec) {
    var out = [], b;
    for (b = 0; b < spec.bins; b++) out.push(0);
    s.occ.forEach(function (p) {
      if (spec.pct) b = Math.floor(p[0] / p[1] * spec.bins);
      else b = Math.floor(p[0] / spec.size);
      out[Math.max(0, Math.min(spec.bins - 1, b))] += 1;
    });
    return out;
  }

  // The centred 3-bin moving average the shading reads; an edge bin averages over the
  // neighbours it has. Mirrors `_GRAPH_SCRIPT`'s smoother exactly.
  function smooth(raw) {
    return raw.map(function (c, b) {
      var sum = c, n = 1;
      if (b > 0) { sum += raw[b - 1]; n += 1; }
      if (b + 1 < raw.length) { sum += raw[b + 1]; n += 1; }
      return sum / n;
    });
  }

  function axisTicks(spec) {
    var ticks = [];
    if (spec.pct) {
      [0, 25, 50, 75, 100].forEach(function (t) { ticks.push({ at: t, label: t + '%' }); });
    } else {
      var span = spec.bins * spec.size;
      var step = spec.size * Math.max(1, Math.ceil(spec.bins / 6));
      for (var t = 0; t <= span; t += step) {
        ticks.push({ at: t / span * 100, label: clock(t) });
      }
    }
    return ticks.map(function (tick) {
      // Anchor by the tick's value, not its index: in abs mode the tick step need not
      // divide the span, so the last tick can sit short of the right edge and must keep
      // its true position rather than be pinned to 100%.
      var style = tick.at <= 0 ? 'left:0'
        : tick.at >= 100 ? 'left:100%;transform:translateX(-100%)'
        : 'left:' + tick.at + '%;transform:translateX(-50%)';
      return '<span style="' + style + '">' + tick.label + '</span>';
    }).join('');
  }

  Array.prototype.forEach.call(document.querySelectorAll('details.heatmap'), function (details) {
    var payload = JSON.parse(details.querySelector('script.hm-data').textContent);
    var grid = details.querySelector('.hm-grid');
    var wrap = details.querySelector('.hm-wrap');
    var tip = details.querySelector('.tl-tip');
    var mode = 'pct';
    var rendered = false;
    var view = null;

    function render() {
      rendered = true;
      var spec = binning(payload, mode);
      var series = payload.series.map(function (s) {
        var raw = counts(s, spec);
        var sm = smooth(raw);
        var maxSm = 0;
        sm.forEach(function (v) { if (v > maxSm) maxSm = v; });
        return { label: s.label, n: s.occ.length, raw: raw, sm: sm, maxSm: maxSm };
      });
      var rows = series.map(function (s, i) {
        var cells = '';
        for (var b = 0; b < spec.bins; b++) {
          // Smoothing drives intensity only; a bin with no actual purchases stays
          // uncoloured rather than inheriting spillover from its neighbours (the
          // tooltip reports raw counts, so a tinted "0 of n" cell would lie).
          var style = '';
          if (s.raw[b] > 0) {
            var pct = 10 + (s.sm[b] / s.maxSm) * 75;
            style = ' style="background: color-mix(in srgb, var(--above) ' +
              pct.toFixed(1) + '%, transparent)"';
          }
          cells += '<span class="hm-cell" data-i="' + i + '" data-b="' + b + '"' + style + '></span>';
        }
        return '<div class="hm-row"><div class="hm-label" title="' + esc(s.label) + '">' +
          esc(s.label) + '<span class="n">' + s.n + '</span></div>' +
          '<div class="hm-cells">' + cells + '</div></div>';
      }).join('');
      grid.innerHTML = rows + '<div class="hm-axis">' + axisTicks(spec) + '</div>';
      view = { spec: spec, series: series };
    }

    Array.prototype.forEach.call(details.querySelectorAll('.tl-toggle button'), function (btn) {
      btn.addEventListener('click', function () {
        if (btn.dataset.mode === mode) return;
        mode = btn.dataset.mode;
        Array.prototype.forEach.call(details.querySelectorAll('.tl-toggle button'), function (o) {
          o.classList.toggle('on', o === btn);
        });
        render();
      });
    });

    details.addEventListener('toggle', function () {
      if (details.open && !rendered) render();
    });
    if (details.open) render();

    wrap.addEventListener('mouseover', function (e) {
      var cell = e.target;
      if (!cell.classList || !cell.classList.contains('hm-cell') || !view) { return; }
      var s = view.series[+cell.dataset.i];
      var b = +cell.dataset.b;
      if (!s || !(s.raw[b] > 0)) { tip.hidden = true; return; }
      var size = view.spec.size;
      var range = view.spec.pct
        ? (b * size) + '\\u2013' + ((b + 1) * size) + '% of match'
        : clock(b * size) + '\\u2013' + clock((b + 1) * size);
      tip.innerHTML = '<b>' + esc(s.label) + '</b> ' + s.raw[b] + ' of ' + s.n +
        ' purchases \\u00b7 ' + range;
      tip.hidden = false;
      var rect = wrap.getBoundingClientRect();
      var cr = cell.getBoundingClientRect();
      var left = cr.left - rect.left + cr.width / 2 + 8;
      if (left + tip.offsetWidth > rect.width - 4) left -= tip.offsetWidth + cr.width + 16;
      tip.style.left = Math.max(0, left) + 'px';
      tip.style.top = Math.max(0, cr.top - rect.top - 30) + 'px';
    });
    wrap.addEventListener('mouseleave', function () {
      tip.hidden = true;
    });
  });
})();
"""


# The build-order Explorer, self-contained like the other scripts. Each `details.botree`
# ships its faction's pruned eco-only tree as a JSON payload (already translated); this script
# draws it lazily on first open as a flat list of indented rows (one per node, root excluded),
# toggling row visibility rather than adding/removing DOM. A row's headline is its share of its
# parent (node.games / parent.games); the muted tail carries games, the win-loss split, the same
# diverging win-rate bar the tables use (markup replicated here), and the median clock. A node
# with children carries a disclosure marker and toggles its subtree on click; visibility
# cascades, so a collapsed node hides its whole subtree and re-expanding restores only the
# descendants whose own state says show. Default expansion follows the dominant line: the root's
# children always show, and a deeper node stays open only while its largest child holds >= 60%
# of its games, collapsing at the first fork. The category dot's hue is fixed per category. When
# the payload is a matchup diff (`root.diff`), each row also carries a `vs overall` annotation
# after its share: the share-vs-overall delta in points (from `base_share`) as the tables'
# `.delta` classes, or a `NEW` badge when the step is absent in the faction overall.
_BUILDORDER_SCRIPT = """\
(function () {
  var DOT = { buildings: '--s1', units: '--s2', heroes: '--s3' };

  function esc(s) { return s.replace(/&/g, '&amp;').replace(/</g, '&lt;'); }
  function clock(seconds) {
    if (seconds === null || seconds === undefined) return '-';
    var m = Math.floor(seconds / 60), s = Math.round(seconds % 60);
    if (s === 60) { m += 1; s = 0; }
    return m + ':' + (s < 10 ? '0' : '') + s;
  }
  // The tables' diverging win-rate bar, rebuilt in JS from a node's win-loss split so the
  // Explorer reads the same as the openings table above it; an undecided node shows the dash.
  function bar(node) {
    var decided = node.wins + node.losses;
    if (!decided) return '<span class="na">-</span>';
    var rate = node.wins / decided;
    var span = Math.abs(rate - 0.5) * 100;
    var side = rate >= 0.5 ? 'above' : 'below';
    return '<span class="bar"><span class="track"><span class="fill ' + side +
      '" style="width:' + span.toFixed(0) + '%"></span><i></i></span>' +
      '<span class="pct">' + Math.round(rate * 100) + '%</span></span>';
  }

  // The share-vs-overall annotation for a diff row: the delta between this node's share of its
  // parent and the baseline's (`base_share`) in points, coloured like the tables' deltas, or a
  // `NEW` badge when the step is absent in the faction overall (base_share null).
  function vsOverall(node, parentGames) {
    if (node.base_share === null || node.base_share === undefined) {
      return '<span class="bo-vs"><span class="badge">NEW</span></span>';
    }
    var share = parentGames > 0 ? node.games / parentGames : 0;
    var points = Math.round(share * 100 - node.base_share * 100);
    var cls = points > 0 ? 'up' : points < 0 ? 'down' : 'even';
    var text = (points > 0 ? '+' : '') + points;
    return '<span class="bo-vs"><span class="delta ' + cls + '">' + text + '</span></span>';
  }

  Array.prototype.forEach.call(document.querySelectorAll('details.botree'), function (details) {
    var root = JSON.parse(details.querySelector('script.bo-data').textContent);
    var diff = !!root.diff;
    var host = details.querySelector('.bo-rows');
    var rows = [];
    var rendered = false;

    // A row is visible only while every real ancestor is expanded; the synthetic root (parent
    // of the depth-1 rows) is always expanded, so the top level always shows.
    function isVisible(row) {
      var p = row.parent;
      while (p) {
        if (!p.expanded) return false;
        p = p.parent;
      }
      return true;
    }
    function refresh() {
      rows.forEach(function (row) {
        row.el.hidden = !isVisible(row);
        if (row.hasKids) row.mark.textContent = row.expanded ? '\\u25BE' : '\\u25B8';
      });
    }
    function makeRow(node, depth, parentGames, hasKids) {
      var el = document.createElement('div');
      el.className = 'bo-row' + (hasKids ? ' bo-open' : '');
      el.style.marginLeft = ((depth - 1) * 18) + 'px';
      var share = parentGames > 0 ? Math.round(node.games / parentGames * 100) : 0;
      var count = node.median_count > 1 ? ' \\u00d7' + node.median_count : '';
      var dot = DOT[node.category] || '--muted';
      el.innerHTML =
        '<span class="bo-mark">' + (hasKids ? '\\u25B8' : '') + '</span>' +
        '<span class="bo-dot" style="background: var(' + dot + ')"></span>' +
        '<span class="bo-label">' + esc(node.label) + count + '</span>' +
        '<span class="bo-share">' + share + '%</span>' +
        (diff ? vsOverall(node, parentGames) : '') +
        '<span class="bo-games">' + node.games + '</span>' +
        '<span class="bo-wl">' + node.wins + '-' + node.losses + '</span>' +
        bar(node) +
        '<span class="bo-time">' + clock(node.median_seconds) + '</span>';
      return el;
    }
    function walk(node, depth, parentGames, parent) {
      var kids = node.children || [];
      var maxKid = 0;
      kids.forEach(function (c) {
        if (c.games > maxKid) maxKid = c.games;
      });
      var hasKids = kids.length > 0;
      var expanded = hasKids &&
        (depth === 0 || (node.games > 0 && maxKid / node.games >= 0.6));
      var row;
      if (depth === 0) {
        row = { expanded: true, parent: null };  // the synthetic root
      } else {
        var el = makeRow(node, depth, parentGames, hasKids);
        row = { el: el, expanded: expanded, hasKids: hasKids, parent: parent,
                mark: el.querySelector('.bo-mark') };
        if (hasKids) {
          (function (r) {
            el.addEventListener('click', function () { r.expanded = !r.expanded; refresh(); });
          })(row);
        }
        rows.push(row);
        host.appendChild(el);
      }
      kids.forEach(function (c) { walk(c, depth + 1, node.games, row); });
    }
    function render() {
      if (rendered) return;
      rendered = true;
      walk(root, 0, root.games, null);
      refresh();
    }

    details.addEventListener('toggle', function () {
      if (details.open) render();
    });
    if (details.open) render();
  });
})();
"""


# The build-order icicle/flow diagram, self-contained like the other scripts. Each `.bo-ice-wrap`
# ships its faction's pruned eco-only tree as the same translated JSON payload the Explorer uses;
# this script lays it out as a horizontal icicle - depth = columns left-to-right (matching the
# openings table's arrow direction), a box's height its share of `games`. Column 0 (depth-1 nodes)
# partitions the full SVG height top-aligned in child order; each deeper column partitions its
# parent box's band among that parent's children the same way, leaving the remainder
# (parent.games - sum child.games) blank at the bottom - real attrition (games whose continuation
# was pruned as uncommon), kept visible so heights read honestly. A box fills with its category's
# `--sN` hue (fallback --muted) and a thin --surface stroke separating stacked boxes; a box tall
# enough carries a haloed, truncated label (the translated step, `×k` when its typical count is
# above one). A static `.ice-legend` above the SVG (server-rendered in `_build_order_icicle`, not
# drawn by this script) names each category against its `--sN` swatch, so the fills read as
# buildings/units/heroes before the icicle itself has laid out. Rendering is lazy via an
# IntersectionObserver (a matchup-heavy page holds many icicles inside collapsed `<details>`),
# falling back to an immediate render where the observer is unavailable, and runs once. Hovering a
# box highlights it and its ancestor path (dimming the rest) and reads out the shared `.tl-tip`:
# label, games, share of parent, W-L, win rate (dash when undecided), and median clock. When the
# payload is a matchup diff (`root.diff`), the tooltip also names the share-vs-overall delta (or
# "new vs overall") and a box new versus the faction overall (base_share null) is outlined with a
# dashed --ink stroke, the diff riding as a second channel over the category fill.
#
# A second readout box (`.ice-sci`, above the SVG) shows a step's science annotation: unless
# pinned, it tracks the hovered box, reading that node's payload `sciences` (the by-step
# annotation, already clock-sorted server-side) as `label m:ss (NN%)` entries - share of that
# node's own games - or "none yet" when the node carries none; it reverts to the default text on
# mouseleave. Right-clicking a box (`contextmenu`, default prevented) pins the readout there - a
# `(pinned)` suffix and the `pinned` class mark the readout, and a `.ice-pin` class marks the
# pinned rect - until the same box is right-clicked again or empty SVG background is
# right-clicked, either of which unpins; right-clicking a different box moves the pin there
# instead. Hover tooltips (`.tl-tip`) keep working regardless of the pin.
_ICICLE_SCRIPT = """\
(function () {
  var CAT = { buildings: '--s1', units: '--s2', heroes: '--s3' };
  var W = 720, H = 300, PAD = 3, GAP = 2, MIN_LABEL = 11, CHAR = 5.4;

  function clock(seconds) {
    if (seconds === null || seconds === undefined) return '-';
    var m = Math.floor(seconds / 60), s = Math.round(seconds % 60);
    if (s === 60) { m += 1; s = 0; }
    return m + ':' + (s < 10 ? '0' : '') + s;
  }
  function esc(s) {
    return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/"/g, '&quot;');
  }
  // The by-step science annotation as the readout's trailing list, already clock-sorted
  // server-side: 'label m:ss (NN%)' per entry, share = that science's games over the node's own
  // games, or 'none yet' when the node carries no science annotation at all.
  function sciText(n) {
    if (!n.sciences.length) return 'none yet';
    var parts = [];
    n.sciences.forEach(function (s) {
      var pct = n.games > 0 ? Math.round(s.games / n.games * 100) : 0;
      parts.push(esc(s.label) + ' ' + clock(s.median_seconds) + ' (' + pct + '%)');
    });
    return parts.join(' \\u00b7 ');
  }
  function maxDepth(node, d) {
    var m = d;
    (node.children || []).forEach(function (c) {
      var cd = maxDepth(c, d + 1);
      if (cd > m) m = cd;
    });
    return m;
  }

  Array.prototype.forEach.call(document.querySelectorAll('.bo-ice-wrap'), function (wrap) {
    var root = JSON.parse(wrap.querySelector('script.ice-data').textContent);
    var host = wrap.querySelector('.bo-ice');
    var tip = wrap.querySelector('.tl-tip');
    var sciBox = wrap.querySelector('.ice-sci');
    var defaultSci = sciBox ? sciBox.textContent : '';
    var diff = !!root.diff;
    var nodes = [];
    var rendered = false;
    var pinned = -1;

    function render() {
      if (rendered) return;
      rendered = true;
      var depth = Math.max(1, maxDepth(root, 0));
      var colW = (W - PAD * 2) / depth;
      var svg = [];

      // Partition a parent band [y0, y1] (its games mapping to the whole band) among its children
      // top-aligned, the pruned remainder left blank at the bottom; emit a rect per real node.
      function walk(node, y0, y1, d, parentIdx) {
        var idx = -1;
        if (d >= 1) {
          idx = nodes.length;
          var x = PAD + (d - 1) * colW, w = colW - GAP, h = y1 - y0;
          var fill = CAT[node.category] || '--muted';
          var isNew = diff && (node.base_share === null || node.base_share === undefined);
          svg.push('<rect class="ice-box" data-i="' + idx + '" x="' + x.toFixed(1) +
            '" y="' + y0.toFixed(1) + '" width="' + w.toFixed(1) + '" height="' + h.toFixed(1) +
            '" fill="var(' + fill + ')" stroke="var(--surface)"' +
            (isNew ? ' stroke-dasharray="3 2" style="stroke:var(--ink)"' : '') + '/>');
          nodes.push({ parent: parentIdx, label: node.label, games: node.games,
            parentGames: parentIdx >= 0 ? nodes[parentIdx].games : root.games,
            wins: node.wins, losses: node.losses, ms: node.median_seconds,
            sciences: node.sciences || [],
            base: (node.base_share === undefined ? null : node.base_share) });
          if (h >= MIN_LABEL) {
            var count = (node.median_count && node.median_count > 1)
              ? ' \\u00d7' + node.median_count : '';
            var label = node.label + count;
            var fit = Math.floor((w - 6) / CHAR);
            if (label.length > fit) label = fit > 1 ? label.slice(0, fit - 1) + '\\u2026' : '';
            if (label) {
              svg.push('<text class="ice-label" x="' + (x + 3).toFixed(1) + '" y="' +
                (y0 + h / 2).toFixed(1) + '" dominant-baseline="middle">' + esc(label) + '</text>');
            }
          }
        }
        var kids = node.children || [];
        if (node.games > 0) {
          var scale = (y1 - y0) / node.games, cursor = y0;
          kids.forEach(function (c) {
            var ch = c.games * scale;
            walk(c, cursor, cursor + ch, d + 1, idx);
            cursor += ch;
          });
        }
      }
      walk(root, PAD, H - PAD, 0, -1);
      host.innerHTML = '<svg viewBox="0 0 ' + W + ' ' + H + '" role="img">' + svg.join('') +
        '</svg>';
    }

    function ancestors(i) {
      var set = {};
      while (i >= 0) { set[i] = true; i = nodes[i].parent; }
      return set;
    }

    // The readout box: unpinned, it tracks the hovered node; pinned, it stays on that node (a
    // '(pinned)' suffix and the 'pinned' class marking it) until unpinned again.
    function showSci(i) {
      if (!sciBox) return;
      var n = nodes[i];
      var html = '<b>' + esc(n.label) + '</b> \\u00b7 sciences by ~' + clock(n.ms) + ': ' +
        sciText(n);
      if (i === pinned) html += ' (pinned)';
      sciBox.innerHTML = html;
      sciBox.classList.toggle('pinned', i === pinned);
    }
    function resetSci() {
      if (!sciBox) return;
      sciBox.textContent = defaultSci;
      sciBox.classList.remove('pinned');
    }
    function setPin(i) {
      pinned = i;
      Array.prototype.forEach.call(host.querySelectorAll('.ice-box'), function (r) {
        r.classList.remove('ice-pin');
      });
      if (i < 0) { resetSci(); return; }
      var rect = host.querySelector('.ice-box[data-i="' + i + '"]');
      if (rect) rect.classList.add('ice-pin');
      showSci(i);
    }

    host.addEventListener('mouseover', function (e) {
      var rect = e.target;
      if (!rect.classList || !rect.classList.contains('ice-box')) return;
      var i = +rect.getAttribute('data-i');
      var set = ancestors(i);
      Array.prototype.forEach.call(host.querySelectorAll('.ice-box'), function (r) {
        r.style.opacity = set[+r.getAttribute('data-i')] ? '1' : '0.25';
      });
      var n = nodes[i];
      var share = n.parentGames > 0 ? Math.round(n.games / n.parentGames * 100) : 0;
      var decided = n.wins + n.losses;
      var wr = decided ? Math.round(n.wins / decided * 100) + '%' : '\\u2013';
      var html = '<b>' + esc(n.label) + '</b> ' + n.games + ' games \\u00b7 ' + share +
        '% of parent \\u00b7 ' + n.wins + '-' + n.losses + ' \\u00b7 ' + wr +
        ' \\u00b7 ' + clock(n.ms);
      if (diff) {
        if (n.base === null) {
          html += ' \\u00b7 new vs overall';
        } else {
          var pts = Math.round((n.parentGames > 0 ? n.games / n.parentGames : 0) * 100 -
            n.base * 100);
          html += ' \\u00b7 ' + (pts > 0 ? '+' : '') + pts + ' vs overall';
        }
      }
      tip.innerHTML = html;
      tip.hidden = false;
      var wr2 = wrap.getBoundingClientRect(), cr = rect.getBoundingClientRect();
      var left = cr.left - wr2.left + cr.width / 2 + 8;
      if (left + tip.offsetWidth > wr2.width - 4) left = wr2.width - tip.offsetWidth - 4;
      tip.style.left = Math.max(0, left) + 'px';
      tip.style.top = Math.max(0, cr.top - wr2.top - 6) + 'px';
      if (pinned < 0) showSci(i);
    });
    host.addEventListener('mouseleave', function () {
      tip.hidden = true;
      Array.prototype.forEach.call(host.querySelectorAll('.ice-box'), function (r) {
        r.style.opacity = '1';
      });
      if (pinned < 0) resetSci();
    });
    host.addEventListener('contextmenu', function (e) {
      e.preventDefault();
      var rect = e.target;
      if (rect.classList && rect.classList.contains('ice-box')) {
        var i = +rect.getAttribute('data-i');
        setPin(i === pinned ? -1 : i);
      } else {
        setPin(-1);
      }
    });

    if (typeof IntersectionObserver === 'undefined') {
      render();
    } else {
      var io = new IntersectionObserver(function (entries) {
        entries.forEach(function (entry) {
          if (entry.isIntersecting) { render(); io.disconnect(); }
        });
      });
      io.observe(wrap);
    }
  });
})();
"""


# Extra styling for the navigation index (`render_index_html`) only, appended after the
# shared sheet so the per-faction pages are untouched: the matchup matrix (vertical column
# heads, tinted diverging cells). The link and nav-pill rules live in the shared sheet, as
# the aggregate pages carry a back-to-index nav of their own.
_INDEX_STYLE = """\
table.matrix th, table.matrix td { text-align: center; }
table.matrix td:first-child, table.matrix th:first-child { text-align: left; }
table.matrix th.col { position: relative; height: 96px; vertical-align: bottom; padding: 4px 3px 26px; }
table.matrix th.col span {
  writing-mode: vertical-rl; transform: rotate(180deg); white-space: nowrap;
  font-family: ui-monospace, Consolas, monospace; font-size: 12px;
  text-transform: none; letter-spacing: 0;
}
table.matrix th.col .cico {
  position: absolute; left: 50%; bottom: 5px; transform: translateX(-50%);
  height: 18px; width: auto; border-radius: 3px;
}
table.matrix td:first-child .ficon { height: 1em; vertical-align: -0.15em; margin-right: 5px; }
table.matrix td.cell { min-width: 40px; font-variant-numeric: tabular-nums; line-height: 1.15; }
table.matrix .n { display: block; font-size: 10px; font-weight: 400; color: var(--muted); }
table.matrix td:first-child .gc { color: var(--muted); font-weight: 400; }
td.mt { color: var(--muted); }
.navbar { display: flex; flex-wrap: wrap; gap: 8px; margin: 4px 0 10px; }
.nav.current { border-color: var(--above); color: var(--muted); cursor: default; }
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


def _timeline_block(
    ranked: list[ChoiceStat], graph: str, translate: Translate, weight: Weight | None = None
) -> str:
    """The collapsed timeline `<details>` for one Buildings/Units table: the x-axis and y-mode
    toggles, the empty containers the graph script draws into, and a JSON payload of every
    occurrence as (order seconds, that match's duration) - raw rather than pre-binned, so the
    client can rebin the same data for either axis and derive every y-mode (see `_GRAPH_SCRIPT`).
    Series ride in row order (`ranked` matches the table body), which is how each row's
    `data-series` index and swatch tie back to a line; labels go through `translate` so the
    graph names what the table names. With `weight` (the Units tables), every series also
    carries its `cp` command-point weight - looked up by the pick's recorded label, before
    `translate` - and the y-toggle gains the "CP share" mode that weighting enables. The note
    under the toggles describes the current y-mode (the script rewrites it on toggle; the
    shipped text is share's, the default). `</` is escaped inside the JSON so no label can
    close the script element early."""
    payload = {
        "series": [
            {
                "label": translate(choice.label),
                "occ": [[round(t, 1), round(d, 1)] for t, d in choice.occurrences],
                **({"cp": weight(choice.label)} if weight is not None else {}),
            }
            for choice in ranked
        ],
    }
    data = json.dumps(payload, separators=(",", ":")).replace("</", "<\\/")
    cp_button = (
        '<button type="button" data-ymode="cpshare">CP share</button>' if weight is not None else ""
    )
    return (
        f'<details class="timeline" data-graph="{graph}"><summary>Timeline '
        '<span class="rec">order timing across match length</span></summary>'
        '<div class="body">'
        '<div class="tl-head"><span class="tl-toggle">'
        '<button type="button" class="on" data-mode="pct">% of match</button>'
        '<button type="button" data-mode="abs">game clock</button></span>'
        '<span class="tl-toggle">'
        '<button type="button" class="on" data-ymode="share">share</button>'
        f"{cp_button}"
        '<button type="button" data-ymode="lifecycle">lifecycle</button>'
        '<button type="button" data-ymode="count">count</button>'
        '<button type="button" data-ymode="cumulative">cumulative</button></span>'
        '<span class="tl-note">share of visible series\' orders per bin</span></div>'
        '<div class="tl-wrap"><div class="tl-svg"></div><div class="tl-tip" hidden></div></div>'
        f'<script type="application/json" class="tl-data">{data}</script>'
        "</div></details>"
    )


def _heatmap_block(ranked: list[ChoiceStat], graph: str, translate: Translate, rec: str) -> str:
    """The collapsed purchase-timing `<details>` for a Sciences/Upgrades/Other purchases table:
    a heatmap rather than the Buildings/Units timeline's line graph, because these picks happen
    at most once per game per row and a faction only carries 10-20 of them - one row per pick
    (in table rank order) reads at a glance where the timeline's overlapping lines would not.
    `rec` is the section-appropriate summary blurb ("when each science is bought..."). Only the
    x-axis toggles (no y-mode: a heatmap cell is always that row's own share of its own
    purchases, row-normalised - see `_HEATMAP_SCRIPT`), and there is no per-row checkbox/swatch
    or header select-all, since there is no line to key a row to. The JSON payload is identical
    in shape to `_timeline_block`'s (series of translated label + raw (order seconds, match
    duration) occurrences), rounded to 1 decimal; `</` is escaped inside it so no label can
    close the script element early."""
    payload = {
        "series": [
            {
                "label": translate(choice.label),
                "occ": [[round(t, 1), round(d, 1)] for t, d in choice.occurrences],
            }
            for choice in ranked
        ],
    }
    data = json.dumps(payload, separators=(",", ":")).replace("</", "<\\/")
    return (
        f'<details class="heatmap" data-graph="{graph}"><summary>Purchase timing '
        f'<span class="rec">{escape(rec)}</span></summary>'
        '<div class="body">'
        '<div class="tl-head"><span class="tl-toggle">'
        '<button type="button" class="on" data-mode="pct">% of match</button>'
        '<button type="button" data-mode="abs">game clock</button></span>'
        '<span class="tl-note">each row shaded by where its own purchases fall</span></div>'
        '<div class="hm-wrap"><div class="hm-grid"></div><div class="tl-tip" hidden></div></div>'
        f'<script type="application/json" class="hm-data">{data}</script>'
        "</div></details>"
    )


def _html_table(
    table: dict[str, ChoiceStat],
    title: str,
    column: str,
    heading: str,
    *,
    games: int,
    translate: Translate,
    base_table: dict[str, ChoiceStat] | None,
    base_games: int,
    owner: str | None,
    annotate: Annotate | None,
    graph_ids: Iterator[int] | None = None,
    graph_kind: str = "timeline",
    heatmap_rec: str = "",
    anchor: str | None = None,
    weight: Weight | None = None,
) -> list[str]:
    """One pick-category table, titled at `heading` depth; empty when the table is. With a
    `base_table` (the faction's overall aggregate for this category) each row gains a `vs
    overall` delta column. With `graph_ids` (the page-wide counter, handed in only for the
    graph-bearing sections - see `_GRAPH_SECTIONS`), a collapsed graph sits between the heading
    and the table: `graph_kind="timeline"` (Buildings/Units) draws `_timeline_block` and gives
    every row's label cell a leading checkbox + colour swatch keying that row to its line -
    inside the first cell rather than its own column, so the sort script's column indices and
    text-based keys are untouched and the checkboxes travel with sorted rows - plus a header
    select-all; `graph_kind="heatmap"` (Sciences/Upgrades/Other purchases) draws
    `_heatmap_block` instead - `heatmap_rec` its section-appropriate summary blurb - with no
    per-row key and no select-all, since a heatmap row has no line to toggle. The id is drawn
    only when a graph actually renders (a table where every game lacked a duration has nothing
    to draw), so ids stay dense across the page."""
    if not table:
        return []
    ranked = _ranked(table)
    graph_id = None
    if graph_ids is not None and any(c.occurrences for c in ranked):
        graph_id = f"g{next(graph_ids)}"
    heatmap = graph_kind == "heatmap"
    vs = base_table is not None
    vs_head = '<th title="pick rate vs the faction overall, in points">vs overall</th>'
    # `anchor` (the top-level faction sections only) ids the heading so the single-faction
    # page's contents box can link to it; matchup sub-tables pass none, avoiding duplicate ids.
    attr = f' id="{anchor}"' if anchor else ""
    lines = [f"<{heading}{attr}>{escape(title)}</{heading}>"]
    if graph_id is not None:
        lines.append(
            _heatmap_block(ranked, graph_id, translate, heatmap_rec)
            if heatmap
            else _timeline_block(ranked, graph_id, translate, weight)
        )
    master = ""
    if graph_id is not None and not heatmap:
        # The header's select-all: one checkbox driving every row checkbox below it (and
        # showing indeterminate when they disagree). It sits inside the sortable label
        # header, so the graph script stops its clicks from reaching the th's sort handler.
        master = (
            '<label class="serieskey"><input type="checkbox" checked '
            f'data-graph-all="{graph_id}" title="show/hide all series"></label>'
        )
    lines.extend(
        [
            '<div class="tablewrap"><table>',
            f"<thead><tr><th>{master}{escape(column)}</th><th>Games</th><th>W-L</th>"
            "<th>Win rate</th><th>Median first</th><th>Total</th>"
            f"{vs_head if vs else ''}</tr></thead>",
            "<tbody>",
        ]
    )
    for index, choice in enumerate(ranked):
        first = clock(choice.median_first) if choice.median_first is not None else "-"
        badge = annotate(owner, choice.label) if annotate and owner is not None else ""
        key = ""
        if graph_id is not None and not heatmap:
            # The row's tie to its graph line: checkbox (visibility) + swatch (the series
            # colour, stamped by the graph script). Contributes no textContent, so the
            # column sorter reads the same label it always did.
            key = (
                '<label class="serieskey"><input type="checkbox" checked '
                f'data-graph="{graph_id}" data-series="{index}">'
                '<span class="swatch"></span></label>'
            )
        vs_cell = ""
        if base_table is not None:
            delta = _pick_rate(choice, games) - _pick_rate(base_table.get(choice.label), base_games)
            vs_cell = f"<td>{_delta(delta)}</td>"
        lines.append(
            f"<tr><td>{key}{escape(translate(choice.label))}{badge}</td><td>{choice.games}</td>"
            f"<td>{choice.wins}-{choice.losses}</td><td>{_html_bar(choice.win_rate)}</td>"
            f'<td class="dim">{first}</td><td>x{choice.total}</td>{vs_cell}</tr>'
        )
    lines.extend(["</tbody>", "</table></div>"])
    return lines


def _tree_has_category(node: BuildNode, category: str) -> bool:
    """Whether any node below `node` (children onward, the root step-less node excluded) carries
    `category` - so a tree with a hero step anywhere earns the Heroes extrapolation caveat."""
    for child in node.children.values():
        if child.category == category or _tree_has_category(child, category):
            return True
    return False


def _science_payload(table: dict[str, list[float]], translate: Translate) -> list[dict]:
    """One node's by-step science annotation (`BuildNode.sciences_by_step`) as the client JSON
    shape: each label translated, `games` the number of clocks recorded for it, sorted by median
    clock ascending (ties by label) - the same ordering `_science_line` and `BuildNode.to_dict`
    use for their own science summaries."""
    entries = [
        {"label": translate(label), "games": len(clocks), "median_seconds": median(clocks)}
        for label, clocks in table.items()
    ]
    entries.sort(key=lambda entry: (entry["median_seconds"], entry["label"]))
    return entries


def _bo_node_payload(
    node: BuildNode,
    translate: Translate,
    base_node: BuildNode | None,
    base_parent: BuildNode | None,
    diffing: bool,
) -> dict:
    """One build-order node as the client JSON shape (shared by the icicle and the Explorer): its
    label through `translate` plus the fields the client draws from, recursing into children.
    Keeps `win_rate`/`decided` out - both scripts derive the bar/win-rate from wins/losses, matching
    the tables. Carries `sciences` - the node's by-step science annotation (`_science_payload`,
    translated, clock-sorted) - only when it is non-empty, so a leaf-less node's payload stays as
    small as before. When `diffing` (a parallel walk of the faction's overall tree, `base_node`/
    `base_parent` following the same key-path) every node carries `base_share`: the matching
    baseline node's share-of-its-parent (`base_node.games / base_parent.games`), or `null` when
    that path is absent in the baseline (a step common only against this enemy) - so every node
    carries the key even below the point the paths diverge. Outside diff mode neither `base_share`
    nor the top-level `diff` flag is emitted, so the payload stays byte-identical to the non-diff
    shape."""
    payload: dict = {
        "label": translate(node.label),
        "category": node.category,
        "games": node.games,
        "wins": node.wins,
        "losses": node.losses,
        "median_seconds": node.median_seconds,
        "median_count": node.median_count,
    }
    sciences = _science_payload(node.sciences_by_step, translate)
    if sciences:
        payload["sciences"] = sciences
    if diffing:
        payload["base_share"] = (
            base_node.games / base_parent.games
            if base_node is not None and base_parent is not None and base_parent.games
            else None
        )
    children = []
    for key, child in node.children.items():
        child_base = base_node.children.get(key) if base_node is not None else None
        children.append(_bo_node_payload(child, translate, child_base, base_node, diffing))
    payload["children"] = children
    return payload


def _bo_payload(
    node: BuildNode, translate: Translate, *, baseline: BuildNode | None = None
) -> dict:
    """The whole build-order tree as the client JSON shape, rooted at `node` (see
    `_bo_node_payload` for one node). With `baseline` (the faction's overall tree) the payload
    walks it in parallel so every node carries a `base_share` and the root gains `diff: true`,
    letting the icicle and Explorer show how the opening shifts against one enemy; without it the
    payload is byte-identical to the non-diff shape (no `base_share`, no `diff`)."""
    diffing = baseline is not None
    payload = _bo_node_payload(node, translate, baseline, None, diffing)
    if diffing:
        payload["diff"] = True
    return payload


def _baseline_path_games(baseline: BuildNode, path: list[BuildNode]) -> int | None:
    """The games reaching the same full key-path in the baseline (overall) tree, walking keys
    from its root; None when any step of the path is absent - an opening common against this enemy
    but not in the faction overall."""
    node = baseline
    for step in path:
        child = node.children.get((step.category, step.label))
        if child is None:
            return None
        node = child
    return node.games


def _build_order_table(
    tree: BuildNode, translate: Translate, *, baseline: BuildNode | None = None
) -> list[str]:
    """The top openings as a standard sortable table: each path's step labels joined with arrows
    (translated, HTML-escaped, `×k` when a step's typical count is above one), then its leaf
    node's games, win-loss, win-rate bar, and `~Complete` (the leaf's own median clock) in a
    muted cell. A non-empty science line (`_science_line`, off the leaf's `sciences_taken`)
    renders as a second, muted line inside the Build order cell (`.bo-sci`). With `baseline` (the
    faction's overall tree, a matchup sub-block only) a trailing `vs overall` column carries the
    path-share delta - this opening's share of the matchup (`leaf.games / tree.games`) minus the
    overall's share of the whole faction at the same full key-path (`_baseline_path_games`) - as
    a `_delta`, or a `NEW` badge when that path is absent in the baseline entirely."""
    vs = baseline is not None
    vs_head = '<th title="opening share vs the faction overall, in points">vs overall</th>'
    lines = [
        '<div class="tablewrap"><table>',
        "<thead><tr><th>Build order</th><th>Games</th><th>W-L</th>"
        f"<th>Win rate</th><th>~Complete</th>{vs_head if vs else ''}</tr></thead>",
        "<tbody>",
    ]
    for path in build_orders.openings(tree, limit=8):
        leaf = path[-1]
        label = _build_path_label(path, translate, arrow=" &rarr; ", times=" &times;", esc=escape)
        complete_at = leaf.median_seconds
        complete = clock(complete_at) if complete_at is not None else "-"
        science_line = _science_line(leaf, translate, arrow=" &rarr; ", esc=escape)
        sci_cell = f'<div class="bo-sci">sciences: {science_line}</div>' if science_line else ""
        vs_cell = ""
        if baseline is not None:
            base_games = _baseline_path_games(baseline, path)
            if base_games is None:
                vs_cell = '<td><span class="badge">NEW</span></td>'
            else:
                share = leaf.games / tree.games if tree.games else 0.0
                base_share = base_games / baseline.games if baseline.games else 0.0
                vs_cell = f"<td>{_delta(share - base_share)}</td>"
        lines.append(
            f"<tr><td>{label}{sci_cell}</td><td>{leaf.games}</td>"
            f"<td>{leaf.wins}-{leaf.losses}</td><td>{_html_bar(leaf.win_rate)}</td>"
            f'<td class="dim">{complete}</td>{vs_cell}</tr>'
        )
    lines.extend(["</tbody>", "</table></div>"])
    return lines


# The icicle's category legend, in the same tree order the boxes themselves stack in (buildings,
# units, heroes) and tied to the same `--sN` slots `_ICICLE_SCRIPT`'s `CAT` map uses, so a swatch
# always matches the fill it names. The tree is eco-only, so sciences never earn a box or a slot.
_ICE_LEGEND = (("buildings", "--s1"), ("units", "--s2"), ("heroes", "--s3"))

# The icicle readout's default text before any step has been hovered or right-click pinned.
_ICE_SCI_DEFAULT = "hover a step for its sciences · right-click pins"


def _build_order_icicle(
    tree: BuildNode, translate: Translate, *, baseline: BuildNode | None = None
) -> str:
    """The build-order tree as a horizontal icicle/flow diagram (`_ICICLE_SCRIPT` draws it): a
    wrapper holding a static category legend, a science readout box (`.ice-sci`, `_ICE_SCI_DEFAULT`
    until a step is hovered or pinned - the script fills it in per step from that node's payload
    `sciences`), the SVG host, a shared tooltip, and the same translated JSON payload the Explorer
    ships (`</` escaped so no label can close the script element early). Column = depth
    left-to-right, a box's height its share of `games`; the client partitions each parent band
    among its children top-aligned, leaving the pruned-away remainder blank. With `baseline` the
    payload carries the diff channel (`base_share`, `diff`) so a matchup icicle can outline steps
    new versus the faction overall and read the share delta in the tooltip. `tree` is eco-only; a
    node's sciences ride in its payload's `sciences` field for the readout, never as boxes of
    their own. The legend (`_ICE_LEGEND`) is plain server-rendered markup, not part of the JSON
    payload or drawn by the script, so it reads before the lazy icicle itself has rendered."""
    payload = _bo_payload(tree, translate, baseline=baseline)
    data = json.dumps(payload, separators=(",", ":")).replace("</", "<\\/")
    legend = "".join(
        f'<span class="ice-legend-item"><span class="swatch" style="--c: var({slot})"></span>'
        f"{category}</span>"
        for category, slot in _ICE_LEGEND
    )
    return (
        f'<div class="bo-ice-wrap"><div class="ice-legend">{legend}</div>'
        f'<div class="ice-sci">{_ICE_SCI_DEFAULT}</div>'
        '<div class="bo-ice"></div><div class="tl-tip" hidden></div>'
        f'<script type="application/json" class="ice-data">{data}</script></div>'
    )


def _build_order_explorer(
    tree: BuildNode, translate: Translate, *, baseline: BuildNode | None = None
) -> str:
    """The collapsed step-by-step `<details class="botree">`: the translated tree as a JSON
    payload (`</` escaped so no label can close the script element early) that `_BUILDORDER_SCRIPT`
    draws lazily on first open into an indented, foldable row per node. With `baseline` (a matchup
    sub-block only) the payload carries the diff channel, so each row also shows how its share
    shifts against the faction overall (a `vs overall` delta, or a `NEW` badge). `tree` is
    eco-only - buildings/units/heroes rows, no science rows; a node's science annotations still
    ride in its payload (for the icicle's readout) but are not drawn by this script."""
    data = json.dumps(
        _bo_payload(tree, translate, baseline=baseline), separators=(",", ":")
    ).replace("</", "<\\/")
    return (
        '<details class="botree"><summary>Explorer '
        '<span class="rec">step-by-step branches with share of games</span></summary>'
        '<div class="body"><div class="bo-rows"></div>'
        f'<script type="application/json" class="bo-data">{data}</script>'
        "</div></details>"
    )


def _build_order_html(
    agg: FactionAggregate,
    heading: str,
    translate: Translate,
    *,
    anchor: str | None = None,
    baseline: BuildNode | None = None,
) -> list[str]:
    """One aggregate's build-order section as HTML: the heading (ided by `anchor` only on the
    single-faction page's own block, never a matchup's), the hero-step extrapolation caveat
    (`_BUILD_ORDER_HERO_NOTE` - scoped to hero steps, not the Heroes table's whole-section
    wording) when a hero step appears anywhere in the tree, then the eco-only tree itself as the
    section headline's icicle/flow diagram (with its science readout box), the top-openings table
    (each row's leaf-wide science order riding as a second line, `_science_line`), and the
    collapsible Explorer. With `baseline` (the faction's overall combined tree, threaded for a
    matchup sub-block) every piece diffs against it, showing how the opening differs from the
    faction's overall. Empty when the aggregate has no pruned build-order tree."""
    if not _build_order_present(agg):
        return []
    assert agg.build_orders is not None
    tree = agg.build_orders
    attr = f' id="{anchor}"' if anchor else ""
    lines = [f"<{heading}{attr}>Build orders</{heading}>"]
    if _tree_has_category(tree, "heroes"):
        lines.append(f'<p class="note">{escape(_BUILD_ORDER_HERO_NOTE)}</p>')
    lines.append(_build_order_icicle(tree, translate, baseline=baseline))
    lines.extend(_build_order_table(tree, translate, baseline=baseline))
    lines.append(_build_order_explorer(tree, translate, baseline=baseline))
    return lines


def _sub_heading(heading: str) -> str:
    """The heading one level deeper than `heading` (h3 -> h4), for the nested powers block."""
    return f"h{int(heading[1:]) + 1}"


def _html_tables(
    agg: FactionAggregate,
    heading: str,
    translate: Translate,
    baseline: FactionAggregate | None = None,
    owner: str | None = None,
    annotate: Annotate | None = None,
    powers_heading: str = DEFAULT_POWERS_HEADING,
    graph_ids: Iterator[int] | None = None,
    section_anchors: bool = False,
    weight: Weight | None = None,
    lead_build_orders: bool = True,
) -> list[str]:
    """The pick-category tables of one aggregate, titled at `heading` (h3/h4) depth, led by the
    common build-order section (`_build_order_html` - anchored only when `section_anchors`) unless
    `lead_build_orders` is False (the faction's own block renders it lower, just above the replay
    list - see `render_aggregate_html` - while matchup sub-blocks keep it leading), and
    with the tracked powers nested a heading level deeper under Units as `powers_heading` (their
    caster is a unit, not a recruitable hero). Row labels are shown through `translate` (raw code
    name when it is the identity). With `baseline` (the faction's overall aggregate), each row gains
    a `vs overall` column: this aggregate's pick rate for the choice minus the baseline's, in
    points - so a matchup table shows how the faction's picks shift against that enemy; the leading
    build-order section diffs against the baseline's own tree the same way (icicle, openings table,
    and Explorer all showing how the opening differs from the faction overall). `annotate(owner,
    label)` may append a badge to a row (e.g. flagging a pick that is not
    `owner`'s roster); `owner` is the faction the picks belong to, which for a matchup sub-table
    is the parent faction, not the enemy. `graph_ids` (a page-wide counter, threaded from
    `render_aggregate_html`) gives the Buildings and Units sections their timeline graphs and the
    Sciences/Upgrades/Other purchases sections their purchase-timing heatmaps: each rendered
    graph draws a fresh id tying its rows (or, for a heatmap, just the graph itself) to its own
    chart, unique across every faction and matchup block on the page. `weight` (a label ->
    command-point lookup, see `command_point_weights`) reaches only the Units timeline, giving
    it the "CP share" y-mode."""
    base_games = baseline.games if baseline is not None else 0
    lines: list[str] = []
    # Build orders lead a matchup sub-block, but the faction's own block renders them lower (just
    # above its replay list, see `render_aggregate_html`), so `lead_build_orders` gates them here.
    if lead_build_orders:
        lines.extend(
            _build_order_html(
                agg,
                heading,
                translate,
                anchor="sec-buildorders" if section_anchors else None,
                baseline=baseline.build_orders if baseline is not None else None,
            )
        )
    for title, attribute, column in _SECTIONS:
        base_table = getattr(baseline, attribute) if baseline is not None else None
        # The section-heading anchor for the single-faction page's contents box; only the
        # faction's own top-level sections carry one (matchup sub-tables leave it off).
        anchor = f"sec-{attribute}" if section_anchors else None
        section = _html_table(
            getattr(agg, attribute),
            title,
            column,
            heading,
            games=agg.games,
            translate=translate,
            base_table=base_table,
            base_games=base_games,
            owner=owner,
            annotate=annotate,
            graph_ids=graph_ids if attribute in _GRAPH_SECTIONS else None,
            graph_kind="timeline" if attribute in _TIMELINE_SECTIONS else "heatmap",
            heatmap_rec=_HEATMAP_REC.get(attribute, ""),
            anchor=anchor,
            # Only the Units timeline weighs its series: command points are an army-cap
            # cost, which structures don't occupy.
            weight=weight if attribute == "units" else None,
        )
        if attribute == "heroes" and section:
            # Sit the extrapolation warning right under the Heroes heading (index 1, after the
            # heading line and before the table wrap), so the caveat travels with the data.
            section.insert(1, f'<p class="note">{escape(_HERO_SECTION_NOTE)}</p>')
        elif attribute == "units":
            base_powers = baseline.powers if baseline is not None else None
            powers = _html_table(
                agg.powers,
                powers_heading,
                "Power",
                _sub_heading(heading),
                games=agg.games,
                translate=translate,
                base_table=base_powers,
                base_games=base_games,
                owner=owner,
                annotate=annotate,
            )
            # A bare Units heading anchors the nested powers when no unit was recruited (keeping
            # the section anchor so the contents box still links here).
            if powers and not section:
                attr = f' id="{anchor}"' if anchor else ""
                section = [f"<{heading}{attr}>{escape(title)}</{heading}>"]
            section.extend(powers)
        lines.extend(section)
    return lines


def _html_tiles(agg: FactionAggregate) -> str:
    """One aggregate's headline record as a row of stat tiles: games played, win-loss record,
    win rate, and median match length. Undetermined-outcome games and the standard-outpost
    milestone still fold into `_faction_summary`'s prose line above the tiles; they don't
    warrant tiles of their own."""
    length = clock(median(agg.durations)) if agg.durations else "-"
    rate = _percent(agg.win_rate).strip() if agg.win_rate is not None else "-"
    tiles = (
        ("Games", str(agg.games)),
        ("Record", f"{agg.wins}-{agg.losses}"),
        ("Win rate", rate),
        ("Median length", length),
    )
    cells = "".join(
        f'<div class="tile"><div class="k">{k}</div><div class="v">{v}</div></div>'
        for k, v in tiles
    )
    return f'<div class="tiles">{cells}</div>'


def _toc(entries: list[tuple[str, str]]) -> list[str]:
    """A contents box from `(label_html, anchor)` pairs - `label_html` is already escaped/marked
    up by the caller (a faction entry carries its icon), `anchor` is the in-page id it links to.
    Empty pairs render nothing."""
    if not entries:
        return []
    items = "".join(f'<li><a href="#{href}">{label}</a></li>' for label, href in entries)
    return [f'<nav class="toc"><p class="toc-title">Contents</p><ul>{items}</ul></nav>']


def _corpus_toc(
    factions: list[FactionAggregate], translate: Translate, icon: FactionIcon
) -> list[str]:
    """The all-faction report's contents: one entry per faction, linking to its `<h2>` block."""
    entries = [
        (_icon_img(icon(agg.faction)) + escape(translate(agg.faction)), f"f-{_anchor(agg.faction)}")
        for agg in factions
    ]
    return _toc(entries)


def _faction_toc(agg: FactionAggregate, has_replays: bool) -> list[str]:
    """A single-faction page's contents: each pick section present (a bare Units section still
    lists when only powers were cast), the matchups block, then the build-order section and the
    replay list when present. Section order and anchors mirror `render_aggregate_html`'s layout,
    where build orders sit after the matchups and just above the replays (`sec-buildorders` /
    `sec-<attribute>` headings)."""
    entries: list[tuple[str, str]] = []
    for title, attribute, _ in _SECTIONS:
        present = bool(getattr(agg, attribute)) or (attribute == "units" and bool(agg.powers))
        if present:
            entries.append((escape(title), f"sec-{attribute}"))
    if agg.matchups:
        entries.append(("Matchups", "matchups"))
    if _build_order_present(agg):
        entries.append(("Build orders", "sec-buildorders"))
    if has_replays:
        entries.append(("Replays", "replays"))
    return _toc(entries)


def render_aggregate_html(
    corpus: Corpus,
    factions: list[FactionAggregate],
    *,
    title: str = "Replay corpus stats",
    translate: Translate | None = None,
    extra: Callable[[FactionAggregate], list[str]] | None = None,
    annotate: Annotate | None = None,
    index_href: str | None = None,
    powers_heading: str = DEFAULT_POWERS_HEADING,
    icon: FactionIcon | None = None,
    weight: Weight | None = None,
) -> list[str]:
    """The same aggregation as one self-contained HTML page (no external assets, light/dark via
    `prefers-color-scheme`): per faction a stat-tile header and the pick-category tables
    (tracked powers nested under Units as `powers_heading`), then a collapsible `vs <enemy>`
    block per matchup when the aggregation carried them. Win rates render as diverging bars
    around 50%. `translate` maps a code name to the display string shown for faction and
    pick-table labels; by default labels render as their raw code names. `extra`, if given,
    returns extra HTML lines appended after each faction's own block (the caller's per-faction
    replay list). Each faction carries a Build orders section (an icicle/flow diagram of the
    pruned eco-only tree as its headline, with a readout box for a hovered/pinned step's
    sciences - its common openings as a sortable table, each row's leaf-wide science order riding
    as a second line - and a collapsible step-by-step Explorer over the same tree - drawn by the
    embedded `_ICICLE_SCRIPT` and `_BUILDORDER_SCRIPT`) when its pruned build-order tree has any
    branches, rendered after its matchups and just above `extra`'s replay list. Matchup blocks
    carry their own Build orders section leading their sub-tables, diffing against the faction's
    overall tree
    (a `vs overall` column on the openings table, a `NEW`/delta annotation in the icicle and the
    Explorer).
    `annotate(faction, label)` may badge a pick row - both the faction's own
    tables and its matchup sub-tables are annotated against that faction as the owner.
    `index_href`, if given, renders a back-to-index nav pill linking there (a page relative path
    from this page). `icon`, if given, maps a faction code name to an icon URL (relative to
    this page - the one optional external asset) shown before the faction name in its header
    and matchup summaries. Every table's column headers sort client-side (`_SORT_SCRIPT`), every
    Buildings/Units table carries a collapsed timeline graph of order timing across match length
    (drawn by the embedded `_GRAPH_SCRIPT`; see its module comment and `_timeline_block` for the
    graph's axis, y-mode, and denominator behavior; `weight`, a pick label -> command-point
    lookup like `command_point_weights(data)`, adds the Units timelines' "CP share" y-mode,
    weighting each series by the army-cap cost its orders occupy), and every Sciences, Upgrades,
    and Other purchases table carries a collapsed purchase-timing heatmap - one row per pick
    shaded by when it tends to be bought (drawn by the embedded `_HEATMAP_SCRIPT`; see its
    module comment and `_heatmap_block`). A contents box
    heads the page: over the factions for a multi-faction report, or over the one faction's own
    sections (each pick
    category present, then Matchups and, when `extra` renders one, Replays) for a single-faction
    page - so `extra`'s replay heading should carry `id="replays"` to be linked."""
    tr = translate or _identity
    ic = icon or _no_icon
    graph_ids = count()
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
        f'<p class="meta">{escape(_HERO_NOTE)}</p>',
    ]
    if index_href is not None:
        lines.append(f'<p><a class="nav" href="{escape(index_href)}">&larr; Back to index</a></p>')
    # A single-faction page (one faction, the caller's per-faction report) gets a contents box
    # over its own sections; a multi-faction report gets one over its factions. The per-faction
    # `extra` (the replay list) is rendered once and reused, so the single-faction contents can
    # tell whether a Replays entry belongs.
    extra_lines = {agg.faction: (extra(agg) if extra is not None else []) for agg in factions}
    single = len(factions) == 1
    if single:
        lines.extend(_faction_toc(factions[0], bool(extra_lines[factions[0].faction])))
    else:
        lines.extend(_corpus_toc(factions, tr, ic))
    for agg in factions:
        lines.append(
            f'<h2 id="f-{_anchor(agg.faction)}">'
            f"{_icon_img(ic(agg.faction))}{escape(tr(agg.faction))}</h2>"
        )
        lines.append(_html_tiles(agg))
        lines.extend(
            _html_tables(
                agg,
                "h3",
                tr,
                owner=agg.faction,
                annotate=annotate,
                powers_heading=powers_heading,
                graph_ids=graph_ids,
                section_anchors=single,
                weight=weight,
                lead_build_orders=False,
            )
        )
        matchups = _ranked_matchups(agg)
        if matchups:
            # A heading anchors the matchup blocks (id only on a single-faction page, where the
            # contents box links to it; a multi-faction report would collide on the id).
            mid = ' id="matchups"' if single else ""
            lines.append(f"<h3{mid}>Matchups</h3>")
        for enemy, sub in matchups:
            swing = ""
            if sub.win_rate is not None and agg.win_rate is not None:
                swing = (
                    ' <span class="rec" title="win rate vs this faction&#39;s overall">'
                    f"&Delta; {_delta(sub.win_rate - agg.win_rate, '%')}</span>"
                )
            lines.extend(
                [
                    "<details><summary>",
                    f"vs {_icon_img(ic(enemy))}{escape(tr(enemy))} {_html_bar(sub.win_rate)}{swing} "
                    f'<span class="rec">{escape(_faction_summary(sub, tr, include_outpost=False))}</span>',
                    '</summary><div class="body">',
                ]
            )
            lines.extend(
                _html_tables(
                    sub,
                    "h3",
                    tr,
                    baseline=agg,
                    owner=agg.faction,
                    annotate=annotate,
                    powers_heading=powers_heading,
                    graph_ids=graph_ids,
                    weight=weight,
                )
            )
            lines.append("</div></details>")
        # The faction's own build orders render here, after its matchups and just above the
        # replay list, rather than leading the block (matchup sub-blocks keep them leading, see
        # `_html_tables`); the anchor rides along only on a single-faction page's contents box.
        lines.extend(_build_order_html(agg, "h3", tr, anchor="sec-buildorders" if single else None))
        lines.extend(extra_lines[agg.faction])
    lines.extend(
        [
            "</main>",
            f"<script>{_SORT_SCRIPT}</script>",
            f"<script>{_GRAPH_SCRIPT}</script>",
            f"<script>{_HEATMAP_SCRIPT}</script>",
            f"<script>{_BUILDORDER_SCRIPT}</script>",
            f"<script>{_ICICLE_SCRIPT}</script>",
        ]
    )
    lines.extend(["</body>", "</html>"])
    return lines


def _index_tiles(corpus: Corpus, factions: list[FactionAggregate]) -> str:
    """The corpus headline as stat tiles: how much data the pages are built from."""
    tiles = (
        ("Replays", str(corpus.replays)),
        ("Factions", str(len(factions))),
    )
    cells = "".join(
        f'<div class="tile"><div class="k">{k}</div><div class="v">{v}</div></div>'
        for k, v in tiles
    )
    return f'<div class="tiles">{cells}</div>'


def _index_leaderboard(
    factions: list[FactionAggregate],
    links: dict[str, str],
    translate: Translate,
    icon: FactionIcon = _no_icon,
) -> list[str]:
    """A row per faction (most-played first) linking to its page, with its headline record.
    The faction is shown through `translate` (with its `icon` before the name) but linked by
    its raw code name via `links`."""
    lines = [
        '<div class="tablewrap"><table>',
        "<thead><tr><th>Faction</th><th>Games</th><th>W-L</th>"
        "<th>Win rate</th><th>Median length</th></tr></thead>",
        "<tbody>",
    ]
    for agg in factions:
        length = clock(median(agg.durations)) if agg.durations else "-"
        href = links.get(agg.faction)
        name = escape(translate(agg.faction))
        cell = _icon_img(icon(agg.faction)) + (
            f'<a href="{escape(href)}">{name}</a>' if href else name
        )
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
    factions: list[FactionAggregate],
    links: dict[str, str],
    translate: Translate,
    icon: FactionIcon = _no_icon,
) -> list[str]:
    """The faction-vs-faction win-rate grid, when the aggregation carried matchups; empty
    otherwise. Rows and columns follow the leaderboard order (most-played first); faction
    names are shown through `translate` (with their `icon` - inline before each row label, and
    pinned under each column header), keyed internally by their raw code names."""
    if not any(agg.matchups for agg in factions):
        return []
    order = [agg.faction for agg in factions]
    heads = "".join(
        f'<th class="col"><span>{escape(translate(f))}</span>{_icon_img(icon(f), "cico")}</th>'
        for f in order
    )
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
        label = f'{_icon_img(icon(agg.faction))}{linked} <span class="gc">{agg.games}</span>'
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


def _index_nav(nav: list[tuple[str, str]] | None) -> list[str]:
    """A row of pills linking between sibling index pages (the overall corpus and each
    per-player-count split). An entry with an empty href is the current page, rendered inert."""
    if not nav:
        return []
    pills = [
        f'<a class="nav" href="{escape(href)}">{escape(label)}</a>'
        if href
        else f'<span class="nav current">{escape(label)}</span>'
        for label, href in nav
    ]
    return ['<p class="navbar">' + "".join(pills) + "</p>"]


def render_index_html(
    corpus: Corpus,
    factions: list[FactionAggregate],
    links: dict[str, str],
    *,
    title: str = "Replay corpus",
    combined_href: str = "aggregate.html",
    generated: str | None = None,
    translate: Translate | None = None,
    nav: list[tuple[str, str]] | None = None,
    icon: FactionIcon | None = None,
) -> list[str]:
    """A self-contained navigation index for a set of aggregate pages (same light/dark
    styling as `render_aggregate_html`): corpus stat tiles, a link to the combined report,
    a per-faction leaderboard linking out via `links` (raw faction code name -> href), the
    matchup win-rate matrix, and the unparseable / unresolved-faction warnings. `generated` is an optional build
    stamp; `translate` maps a faction code name to the display string (raw code name by
    default) while `links` stays keyed by the raw code name. `nav`, if given, is a row of
    `(label, href)` pills linking to sibling index pages (an empty href marks the current one).
    `icon`, if given, maps a faction code name to an icon URL (relative to this page) shown
    before the faction in the leaderboard and matchup matrix. The leaderboard's column headers
    are clickable to sort (the matrix is left unsorted; see `_SORT_SCRIPT`)."""
    tr = translate or _identity
    ic = icon or _no_icon
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
        *_index_nav(nav),
        f'<p><a class="nav" href="{escape(combined_href)}">All factions &mdash; '
        "combined report &rarr;</a></p>",
        "<h2>Factions</h2>",
    ]
    lines.extend(_index_leaderboard(factions, links, tr, ic))
    lines.extend(_index_matrix(factions, links, tr, ic))
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
    lines.extend(["</main>", f"<script>{_SORT_SCRIPT}</script>", "</body>", "</html>"])
    return lines
