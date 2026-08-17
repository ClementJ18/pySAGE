"""The live-bridge patch: let an external process inject orders into the message stream.

Targets the ROTWK SAGE-engine `game.dat` build ``2.01.2614.37001``. Every address below is
derived in ``../docs/message-stream.md``; this module implements what section 4a designs.

**What it does.** Appends a ``.livebrg`` PE section holding a small command buffer plus a
hook routine, and redirects the entry of ``GameLogic::update`` into it. Once per logic frame
the hook checks the buffer; when an order is pending it calls ``TheMessageStream``'s
``appendMessage``, appends each argument through the engine's own ``append*Argument``
helpers, and clears the pending flag.

**The camera is the second, separate command.** It is not an order and does not go through
the message stream: the camera is client state that the simulation never reads, so there is
nothing to network-order and nothing to desync. The hook calls ``TheTacticalView``'s
``setLocation`` (or ``getLocation``, to read the live camera back out) exactly as the game's
own camera-bookmark hotkeys do. Both directions matter - reading first is what lets a caller
change where the camera looks while keeping the zoom and facing it already had.

**Why a patch and not a DLL.** Order injection needs only a per-frame callback on the logic
thread and a place to read bytes from. With no ASLR the buffer's address is a constant, so
the writer just uses ``WriteProcessMemory`` - no loader, no injector, no proxy library. Real
per-frame *observation* is the thing that wants C++, and that is a later milestone.

**Why the entry and not the tick.** The frame counter increment at ``0x0062E577`` is
``inc dword ptr [esi+0x40]`` - three bytes, and the instruction after it is the target of a
nearby ``je``, so five bytes cannot be taken there. ``GameLogic::update``'s entry instruction
is ``mov eax, 0xB841B0``, exactly five bytes, at a function entry: one inbound target by
construction, and a plain constant load that re-emits trivially in the cave.

**Injection is ordered through the normal path.** Orders entering via ``appendMessage`` are
network-ordered and check-summed like any human input. Calling logic functions directly
would bypass that and desync, which is the rule ``../../docs/ml-agent.md`` section 4 states.

**Composition.** Order-independent: the cave is allocated past every existing section and
:meth:`verify` finds it by name, and the only engine byte it edits is the five-byte entry of
``GameLogic::update``, which no other bundled patch touches.

Buffer layout, at the section base::

    +0x00  ready        dword   1 = an order is pending, cleared by the hook
    +0x04  order_type   dword   GameMessage::Type
    +0x08  arg_count    dword   number of arguments that follow
    +0x0C  (reserved)   dword
    +0x10  args         MAX_ARGS x 20 bytes: {type, v0, v1, v2, v3}
           appenders    one address per OrderArgumentType
           tag          dword   BUFFER_TAG - the layout this cave was built to
           camera       dword   CAMERA_APPLY / CAMERA_CAPTURE, cleared by the hook
           location     32 bytes ViewLocation, written by whichever direction ran

**The call command is the third, and it is opt-in.** ``--cheats`` appends a further block and
tags the buffer ``BUFFER_TAG_CHEATS``; without the flag neither the block nor the code that
serves it is emitted, and the section is byte-for-byte what it always was. It exists because a
whole class of things this engine does are *code*, not data: an object dies inside its damage
path, an upgrade's effects are applied by the module that grants it, and no amount of writing to
memory reaches either - a body poked to zero health simply stands there. The block a caller
drives is::

           ready        dword   1 = a call is pending, cleared by the hook
           mode         dword   CALL_DIRECT | CALL_VTABLE
           this         dword   ecx for the call; the object whose vtable CALL_VTABLE reads
           target       dword   a function VA, or a vtable byte offset when mode is CALL_VTABLE
           argc         dword   how many of args to push (0..CALL_MAX_ARGS)
           cleanup      dword   bytes to add to esp after the call: 0 for __thiscall/__stdcall
           result       dword   eax, written before ready is cleared
           args         CALL_MAX_ARGS dwords, pushed right-to-left
           scratch      CALL_SCRATCH_SIZE bytes at a known VA, for structures an argument points at

``scratch`` is the part that makes the command usable at all. The calls worth making take a
structure - ``BodyModule::attemptDamage`` wants a ``DamageInfo`` - and a writer outside the
process has nowhere in the game's heap it may safely build one. With no ASLR the scratch VA is a
constant, so the writer fills it with ``WriteProcessMemory`` and passes its address as an
argument, exactly as it already writes the order buffer.

An argument's four value slots carry either one value (the by-value types) or the bytes of a
structure the engine reads through a pointer (`Position` is three floats, `ScreenRectangle`
four, `ScreenPosition` two, `WideChar` one 16-bit unit).

``tag`` exists because the writer computes these offsets from *this module* while the cave
they address was assembled by whichever version of it patched the binary. Importing the
offsets keeps one process consistent; it says nothing about a `game.dat` patched last month.
A tag the writer does not recognise means the two disagree, and reading it is the difference
between a clear "re-apply the patch" and a camera write landing in the appender table.
"""

from __future__ import annotations

import argparse
import struct

from ...addresses import (
    APPEND_MESSAGE_VTABLE_SLOT,
    ARG_APPENDERS,
    GAME_LOGIC_UPDATE,
    GAME_LOGIC_UPDATE_ENTRY,
    GAME_LOGIC_UPDATE_VTABLE_SLOT,
    THE_MESSAGE_STREAM,
    THE_TACTICAL_VIEW,
    VIEW_GET_LOCATION_VTABLE_SLOT,
    VIEW_LOCATION_SIZE,
    VIEW_SET_LOCATION_VTABLE_SLOT,
)
from ...asm import JA, JE, JNE, Asm
from ...patcher import Patch
from ...utils import allocate_section, apply_byte_patch, find_section, va_to_offset

__all__ = [
    "ARG_APPENDERS",
    "BUFFER_TAG",
    "BUFFER_TAG_CHEATS",
    "CALL_DIRECT",
    "CALL_MAX_ARGS",
    "CALL_SCRATCH_SIZE",
    "CALL_VTABLE",
    "CAMERA_APPLY",
    "CAMERA_CAPTURE",
    "CODE_OFF",
    "LiveBridgePatch",
    "MAX_ARGS",
    "SECTION_NAME",
    "cheat_offsets",
    "code_offset",
]

SECTION_NAME = ".livebrg"

# IMAGE_SCN_CNT_CODE | MEM_EXECUTE | MEM_READ | MEM_WRITE - the buffer is written from
# outside the process, so the section cannot be read-only.
_CHARACTERISTICS = 0x20 | 0x20000000 | 0x40000000 | 0x80000000

# The hooked function and everything the cave calls live in `..addresses`, which is the one
# description of this build - `sage_live` reads the same module for the globals it walks.
HOOK_VA = GAME_LOGIC_UPDATE
HOOK_ORIGINAL = GAME_LOGIC_UPDATE_ENTRY
HOOK_RETURN_VA = HOOK_VA + len(HOOK_ORIGINAL)

# These four take the *address* of their data; the rest take the value itself.
BY_POINTER = (6, 7, 8, 10)

MAX_ARGS = 24
ARG_STRIDE = 20

READY_OFF = 0x00
ORDER_TYPE_OFF = 0x04
ARG_COUNT_OFF = 0x08
ARGS_OFF = 0x10
TABLE_OFF = ARGS_OFF + MAX_ARGS * ARG_STRIDE
TAG_OFF = TABLE_OFF + len(ARG_APPENDERS) * 4
CAMERA_OFF = TAG_OFF + 4
LOCATION_OFF = CAMERA_OFF + 4
# Where the optional cheat block starts, and therefore where the code starts without it. The
# block is appended rather than spliced in so that every offset above holds for both builds and
# a reader only has to branch on the tag for the fields that are genuinely absent.
CHEAT_OFF = LOCATION_OFF + VIEW_LOCATION_SIZE

# `'BL'` in the high half and the layout revision in the low, as one dword a stale binary
# cannot plausibly hold. Bump the revision whenever an offset above moves, so a writer built
# against the new layout refuses an image carrying the old one instead of writing into the
# middle of it. Revision 1 is the order-only buffer, which carried no tag at all.
BUFFER_TAG = 0x424C0002
#: The same layout with the cheat block present. A distinct tag rather than a flag elsewhere,
#: because the question a writer asks is "may I use the call command" and the answer has to be
#: in the one dword it already reads to decide whether it understands the buffer at all.
BUFFER_TAG_CHEATS = 0x424C0102

# The two camera directions, written into `camera` and cleared by the hook once served.
CAMERA_APPLY = 1
CAMERA_CAPTURE = 2

#: `call_mode` values. `CALL_DIRECT` calls `call_target` as an address; `CALL_VTABLE` reads the
#: vtable at `call_this` and calls the slot `call_target` bytes into it. The vtable form is the
#: one that matters for anything polymorphic - a body's `attemptDamage` is slot 0, and dispatching
#: through the object's own vtable is what lets an immortal body keep refusing damage instead of
#: being force-fed a subclass's implementation.
CALL_DIRECT = 0
CALL_VTABLE = 1

#: How many stack arguments the call command can push, and how much caller-writable space sits
#: after them. The scratch area exists because the interesting engine calls take a *structure* -
#: `attemptDamage` wants a `DamageInfo` - and a writer outside the process has nowhere in the
#: game's heap it may safely build one. Its address is a constant, so the writer fills it and
#: passes its VA as an argument.
CALL_MAX_ARGS = 8
CALL_SCRATCH_SIZE = 256


def cheat_offsets(base: int = 0) -> dict[str, int]:
    """The cheat block's fields, as ``base + CHEAT_OFF + field``.

    Pass the section's VA for addresses the cave can encode, or nothing for offsets into the
    section's bytes. `CHEAT_OFF` is added here rather than by each caller because forgetting it
    lands every field on the *order* buffer, whose `ready` is at offset 0 - which is a hook that
    fires a call every time an order is queued.

    Returned as a mapping rather than module constants because these exist only in a cheat build,
    and a name that resolved in a plain one would be an offset into the hook's code.
    """
    start = base + CHEAT_OFF
    fields = {
        "ready": start + 0x00,
        "mode": start + 0x04,
        "this": start + 0x08,
        "target": start + 0x0C,
        "argc": start + 0x10,
        "cleanup": start + 0x14,
        "result": start + 0x18,
    }
    fields["args"] = start + 0x1C
    fields["scratch"] = fields["args"] + CALL_MAX_ARGS * 4
    fields["end"] = fields["scratch"] + CALL_SCRATCH_SIZE
    return fields


CHEAT_BLOCK_SIZE = cheat_offsets()["end"] - CHEAT_OFF


#: Where the hook body starts in a plain build - unchanged by the cheat block existing, which is
#: the point of appending it rather than splicing it in.
CODE_OFF = CHEAT_OFF


def code_offset(cheats: bool) -> int:
    """Where the hook body starts, which the cheat block pushes back when it is present."""
    return CODE_OFF + (CHEAT_BLOCK_SIZE if cheats else 0)


def _emit_camera(a: Asm, base_va: int) -> None:
    """Serve a pending camera command, then fall through to the hook's tail.

    Nothing here touches `GameLogic`. The view is the client's, and the engine ticks logic and
    client from the same loop on the same thread, so this runs where the camera's own code
    runs - the reason the camera rides in the order hook rather than needing a second one.

    `setLocation` and `getLocation` are `__thiscall` and clean their own argument, which is why
    no `add esp, 4` follows either call; the engine's own bookmark sites do the same.
    """
    camera = base_va + CAMERA_OFF
    location = base_va + LOCATION_OFF

    a.emit(0xA1, struct.pack("<I", camera))  # mov eax, [camera]
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "done")

    # No view means the client has not built one yet. Leave the command pending rather than
    # dropping it: unlike an order it is not stale a frame later, and the next frame can serve
    # it. A caller that cares is watching the flag anyway.
    a.emit(0x8B, 0x0D, struct.pack("<I", THE_TACTICAL_VIEW))  # mov ecx, [TheTacticalView]
    a.emit(0x85, 0xC9)  # test ecx, ecx
    a.jcc(JE, "done")

    a.emit(0x8B, 0x11)  # mov edx, [ecx]            ; vtable
    a.emit(0x83, 0xF8, CAMERA_CAPTURE)  # cmp eax, CAMERA_CAPTURE
    a.jcc(JE, "capture")

    a.emit(0x68, struct.pack("<I", location))  # push location
    a.emit(0xFF, 0x92, struct.pack("<I", VIEW_SET_LOCATION_VTABLE_SLOT))  # call [edx+0x174]
    a.jmp("camera_clear")

    a.label("capture")
    a.emit(0x68, struct.pack("<I", location))  # push location
    a.emit(0xFF, 0x92, struct.pack("<I", VIEW_GET_LOCATION_VTABLE_SLOT))  # call [edx+0x170]

    # Cleared last, and only once the buffer holds the answer: on a capture the flag is what
    # tells the reader the 32 bytes are the view's and not the ones it wrote itself.
    a.label("camera_clear")
    a.emit(0xC7, 0x05, struct.pack("<I", camera), b"\x00\x00\x00\x00")  # mov [camera], 0


def _emit_call(a: Asm, base_va: int) -> None:
    """Serve a pending engine call, then fall through to the hook's tail.

    **This is the cheat command, and it is why the block is opt-in.** Everything else the cave
    does is bounded: an order goes through `appendMessage` and is network-ordered like human
    input, and the camera is client state the simulation never reads. This calls whatever address
    the buffer names, on the logic thread, inside a frame. That is the whole point - death,
    typed damage and upgrade grants are *code* in this engine, not values, and no amount of
    writing to memory reaches them - but it is also an arbitrary call into a running process, so
    a binary only carries it when someone asked for it by name.

    The call runs inside the hook's `pushad`/`pushfd`, so every register is already saved and
    this may clobber freely; what it must not do is leave the stack unbalanced before `popad`.
    Hence `cleanup`: the engine's `__thiscall` and `__stdcall` targets clean their own arguments
    and want 0, a `__cdecl` one wants `argc * 4`, and the writer says which rather than this
    guessing from an address it cannot inspect.
    """
    off = cheat_offsets(base_va)

    a.emit(0xA1, struct.pack("<I", off["ready"]))  # mov eax, [ready]
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "done")

    a.emit(0x8B, 0x0D, struct.pack("<I", off["this"]))  # mov ecx, [this]
    a.emit(0x8B, 0x15, struct.pack("<I", off["target"]))  # mov edx, [target]
    a.emit(0xA1, struct.pack("<I", off["mode"]))  # mov eax, [mode]
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "have_target")

    # Vtable dispatch. A null `this` has no vtable to read, and reading one would fault inside
    # the game's own frame - so it is refused here rather than trusted from the buffer.
    a.emit(0x85, 0xC9)  # test ecx, ecx
    a.jcc(JE, "call_clear")
    a.emit(0x8B, 0x01)  # mov eax, [ecx]            ; the vtable
    a.emit(0x8B, 0x14, 0x10)  # mov edx, [eax+edx]  ; the slot

    a.label("have_target")
    a.emit(0x85, 0xD2)  # test edx, edx
    a.jcc(JE, "call_clear")

    a.emit(0x8B, 0x3D, struct.pack("<I", off["argc"]))  # mov edi, [argc]
    a.emit(0x83, 0xFF, CALL_MAX_ARGS)  # cmp edi, CALL_MAX_ARGS
    a.jcc(JA, "call_clear")
    a.emit(0x85, 0xFF)  # test edi, edi
    a.jcc(JE, "call_now")

    # Right to left, so the writer lists arguments in source order and the callee sees them that
    # way: esi starts at the last one and walks back.
    a.emit(0xBE, struct.pack("<I", off["args"]))  # mov esi, args
    a.emit(0x8D, 0x74, 0xBE, 0xFC)  # lea esi, [esi + edi*4 - 4]

    a.label("push_loop")
    a.emit(0xFF, 0x36)  # push dword ptr [esi]
    a.emit(0x83, 0xEE, 0x04)  # sub esi, 4
    a.emit(0x4F)  # dec edi
    a.jcc(JNE, "push_loop")

    a.label("call_now")
    a.emit(0x8B, 0x0D, struct.pack("<I", off["this"]))  # mov ecx, [this]
    a.emit(0xFF, 0xD2)  # call edx
    a.emit(0x03, 0x25, struct.pack("<I", off["cleanup"]))  # add esp, [cleanup]
    a.emit(0xA3, struct.pack("<I", off["result"]))  # mov [result], eax

    # Cleared last, and only once `result` holds the answer: the flag is what tells the reader
    # the return value is the call's and not the one it left there.
    a.label("call_clear")
    a.emit(0xC7, 0x05, struct.pack("<I", off["ready"]), b"\x00\x00\x00\x00")  # mov [ready], 0


def _build_code(base_va: int, cheats: bool = False) -> bytes:
    """The hook body. Runs once per `GameLogic::update`, on the logic thread."""
    ready = base_va + READY_OFF
    order_type = base_va + ORDER_TYPE_OFF
    arg_count = base_va + ARG_COUNT_OFF
    args = base_va + ARGS_OFF
    table = base_va + TABLE_OFF

    a = Asm(base_va + code_offset(cheats))
    a.emit(0x9C)  # pushfd
    a.emit(0x60)  # pushad

    a.emit(0xA1, struct.pack("<I", ready))  # mov eax, [ready]
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "camera")

    a.emit(0x8B, 0x0D, struct.pack("<I", THE_MESSAGE_STREAM))  # mov ecx, [TheMessageStream]
    a.emit(0x85, 0xC9)  # test ecx, ecx
    a.jcc(JE, "clear")

    a.emit(0x8B, 0x01)  # mov eax, [ecx]            ; vtable
    a.emit(0xFF, 0x35, struct.pack("<I", order_type))  # push [order_type]
    a.emit(0xFF, 0x50, APPEND_MESSAGE_VTABLE_SLOT)  # call [eax+0x48]  -> GameMessage*
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "clear")
    a.emit(0x8B, 0xD8)  # mov ebx, eax              ; ebx = GameMessage*

    a.emit(0x8B, 0x3D, struct.pack("<I", arg_count))  # mov edi, [arg_count]
    a.emit(0x85, 0xFF)  # test edi, edi
    a.jcc(JE, "clear")
    a.emit(0x83, 0xFF, MAX_ARGS)  # cmp edi, MAX_ARGS
    a.jcc(JA, "clear")
    a.emit(0xBE, struct.pack("<I", args))  # mov esi, args

    a.label("loop")
    a.emit(0x8B, 0x06)  # mov eax, [esi]            ; argument type tag
    # Reject an out-of-range tag before anything is pushed, so the stack stays balanced.
    a.emit(0x83, 0xF8, len(ARG_APPENDERS) - 1)  # cmp eax, 10
    a.jcc(JA, "clear")
    for tag in BY_POINTER:
        a.emit(0x83, 0xF8, tag)  # cmp eax, <tag>
        a.jcc(JE, "by_pointer")
    a.emit(0xFF, 0x76, 0x04)  # push dword ptr [esi+4]
    a.jmp("dispatch")

    a.label("by_pointer")
    a.emit(0x8D, 0x56, 0x04)  # lea edx, [esi+4]
    a.emit(0x52)  # push edx

    a.label("dispatch")
    a.emit(0x8B, 0xCB)  # mov ecx, ebx              ; this = GameMessage*
    # The appenders are `ret 4`, so they clean the pushed argument themselves.
    a.emit(0xFF, 0x14, 0x85, struct.pack("<I", table))  # call [table + eax*4]
    a.emit(0x83, 0xC6, ARG_STRIDE)  # add esi, 20
    a.emit(0x4F)  # dec edi
    a.jcc(JNE, "loop")

    a.label("clear")
    a.emit(0xC7, 0x05, struct.pack("<I", ready), b"\x00\x00\x00\x00")  # mov [ready], 0

    a.label("camera")
    _emit_camera(a, base_va)

    if cheats:
        _emit_call(a, base_va)

    a.label("done")
    a.emit(0x61)  # popad
    a.emit(0x9D)  # popfd
    a.emit(HOOK_ORIGINAL)  # the displaced instruction
    a.jmp_absolute(HOOK_RETURN_VA)
    return a.finish()


def build_section(base_va: int, cheats: bool = False) -> bytes:
    """The whole ``.livebrg`` payload: command buffer, appender table, tag, then code."""
    body = bytearray(code_offset(cheats))
    struct.pack_into(f"<{len(ARG_APPENDERS)}I", body, TABLE_OFF, *ARG_APPENDERS)
    struct.pack_into("<I", body, TAG_OFF, BUFFER_TAG_CHEATS if cheats else BUFFER_TAG)
    return bytes(body) + _build_code(base_va, cheats)


class LiveBridgePatch(Patch):
    name = "live-bridge"
    author = "officialNecro"
    experimental = True
    description = (
        "Hook GameLogic::update so an external process can inject orders into the "
        "message stream, and place the camera, by writing a command buffer in the "
        "appended .livebrg section."
    )

    def __init__(self, cheats: bool = False) -> None:
        self.cheats = cheats

    def __str__(self) -> str:
        return f"{self.name} (+cheats)" if self.cheats else self.name

    def apply(self, data: bytearray) -> None:
        hook_off = va_to_offset(data, HOOK_VA)
        if hook_off is None:
            raise ValueError(f"{HOOK_VA:#010x} is not mapped - not the expected build")
        # Prove the engine actually dispatches here before taking the site over. A hook on a
        # function nothing calls installs perfectly and simply never runs, which is
        # indistinguishable from a working patch until an injected order is ignored.
        self._check_dispatch(data)
        section_va = allocate_section(
            data,
            SECTION_NAME,
            lambda base: build_section(base, self.cheats),
            _CHARACTERISTICS,
        )
        code_va = section_va + code_offset(self.cheats)
        jump = b"\xe9" + struct.pack("<i", code_va - (HOOK_VA + 5))
        apply_byte_patch(
            data,
            hook_off,
            HOOK_ORIGINAL,
            jump,
            "GameLogic::update entry -> live-bridge hook",
        )

    @staticmethod
    def _check_dispatch(data: bytes | bytearray) -> None:
        """Raise unless the vtable slot still names the function being hooked."""
        slot_off = va_to_offset(data, GAME_LOGIC_UPDATE_VTABLE_SLOT)
        if slot_off is None:
            raise ValueError("the GameLogic vtable is not mapped - not the expected build")
        target = struct.unpack_from("<I", data, slot_off)[0]
        if target != HOOK_VA:
            raise ValueError(
                f"vtable slot {GAME_LOGIC_UPDATE_VTABLE_SLOT:#010x} dispatches to "
                f"{target:#010x}, not {HOOK_VA:#010x} - hooking it would never fire"
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
        expected_code = section_va + code_offset(self.cheats)
        target = HOOK_VA + 5 + struct.unpack_from("<i", data, off + 1)[0]
        if target != expected_code:
            problems.append(f"hook jumps to {target:#010x}, expected {expected_code:#010x}")
        table = struct.unpack_from(f"<{len(ARG_APPENDERS)}I", data, section_off + TABLE_OFF)
        if table != ARG_APPENDERS:
            problems.append("the argument-appender table does not match the expected addresses")
        wanted = BUFFER_TAG_CHEATS if self.cheats else BUFFER_TAG
        tag = struct.unpack_from("<I", data, section_off + TAG_OFF)[0]
        if tag != wanted:
            problems.append(
                f"the command buffer is tagged {tag:#010x}, not {wanted:#010x} - this cave was "
                "built to a different layout and must be re-applied"
            )
        return problems

    @classmethod
    def detect(cls, data: bytes | bytearray) -> LiveBridgePatch | None:
        """Recover whether the cave in ``data`` carries the cheat block, from its own tag.

        The default probe would build with `cheats=False` and report a cheat-enabled binary as
        carrying no live-bridge at all, which is the specific failure `Patch.detect` warns a
        parameterised patch about.
        """
        located = find_section(data, SECTION_NAME)
        if located is None:
            return None
        _, section_off, _ = located
        try:
            tag = struct.unpack_from("<I", data, section_off + TAG_OFF)[0]
        except struct.error:
            return None
        if tag not in (BUFFER_TAG, BUFFER_TAG_CHEATS):
            return None
        patch = cls(cheats=tag == BUFFER_TAG_CHEATS)
        return patch if not patch.verify(data) else None

    @classmethod
    def add_cli_arguments(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--cheats",
            action="store_true",
            help=(
                "add the call command: let the writer call an engine function on the logic "
                "thread. Needed for anything the engine does in code rather than in data - "
                "killing an object, dealing typed damage, granting an upgrade for real. This is "
                "an arbitrary call into the running game; leave it off unless you want it."
            ),
        )

    @classmethod
    def from_cli_args(cls, args: argparse.Namespace) -> LiveBridgePatch:
        return cls(cheats=getattr(args, "cheats", False))
