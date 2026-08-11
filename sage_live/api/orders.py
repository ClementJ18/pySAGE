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
| `recruit_hero` | gold charged, the named roster entry's hero appeared (twice, two factions) |
| `build_at` | gold charged, structure built on a castle plot |
| `research` | gold charged, upgrade applied |
| `cast_at_location` | five ways: a summon spawned at the commanded point, a nuke damaged a
  building, Rebuild repaired one, a spellbook summon fielded eagles and the army of the dead,
  and the Lone Tower raised a sentry tower - the last three **only** with `source_id` naming the
  spellbook, see below |
| `purchase_power` | a spellbook point was spent and the spell appeared |
| `cast_self` | a targetless grant raised the player's spellbook points |
| `cast_at_object` | Faramir's Wound Arrow fired on a lair and went to cooldown |
| `set_stance` | the hero visibly changed stance |
| `attack_move` | two battalions walked, closing on the target for eight seconds |
| `castle_unpack` | a lumber mill on a claimed settlement; a Gondor castle on a claimed castle |
| `unpack` | gold dropped 200 and a `GondorFarm_Extern` rose on a claimed settlement |

Seventeen have now made the engine act. `set_stance` was the one with no oracle readable from
memory - it costs nothing, creates nothing, and its field is not a plain dword on `Object` - so it
was confirmed by watching the game.

Seven of the first thirteen were wrong when this table was written, and **every one failed by
doing nothing at all** - accepted by `appendMessage`, recorded in the replay, discarded by logic.
Corpus shape agreement caught four of them; only running the game caught the rest.

**`unpack` was settled twice over on 2026-08-04**, RotWK 2.01 + Edain, Gondor on
`map mp argonath`, and the cheap half came first. A match *played entirely by hand* records
four `0x43F` orders - each a single `Integer`, exactly the shape this module emits - resolving
to `GondorFarm_Extern`, `GondorLeuchtfeuer`, `GondorRangerTents` and `MenFortressCitadel`, plus
one argument-less `0x43D`. Then the same order was **injected**: a battalion claimed settlement
248, `unpack(GondorFarm_Extern)` went in through the bridge, gold fell 4640 → 4440 and the farm
appeared on the flag's own coordinates within a second.

**Recording a human is the cheapest oracle for an order whose shape is in doubt.** It shows
what the interface itself sends, with nothing of ours in the loop, and it costs one match. Reach
for it before theorising about argument lists.

**A spellbook cast is cast *by* the spellbook, and `source_id=0` does nothing.** Settled in a
controlled match on 2026-08-05, Gondor with every power bought: Eagles, Army of the Dead and the
Lone Tower were each sent at open ground with `source_id=0` and **all three did nothing** - taken
by the stream, discarded by logic, no charge and no diagnostic. The identical orders naming the
player's `GondorSpellBook` object summoned all three eagles, raised the sentry tower, and hatched
the army of the dead immediately. A sweep over `options` (32, 544, 1048864) changed nothing while
the source stayed 0, which is what rules out the bitfield as the cause.

That is also the corpus agreeing rather than a new discovery: the source slot records 0, 550, 551
and 552 across recorded casts, and the non-zero values are spellbook objects. Reading them as
"probably the fortress or the hero" is what kept this hidden - the fix is one field.

**Not every power needs it, which is why it took a controlled match to see.** `SpellBookRebuild`
and Gondor's Assistance in Time of Need both acted with the source at 0; the powers that failed
were exactly the ones whose module is an `OCLSpecialPower` - the ones that put something on the
map. Pass the spellbook for all of them regardless: it is correct for every power measured, and
the failure it prevents is silent.

One correction to the advice this file used to give. It said to read a failure "as a likely bug
here rather than as a game rule" - and `castle_unpack` is the case where that was wrong. Four
argument shapes were tried against an *unclaimed* plot flag and every one was consumed and
discarded, which looked exactly like a broken constructor; the order was correct all along and
the flag simply has to be owned first. When a whole family of shapes fails identically, suspect
a precondition.

**A well-formed order is not a legitimate one.** These constructors reach the engine through
`appendMessage`, the same path a mouse click takes, and the engine does not ask where the order
came from - so an agent can issue actions the interface would never have offered it. The
authority on what is legitimate is the target's own `CommandSet`: if the selected object's
command set holds no button carrying that command, a human could not have issued it, and
sending it anyway is cheating rather than automation. `sage_live.utils.statics` reads command sets,
and the check belongs in the policy - nothing here enforces it, because nothing here can tell
an agent from a scripted convenience a human asked for.

**The `player` argument does not choose who acts.** It fills `Order.player_index`, which the
bridge does not transmit - the engine attributes an injected order to the local player itself
(see `bridge.encode_order`). It matters when an order is serialized to a replay, and for
`purchase_power`, whose *first argument* is a real chunk number the engine reads.
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


# The options field of a ground-targeted cast is never 0 in the recorded corpus: 32 in 119 of
# 165 orders, 544 in 42, 1048864 in 4. The bits are unidentified, so this is the empirical
# default rather than a derived one - if a power misbehaves, this is the field to vary first.
DEFAULT_CAST_OPTIONS = 32

# Which of the three cast constructors a power takes. Declared here, next to the constructors
# themselves, because this is the choice the module warns about: a power sent through the wrong
# one is accepted, charged nothing and does nothing, which reads exactly like a broken encoder.
#
# `sage_live.utils.statics` reads the answer off the firing `CommandButton`'s `Options` and hands
# it back as one of these, so nothing has to guess from what a spell sounds like. `CAST_PASSIVE`
# is the fourth answer and the only one that is not an order at all: the power fired when it was
# bought, and the control bar shows no button to press.
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
    what rises on it.

    Carries no arguments at all. The `CommandButton` behind it is `Command = CASTLE_UNPACK`
    with an *empty* `Object` field: the engine reads what to build off the target's own
    `CastleBehavior`, picking the `CastleToUnpackForFaction` row for the issuing player's
    faction. Naming a template here is the *other* order, `unpack`.

    **This is the narrower of the two, and the button census says so.** RotWK 2.01 + Edain
    defines **17** `CASTLE_UNPACK` buttons against **133** `CASTLE_UNPACK_EXPLICIT_OBJECT`
    ones. The three families that really take it are outposts, castles and camps - see
    `sage_live.utils.statics.PLOT_FAMILIES` for the templates, whose Edain names give nothing
    away. **A settlement is not one of them**, despite looking like the obvious case: its
    plain-claim button exists only while the flag is neutral, and claiming it swaps the palette
    to explicit buttons, so no player ever gets to click it.

    Pick by reading the target's own buttons, never by the kind of plot it looks like;
    `Statics.unpack_buttons` answers it directly.

    **Verified live twice.** 2026-07-31, Isengard: a detachment walked onto an unclaimed
    `WirtschaftPlotFlag_Real`, its `owner_index` flipped from the civilian player to ours, this
    order went in with no arguments, and an `IsengardLumberMill` rose on the flag. 2026-08-04,
    Gondor: the same on a **castle**, `FestungPlotFlagNW_Real` - claimed at 67 units, gold fell
    7568 → 2568, and a `GBCastleFloor` plus a `GondorCastleBaseKeep` rose on the plot.

    **A castle keeps this button through ownership; a settlement does not.** The castle's
    palette read `CastleFlagCommandSet` with the same lone `CASTLE_UNPACK` before *and* after
    the claim, where a settlement's swaps to explicit per-building buttons the instant it
    becomes yours. That contrast is the whole rule: outposts, castles and camps are the plain
    claim, settlements are `unpack`.

    **The plot must already be owned by the issuing player.** That precondition is a game rule
    rather than anything this can check, and an order that fails it is consumed and discarded in
    silence, exactly like a malformed one - against an *unclaimed* flag the order is discarded
    four different ways, every one of which looks precisely like a broken constructor.

    Ownership is taken by standing your own units next to the flag while no enemy is near it.
    The distances are **aims to move toward, not thresholds to test against**: three claims on
    2026-08-04 flipped at 67-78 units - two settlements and a castle - so a policy testing an
    exact radius refuses claims the game would have allowed. Read
    ownership itself from `GameObject.owner_index`, which is the engine's own answer and needs
    no threshold.

    **Ownership is a proximity state, not a property.** It reverts to the civilian player once
    your units leave, and an enemy can take it off you the same way - a claim held long enough
    to read is not a claim held long enough to build on if the order goes out in a later pass.
    Claim and unpack in the same breath.

    **A plot already in use cannot be claimed, and it is `owner_index` that says so.** A free
    plot is owned by the *civilian* player - a small positive index, `1` in these matches - and
    flips to yours on approach. A plot reading **`None`** is one an existing base already
    occupies: a battalion parked 43-64 units off such a castle for 90 seconds never moved it,
    and this order against it was consumed and discarded. `None` is not "unowned and free"; it
    is the state to skip.
    """
    return Order(player, OrderType.CASTLE_UNPACK, [])


def unpack(player: int, template_id: int) -> Order:
    """Build at the **currently selected plot**, naming what to build.

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

    **This is the common one - it is what a player's own clicks send.** Of the two unpack
    orders the engine has, `CASTLE_UNPACK_EXPLICIT_OBJECT` carries **133** of the 166 unpack
    buttons in RotWK 2.01 + Edain, and every one of them names an `Object`: the farm, the
    beacon, the tents, the citadel - each plot button inside a base you already own. A
    hand-played match recorded on 2026-08-04 emits four of these and one `castle_unpack`, which
    is the ratio the button census predicts.

    The argument shape is therefore settled by observation rather than inference: **one
    `Integer`, the created template**, which is what this emits.

    **Verified live by injection** (2026-08-04, RotWK 2.01 + Edain, Gondor): a battalion claimed
    a `WirtschaftPlotFlag_Real` settlement, whose palette swapped to Gondor's explicit buttons
    the moment `owner_index` flipped; this order went in through the bridge naming
    `GondorFarm_Extern`, the player's gold fell 4640 → 4440, and the farm rose on the flag's own
    coordinates. Same precondition as `castle_unpack`: the plot must be yours first.
    """
    return Order(player, OrderType.CASTLE_UNPACK_EXPLICIT_OBJECT, [_int(template_id)])


def attack_move(player: int, position: Vec3) -> Order:
    """Move to a point, engaging what is met on the way - the A-move a push is made of.

    Byte-identical in shape to `move`, and a different order type: the engine distinguishes
    them, and `move` walks units past enemies that are shooting at them.

    **Verified live** (2026-07-31, RotWK 2.01 + Edain): two `IsengardUrukScoutHorde_StartUnit`
    containers were selected and ordered to a point short of the enemy base. Both walked, and
    their distance to the target fell monotonically over eight seconds - 2444 to 2353 and 2464
    to 2389 - which is sustained pathing rather than the unit jostle a single sample would not
    have told apart. Selection-dependent, like `move`.

    That measured the *movement* half only. That it also **engages what it meets on the way**,
    which is the whole reason to prefer it to `move`, is confirmed by the game's own behaviour
    rather than by this package's instrumentation.

    Address the horde **containers**. An order issued to their members is recorded and then
    ignored, which reads exactly like a broken constructor.
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

    **This is the unit form. Heroes go through `recruit_hero` instead**, which is the same
    order with the leading flag set and a *revive index* in place of the template id. Feeding
    this function's argument to that form is what produced two heroes nobody asked for; the
    index space is identified in `sage_live.utils.heroes` and it is not the CommandSet's slot
    number.
    """
    return Order(
        player,
        OrderType.QUEUE_UNIT_CREATE,
        [_bool(False), _int(template_id), _int(-1), _bool(False), _bool(False)],
    )


def recruit_hero(player: int, revive_index: int) -> Order:
    """Recruit a hero at the selected building, by its position in the revive list.

    The same order as `recruit` with the leading flag **set**: that flag picks how the second
    argument is read, and set it means a revive index rather than a `thing_template_order` id.

    `revive_index` is a 0-based position in the player's `BuildableHeroesMP` list, which is
    **not** a `CommandSet` slot and **not** static - a fielded hero leaves the list and the
    ones behind it slide forward. `sage_live.utils.heroes` derives it and `Session.recruit_hero`
    tracks it across frames; the derivation, and the two live recruits that confirm the index
    space, are documented there.

    **Verified live** (RotWK 2.01 + Edain): index 7 at a `GondorBarracks` charged and produced
    `GondorImrahil`, which is `FactionMen`'s roster entry 7; index 1 at a
    `LothlorienCastleBaseKeep` produced `LothlorienRumil`, entry 1 of `FactionElves`.

    **The engine will not stop you recruiting a hero the interface never offered.** Its own
    gate, `BuildAssistant::canMakeUnit`, matches a REVIVE slot by counting and never reads the
    matched button's `NeededUpgrade` - the defect `sage_patch`'s `ai-revive-gate` patch fixes
    for the AI. So an order naming any index reachable in the producer's slot block is honoured,
    including the slots a human's control bar hides. The Imrahil recruit above was one: the
    barracks offers Beregond and Boromir and nothing else. `Session.recruit_hero` refuses that
    unless the session is running with `godsight`; this constructor does not, in keeping with
    every other one here.
    """
    return Order(
        player,
        OrderType.QUEUE_UNIT_CREATE,
        [_bool(True), _int(revive_index), _int(-1), _bool(False), _bool(False)],
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


def sell(player: int) -> Order:
    """Sell the **currently selected** structure back for part of what it cost.

    Argument-less and selection-driven, like `castle_unpack` and `start_self_repair`:
    `Command_Sell` is `Command = SELL` with no `Object` field, so the engine reads what is being
    sold off the selection and prices the refund itself.

    **What this buys is usually the plot, not the gold.** A base runs out of somewhere to build
    long before it runs out of money - a measured match finished holding 11,634 gold with every
    plot occupied - and the only way to put a marketplace up at that point is to take something
    else down.

    `MSG_SELL` is `0x41C` in the network range - see `sage_patch/docs/message-stream.md`.
    """
    return Order(player, OrderType.SELL, [])


def start_self_repair(player: int) -> Order:
    """Start the **currently selected** structure repairing itself, at the cost the engine sets.

    Argument-less and selection-driven, like `castle_unpack`: the `CommandButton` behind it is
    `Command_StartSelfRepair`, `Command = START_SELF_REPAIR`, carrying no `Object` and no cost -
    the price is the engine's, read off the structure. That is why nothing is passed here.

    **The case this exists for is a keep that has been destroyed rather than merely damaged.** A
    camp or castle keep does not leave the object table when it falls: it stands as rubble at
    zero health wearing the `RUBBLE` condition, and this is the order that brings it back. See
    `GameObject.is_rubble`, which is how a caller tells that state from a building worth healing.

    `MSG_START_SELF_REPAIR` is `0x45D` in the network range - see
    `sage_patch/docs/message-stream.md`.
    """
    return Order(player, OrderType.START_SELF_REPAIR, [])


def toggle_formation(player: int, horde_id: int) -> Order:
    """Switch one battalion between its two formations.

    `Command_ToggleFormationGondorFighter`, `Command = HORDE_TOGGLE_FORMATION`. The button
    carries no `Object` and no cost: which formation the battalion swaps to is declared on the
    horde itself, as `HordeContain.AlternateFormation`, so the order names only *which*
    battalion. See `sage_live.utils.statics.Formation`.

    **A toggle rather than a set.** `MSG_HORDE_SET_FORMATION` exists separately at `0x460` and
    every button in RotWK 2.01 + Edain that would send it is commented out, so there is no way
    to ask for a *named* formation - only to flip the one the battalion is in. A caller that
    wants a particular formation therefore has to read the battalion's current one and decide,
    which is why `Formation` exists and why sending this blind is how a battalion ends up in
    the formation you were trying to leave.

    The horde and not its members: the members are slaved and an order naming one is recorded
    and ignored, exactly as for every other order in this module.

    `MSG_HORDE_TOGGLE_FORMATION` is `0x453` in the network range, recovered from
    `GameMessage::getCommandTypeAsAsciiString` - see `sage_patch/docs/message-stream.md`. The
    recorded corpus gives it a single `ObjectId` argument, which is the shape here.

    **Unverified against a running game at the time of writing**, unlike the seventeen
    constructors in the table above. The id and the argument shape are both ground truth - one
    from the binary, one from the corpus - and neither says the engine will act, because a
    well-formed order it declines is consumed in silence. `Statics.alternate_formation` gives
    the oracle to check it with: a battalion that switched has members wearing the engine's
    `ALTERNATE_FORMATION` model condition, and one whose order was dropped does not.
    """
    return Order(player, OrderType.HORDE_TOGGLE_FORMATION, [_obj(horde_id)])


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
