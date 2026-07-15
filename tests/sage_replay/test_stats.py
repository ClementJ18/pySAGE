"""Per-player stats: KindOf bucketing (with ChildObject inheritance), counting, and the
science purchase order. Synthetic GameData and chunks - no game install needed."""

from datetime import UTC, datetime

from sage_replay.narrate import GameData
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
from sage_replay.stats import _bucket, _effective_kindof, compute_stats

_T = OrderArgumentType


class _obj:
    """Stand-in for a loaded Object: `_fields` plus an optional ChildObject-style parent."""

    def __init__(self, fields: dict, parent=None) -> None:
        self._fields = fields
        if parent is not None:
            self.parent = parent


_BARRACKS = _obj({"KindOf": "STRUCTURE SELECTABLE"})
_HORDE = _obj({"KindOf": "HORDE SELECTABLE CAN_CAST_REFLECTIONS"})
_HERO = _obj({"KindOf": "HERO SELECTABLE"})
_CP = _obj({"KindOf": "PRELOAD"})  # a CPObject-like purchase: no SELECTABLE
# a ChildObject with no own KindOf inherits the parent's; one with modifiers adjusts it.
_CHILD_PLAIN = _obj({}, parent=_HERO)
_CHILD_MOD = _obj({"KindOf": "+STRUCTURE -HERO"}, parent=_HERO)


def _data() -> GameData:
    return GameData(
        object_order=["Barracks", "OrcHorde", "Boromir", "CPObject", "ChildHero", "ModChild"],
        objects={
            "Barracks": _BARRACKS,
            "OrcHorde": _HORDE,
            "Boromir": _HERO,
            "CPObject": _CP,
            "ChildHero": _CHILD_PLAIN,
            "ModChild": _CHILD_MOD,
        },
        specialpowers=[],
        sciences=["SCIENCE_One", "SCIENCE_Two"],
        upgrades=["DefaultUpgrade", "Upgrade_ForgedBlades"],
        displaynames={},
        # Only Boromir is a buildable MP hero; ChildHero carries the HERO KindOf but is not on
        # any roster, so it buckets as a unit (a summoned/hero-like unit, not a recruit).
        hero_rosters=[["Boromir"]],
    )


def test_effective_kindof_climbs_and_applies_modifiers():
    objects = _data().objects
    assert _effective_kindof(objects, "Boromir") == {"HERO", "SELECTABLE"}
    assert _effective_kindof(objects, "ChildHero") == {"HERO", "SELECTABLE"}  # inherited
    # modifier tokens adjust the inherited set instead of replacing it.
    assert _effective_kindof(objects, "ModChild") == {"STRUCTURE", "SELECTABLE"}
    assert _effective_kindof(objects, None) == frozenset()
    assert _effective_kindof(objects, "Unknown") == frozenset()


def test_bucket_rules():
    # Only a buildable-MP hero counts as a hero (the second arg), whatever the KindOf.
    assert _bucket(frozenset({"HERO", "SELECTABLE"}), True) == "heroes"
    # The same HERO KindOf, but not a buildable hero, is a unit - a summoned/hero-like unit.
    assert _bucket(frozenset({"HERO", "SELECTABLE"}), False) == "units"
    assert _bucket(frozenset({"HERO"}), False) == "units"  # even without SELECTABLE
    assert _bucket(frozenset({"STRUCTURE", "SELECTABLE"}), False) == "buildings"
    assert _bucket(frozenset({"HORDE", "SELECTABLE"}), False) == "units"
    assert _bucket(frozenset({"PRELOAD"}), False) == "other"  # CPObject-style purchase
    assert _bucket(frozenset(), False) == "other"


def _chunk(order_type: int, args: list, *, timecode: int = 0, number: int = 3) -> ReplayChunk:
    order = Order(player_index=number - 3, order_type=order_type)
    order.arguments = [OrderArgument(t, v) for t, v in args]
    return ReplayChunk(timecode=timecode, order_type=order_type, number=number, order=order)


def _replay(chunks: list[ReplayChunk]) -> ReplayFile:
    slots = [ReplaySlot(slot_type=ReplaySlotType.Human, human_name=f"Player{i}") for i in range(2)]
    header = ReplayHeader(
        game_type=ReplayGameType.Bfme2,
        start_time=datetime(2026, 1, 1, tzinfo=UTC),
        end_time=datetime(2026, 1, 1, 0, 1, tzinfo=UTC),
        num_timecodes=60,  # 1 frame per second
        filename="",
        timestamp=ReplayTimestamp(*([0] * 8)),
        version="",
        build_date="",
        metadata=ReplayMetadata(slots=slots),
    )
    return ReplayFile(header=header, chunks=chunks)


def test_compute_stats_buckets_and_orders():
    def recruit_of(object_id: int, number: int = 3) -> ReplayChunk:
        args = [(_T.Boolean, False), (_T.Integer, object_id), (_T.Integer, 0)]
        return _chunk(0x417, args, number=number)

    replay = _replay(
        [
            _chunk(0x419, [(_T.Integer, 1), (_T.Position, (1.0, 2.0, 3.0))]),  # builds Barracks
            _chunk(0x41A, [(_T.Integer, 1)]),  # builder-constructs Barracks
            _chunk(0x463, [(_T.Integer, 1)]),  # wall segment, counted with buildings
            _chunk(0x43F, [(_T.Integer, 1)]),  # plot unpack: standard +1 id, so 1 -> Barracks
            recruit_of(2),  # OrcHorde -> units
            recruit_of(2),
            recruit_of(3),  # Boromir (on the MP roster) -> heroes
            recruit_of(5),  # ChildHero (inherited HERO, not on any roster) -> units
            recruit_of(4),  # CPObject-like -> other
            _chunk(0x417, [(_T.Boolean, True), (_T.Integer, 2), (_T.Integer, 0)]),  # slot hero
            _chunk(0x414, [(_T.Integer, 3), (_T.Integer, 2)], timecode=9),  # SCIENCE_Two
            _chunk(0x414, [(_T.Integer, 3), (_T.Integer, 1)], timecode=30),  # SCIENCE_One
            # upgrade id = 0-based `upgrades` index + 3, so 4 -> Upgrade_ForgedBlades
            _chunk(0x415, [(_T.Integer, 4)], timecode=20),
            _chunk(0x415, [(_T.Integer, 99)], timecode=21),  # out of range
            recruit_of(2, number=4),  # Player1's lone recruit
        ]
    )
    stats = {per.player: per for per in compute_stats(replay, _data())}

    p0 = stats["Player0"]
    assert p0.buildings == {"Barracks": 4}
    assert p0.units == {"OrcHorde": 2, "ChildHero": 1}
    assert p0.heroes == {"Boromir": 1}
    assert p0.other == {"CPObject": 1}
    assert p0.upgrades == {"Upgrade_ForgedBlades": 1, "<upgrade id 99?>": 1}
    assert p0.fortress_hero_slots == {2: 1}
    # sciences keep purchase order (id is the SECOND integer), clocked at 1 frame/second.
    assert [(int(s), name) for s, name in p0.sciences] == [
        (9, "SCIENCE_Two"),
        (30, "SCIENCE_One"),
    ]

    assert stats["Player1"].units == {"OrcHorde": 1}
    assert not stats["Player1"].buildings


def test_compute_stats_names_castle_bases():
    # A plot-unpack whose target carries a CastleBehavior is labelled with the base the
    # issuing player's faction Side unpacks (CastleToUnpackForFaction).
    data = _data()
    data.castle_bases["Barracks"] = {"rohan": "rohan_outpost"}
    data.faction_sides = ["Rohan"]
    replay = _replay([_chunk(0x43F, [(_T.Integer, 1)])])
    replay.header.metadata.players[0].faction = 0
    stats = {per.player: per for per in compute_stats(replay, data)}
    assert stats["Player0"].buildings == {"Barracks (unpacks rohan_outpost)": 1}


def _recruit(object_id: int, number: int = 3) -> ReplayChunk:
    return _chunk(
        0x417, [(_T.Boolean, False), (_T.Integer, object_id), (_T.Integer, 0)], number=number
    )


def _fortress_recruit(slot: int, number: int = 3) -> ReplayChunk:
    return _chunk(0x417, [(_T.Boolean, True), (_T.Integer, slot), (_T.Integer, 0)], number=number)


def _cancel_unit(template_id: int, number: int = 3) -> ReplayChunk:
    args = [(_T.Boolean, False), (_T.Integer, template_id), (_T.Boolean, False)]
    return _chunk(0x418, args, number=number)


def _research(upgrade_id: int, number: int = 3) -> ReplayChunk:
    return _chunk(0x415, [(_T.Integer, upgrade_id)], number=number)


def _cancel_upgrade(upgrade_id: int, number: int = 3) -> ReplayChunk:
    return _chunk(0x416, [(_T.Integer, upgrade_id)], number=number)


def _cancel_build(number: int = 3) -> ReplayChunk:
    return _chunk(0x41B, [], number=number)


def test_unit_cancel_is_id_matched_and_lifo():
    # CPObject is recruited first, OrcHorde second, but the cancel names CPObject's template
    # id, so it removes CPObject even though OrcHorde is the more-recent recruit.
    replay = _replay([_recruit(4), _recruit(2), _cancel_unit(4)])
    p0 = {per.player: per for per in compute_stats(replay, _data())}["Player0"]
    assert p0.other == {}
    assert p0.units == {"OrcHorde": 1}


def test_unit_cancel_nets_repeated_recruits():
    replay = _replay([_recruit(2), _recruit(2), _recruit(2), _cancel_unit(2), _cancel_unit(2)])
    p0 = {per.player: per for per in compute_stats(replay, _data())}["Player0"]
    assert p0.units == {"OrcHorde": 1}


def test_unmatched_unit_cancel_is_ignored():
    # (a) a cancel with nothing queued at all.
    replay = _replay([_cancel_unit(2)])
    p0 = {per.player: per for per in compute_stats(replay, _data())}["Player0"]
    assert p0.units == {}

    # (b) a cancel naming a different template id than the queued recruit.
    replay = _replay([_recruit(2), _cancel_unit(3)])
    p0 = {per.player: per for per in compute_stats(replay, _data())}["Player0"]
    assert p0.units == {"OrcHorde": 1}


def test_fortress_hero_recruits_are_not_cancellable():
    replay = _replay([_fortress_recruit(2), _cancel_unit(2)])
    p0 = {per.player: per for per in compute_stats(replay, _data())}["Player0"]
    assert p0.fortress_hero_slots == {2: 1}
    assert p0.units == {}
    assert p0.other == {}


def test_upgrade_cancel_is_id_matched():
    # Two researches of the same upgrade id, one cancel: nets to one.
    replay = _replay([_research(4), _research(4), _cancel_upgrade(4)])
    p0 = {per.player: per for per in compute_stats(replay, _data())}["Player0"]
    assert p0.upgrades == {"Upgrade_ForgedBlades": 1}

    # A cancel naming a different upgrade id leaves the queued research intact.
    replay = _replay([_research(4), _cancel_upgrade(3)])
    p0 = {per.player: per for per in compute_stats(replay, _data())}["Player0"]
    assert p0.upgrades == {"Upgrade_ForgedBlades": 1}


def test_build_cancel_is_id_less_lifo():
    build_chunks = [
        _chunk(0x419, [(_T.Integer, 1), (_T.Position, (1.0, 2.0, 3.0))]),  # builds Barracks
        _chunk(0x41A, [(_T.Integer, 1)]),  # builder-constructs Barracks
    ]
    replay = _replay([*build_chunks, _cancel_build()])
    p0 = {per.player: per for per in compute_stats(replay, _data())}["Player0"]
    assert p0.buildings == {"Barracks": 1}

    replay = _replay([*build_chunks, _cancel_build(), _cancel_build()])
    p0 = {per.player: per for per in compute_stats(replay, _data())}["Player0"]
    assert p0.buildings == {}

    # A third cancel with nothing left on the stack is ignored, not an error.
    replay = _replay([*build_chunks, _cancel_build(), _cancel_build(), _cancel_build()])
    p0 = {per.player: per for per in compute_stats(replay, _data())}["Player0"]
    assert p0.buildings == {}


def test_cancels_are_scoped_to_the_issuing_player():
    replay = _replay([_recruit(2), _cancel_unit(2, number=4)])
    stats = {per.player: per for per in compute_stats(replay, _data())}
    assert stats["Player0"].units == {"OrcHorde": 1}


def _power_data() -> GameData:
    """A GameData with a small special-power table and two faction Sides (for the caster-Side
    relabel path). Power replay id = 1-based index into `specialpowers`."""
    data = _data()
    data.specialpowers = ["SpecialAbilityOne", "SpecialAbilityShared"]
    data.faction_sides = ["Imladris", "Angmar"]
    return data


def _cast(power_id: int, order_type: int = 0x410, number: int = 3, options: int = 0) -> ReplayChunk:
    # A cast layout: [powerId, options, ...] - the power id is the first Integer, the firing
    # CommandButton's Options bitfield the second.
    return _chunk(order_type, [(_T.Integer, power_id), (_T.Integer, options)], number=number)


def test_power_casts_land_in_the_powers_bucket():
    # Every cast order type (self / at-location / at-object / global) counts, by raw code name;
    # an out-of-range id is marked rather than dropped.
    replay = _replay([_cast(1, 0x410), _cast(2, 0x412), _cast(2, 0x456), _cast(99, 0x411)])
    p0 = {per.player: per for per in compute_stats(replay, _power_data())}["Player0"]
    assert p0.powers == {"SpecialAbilityShared": 2, "SpecialAbilityOne": 1, "<power id 99?>": 1}


def test_relabel_power_sees_the_casters_side():
    # The hook renames the shared power per caster Side; Player0 is Imladris, Player1 Angmar.
    def relabel(side, power):
        return f"{side}:{power}" if power == "SpecialAbilityShared" else power

    replay = _replay([_cast(2, 0x410, number=3), _cast(2, 0x410, number=4)])
    replay.header.metadata.players[0].faction = 0  # Side "Imladris"
    replay.header.metadata.players[1].faction = 1  # Side "Angmar"
    stats = {per.player: per for per in compute_stats(replay, _power_data(), relabel_power=relabel)}
    assert stats["Player0"].powers == {"Imladris:SpecialAbilityShared": 1}
    assert stats["Player1"].powers == {"Angmar:SpecialAbilityShared": 1}


def test_power_recruits_injects_unit_events():
    # A power that fields permanent units (returned with multiplicity via duplicate names)
    # records them as ordinary bucketed events, alongside the untouched `powers` count.
    calls = []

    def recruits(side, roster, power, options):
        calls.append((side, tuple(roster), power, options))
        return ["OrcHorde", "OrcHorde"] if power == "SpecialAbilityOne" else ()

    replay = _replay([_cast(1, 0x410, number=3)])
    replay.header.metadata.players[0].faction = 0  # Side "Imladris"
    stats = {
        per.player: per for per in compute_stats(replay, _power_data(), power_recruits=recruits)
    }
    p0 = stats["Player0"]
    assert p0.powers == {"SpecialAbilityOne": 1}
    assert p0.units == {"OrcHorde": 2}
    # The hook sees the caster's Side, their faction's (per-map) hero roster, and the cast's
    # CommandButton Options bitfield too.
    assert calls == [("Imladris", ("Boromir",), "SpecialAbilityOne", 0)]


def test_power_recruits_sees_the_firing_buttons_options_bitfield():
    # Two buttons can share one power definition on the same Side (Angmar's SiegeTroll ram vs
    # ThrallMaster orc summon); the cast's second Integer is the firing button's Options
    # bitfield, so the hook can field a different unit per button.
    def recruits(side, roster, power, options):
        return ["Barracks"] if options & 0x100 else ["OrcHorde"]

    replay = _replay([_cast(1, options=0x1000100), _cast(1, options=0)])
    p0 = {per.player: per for per in compute_stats(replay, _power_data(), power_recruits=recruits)}[
        "Player0"
    ]
    assert p0.buildings == {"Barracks": 1}
    assert p0.units == {"OrcHorde": 1}


def test_power_recruits_sees_the_raw_power_name_even_when_relabelled():
    # `relabel_power` may rewrite the stored label, but the hook keys on the raw code name so
    # it survives relabelling.
    seen = []

    def recruits(side, roster, power, options):
        seen.append(power)
        return ()

    def relabel(side, power):
        return "Renamed"

    replay = _replay([_cast(1, 0x410, number=3)])
    replay.header.metadata.players[0].faction = 0
    stats = {
        per.player: per
        for per in compute_stats(
            replay, _power_data(), relabel_power=relabel, power_recruits=recruits
        )
    }
    assert stats["Player0"].powers == {"Renamed": 1}
    assert seen == ["SpecialAbilityOne"]


def test_power_recruit_events_are_not_cancellable():
    # A power cast cannot be cancelled, so the injected events never sit on the `recruits`
    # LIFO stack: an unrelated 0x418 unit-cancel for the same template id must not consume one.
    def recruits(side, roster, power, options):
        return ["OrcHorde"]

    replay = _replay([_cast(1, 0x410, number=3), _cancel_unit(2)])
    p0 = {per.player: per for per in compute_stats(replay, _power_data(), power_recruits=recruits)}[
        "Player0"
    ]
    assert p0.units == {"OrcHorde": 1}


def test_no_power_recruits_hook_or_empty_result_leaves_units_untouched():
    replay = _replay([_cast(1, 0x410, number=3)])
    p0 = {per.player: per for per in compute_stats(replay, _power_data())}["Player0"]
    assert p0.units == {}
    assert p0.powers == {"SpecialAbilityOne": 1}

    def empty(side, roster, power, options):
        return ()

    p0 = {per.player: per for per in compute_stats(replay, _power_data(), power_recruits=empty)}[
        "Player0"
    ]
    assert p0.units == {}
    assert p0.powers == {"SpecialAbilityOne": 1}


def test_upgrade_recruits_injects_units_for_dedication_researches():
    # A dedication research converts its buyer engine-side (the summon never enters the order
    # stream), so the hook's units record as ordinary recruits alongside the untouched
    # `upgrades` count; the hook sees the purchaser's Side.
    calls = []

    def dedications(side, upgrade):
        calls.append((side, upgrade))
        return ["OrcHorde"] if upgrade == "Upgrade_ForgedBlades" else ()

    replay = _replay([_research(4)])
    replay.header.metadata.players[0].faction = 1  # Side "Angmar"
    p0 = {
        per.player: per
        for per in compute_stats(replay, _power_data(), upgrade_recruits=dedications)
    }["Player0"]
    assert p0.upgrades == {"Upgrade_ForgedBlades": 1}
    assert p0.units == {"OrcHorde": 1}
    assert calls == [("Angmar", "Upgrade_ForgedBlades")]


def test_cancelled_dedication_takes_its_fielded_unit_back():
    # A 0x416 upgrade cancel pops the research and the recruit events it injected - the
    # cancelled conversion never happens.
    def dedications(side, upgrade):
        return ["OrcHorde"]

    replay = _replay([_research(4), _cancel_upgrade(4)])
    p0 = {
        per.player: per
        for per in compute_stats(replay, _power_data(), upgrade_recruits=dedications)
    }["Player0"]
    assert p0.upgrades == {}
    assert p0.units == {}


def test_dedication_cancel_only_takes_back_its_own_injected_events():
    # The cancel removes exactly the events its research injected: an ordinary recruit of the
    # same template (an equal-valued StatEvent) survives, ...
    def dedications(side, upgrade):
        return ["OrcHorde"]

    replay = _replay([_recruit(2), _research(4), _cancel_upgrade(4)])
    p0 = {
        per.player: per
        for per in compute_stats(replay, _power_data(), upgrade_recruits=dedications)
    }["Player0"]
    assert p0.units == {"OrcHorde": 1}
    assert p0.upgrades == {}

    # ... and the injected event never sits on the 0x418 unit-cancel stack either.
    replay = _replay([_research(4), _cancel_unit(2)])
    p0 = {
        per.player: per
        for per in compute_stats(replay, _power_data(), upgrade_recruits=dedications)
    }["Player0"]
    assert p0.units == {"OrcHorde": 1}
    assert p0.upgrades == {"Upgrade_ForgedBlades": 1}


def test_ignore_recruits_drops_named_templates():
    # A template in `ignore_recruits` (by raw code name) never records as a recruit; the others
    # in the same stream are untouched.
    replay = _replay([_recruit(2), _recruit(2), _recruit(4)])  # OrcHorde x2, CPObject
    p0 = {
        per.player: per
        for per in compute_stats(replay, _data(), ignore_recruits=frozenset({"OrcHorde"}))
    }["Player0"]
    assert p0.units == {}
    assert p0.other == {"CPObject": 1}


def test_ignored_recruit_is_not_left_on_the_cancel_stack():
    # An ignored recruit was never recorded, so a later 0x418 unit-cancel for its id finds
    # nothing to pop and must not disturb the recruit that is the genuine most-recent match.
    replay = _replay([_recruit(2), _recruit(4), _cancel_unit(2)])  # OrcHorde ignored, CPObject kept
    p0 = {
        per.player: per
        for per in compute_stats(replay, _data(), ignore_recruits=frozenset({"OrcHorde"}))
    }["Player0"]
    assert p0.units == {}
    assert p0.other == {"CPObject": 1}


def test_combine_hordes_are_counted():
    # 0x423 (Edain horde-merge) carries only a runtime ObjectId, so each is counted as one
    # action under a constant label; the count is what matters, not the (runtime) target.
    replay = _replay(
        [_chunk(0x423, [(_T.ObjectId, 237)]), _chunk(0x423, [(_T.ObjectId, 240)], number=4)]
    )
    stats = {per.player: per for per in compute_stats(replay, _data())}
    assert stats["Player0"].combines == {"horde combine": 1}
    assert stats["Player1"].combines == {"horde combine": 1}


def test_interleaved_buy_cancel_rebuy_nets_correctly():
    # Mirrors the real CPObject bug: buy two, cancel both, buy two more - should net to two,
    # not accumulate stale cancelled entries.
    replay = _replay(
        [_recruit(4), _recruit(4), _cancel_unit(4), _cancel_unit(4), _recruit(4), _recruit(4)]
    )
    p0 = {per.player: per for per in compute_stats(replay, _data())}["Player0"]
    assert p0.other == {"CPObject": 2}
