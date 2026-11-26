"""Fold a hash of the whole `game.dat` image into the frame checksum, so a peer running a modified
`game.dat` desyncs instead of playing.

Shroud state is already in the sync hash, but a client that only changes how visibility is drawn
keeps identical state and goes unnoticed. The patch moves the entry point to a stub that hashes
every section as the loader mapped it - `.text`, data and every patch's cave alike - before any
game code or loaded DLL runs, then mixes that hash into the checksum at every heartbeat. Replay
playback is exempt. Every peer needs the byte-identical binary.

The two things the loader writes before the entry point are left out: the import address tables
(each machine's DLL addresses) and the security cookie (random per run).

A later patch can run its own routine at each live heartbeat by writing its address into
`HOOK_OFF`.

Derivation: `../docs/binary-attest.md`.
"""

from __future__ import annotations

import struct
from collections.abc import Sequence

from ...addresses import (
    LOGIC_CRC_EMIT,
    LOGIC_CRC_EMIT_BYTES,
    LOGIC_CRC_EMIT_RESUME,
    LOGIC_CRC_SHROUD_XFER,
    LOGIC_CRC_SHROUD_XFER_BYTES,
    RECORDER_MODE,
    RECORDER_MODE_PLAYBACK,
    THE_RECORDER,
)
from ...asm import JAE, JB, JBE, JE, JNE, JZ, Asm
from ...patcher import Patch
from ...utils import allocate_section, apply_byte_patch, find_section, image_base, va_to_offset

__all__ = [
    "CODE_OFF",
    "EXCLUSIONS_OFF",
    "FNV_OFFSET_BASIS",
    "FNV_PRIME",
    "HASH_OFF",
    "HOOK_OFF",
    "MAX_EXCLUSIONS",
    "ORIGINAL_ENTRY_OFF",
    "READY_OFF",
    "SECTION_LEN",
    "SECTION_NAME",
    "BinaryAttestPatch",
    "build_section",
    "entry_stub_va",
    "expected_hash",
    "hash_routine_va",
    "loader_written_ranges",
]

SECTION_NAME = ".attest"

# IMAGE_SCN_CNT_CODE | MEM_EXECUTE | MEM_READ | MEM_WRITE - the stub stores its result in the
# section, and a hooked patch's address is read from it.
_CHARACTERISTICS = 0x20 | 0x20000000 | 0x40000000 | 0x80000000

READY_OFF = 0x00
HASH_OFF = 0x04
#: A routine for each live heartbeat, or 0. Written into the file by the patch that owns it, so it
#: is part of the image the stub hashes.
HOOK_OFF = 0x08
ORIGINAL_ENTRY_OFF = 0x0C
#: A count, then `MAX_EXCLUSIONS` `(start VA, end VA)` pairs the fold skips.
EXCLUSIONS_OFF = 0x10
MAX_EXCLUSIONS = 6
CODE_OFF = 0x50

SECTION_LEN = 0x200

# FNV-1a over 32-bit words. Chosen for the shape of its inner loop rather than its statistics:
# `xor eax, [esi]` + `imul eax, eax, prime` is two instructions with a carried dependency, so
# there is no table to place in the cave and no way to compensate for an edit by adjusting bytes
# elsewhere the way a plain additive sum invites.
FNV_OFFSET_BASIS = 0x811C9DC5
FNV_PRIME = 0x01000193

_MASK = 0xFFFFFFFF

_IMAGE_SCN_MEM_READ = 0x40000000
_SECTION_HEADER_SIZE = 0x28
# Optional-header offsets in a PE32 image.
_OPT_ENTRY_POINT = 16
_OPT_DATA_DIRECTORIES = 96
_DIR_IMPORT = 1
_DIR_LOAD_CONFIG = 10
# `IMAGE_LOAD_CONFIG_DIRECTORY32::SecurityCookie`.
_LOAD_CONFIG_SECURITY_COOKIE = 0x3C


def _optional_header(data: bytes | bytearray) -> int:
    return struct.unpack_from("<I", data, 0x3C)[0] + 24


def _entry_va(data: bytes | bytearray) -> int:
    return (
        image_base(data)
        + struct.unpack_from("<I", data, _optional_header(data) + _OPT_ENTRY_POINT)[0]
    )


def _section_headers(data: bytes | bytearray) -> list[tuple[int, int, int, int, int]]:
    """Every real section header, in table order: `(VA, raw offset, raw size, virtual size,
    characteristics)`. Read directly rather than through `image_sections`, which also lists the
    shared section's sub-caves - the stub walks the header table, and so must this."""
    e_lfanew = struct.unpack_from("<I", data, 0x3C)[0]
    count = struct.unpack_from("<H", data, e_lfanew + 6)[0]
    optional_size = struct.unpack_from("<H", data, e_lfanew + 0x14)[0]
    table = e_lfanew + 0x18 + optional_size
    base = image_base(data)
    headers = []
    for index in range(count):
        at = table + index * _SECTION_HEADER_SIZE
        vsize, rva, raw_size, raw_offset = struct.unpack_from("<IIII", data, at + 8)
        characteristics = struct.unpack_from("<I", data, at + 0x24)[0]
        headers.append((base + rva, raw_offset, raw_size, vsize, characteristics))
    return headers


def _directory(data: bytes | bytearray, index: int) -> tuple[int, int]:
    """`(VA, size)` of a data directory, `(0, 0)` when empty."""
    at = _optional_header(data) + _OPT_DATA_DIRECTORIES + index * 8
    rva, size = struct.unpack_from("<II", data, at)
    return (image_base(data) + rva, size) if rva and size else (0, 0)


def loader_written_ranges(data: bytes | bytearray) -> list[tuple[int, int]]:
    """The `[start, end)` VA ranges the Windows loader rewrites before the entry point runs, merged
    and dword-aligned: every import's address table (each machine resolves its own DLL addresses)
    and the security cookie (randomised when it still holds the compiler's default).

    Read from the image rather than pinned, because the hash must leave out exactly what the
    loader touches in *this* file. `game.dat` leaves its IAT data directory empty, so the tables
    are found through the import descriptors' `FirstThunk` arrays.
    """
    ranges: list[tuple[int, int]] = []
    base = image_base(data)

    imports_va, _ = _directory(data, _DIR_IMPORT)
    if imports_va:
        at = va_to_offset(data, imports_va)
        if at is None:
            raise ValueError(f"the import directory {imports_va:#010x} is not mapped")
        while True:
            name, first_thunk = struct.unpack_from("<II", data, at + 12)
            if not first_thunk and not name:
                break
            thunk_va = base + first_thunk
            thunk_at = va_to_offset(data, thunk_va)
            if thunk_at is None:
                raise ValueError(f"an import address table at {thunk_va:#010x} is not mapped")
            count = 0
            while struct.unpack_from("<I", data, thunk_at + 4 * count)[0]:
                count += 1
            # The terminator stays in: the loader leaves it zero, but it costs nothing to skip.
            ranges.append((thunk_va, thunk_va + 4 * (count + 1)))
            at += 20

    load_config_va, load_config_size = _directory(data, _DIR_LOAD_CONFIG)
    if load_config_va and load_config_size >= _LOAD_CONFIG_SECURITY_COOKIE + 4:
        at = va_to_offset(data, load_config_va)
        if at is None:
            raise ValueError(f"the load config {load_config_va:#010x} is not mapped")
        cookie = struct.unpack_from("<I", data, at + _LOAD_CONFIG_SECURITY_COOKIE)[0]
        if cookie:
            ranges.append((cookie, cookie + 4))

    merged: list[tuple[int, int]] = []
    for start, end in sorted((start & ~3, (end + 3) & ~3) for start, end in ranges):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def _fold(digest: int, blob: bytes) -> int:
    """FNV-1a over `blob` read as little-endian 32-bit words, exactly as the stub folds it."""
    for (word,) in struct.iter_unpack("<I", blob):
        digest = ((digest ^ word) * FNV_PRIME) & _MASK
    return digest


def _baked_exclusions(data: bytes | bytearray, section_off: int) -> list[tuple[int, int]]:
    count = struct.unpack_from("<I", data, section_off + EXCLUSIONS_OFF)[0]
    if count > MAX_EXCLUSIONS:
        raise ValueError(f"{SECTION_NAME} lists {count} exclusions, more than {MAX_EXCLUSIONS}")
    pairs = []
    for index in range(count):
        start, end = struct.unpack_from("<II", data, section_off + EXCLUSIONS_OFF + 4 + 8 * index)
        pairs.append((start, end))
    return pairs


def expected_hash(data: bytes | bytearray) -> int:
    """The value a patched `game.dat` will compute at runtime, recomputed from the file.

    The image carries no `.reloc` and does not set `DYNAMIC_BASE`, so every section is mapped at
    its preferred address with the file's bytes, and the only differences at the entry point are
    the ranges the stub skips. The attestation value is therefore a property of the file:
    `sage-patch attest` prints it, and `sage_verify` reads the live one out of a running process
    to check the two agree.

    Raises `ValueError` if `data` does not carry the patch, because the honest answer to "what
    will this file attest to" for an unpatched file is not a number.
    """
    located = find_section(data, SECTION_NAME)
    if located is None:
        raise ValueError(f"{SECTION_NAME} is absent - this file does not carry binary-attest")
    exclusions = _baked_exclusions(data, located[1])

    digest = FNV_OFFSET_BASIS
    for va, raw_offset, raw_size, vsize, characteristics in _section_headers(data):
        if not characteristics & _IMAGE_SCN_MEM_READ:
            continue
        end = va + (min(raw_size, vsize) & ~3)
        at = va
        for start, stop in exclusions:
            if stop <= at or start >= end:
                continue
            if start > at:
                digest = _fold(digest, bytes(data[raw_offset + at - va : raw_offset + start - va]))
            at = max(at, stop)
        if at < end:
            digest = _fold(digest, bytes(data[raw_offset + at - va : raw_offset + end - va]))
    return digest


def _build_code(base_va: int, image_base_va: int, original_entry: int) -> Asm:
    """The heartbeat hook, then the entry stub, then `hash_image`."""
    hash_slot = base_va + HASH_OFF
    hook_slot = base_va + HOOK_OFF
    count = base_va + EXCLUSIONS_OFF
    table = base_va + EXCLUSIONS_OFF + 4

    a = Asm(base_va + CODE_OFF)
    # The heartbeat, on the logic thread every `REPLAY_CRC_INTERVAL` frames. `edi` carries the
    # frame checksum and is the one register deliberately modified; the displaced
    # `mov ecx, [TheMessageStream]` is re-emitted at the tail.
    a.emit(0x50)  # push eax
    a.emit(0x51)  # push ecx
    a.emit(0x52)  # push edx
    a.emit(0x56)  # push esi
    a.emit(0x9C)  # pushfd

    # A replay being watched is exempt: there is no peer to disagree with, and mixing here would
    # make every recording from a different build read as a mismatch on playback.
    a.emit(0xA1, struct.pack("<I", THE_RECORDER))  # mov eax, [TheRecorder]
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "live")
    a.emit(0x83, 0x78, RECORDER_MODE, RECORDER_MODE_PLAYBACK)  # cmp dword [eax+0x1c], 1
    a.jcc(JE, "done")

    a.label("live")
    # Computed once, at the entry point. A stub that never ran leaves 0, which mixes nothing and
    # so disagrees with every peer whose stub did.
    a.emit(0xA1, struct.pack("<I", hash_slot))  # mov eax, [hash]
    a.emit(0x33, 0xF8)  # xor edi, eax

    a.emit(0xA1, struct.pack("<I", hook_slot))  # mov eax, [hook]
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "done")
    a.emit(0x60)  # pushad - the hooked routine may use any register
    a.emit(0xFF, 0xD0)  # call eax
    a.emit(0x61)  # popad

    a.label("done")
    a.emit(0x9D)  # popfd
    a.emit(0x5E)  # pop esi
    a.emit(0x5A)  # pop edx
    a.emit(0x59)  # pop ecx
    a.emit(0x58)  # pop eax
    a.emit(LOGIC_CRC_EMIT_BYTES)  # the displaced mov ecx, [TheMessageStream]
    a.jmp_absolute(LOGIC_CRC_EMIT_RESUME)

    # The entry point. Nothing has run yet but the loader, so memory is the file plus the ranges
    # the exclusion table names; the loader's registers and flags go on exactly as they came.
    a.label("entry")
    a.emit(0x9C)  # pushfd
    a.emit(0x60)  # pushad
    a.call("hash_image")
    a.emit(0xA3, struct.pack("<I", hash_slot))  # mov [hash], eax
    a.emit(0xC7, 0x05, struct.pack("<I", base_va + READY_OFF), struct.pack("<I", 1))
    a.emit(0x61)  # popad
    a.emit(0x9D)  # popfd
    a.jmp_absolute(original_entry)

    # `hash_image` -> eax: FNV-1a over every readable section's mapped bytes, in header-table
    # order, skipping each dword the exclusion table covers. Mirrors `expected_hash`.
    a.label("hash_image")
    a.emit(0xB8, struct.pack("<I", FNV_OFFSET_BASIS))  # mov eax, basis
    a.emit(0x8B, 0x1D, struct.pack("<I", image_base_va + 0x3C))  # mov ebx, [e_lfanew]
    a.emit(0x81, 0xC3, struct.pack("<I", image_base_va))  # add ebx, ImageBase
    a.emit(0x0F, 0xB7, 0x4B, 0x06)  # movzx ecx, word [ebx+6]  NumberOfSections
    a.emit(0x0F, 0xB7, 0x53, 0x14)  # movzx edx, word [ebx+0x14]  SizeOfOptionalHeader
    a.emit(0x8D, 0x5C, 0x13, 0x18)  # lea ebx, [ebx+edx+0x18]  first section header
    a.emit(0x85, 0xC9)  # test ecx, ecx
    a.jcc(JZ, "hashed")

    a.label("section")
    a.emit(0x51)  # push ecx
    a.emit(0xF7, 0x43, 0x24, struct.pack("<I", _IMAGE_SCN_MEM_READ))  # test [ebx+0x24], READ
    a.jcc(JZ, "next_section")
    a.emit(0x8B, 0x73, 0x0C)  # mov esi, [ebx+0xC]  VirtualAddress
    a.emit(0x81, 0xC6, struct.pack("<I", image_base_va))  # add esi, ImageBase
    a.emit(0x8B, 0x53, 0x10)  # mov edx, [ebx+0x10]  SizeOfRawData
    a.emit(0x8B, 0x4B, 0x08)  # mov ecx, [ebx+8]  VirtualSize
    a.emit(0x3B, 0xD1)  # cmp edx, ecx
    a.jcc_short(JBE, "sized")
    a.emit(0x8B, 0xD1)  # mov edx, ecx
    a.label("sized")
    a.emit(0x83, 0xE2, 0xFC)  # and edx, ~3
    a.emit(0x8D, 0x3C, 0x16)  # lea edi, [esi+edx]  end

    a.label("word")
    a.emit(0x3B, 0xF7)  # cmp esi, edi
    a.jcc(JAE, "next_section")
    a.emit(0x8B, 0x0D, struct.pack("<I", count))  # mov ecx, [count]
    a.emit(0xBA, struct.pack("<I", table))  # mov edx, table
    a.label("exclusion")
    a.emit(0x85, 0xC9)  # test ecx, ecx
    a.jcc_short(JZ, "fold")
    a.emit(0x3B, 0x32)  # cmp esi, [edx]
    a.jcc_short(JB, "next_exclusion")
    a.emit(0x3B, 0x72, 0x04)  # cmp esi, [edx+4]
    a.jcc_short(JB, "skip")
    a.label("next_exclusion")
    a.emit(0x83, 0xC2, 0x08)  # add edx, 8
    a.emit(0x49)  # dec ecx
    a.jmp_short("exclusion")
    a.label("fold")
    a.emit(0x33, 0x06)  # xor eax, [esi]
    a.emit(0x69, 0xC0, struct.pack("<I", FNV_PRIME))  # imul eax, eax, prime
    a.label("skip")
    a.emit(0x83, 0xC6, 0x04)  # add esi, 4
    a.jmp_short("word")

    a.label("next_section")
    a.emit(0x83, 0xC3, _SECTION_HEADER_SIZE)  # add ebx, 0x28
    a.emit(0x59)  # pop ecx
    a.emit(0x49)  # dec ecx
    a.jcc(JNE, "section")
    a.label("hashed")
    a.emit(0xC3)  # ret
    return a


def entry_stub_va(base_va: int) -> int:
    """Where the entry stub lands in a section based at `base_va`."""
    return _build_code(base_va, 0, 0).label_va("entry")


def hash_routine_va(base_va: int) -> int:
    """Where `hash_image` lands in a section based at `base_va`. A cdecl-clean routine taking no
    arguments and returning the hash in `eax`, which is what the live probe test calls."""
    return _build_code(base_va, 0, 0).label_va("hash_image")


def build_section(
    base_va: int,
    image_base_va: int,
    original_entry: int,
    exclusions: Sequence[tuple[int, int]],
    hook: int = 0,
) -> bytes:
    """The whole `.attest` payload: the slots, the exclusion table, then code, zero-padded to
    `SECTION_LEN`."""
    if len(exclusions) > MAX_EXCLUSIONS:
        raise ValueError(
            f"{len(exclusions)} loader-written ranges do not fit the table of {MAX_EXCLUSIONS}"
        )
    head = bytearray(CODE_OFF)
    struct.pack_into("<III", head, HOOK_OFF, hook, original_entry, len(exclusions))
    for index, (start, end) in enumerate(exclusions):
        struct.pack_into("<II", head, EXCLUSIONS_OFF + 4 + 8 * index, start, end)
    code = _build_code(base_va, image_base_va, original_entry).finish()
    room = SECTION_LEN - CODE_OFF
    if len(code) > room:
        raise ValueError(f"the attest routine is {len(code)} bytes and does not fit in {room}")
    return bytes(head) + code + bytes(room - len(code))


class BinaryAttestPatch(Patch):
    """Order: apply it after every patch that moves the entry point (`dll-load`) or adds an import,
    so the stub runs before any DLL they load can change memory and skips every table the loader
    fills. `verify` checks both."""

    name = "binary-attest"
    author = "officialNecro"
    apply_after = ("dll-load", "dll-import")
    # Confirmed in live Edain games as of 2026-11-15; the entry-point hash is also checked against
    # `expected_hash` in a real 32-bit process (docs/binary-attest.md).
    runtime_verified = "yes"
    description = (
        "Hash the whole game.dat image at its entry point and mix the hash into the frame "
        "checksum, so a peer running a modified game.dat goes out of sync instead of playing. "
        "Apply it after dll-load. No INI change; every peer needs the byte-identical binary, so "
        "ship it with the patched game.dat rather than as an option"
    )

    def apply(self, data: bytearray) -> None:
        hook_off = va_to_offset(data, LOGIC_CRC_EMIT)
        if hook_off is None:
            raise ValueError(f"{LOGIC_CRC_EMIT:#010x} is not mapped - not the expected build")
        self._check_shroud_in_crc(data)
        original_entry = _entry_va(data)
        if va_to_offset(data, original_entry) is None:
            raise ValueError(f"the entry point {original_entry:#010x} is not mapped")
        exclusions = loader_written_ranges(data)
        base = image_base(data)

        section_va = allocate_section(
            data,
            SECTION_NAME,
            lambda va: build_section(va, base, original_entry, exclusions),
            _CHARACTERISTICS,
        )
        # Six displaced bytes, five of which become the jump; the sixth is a nop so that the
        # instruction boundary at LOGIC_CRC_EMIT_RESUME is where the engine left it.
        code_va = section_va + CODE_OFF
        jump = b"\xe9" + struct.pack("<i", code_va - (LOGIC_CRC_EMIT + 5)) + b"\x90"
        apply_byte_patch(
            data,
            hook_off,
            LOGIC_CRC_EMIT_BYTES,
            jump,
            "MSG_LOGIC_CRC emitter -> binary-attest hook",
        )
        struct.pack_into(
            "<I",
            data,
            _optional_header(data) + _OPT_ENTRY_POINT,
            entry_stub_va(section_va) - base,
        )

    @staticmethod
    def _check_shroud_in_crc(data: bytes | bytearray) -> None:
        """Raise unless the CRC producer still folds `TheShroudManager` into the checksum.

        Not a site this patch edits - it is the premise the patch is *scoped* by. Attestation
        covers code, and the reason that is worth doing rather than also hashing the shroud grid
        is that the engine already hashes it. If a build stopped doing so, this patch would be
        the wrong shape for it and should fail rather than quietly cover half of what its
        documentation claims.
        """
        off = va_to_offset(data, LOGIC_CRC_SHROUD_XFER)
        if off is None:
            raise ValueError("the CRC producer is not mapped - not the expected build")
        got = bytes(data[off : off + len(LOGIC_CRC_SHROUD_XFER_BYTES)])
        if got != LOGIC_CRC_SHROUD_XFER_BYTES:
            raise ValueError(
                f"{LOGIC_CRC_SHROUD_XFER:#010x} is {got.hex()}, expected "
                f"{LOGIC_CRC_SHROUD_XFER_BYTES.hex()} (mov eax, [TheShroudManager]) - the shroud "
                "is not being folded into the frame CRC on this build"
            )

    def verify(self, data: bytes | bytearray) -> list[str]:
        problems: list[str] = []
        located = find_section(data, SECTION_NAME)
        if located is None:
            return [f"{SECTION_NAME} section is absent"]
        section_va, section_off, virtual_size = located
        if virtual_size < SECTION_LEN:
            problems.append(f"{SECTION_NAME} is {virtual_size:#x} bytes, expected {SECTION_LEN:#x}")

        off = va_to_offset(data, LOGIC_CRC_EMIT)
        if off is None:
            return [f"{LOGIC_CRC_EMIT:#010x} is not mapped by any section"]
        if data[off] != 0xE9:
            return [f"{LOGIC_CRC_EMIT:#010x} is not a jmp - hook not installed"]
        target = LOGIC_CRC_EMIT + 5 + struct.unpack_from("<i", data, off + 1)[0]
        if target != section_va + CODE_OFF:
            problems.append(f"hook jumps to {target:#010x}, expected {section_va + CODE_OFF:#010x}")
        if data[off + 5] != 0x90:
            problems.append("the sixth displaced byte is not a nop")

        # A patch that moves the entry point after this one would run its own code, and whatever
        # DLL it loads, before the image is hashed.
        stub = entry_stub_va(section_va)
        if _entry_va(data) != stub:
            problems.append(
                f"the entry point is {_entry_va(data):#010x}, not the attest stub {stub:#010x} - "
                "apply binary-attest after every patch that moves the entry point"
            )
        # A patch applied later that adds an import would have the loader write into the hashed
        # image, and each machine would attest to a different value.
        try:
            baked = _baked_exclusions(data, section_off)
            if baked != loader_written_ranges(data):
                problems.append(
                    "the loader-written ranges changed after binary-attest was applied - apply it "
                    "after every patch that adds an import"
                )
        except ValueError as exc:
            problems.append(str(exc))
            return problems

        # The cave is rebuilt from scratch and compared, which checks the hashed routine's bytes
        # as well as its presence. The hook slot is whatever a later patch wrote there.
        original_entry = struct.unpack_from("<I", data, section_off + ORIGINAL_ENTRY_OFF)[0]
        hook = struct.unpack_from("<I", data, section_off + HOOK_OFF)[0]
        expected = build_section(section_va, image_base(data), original_entry, baked, hook)
        got = bytes(data[section_off : section_off + SECTION_LEN])
        if got != expected:
            problems.append(f"{SECTION_NAME} does not hold the expected routine")

        try:
            self._check_shroud_in_crc(data)
        except ValueError as exc:
            problems.append(str(exc))
        return problems
