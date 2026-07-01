"""Rules over the set of top-level definitions a game declares."""

from collections.abc import Iterator

from sage_ini.model.game import Game
from sage_ini.model.xref import Xref, referenceable_keys
from sage_ini.parser.diagnostics import Diagnostic, Severity
from sage_lint.ruleconfig import always_referenced
from sage_lint.rules.base import Rule
from sage_lint.rules.references import _ASSET_TABLES

# Table keys the unused-definition rule never reports. `objects` has its own opt-in rule
# (`unused-object`), and the asset/audio tables are left to the asset checks — their names
# resolve in ways the in-memory reference graph does not see (a sound across several tables,
# an FX named inside a colon-keyed record), so a missing reverse edge there is not "unused".
# `factions` (PlayerTemplate) is referenceable in the schema but is really an engine entry point
# the game loads directly — most factions are named by nothing in the data, so flagging the
# unreferenced ones is noise, not a finding.
_UNUSED_DEFINITION_EXCLUDES = frozenset({"objects", "factions"}) | _ASSET_TABLES


def _overrides_existing(game: Game, key: str, name: str) -> bool:
    """Whether this game's definition `(key, name)` redefines one already built elsewhere — i.e.
    it sits in a context (a per-map build) layered over a reference fallback that already holds
    the name. Such a definition overrides what the engine reaches by that name, so the original
    (referenced where it lives) is what counts; flagging the override as unused is a false
    positive (e.g. a map.ini re-tuning a base-game `Science`)."""
    fallback = getattr(game, "_reference_fallback", None)
    return fallback is not None and fallback.lookup(key, name)[0] is not None


def _unused(game: Game, key: str) -> Iterator[tuple[object, str]]:
    """`(obj, name)` for each definition in table `key` that nothing in the game references.
    A kind named in the `always_referenced` config, and a definition overriding one built
    elsewhere, are skipped — both are reached in ways the in-memory reference graph cannot see."""
    always = always_referenced()
    xref = Xref.for_game(game)
    for obj in game.tables.get(key, {}).values():
        name = getattr(obj, "name", None)
        if not isinstance(name, str) or getattr(obj, "span", None) is None:
            continue
        if type(obj).__name__.lower() in always or key in always:
            continue
        if _overrides_existing(game, key, name):
            continue
        if not xref.is_referenced(obj):
            yield obj, name


class DuplicateDefinitionRule(Rule):
    """A unique-named definition declared twice in one file (the engine keeps the last
    and drops the earlier, so a same-file repeat is almost always a copy-paste slip).
    Cross-file redefinitions (the override mechanism) and collection types are not
    recorded as redefinitions, so neither flags."""

    code = "duplicate-definition"

    def check(self, game: Game) -> Iterator[Diagnostic]:
        for redef in game.redefinitions:
            yield Diagnostic(
                code=self.code,
                message=(
                    f"{redef.name} is defined again here; the earlier definition at "
                    f"line {redef.first.line_start} is overwritten (last wins)"
                ),
                span=redef.second,
                severity=Severity.WARNING,
                extra={
                    "key": redef.key,
                    "name": redef.name,
                    "first_line": redef.first.line_start,
                },
            )


class UnusedDefinitionRule(Rule):
    """A top-level definition of a *referenceable* kind (a weapon, upgrade, command set or
    button, locomotor, OCL, science, armor set, ...) that nothing in the loaded game names. The
    engine reaches such a definition only through a reference another definition holds, so an
    unreferenced one is dead data — built, then never used.

    Scope is deliberately narrow to stay useful rather than noisy. Engine entry-point kinds (a
    faction, the game data, a terrain, the living-world singletons) are loaded by the engine
    directly and named by nothing in the data, so they are excluded wholesale: the rule only
    considers kinds some typed field can actually reference (`referenceable_keys`). Objects get
    their own off-by-default rule (`unused-object`), and the asset/audio tables are left to the
    asset checks (see `_UNUSED_DEFINITION_EXCLUDES`).

    A definition may still be reached from a binary `.map` script the ini graph cannot see, so
    this is a WARNING, not an error."""

    code = "unused-definition"

    def check(self, game: Game) -> Iterator[Diagnostic]:
        for key in sorted(referenceable_keys() - _UNUSED_DEFINITION_EXCLUDES):
            for obj, name in _unused(game, key):
                yield Diagnostic(
                    code=self.code,
                    message=(
                        f"{type(obj).__name__} {name!r} is never referenced; no other "
                        f"definition names it."
                    ),
                    span=obj.span,
                    severity=Severity.WARNING,
                    extra={"name": name, "table": key, "type": type(obj).__name__},
                )


class UnusedObjectRule(Rule):
    """An `Object` definition that nothing in the loaded game references — no OCL, command
    button, horde member list or other field names it. Split from `unused-definition` and
    **off by default** (opt-in via `--select unused-object`) because objects are routinely
    reached in ways the ini reference graph cannot see: spawned by a binary `.map` script,
    placed straight onto a map, or named by a faction's build list. So an unreferenced object
    is a weaker signal than an unreferenced weapon, and surfacing every one by default would
    flood a real game. Enable it when auditing a self-contained data set for dead objects."""

    code = "unused-object"
    default = False

    def check(self, game: Game) -> Iterator[Diagnostic]:
        for obj, name in _unused(game, "objects"):
            yield Diagnostic(
                code=self.code,
                message=f"Object {name!r} is never referenced; no other definition names it.",
                span=obj.span,
                severity=Severity.WARNING,
                extra={"name": name, "table": "objects", "type": type(obj).__name__},
            )
