"""The git textconv dump (`sage_map.textconv`): that a real edit diffs as exactly its own lines -
no shift flood from compression, offsets or renumbered ids - and the `sage-map textconv` CLI."""

import copy
import difflib
import io
import subprocess
from pathlib import Path

import pytest

from sage_map.__main__ import main
from sage_map.assets.object_list import Object, ObjectsList
from sage_map.assets.player_scripts import Script, ScriptGroup
from sage_map.assets.waypoint_list import WaypointsList
from sage_map.map import Map, parse_map, parse_map_from_path, write_map
from sage_map.textconv import _script_items, dump_map, textconv_text

MAPS = Path(__file__).parent / "fixtures" / "maps"
LIBRARY = MAPS / "ki lorien.map"


def _changes(old: str, new: str) -> tuple[list[str], list[str]]:
    """The removed and added lines of a line diff between two dumps."""
    removed, added = [], []
    for line in difflib.unified_diff(old.splitlines(), new.splitlines(), lineterm="", n=0):
        if line.startswith(("---", "+++", "@@")):
            continue
        (removed if line.startswith("-") else added).append(line[1:])
    return removed, added


def _resave(m: Map) -> Map:
    """Write the map the way WorldBuilder saves it (compressed) and read it back."""
    return parse_map(io.BytesIO(write_map(m, compress=True)))


def _library_scripts(m: Map) -> list:
    return next(sl.items for sl in m.player_scripts_list.script_lists if sl.items)


def _scripts(items: list):
    for item in items:
        if isinstance(item, ScriptGroup):
            yield from _scripts(item.items)
        elif isinstance(item, Script):
            yield item


def _first_group(items: list) -> ScriptGroup:
    return next(i for i in items if isinstance(i, ScriptGroup) and any(_scripts(i.items)))


@pytest.mark.parametrize("path", sorted(MAPS.iterdir()), ids=lambda p: p.name)
def test_resave_without_changes_dumps_identically(path):
    original = parse_map_from_path(path)
    assert dump_map(_resave(copy.deepcopy(original))) == dump_map(original)


def test_inserted_script_diffs_as_only_its_own_lines():
    original = parse_map_from_path(LIBRARY)
    edited = copy.deepcopy(original)
    group = _first_group(_library_scripts(edited))
    inserted = copy.deepcopy(next(_scripts(group.items)))
    inserted.name = "Inserted__first"
    group.items.insert(0, inserted)

    removed, added = _changes(dump_map(original), dump_map(_resave(edited)))
    assert removed == []
    assert added[0].strip().startswith('script "Inserted__first"')
    assert len(added) == len(list(_script_items([inserted], 0)))


def test_edited_condition_diffs_as_one_line_pair():
    original = parse_map_from_path(LIBRARY)
    edited = copy.deepcopy(original)
    script = next(s for s in _scripts(_library_scripts(edited)) if s.or_conditions)
    script.or_conditions[0].conditions[0].is_inverted = (
        not script.or_conditions[0].conditions[0].is_inverted
    )

    removed, added = _changes(dump_map(original), dump_map(_resave(edited)))
    assert len(removed) == len(added) == 1
    assert removed[0].strip().startswith("if:") and added[0].strip().startswith("if:")


def _waypoint(name: str, identity: int, x: float) -> Object:
    props = {"waypointName": name, "waypointID": identity, "uniqueID": name}
    return Object(
        version=3,
        position=(x, 0.0, 0.0),
        angle=0.0,
        road_type=0,
        type_name="*Waypoints/Waypoint",
        properties={k: {"name": k, "type": None, "value": v} for k, v in props.items()},
        start_pos=0,
        end_pos=0,
    )


def _waypoint_map(names: list[str], links: list[tuple[str, str]]) -> Map:
    """Waypoints numbered 1..n in order, as WorldBuilder keeps them, linked by name."""
    ids = {name: index + 1 for index, name in enumerate(names)}
    m = Map()
    m.objects_list = ObjectsList(
        version=3,
        object_list=[_waypoint(name, ids[name], float(name.split("_")[1])) for name in names],
        start_pos=0,
        end_pos=0,
    )
    m.waypoints_list = WaypointsList(
        version=1, waypoint_paths=[(ids[a], ids[b]) for a, b in links], start_pos=0, end_pos=0
    )
    return m


def test_deleting_a_waypoint_does_not_flood_the_renumbered_rest():
    names = [f"WP_{i}" for i in range(1, 9)]
    links = list(zip(names, names[1:], strict=False))
    before = _waypoint_map(names, links)
    after = _waypoint_map(
        [n for n in names if n != "WP_2"], [(a, b) for a, b in links if "WP_2" not in (a, b)]
    )

    removed, added = _changes(dump_map(before), dump_map(after))
    assert added == []
    assert len(removed) == 3  # the waypoint itself and its two links
    assert '  "WP_1" -> "WP_2"' in removed and '  "WP_2" -> "WP_3"' in removed
    assert not any(
        "waypointID" in line or "uniqueID" in line for line in dump_map(before).splitlines()
    )


def test_script_header_carries_only_non_default_settings():
    text = dump_map(parse_map_from_path(LIBRARY))
    assert "is_active" not in text and "active_in_easy" not in text
    assert any(line.strip().startswith('script "') for line in text.splitlines())


def test_unparseable_bytes_report_instead_of_raising():
    text = textconv_text(b"not a map")
    assert text.startswith("unparseable map (9 bytes, sha1 ")


def test_cli_writes_lf_utf8_bytes(tmp_path, capsysbinary):
    assert main(["textconv", str(LIBRARY)]) == 0
    out = capsysbinary.readouterr().out
    assert b"\r\n" not in out
    assert out.decode("utf-8") == dump_map(parse_map_from_path(LIBRARY))


def test_cli_install_registers_the_diff_driver(tmp_path, monkeypatch, capsys):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    monkeypatch.chdir(tmp_path)
    assert main(["textconv", "--install"]) == 0

    def config(key: str) -> str:
        return subprocess.run(
            ["git", "config", "--get", key], capture_output=True, text=True, check=True
        ).stdout.strip()

    assert config("diff.sage-map.textconv").endswith("-m sage_map textconv")
    assert config("diff.sage-map.cachetextconv") == "true"
    assert config("diff.sage-map.xfuncname")
    assert "*.bse diff=sage-map" in capsys.readouterr().out


def test_git_diff_names_the_changed_script_in_the_hunk_header(tmp_path, monkeypatch, capsys):
    """End to end through real git: attributes + installed driver + a committed library edit."""
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    monkeypatch.chdir(tmp_path)
    assert main(["textconv", "--install"]) == 0
    (tmp_path / ".gitattributes").write_text("*.map diff=sage-map\n*.bse diff=sage-map\n")
    target = tmp_path / "lib.map"
    target.write_bytes(LIBRARY.read_bytes())
    git = ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "core.autocrlf=false"]
    subprocess.run([*git, "add", "."], check=True)
    subprocess.run([*git, "commit", "-qm", "base"], check=True)

    m = parse_map_from_path(LIBRARY)
    script = next(s for s in _scripts(_library_scripts(m)) if s.actions_if_true)
    script.actions_if_true.pop()
    target.write_bytes(write_map(m, compress=True))

    diff = subprocess.run([*git, "diff"], capture_output=True, text=True, check=True).stdout
    hunks = [line for line in diff.splitlines() if line.startswith("@@")]
    assert hunks and all(f'script "{script.name}"' in h for h in hunks)
    assert "Binary files" not in diff
