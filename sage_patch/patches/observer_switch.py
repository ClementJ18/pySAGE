"""Show the observer's next/prior-player buttons in a skirmish replay, as a network replay already
does.

One `call` at `0x006D7813` is retargeted from `0x0062541E` to `0x00625456`, the engine's own sibling
predicate that also accepts a recorded mode of 2. Five bytes, no cave.

Derivation: `../docs/observer-switch.md` and `../docs/skirmish-replay.md`.
"""

from __future__ import annotations

import struct

from ..addresses import (
    IS_MULTIPLAYER_OR_ITS_REPLAY,
    IS_MULTIPLAYER_OR_ITS_REPLAY_BYTES,
    IS_MULTIPLAYER_OR_SKIRMISH_OR_ITS_REPLAY,
    IS_MULTIPLAYER_OR_SKIRMISH_OR_ITS_REPLAY_BYTES,
    OBSERVER_BAR_GATE_CALL,
    OBSERVER_BAR_GATE_CALL_BYTES,
    OBSERVER_BAR_GATE_FINGERPRINT,
    OBSERVER_BAR_GATE_FINGERPRINT_BYTES,
)
from ..patcher import Patch
from ..utils import apply_byte_patch, va_to_offset

__all__ = ["ANCHORS", "ObserverSwitchPatch", "patched_call_bytes"]

#: The two predicates, by address and by first bytes. The one being left behind is checked as
#: well as the one being called: what makes the `call` at `OBSERVER_BAR_GATE_CALL` the observer
#: bar's gate is that it points at the network-only predicate, and a build where either function
#: moved would otherwise repoint a `call` at whatever now lives at that address.
ANCHORS = {
    IS_MULTIPLAYER_OR_ITS_REPLAY: IS_MULTIPLAYER_OR_ITS_REPLAY_BYTES,
    IS_MULTIPLAYER_OR_SKIRMISH_OR_ITS_REPLAY: IS_MULTIPLAYER_OR_SKIRMISH_OR_ITS_REPLAY_BYTES,
}


def patched_call_bytes() -> bytes:
    """The five bytes that replace the gate's `call`: the same opcode, aimed at the sibling
    predicate that counts a skirmish."""
    rel = IS_MULTIPLAYER_OR_SKIRMISH_OR_ITS_REPLAY - (
        OBSERVER_BAR_GATE_CALL + len(OBSERVER_BAR_GATE_CALL_BYTES)
    )
    return b"\xe8" + struct.pack("<i", rel)


class ObserverSwitchPatch(Patch):
    name = "observer-switch"
    author = "officialNecro"
    runtime_verified = "yes"
    description = (
        "Show the replay observer's next/prior player buttons in a skirmish replay, so the "
        "camera, vision and spellbook can be switched between players as in a network replay. "
        "No INI or .apt change - the ObserverStuff clip already carries the buttons"
    )

    def apply(self, data: bytearray) -> None:
        off = va_to_offset(data, OBSERVER_BAR_GATE_CALL)
        if off is None:
            raise ValueError(
                f"{OBSERVER_BAR_GATE_CALL:#010x} is not mapped - not the expected build"
            )
        self._check_gate(data)
        self._check_anchors(data)
        apply_byte_patch(
            data,
            off,
            OBSERVER_BAR_GATE_CALL_BYTES,
            patched_call_bytes(),
            "observer bar gate -> the predicate that counts a skirmish replay",
        )

    @staticmethod
    def _check_gate(data: bytes | bytearray) -> None:
        """Raise unless the whole 66-byte run around the `call` is still what it was: the
        `TheGameLogic` load, the second predicate on `ThePlayerList`, the cached-state compare
        against `Palantir+0x7E` and both `SetObserverStuffState` thunks.

        The call's own five bytes are deliberately **not** compared: this runs from `verify`
        too, where they are the edit. Everything around them is untouched by the patch, which is
        what lets one check serve both."""
        split = OBSERVER_BAR_GATE_FINGERPRINT_BYTES.index(OBSERVER_BAR_GATE_CALL_BYTES)
        off = va_to_offset(data, OBSERVER_BAR_GATE_FINGERPRINT)
        if off is None:
            raise ValueError("the palantir's observer gate is not mapped - not the expected build")
        end = split + len(OBSERVER_BAR_GATE_CALL_BYTES)
        for at, expected in (
            (0, OBSERVER_BAR_GATE_FINGERPRINT_BYTES[:split]),
            (end, OBSERVER_BAR_GATE_FINGERPRINT_BYTES[end:]),
        ):
            got = bytes(data[off + at : off + at + len(expected)])
            if got != expected:
                raise ValueError(
                    f"{OBSERVER_BAR_GATE_FINGERPRINT + at:#010x} is {got.hex()}, expected "
                    f"{expected.hex()} - this is not the observer bar's visibility gate"
                )

    @staticmethod
    def _check_anchors(data: bytes | bytearray) -> None:
        for va, expected in ANCHORS.items():
            off = va_to_offset(data, va)
            if off is None:
                raise ValueError(f"{va:#010x} is not mapped - not the expected build")
            got = bytes(data[off : off + len(expected)])
            if got != expected:
                raise ValueError(
                    f"{va:#010x} holds {got.hex()}, expected {expected.hex()} - the game-mode "
                    "predicates are not this build's, so the call would be aimed at the wrong "
                    "function"
                )

    def verify(self, data: bytes | bytearray) -> list[str]:
        problems: list[str] = []
        off = va_to_offset(data, OBSERVER_BAR_GATE_CALL)
        if off is None:
            return [f"{OBSERVER_BAR_GATE_CALL:#010x} is not mapped by any section"]
        if data[off] != 0xE8:
            problems.append(f"{OBSERVER_BAR_GATE_CALL:#010x} is not a call - not installed")
        else:
            rel = struct.unpack_from("<i", data, off + 1)[0]
            target = OBSERVER_BAR_GATE_CALL + len(OBSERVER_BAR_GATE_CALL_BYTES) + rel
            if target != IS_MULTIPLAYER_OR_SKIRMISH_OR_ITS_REPLAY:
                stock = target == IS_MULTIPLAYER_OR_ITS_REPLAY
                was = " (the stock network-only one)" if stock else ""
                problems.append(
                    f"the observer bar gate calls {target:#010x}{was}, expected "
                    f"{IS_MULTIPLAYER_OR_SKIRMISH_OR_ITS_REPLAY:#010x}"
                )
        try:
            self._check_gate(data)
            self._check_anchors(data)
        except ValueError as exc:
            problems.append(str(exc))
        return problems
