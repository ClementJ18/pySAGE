"""Let an observer's clicks reach every command button.

The control bar only dispatches a click when the local player is active, which an observer never is.
The five-byte `call` behind that test becomes `xor eax, eax` and `nop`s, so every click dispatches
to `ControlBar::doCommand`. Measured in game, the orders then have no effect: they are attributed to
the observer seat, which owns nothing, and where that attribution is stamped is not yet found.
Mutually exclusive with `observer-command-range`.

Derivation: `../../docs/observer-command-range.md` and `../../docs/observer-all-commands.md`
(section 4).
"""

from __future__ import annotations

from ...addresses import (
    CONTROL_BAR_CLICK_ARGUMENT_BUILD,
    CONTROL_BAR_CLICK_ARGUMENT_BUILD_BYTES,
    CONTROL_BAR_CLICK_GATE_CALL,
    CONTROL_BAR_CLICK_GATE_CALL_BYTES,
    CONTROL_BAR_CLICK_GATE_PREFIX,
    CONTROL_BAR_CLICK_GATE_PREFIX_BYTES,
    CONTROL_BAR_CLICK_GATE_SUFFIX,
    CONTROL_BAR_CLICK_GATE_SUFFIX_BYTES,
)
from ...patcher import Patch
from ...utils import apply_byte_patch, va_to_offset

__all__ = ["ANCHORS", "ALWAYS_ACTIVE", "ObserverAllCommandsPatch"]

#: What replaces the `call`: `xor eax, eax` and three `nop`s. Same five bytes, and the
#: answer the caller's `test al, al` reads is now a constant zero - "the local player is
#: active", the edge that dispatches. Padded with `nop` rather than a shorter encoding so the
#: instruction boundary at `CONTROL_BAR_CLICK_GATE_SUFFIX` is where it was: the `jne` four
#: bytes below is a backward `rel8` into the discard path and is not rewritten.
ALWAYS_ACTIVE = bytes.fromhex("31c0909090")

#: The sites the patch depends on but does not rewrite, as a `{va: bytes}` map.
#:
#: The prefix pins the gate's own shape - the `test esi, esi` and the `ThePlayerList` load whose
#: `ecx` this patch turns into a dead one. The suffix pins the consumer: `test al, al` and the
#: `jne` into the discard path are what the constant zero is answering, and on a build where
#: those bytes are something else the five written here mean nothing. The argument build pins the
#: `sete`/`setne` pair that makes the width of the zero load-bearing - it is the only anchor
#: here that would not be missed by a reader who thought `xor al, al` was enough.
ANCHORS = {
    CONTROL_BAR_CLICK_GATE_PREFIX: CONTROL_BAR_CLICK_GATE_PREFIX_BYTES,
    CONTROL_BAR_CLICK_GATE_SUFFIX: CONTROL_BAR_CLICK_GATE_SUFFIX_BYTES,
    CONTROL_BAR_CLICK_ARGUMENT_BUILD: CONTROL_BAR_CLICK_ARGUMENT_BUILD_BYTES,
}


class ObserverAllCommandsPatch(Patch):
    """Let an observer's command-bar clicks through, all of them."""

    name = "observer-all-commands"
    author = "officialNecro"
    experimental = True
    description = (
        "Let an observer click every button on the command bar, not just the paging ones: "
        "ControlBar::processCommandUI stops asking whether the local player is sitting out. "
        "Supersedes and conflicts with observer-command-range. Order-posting commands dispatch "
        "too, but the engine attributes each order to the observer seat, so they are no-ops in "
        "the simulation - the gate is open, the orders do nothing. No INI change"
    )

    def apply(self, data: bytearray) -> None:
        gate_off = self._gate_offset(data)
        self._check_site(data, gate_off)
        self._check_anchors(data)
        apply_byte_patch(
            data,
            gate_off,
            CONTROL_BAR_CLICK_GATE_CALL_BYTES,
            ALWAYS_ACTIVE,
            "processCommandUI observer gate -> always active",
        )

    def verify(self, data: bytes | bytearray) -> list[str]:
        problems: list[str] = []
        gate_off = va_to_offset(data, CONTROL_BAR_CLICK_GATE_CALL)
        if gate_off is None:
            return [f"{CONTROL_BAR_CLICK_GATE_CALL:#010x} is not mapped by any section"]

        got = bytes(data[gate_off : gate_off + len(ALWAYS_ACTIVE)])
        if got != ALWAYS_ACTIVE:
            problems.append(
                f"the click gate at {CONTROL_BAR_CLICK_GATE_CALL:#010x} holds {got.hex()}, "
                f"expected {ALWAYS_ACTIVE.hex()} - the gate is not open"
            )
        for va, anchor in ANCHORS.items():
            off = va_to_offset(data, va)
            if off is None or bytes(data[off : off + len(anchor)]) != anchor:
                problems.append(
                    f"{va:#010x} is not {anchor.hex()} - the click path is not this build's"
                )
        return problems

    @staticmethod
    def _gate_offset(data: bytes | bytearray) -> int:
        off = va_to_offset(data, CONTROL_BAR_CLICK_GATE_CALL)
        if off is None:
            raise ValueError(
                f"{CONTROL_BAR_CLICK_GATE_CALL:#010x} is not mapped - not the expected build"
            )
        return off

    @staticmethod
    def _check_site(data: bytes | bytearray, gate_off: int) -> None:
        """Say *why* the gate is not the stock `call`, while the answer is still knowable.

        `apply_byte_patch` would refuse either way, with a hex pair. The two cases worth naming
        are the two that actually happen: this patch applied twice, and `observer-command-range`
        having already retargeted the same five bytes at its own cave."""
        got = bytes(data[gate_off : gate_off + len(CONTROL_BAR_CLICK_GATE_CALL_BYTES)])
        if got == CONTROL_BAR_CLICK_GATE_CALL_BYTES:
            return
        if got == ALWAYS_ACTIVE:
            raise ValueError(
                f"{CONTROL_BAR_CLICK_GATE_CALL:#010x} already holds {ALWAYS_ACTIVE.hex()} - "
                "observer-all-commands is applied to this binary"
            )
        if got[0] == 0xE8:
            raise ValueError(
                f"{CONTROL_BAR_CLICK_GATE_CALL:#010x} calls {got.hex()} rather than the stock "
                "predicate - another patch owns this gate, almost certainly "
                "observer-command-range, whose whitelist this patch would replace wholesale. "
                "Apply one or the other to a clean binary, not both"
            )

    @staticmethod
    def _check_anchors(data: bytes | bytearray) -> None:
        for va, anchor in ANCHORS.items():
            off = va_to_offset(data, va)
            if off is None:
                raise ValueError(f"{va:#010x} is not mapped - not the expected build")
            got = bytes(data[off : off + len(anchor)])
            if got != anchor:
                raise ValueError(
                    f"{va:#010x} holds {got.hex()}, expected {anchor.hex()} - the ControlBar's "
                    "click path is not this build's, so the zero written at the gate would be "
                    "answering a question nothing asks"
                )
