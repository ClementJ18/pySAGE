"""Qt-level tests for the sage_ui Browser: the onboarding state and the typo-tolerant
search. Headless via the Qt 'offscreen' platform, so no display is needed; marked `full`
(peripheral package, like the other sage_utils/sage_ui suites)."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")  # headless; must precede the Qt import

import pytest

pytestmark = pytest.mark.full

pytest.importorskip("PyQt6", reason="the [ui] extra (PyQt6) is not installed")

from PyQt6.QtWidgets import QApplication, QLabel, QPushButton  # noqa: E402

import sage_ui.browser as browser_module  # noqa: E402
from sage_ini.model.game import Game  # noqa: E402
from sage_ini.parser.blockparser import parse  # noqa: E402
from sage_ui.browser import Browser  # noqa: E402
from sage_ui.object_browser import faction_tree  # noqa: E402
from sage_utils.factiongraph import (  # noqa: E402
    FactionGraph,
    Power,
    ProducedUnit,
    ResearchableUpgrade,
    Spellbook,
    Structure,
    StructureRole,
)
from sage_utils.views import display_name_index  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    yield QApplication.instance() or QApplication([])


@pytest.fixture
def browser(qapp, tmp_path, monkeypatch):
    # An empty APPDATA (no saved sources) and a tmp cwd (no repo-root `data/` to auto-add)
    # land the window in its fresh-start state.
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    window = Browser()
    window.sources_panel.clear()
    return window


def _panel_widget(window):
    """The single widget currently filling the results area."""
    return window._panels_row.itemAt(0).widget()


def _labels(widget):
    found = widget.findChildren(QLabel)
    if isinstance(widget, QLabel):  # a bare-label panel is its own only label
        found = [widget, *found]
    return [label.text() for label in found]


def _buttons(widget):
    return [button.text() for button in widget.findChildren(QPushButton)]


def _load_units(window):
    """Give the window a one-object game with a localized display name."""
    game = Game()
    game.load_document(
        parse("Object MordorFighter\n  DisplayName = OBJECT:Mordor\nEnd\n", file="t.ini").document
    )
    game.strings.update({"OBJECT:Mordor": "Mordor Orc Warrior"})
    window.game = game
    window._object_names = ["MordorFighter"]
    window._display_names, window._display_index = display_name_index(game, ["MordorFighter"])
    return game


class TestOnboarding:
    def test_guides_to_add_files_when_no_install_detected(self, browser, monkeypatch):
        monkeypatch.setattr(browser_module, "detect_installed_games", lambda: {})
        browser._set_onboarding()
        card = _panel_widget(browser)

        assert any("Welcome" in text for text in _labels(card))
        # No auto-detected game → the manual "add files" buttons are offered.
        assert any("Add data folder" in text for text in _buttons(card))
        assert any("Add .big" in text for text in _buttons(card))

    def test_offers_edain_when_an_install_is_detected(self, browser, monkeypatch):
        monkeypatch.setattr(
            browser_module, "detect_installed_games", lambda: {"RotWK": r"C:\Games\RotWK"}
        )
        browser._set_onboarding()
        card = _panel_widget(browser)

        assert any("Load Edain" in text for text in _buttons(card))
        assert any("RotWK" in text for text in _labels(card))  # names the detected install

    def test_offers_one_click_preset_per_detected_game(self, browser, monkeypatch):
        monkeypatch.setattr(
            browser_module,
            "detect_installed_games",
            lambda: {"BfMe II": r"C:\Games\BFME2", "RotWK": r"C:\Games\RotWK"},
        )
        browser._set_onboarding()
        buttons = _buttons(_panel_widget(browser))

        assert any("Load BfMe II" in text for text in buttons)
        assert any("Load RotWK" in text for text in buttons)

    def test_edain_button_needs_rotwk(self, browser, monkeypatch):
        # Edain lives in the RotWK folder; a BfMe II-only install gets its own preset only.
        monkeypatch.setattr(
            browser_module, "detect_installed_games", lambda: {"BfMe II": r"C:\Games\BFME2"}
        )
        browser._set_onboarding()
        buttons = _buttons(_panel_widget(browser))

        assert any("Load BfMe II" in text for text in buttons)
        assert not any("Edain" in text for text in buttons)


class TestVanillaLoad:
    def _install(self, tmp_path, name: str, lang: bool = True):
        root = tmp_path / name
        (root / "lang").mkdir(parents=True)
        (root / "ini.big").write_bytes(b"")
        (root / "textures0.big").write_bytes(b"")
        if lang:
            (root / "lang" / "english.big").write_bytes(b"")
        return root

    def test_vanilla_archives_probes_what_exists(self, tmp_path):
        root = self._install(tmp_path, "BFME2")
        data, textures = browser_module.vanilla_archives(root)
        assert [p.name for p in data] == ["ini.big", "english.big"]
        assert [p.name for p in textures] == ["textures0.big"]

        empty = tmp_path / "nothing"
        empty.mkdir()
        assert browser_module.vanilla_archives(empty) == ([], [])

    def test_load_rotwk_layers_bfme2_beneath(self, browser, monkeypatch, tmp_path):
        bfme2 = self._install(tmp_path, "BFME2")
        rotwk = self._install(tmp_path, "RotWK", lang=False)
        monkeypatch.setattr(
            browser_module,
            "detect_installed_games",
            lambda: {"BfMe II": str(bfme2), "RotWK": str(rotwk)},
        )
        # Queue only; don't parse. Both loads run through the shared SourceLoader controllers, so
        # the stubs go on those - which still lets `loader.set_sources` populate the panel this
        # test inspects.
        monkeypatch.setattr(browser.loader, "load", lambda: None)
        monkeypatch.setattr(browser.texture_loader, "load", lambda sources: None)

        browser._load_vanilla("RotWK")
        queued = [path for _kind, path in browser.sources_panel.sources()]
        assert queued == [
            str(bfme2 / "ini.big"),
            str(bfme2 / "lang" / "english.big"),
            str(rotwk / "ini.big"),
        ]

    def test_ready_message_once_a_source_is_queued(self, browser):
        browser.sources_panel.add_source("folder", r"C:\data")
        browser._show_initial_state()
        # A queued source replaces onboarding with a one-line "press Load" prompt.
        assert any("Load" in text for text in _labels(_panel_widget(browser)))


def _toy_graph() -> FactionGraph:
    graph = FactionGraph(name="FactionTest", display="Testers", side="Test")
    graph.spellbook = Spellbook(
        name="SB",
        powers=[
            Power(name="P1", display="Heal", cooldown=120.0, creates=[("EagleSummon", "Eagle")])
        ],
    )
    graph.units["Soldier"] = ProducedUnit(name="Soldier", display="Test Soldier")
    graph.upgrades["Upg"] = ResearchableUpgrade(
        name="Upg", display="Forged Blades", cost=300.0, affects=[("Soldier", "Test Soldier")]
    )
    graph.structures["Barracks"] = Structure(
        name="Barracks",
        display="Test Barracks",
        role=StructureRole.FOUNDATION_BUILDING,
        trains_units=["Soldier"],
        researches_upgrades=["Upg"],
    )
    return graph


class TestFactionTree:
    def test_shapes_the_drill_down(self):
        (node,) = faction_tree([_toy_graph()])

        assert node["label"] == "Testers  [Test]"
        groups = {child["label"]: child for child in node["children"]}
        assert set(groups) == {"Spellbook  (1)", "Structures  (1)", "Units  (1)"}

        (power,) = groups["Spellbook  (1)"]["children"]
        assert power["label"] == "Heal  (120s)"
        assert power["children"][0]["object"] == "EagleSummon"  # summons are loadable leaves

        (barracks,) = groups["Structures  (1)"]["children"]
        assert barracks["object"] == "Barracks"
        assert "[foundation building]" in barracks["label"]
        labels = [child["label"] for child in barracks["children"]]
        assert "Test Soldier  (Soldier)" in labels
        assert "research: Forged Blades - 300" in labels
        research = next(c for c in barracks["children"] if c["label"].startswith("research"))
        assert research["object"] is None  # upgrades are info lines, not loadable objects
        assert "Affects: Test Soldier" in research["tooltip"]

    def test_duplicate_display_names_group_under_one_node(self):
        graph = _toy_graph()
        graph.units["Soldier_Veteran"] = ProducedUnit(
            name="Soldier_Veteran", display="Test Soldier"
        )
        graph.structures["Barracks"].trains_units.append("Soldier_Veteran")

        (node,) = faction_tree([graph])
        groups = {child["label"]: child for child in node["children"]}

        # The flat Units list collapses the two same-named variants into one group whose
        # children are the raw object names (each still a loadable leaf).
        (group,) = groups["Units  (2)"]["children"]
        assert group["label"] == "Test Soldier  (2)"
        assert group["object"] is None
        assert [child["label"] for child in group["children"]] == ["Soldier", "Soldier_Veteran"]
        assert all(child["object"] for child in group["children"])

        # The same grouping applies under the training structure.
        (barracks,) = groups["Structures  (1)"]["children"]
        trained = [c for c in barracks["children"] if not c["label"].startswith("research")]
        (trained_group,) = trained
        assert trained_group["label"] == "Test Soldier  (2)"

    def test_faction_tab_populates_and_loads_units(self, browser):
        _load_units(browser)
        browser._open_object_browser()
        ob = browser.object_browser
        ob._on_faction_tree(faction_tree([_toy_graph()]))

        faction_item = ob.faction_tree_widget.topLevelItem(0)
        assert faction_item.text(0) == "Testers  [Test]"
        # Drill to the trained unit and double-click it into the main window.
        structures = next(
            faction_item.child(i)
            for i in range(faction_item.childCount())
            if faction_item.child(i).text(0).startswith("Structures")
        )
        barracks = structures.child(0)
        soldier = barracks.child(0)
        browser._object_names = ["Soldier"]
        browser.game.load_document(parse("Object Soldier\nEnd\n", file="s.ini").document)
        ob._on_double_click(soldier, 0)
        assert browser.panel_a is not None
        assert browser.panel_a._current_obj.name == "Soldier"


FACTION_INFO_FIXTURE = """
PlayerTemplate FactionUiTest
    PlayableSide = Yes
    Side = UiSide
    BuildableHeroesMP = UiHero
    SpellBookMp = UiSpellBook
End
Object UiHero
End
Object UiSpellBook
End
"""


class TestFactionInfoCard:
    def _with_faction(self, browser):
        game = Game()
        game.load_document(parse(FACTION_INFO_FIXTURE, file="f.ini").document)
        browser.game = game
        browser._build_faction_info()
        return browser.faction_info

    def test_heroes_are_collapsed_under_one_section(self, browser):
        card = self._with_faction(browser)

        toggle = next(b for b in card.findChildren(QPushButton) if "Heroes (1)" in b.text())
        assert toggle.text().startswith("▸")  # collapsed by default
        hero_link = next(b for b in card.findChildren(QPushButton) if "UiHero" in b.text())
        # Visibility is asserted relative to the faction block (the whole card body is
        # itself collapsed by default, which would mask the hero grid's own flag).
        block = toggle.parentWidget()
        assert not hero_link.isVisibleTo(block)

        toggle.click()
        assert toggle.text().startswith("▾")
        assert hero_link.isVisibleTo(block)

    def test_expand_kicks_the_roster_build_and_fills_the_tally(self, browser, monkeypatch):
        card = self._with_faction(browser)
        assert browser._faction_tallies["FactionUiTest"].text() == ""

        graph = _toy_graph()
        graph.name = "FactionUiTest"
        calls = []

        def fake_ensure(on_ready, on_failed=None):
            calls.append(on_ready)
            on_ready([graph])

        monkeypatch.setattr(browser, "ensure_faction_graphs", fake_ensure)
        browser._toggle_faction_info()  # expand → build → tallies fill

        assert calls
        tally = browser._faction_tallies["FactionUiTest"].text()
        assert "1 structures" in tally and "1 units" in tally and "1 powers" in tally
        # A "Browse roster" link into the By-faction drill-down sits in the header row.
        assert any("Browse roster" in text for text in _buttons(card))


class TestTypoSearch:
    def test_exact_name_opens_directly(self, browser):
        _load_units(browser)
        browser.search.setText("MordorFighter")
        browser._on_enter()

        assert browser.panel_a is not None
        assert browser.panel_a._current_obj.name == "MordorFighter"

    def test_misspelled_name_offers_a_suggestion_that_opens(self, browser):
        _load_units(browser)
        browser.search.setText("MordrFighter")  # dropped an 'o'
        browser._on_enter()
        card = _panel_widget(browser)

        assert any("No unit matched" in text for text in _labels(card))
        assert any("MordorFighter" in text for text in _buttons(card))

        # Clicking the suggestion opens the unit.
        suggestion = next(b for b in card.findChildren(QPushButton) if "MordorFighter" in b.text())
        suggestion.click()
        assert browser.panel_a is not None
        assert browser.panel_a._current_obj.name == "MordorFighter"

    def test_misspelled_display_name_resolves_in_display_mode(self, browser):
        _load_units(browser)
        browser.string_search_toggle.setChecked(True)
        browser.search.setText("Mordor Orc Warier")  # typo of "Mordor Orc Warrior"
        browser._on_enter()
        card = _panel_widget(browser)

        assert any("Mordor Orc Warrior" in text for text in _buttons(card))

    def test_no_close_match_shows_a_gentle_nudge_not_a_button(self, browser):
        _load_units(browser)
        browser.search.setText("zzzzzzzz")
        browser._on_enter()
        card = _panel_widget(browser)

        assert any("No unit matched" in text for text in _labels(card))
        assert _buttons(card) == []  # nothing close enough to suggest

    def test_compare_typo_reports_the_closest_on_the_status_line(self, browser):
        _load_units(browser)
        browser.show_object("MordorFighter")  # panel A must exist before comparing
        browser.compare_search.setText("MordrFighter")
        browser._on_compare_enter()

        assert "MordorFighter" in browser.status.text()
