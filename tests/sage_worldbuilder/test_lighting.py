"""Global lighting: the lights as WorldBuilder's reader names them, the edits Global Light Options
makes, directions as heading and elevation, and the lights a view is given."""

import math
from pathlib import Path

import pytest

from sage_map.assets.global_lighting import TimeOfTheDay
from sage_worldbuilder import MapDocument, map_defaults
from sage_worldbuilder.lighting import (
    LightSlot,
    LightTarget,
    angles_to_direction,
    current_configuration,
    direction_to_angles,
    light,
    restore_default_lights,
    scene_lights,
    set_light,
    set_lighting,
)

pytest.importorskip("numpy", reason="the [worldbuilder] extra (numpy) is not installed")

from sage_worldbuilder.new_map import NewMapOptions, new_map  # noqa: E402

FIXTURE = (
    Path(__file__).parents[1] / "sage_map" / "fixtures" / "maps" / "map edain ford of bruinen.map"
)


def test_the_default_lights_line_up_by_slot_across_the_three_targets():
    # WorldBuilder's reader order makes each slot's colour and direction the same for terrain,
    # objects and infantry in the corpus's unedited lighting; only the infantry sun's ambient
    # differs. Read in the old order, the slots were scrambled.
    for lights in map_defaults.LIGHTS.values():
        for slot in ("sun", "accent1", "accent2"):
            terrain = lights[f"terrain_{slot}"]
            for other in ("object", "infantry"):
                assert lights[f"{other}_{slot}"][1:] == terrain[1:]


def test_a_real_maps_trailing_settings_decode():
    lighting = MapDocument.from_bytes(FIXTURE.read_bytes()).map.global_lighting
    assert lighting.version == 8
    assert lighting.overbright in (1.0, 2.0)
    assert lighting.bloom_enabled in (0, 1)
    assert lighting.shadow_color is not None and lighting.unknown is None


def document():
    return MapDocument(new_map(NewMapOptions(width=16, height=16, border=2)))


def test_everything_sets_all_three_targets_and_undoes():
    doc = document()
    configuration = current_configuration(doc.map.global_lighting)
    doc.execute(
        set_light(
            configuration, LightTarget.EVERYTHING, LightSlot.ACCENT1, "color", (1.0, 0.0, 0.0)
        )
    )
    for target in (LightTarget.TERRAIN, LightTarget.OBJECTS, LightTarget.INFANTRY):
        assert light(configuration, target, LightSlot.ACCENT1).color == (1.0, 0.0, 0.0)
    doc.stack.undo()
    assert light(configuration, LightTarget.INFANTRY, LightSlot.ACCENT1).color != (1.0, 0.0, 0.0)
    unchanged = set_light(
        configuration,
        LightTarget.TERRAIN,
        LightSlot.SUN,
        "ambient",
        light(configuration, LightTarget.TERRAIN, LightSlot.SUN).ambient,
    )
    assert not unchanged.commands


def test_restore_to_default_brings_back_a_new_maps_lights():
    doc = document()
    lighting = doc.map.global_lighting
    doc.execute(set_lighting(lighting, "time_of_the_day", TimeOfTheDay.Night))
    configuration = current_configuration(lighting)
    doc.execute(
        set_light(configuration, LightTarget.TERRAIN, LightSlot.SUN, "color", (0.0, 1.0, 0.0))
    )
    doc.execute(restore_default_lights(lighting, LightTarget.TERRAIN))
    assert light(configuration, LightTarget.TERRAIN, LightSlot.SUN).color == tuple(
        map_defaults.LIGHTS["Night"]["terrain_sun"][1]
    )


@pytest.mark.parametrize("heading, elevation", [(0.0, 45.0), (135.0, 10.0), (270.0, 89.0)])
def test_heading_and_elevation_round_trip(heading, elevation):
    direction = angles_to_direction(heading, elevation)
    assert math.hypot(*direction) == pytest.approx(1.0)
    assert direction[2] < 0
    assert direction_to_angles(direction) == pytest.approx((heading, elevation))


def test_scene_lights_give_ambient_colours_and_directions():
    doc = document()
    lighting = doc.map.global_lighting
    ambient, colors, directions = scene_lights(lighting, LightTarget.TERRAIN)
    sun = light(current_configuration(lighting), LightTarget.TERRAIN, LightSlot.SUN)
    assert ambient == sun.ambient and colors[0] == sun.color and directions[0] == sun.direction
    assert len(colors) == len(directions) == 3
    assert scene_lights(None, LightTarget.TERRAIN) is None
