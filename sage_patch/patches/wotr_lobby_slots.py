"""Open all eight slots of a multiplayer War of the Ring lobby to human players.

The game-setup screen applies two War of the Ring rules no other mode has. Its gadget binder hides
every window of the seventh and eighth slot, and its slot-state combo offers `GUI:Open` to one slot
at a time and to none once a second human is seated. Together they make the mode six seats, two of
them human. Each rule is one conditional branch, and each becomes unconditional - the binder never
hides, the combo skips its walk - so the lobby behaves as the skirmish and LAN lobbies already do.

The historical-scenario cap is untouched: a `HistoricalScenario` still closes every slot from its
`MaxPlayers` up, and the start gate still refuses more players than `MaxPlayers`, capped at 8.

Derivation: `../docs/living-campaign/wotr-lobby-slots.md`.
"""

from __future__ import annotations

from ..addresses import (
    MP_SETUP_GADGET_UNKNOWN,
    MP_SETUP_GADGET_WOTR_SLOT_JB,
    MP_SETUP_GADGET_WOTR_SLOT_TEST,
    MP_SETUP_GADGET_WOTR_SLOT_TEST_BYTES,
    MP_SETUP_SLOT_COMBO_WALK_DONE,
    MP_SETUP_SLOT_COMBO_WOTR_OPEN_GATE,
    MP_SETUP_SLOT_COMBO_WOTR_OPEN_GATE_BYTES,
    MP_SETUP_SLOT_COMBO_WOTR_OPEN_JE,
)
from ..patcher import Patch
from ..utils import apply_byte_patch, va_to_offset

__all__ = ["JMP_SHORT", "SITES", "WotrLobbySlotsPatch"]

#: The opcode both branches become. Each is a two-byte `jcc rel8`, so swapping the opcode for
#: `jmp rel8` keeps the target and the length.
JMP_SHORT = 0xEB

#: `(anchor VA, its stock bytes, branch VA, stock opcode, target, what it is)`. The branch is the
#: last two bytes of its anchor.
SITES: tuple[tuple[int, bytes, int, int, int, str], ...] = (
    (
        MP_SETUP_GADGET_WOTR_SLOT_TEST,
        MP_SETUP_GADGET_WOTR_SLOT_TEST_BYTES,
        MP_SETUP_GADGET_WOTR_SLOT_JB,
        0x72,
        MP_SETUP_GADGET_UNKNOWN,
        "gadget binder: never hide slots 7-8",
    ),
    (
        MP_SETUP_SLOT_COMBO_WOTR_OPEN_GATE,
        MP_SETUP_SLOT_COMBO_WOTR_OPEN_GATE_BYTES,
        MP_SETUP_SLOT_COMBO_WOTR_OPEN_JE,
        0x74,
        MP_SETUP_SLOT_COMBO_WALK_DONE,
        "slot-state combo: skip the one-open-slot walk",
    ),
)


class WotrLobbySlotsPatch(Patch):
    name = "wotr-lobby-slots"
    author = "officialNecro"
    runtime_verified = "partly"
    description = (
        "Let all eight slots of a multiplayer War of the Ring lobby be opened to human players. "
        "Stock, slots 7 and 8 are hidden and only one slot at a time may be set to Open, so the "
        "mode seats at most six players and two humans. A HistoricalScenario's MaxPlayers still "
        "closes the slots above it. Pair with wotr-battle-observers, without which a battle that "
        "leaves out a human auto-resolves. Scenarios need MaxPlayers raised to 8 for the start "
        "gate; no .str or .apt change"
    )

    def apply(self, data: bytearray) -> None:
        for anchor, stock, branch, _opcode, _target, _what in SITES:
            self._check_anchor(data, anchor, stock, branch)
        for _anchor, _stock, branch, opcode, _target, what in SITES:
            off = self._offset(data, branch)
            apply_byte_patch(data, off, bytes([opcode]), bytes([JMP_SHORT]), what)

    @staticmethod
    def _offset(data: bytes | bytearray, va: int) -> int:
        off = va_to_offset(data, va)
        if off is None:
            raise ValueError(f"{va:#010x} is not mapped - not the expected build")
        return off

    @classmethod
    def _check_anchor(cls, data: bytes | bytearray, anchor: int, stock: bytes, branch: int) -> None:
        """Raise unless the bytes before the branch are the stock test.

        The opcode itself is left out of the comparison, so this holds on a patched image too and
        `verify` can tell "patched" from "some other code"."""
        off = cls._offset(data, anchor)
        size = branch - anchor
        got = bytes(data[off : off + len(stock)])
        if got[:size] != stock[:size] or got[size + 1 :] != stock[size + 1 :]:
            raise ValueError(
                f"{anchor:#010x} holds {got.hex()}, not {stock.hex()} - this is not the "
                "game-setup screen of the expected build"
            )

    def verify(self, data: bytes | bytearray) -> list[str]:
        problems: list[str] = []
        for anchor, stock, branch, opcode, _target, what in SITES:
            try:
                self._check_anchor(data, anchor, stock, branch)
            except ValueError as exc:
                problems.append(str(exc))
                continue
            got = data[self._offset(data, branch)]
            if got != JMP_SHORT:
                which = "the stock branch" if got == opcode else "something else"
                problems.append(
                    f"{branch:#010x} holds {got:02x} ({which}), not jmp: {what} is not applied"
                )
        return problems
