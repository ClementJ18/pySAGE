"""The adaptive state a VP6 stream carries from frame to frame, and the per-frame prediction
state of its macroblocks: what the decoder and encoder must agree on bit for bit.

`Model` holds the probabilities (reset by every keyframe, partly updated by every frame's
header), `MbType`/`REFERENCE_FRAME` name the macroblock coding modes, and `BlockContext` tracks
the neighbour state that DC prediction and the coefficient contexts read while a frame is coded
macroblock by macroblock.
"""

from enum import IntEnum

from sage_vp6.tables import (
    BLOCK_LEFT_SLOT,
    BLOCK_PLANE,
    DCCV_LC,
    DEF_COEFF_REORDER,
    DEF_FDV_VECTOR_MODEL,
    DEF_MB_TYPES_STATS,
    DEF_PDV_VECTOR_MODEL,
    DEF_RUNV_COEFF_MODEL,
    ZIGZAG,
)

__all__ = ["REFERENCE_FRAME", "BlockContext", "MbType", "Model", "RefFrame", "wrap16"]


class RefFrame(IntEnum):
    NONE = -1
    CURRENT = 0
    PREVIOUS = 1
    GOLDEN = 2


class MbType(IntEnum):
    INTER_NOVEC_PF = 0
    INTRA = 1
    INTER_DELTA_PF = 2
    INTER_V1_PF = 3
    INTER_V2_PF = 4
    INTER_NOVEC_GF = 5
    INTER_DELTA_GF = 6
    INTER_4V = 7
    INTER_V1_GF = 8
    INTER_V2_GF = 9


REFERENCE_FRAME = (
    RefFrame.PREVIOUS,
    RefFrame.CURRENT,
    RefFrame.PREVIOUS,
    RefFrame.PREVIOUS,
    RefFrame.PREVIOUS,
    RefFrame.GOLDEN,
    RefFrame.GOLDEN,
    RefFrame.PREVIOUS,
    RefFrame.GOLDEN,
    RefFrame.GOLDEN,
)


def wrap16(value: int) -> int:
    """`value` stored into an int16, as the reference decoder's coefficient arrays do."""
    return ((value + 0x8000) & 0xFFFF) - 0x8000


def _clip(value: int, low: int, high: int) -> int:
    return low if value < low else high if value > high else value


class Model:
    """The probabilities of one VP6 stream. Coefficient models index `[plane_type]` (0 luma, 1
    chroma), then `[code_type]` (what the previous token was: 0 zero run, 1 a one, 2 larger),
    then `[coefficient_group]`, then the tree node."""

    def __init__(self) -> None:
        self.vector_dct = [0, 0]
        self.vector_sig = [0, 0]
        self.vector_pdv = [[0] * 7 for _ in range(2)]
        self.vector_fdv = [[0] * 8 for _ in range(2)]
        self.mb_types_stats = [[[0, 0] for _ in range(10)] for _ in range(3)]
        self.mb_type = [[[0] * 10 for _ in range(10)] for _ in range(3)]
        self.coeff_reorder = [0] * 64
        self.coeff_index_to_pos = [0] * 64
        self.coeff_index_to_idct_selector = [0] * 64
        self.coeff_dccv = [[0] * 11 for _ in range(2)]
        self.coeff_dcct = [[[0] * 5 for _ in range(3)] for _ in range(2)]
        self.coeff_runv = [[0] * 14 for _ in range(2)]
        self.coeff_ract = [[[[0] * 11 for _ in range(6)] for _ in range(3)] for _ in range(2)]

    def reset(self, sub_version: int) -> None:
        """The defaults a keyframe starts from (its coefficient models come from its header)."""
        self.vector_dct = [0xA2, 0xA4]
        self.vector_sig = [0x80, 0x80]
        self.mb_types_stats = [[list(pair) for pair in ctx] for ctx in DEF_MB_TYPES_STATS]
        self.vector_fdv = [list(row) for row in DEF_FDV_VECTOR_MODEL]
        self.vector_pdv = [list(row) for row in DEF_PDV_VECTOR_MODEL]
        self.coeff_runv = [list(row) for row in DEF_RUNV_COEFF_MODEL]
        self.coeff_reorder = list(DEF_COEFF_REORDER)
        self.init_coeff_order(sub_version)

    def init_coeff_order(self, sub_version: int) -> None:
        """Rebuild the coefficient scan from `coeff_reorder`: positions are taken band by band."""
        index_to_pos = [0]
        for band in range(16):
            index_to_pos += [pos for pos in range(1, 64) if self.coeff_reorder[pos] == band]
        self.coeff_index_to_pos = index_to_pos[:64] + [0] * (64 - len(index_to_pos))
        bump = 1 if sub_version > 6 else 0
        highest = 0
        for index in range(64):
            highest = max(highest, self.coeff_index_to_pos[index])
            self.coeff_index_to_idct_selector[index] = highest + bump

    @property
    def scan(self) -> list[int]:
        """Coefficient index -> raster index (vertical frequency * 8 + horizontal)."""
        return [ZIGZAG[pos] for pos in self.coeff_index_to_pos]

    def compute_dcct(self) -> None:
        """The DC models of each neighbour context, derived from the DC model."""
        for pt in range(2):
            for ctx in range(3):
                for node in range(5):
                    weight, offset = DCCV_LC[ctx][node]
                    value = ((self.coeff_dccv[pt][node] * weight + 128) >> 8) + offset
                    self.coeff_dcct[pt][ctx][node] = _clip(value, 1, 255)

    def compute_mb_type_probs(self) -> None:
        """The macroblock-type tree probabilities, from the type statistics."""
        for ctx in range(3):
            stats = self.mb_types_stats[ctx]
            weights = [100 * stats[t][1] for t in range(10)]
            for mb_type in range(10):
                same, other = stats[mb_type]
                probs = self.mb_type[ctx][mb_type]
                probs[0] = 255 - (255 * same) // (1 + same + other)
                p = list(weights)
                p[mb_type] = 0
                p02 = p[0] + p[2]
                p34 = p[3] + p[4]
                p0234 = p02 + p34
                p17 = p[1] + p[7]
                p56 = p[5] + p[6]
                p89 = p[8] + p[9]
                p5689 = p56 + p89
                p156789 = p17 + p5689
                probs[1] = 1 + 255 * p0234 // (1 + p0234 + p156789)
                probs[2] = 1 + 255 * p02 // (1 + p0234)
                probs[3] = 1 + 255 * p17 // (1 + p156789)
                probs[4] = 1 + 255 * p[0] // (1 + p02)
                probs[5] = 1 + 255 * p[3] // (1 + p34)
                probs[6] = 1 + 255 * p[1] // (1 + p17)
                probs[7] = 1 + 255 * p56 // (1 + p5689)
                probs[8] = 1 + 255 * p[5] // (1 + p56)
                probs[9] = 1 + 255 * p[8] // (1 + p89)


class BlockContext:
    """Neighbour state for one frame: the DC values that predict each block's DC, and whether
    each neighbour's coded DC was non-zero (the context of the DC token).

    Blocks are numbered 0-3 (luma, raster order in the macroblock), 4 (U) and 5 (V). Call
    `start_row` before each macroblock row and `next_macroblock` after each macroblock.
    """

    def __init__(self, mb_width: int) -> None:
        size = 4 * mb_width + 6
        self.mb_width = mb_width
        self.above_ref = [int(RefFrame.NONE)] * size
        self.above_dc = [0] * size
        self.above_nn = [0] * size
        self.above_ref[2 * mb_width + 2] = RefFrame.CURRENT
        self.above_ref[3 * mb_width + 4] = RefFrame.CURRENT
        self.left_ref = [int(RefFrame.NONE)] * 4
        self.left_dc = [0] * 4
        self.left_nn = [0] * 4
        self.above_index = [0] * 6
        # [plane][reference frame]
        self.prev_dc = [[0] * 3 for _ in range(3)]
        self.prev_dc[1][RefFrame.CURRENT] = 128
        self.prev_dc[2][RefFrame.CURRENT] = 128

    def start_row(self) -> None:
        self.left_ref = [int(RefFrame.NONE)] * 4
        self.left_dc = [0] * 4
        self.left_nn = [0] * 4
        width = self.mb_width
        self.above_index = [1, 2, 1, 2, 2 * width + 3, 3 * width + 5]

    def next_macroblock(self) -> None:
        index = self.above_index
        for block in range(4):
            index[block] += 2
        index[4] += 1
        index[5] += 1

    def token_context(self, block: int) -> int:
        """0-2: how many of the block's left and above neighbours coded a non-zero DC."""
        return self.left_nn[BLOCK_LEFT_SLOT[block]] + self.above_nn[self.above_index[block]]

    def set_coded_dc(self, block: int, nonzero: bool) -> None:
        flag = 1 if nonzero else 0
        self.left_nn[BLOCK_LEFT_SLOT[block]] = flag
        self.above_nn[self.above_index[block]] = flag

    def predict_dc(self, block: int, ref: int) -> int:
        """The DC predicted for `block` from neighbours coded against the same reference."""
        above = self.above_index[block]
        left = BLOCK_LEFT_SLOT[block]
        count = 0
        dc = 0
        if self.left_ref[left] == ref:
            dc += self.left_dc[left]
            count += 1
        if self.above_ref[above] == ref:
            dc += self.above_dc[above]
            count += 1
        if count == 0:
            return self.prev_dc[BLOCK_PLANE[block]][ref]
        if count == 2:
            # C division: rounds toward zero.
            return -(-dc // 2) if dc < 0 else dc // 2
        return dc

    def store_dc(self, block: int, ref: int, dc: int) -> None:
        """Record `block`'s final (predicted plus coded) DC as its neighbours will see it."""
        dc = wrap16(dc)
        above = self.above_index[block]
        left = BLOCK_LEFT_SLOT[block]
        self.prev_dc[BLOCK_PLANE[block]][ref] = dc
        self.above_dc[above] = dc
        self.above_ref[above] = ref
        self.left_dc[left] = dc
        self.left_ref[left] = ref
