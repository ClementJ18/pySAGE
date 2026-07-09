"""Corpus noise check: a lint rule must not flood the base game (PLAN Step 3.2).

The base game is mostly valid, so a judgment rule that fires on a large fraction
of it is wrong - its premise is too broad - not a discovery of thousands of bugs.
This gate assembles the `data/` base game, runs every registered rule, and holds
each rule's hit count under a plausibility ceiling, so a future rule that floods
fails here instead of drowning real findings in a report.

The exhaustive coverage signals are exempt: `unrecognized-block` (every unmodeled
sub-block) and `unknown-attribute` (every still-untyped field, ~58k of them), both
raised at ERROR to drive the schema toward 100% coverage. They are meant to fire
broadly until the schema catches up, so the ceiling applies only to the remaining
judgment rules - the ones whose firing signals an actual mistake.

Measured on the base game (25,375 objects), for the record:
    duplicate-definition       11      out-of-range                0
    undefined-macro             0      respawn-entry-order         0
    respawn-unknown-level      44      unknown-string-label      307
    repeated-field            247      unknown-attribute        58095
"""

from collections import Counter
from pathlib import Path

import pytest

from sage_ini.loader import load_game
from sage_ini.parser.diagnostics import Severity
from sage_lint.linter import lint_game
from sage_lint.rules.base import RULES

pytestmark = pytest.mark.full

DATA_DIR = Path(__file__).resolve().parents[2] / "data"

# A WARNING/ERROR rule firing on more than this fraction of the corpus is
# implausible for the (mostly valid) base game and means the rule is wrong.
FLOOD_FRACTION = 0.05

# Codes that are exhaustive coverage signals by design (one hit per unmodeled element), so
# the flood ceiling does not apply - they are meant to fire broadly until the schema catches
# up: `unrecognized-block` (every unmodeled sub-block) and `unknown-attribute` (every untyped
# field), both raised at ERROR by request to drive the schema toward 100% coverage.
_EXHAUSTIVE = {"unrecognized-block", "unknown-attribute"}


@pytest.fixture(scope="module")
def base_report():
    """The diagnostics and object count of the assembled base game, built once."""
    if not DATA_DIR.is_dir():
        pytest.skip("base game corpus (data/) not present")
    loaded = load_game(DATA_DIR)
    object_count = sum(len(table) for table in loaded.game.tables.values())
    return list(lint_game(loaded)), object_count


def test_no_rule_floods_the_base_game(base_report):
    diagnostics, object_count = base_report
    ceiling = int(object_count * FLOOD_FRACTION)

    rule_codes = {rule.code for rule in RULES} - _EXHAUSTIVE
    counts = Counter(
        d.code for d in diagnostics if d.code in rule_codes and d.severity is not Severity.INFO
    )
    flooded = {code: n for code, n in counts.items() if n > ceiling}
    assert not flooded, f"rule(s) flooded (> {ceiling} hits): {flooded}"


def test_clean_rules_stay_clean_on_the_base_game(base_report):
    """Rules that find nothing in the base game must keep finding nothing.

    out-of-range and undefined-macro are silent on the base data; a regression
    that makes either fire here is a false-positive leak, not a new discovery.
    """
    counts = Counter(d.code for d in base_report[0])
    assert counts["out-of-range"] == 0
    assert counts["undefined-macro"] == 0
    # The genuine same-file duplicates are few and stable (copy-paste slips that
    # ship in the base game); a sharp rise means the rule started over-reaching.
    assert counts["duplicate-definition"] <= 20
