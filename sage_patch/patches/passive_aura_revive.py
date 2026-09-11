"""The passive-aura-revive patch: let an aura come back after the object carrying it does.

Targets the ROTWK SAGE-engine `game.dat` build ``2.01.2614.37001``. Every address below is
derived in ``../docs/passive-aura-revive.md``.

**The bug.** An update module tells the scheduler when to look at it again by returning a frame
delta, and ``0x3FFFFFFF`` - `UPDATE_SLEEP_FOREVER` - means never. Both of the engine's aura modules
return it the first time they tick on a **dead** object, and **nothing wakes an update module when
an object is revived**: `Object::setEffectivelyDead(FALSE)` (`0x0068D950`) clears the flag and pokes
the drawable, and never walks the module array. An aura that gives up its place in the schedule that
way has no other way back.

That is invisible for a building the engine deletes when it dies, because the module dies with it.
It is permanent for one that **survives death**: `KeepObjectDie` plus `RubbleRiseUpdate` is how
every castle keep, wall, gate and camp citadel in a BFME mod becomes rubble instead of a hole, and
the object that repairs itself out of rubble is the same object. So the aura stops when the
structure falls - which is what a mod wants, and happens on its own because each ping re-applies the
modifier with an expiry one delay ahead - and then never restarts for the rest of the game.

**`PassiveAreaEffectBehavior`, five bytes.** `update` (`0x00887DF7`) ends in three gates. The
`UpgradeRequired` and under-construction gates both return the module's ordinary `PingDelay` sleep,
so the condition gets another look. The dead gate does not::

    00887e5b  test byte [ebx+0x458], 1   ; my own object effectively dead?
    00887e62  je   0x00887e76            ;   no  -> scan and re-apply
    00887e64  mov  eax, 0x3fffffff       ;   yes -> UPDATE_SLEEP_FOREVER
    00887e69  jmp  0x00887ec2            ;          return it

The patch returns the `PingDelay` sleep there instead, at the one instruction above::

    00887e64  mov  eax, [esp+0x10]       ; the sleep every other path returns
    00887e68  nop
    00887e69  jmp  0x00887ec2            ; unchanged

`[esp+0x10]` is the scratch dword the update writes at `0x00887E09` from `ModuleData+0x10`
(`PingDelay`, floored at 1) and reads back at `0x00887EBE` to return. The prologue's five pushes
are still on the stack at the rewritten instruction and every call between the two is
callee-balanced, so the displacement names the same slot in both places.

**`AttributeModifierAuraUpdate`, twenty-four bytes and a cave.** The same defect, and two reasons it
cannot be the same five bytes.

*The sentinel is shared.* It is also where an aura still waiting on its `TriggeredBy` upgrade
parks, and that is correct - `giveSelfUpgrade` (`0x00855388`) wakes it through this module's
`upgradeImplementation` (`0x008554D6`), a bare `setWakeFrame`. Rewriting `0x0089F474` would put
every un-triggered aura in a mod back on a `RefreshDelay` poll for no benefit::

    0089f441  test byte [esi+0x458], 1   ; effectively dead?
    0089f44f  je   0x0089f459            ;   no -> on to the next gate
    0089f451  cmp  byte [edi+0x16a], bl  ; RunWhileDead
    0089f457  je   0x0089f474            ;   dead and No  -> sleep forever    <- the defect
    ...
    0089f46e  call [eax]                 ; UpgradeMux::isAlreadyUpgraded
    0089f470  test al, al
    0089f472  jne  0x0089f47e
    0089f474  mov  eax, 0x3fffffff       ;   not triggered -> sleep forever   <- correct

*It has no construction gate.* `PassiveAreaEffectBehavior` has one at `0x00887E45`, above its dead
test, and that is what makes it resume when a rebuild **finishes**: the effectively-dead flag is
rewritten by `ActiveBody::internalChangeHealth` from `health <= 0`, so it clears on the first frame
a rubble structure repairs above zero, and only `GettingBuiltBehavior::isStillBuilding` stays true
for the rest of the rebuild. `AttributeModifierAuraUpdate` tests neither, so on the dead arm alone
it would come back the moment the rubble started rising.

So the whole gate block becomes a jump into an ``.aurevi`` cave that re-emits the displaced
instructions, adds the sibling module's gate, and splits the dead arm off the sentinel::

    push edi                   ; the three displaced instructions, unchanged
    mov  edi, [ecx-0xc]
    mov  [ebp-0x14], ecx
    mov  ecx, esi              ; transcribed from PassiveAreaEffectBehavior @0x00887E45
    call 0x0068c3e6            ; Object::getGettingBuiltBehavior
    test eax, eax
    je   no_module
    mov  edx, [eax]
    mov  ecx, eax
    call [edx+0x2c]            ; isStillBuilding()
    jmp  answer
  no_module:
    push 2                     ; OBJECT_STATUS_UNDER_CONSTRUCTION
    mov  ecx, esi
    call 0x0044ddec            ; Object::testStatus
  answer:
    test al, al
    jne  ordinary_sleep        ; still going up -> wait
    test byte [esi+0x458], 1   ; stock: effectively dead?
    je   scan
    cmp  byte [edi+0x16a], 0   ; stock: RunWhileDead
    jne  scan                  ; Yes -> keep applying through the death, unchanged
  ordinary_sleep:
    jmp  0x0089f6bd            ; RefreshDelay + id % 5, the sleep every other path returns
  scan:
    mov  ecx, [ebp-0x14]       ; `this` again - the calls above left their own in it
    jmp  0x0089f459

There is no scratch slot to read back for the *sleep*: this update computes it at the exit, from
`RefreshDelay` (`ModuleData+0x18`) and the object's id modulo five. `esi` (the `Object`) and `edi`
(the `ModuleData`) survive both calls, all three pushes the epilogue pops happen above the gate, and
`[ebp-4]` still holds the SEH scope index the sentinel arm returns under - so the jump unwinds
exactly as `0x0089F474` does.

**`ecx` does not survive, and the scan resume point needs it.** A `__thiscall` callee leaves its own
`this` in `ecx`, and ten instructions past `0x0089F459` the update does `add ecx, 0x10` /
`mov eax, [ecx]` / `call [eax]` - the `UpgradeMux::isAlreadyUpgraded` test - off the `ecx` the
prologue left, because stock nothing in between touches it. So the scan arm reloads it from
`[ebp-0x14]`, the slot the displaced `mov` above just wrote. Without that reload the update calls
through `[GettingBuiltBehavior+0x10]`, which is zero, and the game dies on the first finished
structure carrying an aura - which is to say on the first frame of a match.

Both dead arms still return **before** the scan, so no aura is applied while the object is dead and
nothing about the rubble behaviour changes. What changes is that each module keeps its place in the
schedule, so the first tick after the structure is finished sees a live object and resumes.

**What the construction gate costs elsewhere.** It is not limited to a rebuild, because nothing on
the object says which kind of build this is: an `AttributeModifierAuraUpdate` on a structure now
also stays quiet while that structure is put up for the **first** time. That is what
`PassiveAreaEffectBehavior` already does, so the change makes the two modules agree rather than
inventing a third behaviour. Units are untouched - they have no `GettingBuiltBehavior` and never
carry `UNDER_CONSTRUCTION`, so the gate answers no and costs them one module-array walk per tick.

**Cost.** A dead or half-built object runs a handful of compares and one module-array walk every
delay instead of nothing. Only objects carrying one of these two modules are affected; one that is
deleted takes its modules with it as before.

**No INI change.** No keyword, no token, no `.str` key - a mod uses this by writing exactly what it
already writes. The INI-level alternatives both fail on their own terms, which is why this is a
binary patch: an aura whose `UpgradeRequired` is *satisfied* still reaches the dead arm, so no
upgrade gating avoids it, and `AttributeModifierAuraUpdate`'s `RunWhileDead = Yes` trades a
permanent loss for an aura that stays on through the rubble.

**Scope.** `AttributeModifierUpgrade`, the third module a reader might expect here, is not affected
and is not touched: it is not an update module at all, and the modifier it applies is permanent and
outlives its object's death on its own. ``docs/passive-aura-revive.md`` §8.1 records why.

**Composition.** Order-independent: the cave is allocated past every existing section and
:meth:`~PassiveAuraRevivePatch.verify` finds it by name. The engine bytes it edits are five at
`0x00887E64` and twenty-four at `0x0089F441`, which no other bundled patch touches, and it reads
nothing another patch rewrites.
"""

from __future__ import annotations

import struct

from ..addresses import (
    ATTRIBUTE_MODIFIER_AURA_ANCHORS,
    ATTRIBUTE_MODIFIER_AURA_GATES,
    ATTRIBUTE_MODIFIER_AURA_GATES_BYTES,
    ATTRIBUTE_MODIFIER_AURA_NORMAL_SLEEP,
    ATTRIBUTE_MODIFIER_AURA_RUN_WHILE_DEAD_OFFSET,
    ATTRIBUTE_MODIFIER_AURA_SCAN,
    ATTRIBUTE_MODIFIER_AURA_THIS_EBP_OFFSET,
    GETTING_BUILT_STILL_BUILDING_SLOT,
    OBJECT_EFFECTIVELY_DEAD_FLAG,
    OBJECT_GET_GETTING_BUILT_BEHAVIOR,
    OBJECT_STATUS_UNDER_CONSTRUCTION,
    OBJECT_TEST_STATUS,
    PASSIVE_AREA_EFFECT_ANCHORS,
    PASSIVE_AREA_EFFECT_DEAD_SLEEP,
    PASSIVE_AREA_EFFECT_DEAD_SLEEP_BYTES,
    PASSIVE_AREA_EFFECT_PING_SLOT_OFFSET,
)
from ..asm import JE, JNE, Asm
from ..patcher import Patch
from ..utils import allocate_section, apply_byte_patch, find_section, va_to_offset

__all__ = [
    "GATE_JUMP_PADDING",
    "PATCHED_BYTES",
    "SECTION_NAME",
    "PassiveAuraRevivePatch",
    "build_code",
]

SECTION_NAME = ".aurevi"  # 7 chars: the PE name field is 8 bytes and truncates silently

# IMAGE_SCN_CNT_CODE | MEM_EXECUTE | MEM_READ - the cave is pure code and is never written.
_CHARACTERISTICS = 0x20 | 0x20000000 | 0x40000000

#: What the twenty-four byte gate block is padded out with behind the five-byte jump. Named because
#: :meth:`~PassiveAuraRevivePatch.verify` checks it: the `nop` run is how the rewrite says it
#: covered the whole block rather than leaving the tail of an instruction behind.
GATE_JUMP_PADDING = b"\x90" * (len(ATTRIBUTE_MODIFIER_AURA_GATES_BYTES) - 5)


#: `[ebp-0x14]` as a `modrm` displacement byte - the slot the update keeps `this` in.
_EBP_THIS = ATTRIBUTE_MODIFIER_AURA_THIS_EBP_OFFSET & 0xFF


def _sleep_the_ping_delay(offset: int) -> bytes:
    """``mov eax, [esp+offset]`` then a `nop`, so the rewrite is the same five bytes the sentinel
    occupied and the `jmp` behind it keeps its address."""
    if not 0 <= offset <= 0x7F:
        raise ValueError(f"[esp+0x{offset:x}] does not encode as a byte displacement")
    return bytes((0x8B, 0x44, 0x24, offset, 0x90))


#: What replaces :data:`~sage_patch.addresses.PASSIVE_AREA_EFFECT_DEAD_SLEEP_BYTES`.
PATCHED_BYTES = _sleep_the_ping_delay(PASSIVE_AREA_EFFECT_PING_SLOT_OFFSET)


def build_code(base_va: int) -> bytes:
    """`AttributeModifierAuraUpdate`'s gate block, with a construction gate in front of it and the
    dead arm split off the shared sentinel.

    Entered from :data:`~sage_patch.addresses.ATTRIBUTE_MODIFIER_AURA_GATES` with `esi` holding the
    `Object`, `ecx` still holding the update's `this` and `ebx` zeroed. It never returns to the
    hook: every arm jumps back into the update. Both calls are `__thiscall` and preserve
    `esi`/`edi`/`ebx`, which is what lets the stock tests below them run unchanged - but **not**
    `ecx`, which the scan arm therefore reloads from the update's own `this` slot.
    """
    a = Asm(base_va)
    # The three displaced instructions, before `ecx` is needed for anything else.
    a.emit(0x57)  # push edi
    a.emit(0x8B, 0x79, 0xF4)  # mov edi, [ecx-0xc]     the ModuleData
    a.emit(0x89, 0x4D, _EBP_THIS)  # mov [ebp-0x14], ecx    `this`, read back further down

    # Is the object still going up? Transcribed from `PassiveAreaEffectBehavior::update`
    # @0x00887E45, which is the gate this module is missing.
    a.emit(0x8B, 0xCE)  # mov ecx, esi
    a.call_absolute(OBJECT_GET_GETTING_BUILT_BEHAVIOR)
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "no_getting_built")
    a.emit(0x8B, 0x10)  # mov edx, [eax]
    a.emit(0x8B, 0xC8)  # mov ecx, eax
    a.emit(0xFF, 0x52, GETTING_BUILT_STILL_BUILDING_SLOT)  # call [edx+0x2c]
    a.jmp("still_building")

    a.label("no_getting_built")
    a.emit(0x6A, OBJECT_STATUS_UNDER_CONSTRUCTION)  # push 2
    a.emit(0x8B, 0xCE)  # mov ecx, esi
    a.call_absolute(OBJECT_TEST_STATUS)

    a.label("still_building")
    a.emit(0x84, 0xC0)  # test al, al
    a.jcc(JNE, "ordinary_sleep")  # not finished -> wait, and look again

    # The stock dead test, re-emitted.
    a.emit(0xF6, 0x86, struct.pack("<I", OBJECT_EFFECTIVELY_DEAD_FLAG), 0x01)
    a.jcc(JE, "scan")
    # The stock `RunWhileDead` compare. The immediate stands in for the stock `bl` so the cave does
    # not depend on the `xor ebx, ebx` at 0x0089F43F staying where it is; `ebx` is zero either way.
    a.emit(0x80, 0xBF, struct.pack("<I", ATTRIBUTE_MODIFIER_AURA_RUN_WHILE_DEAD_OFFSET), 0x00)
    a.jcc(JNE, "scan")  # RunWhileDead = Yes -> keep applying through the death, unchanged

    a.label("ordinary_sleep")
    a.jmp_absolute(ATTRIBUTE_MODIFIER_AURA_NORMAL_SLEEP)

    # `this` goes back in `ecx` before the scan, because the calls above left their own there and
    # the resume point dereferences it ten instructions on. The sleep arm needs no such thing: it
    # reloads `ecx` from the SEH slot itself.
    a.label("scan")
    a.emit(0x8B, 0x4D, _EBP_THIS)  # mov ecx, [ebp-0x14]
    a.jmp_absolute(ATTRIBUTE_MODIFIER_AURA_SCAN)
    return a.finish()


def _offset(data: bytes | bytearray, va: int) -> int:
    off = va_to_offset(data, va)
    if off is None:
        raise ValueError(f"VA 0x{va:08x} is not mapped - not the expected build")
    return off


class PassiveAuraRevivePatch(Patch):
    """Stop the two aura modules sleeping forever when their own object dies."""

    name = "passive-aura-revive"
    author = "officialNecro"
    description = (
        "PassiveAreaEffectBehavior and AttributeModifierAuraUpdate stop parking themselves at "
        "UPDATE_SLEEP_FOREVER the first time they tick on a dead object, and return their ordinary "
        "sleep instead, so an aura on a structure that survives death as rubble (KeepObjectDie "
        "plus RubbleRiseUpdate, which is every castle keep, wall, gate and camp citadel) resumes "
        "once the structure has been rebuilt rather than being lost for the rest of the game. The "
        "aura is still inactive while the object is dead and for the whole of the rebuild, "
        "AttributeModifierAuraUpdate gaining the GettingBuiltBehavior gate its sibling already "
        "has - so it also stays off while a structure is built for the first time. An aura still "
        "waiting on its TriggeredBy upgrade still sleeps until the upgrade arrives. Needs no INI, "
        ".str or map change - the modules and their fields are unchanged"
    )

    def apply(self, data: bytearray) -> None:
        self._check_anchors(data)
        gate_off = _offset(data, ATTRIBUTE_MODIFIER_AURA_GATES)
        passive_off = _offset(data, PASSIVE_AREA_EFFECT_DEAD_SLEEP)

        section_va = allocate_section(data, SECTION_NAME, build_code, _CHARACTERISTICS)
        jump = b"\xe9" + struct.pack("<i", section_va - (ATTRIBUTE_MODIFIER_AURA_GATES + 5))
        apply_byte_patch(
            data,
            passive_off,
            PASSIVE_AREA_EFFECT_DEAD_SLEEP_BYTES,
            PATCHED_BYTES,
            f"PassiveAreaEffectBehavior dead-arm sleep @0x{PASSIVE_AREA_EFFECT_DEAD_SLEEP:08x}",
        )
        apply_byte_patch(
            data,
            gate_off,
            ATTRIBUTE_MODIFIER_AURA_GATES_BYTES,
            jump + GATE_JUMP_PADDING,
            f"AttributeModifierAuraUpdate gate block "
            f"@0x{ATTRIBUTE_MODIFIER_AURA_GATES:08x} -> {SECTION_NAME} cave",
        )

    def verify(self, data: bytes | bytearray) -> list[str]:
        problems: list[str] = []
        try:
            passive_off = _offset(data, PASSIVE_AREA_EFFECT_DEAD_SLEEP)
            gate_off = _offset(data, ATTRIBUTE_MODIFIER_AURA_GATES)
        except ValueError as exc:
            return [str(exc)]

        got = bytes(data[passive_off : passive_off + len(PATCHED_BYTES)])
        if got != PATCHED_BYTES:
            site = f"the PassiveAreaEffectBehavior dead arm @0x{PASSIVE_AREA_EFFECT_DEAD_SLEEP:08x}"
            if got == PASSIVE_AREA_EFFECT_DEAD_SLEEP_BYTES:
                problems.append(f"{site} is unpatched")
            else:
                problems.append(
                    f"{site} is {got.hex()}, expected {PATCHED_BYTES.hex()} (patched) or "
                    f"{PASSIVE_AREA_EFFECT_DEAD_SLEEP_BYTES.hex()} (stock)"
                )

        located = find_section(data, SECTION_NAME)
        if located is None:
            problems.append(f"{SECTION_NAME} section is absent")
            return problems
        section_va, section_off, _ = located

        gate = f"the AttributeModifierAuraUpdate gates @0x{ATTRIBUTE_MODIFIER_AURA_GATES:08x}"
        if data[gate_off] != 0xE9:
            problems.append(f"{gate} are not a jmp - the hook is not installed")
        else:
            displacement = struct.unpack_from("<i", data, gate_off + 1)[0]
            target = ATTRIBUTE_MODIFIER_AURA_GATES + 5 + displacement
            if target != section_va:
                problems.append(f"{gate} jump to 0x{target:08x}, expected 0x{section_va:08x}")
            tail = bytes(data[gate_off + 5 : gate_off + len(ATTRIBUTE_MODIFIER_AURA_GATES_BYTES)])
            if tail != GATE_JUMP_PADDING:
                problems.append(
                    f"{gate} left {tail.hex()} behind the jump, "
                    f"expected {len(GATE_JUMP_PADDING)} nop"
                )

        code = build_code(section_va)
        if bytes(data[section_off : section_off + len(code)]) != code:
            problems.append(f"the {SECTION_NAME} cave does not hold the expected gates")
        return problems

    @staticmethod
    def _check_anchors(data: bytes | bytearray) -> None:
        """Refuse a build where either update is not the function its bytes were read out of.

        For each module the module-name string and the vtable slot say the function is that
        module's update. Beyond that the passive module's `PingDelay` read and normal return frame
        the scratch slot `[esp+0x10]` names, and its construction gate is the routine the cave
        transcribes; the aura module's anchors cover the two exits its cave has to keep apart - the
        sentinel it deliberately leaves stock, and the sleep computation it jumps to - plus the two
        engine routines the transcription calls.
        """
        for va, expected in {
            **PASSIVE_AREA_EFFECT_ANCHORS,
            **ATTRIBUTE_MODIFIER_AURA_ANCHORS,
        }.items():
            got = bytes(data[_offset(data, va) :][: len(expected)])
            if got != expected:
                raise ValueError(
                    f"unexpected build: 0x{va:08x} is {got.hex()}, expected {expected.hex()} - "
                    "this is not the game.dat these addresses were read from"
                )
