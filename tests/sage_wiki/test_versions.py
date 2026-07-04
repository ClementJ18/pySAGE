"""Reading and rewriting the wiki's version templates."""

import pytest

from sage_wiki.versions import VERSION_TEMPLATES, extract_version, replace_version

# Peripheral package (sage_wiki, deferred project): full suite only.
pytestmark = pytest.mark.full


def test_templates_cover_the_three_versions():
    assert set(VERSION_TEMPLATES) == {
        "Template:VER_LATEST",
        "Template:VER_STANDALONE",
        "Template:VER_UPCOMING",
    }


def test_extract_bare_value():
    assert extract_version("4.6.1") == "4.6.1"
    assert extract_version("  4.6.1\n") == "4.6.1"


def test_extract_ignores_noinclude_documentation():
    text = "4.6.1<noinclude>\n{{documentation}}\n</noinclude>"
    assert extract_version(text) == "4.6.1"


def test_extract_reads_includeonly_body():
    text = "<includeonly>4.6.1</includeonly><noinclude>doc</noinclude>"
    assert extract_version(text) == "4.6.1"


def test_replace_bare_value():
    assert replace_version("4.6.1", "4.7.0") == "4.7.0"


def test_replace_preserves_noinclude_documentation():
    text = "4.6.1<noinclude>\n{{documentation}}\n</noinclude>"
    assert replace_version(text, "4.7.0") == "4.7.0<noinclude>\n{{documentation}}\n</noinclude>"


def test_replace_rewrites_includeonly_body_in_place():
    text = "<includeonly>4.6.1</includeonly><noinclude>doc</noinclude>"
    expected = "<includeonly>4.7.0</includeonly><noinclude>doc</noinclude>"
    assert replace_version(text, "4.7.0") == expected
