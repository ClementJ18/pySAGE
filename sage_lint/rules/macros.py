"""Rule: an arithmetic operand naming a macro that nothing defines.

Macros are referenced by bare name, so most references are indistinguishable from
enum tokens or free text and are left alone. The exception is an arithmetic operand
(inside `#MULTIPLY( X 1.1 )` the engine requires a number), so an operand that is
neither a number nor a defined macro - but looks like a macro name - is an undefined
reference. Caught in both field values and `#define` bodies.
"""

import re
from collections.abc import Iterator

from sage_ini.model.game import Game
from sage_ini.model.types import OPERATIONS, _split_operands, to_number
from sage_ini.parser.diagnostics import Diagnostic, Severity
from sage_ini.parser.location import Span
from sage_ini.suggest import suggestion_hint
from sage_ini.walk import walk_objects
from sage_lint.rules.base import Rule

# A macro name is an identifier; operands that don't match (a malformed number like
# `1.0,`) are left to the conversion pass rather than mislabelled as a macro.
_MACRO_NAME = re.compile(r"[A-Za-z_]\w*\Z")


def _is_number(text: str) -> bool:
    try:
        to_number(text)
    except (ValueError, IndexError):
        return False
    return True


def _undefined_operands(game: Game, text: str) -> Iterator[str]:
    """Macro-named arithmetic operands in `text` that `game.macros` lacks. Only the
    operands of a `#OP( ... )` form are inspected (recursing into nested expressions),
    so a yielded token sits where the syntax requires a number."""
    text = str(text).strip()
    if text.endswith("%") and text != "%":
        text = text[:-1].strip()
    if not (text.startswith("#") and "(" in text):
        return  # not an arithmetic form: operand positions are not guaranteed
    name = text[1 : text.index("(")].strip()
    if name not in OPERATIONS:
        return
    inner = text[text.index("(") + 1 : text.rindex(")")]
    for operand in _split_operands(inner):
        token = operand.strip().rstrip("%").strip()
        if token.startswith("#"):
            yield from _undefined_operands(game, operand)
        elif not _is_number(token) and not game.has_macro(token) and _MACRO_NAME.match(token):
            yield token


class UndefinedMacroRule(Rule):
    """An arithmetic operand referencing a `#define` macro that does not exist. The
    dedicated message names the culprit, and a macro defined in terms of another
    undefined macro is caught even when nothing reads it yet."""

    code = "undefined-macro"

    def check(self, game: Game) -> Iterator[Diagnostic]:
        for name, value in game.macros.items():
            for token in _undefined_operands(game, value):
                hint, suggestion = suggestion_hint(token, game.macros)
                yield Diagnostic(
                    code=self.code,
                    message=f"#define {name} references undefined macro {token!r}.{hint}",
                    span=Span("<macros>", 1, 1),
                    severity=Severity.WARNING,
                    extra={"macro": token, "via_macro": name, "suggestion": suggestion},
                )
        for obj in walk_objects(game):
            for key, value in obj.fields.items():
                for entry in value if isinstance(value, list) else [value]:
                    if not isinstance(entry, str):
                        continue
                    for token in _undefined_operands(game, entry):
                        hint, suggestion = suggestion_hint(token, game.macros)
                        yield Diagnostic(
                            code=self.code,
                            message=(
                                f"{type(obj).__name__}.{key} references "
                                f"undefined macro {token!r}.{hint}"
                            ),
                            span=obj._field_spans.get(key, obj.span),
                            severity=Severity.WARNING,
                            extra={
                                "macro": token,
                                "type": type(obj).__name__,
                                "key": key,
                                "suggestion": suggestion,
                            },
                        )
