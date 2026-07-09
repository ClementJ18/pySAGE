"""Rules scoped to map.ini files (anything under a `maps/` directory).

A map is a per-map overlay on the global game: it may *edit* an existing object's modules, but
only through the `AddModule` / `ReplaceModule` / `RemoveModule` keywords. A module declared
bare - a plain `Behavior =`, `Draw =`, `Body =` directly on the object - is rejected in a map
context, so the change the mapper intended silently does nothing. This flags those.
"""

from collections.abc import Iterator
from pathlib import Path

from sage_ini.model.game import Game
from sage_ini.model.ini_objects import Object
from sage_ini.parser.diagnostics import Diagnostic, Severity
from sage_ini.walk import walk_objects
from sage_lint.rules.base import Rule


def _is_map_file(path: str) -> bool:
    """Whether `path` is map-scoped - under a `maps/` directory (mirrors
    `sage_ini.stats.is_map_path`, but from the file alone)."""
    return any(part.lower() == "maps" for part in Path(path).parts[:-1])


class MapBareModuleRule(Rule):
    """A module declared bare on an object defined in a map.ini. A map may only touch an
    object's modules through `AddModule`/`ReplaceModule`/`RemoveModule`; a directly-declared
    `Behavior`/`Draw`/`Body` is not applied, so the map's intended edit is lost."""

    code = "map-bare-module"

    def check(self, game: Game) -> Iterator[Diagnostic]:
        for obj in walk_objects(game, Object):
            if not _is_map_file(obj.span.file):
                continue
            # Bare modules are the ones declared directly on the object: behaviors/bodies in
            # `modules`, draws in the Draw group. AddModule/ReplaceModule wrap their modules
            # in their own groups, so they are not counted here.
            for module in [*obj._modules, *obj._nested_data.get("Draw", [])]:
                tag = f" {module.tag}" if module.tag else ""
                yield Diagnostic(
                    code=self.code,
                    message=(
                        f"{obj.name!r} declares a bare {type(module).__name__}{tag} module in a "
                        f"map.ini; a map may only edit modules with AddModule, ReplaceModule or "
                        f"RemoveModule."
                    ),
                    span=module.span,
                    severity=Severity.ERROR,
                    extra={"object": obj.name, "module": type(module).__name__, "tag": module.tag},
                )
