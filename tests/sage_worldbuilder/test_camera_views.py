"""The 3D view's camera options without a display: raising objects (Lock Vertical), the chunks
Partial Map Size draws, and the options kept with the settings."""

import pytest

np = pytest.importorskip("numpy", reason="the [worldbuilder] extra (numpy) is not installed")

from sage_map.assets.object_list import Object  # noqa: E402
from sage_map.map import Map  # noqa: E402
from sage_worldbuilder import MapDocument  # noqa: E402
from sage_worldbuilder.objects import MoveObjects  # noqa: E402
from sage_worldbuilder.render.terrain_mesh import chunk_boxes, chunks_near  # noqa: E402
from sage_worldbuilder.viewport import PARTIAL_MAP_SIZES, ViewOptions  # noqa: E402


def placed(x, y, z):
    obj = Object.__new__(Object)
    obj.position = (x, y, z)
    obj.angle = 0.0
    obj.type_name = "Tree"
    obj.properties = {}
    return obj


def test_raising_objects_merges_a_drag_and_undoes_to_the_start():
    document = MapDocument(Map())
    tree = placed(10.0, 20.0, 5.0)
    document.execute(MoveObjects([tree], 0.0, 0.0, dz=4.0))
    document.execute(MoveObjects([tree], 0.0, 0.0, dz=-1.5))
    assert tree.position == pytest.approx((10.0, 20.0, 7.5))
    document.stack.undo()
    assert tree.position == (10.0, 20.0, 5.0)


def test_partial_map_size_draws_the_chunks_near_the_target():
    boxes = chunk_boxes(260, 260, 64)
    # Chunks cover samples 0-64, 64-128, 128-192, 192-256, 256-259; a border of 0.
    assert chunks_near(boxes, 0, 320.0, 320.0, 10.0) == [0]
    assert chunks_near(boxes, 0, 640.0, 320.0, 10.0) == [0, 1]
    everything = chunks_near(boxes, 0, 1300.0, 1300.0, 5000.0)
    assert everything == list(range(len(boxes)))
    # With a border of 10 cells the first chunk starts 100 units below and left of the origin.
    assert chunks_near(boxes, 10, -50.0, -50.0, 10.0) == [0]
    assert chunks_near(boxes, 10, -500.0, -500.0, 10.0) == []


def test_the_3d_options_are_kept_with_the_settings():
    options = ViewOptions(wireframe=True, show_entire_map=False, partial_map_size=161)
    restored = ViewOptions.from_dict(options.to_dict())
    assert restored.wireframe and not restored.show_entire_map
    assert restored.partial_map_size == 161
    assert ViewOptions.from_dict({"partial_map_size": 150}).partial_map_size == PARTIAL_MAP_SIZES[0]
