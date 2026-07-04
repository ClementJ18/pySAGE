"""Best-guess internal wiki linking (sage_wiki.links)."""

import pytest

import sage_ini.model.definitions  # noqa: F401  (register classes)
from sage_ini.model.game import Game
from sage_ini.parser.blockparser import parse
from sage_wiki.links import PageLinker, build_linker

# Peripheral package (sage_wiki, deferred project): full suite only.
pytestmark = pytest.mark.full


def load(text: str) -> Game:
    game = Game()
    result = parse(text, file="t.ini")
    assert not result.diagnostics
    game.load_document(result.document)
    return game


NAME_FIXTURE = """
Object Gandalf
  DisplayName = OBJECT:Gandalf
End
Object TowerGuard
  DisplayName = OBJECT:TowerGuard
End
Object Orc
  DisplayName = OBJECT:Orc
End
Object Nameless
End
"""
_NAME_STRINGS = {
    "OBJECT:Gandalf": "Gandalf",
    "OBJECT:TowerGuard": "Tower Guard",
    "OBJECT:Orc": "Orc",
}


def name_game() -> Game:
    game = load(NAME_FIXTURE)
    game.strings.update(_NAME_STRINGS)
    return game


def test_build_linker_keeps_only_names_with_a_page():
    game = name_game()
    # The wiki has Gandalf and Tower Guard, but not Orc; the linker only targets real pages.
    linker = build_linker(game, {"Gandalf", "Tower Guard"})
    assert linker.link("Gandalf") == "[[Gandalf]]"
    assert linker.link("Tower Guard") == "[[Tower Guard]]"
    assert linker.link("Orc") == "Orc"  # no page, left plain


def test_link_pipes_when_the_page_title_differs_in_case():
    # The cell text is the in-game display name; the page title is the validated wiki title.
    linker = build_linker(name_game(), {"Tower guard"})
    assert linker.link("Tower Guard") == "[[Tower guard|Tower Guard]]"


def test_link_is_case_insensitive_and_passes_unknowns_through():
    linker = build_linker(name_game(), {"Gandalf"})
    assert linker.link("gandalf") == "[[Gandalf|gandalf]]"
    assert linker.link("Sauron") == "Sauron"


def test_linkify_wraps_known_mentions_in_prose():
    linker = build_linker(name_game(), {"Gandalf", "Tower Guard"})
    text = "Summons Gandalf to bolster the Tower Guard."
    assert linker.linkify(text) == "Summons [[Gandalf]] to bolster the [[Tower Guard]]."


def test_linkify_links_each_target_only_once():
    linker = build_linker(name_game(), {"Gandalf"})
    text = "Gandalf calls, and Gandalf answers."
    # The first mention links; the wiki convention is to link a name once per page.
    assert linker.linkify(text) == "[[Gandalf]] calls, and Gandalf answers."


def test_linkify_does_not_link_short_names():
    # A three-letter name is too word-like to wrap blindly in prose, even with a page.
    linker = build_linker(name_game(), {"Orc"})
    assert linker.linkify("An Orc raid.") == "An Orc raid."
    # …but an exact table cell still links it.
    assert linker.link("Orc") == "[[Orc]]"


def test_linkify_respects_word_boundaries():
    linker = build_linker(name_game(), {"Gandalf"})
    # No false link inside a longer word.
    assert linker.linkify("Gandalfian robes") == "Gandalfian robes"


def test_empty_linker_leaves_text_untouched():
    linker = PageLinker({})
    assert linker.link("Gandalf") == "Gandalf"
    assert linker.linkify("Gandalf marches.") == "Gandalf marches."
    assert linker.linkify_wikitext("Gandalf marches.") == "Gandalf marches."


def test_linkify_wikitext_links_free_prose():
    linker = build_linker(name_game(), {"Gandalf", "Tower Guard"})
    text = "The Tower Guard hold while Gandalf arrives."
    assert linker.linkify_wikitext(text) == "The [[Tower Guard]] hold while [[Gandalf]] arrives."


def test_linkify_wikitext_does_not_touch_existing_links():
    linker = build_linker(name_game(), {"Gandalf"})
    # An already-linked name is stepped over, never wrapped again.
    assert linker.linkify_wikitext("[[Gandalf]] leads.") == "[[Gandalf]] leads."
    piped = "[[Gandalf|the wizard]] leads."
    assert linker.linkify_wikitext(piped) == piped


def test_linkify_wikitext_does_not_relink_a_name_already_linked_elsewhere():
    linker = build_linker(name_game(), {"Gandalf"})
    # The page links Gandalf once already; a later bare mention is left plain.
    text = "See [[Gandalf]]. Later, Gandalf returns."
    assert linker.linkify_wikitext(text) == "See [[Gandalf]]. Later, Gandalf returns."


def test_linkify_wikitext_leaves_template_parameters_alone():
    linker = build_linker(name_game(), {"Gandalf", "Tower Guard"})
    # A name inside a template (e.g. an infobox field) must not be linked — it would break the
    # template — but free prose after it still is.
    text = "{{Hero\n|object=Gandalf\n}}\nThe Tower Guard defend."
    out = linker.linkify_wikitext(text)
    assert "|object=Gandalf\n" in out  # untouched
    assert "[[Tower Guard]]" in out  # prose linked


def test_linkify_wikitext_handles_nested_templates():
    linker = build_linker(name_game(), {"Gandalf"})
    text = "{{A|{{B|Gandalf}}}} then Gandalf."
    out = linker.linkify_wikitext(text)
    assert out == "{{A|{{B|Gandalf}}}} then [[Gandalf]]."


def test_linkify_wikitext_skips_comments_and_refs():
    linker = build_linker(name_game(), {"Gandalf"})
    comment = "<!-- Gandalf note --> Gandalf."
    assert linker.linkify_wikitext(comment) == "<!-- Gandalf note --> [[Gandalf]]."
    ref = "Gandalf<ref>see Gandalf</ref> later."
    assert linker.linkify_wikitext(ref) == "[[Gandalf]]<ref>see Gandalf</ref> later."
