"""The map content diff (`sage_map.diff`): section building over hand-made sagemap dataclasses
(no `.map` file or corpus needed), the git commit plumbing over a real temp repo with the blob
parser stubbed, and the `diff-maps` CLI."""

import json
import subprocess

import sage_map.diff as map_diff  # noqa: E402
from sage_lint.cli import main  # noqa: E402
from sage_map import Map  # noqa: E402
from sage_map.assets.height_map import HeightMapData  # noqa: E402
from sage_map.assets.object_list import Object, ObjectsList  # noqa: E402
from sage_map.assets.player_scripts import (  # noqa: E402
    PlayerScriptsList,
    Script,
    ScriptArgument,
    ScriptDerived,
    ScriptList,
)
from sage_map.assets.player_scripts import ScriptArgumentType as AT  # noqa: E402
from sage_map.assets.sides_list import Player, SidesList  # noqa: E402
from sage_map.assets.teams import Team, Teams  # noqa: E402
from sage_map.assets.trigger_areas import TriggerArea, TriggerAreas  # noqa: E402
from sage_map.assets.world_info import WorldInfo  # noqa: E402
from sage_map.diff import (  # noqa: E402
    commit_map_changes,
    diff_commit_maps,
    diff_maps,
    diff_range_maps,
    format_map_diff,
    format_map_file_diffs,
    resolve_range,
)


def _prop(name, value):
    return {"name": name, "type": None, "value": value}


def _team(name, owner="", **props):
    all_props = {"teamName": name, "teamOwner": owner, **props}
    return Team(properties={k: _prop(k, v) for k, v in all_props.items()})


def _player(name, **props):
    all_props = {"playerName": name, **props}
    return Player(properties={k: _prop(k, v) for k, v in all_props.items()}, build_list_items={})


def _object(type_name, position=(0.0, 0.0, 0.0), angle=0.0, **props):
    return Object(
        version=1,
        position=position,
        angle=angle,
        road_type=0,
        type_name=type_name,
        properties={k: _prop(k, v) for k, v in props.items()},
        start_pos=0,
        end_pos=0,
    )


def _action(name, *args):
    return ScriptDerived(
        version=2,
        content_type=7,
        internal_name=(None, 0, name),  # sagemap records the property-key tuple; [2] is the name
        arguments=list(args),
        is_enabled=True,
        is_inverted=None,
        has_internal_name_version=2,
        has_is_enabled_version=3,
        has_is_inverted=False,
    )


def _arg(value):
    return ScriptArgument(type=AT.TEAM_NAME, int_value=0, float_value=0.0, string_value=value)


def _script(name, *, actions_if_true=(), is_active=True):
    script = Script(
        name=name,
        comment="",
        conditions_comment="",
        actions_comment="",
        is_active=is_active,
        deactivate_upon_success=False,
        active_in_easy=True,
        active_in_medium=True,
        active_in_hard=True,
        is_subroutine=False,
        version=2,
        start_pos=0,
        end_pos=0,
    )
    script.actions_if_true = list(actions_if_true)
    return script


def _heightmap(elevations, start_pos=0):
    return HeightMapData(
        version=5,
        width=len(elevations[0]),
        height=len(elevations),
        border_width=0,
        borders=[],
        area=len(elevations) * len(elevations[0]),
        min_height=0,
        max_height=100,
        elevations=elevations,
        start_pos=start_pos,
        end_pos=start_pos,
    )


def _map(
    *,
    teams=(),
    players=(),
    objects=(),
    trigger_areas=(),
    scripts=(),
    world_info=None,
    heightmap=None,
):
    m = Map()
    m.teams = Teams(version=5, teams=list(teams), start_pos=0, end_pos=0) if teams else None
    m.sides_list = SidesList(
        version=6, unknown1=False, players=list(players), start_pos=0, end_pos=0, teams=[]
    )
    m.objects_list = ObjectsList(version=1, object_list=list(objects), start_pos=0, end_pos=0)
    m.trigger_areas = (
        TriggerAreas(version=1, trigger_areas=list(trigger_areas), start_pos=0, end_pos=0)
        if trigger_areas
        else None
    )
    m.player_scripts_list = PlayerScriptsList(
        version=1,
        script_lists=[ScriptList(version=1, items=list(scripts), start_pos=0, end_pos=0)],
        start_pos=0,
        end_pos=0,
    )
    if world_info is not None:
        m.world_info = WorldInfo(
            version=1,
            properties={k: _prop(k, v) for k, v in world_info.items()},
            start_pos=0,
            end_pos=0,
        )
    m.height_map_data = heightmap
    return m


def _section(diff, title):
    return next((s for s in diff.sections if s.title == title), None)


class TestSections:
    def test_identical_maps_have_no_diff(self):
        make = lambda: _map(  # noqa: E731
            teams=[_team("Farmers", owner="PlyrCivilian")],
            objects=[_object("GondorFighter", position=(1.0, 2.0, 0.0))],
        )
        assert diff_maps(make(), make()).is_empty()

    def test_settings_change(self):
        old = _map(world_info={"weather": 0, "compression": 1})
        new = _map(world_info={"weather": 2, "compression": 1})
        section = _section(diff_maps(old, new), "settings")
        assert [entry.label for entry in section.changed] == ["weather: 0 -> 2"]

    def test_player_added_and_property_change(self):
        old = _map(players=[_player("PlyrCreeps", playerFaction="FactionCreeps")])
        new = _map(
            players=[_player("PlyrCreeps", playerFaction="FactionWild"), _player("PlyrHuman")]
        )
        section = _section(diff_maps(old, new), "players")
        assert section.added == ["PlyrHuman"]
        entry = section.changed[0]
        assert entry.label == "PlyrCreeps"
        assert "playerFaction: FactionCreeps -> FactionWild" in entry.details

    def test_team_keyed_by_owner_and_diffed(self):
        old = _map(teams=[_team("Farmers", owner="PlyrCivilian", teamMaxInstances=1)])
        new = _map(teams=[_team("Farmers", owner="PlyrCivilian", teamMaxInstances=3)])
        section = _section(diff_maps(old, new), "teams")
        entry = section.changed[0]
        assert entry.label == "PlyrCivilian/Farmers"
        assert entry.details == ["teamMaxInstances: 1 -> 3"]

    def test_unnamed_objects_group_by_type_with_counts(self):
        old = _map(objects=[_object("RohanPeasant")])
        fighters = [_object("GondorFighter", position=(float(i), 0.0, 0.0)) for i in range(3)]
        new = _map(objects=fighters)
        section = _section(diff_maps(old, new), "objects")
        assert section.added == ["3 x GondorFighter"]
        assert section.removed == ["RohanPeasant"]

    def test_named_object_move_reports_as_change(self):
        hero = lambda pos: _object("GondorAragorn", position=pos, objectName="Hero1")  # noqa: E731
        old = _map(objects=[hero((10.0, 20.0, 0.0))])
        new = _map(objects=[hero((15.0, 21.0, 0.0))])
        section = _section(diff_maps(old, new), "objects")
        assert not section.added and not section.removed
        entry = section.changed[0]
        assert entry.label == "Hero1 (GondorAragorn)"
        assert entry.details == ["moved (10, 20, 0) -> (15, 21, 0)"]

    def test_untouched_objects_cancel_before_pairing(self):
        scenery = [_object("RohanTree", position=(float(i), 0.0, 0.0)) for i in range(5)]
        old = _map(objects=[*scenery, _object("RohanPeasant")])
        new = _map(objects=list(scenery))
        section = _section(diff_maps(old, new), "objects")
        assert section.removed == ["RohanPeasant"] and not section.added

    def test_trigger_area_outline_change(self):
        old = _map(trigger_areas=[TriggerArea("Zone1", "", 1, [(0.0, 0.0), (1.0, 0.0)], 0)])
        new = _map(
            trigger_areas=[TriggerArea("Zone1", "", 1, [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0)], 0)]
        )
        section = _section(diff_maps(old, new), "areas")
        assert section.changed[0].details == ["outline: 2 -> 3 points"]

    def test_script_action_argument_change(self):
        move = lambda team: _script(  # noqa: E731
            "Intro", actions_if_true=[_action("MoveTeamTo", _arg(team))]
        )
        old = _map(scripts=[move("Alpha")])
        new = _map(scripts=[move("Beta")])
        section = _section(diff_maps(old, new), "scripts")
        entry = section.changed[0]
        assert entry.label == "Intro"
        assert entry.details == ["- do: MoveTeamTo('Alpha')", "+ do: MoveTeamTo('Beta')"]

    def test_script_setting_change_and_add_remove(self):
        old = _map(scripts=[_script("Intro"), _script("Gone")])
        new = _map(scripts=[_script("Intro", is_active=False), _script("Fresh")])
        section = _section(diff_maps(old, new), "scripts")
        assert section.added == ["Fresh"]
        assert section.removed == ["Gone"]
        assert "is_active: True -> False" in section.changed[0].details

    def test_heightmap_cells_summarised(self):
        old = _map(heightmap=_heightmap([[0, 0], [0, 0]]))
        new = _map(heightmap=_heightmap([[0, 9], [0, 8]], start_pos=999))  # offsets never count
        section = _section(diff_maps(old, new), "terrain")
        assert section.changed[0].label == "heightmap: 2 of 4 cells changed"

    def test_format_mentions_sections(self):
        old = _map(objects=[_object("RohanPeasant")])
        new = _map(objects=[])
        text = format_map_diff(diff_maps(old, new), "v1", "v2")
        assert "# map diff: v1 -> v2" in text
        assert "## objects" in text
        assert "- RohanPeasant" in text


def _git_repo(tmp_path):
    repo = tmp_path / "repo"
    (repo / "maps" / "alpha").mkdir(parents=True)

    def git(*args):
        subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)

    subprocess.run(["git", "init", "-q", str(repo)], check=True, capture_output=True, text=True)
    git("config", "user.email", "t@t.t")
    git("config", "user.name", "t")
    return repo, git


class TestCommitDiff:
    def test_commit_map_changes_lists_only_map_files(self, tmp_path):
        repo, git = _git_repo(tmp_path)
        (repo / "maps" / "alpha" / "alpha.map").write_bytes(b"v1")
        (repo / "notes.txt").write_text("hi", encoding="utf-8")
        git("add", "-A")
        git("commit", "-q", "-m", "first")
        changes = commit_map_changes(repo, "HEAD")
        assert [(c.status, c.path) for c in changes] == [("A", "maps/alpha/alpha.map")]

    def test_diff_commit_maps_reports_modified_and_added(self, tmp_path, monkeypatch):
        repo, git = _git_repo(tmp_path)
        (repo / "maps" / "alpha" / "alpha.map").write_bytes(b"v1")
        git("add", "-A")
        git("commit", "-q", "-m", "first")
        (repo / "maps" / "alpha" / "alpha.map").write_bytes(b"v2")
        (repo / "maps" / "beta").mkdir()
        (repo / "maps" / "beta" / "beta.bse").write_bytes(b"fresh")
        git("add", "-A")
        git("commit", "-q", "-m", "second")

        parsed = {
            b"v1": _map(objects=[_object("RohanPeasant")]),
            b"v2": _map(objects=[_object("GondorFighter")]),
            b"fresh": _map(objects=[_object("MordorOrc"), _object("MordorOrc", angle=1.0)]),
        }
        monkeypatch.setattr(map_diff, "_parse_blob", parsed.__getitem__)

        results = {r.change.path: r for r in diff_commit_maps(repo, "HEAD")}
        modified = results["maps/alpha/alpha.map"]
        section = _section(modified.diff, "objects")
        assert section.added == ["GondorFighter"] and section.removed == ["RohanPeasant"]
        added = results["maps/beta/beta.bse"]
        assert added.change.status == "A"
        assert "2 object(s)" in added.summary

        text = format_map_file_diffs(list(results.values()), "HEAD^", "HEAD")
        assert "# map diff: HEAD^ -> HEAD" in text
        assert "## maps/alpha/alpha.map" in text
        assert "## + maps/beta/beta.bse" in text

    def test_parse_failure_reported_per_file(self, tmp_path, monkeypatch):
        repo, git = _git_repo(tmp_path)
        (repo / "maps" / "alpha" / "alpha.map").write_bytes(b"junk")
        git("add", "-A")
        git("commit", "-q", "-m", "first")

        def boom(data):
            raise ValueError("Unknown asset: Nope")

        monkeypatch.setattr(map_diff, "_parse_blob", boom)
        (result,) = diff_commit_maps(repo, "HEAD")
        assert result.error == "Unknown asset: Nope"
        text = format_map_file_diffs([result], "HEAD^", "HEAD")
        assert "failed to parse: Unknown asset: Nope" in text

    def test_cli_diff_maps(self, tmp_path, monkeypatch, capsys):
        repo, git = _git_repo(tmp_path)
        (repo / "maps" / "alpha" / "alpha.map").write_bytes(b"v1")
        git("add", "-A")
        git("commit", "-q", "-m", "first")
        (repo / "maps" / "alpha" / "alpha.map").write_bytes(b"v2")
        git("add", "-A")
        git("commit", "-q", "-m", "second")

        parsed = {
            b"v1": _map(scripts=[_script("Intro", actions_if_true=[_action("Move", _arg("A"))])]),
            b"v2": _map(scripts=[_script("Intro", actions_if_true=[_action("Move", _arg("B"))])]),
        }
        monkeypatch.setattr(map_diff, "_parse_blob", parsed.__getitem__)

        assert main(["diff-maps", "HEAD", str(repo)]) == 0
        out = capsys.readouterr().out
        assert "### scripts" in out
        assert "- do: Move('A')" in out
        assert "+ do: Move('B')" in out

    def test_cli_bad_commit_fails_cleanly(self, tmp_path, capsys):
        repo, git = _git_repo(tmp_path)
        (repo / "maps" / "alpha" / "alpha.map").write_bytes(b"v1")
        git("add", "-A")
        git("commit", "-q", "-m", "first")
        assert main(["diff-maps", "nope", str(repo)]) == 2
        assert "git failed" in capsys.readouterr().err


class TestRangeDiff:
    def _three_commits(self, tmp_path):
        """v1 -> v2 -> v3 of one map, one commit each."""
        repo, git = _git_repo(tmp_path)
        for version in (b"v1", b"v2", b"v3"):
            (repo / "maps" / "alpha" / "alpha.map").write_bytes(version)
            git("add", "-A")
            git("commit", "-q", "-m", version.decode())
        return repo

    def test_resolve_range_splits_two_dot(self, tmp_path):
        repo = self._three_commits(tmp_path)
        assert resolve_range(repo, "HEAD~2..HEAD") == ("HEAD~2", "HEAD")
        assert resolve_range(repo, "HEAD~2..") == ("HEAD~2", "HEAD")
        assert resolve_range(repo, "..HEAD~1") == ("HEAD", "HEAD~1")
        assert resolve_range(repo, "HEAD") is None

    def test_resolve_range_three_dot_uses_merge_base(self, tmp_path):
        repo = self._three_commits(tmp_path)
        old, new = resolve_range(repo, "HEAD~2...HEAD")
        # On a linear history the merge base of HEAD~2 and HEAD *is* HEAD~2.
        expected = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD~2"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        assert expected.startswith(old) and new == "HEAD"

    def test_range_reports_net_change_between_endpoints(self, tmp_path, monkeypatch):
        repo = self._three_commits(tmp_path)
        parsed = {
            b"v1": _map(objects=[_object("RohanPeasant")]),
            b"v2": _map(objects=[_object("MordorOrc")]),  # intermediate: must never be read
            b"v3": _map(objects=[_object("GondorFighter")]),
        }
        monkeypatch.setattr(map_diff, "_parse_blob", parsed.__getitem__)
        (result,) = diff_range_maps(repo, "HEAD~2", "HEAD")
        section = _section(result.diff, "objects")
        assert section.added == ["GondorFighter"]
        assert section.removed == ["RohanPeasant"]

    def test_range_skips_change_that_was_reverted(self, tmp_path):
        repo, git = _git_repo(tmp_path)
        for version in (b"v1", b"v2", b"v1"):  # touched then reverted: no net change
            (repo / "maps" / "alpha" / "alpha.map").write_bytes(version)
            git("add", "-A")
            git("commit", "-q", "-m", "step")
        assert diff_range_maps(repo, "HEAD~2", "HEAD") == []

    def test_cli_accepts_range(self, tmp_path, monkeypatch, capsys):
        repo = self._three_commits(tmp_path)
        parsed = {
            b"v1": _map(scripts=[_script("Intro")]),
            b"v3": _map(scripts=[_script("Intro"), _script("Outro")]),
        }
        monkeypatch.setattr(map_diff, "_parse_blob", parsed.__getitem__)
        assert main(["diff-maps", "HEAD~2..HEAD", str(repo)]) == 0
        out = capsys.readouterr().out
        assert "# map diff: HEAD~2 -> HEAD" in out
        assert "+ Outro" in out


class TestOutputFormats:
    def _one_change_repo(self, tmp_path, monkeypatch):
        """One repo, one map modified in HEAD: an object edit plus an added script."""
        repo, git = _git_repo(tmp_path)
        for version in (b"v1", b"v2"):
            (repo / "maps" / "alpha" / "alpha.map").write_bytes(version)
            git("add", "-A")
            git("commit", "-q", "-m", version.decode())
        parsed = {
            b"v1": _map(objects=[_object("RohanPeasant")], scripts=[_script("Intro")]),
            b"v2": _map(
                objects=[_object("GondorFighter")],
                scripts=[_script("Intro"), _script("Outro")],
            ),
        }
        monkeypatch.setattr(map_diff, "_parse_blob", parsed.__getitem__)
        return repo

    def test_json_output_is_structured(self, tmp_path, monkeypatch, capsys):
        repo = self._one_change_repo(tmp_path, monkeypatch)
        assert main(["diff-maps", "HEAD", str(repo), "--output-format", "json"]) == 0
        report = json.loads(capsys.readouterr().out)
        assert (report["old"], report["new"]) == ("HEAD^", "HEAD")
        (entry,) = report["files"]
        assert (entry["status"], entry["path"]) == ("M", "maps/alpha/alpha.map")
        assert entry["error"] is None and entry["summary"] is None
        objects = next(s for s in entry["sections"] if s["title"] == "objects")
        assert objects["added"] == ["GondorFighter"]
        assert objects["removed"] == ["RohanPeasant"]

    def test_json_added_map_has_summary_and_no_sections(self, tmp_path, monkeypatch, capsys):
        repo, git = _git_repo(tmp_path)
        (repo / "maps" / "alpha" / "alpha.map").write_bytes(b"v1")
        git("add", "-A")
        git("commit", "-q", "-m", "first")
        monkeypatch.setattr(
            map_diff, "_parse_blob", {b"v1": _map(objects=[_object("MordorOrc")])}.__getitem__
        )
        assert main(["diff-maps", "HEAD", str(repo), "--output-format", "json"]) == 0
        (entry,) = json.loads(capsys.readouterr().out)["files"]
        assert entry["status"] == "A"
        assert "1 object(s)" in entry["summary"]
        assert entry["sections"] is None

    def test_md_output_quotes_values(self, tmp_path, monkeypatch, capsys):
        repo = self._one_change_repo(tmp_path, monkeypatch)
        assert main(["diff-maps", "HEAD", str(repo), "--output-format", "md"]) == 0
        out = capsys.readouterr().out
        assert "# Map diff: `HEAD^` -> `HEAD`" in out
        assert "## `maps/alpha/alpha.map`" in out
        assert "### objects" in out
        assert "- **Added:** `GondorFighter`" in out
        assert "- **Removed:** `RohanPeasant`" in out
        assert "- **Added:** `Outro`" in out

    def test_md_changed_entry_nests_details(self):
        old = _map(objects=[_object("GondorAragorn", position=(1.0, 0.0, 0.0), objectName="Hero1")])
        new = _map(objects=[_object("GondorAragorn", position=(2.0, 0.0, 0.0), objectName="Hero1")])
        change = map_diff.MapFileChange("M", "maps/a/a.map")
        result = map_diff.MapFileDiff(change, diff=diff_maps(old, new))
        text = map_diff.format_map_file_diffs_md([result], "v1", "v2")
        assert "- **Changed:** `Hero1 (GondorAragorn)`" in text
        assert "  - `moved (1, 0, 0) -> (2, 0, 0)`" in text

    def test_md_empty_report(self, tmp_path, capsys):
        repo, git = _git_repo(tmp_path)
        (repo / "notes.txt").write_text("hi", encoding="utf-8")
        git("add", "-A")
        git("commit", "-q", "-m", "no maps")
        assert main(["diff-maps", "HEAD", str(repo), "--output-format", "md"]) == 0
        assert "_No map files changed._" in capsys.readouterr().out
