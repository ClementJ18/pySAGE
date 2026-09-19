"""Playing the map's ambient sounds: View > Listen To Map and the object sheet's Listen button.

A timer (every 250 ms, as WorldBuilder polls its audio manager) keeps the loudest eight sounds of
the chosen mode heard from what the view looks at playing, each at its gain; a sound that loops
starts another of its files as one ends, one that does not waits its event's delay first. Sound
files are read from the game's art file system (the base game's archives hold most ambient sounds)
into a folder of their own the first time they play. Listen plays one object's sound at its own
volume, and stops it when asked again. QtMultimedia is optional: without it nothing plays.
"""

from __future__ import annotations

import random
import shutil
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from PyQt6.QtCore import QObject, QTimer, QUrl

from sage_ini.model.game import Game
from sage_map.assets.object_list import Object
from sage_worldbuilder.ambient import (
    AmbientSound,
    ListenMode,
    ambient_sound,
    ambient_sounds,
    audible,
    sound_path,
)
from sage_worldbuilder.document import MapDocument

__all__ = ["UPDATE_MS", "AmbientHost", "AmbientPlayer", "Voice", "multimedia_available"]

UPDATE_MS = 250
VOICES = 8


def multimedia_available() -> bool:
    try:
        from PyQt6.QtMultimedia import QMediaPlayer  # noqa: F401, PLC0415
    except ImportError:
        return False
    return True


class AmbientHost(Protocol):
    @property
    def document(self) -> MapDocument | None: ...

    @property
    def game(self) -> Game | None: ...

    def listener_position(self) -> tuple[float, float] | None:
        """Where sounds are heard from, or None when nothing is shown."""
        ...

    def read_sound(self, path: str) -> bytes | None:
        """A game file's bytes, or None when the game has no such file."""
        ...

    def show_status(self, text: str) -> None: ...


class Voice(Protocol):
    def play(self, path: Path, volume: float) -> None: ...

    def set_volume(self, volume: float) -> None: ...

    def stop(self) -> None: ...


class _QtVoice:
    def __init__(self, finished: Callable[[], None]) -> None:
        from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer  # noqa: PLC0415

        self.output = QAudioOutput()
        self.player = QMediaPlayer()
        self.player.setAudioOutput(self.output)
        end = QMediaPlayer.MediaStatus.EndOfMedia
        self.player.mediaStatusChanged.connect(lambda status: finished() if status == end else None)

    def play(self, path: Path, volume: float) -> None:
        self.output.setVolume(min(max(volume, 0.0), 1.0))
        self.player.setSource(QUrl.fromLocalFile(str(path)))
        self.player.play()

    def set_volume(self, volume: float) -> None:
        self.output.setVolume(min(max(volume, 0.0), 1.0))

    def stop(self) -> None:
        self.player.stop()


VoiceFactory = Callable[[Callable[[], None]], Voice]


class AmbientPlayer(QObject):
    def __init__(
        self,
        host: AmbientHost,
        voice_factory: VoiceFactory | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.host = host
        self.available = voice_factory is not None or multimedia_available()
        self._voice_factory: VoiceFactory = voice_factory or _QtVoice
        self.random = random.Random()
        self.mode = ListenMode.NONE
        self._sounds: list[AmbientSound] | None = None
        # Playing voices by the id of the object whose sound they play.
        self.voices: dict[int, tuple[AmbientSound, Voice]] = {}
        self.listening: tuple[AmbientSound, Voice] | None = None
        self._cache: Path | None = None
        self._missing: set[str] = set()
        self.timer = QTimer(self)
        self.timer.setInterval(UPDATE_MS)
        self.timer.timeout.connect(self.update)

    def set_mode(self, mode: ListenMode) -> None:
        self.mode = mode
        self._sounds = None
        if mode is ListenMode.NONE or not self.available:
            self.timer.stop()
            self._stop_voices()
            return
        self.timer.start()
        self.update()

    def refresh(self) -> None:
        """The map's objects or the game changed: find the sounds again with the next update."""
        self._sounds = None

    def sounds(self) -> list[AmbientSound]:
        if self._sounds is None:
            document = self.host.document
            self._sounds = (
                ambient_sounds(document.map, self.host.game, self.mode)
                if document is not None
                else []
            )
        return self._sounds

    def update(self) -> None:
        listener = self.host.listener_position()
        heard = audible(self.sounds(), listener, VOICES) if listener is not None else []
        wanted = {id(sound.obj): (sound, level) for sound, level in heard}
        for key in [key for key in self.voices if key not in wanted]:
            self.voices.pop(key)[1].stop()
        for key, (sound, level) in wanted.items():
            playing = self.voices.get(key)
            if playing is not None and playing[0].files == sound.files:
                playing[1].set_volume(level)
                self.voices[key] = (sound, playing[1])
                continue
            if playing is not None:
                playing[1].stop()
            voice = self._voice_factory(lambda key=key: self._finished(key))
            self.voices[key] = (sound, voice)
            self._play(sound, voice, level)

    def _play(self, sound: AmbientSound, voice: Voice, level: float) -> bool:
        path = self._file(self.random.choice(sound.files))
        if path is None:
            return False
        voice.play(path, level)
        return True

    def _level(self, key: int) -> float | None:
        """A playing sound's gain now, or None when it is no longer heard."""
        listener = self.host.listener_position()
        entry = self.voices.get(key)
        if entry is None or listener is None:
            return None
        heard = audible([entry[0]], listener, 1)
        return heard[0][1] if heard else None

    def _finished(self, key: int) -> None:
        entry = self.voices.get(key)
        if entry is None:
            return
        sound, voice = entry
        if sound.looping:
            level = self._level(key)
            if level is not None:
                self._play(sound, voice, level)
            return
        low, high = sound.delay
        wait = self.random.randint(min(low, high), max(low, high)) if high > 0 else 0

        def again() -> None:
            current = self.voices.get(key)
            level = self._level(key)
            if current is not None and current[1] is voice and level is not None:
                self._play(sound, voice, level)

        QTimer.singleShot(wait, again)

    def listen(self, obj: Object) -> bool:
        """Play one object's sound at its volume, or stop it when it is the one playing. False when
        the object has no sound to play."""
        if self.listening is not None:
            sound, voice = self.listening
            self.listening = None
            voice.stop()
            if sound.obj is obj:
                return True
        sound = ambient_sound(obj, self.host.game)
        if sound is None or not self.available:
            return False

        def finished() -> None:
            if self.listening is not None and self.listening[1] is voice and sound.looping:
                self._play(sound, voice, sound.volume)

        voice = self._voice_factory(finished)
        if not self._play(sound, voice, sound.volume):
            return False
        self.listening = (sound, voice)
        return True

    def _file(self, name: str) -> Path | None:
        """A sound file on disk, read from the game the first time."""
        if name.lower() in self._missing:
            return None
        if self._cache is None:
            self._cache = Path(tempfile.mkdtemp(prefix="sage_worldbuilder_sounds_"))
        path = self._cache / f"{name.lower()}.wav"
        if not path.is_file():
            data = self.host.read_sound(sound_path(name))
            if data is None:
                self._missing.add(name.lower())
                self.host.show_status(f"The game has no sound file {sound_path(name)}.")
                return None
            path.write_bytes(data)
        return path

    def _stop_voices(self) -> None:
        for _sound, voice in self.voices.values():
            voice.stop()
        self.voices.clear()

    def stop(self) -> None:
        """Stop everything and forget the files read."""
        self.timer.stop()
        self._stop_voices()
        if self.listening is not None:
            self.listening[1].stop()
            self.listening = None
        if self._cache is not None:
            shutil.rmtree(self._cache, ignore_errors=True)
            self._cache = None
