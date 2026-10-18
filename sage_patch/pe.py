"""Reading a PE32 image's section table, wherever the bytes happen to live.

The same walk - `0x3C` → `e_lfanew`, then NumberOfSections and SizeOfOptionalHeader, then
40-byte section headers - answers two different questions in this project: where a virtual
address sits in a **file** being patched, and where a section sits in a **running process**
being read. Only the byte source differs, so it is the byte source that is parameterised.

A `Reader` is any `(address, size) -> bytes | None`, addressed however its owner addresses
things: a file image is read at file offsets from zero, a live process at virtual addresses.
`image_sections` handles the first, `mapped_sections` the second.

Nothing here mutates. Section *creation* stays in `utils`, which owns the whole append-a-cave
operation and has to keep the headers, the raw data and `SizeOfImage` consistent together.
"""

from __future__ import annotations

import struct
from collections.abc import Callable
from dataclasses import dataclass

__all__ = [
    "OPT_IMAGE_BASE",
    "SECTION_HEADER_SIZE",
    "SHARED_SECTION_NAME",
    "SUBCAVE_ALIGN",
    "SUBCAVE_HEADER_SIZE",
    "SUBCAVE_MAGIC",
    "Reader",
    "Section",
    "image_sections",
    "mapped_sections",
    "read_headers",
]

# Optional-header field offsets, relative to the optional header start.
OPT_IMAGE_BASE = 28
SECTION_HEADER_SIZE = 40

# The section caves are packed into once the section table is full - see `_sub_caves`.
SHARED_SECTION_NAME = ".sgcaves"
SUBCAVE_MAGIC = b"SGCV"
SUBCAVE_HEADER_SIZE = 16
SUBCAVE_ALIGN = 16

Reader = Callable[[int, int], "bytes | None"]


@dataclass(frozen=True)
class Section:
    """One section header, with both addressings resolved."""

    name: str
    virtual_address: int  # absolute VA, ImageBase already added
    virtual_size: int
    raw_offset: int
    raw_size: int

    @property
    def mapped_size(self) -> int:
        """The span a VA lookup should consider - a section is mapped for the larger of its
        virtual and raw sizes, since either can exceed the other."""
        return max(self.virtual_size, self.raw_size)

    def contains(self, virtual_address: int) -> bool:
        return self.virtual_address <= virtual_address < self.virtual_address + self.mapped_size


@dataclass(frozen=True)
class Headers:
    """The few header fields a section walk needs."""

    e_lfanew: int
    image_base: int
    section_count: int
    section_table: int  # offset of the first section header, in the reader's addressing


def read_headers(read: Reader, base: int = 0) -> Headers | None:
    """Parse just enough of the PE headers to walk the section table.

    `base` is where the image starts in the reader's addressing: 0 for a file image, the
    ImageBase for a mapped one. Returns None for anything that is not a PE32 image, rather
    than raising - a caller that hands over a wrong process or a truncated file gets an
    answer it can report.
    """
    dos = read(base, 0x40)
    if not dos or len(dos) < 0x40 or dos[:2] != b"MZ":
        return None
    e_lfanew = struct.unpack_from("<I", dos, 0x3C)[0]
    # "PE\0\0" signature (4) + COFF file header (20) = 24 bytes before the optional header.
    coff = read(base + e_lfanew, 24)
    if not coff or len(coff) < 24 or coff[:4] != b"PE\x00\x00":
        return None
    section_count = struct.unpack_from("<H", coff, 6)[0]
    size_of_optional = struct.unpack_from("<H", coff, 20)[0]
    optional = read(base + e_lfanew + 24, OPT_IMAGE_BASE + 4)
    if not optional or len(optional) < OPT_IMAGE_BASE + 4:
        return None
    return Headers(
        e_lfanew=e_lfanew,
        image_base=struct.unpack_from("<I", optional, OPT_IMAGE_BASE)[0],
        section_count=section_count,
        section_table=base + e_lfanew + 24 + size_of_optional,
    )


def _sections(read: Reader, headers: Headers, load_base: int, *, mapped: bool) -> list[Section]:
    """`load_base` is what RVAs are relative to: the header's ImageBase for a file image, and
    the address the image is actually mapped at for a live one. Those agree only while the
    image loads at its preferred base, so the caller says which it means rather than this
    guessing from the header. `mapped` says the same of `read`: whether it is addressed by
    virtual address rather than file offset."""
    raw = read(headers.section_table, headers.section_count * SECTION_HEADER_SIZE)
    if not raw:
        return []
    out: list[Section] = []
    for i in range(headers.section_count):
        entry = raw[i * SECTION_HEADER_SIZE : (i + 1) * SECTION_HEADER_SIZE]
        if len(entry) < SECTION_HEADER_SIZE:
            break
        virtual_size, rva, raw_size, raw_offset = struct.unpack_from("<IIII", entry, 8)
        out.append(
            Section(
                name=entry[:8].rstrip(b"\x00").decode("latin-1"),
                virtual_address=load_base + rva,
                virtual_size=virtual_size,
                raw_offset=raw_offset,
                raw_size=raw_size,
            )
        )
    shared = find(out, SHARED_SECTION_NAME)
    if shared is not None:
        out.extend(_sub_caves(read, shared, mapped=mapped))
    return out


def _sub_caves(read: Reader, shared: Section, *, mapped: bool) -> list[Section]:
    """The caves packed into the shared section, each listed as a `Section` of its own so a
    lookup by name cannot tell a packed cave from one with its own section header.

    The shared section is a chain of `SUBCAVE_HEADER_SIZE`-byte headers - magic, 8-byte name,
    content size - each followed by its content, the next header at the following
    `SUBCAVE_ALIGN` boundary. The walk stops at the section's end or the first missing magic."""
    base = shared.virtual_address if mapped else shared.raw_offset
    out: list[Section] = []
    offset = 0
    while offset + SUBCAVE_HEADER_SIZE <= shared.virtual_size:
        header = read(base + offset, SUBCAVE_HEADER_SIZE)
        if not header or len(header) < SUBCAVE_HEADER_SIZE or header[:4] != SUBCAVE_MAGIC:
            break
        size = struct.unpack_from("<I", header, 12)[0]
        content = offset + SUBCAVE_HEADER_SIZE
        out.append(
            Section(
                name=header[4:12].rstrip(b"\x00").decode("latin-1"),
                virtual_address=shared.virtual_address + content,
                virtual_size=size,
                raw_offset=shared.raw_offset + content,
                raw_size=size,
            )
        )
        offset = (content + size + SUBCAVE_ALIGN - 1) & ~(SUBCAVE_ALIGN - 1)
    return out


def image_sections(data: bytes | bytearray) -> list[Section]:
    """Sections of a PE image held in memory as a file image (offsets from zero)."""

    def read(offset: int, size: int) -> bytes | None:
        if offset < 0 or offset + size > len(data):
            return None
        return bytes(data[offset : offset + size])

    headers = read_headers(read, 0)
    # A file image's VAs are its own ImageBase plus the RVA.
    return _sections(read, headers, headers.image_base, mapped=False) if headers else []


def mapped_sections(read: Reader, image_base: int) -> list[Section]:
    """Sections of a PE image mapped into a process, read by virtual address.

    The image's own headers are mapped at `image_base`, so the walk reads them from the
    process rather than needing the file on disk - which is what lets a client discover a
    section the running game carries without knowing where its `game.dat` lives.
    """
    headers = read_headers(read, image_base)
    # RVAs are relative to where the image is actually mapped, not to the ImageBase its
    # header prefers - those differ the moment an image is relocated.
    return _sections(read, headers, image_base, mapped=True) if headers else []


def find(sections: list[Section], name: str) -> Section | None:
    """The named section, or None. Names are compared as the 8-byte field stores them."""
    wanted = name.encode("ascii")[:8].rstrip(b"\x00").decode("latin-1")
    return next((s for s in sections if s.name == wanted), None)
