"""Read the annotation chunks a patched recording client writes into a replay.

A replay records *inputs*. Kills, losses, buildings traded and money earned are simulation
state, so no stock chunk carries them - which is why this package can say what a player did
and never what it cost them.

**Unless the recording client carried the `replay-annotations` patch**
(`sage_patch.patches.replay_annotations`), which writes, at the frame the recording ends:

- one `0x7D1` **manifest** naming the schema version and which record kinds that build writes;
- one `0x7D3` **score record** per player, carrying the engine's own `ScoreKeeper` counters -
  money earned and spent, units and structures built, lost and still alive, and two arrays of
  destructions indexed by the *victim*, which is a per-opponent kill matrix rather than a
  total.

These are not engine orders. The recorder only copies types `0x3E8 < t < 0x7CF` off the command
list and `GameMessage::Type` stops at `0x47B`, so nothing the engine emits can collide with the
reserved `0x7D0`-`0x7EF` block, and an unpatched replay simply carries none.

**Why the manifest matters.** Without it, an empty result is ambiguous: a corpus cannot tell a
build that does not write score records from a game in which nothing scored. `manifest` answers
the first question and `player_scores` the second, and an aggregate that counts absences should
consult both.

**Compatibility, both directions.** Integer argument 0 of every annotation is a schema version
and a record grows by *appending* arguments, so a position once shipped never changes meaning.
A record from a **later** schema is read for the prefix this reader knows, with its own
`schema_version` reported. A record from an **earlier** one keeps `None` for every field it
predates - which is why the v2 additions are all `int | None` and a consumer must test rather
than assume. Only a record short of the **v1 prefix** is malformed, and that one is skipped
rather than guessed at.

Schema v2 added the `Player`-level tail: the seat's resolved faction key, its resource balance,
its spellbook points and its command-point block. See `sage_patch/docs/replay-annotations.md`
§4.1 for why each is not derivable from the counters that were already there.
"""

from __future__ import annotations

from dataclasses import dataclass

from sage_replay.replay import (
    Bfme2OrderType,
    ReplayFile,
    ReplaySlot,
    integer_arguments,
)

__all__ = [
    "MAX_PLAYER_COUNT",
    "SCHEMA_VERSION",
    "SCORE_FIELDS",
    "AnnotationManifest",
    "PlayerScore",
    "manifest",
    "player_scores",
]

MANIFEST = Bfme2OrderType.AnnotationManifest
PLAYER_SCORE = Bfme2OrderType.PlayerScore

#: Every per-player array the engine embeds is this wide (`MAX_PLAYER_COUNT`), so the
#: destruction arrays carry one entry per possible player whether or not the slot was filled.
MAX_PLAYER_COUNT = 20

#: The score record's Integer arguments after the schema version, as `(name, width, since)` in
#: order - `since` being the schema version that introduced the field. This is the patch's
#: `SCORE_FIELDS`, restated - the two are the two ends of one contract and
#: `tests/sage_patch/test_replay_annotations.py` asserts they agree.
SCORE_FIELDS: tuple[tuple[str, int, int], ...] = (
    ("money_earned", 1, 1),
    ("money_spent", 1, 1),
    ("units_alive", 1, 1),
    ("structures_alive", 1, 1),
    ("end_frame", 1, 1),
    ("units_destroyed", MAX_PLAYER_COUNT, 1),
    ("units_built", 1, 1),
    ("units_lost", 1, 1),
    ("structures_destroyed", MAX_PLAYER_COUNT, 1),
    ("structures_built", 1, 1),
    ("structures_lost", 1, 1),
    ("faction_name_key", 1, 2),
    ("resources", 1, 2),
    ("power_points", 1, 2),
    ("power_points_total", 1, 2),
    ("command_points_used", 1, 2),
    ("command_points_cap", 1, 2),
    ("command_points_bonus", 1, 2),
    ("command_points_hard_cap", 1, 2),
)

#: The schema version this reader knows every field of. A record declaring more is read for
#: the prefix defined here; one declaring less keeps `None` for what it predates.
SCHEMA_VERSION = 2

#: Integers a record must carry to be read at all - the v1 prefix. A record shorter than this
#: is malformed rather than old, and is skipped.
_REQUIRED_VALUES = 1 + sum(w for _, w, since in SCORE_FIELDS if since == 1)

_SCORE_VALUES = 1 + sum(width for _, width, _ in SCORE_FIELDS)
_MANIFEST_VALUES = 3

_KIND_PLAYER_SCORE = 1 << 0


@dataclass(slots=True, frozen=True)
class AnnotationManifest:
    """What the recording build said it writes."""

    schema_version: int
    kinds: int  #: bitmask of the record kinds this build writes
    writer_id: int  #: identifies the writer, `0x53414745` ('SAGE') for `sage_patch`
    recorded_at: int  #: the timecode the annotation batch was written at

    @property
    def writes_player_scores(self) -> bool:
        """Whether this build writes `0x7D3` records - so that a replay with none means the
        game scored nothing, not that the information was never recorded."""
        return bool(self.kinds & _KIND_PLAYER_SCORE)


@dataclass(slots=True, frozen=True)
class PlayerScore:
    """One player's `ScoreKeeper` at the frame the recording ended.

    `units_destroyed` and `structures_destroyed` are indexed by the **victim's** engine player
    number, not by metadata slot; `destroyed_by_slot` does that mapping. Every other field is a
    plain total.
    """

    slot_index: int
    slot: ReplaySlot
    number: int  #: the engine player number the record was written under
    schema_version: int
    recorded_at: int
    money_earned: int
    money_spent: int
    units_alive: int
    structures_alive: int
    end_frame: int
    units_destroyed: tuple[int, ...]
    units_built: int
    units_lost: int
    structures_destroyed: tuple[int, ...]
    structures_built: int
    structures_lost: int
    #: Everything below arrived with schema v2 and is None in a record written before it.
    #:
    #: `faction_name_key` is the seat's **resolved** `PlayerTemplate` name key - the answer to
    #: what a `Random` slot actually became, which the header's lobby faction id never carries.
    #: It is an interned key, so it means nothing without the game that made it; 0 marks a seat
    #: with no template (the neutral slot).
    faction_name_key: int | None = None
    #: The spendable balance at the closing frame. **Not** derivable from the money counters:
    #: `money_spent` carries a setup charge that was never deducted from this.
    resources: int | None = None
    power_points: int | None = None
    power_points_total: int | None = None
    command_points_used: int | None = None
    command_points_cap: int | None = None
    command_points_bonus: int | None = None
    command_points_hard_cap: int | None = None

    @property
    def command_point_ceiling(self) -> int | None:
        """The army cap this seat actually played under, as `min(cap + bonus, hard cap)`.

        A **lower bound**: the engine adds a third term from a filtered vector whose entries
        must be evaluated against the world, which nothing outside the running game can do. So
        a seat that built `CPObject`s reads at least this high, possibly higher.
        """
        if self.command_points_cap is None:
            return None
        assert self.command_points_bonus is not None
        assert self.command_points_hard_cap is not None
        return min(
            self.command_points_cap + self.command_points_bonus, self.command_points_hard_cap
        )

    @property
    def total_units_destroyed(self) -> int:
        return sum(self.units_destroyed)

    @property
    def total_structures_destroyed(self) -> int:
        return sum(self.structures_destroyed)

    def destroyed_by_slot(self, replay: ReplayFile) -> dict[int, tuple[int, int]]:
        """`{victim slot index: (units, structures)}` for every victim this player destroyed
        anything of, mapping the arrays' engine player numbers onto metadata slots the same way
        a chunk's own number is mapped. Entries that fall outside the occupied slots - the
        neutral player, unfilled positions - are dropped rather than guessed at."""
        offset = self.slot_index - self.number
        found: dict[int, tuple[int, int]] = {}
        for number, (units, structures) in enumerate(
            zip(self.units_destroyed, self.structures_destroyed, strict=True)
        ):
            if not units and not structures:
                continue
            index = number + offset
            if 0 <= index < len(replay.header.metadata.players):
                found[index] = (units, structures)
        return found


def manifest(replay: ReplayFile) -> AnnotationManifest | None:
    """The annotation manifest `replay` carries, or None when the recording client did not
    write one (an unpatched client, or one carrying only `replay-outcome`). A later batch wins
    over an earlier one, so a teardown that somehow ran twice reports its last word."""
    found: AnnotationManifest | None = None
    for chunk in replay.chunks:
        if chunk.order_type != MANIFEST:
            continue
        values = _integers(chunk, _MANIFEST_VALUES)
        if values is None:
            continue
        version, kinds, writer = values[:_MANIFEST_VALUES]
        found = AnnotationManifest(
            schema_version=version,
            kinds=kinds,
            writer_id=writer,
            recorded_at=chunk.timecode,
        )
    return found


def player_scores(replay: ReplayFile) -> dict[int, PlayerScore]:
    """The per-player score records `replay` carries, keyed by metadata slot index. Empty when
    the recording client did not carry the patch.

    A record names its player exactly as a real order does - the engine's own `m_playerIndex`
    in the chunk's number field - so `ReplayFile.slot_index` maps it with no extra rule.
    Records whose number falls outside the occupied slots, or that carry fewer Integers than
    the schema defines, are skipped rather than guessed at.
    """
    found: dict[int, PlayerScore] = {}
    for chunk in replay.chunks:
        if chunk.order_type != PLAYER_SCORE:
            continue
        index = replay.slot_index(chunk)
        if index is None:
            continue
        values = _integers(chunk, _REQUIRED_VALUES)
        if values is None:
            continue
        # Take whichever prefix the record actually carries. A field the record is too short
        # for is left unset - which is `None` for a v2 field and impossible for a v1 one, since
        # `_integers` already refused anything below `_REQUIRED_VALUES`.
        fields: dict[str, object] = {}
        cursor = 1
        for name, width, _ in SCORE_FIELDS:
            if cursor + width > len(values):
                break
            if width == 1:
                fields[name] = values[cursor]
            else:
                fields[name] = tuple(values[cursor : cursor + width])
            cursor += width
        found[index] = PlayerScore(
            slot_index=index,
            slot=replay.header.metadata.players[index],
            number=chunk.number,
            schema_version=values[0],
            recorded_at=chunk.timecode,
            **fields,  # type: ignore[arg-type]
        )
    return found


def _integers(chunk: object, needed: int) -> list[int] | None:
    """**All** of the chunk's Integer arguments, when it carries at least `needed` of them and
    every one is a number, else None.

    Returning the whole list rather than the first `needed` is what lets a caller read a record
    written by a **later** schema than it knows: the extra arguments are present, and the caller
    stops where its own field table stops. Truncating here would make every record look like the
    oldest one this reader understands.

    A replay rehydrated from a translated document carries resolved code names in the Integer
    slots that hold ids; annotations hold engine numbers with no id space behind them, so a
    name here means the document was edited rather than translated, and is not readable.
    """
    values = integer_arguments(chunk)  # type: ignore[arg-type]
    if len(values) < needed or any(not isinstance(v, int) for v in values):
        return None
    return [v for v in values if isinstance(v, int)]
