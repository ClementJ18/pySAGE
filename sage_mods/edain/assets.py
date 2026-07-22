"""Walk the on-disk assets an ini object references, sized against an art tree.

Given an object (a unit, a structure, a particle system, a mapped image, ...), this gathers
every `.w3d` model it can show - one per model-condition state, animation clips, the skeletons
a skinned mesh's HLOD pulls in - and every texture it names, whether in a typed field (a draw's
`Texture`, a particle system's `ParticleName`, a mapped image's `Texture`) or inside those
`.w3d` files, and resolves each to its file size in an `ArtIndex`. Nothing here decides *which*
objects belong together - a caller passes the objects it cares about and each asset is counted
once across them.

File size stands in for RAM weight as a deliberate first-order estimate: a `.dds` stays
block-compressed in memory the way it sits on disk, a `.tga` is raw both places, and a `.w3d`'s
geometry loads roughly 1:1 - none of this accounts for mipmaps, engine padding or streaming, but
it is the number available without decoding every asset.
"""

import csv
import struct
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TextIO

from sage_asset import w3d_references
from sage_ini.model.draw import Animation, ModelConditionState
from sage_ini.model.objects import IniObject
from sage_ini.model.types import _ModelFile, _TextureFile
from sage_ini.walk import walk_asset_fields, walk_objects
from sage_utils.sources import big_entry_basename

__all__ = ["ArtIndex", "AssetRecord", "object_assets", "write_csv"]

_TEXTURE_EXTENSIONS = (".dds", ".tga")
_TEXTURE_PRIORITY = {".dds": 0, ".tga": 1}
_MODEL_EXTENSION = ".w3d"


@dataclass(frozen=True)
class _Found:
    """One resolved asset: its on-disk display name (original case for a loose file, lower-cased
    for a `.big` entry), byte size, origin (a folder path or `.big` path - the CSV `source`
    column), and a lazy loader for its bytes."""

    name: str
    size: int
    origin: str
    load: Callable[[], bytes]


def _keep_best_texture(textures: dict[str, _Found], stem: str, suffix: str, found: _Found) -> None:
    """Record `found` for `stem` in this source's texture map unless it already holds a
    lower-priority extension for the same stem (`.dds` beats `.tga` - the engine/cache's own
    texture priority); a tie keeps the first one seen."""
    current = textures.get(stem)
    if current is not None:
        current_suffix = Path(current.name).suffix.lower()
        if _TEXTURE_PRIORITY[current_suffix] <= _TEXTURE_PRIORITY[suffix]:
            return
    textures[stem] = found


class ArtIndex:
    """Where assets live and how big they are: two case-insensitive maps, keyed by lower-cased
    stem, built from a priority-ordered list of art sources (loose folders or `.big` archives). A
    later source overrides an earlier one for the same stem - the mod-over-base ordering a caller
    layering a base game under a mod wants."""

    def __init__(self) -> None:
        self.textures: dict[str, _Found] = {}
        self.models: dict[str, _Found] = {}

    @classmethod
    def build(cls, sources: Sequence[Path]) -> "ArtIndex":
        """An index over `sources` in ascending priority - a later source's assets override an
        earlier source's for the same stem. Each source is a folder (crawled for `.w3d`/`.tga`/
        `.dds`) or a `.big` archive."""
        index = cls()
        for source in sources:
            if source.is_dir():
                index._merge_folder(source)
            else:
                index._merge_big(source)
        return index

    def _merge_folder(self, folder: Path) -> None:
        origin = str(folder)
        textures: dict[str, _Found] = {}
        models: dict[str, _Found] = {}
        for path in sorted(folder.rglob("*")):
            if not path.is_file():
                continue
            suffix = path.suffix.lower()
            stem = path.stem.lower()
            if suffix in _TEXTURE_EXTENSIONS:
                found = _Found(path.name, path.stat().st_size, origin, path.read_bytes)
                _keep_best_texture(textures, stem, suffix, found)
            elif suffix == _MODEL_EXTENSION:
                models[stem] = _Found(path.name, path.stat().st_size, origin, path.read_bytes)
        self.textures.update(textures)
        self.models.update(models)

    def _merge_big(self, big_path: Path) -> None:
        from pyBIG import InDiskArchive  # noqa: PLC0415 - lazy: the [ui]/[wiki] extra is optional

        origin = str(big_path)
        archive = InDiskArchive(str(big_path))

        def load(name: str) -> Callable[[], bytes]:
            return lambda: archive.read_file(name)

        textures: dict[str, _Found] = {}
        models: dict[str, _Found] = {}
        for entry_name in archive.file_list():
            basename = big_entry_basename(entry_name)  # already lower-cased
            suffix = Path(basename).suffix
            if suffix not in _TEXTURE_EXTENSIONS and suffix != _MODEL_EXTENSION:
                continue
            stem = Path(basename).stem
            size = archive.get_file_entry(entry_name).size
            found = _Found(basename, size, origin, load(entry_name))
            if suffix in _TEXTURE_EXTENSIONS:
                _keep_best_texture(textures, stem, suffix, found)
            else:
                models[stem] = found
        self.textures.update(textures)
        self.models.update(models)

    def read_w3d(self, stem: str) -> bytes | None:
        """The bytes of the model resolved for `stem` (case-insensitive), or None when no art
        source ships it."""
        found = self.models.get(stem.lower())
        return found.load() if found is not None else None


@dataclass
class AssetRecord:
    """One deduplicated asset: its winning on-disk name, kind, byte size (None when no art source
    ships it), origin (a folder/`.big` path, or `"missing"`), and every referrer that named it."""

    name: str
    kind: str  # "model" | "animation" | "texture"
    size: int | None
    source: str
    referrers: list[str] = field(default_factory=list)

    @property
    def ref_count(self) -> int:
        return len(self.referrers)


@dataclass
class _Pending:
    """One not-yet-resolved pool entry while `object_assets` walks: its kind (fixed the first time
    the stem is seen) and every referrer that has named it so far."""

    kind: str
    referrers: set[str] = field(default_factory=set)


def _touch(pool: dict[str, _Pending], stem: str | None, kind: str, referrer: str) -> None:
    """Record one more reference to `stem` in `pool` (a no-op for an unusable stem)."""
    if not stem:
        return
    pending = pool.setdefault(stem, _Pending(kind=kind))
    pending.referrers.add(referrer)


def _normalize_asset_name(raw: str | None) -> str | None:
    """The lower-cased stem `raw` names, or None for a value that names no real asset: empty, the
    `NONE` sentinel, an unresolved `<...>` placeholder, or nothing once quotes, directory and
    extension are stripped."""
    if raw is None:
        return None
    text = raw.strip().strip('"')
    if not text or text.upper() == "NONE" or text.startswith("<"):
        return None
    basename = text.replace("\\", "/").rsplit("/", 1)[-1].strip()
    stem = basename.rsplit(".", 1)[0] if "." in basename else basename
    stem = stem.strip().lower()
    return stem or None


def _animation_stem(value: str) -> str | None:
    """The w3d stem an `AnimationName` clip (`RuGlorfindel_SKL.RuGlorfindel_ATKA`) ships in: the
    part after the last `.`, lower-cased - the animation's own file, distinct from the skeleton
    named before the dot. Falls back to the whole value when it carries no dot."""
    text = value.strip()
    if not text:
        return None
    return text.rsplit(".", 1)[-1].lower() or None


def _raw_lines(node: IniObject, field_name: str) -> list[str]:
    """`node`'s raw, unconverted value(s) for `field_name`, always a list of lines (one per
    occurrence). Reads the field directly rather than through lazy conversion - these fields are
    typed as opaque/untyped tokens, and the plain text is exactly what's wanted here."""
    raw = node._fields.get(field_name)
    if raw is None:
        return []
    return raw if isinstance(raw, list) else [raw]


# Untyped per-line texture-swap fields: any token whose lowercase ends `.tga`/`.dds` names a
# texture, on whatever kind of draw node carries the field.
_TEXTURE_TOKEN_FIELDS = ("RandomTexture", "TimeOfDayTexture", "WeatherTexture")


def _collect_direct_assets(
    obj: IniObject, textures: dict[str, _Pending], w3ds: dict[str, _Pending]
) -> None:
    """Every typed `_TextureFile`/`_ModelFile` field anywhere under `obj`'s own subtree (a
    `MappedImage`'s `Texture`, a model draw's `Texture`/`TrackMarks`, a particle system's
    `ParticleName`, ...), attributed to `obj` itself - the object being walked, not whatever
    nested block actually carries the field, so a default and a damaged state naming the same
    model both count `obj` as a single referrer."""
    for _node, _field, asset_cls, raw in walk_asset_fields(obj):
        if issubclass(asset_cls, _TextureFile):
            _touch(textures, _normalize_asset_name(raw), "texture", obj.name)
        elif issubclass(asset_cls, _ModelFile):
            _touch(w3ds, _normalize_asset_name(raw), "model", obj.name)


def _collect_draw_assets(
    obj: IniObject, textures: dict[str, _Pending], w3ds: dict[str, _Pending]
) -> None:
    """Draw fields the typed asset walk can't see: `ModelConditionState.Model` raw lines
    (`t.RawList`, not a typed `ModelFile`), an `Animation` clip's own w3d, and the untyped
    `RandomTexture`/`TimeOfDayTexture`/`WeatherTexture` swap lists."""
    for node in walk_objects(obj):
        if isinstance(node, ModelConditionState):
            for line in _raw_lines(node, "Model"):
                tokens = line.split()
                token = tokens[0] if tokens else None
                _touch(w3ds, _normalize_asset_name(token), "model", obj.name)
        if isinstance(node, Animation):
            for line in _raw_lines(node, "AnimationName"):
                _touch(w3ds, _animation_stem(line), "animation", obj.name)
        for field_name in _TEXTURE_TOKEN_FIELDS:
            for line in _raw_lines(node, field_name):
                for token in line.split():
                    if token.lower().endswith((".tga", ".dds")):
                        _touch(textures, _normalize_asset_name(token), "texture", obj.name)


def _expand_w3d_pool(
    art: ArtIndex, w3ds: dict[str, _Pending], textures: dict[str, _Pending]
) -> None:
    """Breadth-first over the w3d pool, so a skeleton pulled in by one model can itself pull in
    another without looping: each stem `art` resolves is opened once and its own `w3d_references`
    folded in - mesh textures into the texture pool, an external hierarchy stem back into the w3d
    pool - both attributed to *this file*, not whatever object first named it. A stem `art` can't
    resolve, or a file too malformed to parse, simply contributes nothing further; it still
    surfaces as a `missing` (or size-less) record."""
    expanded: set[str] = set()
    queue = list(w3ds)
    while queue:
        stem = queue.pop(0)
        if stem in expanded:
            continue
        expanded.add(stem)
        data = art.read_w3d(stem)
        if data is None:
            continue
        found = art.models.get(stem)
        referrer = found.name if found is not None else stem
        try:
            refs = w3d_references(data)
        except (struct.error, ValueError):
            continue  # malformed art must not crash a diagnostic-free tool
        for texture in refs.textures:
            _touch(textures, _normalize_asset_name(texture), "texture", referrer)
        for hier_stem in refs.hierarchies:
            _touch(w3ds, hier_stem, "model", referrer)
            if hier_stem not in expanded:
                queue.append(hier_stem)


def _build_records(pool: dict[str, _Pending], resolved: dict[str, _Found]) -> list[AssetRecord]:
    """One `AssetRecord` per pooled stem: the winning on-disk file from `resolved` when an art
    source ships one, else a synthetic `<stem>.<ext>` name with no size and `source="missing"`."""
    records = []
    for stem, pending in pool.items():
        found = resolved.get(stem)
        if found is not None:
            records.append(
                AssetRecord(
                    name=found.name,
                    kind=pending.kind,
                    size=found.size,
                    source=found.origin,
                    referrers=sorted(pending.referrers),
                )
            )
        else:
            ext = ".tga" if pending.kind == "texture" else ".w3d"
            records.append(
                AssetRecord(
                    name=f"{stem}{ext}",
                    kind=pending.kind,
                    size=None,
                    source="missing",
                    referrers=sorted(pending.referrers),
                )
            )
    return records


def object_assets(objects: Iterable[IniObject], art: ArtIndex) -> list[AssetRecord]:
    """Every asset (model, animation clip, texture) `objects` reference, deduplicated by stem: the
    typed and untyped asset fields under each object's own subtree, expanded through each resolved
    w3d's own mesh textures and external skeleton. Each object contributes only its own subtree -
    references it makes to *other* objects are not followed - so a caller controls the scope by
    which objects it passes. Order is unspecified; `write_csv` sorts."""
    textures: dict[str, _Pending] = {}
    w3ds: dict[str, _Pending] = {}
    for obj in objects:
        _collect_direct_assets(obj, textures, w3ds)
        _collect_draw_assets(obj, textures, w3ds)

    _expand_w3d_pool(art, w3ds, textures)

    return _build_records(textures, art.textures) + _build_records(w3ds, art.models)


def write_csv(records: Sequence[AssetRecord], out: TextIO) -> None:
    """The per-asset report: `asset,kind,size_bytes,ref_count,references,source`, one row per
    record, sorted so the biggest resolved assets lead and every `missing` one (unknown size)
    sinks last."""
    writer = csv.writer(out)
    writer.writerow(["asset", "kind", "size_bytes", "ref_count", "references", "source"])
    ordered = sorted(records, key=lambda r: (r.size is None, -(r.size or 0), r.name.lower()))
    for record in ordered:
        writer.writerow(
            [
                record.name,
                record.kind,
                "" if record.size is None else record.size,
                record.ref_count,
                ";".join(record.referrers),
                record.source,
            ]
        )
