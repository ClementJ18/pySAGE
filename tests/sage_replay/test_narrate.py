"""English narration of the order stream: id resolution, order phrasing, and event collapsing.

These build a synthetic `GameData` and synthetic orders so nothing here needs a game install;
`test_corpus.py` / the `narrate` CLI exercise the resolution against real trees.
"""

from datetime import UTC, datetime

from sage_replay.narrate import GameData, _describe, _target_phrase, narrate
from sage_replay.replay import (
    Order,
    OrderArgument,
    OrderArgumentType,
    ReplayChunk,
    ReplayFile,
    ReplayGameType,
    ReplayHeader,
    ReplayMetadata,
    ReplaySlot,
    ReplaySlotType,
    ReplayTimestamp,
)

_T = OrderArgumentType


def _data(**overrides) -> GameData:
    base = {
        # id = index + 1: id 1 -> Alpha, id 2 -> Bravo, ...
        "object_order": ["Alpha", "Bravo", "Charlie"],
        "objects": {"Bravo": _obj({"Side": "Mordor"})},
        "specialpowers": ["PowerOne", "SpecialAbilityBladeOfPurity"],
        "sciences": ["SciZero", "SciOne", "SCIENCE_EyeofSauron"],
        # upgrade replay id = 0-based index + 3: id 3 -> index 0 -> Upgrade_ForgedBlades
        "upgrades": ["Upgrade_ForgedBlades", "Upgrade_FireArrows"],
        # only Bravo and the forged-blades upgrade have a localized name; everything else
        # (Alpha/Charlie, the power, the science) falls back to its raw code name.
        "displaynames": {"Bravo": "Orc Warriors", "Upgrade_ForgedBlades": "Forged Blades"},
        # Alpha is a pre-placed castle you unpack; Charlie is raised from a foundation plot.
        # Bravo has no build button (recruited unit); a wall/expansion template is simply absent.
        "build_commands": {
            "Alpha": frozenset({"CASTLE_UNPACK"}),
            "Charlie": frozenset({"FOUNDATION_CONSTRUCT"}),
        },
    }
    base.update(overrides)
    return GameData(**base)


class _obj:
    """Minimal stand-in for a loaded Object: just the `_fields` dict the narrator reads."""

    def __init__(self, fields: dict) -> None:
        self._fields = fields


def _chunk(order_type: int, args: list[tuple[OrderArgumentType, object]], *, number: int = 3):
    order = Order(player_index=number - 3, order_type=order_type)
    order.arguments = [OrderArgument(t, v) for t, v in args]
    return ReplayChunk(timecode=0, order_type=order_type, number=number, order=order)


# --- id resolution --------------------------------------------------------------------


def test_object_id_is_index_plus_one():
    data = _data()
    assert data.object_name(1) == "Alpha"
    assert data.object_name(3) == "Charlie"
    assert data.object_name(4) is None  # out of range


def test_object_label_prefers_localized_name_else_code_name():
    data = _data()
    assert data.object_label(2) == "Orc Warriors"  # localized DisplayName
    assert data.object_label(1) == "Alpha"  # no localized name -> raw code name
    assert data.object_label(99) == "<object id 99?>"


def test_label_uses_code_name_when_no_localized_string():
    data = _data()
    # a power/science with no DisplayName is shown verbatim, not prettified.
    assert data.label("SpecialAbilityBladeOfPurity") == "SpecialAbilityBladeOfPurity"
    assert data.label("SCIENCE_EyeofSauron") == "SCIENCE_EyeofSauron"
    # an upgrade that does have one is localized.
    assert data.label("Upgrade_ForgedBlades") == "Forged Blades"
    assert data.label(None) is None


def test_special_power_and_science_and_upgrade_offsets():
    data = _data()
    assert data.special_power(2) == "SpecialAbilityBladeOfPurity"
    assert data.science(3) == "SCIENCE_EyeofSauron"
    # replay upgrade id = 0-based table index + 3 (survey-calibrated; the old 1-based reading
    # was one high - the FireArrows/ForgedBlades anchor pair matches as a set under both).
    assert data.upgrade(3) == "Upgrade_ForgedBlades"
    assert data.upgrade(4) == "Upgrade_FireArrows"
    assert data.upgrade(2) is None  # below the offset floor
    assert data.upgrade(5) is None  # past the table end


# --- power targeting from the Options bitfield -----------------------------------------


def test_target_phrase_shows_raw_location_and_target():
    # NEED_TARGET_POS (32) -> the raw ground Position (rounded).
    assert _target_phrase(0x411, 0x20, (1083.4, 1005.9, 300.0), None) == " at (1083, 1006, 300)"
    # NEED_TARGET_ENEMY_OBJECT (1) / +NEUTRAL (2) -> raw target id, tagged enemy.
    assert _target_phrase(0x412, 0x1, None, 861) == " on enemy object #861"
    assert _target_phrase(0x412, 0x3, None, 861) == " on enemy object #861"
    # NEED_TARGET_ALLY_OBJECT (4) -> friendly (Edain mind-control).
    assert _target_phrase(0x412, 0x4, None, 866) == " on friendly object #866"
    # all three allegiance bits (7) -> any object, no allegiance word.
    assert _target_phrase(0x412, 0x7, None, 900) == " on object #900"
    # self / global casts carry no target.
    assert _target_phrase(0x410, 0x0, None, None) == ""
    assert _target_phrase(0x456, 0x0, None, None) == ""


# --- per-order phrasing ---------------------------------------------------------------


def test_describe_recruit_build_power_science_upgrade():
    data = _data()
    # recruit: 0x417 flag=False, id in the first Integer.
    recruit = _chunk(0x417, [(_T.Boolean, False), (_T.Integer, 2), (_T.Integer, 0)])
    assert _describe(recruit, data) == "recruits Orc Warriors"
    # hero mode: flag=True -> the integer is a command slot, not a template.
    hero = _chunk(0x417, [(_T.Boolean, True), (_T.Integer, 1), (_T.Integer, 0)])
    assert _describe(hero, data) == "recruits a fortress hero (command slot 1)"
    # build
    assert _describe(_chunk(0x41A, [(_T.Integer, 3)]), data) == "builds Charlie"
    # special power at a location - no localized name, so the raw code name is used verbatim.
    power = _chunk(0x411, [(_T.Integer, 2), (_T.Integer, 0x20), (_T.Position, (12.6, 34.2, 5.0))])
    assert _describe(power, data) == "uses SpecialAbilityBladeOfPurity at (13, 34, 5)"
    # special power on an enemy object (powerId, target ObjectId first, options=enemy)
    on_obj = _chunk(0x412, [(_T.Integer, 2), (_T.ObjectId, 55), (_T.Integer, 0x1)])
    assert _describe(on_obj, data) == "uses SpecialAbilityBladeOfPurity on enemy object #55"
    # spellbook purchase reads the SECOND integer; no localized name -> raw code name.
    science = _chunk(0x414, [(_T.Integer, 4), (_T.Integer, 3)])
    assert _describe(science, data) == "acquires the spellbook power SCIENCE_EyeofSauron"
    # upgrade research - this one has a localized DisplayName.
    upgrade = _chunk(0x415, [(_T.ObjectId, 100), (_T.Integer, 3)])
    assert _describe(upgrade, data) == "researches Forged Blades"


def test_describe_placement_build_and_unpack():
    data = _data()
    # 0x419 foundation build: Charlie is a foundation template, so "builds", and the placement
    # Position prints as ` at (x, y)` (z is dropped).
    foundation = _chunk(0x419, [(_T.Integer, 3), (_T.Position, (512.7, 780.2, 90.0))])
    assert _describe(foundation, data) == "builds Charlie at (513, 780)"
    # 0x419 unpack: Alpha is a castle-unpack template, so "unpacks".
    unpack = _chunk(0x419, [(_T.Integer, 1), (_T.Position, (100.4, 200.6, 5.0))])
    assert _describe(unpack, data) == "unpacks Alpha at (100, 201)"
    # 0x41A mobile-builder construct with a Position uses the same path and appends the location.
    dozer = _chunk(0x41A, [(_T.Integer, 3), (_T.Position, (12.9, 34.1, 5.0))])
    assert _describe(dozer, data) == "builds Charlie at (13, 34)"
    # 0x41A without a Position omits the clause (unchanged from the recruit/build suite).
    assert _describe(_chunk(0x41A, [(_T.Integer, 3)]), data) == "builds Charlie"
    # a template with no build_commands entry (Bravo, a recruited unit) still narrates as "builds".
    unmatched = _chunk(0x419, [(_T.Integer, 2), (_T.Position, (1.0, 2.0, 3.0))])
    assert _describe(unmatched, data) == "builds Orc Warriors at (1, 2)"


def test_describe_plot_unpack_uses_standard_ids():
    data = _data()
    # 0x43F unpack/build at a selected plot: standard +1 ids, same space as 0x419 (the
    # earlier +2 reading was a resolving-table artifact). Alpha (id 1) is unpack-only ->
    # "unpacks"; the order never carries a Position, so there is no placement clause.
    assert _describe(_chunk(0x43F, [(_T.Integer, 1)]), data) == "unpacks Alpha"
    # a template with a non-unpack build button narrates as "builds" (id 3 -> Charlie).
    assert _describe(_chunk(0x43F, [(_T.Integer, 3)]), data) == "builds Charlie"
    # out of range -> the marker shows the raw order id.
    assert _describe(_chunk(0x43F, [(_T.Integer, 99)]), data) == "builds <object id 99?>"


def test_describe_names_the_castle_base_for_the_players_side():
    data = _data()
    data.castle_bases["Alpha"] = {"imladris": "dunedain_outpost", "men": "gondor_outpost"}
    # The issuing player's Side picks the CastleToUnpackForFaction row.
    plot = _chunk(0x43F, [(_T.Integer, 1)])
    assert _describe(plot, data, "Imladris") == "unpacks Alpha - unpacks the dunedain_outpost base"
    assert _describe(plot, data, "Men") == "unpacks Alpha - unpacks the gondor_outpost base"
    # An unknown side, or a template without a castle table, adds nothing.
    assert _describe(plot, data, "Mordor") == "unpacks Alpha"
    assert _describe(plot, data, None) == "unpacks Alpha"
    assert _describe(_chunk(0x43F, [(_T.Integer, 3)]), data, "Imladris") == "builds Charlie"
    # The 0x419 placement path names the base the same way (a fortress unpack).
    placed = _chunk(0x419, [(_T.Integer, 1), (_T.Position, (100.4, 200.6, 5.0))])
    assert (
        _describe(placed, data, "Imladris")
        == "unpacks Alpha at (100, 201) - unpacks the dunedain_outpost base"
    )


def test_describe_wall_segment():
    data = _data()
    # 0x463 carries the template then two endpoint Positions; each prints 2-D int-rounded.
    wall = _chunk(
        0x463,
        [
            (_T.Integer, 3),
            (_T.Position, (100.4, 200.6, 5.0)),
            (_T.Position, (300.9, 250.1, 5.0)),
        ],
    )
    assert _describe(wall, data) == "builds a wall segment: Charlie from (100, 201) to (301, 250)"
    # missing endpoints omit the from/to clause.
    bare = _chunk(0x463, [(_T.Integer, 3)])
    assert _describe(bare, data) == "builds a wall segment: Charlie"


def test_describe_combine_hordes():
    data = _data()
    # 0x423 carries only a runtime ObjectId (the target/primary horde); it is narrated from
    # that handle since there is no static id to resolve.
    combine = _chunk(0x423, [(_T.ObjectId, 237)])
    assert _describe(combine, data) == "combines hordes into object #237"
    # a missing/zero target still names the action.
    assert _describe(_chunk(0x423, [(_T.ObjectId, 0)]), data) == "combines hordes"


def test_describe_skips_control_orders():
    # a pure selection/move order carries no static id and is not narrated.
    assert _describe(_chunk(0x42F, [(_T.Position, (1, 2, 3))]), data=_data()) is None
    assert _describe(_chunk(0x424, [(_T.ScreenRectangle, (0, 0, 1, 1))]), data=_data()) is None


# --- whole-stream narration -----------------------------------------------------------


def _replay(chunks: list[ReplayChunk]) -> ReplayFile:
    slots = [ReplaySlot(slot_type=ReplaySlotType.Human, human_name=f"Player{i}") for i in range(2)]
    metadata = ReplayMetadata(slots=slots)
    header = ReplayHeader(
        game_type=ReplayGameType.Bfme2,
        start_time=datetime(2026, 1, 1, tzinfo=UTC),
        end_time=datetime(2026, 1, 1, 0, 1, tzinfo=UTC),  # 60s span
        num_timecodes=60,  # -> 1 frame per second
        filename="",
        timestamp=ReplayTimestamp(*([0] * 8)),
        version="",
        build_date="",
        metadata=metadata,
    )
    return ReplayFile(header=header, chunks=chunks)


def test_narrate_collapses_consecutive_identical_actions():
    def recruit_at(tc: int, obj_id: int, number: int) -> ReplayChunk:
        args = [(_T.Boolean, False), (_T.Integer, obj_id), (_T.Integer, 0)]
        chunk = _chunk(0x417, args, number=number)
        chunk.timecode = tc
        return chunk

    replay = _replay(
        [
            recruit_at(30, 2, 3),  # Player0 recruits Orc Warriors
            recruit_at(31, 2, 3),  # ... again -> collapses into the previous event
            recruit_at(32, 2, 4),  # Player1 recruits Orc Warriors -> distinct player, new event
            recruit_at(40, 3, 3),  # Player0 recruits Charlie -> distinct text, new event
        ]
    )
    events = narrate(replay, _data())
    assert [(e.player, e.text, e.count) for e in events] == [
        ("Player0", "recruits Orc Warriors", 2),
        ("Player1", "recruits Orc Warriors", 1),
        ("Player0", "recruits Charlie", 1),
    ]
    # timing: 1 frame/second, so timecode 30 -> 0:30.
    assert events[0].clock == "0:30"
    assert events[2].clock == "0:40"
