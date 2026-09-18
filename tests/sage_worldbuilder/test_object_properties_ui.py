"""The object property specs, and the Object Properties panel: edits apply to every selected
object as one undo entry. Qt parts headless via the 'offscreen' platform; marked `full`."""

import math
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")  # headless; must precede the Qt import

import pytest

from sage_map.assets.object_list import Object, ObjectsList
from sage_map.context import AssetPropertyType
from sage_map.map import Map
from sage_worldbuilder import MapDocument
from sage_worldbuilder.properties import OBJECT_SPECS, WAYPOINT_SPECS

# The stored type of each key in every corpus map that has it (the census of 509 Edain maps).
CORPUS_TYPES = {
    "objectInitialHealth": 1,
    "objectEnabled": 0,
    "objectIndestructible": 0,
    "objectUnsellable": 0,
    "objectPowered": 0,
    "objectRecruitableAI": 0,
    "objectTargetable": 0,
    "originalOwner": 3,
    "objectLayer": 3,
    "objectBasePriority": 1,
    "objectBasePhase": 1,
    "exportWithScript": 0,
    "objectPrototypeScale": 2,
    "alignToTerrain": 0,
    "waypointName": 3,
    "waypointTypeOption": 3,
    "objectSelectable": 0,
    "waypointPathLabel1": 3,
    "waypointPathLabel2": 3,
    "waypointPathLabel3": 3,
    "objectName": 3,
    "objectUpgradesList": 3,
    "objectExperienceLevel": 1,
    "objectAggressiveness": 1,
    "objectMaxHPs": 1,
    "objectVeterancy": 1,
    "objectBaseName": 3,
    "objectInitialStance": 1,
    "objectSoundAmbientCustomized": 0,
    "objectWeather": 1,
    "objectSoundAmbient": 3,
    "objectSoundAmbientMinRange": 2,
    "objectSoundAmbientMaxRange": 2,
    "objectSoundAmbientVolume": 2,
    "objectSoundAmbientEnabled": 0,
    "objectVisualRange": 1,
    "objectShroudClearingDistance": 1,
    "objectThreatFinderRadius": 2,
    "waypointPathBiDirectional": 0,
    "objectTime": 1,
    "objectSoundAmbientPriority": 1,
    "objectStoppingDistance": 2,
    "waypointType": 1,
    "objectIsABase": 0,
    "objectSoundAmbientMinVolume": 2,
    "objectEventsList": 3,
    "objectSoundAmbientLooping": 0,
}


def test_specs_store_the_types_the_maps_store():
    specs = {spec.name: spec for spec in (*OBJECT_SPECS, *WAYPOINT_SPECS)}
    assert len(specs) == len(OBJECT_SPECS) + len(WAYPOINT_SPECS)
    for name, spec in specs.items():
        assert spec.type == AssetPropertyType(CORPUS_TYPES[name]), name
    aggressiveness = specs["objectAggressiveness"]
    assert aggressiveness.choice_base == -3 and len(aggressiveness.choices) == 6


def placed(type_name, x, y, **properties):
    stored = {
        key: {"name": key, "type": kind, "value": value}
        for key, (kind, value) in properties.items()
    }
    return Object(3, (x, y, 0.0), 0.0, 0, type_name, stored, 0, 0)


@pytest.fixture(scope="module")
def qapp():
    pytest.importorskip("PyQt6", reason="the [worldbuilder] extra (PyQt6) is not installed")
    from PyQt6.QtWidgets import QApplication  # noqa: PLC0415

    yield QApplication.instance() or QApplication([])


class Host:
    def __init__(self, document):
        self.document = document
        self.game = None

    def execute(self, command):
        self.document.execute(command)


@pytest.mark.full
def test_panel_edits_every_selected_object(qapp):
    from PyQt6.QtCore import Qt  # noqa: PLC0415
    from PyQt6.QtWidgets import QCheckBox, QComboBox, QGridLayout  # noqa: PLC0415

    from sage_worldbuilder.ui.object_properties import ObjectPropertiesPanel  # noqa: PLC0415

    boolean, integer = AssetPropertyType.Boolean, AssetPropertyType.Integer
    ascii_string = AssetPropertyType.AsciiString
    tree = placed(
        "Tree",
        10.0,
        20.0,
        objectEnabled=(boolean, True),
        uniqueID=(ascii_string, "Tree 0"),
        scorchType=(integer, 1),
    )
    rock = placed("Rock", 50.0, 60.0, objectEnabled=(boolean, True))
    map = Map()
    map.objects_list = ObjectsList(version=3, object_list=[tree, rock], start_pos=0, end_pos=0)
    document = MapDocument(map)
    panel = ObjectPropertiesPanel(Host(document))
    assert panel.heading.text() == "Nothing selected."

    document.selection.set([tree, rock])
    panel.refresh()
    assert "Tree (Tree 0)" in panel.heading.text()
    assert panel.heading.textInteractionFlags() & Qt.TextInteractionFlag.TextSelectableByMouse
    assert [panel.other_keys.topLevelItem(0).text(i) for i in range(3)] == [
        "scorchType",
        "Integer",
        "1",
    ]
    assert panel.visible_tabs() == [panel.object_tab, panel.other_keys]

    enabled = panel.object_form.fields["objectEnabled"]
    assert isinstance(enabled, QCheckBox) and enabled.isChecked()
    # A run of check boxes shares one row in pairs, each labelled by its own text.
    recruitable = panel.object_form.fields["objectRecruitableAI"]
    assert enabled.text() == "Enabled"
    grid = next(
        layout
        for layout in panel.object_form.findChildren(QGridLayout)
        if layout.indexOf(enabled) >= 0
    )
    assert grid.getItemPosition(grid.indexOf(enabled))[:2] == (0, 0)
    assert grid.getItemPosition(grid.indexOf(recruitable))[:2] == (0, 1)
    enabled.setChecked(False)
    assert tree.properties["objectEnabled"]["value"] is False
    assert rock.properties["objectEnabled"]["value"] is False

    aggressiveness = panel.object_form.fields["objectAggressiveness"]
    assert isinstance(aggressiveness, QComboBox)
    assert aggressiveness.currentText() == "Normal"
    aggressiveness.setCurrentIndex(0)
    assert rock.properties["objectAggressiveness"]["value"] == -3

    panel.x_field.setValue(15.0)
    assert tree.position == (15.0, 20.0, 0.0) and rock.position == (55.0, 60.0, 0.0)
    panel.angle.setValue(90.0)
    assert rock.angle == pytest.approx(math.pi / 2)

    stack = document.stack
    labels = []
    while stack.can_undo:
        labels.append(stack.undo_label)
        stack.undo()
    assert len(labels) == 4
    assert tree.position == (10.0, 20.0, 0.0)
    assert rock.properties["objectEnabled"]["value"] is True
    assert "objectAggressiveness" not in rock.properties


@pytest.mark.full
def test_health_presets_and_waypoint_type_names(qapp):
    from sage_worldbuilder.properties import WAYPOINT_TYPE_NAMES  # noqa: PLC0415
    from sage_worldbuilder.ui.object_properties import ObjectPropertiesPanel  # noqa: PLC0415
    from sage_worldbuilder.ui.property_form import PresetField  # noqa: PLC0415

    integer = AssetPropertyType.Integer
    tree = placed("Tree", 0.0, 0.0, objectInitialHealth=(integer, 40))
    waypoint = placed("*Waypoints/Waypoint", 5.0, 5.0, waypointID=(integer, 1))
    map = Map()
    map.objects_list = ObjectsList(version=3, object_list=[tree, waypoint], start_pos=0, end_pos=0)
    document = MapDocument(map)
    panel = ObjectPropertiesPanel(Host(document))
    document.selection.set([tree, waypoint])
    panel.refresh()

    health = panel.object_form.fields["objectInitialHealth"]
    assert isinstance(health, PresetField)
    assert [health.choice.itemText(i) for i in range(health.choice.count())] == [
        "0%",
        "25%",
        "50%",
        "75%",
        "100%",
        "Other",
    ]
    # 40 is no preset: Other, with the number box on.
    assert health.choice.currentText() == "Other" and health.number.isEnabled()
    assert health.number.value() == 40
    health.choice.setCurrentIndex(2)
    assert tree.properties["objectInitialHealth"]["value"] == 50
    assert not health.number.isEnabled()
    health.choice.setCurrentIndex(5)
    assert tree.properties["objectInitialHealth"]["value"] == 99
    health.number.setValue(12)
    assert tree.properties["objectInitialHealth"]["value"] == 12

    max_hp = panel.object_form.fields["objectMaxHPs"]
    assert max_hp.choice.currentText() == "Default For Unit" and not max_hp.number.isEnabled()

    kind = panel.waypoint_form.fields["waypointType"]
    assert kind.count() == len(WAYPOINT_TYPE_NAMES) and kind.currentText() == "Normal"
    kind.setCurrentIndex(5)
    assert waypoint.properties["waypointType"]["value"] == 5
