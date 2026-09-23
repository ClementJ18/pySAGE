"""Order constructors: build `sage_replay.Order`s for a live session to send.

The action space is `sage_replay.Order` itself, so anything built here can be written by
`sage_replay.serialize` and compared against the replay the engine recorded. Order type ids are the
engine's own (see `sage_patch/docs/message-stream.md`).

These take resolved integer ids; `sage_live.utils.resolve` turns names into ids. A malformed order
is silently discarded by the engine, so each constructor is only trusted once verified in a running
game - see "Verified orders" in `docs/live-api.md`.
"""

from __future__ import annotations

from collections.abc import Sequence
from enum import IntEnum

from sage_live.api.observation import Vec3
from sage_replay.replay import Order, OrderArgument, OrderArgumentType

__all__ = [
    "CAST_LOCATION",
    "CAST_OBJECT",
    "CAST_PASSIVE",
    "CAST_SELF",
    "DEFAULT_CAST_OPTIONS",
    "OrderType",
    "attack_move",
    "attack_object",
    "build_at",
    "cast_at_location",
    "cast_at_object",
    "cast_self",
    "castle_unpack",
    "deselect",
    "move",
    "purchase_power",
    "recruit",
    "recruit_hero",
    "research",
    "select",
    "set_stance",
    "stop",
    "toggle_formation",
    "unpack",
]


class OrderType(IntEnum):
    """The `GameMessage::Type` ids these constructors emit (the full list is in
    `sage_patch/docs/message-stream.md`)."""

    CREATE_SELECTED_GROUP = 0x3E9
    DESTROY_SELECTED_GROUP = 0x3EC
    DO_SPECIAL_POWER = 0x410
    DO_SPECIAL_POWER_AT_LOCATION = 0x411
    DO_SPECIAL_POWER_AT_OBJECT = 0x412
    PURCHASE_SCIENCE = 0x414
    QUEUE_UPGRADE = 0x415
    QUEUE_UNIT_CREATE = 0x417
    SELL = 0x41C
    FOUNDATION_CONSTRUCT = 0x419
    DOZER_CONSTRUCT = 0x41A
    DO_ATTACK_OBJECT = 0x425
    DO_MOVETO = 0x42F
    DO_ATTACKMOVETO = 0x430
    DO_STOP = 0x435
    CASTLE_UNPACK = 0x43D
    HORDE_TOGGLE_FORMATION = 0x453
    CASTLE_UNPACK_EXPLICIT_OBJECT = 0x43F
    START_SELF_REPAIR = 0x45D
    CHANGE_STANCE = 0x468


# The most common options value on recorded ground casts (119 of 165); the bits are unknown.
DEFAULT_CAST_OPTIONS = 32

# Which cast constructor a power takes, as `sage_live.utils.statics` reads it off the firing
# `CommandButton`. `CAST_PASSIVE` is not an order: the power fired when it was bought.
CAST_LOCATION = "location"
CAST_OBJECT = "object"
CAST_SELF = "self"
CAST_PASSIVE = "passive"


def _int(v: int) -> OrderArgument:
    return OrderArgument(OrderArgumentType.Integer, v)


def _bool(v: bool) -> OrderArgument:
    return OrderArgument(OrderArgumentType.Boolean, v)


def _obj(v: int) -> OrderArgument:
    return OrderArgument(OrderArgumentType.ObjectId, v)


def _pos(v: Vec3) -> OrderArgument:
    return OrderArgument(OrderArgumentType.Position, v)


def _float(v: float) -> OrderArgument:
    return OrderArgument(OrderArgumentType.Float, v)


def select(player: int, object_ids: Sequence[int], additive: bool = False) -> Order:
    """Select objects. `additive=False` replaces the selection, which is the common case.

    An empty list is select-none, which the engine treats as a real order rather than a
    no-op.
    """
    args = [_bool(not additive)] + [_obj(i) for i in object_ids]
    return Order(player, OrderType.CREATE_SELECTED_GROUP, args)


def deselect(player: int) -> Order:
    return Order(player, OrderType.DESTROY_SELECTED_GROUP, [_bool(True)])


def move(player: int, position: Vec3) -> Order:
    return Order(player, OrderType.DO_MOVETO, [_pos(position)])


def stop(player: int) -> Order:
    return Order(player, OrderType.DO_STOP, [])


def attack_object(player: int, target_id: int, position: Vec3) -> Order:
    """Attack a specific object. `position` is where the target is - the engine records one
    on every attack order (966/966 in the corpus), so it is required rather than defaulted."""
    return Order(player, OrderType.DO_ATTACK_OBJECT, [_obj(target_id), _pos(position)])


def build_at(player: int, template_id: int, position: Vec3, angle: float = 0.0) -> Order:
    """Place a structure through the placement UI (`MSG_FOUNDATION_CONSTRUCT`).

    This is the placement-interface build. A build ordered to an already-selected mobile
    builder is `DOZER_CONSTRUCT` instead, which is a different id with the same arguments.
    """
    return Order(
        player, OrderType.FOUNDATION_CONSTRUCT, [_int(template_id), _pos(position), _float(angle)]
    )


def castle_unpack(player: int) -> Order:
    """Claim the **currently selected** outpost, castle or camp, letting the engine choose
    what rises on it from the target's `CastleBehavior`.

    Carries no arguments. Settlements are not claimed this way: once owned, their palette offers
    explicit per-building buttons, which are `unpack`. Pick by reading the target's own buttons
    (`Statics.unpack_buttons`), never by the kind of plot it looks like.

    **The plot must already belong to the issuing player**, or the order is silently discarded.
    Ownership comes from standing your units near the flag with no enemy close (claims flipped
    at 67-78 units), and it reverts when they leave, so claim and unpack together. Read it from
    `GameObject.owner_index`: the civilian player's index means free, `None` means another base
    already occupies the plot and it cannot be claimed.
    """
    return Order(player, OrderType.CASTLE_UNPACK, [])


def unpack(player: int, template_id: int) -> Order:
    """Build at the **currently selected plot**, naming what to build.

    Unlike `build_at`, there is no position: the location is the selected object. This is what a
    player's own plot buttons send - the farm, the beacon, the citadel inside a base they own.
    `template_id` is the **created** template, in the `thing_template_order` space `recruit` and
    `build_at` use; resolve it against the install's own archives, not a mod's `_mod` overlay tree.

    Same precondition as `castle_unpack`: the plot must be yours first.
    """
    return Order(player, OrderType.CASTLE_UNPACK_EXPLICIT_OBJECT, [_int(template_id)])


def attack_move(player: int, position: Vec3) -> Order:
    """Move to a point, engaging what is met on the way.

    Same arguments as `move` but a different order: `move` walks past enemies that are shooting
    at it. Address horde **containers**; an order to their members is recorded and ignored.
    """
    return Order(player, OrderType.DO_ATTACKMOVETO, [_pos(position)])


def recruit(player: int, template_id: int) -> Order:
    """Queue a unit at the selected production building.

    The engine records five arguments, `[flag, id, -1, False, False]`, and silently discards a
    shorter order. The leading flag says how the id is read: False for a `thing_template_order`
    id (this function), True for a revive index (`recruit_hero`).
    """
    return Order(
        player,
        OrderType.QUEUE_UNIT_CREATE,
        [_bool(False), _int(template_id), _int(-1), _bool(False), _bool(False)],
    )


def recruit_hero(player: int, revive_index: int) -> Order:
    """Recruit a hero at the selected building, by its position in the revive list.

    The same order as `recruit` with the leading flag set. `revive_index` is a 0-based position
    in the player's `BuildableHeroesMP` list - **not** a `CommandSet` slot, and not static: a
    fielded hero leaves the list and the ones behind it move up. `sage_live.utils.heroes` derives
    it and `Session.recruit_hero` tracks it across frames.

    The engine does not check that the interface offered the hero, so any reachable index is
    honoured. `Session.recruit_hero` refuses that unless the session runs with `godsight`; this
    constructor does not check.
    """
    return Order(
        player,
        OrderType.QUEUE_UNIT_CREATE,
        [_bool(True), _int(revive_index), _int(-1), _bool(False), _bool(False)],
    )


def research(player: int, upgrade_id: int, building_id: int) -> Order:
    """Purchase an upgrade at a specific building.

    `building_id` must name the building. 0 does not mean "the current selection": that order is
    discarded without charging anything, so there is no default.
    """
    return Order(player, OrderType.QUEUE_UPGRADE, [_obj(building_id), _int(upgrade_id)])


def purchase_power(player: int, science_id: int) -> Order:
    """Buy a spellbook power.

    The first argument is the issuing player's in-memory `PlayerList` index - the same index
    `Observation.local_player` gives - passed through unchanged. `player + 1` is discarded.
    """
    return Order(player, OrderType.PURCHASE_SCIENCE, [_int(player), _int(science_id)])


def cast_self(player: int, power_id: int, options: int = 0, source_id: int = 0) -> Order:
    """Cast a power that takes no target.

    **Pick the cast form from the power's definition, not from what it sounds like.** A power
    sent through the wrong constructor is silently discarded. The `SpecialPower` block says which:

    | `Enum` / cursor in the ini | constructor |
    |---|---|
    | `SPECIAL_GENERAL_TARGETLESS`, `..._TWO` | `cast_self` |
    | a radius cursor, `NEED_TARGET_POS`, `InitiateAtLocationSound` | `cast_at_location` |
    | `NEED_TARGET_OBJECT` | `cast_at_object` |

    The trailing argument is 0 in all 142 recorded casts; its meaning is unknown.
    """
    return Order(
        player,
        OrderType.DO_SPECIAL_POWER,
        [_int(power_id), _int(options), _obj(source_id), _obj(0)],
    )


def cast_at_location(
    player: int,
    power_id: int,
    position: Vec3,
    options: int = DEFAULT_CAST_OPTIONS,
    source_id: int = 0,
) -> Order:
    """Ground-targeted cast.

    Pass the player's spellbook object as `source_id`: powers that place something on the map do
    nothing without it, and every other power works with it.
    """
    return Order(
        player,
        OrderType.DO_SPECIAL_POWER_AT_LOCATION,
        [_int(power_id), _pos(position), _obj(0), _int(options), _obj(source_id)],
    )


def cast_at_object(
    player: int,
    power_id: int,
    target_id: int,
    position: Vec3,
    options: int = 1,
) -> Order:
    """Object-targeted cast. Carries the target's position as well as its id.

    There is deliberately no `source_id`: the engine takes the caster from the selection, and
    naming the caster in that slot stops the order working.
    """
    return Order(
        player,
        OrderType.DO_SPECIAL_POWER_AT_OBJECT,
        [_int(power_id), _obj(target_id), _int(options), _obj(0), _pos(position)],
    )


def sell(player: int) -> Order:
    """Sell the **currently selected** structure for part of its cost.

    Argument-less; the engine prices the refund. Mostly useful for freeing a plot: a base runs
    out of plots long before it runs out of gold.
    """
    return Order(player, OrderType.SELL, [])


def start_self_repair(player: int) -> Order:
    """Start the **currently selected** structure repairing itself, at the engine's price.

    Argument-less. The main use is a destroyed camp or castle keep, which stays on the map as
    rubble at zero health (`GameObject.is_rubble`) until repaired.
    """
    return Order(player, OrderType.START_SELF_REPAIR, [])


def toggle_formation(player: int, horde_id: int) -> Order:
    """Switch one battalion between its two formations.

    A toggle, not a set: no button sends the engine's set-formation order, so a caller that
    wants a particular formation reads the current one (`sage_live.utils.statics.Formation`) and
    decides. Name the horde, not its members.
    """
    return Order(player, OrderType.HORDE_TOGGLE_FORMATION, [_obj(horde_id)])


def set_stance(player: int, stance: int) -> Order:
    """Change the selected unit's stance.

    The ini never states the integers, so they are empirical: **3 = Aggressive** (seen on a
    hero). 2 is the corpus's most common value and is probably `Battle`, the default.
    """
    return Order(player, OrderType.CHANGE_STANCE, [_int(stance)])
