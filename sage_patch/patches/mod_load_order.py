r"""The mod-load-order patch: mount `-mod` before the first INI file is read.

Targets the ROTWK SAGE-engine `game.dat` build ``2.01.2614.37001``. Every address below is derived
in ``../docs/mod-load-order.md``.

**The defect.** `GameEngine::init` registers `TheWritableGlobalData` at :data:`GLOBAL_DATA_CALL`
and only then parses the startup switches at :data:`MOD_CALL`. The registration is not a bare
allocation: it reaches `initSubsystem`, which calls the subsystem's ``vtbl+8`` - the legend-driven
loader `SUBSYSTEM_LOAD_LEGEND_FILES` - which `INI::load`s every `InitFile` the subsystem legend
declares for that name, and for `TheWritableGlobalData` those are ``Data\INI\Default\GameData.ini``
and ``Data\INI\GameData.ini``.

So `GameData.ini` is read fourteen bytes before `-mod` exists. Until `MOD_MOUNT_DIRECTORY` runs,
`MOD_PREFER_LOCAL_FLAG` is zero and `MOD_DIRECTORY` is empty, and every mod-aware site in the file
system - `openFile`, `getFileInfo`, `getFileListInDirectory` - skips its mod branch. `GameData.ini`
therefore always comes out of the archives however the loose tree spells it.

That reads in practice as "a changed ``#define`` is ignored", because a mod keeps its shared macros
in a file `GameData.ini` includes, and everything else in the tree is loaded after the mount and
does pick up loose edits. The macro machinery is not involved: `INI::load`'s ``#define`` pre-pass
fills `INI_MACRO_TABLE` the same way whatever the bytes came from.

**What this does.** Two edits, neither of which rewrites any engine logic - one `call` target, and
one jump over a block that now runs too late to matter.

* :data:`GLOBAL_DATA_CALL`, the `call` that registers `TheWritableGlobalData`, is repointed into a
  ``.modord`` cave. The cave publishes the object to `GLOBAL_DATA` (the `-mod` handler bails
  silently while that is null, which is why the parse cannot simply be moved up), runs
  `COMMAND_LINE_PARSE` over the startup table, mounts what `-mod` named - transcribing
  :data:`MOD_MOUNT_BLOCK` instruction for instruction - and then tail-jumps to the original
  registration with the stack untouched, so `GameData.ini` is read with the mod already mounted.
* :data:`MOD_MOUNT_BLOCK`, the mount half of `COMMAND_LINE_PARSE_AND_MOUNT_MODS`, is jumped over to
  :data:`MOD_MOUNT_BLOCK_END`, so nothing is mounted a second time. The jump is preceded by the
  block's own ``add esp, 0x0c``, which belongs to the parse rather than to the mount and would
  otherwise be skipped with it - see :data:`MOD_MOUNT_BLOCK` for what that costs.

:data:`MOD_CALL` is deliberately **left alone**. The stock site still calls the stock function, so
the switches are still parsed after `GameData.ini` and a switch keeps beating what the tree says
about the same field - the precedence the addresses note on ``GLOBAL_DATA_FPS_LIMIT`` records. All
that function loses is the mount, which by then has already happened.

**Why the parse runs twice.** Once early, to learn where `-mod` points; once at the stock site, to
keep that precedence for everything else. Every startup handler rebuilds its result from `argv` and
assigns, so running them twice is idempotent - including the `-mod` handler, which builds its path
in a local and appends a trailing separator only when one is absent.

**`-preferLocalFiles` moves with it.** It sits in the same table and raises the same
`MOD_PREFER_LOCAL_FLAG`, so it too now applies to `GameData.ini` rather than starting one file
late. That is the same defect, not a second change.

**The cave reads the stock switch table deliberately.** `COMMAND_LINE_STARTUP_TABLE` and its count
are assembled in as constants rather than read out of the image, because `headless` rewrites the
two operands that tell the stock site which table to walk (``0x007BAA4B`` and ``0x007BAA54``), and
reading them here would make this patch's bytes depend on whether that one had been applied yet.
The early parse exists only to find `-mod`, which is a row of the stock sixteen; a switch some other
patch adds is still parsed at the stock site, which this patch leaves calling the stock function
over whatever table it was pointed at. Neither patch reads or writes a byte the other touches, and
neither disables the other's work, so the two compose in either order.

**What it does not fix.** `TheSubsystemLegend` and its
``Data\INI\Default\SubsystemLegendExpansion1.ini`` are read at ``0x0063AF40`` and ``0x0063AF60``,
before `GlobalData` is even allocated, so a mod still cannot replace the legend from loose files.
Covering that means moving the allocation and constructor ahead of the legend registration, which
is a rewrite of the function's opening rather than a repointed call.

**Determinism.** A mod that changes `GameData.ini` loosely now gets different game data than it did
before, so this is simulation state: **every peer needs the same binary and the same tree**, the
same way a `.big` change is. The patch adds no new source of divergence of its own.

**No INI change.** Nothing new is spelled anywhere; the patch only changes which copy of a file the
engine reads.
"""

from __future__ import annotations

import struct

from ..addresses import (
    ARCHIVE_FILE_SYSTEM,
    ARCHIVE_FILE_SYSTEM_LOAD_ARCHIVE_SLOT,
    ASCII_STRING_IS_EMPTY,
    COMMAND_LINE_PARSE,
    COMMAND_LINE_PARSE_AND_MOUNT_MODS,
    COMMAND_LINE_STARTUP_TABLE,
    COMMAND_LINE_STARTUP_TABLE_COUNT,
    GAME_ENGINE_INIT_GLOBAL_DATA_CALL,
    GAME_ENGINE_INIT_GLOBAL_DATA_CALL_BYTES,
    GAME_ENGINE_INIT_MOD_CALL,
    GAME_ENGINE_INIT_MOD_CALL_BYTES,
    GLOBAL_DATA,
    GLOBAL_DATA_MOD_BIG,
    GLOBAL_DATA_MOD_DIR,
    GLOBAL_DATA_VTABLE,
    MOD_MOUNT_DIRECTORY,
    SUBSYSTEM_LOAD_LEGEND_FILES,
    SUBSYSTEM_REGISTER,
)
from ..asm import JE, JNE, Asm
from ..patcher import Patch
from ..utils import allocate_section, apply_byte_patch, find_section, va_to_offset

__all__ = [
    "ANCHORS",
    "EMPTY_STRING",
    "GLOBAL_DATA_ARGS",
    "GLOBAL_DATA_CALL",
    "GLOBAL_DATA_CALL_ORIGINAL",
    "GLOBAL_DATA_CALL_TARGET",
    "GLOBAL_DATA_CLEANUP",
    "MOD_CALL",
    "MOD_CALL_ORIGINAL",
    "MOD_CALL_TARGET",
    "MOD_HANDLER_GUARD",
    "MOD_MOUNT_BLOCK",
    "MOD_MOUNT_BLOCK_END",
    "MOD_MOUNT_BLOCK_ORIGINAL",
    "MOD_MOUNT_SKIP",
    "MOD_TABLE_NAME",
    "MOD_TABLE_ROW",
    "SECTION_NAME",
    "SITES",
    "SUBSYSTEM_INIT_GLOBAL_DATA",
    "ModLoadOrderPatch",
    "build_code",
]

SECTION_NAME = ".modord"  # 7 chars: the PE name field is 8 bytes and truncates silently

# IMAGE_SCN_CNT_CODE | MEM_EXECUTE | MEM_READ - the cave is pure code and is never written.
_CHARACTERISTICS = 0x20 | 0x20000000 | 0x40000000

#: The `call` that registers `TheWritableGlobalData`, and its stock bytes. Repointed into the cave.
GLOBAL_DATA_CALL = GAME_ENGINE_INIT_GLOBAL_DATA_CALL
GLOBAL_DATA_CALL_ORIGINAL = GAME_ENGINE_INIT_GLOBAL_DATA_CALL_BYTES

#: Where :data:`GLOBAL_DATA_CALL_ORIGINAL` actually goes, decoded from its own displacement rather
#: than written down, so "the site this patch repoints is the subsystem registration" is derived
#: and can be asserted instead of trusted. It is also where the cave tail-jumps.
GLOBAL_DATA_CALL_TARGET = (
    GLOBAL_DATA_CALL + 5 + struct.unpack("<i", GLOBAL_DATA_CALL_ORIGINAL[1:5])[0]
)

#: `GameEngine::init`'s own argument setup for that call, ending exactly at
#: :data:`GLOBAL_DATA_CALL`. Anchored, not edited: it fixes the order the seven arguments are
#: pushed in, which is what makes ``[esp+0x18]`` inside the cave the `GlobalData` object being
#: registered and not something else.
GLOBAL_DATA_ARGS = 0x0063AF86
GLOBAL_DATA_ARGS_BYTES = bytes.fromhex(
    "5353535350518965e88bcc6888f2bf00c645fc07e841c5dfff686443de00"
)

#: What follows the call: `add esp, 0x1c` - seven dwords, so the callee cleans nothing and the cave
#: may tail-jump to it with the stack exactly as it found it - and the two pushes that fix `argc`
#: at ``[ebp+8]`` and `argv` at ``[ebp+0x0c]``, which is where the cave reads them from.
GLOBAL_DATA_CLEANUP = 0x0063AFA9
GLOBAL_DATA_CLEANUP_BYTES = bytes.fromhex("83c41cff750cff7508")

#: `GlobalData`'s vtable slot ``+8``. This is the whole reason the registration is a problem: the
#: slot holds the legend-driven INI loader, so registering the subsystem reads `GameData.ini`.
SUBSYSTEM_INIT_GLOBAL_DATA = GLOBAL_DATA_VTABLE + 8

#: The `call` to `COMMAND_LINE_PARSE_AND_MOUNT_MODS` at the stock site. Anchored, never edited: it
#: is what keeps the switches parsed *after* `GameData.ini`, and leaving it alone is what lets
#: `headless` point that function at its own extended table without this patch stranding it.
MOD_CALL = GAME_ENGINE_INIT_MOD_CALL
MOD_CALL_ORIGINAL = GAME_ENGINE_INIT_MOD_CALL_BYTES
MOD_CALL_TARGET = MOD_CALL + 5 + struct.unpack("<i", MOD_CALL_ORIGINAL[1:5])[0]

#: The mount half of `COMMAND_LINE_PARSE_AND_MOUNT_MODS`: from the first read of `GLOBAL_DATA`
#: through the `pop ecx` that cleans the directory mount, ending at :data:`MOD_MOUNT_BLOCK_END` -
#: which is the tail the stock function still has to run, so the jump goes there and not to its
#: `ret`. The cave transcribes this block; the patch replaces its first eight bytes with a stack
#: cleanup and that jump.
#:
#: **The cleanup is why the replacement is not just a jump.** `add esp, 0x0c` sits *twelve* bytes
#: into the block, at ``0x007BAA67``, and it is not the mount's: it is the *parse's*, scheduled
#: into the middle of the block by the compiler. Jumping from the block's first instruction
#: straight to its end therefore drops it, and `COMMAND_LINE_PARSE_AND_MOUNT_MODS` runs the rest
#: of itself twelve bytes out of balance - its epilogue pops the three parse arguments as if they
#: were the `ebx`/`esi`/`edi` it saved on entry, and returns to whatever `GameEngine::init` was
#: holding in `edi`, which is the INI load type ``1``. So :data:`MOD_MOUNT_SKIP` performs that
#: cleanup itself before it jumps. The cave emits its own copy for its own parse, separately.
MOD_MOUNT_BLOCK = 0x007BAA5B
MOD_MOUNT_BLOCK_END = 0x007BAABE
MOD_MOUNT_BLOCK_ORIGINAL = bytes.fromhex(
    "8b356443de0081c63c0d000083c40c8bcee8f373c4ff84c0bf3f0cbd0075198b3685f68d460875028bc7"
    "8b0da4c9de008b116a0150ff52148b356443de0081c6380d00008bcee8be73c4ff84c075148b0685c074"
    "0583c008eb028bc750e85698250059"
)

#: What the eight bytes at :data:`MOD_MOUNT_BLOCK` become: the parse's `add esp, 0x0c`, which the
#: block would otherwise have run twelve bytes in, and then a near jump to
#: :data:`MOD_MOUNT_BLOCK_END`. Eight bytes into a block of ninety-nine, so there is room.
MOD_MOUNT_SKIP = (
    b"\x83\xc4\x0c"  # add esp, 0x0c - the parse's cleanup, and the only part of the block kept
    + b"\xe9"
    + struct.pack("<i", MOD_MOUNT_BLOCK_END - (MOD_MOUNT_BLOCK + 8))
)

#: The `-mod` handler's opening: the `TheWritableGlobalData` null guard that makes the handler a
#: silent no-op while the global is not published - the whole reason the cave publishes it before
#: parsing - and the unconditional raise of `MOD_PREFER_LOCAL_FLAG` beside it.
MOD_HANDLER_GUARD = 0x007BADC6
MOD_HANDLER_GUARD_BYTES = bytes.fromhex("833d6443de0000535657c60590c4de00010f845d010000837d0c01")

#: The `-mod` row of the startup table, and the string it names. Anchored because the cave parses
#: that table by address: if `-mod` were not a row of it, the early parse would find nothing and
#: the patch would apply, verify and change nothing.
MOD_TABLE_ROW = COMMAND_LINE_STARTUP_TABLE + 8
MOD_TABLE_ROW_BYTES = bytes.fromhex("cc5ec300b9ad7b00")
MOD_TABLE_NAME = 0x00C35ECC
MOD_TABLE_NAME_BYTES = b"-mod\x00"

#: The first bytes of the three routines the cave calls. Anchoring them is how a build whose layout
#: moved fails at `apply` rather than on a wild call from inside the cave.
ASCII_STRING_IS_EMPTY_BYTES = bytes.fromhex("8b0185c0740a6683780400740333c0c333c040c3")
MOD_MOUNT_DIRECTORY_BYTES = bytes.fromhex(
    "56ff742408be98c4de0056e8f38b020059598b0da4c9de006a01684031c900c60590c4de00018b0156ff50205ec3"
)
COMMAND_LINE_PARSE_BYTES = bytes.fromhex("558bec83ec0c5733ff47")

#: The engine's empty `AsciiString`, which the stock mount substitutes when a path field has no
#: data block. Unreachable behind `AsciiString::isEmpty`, and reproduced anyway so the cave is a
#: transcription of the block it replaces rather than an edited one.
EMPTY_STRING = 0x00BD0C3F

#: The first bytes at every address the cave calls or the patch reasons from, as a `{va: bytes}`
#: map. The two rewritten sites are asserted by `apply_byte_patch`; these are the argument setup
#: that fixes what ``[esp+0x18]`` is, the cleanup that fixes `argc`/`argv`, the vtable slot that
#: makes the registration an INI load, the stock command-line call the patch leaves in place, the
#: `-mod` table row and handler, and the three routines the cave calls.
ANCHORS = {
    GLOBAL_DATA_ARGS: GLOBAL_DATA_ARGS_BYTES,
    GLOBAL_DATA_CLEANUP: GLOBAL_DATA_CLEANUP_BYTES,
    SUBSYSTEM_INIT_GLOBAL_DATA: struct.pack("<I", SUBSYSTEM_LOAD_LEGEND_FILES),
    MOD_CALL: MOD_CALL_ORIGINAL,
    MOD_HANDLER_GUARD: MOD_HANDLER_GUARD_BYTES,
    MOD_TABLE_ROW: MOD_TABLE_ROW_BYTES,
    MOD_TABLE_NAME: MOD_TABLE_NAME_BYTES,
    ASCII_STRING_IS_EMPTY: ASCII_STRING_IS_EMPTY_BYTES,
    MOD_MOUNT_DIRECTORY: MOD_MOUNT_DIRECTORY_BYTES,
    COMMAND_LINE_PARSE: COMMAND_LINE_PARSE_BYTES,
}

#: The two sites the patch rewrites, each with the bytes it expects to find there.
SITES = {
    GLOBAL_DATA_CALL: GLOBAL_DATA_CALL_ORIGINAL,
    MOD_MOUNT_BLOCK: MOD_MOUNT_BLOCK_ORIGINAL[: len(MOD_MOUNT_SKIP)],
}


def _parse_startup_switches(a: Asm) -> None:
    """Emit `COMMAND_LINE_PARSE(count, argc, argv)` over the stock table, and clean up after it.

    The table goes in `ebx`, which is how the engine's own caller passes it. `argc` and `argv` come
    from `GameEngine::init`'s frame, which is still live at the call site the cave replaces.
    """
    a.emit(0xBB, struct.pack("<I", COMMAND_LINE_STARTUP_TABLE))  # mov  ebx, <startup table>
    a.emit(0xFF, 0x75, 0x0C)  # push [ebp+0x0c]  ; argv
    a.emit(0xFF, 0x75, 0x08)  # push [ebp+0x08]  ; argc
    a.emit(0x6A, COMMAND_LINE_STARTUP_TABLE_COUNT)  # push <entry count>
    a.call_absolute(COMMAND_LINE_PARSE)
    a.emit(0x83, 0xC4, 0x0C)  # add  esp, 0x0c


def _mount(a: Asm) -> None:
    """Emit the mount, transcribed from :data:`MOD_MOUNT_BLOCK`.

    Two path fields, each guarded by `AsciiString::isEmpty` on the field itself: `m_modBIG` goes to
    `TheArchiveFileSystem`'s load-archive slot, `m_modDir` to `MOD_MOUNT_DIRECTORY`, which is what
    raises `MOD_PREFER_LOCAL_FLAG` and fills `MOD_DIRECTORY`. Both re-read `GLOBAL_DATA` rather
    than keeping a pointer across the calls, as the original does.
    """
    a.emit(0xBF, struct.pack("<I", EMPTY_STRING))  # mov  edi, <"">

    a.emit(0x8B, 0x35, struct.pack("<I", GLOBAL_DATA))  # mov  esi, [GLOBAL_DATA]
    a.emit(0x81, 0xC6, struct.pack("<I", GLOBAL_DATA_MOD_BIG))  # add  esi, 0xd3c  ; &m_modBIG
    a.emit(0x8B, 0xCE)  # mov  ecx, esi
    a.call_absolute(ASCII_STRING_IS_EMPTY)
    a.emit(0x84, 0xC0)  # test al, al
    a.jcc(JNE, "directory")  # no archive named
    a.emit(0x8B, 0x36)  # mov  esi, [esi]   ; the string's data block
    a.emit(0x85, 0xF6)  # test esi, esi
    a.emit(0x8D, 0x46, 0x08)  # lea  eax, [esi+8] ; -> its chars
    a.jcc_short(JNE, "archive_chars")
    a.emit(0x8B, 0xC7)  # mov  eax, edi
    a.label("archive_chars")
    a.emit(0x8B, 0x0D, struct.pack("<I", ARCHIVE_FILE_SYSTEM))  # mov ecx, [TheArchiveFileSystem]
    a.emit(0x8B, 0x11)  # mov  edx, [ecx]
    a.emit(0x6A, 0x01)  # push 1
    a.emit(0x50)  # push eax
    a.emit(0xFF, 0x52, ARCHIVE_FILE_SYSTEM_LOAD_ARCHIVE_SLOT)  # call [edx+0x14]

    a.label("directory")
    a.emit(0x8B, 0x35, struct.pack("<I", GLOBAL_DATA))  # mov  esi, [GLOBAL_DATA]
    a.emit(0x81, 0xC6, struct.pack("<I", GLOBAL_DATA_MOD_DIR))  # add  esi, 0xd38  ; &m_modDir
    a.emit(0x8B, 0xCE)  # mov  ecx, esi
    a.call_absolute(ASCII_STRING_IS_EMPTY)
    a.emit(0x84, 0xC0)  # test al, al
    a.jcc(JNE, "done")  # no directory named
    a.emit(0x8B, 0x06)  # mov  eax, [esi]
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc_short(JE, "directory_empty")
    a.emit(0x83, 0xC0, 0x08)  # add  eax, 8
    a.jmp_short("directory_chars")
    a.label("directory_empty")
    a.emit(0x8B, 0xC7)  # mov  eax, edi
    a.label("directory_chars")
    a.emit(0x50)  # push eax
    a.call_absolute(MOD_MOUNT_DIRECTORY)
    a.emit(0x59)  # pop  ecx


def build_code(base_va: int) -> bytes:
    """The ``.modord`` cave: publish, parse, mount, then fall into the registration.

    Entered by the repointed `call` at :data:`GLOBAL_DATA_CALL` in place of
    :data:`GLOBAL_DATA_CALL_TARGET`, so it is reached with that function's seven arguments and its
    return address on the stack, and it leaves both exactly as it found them.

    `GameEngine::init` carries `ebx = 0` as its zero register and `edi = 1` as the load type it
    hands to every `INI::load` from this point on, so both come back untouched.
    """
    a = Asm(base_va)
    a.emit(0x53, 0x56, 0x57)  # push ebx / esi / edi
    a.emit(0x8B, 0x44, 0x24, 0x18)  # mov  eax, [esp+0x18]  ; the GlobalData being registered
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "done")  # the allocation failed - leave the stock path alone
    a.emit(0xA3, struct.pack("<I", GLOBAL_DATA))  # mov  [GLOBAL_DATA], eax
    _parse_startup_switches(a)
    _mount(a)
    a.label("done")
    a.emit(0x5F, 0x5E, 0x5B)  # pop  edi / esi / ebx
    a.jmp_absolute(GLOBAL_DATA_CALL_TARGET)  # the registration, with the stack as it was
    return a.finish()


class ModLoadOrderPatch(Patch):
    name = "mod-load-order"
    author = "officialNecro"
    description = (
        "Mount -mod before the first INI file is read, so a loose GameData.ini - and the macros "
        "it includes - overrides the archives the way the rest of the tree already does. Nothing "
        "new to declare: no INI change"
    )

    def apply(self, data: bytearray) -> None:
        self._check_anchors(data)
        section_va = allocate_section(data, SECTION_NAME, build_code, _CHARACTERISTICS)

        apply_byte_patch(
            data,
            self._offset(data, GLOBAL_DATA_CALL),
            GLOBAL_DATA_CALL_ORIGINAL,
            b"\xe8" + struct.pack("<i", section_va - (GLOBAL_DATA_CALL + 5)),
            "TheWritableGlobalData registration -> mod-load-order early mount",
        )
        apply_byte_patch(
            data,
            self._offset(data, MOD_MOUNT_BLOCK),
            SITES[MOD_MOUNT_BLOCK],
            MOD_MOUNT_SKIP,
            "the stock mount -> jump past it, so -mod is not mounted twice",
        )

    @staticmethod
    def _offset(data: bytes | bytearray, va: int) -> int:
        off = va_to_offset(data, va)
        if off is None:
            raise ValueError(f"{va:#010x} is not mapped - not the expected build")
        return off

    @classmethod
    def _check_anchors(cls, data: bytes | bytearray) -> None:
        for derived, expected, what in (
            (GLOBAL_DATA_CALL_TARGET, SUBSYSTEM_REGISTER, "the subsystem registration"),
            (MOD_CALL_TARGET, COMMAND_LINE_PARSE_AND_MOUNT_MODS, "the startup command line"),
        ):
            if derived != expected:
                raise ValueError(
                    f"a call this patch reasons from goes to {derived:#010x}, not {what} at "
                    f"{expected:#010x}"
                )
        for va, stock in {**SITES, **ANCHORS}.items():
            off = cls._offset(data, va)
            got = bytes(data[off : off + len(stock)])
            if got != stock:
                raise ValueError(
                    f"{va:#010x} holds {got.hex()}, expected {stock.hex()} - this build's "
                    "startup does not have the shape the cave is written against"
                )

    def verify(self, data: bytes | bytearray) -> list[str]:
        problems: list[str] = []
        located = find_section(data, SECTION_NAME)
        if located is None:
            return [f"{SECTION_NAME} section is absent"]
        section_va, section_off, _ = located

        off = va_to_offset(data, GLOBAL_DATA_CALL)
        if off is None:
            return [f"{GLOBAL_DATA_CALL:#010x} is not mapped by any section"]
        if data[off] != 0xE8:
            problems.append(f"{GLOBAL_DATA_CALL:#010x} is not a call - the hook is not installed")
        else:
            target = GLOBAL_DATA_CALL + 5 + struct.unpack_from("<i", data, off + 1)[0]
            if target != section_va:
                problems.append(f"hook calls {target:#010x}, expected {section_va:#010x}")

        off = va_to_offset(data, MOD_MOUNT_BLOCK)
        if off is None:
            return [f"{MOD_MOUNT_BLOCK:#010x} is not mapped by any section"]
        if bytes(data[off : off + len(MOD_MOUNT_SKIP)]) != MOD_MOUNT_SKIP:
            problems.append(
                f"{MOD_MOUNT_BLOCK:#010x} still mounts - the stock mount is not skipped"
            )

        code = build_code(section_va)
        if bytes(data[section_off : section_off + len(code)]) != code:
            problems.append(f"the {SECTION_NAME} cave does not hold the expected routine")
        return problems
