"""The agent tool layer over a real map: reading, editing as single undo entries, and errors the
agent can act on. The MCP wrapper is checked only when the `mcp` SDK is installed."""

import asyncio
import json
import shutil
from pathlib import Path

import pytest

from sage_worldbuilder.mcp_server import ToolError, WorldBuilderSession
from sage_worldbuilder.mcp_server.tools import TOOLS

FIXTURE = (
    Path(__file__).parents[1] / "sage_map" / "fixtures" / "maps" / "map edain ford of bruinen.map"
)


@pytest.fixture
def session(tmp_path):
    copy = tmp_path / "ford.map"
    shutil.copy(FIXTURE, copy)
    session = WorldBuilderSession()
    session.open_map(str(copy))
    return session


def test_tools_need_an_open_map():
    with pytest.raises(ToolError, match="open_map"):
        WorldBuilderSession().map_info()


def test_map_info_states_the_units_and_extent(session):
    info = session.map_info()
    assert info["title"] == "ford"
    assert info["units"]["world_units_per_cell"] == 10.0
    assert info["playable_extent"]["x"][1] > 0
    assert not info["dirty"]


def test_list_objects_pages_and_filters(session):
    everything = session.list_objects(limit=1000)
    assert everything["total"] > 0
    assert len(everything["objects"]) <= 200
    first = everything["objects"][0]
    filtered = session.list_objects(name_filter=first["template"].upper())
    assert all(first["template"].lower() in o["template"].lower() for o in filtered["objects"])
    assert session.list_objects(offset=everything["total"])["objects"] == []
    assert all(not o["template"].startswith("*Waypoints/") for o in everything["objects"])


def test_place_move_rotate_delete_are_each_one_undo_entry(session):
    placed = session.place_object("TestTree", 100.0, 120.0, angle=90.0)
    object_id = placed["id"]
    assert placed["template"] == "TestTree"
    assert placed["owner"] == "/team"
    assert session.map_info()["dirty"]

    moved = session.move_object(object_id, 150.0, 160.0)
    assert (moved["x"], moved["y"]) == (150.0, 160.0)
    assert session.rotate_object(object_id, 45.0)["angle"] == 45.0

    session.undo()
    assert session.get_object(object_id)["angle"] == 90.0
    session.undo()
    assert session.get_object(object_id)["x"] == 100.0
    session.redo()
    session.redo()

    total = session.list_objects(name_filter="TestTree")["total"]
    session.delete_objects([object_id])
    assert session.list_objects(name_filter="TestTree")["total"] == total - 1
    session.undo()
    assert session.get_object(object_id)["x"] == 150.0


def test_set_object_property_keeps_the_stored_type(session):
    object_id = session.list_objects()["objects"][0]["id"]
    before = session.get_object(object_id)["properties"]["objectInitialHealth"]
    after = session.set_object_property(object_id, "objectInitialHealth", "50")
    assert after["properties"]["objectInitialHealth"] == {"type": before["type"], "value": 50}
    removed = session.set_object_property(object_id, "objectInitialHealth", None)
    assert "objectInitialHealth" not in removed["properties"]
    session.undo()
    assert session.get_object(object_id)["properties"]["objectInitialHealth"]["value"] == 50


def test_unknown_owner_and_object_are_tool_errors(session):
    with pytest.raises(ToolError, match="list_teams"):
        session.place_object("TestTree", 0.0, 0.0, owner="nobody/here")
    with pytest.raises(ToolError, match="no object"):
        session.get_object("does-not-exist")
    with pytest.raises(ToolError, match="no object"):
        session.get_object("#999999")


def test_flattening_terrain_then_sampling_it(session):
    session.set_terrain_height(50.0, 50.0, 90.0, 90.0, 40.0)
    sample = session.sample_heights(50.0, 50.0, 90.0, 90.0)
    assert sample["step"] == 10.0
    assert all(abs(value - 40.0) < 0.05 for row in sample["rows"] for value in row)
    session.undo()
    assert session.sample_heights(50.0, 50.0, 90.0, 90.0) != sample


def test_large_samples_widen_the_step(session):
    extent = session.map_info()["playable_extent"]
    sample = session.sample_heights(0.0, 0.0, extent["x"][1], extent["y"][1])
    assert sum(len(row) for row in sample["rows"]) <= 4096


def test_save_round_trips(session, tmp_path):
    placed = session.place_object("TestTree", 100.0, 120.0)
    target = tmp_path / "out.map"
    session.save_map(str(target))
    reopened = WorldBuilderSession()
    reopened.open_map(str(target))
    assert reopened.get_object(placed["id"])["template"] == "TestTree"


def test_the_server_registers_the_tools(session):
    pytest.importorskip("mcp")
    from sage_worldbuilder.mcp_server.server import build_server  # noqa: PLC0415 - needs mcp

    server = build_server(session)
    assert {tool.name for tool in asyncio.run(server.list_tools())} == set(TOOLS)


def test_selection_is_settable_and_the_view_tools_need_the_editor(session):
    first = session.list_objects(limit=2)["objects"]
    assert session.select_objects([o["id"] for o in first]) == first
    assert session.get_selection() == first
    assert session.select_objects([]) == []
    with pytest.raises(ToolError, match="editor"):
        session.screenshot()
    with pytest.raises(ToolError, match="editor"):
        session.view_at(0.0, 0.0)


def test_marking_is_not_an_edit(session):
    area = session.mark_area(x0=300.0, y0=200.0, x1=100.0, y1=400.0)
    assert area == {
        "name": "A",
        "kind": "area",
        "points": [[100.0, 200.0], [300.0, 200.0], [300.0, 400.0], [100.0, 400.0]],
        "bounds": [100.0, 200.0, 300.0, 400.0],
        "size": [200.0, 200.0],
        "rectangle": True,
    }
    point = session.mark_point(150.0, 250.0)
    assert point["name"] == "P1" and "height" in point
    assert session.get_markers() == [area, session.get_markers("point")[0]]
    info = session.map_info()
    assert not info["dirty"] and info["undo"] is None
    assert session.delete_markers() == {"deleted": 2}
    assert session.get_markers() == []


def test_the_rectangle_tools_take_an_area(session):
    session.mark_area(x0=100.0, y0=100.0, x1=400.0, y1=400.0)
    by_region = session.list_objects(region="a", limit=200)
    by_bounds = session.list_objects(bounds=(100.0, 100.0, 400.0, 400.0), limit=200)
    assert by_region == by_bounds
    session.set_terrain_height(height=25.0, region="A")
    sample = session.sample_heights(region="A")
    assert all(abs(value - 25.0) < 0.05 for row in sample["rows"] for value in row)
    assert session.map_info()["undo"] == "Set Height"


def test_a_polygon_area_limits_the_tools_to_its_shape(session):
    session.set_terrain_height(100.0, 100.0, 300.0, 300.0, 10.0)
    # A triangle over the lower-left half of the square.
    triangle = session.mark_area([[100.0, 100.0], [300.0, 100.0], [100.0, 300.0]])
    assert not triangle["rectangle"]
    result = session.set_terrain_height(height=40.0, region="A")
    rows = session.sample_heights(100.0, 100.0, 300.0, 300.0)["rows"]
    assert rows[0][0] == pytest.approx(40.0, abs=0.05)  # the right-angle corner
    assert rows[-1][-1] == pytest.approx(10.0, abs=0.05)  # the far corner, outside
    assert 0 < result["samples"] < 21 * 21


def test_describe_marker_says_what_an_area_covers(session):
    extent = session.map_info()["playable_extent"]
    session.mark_area(x0=0.0, y0=0.0, x1=extent["x"][1], y1=extent["y"][1], name="all")
    described = session.describe_marker("ALL")
    objects = described["objects"]
    assert objects["total"] == session.list_objects(region="all")["total"]
    assert sum(objects["by_template"].values()) <= objects["total"]
    assert "list" not in objects  # too many to name one by one
    terrain = described["terrain"]
    assert terrain["min_height"] <= terrain["mean_height"] <= terrain["max_height"]
    assert terrain["max_slope_degrees"] >= terrain["mean_slope_degrees"] >= 0
    assert abs(sum(terrain["textures"].values()) - 1) < 0.01
    assert described["cells"] == [round(size / 10, 1) for size in described["size"]]

    session.set_terrain_height(10.0, 10.0, 50.0, 50.0, 30.0)
    session.mark_area(x0=20.0, y0=20.0, x1=40.0, y1=40.0, name="flat")
    flat = session.describe_marker("flat")
    assert flat["terrain"]["max_slope_degrees"] == 0.0
    assert flat["terrain"]["min_height"] == flat["terrain"]["max_height"]


def test_paths_run_through_points_and_follow_them(session):
    session.mark_point(100.0, 100.0, name="ford")
    path = session.mark_path(["ford", [300.0, 100.0], [300.0, 300.0]])
    assert path["name"] == "L1"
    assert path["stops"] == ["FORD", "P1", "P2"]
    assert path["length"] == 400.0
    assert session.get_markers("point")[0]["paths"] == ["L1"]

    moved = session.edit_marker("P1", x=300.0, y=200.0)
    assert moved["x"] == 300.0
    assert session.get_markers("path")[0]["length"] == pytest.approx(223.6 + 100, abs=0.1)
    renamed = session.edit_marker("L1", new_name="road", offset=[10.0, 0.0])
    assert renamed["name"] == "ROAD"
    assert renamed["points"][0] == [110.0, 100.0]
    session.edit_marker("road", points=["P2", "FORD"])
    assert session.get_markers("path")[0]["stops"] == ["P2", "FORD"]

    described = session.describe_marker("road")
    assert described["segments"] == [described["length"]]
    assert described["ground"]["min_height"] <= described["ground"]["max_height"]
    assert abs(sum(described["textures"].values()) - 1) < 0.01

    session.delete_markers(["P2"])
    assert session.get_markers("path") == []  # one point left: the path went with it


def test_a_failed_path_leaves_no_new_points(session):
    with pytest.raises(ToolError, match="two different points"):
        session.mark_path([[0.0, 0.0]])
    assert session.get_markers() == []
    with pytest.raises(ToolError, match="Q is not a marked point"):
        session.mark_path([[0.0, 0.0], "q"])
    assert session.get_markers() == []


def test_editing_an_area_and_a_point(session):
    session.mark_area(x0=0.0, y0=0.0, x1=100.0, y1=100.0)
    reshaped = session.edit_marker("A", points=[[0, 0], [100, 0], [50, 80]])
    assert reshaped["points"] == [[0.0, 0.0], [100.0, 0.0], [50.0, 80.0]]
    point = session.mark_point(500.0, 500.0)
    described = session.describe_marker(point["name"])
    assert described["nearby_radius"] == 100.0
    assert all(obj["distance"] <= 100.0 for obj in described["nearby_objects"])
    with pytest.raises(ToolError, match="nothing to change"):
        session.edit_marker("A")
    with pytest.raises(ToolError, match="x and y move a point"):
        session.edit_marker("A", x=1.0, y=2.0)
    with pytest.raises(ToolError, match="no corners or stops"):
        session.edit_marker("P1", points=[[0, 0]])


def test_an_unknown_marker_names_the_marked_ones(session):
    with pytest.raises(ToolError, match=r"marked: none"):
        session.describe_marker("A")
    session.mark_area(x0=0.0, y0=0.0, x1=10.0, y1=10.0)
    session.mark_point(5.0, 5.0)
    with pytest.raises(ToolError, match=r"marked areas: A"):
        session.sample_heights(region="B")
    with pytest.raises(ToolError, match="P1 is a point, not an area"):
        session.sample_heights(region="P1")
    with pytest.raises(ToolError, match="x0, y0, x1, y1"):
        session.sample_heights(x0=1.0)
    with pytest.raises(ToolError, match="width and a height"):
        session.mark_area(x0=5.0, y0=0.0, x1=5.0, y1=10.0)
    with pytest.raises(ToolError, match="no marker Q"):
        session.delete_markers(["A", "Q"])
    with pytest.raises(ToolError, match="kind is one of"):
        session.get_markers("blob")
    assert len(session.get_markers()) == 2


def test_markers_are_attachable_as_a_resource_and_a_prompt(session):
    pytest.importorskip("mcp")
    from sage_worldbuilder.mcp_server.server import build_server  # noqa: PLC0415 - needs mcp

    server = build_server(session)
    assert [r.name for r in asyncio.run(server.list_resources())] == ["markers"]
    assert [t.name for t in asyncio.run(server.list_resource_templates())] == ["marker"]
    assert [p.name for p in asyncio.run(server.list_prompts())] == ["marker"]

    nothing = asyncio.run(server.get_prompt("marker", {}))
    assert "nothing is marked" in nothing.messages[0].content.text

    session.mark_area(x0=100.0, y0=100.0, x1=300.0, y1=300.0)
    (contents,) = asyncio.run(server.read_resource("markers://all"))
    assert json.loads(contents.content)[0]["name"] == "A"
    (one,) = asyncio.run(server.read_resource("marker://A"))
    assert json.loads(one.content)["bounds"] == [100.0, 100.0, 300.0, 300.0]
    # Headless there is no view, so the prompt carries the description alone.
    prompt = asyncio.run(server.get_prompt("marker", {"name": "a"}))
    assert len(prompt.messages) == 1
    assert '"name": "A"' in prompt.messages[0].content.text
