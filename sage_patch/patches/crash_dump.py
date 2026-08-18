"""The crash-dump patch: make the minidump the engine already writes worth opening.

Targets the ROTWK SAGE-engine `game.dat` build ``2.01.2614.37001``. Every address below is derived
in ``../docs/crash-dump-quality.md`` (the scoping notes) and ``../docs/crash-dump.md`` (this
patch).

**The defect.** The engine writes a minidump on every unhandled exception, from EA's `Debug`
library: `writeMiniDump` at `WRITE_MINI_DUMP` builds a file name, opens it, takes
`SeDebugPrivilege` and calls `MiniDumpWriteDump`. It asks for `MiniDumpWithDataSegs` alone and
passes `NULL` for both the callback and the user-stream parameter, and those choices cost
everything a dump is opened for:

* `WithDataSegs` captures **every loaded module's data segment**, so a measured 27.4 MB dump is
  20 MB of `nvd3dum.dll` and `igd9dxva32.dll` globals - and **no heap at all**. Every engine
  singleton pointer is in the dump and nothing any of them points at is: `TheGameLogic`
  (`0x00DE412C`) reads a heap address that falls in no captured range. A null-pointer fault in a
  live object is therefore unreadable - the dump names the pointer and not the object.
* `Debug::crash` raises the engine's own `DEBUG_CRASH_EXCEPTION_CODE` with
  ``lpArguments = NULL`` and ``nNumberOfArguments = 0``, so the exception record that reaches the
  dump carries **no parameters**. The expression, file and line are formatted into a heap buffer,
  shown in a message box, written to a `Debug` I/O sink that no shipping config registers, and
  then dropped. Four of six observed dumps are this code, i.e. four dumps that record that an
  assert fired and not which one.

**What this does.** Appends a ``.crshdp`` PE section holding a small data header and three
routines, and redirects two windows into it.

* At `MINI_DUMP_ARGS`, the eighteen bytes that push `MiniDumpWriteDump`'s last four arguments are
  replaced by a jump into the cave, which pushes the same four - but with a **patch-owned dump
  type** taken from a two-entry table indexed by the engine's own `fulldump` flag
  (`MINI_DUMP_FULL_DUMP_EBP`), and with the null `CallbackParam` replaced by a pointer to a
  `MINIDUMP_CALLBACK_INFORMATION` in the cave. The `UserStreamParam` stays `NULL`.
* The callback drops the foreign data segments. It answers only `ModuleCallback`, clears
  `ModuleWriteDataSeg` for every module whose `BaseOfImage` is not `IMAGE_BASE`, and returns
  `TRUE` for everything else. That is the 20 MB, and it is what pays for the heap.
* At `DEBUG_CRASH_RAISE`, the four `RaiseException` arguments are replaced by a jump into the cave,
  which spills three `ULONG_PTR`s into a static slot and passes them as the exception parameters:
  the formatted crash text (`DEBUG_CRASH_MESSAGE_EBP`), the `.rdata` literal that tags it as an
  assertion or an error (`DEBUG_CRASH_TAG_EBP`), and the mode (`DEBUG_CRASH_MODE_EBP`). Minidumps
  store `ExceptionInformation[]` in full, so all three survive.

**The two halves need each other.** The message pointer is a heap pointer - `Debug::crash`
allocates the buffer at `0x0043A91E` - so putting it in the exception record only helps in a dump
that carries the heap, which is the profile's job. The tag literal is in `.rdata` and readable
either way.

**The profile.** The default is ``0x1B65``: `WithDataSegs | HandleData | WithUnloadedModules |
WithIndirectlyReferencedMemory | WithProcessThreadData | WithPrivateReadWriteMemory |
WithFullMemoryInfo | WithThreadInfo`. `WithPrivateReadWriteMemory` (``0x0200``) is the bit that
answers the motivating crash: it captures committed private read/write memory - the SAGE heap and
the CRT heap, without the mapped images - so an arbitrary object reached through a singleton
pointer is readable. The deep profile the `fulldump` debug command selects adds `WithFullMemory`
(``0x0002``) on top. Both are parameters, so a mod that wants smaller files can dial the bits back
without a code change, and `detect` reads them straight back out of the cave.

**The shipped `dbghelp.dll` supports all of it.** It is `6.3.0005.1`, loaded by explicit full path
out of the game folder, and every value up to `WithCodeSegs` (``0x2000``) is documented as
unsupported only on *DbgHelp 6.1 and earlier*. So none of the bits above needs the folder's copy
renamed out of the way, which the scoping notes assumed for two of them. An unrecognised type bit
is masked off rather than failing the write, so a build that did load an older `dbghelp` degrades
to a smaller dump rather than to none.

**Crash-time safety.** Both routines run in a process that is already broken, so both are leaf
code: no allocation, no CRT, no locks, no loop. The callback reads two fields and writes one, with
an explicit null test on each pointer it is handed. Each hook pushes exactly as many dwords as the
window it replaced, and clobbers only registers the replaced bytes already clobbered - the args
hook `eax`/`ecx` where the stock code used `eax`/`ecx`/`edx`, the raise hook `eax`, which is dead
there. The unhandled-exception filter's second-chance guard at `0x00DC6E50` sits outside both, so
a fault inside either costs the dump and nothing else.

**Blast radius: client-local.** Nothing here touches the simulation, the frame checksum, the order
stream or the replay format. It is reached only from the unhandled-exception filter and from
`Debug::crash`, neither of which runs in a game that is not already over. Peers need not match and
replays cross both ways.

**Composition.** Order-independent: the cave is allocated past every existing section and
:meth:`verify` finds it by name. The only engine bytes it edits are the eighteen at
`MINI_DUMP_ARGS` and the eight at `DEBUG_CRASH_RAISE`, which no other bundled patch touches, and it
reads no structure another patch rewrites. It has no INI surface.
"""

from __future__ import annotations

import struct
from typing import TYPE_CHECKING

from ..addresses import (
    DEBUG_CRASH_EXCEPTION_CODE,
    DEBUG_CRASH_MESSAGE_EBP,
    DEBUG_CRASH_MESSAGE_READ,
    DEBUG_CRASH_MESSAGE_READ_BYTES,
    DEBUG_CRASH_MODE_EBP,
    DEBUG_CRASH_RAISE,
    DEBUG_CRASH_RAISE_BYTES,
    DEBUG_CRASH_RAISE_RESUME,
    DEBUG_CRASH_RAISE_RESUME_BYTES,
    DEBUG_CRASH_TAG_EBP,
    DEBUG_CRASH_TAG_STORE,
    DEBUG_CRASH_TAG_STORE_BYTES,
    IMAGE_BASE,
    MINI_DUMP_ARGS,
    MINI_DUMP_ARGS_BYTES,
    MINI_DUMP_ARGS_RESUME,
    MINI_DUMP_ARGS_RESUME_BYTES,
    MINI_DUMP_EXCEPTION_INFO_EBP,
    MINI_DUMP_FULL_DUMP_EBP,
    MINI_DUMP_NULL_EDI,
    MINI_DUMP_NULL_EDI_BYTES,
    WRITE_MINI_DUMP,
    WRITE_MINI_DUMP_BYTES,
)
from ..asm import JE, JNE, Asm
from ..patcher import Patch
from ..utils import allocate_section, apply_byte_patch, find_section, va_to_offset

if TYPE_CHECKING:
    import argparse

__all__ = [
    "ANCHORS",
    "DEEP_PROFILE",
    "MODULE_WRITE_DATA_SEG",
    "NORMAL_PROFILE",
    "RAISE_ARGUMENT_COUNT",
    "SECTION_NAME",
    "CrashDumpPatch",
    "build_code",
    "build_section",
    "entry_points",
]

SECTION_NAME = ".crshdp"  # 7 chars: the PE name field is 8 bytes and truncates silently

# IMAGE_SCN_CNT_CODE | CNT_INITIALIZED_DATA | MEM_EXECUTE | MEM_READ | MEM_WRITE. Writable, unlike
# most caves here, because the raise hook spills three dwords into `_RAISE_ARGS_OFF` before it
# hands `RaiseException` their address - `lpArguments` has to point at memory the process may
# write, and a static slot is what keeps that spill off a stack that is about to unwind.
_CHARACTERISTICS = 0x20 | 0x40 | 0x20000000 | 0x40000000 | 0x80000000

#: `MINIDUMP_TYPE` bits, from `dbghelp.h`. Named here rather than written as one magic number so
#: the profile below can be read as a sentence, and so a mod that changes it says what it dropped.
_WITH_DATA_SEGS = 0x0001
_WITH_FULL_MEMORY = 0x0002
_WITH_HANDLE_DATA = 0x0004
_WITH_UNLOADED_MODULES = 0x0020
_WITH_INDIRECTLY_REFERENCED_MEMORY = 0x0040
_WITH_PROCESS_THREAD_DATA = 0x0100
_WITH_PRIVATE_READ_WRITE_MEMORY = 0x0200
_WITH_FULL_MEMORY_INFO = 0x0800
_WITH_THREAD_INFO = 0x1000

#: The type written when the `fulldump` debug command has **not** been used, which is every
#: shipping configuration. `WithPrivateReadWriteMemory` is the one that makes a dump answer "what
#: was this pointer pointing at"; the rest are cheap streams that cost kilobytes and answer
#: questions the stock dump cannot: which module a return address came from once it unloaded,
#: which of 33 anonymous threads is the logic thread, and whether an address is a live commit or
#: freed memory.
NORMAL_PROFILE = (
    _WITH_DATA_SEGS
    | _WITH_HANDLE_DATA
    | _WITH_UNLOADED_MODULES
    | _WITH_INDIRECTLY_REFERENCED_MEMORY
    | _WITH_PROCESS_THREAD_DATA
    | _WITH_PRIVATE_READ_WRITE_MEMORY
    | _WITH_FULL_MEMORY_INFO
    | _WITH_THREAD_INFO
)

#: The type written when `fulldump` is on. `WithFullMemory` adds the mapped images back on top of
#: the private pages the normal profile already takes, which is the only thing left to add.
DEEP_PROFILE = NORMAL_PROFILE | _WITH_FULL_MEMORY

#: `MINIDUMP_CALLBACK_OUTPUT.ModuleWriteFlags`' data-segment bit, the one the module callback
#: clears. `ModuleWriteModule` (`0x01`) is left alone, so a filtered module still appears in the
#: dump's module list with its name, version and load address - only its globals are dropped.
MODULE_WRITE_DATA_SEG = 0x0002

#: How many `ULONG_PTR`s the raise hook hands `RaiseException`. Well under the 15 an
#: `EXCEPTION_RECORD` holds and a minidump stores, so nothing is truncated.
RAISE_ARGUMENT_COUNT = 3

# `MINIDUMP_CALLBACK_INPUT`, as a 32-bit compiler lays it out: `ProcessId`, `ProcessHandle`,
# `CallbackType`, then the union - which starts at `0x10` rather than `0x0C`, because every arm of
# it contains a `ULONG64` and therefore aligns to 8. `MINIDUMP_MODULE_CALLBACK` is
# `{ PWCHAR FullPath; ULONG64 BaseOfImage; ... }`, so the base is at union + 8.
_CALLBACK_TYPE_OFF = 0x08
_MODULE_CALLBACK = 0
_MODULE_BASE_OFF = 0x18

# The cave's data header, ahead of the code.
_PROFILES_OFF = 0x00  # dword[2]: the normal type, then the deep one
_CALLBACK_INFO_OFF = 0x08  # MINIDUMP_CALLBACK_INFORMATION { CallbackRoutine, CallbackParam }
_RAISE_ARGS_OFF = 0x10  # ULONG_PTR[3]: the raise hook's exception parameters
_CODE_OFF = 0x20

#: The first bytes at each address the cave jumps to or reads through, as a `{va: bytes}` map. The
#: two hook windows are asserted by `apply_byte_patch`; these are everything else the assembly
#: assumes about this build - the dump writer's prologue, the `xor edi, edi` that makes the two
#: displaced `push edi` a pair of literal nulls, both resume points, and the two instructions that
#: pin `Debug::crash`'s frame slots to a live message pointer and a live tag pointer. A build whose
#: layout moved fails here rather than by pushing a stack slot that holds something else.
ANCHORS = {
    WRITE_MINI_DUMP: WRITE_MINI_DUMP_BYTES,
    MINI_DUMP_NULL_EDI: MINI_DUMP_NULL_EDI_BYTES,
    MINI_DUMP_ARGS_RESUME: MINI_DUMP_ARGS_RESUME_BYTES,
    DEBUG_CRASH_TAG_STORE: DEBUG_CRASH_TAG_STORE_BYTES,
    DEBUG_CRASH_MESSAGE_READ: DEBUG_CRASH_MESSAGE_READ_BYTES,
    DEBUG_CRASH_RAISE_RESUME: DEBUG_CRASH_RAISE_RESUME_BYTES,
}


def _u32(value: int) -> bytes:
    return struct.pack("<I", value)


def _assemble(base_va: int) -> Asm:
    """The three routines, laid out at ``base_va + _CODE_OFF``. ``base_va`` is the section base,
    because all three address the data header that sits in front of them."""
    a = Asm(base_va + _CODE_OFF)
    profiles = base_va + _PROFILES_OFF
    callback_info = base_va + _CALLBACK_INFO_OFF
    raise_args = base_va + _RAISE_ARGS_OFF

    # Jumped to in place of the eighteen bytes that push `MiniDumpWriteDump`'s last four
    # arguments, and jumps back to the `push esi` that follows with the file handle. `ebp` is
    # still `writeMiniDump`'s frame, so both the exception-information block it filled and the
    # `fullDump` argument are addressable here. Four pushes in, four pushes out.
    a.label("args")
    a.emit(0x68, _u32(callback_info))  # push &MINIDUMP_CALLBACK_INFORMATION
    a.emit(0x6A, 0x00)  # push 0                ; UserStreamParam, still NULL
    a.emit(0x8D, 0x45, MINI_DUMP_EXCEPTION_INFO_EBP & 0xFF)  # lea eax, [ebp-0x10]
    a.emit(0x50)  # push eax                    ; ExceptionParam
    a.emit(0x33, 0xC9)  # xor ecx, ecx
    a.emit(0x80, 0x7D, MINI_DUMP_FULL_DUMP_EBP, 0x00)  # cmp byte [ebp+0xc], 0
    a.jcc_short(JE, "args_type")
    a.emit(0x41)  # inc ecx                     ; fulldump on: take the deep profile
    a.label("args_type")
    a.emit(0xFF, 0x34, 0x8D, _u32(profiles))  # push dword [profiles + ecx*4]
    a.jmp_absolute(MINI_DUMP_ARGS_RESUME)

    # Jumped to in place of `RaiseException`'s four arguments, and jumps back to the call itself.
    # `eax` is dead here - the `__thiscall` two instructions earlier returns into it and nothing
    # reads it - so it is the one register the spill needs. Four pushes in, four pushes out, so
    # `RaiseException`'s own `ret 16` still balances if a handler resumes execution.
    a.label("raise")
    a.emit(0x8B, 0x45, DEBUG_CRASH_MESSAGE_EBP & 0xFF)  # mov eax, [ebp-4]   ; the crash text
    a.emit(0xA3, _u32(raise_args))
    a.emit(0x8B, 0x45, DEBUG_CRASH_TAG_EBP & 0xFF)  # mov eax, [ebp-8]      ; assertion or error
    a.emit(0xA3, _u32(raise_args + 4))
    a.emit(0x8B, 0x45, DEBUG_CRASH_MODE_EBP)  # mov eax, [ebp+8]            ; the mode itself
    a.emit(0xA3, _u32(raise_args + 8))
    a.emit(0x68, _u32(raise_args))  # push lpArguments
    a.emit(0x6A, RAISE_ARGUMENT_COUNT)  # push 3        ; nNumberOfArguments
    a.emit(0x6A, 0x00)  # push 0                        ; dwExceptionFlags, continuable as stock
    a.emit(0x68, _u32(DEBUG_CRASH_EXCEPTION_CODE))  # push 0x04560123
    a.jmp_absolute(DEBUG_CRASH_RAISE_RESUME)

    # `BOOL __stdcall (PVOID param, PMINIDUMP_CALLBACK_INPUT in, PMINIDUMP_CALLBACK_OUTPUT out)`,
    # so the two pointers are at `[esp+8]` and `[esp+0xc]` and the routine cleans twelve bytes.
    # Returning TRUE with the flags untouched is what "no opinion" looks like, which is the answer
    # to every callback type but `ModuleCallback` and to `game.dat` itself.
    a.label("callback")
    a.emit(0x8B, 0x44, 0x24, 0x08)  # mov eax, [esp+8]           ; CallbackInput
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc_short(JE, "callback_out")
    a.emit(0x83, 0x78, _CALLBACK_TYPE_OFF, _MODULE_CALLBACK)  # cmp dword [eax+8], 0
    a.jcc_short(JNE, "callback_out")
    a.emit(0x83, 0x78, _MODULE_BASE_OFF + 4, 0x00)  # cmp dword [eax+0x1c], 0  ; BaseOfImage high
    a.jcc_short(JNE, "callback_drop")
    a.emit(0x81, 0x78, _MODULE_BASE_OFF, _u32(IMAGE_BASE))  # cmp dword [eax+0x18], 0x400000
    a.jcc_short(JE, "callback_out")
    a.label("callback_drop")
    a.emit(0x8B, 0x4C, 0x24, 0x0C)  # mov ecx, [esp+0xc]         ; CallbackOutput
    a.emit(0x85, 0xC9)  # test ecx, ecx
    a.jcc_short(JE, "callback_out")
    a.emit(0x83, 0x21, 0xFF & ~MODULE_WRITE_DATA_SEG)  # and dword [ecx], ~ModuleWriteDataSeg
    a.label("callback_out")
    a.emit(0xB8, _u32(1))  # mov eax, TRUE
    a.emit(0xC2, 0x0C, 0x00)  # ret 12
    return a


def build_code(base_va: int) -> bytes:
    """The cave's code, for a section placed at ``base_va``."""
    return _assemble(base_va).finish()


def entry_points(base_va: int) -> tuple[int, int, int]:
    """``(args, raise, callback)`` - the virtual address of each routine, read off the emitted
    layout rather than counted by hand."""
    a = _assemble(base_va)
    a.finish()
    return a.label_va("args"), a.label_va("raise"), a.label_va("callback")


def build_section(base_va: int, normal: int, deep: int) -> bytes:
    """The whole ``.crshdp`` section for a placement at ``base_va``: the data header, then the
    code. The header holds the two dump types, the `MINIDUMP_CALLBACK_INFORMATION` the args hook
    hands `MiniDumpWriteDump`, and the three-slot argument block the raise hook fills."""
    _args, _raise, callback = entry_points(base_va)
    header = bytearray(_CODE_OFF)
    struct.pack_into("<II", header, _PROFILES_OFF, normal, deep)
    struct.pack_into("<II", header, _CALLBACK_INFO_OFF, callback, 0)
    return bytes(header) + build_code(base_va)


class CrashDumpPatch(Patch):
    """Give `MiniDumpWriteDump` a usable dump type, a module filter and a filled exception
    record."""

    name = "crash-dump"
    author = "officialNecro"
    description = (
        "Make the engine's crash .dmp readable: the SAGE heap goes in so a singleton pointer can "
        "be followed to the object it names, the video driver's 20 MB of globals come out, and "
        "the assert text, its kind and its mode land in the exception record - no INI, string "
        "table or map data to declare"
    )

    def __init__(self, normal: int = NORMAL_PROFILE, deep: int = DEEP_PROFILE):
        for label, value in (("normal", normal), ("deep", deep)):
            if not 0 <= value <= 0xFFFFFFFF:
                raise ValueError(f"{label} dump type must be a dword, got {value:#x}")
            if not value & (_WITH_FULL_MEMORY | _WITH_PRIVATE_READ_WRITE_MEMORY):
                raise ValueError(
                    f"the {label} dump type {value:#06x} carries neither WithFullMemory "
                    f"({_WITH_FULL_MEMORY:#06x}) nor WithPrivateReadWriteMemory "
                    f"({_WITH_PRIVATE_READ_WRITE_MEMORY:#06x}), so the dump would still hold no "
                    "heap - which is the whole defect this patch exists to fix"
                )
        self.normal = normal
        self.deep = deep

    def __str__(self) -> str:
        return f"{self.name} (0x{self.normal:04x}/0x{self.deep:04x})"

    def apply(self, data: bytearray) -> None:
        self._check_anchors(data)
        section_va = allocate_section(
            data,
            SECTION_NAME,
            lambda base: build_section(base, self.normal, self.deep),
            _CHARACTERISTICS,
        )
        for hook_va, original, target, note in self._hooks(section_va):
            off = va_to_offset(data, hook_va)
            if off is None:
                raise ValueError(f"{hook_va:#010x} is not mapped - not the expected build")
            apply_byte_patch(data, off, original, self._jump(hook_va, target, len(original)), note)

    @staticmethod
    def _jump(hook_va: int, target: int, width: int) -> bytes:
        """A `jmp rel32` to ``target``, `nop`-padded out to ``width``. The padding matters: a
        leftover byte of the window would be decoded as an instruction on the way back in."""
        return b"\xe9" + struct.pack("<i", target - (hook_va + 5)) + b"\x90" * (width - 5)

    @staticmethod
    def _hooks(section_va: int) -> list[tuple[int, bytes, int, str]]:
        """The two ``(hook va, original bytes, cave target, note)`` redirections, shared by
        :meth:`apply` and :meth:`verify` so the two cannot disagree about either target."""
        args, raise_, _callback = entry_points(section_va)
        return [
            (
                MINI_DUMP_ARGS,
                MINI_DUMP_ARGS_BYTES,
                args,
                "MiniDumpWriteDump argument push -> crash-dump cave",
            ),
            (
                DEBUG_CRASH_RAISE,
                DEBUG_CRASH_RAISE_BYTES,
                raise_,
                "Debug::crash RaiseException argument push -> crash-dump cave",
            ),
        ]

    @staticmethod
    def _check_anchors(data: bytes | bytearray) -> None:
        for va, expected in ANCHORS.items():
            off = va_to_offset(data, va)
            if off is None:
                raise ValueError(f"{va:#010x} is not mapped - not the expected build")
            got = bytes(data[off : off + len(expected)])
            if got != expected:
                raise ValueError(
                    f"{va:#010x} holds {got.hex()}, expected {expected.hex()} - this build's "
                    "crash path is not the one the cave was written against, so it would push "
                    "the wrong stack slots or return into the middle of an instruction"
                )

    def verify(self, data: bytes | bytearray) -> list[str]:
        problems: list[str] = []
        located = find_section(data, SECTION_NAME)
        if located is None:
            return [f"{SECTION_NAME} section is absent"]
        section_va, section_off, _vsize = located
        content = build_section(section_va, self.normal, self.deep)
        # The raise hook writes into its argument slots at crash time, so the file's copy of them
        # is only zero until the game has crashed once with this binary. Compare everything else.
        for start, end, label in (
            (0, _RAISE_ARGS_OFF, "dump types and callback block"),
            (_CODE_OFF, len(content), "routines"),
        ):
            if bytes(data[section_off + start : section_off + end]) != content[start:end]:
                problems.append(f"the {SECTION_NAME} cave's {label} are not the expected bytes")
        for hook_va, _original, target, note in self._hooks(section_va):
            off = va_to_offset(data, hook_va)
            if off is None:
                return [f"{hook_va:#010x} is not mapped by any section"]
            if data[off] != 0xE9:
                problems.append(f"{note}: {hook_va:#010x} is not a jump - the hook is absent")
                continue
            reached = hook_va + 5 + struct.unpack_from("<i", data, off + 1)[0]
            if reached != target:
                problems.append(f"{note}: jumps to {reached:#010x}, expected {target:#010x}")
        return problems

    @classmethod
    def detect(cls, data: bytes | bytearray) -> CrashDumpPatch | None:
        """Recognise this patch **and recover both dump types** from ``data``.

        The default probe cannot: it would ask `verify` about the default profile and call a
        binary patched with any other one unpatched. The two types are the first two dwords of the
        cave, so they read straight back out, and `verify` then checks the rest against them."""
        located = find_section(data, SECTION_NAME)
        if located is None:
            return None
        _section_va, section_off, _vsize = located
        try:
            normal, deep = struct.unpack_from("<II", data, section_off + _PROFILES_OFF)
            patch = cls(normal, deep)
        except (ValueError, struct.error):
            return None
        return None if patch.verify(data) else patch

    @classmethod
    def add_cli_arguments(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--dump-type",
            type=lambda text: int(text, 0),
            default=NORMAL_PROFILE,
            metavar="BITS",
            help=(
                f"MINIDUMP_TYPE written on a normal crash; default {NORMAL_PROFILE:#06x}. Must "
                "include WithFullMemory (0x0002) or WithPrivateReadWriteMemory (0x0200), or the "
                "dump still carries no heap"
            ),
        )
        parser.add_argument(
            "--deep-dump-type",
            type=lambda text: int(text, 0),
            default=DEEP_PROFILE,
            metavar="BITS",
            help=(
                "MINIDUMP_TYPE written when the engine's own `fulldump` debug command is on; "
                f"default {DEEP_PROFILE:#06x}"
            ),
        )

    @classmethod
    def from_cli_args(cls, args: argparse.Namespace) -> CrashDumpPatch:
        return cls(normal=args.dump_type, deep=args.deep_dump_type)
