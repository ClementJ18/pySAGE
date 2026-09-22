"""The Available Upgrades list: which upgrades an object offers, and how the ticked ones are
stored. The panel part needs Qt, headless via the 'offscreen' platform; marked `full`."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")  # headless; must precede the Qt import

import pytest

from sage_ini.loader import load_game
from sage_map.assets.object_list import Object, ObjectsList
from sage_map.context import AssetPropertyType
from sage_map.map import Map
from sage_worldbuilder import MapDocument
from sage_worldbuilder.upgrades import (
    UPGRADES_KEY,
    available_upgrades,
    format_upgrades,
    parse_upgrades,
    set_upgrades,
    stored_upgrades,
    upgrade_choices,
)

_GAME = """
Upgrade Upgrade_GondorHeavyArmor
    Type = PLAYER
End

Upgrade Upgrade_GondorForgedBlades
    Type = PLAYER
End

Upgrade Upgrade_Banner
    Type = OBJECT
End

Object GondorSoldier
    Behavior = ArmorUpgrade ModuleTag_Armor
        TriggeredBy = Upgrade_GondorHeavyArmor
    End
    Behavior = WeaponSetUpgrade ModuleTag_Blades
        TriggeredBy = Upgrade_GondorForgedBlades
    End
    Behavior = SubObjectsUpgrade ModuleTag_Ghost
        TriggeredBy = Upgrade_NoSuchThing
    End
End

Object GondorArcher
    Behavior = ArmorUpgrade ModuleTag_Armor
        TriggeredBy = Upgrade_GondorHeavyArmor
    End
End

Object GondorWall
End
"""


@pytest.fixture(scope="module")
def game(tmp_path_factory):
    root = tmp_path_factory.mktemp("upgrades")
    ini = root / "data" / "ini" / "object" / "gondor.ini"
    ini.parent.mkdir(parents=True)
    ini.write_text(_GAME, encoding="utf-8")
    return load_game(root).game


def placed(type_name, **stored):
    properties = {
        key: {"name": key, "type": AssetPropertyType.AsciiString, "value": value}
        for key, value in stored.items()
    }
    return Object(3, (0.0, 0.0, 0.0), 0.0, 0, type_name, properties, 0, 0)


def test_the_key_is_read_and_written_the_way_the_maps_store_it():
    assert parse_upgrades("Upgrade_A Upgrade_B ") == ["Upgrade_A", "Upgrade_B"]
    assert parse_upgrades(None) == []
    # Sorted ignoring case, each name followed by a space, one row per name.
    assert format_upgrades(["Upgrade_b", "Upgrade_A", "Upgrade_B"]) == "Upgrade_A Upgrade_b "
    assert format_upgrades([]) == ""


def test_only_the_upgrades_the_template_is_triggered_by_are_offered(game):
    assert available_upgrades(game, ["GondorSoldier"]) == [
        "Upgrade_GondorForgedBlades",
        "Upgrade_GondorHeavyArmor",
    ]
    # Several objects offer the union of theirs, and an object with no upgrade module none.
    assert available_upgrades(game, ["GondorSoldier", "GondorArcher"]) == [
        "Upgrade_GondorForgedBlades",
        "Upgrade_GondorHeavyArmor",
    ]
    assert available_upgrades(game, ["GondorWall"]) == []
    assert available_upgrades(game, ["NotAnObject"]) == []
    assert available_upgrades(None, ["GondorSoldier"]) == []


def test_a_name_no_upgrade_block_defines_is_dropped(game):
    """WorldBuilder resolves each name through TheUpgradeCenter and leaves out what it cannot
    find, so a `TriggeredBy` naming nothing never becomes a row."""
    assert "Upgrade_NoSuchThing" not in available_upgrades(game, ["GondorSoldier"])


def test_what_the_object_already_stores_is_listed_even_when_it_is_not_offered(game):
    """Ticking one upgrade must not silently drop another the map already stores."""
    soldier = placed("GondorSoldier", objectUpgradesList="Upgrade_Banner Upgrade_GondorHeavyArmor ")
    assert upgrade_choices(game, [soldier]) == [
        "Upgrade_Banner",
        "Upgrade_GondorForgedBlades",
        "Upgrade_GondorHeavyArmor",
    ]
    assert stored_upgrades(soldier.properties) == ["Upgrade_Banner", "Upgrade_GondorHeavyArmor"]


def test_ticking_writes_the_key_on_every_selected_object_as_one_undo_entry():
    soldier, archer = placed("GondorSoldier"), placed("GondorArcher")
    map = Map()
    map.objects_list = ObjectsList(version=3, object_list=[soldier, archer], start_pos=0, end_pos=0)
    document = MapDocument(map)

    document.execute(set_upgrades([soldier, archer], ["Upgrade_B", "Upgrade_A"]))

    assert soldier.properties[UPGRADES_KEY]["value"] == "Upgrade_A Upgrade_B "
    assert archer.properties[UPGRADES_KEY]["value"] == "Upgrade_A Upgrade_B "
    assert soldier.properties[UPGRADES_KEY]["type"] == AssetPropertyType.AsciiString
    document.stack.undo()
    assert UPGRADES_KEY not in soldier.properties and UPGRADES_KEY not in archer.properties


@pytest.fixture(scope="module")
def qapp():
    pytest.importorskip("PyQt6", reason="the [worldbuilder] extra (PyQt6) is not installed")
    from PyQt6.QtWidgets import QApplication  # noqa: PLC0415

    yield QApplication.instance() or QApplication([])


class Host:
    def __init__(self, document, game):
        self.document = document
        self.game = game

    def execute(self, command):
        self.document.execute(command)


@pytest.mark.full
def test_the_panel_ticks_what_is_stored_and_writes_what_is_ticked(qapp, game):
    from PyQt6.QtCore import Qt  # noqa: PLC0415

    from sage_worldbuilder.ui.object_properties import ObjectPropertiesPanel  # noqa: PLC0415

    soldier = placed("GondorSoldier", objectUpgradesList="Upgrade_GondorHeavyArmor ")
    archer = placed("GondorArcher")
    map = Map()
    map.objects_list = ObjectsList(version=3, object_list=[soldier, archer], start_pos=0, end_pos=0)
    document = MapDocument(map)
    panel = ObjectPropertiesPanel(Host(document, game))
    # No form carries the key: the check list on the Logical page edits it.
    assert panel.object_field("objectUpgradesList") is None

    document.selection.set([soldier, archer])
    panel.refresh()
    rows = panel.upgrades.list
    assert [rows.item(i).text() for i in range(rows.count())] == [
        "Upgrade_GondorForgedBlades",
        "Upgrade_GondorHeavyArmor",
    ]
    assert panel.upgrades.checked() == ["Upgrade_GondorHeavyArmor"]

    rows.item(0).setCheckState(Qt.CheckState.Checked)
    value = "Upgrade_GondorForgedBlades Upgrade_GondorHeavyArmor "
    assert soldier.properties[UPGRADES_KEY]["value"] == value
    assert archer.properties[UPGRADES_KEY]["value"] == value

    document.stack.undo()
    panel.refresh()
    assert panel.upgrades.checked() == ["Upgrade_GondorHeavyArmor"]


@pytest.mark.full
def test_without_game_data_the_list_says_so_rather_than_looking_empty(qapp):
    from sage_worldbuilder.ui.object_properties import ObjectPropertiesPanel  # noqa: PLC0415

    soldier = placed("GondorSoldier")
    map = Map()
    map.objects_list = ObjectsList(version=3, object_list=[soldier], start_pos=0, end_pos=0)
    document = MapDocument(map)
    panel = ObjectPropertiesPanel(Host(document, None))
    document.selection.set([soldier])
    panel.refresh()

    assert panel.upgrades.list.count() == 0
    assert "game data" in panel.upgrades.note.text()


@pytest.mark.full
def test_the_list_is_never_squeezed_below_five_rows(qapp, game):
    """The Object tab scrolls, so a list that asked for nothing would be given one row."""
    from sage_worldbuilder.ui.object_properties import ObjectPropertiesPanel  # noqa: PLC0415
    from sage_worldbuilder.ui.upgrade_list import VISIBLE_ROWS  # noqa: PLC0415

    soldier = placed("GondorSoldier")
    map = Map()
    map.objects_list = ObjectsList(version=3, object_list=[soldier], start_pos=0, end_pos=0)
    document = MapDocument(map)
    panel = ObjectPropertiesPanel(Host(document, game))
    # A narrow, short dock: the form above the list is taller than the tab, so everything in it
    # is squeezed to its minimum.
    panel.resize(320, 500)
    panel.show()
    document.selection.set([soldier])
    panel.refresh()
    qapp.processEvents()

    rows = panel.upgrades.list
    row_height = rows.sizeHintForRow(0)
    assert row_height > 0
    assert rows.minimumSizeHint().height() >= row_height * VISIBLE_ROWS
    assert rows.height() // row_height >= VISIBLE_ROWS
