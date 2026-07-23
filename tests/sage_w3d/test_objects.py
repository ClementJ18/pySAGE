"""Data-free round-trip tests for `sage_w3d.objects` (`CollisionBox`, `Dazzle`)."""

from sage_w3d.binary import FixedString, NulString, StringChunk
from sage_w3d.chunks import (
    W3D_CHUNK_DAZZLE_NAME,
    W3D_CHUNK_DAZZLE_TYPENAME,
    Rgba,
    UnknownChunk,
    Version,
)
from sage_w3d.objects import (
    COLLISION_TYPE_MASK,
    GEOMETRY_TYPE_MASK,
    CollisionBox,
    Dazzle,
    parse_box_chunk,
    parse_dazzle_chunk,
    write_box_chunk,
    write_dazzle_chunk,
)


class TestCollisionBox:
    def test_round_trip(self):
        box = CollisionBox(
            flagged=False,
            version=Version(1, 0),
            flags=0x21,
            name=FixedString.from_value("container.box01", 32),
            color=Rgba(10, 20, 30, 40),
            center=(0.0, 0.0, 0.0),
            extend=(1.0, 1.0, 1.0),
        )
        data = write_box_chunk(box)
        diagnostics: list = []
        parsed = parse_box_chunk(data[8:], box.flagged, 0, diagnostics)
        assert diagnostics == []
        assert parsed == box
        assert write_box_chunk(parsed) == data
        assert parsed.box_type == 0x21 & GEOMETRY_TYPE_MASK
        assert parsed.collision_types == 0x21 & COLLISION_TYPE_MASK

    def test_flags_outside_known_masks_round_trip(self):
        # `flags` is kept whole - bits outside GEOMETRY_TYPE_MASK/COLLISION_TYPE_MASK must
        # survive even though no named property exposes them.
        box = CollisionBox(
            flagged=False,
            version=Version(1, 0),
            flags=0xFFFFFFFF,
            name=FixedString.from_value("x", 32),
            color=Rgba(0, 0, 0, 0),
            center=(0.0, 0.0, 0.0),
            extend=(0.0, 0.0, 0.0),
        )
        data = write_box_chunk(box)
        diagnostics: list = []
        parsed = parse_box_chunk(data[8:], box.flagged, 0, diagnostics)
        assert parsed.flags == 0xFFFFFFFF


class TestDazzle:
    def test_round_trip(self):
        dazzle = Dazzle(
            flagged=True,
            chunks=[
                StringChunk(W3D_CHUNK_DAZZLE_NAME, False, NulString.from_value("a_dazzle")),
                StringChunk(W3D_CHUNK_DAZZLE_TYPENAME, False, NulString.from_value("REDLIGHT")),
            ],
        )
        data = write_dazzle_chunk(dazzle)
        diagnostics: list = []
        parsed = parse_dazzle_chunk(data[8:], dazzle.flagged, 0, diagnostics)
        assert diagnostics == []
        assert parsed == dazzle
        assert parsed.name == "a_dazzle"
        assert parsed.type_name == "REDLIGHT"
        assert write_dazzle_chunk(parsed) == data

    def test_unknown_child_preserved(self):
        unknown = UnknownChunk(0x999, False, b"???")
        dazzle = Dazzle(flagged=True, chunks=[unknown])
        data = write_dazzle_chunk(dazzle)
        diagnostics: list = []
        parsed = parse_dazzle_chunk(data[8:], dazzle.flagged, 0, diagnostics)
        assert parsed.chunks == [unknown]
