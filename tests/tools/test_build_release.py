"""Which specs a release build picks up. The mod overlays are opt-in - a plain run ships the
engine-generic tools, and the Edain windows come along only when a filter names them - so this
guards the one rule that decides what a downloaded release contains.

Reads the repo's own spec files (no building, no game data), so it is core-suite."""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "tools"))

from build_release import OPTIONAL_DIRS, find_specs  # noqa: E402


def paths(filters: list[str]) -> list[str]:
    return [spec.relative_to(REPO_ROOT).as_posix() for spec in find_specs(filters)]


def test_a_plain_run_skips_the_mod_overlays():
    assert not [p for p in paths([]) if p.startswith(OPTIONAL_DIRS)]


def test_a_plain_run_still_takes_the_generic_specs():
    found = paths([])
    assert "sage_ini/sage-ini.spec" in found
    assert "sage_lint/sage-lint.spec" in found


def test_naming_the_overlay_builds_it():
    assert "sage_mods/edain/sage-edain-horde.spec" in paths(["edain"])


def test_a_filter_can_name_one_overlay_spec_alone():
    assert paths(["sage-edain-horde"]) == ["sage_mods/edain/sage-edain-horde.spec"]


def test_a_filter_that_reaches_nothing_finds_nothing():
    assert paths(["no-such-tool"]) == []


def test_every_spec_the_repo_has_is_reachable_by_filter():
    """The skip is a default, not a wall: filtering by the tree itself takes the lot."""
    everything = sorted(paths([]) + paths(list(OPTIONAL_DIRS)))
    assert everything == sorted(
        spec.relative_to(REPO_ROOT).as_posix() for spec in REPO_ROOT.glob("*/**/*.spec")
    )
