"""The castle-unpack-clearance patch: stop a camp or castle unpack silently dropping structures.

Targets the ROTWK SAGE-engine `game.dat` build ``2.01.2614.37001``. Every address below is derived
in ``../docs/castle-unpack-clearance.md``.

**The defect, and why it is one defect and not two.** `CastleBehavior`'s per-entry builder
(``0x007987EE``) asks `BuildAssistant::isLocationLegalToBuild` once per prefab entry and, on any
non-zero answer, abandons that entry for good - `esi` is zeroed and the routine returns NULL. The
loop that drives it hands that NULL to `onStructureBuilt`, which null-checks and does nothing, so
a camp comes up with a hole in it and the game says nothing. There is no retry and no nudge.

Two things reach that refusal, and they are the two reported symptoms:

* **An object in the way.** Bit ``0x4`` of the flags word the builder passes turns on
  `isLocationClearOfObjects`. `SHRUBBERY`, `CLEARED_BY_BUILD`, `INERT` and `AIRCRAFT` step aside;
  everything else - a unit standing on the spot, a rock, a plot flag, somebody's building -
  deletes a structure from the prefab.
* **Rotation.** The prefab is placed through the flag's own 3x4 transform (``0x0079889E``), so the
  layout is *rigid*: rotating a camp cannot make its own structures collide. What rotation changes
  is the ground and the scenery underneath, and bit ``0x1`` of the same flags word runs the
  footprint flatness and pathfind-cell tests against exactly that. A camp turned any amount samples
  terrain and sweeps props the prefab was never authored against, which is why it presents as a
  risk rather than a rule.

The keep is already exempt: ``0x00798951`` skips the whole gate for a `KindOf COMMANDCENTER`
template, which is why the fortress always appears and only the rest of the camp is at risk.

**What this does.** Repoints the builder's five-byte `call` at :data:`HOOK_VA` into an ``.cstunp``
cave that asks the same question twice. The first ask is the stock one, bit for bit; when it comes
back legal, that is the answer. When it does not, the cave asks again with a flags word of **zero**
and returns *that*. Flags zero is not "skip the test" - `isLocationLegalToBuild` runs three tests
no flag controls, and they keep their veto:

* the position must be inside the map's playable extent (``0x0079683D``), so nothing lands off the
  map;
* `KindOf CANNOT_BUILD_NEAR_SUPPLIES` proximity (``0x00796942``);
* `KindOf WALL_HUB` anchor proximity (``0x00796C66``).

So the patch says, structurally, "refuse only for a reason the flags word never controlled". That
is the whole change: no new predicate, no reimplementation of anything the binary already states.

**What it does not do.** Nothing is destroyed or pushed out of the way. A structure that was being
refused now materialises where it was meant to be, on top of whatever was standing there - which on
a camp the mod placed itself is normally scenery. Clearing the blocker needs a partition sweep and
a policy for enemy units standing on a camp being unpacked, and that is a design question rather
than a bug; ``docs/castle-unpack-clearance.md`` §4.3 prices it.

**Scope: the prefab path only.** The builder has one caller, the structure loop at ``0x0079B903``.
The explicit-object path (``0x0079B98B``) reaches the foundation interface's create slot directly
and asks no legality question at all, so a plot built through `CASTLE_UNPACK_EXPLICIT_OBJECT`
already spawned unconditionally and is untouched here. Nothing else in the game calls the builder,
so no other placement - a player building on a plot, the AI's farm builder, a script - changes.

**The hook is a `call`, and the cave is a callee.** The stock instruction is
`call CASTLE_LEGALITY_THUNK`, a ``__stdcall`` that cleans its own five arguments with ``ret 0x14``.
The cave replaces the call's *target*, not the call, so it is entered the way the thunk was and
ends in the same ``ret 0x14`` - identical stack effect, and none of the displaced-call hazards that
come from reaching a callee with a `jmp`. It saves and restores `ebp` and touches only `eax`,
`ecx` and `edx`, all of which the stock call already clobbered and none of which the builder holds
live across the site.

**Determinism.** Which structures a camp unpacks with changes object ids and the frame CRC, so this
is simulation state: **every peer needs the same binary**, and replays do not play back on a stock
one. The gate itself reads only logic state, so the added edge is not a source of divergence on a
uniformly patched lobby.

**No INI change.** The behaviour is unconditional. `CastleBehavior`'s module data is ``0x78`` bytes
with its last named field at ``+0x75``, so ``+0x76`` and ``+0x77`` are free if this is ever wanted
as a keyword; that would need a relocated field table and a Worldbuilder twin, and is deliberately
not part of this patch.

**Composition.** Order-independent: the cave is allocated past every existing section and
:meth:`verify` finds it by name. The only engine bytes it edits are the five at :data:`HOOK_VA`.
`foundation-rebind` is the other patch in this corner of the binary and touches neither the builder
nor the `BuildAssistant`; it edits ``0x008BB6CC`` / ``0x008BB955`` and calls
`CastleBehavior::onStructureBuilt`, which this patch neither edits nor reads.
"""

from __future__ import annotations

import struct

from ..addresses import BUILD_ASSISTANT_VTABLE
from ..asm import JE, Asm
from ..patcher import Patch
from ..utils import allocate_section, apply_byte_patch, find_section, va_to_offset

__all__ = [
    "ANCHORS",
    "BUILD_ASSISTANT_OBJECT_GATE",
    "BUILD_ASSISTANT_TERRAIN_GATE",
    "CASTLE_BUILD_MEMBER",
    "CASTLE_BUILD_MEMBER_ARGS",
    "CASTLE_BUILD_MEMBER_KEEP_TEST",
    "CASTLE_BUILD_MEMBER_REJECT",
    "CASTLE_LEGALITY_THUNK",
    "HOOK_ORIGINAL",
    "HOOK_VA",
    "IS_LOCATION_LEGAL",
    "IS_LOCATION_LEGAL_SLOT",
    "IS_LOCATION_LEGAL_SLOT_VA",
    "SECTION_NAME",
    "STOCK_FLAGS",
    "THUNK_CALL_TARGET",
    "UNCONDITIONAL_FLAGS",
    "CastleUnpackClearancePatch",
    "build_code",
]

SECTION_NAME = ".cstunp"  # 7 chars: the PE name field is 8 bytes and truncates silently

# IMAGE_SCN_CNT_CODE | MEM_EXECUTE | MEM_READ - the cave is pure code and is never written.
_CHARACTERISTICS = 0x20 | 0x20000000 | 0x40000000

#: `CastleBehavior::buildCastleMember(entry, arg)` - ``__thiscall``, one caller (the structure loop
#: at ``0x0079B903``), returns the created `Object *` or NULL. Named here because everything else
#: in this module is an offset into it.
CASTLE_BUILD_MEMBER = 0x007987EE

#: The `KindOf COMMANDCENTER` test that exempts the keep from the gate entirely, with the `jne`
#: that skips past it. Anchored, not edited: it is what makes "only the fortress is safe today" a
#: fact about this build rather than a claim, and it is the shape the patch generalises.
CASTLE_BUILD_MEMBER_KEEP_TEST = 0x00798951
CASTLE_BUILD_MEMBER_KEEP_TEST_BYTES = bytes.fromhex("f6860a01000002d95d08597522")

#: The builder's own argument setup for the gate, ending exactly at :data:`HOOK_VA`. Anchoring it
#: is how the cave's forwarding is checked against the real thing: it fixes the order the five
#: arguments are pushed in, and the ``6a 05`` inside it is the stock flags word the cave passes
#: through unchanged on its first ask.
CASTLE_BUILD_MEMBER_ARGS = 0x0079895E
CASTLE_BUILD_MEMBER_ARGS_BYTES = bytes.fromhex("8b4708d945088b4f04506a0551d91c24568d45cc50")

#: The `test eax, eax` / `jne` that follows the call: non-zero means **drop this entry**, and the
#: `jne` goes to ``0x00798849``, which zeroes `esi` and returns NULL. The patch changes what the
#: call answers, never what the caller does with the answer, so this window has to survive.
CASTLE_BUILD_MEMBER_REJECT = 0x00798978
CASTLE_BUILD_MEMBER_REJECT_BYTES = bytes.fromhex("85c00f85c9feffff")

#: The five-byte `call` the patch repoints, and its stock bytes.
HOOK_VA = 0x00798973
HOOK_ORIGINAL = bytes.fromhex("e81ef1ffff")

#: The thunk the builder calls: it ORs ``0x100`` into the flags word and forwards to
#: `TheBuildAssistant`'s vtable ``+0x44``. ``__stdcall``, five arguments, ``ret 0x14`` - which is
#: the calling convention the cave has to reproduce, because it takes this function's place.
CASTLE_LEGALITY_THUNK = 0x00797A96
CASTLE_LEGALITY_THUNK_BYTES = bytes.fromhex("558bec8b5514d945108b0d0082de00")

#: Where :data:`HOOK_ORIGINAL` actually goes, decoded from its own displacement rather than
#: written down, so "the site this patch repoints is the legality call" is derived and can be
#: asserted instead of trusted.
THUNK_CALL_TARGET = HOOK_VA + 5 + struct.unpack("<i", HOOK_ORIGINAL[1:5])[0]

#: `BuildAssistant::isLocationLegalToBuild`, and the vtable slot the thunk dispatches through.
#: The slot is anchored to this address, which is what proves the thunk still reaches the function
#: whose flag semantics the cave depends on.
IS_LOCATION_LEGAL = 0x00796810
IS_LOCATION_LEGAL_SLOT = 0x44
IS_LOCATION_LEGAL_SLOT_VA = BUILD_ASSISTANT_VTABLE + IS_LOCATION_LEGAL_SLOT

#: Inside `isLocationLegalToBuild`: where bit ``0x4`` of the flags word gates the object-clearance
#: test (``and dword [ebp+8], ecx`` with `ecx` = 4), and where bit ``0x1`` gates the terrain tests.
#: These two windows are the patch's whole premise - that clearing the flags word is what stops
#: objects and terrain vetoing - so a build that moved either bit refuses to apply.
BUILD_ASSISTANT_OBJECT_GATE = 0x007968A5
BUILD_ASSISTANT_OBJECT_GATE_BYTES = bytes.fromhex("c1e8076a04240189550859214d08")
BUILD_ASSISTANT_TERRAIN_GATE = 0x00796A9A
BUILD_ASSISTANT_TERRAIN_GATE_BYTES = bytes.fromhex("f64514010f84")

#: The flags word the builder passes (bit ``0x1`` terrain, bit ``0x4`` objects), and the one the
#: cave retries with. Zero leaves only the three tests no flag controls: map extent,
#: `CANNOT_BUILD_NEAR_SUPPLIES` proximity and `WALL_HUB` anchor proximity.
STOCK_FLAGS = 0x05
UNCONDITIONAL_FLAGS = 0x00

#: The first bytes at every address the cave calls or the patch reasons from, as a `{va: bytes}`
#: map. The hooked call's own five bytes are asserted by `apply_byte_patch`; these are the thunk
#: the cave calls, the vtable slot behind it, the two flag gates the retry depends on, and the
#: three windows in the builder that fix the argument order and what the caller does with the
#: answer. A build whose layout moved fails here instead of on a wild call.
ANCHORS = {
    CASTLE_BUILD_MEMBER_KEEP_TEST: CASTLE_BUILD_MEMBER_KEEP_TEST_BYTES,
    CASTLE_BUILD_MEMBER_ARGS: CASTLE_BUILD_MEMBER_ARGS_BYTES,
    CASTLE_BUILD_MEMBER_REJECT: CASTLE_BUILD_MEMBER_REJECT_BYTES,
    CASTLE_LEGALITY_THUNK: CASTLE_LEGALITY_THUNK_BYTES,
    IS_LOCATION_LEGAL_SLOT_VA: struct.pack("<I", IS_LOCATION_LEGAL),
    BUILD_ASSISTANT_OBJECT_GATE: BUILD_ASSISTANT_OBJECT_GATE_BYTES,
    BUILD_ASSISTANT_TERRAIN_GATE: BUILD_ASSISTANT_TERRAIN_GATE_BYTES,
}


def _ask(a: Asm, flags: int | None) -> None:
    """Emit one forwarded call to the legality thunk, from the cave's own frame.

    ``flags`` of None passes the caller's word straight through, which is what makes the first ask
    bit-for-bit the stock question; an int pushes that immediate instead. The four other arguments
    are forwarded unchanged either way, so the two asks differ in exactly one dword.
    """
    a.emit(0xFF, 0x75, 0x18)  # push [ebp+0x18]  ; the flag object, the "builder"
    if flags is None:
        a.emit(0xFF, 0x75, 0x14)  # push [ebp+0x14]  ; the caller's own flags word
    else:
        a.emit(0x6A, flags)  # push imm8
    a.emit(0xFF, 0x75, 0x10)  # push [ebp+0x10]  ; the angle
    a.emit(0xFF, 0x75, 0x0C)  # push [ebp+0x0c]  ; the template
    a.emit(0xFF, 0x75, 0x08)  # push [ebp+0x08]  ; the position
    a.call_absolute(CASTLE_LEGALITY_THUNK)


def build_code(base_va: int) -> bytes:
    """The cave: `isLocationLegalToBuild`, asked a second time without the flags word.

    Entered by the `call` at :data:`HOOK_VA` in place of :data:`CASTLE_LEGALITY_THUNK`, so it takes
    that function's arguments and its ``ret 0x14``.
    """
    a = Asm(base_va)
    a.emit(0x55)  # push ebp
    a.emit(0x8B, 0xEC)  # mov  ebp, esp

    _ask(a, None)  # the stock question, unchanged
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "legal")  # legal: that is the answer

    _ask(a, UNCONDITIONAL_FLAGS)  # only the tests no flag controls

    a.label("legal")
    a.emit(0x5D)  # pop  ebp
    a.emit(0xC2, 0x14, 0x00)  # ret  0x14  ; the thunk's own cleanup, unchanged
    return a.finish()


class CastleUnpackClearancePatch(Patch):
    name = "castle-unpack-clearance"
    author = "officialNecro"
    description = (
        "Stop a camp or castle unpack silently dropping structures that terrain or a blocking "
        "object vetoed, which is what loses buildings from a rotated camp. No INI change"
    )

    def apply(self, data: bytearray) -> None:
        hook_off = va_to_offset(data, HOOK_VA)
        if hook_off is None:
            raise ValueError(f"{HOOK_VA:#010x} is not mapped - not the expected build")
        # Prove the call being repointed is the legality call, that the thunk it reached still
        # takes the arguments the cave forwards, and that the two flag bits the retry drops are
        # still where they are read.
        self._check_anchors(data)
        section_va = allocate_section(data, SECTION_NAME, build_code, _CHARACTERISTICS)
        call = b"\xe8" + struct.pack("<i", section_va - (HOOK_VA + 5))
        apply_byte_patch(
            data,
            hook_off,
            HOOK_ORIGINAL,
            call,
            "CastleBehavior unpack legality call -> castle-unpack-clearance cave",
        )

    @staticmethod
    def _check_anchors(data: bytes | bytearray) -> None:
        if THUNK_CALL_TARGET != CASTLE_LEGALITY_THUNK:
            raise ValueError(
                f"the hooked call goes to {THUNK_CALL_TARGET:#010x}, not the legality thunk at "
                f"{CASTLE_LEGALITY_THUNK:#010x}"
            )
        for va, expected in ANCHORS.items():
            off = va_to_offset(data, va)
            if off is None:
                raise ValueError(f"{va:#010x} is not mapped - not the expected build")
            got = bytes(data[off : off + len(expected)])
            if got != expected:
                raise ValueError(
                    f"{va:#010x} holds {got.hex()}, expected {expected.hex()} - the castle "
                    "unpack's build-legality path is not this build's, so the cave would forward "
                    "the wrong arguments or clear the wrong flags"
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
        if data[off] != 0xE8:
            return [f"{HOOK_VA:#010x} is not a call - the hook is not installed"]
        target = HOOK_VA + 5 + struct.unpack_from("<i", data, off + 1)[0]
        if target != section_va:
            problems.append(f"hook calls {target:#010x}, expected {section_va:#010x}")
        code = build_code(section_va)
        if bytes(data[section_off : section_off + len(code)]) != code:
            problems.append(f"the {SECTION_NAME} cave does not hold the expected routine")
        return problems
