"""Data-free round-trip tests for `sage_w3d.compressed_animation`: the time-coded and
adaptive-delta channel shapes, the bit channel, and the motion channel's two bodies - the
hazards the plan calls out (mid-stream padding, non-zero reserved bytes) are exercised
explicitly."""

from sage_w3d.binary import FixedString
from sage_w3d.chunks import W3D_CHUNK_COMPRESSED_ANIMATION_CHANNEL, UnknownChunk, Version
from sage_w3d.compressed_animation import (
    ADAPTIVE_DELTA_FLAVOR,
    TIME_CODED_FLAVOR,
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
    parse_compressed_animation_chunk,
    write_compressed_animation_chunk,
)


def _round_trip(animation: CompressedAnimation) -> CompressedAnimation:
    data = write_compressed_animation_chunk(animation)
    diagnostics: list = []
    parsed = parse_compressed_animation_chunk(data[8:], animation.flagged, 0, diagnostics)
    assert diagnostics == []
    assert isinstance(parsed, CompressedAnimation)
    assert write_compressed_animation_chunk(parsed) == data
    return parsed


def _header(flavor: int, num_frames: int = 4) -> CompressedAnimationHeader:
    return CompressedAnimationHeader(
        flagged=False,
        version=Version(0, 1),
        name=FixedString.from_value("a", 16),
        hierarchy_name=FixedString.from_value("b", 16),
        num_frames=num_frames,
        frame_rate=30,
        flavor=flavor,
    )


class TestTimeCodedChannel:
    def test_scalar_channel_with_interpolation_flag(self):
        channel = TimeCodedAnimationChannel(
            flagged=False,
            pivot=1,
            vector_len=1,
            channel_type=0,
            data=[
                TimeCodedDatum(0, False, 0.0),
                TimeCodedDatum(2, True, 1.5),
            ],
        )
        animation = CompressedAnimation(flagged=True, chunks=[_header(TIME_CODED_FLAVOR), channel])
        parsed = _round_trip(animation)
        assert parsed.time_coded_channels == [channel]

    def test_quaternion_channel(self):
        channel = TimeCodedAnimationChannel(
            flagged=False,
            pivot=2,
            vector_len=4,
            channel_type=6,
            data=[TimeCodedDatum(0, False, (0.0, 0.0, 0.0, 1.0))],
        )
        animation = CompressedAnimation(flagged=True, chunks=[_header(TIME_CODED_FLAVOR), channel])
        parsed = _round_trip(animation)
        assert parsed.time_coded_channels == [channel]


class TestAdaptiveDeltaChannel:
    def test_scalar_channel_with_nonzero_padding(self):
        # Hazard: the 3-byte trailing pad is not always zero.
        block = AdaptiveDeltaBlock(block_index=33, delta_bytes=bytes(range(8)))
        channel = AdaptiveDeltaAnimationChannel(
            flagged=False,
            num_time_codes=4,
            pivot=1,
            vector_len=1,
            channel_type=0,
            scale=0.5,  # float32-exact, so the round-trip comparison isn't muddied by rounding
            data=AdaptiveDeltaData(initial_value=0.0, delta_blocks=[block]),
            padding=b"\x01\x02\x03",
        )
        animation = CompressedAnimation(
            flagged=True, chunks=[_header(ADAPTIVE_DELTA_FLAVOR), channel]
        )
        parsed = _round_trip(animation)
        assert parsed.adaptive_delta_channels == [channel]

    def test_unrecognized_flavor_keeps_channel_raw(self):
        # A flavor this package doesn't know how to interpret must not crash the parse; the
        # channel simply isn't modeled (no way to tell time-coded from adaptive-delta bytes).
        raw_channel = UnknownChunk(W3D_CHUNK_COMPRESSED_ANIMATION_CHANNEL, False, b"\x00" * 12)
        animation = CompressedAnimation(flagged=True, chunks=[_header(99), raw_channel])
        parsed = _round_trip(animation)
        assert raw_channel in parsed.chunks


class TestBitChannel:
    def test_round_trips_time_codes_and_default(self):
        channel = TimeCodedBitChannel(
            flagged=False,
            pivot=0,
            channel_type=15,
            default_value=1,
            data=[TimeCodedBitDatum(0, True), TimeCodedBitDatum(1, False)],
        )
        animation = CompressedAnimation(flagged=True, chunks=[_header(TIME_CODED_FLAVOR), channel])
        parsed = _round_trip(animation)
        assert parsed.bit_channels == [channel]


class TestMotionChannel:
    def test_time_coded_body_with_odd_count_needs_alignment_pad(self):
        channel = MotionChannel(
            flagged=True,
            zero_byte=0,
            delta_type=0,
            vector_len=1,
            channel_type=0,
            num_time_codes=3,
            pivot=5,
            body=MotionTimeCodedData(
                data=[
                    MotionTimeCodedDatum(0, 0.0),
                    MotionTimeCodedDatum(1, 1.0),
                    MotionTimeCodedDatum(2, 2.0),
                ],
                pad=b"\x00\x00",
            ),
        )
        animation = CompressedAnimation(flagged=True, chunks=[_header(TIME_CODED_FLAVOR), channel])
        parsed = _round_trip(animation)
        assert parsed.motion_channels == [channel]

    def test_time_coded_body_with_even_count_has_no_pad(self):
        channel = MotionChannel(
            flagged=True,
            zero_byte=7,  # hazard: this reserved byte is not always zero either
            delta_type=0,
            vector_len=1,
            channel_type=0,
            num_time_codes=2,
            pivot=5,
            body=MotionTimeCodedData(
                data=[MotionTimeCodedDatum(0, 0.0), MotionTimeCodedDatum(1, 1.0)], pad=b""
            ),
        )
        animation = CompressedAnimation(flagged=True, chunks=[_header(TIME_CODED_FLAVOR), channel])
        parsed = _round_trip(animation)
        assert parsed.motion_channels[0].zero_byte == 7
        assert parsed.motion_channels[0].body.pad == b""

    def test_adaptive_delta_body(self):
        block = AdaptiveDeltaBlock(block_index=10, delta_bytes=bytes(range(16)))
        channel = MotionChannel(
            flagged=True,
            zero_byte=0,
            delta_type=2,
            vector_len=1,
            channel_type=0,
            num_time_codes=4,
            pivot=1,
            body=MotionAdaptiveDeltaData(
                scale=0.5, data=AdaptiveDeltaData(initial_value=0.0, delta_blocks=[block])
            ),
        )
        animation = CompressedAnimation(flagged=True, chunks=[_header(TIME_CODED_FLAVOR), channel])
        parsed = _round_trip(animation)
        assert parsed.motion_channels == [channel]
