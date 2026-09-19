"""Ambient sounds placed on the map (PLAN.md 5.9): what View > Listen To Map plays, and Validation >
Remove MinVolume Customization.

An object's ambient sound is its own `objectSoundAmbient` when that names one, else its template's
`SoundAmbient`; `NoSound` and an empty name are none. The sound is an `AudioEvent`: its `Sounds`
files (`data\\audio\\sounds\\<name>.wav`), `Volume` and `MinVolume` in percent, `MinRange`,
`MaxRange`, whether `Control` loops, and the `Delay` between plays. An object that customizes its
sound (`objectSoundAmbientCustomized`) replaces the volume, minimum volume (both fractions of 1, as
the object sheet stores what its percent boxes show over 100: `MapObjectProps::OnListen`,
`0x00566A30`), ranges and looping with its own. `objectSoundAmbientEnabled` is separate from the
customization.

WorldBuilder's modes (strings 33394-33397): play the sounds of objects whose Enabled box is
checked, of objects whose sounds loop forever, of all objects, or none. It hands the sounds to the
game's audio engine and polls it from a timer (`WBAudioManager::UpdateSoundTimerProc`,
`0x00635EC0`); how that engine mixes them is not read. So here a sound is heard at its volume within
its minimum range, fading linearly to nothing at its maximum range, and not at all where that is
below its minimum volume (the ini's meaning of `MinVolume`). That makes a minimum volume above the
volume silence the sound, which the corpus has (1.15 and 1.5 among the 206 stored), and which
Remove MinVolume Customization undoes: it removes `objectSoundAmbientMinVolume` from every object
that stores it, in one edit (`0x006429D0`).
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any

from sage_map.assets.object_list import Object
from sage_worldbuilder.changes import Change, ChangeKind
from sage_worldbuilder.commands.base import Command, CompositeCommand
from sage_worldbuilder.commands.edits import SetProperty

if TYPE_CHECKING:
    from sage_ini.model.game import Game
    from sage_map.map import Map

__all__ = [
    "MIN_VOLUME_KEY",
    "AmbientSound",
    "ListenMode",
    "ambient_sound",
    "ambient_sounds",
    "attached_sound_name",
    "audible",
    "gain",
    "min_volume_customizations",
    "remove_min_volume_customization",
    "sound_path",
]

OBJECTS = Change(ChangeKind.OBJECTS)
NO_SOUND = "nosound"
SOUND_FOLDER = "data\\audio\\sounds"
SOUND_EXTENSION = ".wav"
ATTACHED_KEY = "objectSoundAmbient"
CUSTOMIZED_KEY = "objectSoundAmbientCustomized"
ENABLED_KEY = "objectSoundAmbientEnabled"
LOOPING_KEY = "objectSoundAmbientLooping"
VOLUME_KEY = "objectSoundAmbientVolume"
MIN_VOLUME_KEY = "objectSoundAmbientMinVolume"
MIN_RANGE_KEY = "objectSoundAmbientMinRange"
MAX_RANGE_KEY = "objectSoundAmbientMaxRange"


class ListenMode(Enum):
    ENABLED = "enabled"
    PERMANENT = "permanent"
    ALL = "all"
    NONE = "none"


@dataclass(frozen=True, eq=False)
class AmbientSound:
    """One object's ambient sound as it plays: volumes as fractions of 1, ranges in world units,
    the pause between plays of a sound that does not loop in milliseconds."""

    obj: Object
    event: str
    files: tuple[str, ...]
    volume: float
    min_volume: float
    min_range: float
    max_range: float
    looping: bool
    enabled: bool
    delay: tuple[int, int] = field(default=(0, 0))

    @property
    def position(self) -> tuple[float, float]:
        return (self.obj.position[0], self.obj.position[1])


def _stored(obj: Object, key: str) -> Any:
    stored = obj.properties.get(key)
    return stored["value"] if stored is not None else None


def _name(value: object) -> str:
    return str(getattr(value, "name", value) or "")


def attached_sound_name(obj: Object, game: Game | None) -> str | None:
    """The `AudioEvent` name an object plays, or None."""
    name = _stored(obj, ATTACHED_KEY)
    if not name and game is not None:
        template, _ = game.lookup("objects", obj.type_name)
        name = _name(getattr(template, "SoundAmbient", None)) if template is not None else ""
    name = str(name or "").strip()
    return name if name and name.lower() != NO_SOUND else None


def _number(value: object, default: float) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _loops(event: object) -> bool:
    return any(
        getattr(flag, "name", str(flag)).upper() == "LOOP"
        for flag in getattr(event, "Control", None) or []
    )


def ambient_sound(obj: Object, game: Game | None) -> AmbientSound | None:
    """An object's ambient sound, or None when it has none the game knows with files to play (a
    multisound has none of its own)."""
    name = attached_sound_name(obj, game)
    if name is None or game is None:
        return None
    event, _ = game.lookup("audioevents", name)
    if event is None:
        return None
    files = tuple(str(sound) for sound in getattr(event, "Sounds", None) or [] if str(sound))
    if not files:
        return None
    volume = _number(getattr(event, "Volume", None), 100.0) / 100
    min_volume = _number(getattr(event, "MinVolume", None), 0.0) / 100
    min_range = _number(getattr(event, "MinRange", None), 0.0)
    max_range = _number(getattr(event, "MaxRange", None), 0.0)
    looping = _loops(event)
    if _stored(obj, CUSTOMIZED_KEY):
        volume = _number(_stored(obj, VOLUME_KEY), volume)
        min_volume = _number(_stored(obj, MIN_VOLUME_KEY), min_volume)
        min_range = _number(_stored(obj, MIN_RANGE_KEY), min_range)
        max_range = _number(_stored(obj, MAX_RANGE_KEY), max_range)
        stored_looping = _stored(obj, LOOPING_KEY)
        looping = bool(stored_looping) if stored_looping is not None else looping
    enabled = _stored(obj, ENABLED_KEY)
    delay = getattr(event, "Delay", None) or (0, 0)
    return AmbientSound(
        obj,
        _name(event) or name,
        files,
        volume,
        min_volume,
        min_range,
        max_range,
        looping,
        True if enabled is None else bool(enabled),
        (int(delay[0]), int(delay[1])),
    )


def ambient_sounds(map: Map, game: Game | None, mode: ListenMode) -> list[AmbientSound]:
    """The sounds a Listen To Map mode plays."""
    if mode is ListenMode.NONE or map.objects_list is None:
        return []
    sounds = []
    for obj in map.objects_list.object_list:
        sound = ambient_sound(obj, game)
        if sound is None:
            continue
        if mode is ListenMode.ENABLED and not sound.enabled:
            continue
        if mode is ListenMode.PERMANENT and not sound.looping:
            continue
        sounds.append(sound)
    return sounds


def gain(sound: AmbientSound, listener: tuple[float, float]) -> float:
    """How loud a sound is heard from a spot: 0 when it is not heard."""
    distance = math.hypot(sound.position[0] - listener[0], sound.position[1] - listener[1])
    low, high = sound.min_range, sound.max_range
    if distance <= low:
        level = sound.volume
    elif distance >= high:
        return 0.0
    else:
        level = sound.volume * (1 - (distance - low) / (high - low))
    return level if level > 0 and level >= sound.min_volume else 0.0


def audible(
    sounds: Iterable[AmbientSound], listener: tuple[float, float], limit: int = 8
) -> list[tuple[AmbientSound, float]]:
    """The loudest `limit` sounds heard from a spot, loudest first."""
    heard = [(sound, level) for sound in sounds if (level := gain(sound, listener)) > 0]
    heard.sort(key=lambda pair: -pair[1])
    return heard[:limit]


def sound_path(file: str) -> str:
    return f"{SOUND_FOLDER}\\{file}{SOUND_EXTENSION}"


def min_volume_customizations(map: Map) -> list[Object]:
    objects: Sequence[Object] = map.objects_list.object_list if map.objects_list is not None else []
    return [obj for obj in objects if MIN_VOLUME_KEY in obj.properties]


def remove_min_volume_customization(map: Map) -> Command | None:
    """Remove every object's customized minimum volume, or None when no object stores one."""
    objects = min_volume_customizations(map)
    if not objects:
        return None
    label = "Remove MinVolume Customization"
    return CompositeCommand(
        label,
        [SetProperty(obj.properties, MIN_VOLUME_KEY, None, OBJECTS, label) for obj in objects],
    )
