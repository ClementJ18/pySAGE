"""A VP6 encoder: pictures in, frame payloads out.

What it writes is a plain subset of VP6, chosen to be easy to get exactly right:

- keyframes, and inter frames whose macroblocks either copy the previous frame and add a
  residual (no motion vectors) or are coded intra - so still and slow scenes stay small and a
  cut costs about a keyframe;
- one quantizer for the whole movie (`EncoderSettings.quality`), no loop filter and no
  Huffman coding, with the coefficient probabilities fitted to each frame's own statistics and
  sent in its header when that pays for itself.

Every frame is reconstructed exactly as a decoder will rebuild it, and that reconstruction is
what the next frame is predicted from, so errors never drift.
"""

import math
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from sage_vp6.codec.blocks import BlockLayout
from sage_vp6.codec.dct import block_residuals, forward_dct
from sage_vp6.codec.frames import YuvFrame, from_coded, to_coded
from sage_vp6.container import Frame
from sage_vp6.model import REFERENCE_FRAME, BlockContext, MbType, Model
from sage_vp6.rangecoder import BoolEncoder, tree_paths
from sage_vp6.tables import (
    AC_DEQUANT,
    COEFF_BIAS,
    COEFF_BIT_LENGTH,
    COEFF_GROUPS,
    COEFF_PARSE_TABLE,
    DC_DEQUANT,
    DCCV_LC,
    DCCV_PCT,
    FDV_PCT,
    PC_TREE,
    PCR_TREE,
    PDV_PCT,
    PMBT_TREE,
    RACT_PCT,
    RUNV_PCT,
    SIG_DCT_PCT,
)

__all__ = ["Encoder", "EncoderSettings"]

type IntArray = npt.NDArray[np.int64]
type Plane = npt.NDArray[np.uint8]

# VP6.1's transform selection is exact; VP6.0's can drop a coefficient (see `block_residuals`).
SUB_VERSION = 7
_MAX_LEVEL = 2114  # the largest magnitude the token alphabet can code

# Token slots: below 256 a slot is a fixed probability; above, an entry of the frame's model.
_DCCV = 256
_DCCT = _DCCV + 2 * 11
_RUNV = _DCCT + 2 * 3 * 5
_RACT = _RUNV + 2 * 14
_SLOTS = _RACT + 2 * 3 * 6 * 11

_PC_PATHS = tree_paths(PC_TREE)
_PCR_PATHS = tree_paths(PCR_TREE)
_PMBT_PATHS = tree_paths(PMBT_TREE)


def _bit_costs() -> tuple[list[float], list[float]]:
    zero = [0.0] + [-math.log2(p / 256) for p in range(1, 256)]
    one = [0.0] + [-math.log2(1 - p / 256) for p in range(1, 256)]
    return zero, one


_COST0, _COST1 = _bit_costs()
# Every probability a model update can carry: 1, then the even values up to 254.
_STORABLE = [1, *range(2, 255, 2)]


@dataclass(frozen=True, slots=True)
class EncoderSettings:
    """`quality` is VP6's quantizer index, 0 (coarsest) to 63 (finest); BFME's own movies use
    47-60. A keyframe is forced every `keyframe_interval` frames, and whenever more than
    `scene_cut` of an inter frame's macroblocks would be coded intra. `rounding` is where a
    coefficient rounds up to the next level: 0.5 is nearest, lower values zero out more of the
    small coefficients, which shrinks the file for little visible loss."""

    quality: int = 50
    keyframe_interval: int = 120
    scene_cut: float = 0.6
    rounding: float = 0.35

    def __post_init__(self) -> None:
        if not 0 <= self.quality <= 63:
            raise ValueError(f"quality must be 0-63, not {self.quality}")
        if self.keyframe_interval < 1:
            raise ValueError("keyframe_interval must be at least 1")


@dataclass(frozen=True, slots=True)
class _Quantized:
    """One way of coding every block of a frame."""

    levels: IntArray  # (blocks, 64) AC levels in coefficient-index order; column 0 unused
    dc: IntArray  # (blocks,) DC in quantizer steps, before DC prediction
    cost: IntArray  # (macroblocks,) estimated cost of the coefficients, in bits


class Encoder:
    """Encodes the frames of one movie in order. `flip` writes the picture bottom-up, as EA
    movies store it."""

    def __init__(
        self, width: int, height: int, settings: EncoderSettings | None = None, flip: bool = True
    ) -> None:
        if width < 1 or height < 1:
            raise ValueError("the picture must be at least 1x1")
        self.width = width
        self.height = height
        self.settings = settings or EncoderSettings()
        self.flip = flip
        self.mb_rows = (height + 15) // 16
        self.mb_cols = (width + 15) // 16
        if self.mb_rows > 255 or self.mb_cols > 255:
            raise ValueError("VP6 pictures are at most 4080 pixels on a side")
        self.layout = BlockLayout.of(self.mb_rows, self.mb_cols)
        self.model = Model()
        self.model.reset(SUB_VERSION)
        self.reference: list[Plane] | None = None
        self.frame_index = 0
        quantizer = self.settings.quality
        self._ac_step = AC_DEQUANT[quantizer]
        self._dc_step = DC_DEQUANT[quantizer]

    @property
    def reconstruction(self) -> YuvFrame:
        """The last frame as a decoder will show it."""
        if self.reference is None:
            raise ValueError("no frame has been encoded yet")
        return from_coded(self.reference, self.width, self.height, self.flip)

    def encode(self, frame: YuvFrame) -> Frame:
        """The next frame's payload."""
        planes = to_coded(frame, self.mb_rows, self.mb_cols, self.flip)
        pixels = self.layout.gather(planes)
        intra = self._quantize(forward_dct(pixels - 128))
        keyframe = self.reference is None or self.frame_index % self.settings.keyframe_interval == 0
        modes = np.full(self.mb_rows * self.mb_cols, MbType.INTRA, dtype=np.int64)
        coded = intra
        prediction: IntArray = np.full_like(pixels, 128)
        if not keyframe:
            assert self.reference is not None
            previous = self.layout.gather(self.reference)
            inter = self._quantize(forward_dct(pixels - previous))
            # A macroblock goes intra only when that is clearly cheaper than the residual.
            use_intra = intra.cost * 5 < inter.cost * 4
            if use_intra.mean() > self.settings.scene_cut:
                keyframe = True
            else:
                modes[~use_intra] = MbType.INTER_NOVEC_PF
                per_block = np.repeat(use_intra, 6)
                coded = _Quantized(
                    levels=np.where(per_block[:, None], intra.levels, inter.levels),
                    dc=np.where(per_block, intra.dc, inter.dc),
                    cost=np.where(use_intra, intra.cost, inter.cost),
                )
                prediction = np.where(per_block[:, None, None], 128, previous)

        payload = self._write_frame(coded, modes, keyframe)
        self.reference = self._reconstruct(coded, modes, prediction)
        self.frame_index += 1
        return Frame(keyframe=keyframe, payload=payload)

    def _quantize(self, coefficients: npt.NDArray[np.float64]) -> _Quantized:
        flat = coefficients.reshape(-1, 64)
        ordered = flat[:, self.model.scan]
        magnitude = np.floor(np.abs(ordered) / self._ac_step + self.settings.rounding)
        levels = (np.sign(ordered) * np.minimum(magnitude, _MAX_LEVEL)).astype(np.int64)
        levels[:, 0] = 0
        dc = np.rint(flat[:, 0] / self._dc_step).astype(np.int64)
        dc = np.clip(dc, -_MAX_LEVEL // 2, _MAX_LEVEL // 2)
        nonzero = levels != 0
        bits = (nonzero * (3 + 2 * np.log2(np.abs(levels) + 1))).sum(axis=1)
        bits += 2 + 2 * np.log2(np.abs(dc) + 1)
        return _Quantized(levels, dc, bits.reshape(-1, 6).sum(axis=1).astype(np.int64))

    def _reconstruct(self, coded: _Quantized, modes: IntArray, prediction: IntArray) -> list[Plane]:
        scan = self.model.scan
        natural = np.zeros_like(coded.levels)
        natural[:, scan] = coded.levels * (self._ac_step << 2)
        natural[:, 0] = coded.dc * (self._dc_step << 2)
        natural = ((natural + 0x8000) & 0xFFFF) - 0x8000
        # Each block's IDCT selector: the furthest scan position its coefficients reach.
        selectors = np.array(self.model.coeff_index_to_idct_selector)
        nonzero = coded.levels[:, 1:] != 0
        last = np.where(nonzero.any(axis=1), 63 - np.argmax(nonzero[:, ::-1], axis=1), 0)
        stop = np.minimum(np.maximum(last + 1, 1), 63)
        intra = np.repeat(modes == MbType.INTRA, 6)
        residual = block_residuals(natural.reshape(-1, 8, 8), selectors[stop], intra)
        return self.layout.scatter(np.clip(prediction + residual, 0, 255))

    def _write_frame(self, coded: _Quantized, modes: IntArray, keyframe: bool) -> bytes:
        model = self.model
        if keyframe:
            model.reset(SUB_VERSION)
        else:
            model.compute_mb_type_probs()
        slots, bits, mb_slots, mb_bits = self._tokenize(coded, modes, keyframe)

        header = BoolEncoder()
        if keyframe:
            header.write_bits(0, 2)
        else:
            header.write(0, 128)  # not a golden frame
        header.write(0, 128)  # range-coded, not Huffman
        if not keyframe:
            for _ in range(3):
                header.write(0, 174)  # keep the macroblock-type statistics
                header.write(0, 254)
            for comp in range(2):
                header.write(0, SIG_DCT_PCT[comp][0])
                header.write(0, SIG_DCT_PCT[comp][1])
            for comp in range(2):
                for node in range(7):
                    header.write(0, PDV_PCT[comp][node])
            for comp in range(2):
                for node in range(8):
                    header.write(0, FDV_PCT[comp][node])
        counts = np.bincount(
            np.asarray(slots, dtype=np.int64) * 2 + np.asarray(bits, dtype=np.int64),
            minlength=_SLOTS * 2,
        ).reshape(_SLOTS, 2)
        _write_coefficient_models(header, model, counts.tolist(), keyframe)
        for slot, bit in zip(mb_slots, mb_bits, strict=True):
            header.write(bit, slot)
        first = header.finish()

        probs = _slot_probabilities(model)
        coefficients = BoolEncoder()
        write = coefficients.write
        for slot, bit in zip(slots, bits, strict=True):
            write(bit, probs[slot])
        second = coefficients.finish()

        quantizer = self.settings.quality
        if keyframe:
            offset = 8 + len(first)
            if offset > 0xFFFF:
                raise ValueError("frame header partition is too large")
            head = bytes([quantizer << 1 | 1, SUB_VERSION << 3, offset >> 8, offset & 0xFF])
            head += bytes([self.mb_rows, self.mb_cols, self.mb_rows, self.mb_cols])
        else:
            offset = 3 + len(first)
            if offset > 0xFFFF:
                raise ValueError("frame header partition is too large")
            head = bytes([0x80 | quantizer << 1 | 1, offset >> 8, offset & 0xFF])
        return head + first + second

    def _tokenize(
        self, coded: _Quantized, modes: IntArray, keyframe: bool
    ) -> tuple[list[int], list[int], list[int], list[int]]:
        """The coefficient tokens (as model slots and bits) and the macroblock-type bits (as
        fixed probabilities and bits)."""
        slots: list[int] = []
        bits: list[int] = []
        mb_slots: list[int] = []
        mb_bits: list[int] = []
        levels = coded.levels.tolist()
        dcs = coded.dc.tolist()
        mode_list = modes.tolist()
        context = BlockContext(self.mb_cols)
        # With no motion vectors anywhere, no neighbour offers a vector candidate, which is
        # macroblock-type context 1.
        type_probs = self.model.mb_type[1]
        previous_type = MbType.INTER_NOVEC_PF
        for row in range(self.mb_rows):
            context.start_row()
            for col in range(self.mb_cols):
                mb = row * self.mb_cols + col
                mb_type = mode_list[mb]
                if not keyframe:
                    probs = type_probs[previous_type]
                    if mb_type == previous_type:
                        mb_slots.append(probs[0])
                        mb_bits.append(1)
                    else:
                        mb_slots.append(probs[0])
                        mb_bits.append(0)
                        for index, bit in _PMBT_PATHS[mb_type]:
                            mb_slots.append(probs[index])
                            mb_bits.append(bit)
                    previous_type = mb_type
                ref = REFERENCE_FRAME[mb_type]
                for block in range(6):
                    index = mb * 6 + block
                    token_context = context.token_context(block)
                    total = dcs[index]
                    dc = total - context.predict_dc(block, ref)
                    context.store_dc(block, ref, total)
                    context.set_coded_dc(block, dc != 0)
                    block_levels = levels[index]
                    block_levels[0] = dc
                    _tokenize_block(block_levels, 1 if block > 3 else 0, token_context, slots, bits)
                context.next_macroblock()
        return slots, bits, mb_slots, mb_bits


def _tokenize_block(
    levels: list[int], pt: int, ctx: int, slots: list[int], bits: list[int]
) -> None:
    """Append one block's tokens; `levels` is in coefficient-index order with the coded DC."""
    last = 63
    while last >= 0 and not levels[last]:
        last -= 1
    m1 = _DCCV + pt * 11
    m2 = _DCCT + (pt * 3 + ctx) * 5
    ract = _RACT + pt * 3 * 6 * 11
    index = 0
    code_type = 1
    while True:
        value = levels[index]
        if value:
            if not (index > 1 and code_type == 0):
                slots.append(m2)
                bits.append(1)
            magnitude = -value if value < 0 else value
            if magnitude == 1:
                slots.append(m2 + 2)
                bits.append(0)
                code_type = 1
            else:
                slots.append(m2 + 2)
                bits.append(1)
                if magnitude <= 4:
                    slots.append(m2 + 3)
                    bits.append(0)
                    if magnitude == 2:
                        slots.append(m2 + 4)
                        bits.append(0)
                    else:
                        slots.append(m2 + 4)
                        bits.append(1)
                        slots.append(m1 + 5)
                        bits.append(magnitude - 3)
                else:
                    slots.append(m2 + 3)
                    bits.append(1)
                    category = 5
                    while COEFF_BIAS[category + 5] > magnitude:
                        category -= 1
                    for node, bit in _PC_PATHS[category]:
                        slots.append(m1 + node)
                        bits.append(bit)
                    extra = magnitude - COEFF_BIAS[category + 5]
                    table = COEFF_PARSE_TABLE[category]
                    for shift in range(COEFF_BIT_LENGTH[category], -1, -1):
                        slots.append(table[shift])
                        bits.append((extra >> shift) & 1)
                code_type = 2
            slots.append(128)
            bits.append(1 if value < 0 else 0)
            run = 1
        else:
            slots.append(m2)
            bits.append(0)
            code_type = 0
            run = 1
            if index > 0:
                if index > last:
                    slots.append(m2 + 1)
                    bits.append(0)
                    return
                slots.append(m2 + 1)
                bits.append(1)
                following = index + 1
                while not levels[following]:
                    following += 1
                run = following - index
                runv = _RUNV + (14 if index >= 6 else 0)
                for node, bit in _PCR_PATHS[run if run <= 8 else 0]:
                    slots.append(runv + node)
                    bits.append(bit)
                if run > 8:
                    extra = run - 9
                    for shift in range(6):
                        slots.append(runv + 8 + shift)
                        bits.append((extra >> shift) & 1)
        index += run
        if index >= 64:
            return
        m1 = m2 = ract + (code_type * 6 + COEFF_GROUPS[index]) * 11


def _slot_probabilities(model: Model) -> list[int]:
    probs = list(range(256))
    for pt in range(2):
        probs += model.coeff_dccv[pt]
    for pt in range(2):
        for ctx in range(3):
            probs += model.coeff_dcct[pt][ctx]
    for group in range(2):
        probs += model.coeff_runv[group]
    for pt in range(2):
        for ct in range(3):
            for cg in range(6):
                probs += model.coeff_ract[pt][ct][cg]
    return probs


def _cost(counts: list[int], prob: int) -> float:
    return counts[0] * _COST0[prob] + counts[1] * _COST1[prob]


def _best(counts: list[int]) -> int:
    total = counts[0] + counts[1]
    target = round(256 * counts[0] / total / 2)
    candidates = {1, *(2 * v for v in range(max(target - 1, 1), min(target + 1, 127) + 1))}
    return min(sorted(candidates), key=lambda p: _cost(counts, p))


def _choose(
    header: BoolEncoder, gate: int, current: int, cost_of: dict[int, float] | list[int]
) -> tuple[int, bool]:
    """Write whether to replace `current` (and with what), whichever codes cheaper; returns
    the probability in force and whether it was sent. `cost_of` is the slot's [zero, one]
    counts, or a probability -> cost table for a slot whose cost is spread over derived models."""
    if isinstance(cost_of, list):
        if not cost_of[0] and not cost_of[1]:
            header.write(0, gate)
            return current, False
        counts = cost_of
        best = _best(counts)
        keep = _COST0[gate] + _cost(counts, current)
        change = _COST1[gate] + 7 + _cost(counts, best)
    else:
        if not any(cost_of.values()):
            header.write(0, gate)
            return current, False
        best = min(cost_of, key=lambda p: cost_of[p])
        keep = _COST0[gate] + cost_of[current]
        change = _COST1[gate] + 7 + cost_of[best]
    if change < keep:
        header.write(1, gate)
        header.write_probability(best)
        return best, True
    header.write(0, gate)
    return current, False


def _write_coefficient_models(
    header: BoolEncoder, model: Model, counts: list[list[int]], keyframe: bool
) -> None:
    """Fit the coefficient models to this frame's token counts and write the updates. On a
    keyframe, a model entry not sent repeats the last value sent for its node."""
    default = [0x80] * 11
    for pt in range(2):
        for node in range(11):
            current = default[node] if keyframe else model.coeff_dccv[pt][node]
            if node < 5:
                # The DC token reads these nodes through the per-context models derived from it.
                derived = [counts[_DCCT + (pt * 3 + ctx) * 5 + node] for ctx in range(3)]
                table = {
                    p: sum(
                        _cost(derived[ctx], _derive_dcct(p, ctx, node))
                        for ctx in range(3)
                        if derived[ctx][0] or derived[ctx][1]
                    )
                    for p in sorted({*_STORABLE, current})
                }
                chosen, sent = _choose(header, DCCV_PCT[pt][node], current, table)
            else:
                slot = _DCCV + pt * 11 + node
                chosen, sent = _choose(header, DCCV_PCT[pt][node], current, counts[slot])
            if sent:
                default[node] = chosen
            model.coeff_dccv[pt][node] = chosen
    header.write(0, 128)  # keep the coefficient order
    for group in range(2):
        for node in range(14):
            slot = _RUNV + group * 14 + node
            model.coeff_runv[group][node], _ = _choose(
                header, RUNV_PCT[group][node], model.coeff_runv[group][node], counts[slot]
            )
    for ct in range(3):
        for pt in range(2):
            for cg in range(6):
                for node in range(11):
                    current = default[node] if keyframe else model.coeff_ract[pt][ct][cg][node]
                    slot = _RACT + ((pt * 3 + ct) * 6 + cg) * 11 + node
                    gate = RACT_PCT[ct][pt][cg][node]
                    chosen, sent = _choose(header, gate, current, counts[slot])
                    if sent:
                        default[node] = chosen
                    model.coeff_ract[pt][ct][cg][node] = chosen
    model.compute_dcct()


def _derive_dcct(prob: int, ctx: int, node: int) -> int:
    weight, offset = DCCV_LC[ctx][node]
    value = ((prob * weight + 128) >> 8) + offset
    return 1 if value < 1 else 255 if value > 255 else value
