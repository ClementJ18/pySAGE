"""Which W3D model the game shows for a placed object, and the art files behind it.

An object shows the model WorldBuilder shows, from its `Draw` modules, a draw with a
`WORLD_BUILDER` condition state first: the first `Model` of that state, else of the draw's
`DefaultModelConditionState` (the first `ModelConditionState` naming one when it has no default),
or `ModelName` on tree, prop and floor draws. The state's `Skeleton` is the hierarchy a skinned
model is posed on, before the one its HLOD names. A draw whose model is `None` shows nothing (farm
templates and plot flags use it), and the next draw is tried. A tree draw's `TextureName`
replaces its model's textures. No other condition states, animations or levels of detail are
shown.

Models are `.w3d` files under `art\\w3d\\` and textures under `art\\compiledtextures\\`, each in a
folder named after its first two letters. `ArtIndex` finds both by file name whatever the folder,
and is the `AssetResolver` `sage_w3d.render.scene.build_scene` finds skeletons and textures with.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import PureWindowsPath
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from sage_ini.model.game import Game
    from sage_utils.vfs import VfsEntry
    from sage_w3d.w3d import W3DFile

__all__ = ["ArtIndex", "ObjectModel", "ObjectModels", "object_model"]

_MODEL_FOLDER = "art\\w3d"
_TEXTURE_FOLDER = "art\\compiledtextures"
_STATE_GROUPS = (
    "DefaultModelConditionState",
    "DefaultConditionState",
    "ModelConditionState",
    "ConditionState",
)
_NO_MODEL = "none"
_WORLD_BUILDER = "WORLD_BUILDER"


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


def _world_builder_state(draw: object) -> object | None:
    """The draw's condition state with `WORLD_BUILDER` among its flags, if it has one."""
    for state in _states(draw):
        if _WORLD_BUILDER in str(getattr(state, "name", "") or "").upper().split():
            return state
    return None


def _shown_state(draw: object, world_builder: bool) -> object | None:
    """The condition state shown: the `WORLD_BUILDER` state when `world_builder` and the draw
    has one, else the default, else the first state that names a model."""
    chosen = _world_builder_state(draw) if world_builder else None
    if chosen is not None:
        return chosen
    defaults = _states(draw, ("DefaultModelConditionState", "DefaultConditionState"))
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


def object_model(template: object, world_builder: bool = True) -> ObjectModel | None:
    """The model an object template shows, or None when it shows none. With `world_builder`,
    as WorldBuilder shows it: a draw with a `WORLD_BUILDER` state is tried first, and shows that
    state; without, every draw shows its default state. A `ChildObject` shows the draws it
    inherits, with its module edits applied (`_draws`)."""
    draws = _draws(template)
    if world_builder:
        draws.sort(key=lambda draw: _world_builder_state(draw) is None)
    for draw in draws:
        state = _shown_state(draw, world_builder)
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
    """Models by object name, read from the game data on first use and kept; with
    `world_builder`, the models WorldBuilder shows (`object_model`)."""

    def __init__(self, game: Game, world_builder: bool = True) -> None:
        self.game = game
        self.world_builder = world_builder
        self._cache: dict[str, ObjectModel | None] = {}
        self._names: dict[str, str] | None = None

    def get(self, type_name: str) -> ObjectModel | None:
        if type_name not in self._cache:
            objects = self.game.objects
            template = objects.get(type_name)
            if template is None:
                if self._names is None:
                    self._names = {name.lower(): name for name in objects}
                name = self._names.get(type_name.lower())
                template = objects.get(name) if name is not None else None
            self._cache[type_name] = (
                object_model(template, self.world_builder) if template is not None else None
            )
        return self._cache[type_name]


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
            from sage_w3d.w3d import parse_w3d  # noqa: PLC0415 - lazy: parsing is on demand

            path = self.model_path(name)
            self._models[key] = parse_w3d(self.filesystem.read_bytes(path)) if path else None
        return self._models[key]

    def find_hierarchy(self, name: str) -> W3DFile | None:
        return self.find_model(name)

    def find_texture(self, name: str) -> bytes | None:
        path = self._paths(_TEXTURE_FOLDER).get(_stem(name))
        return self.filesystem.read_bytes(path) if path else None
