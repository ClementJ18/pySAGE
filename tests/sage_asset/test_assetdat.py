"""Data-free tests for `sage_asset.assetdat`. Synthetic asset.dat bytes are built in-code with
`struct`, independent of the module under test, so the read-side tests check parsing against a
known-correct byte layout rather than against the writer's own idea of the format."""

import struct
from datetime import UTC, datetime

import pytest

from sage_asset.assetdat import (
    Asset,
    AssetDat,
    AssetDatError,
    FileEntry,
    ReferenceRecord,
    VersionMismatchWarning,
    combine_asset_dats,
    parse_asset_dat,
    shadowed_entries,
    write_asset_dat,
)


def _pstr(value: str) -> bytes:
    raw = value.encode("latin-1")
    return struct.pack("<B", len(raw)) + raw


def _asset_bytes(name: str, raw_type: bytes, offset: int, size: int) -> bytes:
    return _pstr(name) + raw_type + struct.pack("<II", offset, size)


def _file_entry_bytes(name: str, file_time: int, assets: list[bytes]) -> bytes:
    return _pstr(name) + struct.pack("<QH", file_time, len(assets)) + b"".join(assets)


def _reference_bytes(file_name: str, asset_name: str, references: list[str]) -> bytes:
    body = _pstr(file_name) + _pstr(asset_name) + struct.pack("<H", len(references))
    return body + b"".join(_pstr(r) for r in references)


def _header(version: int, file_count: int, ref_count: int) -> bytes:
    return b"ALAE" + struct.pack("<III", version, file_count, ref_count)


def _build(version: int, files: list[bytes], references: list[bytes]) -> bytes:
    return _header(version, len(files), len(references)) + b"".join(files) + b"".join(references)


def test_parse_header_and_entries():
    file_bytes = _file_entry_bytes(
        "acolyte_soul.w3d",
        130000000000000000,
        [_asset_bytes("ACOLYTE_SOUL", b"HSEM", 0, 128)],
    )
    ref_bytes = _reference_bytes("acolyte_soul.w3d", "ACOLYTE_SOUL", ["acolyte_soul.tga"])
    data = _build(0x102, [file_bytes], [ref_bytes])

    ad = parse_asset_dat(data)

    assert ad.version == 0x102
    assert len(ad.files) == 1
    assert ad.files[0].name == "acolyte_soul.w3d"
    assert ad.files[0].file_time == 130000000000000000
    assert ad.files[0].assets == [Asset(name="ACOLYTE_SOUL", type="MESH", offset=0, size=128)]

    assert len(ad.references) == 1
    assert ad.references[0] == ReferenceRecord(
        file_name="acolyte_soul.w3d",
        asset_name="ACOLYTE_SOUL",
        references=["acolyte_soul.tga"],
    )


def test_filetime_to_modified():
    assert FileEntry(name="f", file_time=0, assets=[]).modified == datetime(1601, 1, 1, tzinfo=UTC)

    # 116444736000000000 ticks is the well-known FILETIME value of the Unix epoch.
    assert FileEntry(name="f", file_time=116444736000000000, assets=[]).modified == datetime(
        1970, 1, 1, tzinfo=UTC
    )


@pytest.mark.parametrize(
    "raw_type,decoded",
    [
        (b"XET\0", "TEX"),
        (b"HSEM", "MESH"),
        (b"REIH", "HIER"),
        (b"DOLH", "HLOD"),
        (b"MINA", "ANIM"),
        (b"XOB\0", "BOX"),
        (b"HSXF", "FXSH"),
        (b"TRAP", "PART"),
        (b"ZYX\0", "XYZ"),  # unknown but well-formed tag: parses and round-trips like any other
    ],
)
def test_type_tag_decode_and_round_trip(raw_type, decoded):
    data = _build(0x102, [_file_entry_bytes("f", 0, [_asset_bytes("A", raw_type, 0, 0)])], [])

    ad = parse_asset_dat(data)

    assert ad.files[0].assets[0].type == decoded
    assert write_asset_dat(ad) == data


def test_round_trip_with_duplicate_and_reordered_references():
    files = [
        _file_entry_bytes("a.w3d", 111, [_asset_bytes("A", b"HSEM", 0, 10)]),
        _file_entry_bytes("b.w3d", 222, [_asset_bytes("B", b"DOLH", 0, 0)]),
    ]
    # Section 2 is deliberately out of section-1 order and holds a duplicate (file, asset)
    # pair, mirroring what Edain's complete_asset/asset.dat has been observed to contain.
    references = [
        _reference_bytes("b.w3d", "B", ["a.w3d"]),
        _reference_bytes("a.w3d", "A", ["b.w3d"]),
        _reference_bytes("a.w3d", "A", ["b.w3d"]),
    ]
    data = _build(0x102, files, references)

    ad = parse_asset_dat(data)

    assert [r.file_name for r in ad.references] == ["b.w3d", "a.w3d", "a.w3d"]
    assert ad.references[1] == ad.references[2]
    assert write_asset_dat(ad) == data


def test_empty_asset_dat_round_trips():
    data = _build(0x102, [], [])

    ad = parse_asset_dat(data)

    assert ad == AssetDat(version=0x102, files=[], references=[])
    assert write_asset_dat(ad) == data


def test_parse_write_model_round_trips_by_equality():
    ad = AssetDat(
        version=0x102,
        files=[
            FileEntry(
                name="acolyte_soul.w3d",
                file_time=127972071240000000,
                assets=[
                    Asset(name="ACOLYTE_SOUL.KUACOLYTE_SKIN0", type="MESH", offset=0, size=64),
                    Asset(name="ACOLYTE_SOUL", type="HLOD", offset=64, size=32),
                ],
            ),
            FileEntry(
                name="acolyte_soul.tga",
                file_time=1,
                assets=[Asset(name="acolyte_soul.tga", type="TEX", offset=0, size=0)],
            ),
        ],
        references=[
            ReferenceRecord(
                file_name="acolyte_soul.w3d",
                asset_name="ACOLYTE_SOUL",
                references=["acolyte_soul.kuacolyte_skin0", "h*acolyte_soul"],
            ),
        ],
    )

    assert parse_asset_dat(write_asset_dat(ad)) == ad


def test_bad_magic_raises():
    with pytest.raises(AssetDatError, match="bad magic"):
        parse_asset_dat(b"NOPE" + struct.pack("<III", 0x102, 0, 0))


def test_truncated_header_raises():
    with pytest.raises(AssetDatError, match="truncated header"):
        parse_asset_dat(b"ALAE" + struct.pack("<I", 0x102))


def test_truncated_section1_missing_entry_raises():
    data = _header(0x102, 1, 0)  # claims one file entry but supplies none

    with pytest.raises(AssetDatError, match="truncated section 1"):
        parse_asset_dat(data)


def test_truncated_section1_partial_string_raises():
    # a pstr length prefix of 20 with only 5 payload bytes behind it
    data = _header(0x102, 1, 0) + struct.pack("<B", 20) + b"short"

    with pytest.raises(AssetDatError, match="truncated section 1"):
        parse_asset_dat(data)


def test_truncated_section1_partial_type_tag_raises():
    partial_asset = _pstr("A") + b"HS"  # 2 of the 4 type-tag bytes
    data = _header(0x102, 1, 0) + _pstr("a.w3d") + struct.pack("<QH", 0, 1) + partial_asset

    with pytest.raises(AssetDatError, match="truncated section 1"):
        parse_asset_dat(data)


def test_truncated_section2_raises():
    data = _header(0x102, 1, 1) + _file_entry_bytes(
        "a.w3d", 0, []
    )  # claims a ref record, none follow

    with pytest.raises(AssetDatError, match="truncated section 2"):
        parse_asset_dat(data)


def test_trailing_bytes_raise():
    data = _build(0x102, [], []) + b"junk"

    with pytest.raises(AssetDatError, match="trailing bytes"):
        parse_asset_dat(data)


def test_write_name_too_long_raises():
    ad = AssetDat(version=0x102, files=[FileEntry(name="x" * 256, file_time=0, assets=[])])

    with pytest.raises(AssetDatError, match="255-byte"):
        write_asset_dat(ad)


def test_write_too_many_references_raises():
    ad = AssetDat(
        version=0x102,
        references=[
            ReferenceRecord(file_name="a.w3d", asset_name="A", references=["x"] * (0xFFFF + 1))
        ],
    )

    with pytest.raises(AssetDatError, match="uint16 field limit"):
        write_asset_dat(ad)


def test_write_too_many_assets_raises():
    many_assets = [Asset(name="A", type="TEX", offset=0, size=0)] * (0xFFFF + 1)
    ad = AssetDat(version=0x102, files=[FileEntry(name="a.w3d", file_time=0, assets=many_assets)])

    with pytest.raises(AssetDatError, match="uint16 field limit"):
        write_asset_dat(ad)


def test_file_lookup_is_case_insensitive():
    entry = FileEntry(name="Acolyte_Soul.w3d", file_time=0, assets=[])
    ad = AssetDat(version=0x102, files=[entry])

    assert ad.file("acolyte_soul.w3d") is entry
    assert ad.file("ACOLYTE_SOUL.W3D") is entry
    assert ad.file("nope.w3d") is None


def test_references_for_returns_every_matching_record():
    ad = AssetDat(
        version=0x102,
        references=[
            ReferenceRecord(file_name="a.w3d", asset_name="A", references=["x.tga"]),
            ReferenceRecord(file_name="a.w3d", asset_name="A", references=["y.tga"]),
            ReferenceRecord(file_name="a.w3d", asset_name="B", references=["z.tga"]),
        ],
    )

    assert ad.references_for("A.W3D", "a") == [["x.tga"], ["y.tga"]]


def test_combine_concatenates_base_then_overlay():
    base = AssetDat(
        version=0x102,
        files=[FileEntry(name="a.w3d", file_time=1, assets=[])],
        references=[ReferenceRecord(file_name="a.w3d", asset_name="A", references=["x"])],
    )
    # Overlay collides with base on the same file name - the combined list keeps both,
    # base's copy first, rather than deduplicating.
    overlay = AssetDat(
        version=0x102,
        files=[FileEntry(name="a.w3d", file_time=2, assets=[])],
        references=[ReferenceRecord(file_name="a.w3d", asset_name="A", references=["y"])],
    )

    combined = combine_asset_dats(base, overlay)

    assert combined.version == 0x102
    assert combined.files == [base.files[0], overlay.files[0]]
    assert combined.references == [base.references[0], overlay.references[0]]


def test_combine_three_way_keeps_left_to_right_order():
    base = AssetDat(version=0x102, files=[FileEntry(name="base.w3d", file_time=0, assets=[])])
    overlay1 = AssetDat(version=0x102, files=[FileEntry(name="o1.w3d", file_time=0, assets=[])])
    overlay2 = AssetDat(version=0x102, files=[FileEntry(name="o2.w3d", file_time=0, assets=[])])

    combined = combine_asset_dats(base, overlay1, overlay2)

    assert [f.name for f in combined.files] == ["base.w3d", "o1.w3d", "o2.w3d"]


def test_combine_version_mismatch_warns_and_proceeds():
    base = AssetDat(version=0x102, files=[FileEntry(name="a.w3d", file_time=1, assets=[])])
    overlay = AssetDat(version=0x103, files=[FileEntry(name="b.w3d", file_time=2, assets=[])])

    with pytest.warns(VersionMismatchWarning, match="version mismatch"):
        combined = combine_asset_dats(base, overlay)

    assert combined.version == 0x102
    assert [f.name for f in combined.files] == ["a.w3d", "b.w3d"]


def test_combine_zero_overlays_returns_equal_content():
    base = AssetDat(
        version=0x102,
        files=[FileEntry(name="a.w3d", file_time=1, assets=[])],
        references=[ReferenceRecord(file_name="a.w3d", asset_name="A", references=["x"])],
    )

    combined = combine_asset_dats(base)

    assert combined == base
    assert combined.files is not base.files


def test_combine_write_round_trips():
    base = AssetDat(
        version=0x102,
        files=[
            FileEntry(
                name="a.w3d",
                file_time=1,
                assets=[Asset(name="A", type="MESH", offset=0, size=4)],
            )
        ],
        references=[ReferenceRecord(file_name="a.w3d", asset_name="A", references=["a.tga"])],
    )
    overlay = AssetDat(
        version=0x102,
        files=[
            FileEntry(
                name="b.w3d",
                file_time=2,
                assets=[Asset(name="B", type="HLOD", offset=0, size=0)],
            )
        ],
        references=[ReferenceRecord(file_name="b.w3d", asset_name="B", references=["b.tga"])],
    )

    combined = combine_asset_dats(base, overlay)
    round_tripped = parse_asset_dat(write_asset_dat(combined))

    expected = AssetDat(
        version=0x102,
        files=base.files + overlay.files,
        references=base.references + overlay.references,
    )
    assert round_tripped == expected


def test_shadowed_entries_tags_identical_and_changed_duplicates():
    unique = FileEntry(name="unique.tga", file_time=1, assets=[])
    same_first = FileEntry(
        name="same.tga", file_time=5, assets=[Asset(name="same.tga", type="TEX", offset=0, size=0)]
    )
    same_second = FileEntry(
        name="same.tga", file_time=5, assets=[Asset(name="same.tga", type="TEX", offset=0, size=0)]
    )
    changed_first = FileEntry(name="changed.tga", file_time=1, assets=[])
    changed_second = FileEntry(name="changed.tga", file_time=2, assets=[])
    ad = AssetDat(
        version=0x102,
        files=[unique, same_first, same_second, changed_first, changed_second],
    )

    shadowed = shadowed_entries(ad)

    assert len(shadowed) == 2
    by_name = {s.name: s for s in shadowed}
    assert by_name["same.tga"].entry is same_first
    assert by_name["same.tga"].winner is same_second
    assert by_name["same.tga"].identical is True
    assert by_name["changed.tga"].entry is changed_first
    assert by_name["changed.tga"].winner is changed_second
    assert by_name["changed.tga"].identical is False


def test_shadowed_entries_empty_without_duplicate_names():
    ad = AssetDat(version=0x102, files=[FileEntry(name="a.tga", file_time=1, assets=[])])

    assert shadowed_entries(ad) == []


def test_asset_counts_tallies_by_type():
    ad = AssetDat(
        version=0x102,
        files=[
            FileEntry(
                name="a.tga",
                file_time=0,
                assets=[Asset(name="a.tga", type="TEX", offset=0, size=0)],
            ),
            FileEntry(
                name="b.w3d",
                file_time=0,
                assets=[
                    Asset(name="B", type="MESH", offset=0, size=10),
                    Asset(name="B2", type="MESH", offset=10, size=10),
                ],
            ),
        ],
    )

    assert ad.asset_counts() == {"TEX": 1, "MESH": 2}
