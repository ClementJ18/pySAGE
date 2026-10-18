"""The plugin's run-wide options: `--shard` slicing a suite between processes, `--headless`."""

import pytest

from sage_test import plugin

pytest_plugins = ["pytester"]

#: Three scopes - two classes and a module of bare functions - with two tests in each.
_SUITE = """
class TestFirst:
    def test_a(self): pass
    def test_b(self): pass

class TestSecond:
    def test_a(self): pass
    def test_b(self): pass

def test_bare_a(): pass
def test_bare_b(): pass
"""


#: One class run once per unit, the way a scenario test covers several units: a class-scoped
#: fixture with `params`, and two tests on each.
_UNITS = """
import pytest

@pytest.fixture(scope="class", params=["a", "b", "c", "d"])
def unit(request):
    return request.param

class TestUnit:
    def test_one(self, unit): pass
    def test_two(self, unit): pass
"""

#: A class whose tests are parametrized per function - all in one game, so never split.
_CASES = """
import pytest

class TestCases:
    @pytest.mark.parametrize("case", [1, 2, 3])
    def test_case(self, case): pass
"""


def _ran(pytester: pytest.Pytester, *args: str) -> set[str]:
    pytester.makepyfile(test_suite=_SUITE)
    result = pytester.runpytest("-p", "sage_test.plugin", "-q", "--co", *args)
    return {line.strip() for line in result.outlines if "::" in line}


class TestShard:
    def test_the_shards_partition_the_suite(self, pytester: pytest.Pytester):
        whole = _ran(pytester)
        shards = [_ran(pytester, "--shard", f"{k}/3") for k in (1, 2, 3)]

        assert len(whole) == 6
        assert set().union(*shards) == whole
        assert sum(len(shard) for shard in shards) == len(whole)

    def test_a_class_is_never_split(self, pytester: pytest.Pytester):
        for k in (1, 2):
            ran = _ran(pytester, "--shard", f"{k}/2")
            for scope in ("TestFirst", "TestSecond"):
                in_scope = {test for test in ran if f"::{scope}::" in test}
                assert len(in_scope) in (0, 2)

    def test_more_shards_than_scopes_leaves_some_empty(self, pytester: pytest.Pytester):
        assert _ran(pytester, "--shard", "4/4") == set()

    def test_a_class_scoped_parameter_spreads_its_values_across_shards(
        self, pytester: pytest.Pytester
    ):
        """One scenario per unit through a parametrized class fixture: each unit is a game of its
        own, so the units are what the shards share out - never the tests of one unit."""
        pytester.makepyfile(test_units=_UNITS)
        ran = []
        for k in (1, 2, 3, 4):
            result = pytester.runpytest("-p", "sage_test.plugin", "-q", "--co", "--shard", f"{k}/4")
            ran.append({line.strip() for line in result.outlines if "::" in line})

        assert all(len(shard) == 2 for shard in ran)  # one unit, both its tests, per shard
        for shard in ran:
            assert len({test.split("[")[1] for test in shard}) == 1

    def test_a_function_scoped_parameter_never_splits_a_class(self, pytester: pytest.Pytester):
        pytester.makepyfile(test_cases=_CASES)
        sizes = []
        for k in (1, 2):
            result = pytester.runpytest("-p", "sage_test.plugin", "-q", "--co", "--shard", f"{k}/2")
            sizes.append(sum("::" in line for line in result.outlines))
        assert sorted(sizes) == [0, 3]

    @pytest.mark.parametrize("given", ["3", "0/2", "3/2", "a/b"])
    def test_a_malformed_shard_is_a_usage_error(self, pytester: pytest.Pytester, given: str):
        pytester.makepyfile(test_suite=_SUITE)
        result = pytester.runpytest("-p", "sage_test.plugin", "--shard", given)
        assert result.ret == pytest.ExitCode.USAGE_ERROR


class _Config:
    def __init__(self, **options):
        self.options = {"--shard": None, "--headless": False, **options}

    def getoption(self, name):
        return self.options[name]


class TestWorkerId:
    def test_alone_it_is_master(self, monkeypatch):
        monkeypatch.delenv("PYTEST_XDIST_WORKER", raising=False)
        assert plugin._worker_id(_Config()) == "master"
        assert plugin._worker_id(_Config(**{"--shard": "1/1"})) == "master"

    def test_a_shard_names_itself(self):
        assert plugin._worker_id(_Config(**{"--shard": "2/3"})) == "shard2"

    def test_an_xdist_worker_names_itself(self, monkeypatch):
        monkeypatch.setenv("PYTEST_XDIST_WORKER", "gw1")
        assert plugin._worker_id(_Config()) == "gw1"


def test_headless_stops_drawing_and_keeps_the_frame_cap():
    assert plugin._engine_args(_Config()) == ()
    # `-renderEvery 0`, not `-headless`: that one uncaps the loop as well.
    assert plugin._engine_args(_Config(**{"--headless": True})) == ("-renderEvery", "0")
