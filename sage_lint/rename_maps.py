"""Find, but never rewrite, the uses of a definition inside binary `.map` layouts.

A rename edits ini text; a WorldBuilder layout is a binary asset that belongs to the map author,
so this module only reports. Every hit it returns is a reference the rename is about to break -
the same one `sage-lint lint-maps` will report as `map-dangling-object` /
`map-dangling-reference` afterwards - which is why the report names the exact placed object or
script-argument address, so the map can be fixed in WorldBuilder.

The three places a map names a game definition are the ones `sage_map.linter` resolves: a placed
object's template, a reference-bearing object property, and a GAME-scope script argument.

This module imports `sage_map` at the top, so the caller imports *this module* lazily to keep a
run that never touches maps from paying for the binary map reader.
"""

import struct
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

from sage_map import MapModel, Scope
from sage_map.properties import OBJECT_PROPERTY_SPECS

__all__ = ["MapUsage", "map_hits", "scan_maps"]

# What a map file raises when it is truncated, not a map, or otherwise unreadable. The binary
# reader surfaces short reads as `struct.error`, and the asset layer as the value/key/index errors
# of a field that is not where the format says it should be.
_UNREADABLE = (OSError, ValueError, KeyError, IndexError, struct.error)


@dataclass(frozen=True, slots=True)
class MapUsage:
    """One place a `.map` names the symbol being renamed. `where` locates it the way the map's
    own linter does - a script argument by its logical address, a placed object or property by
    kind - and `count` folds the repeats of an identical hit."""

    path: str
    where: str
    count: int = 1

    def __str__(self) -> str:
        times = "" if self.count == 1 else f" ({self.count}x)"
        return f"{self.path}: {self.where}{times}"


def map_hits(model: MapModel, table: str, old: str) -> Iterator[str]:
    """Every `where` string for which `model` names `old` in `table` - one per reference, so a
    caller can count the repeats of an identical hit."""
    wanted = old.strip().lower()

    objects_list = model.raw.objects_list
    if objects_list is not None:
        for obj in objects_list.object_list:
            if table == "objects":
                name = obj.type_name
                if isinstance(name, str) and name.strip().lower() == wanted:
                    yield "placed object"
            for key, spec in OBJECT_PROPERTY_SPECS.items():
                if spec.scope is not Scope.GAME or spec.target != table:
                    continue
                prop = obj.properties.get(key)
                value = prop["value"] if prop is not None else None
                if not isinstance(value, str):
                    continue
                # A `multi` property is a space-separated list, so each name is judged on its own.
                names = value.split() if spec.multi else [value]
                if any(name.strip().lower() == wanted for name in names):
                    yield f"object property {key!r}"

    for ref in model.references():
        arg_spec = ref.resolved.spec
        if arg_spec.scope is not Scope.GAME or arg_spec.target != table:
            continue
        argument = ref.resolved.value
        if isinstance(argument, str) and argument.strip().lower() == wanted:
            yield f"script argument {ref.address}"


def scan_maps(paths: Iterable[Path], table: str, old: str) -> tuple[list[MapUsage], list[str]]:
    """`(usages, unreadable)` for every `.map` in `paths` that names `table`/`old`.

    A map that will not parse is reported by path rather than raised on: the caller is renaming
    ini data, and one unreadable layout is a thing to mention, not a reason to abandon the run.
    """
    usages: list[MapUsage] = []
    unreadable: list[str] = []
    for path in paths:
        try:
            model = MapModel.from_path(str(path))
        except _UNREADABLE as exc:
            unreadable.append(f"{path}: {exc}")
            continue
        counts: dict[str, int] = {}
        for where in map_hits(model, table, old):
            counts[where] = counts.get(where, 0) + 1
        usages.extend(MapUsage(str(path), where, count) for where, count in sorted(counts.items()))
    return usages, unreadable
