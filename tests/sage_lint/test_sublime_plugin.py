"""The Sublime plugin's symbol resolution.

The plugin runs inside Sublime's own interpreter and cannot import `sage_ini`, so its notion of
where a name ends is a second copy of the rule in `sage_ini.model.aliases`. A copy that drifts
would make Go to Definition and the hover popups quietly stop resolving on annotated references,
which nothing else would catch - hence these tests, which load the plugin with `sublime` stubbed.
"""

import importlib.util
import sys
import types
from pathlib import Path

import pytest

from sage_ini.model.aliases import ALIAS_SEPARATOR

_PLUGIN = Path(__file__).resolve().parents[2] / "sage_lint" / "plugins" / "sublime" / "sage_lint.py"


@pytest.fixture(scope="module")
def plugin():
    """The plugin module, imported against stub `sublime` / `sublime_plugin` modules. The stubs
    only have to satisfy import-time attribute lookups; nothing here calls into the editor."""
    saved = {name: sys.modules.get(name) for name in ("sublime", "sublime_plugin")}
    sublime = types.ModuleType("sublime")
    for attribute in ("Region", "INHIBIT_WORD_COMPLETIONS", "INHIBIT_EXPLICIT_COMPLETIONS"):
        setattr(sublime, attribute, 0)
    sublime_plugin = types.ModuleType("sublime_plugin")
    for attribute in (
        "TextCommand",
        "WindowCommand",
        "EventListener",
        "ViewEventListener",
        "ApplicationCommand",
    ):
        setattr(sublime_plugin, attribute, type(attribute, (), {}))
    sys.modules["sublime"] = sublime
    sys.modules["sublime_plugin"] = sublime_plugin
    try:
        spec = importlib.util.spec_from_file_location("st_sage_lint", _PLUGIN)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        yield module
    finally:
        for name, previous in saved.items():
            if previous is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous


class TestNameCharacters:
    def test_the_separator_is_part_of_a_symbol(self, plugin):
        # Widening the token past `@` is what lets the caret resolve from the annotation half;
        # `_name_variants` is what turns it back into an indexed name.
        assert plugin._NAME_CHAR_RE.match(ALIAS_SEPARATOR)

    def test_ordinary_name_characters_still_match(self, plugin):
        for character in "Aa_9:+-":
            assert plugin._NAME_CHAR_RE.match(character), character

    def test_a_separator_is_not_a_name_character_elsewhere(self, plugin):
        for character in " \t;=/":
            assert not plugin._NAME_CHAR_RE.match(character), character


class TestNameVariants:
    def test_an_aliased_reference_resolves_to_the_upgrade(self, plugin):
        assert "Upgrade_TestBuilding" in plugin._name_variants("Upgrade_TestBuilding@Smithy")

    def test_a_leading_marker_resolves_to_the_upgrade(self, plugin):
        # `@Name` is the create-a-hero default-bling marker, not an alias with an empty name.
        assert "Upgrade_NoHelmet" in plugin._name_variants("@Upgrade_NoHelmet")

    def test_the_raw_token_is_tried_first(self, plugin):
        # A definition really spelled with the character would still win over the peeled form.
        assert plugin._name_variants("Upgrade_X@Smithy")[0] == "Upgrade_X@Smithy"

    def test_a_plain_name_is_unchanged(self, plugin):
        assert plugin._name_variants("Upgrade_TestBuilding") == ["Upgrade_TestBuilding"]

    def test_the_alias_half_is_never_offered_as_a_name(self, plugin):
        # Resolving to `Smithy` would send Go to Definition to whatever happened to be named
        # that, which is a different symbol entirely.
        assert "Smithy" not in plugin._name_variants("Upgrade_X@Smithy")

    def test_it_composes_with_the_existing_prefix_and_label_peeling(self, plugin):
        assert "ElvenVigilantEnt" in plugin._name_variants("+ElvenVigilantEnt@Escort")

    def test_a_lone_separator_yields_no_empty_name(self, plugin):
        assert all(variant for variant in plugin._name_variants(ALIAS_SEPARATOR))
