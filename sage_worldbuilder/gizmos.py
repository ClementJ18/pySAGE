"""Transform gizmos: the handles drawn on a selection, and what a drag on one of them means.

New, not WorldBuilder. The shapes follow Blender's: a move gizmo is an arrow per axis out of the
selection's centre, and a drag on one holds the move to that axis alone, with X, Y and Z switching
the axis mid-drag. A selected object also carries a shorter handle of its own, out of its
selection ring along its facing, which says which way its front points and rotates it when grabbed.

The map stores one angle per object, its heading about the up axis, so **there is one rotation
axis**: Z. A rotate gizmo is one ring, and X and Y mean nothing to it - an object cannot be
pitched or rolled, whatever a gizmo drew.

Lengths here are in pixels, turned into world units at the view's scale, so a gizmo is the same
size on screen however far the camera is.
"""

from __future__ import annotations

import math
from enum import StrEnum

__all__ = [
    "GIZMO_PIXELS",
    "HANDLE_KNOB_PIXELS",
    "HANDLE_PIXELS",
    "LOCKED_STEP_DEGREES",
    "MOVE_AXES",
    "Axis",
    "axis_tip",
    "constrained",
    "front_tip",
    "point_to_segment",
    "reach",
    "snapped_angle",
]

# How far a move or rotate gizmo reaches from the selection's centre, and how far a selected
# object's own front handle reaches from its dot.
GIZMO_PIXELS = 70.0
HANDLE_PIXELS = 20.0
HANDLE_KNOB_PIXELS = 4.0
# What Lock Angle rounds a turn to: the eight 45-degree directions, as it does for a move.
LOCKED_STEP_DEGREES = 45.0


class Axis(StrEnum):
    """What a gizmo drag is held to. `GROUND` is the free move Select and Move makes."""

    X = "X"
    Y = "Y"
    Z = "Z"
    GROUND = "Ground"


MOVE_AXES = (Axis.X, Axis.Y, Axis.Z)


def reach(pixels: float, scale: float) -> float:
    """`pixels` on screen as world units at a view's scale."""
    return pixels / max(scale, 1e-9)


def front_tip(x: float, y: float, angle: float, scale: float) -> tuple[float, float]:
    """Where a selected object's front handle ends: `HANDLE_PIXELS` out along its facing."""
    out = reach(HANDLE_PIXELS, scale)
    return (x + out * math.cos(angle), y + out * math.sin(angle))


def axis_tip(center: tuple[float, float], axis: Axis, scale: float) -> tuple[float, float]:
    """Where a move gizmo's X or Y arrow ends. Z has no direction on the ground, so it is drawn
    straight up the screen instead and this leaves the centre where it is."""
    out = reach(GIZMO_PIXELS, scale)
    if axis is Axis.X:
        return (center[0] + out, center[1])
    if axis is Axis.Y:
        return (center[0], center[1] + out)
    return center


def constrained(delta: tuple[float, float, float], axis: Axis | None) -> tuple[float, float, float]:
    """A drag's `(dx, dy, dz)` kept to one axis; `GROUND` and no axis keep it on the ground."""
    dx, dy, dz = delta
    if axis is Axis.X:
        return (dx, 0.0, 0.0)
    if axis is Axis.Y:
        return (0.0, dy, 0.0)
    if axis is Axis.Z:
        return (0.0, 0.0, dz)
    return (dx, dy, 0.0)


def snapped_angle(angle: float, degrees: float = LOCKED_STEP_DEGREES) -> float:
    """`angle` radians rounded to the nearest whole `degrees`."""
    if degrees <= 0:
        return angle
    step = math.radians(degrees)
    return round(angle / step) * step


def point_to_segment(
    point: tuple[float, float], start: tuple[float, float], end: tuple[float, float]
) -> float:
    """How far a point lies from a line segment, in whatever units they share."""
    dx, dy = end[0] - start[0], end[1] - start[1]
    length = dx * dx + dy * dy
    if length == 0:
        return math.dist(point, start)
    along = ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy) / length
    along = max(0.0, min(1.0, along))
    return math.dist(point, (start[0] + along * dx, start[1] + along * dy))
