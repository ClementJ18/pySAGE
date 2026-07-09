"""End-to-end parsing of the fixture BFME2 *campaign* saves - the two save kinds skirmish
fixtures don't exercise: a full in-mission campaign save (32 chunks, single-player mode, a
`CHUNK_Campaign` carrying the persistent-hero carry-over roster) and a between-missions
*mission* save (6 chunks, a `CHUNK_GameStateMap` stub with no embedded map, an objectless
`CHUNK_GameLogic`, and the roster as its only ini-name source).

Four fixtures, all from the BFME2 evil campaign: saves 1 & 2 are two stages of mission 1 (full
saves); "Auto Save for Evil 2" is the autosave between missions 1 and 2 and "Saved Game 3" is
the same point saved manually - both mission saves, byte-identical in their campaign/logic
stubs. Tests skip cleanly when a fixture is absent."""

from collections import Counter
from pathlib import Path

import pytest

from sage_save import (
    decode_campaign,
    decode_game_logic,
    decode_game_state_map,
    encode_campaign,
    encode_game_state_map,
    extract_map,
    harvest_campaign_references,
    harvest_references,
    parse_save_from_path,
)
from tests.sage_save.corpus import fixture_id

FIXTURES = Path(__file__).resolve().parent / "fixtures"
CAMPAIGN = FIXTURES / "campaign"
# The whole campaign corpus (both campaigns, all missions, full + between-missions stubs).
ALL_CAMPAIGN = sorted(CAMPAIGN.glob("*.BfME2Campaign"))
FULL_SAVES = [CAMPAIGN / "Saved Game 1.BfME2Campaign", CAMPAIGN / "Saved Game 2.BfME2Campaign"]
MISSION_SAVES = [
    CAMPAIGN / "Auto Save for Evil 2 - Grey Havens.BfME2Campaign",
    CAMPAIGN / "Saved Game 3.BfME2Campaign",
]
CAMPAIGN_SAVES = FULL_SAVES + MISSION_SAVES

# The seven persistent heroes the evil-campaign carry-over roster tracks (three Black Riders,
# one each of the others). The order within the roster differs by save stage - full saves group
# heroes per owning player, the merged between-missions roster does not - so tests compare as a
# multiset.
ROSTER_COUNTS = Counter(
    {
        "WildShelob": 1,
        "Drogoth": 1,
        "WildGoblinKing": 1,
        "EvilMenBlackRider": 3,
        "MordorMouthOfSauron": 1,
    }
)


def _require(path: Path) -> Path:
    if not path.is_file():
        pytest.skip(f"fixture save not present: {path.name}")
    return path


@pytest.fixture(params=CAMPAIGN_SAVES, ids=lambda p: p.stem.replace(" ", "_"))
def any_campaign(request):
    return _require(request.param)


@pytest.fixture(params=MISSION_SAVES, ids=lambda p: p.stem.replace(" ", "_"))
def any_mission(request):
    return _require(request.param)


# --- CHUNK_Campaign: the persistent-hero carry-over roster ---


def test_campaign_active_and_roster(any_campaign):
    campaign = decode_campaign(parse_save_from_path(any_campaign).chunk("CHUNK_Campaign"))
    assert campaign.version == 1
    assert campaign.active  # a campaign save has an active campaign (skirmish does not)
    assert campaign.current_campaign == "EVIL_CAMPAIGN"
    # saves 1-2 are mid-mission-1; the between-missions saves are the entry to mission 2
    expected_mission = 1 if any_campaign in FULL_SAVES else 2
    assert campaign.mission_number == expected_mission
    # The same seven heroes are carried in every save of this campaign, whatever the stage.
    assert Counter(h.name for h in campaign.heroes) == ROSTER_COUNTS


def test_campaign_encoder_is_exact_inverse(any_campaign):
    # The roster block is kept verbatim, so re-encoding reproduces the chunk byte-for-byte -
    # including for the skirmish-style empty case and the rich campaign case.
    chunk = parse_save_from_path(any_campaign).chunk("CHUNK_Campaign")
    assert encode_campaign(decode_campaign(chunk)) == chunk.payload


def test_campaign_upgrades_only_after_mission_progress():
    # Mid-mission (full saves), no hero has earned upgrades yet; the between-missions saves have
    # the mission-1 rewards baked into the roster.
    for path in FULL_SAVES:
        campaign = decode_campaign(parse_save_from_path(_require(path)).chunk("CHUNK_Campaign"))
        assert all(h.upgrades == [] for h in campaign.heroes)
        assert all(h.experience == 0.0 for h in campaign.heroes)


def test_mission_save_roster_has_earned_upgrades(any_mission):
    heroes = {
        h.name: h
        for h in decode_campaign(parse_save_from_path(any_mission).chunk("CHUNK_Campaign")).heroes
    }
    # the Mouth of Sauron earned two named upgrades; a Black Rider earned one
    assert heroes["MordorMouthOfSauron"].upgrades == [
        "Upgrade_MouthOfSauronEvilEye",
        "Upgrade_MouthOfSauronDoubt",
    ]
    assert heroes["EvilMenBlackRider"].upgrades == ["Upgrade_BlackRiderDreadVisage"]
    assert heroes["MordorMouthOfSauron"].experience > 0
    assert heroes["MordorMouthOfSauron"].rank >= 1


# --- mission (between-missions) saves: the stub variants ---


def test_mission_save_chunk_set(any_mission):
    # A mission save is a small fixed set - not the 32-chunk full save. It keeps GameState and
    # Campaign (the load-browser + carry-over), plus the map/logic stubs and the BFME preambles.
    names = [c.name.removeprefix("CHUNK_") for c in parse_save_from_path(any_mission).chunks]
    assert names == [
        "LivingWorldLogic",
        "Audio",
        "GameState",
        "Campaign",
        "GameStateMap",
        "GameLogic",
    ]


def test_mission_save_map_is_a_stub(any_mission):
    gsm = decode_game_state_map(parse_save_from_path(any_mission).chunk("CHUNK_GameStateMap"))
    assert gsm.version == 2
    assert not gsm.has_map  # no embedded map: the next mission boots a fresh one
    assert gsm.map_data == b""


def test_mission_save_extract_map_refuses(any_mission):
    with pytest.raises(ValueError, match="no embedded map"):
        extract_map(parse_save_from_path(any_mission))


def test_mission_save_game_logic_is_objectless(any_mission):
    # The between-missions GameLogic has no live objects and no template table; decoding must
    # yield an empty state rather than failing to locate the (absent) table.
    state = decode_game_logic(parse_save_from_path(any_mission).chunk("CHUNK_GameLogic"))
    assert state.objects == []
    assert state.templates == {}


def test_full_campaign_save_has_embedded_map():
    # A full campaign save still carries its map (single-player mode 0), unlike the mission stub.
    save = parse_save_from_path(_require(FULL_SAVES[0]))
    gsm = decode_game_state_map(save.chunk("CHUNK_GameStateMap"))
    assert gsm.has_map
    assert gsm.game_mode == 0  # single-player campaign, not skirmish (2)
    assert gsm.map_data[:4] == b"EAR\x00"


def test_game_state_map_stub_encoder_is_exact_inverse(any_mission):
    chunk = parse_save_from_path(any_mission).chunk("CHUNK_GameStateMap")
    assert encode_game_state_map(decode_game_state_map(chunk), chunk.payload) == chunk.payload


# --- Phase 3: the roster is a fatal ini cross-reference surface ---


def test_campaign_references_are_fatal(any_campaign):
    refs = harvest_campaign_references(parse_save_from_path(any_campaign))
    assert refs, "expected hero templates in a campaign roster"
    assert all(r.fatal for r in refs)
    assert all(r.kind in ("object_template", "upgrade") for r in refs)
    # every carried-over hero template is present as a reference
    templates = {r.name for r in refs if r.kind == "object_template"}
    assert set(ROSTER_COUNTS) <= templates


def test_mission_save_references_come_only_from_the_roster(any_mission):
    # A mission save has no live objects and no CHUNK_Players, so the roster is the whole harvest.
    save = parse_save_from_path(any_mission)
    assert harvest_references(save) == harvest_campaign_references(save)
    names = {r.name for r in harvest_references(save)}
    assert "Upgrade_BlackRiderDreadVisage" in names
    assert "MordorMouthOfSauron" in names


def test_references_merge_shared_hero_names():
    # In a full save a hero is both a live object (non-fatal) and a carry-over hero (fatal); it
    # must be reported once, fatal winning.
    refs = harvest_references(parse_save_from_path(_require(FULL_SAVES[0])))
    keys = [(r.kind, r.name) for r in refs]
    assert len(keys) == len(set(keys))  # no duplicate (kind, name)
    black_rider = [r for r in refs if r.name == "EvilMenBlackRider"]
    assert len(black_rider) == 1
    assert black_rider[0].fatal


# --- corpus-wide coverage over the full campaign fixture set (both campaigns, all missions) ---


@pytest.mark.parametrize("path", ALL_CAMPAIGN, ids=fixture_id)
def test_every_campaign_save_decodes(path):
    save = parse_save_from_path(_require(path))
    campaign = decode_campaign(save.chunk("CHUNK_Campaign"))
    assert campaign.active
    # both campaigns appear in the corpus, each on the expected side
    assert campaign.current_campaign in ("EVIL_CAMPAIGN", "GOOD_CAMPAIGN")
    assert campaign.campaign_flag == 1  # the constant int32 after the name
    assert campaign.mission_number >= 1  # decoded from the roster preamble
    # roster is never empty in a campaign save, and every hero re-encodes verbatim
    assert campaign.heroes
    chunk = save.chunk("CHUNK_Campaign")
    assert encode_campaign(campaign) == chunk.payload


def test_good_campaign_roster_is_the_free_peoples_heroes():
    # A Good-campaign full save carries the seven free-peoples carry-over heroes.
    good = decode_campaign(
        parse_save_from_path(_require(CAMPAIGN / "Saved Game 8.BfME2Campaign")).chunk(
            "CHUNK_Campaign"
        )
    )
    assert good.current_campaign == "GOOD_CAMPAIGN"
    assert {h.name for h in good.heroes} == {
        "ElvenElrond",
        "ElvenArwen",
        "ElvenHaldir",
        "DwarvenDain",
        "ElvenThranduil",
        "ElvenGlorfindel",
        "DwarvenGloin",
    }


def test_mission_number_tracks_progress():
    # The 0-based roster counter → 1-based mission index tracks the campaign across missions:
    # a mid-mission-1 save, then the autosaves entering missions 2 and 3.
    def mission(path):
        return decode_campaign(
            parse_save_from_path(_require(path)).chunk("CHUNK_Campaign")
        ).mission_number

    assert mission(CAMPAIGN / "Saved Game 1.BfME2Campaign") == 1
    assert mission(CAMPAIGN / "Auto Save for Evil 2 - Grey Havens.BfME2Campaign") == 2
    assert mission(CAMPAIGN / "Auto Save for Evil 3 - Shire.BfME2Campaign") == 3
