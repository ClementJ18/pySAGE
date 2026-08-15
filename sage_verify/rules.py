"""The judgement, with no game and no process attached to it.

Everything that decides whether an order was legitimate lives here and takes plain data, so the
rule can be tested against constructed situations rather than only against a match somebody has
to play. `watch` is the part that fetches the data.

**The rule, in one line:** an order naming a target its issuer has never been able to see is
evidence the issuer knew something the game did not tell them.

Three things make that harder than it sounds, and each is handled explicitly rather than
averaged away.

**1. The engine has no memory, so this module has to.** The shroud grid answers "can this seat
see that cell *right now*" and nothing else - a cell scouted an hour ago reads identically to one
never reached (`sage_live.api.shroud`). A human, though, can attack a building they scouted long
ago, and calling that a violation would bury every real finding under them. `Memory` therefore
accumulates what each seat has been observed to see, and a target is only ever a finding if it
was **never** seen. That memory is only as complete as the sampling, which is why
`Snapshot.frame` travels with every verdict and why a stale snapshot refuses to judge.

**2. Judging must use the state *before* the order.** Attacking a unit reveals it, so the shroud
one frame after an attack shows the target plainly visible. A verdict computed from a later
sample is therefore lenient - it clears real maphacks - which is the safe direction but a useless
one. `judge` is handed the snapshot at or before the order's frame, and refuses when the nearest
one is further back than the caller's tolerance.

**3. Own and allied targets are not evidence.** Repairing your own wall or entering your own
building names an object you own; that is not visibility, it is bookkeeping.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from sage_live.api.shroud import CellShroud, ShroudGrid
from sage_verify.orders import OrderTarget

__all__ = ["Memory", "Snapshot", "Verdict", "judge"]

#: A world position, as it comes off an object or an order argument.
_Point = tuple[float, float, float]


@dataclass(frozen=True)
class Snapshot:
    """One sampled frame: where everything was, and who could see what.

    Deliberately a value rather than a live `Observation`. The judgement needs a frame's worth of
    facts and nothing else, and keeping it to that is what lets a test construct one.
    """

    frame: int
    #: `{object_id -> (position, owner index)}` for every object in the frame.
    objects: Mapping[int, tuple[_Point, int]]
    #: The engine's grid for the seats being watched, or None where none was readable.
    shroud: ShroudGrid | None

    def owner_of(self, object_id: int) -> int | None:
        entry = self.objects.get(object_id)
        return None if entry is None else entry[1]

    def position_of(self, object_id: int) -> _Point | None:
        entry = self.objects.get(object_id)
        return None if entry is None else entry[0]

    def sees_position(self, position: _Point, player: int) -> bool:
        if self.shroud is None:
            return False
        return self.shroud.status(position, player) is CellShroud.CLEAR


@dataclass
class Memory:
    """What each seat has been *observed* to have seen, accumulated across sampled frames.

    This is the explored-versus-never-explored distinction the engine does not keep per cell, so
    it is reconstructed here from the frames that were actually sampled. Two consequences worth
    stating rather than hiding:

    - It can only ever be an **under**-estimate of what a player has seen, because it misses
      whatever was revealed and re-hidden between two samples. Under-estimating knowledge
      manufactures false positives, which is why `watch` samples as fast as it can and why a
      finding carries the sampling gap that produced it.
    - It is per *object id*, not per cell, for object targets. A player who has seen a unit once
      has seen it; where it stood at the time is not the question being asked.
    """

    #: `{player index -> object ids that player has been seen to have line of sight on}`
    objects: dict[int, set[int]] = field(default_factory=dict)
    #: `{player index -> (cx, cy) cells that player has been seen to reveal}`
    cells: dict[int, set[tuple[int, int]]] = field(default_factory=dict)
    #: The most recent frame absorbed, for reporting how far the memory reaches.
    frame: int = -1

    def absorb(self, snapshot: Snapshot, players: Iterable[int]) -> None:
        """Fold one sampled frame into the memory."""
        grid = snapshot.shroud
        if grid is None:
            return
        self.frame = max(self.frame, snapshot.frame)
        for player in players:
            seen_objects = self.objects.setdefault(player, set())
            for object_id, (position, _) in snapshot.objects.items():
                if grid.status(position, player) is CellShroud.CLEAR:
                    seen_objects.add(object_id)
            seen_cells = self.cells.setdefault(player, set())
            column = grid.levels.get(player)
            if column is None:
                continue
            for index in range(grid.cell_count):
                level = int.from_bytes(column[index * 2 : index * 2 + 2], "little")
                if level and level != 0xFFFF:
                    seen_cells.add((index % grid.cells_x, index // grid.cells_x))

    def has_seen_object(self, player: int, object_id: int) -> bool:
        return object_id in self.objects.get(player, ())

    def has_seen_cell(self, player: int, cell: tuple[int, int]) -> bool:
        return cell in self.cells.get(player, ())


@dataclass(frozen=True)
class Verdict:
    """The answer for one order.

    `ok` and `unjudged` are both non-findings and are kept apart on purpose: "this order was
    legitimate" and "nothing here could be checked" are different statements, and collapsing them
    is how a tool ends up reporting a clean match it never actually looked at.
    """

    #: One of `ok`, `violation`, `unjudged`.
    outcome: str
    #: Why, in a sentence, for whichever outcome it is.
    reason: str
    #: `high` for object targets, `low` for ground targets; None when there is no finding.
    confidence: str | None = None

    @property
    def is_finding(self) -> bool:
        return self.outcome == "violation"


_OK = Verdict("ok", "target was visible or already known")


def judge(
    target: OrderTarget,
    *,
    player: int,
    frame: int,
    snapshot: Snapshot | None,
    memory: Memory,
    max_lag: int,
    allies: Iterable[int] = (),
) -> Verdict:
    """Whether `player` could legitimately have named `target` at `frame`.

    `snapshot` is the most recent sample at or before `frame`; None, or one further back than
    `max_lag` frames, refuses to judge rather than guessing from stale visibility.
    """
    if snapshot is None:
        return Verdict("unjudged", f"no visibility sample at or before frame {frame}")
    if snapshot.frame > frame:
        return Verdict(
            "unjudged",
            f"nearest sample is frame {snapshot.frame}, after the order at {frame}",
        )
    lag = frame - snapshot.frame
    if lag > max_lag:
        return Verdict(
            "unjudged",
            f"nearest sample is {lag} frames stale (limit {max_lag}) - visibility may have changed",
        )
    if snapshot.shroud is None:
        return Verdict("unjudged", "no shroud grid was readable in that sample")
    if not snapshot.shroud.fog_enabled:
        return Verdict("unjudged", "the match is running with fog of war switched off")

    friendly = {player, *allies}

    if target.is_object:
        object_id = target.object_id
        assert object_id is not None
        owner = snapshot.owner_of(object_id)
        if owner is None:
            return Verdict("unjudged", f"object {object_id} was not in the sampled frame")
        if owner in friendly:
            return _OK
        position = snapshot.position_of(object_id)
        assert position is not None
        if snapshot.sees_position(position, player):
            return _OK
        if memory.has_seen_object(player, object_id):
            return _OK
        return Verdict(
            "violation",
            f"ordered against object {object_id} (owned by player {owner}), which player "
            f"{player} has never been observed to see - not visible at frame {snapshot.frame} "
            "and absent from every earlier sample",
            confidence="high",
        )

    if target.is_position:
        position = target.position
        assert position is not None
        if snapshot.sees_position(position, player):
            return _OK
        cell = snapshot.shroud.cell_of(position[0], position[1])
        if memory.has_seen_cell(player, cell):
            return _OK
        return Verdict(
            "violation",
            f"targeted ground at {position[0]:.0f},{position[1]:.0f} (cell {cell[0]},{cell[1]}), "
            f"which player {player} has never been observed to reveal",
            confidence="low",
        )

    return Verdict("unjudged", "the order names no target")
