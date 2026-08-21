"""The observer-command-range patch: let an observer page a command bar.

Targets the ROTWK SAGE-engine `game.dat` build ``2.01.2614.37001``. Every address below is
derived in ``../docs/observer-command-range.md``.

**The gap.** Observing a seat - a replay, or a live game after being defeated - the palantir
populates for the observed player, portraits and production and upgrade states included. Select a
structure whose `CommandSet` pages itself with a `PUSH_VISIBLE_COMMAND_RANGE` button and the
button is there, drawn enabled, and does nothing. Whatever is being bought or researched on page
two stays unreadable for the whole match.

**One predicate eats the click**, and it eats every command-bar click an observer makes:
`ControlBar::processCommandUI` asks `PlayerList::localPlayerIsNotActive`
(`PLAYER_LIST_LOCAL_IS_NOT_ACTIVE`) and returns without dispatching when the answer is yes. That
predicate is ``m_isObserver || m_isDefeated`` on `ThePlayerList->m_local`, so it is yes for the
length of any observed game.

**Everything else is already right**, which is what makes the fix this small:

* `PlayerList::getLocalPlayer` (`PLAYER_LIST_GET_LOCAL_PLAYER`) is not a plain getter: when
  `m_local` is inactive it returns `ControlBar+0x218`, the observed player. So
  `ControlBar::getCommandAvailability` evaluates every button - every science, upgrade and
  affordability test - against the seat being watched, and the page a `PUSH` would reveal is that
  player's real state rather than the observer's empty one.
* Both paging commands land in that evaluator's **default** case, verdict ``1`` (enabled), and
  the per-frame status update deliberately leaves an observer's verdicts alone where it forces an
  active player's foreign-object verdicts to zero. That is exactly why the button looks live.
* The context evaluator gives an observer the full command set, because `Player::getRelationship`
  answers `NEUTRAL` by default and an observer seat declares no relationships - the same branch a
  neutral capturable structure takes.

**What it does.** Retargets the single ``call`` at `CONTROL_BAR_CLICK_GATE_CALL` into a 28-byte
cave that answers "the local player is active" for `GUICOMMAND_PUSH_VISIBLE_COMMAND_RANGE` and
`GUICOMMAND_POP_VISIBLE_COMMAND_RANGE`, and tail-calls the stock predicate for every other
command. Five bytes at the call site; nothing else in the click path changes.

**Why a whitelist and not the gate.** This gate is the only thing between an observer and *every*
command button. Removing it would let an observer issue real orders - `UNIT_BUILD` and its
neighbours post `GameMessage`s - so the two commands are named rather than the gate deleted. They
are the two the engine has that change nothing but which slice of a `CommandSet` is on screen:
`PUSH` appends the button's range pair to the stack at ``ControlBar+0x2B0``, `POP` drops the top
one, and both then re-run `switchToContext` to redraw.

**Why the call site and not the predicate.** `PLAYER_LIST_LOCAL_IS_NOT_ACTIVE` has twelve
callers, the observer bar's own visibility gate among them, so widening it in place would leak
into all of them. Retargeting one ``call`` changes exactly one question.

**Determinism.** Client-side UI: neither handler posts a `GameMessage` and neither touches an
object, so nothing enters the simulation. Like `observer-switch` and `replay-outcome`, and unlike
`production-condition`, it does not have to be on every peer, and a replay it is applied to stays
faithful.

**Spillover.** The predicate is ``m_isObserver || m_isDefeated``, so a player who has lost a live
game can page the bar too. That is the same read-only affordance, and splitting the two cases
would mean reading the observer flag separately for no behavioural difference.

**What it does not add.** No UI and no INI surface: the paging buttons it makes clickable are the
ones a mod's `CommandSet` already defines, under the ceiling
``CommandRangeStart + CommandRangeCount <= N`` that `docs/push-visible-command-range.md` sets. A
`CommandSet` with no paging button gains nothing.

**Composition.** Order-independent. The cave is allocated with
:func:`~..utils.allocate_section` past every existing section and :meth:`verify` finds it by
name; the five bytes it edits are touched by no other bundled patch, and the structures it reads
- the click gate and the executor's two switch tables - are ones nothing else rewrites. It is the
natural companion to `observer-switch`, which is what gets an observer onto a skirmish replay's
seat in the first place, but the two are independent: either applies without the other.
"""

from __future__ import annotations

import struct

from ..addresses import (
    COMMAND_BUTTON_COMMAND,
    CONTROL_BAR_CLICK_BUTTON_LOAD,
    CONTROL_BAR_CLICK_BUTTON_LOAD_BYTES,
    CONTROL_BAR_CLICK_GATE_CALL,
    CONTROL_BAR_CLICK_GATE_CALL_BYTES,
    CONTROL_BAR_CLICK_GATE_PREFIX,
    CONTROL_BAR_CLICK_GATE_PREFIX_BYTES,
    CONTROL_BAR_CLICK_GATE_SUFFIX,
    CONTROL_BAR_CLICK_GATE_SUFFIX_BYTES,
    CONTROL_BAR_COMMAND_DISPATCH,
    CONTROL_BAR_COMMAND_DISPATCH_BYTES,
    CONTROL_BAR_COMMAND_INDEX_TABLE,
    CONTROL_BAR_COMMAND_JUMP_TABLE,
    CONTROL_BAR_POP_RANGE_HANDLER,
    CONTROL_BAR_POP_RANGE_HANDLER_BYTES,
    CONTROL_BAR_PUSH_RANGE_HANDLER,
    CONTROL_BAR_PUSH_RANGE_HANDLER_BYTES,
    GUICOMMAND_POP_VISIBLE_COMMAND_RANGE,
    GUICOMMAND_PUSH_VISIBLE_COMMAND_RANGE,
    PLAYER_LIST_LOCAL_IS_NOT_ACTIVE,
    PLAYER_LIST_LOCAL_IS_NOT_ACTIVE_BYTES,
)
from ..asm import JE, Asm
from ..patcher import Patch
from ..utils import allocate_section, apply_byte_patch, find_section, va_to_offset

__all__ = [
    "ANCHORS",
    "PAGING_COMMANDS",
    "SECTION_NAME",
    "ObserverCommandRangePatch",
    "build_code",
]


def _call_bytes(from_va: int, to_va: int) -> bytes:
    """The five bytes of ``call rel32`` sited at ``from_va``."""
    return b"\xe8" + struct.pack("<i", to_va - (from_va + 5))


SECTION_NAME = ".obscmd"  # 7 chars: the PE name field is 8 bytes and truncates silently

# IMAGE_SCN_CNT_CODE | MEM_EXECUTE | MEM_READ - the cave is pure code and is never written.
_CHARACTERISTICS = 0x20 | 0x20000000 | 0x40000000

#: The commands the cave waves through, as ``(GUICOMMAND, handler VA, handler bytes)``. The
#: handler is carried alongside the number so :meth:`~ObserverCommandRangePatch.verify` can walk
#: the executor's own switch tables and prove the number reaches the paging code in *this* binary,
#: rather than trusting the ordering of the name table it was read from.
PAGING_COMMANDS = (
    (
        GUICOMMAND_PUSH_VISIBLE_COMMAND_RANGE,
        CONTROL_BAR_PUSH_RANGE_HANDLER,
        CONTROL_BAR_PUSH_RANGE_HANDLER_BYTES,
    ),
    (
        GUICOMMAND_POP_VISIBLE_COMMAND_RANGE,
        CONTROL_BAR_POP_RANGE_HANDLER,
        CONTROL_BAR_POP_RANGE_HANDLER_BYTES,
    ),
)

#: The sites the patch depends on but does not rewrite, as a ``{va: bytes}`` map. The gate is
#: anchored either side of the ``call`` and never across it, so both halves stay valid once the
#: call is retargeted; `..._BUTTON_LOAD` pins where ``esi`` comes from, and the predicate's own
#: first bytes prove the tail jump lands on it. None of these would be caught by anything else -
#: a cave reading ``[esi+0x14]`` off some other pointer just reads whatever is there.
ANCHORS = {
    CONTROL_BAR_CLICK_BUTTON_LOAD: CONTROL_BAR_CLICK_BUTTON_LOAD_BYTES,
    CONTROL_BAR_CLICK_GATE_PREFIX: CONTROL_BAR_CLICK_GATE_PREFIX_BYTES,
    CONTROL_BAR_CLICK_GATE_SUFFIX: CONTROL_BAR_CLICK_GATE_SUFFIX_BYTES,
    CONTROL_BAR_COMMAND_DISPATCH: CONTROL_BAR_COMMAND_DISPATCH_BYTES,
    PLAYER_LIST_LOCAL_IS_NOT_ACTIVE: PLAYER_LIST_LOCAL_IS_NOT_ACTIVE_BYTES,
}


def build_code(base_va: int) -> bytes:
    """The replacement predicate: "is the local player sitting out", except for the two paging
    commands.

    Entry is the stock call's, unchanged: ``ecx`` already holds `ThePlayerList` and ``esi`` the
    `CommandButton` the click arrived on. The answer goes back in ``al`` for the caller's
    ``test al, al / jne`` - zero means active, which is the edge that dispatches.

    Only ``eax`` and the flags are touched, which the stock predicate clobbers anyway, and the
    refusing path tail-jumps rather than calling, so the thiscall shape and the return address
    the caller sees are identical to the stock ones."""
    a = Asm(base_va)
    for command, _handler, _bytes in PAGING_COMMANDS:
        a.emit(0x83, 0x7E, COMMAND_BUTTON_COMMAND, command)  # cmp dword [esi+0x14], <command>
        a.jcc(JE, "allow")
    a.jmp_absolute(PLAYER_LIST_LOCAL_IS_NOT_ACTIVE)  # anything else: ask the stock predicate

    a.label("allow")
    a.emit(0x32, 0xC0)  # xor al, al   ; "active" - let the click through
    a.emit(0xC3)  # ret
    return a.finish()


class ObserverCommandRangePatch(Patch):
    """Let an observer work a command bar's paging buttons, and nothing else on it."""

    name = "observer-command-range"
    author = "officialNecro"
    description = (
        "Let an observer click a command bar's PUSH_VISIBLE_COMMAND_RANGE and "
        "POP_VISIBLE_COMMAND_RANGE buttons, so the pages behind them can be read while watching "
        "a replay or after being defeated. Every other command stays refused. No INI change: the "
        "paging buttons are the ones the CommandSet already defines"
    )

    def apply(self, data: bytearray) -> None:
        gate_off = va_to_offset(data, CONTROL_BAR_CLICK_GATE_CALL)
        if gate_off is None:
            raise ValueError(
                f"{CONTROL_BAR_CLICK_GATE_CALL:#010x} is not mapped - not the expected build"
            )
        self._check_anchors(data)
        self._check_dispatch(data)
        section_va = allocate_section(data, SECTION_NAME, build_code, _CHARACTERISTICS)
        apply_byte_patch(
            data,
            gate_off,
            CONTROL_BAR_CLICK_GATE_CALL_BYTES,
            _call_bytes(CONTROL_BAR_CLICK_GATE_CALL, section_va),
            "processCommandUI observer gate -> observer-command-range cave",
        )

    def verify(self, data: bytes | bytearray) -> list[str]:
        problems: list[str] = []
        located = find_section(data, SECTION_NAME)
        if located is None:
            return [f"{SECTION_NAME} section is absent"]
        section_va, section_off, _vsize = located

        gate_off = va_to_offset(data, CONTROL_BAR_CLICK_GATE_CALL)
        if gate_off is None:
            return [f"{CONTROL_BAR_CLICK_GATE_CALL:#010x} is not mapped by any section"]
        expected = _call_bytes(CONTROL_BAR_CLICK_GATE_CALL, section_va)
        got = bytes(data[gate_off : gate_off + len(expected)])
        if got != expected:
            problems.append(
                f"the click gate at {CONTROL_BAR_CLICK_GATE_CALL:#010x} calls {got.hex()}, "
                f"expected {expected.hex()} - the hook is not installed"
            )

        code = build_code(section_va)
        if bytes(data[section_off : section_off + len(code)]) != code:
            problems.append(f"the {SECTION_NAME} cave does not hold the expected predicate")

        for va, anchor in ANCHORS.items():
            off = va_to_offset(data, va)
            if off is None or bytes(data[off : off + len(anchor)]) != anchor:
                problems.append(
                    f"{va:#010x} is not {anchor.hex()} - the click path is not this build's"
                )
        problems.extend(self._dispatch_problems(data))
        return problems

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
                    "click path is not this build's, so the cave would read the wrong pointer "
                    "or hand its answer to something else"
                )

    @classmethod
    def _check_dispatch(cls, data: bytes | bytearray) -> None:
        problems = cls._dispatch_problems(data)
        if problems:
            raise ValueError("; ".join(problems))

    @staticmethod
    def _dispatch_problems(data: bytes | bytearray) -> list[str]:
        """Walk the executor's two-level switch and check each whitelisted command still reaches
        its paging handler.

        This is what stops the patch from waving a command through on the strength of a number
        read out of a name table: the number is only right if the executor actually sends it to
        the code that pushes or pops a visible range, so that is what gets asserted."""
        problems: list[str] = []
        index_off = va_to_offset(data, CONTROL_BAR_COMMAND_INDEX_TABLE)
        jump_off = va_to_offset(data, CONTROL_BAR_COMMAND_JUMP_TABLE)
        if index_off is None or jump_off is None:
            return ["the click executor's switch tables are not mapped - not the expected build"]

        for command, handler, head in PAGING_COMMANDS:
            slot = data[index_off + command - 1]  # the switch indexes on `command - 1`
            target = struct.unpack_from("<I", data, jump_off + slot * 4)[0]
            if target != handler:
                problems.append(
                    f"GUICOMMAND {command} dispatches to {target:#010x}, not {handler:#010x} - "
                    f"the paging commands are not numbered {command} in this binary"
                )
                continue
            handler_off = va_to_offset(data, handler)
            if handler_off is None or bytes(data[handler_off : handler_off + len(head)]) != head:
                problems.append(
                    f"the handler for GUICOMMAND {command} at {handler:#010x} does not open "
                    f"with {head.hex()} - it is not the paging code"
                )
        return problems
