"""Phase 2: a game-aware view over a parsed `.map`.

Harvests the symbols a map declares for itself - teams, players, waypoints and their paths,
trigger areas, scripts, named units - keyed by the same `target` names the MAP-scope entries in
`ARG_SPECS` use. The Phase 3 rules ask `MapSymbols.resolve(target, name)` to tell a dangling
map-local reference (a script targeting a team the map never defines) from a valid one.

Counters, flags and boundaries are referenced by scripts but never *declared* - the engine creates
them on first use - so they are deliberately untracked: a reference to one cannot be dangling, and
`resolve` returns `None` (skip) for those targets rather than a membership answer.

`iter_script_arguments` walks the script tree and pairs every argument with its `ResolvedArg`
(`sage_map.scripts`) and a logical address - `<ScriptName>/if_true[2]/arg[1]` - that names where in
the binary it lives, since a `.map` has no text line for a Diagnostic to point at.
"""

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

from sage_map.assets.player_scripts import Script, ScriptGroup
from sage_map.map import Map, parse_map_from_path
from sage_map.scripts import ResolvedArg, Scope, typed_value

# Object-property keys the harvest reads (see the probe in docs/sage_map_plan.md history).
_TEAM_NAME = "teamName"
_TEAM_OWNER = "teamOwner"
_PLAYER_NAME = "playerName"
_WAYPOINT_NAME = "waypointName"
_OBJECT_NAME = "objectName"  # a placed unit's script-referenceable name (not its template)
_WAYPOINT_PATH_LABELS = ("waypointPathLabel1", "waypointPathLabel2", "waypointPathLabel3")


def _prop(obj: Any, key: str) -> Any:
    """A map object property value, or None when the property is absent."""
    prop = obj.properties.get(key)
    return prop["value"] if prop is not None else None


@dataclass
class MapSymbols:
    """The names a map defines, grouped by the `ARG_SPECS` MAP-scope target they answer for.

    Membership is case-insensitive (the engine interns names loosely, as `Game.lookup` does for
    ini definitions). A target absent from `_tables` is untracked - `resolve` returns `None` so a
    rule skips it instead of flagging a reference that was never meant to be declared.
    """

    teams: set[str] = field(default_factory=set)
    players: set[str] = field(default_factory=set)
    waypoints: set[str] = field(default_factory=set)
    waypoint_paths: set[str] = field(default_factory=set)
    trigger_areas: set[str] = field(default_factory=set)
    scripts: set[str] = field(default_factory=set)
    units: set[str] = field(default_factory=set)

    def _table(self, target: str) -> set[str] | None:
        # `units` and `scripts` are harvested but intentionally *not* resolvable. Units are also
        # created by scripts at runtime, and a `SCRIPT_NAME`/`SUBROUTINE_NAME` reference often
        # targets a subroutine (a script or a *script group*) imported from a library map that is
        # merged only at runtime - so a name absent from this map's own set is not necessarily
        # dangling. The same reason counters/flags/attack-priority-sets are untracked.
        return {
            "teams": self.teams,
            "players": self.players,
            "waypoints": self.waypoints,
            "waypoint_paths": self.waypoint_paths,
            "trigger_areas": self.trigger_areas,
        }.get(target)

    def resolve(self, target: str, name: str) -> bool | None:
        """Whether `name` is defined for `target`: True/False when tracked, None when not.

        `None` means the target (counters, flags, boundaries) is referenced but never declared, so
        a rule must not treat a miss as dangling."""
        table = self._table(target)
        if table is None:
            return None
        return name.strip().lower() in table

    def names(self, target: str) -> set[str] | None:
        """The set of names tracked for `target`, or None when the target is not resolved at all.
        An empty set means a tracked kind the map happens to declare none of - a caller can skip
        resolving against it rather than flag everything."""
        return self._table(target)


def _all_teams(map_obj: Map) -> Iterator[Any]:
    """Teams live in the standalone `Teams` asset (modern maps) or inside `SidesList` (older
    maps); yield from whichever the map carries."""
    if map_obj.teams is not None:
        yield from map_obj.teams.teams
    if map_obj.sides_list is not None:
        yield from map_obj.sides_list.teams


def build_symbols(map_obj: Map) -> MapSymbols:
    """Collect every map-local symbol a script may reference. Names are folded to lower case for
    case-insensitive resolution; empty names (e.g. the neutral player) are dropped."""
    symbols = MapSymbols()

    # Scripts reference a team by its *qualified* name, `<owner>/<team>` (e.g.
    # `PlyrCivilian/Farmers`); harvest that form plus the bare team name so either resolves.
    for team in _all_teams(map_obj):
        name = _prop(team, _TEAM_NAME)
        if not name:
            continue
        owner = _prop(team, _TEAM_OWNER) or ""
        symbols.teams.add(name.lower())
        symbols.teams.add(f"{owner}/{name}".lower())

    if map_obj.sides_list is not None:
        symbols.players = {
            n.lower() for p in map_obj.sides_list.players if (n := _prop(p, _PLAYER_NAME))
        }

    if map_obj.objects_list is not None:
        for obj in map_obj.objects_list.object_list:
            if (name := _prop(obj, _WAYPOINT_NAME)) is not None:
                symbols.waypoints.add(name.lower())
            if (unit := _prop(obj, _OBJECT_NAME)) is not None:
                symbols.units.add(unit.lower())
            for label_key in _WAYPOINT_PATH_LABELS:
                if (label := _prop(obj, label_key)) is not None:
                    symbols.waypoint_paths.add(label.lower())

    if map_obj.trigger_areas is not None:
        symbols.trigger_areas |= {a.name.lower() for a in map_obj.trigger_areas.trigger_areas}
    if map_obj.polygon_triggers is not None:
        symbols.trigger_areas |= {t.name.lower() for t in map_obj.polygon_triggers.polygon_triggers}

    symbols.scripts = script_names(map_obj)

    return symbols


@dataclass(frozen=True)
class ScriptArgRef:
    """One script argument, located. `address` is the logical path to it within the map
    (`<ScriptName>/if_true[2]/arg[1]`); `resolved` carries its spec and payload."""

    script_name: str
    address: str
    resolved: ResolvedArg


def _iter_scripts(map_obj: Map) -> Iterator["_ScriptRef"]:
    """Flatten the (possibly nested) script tree to its `Script` leaves, dropping group nesting."""
    if map_obj.player_scripts_list is None:
        return
    for script_list in map_obj.player_scripts_list.script_lists:
        yield from _walk_items(script_list.items)


@dataclass(frozen=True)
class _ScriptRef:
    script_name: str
    script: Script


def _walk_items(items: list) -> Iterator[_ScriptRef]:
    for item in items:
        if isinstance(item, ScriptGroup):
            yield from _walk_items(item.items)
        elif isinstance(item, Script):
            yield _ScriptRef(item.name, item)


def script_names(map_obj: Map) -> set[str]:
    """Lower-cased names of the leaf scripts the map defines (informational only - script
    references are not resolved; see `MapSymbols._table`)."""
    return {ref.script_name.lower() for ref in _iter_scripts(map_obj)}


def iter_script_arguments(map_obj: Map) -> Iterator[ScriptArgRef]:
    """Every argument of every action and condition, paired with its `ResolvedArg` and a logical
    address. Walks `or_conditions[i].conditions[j]`, `actions_if_true[k]` and `actions_if_false[k]`
    of each script in declaration order."""
    for ref in _iter_scripts(map_obj):
        name, script = ref.script_name, ref.script
        for i, or_condition in enumerate(script.or_conditions):
            for j, condition in enumerate(or_condition.conditions):
                for a, arg in enumerate(condition.arguments):
                    address = f"{name}/condition[{i}.{j}]/arg[{a}]"
                    yield ScriptArgRef(name, address, typed_value(arg))
        for k, action in enumerate(script.actions_if_true):
            for a, arg in enumerate(action.arguments):
                yield ScriptArgRef(name, f"{name}/if_true[{k}]/arg[{a}]", typed_value(arg))
        for k, action in enumerate(script.actions_if_false):
            for a, arg in enumerate(action.arguments):
                yield ScriptArgRef(name, f"{name}/if_false[{k}]/arg[{a}]", typed_value(arg))


@dataclass
class MapModel:
    """A parsed `.map` plus the symbols it declares - the unit the Phase 3 rules lint."""

    raw: Map
    symbols: MapSymbols

    @classmethod
    def from_map(cls, raw: Map) -> "MapModel":
        return cls(raw=raw, symbols=build_symbols(raw))

    @classmethod
    def from_path(cls, path: str) -> "MapModel":
        return cls.from_map(parse_map_from_path(path))

    def script_arguments(self) -> Iterator[ScriptArgRef]:
        """Every located script argument (see `iter_script_arguments`)."""
        return iter_script_arguments(self.raw)

    def references(self) -> Iterator[ScriptArgRef]:
        """Only the arguments that name something resolvable - GAME, MAP or STRINGS scope - which
        is the subset the Phase 3 reference rules act on."""
        for ref in self.script_arguments():
            if ref.resolved.spec.scope in (Scope.GAME, Scope.MAP, Scope.STRINGS):
                if isinstance(ref.resolved.value, str) and ref.resolved.value.strip():
                    yield ref
