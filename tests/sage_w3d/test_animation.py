"""Data-free round-trip tests for `sage_w3d.animation`."""

from sage_w3d.animation import (
    Animation,
    AnimationBitChannel,
    AnimationChannel,
    AnimationHeader,
    parse_animation_chunk,
    write_animation_chunk,
)
from sage_w3d.binary import FixedString
from sage_w3d.chunks import Version


def _round_trip(animation: Animation) -> Animation:
    data = write_animation_chunk(animation)
    diagnostics: list = []
    parsed = parse_animation_chunk(data[8:], animation.flagged, 0, diagnostics)
    assert diagnostics == []
    assert isinstance(parsed, Animation)
    assert write_animation_chunk(parsed) == data
    return parsed


class TestAnimationRoundTrip:
    def test_header_and_translation_channel(self):
        header = AnimationHeader(
            flagged=False,
            version=Version(4, 1),
            name=FixedString.from_value("a_anim", 16),
            hierarchy_name=FixedString.from_value("a_skel", 16),
            num_frames=3,
            frame_rate=30,
        )
        channel = AnimationChannel(
            flagged=False,
            first_frame=0,
            last_frame=2,
            vector_len=1,
            channel_type=0,
            pivot=1,
            pad=0,
            data=[0.0, 1.0, 2.0],
            trailing=b"",
        )
        animation = Animation(flagged=True, chunks=[header, channel])
        parsed = _round_trip(animation)
        assert parsed.name == "a_anim"
        assert parsed.channels == [channel]
        assert parsed.channels[0].values == [(0.0,), (1.0,), (2.0,)]

    def test_quaternion_channel_with_nonzero_pad(self):
        # Hazard: the u16 immediately after `pivot` is not always zero in real files. Values are
        # chosen exactly representable in float32 so the round-trip comparison isn't muddied by
        # the usual float64-literal-vs-float32-storage rounding (unrelated to this package).
        channel = AnimationChannel(
            flagged=False,
            first_frame=0,
            last_frame=1,
            vector_len=4,
            channel_type=6,
            pivot=2,
            pad=0xBEEF,
            data=[0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.5, 0.5],
            trailing=b"",
        )
        header = AnimationHeader(
            False,
            Version(4, 1),
            FixedString.from_value("a", 16),
            FixedString.from_value("b", 16),
            2,
            30,
        )
        animation = Animation(flagged=True, chunks=[header, channel])
        parsed = _round_trip(animation)
        assert parsed.channels[0].pad == 0xBEEF
        assert parsed.channels[0].values == [(0.0, 0.0, 0.0, 1.0), (0.0, 0.0, 0.5, 0.5)]

    def test_bit_channel_round_trips_default_and_bits(self):
        bit_channel = AnimationBitChannel(
            flagged=False,
            first_frame=0,
            last_frame=9,
            channel_type=15,
            pivot=0,
            default_raw=255,
            bits=b"\xff\x02",
        )
        header = AnimationHeader(
            False,
            Version(4, 1),
            FixedString.from_value("a", 16),
            FixedString.from_value("b", 16),
            10,
            30,
        )
        animation = Animation(flagged=True, chunks=[header, bit_channel])
        parsed = _round_trip(animation)
        assert parsed.bit_channels[0].default == 1.0
        assert parsed.bit_channels[0].values == [True] * 8 + [False, True]
