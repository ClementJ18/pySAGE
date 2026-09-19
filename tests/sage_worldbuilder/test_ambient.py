"""Tests for the map's ambient sounds: which sound an object plays, customized values, the Listen
To Map modes, how loud a sound is heard, and Remove MinVolume Customization."""

from types import SimpleNamespace

import pytest

from sage_map.assets.object_list import Object, ObjectsList
from sage_map.context import AssetPropertyType
from sage_map.map import Map
from sage_worldbuilder import MapDocument
from sage_worldbuilder.ambient import (
    MIN_VOLUME_KEY,
    ListenMode,
    ambient_sound,
    ambient_sounds,
    attached_sound_name,
    audible,
    gain,
    remove_min_volume_customization,
    sound_path,
)

pytest.importorskip("numpy", reason="the [worldbuilder] extra (numpy) is not installed")

from sage_worldbuilder.new_map import NewMapOptions, new_map  # noqa: E402

LOOP = SimpleNamespace(name="LOOP")


def events():
    return {
        "Amb_Loop": SimpleNamespace(
            name="Amb_Loop",
            Sounds=["loop_a", "loop_b"],
            Volume=90.0,
            MinVolume=None,
            MinRange=100.0,
            MaxRange=300.0,
            Control=[LOOP],
            Delay=None,
        ),
        "Amb_Once": SimpleNamespace(
            name="Amb_Once",
            Sounds=["once"],
            Volume=50.0,
            MinVolume=10.0,
            MinRange=0.0,
            MaxRange=1000.0,
            Control=[],
            Delay=(1000, 2000),
        ),
        "Amb_Multi": SimpleNamespace(name="Amb_Multi", Sounds=[], Volume=100.0, Control=[]),
    }


class FakeGame:
    def __init__(self):
        audio = events()
        self.tables = {
            "audioevents": audio,
            "objects": {
                "Lamp": SimpleNamespace(SoundAmbient=audio["Amb_Loop"]),
                "Bell": SimpleNamespace(SoundAmbient="Amb_Once"),
                "Silent": SimpleNamespace(SoundAmbient="NoSound"),
                "Rock": SimpleNamespace(),
            },
        }

    def lookup(self, key, name):
        for stored, value in self.tables[key].items():
            if stored.lower() == str(name).lower():
                return value, stored
        return None, name


_TYPES = {
    bool: AssetPropertyType.Boolean,
    int: AssetPropertyType.Integer,
    float: AssetPropertyType.RealNumber,
    str: AssetPropertyType.AsciiString,
}


def placed(type_name, x=0.0, y=0.0, **properties):
    return Object(
        version=3,
        position=(x, y, 0.0),
        angle=0.0,
        road_type=0,
        type_name=type_name,
        properties={
            key: {"name": key, "type": _TYPES[type(value)], "value": value}
            for key, value in properties.items()
        },
        start_pos=0,
        end_pos=0,
    )


def with_objects(objects):
    map = Map()
    map.objects_list = ObjectsList(version=3, object_list=list(objects), start_pos=0, end_pos=0)
    return map


def test_an_object_plays_its_own_sound_before_its_templates():
    game = FakeGame()
    assert attached_sound_name(placed("Lamp"), game) == "Amb_Loop"
    assert attached_sound_name(placed("Bell"), game) == "Amb_Once"
    assert attached_sound_name(placed("Lamp", objectSoundAmbient="Amb_Once"), game) == "Amb_Once"
    assert attached_sound_name(placed("Lamp", objectSoundAmbient=""), game) == "Amb_Loop"
    assert attached_sound_name(placed("Lamp", objectSoundAmbient="NoSound"), game) is None
    assert attached_sound_name(placed("Silent"), game) is None
    assert attached_sound_name(placed("Rock"), game) is None
    assert attached_sound_name(placed("Rock", objectSoundAmbient="Amb_Once"), None) == "Amb_Once"
    assert ambient_sound(placed("Rock", objectSoundAmbient="Amb_Missing"), game) is None
    assert ambient_sound(placed("Rock", objectSoundAmbient="Amb_Multi"), game) is None


def test_the_events_values_in_percent_become_fractions():
    sound = ambient_sound(placed("Bell"), FakeGame())
    assert sound.files == ("once",)
    assert (sound.volume, sound.min_volume) == pytest.approx((0.5, 0.1))
    assert (sound.min_range, sound.max_range, sound.looping) == (0.0, 1000.0, False)
    assert sound.delay == (1000, 2000) and sound.enabled
    assert ambient_sound(placed("Lamp"), FakeGame()).looping


def test_a_customized_sound_uses_the_objects_values():
    game = FakeGame()
    customized = placed(
        "Lamp",
        objectSoundAmbientCustomized=True,
        objectSoundAmbientVolume=0.25,
        objectSoundAmbientMinVolume=0.1,
        objectSoundAmbientMinRange=50.0,
        objectSoundAmbientMaxRange=150.0,
        objectSoundAmbientLooping=False,
        objectSoundAmbientEnabled=False,
    )
    sound = ambient_sound(customized, game)
    assert (sound.volume, sound.min_volume, sound.min_range, sound.max_range) == (
        0.25,
        0.1,
        50.0,
        150.0,
    )
    assert not sound.looping and not sound.enabled
    # Values stored without the Customize box do not count; Enabled does.
    plain = ambient_sound(
        placed("Lamp", objectSoundAmbientVolume=0.25, objectSoundAmbientEnabled=False), game
    )
    assert plain.volume == pytest.approx(0.9) and not plain.enabled


def test_the_listen_modes_choose_their_sounds():
    game = FakeGame()
    enabled_loop = placed("Lamp")
    disabled_loop = placed("Lamp", objectSoundAmbientEnabled=False)
    enabled_once = placed("Bell")
    map = with_objects([enabled_loop, disabled_loop, enabled_once, placed("Rock")])

    def chosen(mode):
        return [sound.obj for sound in ambient_sounds(map, game, mode)]

    assert chosen(ListenMode.ENABLED) == [enabled_loop, enabled_once]
    assert chosen(ListenMode.PERMANENT) == [enabled_loop, disabled_loop]
    assert chosen(ListenMode.ALL) == [enabled_loop, disabled_loop, enabled_once]
    assert chosen(ListenMode.NONE) == []


def test_a_sound_fades_from_its_minimum_to_its_maximum_range():
    game = FakeGame()
    loop = ambient_sound(placed("Lamp", 0.0, 0.0), game)
    assert gain(loop, (60.0, 80.0)) == pytest.approx(0.9)
    assert gain(loop, (200.0, 0.0)) == pytest.approx(0.45)
    assert gain(loop, (300.0, 0.0)) == 0.0
    once = ambient_sound(placed("Bell", 0.0, 0.0), game)
    assert gain(once, (700.0, 0.0)) == pytest.approx(0.15)
    # Below its minimum volume (0.1) a sound is not heard.
    assert gain(once, (950.0, 0.0)) == 0.0
    silenced = ambient_sound(
        placed("Lamp", objectSoundAmbientCustomized=True, objectSoundAmbientMinVolume=1.15), game
    )
    assert gain(silenced, (0.0, 0.0)) == 0.0


def test_the_loudest_sounds_are_heard_first():
    game = FakeGame()
    sounds = [ambient_sound(placed("Lamp", x, 0.0), game) for x in (250.0, 0.0, 150.0, 900.0)]
    heard = audible(sounds, (0.0, 0.0), limit=2)
    assert [sound.position[0] for sound, _level in heard] == [0.0, 150.0]
    assert len(audible(sounds, (0.0, 0.0))) == 3


def test_remove_min_volume_customization_is_one_undoable_edit():
    map = new_map(NewMapOptions(width=24, height=24, border=2))
    document = MapDocument(map)
    stored = placed("Lamp", objectSoundAmbientMinVolume=1.5, objectSoundAmbientVolume=0.5)
    other = placed("Lamp", objectSoundAmbientVolume=0.5)
    map.objects_list.object_list.extend([stored, other])
    assert remove_min_volume_customization(with_objects([other])) is None
    document.execute(remove_min_volume_customization(map))
    assert MIN_VOLUME_KEY not in stored.properties
    document.stack.undo()
    assert list(stored.properties) == [MIN_VOLUME_KEY, "objectSoundAmbientVolume"]


def test_sound_files_are_in_the_sounds_folder():
    assert sound_path("WAVilla_stonewa") == "data\\audio\\sounds\\WAVilla_stonewa.wav"
