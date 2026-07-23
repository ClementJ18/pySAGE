"""Corpus acceptance gate: parses and re-writes every real .cah fixture in
tests/sage_cah/fixtures/{bfme2,rotwk}/, byte-exact, and confirms the stored checksum validates.
Needs the real shipped example-hero files on disk (not committed), so it belongs in the opt-in
`--full` tier."""

from pathlib import Path

import pytest

from sage_cah.cah import POWER_SLOT_COUNT, parse_cah, write_cah

pytestmark = pytest.mark.full


def _fixture_paths() -> list[Path]:
    fixtures_dir = Path(__file__).parent / "fixtures"
    if not fixtures_dir.exists():
        return []
    return sorted(fixtures_dir.glob("*/*.cah"))


def _params():
    paths = _fixture_paths()
    if not paths:
        return [pytest.param(None, marks=pytest.mark.skip(reason="no .cah fixtures present"))]
    return paths


@pytest.mark.parametrize(
    "cah_path",
    _params(),
    ids=lambda p: f"{p.parent.name}/{p.name}" if p else "no-fixtures",
)
def test_parse_round_trips_byte_exact_and_checksum_is_valid(cah_path: Path):
    data = cah_path.read_bytes()

    hero = parse_cah(data)

    assert write_cah(hero) == data
    assert hero.checksum_valid
    assert hero.is_system_hero == 1
    assert len(hero.powers) == POWER_SLOT_COUNT
    assert all(not power.is_empty for power in hero.powers[:10])
    assert all(power.is_empty for power in hero.powers[10:])
    assert len(hero.blings) == 12
