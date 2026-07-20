"""Symbol manifest: a compact, per-source-file index of a loaded base game, and the loader that
rehydrates it back into a `Game` so a mod can be linted against base symbols with no base tree on
disk.

Linting a mod needs the base game loaded only so the mod's *references* resolve - the rules read
names, tables, classes, module tags, a handful of raw field values, and the game-level macro/
string/asset tables, never the base's full converted model. This module captures exactly that
much and no more (see `build_manifest`), serializes it as JSON (optionally gzipped), and on the
consuming side reconstructs base definitions as real `IniObject` instances registered in
`game.tables` - not a lookup side-table. The materialization is deliberate: `ChildObject.parent`,
`default_module_tags` and `levels_for_names` read `game.tables[...]` *directly*, bypassing
`lookup`'s reference fallback, so a stand-in only counts if it registers the ordinary way.

The file is the unit of fidelity because that is the granularity at which SAGE games shadow each
other: a manifest entry is keyed by its defining file's `ini_root`-relative path (the identity
`loader._rel_key` uses), so a mod file overriding a base file shadows the whole manifest entry,
and `load_manifest_into`'s `shadow` set drops the base definitions a mod already owns.

Forward reference edges are precomputed with `Xref` at build time and reattached as
`_manifest_edges`; `xref._object_references` folds them back through `game.lookup` so a base->mod
reverse edge lands exactly as a real combined load would give it (an unused-definition check
needs the base's outgoing edges to judge a mod definition that only a base entry names).

A manifest serves linting only. String *values* are dropped (labels alone are kept), so
value-reading consumers cannot run off one; that is the accepted trade for a load-free base.
"""

from __future__ import annotations

import gzip
import hashlib
import json
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

from sage_ini.loader import LoadedGame
from sage_ini.model.game import Game
from sage_ini.model.ini_objects import (
    AddModule,
    ChildObject,
    InheritableModule,
    ReplaceModule,
)
from sage_ini.model.objects import REGISTRY, IniObject, Module, get_class
from sage_ini.model.xref import Xref
from sage_ini.parser.ast import Block
from sage_ini.parser.io import MAP_SUFFIXES
from sage_ini.parser.location import Span
from sage_ini.stats import as_root_list, ini_root
from sage_utils.sources import LOAD_SUFFIXES, loadable_files

__all__ = [
    "FORMAT_VERSION",
    "ManifestError",
    "build_manifest",
    "write_manifest",
    "read_manifest",
    "source_digest",
    "manifest_matches_roots",
    "load_manifest_into",
    "game_from_manifest",
]

FORMAT_VERSION = 1

# Tables whose rules read raw field values, so the whole `_fields` dict is serialized: respawn
# levels (`levels`), revive buttons (`commandbuttons`), and the modifier-fx lifetime pair
# (`fxlists` + the `particlesystems` its nuggets name). Every other table needs only metadata.
RAW_FIELD_TABLES = frozenset({"levels", "commandbuttons", "particlesystems", "fxlists"})

# Suffixes the freshness digest walks: the loadable ini/str plus the `.map`/`.bse` layouts, the
# same set `sage_lint.linter`'s base merge uses - sourced here from sage_utils so sage_ini never
# imports sage_lint.
_DIGEST_SUFFIXES = LOAD_SUFFIXES | MAP_SUFFIXES


class ManifestError(Exception):
    """A manifest that cannot be trusted: unreadable, malformed, or an unsupported format
    version. Distinct from a plain parse error so a caller can treat a bad manifest as a hard
    stop rather than a lint finding."""


# --------------------------------------------------------------------------- generation


def _file_key(file: str, ini_roots: list[Path]) -> str:
    """A definition's file identity: its span file made `ini_root`-relative, lowercased and
    forward-slashed, matching `loader._rel_key` so a mod file shadows the manifest entry. Falls
    back to the bare name for a file under no known root."""
    resolved = Path(file).resolve()
    for base in ini_roots:
        try:
            return resolved.relative_to(base).as_posix().lower()
        except ValueError:
            continue
    return Path(file).name.lower()


def _rel_path(path: Path, roots: list[Path]) -> str:
    """A map file relative to the game root it lives under (maps sit at root level, outside
    `ini_root`), forward-slashed. Bare name if it belongs to none."""
    resolved = Path(path).resolve()
    for root in roots:
        try:
            return resolved.relative_to(root).as_posix()
        except ValueError:
            continue
    return Path(path).name


def _module_entries(obj: IniObject) -> list[list[str]]:
    """`[class, tag, group]` for every tagged module the module-op rules read off `obj`: typed
    modules (`_modules`), draws (`_nested_data["Draw"]`), untyped tagged blocks (`_extras`), and
    `InheritableModule` wrappers. Tag-less modules are skipped - consumers ignore them."""
    entries: list[list[str]] = []
    for module in obj._modules:
        tag = getattr(module, "tag", None)
        if tag:
            entries.append([type(module).__name__, tag, "modules"])
    for module in obj._nested_data.get("Draw", []):
        tag = getattr(module, "tag", None)
        if tag:
            entries.append([type(module).__name__, tag, "Draw"])
    for child in obj._extras:
        # The `_local_tagged` shape: an unmodeled `Class Tag` block contributes its tag mapped to
        # an unknown type, so an existence check still holds where the schema is incomplete.
        if isinstance(child, Block) and child.uses_equals and child.label:
            tokens = child.label.split()
            if len(tokens) >= 2:
                entries.append([tokens[0], tokens[1], "extras"])
    for wrapper in obj._nested_data.get("InheritableModule", []):
        module = wrapper.module
        tag = getattr(module, "tag", None) if module is not None else None
        if tag:
            entries.append([type(module).__name__, tag, "InheritableModule"])
    return entries


def _removed_tags(obj: IniObject) -> list[str]:
    """The `RemoveModule` tags declared on `obj`, as a list (the raw field is a scalar or list)."""
    value = obj._fields.get("RemoveModule")
    if value is None:
        return []
    return list(value) if isinstance(value, list) else [value]


def _edit_entries(obj: IniObject) -> dict[str, list]:
    """The inherited-module edits an object applies: `add` `[class, tag]`, `replace`
    `[old_tag, class, new_tag]`, `remove` `[tag, ...]`. Empty groups are omitted."""
    edits: dict[str, list] = {}
    add = []
    for wrapper in obj._nested_data.get("AddModule", []):
        module = wrapper.module
        tag = getattr(module, "tag", None) if module is not None else None
        if tag:
            add.append([type(module).__name__, tag])
    replace = []
    for wrapper in obj._nested_data.get("ReplaceModule", []):
        module = wrapper.module
        tag = getattr(module, "tag", None) if module is not None else None
        if tag:
            replace.append([wrapper.name, type(module).__name__, tag])
    remove = _removed_tags(obj)
    if add:
        edits["add"] = add
    if replace:
        edits["replace"] = replace
    if remove:
        edits["remove"] = remove
    return edits


def _nugget_fields(obj: IniObject, group: str) -> list[dict]:
    """Raw `_fields` of each nested nugget in `group` (an FXList's `BuffNugget`/`ParticleSystem`),
    for the modifier-fx lifetime comparison. Values are already `str | list[str]`, so JSON-safe."""
    return [dict(nugget._fields) for nugget in obj._nested_data.get(group, [])]


def _definition_record(obj: IniObject, xref: Xref, ini_roots: list[Path]) -> dict:
    """The manifest record for one registered definition: table, name, class, opening line, and
    the targeted extras each rule kind consults (empty keys omitted)."""
    record: dict = {
        "table": obj.key,
        "name": obj.name,
        "class": type(obj).__name__,
        "line": obj.span.line_start if obj.span is not None else 1,
    }
    if isinstance(obj, ChildObject) and obj.parent_name:
        record["parent"] = obj.parent_name
    if obj.key == "objects":
        modules = _module_entries(obj)
        if modules:
            record["modules"] = modules
        edits = _edit_entries(obj)
        if edits:
            record["edits"] = edits
    refs = sorted({(t.key, t.name) for t in xref.references(obj) if t.key is not None})
    if refs:
        record["refs"] = [list(ref) for ref in refs]
    if obj.key in RAW_FIELD_TABLES:
        fields = dict(obj._fields)
        if fields:
            record["fields"] = fields
        if obj.key == "fxlists":
            nuggets = {
                group: items
                for group in ("BuffNugget", "ParticleSystem")
                if (items := _nugget_fields(obj, group))
            }
            if nuggets:
                record["nuggets"] = nuggets
    return record


def build_manifest(loaded: LoadedGame, roots) -> dict:
    """Index a loaded base game into a format-`FORMAT_VERSION` manifest dict: every registered
    definition grouped under its defining file, plus the game-level macros, string labels, asset
    basenames and map paths the rules consult. Forward reference edges come from `Xref.for_game`,
    so the reverse edges a mod needs reconstruct on load. `roots` is the game root (or roots) the
    game was loaded from, used for the freshness digest and to make file/map paths relative."""
    game = loaded.game
    root_list = as_root_list(roots)
    ini_roots = [ini_root(root).resolve() for root in root_list]
    resolved_roots = [root.resolve() for root in root_list]
    xref = Xref.for_game(game)

    files: dict[str, list[dict]] = defaultdict(list)
    for table in game.tables.values():
        for obj in table.values():
            if obj.span is None:
                continue  # a definition with no source position has no file to key on
            key = _file_key(obj.span.file, ini_roots)
            files[key].append(_definition_record(obj, xref, ini_roots))
    for records in files.values():
        records.sort(key=lambda record: (record["table"], record["name"], record["line"]))

    file_count, digest = source_digest(root_list)
    return {
        "format": FORMAT_VERSION,
        "source": {
            "roots": [str(root) for root in root_list],
            "created": datetime.now(UTC).isoformat(),
            "file_count": file_count,
            "digest": digest,
        },
        "macros": dict(game.macros),
        "strings": sorted(game.strings),
        "assets": sorted(game.assets),
        "map_files": sorted(_rel_path(path, resolved_roots) for path in game.map_files),
        "files": {key: files[key] for key in sorted(files)},
    }


def write_manifest(data: dict, path: str | Path) -> Path:
    """Write `data` to `path` as JSON, gzip-compressed when the suffix is `.gz`. Returns where
    it landed, creating parent folders as needed."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, separators=(",", ":")).encode("utf-8")
    if path.suffix == ".gz":
        with gzip.open(path, "wb") as handle:
            handle.write(payload)
    else:
        path.write_bytes(payload)
    return path


def read_manifest(path: str | Path) -> dict:
    """The manifest at `path` (gunzipped when `.gz`), validated. Raises `ManifestError` on an
    unreadable/malformed file, a non-object payload, an unsupported `format`, or a missing top-
    level section - a bad manifest is a hard stop, not a silent partial load."""
    path = Path(path)
    try:
        raw = gzip.open(path, "rb").read() if path.suffix == ".gz" else path.read_bytes()
        data = json.loads(raw)
    except (OSError, ValueError) as exc:
        raise ManifestError(f"cannot read manifest {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ManifestError(f"manifest {path} is not a JSON object")
    version = data.get("format")
    if version != FORMAT_VERSION:
        raise ManifestError(
            f"manifest {path} has unsupported format {version!r} (expected {FORMAT_VERSION})"
        )
    for section, kind in (("files", dict), ("macros", dict), ("strings", list), ("assets", list)):
        if not isinstance(data.get(section), kind):
            raise ManifestError(f"manifest {path} is missing a valid {section!r} section")
    return data


def source_digest(roots) -> tuple[int, str]:
    """`(file_count, sha256)` over the loadable files under `roots`: a hash of the sorted
    `relpath|size|mtime_ns` lines. Metadata only, never file contents - a base tree is thousands
    of files. The advisory freshness signal `manifest_matches_roots` compares against."""
    lines: list[str] = []
    for root in as_root_list(roots):
        for rel, path in loadable_files(Path(root), _DIGEST_SUFFIXES):
            stat = path.stat()
            lines.append(f"{rel}|{stat.st_size}|{stat.st_mtime_ns}")
    lines.sort()
    digest = hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()
    return len(lines), digest


def manifest_matches_roots(data: dict, roots) -> bool:
    """Whether `data`'s recorded digest still matches `roots` on disk - an advisory "is this
    manifest stale?" check for regeneration, never a load gate (nothing auto-invalidates)."""
    _, digest = source_digest(roots)
    source = data.get("source")
    return isinstance(source, dict) and source.get("digest") == digest


# --------------------------------------------------------------------------- loading


def _definition_class(class_name: str | None, table: str) -> type[IniObject]:
    """The class to build a definition record with: its recorded class when that class still
    registers into `table`, else any registered class with the same table key (so an
    unknown-at-load class name still lands the stand-in in the right table)."""
    cls = get_class(class_name) if class_name else None
    if cls is not None and cls.key == table:
        return cls
    for candidate in REGISTRY.values():
        if candidate.key == table:
            return candidate
    raise ManifestError(f"no registered class for table {table!r}")


def _extras_block(class_name: str, tag: str, span: Span) -> Block:
    """The unmodeled-module shape `module_ops._local_tagged` reads from `_extras`: a `Class Tag`
    block whose tag exists but whose type is unknown."""
    return Block(name=class_name, label=f"{class_name} {tag}", uses_equals=True, span=span)


def _module_standin(game: Game, class_name: str, tag: str, span: Span) -> Module:
    """A `Module` instance named `"Class Tag"` so `.tag` (and the replace-module type check)
    resolve. Uses the real class when it is a known module type, else a bare `Module` - callers
    that must have a `.module` (edits, inheritables) accept the untyped fallback."""
    cls = get_class(class_name)
    if not (isinstance(cls, type) and issubclass(cls, Module)):
        cls = Module
    return cls(f"{class_name} {tag}", game, {}, [], span=span)


def _place_module(
    game: Game,
    class_name: str,
    tag: str,
    span: Span,
    target: list,
    extras: list,
) -> None:
    """Add a `_modules`/`Draw` module: a typed stand-in when the class is a known module type,
    else the untyped `_extras` block shape. Either way the tag is visible to `_local_tagged`."""
    cls = get_class(class_name)
    if isinstance(cls, type) and issubclass(cls, Module):
        target.append(cls(f"{class_name} {tag}", game, {}, [], span=span))
    else:
        extras.append(_extras_block(class_name, tag, span))


def _load_record(game: Game, record: dict, virtual_root: Path, rel_file: str) -> None:
    """Materialize one definition record as a real `IniObject` registered in `game`, with its
    modules/edits/parent/refs reconstructed to whatever shape each consumer reads."""
    table = record["table"]
    span = Span(str(virtual_root / rel_file), record.get("line", 1), record.get("line", 1))
    cls = _definition_class(record.get("class"), table)

    fields: dict = dict(record.get("fields", {})) if table in RAW_FIELD_TABLES else {}
    extras: list = []
    modules: list = []
    nested_data: dict[str, list] = {}

    for class_name, tag, group in record.get("modules", []):
        if group == "extras":
            extras.append(_extras_block(class_name, tag, span))
        elif group == "InheritableModule":
            standin = _module_standin(game, class_name, tag, span)
            nested_data.setdefault("InheritableModule", []).append(
                InheritableModule("InheritableModule", game, {}, [], modules=[standin], span=span)
            )
        elif group == "Draw":
            _place_module(game, class_name, tag, span, nested_data.setdefault("Draw", []), extras)
        else:
            _place_module(game, class_name, tag, span, modules, extras)

    edits = record.get("edits", {})
    for class_name, tag in edits.get("add", []):
        standin = _module_standin(game, class_name, tag, span)
        nested_data.setdefault("AddModule", []).append(
            AddModule("AddModule", game, {}, [], modules=[standin], span=span)
        )
    for old_tag, class_name, tag in edits.get("replace", []):
        standin = _module_standin(game, class_name, tag, span)
        nested_data.setdefault("ReplaceModule", []).append(
            ReplaceModule(old_tag, game, {}, [], modules=[standin], span=span)
        )
    if edits.get("remove"):
        fields["RemoveModule"] = edits["remove"]

    if table == "fxlists":
        for group, items in record.get("nuggets", {}).items():
            nugget_cls = get_class(group)
            if not isinstance(nugget_cls, type):
                continue
            nested_data.setdefault(group, []).extend(
                nugget_cls(group, game, dict(item), [], span=span) for item in items
            )

    obj = cls(record["name"], game, fields, extras, nested_data, modules, span=span)
    if isinstance(obj, ChildObject) and record.get("parent"):
        obj.parent_name = record["parent"]
    obj._manifest_edges = tuple((ref[0], ref[1]) for ref in record.get("refs", []))


def load_manifest_into(
    game: Game,
    data: dict,
    virtual_root: Path,
    shadow: frozenset[str] = frozenset(),
) -> None:
    """Seed `game` with the manifest's base definitions and game-level tables, so a mod built on
    top resolves its references. Each definition registers the ordinary way (real class, real
    `IniObject.__init__`) under a synthetic `virtual_root`-anchored span, so the linter's
    `exclude` mechanism silences base diagnostics with no new origin flag. A file whose relpath
    is in `shadow` (a path the mod already owns) is skipped, matching file-level shadowing."""
    for rel_file, records in data.get("files", {}).items():
        if rel_file in shadow:
            continue
        for record in records:
            _load_record(game, record, virtual_root, rel_file)
    game.add_macros(data.get("macros", {}))
    game.strings.update(dict.fromkeys(data.get("strings", []), ""))
    game.assets.update(data.get("assets", []))
    game.map_files.extend(virtual_root / path for path in data.get("map_files", []))


def game_from_manifest(path: str | Path, virtual_root: Path | None = None) -> Game:
    """A fresh `Game` seeded from the manifest at `path`. `virtual_root` anchors the synthetic
    spans (defaulting to the manifest's own folder) - a caller layering a mod on top passes the
    mod root so shadowing and `exclude` line up."""
    data = read_manifest(path)
    game = Game()
    root = Path(virtual_root) if virtual_root is not None else Path(path).resolve().parent
    load_manifest_into(game, data, root)
    return game
