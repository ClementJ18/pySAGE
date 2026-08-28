"""The deploy-before-attack patch: `MustDeployToAttack` also gates an attack the AI starts.

Targets the ROTWK SAGE-engine `game.dat` build ``2.01.2614.37001``. Every address below is derived
in ``../docs/deploy-before-attack.md``.

**The defect.** `MustDeployToAttack` is read in exactly one place that decides anything:
`DeployStyleAIUpdate::update`'s `READY_TO_MOVE` arm, and that arm is reached only once the module
has a **recorded command** to resolve. A command is recorded only by `aiDoCommand`, so only an
order that travels as an `AICommandParms` makes a unit stand up - and almost nothing the engine
starts on its own travels that way. A stationary unit sits in `AIGuardState`, whose `AIGuardMachine`
acquires and attacks from `AIGuardInnerState`; a moving one is in `AIInternalMoveToState`, which
drives the state machine to `AI_ATTACK_OBJECT` directly. Neither builds an `AICommandParms`, so a
`MustDeployToAttack = Yes` trebuchet with an enemy in range fires packed.

**What this does.** Stops asking *which command arrived* and asks *what the unit is doing*. Nine
bytes at the head of `update`'s recorded-command resolution (`DEPLOY_STYLE_UPDATE_RESOLVE_BRANCH`)
become a jump into an appended cave that, before the stock resolution runs, deploys the unit when
all of: no *targeted* command is recorded, the state is `READY_TO_MOVE`, `MustDeployToAttack` is
set, `AIUpdateInterface::getCurrentVictim` returns an object, and the weapon says that object is in
range. Everything else falls into the two stock arms exactly as before.

**Why `getCurrentVictim`.** It reads `m_currentVictimID` at `AIUpdateInterface+0x40`, which the
setter at `AI_SET_CURRENT_VICTIM` writes from all 27 of its call sites - the idle, move, guard,
approach and pursue states alike - and which is cleared both when the AI stops attacking and when
the victim dies. It is the one field that sees the attack however the engine started it. The
attack-machine slots at `+0x20C` do not: a unit attacking out of its guard machine leaves them
null, which is why the first version of this patch missed the common case entirely.

**Nothing is written to the module.** The cave calls `setMyState(DEPLOY)` and jumps to
`DEPLOY_STYLE_UPDATE_RESOLVED`, the point every arm of the resolution rejoins with nothing
resolved - so it leaves no flag behind that could go stale when the target dies, and the next
frame simply asks the same question again. `setMyState(DEPLOY)` opens with `aiIdle(CMD_FROM_AI)`,
which is what takes the attack off the base state machine while the unit stands up; once
`READY_TO_ATTACK` is reached the unit re-acquires on its own, deployed. That is the same way a
player-ordered attack resumes after its deploy, so both routes now end in the same place.

**Why the range test.** Without it a unit would stand up the moment it acquired something across
the map and then walk to it deployed. The cave asks the same `Weapon::isTargetObjectInRange`
question, with the same arguments, that `update` asks further down for a recorded target, so
"close enough to shoot" means one thing in both places.

**Why only the *targeted* flags keep it out of the way.** A player's attack order records
`+0x595` (attack object) or `+0x596` (attack position), and the `READY_TO_MOVE` arm resolves those
itself and deploys for them - so the cave stands aside, and that path is untouched. `+0x594` is
different: it means "attack-ish, no explicit target" - guard, attack-move, hunt - and its arm can
only find a target through the mood picker and the tracked id, both of which come back empty for a
unit attacking out of its guard machine. Refusing to act while `+0x594` is set left a stationary
guarding trebuchet firing packed, which is the case this patch exists for, so `+0x594` is
deliberately not one of `DEPLOY_STYLE_TARGETED_COMMAND_OFFSETS`.

**Every peer must run the same patched binary.** This changes when a logic-side state machine is
told to deploy, so a patched and an unpatched client diverge on the first auto-acquire by a
deploying unit, and replays do not cross - the same requirement `attack-requires-damage`,
`multi-execute-gate` and `spawn-union` carry. There is **no INI change**: the keyword already
exists, and `MustDeployToAttack = No` is untouched because the cave reads the same byte the stock
arm reads and falls through when it is zero.

**Composition.** Order-independent: the cave is allocated past every existing section and
:meth:`verify` finds it by name. The only engine bytes it edits are the nine at
`DEPLOY_STYLE_UPDATE_RESOLVE_BRANCH`, which no other bundled patch touches, and it reads nothing
another patch rewrites.

**Runtime-verified.** The predicate was checked twice by reading paused matches - it selects
exactly the trebuchets that are packed with a victim in range, including the guarding one with
`+0x594` recorded that an earlier revision refused, and leaves the already-deployed ones alone -
and the finished patch was then confirmed in a live game: siege deploys before its first shot.
"""

from __future__ import annotations

import struct

from ..addresses import (
    AI_CURRENT_VICTIM,
    AI_CURRENT_VICTIM_BYTES,
    AI_SET_CURRENT_VICTIM,
    AI_SET_CURRENT_VICTIM_BYTES,
    DEPLOY_STYLE_MODULE_DATA_OFFSET,
    DEPLOY_STYLE_MOVE_ARM_MUST_DEPLOY,
    DEPLOY_STYLE_MOVE_ARM_MUST_DEPLOY_BYTES,
    DEPLOY_STYLE_MUST_DEPLOY_GETTER,
    DEPLOY_STYLE_MUST_DEPLOY_GETTER_BYTES,
    DEPLOY_STYLE_MUST_DEPLOY_OFFSET,
    DEPLOY_STYLE_RECORD_STORES,
    DEPLOY_STYLE_RECORDED_COMMAND_OFFSETS,
    DEPLOY_STYLE_SET_MY_STATE,
    DEPLOY_STYLE_SET_MY_STATE_BYTES,
    DEPLOY_STYLE_SET_STATE_STORE,
    DEPLOY_STYLE_SET_STATE_STORE_BYTES,
    DEPLOY_STYLE_STATE_DEPLOY,
    DEPLOY_STYLE_STATE_OFFSET,
    DEPLOY_STYLE_STATE_READY_TO_MOVE,
    DEPLOY_STYLE_TARGETED_COMMAND_OFFSETS,
    DEPLOY_STYLE_UPDATE,
    DEPLOY_STYLE_UPDATE_ENTRY,
    DEPLOY_STYLE_UPDATE_ESI_BIAS,
    DEPLOY_STYLE_UPDATE_OBJECT_PATH,
    DEPLOY_STYLE_UPDATE_OBJECT_PATH_BYTES,
    DEPLOY_STYLE_UPDATE_POSITION_PATH,
    DEPLOY_STYLE_UPDATE_POSITION_PATH_BYTES,
    DEPLOY_STYLE_UPDATE_RESOLVE_BRANCH,
    DEPLOY_STYLE_UPDATE_RESOLVE_BRANCH_BYTES,
    DEPLOY_STYLE_UPDATE_RESOLVED,
    DEPLOY_STYLE_UPDATE_RESOLVED_BYTES,
    WEAPON_TARGET_IN_RANGE,
    WEAPON_TARGET_IN_RANGE_BYTES,
)
from ..asm import JE, JNE, Asm
from ..patcher import Patch
from ..utils import allocate_section, apply_byte_patch, find_section, va_to_offset

__all__ = [
    "ANCHORS",
    "HOOK_ORIGINAL",
    "HOOK_VA",
    "SECTION_NAME",
    "DeployBeforeAttackPatch",
    "build_cave",
    "update_field",
]

SECTION_NAME = ".deploy"  # 7 chars: the PE name field is 8 bytes and truncates silently

# IMAGE_SCN_CNT_CODE | MEM_EXECUTE | MEM_READ - the cave is pure code and is never written.
_CHARACTERISTICS = 0x20 | 0x20000000 | 0x40000000

HOOK_VA = DEPLOY_STYLE_UPDATE_RESOLVE_BRANCH
HOOK_ORIGINAL = DEPLOY_STYLE_UPDATE_RESOLVE_BRANCH_BYTES

#: The first instruction at each address the cave jumps into or calls, plus the getters and stores
#: whose bytes fix the field offsets it reads. A build that laid any of them out differently fails
#: here instead of on a wild jump or a byte read off the wrong field.
ANCHORS = {
    DEPLOY_STYLE_UPDATE: DEPLOY_STYLE_UPDATE_ENTRY,
    DEPLOY_STYLE_UPDATE_POSITION_PATH: DEPLOY_STYLE_UPDATE_POSITION_PATH_BYTES,
    DEPLOY_STYLE_UPDATE_OBJECT_PATH: DEPLOY_STYLE_UPDATE_OBJECT_PATH_BYTES,
    DEPLOY_STYLE_UPDATE_RESOLVED: DEPLOY_STYLE_UPDATE_RESOLVED_BYTES,
    DEPLOY_STYLE_SET_MY_STATE: DEPLOY_STYLE_SET_MY_STATE_BYTES,
    DEPLOY_STYLE_SET_STATE_STORE: DEPLOY_STYLE_SET_STATE_STORE_BYTES,
    DEPLOY_STYLE_MUST_DEPLOY_GETTER: DEPLOY_STYLE_MUST_DEPLOY_GETTER_BYTES,
    DEPLOY_STYLE_MOVE_ARM_MUST_DEPLOY: DEPLOY_STYLE_MOVE_ARM_MUST_DEPLOY_BYTES,
    AI_CURRENT_VICTIM: AI_CURRENT_VICTIM_BYTES,
    AI_SET_CURRENT_VICTIM: AI_SET_CURRENT_VICTIM_BYTES,
    WEAPON_TARGET_IN_RANGE: WEAPON_TARGET_IN_RANGE_BYTES,
    **DEPLOY_STYLE_RECORD_STORES,
}


def update_field(offset: int) -> bytes:
    """``offset`` - a module field, counted from the module - as `update` addresses it.

    `update` biases `esi` to `this + 0x10` for its whole body, so every field the cave shares with
    `aiDoCommand` is named 0x10 lower here. Doing that subtraction in one place is what keeps the
    two sets of offsets from drifting apart."""
    return struct.pack("<i", offset - DEPLOY_STYLE_UPDATE_ESI_BIAS)


def _update_field_byte(offset: int) -> int:
    """The same subtraction for a field close enough to `esi` to take an 8-bit displacement."""
    return (offset - DEPLOY_STYLE_UPDATE_ESI_BIAS) & 0xFF


def build_cave(base_va: int) -> bytes:
    """The deploy test that runs before `update` resolves a recorded command.

    On entry `esi` is `module + 0x10`, `ebx` the weapon `update` just fetched, `ebp` the owning
    `Object` and `edi` zero - all established by the prologue and live across the hook. The two
    helpers and `setMyState` are `__thiscall` and preserve `ebx`, `esi`, `edi` and `ebp`, so the
    stock code the cave falls back into finds every register it expects."""
    module = b"\x8d\x4e" + bytes([-DEPLOY_STYLE_UPDATE_ESI_BIAS & 0xFF])  # lea ecx, [esi-0x10]
    a = Asm(base_va)

    # No *targeted* command recorded. An attack-object or attack-position order names something
    # the stock arm resolves for itself, and deploys for, so leave those alone. A `+0x594`
    # command - guard, attack-move, hunt - names nothing, and its arm comes back empty for a unit
    # attacking out of its guard machine, so it is ours to answer.
    for offset in DEPLOY_STYLE_TARGETED_COMMAND_OFFSETS:
        a.emit(b"\x80\xbe", update_field(offset), 0x00)  # cmp byte [esi+<flag>], 0
        a.jcc(JNE, "stock")

    a.emit(b"\x83\xbe", update_field(DEPLOY_STYLE_STATE_OFFSET), DEPLOY_STYLE_STATE_READY_TO_MOVE)
    a.jcc(JNE, "stock")  # already standing, or already on its way there

    a.emit(b"\x8b\x46", _update_field_byte(DEPLOY_STYLE_MODULE_DATA_OFFSET))  # mov eax,[esi-0xc]
    a.emit(b"\x80\x78", DEPLOY_STYLE_MUST_DEPLOY_OFFSET, 0x00)  # cmp byte [eax+0x6f], 0
    a.jcc(JE, "stock")  # MustDeployToAttack = No: stock

    a.emit(module)
    a.call_absolute(AI_CURRENT_VICTIM)  # -> the Object the AI is attacking, or NULL
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc(JE, "stock")  # not attacking anything

    # The same in-range question `update` asks for a recorded target, with the same arguments.
    a.emit(b"\x6a\x01")  # push 1
    a.emit(b"\xd9\xee")  # fldz
    a.emit(b"\x51")  # push ecx          ; four bytes for the float
    a.emit(b"\xd9\x1c\x24")  # fstp dword [esp]  ; 0.0f extra range
    a.emit(b"\x50")  # push eax          ; the victim
    a.emit(b"\x55")  # push ebp          ; the owning Object
    a.emit(b"\x8b\xcb")  # mov ecx, ebx      ; the weapon
    a.call_absolute(WEAPON_TARGET_IN_RANGE)
    a.emit(b"\x84\xc0")  # test al, al
    a.jcc(JE, "stock")  # out of range: let it close first, and ask again next frame

    a.emit(0x6A, DEPLOY_STYLE_STATE_DEPLOY)  # push 1
    a.emit(module)
    a.call_absolute(DEPLOY_STYLE_SET_MY_STATE)
    a.jmp_absolute(DEPLOY_STYLE_UPDATE_RESOLVED)  # rejoin with nothing resolved

    # The displaced branch, unchanged: a recorded attack position falls through to its arm,
    # anything else goes on to try the recorded attack object.
    a.label("stock")
    a.emit(b"\x80\xbe", update_field(DEPLOY_STYLE_RECORDED_COMMAND_OFFSETS[2]), 0x00)
    a.jcc(JNE, "position")
    a.jmp_absolute(DEPLOY_STYLE_UPDATE_OBJECT_PATH)

    a.label("position")
    a.jmp_absolute(DEPLOY_STYLE_UPDATE_POSITION_PATH)
    return a.finish()


class DeployBeforeAttackPatch(Patch):
    name = "deploy-before-attack"
    author = "officialNecro"
    description = (
        "Make `MustDeployToAttack` gate an attack the AI starts, not just one the player orders. "
        "A `DeployStyleAIUpdate` unit that acquires a target on its own - idle, on the move or "
        "under attack-move - now stands up before it shoots instead of firing packed. No INI "
        "change"
    )

    def apply(self, data: bytearray) -> None:
        hook_off = va_to_offset(data, HOOK_VA)
        if hook_off is None:
            raise ValueError(f"{HOOK_VA:#010x} is not mapped - not the expected build")
        self._check_anchors(data)
        section_va = allocate_section(data, SECTION_NAME, build_cave, _CHARACTERISTICS)
        jump = b"\xe9" + struct.pack("<i", section_va - (HOOK_VA + 5))
        jump += b"\x90" * (len(HOOK_ORIGINAL) - len(jump))
        apply_byte_patch(
            data,
            hook_off,
            HOOK_ORIGINAL,
            jump,
            "DeployStyleAIUpdate::update resolution head -> deploy-before-attack cave",
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
                    f"{va:#010x} holds {got.hex()}, expected {expected.hex()} - "
                    "`DeployStyleAIUpdate`'s layout is not this build's, so the cave would jump "
                    "into the wrong place or read the wrong field"
                )

    def verify(self, data: bytes | bytearray) -> list[str]:
        problems: list[str] = []
        located = find_section(data, SECTION_NAME)
        if located is None:
            return [f"{SECTION_NAME} section is absent"]
        section_va, section_off, _ = located
        off = va_to_offset(data, HOOK_VA)
        if off is None:
            return [f"{HOOK_VA:#010x} is not mapped by any section"]
        if data[off] != 0xE9:
            return [f"{HOOK_VA:#010x} is not a jmp - the hook is not installed"]
        target = HOOK_VA + 5 + struct.unpack_from("<i", data, off + 1)[0]
        if target != section_va:
            problems.append(f"hook jumps to {target:#010x}, expected {section_va:#010x}")
        tail = bytes(data[off + 5 : off + len(HOOK_ORIGINAL)])
        if tail != b"\x90" * (len(HOOK_ORIGINAL) - 5):
            problems.append(f"the displaced branch's tail is {tail.hex()}, expected nops")
        cave = build_cave(section_va)
        if bytes(data[section_off : section_off + len(cave)]) != cave:
            problems.append(f"the {SECTION_NAME} cave does not hold the expected test")
        return problems
