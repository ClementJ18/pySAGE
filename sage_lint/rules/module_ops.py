"""Rule: validate a ChildObject's inherited-module edits.

An object built on another (`ChildObject Foo Base`) inherits Base's modules, then edits them:
`AddModule` contributes a new one, `ReplaceModule <tag>` swaps one out, `RemoveModule <tag>`
drops one. Each edit references a `ModuleTag_*` that must (or must not) already be present once
inheritance is taken into account, so a typo'd or stale tag silently no-ops in the engine. This
rule resolves the module set down the parent chain and checks each edit against it:

* `AddModule` - its tag must not already exist on the object or any parent.
* `ReplaceModule` - the replaced tag must exist; the replacement must be the same module type
  and carry a different tag.
* `RemoveModule` - the removed tag must exist.
"""

from collections.abc import Iterator

from sage_ini.model.game import Game
from sage_ini.model.ini_objects import ChildObject, Object
from sage_ini.parser.ast import Block
from sage_ini.parser.diagnostics import Diagnostic, Severity
from sage_ini.walk import walk_objects
from sage_lint.rules.base import Rule


def _local_tagged(obj) -> dict[str, object]:
    """`tag -> module` for every tagged module declared directly on `obj`. A still-unmodeled
    module block contributes its tag mapped to None (type unknown), so existence checks hold
    even where the schema is incomplete; a typed module overrides it."""
    result: dict[str, object] = {}
    for child in obj._extras:
        if isinstance(child, Block) and child.uses_equals and child.label:
            tokens = child.label.split()
            if len(tokens) >= 2:
                result[tokens[1]] = None
    for module in [*obj._modules, *obj._nested_data.get("Draw", [])]:
        if getattr(module, "tag", None):
            result[module.tag] = module
    return result


def _parent(obj):
    # A map.ini override inherits from the definition it patches (its `_override_base`), which
    # already carries the full parent chain; otherwise a ChildObject inherits from its declared
    # parent. The override base wins, since a same-name override cannot resolve a parent by name.
    base = getattr(obj, "_override_base", None)
    if base is not None:
        return base
    return obj.parent if isinstance(obj, ChildObject) else None


def default_module_tags(game: Game) -> dict[str, object]:
    """`tag -> module` for the modules every object inherits from `DefaultThingTemplate` - its
    own modules plus those wrapped in `InheritableModule` (copied into and kept by every
    object). Seeded into each object's base so a `Replace`/`Remove` of one is not mistaken for
    a missing module."""
    default = game.tables.get("objects", {}).get("DefaultThingTemplate")
    if default is None:
        return {}
    result = _local_tagged(default)
    for wrapper in default._nested_data.get("InheritableModule", []):
        module = wrapper.module
        if module is not None and module.tag:
            result[module.tag] = module
    return result


def effective_module_tags(obj, default_tags: dict[str, object]) -> dict[str, object]:
    """`tag -> module` for every module visible on `obj`: the default template's modules
    (`default_tags`), the parent chain's effective set, and the modules declared directly on
    `obj`. The shared "what modules does this object have" view (a fresh dict the caller may
    mutate)."""
    base = dict(default_tags)
    parent = _parent(obj)
    if parent is not None:
        base.update(_effective_modules(parent, {id(parent)}))
    base.update(_local_tagged(obj))
    return base


def resolved_module_tags(obj, default_tags: dict[str, object]) -> dict[str, object]:
    """`tag -> module` for the object's *final* module set - the default template's modules
    plus everything `_effective_modules` resolves (parent chain, this object's removes,
    replaces, adds and own modules). Unlike `effective_module_tags`, this includes the object's
    own `AddModule`s, so it answers "does this tag exist on the finished object?"."""
    tags = dict(default_tags)
    tags.update(_effective_modules(obj, {id(obj)}))
    return tags


def _removed_tags(obj) -> list[str]:
    value = obj._fields.get("RemoveModule")
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _effective_modules(obj, seen: set[int]) -> dict[str, object]:
    """`tag -> module` for everything visible on `obj`: its parents' effective set, then this
    object's removes, replaces, adds and own modules layered on top (the engine's order)."""
    result: dict[str, object] = {}
    parent = _parent(obj)
    if parent is not None and id(parent) not in seen:
        seen.add(id(parent))
        result.update(_effective_modules(parent, seen))
    for tag in _removed_tags(obj):
        result.pop(tag, None)
    for replace in obj._nested_data.get("ReplaceModule", []):
        result.pop(replace.name, None)
        new = replace.module
        if new is not None and new.tag:
            result[new.tag] = new
    for add in obj._nested_data.get("AddModule", []):
        new = add.module
        if new is not None and new.tag:
            result[new.tag] = new
    result.update(_local_tagged(obj))
    return result


class ModuleOperationRule(Rule):
    """An `AddModule`/`ReplaceModule`/`RemoveModule` whose target tag is wrong once inheritance
    is resolved: an add colliding with an existing tag, or a replace/remove of a module that
    is not there (and a replace must keep the type and change the tag). The engine quietly
    ignores such an edit, so the object does not end up as intended."""

    code = "invalid-module-operation"

    def check(self, game: Game) -> Iterator[Diagnostic]:
        default_tags = default_module_tags(game)
        for obj in walk_objects(game, Object):
            adds = obj._nested_data.get("AddModule", [])
            replaces = obj._nested_data.get("ReplaceModule", [])
            removes = _removed_tags(obj)
            if not (adds or replaces or removes):
                continue
            # Without the parent the inherited modules are unknown; skip rather than guess (a
            # single-file build that has not assembled the parent would otherwise misfire).
            if isinstance(obj, ChildObject) and obj.parent_name and obj.parent is None:
                continue

            base = effective_module_tags(obj, default_tags)

            for tag in removes:
                if tag in base:
                    base.pop(tag, None)
                else:
                    yield self._error(
                        obj,
                        obj._field_spans.get("RemoveModule", obj.span),
                        f"RemoveModule {tag!r} removes a module that does not exist on "
                        f"{obj.name!r} or its parents.",
                    )

            for replace in replaces:
                target, new = replace.name, replace.module
                if target not in base:
                    yield self._error(
                        obj,
                        replace.span,
                        f"ReplaceModule {target!r} replaces a module that does not exist on "
                        f"{obj.name!r} or its parents.",
                    )
                    continue
                old = base[target]
                if new is not None and old is not None and type(new) is not type(old):
                    yield self._error(
                        obj,
                        replace.span,
                        f"ReplaceModule {target!r} replaces a {type(old).__name__} with a "
                        f"{type(new).__name__}; a module can only be replaced by its own type.",
                    )
                elif new is not None and new.tag == target:
                    yield self._error(
                        obj,
                        replace.span,
                        f"ReplaceModule {target!r}: the replacement must use a different "
                        f"ModuleTag than the module it replaces.",
                    )
                base.pop(target, None)
                if new is not None and new.tag:
                    base[new.tag] = new

            for add in adds:
                new = add.module
                if new is None or new.tag is None:
                    continue
                if new.tag in base:
                    yield self._error(
                        obj,
                        add.span,
                        f"AddModule adds a module tagged {new.tag!r}, but one with that tag "
                        f"already exists on {obj.name!r} or its parents.",
                    )
                else:
                    base[new.tag] = new

    def _error(self, obj, span, message: str) -> Diagnostic:
        return Diagnostic(
            code=self.code,
            message=message,
            span=span,
            severity=Severity.ERROR,
            extra={"type": type(obj).__name__, "object": obj.name},
        )
