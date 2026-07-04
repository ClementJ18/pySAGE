"""Parsing APT shape geometry `.ru` files + the uv->position matrix inverse (stdlib)."""

from sage_apt.geometry import invert_matrix, parse_geometry


def test_solid_and_textured_fills():
    text = (
        "c\n"
        "s tc:255:255:255:255:102:1:0:0:1:174.5:301.05\n"
        "t -173.5:65.95:-173.5:-43.05:170.5:-43.05\n"
        "t 170.5:-43.05:170.5:65.95:-173.5:65.95\n"
        "c\n"
        "s s:0:153:153:255\n"
        "t -50:40:-50:-60:50:-60\n"
    )
    fills = parse_geometry(text)
    assert len(fills) == 2

    tex = fills[0]
    assert tex.kind == "textured"
    assert tex.color == (255, 255, 255, 255)
    assert tex.image_id == 102
    assert tex.matrix == (1.0, 0.0, 0.0, 1.0, 174.5, 301.05)
    assert len(tex.triangles) == 2
    assert tex.triangles[0] == (-173.5, 65.95, -173.5, -43.05, 170.5, -43.05)

    solid = fills[1]
    assert solid.kind == "solid"
    assert solid.color == (0, 153, 153, 255)
    assert len(solid.triangles) == 1


def test_line_style_and_segments_skipped():
    text = "c\ns l:1:116:128:142:255\nl 34.25:72.15:281:72.15\n"
    assert parse_geometry(text) == []  # a line style has no fillable triangles


def test_fill_without_triangles_dropped():
    text = "c\ns s:255:0:0:255\nc\ns s:0:255:0:255\nt 0:0:1:0:1:1\n"
    fills = parse_geometry(text)
    assert len(fills) == 1  # the first empty fill is dropped
    assert fills[0].color == (0, 255, 0, 255)


def test_malformed_lines_ignored():
    text = "s tc:bad\ns s:1:2:3\nt 0:0:1\ns s:10:20:30:255\nt 0:0:5:0:5:5\n"
    fills = parse_geometry(text)
    assert len(fills) == 1
    assert fills[0].color == (10, 20, 30, 255)
    assert fills[0].triangles == [(0.0, 0.0, 5.0, 0.0, 5.0, 5.0)]


def test_invert_matrix_identity_translation():
    # M = translate(174.5, 301.05); inverse maps uv (x+174.5, y+301.05) back to (x, y)
    inv = invert_matrix((1.0, 0.0, 0.0, 1.0, 174.5, 301.05))
    assert inv == (1.0, -0.0, -0.0, 1.0, -174.5, -301.05)


def test_invert_matrix_scale():
    inv = invert_matrix((2.0, 0.0, 0.0, 2.0, 100.0, 50.0))
    assert inv == (0.5, -0.0, -0.0, 0.5, -50.0, -25.0)


def test_invert_singular_returns_none():
    assert invert_matrix((0.0, 0.0, 0.0, 0.0, 5.0, 5.0)) is None
