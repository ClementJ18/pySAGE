"""The script action and condition templates: what "New action" and "New condition" offer.

`script_templates.json` is extracted from WorldBuilder by `tools/extract_script_templates.py`.
Each template gives the id and internal name a map stores, the menu path, the sentence
fragments shown around the parameters, and each parameter's type. The table is kept as
WorldBuilder builds it: a slot its own source declared but never filled is `None`.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from functools import cache
from importlib.resources import files

from sage_map.assets.player_scripts import ScriptArgumentType

__all__ = [
    "ParameterType",
    "ScriptTemplate",
    "TemplateKind",
    "parameter_values",
    "script_templates",
    "template",
    "template_named",
]

# A parameter type `sage_map` names, or the bare number for one it does not (the Living World
# reference types WorldBuilder itself cannot display), or `None` for a slot never filled.
ParameterType = ScriptArgumentType | int | None


class TemplateKind(StrEnum):
    ACTION = "action"
    CONDITION = "condition"


@dataclass(frozen=True)
class ScriptTemplate:
    kind: TemplateKind
    id: int
    internal_name: str
    ui_name: str
    flags: int
    ui_strings: tuple[str | None, ...]
    parameters: tuple[ParameterType, ...]

    @property
    def path(self) -> tuple[str, ...]:
        """The menu path, folder by folder, ending with the template's own label."""
        return tuple(part.strip() for part in self.ui_name.split("/"))

    def sentence(self, arguments: Sequence[str]) -> str:
        """The template read as a sentence: each fragment followed by the matching argument's
        text, as WorldBuilder lists a script's conditions and actions."""
        pieces: list[str] = []
        for index, fragment in enumerate(self.ui_strings):
            pieces.append(fragment or "")
            if index < len(self.parameters) and index < len(arguments):
                pieces.append(arguments[index])
        return "".join(pieces)


def _parameter_type(value: int | None) -> ParameterType:
    if value is None:
        return None
    try:
        return ScriptArgumentType(value)
    except ValueError:
        return value


@cache
def _catalogue() -> dict:
    text = files("sage_worldbuilder").joinpath("script_templates.json").read_text(encoding="utf-8")
    return json.loads(text)


@cache
def parameter_values(parameter_type: int) -> tuple[str, ...] | None:
    """The names of an enum parameter's values, in value order, as WorldBuilder prints them
    (Comparison: `Less Than`, ...), or `None` for a type whose value is not a small enum."""
    names = _catalogue()["parameter_values"].get(str(int(parameter_type)))
    return tuple(names) if names is not None else None


@cache
def script_templates() -> tuple[ScriptTemplate, ...]:
    return tuple(
        ScriptTemplate(
            kind=TemplateKind(row["kind"]),
            id=row["id"],
            internal_name=row["internal_name"],
            ui_name=row["ui_name"],
            flags=row["flags"],
            ui_strings=tuple(row["ui_strings"]),
            parameters=tuple(_parameter_type(value) for value in row["parameters"]),
        )
        for row in _catalogue()["templates"]
    )


@cache
def _by_id() -> dict[tuple[TemplateKind, int], ScriptTemplate]:
    return {(entry.kind, entry.id): entry for entry in script_templates()}


@cache
def _by_name() -> dict[tuple[TemplateKind, str], ScriptTemplate]:
    # Actions 552 and 553 share `MAP_REVEAL_IN_TRIGGER` (553's sentence says "shrouded"); the
    # lowest id keeps the name, and it is the one maps store.
    by_name: dict[tuple[TemplateKind, str], ScriptTemplate] = {}
    for entry in script_templates():
        by_name.setdefault((entry.kind, entry.internal_name), entry)
    return by_name


def template(kind: TemplateKind, content_type: int) -> ScriptTemplate | None:
    """The template a map's `content_type` selects."""
    return _by_id().get((kind, content_type))


def template_named(kind: TemplateKind, internal_name: str) -> ScriptTemplate | None:
    return _by_name().get((kind, internal_name))
