"""Grey a summoning special power while the object it summons is at its `MaxSimultaneousOfType`.

The OCL `CreateObject` nugget refuses a spawn once the player already has `MaxSimultaneousOfType`
of the template, but nothing tells the button: the power stays clickable, the cast goes through,
the recharge is spent and nothing appears. With this patch a `SPECIAL_POWER` button that names the
capped object in its `Object` field is unavailable while the player is at the cap:

    CommandButton Command_SummonEnts
        Command      = SPECIAL_POWER
        SpecialPower = SpellBookSummonEnts
        Object       = ElvenEnt
    End

The count is the engine's own (`Player::countObjectsByThingTemplate`, called exactly as the OCL
calls it), so the button and the spawn agree. A power still recharging keeps its clock; the cap
only replaces "ready". The click is refused too, so a hotkey cannot cast it. Client-side only.

Derivation: `../docs/special-power-object-cap.md`.
"""

from __future__ import annotations

from ..addresses import (
    COMMAND_BUTTON_COMMAND,
    COMMAND_BUTTON_GET_THING_TEMPLATE,
    COMMAND_BUTTON_GET_THING_TEMPLATE_ENTRY,
    CONTROL_BAR_DO_COMMAND_COMMAND_LOAD,
    CONTROL_BAR_DO_COMMAND_COMMAND_LOAD_BYTES,
    CONTROL_BAR_DO_COMMAND_REFUSE,
    CONTROL_BAR_DO_COMMAND_REFUSE_BYTES,
    CONTROL_BAR_DO_COMMAND_SPECIAL_POWER_DISPATCH,
    CONTROL_BAR_DO_COMMAND_SPECIAL_POWER_DISPATCH_BYTES,
    CONTROL_BAR_DO_COMMAND_SPECIAL_POWER_DISPATCH_RESUME,
    CONTROL_BAR_DO_COMMAND_SPECIAL_POWER_GATE,
    CONTROL_BAR_SPECIAL_POWER_READY,
    CONTROL_BAR_SPECIAL_POWER_READY_BYTES,
    CONTROL_BAR_SPECIAL_POWER_READY_RESUME,
    CONTROL_BAR_SPECIAL_POWER_READY_TEST,
    CONTROL_BAR_SPECIAL_POWER_READY_TEST_BYTES,
    CONTROL_BAR_UNAVAILABLE,
    GUI_COMMAND_SPECIAL_POWER,
    OBJECT_GET_CONTROLLING_PLAYER,
    OBJECT_GET_CONTROLLING_PLAYER_ENTRY,
    OCL_CREATE_OBJECT_CAP_TEST,
    OCL_CREATE_OBJECT_CAP_TEST_BYTES,
    PLAYER_COUNT_OBJECTS_BY_THING_TEMPLATE,
    PLAYER_COUNT_OBJECTS_BY_THING_TEMPLATE_ENTRY,
    PLAYER_LIST_GET_LOCAL_PLAYER,
    THE_PLAYER_LIST,
    THING_TEMPLATE_MAX_SIMULTANEOUS_OF_TYPE,
)
from ..asm import JB, JE, JNE, Asm
from ..patcher import Patch
from ..utils import allocate_section, apply_byte_patch, file_offset, find_section, jmp_rel32, u32

__all__ = [
    "ANCHORS",
    "HOOKS",
    "ROUTINES",
    "SECTION_NAME",
    "SpecialPowerObjectCapPatch",
    "build_code",
    "entry_points",
]

SECTION_NAME = ".spcap"

# CNT_CODE | MEM_EXECUTE | MEM_READ.
_CHARACTERISTICS = 0x20 | 0x20000000 | 0x40000000

#: `{hook va: (stock bytes, routine)}`. Each window is replaced by a `jmp` to its routine.
HOOKS: dict[int, tuple[bytes, str]] = {
    CONTROL_BAR_SPECIAL_POWER_READY: (CONTROL_BAR_SPECIAL_POWER_READY_BYTES, "available"),
    CONTROL_BAR_DO_COMMAND_SPECIAL_POWER_DISPATCH: (
        CONTROL_BAR_DO_COMMAND_SPECIAL_POWER_DISPATCH_BYTES,
        "click",
    ),
}

#: Read, never rewritten: the routines the cave calls, the exits it jumps to, the instructions
#: that fix which register holds what at each hook, and the OCL test whose rule the cave copies.
ANCHORS: dict[int, bytes] = {
    COMMAND_BUTTON_GET_THING_TEMPLATE: COMMAND_BUTTON_GET_THING_TEMPLATE_ENTRY,
    OBJECT_GET_CONTROLLING_PLAYER: OBJECT_GET_CONTROLLING_PLAYER_ENTRY,
    PLAYER_LIST_GET_LOCAL_PLAYER: bytes.fromhex("568b711085f6"),
    PLAYER_COUNT_OBJECTS_BY_THING_TEMPLATE: PLAYER_COUNT_OBJECTS_BY_THING_TEMPLATE_ENTRY,
    PLAYER_COUNT_OBJECTS_BY_THING_TEMPLATE + 0x47: bytes.fromhex("c21400"),
    OCL_CREATE_OBJECT_CAP_TEST: OCL_CREATE_OBJECT_CAP_TEST_BYTES,
    # The module-ready test whose `jne` reaches the first hook, and what follows the window: the
    # model-condition gate taking (button = edi, object = ebx).
    CONTROL_BAR_SPECIAL_POWER_READY_TEST: CONTROL_BAR_SPECIAL_POWER_READY_TEST_BYTES,
    CONTROL_BAR_SPECIAL_POWER_READY_RESUME: bytes.fromhex("e8afeeffff"),
    CONTROL_BAR_UNAVAILABLE: bytes.fromhex("33c0e991f3ffff"),
    # `mov eax, [esi+0x14]` ahead of the second hook, the gate it dispatches to, and the exit.
    CONTROL_BAR_DO_COMMAND_COMMAND_LOAD: CONTROL_BAR_DO_COMMAND_COMMAND_LOAD_BYTES,
    CONTROL_BAR_DO_COMMAND_SPECIAL_POWER_GATE: bytes.fromhex("85db"),
    CONTROL_BAR_DO_COMMAND_REFUSE: CONTROL_BAR_DO_COMMAND_REFUSE_BYTES,
}

#: The cave's routines, in layout order. `capped` is shared; the other two are hook targets.
ROUTINES = ("capped", "available", "click")


def _assemble(base_va: int) -> Asm:
    a = Asm(base_va)

    # capped: stdcall(button, player) -> eax non-zero when the button is a SPECIAL_POWER whose
    # `Object` has a MaxSimultaneousOfType the player has reached. `ret 8`; keeps ebx/esi/edi.
    # Frame: [ebp-0xc] the template (the one-element array the count takes), [ebp-0x10] the count.
    a.label("capped")
    a.emit(0x55)  # push ebp
    a.emit(0x8B, 0xEC)  # mov ebp, esp
    a.emit(0x56, 0x57)  # push esi / push edi
    a.emit(0x83, 0xEC, 0x08)  # sub esp, 8
    a.emit(0x33, 0xFF)  # xor edi, edi                    ; the answer: not capped
    a.emit(0x8B, 0x75, 0x0C)  # mov esi, [ebp+0xc]        ; the player
    a.emit(0x85, 0xF6)  # test esi, esi
    a.jcc(JE, "cp_out")
    a.emit(0x8B, 0x4D, 0x08)  # mov ecx, [ebp+8]          ; the button
    a.emit(0x85, 0xC9)  # test ecx, ecx
    a.jcc(JE, "cp_out")
    a.emit(0x83, 0x79, COMMAND_BUTTON_COMMAND, GUI_COMMAND_SPECIAL_POWER)  # cmp [ecx+0x14], 0x18
    a.jcc(JNE, "cp_out")
    a.call_absolute(COMMAND_BUTTON_GET_THING_TEMPLATE)  # the button's `Object`, or null
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "cp_out")
    a.emit(0x66, 0x83, 0xB8, u32(THING_TEMPLATE_MAX_SIMULTANEOUS_OF_TYPE), 0x00)  # cmp word [..], 0
    a.jcc(JE, "cp_out")  # no cap
    a.emit(0x89, 0x45, 0xF4)  # mov [ebp-0xc], eax
    # The OCL's own call: (1, &tmpl, ignoreDead = 1, &count, ignoreUnderConstruction = 0).
    a.emit(0x6A, 0x00)  # push 0
    a.emit(0x8D, 0x45, 0xF0)  # lea eax, [ebp-0x10]
    a.emit(0x50)  # push eax
    a.emit(0x6A, 0x01)  # push 1
    a.emit(0x8D, 0x45, 0xF4)  # lea eax, [ebp-0xc]
    a.emit(0x50)  # push eax
    a.emit(0x6A, 0x01)  # push 1
    a.emit(0x8B, 0xCE)  # mov ecx, esi
    a.call_absolute(PLAYER_COUNT_OBJECTS_BY_THING_TEMPLATE)
    a.emit(0x8B, 0x45, 0xF4)  # mov eax, [ebp-0xc]
    a.emit(0x0F, 0xB7, 0x88, u32(THING_TEMPLATE_MAX_SIMULTANEOUS_OF_TYPE))  # movzx ecx, word [..]
    a.emit(0x39, 0x4D, 0xF0)  # cmp [ebp-0x10], ecx     ; the OCL spawns while count < max
    a.jcc(JB, "cp_out")
    a.emit(0x47)  # inc edi                               ; at the cap
    a.label("cp_out")
    a.emit(0x8B, 0xC7)  # mov eax, edi
    a.emit(0x8D, 0x65, 0xF8)  # lea esp, [ebp-8]
    a.emit(0x5F, 0x5E)  # pop edi / pop esi
    a.emit(0x5D)  # pop ebp
    a.emit(0xC2, 0x08, 0x00)  # ret 8

    # available: the availability evaluator, a SPECIAL_POWER whose module is ready. edi is the
    # button, ebx the object (never null here). At the cap, answer the evaluator's "unavailable".
    a.label("available")
    a.emit(0x60)  # pushad
    a.emit(0x8B, 0xCB)  # mov ecx, ebx
    a.call_absolute(OBJECT_GET_CONTROLLING_PLAYER)  # whose objects the OCL would count
    a.emit(0x50)  # push eax                              ; the player
    a.emit(0x57)  # push edi                              ; the button
    a.call("capped")
    a.emit(0x85, 0xC0)  # test eax, eax
    a.emit(0x61)  # popad                                 ; keeps the flags
    a.jcc(JNE, "av_refuse")
    a.emit(CONTROL_BAR_SPECIAL_POWER_READY_BYTES)  # mov ecx,[ebp-0x14]; push ebx; push edi
    a.jmp_absolute(CONTROL_BAR_SPECIAL_POWER_READY_RESUME)
    a.label("av_refuse")
    a.jmp_absolute(CONTROL_BAR_UNAVAILABLE)

    # click: doCommand, eax the button's command, esi the button, ebx the context object or null.
    # A capped SPECIAL_POWER leaves doCommand as a refused click does, before anything is posted.
    a.label("click")
    a.emit(0x83, 0xF8, GUI_COMMAND_SPECIAL_POWER)  # cmp eax, 0x18
    a.jcc(JNE, "ck_stock")
    a.emit(0x60)  # pushad
    a.emit(0x85, 0xDB)  # test ebx, ebx
    a.jcc(JE, "ck_local")
    a.emit(0x8B, 0xCB)  # mov ecx, ebx
    a.call_absolute(OBJECT_GET_CONTROLLING_PLAYER)
    a.jmp("ck_ask")
    a.label("ck_local")
    a.emit(0x8B, 0x0D, u32(THE_PLAYER_LIST))  # mov ecx, [ThePlayerList]
    a.call_absolute(PLAYER_LIST_GET_LOCAL_PLAYER)
    a.label("ck_ask")
    a.emit(0x50)  # push eax                              ; the player
    a.emit(0x56)  # push esi                              ; the button
    a.call("capped")
    a.emit(0x85, 0xC0)  # test eax, eax
    a.emit(0x61)  # popad
    a.jcc(JNE, "ck_refuse")
    a.jmp_absolute(CONTROL_BAR_DO_COMMAND_SPECIAL_POWER_GATE)  # the stock `je` taken
    a.label("ck_stock")
    a.jmp_absolute(CONTROL_BAR_DO_COMMAND_SPECIAL_POWER_DISPATCH_RESUME)
    a.label("ck_refuse")
    a.jmp_absolute(CONTROL_BAR_DO_COMMAND_REFUSE)
    return a


def build_code(base_va: int) -> bytes:
    """The cave's three routines, laid out at the address they will occupy."""
    return _assemble(base_va).finish()


def entry_points(base_va: int) -> dict[str, int]:
    a = _assemble(base_va)
    return {name: a.label_va(name) for name in ROUTINES}


def _check(data: bytes | bytearray, va: int, expected: bytes) -> None:
    off = file_offset(data, va)
    got = bytes(data[off : off + len(expected)])
    if got != expected:
        raise ValueError(
            f"{va:#010x} holds {got.hex()}, expected {expected.hex()} - the file is not the "
            "expected build, or already carries this patch"
        )


class SpecialPowerObjectCapPatch(Patch):
    name = "special-power-object-cap"
    author = "ClementJ18"
    description = (
        "Grey a SPECIAL_POWER CommandButton, and refuse its click, while the player already has "
        "MaxSimultaneousOfType of the object named by the button's Object field - the cap at which "
        "the power's OCL silently spawns nothing. Write Object = <the summoned unit> on the "
        "button. A recharging power keeps its clock. Client-side only"
    )

    def apply(self, data: bytearray) -> None:
        if find_section(data, SECTION_NAME) is not None:
            raise ValueError(f"the file already carries a {SECTION_NAME} section")
        for va, expected in ANCHORS.items():
            _check(data, va, expected)
        for va, (stock, _routine) in HOOKS.items():
            _check(data, va, stock)
        base_va = allocate_section(data, SECTION_NAME, build_code, _CHARACTERISTICS)
        routines = entry_points(base_va)
        for va, (stock, routine) in HOOKS.items():
            apply_byte_patch(
                data,
                file_offset(data, va),
                stock,
                jmp_rel32(va, routines[routine], len(stock)),
                f"{va:#010x} -> the {SECTION_NAME} {routine} routine",
            )

    def verify(self, data: bytes | bytearray) -> list[str]:
        located = find_section(data, SECTION_NAME)
        if located is None:
            return [f"no {SECTION_NAME} section: the file does not carry this patch"]
        base_va, section_off, vsize = located
        problems: list[str] = []
        expected = build_code(base_va)
        got = bytes(data[section_off : section_off + len(expected)])
        if vsize < len(expected) or got != expected:
            problems.append(f"the {SECTION_NAME} cave is not the one this patch builds")
        routines = entry_points(base_va)
        for va, (stock, routine) in HOOKS.items():
            new = jmp_rel32(va, routines[routine], len(stock))
            off = file_offset(data, va)
            here = bytes(data[off : off + len(new)])
            if here != new:
                problems.append(f"@{va:#010x}: the {routine} hook is not installed")
        return problems
