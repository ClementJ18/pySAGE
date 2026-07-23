"""Data-free round-trip tests for `sage_w3d.hlod`."""

from sage_w3d.binary import FixedString
from sage_w3d.chunks import W3D_CHUNK_HLOD_AGGREGATE_ARRAY, W3D_CHUNK_HLOD_LOD_ARRAY, Version
from sage_w3d.hlod import (
    HLOD,
    HLODArrayHeader,
    HLODHeader,
    HLODSubObject,
    HLODSubObjectArray,
    parse_hlod_chunk,
    write_hlod_chunk,
)


def _round_trip(hlod: HLOD) -> HLOD:
    data = write_hlod_chunk(hlod)
    diagnostics: list = []
    parsed = parse_hlod_chunk(data[8:], hlod.flagged, 0, diagnostics)
    assert diagnostics == []
    assert isinstance(parsed, HLOD)
    assert write_hlod_chunk(parsed) == data
    return parsed


class TestHLODRoundTrip:
    def test_header_and_lod_array(self):
        header = HLODHeader(
            flagged=False,
            version=Version(1, 0),
            lod_count=1,
            model_name=FixedString.from_value("a_model", 16),
            hierarchy_name=FixedString.from_value("a_skeleton", 16),
        )
        sub_object = HLODSubObject(False, 0, FixedString.from_value("a_container.a_mesh", 32))
        lod_array = HLODSubObjectArray(
            chunk_type=W3D_CHUNK_HLOD_LOD_ARRAY,
            flagged=True,
            chunks=[HLODArrayHeader(False, 1, 1000.0), sub_object],
        )
        hlod = HLOD(flagged=True, chunks=[header, lod_array])
        parsed = _round_trip(hlod)
        assert parsed.model_name == "a_model"
        assert parsed.hierarchy_name == "a_skeleton"
        assert len(parsed.lod_arrays) == 1
        assert parsed.lod_arrays[0].sub_objects == [sub_object]
        assert parsed.aggregate_array is None
        assert parsed.proxy_array is None

    def test_multiple_lod_levels_and_aggregate_array(self):
        header = HLODHeader(
            flagged=False,
            version=Version(1, 0),
            lod_count=2,
            model_name=FixedString.from_value("a_model", 16),
            hierarchy_name=FixedString.from_value("a_skeleton", 16),
        )
        lod0 = HLODSubObjectArray(W3D_CHUNK_HLOD_LOD_ARRAY, True, [HLODArrayHeader(False, 0, 0.0)])
        lod1 = HLODSubObjectArray(
            W3D_CHUNK_HLOD_LOD_ARRAY,
            True,
            [
                HLODArrayHeader(False, 1, 999.0),
                HLODSubObject(False, 3, FixedString.from_value("a.b", 32)),
            ],
        )
        aggregate = HLODSubObjectArray(
            W3D_CHUNK_HLOD_AGGREGATE_ARRAY, True, [HLODArrayHeader(False, 0, 0.0)]
        )
        hlod = HLOD(flagged=True, chunks=[header, lod0, lod1, aggregate])
        parsed = _round_trip(hlod)
        assert len(parsed.lod_arrays) == 2
        assert parsed.aggregate_array is not None
        assert parsed.aggregate_array.sub_objects == []
