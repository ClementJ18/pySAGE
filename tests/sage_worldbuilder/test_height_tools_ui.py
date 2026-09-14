"""Qt-level tests for the height tools: a stroke in the map view, its single undo entry, the
partial terrain redraw, contours and the Brush Options panel. Headless via 'offscreen'; marked
`full`."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")  # headless; must precede the Qt import

import pytest

pytestmark = pytest.mark.full

pytest.importorskip("PyQt6", reason="the [worldbuilder] extra (PyQt6) is not installed")
np = pytest.importorskip("numpy", reason="the [worldbuilder] extra (numpy) is not installed")

from PyQt6.QtCore import QPointF  # noqa: E402
from PyQt6.QtGui import QImage  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from sage_map.assets.height_map import HeightMapBorder, HeightMapData  # noqa: E402
from sage_map.map import Map  # noqa: E402
from sage_worldbuilder import MapDocument  # noqa: E402
from sage_worldbuilder.brush_options import BrushOptions  # noqa: E402
from sage_worldbuilder.settings import Settings  # noqa: E402
from sage_worldbuilder.terrain.brushes import BrushKind  # noqa: E402
from sage_worldbuilder.ui.tools import Gesture  # noqa: E402
from sage_worldbuilder.ui.window import MainWindow  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    yield QApplication.instance() or QApplication([])


def sloped_map(width: int = 40, height: int = 30) -> Map:
    map = Map()
    map.height_map_data = HeightMapData(
        version=5,
        width=width,
        height=height,
        border_width=0,
        borders=[HeightMapBorder((0, 0), (width, height))],
        area=width * height,
        min_height=0,
        max_height=0,
        # A slope with bumps, so smoothing has something to even out.
        elevations=[
            [
                row * 40 + column * 25 + (60 if (row * 7 + column * 3) % 5 == 0 else 0)
                for column in range(width)
            ]
            for row in range(height)
        ],
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
    settings = Settings(install=str(install))
    settings.brush = BrushOptions(width=3, feather=1, height=20.0, amount=2.0, radius=1, rate=10)
    window = MainWindow(settings, load_game_data=False)
    window._set_document(MapDocument(sloped_map()))
    view = window.map_view
    view.resize(600, 500)
    view.transform.width, view.transform.height = 600, 500
    view.fit_map()
    yield window
    window.document = None
    window.close()


def gesture(window, x, y):
    return Gesture((x, y), QPointF(*window.map_view.transform.world_to_screen(x, y)))


def pixels(image: QImage) -> bytes:
    converted = image.convertToFormat(QImage.Format.Format_RGBA8888)
    return bytes(converted.constBits().asarray(converted.sizeInBytes()))


def stroke(window, kind, points):
    view = window.map_view
    window.height_tool_actions[kind].trigger()
    tool = view.tool
    assert tool is window.height_tools[kind]
    first, *rest = points
    assert tool.press(view, gesture(window, *first))
    for point in rest:
        tool.move(view, gesture(window, *point))
    tool.release(view, gesture(window, *points[-1]))


def test_a_stroke_is_one_undo_entry_and_the_view_redraws_only_its_cells(window):
    view, document = window.map_view, window.document
    view._terrain_image()
    before = document.map.height_map_data.elevations[30 - 1 - 10][10]
    stroke(window, BrushKind.SMOOTH, [(100.0, 100.0), (120.0, 100.0), (140.0, 110.0)])
    image = view._image
    assert image is not None, "a stroke inside the height range patches the picture"
    patched = pixels(image)
    view._image = None
    assert pixels(view._terrain_image()) == patched, "the patch matches a full redraw"
    assert document.stack.undo_label == "Smooth Height"

    ground = int(document.terrain.heights[15, 20])
    stroke(window, BrushKind.RAISE, [(200.0, 150.0), (210.0, 150.0), (220.0, 150.0)])
    assert document.terrain.heights[15, 20] > ground
    document.stack.undo()
    assert document.terrain.heights[15, 20] == ground
    assert document.stack.undo_label == "Smooth Height"
    document.stack.undo()
    assert document.map.height_map_data.elevations[30 - 1 - 10][10] == before
    assert not document.stack.can_undo


def test_height_brush_paints_the_brush_height_and_shows_a_brush_outline(window):
    view, document = window.map_view, window.document
    stroke(window, BrushKind.SET, [(50.0, 50.0)])
    assert document.terrain.heights[5, 5] == round(20.0 * 256 / 10)
    view.tool.hover(view, gesture(window, 50.0, 50.0))
    assert view.tool.center == (5.0, 5.0)
    image = QImage(view.size(), QImage.Format.Format_ARGB32)
    view.render(image)


def test_contours_brush_panel_and_height_readout(window):
    view = window.map_view
    window.view_actions["show_contours"].trigger()
    assert window.settings.view.show_contours
    image = QImage(view.size(), QImage.Format.Format_ARGB32)
    view.render(image)
    assert view._contours is not None

    window.brush_panel.width_box.setValue(7)
    assert window.settings.brush.width == 7
    assert window.brush_panel.size_label.text() == "70 ft, 90 ft with the feather"

    window.show_cursor((1, 2), 512.0)
    assert window.height_label.text() == "Height: 512 (20.0 ft)"
