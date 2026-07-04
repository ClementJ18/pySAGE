"""Parsing the APT image-map `.dat` (stdlib; always runs)."""

from sage_apt.imagemap import parse_image_map


def test_assignments_and_rectangles():
    text = "; Created by AptToBigc.\n53->1\n62->2\n17=0 0 15 32\n18=4 8 64 50\n"
    imap = parse_image_map(text)
    assert imap.texture_of(53) == 1
    assert imap.texture_of(62) == 2
    assert imap.rect_of(17) == (0, 0, 15, 32)
    assert imap.rect_of(18) == (4, 8, 64, 50)
    assert bool(imap) is True


def test_default_texture_and_missing_rect():
    imap = parse_image_map("99=1 2 3 4\n")
    assert imap.texture_of(12345) == imap.DEFAULT_TEXTURE == 1  # unassigned -> texture 1
    assert imap.rect_of(12345) is None


def test_malformed_lines_skipped():
    imap = parse_image_map("garbage\n5->\n6=1 2 3\n7=1 2 3 4 5\n8->x\n")
    assert imap.texture_of(5) == 1  # '5->' had no target, skipped
    assert imap.rect_of(6) is None  # only 3 numbers
    assert imap.rect_of(7) is None  # 5 numbers
    assert not imap  # nothing valid parsed


def test_empty_map_is_falsy():
    assert not parse_image_map("; just a comment\n\n")
