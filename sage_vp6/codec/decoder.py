"""A VP6 decoder: one frame payload in, one picture out.

The bitstream is entropy-decoded macroblock by macroblock in Python; the transforms and the
whole-pixel predictions then run over the frame's blocks at once in numpy. Coefficients may be
range-coded or Huffman-coded; interlaced frames are rejected, as no BFME movie uses them.
"""

import numpy as np
import numpy.typing as npt

from sage_vp6.codec.blocks import BlockLayout
from sage_vp6.codec.dct import block_residuals
from sage_vp6.codec.frames import YuvFrame, from_coded
from sage_vp6.codec.motion import MotionFilter, predict_block
from sage_vp6.container import Vp6FormatError, parse_frame_header
from sage_vp6.huffman import BitReader, HuffmanTable, build_table
from sage_vp6.model import REFERENCE_FRAME, BlockContext, MbType, Model, RefFrame, wrap16
from sage_vp6.rangecoder import BoolDecoder
from sage_vp6.tables import (
    AC_DEQUANT,
    CANDIDATE_PREDICTOR_POS,
    COEFF_BIAS,
    COEFF_BIT_LENGTH,
    COEFF_GROUPS,
    COEFF_PARSE_TABLE,
    COEFF_REORDER_PCT,
    COORD_DIV,
    DC_DEQUANT,
    DCCV_PCT,
    FDV_PCT,
    HUFF_COEFF_MAP,
    HUFF_RUN_MAP,
    MB_TYPE_MODEL_MODEL,
    PC_TREE,
    PCR_TREE,
    PDV_PCT,
    PMBT_TREE,
    PMBTM_TREE,
    PRE_DEF_MB_TYPE_STATS,
    PVA_TREE,
    RACT_PCT,
    RUNV_PCT,
    SIG_DCT_PCT,
)

__all__ = ["Decoder", "UnsupportedStreamError"]

type Plane = npt.NDArray[np.uint8]
type Vector = tuple[int, int]

_ZERO: Vector = (0, 0)
_LONG_VECTOR_ORDER = (0, 1, 2, 7, 6, 5, 4)


class UnsupportedStreamError(Vp6FormatError):
    """A valid VP6 feature this decoder does not implement."""


def _null_run_length(bits: BitReader) -> int:
    """How many following blocks share a zero DC or an empty AC, in VP6's short code."""
    value = bits.read_bits(2)
    if value == 2:
        value += bits.read_bits(2)
    elif value == 3:
        extra = bits.read_bit() << 2
        value = 6 + extra + bits.read_bits(2 + extra)
    return value


def _rshift_round(value: int, shift: int) -> int:
    half = (1 << shift) >> 1
    return (value + half) >> shift if value > 0 else (value + half - 1) >> shift


class Decoder:
    """Decodes the frames of one VP6 stream in order. `flip` is for EA movies, which code their
    picture bottom-up; `width` and `height` crop the coded picture to the displayed one."""

    def __init__(self, width: int, height: int, flip: bool = True) -> None:
        self.width = width
        self.height = height
        self.flip = flip
        self.model = Model()
        self.sub_version = 0
        self.filter_header = 0
        self.mb_rows = 0
        self.mb_cols = 0
        self.previous: list[Plane] | None = None
        self.golden: list[Plane] | None = None
        self.motion = MotionFilter()
        self._mb_types: list[int] = []
        self._mb_vectors: list[Vector] = []
        self._mb_type = MbType.INTER_NOVEC_PF
        self._candidates: list[Vector] = [_ZERO, _ZERO]
        self._candidate_pos = 0

    def decode(self, payload: bytes) -> YuvFrame:
        """The display picture of the next frame of the stream."""
        return from_coded(self.decode_coded(payload), self.width, self.height, self.flip)

    def decode_coded(self, payload: bytes) -> list[Plane]:
        """The next frame's planes as coded: whole macroblocks, bottom-up for EA movies."""
        header = parse_frame_header(payload, self.filter_header)
        model = self.model
        parse_filter_info = 0
        golden = 0
        mode = self.motion.mode
        variance_threshold = self.motion.variance_threshold
        max_vector_length = self.motion.max_vector_length
        selection = self.motion.selection
        deblock = self.motion.deblock
        vrt_shift = 0
        if header.keyframe:
            assert header.sub_version is not None and header.filter_header is not None
            assert header.mb_rows is not None and header.mb_cols is not None
            if header.interlaced:
                raise UnsupportedStreamError("interlaced VP6 frames are not supported")
            if header.sub_version > 8:
                raise Vp6FormatError(f"VP6 sub-version {header.sub_version} does not exist")
            if not header.mb_rows or not header.mb_cols:
                raise Vp6FormatError("keyframe has no macroblocks")
            self.sub_version = header.sub_version
            self.filter_header = header.filter_header
            if (header.mb_rows, header.mb_cols) != (self.mb_rows, self.mb_cols):
                self.mb_rows, self.mb_cols = header.mb_rows, header.mb_cols
                self.previous = self.golden = None
            c = BoolDecoder(payload, header.data_start)
            c.read_bits(2)
            parse_filter_info = self.filter_header
            vrt_shift = 5 if self.sub_version < 8 else 0
        else:
            if not self.sub_version or self.previous is None:
                raise Vp6FormatError("inter frame before any keyframe")
            c = BoolDecoder(payload, header.data_start)
            golden = c.read(128)
            if self.filter_header:
                deblock = bool(c.read(128))
                if deblock:
                    c.read(128)
                if self.sub_version > 7:
                    parse_filter_info = c.read(128)
        if parse_filter_info:
            if c.read(128):
                mode = 2
                variance_threshold = c.read_bits(5) << vrt_shift
                max_vector_length = 2 << c.read_bits(3)
            elif c.read(128):
                mode = 1
            else:
                mode = 0
            selection = c.read_bits(4) if self.sub_version > 7 else 16
        use_huffman = c.read(128)
        self.motion = MotionFilter(
            mode, variance_threshold, max_vector_length, selection, deblock, header.quantizer
        )
        separate = header.coeff_offset not in (0, 2)
        coeffs: BoolDecoder | BitReader
        if separate and use_huffman:
            coeffs = BitReader(payload, header.coeff_offset)
        elif separate:
            coeffs = BoolDecoder(payload, header.coeff_offset)
        else:
            coeffs = c

        mb_count = self.mb_rows * self.mb_cols
        if header.keyframe:
            model.reset(self.sub_version)
            self._mb_types = [MbType.INTRA] * mb_count
        else:
            self._parse_mb_type_models(c)
            self._parse_vector_models(c)
            self._mb_type = MbType.INTER_NOVEC_PF
        if len(self._mb_vectors) != mb_count:
            self._mb_vectors = [_ZERO] * mb_count
        self._parse_coeff_models(c, header.keyframe)
        model.compute_dcct()
        if isinstance(coeffs, BitReader):
            self._build_huffman_tables()
        return self._decode_macroblocks(c, coeffs, header.keyframe, header.quantizer, golden)

    def _parse_mb_type_models(self, c: BoolDecoder) -> None:
        model = self.model
        for ctx in range(3):
            if c.read(174):
                index = c.read_bits(4)
                model.mb_types_stats[ctx] = [list(p) for p in PRE_DEF_MB_TYPE_STATS[index][ctx]]
            if c.read(254):
                for mb_type in range(10):
                    for i in range(2):
                        if c.read(205):
                            sign = c.read(128)
                            delta = c.read_tree(PMBTM_TREE, MB_TYPE_MODEL_MODEL)
                            if not delta:
                                delta = 4 * c.read_bits(7)
                            stats = model.mb_types_stats[ctx][mb_type]
                            stats[i] = (stats[i] + (-delta if sign else delta)) & 0xFF
        model.compute_mb_type_probs()

    def _parse_vector_models(self, c: BoolDecoder) -> None:
        model = self.model
        for comp in range(2):
            if c.read(SIG_DCT_PCT[comp][0]):
                model.vector_dct[comp] = c.read_probability()
            if c.read(SIG_DCT_PCT[comp][1]):
                model.vector_sig[comp] = c.read_probability()
        for comp in range(2):
            for node in range(7):
                if c.read(PDV_PCT[comp][node]):
                    model.vector_pdv[comp][node] = c.read_probability()
        for comp in range(2):
            for node in range(8):
                if c.read(FDV_PCT[comp][node]):
                    model.vector_fdv[comp][node] = c.read_probability()

    def _parse_coeff_models(self, c: BoolDecoder, keyframe: bool) -> None:
        model = self.model
        default = [0x80] * 11
        for pt in range(2):
            for node in range(11):
                if c.read(DCCV_PCT[pt][node]):
                    default[node] = c.read_probability()
                    model.coeff_dccv[pt][node] = default[node]
                elif keyframe:
                    model.coeff_dccv[pt][node] = default[node]
        if c.read(128):
            for pos in range(1, 64):
                if c.read(COEFF_REORDER_PCT[pos]):
                    model.coeff_reorder[pos] = c.read_bits(4)
            model.init_coeff_order(self.sub_version)
        for group in range(2):
            for node in range(14):
                if c.read(RUNV_PCT[group][node]):
                    model.coeff_runv[group][node] = c.read_probability()
        for ct in range(3):
            for pt in range(2):
                for cg in range(6):
                    for node in range(11):
                        if c.read(RACT_PCT[ct][pt][cg][node]):
                            default[node] = c.read_probability()
                            model.coeff_ract[pt][ct][cg][node] = default[node]
                        elif keyframe:
                            model.coeff_ract[pt][ct][cg][node] = default[node]

    def _build_huffman_tables(self) -> None:
        model = self.model
        self._dccv_tables = [
            build_table(model.coeff_dccv[pt], HUFF_COEFF_MAP, 12) for pt in range(2)
        ]
        self._runv_tables = [build_table(model.coeff_runv[pt], HUFF_RUN_MAP, 9) for pt in range(2)]
        self._ract_tables = [
            [
                [build_table(model.coeff_ract[pt][ct][cg], HUFF_COEFF_MAP, 12) for cg in range(6)]
                for ct in range(3)
            ]
            for pt in range(2)
        ]
        # How many more blocks of each plane type have a zero DC ([0]) or no AC ([1]).
        self._null_runs = [[0, 0], [0, 0]]

    def _parse_block_huffman(
        self,
        bits: BitReader,
        pt: int,
        scan: list[int],
        dequant_ac: int,
        base: int,
        positions: list[int],
        values: list[int],
    ) -> tuple[int, int]:
        """`_parse_block` for a Huffman-coded partition."""
        null_runs = self._null_runs
        table: HuffmanTable = self._dccv_tables[pt]
        ract = self._ract_tables[pt]
        index = 0
        code_type = 0
        dc = 0
        while True:
            run = 1
            if index < 2 and null_runs[index][pt]:
                null_runs[index][pt] -= 1
                if index:
                    break
            else:
                symbol = table.read(bits)
                if symbol == 0:
                    code_type = 0
                    if index:
                        run += self._runv_tables[1 if index >= 6 else 0].read(bits)
                        if run >= 9:
                            run += bits.read_bits(6)
                    else:
                        null_runs[0][pt] = _null_run_length(bits)
                elif symbol == 11:
                    if index == 1:
                        null_runs[1][pt] = _null_run_length(bits)
                    break
                else:
                    coeff = COEFF_BIAS[symbol]
                    if symbol > 4:
                        coeff += bits.read_bits(symbol - 4 if symbol <= 9 else 11)
                    code_type = 2 if coeff > 1 else 1
                    if bits.read_bit():
                        coeff = -coeff
                    if index:
                        positions.append(base + scan[index])
                        values.append(wrap16(coeff * dequant_ac))
                    else:
                        dc = coeff
            index += run
            if index >= 64:
                break
            table = ract[code_type][min(COEFF_GROUPS[index], 3)]
        return index, dc

    def _vector_predictors(self, row: int, col: int, ref: int) -> int:
        """Find up to two distinct non-zero vectors of nearby macroblocks; the context is
        0 for two, 1 for none and 2 for one."""
        found: list[Vector] = [_ZERO, _ZERO]
        count = 0
        for pos, (dx, dy) in enumerate(CANDIDATE_PREDICTOR_POS):
            x = col + dx
            y = row + dy
            if x < 0 or x >= self.mb_cols or y < 0 or y >= self.mb_rows:
                continue
            index = y * self.mb_cols + x
            if REFERENCE_FRAME[self._mb_types[index]] != ref:
                continue
            vector = self._mb_vectors[index]
            if vector == found[0] or vector == _ZERO:
                continue
            found[count] = vector
            count += 1
            if count > 1:
                count = -1
                break
            self._candidate_pos = pos
        self._candidates = found
        return count + 1

    def _vector_delta(self, c: BoolDecoder) -> Vector:
        model = self.model
        base = self._candidates[0] if self._candidate_pos < 2 else _ZERO
        result = list(base)
        for comp in range(2):
            if c.read(model.vector_dct[comp]):
                delta = 0
                for bit in _LONG_VECTOR_ORDER:
                    delta |= c.read(model.vector_fdv[comp][bit]) << bit
                if delta & 0xF0:
                    delta |= c.read(model.vector_fdv[comp][3]) << 3
                else:
                    delta |= 8
            else:
                delta = c.read_tree(PVA_TREE, model.vector_pdv[comp])
            if delta and c.read(model.vector_sig[comp]):
                delta = -delta
            result[comp] += delta
        return result[0], result[1]

    def _decode_mv(self, c: BoolDecoder, row: int, col: int) -> tuple[int, list[Vector]]:
        index = row * self.mb_cols + col
        ctx = self._vector_predictors(row, col, RefFrame.PREVIOUS)
        probs = self.model.mb_type[ctx][self._mb_type]
        if not c.read(probs[0]):
            self._mb_type = MbType(c.read_tree(PMBT_TREE, probs))
        mb_type = self._mb_type
        self._mb_types[index] = mb_type

        vector = _ZERO
        if mb_type == MbType.INTER_V1_PF:
            vector = self._candidates[0]
        elif mb_type == MbType.INTER_V2_PF:
            vector = self._candidates[1]
        elif mb_type == MbType.INTER_V1_GF:
            self._vector_predictors(row, col, RefFrame.GOLDEN)
            vector = self._candidates[0]
        elif mb_type == MbType.INTER_V2_GF:
            self._vector_predictors(row, col, RefFrame.GOLDEN)
            vector = self._candidates[1]
        elif mb_type == MbType.INTER_DELTA_PF:
            vector = self._vector_delta(c)
        elif mb_type == MbType.INTER_DELTA_GF:
            self._vector_predictors(row, col, RefFrame.GOLDEN)
            vector = self._vector_delta(c)
        elif mb_type == MbType.INTER_4V:
            return mb_type, self._decode_4mv(c, index)
        self._mb_vectors[index] = vector
        return mb_type, [vector] * 6

    def _decode_4mv(self, c: BoolDecoder, index: int) -> list[Vector]:
        kinds = [c.read_bits(2) for _ in range(4)]
        vectors: list[Vector] = []
        for kind in kinds:
            if kind == 0:
                vectors.append(_ZERO)
            elif kind == 1:
                vectors.append(self._vector_delta(c))
            elif kind == 2:
                vectors.append(self._candidates[0])
            else:
                vectors.append(self._candidates[1])
        self._mb_vectors[index] = vectors[3]
        sum_x = sum(v[0] for v in vectors)
        sum_y = sum(v[1] for v in vectors)
        chroma = (_rshift_round(sum_x, 2), _rshift_round(sum_y, 2))
        return [*vectors, chroma, chroma]

    def _parse_block(
        self,
        c: BoolDecoder,
        pt: int,
        ctx: int,
        scan: list[int],
        dequant_ac: int,
        base: int,
        positions: list[int],
        values: list[int],
    ) -> tuple[int, int]:
        """Read one block's tokens into `positions`/`values` (AC only, dequantized); returns
        the coefficient index it stopped at and the coded DC."""
        model = self.model
        read = c.read
        m1 = model.coeff_dccv[pt]
        m2: list[int] = model.coeff_dcct[pt][ctx]
        ract = model.coeff_ract[pt]
        runv = model.coeff_runv
        index = 0
        code_type = 1
        run = 1
        dc = 0
        while True:
            if (index > 1 and code_type == 0) or read(m2[0]):
                if read(m2[2]):
                    if read(m2[3]):
                        category = c.read_tree(PC_TREE, m1)
                        coeff = COEFF_BIAS[category + 5]
                        table = COEFF_PARSE_TABLE[category]
                        for bit in range(COEFF_BIT_LENGTH[category], -1, -1):
                            coeff += read(table[bit]) << bit
                    elif read(m2[4]):
                        coeff = 3 + read(m1[5])
                    else:
                        coeff = 2
                    code_type = 2
                else:
                    code_type = 1
                    coeff = 1
                if read(128):
                    coeff = -coeff
                if index:
                    positions.append(base + scan[index])
                    values.append(wrap16(coeff * dequant_ac))
                else:
                    dc = coeff
                run = 1
            else:
                code_type = 0
                if index > 0:
                    if not read(m2[1]):
                        break
                    m3 = runv[1 if index >= 6 else 0]
                    run = c.read_tree(PCR_TREE, m3)
                    if not run:
                        run = 9
                        for bit in range(6):
                            run += read(m3[bit + 8]) << bit
            index += run
            if index >= 64:
                break
            m1 = m2 = ract[code_type][COEFF_GROUPS[index]]
        return index, dc

    def _decode_macroblocks(
        self,
        c: BoolDecoder,
        coeffs: BoolDecoder | BitReader,
        keyframe: bool,
        quantizer: int,
        golden: int,
    ) -> list[Plane]:
        model = self.model
        rows, cols = self.mb_rows, self.mb_cols
        block_count = rows * cols * 6
        dequant_dc = DC_DEQUANT[quantizer] << 2
        dequant_ac = AC_DEQUANT[quantizer] << 2
        scan = model.scan
        selectors = model.coeff_index_to_idct_selector
        ctx = BlockContext(cols)
        positions: list[int] = []
        values: list[int] = []
        dcs = [0] * block_count
        block_selectors = [0] * block_count
        block_types = [0] * block_count
        block_vectors: list[Vector] = [_ZERO] * block_count

        for row in range(rows):
            ctx.start_row()
            for col in range(cols):
                mb = row * cols + col
                mb_type: int
                vectors: list[Vector] | None
                if keyframe:
                    mb_type, vectors = MbType.INTRA, None
                else:
                    mb_type, vectors = self._decode_mv(c, row, col)
                ref = REFERENCE_FRAME[mb_type]
                for block in range(6):
                    index = mb * 6 + block
                    pt = 1 if block > 3 else 0
                    if isinstance(coeffs, BitReader):
                        stop, dc = self._parse_block_huffman(
                            coeffs, pt, scan, dequant_ac, index * 64, positions, values
                        )
                    else:
                        stop, dc = self._parse_block(
                            coeffs,
                            pt,
                            ctx.token_context(block),
                            scan,
                            dequant_ac,
                            index * 64,
                            positions,
                            values,
                        )
                    ctx.set_coded_dc(block, dc != 0)
                    total = wrap16(dc + ctx.predict_dc(block, ref))
                    ctx.store_dc(block, ref, total)
                    dcs[index] = wrap16(total * dequant_dc)
                    block_selectors[index] = selectors[min(stop, 63)]
                    block_types[index] = mb_type
                    if vectors is not None:
                        block_vectors[index] = vectors[block]
                ctx.next_macroblock()

        flat = np.zeros(block_count * 64, dtype=np.int64)
        flat[np.array(positions, dtype=np.int64)] = np.array(values, dtype=np.int64)
        coefficients = flat.reshape(block_count, 64)
        coefficients[:, 0] = dcs
        current = self._render(
            coefficients.reshape(block_count, 8, 8),
            np.array(block_types),
            np.array(block_selectors),
            block_vectors,
        )
        if keyframe or golden:
            self.golden = current
        self.previous = current
        return current

    def _render(
        self,
        coefficients: npt.NDArray[np.int64],
        block_types: npt.NDArray[np.int64],
        selectors: npt.NDArray[np.int64],
        block_vectors: list[Vector],
    ) -> list[Plane]:
        layout = BlockLayout.of(self.mb_rows, self.mb_cols)
        plane, left, top = layout.plane, layout.left, layout.top
        intra = block_types == MbType.INTRA
        residual = block_residuals(coefficients, selectors, intra)

        prediction = np.full(coefficients.shape, 128, dtype=np.int64)
        for kind, ref_planes in (
            (MbType.INTER_NOVEC_PF, self.previous),
            (MbType.INTER_NOVEC_GF, self.golden),
        ):
            chosen = np.nonzero(block_types == kind)[0]
            if chosen.size and ref_planes is not None:
                prediction[chosen] = layout.gather(ref_planes, chosen)
        moving = np.nonzero(
            ~intra & (block_types != MbType.INTER_NOVEC_PF) & (block_types != MbType.INTER_NOVEC_GF)
        )[0]
        for index in moving.tolist():
            ref_frame = REFERENCE_FRAME[int(block_types[index])]
            ref_planes = self.golden if ref_frame == RefFrame.GOLDEN else self.previous
            if ref_planes is None:
                continue
            block = index % 6
            prediction[index] = predict_block(
                ref_planes[int(plane[index])],
                int(left[index]),
                int(top[index]),
                block_vectors[index],
                COORD_DIV[block],
                block < 4,
                self.motion,
            )

        return layout.scatter(np.clip(prediction + residual, 0, 255))
