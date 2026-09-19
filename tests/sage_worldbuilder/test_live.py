"""The editor's view of a running game's scripts: map matching and the per-script live status."""

from __future__ import annotations

import struct
from typing import Any, cast

from sage_live.backends.scripts import LiveScript, LiveScriptGroup, ScriptTree, SideScripts
from sage_map.map import Map
from sage_patch.addresses import (
    GAME_INFO_MAP,
    TERRAIN_LOGIC_MAP_PATH,
    THE_GAME_INFO,
    THE_SKIRMISH_GAME_INFO,
    THE_TERRAIN_LOGIC,
)
from sage_worldbuilder.document import MapDocument
from sage_worldbuilder.live import (
    LiveIndex,
    LiveSession,
    LiveSnapshot,
    LiveStatus,
    document_keys,
    map_key,
)
from tests.sage_live.fake_process import FakeProcess


def script(name: str, **overrides: object) -> LiveScript:
    fields: dict[str, object] = {
        "name": name,
        "address": 0x1000,
        "active": True,
        "authored_active": True,
        "one_shot": False,
        "subroutine": False,
        "easy": True,
        "normal": True,
        "hard": True,
        "delay_seconds": 0,
        "sequential": False,
        "next_frame": 0,
    }
    fields.update(overrides)
    return LiveScript(**fields)  # type: ignore[arg-type]


def snapshot() -> LiveSnapshot:
    group = LiveScriptGroup(
        name="Waves",
        address=0x2000,
        active=False,
        subroutine=False,
        scripts=(script("Wave", delay_seconds=2, next_frame=110),),
        groups=(),
    )
    sides = (
        SideScripts(index=0, scripts=(), groups=()),
        SideScripts(
            index=1,
            scripts=(script("Intro", one_shot=True, active=False), script("Shared")),
            groups=(group,),
        ),
        SideScripts(index=2, scripts=(script("Shared", active=False),), groups=()),
    )
    return LiveSnapshot(
        map_path="c:\\users\\me\\maps\\my map\\my map.map",
        frame=100,
        logic_rate=5,
        tree=ScriptTree(sides=sides, difficulty=1),
        variables=(),
        players={0: "", 1: "Player_1", 2: "Player_2"},
    )


def test_map_keys_agree_between_the_game_and_the_editor() -> None:
    assert map_key("c:\\users\\me\\maps\\My Map\\My Map.map") == "my map"
    assert map_key("maps/map mp westfold") == "map mp westfold"
    document = MapDocument(Map(), path="C:/maps/My Map/My Map.map")
    assert map_key(snapshot().map_path) in document_keys(document)


def ascii_string(game: FakeProcess, holder: int, text: str) -> None:
    block = game.alloc(0x100)
    game.write(block, struct.pack("<IH", 1, len(text)) + bytes(2) + text.encode("latin-1"))
    game.u32(holder, block)


def test_the_map_path_comes_from_the_terrain_logic_first() -> None:
    """A `-file` start leaves both game-info globals null in the match; the loaded map is still
    named by the terrain logic."""
    game = FakeProcess()
    session = LiveSession(cast(Any, game), cast(Any, None), 0)
    for global_ in (THE_GAME_INFO, THE_SKIRMISH_GAME_INFO, THE_TERRAIN_LOGIC):
        game.u32(global_, 0)
    assert session.map_path() == ""

    info = game.alloc(0x100)
    game.u32(THE_SKIRMISH_GAME_INFO, info)
    ascii_string(game, info + GAME_INFO_MAP, "maps/map mp westfold")
    assert session.map_path() == "maps/map mp westfold"

    terrain = game.alloc(0x100)
    game.u32(THE_TERRAIN_LOGIC, terrain)
    ascii_string(game, terrain + TERRAIN_LOGIC_MAP_PATH, "maps\\my map\\my map.map")
    assert map_key(session.map_path()) == "my map"


def test_a_map_without_a_file_matches_the_copy_jump_to_game_makes() -> None:
    document = MapDocument(Map(), name='Fords: "of" Isen')
    assert "fords_ _of_ isen" in document_keys(document)


def test_a_fired_one_shot() -> None:
    state = LiveIndex(snapshot()).script("Player_1", "intro", authored_active=True)
    assert state is not None
    assert state.status is LiveStatus.FIRED and state.player == "Player_1"


def test_the_owning_player_wins_over_other_copies() -> None:
    index = LiveIndex(snapshot())
    mine = index.script("Player_2", "Shared", authored_active=True)
    assert mine is not None and mine.side == 2 and mine.status is LiveStatus.INACTIVE
    assert mine.changed and mine.copies == 2
    anyone = index.script("PlyrCreeps", "Shared", authored_active=True)
    assert anyone is not None and anyone.side == 1


def test_groups_and_missing_scripts() -> None:
    index = LiveIndex(snapshot())
    group = index.group("Player_1", "Waves", authored_active=True)
    assert group is not None and group.status is LiveStatus.INACTIVE and group.changed
    assert index.script("Player_1", "Nowhere", authored_active=True) is None


def test_describe_counts_down_to_the_next_evaluation() -> None:
    state = LiveIndex(snapshot()).script("Player_1", "Wave", authored_active=True)
    assert state is not None
    assert state.describe(frame=100, rate=5) == "active - evaluates again in 2.0 s on Player_1"
