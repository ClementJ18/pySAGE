"""The data-free parts of mission testing: the objectives tracker decode and the opening diff."""

from __future__ import annotations

import json
import struct
from pathlib import Path

import pytest

from sage_patch.addresses import (
    MAX_PLAYER_COUNT,
    MISSION_OBJECTIVE_LIST_OFFSET,
    MISSION_OBJECTIVE_TRACKER,
    PLAYER_DEFEAT_FRAME,
    PLAYER_INDEX,
    PLAYER_IS_DEFEATED,
    THE_VICTORY_CONDITIONS,
    VICTORY_CONDITIONS_IS_DEFEATED,
    VICTORY_CONDITIONS_PLAYERS,
)
from sage_test.mission import Defeat, Objective, read_defeats, read_objectives
from sage_test.mission_record import diff


class _Memory:
    def __init__(self) -> None:
        self.bytes: dict[int, int] = {}

    def write(self, address: int, data: bytes) -> None:
        for offset, byte in enumerate(data):
            self.bytes[address + offset] = byte

    def u32(self, address: int, value: int) -> None:
        self.write(address, struct.pack("<I", value))

    def read(self, address: int, size: int) -> bytes | None:
        try:
            return bytes(self.bytes[address + i] for i in range(size))
        except KeyError:
            return None


def test_objectives_decode_bonus_shown_and_ticked_per_slot():
    memory = _Memory()
    tracker, listed, entries = 0x2000_0000, 0x2000_1000, 0x2000_2000
    memory.u32(MISSION_OBJECTIVE_TRACKER, tracker)
    memory.u32(tracker + MISSION_OBJECTIVE_LIST_OFFSET, listed)
    memory.u32(listed + 4, entries)
    memory.u32(listed + 8, entries + 3 * 8)
    # {label pointer, bonus, shown, ticked, padding} per entry.
    memory.write(entries, struct.pack("<I4B", 0x1234, 0, 1, 1, 0))
    memory.write(entries + 8, struct.pack("<I4B", 0x1234, 0, 1, 0, 0))
    memory.write(entries + 16, struct.pack("<I4B", 0x1234, 1, 0, 0, 0))
    assert read_objectives(memory.read) == [
        Objective(1, bonus=False, shown=True, ticked=True),
        Objective(2, bonus=False, shown=True, ticked=False),
        Objective(3, bonus=True, shown=False, ticked=False),
    ]


def test_no_tracker_is_no_objectives():
    """At the menus, or in a skirmish map with no mission objectives at all."""
    assert read_objectives(_Memory().read) == []


def test_defeats_pair_each_tracked_player_with_its_latch():
    memory = _Memory()
    conditions, standing, beaten = 0x2100_0000, 0x2100_1000, 0x2100_2000
    memory.u32(THE_VICTORY_CONDITIONS, conditions)
    memory.write(
        conditions + VICTORY_CONDITIONS_IS_DEFEATED, bytes([0, 1] + [0] * (MAX_PLAYER_COUNT - 2))
    )
    for slot in range(MAX_PLAYER_COUNT):
        memory.u32(conditions + VICTORY_CONDITIONS_PLAYERS + 4 * slot, 0)
    memory.u32(conditions + VICTORY_CONDITIONS_PLAYERS, standing)
    memory.u32(conditions + VICTORY_CONDITIONS_PLAYERS + 4, beaten)
    for player, index, flag, frame in ((standing, 3, 0, 0), (beaten, 4, 1, 25)):
        memory.u32(player + PLAYER_INDEX, index)
        memory.write(player + PLAYER_IS_DEFEATED, bytes([flag]))
        memory.u32(player + PLAYER_DEFEAT_FRAME, frame)
    assert read_defeats(memory.read) == [
        Defeat(player=3, latched=False, flagged=False, frame=0),
        Defeat(player=4, latched=True, flagged=True, frame=25),
    ]


def _log(path: Path, *entries: dict) -> Path:
    path.write_text("".join(json.dumps(e) + "\n" for e in entries), encoding="utf-8")
    return path


def test_the_diff_reports_what_only_one_opening_did(tmp_path: Path, capsys: pytest.CaptureFixture):
    start = {
        "kind": "start",
        "frame": 1,
        "local": 2,
        "players": [],
        "fired_before_attach": [],
    }
    skirmish = _log(
        tmp_path / "skirmish.jsonl",
        start,
        {"kind": "fired", "frame": 3, "player": "Player_2", "script": "Intro"},
        {"kind": "gone", "frame": 25, "id": 7, "template": "MineShaft", "owner": 2},
    )
    campaign = _log(
        tmp_path / "campaign.jsonl",
        start,
        {"kind": "fired", "frame": 9, "player": "Player_2", "script": "Intro"},
    )
    diff(skirmish, campaign)
    printed = capsys.readouterr().out
    assert "scripts fired: only in skirmish.jsonl (0), only in campaign.jsonl (0)" in printed
    assert "< ('MineShaft', 2)" in printed
