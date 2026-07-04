"""Tests for sage_lint meta-analysis: faction stats, cost curves, table diffs."""

from sage_ini.model.game import Game
from sage_ini.parser.blockparser import parse
from sage_lint.analysis import cost_curve, diff_table, faction_stats


def _load(text: str) -> Game:
    game = Game()
    game.load_document(parse(text, file="t.ini").document)
    return game


_TWO_SIDES = (
    "Object MenSoldier\n    Side = Men\n    BuildCost = 100\nEnd\n"
    "Object MenKnight\n    Side = Men\n    BuildCost = 300\nEnd\n"
    "Object MenBanner\n    Side = Men\nEnd\n"  # no BuildCost
    "Object MordorOrc\n    Side = Mordor\n    BuildCost = 50\nEnd\n"
)


class TestFactionStats:
    def test_counts_objects_and_buildables_per_side(self):
        stats = faction_stats(_load(_TWO_SIDES))

        assert stats["Men"].objects == 3
        assert stats["Men"].buildable == 2
        assert stats["Men"].total_cost == 400
        assert stats["Men"].average_cost == 200.0
        assert stats["Mordor"].objects == 1
        assert stats["Mordor"].average_cost == 50.0

    def test_objects_without_a_side_group_under_none(self):
        stats = faction_stats(_load("Object Rock\n    BuildCost = 5\nEnd\n"))
        assert stats["<none>"].objects == 1

    def test_average_is_zero_when_no_object_is_priced(self):
        stats = faction_stats(_load("Object Tree\n    Side = Wild\nEnd\n"))
        assert stats["Wild"].buildable == 0
        assert stats["Wild"].average_cost == 0.0


class TestCostCurve:
    def test_orders_priced_objects_dearest_first(self):
        curve = cost_curve(_load(_TWO_SIDES))
        assert curve == [("MenKnight", 300), ("MenSoldier", 100), ("MordorOrc", 50)]

    def test_filters_by_side(self):
        curve = cost_curve(_load(_TWO_SIDES), side="Mordor")
        assert curve == [("MordorOrc", 50)]


class TestDiffTable:
    def test_reports_new_deleted_and_modified(self):
        base = _load(
            "Object Kept\n    BuildCost = 1\nEnd\n"
            "Object Changed\n    BuildCost = 1\nEnd\n"
            "Object Gone\n    BuildCost = 1\nEnd\n"
        )
        mod = _load(
            "Object Kept\n    BuildCost = 1\nEnd\n"
            "Object Changed\n    BuildCost = 2\nEnd\n"
            "Object Added\n    BuildCost = 1\nEnd\n"
        )
        diff = diff_table(base, mod, "objects")

        assert diff.new == ["Added"]
        assert diff.deleted == ["Gone"]
        assert diff.modified == ["Changed"]

    def test_detects_a_change_in_a_nested_module(self):
        base = _load(
            "Object Hero\n    Behavior = UpgradeBehavior Tag\n"
            "        TriggeredBy = Up_A\n    End\nEnd\n"
        )
        mod = _load(
            "Object Hero\n    Behavior = UpgradeBehavior Tag\n"
            "        TriggeredBy = Up_B\n    End\nEnd\n"
        )
        assert diff_table(base, mod, "objects").modified == ["Hero"]

    def test_identical_tables_have_no_differences(self):
        text = "Object Same\n    BuildCost = 10\nEnd\n"
        diff = diff_table(_load(text), _load(text), "objects")
        assert not (diff.new or diff.deleted or diff.modified)
