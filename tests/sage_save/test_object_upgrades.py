"""Step 6 — the fatal upgrade masks carried by live objects in CHUNK_GameLogic.

`harvest_object_upgrade_references` scans the object bodies for the same `version=1 + u16 count +
Upgrade_ names` mask signature the player harvest uses, adding the *applied* upgrades (veterancy,
hero abilities, structure/object levels) the per-player faction masks omit. The two classes the
plan reserved for Step 6 turned out not to apply to BFME saves: kind-of flags are non-fatal (an
unknown one is silently ignored per GPL `Xfer::xferKindOf`) and command-button names are never
serialized — so this upgrade source is the real Step-6 win, and these tests pin it down."""

from pathlib import Path

import pytest

from sage_save import (
    harvest_object_upgrade_references,
    harvest_player_references,
    harvest_references,
    parse_save_from_path,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"
SAVE3 = FIXTURES / "Saved Game 3.BfME2Skirmish"


def _save(path=SAVE3):
    if not path.is_file():
        pytest.skip(f"fixture not present: {path.name}")
    return parse_save_from_path(path)


def test_object_upgrades_are_fatal():
    refs = harvest_object_upgrade_references(_save())
    assert refs, "expected applied upgrade masks in a populated GameLogic"
    assert all(r.fatal and r.kind == "upgrade" for r in refs)
    assert all(r.name.startswith("Upgrade_") for r in refs)


def test_object_upgrades_add_names_beyond_players():
    save = _save()
    player_upgrades = {r.name for r in harvest_player_references(save) if r.kind == "upgrade"}
    object_upgrades = {r.name for r in harvest_object_upgrade_references(save)}
    new = object_upgrades - player_upgrades
    # the applied structure/object-level upgrades are not in the per-player faction masks
    assert "Upgrade_StructureLevel1" in new
    assert any(n.startswith("Upgrade_ObjectLevel") for n in new)


def test_merged_harvest_dedups_and_includes_object_upgrades():
    refs = harvest_references(_save())
    keys = [(r.kind, r.name) for r in refs]
    assert len(keys) == len(set(keys))  # no duplicate (kind, name) across chunks
    names = {r.name for r in refs if r.kind == "upgrade"}
    assert "Upgrade_StructureLevel1" in names  # object-body upgrade
    assert "Upgrade_ElfFaction" in names  # player upgrade — both present, merged


def test_no_command_button_class_is_serialized():
    # The plan's other Step-6 class: command-button names are not serialized by name anywhere,
    # so no chunk yields a Command_-style button reference (a tripwire on that negative finding).
    save = _save()
    names: set[str] = set()
    for chunk in save.chunks:
        payload = chunk.payload
        i = 0
        while i < len(payload):
            length = payload[i]
            if 3 <= length <= 48 and i + 1 + length <= len(payload):
                token = payload[i + 1 : i + 1 + length]
                if all(32 <= c < 127 for c in token):
                    names.add(token.decode())
                    i += 1 + length
                    continue
            i += 1
    # "Command_<Action>" button names simply do not appear (CommandPoints_Upgrade is an upgrade)
    assert not [n for n in names if n.startswith("Command_")]
