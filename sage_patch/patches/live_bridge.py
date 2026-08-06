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

import struct

from ..addresses import (
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
from ..asm import JA, JE, JNE, Asm
from ..patcher import Patch
from ..utils import allocate_section, apply_byte_patch, find_section, va_to_offset

__all__ = [
    "ARG_APPENDERS",
    "BUFFER_TAG",
    "CAMERA_APPLY",
    "CAMERA_CAPTURE",
    "LiveBridgePatch",
    "MAX_ARGS",
    "SECTION_NAME",
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
CODE_OFF = LOCATION_OFF + VIEW_LOCATION_SIZE

# `'BL'` in the high half and the layout revision in the low, as one dword a stale binary
# cannot plausibly hold. Bump the revision whenever an offset above moves, so a writer built
# against the new layout refuses an image carrying the old one instead of writing into the
# middle of it. Revision 1 is the order-only buffer, which carried no tag at all.
BUFFER_TAG = 0x424C0002

# The two camera directions, written into `camera` and cleared by the hook once served.
CAMERA_APPLY = 1
CAMERA_CAPTURE = 2


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


def _build_code(base_va: int) -> bytes:
    """The hook body. Runs once per `GameLogic::update`, on the logic thread."""
    ready = base_va + READY_OFF
    order_type = base_va + ORDER_TYPE_OFF
    arg_count = base_va + ARG_COUNT_OFF
    args = base_va + ARGS_OFF
    table = base_va + TABLE_OFF

    a = Asm(base_va + CODE_OFF)
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

    a.label("done")
    a.emit(0x61)  # popad
    a.emit(0x9D)  # popfd
    a.emit(HOOK_ORIGINAL)  # the displaced instruction
    a.jmp_absolute(HOOK_RETURN_VA)
    return a.finish()


def build_section(base_va: int) -> bytes:
    """The whole ``.livebrg`` payload: command buffer, appender table, tag, then code."""
    body = bytearray(CODE_OFF)
    struct.pack_into(f"<{len(ARG_APPENDERS)}I", body, TABLE_OFF, *ARG_APPENDERS)
    struct.pack_into("<I", body, TAG_OFF, BUFFER_TAG)
    return bytes(body) + _build_code(base_va)


class LiveBridgePatch(Patch):
    name = "live-bridge"
    description = (
        "Hook GameLogic::update so an external process can inject orders into the "
        "message stream, and place the camera, by writing a command buffer in the "
        "appended .livebrg section."
    )

    def apply(self, data: bytearray) -> None:
        hook_off = va_to_offset(data, HOOK_VA)
        if hook_off is None:
            raise ValueError(f"{HOOK_VA:#010x} is not mapped - not the expected build")
        # Prove the engine actually dispatches here before taking the site over. A hook on a
        # function nothing calls installs perfectly and simply never runs, which is
        # indistinguishable from a working patch until an injected order is ignored.
        self._check_dispatch(data)
        section_va = allocate_section(data, SECTION_NAME, build_section, _CHARACTERISTICS)
        code_va = section_va + CODE_OFF
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
        target = HOOK_VA + 5 + struct.unpack_from("<i", data, off + 1)[0]
        if target != section_va + CODE_OFF:
            problems.append(f"hook jumps to {target:#010x}, expected {section_va + CODE_OFF:#010x}")
        table = struct.unpack_from(f"<{len(ARG_APPENDERS)}I", data, section_off + TABLE_OFF)
        if table != ARG_APPENDERS:
            problems.append("the argument-appender table does not match the expected addresses")
        tag = struct.unpack_from("<I", data, section_off + TAG_OFF)[0]
        if tag != BUFFER_TAG:
            problems.append(
                f"the command buffer is tagged {tag:#010x}, not {BUFFER_TAG:#010x} - this cave "
                "was built to a different layout and must be re-applied"
            )
        return problems
