"""`sage-vp6` driven through `main([...])` on synthetic files in `tmp_path`."""

import json

import pytest

from sage_vp6 import Frame, build_movie, read_movie_from_path, write_movie
from sage_vp6.__main__ import main


def _write_movie(path) -> None:
    key = bytes([0x79, 0x30, 0x00, 0x0A, 1, 1, 1, 1]) + b"\x00\x00"
    frames = [Frame(True, key), Frame(False, b"\xf9\x00\x03\x00"), Frame(False, b"\xf9\x00\x03")]
    path.write_bytes(write_movie(build_movie(frames, 16, 16, rate=983019, scale=32767)))


def test_info_reports_the_header_and_frames(tmp_path, capsys):
    movie = tmp_path / "m.vp6"
    _write_movie(movie)
    assert main(["info", str(movie), "--json", "--frames"]) == 0
    info = json.loads(capsys.readouterr().out)
    assert info["width"] == 16 and info["fps"] == 30.0
    assert info["frames"] == 3 and info["keyframes"] == 1
    assert info["quantizer"] == 60 and info["sub_version"] == 6
    assert [row["keyframe"] for row in info["frame_list"]] == [True, False, False]


def test_info_rejects_a_file_that_is_not_a_movie(tmp_path, capsys):
    bogus = tmp_path / "x.vp6"
    bogus.write_bytes(b"not a movie at all")
    assert main(["info", str(bogus)]) == 1
    assert "info:" in capsys.readouterr().err


def test_encode_then_extract_a_frame(tmp_path, capsys):
    np = pytest.importorskip("numpy", reason="the [vp6] extra (numpy) is not installed")
    width, height = 24, 16
    source = tmp_path / "in.y4m"
    data = b"YUV4MPEG2 W24 H16 F25:1 C420jpeg\n"
    for t in range(3):
        luma = np.full((height, width), 40 + 50 * t, dtype=np.uint8)
        chroma = np.full((height // 2, width // 2), 128, dtype=np.uint8)
        data += b"FRAME\n" + luma.tobytes() + chroma.tobytes() + chroma.tobytes()
    source.write_bytes(data)
    out = tmp_path / "out.vp6"
    assert main(["encode", str(source), str(out), "--quality", "55"]) == 0
    movie = read_movie_from_path(out)
    assert (movie.header.width, movie.header.height, movie.header.fps) == (24, 16, 25)
    assert len(movie.frames()) == 3

    still = tmp_path / "f.png"
    assert main(["frame", str(out), str(still), "--index", "2"]) == 0
    assert still.read_bytes().startswith(b"\x89PNG")

    decoded = tmp_path / "back.y4m"
    assert main(["decode", str(out), str(decoded)]) == 0
    assert decoded.read_bytes().count(b"FRAME\n") == 3
    capsys.readouterr()


def test_encode_rejects_a_bad_quality(tmp_path, capsys):
    pytest.importorskip("numpy", reason="the [vp6] extra (numpy) is not installed")
    source = tmp_path / "in.y4m"
    source.write_bytes(b"YUV4MPEG2 W16 H16 C420jpeg\n")
    assert main(["encode", str(source), str(tmp_path / "o.vp6"), "--quality", "99"]) == 1
    assert "quality" in capsys.readouterr().err


def test_encode_an_alpha_movie_from_a_matte(tmp_path, capsys):
    np = pytest.importorskip("numpy", reason="the [vp6] extra (numpy) is not installed")
    width, height = 32, 32

    def y4m(path, lumas):
        data = b"YUV4MPEG2 W32 H32 F30000:1001 C420jpeg\n"
        chroma = np.full((height // 2, width // 2), 128, dtype=np.uint8).tobytes()
        for luma in lumas:
            data += b"FRAME\n" + luma.tobytes() + chroma + chroma
        path.write_bytes(data)

    colour, matte = tmp_path / "colour.y4m", tmp_path / "matte.y4m"
    y4m(colour, [np.full((height, width), 90 + 10 * t, dtype=np.uint8) for t in range(3)])
    mattes = []
    for t in range(3):
        luma = np.full((height, width), 16, dtype=np.uint8)
        luma[:, : 8 + 8 * t] = 235
        mattes.append(luma)
    y4m(matte, mattes)
    out = tmp_path / "flag.vp6"
    assert main(["encode", str(colour), str(out), "--alpha", str(matte), "--quality", "60"]) == 0
    movie = read_movie_from_path(out)
    assert movie.has_alpha and len(movie.frames(alpha=True)) == 3

    still = tmp_path / "matte.png"
    assert main(["frame", str(out), str(still), "--index", "2", "--alpha"]) == 0
    assert still.read_bytes().startswith(b"\x89PNG")

    short = tmp_path / "short.y4m"
    y4m(short, mattes[:2])
    assert main(["encode", str(colour), str(out), "--alpha", str(short)]) == 1
    assert "frames" in capsys.readouterr().err
