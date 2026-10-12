"""Stop one skirmish AI build order that has no builder from starving every order behind it.

The AI keeps its farms, structures, upgrades and units in one queue and walks it from the front
each tick, starting the first order it can. An order that answers "no builder I can use" ends the
walk whenever the AI's pool of free builders is not empty - the stock reading being "a builder is
coming, hold the queue for it". When the pooled builders can never serve that order the walk ends
there every tick, and a farm order at priority 2000 keeps an AI with a full bank from recruiting
until its army falls under a third of its command points.

Two bytes: the branch that ends the walk becomes `nop`s, so the order takes the pump's ordinary
"not this one, next" path. AI-only - the pump is `AIPlayer`'s. Applies to every faction.

Derivation: `../docs/ai-build-queue-skip.md`.
"""

from __future__ import annotations

from ..addresses import (
    AI_ORDER_PUMP_CAN_START_CALL,
    AI_ORDER_PUMP_CAN_START_CALL_BYTES,
    AI_ORDER_PUMP_NO_BUILDER_STOP,
    AI_ORDER_PUMP_NO_BUILDER_STOP_BYTES,
    AI_ORDER_PUMP_NO_BUILDER_TEST,
    AI_ORDER_PUMP_NO_BUILDER_TEST_BYTES,
)
from ..patcher import Patch
from ..utils import apply_byte_patch, va_to_offset

__all__ = ["ANCHORS", "NOPS", "AiBuildQueueSkipPatch"]

#: What the stop becomes: one `nop` per byte of the `ja` it replaces.
NOPS = b"\x90" * len(AI_ORDER_PUMP_NO_BUILDER_STOP_BYTES)

#: Byte windows the patch depends on and does not write: the call whose answer is being tested,
#: and the test the removed branch belongs to.
ANCHORS: dict[int, bytes] = {
    AI_ORDER_PUMP_CAN_START_CALL: AI_ORDER_PUMP_CAN_START_CALL_BYTES,
    AI_ORDER_PUMP_NO_BUILDER_TEST: AI_ORDER_PUMP_NO_BUILDER_TEST_BYTES,
}


class AiBuildQueueSkipPatch(Patch):
    name = "ai-build-queue-skip"
    author = "officialNecro"
    description = (
        "The skirmish AI skips a build order that has no builder it can use instead of ending "
        "its queue walk there, so a farm or structure order that cannot start no longer keeps "
        "the orders behind it - units above all - from starting. All factions. No INI change"
    )

    def apply(self, data: bytearray) -> None:
        self._check_anchors(data)
        apply_byte_patch(
            data,
            self._offset(data, AI_ORDER_PUMP_NO_BUILDER_STOP),
            AI_ORDER_PUMP_NO_BUILDER_STOP_BYTES,
            NOPS,
            "AI order pump: skip an order with no builder",
        )

    @staticmethod
    def _offset(data: bytes | bytearray, va: int) -> int:
        off = va_to_offset(data, va)
        if off is None:
            raise ValueError(f"{va:#010x} is not mapped - not the expected build")
        return off

    @classmethod
    def _check_anchors(cls, data: bytes | bytearray) -> None:
        """Raise unless the bytes before the site are the pump's no-builder test.

        The branch is only this patch's to remove when it is the one taken on that test: a build
        whose pump moved would otherwise have some other two bytes turned into `nop`s."""
        for va, expected in ANCHORS.items():
            off = cls._offset(data, va)
            got = bytes(data[off : off + len(expected)])
            if got != expected:
                raise ValueError(
                    f"{va:#010x} holds {got.hex()}, expected {expected.hex()} - this is not the "
                    "AI order pump's no-builder test of the expected build"
                )

    def verify(self, data: bytes | bytearray) -> list[str]:
        try:
            self._check_anchors(data)
        except ValueError as exc:
            return [str(exc)]
        off = self._offset(data, AI_ORDER_PUMP_NO_BUILDER_STOP)
        got = bytes(data[off : off + len(NOPS)])
        if got == NOPS:
            return []
        which = "the stock stop" if got == AI_ORDER_PUMP_NO_BUILDER_STOP_BYTES else "something else"
        return [
            f"{AI_ORDER_PUMP_NO_BUILDER_STOP:#010x} holds {got.hex()} ({which}): the file does not "
            "carry this patch"
        ]
