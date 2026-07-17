"""Rule-runner for standalone map checks: no game data, just the parsed `Map`.

Findings are ordinary `sage_ini` `Diagnostic`s, so map checks carry the same severity/code/span
primitives as every other linter in the repo. A rule is any callable taking the parsed map and a
`LintConfig` and returning `Diagnostic`s; the runner stamps every finding with the map file's
span (a binary map has no lines, so the span is `path:1`), turns an exception escaping a rule
into a `rule-error` finding, and applies the config's code exclusions. Rule sets live with the
mod-specific packages: `sage_mods.edain.map_checks` holds the Edain mapping conventions.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import TYPE_CHECKING

from sage_ini.parser.diagnostics import Diagnostic, Diagnostics
from sage_ini.parser.location import Span

if TYPE_CHECKING:
    from ..map import Map

# Rules build findings against this placeholder; the runner stamps the real file over it.
UNSTAMPED_SPAN = Span("<map>", 1, 1)


@dataclass
class LintConfig:
    """Base configuration: which codes to drop. Rule sets subclass this with their knobs."""

    exclude_codes: list[str] = field(default_factory=list)


def lint_map[C: LintConfig](
    map_obj: "Map",
    rules: Sequence[Callable[["Map", C], list[Diagnostic]]],
    config: C,
    path: str | Path = "<map>",
) -> Diagnostics:
    span = Span(str(path), 1, 1)
    diagnostics = Diagnostics()
    for rule in rules:
        try:
            found = rule(map_obj, config)
        except Exception as exc:  # noqa: BLE001 - a crashing rule becomes a finding, not an abort
            name = getattr(rule, "__name__", repr(rule))
            diagnostics.add("rule-error", f"{name} failed: {exc}", span)
            continue
        diagnostics.items.extend(replace(d, span=span) for d in found)

    if config.exclude_codes:
        exclude_set = set(config.exclude_codes)
        diagnostics.items = [d for d in diagnostics.items if d.code not in exclude_set]

    return diagnostics
