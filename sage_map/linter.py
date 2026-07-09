"""Phase 3: flag dangling references in a `.map`, resolved against the assembled game.

Every script argument that names something - an object template, a science, a map-local team, a
localization label - is resolved the way the engine would: GAME-scope names against the built
`Game` (via `Game.lookup`, case-insensitive), MAP-scope names against the map's own symbols, and
STRINGS against `Game.strings`. A name that resolves to nothing is reported: the engine silently
no-ops the action, so the script does not do what its author meant.

Two guards keep the check honest, mirroring sage_lint's missing-asset rule:

* engine sentinels (`<All Players>`, `<This Object>`, `NONE`, empty) are left alone; and
* a GAME table (or the strings table) that was never populated - a map linted without building its
  mod - is skipped rather than flagged wholesale, since the miss would be the build's fault.

A `.map` is binary, so a diagnostic's `Span` points at the file with the offending argument's
logical address (`<ScriptName>/if_true[2]/arg[1]`) carried in the message and `extra`.
"""

from collections import Counter
from collections.abc import Iterable
from pathlib import Path

from sage_ini.loader import load_game
from sage_ini.model.game import Game
from sage_ini.parser.diagnostics import Diagnostic, Diagnostics, Severity
from sage_ini.parser.location import Span
from sage_map.model import MapModel, ScriptArgRef
from sage_map.properties import OBJECT_PROPERTY_SPECS
from sage_map.scripts import Scope

# Distinct codes per check, so each is separately `--select`/`--ignore`-able - the object checks
# are the GAME-scope ones that flood without the base archives loaded, so a user can silence them
# alone while keeping the reliable map-local script-argument checks.
CODE = "map-dangling-reference"  # a script argument naming something undefined
OBJECT_CODE = "map-dangling-object"  # a placed object whose type is undefined
PROPERTY_CODE = "map-dangling-property"  # an object property naming something undefined
PARSE_ERROR_CODE = "map-parse-error"

# A GAME/MAP target's noun for the message, by the `ArgSpec.target` it carries.
_NOUNS: dict[str, str] = {
    "objects": "object",
    "sciences": "science",
    "upgrades": "upgrade",
    "commandbuttons": "command button",
    "specialpowers": "special power",
    "attackpriorities": "attack priority set",
    "factions": "faction",
    "teams": "team",
    "players": "player",
    "waypoints": "waypoint",
    "waypoint_paths": "waypoint path",
    "trigger_areas": "trigger area",
    "scripts": "script",
    "units": "named unit",
}


def _is_sentinel(name: str) -> bool:
    """Engine placeholders that name no definition: `<All Players>`, `NONE`, the empty string."""
    stripped = name.strip()
    return not stripped or stripped.lower() == "none" or stripped.startswith("<")


def _diagnostic(ref: ScriptArgRef, map_path: str, noun: str, where: str) -> Diagnostic:
    name = ref.resolved.value
    return Diagnostic(
        code=CODE,
        message=(
            f"Script {ref.script_name!r} references {noun} {name!r} ({ref.address}), which {where}."
        ),
        span=Span(map_path, 1, 1),
        severity=Severity.WARNING,
        extra={
            "name": name,
            "noun": noun,
            "scope": ref.resolved.spec.scope.value,
            "target": ref.resolved.spec.target,
            "script": ref.script_name,
            "address": ref.address,
        },
    )


def _check(
    ref: ScriptArgRef,
    map_path: str,
    game: Game,
    model: MapModel,
    folded_strings: set[str],
) -> Diagnostic | None:
    spec = ref.resolved.spec
    name = ref.resolved.value
    if not isinstance(name, str) or _is_sentinel(name):
        return None

    if spec.scope is Scope.GAME:
        assert spec.target is not None
        if not game.tables.get(spec.target):
            return None  # that table was never built: nothing to resolve against
        obj, _ = game.lookup(spec.target, name)
        if obj is None:
            noun = _NOUNS.get(spec.target, spec.target)
            return _diagnostic(ref, map_path, noun, "is not defined in the game")

    elif spec.scope is Scope.MAP:
        assert spec.target is not None
        resolved = model.symbols.resolve(spec.target, name)
        if resolved is False:
            noun = _NOUNS.get(spec.target, spec.target)
            return _diagnostic(ref, map_path, noun, "the map does not define")

    elif spec.scope is Scope.STRINGS:
        if not folded_strings:
            return None  # no strings loaded: skip rather than flag every label
        if name.lower() not in folded_strings:
            return _diagnostic(ref, map_path, "string label", "is not defined")

    return None


def _check_object_types(model: MapModel, game: Game, map_path: str) -> list[Diagnostic]:
    """Every placed object names an Object template; one the game does not define silently fails to
    spawn. Resolved against the `objects` table the way the engine looks it up (case-insensitive,
    `Game.lookup`). Reported once per distinct missing type with the count of placed instances -
    not once per object - so a single bad template name does not flood the report. Skipped when the
    objects table was not built (the empty-table guard); engine sentinels and the WorldBuilder
    internal categories (`*Waypoints/Waypoint`, `*Lights/...`) are left alone."""
    objects_list = model.raw.objects_list
    if objects_list is None or not game.tables.get("objects"):
        return []
    missing: Counter[str] = Counter()
    for obj in objects_list.object_list:
        name = obj.type_name
        if not name or _is_sentinel(name) or name.startswith("*"):
            continue  # empty, an engine sentinel, or a WorldBuilder internal category
        if game.lookup("objects", name)[0] is None:
            missing[name] += 1
    diagnostics = []
    for name, count in sorted(missing.items()):
        placed = "1 object" if count == 1 else f"{count} objects"
        diagnostics.append(
            Diagnostic(
                code=OBJECT_CODE,
                message=f"Object type {name!r} ({placed}) is not defined in the game.",
                span=Span(map_path, 1, 1),
                severity=Severity.WARNING,
                extra={
                    "name": name,
                    "noun": "object",
                    "scope": "game",
                    "target": "objects",
                    "count": count,
                },
            )
        )
    return diagnostics


def _check_object_properties(model: MapModel, game: Game, map_path: str) -> list[Diagnostic]:
    """Object instance properties that name another entity (`originalOwner` -> the owning team,
    ...; see `OBJECT_PROPERTY_SPECS`). Resolved like the script-argument references - MAP-scope
    against the map's own symbols, GAME-scope against the game - and reported once per distinct
    `(property, value)` with the placed-instance count, so a single bad value does not flood. A
    MAP target the map declares none of (no teams at all) is skipped, the same empty-set guard the
    GAME checks use."""
    objects_list = model.raw.objects_list
    if objects_list is None:
        return []
    missing: Counter[tuple[str, str]] = Counter()  # (property key, referenced name) -> count
    for obj in objects_list.object_list:
        for key, spec in OBJECT_PROPERTY_SPECS.items():
            prop = obj.properties.get(key)
            value = prop["value"] if prop is not None else None
            if not isinstance(value, str) or not value.strip():
                continue
            # A `multi` property is a space-separated list (with a trailing space); resolve each
            # name on its own so a miss is reported per referenced name, not per whole list.
            for name in value.split() if spec.multi else [value]:
                if not name or _is_sentinel(name):
                    continue
                if spec.scope is Scope.MAP:
                    if not model.symbols.names(spec.target):
                        continue  # the map declares none of this kind: nothing to resolve against
                    if model.symbols.resolve(spec.target, name) is False:
                        missing[(key, name)] += 1
                elif spec.scope is Scope.GAME:
                    if game.tables.get(spec.target) and game.lookup(spec.target, name)[0] is None:
                        missing[(key, name)] += 1

    diagnostics = []
    for (key, value), count in sorted(missing.items()):
        spec = OBJECT_PROPERTY_SPECS[key]
        noun = _NOUNS.get(spec.target, spec.target)
        where = (
            "the map does not define" if spec.scope is Scope.MAP else "is not defined in the game"
        )
        placed = "1 object" if count == 1 else f"{count} objects"
        message = f"Object property {key!r} references {noun} {value!r} ({placed}), which {where}."
        diagnostics.append(
            Diagnostic(
                code=PROPERTY_CODE,
                message=message,
                span=Span(map_path, 1, 1),
                severity=Severity.WARNING,
                extra={
                    "name": value,
                    "noun": noun,
                    "scope": spec.scope.value,
                    "target": spec.target,
                    "key": key,
                    "count": count,
                },
            )
        )
    return diagnostics


def lint_map(model: MapModel, game: Game, map_path: str | Path = "<map>") -> Diagnostics:
    """Report every dangling reference in one parsed map, resolved against `game`: script
    arguments (GAME/MAP/STRINGS scope), every placed object's type, and reference-bearing object
    properties (the owning team, ...)."""
    diagnostics = Diagnostics()
    path = str(map_path)
    folded_strings = {label.lower() for label in game.strings}  # fold once per map, not per ref
    for ref in model.references():
        diagnostic = _check(ref, path, game, model, folded_strings)
        if diagnostic is not None:
            diagnostics.items.append(diagnostic)
    diagnostics.items.extend(_check_object_types(model, game, path))
    diagnostics.items.extend(_check_object_properties(model, game, path))
    return diagnostics


def lint_map_file(path: str | Path, game: Game) -> Diagnostics:
    """Parse one `.map` and lint it against an already-built `game`."""
    return lint_map(MapModel.from_path(str(path)), game, path)


def lint_maps(
    root: str | Path,
    game: Game | None = None,
    paths: Iterable[str | Path] | None = None,
) -> Diagnostics:
    """Build the game under `root` (unless one is supplied) and lint every `.map` it found.

    `game.map_files` is populated by the loader's folder crawl, so the maps linted are exactly the
    WorldBuilder layouts shipped under `root` (and its base layers). A map that fails to parse is
    reported as one diagnostic rather than aborting the run."""
    if game is None:
        game = load_game(root).game
    map_paths = list(paths) if paths is not None else list(game.map_files)

    diagnostics = Diagnostics()
    for map_path in map_paths:
        try:
            diagnostics.items.extend(lint_map_file(map_path, game).items)
        except Exception as exc:  # noqa: BLE001 - any failure on one binary map must not abort the batch
            diagnostics.add(
                PARSE_ERROR_CODE,
                f"failed to parse map: {exc}",
                Span(str(map_path), 1, 1),
                Severity.ERROR,
            )
    return diagnostics
