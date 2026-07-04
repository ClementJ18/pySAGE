"""Tests for the single-file briefing (`sage_ini.brief`) and its `brief` CLI command."""

from sage_ini.__main__ import main
from sage_ini.brief import build_brief
from sage_ini.modindex import ModIndex


def _mod(tmp_path):
    # a.ini includes b.inc; the macro and the Upgrade it references live in the fragment.
    (tmp_path / "a.ini").write_text(
        '#include "b.inc"\n'
        "Object Tower\n    BuildCost = TOWER_COST\nEnd\n"
        "CommandButton Command_Foo\n    Object = Tower\n    Upgrade = Upgrade_Foo\nEnd\n",
        encoding="utf-8",
    )
    (tmp_path / "b.inc").write_text(
        "#define TOWER_COST 100\nUpgrade Upgrade_Foo\nEnd\n",
        encoding="utf-8",
    )
    return tmp_path


class TestBuildBrief:
    def _brief(self, tmp_path, focus=None):
        root = _mod(tmp_path)
        return build_brief(ModIndex(root), root / "a.ini", focus=focus)

    def test_defines_only_this_file(self, tmp_path):
        names = {d.name for d in self._brief(tmp_path).defines}
        # Tower and Command_Foo are declared here; Upgrade_Foo lives in the included fragment.
        assert names == {"Tower", "Command_Foo"}

    def test_resolved_references_carry_sites(self, tmp_path):
        brief = self._brief(tmp_path)
        [source] = brief.references  # only Command_Foo references anything
        assert source.name == "Command_Foo"
        targets = {(t.name, t.table) for t in source.targets}
        assert targets == {("Tower", "objects"), ("Upgrade_Foo", "upgrades")}
        # The Upgrade is defined in the included fragment; its site points there.
        upgrade_site = next(t.site for t in source.targets if t.name == "Upgrade_Foo")
        assert "b.inc:" in upgrade_site

    def test_reference_table_aggregate(self, tmp_path):
        assert self._brief(tmp_path).ref_table_counts == {"objects": 1, "upgrades": 1}

    def test_includes_listed(self, tmp_path):
        assert [p.name for p in self._brief(tmp_path).includes] == ["b.inc"]

    def test_macros_used_with_origin(self, tmp_path):
        [macro] = self._brief(tmp_path).macros
        assert macro.name == "TOWER_COST" and macro.value == "100"
        assert macro.site is not None and "b.inc:" in macro.site

    def test_focus_narrows_defines_and_scopes_macros(self, tmp_path):
        # Command_Foo uses no macro; focusing on it drops the file-wide TOWER_COST.
        button = self._brief(tmp_path, focus="Command_Foo")
        assert [d.name for d in button.defines] == ["Command_Foo"]
        assert button.macros == []
        # Tower is the one that uses the macro.
        tower = self._brief(tmp_path, focus="Tower")
        assert [m.name for m in tower.macros] == ["TOWER_COST"]

    def test_focus_is_case_insensitive(self, tmp_path):
        defines = self._brief(tmp_path, focus="command_foo").defines
        assert [d.name for d in defines] == ["Command_Foo"]


class TestBriefCommand:
    def test_reports_file_summary(self, tmp_path, capsys):
        root = _mod(tmp_path)
        assert main(["brief", str(root), str(root / "a.ini")]) == 0
        out = capsys.readouterr().out
        assert "defines (2):" in out
        assert "-> Tower [objects]" in out
        assert "TOWER_COST = 100" in out

    def test_focus_argument(self, tmp_path, capsys):
        root = _mod(tmp_path)
        assert main(["brief", str(root), str(root / "a.ini"), "Command_Foo"]) == 0
        out = capsys.readouterr().out
        assert "[focus: Command_Foo]" in out
