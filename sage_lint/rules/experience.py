"""Rules over the `ExperienceLevel` ladders objects are registered in.

An object has no ladder of its own: the engine builds one by scanning every `ExperienceLevel`
for a `TargetNames` that names the object, and ordering the hits by required experience. That
scan trusts the data to give each object **one** level per rank. Two levels claiming the same
object at the same rank leave it with an ambiguous ladder, which is a known crasher rather than
a merge - so this is an error, not a style note.

Sharing an object across *different* ranks is the normal shape (`FooLevel1`, `FooLevel2`, ...
each name the same unit), and a level naming many objects is normal too. Only the rank
collision is a defect.

`TargetNames` tokens are frequently `#define` lists, and in practice that is where the mistake
hides - two macros that each grew to include the same unit. So a collision reports the token it
came through as well as the object, since the edit belongs in the macro rather than on the
`TargetNames` line the diagnostic lands on.
"""

from collections.abc import Iterator

from sage_ini.model.game import Game
from sage_ini.model.state import expand_target_names
from sage_ini.parser.diagnostics import Diagnostic, Severity
from sage_lint.rules.base import Rule

#: How many colliding names a message spells out before summarising the rest.
_NAMES_SHOWN = 3


def _rank(level) -> float | None:
    """A level's `Rank`, or `None` when it declares none.

    A level with no rank cannot collide with anything: without it the engine has no key to
    place the level on the ladder, and guessing a default here would invent collisions between
    levels that merely leave the field out."""
    try:
        rank = level.Rank
    except (ValueError, KeyError, TypeError):
        return None  # a malformed rank is the converter's diagnostic, not ours
    return None if rank is None else float(rank)


def _claims(game: Game, level) -> dict[str, str]:
    """Every object name the level claims, mapped to the `TargetNames` token that produced it.

    A token that is a list macro expands to many names; one that is a plain object name maps to
    itself. Keeping the token is what lets the diagnostic point at the macro to fix."""
    raw = level._fields.get("TargetNames")
    entries = raw if isinstance(raw, list) else [raw]
    claims: dict[str, str] = {}
    for entry in entries:
        for token in str(entry).split() if entry else ():
            for name in expand_target_names(game, token):
                claims.setdefault(name, token)
    return claims


def _via(names: list[str], claims: dict[str, str]) -> str:
    """`" (via MACRO)"` when the collision arrived through list macros, else `""`."""
    tokens = sorted({claims[name] for name in names if claims.get(name) not in (None, name)})
    return f" (via {', '.join(tokens)})" if tokens else ""


def _span(level):
    """The `TargetNames` line, so the diagnostic lands on the claim rather than the block head."""
    spans = level.field_spans("TargetNames")
    return spans[0] if spans else level.span


class ExperienceLevelConflictRule(Rule):
    """An object named by two `ExperienceLevel`s that share a `Rank`.

    Reported once per pair of colliding levels rather than once per shared object, since a
    level naming thirty units collides on all thirty at once and that is one mistake."""

    code = "experience-level-conflict"

    def check(self, game: Game) -> Iterator[Diagnostic]:
        levels = list(game.tables.get("levels", {}).values())
        order = {id(level): index for index, level in enumerate(levels)}
        claims = {id(level): _claims(game, level) for level in levels}
        # (rank, name) -> the first level that claimed it. Keying by rank is what keeps the
        # common case - one unit across its whole ladder - from registering as a conflict.
        claimed: dict[tuple[float, str], object] = {}
        collisions: dict[tuple[int, int], list[str]] = {}

        for level in levels:
            rank = _rank(level)
            if rank is None:
                continue
            for name in sorted(claims[id(level)]):
                first = claimed.setdefault((rank, name), level)
                if first is not level:
                    collisions.setdefault((order[id(first)], order[id(level)]), []).append(name)

        for (first_index, second_index), names in sorted(collisions.items()):
            first, second = levels[first_index], levels[second_index]
            shown = ", ".join(names[:_NAMES_SHOWN])
            if len(names) > _NAMES_SHOWN:
                shown += f" and {len(names) - _NAMES_SHOWN} more"
            yield Diagnostic(
                code=self.code,
                message=(
                    f"{second.name} claims {shown}{_via(names, claims[id(second)])} at Rank "
                    f"{_rank(second):g}, which {first.name} already claims"
                    f"{_via(names, claims[id(first)])}; an object may sit on only one "
                    f"ExperienceLevel per rank"
                ),
                span=_span(second),
                severity=Severity.ERROR,
                extra={
                    "level": second.name,
                    "conflicts_with": first.name,
                    "rank": _rank(second),
                    "names": names,
                },
            )
