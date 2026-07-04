"""Extract the object-referencing ids from a replay's order stream and align them to a
hand-written label log, so a controlled replay yields an `id -> object` mapping.

Replay orders carry integer ids that reference mod content (the unit recruited, the
structure built). This module isolates those ids: it summarises which order types carry
an integer, pulls the timecode-ordered id sequence for one order type and player, and
collapses consecutive repeats into runs. A run of the same id is one labelled action
("recruit 2x Gondor Soldier" → a run of length 2), so a run sequence lines up with the
ordered label log positionally. See object_id_mapping_plan.md, Phase 2.

The label format is plain text (no dependency): `#` comments, `key: value` header
lines, and one action per line as `[<count>x] <object name>`.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field

from sage_replay.replay import OrderArgumentType, ReplayChunk, ReplayFile

__all__ = [
    "AlignRow",
    "IdEvent",
    "IdRun",
    "LabelAction",
    "Labels",
    "OrderIdSummary",
    "align",
    "arg_equals",
    "collapse_runs",
    "id_events",
    "order_id_summaries",
    "parse_labels",
]

# A chunk predicate used to sub-select orders (e.g. one of `0x417`'s two modes).
ChunkPredicate = Callable[[ReplayChunk], bool]


def arg_equals(arg_index: int, value: object) -> ChunkPredicate:
    """Predicate: the order's argument at `arg_index` equals `value`. Out-of-range is a
    non-match. Note Python treats `True == 1`, so a Boolean argument matches either form."""

    def predicate(chunk: ReplayChunk) -> bool:
        args = chunk.order.arguments
        return arg_index < len(args) and args[arg_index].value == value

    return predicate


def integer_arguments(chunk: ReplayChunk) -> list[int]:
    """The Integer-typed argument values of a chunk's order, in order."""
    return [
        a.value
        for a in chunk.order.arguments
        if a.argument_type is OrderArgumentType.Integer and isinstance(a.value, int)
    ]


@dataclass
class OrderIdSummary:
    order_type: int
    total: int  # chunks of this order type carrying at least one Integer argument
    distinct_ids: int
    top: list[tuple[int, int]]  # (id, count), most common first


def order_id_summaries(
    replay: ReplayFile,
    *,
    slot_index: int | None = None,
    arg_index: int = 0,
    where: ChunkPredicate | None = None,
) -> list[OrderIdSummary]:
    """Summarise every order type that carries an Integer argument, most frequent first.

    `arg_index` selects which Integer argument to treat as the id (0 = the first).
    `slot_index` restricts to one player's orders (see `ReplayFile.slot_index`).
    `where` sub-selects chunks (e.g. `arg_equals(0, False)` for one `0x417` mode).
    """
    totals: Counter[int] = Counter()
    values: dict[int, Counter[int]] = {}
    for chunk in replay.chunks:
        if slot_index is not None and replay.slot_index(chunk) != slot_index:
            continue
        if where is not None and not where(chunk):
            continue
        ints = integer_arguments(chunk)
        if len(ints) <= arg_index:
            continue
        order_type = chunk.order_type
        totals[order_type] += 1
        values.setdefault(order_type, Counter())[ints[arg_index]] += 1

    summaries = [
        OrderIdSummary(
            order_type=order_type,
            total=total,
            distinct_ids=len(values[order_type]),
            top=values[order_type].most_common(10),
        )
        for order_type, total in totals.most_common()
    ]
    return summaries


@dataclass
class IdEvent:
    timecode: int
    id: int
    slot_index: int | None


def id_events(
    replay: ReplayFile,
    order_type: int,
    *,
    slot_index: int | None = None,
    arg_index: int = 0,
    where: ChunkPredicate | None = None,
) -> list[IdEvent]:
    """The timecode-ordered id sequence for one order type (chunks are already ordered).

    `where` sub-selects chunks (e.g. `arg_equals(0, False)` for one `0x417` mode).
    """
    events = []
    for chunk in replay.chunks:
        if chunk.order_type != order_type:
            continue
        chunk_slot = replay.slot_index(chunk)
        if slot_index is not None and chunk_slot != slot_index:
            continue
        if where is not None and not where(chunk):
            continue
        ints = integer_arguments(chunk)
        if len(ints) > arg_index:
            events.append(IdEvent(chunk.timecode, ints[arg_index], chunk_slot))
    return events


@dataclass
class IdRun:
    start_timecode: int
    id: int
    count: int


def collapse_runs(events: list[IdEvent]) -> list[IdRun]:
    """Collapse consecutive equal ids into runs — one run per labelled action."""
    runs: list[IdRun] = []
    for event in events:
        if runs and runs[-1].id == event.id:
            runs[-1].count += 1
        else:
            runs.append(IdRun(event.timecode, event.id, 1))
    return runs


@dataclass
class LabelAction:
    count: int
    name: str


@dataclass
class Labels:
    metadata: dict[str, str] = field(default_factory=dict)
    actions: list[LabelAction] = field(default_factory=list)


def parse_labels(text: str) -> Labels:
    """Parse the plain-text label log. `key: value` lines seen before the first action
    become metadata; each remaining line is one action, `[<count>x] <name>`."""
    labels = Labels()
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue

        # A `key: value` line is metadata, but only until the first action is recorded
        # (unit names may legitimately be bare words that never contain a colon).
        if not labels.actions and ":" in line:
            key, _, value = line.partition(":")
            labels.metadata[key.strip()] = value.strip()
            continue

        labels.actions.append(_parse_action_line(line))
    return labels


def _parse_action_line(line: str) -> LabelAction:
    """Parse `<count>x <name>`, `<count> <name>`, or a bare `<name>` (count 1)."""
    head, _, tail = line.partition(" ")
    multiplier = head[:-1] if head.lower().endswith("x") else head
    if multiplier.isdigit() and tail.strip():
        return LabelAction(count=int(multiplier), name=tail.strip())
    return LabelAction(count=1, name=line)


@dataclass
class AlignRow:
    id: int | None
    name: str
    replay_count: int | None  # run length in the replay; None when there is no run to pair
    label_count: int

    @property
    def ok(self) -> bool:
        return self.replay_count == self.label_count


def align(runs: list[IdRun], actions: list[LabelAction]) -> tuple[list[AlignRow], list[str]]:
    """Pair id runs to labelled actions positionally (both are in performed order).

    Returns the paired rows and human-readable warnings — a length mismatch (noise or a
    missed action) or a run whose length disagrees with the labelled count.
    """
    rows: list[AlignRow] = []
    warnings: list[str] = []

    for index in range(max(len(runs), len(actions))):
        run = runs[index] if index < len(runs) else None
        action = actions[index] if index < len(actions) else None
        if run is not None and action is not None:
            row = AlignRow(run.id, action.name, run.count, action.count)
            rows.append(row)
            if not row.ok:
                warnings.append(
                    f"count mismatch at position {index}: id {run.id} occurs {run.count}x "
                    f"but label '{action.name}' says {action.count}x"
                )
        elif action is not None:
            rows.append(AlignRow(None, action.name, None, action.count))
            warnings.append(f"unmatched label at position {index}: '{action.name}' (no id run)")
        elif run is not None:
            warnings.append(
                f"unmatched id run at position {index}: id {run.id} ({run.count}x) has no label"
            )

    if len(runs) != len(actions):
        warnings.insert(
            0,
            f"{len(runs)} id runs vs {len(actions)} labelled actions - sequences differ in length",
        )
    return rows, warnings
