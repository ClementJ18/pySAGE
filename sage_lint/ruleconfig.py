"""Process-global rule options a `Rule` reads but the `Game` it runs over does not carry.

A `Rule.check` only receives the assembled `Game`, yet a few rules need project-level
choices from `.sagelint` that are not facts about the game: the extra `sentinels` a
reference may name without being "dangling", and the kinds `always_referenced` an
unused-definition check must never flag. Rather than thread these through every lint
entry point, they live here as opt-in process state the CLI sets for the duration of a
run (the same pattern `sage_ini.suggest` uses for its enable flag), and the rules read.

Both default to empty, so a plain run behaves exactly as before. Names are matched
case-insensitively, since SAGE is.
"""

import contextlib

__all__ = ["sentinels", "always_referenced", "rule_options", "set_options"]

# Extra "intentionally nothing" tokens a reference field may name without being reported as
# dangling (e.g. `NoSound`). `None`/`NONE`/empty are always treated as sentinels regardless,
# so they are not stored here. Lower-cased.
_SENTINELS: frozenset[str] = frozenset()
# Definition kinds (block type names, e.g. `PlayerAIType`) the unused-definition rule never
# flags, for kinds the engine reaches in ways the ini reference graph cannot see. Lower-cased.
_ALWAYS_REFERENCED: frozenset[str] = frozenset()


def sentinels() -> frozenset[str]:
    """The configured extra sentinel tokens, lower-cased (`None`/empty are always-implicit and
    not included here)."""
    return _SENTINELS


def always_referenced() -> frozenset[str]:
    """The configured always-referenced definition kinds, lower-cased."""
    return _ALWAYS_REFERENCED


def set_options(
    sentinels: list[str] | None = None, always_referenced: list[str] | None = None
) -> tuple[frozenset[str], frozenset[str]]:
    """Set the rule options for the run, returning the previous `(sentinels, always_referenced)`
    so a caller can restore them. A `None` argument leaves that option unchanged."""
    global _SENTINELS, _ALWAYS_REFERENCED
    previous = (_SENTINELS, _ALWAYS_REFERENCED)
    if sentinels is not None:
        _SENTINELS = frozenset(name.lower() for name in sentinels)
    if always_referenced is not None:
        _ALWAYS_REFERENCED = frozenset(name.lower() for name in always_referenced)
    return previous


@contextlib.contextmanager
def rule_options(sentinels: list[str] | None = None, always_referenced: list[str] | None = None):
    """Apply rule options within this block, restoring the prior values on exit."""
    previous = set_options(sentinels, always_referenced)
    try:
        yield
    finally:
        set_options(list(previous[0]), list(previous[1]))
