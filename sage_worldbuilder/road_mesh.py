"""Roads laid out on the ground the way the game builds its road mesh (spike R9: `W3DRoadBuffer`).

A road segment is a strip `RoadWidth * RoadWidthInTexture` world units across
(`W3DRoadBuffer::addMapObject`, `0x00852020`: half that on each side); two ends at one spot are
moved a quarter unit apart (`addMapObjects`, `0x00854670`). Where exactly two segments of one road
type share a point, `insertCurveSegments` (`0x00870FC0`) joins them (`insertCurveSegmentAt`,
`0x008760D0`):

- the turn between them is measured in 30-degree steps; under 0.9 of a step, or when the corner is
  angled (flag `0x8`), the two strips are mitred (`W3DRoadBuffer::miter`, `0x00875B20`): their
  edges run on to where they cross;
- otherwise the corner is a curve of radius 1.5 road widths (broad) or 0.5 (tight, flag `0x40`)
  (`0x01E3CFD8`, `0x01E3CFDC`): each strip stops where the curve leaves it, and the curve is made
  of pieces of at most 30 degrees; a curve that does not fit, leaving less than half a unit of
  either segment, is mitred instead.

Points where three or more segments meet are the game's tees, Y and four-way joins
(`insertTeeIntersections`, `insertY`, `insert4Way`); they are not built, so those strips end
square. A piece keeps the segment it belongs to, so selection outlines follow the segment.
Sharp mitres are left square when the edges would cross more than four half-widths out (a
choice: the game's own limit was not read).

Every piece also carries the texture coordinates its corners take in the road type's `Texture`.
A road texture is an atlas of three rows: the straight road on top, and the corner, tee and
four-way pieces below it. The engine (`game.dat` `0x004D7C73`, the vertex loop of the section
loader called at `0x004D761A`, reached from `drawRoads` at `0x004D7217`) gives a point of the
straight strip

    u = dot(point - start, along) / (4 * RoadWidth)
    v = 0.166016 - dot(point - start, left) / (4 * RoadWidth)

with `along` and `left` the unit direction of travel and its left normal, both normalised by the
loader itself (`0x004D771F`). So the texture repeats every four road widths along the road, the
strip covers `RoadWidthInTexture / 8` of it on each side of `0.166016` (`0x00BE43B8`, the middle
of the top row; the other rows sit at `0x00BE43B4` and `0x00BE43B0`), and each segment starts its
own `u` at its stored start, as the game does. A curve piece carries `u` on around the arc from
where its strip ends and `v` across the arc, which the game instead takes from the atlas's corner
rows: a choice, so that the road reads as one ribbon through a bend.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from sage_worldbuilder.roads import CORNER_ANGLED, CORNER_TIGHT, RoadSegment, RoadStyle

__all__ = [
    "BROAD_RADIUS",
    "CURVE_STEP",
    "STRAIGHT_ROW",
    "TEXTURE_REPEAT",
    "TIGHT_RADIUS",
    "RoadPiece",
    "road_pieces",
]

CURVE_STEP = math.radians(30.0)
MITRE_BELOW_STEPS = 0.9
BROAD_RADIUS = 1.5
TIGHT_RADIUS = 0.5
FIT_MARGIN = 0.5
COINCIDENT_NUDGE = 0.25
_MITRE_LIMIT = 4.0
# The middle of the road texture's top row, and the road widths one repeat of it runs for.
STRAIGHT_ROW = 0.166016
TEXTURE_REPEAT = 4.0

Point = tuple[float, float]


@dataclass
class RoadPiece:
    """One quadrilateral of road: a segment's strip, or one piece of a curve joining it on, with
    the texture coordinate of each of its corners."""

    segment: RoadSegment
    corners: list[Point]
    uvs: list[Point]
    curve: bool = False


def _sub(a: Point, b: Point) -> Point:
    return (a[0] - b[0], a[1] - b[1])


def _add(a: Point, b: Point) -> Point:
    return (a[0] + b[0], a[1] + b[1])


def _scale(a: Point, factor: float) -> Point:
    return (a[0] * factor, a[1] * factor)


def _dot(a: Point, b: Point) -> float:
    return a[0] * b[0] + a[1] * b[1]


def _cross(a: Point, b: Point) -> float:
    return a[0] * b[1] - a[1] * b[0]


def _unit(a: Point) -> Point:
    length = math.hypot(*a)
    return (a[0] / length, a[1] / length) if length else (0.0, 0.0)


def _left(a: Point) -> Point:
    return (-a[1], a[0])


def _rotate(a: Point, angle: float) -> Point:
    cos, sin = math.cos(angle), math.sin(angle)
    return (a[0] * cos - a[1] * sin, a[0] * sin + a[1] * cos)


def _crossing(p: Point, d: Point, q: Point, e: Point) -> Point | None:
    """Where the line through `p` along `d` crosses the line through `q` along `e`."""
    denominator = _cross(d, e)
    if abs(denominator) < 1e-9:
        return None
    t = _cross(_sub(q, p), e) / denominator
    return _add(p, _scale(d, t))


@dataclass
class _Strip:
    segment: RoadSegment
    start: Point
    end: Point
    half: float
    road_width: float
    joins: bool
    # start + left, end + left, end - left, start - left, left of the way from start to end.
    corners: list[Point]
    # Where the strip's texture is measured from: its stored start and the unit way to its stored
    # end, kept as they were before any join moved an end.
    origin: Point
    axis: Point

    def uv(self, point: Point) -> Point:
        """Where a point on the ground falls in the road texture."""
        reach = TEXTURE_REPEAT * self.road_width
        offset = _sub(point, self.origin)
        return (
            _dot(offset, self.axis) / reach,
            STRAIGHT_ROW - _dot(offset, _left(self.axis)) / reach,
        )


# For a strip end at a shared point: the corner indices on the left and right of travel, arriving
# at the point or leaving it, by whether the point is the strip's start.
_ARRIVING = {False: (1, 2), True: (3, 0)}
_LEAVING = {True: (0, 3), False: (2, 1)}


def _strip(segment: RoadSegment, style: RoadStyle) -> _Strip:
    start = (segment.start.position[0], segment.start.position[1])
    end = (segment.end.position[0], segment.end.position[1])
    if start == end:
        end = (end[0] + COINCIDENT_NUDGE, end[1])
    width = style.width * (1.0 if style.bridge else style.width_in_texture)
    half = width / 2
    axis = _unit(_sub(end, start))
    left = _scale(_left(axis), half)
    return _Strip(
        segment,
        start,
        end,
        half,
        style.width,
        not (segment.bridge or style.bridge),
        [_add(start, left), _add(end, left), _sub(end, left), _sub(start, left)],
        start,
        axis,
    )


def _key(point: Point) -> tuple[float, float]:
    return (round(point[0], 3), round(point[1], 3))


def _set_end(strip: _Strip, at_start: bool, point: Point) -> None:
    """Move one end of a strip to `point`, square across."""
    if at_start:
        strip.start = point
    else:
        strip.end = point
    left = _scale(_left(_unit(_sub(strip.end, strip.start))), strip.half)
    if at_start:
        strip.corners[0], strip.corners[3] = _add(point, left), _sub(point, left)
    else:
        strip.corners[1], strip.corners[2] = _add(point, left), _sub(point, left)


def _mitre(
    arriving: _Strip,
    arriving_start: bool,
    d1: Point,
    leaving: _Strip,
    leaving_start: bool,
    d2: Point,
) -> None:
    a_left, a_right = _ARRIVING[arriving_start]
    l_left, l_right = _LEAVING[leaving_start]
    point = arriving.start if arriving_start else arriving.end
    limit = _MITRE_LIMIT * max(arriving.half, leaving.half)
    crossings = []
    for a_index, l_index in ((a_left, l_left), (a_right, l_right)):
        crossing = _crossing(arriving.corners[a_index], d1, leaving.corners[l_index], d2)
        if crossing is None or math.dist(crossing, point) > limit:
            return
        crossings.append((a_index, l_index, crossing))
    for a_index, l_index, crossing in crossings:
        arriving.corners[a_index] = crossing
        leaving.corners[l_index] = crossing


def _join(
    arriving: _Strip, arriving_start: bool, leaving: _Strip, leaving_start: bool, flags: int
) -> list[RoadPiece]:
    """Join two strips at their shared point; the curve's pieces, if the join is a curve."""
    point = arriving.start if arriving_start else arriving.end
    arriving_far = arriving.end if arriving_start else arriving.start
    leaving_far = leaving.end if leaving_start else leaving.start
    d1 = _unit(_sub(point, arriving_far))
    d2 = _unit(_sub(leaving_far, point))
    turn = math.acos(max(-1.0, min(1.0, _dot(d1, d2))))
    side = _cross(d1, d2)
    if turn / CURVE_STEP < MITRE_BELOW_STEPS or flags & CORNER_ANGLED or abs(side) < 1e-9:
        _mitre(arriving, arriving_start, d1, leaving, leaving_start, d2)
        return []
    radius = (TIGHT_RADIUS if flags & CORNER_TIGHT else BROAD_RADIUS) * arriving.road_width
    reach = radius * math.tan(turn / 2)
    if (
        math.dist(point, arriving_far) - reach < FIT_MARGIN
        or math.dist(leaving_far, point) - reach < FIT_MARGIN
    ):
        _mitre(arriving, arriving_start, d1, leaving, leaving_start, d2)
        return []
    sign = 1.0 if side > 0 else -1.0
    first = _sub(point, _scale(d1, reach))
    last = _add(point, _scale(d2, reach))
    centre = _add(first, _scale(_left(d1), sign * radius))
    _set_end(arriving, arriving_start, first)
    _set_end(leaving, leaving_start, last)
    outward = _unit(_sub(first, centre))
    inner, outer = max(radius - arriving.half, 0.0), radius + arriving.half
    angles = [
        CURVE_STEP * step
        for step in range(1, math.ceil(turn / CURVE_STEP))
        if CURVE_STEP * step < turn - 1e-9
    ]
    angles = [0.0, *angles, turn]
    # The texture carries on from where the arriving strip now ends, along the arc and across it;
    # travelling against the strip's stored way turns both around.
    span = TEXTURE_REPEAT * arriving.road_width
    forwards = -1.0 if arriving_start else 1.0
    entry = arriving.uv(first)[0]

    def uv(angle: float, rad: float) -> Point:
        return (
            entry + forwards * radius * angle / span,
            STRAIGHT_ROW - forwards * sign * (radius - rad) / span,
        )

    pieces = []
    for low, high in zip(angles, angles[1:], strict=False):
        from_low, from_high = _rotate(outward, sign * low), _rotate(outward, sign * high)
        corners = [
            _add(centre, _scale(from_low, inner)),
            _add(centre, _scale(from_low, outer)),
            _add(centre, _scale(from_high, outer)),
            _add(centre, _scale(from_high, inner)),
        ]
        uvs = [uv(low, inner), uv(low, outer), uv(high, outer), uv(high, inner)]
        pieces.append(RoadPiece(arriving.segment, corners, uvs, curve=True))
    return pieces


def road_pieces(
    segments: Sequence[RoadSegment], style: Callable[[str], RoadStyle]
) -> list[RoadPiece]:
    """The road pieces of a map's segments: each segment's strip, then the curves joining them."""
    strips = [_strip(segment, style(segment.type_name)) for segment in segments]
    ends: dict[tuple[float, float], list[tuple[int, bool]]] = {}
    for index, strip in enumerate(strips):
        ends.setdefault(_key(strip.start), []).append((index, True))
        ends.setdefault(_key(strip.end), []).append((index, False))
    curves: list[RoadPiece] = []
    for shared in ends.values():
        if len(shared) != 2:
            continue
        (first, first_start), (second, second_start) = shared
        a, b = strips[first], strips[second]
        if first == second or not (a.joins and b.joins):
            continue
        if a.segment.type_name.lower() != b.segment.type_name.lower():
            continue
        # The game joins a segment's start onto the end of the one before it: arrive along the
        # strip whose end is at the point when there is one.
        if first_start and not second_start:
            (first, first_start), (second, second_start) = (
                (second, second_start),
                (first, first_start),
            )
            a, b = b, a
        a_object = a.segment.start if first_start else a.segment.end
        b_object = b.segment.start if second_start else b.segment.end
        flags = a_object.road_type | b_object.road_type
        curves.extend(_join(a, first_start, b, second_start, flags))
    strip_pieces = [
        RoadPiece(strip.segment, strip.corners, [strip.uv(corner) for corner in strip.corners])
        for strip in strips
    ]
    return strip_pieces + curves
