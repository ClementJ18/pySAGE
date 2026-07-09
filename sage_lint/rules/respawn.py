"""Rules for `RespawnUpdate.RespawnEntry` ladders. `RespawnEntry = Level:N Cost:.. Time:..`
names the veterancy rank a hero respawns into. Once listed, every `Level` must be a rank
the object actually has, and the entries must ascend by level.
"""

from collections.abc import Iterator

from sage_ini.model.behaviors import RespawnUpdate
from sage_ini.model.game import Game
from sage_ini.model.state import RankSelector
from sage_ini.parser.diagnostics import Diagnostic, Severity
from sage_ini.walk import walk_objects
from sage_lint.rules.base import Rule


def _respawn_ladders(game: Game) -> Iterator[tuple]:
    """Yield `(obj, levels)` for each `RespawnUpdate` that lists entries, where `levels` is a
    list of `(level, span)` in source order - each entry carries the span of its own
    `RespawnEntry` line so its diagnostic lands there rather than on the first entry.
    Iterating the object table keeps each module tied to the template whose rank ladder its
    entries must match."""
    for obj in game.objects.values():
        for module in walk_objects(obj, RespawnUpdate):
            try:
                entries = module.RespawnEntry or []
            except (ValueError, KeyError, TypeError, IndexError):
                continue  # a malformed entry is the converter's diagnostic, not ours
            spans = module.field_spans("RespawnEntry")
            default = spans[0] if spans else module.span
            levels = [
                (int(entry["Level"]), spans[index] if index < len(spans) else default)
                for index, entry in enumerate(entries)
                if isinstance(entry, dict) and entry.get("Level") is not None
            ]
            if levels:
                yield obj, levels


class RespawnLevelRule(Rule):
    """A `RespawnEntry` whose `Level` is not a rank the object is registered for (the
    `Rank`s of the `ExperienceLevel`s targeting it) - dead data, since the hero can
    never respawn at a rank it cannot reach."""

    code = "respawn-unknown-level"

    def check(self, game: Game) -> Iterator[Diagnostic]:
        for obj, levels in _respawn_ladders(game):
            ranks = {int(rank) for rank in RankSelector(obj, game).ranks}
            for level, span in levels:
                if level in ranks:
                    continue
                known = ", ".join(str(rank) for rank in sorted(ranks)) or "none"
                yield Diagnostic(
                    code=self.code,
                    message=(
                        f"{obj.name} RespawnEntry Level:{level} is not a rank it has an "
                        f"ExperienceLevel for (registered ranks: {known})"
                    ),
                    span=span,
                    severity=Severity.WARNING,
                    extra={"name": obj.name, "level": level, "ranks": sorted(ranks)},
                )


class RespawnOrderRule(Rule):
    """`RespawnEntry` levels that do not ascend. The engine matches a rank by scanning
    entries in order, so a duplicate or backwards step shadows its neighbour."""

    code = "respawn-entry-order"

    def check(self, game: Game) -> Iterator[Diagnostic]:
        for obj, levels in _respawn_ladders(game):
            for (previous, _), (level, span) in zip(levels, levels[1:], strict=False):
                if level > previous:
                    continue
                yield Diagnostic(
                    code=self.code,
                    message=(
                        f"{obj.name} RespawnEntry Level:{level} is out of order: "
                        f"it follows Level:{previous} but entries must ascend by level"
                    ),
                    span=span,
                    severity=Severity.WARNING,
                    extra={"name": obj.name, "level": level, "previous": previous},
                )
