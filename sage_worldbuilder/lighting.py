"""Global Light Options: the map's lights for its time of day, as WorldBuilder's dialog edits them.

The dialog (154) edits one time of day at a time, the map's own, for one target: the terrain,
objects, infantry, or everything (which writes all three and shows the objects' lights, as its
slider handlers at `0x00508A20` read the objects' block). For the target it edits the sun's
ambient colour, and each of the sun's and the two accents' colour and direction. A direction is set
with two sliders, a heading of 0-359 degrees and an elevation of 0-90; here a heading is the
compass direction the light comes from, counter-clockwise from +x, and the elevation its height
above the horizon. That conversion is a choice: WorldBuilder's is not read.

Colours are floats, 1.0 for full, as the chunk stores them; the dialog's sliders show them 0-255.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from enum import StrEnum

from sage_map.assets.global_lighting import (
    GlobalLight,
    GlobalLighting,
    GlobalLightingConfiguration,
    TimeOfTheDay,
)
from sage_worldbuilder import map_defaults
from sage_worldbuilder.changes import Change, ChangeKind
from sage_worldbuilder.commands.base import Command, CompositeCommand, SetAttribute

__all__ = [
    "SETTINGS",
    "LightSlot",
    "LightTarget",
    "angles_to_direction",
    "current_configuration",
    "direction_to_angles",
    "light",
    "next_time_of_day",
    "restore_default_lights",
    "scene_lights",
    "set_light",
    "set_lighting",
]

SETTINGS = Change(ChangeKind.SETTINGS)

Vector = tuple[float, float, float]


class LightTarget(StrEnum):
    TERRAIN = "Terrain"
    OBJECTS = "Objects"
    INFANTRY = "Infantry"
    EVERYTHING = "Everything"


class LightSlot(StrEnum):
    SUN = "Sun"
    ACCENT1 = "Accent 1"
    ACCENT2 = "Accent 2"


_PREFIX = {
    LightTarget.TERRAIN: "terrain",
    LightTarget.OBJECTS: "object",
    LightTarget.INFANTRY: "infantry",
}
_SUFFIX = {LightSlot.SUN: "sun", LightSlot.ACCENT1: "accent1", LightSlot.ACCENT2: "accent2"}


def _targets(target: LightTarget) -> tuple[LightTarget, ...]:
    if target is LightTarget.EVERYTHING:
        return (LightTarget.TERRAIN, LightTarget.OBJECTS, LightTarget.INFANTRY)
    return (target,)


def _name(target: LightTarget, slot: LightSlot) -> str:
    shown = LightTarget.OBJECTS if target is LightTarget.EVERYTHING else target
    return f"{_PREFIX[shown]}_{_SUFFIX[slot]}"


def current_configuration(lighting: GlobalLighting) -> GlobalLightingConfiguration:
    return lighting.lighting_configurations[lighting.time_of_the_day]


def light(
    configuration: GlobalLightingConfiguration, target: LightTarget, slot: LightSlot
) -> GlobalLight | None:
    """The light a target's slot shows (the objects' for Everything), or None when the chunk's
    version does not store it."""
    return getattr(configuration, _name(target, slot))


def set_light(
    configuration: GlobalLightingConfiguration,
    target: LightTarget,
    slot: LightSlot,
    field: str,
    value: Vector,
    label: str = "Global Light Options",
) -> CompositeCommand:
    """Set one field (`ambient`, `color` or `direction`) of a slot's light for a target, or for
    all three with Everything; lights already at the value, or not stored, are left alone."""
    commands: list[Command] = []
    for each in _targets(target):
        found = getattr(configuration, _name(each, slot))
        if found is not None and tuple(getattr(found, field)) != tuple(value):
            commands.append(SetAttribute(found, field, tuple(value), SETTINGS, label))
    return CompositeCommand(label, commands)


def set_lighting(
    lighting: GlobalLighting, field: str, value: object, label: str = "Global Light Options"
) -> Command:
    return SetAttribute(lighting, field, value, SETTINGS, label)


def next_time_of_day(lighting: GlobalLighting, label: str = "Change Time Of Day") -> Command:
    """Change Time Of Day (32942, Ctrl+D): the map's next time of day, Night going back to Morning.
    WorldBuilder steps its time of day the same way (`0x00649ED0`) and saves the lighting chunk
    with it; it counts to 5 before wrapping, one past the four the chunk names."""
    times = list(TimeOfTheDay)
    following = times[(times.index(lighting.time_of_the_day) + 1) % len(times)]
    return SetAttribute(lighting, "time_of_the_day", following, SETTINGS, label)


def restore_default_lights(
    lighting: GlobalLighting, target: LightTarget, label: str = "Restore To Default"
) -> CompositeCommand:
    """Restore To Default: the target's lights for the map's time of day go back to a new map's."""
    configuration = current_configuration(lighting)
    defaults = map_defaults.LIGHTS[lighting.time_of_the_day.name]
    commands: list[Command] = []
    for each in _targets(target):
        for slot in LightSlot:
            name = _name(each, slot)
            found = getattr(configuration, name)
            if found is None:
                continue
            for field, value in zip(("ambient", "color", "direction"), defaults[name], strict=True):
                if tuple(getattr(found, field)) != tuple(value):
                    commands.append(SetAttribute(found, field, tuple(value), SETTINGS, label))
    return CompositeCommand(label, commands)


def direction_to_angles(direction: Sequence[float]) -> tuple[float, float]:
    """(heading, elevation) in degrees for a light's direction: the heading it comes from,
    0-360 counter-clockwise from +x, and how far above the horizon, 0-90."""
    x, y, z = direction
    length = math.sqrt(x * x + y * y + z * z)
    if length == 0:
        return 0.0, 90.0
    elevation = math.degrees(math.asin(max(-1.0, min(1.0, -z / length))))
    heading = math.degrees(math.atan2(-y, -x)) % 360.0 if x or y else 0.0
    return heading, max(0.0, elevation)


def angles_to_direction(heading: float, elevation: float) -> Vector:
    """The unit direction of a light coming from `heading` at `elevation` degrees."""
    h, e = math.radians(heading), math.radians(elevation)
    return (-math.cos(e) * math.cos(h), -math.cos(e) * math.sin(h), -math.sin(e))


def scene_lights(
    lighting: GlobalLighting | None, target: LightTarget
) -> tuple[Vector, list[Vector], list[Vector]] | None:
    """What lights a target in the map's time of day, for a view: the sun's ambient colour, and
    the colour and direction of the sun and both accents (black for a light the chunk lacks).
    None without a lighting chunk."""
    if lighting is None:
        return None
    configuration = current_configuration(lighting)
    sun = light(configuration, target, LightSlot.SUN)
    ambient = tuple(sun.ambient) if sun is not None else (0.0, 0.0, 0.0)
    colors: list[Vector] = []
    directions: list[Vector] = []
    for slot in LightSlot:
        found = light(configuration, target, slot)
        colors.append(tuple(found.color) if found is not None else (0.0, 0.0, 0.0))  # type: ignore[arg-type]
        directions.append(tuple(found.direction) if found is not None else (0.0, 0.0, -1.0))  # type: ignore[arg-type]
    return ambient, colors, directions  # type: ignore[return-value]
