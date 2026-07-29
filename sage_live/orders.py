"""Order constructors.

The action space is `sage_replay.Order` unchanged - this module adds constructors, not a
parallel model. That matters for more than tidiness: an order built here can be written by
`sage_replay.serialize`, so an emitted action round-trips through the same byte-exact writer
the replay corpus gates, and a session's output can be checked against a replay the engine
recorded of that same session.

Order type ids and names are the engine's own, recovered from
`GameMessage::getCommandTypeAsAsciiString` - see `sage_patch/docs/message-stream.md`. The
enum value *is* the order id; there is no offset.

These take resolved integer ids. Turning `"MordorFighterHorde"` into this build's id needs a
loaded game and lives in `resolve`, which is imported separately so this module stays
install-free.

**What has been proven against a running game** (2026-07-29, RotWK 2.01 + Edain). A malformed
order is accepted by `appendMessage`, reaches the replay, and is then silently discarded by
logic - so shape agreement with the corpus is necessary but not sufficient, and this table
records which constructors have actually made the engine *do* something:

| constructor | verified by |
|---|---|
| `select` | replay records the order; selection then obeyed a move |
| `move` | unit walked to the commanded point |
| `stop` | unit halted mid-path |
| `deselect` | a following `move` did nothing at all |
| `attack_object` | unit advanced 380 units, closing on the target |
| `recruit` | gold charged, unit appeared |
| `build_at` | gold charged, structure built on a castle plot |
| `research` | gold charged, upgrade applied |
| `cast_at_location` | three ways: a summon spawned at the commanded point, a nuke damaged a
  building, and Rebuild repaired one |
| `purchase_power` | a spellbook point was spent and the spell appeared |
| `cast_self` | a targetless grant raised the player's spellbook points |
| `cast_at_object` | Faramir's Wound Arrow fired on a lair and went to cooldown |
| `set_stance` | the hero visibly changed stance |

All thirteen have now made the engine act. `set_stance` was the one with no oracle readable from
memory - it costs nothing, creates nothing, and its field is not a plain dword on `Object` - so it
was confirmed by watching the game.

Seven of these thirteen were wrong when this table was first written, and **every one failed by
doing nothing at all** - accepted by `appendMessage`, recorded in the replay, discarded by logic.
Corpus shape agreement caught four of them; only running the game caught the rest.

**Two more are corpus-shaped but not yet live-verified**, and are marked as such on themselves:
`unpack` and `attack_move`. Given the record above - seven of thirteen wrong on first writing -
treat them as unproven until something in the game visibly changes, and read a failure as a
likely bug here rather than as a game rule.

**The `player` argument does not choose who acts.** It fills `Order.player_index`, which the
bridge does not transmit - the engine attributes an injected order to the local player itself
(see `bridge.encode_order`). It matters when an order is serialized to a replay, and for
`purchase_power`, whose *first argument* is a real chunk number the engine reads.
"""

from __future__ import annotations

from collections.abc import Sequence
from enum import IntEnum

from sage_live.observation import Vec3
from sage_replay.replay import Order, OrderArgument, OrderArgumentType

__all__ = [
    "DEFAULT_CAST_OPTIONS",
    "OrderType",
    "attack_move",
    "attack_object",
    "build_at",
    "cast_at_location",
    "cast_at_object",
    "cast_self",
    "deselect",
    "move",
    "purchase_power",
    "recruit",
    "research",
    "select",
    "set_stance",
    "stop",
    "unpack",
]


class OrderType(IntEnum):
    """The subset of `GameMessage::Type` these constructors emit.

    The full 147-name network range is documented in
    `sage_patch/docs/message-stream.md`; only what is constructed here is named, so this
    enum does not drift into a second, partial copy of that table.
    """

    CREATE_SELECTED_GROUP = 0x3E9
    DESTROY_SELECTED_GROUP = 0x3EC
    DO_SPECIAL_POWER = 0x410
    DO_SPECIAL_POWER_AT_LOCATION = 0x411
    DO_SPECIAL_POWER_AT_OBJECT = 0x412
    PURCHASE_SCIENCE = 0x414
    QUEUE_UPGRADE = 0x415
    QUEUE_UNIT_CREATE = 0x417
    FOUNDATION_CONSTRUCT = 0x419
    DOZER_CONSTRUCT = 0x41A
    DO_ATTACK_OBJECT = 0x425
    DO_MOVETO = 0x42F
    DO_ATTACKMOVETO = 0x430
    DO_STOP = 0x435
    CASTLE_UNPACK_EXPLICIT_OBJECT = 0x43F
    CHANGE_STANCE = 0x468


# The options field of a ground-targeted cast is never 0 in the recorded corpus: 32 in 119 of
# 165 orders, 544 in 42, 1048864 in 4. The bits are unidentified, so this is the empirical
# default rather than a derived one - if a power misbehaves, this is the field to vary first.
DEFAULT_CAST_OPTIONS = 32


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


def unpack(player: int, template_id: int) -> Order:
    """Build at the **currently selected plot**, with no placement interface.

    The other build path. `build_at` drives the placement UI and therefore carries a world
    position; this one names only what to create and takes its location from the selected
    object, which is how a fixed castle plot, a settlement extern and an outpost claim are all
    built. A target carrying a `CastleBehavior` unpacks the base its `CastleToUnpackForFaction`
    row names for the issuing player's faction.

    `template_id` is the **created** template, in the same `thing_template_order` space as
    `recruit` and `build_at` - the earlier "+2" reading was an artifact of resolving against
    Edain's `_mod` overlay tree, whose table is shifted one low, rather than against a faithful
    live-install mount. On the install mount the standard rule resolves 2136/2166 (98.6%) of
    the corpus's orders of this type; under +2 it manages 47%. Resolve against the install.

    **Not yet live-verified.** Shape and id rule come from the corpus
    (`order_space_map.md` section A, `0x43F`); no order built here has yet been watched to
    create a building. If it does nothing, suspect this before suspecting the game.
    """
    return Order(player, OrderType.CASTLE_UNPACK_EXPLICIT_OBJECT, [_int(template_id)])


def attack_move(player: int, position: Vec3) -> Order:
    """Move to a point, engaging what is met on the way - the A-move a push is made of.

    Byte-identical in shape to `move`, and a different order type: the engine distinguishes
    them, and `move` walks units past enemies that are shooting at them.

    **Not yet live-verified.** `0x430` `MSG_DO_ATTACKMOVETO` is ground truth from the binary's
    own name table, and the single-Position signature matches `move`, but nothing has yet been
    watched to engage on the way. Selection-dependent, like `move`.
    """
    return Order(player, OrderType.DO_ATTACKMOVETO, [_pos(position)])


def recruit(player: int, template_id: int) -> Order:
    """Queue a unit at the selected production building.

    Five arguments, not two. The engine records `[flag, id, -1, False, False]` on every
    `QUEUE_UNIT_CREATE` (822/822 in the corpus agree on the trailing three), and a short order
    is **appended to the stream and then silently discarded by logic** - it costs nothing and
    produces nothing, which is a miserable thing to debug. The leading flag picks how the
    second argument is read: False for a `thing_template_order` id, True for a command-slot
    index (that is the form an outpost unpack uses).

    **Use the template-id form. The command-slot index is not the CommandSet file's slot
    number.** Tested twice, and both times it produced something else entirely: slot 1 of
    `LothlorienCastleBaseKeepCommandSet`, whose file entry 1 is
    `Command_ConstructElvenLorienWarriorHorde`, recruited the hero Orophin; slot 7 of
    `GondorBarracksCommandSet`, whose file entry 7 is the structure-upgrade button, recruited
    the hero Imrahil. Both orders were accepted and charged - so this form is not broken, it is
    indexed against something we have not identified (visible-button order, or a runtime
    rebuild of the set). Until that is worked out, a file-derived index buys the wrong thing at
    full price.
    """
    return Order(
        player,
        OrderType.QUEUE_UNIT_CREATE,
        [_bool(False), _int(template_id), _int(-1), _bool(False), _bool(False)],
    )


def research(player: int, upgrade_id: int, building_id: int) -> Order:
    """Purchase an upgrade at a specific building.

    **`building_id` must name the building; 0 does not mean "the current selection".** Verified
    live: with a `GondorBarracks` selected and the one upgrade its command set offers, an order
    carrying 0 was consumed by the bridge and then discarded by logic - nothing charged, nothing
    researched. The identical order naming the building's own object id charged immediately. So
    this argument has no default, because the plausible default is the broken value.

    The corpus does contain recorded orders with 0 here, so 0 must mean *something* in some
    other context (a player-wide purchase, most likely). That context is not identified, and
    guessing it is what produced the bug.
    """
    return Order(player, OrderType.QUEUE_UPGRADE, [_obj(building_id), _int(upgrade_id)])


def purchase_power(player: int, science_id: int) -> Order:
    """Buy a spellbook power.

    The first argument identifies the issuing player, and **it is the index this package uses
    everywhere else** - the in-memory `PlayerList` index that `Observation.local_player` gives
    you - so it is passed through unchanged.

    This used to send `player + 1`, reading the corpus note that arg0 is the player's "chunk
    number" as an offset to apply. It is not: verified live, `player + 1` was consumed and
    discarded while the identical order carrying `player` spent a point immediately. The
    corpus note is still right, because a replay's player index runs one *below* the in-memory
    index on this build - so chunk number and `PlayerList` index are the same number, and the
    +1 was double-counting a conversion that had already happened.
    """
    return Order(player, OrderType.PURCHASE_SCIENCE, [_int(player), _int(science_id)])


def cast_self(player: int, power_id: int, options: int = 0, source_id: int = 0) -> Order:
    """Cast a power that takes no target.

    **Pick the cast form from the power's own definition, not from what the spell sounds
    like.** A power sent through the wrong one of these three constructors is accepted,
    charged nothing, and does nothing - the same silent discard as a malformed order, and it
    reads exactly like a broken constructor. The `SpecialPower` block in the ini says which:

    | `Enum` / cursor in the ini | constructor |
    |---|---|
    | `SPECIAL_GENERAL_TARGETLESS`, `..._TWO` | `cast_self` |
    | a radius cursor, `NEED_TARGET_POS`, `InitiateAtLocationSound` | `cast_at_location` |
    | `NEED_TARGET_OBJECT` | `cast_at_object` |

    Gondor's Rebuild is the cautionary case: it repairs a *building*, so an object target is
    the obvious guess, and three attempts through `cast_at_object` did nothing. It carries a
    radius cursor - `cast_at_location` at the building's position repaired it instantly.

    The trailing argument is 0 in all 142 recorded casts; its meaning is unidentified.
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
    """Ground-targeted cast. `target_id` is 0 for a plain ground target."""
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

    **There is deliberately no `source_id`.** The fourth argument is 0 in all 24 recorded
    casts, and putting the caster's object id there stops the order working: Faramir's Wound
    Arrow, with its button ready and a valid target under the cursor, did nothing when the
    order named him as the source, and fired - visibly, and onto its cooldown - when that slot
    was zeroed. The engine takes the caster from the selection, not from the order.

    This is worth stating plainly because `cast_at_location`'s equivalent slot *does* carry a
    caster (the corpus records 0, 550, 551 and 552 there), and generalising from that one to
    this one is what produced the bug.
    """
    return Order(
        player,
        OrderType.DO_SPECIAL_POWER_AT_OBJECT,
        [_int(power_id), _obj(target_id), _int(options), _obj(0), _pos(position)],
    )


def set_stance(player: int, stance: int) -> Order:
    """Change the selected unit's stance.

    Stance applies per unit and comes from the `SET_STANCE` buttons, which name three stances -
    `Battle`, `Aggressive`, `HoldGround` - without ever stating the integer the order carries.
    The engine's enum order is not in the ini, so the numbering here is empirical:
    **3 = Aggressive**, confirmed visually on a hero. `2` is the corpus's dominant value (192
    recorded orders) and is most likely `Battle`, the default, but that is inference.

    Verified by watching the game rather than by memory: the stance field is not a plain dword
    in the first 0x400 bytes of `Object`, so a differential scan only turned up per-frame
    animation churn. It presumably lives on a behaviour module a pointer away.
    """
    return Order(player, OrderType.CHANGE_STANCE, [_int(stance)])
