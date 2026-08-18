"""The observer-switch patch: let a skirmish replay cycle players, as a network replay already can.

Targets the ROTWK SAGE-engine `game.dat` build ``2.01.2614.37001``. Every address below is
derived in ``../docs/observer-switch.md``.

**The gap.** Watching a recorded skirmish, the observer bar never appears: no *next player* /
*prior player* buttons, so there is no way to move the camera onto another seat and see its
vision, its palantir and its unlocked spellbook. The same replay recorded from a network game
offers all of it.

Only one thing differs. The palantir's per-frame update asks two questions before showing the
bar - the APT clip ``ObserverStuff``, which holds ``NextPlayerBttn`` and ``PriorPlayerBttn``:

1. ``0x0062541E`` - is this a multiplayer game, or a replay of one? and
2. ``0x006A87F5`` - is the local player an observer (or defeated)?

The second is true in any replay. The first tests the **recorded** game mode against ``{1, 5}``,
the same network-only whitelist ``skirmish-replay`` had to widen at the recording end - and a
recorded skirmish carries mode **2**, read straight off the header by `startPlayback`. So the
answer is no, the bar is hidden, and the whole observer UI is unreachable for the length of the
playback.

**Everything downstream already works**, which is why the fix is this small:

* `PlayerList::observeNextPlayer` (`PLAYER_LIST_OBSERVE_NEXT_PLAYER`) - the switch itself - gates
  on nothing but question 2 above and `GameLogic::isInGame` (`GAME_LOGIC_IS_IN_GAME`: the mode is
  not the shell map). Neither cares whether the game was a skirmish.
* Playback installs the observer seat at `PLAYBACK_INSTALLS_OBSERVER` on
  ``TheGameLogic+0x110 == 3`` - the *playback* mode, which is 3 whatever was recorded - so a
  skirmish replay already gets `setLocalPlayer(ReplayObserver)` and its initially-observed player
  seeded from the recorded local index.
* Switching re-runs `TheShroudManager` and `TheTaintManager` for the new seat, so the vision
  follows the button, and the palantir redraws off `ControlBar+0x218`.

**What it does.** Retargets the single ``call`` at ``0x006D7813`` from ``0x0062541E`` to
``0x00625456`` - the engine's own sibling predicate, identical but for accepting a live skirmish
and a *recorded* mode of 2. Five bytes, one call site, no cave. That is the same function
``docs/skirmish-replay.md`` §3 cites as proof the engine already anticipates a mode-2 recording;
it has 31 other callers, so nothing about it is new code paths.

**Why the call site and not the predicate.** ``0x0062541E`` would be equally patchable - it has
exactly one caller, this one - but rewriting it means writing a third copy of a mode whitelist the
binary already states twice. Repointing the call reuses the shipped one, and leaves a diff of one
`call` target that says exactly what it does.

**The one behavioural spillover.** ``0x00625456`` also answers true for a *live* skirmish, so the
bar now appears in a live game against the AI once the local player is an observer or has been
defeated. That is precisely what the stock engine does in a live network game under the same
condition; this extends it to skirmish rather than inventing anything. It cannot appear while you
are still playing, because question 2 is false for an active player.

**Determinism.** The gate is client-side UI: nothing enters the simulation, nothing is sent, and
`observeNextPlayer` issues no `GameMessage`. Like `replay-outcome` and `skirmish-replay`, and
unlike `production-condition`, it does not have to be on every peer.

**Composition.** Order-independent, and it allocates no section. The five bytes it edits are
touched by no other bundled patch, and it reads nothing another patch rewrites. It is the natural
companion to `skirmish-replay`, which is what produces a mode-2 recording in the first place, but
the two are independent: either applies without the other.
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
    """The five bytes that replace the gate's ``call``: the same opcode, aimed at the sibling
    predicate that counts a skirmish."""
    rel = IS_MULTIPLAYER_OR_SKIRMISH_OR_ITS_REPLAY - (
        OBSERVER_BAR_GATE_CALL + len(OBSERVER_BAR_GATE_CALL_BYTES)
    )
    return b"\xe8" + struct.pack("<i", rel)


class ObserverSwitchPatch(Patch):
    name = "observer-switch"
    author = "officialNecro"
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
        """Raise unless the whole 66-byte run around the ``call`` is still what it was: the
        `TheGameLogic` load, the second predicate on `ThePlayerList`, the cached-state compare
        against ``Palantir+0x7E`` and both `SetObserverStuffState` thunks.

        The call's own five bytes are deliberately **not** compared: this runs from :meth:`verify`
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
