"""The `serve` command: a long-lived daemon for an editor. Build the game once, then re-lint
individual files against that cache on demand — full-folder accuracy at single-file speed —
and serve the symbol index (definitions, macros, strings, block schemas) the editor's
navigation and autocomplete read. Speaks newline-delimited JSON on stdin/stdout.
"""

import argparse
import enum
import json
import os
import re
import sys
import tempfile
from dataclasses import replace

from sage_ini.model.objects import (
    REGISTRY,
    IniObject,
    Module,
    NestedAttribute,
    Nugget,
    resolve_annotation,
)
from sage_ini.model.types import Reference
from sage_ini.parser.diagnostics import Diagnostics
from sage_ini.parser.location import Span
from sage_ini.stats import ini_root
from sage_ini.suggest import set_enabled as set_suggestions_enabled
from sage_lint.commands.common import (
    base_paths,
    base_source,
    config_path,
    diagnostic_dict,
    effective_root,
    load_lint_config,
    resolve_rule_set,
    select_and_summarize,
    split_codes,
)
from sage_lint.linter import build_cache, lint_file_cached
from sage_lint.ruleconfig import set_options


def _tidy_type_token(token: str) -> str:
    """Drop the leading `_` of a private converter alias (`_Int`, `_List`) and a `Block`
    suffix on a model class name (`_FXListBlock` -> `FXList`), so the editor sees the name a
    modder would write rather than the internal Python identifier."""
    token = token.lstrip("_")
    if token.endswith("Block") and len(token) > 5:
        token = token[: -len("Block")]
    return token


def _type_label(annotation: object) -> str:
    """A short, readable name for a field's converter annotation, for the editor's module
    documentation. A typed field is `Annotated[PyType, converter]`; the `PyType` is the
    human-facing type, so prefer it (a `ForwardRef` cross-reference keeps its written form). A
    bare class-name string is already a label; any other converter falls back to its class
    name. Private alias/internal spellings are tidied to the form a modder recognizes."""
    metadata = getattr(annotation, "__metadata__", None)
    args = getattr(annotation, "__args__", None)
    if metadata is not None and args:
        py_type = args[0]
        raw = (
            getattr(py_type, "__forward_arg__", None)
            or getattr(py_type, "__name__", None)
            or str(py_type)
        )
    elif isinstance(annotation, str):
        raw = annotation
    else:
        cls = annotation if isinstance(annotation, type) else type(annotation)
        raw = cls.__name__
    return re.sub(r"[A-Za-z_][A-Za-z0-9_]*", lambda m: _tidy_type_token(m.group()), raw)


def _field_value_info(annotation: object) -> dict[str, object]:
    """Per-field metadata for the editor's value autocomplete: always a `type` label, plus —
    when the field's converter (or its list/flag element, or any tuple slot) is an enum — the
    enum's member names under `enum`, or — when it is a cross-`Reference` — the referenced
    table key under `ref`. Mirrors the converter shapes `references.py::_iter_refs` walks, so a
    `List[Weapon]` advertises the same `ref` a bare `Weapon` field does."""
    info: dict[str, object] = {"type": _type_label(annotation)}
    try:
        converter = resolve_annotation(annotation)
    except (KeyError, TypeError):
        return info
    seen: set[int] = set()
    while converter is not None and id(converter) not in seen:
        seen.add(id(converter))
        if isinstance(converter, type) and issubclass(converter, enum.Enum):
            info["enum"] = list(converter.__members__)
            return info
        if isinstance(converter, Reference):
            info["ref"] = converter.key
            return info
        # A field typed directly as a definition class (e.g. `CommandSet`, `Object`) names a
        # value in that class's table — the same `key` the object registers under — so it is a
        # reference too. Modules and other unstored classes carry `key = None` and are skipped.
        if isinstance(converter, type) and issubclass(converter, IniObject) and converter.key:
            info["ref"] = converter.key
            return info
        # Unwrap the single-value wrappers to the converter that actually types the value: a
        # `List`/`FlagList` element, a `Nullable` inner, or a `Tuple`'s first slot. (A
        # `KeyedRecord`'s many keys have no single value kind, so it is left as its label.)
        element = getattr(converter, "element", None) or getattr(converter, "inner", None)
        if element is None:
            element_types = getattr(converter, "element_types", None)
            element = element_types[0] if element_types else None
        if element is None:
            return info
        try:
            converter = resolve_annotation(element)
        except (KeyError, TypeError):
            return info
    return info


def _block_schemas() -> dict[str, dict[str, dict[str, object]]]:
    """`block class name -> {field: field_info}` for every modelled block — top-level objects
    (Object, Weapon, Armor, CommandSet, CommandButton, Upgrade, Science …) and module slots
    alike — read straight from the typed model's registry (the same `_fieldspec` conversion
    runs against). Each `field_info` carries a `type` label and, when known, the field's `enum`
    members or referenced `ref` table. Drives module documentation and field/value autocomplete
    without a hand-maintained data table."""
    # `_fieldspec` is the whole MRO's annotations, so it also carries the base classes'
    # configuration attributes (`key`, `unique_name`, the `_`-prefixed internals …), which are
    # never real INI fields. Drop everything declared on the infrastructure bases to leave only
    # the keys a block actually reads.
    infrastructure = set()
    for base in (IniObject, Module, NestedAttribute, Nugget):
        infrastructure.update(getattr(base, "__annotations__", {}))

    schemas: dict[str, dict[str, dict[str, object]]] = {}
    for name, cls in REGISTRY.items():
        if not (isinstance(cls, type) and issubclass(cls, IniObject)):
            continue
        fields = {
            field: _field_value_info(spec)
            for field, spec in getattr(cls, "_fieldspec", {}).items()
            if field not in infrastructure and not field.startswith("_")
        }
        if fields:
            schemas[name] = fields
    return schemas


def _module_slot_names() -> list[str]:
    """The registered module classes (behaviors, bodies, draws, updates …) — the value tokens
    valid after a `Behavior =`/`Body =`/… slot, for the editor's module-name autocomplete."""
    return sorted(
        name
        for name, cls in REGISTRY.items()
        if isinstance(cls, type) and issubclass(cls, Module) and cls is not Module
    )


def _keyed_by_label_names() -> list[str]:
    """The block classes opened by their *name* with the label as a key (`ModelConditionState =
    DAMAGED`, `AnimationState = MOVING`), as `classify_subblock` types them. The editor needs
    these to tell such a header from a plain `Field = value`, so it offers the right block's
    fields inside one."""
    return sorted(
        name
        for name, cls in REGISTRY.items()
        if isinstance(cls, type) and getattr(cls, "keyed_by_label", False)
    )


def _game_index(game, include_roots: tuple[str, ...] = ()) -> dict[str, object]:
    """A JSON-serializable symbol index of the assembled game, for the editor's go-to-definition,
    symbol browser and autocomplete: every named definition with its source span, plus the macro
    and string tables. Built from the live typed game, so kinds and locations match the parse.

    `include_roots` are the ordered include-resolution roots the linter uses (the mod's ini root,
    then any merged base-game roots) so the editor can resolve an `#include` the same way — a
    base-game-only include included by a mod file is found, not reported missing."""
    definitions = []
    for table in game.tables.values():
        for obj in table.values():
            span = getattr(obj, "span", None)
            if span is None or not isinstance(obj.name, str):
                continue
            definitions.append(
                {
                    "name": obj.name,
                    "kind": type(obj).__name__,
                    "table": obj.key,
                    "file": span.file,
                    "line": span.line_start,
                }
            )
    macros = {}
    for name, value in game.macros.items():
        span = game.macro_definitions.get(name)
        macros[name] = {
            "value": value,
            "file": span.file if span is not None else None,
            "line": span.line_start if span is not None else None,
        }
    strings = {}
    for name, value in game.strings.items():
        span = game.string_definitions.get(name)
        strings[name] = {
            "value": value,
            "file": span.file if span is not None else None,
            "line": span.line_start if span is not None else None,
        }
    return {
        "type": "index",
        "definitions": definitions,
        "macros": macros,
        "strings": strings,
        "blocks": _block_schemas(),
        "module_slots": _module_slot_names(),
        "keyed_by_label": _keyed_by_label_names(),
        "include_roots": list(include_roots),
    }


def _emit(obj: dict) -> None:
    """Write one newline-delimited JSON message to stdout (the daemon's wire format)."""
    print(json.dumps(obj), flush=True)


def _lint_request(game, path, content, root, rules, include_bases=()):
    """Re-lint a daemon `lint_file` request against the cache. With `content` (the live editor
    buffer), lint that text from a temp file beside the real one — so relative `#include`s
    resolve identically — and relabel the diagnostics back onto the real path; otherwise lint
    the file on disk. `include_bases` are the merged base-game include roots, so an `#include`
    that falls through to the base resolves here just as it does on the whole-folder build."""
    if content is None:
        return lint_file_cached(
            game, path, include_root=root, rules=rules, include_bases=include_bases
        )
    handle, tmp = tempfile.mkstemp(prefix=".sagelint-", suffix=".tmp", dir=os.path.dirname(path))
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as buffer:
            buffer.write(content)
        result = lint_file_cached(
            game, tmp, include_root=root, rules=rules, include_bases=include_bases
        )
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass
    # Diagnostics carry the temp path; rewrite each onto the real file (spans are frozen).
    tmp_key = os.path.normcase(tmp)
    relabelled = Diagnostics()
    for diag in result.items:
        if os.path.normcase(diag.span.file) == tmp_key:
            span = Span(str(path), diag.span.line_start, diag.span.line_end)
            relabelled.items.append(replace(diag, span=span))
        else:
            relabelled.items.append(diag)
    return relabelled


def run_serve(args: argparse.Namespace) -> int:
    """Long-lived daemon for an editor: build the game once, then re-lint individual files
    against that cache on demand — full-folder accuracy at single-file speed. Speaks
    newline-delimited JSON: one `{"type":"folder",...}` message once the build is ready (and
    again after each `rebuild`), one `{"type":"file",...}` per `lint_file` request, and one
    `{"type":"index",...}` (the symbol/macro/string/module tables) per `index` request. Commands
    arrive as JSON lines on stdin: `lint_file` (with `path`, optional `id`), `index`, `rebuild`,
    `shutdown`."""
    config = load_lint_config(args)
    root = effective_root(args, config)
    if root is None or not root.is_dir():
        _emit({"type": "error", "message": f"not a directory: {root}"})
        return 2

    # Opt-in for the daemon's lifetime: every build and re-lint then carries hints, and the
    # reference/unused rules read the project's sentinels/always-referenced from process state.
    set_suggestions_enabled(args.suggest or config.suggest)
    set_options(sentinels=config.sentinels, always_referenced=config.always_referenced)

    base_dir = root
    include_assets = args.assets or config.assets
    selected = split_codes(args.select) or set(config.select)
    ignored = split_codes(args.ignore) or set(config.ignore)
    level_name = args.level or config.level
    excludes = tuple(
        list(args.exclude) if args.exclude else [config_path(base_dir, e) for e in config.exclude]
    )
    bases = tuple(base_source(b) for b in base_paths(args, config, base_dir, include_assets))
    rule_set = resolve_rule_set(selected, include_assets)

    # The merged base game is kept on disk between builds so a single-file re-lint can resolve
    # `#include`s that fall through to the base; each rebuild replaces it, shutdown removes it.
    base_layer = None

    def rebuild() -> object:
        nonlocal base_layer
        _emit({"type": "building", "root": str(root)})
        if base_layer is not None:
            base_layer.cleanup()
            base_layer = None
        game, folder, base_layer = build_cache(root, rules=rule_set, exclude=excludes, bases=bases)
        shown, summary = select_and_summarize(folder.items, selected, ignored, level_name)
        _emit(
            {
                "type": "folder",
                "diagnostics": [diagnostic_dict(d) for d in shown],
                "summary": summary,
            }
        )
        return game

    game = rebuild()
    try:
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                command = json.loads(line)
            except ValueError:
                _emit({"type": "error", "message": "malformed command"})
                continue
            kind = command.get("cmd")
            if kind == "shutdown":
                break
            if kind == "rebuild":
                game = rebuild()
            elif kind == "index":
                include_bases = (base_layer.include_root,) if base_layer is not None else ()
                include_roots = (str(ini_root(root)), *(str(base) for base in include_bases))
                message = _game_index(game, include_roots)
                if "id" in command:
                    message["id"] = command["id"]
                _emit(message)
            elif kind == "lint_file":
                path = command.get("path")
                include_bases = (base_layer.include_root,) if base_layer is not None else ()
                try:
                    diagnostics = _lint_request(
                        game, path, command.get("content"), root, rule_set, include_bases
                    )
                    shown, summary = select_and_summarize(
                        diagnostics.items, selected, ignored, level_name
                    )
                    payload = [diagnostic_dict(d) for d in shown]
                    message = {
                        "type": "file",
                        "path": path,
                        "diagnostics": payload,
                        "summary": summary,
                    }
                except (OSError, ValueError, KeyError, TypeError, IndexError) as exc:
                    message = {"type": "file", "path": path, "error": str(exc)}
                if "id" in command:
                    message["id"] = command["id"]
                _emit(message)
            else:
                _emit({"type": "error", "message": f"unknown command {kind!r}"})
    finally:
        if base_layer is not None:
            base_layer.cleanup()
    return 0
