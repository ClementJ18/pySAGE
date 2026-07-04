"""Tests for the `python -m sage_ini` command line (stats / lint / xref)."""

import json

import pytest

from sage_ini.__main__ import main


class TestLintCommand:
    def test_clean_file_exits_zero(self, tmp_path, capsys):
        path = tmp_path / "ok.ini"
        path.write_text("Object Foo\n    BuildCost = 100\nEnd\n", encoding="utf-8")
        assert main(["lint", str(path)]) == 0

    def test_conversion_error_exits_one(self, tmp_path, capsys):
        path = tmp_path / "bad.ini"
        path.write_text("Object Foo\n    BuildCost = notanumber\nEnd\n", encoding="utf-8")

        assert main(["lint", str(path)]) == 1
        assert "conversion-error" in capsys.readouterr().out

    def test_missing_path_errors(self, tmp_path, capsys):
        with pytest.raises(SystemExit):
            main(["lint", str(tmp_path / "nope.ini")])


class TestXrefCommand:
    def _folder(self, tmp_path):
        (tmp_path / "a.ini").write_text(
            "Upgrade Upgrade_Foo\nEnd\nCommandButton Command_Bar\n    Upgrade = Upgrade_Foo\nEnd\n",
            encoding="utf-8",
        )
        return tmp_path

    def test_reports_both_directions(self, tmp_path, capsys):
        root = self._folder(tmp_path)
        assert main(["xref", str(root), "Upgrade_Foo"]) == 0

        out = capsys.readouterr().out
        assert "Upgrade_Foo [upgrades]" in out
        assert "Command_Bar [commandbuttons]" in out

    def test_unknown_name_exits_one(self, tmp_path, capsys):
        root = self._folder(tmp_path)
        assert main(["xref", str(root), "DoesNotExist"]) == 1
        assert "no definition named" in capsys.readouterr().out


class TestJsonOutput:
    """`--json` on the query commands emits machine-readable reports for agents."""

    def _folder(self, tmp_path):
        (tmp_path / "a.ini").write_text(
            "#define BASE_COST 100\n"
            "Upgrade Upgrade_Foo\nEnd\n"
            "CommandButton Command_Bar\n    Upgrade = Upgrade_Foo\nEnd\n",
            encoding="utf-8",
        )
        return tmp_path

    def test_lint_json_reports_diagnostics_and_summary(self, tmp_path, capsys):
        path = tmp_path / "bad.ini"
        path.write_text("Object Foo\n    BuildCost = notanumber\nEnd\n", encoding="utf-8")

        assert main(["lint", "--json", str(path)]) == 1
        payload = json.loads(capsys.readouterr().out)
        assert payload["summary"]["errors"] >= 1
        diag = payload["diagnostics"][0]
        assert set(diag) == {"code", "severity", "message", "file", "line_start", "line_end"}

    def test_lint_json_clean_file(self, tmp_path, capsys):
        path = tmp_path / "ok.ini"
        path.write_text("Object Foo\n    BuildCost = 100\nEnd\n", encoding="utf-8")

        assert main(["lint", "--json", str(path)]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload == {"diagnostics": [], "summary": {"errors": 0, "others": 0}}

    def test_xref_json_reports_both_directions(self, tmp_path, capsys):
        root = self._folder(tmp_path)

        assert main(["xref", "--json", str(root), "Upgrade_Foo"]) == 0
        payload = json.loads(capsys.readouterr().out)
        (match,) = payload["matches"]
        assert match["table"] == "upgrades"
        assert [s["name"] for s in match["referenced_by"]] == ["Command_Bar"]
        assert match["referenced_by"][0]["line"] == 4

    def test_xref_json_unknown_name(self, tmp_path, capsys):
        root = self._folder(tmp_path)
        assert main(["xref", "--json", str(root), "Nope"]) == 1
        assert json.loads(capsys.readouterr().out) == {"name": "Nope", "matches": []}

    def test_resolve_json_definition_and_macro(self, tmp_path, capsys):
        root = self._folder(tmp_path)

        assert main(["resolve", "--json", str(root), "Upgrade_Foo"]) == 0
        payload = json.loads(capsys.readouterr().out)
        (definition,) = payload["definitions"]
        assert definition["table"] == "upgrades"
        assert definition["line"] == 2

        assert main(["resolve", "--json", str(root), "BASE_COST"]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["macro"]["value"] == "100"

    def test_resolve_json_miss_suggests(self, tmp_path, capsys):
        root = self._folder(tmp_path)
        assert main(["resolve", "--json", str(root), "Upgrade_Fooo"]) == 1
        payload = json.loads(capsys.readouterr().out)
        assert payload["definitions"] == [] and payload["macro"] is None
        assert "Upgrade_Foo" in payload["suggestions"]

    def test_brief_json_shape(self, tmp_path, capsys):
        root = self._folder(tmp_path)

        assert main(["brief", "--json", str(root), str(root / "a.ini")]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert {d["name"] for d in payload["defines"]} == {"Upgrade_Foo", "Command_Bar"}
        (source,) = payload["references"]
        assert source["name"] == "Command_Bar"
        assert source["targets"][0]["name"] == "Upgrade_Foo"
        assert payload["ref_table_counts"] == {"upgrades": 1}

    def test_diff_json_reports_changes(self, tmp_path, capsys):
        old = tmp_path / "old"
        new = tmp_path / "new"
        old.mkdir()
        new.mkdir()
        (old / "a.ini").write_text("Object Foo\n    BuildCost = 100\nEnd\n", encoding="utf-8")
        (new / "a.ini").write_text(
            "Object Foo\n    BuildCost = 150\nEnd\nObject Bar\nEnd\n", encoding="utf-8"
        )

        assert main(["diff", "--json", str(old), str(new)]) == 0
        payload = json.loads(capsys.readouterr().out)
        (table,) = payload["tables"]
        assert table["key"] == "objects"
        assert table["added"] == ["Bar"]
        (changed,) = table["changed"]
        assert changed["name"] == "Foo"
        assert changed["diff"]["fields"] == [{"key": "BuildCost", "old": "100", "new": "150"}]
