"""Qt-level tests for texture painting: the palette, Single / Large Tile in Texture mode, a new
texture joining the map, Flood Fill and replace-all, the Eyedropper and Alt-click, and the
no-room refusal. Headless via 'offscreen'; marked `full`."""

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")  # headless; must precede the Qt import

import pytest

pytestmark = pytest.mark.full

pytest.importorskip("PyQt6", reason="the [worldbuilder] extra (PyQt6) is not installed")
np = pytest.importorskip("numpy", reason="the [worldbuilder] extra (numpy) is not installed")

from PyQt6.QtCore import QPointF  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from sage_worldbuilder import MapDocument  # noqa: E402
from sage_worldbuilder.brush_options import BrushOptions, PaintMode  # noqa: E402
from sage_worldbuilder.settings import Settings  # noqa: E402
from sage_worldbuilder.terrain.cells import TileLayer  # noqa: E402
from sage_worldbuilder.terrain.textures import (  # noqa: E402
    NO_ROOM_MESSAGE,
    TEXTURE_CELL_LIMIT,
    texture_classes,
)
from sage_worldbuilder.texture_colors import terrain_class_group  # noqa: E402
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


def classes(window):
    blend = window.document.map.blend_tile_data
    return texture_classes(window.document.cells(TileLayer.TILES), blend.textures)


def click(tool, window, column, row, **modifiers):
    view = window.map_view
    tool.press(view, gesture(window, column, row, **modifiers))
    tool.release(view, gesture(window, column, row, **modifiers))


def test_class_groups_read_type_and_first_region():
    assert terrain_class_group("Type Dirt NEXT Region The_Shire NEXT Region X") == (
        "Dirt",
        "The_Shire",
    )
    assert terrain_class_group("Type CliFF") == ("Cliff", "")
    assert terrain_class_group("") == ("Other", "")


def test_the_palette_lists_the_maps_textures_and_choosing_one_switches_to_texture_mode(window):
    panel = window.terrain_material_panel
    blend = window.document.map.blend_tile_data
    assert sorted(panel.texture_names(), key=str.lower) == sorted(
        {texture.name for texture in blend.textures}, key=str.lower
    )
    group = panel.tree.topLevelItem(0)
    assert group.text(0) == "This map"
    panel.tree.setCurrentItem(group.child(1))
    assert window.settings.paint.mode is PaintMode.TEXTURE
    assert window.settings.paint.texture == group.child(1).text(0)
    assert panel.texture_label.text() == group.child(1).text(0)
    panel.search.setText(group.child(1).text(0)[:5])
    assert panel.tree.topLevelItemCount() == 1


def test_large_tile_paints_a_texture_the_map_has_as_one_stroke(window):
    blend = window.document.map.blend_tile_data
    target = blend.textures[3].name
    window.terrain_material_panel.select_texture(target)
    window.large_tile_action.trigger()
    tool, view = window.large_tile_tool, window.map_view
    tool.press(view, gesture(window, 200.5, 150.5))
    tool.move(view, gesture(window, 206.5, 150.5))
    tool.release(view, gesture(window, 206.5, 150.5))
    painted = classes(window)[149:153, 199:209]
    assert (painted == 3).all()
    assert not window.document.cells(TileLayer.BLENDS)[149:153, 199:209].any()
    assert window.document.stack.undo_label == "Paint Texture"
    window.document.stack.undo()
    assert not window.document.stack.can_undo


def test_a_new_texture_joins_the_map_and_the_palette(window):
    blend = window.document.map.blend_tile_data
    count, cells = len(blend.textures), blend.texture_cell_count
    window.settings.paint.mode = PaintMode.TEXTURE
    window.settings.paint.texture = "BrandNewTexture"
    window.single_tile_action.trigger()
    click(window.single_tile_tool, window, 50.2, 60.3)
    assert len(blend.textures) == count + 1
    assert blend.texture_cell_count == cells + 16
    assert classes(window)[60, 50] == count
    assert "BrandNewTexture" in window.terrain_material_panel.texture_names()
    window.document.stack.undo()
    assert len(blend.textures) == count and blend.texture_cell_count == cells


def test_no_room_for_a_new_texture_is_refused(window):
    blend = window.document.map.blend_tile_data
    blend.texture_cell_count = TEXTURE_CELL_LIMIT - 1
    window.settings.paint.mode = PaintMode.TEXTURE
    window.settings.paint.texture = "BrandNewTexture"
    window.single_tile_action.trigger()
    click(window.single_tile_tool, window, 50.0, 60.0)
    assert not window.document.stack.can_undo
    assert window.statusBar().currentMessage() == NO_ROOM_MESSAGE


def test_flood_fill_eyedropper_and_alt_click(window, monkeypatch):
    document = window.document
    blend = document.map.blend_tile_data
    before = classes(window)
    under = int(before[100, 100])
    window.eyedropper_action.trigger()
    window.settings.paint.texture = ""
    click(window.eyedropper_tool, window, 100.0, 100.0)
    assert window.settings.paint.texture == blend.textures[under].name
    assert window.settings.paint.mode is PaintMode.TEXTURE

    other = next(i for i in range(len(blend.textures)) if i != under)
    window.terrain_material_panel.select_texture(blend.textures[other].name)
    window.flood_fill_action.trigger()
    click(window.flood_fill_tool, window, 100.0, 100.0)
    after = classes(window)
    assert after[100, 100] == other
    assert (after[before != under] == before[before != under]).all()
    region_size = int(((before == under) & (after == other)).sum())
    document.stack.undo()

    asked = []
    monkeypatch.setattr(window, "confirm_replace_all", lambda name: asked.append(name) or True)
    click(window.flood_fill_tool, window, 100.0, 100.0, shift=True)
    assert asked == [blend.textures[under].name]
    everywhere = classes(window)
    assert not (everywhere == under).any()
    assert int((everywhere == other).sum()) >= region_size
    document.stack.undo()

    window.large_tile_action.trigger()
    window.settings.paint.texture = ""
    click(window.large_tile_tool, window, 100.0, 100.0, alt=True)
    assert window.settings.paint.texture == blend.textures[under].name
    assert not document.stack.can_undo


def test_palette_rows_get_previews_once_they_can_be_seen(qapp):
    from PyQt6.QtGui import QColor, QPixmap  # noqa: PLC0415

    from sage_worldbuilder.brush_options import PaintOptions  # noqa: PLC0415
    from sage_worldbuilder.ui.terrain_material import TerrainMaterialPanel  # noqa: PLC0415

    calls = []

    def source(name):
        calls.append(name)
        pixmap = QPixmap(8, 8)
        pixmap.fill(QColor("red"))
        return pixmap

    panel = TerrainMaterialPanel(PaintOptions())
    panel.set_preview_source(source)
    panel.set_catalogue({"Grass": {"": ["G1", "G2"], "Shire": ["S1"]}, "Rock": {"": ["R1"]}})
    panel.load_pending_icons()
    assert calls == [], "closed groups read no previews"

    grass = panel.tree.topLevelItem(0)
    grass.setExpanded(True)
    panel.load_pending_icons()
    assert calls == ["G1", "G2"]
    assert not grass.child(0).icon(0).isNull()
    shire = grass.child(2)
    assert shire.text(0) == "Shire" and shire.child(0).icon(0).isNull()
    shire.setExpanded(True)
    panel.load_pending_icons()
    assert calls == ["G1", "G2", "S1"]

    grass.setExpanded(False)
    grass.setExpanded(True)
    panel.load_pending_icons()
    assert calls == ["G1", "G2", "S1"], "a row's preview is read once"

    panel.search.setText("r1")
    panel.load_pending_icons()
    assert calls[-1] == "R1"
    assert not panel.tree.topLevelItem(0).child(0).icon(0).isNull()
