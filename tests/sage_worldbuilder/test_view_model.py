"""The Qt-free parts of the map view: the terrain picture, the view transform and options, and the
scene of markers and areas."""

import math
from types import SimpleNamespace

import pytest

from sage_map.assets.blend_tile_data import BlendTileTexture
from sage_map.assets.object_list import Object, ObjectsList
from sage_map.assets.trigger_areas import TriggerArea, TriggerAreas
from sage_map.assets.waypoint_list import WaypointsList
from sage_map.context import AssetPropertyType
from sage_map.map import Map
from sage_worldbuilder.anchors import RotationAnchors, shown_position
from sage_worldbuilder.scene import MapScene, MarkerKind
from sage_worldbuilder.viewport import GridSettings, ViewOptions, ViewTransform, snap

np = pytest.importorskip("numpy", reason="the [worldbuilder] extra (numpy) is not installed")

from sage_worldbuilder.render.topdown import (  # noqa: E402
    class_colors,
    hillshade,
    terrain_image,
    tile_classes,
)


def test_transform_round_trips_and_flips_y():
    view = ViewTransform(center_x=100.0, center_y=50.0, scale=2.0, width=200, height=100)
    assert view.world_to_screen(100.0, 50.0) == (100.0, 50.0)
    assert view.world_to_screen(110.0, 60.0) == (120.0, 30.0)
    assert view.screen_to_world(120.0, 30.0) == (110.0, 60.0)
    assert view.visible_world() == (50.0, 25.0, 150.0, 75.0)


def test_zoom_keeps_the_point_under_the_cursor():
    view = ViewTransform(scale=1.0, width=400, height=300)
    before = view.screen_to_world(300, 100)
    view.zoom_at(300, 100, 2.5)
    assert view.scale == 2.5
    assert view.screen_to_world(300, 100) == pytest.approx(before)


def test_pan_and_fit():
    view = ViewTransform(scale=2.0, width=100, height=100)
    view.pan_pixels(20, -10)
    assert (view.center_x, view.center_y) == (-10.0, -5.0)
    view.fit(0, 0, 1000, 500, margin=0)
    assert (view.center_x, view.center_y, view.scale) == (500.0, 250.0, 0.1)


def test_grid_lines_and_snapping():
    view = ViewTransform(center_x=0, center_y=0, scale=1.0, width=250, height=100)
    xs, ys = view.grid_lines(50.0)
    assert xs == [-100.0, -50.0, 0.0, 50.0, 100.0]
    assert ys == [-50.0, 0.0, 50.0]
    assert view.grid_lines(2.0) == ([], [])
    assert snap(74.0, 50.0) == 50.0
    assert snap(76.0, 50.0) == 100.0
    assert snap(12.0, 10.0, origin=5.0) == 15.0


def test_view_options_survive_a_dict_and_ignore_bad_values():
    options = ViewOptions(show_grid=True, grid=GridSettings(spacing=40.0, snap=True))
    assert ViewOptions.from_dict(options.to_dict()) == options
    restored = ViewOptions.from_dict({"show_grid": "yes", "grid": {"spacing": -3, "snap": True}})
    assert restored.show_grid is False
    assert restored.grid == GridSettings(snap=True)
    assert ViewOptions.from_dict(None) == ViewOptions()


def test_tile_classes_follow_the_cell_ranges_and_turn_x_y_around():
    class Blend:
        textures = [BlendTileTexture(0, 16, 4, 0, "Grass"), BlendTileTexture(16, 16, 4, 0, "Rock")]
        # Stored [x][y]: column 0 is grass on both rows, column 1 is rock above grass, and a tile
        # past every range.
        tiles = [[0, 4 * 3], [4 * 20, 4 * 99]]

    classes = tile_classes(Blend())
    assert classes.tolist() == [[0, 1], [0, -1]]
    palette = np.array([[10, 20, 30], [200, 100, 0]], dtype=np.uint8)
    fallback = np.zeros((2, 2, 3), dtype=np.uint8)
    colors = class_colors(classes, palette, fallback)
    assert colors[0, 1].tolist() == [200, 100, 0]
    assert colors[1, 1].tolist() == [0, 0, 0]


def test_terrain_image_is_rgba_rows_top_first():
    heights = np.array([[0, 0, 0], [0, 0, 0], [500, 500, 500]], dtype=np.uint16)
    image = terrain_image(heights)
    assert image.shape == (3, 3, 4)
    assert image.flags.c_contiguous
    assert (image[..., 3] == 255).all()
    # The top row of the picture is the highest row of the map, lighter on the height ramp.
    assert image[0, 1, :3].sum() > image[2, 1, :3].sum()
    flat = hillshade(np.zeros((4, 4)))
    assert np.allclose(flat, flat[0, 0])
    base = np.full((3, 3, 3), 100, dtype=np.uint8)
    assert terrain_image(heights, base)[2, 0, 0] != terrain_image(heights)[2, 0, 0]


def _object(type_name, x, y, road_type=0, **properties):
    stored = {
        key: {
            "name": key,
            "type": AssetPropertyType.Integer
            if isinstance(v, int)
            else AssetPropertyType.AsciiString,
            "value": v,
        }
        for key, v in properties.items()
    }
    return Object(3, (x, y, 0.0), 0.0, road_type, type_name, stored, 0, 0)


def scene_map() -> Map:
    map = Map()
    map.objects_list = ObjectsList(
        version=3,
        object_list=[
            _object("GondorFighter", 10.0, 10.0, objectName="Guard"),
            _object("*Waypoints/Waypoint", 100.0, 100.0, waypointID=1, waypointName="A"),
            _object("*Waypoints/Waypoint", 200.0, 100.0, waypointID=2, waypointName="B"),
            _object("RoadSegment", 300.0, 300.0, road_type=4),
            _object("*GenericAIObjects/GenericAIObject", 400.0, 0.0),
            _object("Tree", 12.0, 11.0),
        ],
        start_pos=0,
        end_pos=0,
    )
    map.waypoints_list = WaypointsList(
        version=1, waypoint_paths=[(1, 2), (2, 7)], start_pos=0, end_pos=0
    )
    map.trigger_areas = TriggerAreas(
        version=1,
        trigger_areas=[TriggerArea("Zone", "", 1, [(0, 0), (50, 0), (50, 50)], 0)],
        start_pos=0,
        end_pos=0,
    )
    return map


def test_scene_markers_kinds_links_and_areas():
    scene = MapScene.from_map(scene_map())
    assert [marker.kind for marker in scene.markers] == [
        MarkerKind.OBJECT,
        MarkerKind.WAYPOINT,
        MarkerKind.WAYPOINT,
        MarkerKind.ROAD,
        MarkerKind.GENERIC_AI,
        MarkerKind.OBJECT,
    ]
    assert [marker.label for marker in scene.markers[:3]] == ["Guard", "A", "B"]
    assert [(a.label, b.label) for a, b in scene.links] == [("A", "B")]
    assert scene.areas[0].points == ((0.0, 0.0), (50.0, 0.0), (50.0, 50.0))


def test_scene_picking():
    map = scene_map()
    scene = MapScene.from_map(map)
    inside = sorted(marker.source.type_name for marker in scene.in_rect(150, 150, 0, 0))
    assert inside == ["*Waypoints/Waypoint", "GondorFighter", "Tree"]
    assert scene.nearest(11.0, 10.0, 5.0).source.type_name == "GondorFighter"
    assert scene.nearest(12.0, 11.0, 5.0).source.type_name == "Tree"
    assert scene.nearest(11.0, 10.0, 5.0, frozenset({MarkerKind.WAYPOINT})) is None
    assert scene.nearest(1000.0, 1000.0, 5.0) is None
    tree = map.objects_list.object_list[-1]
    assert scene.marker_for(tree).x == 12.0


def test_rotation_anchors_turn_with_the_object():
    game = SimpleNamespace(
        objects={
            "CastleWall": SimpleNamespace(GeometryRotationAnchorOffset=[[375.0, 0.0, 0.0]]),
            "Tower": SimpleNamespace(GeometryRotationAnchorOffset=[[10.0, 5.0], [99.0, 99.0]]),
            "Tree": SimpleNamespace(),
        }
    )
    anchors = RotationAnchors(game)
    assert anchors.get("castlewall") == (375.0, 0.0)
    assert anchors.get("Tower") == (10.0, 5.0)
    assert anchors.get("Tree") == anchors.get("Unknown") == (0.0, 0.0)

    tower = _object("Tower", 100.0, 200.0)
    assert shown_position(tower, anchors) == pytest.approx((110.0, 205.0, 0.0))
    tower.angle = math.pi / 2
    assert shown_position(tower, anchors) == pytest.approx((95.0, 210.0, 0.0))
    assert shown_position(tower, None) == (100.0, 200.0, 0.0)
    assert tower.position == (100.0, 200.0, 0.0)


def test_scene_stands_anchored_objects_around_their_pivot():
    # Two walls stored at one pivot, turned apart, as a castle base stores its ring.
    east = _object("CastleWall", 1000.0, 1000.0)
    north = _object("CastleWall", 1000.0, 1000.0)
    north.angle = math.pi / 2
    map = Map()
    map.objects_list = ObjectsList(version=3, object_list=[east, north], start_pos=0, end_pos=0)
    game = SimpleNamespace(
        objects={"CastleWall": SimpleNamespace(GeometryRotationAnchorOffset=[[375.0, 0.0, 0.0]])}
    )

    scene = MapScene.from_map(map, RotationAnchors(game))
    assert (scene.marker_for(east).x, scene.marker_for(east).y) == pytest.approx((1375.0, 1000.0))
    assert (scene.marker_for(north).x, scene.marker_for(north).y) == pytest.approx((1000.0, 1375.0))
    assert scene.nearest(1000.0, 1370.0, 10.0).source is north
    assert scene.nearest(1000.0, 1000.0, 10.0) is None
    unanchored = MapScene.from_map(map)
    assert (unanchored.marker_for(north).x, unanchored.marker_for(north).y) == (1000.0, 1000.0)
