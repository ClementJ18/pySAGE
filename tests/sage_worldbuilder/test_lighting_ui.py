"""Qt-level tests for Global Light Options and Environment Options: the menu commands open them,
each edit is an undoable change of the map's chunks, and the panels follow undo and the time of
day. Headless via the Qt 'offscreen' platform; marked `full`."""

import io
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")  # headless; must precede the Qt import

import pytest

pytestmark = pytest.mark.full

pytest.importorskip("PyQt6", reason="the [worldbuilder] extra (PyQt6) is not installed")
pytest.importorskip("numpy", reason="the [worldbuilder] extra (numpy) is not installed")

from PyQt6.QtWidgets import QApplication  # noqa: E402

from sage_map.assets.global_lighting import TimeOfTheDay  # noqa: E402
from sage_map.map import parse_map, write_map  # noqa: E402
from sage_worldbuilder import MapDocument, map_defaults  # noqa: E402
from sage_worldbuilder.cameras import CameraView  # noqa: E402
from sage_worldbuilder.lighting import (  # noqa: E402
    LightSlot,
    LightTarget,
    current_configuration,
    direction_to_angles,
    light,
    set_lighting,
)
from sage_worldbuilder.new_map import NewMapOptions, new_map  # noqa: E402
from sage_worldbuilder.settings import Settings  # noqa: E402
from sage_worldbuilder.ui.environment_options import (  # noqa: E402
    LOOKUP_TABLE_EFFECT,
    SKYBOX_VERSION,
)
from sage_worldbuilder.ui.window import MainWindow  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    yield QApplication.instance() or QApplication([])


@pytest.fixture
def window(qapp, tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    install = tmp_path / "install"
    install.mkdir()
    monkeypatch.setattr("sage_worldbuilder.gamedata.user_data_dir", lambda game: tmp_path)
    window = MainWindow(Settings(install=str(install)), load_game_data=False)
    window._set_document(MapDocument(new_map(NewMapOptions(width=24, height=24, border=2))))
    yield window
    window.document = None
    window.close()


def lighting(window):
    return window.document.map.global_lighting


def test_the_menu_commands_open_the_panels(window):
    window.global_light_action.trigger()
    assert window.lighting_dock.isVisibleTo(window)
    window.post_effects_action.trigger()
    assert window.environment_dock.isVisibleTo(window)


def test_light_colour_and_direction_edits_undo(window):
    panel = window.lighting_panel
    configuration = current_configuration(lighting(window))
    panel.target_box.setCurrentIndex(list(LightTarget).index(LightTarget.INFANTRY))
    panel.color_buttons[LightSlot.ACCENT2].choose((1.0, 0.5, 0.0))
    assert light(configuration, LightTarget.INFANTRY, LightSlot.ACCENT2).color == (1.0, 0.5, 0.0)
    assert light(configuration, LightTarget.TERRAIN, LightSlot.ACCENT2).color != (1.0, 0.5, 0.0)
    panel.heading_boxes[LightSlot.SUN].setValue(90.0)
    panel.elevation_boxes[LightSlot.SUN].setValue(30.0)
    panel.heading_boxes[LightSlot.SUN].editingFinished.emit()
    heading, elevation = direction_to_angles(
        light(configuration, LightTarget.INFANTRY, LightSlot.SUN).direction
    )
    assert (heading, elevation) == pytest.approx((90.0, 30.0))
    stack = window.document.stack
    stack.undo()
    stack.undo()
    assert light(configuration, LightTarget.INFANTRY, LightSlot.ACCENT2).color == tuple(
        map_defaults.LIGHTS["Morning"]["infantry_accent2"][1]
    )
    # The boxes show the restored light again: leaving one unedited makes no new edit.
    panel.heading_boxes[LightSlot.SUN].editingFinished.emit()
    assert stack.can_redo


def test_unedited_direction_boxes_make_no_edit(window):
    panel = window.lighting_panel
    panel.heading_boxes[LightSlot.ACCENT1].editingFinished.emit()
    assert not window.document.stack.can_undo


def test_effects_and_shadow_edits(window):
    panel = window.lighting_panel
    panel.overbright_box.setChecked(False)
    assert lighting(window).overbright == 1.0
    panel.bloom_box.setChecked(True)
    assert lighting(window).bloom_enabled == 1
    panel.bloom_buttons["bloom_terrain"].choose((0.2, 0.4, 0.6))
    assert lighting(window).bloom_terrain == pytest.approx((0.2, 0.4, 0.6))
    panel.intensity_box.setValue(100)
    panel.intensity_box.editingFinished.emit()
    assert lighting(window).shadow_color.a == 100
    for _ in range(4):
        window.document.stack.undo()
    assert lighting(window).overbright == map_defaults.OVERBRIGHT
    assert panel.overbright_box.isChecked()


def test_the_panel_follows_the_time_of_day(window):
    window.execute(set_lighting(lighting(window), "time_of_the_day", TimeOfTheDay.Night))
    assert "Night" in window.lighting_panel.time_label.text()
    night_sun = map_defaults.LIGHTS["Night"]["terrain_sun"]
    shown = window.lighting_panel.color_buttons[LightSlot.SUN].color
    assert shown == pytest.approx(night_sun[1])


def test_environment_textures_and_post_effect(window):
    panel = window.environment_panel
    panel.macro_edit.setText("TSCracks02.tga")
    panel.macro_edit.editingFinished.emit()
    assert window.document.map.environment_data.macro_texture == "TSCracks02.tga"
    effects = window.document.map.post_effects_chunk.post_effects
    assert effects == [] and not panel.enable_box.isChecked()
    panel.enable_box.setChecked(True)
    assert [effect.name for effect in effects] == [LOOKUP_TABLE_EFFECT]
    panel.blend_box.setValue(0.5)
    panel.blend_box.editingFinished.emit()
    assert effects[0].blend_factor == 0.5
    panel.enable_box.setChecked(False)
    assert effects == []
    stack = window.document.stack
    stack.undo()
    assert effects[0].blend_factor == 0.5
    stack.undo()
    stack.undo()
    assert effects == []


def test_the_skybox_is_added_edited_centred_saved_and_removed(window):
    window.skybox_action.trigger()
    assert window.environment_dock.isVisibleTo(window)
    panel = window.environment_panel
    panel.set_skybox_schemes(["NightSky", "DaySky"])
    assert [panel.skybox_scheme.itemText(index) for index in range(2)] == ["DaySky", "NightSky"]
    assert window.document.map.skybox_settings is None
    assert not panel.skybox_box.isChecked() and not panel.skybox_scale.isEnabled()
    window.current_view = lambda: CameraView((120.0, 80.0, 5.0), 0.0, 60.0, 500.0, 45.0)
    panel.skybox_box.setChecked(True)
    skybox = window.document.map.skybox_settings
    assert (skybox.version, skybox.position, skybox.scale, skybox.rotation) == (
        SKYBOX_VERSION,
        (120.0, 80.0, 5.0),
        1.0,
        0.0,
    )
    assert skybox.texture_scheme == "DaySky" and panel.skybox_scale.isEnabled()
    panel.skybox_scale.setValue(2.5)
    panel.skybox_scale.editingFinished.emit()
    assert skybox.scale == 2.5
    panel.skybox_scheme.setCurrentIndex(1)
    panel.skybox_scheme.activated.emit(1)
    assert skybox.texture_scheme == "NightSky"
    window.current_view = lambda: CameraView((10.0, 20.0, 0.0), 0.0, 60.0, 500.0, 45.0)
    panel.center_skybox_button.click()
    assert skybox.position == (10.0, 20.0, 0.0)
    saved = parse_map(io.BytesIO(write_map(window.document.map, compress=False)))
    reread = saved.skybox_settings
    assert tuple(reread.position) == (10.0, 20.0, 0.0)
    assert (reread.version, reread.scale, reread.texture_scheme) == (
        SKYBOX_VERSION,
        2.5,
        "NightSky",
    )
    panel.skybox_box.setChecked(False)
    assert window.document.map.skybox_settings is None
    window.document.stack.undo()
    assert window.document.map.skybox_settings is skybox and panel.skybox_box.isChecked()
