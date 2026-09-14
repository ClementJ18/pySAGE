"""Qt-level tests for the blend tools: Blend Single Edge with either button, Auto Edge Out and In
by click, and the map view handing right-button drags only to a tool that takes them. Headless via
'offscreen'; marked `full`."""

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")  # headless; must precede the Qt import

import pytest

pytestmark = pytest.mark.full

pytest.importorskip("PyQt6", reason="the [worldbuilder] extra (PyQt6) is not installed")
np = pytest.importorskip("numpy", reason="the [worldbuilder] extra (numpy) is not installed")

from PyQt6.QtCore import QPoint, QPointF, Qt  # noqa: E402
from PyQt6.QtGui import QImage  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from sage_worldbuilder import MapDocument  # noqa: E402
from sage_worldbuilder.brush_options import BrushOptions, PaintMode  # noqa: E402
from sage_worldbuilder.settings import Settings  # noqa: E402
from sage_worldbuilder.terrain.cells import TileLayer  # noqa: E402
from sage_worldbuilder.terrain.textures import texture_classes  # noqa: E402
from sage_worldbuilder.texture_colors import picture_colors  # noqa: E402
from sage_worldbuilder.ui.tools import Gesture  # noqa: E402
from sage_worldbuilder.ui.window import MainWindow  # noqa: E402

FIXTURE = (
    Path(__file__).parents[1] / "sage_map" / "fixtures" / "maps" / "map edain ford of bruinen.map"
)


@pytest.fixture(scope="module")
def qapp():
    yield QApplication.instance() or QApplication([])


@pytest.fixture
def window(qapp, tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    install = tmp_path / "install"
    install.mkdir()
    monkeypatch.setattr("sage_worldbuilder.gamedata.user_data_dir", lambda game: tmp_path)
    settings = Settings(install=str(install))
    settings.brush = BrushOptions(width=4)
    window = MainWindow(settings, load_game_data=False)
    window._set_document(MapDocument.from_bytes(FIXTURE.read_bytes()))
    view = window.map_view
    view.resize(600, 500)
    view.transform.width, view.transform.height = 600, 500
    view.fit_map()
    yield window
    window.document = None
    window.close()


def gesture(window, column, row, **modifiers):
    x, y = window.document.terrain.cell_to_world(column, row)
    point = QPointF(*window.map_view.transform.world_to_screen(x, y))
    return Gesture((x, y), point, **modifiers)


def unblended_edge(window):
    """A cell `(x, y)` with no blend whose +x neighbour shows another texture, unblended too."""
    document = window.document
    classes = texture_classes(
        document.cells(TileLayer.TILES), document.map.blend_tile_data.textures
    )
    blended = (document.cells(TileLayer.BLENDS) != 0) | (
        document.cells(TileLayer.THREE_WAY_BLENDS) != 0
    )
    found = (
        (classes[:, :-1] != classes[:, 1:])
        & (classes[:, 1:] >= 0)
        & ~blended[:, :-1]
        & ~blended[:, 1:]
    )
    ys, xs = np.nonzero(found)
    return int(xs[len(xs) // 2]), int(ys[len(ys) // 2])


def drag(tool, window, start, end, **modifiers):
    view = window.map_view
    tool.press(view, gesture(window, *start, **modifiers))
    tool.move(view, gesture(window, *end, **modifiers))
    tool.release(view, gesture(window, *end, **modifiers))


def test_blend_single_edge_blends_the_dragged_from_texture(window):
    document = window.document
    x, y = unblended_edge(window)
    window.blend_single_edge_action.trigger()
    assert window.map_view.tool is window.blend_single_edge_tool
    drag(window.blend_single_edge_tool, window, (x + 1, y), (x, y))
    assert document.cells(TileLayer.BLENDS)[y, x] != 0
    assert document.stack.undo_label == "Blend Single Edge"
    document.stack.undo()
    assert not document.stack.can_undo


def test_the_right_button_blends_the_chosen_texture(window):
    document = window.document
    blend = document.map.blend_tile_data
    count = len(blend.textures)
    x, y = unblended_edge(window)
    window.settings.paint.mode = PaintMode.TEXTURE
    window.settings.paint.texture = "BrandNewTexture"
    window.blend_single_edge_action.trigger()
    drag(window.blend_single_edge_tool, window, (x + 1, y), (x, y), right=True)
    assert len(blend.textures) == count + 1
    number = int(document.cells(TileLayer.BLENDS)[y, x])
    secondary = blend.blend_descriptions[number - 1].secondary_texture_tile
    assert texture_classes(np.array([secondary]), blend.textures)[0] == count
    document.stack.undo()
    assert len(blend.textures) == count


def test_auto_edge_tools_edge_by_click(window):
    document = window.document
    for action, tool, label in (
        (window.auto_edge_in_action, window.auto_edge_in_tool, "Auto Edge In"),
        (window.auto_edge_out_action, window.auto_edge_out_tool, "Auto Edge Out"),
    ):
        action.trigger()
        assert window.map_view.tool is tool
        view = window.map_view
        tool.press(view, gesture(window, 240, 210, shift=True))
        tool.release(view, gesture(window, 240, 210, shift=True))
        assert document.stack.undo_label == label
        document.stack.undo()
        assert not document.stack.can_undo


def test_the_map_view_hands_the_right_button_only_to_tools_that_take_it(window):
    view = window.map_view
    x, y = window.document.terrain.cell_to_world(100, 100)
    sx, sy = view.transform.world_to_screen(x, y)
    point = QPoint(round(sx), round(sy))
    window.use_tool("select")
    QTest.mousePress(view, Qt.MouseButton.RightButton, pos=point)
    assert not view.gesture_active
    QTest.mouseRelease(view, Qt.MouseButton.RightButton, pos=point)
    window.blend_single_edge_action.trigger()
    QTest.mousePress(view, Qt.MouseButton.RightButton, pos=point)
    assert view.gesture_active and window.blend_single_edge_tool.source is not None
    QTest.mouseRelease(view, Qt.MouseButton.RightButton, pos=point)
    assert not view.gesture_active and window.blend_single_edge_tool.source is None


def test_show_blends_tints_the_blended_cells(window):
    document, view = window.document, window.map_view
    blends = document.cells(TileLayer.BLENDS)
    three_way = document.cells(TileLayer.THREE_WAY_BLENDS)
    rows = blends.shape[0]
    window.view_actions["show_blends"].trigger()
    assert window.settings.view.show_blends
    image = view._blend_image()
    ys, xs = np.nonzero(blends)
    assert image.pixelColor(int(xs[0]), rows - 1 - int(ys[0])).alpha() > 0
    ys, xs = np.nonzero((blends == 0) & (three_way == 0))
    assert image.pixelColor(int(xs[0]), rows - 1 - int(ys[0])).alpha() == 0
    view.grab()  # draws with the tint without failing


class Colors:
    def color(self, name):
        key = sum(name.lower().encode())
        return (key % 200, (key // 7) % 200, (key // 13) % 200)


def image_bytes(image):
    converted = image.convertToFormat(QImage.Format.Format_RGBA8888)
    return bytes(converted.constBits().asarray(converted.sizeInBytes()))


def test_a_blend_redraws_the_blended_picture_as_a_full_redraw_would(window):
    document, view = window.document, window.map_view
    blend = document.map.blend_tile_data
    colors = Colors()
    base, picture, table = picture_colors(blend, document.terrain.heights, colors)
    window._texture_colors = colors
    window._sample_colors = base
    window._blend_table = ((len(blend.blend_descriptions), len(blend.textures)), table)
    view.set_base_colors(picture)
    view._terrain_image()
    x, y = unblended_edge(window)
    window.blend_single_edge_action.trigger()
    drag(window.blend_single_edge_tool, window, (x + 1, y), (x, y))
    assert document.cells(TileLayer.BLENDS)[y, x] != 0
    _, fresh, _ = picture_colors(blend, document.terrain.heights, colors)
    assert np.array_equal(view.base_colors, fresh)
    patched = image_bytes(view._image)
    view._image = None
    assert image_bytes(view._terrain_image()) == patched
