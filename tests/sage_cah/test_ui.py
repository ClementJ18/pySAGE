"""Qt-level tests for the sage_cah editor: a hero opens into the widgets, saves back
byte-identical when nothing was touched, and an edit lands in the file with a refreshed
checksum - plus what loading game data changes (class names, power completion, bling hints).
Headless via the Qt 'offscreen' platform, so no display is needed; marked `full` (peripheral
package, like the other sage_utils/sage_ui suites)."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")  # headless; must precede the Qt import

import pytest

pytestmark = pytest.mark.full

pytest.importorskip("PyQt6", reason="the [cah-ui] extra (PyQt6) is not installed")

from PyQt6.QtWidgets import QApplication, QMenu  # noqa: E402

from sage_cah.cah import (  # noqa: E402
    CahBling,
    CahPower,
    CustomHero,
    compute_checksum,
    parse_cah_from_path,
    write_cah_to_path,
)
from sage_cah.gamedata import (  # noqa: E402
    BlingGroup,
    BlingOption,
    CahGameData,
    HeroClass,
    HeroSubClass,
    PowerOption,
)
from sage_cah.ui.window import CahWindow  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    yield QApplication.instance() or QApplication([])


@pytest.fixture
def window(qapp):
    return CahWindow()


def _hero() -> CustomHero:
    """A hero shaped like a real one: 10 bought powers, 5 empty slots, 3 bling entries."""
    powers = [
        CahPower(command_button=f"Command_CreateAHero_Power{i}", exp_level=i, button_index=1)
        for i in range(10)
    ]
    powers += [CahPower(command_button="", exp_level=-1, button_index=0) for _ in range(5)]
    return CustomHero(
        header_unk1=1,
        header_unk2=0,
        version=8,
        obj_id=19,
        name="Test Hero",
        class_index=0,
        sub_class_index=1,
        reserved1=0,
        reserved2=0,
        color1=0xFF112233,
        color2=0xFF445566,
        color3=0xFF778899,
        powers=powers,
        blings=[
            CahBling(group_name="CreateAHero_Helmet", bling_index=1),
            CahBling(group_name="CreateAHero_ArmorAttribute", bling_index=9),
            CahBling(group_name="CreateAHero_Weapon", bling_index=0),
        ],
        guid="ABCDEF0123456789",
        is_system_hero=0,
        checksum=0,
    )


@pytest.fixture
def hero_file(tmp_path):
    path = tmp_path / "myhero_abcdef.cah"
    write_cah_to_path(_hero(), path, refresh_checksum=True)
    return path


def _game_data() -> CahGameData:
    """Stand-in for a scan of a real tree - two classes, two powers, two bling groups."""
    return CahGameData(
        classes=(
            HeroClass(
                name="Captain",
                upgrade="Upgrade_Class_Captain",
                sub_classes=(
                    HeroSubClass(
                        name="Captain of Gondor",
                        upgrade="Upgrade_SubClass_0",
                        bling_upgrades=("Upgrade_NoHelmet", "Upgrade_CaptainHelm"),
                    ),
                    HeroSubClass(
                        name="Rider of Rohan",
                        upgrade="Upgrade_SubClass_1",
                        bling_upgrades=("Upgrade_CaptainHelm", "Upgrade_NoHelmet"),
                    ),
                ),
            ),
            HeroClass(name="Troll", upgrade="Upgrade_Class_Troll", sub_classes=()),
        ),
        powers=(
            PowerOption(
                command_button="Command_CreateAHero_Power0",
                label="Slash",
                class_upgrades=("Upgrade_Class_Captain",),
                min_level=1,
                prerequisite=None,
            ),
            PowerOption(
                command_button="Command_CreateAHero_Roar",
                label="Roar",
                class_upgrades=("Upgrade_Class_Troll",),
                min_level=3,
                prerequisite=None,
            ),
        ),
        bling_groups=(
            BlingGroup(
                group_name="CreateAHero_Helmet",
                label="Helmet",
                kind="APPEARANCE",
                ui_slot=1,
                options=(
                    BlingOption(upgrade="Upgrade_NoHelmet", label="Bare head"),
                    BlingOption(upgrade="Upgrade_CaptainHelm", label="Captain's helm"),
                ),
            ),
            BlingGroup(
                group_name="CreateAHero_ArmorAttribute",
                label="Armour",
                kind="ATTRIBUTE",
                ui_slot=0,
                options=tuple(
                    BlingOption(upgrade=f"Upgrade_Armor{i:02}", label="") for i in range(1, 21)
                ),
            ),
        ),
    )


def test_window_starts_with_nothing_open(window):
    assert not window.save_button.isEnabled()
    assert window._power_rows == []
    assert "Open a .cah" in window.status.text()


def test_window_has_a_help_menu_with_getting_started(window):
    help_menu = next(m for m in window.menuBar().findChildren(QMenu) if m.title() == "&Help")
    labels = [action.text() for action in help_menu.actions() if action.text()]
    assert "&Getting started…" in labels
    assert "&About SAGE Custom Hero" in labels


def test_opening_a_hero_fills_every_card(window, hero_file):
    window.load_path(hero_file)

    assert window.name_edit.text() == "Test Hero"
    assert window.objid_spin.value() == 19
    assert window.guid_edit.text() == "ABCDEF0123456789"
    assert window.class_combo.currentData() == 0
    assert window.sub_combo.currentData() == 1
    assert window._colors == [0xFF112233, 0xFF445566, 0xFF778899]
    assert len(window._power_rows) == 15
    assert len(window._bling_rows) == 3
    assert window._power_rows[0].button.text() == "Command_CreateAHero_Power0"
    assert window._power_rows[0].level.value() == 1
    assert window._power_rows[14].button.text() == ""
    assert window._power_rows[14].level.value() == 0  # an unused slot stores exp_level -1
    assert window.save_button.isEnabled()
    assert "checksum" in window.status.text()


def test_an_attribute_bling_shows_the_value_and_an_appearance_one_the_index(window, hero_file):
    window.load_path(hero_file)
    helmet, armour, _weapon = window._bling_rows

    assert helmet.value.value() == 1 and helmet.value.prefix() == ""
    assert armour.value.value() == 10 and armour.value.prefix() == "value "
    assert window._stored_index(armour) == 9


def test_saving_an_untouched_hero_reproduces_the_file(window, hero_file, tmp_path):
    """The editor must be lossless on the fields it does not show (the header ints, version,
    the reserved words) - open then save is a byte-for-byte round trip."""
    window.load_path(hero_file)
    out = tmp_path / "out.cah"

    window._write_to(out)

    assert out.read_bytes() == hero_file.read_bytes()
    assert not window._dirty


def test_an_edit_is_written_back_with_a_refreshed_checksum(window, hero_file, tmp_path):
    window.load_path(hero_file)
    window.name_edit.setText("Renamed Hero")
    window._power_rows[0].button.setText("Command_CreateAHero_Other")
    window._bling_rows[1].value.setValue(17)
    assert window._dirty
    out = tmp_path / "edited.cah"

    window._write_to(out)

    saved = parse_cah_from_path(out)
    assert saved.name == "Renamed Hero"
    assert saved.powers[0].command_button == "Command_CreateAHero_Other"
    assert saved.bling("CreateAHero_ArmorAttribute").bling_index == 16  # value 17
    assert saved.checksum == compute_checksum(saved)
    assert not window._dirty


def test_an_unknown_class_index_survives_a_save(window, tmp_path):
    """A class the editor cannot name is still a class the file holds; it must come back out
    unchanged rather than snapping to a known one."""
    hero = _hero()
    hero.class_index = 42
    path = tmp_path / "odd.cah"
    write_cah_to_path(hero, path, refresh_checksum=True)
    window.load_path(path)

    assert window.class_combo.currentData() == 42
    window._write_to(tmp_path / "odd-out.cah")

    assert parse_cah_from_path(tmp_path / "odd-out.cah").class_index == 42


def test_loaded_game_data_names_the_classes_powers_and_bling(window, hero_file):
    window.load_path(hero_file)

    window._on_data_loaded(_game_data())

    assert window.class_combo.itemText(0).startswith("Captain")
    assert window.sub_combo.itemText(1).startswith("Rider of Rohan")
    # Only the selected class's powers are offered, and the typed one is named.
    assert window._power_model.stringList() == ["Command_CreateAHero_Power0"]
    assert window._power_rows[0].hint.text() == "Slash - from level 1"
    assert window._power_rows[1].hint.text() == "not in the loaded data"
    assert window._power_rows[14].hint.text() == ""
    # Helmet index 1 is *this* sub-class's second helmet - the Rider of Rohan lists them the
    # other way round from the Captain of Gondor - and an attribute names its group instead.
    assert window._bling_rows[0].hint.text() == "Bare head"
    assert window._bling_rows[1].hint.text() == "Armour"
    assert window._bling_rows[2].hint.text() == ""  # no such group in the loaded data
    assert not window._dirty


def test_choosing_another_class_refilters_the_powers_and_bling(window, hero_file):
    window.load_path(hero_file)
    window._on_data_loaded(_game_data())

    window.class_combo.setCurrentIndex(window.class_combo.findData(1))

    # The Troll class declares no sub-class, so the index the file holds is all that is left
    # to show - and with no sub-class there is no helmet list for its index to count into.
    assert window.sub_combo.itemText(0) == "index 0"
    assert window._power_model.stringList() == ["Command_CreateAHero_Roar"]
    assert window._bling_rows[0].hint.text() == ""
    assert window._dirty


def test_a_group_renamed_to_an_attribute_keeps_the_stored_index(window, hero_file):
    """Editing a bling row's group flips how its spin box reads - value or bare index - and
    must carry the stored index across rather than shifting it by one."""
    window.load_path(hero_file)
    helmet = window._bling_rows[0]

    helmet.group.setText("CreateAHero_VisionAttribute")

    assert helmet.attribute
    assert helmet.value.prefix() == "value "
    assert window._stored_index(helmet) == 1
    assert helmet.value.value() == 2


def test_a_bad_colour_word_leaves_the_colour_alone(window, hero_file):
    window.load_path(hero_file)

    window.color_edits[0].setText("not hex")
    window._color_typed(0)

    assert window._colors[0] == 0xFF112233
    assert window.color_edits[0].text() == "FF112233"


def test_opening_a_file_that_is_not_a_hero_reports_it(window, tmp_path):
    junk = tmp_path / "junk.cah"
    junk.write_bytes(b"not a hero at all")

    window.load_path(junk)

    assert window.hero is None
    assert "Could not open" in window.status.text()
