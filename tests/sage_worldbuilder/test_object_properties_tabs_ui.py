"""The Object Properties panel shows a tab for each kind of thing selected, and only those; each
tab edits only its own kind. Headless via the Qt 'offscreen' platform; marked `full`."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")  # headless; must precede the Qt import

import pytest

pytestmark = pytest.mark.full

pytest.importorskip("PyQt6", reason="the [worldbuilder] extra (PyQt6) is not installed")

from PyQt6.QtWidgets import QApplication  # noqa: E402

from sage_map.assets.object_list import Object, ObjectsList  # noqa: E402
from sage_map.assets.trigger_areas import TriggerArea, TriggerAreas  # noqa: E402
from sage_map.context import AssetPropertyType  # noqa: E402
from sage_map.map import Map  # noqa: E402
from sage_worldbuilder import MapDocument  # noqa: E402
from sage_worldbuilder.ui.object_properties import ObjectPropertiesPanel  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    yield QApplication.instance() or QApplication([])


class Host:
    def __init__(self, document):
        self.document = document
        self.game = None

    def execute(self, command):
        self.document.execute(command)


def text(key, value):
    return {"name": key, "type": AssetPropertyType.AsciiString, "value": value}


@pytest.fixture
def scene(qapp):
    tree = Object(
        3, (10.0, 20.0, 0.0), 0.0, 0, "Tree", {"uniqueID": text("uniqueID", "Tree 0")}, 0, 0
    )
    waypoint = Object(
        3,
        (50.0, 60.0, 0.0),
        0.0,
        0,
        "*Waypoints/Waypoint",
        {
            "objectLayer": text("objectLayer", ""),
            "uniqueID": text("uniqueID", "Start"),
            "waypointName": text("waypointName", "Start"),
        },
        0,
        0,
    )
    area = TriggerArea("Village", "", 3, [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0)], 0)
    map = Map()
    map.objects_list = ObjectsList(version=3, object_list=[tree, waypoint], start_pos=0, end_pos=0)
    map.trigger_areas = TriggerAreas(version=1, trigger_areas=[area], start_pos=0, end_pos=0)
    document = MapDocument(map)
    panel = ObjectPropertiesPanel(Host(document))
    return panel, document, tree, waypoint, area


def select(panel, document, *items):
    document.selection.set(items)
    panel.refresh()


def test_nothing_selected_shows_no_tabs_or_placement(scene):
    panel, document, *_ = scene
    select(panel, document)
    assert panel.visible_tabs() == []
    assert panel.heading.text() == "Nothing selected."
    assert panel.placement.isHidden()


def test_an_area_shows_only_the_area_tab(scene):
    panel, document, _tree, _waypoint, area = scene
    select(panel, document, area)
    assert panel.visible_tabs() == [panel.area_tab]
    assert panel.tabs.currentWidget() is panel.area_tab
    assert panel.placement.isHidden()
    assert panel.heading.text() == "Trigger area Village"
    assert panel.area_details.text() == "Id 3, 3 corners"


def test_a_waypoint_shows_waypoint_and_other_keys(scene):
    panel, document, _tree, waypoint, _area = scene
    select(panel, document, waypoint)
    assert panel.visible_tabs() == [panel.waypoint_tab, panel.other_keys]
    assert panel.tabs.currentWidget() is panel.waypoint_tab
    assert not panel.placement.isHidden()
    assert not panel.angle.isEnabled()
    assert panel.heading.text() == "Waypoint Start"
    keys = [
        panel.other_keys.topLevelItem(i).text(0)
        for i in range(panel.other_keys.topLevelItemCount())
    ]
    assert keys == ["objectLayer"]


def test_a_mixed_selection_shows_each_kind_and_edits_stay_in_their_kind(scene):
    panel, document, tree, waypoint, area = scene
    select(panel, document, tree, waypoint, area)
    assert panel.visible_tabs() == [
        panel.object_tab,
        panel.waypoint_tab,
        panel.area_tab,
        panel.other_keys,
    ]
    assert panel.heading.text() == "Tree (Tree 0); 1 object, 1 waypoint, 1 trigger area selected"

    panel.object_form.fields["objectEnabled"].setChecked(False)
    assert tree.properties["objectEnabled"]["value"] is False
    assert "objectEnabled" not in waypoint.properties

    panel.x_field.setValue(15.0)
    assert tree.position[0] == 15.0 and waypoint.position[0] == 55.0

    panel.tabs.setCurrentWidget(panel.area_tab)
    select(panel, document, area)
    assert panel.tabs.currentWidget() is panel.area_tab
    select(panel, document, tree)
    assert panel.tabs.currentWidget() is panel.object_tab
