"""Data-free unit tests for `sage_w3d.render.math3d`: quaternion-to-matrix against hand-computed
90-degree rotations, translate-then-rotate compose order, point-vs-direction transforms, and
weighted matrix blending."""

import math

import pytest

from sage_w3d.render.math3d import (
    IDENTITY,
    blend_matrices,
    multiply,
    normalize,
    pivot_local_matrix,
    quat_to_matrix,
    transform_direction,
    transform_point,
    translation_matrix,
)

_SIN45 = math.sqrt(2) / 2
_COS45 = math.sqrt(2) / 2


class TestQuatToMatrix:
    def test_90_degrees_about_x(self):
        # Standard Rx(90): (0, 1, 0) rotates to (0, 0, 1).
        m = quat_to_matrix(_SIN45, 0.0, 0.0, _COS45)
        assert transform_point(m, (0.0, 1.0, 0.0)) == pytest.approx((0.0, 0.0, 1.0))

    def test_90_degrees_about_y(self):
        # Standard Ry(90): (1, 0, 0) rotates to (0, 0, -1).
        m = quat_to_matrix(0.0, _SIN45, 0.0, _COS45)
        assert transform_point(m, (1.0, 0.0, 0.0)) == pytest.approx((0.0, 0.0, -1.0))

    def test_90_degrees_about_z(self):
        # Standard Rz(90): (1, 0, 0) rotates to (0, 1, 0).
        m = quat_to_matrix(0.0, 0.0, _SIN45, _COS45)
        assert transform_point(m, (1.0, 0.0, 0.0)) == pytest.approx((0.0, 1.0, 0.0))

    def test_identity_quaternion_is_identity_matrix(self):
        assert quat_to_matrix(0.0, 0.0, 0.0, 1.0) == IDENTITY


class TestComposeOrder:
    def test_pivot_local_matrix_rotates_before_translating(self):
        # Rotate (1, 0, 0) 90 degrees about Z first -> (0, 1, 0), then translate by (1, 0, 0)
        # -> (1, 1, 0). Translating first (the wrong order) would give (0, 2, 0) instead.
        m = pivot_local_matrix((1.0, 0.0, 0.0), (0.0, 0.0, _SIN45, _COS45))
        assert transform_point(m, (1.0, 0.0, 0.0)) == pytest.approx((1.0, 1.0, 0.0))

    def test_multiply_applies_the_right_operand_first(self):
        rotate = quat_to_matrix(0.0, 0.0, _SIN45, _COS45)
        translate = translation_matrix(1.0, 0.0, 0.0)
        combined = multiply(rotate, translate)
        point = (1.0, 0.0, 0.0)
        direct = transform_point(rotate, transform_point(translate, point))
        assert transform_point(combined, point) == pytest.approx(direct)


class TestPointVsDirection:
    def test_transform_point_includes_translation(self):
        m = translation_matrix(5.0, 5.0, 5.0)
        assert transform_point(m, (1.0, 0.0, 0.0)) == (6.0, 5.0, 5.0)

    def test_transform_direction_ignores_translation(self):
        m = translation_matrix(5.0, 5.0, 5.0)
        assert transform_direction(m, (1.0, 0.0, 0.0)) == (1.0, 0.0, 0.0)

    def test_transform_direction_still_rotates(self):
        m = quat_to_matrix(0.0, 0.0, _SIN45, _COS45)
        assert transform_direction(m, (1.0, 0.0, 0.0)) == pytest.approx((0.0, 1.0, 0.0))


class TestNormalize:
    def test_scales_to_unit_length(self):
        assert normalize((3.0, 4.0, 0.0)) == (0.6, 0.8, 0.0)

    def test_zero_vector_is_returned_unchanged(self):
        assert normalize((0.0, 0.0, 0.0)) == (0.0, 0.0, 0.0)


class TestBlendMatrices:
    def test_weighted_average_of_two_translations(self):
        a = translation_matrix(2.0, 0.0, 0.0)
        b = translation_matrix(0.0, 2.0, 0.0)
        blended = blend_matrices([(a, 0.5), (b, 0.5)])
        assert transform_point(blended, (0.0, 0.0, 0.0)) == (1.0, 1.0, 0.0)

    def test_single_full_weight_matrix_is_unchanged(self):
        a = translation_matrix(3.0, 0.0, 0.0)
        blended = blend_matrices([(a, 1.0)])
        assert blended == a
