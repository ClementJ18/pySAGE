"""Roads as pairs of objects: which objects are road ends, segments, new roads in the corpus's
form, Apply To Selection, keeping pairs whole, picking, and road widths from the game data."""

from types import SimpleNamespace

import pytest

from sage_map.assets.object_list import Object, ObjectsList
from sage_map.assets.waypoint_list import WaypointsList
from sage_map.context import AssetPropertyType
from sage_map.map import Map
from sage_worldbuilder import MapDocument
from sage_worldbuilder.objects import DeleteObjects, copy_objects, paste_objects
from sage_worldbuilder.pick import PickCategory, PickRules
from sage_worldbuilder.roads import (
    BRIDGE_END,
    BRIDGE_START,
    CORNER_ANGLED,
    CORNER_TIGHT,
    DEFAULT_ROAD_WIDTH,
    ROAD_END,
    ROAD_JOIN,
    ROAD_START,
    CornerType,
    RoadStyles,
    add_road,
    apply_road_style,
    nearest_road_end,
    new_road,
    road_segments,
    segment_at,
    selected_segments,
    with_partners,
)
from sage_worldbuilder.scene import MapScene, MarkerKind, marker_kind


def placed(type_name, x=0.0, y=0.0, flags=0, unique=None):
    properties = {}
    if unique is not None:
        properties["uniqueID"] = {
            "name": "uniqueID",
            "type": AssetPropertyType.AsciiString,
            "value": unique,
        }
    return Object(3, (x, y, 0.0), 0.0, flags, type_name, properties, 0, 0)


def map_with(*objects):
    map = Map()
    map.objects_list = ObjectsList(version=3, object_list=list(objects), start_pos=0, end_pos=0)
    map.waypoints_list = WaypointsList(version=1, waypoint_paths=[], start_pos=0, end_pos=0)
    return map


def test_only_the_road_point_flags_make_a_road_marker():
    # 0x100 sits on corpus ambient sound emitters and farms, which are not roads.
    assert marker_kind(placed("Amb_BirdsMountain1", flags=0x100)) is MarkerKind.OBJECT
    assert marker_kind(placed("DirtRoad", flags=ROAD_START)) is MarkerKind.ROAD
    assert marker_kind(placed("Bridge", flags=BRIDGE_END | CORNER_TIGHT)) is MarkerKind.ROAD
    assert marker_kind(placed("Tree")) is MarkerKind.OBJECT


def test_a_0x100_sound_object_picks_as_a_sound():
    sound = placed("Amb_Birds", flags=0x100)
    game = SimpleNamespace(
        objects={"Amb_Birds": SimpleNamespace(EditorSorting=[SimpleNamespace(name="AUDIO")])}
    )
    scene = MapScene.from_map(map_with(sound))
    assert PickRules(game).category(scene.markers[0]) is PickCategory.SOUNDS


def test_segments_are_starts_followed_by_ends():
    a, b = placed("Dirt", 0, 0, ROAD_START), placed("Dirt", 10, 0, ROAD_END)
    sound = placed("Amb", flags=0x100)
    c, d = placed("Arc", 0, 5, BRIDGE_START), placed("Arc", 9, 5, BRIDGE_END | CORNER_ANGLED)
    lone_end = placed("Dirt", 3, 3, ROAD_END)
    lone_start = placed("Dirt", 4, 4, ROAD_START)
    segments = road_segments([a, b, sound, c, d, lone_end, lone_start])
    assert [(s.start, s.end) for s in segments] == [(a, b), (c, d)]
    assert [s.bridge for s in segments] == [False, True]
    assert segments[0].points == ((0.0, 0.0), (10.0, 0.0))
    scene = MapScene.from_map(map_with(a, b, sound, c, d))
    assert [(s.start, s.end) for s in scene.roads] == [(a, b), (c, d)]


def test_a_start_pairs_only_with_an_end_of_its_own_kind():
    bridge_start, road_end = placed("Arc", flags=BRIDGE_START), placed("Dirt", flags=ROAD_END)
    road_start, bridge_end = placed("Dirt", flags=ROAD_START), placed("Arc", flags=BRIDGE_END)
    assert road_segments([bridge_start, road_end]) == []
    assert road_segments([road_start, bridge_end]) == []
    # Two lone bridge starts in a row, as Ford of Bruinen stores, then a road.
    lone = [placed("Arc", flags=BRIDGE_START), placed("Arc", flags=BRIDGE_START)]
    (segment,) = road_segments([*lone, road_start, road_end])
    assert segment.start is road_start


def test_segment_style_reads_corner_and_join():
    start = placed("Dirt", flags=ROAD_START | CORNER_TIGHT | ROAD_JOIN)
    (segment,) = road_segments([start, placed("Dirt", flags=ROAD_END | CORNER_TIGHT | ROAD_JOIN)])
    assert segment.corner is CornerType.TIGHT and segment.join


def test_new_road_takes_the_corpus_form():
    map = map_with(placed("Tree", unique="Tree 41"))
    segment = new_road(
        map, "DirtRoad", (1.0, 2.0), (30.0, 2.0), corner=CornerType.ANGLED, join=True, layer="L"
    )
    start, end = segment.start, segment.end
    assert start.road_type == ROAD_START | CORNER_ANGLED | ROAD_JOIN
    assert end.road_type == ROAD_END | CORNER_ANGLED | ROAD_JOIN
    assert start.position == (1.0, 2.0, 0.0) and end.position == (30.0, 2.0, 0.0)
    assert start.type_name == end.type_name == "DirtRoad"
    # The start's number is one above its end's, as on the corpus maps.
    assert start.properties["uniqueID"]["value"] == "DirtRoad 43"
    assert end.properties["uniqueID"]["value"] == "DirtRoad 42"
    assert list(start.properties) == [
        "objectInitialHealth",
        "objectEnabled",
        "objectIndestructible",
        "objectUnsellable",
        "objectPowered",
        "objectRecruitableAI",
        "objectTargetable",
        "originalOwner",
        "uniqueID",
        "objectLayer",
        "objectBasePriority",
        "objectBasePhase",
    ]
    assert start.properties["originalOwner"]["value"] == "/team"
    assert start.properties["objectLayer"]["value"] == "L"
    bridge = new_road(map, "Arc", (0, 0), (5, 5), bridge=True)
    assert (bridge.start.road_type, bridge.end.road_type) == (BRIDGE_START, BRIDGE_END)


def test_add_road_appends_start_then_end_and_undoes():
    tree = placed("Tree")
    document = MapDocument(map_with(tree))
    segment = new_road(document.map, "Dirt", (0, 0), (10, 0))
    document.execute(add_road(document.map, segment))
    assert document.map.objects_list.object_list == [tree, segment.start, segment.end]
    document.stack.undo()
    assert document.map.objects_list.object_list == [tree]


def test_partners_keep_segments_whole_for_delete_copy_and_paste():
    tree = placed("Tree", 50, 50, unique="Tree 0")
    start = placed("Dirt", 0, 0, ROAD_START, unique="Dirt 2")
    end = placed("Dirt", 10, 0, ROAD_END, unique="Dirt 1")
    map = map_with(tree, start, end)
    assert with_partners(map, [end, tree]) == [tree, start, end]
    assert with_partners(map, [tree]) == [tree]
    assert selected_segments(map, [end])[0].start is start

    clipboard = copy_objects(map, with_partners(map, [end]))
    document = MapDocument(map)
    command, pasted = paste_objects(map, clipboard, (100.0, 100.0))
    document.execute(command)
    assert len(road_segments(map.objects_list.object_list)) == 2
    assert pasted[0].road_type & ROAD_START and pasted[1].road_type & ROAD_END

    document.execute(DeleteObjects(with_partners(map, [end])))
    assert map.objects_list.object_list[0] is tree
    assert start not in map.objects_list.object_list and end not in map.objects_list.object_list


def test_apply_road_style_changes_type_corner_join_and_keeps_other_bits():
    start = placed("Dirt", 0, 0, ROAD_START | CORNER_TIGHT | 0x100)
    end = placed("Dirt", 10, 0, ROAD_END | CORNER_TIGHT)
    document = MapDocument(map_with(start, end))
    segments = road_segments([start, end])
    document.execute(apply_road_style(segments, "Arc", True, CornerType.ANGLED, True))
    assert start.road_type == BRIDGE_START | CORNER_ANGLED | ROAD_JOIN | 0x100
    assert end.road_type == BRIDGE_END | CORNER_ANGLED | ROAD_JOIN
    assert start.type_name == end.type_name == "Arc"
    document.stack.undo()
    assert start.road_type == ROAD_START | CORNER_TIGHT | 0x100
    assert end.type_name == "Dirt"
    # No type chosen: each segment keeps its own type and kind.
    command = apply_road_style(segments, None, True, CornerType.BROAD, False)
    document.execute(command)
    assert (start.road_type, start.type_name) == (ROAD_START | 0x100, "Dirt")
    assert not apply_road_style(segments, None, False, CornerType.BROAD, False).commands


def test_segment_at_and_nearest_road_end():
    a, b = placed("Wide", 0, 0, ROAD_START), placed("Wide", 100, 0, ROAD_END)
    c, d = placed("Thin", 0, 50, ROAD_START), placed("Thin", 100, 50, ROAD_END)
    segments = road_segments([a, b, c, d])
    assert segment_at(segments, 50, 4, 5).start is a
    assert segment_at(segments, 50, 20, 5) is None
    assert segment_at(segments, 50, 20, 5, {"Wide": 60.0}).start is a
    assert segment_at(segments, 150, 0, 5) is None
    assert nearest_road_end(segments, 97, 3, 10) == (100.0, 0.0)
    assert nearest_road_end(segments, 50, 25, 10) is None


def test_road_styles_read_widths_textures_and_bridges():
    game = SimpleNamespace(
        roads={
            "DirtRoad": SimpleNamespace(
                RoadWidth=52.0, RoadWidthInTexture=0.95, Texture="TRDirtRoad.tga"
            ),
            "Odd": SimpleNamespace(),
        },
        bridges={"ArcBridge": SimpleNamespace(Texture="CBWBrdgeArc.tga")},
    )
    styles = RoadStyles(game)
    assert styles.get("dirtroad").width == 52.0
    assert styles.get("dirtroad").width_in_texture == 0.95
    assert styles.get("dirtroad").texture == "TRDirtRoad.tga"
    assert styles.get("Odd").width == DEFAULT_ROAD_WIDTH
    assert styles.get("Odd").width_in_texture == 1.0
    assert styles.get("Odd").texture is None
    # A bridge is a model, not a road texture laid on the ground.
    assert styles.get("ArcBridge").bridge
    assert styles.get("ArcBridge").texture is None
    assert styles.get("Unknown").width == DEFAULT_ROAD_WIDTH
    assert styles.names() == (["DirtRoad", "Odd"], ["ArcBridge"])


@pytest.mark.parametrize("flags", [0x2, 0x4, 0x10, 0x20])
def test_every_point_flag_is_a_road_end(flags):
    assert marker_kind(placed("R", flags=flags)) is MarkerKind.ROAD
