"""Qt-level tests for ambient sounds: the player keeps the loudest sounds heard from the view
playing, loops and stops them, reads their files once, and plays one object's sound for the Listen
button; the window's Listen To Map modes, Remove MinVolume Customization and the object sheet's
Listen button. Voices are fakes, so nothing is heard. Headless via the Qt 'offscreen' platform;
marked `full`."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")  # headless; must precede the Qt import

import pytest

pytestmark = pytest.mark.full

pytest.importorskip("PyQt6", reason="the [worldbuilder] extra (PyQt6) is not installed")
pytest.importorskip("numpy", reason="the [worldbuilder] extra (numpy) is not installed")

from PyQt6.QtWidgets import QApplication  # noqa: E402

from sage_worldbuilder import MapDocument  # noqa: E402
from sage_worldbuilder.ambient import MIN_VOLUME_KEY, ListenMode  # noqa: E402
from sage_worldbuilder.new_map import NewMapOptions, new_map  # noqa: E402
from sage_worldbuilder.settings import Settings  # noqa: E402
from sage_worldbuilder.ui.ambient_player import AmbientPlayer  # noqa: E402
from sage_worldbuilder.ui.window import MainWindow  # noqa: E402
from tests.sage_worldbuilder.test_ambient import FakeGame, placed, with_objects  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    yield QApplication.instance() or QApplication([])


class StubHost:
    def __init__(self, objects):
        self.document = type("Document", (), {"map": with_objects(objects)})()
        self.game = FakeGame()
        self.listener = (0.0, 0.0)
        self.files = {
            "data\\audio\\sounds\\loop_a.wav": b"RIFFloopa",
            "data\\audio\\sounds\\loop_b.wav": b"RIFFloopb",
        }
        self.read = []
        self.statuses = []

    def listener_position(self):
        return self.listener

    def read_sound(self, path):
        self.read.append(path)
        return self.files.get(path)

    def show_status(self, text):
        self.statuses.append(text)


class FakeVoice:
    made = []

    def __init__(self, finished):
        self.finished = finished
        self.plays = []
        self.volume = None
        self.stopped = False
        FakeVoice.made.append(self)

    def play(self, path, volume):
        self.plays.append((path, volume))
        self.volume = volume
        self.stopped = False

    def set_volume(self, volume):
        self.volume = volume

    def stop(self):
        self.stopped = True


@pytest.fixture
def player(qapp):
    FakeVoice.made = []
    near, far = placed("Lamp", 0.0, 0.0), placed("Lamp", 250.0, 0.0)
    host = StubHost([near, far, placed("Bell", 5000.0, 0.0)])
    player = AmbientPlayer(host, voice_factory=FakeVoice)
    player.random.seed(1)
    yield player
    player.stop()


def test_the_sounds_heard_from_the_view_play_at_their_gain(player):
    player.set_mode(ListenMode.ALL)
    assert player.timer.isActive()
    levels = sorted(voice.volume for _sound, voice in player.voices.values())
    assert levels == pytest.approx([0.225, 0.9])
    path = next(iter(player.voices.values()))[1].plays[0][0]
    assert path.read_bytes().startswith(b"RIFF")
    player.host.listener = (200.0, 0.0)
    player.update()
    assert sorted(voice.volume for _sound, voice in player.voices.values()) == pytest.approx(
        [0.45, 0.9]
    )
    player.host.listener = (3000.0, 0.0)
    player.update()
    assert player.voices == {} and all(voice.stopped for voice in FakeVoice.made)


def test_a_looping_sound_plays_again_and_files_are_read_once(player):
    player.set_mode(ListenMode.PERMANENT)
    voice = next(voice for sound, voice in player.voices.values() if sound.position == (0.0, 0.0))
    for _ in range(6):
        voice.finished()
    assert len(voice.plays) == 7
    assert len(player.host.read) == len(set(player.host.read)) <= 2


def test_no_sound_mode_stops_everything(player):
    player.set_mode(ListenMode.ALL)
    voices = [voice for _sound, voice in player.voices.values()]
    player.set_mode(ListenMode.NONE)
    assert not player.timer.isActive() and player.voices == {}
    assert all(voice.stopped for voice in voices)


def test_a_missing_file_is_reported_once(player):
    player.host.files.clear()
    player.set_mode(ListenMode.ALL)
    player.update()
    assert all(not voice.plays for voice in FakeVoice.made)
    # Each file the lamps tried is reported once, however often it is tried.
    statuses = player.host.statuses
    assert statuses and len(statuses) == len(set(statuses))


def test_listen_plays_one_object_and_stops_it_again(player):
    lamp = player.host.document.map.objects_list.object_list[0]
    assert player.listen(lamp)
    (voice,) = FakeVoice.made
    assert voice.plays[0][1] == pytest.approx(0.9)
    assert player.listen(lamp)
    assert player.listening is None and voice.stopped
    rock = placed("Rock")
    assert not player.listen(rock)


@pytest.fixture
def window(qapp, tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    install = tmp_path / "install"
    install.mkdir()
    monkeypatch.setattr("sage_worldbuilder.gamedata.user_data_dir", lambda game: tmp_path)
    window = MainWindow(Settings(install=str(install)), load_game_data=False)
    window._set_document(MapDocument(new_map(NewMapOptions(width=24, height=24, border=2))))
    yield window
    window.ambient_player.stop()
    window.document = None
    window.close()


def status(window):
    return window.statusBar().currentMessage()


def test_the_listen_to_map_modes_are_one_choice(window):
    actions = window.listen_actions
    assert actions[ListenMode.NONE].isChecked()
    actions[ListenMode.ALL].trigger()
    assert window.ambient_player.mode is ListenMode.ALL
    assert actions[ListenMode.ALL].isChecked() and not actions[ListenMode.NONE].isChecked()
    actions[ListenMode.NONE].trigger()
    assert window.ambient_player.mode is ListenMode.NONE
    assert not window.ambient_player.timer.isActive()


def test_remove_min_volume_customization_from_the_validation_menu(window):
    objects = window.document.map.objects_list.object_list
    lamp = placed("Lamp", objectSoundAmbientMinVolume=1.5)
    objects.append(lamp)
    window.remove_min_volume_action.trigger()
    assert MIN_VOLUME_KEY not in lamp.properties
    assert "from 1 object." in status(window)
    window.document.stack.undo()
    assert MIN_VOLUME_KEY in lamp.properties
    objects.remove(lamp)
    window.remove_min_volume_action.trigger()
    assert status(window).startswith("No objects have the customized minimum volume")


def test_the_object_sheet_listen_button_plays_the_selected_object(window, monkeypatch):
    lamp = placed("Lamp")
    window.document.map.objects_list.object_list.append(lamp)
    heard = []
    monkeypatch.setattr(window.ambient_player, "listen", lambda obj: heard.append(obj) or False)
    window.document.selection.set([lamp])
    window.object_panel.listen_button.click()
    assert heard == [lamp]
    assert "no ambient sound" in status(window)
