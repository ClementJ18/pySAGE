"""`OK_FOR_MULTI_EXECUTE` honours each unit's own `EnableOnModelCondition` /
`DisableOnModelCondition`.

Targets the ROTWK SAGE-engine `game.dat` build ``2.01.2614.37001``. Every address below is derived
in ``../docs/multi-execute-gate.md``.

**What the engine does today.** A `CommandButton`'s `EnableOnModelCondition` /
`DisableOnModelCondition` are evaluated by exactly one routine, `MODEL_CONDITION_GATE_VA`, which
takes *one* button and *one* `Object` and answers 2 (fine) or 3 (disabled). The ControlBar calls it
per object; with several units selected it walks the selection and lights the button if **any**
member comes back available - which is the right answer for whether to draw the button.

The click is where it goes wrong. A `Command = SPECIAL_POWER` button emits `MSG_DO_SPECIAL_POWER`
carrying the special power's id, the button's `Options` word and an object id of **zero**, and the
logic-side handler turns a zero into *the issuing player's whole selection* as an `AIGroup`. If bit
20 of that options word - `OK_FOR_MULTI_EXECUTE` - is set, `AIGroup::doSpecialPower` skips its
"pick the best member" pass and runs the power on every member in turn. The only per-member gate on
that loop is `GATE_A_VA`, which checks the power's own preconditions: required sciences, `UnitCost`
against the horde's size, the module's recharge. **It never sees the `CommandButton`** - it is
handed a `SpecialPowerTemplate` - so the model conditions that greyed the button on some of those
units are not consulted, and the power fires on all of them.

That is why Edain's *Ambush of the Wood-elves* is gated by a command-set swap rather than by the
`EnableOnModelCondition = INVISIBLE_CAMOUFLAGE` its button already declares: with a mixed group,
one stealthed battalion is enough to fire the ambush on every battalion selected. The swap is the
workaround, and it costs the player the mass trigger - battalions have to be clicked one at a time.

**What this patch does.** It adds the missing per-member check to the two group loops, and nothing
else. The button stays `OK_FOR_MULTI_EXECUTE`, the ControlBar still lights it when any member
qualifies, and the loop still visits every member - a member whose *own* command button is disabled
by a model condition is simply skipped, exactly as if it had failed the recharge check.

Recovering the button is what makes this possible without touching the message. The logic side
already knows how: `GET_COMMAND_SET_STRING_VA` resolves an `Object`'s effective command-set name
(honouring the three per-object overrides a command-set swap writes, so a swapped set is the set
this reads), `FIND_COMMAND_SET_VA` looks it up, and `GET_COMMAND_BUTTON_VA` indexes it. The engine
performs that exact walk in two places already; this cave is a third, matching on
``Command == SPECIAL_POWER`` and on the button's `SpecialPower` resolving to the same template id
the group was told to run. A member with no such button is left alone.

Coverage
--------
Two hooks, one per group loop:

* `GATE_A_CALL_VA`, inside `AIGroup::doSpecialPower` - the targetless form, behind
  `MSG_DO_SPECIAL_POWER`. This is the one *Ambush of the Wood-elves* takes.
* `GATE_B_CALL_VA`, inside `AIGroup::doSpecialPowerAt*` - the targeted forms, behind
  `MSG_DO_SPECIAL_POWER_AT_LOCATION` / `..._AT_OBJECT`.

Both are the ``call <precondition gate>`` that opens the loop body, and both loops already treat a
false answer as "skip this member and continue" - so the shim needs no new control flow, only a
reason to answer false.

The **single-member** paths in the same two functions (the "best member" the engine picks when
`OK_FOR_MULTI_EXECUTE` is *absent*) are deliberately left stock. Gating them could turn a click
that works today into one that silently does nothing, because the scoring pass that chose the
member does not know about model conditions and would not fall through to another candidate. That
is a real second gap, but it is not this patch's, and fixing it means replacing the scoring pass
rather than filtering it.

**Every peer must run the same patched binary.** This changes which objects a logic-side order
reaches, so a patched and an unpatched client diverge on the first multi-execute activation of a
model-conditioned button, and replays do not cross. That is stricter than the client-local patches
in this package (`replay-outcome`, `skirmish-replay`) and the same requirement
`production-condition` carries.

**Composition.** The cave is allocated with :func:`~..utils.allocate_section` past every existing
section and :meth:`verify` finds it by name; the four bytes rewritten (two ``call rel32``
displacements) are shared with no other bundled patch. One ordered dependency, per rule 3 of the
composition contract on :class:`~..patcher.Patch`: the cave walks a `CommandSet`'s slot array to a
literal bound, and `commandset-limit` is what decides how many slots there are. ``slots=None`` (the
default) reads that bound out of the image at apply time, so **apply `commandset-limit` first** and
this patch follows it automatically; pass ``--slots N`` to pin it instead. Get it wrong and nothing
corrupts - a button sitting past the bound is simply not found, and that member takes the stock
path - but `verify` will report the disagreement.
"""

from __future__ import annotations

import struct
from typing import TYPE_CHECKING

from ..addresses import GET_FINAL_OVERRIDE, GUI_COMMAND_SPECIAL_POWER
from ..asm import JE, JL, JNE, Asm
from ..patcher import Patch
from ..utils import allocate_section, apply_byte_patch, find_section, va_to_offset
from .commandset import CommandSetLimitPatch

if TYPE_CHECKING:
    import argparse

__all__ = [
    "COMMAND_BUTTON_SPECIAL_POWER_OFFSET",
    "DISABLED",
    "FIND_COMMAND_SET_VA",
    "GATE_A_CALL_VA",
    "GATE_A_VA",
    "GATE_A_WINDOW",
    "GATE_B_CALL_VA",
    "GATE_B_VA",
    "GATE_B_WINDOW",
    "GET_COMMAND_BUTTON_VA",
    "GET_COMMAND_SET_STRING_VA",
    "MODEL_CONDITION_GATE_VA",
    "MODEL_CONDITION_GATE_WINDOW",
    "MULTI_EXECUTE_BIT",
    "MULTI_EXECUTE_WINDOWS",
    "SECTION_NAME",
    "SPECIAL_POWER_ID_OFFSET",
    "STOCK_SLOTS",
    "THE_CONTROL_BAR_VA",
    "MultiExecuteGatePatch",
    "build_gate",
    "build_thunk",
]

# --- the two group loops (VA, ImageBase 0x400000) ---------------------------------------------

#: `AIGroup::doSpecialPower`'s per-member precondition gate, and the ``call`` to it that opens the
#: multi-execute loop body. The gate is ``__thiscall`` with five stack arguments (`Object*`,
#: `SpecialPowerTemplate*`, 0, the button options, a "check recharge" bool) and cleans them itself.
GATE_A_VA = 0x0082D5DA
GATE_A_CALL_VA = 0x0076F6DA
GATE_A_ARG_BYTES = 0x14
#: Where the `Object*` and the `SpecialPowerTemplate*` sit relative to ``esp`` at the call.
GATE_A_OBJECT_ESP = 0x04
GATE_A_TEMPLATE_ESP = 0x08

#: `AIGroup::doSpecialPowerAtLocation` / `...AtObject`'s equivalent: six arguments, with the
#: template fourth rather than second.
GATE_B_VA = 0x0082D925
GATE_B_CALL_VA = 0x00770B67
GATE_B_ARG_BYTES = 0x18
GATE_B_OBJECT_ESP = 0x04
GATE_B_TEMPLATE_ESP = 0x10

#: The 30- and 29-byte runs the two hooks sit inside: the singleton load, every pushed argument,
#: the ``call`` itself and the ``test al,al`` / ``je <loop tail>`` that turns a false answer into a
#: skip. A bare ``call rel32`` says nothing about which call it is; this pins the whole shape, so a
#: build whose layout moved fails before anything is written.
GATE_A_WINDOW = (
    0x0076F6C9,
    bytes.fromhex("8b0da88bde006a01ff750c6a00ff75fc56e8fbde0b0084c0742133db53ff"),
)
GATE_B_WINDOW = (
    0x00770B54,
    bytes.fromhex("ff75e48b0da88bde00ff7510536a00ff750c56e8b9cd0b0084c074196a"),
)

#: ``OK_FOR_MULTI_EXECUTE`` is index 20 of the `CommandButton` `Options` name table at
#: ``0x00DA4C88``, which the shared bit-string parser turns into ``1 << 20``.
MULTI_EXECUTE_BIT = 1 << 20

#: The two ``and eax, 0x100000`` sites that read that bit off the message's options word - one per
#: group function, and the whole of the engine's use of the flag. They are asserted rather than
#: rewritten: they are what make the loops this patch hooks the *multi-execute* loops, and nothing
#: else in the image tests bit 20 of anything.
MULTI_EXECUTE_WINDOWS = (
    (0x0076F5FA, bytes.fromhex("8b450c33ff2500001000897d088945f4")),
    (0x007709BA, bytes.fromhex("8b451025000010008945e0")),
)

# --- what the cave calls -----------------------------------------------------------------------

#: The one routine that evaluates a `CommandButton`'s `DisableOnModelCondition` and then its
#: `EnableOnModelCondition` against an `Object`'s model-condition mask. ``stdcall(button, object)``,
#: ``ret 8``, answering :data:`DISABLED` or :data:`AVAILABLE`. It pushes and pops ``ebx``/``esi``/
#: ``edi``, so the cave can hold its loop state across the call.
MODEL_CONDITION_GATE_VA = 0x00942490
MODEL_CONDITION_GATE_WINDOW = (
    MODEL_CONDITION_GATE_VA,
    bytes.fromhex("5356578b7c24108db7e00100008bcee8df12b7ff84c08b5c24147410568d8b0c"),
)
DISABLED = 3
AVAILABLE = 2

#: `Object::getCommandSetString` - ``__thiscall``, no arguments, returning the `AsciiString*` of the
#: object's *effective* command set: the first non-empty of the three per-object override strings at
#: ``+0x438`` / ``+0x440`` / ``+0x43C``, else its `ThingTemplate`'s own ``CommandSet`` at ``+0x70``.
#: A command-set swap writes those overrides, so this is the set the player is actually looking at.
GET_COMMAND_SET_STRING_VA = 0x0069156B

#: `ControlBar::findCommandSet(AsciiString*)` - ``__thiscall``, ``ret 4``, 0 when the name is
#: unknown. `TheControlBar` is the singleton the ControlBar registers itself in.
FIND_COMMAND_SET_VA = 0x0071EFA2
THE_CONTROL_BAR_VA = 0x00DE7744

#: `CommandSet::getCommandButton(i)` - ``__thiscall``, ``ret 4``, a bare unchecked
#: ``[this + i*4 + 0x14]``. The caller owns the bound; see :data:`STOCK_SLOTS`.
GET_COMMAND_BUTTON_VA = 0x0080C837

#: `CommandButton` members the cave reads: the GUI command it dispatches on (compared against
#: :data:`~..addresses.GUI_COMMAND_SPECIAL_POWER`) and the `SpecialPowerTemplate*` it names.
COMMAND_BUTTON_GUI_COMMAND_OFFSET = 0x14
COMMAND_BUTTON_SPECIAL_POWER_OFFSET = 0x44
#: `SpecialPowerTemplate::m_id` - what the message carries and what the store resolves back, so
#: matching on it is immune to whether either side is a base template or an override copy.
SPECIAL_POWER_ID_OFFSET = 0x14

#: `MAX_COMMANDS_PER_COMMAND_SET` in the stock build; `commandset-limit` raises it.
STOCK_SLOTS = 33

SECTION_NAME = ".mxgate"
# CNT_CODE | CNT_INITIALIZED_DATA | MEM_EXECUTE | MEM_READ
SECTION_CHARACTERISTICS = 0x60000060


def _call_bytes(from_va: int, to_va: int) -> bytes:
    """The five bytes of ``call rel32`` sited at ``from_va``."""
    return b"\xe8" + struct.pack("<i", to_va - (from_va + 5))


# --- the cave ----------------------------------------------------------------------------------


def build_gate(base_va: int, slots: int = STOCK_SLOTS) -> bytes:
    """``bool gate(Object *obj, SpecialPowerTemplate *tmpl)`` - cdecl, caller cleans.

    False iff ``obj``'s own command set carries a `SPECIAL_POWER` button for ``tmpl`` **and** that
    button's model conditions disable it. Everything else - no command set, no matching button, an
    empty pair of masks - answers true, which is the stock behaviour.

    The match is on the special power's **id** rather than on the template pointer, because the two
    sides reach it differently: the loop's template came from the store by id, while the button
    names one that may be an INI override copy. Resolving the button's through
    :data:`~..addresses.GET_FINAL_OVERRIDE` and comparing ids is what the ControlBar itself does.

    All four callees are ``__thiscall`` or ``stdcall`` and preserve ``ebx``/``esi``/``edi``, so the
    slot index, the `CommandSet` and the candidate button live in registers for the whole walk."""
    a = Asm(base_va)
    a.emit(0x55)  # push ebp
    a.emit(b"\x8b\xec")  # mov ebp, esp
    a.emit(0x53, 0x56, 0x57)  # push ebx / push esi / push edi

    a.emit(b"\x8b\x4d\x08")  # mov ecx, [ebp+8]        ; the Object
    a.call_absolute(GET_COMMAND_SET_STRING_VA)  # call <getCommandSetString> ; eax = AsciiString*
    a.emit(b"\x8b\x0d", struct.pack("<I", THE_CONTROL_BAR_VA))  # mov ecx, [TheControlBar]
    a.emit(b"\x85\xc9")  # test ecx, ecx
    a.jcc(JE, "allow")  # je .allow               ; no ControlBar -> stock
    a.emit(0x50)  # push eax
    a.call_absolute(FIND_COMMAND_SET_VA)  # call <findCommandSet>   ; ret 4
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc(JE, "allow")  # je .allow               ; unknown set -> stock
    a.emit(b"\x8b\xf0")  # mov esi, eax            ; the CommandSet
    a.emit(b"\x33\xdb")  # xor ebx, ebx            ; slot = 0

    a.label("next")
    a.emit(0x53)  # push ebx
    a.emit(b"\x8b\xce")  # mov ecx, esi
    a.call_absolute(GET_COMMAND_BUTTON_VA)  # call <getCommandButton> ; ret 4
    a.emit(b"\x8b\xf8")  # mov edi, eax            ; the candidate button
    a.emit(b"\x85\xff")  # test edi, edi
    a.jcc(JE, "step")  # je .step                ; empty slot
    a.emit(b"\x83\x7f", COMMAND_BUTTON_GUI_COMMAND_OFFSET, GUI_COMMAND_SPECIAL_POWER)
    a.jcc(JNE, "step")  # jne .step               ; not a SPECIAL_POWER button
    a.emit(b"\x8b\x4f", COMMAND_BUTTON_SPECIAL_POWER_OFFSET)  # mov ecx, [edi+0x44]
    a.emit(b"\x85\xc9")  # test ecx, ecx
    a.jcc(JE, "step")  # je .step                ; names no power
    a.call_absolute(GET_FINAL_OVERRIDE)  # call <getFinalOverride>
    a.emit(b"\x8b\x40", SPECIAL_POWER_ID_OFFSET)  # mov eax, [eax+0x14]  ; the button's power id
    a.emit(b"\x8b\x4d\x0c")  # mov ecx, [ebp+0xc]      ; the template
    a.emit(b"\x3b\x41", SPECIAL_POWER_ID_OFFSET)  # cmp eax, [ecx+0x14]
    a.jcc(JNE, "step")  # jne .step               ; a different power

    a.emit(b"\xff\x75\x08")  # push dword [ebp+8]      ; arg2 = the Object
    a.emit(0x57)  # push edi                ; arg1 = the button
    a.call_absolute(MODEL_CONDITION_GATE_VA)  # call <model-condition gate> ; ret 8
    a.emit(b"\x83\xf8", DISABLED)  # cmp eax, 3
    a.jcc(JNE, "allow")  # jne .allow
    a.emit(b"\x32\xc0")  # xor al, al             ; disabled on this unit
    a.jmp("done")

    a.label("step")
    a.emit(0x43)  # inc ebx
    a.emit(b"\x83\xfb", slots)  # cmp ebx, <slots>
    a.jcc(JL, "next")  # jl .next

    a.label("allow")
    a.emit(b"\xb0\x01")  # mov al, 1

    a.label("done")
    a.emit(0x5F, 0x5E, 0x5B)  # pop edi / pop esi / pop ebx
    a.emit(0x5D)  # pop ebp
    a.emit(0xC3)  # ret
    return a.finish()


def build_thunk(
    base_va: int,
    gate_va: int,
    stock_va: int,
    arg_bytes: int,
    object_esp: int,
    template_esp: int,
) -> bytes:
    """The shim a hooked ``call <precondition gate>`` lands in.

    On entry the stock gate's arguments are already pushed and ``ecx`` holds its ``this``, so the
    shim borrows the two it needs off the stack, asks :func:`build_gate`, and either refuses - which
    means cleaning the arguments itself, since the stock gate is the one that would have - or
    tail-jumps to the stock gate so its own ``ret <arg_bytes>`` returns straight to the loop.

    ``object_esp`` and ``template_esp`` are the arguments' displacements from ``esp`` at the call,
    which differ between the two loops: the targetless gate takes the template second and the
    targeted one takes it fourth."""
    a = Asm(base_va)
    a.emit(0x51)  # push ecx                     ; save the gate's `this`
    # +4 for the saved ecx, then +4 again for the template already pushed.
    a.emit(b"\xff\x74\x24", template_esp + 4)  # push dword [esp+N]  ; the SpecialPowerTemplate
    a.emit(b"\xff\x74\x24", object_esp + 8)  # push dword [esp+N]    ; the Object
    a.call_absolute(gate_va)  # call <gate>
    a.emit(b"\x83\xc4\x08")  # add esp, 8
    a.emit(0x59)  # pop ecx
    a.emit(b"\x84\xc0")  # test al, al
    a.jcc(JNE, "stock")  # jne .stock                   ; allowed -> the stock gate
    a.emit(b"\x32\xc0")  # xor al, al                   ; refuse: skip this member
    a.emit(0xC2, struct.pack("<H", arg_bytes))  # ret <arg_bytes>
    a.label("stock")
    a.jmp_absolute(stock_va)  # jmp <stock gate>
    return a.finish()


# --- the patch ---------------------------------------------------------------------------------


class MultiExecuteGatePatch(Patch):
    """Skip members whose own command button is model-condition disabled when a group runs a
    special power under `OK_FOR_MULTI_EXECUTE`."""

    name = "multi-execute-gate"
    description = "OK_FOR_MULTI_EXECUTE respects each unit's Enable/DisableOnModelCondition"

    def __init__(self, slots: int | None = None):
        if slots is not None and not 1 <= slots <= 127:
            raise ValueError(f"slots must be in 1..127, got {slots}")
        self.slots = slots

    def __str__(self) -> str:
        pinned = "auto" if self.slots is None else str(self.slots)
        return f"{self.name} (slots={pinned})"

    # --- apply / verify ----------------------------------------------------------------------

    def apply(self, data: bytearray) -> None:
        self._check_anchors(data)
        slots = self._resolve_slots(data)
        section_va = allocate_section(
            data,
            SECTION_NAME,
            lambda va: self._compute_section(va, slots)[0],
            SECTION_CHARACTERISTICS,
        )
        _content, thunks = self._compute_section(section_va, slots)
        for file_off, old, new, note in self._edits(data, thunks):
            apply_byte_patch(data, file_off, old, new, note)

    def verify(self, data: bytes | bytearray) -> list[str]:
        """Structural check that ``data`` carries this patch at this slot bound (an empty list ==
        verified). Recomputes the cave and both repointed ``call``s from the same inputs `apply`
        used and compares them to what is on disk, plus the four windows the patch reads but does
        not rewrite. Reads only via ``struct`` and the section table - no disassembler."""
        located = find_section(data, SECTION_NAME)
        if located is None:
            return [f"no {SECTION_NAME} section: the file does not carry this patch"]
        section_va, section_off, _vsize = located

        problems: list[str] = []
        try:
            slots = self._resolve_slots(data)
            content, thunks = self._compute_section(section_va, slots)
            edits = self._edits(data, thunks)
        except (ValueError, struct.error) as exc:
            return [f"cannot recompute the expected cave (wrong build?): {exc}"]

        got = bytes(data[section_off : section_off + len(content)])
        if got != content:
            problems.append(
                f"{SECTION_NAME} does not match a {slots}-slot walk "
                "(the gate or one of the two shims differs)"
            )

        for file_off, _old, new, note in edits:
            got = bytes(data[file_off : file_off + len(new)])
            if got != new:
                problems.append(f"{note} @0x{file_off:x}: expected {new.hex()}, got {got.hex()}")

        problems += self._anchor_problems(data, skip_call_bytes=True)
        return problems

    @classmethod
    def detect(cls, data: bytes | bytearray) -> MultiExecuteGatePatch | None:
        """Recognise this patch and recover its slot bound.

        The bound is not stored anywhere but the cave, and it is not a parameter someone picks
        freely - it is whatever `commandset-limit` left in the image. So detection re-derives it the
        same way `apply` did and asks `verify`, which means a binary whose `commandset-limit` was
        raised *after* this patch reports as unpatched rather than as patched-and-correct."""
        if find_section(data, SECTION_NAME) is None:
            return None
        try:
            patch = cls()
            problems = patch.verify(data)
        except (ValueError, KeyError, IndexError, TypeError, struct.error):
            return None
        return None if problems else patch

    # --- CLI integration ---------------------------------------------------------------------

    @classmethod
    def add_cli_arguments(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--slots",
            type=int,
            default=None,
            metavar="N",
            help=(
                "how many CommandSet slots the cave walks looking for the button. Default: read "
                f"out of the image ({STOCK_SLOTS} unless commandset-limit raised it), which is "
                "correct as long as commandset-limit is applied first"
            ),
        )

    @classmethod
    def from_cli_args(cls, args: argparse.Namespace) -> MultiExecuteGatePatch:
        return cls(slots=args.slots)

    # --- layout ------------------------------------------------------------------------------

    def _resolve_slots(self, data: bytes | bytearray) -> int:
        """The `CommandSet` slot bound the cave walks to: pinned, or read back out of the image."""
        if self.slots is not None:
            return self.slots
        raised = CommandSetLimitPatch.detect(data)
        return STOCK_SLOTS if raised is None else raised.count

    def _compute_section(self, section_va: int, slots: int) -> tuple[bytes, tuple[int, int]]:
        """Return ``(section content, (thunk A VA, thunk B VA))`` for a cave based at
        ``section_va``. The gate goes first so both shims can reach it by a resolved address."""
        gate = build_gate(section_va, slots)

        thunk_a_va = section_va + len(gate)
        thunk_a = build_thunk(
            thunk_a_va,
            section_va,
            GATE_A_VA,
            GATE_A_ARG_BYTES,
            GATE_A_OBJECT_ESP,
            GATE_A_TEMPLATE_ESP,
        )
        thunk_b_va = thunk_a_va + len(thunk_a)
        thunk_b = build_thunk(
            thunk_b_va,
            section_va,
            GATE_B_VA,
            GATE_B_ARG_BYTES,
            GATE_B_OBJECT_ESP,
            GATE_B_TEMPLATE_ESP,
        )
        return gate + thunk_a + thunk_b, (thunk_a_va, thunk_b_va)

    def _edits(
        self, data: bytes | bytearray, thunks: tuple[int, int]
    ) -> list[tuple[int, bytes, bytes, str]]:
        """Every byte range this patch rewrites, as ``(file offset, old, new, note)`` - two
        ``call rel32`` displacements, and nothing else."""
        thunk_a_va, thunk_b_va = thunks
        edits: list[tuple[int, bytes, bytes, str]] = []
        for call_va, stock_va, thunk_va, note in (
            (GATE_A_CALL_VA, GATE_A_VA, thunk_a_va, "AIGroup::doSpecialPower gate -> cave"),
            (GATE_B_CALL_VA, GATE_B_VA, thunk_b_va, "AIGroup::doSpecialPowerAt* gate -> cave"),
        ):
            off = va_to_offset(data, call_va)
            if off is None:
                raise ValueError(f"{note}: VA 0x{call_va:08x} is not mapped")
            edits.append(
                (
                    off,
                    _call_bytes(call_va, stock_va),
                    _call_bytes(call_va, thunk_va),
                    note,
                )
            )
        return edits

    # --- the build fingerprint ----------------------------------------------------------------

    def _anchor_problems(self, data: bytes | bytearray, skip_call_bytes: bool = False) -> list[str]:
        """Everything the patch depends on and does not rewrite.

        Four kinds, and all four are silent when wrong: the two loop windows say the hooks really
        are the per-member gate of a group loop, the two ``and eax, 0x100000`` sites say those loops
        really are the multi-execute ones, and the model-condition gate's own prologue says the
        routine the cave calls is still the one that reads the two masks.

        ``skip_call_bytes`` blanks the five bytes of the hooked ``call`` inside each loop window,
        which is what lets the same check run against an already-patched image."""
        problems: list[str] = []

        windows = [
            (GATE_A_WINDOW, GATE_A_CALL_VA, "AIGroup::doSpecialPower's per-member gate"),
            (GATE_B_WINDOW, GATE_B_CALL_VA, "AIGroup::doSpecialPowerAt*'s per-member gate"),
        ]
        for (va, expected), call_va, what in windows:
            off = va_to_offset(data, va)
            if off is None:
                problems.append(f"{what}: VA 0x{va:08x} is not mapped")
                continue
            got = bytearray(data[off : off + len(expected)])
            want = bytearray(expected)
            if skip_call_bytes:
                at = call_va - va
                got[at : at + 5] = want[at : at + 5] = b"\x00" * 5
            if bytes(got) != bytes(want):
                problems.append(
                    f"{what} @0x{va:08x}: expected {bytes(want).hex()}, got {bytes(got).hex()}"
                )

        checks = [
            *(
                (va, expected, "the multi-execute bit test")
                for va, expected in MULTI_EXECUTE_WINDOWS
            ),
            (*MODEL_CONDITION_GATE_WINDOW, "the model-condition gate"),
        ]
        for va, expected, what in checks:
            off = va_to_offset(data, va)
            if off is None:
                problems.append(f"{what}: VA 0x{va:08x} is not mapped")
                continue
            found = bytes(data[off : off + len(expected)])
            if found != expected:
                problems.append(f"{what} @0x{va:08x}: expected {expected.hex()}, got {found.hex()}")
        return problems

    def _check_anchors(self, data: bytes | bytearray) -> None:
        problems = self._anchor_problems(data)
        if problems:
            joined = "; ".join(problems)
            raise ValueError(f"this is not the expected build: {joined}")
