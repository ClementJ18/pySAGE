"""The 8x8 transforms, vectorised over a stack of blocks.

`inverse_dct` is the decoder's integer transform, exact to the bit: the encoder runs it too, so
that its reference frames are the ones a decoder rebuilds. `forward_dct` is the encoder's float
analysis transform, scaled so that `inverse_dct(4 * forward_dct(x))` gives back `x`.

Blocks are indexed `[..., vertical frequency, horizontal frequency]` for coefficients and
`[..., y, x]` for pixels.
"""

import numpy as np
import numpy.typing as npt

__all__ = ["block_residuals", "forward_dct", "inverse_dct"]

_C1 = 64277
_C2 = 60547
_C3 = 54491
_C4 = 46341
_C5 = 36410
_C6 = 25080
_C7 = 12785

type IntArray = npt.NDArray[np.int64]


def _mul(constant: int, value: IntArray) -> IntArray:
    # The reference multiplies in unsigned 32-bit arithmetic, then shifts the result as signed.
    product = (value * constant + 0x80000000) & 0xFFFFFFFF
    return (product - 0x80000000) >> 16


def _wrap16(value: IntArray) -> IntArray:
    return ((value + 0x8000) & 0xFFFF) - 0x8000


def _idct_1d(ip: IntArray, rounding: int) -> list[IntArray]:
    """One pass over the last axis; returns the eight outputs before the final shift."""
    i0, i1, i2, i3, i4, i5, i6, i7 = (ip[..., k] for k in range(8))
    a = _mul(_C1, i1) + _mul(_C7, i7)
    b = _mul(_C7, i1) - _mul(_C1, i7)
    c = _mul(_C3, i3) + _mul(_C5, i5)
    d = _mul(_C3, i5) - _mul(_C5, i3)
    ad = _mul(_C4, a - c)
    bd = _mul(_C4, b - d)
    cd = a + c
    dd = b + d
    e = _mul(_C4, i0 + i4) + rounding
    f = _mul(_C4, i0 - i4) + rounding
    g = _mul(_C2, i2) + _mul(_C6, i6)
    h = _mul(_C6, i2) - _mul(_C2, i6)
    ed = e - g
    gd = e + g
    add = f + ad
    bdd = bd - h
    fd = f - ad
    hd = bd + h
    return [gd + cd, add + hd, add - hd, ed + dd, ed - dd, fd + bdd, fd - bdd, gd - cd]


def inverse_dct(coefficients: npt.NDArray[np.integer]) -> IntArray:
    """The residual each block adds to its prediction (intra blocks add it to 128)."""
    block = _wrap16(coefficients.astype(np.int64))
    # Horizontal pass: each row of frequencies becomes a row of spatial values, kept as int16.
    rows = _wrap16(np.stack(_idct_1d(block, 0), axis=-1))
    # Vertical pass, over each column.
    columns = np.swapaxes(rows, -1, -2)
    out = np.stack(_idct_1d(columns, 8), axis=-1) >> 4
    return np.swapaxes(out, -1, -2)


def dc_only_residual(dc: npt.NDArray[np.integer]) -> IntArray:
    """The residual of an inter block whose only coefficient is its DC: the decoder's shortcut,
    which rounds differently from the full transform."""
    return (dc.astype(np.int64) + 15) >> 5


def block_residuals(
    coefficients: npt.NDArray[np.integer],
    selectors: npt.NDArray[np.integer],
    intra: npt.NDArray[np.bool_],
) -> IntArray:
    """Every block's residual, through the transform the decoder picks by the block's IDCT
    selector (the furthest scan position its coefficients reach). A selector of 2-10 takes the
    reduced transform, which reads only the top-left 4x4 coefficients - in a VP6.0 stream a
    selector of 10 can still carry a coefficient outside it, and the decoder drops it. An inter
    block with a selector of 1 or less takes the DC shortcut."""
    reduced = (selectors >= 2) & (selectors <= 10)
    if reduced.any():
        coefficients = coefficients.copy()
        corner = np.zeros((8, 8), dtype=bool)
        corner[:4, :4] = True
        coefficients[reduced] *= corner
    residual = inverse_dct(coefficients)
    dc_only = ~intra & (selectors <= 1)
    if dc_only.any():
        residual[dc_only] = dc_only_residual(coefficients[dc_only, 0, 0])[:, None, None]
    return residual


def _basis() -> npt.NDArray[np.float64]:
    k = np.arange(8)[:, None]
    n = np.arange(8)[None, :]
    basis = np.cos((2 * n + 1) * k * np.pi / 16) * np.sqrt(2 / 8)
    basis[0] /= np.sqrt(2)
    return basis


_BASIS = _basis()


def forward_dct(pixels: npt.NDArray[np.number]) -> npt.NDArray[np.float64]:
    """The coefficients whose dequantized values (times 4) rebuild `pixels`."""
    values = pixels.astype(np.float64)
    return np.einsum("vy,...yx,ux->...vu", _BASIS, values, _BASIS)
