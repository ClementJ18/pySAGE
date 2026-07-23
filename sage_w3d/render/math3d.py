"""Stdlib 4x4 transform math for W3D scene assembly: quaternion-to-matrix, matrix composition,
and point/direction transforms. A pivot's rest-pose world matrix is translation-then-rotation
composed up the parent chain (`pivot_local_matrix` + `multiply`); a skinned vertex blends 1-2
such matrices by its influence weights (`blend_matrices`). Matrices are plain tuples of four
row-tuples - immutable and hashable - so this module stays stdlib-only, no numpy, matching the
rest of the `sage_w3d` core."""

import math

__all__ = [
    "IDENTITY",
    "Mat4",
    "Vec3",
    "blend_matrices",
    "multiply",
    "normalize",
    "pivot_local_matrix",
    "quat_to_matrix",
    "transform_direction",
    "transform_point",
    "translation_matrix",
]

Vec3 = tuple[float, float, float]
Mat4 = tuple[
    tuple[float, float, float, float],
    tuple[float, float, float, float],
    tuple[float, float, float, float],
    tuple[float, float, float, float],
]

IDENTITY: Mat4 = (
    (1.0, 0.0, 0.0, 0.0),
    (0.0, 1.0, 0.0, 0.0),
    (0.0, 0.0, 1.0, 0.0),
    (0.0, 0.0, 0.0, 1.0),
)


def quat_to_matrix(x: float, y: float, z: float, w: float) -> Mat4:
    """The rotation matrix for quaternion `(x, y, z, w)` - the standard row-major expansion,
    embedded in an otherwise-identity 4x4 so it composes directly with a translation matrix."""
    return (
        (1 - 2 * y * y - 2 * z * z, 2 * x * y - 2 * z * w, 2 * x * z + 2 * y * w, 0.0),
        (2 * x * y + 2 * z * w, 1 - 2 * x * x - 2 * z * z, 2 * y * z - 2 * x * w, 0.0),
        (2 * x * z - 2 * y * w, 2 * y * z + 2 * x * w, 1 - 2 * x * x - 2 * y * y, 0.0),
        (0.0, 0.0, 0.0, 1.0),
    )


def translation_matrix(tx: float, ty: float, tz: float) -> Mat4:
    return (
        (1.0, 0.0, 0.0, tx),
        (0.0, 1.0, 0.0, ty),
        (0.0, 0.0, 1.0, tz),
        (0.0, 0.0, 0.0, 1.0),
    )


def multiply(a: Mat4, b: Mat4) -> Mat4:
    """`a @ b` - applying the result to a point applies `b` first, then `a`."""

    def entry(i: int, j: int) -> float:
        return a[i][0] * b[0][j] + a[i][1] * b[1][j] + a[i][2] * b[2][j] + a[i][3] * b[3][j]

    return (
        (entry(0, 0), entry(0, 1), entry(0, 2), entry(0, 3)),
        (entry(1, 0), entry(1, 1), entry(1, 2), entry(1, 3)),
        (entry(2, 0), entry(2, 1), entry(2, 2), entry(2, 3)),
        (entry(3, 0), entry(3, 1), entry(3, 2), entry(3, 3)),
    )


def pivot_local_matrix(translation: Vec3, rotation: tuple[float, float, float, float]) -> Mat4:
    """A pivot's local rest-pose transform: the quaternion rotation applies to a point first,
    then the translation - the on-disk translation + quaternion pair, composed."""
    return multiply(translation_matrix(*translation), quat_to_matrix(*rotation))


def transform_point(m: Mat4, p: Vec3) -> Vec3:
    x, y, z = p
    return (
        m[0][0] * x + m[0][1] * y + m[0][2] * z + m[0][3],
        m[1][0] * x + m[1][1] * y + m[1][2] * z + m[1][3],
        m[2][0] * x + m[2][1] * y + m[2][2] * z + m[2][3],
    )


def transform_direction(m: Mat4, d: Vec3) -> Vec3:
    """Like `transform_point`, but drops the translation column - the correct transform for a
    normal (or any other direction vector), which has no position to translate."""
    x, y, z = d
    return (
        m[0][0] * x + m[0][1] * y + m[0][2] * z,
        m[1][0] * x + m[1][1] * y + m[1][2] * z,
        m[2][0] * x + m[2][1] * y + m[2][2] * z,
    )


def normalize(v: Vec3) -> Vec3:
    """`v` scaled to unit length; a zero vector is returned unchanged (nothing sane to divide
    by) rather than raising - callers see it stay zero and can decide what that means."""
    x, y, z = v
    length = math.sqrt(x * x + y * y + z * z)
    if length == 0.0:
        return v
    return (x / length, y / length, z / length)


def blend_matrices(weighted: list[tuple[Mat4, float]]) -> Mat4:
    """The weighted elementwise sum of one or more 4x4 matrices - linear blend skinning's
    combination step for a vertex with more than one bone influence. Callers normalize the
    weights beforehand (they must sum to 1) since the on-disk weight scale is not uniform
    across files (see `scene.py`)."""
    sums = [[0.0, 0.0, 0.0, 0.0] for _ in range(4)]
    for m, weight in weighted:
        for i in range(4):
            row = m[i]
            sums[i][0] += row[0] * weight
            sums[i][1] += row[1] * weight
            sums[i][2] += row[2] * weight
            sums[i][3] += row[3] * weight
    return (
        (sums[0][0], sums[0][1], sums[0][2], sums[0][3]),
        (sums[1][0], sums[1][1], sums[1][2], sums[1][3]),
        (sums[2][0], sums[2][1], sums[2][2], sums[2][3]),
        (sums[3][0], sums[3][1], sums[3][2], sums[3][3]),
    )
