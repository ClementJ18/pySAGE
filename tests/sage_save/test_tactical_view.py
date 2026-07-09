"""`CHUNK_TacticalView` - the camera (Step 3).

BFME2 bumped the chunk to version 3 and appended camera state its non-public `View::xfer`
overrides add, but the *leading* fields are exactly the GPL `View::xfer` (angle + look-at
position), so those decode and round-trip while the tail stays opaque. The exact-inverse
round-trip over every fixture is covered by the registry test in test_infra.py; here we pin the
camera values and the editability the decode unlocks."""

from pathlib import Path

import pytest

from sage_save import (
    apply_json,
    decode_tactical_view,
    encode_tactical_view,
    parse_save,
    parse_save_from_path,
    write_save,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"
SKIRMISH = FIXTURES / "Saved Game 4.BfME2Skirmish"


def _save():
    if not SKIRMISH.is_file():
        pytest.skip(f"fixture not present: {SKIRMISH.name}")
    return parse_save_from_path(SKIRMISH)


def test_decodes_camera_and_keeps_tail_opaque():
    view = decode_tactical_view(_save().chunk("CHUNK_TacticalView"))
    assert view.version == 3
    # the look-at position is a real map coordinate (this save's camera)
    x, y, z = view.position
    assert 3000 < x < 4500 and 500 < y < 1500
    assert view.trailing  # BFME2 version-2/3 additions kept opaque


def test_camera_position_varies_between_saves():
    # different saves in the enedwaith series framed the camera at different points
    positions = set()
    for n in range(4, 10):
        path = FIXTURES / f"Saved Game {n}.BfME2Skirmish"
        if not path.is_file():
            continue
        positions.add(
            decode_tactical_view(parse_save_from_path(path).chunk("CHUNK_TacticalView")).position
        )
    if positions:
        assert len(positions) > 1


def test_encode_is_exact_inverse():
    chunk = _save().chunk("CHUNK_TacticalView")
    assert encode_tactical_view(decode_tactical_view(chunk)) == chunk.payload


def test_camera_is_editable_length_preserving():
    # moving the camera is a float-in-place edit → length-preserving, so it applies and reparses
    save = _save()
    edited = apply_json(save, {"tactical_view": {"position": [1234.0, 5678.0, 90.0], "angle": 1.5}})
    reparsed = parse_save(write_save(edited))
    view = decode_tactical_view(reparsed.chunk("CHUNK_TacticalView"))
    assert view.position == (1234.0, 5678.0, 90.0)
    assert abs(view.angle - 1.5) < 1e-6
    # only the one chunk changed
    changed = [
        a.name for a, b in zip(save.chunks, reparsed.chunks, strict=True) if a.payload != b.payload
    ]
    assert changed == ["CHUNK_TacticalView"]
