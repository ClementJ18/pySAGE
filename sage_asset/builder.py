"""Builds an `AssetDat` model by scanning an unpacked SAGE art tree: `compiledtextures/` for
textures and `w3d/` for models. Each W3D file's chunk structure is walked to enumerate its
sub-assets (mesh/hierarchy/animation/HLOD/box) with their byte range and the textures a mesh
references, matching what the community `asset-combiner`/`AssetCacheBuilder` tools produce.
Ported from Brechstange's Edain-Toolbar (`core/utils/asset_builder.py`)."""

import os
import struct
import unicodedata
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import NamedTuple

from sage_asset.assetdat import Asset, AssetDat, FileEntry, ReferenceRecord, _decode_type

__all__ = ["build_asset_dat", "collect_art_index"]

# W3D chunk ids (the type discriminator at the start of every chunk header).
_CHUNK_MESH = 0x00000000
_CHUNK_HIERARCHY_DEF = 0x00000100
_CHUNK_ANIMATION = 0x00000200
_CHUNK_COMPRESSED_ANIMATION = 0x00000280
_CHUNK_HLOD = 0x00000700
_CHUNK_BOX = 0x00000740

_TEXTURE_EXTENSIONS = {".dds", ".tga", ".jpg", ".jpeg", ".png"}
_IGNORED_EXTENSIONS = {".ini", ".db", ".credits", ".lnk", ".txt", ".log"}
_EXTENSION_PRIORITY = {".dds": 0, ".tga": 1, ".jpg": 2, ".jpeg": 3, ".png": 4}

# Windows FILETIME (100ns ticks since 1601-01-01 UTC) of the Unix epoch.
_EPOCH_DIFF = 116_444_736_000_000_000


def _filetime_from_path(path: Path) -> int:
    try:
        mtime_ns = os.stat(path).st_mtime_ns
    except OSError:
        return 0
    return mtime_ns // 100 + _EPOCH_DIFF


def _latin1_safe(value: str) -> str:
    """`value` as it will strict-encode to latin-1 further down the write pipeline: any
    character outside the latin-1 range collapses to '?', the same lossy transform asset.dat
    names go through on disk."""
    return value.encode("latin-1", errors="replace").decode("latin-1")


def _ascii_lower(value: str) -> str:
    """Case-fold only ASCII A-Z. The HLOD reference names this is used for are built from
    names already put through `_latin1_safe` - i.e. already-encoded bytes - and are lowered as
    bytes there, which folds ASCII case only and leaves the high half of latin-1 untouched."""
    return value.encode("latin-1").lower().decode("latin-1")


def _parse_w3d_mesh_name(data: bytes, chunk_start: int) -> str:
    """The mesh chunk's `container.mesh` name from its 0x1F header sub-chunk, or "" if the
    sub-chunk is missing, of the wrong type, or too short to hold both name fields."""
    inner = chunk_start + 8
    if inner + 8 > len(data):
        return ""
    inner_type = struct.unpack("<I", data[inner : inner + 4])[0]
    inner_size = struct.unpack("<I", data[inner + 4 : inner + 8])[0] & 0x7FFFFFFF
    if inner_type != 0x1F or inner_size < 40:
        return ""
    hdr = data[inner + 8 : inner + 8 + inner_size]
    mesh_name = hdr[8:24].split(b"\x00")[0].decode("latin-1")
    container_name = hdr[24:40].split(b"\x00")[0].decode("latin-1")
    if container_name:
        return f"{container_name}.{mesh_name}"
    return mesh_name


def _parse_w3d_hierarchy_def_name(data: bytes, chunk_start: int) -> str:
    inner = chunk_start + 8
    if inner + 8 > len(data):
        return ""
    inner_type = struct.unpack("<I", data[inner : inner + 4])[0]
    inner_size = struct.unpack("<I", data[inner + 4 : inner + 8])[0] & 0x7FFFFFFF
    if inner_type != 0x0101 or inner_size < 20:
        return ""
    hdr = data[inner + 8 : inner + 8 + inner_size]
    return hdr[4:20].split(b"\x00")[0].decode("latin-1")


def _parse_w3d_animation_name(data: bytes, chunk_start: int, chunk_type: int) -> str:
    inner = chunk_start + 8
    if inner + 8 > len(data):
        return ""
    inner_type = struct.unpack("<I", data[inner : inner + 4])[0]
    inner_size = struct.unpack("<I", data[inner + 4 : inner + 8])[0] & 0x7FFFFFFF
    expected_sub = 0x0201 if chunk_type == _CHUNK_ANIMATION else 0x0281
    if inner_type != expected_sub or inner_size < 36:
        return ""
    hdr = data[inner + 8 : inner + 8 + inner_size]
    anim_name = hdr[4:20].split(b"\x00")[0].decode("latin-1")
    hier_name = hdr[20:36].split(b"\x00")[0].decode("latin-1")
    return f"A*{hier_name}.{anim_name}"


def _parse_w3d_hlod_header(data: bytes, chunk_start: int) -> tuple[str, str]:
    """The HLOD's own name and the hierarchy name it points at, from its 0x701 header
    sub-chunk - or `("", "")` if that sub-chunk is missing, of the wrong type, or too short."""
    inner = chunk_start + 8
    if inner + 8 > len(data):
        return "", ""
    inner_type = struct.unpack("<I", data[inner : inner + 4])[0]
    inner_size = struct.unpack("<I", data[inner + 4 : inner + 8])[0] & 0x7FFFFFFF
    if inner_type != 0x0701 or inner_size < 40:
        return "", ""
    hdr = data[inner + 8 : inner + 8 + inner_size]
    name = hdr[8:24].split(b"\x00")[0].decode("latin-1")
    hier_ref = hdr[24:40].split(b"\x00")[0].decode("latin-1")
    return name, hier_ref


def _is_texture_property(name: str) -> bool:
    return name.endswith("Texture") or name.startswith("Texture_")


def _walk_mesh_textures(data: bytes, start: int, end: int, textures: list[str]) -> None:
    """Collect texture names referenced by a mesh chunk's sub-chunks: `W3D_CHUNK_TEXTURE_NAME`
    (0x32) directly, and any shader material string property whose name looks like a texture
    slot (0x53, a string-valued property of type 1)."""
    pos = start
    while pos + 8 <= end:
        ctype = struct.unpack("<I", data[pos : pos + 4])[0]
        size_raw = struct.unpack("<I", data[pos + 4 : pos + 8])[0]
        size = size_raw & 0x7FFFFFFF
        has_sub_chunks = bool(size_raw & 0x80000000)

        if ctype == 0x32:
            tex = data[pos + 8 : pos + 8 + size].split(b"\x00")[0].decode("latin-1")
            if tex and tex not in textures:
                textures.append(tex)
        elif ctype == 0x53 and size >= 9:
            prop = data[pos + 8 : pos + 8 + size]
            prop_type = struct.unpack("<I", prop[0:4])[0]
            if prop_type == 1:
                name_len = struct.unpack("<I", prop[4:8])[0]
                if 8 + name_len + 4 <= len(prop):
                    pname = prop[8 : 8 + name_len].rstrip(b"\x00").decode("latin-1")
                    if _is_texture_property(pname):
                        val_off = 8 + name_len
                        val_len = struct.unpack("<I", prop[val_off : val_off + 4])[0]
                        val = (
                            prop[val_off + 4 : val_off + 4 + val_len]
                            .split(b"\x00")[0]
                            .decode("latin-1")
                        )
                        if val and val != "None" and val not in textures:
                            textures.append(val)

        if has_sub_chunks:
            _walk_mesh_textures(data, pos + 8, pos + 8 + size, textures)

        pos += 8 + size


def _parse_mesh_textures(data: bytes, chunk_start: int, chunk_total: int) -> list[str]:
    textures: list[str] = []
    _walk_mesh_textures(data, chunk_start + 8, chunk_start + chunk_total, textures)
    return textures


def _parse_w3d_box_name(data: bytes, chunk_start: int, chunk_total: int) -> str:
    box_data = data[chunk_start + 8 : chunk_start + chunk_total]
    if len(box_data) < 40:
        return ""
    # version(4) + attributes(4) + name(32, NUL-terminated)
    return box_data[8:40].split(b"\x00")[0].decode("latin-1")


class _SubChunk(NamedTuple):
    name: str
    type_tag: str
    offset: int
    size: int
    textures: list[str]
    hier_ref: str


def _iter_sub_chunks(data: bytes) -> Iterator[_SubChunk]:
    """Walk a W3D file's top-level chunks. A hierarchy-def or animation chunk whose inner
    header fails to parse is skipped entirely (no `_SubChunk` yielded, though its bytes are
    still consumed while walking); every other chunk kind always yields, even with an empty
    name. An unrecognized chunk id still yields, named `CHUNK_0x...`, with its type tag decoded
    from the raw chunk id the same way any on-disk type tag is - lossless for any 4 bytes, so
    writing it back out reproduces the identical chunk id."""
    pos = 0
    while pos + 8 <= len(data):
        ctype = struct.unpack("<I", data[pos : pos + 4])[0]
        size_raw = struct.unpack("<I", data[pos + 4 : pos + 8])[0]
        size = size_raw & 0x7FFFFFFF
        total = 8 + size

        if ctype == _CHUNK_MESH:
            name = _parse_w3d_mesh_name(data, pos)
            textures = _parse_mesh_textures(data, pos, total)
            yield _SubChunk(name, "MESH", pos, total, textures, "")
        elif ctype == _CHUNK_BOX:
            name = _parse_w3d_box_name(data, pos, total)
            yield _SubChunk(name, "BOX", pos, total, [], "")
        elif ctype == _CHUNK_HIERARCHY_DEF:
            name = _parse_w3d_hierarchy_def_name(data, pos)
            if name:
                yield _SubChunk(f"H*{name}", "HIER", pos, total, [], "")
        elif ctype in (_CHUNK_ANIMATION, _CHUNK_COMPRESSED_ANIMATION):
            name = _parse_w3d_animation_name(data, pos, ctype)
            if name:
                yield _SubChunk(name, "ANIM", pos, total, [], "")
        elif ctype == _CHUNK_HLOD:
            name, hier_ref = _parse_w3d_hlod_header(data, pos)
            yield _SubChunk(name, "HLOD", pos, total, [], hier_ref)
        else:
            type_tag = _decode_type(struct.pack("<I", ctype))
            yield _SubChunk(f"CHUNK_{ctype:#010x}", type_tag, pos, total, [], "")

        pos += total


def _collect_best_textures(compiledtextures_dir: Path) -> dict[str, Path]:
    """The winning file for each `.tga`-named entry under `compiledtextures_dir`: when more
    than one extension provides the same stem, the lowest-priority extension (dds < tga < jpg
    < jpeg < png) wins - every texture is stored as a TEX asset under its `.tga` name on disk
    regardless of which extension actually won."""
    if not compiledtextures_dir.is_dir():
        return {}

    best: dict[str, tuple[int, Path]] = {}
    for file in compiledtextures_dir.rglob("*"):
        if not file.is_file():
            continue
        ext = file.suffix.lower()
        if ext in _IGNORED_EXTENSIONS or ext not in _TEXTURE_EXTENSIONS:
            continue
        entry_name = _latin1_safe(unicodedata.normalize("NFC", file.stem + ".tga").lower())
        priority = _EXTENSION_PRIORITY.get(ext, 99)
        prev = best.get(entry_name)
        if prev is None or priority < prev[0]:
            best[entry_name] = (priority, file)

    return {entry_name: file for entry_name, (_, file) in best.items()}


def _collect_w3d_paths(w3d_dir: Path) -> list[Path]:
    """Every `.w3d` file under `w3d_dir`."""
    if not w3d_dir.is_dir():
        return []
    return [f for f in w3d_dir.rglob("*") if f.is_file() and f.suffix.lower() == ".w3d"]


def _w3d_entry_name(file: Path) -> str:
    """The on-disk entry name a `.w3d` source file gets."""
    return _latin1_safe(unicodedata.normalize("NFC", file.stem + ".w3d").lower())


def collect_art_index(art_dir: Path) -> dict[str, tuple[Path, int]]:
    """Every file `build_asset_dat` would index under `art_dir`, from its on-disk entry name
    to `(source_path, current FILETIME)` - the same texture-priority and naming rules
    `build_asset_dat` uses, but without walking any W3D chunk structure. For comparing an
    existing asset.dat against the art tree's current state (`sage-asset check --art`) without
    paying for a full rebuild."""
    index: dict[str, tuple[Path, int]] = {}
    for entry_name, file in _collect_best_textures(art_dir / "compiledtextures").items():
        index[entry_name] = (file, _filetime_from_path(file))
    for file in _collect_w3d_paths(art_dir / "w3d"):
        index[_w3d_entry_name(file)] = (file, _filetime_from_path(file))
    return index


def _collect_texture_entries(compiledtextures_dir: Path) -> Iterator[FileEntry]:
    """One `FileEntry` per distinct texture stem under `compiledtextures_dir` (see
    `_collect_best_textures` for which file wins a stem with more than one extension)."""
    best = _collect_best_textures(compiledtextures_dir)
    for entry_name in sorted(best):
        file = best[entry_name]
        yield FileEntry(
            name=entry_name,
            file_time=_filetime_from_path(file),
            assets=[Asset(name=entry_name, type="TEX", offset=0, size=0)],
        )


def _collect_w3d_entries(
    w3d_dir: Path, known_textures: set[str]
) -> Iterator[tuple[FileEntry, list[ReferenceRecord]]]:
    """One `(FileEntry, references)` pair per `.w3d` file under `w3d_dir`. A mesh's references
    are limited to textures also present under `compiledtextures/` (`known_textures`); an
    HLOD's references are its sub-object names seen so far in chunk order, plus a hierarchy
    reference - the file's own hierarchy-def if it has one, else `h*<hier_ref>` when `hier_ref`
    names a different, known w3d file."""
    all_w3d = _collect_w3d_paths(w3d_dir)
    known_w3d_stems = {unicodedata.normalize("NFC", f.stem).lower() for f in all_w3d}

    for file in sorted(all_w3d, key=lambda p: p.name.lower()):
        entry_name = _w3d_entry_name(file)
        data = file.read_bytes()

        assets: list[Asset] = []
        references: list[ReferenceRecord] = []
        sub_object_names: list[str] = []
        hier_def_name: str | None = None

        for chunk in _iter_sub_chunks(data):
            sub_name = _latin1_safe(chunk.name)
            assets.append(
                Asset(name=sub_name, type=chunk.type_tag, offset=chunk.offset, size=chunk.size)
            )

            if chunk.type_tag == "MESH":
                sub_object_names.append(sub_name)
                if chunk.textures:
                    known_tex = [
                        _latin1_safe(t.lower())
                        for t in chunk.textures
                        if _latin1_safe(t.lower()) in known_textures
                    ]
                    if known_tex:
                        references.append(
                            ReferenceRecord(
                                file_name=entry_name, asset_name=sub_name, references=known_tex
                            )
                        )
            elif chunk.type_tag == "BOX":
                sub_object_names.append(sub_name)
            elif chunk.type_tag == "HIER":
                hier_def_name = sub_name
            elif chunk.type_tag == "HLOD":
                refs = [_ascii_lower(name) for name in sub_object_names]
                if hier_def_name is not None:
                    refs.append(_ascii_lower(hier_def_name))
                elif (
                    chunk.hier_ref
                    and chunk.hier_ref.lower() != chunk.name.lower()
                    and chunk.hier_ref.lower() in known_w3d_stems
                ):
                    refs.append(_latin1_safe(f"h*{chunk.hier_ref.lower()}"))
                references.append(
                    ReferenceRecord(file_name=entry_name, asset_name=sub_name, references=refs)
                )

        yield (
            FileEntry(name=entry_name, file_time=_filetime_from_path(file), assets=assets),
            references,
        )


def build_asset_dat(
    art_dir: Path, *, progress: Callable[[int, str], None] | None = None
) -> AssetDat:
    """Scan `art_dir` (`compiledtextures/` and `w3d/`) and build the `AssetDat` model it
    describes. `progress` is called a handful of times with a 0-100 percentage and a short
    status message, for a UI to report while the scan runs."""
    compiledtextures_dir = art_dir / "compiledtextures"
    w3d_dir = art_dir / "w3d"

    if progress:
        progress(5, "Scanning texture files...")
    tex_entries: list[tuple[FileEntry, list[ReferenceRecord]]] = [
        (entry, []) for entry in _collect_texture_entries(compiledtextures_dir)
    ]
    known_textures = {entry.name for entry, _ in tex_entries}

    if progress:
        progress(30, "Scanning W3D model files...")
    w3d_entries = list(_collect_w3d_entries(w3d_dir, known_textures))

    if progress:
        progress(60, "Sorting entries...")
    entries = tex_entries + w3d_entries
    entries.sort(key=lambda pair: pair[0].name)

    if progress:
        progress(70, "Building the model...")
    files = [entry for entry, _ in entries]
    references = [ref for _, refs in entries for ref in refs]

    if progress:
        progress(100, "asset.dat built successfully.")

    return AssetDat(version=0x102, files=files, references=references)
