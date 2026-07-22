"""Traversal over the two sage_ini structures: `walk_nodes`/`walk_blocks` descend the
comment-preserving AST, `walk_objects` descends the typed `Game` (or any `IniObject`);
`walk_asset_fields` narrows that further to the on-disk asset references typed fields carry."""

from collections.abc import Iterator

from sage_ini.model.game import Game
from sage_ini.model.objects import IniObject, resolve_annotation
from sage_ini.model.types import KeyedRecord, _AssetFile
from sage_ini.parser.ast import Block, IniDocument, Node

__all__ = ["walk_asset_fields", "walk_blocks", "walk_nodes", "walk_objects"]


def walk_nodes(root: IniDocument | Node) -> Iterator[Node]:
    """Every AST node under `root`, depth-first pre-order (a node yields itself, then a
    `Block`'s children). Script bodies are opaque, so a `ScriptBlock` has no child nodes."""
    if isinstance(root, IniDocument):
        for child in root.children:
            yield from walk_nodes(child)
        return
    yield root
    if isinstance(root, Block):
        for child in root.children:
            yield from walk_nodes(child)


def walk_blocks(root: IniDocument | Node, name: str | None = None) -> Iterator[Block]:
    """Every `Block` under `root`; with `name`, only blocks of that header name."""
    for node in walk_nodes(root):
        if isinstance(node, Block) and (name is None or node.name == name):
            yield node


def walk_objects(root: Game | IniObject, cls: type[IniObject] | None = None) -> Iterator[IniObject]:
    """Every typed object under `root`, depth-first (an `IniObject` yields itself, then its
    nested-group children and modules). With `cls`, only instances of that class."""
    for obj in _iter_objects(root):
        if cls is None or isinstance(obj, cls):
            yield obj


def _iter_objects(root: Game | IniObject) -> Iterator[IniObject]:
    if isinstance(root, Game):
        for table in root.tables.values():
            for obj in table.values():
                yield from _iter_objects(obj)
        return
    yield root
    for items in root._nested_data.values():
        for item in items:
            yield from _iter_objects(item)
    for module in root._modules:
        yield from _iter_objects(module)


def walk_asset_fields(
    root: Game | IniObject,
) -> Iterator[tuple[IniObject, str, type[_AssetFile], str]]:
    """`(obj, field, asset_class, raw_name)` for every `_AssetFile`-typed slot reachable under
    `root`: a bare asset field, one inside a `List`/`Tuple`, or a `KeyedRecord`'s typed key.
    `root` may be the whole `Game` (every typed field) or a single `IniObject` subtree - what a
    scoped tool (e.g. a per-faction asset count) needs."""
    for obj in walk_objects(root):
        fieldspec = type(obj)._fieldspec
        for key in obj.fields:
            if key not in fieldspec:
                continue
            try:
                converter = resolve_annotation(fieldspec[key])
                value = getattr(obj, key)
            except (ValueError, KeyError, TypeError, IndexError):
                continue  # a bad value is the conversion pass's own diagnostic
            for asset_cls, name in _iter_asset_values(value, converter):
                yield obj, key, asset_cls, name


def _iter_asset_values(value: object, converter: object) -> Iterator[tuple[type[_AssetFile], str]]:
    """`(asset_class, raw_name)` for every asset-file slot reachable through `value` given its
    resolved `converter`. Mirrors the reference walker (`xref._collect_keys`): a bare
    `_AssetFile`, a `List[...]` of one (via its `element`), a `Tuple[...]` (via `element_types`),
    and a `KeyedRecord`'s typed keys are all descended."""
    if isinstance(converter, type) and issubclass(converter, _AssetFile):
        if isinstance(value, str):
            yield converter, value
    elif (element := getattr(converter, "element", None)) is not None:
        for item in value if isinstance(value, list) else [value]:
            yield from _iter_asset_values(item, resolve_annotation(element))
    elif (element_types := getattr(converter, "element_types", None)) is not None:
        if isinstance(value, (list, tuple)):
            for slot, annotation in zip(value, element_types, strict=False):
                yield from _iter_asset_values(slot, resolve_annotation(annotation))
    elif isinstance(converter, type) and issubclass(converter, KeyedRecord):
        for record in value if isinstance(value, list) else [value]:
            if record is None:
                continue
            for key, annotation in converter._keyspec.items():
                yield from _iter_asset_values(
                    getattr(record, key, None), resolve_annotation(annotation)
                )
