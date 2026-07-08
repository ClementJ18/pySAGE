"""Task 3 (first slice) — the `Object::xfer` prefix head.

The session1 "unit moving" delta bounded it: every object body opens with a version byte
(26), an ascii echo of its template name, a u32 echo of its object id, and the 12-float 3x4
transform whose translation column moved with the unit while everything else held still.
Both echoes are validated against the object index, so the decode cannot silently misalign.
The scalars after the matrix stay undecoded for now (health/veterancy want the still-missing
damage-delta save)."""

import pytest

from sage_save import (
    apply_json,
    decode_game_logic,
    decode_object_prefix,
    iter_objects,
    object_veterancy_level,
    parse_save_from_path,
    save_to_dict,
    set_object_position,
    write_save,
)
from tests.sage_save.corpus import ALL_SAVES, FIXTURES, fixture_id

SESSION1 = FIXTURES / "session1"
# full → damaged → vet on one recruited DwarvenGuardian horde
UNIT_DELTAS = FIXTURES / "unit_deltas"


def _require(path):
    if not path.is_file():
        pytest.skip(f"fixture not present: {path.name}")
    return path


def _objects(path):
    try:
        return iter_objects(parse_save_from_path(_require(path)))
    except ValueError:
        pytest.skip(f"{path.name} has no live objects (between-missions stub)")


def test_moving_unit_changes_only_its_transform():
    before = {
        o.object_id: o for o in _objects(SESSION1 / "Saved Game 1 science spent.BfME2Skirmish")
    }
    after = {o.object_id: o for o in _objects(SESSION1 / "Saved Game 1 unit moving.BfME2Skirmish")}
    moved = []
    for object_id in set(before) & set(after):
        pos_a = decode_object_prefix(before[object_id]).position
        pos_b = decode_object_prefix(after[object_id]).position
        if pos_a != pos_b:
            moved.append(before[object_id].template_name)
    # units wander between saves (AI, creeps), but the transform decode sees real movement
    assert moved
    for object_id in set(before) & set(after):
        prefix = decode_object_prefix(after[object_id])
        assert prefix.version == 26


def test_export_includes_positions():
    save = parse_save_from_path(_require(SESSION1 / "Saved Game 1 money 4025.BfME2Skirmish"))
    data = save_to_dict(save)
    objects = data["game_logic"]["objects"]
    assert all(len(o["position"]) == 3 for o in objects)
    # positions are on-map magnitudes, not garbage float reinterpretations
    assert all(abs(c) < 1e6 for o in objects for c in o["position"])


def test_set_object_position_is_length_preserving_and_rewrites_only_translation():
    obj = _objects(SESSION1 / "Saved Game 1 money 4025.BfME2Skirmish")[0]
    before = decode_object_prefix(obj)
    moved = set_object_position(obj, (1234.5, -678.25, 42.0))
    assert len(moved.body) == len(obj.body)  # length-preserving (absolute-offset safe)
    after = decode_object_prefix(moved)
    assert after.position == (1234.5, -678.25, 42.0)
    # the rotation columns (every matrix slot but 3/7/11) are untouched
    for i in range(12):
        if i not in (3, 7, 11):
            assert after.matrix[i] == before.matrix[i]


def test_object_position_editable_through_apply_json():
    save = parse_save_from_path(_require(SESSION1 / "Saved Game 1 money 4025.BfME2Skirmish"))
    target = decode_game_logic(save.chunk("CHUNK_GameLogic")).objects[0]
    edit = {"object_id": target.object_id, "position": [10.0, 20.0, 30.0]}
    edited = apply_json(save, {"game_logic": {"objects": [edit]}})
    # the whole container round-trips at identical length, and the new position reads back
    assert len(write_save(edited)) == len(write_save(save))
    reobj = {o.object_id: o for o in decode_game_logic(edited.chunk("CHUNK_GameLogic")).objects}
    assert decode_object_prefix(reobj[target.object_id]).position == (10.0, 20.0, 30.0)
    # the original save is untouched
    orig = decode_game_logic(save.chunk("CHUNK_GameLogic")).objects[0]
    assert decode_object_prefix(orig).position != (10.0, 20.0, 30.0)


def _unit_delta_objects(tag):
    return {
        o.object_id: o for o in _objects(UNIT_DELTAS / f"Saved Game 3 unit {tag}.BfME2Skirmish")
    }


def test_veterancy_level_tracks_the_rank_up_delta():
    # The recruited unit is the DwarvenGuardianHorde (id 174) with its members; it is level 1
    # in the full/damaged saves and level 2 after ranking up in the vet save. Veterancy is read
    # from the applied `Upgrade_ObjectLevelN` mask, so it needs no offset walk.
    full = _unit_delta_objects("full")
    damaged = _unit_delta_objects("damaged")
    vet = _unit_delta_objects("vet")
    for oid in (174, 175):  # horde + one member
        assert object_veterancy_level(full[oid]) == 1
        assert object_veterancy_level(damaged[oid]) == 1
        assert object_veterancy_level(vet[oid]) == 2


def test_veterancy_zero_for_props_and_structures():
    # Objects that never gain a rank (rocks, farms, flags) carry no ObjectLevel upgrade → 0.
    objects = _unit_delta_objects("full")
    props = [o for o in objects.values() if o.template_name.startswith(("DarkRockGrey", "Farm"))]
    assert props and all(object_veterancy_level(o) == 0 for o in props)


def test_export_carries_veterancy():
    save = parse_save_from_path(_require(UNIT_DELTAS / "Saved Game 3 unit vet.BfME2Skirmish"))
    objects = {o["object_id"]: o for o in save_to_dict(save)["game_logic"]["objects"]}
    assert objects[174]["veterancy"] == 2


@pytest.mark.parametrize("path", ALL_SAVES, ids=fixture_id)
def test_object_prefix_decodes_corpus_wide(path):
    objects = _objects(path)
    for obj in objects:
        prefix = decode_object_prefix(obj)  # raises if either echo mismatches
        assert prefix.version == 26
        assert all(abs(value) < 1e7 for value in prefix.matrix)
