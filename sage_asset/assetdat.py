"""Binary reader/writer for the SAGE engine's `asset.dat` file: the BFME2/RotWK asset cache
index of every source art file (`.w3d`/`.tga`/...), the individual assets each one provides
with their byte range inside it, and a dependency table of which assets reference which
other assets. See README.md for the full on-disk layout.

Every integer is little-endian. Every string is a uint8 length prefix followed by that many
latin-1 bytes (no NUL terminator). A type tag is stored byte-reversed and NUL-padded to 4
bytes on disk (`b"XET\\0"` <-> `"TEX"`); section 2 is kept as its own ordered list rather than
derived from section 1 because a community-built asset.dat can hold duplicate (file, asset)
entries and a different record order than section 1."""

import io
import struct
import warnings
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sage_utils.stream import BinaryStream

__all__ = [
    "Asset",
    "AssetDat",
    "AssetDatError",
    "FileEntry",
    "ReferenceRecord",
    "ShadowedEntry",
    "VersionMismatchWarning",
    "combine_asset_dats",
    "parse_asset_dat",
    "parse_asset_dat_from_path",
    "shadowed_entries",
    "write_asset_dat",
    "write_asset_dat_to_path",
]

_MAGIC = b"ALAE"

# Windows FILETIME: 100ns ticks since 1601-01-01 UTC.
_FILETIME_EPOCH = datetime(1601, 1, 1, tzinfo=UTC)
_FILETIME_TICKS_PER_SECOND = 10_000_000


class AssetDatError(Exception):
    """Raised for malformed asset.dat input (bad magic, truncated data) or a model that
    cannot be written back out (a string over 255 bytes, a count over its field width)."""


class VersionMismatchWarning(UserWarning):
    """Emitted by `combine_asset_dats` when an overlay's version differs from the base's."""


def _read_pstr(stream: BinaryStream) -> str:
    length = stream.readUChar()
    raw = stream.readBytes(length)
    if len(raw) != length:
        raise struct.error(f"pstr wants {length} bytes, got {len(raw)}")
    return raw.decode("latin-1")


def _write_pstr(stream: BinaryStream, value: str) -> None:
    raw = value.encode("latin-1")
    if len(raw) > 0xFF:
        raise AssetDatError(f"string {value!r} is {len(raw)} bytes, over the 255-byte pstr limit")
    stream.writeUChar(len(raw))
    stream.writeBytes(raw)


def _decode_type(raw: bytes) -> str:
    """Decode a 4-byte on-disk type tag: strip trailing NULs, then reverse the bytes."""
    decoded = raw.rstrip(b"\0")[::-1].decode("latin-1")
    if _encode_type(decoded) != raw:
        raise AssetDatError(f"type tag {raw!r} does not round-trip through decode/encode")
    return decoded


def _encode_type(type_: str) -> bytes:
    """Encode a decoded type tag back to its on-disk form: reverse it, NUL-pad to 4 bytes."""
    raw = type_.encode("latin-1")[::-1]
    if len(raw) > 4:
        raise AssetDatError(f"type tag {type_!r} is longer than 4 characters")
    return raw.ljust(4, b"\0")


@dataclass
class Asset:
    """One asset (mesh, texture, animation, ...) that a source file provides. `offset`/`size`
    locate its chunk inside the source file's bytes; both are 0 for a TEX asset, which is the
    whole source file rather than a sub-chunk of it."""

    name: str
    type: str
    offset: int
    size: int


@dataclass
class FileEntry:
    """One source art file the cache knows about, and the assets it provides."""

    name: str
    file_time: int
    assets: list[Asset] = field(default_factory=list)

    @property
    def modified(self) -> datetime:
        """`file_time` decoded to a timezone-aware UTC `datetime`."""
        seconds, ticks = divmod(self.file_time, _FILETIME_TICKS_PER_SECOND)
        return _FILETIME_EPOCH + timedelta(seconds=seconds, microseconds=ticks // 10)


@dataclass
class ReferenceRecord:
    """The references one asset (`asset_name`, defined in `file_name`) depends on. Only
    assets with at least one reference get a record, so this is not one-to-one with every
    `Asset` in section 1."""

    file_name: str
    asset_name: str
    references: list[str] = field(default_factory=list)


@dataclass
class AssetDat:
    """The full parsed contents of an asset.dat: section 1 (`files`) and section 2
    (`references`), kept as separate ordered lists - never derive one from the other, since a
    real-world file can order and duplicate them independently of section 1."""

    version: int
    files: list[FileEntry] = field(default_factory=list)
    references: list[ReferenceRecord] = field(default_factory=list)

    def file(self, name: str) -> FileEntry | None:
        """The `FileEntry` named `name`, matched case-insensitively, or `None`."""
        needle = name.lower()
        for entry in self.files:
            if entry.name.lower() == needle:
                return entry
        return None

    def references_for(self, file_name: str, asset_name: str) -> list[list[str]]:
        """Reference lists recorded for `asset_name` in `file_name`, matched case-insensitively.
        A list of ref-lists rather than a single list: duplicate (file, asset) section-2 records
        exist in the wild (Edain's `complete_asset/asset.dat`), each with its own reference list."""
        wanted = (file_name.lower(), asset_name.lower())
        return [
            list(record.references)
            for record in self.references
            if (record.file_name.lower(), record.asset_name.lower()) == wanted
        ]

    def asset_counts(self) -> dict[str, int]:
        """Number of assets of each type, across every file entry."""
        counts: dict[str, int] = {}
        for entry in self.files:
            for asset in entry.assets:
                counts[asset.type] = counts.get(asset.type, 0) + 1
        return counts


def combine_asset_dats(base: AssetDat, *overlays: AssetDat) -> AssetDat:
    """Concatenate `base` and `overlays`, in order: every file and reference of `base` first,
    then each overlay's in turn. This is what the community asset-combiner tool produces and
    the game loads - a later entry for a file name already present is how a mod's assets take
    effect over the base game's, so duplicate file names and duplicate (file, asset) reference
    pairs are kept rather than deduplicated. The result holds new `files`/`references` lists
    but the same `FileEntry`/`ReferenceRecord` objects as the inputs, so mutating one of them
    also mutates the corresponding input.

    A `VersionMismatchWarning` is emitted if an overlay's version differs from `base`'s -
    every known asset.dat is version 0x102, so a mismatch suggests the inputs come from
    different game generations rather than being a base/mod pair. The combination still
    proceeds, carrying `base`'s version."""
    for overlay in overlays:
        if overlay.version != base.version:
            warnings.warn(
                f"version mismatch: base is 0x{base.version:x}, overlay is 0x{overlay.version:x}",
                VersionMismatchWarning,
                stacklevel=2,
            )

    files = list(base.files)
    references = list(base.references)
    for overlay in overlays:
        files.extend(overlay.files)
        references.extend(overlay.references)

    return AssetDat(version=base.version, files=files, references=references)


@dataclass
class ShadowedEntry:
    """One occurrence of a file name that a later, same-named entry in `AssetDat.files`
    overrides - `entry` never takes effect at load time because `winner` (the last entry with
    that name) loads after it."""

    name: str
    entry: FileEntry
    winner: FileEntry

    @property
    def identical(self) -> bool:
        """True when `entry` matches `winner`'s `file_time` and asset list exactly - pure size
        bloat, an overlay re-shipping a base file unchanged, rather than an actual override."""
        return (
            self.entry.file_time == self.winner.file_time
            and self.entry.assets == self.winner.assets
        )


def shadowed_entries(ad: AssetDat) -> list[ShadowedEntry]:
    """Every file entry in `ad.files` that a later same-named entry shadows - the situation
    `combine_asset_dats` creates on purpose when an overlay overrides a base file. Grouped by
    name in order of first appearance; within a name, every occurrence but the last is paired
    with that last (winning) one, in `ad.files` order. A name appearing N times yields N-1
    entries here."""
    by_name: dict[str, list[FileEntry]] = {}
    for entry in ad.files:
        by_name.setdefault(entry.name.lower(), []).append(entry)

    result: list[ShadowedEntry] = []
    for name, entries in by_name.items():
        if len(entries) < 2:
            continue
        winner = entries[-1]
        result.extend(
            ShadowedEntry(name=name, entry=entry, winner=winner) for entry in entries[:-1]
        )
    return result


def _parse_asset(stream: BinaryStream) -> Asset:
    name = _read_pstr(stream)
    raw_type = stream.readBytes(4)
    if len(raw_type) != 4:
        raise struct.error(f"type tag wants 4 bytes, got {len(raw_type)}")
    type_ = _decode_type(raw_type)
    offset = stream.readUInt32()
    size = stream.readUInt32()
    return Asset(name=name, type=type_, offset=offset, size=size)


def _parse(stream: BinaryStream) -> AssetDat:
    magic = stream.readBytes(4)
    if magic != _MAGIC:
        raise AssetDatError(f"bad magic {magic!r} at offset 0, expected {_MAGIC!r}")

    try:
        version = stream.readUInt32()
        file_count = stream.readUInt32()
        ref_count = stream.readUInt32()
    except struct.error as exc:
        raise AssetDatError(f"truncated header at offset {stream.tell()}: {exc}") from exc

    files: list[FileEntry] = []
    for i in range(file_count):
        offset = stream.tell()
        try:
            name = _read_pstr(stream)
            file_time = stream.readUInt64()
            asset_count = stream.readUInt16()
            assets = [_parse_asset(stream) for _ in range(asset_count)]
        except struct.error as exc:
            raise AssetDatError(f"truncated section 1 entry {i} at offset {offset}: {exc}") from exc
        files.append(FileEntry(name=name, file_time=file_time, assets=assets))

    references: list[ReferenceRecord] = []
    for i in range(ref_count):
        offset = stream.tell()
        try:
            file_name = _read_pstr(stream)
            asset_name = _read_pstr(stream)
            n = stream.readUInt16()
            refs = [_read_pstr(stream) for _ in range(n)]
        except struct.error as exc:
            raise AssetDatError(
                f"truncated section 2 record {i} at offset {offset}: {exc}"
            ) from exc
        references.append(
            ReferenceRecord(file_name=file_name, asset_name=asset_name, references=refs)
        )

    return AssetDat(version=version, files=files, references=references)


def parse_asset_dat(data: bytes) -> AssetDat:
    """Parse the bytes of an asset.dat file into an `AssetDat`."""
    stream = BinaryStream(io.BytesIO(data))
    ad = _parse(stream)
    # The model must account for every input byte or writing it back would silently drop
    # whatever followed the last section-2 record.
    if stream.tell() != len(data):
        raise AssetDatError(
            f"{len(data) - stream.tell()} trailing bytes after the last section-2 record"
        )
    return ad


def parse_asset_dat_from_path(path: str | Path) -> AssetDat:
    """Parse the asset.dat file at `path` into an `AssetDat`."""
    with open(path, "rb") as f:
        return parse_asset_dat(f.read())


def write_asset_dat(ad: AssetDat) -> bytes:
    """Serialize `ad` back to asset.dat bytes."""
    stream = BinaryStream(io.BytesIO())
    stream.writeBytes(_MAGIC)
    stream.writeUInt32(ad.version)
    stream.writeUInt32(len(ad.files))
    stream.writeUInt32(len(ad.references))

    for entry in ad.files:
        _write_pstr(stream, entry.name)
        stream.writeUInt64(entry.file_time)
        if len(entry.assets) > 0xFFFF:
            raise AssetDatError(
                f"file {entry.name!r} has {len(entry.assets)} assets, over the uint16 field limit"
            )
        stream.writeUInt16(len(entry.assets))
        for asset in entry.assets:
            _write_pstr(stream, asset.name)
            stream.writeBytes(_encode_type(asset.type))
            stream.writeUInt32(asset.offset)
            stream.writeUInt32(asset.size)

    for record in ad.references:
        _write_pstr(stream, record.file_name)
        _write_pstr(stream, record.asset_name)
        if len(record.references) > 0xFFFF:
            raise AssetDatError(
                f"{record.file_name!r}/{record.asset_name!r} has {len(record.references)} "
                "references, over the uint16 field limit"
            )
        stream.writeUInt16(len(record.references))
        for ref in record.references:
            _write_pstr(stream, ref)

    return stream.getvalue()


def write_asset_dat_to_path(ad: AssetDat, path: str | Path) -> None:
    """Serialize `ad` and write it to `path`."""
    data = write_asset_dat(ad)
    with open(path, "wb") as f:
        f.write(data)
