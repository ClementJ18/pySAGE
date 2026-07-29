"""The shared PE section walk, over both byte sources it serves."""

from __future__ import annotations

import struct

from sage_patch.pe import find, image_sections, mapped_sections, read_headers

IMAGE_BASE = 0x00400000


def build_image(sections: list[tuple[str, int, int, int, int]], size: int = 0x4000) -> bytearray:
    """`sections` are (name, virtual_size, rva, raw_size, raw_offset)."""
    data = bytearray(size)
    data[0:2] = b"MZ"
    e = 0x80
    struct.pack_into("<I", data, 0x3C, e)
    data[e : e + 4] = b"PE\x00\x00"
    struct.pack_into("<H", data, e + 4, 0x14C)  # Machine, at the COFF header start
    struct.pack_into("<H", data, e + 6, len(sections))
    struct.pack_into("<H", data, e + 20, 0xE0)  # SizeOfOptionalHeader
    opt = e + 24
    struct.pack_into("<H", data, opt, 0x10B)
    struct.pack_into("<I", data, opt + 28, IMAGE_BASE)
    table = opt + 0xE0
    for i, (name, vsize, rva, raw_size, raw_offset) in enumerate(sections):
        entry = bytearray(40)
        entry[0:8] = name.encode("ascii").ljust(8, b"\x00")[:8]
        struct.pack_into("<IIII", entry, 8, vsize, rva, raw_size, raw_offset)
        data[table + i * 40 : table + (i + 1) * 40] = entry
    return data


ONE = [(".text", 0x1000, 0x1000, 0x1000, 0x400)]


def test_headers_parse():
    headers = read_headers(lambda o, n: bytes(build_image(ONE)[o : o + n]), 0)
    assert headers is not None
    assert headers.image_base == IMAGE_BASE
    assert headers.section_count == 1


def test_a_non_pe_is_refused_rather_than_misparsed():
    assert read_headers(lambda o, n: bytes(bytearray(0x1000)[o : o + n]), 0) is None
    assert image_sections(bytearray(0x1000)) == []


def test_truncated_headers_are_refused():
    assert image_sections(bytearray(b"MZ")) == []


def test_file_image_sections_resolve_against_the_header_image_base():
    section = find(image_sections(build_image(ONE)), ".text")
    assert section is not None
    assert section.virtual_address == IMAGE_BASE + 0x1000
    assert section.raw_offset == 0x400


def test_a_mapped_image_resolves_against_where_it_is_actually_mapped():
    """The header records the *preferred* base; a relocated image is somewhere else, and the
    caller is the one that knows where."""
    data = build_image(ONE)
    relocated = 0x10000000

    def read(address: int, size: int) -> bytes | None:
        offset = address - relocated
        if offset < 0 or offset + size > len(data):
            return None
        return bytes(data[offset : offset + size])

    section = find(mapped_sections(read, relocated), ".text")
    assert section is not None
    assert section.virtual_address == relocated + 0x1000, "not the header's ImageBase"


def test_a_missing_section_is_none_not_an_error():
    assert find(image_sections(build_image(ONE)), ".nope") is None


def test_names_shorter_than_eight_bytes_match():
    section = find(
        image_sections(build_image([(".cmdext", 0x100, 0x2000, 0x100, 0x600)])), ".cmdext"
    )
    assert section is not None


def test_a_full_eight_byte_name_matches():
    """`.livebrg` fills the field exactly, with no NUL terminator."""
    section = find(
        image_sections(build_image([(".livebrg", 0x100, 0x2000, 0x100, 0x600)])), ".livebrg"
    )
    assert section is not None


def test_contains_spans_the_larger_of_virtual_and_raw_size():
    big_virtual = find(image_sections(build_image([(".bss", 0x8000, 0x1000, 0x10, 0x400)])), ".bss")
    assert big_virtual is not None
    assert big_virtual.mapped_size == 0x8000
    assert big_virtual.contains(IMAGE_BASE + 0x1000)
    assert big_virtual.contains(IMAGE_BASE + 0x8FFF)
    assert not big_virtual.contains(IMAGE_BASE + 0x9000)


def test_several_sections_are_all_found():
    data = build_image(
        [
            (".text", 0x1000, 0x1000, 0x1000, 0x400),
            (".rdata", 0x800, 0x2000, 0x800, 0x1400),
            (".livebrg", 0x400, 0x3000, 0x400, 0x1C00),
        ]
    )
    names = [s.name for s in image_sections(data)]
    assert names == [".text", ".rdata", ".livebrg"]
