"""Data-free round-trip tests for `sage_w3d.hierarchy`."""

from sage_w3d.binary import FixedString, Vec3ListChunk
from sage_w3d.chunks import W3D_CHUNK_PIVOT_FIXUPS, Version
from sage_w3d.hierarchy import (
    Hierarchy,
    HierarchyHeader,
    HierarchyPivot,
    Pivots,
    parse_hierarchy_chunk,
    write_hierarchy_chunk,
)


def _round_trip(hierarchy: Hierarchy) -> Hierarchy:
    data = write_hierarchy_chunk(hierarchy)
    diagnostics: list = []
    parsed = parse_hierarchy_chunk(data[8:], hierarchy.flagged, 0, diagnostics)
    assert diagnostics == []
    assert isinstance(parsed, Hierarchy)
    assert write_hierarchy_chunk(parsed) == data
    return parsed


class TestHierarchyRoundTrip:
    def test_header_and_pivots(self):
        header = HierarchyHeader(
            flagged=False,
            version=Version(4, 1),
            name=FixedString.from_value("a_skeleton", 16),
            num_pivots=2,
            center_pos=(0.0, 0.0, 0.0),
        )
        root = HierarchyPivot(
            name=FixedString.from_value("root", 16),
            parent_id=-1,
            translation=(0.0, 0.0, 0.0),
            euler_angles=(0.0, 0.0, 0.0),
            rotation=(0.0, 0.0, 0.0, 1.0),
        )
        child = HierarchyPivot(
            name=FixedString.from_value("bone01", 16),
            parent_id=0,
            translation=(1.0, 2.0, 3.0),
            # float32-exact values, so the round-trip comparison isn't muddied by the usual
            # float64-literal-vs-float32-storage rounding (unrelated to this package).
            euler_angles=(0.125, 0.25, 0.375),
            rotation=(0.0, 0.0, 0.5, 0.5),
        )
        hierarchy = Hierarchy(flagged=True, chunks=[header, Pivots(False, [root, child])])
        parsed = _round_trip(hierarchy)
        assert parsed.name == "a_skeleton"
        assert parsed.pivots == [root, child]

    def test_pivot_fixups(self):
        header = HierarchyHeader(
            flagged=False,
            version=Version(4, 1),
            name=FixedString.from_value("skel", 16),
            num_pivots=0,
            center_pos=(0.0, 0.0, 0.0),
        )
        fixups = Vec3ListChunk(W3D_CHUNK_PIVOT_FIXUPS, False, [(1.0, 0.0, 0.0), (0.0, 1.0, 0.0)])
        hierarchy = Hierarchy(flagged=True, chunks=[header, fixups])
        parsed = _round_trip(hierarchy)
        assert parsed.pivot_fixups == [(1.0, 0.0, 0.0), (0.0, 1.0, 0.0)]
