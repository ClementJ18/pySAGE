"""A generated description of the JSON shapes the CLI emits (`explore --json`, `diff
--json`), for an agent or tool builder consuming them. Rendered live from the dataclasses
by introspection - the same fields `ToDictMixin.to_dict` walks - so it cannot drift from
the payload. A field serialized through a custom converter documents its shape via a
`"schema"` note in its `field` metadata.
"""

from __future__ import annotations

import types
import typing
from dataclasses import fields, is_dataclass
from enum import StrEnum

import sage_mods.edain.diff as diff_module
import sage_utils.factiongraph.model as model_module
from sage_mods.edain.diff import ModDiff
from sage_utils.factiongraph.model import FactionGraph, ToDictMixin

__all__ = ["render_schema"]


def _enum_label(tp: type[StrEnum]) -> str:
    return " | ".join(f'"{member.value}"' for member in tp)


def _label(tp, pending: list[type]) -> str:
    """A compact JSON-ish label for one annotation, queueing referenced dataclasses so the
    walk documents them too."""
    origin = typing.get_origin(tp)
    args = typing.get_args(tp)
    if origin in (typing.Union, types.UnionType):
        return " | ".join(_label(arg, pending) for arg in args)
    if tp is type(None):
        return "null"
    if origin is list:
        return f"[{_label(args[0], pending)}]"
    if origin is dict:
        return f"{{{_label(args[0], pending)}: {_label(args[1], pending)}}}"
    if origin is tuple:
        return "[" + ", ".join(_label(arg, pending) for arg in args) + "]"
    if isinstance(tp, type) and issubclass(tp, StrEnum):
        return _enum_label(tp)
    if isinstance(tp, type) and is_dataclass(tp):
        pending.append(tp)
        return tp.__name__
    return {str: "str", float: "number", int: "int", bool: "bool"}.get(tp, str(tp))


def _class_lines(cls: type, module, pending: list[type]) -> list[str]:
    """One dataclass's fields as `name: shape` lines, resolving the module's postponed
    annotations."""
    hints = typing.get_type_hints(cls, vars(module))
    lines = [f"{cls.__name__}:"]
    for spec in fields(cls):
        note = spec.metadata.get("schema")
        shape = note if note is not None else _label(hints[spec.name], pending)
        lines.append(f"  {spec.name}: {shape}")
    return lines


def _walk(root: type, module) -> list[str]:
    """The root dataclass and every dataclass it references, each documented once, in
    first-reference order."""
    lines: list[str] = []
    seen: set[type] = set()
    pending: list[type] = [root]
    while pending:
        cls = pending.pop(0)
        if cls in seen or not issubclass(cls, ToDictMixin):
            continue
        seen.add(cls)
        queue: list[type] = []
        lines += _class_lines(cls, module, queue)
        lines.append("")
        pending.extend(queue)
    return lines


def render_schema(which: str = "graph") -> str:
    """The JSON shape of `explore --json` (`which="graph"`) or `diff --json`
    (`which="diff"`), one dataclass per block. Every key is always present; a missing
    value is `null`, an empty collection `[]`/`{}`; enums list their tokens."""
    if which == "diff":
        header = [
            "# sage-edain diff --json payload (plus top-level `old`/`new` folder labels).",
            "# Generated from sage_mods.edain.diff; every key is always present.",
            "",
        ]
        return "\n".join(header + _walk(ModDiff, diff_module)).rstrip("\n") + "\n"
    header = [
        '# sage-edain explore --json payload: one FactionGraph, or {"factions":',
        "# [FactionGraph, ...]} when no faction was named.",
        "# Generated from sage_utils.factiongraph.model; every key is always present.",
        "",
    ]
    return "\n".join(header + _walk(FactionGraph, model_module)).rstrip("\n") + "\n"
