"""Qt-level tests for the 3D view: opening it from the window, drawing the terrain, clicks landing
on the ground under the cursor, tools working through its camera projection, and edits reaching
it. Headless via 'offscreen' unless another platform is set; marked `full`. Skipped where no
OpenGL 3.3 context can be made."""

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")  # headless; must precede the Qt import

import pytest

pytestmark = pytest.mark.full

pytest.importorskip("PyQt6", reason="the [worldbuilder] extra (PyQt6) is not installed")
np = pytest.importorskip("numpy", reason="the [worldbuilder] extra (numpy) is not installed")
pytest.importorskip("OpenGL", reason="the [worldbuilder] extra (PyOpenGL) is not installed")

from PyQt6.QtCore import QPointF  # noqa: E402
from PyQt6.QtGui import QColor  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from sage_worldbuilder import MapDocument  # noqa: E402
from sage_worldbuilder.brush_options import BrushOptions  # noqa: E402
from sage_worldbuilder.changes import Change, ChangeKind  # noqa: E402
from sage_worldbuilder.render.model_mesh import ModelGeometry, ModelPart  # noqa: E402
from sage_worldbuilder.render.terrain_texturing import atlas_key, build_atlas  # noqa: E402
from sage_worldbuilder.scene import MarkerKind  # noqa: E402
from sage_worldbuilder.settings import Settings  # noqa: E402
from sage_worldbuilder.terrain.brushes import BrushKind  # noqa: E402
from sage_worldbuilder.terrain.cells import CellLayer, TileLayer  # noqa: E402
from sage_worldbuilder.ui.map_view_3d import TerrainMode  # noqa: E402
from sage_worldbuilder.ui.tools import Gesture  # noqa: E402
from sage_worldbuilder.ui.window import MainWindow  # noqa: E402

FIXTURE = (
    Path(__file__).parents[1] / "sage_map" / "fixtures" / "maps" / "map edain ford of bruinen.map"
)
_BACKGROUND = QColor(24, 26, 30)


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
    window.resize(1100, 800)
    window.show()
    yield window
    window.document = None
    window.close()


@pytest.fixture
def view(window):
    window.show_3d_view(True)
    view = window.map_view_3d
    view.resize(640, 480)
    frame = view.grabFramebuffer()
    context = view.context()
    if context is None or not context.isValid() or frame.isNull():
        pytest.skip("no OpenGL context on this platform")
    surface = context.format()
    if (surface.majorVersion(), surface.minorVersion()) < (3, 3):
        pytest.skip("OpenGL 3.3 is not available")
    assert view.failure is None
    view.fit_map()
    return view


def screen_of(view, column, row):
    x, y = view.document.terrain.cell_to_world(column, row)
    return (x, y), QPointF(*view.transform.world_to_screen(x, y))


def test_the_3d_view_takes_the_central_area_and_gives_it_back(window, view):
    assert window.active_view() is view
    assert window.view_3d_action.isChecked()
    window.show_3d_view(False)
    assert window.active_view() is window.map_view
    assert not window.view_3d_action.isChecked()
    window.show_3d_view(True)
    assert window.active_view() is view


def test_the_terrain_fills_the_view(view):
    frame = view.grabFramebuffer()
    step = 8
    samples = [
        frame.pixelColor(x, y)
        for x in range(0, frame.width(), step)
        for y in range(0, frame.height(), step)
    ]
    drawn = sum(1 for color in samples if color.rgb() != _BACKGROUND.rgb())
    assert drawn > len(samples) // 2
    assert view.failure is None


def test_the_ground_under_a_pixel_is_the_point_projected_there(view):
    grid = view.document.terrain
    for column, row in ((grid.width // 2, grid.height // 2), (grid.width // 3, grid.height // 4)):
        (x, y), point = screen_of(view, column, row)
        hit = view.transform.screen_to_world(point.x(), point.y())
        assert hit == pytest.approx((x, y), abs=1.0)


def test_a_mound_stroke_in_the_3d_view_raises_the_ground_and_refreshes_the_mesh(window, view):
    grid = view.document.terrain
    column, row = grid.width // 2, grid.height // 2
    before = grid.heights[row - 3 : row + 4, column - 3 : column + 4].copy()
    window.use_tool(BrushKind.RAISE.value)
    tool = window.map_view.tool
    world, point = screen_of(view, column, row)
    tool.press(view, Gesture(world, point))
    tool.release(view, Gesture(world, point))
    after = view.document.terrain.heights[row - 3 : row + 4, column - 3 : column + 4]
    assert (after >= before).all() and (after > before).any()
    assert view._dirty_chunks or view._rebuild
    view.grabFramebuffer()
    assert not view._dirty_chunks
    assert view.failure is None


def test_clicking_a_marker_in_the_3d_view_selects_its_object(window, view):
    scene = view.scene
    grid = view.document.terrain
    marker = next(
        m
        for m in scene.markers
        if m.kind is MarkerKind.WAYPOINT and grid.nearest_cell(m.x, m.y) is not None
    )
    view.camera.look_at(marker.x, marker.y, view.transform.ground(marker.x, marker.y))
    view.camera.distance = 400.0
    view.transform.moved()
    point = QPointF(*view.transform.world_to_screen(marker.x, marker.y))
    world = view.transform.screen_to_world(point.x(), point.y())
    window.use_tool("select")
    tool = window.map_view.tool
    tool.press(view, Gesture(world, point))
    tool.release(view, Gesture(world, point))
    assert marker.source in view.document.selection


RED, BLUE = (255, 0, 0, 255), (0, 0, 255, 255)


def two_colour_atlas(view):
    """Give the view an atlas where the map's first texture is red and every other one blue,
    and hide what is drawn over the terrain."""
    options = view.options
    options.show_objects = options.show_waypoints = options.show_areas = False
    options.show_boundaries = False
    textures = view.document.map.blend_tile_data.textures
    first = textures[0]

    def cells_for(texture, pixels):
        cells = np.empty((texture.cell_size, texture.cell_size, pixels, pixels, 4), dtype=np.uint8)
        cells[:] = RED if texture is first else BLUE
        return cells

    view.set_atlas(atlas_key(textures), build_atlas(textures, cells_for))
    return first


def in_texture(tiles, texture):
    cells = np.asarray(tiles) >> 2
    return (cells >= texture.cell_start) & (cells < texture.cell_start + texture.cell_count)


def look_down_at(view, x, y, distance):
    view.camera.pitch = 90.0
    view.camera.look_at(x, y, view.transform.ground(x, y))
    view.camera.distance = distance
    view.transform.moved()


def pixel(view, frame, x, y):
    sx, sy = view.transform.project(x, y)
    ratio = frame.width() / view.width()
    return frame.pixelColor(int(sx * ratio), int(sy * ratio))


def test_the_game_textures_colour_a_cell_from_its_texture(view):
    first = two_colour_atlas(view)
    document = view.document
    plain = in_texture(document.cells(TileLayer.TILES), first) & (
        document.cells(TileLayer.BLENDS) == 0
    )
    # A cell whose eight neighbours are plain too, so nothing blends into its middle.
    around = np.ones_like(plain[1:-1, 1:-1])
    for dy in range(3):
        for dx in range(3):
            around &= plain[dy : dy + plain.shape[0] - 2, dx : dx + plain.shape[1] - 2]
    ys, xs = np.nonzero(around)
    column, row = int(xs[0]) + 1, int(ys[0]) + 1
    x, y = document.terrain.cell_to_world(column + 0.5, row + 0.5)
    look_down_at(view, x, y, 80.0)
    frame = view.grabFramebuffer()
    assert view.mode == TerrainMode.TEXTURES
    color = pixel(view, frame, x, y)
    assert color.red() > 100 and color.blue() < 30


def test_a_blend_mixes_its_texture_in_from_its_side(view):
    first = two_colour_atlas(view)
    view.grabFramebuffer()
    _, indices, secondaries = view._blend_tables
    document = view.document
    tiles, blends = document.cells(TileLayer.TILES), document.cells(TileLayer.BLENDS)
    three_way, cliffs = (
        document.cells(TileLayer.THREE_WAY_BLENDS),
        document.cells(TileLayer.CLIFF_TEXTURES),
    )
    valid = (blends > 0) & (blends < len(indices))
    number = np.where(valid, blends, 0)
    candidates = (
        in_texture(tiles, first)
        & valid
        & (indices[number] == 0)
        & ~in_texture(secondaries[number], first)
        & (three_way == 0)
    )
    if cliffs is not None:
        candidates &= cliffs == 0
    ys, xs = np.nonzero(candidates)
    if not ys.size:
        pytest.skip("the fixture has no plain horizontal blend onto its first texture")
    column, row = int(xs[0]), int(ys[0])
    x, y = document.terrain.cell_to_world(column + 0.5, row + 0.5)
    look_down_at(view, x, y, 40.0)
    frame = view.grabFramebuffer()
    left = pixel(view, frame, x - 3.5, y)
    right = pixel(view, frame, x + 3.5, y)
    # Mask 0 brings the blend's texture (blue) in from +x over the cell's own (red).
    assert right.blue() > left.blue() + 60
    assert left.red() > right.red() + 60


def test_objects_are_drawn_as_their_models(view):
    options = view.options
    options.show_waypoints = options.show_areas = options.show_boundaries = False
    options.show_object_dots = False
    terrain = view.document.terrain
    marker = next(
        m
        for m in view.scene.markers
        if m.kind is MarkerKind.OBJECT and terrain.nearest_cell(m.x, m.y) is not None
    )
    name = marker.source.type_name
    # A red square 40 units across, 40 above the ground, seen from straight above.
    top = ModelPart(
        positions=np.array(
            [(-20, -20, 40), (20, -20, 40), (20, 20, 40), (-20, 20, 40)], dtype=np.float32
        ),
        normals=np.tile(np.array((0.0, 0.0, 1.0), dtype=np.float32), (4, 1)),
        uvs=None,
        indices=np.array([0, 1, 2, 0, 2, 3], dtype=np.uint32),
        texture=None,
        color=(1.0, 0.0, 0.0, 1.0),
        two_sided=True,
        translucent=False,
        alpha_test=False,
    )
    view.set_models({name: ModelGeometry((top,))}, {})
    # Off the object's centre, but inside the square however the object is turned and scaled.
    look_down_at(view, marker.x + 5, marker.y, 150.0)
    frame = view.grabFramebuffer()
    color = frame.pixelColor(frame.width() // 2, frame.height() // 2)
    assert color.red() > 150 and color.green() < 60 and color.blue() < 60
    # With the dots off, the model alone shows where the object stands.
    centre = pixel(view, frame, marker.x, marker.y)
    assert centre.red() > 150 and centre.green() < 60 and centre.blue() < 60
    assert marker.source in view.model_objects(name)
    assert view.failure is None


def test_object_dots_are_drawn_over_the_models(window, view):
    options = view.options
    options.show_waypoints = options.show_areas = options.show_boundaries = False
    terrain = view.document.terrain
    marker = next(
        m
        for m in view.scene.markers
        if m.kind is MarkerKind.OBJECT and terrain.nearest_cell(m.x, m.y) is not None
    )
    top = ModelPart(
        positions=np.array(
            [(-20, -20, 40), (20, -20, 40), (20, 20, 40), (-20, 20, 40)], dtype=np.float32
        ),
        normals=np.tile(np.array((0.0, 0.0, 1.0), dtype=np.float32), (4, 1)),
        uvs=None,
        indices=np.array([0, 1, 2, 0, 2, 3], dtype=np.uint32),
        texture=None,
        color=(1.0, 0.0, 0.0, 1.0),
        two_sided=True,
        translucent=False,
        alpha_test=False,
    )
    view.set_models({marker.source.type_name: ModelGeometry((top,))}, {})
    look_down_at(view, marker.x + 5, marker.y, 150.0)
    dot = pixel(view, view.grabFramebuffer(), marker.x, marker.y)
    assert dot.red() > 150 and dot.green() > 150 and dot.blue() < 150
    # Show Object Dots takes it off again, leaving the red model.
    window.view_actions["show_object_dots"].trigger()
    assert not view.options.show_object_dots
    centre = pixel(view, view.grabFramebuffer(), marker.x, marker.y)
    assert centre.red() > 150 and centre.green() < 60 and centre.blue() < 60
    assert view.failure is None


def test_a_click_on_a_dot_picks_its_object_whatever_is_in_front(window):
    """Picking goes by the dots on screen, which are drawn over everything, so it needs no
    frame: the camera projection is all it asks for."""
    window.show_3d_view(True)
    view = window.map_view_3d
    view.resize(640, 480)
    terrain = view.document.terrain
    marker = next(
        m
        for m in view.scene.markers
        if m.kind is MarkerKind.OBJECT and terrain.nearest_cell(m.x, m.y) is not None
    )
    look_down_at(view, marker.x, marker.y, 400.0)
    screen = QPointF(*view.transform.project(marker.x, marker.y))
    # The ground point the click landed on is nowhere near the object, as it is when a wall or a
    # hill stands between the camera and it: the dot under the cursor picks it all the same.
    picked = view.marker_at(screen, (marker.x + 500.0, marker.y + 500.0), 8.0, lambda _m: True)
    assert picked is not None and picked.source is marker.source
    # A click 200 pixels from its dot does not, wherever the ground under it is.
    away = QPointF(screen.x() + 200, screen.y())
    missed = view.marker_at(away, view.world_at(away), 8.0, lambda _m: True)
    assert missed is None or missed.source is not marker.source


def test_tile_feedback_tints_the_terrain(view):
    options = view.options
    options.show_objects = options.show_waypoints = options.show_areas = False
    options.show_boundaries = False
    document = view.document
    impassable = document.cells(CellLayer.IMPASSABLE) != 0
    # A sample whose eight neighbours are impassable too, so its whole tint block is red.
    around = np.ones_like(impassable[1:-1, 1:-1])
    for dy in range(3):
        for dx in range(3):
            around &= impassable[
                dy : dy + impassable.shape[0] - 2, dx : dx + impassable.shape[1] - 2
            ]
    ys, xs = np.nonzero(around)
    if not ys.size:
        pytest.skip("the fixture has no impassable patch")
    x, y = document.terrain.cell_to_world(int(xs[0]) + 1, int(ys[0]) + 1)
    look_down_at(view, x, y, 80.0)
    before = pixel(view, view.grabFramebuffer(), x, y)
    options.show_impassable = True
    view.source.options_changed()
    after = pixel(view, view.grabFramebuffer(), x, y)
    assert after.red() > before.red() + 20
    assert after.green() < before.green()
    assert view.failure is None


def test_top_down_looks_straight_down_and_gives_the_pitch_back(window, view):
    view.camera.pitch = 40.0
    window.top_down_action.trigger()
    assert view.top_down and view.camera.pitch == 90.0
    window.top_down_action.trigger()
    assert not view.top_down and view.camera.pitch == 40.0


def test_the_game_camera_takes_the_maps_camera_settings(window, view):
    settings = view.document.map.world_info.properties
    window.use_game_camera()
    pitch = float(settings["cameraPitchAngle"]["value"])
    height = float(settings["cameraMaxHeight"]["value"])
    assert view.camera.pitch == pytest.approx(pitch)
    eye_height = view.camera.eye[2] - view.camera.target_z
    assert eye_height == pytest.approx(height)


def test_wireframe_and_part_of_the_map_still_draw(window, view):
    window.view_actions["wireframe"].trigger()
    assert view.options.wireframe
    view.grabFramebuffer()
    window.view_actions["show_entire_map"].trigger()
    assert not view.options.show_entire_map
    drawn = view._drawn_chunks(view.document.terrain)
    assert 0 < len(drawn) < len(view._chunks)
    view.grabFramebuffer()
    assert view.failure is None


def test_lock_vertical_drags_the_selection_up(window, view):
    tree = next(m.source for m in view.scene.markers if m.kind is MarkerKind.OBJECT)
    before = tree.position
    window.use_tool("select")
    window.lock_vertical_action.setChecked(True)
    tool = window.map_view.tool
    view.document.selection.set([tree])
    tool._picked = tree
    point = QPointF(*view.transform.world_to_screen(tree.position[0], tree.position[1]))
    world = view.transform.screen_to_world(point.x(), point.y())
    tool.press(view, Gesture(world, point))
    tool._picked = tree
    tool.move(view, Gesture(world, point - QPointF(0, 40)))
    tool.release(view, Gesture(world, point - QPointF(0, 40)))
    assert tree.position[:2] == pytest.approx(before[:2])
    assert tree.position[2] > before[2]


def test_a_whole_terrain_change_rebuilds_the_mesh(view):
    view.grabFramebuffer()
    assert not view._rebuild
    view.source.on_change(Change(ChangeKind.WHOLE))
    assert view._rebuild
    view.grabFramebuffer()
    assert not view._rebuild
    assert view.failure is None


def test_a_lake_is_drawn_at_its_water_height_in_the_3d_view(window, view):
    from sage_worldbuilder.terrain.surface import ground_height  # noqa: PLC0415
    from sage_worldbuilder.water import add_water, new_lake  # noqa: PLC0415

    grid = view.document.terrain
    window.view_actions["show_objects"].trigger()
    (x, y), point = screen_of(view, grid.width // 2, grid.height // 2)
    before = view.grabFramebuffer().pixelColor(int(point.x()), int(point.y()))
    height = round(ground_height(grid, x, y)) + 20
    corners = [
        (x - 200.0, y - 200.0),
        (x + 200.0, y - 200.0),
        (x + 200.0, y + 200.0),
        (x - 200.0, y + 200.0),
    ]
    lake = new_lake(view.document.map, corners, height)
    window.execute(add_water(view.document.map, lake))
    after = view.grabFramebuffer().pixelColor(int(point.x()), int(point.y()))
    assert id(lake) in view._water_drawn
    assert after != before
    window.view_actions["show_water"].trigger()
    hidden = view.grabFramebuffer().pixelColor(int(point.x()), int(point.y()))
    assert hidden == before
    assert view.failure is None


def test_a_road_is_drawn_on_the_ground_in_the_3d_view(window, view):
    from sage_worldbuilder.roads import add_road, new_road  # noqa: PLC0415

    grid = view.document.terrain
    window.view_actions["show_objects"].trigger()
    (x, y), point = screen_of(view, grid.width // 2, grid.height // 2)
    before = view.grabFramebuffer().pixelColor(int(point.x()), int(point.y()))
    segment = new_road(view.document.map, "DirtRoad", (x - 150.0, y), (x + 150.0, y))
    window.execute(add_road(view.document.map, segment))
    after = view.grabFramebuffer().pixelColor(int(point.x()), int(point.y()))
    # The road is ground of its own, drawn before the overlay, not an outline over it.
    assert after != before
    assert view._roads and all(draw.count > 0 for draw in view._roads)
    window.view_actions["show_roads"].trigger()
    hidden = view.grabFramebuffer().pixelColor(int(point.x()), int(point.y()))
    assert hidden == before
    assert view.failure is None


def test_the_editor_opens_in_3d_and_remembers_the_view_left_behind(window, view):
    assert window.active_view() is view
    assert window.settings.view.view_3d is True
    window.show_3d_view(False)
    assert window.settings.view.view_3d is False
    assert Settings.from_dict(window.settings.to_dict()).view.view_3d is False
