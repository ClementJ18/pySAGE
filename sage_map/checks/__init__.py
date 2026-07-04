"""Standalone map-check architecture: rule-runner and terrain helpers.

Game- and mod-agnostic: findings are ordinary `sage_ini` `Diagnostic`s, so map checks ride the
same severity/code/reporting primitives as the rest of the repo's linting. This package defines
how a sequence of rules runs over a parsed `Map` (`lint_map`, `LintConfig`) and shared terrain
geometry helpers (`height_utils`). The actual rules are mod conventions and live elsewhere;
`sage_edain.map_checks` is the Edain rule set (with its CLI: `python -m sage_edain.map_checks`).
"""

from .height_utils import get_flatness_percentage, is_flat_at_position
from .linter import UNSTAMPED_SPAN, LintConfig, lint_map

__all__ = [
    "UNSTAMPED_SPAN",
    "LintConfig",
    "get_flatness_percentage",
    "is_flat_at_position",
    "lint_map",
]
