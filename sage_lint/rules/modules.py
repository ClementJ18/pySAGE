"""Rules: a child block whose type the schema does not recognize, and a module header naming a
class the schema models but the game's module factory does not register.

A `Behavior`/`Draw`/`Body`/... module names its class in its header (`Behavior =
PhysicsBehavior Tag`); a named sub-block is typed by its own name. When that type is not in
the model `REGISTRY` the builder cannot type it, so it is parked raw in the parent's
`_extras` and would otherwise vanish silently - hiding both genuine typos (`PhysicsBeavior`
for `PhysicsBehavior`) and still-unmodeled block kinds. This rule surfaces every one of them
for manual triage.
"""

from collections.abc import Iterator

from sage_ini.model.game import Game
from sage_ini.model.objects import REGISTRY, Behavior, Draw, Module, classify_subblock
from sage_ini.parser.ast import Block
from sage_ini.parser.diagnostics import Diagnostic, Severity
from sage_ini.suggest import suggestion_hint
from sage_ini.walk import walk_objects
from sage_lint.rules.base import Rule


class UnrecognizedBlockRule(Rule):
    """A sub-block (`Behavior`, `Draw`, a named block, ...) whose type the model does not
    declare: an engine module the linter cannot type - a misspelled class name, or a kind the
    schema does not cover yet. Raised as an ERROR so none slips by unnoticed.

    Exhaustive by design: an incomplete schema leaves many valid blocks unmodeled, so this
    fires across a large share of any real game. Like the `unknown-attribute` coverage signal
    (untyped fields, also ERROR) it is therefore excluded from the corpus flood gate; silence
    it with `ignore = ["unrecognized-block"]` once the backlog is triaged."""

    code = "unrecognized-block"

    def check(self, game: Game) -> Iterator[Diagnostic]:
        known = REGISTRY.keys()
        for obj in walk_objects(game):
            for child in obj._extras:
                if not isinstance(child, Block):
                    continue
                type_name, _ = classify_subblock(child)
                hint, suggestion = suggestion_hint(type_name, known)
                yield Diagnostic(
                    code=self.code,
                    message=(
                        f"{type_name!r} is not a recognized module or block type; "
                        f"the linter cannot model it.{hint}"
                    ),
                    span=child.span,
                    severity=Severity.ERROR,
                    extra={
                        "type_name": type_name,
                        "header": child.name,
                        "suggestion": suggestion,
                    },
                )


# Unregistered classes with one registered module that does their job in RotWK. Name similarity
# alone would pick `W3DSailModelDraw` for `W3DModelDraw`.
_REGISTERED_EQUIVALENT = {"W3DModelDraw": "W3DScriptedModelDraw"}


def _registered_alternatives(cls: type[Module]) -> list[str]:
    """Registered module names to suggest instead of `cls`: its known equivalent, else its
    registered subclasses (a C++ base names the family to pick from), else the registered
    modules of its slot."""
    if cls.__name__ in _REGISTERED_EQUIVALENT:
        return [_REGISTERED_EQUIVALENT[cls.__name__]]
    descendants = [c.__name__ for c in _all_subclasses(cls) if c.factory_registered]
    if descendants:
        return descendants
    slot = next((base for base in (Draw, Behavior) if issubclass(cls, base)), Module)
    return [c.__name__ for c in _all_subclasses(slot) if c.factory_registered]


def _all_subclasses(cls: type[Module]) -> list[type[Module]]:
    found: list[type[Module]] = []
    for sub in cls.__subclasses__():
        found.append(sub)
        found.extend(_all_subclasses(sub))
    return found


class UnregisteredModuleRule(Rule):
    """A module header naming a class the schema models but RotWK's module factory does not
    register (`Draw = W3DModelDraw`, `Behavior = DieBehavior`): a C++ base class or a Generals
    module. The parser accepts it, then the factory returns NULL and the game crashes while
    loading the INI, with no error dialog."""

    code = "unregistered-module"

    def check(self, game: Game) -> Iterator[Diagnostic]:
        for module in walk_objects(game, Module):
            if not isinstance(module, Module) or module.factory_registered:
                continue
            cls = type(module)
            hint, suggestion = suggestion_hint(cls.__name__, _registered_alternatives(cls), 0.0)
            yield Diagnostic(
                code=self.code,
                message=(
                    f"{cls.__name__!r} is not a module the game registers; naming it crashes "
                    f"the game on load.{hint}"
                ),
                span=module.span,
                severity=Severity.ERROR,
                extra={"type_name": cls.__name__, "header": module.name, "suggestion": suggestion},
            )
