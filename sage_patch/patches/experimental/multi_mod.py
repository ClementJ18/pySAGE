r"""The multi-mod patch: honour every `-mod` on the command line, not just the last one.

Targets the ROTWK SAGE-engine `game.dat` build ``2.01.2614.37001``. Every address below is derived
in ``../../docs/multi-mod.md``.

**The defect.** `-mod` is a startup switch like any other: its handler
(`COMMAND_LINE_MOD_HANDLER`) resolves the argument to an absolute path, asks `_stat` whether it is
a directory or a file, and **assigns** it - `AsciiString::operator=`, at
:data:`MOD_HANDLER_STORE` - into one of two `GlobalData` fields, `GLOBAL_DATA_MOD_DIR` or
`GLOBAL_DATA_MOD_BIG`. A second `-mod` overwrites the first. `COMMAND_LINE_PARSE_AND_MOUNT_MODS`
then mounts whatever survived, so ``-mod A -mod B`` runs B alone and A is silently ignored.

The loose-file half is single-valued a second time over. `MOD_MOUNT_DIRECTORY` copies the
directory into the one global `MOD_DIRECTORY`, and the four file-system entry points that consult
it - :data:`OPEN_FILE_BLOCK`, :data:`DOES_FILE_EXIST_BLOCK`, :data:`GET_FILE_INFO_BLOCK` and
:data:`GET_FILE_LIST_BLOCK` - each format `<MOD_DIRECTORY>\<name>` once and try it once. Archives
are the exception: `TheArchiveFileSystem`'s file map is shared, entries are inserted with the
overwrite flag set (`ARCHIVE_FILE_SYSTEM_LOAD_ARCHIVE` takes it as its second argument, and
`0x00A18384` is where an existing entry is kept or replaced on it), so several mounted ``.big``\ s
already stack - **last mounted wins**.

**What this does.** Adds a ``.modmul`` cave holding a sixteen-entry table of mod paths, and makes
five edits: one that fills the table, and four that read it.

* :data:`MOD_HANDLER_STORE`, the `AsciiString::operator=` that ends the `-mod` handler, is
  repointed to a stand-in that performs that assignment unchanged and then records the path it
  just stored - tagged as an archive when the destination field was `GLOBAL_DATA_MOD_BIG` - and
  mounts it on the spot, the way the stock site would have. Recording the *destination* rather
  than the source is deliberate: it is the finished absolute path, trailing separator and all.
* The four file-system blocks are replaced by cave routines that loop the same formatting and the
  same `TheLocalFileSystem` call over every recorded directory instead of running it once.

**Precedence: the last `-mod` wins.** That is not a choice so much as the rule the archive file
system already follows, extended to loose files: mounting happens in command-line order, so a
later mod's ``.big``\ s overwrite an earlier one's map entries, and the loose search therefore runs
the table backwards - last recorded first - so both halves agree. With one `-mod` the order is a
single element either way and nothing changes.

**Mounting from the handler.** The stock mount runs a few instructions after the parse returns,
inside the same function; this one runs during it. Both sit after `FILE_SYSTEM_CREATE_CALL`, which
is where `GameEngine::init` builds `TheLocalFileSystem` and `TheArchiveFileSystem` - eight hundred
bytes before the parse is even reached - so the singletons the mount needs exist at both moments.
That call is anchored for exactly that reason.

**The stock mount still runs, and is left alone.** It re-mounts the last archive and the last
directory - the two values that survive in the `GlobalData` fields - on top of a table that has
already mounted them. Both operations are idempotent (`MOD_MOUNT_DIRECTORY` re-copies the same
path and re-inserts the same file entries; `loadArchive` overwrites entries with the same offsets)
and both re-mount in the stock relative order, archive then directory. So the stock rule that a
`-mod` **directory** outranks a `-mod` **archive** survives unchanged, and every other entry
stacks underneath in command-line order. Not rewriting that block is what lets this patch and
`mod-load-order` - which replaces it wholesale - compose in either order: neither reads or writes
a byte the other touches.

**Recording is idempotent.** A path already in the table is not appended and not re-mounted,
compared with `STRCMPI` so that two spellings of one directory count once. That matters because
`mod-load-order` makes the whole startup table parse **twice**, which runs the `-mod` handler -
and so this stand-in - twice per switch.

**The stock guard is kept.** Each file-system block is still entered through the engine's own
``cmp byte [MOD_DIRECTORY], 0``, so a run with no mod at all takes exactly the path it always did.
And when the table holds no directory the loop falls back to `MOD_DIRECTORY` itself, so a path
this patch declined to record - one longer than :data:`PATH_SIZE`, or a seventeenth `-mod` - still
gets searched the stock way rather than disappearing.

**Determinism.** Which files the engine reads now depends on the whole command line rather than
its last `-mod`, so this is simulation state: **every peer needs the same binary and the same set
of mods, in the same order**, the way a `.big` change already had to match. The patch adds no new
source of divergence of its own.

**No INI change.** Nothing new is spelled anywhere; the patch only changes how many trees the
engine reads.
"""

from __future__ import annotations

import struct

from ...addresses import (
    ARCHIVE_FILE_SYSTEM,
    ARCHIVE_FILE_SYSTEM_LOAD_ARCHIVE,
    ARCHIVE_FILE_SYSTEM_LOAD_ARCHIVE_SLOT,
    ARCHIVE_FILE_SYSTEM_VTABLE,
    ASCII_STRING_ASSIGN,
    ASCII_STRING_CHARS_OFFSET,
    ASCII_STRING_SET,
    COMMAND_LINE_MOD_HANDLER_STORE,
    COMMAND_LINE_MOD_HANDLER_STORE_BYTES,
    COMMAND_LINE_MOD_HANDLER_TARGET,
    COMMAND_LINE_MOD_HANDLER_TARGET_BYTES,
    FILE_SYSTEM_CREATE_CALL,
    FILE_SYSTEM_CREATE_CALL_BYTES,
    GLOBAL_DATA,
    GLOBAL_DATA_MOD_BIG,
    LOCAL_FILE_SYSTEM,
    LOCAL_FILE_SYSTEM_DOES_FILE_EXIST_SLOT,
    LOCAL_FILE_SYSTEM_GET_FILE_INFO_SLOT,
    LOCAL_FILE_SYSTEM_GET_FILE_LIST_SLOT,
    LOCAL_FILE_SYSTEM_OPEN_FILE_SLOT,
    MOD_DIRECTORY,
    MOD_MOUNT_DIRECTORY,
    MOD_PATH_FORMAT,
    SPRINTF_SLOT,
    STRCMPI,
    STRCPY,
    STRLEN,
)
from ...asm import JAE, JE, JNE, Asm
from ...patcher import Patch
from ...utils import allocate_section, apply_byte_patch, find_section, va_to_offset

__all__ = [
    "ANCHORS",
    "BLOCKS",
    "COUNT_OFFSET",
    "DOES_FILE_EXIST_BLOCK",
    "DOES_FILE_EXIST_BLOCK_ORIGINAL",
    "EMPTY_STRING",
    "ENTRIES_OFFSET",
    "ENTRY_STRIDE",
    "GET_FILE_INFO_BLOCK",
    "GET_FILE_INFO_BLOCK_ORIGINAL",
    "GET_FILE_LIST_BLOCK",
    "GET_FILE_LIST_BLOCK_ORIGINAL",
    "KIND_ARCHIVE",
    "KIND_DIRECTORY",
    "MAX_MODS",
    "MOD_HANDLER_STORE",
    "MOD_HANDLER_STORE_ORIGINAL",
    "MOD_HANDLER_STORE_TARGET",
    "MOD_HANDLER_TARGET",
    "OPEN_FILE_BLOCK",
    "OPEN_FILE_BLOCK_ORIGINAL",
    "PATH_SIZE",
    "SECTION_NAME",
    "SITES",
    "TABLE_SIZE",
    "MultiModPatch",
    "build_code",
    "entry_points",
    "table_va",
]

SECTION_NAME = ".modmul"  # 7 chars: the PE name field is 8 bytes and truncates silently

# IMAGE_SCN_CNT_CODE | CNT_INITIALIZED_DATA | MEM_EXECUTE | MEM_READ | MEM_WRITE. The cave carries
# both the routines and the table they fill, and the table is written at run time.
_CHARACTERISTICS = 0xE0000060

#: The engine's empty `AsciiString`, which the file system substitutes wherever a path field has
#: no data block. The cave reproduces every one of those substitutions rather than assuming a
#: string is present.
EMPTY_STRING = 0x00BD0C3F

#: How many `-mod` switches are honoured, and how long a path may be. A path that does not fit -
#: either bound - is left unrecorded rather than truncated, which degrades to the stock single-mod
#: behaviour for that entry instead of building a path that names nothing.
MAX_MODS = 16
PATH_SIZE = 0x104

#: The table's shape: a count, then `MAX_MODS` entries of ``{UnsignedInt kind; char path[]}``.
COUNT_OFFSET = 0x00
ENTRIES_OFFSET = 0x04
ENTRY_STRIDE = 4 + PATH_SIZE
TABLE_SIZE = ENTRIES_OFFSET + MAX_MODS * ENTRY_STRIDE

#: What an entry's `kind` says the path is. Directories are what the loose-file search walks;
#: archives are recorded so that they mount in command-line order and are then skipped by it.
KIND_DIRECTORY = 0
KIND_ARCHIVE = 1

#: The `AsciiString::operator=` that ends the `-mod` handler, and its stock bytes. `ecx` is the
#: `GlobalData` field being written - which is what says whether this `-mod` named a directory or
#: an archive - and the one stack argument is the path the handler built.
MOD_HANDLER_STORE = COMMAND_LINE_MOD_HANDLER_STORE
MOD_HANDLER_STORE_ORIGINAL = COMMAND_LINE_MOD_HANDLER_STORE_BYTES

#: Where :data:`MOD_HANDLER_STORE_ORIGINAL` actually goes, decoded from its own displacement so
#: that "the call this patch stands in front of is the assignment" is derived and can be asserted.
MOD_HANDLER_STORE_TARGET = (
    MOD_HANDLER_STORE + 5 + struct.unpack("<i", MOD_HANDLER_STORE_ORIGINAL[1:5])[0]
)

#: The `-mod` handler's tail, ending exactly at :data:`MOD_HANDLER_STORE`: the two field addresses
#: it picks between and the push of the path. Anchored, not edited - it is what fixes `ecx` as the
#: destination field and `[esp+4]` as the source string.
MOD_HANDLER_TARGET = COMMAND_LINE_MOD_HANDLER_TARGET
MOD_HANDLER_TARGET_BYTES = COMMAND_LINE_MOD_HANDLER_TARGET_BYTES

#: `FileSystem::openFile`'s mod branch: format ``<MOD_DIRECTORY>\<name>`` into the caller's
#: 0x200-byte buffer, ask `TheLocalFileSystem` for it, and on a hit reset the `File`'s name to the
#: logical one. Replaced by a loop over the table; `esi` carries the result out, `ebx` holds the
#: access flags and `edi` the `sprintf` the block after this one still calls.
OPEN_FILE_BLOCK = 0x00A14A06
OPEN_FILE_BLOCK_ORIGINAL = bytes.fromhex(
    "ff75088d8500feffff6898c4de00682851bf0050ffd78b0dacc9de008b0183c410"
    "ff75108d9500feffff5352ff500c8bf085f6740bff75088d4e04e8a0069fff"
)

#: `FileSystem::doesFileExist`'s mod branch. Same formatting into the same size of buffer, one
#: `TheLocalFileSystem` call, result in `al`. `edi` is the file name here and `esi` the `sprintf`.
DOES_FILE_EXIST_BLOCK = 0x00A14B43
DOES_FILE_EXIST_BLOCK_ORIGINAL = bytes.fromhex(
    "576898c4de008d8500feffff682851bf0050ffd68b0dacc9de008b0183c4108d9500feffff52ff5014"
)

#: `FileSystem::getFileInfo`'s mod branch. `ebx` is the file name, `edi` the `FileInfo` being
#: filled and `esi` the `sprintf`; the buffer is 0x104 bytes, not 0x200.
GET_FILE_INFO_BLOCK = 0x00A14C13
GET_FILE_INFO_BLOCK_ORIGINAL = bytes.fromhex(
    "536898c4de008d85fcfeffff682851bf0050ffd68b0dacc9de008b0183c410578d95fcfeffff52ff5028"
)

#: `FileSystem::getFileListInDirectory`'s mod branch - the one with no success test, because it
#: merges names into a set rather than returning the first hit, so the loop that replaces it runs
#: to the end of the table. `esi` is the empty string and `edi` the `sprintf`, both of which the
#: language branch after this one still uses.
GET_FILE_LIST_BLOCK = 0x00A14D62
GET_FILE_LIST_BLOCK_ORIGINAL = bytes.fromhex(
    "8b45088b0085c0740583c008eb05b83f0cbd00506898c4de008d85dcfeffff682851bf0050ffd7"
    "8b0383c41085c0740883c0088945f0eb07c745f03f0cbd008b45088b0085c0740583c008eb05b8"
    "3f0cbd00ff75148b0dacc9de00ff75108b11ff75f08d9ddcfeffff535650ff5218"
)

#: The guard each file-system block is entered through - ``cmp byte [MOD_DIRECTORY], 0``, the
#: `sprintf` load beside it and the branch past the block. Anchored, not edited: keeping the stock
#: guard is what makes a run with no mod at all take the stock path, and anchoring it is what
#: establishes that the block being replaced is the mod branch rather than a neighbour.
OPEN_FILE_GUARD = 0x00A149F6
OPEN_FILE_GUARD_BYTES = bytes.fromhex("803d98c4de0000578b3dc006bd007440")
DOES_FILE_EXIST_GUARD = 0x00A14B34
DOES_FILE_EXIST_GUARD_BYTES = bytes.fromhex("380598c4de00568b35c006bd007431")
GET_FILE_INFO_GUARD = 0x00A14C04
GET_FILE_INFO_GUARD_BYTES = bytes.fromhex("803d98c4de00008b35c006bd007432")
GET_FILE_LIST_GUARD = 0x00A14D53
GET_FILE_LIST_GUARD_BYTES = bytes.fromhex("803d98c4de00008b3dc006bd007472")

#: What each block runs into, which is what fixes the register its replacement has to leave the
#: answer in: `esi` for `openFile`, `al` for the two predicates, and nothing at all for the
#: listing merge.
OPEN_FILE_CONTINUATION = 0x00A14A46
OPEN_FILE_CONTINUATION_BYTES = bytes.fromhex("ff75088d8500feffff68d0acdb00")
DOES_FILE_EXIST_CONTINUATION = 0x00A14B6C
DOES_FILE_EXIST_CONTINUATION_BYTES = bytes.fromhex("84c07404b001eb2e")
GET_FILE_INFO_CONTINUATION = 0x00A14C3D
GET_FILE_INFO_CONTINUATION_BYTES = bytes.fromhex("84c07404b001eb7d")
GET_FILE_LIST_CONTINUATION = 0x00A14DD1
GET_FILE_LIST_CONTINUATION_BYTES = bytes.fromhex("8b5d0c803dd0acdb0000")

#: The first bytes of everything the cave calls or mounts through. Anchoring them is how a build
#: whose layout moved fails at `apply` rather than on a wild call from inside the cave.
ASCII_STRING_ASSIGN_BYTES = bytes.fromhex("8b4424048b0085c0568b")
ASCII_STRING_SET_BYTES = bytes.fromhex("568b74240885f6578bf9740956")
MOD_MOUNT_DIRECTORY_BYTES = bytes.fromhex("56ff742408be98c4de0056e8f38b020059598b0da4c9de00")
ARCHIVE_LOAD_ARCHIVE_BYTES = bytes.fromhex("558bec81ec2c010000566a00")
STRLEN_BYTES = bytes.fromhex("ff25d406bd00")
STRCPY_BYTES = bytes.fromhex("ff25d006bd00")
STRCMPI_BYTES = bytes.fromhex("ff251c05bd00")
MOD_PATH_FORMAT_BYTES = b"%s\\%s\x00"

#: `TheArchiveFileSystem`'s vtable slot the mount goes through, as a dword. The cave calls that
#: slot on the live object, so what makes "slot 0x14 is `loadArchive`" checkable is the slot in
#: the class's own vtable pointing at the function whose opening is anchored beside it.
ARCHIVE_LOAD_ARCHIVE_SLOT_VA = ARCHIVE_FILE_SYSTEM_VTABLE + ARCHIVE_FILE_SYSTEM_LOAD_ARCHIVE_SLOT

#: Every window the patch reads but does not rewrite, as a ``{va: bytes}`` map.
ANCHORS = {
    MOD_HANDLER_TARGET: MOD_HANDLER_TARGET_BYTES,
    FILE_SYSTEM_CREATE_CALL: FILE_SYSTEM_CREATE_CALL_BYTES,
    OPEN_FILE_GUARD: OPEN_FILE_GUARD_BYTES,
    OPEN_FILE_CONTINUATION: OPEN_FILE_CONTINUATION_BYTES,
    DOES_FILE_EXIST_GUARD: DOES_FILE_EXIST_GUARD_BYTES,
    DOES_FILE_EXIST_CONTINUATION: DOES_FILE_EXIST_CONTINUATION_BYTES,
    GET_FILE_INFO_GUARD: GET_FILE_INFO_GUARD_BYTES,
    GET_FILE_INFO_CONTINUATION: GET_FILE_INFO_CONTINUATION_BYTES,
    GET_FILE_LIST_GUARD: GET_FILE_LIST_GUARD_BYTES,
    GET_FILE_LIST_CONTINUATION: GET_FILE_LIST_CONTINUATION_BYTES,
    ASCII_STRING_ASSIGN: ASCII_STRING_ASSIGN_BYTES,
    ASCII_STRING_SET: ASCII_STRING_SET_BYTES,
    MOD_MOUNT_DIRECTORY: MOD_MOUNT_DIRECTORY_BYTES,
    ARCHIVE_LOAD_ARCHIVE_SLOT_VA: struct.pack("<I", ARCHIVE_FILE_SYSTEM_LOAD_ARCHIVE),
    ARCHIVE_FILE_SYSTEM_LOAD_ARCHIVE: ARCHIVE_LOAD_ARCHIVE_BYTES,
    STRLEN: STRLEN_BYTES,
    STRCPY: STRCPY_BYTES,
    STRCMPI: STRCMPI_BYTES,
    MOD_PATH_FORMAT: MOD_PATH_FORMAT_BYTES,
}

#: The five sites the patch rewrites, each with the bytes it expects to find there.
SITES = {
    MOD_HANDLER_STORE: MOD_HANDLER_STORE_ORIGINAL,
    OPEN_FILE_BLOCK: OPEN_FILE_BLOCK_ORIGINAL,
    DOES_FILE_EXIST_BLOCK: DOES_FILE_EXIST_BLOCK_ORIGINAL,
    GET_FILE_INFO_BLOCK: GET_FILE_INFO_BLOCK_ORIGINAL,
    GET_FILE_LIST_BLOCK: GET_FILE_LIST_BLOCK_ORIGINAL,
}

#: Each replaced block, paired with the cave routine that stands in for it. `apply` and `verify`
#: both walk this, so the two cannot disagree about which routine went where.
BLOCKS = {
    OPEN_FILE_BLOCK: ("open_file", OPEN_FILE_BLOCK_ORIGINAL),
    DOES_FILE_EXIST_BLOCK: ("does_file_exist", DOES_FILE_EXIST_BLOCK_ORIGINAL),
    GET_FILE_INFO_BLOCK: ("get_file_info", GET_FILE_INFO_BLOCK_ORIGINAL),
    GET_FILE_LIST_BLOCK: ("get_file_list", GET_FILE_LIST_BLOCK_ORIGINAL),
}


def table_va(base_va: int) -> int:
    """Where the mod table sits. The table leads the section so that its address is known before
    the code is laid out - the routines address it absolutely, and a cave whose data trailed its
    code would have to be assembled twice to find out where."""
    return base_va


def _code_va(base_va: int) -> int:
    """Where the routines start: past the table."""
    return base_va + TABLE_SIZE


def _u32(value: int) -> bytes:
    return struct.pack("<I", value)


def _entry(a: Asm, index_register: int, table: int) -> None:
    """Emit ``edi = &entries[<index_register>]``, the index being a register number."""
    a.emit(0x69, 0xC0 | (7 << 3) | index_register, _u32(ENTRY_STRIDE))  # imul edi, <reg>, stride
    a.emit(0x81, 0xC7, _u32(table + ENTRIES_OFFSET))  # add  edi, <entries>


def _format_path(a: Asm, buffer_displacement: bytes, name_push: bytes) -> None:
    """Emit ``sprintf(buffer, "%s\\%s", <eax>, <name>)`` and clean up after it.

    The directory arrives in `eax` from :func:`_mod_directory`; the buffer is one of the caller's
    frame locals, which is reachable because every one of these routines is entered by a `call`
    and leaves `ebp` alone.
    """
    a.emit(name_push)  # push <the logical name>
    a.emit(0x50)  # push eax        ; the mod directory
    a.emit(0x68, _u32(MOD_PATH_FORMAT))  # push "%s\%s"
    a.emit(0x8D, 0x85, buffer_displacement)  # lea  eax, [ebp-<buffer>]
    a.emit(0x50)  # push eax
    a.emit(0xFF, 0x15, _u32(SPRINTF_SLOT))  # call [sprintf]
    a.emit(0x83, 0xC4, 0x10)  # add  esp, 0x10


def _record(a: Asm) -> None:
    """The `AsciiString::operator=` stand-in that ends the `-mod` handler.

    `__thiscall` returning `this` and cleaning one argument, because that is what it replaces. The
    assignment happens first and unchanged, so the `GlobalData` fields end up holding exactly what
    they always did; the recording then reads the *destination*, which is the finished path.
    """
    a.label("record")
    a.emit(0x53)  # push ebx
    a.emit(0x8B, 0xD9)  # mov  ebx, ecx     ; the GlobalData field
    a.emit(0xFF, 0x74, 0x24, 0x08)  # push [esp+8]      ; the source string
    a.call_absolute(ASCII_STRING_ASSIGN)  # thiscall, cleans its one argument

    a.emit(0x8B, 0x03)  # mov  eax, [ebx]   ; the string's data block
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "record_done")
    a.emit(0x83, 0xC0, ASCII_STRING_CHARS_OFFSET)  # add  eax, 8   ; -> its chars
    a.emit(0x80, 0x38, 0x00)  # cmp  byte [eax], 0
    a.jcc(JE, "record_done")

    # Which field was written is what says whether this -mod named an archive or a directory.
    a.emit(0x8B, 0x0D, _u32(GLOBAL_DATA))  # mov  ecx, [GLOBAL_DATA]
    a.emit(0x81, 0xC1, _u32(GLOBAL_DATA_MOD_BIG))  # add  ecx, 0xd3c
    a.emit(0x33, 0xD2)  # xor  edx, edx
    a.emit(0x3B, 0xD9)  # cmp  ebx, ecx
    a.emit(0x0F, 0x94, 0xC2)  # sete dl
    a.emit(0x52)  # push edx
    a.emit(0x50)  # push eax
    a.call("add_mod")
    a.emit(0x83, 0xC4, 0x08)  # add  esp, 8

    a.label("record_done")
    a.emit(0x8B, 0xC3)  # mov  eax, ebx     ; operator= returns this
    a.emit(0x5B)  # pop  ebx
    a.emit(0xC2, 0x04, 0x00)  # ret  4


def _add_mod(a: Asm, table: int) -> None:
    """``add_mod(const char *path, UnsignedInt kind)`` - record a mod, then mount it.

    Nothing happens twice: a path already in the table is neither appended nor re-mounted, which
    is what makes the stand-in safe to run through more than once. A path that does not fit the
    table - too long, or a seventeenth entry - is dropped rather than truncated, and the stock
    single-mod path still covers whichever of the two fields the handler wrote.
    """
    a.label("add_mod")
    a.emit(0x55)  # push ebp
    a.emit(0x8B, 0xEC)  # mov  ebp, esp
    a.emit(0x53, 0x56, 0x57)  # push ebx / esi / edi
    a.emit(0x8B, 0x75, 0x08)  # mov  esi, [ebp+8]   ; path

    a.emit(0x56)  # push esi
    a.call_absolute(STRLEN)
    a.emit(0x59)  # pop  ecx
    a.emit(0x3D, _u32(PATH_SIZE))  # cmp  eax, <path size>
    a.jcc(JAE, "add_mod_out")  # no room for it and its terminator

    a.emit(0x8B, 0x0D, _u32(table + COUNT_OFFSET))  # mov  ecx, [count]
    a.emit(0x33, 0xDB)  # xor  ebx, ebx

    a.label("add_mod_scan")
    a.emit(0x3B, 0xD9)  # cmp  ebx, ecx
    a.jcc(JAE, "add_mod_append")
    _entry(a, 3, table)  # edi = &entries[ebx]
    a.emit(0x56)  # push esi
    a.emit(0x8D, 0x47, 0x04)  # lea  eax, [edi+4]  ; the stored path
    a.emit(0x50)  # push eax
    a.call_absolute(STRCMPI)
    a.emit(0x83, 0xC4, 0x08)  # add  esp, 8
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "add_mod_out")  # already recorded, and so already mounted
    a.emit(0x43)  # inc  ebx
    a.emit(0x8B, 0x0D, _u32(table + COUNT_OFFSET))  # mov  ecx, [count]
    a.jmp("add_mod_scan")

    a.label("add_mod_append")
    a.emit(0x83, 0xF9, MAX_MODS)  # cmp  ecx, <max mods>
    a.jcc(JAE, "add_mod_out")
    _entry(a, 1, table)  # edi = &entries[ecx]
    a.emit(0x8B, 0x45, 0x0C)  # mov  eax, [ebp+0x0c]  ; kind
    a.emit(0x89, 0x07)  # mov  [edi], eax
    a.emit(0x56)  # push esi
    a.emit(0x8D, 0x47, 0x04)  # lea  eax, [edi+4]
    a.emit(0x50)  # push eax
    a.call_absolute(STRCPY)
    a.emit(0x83, 0xC4, 0x08)  # add  esp, 8
    a.emit(0xFF, 0x05, _u32(table + COUNT_OFFSET))  # inc  dword [count]

    # Mount it here, in command-line order, so that a later mod's archives overwrite an earlier
    # one's entries in the shared file map.
    a.emit(0x8D, 0x77, 0x04)  # lea  esi, [edi+4]   ; the stored copy
    a.emit(0x83, 0x3F, KIND_ARCHIVE)  # cmp  dword [edi], 1
    a.jcc(JE, "add_mod_archive")
    a.emit(0x56)  # push esi
    a.call_absolute(MOD_MOUNT_DIRECTORY)
    a.emit(0x59)  # pop  ecx
    a.jmp("add_mod_out")

    a.label("add_mod_archive")
    a.emit(0x8B, 0x0D, _u32(ARCHIVE_FILE_SYSTEM))  # mov  ecx, [TheArchiveFileSystem]
    a.emit(0x8B, 0x01)  # mov  eax, [ecx]
    a.emit(0x6A, 0x01)  # push 1              ; overwrite existing entries
    a.emit(0x56)  # push esi
    a.emit(0xFF, 0x50, ARCHIVE_FILE_SYSTEM_LOAD_ARCHIVE_SLOT)  # call [eax+0x14]

    a.label("add_mod_out")
    a.emit(0x5F, 0x5E, 0x5B)  # pop  edi / esi / ebx
    a.emit(0x5D)  # pop  ebp
    a.emit(0xC3)  # ret


def _mod_directory(a: Asm, table: int) -> None:
    """``mod_directory(eax = index) -> eax``: the index'th mod directory, or NULL past the end.

    Index 0 is the **last** `-mod` directory recorded, so the loose search runs in the same
    precedence order the archive file system already imposes. Archive entries are skipped; they
    are in the table only so that mounting happens in command-line order.

    With no directory recorded at all, index 0 answers `MOD_DIRECTORY` itself. That is what makes
    every one of these loops degrade to exactly the stock lookup when the table is empty - which
    is the state a path this patch declined to record leaves it in.
    """
    a.label("mod_directory")
    a.emit(0x53, 0x56)  # push ebx / esi
    a.emit(0x8B, 0xF0)  # mov  esi, eax    ; the index wanted
    a.emit(0x8B, 0x0D, _u32(table + COUNT_OFFSET))  # mov  ecx, [count]
    a.emit(0x33, 0xDB)  # xor  ebx, ebx    ; directories passed so far

    a.label("mod_directory_scan")
    a.emit(0x85, 0xC9)  # test ecx, ecx
    a.jcc(JE, "mod_directory_none")
    a.emit(0x49)  # dec  ecx         ; walk backwards, newest first
    a.emit(0x69, 0xC1, _u32(ENTRY_STRIDE))  # imul eax, ecx, stride
    a.emit(0x05, _u32(table + ENTRIES_OFFSET))  # add  eax, <entries>
    a.emit(0x83, 0x38, KIND_DIRECTORY)  # cmp  dword [eax], 0
    a.jcc(JNE, "mod_directory_scan")  # an archive - not searchable loosely
    a.emit(0x3B, 0xDE)  # cmp  ebx, esi
    a.jcc(JE, "mod_directory_hit")
    a.emit(0x43)  # inc  ebx
    a.jmp("mod_directory_scan")

    a.label("mod_directory_hit")
    a.emit(0x83, 0xC0, 0x04)  # add  eax, 4      ; -> the path
    a.jmp("mod_directory_out")

    a.label("mod_directory_none")
    a.emit(0x33, 0xC0)  # xor  eax, eax
    a.emit(0x85, 0xF6)  # test esi, esi
    a.jcc(JNE, "mod_directory_out")  # past the end of the table
    a.emit(0x85, 0xDB)  # test ebx, ebx
    a.jcc(JNE, "mod_directory_out")  # there were directories, just not this many
    a.emit(0xB8, _u32(MOD_DIRECTORY))  # mov  eax, MOD_DIRECTORY

    a.label("mod_directory_out")
    a.emit(0x5E, 0x5B)  # pop  esi / ebx
    a.emit(0xC3)  # ret


def _open_file(a: Asm) -> None:
    """`FileSystem::openFile`'s mod branch, looped.

    Leaves the `File *` in `esi` the way the block it replaces does, and resets the file's name to
    the logical one on a hit, so a caller that reads the name back gets what it asked for rather
    than the path a particular mod happened to hold it at. `ebx` (the access flags) and `edi` (the
    `sprintf` the language lookup after this still calls) are left alone.
    """
    a.label("open_file")
    a.emit(0x57)  # push edi
    a.emit(0x33, 0xF6)  # xor  esi, esi    ; the result
    a.emit(0x33, 0xFF)  # xor  edi, edi    ; the search index

    a.label("open_file_next")
    a.emit(0x8B, 0xC7)  # mov  eax, edi
    a.call("mod_directory")
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "open_file_done")
    _format_path(a, b"\x00\xfe\xff\xff", b"\xff\x75\x08")  # buffer [ebp-0x200], name [ebp+8]
    a.emit(0x8B, 0x0D, _u32(LOCAL_FILE_SYSTEM))  # mov  ecx, [TheLocalFileSystem]
    a.emit(0x8B, 0x01)  # mov  eax, [ecx]
    a.emit(0xFF, 0x75, 0x10)  # push [ebp+0x10]
    a.emit(0x53)  # push ebx           ; the access flags
    a.emit(0x8D, 0x95, b"\x00\xfe\xff\xff")  # lea  edx, [ebp-0x200]
    a.emit(0x52)  # push edx
    a.emit(0xFF, 0x50, LOCAL_FILE_SYSTEM_OPEN_FILE_SLOT)  # call [eax+0x0c]
    a.emit(0x8B, 0xF0)  # mov  esi, eax
    a.emit(0x85, 0xF6)  # test esi, esi
    a.jcc(JNE, "open_file_hit")
    a.emit(0x47)  # inc  edi
    a.jmp("open_file_next")

    a.label("open_file_hit")
    a.emit(0xFF, 0x75, 0x08)  # push [ebp+8]
    a.emit(0x8D, 0x4E, 0x04)  # lea  ecx, [esi+4]  ; the File's name
    a.call_absolute(ASCII_STRING_SET)

    a.label("open_file_done")
    a.emit(0x5F)  # pop  edi
    a.emit(0xC3)  # ret


def _does_file_exist(a: Asm) -> None:
    """`FileSystem::doesFileExist`'s mod branch, looped. Answers in `al`, as the block does."""
    a.label("does_file_exist")
    a.emit(0x53, 0x57)  # push ebx / edi
    a.emit(0x8B, 0xDF)  # mov  ebx, edi    ; the file name
    a.emit(0x33, 0xFF)  # xor  edi, edi    ; the search index

    a.label("does_file_exist_next")
    a.emit(0x8B, 0xC7)  # mov  eax, edi
    a.call("mod_directory")
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "does_file_exist_miss")
    _format_path(a, b"\x00\xfe\xff\xff", b"\x53")  # buffer [ebp-0x200], name in ebx
    a.emit(0x8B, 0x0D, _u32(LOCAL_FILE_SYSTEM))  # mov  ecx, [TheLocalFileSystem]
    a.emit(0x8B, 0x01)  # mov  eax, [ecx]
    a.emit(0x8D, 0x95, b"\x00\xfe\xff\xff")  # lea  edx, [ebp-0x200]
    a.emit(0x52)  # push edx
    a.emit(0xFF, 0x50, LOCAL_FILE_SYSTEM_DOES_FILE_EXIST_SLOT)  # call [eax+0x14]
    a.emit(0x84, 0xC0)  # test al, al
    a.jcc(JNE, "does_file_exist_hit")
    a.emit(0x47)  # inc  edi
    a.jmp("does_file_exist_next")

    a.label("does_file_exist_miss")
    a.emit(0x32, 0xC0)  # xor  al, al
    a.jmp("does_file_exist_out")
    a.label("does_file_exist_hit")
    a.emit(0xB0, 0x01)  # mov  al, 1

    a.label("does_file_exist_out")
    a.emit(0x5F, 0x5B)  # pop  edi / ebx
    a.emit(0xC3)  # ret


def _get_file_info(a: Asm) -> None:
    """`FileSystem::getFileInfo`'s mod branch, looped. Answers in `al`; the buffer is 0x104."""
    a.label("get_file_info")
    a.emit(0x56, 0x57)  # push esi / edi
    a.emit(0x8B, 0xF7)  # mov  esi, edi    ; the FileInfo being filled
    a.emit(0x33, 0xFF)  # xor  edi, edi    ; the search index

    a.label("get_file_info_next")
    a.emit(0x8B, 0xC7)  # mov  eax, edi
    a.call("mod_directory")
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "get_file_info_miss")
    _format_path(a, b"\xfc\xfe\xff\xff", b"\x53")  # buffer [ebp-0x104], name in ebx
    a.emit(0x8B, 0x0D, _u32(LOCAL_FILE_SYSTEM))  # mov  ecx, [TheLocalFileSystem]
    a.emit(0x8B, 0x01)  # mov  eax, [ecx]
    a.emit(0x56)  # push esi           ; the FileInfo
    a.emit(0x8D, 0x95, b"\xfc\xfe\xff\xff")  # lea  edx, [ebp-0x104]
    a.emit(0x52)  # push edx
    a.emit(0xFF, 0x50, LOCAL_FILE_SYSTEM_GET_FILE_INFO_SLOT)  # call [eax+0x28]
    a.emit(0x84, 0xC0)  # test al, al
    a.jcc(JNE, "get_file_info_hit")
    a.emit(0x47)  # inc  edi
    a.jmp("get_file_info_next")

    a.label("get_file_info_miss")
    a.emit(0x32, 0xC0)  # xor  al, al
    a.jmp("get_file_info_out")
    a.label("get_file_info_hit")
    a.emit(0xB0, 0x01)  # mov  al, 1

    a.label("get_file_info_out")
    a.emit(0x5F, 0x5E)  # pop  edi / esi
    a.emit(0xC3)  # ret


def _get_file_list(a: Asm) -> None:
    """`FileSystem::getFileListInDirectory`'s mod branch, looped over every recorded directory.

    The only one of the four with no early exit: the callee merges names into a set under their
    *logical* directory, so running it once per mod is how the trees union rather than shadow one
    another. `esi` (the empty string) and `edi` (the `sprintf`) both survive, because the language
    listing after this block still uses them.
    """
    a.label("get_file_list")
    a.emit(0x53, 0x57)  # push ebx / edi
    a.emit(0x33, 0xFF)  # xor  edi, edi    ; the search index

    a.label("get_file_list_next")
    a.emit(0x8B, 0xC7)  # mov  eax, edi
    a.call("mod_directory")
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "get_file_list_done")
    a.emit(0x8B, 0xD8)  # mov  ebx, eax    ; the mod directory
    a.call("list_directory_chars")
    a.emit(0x50)  # push eax         ; the logical directory
    a.emit(0x53)  # push ebx
    a.emit(0x68, _u32(MOD_PATH_FORMAT))  # push "%s\%s"
    a.emit(0x8D, 0x85, b"\xdc\xfe\xff\xff")  # lea  eax, [ebp-0x124]
    a.emit(0x50)  # push eax
    a.emit(0xFF, 0x15, _u32(SPRINTF_SLOT))  # call [sprintf]
    a.emit(0x83, 0xC4, 0x10)  # add  esp, 0x10

    a.emit(0x8B, 0x45, 0x0C)  # mov  eax, [ebp+0x0c]  ; the pattern
    a.emit(0x8B, 0x00)  # mov  eax, [eax]
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "get_file_list_no_pattern")
    a.emit(0x83, 0xC0, ASCII_STRING_CHARS_OFFSET)  # add  eax, 8
    a.jmp("get_file_list_pattern")
    a.label("get_file_list_no_pattern")
    a.emit(0xB8, _u32(EMPTY_STRING))  # mov  eax, <"">
    a.label("get_file_list_pattern")
    a.emit(0x8B, 0xD8)  # mov  ebx, eax    ; the pattern's chars

    a.call("list_directory_chars")
    a.emit(0xFF, 0x75, 0x14)  # push [ebp+0x14]
    a.emit(0x8B, 0x0D, _u32(LOCAL_FILE_SYSTEM))  # mov  ecx, [TheLocalFileSystem]
    a.emit(0xFF, 0x75, 0x10)  # push [ebp+0x10]
    a.emit(0x8B, 0x11)  # mov  edx, [ecx]
    a.emit(0x53)  # push ebx           ; the pattern
    a.emit(0x8D, 0x9D, b"\xdc\xfe\xff\xff")  # lea  ebx, [ebp-0x124]
    a.emit(0x53)  # push ebx           ; the directory to scan
    a.emit(0x68, _u32(EMPTY_STRING))  # push <"">
    a.emit(0x50)  # push eax           ; the logical directory
    a.emit(0xFF, 0x52, LOCAL_FILE_SYSTEM_GET_FILE_LIST_SLOT)  # call [edx+0x18]
    a.emit(0x47)  # inc  edi
    a.jmp("get_file_list_next")

    a.label("get_file_list_done")
    a.emit(0x5F, 0x5B)  # pop  edi / ebx
    a.emit(0xC3)  # ret

    # The listing's own directory argument, which the block reads twice per pass and which is an
    # `AsciiString *` that may have no data block.
    a.label("list_directory_chars")
    a.emit(0x8B, 0x45, 0x08)  # mov  eax, [ebp+8]
    a.emit(0x8B, 0x00)  # mov  eax, [eax]
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "list_directory_chars_empty")
    a.emit(0x83, 0xC0, ASCII_STRING_CHARS_OFFSET)  # add  eax, 8
    a.emit(0xC3)  # ret
    a.label("list_directory_chars_empty")
    a.emit(0xB8, _u32(EMPTY_STRING))  # mov  eax, <"">
    a.emit(0xC3)  # ret


def _layout(base_va: int) -> Asm:
    """Every cave routine, laid out and resolved, as the `Asm` that carries their labels."""
    table = table_va(base_va)
    a = Asm(_code_va(base_va))
    _record(a)
    _add_mod(a, table)
    _mod_directory(a, table)
    _open_file(a)
    _does_file_exist(a)
    _get_file_info(a)
    _get_file_list(a)
    a.finish()
    return a


def build_code(base_va: int) -> bytes:
    """The ``.modmul`` section: the zeroed mod table, then the routines that fill and read it."""
    return bytes(TABLE_SIZE) + bytes(_layout(base_va).buf)


def entry_points(base_va: int) -> dict[str, int]:
    """Each cave routine's virtual address, read off the layout that was actually emitted rather
    than counted by hand - which is the reason :mod:`sage_patch.asm` carries labels at all."""
    a = _layout(base_va)
    names = ["record", *(routine for routine, _ in BLOCKS.values())]
    return {name: a.label_va(name) for name in names}


class MultiModPatch(Patch):
    name = "multi-mod"
    author = "officialNecro"
    experimental = True
    description = (
        "Honour every -mod on the command line instead of only the last: all of them mount, and "
        "loose-file lookups search all of them, the last one given winning. Nothing new to "
        "declare: no INI change"
    )

    def apply(self, data: bytearray) -> None:
        self._check_anchors(data)
        section_va = allocate_section(data, SECTION_NAME, build_code, _CHARACTERISTICS)
        routines = entry_points(section_va)

        apply_byte_patch(
            data,
            self._offset(data, MOD_HANDLER_STORE),
            MOD_HANDLER_STORE_ORIGINAL,
            _call(MOD_HANDLER_STORE, routines["record"]),
            "the -mod handler's store -> multi-mod's recording stand-in",
        )
        for block_va, (routine, original) in BLOCKS.items():
            apply_byte_patch(
                data,
                self._offset(data, block_va),
                original,
                _call(block_va, routines[routine]) + b"\x90" * (len(original) - 5),
                f"the mod branch at {block_va:#010x} -> multi-mod's {routine} loop",
            )

    @staticmethod
    def _offset(data: bytes | bytearray, va: int) -> int:
        off = va_to_offset(data, va)
        if off is None:
            raise ValueError(f"{va:#010x} is not mapped - not the expected build")
        return off

    @classmethod
    def _check_anchors(cls, data: bytes | bytearray) -> None:
        if MOD_HANDLER_STORE_TARGET != ASCII_STRING_ASSIGN:
            raise ValueError(
                f"the -mod handler's store goes to {MOD_HANDLER_STORE_TARGET:#010x}, not "
                f"AsciiString::operator= at {ASCII_STRING_ASSIGN:#010x}"
            )
        for va, expected in {**SITES, **ANCHORS}.items():
            off = cls._offset(data, va)
            got = bytes(data[off : off + len(expected)])
            if got != expected:
                raise ValueError(
                    f"{va:#010x} holds {got.hex()}, expected {expected.hex()} - this build's "
                    "mod handling does not have the shape the cave is written against"
                )

    def verify(self, data: bytes | bytearray) -> list[str]:
        problems: list[str] = []
        located = find_section(data, SECTION_NAME)
        if located is None:
            return [f"{SECTION_NAME} section is absent"]
        section_va, section_off, _ = located
        routines = entry_points(section_va)

        sites = {MOD_HANDLER_STORE: ("record", MOD_HANDLER_STORE_ORIGINAL)}
        sites.update(BLOCKS)
        for va, (routine, original) in sites.items():
            off = va_to_offset(data, va)
            if off is None:
                return [f"{va:#010x} is not mapped by any section"]
            if data[off] != 0xE8:
                problems.append(f"{va:#010x} is not a call - the hook is not installed")
                continue
            target = va + 5 + struct.unpack_from("<i", data, off + 1)[0]
            if target != routines[routine]:
                problems.append(
                    f"{va:#010x} calls {target:#010x}, not {routine} at {routines[routine]:#010x}"
                )
            tail = bytes(data[off + 5 : off + len(original)])
            if tail != b"\x90" * (len(original) - 5):
                problems.append(f"the block at {va:#010x} is not nop-padded out: {tail.hex()}")

        code = build_code(section_va)
        if bytes(data[section_off + TABLE_SIZE : section_off + len(code)]) != code[TABLE_SIZE:]:
            problems.append(f"the {SECTION_NAME} cave does not hold the expected routines")
        return problems


def _call(from_va: int, to_va: int) -> bytes:
    """``call rel32`` sited at ``from_va``."""
    return b"\xe8" + struct.pack("<i", to_va - (from_va + 5))
