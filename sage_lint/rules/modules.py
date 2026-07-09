"""Rule: a child block whose type the schema does not recognize.

A `Behavior`/`Draw`/`Body`/... module names its class in its header (`Behavior =
PhysicsBehavior Tag`); a named sub-block is typed by its own name. When that type is not in
the model `REGISTRY` the builder cannot type it, so it is parked raw in the parent's
`_extras` and would otherwise vanish silently - hiding both genuine typos (`PhysicsBeavior`
for `PhysicsBehavior`) and still-unmodeled block kinds. This rule surfaces every one of them
for manual triage.
"""

from collections.abc import Iterator

from sage_ini.model.game import Game
from sage_ini.model.objects import REGISTRY, classify_subblock
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
