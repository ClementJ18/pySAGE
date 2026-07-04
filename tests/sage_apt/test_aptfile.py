"""Round-trip tests over the SpellStore fixture (RotWK / Edain spellbook store UI —
a pristine game file, not a re-export) plus data-free unit tests for the flag
conversions."""

import shutil
from collections import Counter
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from sage_apt import AptError, apt_to_xml, render_viewer_html, xml_to_apt
from sage_apt.flags import (
    get_but_action_flags_int,
    get_but_action_flags_str,
    get_but_flags_int,
    get_but_flags_str,
    get_po_flags_int,
    get_po_flags_str,
)

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def workdir(tmp_path):
    shutil.copy(FIXTURES / "SpellStore.apt", tmp_path / "SpellStore.apt")
    shutil.copy(FIXTURES / "SpellStore.const", tmp_path / "SpellStore.const")
    return tmp_path


@pytest.fixture
def spellstore_xml(workdir):
    assert apt_to_xml(workdir / "SpellStore.apt") == workdir / "SpellStore.xml"
    return workdir / "SpellStore.xml"


def test_apt_to_xml_structure(spellstore_xml):
    root = ET.parse(spellstore_xml).getroot()
    assert root.tag == "aptdata"

    movieclip = root.find("movieclip")
    assert movieclip is not None
    frames = movieclip.find("frames")
    assert frames is not None and len(frames) == 24

    counts = Counter(ch.tag for ch in root)
    assert counts["sprite"] > 20
    assert counts["shape"] > 20
    assert counts["image"] > 20
    assert counts["button"] == 3
    assert counts["edittext"] >= 2
    assert counts["font"] >= 2

    # The import that ties the store into the in-game shell
    imports = movieclip.find("imports")
    assert imports is not None and len(imports) >= 1


def test_buttons_have_records_and_actions(spellstore_xml):
    """Buttons carry hit geometry, state records, and ActionScript handlers; these
    were silently lost by the original exporter's struct layout."""
    root = ET.parse(spellstore_xml).getroot()
    buttons = [ch for ch in root if ch.tag == "button"]
    assert buttons
    for button in buttons:
        assert button.find("vertexes") is not None
        assert button.find("triangles") is not None
        records = button.find("buttonrecords")
        assert records is not None and len(records) >= 1
        actions = button.find("buttonactions")
        assert actions is not None and len(actions) >= 1


def test_round_trip_is_stable(workdir, spellstore_xml):
    """apt -> xml -> apt -> xml must reproduce the first XML exactly."""
    first = spellstore_xml.read_bytes()
    apt_path, const_path = xml_to_apt(spellstore_xml)
    assert apt_path == workdir / "SpellStore.apt"
    assert const_path == workdir / "SpellStore.const"
    assert apt_to_xml(workdir / "SpellStore.apt")
    assert spellstore_xml.read_bytes() == first


def test_rewritten_const_parses(workdir, spellstore_xml):
    xml_to_apt(spellstore_xml)
    const = (workdir / "SpellStore.const").read_bytes()
    assert const.startswith(b"Apt constant file")


def test_viewer_renders(spellstore_xml):
    html = render_viewer_html(spellstore_xml)
    assert "<svg" in html
    assert html.count('class="apt-elem"') > 50
    assert "SpellStore.xml" in html


def test_missing_apt_raises(tmp_path):
    with pytest.raises(AptError, match="file is missing"):
        apt_to_xml(tmp_path / "Nope.apt")


def test_missing_const_raises(tmp_path):
    shutil.copy(FIXTURES / "SpellStore.apt", tmp_path / "SpellStore.apt")
    with pytest.raises(AptError, match=r"\.const file is missing"):
        apt_to_xml(tmp_path / "SpellStore.apt")


def test_non_xml_input_raises(tmp_path):
    not_xml = tmp_path / "SpellStore.txt"
    not_xml.write_text("whatever")
    with pytest.raises(AptError, match="not an .xml file"):
        xml_to_apt(not_xml)


def test_malformed_xml_raises(tmp_path):
    bad = tmp_path / "Broken.xml"
    bad.write_text("<aptdata><movieclip></aptdata>")
    with pytest.raises(AptError, match="malformed XML"):
        xml_to_apt(bad)


def test_failed_compile_leaves_no_output(workdir, spellstore_xml):
    """A mid-build failure must never create or modify the .apt/.const pair."""
    apt_path = workdir / "SpellStore.apt"
    const_path = workdir / "SpellStore.const"

    # Corrupt a placeobject attribute so the movie build raises mid-way.
    text = spellstore_xml.read_text(encoding="utf-8")
    corrupted = text.replace('tx="', 'tx="bogus', 1)
    assert corrupted != text
    spellstore_xml.write_text(corrupted, encoding="utf-8")

    apt_before = apt_path.read_bytes()
    const_before = const_path.read_bytes()
    with pytest.raises(ValueError):
        xml_to_apt(spellstore_xml)
    assert apt_path.read_bytes() == apt_before
    assert const_path.read_bytes() == const_before

    # And with the pair removed, a failed compile creates neither file.
    apt_path.unlink()
    const_path.unlink()
    with pytest.raises(ValueError):
        xml_to_apt(spellstore_xml)
    assert not apt_path.exists()
    assert not const_path.exists()


def test_po_flags_round_trip():
    for value in (0x01, 0x02 | 0x04 | 0x08, 0x20 | 0x40, 0xFF):
        assert get_po_flags_int(get_po_flags_str(value)) == value
    assert get_po_flags_str(0) == ""
    assert get_po_flags_int("") == 0


def test_but_flags_round_trip():
    for value in (0x01, 0x0F, 0x02 | 0x08):
        assert get_but_flags_int(get_but_flags_str(value)) == value


def test_but_action_flags_round_trip():
    # Condition bits plus the 7-bit keypress field (printable and named keys)
    for value in (0x0001, 0x8000, 0x0100 | 0x0200, ord("A") << 1, 4 << 1 | 0x0001):
        assert get_but_action_flags_int(get_but_action_flags_str(value)) == value
