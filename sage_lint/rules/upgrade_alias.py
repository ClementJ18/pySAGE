"""Rules for descriptive aliases on upgrade references (`Upgrade_TestBuilding@SmithyLevel2`).

The engine gives every distinct upgrade name one bit in a fixed global mask, so a mod short on
bits reuses a few generic upgrades as object-local flags. `Upgrade_TestBuilding` means one thing
on an Isengard tent and something unrelated on a Mordor camp, and nothing in the text says which.
An alias records the intent at the reference; `sage_ini.model.aliases` defines the split, and
these rules are what makes the annotation load-bearing rather than decorative.

The alias is read off the *raw* field text, not the converted value: resolution deliberately
drops it (the alias is not part of the upgrade's identity), so by the time a field converts, the
annotation is gone. A field counts as carrying upgrade references when its annotation can reach
the `upgrades` table through whatever container or record shape it is written as, which
`xref.annotation_keys` answers from the schema.

What the rules judge, in the order a problem matters:

* an alias on a *definition* header, which the engine resolves like any other name and so turns
  a new upgrade into a silent override of the one it aliases (`upgrade-alias-in-definition`);
* an alias that is not spelled like an intent name, usually a stray separator
  (`upgrade-alias-malformed`);
* one upgrade carrying two different intents on a single runtime object, which is the bit
  collision the whole convention exists to catch (`upgrade-alias-conflict`);
* an upgrade annotated in some places and left bare in others, so the convention is adopted per
  upgrade and then enforced (`upgrade-alias-inconsistent`).
"""

from collections import defaultdict
from collections.abc import Iterator
from dataclasses import dataclass

from sage_ini.model.aliases import ALIAS_SEPARATOR, ALIASED_TABLES, is_well_formed, resolve_alias
from sage_ini.model.game import Game
from sage_ini.model.ini_objects import ChildObject, Object
from sage_ini.model.objects import IniObject, Module
from sage_ini.model.xref import annotation_keys
from sage_ini.parser.diagnostics import Diagnostic, Severity
from sage_ini.parser.location import Span
from sage_ini.suggest import suggestion_hint
from sage_lint.rules.base import Rule

# How far a `ChildObject` parent chain is followed before assuming it loops. Inheritance in the
# data is a handful of levels deep; anything past this is a cycle, which is a separate diagnostic.
_MAX_INHERITANCE_DEPTH = 16


@dataclass(frozen=True)
class AliasUse:
    """One upgrade reference token as written, with whatever intent it was annotated with."""

    root: IniObject  # the top-level definition the reference lives in
    obj: IniObject  # the node carrying the field (an `Object`, a module, a nested record)
    field: str
    name: str  # the upgrade name the engine resolves, alias removed
    alias: str | None  # None when the token carries no separator
    module_tag: str | None  # `ModuleTag_*` of the nearest enclosing module, for override checks
    span: Span

    @property
    def canonical(self) -> str:
        """The upgrade's name folded for grouping - engine name lookup ignores case."""
        return self.name.lower()


def _upgrade_fields(cls: type[IniObject]) -> frozenset[str]:
    """The field keys of `cls` whose annotation can reach an alias-taking table.

    Resolving every annotation of every class costs more than the walk that uses the answer, so
    it is memoized on the class next to the `_fieldspec` it was derived from. `rebuild_schema`
    assigns a *new* fieldspec dict, so the identity check expires the entry exactly when an
    engine injects or retypes a field, and holding the dict keeps the comparison honest."""
    fieldspec = getattr(cls, "_fieldspec", {})
    cached = cls.__dict__.get("_upgrade_alias_fields")
    if cached is not None and cached[0] is fieldspec:
        return cached[1]
    found = set()
    for key, annotation in fieldspec.items():
        try:
            if ALIASED_TABLES & annotation_keys(annotation):
                found.add(key)
        except (KeyError, TypeError):
            continue  # an annotation naming no registered class is not a reference
    keys = frozenset(found)
    cls._upgrade_alias_fields = (fieldspec, keys)  # type: ignore[attr-defined]
    return keys


def _walk_tagged(obj: IniObject, tag: str | None = None) -> Iterator[tuple[IniObject, str | None]]:
    """Every node under `obj` paired with the `ModuleTag_*` of the module it sits in. The tag is
    what makes inheritance decidable: a child re-declaring a parent's tag replaces that module
    rather than adding a second one."""
    yield obj, tag
    for items in obj._nested_data.values():
        for item in items:
            if isinstance(item, IniObject):
                yield from _walk_tagged(item, tag)
    for module in obj._modules:
        inner = module.tag if isinstance(module, Module) else tag
        yield from _walk_tagged(module, inner)


def _occurrences(obj: IniObject, key: str, fields: dict) -> Iterator[tuple[str, Span]]:
    """`(raw_value, span)` per occurrence of `key` - a repeated key writes one line each, and
    each has to land its own diagnostic rather than stacking on the first."""
    value = fields.get(key)
    values = value if isinstance(value, list) else [value]
    spans = obj.field_spans(key)
    fallback = spans[-1] if spans else obj.span
    for index, raw in enumerate(values):
        if isinstance(raw, str):
            yield raw, (spans[index] if index < len(spans) else fallback)


def _tokens(raw: str) -> Iterator[str]:
    """The reference tokens on one raw value. A `Key:value` component of a colon-keyed line
    (`Upgrade_A Upgrade_B Delay:1000`) is never a reference name, so it is dropped."""
    for token in raw.split():
        if ":" not in token and token.lower() not in ("", "none"):
            yield token


def iter_alias_uses(game: Game) -> Iterator[AliasUse]:
    """Every upgrade reference token in the game, annotated or not.

    A token counts when it either carries a separator or resolves to a known upgrade. That
    second test is what keeps a stray word out of the results: a scalar field the engine reads
    one token from may have trailing text, and a colon-keyed line mixes names with components.
    An annotated token counts even when its name resolves to nothing, so a typo'd base name is
    still judged here rather than vanishing (the dangling-reference rule reports the name)."""
    for table in game.tables.values():
        for root in table.values():
            for node, tag in _walk_tagged(root):
                keys = _upgrade_fields(type(node))
                if not keys:
                    continue
                fields = node.fields
                for key in keys & fields.keys():
                    for raw, span in _occurrences(node, key, fields):
                        for token in _tokens(raw):
                            name, alias = resolve_alias(game, "upgrades", token)
                            if alias is None and game.lookup("upgrades", name)[0] is None:
                                continue
                            yield AliasUse(root, node, key, name, alias, tag, span)


def _inheritance_chain(root: IniObject) -> list[IniObject]:
    """`root` followed by the `ChildObject` parents whose modules it inherits, nearest first.
    Everything in the chain writes into one runtime object's upgrade mask, so an alias conflict
    across the chain is as real as one inside a single block - and harder to see, since the two
    uses sit in different files."""
    chain = [root]
    current = root
    seen = {id(root)}
    while isinstance(current, ChildObject) and len(chain) < _MAX_INHERITANCE_DEPTH:
        parent = current.parent
        if parent is None or id(parent) in seen:
            break
        chain.append(parent)
        seen.add(id(parent))
        current = parent
    return chain


def _live_uses(chain: list[IniObject], by_root: dict[int, list[AliasUse]]) -> list[AliasUse]:
    """The alias uses that survive inheritance onto one runtime object. Walking the chain from
    the most derived end, a module tag already claimed by a nearer definition shadows the
    parent's module of that tag, so the parent's uses inside it never run."""
    live: list[AliasUse] = []
    claimed: set[str] = set()
    for definition in chain:
        tags = {use.module_tag for use in by_root.get(id(definition), ()) if use.module_tag}
        for use in by_root.get(id(definition), ()):
            if use.module_tag is None or use.module_tag not in claimed:
                live.append(use)
        claimed |= tags
    return live


class UpgradeAliasInDefinitionRule(Rule):
    """An upgrade *definition* whose name carries an alias separator. The engine resolves a
    block header through the same name lookup as a reference, so `Upgrade Upgrade_X@Thing` does
    not declare a new upgrade: it finds `Upgrade_X` and overrides it in place, keeping its mask
    bit and silently rewriting the upgrade every other object shares. An alias belongs on a
    reference, never on the declaration."""

    code = "upgrade-alias-in-definition"

    def check(self, game: Game) -> Iterator[Diagnostic]:
        for key in sorted(ALIASED_TABLES):
            for name, obj in game.tables.get(key, {}).items():
                if not isinstance(name, str) or ALIAS_SEPARATOR not in name:
                    continue
                base = name.split(ALIAS_SEPARATOR, 1)[0]
                yield Diagnostic(
                    code=self.code,
                    message=(
                        f"{type(obj).__name__} {name!r} declares an alias on its name. The engine "
                        f"resolves a header like any other reference, so this overrides "
                        f"{base!r} instead of declaring a new upgrade. Name the definition "
                        f"{base!r} and put the alias on the references to it."
                    ),
                    span=obj.span,
                    severity=Severity.ERROR,
                    extra={"name": name, "base": base, "table": key},
                )


class UpgradeAliasMalformedRule(Rule):
    """An alias that is not spelled like an intent name - empty (`Upgrade_X@`), or carrying a
    second separator. Both come from a stray `@` rather than a deliberate annotation, and both
    resolve to the bare upgrade at load, so nothing else would ever report them."""

    code = "upgrade-alias-malformed"

    def check(self, game: Game) -> Iterator[Diagnostic]:
        for use in iter_alias_uses(game):
            if use.alias is None or is_well_formed(use.alias):
                continue
            detail = "is empty" if not use.alias else "is not an identifier"
            yield Diagnostic(
                code=self.code,
                message=(
                    f"{type(use.obj).__name__}.{use.field} annotates {use.name!r} with an alias "
                    f"that {detail}: {use.alias!r}."
                ),
                span=use.span,
                severity=Severity.ERROR,
                extra={"name": use.name, "alias": use.alias, "key": use.field},
            )


class UpgradeAliasConflictRule(Rule):
    """One upgrade used for two different intents on a single object - the bit collision the
    alias convention exists to make visible. The two uses share a mask bit, so granting the
    upgrade for one purpose fires the other as well.

    Scope is the runtime object, which means a `ChildObject` is judged together with the parents
    it inherits modules from: the common form of this bug is a child adding a use of a generic
    upgrade its parent already spends, in a different file, where nothing puts the two lines
    side by side. A module the child re-declares by tag replaces the parent's, so its uses drop
    out rather than counting twice."""

    code = "upgrade-alias-conflict"

    def check(self, game: Game) -> Iterator[Diagnostic]:
        by_root: dict[int, list[AliasUse]] = defaultdict(list)
        for use in iter_alias_uses(game):
            if use.alias:
                by_root[id(use.root)].append(use)
        for root in game.tables.get("objects", {}).values():
            if not isinstance(root, Object):
                continue
            chain = _inheritance_chain(root)
            if not any(id(link) in by_root for link in chain):
                continue
            grouped: dict[str, dict[str, AliasUse]] = defaultdict(dict)
            for use in _live_uses(chain, by_root):
                if use.alias is not None:  # `by_root` collected only the annotated ones
                    grouped[use.canonical].setdefault(use.alias, use)
            for uses in grouped.values():
                if len(uses) < 2:
                    continue
                # Report in source order so the anchor is the line that introduced the clash,
                # not whichever intent sorts first alphabetically.
                ordered = sorted(
                    uses.values(), key=lambda use: (use.span.file, use.span.line_start)
                )
                first, *rest = ordered
                where = ", ".join(f"{use.alias!r} at {use.span}" for use in ordered)
                for use in rest:
                    yield Diagnostic(
                        code=self.code,
                        message=(
                            f"{root.name} uses {use.name!r} for {len(uses)} different purposes, "
                            f"which share one upgrade bit: {where}. Give each purpose its own "
                            f"upgrade, or settle on one alias if they really are the same flag."
                        ),
                        span=use.span,
                        severity=Severity.ERROR,
                        extra={
                            "object": root.name,
                            "name": use.name,
                            "alias": use.alias,
                            "aliases": sorted(uses),
                            "first": str(first.span),
                        },
                    )


class UpgradeAliasInconsistentRule(Rule):
    """An upgrade annotated in some places and left bare in others. The convention is adopted
    one upgrade at a time - annotating a name anywhere is the statement that its uses carry
    distinct intents - and from then on a bare reference to it is an unannotated use rather than
    an upgrade nobody has got to yet. Silent on data that uses no aliases at all, so it costs
    nothing until the convention is taken up.

    A bare use next to an established alias set is also where typos surface, so the message
    suggests the nearest known intent when the field looks like a misspelling of one."""

    code = "upgrade-alias-inconsistent"

    def check(self, game: Game) -> Iterator[Diagnostic]:
        uses = list(iter_alias_uses(game))
        aliases: dict[str, set[str]] = defaultdict(set)
        for use in uses:
            if use.alias and is_well_formed(use.alias):
                aliases[use.canonical].add(use.alias)
        for use in uses:
            known = aliases.get(use.canonical)
            if use.alias is not None or not known:
                continue
            hint, suggestion = suggestion_hint(use.field, sorted(known))
            yield Diagnostic(
                code=self.code,
                message=(
                    f"{type(use.obj).__name__}.{use.field} references {use.name!r} with no "
                    f"alias, but it is annotated elsewhere as "
                    f"{', '.join(repr(alias) for alias in sorted(known))}. Say which purpose "
                    f"this use serves.{hint}"
                ),
                span=use.span,
                severity=Severity.WARNING,
                extra={
                    "name": use.name,
                    "key": use.field,
                    "known": sorted(known),
                    "suggestion": suggestion,
                },
            )
