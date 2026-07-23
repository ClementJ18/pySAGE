"""The adaptive-delta codec used by compressed animation channels (`sage_w3d.compressed_animation`):
a per-frame delta from the previous frame's value, quantized to a 4- or 8-bit signed integer and
scaled by one of 256 fixed table entries (`DELTA_TABLE`) chosen per 16-frame block.

Neither `decode` nor `encode` is needed for a channel's own byte-exact round trip - the raw block
bytes `sage_w3d.compressed_animation` stores already guarantee that regardless of what these
functions do. They exist purely to turn those blocks into (or from) actual per-frame values."""

import math

__all__ = ["DELTA_TABLE", "decode", "encode"]


def _build_delta_table() -> list[float]:
    # Entries 0-15: powers of ten from 10^-8 to 10^7 (coarse scale steps). Entries 16-255: a
    # quarter sine curve from 1.0 down to ~0.0 (fine scale steps) - together a table of
    # multipliers spanning many orders of magnitude that a single byte can index into.
    table = [10.0 ** (i - 8) for i in range(16)]
    table.extend(1.0 - math.sin(90.0 * (i / 240.0) * math.pi / 180.0) for i in range(240))
    return table


DELTA_TABLE = _build_delta_table()


def _unpack_deltas(delta_bytes: bytes, bit_count: int) -> list[int]:
    """`delta_bytes` (`bit_count * 2` raw bytes) as `bit_count * 2` signed deltas: two 4-bit
    two's-complement nibbles per byte (both signed - decoding real animation channels with an
    unsigned upper nibble makes every accumulated value drift monotonically upward, visibly
    off the unit sphere for quaternions) when `bit_count == 4`, one excess-128 byte per byte
    otherwise (excess-128, not two's complement, verified against real 8-bit channels: unit
    quaternion norms hold to ~0.001 under excess-128 and explode past 4.0 under two's
    complement)."""
    if bit_count == 4:
        deltas = [0] * (len(delta_bytes) * 2)
        for i, byte in enumerate(delta_bytes):
            lower = byte & 0x0F
            upper = byte >> 4
            if lower >= 8:
                lower -= 16
            if upper >= 8:
                upper -= 16
            deltas[i * 2] = lower
            deltas[i * 2 + 1] = upper
        return deltas
    deltas = []
    for byte in delta_bytes:
        value = byte + 128
        if value >= 128:
            value -= 256
        deltas.append(value)
    return deltas


def _pack_deltas(deltas: list[int], bit_count: int) -> bytes:
    if bit_count == 4:
        out = bytearray(len(deltas) // 2)
        for i in range(len(out)):
            lower = deltas[i * 2]
            if lower < 0:
                lower += 16
            upper = deltas[i * 2 + 1] & 0x0F
            out[i] = (upper << 4) | (lower & 0x0F)
        return bytes(out)
    out = bytearray(len(deltas))
    for i, value in enumerate(deltas):
        value -= 128
        if value < -127:
            value += 256
        out[i] = value & 0xFF
    return bytes(out)


def decode(
    channel_type: int,
    vector_len: int,
    num_time_codes: int,
    scale: float,
    initial_value: float | tuple[float, float, float, float],
    blocks: list[tuple[int, bytes]],
    bit_count: int = 4,
) -> list[float | tuple[float, float, float, float]]:
    """Reconstruct `num_time_codes` per-frame values from `initial_value` and `blocks`
    (`(block_index, delta_bytes)` per block, in file order: 16 consecutive frames per vector
    component, one component's run after another - the shape `AdaptiveDeltaData.blocks` stores).
    `channel_type == 6` decodes each frame as an (x, y, z, w) quaternion; anything else, a plain
    float. `bit_count` is 4 for a plain adaptive-delta channel, or a motion channel's
    `delta_type * 4`."""
    scale_factor = 1.0 / 16.0 if bit_count == 8 else 1.0
    result: list[float | tuple[float, float, float, float] | None] = [None] * num_time_codes
    if num_time_codes > 0:
        result[0] = initial_value

    for i, (block_index, delta_bytes) in enumerate(blocks):
        delta_scale = scale * scale_factor * DELTA_TABLE[block_index]
        deltas = _unpack_deltas(delta_bytes, bit_count)
        vector_index = i % vector_len if vector_len else 0

        for j, delta in enumerate(deltas):
            idx = (i // vector_len if vector_len else i) * 16 + j + 1
            if idx >= num_time_codes:
                break
            previous = result[idx - 1]
            if previous is None:
                continue

            if channel_type == 6:
                assert isinstance(previous, tuple)
                # Component runs are in x, y, z, w order - the same order the initial value and
                # every non-delta channel kind store, verified on real motion and flavor-1
                # channels by two invariants at once: decoded quaternions stay unit-length
                # (within ~0.004) and cyclic animations end where they began. A w-first
                # (+1 shifted) mapping breaks both.
                existing = result[idx]
                current = list(existing) if isinstance(existing, tuple) else list(previous)
                current[vector_index] = previous[vector_index] + delta_scale * delta
                result[idx] = (current[0], current[1], current[2], current[3])
            else:
                assert isinstance(previous, int | float)
                result[idx] = previous + delta_scale * delta

    return [v if v is not None else 0.0 for v in result]


def _quantize(value: float, delta_scale: float, bit_count: int) -> int:
    if delta_scale == 0:
        return 0
    q = round(value / delta_scale)
    lo, hi = (-8, 7) if bit_count == 4 else (-127, 127)
    return max(lo, min(hi, q))


def encode(
    channel_type: int,
    vector_len: int,
    scale: float,
    values: list[float | tuple[float, float, float, float]],
    bit_count: int = 4,
) -> tuple[float | tuple[float, float, float, float], list[tuple[int, bytes]]]:
    """Best-effort inverse of `decode`: quantize `values` (per-frame; `values[0]` becomes the
    channel's initial value) into adaptive-delta blocks at the given `scale`/`bit_count`. Not an
    exact inverse - the format is inherently lossy, and choosing the optimal per-block table index
    is a search the original tool never documents a formula for - but every block returned
    decodes back to within one quantization step of its input."""
    scale_factor = 1.0 / 16.0 if bit_count == 8 else 1.0
    num_time_codes = len(values)
    initial_value = values[0]
    blocks: list[tuple[int, bytes]] = []

    num_groups = (num_time_codes + 15) // 16
    for group in range(num_groups):
        base_idx = group * 16
        for component in range(vector_len):
            deltas: list[float] = []
            for j in range(16):
                idx = base_idx + j + 1
                if idx >= num_time_codes:
                    deltas.append(0.0)
                    continue
                if channel_type == 6:
                    prev = values[idx - 1]
                    cur = values[idx]
                    assert isinstance(prev, tuple) and isinstance(cur, tuple)
                    deltas.append(cur[component] - prev[component])
                else:
                    prev_f, cur_f = values[idx - 1], values[idx]
                    assert isinstance(prev_f, int | float) and isinstance(cur_f, int | float)
                    deltas.append(cur_f - prev_f)

            best_index = 0
            best_error: float | None = None
            for table_index, table_value in enumerate(DELTA_TABLE):
                delta_scale = scale * scale_factor * table_value
                if delta_scale == 0:
                    continue
                error = max(
                    abs(d - _quantize(d, delta_scale, bit_count) * delta_scale) for d in deltas
                )
                if best_error is None or error < best_error:
                    best_error = error
                    best_index = table_index

            delta_scale = scale * scale_factor * DELTA_TABLE[best_index]
            quantized = [_quantize(d, delta_scale, bit_count) for d in deltas]
            blocks.append((best_index, _pack_deltas(quantized, bit_count)))

    return initial_value, blocks
