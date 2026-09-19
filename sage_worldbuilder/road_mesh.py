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

Where three or four segments of one road type meet, `insertTeeIntersections` (`0x00870D50`) joins
them first, each with a piece of its own from the atlas's lower rows:

- three: the two closest to straight through are the road, the third its branch. A branch within
  60 degrees of square is a tee (`insertTee`, `0x00856430`): the road ends half a road width to
  either side and the branch half a width out, and a piece reaching 0.515 widths ahead and to
  each side covers the join. Otherwise it is a Y (types 5 and 6): the road end on the side the
  branch leans to stands back 1.025 widths and the other 0.23, the branch goes 1.05 widths out
  turned 45 degrees toward its lean, and the Y piece (`0x0083CE00`), mirrored for a branch on the
  stem's left, covers the fork;
- four: the straightest pair runs through, the other two cross it square (`insert4Way`,
  `0x0086C130`), each ending half a width from the point, under a square piece 0.515 widths out
  on every side.

Before a tee the engine tries a symmetric Y (`insertY`, `0x0085B490`, type 4): three roads none
of which runs on through, one the stem with the other two behind it either side. The stem stands
back 0.275 widths, each arm 0.55 out at 135 degrees from the stem, and a piece 1.59 widths across
the stem covers the fork (`0x0083B6C0`). Five or more ends at one point, or roads of different
types, stay square. A piece keeps the segment it belongs to, so selection outlines follow the
segment.
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
# Joins of three and four roads (`insertTee`, `insert4Way` and their offsets and loaders): a branch
# within this cosine of square to the road is a tee, else a Y; the tee and four-way pieces reach
# this many road widths out; a Y's road ends stand back these many half widths on the near and
# the far side of its fork, and its branch this many half widths out; the Y piece is this many
# widths across, lies this share of that off the stem (the other share when flipped), and runs this
# many widths along the stem. Where each piece's texture sits in the atlas, as (u, v).
TEE_LIMIT = 0.5
JOIN_REACH = 0.515
Y_NEAR = 0.46
Y_FAR = 2.05
Y_BRANCH = 2.1
Y_ACROSS = 1.35
Y_SHIFT = 0.8
Y_FLIPPED_SHIFT = 0.2
Y_LENGTH = 1.2
TEE_TEXTURE = (0.830078125, 0.498046875)
FOUR_WAY_TEXTURE = (0.830078125, 0.830078125)
Y_TEXTURE = (0.39453125, 0.7109375)
# A symmetric Y: no pair of its roads within this cosine of straight, arms best this cosine from
# the stem; the stem stands back and each arm reaches out these many half widths; its piece lies
# this many widths ahead of the point, is this long across the stem and this deep behind.
SYMMETRIC_Y_STRAIGHT = 0.866
SYMMETRIC_Y_ARM = 0.707
SYMMETRIC_Y_STEM = 0.55
SYMMETRIC_Y_OUT = 1.1
SYMMETRIC_Y_AHEAD = 0.29
SYMMETRIC_Y_LENGTH = 1.59
SYMMETRIC_Y_DEPTH = 1.08
SYMMETRIC_Y_TEXTURE = (0.498046875, 0.44140625)

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


def _end_point(strip: _Strip, at_start: bool) -> Point:
    return strip.start if at_start else strip.end


def _far_point(strip: _Strip, at_start: bool) -> Point:
    return strip.end if at_start else strip.start


def _place_end(strip: _Strip, at_start: bool, point: Point, side: Point) -> None:
    """Move one end of a strip to `point`, its edge running `side` either way from it (the
    engine sets a joined end's corners from the join, not square to the strip)."""
    if at_start:
        strip.start = point
    else:
        strip.end = point
    left = _left(_unit(_sub(strip.end, strip.start)))
    if _dot(side, left) < 0:
        side = _scale(side, -1.0)
    if at_start:
        strip.corners[0], strip.corners[3] = _add(point, side), _sub(point, side)
    else:
        strip.corners[1], strip.corners[2] = _add(point, side), _sub(point, side)


def _junction_piece(
    strip: _Strip,
    corners: list[Point],
    origin: Point,
    along: Point,
    left: Point,
    texture_origin: Point,
) -> RoadPiece:
    """A join's own quadrilateral, its texture read from `texture_origin` in the atlas: `u` along
    `along` and `v` against `left`, one repeat every four road widths, as every road piece."""
    reach = TEXTURE_REPEAT * strip.road_width
    along, left = _unit(along), _unit(left)
    uvs = [
        (
            texture_origin[0] + _dot(_sub(corner, origin), along) / reach,
            texture_origin[1] - _dot(_sub(corner, origin), left) / reach,
        )
        for corner in corners
    ]
    return RoadPiece(strip.segment, corners, uvs, curve=True)


def _square_piece(
    strip: _Strip,
    point: Point,
    direction: Point,
    back: float,
    forward: float,
    across: float,
    texture_origin: Point,
) -> RoadPiece:
    """The tee and four-way piece (`0x00839A30`, laid by `0x0083F470`): from `back` behind `point`
    to `forward` ahead of it along `direction`, `across` to each side."""
    axis, left = _unit(direction), _left(_unit(direction))
    start = _sub(point, _scale(axis, back))
    end = _add(point, _scale(axis, forward))
    corners = [
        _add(start, _scale(left, across)),
        _add(end, _scale(left, across)),
        _sub(end, _scale(left, across)),
        _sub(start, _scale(left, across)),
    ]
    return _junction_piece(strip, corners, point, axis, left, texture_origin)


def _straightest_pair(directions: Sequence[Point], order: Sequence[tuple[int, int]]) -> int:
    """The index into `order` of the pair of directions closest to opposite; the first of equals
    in `order`, as the engine compares them."""
    best, best_dot = 0, math.inf
    for index, (a, b) in enumerate(order):
        dot = _dot(directions[a], directions[b])
        if dot < best_dot:
            best, best_dot = index, dot
    return best


def _side(a: Point, b: Point) -> int:
    """Which side of `a` `b` lies on: 1 anticlockwise, -1 clockwise, 0 along it (`0x0085B430`)."""
    cross = _cross(a, b)
    return 1 if cross > 0 else -1 if cross < 0 else 0


def _symmetric_y(strip_ends: list[tuple[_Strip, bool]], point: Point) -> list[RoadPiece] | None:
    """A fork of three roads none of which runs on through (`insertY`, `0x0085B490`), or None
    when the three are not one: every pair more than 30 degrees off straight, and one road, the
    stem, with the other two either side of it and behind it. Of several stems the one whose arms
    come nearest 135 degrees from it is taken."""
    directions = [_unit(_sub(_far_point(s, at), point)) for s, at in strip_ends]
    dots = {
        frozenset(pair): _dot(directions[pair[0]], directions[pair[1]])
        for pair in ((0, 1), (0, 2), (1, 2))
    }
    if min(dots.values()) < -SYMMETRIC_Y_STRAIGHT:
        return None
    scores = {}
    for stem, arms in ((0, (1, 2)), (2, (1, 0)), (1, (2, 0))):
        axis = directions[stem]
        first, second = (directions[arm] for arm in arms)
        sides = _side(axis, first), _side(axis, second)
        back = _left(axis)
        if (
            sides[0] != sides[1]
            and sum(sides) == 0
            and _side(back, first) == _side(back, second) == 1
        ):
            scores[stem] = sum(abs(dots[frozenset((stem, arm))] + SYMMETRIC_Y_ARM) for arm in arms)
    if not scores:
        return None
    # Of equal fits the engine keeps the first road, then the second.
    stem = min((0, 1, 2), key=lambda candidate: scores.get(candidate, math.inf))
    strip = strip_ends[0][0]
    width, half = strip.road_width, strip.half
    axis = directions[stem]
    # `offsetSymY` (`0x00865360`): the stem stands back a little, each arm further, out along
    # the stem turned 135 degrees to its side; each end keeps its own square edge or turns with
    # its arm.
    stem_strip, stem_at = strip_ends[stem]
    _place_end(
        stem_strip,
        stem_at,
        _add(point, _scale(axis, SYMMETRIC_Y_STEM * width / 2)),
        _scale(_left(_unit(_sub(stem_strip.end, stem_strip.start))), half),
    )
    for arm in {0, 1, 2} - {stem}:
        turn = 1.0 if _side(axis, directions[arm]) > 0 else -1.0
        out = _rotate(axis, turn * 3 * math.pi / 4)
        arm_strip, arm_at = strip_ends[arm]
        _place_end(
            arm_strip,
            arm_at,
            _add(point, _scale(out, SYMMETRIC_Y_OUT * width / 2)),
            _scale(_left(out), half),
        )
    # The piece (`0x0083B6C0`): across the stem, 1.59 widths long, from 0.29 widths ahead of the
    # point back to 0.79 behind it.
    along = _rotate(axis, -math.pi / 2)
    base = _add(point, _scale(axis, SYMMETRIC_Y_AHEAD * width))
    start = _sub(base, _scale(along, SYMMETRIC_Y_LENGTH * width / 2))
    end = _add(start, _scale(along, SYMMETRIC_Y_LENGTH * width))
    depth = _scale(axis, SYMMETRIC_Y_DEPTH * width)
    corners = [_sub(start, depth), _sub(end, depth), end, start]
    return [_junction_piece(strip, corners, base, along, axis, SYMMETRIC_Y_TEXTURE)]


def _three_way(strip_ends: list[tuple[_Strip, bool]], point: Point) -> list[RoadPiece]:
    """A tee or Y where three strips meet (`W3DRoadBuffer::insertTee`, `0x00856430`), once they
    are no symmetric Y. The two closest to straight through carry on as one road; the third is
    its branch."""
    symmetric = _symmetric_y(strip_ends, point)
    if symmetric is not None:
        return symmetric
    directions = [_unit(_sub(_far_point(s, at), point)) for s, at in strip_ends]
    d01 = _dot(directions[0], directions[1])
    d02 = _dot(directions[0], directions[2])
    d21 = _dot(directions[2], directions[1])
    # The engine's own comparisons, ties included; the road runs from a to b.
    if d02 <= d01:
        a, b, c = (2, 1, 0) if d21 <= d02 else (0, 2, 1)
    else:
        a, b, c = (2, 1, 0) if d21 <= d01 else (0, 1, 2)
    strip = strip_ends[0][0]
    width = strip.road_width
    along = _unit(_sub(directions[b], directions[a]))
    branch = directions[c]
    stem = _left(along) if _cross(along, branch) >= 0 else _scale(_left(along), -1.0)
    (sa, at_a), (sb, at_b), (sc, at_c) = strip_ends[a], strip_ends[b], strip_ends[c]
    half = strip.half
    if abs(_dot(along, branch)) <= TEE_LIMIT:
        # `offsetTee` (`0x0085E830`): the road ends half a width either side, the branch half a
        # width out, each edge square to its own way.
        _place_end(sa, at_a, _sub(point, _scale(along, width / 2)), _scale(stem, half))
        _place_end(sb, at_b, _add(point, _scale(along, width / 2)), _scale(stem, half))
        _place_end(sc, at_c, _add(point, _scale(stem, width / 2)), _scale(along, half))
        return [
            _square_piece(
                strip, point, stem, half, JOIN_REACH * width, JOIN_REACH * width, TEE_TEXTURE
            )
        ]
    # A Y (`offsetY`, `0x00861760`): the branch leans to one side of the stem, and the road end
    # on that side stands back further, under the fork.
    flip = _cross(stem, branch) > 0
    clockwise = _cross(along, stem) < 0
    near, far = (Y_NEAR, Y_FAR) if flip == clockwise else (Y_FAR, Y_NEAR)
    _place_end(sa, at_a, _sub(point, _scale(along, near * width / 2)), _scale(stem, half))
    _place_end(sb, at_b, _add(point, _scale(along, far * width / 2)), _scale(stem, half))
    fork = _rotate(stem, math.pi / 4 if flip else -math.pi / 4)
    _place_end(sc, at_c, _add(point, _scale(fork, Y_BRANCH * width / 2)), _scale(_left(fork), half))
    # The Y piece (`0x0083CE00`): along the stem from half a road width behind the point, across
    # a band 1.35 widths wide that lies mostly on the branch's side; flipped, its texture is
    # read mirrored.
    side = _scale(_left(stem), Y_ACROSS * width)
    base = _sub(point, _scale(side, Y_FLIPPED_SHIFT if flip else Y_SHIFT))
    start = _sub(base, _scale(stem, half))
    end = _add(start, _scale(stem, half + Y_LENGTH * width))
    corners = [start, end, _add(end, side), _add(start, side)]
    left = _scale(side, -1.0) if flip else side
    return [_junction_piece(strip, corners, base, stem, left, Y_TEXTURE)]


# The pairs `insert4Way` (`0x0086C130`) compares, in its order, each (a, b) with the road running
# from a to b; the other two directions follow as (c, d), c's far end choosing the cross side.
_FOUR_WAY_PAIRS = ((0, 1), (0, 2), (0, 3), (1, 2), (1, 3), (2, 3))
_FOUR_WAY_OTHERS = {
    (0, 1): (2, 3),
    (0, 2): (1, 3),
    (0, 3): (2, 1),
    (1, 2): (0, 3),
    (1, 3): (0, 2),
    (2, 3): (0, 1),
}


def _four_way(strip_ends: list[tuple[_Strip, bool]], point: Point) -> list[RoadPiece]:
    """A crossroads where four strips meet (`insert4Way`, `offset4Way` at `0x00867EF0`): the
    straightest pair runs through, the other two cross it square, each ending half a road width
    from the point."""
    directions = [_unit(_sub(_far_point(s, at), point)) for s, at in strip_ends]
    a, b = _FOUR_WAY_PAIRS[_straightest_pair(directions, _FOUR_WAY_PAIRS)]
    c, d = _FOUR_WAY_OTHERS[(a, b)]
    strip = strip_ends[0][0]
    width, half = strip.road_width, strip.half
    along = _unit(_sub(directions[b], directions[a]))
    cross = _left(along)
    if _cross(along, _sub(_far_point(*strip_ends[c]), point)) < 0:
        cross = _scale(cross, -1.0)
    reach = width / 2
    for index, way, side in (
        (a, _scale(along, -reach), _left(along)),
        (b, _scale(along, reach), _left(along)),
        (c, _scale(cross, reach), along),
        (d, _scale(cross, -reach), along),
    ):
        end_strip, at = strip_ends[index]
        _place_end(end_strip, at, _add(point, way), _scale(side, half))
    if along[0] < 0:
        along = _scale(along, -1.0)
    size = JOIN_REACH * width
    return [_square_piece(strip, point, along, size, size, size, FOUR_WAY_TEXTURE)]


def road_pieces(
    segments: Sequence[RoadSegment], style: Callable[[str], RoadStyle]
) -> list[RoadPiece]:
    """The road pieces of a map's segments: each segment's strip, then the curves joining them."""
    strips = [_strip(segment, style(segment.type_name)) for segment in segments]
    ends: dict[tuple[float, float], list[tuple[int, bool]]] = {}
    for index, strip in enumerate(strips):
        ends.setdefault(_key(strip.start), []).append((index, True))
        ends.setdefault(_key(strip.end), []).append((index, False))
    joins: list[RoadPiece] = []
    # The engine builds tees and four-ways first (`insertTeeIntersections`, `0x00870D50`), then
    # the curves: a point's roads must all be of one type and join for either.
    for shared in ends.values():
        if len(shared) not in (3, 4) or len({index for index, _ in shared}) != len(shared):
            continue
        meeting = [(strips[index], at_start) for index, at_start in shared]
        if not all(strip.joins for strip, _ in meeting):
            continue
        if len({strip.segment.type_name.lower() for strip, _ in meeting}) != 1:
            continue
        point = _end_point(*meeting[0])
        build = _three_way if len(meeting) == 3 else _four_way
        joins.extend(build(meeting, point))
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
    return strip_pieces + joins + curves
