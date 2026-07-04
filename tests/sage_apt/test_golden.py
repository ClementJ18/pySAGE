"""Golden byte-freeze for the SpellStore fixture (Phase 7 foundation).

Freezes the exact bytes of (a) the decompiled XML and (b) the `.apt`/`.const` recompiled
from that XML, so any refactor of the reader/writer (e.g. the typed-model rewrite) is
diffed against frozen output rather than only self-consistency. Regenerate deliberately
with `tools`/by hand only when an intended output change is reviewed."""

import shutil
from pathlib import Path

from sage_apt import apt_to_xml, xml_to_apt

FIXTURES = Path(__file__).parent / "fixtures"
GOLDEN = FIXTURES / "golden"


def test_decompile_matches_golden_xml(tmp_path):
    shutil.copy(FIXTURES / "SpellStore.apt", tmp_path / "SpellStore.apt")
    shutil.copy(FIXTURES / "SpellStore.const", tmp_path / "SpellStore.const")
    xml = apt_to_xml(tmp_path / "SpellStore.apt")
    assert xml.read_bytes() == (GOLDEN / "decompiled.xml").read_bytes()


def test_recompile_matches_golden_binary(tmp_path):
    xml = tmp_path / "SpellStore.xml"
    shutil.copy(GOLDEN / "decompiled.xml", xml)
    apt_path, const_path = xml_to_apt(xml)
    assert apt_path.read_bytes() == (GOLDEN / "recompiled.apt").read_bytes()
    assert const_path.read_bytes() == (GOLDEN / "recompiled.const").read_bytes()
