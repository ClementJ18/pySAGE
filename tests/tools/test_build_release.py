"""Which specs a release build picks up: every `*.spec` in the repo, and any subset a filter
names. This guards the one rule that decides what a downloaded release contains.

Reads the repo's own spec files (no building, no game data), so it is core-suite."""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "tools"))

from build_release import find_specs  # noqa: E402


def paths(filters: list[str]) -> list[str]:
    return [spec.relative_to(REPO_ROOT).as_posix() for spec in find_specs(filters)]


def test_a_plain_run_takes_every_spec_the_repo_has():
    assert sorted(paths([])) == sorted(
        spec.relative_to(REPO_ROOT).as_posix() for spec in REPO_ROOT.glob("*/**/*.spec")
    )


def test_a_plain_run_takes_the_generic_specs():
    found = paths([])
    assert "sage_ini/sage-ini.spec" in found
    assert "sage_lint/sage-lint.spec" in found


def test_a_filter_narrows_to_one_tree():
    assert paths(["sage_ini"]) == ["sage_ini/sage-ini.spec"]


def test_a_filter_can_name_one_spec_alone():
    assert paths(["sage-lint.spec"]) == ["sage_lint/sage-lint.spec"]


def test_a_filter_that_reaches_nothing_finds_nothing():
    assert paths(["no-such-tool"]) == []
