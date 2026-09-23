"""Let a structure's rally point name a hero or unit, so produced units go where it is rather than
where it stood.

`MSG_SET_RALLY_POINT` already carries the object under the cursor, and the handler drops it. The
patch grows `QueueProductionExitUpdate` by a dword to record that object, clears it whenever a plain
rally point is set, and when a unit is released (it would walk to the stored point at `0x008A3D32`)
sends it to where the object stands at that moment. No client edit is needed: the context test
already accepts a hero (`0x0069D517`). No INI change; logic-side, so every peer needs the same
binary.

Derivation: `../../docs/smart-rally-points.md`.
"""

from __future__ import annotations

import argparse
import struct

from ...asm import JE, JNE, JZ, Asm
from ...patcher import Patch
from ...utils import allocate_section, apply_byte_patch, find_section, va_to_offset

__all__ = [
    "ANCHORS",
    "EXIT_VTABLE",
    "SECTION_NAME",
    "SmartRallyPatch",
    "build_code",
    "entry_points",
]

SECTION_NAME = ".rally"

# IMAGE_SCN_CNT_CODE | MEM_EXECUTE | MEM_READ - the cave is pure code and is never written.
_CHARACTERISTICS = 0x20 | 0x20000000 | 0x40000000

# The engine

#: `QueueProductionExitUpdate`'s `ExitInterface` vtable, written by the one constructor at
#: `0x008A3978`. The record hook compares against it before writing, because
#: `Object::getExitInterface` also answers with other classes on whose layout `+0x24` is taken.
EXIT_VTABLE = 0x00C682C4

#: `Object::getExitInterface` - `__thiscall`, no arguments. Walks the module array at
#: `Object+0x24C` asking each module's vtable `+0x50`, then falls back to the contain module.
GET_EXIT_INTERFACE = 0x0068BB14

#: `Object::getRelationship` - `__thiscall`, `ret 4`. The engine's own rally-target test
#: (`0x008A3B87`) demands the answer `2`, and the spend hook demands the same, so an ally that
#: turns hostile stops being a rally target rather than becoming a feeding tube.
GET_RELATIONSHIP = 0x0068D7AB
RELATIONSHIP_ALLIED = 2

#: `TheGameLogic` and `GameLogic::findObjectByID` - `__thiscall`, `ret 4`.
THE_GAME_LOGIC = 0x00DE412C
FIND_OBJECT_BY_ID = 0x00449681

#: `AIUpdateInterface::aiMoveToPosition(const Coord3D *, CommandSourceType)` - `__thiscall`,
#: `ret 8`. The call the stock walk-to-the-point arm makes.
AI_MOVE_TO_POSITION = 0x0066C4CA

#: `AIUpdateInterface::aiGuardObject(Object *, GuardMode, CommandSourceType)` - `__thiscall`,
#: `ret 0xC`. Reached from the `MSG_DO_GUARD_OBJECT` handler through the group walker at
#: `0x00772736`, whose argument order this reproduces.
#:
#: **It can refuse.** The order reaches `AIUpdate::privateGuardObject` (`0x00664B19`, module
#: vtable `+0x100`) through the state dispatch at `0x0066AE61`, and that opens with three gates
#: - `Object::testStatus(38)`, the can-this-be-moved predicate at `0x00690E97`, and KindOf
#: `PROJECTILE` - any of which makes it `return -1` **having touched nothing**. The wrapper does
#: not pass that verdict back usably (`0x0077185F` clobbers `eax` on one edge), so the cave reads
#: the effect instead: see `AI_GUARD_TARGET_OFFSET`.
AI_GUARD_OBJECT = 0x00771805

#: What `privateGuardObject` writes on success, as a displacement from the `AIUpdate` **module**
#: (`Object+0x260`, one `0x20` short of the interface every order is issued through): the guarded
#: object's `ObjectID`, from `0x00664B73`. Reading it back and comparing against the id we asked
#: for is how the cave learns whether the order took, without depending on a return value.
AI_GUARD_TARGET_OFFSET = 0x64
GUARD_MODE_NORMAL = 0

#: `CommandSourceType`. The stock rally path issues its orders as `CMD_FROM_AI`, and the move form
#: copies it. The guard form issues `CMD_FROM_PLAYER` instead, because that is what the engine's own
#: `MSG_DO_GUARD_OBJECT` path passes (`0x0077ABEA`) and a guard is a standing order that has to
#: survive the unit's idle behaviour rather than a short move that completes before anything can
#: reconsider it.
COMMAND_FROM_PLAYER = 0
COMMAND_FROM_AI = 2

#: The handler's single-producer rally routine - `__cdecl`, four arguments, caller cleans,
#: answers in `al`. It can refuse (no path to the point), which is why the record hook tests the
#: answer before it stores anything.
SET_RALLY_POINT_FOR = 0x00779544

#: The position setter, `ExitInterface` slot `+0x1C`. Reached only through that slot, and only
#: `QueueProductionExitUpdate`'s vtable holds it, which is what makes the clear hook safe.
SET_RALLY_POSITION = 0x008A3BCC

#: The release routine, `ExitInterface` slot `+0x2C`. `esi` is the interface and `edi` the unit
#: being let out for the whole of it.
RELEASE_UNIT = 0x008A3BF8

#: `ControlBar::setRallyPointMarker(const Coord3D *)` - `__thiscall`, `ret 4`. A NULL point
#: destroys the marker; anything else creates or moves it, copying the point into the drawable
#: through `Drawable::setPosition` (`0x006713E1`) rather than keeping the pointer. That copy is
#: what makes it safe for the marker routine to answer with a pointer into a live `Object`.
SET_RALLY_POINT_MARKER = 0x0071D18F

# Structure offsets

#: The `ObjectID` this patch adds, as a displacement from the `ExitInterface` (module `+0x44`).
#: It sits immediately past the stock object, which is why `ALLOC_SIZE_VA` has to grow first.
TARGET_ID_OFFSET = 0x24

STOCK_MODULE_SIZE = 0x44
PATCHED_MODULE_SIZE = 0x48

#: `ExitInterface` `+0x14` is the "a rally point is set" flag the clear hook reproduces, and
#: `-0x18` is the producing `Object *` the spend hook asks the relationship of.
RALLY_SET_OFFSET = 0x14
PRODUCER_OFFSET = -0x18

OBJECT_ID_OFFSET = 0x74
OBJECT_POSITION_OFFSET = 0x38
OBJECT_AI_MODULE_OFFSET = 0x260

#: `AIUpdateInterface` is `AIUpdate` `+0x20`; every stock caller adds it by hand.
AI_INTERFACE_OFFSET = 0x20

#: The handler's frame slot holding the clicked `Coord3D`, as a displacement from its `ebp`.
FRAME_RALLY_POINT = -0x24

# The hooks

#: `push 0x44` in `QueueProductionExitUpdate`'s factory - the class's only allocation.
ALLOC_SIZE_VA = 0x0064E65C
ALLOC_SIZE_STOCK = bytes([0x6A, STOCK_MODULE_SIZE])
ALLOC_SIZE_PATCHED = bytes([0x6A, PATCHED_MODULE_SIZE])

#: The constructor's epilogue, displaced so the new field starts at zero. `ecx` is still zero here,
#: but the cave writes an explicit immediate rather than lean on that.
CTOR_HOOK_VA = 0x008A39AC
CTOR_HOOK_STOCK = bytes.fromhex("8bc65ec20800")  # mov eax,esi; pop esi; ret 8

#: The position setter's epilogue. `ebx` is the interface and `esi`/`edi` are already popped.
CLEAR_HOOK_VA = 0x008A3BF0
CLEAR_HOOK_STOCK = bytes.fromhex("c64314015b")  # mov byte [ebx+0x14],1; pop ebx

#: The handler's single-producer arm. `eax` is the resolved argument-3 object (or NULL), `edi` the
#: producer, `ebx` the function's zero register; the six displaced bytes are the first three
#: instructions of the stock call sequence, which the cave reproduces in full.
RECORD_HOOK_VA = 0x0077A2EF
RECORD_HOOK_STOCK = bytes.fromhex("536a018d45dc")  # push ebx; push 1; lea eax,[ebp-0x24]
RECORD_RESUME_VA = 0x0077A2FF

#: The two ControlBar sites that ask an exit interface where to draw the rally banner. Both hold
#: the identical seven bytes `mov edx,[eax]; mov ecx,eax; call [edx+0x20]` with the interface in
#: `eax`, and both follow it with `push eax; mov ecx,ebx` into `SET_RALLY_POINT_MARKER` - so one
#: routine serves both, reached by a `call` rather than a `jmp` so that its `ret` lands in the right
#: caller without either site needing its own trampoline.
MARKER_HOOK_VAS: tuple[int, ...] = (0x009443A0, 0x00945099)
MARKER_HOOK_STOCK = bytes.fromhex("8b108bc8ff5220")
MARKER_TAIL_STOCK = bytes.fromhex("508bcb")  # push eax; mov ecx,ebx - the answer goes to the marker

#: The head of the release routine's walk-to-the-point arm - the whole of the exit-path call,
#: displaced so that a smart rally can decline to make it. `Object` vtable `+0x244`, on the
#: container the unit is leaving (`[ebp-4]`, from the contain module's vtable `+0x7C`), handed
#: the rally point copy at `[ebp-0x14]`. **The engine's own rally-at-object arm never calls it**
#: (`0x008A3CDE` goes straight to model conditions and `aiEnter`), and issuing it alongside an
#: object order is what walked produced units to the target and then back to the stored point.
SPEND_HOOK_VA = 0x008A3D14
SPEND_HOOK_STOCK = bytes.fromhex("8b4dfc8b018d55ec52ff9044020000")

#: `Object` vtable slot for that call, and the two frame slots it reads, as displacements from the
#: release routine's `ebp`.
EXIT_PATH_SLOT = 0x244
FRAME_CONTAINER = -0x04
FRAME_RALLY_COPY = -0x14
SPEND_FALLBACK_VA = 0x008A3D29
SPEND_RESUME_VA = 0x008A3D37

#: The first bytes at each address the cave calls or jumps to, plus the windows that prove the
#: hooks sit where this patch thinks they do, as a `{va: bytes}` map. A build whose layout moved
#: fails here rather than on a wild jump, a mis-aimed `this`, or - worst of the three - a write
#: four bytes past a module that was never grown.
ANCHORS: dict[int, bytes] = {
    ALLOC_SIZE_VA: ALLOC_SIZE_STOCK,
    CTOR_HOOK_VA: CTOR_HOOK_STOCK,
    CLEAR_HOOK_VA: CLEAR_HOOK_STOCK,
    RECORD_HOOK_VA: RECORD_HOOK_STOCK,
    SPEND_HOOK_VA: SPEND_HOOK_STOCK,
    MARKER_HOOK_VAS[0]: MARKER_HOOK_STOCK,
    MARKER_HOOK_VAS[1]: MARKER_HOOK_STOCK,
    # What each marker site does with the answer, which is what makes returning a different
    # `Coord3D *` enough to move the banner and unable to affect anything else.
    MARKER_HOOK_VAS[0] + len(MARKER_HOOK_STOCK): MARKER_TAIL_STOCK,
    MARKER_HOOK_VAS[1] + len(MARKER_HOOK_STOCK): MARKER_TAIL_STOCK,
    SET_RALLY_POINT_MARKER: bytes.fromhex("b87df3b800"),
    # The factory whose `push 0x44` is grown, so the size belongs to this class and no other.
    0x0064E651: bytes.fromhex("b8705fb800"),
    # The constructor's entry and its `mov [esi+0x20], EXIT_VTABLE`, which is what ties the vtable
    # the record hook compares against to the object whose size this patch grows.
    0x008A3948: bytes.fromhex("56ff74240c"),
    0x008A3978: bytes.fromhex("c74620") + struct.pack("<I", EXIT_VTABLE),
    # Slots +0x1C and +0x2C of that vtable, holding the two routines hooked inside the class.
    EXIT_VTABLE + 0x1C: struct.pack("<I", SET_RALLY_POSITION),
    EXIT_VTABLE + 0x2C: struct.pack("<I", RELEASE_UNIT),
    SET_RALLY_POSITION: bytes.fromhex("53568b74"),
    RELEASE_UNIT: bytes.fromhex("558bec"),
    # `call findObjectByID` on argument 3 - the proof that `eax` holds the target at the hook.
    0x0077A2C8: bytes.fromhex("e8b4f3ccff"),
    RECORD_RESUME_VA: bytes.fromhex("e9e22c0000"),
    SPEND_FALLBACK_VA: bytes.fromhex("6a02"),
    SPEND_RESUME_VA: bytes.fromhex("5f"),
    # The routines the cave calls.
    SET_RALLY_POINT_FOR: bytes.fromhex("b85c30b900"),
    GET_EXIT_INTERFACE: bytes.fromhex("56578bf9"),
    FIND_OBJECT_BY_ID: bytes.fromhex("837c240400"),
    GET_RELATIONSHIP: bytes.fromhex("538b5c2408"),
    AI_MOVE_TO_POSITION: bytes.fromhex("b81173b800"),
    AI_GUARD_OBJECT: bytes.fromhex("b8672bb900"),
}

#: The cave's routines, in the order they are laid out. Each is the target of at least one hook.
ROUTINES = ("ctor_tail", "clear", "record", "spend", "marker")


def _assemble(base_va: int, guard: bool) -> Asm:
    a = Asm(base_va)

    # The constructor's epilogue, with the new field zeroed ahead of it
    a.label("ctor_tail")
    a.emit(0x83, 0x66, 0x44, 0x00)  # and dword [esi+0x44], 0
    a.emit(0x8B, 0xC6)  # mov eax, esi
    a.emit(0x5E)  # pop esi
    a.emit(0xC2, 0x08, 0x00)  # ret 8

    # The position setter's epilogue: storing a point drops whatever object it replaces
    a.label("clear")
    a.emit(0xC6, 0x43, RALLY_SET_OFFSET, 0x01)  # mov byte [ebx+0x14], 1
    a.emit(0x83, 0x63, TARGET_ID_OFFSET, 0x00)  # and dword [ebx+0x24], 0
    a.emit(0x5B)  # pop ebx
    a.emit(0xC2, 0x04, 0x00)  # ret 4

    # Record the target the order named, once the engine has accepted the rally point
    a.label("record")
    # `eax` is argument 3's object, or NULL for a click on bare ground. It has to survive a call
    # that may clobber it, and every register here is either live or caller-saved, so it goes on
    # the stack - below the reproduced argument block, which the callee addresses off `esp`.
    a.emit(0x50)  # push eax
    a.emit(0x53)  # push ebx           ; the handler's zero
    a.emit(0x6A, 0x01)  # push 1
    a.emit(0x8D, 0x45, FRAME_RALLY_POINT & 0xFF)  # lea eax, [ebp-0x24]
    a.emit(0x50)  # push eax
    a.emit(0x57)  # push edi           ; the producer
    a.call_absolute(SET_RALLY_POINT_FOR)
    a.emit(0x83, 0xC4, 0x10)  # add esp, 0x10
    a.emit(0x84, 0xC0)  # test al, al
    a.jcc(JZ, "record_done")  # refused (no path) - leave the standing target alone
    a.emit(0x8B, 0xCF)  # mov ecx, edi
    a.call_absolute(GET_EXIT_INTERFACE)
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JZ, "record_done")
    # Only `QueueProductionExitUpdate` has the field; on every other exit interface `+0x24` is
    # somebody else's, so the vtable is checked before a single byte is written.
    a.emit(0x81, 0x38, struct.pack("<I", EXIT_VTABLE))  # cmp dword [eax], EXIT_VTABLE
    a.jcc(JNE, "record_done")
    a.emit(0x8B, 0x0C, 0x24)  # mov ecx, [esp]     ; the stashed target
    a.emit(0x33, 0xD2)  # xor edx, edx
    a.emit(0x85, 0xC9)  # test ecx, ecx
    a.jcc(JZ, "record_store")  # bare ground: store zero, which clears
    a.emit(0x8B, 0x51, OBJECT_ID_OFFSET)  # mov edx, [ecx+0x74]
    a.label("record_store")
    a.emit(0x89, 0x50, TARGET_ID_OFFSET)  # mov [eax+0x24], edx
    a.label("record_done")
    a.emit(0x83, 0xC4, 0x04)  # add esp, 4
    a.jmp_absolute(RECORD_RESUME_VA)

    # Spend it: send the unit to the object rather than to the point
    a.label("spend")
    a.emit(0x8B, 0x46, TARGET_ID_OFFSET)  # mov eax, [esi+0x24]
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JZ, "spend_fallback")
    a.emit(0x8B, 0x0D, struct.pack("<I", THE_GAME_LOGIC))  # mov ecx, [TheGameLogic]
    a.emit(0x50)  # push eax
    a.call_absolute(FIND_OBJECT_BY_ID)
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JZ, "spend_fallback")  # the target died - walk to where it fell
    # `ebx` is the release routine's zero register and is dead from here to its `pop ebx`, so it
    # is the one register free to carry the target across the relationship call.
    a.emit(0x8B, 0xD8)  # mov ebx, eax
    a.emit(0x8B, 0x4E, PRODUCER_OFFSET & 0xFF)  # mov ecx, [esi-0x18]
    a.emit(0x53)  # push ebx
    a.call_absolute(GET_RELATIONSHIP)
    a.emit(0x83, 0xF8, RELATIONSHIP_ALLIED)  # cmp eax, 2
    a.jcc(JNE, "spend_fallback")
    # A live, allied target: order the unit at it and **do not** make the exit-path call. The
    # engine's own rally-at-object arm does not make it either, and making it alongside an object
    # order is a second destination that reasserts itself once the first one is reached.
    a.emit(0x8B, 0x8F, struct.pack("<I", OBJECT_AI_MODULE_OFFSET))  # mov ecx, [edi+0x260]
    a.emit(0x83, 0xC1, AI_INTERFACE_OFFSET)  # add ecx, 0x20
    if guard:
        a.emit(0x6A, COMMAND_FROM_PLAYER)  # push 0
        a.emit(0x6A, GUARD_MODE_NORMAL)  # push 0
        a.emit(0x53)  # push ebx
        a.call_absolute(AI_GUARD_OBJECT)
        # Did it take? `privateGuardObject` records the guarded id on success and returns -1
        # having done nothing on any of its three gates, so the id it left is the verdict.
        a.emit(0x8B, 0x87, struct.pack("<I", OBJECT_AI_MODULE_OFFSET))  # mov eax, [edi+0x260]
        a.emit(0x8B, 0x40, AI_GUARD_TARGET_OFFSET)  # mov eax, [eax+0x64]
        a.emit(0x3B, 0x43, OBJECT_ID_OFFSET)  # cmp eax, [ebx+0x74]
        a.jcc(JE, "spend_done")
        # Refused. The engine has left the unit with nothing, so give it the form that works
        # rather than let it walk out of the door and idle.
        a.emit(0x8B, 0x8F, struct.pack("<I", OBJECT_AI_MODULE_OFFSET))  # mov ecx, [edi+0x260]
        a.emit(0x83, 0xC1, AI_INTERFACE_OFFSET)  # add ecx, 0x20
    a.emit(0x6A, COMMAND_FROM_AI)  # push 2
    a.emit(0x8D, 0x43, OBJECT_POSITION_OFFSET)  # lea eax, [ebx+0x38]
    a.emit(0x50)  # push eax
    a.call_absolute(AI_MOVE_TO_POSITION)
    a.label("spend_done")
    a.jmp_absolute(SPEND_RESUME_VA)

    # No target, a dead one, or one that stopped being allied: reproduce the fifteen displaced
    # bytes exactly and re-enter the stock arm, so a rejected target costs nothing.
    a.label("spend_fallback")
    a.emit(0x8B, 0x4D, FRAME_CONTAINER & 0xFF)  # mov ecx, [ebp-4]
    a.emit(0x8B, 0x01)  # mov eax, [ecx]
    a.emit(0x8D, 0x55, FRAME_RALLY_COPY & 0xFF)  # lea edx, [ebp-0x14]
    a.emit(0x52)  # push edx
    a.emit(0xFF, 0x90, struct.pack("<I", EXIT_PATH_SLOT))  # call [eax+0x244]
    a.emit(0x8B, 0x8F, struct.pack("<I", OBJECT_AI_MODULE_OFFSET))  # mov ecx, [edi+0x260]
    a.jmp_absolute(SPEND_FALLBACK_VA)

    # Draw the banner where the target is, not where the click was
    # Called rather than jumped to, from two sites that displaced the same seven bytes, so the
    # `ret` goes back to whichever asked. `eax` is the exit interface on entry and the `Coord3D *`
    # the ControlBar draws at on exit; nothing else is touched but `ecx` and `edx`, which both
    # sites reload.
    a.label("marker")
    a.emit(0x50)  # push eax            ; the interface, across the call
    a.emit(0x8B, 0x10)  # mov edx, [eax]
    a.emit(0x8B, 0xC8)  # mov ecx, eax
    a.emit(0xFF, 0x52, 0x20)  # call [edx+0x20]     ; the displaced getRallyPoint
    a.emit(0x59)  # pop ecx             ; the interface back
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JZ, "marker_done")  # NULL still means "destroy the marker"
    a.emit(0x81, 0x39, struct.pack("<I", EXIT_VTABLE))  # cmp dword [ecx], EXIT_VTABLE
    a.jcc(JNE, "marker_done")  # another class: +0x24 is not our field
    a.emit(0x8B, 0x51, TARGET_ID_OFFSET)  # mov edx, [ecx+0x24]
    a.emit(0x85, 0xD2)  # test edx, edx
    a.jcc(JZ, "marker_done")  # a plain rally point draws where it always did
    a.emit(0x50)  # push eax            ; the stored point, as the fallback
    a.emit(0x51)  # push ecx
    a.emit(0x8B, 0x0D, struct.pack("<I", THE_GAME_LOGIC))  # mov ecx, [TheGameLogic]
    a.emit(0x52)  # push edx
    a.call_absolute(FIND_OBJECT_BY_ID)
    a.emit(0x59)  # pop ecx
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JZ, "marker_fallback")
    # The banner has to say what the units will do, so it asks the same question `spend` asks.
    a.emit(0x50)  # push eax            ; the target
    a.emit(0x8B, 0x49, PRODUCER_OFFSET & 0xFF)  # mov ecx, [ecx-0x18]
    a.emit(0x50)  # push eax
    a.call_absolute(GET_RELATIONSHIP)
    a.emit(0x83, 0xF8, RELATIONSHIP_ALLIED)  # cmp eax, 2
    a.emit(0x58)  # pop eax             ; the target back; `pop` leaves the flags
    a.jcc(JNE, "marker_fallback")
    a.emit(0x83, 0xC4, 0x04)  # add esp, 4          ; drop the fallback
    a.emit(0x83, 0xC0, OBJECT_POSITION_OFFSET)  # add eax, 0x38
    a.emit(0xC3)  # ret

    a.label("marker_fallback")
    a.emit(0x58)  # pop eax             ; the stored point
    a.label("marker_done")
    a.emit(0xC3)  # ret
    return a


def build_code(base_va: int, guard: bool = False) -> bytes:
    """The cave: four routines, one per hook, laid out in `ROUTINES` order."""
    return _assemble(base_va, guard).finish()


def entry_points(base_va: int, guard: bool = False) -> dict[str, int]:
    """Where each routine starts, taken from the layout that was actually emitted rather than
    counted a second time by hand."""
    a = _assemble(base_va, guard)
    return {name: a.label_va(name) for name in ROUTINES}


class SmartRallyPatch(Patch):
    name = "smart-rally"
    author = "officialNecro"
    experimental = True
    description = (
        "Let a structure's rally point name a hero or unit, so produced units go where the target "
        "is rather than where it stood. No INI change"
    )

    def __init__(self, guard: bool = False) -> None:
        """`guard` issues `aiGuardObject` rather than a move to the target's current position,
        so the units coming out follow and defend it instead of walking over once."""
        self.guard = guard

    #: The five-byte jump each routine is reached by, as `{hook va: (stock bytes, routine)}`.
    #: `record`, `spend` and the constructor displace six bytes and take a trailing `nop`.
    _JUMP_HOOKS = {
        CTOR_HOOK_VA: (CTOR_HOOK_STOCK, "ctor_tail"),
        CLEAR_HOOK_VA: (CLEAR_HOOK_STOCK, "clear"),
        RECORD_HOOK_VA: (RECORD_HOOK_STOCK, "record"),
        SPEND_HOOK_VA: (SPEND_HOOK_STOCK, "spend"),
    }

    #: The sites reached by a `call` instead, so that one routine can serve both and `ret` to the
    #: right one. Seven displaced bytes, five of `call rel32` and two of `nop`.
    _CALL_HOOKS = dict.fromkeys(MARKER_HOOK_VAS, (MARKER_HOOK_STOCK, "marker"))

    @property
    def _hooks(self) -> dict[int, tuple[bytes, str, int]]:
        """Every hook, as `{va: (stock bytes, routine, opcode)}`."""
        return {
            **{va: (stock, name, 0xE9) for va, (stock, name) in self._JUMP_HOOKS.items()},
            **{va: (stock, name, 0xE8) for va, (stock, name) in self._CALL_HOOKS.items()},
        }

    def apply(self, data: bytearray) -> None:
        self._check_anchors(data)
        section_va = allocate_section(
            data, SECTION_NAME, lambda va: build_code(va, self.guard), _CHARACTERISTICS
        )
        entries = entry_points(section_va, self.guard)

        # The size first: every other edit assumes the field it writes is inside the object.
        apply_byte_patch(
            data,
            self._offset(data, ALLOC_SIZE_VA),
            ALLOC_SIZE_STOCK,
            ALLOC_SIZE_PATCHED,
            f"QueueProductionExitUpdate {STOCK_MODULE_SIZE:#x} -> {PATCHED_MODULE_SIZE:#x}",
        )
        for hook_va, (stock, routine, opcode) in self._hooks.items():
            branch = bytes([opcode]) + struct.pack("<i", entries[routine] - (hook_va + 5))
            branch += b"\x90" * (len(stock) - len(branch))
            apply_byte_patch(
                data,
                self._offset(data, hook_va),
                stock,
                branch,
                f"{hook_va:#010x} -> smart-rally {routine}",
            )

    @staticmethod
    def _offset(data: bytes | bytearray, va: int) -> int:
        off = va_to_offset(data, va)
        if off is None:
            raise ValueError(f"{va:#010x} is not mapped - not the expected build")
        return off

    @classmethod
    def _check_anchors(cls, data: bytes | bytearray) -> None:
        for va, expected in ANCHORS.items():
            off = cls._offset(data, va)
            got = bytes(data[off : off + len(expected)])
            if got != expected:
                raise ValueError(
                    f"{va:#010x} holds {got.hex()}, expected {expected.hex()} - this build's "
                    "production-exit layout is not the one smart-rally was derived against, so "
                    "the patch would write past a module it had not grown"
                )

    def verify(self, data: bytes | bytearray) -> list[str]:
        problems: list[str] = []
        located = find_section(data, SECTION_NAME)
        if located is None:
            return [f"{SECTION_NAME} section is absent"]
        section_va, section_off, _ = located

        size_off = va_to_offset(data, ALLOC_SIZE_VA)
        if size_off is None:
            return [f"{ALLOC_SIZE_VA:#010x} is not mapped by any section"]
        if bytes(data[size_off : size_off + 2]) != ALLOC_SIZE_PATCHED:
            problems.append(
                f"{ALLOC_SIZE_VA:#010x} does not allocate {PATCHED_MODULE_SIZE:#x} bytes - the "
                "target id would be written past the module"
            )

        entries = entry_points(section_va, self.guard)
        for hook_va, (_stock, routine, opcode) in self._hooks.items():
            off = va_to_offset(data, hook_va)
            if off is None:
                problems.append(f"{hook_va:#010x} is not mapped by any section")
                continue
            if data[off] != opcode:
                problems.append(f"{hook_va:#010x} does not branch - the {routine} hook is absent")
                continue
            target = hook_va + 5 + struct.unpack_from("<i", data, off + 1)[0]
            if target != entries[routine]:
                problems.append(
                    f"{hook_va:#010x} jumps to {target:#010x}, expected {entries[routine]:#010x}"
                )

        code = build_code(section_va, self.guard)
        if bytes(data[section_off : section_off + len(code)]) != code:
            problems.append(f"the {SECTION_NAME} cave does not hold the expected routines")
        return problems

    @classmethod
    def detect(cls, data: bytes | bytearray) -> Patch | None:
        """Recover which order form the cave was built with, by asking both."""
        for guard in (False, True):
            try:
                patch = cls(guard=guard)
                if not patch.verify(data):
                    return patch
            except (ValueError, KeyError, IndexError, TypeError, struct.error):
                return None
        return None

    @classmethod
    def add_cli_arguments(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--guard",
            action="store_true",
            help=(
                "issue aiGuardObject instead of a move to the target's current position, so units "
                "coming out follow and defend the target rather than walking to it once. KNOWN "
                "DEFECT: units have been seen walking to the spawn-time position and then off to "
                "an unrelated one; see the doc before relying on it"
            ),
        )

    @classmethod
    def from_cli_args(cls, args: argparse.Namespace) -> Patch:
        return cls(guard=bool(getattr(args, "guard", False)))

    def __str__(self) -> str:
        return f"{self.name} (guard)" if self.guard else self.name
