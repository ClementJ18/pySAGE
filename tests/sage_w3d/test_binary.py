"""Data-free tests for the shared chunk-framing primitives in `sage_w3d.binary`: chunk head
round-trip (including the `flagged` bit), `FixedString`/`NulString` preserving raw bytes past a
NUL terminator, and `split_chunks`'s malformed-input signal."""

import struct

from sage_w3d.binary import FixedString, NulString, split_chunks, write_chunk, write_chunk_header


class TestChunkHeader:
    def test_write_then_split_round_trips_type_and_size(self):
        payload = b"hello!!!"
        data = write_chunk(0x1234, False, payload)
        entries = split_chunks(data)
        assert entries is not None
        assert len(entries) == 1
        assert entries[0].chunk_type == 0x1234
        assert entries[0].flagged is False
        assert entries[0].payload == payload

    def test_flagged_bit_is_captured_and_written_back(self):
        data = write_chunk(0x0100, True, b"xyz")
        entries = split_chunks(data)
        assert entries is not None
        assert entries[0].flagged is True
        # Bit 31 of the raw size field must actually be set on disk.
        _, raw_size = struct.unpack_from("<II", data, 0)
        assert raw_size & 0x80000000

    def test_size_field_excludes_the_flag_bit(self):
        header = write_chunk_header(0x01, True, 12)
        chunk_type, raw_size = struct.unpack_from("<II", header, 0)
        assert chunk_type == 0x01
        assert raw_size & 0x7FFFFFFF == 12
        assert raw_size & 0x80000000


class TestSplitChunks:
    def test_empty_payload_splits_to_no_entries(self):
        assert split_chunks(b"") == []

    def test_multiple_sibling_chunks_split_in_order(self):
        data = write_chunk(0x01, False, b"aaaa") + write_chunk(0x02, False, b"bb")
        entries = split_chunks(data)
        assert entries is not None
        assert [e.chunk_type for e in entries] == [0x01, 0x02]
        assert [e.payload for e in entries] == [b"aaaa", b"bb"]

    def test_truncated_header_returns_none(self):
        assert split_chunks(b"\x01\x02\x03") is None

    def test_overrunning_size_field_returns_none(self):
        header = write_chunk_header(0x01, False, 100)
        assert split_chunks(header + b"short") is None

    def test_header_offsets_are_relative_to_the_payload(self):
        data = write_chunk(0x01, False, b"aaaa") + write_chunk(0x02, False, b"bb")
        entries = split_chunks(data)
        assert entries is not None
        assert entries[0].header_offset == 0
        assert entries[1].header_offset == 8 + 4


class TestFixedString:
    def test_value_decodes_up_to_first_nul(self):
        fs = FixedString(raw=b"bone_l_arm\x00\x00\x00\x00\x00\x00")
        assert fs.value == "bone_l_arm"

    def test_garbage_after_nul_is_preserved_in_raw_and_round_trips(self):
        # A real 3ds Max exporter can leave leftover buffer contents after the NUL - the model
        # must reproduce those bytes exactly even though .value only reflects the name.
        raw = b"bone\x00garbage!!!!!!!!"[:16]
        fs = FixedString(raw=raw)
        assert fs.value == "bone"
        assert fs.write() == raw

    def test_from_value_nul_pads_to_width(self):
        fs = FixedString.from_value("hi", 8)
        assert fs.raw == b"hi\x00\x00\x00\x00\x00\x00"
        assert fs.value == "hi"

    def test_equality_compares_raw_not_value(self):
        a = FixedString(raw=b"bone\x00AAAAAAAAAAA")
        b = FixedString(raw=b"bone\x00BBBBBBBBBBB")
        assert a.value == b.value
        assert a != b


class TestNulString:
    def test_value_and_round_trip(self):
        ns = NulString.from_value("a_texture.tga")
        assert ns.value == "a_texture.tga"
        assert ns.write() == b"a_texture.tga\x00"

    def test_trailing_bytes_after_nul_are_preserved(self):
        raw = b"name\x00trailing junk"
        ns = NulString(raw=raw)
        assert ns.value == "name"
        assert ns.write() == raw
