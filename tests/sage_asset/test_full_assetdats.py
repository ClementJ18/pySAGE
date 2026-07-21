"""Corpus acceptance gate: parses and re-writes every real asset.dat fixture in
tests/sage_asset/fixtures/assetdats/, byte-exact. Needs real game/mod asset.dat files on disk
(not committed), so it belongs in the opt-in `--full` tier."""

import struct
from pathlib import Path

import pytest

from sage_asset.assetdat import AssetDat, combine_asset_dats, parse_asset_dat, write_asset_dat

pytestmark = pytest.mark.full


def _fixture_paths() -> list[Path]:
    fixtures_dir = Path(__file__).parent / "fixtures" / "assetdats"
    if not fixtures_dir.exists():
        return []
    return sorted(fixtures_dir.glob("*.dat"))


def _params():
    paths = _fixture_paths()
    if not paths:
        return [pytest.param(None, marks=pytest.mark.skip(reason="no asset.dat fixtures present"))]
    return paths


@pytest.mark.parametrize("dat_path", _params(), ids=lambda p: p.name if p else "no-fixtures")
def test_parse_and_round_trip(dat_path: Path):
    data = dat_path.read_bytes()

    ad = parse_asset_dat(data)

    assert write_asset_dat(ad) == data


def _section1_and_section2(ad: AssetDat, data: bytes) -> tuple[bytes, bytes]:
    """`ad`'s section-1 bytes (re-serialized with no references, then the header sliced off)
    and `data`'s section-2 bytes (whatever in the original file follows that section 1)."""
    section1 = write_asset_dat(AssetDat(version=ad.version, files=ad.files, references=[]))[16:]
    section2 = data[16 + len(section1) :]
    return section1, section2


def test_combine_bfme2_and_edain_mod_matches_byte_level_splice():
    """`edain_complete.dat` cannot be reproduced byte-for-byte here (it was built from an older
    `_mod/asset.dat` than the one in the corpus), so this proves the splice at the byte level
    instead: combining BFME2's asset.dat with the mod's must write out to exactly the two
    inputs' section-1 payloads back to back, followed by their section-2 payloads back to back,
    under one summed header - the same layout the shipping combined file was verified against."""
    fixtures_dir = Path(__file__).parent / "fixtures" / "assetdats"
    a_path = fixtures_dir / "bfme2.dat"
    b_path = fixtures_dir / "edain_mod.dat"
    if not a_path.is_file() or not b_path.is_file():
        pytest.skip("bfme2.dat / edain_mod.dat fixtures not present")

    a_data = a_path.read_bytes()
    b_data = b_path.read_bytes()
    a = parse_asset_dat(a_data)
    b = parse_asset_dat(b_data)

    s1a, s2a = _section1_and_section2(a, a_data)
    s1b, s2b = _section1_and_section2(b, b_data)

    combined = combine_asset_dats(a, b)
    header = struct.pack(
        "<4sIII",
        b"ALAE",
        a.version,
        len(a.files) + len(b.files),
        len(a.references) + len(b.references),
    )

    assert write_asset_dat(combined) == header + s1a + s1b + s2a + s2b
