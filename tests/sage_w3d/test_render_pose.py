"""Data-free tests for `sage_w3d.render.pose`: synthetic `Hierarchy`/`Animation`/
`CompressedAnimation` chunks built the way the rest of `sage_w3d`'s test suite builds them (see
`test_render_scene.py`'s `_pivot`/`_hierarchy` helpers), exercising the delta-composition rule,
parent chaining, every channel kind's sampling, visibility, and the evaluator's diagnostics."""

import math

import pytest

from sage_w3d import adaptive_delta
from sage_w3d.animation import (
    Animation,
    AnimationBitChannel,
    AnimationChannel,
    AnimationHeader,
)
from sage_w3d.binary import FixedString
from sage_w3d.chunks import Version
from sage_w3d.compressed_animation import (
    AdaptiveDeltaAnimationChannel,
    AdaptiveDeltaBlock,
    AdaptiveDeltaData,
    CompressedAnimation,
    CompressedAnimationHeader,
    MotionAdaptiveDeltaData,
    MotionChannel,
    MotionTimeCodedData,
    MotionTimeCodedDatum,
    TimeCodedAnimationChannel,
    TimeCodedBitChannel,
    TimeCodedBitDatum,
    TimeCodedDatum,
)
from sage_w3d.hierarchy import Hierarchy, HierarchyHeader, HierarchyPivot, Pivots
from sage_w3d.render.math3d import IDENTITY, Mat4
from sage_w3d.render.pose import Pose, PoseEvaluator
from sage_w3d.render.scene import _pivot_world_matrices
from sage_w3d.w3d import W3DFile

_SIN45 = math.sqrt(2) / 2
_COS45 = math.sqrt(2) / 2


def _pivot(
    name: str,
    parent_id: int,
    translation: tuple[float, float, float] = (0.0, 0.0, 0.0),
    rotation: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 1.0),
) -> HierarchyPivot:
    return HierarchyPivot(
        name=FixedString.from_value(name, 16),
        parent_id=parent_id,
        translation=translation,
        euler_angles=(0.0, 0.0, 0.0),
        rotation=rotation,
    )


def _hierarchy(name: str, pivots: list[HierarchyPivot]) -> Hierarchy:
    header = HierarchyHeader(
        flagged=False,
        version=Version(4, 1),
        name=FixedString.from_value(name, 16),
        num_pivots=len(pivots),
        center_pos=(0.0, 0.0, 0.0),
    )
    return Hierarchy(flagged=True, chunks=[header, Pivots(False, pivots)])


def _anim_header(
    name: str = "a", hierarchy_name: str = "skel", num_frames: int = 5, frame_rate: int = 30
) -> AnimationHeader:
    return AnimationHeader(
        flagged=False,
        version=Version(4, 1),
        name=FixedString.from_value(name, 16),
        hierarchy_name=FixedString.from_value(hierarchy_name, 16),
        num_frames=num_frames,
        frame_rate=frame_rate,
    )


def _translation_channel(
    pivot: int, values: list[float], first_frame: int = 0, channel_type: int = 1
) -> AnimationChannel:
    return AnimationChannel(
        flagged=False,
        first_frame=first_frame,
        last_frame=first_frame + len(values) - 1,
        vector_len=1,
        channel_type=channel_type,
        pivot=pivot,
        pad=0,
        data=list(values),
        trailing=b"",
    )


def _quat_channel(
    pivot: int, values: list[tuple[float, float, float, float]], first_frame: int = 0
) -> AnimationChannel:
    flat = [c for v in values for c in v]
    return AnimationChannel(
        flagged=False,
        first_frame=first_frame,
        last_frame=first_frame + len(values) - 1,
        vector_len=4,
        channel_type=6,
        pivot=pivot,
        pad=0,
        data=flat,
        trailing=b"",
    )


def _compressed_header(
    flavor: int, hierarchy_name: str = "skel", num_frames: int = 20, frame_rate: int = 30
) -> CompressedAnimationHeader:
    return CompressedAnimationHeader(
        flagged=False,
        version=Version(0, 1),
        name=FixedString.from_value("a", 16),
        hierarchy_name=FixedString.from_value(hierarchy_name, 16),
        num_frames=num_frames,
        frame_rate=frame_rate,
        flavor=flavor,
    )


def _flat(m: Mat4) -> tuple[float, ...]:
    return tuple(v for row in m for v in row)


class TestComposition:
    def test_translation_and_rotation_delta_compose_onto_the_rest_pose(self):
        # Rest: translated (1, 0, 0), unrotated. Anim: translated (0, 1, 0), rotated 90 degrees
        # about Z. world = T(rest_t) . T(anim_t) . R(anim_q); consecutive pure translations add,
        # so the local matrix is a translation by (1, 1, 0) with a 90-degree Z rotation baked in
        # (hand-derived via math3d.quat_to_matrix's own formula).
        hierarchy = _hierarchy("skel", [_pivot("root", -1, translation=(1.0, 0.0, 0.0))])
        header = _anim_header(num_frames=1)
        channel_t = _translation_channel(0, [1.0], channel_type=1)
        channel_q = _quat_channel(0, [(0.0, 0.0, _SIN45, _COS45)])
        animation = Animation(flagged=True, chunks=[header, channel_t, channel_q])

        evaluator = PoseEvaluator(hierarchy, animation)
        pose = evaluator.evaluate(0.0)

        expected: Mat4 = (
            (0.0, -1.0, 0.0, 1.0),
            (1.0, 0.0, 0.0, 1.0),
            (0.0, 0.0, 1.0, 0.0),
            (0.0, 0.0, 0.0, 1.0),
        )
        assert _flat(pose.world_matrices[0]) == pytest.approx(_flat(expected))
        assert evaluator.diagnostics == []

    def test_zero_delta_channel_reproduces_the_rest_matrix_exactly(self):
        hierarchy = _hierarchy(
            "skel", [_pivot("root", -1, translation=(2.0, 3.0, 4.0), rotation=(0.0, 0.0, 0.5, 0.5))]
        )
        header = _anim_header(num_frames=1)
        channel_t = _translation_channel(0, [0.0], channel_type=0)
        channel_q = _quat_channel(0, [(0.0, 0.0, 0.0, 1.0)])
        animation = Animation(flagged=True, chunks=[header, channel_t, channel_q])

        pose = PoseEvaluator(hierarchy, animation).evaluate(0.0)

        rest = _pivot_world_matrices(hierarchy)[0]
        assert pose.world_matrices[0] == rest

    def test_unanimated_pivot_is_bit_identical_to_the_rest_pose_renderer(self):
        hierarchy = _hierarchy(
            "skel",
            [
                _pivot(
                    "root", -1, translation=(1.0, 2.0, 3.0), rotation=(0.0, 0.0, _SIN45, _COS45)
                ),
                _pivot("child", 0, translation=(4.0, 5.0, 6.0)),
            ],
        )
        # An animation with channels for a different, unrelated pivot index only - neither of
        # these two pivots carries a track.
        header = _anim_header(num_frames=1)
        animation = Animation(flagged=True, chunks=[header])

        pose = PoseEvaluator(hierarchy, animation).evaluate(0.0)

        assert pose.world_matrices == _pivot_world_matrices(hierarchy)


class TestParentChaining:
    def test_child_inherits_the_parents_animated_matrix(self):
        hierarchy = _hierarchy(
            "skel", [_pivot("root", -1), _pivot("child", 0, translation=(2.0, 0.0, 0.0))]
        )
        header = _anim_header(num_frames=1)
        # Only the root moves - by (0, 5, 0). The unanimated child's rest translation (2, 0, 0)
        # then adds on top of that in world space (both are pure translations).
        channel = _translation_channel(0, [5.0], channel_type=1)
        animation = Animation(flagged=True, chunks=[header, channel])

        pose = PoseEvaluator(hierarchy, animation).evaluate(0.0)

        root_translation = tuple(row[3] for row in pose.world_matrices[0])[:3]
        child_translation = tuple(row[3] for row in pose.world_matrices[1])[:3]
        assert root_translation == pytest.approx((0.0, 5.0, 0.0))
        assert child_translation == pytest.approx((2.0, 5.0, 0.0))


class TestScalarAndQuatSampling:
    def test_clamps_before_first_and_after_last_key(self):
        hierarchy = _hierarchy("skel", [_pivot("root", -1)])
        header = _anim_header(num_frames=10)
        channel = _translation_channel(0, [10.0, 20.0, 30.0], first_frame=2, channel_type=0)
        animation = Animation(flagged=True, chunks=[header, channel])
        evaluator = PoseEvaluator(hierarchy, animation)

        before = evaluator.evaluate(0.0).world_matrices[0][0][3]
        after = evaluator.evaluate(10.0).world_matrices[0][0][3]
        assert before == pytest.approx(10.0)
        assert after == pytest.approx(30.0)

    def test_scalar_lerp_at_the_midpoint(self):
        hierarchy = _hierarchy("skel", [_pivot("root", -1)])
        header = _anim_header(num_frames=2)
        channel = _translation_channel(0, [0.0, 10.0], channel_type=0)
        animation = Animation(flagged=True, chunks=[header, channel])

        pose = PoseEvaluator(hierarchy, animation).evaluate(0.5)

        assert pose.world_matrices[0][0][3] == pytest.approx(5.0)

    def test_quat_hemisphere_correction_takes_the_short_path(self):
        # b is stored as the negation of a rotation 10 degrees short of `a` (identity) - the same
        # rotation as a quaternion 10 degrees "the other way", per q == -q. Correcting the
        # hemisphere before nlerping recovers the short (-5 degree midpoint) path; the matrix's
        # [0][0] entry (1 - 2*z^2) stays close to +1 on the short path and would flip to roughly
        # -1 on the long (175-degree) path a naive lerp would take instead.
        rot = (0.0, 0.0, math.sin(math.radians(-5.0)), math.cos(math.radians(-5.0)))
        b_stored = tuple(-c for c in rot)
        hierarchy = _hierarchy("skel", [_pivot("root", -1)])
        channel = TimeCodedAnimationChannel(
            flagged=False,
            pivot=0,
            vector_len=4,
            channel_type=6,
            data=[
                TimeCodedDatum(0, False, (0.0, 0.0, 0.0, 1.0)),
                TimeCodedDatum(10, False, b_stored),
            ],
        )
        animation = CompressedAnimation(
            flagged=True, chunks=[_compressed_header(0, num_frames=11), channel]
        )

        pose = PoseEvaluator(hierarchy, animation).evaluate(5.0)

        assert pose.world_matrices[0][0][0] > 0.9

    def test_step_key_holds_the_previous_value_until_its_own_frame(self):
        hierarchy = _hierarchy("skel", [_pivot("root", -1)])
        channel = TimeCodedAnimationChannel(
            flagged=False,
            pivot=0,
            vector_len=1,
            channel_type=0,
            data=[TimeCodedDatum(0, False, 0.0), TimeCodedDatum(4, True, 100.0)],
        )
        animation = CompressedAnimation(
            flagged=True, chunks=[_compressed_header(0, num_frames=5), channel]
        )
        evaluator = PoseEvaluator(hierarchy, animation)

        held = evaluator.evaluate(2.0).world_matrices[0][0][3]
        jumped = evaluator.evaluate(4.0).world_matrices[0][0][3]
        assert held == pytest.approx(0.0)
        assert jumped == pytest.approx(100.0)


class TestVisibility:
    def test_uncompressed_bit_channel_uses_the_default_outside_its_range(self):
        hierarchy = _hierarchy("skel", [_pivot("root", -1)])
        header = _anim_header(num_frames=10)
        # Frames 2-4: True, False, True. default_raw 0 -> default False, used outside [2, 4].
        bit_channel = AnimationBitChannel(
            flagged=False,
            first_frame=2,
            last_frame=4,
            channel_type=15,
            pivot=0,
            default_raw=0,
            bits=bytes([0b101]),
        )
        animation = Animation(flagged=True, chunks=[header, bit_channel])
        evaluator = PoseEvaluator(hierarchy, animation)

        assert evaluator.evaluate(0.0).pivot_visible == [False]
        assert evaluator.evaluate(2.0).pivot_visible == [True]
        assert evaluator.evaluate(3.0).pivot_visible == [False]
        assert evaluator.evaluate(4.0).pivot_visible == [True]
        assert evaluator.evaluate(10.0).pivot_visible == [False]

    def test_time_coded_bit_channel_steps_from_its_default(self):
        hierarchy = _hierarchy("skel", [_pivot("root", -1)])
        bit_channel = TimeCodedBitChannel(
            flagged=False,
            pivot=0,
            channel_type=15,
            default_value=1,
            data=[TimeCodedBitDatum(5, False)],
        )
        animation = CompressedAnimation(
            flagged=True, chunks=[_compressed_header(0, num_frames=10), bit_channel]
        )
        evaluator = PoseEvaluator(hierarchy, animation)

        assert evaluator.evaluate(0.0).pivot_visible == [True]
        assert evaluator.evaluate(5.0).pivot_visible == [False]
        assert evaluator.evaluate(9.0).pivot_visible == [False]

    def test_unanimated_pivot_is_always_visible(self):
        hierarchy = _hierarchy("skel", [_pivot("root", -1)])
        animation = Animation(flagged=True, chunks=[_anim_header(num_frames=1)])

        pose = PoseEvaluator(hierarchy, animation).evaluate(0.0)

        assert pose.pivot_visible == [True]

    def test_float_visibility_channel_thresholds_a_fade_ramp(self):
        # The BFME float visibility channel (type 15): a 0..1 fade-in, visible from the frame
        # the ramp reaches the 0.5 midpoint - including between keys, where sampling lerps.
        hierarchy = _hierarchy("skel", [_pivot("root", -1)])
        channel = _translation_channel(0, [0.0, 0.25, 0.5, 0.75, 1.0], channel_type=15)
        animation = Animation(flagged=True, chunks=[_anim_header(num_frames=5), channel])
        evaluator = PoseEvaluator(hierarchy, animation)

        assert evaluator.diagnostics == []
        assert evaluator.evaluate(0.0).pivot_visible == [False]
        assert evaluator.evaluate(1.5).pivot_visible == [False]  # lerped 0.375
        assert evaluator.evaluate(2.0).pivot_visible == [True]  # exactly the 0.5 midpoint
        assert evaluator.evaluate(4.0).pivot_visible == [True]

    def test_float_visibility_time_coded_negative_switch(self):
        # Real projectile channels store +-1.0 on/off values (e.g. `aubomcat.w3d`); the lerp
        # between +1 and -1 crosses the 0.5 threshold a quarter of the way in.
        hierarchy = _hierarchy("skel", [_pivot("root", -1)])
        channel = TimeCodedAnimationChannel(
            flagged=False,
            pivot=0,
            vector_len=1,
            channel_type=15,
            data=[TimeCodedDatum(0, False, 1.0), TimeCodedDatum(10, False, -1.0)],
        )
        animation = CompressedAnimation(
            flagged=True, chunks=[_compressed_header(0, num_frames=11), channel]
        )
        evaluator = PoseEvaluator(hierarchy, animation)

        assert evaluator.diagnostics == []
        assert evaluator.evaluate(0.0).pivot_visible == [True]
        assert evaluator.evaluate(2.0).pivot_visible == [True]  # lerped 0.6
        assert evaluator.evaluate(3.0).pivot_visible == [False]  # lerped 0.4
        assert evaluator.evaluate(10.0).pivot_visible == [False]

    def test_float_visibility_motion_channel_fades_in(self):
        # The shape `aubomship_a.w3d` ships: a motion channel (type 15, time-coded body)
        # ramping 0 -> 1.
        hierarchy = _hierarchy("skel", [_pivot("root", -1)])
        channel = MotionChannel(
            flagged=True,
            zero_byte=0,
            delta_type=0,
            vector_len=1,
            channel_type=15,
            num_time_codes=2,
            pivot=0,
            body=MotionTimeCodedData(
                data=[MotionTimeCodedDatum(0, 0.0), MotionTimeCodedDatum(4, 1.0)], pad=b""
            ),
        )
        animation = CompressedAnimation(
            flagged=True, chunks=[_compressed_header(0, num_frames=5), channel]
        )
        evaluator = PoseEvaluator(hierarchy, animation)

        assert evaluator.diagnostics == []
        assert evaluator.evaluate(0.0).pivot_visible == [False]
        assert evaluator.evaluate(2.0).pivot_visible == [True]  # lerped 0.5, at the threshold
        assert evaluator.evaluate(4.0).pivot_visible == [True]

    def test_float_visibility_outranks_a_bit_channel_in_either_order(self):
        # Real exporters write both forms for the same pivot (`aubomcat.w3d`,
        # `aubomship_a.w3d`): the float channel wins silently whether it is ingested before
        # the bit channel or after it. Here they deliberately disagree (bit says visible,
        # float says hidden) so the winner is observable.
        bit_channel = AnimationBitChannel(
            flagged=False,
            first_frame=0,
            last_frame=0,
            channel_type=15,
            pivot=0,
            default_raw=255,
            bits=bytes([0b1]),
        )
        float_channel = _translation_channel(0, [0.0], channel_type=15)
        hierarchy = _hierarchy("skel", [_pivot("root", -1)])

        for chunks in (
            [_anim_header(num_frames=1), bit_channel, float_channel],
            [_anim_header(num_frames=1), float_channel, bit_channel],
        ):
            evaluator = PoseEvaluator(hierarchy, Animation(flagged=True, chunks=chunks))
            assert evaluator.diagnostics == []
            assert evaluator.evaluate(0.0).pivot_visible == [False]

    def test_float_visibility_displaces_an_already_stored_bit_channel(self):
        # The compressed shape `aubomship_a.w3d` ships: the bit channel is ingested before the
        # motion channels, so the float channel arrives second and displaces the already-stored
        # bit track (the other half of the outranking rule - the uncompressed test above only
        # exercises the float-first path, since ingestion groups channels before bit channels).
        hierarchy = _hierarchy("skel", [_pivot("root", -1)])
        bit_channel = TimeCodedBitChannel(
            flagged=False,
            pivot=0,
            channel_type=15,
            default_value=1,
            data=[TimeCodedBitDatum(0, True)],
        )
        float_channel = MotionChannel(
            flagged=True,
            zero_byte=0,
            delta_type=0,
            vector_len=1,
            channel_type=15,
            num_time_codes=1,
            pivot=0,
            body=MotionTimeCodedData(data=[MotionTimeCodedDatum(0, 0.0)], pad=b""),
        )
        animation = CompressedAnimation(
            flagged=True, chunks=[_compressed_header(0, num_frames=1), bit_channel, float_channel]
        )
        evaluator = PoseEvaluator(hierarchy, animation)

        assert evaluator.diagnostics == []
        assert evaluator.evaluate(0.0).pivot_visible == [False]

    def test_two_float_visibility_channels_are_a_diagnosed_duplicate(self):
        hierarchy = _hierarchy("skel", [_pivot("root", -1)])
        first = _translation_channel(0, [0.0], channel_type=15)
        second = _translation_channel(0, [1.0], channel_type=15)
        animation = Animation(flagged=True, chunks=[_anim_header(num_frames=1), first, second])
        evaluator = PoseEvaluator(hierarchy, animation)

        assert len(evaluator.diagnostics) == 1
        assert "duplicate visibility.float" in evaluator.diagnostics[0]
        assert evaluator.evaluate(0.0).pivot_visible == [False]  # the first channel won


class TestCompressedChannels:
    def test_time_coded_channel_sparse_keys_interpolate(self):
        hierarchy = _hierarchy("skel", [_pivot("root", -1)])
        channel = TimeCodedAnimationChannel(
            flagged=False,
            pivot=0,
            vector_len=1,
            channel_type=0,
            data=[TimeCodedDatum(0, False, 0.0), TimeCodedDatum(10, False, 100.0)],
        )
        animation = CompressedAnimation(
            flagged=True, chunks=[_compressed_header(0, num_frames=11), channel]
        )

        pose = PoseEvaluator(hierarchy, animation).evaluate(5.0)

        assert pose.world_matrices[0][0][3] == pytest.approx(50.0)

    def test_motion_channel_time_coded_body_interpolates(self):
        hierarchy = _hierarchy("skel", [_pivot("root", -1)])
        channel = MotionChannel(
            flagged=True,
            zero_byte=0,
            delta_type=0,
            vector_len=1,
            channel_type=0,
            num_time_codes=2,
            pivot=0,
            body=MotionTimeCodedData(
                data=[MotionTimeCodedDatum(0, 0.0), MotionTimeCodedDatum(4, 8.0)], pad=b""
            ),
        )
        animation = CompressedAnimation(
            flagged=True, chunks=[_compressed_header(0, num_frames=5), channel]
        )

        pose = PoseEvaluator(hierarchy, animation).evaluate(2.0)

        assert pose.world_matrices[0][0][3] == pytest.approx(4.0)

    def test_adaptive_delta_channel_sampling_matches_encoded_values(self):
        # scale=1.0 with unit deltas (0, 1, 2, 3) hits DELTA_TABLE's index 8 (== 10**0 == 1.0)
        # exactly, so encode()'s search finds a delta_scale that reconstructs these particular
        # values with zero quantization error - a clean way to exercise the encode -> channel ->
        # PoseEvaluator wiring without fighting the codec's lossiness for the assertion itself.
        values = [0.0, 1.0, 2.0, 3.0]
        initial_value, blocks = adaptive_delta.encode(0, 1, 1.0, values)
        hierarchy = _hierarchy("skel", [_pivot("root", -1)])
        channel = AdaptiveDeltaAnimationChannel(
            flagged=False,
            num_time_codes=len(values),
            pivot=0,
            vector_len=1,
            channel_type=0,
            scale=1.0,
            data=AdaptiveDeltaData(
                initial_value=initial_value,
                delta_blocks=[AdaptiveDeltaBlock(idx, data) for idx, data in blocks],
            ),
            padding=b"\x00\x00\x00",
        )
        animation = CompressedAnimation(
            flagged=True, chunks=[_compressed_header(1, num_frames=len(values)), channel]
        )
        evaluator = PoseEvaluator(hierarchy, animation)

        for frame, expected in enumerate(values):
            got = evaluator.evaluate(float(frame)).world_matrices[0][0][3]
            assert got == pytest.approx(expected, abs=1e-4)

    def test_motion_channel_adaptive_body_sampling_matches_encoded_values(self):
        values = [0.0, 1.0, 2.0, 3.0]
        initial_value, blocks = adaptive_delta.encode(0, 1, 1.0, values, bit_count=4)
        hierarchy = _hierarchy("skel", [_pivot("root", -1)])
        channel = MotionChannel(
            flagged=True,
            zero_byte=0,
            delta_type=1,  # bit_count = delta_type * 4 == 4
            vector_len=1,
            channel_type=0,
            num_time_codes=len(values),
            pivot=0,
            body=MotionAdaptiveDeltaData(
                scale=1.0,
                data=AdaptiveDeltaData(
                    initial_value=initial_value,
                    delta_blocks=[AdaptiveDeltaBlock(idx, data) for idx, data in blocks],
                ),
            ),
        )
        animation = CompressedAnimation(
            flagged=True, chunks=[_compressed_header(0, num_frames=len(values)), channel]
        )
        evaluator = PoseEvaluator(hierarchy, animation)

        for frame, expected in enumerate(values):
            got = evaluator.evaluate(float(frame)).world_matrices[0][0][3]
            assert got == pytest.approx(expected, abs=1e-4)


class TestDiagnostics:
    def test_pivot_out_of_range_is_diagnosed_and_skipped(self):
        hierarchy = _hierarchy("skel", [_pivot("root", -1)])
        header = _anim_header(num_frames=1)
        channel = _translation_channel(99, [1.0], channel_type=0)
        animation = Animation(flagged=True, chunks=[header, channel])

        evaluator = PoseEvaluator(hierarchy, animation)
        pose = evaluator.evaluate(0.0)

        assert any("out of range" in d for d in evaluator.diagnostics)
        assert pose.world_matrices == _pivot_world_matrices(hierarchy)

    def test_euler_channel_type_is_diagnosed_and_skipped(self):
        hierarchy = _hierarchy("skel", [_pivot("root", -1)])
        header = _anim_header(num_frames=1)
        channel = _translation_channel(0, [1.0], channel_type=3)
        animation = Animation(flagged=True, chunks=[header, channel])

        evaluator = PoseEvaluator(hierarchy, animation)

        assert any("not supported" in d for d in evaluator.diagnostics)
        assert evaluator.evaluate(0.0).world_matrices == _pivot_world_matrices(hierarchy)

    def test_hierarchy_name_mismatch_is_diagnosed_but_evaluation_proceeds(self):
        hierarchy = _hierarchy("skel", [_pivot("root", -1)])
        header = _anim_header(hierarchy_name="other_skeleton", num_frames=1)
        animation = Animation(flagged=True, chunks=[header])

        evaluator = PoseEvaluator(hierarchy, animation)

        assert any("does not match" in d for d in evaluator.diagnostics)
        assert evaluator.evaluate(0.0).world_matrices == _pivot_world_matrices(hierarchy)

    def test_duplicate_channel_is_diagnosed_and_the_first_wins(self):
        hierarchy = _hierarchy("skel", [_pivot("root", -1)])
        header = _anim_header(num_frames=1)
        first = _translation_channel(0, [1.0], channel_type=0)
        second = _translation_channel(0, [99.0], channel_type=0)
        animation = Animation(flagged=True, chunks=[header, first, second])

        evaluator = PoseEvaluator(hierarchy, animation)
        pose = evaluator.evaluate(0.0)

        assert any("duplicate" in d for d in evaluator.diagnostics)
        assert pose.world_matrices[0][0][3] == pytest.approx(1.0)


class TestHeaderProperties:
    def test_name_frames_and_rate_come_from_the_header(self):
        hierarchy = _hierarchy("skel", [_pivot("root", -1)])
        header = _anim_header(name="walk", num_frames=42, frame_rate=24)
        animation = Animation(flagged=True, chunks=[header])

        evaluator = PoseEvaluator(hierarchy, animation)

        assert evaluator.name == "walk"
        assert evaluator.num_frames == 42
        assert evaluator.frame_rate == pytest.approx(24.0)

    def test_header_less_animation_is_diagnosed_and_defaults(self):
        hierarchy = _hierarchy("skel", [_pivot("root", -1)])
        animation = Animation(flagged=True, chunks=[])

        evaluator = PoseEvaluator(hierarchy, animation)

        assert evaluator.name == ""
        assert evaluator.num_frames == 0
        assert evaluator.frame_rate == 0.0
        assert any("no header" in d for d in evaluator.diagnostics)


class TestW3DFilePluralProperties:
    def test_animations_and_compressed_animations_return_every_chunk(self):
        anim_a = Animation(flagged=True, chunks=[_anim_header(name="a")])
        anim_b = Animation(flagged=True, chunks=[_anim_header(name="b")])
        compressed = CompressedAnimation(flagged=True, chunks=[_compressed_header(0)])
        w3d = W3DFile(chunks=[anim_a, anim_b, compressed])

        assert w3d.animations == [anim_a, anim_b]
        assert w3d.compressed_animations == [compressed]
        assert w3d.animation is anim_a
        assert w3d.compressed_animation is compressed


def test_pose_dataclass_fields():
    pose = Pose(world_matrices=[IDENTITY], pivot_visible=[True])
    assert pose.world_matrices == [IDENTITY]
    assert pose.pivot_visible == [True]
