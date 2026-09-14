"""Castle templates rebuilt from a base's objects, as WorldBuilder writes them on saving a base."""

import io
import math
from types import SimpleNamespace

import pytest

from sage_map.assets.trigger_areas import TriggerArea, TriggerAreas
from sage_map.map import parse_map, write_map
from sage_worldbuilder.anchors import RotationAnchors
from sage_worldbuilder.document import MapDocument
from sage_worldbuilder.objects import new_object, place_objects

np = pytest.importorskip("numpy", reason="the [worldbuilder] extra (numpy) is not installed")

from sage_worldbuilder.castles import (  # noqa: E402
    CastleKinds,
    castle_templates,
    is_base_path,
    refresh_castle_templates,
)
from sage_worldbuilder.new_map import NewMapOptions, new_map  # noqa: E402

CENTER = SimpleNamespace(name="CASTLE_CENTER")
GAME = SimpleNamespace(
    objects={
        "CastleCenter": SimpleNamespace(KindOf=[CENTER]),
        "Tower": SimpleNamespace(KindOf=[]),
        "CastleWall": SimpleNamespace(KindOf=[], GeometryRotationAnchorOffset=[[375.0, 0.0, 0.0]]),
    }
)


def f32(value: float) -> float:
    return float(np.float32(value))


def _map():
    return new_map(NewMapOptions(width=64, height=64, border=4))


def _add(map, type_name, position, angle=0.0, **values):
    obj = new_object(map, type_name, position, angle, "/team")
    for key in ("objectBasePriority", "objectBasePhase"):
        del obj.properties[key]
    for key, value in values.items():
        kind = type(next(iter(obj.properties.values()))["type"])
        stored = {bool: kind.Boolean, int: kind.Integer, str: kind.AsciiString}[type(value)]
        obj.properties[key] = {"name": key, "type": stored, "value": value}
    map.objects_list.object_list.append(obj)
    return obj


def test_pieces_are_stored_from_the_castle_centre():
    map = _map()
    _add(map, "CastleCenter", (500.0, 500.0, 0.0), objectBaseName="Keep")
    _add(
        map,
        "Tower",
        (530.5, 490.25, 2.0),
        0.5,
        objectBaseName="Keep",
        objectBasePriority=200,
        objectBasePhase=3,
    )
    _add(map, "Tower", (400.0, 600.0, 0.0), objectBaseName="Keep", objectName="Gate tower")
    _add(map, "Tower", (1.0, 1.0, 0.0), objectBaseName="Keep", objectIsABase=True)
    _add(map, "Tower", (9.0, 9.0, 0.0))

    chunk = castle_templates(map, "Keep", CastleKinds(GAME), None)

    assert chunk.version == 5
    assert chunk.property_key[2] == "Keep"
    assert [
        (t.name, t.template_name, t.offset, t.angle, t.priority, t.phase) for t in chunk.templates
    ] == [
        ("", "Tower", (30.5, -9.75, 2.0), f32(0.5), 200, 3),
        ("Gate tower", "Tower", (-100.0, 100.0, 0.0), 0.0, 40, 40),
    ]
    assert chunk.perimeters == []


def test_without_a_centre_the_pieces_mean_is_the_centre():
    map = _map()
    _add(map, "Tower", (100.0, 100.0, 0.0), objectBaseName="Camp")
    _add(map, "Tower", (200.0, 300.0, 0.0), objectBaseName="Camp")

    chunk = castle_templates(map, "Camp", CastleKinds(GAME), None)

    assert [t.offset for t in chunk.templates] == [(-50.0, -100.0, 0.0), (50.0, 100.0, 0.0)]


def test_walls_are_placed_where_they_stand_not_at_their_pivot():
    map = _map()
    _add(map, "CastleCenter", (500.0, 500.0, 0.0), objectBaseName="Keep")
    _add(map, "CastleWall", (500.0, 500.0, 0.0), math.pi / 2, objectBaseName="Keep")

    chunk = castle_templates(map, "Keep", CastleKinds(GAME), RotationAnchors(GAME))

    x, y, _ = chunk.templates[0].offset
    assert abs(x) < 1e-3 and abs(y - 375.0) < 1e-3


def test_trigger_areas_become_perimeters_relative_to_the_centre():
    map = _map()
    _add(map, "CastleCenter", (500.0, 500.0, 0.0), objectBaseName="Keep")
    area = TriggerArea("InnerRing", "", 1, [(400.0, 400.0), (600.0, 450.0)], 0)
    if map.trigger_areas is None:
        map.trigger_areas = TriggerAreas(1, [area], 0, 0)
    else:
        map.trigger_areas.trigger_areas.append(area)

    chunk = castle_templates(map, "Keep", CastleKinds(GAME), None)

    assert [(p.name, [(q.x, q.y) for q in p.points]) for p in chunk.perimeters] == [
        ("InnerRing", [(-100.0, -100.0), (100.0, -50.0)])
    ]


def test_refresh_replaces_the_chunk_only_for_a_base_with_game_data():
    map = _map()
    _add(map, "Tower", (100.0, 100.0, 0.0), objectBaseName="Camp")

    assert not refresh_castle_templates(map, "maps/camp/camp.map", GAME)
    assert not refresh_castle_templates(map, "bases/camp/camp.bse", None)
    assert map.castle_templates is None
    assert refresh_castle_templates(map, "bases/camp/camp.bse", GAME)

    reread = parse_map(io.BytesIO(write_map(map, compress=False)))
    assert reread.castle_templates.property_key[2] == "camp"
    assert reread.castle_templates.templates == map.castle_templates.templates
    assert is_base_path("X.BSE") and not is_base_path("x.map") and not is_base_path(None)


def test_a_base_needs_new_templates_after_its_objects_change(tmp_path):
    document = MapDocument(_map())
    assert document.castle_templates_stale

    refresh_castle_templates(document.map, tmp_path / "camp.bse", GAME)
    document.save(tmp_path / "camp.bse")
    assert not document.castle_templates_stale

    tower = new_object(document.map, "Tower", (10.0, 10.0, 0.0), 0.0, "/team")
    document.execute(place_objects(document.map, [tower]))
    assert document.castle_templates_stale

    document.stack.undo()
    document.save(tmp_path / "camp.bse")
    assert not document.castle_templates_stale
