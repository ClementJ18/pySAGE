"""The observer-all-commands patch: an observer's clicks reach every command button.

Targets the ROTWK SAGE-engine `game.dat` build ``2.01.2614.37001``. The click path, the predicate
and every address below are derived in ``../../docs/observer-command-range.md``; what this patch
adds on top of that write-up is in ``../../docs/observer-all-commands.md``.

**The gate.** `ControlBar::processCommandUI` asks `PlayerList::localPlayerIsNotActive` before it
dispatches anything at all, and throws the click away when the answer is yes. That predicate is
``m_isObserver || m_isDefeated`` read straight off `ThePlayerList->m_local`, without the
`getLocalPlayer` redirect the rest of the bar goes through - so it is yes for the whole of any
replay and for the whole of a live game after being defeated. It is the only thing standing
between an observer and every command button on the palantir.

**What this does.** Deletes the question. The five bytes of the ``call`` become ``xor eax, eax``
and three ``nop``s, so the gate reads "the local player is active" for everybody, always, and
every click an observer makes is dispatched to `ControlBar::doCommand` exactly as a playing
player's would be.

**Why the whole of ``eax`` and not just ``al``.** The caller tests ``al``, but four instructions
later it builds the executor's two `Bool` arguments with ``sete al`` / ``setne al`` and pushes
``eax`` as a dword each time. The stock predicate returns a clean 0 or 1 in all thirty-two bits
(``neg al; sbb eax, eax; inc eax``), so zeroing only ``al`` would leave the top three bytes
holding whatever the window virtual at ``0x00941BBD`` returned and push a malformed bool into the
executor. ``xor eax, eax`` is the one replacement that keeps that contract identical to stock.

**Why inline and not a cave.** There is nothing left to decide: the answer is a constant, and a
constant fits in the five bytes the ``call`` occupied. ``ecx``, loaded with `ThePlayerList` two
instructions above, simply becomes a dead load - it is caller-saved and nothing downstream reads
it before `ControlBar::doCommand` reloads it from ``ebx``.

**What this is for, and what it is not.** Read-only interest in the *other* buttons is the point:
a paging button whose page the sibling patch already reaches, a tooltip or detail panel that only
opens on a click, a spellbook page, a tab. The engine does not sort commands into "inspect" and
"order" - this gate was the sort - so removing it hands the observer the order-posting commands
as well, and clicking one of those posts a real `GameMessage` from a seat the engine has already
decided is not playing. That is why this is experimental and why `observer-command-range` exists:
that patch names the two commands that change nothing but which slice of a `CommandSet` is on
screen, and refuses the rest. Prefer it unless the whole bar is what you are after.

**Determinism.** *Not* client-local: every command past the two paging ones ends in a posted
`GameMessage`. `observer-command-range`, `observer-switch` and `replay-outcome` are all honest
about staying out of the simulation; this one is not, and nothing in it tries to be.

**What it does not do, measured in a live game 2026-09-20.** It does not make an observer's
commands *take effect*. The buttons render lit, the clicks dispatch, the handlers post their
messages - and every order is then attributed to ``ThePlayerList->m_local``, the observer seat,
rather than to the `PlayerList::getLocalPlayer` redirect that the bar, the portraits and the
availability evaluation all use. That seat owns no objects and has no production, so each order
is issued, accepted and executed as a well-formed no-op. It is the same asymmetry that made the
gate bite, one layer further down. Where attribution is stamped has not been located - it is not
in the message-stream code, which holds no reference to `ThePlayerList` at all - so nothing here
redirects it. ``../../docs/observer-all-commands.md`` §4 is the measurement and §4.3 the open
question.

**Mutually exclusive with `observer-command-range`.** Both own the same five bytes at
`CONTROL_BAR_CLICK_GATE_CALL`, so whichever is applied second raises rather than writing; this
one says which other patch is in the way. The exclusion costs nothing, because what that patch
allows is a strict subset of what this one does.

**Composition, otherwise.** Order-independent, and no cave: five bytes in
`ControlBar::processCommandUI` that no other bundled patch reads or rewrites. No INI surface -
the buttons it makes clickable are the ones a mod's `CommandSet` already defines.
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

#: What replaces the ``call``: ``xor eax, eax`` and three ``nop``s. Same five bytes, and the
#: answer the caller's ``test al, al`` reads is now a constant zero - "the local player is
#: active", the edge that dispatches. Padded with ``nop`` rather than a shorter encoding so the
#: instruction boundary at `CONTROL_BAR_CLICK_GATE_SUFFIX` is where it was: the ``jne`` four
#: bytes below is a backward ``rel8`` into the discard path and is not rewritten.
ALWAYS_ACTIVE = bytes.fromhex("31c0909090")

#: The sites the patch depends on but does not rewrite, as a ``{va: bytes}`` map.
#:
#: The prefix pins the gate's own shape - the ``test esi, esi`` and the `ThePlayerList` load whose
#: ``ecx`` this patch turns into a dead one. The suffix pins the consumer: ``test al, al`` and the
#: ``jne`` into the discard path are what the constant zero is answering, and on a build where
#: those bytes are something else the five written here mean nothing. The argument build pins the
#: ``sete``/``setne`` pair that makes the width of the zero load-bearing - it is the only anchor
#: here that would not be missed by a reader who thought ``xor al, al`` was enough.
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
        """Say *why* the gate is not the stock ``call``, while the answer is still knowable.

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
