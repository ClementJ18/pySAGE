"""Fuzzy "did you mean" suggestions. When a token fails to resolve against a closed set
of known names - a dangling cross-reference, an unknown attribute, a missing macro or
string - the likeliest intended name is often a near-spelling already in that set. These
helpers surface that guess in a diagnostic message.

Suggestions only: the match is probabilistic, so it is never used to drive an automated
rewrite (unlike the case fixes in `sage_lint.fixer`); it informs a human, who decides.

Computing a suggestion runs difflib over the *whole* candidate set, and on a large game the
objects table alone holds ~11k names - matching every unresolved token against it is the
dominant cost of a full `validate`/lint. So suggestions are **off by default** and produce no
hint; a caller that wants them (the `lint --suggest` flag, an interactive tool) turns them on
for the duration with `suggestions_enabled()`.
"""

import contextlib
import difflib

__all__ = [
    "did_you_mean",
    "closest_names",
    "suggestion_hint",
    "suggestions_enabled",
    "set_enabled",
]

# Ratio below which a candidate is too far to be a plausible typo of the given name.
# High on purpose: a weak match is worse than no suggestion, since it misleads.
_CUTOFF = 0.8

# A more forgiving ratio for an interactive search box: the user sees the matches and picks
# one, so recall (still finding the unit despite a sloppy spelling) beats the strictness a
# silent lint hint needs.
_SEARCH_CUTOFF = 0.6

# Whether suggestions are computed at all (see module docstring). Process-global and
# opt-in; toggled through `set_enabled`/`suggestions_enabled`.
_ENABLED = False


def set_enabled(value: bool) -> bool:
    """Turn suggestion computation on or off, returning the previous setting (so a caller can
    restore it)."""
    global _ENABLED
    previous = _ENABLED
    _ENABLED = bool(value)
    return previous


@contextlib.contextmanager
def suggestions_enabled(value: bool = True):
    """Compute suggestions within this block, restoring the prior setting on exit."""
    previous = set_enabled(value)
    try:
        yield
    finally:
        set_enabled(previous)


def did_you_mean(name: str, candidates, cutoff: float = _CUTOFF) -> str | None:
    """The single closest candidate to `name` above `cutoff`, or None when none is close
    enough (or suggestions are disabled). Matching ignores case (a pure case mismatch has its
    own diagnostic) but the candidate's own spelling is returned."""
    if not _ENABLED:
        return None
    if not isinstance(name, str) or not name:
        return None
    by_lower = {candidate.lower(): candidate for candidate in candidates}
    matches = difflib.get_close_matches(name.lower(), list(by_lower), n=1, cutoff=cutoff)
    return by_lower[matches[0]] if matches else None


def closest_names(
    name: str, candidates, *, count: int = 5, cutoff: float = _SEARCH_CUTOFF
) -> list[str]:
    """Up to `count` candidates most similar to `name`, closest first - the backing for an
    interactive "did you mean" search box. Unlike `did_you_mean`, this is **not** gated by the
    global enable flag (a user typing a search always wants matches) and returns several rather
    than one. Matching ignores case; each candidate's own spelling is returned, the first
    occurrence winning a case collision."""
    if not isinstance(name, str) or not name:
        return []
    by_lower: dict[str, str] = {}
    for candidate in candidates:
        by_lower.setdefault(candidate.lower(), candidate)
    matches = difflib.get_close_matches(name.lower(), list(by_lower), n=count, cutoff=cutoff)
    return [by_lower[match] for match in matches]


def suggestion_hint(name: str, candidates, cutoff: float = _CUTOFF) -> tuple[str, str | None]:
    """`(hint, suggestion)`: a `" Did you mean 'X'?"` clause to append to a message, plus
    the bare suggested name (for a diagnostic's `extra`). Both empty/None when nothing is
    close enough or suggestions are disabled."""
    suggestion = did_you_mean(name, candidates, cutoff)
    hint = f" Did you mean {suggestion!r}?" if suggestion else ""
    return hint, suggestion
