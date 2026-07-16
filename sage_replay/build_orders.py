"""Common build orders: a player's clocked stats reduced to a normalized opening - a pair of
independent sequences, not one timeline - aggregated across many games into a per-faction
prefix tree, then pruned down to what is actually common.

A build-order *step* is one decision: what got built/recruited/researched, and roughly when.
Only the categories that represent a deliberate opening choice count (`BUILD_ORDER_CATEGORIES`)
- a repeatable power cast or a per-battalion upgrade is not part of an opening, and would just
add noise. A `fortress_hero_slots` event (an unresolved revive-menu recruit) is folded in under
"heroes" with the same `fortress hero (command slot N)` label the aggregate hero tables use, so
a build order and the pick tables agree on what a hero recruit is called even when its identity
never resolved.

A build's *identity* is a pair of independent sequences: buildings/units/heroes (plus the
relabelled `fortress_hero_slots`) compete for the shared resource pool, while sciences spend the
separate spellbook-point currency, so which of the two comes first at any given moment carries no
information about the build - `Farm → Heal → Barracks` and `Farm → Barracks → Heal` are the same
build, and two builds differ only when one sequence differs on its own terms. `build_sequence`
extracts the eco and science streams independently, each running the same *introduction-order*
algorithm over its own events, with its own open step and its own seen-set: a (category, label)
becomes a step at its first order in that stream, the step stays open - counting further orders
of it - until that stream's next new thing is introduced, and a later repeat of something already
fielded in that stream is filler, ignored outright without closing the open step's counting
window (`Farm, Farm, Barracks, Farm, Peasants` reads `Farm ×2 → Barracks ×1 → Peasants ×1`; the
second farm wave never re-appears). An event in one stream never closes the other stream's open
window and is never filler for it - a science purchase between two Farm orders leaves the Farm
step open for the next one, and vice versa. Filler must not become a step: a label re-bought a
few steps later would split otherwise-equal openings into separate branches, fragmenting the
prefix tree and starving the deeper steps of the game support they need to survive pruning - and
introduction order is how players actually state a build order, as the sequence in which things
are first fielded. `depth` and `science_depth` independently cap each stream's number of
introductions (extraction of a stream stops where one more of its own introductions would begin,
so that stream's last step still accumulates count until then, through the other stream's events
too) - so each cap measures distinct opening decisions in its own currency, not raw orders.
`build_sequence` returns the canonical `eco_steps + science_steps` concatenation - identity, not
chronology - so any two interleavings of the same pair of sequences produce the identical list
and fold into one shared tree path.

Many games' sequences fold into one prefix tree per faction (`BuildNode`, built with `new_root`,
`insert`, and `build_tree`): each node is an eco (category, label) step reached from the root,
carrying how many games passed through it, their win/loss split, and the per-game step counts and
clocks that passed through - so a node can report a typical order count and a typical timing, not
just a frequency. A build's identity in the tree is its eco sequence alone; the science stream
never grows tree nodes of its own, riding instead as two per-node annotations folded in while each
game's eco path is walked: `sciences_by_step` keeps, for every science the game had already bought
by that step's own clock (that science's `seconds <=` the step's `seconds`), one clock per label -
the running "what's typically in hand here" picture - while `sciences_taken` keeps the game's whole
science order unconditionally at every node along its path, also one clock per label - "what
science order rides with this opening." Both are keyed by science label to a list of per-game
clocks, so a label's games and median clock read off the list the same way every other node stat
does. The root itself counts every inserted game (including a game with an empty sequence) but is
never annotated and never rendered, so a top-level child's share of the root is a share of the
whole faction, and `prune` can compare a child's games against its parent's as-inserted total to
decide whether a branch is common enough to keep - a low-share or low-sample branch is dropped, and
dropping a branch drops everything under it, its annotations along with it, since a rare fork's
children are rarer still. `openings` finally reads the pruned tree back out as the top root-to-leaf
paths, ordered by how many games took them."""

from __future__ import annotations

import statistics
from collections.abc import Sequence
from dataclasses import dataclass, field

from sage_replay.stats import PlayerStats

__all__ = [
    "BUILD_ORDER_CATEGORIES",
    "BuildNode",
    "BuildStep",
    "build_sequence",
    "build_tree",
    "insert",
    "new_root",
    "openings",
    "prune",
]

# The event categories that represent an opening decision. `fortress_hero_slots` is handled
# separately in `build_sequence` (relabelled into "heroes"), not listed here. `sciences` is its
# own independent stream in `build_sequence`; the rest form the eco stream.
BUILD_ORDER_CATEGORIES: frozenset[str] = frozenset({"buildings", "units", "heroes", "sciences"})


@dataclass(slots=True, frozen=True)
class BuildStep:
    """One opening decision: a (category, label) at its introduction, `count` the orders of it
    from its introduction until the next new step opens, `seconds` the introducing order's
    clock."""

    label: str
    category: str
    count: int
    seconds: float


@dataclass(slots=True)
class _StreamState:
    """One stream's introduction-order extraction state (eco or sciences): its steps so far,
    the (category, label) keys already introduced, the currently open key, `depth` its
    introduction cap, and `stopped` once that cap has been reached - after which the stream
    ignores every further event of its own, mirroring how a single-stream extraction would stop
    outright at its depth cap."""

    depth: int
    steps: list[BuildStep] = field(default_factory=list)
    seen: set[tuple[str, str]] = field(default_factory=set)
    open_key: tuple[str, str] | None = None
    stopped: bool = False

    def feed(self, category: str, label: str, seconds: float) -> None:
        """Fold one of this stream's own events in: bump the open step, introduce a new one, or
        drop it as filler, applying the introduction-order rule to this stream's own keys and
        its own depth cap alone."""
        if self.stopped:
            return
        key = (category, label)
        if key == self.open_key:
            last = self.steps[-1]
            self.steps[-1] = BuildStep(label, category, last.count + 1, last.seconds)
        elif key not in self.seen:
            if self.depth > 0 and len(self.steps) >= self.depth:
                self.stopped = True
                return
            self.steps.append(BuildStep(label, category, 1, seconds))
            self.seen.add(key)
            self.open_key = key
        # else: already introduced but no longer open - filler, ignored without closing the
        # open step's counting window.


def build_sequence(
    stats: PlayerStats, *, depth: int = 12, science_depth: int = 4
) -> list[BuildStep]:
    """One player's opening as the canonical `eco_steps + science_steps` concatenation: the eco
    stream (buildings/units/heroes, plus the relabelled `fortress_hero_slots`) and the science
    stream (sciences) each run introduction order independently over their own events - a
    (category, label)'s first order in its stream introduces a step and opens it, further orders
    of the open step bump its count, and an order for anything already introduced but no longer
    open in that stream is filler, ignored without closing the open step's counting window and
    without ever touching the other stream. `depth` caps the eco introductions and
    `science_depth` caps the science introductions (each stream's extraction stops where one
    more of its own introductions would begin; `depth <= 0` / `science_depth <= 0` means
    unlimited for that stream). The concatenation - not the original event order - is what makes
    two interleavings of the same pair of sequences identical."""
    eco = _StreamState(depth)
    science = _StreamState(science_depth)
    for event in stats.events:
        if event.category == "fortress_hero_slots":
            eco.feed("heroes", f"fortress hero (command slot {event.label})", event.seconds)
        elif event.category == "sciences":
            science.feed("sciences", str(event.label), event.seconds)
        elif event.category in BUILD_ORDER_CATEGORIES:
            eco.feed(event.category, str(event.label), event.seconds)
    return eco.steps + science.steps


@dataclass(slots=True)
class BuildNode:
    """One node of the per-faction build-order prefix tree: an eco step reached from the root,
    with the games that passed through it, their outcomes, their per-game step counts/clocks, and
    two science annotations folded in from those same games' science streams (see the module
    docstring): `sciences_by_step` (label -> per-game clocks, only for a science that game had
    bought by this step's own clock) and `sciences_taken` (label -> per-game clocks, that game's
    whole science order, unconditionally). Each label carries at most one clock per game."""

    label: str
    category: str
    games: int = 0
    wins: int = 0
    losses: int = 0
    counts: list[int] = field(default_factory=list)
    times: list[float] = field(default_factory=list)
    children: dict[tuple[str, str], BuildNode] = field(default_factory=dict)
    sciences_by_step: dict[str, list[float]] = field(default_factory=dict)
    sciences_taken: dict[str, list[float]] = field(default_factory=dict)

    @property
    def decided(self) -> int:
        return self.wins + self.losses

    @property
    def win_rate(self) -> float | None:
        return self.wins / self.decided if self.decided else None

    @property
    def median_seconds(self) -> float | None:
        return statistics.median(self.times) if self.times else None

    @property
    def median_count(self) -> int | None:
        return round(statistics.median(self.counts)) if self.counts else None

    def to_dict(self) -> dict:
        return {
            "label": self.label,
            "category": self.category,
            "games": self.games,
            "wins": self.wins,
            "losses": self.losses,
            "win_rate": self.win_rate,
            "median_seconds": self.median_seconds,
            "median_count": self.median_count,
            "sciences_by_step": _science_annotation_summary(self.sciences_by_step),
            "sciences_taken": _science_annotation_summary(self.sciences_taken),
            "children": [child.to_dict() for child in self.children.values()],
        }


def _science_annotation_summary(table: dict[str, list[float]]) -> list[dict]:
    """One science annotation (`sciences_by_step` or `sciences_taken`) as `to_dict`'s JSON shape:
    one `{"label", "games", "median_seconds"}` entry per label, `games` the number of clocks
    recorded for it, sorted by median clock ascending and then by label."""
    entries = [
        {"label": label, "games": len(clocks), "median_seconds": statistics.median(clocks)}
        for label, clocks in table.items()
    ]
    entries.sort(key=lambda entry: (entry["median_seconds"], entry["label"]))
    return entries


def new_root() -> BuildNode:
    """A sentinel tree root: not a step itself, but its games/wins/losses count every inserted
    game (empty sequences included), so a top-level child's share of the root is a share of the
    whole faction."""
    return BuildNode(label="", category="")


def _extend(node: BuildNode, steps: Sequence[BuildStep], outcome: str) -> None:
    """Walk/create a child of `node` per step, bumping each visited child's games/outcome and
    recording that game's step count and clock, without ever bumping `node` itself - `insert`
    (the sole caller) counts the starting node's game alongside this walk."""
    for step in steps:
        key = (step.category, step.label)
        child = node.children.get(key)
        if child is None:
            child = BuildNode(label=step.label, category=step.category)
            node.children[key] = child
        child.games += 1
        if outcome == "won":
            child.wins += 1
        elif outcome == "lost":
            child.losses += 1
        child.counts.append(step.count)
        child.times.append(step.seconds)
        node = child


def insert(root: BuildNode, steps: Sequence[BuildStep], outcome: str) -> None:
    """Fold one game's opening into the tree: bump `root` for the game itself, then walk/create
    a child per step (`_extend`). `outcome` is "won"/"lost"/anything else (ignored, e.g.
    "undetermined")."""
    root.games += 1
    if outcome == "won":
        root.wins += 1
    elif outcome == "lost":
        root.losses += 1
    _extend(root, steps, outcome)


def prune(root: BuildNode, *, min_games: int = 3, min_share: float = 0.10) -> None:
    """Drop, in place, every child whose games fall below `max(min_games, min_share *
    parent.games)` (the parent's as-inserted total, not its post-prune total), recursing into
    survivors - so a dropped branch takes its whole subtree with it."""
    threshold = max(min_games, min_share * root.games)
    dropped = [key for key, child in root.children.items() if child.games < threshold]
    for key in dropped:
        del root.children[key]
    for child in root.children.values():
        prune(child, min_games=min_games, min_share=min_share)


def _annotate_sciences(
    root: BuildNode, eco: Sequence[BuildStep], science: Sequence[BuildStep]
) -> None:
    """Walk one game's just-inserted eco path (`root` down through `eco`'s own keys - every node
    on it is guaranteed to exist, `insert` having just created or bumped it) and fold `science`
    into each visited node's two annotations: `sciences_taken` gets every science unconditionally,
    `sciences_by_step` only those bought by that node's own step clock (`seconds <=`). The root
    itself is skipped - it is never annotated."""
    node = root
    for step in eco:
        node = node.children[(step.category, step.label)]
        for sci in science:
            node.sciences_taken.setdefault(sci.label, []).append(sci.seconds)
            if sci.seconds <= step.seconds:
                node.sciences_by_step.setdefault(sci.label, []).append(sci.seconds)


def build_tree(
    games: Sequence[tuple[Sequence[BuildStep], str]],
    *,
    min_games: int = 3,
    min_share: float = 0.10,
) -> BuildNode:
    """A faction's pruned build-order tree, grown from `games` (each a game's canonical
    `build_sequence` output paired with its outcome). Each game's steps split into its eco part
    (everything but "sciences") and its science part; the eco part inserts (`insert`, an empty
    eco part still inserts, so the root counts every game) and the game's sciences annotate every
    node its own eco path visits (`_annotate_sciences`) - the tree's identity stays the eco
    sequence alone, sciences never growing nodes of their own. A single `prune` with
    `min_games`/`min_share` then drops the branches too rare to matter, taking their annotations
    along with them."""
    root = new_root()
    for steps, outcome in games:
        eco = [step for step in steps if step.category != "sciences"]
        science = [step for step in steps if step.category == "sciences"]
        insert(root, eco, outcome)
        _annotate_sciences(root, eco, science)
    prune(root, min_games=min_games, min_share=min_share)
    return root


def openings(root: BuildNode, *, limit: int = 10) -> list[list[BuildNode]]:
    """The top root-to-leaf paths of the (already pruned) tree, root excluded, ranked by leaf
    games descending and then by the path's labels ascending for a deterministic tie-break."""
    paths: list[list[BuildNode]] = []

    def walk(node: BuildNode, path: list[BuildNode]) -> None:
        if not node.children:
            if path:
                paths.append(path)
            return
        for child in node.children.values():
            walk(child, path + [child])

    walk(root, [])
    paths.sort(key=lambda path: (-path[-1].games, [n.label for n in path]))
    return paths[:limit]
