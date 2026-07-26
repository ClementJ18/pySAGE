"""Low-level helpers for binary-patching a PE32 `game.dat`.

Everything here operates on an in-memory ``bytearray`` and pure ``struct`` reads - no pefile
dependency, so the patch pipeline stays light. Offsets are file offsets unless a name says ``va``
(virtual address) or ``rva`` (relative virtual address = va - ImageBase)."""

from __future__ import annotations

import logging
import struct

log = logging.getLogger("sage_patch")

# --- PE optional-header field offsets (relative to the optional header start) ---
_OPT_IMAGE_BASE = 28
_OPT_SECTION_ALIGNMENT = 32
_OPT_FILE_ALIGNMENT = 36
_OPT_SIZE_OF_IMAGE = 56
_OPT_SIZE_OF_HEADERS = 60
_SECTION_HEADER_SIZE = 40


def align_up(value: int, alignment: int) -> int:
    return (value + alignment - 1) & ~(alignment - 1)


def hexbytes(text: str) -> bytes:
    """`"68 d8 f3 c4 00"` -> the 5 raw bytes (spaces optional)."""
    return bytes.fromhex(text.replace(" ", ""))


def _coerce(value: bytes | bytearray | str) -> bytes:
    return hexbytes(value) if isinstance(value, str) else bytes(value)


# --- PE navigation -------------------------------------------------------------------------


def _e_lfanew(data: bytes | bytearray) -> int:
    return struct.unpack_from("<I", data, 0x3C)[0]


def _optional_header_offset(data: bytes | bytearray) -> int:
    return _e_lfanew(data) + 24  # 4-byte "PE\0\0" signature + 20-byte COFF file header


def image_base(data: bytes | bytearray) -> int:
    return struct.unpack_from("<I", data, _optional_header_offset(data) + _OPT_IMAGE_BASE)[0]


def va_to_offset(data: bytes | bytearray, va: int) -> int | None:
    """Map a virtual address to its file offset via the section table, or None if unmapped."""
    e = _e_lfanew(data)
    nsec = struct.unpack_from("<H", data, e + 6)[0]
    szopt = struct.unpack_from("<H", data, e + 20)[0]
    sectab = e + 24 + szopt
    rva = va - image_base(data)
    for i in range(nsec):
        o = sectab + i * _SECTION_HEADER_SIZE
        vsize, sva, rawsize, praw = struct.unpack_from("<IIII", data, o + 8)
        if sva <= rva < sva + max(vsize, rawsize):
            return praw + (rva - sva)
    return None


# --- editing -------------------------------------------------------------------------------


def apply_byte_patch(
    data: bytearray,
    file_off: int,
    old: bytes | bytearray | str,
    new: bytes | bytearray | str,
    note: str = "",
) -> None:
    """Overwrite ``old`` with ``new`` at ``file_off``, first asserting the bytes there match
    ``old`` (so a patch aimed at the wrong build fails loudly instead of corrupting it). ``old``
    and ``new`` may be hex strings or raw bytes, and must be the same length."""
    old_b, new_b = _coerce(old), _coerce(new)
    if len(old_b) != len(new_b):
        raise ValueError(f"{note}: length mismatch {len(old_b)} != {len(new_b)}")
    got = bytes(data[file_off : file_off + len(old_b)])
    if got != old_b:
        raise ValueError(f"{note} @0x{file_off:x}: expected {old_b.hex()} got {got.hex()}")
    data[file_off : file_off + len(new_b)] = new_b
    log.info("  ok  0x%06x  %s", file_off, note)


def next_section_rva(data: bytes | bytearray) -> int:
    """The RVA at which the next appended section would start: the highest section end
    (``VirtualAddress + VirtualSize``), rounded up to SectionAlignment. Pass this to
    :func:`append_section` so a cave lands past every existing section regardless of what else
    (e.g. another patch's section) has already been appended."""
    e = _e_lfanew(data)
    opt = _optional_header_offset(data)
    nsec = struct.unpack_from("<H", data, e + 6)[0]
    szopt = struct.unpack_from("<H", data, e + 20)[0]
    sec_align = struct.unpack_from("<I", data, opt + _OPT_SECTION_ALIGNMENT)[0]
    sectab = e + 24 + szopt
    max_end = 0
    for i in range(nsec):
        o = sectab + i * _SECTION_HEADER_SIZE
        vsize, sva = struct.unpack_from("<II", data, o + 8)
        max_end = max(max_end, sva + vsize)
    return align_up(max_end, sec_align)


def append_section(
    data: bytearray,
    name: str,
    rva: int,
    content: bytes,
    characteristics: int,
) -> int:
    """Add a new section carrying ``content`` at ``rva``: write its 40-byte header into the free
    space after the last header, append the (file-aligned) raw data, and bump NumberOfSections
    and SizeOfImage. Returns the section's base virtual address. Raises if the header block has no
    room for another entry."""
    e = _e_lfanew(data)
    opt = _optional_header_offset(data)
    nsec = struct.unpack_from("<H", data, e + 6)[0]
    szopt = struct.unpack_from("<H", data, e + 20)[0]
    sec_align = struct.unpack_from("<I", data, opt + _OPT_SECTION_ALIGNMENT)[0]
    file_align = struct.unpack_from("<I", data, opt + _OPT_FILE_ALIGNMENT)[0]
    size_of_headers = struct.unpack_from("<I", data, opt + _OPT_SIZE_OF_HEADERS)[0]

    sectab = e + 24 + szopt
    hdr_off = sectab + nsec * _SECTION_HEADER_SIZE
    if hdr_off + _SECTION_HEADER_SIZE > size_of_headers:
        raise ValueError("no room in the PE header for another section")

    vsize = len(content)
    raw_size = align_up(vsize, file_align)
    praw = align_up(len(data), file_align)

    hdr = bytearray(_SECTION_HEADER_SIZE)
    hdr[0:8] = name.encode("ascii").ljust(8, b"\x00")[:8]
    struct.pack_into("<IIII", hdr, 8, vsize, rva, raw_size, praw)
    struct.pack_into("<I", hdr, 36, characteristics)
    data[hdr_off : hdr_off + _SECTION_HEADER_SIZE] = hdr

    struct.pack_into("<H", data, e + 6, nsec + 1)  # NumberOfSections++
    struct.pack_into("<I", data, opt + _OPT_SIZE_OF_IMAGE, align_up(rva + vsize, sec_align))

    if len(data) < praw:  # pad the file up to the new section's raw pointer
        data += b"\x00" * (praw - len(data))
    data += content + b"\x00" * (raw_size - vsize)

    base_va = image_base(data) + rva
    log.info(
        "  new section %-8s rva=0x%x va=0x%x praw=0x%x vsize=0x%x rawsize=0x%x",
        name,
        rva,
        base_va,
        praw,
        vsize,
        raw_size,
    )
    return base_va
