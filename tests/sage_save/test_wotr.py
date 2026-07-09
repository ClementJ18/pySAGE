"""War-of-the-Ring saves (Edain) - battle vs living-world, and the one detectable corruption.

WotR sits outside the auto-discovered corpus (see `corpus.py`): the mode and the Edain mod diverge
from the BFME2 invariants the corpus-wide tests assert. This module pins what the tooling concludes
about each kind:

- **Battle saves** (`ang 5`, `Saved Game 4`) are full in-battle snapshots - an embedded map and a
  live object/drawable index. They exercise the Edain-specific decode: the `CHUNK_GameLogic` object
  table carries Latin-1 template names (German umlauts), and its preamble embeds `Command_*` strings
  that a naive locator mistakes for a one-entry table. The table locator must survive both.
- **Living-world saves** (`Saved Game 2/3/5/6/7`) are valid, loadable strategic-layer saves that are
  *objectless by nature*: no embedded battle map, no live objects. They are the counter-examples
  that make "no map + no objects" a normal state, not a corruption signal - so the tooling must
  parse them, round-trip them, and report them clean.
- **`angmar 6`** the game reports corrupt, yet it is structurally an ordinary objectless
  living-world save (parses, re-encodes exactly). The tooling cannot distinguish it from a valid
  one, and must not pretend to - the only assertion is that it parses and round-trips.
- **`angmar 7`** is an interrupted write whose container does not parse - the one WotR corruption
  the tooling can actually detect.
"""

from pathlib import Path

import pytest

from sage_save import (
    decode_game_client,
    decode_game_logic,
    decode_game_state_map,
    decode_living_world_logic,
    diagnose_save,
    encode_game_client,
    encode_game_logic,
    encode_living_world_logic,
    harvest_living_world_references,
    living_world_names,
    living_world_object_templates,
    parse_save,
    parse_save_from_path,
    write_save,
)
from tests.sage_save.corpus import (
    ALL_SKIRMISH,
    WOTR_BATTLE,
    WOTR_GAME_CORRUPT,
    WOTR_LIVING_WORLD,
    WOTR_PARSEABLE,
    WOTR_TRUNCATED,
    fixture_id,
)


def _require(path: Path) -> Path:
    if not path.is_file():
        pytest.skip(f"fixture not present: {path.name}")
    return path


def _chunk(save, name):
    chunk = save.chunk(name)
    assert chunk is not None, f"missing {name}"
    return chunk


# --- every parseable WotR save: container and modelled chunks round-trip -----------------------


@pytest.mark.parametrize("path", WOTR_PARSEABLE, ids=fixture_id)
def test_parseable_save_container_round_trips(path):
    save = parse_save_from_path(_require(path))
    assert write_save(save) == path.read_bytes()


@pytest.mark.parametrize("path", WOTR_PARSEABLE, ids=fixture_id)
def test_game_logic_and_client_re_encode_exactly(path):
    """Object/drawable-index decode is byte-exact whether the save has a live world (battle) or
    none (living-world) - the objectless case must re-encode to just version + frame + trailing,
    not an empty table."""
    save = parse_save_from_path(_require(path))
    logic_chunk = _chunk(save, "CHUNK_GameLogic")
    client_chunk = _chunk(save, "CHUNK_GameClient")
    assert encode_game_logic(decode_game_logic(logic_chunk)) == logic_chunk.payload
    assert encode_game_client(decode_game_client(client_chunk)) == client_chunk.payload


# --- battle saves: an embedded map and a live index -------------------------------------------


@pytest.mark.parametrize("path", WOTR_BATTLE, ids=fixture_id)
def test_battle_save_has_map_and_live_objects(path):
    save = parse_save_from_path(_require(path))
    assert decode_game_state_map(_chunk(save, "CHUNK_GameStateMap")).has_map is True
    logic = decode_game_logic(_chunk(save, "CHUNK_GameLogic"))
    client = decode_game_client(_chunk(save, "CHUNK_GameClient"))
    assert logic.objects, "a battle save must carry a live object index"
    # the drawable index mirrors the object index one-for-one
    assert len(client.drawables) == len(logic.objects)


def test_battle_save_decodes_umlaut_template_names():
    """The Edain object table decodes with its Latin-1 (umlaut) names intact - the regression guard
    for the strict-ASCII locator that used to slide past the real table onto a spurious match."""
    save = parse_save_from_path(_require(WOTR_BATTLE[0]))
    templates = decode_game_logic(_chunk(save, "CHUNK_GameLogic")).templates
    assert [n for n in templates.values() if any(ord(ch) > 127 for ch in n)]


# --- living-world saves: valid, objectless, and clean -----------------------------------------


@pytest.mark.parametrize("path", WOTR_LIVING_WORLD, ids=fixture_id)
def test_living_world_save_is_objectless(path):
    """No embedded battle map and no live objects - the normal shape of a strategic-layer save. The
    locator must *not* invent a one-entry table from the `Command_*` strings in the preamble."""
    save = parse_save_from_path(_require(path))
    assert decode_game_state_map(_chunk(save, "CHUNK_GameStateMap")).has_map is False
    assert decode_game_logic(_chunk(save, "CHUNK_GameLogic")).objects == []
    assert decode_game_client(_chunk(save, "CHUNK_GameClient")).drawables == []


@pytest.mark.parametrize("path", WOTR_LIVING_WORLD, ids=fixture_id)
def test_living_world_save_diagnoses_clean(path):
    """A valid living-world save must carry no fatal diagnostic - the tooling must not read its
    empty world as corruption (the mistake `WOTR_GAME_CORRUPT` would otherwise provoke)."""
    save = parse_save_from_path(_require(path))
    assert not [d for d in diagnose_save(save) if d.severity == "fatal"]


# --- angmar 6: game-corrupt but structurally indistinguishable --------------------------------


def test_game_corrupt_save_is_structurally_indistinguishable():
    """It parses and re-encodes byte-exactly like a valid living-world save; the tooling has no
    structural signal to flag it, and asserting otherwise would over-fit a sample of one."""
    save = parse_save_from_path(_require(WOTR_GAME_CORRUPT))
    assert write_save(save) == WOTR_GAME_CORRUPT.read_bytes()
    assert decode_game_logic(_chunk(save, "CHUNK_GameLogic")).objects == []


# --- LivingWorldLogic: the WotR strategic roster ----------------------------------------------


@pytest.mark.parametrize("path", WOTR_PARSEABLE, ids=fixture_id)
def test_living_world_logic_round_trips_and_harvests_a_roster(path):
    """Every WotR save (battle or living-world) populates `CHUNK_LivingWorldLogic`, and the roster
    harvest pulls a plausible strategic roster: at least one `LWA:*` army and the standard player
    slots. The chunk still re-encodes byte-exactly (the names are a view, the body is opaque)."""
    save = parse_save_from_path(_require(path))
    chunk = _chunk(save, "CHUNK_LivingWorldLogic")
    state = decode_living_world_logic(chunk)

    assert encode_living_world_logic(state) == chunk.payload
    assert state.version == 6
    assert any(name.startswith("LWA:") for name in state.names)
    assert "Player_1" in state.names
    # a real roster names dozens of things; no garbage means the strict scan found a dense set
    assert len(state.names) > 50


@pytest.mark.parametrize("path", WOTR_BATTLE + WOTR_LIVING_WORLD, ids=fixture_id)
def test_living_world_army_object_templates_are_harvested(path):
    """The `02 01` roster-entry signature pulls the army rosters' unit/hero object templates - a
    non-empty set of `object_template` references, all non-fatal, and distinct (no runtime instance
    names like `DurmarthPlayerArmy` leak in)."""
    save = parse_save_from_path(_require(path))
    templates = living_world_object_templates(_chunk(save, "CHUNK_LivingWorldLogic").payload)
    assert templates, "expected the living-world armies to field object templates"
    assert len(templates) == len(set(templates))  # distinct
    # no instance-name shapes (those never carry the 02 01 marker)
    assert not [t for t in templates if t.startswith(("LWA:", "Player_")) or t.endswith("Army")]

    refs = harvest_living_world_references(save)
    assert {r.name for r in refs} == set(templates)
    assert all(r.kind == "object_template" and not r.fatal for r in refs)


def test_object_template_harvest_excludes_createahero_instance_names():
    """`angmar 6` carries a CreateAHero roster whose entries (`OrcChief01`) are runtime instance
    names, not ini definitions - they use a separate `00 00 00 0a` framing that the object-template
    signature (`02 01`) deliberately does not match. `OrcChief01` must appear in the informational
    roster view but never in the harvested object templates, or it would become a false dangling
    reference. This pins the boundary that keeps the CreateAHero list out of the xref surface."""
    save = parse_save_from_path(_require(WOTR_GAME_CORRUPT))
    payload = _chunk(save, "CHUNK_LivingWorldLogic").payload
    assert "OrcChief01" in living_world_names(payload)
    assert "OrcChief01" not in living_world_object_templates(payload)


def test_living_world_logic_is_empty_in_a_non_wotr_save():
    """A vanilla skirmish save's `CHUNK_LivingWorldLogic` is the 22-byte no-living-world constant -
    the harvest must yield an empty roster, not invent names from the fixed bytes."""
    skirmish = next((p for p in ALL_SKIRMISH if p.is_file()), None)
    if skirmish is None:
        pytest.skip("no skirmish fixture present")
    save = parse_save_from_path(skirmish)
    assert decode_living_world_logic(_chunk(save, "CHUNK_LivingWorldLogic")).names == []


# --- angmar 7: the one detectable corruption --------------------------------------------------


def test_truncated_save_container_does_not_parse():
    data = _require(WOTR_TRUNCATED).read_bytes()
    with pytest.raises(ValueError):
        parse_save(data)
