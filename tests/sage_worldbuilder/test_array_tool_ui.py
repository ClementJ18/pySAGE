"""Qt-level tests for the Radial Array tool and Array Options: a ring of the palette's object, a
ring of the selection, the ring built through a selection that stays put, and each gesture one
undo entry. Headless via the Qt 'offscreen' platform; marked `full`."""

import math
import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")  # headless; must precede the Qt import

import pytest

pytestmark = pytest.mark.full

pytest.importorskip("PyQt6", reason="the [worldbuilder] extra (PyQt6) is not installed")
pytest.importorskip("numpy", reason="the [worldbuilder] extra (numpy) is not installed")

from PyQt6.QtCore import QPointF  # noqa: E402
from PyQt6.QtGui import QImage, QPainter  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from sage_map.assets.object_list import ObjectsList  # noqa: E402
from sage_map.assets.sides_list import SidesList  # noqa: E402
from sage_map.assets.teams import Teams  # noqa: E402
from sage_map.map import Map  # noqa: E402
from sage_worldbuilder import MapDocument  # noqa: E402
from sage_worldbuilder.arrays import Facing  # noqa: E402
from sage_worldbuilder.objects import new_object  # noqa: E402
from sage_worldbuilder.players import new_player  # noqa: E402
from sage_worldbuilder.settings import Settings  # noqa: E402
from sage_worldbuilder.teams import new_team  # noqa: E402
from sage_worldbuilder.ui.tools import Gesture  # noqa: E402
from sage_worldbuilder.ui.window import MainWindow  # noqa: E402

CENTER = (300.0, 300.0)


@pytest.fixture(scope="module")
def qapp():
    yield QApplication.instance() or QApplication([])


def placeable_map():
    map = Map()
    map.objects_list = ObjectsList(version=3, object_list=[], start_pos=0, end_pos=0)
    map.sides_list = SidesList(
        version=6,
        unknown1=False,
        players=[new_player(""), new_player("PlyrCivilian", "Civilian")],
        start_pos=0,
        end_pos=0,
    )
    map.teams = Teams(
        version=1,
        teams=[new_team("team", ""), new_team("teamPlyrCivilian", "PlyrCivilian")],
        start_pos=0,
        end_pos=0,
    )
    return map


@pytest.fixture
def window(qapp, tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    install = tmp_path / "install"
    install.mkdir()
    monkeypatch.setattr("sage_worldbuilder.gamedata.user_data_dir", lambda game: tmp_path)
    window = MainWindow(Settings(install=str(install)), load_game_data=False)
    window.context.game = SimpleNamespace(
        objects={
            "GondorMarketPlace": SimpleNamespace(
                EditorSorting=[SimpleNamespace(name="STRUCTURE")], Side="Gondor"
            ),
            "GondorWall": SimpleNamespace(
                EditorSorting=[SimpleNamespace(name="STRUCTURE")], Side="Gondor"
            ),
        },
        tables={"factions": {}},
    )
    window._set_document(MapDocument(placeable_map()))
    window.map_view.transform.width = window.map_view.transform.height = 600
    window.map_view.transform.fit(0, 0, 600, 600, margin=0)
    window.settings.array.count = 4
    window.array_panel.refresh()
    yield window
    window.document = None
    window.close()


def gesture(window, x, y):
    return Gesture((x, y), QPointF(*window.map_view.transform.world_to_screen(x, y)))


def placed(window):
    return window.document.map.objects_list.object_list


def drag(window, start, end):
    tool, view = window.array_tool, window.map_view
    tool.press(view, gesture(window, *start))
    tool.move(view, gesture(window, *end))
    tool.paint(view, _painter(window))
    tool.release(view, gesture(window, *end))


def _painter(window):
    window._paint_image = QImage(10, 10, QImage.Format.Format_ARGB32)
    return QPainter(window._paint_image)


def existing(window, name, x, y, angle=0.0):
    obj = new_object(window.document.map, name, (x, y, 0.0), angle, "/team")
    placed(window).append(obj)
    return obj


def faces_center(obj, center=CENTER):
    wanted = math.atan2(center[1] - obj.position[1], center[0] - obj.position[0])
    return math.isclose(math.remainder(obj.angle - wanted, math.tau), 0.0, abs_tol=1e-6)


def test_a_drag_rings_the_palette_object_and_aims_every_copy_at_the_centre(window):
    window.palette_panel.choose("GondorMarketPlace")
    window.use_tool("array")
    assert window.map_view.tool is window.array_tool
    assert window.array_tool_action.isChecked()

    drag(window, CENTER, (300.0, 400.0))
    ring = placed(window)
    assert len(ring) == 4
    assert all(obj.type_name == "GondorMarketPlace" for obj in ring)
    assert all(
        math.isclose(math.dist(obj.position[:2], CENTER), 100.0, abs_tol=1e-6) for obj in ring
    )
    assert all(faces_center(obj) for obj in ring)
    # Evenly spaced: the four copies sit a quarter turn apart around the centre.
    bearings = sorted(
        round(math.degrees(math.atan2(y - CENTER[1], x - CENTER[0])) % 360)
        for x, y, _z in (obj.position for obj in ring)
    )
    assert bearings == [0, 90, 180, 270]
    assert window.document.selection.items == tuple(ring)
    assert window.document.stack.undo_label == "Radial Array"
    window.document.stack.undo()
    assert placed(window) == []


def test_the_ring_carries_the_palettes_owner_height_and_fresh_ids(window):
    window.palette_panel.choose("GondorMarketPlace")
    window.palette_panel.owner.setCurrentIndex(1)
    window.palette_panel.height_offset.setValue(5.0)
    window.use_tool("array")
    drag(window, CENTER, (300.0, 400.0))
    ring = placed(window)
    assert [obj.position[2] for obj in ring] == [5.0, 5.0, 5.0, 5.0]
    assert all(
        obj.properties["originalOwner"]["value"] == "PlyrCivilian/teamPlyrCivilian" for obj in ring
    )
    assert [obj.properties["uniqueID"]["value"] for obj in ring] == [
        f"GondorMarketPlace {number}" for number in range(4)
    ]


def test_a_press_with_a_selection_rings_it_where_it_stands_and_turns_it_with_the_copies(window):
    market = existing(window, "GondorMarketPlace", 300.0, 400.0)
    window.document.selection.set([market])
    window.use_tool("array")
    tool, view = window.array_tool, window.map_view
    tool.press(view, gesture(window, *CENTER))
    tool.release(view, gesture(window, *CENTER))

    ring = placed(window)
    assert len(ring) == 4
    assert ring[0] is market
    assert market.position == (300.0, 400.0, 0.0)
    assert all(faces_center(obj) for obj in ring)
    assert sorted(map(id, window.document.selection.items)) == sorted(map(id, ring))
    window.document.stack.undo()
    assert placed(window) == [market]
    assert market.angle == 0.0


def test_a_drag_with_a_selection_repeats_the_group_and_leaves_the_originals_alone(window):
    market = existing(window, "GondorMarketPlace", 100.0, 100.0)
    wall = existing(window, "GondorWall", 110.0, 100.0)
    window.document.selection.set([market, wall])
    window.use_tool("array")
    drag(window, CENTER, (300.0, 400.0))

    ring = placed(window)
    assert len(ring) == 2 + 8
    assert market.position == (100.0, 100.0, 0.0) and wall.position == (110.0, 100.0, 0.0)
    copies = ring[2:]
    assert [obj.type_name for obj in copies[:2]] == ["GondorMarketPlace", "GondorWall"]
    # The group keeps its shape: the wall stays ten units from its market in every copy.
    for building, beside in zip(copies[0::2], copies[1::2], strict=True):
        assert math.isclose(
            math.dist(building.position[:2], beside.position[:2]), 10.0, abs_tol=1e-6
        )
    assert window.document.selection.items == tuple(copies)
    window.document.stack.undo()
    assert placed(window) == [market, wall]


def test_keeping_the_angles_leaves_a_ringed_selection_untouched(window):
    window.settings.array.facing = Facing.KEEP
    window.array_panel.refresh()
    market = existing(window, "GondorMarketPlace", 300.0, 400.0, angle=1.0)
    window.document.selection.set([market])
    window.use_tool("array")
    tool, view = window.array_tool, window.map_view
    tool.press(view, gesture(window, *CENTER))
    tool.release(view, gesture(window, *CENTER))
    assert market.angle == 1.0
    assert len(placed(window)) == 4


def test_turning_the_selection_off_places_the_palettes_object_instead(window):
    market = existing(window, "GondorMarketPlace", 100.0, 100.0)
    window.document.selection.set([market])
    window.palette_panel.choose("GondorWall")
    window.array_panel.selection_box.setChecked(False)
    window.use_tool("array")
    drag(window, CENTER, (300.0, 400.0))
    assert [obj.type_name for obj in placed(window)[1:]] == ["GondorWall"] * 4


def test_a_press_with_no_drag_and_no_selection_places_nothing(window):
    window.palette_panel.choose("GondorMarketPlace")
    window.use_tool("array")
    tool, view = window.array_tool, window.map_view
    tool.press(view, gesture(window, *CENTER))
    tool.release(view, gesture(window, *CENTER))
    assert placed(window) == []


def test_a_drag_that_goes_nowhere_places_nothing(window):
    window.palette_panel.choose("GondorMarketPlace")
    window.use_tool("array")
    tool, view = window.array_tool, window.map_view
    tool.press(view, gesture(window, *CENTER))
    tool.move(view, gesture(window, 300.4, 300.4))
    tool.release(view, gesture(window, 300.4, 300.4))
    assert placed(window) == []


def test_the_tool_needs_an_object_and_says_so(window):
    window.use_tool("array")
    assert not window.array_tool.press(window.map_view, gesture(window, *CENTER))
    assert placed(window) == []


def test_choosing_an_object_does_not_leave_the_array_tool(window):
    window.use_tool("array")
    window.palette_panel.choose("GondorWall")
    window.palette_panel._clicked(window.palette_panel.tree.topLevelItem(0).child(0).child(0))
    assert window.map_view.tool is window.array_tool
    window.use_tool("select")
    window.palette_panel._clicked(window.palette_panel.tree.topLevelItem(0).child(0).child(0))
    assert window.map_view.tool is window.place_tool


def test_array_options_write_through_to_the_settings(window):
    panel = window.array_panel
    panel.count_box.setValue(8)
    panel.facing_box.setCurrentText(Facing.AWAY.value)
    panel.offset_box.setValue(90.0)
    assert window.settings.array.count == 8
    assert window.settings.array.facing is Facing.AWAY
    assert window.settings.array.offset_degrees == 90.0
    assert "45.0 degrees apart" in panel.spacing_label.text()

    window.palette_panel.choose("GondorMarketPlace")
    window.use_tool("array")
    drag(window, CENTER, (300.0, 400.0))
    ring = placed(window)
    assert len(ring) == 8
    # Away from the centre, turned another quarter: the copies lie along the ring.
    for obj in ring:
        outwards = math.atan2(obj.position[1] - CENTER[1], obj.position[0] - CENTER[0])
        assert math.isclose(
            math.remainder(obj.angle - outwards - math.pi / 2, math.tau), 0.0, abs_tol=1e-6
        )
