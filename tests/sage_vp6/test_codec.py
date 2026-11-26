"""The codec end to end on synthetic video: whatever the encoder writes, the decoder rebuilds
pixel for pixel as the encoder's own reconstruction, so a movie never drifts; and that
reconstruction stays close to the source."""

import io

import pytest

np = pytest.importorskip("numpy", reason="the [vp6] extra (numpy) is not installed")

from sage_vp6.codec import (  # noqa: E402 - after the importorskip guard
    Decoder,
    Encoder,
    EncoderSettings,
    YuvFrame,
    iter_y4m,
    png_bytes,
    to_rgb,
)
from sage_vp6.codec.dct import block_residuals, forward_dct, inverse_dct  # noqa: E402
from sage_vp6.codec.frames import from_coded, to_coded  # noqa: E402


def _scene(width: int, height: int, t: int) -> YuvFrame:
    """A gradient with a bright box sliding across it, light noise, and two-tone chroma."""
    yy, xx = np.mgrid[0:height, 0:width]
    luma = 60 + 0.5 * xx + 0.3 * yy
    left, top = 10 + 3 * t, 8 + 2 * t
    luma[(yy >= top) & (yy < top + 20) & (xx >= left) & (xx < left + 24)] = 220
    luma += np.random.default_rng(t).integers(-3, 4, size=luma.shape)
    chroma_shape = ((height + 1) // 2, (width + 1) // 2)
    u = np.full(chroma_shape, 100, dtype=np.uint8)
    u[:, : chroma_shape[1] // 3] = 160
    v = np.full(chroma_shape, 140, dtype=np.uint8)
    v[chroma_shape[0] // 2 :, :] = 90
    return YuvFrame(np.clip(luma, 0, 255).astype(np.uint8), u, v)


def _psnr(a: "np.ndarray", b: "np.ndarray") -> float:
    mse = float(((a.astype(np.float64) - b) ** 2).mean())
    return 99.0 if mse == 0 else 10 * np.log10(255**2 / mse)


def _same(a: YuvFrame, b: YuvFrame) -> bool:
    return all((x == y).all() for x, y in ((a.y, b.y), (a.u, b.u), (a.v, b.v)))


def test_transforms_invert_each_other():
    pixels = np.random.default_rng(0).integers(-128, 128, size=(200, 8, 8))
    coefficients = np.rint(4 * forward_dct(pixels)).astype(np.int64)
    assert np.abs(inverse_dct(coefficients) - pixels).max() <= 2


@pytest.mark.parametrize("quality", [10, 50, 63])
def test_decoder_rebuilds_the_encoders_reconstruction(quality):
    width, height = 72, 56
    encoder = Encoder(width, height, EncoderSettings(quality=quality, keyframe_interval=6))
    decoder = Decoder(width, height)
    kinds = []
    for t in range(9):
        source = _scene(width, height, t)
        frame = encoder.encode(source)
        kinds.append(frame.keyframe)
        picture = decoder.decode(frame.payload)
        assert _same(picture, encoder.reconstruction), f"frame {t} drifted"
        assert _psnr(picture.y, source.y) > (25 if quality < 30 else 33)
    assert kinds == [True, False, False, False, False, False, True, False, False]


def test_finer_quality_costs_more_and_looks_better():
    sizes, scores = [], []
    for quality in (20, 45, 60):
        encoder = Encoder(64, 48, EncoderSettings(quality=quality))
        source = _scene(64, 48, 0)
        sizes.append(len(encoder.encode(source).payload))
        scores.append(_psnr(encoder.reconstruction.y, source.y))
    assert sizes == sorted(sizes)
    assert scores == sorted(scores)


def test_a_still_scene_codes_inter_frames_tiny():
    encoder = Encoder(64, 48)
    still = _scene(64, 48, 0)
    first = encoder.encode(still)
    second = encoder.encode(still)
    assert first.keyframe and not second.keyframe
    assert len(second.payload) * 4 < len(first.payload)


def test_a_scene_cut_becomes_a_keyframe():
    # From busy texture to a smooth scene: predicting from the old picture costs more than
    # starting over, so the frame is coded as a keyframe.
    encoder = Encoder(64, 48, EncoderSettings(keyframe_interval=100))
    rng = np.random.default_rng(5)
    busy = YuvFrame(
        rng.integers(0, 256, size=(48, 64), dtype=np.uint8),
        rng.integers(0, 256, size=(24, 32), dtype=np.uint8),
        rng.integers(0, 256, size=(24, 32), dtype=np.uint8),
    )
    encoder.encode(busy)
    assert not encoder.encode(busy).keyframe
    assert encoder.encode(_scene(64, 48, 0)).keyframe


def test_odd_sizes_are_padded_and_cropped_back():
    width, height = 37, 23
    encoder = Encoder(width, height, EncoderSettings(quality=60))
    decoder = Decoder(width, height)
    source = _scene(width, height, 1)
    picture = decoder.decode(encoder.encode(source).payload)
    assert picture.y.shape == (23, 37) and picture.u.shape == (12, 19)
    assert _psnr(picture.y, source.y) > 33


def test_the_picture_stays_upright():
    # EA movies are coded bottom-up; a bright top-left corner must come back top-left.
    luma = np.full((32, 32), 30, dtype=np.uint8)
    luma[:8, :8] = 230
    chroma = np.full((16, 16), 128, dtype=np.uint8)
    encoder = Encoder(32, 32, EncoderSettings(quality=60))
    picture = Decoder(32, 32).decode(encoder.encode(YuvFrame(luma, chroma, chroma)).payload)
    assert picture.y[:8, :8].mean() > 200 and picture.y[-8:, -8:].mean() < 60


def test_coded_planes_round_trip():
    frame = _scene(37, 23, 0)
    planes = to_coded(frame, 2, 3)
    assert [p.shape for p in planes] == [(32, 48), (16, 24), (16, 24)]
    assert _same(from_coded(planes, 37, 23), frame)


@pytest.mark.parametrize("quality", [-1, 64])
def test_quality_is_range_checked(quality):
    with pytest.raises(ValueError, match="quality"):
        EncoderSettings(quality=quality)


def test_y4m_frames_are_read():
    frames = [_scene(10, 6, t) for t in range(2)]
    data = b"YUV4MPEG2 W10 H6 F30000:1001 Ip A1:1 C420jpeg\n"
    for frame in frames:
        data += b"FRAME\n" + frame.y.tobytes() + frame.u.tobytes() + frame.v.tobytes()
    header, pictures = iter_y4m(io.BytesIO(data))
    assert (header.width, header.height, header.rate, header.scale) == (10, 6, 30000, 1001)
    assert all(_same(a, b) for a, b in zip(pictures, frames, strict=True))


def test_y4m_rejects_other_chroma_layouts():
    with pytest.raises(ValueError, match="4:2:0"):
        iter_y4m(io.BytesIO(b"YUV4MPEG2 W4 H4 C444\n"))


def test_png_snapshot_is_a_png():
    data = png_bytes(to_rgb(_scene(9, 5, 0)))
    assert data.startswith(b"\x89PNG\r\n\x1a\n") and data.endswith(b"IEND\xaeB`\x82")


def test_reduced_transform_drops_what_lies_outside_its_corner():
    # VP6.0's selector can be 10 while scan position 10 (row 4, column 0) is coded; the decoder's
    # reduced transform reads only the top-left 4x4 and loses it, as FFmpeg's and On2's do.
    block = np.zeros((1, 8, 8), dtype=np.int64)
    block[0, 0, 0] = 64
    block[0, 4, 0] = 400
    intra = np.array([True])
    reduced = block_residuals(block, np.array([10]), intra)
    full = block_residuals(block, np.array([11]), intra)
    assert (reduced == inverse_dct(_corner(block))).all()
    assert not (reduced == full).all()


def _corner(block):
    out = np.zeros_like(block)
    out[:, :4, :4] = block[:, :4, :4]
    return out


def test_inter_dc_only_blocks_take_the_shortcut():
    block = np.zeros((2, 8, 8), dtype=np.int64)
    block[:, 0, 0] = 100
    residual = block_residuals(block, np.array([1, 1]), np.array([False, True]))
    assert (residual[0] == (100 + 15) >> 5).all()
    assert (residual[1] == inverse_dct(block[1:])[0]).all()
