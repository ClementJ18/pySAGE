"""`CameraView` - what the local client's camera sees, and reading it out of a process.

The camera here is one read from a running RotWK 2.01 replay (1920x1080, the default 50 degree
field of view), and the objects are ones that were on that screen: a Gondor farm in the middle,
a Rohan stud farm up and to the left, and a battalion of Gondor fighters just below centre. So the
projection is checked against what a person saw, not against the same algebra run backwards.
"""

from __future__ import annotations

import math
import struct

import pytest

from sage_live import CameraView, Session
from sage_live.backends.memory import MemoryBackend
from sage_patch.addresses import (
    CAMERA_CLIP_PLANES_OFFSET,
    CAMERA_PROJECTION_OFFSET,
    CAMERA_TRANSFORM_OFFSET,
    CAMERA_VIEW_PLANE_OFFSET,
    CAMERA_VIEWPORT_OFFSET,
    THE_TACTICAL_VIEW,
    W3DVIEW_3D_CAMERA_OFFSET,
)
from tests.sage_live.fake_process import FakeProcess

# Rows as read, to four places: a camera with no yaw, tilted 53 degrees down.
LIVE = CameraView(
    transform=(
        (1.0, 0.0, 0.0, 2224.1648),
        (0.0, 0.5948, -0.8039, 1200.916),
        (0.0, 0.8039, 0.5948, 750.1042),
    ),
    view_plane=(-0.4663073, -0.2622979, 0.4663073, 0.2622979),
    near=10.0,
    far=27000.0,
)

GONDOR_FARM = (2269.0, 1935.7, 200.0)
STUD_FARM = (1944.9, 2452.0, 129.9)
FIGHTER = (2219.5, 1868.4, 200.1)


def test_the_eye_and_the_way_it_looks_come_from_the_transform() -> None:
    assert LIVE.eye == (2224.1648, 1200.916, 750.1042)
    x, y, z = LIVE.forward
    assert (x, y, z) == pytest.approx((0.0, 0.8039, -0.5948))
    assert math.degrees(math.asin(-z)) == pytest.approx(36.5, abs=0.1)


@pytest.mark.parametrize(
    ("where", "seen"),
    [(GONDOR_FARM, (0.55, 0.51)), (STUD_FARM, (0.28, 0.16)), (FIGHTER, (0.49, 0.60))],
)
def test_objects_land_where_they_were_on_screen(where, seen) -> None:
    at = LIVE.project(where)
    assert at is not None
    assert at == pytest.approx(seen, abs=0.01)
    assert LIVE.sees(where)


def test_a_point_off_to_the_side_still_projects_but_is_not_seen() -> None:
    """Just off screen is a fraction past the edge, which is what a margin is measured against."""
    beside = (GONDOR_FARM[0] + 700.0, GONDOR_FARM[1], GONDOR_FARM[2])
    at = LIVE.project(beside)
    assert at is not None and at[0] > 1.0
    assert not LIVE.sees(beside)
    assert LIVE.sees(beside, margin=at[0] - 1.0 + 0.01)


def test_a_negative_margin_keeps_to_the_middle_of_the_screen() -> None:
    assert LIVE.sees(STUD_FARM)
    assert not LIVE.sees(STUD_FARM, margin=-0.2)
    assert LIVE.sees(GONDOR_FARM, margin=-0.4)


def test_behind_the_camera_and_past_the_clip_planes_is_nowhere() -> None:
    assert LIVE.project((2224.0, 0.0, 200.0)) is None
    assert LIVE.project((2224.0, 40000.0, 200.0)) is None
    # Closer than the near plane, right in front of the lens.
    eye = LIVE.eye
    assert LIVE.project((eye[0], eye[1] + 3.0, eye[2] - 2.0)) is None


def test_the_footprint_corners_project_back_onto_the_screen_corners() -> None:
    corners = LIVE.ground_footprint(200.0)
    assert len(corners) == 4
    for (x, y), screen in zip(corners, ((0, 0), (1, 0), (1, 1), (0, 1)), strict=True):
        assert LIVE.project((x, y, 200.0)) == pytest.approx(screen, abs=1e-4)


def test_a_tilted_view_is_wider_at_the_top_of_the_screen() -> None:
    (tl, tr, br, bl) = LIVE.ground_footprint(200.0)
    assert tr[0] - tl[0] > br[0] - bl[0]
    assert tl[1] == pytest.approx(tr[1]) and tl[1] > bl[1]


def test_a_corner_above_the_horizon_stops_at_the_far_clip() -> None:
    level = CameraView(
        transform=((1.0, 0.0, 0.0, 0.0), (0.0, 0.0, -1.0, 0.0), (0.0, 1.0, 0.0, 100.0)),
        view_plane=(-0.5, -0.25, 0.5, 0.25),
        near=1.0,
        far=1000.0,
    )
    tl, tr, br, bl = level.ground_footprint(0.0)
    # The top edge looks up, so it runs out to the far clip; the bottom meets the ground at 400.
    assert tl[1] == pytest.approx(1000.0) and tr[1] == pytest.approx(1000.0)
    assert bl[1] == pytest.approx(400.0) and br[1] == pytest.approx(400.0)


def test_an_orthographic_camera_does_not_divide_by_depth() -> None:
    top_down = CameraView(
        transform=((1.0, 0.0, 0.0, 500.0), (0.0, 1.0, 0.0, 500.0), (0.0, 0.0, 1.0, 1000.0)),
        view_plane=(-200.0, -100.0, 200.0, 100.0),
        near=1.0,
        far=5000.0,
        orthographic=True,
    )
    assert top_down.project((500.0, 500.0, 0.0)) == pytest.approx((0.5, 0.5))
    assert top_down.project((300.0, 600.0, 900.0)) == pytest.approx((0.0, 0.0))
    corners = [v for corner in top_down.ground_footprint(0.0) for v in corner]
    assert corners == pytest.approx([300.0, 600.0, 700.0, 600.0, 700.0, 400.0, 300.0, 400.0])


def test_a_viewport_narrower_than_the_screen_maps_into_it() -> None:
    from_the_left = CameraView(
        transform=LIVE.transform,
        view_plane=LIVE.view_plane,
        near=LIVE.near,
        far=LIVE.far,
        viewport=(0.5, 0.0, 1.0, 1.0),
    )
    x, y = LIVE.project(GONDOR_FARM) or (0.0, 0.0)
    assert from_the_left.project(GONDOR_FARM) == pytest.approx((0.5 + x / 2, y))


VIEW = 0x20000000
CAMERA = 0x20010000


def _process(camera: CameraView, projection: int = 0) -> FakeProcess:
    """A process holding `TheTacticalView` and its 3D camera at the documented offsets."""
    proc = FakeProcess()
    proc.u32(THE_TACTICAL_VIEW, VIEW)
    proc.u32(VIEW + W3DVIEW_3D_CAMERA_OFFSET, CAMERA)
    rows = [v for row in camera.transform for v in row]
    proc.write(CAMERA + CAMERA_TRANSFORM_OFFSET, struct.pack("<12f", *rows))
    proc.u32(CAMERA + CAMERA_PROJECTION_OFFSET, projection)
    proc.write(CAMERA + CAMERA_VIEWPORT_OFFSET, struct.pack("<4f", *camera.viewport))
    proc.write(CAMERA + CAMERA_VIEW_PLANE_OFFSET, struct.pack("<4f", *camera.view_plane))
    proc.write(CAMERA + CAMERA_CLIP_PLANES_OFFSET, struct.pack("<2f", camera.near, camera.far))
    return proc


def test_the_backend_reads_the_camera_the_view_draws_through() -> None:
    view = MemoryBackend(_process(LIVE)).read_camera_view()
    assert view is not None
    assert not view.orthographic
    assert view.eye == pytest.approx(LIVE.eye)
    assert view.view_plane == pytest.approx(LIVE.view_plane)
    assert (view.near, view.far) == (LIVE.near, LIVE.far)
    assert view.project(GONDOR_FARM) == pytest.approx((0.55, 0.51), abs=0.01)


def test_a_nonzero_projection_type_reads_as_orthographic() -> None:
    view = MemoryBackend(_process(LIVE, projection=1)).read_camera_view()
    assert view is not None and view.orthographic


def test_no_view_yet_is_no_camera() -> None:
    """The menus and a loading screen have no tactical view, and that is not an error."""
    backend = MemoryBackend(FakeProcess())
    assert backend.read_camera_view() is None
    assert not backend.diagnostics


def test_a_camera_that_does_not_make_sense_is_reported_not_returned() -> None:
    proc = _process(LIVE)
    proc.write(CAMERA + CAMERA_CLIP_PLANES_OFFSET, struct.pack("<2f", 500.0, 10.0))
    backend = MemoryBackend(proc)
    assert backend.read_camera_view() is None
    assert any("does not read as one" in d.message for d in backend.diagnostics)


def test_a_session_asks_its_backend_and_says_none_where_it_cannot() -> None:
    assert Session(MemoryBackend(_process(LIVE))).camera_view() is not None
    assert Session(object()).camera_view() is None  # type: ignore[arg-type]
