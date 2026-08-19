r"""`-mod` support for Worldbuilder's own startup.

**This patch targets `Worldbuilder.exe`, not `game.dat`.** See ``../docs/worldbuilder-mod.md``
for the derivation; the short version is that Worldbuilder already carries the whole `-mod`
pipeline and never reaches any of it.

`Worldbuilder.exe` links the same `Common/CommandLine.cpp` the game does, so it has the `-mod`
table entry (``0x01EA2688``), a full `parseMod` (``0x00C59880``), and
`ArchiveFileSystem::loadMods` (``0x00C5AC10``). All three hang off `GameEngine::init`
(``0x00C9B6D0``) - and Worldbuilder never constructs a `GameEngine`. Its engine vtable
``0x01EAF4E8`` appears at exactly two addresses in a live process, both of them the static vptr
stores in the constructor and destructor, so nothing enters that call graph. `CWorldBuilderApp`
brings up `GlobalData` and the file systems itself, from `WorldBuilder.cpp`, and never parses a
command line for the engine's benefit. The switch is linked but unreachable.

**What actually has to happen.** The directory half of `-mod` is one self-contained function,
``0x01682780``, which takes a path and does three things: copies it into the mod-directory buffer
at ``0x022D4820``, sets the mod-active flag at ``0x022D4818``, and enumerates ``*.BIG`` under it
recursively so each archive is mounted. The flag and buffer are what arm the loose-file lookup at
``0x01683704``, which prefixes ``<modDir>\`` to every file the engine opens and falls back to the
normal search on a miss:

```
01683704  mov al, [0x022D4818]     ; set by 0x01682780
01683716  je  ...                  ; clear -> no mod lookup at all
01683732  mov al, [0x022D4820]     ; the mod directory
01683745  push 0x01E745DC          ; "%s\%s"
01683763  call [edx+0xc]           ; LocalFileSystem::openFile
```

So calling ``0x01682780`` once, early enough, is the entire fix - loose uncompiled `data\ini\...`
overriding a shipped `.big` is behaviour the editor already has and simply never switches on.

**Where the hook goes.** Two constraints bracket it. ``0x01682780`` dereferences the archive file
system at ``0x022D507C`` and calls a virtual on it, so the file systems must already exist; and
the mod directory has to be armed before any INI is read, or the override comes too late to
matter. `CWorldBuilderApp::InitInstance` loads its first INI at ``0x0069017A``:

```
00690155  mov ecx, [ebp-0x1758]    ; <- the hook window, both branches converge here
0069015b  mov [ebp-0x1014], ecx
00690161  mov byte [ebp-4], 7
00690165  push 0
00690167  push 0
00690169  push 0x01E20A28          ; "Data\INI\Default\SubSystemLegendExpansion1.ini"
0069016e  mov edx, [ebp-0x1014]
00690174  push edx
00690175  push 0x022C9028
0069017a  call 0x004097BE          ; the first INI read
```

``0x00690155`` is the last six-byte instruction before it and there is **no call between the two**,
so whatever state holds at the INI read holds at the hook: the archive file system is necessarily
up. It is also the target of the ``jmp`` at ``0x00690149``, and the `je` at ``0x006900E1`` reaches
it through ``0x0069014B``, so both paths run the hook exactly once.

**Reading the argument.** Worldbuilder imports no `__argv`, so the cave takes `GetCommandLineA`
(IAT ``0x022F4304``) and scans it for a `-mod` token delimited by whitespace on both sides, then
copies the token after it, stripping one level of quoting. The both-sides delimiter check is not
optional: a mod living under `D:\Edain-Mod\...` puts the literal text `-Mod` inside another
argument, and only the trailing check rejects it. Paths of 128 characters or more are dropped -
see `MAX_MOD_PATH_CHARS` for the buffer that bound comes from.

**This does not fix the MFC collision.** Worldbuilder is an MFC app, and
`CCommandLineInfo::ParseParam` still claims the bare mod path as `m_strFileName` and tries to open
it as a document. Pass a map before `-mod` so the path has nowhere to land; see the doc's §4.
"""

from __future__ import annotations

import struct
from typing import TYPE_CHECKING

from ..asm import JB, JE, JNE, Asm
from ..patcher import Patch
from ..utils import allocate_section, apply_byte_patch, find_section, va_to_offset

if TYPE_CHECKING:
    import argparse

__all__ = [
    "ANCHORS",
    "HOOK_VA",
    "MAX_MOD_PATH_CHARS",
    "SECTION_NAME",
    "WorldbuilderModPatch",
    "build_section",
]

SECTION_NAME = ".wbmod"

# IMAGE_SCN_CNT_CODE | CNT_INITIALIZED_DATA | MEM_EXECUTE | MEM_READ | MEM_WRITE. Writable because
# the cave copies the parsed path into its own buffer before handing it over.
_CHARACTERISTICS = 0x20 | 0x40 | 0x20000000 | 0x40000000 | 0x80000000

#: The instruction the hook replaces, and the bytes it must still hold.
HOOK_VA = 0x00690155
_HOOK_BYTES = bytes.fromhex("8b8da8e8ffff")  # mov ecx, [ebp-0x1758]

#: ``setModDir(const char *)``: arms the mod directory and mounts every `.BIG` under it. `cdecl`,
#: one argument, caller cleans - it reads `[esp+4]` and returns with a bare `ret`.
SET_MOD_DIR = 0x01682780

#: The archive file system the callee dereferences. Null means the file systems are not up yet,
#: which the cave treats as "do nothing" rather than faulting.
ARCHIVE_FS_PTR = 0x022D507C

#: `GetCommandLineA`'s import slot.
GET_COMMAND_LINE_A = 0x022F4304

#: The cave refuses a mod path this long or longer rather than copying it. ``0x01682780`` copies
#: into its fixed buffer at ``0x022D4820`` with an unbounded byte loop, and the next global
#: anything references is ``0x022D48B8`` - only ``0x98`` bytes later - so that buffer holds at
#: most 152 bytes. 128 stays clear of it with room to spare. Over-long paths are dropped rather
#: than truncated: a truncated path names a *different* directory, which is a worse failure than
#: not arming the mod at all.
MAX_MOD_PATH_CHARS = 128

_BUF_OFF = 0
_BUF_SIZE = 0x104
_CODE_OFF = 0x110

#: Everything outside the hook window that the cave assumes about this build: the callee's
#: prologue and the two stores that make it the function this patch thinks it is, the loose-file
#: lookup it arms, and the INI read the hook must precede. A build that moved fails here rather
#: than by calling into the middle of something else.
ANCHORS = {
    SET_MOD_DIR: bytes.fromhex("8b442404ba20482d"),  # mov eax,[esp+4]; mov edx,0x22d4820
    0x016827A7: bytes.fromhex("c60518482d0201"),  # mov byte [0x22d4818], 1
    0x016827B0: bytes.fromhex("6820482d02"),  # push 0x22d4820
    0x01683704: bytes.fromhex("a018482d0255"),  # mov al, [0x22d4818]
    0x00690169: bytes.fromhex("68280ae201"),  # push "Data\INI\Default\SubSystem...ini"
    0x0069017A: bytes.fromhex("e83f96d7ff"),  # call the INI loader
}

#: PE `DllCharacteristics` bit that would let the loader rebase the image out from under the
#: absolute addresses the cave reads and calls.
_DYNAMIC_BASE = 0x0040


def _u32(value: int) -> bytes:
    return struct.pack("<I", value)


def _assemble(base_va: int) -> Asm:
    """The cave's one routine, laid out at ``base_va + _CODE_OFF``.

    Entered by `call`, so it returns with `ret` after re-running the instruction the hook
    displaced. `pushad`/`pushfd` bracket the whole body: this sits in the middle of
    `InitInstance`'s frame and must not disturb a single register or flag."""
    a = Asm(base_va + _CODE_OFF)
    buf = base_va + _BUF_OFF

    a.emit(0x60)  # pushad
    a.emit(0x9C)  # pushfd

    # Nothing to arm if the file systems are not up - the callee would fault on a null vtable.
    a.emit(0xA1, _u32(ARCHIVE_FS_PTR))  # mov eax, [ARCHIVE_FS_PTR]
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "done")

    a.emit(0xFF, 0x15, _u32(GET_COMMAND_LINE_A))  # call [GetCommandLineA]
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "done")
    a.emit(0x8B, 0xF0)  # mov esi, eax

    # Walk to the next run of whitespace. Quoted arguments are not honoured here on purpose: the
    # scan only ever has to recognise the bare token `-mod`, and treating a quoted path as several
    # whitespace-separated fragments cannot make one of those fragments look like it.
    a.label("scan")
    a.emit(0x8A, 0x06)  # mov al, [esi]
    a.emit(0x84, 0xC0)  # test al, al
    a.jcc(JE, "done")
    a.emit(0x3C, 0x20)  # cmp al, ' '
    a.jcc(JE, "at_ws")
    a.emit(0x3C, 0x09)  # cmp al, '\t'
    a.jcc(JE, "at_ws")
    a.emit(0x46)  # inc esi
    a.jmp("scan")

    # Skip the whitespace run and land on the token that follows it.
    a.label("at_ws")
    a.emit(0x46)  # inc esi
    a.emit(0x8A, 0x06)  # mov al, [esi]
    a.emit(0x3C, 0x20)  # cmp al, ' '
    a.jcc(JE, "at_ws")
    a.emit(0x3C, 0x09)  # cmp al, '\t'
    a.jcc(JE, "at_ws")
    a.emit(0x84, 0xC0)  # test al, al
    a.jcc(JE, "done")

    # Is this token exactly `-mod`, ignoring case, and delimited on the right? Every mismatch
    # rejoins the scan at the same cursor, which is still on a non-space, so the walk advances.
    a.emit(0x3C, 0x2D)  # cmp al, '-'
    a.jcc(JNE, "scan")
    for index, letter in ((0x01, 0x6D), (0x02, 0x6F), (0x03, 0x64)):  # 'm', 'o', 'd'
        a.emit(0x8A, 0x46, index)  # mov al, [esi+index]
        a.emit(0x0C, 0x20)  # or al, 0x20
        a.emit(0x3C, letter)  # cmp al, letter
        a.jcc(JNE, "scan")
    a.emit(0x8A, 0x46, 0x04)  # mov al, [esi+4]
    a.emit(0x3C, 0x20)  # cmp al, ' '
    a.jcc(JE, "found")
    a.emit(0x3C, 0x09)  # cmp al, '\t'
    a.jcc(JE, "found")
    a.jmp("scan")

    a.label("found")
    a.emit(0x83, 0xC6, 0x04)  # add esi, 4

    a.label("skip_ws")
    a.emit(0x8A, 0x06)  # mov al, [esi]
    a.emit(0x3C, 0x20)  # cmp al, ' '
    a.jcc(JE, "skip_step")
    a.emit(0x3C, 0x09)  # cmp al, '\t'
    a.jcc(JNE, "have_path")
    a.label("skip_step")
    a.emit(0x46)  # inc esi
    a.jmp("skip_ws")

    # `dl` is the terminator: a closing quote when the path is quoted, otherwise whitespace.
    a.label("have_path")
    a.emit(0x84, 0xC0)  # test al, al
    a.jcc(JE, "done")
    a.emit(0x31, 0xD2)  # xor edx, edx
    a.emit(0x3C, 0x22)  # cmp al, '"'
    a.jcc(JNE, "copy_init")
    a.emit(0x46)  # inc esi
    a.emit(0xB2, 0x22)  # mov dl, '"'

    a.label("copy_init")
    a.emit(0xBF, _u32(buf))  # mov edi, buf
    a.emit(0x31, 0xC9)  # xor ecx, ecx

    a.label("copy")
    a.emit(0x8A, 0x06)  # mov al, [esi]
    a.emit(0x84, 0xC0)  # test al, al
    a.jcc(JE, "copy_done")
    a.emit(0x84, 0xD2)  # test dl, dl
    a.jcc(JE, "copy_unquoted")
    a.emit(0x38, 0xD0)  # cmp al, dl
    a.jcc(JE, "copy_done")
    a.jmp("copy_store")

    a.label("copy_unquoted")
    a.emit(0x3C, 0x20)  # cmp al, ' '
    a.jcc(JE, "copy_done")
    a.emit(0x3C, 0x09)  # cmp al, '\t'
    a.jcc(JE, "copy_done")

    a.label("copy_store")
    a.emit(0x88, 0x07)  # mov [edi], al
    a.emit(0x47)  # inc edi
    a.emit(0x46)  # inc esi
    a.emit(0x41)  # inc ecx
    a.emit(0x81, 0xF9, _u32(MAX_MOD_PATH_CHARS))  # cmp ecx, MAX_MOD_PATH_CHARS
    a.jcc(JB, "copy")

    a.label("copy_done")
    a.emit(0xC6, 0x07, 0x00)  # mov byte [edi], 0
    a.emit(0x85, 0xC9)  # test ecx, ecx
    a.jcc(JE, "done")
    a.emit(0x81, 0xF9, _u32(MAX_MOD_PATH_CHARS))  # cmp ecx, MAX_MOD_PATH_CHARS
    a.jcc(JE, "done")  # hit the bound: refuse rather than hand over a truncated path
    a.emit(0x68, _u32(buf))  # push buf
    a.call_absolute(SET_MOD_DIR)
    a.emit(0x83, 0xC4, 0x04)  # add esp, 4

    a.label("done")
    a.emit(0x9D)  # popfd
    a.emit(0x61)  # popad
    a.emit(_HOOK_BYTES)  # the displaced mov ecx, [ebp-0x1758]
    a.emit(0xC3)  # ret

    return a


def build_section(base_va: int) -> bytes:
    """The cave: a zeroed path buffer, then the routine."""
    code = _assemble(base_va).finish()
    body = bytearray(_CODE_OFF)
    body[_BUF_OFF : _BUF_OFF + _BUF_SIZE] = b"\x00" * _BUF_SIZE
    return bytes(body) + code


class WorldbuilderModPatch(Patch):
    """Make Worldbuilder honour `-mod`, so a mod's loose files load without being packed."""

    name = "worldbuilder-mod"
    author = "officialNecro"
    description = (
        "Worldbuilder.exe (not game.dat): honour -mod <dir> during the editor's own startup, so "
        "loose uncompiled files under the mod directory override the shipped .big archives and a "
        "mod can be edited without compiling it first. Pass a map before -mod so MFC does not "
        "claim the mod path as a document to open. Point -mod at the subtree being edited rather "
        "than a whole mod: the editor dies partway through a full one, where the game does not"
    )

    def apply(self, data: bytearray) -> None:
        self._check_not_rebased(data)
        self._check_anchors(data)
        section_va = allocate_section(data, SECTION_NAME, build_section, _CHARACTERISTICS)
        off = self._offset(data, HOOK_VA)
        apply_byte_patch(
            data,
            off,
            _HOOK_BYTES,
            self._hook(section_va),
            f"InitInstance pre-INI hook @0x{HOOK_VA:08x} -> {SECTION_NAME} cave",
        )

    def verify(self, data: bytes | bytearray) -> list[str]:
        located = find_section(data, SECTION_NAME)
        if located is None:
            return [f"no {SECTION_NAME} section: the file does not carry this patch"]
        section_va, section_off, _vsize = located

        problems: list[str] = []
        expected = build_section(section_va)
        got = bytes(data[section_off : section_off + len(expected)])
        if got != expected:
            problems.append(
                f"the {SECTION_NAME} cave does not match what this patch builds for base "
                f"0x{section_va:08x}"
            )
        hook = self._hook(section_va)
        off = va_to_offset(data, HOOK_VA)
        if off is None:
            problems.append(f"0x{HOOK_VA:08x} is not mapped")
        elif bytes(data[off : off + len(hook)]) != hook:
            problems.append(
                f"the hook @0x{HOOK_VA:08x} is {bytes(data[off : off + len(hook)]).hex()}, "
                f"expected {hook.hex()}"
            )
        return problems

    @classmethod
    def detect(cls, data: bytes | bytearray) -> WorldbuilderModPatch | None:
        if find_section(data, SECTION_NAME) is None:
            return None
        patch = cls()
        return None if patch.verify(data) else patch

    @classmethod
    def add_cli_arguments(cls, parser: argparse.ArgumentParser) -> None:
        """No options: the mod directory is whatever `-mod` names at run time, which is the
        point - one patched Worldbuilder serves every mod."""

    @classmethod
    def from_cli_args(cls, args: argparse.Namespace) -> WorldbuilderModPatch:
        return cls()

    @staticmethod
    def _hook(section_va: int) -> bytes:
        """`call` into the cave, `nop`-padded to the width of the instruction it replaces. The
        padding matters: a leftover byte of the window would be decoded on the way back in."""
        target = section_va + _CODE_OFF
        call = b"\xe8" + struct.pack("<i", target - (HOOK_VA + 5))
        return call + b"\x90" * (len(_HOOK_BYTES) - len(call))

    @staticmethod
    def _offset(data: bytes | bytearray, va: int) -> int:
        off = va_to_offset(data, va)
        if off is None:
            raise ValueError(f"0x{va:08x} is not mapped - not the expected build")
        return off

    @staticmethod
    def _check_anchors(data: bytes | bytearray) -> None:
        for va, expected in ANCHORS.items():
            off = va_to_offset(data, va)
            if off is None:
                raise ValueError(f"0x{va:08x} is not mapped - not the expected build")
            got = bytes(data[off : off + len(expected)])
            if got != expected:
                raise ValueError(
                    f"0x{va:08x} holds {got.hex()}, expected {expected.hex()} - this build's "
                    "startup is not the one the cave was written against, so the hook would "
                    "arm the mod directory at the wrong moment or call the wrong function"
                )

    @staticmethod
    def _check_not_rebased(data: bytes | bytearray) -> None:
        """Raise if the loader could move the image. The cave reads two globals and calls one
        function by absolute address, none of which carry base-relocation entries."""
        e_lfanew = struct.unpack_from("<I", data, 0x3C)[0]
        dll_characteristics = struct.unpack_from("<H", data, e_lfanew + 24 + 70)[0]
        if dll_characteristics & _DYNAMIC_BASE:
            raise ValueError(
                "the image opts in to ASLR (DllCharacteristics DYNAMIC_BASE), so the absolute "
                "addresses this cave reads and calls would move under it - refusing rather than "
                "writing a hook that faults when the image is rebased"
            )
