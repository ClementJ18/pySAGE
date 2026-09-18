"""Which W3D model the game shows for a placed object, and the art files behind it.

An object shows the model WorldBuilder shows, from its `Draw` modules, a draw with a
`WORLD_BUILDER` condition state first: the first `Model` of the condition state that best fits the
object's model conditions, else of the draw's `DefaultModelConditionState` (the first
`ModelConditionState` naming one when it has no default), or `ModelName` on tree, prop and floor
draws. The state's `Skeleton` is the hierarchy a skinned model is posed on, before the one its
HLOD names. A draw whose model is `None` shows nothing (farm templates and plot flags use it), and
the next draw is tried. A tree draw's `TextureName` replaces its model's textures. No animations
or levels of detail are shown.

WorldBuilder asks the draw for the model of a set of conditions (`0x0064F530`): `WORLD_BUILDER`;
`DAMAGED`, `REALLYDAMAGED` or `RUBBLE` as the object's starting health is at or under GameData's
`UnitDamagedThreshold`, `UnitReallyDamagedThreshold` or zero; `NIGHT` when the object's time is
2 or the map's time of day is night; `SNOW` when the object's weather is 2 or the map's weather is
snowy; and `GARRISONED` while View > Show Garrisoned is on. The state that fits best shares the
most flags with those conditions and, among those, has the fewest flags they lack; the default
state has none, and the first of equals wins (the engine's sparse match). An object's model is
found and cached by its model key, `name#FLAGS` (`model_key`).

Models are `.w3d` files under `art\\w3d\\` and textures under `art\\compiledtextures\\`, each in a
folder named after its first two letters. `ArtIndex` finds both by file name whatever the folder,
and is the `AssetResolver` `sage_w3d.render.scene.build_scene` finds skeletons and textures with.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass, replace
from pathlib import PureWindowsPath
from typing import TYPE_CHECKING, Protocol

from sage_map.assets.global_lighting import TimeOfTheDay
from sage_w3d.w3d import W3DFile, parse_w3d

if TYPE_CHECKING:
    from sage_ini.model.game import Game
    from sage_map.map import Map
    from sage_utils.vfs import VfsEntry

__all__ = [
    "ArtIndex",
    "MapConditions",
    "ObjectModel",
    "ObjectModels",
    "model_conditions",
    "model_key",
    "object_model",
]

_MODEL_FOLDER = "art\\w3d"
_TEXTURE_FOLDER = "art\\compiledtextures"
_STATE_GROUPS = (
    "DefaultModelConditionState",
    "DefaultConditionState",
    "ModelConditionState",
    "ConditionState",
)
_DEFAULT_GROUPS = _STATE_GROUPS[:2]
_NO_MODEL = "none"
_WORLD_BUILDER = "WORLD_BUILDER"
_KEY_SEPARATOR = "#"
# The object time and weather values that ask for night and snow (`objectTime`, `objectWeather`).
_OBJECT_NIGHT = 2
_OBJECT_SNOW = 2
# The map's weather value for SNOWY (`MapWeatherType`).
_MAP_SNOW = 1
# GameData's defaults, for a game whose data sets none.
_DAMAGED = 0.5
_REALLY_DAMAGED = 0.1


@dataclass(frozen=True)
class MapConditions:
    """What the map and the view ask of every object's model: night and snow from the map's
    time of day and weather, garrisoned from the view, and the health thresholds from the game."""

    night: bool = False
    snow: bool = False
    garrisoned: bool = False
    damaged: float = _DAMAGED
    really_damaged: float = _REALLY_DAMAGED

    @classmethod
    def of_game(cls, game: Game | None) -> MapConditions:
        """No conditions, with the game's damage thresholds."""
        damaged, really_damaged = _DAMAGED, _REALLY_DAMAGED
        blocks = game.tables.get("gamedatas", {}) if game is not None else {}
        for data in blocks.values():
            damaged = _real(getattr(data, "UnitDamagedThreshold", None), damaged)
            really_damaged = _real(
                getattr(data, "UnitReallyDamagedThreshold", None), really_damaged
            )
        return cls(damaged=damaged, really_damaged=really_damaged)

    def of_map(self, map: Map, garrisoned: bool) -> MapConditions:
        """These thresholds with the map's night and snow, and `garrisoned`."""
        lighting = map.global_lighting
        night = lighting is not None and lighting.time_of_the_day is TimeOfTheDay.Night
        info = map.world_info.properties if map.world_info is not None else {}
        snow = _stored(info, "weather", 0) == _MAP_SNOW
        return replace(self, night=night, snow=snow, garrisoned=garrisoned)


def _real(value: object, default: float) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _stored(properties: Mapping[str, Mapping[str, object]], key: str, default: object) -> object:
    stored = properties.get(key)
    return stored["value"] if stored is not None else default


def model_conditions(
    properties: Mapping[str, Mapping[str, object]], conditions: MapConditions
) -> frozenset[str]:
    """The model conditions WorldBuilder shows an object with, but for `WORLD_BUILDER`."""
    flags: set[str] = set()
    health = _real(_stored(properties, "objectInitialHealth", 100), 100.0) / 100
    if health <= 0:
        flags.add("RUBBLE")
    elif health <= conditions.really_damaged:
        flags.add("REALLYDAMAGED")
    elif health <= conditions.damaged:
        flags.add("DAMAGED")
    if conditions.night or _stored(properties, "objectTime", 0) == _OBJECT_NIGHT:
        flags.add("NIGHT")
    if conditions.snow or _stored(properties, "objectWeather", 0) == _OBJECT_SNOW:
        flags.add("SNOW")
    if conditions.garrisoned:
        flags.add("GARRISONED")
    return frozenset(flags)


def model_key(type_name: str, conditions: frozenset[str]) -> str:
    """The name an object's model is found and cached by: its type, and its conditions if any."""
    if not conditions:
        return type_name
    return f"{type_name}{_KEY_SEPARATOR}{' '.join(sorted(conditions))}"


class _FileSystem(Protocol):
    def listdir(self, folder: str) -> Iterator[VfsEntry]: ...

    def read_bytes(self, entry: VfsEntry | str) -> bytes: ...


@dataclass(frozen=True)
class ObjectModel:
    """A model name, the skeleton its condition state binds it to, and the texture that replaces
    its own textures, if any."""

    model: str
    texture: str | None = None
    skeleton: str | None = None


def _first_word(value: object) -> str:
    words = str(value).split() if value else []
    return words[0] if words else ""


def _states(draw: object, groups: tuple[str, ...] = _STATE_GROUPS) -> list[object]:
    return [state for group in groups for state in getattr(draw, group, None) or []]


def _state_model(state: object) -> str:
    models = getattr(state, "Model", None) or []
    return _first_word(models[0]) if models else ""


def _flags(state: object) -> frozenset[str]:
    return frozenset(str(getattr(state, "name", "") or "").upper().split())


def _world_builder_state(draw: object) -> object | None:
    """The draw's condition state with `WORLD_BUILDER` among its flags, if it has one."""
    for state in _states(draw):
        if _WORLD_BUILDER in _flags(state):
            return state
    return None


def _best_state(draw: object, conditions: frozenset[str]) -> object | None:
    """The draw's condition state that best fits `conditions`: the most flags in common, then the
    fewest flags the conditions lack, the first of equals. A default state has no flags."""
    defaults = _states(draw, _DEFAULT_GROUPS)
    best: object | None = None
    best_shared, best_extra = 0, None
    for state in [*defaults, *_states(draw, _STATE_GROUPS[2:])]:
        flags = frozenset() if any(state is default for default in defaults) else _flags(state)
        shared, extra = len(flags & conditions), len(flags - conditions)
        if shared > best_shared or (
            shared == best_shared and (best_extra is None or extra < best_extra)
        ):
            best, best_shared, best_extra = state, shared, extra
    return best


def _shown_state(draw: object, conditions: frozenset[str]) -> object | None:
    """The condition state shown: the one that best fits `conditions` when it names a model,
    else the default, else the first state that names a model."""
    chosen = _best_state(draw, conditions)
    if chosen is not None and _state_model(chosen):
        return chosen
    defaults = _states(draw, _DEFAULT_GROUPS)
    if defaults:
        return defaults[0]
    return next((state for state in _states(draw) if _state_model(state)), None)


def _removed_tags(owner: object) -> set[str]:
    """The module tags `owner` itself removes. Read from its own fields: through a `ChildObject`
    the attribute would come from the parent when the child names none."""
    fields = getattr(owner, "_fields", None)
    raw = fields.get("RemoveModule") if isinstance(fields, dict) else None
    values = raw if isinstance(raw, list) else [raw] if raw is not None else []
    return {word.lower() for value in values for word in str(value).split()}


def _is_draw(module: object) -> bool:
    from sage_ini.model.objects import Draw  # noqa: PLC0415 - the model is loaded with the game

    return isinstance(module, Draw)


def _draws(template: object) -> list[object]:
    """The template's draw modules as the engine assembles them. A `ChildObject` starts from its
    parent's, drops the ones its `RemoveModule` tags name, swaps those its `ReplaceModule` blocks
    name, then adds its `AddModule` draws and its own `Draw` lines."""
    chain: list[object] = []
    current: object | None = template
    while current is not None and all(current is not seen for seen in chain):
        chain.append(current)
        current = getattr(current, "parent", None)
    draws: list[object] = []
    for owner in reversed(chain):
        removed = _removed_tags(owner)
        replacements = {
            _first_word(getattr(wrapper, "name", None)).lower(): getattr(wrapper, "module", None)
            for wrapper in getattr(owner, "ReplaceModule", None) or []
        }
        kept = []
        for draw in draws:
            tag = str(getattr(draw, "tag", None) or "").lower()
            if tag and tag in removed:
                continue
            if tag and tag in replacements:
                replacement = replacements[tag]
                if _is_draw(replacement):
                    kept.append(replacement)
                continue
            kept.append(draw)
        added = [
            wrapper.module
            for wrapper in getattr(owner, "AddModule", None) or []
            if _is_draw(getattr(wrapper, "module", None))
        ]
        draws = kept + added + list(getattr(owner, "Draw", None) or [])
    return draws


def object_model(
    template: object, world_builder: bool = True, conditions: frozenset[str] = frozenset()
) -> ObjectModel | None:
    """The model an object template shows under `conditions`, or None when it shows none. With
    `world_builder`, as WorldBuilder shows it: `WORLD_BUILDER` is among the conditions, and a
    draw with a `WORLD_BUILDER` state is tried first. A `ChildObject` shows the draws it
    inherits, with its module edits applied (`_draws`)."""
    draws = _draws(template)
    if world_builder:
        conditions |= {_WORLD_BUILDER}
        draws.sort(key=lambda draw: _world_builder_state(draw) is None)
    for draw in draws:
        state = _shown_state(draw, conditions)
        name = (
            _state_model(state)
            if state is not None
            else _first_word(getattr(draw, "ModelName", None))
        )
        if not name or name.lower() == _NO_MODEL:
            continue
        texture = _first_word(getattr(draw, "TextureName", None))
        skeleton = _first_word(getattr(state, "Skeleton", None)) if state is not None else ""
        return ObjectModel(name, texture or None, skeleton or None)
    return None


class ObjectModels:
    """Models by model key (`model_key`), read from the game data on first use and kept; with
    `world_builder`, the models WorldBuilder shows (`object_model`)."""

    def __init__(self, game: Game, world_builder: bool = True) -> None:
        self.game = game
        self.world_builder = world_builder
        self._cache: dict[str, ObjectModel | None] = {}
        self._names: dict[str, str] | None = None

    def get(self, key: str) -> ObjectModel | None:
        if key not in self._cache:
            type_name, _, flags = key.partition(_KEY_SEPARATOR)
            objects = self.game.objects
            template = objects.get(type_name)
            if template is None:
                if self._names is None:
                    self._names = {name.lower(): name for name in objects}
                name = self._names.get(type_name.lower())
                template = objects.get(name) if name is not None else None
            self._cache[key] = (
                object_model(template, self.world_builder, frozenset(flags.split()))
                if template is not None
                else None
            )
        return self._cache[key]


def _stem(name: str) -> str:
    return PureWindowsPath(name).stem.lower()


class ArtIndex:
    """Model and texture files by name, listed from `filesystem` on first use; parsed models
    are kept."""

    def __init__(self, filesystem: _FileSystem) -> None:
        self.filesystem = filesystem
        self._folders: dict[str, dict[str, str]] = {}
        self._models: dict[str, W3DFile | None] = {}

    def _paths(self, folder: str) -> dict[str, str]:
        if folder not in self._folders:
            paths: dict[str, str] = {}
            for entry in self.filesystem.listdir(folder):
                paths.setdefault(_stem(entry.path), entry.path)
            self._folders[folder] = paths
        return self._folders[folder]

    def model_path(self, name: str) -> str | None:
        return self._paths(_MODEL_FOLDER).get(_stem(name))

    def find_model(self, name: str) -> W3DFile | None:
        key = _stem(name)
        if key not in self._models:
            path = self.model_path(name)
            self._models[key] = parse_w3d(self.filesystem.read_bytes(path)) if path else None
        return self._models[key]

    def find_hierarchy(self, name: str) -> W3DFile | None:
        return self.find_model(name)

    def find_texture(self, name: str) -> bytes | None:
        path = self._paths(_TEXTURE_FOLDER).get(_stem(name))
        return self.filesystem.read_bytes(path) if path else None
