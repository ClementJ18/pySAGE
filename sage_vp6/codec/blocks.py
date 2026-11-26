"""Where a frame's 8x8 blocks sit in its planes, in the order the bitstream codes them:
macroblocks in raster order, and within each the four luma blocks (raster order), then U, then V.
"""

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from sage_vp6.tables import BLOCK_PLANE

__all__ = ["BlockLayout"]

type Plane = npt.NDArray[np.uint8]
type IntArray = npt.NDArray[np.int64]

_OFFSETS = np.arange(8)


@dataclass(frozen=True)
class BlockLayout:
    """Plane, left and top of every block of an `mb_rows` x `mb_cols` frame."""

    mb_rows: int
    mb_cols: int
    plane: IntArray
    left: IntArray
    top: IntArray

    @classmethod
    def of(cls, mb_rows: int, mb_cols: int) -> "BlockLayout":
        rows, cols = np.meshgrid(np.arange(mb_rows), np.arange(mb_cols), indexing="ij")
        rows = rows.reshape(-1, 1)
        cols = cols.reshape(-1, 1)
        plane = np.broadcast_to(np.array(BLOCK_PLANE), (rows.size, 6))
        left = np.concatenate([16 * cols + off for off in (0, 8, 0, 8)] + [8 * cols] * 2, axis=1)
        top = np.concatenate([16 * rows + off for off in (0, 0, 8, 8)] + [8 * rows] * 2, axis=1)
        return cls(mb_rows, mb_cols, plane.reshape(-1), left.reshape(-1), top.reshape(-1))

    @property
    def count(self) -> int:
        return int(self.plane.size)

    def _where(self, selected: IntArray) -> tuple[IntArray, IntArray]:
        ys = self.top[selected][:, None, None] + _OFFSETS[None, :, None]
        xs = self.left[selected][:, None, None] + _OFFSETS[None, None, :]
        return ys, xs

    def gather(self, planes: list[Plane], selected: IntArray | None = None) -> IntArray:
        """The pixels of the `selected` blocks (all by default), as int64 8x8 blocks."""
        if selected is None:
            selected = np.arange(self.count)
        out = np.zeros((selected.size, 8, 8), dtype=np.int64)
        for p in range(3):
            mine = np.nonzero(self.plane[selected] == p)[0]
            if mine.size:
                ys, xs = self._where(selected[mine])
                out[mine] = planes[p][ys, xs]
        return out

    def scatter(self, blocks: npt.NDArray[np.integer]) -> list[Plane]:
        """New planes holding every block's pixels."""
        planes = [
            np.zeros((16 * self.mb_rows, 16 * self.mb_cols), dtype=np.uint8),
            np.zeros((8 * self.mb_rows, 8 * self.mb_cols), dtype=np.uint8),
            np.zeros((8 * self.mb_rows, 8 * self.mb_cols), dtype=np.uint8),
        ]
        for p in range(3):
            mine = np.nonzero(self.plane == p)[0]
            ys, xs = self._where(mine)
            planes[p][ys, xs] = blocks[mine]
        return planes
