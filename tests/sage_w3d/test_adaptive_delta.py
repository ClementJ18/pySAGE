"""Data-free tests for `sage_w3d.adaptive_delta`: the delta table shape, and decode/encode
against small hand-built vectors. Neither function is needed for a compressed animation
channel's own byte-exact round trip (covered in test_compressed_animation.py) - these tests
check the value-level codec on its own."""

from sage_w3d.adaptive_delta import DELTA_TABLE, decode, encode


class TestDeltaTable:
    def test_has_256_entries(self):
        assert len(DELTA_TABLE) == 256

    def test_first_sixteen_entries_are_powers_of_ten(self):
        assert DELTA_TABLE[8] == 1.0
        assert DELTA_TABLE[9] == 10.0
        assert abs(DELTA_TABLE[0] - 1e-8) < 1e-12

    def test_tail_entries_approach_zero(self):
        assert DELTA_TABLE[-1] < 0.01


class TestScalarRoundTrip:
    def test_encode_then_decode_recovers_values_within_one_quantization_step(self):
        values = [0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0]
        scale = 1.0
        initial_value, blocks = encode(
            channel_type=0, vector_len=1, scale=scale, values=values, bit_count=4
        )
        decoded = decode(
            channel_type=0,
            vector_len=1,
            num_time_codes=len(values),
            scale=scale,
            initial_value=initial_value,
            blocks=blocks,
            bit_count=4,
        )
        assert decoded[0] == values[0]
        assert len(decoded) == len(values)
        for expected, actual in zip(values, decoded, strict=True):
            assert abs(expected - actual) < 0.5

    def test_decode_of_zero_deltas_holds_the_initial_value(self):
        blocks = [(8, bytes(8))]  # table index 8 == scale factor 1.0, all-zero deltas
        decoded = decode(
            channel_type=0,
            vector_len=1,
            num_time_codes=3,
            scale=1.0,
            initial_value=5.0,
            blocks=blocks,
        )
        assert decoded == [5.0, 5.0, 5.0]


class TestQuaternionRoundTrip:
    def test_encode_then_decode_quaternions(self):
        values = [
            (0.0, 0.0, 0.0, 1.0),
            (0.1, 0.0, 0.0, 0.9),
            (0.2, 0.0, 0.0, 0.8),
        ]
        initial_value, blocks = encode(
            channel_type=6, vector_len=4, scale=1.0, values=values, bit_count=4
        )
        decoded = decode(
            channel_type=6,
            vector_len=4,
            num_time_codes=len(values),
            scale=1.0,
            initial_value=initial_value,
            blocks=blocks,
            bit_count=4,
        )
        assert decoded[0] == values[0]
        assert len(decoded) == len(values)
