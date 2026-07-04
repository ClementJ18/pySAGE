"""Tests for the per-mod resolution index (`sage_ini.modindex`) and its CLI commands."""

from sage_ini.__main__ import main
from sage_ini.modindex import ModIndex


def _mod(tmp_path):
    # a.ini includes b.inc; the Upgrade and macro live in the included fragment.
    (tmp_path / "a.ini").write_text(
        'Object Tower\n    BuildCost = 100\nEnd\n#include "b.inc"\n',
        encoding="utf-8",
    )
    (tmp_path / "b.inc").write_text(
        "#define TOWER_COST 100\nUpgrade Upgrade_Foo\nEnd\n",
        encoding="utf-8",
    )
    return tmp_path


class TestModIndex:
    def test_resolve_locates_a_definition(self, tmp_path):
        index = ModIndex(_mod(tmp_path))
        [definition] = index.resolve("Upgrade_Foo")
        assert definition.table == "upgrades"
        # The definition lives in the included fragment; the span points at the physical file.
        assert definition.span.file.endswith("b.inc")

    def test_resolve_is_case_insensitive(self, tmp_path):
        index = ModIndex(_mod(tmp_path))
        [definition] = index.resolve("upgrade_foo")
        assert definition.name == "Upgrade_Foo"

    def test_resolve_unknown_is_empty(self, tmp_path):
        assert ModIndex(_mod(tmp_path)).resolve("Nope") == []

    def test_macro_carries_value_and_site(self, tmp_path):
        macro = ModIndex(_mod(tmp_path)).macro("TOWER_COST")
        assert macro is not None
        assert macro.value == "100"
        assert macro.span is not None and macro.span.file.endswith("b.inc")

    def test_include_graph_both_directions(self, tmp_path):
        root = _mod(tmp_path)
        index = ModIndex(root)
        assert [p.name for p in index.includes(root / "a.ini")] == ["b.inc"]
        assert [p.name for p in index.included_by(root / "b.inc")] == ["a.ini"]


class TestResolveCommand:
    def test_reports_definition_site(self, tmp_path, capsys):
        assert main(["resolve", str(_mod(tmp_path)), "Upgrade_Foo"]) == 0
        out = capsys.readouterr().out
        assert "Upgrade_Foo [upgrades]" in out and "b.inc:" in out

    def test_reports_macro(self, tmp_path, capsys):
        assert main(["resolve", str(_mod(tmp_path)), "TOWER_COST"]) == 0
        assert "#define TOWER_COST = 100" in capsys.readouterr().out

    def test_unknown_exits_one(self, tmp_path, capsys):
        assert main(["resolve", str(_mod(tmp_path)), "Nope"]) == 1
        assert "no definition or macro" in capsys.readouterr().out


class TestIncludesCommand:
    def test_lists_both_directions(self, tmp_path, capsys):
        root = _mod(tmp_path)
        assert main(["includes", str(root), str(root / "a.ini")]) == 0
        out = capsys.readouterr().out
        assert "-> b.inc" in out
        assert main(["includes", str(root), str(root / "b.inc")]) == 0
        assert "<- a.ini" in capsys.readouterr().out
