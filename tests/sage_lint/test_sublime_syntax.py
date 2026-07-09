"""The Sublime `.sublime-syntax` generator: its keyword lists come from sage_ini's class
registry, and its output must stay valid `.sublime-syntax` - in particular the `{{var}}`
variable references the f-string templating is easy to get wrong."""

import importlib.util
from pathlib import Path

_GENERATOR = (
    Path(__file__).resolve().parents[2] / "sage_lint" / "plugins" / "sublime" / "generate_syntax.py"
)


def _load():
    spec = importlib.util.spec_from_file_location("generate_syntax", _GENERATOR)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestGenerateSyntax:
    def test_renders_registry_keywords_with_intact_variable_references(self):
        text = _load().render()

        assert "name: Sage Lint" in text
        assert "scope: source.ini" in text
        # The Sublime variable references must survive f-string templating as single braces.
        assert "{{block_keywords}}" in text and "{{type_names}}" in text
        assert "{{{" not in text  # no over-escaped braces leaking through

        # Block keywords are the table-backed definitions; type names also cover modules.
        block, types = _load()._keyword_sets()
        assert "Object" in block.split("|") and "Weapon" in block.split("|")
        assert "AutoHealBehavior" in types.split("|")
        # Abstract `_`-prefixed bases never appear in source, so they are filtered out.
        assert not any(name.startswith("_") for name in types.split("|"))

    def test_committed_syntax_file_is_well_formed(self):
        # Exact equality with render() is avoided on purpose: other tests register extra
        # IniObject subclasses into the global registry, so a fresh render in the full suite
        # need not match the file generated from the canonical model. Check structure instead.
        text = _load()._OUTPUT.read_text(encoding="utf-8")

        assert text.startswith("%YAML 1.2")
        assert "name: Sage Lint" in text and "scope: source.ini" in text
        assert "{{block_keywords}}" in text and "{{type_names}}" in text
        assert "\t" not in text  # Sublime syntax must be space-indented
        # Single-quoted YAML scalars must stay balanced (the keyword lists are one each).
        for line in text.splitlines():
            if not line.lstrip().startswith("#"):
                assert line.count("'") % 2 == 0
