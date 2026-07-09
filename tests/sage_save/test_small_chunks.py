"""Step 1 - the nine small chunks handled by the generic `SmallChunk` codec.

The exact-inverse round-trip of each is already covered by the registry test in test_infra.py
(they are in `CHUNK_CODECS`). These tests pin the *reversing conclusions*: which chunks are a
fixed constant across every fixture (a change would mean a new field to decode), and the two that
carry real, varying data (`WeatherSystem`, `MissionObjectives`). They double as tripwires - if a
future save makes a "constant" chunk vary, the assertion fails and flags it for a fuller decode.
"""

from pathlib import Path

import pytest

from sage_save import coverage_summary, decode_small_chunk, parse_save_from_path
from sage_save.chunks import CHUNK_CODECS, decode_campaign
from tests.sage_save.corpus import ALL_SAVES as SAVE_FILES
from tests.sage_save.corpus import FIXTURES

SKIRMISH = FIXTURES / "Saved Game 1.BfME2Skirmish"

# Chunks whose payload is byte-identical across every fixture (a fixed empty/default state), with
# the constant value observed. WeatherSystem and MissionObjectives are excluded (they vary).
CONSTANT_CHUNKS = {
    "CHUNK_MineshaftPortalNetworkManager": "01",
    "CHUNK_Partition": "0101",
    "CHUNK_Collision": "0101",
    "CHUNK_SpellStore": "0101",
    "CHUNK_ObjectivesMenu": "0101",
    "CHUNK_InGameUI": "020000000001010000000000ffffffff00000000",
    "CHUNK_LivingWorldLogic": "0600000000000000000000000046040000ffffffff00",
}


def _require(path: Path) -> Path:
    if not path.is_file():
        pytest.skip(f"fixture save not present: {path.name}")
    return path


def test_all_nine_registered():
    small_names = {
        "CHUNK_MineshaftPortalNetworkManager",
        "CHUNK_Partition",
        "CHUNK_Collision",
        "CHUNK_SpellStore",
        "CHUNK_ObjectivesMenu",
        "CHUNK_MissionObjectives",
        "CHUNK_InGameUI",
        "CHUNK_LivingWorldLogic",
        "CHUNK_WeatherSystem",
    }
    assert small_names <= set(CHUNK_CODECS)


@pytest.mark.parametrize("name,expected_hex", sorted(CONSTANT_CHUNKS.items()))
def test_constant_chunks_are_the_known_fixed_value(name, expected_hex):
    # These must hold in every fixture that carries the chunk; a divergence means a real field.
    seen = False
    for path in SAVE_FILES:
        save = parse_save_from_path(path)
        chunk = save.chunk(name)
        if chunk is None:
            continue
        seen = True
        assert chunk.payload.hex() == expected_hex, f"{name} changed in {path.name}"
    if not seen:
        pytest.skip(f"no fixture carries {name}")


def test_small_chunk_decode_splits_version_and_body():
    save = parse_save_from_path(_require(SKIRMISH))
    decoded = decode_small_chunk(save.chunk("CHUNK_LivingWorldLogic"))
    assert decoded.version == 6
    assert len(decoded.body) == 21  # 22-byte payload minus the version byte


def test_mission_objectives_empty_in_skirmish():
    # A skirmish save has no mission objectives: version 1 + a single empty-list byte.
    save = parse_save_from_path(_require(SKIRMISH))
    decoded = decode_small_chunk(save.chunk("CHUNK_MissionObjectives"))
    assert decoded.version == 1
    assert decoded.body == b"\x00"


def test_mission_objectives_lists_scripts_in_campaign():
    # In a campaign save the chunk carries the mission's objective/bonus script names (kept in the
    # opaque body for now - a fuller decode is deferred with the other script-bearing chunks).
    path = FIXTURES / "campaign" / "Saved Game 1.BfME2Campaign"
    save = parse_save_from_path(_require(path))
    chunk = save.chunk("CHUNK_MissionObjectives")
    assert len(chunk.payload) > 100
    assert b"SCRIPT:OBJECTIVE_" in chunk.payload
    assert b"SCRIPT:BONUS_" in chunk.payload


def test_weather_system_version_and_varying_seed():
    # WeatherSystem is version 4, constant but for an equal int32 pair near the end that differs
    # per save (a weather seed/offset). Collect the pair across saves; expect more than one value.
    seeds = set()
    for path in SAVE_FILES:
        save = parse_save_from_path(path)
        chunk = save.chunk("CHUNK_WeatherSystem")
        if chunk is None:
            continue
        decoded = decode_small_chunk(chunk)
        assert decoded.version == 4
        # the pair sits at payload bytes 53..61 (two equal little-endian int32s)
        pair = chunk.payload[53:61]
        assert pair[:4] == pair[4:], "the two int32s of the pair are equal"
        seeds.add(pair)
    if seeds:
        assert len(seeds) > 1, "the weather seed should differ between saves"


def test_full_save_coverage_after_step1():
    # four core decoders + the nine small chunks + TacticalView + TeamFactory + GameClient
    # + ScriptEngine + Players
    summary = coverage_summary(parse_save_from_path(_require(SKIRMISH)))
    assert summary.chunks_decoded == 18


def test_campaign_still_decodes_after_step1():
    # Sanity: registering the small chunks did not disturb the richer decoders.
    save = parse_save_from_path(_require(FIXTURES / "campaign" / "Saved Game 1.BfME2Campaign"))
    assert decode_campaign(save.chunk("CHUNK_Campaign")).active
