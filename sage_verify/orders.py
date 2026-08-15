"""Which orders name a target, and how to read that target out of a replay chunk.

The ids and names here are the engine's own, recovered from `getCommandTypeAsAsciiString` and
tabulated in `sage_patch/docs/message-stream.md` section 3. They are kept as raw integers rather
than taken from `sage_replay.Bfme2OrderType`, which deliberately carries only the subset whose
*meaning* was confirmed from replay evidence - most of the orders that matter here (attack,
capture, enter) are named by the binary but absent from that enum.

**Only orders whose target is a thing in the world are listed.** An order that names no target,
or whose target is always the issuer's own property (rally points, unit queues, formation
toggles), says nothing about what its issuer could see and is not evidence either way.
"""

from __future__ import annotations

from dataclasses import dataclass

from sage_replay.replay import OrderArgumentType, ReplayChunk

__all__ = [
    "OBJECT_TARGETED",
    "POSITION_TARGETED",
    "OrderTarget",
    "order_name",
    "target_of",
]

#: Orders that name a target **object**. Clicking one requires it to be on screen, which is what
#: makes these the near-conclusive cases: the engine will not accept an ObjectId the issuing
#: client never drew.
OBJECT_TARGETED: dict[int, str] = {
    0x40F: "MSG_DO_WEAPON_AT_OBJECT",
    0x412: "MSG_DO_SPECIAL_POWER_AT_OBJECT",
    0x422: "MSG_COMBATDROP_AT_OBJECT",
    0x425: "MSG_DO_ATTACK_OBJECT",
    0x426: "MSG_DO_FORCE_ATTACK_OBJECT",
    0x428: "MSG_GET_REPAIRED",
    0x42A: "MSG_DO_REPAIR",
    0x42C: "MSG_ENTER",
    0x434: "MSG_DO_GUARD_OBJECT",
    0x43C: "MSG_CAPTUREBUILDING",
    0x440: "MSG_SNIPE_VEHICLE",
}

#: Orders that name a target **position**. Weaker evidence by construction - ground can be aimed
#: at for honest reasons (a guess, a remembered location, a chokepoint) - so these are reported
#: at low confidence and never on their own terms.
POSITION_TARGETED: dict[int, str] = {
    0x40E: "MSG_DO_WEAPON_AT_LOCATION",
    0x411: "MSG_DO_SPECIAL_POWER_AT_LOCATION",
    0x421: "MSG_COMBATDROP_AT_LOCATION",
    0x427: "MSG_DO_FORCE_ATTACK_GROUND",
}

#: Every network order name the binary knows, for readable output on ids that are not targeted.
#: Only the ones above are ever judged.
_EXTRA_NAMES: dict[int, str] = {
    0x3E9: "MSG_CREATE_SELECTED_GROUP",
    0x3EC: "MSG_DESTROY_SELECTED_GROUP",
    0x410: "MSG_DO_SPECIAL_POWER",
    0x424: "MSG_AREA_SELECTION",
    0x42F: "MSG_DO_MOVETO",
    0x430: "MSG_DO_ATTACKMOVETO",
    0x431: "MSG_DO_FORCEMOVETO",
    0x44A: "MSG_LOGIC_CRC",
    0x448: "MSG_SELF_DESTRUCT",
}


def order_name(order_type: int) -> str:
    """The engine's name for an order id, or its hex if this module does not carry one."""
    for table in (OBJECT_TARGETED, POSITION_TARGETED, _EXTRA_NAMES):
        if order_type in table:
            return table[order_type]
    return f"0x{order_type:X}"


@dataclass(frozen=True)
class OrderTarget:
    """What an order aimed at: an object, a ground position, or neither."""

    object_id: int | None = None
    position: tuple[float, float, float] | None = None

    @property
    def is_object(self) -> bool:
        return self.object_id is not None

    @property
    def is_position(self) -> bool:
        return self.position is not None


def target_of(chunk: ReplayChunk) -> OrderTarget | None:
    """The target `chunk` names, or None when this order type is not evidence of anything.

    **The first argument of the matching type, not any argument of it.** A targeted order carries
    its target first and may carry other ids after it (a special power carries its own id, a
    combat drop carries both a location and an object). Taking the first keeps the reading
    aligned with the argument order `GameMessage::append*Argument` lays down, and a chunk that is
    missing it is reported as no target rather than guessed at from a later one.
    """
    if chunk.order_type in OBJECT_TARGETED:
        for argument in chunk.order.arguments:
            if argument.argument_type is OrderArgumentType.ObjectId:
                object_id = argument.value
                if isinstance(object_id, int) and object_id:
                    return OrderTarget(object_id=object_id)
                return None
        return None

    if chunk.order_type in POSITION_TARGETED:
        for argument in chunk.order.arguments:
            if argument.argument_type is OrderArgumentType.Position:
                position = argument.value
                if isinstance(position, tuple) and len(position) == 3:
                    return OrderTarget(
                        position=(float(position[0]), float(position[1]), float(position[2]))
                    )
                return None
        return None

    return None
