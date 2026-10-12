"""Rule: a contain module an enter order never reaches.

An object stores one contain - the last one it declares, inheritance and module edits resolved -
and the stock engine asks only that one whether a unit may enter. The `multi-contain` binary
patch widens this for exactly one kind of module: a slaughter contain (`SlaughterHordeContain`
and its `CitadelSlaughterHordeContain` child) declared *before* the stored one takes the riders the
stored one refuses. A slaughter contain is the only kind that can, because it destroys a rider as
it takes it and never holds anyone; leaving, evacuating and dying inside still go through the
stored contain alone. See `sage_patch/docs/multi-contain.md`.

The rule runs only against an engine that carries the patch (the `contain.secondary_slaughter`
limit a `.sagepatch` declares). On a stock engine every earlier contain is unreachable, and Edain
ships objects in that shape on purpose, so it stays silent there.
"""

from collections.abc import Iterator

from sage_ini.engine import active
from sage_ini.model.behaviors import ContainBehavior, SlaughterHordeContain
from sage_ini.model.game import Game
from sage_ini.model.ini_objects import ChildObject, Object
from sage_ini.model.objects import IniObject
from sage_ini.parser.diagnostics import Diagnostic, Severity
from sage_ini.walk import walk_objects
from sage_lint.rules.base import Rule
from sage_lint.rules.module_ops import default_module_tags, resolved_module_tags

# Set to 1 by the multi-contain patch; 0 (stock) means only the last contain is ever asked.
_SECONDARY_SLAUGHTER = "contain.secondary_slaughter"


def _class_name(module: object) -> str:
    return type(module).__name__


class UnreachableContainRule(Rule):
    """An object declaring more than one contain module, on an engine with the `multi-contain`
    patch, where one of the earlier contains is not a slaughter contain. The engine keeps only
    the last contain declared and the patch lets an earlier one take riders only if it is a
    `SlaughterHordeContain` (or `CitadelSlaughterHordeContain`), so a unit ordered to enter the
    object is never offered any other earlier contain. When the slaughter contain is the last one,
    the usual cause is declaration order: the contain that keeps its passengers (a
    `TunnelContain`, a `TransportContain`, a garrison) has to come last.

    WARNING, not an error: the object loads and plays, and the module may still be filled by
    something that is not an enter order (Edain's Gandalf carries a hobbit in a transport that
    sits ahead of his ring pickup). Reordering also moves which contain everything else -
    exiting, evacuating, death - goes through, so it is a judgement call, not a mechanical fix.

    Two things the patch does that this rule does not check: hordes and horde members always use
    the last contain, so a slaughter contain meant for battalions should be the last one itself;
    and a rider both contains accept goes to the last one."""

    code = "unreachable-contain"

    def check(self, game: Game) -> Iterator[Diagnostic]:
        if not active().limit(_SECONDARY_SLAUGHTER):
            return
        default_tags = default_module_tags(game)
        for obj in walk_objects(game, Object):
            # Without the parent the inherited modules are unknown; skip rather than guess.
            if isinstance(obj, ChildObject) and obj.parent_name and obj.parent is None:
                continue
            modules = resolved_module_tags(obj, default_tags).values()
            contains = [module for module in modules if isinstance(module, ContainBehavior)]
            if len(contains) < 2:
                continue
            stored = contains[-1]
            for module in contains[:-1]:
                if isinstance(module, SlaughterHordeContain):
                    continue
                yield self._diagnostic(obj, module, stored)

    def _diagnostic(self, obj: IniObject, module, stored) -> Diagnostic:
        name, tag = _class_name(module), module.tag
        stored_name = _class_name(stored)
        if isinstance(stored, SlaughterHordeContain):
            fix = (
                f"declaring {name} {tag} after {stored_name} {stored.tag} would make the "
                f"slaughter contain the reachable earlier one"
            )
        else:
            fix = "only one contain that keeps its passengers can take enter orders"
        return Diagnostic(
            code=self.code,
            message=(
                f"Object {obj.name!r}: a unit ordered to enter is never offered {name} {tag}. "
                f"The engine asks the last contain declared ({stored_name} {stored.tag}), and "
                f"multi-contain adds an earlier one only when it is a slaughter contain; {fix}."
            ),
            span=getattr(module, "span", None) or obj.span,
            severity=Severity.WARNING,
            extra={
                "object": obj.name,
                "module": name,
                "tag": tag,
                "stored_module": stored_name,
                "stored_tag": stored.tag,
            },
        )
