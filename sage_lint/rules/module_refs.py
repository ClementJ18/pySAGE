"""Rule: a module-tag field naming a module that the object does not actually have.

Some module fields point at *another module on the same object* by its `ModuleTag_*` rather
than at a Game-table definition - `ActivateModuleSpecialPower.TriggerSpecialPower` names the
module it fires. A converter cannot check these (it has no view of the parent object), so this
rule resolves each object's final module set (inheritance, adds/replaces/removes included) and
flags a tag that is not among them: the engine finds no such module and the trigger silently
does nothing.
"""

from collections.abc import Iterator

from sage_ini.model.behaviors import ActivateModuleSpecialPower
from sage_ini.model.game import Game
from sage_ini.model.ini_objects import ChildObject, Object
from sage_ini.parser.diagnostics import Diagnostic, Severity
from sage_ini.walk import walk_objects
from sage_lint.rules.base import Rule
from sage_lint.rules.module_ops import default_module_tags, resolved_module_tags


def _trigger_modules(obj) -> Iterator[ActivateModuleSpecialPower]:
    """Every `ActivateModuleSpecialPower` on `obj`, declared directly or contributed by an
    `AddModule`/`ReplaceModule` edit."""
    for module in obj._modules:
        if isinstance(module, ActivateModuleSpecialPower):
            yield module
    edits = (*obj._nested_data.get("AddModule", []), *obj._nested_data.get("ReplaceModule", []))
    for wrapper in edits:
        module = getattr(wrapper, "module", None)
        if isinstance(module, ActivateModuleSpecialPower):
            yield module


class ModuleTagReferenceRule(Rule):
    """A `TriggerSpecialPower` whose `ModuleTag` names no module on the owning object once
    inheritance is resolved. The engine finds nothing to fire, so the special power silently
    never triggers - almost always a typo'd or stale tag."""

    code = "module-tag-reference"

    def check(self, game: Game) -> Iterator[Diagnostic]:
        default_tags = default_module_tags(game)
        for obj in walk_objects(game, Object):
            triggers = list(_trigger_modules(obj))
            if not triggers:
                continue
            # Without the parent the inherited modules are unknown; skip rather than guess (a
            # single-file build that has not assembled the parent would otherwise misfire).
            if isinstance(obj, ChildObject) and obj.parent_name and obj.parent is None:
                continue

            tags = resolved_module_tags(obj, default_tags)
            for module in triggers:
                try:
                    entries = module.TriggerSpecialPower
                except (ValueError, KeyError, TypeError, IndexError):
                    continue  # a bad value is the conversion pass's own diagnostic
                for entry in entries or []:
                    tag = entry[0] if isinstance(entry, tuple) else entry
                    if not isinstance(tag, str) or tag in tags:
                        continue
                    yield Diagnostic(
                        code=self.code,
                        message=(
                            f"{type(obj).__name__} {obj.name!r}: TriggerSpecialPower references "
                            f"module tag {tag!r}, which no module on this object declares."
                        ),
                        span=module._field_spans.get("TriggerSpecialPower", module.span),
                        severity=Severity.WARNING,
                        extra={"type": type(obj).__name__, "object": obj.name, "tag": tag},
                    )
