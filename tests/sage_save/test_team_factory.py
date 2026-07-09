"""`CHUNK_TeamFactory` - team prototypes (Step 3, header only).

The GPL `TeamFactory::xfer` header (unique-team-ID counter + prototype count) ports cleanly, and
each prototype body even *starts* like ZH's `TeamPrototype::xfer` (v2, `owningPlayerIndex`,
`attackPriorityName`) - but the embedded `TeamTemplateInfo` is BFME2 version 3 (ZH is v1) with
undocumented extra fields, so the per-prototype walk (and the team→player attribution it would
yield) is not completed and the prototype block is kept opaque. These tests pin the decoded
header; the exact-inverse round-trip is covered by the registry test in test_infra.py."""

from pathlib import Path

import pytest

from sage_save import decode_team_factory, parse_save_from_path

FIXTURES = Path(__file__).resolve().parent / "fixtures"
SKIRMISH = FIXTURES / "Saved Game 4.BfME2Skirmish"


def _save(path=SKIRMISH):
    if not path.is_file():
        pytest.skip(f"fixture not present: {path.name}")
    return parse_save_from_path(path)


def test_header_decodes():
    tf = decode_team_factory(_save().chunk("CHUNK_TeamFactory"))
    assert tf.version == 3
    assert tf.prototype_count == 111  # team prototypes on the enedwaith map
    assert tf.unique_team_id > 0  # the next-team-instance id counter has advanced past setup
    assert tf.body  # the prototype records, kept opaque (walk blocked at TeamTemplateInfo v3)


def test_prototype_count_is_map_specific():
    # harlindon (saves 1/2) has fewer team prototypes than enedwaith (save 4)
    harlindon = FIXTURES / "Saved Game 1.BfME2Skirmish"
    assert decode_team_factory(_save(harlindon).chunk("CHUNK_TeamFactory")).prototype_count == 74


def test_unique_team_id_grows_through_the_match():
    # as teams are spawned across the enedwaith time-series the id counter only advances
    ids = []
    for n in (4, 7, 9):
        path = FIXTURES / f"Saved Game {n}.BfME2Skirmish"
        if path.is_file():
            ids.append(
                decode_team_factory(
                    parse_save_from_path(path).chunk("CHUNK_TeamFactory")
                ).unique_team_id
            )
    if len(ids) == 3:
        assert ids[0] <= ids[1] <= ids[2]
